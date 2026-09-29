"""Request intake, the statutory clock, review passes, release and withdrawal."""

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from events import append_event, events_of
from security import ALL_ROLES, STAFF, actor, own_request

bp = Blueprint("requests", __name__)

WITHDRAW_ORIGINS = (
    "INTAKE_REVIEW", "AUTH_DEFECT_PENDING", "COMPILATION",
    "SENSITIVE_REVIEW", "REDACTION", "RELEASE_READY",
)


def _get_request(id):
    req = store.requests.get(id)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    return req


# ============================================================ intake
@bp.post("/roi/requests")
def create_request():
    uid, role = actor(["IntakeSpecialist"])
    body = v.body()

    facility_id = v.req_id(body, "facility_id")
    patient_id = v.req_id(body, "patient_id")
    requester_id = v.req_id(body, "requester_id")
    access_basis = v.req_enum(body, "access_basis", store.ACCESS_BASES)
    requested_categories = v.req_enum_array(body, "requested_categories",
                                            store.CATEGORIES, allow_empty=False)
    raw_start, start = v.req_date(body, "date_range_start")
    raw_end, end = v.req_date(body, "date_range_end")
    delivery_format = v.req_enum(body, "delivery_format", store.DELIVERY_FORMATS)
    authorization_id = v.opt_id(body, "authorization_id")
    predecessor_request_id = v.opt_id(body, "predecessor_request_id")
    certification_requested = v.opt_bool(body, "certification_requested", False)

    if end < start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    facility = store.facilities.get(facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    if patient_id not in store.patients:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    requester = store.requesters.get(requester_id)
    if requester is None:
        raise ApiError("ERR_REQUESTER_NOT_FOUND")
    auth = None
    if authorization_id is not None:
        auth = store.authorizations.get(authorization_id)
        if auth is None:
            raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    if predecessor_request_id is not None and predecessor_request_id not in store.requests:
        raise ApiError("ERR_REQUEST_NOT_FOUND")

    if facility["status"] == "SUSPENDED":
        raise ApiError("ERR_FACILITY_SUSPENDED")

    # priority 26 — the requesting patient must be the subject
    if requester["requester_type"] == "PATIENT" and requester.get("patient_id") != patient_id:
        raise ApiError("ERR_PATIENT_IDENTITY_MISMATCH")

    # priority 27 — only the patient or its representative may claim the right of access
    if access_basis == "PATIENT_RIGHT_OF_ACCESS" \
            and requester["requester_type"] not in ("PATIENT", "PERSONAL_REPRESENTATIVE"):
        raise ApiError("ERR_ACCESS_BASIS_REQUESTER_MISMATCH")

    # priority 28 — the access basis and the authorization must agree
    if access_basis == "THIRD_PARTY_AUTHORIZATION" and auth is None:
        raise ApiError("ERR_AUTHORIZATION_REQUIRED")
    if access_basis == "PATIENT_RIGHT_OF_ACCESS" and auth is not None:
        raise ApiError("ERR_AUTHORIZATION_REQUIRED")
    if auth is not None and (auth["patient_id"] != patient_id
                            or auth["requester_id"] != requester_id):
        raise ApiError("ERR_AUTHORIZATION_REQUIRED")

    # priority 35 — no duplicate in-flight work
    for other in store.ordered(list(store.requests.values())):
        if other["fulfillment_status"] in ("CLOSED", "CANCELLED"):
            continue
        if predecessor_request_id is not None and other["id"] == predecessor_request_id:
            continue
        if (other["facility_id"] == facility_id and other["patient_id"] == patient_id
                and other["requester_id"] == requester_id
                and other["date_range_start"] == raw_start
                and other["date_range_end"] == raw_end):
            raise ApiError("ERR_DUPLICATE_INFLIGHT_REQUEST")

    req = store.common_fields()
    req["facility_id"] = facility_id
    req["patient_id"] = patient_id
    req["requester_id"] = requester_id
    req["authorization_id"] = authorization_id
    req["predecessor_request_id"] = predecessor_request_id
    req["access_basis"] = access_basis
    req["requested_categories"] = requested_categories
    req["date_range_start"] = raw_start
    req["date_range_end"] = raw_end
    req["delivery_format"] = delivery_format
    req["certification_requested"] = certification_requested
    req["received_at"] = store.fmt(store.now())
    req["intake_user_id"] = uid
    req["release_reviewer_user_id"] = None
    req["fulfillment_status"] = "INTAKE_REVIEW"
    req["billing_status"] = "PENDING_INVOICE"
    req["extension_applied"] = False
    req["extension_noticed_at"] = None
    req["defect_opened_at"] = None
    req["tolled_seconds"] = 0
    req["statutory_due_at"] = None
    req["page_count_total"] = 0
    req["billable_page_count"] = 0
    req["withheld_page_count"] = 0
    req["redacted_page_count_total"] = 0
    req["penalty_exposure_cents"] = 0
    req["safe_harbor_penalty_cents"] = 0
    req["amendment_notice_required"] = False
    req["released_at"] = None
    req["closed_at"] = None
    store.requests[req["id"]] = req
    calc.refresh_statutory_due_at(req)
    return created(store.public(req))


# ============================================================ reads
@bp.get("/roi/requests/<id>")
def read_request(id):
    uid, role = actor(ALL_ROLES)
    req = store.requests.get(id)
    own_request(role, uid, req)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    return ok(store.public(req))


@bp.get("/roi/requests")
def list_requests():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.requests.values()))
    if role == "Requester":
        rows = [r for r in rows if r["requester_id"] == uid]
    for field in ("facility_id", "patient_id", "requester_id", "authorization_id",
                  "predecessor_request_id", "fulfillment_status", "billing_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


@bp.get("/roi/requests/<id>/turnaround")
def read_turnaround(id):
    uid, role = actor(ALL_ROLES)
    req = store.requests.get(id)
    own_request(role, uid, req)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    return ok(calc.turnaround(req))


@bp.get("/roi/requests/<id>/compliance-events")
def list_compliance_events(id):
    actor(STAFF)
    limit, offset = v.paging()
    req = _get_request(id)
    rows = events_of(req["id"])
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ intake decision
@bp.post("/roi/requests/<id>/intake-decision")
def intake_decision(id):
    uid, role = actor(["IntakeSpecialist"])
    body = v.body()
    decision = v.req_enum(body, "decision", ["ACCEPT", "DEFECT"])
    if v.present(body, "defect_reasons"):
        if not isinstance(body["defect_reasons"], list):
            v.bad()
        for item in body["defect_reasons"]:
            if not isinstance(item, str):
                v.bad()

    req = _get_request(id)
    if req["fulfillment_status"] != "INTAKE_REVIEW":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    facility = calc.facility_of(req)
    auth = calc.authorization_of(req)

    if decision == "ACCEPT":
        if facility is not None and facility["status"] == "SUSPENDED":
            raise ApiError("ERR_FACILITY_SUSPENDED")
        if req["access_basis"] == "THIRD_PARTY_AUTHORIZATION":
            if auth is None or auth["status"] != "VALID":
                raise ApiError("ERR_AUTHORIZATION_NOT_VALID")
            if store.parse_dt(auth["expires_at"]) <= store.now():
                raise ApiError("ERR_AUTHORIZATION_EXPIRED")
        else:
            if req.get("authorization_id") is not None:
                raise ApiError("ERR_AUTHORIZATION_REQUIRED")
        req["fulfillment_status"] = "COMPILATION"
        calc.refresh_statutory_due_at(req)
        calc.refresh_penalties(req, uid)
    else:
        if req["access_basis"] != "THIRD_PARTY_AUTHORIZATION":
            raise ApiError("ERR_AUTHORIZATION_REQUIRED")
        if auth is None or auth["status"] != "DEFECTIVE":
            raise ApiError("ERR_AUTHORIZATION_STATE_INVALID")
        req["fulfillment_status"] = "AUTH_DEFECT_PENDING"
        req["defect_opened_at"] = store.fmt(store.now())
        calc.refresh_statutory_due_at(req)

    store.touch(req)
    return ok(store.public(req))


# ============================================================ statutory extension
@bp.post("/roi/requests/<id>/extension")
def notice_extension(id):
    uid, role = actor(["IntakeSpecialist"])
    body = v.body()
    v.req_str(body, "notice_note", max_len=500)

    req = _get_request(id)
    if req["fulfillment_status"] in store.TERMINAL_FULFILLMENT:
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    rule = calc.rule_of_request(req)
    due_at = store.parse_dt(req.get("statutory_due_at"))
    if req.get("extension_applied"):
        raise ApiError("ERR_EXTENSION_NOT_AVAILABLE")
    if rule is None or rule["extension_days"] == 0:
        raise ApiError("ERR_EXTENSION_NOT_AVAILABLE")
    if due_at is not None and store.now() > due_at:
        raise ApiError("ERR_EXTENSION_NOT_AVAILABLE")

    req["extension_applied"] = True
    req["extension_noticed_at"] = store.fmt(store.now())
    calc.refresh_statutory_due_at(req)
    calc.refresh_penalties(req, uid)
    store.touch(req)
    return ok(store.public(req))


# ============================================================ compilation finished
@bp.post("/roi/requests/<id>/complete-compilation")
def complete_compilation(id):
    uid, role = actor(["RecordsAnalyst"])
    v.body()

    req = _get_request(id)
    if req["fulfillment_status"] != "COMPILATION":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    segments = calc.segments_of(req["id"])
    if len(segments) == 0:
        raise ApiError("ERR_SEGMENTS_PENDING")
    if any(s["retrieval_status"] == "PENDING" for s in segments):
        raise ApiError("ERR_SEGMENTS_PENDING")

    req["fulfillment_status"] = "SENSITIVE_REVIEW"
    calc.refresh_page_ledger(req)
    calc.refresh_statutory_due_at(req)
    calc.refresh_penalties(req, uid)
    store.touch(req)
    return ok(store.public(req))


# ============================================================ sensitive review
def _read_decisions(body):
    raw = body.get("segment_decisions")
    if raw is None or not isinstance(raw, list):
        v.bad()
    decisions = []
    for entry in raw:
        if not isinstance(entry, dict):
            v.bad()
        item = {
            "record_segment_id": v.req_id(entry, "record_segment_id"),
            "decision": v.req_enum(entry, "decision", ["INCLUDE", "WITHHOLD"]),
            "redaction_required": v.opt_bool(entry, "redaction_required", False),
            "note": v.opt_str(entry, "note", max_len=500),
        }
        decisions.append(item)
    return decisions


@bp.post("/roi/requests/<id>/sensitive-review")
def sensitive_review(id):
    uid, role = actor(["ReleaseReviewer"])
    body = v.body()
    decisions = _read_decisions(body)

    req = _get_request(id)

    # priority 7 — every named segment must exist and belong to this request
    for item in decisions:
        seg = store.segments.get(item["record_segment_id"])
        if seg is None or seg["request_id"] != req["id"]:
            raise ApiError("ERR_SEGMENT_NOT_FOUND")
        item["_segment"] = seg

    if req["fulfillment_status"] != "SENSITIVE_REVIEW":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    auth = calc.authorization_of(req)
    if req["access_basis"] == "THIRD_PARTY_AUTHORIZATION" and auth is not None:
        if store.parse_dt(auth["expires_at"]) <= store.now():
            raise ApiError("ERR_AUTHORIZATION_EXPIRED")

    includes = [d for d in decisions if d["decision"] == "INCLUDE"]

    # priority 20 — psychotherapy notes never leave, under any basis
    for item in includes:
        if item["_segment"]["category"] == "PSYCHOTHERAPY_NOTES":
            raise ApiError("ERR_PSYCHOTHERAPY_NOTES_NOT_RELEASABLE")

    # priority 21 — the category must be inside the authorization's sensitive set
    if req["access_basis"] == "THIRD_PARTY_AUTHORIZATION":
        authorized = auth["sensitive_categories_authorized"] if auth else []
        for item in includes:
            if item["_segment"]["category"] not in authorized:
                raise ApiError("ERR_SENSITIVE_CATEGORY_NOT_AUTHORIZED")

        # priority 22 — Part 2 redisclosure acknowledgement
        for item in includes:
            if item["_segment"]["category"] == "SUD_PART2" \
                    and not (auth and auth["part2_redisclosure_prohibition_ack"]):
                raise ApiError("ERR_PART2_ACK_MISSING")

    # priority 38 — the pass is all-or-nothing on completeness
    seen = []
    for item in decisions:
        seg = item["_segment"]
        if seg["id"] in seen:
            raise ApiError("ERR_SEGREGATION_REVIEW_INCOMPLETE")
        seen.append(seg["id"])
        if seg["sensitivity_status"] != "SEGREGATED_PENDING_REVIEW":
            raise ApiError("ERR_SEGREGATION_REVIEW_INCOMPLETE")
    for seg in calc.segments_of(req["id"]):
        if seg["sensitivity_status"] == "SEGREGATED_PENDING_REVIEW" and seg["id"] not in seen:
            raise ApiError("ERR_SEGREGATION_REVIEW_INCOMPLETE")

    opened_redaction = False
    for item in decisions:
        seg = item["_segment"]
        if item["decision"] == "INCLUDE":
            seg["sensitivity_status"] = "AUTHORIZED_INCLUDE"
            if item["redaction_required"]:
                seg["redaction_status"] = "OPEN"
                opened_redaction = True
        else:
            seg["sensitivity_status"] = "WITHHELD"
            append_event(req["id"], "SENSITIVE_WITHHOLD", uid,
                         detail="segment_category=%s" % seg["category"])
        store.touch(seg)

    if opened_redaction:
        req["fulfillment_status"] = "REDACTION"
    else:
        calc.enter_release_ready(req)
    calc.refresh_page_ledger(req)
    calc.refresh_statutory_due_at(req)
    store.touch(req)
    return ok(store.public(req))


# ============================================================ release
@bp.post("/roi/requests/<id>/release")
def release_request(id):
    uid, role = actor(["ReleaseReviewer"])
    body = v.body()
    v.opt_str(body, "release_note", max_len=500)

    req = _get_request(id)

    # priority 9 — the reviewer may not be the intake specialist
    if uid == req.get("intake_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if req["fulfillment_status"] != "RELEASE_READY":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    if calc.redactions_open(req["id"]):
        raise ApiError("ERR_REDACTION_NOT_APPROVED")
    if req["billing_status"] in ("PENDING_INVOICE", "INVOICED"):
        raise ApiError("ERR_INVOICE_UNSETTLED")

    released_at = store.now()
    req["fulfillment_status"] = "RELEASED"
    req["released_at"] = store.fmt(released_at)
    req["release_reviewer_user_id"] = uid
    calc.refresh_statutory_due_at(req)
    calc.refresh_penalties(req, uid, completion_at=released_at)
    store.touch(req)
    return ok(store.public(req))


# ============================================================ withdrawal
@bp.post("/roi/requests/<id>/withdraw")
def withdraw_request(id):
    uid, role = actor(["Requester"])
    req = store.requests.get(id)
    own_request(role, uid, req)

    body = v.body()
    v.req_str(body, "withdrawal_reason", max_len=500)

    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    if req["fulfillment_status"] not in WITHDRAW_ORIGINS:
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    closed_at = store.now()
    req["fulfillment_status"] = "CANCELLED"
    req["closed_at"] = store.fmt(closed_at)
    for inv in calc.invoices_of(req["id"]):
        if inv["status"] in ("DRAFT", "ISSUED"):
            calc.void_invoice(inv, "BILLING_CLERK_VOID")
    req["billing_status"] = "NOT_BILLABLE"
    calc.refresh_facility_money(req["facility_id"])
    calc.refresh_penalties(req, uid, completion_at=closed_at)
    store.touch(req)
    return ok(store.public(req))
