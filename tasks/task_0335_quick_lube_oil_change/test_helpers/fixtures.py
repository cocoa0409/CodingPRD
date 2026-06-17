"""Composite setup helpers for the Quick Lube & Oil Change API.

These encapsulate the multi-step API call sequences that bring the system into the
state a test needs to assert against. All setup calls go through get_success_data()
(the lenient 2xx validator) so a broken precondition surfaces as a clear "Setup step
failed" error rather than a confusing downstream assertion failure.

Identity threading: Technician and FleetManager are entity-backed roles, so every
ownership-gated call uses make_technician_headers(tech_id) / make_fleet_manager_headers
(account_id) with the real entity id.

The harness restarts the server (empty DB) before each test, so every fixture builds
its full precondition chain from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_shop_payload,
    create_service_package_payload,
    create_inspection_item_payload,
    create_coupon_payload,
    create_fleet_account_payload,
    create_vehicle_payload,
    create_bay_payload,
    create_technician_payload,
    create_queue_ticket_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_fleet_manager_headers,
)

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]

DEFAULT_CLOCK = "2026-06-14T09:00:00Z"


# ─── Clock ────────────────────────────────────────────

def set_clock(iso: str = DEFAULT_CLOCK):
    """Pin the server clock to a fixed instant (PRD §3.12). ShopManager-only."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, SM))


# ─── Tier 1: Catalog primitives ───────────────────────

def create_shop(clock: str = DEFAULT_CLOCK, **overrides):
    """Set the clock then create a shop. Returns the shop dict."""
    set_clock(clock)
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), SM))


def create_package(shop_id, **overrides):
    return get_success_data(
        api_client.create_service_package(create_service_package_payload(shop_id, **overrides), SM)
    )


def create_inspection_item(shop_id, **overrides):
    return get_success_data(
        api_client.create_inspection_item(create_inspection_item_payload(shop_id, **overrides), SM)
    )


def create_coupon(shop_id, **overrides):
    return get_success_data(
        api_client.create_coupon(create_coupon_payload(shop_id, **overrides), SM)
    )


def create_fleet_account(shop_id, **overrides):
    return get_success_data(
        api_client.create_fleet_account(create_fleet_account_payload(shop_id, **overrides), SM)
    )


def create_bay(shop_id, **overrides):
    return get_success_data(api_client.create_bay(create_bay_payload(shop_id, **overrides), SM))


def create_technician(shop_id, **overrides):
    return get_success_data(
        api_client.create_technician(create_technician_payload(shop_id, **overrides), SM)
    )


def create_retail_vehicle(shop_id, **overrides):
    """Register a retail (no fleet) vehicle as ServiceAdvisor."""
    return get_success_data(api_client.create_vehicle(create_vehicle_payload(shop_id, **overrides), SA))


def create_fleet_vehicle(shop_id, fleet_account_id, **overrides):
    """Register a fleet vehicle as the owning FleetManager (entity-backed identity)."""
    payload = create_vehicle_payload(shop_id, fleet_account_id=fleet_account_id, **overrides)
    headers = make_fleet_manager_headers(fleet_account_id)
    return get_success_data(api_client.create_vehicle(payload, headers))


def create_queue_ticket(shop_id, vehicle_id, package_id):
    return get_success_data(
        api_client.create_queue_ticket(
            create_queue_ticket_payload(shop_id, vehicle_id, package_id), SA
        )
    )


# ─── Tier 2: Base scenarios ───────────────────────────

def setup_shop_with_catalog(clock: str = DEFAULT_CLOCK, package_overrides=None,
                            bay_overrides=None, tech_overrides=None):
    """Shop + one package + one OPEN bay + one technician. Returns a dict of entities."""
    shop = create_shop(clock)
    pkg = create_package(shop["id"], **(package_overrides or {}))
    bay = create_bay(shop["id"], **(bay_overrides or {}))
    tech = create_technician(shop["id"], **(tech_overrides or {}))
    return {"shop": shop, "package": pkg, "bay": bay, "technician": tech}


def create_direct_work_order(shop_id, vehicle_id, bay_id, package_id, odometer_in, **overrides):
    """Direct (non-queue) work-order creation as ServiceAdvisor. Returns the DRAFT order."""
    payload = create_work_order_payload(shop_id, vehicle_id, bay_id, package_id, odometer_in, **overrides)
    return get_success_data(api_client.create_work_order(payload, SA))


def setup_draft_work_order(clock: str = DEFAULT_CLOCK, package_overrides=None,
                           vehicle_overrides=None, wo_overrides=None,
                           with_technician=True, tech_overrides=None):
    """Shop + package + bay + (optional technician) + retail vehicle + a DRAFT work order
    occupying the bay. Returns a dict including 'work_order'."""
    base = setup_shop_with_catalog(clock, package_overrides=package_overrides,
                                   tech_overrides=tech_overrides)
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    odo = (vehicle_overrides or {}).get("odometer", 1000)
    veh = create_retail_vehicle(shop["id"], **(vehicle_overrides or {}))
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], odo, **(wo_overrides or {}))
    result = {"shop": shop, "package": pkg, "bay": bay, "vehicle": veh, "work_order": wo}
    if with_technician:
        result["technician"] = tech
    return result


# ─── Tier 3: Service-status lifecycle shortcuts ───────

def claim(work_order_id, technician_id):
    headers = make_technician_headers(technician_id)
    return get_success_data(
        api_client.claim_work_order(work_order_id, {"technician_id": technician_id}, headers)
    )


def start(work_order_id, technician_id):
    return get_success_data(api_client.start_work_order(work_order_id, make_technician_headers(technician_id)))


def begin_inspection(work_order_id, technician_id):
    return get_success_data(api_client.begin_inspection(work_order_id, make_technician_headers(technician_id)))


def finish_inspection(work_order_id, technician_id):
    return get_success_data(api_client.finish_inspection(work_order_id, make_technician_headers(technician_id)))


def mark_ready(work_order_id, technician_id):
    return get_success_data(api_client.mark_ready(work_order_id, make_technician_headers(technician_id)))


def add_line(work_order_id, technician_id, inspection_item_id, expected_work_order_version):
    headers = make_technician_headers(technician_id)
    payload = {
        "inspection_item_id": inspection_item_id,
        "expected_work_order_version": expected_work_order_version,
    }
    return get_success_data(api_client.add_line(work_order_id, payload, headers))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, SA))


def authorize(work_order_id, payment_method):
    return get_success_data(
        api_client.authorize_payment(work_order_id, {"payment_method": payment_method}, SA)
    )


def capture(work_order_id):
    return get_success_data(api_client.capture_payment(work_order_id, SA))


def void_payment(work_order_id):
    return get_success_data(api_client.void_payment(work_order_id, SA))


def complete(work_order_id):
    return get_success_data(api_client.complete_work_order(work_order_id, SA))


def cancel_work_order(work_order_id):
    return get_success_data(api_client.cancel_work_order(work_order_id, SA))


def claim_start(work_order_id, technician_id):
    """Claim then start (DRAFT -> IN_SERVICE). Returns the IN_SERVICE order."""
    claim(work_order_id, technician_id)
    return start(work_order_id, technician_id)


def drive_to_ready(work_order_id, technician_id):
    """Claim -> start -> mark-ready (no inspection lines). Returns the READY order."""
    claim_start(work_order_id, technician_id)
    return mark_ready(work_order_id, technician_id)


def drive_to_paid(work_order_id, technician_id, payment_method="CASH"):
    """Claim -> start -> mark-ready -> authorize -> capture. Returns the PAID order."""
    drive_to_ready(work_order_id, technician_id)
    authorize(work_order_id, payment_method)
    return capture(work_order_id)


def drive_to_completed(work_order_id, technician_id, payment_method="CASH"):
    """Full lifecycle through COMPLETED. Returns the COMPLETED order."""
    drive_to_paid(work_order_id, technician_id, payment_method)
    return complete(work_order_id)


# ─── Tier 4: Pricing scenario builders ────────────────

def setup_ready_work_order(clock: str = DEFAULT_CLOCK, package_overrides=None,
                           vehicle_overrides=None, wo_overrides=None):
    """Build a retail order and drive it to READY (no inspection lines). Returns dict
    with 'work_order' refreshed to the READY state plus catalog entities."""
    s = setup_draft_work_order(clock, package_overrides=package_overrides,
                               vehicle_overrides=vehicle_overrides, wo_overrides=wo_overrides)
    ready = drive_to_ready(s["work_order"]["id"], s["technician"]["id"])
    s["work_order"] = ready
    return s


def setup_order_with_one_line_to_inspection(item_price_cents=4495, package_overrides=None,
                                            wo_overrides=None):
    """Shop+package+item+bay+tech+vehicle; order claimed, started, in INSPECTION with one
    upsell line added. Returns dict with 'work_order' (post-add), 'item', 'line'."""
    base = setup_shop_with_catalog(package_overrides=package_overrides)
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item = create_inspection_item(shop["id"], price_cents=item_price_cents)
    veh = create_retail_vehicle(shop["id"])
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000, **(wo_overrides or {}))
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    line = add_line(wo["id"], tech["id"], item["id"], in_insp["version"])
    wo_after = get_work_order(wo["id"])
    return {"shop": shop, "package": pkg, "bay": bay, "technician": tech,
            "vehicle": veh, "item": item, "work_order": wo_after, "line": line}


# ─── Tier 5: Queue / cascade builders ─────────────────

def setup_assigned_ticket(clock: str = DEFAULT_CLOCK):
    """Shop + one OPEN bay + vehicle + WAITING ticket, then assign it. Returns dict with
    'ticket' (ASSIGNED), 'bay', and the bay version observed before assign."""
    shop = create_shop(clock)
    pkg = create_package(shop["id"])
    bay = create_bay(shop["id"])
    veh = create_retail_vehicle(shop["id"])
    ticket = create_queue_ticket(shop["id"], veh["id"], pkg["id"])
    assigned = get_success_data(
        api_client.assign_queue_ticket(
            ticket["id"], {"bay_id": bay["id"], "expected_bay_version": bay["version"]}, SA
        )
    )
    return {"shop": shop, "package": pkg, "bay": bay, "vehicle": veh, "ticket": assigned}


def setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10,
                            package_overrides=None, clock: str = DEFAULT_CLOCK):
    """Fleet account + fleet vehicle + work order driven to READY. Returns dict with
    'fleet_account', 'vehicle', 'work_order' (READY), and catalog entities."""
    base = setup_shop_with_catalog(clock, package_overrides=package_overrides)
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    fleet = create_fleet_account(shop["id"], discount_pct=discount_pct,
                                 credit_limit_cents=credit_limit_cents)
    veh = create_fleet_vehicle(shop["id"], fleet["id"], odometer=6000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 6000)
    ready = drive_to_ready(wo["id"], tech["id"])
    return {"shop": shop, "package": pkg, "bay": bay, "technician": tech,
            "fleet_account": fleet, "vehicle": veh, "work_order": ready}
