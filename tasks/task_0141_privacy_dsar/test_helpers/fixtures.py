"""Composite setup helpers for the Privacy DSAR API.

These encapsulate the multi-step API sequences that drive a request from intake
through identity verification, discovery, review, fulfillment dispatch, and item
completion, so tests can focus on the assertion under examination.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty database before
each test). Setup calls use the lenient get_success_data() validator so a broken
precondition surfaces as a clear "Setup step failed" message.

Identity threading: identity is opaque, but the segregation-of-duties rule
compares the dispatching officer's X-User-ID against the X-User-ID pinned at
verify-identity. Helpers therefore accept distinct intake_user_id /
officer_user_id values and default them to DIFFERENT operators so dispatch
succeeds; tests that want to provoke ERR_SEGREGATION_OF_DUTIES pass the same id
to both.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_intake_agent_headers,
    make_privacy_officer_headers,
    make_fulfillment_worker_headers,
    make_processor_agent_headers,
)
from .factories import (
    create_controller_payload,
    create_data_subject_payload,
    create_processor_payload,
    create_dsar_request_payload,
    create_finding_payload,
    create_legal_hold_payload,
    create_consent_record_payload,
    create_exemption_payload,
)
from .constants import DEFAULT_RECEIVED_AT

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
_FW = TEST_USERS["fulfillment_worker_headers"]
_PA = TEST_USERS["processor_agent_headers"]


# --------------------------------------------------------------------------
# Tier 0: clock control
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the server clock; triggers expiry/overdue sweeps. PrivacyOfficer only."""
    return get_success_data(_api.set_clock({"to_iso8601": to_iso8601}, _PO))


# --------------------------------------------------------------------------
# Tier 1: registry primitives
# --------------------------------------------------------------------------
def create_controller(jurisdiction="GDPR", **overrides):
    payload = create_controller_payload(jurisdiction=jurisdiction, **overrides)
    return get_success_data(_api.create_controller(payload, _PO))


def create_data_subject(controller_id, **overrides):
    payload = create_data_subject_payload(controller_id, **overrides)
    return get_success_data(_api.create_data_subject(payload, _IA))


def create_processor(controller_id, **overrides):
    payload = create_processor_payload(controller_id, **overrides)
    return get_success_data(_api.create_processor(payload, _PO))


def create_consent(data_subject_id, purpose="MARKETING"):
    payload = create_consent_record_payload(data_subject_id, purpose=purpose)
    return get_success_data(_api.create_consent_record(payload, _IA))


def create_legal_hold(controller_id, data_subject_id, data_categories=("IDENTITY",), **overrides):
    payload = create_legal_hold_payload(
        controller_id, data_subject_id,
        data_categories=list(data_categories), **overrides,
    )
    return get_success_data(_api.create_legal_hold(payload, _PO))


def setup_registry(jurisdiction="GDPR", with_processor=True):
    """Controller + subject (+ processor). Returns (controller, subject, processor|None)."""
    controller = create_controller(jurisdiction=jurisdiction)
    subject = create_data_subject(controller["id"])
    processor = create_processor(controller["id"]) if with_processor else None
    return controller, subject, processor


# --------------------------------------------------------------------------
# Tier 1: request state progression
# --------------------------------------------------------------------------
def create_request(controller_id, data_subject_id, request_type="ACCESS",
                   received_at=DEFAULT_RECEIVED_AT):
    payload = create_dsar_request_payload(
        controller_id, data_subject_id,
        request_type=request_type, received_at=received_at,
    )
    return get_success_data(_api.create_dsar_request(payload, _IA))


def create_pending_request(jurisdiction="GDPR", request_type="ACCESS",
                           received_at=DEFAULT_RECEIVED_AT, with_processor=True):
    """Registry + a fresh request still in PENDING_VERIFICATION.
    Returns dict(controller, subject, processor, request)."""
    controller, subject, processor = setup_registry(jurisdiction, with_processor)
    request = create_request(controller["id"], subject["id"], request_type, received_at)
    return {
        "controller": controller,
        "subject": subject,
        "processor": processor,
        "request": request,
    }


def verify_request(request_id, intake_user_id="intake-A", evidence_reference="ev"):
    headers = make_intake_agent_headers(intake_user_id)
    return get_success_data(
        _api.verify_identity(request_id, {"evidence_reference": evidence_reference}, headers)
    )


def create_request_in_discovery(jurisdiction="GDPR", request_type="ACCESS",
                                received_at=DEFAULT_RECEIVED_AT, intake_user_id="intake-A",
                                with_processor=True):
    """Registry + request advanced through verify-identity into DISCOVERY.
    Returns dict(controller, subject, processor, request)."""
    ctx = create_pending_request(jurisdiction, request_type, received_at, with_processor)
    verify_request(ctx["request"]["id"], intake_user_id=intake_user_id)
    ctx["request"] = get_success_data(_api.get_dsar_request(ctx["request"]["id"], _PO))
    ctx["intake_user_id"] = intake_user_id
    return ctx


def add_finding(request_id, processor_id, data_category="IDENTITY", record_count=1,
                confidence="EXACT"):
    payload = create_finding_payload(
        processor_id, data_category=data_category,
        record_count=record_count, confidence=confidence,
    )
    return get_success_data(_api.create_finding(request_id, payload, _PO))


def confirm_finding(finding_id):
    return get_success_data(_api.confirm_finding(finding_id, _PO))


def add_confirmed_finding(request_id, processor_id, data_category="IDENTITY",
                          record_count=1, confidence="EXACT"):
    finding = add_finding(request_id, processor_id, data_category, record_count, confidence)
    confirm_finding(finding["id"])
    return get_success_data(_api.get_finding(finding["id"], _PO))


def complete_discovery(request_id):
    return get_success_data(_api.complete_discovery(request_id, _PO))


def create_request_under_review(jurisdiction="GDPR", request_type="ACCESS",
                                findings=None, intake_user_id="intake-A",
                                received_at=DEFAULT_RECEIVED_AT):
    """Registry + request driven to UNDER_REVIEW with the given confirmed findings.

    `findings` is a list of dicts: {data_category, record_count, confidence}.
    Defaults to a single CONFIRMED IDENTITY x1 finding. Returns
    dict(controller, subject, processor, request, findings=[...]).
    """
    if findings is None:
        findings = [{"data_category": "IDENTITY", "record_count": 1, "confidence": "EXACT"}]
    ctx = create_request_in_discovery(
        jurisdiction, request_type, received_at, intake_user_id, with_processor=True
    )
    proc_id = ctx["processor"]["id"]
    created = []
    for spec in findings:
        created.append(add_confirmed_finding(
            ctx["request"]["id"], proc_id,
            data_category=spec.get("data_category", "IDENTITY"),
            record_count=spec.get("record_count", 1),
            confidence=spec.get("confidence", "EXACT"),
        ))
    complete_discovery(ctx["request"]["id"])
    ctx["request"] = get_success_data(_api.get_dsar_request(ctx["request"]["id"], _PO))
    ctx["findings"] = created
    return ctx


# --------------------------------------------------------------------------
# Tier 2/3: dispatch fan-out
# --------------------------------------------------------------------------
def dispatch_fulfillment(request_id, expected_request_version, officer_user_id="officer-B"):
    headers = make_privacy_officer_headers(officer_user_id)
    return get_success_data(
        _api.dispatch_fulfillment(
            request_id, {"expected_request_version": expected_request_version}, headers
        )
    )


def create_request_fulfilling(jurisdiction="GDPR", request_type="ACCESS",
                              findings=None, intake_user_id="intake-A",
                              officer_user_id="officer-B",
                              received_at=DEFAULT_RECEIVED_AT):
    """Registry + request fanned out into FULFILLING with one item per confirmed finding.

    Returns dict(controller, subject, processor, request, findings=[...], items=[...]).
    The officer who dispatches uses a DIFFERENT X-User-ID than the verifier so
    the segregation-of-duties rule passes.
    """
    ctx = create_request_under_review(
        jurisdiction, request_type, findings, intake_user_id, received_at
    )
    req_v = ctx["request"]["version"]
    dispatch_fulfillment(ctx["request"]["id"], req_v, officer_user_id=officer_user_id)
    ctx["request"] = get_success_data(_api.get_dsar_request(ctx["request"]["id"], _PO))
    items, _ = _list_items_for_request(ctx["request"]["id"])
    ctx["items"] = items
    ctx["officer_user_id"] = officer_user_id
    return ctx


def _list_items_for_request(request_id):
    resp = _api.list_request_fulfillment_items(request_id, _PO, params={"limit": 100})
    body = resp.json()
    return body["data"], body["meta"]


def get_item_for_finding(finding_id):
    """Return the single fulfillment item created for a confirmed finding."""
    resp = _api.list_fulfillment_items(_PO, params={"discovery_finding_id": finding_id})
    data = resp.json()["data"]
    assert data, f"no fulfillment item found for finding {finding_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier 3: item lifecycle (dispatch -> notify -> ack -> complete)
# --------------------------------------------------------------------------
def dispatch_item(item_id, expected_item_version, worker_user_id="worker-A"):
    headers = make_fulfillment_worker_headers(worker_user_id)
    return get_success_data(
        _api.dispatch_item(item_id, {"expected_item_version": expected_item_version}, headers)
    )


def get_item_notification(item_id):
    resp = _api.list_item_notifications(item_id, _FW)
    data = resp.json()["data"]
    assert data, f"no notification found for item {item_id}"
    return data[0]


def acknowledge_notification(notification_id, processor_user_id="processor-A"):
    headers = make_processor_agent_headers(processor_user_id)
    return get_success_data(_api.acknowledge_notification(notification_id, headers))


def complete_item(item_id, worker_user_id="worker-A"):
    headers = make_fulfillment_worker_headers(worker_user_id)
    return get_success_data(_api.complete_item(item_id, headers))


def dispatch_ack_complete_item(item_id):
    """Drive a QUEUED item all the way to COMPLETED:
    dispatch -> (notification SENT) -> acknowledge -> complete.
    Returns the COMPLETED item dict."""
    item = get_success_data(_api.get_fulfillment_item(item_id, _PO))
    dispatch_item(item_id, item["version"])
    notif = get_item_notification(item_id)
    acknowledge_notification(notif["id"])
    complete_item(item_id)
    return get_success_data(_api.get_fulfillment_item(item_id, _PO))


def dispatch_item_to_dispatched(item_id):
    """Dispatch a QUEUED item so it becomes DISPATCHED with a SENT notification.
    Returns (item, notification)."""
    item = get_success_data(_api.get_fulfillment_item(item_id, _PO))
    dispatch_item(item_id, item["version"])
    notif = get_item_notification(item_id)
    item = get_success_data(_api.get_fulfillment_item(item_id, _PO))
    return item, notif


# --------------------------------------------------------------------------
# Tier 4: deletion / legal-hold scenarios
# --------------------------------------------------------------------------
def create_deletion_fulfilling_with_hold(hold_categories=("IDENTITY",),
                                          finding_category="IDENTITY",
                                          record_count=1,
                                          intake_user_id="intake-A",
                                          officer_user_id="officer-B"):
    """A DELETION request fanned out into FULFILLING where the single ERASE item's
    category is frozen by an ACTIVE legal hold, so the item is created BLOCKED.

    Returns dict(controller, subject, processor, hold, request, finding, item).
    """
    controller, subject, processor = setup_registry("GDPR", with_processor=True)
    hold = create_legal_hold(controller["id"], subject["id"], data_categories=hold_categories)
    request = create_request(controller["id"], subject["id"], request_type="DELETION")
    verify_request(request["id"], intake_user_id=intake_user_id)
    finding = add_confirmed_finding(
        request["id"], processor["id"],
        data_category=finding_category, record_count=record_count,
    )
    complete_discovery(request["id"])
    req = get_success_data(_api.get_dsar_request(request["id"], _PO))
    dispatch_fulfillment(req["id"], req["version"], officer_user_id=officer_user_id)
    item = get_item_for_finding(finding["id"])
    return {
        "controller": controller,
        "subject": subject,
        "processor": processor,
        "hold": hold,
        "request": get_success_data(_api.get_dsar_request(request["id"], _PO)),
        "finding": finding,
        "item": item,
    }
