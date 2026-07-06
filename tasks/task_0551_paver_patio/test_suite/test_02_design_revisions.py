"""Design revision lifecycle: the cyclic revision loop and its invalid-state guards."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

DESIGN = TEST_USERS["design_consultant_headers"]


def test_revision_cycle_increments_revision_round(api):
    """PRD §3.2: "A revision-requested design is revised by the consultant back to `DRAFTING`;
    that `REVISION_REQUESTED → DRAFTING` step increments `revision_round` by one and clears
    `render_url`, re-entering the loop."

    Design: Difficulty/non_linear_state_machine/design_revision_revision_cycle
    """
    ctx = fx.setup_revision_requested_design(api)
    data = validate_success(api.revise_design(ctx["revision_id"], DESIGN))
    assert data["revision_round"] == 2, f"expected revision_round 2, got {data['revision_round']}"


def test_revise_returns_revision_to_drafting(api):
    """PRD §3.2: "A revision-requested design is revised by the consultant back to `DRAFTING`;
    that `REVISION_REQUESTED → DRAFTING` step increments `revision_round` by one and clears
    `render_url`, re-entering the loop."

    Design: Difficulty/non_linear_state_machine/design_revision_revision_cycle
    """
    ctx = fx.setup_revision_requested_design(api)
    data = validate_success(api.revise_design(ctx["revision_id"], DESIGN))
    assert data["status"] == "DRAFTING", f"expected DRAFTING, got {data['status']}"


def test_approve_design_from_drafting_invalid_state(api):
    """PRD §3.2: "From `IN_REVIEW`, the homeowner — who must own the project — either approves it,
    advancing `IN_REVIEW` to `APPROVED`, or asks for changes, advancing `IN_REVIEW` to
    `REVISION_REQUESTED`."
    PRD §2.5: "The target resource must sit in a state from which the transition is legal. A
    generic violation is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/approve_design_from_drafting_returns_invalid_state
    """
    from test_helpers import make_client_headers
    customer = fx.make_customer(api, email="ov@example.com")
    project = fx.make_project(api, customer["id"], site_address="27 Yard Ln")
    dr = fx.get_success_data(api.create_design_revision({"project_id": project["id"]}, DESIGN))
    resp = api.approve_design(dr["id"], make_client_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_render_already_rendered_invalid_state(api):
    """PRD §3.2: "The consultant produces a 3D rendering, which advances the revision from
    `DRAFTING` to `RENDERED` and populates `render_url` with the generated artifact URL, then
    submits it for review, moving `RENDERED` to `IN_REVIEW`."
    PRD §2.5: "The target resource must sit in a state from which the transition is legal. A
    generic violation is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/render_twice_returns_invalid_state
    """
    customer = fx.make_customer(api, email="oid@example.com")
    project = fx.make_project(api, customer["id"], site_address="28 Yard Ln")
    dr = fx.get_success_data(api.create_design_revision({"project_id": project["id"]}, DESIGN))
    validate_success(api.render_design(dr["id"], DESIGN))
    resp = api.render_design(dr["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
