"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness resets the database before each test. Helpers use get_success_data()
so setup failures surface as clear "Setup failed" errors.

Identity threading: after creating an entity-backed principal (Owner / Guest / Vendor),
any ownership-gated call uses make_<role>_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_owner_headers, make_vendor_headers
from . import factories as f

PM = TEST_USERS["property_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

__all__ = [
    "set_clock",
    "create_owner", "create_guest", "create_vendor", "create_property",
    "create_active_permit", "create_listed_property", "get_property_version",
    "create_booking", "screen_booking", "confirm_booking", "check_in_booking",
    "check_out_booking", "create_confirmed_booking",
    "setup_owner_statement_scenario",
    "create_completed_owner_work_order", "create_approved_owner_work_order",
    "setup_cleaned_turnover",
]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# --------------------------------------------------------------------------- #
# Tier 1/2: base entities
# --------------------------------------------------------------------------- #
def create_owner(api, mgmt_fee_pct: int = 20, **overrides):
    return get_success_data(
        api.create_owner(f.create_owner_payload(default_management_fee_pct=mgmt_fee_pct, **overrides), ADMIN)
    )


def create_guest(api, banned: bool = False, **overrides):
    guest = get_success_data(api.create_guest(f.create_guest_payload(**overrides), ANON))
    if banned:
        get_success_data(api.ban_guest(guest["id"], PM))
        guest = get_success_data(api.get_guest(guest["id"], PM))
    return guest


def create_vendor(api, vendor_type: str = "CLEANER", **overrides):
    return get_success_data(api.create_vendor(f.create_vendor_payload(vendor_type=vendor_type, **overrides), PM))


def create_property(api, owner_id: str, **overrides):
    return get_success_data(api.create_property(f.create_property_payload(owner_id, **overrides), PM))


def create_active_permit(api, property_id: str, occupancy_tax_pct: int = 10,
                         expires_on: str = "2027-01-01T00:00:00Z", **overrides):
    permit = get_success_data(
        api.create_permit(
            f.create_permit_payload(property_id, occupancy_tax_pct=occupancy_tax_pct,
                                    expires_on=expires_on, **overrides),
            PM,
        )
    )
    get_success_data(api.activate_permit(permit["id"], PM))
    return get_success_data(api.get_permit(permit["id"], PM))


def create_listed_property(api, mgmt_fee_pct: int = 20, base_nightly_rate_cents: int = 20000,
                           cleaning_fee_cents: int = 15000, occupancy_tax_pct: int = 10,
                           default_cancellation_policy=None, expires_on: str = "2027-01-01T00:00:00Z"):
    """Owner + property + ACTIVE permit + LISTED property.

    Returns {"owner", "property", "permit"} where "property" is the LISTED object.
    """
    owner = create_owner(api, mgmt_fee_pct)
    prop_overrides = {"base_nightly_rate_cents": base_nightly_rate_cents,
                      "cleaning_fee_cents": cleaning_fee_cents}
    if default_cancellation_policy:
        prop_overrides["default_cancellation_policy"] = default_cancellation_policy
    prop = create_property(api, owner["id"], **prop_overrides)
    permit = create_active_permit(api, prop["id"], occupancy_tax_pct, expires_on=expires_on)
    listed = get_success_data(api.list_property(prop["id"], PM))
    return {"owner": owner, "property": listed, "permit": permit}


def get_property_version(api, property_id: str) -> int:
    return get_success_data(api.get_property(property_id, PM))["version"]


# --------------------------------------------------------------------------- #
# Booking lifecycle helpers
# --------------------------------------------------------------------------- #
def create_booking(api, property_id: str, guest_id: str, check_in: str, check_out: str,
                   cancellation_policy=None, headers=None):
    extra = {}
    if cancellation_policy:
        extra["cancellation_policy"] = cancellation_policy
    return get_success_data(
        api.create_booking(
            f.create_booking_payload(property_id, guest_id, check_in, check_out, **extra),
            headers or PM,
        )
    )


def screen_booking(api, booking_id: str, decision: str):
    return get_success_data(api.screen_booking(booking_id, {"decision": decision}, PM))


def confirm_booking(api, booking_id: str):
    return get_success_data(api.confirm_booking(booking_id, PM))


def check_in_booking(api, booking_id: str):
    return get_success_data(api.check_in_booking(booking_id, PM))


def check_out_booking(api, booking_id: str):
    return get_success_data(api.check_out_booking(booking_id, PM))


def create_confirmed_booking(api, property_id: str, guest_id: str, check_in: str, check_out: str):
    """Booking screened APPROVED and confirmed (stay CONFIRMED)."""
    b = create_booking(api, property_id, guest_id, check_in, check_out)
    screen_booking(api, b["id"], "APPROVED")
    confirm_booking(api, b["id"])
    return get_success_data(api.get_booking(b["id"], PM))


# --------------------------------------------------------------------------- #
# Tier 3/4: owner-statement scenarios
# --------------------------------------------------------------------------- #
def setup_owner_statement_scenario(api, mgmt_fee_pct: int = 15, base_nightly_rate_cents: int = 10010,
                                   occupancy_tax_pct: int = 0, num_bookings: int = 3,
                                   checkin_clock: str = "2026-06-20T00:00:00Z"):
    """Owner + LISTED property + N consecutive 1-night CHECKED_OUT June-2026 bookings +
    a generated DRAFT OwnerStatement for 2026-06.

    Bookings check in on consecutive June nights starting 2026-06-05. They are created
    while the clock reads 2026-06-01, so the last-minute pricing factor applies per
    PRD §3.3. Returns {"owner", "property", "guest", "bookings", "statement"} where
    "statement" is the DRAFT statement (provisional split).
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    owner = create_owner(api, mgmt_fee_pct)
    prop = create_property(api, owner["id"], base_nightly_rate_cents=base_nightly_rate_cents,
                           cleaning_fee_cents=0)
    create_active_permit(api, prop["id"], occupancy_tax_pct)
    get_success_data(api.list_property(prop["id"], PM))
    guest = create_guest(api)

    bookings = []
    for i in range(num_bookings):
        ci = f"2026-06-{5 + i:02d}T00:00:00Z"
        co = f"2026-06-{6 + i:02d}T00:00:00Z"
        b = create_booking(api, prop["id"], guest["id"], ci, co)
        screen_booking(api, b["id"], "APPROVED")
        confirm_booking(api, b["id"])
        bookings.append(b)

    set_clock(api, checkin_clock)
    for b in bookings:
        check_in_booking(api, b["id"])
        check_out_booking(api, b["id"])

    statement = get_success_data(
        api.create_owner_statement(f.create_owner_statement_payload(owner["id"], 2026, 6), PM)
    )
    return {"owner": owner, "property": prop, "guest": guest, "bookings": bookings, "statement": statement}


# --------------------------------------------------------------------------- #
# Work-order helpers
# --------------------------------------------------------------------------- #
def create_completed_owner_work_order(api, property_id: str, cost_cents: int = 5000):
    """OWNER-billable work order walked to COMPLETED (not yet approved)."""
    wo = get_success_data(api.create_work_order(f.create_work_order_payload(property_id, cost_cents, "OWNER"), PM))
    vendor = create_vendor(api, "MAINTENANCE")
    get_success_data(api.assign_work_order(wo["id"], {"vendor_id": vendor["id"]}, PM))
    get_success_data(api.start_work_order(wo["id"], make_vendor_headers(vendor["id"])))
    get_success_data(api.complete_work_order(wo["id"], make_vendor_headers(vendor["id"])))
    return get_success_data(api.get_work_order(wo["id"], PM))


def create_approved_owner_work_order(api, property_id: str, owner_id: str, cost_cents: int = 5000):
    """OWNER-billable work order completed and APPROVED. Uses the Owner as approver when
    the cost is over the owner-approval threshold, otherwise the PropertyManager."""
    from .constants import OWNER_APPROVAL_THRESHOLD_CENTS
    wo = create_completed_owner_work_order(api, property_id, cost_cents)
    if cost_cents > OWNER_APPROVAL_THRESHOLD_CENTS:
        get_success_data(api.approve_work_order(wo["id"], make_owner_headers(owner_id)))
    else:
        get_success_data(api.approve_work_order(wo["id"], PM))
    return get_success_data(api.get_work_order(wo["id"], PM))


# --------------------------------------------------------------------------- #
# Turnover / inspection helpers
# --------------------------------------------------------------------------- #
def setup_cleaned_turnover(api, window_start: str = "2026-07-04T10:00:00Z",
                           window_end: str = "2026-07-04T13:00:00Z"):
    """LISTED property + booking + CLEANER + INSPECTOR + a turnover walked to CLEANED.

    Returns {"owner","property","permit","guest","booking","cleaner","inspector","turnover"}.
    """
    listed = create_listed_property(api)
    prop = listed["property"]
    guest = create_guest(api)
    booking = create_booking(api, prop["id"], guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    cleaner = create_vendor(api, "CLEANER")
    inspector = create_vendor(api, "INSPECTOR")
    turnover = get_success_data(
        api.create_turnover_task(
            f.create_turnover_task_payload(booking["id"], prop["id"], cleaner["id"], window_start, window_end),
            PM,
        )
    )
    get_success_data(api.start_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    get_success_data(api.complete_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    turnover = get_success_data(api.get_turnover_task(turnover["id"], PM))
    return {
        "owner": listed["owner"], "property": prop, "permit": listed["permit"],
        "guest": guest, "booking": booking, "cleaner": cleaner,
        "inspector": inspector, "turnover": turnover,
    }
