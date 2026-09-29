"""Opening posture, submission preconditions and terminal-state lockdown."""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_event_dimensions,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    new_club,
    new_demo_event,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    BookingAction,
    BookingStatus,
    DayPart,
    ProductCategory,
    SettlementStatus,
    StaffingStatus,
)


def _instant(value):
    """Parse an ISO-8601 UTC instant, tolerating the optional fractional part."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_a_new_booking_occupies_the_initial_state_of_all_three_dimensions(api):
    """PRD §3.2: "And the booking opens in a known posture: `booking_status` `DRAFT`, `staffing_status` `UNSTAFFED`, `settlement_status` `UNBILLED`, and `allocated_sample_cases`, `pool_cases_used` and `reserve_cases_used` all zero, with `submitted_at`, `approved_at` and `cancellation_reason` all unset, `required_support_count` zero and `no_show_recovery_open` false."

    PRD §2.5: "A `MORNING` demo runs from 09:00Z to 13:00Z, a `MIDDAY` demo from 12:00Z to 16:00Z, and an `AFTERNOON` demo from 15:00Z to 19:00Z, all on the event's `event_date`."

    Design: Corner/state_machines/demo_event_starts_in_draft_unstaffed_and_unbilled
    """
    vendor = new_manufacturer(api, legal_name="Jarrowmill Home")
    club = new_club(api, club_number="C6009", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="JH-RUG-009",
        name="Woven Runner Rug",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=3100,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )

    event = validate_success(
        api.create_demo_event(
            {
                "manufacturer_id": vendor["id"],
                "club_id": club["id"],
                "product_id": product["id"],
                "event_date": "2026-09-14",
                "day_part": DayPart.AFTERNOON,
                "requested_sample_cases": 3,
                "addon_services": [],
            },
            make_manufacturer_headers(vendor["id"]),
        ),
        201,
    )

    assert_event_dimensions(
        event,
        booking_status=BookingStatus.DRAFT,
        staffing_status=StaffingStatus.UNSTAFFED,
        settlement_status=SettlementStatus.UNBILLED,
    )
    assert event["no_show_recovery_open"] is False
    assert event["cancellation_reason"] is None
    assert event["allocated_sample_cases"] == 0
    assert event["pool_cases_used"] == 0
    assert event["reserve_cases_used"] == 0
    assert event["required_support_count"] == 0
    assert _instant(event["event_window_start_utc"]) == _instant("2026-09-14T15:00:00Z")
    assert _instant(event["event_window_end_utc"]) == _instant("2026-09-14T19:00:00Z")


def test_submission_is_refused_one_day_short_of_the_lead_time_and_accepted_at_it(api):
    """PRD §2.8: "**Booking lead time.** `SUBMIT` requires the event's `event_date` to be at least 7 days after the logical clock's UTC date — otherwise `ERR_BOOKING_LEAD_TIME_TOO_SHORT` (422)."

    PRD §2.5: "Until an operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real time."

    Design: Corner/state_machines/submit_before_minimum_lead_time_is_rejected
    """
    vendor = new_manufacturer(api, legal_name="Kelbrook Wares")
    club = new_club(api, club_number="C6010", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="KW-TRY-010",
        name="Serving Tray Set",
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    too_early = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-08-07",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    on_the_bound = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-08-08",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=2,
    )

    validate_error(
        api.demo_event_transition(
            too_early["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        ApiErrorId.BOOKING_LEAD_TIME_TOO_SHORT,
        422,
    )
    still_draft = validate_success(api.get_demo_event(too_early["id"], vendor_headers))
    assert still_draft["booking_status"] == BookingStatus.DRAFT
    assert still_draft["submitted_at"] is None

    accepted = validate_success(
        api.demo_event_transition(
            on_the_bound["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        200,
    )
    assert accepted["booking_status"] == BookingStatus.SUBMITTED


def test_a_second_submit_on_a_submitted_booking_neither_restamps_nor_reversions(api):
    """PRD §2.8: "**Transition legality.** The target resource's current state must be a declared source state of the requested transition — otherwise `ERR_INVALID_STATE` (409)."

    PRD §3.2: "On success the submission stamps `submitted_at` with the logical clock's current instant and increments the event's `version` by 1."

    Design: Corner/state_machines/repeating_submit_on_an_already_submitted_event_is_rejected
    """
    vendor = new_manufacturer(api, legal_name="Oakhampton Home")
    club = new_club(api, club_number="C6014", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="OH-BSK-014",
        name="Storage Basket",
        unit_cost_cents=1400,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    first = submit(api, event["id"], vendor["id"])

    validate_error(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    unchanged = validate_success(api.get_demo_event(event["id"], vendor_headers))
    assert unchanged["submitted_at"] == first["submitted_at"]
    assert unchanged["version"] == first["version"]
    assert unchanged["booking_status"] == BookingStatus.SUBMITTED


def test_close_out_without_execution_reports_the_staffing_dimension_refusal(api):
    """PRD §2.8: "**Execution readiness.** `CLOSE_OUT` requires the event's `staffing_status` to be `EXECUTED` and every assignment on the event to have reached `COMPLETED`, `NO_SHOW` or `RELEASED` — otherwise `ERR_EVENT_NOT_EXECUTED` (409)."

    Design: Corner/state_machines/close_out_from_confirmed_without_execution_is_rejected
    """
    vendor = new_manufacturer(api, legal_name="Mistleford Supply")
    club = new_club(api, club_number="C6012", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="MS-CUP-012",
        name="Insulated Cup Pack",
        unit_cost_cents=1800,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    confirmed = approve(api, event["id"], club["id"])
    club_headers = make_club_headers(club["id"])

    error = validate_error(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.CLOSE_OUT}, club_headers
        ),
        ApiErrorId.EVENT_NOT_EXECUTED,
        409,
    )
    assert error["error_id"] != ApiErrorId.INVALID_STATE

    after = validate_success(api.get_demo_event(event["id"], club_headers))
    assert_event_dimensions(
        after,
        booking_status=BookingStatus.CONFIRMED,
        staffing_status=StaffingStatus.UNSTAFFED,
        settlement_status=SettlementStatus.UNBILLED,
    )
    assert after["version"] == confirmed["version"]


def test_a_cancelled_booking_accepts_no_further_action_at_all(api):
    """PRD §3.3: "Both `COMPLETED` and `CANCELLED` are terminal for the booking dimension: no further booking action is accepted, and a second cancellation attempt is refused with `ERR_INVALID_STATE`."

    PRD §3.2: "Cancelling from `DRAFT` moves the event straight to `CANCELLED`, sets `cancellation_reason` to `MANUFACTURER_CANCELLED_EARLY`, and increments `version` by 1 — and it creates no cancellation credit at all, because nothing was ever allocated and nothing was ever billable."

    Design: Corner/state_machines/cancelled_event_is_locked_against_every_further_transition
    """
    vendor = new_manufacturer(api, legal_name="Norvale Kitchenware")
    club = new_club(api, club_number="C6013", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="NK-PAN-013",
        name="Nonstick Pan",
        unit_cost_cents=2600,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])
    club_headers = make_club_headers(club["id"])

    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    cancelled = validate_success(
        api.demo_event_transition(
            event["id"],
            {"action": BookingAction.CANCEL, "reason": "manufacturer withdrew"},
            vendor_headers,
        )
    )
    assert cancelled["booking_status"] == BookingStatus.CANCELLED

    validate_error(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.CANCEL}, vendor_headers
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    frozen = validate_success(api.get_demo_event(event["id"], vendor_headers))
    assert frozen["version"] == cancelled["version"]
    assert frozen["allocated_sample_cases"] == 0

    credits, meta = validate_paginated(
        api.list_credits(vendor_headers, {"demo_event_id": event["id"]})
    )
    assert credits == []
    assert meta["total_count"] == 0
