"""Signed authorizations: recording, superseding, curing and revoking (PRD 3.2)."""

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from events import append_event
from security import ALL_ROLES, actor, own_authorization

bp = Blueprint("authorizations", __name__)

AUTH_INPUTS = ["signed_at", "expires_at", "scope_categories",
               "designated_recipient_endpoint", "signature_verified"]


def _read_auth_payload(body, require_range_check):
    """The five mandatory authorization inputs plus the three optional ones."""
    raw_signed, signed = v.req_datetime(body, "signed_at")
    raw_expires, expires = v.req_datetime(body, "expires_at")
    scope = v.req_enum_array(body, "scope_categories", store.CATEGORIES)
    endpoint = v.req_str(body, "designated_recipient_endpoint", max_len=200)
    verified = v.req_bool(body, "signature_verified")
    sensitive = v.opt_enum_array(body, "sensitive_categories_authorized",
                                 store.CATEGORIES, default=[])
    ack = v.opt_bool(body, "part2_redisclosure_prohibition_ack", False)
    if require_range_check and expires <= signed:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    return {
        "signed_at": raw_signed, "_signed": signed,
        "expires_at": raw_expires, "_expires": expires,
        "scope_categories": scope,
        "designated_recipient_endpoint": endpoint,
        "signature_verified": verified,
        "sensitive_categories_authorized": sensitive,
        "part2_redisclosure_prohibition_ack": ack,
    }


def _classify(payload):
    """The computed initial status and its defect reason codes."""
    reasons = []
    if not payload["signature_verified"]:
        reasons.append("SIGNATURE_UNVERIFIED")
    if len(payload["scope_categories"]) == 0:
        reasons.append("SCOPE_EMPTY")
    lapsed = payload["_expires"] <= store.now()
    if reasons or lapsed:
        return "DEFECTIVE", reasons
    return "VALID", []


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: adjacency is not a collision."""
    return a_start < b_end and b_start < a_end


@bp.post("/roi/authorizations")
def create_authorization():
    uid, role = actor(["IntakeSpecialist", "PrivacyOfficer"])
    body = v.body()

    patient_id = v.req_id(body, "patient_id")
    requester_id = v.req_id(body, "requester_id")
    expected_patient_version = v.req_int(body, "expected_patient_version")
    payload = _read_auth_payload(body, require_range_check=True)
    supersedes = v.opt_id(body, "supersedes_authorization_id")

    patient = store.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    if requester_id not in store.requesters:
        raise ApiError("ERR_REQUESTER_NOT_FOUND")
    predecessor = None
    if supersedes is not None:
        predecessor = store.authorizations.get(supersedes)
        if predecessor is None:
            raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")

    if expected_patient_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")

    # priority 30 — coverage-window collision, the named predecessor excepted
    new_scope = set(payload["scope_categories"])
    for other in store.ordered(list(store.authorizations.values())):
        if other["patient_id"] != patient_id or other["requester_id"] != requester_id:
            continue
        if other["status"] not in ("VALID", "DEFECTIVE"):
            continue
        if supersedes is not None and other["id"] == supersedes:
            continue
        if not new_scope.intersection(other["scope_categories"]):
            continue
        other_start = store.parse_dt(other["signed_at"])
        other_end = store.parse_dt(other["expires_at"])
        if _overlaps(payload["_signed"], payload["_expires"], other_start, other_end):
            raise ApiError("ERR_AUTHORIZATION_WINDOW_OVERLAP")

    auth = store.common_fields()
    auth["patient_id"] = patient_id
    auth["requester_id"] = requester_id
    auth["supersedes_authorization_id"] = supersedes
    auth["signed_at"] = payload["signed_at"]
    auth["expires_at"] = payload["expires_at"]
    auth["scope_categories"] = payload["scope_categories"]
    auth["sensitive_categories_authorized"] = payload["sensitive_categories_authorized"]
    auth["part2_redisclosure_prohibition_ack"] = payload["part2_redisclosure_prohibition_ack"]
    auth["designated_recipient_endpoint"] = payload["designated_recipient_endpoint"]
    auth["signature_verified"] = payload["signature_verified"]
    auth["status"], auth["defect_reasons"] = _classify(payload)
    auth["revoked_at"] = None
    store.authorizations[auth["id"]] = auth

    if predecessor is not None and predecessor["patient_id"] == patient_id \
            and predecessor["status"] in ("VALID", "DEFECTIVE"):
        predecessor["status"] = "SUPERSEDED"
        store.touch(predecessor)

    store.touch(patient)
    return created(store.public(auth))


@bp.get("/roi/authorizations/<id>")
def read_authorization(id):
    uid, role = actor(ALL_ROLES)
    auth = store.authorizations.get(id)
    own_authorization(role, uid, auth)
    if auth is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    return ok(store.public(auth))


@bp.get("/roi/authorizations")
def list_authorizations():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.authorizations.values()))
    if role == "Requester":
        rows = [r for r in rows if r["requester_id"] == uid]
    for field in ("patient_id", "requester_id", "supersedes_authorization_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ------------------------------------------------------------------ cure
def _close_tolling(req):
    """AUTH_DEFECT_PENDING -> INTAKE_REVIEW: close the interval under the cap."""
    opened = store.parse_dt(req.get("defect_opened_at"))
    if opened is not None:
        elapsed = int((store.now() - opened).total_seconds())
        if elapsed < 0:
            elapsed = 0
        remaining = store.MAX_TOLL_SECONDS - req.get("tolled_seconds", 0)
        if remaining < 0:
            remaining = 0
        req["tolled_seconds"] = req.get("tolled_seconds", 0) + min(elapsed, remaining)
    req["defect_opened_at"] = None


@bp.post("/roi/authorizations/<id>/cure")
def cure_authorization(id):
    uid, role = actor(["IntakeSpecialist"])
    body = v.body()
    payload = _read_auth_payload(body, require_range_check=False)

    auth = store.authorizations.get(id)
    if auth is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    if auth["status"] != "DEFECTIVE":
        raise ApiError("ERR_AUTHORIZATION_STATE_INVALID")

    status, _reasons = _classify(payload)
    if status != "VALID":
        raise ApiError("ERR_AUTHORIZATION_STATE_INVALID")

    auth["signed_at"] = payload["signed_at"]
    auth["expires_at"] = payload["expires_at"]
    auth["scope_categories"] = payload["scope_categories"]
    auth["designated_recipient_endpoint"] = payload["designated_recipient_endpoint"]
    auth["signature_verified"] = payload["signature_verified"]
    auth["sensitive_categories_authorized"] = payload["sensitive_categories_authorized"]
    auth["part2_redisclosure_prohibition_ack"] = payload["part2_redisclosure_prohibition_ack"]
    auth["status"] = "VALID"
    auth["defect_reasons"] = []
    store.touch(auth)

    for req in store.ordered(list(store.requests.values())):
        if req.get("authorization_id") != auth["id"]:
            continue
        if req["fulfillment_status"] != "AUTH_DEFECT_PENDING":
            continue
        _close_tolling(req)
        req["fulfillment_status"] = "INTAKE_REVIEW"
        calc.refresh_statutory_due_at(req)
        calc.refresh_penalties(req, uid)
        store.touch(req)

    return ok(store.public(auth))


# ------------------------------------------------------------------ revoke
REVOKE_CASCADE_ORIGINS = (
    "INTAKE_REVIEW", "COMPILATION", "SENSITIVE_REVIEW", "REDACTION", "RELEASE_READY",
)


@bp.post("/roi/authorizations/<id>/revoke")
def revoke_authorization(id):
    uid, role = actor(["PrivacyOfficer", "Requester"])
    auth = store.authorizations.get(id)
    own_authorization(role, uid, auth)

    body = v.body()
    v.req_str(body, "revocation_reason", max_len=500)

    if auth is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    if auth["status"] not in ("VALID", "DEFECTIVE"):
        raise ApiError("ERR_AUTHORIZATION_STATE_INVALID")

    auth["status"] = "REVOKED"
    auth["revoked_at"] = store.fmt(store.now())
    store.touch(auth)

    touched_facilities = []
    for req in store.ordered(list(store.requests.values())):
        if req.get("authorization_id") != auth["id"]:
            continue
        if req["fulfillment_status"] not in REVOKE_CASCADE_ORIGINS:
            continue

        req["defect_opened_at"] = store.fmt(store.now())
        req["release_reviewer_user_id"] = None
        for seg in calc.segments_of(req["id"]):
            dirty = False
            if seg["sensitivity_status"] in ("AUTHORIZED_INCLUDE", "WITHHELD"):
                seg["sensitivity_status"] = "SEGREGATED_PENDING_REVIEW"
                dirty = True
            if seg["redaction_status"] in ("OPEN", "APPLIED", "APPROVED", "REWORK"):
                seg["redaction_status"] = "OPEN"
                seg["redaction_approved_by_user_id"] = None
                dirty = True
            if dirty:
                store.touch(seg)

        req["fulfillment_status"] = "AUTH_DEFECT_PENDING"
        calc.refresh_page_ledger(req)
        calc.refresh_statutory_due_at(req)

        voided = False
        for inv in calc.invoices_of(req["id"]):
            if inv["status"] in ("DRAFT", "ISSUED"):
                calc.void_invoice(inv, "AUTHORIZATION_REVOKED")
                voided = True
        if voided:
            req["billing_status"] = "PENDING_INVOICE"
        calc.refresh_facility_money(req["facility_id"])
        if req["facility_id"] not in touched_facilities:
            touched_facilities.append(req["facility_id"])

        append_event(req["id"], "AUTHORIZATION_REVOKED", uid,
                     days_late=calc.turnaround(req)["days_late_strict"],
                     detail="authorization_id=%s" % auth["id"])
        store.touch(req)

    for facility_id in touched_facilities:
        calc.refresh_facility_penalty(facility_id)

    return ok(store.public(auth))
