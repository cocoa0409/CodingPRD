"""Discovery findings, finding resolution, complete-discovery gating, and exemptions."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_registry, create_request_in_discovery, create_request_under_review,
    add_finding, add_confirmed_finding, create_pending_request, create_request,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]


def test_processor_sla_ack_hours_default_applied(api):
    """PRD §3.1: "an optional sla_ack_hours stating how many hours the processor is
    contractually allowed to acknowledge a notification; sla_ack_hours must be at
    least 1 and defaults to 72 when omitted. A processor's status begins ACTIVE."

    Design: Corner/entities/processor_sla_ack_hours_default_applied
    """
    controller, _, _ = setup_registry("GDPR", with_processor=False)
    resp = api.create_processor(
        {"controller_id": controller["id"], "name": "DefProc", "notify_email": "dp@x.example"}, _PO)
    data = validate_success(resp, 201)
    assert data["sla_ack_hours"] == 72
    assert data["status"] == "ACTIVE"


def test_finding_record_count_zero_rejected_boundary(api):
    """PRD §2.9: "On any endpoint that accepts a body, the server validates ... that
    a finding's record_count is at least 1. A violation of any of these is reported
    as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/finding_record_count_zero_rejected_boundary
    """
    ctx = create_request_in_discovery(intake_user_id="intake-rc0")
    resp = api.create_finding(
        ctx["request"]["id"],
        {"processor_id": ctx["processor"]["id"], "data_category": "IDENTITY",
         "record_count": 0, "confidence": "EXACT"}, _PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_finding_confirm_then_dismiss_redecision_edge(api):
    """PRD §3.4: "a finding already CONFIRMED may still be dismissed
    (CONFIRMED → DISMISSED) so long as the request remains in DISCOVERY, but never
    reconfirmed."

    Design: Difficulty/non_linear_state_machine/finding_confirm_then_redismiss_redecision_edge
    """
    ctx = create_request_in_discovery(intake_user_id="intake-redec")
    finding = add_finding(ctx["request"]["id"], ctx["processor"]["id"],
                          data_category="CONTACT", record_count=1, confidence="PROBABLE")
    validate_success(api.confirm_finding(finding["id"], _PO), 200)
    dismissed = validate_success(api.dismiss_finding(finding["id"], _PO), 200)
    assert dismissed["state"] == "DISMISSED"


def test_confirm_dismissed_finding_returns_invalid_state(api):
    """PRD §3.4: "attempting a finding decision when the finding is not in the
    required state, or when its parent request has already left DISCOVERY, is
    refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/confirm_finding_from_dismissed_terminal_returns_invalid_state
    """
    ctx = create_request_in_discovery(intake_user_id="intake-dt")
    finding = add_finding(ctx["request"]["id"], ctx["processor"]["id"],
                          data_category="CONTACT", record_count=1, confidence="PROBABLE")
    validate_success(api.dismiss_finding(finding["id"], _PO), 200)
    resp = api.confirm_finding(finding["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_finding(finding["id"], _PO), 200)
    assert after["state"] == "DISMISSED"


def test_complete_discovery_zero_findings_returns_no_findings(api):
    """PRD §3.4: "when at least one finding exists (an attempt with zero findings is
    refused with ERR_NO_FINDINGS)".

    Design: Difficulty/boundary_precision_check/complete_discovery_zero_findings_empty_set_boundary
    """
    ctx = create_request_in_discovery(intake_user_id="intake-nf")
    resp = api.complete_discovery(ctx["request"]["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_NO_FINDINGS.value, 409)
    after = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    assert after["status"] == "DISCOVERY"


def test_complete_discovery_empty_set_boundary_then_succeeds_with_one(api):
    """PRD §3.4: "Closing discovery ... is permitted only when the request is in
    DISCOVERY, when at least one finding exists (an attempt with zero findings is
    refused with ERR_NO_FINDINGS)".

    Design: Difficulty/boundary_precision_check/complete_discovery_zero_findings_empty_set_boundary
    """
    ctx = create_request_in_discovery(intake_user_id="intake-nf2")
    # Boundary X (zero findings) rejects.
    resp = api.complete_discovery(ctx["request"]["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_NO_FINDINGS.value, 409)
    # X+1 (one confirmed finding) succeeds.
    add_confirmed_finding(ctx["request"]["id"], ctx["processor"]["id"])
    ok = validate_success(api.complete_discovery(ctx["request"]["id"], _PO), 200)
    assert ok["status"] == "UNDER_REVIEW"


def test_complete_discovery_with_pending_finding_returns_unresolved_findings(api):
    """PRD §3.4: "and when no finding remains PENDING — every finding must be either
    CONFIRMED or DISMISSED, or the action is refused with ERR_UNRESOLVED_FINDINGS."

    Design: Corner/validations/complete_discovery_with_pending_finding_returns_unresolved_findings
    """
    ctx = create_request_in_discovery(intake_user_id="intake-uf")
    add_finding(ctx["request"]["id"], ctx["processor"]["id"],
                data_category="IDENTITY", record_count=1, confidence="PROBABLE")
    resp = api.complete_discovery(ctx["request"]["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_FINDINGS.value, 409)
    after = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    assert after["status"] == "DISCOVERY"


def test_dispatch_fulfillment_from_pending_verification_returns_invalid_state(api):
    """PRD §3.5: "Three preconditions are evaluated for this action ... First, the
    request must be in UNDER_REVIEW."
    PRD §3.9: "State validity is then checked: a target not in a valid state for the
    requested transition yields ERR_INVALID_STATE."

    Design: Corner/state_machines/dispatch_fulfillment_from_pending_verification_returns_invalid_state
    """
    ctx = create_pending_request("GDPR", "ACCESS", with_processor=False)
    req = ctx["request"]
    resp = api.dispatch_fulfillment(
        req["id"], {"expected_request_version": req["version"]}, _PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_exemption_upheld_requires_active_legal_hold_present(api):
    """PRD §3.5: "when the basis is LEGAL_HOLD, upholding the claim requires that an
    ACTIVE legal hold actually exist on the subject covering the same data_category;
    if no such hold backs it, the decision is refused with
    ERR_EXEMPTION_BASIS_UNSUPPORTED."

    Design: Difficulty/cross_entity_state_dependency/exemption_upheld_requires_active_legal_hold_present
    """
    ctx = create_request_under_review(
        jurisdiction="GDPR", request_type="DELETION",
        findings=[{"data_category": "HEALTH", "record_count": 1, "confidence": "EXACT"}],
        intake_user_id="intake-eh")
    exemption = validate_success(
        api.create_exemption(ctx["request"]["id"],
                            {"data_category": "HEALTH", "basis": "LEGAL_HOLD"}, _PO), 201)
    resp = api.decide_exemption(exemption["id"], {"decision": "UPHELD"}, _PO)
    validate_error(resp, ApiErrorId.ERR_EXEMPTION_BASIS_UNSUPPORTED.value, 409)
    after = validate_success(api.get_exemption(exemption["id"], _PO), 200)
    assert after["state"] == "ASSERTED"


def test_exemption_legal_hold_basis_upheld_when_hold_exists(api):
    """PRD §3.5: "when the basis is LEGAL_HOLD, upholding the claim requires that an
    ACTIVE legal hold actually exist on the subject covering the same data_category".

    Design: Difficulty/cross_entity_state_dependency/exemption_upheld_requires_active_legal_hold_present
    """
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    # Place an ACTIVE hold on HEALTH before review so the uphold is backed.
    validate_success(
        api.create_legal_hold(
            {"controller_id": controller["id"], "data_subject_id": subject["id"],
             "matter_reference": "M-eh2", "data_categories": ["HEALTH"]}, _PO), 201)
    req = create_request(controller["id"], subject["id"], request_type="DELETION")
    from test_helpers import make_intake_agent_headers
    validate_success(api.verify_identity(req["id"], {"evidence_reference": "ev"},
                                         make_intake_agent_headers("intake-eh2")), 200)
    finding = validate_success(
        api.create_finding(req["id"],
                          {"processor_id": processor["id"], "data_category": "HEALTH",
                           "record_count": 1, "confidence": "EXACT"}, _PO), 201)
    validate_success(api.confirm_finding(finding["id"], _PO), 200)
    validate_success(api.complete_discovery(req["id"], _PO), 200)
    exemption = validate_success(
        api.create_exemption(req["id"],
                           {"data_category": "HEALTH", "basis": "LEGAL_HOLD"}, _PO), 201)
    upheld = validate_success(api.decide_exemption(exemption["id"], {"decision": "UPHELD"}, _PO), 200)
    assert upheld["state"] == "UPHELD"
