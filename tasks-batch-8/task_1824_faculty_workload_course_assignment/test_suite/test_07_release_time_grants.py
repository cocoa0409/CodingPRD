"""Release-time grants: buyout variants, closed-interval overlap, approve/revoke."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_grant_payload,
    get_load_sheet,
    make_faculty,
    make_term,
    setup_grant,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]


def test_release_buyout_salary_prorate_vs_flat_rate__prorate(api):
    """PRD §3.8: "For a `RESEARCH_BUYOUT` grant, the salary-prorate variant applies:
    the faculty member's `base_salary_cents` is multiplied by `credits_released` and
    divided by the product of the faculty member's `base_load_credits` and two — two
    terms per year — with the result rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/release_buyout_salary_prorate_vs_flat_rate
    """
    term = make_term()
    faculty = make_faculty(base_salary_cents=9_000_000, base_load_credits=12)
    grant = setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="RESEARCH_BUYOUT", credits_released=3,
        start_date="2026-08-24", end_date="2026-10-16",
    )
    # round_half_up(9_000_000 * 3 / (12 * 2)) = 1_125_000
    assert grant["buyout_value_cents"] == 1_125_000


def test_release_buyout_salary_prorate_vs_flat_rate__flat(api):
    """PRD §3.8: "For an `ADMINISTRATIVE` or `SABBATICAL` grant, the flat-rate variant
    applies: `credits_released` is multiplied by the term's `flat_release_rate_cents`,
    rounded half-up to whole cents. For identical `credits_released`, the two variants
    generally produce different values."

    Design: Difficulty/dual_variant_calc/release_buyout_salary_prorate_vs_flat_rate
    """
    term = make_term()
    faculty = make_faculty(base_salary_cents=9_000_000, base_load_credits=12)
    grant = setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="ADMINISTRATIVE", credits_released=3,
        start_date="2026-10-17", end_date="2026-12-11",
    )
    # 3 * 80000 = 240000, materially below the prorated 1125000 for the same credits.
    assert grant["buyout_value_cents"] == 240_000

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["release_credits"] == pytest.approx(3.0)


def test_closed_interval_release_overlap__shared_day_conflicts(api):
    """PRD §3.8: "Because the interval is closed, two grants sharing even a single
    calendar day — one ending the day the other begins — **do** overlap, and the
    create is rejected with `ERR_RELEASE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/closed_interval_release_overlap
    """
    term = make_term()
    faculty = make_faculty()
    setup_grant(
        term["id"], faculty["id"],
        grant_type="RESEARCH_BUYOUT", credits_released=3,
        start_date="2026-08-24", end_date="2026-10-16",
    )
    resp = api.create_grant(
        create_grant_payload(
            term["id"], faculty["id"],
            grant_type="ADMINISTRATIVE", credits_released=1,
            start_date="2026-10-16", end_date="2026-11-30",
        ),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_PERIOD_OVERLAP, 409)


def test_closed_interval_release_overlap__next_day_allowed(api):
    """PRD §3.8: "When a grant is created, it is compared against every other grant of
    the same pair in `REQUESTED` or `APPROVED` status, using closed-interval
    semantics: the candidate overlaps another grant whenever the candidate's
    `start_date` is on or before the other's `end_date` and the other's `start_date`
    is on or before the candidate's `end_date`."

    Design: Difficulty/resource_temporal_overlap/closed_interval_release_overlap
    """
    term = make_term()
    faculty = make_faculty()
    setup_grant(
        term["id"], faculty["id"],
        grant_type="RESEARCH_BUYOUT", credits_released=3,
        start_date="2026-08-24", end_date="2026-10-16",
    )
    resp = api.create_grant(
        create_grant_payload(
            term["id"], faculty["id"],
            grant_type="ADMINISTRATIVE", credits_released=1,
            start_date="2026-10-17", end_date="2026-11-30",
        ),
        CHAIR,
    )
    grant = validate_success(resp, 201)
    assert grant["status"] == "REQUESTED", (
        "starting the day after the previous grant's end_date is disjoint and allowed"
    )


def test_release_credits_approve_revoke_invariant__approve(api):
    """PRD §3.8: "Approval then credits the load sheet — auto-created if absent — by
    adding `credits_released` to `release_credits`, recomputing the obligation and
    overload figures, and applying the overload auto-withdraw rule."

    Design: Difficulty/compensating_invariant/release_credits_approve_revoke_invariant
    """
    term = make_term()
    faculty = make_faculty()
    grant = setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="ADMINISTRATIVE", credits_released=3,
        start_date="2026-08-24", end_date="2026-12-11",
    )
    assert grant["buyout_value_cents"] == 240_000, "FLAT_RATE 3 x 80000"

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["release_credits"] == pytest.approx(3.0)
    assert sheet["effective_obligation_credits"] == pytest.approx(9.0)


def test_release_credits_approve_revoke_invariant__revoke(api):
    """PRD §3.8: "Revocation compensates the load sheet: `credits_released` is
    subtracted from `release_credits`, and the overload and underload figures are
    recomputed. The recorded `buyout_value_cents` remains on the grant for audit even
    though the release credit is returned."

    Design: Difficulty/compensating_invariant/release_credits_approve_revoke_invariant
    """
    term = make_term()
    faculty = make_faculty()
    grant = setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="ADMINISTRATIVE", credits_released=3,
        start_date="2026-08-24", end_date="2026-12-11",
    )
    resp = api.transition_grant(grant["id"], {"to_state": "REVOKED"}, DEAN)
    revoked = validate_success(resp)
    assert revoked["status"] == "REVOKED"
    assert revoked["buyout_value_cents"] == 240_000, (
        "buyout_value_cents remains recorded for audit"
    )

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["release_credits"] == pytest.approx(0.0), (
        "revocation returns the release credit with zero drift"
    )
    assert sheet["effective_obligation_credits"] == pytest.approx(12.0)


def test_grant_denied_terminal(api):
    """PRD §3.8: "Denial moves the grant to the terminal `DENIED` state with no side
    effects."
    PRD §3.8: "From `REQUESTED`, a `DeanOffice` operator may approve or deny the
    grant; any other from-state for these targets is rejected with
    `ERR_INVALID_GRANT_TRANSITION`."

    Design: Corner/state_machines/c_grant_denied_terminal
    """
    term = make_term()
    faculty = make_faculty()
    grant = setup_grant(
        term["id"], faculty["id"],
        grant_type="SABBATICAL", credits_released=1,
        start_date="2026-08-24", end_date="2026-12-11",
    )
    resp = api.transition_grant(grant["id"], {"to_state": "DENIED"}, DEAN)
    denied = validate_success(resp)
    assert denied["status"] == "DENIED"

    resp = api.transition_grant(grant["id"], {"to_state": "APPROVED"}, DEAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_GRANT_TRANSITION, 409)

    after = validate_success(api.get_grant(grant["id"], CHAIR))
    assert after["status"] == "DENIED"
