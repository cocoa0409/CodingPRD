"""Validation gates, priority conflicts, and cross-entity state dependencies.

Covers the priority-pair-validation-conflict rule (state beats fiscal on project
activate; safety beats capacity on bring-online), the cross-entity-state-
dependency rule (project activate needs ACTIVE contract; RMA authorize needs
FAULTED device), and corner precondition/violation claims that surface a single
gate error.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    DESIGNER, PM, TECH, SUPPORT,
    create_client, create_project, create_rack, setup_sent_proposal, accept_proposal,
    setup_provisioning_project, setup_provisioning_with_online_device,
    setup_commissioned_project, setup_active_contract_with_online_device,
    create_crew_member, create_visit, assign_crew, create_contract,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / state_vs_fiscal_on_project_activate
# ===========================================================================

def test_activate_accepted_project_with_pending_contract_reports_invalid_state():
    """PRD §2.9: "The state precondition for a transition is checked seventh,
    yielding ERR_INVALID_STATE when the target is not in a state from which the
    requested transition is defined."
    PRD §3.1: "Bringing a COMMISSIONED project to ACTIVE ... requires that a
    contract for the project is ACTIVE, failing with ERR_CONTRACT_NOT_ACTIVE
    otherwise".

    The project is ACCEPTED (not COMMISSIONED) and the contract is PENDING; both
    the state precondition (priority 7) and the fiscal gate (priority 14) would
    fail, and the higher-priority state check wins.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_project_activate
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    create_contract(project["id"], plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    resp = api_client.activate_project(project["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    proj = validate_success(api_client.get_project(project["id"], PM))
    assert proj["status"] == "ACCEPTED", "project unchanged"


def test_activate_accepted_project_does_not_report_fiscal_error():
    """PRD §2.9: "the first failure determines the error returned. ... The state
    precondition for a transition is checked seventh, yielding ERR_INVALID_STATE
    when the target is not in a state from which the requested transition is
    defined."

    The same ACCEPTED-project-with-PENDING-contract request must surface the state
    error, not the fiscal ERR_CONTRACT_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_project_activate
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    create_contract(project["id"], plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    resp = api_client.activate_project(project["id"], PM)
    body = resp.json()["data"]
    assert body["error_id"] == "ERR_INVALID_STATE", (
        f"state priority 7 beats fiscal priority 14, got {body['error_id']}")


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / safety_vs_capacity_on_device_bring_online
# ===========================================================================

def test_bring_online_without_firmware_reports_firmware_required():
    """PRD §3.5: "Bringing a device online ... requires that the device's
    firmware_version has been set by an applied firmware update, otherwise
    ERR_FIRMWARE_REQUIRED, and it recomputes the project's
    provisioned_device_count."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_capacity_on_device_bring_online
    """
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])  # PROVISIONED, no firmware
    resp = api_client.bring_online(device["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_FIRMWARE_REQUIRED)


def test_bring_online_without_firmware_leaves_device_provisioned():
    """PRD §3.5: "Bringing a device online, also a LowVoltageTech action, moves it
    from PROVISIONED to ONLINE or recovers it from FAULTED to ONLINE; either way it
    requires that the device's firmware_version has been set by an applied firmware
    update, otherwise ERR_FIRMWARE_REQUIRED".

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_capacity_on_device_bring_online
    """
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])
    api_client.bring_online(device["id"], TECH)
    data = validate_success(api_client.get_device(device["id"], TECH))
    assert data["status"] == "PROVISIONED", "device unchanged after rejected bring-online"


# ===========================================================================
# Difficulty / cross_entity_state_dependency / project_activate_requires_contract_active
# ===========================================================================

def test_commissioned_project_activate_blocked_by_pending_contract():
    """PRD §3.1: "Bringing a COMMISSIONED project to ACTIVE is a deliberate
    project-manager action and the final fiscal gate of the build. It requires that
    a contract for the project is ACTIVE, failing with ERR_CONTRACT_NOT_ACTIVE
    otherwise, and that open_change_order_count is exactly zero, failing with
    ERR_OPEN_CHANGE_ORDERS otherwise."

    Design: Difficulty/cross_entity_state_dependency/project_activate_requires_contract_active
    """
    ctx = setup_commissioned_project(region_code="WEST")
    project_id = ctx["project"]["id"]
    assert ctx["project"]["status"] == "COMMISSIONED", "precondition: project commissioned"
    # PENDING contract present, not yet activated
    create_contract(project_id, plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    resp = api_client.activate_project(project_id, PM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


def test_commissioned_project_activates_after_contract_active():
    """PRD §3.1: "It requires that a contract for the project is ACTIVE, failing
    with ERR_CONTRACT_NOT_ACTIVE otherwise, and that open_change_order_count is
    exactly zero".

    Design: Difficulty/cross_entity_state_dependency/project_activate_requires_contract_active
    """
    ctx = setup_commissioned_project(region_code="WEST")
    project_id = ctx["project"]["id"]
    fx.setup_active_contract(project_id, plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    data = validate_success(api_client.activate_project(project_id, PM))
    assert data["status"] == "ACTIVE", "activation succeeds once contract is ACTIVE"


# ===========================================================================
# Difficulty / cross_entity_state_dependency / rma_authorize_requires_device_faulted
# ===========================================================================

def test_rma_authorize_on_online_device_rejected():
    """PRD §3.11: "Authorizing an opened ticket is a SupportEngineer action
    requiring that the contract is ACTIVE, otherwise ERR_CONTRACT_NOT_ACTIVE, and
    that the device is FAULTED, otherwise ERR_DEVICE_NOT_FAULTED."

    Design: Difficulty/cross_entity_state_dependency/rma_authorize_requires_device_faulted
    """
    ctx = setup_active_contract_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    online = validate_success(api_client.get_device(device_id, TECH))
    assert online["status"] == "ONLINE", "device ONLINE before authorize"
    rma = fx.open_rma(device_id, ctx["contract"]["id"], resolution="RETURN_REPAIR")
    resp = api_client.authorize_rma(rma["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_FAULTED)


def test_rma_authorize_succeeds_once_device_faulted():
    """PRD §3.11: "Authorizing an opened ticket is a SupportEngineer action
    requiring that the contract is ACTIVE, otherwise ERR_CONTRACT_NOT_ACTIVE, and
    that the device is FAULTED, otherwise ERR_DEVICE_NOT_FAULTED."

    Design: Difficulty/cross_entity_state_dependency/rma_authorize_requires_device_faulted
    """
    ctx = setup_active_contract_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    rma = fx.open_rma(device_id, ctx["contract"]["id"], resolution="RETURN_REPAIR")
    fx.fault_device(device_id)
    data = validate_success(api_client.authorize_rma(rma["id"], SUPPORT))
    assert data["status"] == "AUTHORIZED"


# ===========================================================================
# Corner / state_machines / retire_device_with_open_rma_returns_device_has_open_rma
# ===========================================================================

def test_retire_device_with_open_rma_rejected():
    """PRD §3.5: "it is blocked while the device is referenced by an RMA ticket in
    OPENED, AUTHORIZED, or SHIPPED state, failing with ERR_DEVICE_HAS_OPEN_RMA."

    Design: Corner/state_machines/retire_device_with_open_rma_returns_device_has_open_rma
    """
    # PRD §3.5: retire is reachable from REGISTERED, PROVISIONED, or ONLINE, and
    # is blocked while an open RMA references the device. Keep the device ONLINE
    # (a retirable state) so the RMA-block — not the state precondition — is
    # exercised. PRD §3.11 places no device-state gate on opening an RMA.
    ctx = setup_active_contract_with_online_device(region_code="WEST")
    device_id = ctx["device"]["id"]
    fx.open_rma(device_id, ctx["contract"]["id"], resolution="RETURN_REPAIR")
    resp = api_client.retire_device(device_id, TECH)
    validate_error(resp, ApiErrorId.ERR_DEVICE_HAS_OPEN_RMA)


# ===========================================================================
# Corner / state_machines / firmware_apply_not_newer_returns_firmware_not_newer
# ===========================================================================

def test_firmware_apply_not_newer_rejected():
    """PRD §3.10: "Applying a staged update ... only when the target_version is
    strictly greater by semver than the device's current firmware_version, or the
    device has no firmware version yet, otherwise ERR_FIRMWARE_NOT_NEWER."

    Design: Corner/state_machines/firmware_apply_not_newer_returns_firmware_not_newer
    """
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])
    fx.apply_firmware(device["id"], "3.4.1")  # device now at 3.4.1
    fw2 = get_success_data(api_client.stage_firmware_update(
        device["id"], f.create_firmware_update_payload(target_version="3.4.1"), SUPPORT))
    resp = api_client.apply_firmware_update(device["id"], fw2["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_FIRMWARE_NOT_NEWER)


# ===========================================================================
# Corner / state_machines / scene_validate_no_controller_returns_no_controller_in_scene
# ===========================================================================

def test_scene_validate_no_controller_rejected():
    """PRD §3.6: "at least one device in device_ids must be a controller (its
    is_controller true), otherwise ERR_NO_CONTROLLER_IN_SCENE."

    Design: Corner/state_machines/scene_validate_no_controller_returns_no_controller_in_scene
    """
    ctx = setup_provisioning_project(
        region_code="WEST",
        line_items=[dict(sku="C4-SPK", category="AUDIO", qty=1, unit_price_cents=80000)])
    device = fx.register_device(ctx["rack"]["id"], sku="C4-SPK", category="AUDIO", rack_units=1)
    scene = fx.create_scene(ctx["project"]["id"], [device["id"]], name="Audio Only", action_count=1)
    resp = api_client.validate_scene(ctx["project"]["id"], scene["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_NO_CONTROLLER_IN_SCENE)


# ===========================================================================
# Corner / state_machines / scene_deploy_device_not_online_returns_scene_device_not_online
# ===========================================================================

def test_scene_deploy_device_not_online_rejected():
    """PRD §3.6: "Deploying a VALIDATED scene, also a designer action, requires that
    every device in device_ids is currently ONLINE, otherwise
    ERR_SCENE_DEVICE_NOT_ONLINE."

    Design: Corner/state_machines/scene_deploy_device_not_online_returns_scene_device_not_online
    """
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    fx.provision_device(device["id"])  # PROVISIONED, not ONLINE
    scene = fx.setup_validated_scene(ctx["project"]["id"], [device["id"]],
                                     name="Movie", action_count=2)
    resp = api_client.deploy_scene(ctx["project"]["id"], scene["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_SCENE_DEVICE_NOT_ONLINE)


# ===========================================================================
# Corner / state_machines / visit_confirm_understaffed_returns_understaffed_visit
# ===========================================================================

def test_visit_confirm_understaffed_rejected():
    """PRD §3.8: "the visit's assigned_crew_count must be at least its
    crew_size_required, otherwise ERR_UNDERSTAFFED_VISIT".

    Design: Corner/state_machines/visit_confirm_understaffed_returns_understaffed_visit
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN")
    visit = create_visit(project["id"], "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z",
                         visit_kind="INSTALL", crew_size_required=2)
    assign_crew(project["id"], visit["id"], crew["id"], visit["version"])
    resp = api_client.confirm_visit(project["id"], visit["id"], PM)
    validate_error(resp, ApiErrorId.ERR_UNDERSTAFFED_VISIT)


# ===========================================================================
# Corner / state_machines / visit_start_before_window_returns_visit_not_due
# ===========================================================================

def test_visit_start_before_window_rejected():
    """PRD §3.8: "Starting a CONFIRMED visit is a LowVoltageTech action gated on the
    logical clock: it is permitted only when the logical clock is at or after the
    visit's window_start, otherwise ERR_VISIT_NOT_DUE."

    Design: Corner/state_machines/visit_start_before_window_returns_visit_not_due
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN")
    visit = fx.setup_confirmed_visit(project["id"], crew["id"],
                                     "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z",
                                     visit_kind="INSTALL", crew_size_required=1)
    # clock left at the default 2026-01-01T00:00:00Z, before window_start
    resp = api_client.start_visit(project["id"], visit["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_DUE)


# ===========================================================================
# Corner / state_machines / commission_visit_confirm_cert_too_low
# ===========================================================================

def test_commission_visit_confirm_with_apprentice_only_rejected():
    """PRD §3.8: "if the visit_kind is COMMISSION, at least one ACTIVE assignee must
    have a cert_level of JOURNEYMAN or MASTER, otherwise ERR_CERT_TOO_LOW."

    Design: Corner/state_machines/commission_visit_confirm_cert_too_low
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    crew = create_crew_member(region_code="WEST", cert_level="APPRENTICE")
    visit = create_visit(project["id"], "2026-06-02T09:00:00Z", "2026-06-02T12:00:00Z",
                         visit_kind="COMMISSION", crew_size_required=1)
    assign_crew(project["id"], visit["id"], crew["id"], visit["version"])
    resp = api_client.confirm_visit(project["id"], visit["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CERT_TOO_LOW)


# ===========================================================================
# Corner / state_machines / contract_activate_second_returns_already_active
# ===========================================================================

def test_second_contract_activate_rejected_when_one_active():
    """PRD §3.9: "Activating a PENDING contract is a SupportEngineer action
    requiring that the project is COMMISSIONED or ACTIVE, otherwise
    ERR_INVALID_STATE, and that no other contract of the project is already ACTIVE
    or SUSPENDED, otherwise ERR_CONTRACT_ALREADY_ACTIVE."

    The project here is left in DRAFT, so the only way the activate reaches the
    second-contract gate is if the state precondition is satisfied — but the PRD
    says state is checked first. To isolate ERR_CONTRACT_ALREADY_ACTIVE we use a
    project that is COMMISSIONED.

    Design: Corner/state_machines/contract_activate_second_returns_already_active
    """
    ctx = setup_commissioned_project(region_code="WEST")
    project_id = ctx["project"]["id"]
    fx.setup_active_contract(project_id, plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    # second PENDING contract
    create_contract(project_id, plan="PLUS", prepaid_hours=5, hourly_rate_cents=12000)
    resp = api_client.activate_contract(project_id, SUPPORT)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_ALREADY_ACTIVE)


# ===========================================================================
# Corner / validations / project_activate_open_change_orders_returns_open_change_orders
# ===========================================================================

def test_activate_with_open_change_order_rejected():
    """PRD §3.1: "and that open_change_order_count is exactly zero, failing with
    ERR_OPEN_CHANGE_ORDERS otherwise."

    Design: Corner/validations/project_activate_open_change_orders_returns_open_change_orders
    """
    ctx = setup_commissioned_project(region_code="WEST")
    project_id = ctx["project"]["id"]
    fx.setup_active_contract(project_id, plan="BASIC", prepaid_hours=5, hourly_rate_cents=10000)
    get_success_data(api_client.create_change_order(
        project_id, f.create_change_order_payload(description="late add", delta_cents=5000), PM))
    proj = validate_success(api_client.get_project(project_id, PM))
    assert proj["open_change_order_count"] == 1
    resp = api_client.activate_project(project_id, PM)
    validate_error(resp, ApiErrorId.ERR_OPEN_CHANGE_ORDERS)
