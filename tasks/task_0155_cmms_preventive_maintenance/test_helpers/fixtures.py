"""Composite setup helpers.

Each test runs against an empty database (the server is restarted before every
test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Setup steps use get_success_data() (lenient) so a setup
failure surfaces as a clear "Setup step failed" message rather than a confusing
assertion error inside a test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_technician_headers
from .factories import (
    create_site_payload,
    create_spare_part_payload,
    create_technician_payload,
    create_asset_payload,
    create_pm_schedule_payload,
    create_work_order_payload,
    create_reservation_payload,
    create_downtime_event_payload,
    create_warranty_claim_payload,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


# --- Clock ----------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Pin the server clock to a known UTC instant."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


# --- Tier 1/2: foundational records ---------------------------------------

def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), MANAGER))


def create_spare_part(**overrides) -> dict:
    return get_success_data(
        api_client.create_spare_part(create_spare_part_payload(**overrides), CLERK)
    )


def create_technician(**overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_technician_payload(**overrides), MANAGER)
    )


def create_asset(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(create_asset_payload(site_id, **overrides), MANAGER)
    )


def create_pm_schedule(asset_id, trigger_type, **overrides) -> dict:
    return get_success_data(
        api_client.create_pm_schedule(
            asset_id, create_pm_schedule_payload(trigger_type, **overrides), PLANNER
        )
    )


def create_meter_reading(asset_id, value, reading_at) -> dict:
    return get_success_data(
        api_client.create_meter_reading(
            asset_id, {"value": value, "reading_at": reading_at},
            TEST_USERS["technician_headers"],
        )
    )


def setup_site_and_asset(asset_overrides=None, site_overrides=None):
    """Most common base: one site + one OPERATIONAL asset. Returns (site, asset)."""
    site = create_site(**(site_overrides or {}))
    asset = create_asset(site["id"], **(asset_overrides or {}))
    return site, asset


# --- Tier 3: work-order lifecycle shortcuts --------------------------------

def create_corrective_work_order(asset_id, **overrides) -> dict:
    """Create a DRAFT corrective work order."""
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(asset_id, **overrides), PLANNER)
    )


def release_to_queue(wo_id) -> dict:
    return get_success_data(api_client.release_to_queue(wo_id, PLANNER))


def assign(wo_id, technician_id) -> dict:
    return get_success_data(
        api_client.assign_work_order(wo_id, {"technician_id": technician_id}, PLANNER)
    )


def start(wo_id, technician_id) -> dict:
    return get_success_data(
        api_client.start_work_order(wo_id, make_technician_headers(technician_id))
    )


def close(wo_id, technician_id, actual_cost_cents) -> dict:
    return get_success_data(
        api_client.close_work_order(
            wo_id, {"actual_cost_cents": actual_cost_cents},
            make_technician_headers(technician_id),
        )
    )


def setup_assigned_work_order(asset_id, technician_id, **wo_overrides):
    """DRAFT -> UNASSIGNED -> ASSIGNED. Returns the ASSIGNED work order dict."""
    wo = create_corrective_work_order(asset_id, **wo_overrides)
    release_to_queue(wo["id"])
    return assign(wo["id"], technician_id)


def setup_in_progress_work_order(asset_id, technician_id, **wo_overrides):
    """DRAFT -> ... -> IN_PROGRESS. Returns the IN_PROGRESS work order dict."""
    wo = setup_assigned_work_order(asset_id, technician_id, **wo_overrides)
    return start(wo["id"], technician_id)


def setup_closed_work_order(asset_id, technician_id, actual_cost_cents, **wo_overrides):
    """DRAFT -> ... -> CLOSED. Returns the CLOSED work order dict."""
    wo = setup_in_progress_work_order(asset_id, technician_id, **wo_overrides)
    return close(wo["id"], technician_id, actual_cost_cents)


def setup_site_asset_tech(
    asset_overrides=None, tech_overrides=None, site_overrides=None
):
    """Site + asset + a technician. Returns (site, asset, technician)."""
    site, asset = setup_site_and_asset(asset_overrides, site_overrides)
    tech = create_technician(**(tech_overrides or {}))
    return site, asset, tech


def setup_closed_work_order_full(
    actual_cost_cents=100_000,
    asset_overrides=None,
    tech_overrides=None,
    site_overrides=None,
    wo_overrides=None,
):
    """Site + asset + technician + a CLOSED work order.

    Returns (site, asset, technician, closed_work_order).
    """
    site, asset, tech = setup_site_asset_tech(asset_overrides, tech_overrides, site_overrides)
    # MASTER skill clears the gate for any severity by default; callers can
    # still override via tech_overrides/wo_overrides.
    closed = setup_closed_work_order(
        asset["id"], tech["id"], actual_cost_cents, **(wo_overrides or {})
    )
    return site, asset, tech, closed


# --- Tier 4: reservations --------------------------------------------------

def reserve(wo_id, spare_part_id, qty, expected_spare_part_version) -> dict:
    return get_success_data(
        api_client.create_reservation(
            wo_id,
            create_reservation_payload(spare_part_id, qty, expected_spare_part_version),
            CLERK,
        )
    )


def commit_parts(wo_id) -> dict:
    return get_success_data(api_client.commit_parts(wo_id, CLERK))


def setup_unassigned_wo_with_part(
    on_hand_qty=10, unit_cost_cents=1000, sku="PART-1", asset_overrides=None
):
    """Site + asset + spare part + an UNASSIGNED work order (no reservation yet).

    Returns (site, asset, part, work_order). The part dict carries its current
    version so callers can pass expected_spare_part_version.
    """
    site, asset = setup_site_and_asset(asset_overrides)
    part = create_spare_part(sku=sku, on_hand_qty=on_hand_qty, unit_cost_cents=unit_cost_cents)
    wo = create_corrective_work_order(asset["id"])
    release_to_queue(wo["id"])
    return site, asset, part, wo


def setup_committed_in_progress_wo(
    on_hand_qty=10, qty=3, unit_cost_cents=5000, sku="PART-C"
):
    """An IN_PROGRESS work order with one COMMITTED reservation.

    Returns (asset, technician, part, work_order, reservation).
    """
    site, asset, tech = setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
    part = create_spare_part(sku=sku, on_hand_qty=on_hand_qty, unit_cost_cents=unit_cost_cents)
    wo = create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=3)
    release_to_queue(wo["id"])
    assign(wo["id"], tech["id"])
    reservation = reserve(wo["id"], part["id"], qty, part["version"])
    start(wo["id"], tech["id"])
    commit_parts(wo["id"])
    return asset, tech, part, wo, reservation


# --- Tier 5: downtime ------------------------------------------------------

def open_downtime(asset_id, reason_code, started_at, work_order_id=None) -> dict:
    payload = create_downtime_event_payload(reason_code, started_at)
    if work_order_id is not None:
        payload["work_order_id"] = work_order_id
    return get_success_data(
        api_client.create_downtime_event(asset_id, payload, TEST_USERS["technician_headers"])
    )


def resolve_downtime(downtime_id, ended_at) -> dict:
    return get_success_data(
        api_client.resolve_downtime_event(
            downtime_id, {"ended_at": ended_at}, TEST_USERS["technician_headers"]
        )
    )


# --- Tier 5: warranty ------------------------------------------------------

def submit_claim(asset_id, work_order_id, claim_type) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(asset_id, work_order_id, claim_type), WARRANTY
        )
    )


def approve_claim(claim_id, decision_reason="approved") -> dict:
    return get_success_data(
        api_client.approve_claim(claim_id, {"decision_reason": decision_reason}, WARRANTY)
    )


def deny_claim(claim_id, decision_reason="denied") -> dict:
    return get_success_data(
        api_client.deny_claim(claim_id, {"decision_reason": decision_reason}, WARRANTY)
    )


def setup_warranted_closed_wo_with_claim(
    claim_type="REPAIR",
    actual_cost_cents=100_000,
    acquisition_cost_cents=500_000,
    warranty_cost_cap_cents=None,
    warranty_expires_at="2027-01-01T00:00:00Z",
    closed_at_clock="2026-02-01T00:00:00Z",
):
    """Warranted asset + a CLOSED work order + a SUBMITTED claim against it.

    The clock is pinned to closed_at_clock before the close so closed_at falls
    inside coverage. Returns (site, asset, technician, work_order, claim).
    """
    set_clock(closed_at_clock)
    asset_overrides = {
        "acquisition_cost_cents": acquisition_cost_cents,
        "warranty_expires_at": warranty_expires_at,
    }
    if warranty_cost_cap_cents is not None:
        asset_overrides["warranty_cost_cap_cents"] = warranty_cost_cap_cents
    site, asset, tech = setup_site_asset_tech(
        asset_overrides=asset_overrides, tech_overrides={"skill_level": "MASTER"}
    )
    closed = setup_closed_work_order(asset["id"], tech["id"], actual_cost_cents)
    claim = submit_claim(asset["id"], closed["id"], claim_type)
    return site, asset, tech, closed, claim


# --- Generic getters used by triggers --------------------------------------

def get_asset(asset_id, headers=None) -> dict:
    return get_success_data(api_client.get_asset(asset_id, headers or MANAGER))


def get_spare_part(part_id, headers=None) -> dict:
    return get_success_data(api_client.get_spare_part(part_id, headers or CLERK))


def get_site(site_id, headers=None) -> dict:
    return get_success_data(api_client.get_site(site_id, headers or MANAGER))


def get_work_order(wo_id, headers=None) -> dict:
    return get_success_data(api_client.get_work_order(wo_id, headers or PLANNER))


def get_pm_schedule(schedule_id, headers=None) -> dict:
    return get_success_data(api_client.get_pm_schedule(schedule_id, headers or PLANNER))


def get_warranty_claim(claim_id, headers=None) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, headers or WARRANTY))


def get_reservation(reservation_id, headers=None) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, headers or CLERK))
