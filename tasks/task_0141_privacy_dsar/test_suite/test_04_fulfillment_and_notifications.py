"""Fulfillment fan-out, item dispatch/ack/complete, processor notifications,
OCC stale-version guards, and the SKIPPED_EXEMPT fan-out branch."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_instant_equals,
    TEST_USERS,
    make_privacy_officer_headers,
    setup_registry, create_request, create_request_under_review,
    create_request_fulfilling, add_confirmed_finding,
    get_item_for_finding, dispatch_item_to_dispatched,
    get_item_notification, set_clock,
    verify_request, complete_discovery,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
_FW = TEST_USERS["fulfillment_worker_headers"]
_PA = TEST_USERS["processor_agent_headers"]


def test_dispatch_fulfillment_immediate_consistency(api):
    """PRD §3.5: "Dispatching fulfillment is the pivotal PrivacyOfficer action that
    advances the request UNDER_REVIEW → FULFILLING and materializes the work to be
    done ... the system fans out one fulfillment item per CONFIRMED finding."

    Design: Corner/consistency_model/dispatch_fulfillment_changes_visible_in_same_response_immediate
    """
    ctx = create_request_under_review(intake_user_id="intake-ic")
    req = ctx["request"]
    officer = make_privacy_officer_headers("officer-ic")
    dispatched = validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": req["version"]}, officer), 200)
    assert dispatched["status"] == "FULFILLING"
    data, meta = validate_paginated(api.list_request_fulfillment_items(req["id"], _PO))
    assert meta["total_count"] == 1


def test_dispatch_fulfillment_creates_skipped_exempt_for_upheld_exemption(api):
    """PRD §3.5: "A finding whose data_category is shielded by an UPHELD exemption
    produces an item created directly in SKIPPED_EXEMPT."

    Design: Corner/state_machines/dispatch_fulfillment_creates_skipped_exempt_for_upheld_exemption
    """
    ctx = create_request_under_review(
        jurisdiction="GDPR", request_type="ACCESS",
        findings=[{"data_category": "FINANCIAL", "record_count": 2, "confidence": "EXACT"}],
        intake_user_id="intake-skip")
    req = ctx["request"]
    finding = ctx["findings"][0]
    exemption = validate_success(
        api.create_exemption(req["id"], {"data_category": "FINANCIAL", "basis": "TRADE_SECRET"}, _PO), 201)
    validate_success(api.decide_exemption(exemption["id"], {"decision": "UPHELD"}, _PO), 200)
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-skip")
    fulfilled = validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    assert fulfilled["status"] == "FULFILLING"
    item = get_item_for_finding(finding["id"])
    assert item["state"] == "SKIPPED_EXEMPT"


def test_item_dispatch_requires_active_processor(api):
    """PRD §3.6: "It requires that the item be QUEUED, that the parent request be in
    FULFILLING, and that the referenced processor be ACTIVE — dispatching to a
    SUSPENDED processor is refused with ERR_PROCESSOR_SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/item_dispatch_requires_active_processor
    """
    ctx = create_request_fulfilling(intake_user_id="intake-psusp",
                                    officer_user_id="officer-psusp")
    item = ctx["items"][0]
    validate_success(api.suspend_processor(ctx["processor"]["id"], _PO), 200)
    resp = api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW)
    validate_error(resp, ApiErrorId.ERR_PROCESSOR_SUSPENDED.value, 409)
    after = validate_success(api.get_fulfillment_item(item["id"], _PO), 200)
    assert after["state"] == "QUEUED"


def test_complete_item_before_ack_returns_notification_not_acked(api):
    """PRD §3.6: "It requires the item to be DISPATCHED and the item's notification
    to have reached ACKNOWLEDGED; completing an item whose notification is not yet
    acknowledged is refused with ERR_NOTIFICATION_NOT_ACKED."

    Design: Corner/validations/complete_item_before_ack_returns_notification_not_acked
    """
    ctx = create_request_fulfilling(intake_user_id="intake-nack",
                                    officer_user_id="officer-nack")
    item = ctx["items"][0]
    dispatched, _ = dispatch_item_to_dispatched(item["id"])
    assert dispatched["state"] == "DISPATCHED"
    resp = api.complete_item(item["id"], _FW)
    validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_ACKED.value, 409)
    after = validate_success(api.get_fulfillment_item(item["id"], _PO), 200)
    assert after["state"] == "DISPATCHED"


def test_occ_correct_version_dispatch_succeeds_and_bumps_version(api):
    """PRD §2.8: "when dispatching an individual fulfillment item, the caller must
    include expected_item_version carrying the item's last-observed version."
    PRD §3.6: "A successful dispatch creates a processor notification for this
    item's processor, born in SENT ... and bumps the item's version."

    Design: Corner/cross_cutting/occ_correct_version_dispatch_succeeds_and_bumps_version
    """
    ctx = create_request_fulfilling(intake_user_id="intake-occ-ok",
                                    officer_user_id="officer-occ-ok")
    item = ctx["items"][0]
    assert item["version"] == 1
    data = validate_success(
        api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    assert data["state"] == "DISPATCHED"
    assert data["version"] == 2


def test_occ_stale_version_on_item_dispatch_after_unblock(api):
    """PRD §2.8: "if a prior unblock has advanced the item's version since the
    client read it, the dispatch is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §3.5: "A successful unblock bumps the item's version — which is precisely
    why a later dispatch that still carries the pre-unblock expected_item_version
    will be caught by the stale-version check."

    Design: Corner/cross_cutting/occ_stale_version_on_item_dispatch_after_unblock
    """
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    validate_success(
        api.create_legal_hold(
            {"controller_id": controller["id"], "data_subject_id": subject["id"],
             "matter_reference": "M-occ", "data_categories": ["IDENTITY"]}, _PO), 201)
    req = create_request(controller["id"], subject["id"], request_type="DELETION")
    verify_request(req["id"], intake_user_id="intake-occ-stale")
    finding = add_confirmed_finding(req["id"], processor["id"],
                                    data_category="IDENTITY", record_count=1)
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-occ-stale")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    assert item["state"] == "BLOCKED"
    stale_version = item["version"]
    # Lift the hold, then unblock (this advances the item version).
    holds = api.list_legal_holds(_PO, params={"data_subject_id": subject["id"]}).json()["data"]
    validate_success(api.lift_legal_hold(holds[0]["id"], _PO), 200)
    validate_success(api.unblock_item(item["id"], _PO), 200)
    # Dispatch carrying the pre-unblock version is stale.
    resp = api.dispatch_item(item["id"], {"expected_item_version": stale_version}, _FW)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_dispatch_fulfillment_stale_request_version_returns_stale_version(api):
    """PRD §2.8: "When dispatching fulfillment for a request, the caller must
    include expected_request_version carrying the version of the request as the
    client last read it. Between that read and this dispatch, an exemption decision
    or a finding confirmation may legitimately have advanced the request's version;
    if so ... the dispatch is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/dispatch_fulfillment_stale_request_version_returns_stale_version
    """
    ctx = create_request_under_review(intake_user_id="intake-occ-req")
    req = ctx["request"]
    stale_version = req["version"]
    # An exemption assertion + decision advances the request version after capture.
    exemption = validate_success(
        api.create_exemption(req["id"], {"data_category": "IDENTITY", "basis": "TRADE_SECRET"}, _PO), 201)
    validate_success(api.decide_exemption(exemption["id"], {"decision": "OVERRULED"}, _PO), 200)
    officer = make_privacy_officer_headers("officer-occ-req")
    resp = api.dispatch_fulfillment(req["id"], {"expected_request_version": stale_version}, officer)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_processor_ack_deadline_default_seventy_two_hours(api):
    """PRD §3.6: "computes an ack_deadline_at equal to its dispatched_at plus the
    processor's sla_ack_hours hours of exact UTC-instant arithmetic."
    PRD §3.1: "sla_ack_hours ... defaults to 72 when omitted."

    Design: Corner/calculations/processor_ack_deadline_default_seventy_two_hours
    """
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    set_clock("2026-01-10T10:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-ack72")
    finding = add_confirmed_finding(req["id"], processor["id"])
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-ack72")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    validate_success(api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    notif = get_item_notification(item["id"])
    assert_instant_equals(notif["ack_deadline_at"], "2026-01-13T10:00:00Z", "ack deadline 72h")


def test_processor_notification_ack_window_buffered_by_sla_hours(api):
    """PRD §3.6: "A notification goes OVERDUE only by the clock sweep: when the
    clock is set forward past a notification's ack_deadline_at while it is still
    SENT, the sweep marks it OVERDUE."

    Design: Difficulty/resource_temporal_overlap/processor_notification_ack_window_buffered_by_sla_hours
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    processor = validate_success(
        api.create_processor(
            {"controller_id": controller["id"], "name": "P24", "notify_email": "p24@x.example",
             "sla_ack_hours": 24}, _PO), 201)
    set_clock("2026-01-10T10:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-ovr")
    finding = add_confirmed_finding(req["id"], processor["id"])
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-ovr")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    validate_success(api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    notif = get_item_notification(item["id"])
    assert_instant_equals(notif["ack_deadline_at"], "2026-01-11T10:00:00Z", "ack deadline 24h")
    # Advance one second past the ack deadline -> sweep marks it OVERDUE.
    set_clock("2026-01-11T10:00:01Z")
    after = validate_success(api.get_notification(notif["id"], _PA), 200)
    assert after["state"] == "OVERDUE"


def test_acknowledge_overdue_notification_still_allowed(api):
    """PRD §3.6: "A ProcessorAgent acknowledges it, moving it to ACKNOWLEDGED;
    acknowledgement is allowed whether the notification is still SENT or has already
    gone OVERDUE."

    Design: Corner/state_machines/acknowledge_overdue_notification_still_allowed
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    processor = validate_success(
        api.create_processor(
            {"controller_id": controller["id"], "name": "P24b", "notify_email": "p24b@x.example",
             "sla_ack_hours": 24}, _PO), 201)
    set_clock("2026-01-10T10:00:00Z")
    req = create_request(controller["id"], subject["id"], "ACCESS",
                         received_at="2026-01-05T09:00:00Z")
    verify_request(req["id"], intake_user_id="intake-ackovr")
    finding = add_confirmed_finding(req["id"], processor["id"])
    complete_discovery(req["id"])
    cur = validate_success(api.get_dsar_request(req["id"], _PO), 200)
    officer = make_privacy_officer_headers("officer-ackovr")
    validate_success(
        api.dispatch_fulfillment(req["id"], {"expected_request_version": cur["version"]}, officer), 200)
    item = get_item_for_finding(finding["id"])
    validate_success(api.dispatch_item(item["id"], {"expected_item_version": item["version"]}, _FW), 200)
    notif = get_item_notification(item["id"])
    set_clock("2026-01-11T11:00:00Z")  # past ack deadline -> OVERDUE
    overdue = validate_success(api.get_notification(notif["id"], _PA), 200)
    assert overdue["state"] == "OVERDUE"
    acked = validate_success(api.acknowledge_notification(notif["id"], _PA), 200)
    assert acked["state"] == "ACKNOWLEDGED"
