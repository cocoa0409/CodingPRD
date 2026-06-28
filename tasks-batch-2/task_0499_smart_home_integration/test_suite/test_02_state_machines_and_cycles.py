"""State-machine cycles and transition facts.

Covers the non-linear state-machine rule (scene revise loop, contract
suspend/resume loop) and corner state-machine claims: proposal initial state,
send/accept/reject bubbles, superseding proposals, terminal lockdowns.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    DESIGNER, PM, SUPPORT,
    create_client, create_project, create_rack, create_proposal,
    setup_draft_proposal_with_items, setup_sent_proposal, accept_proposal,
    setup_provisioning_with_online_device, setup_provisioning_project,
    project_version,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / non_linear_state_machine / scene_program_revision_cycle_validated_back_to_draft
# ===========================================================================

def _provisioning_with_registered_controller():
    """PROVISIONING project + rack + one REGISTERED CONTROLLER device.
    Returns (project_id, device_id)."""
    ctx = setup_provisioning_project(region_code="WEST")
    device = fx.register_device(ctx["rack"]["id"], sku="C4-CTRL",
                                category="CONTROLLER", rack_units=2)
    return ctx["project"]["id"], device["id"]


def test_scene_revise_returns_validated_scene_to_draft():
    """PRD §3.6: "A designer may revise a VALIDATED scene back to DRAFT to re-open
    it for editing".

    Design: Difficulty/non_linear_state_machine/scene_program_revision_cycle_validated_back_to_draft
    """
    project_id, device_id = _provisioning_with_registered_controller()
    scene = fx.setup_validated_scene(project_id, [device_id], name="Movie Night", action_count=2)
    data = validate_success(api_client.revise_scene(project_id, scene["id"], DESIGNER))
    assert data["status"] == "DRAFT"


def test_scene_can_be_revalidated_after_revise_completing_cycle():
    """PRD §3.6: "A scene runs DRAFT to VALIDATED to DEPLOYED, with ARCHIVED as the
    terminal state and a revise path back to DRAFT."

    Design: Difficulty/non_linear_state_machine/scene_program_revision_cycle_validated_back_to_draft
    """
    project_id, device_id = _provisioning_with_registered_controller()
    scene = fx.setup_validated_scene(project_id, [device_id], name="Movie Night", action_count=2)
    get_success_data(api_client.revise_scene(project_id, scene["id"], DESIGNER))
    data = validate_success(api_client.validate_scene(project_id, scene["id"], DESIGNER))
    assert data["status"] == "VALIDATED", "scene re-validated after revise (cycle completed)"


# ===========================================================================
# Difficulty / non_linear_state_machine / contract_active_suspended_resume_cycle
# ===========================================================================

def _project_with_active_contract(prepaid_hours=5, hourly_rate_cents=10000, plan="BASIC"):
    # PRD §3.9: activating a PENDING contract requires the project to be
    # COMMISSIONED or ACTIVE, so drive the project to COMMISSIONED first.
    ctx = fx.setup_commissioned_project(region_code="WEST")
    project_id = ctx["project"]["id"]
    fx.create_contract(project_id, plan=plan, prepaid_hours=prepaid_hours,
                       hourly_rate_cents=hourly_rate_cents)
    get_success_data(api_client.activate_contract(project_id, SUPPORT))
    return project_id


def test_contract_suspend_moves_active_to_suspended():
    """PRD §3.9: "A support engineer may suspend an ACTIVE contract — which blocks
    remote-support sessions and new RMA authorizations while suspended — and resume
    a SUSPENDED contract back to ACTIVE."

    Design: Difficulty/non_linear_state_machine/contract_active_suspended_resume_cycle
    """
    project_id = _project_with_active_contract()
    data = validate_success(api_client.suspend_contract(project_id, SUPPORT))
    assert data["status"] == "SUSPENDED"


def test_contract_resume_moves_suspended_back_to_active():
    """PRD §3.9: "A support engineer may suspend an ACTIVE contract ... and resume
    a SUSPENDED contract back to ACTIVE."

    Design: Difficulty/non_linear_state_machine/contract_active_suspended_resume_cycle
    """
    project_id = _project_with_active_contract()
    get_success_data(api_client.suspend_contract(project_id, SUPPORT))
    data = validate_success(api_client.resume_contract(project_id, SUPPORT))
    assert data["status"] == "ACTIVE", "contract resumed to ACTIVE (cycle completed)"


# ===========================================================================
# Corner / state_machines / proposal_initial_state_is_draft
# ===========================================================================

def test_new_proposal_is_draft_revision_one():
    """PRD §3.2: "upon creation the new proposal takes revision equal to one more
    than the highest existing revision on the project, starts in DRAFT".

    Design: Corner/state_machines/proposal_initial_state_is_draft
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    data = validate_success(api_client.create_proposal(
        project["id"], f.create_proposal_payload(project["version"], labor_hours_estimate=3.0),
        DESIGNER), expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["revision"] == 1


# ===========================================================================
# Corner / state_machines / accept_already_accepted_proposal_returns_invalid_state
# ===========================================================================

def test_accept_already_accepted_proposal_rejected():
    """PRD §3.3: "acting on a project not in PROPOSED is ERR_INVALID_STATE."

    Design: Corner/state_machines/accept_already_accepted_proposal_returns_invalid_state
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    resp = api_client.accept_proposal(
        project["id"], proposal["id"], fx.make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Corner / state_machines / start_provisioning_without_rack_returns_rack_required
# ===========================================================================

def test_start_provisioning_without_rack_rejected():
    """PRD §3.1: "this start-of-provisioning transition requires that
    accepted_proposal_id has been set and that a rack already exists for the
    project, failing otherwise with ERR_INVALID_STATE when no proposal is pinned
    and with ERR_RACK_REQUIRED when no rack has been created."

    Design: Corner/state_machines/start_provisioning_without_rack_returns_rack_required
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])  # no rack created
    accept_proposal(project["id"], proposal["id"], client["id"])
    resp = api_client.start_provisioning(project["id"], PM)
    validate_error(resp, ApiErrorId.ERR_RACK_REQUIRED)


# ===========================================================================
# Corner / state_machines / proposal_send_bubbles_project_to_proposed
# ===========================================================================

def test_send_proposal_bubbles_project_to_proposed():
    """PRD §3.2: "Sending freezes the line items against further edits, recomputes
    the full pricing, and moves the project from DRAFT to PROPOSED."

    Design: Corner/state_machines/proposal_send_bubbles_project_to_proposed
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal, _ = setup_draft_proposal_with_items(project["id"])
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["status"] == "SENT"
    proj = validate_success(api_client.get_project(project["id"], PM))
    assert proj["status"] == "PROPOSED"


# ===========================================================================
# Corner / state_machines / proposal_reject_returns_project_to_draft_revision_loop
# ===========================================================================

def test_reject_proposal_returns_project_to_draft():
    """PRD §3.3: "Rejecting a SENT proposal returns the project from PROPOSED to
    DRAFT so that the designer may issue a superseding revision."

    Design: Corner/state_machines/proposal_reject_returns_project_to_draft_revision_loop
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    data = validate_success(api_client.reject_proposal(
        project["id"], proposal["id"], fx.make_client_headers(client["id"])))
    assert data["status"] == "REJECTED"
    proj = validate_success(api_client.get_project(project["id"], PM))
    assert proj["status"] == "DRAFT"


# ===========================================================================
# Corner / state_machines / superseding_proposal_closes_prior_draft
# ===========================================================================

def test_superseding_proposal_closes_prior_draft_and_increments_revision():
    """PRD §3.2: "supersedes any currently open DRAFT or SENT proposal (moving each
    to SUPERSEDED), and increments the project's version by one."
    PRD §3.2: "the new proposal takes revision equal to one more than the highest
    existing revision on the project".

    Design: Corner/state_machines/superseding_proposal_closes_prior_draft
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    prop1 = create_proposal(project["id"], labor_hours_estimate=3.0)
    v1 = project_version(project["id"])
    prop2 = validate_success(api_client.create_proposal(
        project["id"], f.create_proposal_payload(v1, labor_hours_estimate=4.0),
        DESIGNER), expected_status=201)
    prop1_now = validate_success(api_client.get_proposal(prop1["id"], DESIGNER))
    assert prop1_now["status"] == "SUPERSEDED"
    assert prop2["revision"] == 2
    assert prop2["status"] == "DRAFT"


# ===========================================================================
# Corner / state_machines / terminal_change_order_applied_cannot_reapply
# ===========================================================================

def test_reapply_applied_change_order_rejected():
    """PRD §3.3: "Application sets applied_at to the current logical clock instant,
    moves the change order to APPLIED, recomputes open_change_order_count, and
    increments the project's version by one."
    PRD §2.9: "The state precondition for a transition is checked seventh, yielding
    ERR_INVALID_STATE when the target is not in a state from which the requested
    transition is defined."

    Design: Corner/state_machines/terminal_change_order_applied_cannot_reapply
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    co = get_success_data(api_client.create_change_order(
        project["id"], f.create_change_order_payload(description="Add", delta_cents=10000), PM))
    get_success_data(api_client.approve_change_order(
        project["id"], co["id"], fx.make_client_headers(client["id"])))
    pre = project_version(project["id"])
    get_success_data(api_client.apply_change_order(
        project["id"], co["id"], f.apply_change_order_payload(pre), PM))
    post = project_version(project["id"])
    resp = api_client.apply_change_order(
        project["id"], co["id"], f.apply_change_order_payload(post), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
