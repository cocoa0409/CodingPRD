"""Depth-3 offboard cascade: property -> booking -> turnover -> inspection."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_turnover_task_payload, create_inspection_payload,
    make_vendor_headers, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _property_with_failed_turnover_and_inspection(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    cleaner = fixtures.create_vendor(api, "CLEANER")
    inspector = fixtures.create_vendor(api, "INSPECTOR")
    turnover = get_success_data(api.create_turnover_task(create_turnover_task_payload(
        booking["id"], pid, cleaner["id"], "2026-06-13T10:00:00Z", "2026-06-13T13:00:00Z"), PM))
    get_success_data(api.start_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    get_success_data(api.complete_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    inspection = get_success_data(api.create_inspection(create_inspection_payload(
        turnover["id"], inspector["id"], "FAIL"), PM))  # turnover -> FAILED, inspection COMPLETED
    return {"property": pid, "booking": booking["id"], "turnover": turnover["id"], "inspection": inspection["id"]}


def test_offboard_cancels_property_and_booking(api):
    """PRD §2.8: "Offboarding a property is the deepest: it drives the property to
    `OFFBOARDED`, transitions every one of its channel listings to `DELISTED`, and cancels
    every non-terminal booking (any booking whose `stay_status` is `HOLD` or `CONFIRMED`)."

    Design: Difficulty/transitive_cascade/offboard_cancels_booking_then_turnover_then_inspection
    """
    ctx = _property_with_failed_turnover_and_inspection(api)
    prop = validate_success(api.offboard_property(ctx["property"], PM), 200)
    assert prop["status"] == "OFFBOARDED"
    assert get_success_data(api.get_booking(ctx["booking"], PM))["stay_status"] == "CANCELLED"


def test_offboard_cascades_turnover_then_inspection(api):
    """PRD §2.8: "Each such booking cancellation itself cascades — it releases the held
    calendar nights and cancels that booking's turnover task if the task is still non-terminal,
    and that turnover cancellation in turn cancels any `COMPLETED` inspection attached to it."

    Design: Difficulty/transitive_cascade/offboard_cancels_booking_then_turnover_then_inspection
    """
    ctx = _property_with_failed_turnover_and_inspection(api)
    get_success_data(api.offboard_property(ctx["property"], PM))
    assert get_success_data(api.get_turnover_task(ctx["turnover"], PM))["status"] == "CANCELLED"
    assert get_success_data(api.get_inspection(ctx["inspection"], PM))["status"] == "CANCELLED"
