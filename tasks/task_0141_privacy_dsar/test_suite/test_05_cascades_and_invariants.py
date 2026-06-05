"""Cross-entity cascades (SUPPRESS->consent withdrawal, clock expiry->open_count),
legal-hold block/unblock compensation, close gating, and compensating invariants."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    make_intake_agent_headers, make_privacy_officer_headers,
    setup_registry, create_request, create_request_fulfilling,
    add_confirmed_finding, complete_discovery, verify_request,
    get_item_for_finding, dispatch_ack_complete_item,
    create_deletion_fulfilling_with_hold, set_clock, create_consent,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
_FW = TEST_USERS["fulfillment_worker_headers"]


def test_suppress_completion_cascades_consent_withdrawal(api):
    """PRD §3.6: "when a completed item's action is SUPPRESS, every consent record
    of the subject whose purpose is MARKETING, ANALYTICS, or SALE_OF_DATA and whose
    state is still GRANTED is flipped to WITHDRAWN with its withdrawn_at stamped to
    the current clock instant."

    Design: Difficulty/transitive_cascade/dispatch_then_complete_suppress_cascades_consent_withdrawal
    """
    controller, subject, processor = setup_registry("CCPA", with_processor=True)
    consent = create_consent(subject["id"], purpose="MARKETING")
    req = create_request(controller["id"], subject["id"], request_type="OPT_OUT")
    verify_request(req["id"], intake_user_id="intake-supp")
    finding = add_confirmed_finding(req["id"], processor["id"],
                                    data_category="BEHAVIORAL", record_count=1)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-supp")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    completed = dispatch_ack_complete_item(item["id"])
    assert completed["state"] == "COMPLETED"
    after = validate_success(api.get_consent_record(consent["id"], _PO), 200)
    assert after["state"] == "WITHDRAWN"
    assert after["withdrawn_at"] is not None


def test_consent_grant_count_conserved_essential_stays_granted(api):
    """PRD §3.6: "Consent records for the ESSENTIAL purpose are never swept by this
    cascade."

    Design: Difficulty/compensating_invariant/consent_grant_count_conserved_suppress_then_no_double_withdraw
    """
    controller, subject, processor = setup_registry("CCPA", with_processor=True)
    consent_mkt = create_consent(subject["id"], purpose="MARKETING")
    consent_ess = create_consent(subject["id"], purpose="ESSENTIAL")
    req = create_request(controller["id"], subject["id"], request_type="OPT_OUT")
    verify_request(req["id"], intake_user_id="intake-cons")
    finding = add_confirmed_finding(req["id"], processor["id"],
                                    data_category="BEHAVIORAL", record_count=1)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-cons")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    dispatch_ack_complete_item(item["id"])
    mkt = validate_success(api.get_consent_record(consent_mkt["id"], _PO), 200)
    ess = validate_success(api.get_consent_record(consent_ess["id"], _PO), 200)
    assert mkt["state"] == "WITHDRAWN"
    assert ess["state"] == "GRANTED"


def test_clock_advance_expires_request_decrements_open_count(api):
    """PRD §3.8: "every non-terminal request ... whose deadline_at now lies in the
    past is expired to CLOSED_EXPIRED; each such expiry ... recomputes the owning
    controller's open_request_count."

    Design: Difficulty/transitive_cascade/clock_advance_expires_request_decrements_open_count
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-exp")
    set_clock("2026-02-05T09:00:00Z")  # one day past deadline -> sweep
    after_req = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    after_ctrl = validate_success(api.get_controller(controller["id"], _PO), 200)
    assert after_req["status"] == "CLOSED_EXPIRED"
    assert after_ctrl["open_request_count"] == 0


def test_open_request_count_conserved_across_intake_and_close(api):
    """PRD §3.1: "Whenever a request reaches CLOSED_FULFILLED, CLOSED_REJECTED, or
    CLOSED_EXPIRED, the count is recomputed downward; whenever a new request is
    intaken, it rises."
    PRD §3.7: "From VERIFICATION_REJECTED, the same close action advances the
    request VERIFICATION_REJECTED → CLOSED_REJECTED."

    Design: Difficulty/compensating_invariant/open_request_count_conserved_across_intake_and_close
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    req = create_request(controller["id"], subject["id"], "ACCESS")
    after_intake = validate_success(api.get_controller(controller["id"], _PO), 200)
    assert after_intake["open_request_count"] == 1
    ia = make_intake_agent_headers("intake-cons2")
    validate_success(api.reject_identity(req["id"], {"reason": "no match"}, ia), 200)
    closed = validate_success(api.close_request(req["id"], {"disposition": "REJECTED"}, _PO), 200)
    assert closed["status"] == "CLOSED_REJECTED"
    final_ctrl = validate_success(api.get_controller(controller["id"], _PO), 200)
    assert final_ctrl["open_request_count"] == 0


def test_legal_hold_lift_then_unblock_item_compensation(api):
    """PRD §3.5: "once the legal hold over its category has been lifted, a
    PrivacyOfficer may unblock it, returning it BLOCKED → QUEUED. Unblocking is
    permitted only when the item is BLOCKED and no ACTIVE legal hold any longer
    covers the item's data_category."

    Design: Corner/state_machines/legal_hold_lift_then_unblock_item_compensation
    """
    ctx = create_deletion_fulfilling_with_hold(
        hold_categories=("IDENTITY",), finding_category="IDENTITY",
        intake_user_id="intake-unblk", officer_user_id="officer-unblk")
    assert ctx["item"]["state"] == "BLOCKED"
    validate_success(api.lift_legal_hold(ctx["hold"]["id"], _PO), 200)
    unblocked = validate_success(api.unblock_item(ctx["item"]["id"], _PO), 200)
    assert unblocked["state"] == "QUEUED"
    hold_after = validate_success(api.get_legal_hold(ctx["hold"]["id"], _PO), 200)
    assert hold_after["state"] == "LIFTED"


def test_unblock_item_while_hold_active_returns_legal_hold_active(api):
    """PRD §3.5: "Unblocking is permitted only when the item is BLOCKED and no
    ACTIVE legal hold any longer covers the item's data_category; if such a hold is
    still active, the unblock is refused with ERR_LEGAL_HOLD_ACTIVE."

    Design: Corner/state_machines/unblock_item_while_hold_active_returns_legal_hold_active
    """
    ctx = create_deletion_fulfilling_with_hold(
        hold_categories=("IDENTITY",), finding_category="IDENTITY",
        intake_user_id="intake-lha", officer_user_id="officer-lha")
    assert ctx["item"]["state"] == "BLOCKED"
    # Hold NOT lifted.
    resp = api.unblock_item(ctx["item"]["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_ACTIVE.value, 409)
    after = validate_success(api.get_fulfillment_item(ctx["item"]["id"], _PO), 200)
    assert after["state"] == "BLOCKED"


def test_close_fulfilling_with_open_item_returns_fulfillment_incomplete(api):
    """PRD §3.7: "From FULFILLING, closing advances the request FULFILLING →
    CLOSED_FULFILLED, but only when no fulfillment item remains in QUEUED,
    DISPATCHED, or BLOCKED — every item must have reached COMPLETED or
    SKIPPED_EXEMPT, or the close is refused with ERR_FULFILLMENT_INCOMPLETE."

    Design: Corner/validations/close_fulfilling_with_open_item_returns_fulfillment_incomplete
    """
    ctx = create_request_fulfilling(intake_user_id="intake-fi",
                                    officer_user_id="officer-fi")
    # One item is still QUEUED (never dispatched).
    resp = api.close_request(ctx["request"]["id"], {"disposition": "FULFILLED"}, _PO)
    validate_error(resp, ApiErrorId.ERR_FULFILLMENT_INCOMPLETE.value, 409)
    after = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    assert after["status"] == "FULFILLING"
