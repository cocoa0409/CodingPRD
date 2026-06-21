"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Helpers use
get_success_data() (lenient) so setup failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.

Identity threading: after creating a Vendor (entity_backed role), every
ownership-gated call (pay-fee, confirm, withdraw) uses make_vendor_headers(vendor_id),
never the shared TEST_USERS["vendor_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_festival_payload, create_zone_payload, create_stage_payload,
    create_parking_lot_payload, create_camping_area_payload, create_ticket_payload,
    create_wristband_payload, create_vendor_payload, create_vendor_application_payload,
    create_performance_payload, create_parking_addon_payload, topup_payload, gate_scan_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── Clock helper ─────────────────────────────────────────────────────

def set_clock(iso8601: str):
    """Pin the server clock (drives voluntary refund day tiers)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, _DIRECTOR))


# ─── Tier 1: Festival creation & posture progression ──────────────────

def create_festival(start_date="2026-08-01", end_date="2026-08-03", name="Test Festival",
                    **overrides):
    """Create a PLANNING festival. Returns the festival entity."""
    payload = create_festival_payload(name=name, start_date=start_date, end_date=end_date,
                                      **overrides)
    return get_success_data(api_client.create_festival(payload, _DIRECTOR))


def create_zone(festival_id, code="A", slot_capacity=1):
    return get_success_data(api_client.create_zone(
        festival_id, create_zone_payload(code=code, slot_capacity=slot_capacity), _DIRECTOR))


def create_stage(festival_id, name="Main Stage", changeover_minutes=30):
    return get_success_data(api_client.create_stage(
        festival_id, create_stage_payload(name=name, changeover_minutes=changeover_minutes),
        _DIRECTOR))


def create_festival_with_zone_and_stage(start_date="2026-08-01", end_date="2026-08-03",
                                        name="Test Festival", zone_code="A",
                                        zone_slot_capacity=1, **overrides):
    """Planning festival + one zone + one stage (the open-sales precondition).
    Returns (festival, zone, stage)."""
    festival = create_festival(start_date=start_date, end_date=end_date, name=name, **overrides)
    zone = create_zone(festival["id"], code=zone_code, slot_capacity=zone_slot_capacity)
    stage = create_stage(festival["id"])
    return festival, zone, stage


def open_sales(festival_id):
    return get_success_data(api_client.open_sales(festival_id, _DIRECTOR))


def go_live(festival_id):
    return get_success_data(api_client.go_live(festival_id, _DIRECTOR))


def open_day(festival_id, day):
    return get_success_data(api_client.open_day(festival_id, {"day": day}, _DIRECTOR))


def weather_hold(festival_id):
    return get_success_data(api_client.weather_hold(festival_id, _DIRECTOR))


def create_on_sale_festival(start_date="2026-08-01", end_date="2026-08-03", name="On Sale F",
                            zone_code="A", zone_slot_capacity=1, **overrides):
    """Festival driven to ON_SALE (zone + stage created first). Returns (festival, zone, stage)."""
    festival, zone, stage = create_festival_with_zone_and_stage(
        start_date=start_date, end_date=end_date, name=name, zone_code=zone_code,
        zone_slot_capacity=zone_slot_capacity, **overrides)
    open_sales(festival["id"])
    festival = get_success_data(api_client.get_festival(festival["id"], _DIRECTOR))
    return festival, zone, stage


def create_live_festival(start_date="2026-08-01", end_date="2026-08-03", name="Live F",
                         zone_code="A", **overrides):
    """Festival driven to LIVE (current_festival_day 1). Returns (festival, zone, stage)."""
    festival, zone, stage = create_on_sale_festival(
        start_date=start_date, end_date=end_date, name=name, zone_code=zone_code, **overrides)
    go_live(festival["id"])
    festival = get_success_data(api_client.get_festival(festival["id"], _DIRECTOR))
    return festival, zone, stage


# ─── Tier 2: Ticket & wristband helpers ───────────────────────────────

def sell_ticket(festival_id, ticket_type="GA", day_count=2, purchaser_email="patron@example.com"):
    return get_success_data(api_client.create_ticket(
        festival_id,
        create_ticket_payload(ticket_type=ticket_type, day_count=day_count,
                              purchaser_email=purchaser_email),
        _BOXOFFICE))


def issue_wristband(festival_id, rfid_uid):
    return get_success_data(api_client.create_wristband(
        festival_id, create_wristband_payload(rfid_uid), _BOXOFFICE))


def activate_wristband(wristband_id, ticket_id):
    return get_success_data(api_client.activate_wristband(
        wristband_id, {"ticket_id": ticket_id}, _BOXOFFICE))


def topup(wristband_id, amount):
    return get_success_data(api_client.topup_wristband(
        wristband_id, topup_payload(amount), _BOXOFFICE))


def setup_active_wristband(festival, ticket_type="GA", day_count=2, rfid_uid="RF-1",
                           balance=None):
    """On a festival that is at least ON_SALE: sell a ticket, issue + activate a
    wristband, optionally top it up. Returns (ticket, wristband)."""
    ticket = sell_ticket(festival["id"], ticket_type=ticket_type, day_count=day_count)
    wristband = issue_wristband(festival["id"], rfid_uid)
    activate_wristband(wristband["id"], ticket["id"])
    if balance:
        topup(wristband["id"], balance)
        wristband = get_success_data(api_client.get_wristband(wristband["id"], _BOXOFFICE))
    return ticket, wristband


def setup_live_festival_with_active_wristband(start_date="2026-08-01", end_date="2026-08-03",
                                              name="LiveWB F", rfid_uid="RF-1", balance=None,
                                              day_count=2, **overrides):
    """ON_SALE festival -> sell ticket -> issue+activate wristband -> (optional topup)
    -> go LIVE. Returns (festival, ticket, wristband). The wristband is ACTIVE/OUTSIDE
    and the festival is LIVE, ready for gate scans."""
    festival, zone, stage = create_on_sale_festival(
        start_date=start_date, end_date=end_date, name=name, **overrides)
    ticket, wristband = setup_active_wristband(
        festival, day_count=day_count, rfid_uid=rfid_uid, balance=balance)
    go_live(festival["id"])
    festival = get_success_data(api_client.get_festival(festival["id"], _DIRECTOR))
    wristband = get_success_data(api_client.get_wristband(wristband["id"], _BOXOFFICE))
    return festival, ticket, wristband


def gate_enter(festival_id, wristband_id):
    return api_client.gate_scan(festival_id, gate_scan_payload(wristband_id, "ENTER"), _GATE)


def gate_exit(festival_id, wristband_id):
    return api_client.gate_scan(festival_id, gate_scan_payload(wristband_id, "EXIT"), _GATE)


# ─── Tier 3: Vendor application lifecycle ─────────────────────────────

def create_vendor(company_name="Test Vendor Co", contact_email="vendor@example.com"):
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(company_name=company_name, contact_email=contact_email),
        _VENDOR_MANAGER))


def submit_application(festival_id, vendor_id, zone_id, booth_tier="STANDARD",
                       day_count=2, power_addon=False):
    return get_success_data(api_client.create_vendor_application(
        festival_id,
        create_vendor_application_payload(vendor_id, zone_id, booth_tier=booth_tier,
                                          day_count=day_count, power_addon=power_addon),
        _VENDOR_MANAGER))


def setup_application_under_review(festival_id, zone, booth_tier="STANDARD", day_count=2,
                                   power_addon=False, vendor_name="Vendor Co"):
    """Register vendor + submit application + start review. Returns (vendor, application)
    with the application in UNDER_REVIEW. zone is the zone entity (carries its version)."""
    vendor = create_vendor(company_name=vendor_name,
                           contact_email=f"{vendor_name.replace(' ', '').lower()}@x.com")
    application = submit_application(festival_id, vendor["id"], zone["id"],
                                     booth_tier=booth_tier, day_count=day_count,
                                     power_addon=power_addon)
    get_success_data(api_client.start_review(application["id"], _VENDOR_MANAGER))
    application = get_success_data(api_client.get_vendor_application(application["id"], _VENDOR_MANAGER))
    return vendor, application


def approve_application(application_id, expected_zone_version):
    return get_success_data(api_client.approve_application(
        application_id, {"expected_zone_version": expected_zone_version}, _VENDOR_MANAGER))


def setup_approved_application(festival_id, zone, booth_tier="STANDARD", day_count=2,
                               power_addon=False, vendor_name="Vendor Co"):
    """Register vendor + submit + start-review + approve (with the zone's current
    version). Returns (vendor, application) in APPROVED state. zone must carry its
    current 'version' (read fresh after creation)."""
    vendor, application = setup_application_under_review(
        festival_id, zone, booth_tier=booth_tier, day_count=day_count,
        power_addon=power_addon, vendor_name=vendor_name)
    application = approve_application(application["id"], zone["version"])
    return vendor, application


def pay_fee(application_id, vendor_id, amount):
    """Ownership-gated: uses the entity-backed vendor's own id in the headers."""
    return get_success_data(api_client.pay_fee(
        application_id, {"amount": amount}, make_vendor_headers(vendor_id)))


def confirm_application(application_id, vendor_id):
    return get_success_data(api_client.confirm_application(
        application_id, make_vendor_headers(vendor_id)))


# ─── Tier 4: Performance scheduling ───────────────────────────────────

def schedule_performance(stage_id, artist_name, starts_at, ends_at):
    return get_success_data(api_client.create_performance(
        stage_id, create_performance_payload(artist_name, starts_at, ends_at), _DIRECTOR))


# ─── Tier 5: Parking add-on helpers ───────────────────────────────────

def create_parking_lot(festival_id, capacity=10, price_per_pass=25.00, name="Lot A"):
    return get_success_data(api_client.create_parking_lot(
        festival_id, create_parking_lot_payload(name=name, capacity=capacity,
                                                 price_per_pass=price_per_pass), _DIRECTOR))


def create_camping_area(festival_id, capacity=10, price_per_night=30.00, name="Field A"):
    return get_success_data(api_client.create_camping_area(
        festival_id, create_camping_area_payload(name=name, capacity=capacity,
                                                  price_per_night=price_per_night), _DIRECTOR))


def sell_parking_addon(ticket_id, parking_lot_id, expected_lot_version):
    return get_success_data(api_client.create_addon(
        ticket_id,
        create_parking_addon_payload(parking_lot_id, expected_lot_version),
        _BOXOFFICE))


def get_lot_version(lot_id):
    lot = get_success_data(api_client.get_parking_lot(lot_id, _BOXOFFICE))
    return lot["version"]
