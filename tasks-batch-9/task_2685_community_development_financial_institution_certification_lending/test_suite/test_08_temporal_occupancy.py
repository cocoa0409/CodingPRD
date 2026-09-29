"""Two occupancy resources that disagree about where adjacency begins.

A measurement window is half-open and its occupancy is partitioned by
weighting basis, so abutting cuts are legal. A coaching slot is a closed
interval padded by half an hour on each side, so abutting bookings are not.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _draft_window(institution_id, period_start, period_end,
                  weighting_basis="DOLLAR_WEIGHTED"):
    """Open one draft measurement and return the raw response."""
    return api_client.create_compliance_measurement(
        institution_id,
        {
            "period_start": period_start,
            "period_end": period_end,
            "weighting_basis": weighting_basis,
        },
        ANALYST,
    )


def _institution_with_a_july_dollar_window():
    """A lender holding one draft dollar-weighted cut over July 2026."""
    fixtures.set_clock("2026-10-01T00:00:00Z")
    institution = fixtures.create_institution()
    first = validate_success(
        _draft_window(
            institution["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        201,
    )
    assert first["state"] == "DRAFT"
    assert first["verdict"] == "PENDING"
    return institution, first


def test_abutting_and_other_basis_windows_are_accepted_but_a_straddle_is_not():
    """Only a same-basis intersection is refused; touching endpoints are not.

    PRD: "A new window is refused with `ERR_MEASUREMENT_PERIOD_OVERLAP` when it
    intersects the window of any existing measurement of the same institution
    **and the same** `weighting_basis` whose `state` is `DRAFT` or `FINALIZED`."
    PRD: "Two consequences follow directly: adjacency is permitted, so a new
    window whose `period_start` equals an existing window's `period_end` is
    accepted; and a window that duplicates an existing one under the *other*
    basis is also accepted, which is precisely how the same period is measured
    both ways for comparison."

    Design: Difficulty/resource_temporal_overlap/measurement_window_half_open_adjacency_allowed_and_partitioned_by_basis
    """
    institution, first = _institution_with_a_july_dollar_window()
    institution_id = institution["id"]

    abutting = validate_success(
        _draft_window(
            institution_id, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
        ),
        201,
    )
    assert abutting["state"] == "DRAFT"
    assert abutting["weighting_basis"] == "DOLLAR_WEIGHTED"
    assert abutting["period_start"] == "2026-08-01T00:00:00Z"

    straddling = _draft_window(
        institution_id, "2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"
    )
    validate_error(straddling, ApiErrorId.ERR_MEASUREMENT_PERIOD_OVERLAP)

    other_basis = validate_success(
        _draft_window(
            institution_id,
            "2026-07-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
            weighting_basis="COUNT_WEIGHTED",
        ),
        201,
    )
    assert other_basis["state"] == "DRAFT"
    assert other_basis["weighting_basis"] == "COUNT_WEIGHTED"
    assert other_basis["period_start"] == first["period_start"]
    assert other_basis["period_end"] == first["period_end"]


def test_voiding_a_draft_frees_its_window_for_an_identical_re_cut():
    """A voided row leaves the candidate set, so the same window reopens.

    PRD: "Measurements in `state` `VOIDED` are excluded from the overlap
    candidate set entirely."
    PRD: "Voiding requires the measurement to be `DRAFT`, carries a
    `void_reason`, moves it `DRAFT → VOIDED`, and releases the window: because
    voided rows leave the overlap candidate set, an overlapping period may then
    be cut afresh."

    Design: Difficulty/resource_temporal_overlap/measurement_window_half_open_adjacency_allowed_and_partitioned_by_basis
    """
    institution, first = _institution_with_a_july_dollar_window()
    institution_id = institution["id"]

    abutting = validate_success(
        _draft_window(
            institution_id, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
        ),
        201,
    )
    other_basis = validate_success(
        _draft_window(
            institution_id,
            "2026-07-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
            weighting_basis="COUNT_WEIGHTED",
        ),
        201,
    )

    voided = validate_success(
        api_client.void_compliance_measurement(
            first["id"], {"void_reason": "WINDOW_RECUT"}, ANALYST
        )
    )
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "WINDOW_RECUT"
    assert voided["version"] == first["version"] + 1

    recut = validate_success(
        _draft_window(
            institution_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        201,
    )
    assert recut["state"] == "DRAFT"
    assert recut["verdict"] == "PENDING"
    assert recut["weighting_basis"] == "DOLLAR_WEIGHTED"
    assert recut["id"] != first["id"]

    drafts, meta = validate_paginated(
        api_client.list_institution_compliance_measurements(
            institution_id, ANALYST, {"state": "DRAFT"}
        )
    )
    assert meta["total_count"] == 3, (
        "the abutting cut, the other-basis cut and the re-cut are the three "
        "drafts that survive the void"
    )
    assert {row["id"] for row in drafts} == {
        abutting["id"], other_basis["id"], recut["id"]
    }


def _coached_borrower_with_an_afternoon_session():
    """A borrower holding one scheduled session from 14:00 to 15:00.

    Padded by half an hour on each side, that session occupies the borrower's
    calendar from 13:30 through 15:30 inclusive.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    borrower = fixtures.create_geocoded_borrower(institution_id)
    officer = fixtures.make_institution_officer_headers(institution_id)
    first = fixtures.book_ta_engagement(
        institution_id, borrower["id"],
        "2026-09-02T14:00:00Z", "2026-09-02T15:00:00Z", 1.00,
    )
    assert first["state"] == "SCHEDULED"
    return institution_id, borrower, officer, first


def test_a_booking_on_the_buffer_edge_is_refused_and_one_minute_later_is_not():
    """The buffered comparison is inclusive, so 15:30 collides and 15:31 does not.

    PRD: "The requested closed interval is padded by a half-hour buffer on each
    side, and the booking is refused with `ERR_TA_SLOT_CONFLICT` when it
    intersects any existing session of the **same** borrower whose `state` is
    `SCHEDULED` or `COMPLETED`. Stated exactly: the booking is rejected when the
    new `scheduled_start_at` is at or before the existing session's
    `scheduled_end_at` advanced by 30 minutes, and simultaneously the existing
    session's `scheduled_start_at` is at or before the new `scheduled_end_at`
    advanced by 30 minutes."

    Design: Difficulty/resource_temporal_overlap/ta_slot_closed_interval_with_thirty_minute_buffer_rejects_abutment
    """
    institution_id, borrower, officer, _first = (
        _coached_borrower_with_an_afternoon_session()
    )

    on_the_edge = api_client.create_ta_engagement(
        institution_id,
        {
            "borrower_id": borrower["id"],
            "topic": "FINANCIAL_COACHING",
            "scheduled_start_at": "2026-09-02T15:30:00Z",
            "scheduled_end_at": "2026-09-02T16:30:00Z",
            "planned_hours": 1.00,
        },
        officer,
    )
    validate_error(on_the_edge, ApiErrorId.ERR_TA_SLOT_CONFLICT)

    one_minute_later = validate_success(
        api_client.create_ta_engagement(
            institution_id,
            {
                "borrower_id": borrower["id"],
                "topic": "FINANCIAL_COACHING",
                "scheduled_start_at": "2026-09-02T15:31:00Z",
                "scheduled_end_at": "2026-09-02T16:31:00Z",
                "planned_hours": 1.00,
            },
            officer,
        ),
        201,
    )
    assert one_minute_later["state"] == "SCHEDULED"
    assert one_minute_later["scheduled_start_at"] == "2026-09-02T15:31:00Z"
    assert float(one_minute_later["actual_hours"]) == 0.00
    assert one_minute_later["competency_verified"] is False
    assert one_minute_later["closed_at"] is None


def test_a_no_show_releases_the_interval_for_an_identical_rebooking():
    """Only scheduled and completed sessions occupy the calendar.

    PRD: "An `outcome` of `NO_SHOW` moves the session `SCHEDULED → NO_SHOW`,
    stamps `closed_at` from the logical clock, sets `actual_hours` to 0.00 and
    `competency_verified` to false, leaves the borrower's `ta_hours_total`
    unchanged, and — because only `SCHEDULED` and `COMPLETED` sessions occupy
    the borrower's calendar — releases the interval so that it becomes bookable
    again."
    PRD: "Sessions of other borrowers, and sessions already closed as no-shows,
    are irrelevant to the test."

    Design: Difficulty/resource_temporal_overlap/ta_slot_closed_interval_with_thirty_minute_buffer_rejects_abutment
    """
    institution_id, borrower, officer, first = (
        _coached_borrower_with_an_afternoon_session()
    )
    evening = validate_success(
        api_client.create_ta_engagement(
            institution_id,
            {
                "borrower_id": borrower["id"],
                "topic": "FINANCIAL_COACHING",
                "scheduled_start_at": "2026-09-02T15:31:00Z",
                "scheduled_end_at": "2026-09-02T16:31:00Z",
                "planned_hours": 1.00,
            },
            officer,
        ),
        201,
    )

    closed = validate_success(
        api_client.close_ta_engagement(
            first["id"], {"outcome": "NO_SHOW"}, officer
        )
    )
    assert closed["state"] == "NO_SHOW"
    assert float(closed["actual_hours"]) == 0.00
    assert closed["competency_verified"] is False
    assert closed["closed_at"] == "2026-09-01T00:00:00.000Z"

    rebooked = validate_success(
        api_client.create_ta_engagement(
            institution_id,
            {
                "borrower_id": borrower["id"],
                "topic": "CREDIT_BUILDING",
                "scheduled_start_at": "2026-09-02T14:00:00Z",
                "scheduled_end_at": "2026-09-02T15:00:00Z",
                "planned_hours": 1.00,
            },
            officer,
        ),
        201,
    )
    assert rebooked["state"] == "SCHEDULED"
    assert rebooked["scheduled_start_at"] == "2026-09-02T14:00:00Z"
    assert rebooked["id"] != first["id"]

    reread_borrower = validate_success(
        api_client.get_borrower(borrower["id"], ANALYST)
    )
    assert float(reread_borrower["ta_hours_total"]) == 0.00

    scheduled, meta = validate_paginated(
        api_client.list_ta_engagements(
            ANALYST, {"borrower_id": borrower["id"], "state": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in scheduled} == {evening["id"], rebooked["id"]}
