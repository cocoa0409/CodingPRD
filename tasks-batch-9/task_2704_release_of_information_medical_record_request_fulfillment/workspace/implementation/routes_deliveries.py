"""Deliveries: channel safety, the designated recipient and the attempt ceiling."""

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from events import append_event
from security import ALL_ROLES, actor, own_request

bp = Blueprint("deliveries", __name__)

FAX_FORBIDDEN_CATEGORIES = ("SUD_PART2", "HIV", "GENETIC")
LIVE_DELIVERY_STATES = ("PENDING", "SENT", "FAILED")


def _get_delivery(id):
    dlv = store.deliveries.get(id)
    if dlv is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND")
    return dlv


@bp.post("/roi/deliveries")
def create_delivery():
    uid, role = actor(["ReleaseReviewer"])
    body = v.body()

    request_id = v.req_id(body, "request_id")
    delivery_format = v.req_enum(body, "delivery_format", store.DELIVERY_FORMATS)
    recipient_endpoint = v.req_str(body, "recipient_endpoint", max_len=200)
    encryption = v.req_enum(body, "encryption", ["TLS", "AES256_ZIP", "NONE"])
    patient_direction_ack = v.opt_bool(body, "patient_direction_ack", False)

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    # the format is a field constraint measured against the request it serves
    if delivery_format != req["delivery_format"]:
        v.bad()

    # priority 19
    if req["fulfillment_status"] != "RELEASED":
        raise ApiError("ERR_REQUEST_NOT_RELEASE_READY")

    # priority 23 — an unsecured channel needs the patient's own direction
    if delivery_format == "UNENCRYPTED_EMAIL" or encryption == "NONE":
        directed = (req["access_basis"] == "PATIENT_RIGHT_OF_ACCESS"
                    and patient_direction_ack)
        if not directed:
            raise ApiError("ERR_UNENCRYPTED_DELIVERY_NOT_DIRECTED")

    # priority 24 — three categories may never ride a fax
    if delivery_format == "FAX":
        for seg in calc.segments_of(req["id"]):
            if seg["retrieval_status"] != "RETRIEVED":
                continue
            if seg["sensitivity_status"] != "AUTHORIZED_INCLUDE":
                continue
            if seg["category"] in FAX_FORBIDDEN_CATEGORIES:
                raise ApiError("ERR_FAX_NOT_PERMITTED")

    # priority 25 — the third party may only be reached where it was designated
    if req["access_basis"] == "THIRD_PARTY_AUTHORIZATION":
        auth = calc.authorization_of(req)
        designated = auth["designated_recipient_endpoint"] if auth else None
        if recipient_endpoint != designated:
            raise ApiError("ERR_RECIPIENT_NOT_DESIGNATED")

    # priority 42 — exactly one live transmission per request
    for other in calc.deliveries_of(req["id"]):
        if other["status"] in LIVE_DELIVERY_STATES:
            raise ApiError("ERR_DELIVERY_ALREADY_EXISTS")

    dlv = store.common_fields()
    dlv["request_id"] = req["id"]
    dlv["delivery_format"] = delivery_format
    dlv["recipient_endpoint"] = recipient_endpoint
    dlv["encryption"] = encryption
    dlv["patient_direction_ack"] = patient_direction_ack
    dlv["status"] = "PENDING"
    dlv["attempt_count"] = 0
    dlv["sent_at"] = None
    dlv["confirmed_at"] = None
    dlv["failure_reason"] = None
    store.deliveries[dlv["id"]] = dlv
    return created(store.public(dlv))


@bp.get("/roi/deliveries/<id>")
def read_delivery(id):
    uid, role = actor(ALL_ROLES)
    dlv = store.deliveries.get(id)
    own_request(role, uid, store.requests.get(dlv["request_id"]) if dlv else None)
    if dlv is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND")
    return ok(store.public(dlv))


@bp.get("/roi/deliveries")
def list_deliveries():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.deliveries.values()))
    if role == "Requester":
        rows = [r for r in rows
                if (store.requests.get(r["request_id"]) or {}).get("requester_id") == uid]
    for field in ("request_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ one attempt
@bp.post("/roi/deliveries/<id>/transmission")
def record_transmission(id):
    uid, role = actor(["ReleaseReviewer"])
    body = v.body()
    outcome = v.req_enum(body, "outcome", ["SENT", "FAILED"])
    failure_reason = v.opt_str(body, "failure_reason", max_len=500)
    if outcome == "FAILED" and failure_reason is None:
        v.bad()

    dlv = _get_delivery(id)
    # priority 14 — only a PENDING or FAILED delivery may be attempted
    if dlv["status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_DELIVERY_STATE_INVALID")

    req = store.requests.get(dlv["request_id"])
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    if outcome == "SENT" and req["fulfillment_status"] != "RELEASED":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    # priority 41 — the ceiling is measured before the attempt is counted
    if dlv["attempt_count"] >= store.MAX_DELIVERY_ATTEMPTS:
        raise ApiError("ERR_DELIVERY_ATTEMPT_LIMIT")

    dlv["attempt_count"] = dlv["attempt_count"] + 1
    if outcome == "SENT":
        dlv["status"] = "SENT"
        dlv["sent_at"] = store.fmt(store.now())
    else:
        dlv["status"] = "FAILED"
        dlv["failure_reason"] = failure_reason
        append_event(req["id"], "DELIVERY_FAILED", uid,
                     detail="attempt_count=%d" % dlv["attempt_count"])
    store.touch(dlv)
    return ok(store.public(dlv))


# ============================================================ receipt or return
@bp.post("/roi/deliveries/<id>/confirm")
def confirm_delivery(id):
    uid, role = actor(["ReleaseReviewer", "Requester"])
    dlv = store.deliveries.get(id)
    own_request(role, uid, store.requests.get(dlv["request_id"]) if dlv else None)

    body = v.body()
    outcome = v.req_enum(body, "outcome", ["CONFIRMED", "RETURNED"])

    if dlv is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND")
    # priority 14 — receipt is only meaningful from SENT
    if dlv["status"] != "SENT":
        raise ApiError("ERR_DELIVERY_STATE_INVALID")

    req = store.requests.get(dlv["request_id"])
    confirmed_at = store.now()
    dlv["confirmed_at"] = store.fmt(confirmed_at)
    dlv["status"] = outcome
    store.touch(dlv)

    if outcome == "CONFIRMED":
        # a confirmed receipt is the completed disclosure: the request closes
        if req is not None and req["fulfillment_status"] == "RELEASED":
            req["fulfillment_status"] = "CLOSED"
            req["closed_at"] = store.fmt(confirmed_at)
            calc.refresh_facility_penalty(req["facility_id"])
            store.touch(req)
    else:
        # a returned envelope is not a disclosure: the request stays RELEASED
        if req is not None:
            append_event(req["id"], "DELIVERY_FAILED", uid,
                         detail="delivery_returned=true")
    return ok(store.public(dlv))
