"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty DB before each
test). Helpers use get_success_data() so setup failures surface clearly.

Identity threading: after creating a Client, ownership-gated calls (proposal
accept/reject, change-order approve/reject) use make_client_headers(client_id),
never the shared TEST_USERS["client_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
DESIGNER = TEST_USERS["systems_designer_headers"]
PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["low_voltage_tech_headers"]
SUPPORT = TEST_USERS["support_engineer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def create_client(billing_tier=None, **overrides):
    """Register a client. Returns the Client dict (carries id)."""
    payload = f.create_client_payload(**overrides)
    if billing_tier is not None:
        payload["billing_tier"] = billing_tier
    return get_success_data(api_client.create_client(payload, ADMIN))


def create_project(client_id, region_code="WEST", **overrides):
    """Create a DRAFT project. Returns the Project dict."""
    payload = f.create_project_payload(client_id, region_code=region_code, **overrides)
    return get_success_data(api_client.create_project(payload, PM))


def create_rack(project_id, **overrides):
    """Create the project's rack. Returns the Rack dict."""
    payload = f.create_rack_payload(**overrides)
    return get_success_data(api_client.create_rack(project_id, payload, PM))


def create_crew_member(region_code="WEST", cert_level="JOURNEYMAN",
                       daily_visit_cap=2, active=True, **overrides):
    """Register a crew member. Returns the CrewMember dict."""
    payload = f.create_crew_member_payload(
        region_code=region_code, cert_level=cert_level,
        daily_visit_cap=daily_visit_cap, active=active, **overrides)
    return get_success_data(api_client.create_crew_member(payload, ADMIN))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, PM))


def project_version(project_id):
    return get_project(project_id)["version"]


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: proposal lifecycle
# ---------------------------------------------------------------------------

def create_proposal(project_id, labor_hours_estimate=2.0, expected_version=None):
    """Create a DRAFT proposal on a project. Returns the Proposal dict."""
    if expected_version is None:
        expected_version = project_version(project_id)
    payload = f.create_proposal_payload(expected_version,
                                        labor_hours_estimate=labor_hours_estimate)
    return get_success_data(api_client.create_proposal(project_id, payload, DESIGNER))


def add_line_item(project_id, proposal_id, **item):
    payload = f.create_line_item_payload(**item)
    return get_success_data(
        api_client.add_line_item(project_id, proposal_id, payload, DESIGNER))


def setup_draft_proposal_with_items(project_id, line_items=None,
                                    labor_hours_estimate=2.0, expected_version=None):
    """Create a DRAFT proposal with the given line items (defaults to one
    CONTROLLER 1x250000). Returns (proposal, [line_item, ...])."""
    if line_items is None:
        line_items = [dict(sku="C4-CTRL", category="CONTROLLER", qty=1,
                           unit_price_cents=250000)]
    proposal = create_proposal(project_id, labor_hours_estimate, expected_version)
    items = [add_line_item(project_id, proposal["id"], **li) for li in line_items]
    return proposal, items


def setup_sent_proposal(project_id, line_items=None, labor_hours_estimate=2.0):
    """Create a DRAFT proposal, add line items, send it. Returns the sent Proposal."""
    proposal, _ = setup_draft_proposal_with_items(
        project_id, line_items, labor_hours_estimate)
    return get_success_data(api_client.send_proposal(project_id, proposal["id"], DESIGNER))


def accept_proposal(project_id, proposal_id, client_id):
    """Owning client accepts a SENT proposal. Returns the accepted Proposal."""
    return get_success_data(
        api_client.accept_proposal(project_id, proposal_id, make_client_headers(client_id)))


# ---------------------------------------------------------------------------
# Tier 2: project state progression
# ---------------------------------------------------------------------------

def setup_accepted_project(region_code="WEST", billing_tier="RESIDENTIAL",
                           line_items=None, labor_hours_estimate=2.0, with_rack=False):
    """Client + DRAFT project + sent+accepted proposal -> project ACCEPTED.
    Returns dict(client, project, proposal). project reflects ACCEPTED state.
    If with_rack, also creates a rack (returns rack too)."""
    client = create_client(billing_tier=billing_tier)
    project = create_project(client["id"], region_code=region_code)
    rack = None
    if with_rack:
        rack = create_rack(project["id"])
    proposal = setup_sent_proposal(project["id"], line_items, labor_hours_estimate)
    accept_proposal(project["id"], proposal["id"], client["id"])
    result = {"client": client, "project": get_project(project["id"]),
              "proposal": proposal}
    if rack is not None:
        result["rack"] = rack
    return result


def setup_provisioning_project(region_code="WEST", billing_tier="RESIDENTIAL",
                               rack_overrides=None, line_items=None,
                               labor_hours_estimate=2.0):
    """Accepted project with a rack -> start-provisioning (project PROVISIONING).
    Returns dict(client, project, proposal, rack)."""
    client = create_client(billing_tier=billing_tier)
    project = create_project(client["id"], region_code=region_code)
    rack = create_rack(project["id"], **(rack_overrides or {}))
    proposal = setup_sent_proposal(project["id"], line_items, labor_hours_estimate)
    accept_proposal(project["id"], proposal["id"], client["id"])
    get_success_data(api_client.start_provisioning(project["id"], PM))
    return {"client": client, "project": get_project(project["id"]),
            "proposal": proposal, "rack": rack}


# ---------------------------------------------------------------------------
# Tier 3: device lifecycle shortcuts
# ---------------------------------------------------------------------------

def register_device(rack_id, sku="C4-CTRL", category="CONTROLLER", rack_units=2):
    payload = f.create_device_payload(rack_id, sku=sku, category=category,
                                      rack_units=rack_units)
    return get_success_data(api_client.create_device(payload, TECH))


def provision_device(device_id):
    return get_success_data(api_client.provision_device(device_id, TECH))


def apply_firmware(device_id, target_version="3.4.1"):
    """Stage + apply a firmware update on a device. Returns (fw_update, device).

    The apply endpoint transitions and returns the firmware-update resource; the
    device's firmware_version is read back with a fresh GET on the device.
    """
    fw = get_success_data(api_client.stage_firmware_update(
        device_id, f.create_firmware_update_payload(target_version=target_version), SUPPORT))
    applied_fw = get_success_data(api_client.apply_firmware_update(device_id, fw["id"], SUPPORT))
    device = get_success_data(api_client.get_device(device_id, TECH))
    return applied_fw, device


def bring_online(device_id):
    return get_success_data(api_client.bring_online(device_id, TECH))


def setup_online_device(rack_id, sku="C4-CTRL", category="CONTROLLER",
                        rack_units=2, target_version="3.4.1"):
    """Register -> provision -> apply firmware -> bring online. Returns the ONLINE Device."""
    device = register_device(rack_id, sku=sku, category=category, rack_units=rack_units)
    provision_device(device["id"])
    apply_firmware(device["id"], target_version)
    return bring_online(device["id"])


def setup_provisioning_with_online_device(region_code="WEST", **kwargs):
    """PROVISIONING project + rack + one ONLINE CONTROLLER device.
    Returns dict(client, project, proposal, rack, device)."""
    ctx = setup_provisioning_project(region_code=region_code, **kwargs)
    device = setup_online_device(ctx["rack"]["id"])
    ctx["device"] = device
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: scene lifecycle
# ---------------------------------------------------------------------------

def create_scene(project_id, device_ids, name="Movie Night", action_count=1):
    payload = f.create_scene_payload(device_ids, name=name, action_count=action_count)
    return get_success_data(api_client.create_scene(project_id, payload, DESIGNER))


def setup_validated_scene(project_id, device_ids, name="Movie Night", action_count=2):
    """Create + validate a scene. Returns the VALIDATED SceneProgram."""
    scene = create_scene(project_id, device_ids, name=name, action_count=action_count)
    return get_success_data(api_client.validate_scene(project_id, scene["id"], DESIGNER))


def setup_deployed_scene(project_id, device_ids, name="Movie Night", action_count=2):
    """Create + validate + deploy a scene (devices must already be ONLINE).
    Returns the DEPLOYED SceneProgram."""
    scene = setup_validated_scene(project_id, device_ids, name=name, action_count=action_count)
    return get_success_data(api_client.deploy_scene(project_id, scene["id"], DESIGNER))


# ---------------------------------------------------------------------------
# Tier 5: visits & crew assignment
# ---------------------------------------------------------------------------

def create_visit(project_id, window_start, window_end, visit_kind="INSTALL",
                 crew_size_required=1):
    payload = f.create_visit_payload(
        window_start=window_start, window_end=window_end,
        visit_kind=visit_kind, crew_size_required=crew_size_required)
    return get_success_data(api_client.create_visit(project_id, payload, PM))


def assign_crew(project_id, visit_id, crew_member_id, expected_visit_version):
    payload = f.create_assignment_payload(crew_member_id, expected_visit_version)
    return get_success_data(
        api_client.create_assignment(project_id, visit_id, payload, PM))


def setup_confirmed_visit(project_id, crew_member_id, window_start, window_end,
                          visit_kind="INSTALL", crew_size_required=1):
    """Create a visit, assign one crew member, confirm it. Returns the CONFIRMED Visit."""
    visit = create_visit(project_id, window_start, window_end,
                         visit_kind=visit_kind, crew_size_required=crew_size_required)
    assign_crew(project_id, visit["id"], crew_member_id, visit["version"])
    return get_success_data(api_client.confirm_visit(project_id, visit["id"], PM))


def run_visit_to_completed(project_id, crew_member_id, window_start, window_end,
                           visit_kind="INSTALL"):
    """Full visit run: create -> assign -> confirm -> (clock) start -> complete.
    Returns the COMPLETED Visit. Advances the logical clock to window_start."""
    visit = setup_confirmed_visit(project_id, crew_member_id, window_start, window_end,
                                  visit_kind=visit_kind, crew_size_required=1)
    set_clock(window_start)
    get_success_data(api_client.start_visit(project_id, visit["id"], TECH))
    return get_success_data(api_client.complete_visit(project_id, visit["id"], TECH))


# ---------------------------------------------------------------------------
# Tier 6: contracts
# ---------------------------------------------------------------------------

def create_contract(project_id, plan="PLUS", prepaid_hours=10, hourly_rate_cents=12000):
    payload = f.create_contract_payload(plan=plan, prepaid_hours=prepaid_hours,
                                        hourly_rate_cents=hourly_rate_cents)
    return get_success_data(api_client.create_contract(project_id, payload, SUPPORT))


def setup_active_contract(project_id, plan="PLUS", prepaid_hours=10, hourly_rate_cents=12000):
    """Create + activate a contract (project must be COMMISSIONED or ACTIVE).
    Returns the ACTIVE Contract."""
    create_contract(project_id, plan, prepaid_hours, hourly_rate_cents)
    return get_success_data(api_client.activate_contract(project_id, SUPPORT))


# ---------------------------------------------------------------------------
# Tier 7: full lifecycle to COMMISSIONED
# ---------------------------------------------------------------------------

def setup_commissioned_project(region_code="WEST", billing_tier="RESIDENTIAL"):
    """Full lifecycle to COMMISSIONED: accepted -> provisioning -> one ONLINE
    device -> deployed scene -> INSTALL visit (confirm bubbles to SCHEDULED,
    start bubbles to INSTALLING) -> COMMISSION visit completes (commission gate).
    Project ends COMMISSIONED with no contract and zero open change orders.
    Returns dict(client, project, proposal, rack, device, scene, crew)."""
    ctx = setup_provisioning_with_online_device(region_code=region_code,
                                                billing_tier=billing_tier)
    project_id = ctx["project"]["id"]
    scene = setup_deployed_scene(project_id, [ctx["device"]["id"]],
                                 name="All On", action_count=1)
    crew = create_crew_member(region_code=region_code, cert_level="MASTER")
    # INSTALL visit: confirm bubbles PROVISIONING->SCHEDULED, start bubbles
    # SCHEDULED->INSTALLING.
    run_visit_to_completed(project_id, crew["id"],
                           "2026-03-01T09:00:00Z", "2026-03-01T12:00:00Z",
                           visit_kind="INSTALL")
    # COMMISSION visit: completing it attempts the guarded INSTALLING->COMMISSIONED.
    run_visit_to_completed(project_id, crew["id"],
                           "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z",
                           visit_kind="COMMISSION")
    ctx["scene"] = scene
    ctx["crew"] = crew
    ctx["project"] = get_project(project_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 8: faulted device + RMA
# ---------------------------------------------------------------------------

def fault_device(device_id):
    return get_success_data(api_client.mark_faulted(device_id, SUPPORT))


def setup_active_contract_with_online_device(region_code="WEST"):
    """A project advanced to COMMISSIONED with an ACTIVE contract and a still-ONLINE
    device. Returns dict(client, project, rack, device, contract, crew, ...)."""
    ctx = setup_commissioned_project(region_code=region_code)
    contract = setup_active_contract(ctx["project"]["id"])
    ctx["contract"] = contract
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def open_rma(device_id, contract_id, fault_code="HARDWARE", resolution="RETURN_REPAIR"):
    payload = f.create_rma_payload(device_id, contract_id,
                                   fault_code=fault_code, resolution=resolution)
    return get_success_data(api_client.create_rma_ticket(payload, SUPPORT))
