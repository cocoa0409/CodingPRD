"""Exact-equality boundaries: the day-capacity limit and a zero denominator."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_decimal2
from test_helpers.fixtures import file_reconciliation, read_reconciliation
from test_helpers.test_users import ADMIN_HQ_HEADERS, make_club_headers
from test_helpers.types import BookingAction


# ---------------------------------------------------------------------------
# confirmed_count 1 of 2 admits; confirmed_count 2 of 2 rejects
# ---------------------------------------------------------------------------
def test_second_approval_is_admitted_one_below_the_daily_capacity(
    api, capacity_boundary_setup
):
    """PRD §2.8: "The count of events at the same club on the same `event_date`
    whose `booking_status` is `CONFIRMED` or `COMPLETED` must be strictly below
    the club's `daily_event_capacity` — otherwise `ERR_CLUB_DAY_CAPACITY_FULL`
    (409)." `remaining_slots` is `daily_event_capacity` less `confirmed_count`,
    clamped at zero so it is never negative.

    Design: Difficulty/boundary_precision_check/club_day_capacity_admits_at_one_below_and_rejects_at_exact_equality
    """
    club_id = capacity_boundary_setup["club"]["id"]
    club_headers = make_club_headers(club_id)

    before = validate_success(
        api.get_club_capacity(club_id, club_headers, "2026-09-14")
    )
    assert before["confirmed_count"] == 1
    assert before["remaining_slots"] == 1

    approved = validate_success(
        api.demo_event_transition(
            capacity_boundary_setup["events"]["b"],
            {"action": BookingAction.APPROVE},
            club_headers,
        )
    )
    assert approved["booking_status"] == "CONFIRMED"


def test_third_approval_is_refused_at_exact_equality_with_the_capacity(
    api, capacity_boundary_setup
):
    """PRD §2.8: "The count of events at the same club on the same `event_date`
    whose `booking_status` is `CONFIRMED` or `COMPLETED` must be strictly below
    the club's `daily_event_capacity` — otherwise `ERR_CLUB_DAY_CAPACITY_FULL`
    (409)." Equality with the capacity therefore rejects rather than admits, and
    the clamped `remaining_slots` never reads a negative number.

    Design: Difficulty/boundary_precision_check/club_day_capacity_admits_at_one_below_and_rejects_at_exact_equality
    """
    club_id = capacity_boundary_setup["club"]["id"]
    club_headers = make_club_headers(club_id)
    third_event_id = capacity_boundary_setup["events"]["c"]

    validate_success(
        api.demo_event_transition(
            capacity_boundary_setup["events"]["b"],
            {"action": BookingAction.APPROVE},
            club_headers,
        )
    )
    at_limit = validate_success(
        api.get_club_capacity(club_id, club_headers, "2026-09-14")
    )
    assert at_limit["confirmed_count"] == 2
    assert at_limit["remaining_slots"] == 0

    validate_error(
        api.demo_event_transition(
            third_event_id, {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.CLUB_DAY_CAPACITY_FULL,
        409,
    )

    blocked = validate_success(api.get_demo_event(third_event_id, club_headers))
    after = validate_success(api.get_club_capacity(club_id, club_headers, "2026-09-14"))
    assert blocked["booking_status"] == "SUBMITTED"
    assert after["confirmed_count"] == 2
    assert after["remaining_slots"] == 0
    assert after["remaining_slots"] != -1


# ---------------------------------------------------------------------------
# units_delivered 0 is a denominator, not an exception
# ---------------------------------------------------------------------------
def test_wholly_rejected_load_leaves_the_allocation_intact(api, zero_delivery_event):
    """PRD §3.7: "When `cases_received` is zero, the shipment lands `REJECTED`:
    `cases_received` is written as zero, `received_at` is written, and
    `short_cases` settles at the full `cases_shipped`. The divergence from the
    `SHORT` branch is deliberate and complete — a wholly rejected load does
    **not** touch the event's `allocated_sample_cases`, does not recompute
    `required_support_count` or `staffing_status`, and creates no cancellation
    credit — precisely so that the vendor can re-ship against the same intact
    allocation."

    Design: Difficulty/boundary_precision_check/zero_cases_delivered_yields_variance_pct_zero_not_a_division_by_zero
    """
    shipment = zero_delivery_event["shipment"]
    event = validate_success(
        api.get_demo_event(zero_delivery_event["event_id"], ADMIN_HQ_HEADERS)
    )

    assert shipment["shipment_status"] == "REJECTED"
    assert shipment["cases_received"] == 0
    assert shipment["short_cases"] == 3
    assert event["allocated_sample_cases"] == 3


def test_zero_units_delivered_reads_a_variance_of_zero_percent(
    api, zero_delivery_event
):
    """PRD §3.7: "`variance_pct` reads 0.00 whenever `units_delivered` is zero —
    that zero-denominator guard is part of the contract, not an implementation
    nicety — and otherwise is the absolute value of `variance_units` divided by
    `units_delivered`, multiplied by 100, rounded half-up to two decimal places."
    It settles at `BALANCED` when `variance_units` is exactly zero, or when
    `variance_pct` is at or below a tolerance of 2.00 percent.

    Design: Difficulty/boundary_precision_check/zero_cases_delivered_yields_variance_pct_zero_not_a_division_by_zero
    """
    recon = file_reconciliation(
        api, zero_delivery_event["event_id"], zero_delivery_event["club"]["id"], 0, 0, 0
    )

    assert recon["cases_delivered"] == 0
    assert recon["units_per_case"] == 4
    assert recon["units_delivered"] == 0
    assert recon["variance_units"] == 0
    assert_decimal2(recon["variance_pct"], 0.00, "variance_pct")
    assert recon["recon_status"] == "BALANCED"
    assert_cents(recon["write_off_cost_cents"], 0, "write_off_cost_cents")


def test_write_off_is_refused_against_a_balanced_reconciliation(
    api, zero_delivery_event
):
    """PRD §3.7: "A write-off attempted against a `BALANCED` row is refused with
    `ERR_INVALID_STATE`." Resolution is a head-office write-off, legal only from
    `VARIANCE_FLAGGED`.

    Design: Difficulty/boundary_precision_check/zero_cases_delivered_yields_variance_pct_zero_not_a_division_by_zero
    """
    recon = file_reconciliation(
        api, zero_delivery_event["event_id"], zero_delivery_event["club"]["id"], 0, 0, 0
    )

    validate_error(
        api.write_off_reconciliation(
            recon["id"], {"note": "attempt on a balanced row"}, ADMIN_HQ_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    unchanged = read_reconciliation(api, zero_delivery_event["event_id"])
    assert unchanged["recon_status"] == "BALANCED"
    assert_cents(unchanged["write_off_cost_cents"], 0, "write_off_cost_cents")

    assignment = validate_success(
        api.get_assignment(zero_delivery_event["assignment_id"], ADMIN_HQ_HEADERS)
    )
    assert_decimal2(assignment["billable_hours"], 5.50, "billable_hours")
