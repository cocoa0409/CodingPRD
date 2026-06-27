"""Cascades, cross-entity propagation, and compensating invariants.

Covers the transitive-cascade rule (project cancel -> visit cancel -> assignment
release; device fault -> scene de-deploy), the compensating-invariant rule
(firmware apply/rollback conserves firmware_version; provision/retire conserves
rack_units_used), and corner cascade claims (RMA advance-replace mint, RMA ship
return-repair retire, immediate consistency).
"""
from test_helpers import (
    validate_success, get_success_data, is_valid_uuid,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    DESIGNER, PM, TECH, SUPPORT,
    create_client, create_project, create_rack, setup_sent_proposal, accept_proposal,
    setup_provisioning_project, setup_provisioning_with_online_device,
    create_crew_member, create_visit, assign_crew, setup_active_contract_with_online_device,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / transitive_cascade / project_cancel_cascades_visit_cancel_then_assignment_release
# ===========================================================================

def _accepted_project_with_confirmed_visit_and_assignment():
    """ACCEPTED WEST project + rack + crew + CONFIRMED INSTALL visit with one
    ACTIVE assignment. Returns (project_id, visit_id, assignment_id, crew_id)."""
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN")
    visit = create_visit(project["id"], "2026-03-01T09:00:00Z", "2026-03-01T12:00:00Z",
                         visit_kind="INSTALL", crew_size_required=1)
    asg = assign_crew(project["id"], visit["id"], crew["id"], visit["version"])
    get_success_data(api_client.confirm_visit(project["id"], visit["id"], PM))
    return project["id"], visit["id"], asg["id"], crew["id"]


def test_project_cancel_cascades_visit_to_cancelled():
    """PRD §3.1: "Cancelling from ACCEPTED, PROVISIONING, or SCHEDULED cascades
    downward: every non-terminal visit on the project moves to CANCELLED (which in
    turn releases each visit's ACTIVE assignments), and every non-RETIRED device on
    the project's rack moves to RETIRED, releasing its rack units and management IP."

    Design: Difficulty/transitive_cascade/project_cancel_cascades_visit_cancel_then_assignment_release
    """
    project_id, visit_id, asg_id, _ = _accepted_project_with_confirmed_visit_and_assignment()
    data = validate_success(api_client.cancel_project(project_id, PM))
    assert data["status"] == "CANCELLED"
    visit = validate_success(api_client.get_visit(visit_id, PM))
    assert visit["status"] == "CANCELLED", "hop 2: visit cancelled by project cancel"


def test_project_cancel_cascades_assignment_release_and_zeroes_crew_count():
    """PRD §3.1: "every non-terminal visit on the project moves to CANCELLED (which
    in turn releases each visit's ACTIVE assignments)".
    PRD §3.7: "a released assignment frees the crew member's capacity so it no
    longer counts toward assigned_crew_count, the daily load, or the crew
    time-overlap check, and the visit's assigned_crew_count is recomputed."

    Design: Difficulty/transitive_cascade/project_cancel_cascades_visit_cancel_then_assignment_release
    """
    from test_helpers import validate_paginated
    project_id, visit_id, asg_id, _ = _accepted_project_with_confirmed_visit_and_assignment()
    validate_success(api_client.cancel_project(project_id, PM))
    # assigned_crew_count recomputed to 0 (released assignment no longer counts)
    listing = validate_success(api_client.get_visit(visit_id, PM))
    assert listing["assigned_crew_count"] == 0, "assigned_crew_count recomputed to 0"
    # the assignment row itself is RELEASED (hop 3, caused by the visit cancel)
    rows, _ = validate_paginated(api_client.list_visit_assignments_flat(visit_id, PM))
    target = [a for a in rows if a["id"] == asg_id]
    assert target and target[0]["status"] == "RELEASED", "hop 3: assignment released"


# ===========================================================================
# Difficulty / transitive_cascade / device_fault_cascades_scene_dedeploy
# ===========================================================================

def test_device_fault_dedeploys_scene_to_validated():
    """PRD §3.5: "A SupportEngineer may mark an ONLINE device FAULTED; doing so
    triggers a cross-entity cascade in which every DEPLOYED scene program whose
    device_ids includes this device is de-deployed back to VALIDATED".

    Design: Difficulty/transitive_cascade/device_fault_cascades_scene_dedeploy
    """
    ctx = setup_provisioning_with_online_device(region_code="WEST")
    project_id = ctx["project"]["id"]
    device_id = ctx["device"]["id"]
    scene = fx.setup_deployed_scene(project_id, [device_id], name="All On", action_count=1)
    device = validate_success(api_client.mark_faulted(device_id, SUPPORT))
    assert device["status"] == "FAULTED"
    scene_now = validate_success(api_client.get_scene(project_id, scene["id"], DESIGNER))
    assert scene_now["status"] == "VALIDATED", "scene de-deployed by the device fault"


def test_device_fault_sets_device_status_faulted():
    """PRD §3.5: "A SupportEngineer may mark an ONLINE device FAULTED".

    Design: Difficulty/transitive_cascade/device_fault_cascades_scene_dedeploy
    """
    ctx = setup_provisioning_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    fx.setup_deployed_scene(ctx["project"]["id"], [device_id], name="All On", action_count=1)
    device = validate_success(api_client.mark_faulted(device_id, SUPPORT))
    assert device["status"] == "FAULTED"


# ===========================================================================
# Difficulty / compensating_invariant / firmware_apply_rollback_restores_version_invariant
# ===========================================================================

def _provisioned_device():
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])
    return device["id"]


def test_firmware_apply_sets_version_then_rollback_restores_null():
    """PRD §3.10: "Applying captures the device's current firmware_version (which
    may be absent) into the update's prior_version, then sets the device's
    firmware_version to the target_version."
    PRD §3.10: "rollback is a compensation that restores the device's
    firmware_version to the exact prior_version captured at staging."

    Design: Difficulty/compensating_invariant/firmware_apply_rollback_restores_version_invariant
    """
    device_id = _provisioned_device()
    fw, applied_device = fx.apply_firmware(device_id, "3.4.1")
    assert applied_device["firmware_version"] == "3.4.1", "apply set firmware to target"
    update = validate_success(api_client.rollback_firmware_update(device_id, fw["id"], SUPPORT))
    assert update["status"] == "ROLLED_BACK"
    device = validate_success(api_client.get_device(device_id, TECH))
    assert device["firmware_version"] is None, (
        "rollback restores firmware_version to prior_version (null) — conserved")


def test_firmware_prior_version_captured_null_at_staging():
    """PRD §3.10: "Applying captures the device's current firmware_version (which
    may be absent) into the update's prior_version".

    Design: Difficulty/compensating_invariant/firmware_apply_rollback_restores_version_invariant
    """
    from test_helpers import validate_paginated
    device_id = _provisioned_device()
    fw, _ = fx.apply_firmware(device_id, "3.4.1")
    rows, _meta = validate_paginated(api_client.list_firmware_updates(device_id, SUPPORT))
    target = [u for u in rows if u["id"] == fw["id"]]
    assert target and target[0]["prior_version"] is None, "prior_version captured as null"


# ===========================================================================
# Difficulty / compensating_invariant / device_provision_retire_conserves_rack_units_used
# ===========================================================================

def test_provision_then_retire_conserves_rack_units_used():
    """PRD §3.4: "rack_units_used is kept reconciled as the sum of the rack_units of
    every device on the rack whose status is REGISTERED, PROVISIONED, ONLINE, or
    FAULTED; devices that have been RETIRED release their rack units and are
    excluded from the sum."
    PRD §3.5: "Retiring a provisioned device additionally releases its mgmt_ip and
    recomputes both rack_units_used and provisioned_device_count."

    Design: Difficulty/compensating_invariant/device_provision_retire_conserves_rack_units_used
    """
    ctx = setup_provisioning_project(region_code="WEST")
    rack_id = ctx["rack"]["id"]
    device = fx.register_device(rack_id, sku="C4-CTRL", category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])
    rack = validate_success(api_client.get_rack(ctx["project"]["id"], PM))[0]
    assert rack["rack_units_used"] == 2, "after provision"
    retired = validate_success(api_client.retire_device(device["id"], TECH))
    assert retired["status"] == "RETIRED"
    rack = validate_success(api_client.get_rack(ctx["project"]["id"], PM))[0]
    assert rack["rack_units_used"] == 0, "after retire (RU conserved, no drift)"


def test_provision_raises_rack_units_used_by_device_units():
    """PRD §3.5: "Provisioning assigns the device its mgmt_ip by the lowest-free
    rule, then recomputes the rack's rack_units_used and the project's
    provisioned_device_count."

    Design: Difficulty/compensating_invariant/device_provision_retire_conserves_rack_units_used
    """
    ctx = setup_provisioning_project(region_code="WEST")
    rack_id = ctx["rack"]["id"]
    device = fx.register_device(rack_id, sku="C4-CTRL", category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])
    rack = validate_success(api_client.get_rack(ctx["project"]["id"], PM))[0]
    assert rack["rack_units_used"] == 2


# ===========================================================================
# Corner / state_machines / rma_advance_replace_mints_replacement_device
# ===========================================================================

def test_rma_advance_replace_mints_replacement_device():
    """PRD §3.11: "If the resolution is ADVANCE_REPLACE, authorization performs a
    cross-aggregate cascade: it mints a new REGISTERED device on the same rack
    carrying the faulted device's sku, category, and rack_units, and records that
    new device's id in replacement_device_id."

    Design: Corner/state_machines/rma_advance_replace_mints_replacement_device
    """
    ctx = setup_active_contract_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    fx.fault_device(device_id)
    rma = fx.open_rma(device_id, ctx["contract"]["id"], resolution="ADVANCE_REPLACE")
    data = validate_success(api_client.authorize_rma(rma["id"], SUPPORT))
    assert data["status"] == "AUTHORIZED"
    assert is_valid_uuid(data["replacement_device_id"] or ""), "replacement_device_id set"
    repl = validate_success(api_client.get_device(data["replacement_device_id"], TECH))
    assert repl["rack_id"] == ctx["rack"]["id"]
    assert repl["status"] == "REGISTERED"
    faulted = validate_success(api_client.get_device(device_id, TECH))
    assert faulted["status"] == "FAULTED", "faulted device unchanged"


# ===========================================================================
# Corner / state_machines / rma_ship_return_repair_retires_faulted_device
# ===========================================================================

def test_rma_ship_return_repair_retires_faulted_device():
    """PRD §3.11: "Shipping an authorized ticket is permitted from AUTHORIZED; if
    the resolution is RETURN_REPAIR, shipping cascades the faulted device from
    FAULTED to RETIRED, releasing its mgmt_ip and rack units."

    Design: Corner/state_machines/rma_ship_return_repair_retires_faulted_device
    """
    ctx = setup_active_contract_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    fx.fault_device(device_id)
    rma = fx.open_rma(device_id, ctx["contract"]["id"], resolution="RETURN_REPAIR")
    get_success_data(api_client.authorize_rma(rma["id"], SUPPORT))
    data = validate_success(api_client.ship_rma(rma["id"], SUPPORT))
    assert data["status"] == "SHIPPED"
    device = validate_success(api_client.get_device(device_id, TECH))
    assert device["status"] == "RETIRED"
    rack = validate_success(api_client.get_rack(ctx["project"]["id"], PM))[0]
    assert rack["rack_units_used"] == 0, "RU released by retire"


# ===========================================================================
# Corner / consistency_model / immediate_consistency_provision_reflected_in_same_response
# ===========================================================================

def test_provision_immediately_reflected_in_rack_read():
    """PRD §3.4: "When a device is provisioned, the system assigns it a management
    IP from the rack's subnet by a deterministic lowest-free-address allocation".
    PRD §2.6: "The platform maintains immediate consistency between parent and
    child resources."

    Design: Corner/consistency_model/immediate_consistency_provision_reflected_in_same_response
    """
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="X", category="CONTROLLER", rack_units=2)
    provisioned = validate_success(api_client.provision_device(device["id"], TECH))
    assert provisioned["status"] == "PROVISIONED"
    assert provisioned["mgmt_ip"] == "10.20.0.1"
    rack = validate_success(api_client.get_rack(ctx["project"]["id"], PM))[0]
    assert rack["rack_units_used"] == 2, "immediate consistency in the following GET"
