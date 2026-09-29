"""Partial roster updates, and the refusal branch of a credit decision."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN_CONTROLLER_HEADERS,
    ADMIN_CONTROLLER_USER_ID,
    ADMIN_HQ_HEADERS,
    ApiErrorId,
    STAFF_OPS_HEADERS,
    assert_cents,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    credits_for_event,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    BookingAction,
    BookingStatus,
    CreditDecision,
    CreditReason,
    CreditStatus,
    DayPart,
    EmploymentStatus,
    ProductCategory,
    StaffingStatus,
)


def test_a_roster_update_touches_only_the_keys_it_names(api):
    """PRD §3.4: "Roster maintenance may revise `employment_status`, `hourly_rate_cents` and `max_weekly_events`."

    PRD §3.4: "Only `ACTIVE` permits a new assignment; both `ON_LEAVE` and `TERMINATED` block one, and the refusal is `ERR_DEMONSTRATOR_NOT_ACTIVE`."

    PRD §3.4: "Adding a demonstrator captures a `home_club_id` naming the club the worker is rostered to, a `full_name`, an `hourly_rate_cents` of at least 1 that will price the invoice's staffing lines, and an optional `max_weekly_events` from 1 through 14 that defaults to 5."

    Design: Corner/endpoints/patch_demonstrator_updates_the_row_and_gates_later_assignments
    """
    vendor = new_manufacturer(api, legal_name="Marchwood Home", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6033",
        name="Marchwood Club 6033",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="MH-STL-033",
        name="Step Stool",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2800,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    worker = new_demonstrator(
        api, club["id"], full_name="Nora Blackwell", hourly_rate_cents=2200
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
    approve(api, event["id"], club["id"])

    repriced = validate_success(
        api.update_demonstrator(
            worker["id"], {"hourly_rate_cents": 2600}, STAFF_OPS_HEADERS
        )
    )
    assert_cents(repriced["hourly_rate_cents"], 2600, "hourly_rate_cents")
    assert repriced["full_name"] == "Nora Blackwell"
    assert repriced["employment_status"] == EmploymentStatus.ACTIVE
    assert repriced["version"] == worker["version"] + 1

    stood_down = validate_success(
        api.update_demonstrator(
            worker["id"],
            {"employment_status": EmploymentStatus.ON_LEAVE},
            STAFF_OPS_HEADERS,
        )
    )
    assert stood_down["employment_status"] == EmploymentStatus.ON_LEAVE
    assert stood_down["version"] == repriced["version"] + 1

    validate_error(
        api.create_assignment(
            event["id"],
            {"demonstrator_id": worker["id"], "role": AssignmentRole.LEAD},
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.DEMONSTRATOR_NOT_ACTIVE,
        422,
    )

    read_back = validate_success(api.get_demonstrator(worker["id"], STAFF_OPS_HEADERS))
    assert read_back["home_club_id"] == club["id"]
    assert read_back["max_weekly_events"] == 5
    assert_cents(read_back["hourly_rate_cents"], 2600, "hourly_rate_cents")

    uncovered = validate_success(
        api.get_demo_event(event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert uncovered["staffing_status"] == StaffingStatus.UNSTAFFED


def test_a_refused_credit_reaches_a_terminal_state_and_moves_no_money(api):
    """PRD §3.9: "Rejection is far simpler and is the symmetric branch: it stamps `approved_by_user_id` with the acting `X-User-ID`, moves `credit_status` to `REJECTED`, leaves every invoice untouched along with both `outstanding_balance_cents` and `credit_note_balance_cents`, and increments the credit's `version` by 1."

    PRD §3.9: "Both `APPLIED` and `REJECTED` are terminal, and a second decision on a decided credit is refused with `ERR_INVALID_STATE`."

    PRD §3.9: "A credit opens in `PENDING_APPROVAL` with `approved_by_user_id` and `applied_to_invoice_id` both unset."

    PRD §3.3: "One cancellation credit is created on the event, with its `credit_reason` copied from the event's `cancellation_reason` and its `credit_status` opening at `PENDING_APPROVAL`, valued by the notice-tier arithmetic of §3.9."

    Design: Corner/endpoints/rejecting_a_cancellation_credit_closes_it_without_touching_any_balance
    """
    vendor = new_manufacturer(api, legal_name="Netherby Brands", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6034",
        name="Netherby Club 6034",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="NB-BLK-034",
        name="Fleece Blanket",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=3400,
        samples_per_case=2,
        weekly_sample_case_pool=20,
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
    approve(api, event["id"], club["id"])

    cancelled = validate_success(
        api.demo_event_transition(
            event["id"],
            {"action": BookingAction.CANCEL, "reason": "club remodel"},
            make_club_headers(club["id"]),
        )
    )
    assert cancelled["booking_status"] == BookingStatus.CANCELLED
    assert cancelled["cancellation_reason"] == CreditReason.CLUB_CANCELLED

    credits = credits_for_event(api, event["id"])
    assert len(credits) == 1
    credit = credits[0]
    assert credit["credit_status"] == CreditStatus.PENDING_APPROVAL
    assert credit["approved_by_user_id"] is None
    assert credit["applied_to_invoice_id"] is None

    rejected = validate_success(
        api.decide_credit(
            credit["id"],
            {
                "decision": CreditDecision.REJECT,
                "note": "cancellation was inside the manufacturer's control",
            },
            ADMIN_CONTROLLER_HEADERS,
        )
    )
    assert rejected["credit_status"] == CreditStatus.REJECTED
    assert rejected["applied_to_invoice_id"] is None
    assert rejected["approved_by_user_id"] == ADMIN_CONTROLLER_USER_ID
    assert rejected["version"] == credit["version"] + 1

    validate_error(
        api.decide_credit(
            credit["id"],
            {"decision": CreditDecision.APPROVE},
            ADMIN_CONTROLLER_HEADERS,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    ledger = validate_success(api.get_manufacturer(vendor["id"], ADMIN_HQ_HEADERS))
    assert_cents(ledger["credit_note_balance_cents"], 0, "credit_note_balance_cents")
    assert_cents(ledger["outstanding_balance_cents"], 0, "outstanding_balance_cents")
