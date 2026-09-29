"""Date-window edges, account standing and the resolution-before-ownership order."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN_HQ_HEADERS,
    ApiErrorId,
    make_manufacturer_headers,
)
from test_helpers.factories import demo_event_payload
from test_helpers.fixtures import (
    new_club,
    new_demo_event,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    AccountStatus,
    BookingAction,
    BookingStatus,
    DayPart,
    ProductCategory,
)

UNKNOWN_EVENT_ID = "00000000-0000-4000-8000-00000000dead"


def test_a_booking_dated_one_day_past_the_far_edge_cannot_be_submitted(api):
    """PRD §3.2: "Submitting the booking moves `booking_status` from `DRAFT` to `SUBMITTED`."

    PRD §2.8: "**Booking horizon.** `SUBMIT` requires the event's `event_date` to be no more than 120 days after the logical clock's UTC date — otherwise `ERR_BOOKING_HORIZON_EXCEEDED` (422)."

    PRD §2.8: "**Booking lead time.** `SUBMIT` requires the event's `event_date` to be at least 7 days after the logical clock's UTC date — otherwise `ERR_BOOKING_LEAD_TIME_TOO_SHORT` (422)."

    Design: Corner/validations/submit_beyond_the_booking_horizon_is_rejected_at_the_exact_edge
    """
    vendor = new_manufacturer(api, legal_name="Carrowmore Goods", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6026",
        name="Carrowmore Club 6026",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="CG-LNT-026",
        name="Lint Roller",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=700,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    beyond_edge = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-11-30",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    at_edge = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-11-29",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )

    refusal = validate_error(
        api.demo_event_transition(
            beyond_edge["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        ApiErrorId.BOOKING_HORIZON_EXCEEDED,
        422,
    )
    assert refusal["error_id"] != ApiErrorId.BOOKING_LEAD_TIME_TOO_SHORT

    unmoved = validate_success(api.get_demo_event(beyond_edge["id"], vendor_headers))
    assert unmoved["booking_status"] == BookingStatus.DRAFT
    assert unmoved["submitted_at"] is None
    assert unmoved["version"] == beyond_edge["version"]

    accepted = submit(api, at_edge["id"], vendor["id"])
    assert accepted["booking_status"] == BookingStatus.SUBMITTED
    assert accepted["submitted_at"] is not None


def test_a_suspended_account_cannot_book_while_a_held_one_can_only_draft(api):
    """PRD §3.1: "`ACTIVE` is the only state that permits a booking to advance: both `SUBMIT` and `APPROVE` require it."

    PRD §3.1: "`SUSPENDED` is the hardest state — it blocks event creation outright as well as every booking advance and every invoice advance — and it is only ever set or cleared by head-office maintenance, never by an automatic transition."

    PRD §2.8: "**Suspension.** The manufacturer's `account_status` must not be `SUSPENDED` when an event is booked, when the booking dimension is advanced, or when an invoice is advanced — otherwise `ERR_MANUFACTURER_SUSPENDED` (402)."

    PRD §2.8: "**Credit hold.** `SUBMIT` and `APPROVE` both require the manufacturer's `account_status` to be exactly `ACTIVE`; an account on `HOLD` may still edit drafts but may not advance a booking, and the refusal is `ERR_MANUFACTURER_ON_CREDIT_HOLD` (402)."

    Design: Corner/validations/account_status_gates_creation_and_advancement_differently
    """
    vendor = new_manufacturer(api, legal_name="Dovecourt Brands", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6027",
        name="Dovecourt Club 6027",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="DB-FRM-027",
        name="Picture Frame",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1300,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])
    booking = demo_event_payload(
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )

    suspended = validate_success(
        api.update_manufacturer(
            vendor["id"], {"account_status": AccountStatus.SUSPENDED}, ADMIN_HQ_HEADERS
        )
    )
    assert suspended["account_status"] == AccountStatus.SUSPENDED

    validate_error(
        api.create_demo_event(booking, vendor_headers),
        ApiErrorId.MANUFACTURER_SUSPENDED,
        402,
    )

    held = validate_success(
        api.update_manufacturer(
            vendor["id"], {"account_status": AccountStatus.HOLD}, ADMIN_HQ_HEADERS
        )
    )
    assert held["account_status"] == AccountStatus.HOLD

    drafted = validate_success(api.create_demo_event(booking, vendor_headers), 201)
    assert drafted["booking_status"] == BookingStatus.DRAFT

    validate_error(
        api.demo_event_transition(
            drafted["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        ),
        ApiErrorId.MANUFACTURER_ON_CREDIT_HOLD,
        402,
    )
    assert (
        validate_success(api.get_demo_event(drafted["id"], vendor_headers))[
            "booking_status"
        ]
        == BookingStatus.DRAFT
    )

    validate_success(
        api.update_manufacturer(
            vendor["id"], {"account_status": AccountStatus.ACTIVE}, ADMIN_HQ_HEADERS
        )
    )

    advanced = submit(api, drafted["id"], vendor["id"])
    assert advanced["booking_status"] == BookingStatus.SUBMITTED


def test_an_unresolvable_path_is_answered_before_the_caller_is_checked_for_ownership(api):
    """PRD §2.8: "**Path resolution.** Each identifier in the URL path is resolved left to right, and the first one that does not resolve determines the 404."

    PRD §2.8: "**Ownership.** For the three entity-backed roles, the acting `X-User-ID` must own the target, as defined in §2.1 — otherwise `ERR_RESOURCE_OWNERSHIP` (403)."

    PRD §3.2: "While a booking is still in `DRAFT`, the vendor may revise `event_date`, `day_part`, `requested_sample_cases`, `attribution_window_days` and `addon_services`."

    Design: Corner/validations/not_found_at_priority_6_outranks_ownership_at_priority_8
    """
    owner = new_manufacturer(api, legal_name="Elmsworth Organics", credit_limit_cents=900_000)
    outsider = new_manufacturer(api, legal_name="Fenwick Foods", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6028",
        name="Elmsworth Club 6028",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        owner["id"],
        sku="EO-PLW-028",
        name="Throw Pillow",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1800,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    event = new_demo_event(
        api,
        owner["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    outsider_headers = make_manufacturer_headers(outsider["id"])

    validate_error(
        api.update_demo_event(
            event["id"], {"requested_sample_cases": 4}, outsider_headers
        ),
        ApiErrorId.RESOURCE_OWNERSHIP,
        403,
    )

    validate_error(
        api.update_demo_event(
            UNKNOWN_EVENT_ID, {"requested_sample_cases": 4}, outsider_headers
        ),
        ApiErrorId.DEMO_EVENT_NOT_FOUND,
        404,
    )

    revised = validate_success(
        api.update_demo_event(
            event["id"],
            {"requested_sample_cases": 4},
            make_manufacturer_headers(owner["id"]),
        )
    )
    assert revised["requested_sample_cases"] == 4
    assert revised["booking_status"] == BookingStatus.DRAFT
    assert revised["version"] == event["version"] + 1
