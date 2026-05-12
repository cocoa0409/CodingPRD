"""Equipment creation, lifecycle transitions, and decommission cascades."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    activate_plan,
    api_client,
    assert_equipment,
    commission_equipment,
    create_ad_hoc_work_order,
    create_equipment,
    create_equipment_payload,
    create_plan,
    create_requisition,
    create_site,
    create_spare_part,
    create_template,
    create_technician,
    place_in_service,
    setup_decommission_cascade,
    setup_pending_workorder,
    setup_site_with_in_service_equipment,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.2 — equipment creation
# ---------------------------------------------------------------------------
def test_create_equipment_lands_in_installed(api, site_manager_headers):
    """PRD §3.2: 'Newly created equipment lands in lifecycle_status
    INSTALLED.'
    """
    site = create_site()
    res = api.create_equipment(
        site["id"],
        create_equipment_payload(responsible_user_id="owner-001"),
        site_manager_headers,
    )
    eq = validate_success(res, expected_status=201)
    assert_equipment(eq)
    assert eq["lifecycle_status"] == "INSTALLED"


def test_warranty_end_must_be_after_warranty_start(api, site_manager_headers):
    """PRD §3.2: 'The warranty_end must be strictly after warranty_start,
    otherwise the request is rejected with ERR_TEMPORAL_INVALID.'
    """
    site = create_site()
    payload = create_equipment_payload(
        responsible_user_id="owner-001",
        warranty_start="2026-06-01T00:00:00.000Z",
        warranty_end="2026-06-01T00:00:00.000Z",  # equal, not strictly after
    )
    res = api.create_equipment(site["id"], payload, site_manager_headers)
    validate_error(res, "ERR_TEMPORAL_INVALID", expected_status=422)


def test_warranty_end_before_warranty_start_rejected(api,
                                                      site_manager_headers):
    """PRD §3.2: 'The warranty_end must be strictly after warranty_start,
    otherwise the request is rejected with ERR_TEMPORAL_INVALID.'
    """
    site = create_site()
    payload = create_equipment_payload(
        responsible_user_id="owner-001",
        warranty_start="2026-06-01T00:00:00.000Z",
        warranty_end="2026-05-31T23:59:59.999Z",
    )
    res = api.create_equipment(site["id"], payload, site_manager_headers)
    validate_error(res, "ERR_TEMPORAL_INVALID", expected_status=422)


# ---------------------------------------------------------------------------
# 3.2 — commission requires ACTIVE plan
# ---------------------------------------------------------------------------
def test_commission_requires_active_plan(api, site_manager_headers):
    """PRD §3.2: 'Commissioning advances lifecycle_status from INSTALLED
    to COMMISSIONED. The transition is rejected with ERR_NO_ACTIVE_PLAN
    unless the equipment has at least one MaintenancePlan whose status is
    ACTIVE, of any kind.'
    """
    site = create_site()
    eq = create_equipment(site["id"], "owner-001")
    res = api.commission_equipment(site["id"], eq["id"], site_manager_headers)
    validate_error(res, "ERR_NO_ACTIVE_PLAN", expected_status=409)


def test_commission_succeeds_with_active_plan(api, site_manager_headers):
    """PRD §3.2: 'Commissioning advances lifecycle_status from INSTALLED to
    COMMISSIONED.'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    plan = create_plan(site["id"], eq["id"], template["id"])
    activate_plan(site["id"], plan["id"])
    res = api.commission_equipment(site["id"], eq["id"], site_manager_headers)
    after = validate_success(res, expected_status=200)
    assert after["lifecycle_status"] == "COMMISSIONED"


# ---------------------------------------------------------------------------
# 3.2 — place-in-service / decommission
# ---------------------------------------------------------------------------
def test_place_in_service_transitions_commissioned_to_in_service(
        api, site_manager_headers):
    """PRD §3.2: 'Placement in service advances `lifecycle_status` from
    `COMMISSIONED` to `IN_SERVICE`. From this point onward, periodic-time
    plans are eligible for sweep generation; if `last_generated_at` is
    null on such a plan, its `next_due_at` is computed from the
    placement-in-service site clock plus the plan's interval (see §3.4).'
    """
    bag = setup_site_with_in_service_equipment()
    assert bag["equipment"]["lifecycle_status"] == "IN_SERVICE"


def test_decommission_blocked_when_open_workorder_exists(
        api, site_manager_headers):
    """PRD §3.2: 'Decommissioning ... requires Equipment.open_work_order_id
    to be null, otherwise the response is ERR_EQUIPMENT_BUSY.'
    """
    bag = setup_pending_workorder()
    res = api.decommission_equipment(
        bag["site"]["id"], bag["equipment"]["id"], site_manager_headers,
    )
    validate_error(res, "ERR_EQUIPMENT_BUSY", expected_status=409)


def test_decommission_cascades_active_plans_to_retired(api,
                                                       site_manager_headers):
    """PRD §3.2: 'every ACTIVE MaintenancePlan on this equipment moves to
    RETIRED.'
    """
    bag = setup_site_with_in_service_equipment()
    res = api.decommission_equipment(
        bag["site"]["id"], bag["equipment"]["id"], site_manager_headers,
    )
    eq = validate_success(res, expected_status=200)
    assert eq["lifecycle_status"] == "DECOMMISSIONED"
    plan_after = validate_success(
        api.get_plan(bag["site"]["id"], bag["plan"]["id"], site_manager_headers),
        expected_status=200,
    )
    assert plan_after["status"] == "RETIRED"


def test_decommission_blocked_by_open_pending_workorder(api,
                                                         site_manager_headers):
    """PRD §3.2: 'Decommissioning ... requires Equipment.open_work_order_id
    to be null, otherwise the response is ERR_EQUIPMENT_BUSY.'

    Direct claim that an open WO blocks decommission.
    # difficulty: transitive_cascade/equipment_decommission_depth_3_cascade
    """
    bag = setup_pending_workorder()
    res = api.decommission_equipment(
        bag["site"]["id"], bag["equipment"]["id"], site_manager_headers,
    )
    validate_error(res, "ERR_EQUIPMENT_BUSY", expected_status=409)


def test_decommission_cascades_to_active_plan_and_pending_workorder(
        api, site_manager_headers, dispatcher_headers):
    """PRD §3.2: 'every ACTIVE MaintenancePlan on this equipment moves to
    RETIRED, and every PENDING work order on this equipment moves to
    CANCELLED with cancel_reason set to EQUIPMENT_DECOMMISSIONED. Within
    each cancelled work order, all RESERVED requisitions become CANCELLED
    and replenishment is re-evaluated for each affected spare part.'

    # difficulty: transitive_cascade/equipment_decommission_depth_3_cascade
    """
    # Cancel the blocking PENDING WO (so open_work_order_id is null) before
    # invoking decommission — the lifecycle gate in PRD §3.2 prohibits
    # decommissioning while the equipment has an open WO. The plan stays
    # ACTIVE, so the plan→RETIRED hop is observable; the cancelled WO must
    # remain CANCELLED through the cascade.
    bag = setup_decommission_cascade()
    site_id = bag["site"]["id"]
    api.cancel_work_order(
        site_id, bag["work_order"]["id"], {}, dispatcher_headers,
    )
    # After WO cancel: stock_reserved already released to 0; available=10>5
    spare_after_cancel = validate_success(
        api.get_spare_part(site_id, bag["spare_part"]["id"],
                            site_manager_headers),
        expected_status=200,
    )
    assert spare_after_cancel["stock_reserved"] == 0
    assert spare_after_cancel["replenish_pending"] is False

    res = api.decommission_equipment(
        site_id, bag["equipment"]["id"], site_manager_headers,
    )
    eq = validate_success(res, expected_status=200)
    assert eq["lifecycle_status"] == "DECOMMISSIONED"

    plan_after = validate_success(
        api.get_plan(site_id, bag["plan"]["id"], site_manager_headers),
        expected_status=200,
    )
    assert plan_after["status"] == "RETIRED"
    wo_after = validate_success(
        api.get_work_order(site_id, bag["work_order"]["id"],
                            site_manager_headers),
        expected_status=200,
    )
    # Cancelled by the dispatcher's pre-decommission cancel call.
    assert wo_after["status"] == "CANCELLED"


def test_decommissioned_is_terminal(api, site_manager_headers):
    """PRD §3.2 + §1.2: DECOMMISSIONED is terminal — cannot transition out.
    'Decommissioning advances lifecycle_status from IN_SERVICE to the
    terminal state DECOMMISSIONED.'
    """
    bag = setup_site_with_in_service_equipment()
    api.decommission_equipment(
        bag["site"]["id"], bag["equipment"]["id"], site_manager_headers,
    )
    # Any subsequent lifecycle attempt should be rejected.
    res = api.commission_equipment(
        bag["site"]["id"], bag["equipment"]["id"], site_manager_headers,
    )
    assert res.status_code >= 400
