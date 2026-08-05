"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via PRD-declared endpoints (the harness
restarts the server, resetting both DB and logical clock to 2026-05-01T00:00:00Z, before every
test). Fixtures use get_success_data() (lenient) so setup failures surface as clear errors.

Identity threading: entity-backed roles (Resident, Carrier) always call ownership-gated
endpoints with make_<role>_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_property_payload, create_carrier_payload, create_resident_payload,
    create_locker_bank_payload, create_locker_payload, create_shelf_payload,
    create_package_payload, create_retail_return_payload, notify_payload,
    pickup_payload, pms_sync_payload, unique_tracking,
)
from .test_users import (
    TEST_USERS, make_resident_headers, make_carrier_headers, make_concierge_headers,
)

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]
PMS = TEST_USERS["pms_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────────
def advance_clock(iso: str):
    """Advance the server logical clock to an ISO 8601 instant (PM/PMS admin capability)."""
    return get_success_data(api_client.set_clock(iso, PM))


# ─── Tier 1: Single-entity primitives ─────────────────────────────────────────
def make_property(**overrides) -> dict:
    return get_success_data(api_client.create_property(create_property_payload(**overrides), PM))


def make_carrier(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(property_id, **overrides), PM))


def make_resident(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_resident(create_resident_payload(property_id, **overrides), PM))


def make_bank(property_id: str, storage_class: str = "AMBIENT", label: str = "A") -> dict:
    return get_success_data(api_client.create_locker_bank(
        create_locker_bank_payload(property_id, storage_class=storage_class, label=label), PM))


def make_locker(bank_id: str, size_class: str = "LARGE", storage_class: str = None) -> dict:
    payload = create_locker_payload(bank_id, size_class=size_class)
    if storage_class is not None:
        payload["storage_class"] = storage_class
    return get_success_data(api_client.create_locker(payload, PM))


def make_shelf(property_id: str, capacity: int, storage_class: str = "AMBIENT",
               zone: str = "Z1") -> dict:
    return get_success_data(api_client.create_shelf(
        create_shelf_payload(property_id, capacity=capacity,
                             storage_class=storage_class, zone=zone), PM))


def log_package(property_id: str, resident_id: str, carrier_id: str,
                headers: dict = None, **overrides) -> dict:
    """Scan/log an inbound package (LOGGED). Default actor is ConciergeStaff."""
    return get_success_data(api_client.create_package(
        create_package_payload(property_id, resident_id, carrier_id, **overrides),
        headers or CONCIERGE))


def notify_into_locker(package_id: str, locker_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.notify_package(
        package_id, notify_payload(storage_target="LOCKER", locker_id=locker_id),
        headers or CONCIERGE))


def notify_into_shelf(package_id: str, shelf_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.notify_package(
        package_id, notify_payload(storage_target="SHELF", shelf_id=shelf_id),
        headers or CONCIERGE))


# ─── Tier 2: Property + actors + storage topology ─────────────────────────────
def setup_property_carrier_resident(prop_overrides: dict = None,
                                    resident_overrides: dict = None) -> dict:
    """Active property + one carrier + one ACTIVE resident. Returns a context dict."""
    prop = make_property(**(prop_overrides or {}))
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"], **(resident_overrides or {}))
    return {"property": prop, "carrier": carrier, "resident": resident}


def setup_bank_with_lockers(prop_overrides: dict = None, bank_storage: str = "AMBIENT",
                            locker_specs=(("LARGE", None),),
                            resident_overrides: dict = None) -> dict:
    """Property + carrier + resident + one bank + N lockers.

    locker_specs is a sequence of (size_class, storage_class) tuples; storage_class None
    inherits the bank's class. Returns ctx with `bank` and `lockers` (list)."""
    ctx = setup_property_carrier_resident(prop_overrides, resident_overrides)
    bank = make_bank(ctx["property"]["id"], storage_class=bank_storage)
    lockers = [make_locker(bank["id"], size_class=sz, storage_class=sc)
               for (sz, sc) in locker_specs]
    ctx["bank"] = bank
    ctx["lockers"] = lockers
    return ctx


# ─── Tier 3: Package lifecycle shortcuts ──────────────────────────────────────
def setup_notified_locker_package(prop_overrides: dict = None,
                                  resident_overrides: dict = None,
                                  bank_storage: str = "AMBIENT",
                                  locker_size: str = "LARGE",
                                  locker_storage: str = None,
                                  pkg_size: str = "MEDIUM",
                                  pkg_storage_type: str = "AMBIENT",
                                  tracking_number: str = None) -> dict:
    """Full chain: property -> carrier -> resident -> bank -> locker -> log package ->
    notify into that locker (AWAITING_PICKUP). Returns ctx with `package`, `locker`,
    `bank` and the minted `pickup_code`."""
    ctx = setup_bank_with_lockers(
        prop_overrides, bank_storage=bank_storage,
        locker_specs=((locker_size, locker_storage),),
        resident_overrides=resident_overrides)
    pkg_kwargs = {"size_class": pkg_size, "storage_type": pkg_storage_type}
    if tracking_number is not None:
        pkg_kwargs["tracking_number"] = tracking_number
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"],
                      **pkg_kwargs)
    notified = notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])
    ctx["locker"] = ctx["lockers"][0]
    ctx["package"] = notified
    ctx["pickup_code"] = notified.get("pickup_code")
    return ctx


def setup_awaiting_shelf_packages(prop_overrides: dict = None, capacity: int = 2,
                                  num_awaiting: int = 2, storage_class: str = "AMBIENT") -> dict:
    """Property + carrier + resident + one shelf holding `num_awaiting` AWAITING packages.
    Returns ctx with `shelf` and `packages` (list of the notified packages)."""
    ctx = setup_property_carrier_resident(prop_overrides)
    shelf = make_shelf(ctx["property"]["id"], capacity=capacity, storage_class=storage_class)
    packages = []
    for _ in range(num_awaiting):
        pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"],
                          size_class="MEDIUM", storage_type="AMBIENT")
        packages.append(notify_into_shelf(pkg["id"], shelf["id"]))
    ctx["shelf"] = shelf
    ctx["packages"] = packages
    return ctx


def setup_return_initiated_package(concierge_user_id: str,
                                   prop_overrides: dict = None,
                                   clock_at: str = None) -> dict:
    """Property/locker/package chain, then return-initiate as ConciergeStaff `concierge_user_id`
    (recorded into return_initiated_by_user_id). Returns ctx with the RETURN_INITIATED package."""
    ctx = setup_notified_locker_package(prop_overrides=prop_overrides)
    if clock_at is not None:
        advance_clock(clock_at)
    initiated = get_success_data(api_client.return_initiate(
        ctx["package"]["id"], make_concierge_headers(concierge_user_id)))
    ctx["package"] = initiated
    ctx["return_initiated_by"] = concierge_user_id
    return ctx


# ─── Tier 4: Retail-return staging ────────────────────────────────────────────
def setup_staged_retail_return(prop_overrides: dict = None,
                               verify: bool = False) -> dict:
    """Property + carrier + resident + one dropped-off RetailReturn (as the owning resident).
    If verify=True, advance it to AWAITING_CARRIER. Returns ctx with `retail_return`."""
    ctx = setup_property_carrier_resident(prop_overrides)
    rr = get_success_data(api_client.create_retail_return(
        create_retail_return_payload(ctx["property"]["id"], ctx["resident"]["id"],
                                     ctx["carrier"]["id"]),
        make_resident_headers(ctx["resident"]["id"])))
    if verify:
        rr = get_success_data(api_client.verify_label(rr["id"], CONCIERGE))
    ctx["retail_return"] = rr
    return ctx


# ─── Small utilities used across suites ───────────────────────────────────────
def get_property(property_id: str) -> dict:
    return get_success_data(api_client.get_property(property_id, PM))


def get_locker(locker_id: str) -> dict:
    return get_success_data(api_client.get_locker(locker_id, PM))


def get_package(package_id: str) -> dict:
    return get_success_data(api_client.get_package(package_id, PM))


def get_bank(bank_id: str) -> dict:
    return get_success_data(api_client.get_locker_bank(bank_id, PM))


def get_resident(resident_id: str) -> dict:
    return get_success_data(api_client.get_resident(resident_id, PM))


def list_package_notifications(package_id: str) -> list:
    resp = api_client.list_notifications(package_id, PM, params={"limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("items", data)


def list_package_charges(package_id: str) -> list:
    resp = api_client.list_charges(package_id, PM, params={"limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("items", data)
