"""Second-pass difficulty tests: each asserts a distinct PRD-verbatim facet of a
hard-scenario rule, giving each such rule a second independent test. Every test
here pairs with a primary test elsewhere carrying the same Design tag."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_instant_equals,
    TEST_USERS,
    make_intake_agent_headers, make_privacy_officer_headers,
    setup_registry, create_request, create_request_under_review,
    create_request_fulfilling, create_request_in_discovery,
    add_confirmed_finding, complete_discovery, verify_request,
    get_item_for_finding, dispatch_ack_complete_item,
    set_clock, create_consent,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
_FW = TEST_USERS["fulfillment_worker_headers"]
_PA = TEST_USERS["processor_agent_headers"]


# ---- dual_variant_calc / erasure_residual_diverges_completed_vs_uncompleted ----
def test_erasure_residual_drops_to_zero_when_all_completed(api):
    """PRD §3.7: "an item that has reached COMPLETED is fully remediated and
    contributes nothing to residual ... When the total is 0 (the request has no
    ERASE items at all), the score is 0.00."

    Design: Difficulty/dual_variant_calc/erasure_residual_diverges_completed_vs_uncompleted
    """
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    req = create_request(controller["id"], subject["id"], request_type="DELETION")
    verify_request(req["id"], intake_user_id="intake-er0")
    f_health = add_confirmed_finding(req["id"], processor["id"], data_category="HEALTH", record_count=2)
    f_fin = add_confirmed_finding(req["id"], processor["id"], data_category="FINANCIAL", record_count=3)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-er0")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    dispatch_ack_complete_item(get_item_for_finding(f_health["id"])["id"])
    dispatch_ack_complete_item(get_item_for_finding(f_fin["id"])["id"])
    risk = validate_success(api.get_dsar_risk(req["id"], _PO), 200)
    # Both COMPLETED -> residual 0, total 22 -> 0.00.
    assert risk["residual_weighted"] == 0
    assert risk["total_weighted"] == 22
    assert risk["erasure_exposure_score"] == pytest.approx(0.00, abs=0.001)


# ---- combinatorial_formula / fulfillment_progress_sum_then_round_two_thirds ----
def test_fulfillment_progress_full_when_all_items_terminal(api):
    """PRD §3.7: "it is one hundred multiplied by the number of items in COMPLETED
    or SKIPPED_EXEMPT, divided by the total number of items, with the division
    performed first and the resulting percentage rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/fulfillment_progress_sum_then_round_two_thirds
    """
    ctx = create_request_fulfilling(
        jurisdiction="GDPR", request_type="ACCESS",
        findings=[{"data_category": "IDENTITY", "record_count": 1, "confidence": "EXACT"},
                  {"data_category": "CONTACT", "record_count": 1, "confidence": "EXACT"},
                  {"data_category": "BEHAVIORAL", "record_count": 1, "confidence": "EXACT"}],
        intake_user_id="intake-prog2", officer_user_id="officer-prog2")
    for f in ctx["findings"]:
        dispatch_ack_complete_item(get_item_for_finding(f["id"])["id"])
    data = validate_success(api.get_dsar_request(ctx["request"]["id"], _PO), 200)
    # 3 of 3 terminal -> 100.00.
    assert data["fulfillment_progress_pct"] == pytest.approx(100.00, abs=0.001)


# ---- non_linear_state_machine / finding_confirm_then_redismiss_redecision_edge ----
def test_dismissed_finding_cannot_be_reconfirmed(api):
    """PRD §3.4: "a finding already CONFIRMED may still be dismissed
    (CONFIRMED → DISMISSED) so long as the request remains in DISCOVERY, but never
    reconfirmed."

    Design: Difficulty/non_linear_state_machine/finding_confirm_then_redismiss_redecision_edge
    """
    ctx = create_request_in_discovery(intake_user_id="intake-redec2")
    finding = add_confirmed_finding(ctx["request"]["id"], ctx["processor"]["id"],
                                    data_category="CONTACT", record_count=1)
    validate_success(api.dismiss_finding(finding["id"], _PO), 200)
    # Reconfirming the now-DISMISSED finding is refused.
    resp = api.confirm_finding(finding["id"], _PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_finding(finding["id"], _PO), 200)
    assert after["state"] == "DISMISSED"


# ---- transitive_cascade / dispatch_then_complete_suppress_cascades_consent_withdrawal ----
def test_suppress_completion_marks_item_completed_and_stamps_withdrawn_at(api):
    """PRD §3.6: "Completing a fulfillment item is a FulfillmentWorker action that
    advances it DISPATCHED → COMPLETED ... every consent record of the subject whose
    purpose is MARKETING, ANALYTICS, or SALE_OF_DATA and whose state is still
    GRANTED is flipped to WITHDRAWN with its withdrawn_at stamped to the current
    clock instant."

    Design: Difficulty/transitive_cascade/dispatch_then_complete_suppress_cascades_consent_withdrawal
    """
    controller, subject, processor = setup_registry("CCPA", with_processor=True)
    consent = create_consent(subject["id"], purpose="ANALYTICS")
    req = create_request(controller["id"], subject["id"], request_type="OPT_OUT")
    verify_request(req["id"], intake_user_id="intake-supp2")
    finding = add_confirmed_finding(req["id"], processor["id"],
                                    data_category="BEHAVIORAL", record_count=1)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-supp2")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    assert item["action"] == "SUPPRESS"
    completed = dispatch_ack_complete_item(item["id"])
    assert completed["state"] == "COMPLETED"
    after = validate_success(api.get_consent_record(consent["id"], _PO), 200)
    assert after["state"] == "WITHDRAWN"
    assert after["withdrawn_at"] is not None


# ---- transitive_cascade / clock_advance_expires_request_decrements_open_count ----
def test_clock_advance_expires_request_to_closed_expired(api):
    """PRD §3.8: "every non-terminal request — one whose status is any of
    PENDING_VERIFICATION, VERIFICATION_REJECTED, DISCOVERY, UNDER_REVIEW, or
    FULFILLING — whose deadline_at now lies in the past is expired to
    CLOSED_EXPIRED."

    Design: Difficulty/transitive_cascade/clock_advance_expires_request_decrements_open_count
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-exp2")  # request now in DISCOVERY
    set_clock("2026-02-05T09:00:00Z")
    after = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert after["status"] == "CLOSED_EXPIRED"


# ---- priority_pair / segregation_beats_undecided_exemption_on_dispatch ----
def test_segregation_violation_leaves_no_exemption_decided_side_effect(api):
    """PRD §3.5: "the acting PrivacyOfficer must not be the operator pinned in
    verified_by_user_id — the segregation-of-duties rule, under which dispatching
    with the same X-User-ID that verified identity is refused with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_undecided_exemption_on_dispatch
    """
    shared = "shared-seg2"
    ctx = create_request_under_review(
        jurisdiction="GDPR", request_type="ACCESS",
        findings=[{"data_category": "IDENTITY", "record_count": 1, "confidence": "EXACT"}],
        intake_user_id=shared)
    req = ctx["request"]
    exemption = validate_success(
        api.create_exemption(req["id"], {"data_category": "IDENTITY", "basis": "TRADE_SECRET"}, _PO), 201)
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers(shared)
    resp = api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    # The exemption is untouched (still ASSERTED) — dispatch never proceeded.
    ex_after = validate_success(api.get_exemption(exemption["id"], _PO), 200)
    assert ex_after["state"] == "ASSERTED"


# ---- priority_pair / invalid_state_beats_processor_suspended_on_dispatch_item ----
def test_redundant_dispatch_on_completed_item_rejected_state_over_processor(api):
    """PRD §3.6: "It requires that the item be QUEUED, that the parent request be in
    FULFILLING, and that the referenced processor be ACTIVE."
    PRD §3.9: "State validity is then checked: a target not in a valid state for the
    requested transition yields ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_processor_suspended_on_dispatch_item
    """
    ctx = create_request_fulfilling(intake_user_id="intake-isp2",
                                    officer_user_id="officer-isp2")
    item = ctx["items"][0]
    completed = dispatch_ack_complete_item(item["id"])
    cur = validate_success(api.get_fulfillment_item(item["id"], _PO), 200)
    validate_success(api.suspend_processor(ctx["processor"]["id"], _PO), 200)
    # Dispatch on a COMPLETED item: ERR_INVALID_STATE despite the SUSPENDED processor.
    resp = api.dispatch_item(item["id"], {"expected_item_version": cur["version"]}, _FW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---- boundary_precision / deadline_exact_instant_is_not_past ----
def test_deadline_one_second_before_instant_still_admits_verify(api):
    """PRD §3.2: "and that the request not be past its deadline (if the clock has
    passed deadline_at, the action is refused with ERR_DEADLINE_PASSED)".

    Design: Difficulty/boundary_precision_check/deadline_exact_instant_is_not_past
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    # One second before the deadline instant — clearly not past, verify succeeds.
    set_clock("2026-02-04T08:59:59Z")
    data = validate_success(
        api.verify_identity(req["id"], {"evidence_reference": "ev"},
                            make_intake_agent_headers("intake-exact2")), 200)
    assert data["status"] == "DISCOVERY"


# ---- resource_temporal_overlap / deadline_window_inclusive_endpoint_request_clock ----
def test_request_survives_at_exact_deadline_instant_not_swept(api):
    """PRD §3.8: "every non-terminal request ... whose deadline_at now lies in the
    past is expired to CLOSED_EXPIRED."

    Design: Difficulty/resource_temporal_overlap/deadline_window_inclusive_endpoint_request_clock
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    set_clock("2026-01-05T09:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    # Clock exactly at deadline_at: not in the past, so the request is NOT swept.
    set_clock("2026-02-04T09:00:00Z")
    data = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    assert data["status"] != "CLOSED_EXPIRED"
    assert data["status"] == "PENDING_VERIFICATION"


# ---- resource_temporal_overlap / processor_notification_ack_window_buffered_by_sla_hours ----
def test_notification_not_overdue_before_ack_window_elapses(api):
    """PRD §3.6: "A notification goes OVERDUE only by the clock sweep: when the clock
    is set forward past a notification's ack_deadline_at while it is still SENT, the
    sweep marks it OVERDUE."

    Design: Difficulty/resource_temporal_overlap/processor_notification_ack_window_buffered_by_sla_hours
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    processor = validate_success(
        api.create_processor(
            {"controller_id": controller["id"], "name": "P24c", "notify_email": "p24c@x.example",
             "sla_ack_hours": 24}, _PO), 201)
    set_clock("2026-01-10T10:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-nov")
    finding = add_confirmed_finding(req["id"], processor["id"])
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-nov")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    validate_success(api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    notif = api.list_item_notifications(item["id"], _FW).json()["data"][0]
    assert_instant_equals(notif["ack_deadline_at"], "2026-01-11T10:00:00Z", "ack deadline 24h")
    # Advance to before the ack deadline -> still SENT, not OVERDUE.
    set_clock("2026-01-11T09:00:00Z")
    after = validate_success(api.get_notification(notif["id"], _PA), 200)
    assert after["state"] == "SENT"


# ---- cross_entity_state_dependency / item_dispatch_requires_active_processor ----
def test_item_dispatch_succeeds_against_active_processor(api):
    """PRD §3.6: "A QUEUED fulfillment item is dispatched to its processor by a
    FulfillmentWorker, advancing it QUEUED → DISPATCHED ... A successful dispatch
    creates a processor notification for this item's processor, born in SENT."

    Design: Difficulty/cross_entity_state_dependency/item_dispatch_requires_active_processor
    """
    ctx = create_request_fulfilling(intake_user_id="intake-pact",
                                    officer_user_id="officer-pact")
    item = ctx["items"][0]
    data = validate_success(
        api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    assert data["state"] == "DISPATCHED"
    notifs = api.list_item_notifications(item["id"], _FW).json()["data"]
    assert len(notifs) == 1
    assert notifs[0]["state"] == "SENT"


# ---- compensating_invariant / open_request_count_conserved_across_intake_and_close ----
def test_open_request_count_rises_to_one_on_intake(api):
    """PRD §3.1: "the controller begins life with an open_request_count of 0 ...
    whenever a new request is intaken, it rises."

    Design: Difficulty/compensating_invariant/open_request_count_conserved_across_intake_and_close
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    before = validate_success(api.get_controller(controller["id"], _PO), 200)
    assert before["open_request_count"] == 0
    create_request(controller["id"], subject["id"], "ACCESS")
    after = validate_success(api.get_controller(controller["id"], _PO), 200)
    assert after["open_request_count"] == 1


# ---- compensating_invariant / consent_grant_count_conserved_suppress_then_no_double_withdraw ----
def test_suppress_withdraws_marketing_once_no_double_withdraw(api):
    """PRD §3.6: "every consent record of the subject whose purpose is MARKETING,
    ANALYTICS, or SALE_OF_DATA and whose state is still GRANTED is flipped to
    WITHDRAWN with its withdrawn_at stamped to the current clock instant."

    Design: Difficulty/compensating_invariant/consent_grant_count_conserved_suppress_then_no_double_withdraw
    """
    controller, subject, processor = setup_registry("CCPA", with_processor=True)
    consent_mkt = create_consent(subject["id"], purpose="MARKETING")
    req = create_request(controller["id"], subject["id"], request_type="OPT_OUT")
    verify_request(req["id"], intake_user_id="intake-nodbl")
    finding = add_confirmed_finding(req["id"], processor["id"],
                                    data_category="BEHAVIORAL", record_count=1)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-nodbl")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    dispatch_ack_complete_item(item["id"])
    after = validate_success(api.get_consent_record(consent_mkt["id"], _PO), 200)
    assert after["state"] == "WITHDRAWN"
    stamped = after["withdrawn_at"]
    # The MARKETING grant was withdrawn exactly once; its withdrawn_at is stamped.
    assert stamped is not None
    # Re-reading shows the same single WITHDRAWN state (no second withdrawal path).
    again = validate_success(api.get_consent_record(consent_mkt["id"], _PO), 200)
    assert again["state"] == "WITHDRAWN"
    assert again["withdrawn_at"] == stamped
