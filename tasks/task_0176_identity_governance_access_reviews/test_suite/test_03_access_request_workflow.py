"""Access-request workflow: the RETURNED revision loop, the approval cascade and
its high-risk auto-flag, validation precedence at approval, and cross-entity
state gates.

Derived from PRD §3.3 (Raising and Submitting), §3.4 (Deciding: Separation of
Duties, Dual Approval, and SoD Conflicts), §2.6 (Validation Order and
Precedence), and the state machine in §3.5.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_sod_policy_payload, create_grant_payload, create_access_request_payload,
    ApiErrorId,
    TEST_USERS, build_user_headers,
    fixtures,
)

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]
APPROVER = TEST_USERS["access_approver_headers"]


def test_returned_request_can_be_resubmitted(api):
    """PRD §3.3: "Submission is allowed from DRAFT and again from RETURNED — the
    latter is a deliberate revision loop, so a returned request can be resubmitted
    any number of times."
    PRD §3.3: "Returning a submitted request is an approver's action: it moves the
    request from SUBMITTED back to RETURNED."

    A request goes SUBMITTED -> RETURNED -> SUBMITTED: the same request reaches
    SUBMITTED twice without creating a new resource.

    Design: Difficulty/non_linear_state_machine/access_request_returned_resubmit_cycle
    """
    ent = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntLoop", system_code="EL", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ent["id"]], name="RoleLoop"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Loopy", email="loop@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-9", "AccessManager")
    apr = build_user_headers("apr-9", "AccessApprover")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    validate_success(api.return_access_request(req["id"], apr), 200)

    resubmitted = validate_success(api.submit_access_request(req["id"], mgr), 200)
    assert resubmitted["status"] == "SUBMITTED", resubmitted["status"]


def test_returned_request_can_cycle_multiple_times(api):
    """PRD §3.3: "the latter is a deliberate revision loop, so a returned request
    can be resubmitted any number of times."
    PRD §3.3: "Returning a submitted request is an approver's action: it moves the
    request from SUBMITTED back to RETURNED."

    The cycle is traversable more than once: SUBMITTED -> RETURNED -> SUBMITTED ->
    RETURNED -> SUBMITTED, ending in SUBMITTED after the second full loop, on the
    same request resource.

    Design: Difficulty/non_linear_state_machine/access_request_returned_resubmit_cycle
    """
    ent = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntLoop2", system_code="EL2", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ent["id"]], name="RoleLoop2"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Loopy2", email="loop2@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-9b", "AccessManager")
    apr = build_user_headers("apr-9b", "AccessApprover")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    for _ in range(2):
        validate_success(api.submit_access_request(req["id"], mgr), 200)
        validate_success(api.return_access_request(req["id"], apr), 200)
    final = validate_success(api.submit_access_request(req["id"], mgr), 200)
    assert final["status"] == "SUBMITTED", final["status"]


def test_approval_cascade_creates_active_grant_and_flags_high_risk(api):
    """PRD §3.4: "For each entitlement bundled by the role, the system creates one
    grant in the provisioning stage and then auto-advances each new grant to
    active"
    PRD §3.4: "If, as a result of these activations, the identity's
    effective_risk_score crosses the high-risk threshold of 100 points, the newest
    privileged grant has its review dimension set to FLAGGED."

    Approving a request for a single privileged entitlement of risk 75 lands
    effective risk at 100 (75 base + 25 surcharge); the new grant is ACTIVE and
    FLAGGED.

    Design: Difficulty/transitive_cascade/approval_to_grant_to_activation_to_riskflag
    """
    bp = validate_success(api.create_entitlement(
        create_entitlement_payload(name="BigPriv", system_code="BP",
                                   is_privileged=True, risk_weight=75), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([bp["id"]], name="RoleBig"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Risky", email="risky@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-7", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    apr = build_user_headers("apr-7", "AccessApprover")
    validate_success(api.approve_access_request(req["id"],
        {"second_approver_confirmed": True}, apr), 200)

    grants, _meta = validate_paginated(
        api.list_grants(APPROVER, params={"identity_id": identity["id"]}))
    assert len(grants) == 1, grants
    g = grants[0]
    assert g["lifecycle_status"] == "ACTIVE", g["lifecycle_status"]
    assert g["review_status"] == "FLAGGED", g["review_status"]
    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["effective_risk_score"] == 100, got["effective_risk_score"]


def test_approval_cascade_appends_request_approved_and_grant_activated_audits(api):
    """PRD §3.4: "each activation recomputes the identity's active_grant_count,
    privileged_entitlement_count, and effective_risk_score ... An audit event of
    type REQUEST_APPROVED is appended."
    PRD §3.5: "it appends an audit event of type GRANT_ACTIVATED."

    The same single-approve cascade, asserted on its audit-evidence hop: the
    depth-three chain leaves both a REQUEST_APPROVED event (the approval) and a
    GRANT_ACTIVATED event (the downstream activation) on the subject identity.

    Design: Difficulty/transitive_cascade/approval_to_grant_to_activation_to_riskflag
    """
    bp = validate_success(api.create_entitlement(
        create_entitlement_payload(name="BigPriv2", system_code="BP2",
                                   is_privileged=True, risk_weight=75), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([bp["id"]], name="RoleBig2"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Risky2", email="risky2@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-7b", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    apr = build_user_headers("apr-7b", "AccessApprover")
    validate_success(api.approve_access_request(req["id"],
        {"second_approver_confirmed": True}, apr), 200)

    approved = fixtures.list_identity_audit_events(identity["id"], event_type="REQUEST_APPROVED")
    activated = fixtures.list_identity_audit_events(identity["id"], event_type="GRANT_ACTIVATED")
    assert len(approved) >= 1, "expected a REQUEST_APPROVED audit event"
    assert len(activated) >= 1, "expected a GRANT_ACTIVATED audit event"


def test_dual_approval_required_beats_soft_sod_override(api):
    """PRD §3.4: "Next, dual approval is enforced: if the requested role's
    requires_dual_approval is true, the approval request body must carry
    second_approver_confirmed equal to true, or the request is rejected with
    ERR_DUAL_APPROVAL_REQUIRED. Finally the segregation-of-duties conflict gate
    applies".

    A privileged role with a SOFT SoD conflict approved WITHOUT
    second_approver_confirmed is rejected with ERR_DUAL_APPROVAL_REQUIRED (the
    dual-approval gate runs before the SoD override gate).

    Design: Difficulty/priority_pair_validation_conflict/dual_approval_beats_sod_override
    """
    ea2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntA2", system_code="EA2", risk_weight=10), CATALOG), 201)
    pp2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="PrivP", system_code="PP",
                                   is_privileged=True, risk_weight=30), CATALOG), 201)
    validate_success(api.create_sod_policy(
        create_sod_policy_payload(ea2["id"], pp2["id"], name="A2P", severity="SOFT"), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([pp2["id"]], name="RolePriv"), CATALOG), 201)
    assert role["requires_dual_approval"] is True
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Da", email="da@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(ea2["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-6", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"],
                                      sod_override_justification="ok"), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    apr = build_user_headers("apr-6", "AccessApprover")
    resp = api.approve_access_request(req["id"], {"sod_override_justification": "ok"}, apr)
    validate_error(resp, ApiErrorId.ERR_DUAL_APPROVAL_REQUIRED.value)


def test_dual_approval_gate_clears_then_soft_sod_gate_passes(api):
    """PRD §3.4: "Next, dual approval is enforced: if the requested role's
    requires_dual_approval is true, the approval request body must carry
    second_approver_confirmed equal to true ... Finally the segregation-of-duties
    conflict gate applies ... if the only conflicts present are SOFT, approval may
    proceed but only when a non-empty sod_override_justification accompanies it".

    Complement to the priority test: once second_approver_confirmed clears the
    dual-approval gate (priority 6), the later SOFT-SoD gate (priority 8) is reached
    and, with a non-empty override justification, approval succeeds (status
    APPROVED). This proves the two gates are ordered, not fused.

    Design: Difficulty/priority_pair_validation_conflict/dual_approval_beats_sod_override
    """
    ea2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntA2b", system_code="EA2B", risk_weight=10), CATALOG), 201)
    pp2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="PrivPb", system_code="PPB",
                                   is_privileged=True, risk_weight=30), CATALOG), 201)
    validate_success(api.create_sod_policy(
        create_sod_policy_payload(ea2["id"], pp2["id"], name="A2Pb", severity="SOFT"), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([pp2["id"]], name="RolePrivB"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Db", email="db@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(ea2["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-6b", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"],
                                      sod_override_justification="ok"), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    apr = build_user_headers("apr-6b", "AccessApprover")
    approved = validate_success(api.approve_access_request(req["id"],
        {"second_approver_confirmed": True, "sod_override_justification": "ok"}, apr), 200)
    assert approved["status"] == "APPROVED", approved["status"]


def test_state_check_beats_sod_on_reapprove(api):
    """PRD §2.6: "State validity is checked fourth: if the target resource is not
    in a state from which the requested transition is defined, the request is
    rejected with ERR_INVALID_STATE. Only after these structural gates pass does
    the system evaluate the business-safety, referential, constraint, and temporal
    rules".

    A request with a SOFT SoD conflict is already APPROVED; a second approve hits
    the state gate (request no longer SUBMITTED) -> ERR_INVALID_STATE, not the SoD
    business rule.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_approve
    """
    ea = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntA", system_code="EA", risk_weight=10), CATALOG), 201)
    eb = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntB", system_code="EB", risk_weight=10), CATALOG), 201)
    validate_success(api.create_sod_policy(
        create_sod_policy_payload(ea["id"], eb["id"], name="AB", severity="SOFT"), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([eb["id"]], name="RoleB"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Sd", email="sd@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(ea["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-5", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"],
                                      sod_override_justification="approved exception"), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    apr = build_user_headers("apr-5", "AccessApprover")
    validate_success(api.approve_access_request(req["id"],
        {"sod_override_justification": "approved exception"}, apr), 200)

    resp = api.approve_access_request(req["id"],
        {"sod_override_justification": "approved exception"}, apr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_sod_self_action_on_reapprove(api):
    """PRD §2.6: "State validity is checked fourth: if the target resource is not
    in a state from which the requested transition is defined, the request is
    rejected with ERR_INVALID_STATE. Only after these structural gates pass does
    the system evaluate the business-safety, referential, constraint, and temporal
    rules".

    Same precedence rule, a different business gate: a request already APPROVED is
    re-approved by the original requester (who would trip ERR_SOD_SELF_ACTION). The
    structural state gate fires first, so the result is ERR_INVALID_STATE, not the
    SoD self-action error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_approve
    """
    ent = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntSt", system_code="EST", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ent["id"]], name="RoleSt"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Sd2", email="sd2@x.com"), MANAGER), 201)
    requester = build_user_headers("shared-op-1", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), requester), 201)
    validate_success(api.submit_access_request(req["id"], requester), 200)
    approver = build_user_headers("apr-st", "AccessApprover")
    validate_success(api.approve_access_request(req["id"], {}, approver), 200)

    # Re-approve as the original requester — would be ERR_SOD_SELF_ACTION if the
    # state gate did not pre-empt it; the request is no longer SUBMITTED.
    self_approver = build_user_headers("shared-op-1", "AccessApprover")
    resp = api.approve_access_request(req["id"], {}, self_approver)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_blocked_when_target_identity_not_active(api):
    """PRD §3.4: "Next the target identity's status must be ACTIVE, or approval
    fails with ERR_IDENTITY_NOT_ACTIVE."

    A SUBMITTED request whose target identity is disabled before approval is
    rejected with ERR_IDENTITY_NOT_ACTIVE — the block comes from the linked
    Identity's state, not the request's own state.

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_when_identity_not_active
    """
    ex = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntX", system_code="EX", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ex["id"]], name="RoleX"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Xi", email="xi@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-3", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": fresh["version"]}, MANAGER), 200)

    apr = build_user_headers("apr-3", "AccessApprover")
    resp = api.approve_access_request(req["id"], {"second_approver_confirmed": True}, apr)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_ACTIVE.value)


def test_approve_blocked_when_target_identity_deprovisioned(api):
    """PRD §3.4: "Next the target identity's status must be ACTIVE, or approval
    fails with ERR_IDENTITY_NOT_ACTIVE."

    Same cross-entity dependency reached through a different terminal Identity
    state: the target identity is disabled then deprovisioned (status
    DEPROVISIONED, not ACTIVE) after the request was submitted. Approval still fails
    with ERR_IDENTITY_NOT_ACTIVE — the gate keys off the linked Identity.status.

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_when_identity_not_active
    """
    ent = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntXd", system_code="EXD", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ent["id"]], name="RoleXd"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Xid", email="xid@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-3b", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    disabled = validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": fresh["version"]}, MANAGER), 200)
    validate_success(api.deprovision_identity(identity["id"], MANAGER), 200)

    apr = build_user_headers("apr-3b", "AccessApprover")
    resp = api.approve_access_request(req["id"], {"second_approver_confirmed": True}, apr)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_ACTIVE.value)


def test_submit_with_archived_entitlement_rejected(api):
    """PRD §3.3: "and on the first submission out of DRAFT, every entitlement
    bundled by the role must have status equal to ACTIVE, or the request is
    rejected with ERR_ENTITLEMENT_ARCHIVED".

    Submitting a request whose role bundles an entitlement that was archived after
    role creation is rejected with ERR_ENTITLEMENT_ARCHIVED.

    Design: Corner/validations/submit_with_archived_entitlement_rejected
    """
    wa = validate_success(api.create_entitlement(
        create_entitlement_payload(name="WillArch", system_code="WA", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([wa["id"]], name="RoleWA"), CATALOG), 201)
    validate_success(api.archive_entitlement(wa["id"], CATALOG), 200)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Wa", email="wa@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-c", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)

    resp = api.submit_access_request(req["id"], mgr)
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_ARCHIVED.value)


def test_new_access_request_starts_in_draft(api):
    """PRD §3.3: "The request is created in DRAFT status, and the raising
    manager's X-User-ID is stored as requester_user_id".

    A freshly raised access request has status == DRAFT.

    Design: Corner/state_machines/new_access_request_starts_in_draft
    """
    ei = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntI", system_code="EI", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([ei["id"]], name="RoleI"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Ii", email="ii@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-b", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    assert req["status"] == "DRAFT", req["status"]


def test_submit_from_approved_returns_invalid_state(api):
    """PRD §2.6: "State validity is checked fourth: if the target resource is not
    in a state from which the requested transition is defined, the request is
    rejected with ERR_INVALID_STATE."
    PRD §3.3: "Submission is allowed from DRAFT and again from RETURNED".

    Submitting an already-APPROVED request -> 409 ERR_INVALID_STATE (APPROVED is
    not a state from which submit is defined).

    Design: Corner/state_machines/submit_from_approved_returns_invalid_state
    """
    es = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntS", system_code="ES", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([es["id"]], name="RoleS"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Si", email="si@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-a", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)
    apr = build_user_headers("apr-a", "AccessApprover")
    validate_success(api.approve_access_request(req["id"], {}, apr), 200)

    resp = api.submit_access_request(req["id"], mgr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
