"""Special-waste approval branch and the hauler-active guard on manifest submission."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_environmental_officer_headers, make_facility_admin_headers, make_hauler_headers,
    decide_payload,
    setup_special_waste_manifest, setup_posted_ticket,
    create_hauler, create_manifest, submit_manifest, decide_special_waste_approval,
)


def test_special_waste_approve_clears_manifest(api):
    """PRD §3.2: "A `decision` of `APPROVE` advances `PENDING → APPROVED`, records the
    officer's identity in `decided_by`, stores any supplied `decision_note`, and sets the
    parent manifest's `special_waste_cleared` to true — clearing that manifest for
    special-waste posting."

    Design: Difficulty/non_linear_state_machine/special_waste_branch_approve_vs_deny
    """
    ctx = setup_special_waste_manifest(declared_material="ASBESTOS", waste_type="ASBESTOS")
    approved = decide_special_waste_approval(ctx["approval"]["id"], "APPROVE",
                                             decision_note="profile ok")
    assert approved["status"] == "APPROVED"
    manifest = validate_success(
        api.get_manifest(ctx["manifest"]["id"], make_environmental_officer_headers("eo1")))
    assert manifest["special_waste_cleared"] is True


def test_special_waste_deny_leaves_manifest_uncleared(api):
    """PRD §3.2: "A `decision` of `DENY` advances `PENDING → DENIED`, likewise records
    `decided_by` and any `decision_note`, but leaves `special_waste_cleared` false, so a tire
    or asbestos ticket bound to that manifest can never be posted."

    Design: Difficulty/non_linear_state_machine/special_waste_branch_approve_vs_deny
    """
    ctx = setup_special_waste_manifest(declared_material="ASBESTOS", waste_type="ASBESTOS")
    denied = decide_special_waste_approval(ctx["approval"]["id"], "DENY")
    assert denied["status"] == "DENIED"
    manifest = validate_success(
        api.get_manifest(ctx["manifest"]["id"], make_environmental_officer_headers("eo1")))
    assert manifest["special_waste_cleared"] is False


def test_manifest_submit_under_suspended_hauler_rejected(api):
    """PRD §3.2: "Submission is a cross-entity guard: it is permitted only while the backing
    hauler account is `ACTIVE`; a submission attempted while the account is `SUSPENDED` is
    rejected with `ERR_HAULER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_requires_hauler_active
    """
    ctx = setup_posted_ticket(credit_limit=2600, material="CONSTRUCTION_DEBRIS",
                              gross=1.5, tare=1.0)
    hauler = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_facility_admin_headers("adm1")))
    assert hauler["status"] == "SUSPENDED"
    manifest = create_manifest(ctx["hauler"]["id"], declared_material="MSW",
                               declared_weight_tons=4.0)
    resp = submit_manifest(manifest["id"], ctx["hauler"]["id"])
    validate_error(resp, ApiErrorId.ERR_HAULER_SUSPENDED)


def test_manifest_submit_under_active_hauler_succeeds(api):
    """PRD §3.2: "Submission is a cross-entity guard: it is permitted only while the backing
    hauler account is `ACTIVE`; a submission attempted while the account is `SUSPENDED` is
    rejected with `ERR_HAULER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_requires_hauler_active
    """
    hauler = create_hauler(100_000_000)
    manifest = create_manifest(hauler["id"], declared_material="MSW", declared_weight_tons=4.0)
    resp = submit_manifest(manifest["id"], hauler["id"])
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED"


def test_deciding_approved_approval_again_rejected(api):
    """PRD §3.2: "A `decision` of `APPROVE` advances `PENDING → APPROVED`".
    PRD §2.11: "State — the target resource is in a valid state for the requested transition,
    else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/special_waste_decide_twice_terminal_lockdown
    """
    ctx = setup_special_waste_manifest(declared_material="TIRE", waste_type="TIRE",
                                       profile_ref="PRF-9")
    decide_special_waste_approval(ctx["approval"]["id"], "APPROVE")
    resp = api.decide_special_waste_approval(
        ctx["approval"]["id"], decide_payload("DENY"), make_environmental_officer_headers("eo1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
