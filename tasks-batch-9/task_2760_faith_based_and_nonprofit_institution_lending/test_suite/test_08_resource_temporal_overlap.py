"""
Queue A — §1.8 rule ``resource_temporal_overlap``.

The two instances carry opposite endpoint conventions on purpose: a giving
period's interval is closed at both ends, so touching collides, while a lien
occupation is half-open and buffered, so touching the buffered end is legal.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.assertions import assert_fields, assert_iso_equal, assert_nulls
from test_helpers.factories import (
    assignment_payload,
    giving_period_payload,
    release_payload,
)
from test_helpers.fixtures import (
    build_authorized_authorization,
    build_collateral_asset,
    build_draft_application,
    build_giving_period,
    build_institution,
)
from test_helpers.test_users import CREDIT_ANALYST

INCUMBENT = {
    "period_label": "2025Q1",
    "period_start": "2025-01-01T00:00:00Z",
    "period_end": "2025-03-31T00:00:00Z",
}
TOUCHING_START = {
    "period_label": "2025Q2-TOUCHING-START",
    "period_start": "2025-03-31T00:00:00Z",
    "period_end": "2025-06-30T00:00:00Z",
    "total_contributions_cents": 62000000,
    "operating_expense_cents": 40999950,
    "member_household_count": 510,
}
TOUCHING_END = {
    "period_label": "2024Q4-TOUCHING-END",
    "period_start": "2024-10-01T00:00:00Z",
    "period_end": "2025-01-01T00:00:00Z",
    "total_contributions_cents": 58000000,
    "operating_expense_cents": 39000000,
    "member_household_count": 495,
}
ADJACENT_AFTER = dict(TOUCHING_START, period_label="2025Q2", period_start="2025-04-01T00:00:00Z")
ADJACENT_BEFORE = dict(TOUCHING_END, period_label="2024Q4", period_end="2024-12-31T00:00:00Z")
SCHOOL = {
    "legal_name": "Trinity Lutheran School",
    "institution_type": "SCHOOL",
    "denomination_code": "ELCA",
    "bylaws_borrowing_cap_cents": 300000000,
    "bylaws_quorum_pct": 0.5000,
    "community_program_count": 1,
    "endowment_market_value_cents": 0,
}
SCHOOL_PERIOD = {
    "total_contributions_cents": 20000000,
    "restricted_contributions_cents": 2000000,
    "donor_restricted_endowment_draw_cents": 0,
    "operating_expense_cents": 15000000,
    "member_household_count": 120,
}


def _file_period(api, institution_id, spec):
    return api.create_giving_period(giving_period_payload(institution_id, **spec), CREDIT_ANALYST)


def _period_count(api, institution_id):
    return get_success_data(api.get_institution(institution_id, CREDIT_ANALYST))["period_count"]


def test_a_giving_period_touching_an_existing_endpoint_is_refused(api):
    """
    Sharing a single instant with an incumbent period is an overlap on a closed interval.

    PRD §3.1: "Because a period's interval is closed at both ends, two periods of the
    same institution collide if they share even a single touching endpoint: a new period
    is refused with `ERR_GIVING_PERIOD_OVERLAP` whenever its start falls at or before an
    existing period's end and that existing period's start falls at or before the new
    period's end."

    PRD §2.10: "The new giving period's closed interval shares no instant with any
    existing period of the same institution — `ERR_GIVING_PERIOD_OVERLAP` (HTTP 409), on
    giving-period creation."

    Design: Difficulty/resource_temporal_overlap/giving_period_closed_interval_touching_endpoint_collides
    """
    institution = build_institution(api)
    build_giving_period(api, institution["id"], INCUMBENT)

    validate_error(
        _file_period(api, institution["id"], TOUCHING_START), "ERR_GIVING_PERIOD_OVERLAP", 409
    )
    validate_error(
        _file_period(api, institution["id"], TOUCHING_END), "ERR_GIVING_PERIOD_OVERLAP", 409
    )

    assert _period_count(api, institution["id"]) == 1


def test_one_day_gaps_are_accepted_and_the_overlap_check_is_per_institution(api):
    """
    A single day of clearance is enough, and a second institution may hold the same window.

    PRD §3.1: "A period carries the `institution_id` it belongs to, a human
    `period_label` such as "2025Q3", and a **closed** interval delimited by
    `period_start` and `period_end` — both inclusive, both ISO 8601 UTC instants at
    midnight."

    PRD §3.1: "`unrestricted_contributions_cents` is total contributions reduced by
    restricted contributions and reduced again by the donor-restricted endowment draw,
    with the result floored at zero if those two deductions together would exceed the
    total."

    PRD §3.1: "`net_available_for_debt_service_cents` is that unrestricted figure reduced
    by the period's operating expense, again floored at zero, so a period that spent more
    than it took in unrestricted giving contributes nothing rather than a negative
    amount."

    Design: Difficulty/resource_temporal_overlap/giving_period_closed_interval_touching_endpoint_collides
    """
    institution_a = build_institution(api)
    institution_b = build_institution(api, **SCHOOL)
    build_giving_period(api, institution_a["id"], INCUMBENT)

    after = get_success_data(_file_period(api, institution_a["id"], ADJACENT_AFTER), 201)
    before = get_success_data(_file_period(api, institution_a["id"], ADJACENT_BEFORE), 201)
    twin = get_success_data(
        _file_period(api, institution_b["id"], dict(INCUMBENT, **SCHOOL_PERIOD)), 201
    )

    assert_fields(
        after, unrestricted_contributions_cents=52000000, net_available_for_debt_service_cents=11000050
    )
    assert_fields(before, period_label="2024Q4")
    assert_fields(twin, period_label="2025Q1", unrestricted_contributions_cents=18000000)
    assert _period_count(api, institution_a["id"]) == 3
    assert _period_count(api, institution_b["id"]) == 1


def _released_asset(api):
    """
    One sanctuary asset assigned first lien to application 1 for [2026-08-01, 2026-09-01)
    and then released, so the occupation survives only in ``lien_history``.
    """
    institution = build_institution(api)
    authorization = build_authorized_authorization(api, institution["id"])
    app_one = build_draft_application(
        api,
        institution["id"],
        authorization["id"],
        purpose="SANCTUARY_CONSTRUCTION",
        requested_amount_cents=200000000,
        term_months=240,
        interest_rate_bps=625,
    )
    app_two = build_draft_application(
        api,
        institution["id"],
        authorization["id"],
        purpose="REFINANCE",
        requested_amount_cents=150000000,
        term_months=180,
        interest_rate_bps=650,
    )
    asset = build_collateral_asset(api, institution["id"])
    get_success_data(
        api.assign_collateral_asset(
            asset["id"],
            assignment_payload(
                app_one["id"],
                lien_effective_from="2026-08-01T00:00:00Z",
                lien_effective_to="2026-09-01T00:00:00Z",
            ),
            CREDIT_ANALYST,
        )
    )
    released = get_success_data(
        api.release_collateral_asset(
            asset["id"],
            release_payload(release_note="Application 1 withdrawn; lien released"),
            CREDIT_ANALYST,
        )
    )
    return asset, app_one, app_two, released


def _attempt(api, asset_id, application_id, start, end):
    return api.assign_collateral_asset(
        asset_id,
        assignment_payload(application_id, lien_effective_from=start, lien_effective_to=end),
        CREDIT_ANALYST,
    )


def test_a_released_lien_keeps_blocking_until_the_thirty_day_buffer_expires(api):
    """
    The unbuffered end and a day inside the buffer are both refused.

    PRD §3.4: "So each prior occupation of the same asset — the current assignment if
    any, and every entry already recorded in `lien_history` — is compared after extending
    its end by 30 days."

    PRD §3.4: "The new occupation is refused with `ERR_COLLATERAL_LIEN_WINDOW_CONFLICT`
    whenever the new window's start falls strictly before that extended end **and** the
    prior occupation's start falls strictly before the new window's end."

    PRD §3.4: "The release appends the occupation just ended to `lien_history` as a record
    carrying `loan_application_id`, `lien_position`, `effective_from`, `effective_to` and
    `released_at`, with the list held in ascending `released_at` order and never rewritten
    once appended."

    Design: Difficulty/resource_temporal_overlap/collateral_lien_window_half_open_with_thirty_day_buffer_conflicts
    """
    asset, app_one, app_two, released = _released_asset(api)
    assert_nulls(
        released,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert len(released["lien_history"]) == 1
    entry = released["lien_history"][0]
    assert_fields(entry, loan_application_id=app_one["id"], lien_position=1)
    assert_iso_equal(entry["effective_from"], "2026-08-01T00:00:00Z", "effective_from")
    assert_iso_equal(entry["effective_to"], "2026-09-01T00:00:00Z", "effective_to")
    assert_iso_equal(entry["released_at"], "2026-08-01T00:00:00Z", "released_at")

    validate_error(
        _attempt(api, asset["id"], app_two["id"], "2026-09-01T00:00:00Z", "2031-09-01T00:00:00Z"),
        "ERR_COLLATERAL_LIEN_WINDOW_CONFLICT",
        409,
    )
    validate_error(
        _attempt(api, asset["id"], app_two["id"], "2026-09-30T00:00:00Z", "2031-09-30T00:00:00Z"),
        "ERR_COLLATERAL_LIEN_WINDOW_CONFLICT",
        409,
    )

    after = get_success_data(api.get_collateral_asset(asset["id"], CREDIT_ANALYST))
    assert len(after["lien_history"]) == 1
    assert_nulls(after, "assigned_loan_application_id", "lien_position")


def test_a_window_starting_exactly_at_the_buffered_end_is_accepted(api):
    """
    Thirty days after the prior occupation ended, the half-open window no longer conflicts.

    PRD §3.4: "A window that begins exactly 30 days after a prior occupation ended is
    therefore acceptable; one that begins 29 days after is not."

    PRD §3.4: "The payload names the `loan_application_id` taking the lien, the
    `lien_position` the lender will occupy, and the occupation window as
    `lien_effective_from` and `lien_effective_to` — a **half-open** interval, inclusive of
    its start and exclusive of its end."

    Design: Difficulty/resource_temporal_overlap/collateral_lien_window_half_open_with_thirty_day_buffer_conflicts
    """
    asset, _app_one, app_two, _released = _released_asset(api)
    validate_error(
        _attempt(api, asset["id"], app_two["id"], "2026-09-30T00:00:00Z", "2031-09-30T00:00:00Z"),
        "ERR_COLLATERAL_LIEN_WINDOW_CONFLICT",
        409,
    )

    reassigned = get_success_data(
        _attempt(api, asset["id"], app_two["id"], "2026-10-01T00:00:00Z", "2031-10-01T00:00:00Z")
    )

    assert_fields(
        reassigned,
        assigned_loan_application_id=app_two["id"],
        lien_position=1,
        lending_value_cents=225000000,
    )
    assert_iso_equal(
        reassigned["lien_effective_from"], "2026-10-01T00:00:00Z", "lien_effective_from"
    )
    assert len(reassigned["lien_history"]) == 1
