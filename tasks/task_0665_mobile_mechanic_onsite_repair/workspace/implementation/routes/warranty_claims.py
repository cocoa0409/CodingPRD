"""Warranty-claim endpoints: fetch, list, request-info, supply-info, approve, deny."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, parse_pagination, paginate
from services import models, validate, scheduling

bp = Blueprint("warranty_claims", __name__)


def _sorted(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def _get_claim(wid):
    w = db.store.warranty_claims.get(wid)
    if w is None:
        raise errors.not_found("Warranty claim not found.")
    return w


@bp.route("/warranty-claims/<wid>", methods=["GET"])
def get_claim(wid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Dispatcher"})
    w = _get_claim(wid)
    if role == "Customer":
        sr = db.store.service_requests.get(w["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own claims.")
    return response.success(models.serialize(w), 200)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    limit, offset = parse_pagination()
    callback_filter = request.args.get("callback_visit_id")
    sr_filter = request.args.get("service_request_id")
    items = list(db.store.warranty_claims.values())
    if callback_filter is not None:
        items = [w for w in items if w.get("callback_visit_id") == callback_filter]
    if sr_filter is not None:
        items = [w for w in items if w["service_request_id"] == sr_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(w) for w in page], limit, offset, total)


@bp.route("/warranty-claims/<wid>/request-info", methods=["POST"])
def request_info(wid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    w = _get_claim(wid)
    if w["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    w["status"] = "INFO_REQUESTED"
    models.touch(w, db.store)
    return response.success(models.serialize(w), 200)


@bp.route("/warranty-claims/<wid>/supply-info", methods=["POST"])
def supply_info(wid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    w = _get_claim(wid)
    sr = db.store.service_requests.get(w["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only supply info on its own claims.")
    if w["status"] != "INFO_REQUESTED":
        raise errors.invalid_state("Claim is not INFO_REQUESTED.")
    w["status"] = "UNDER_REVIEW"
    models.touch(w, db.store)
    return response.success(models.serialize(w), 200)


@bp.route("/warranty-claims/<wid>/approve", methods=["POST"])
def approve_claim(wid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    w = _get_claim(wid)
    sr = db.store.service_requests.get(w["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")

    body = validate.get_body()
    # body FK existence (priority 3): mechanic_id
    mechanic_id = body.get("mechanic_id")
    if not isinstance(mechanic_id, str) or db.store.mechanics.get(mechanic_id) is None:
        raise errors.not_found("mechanic_id does not resolve.")
    mechanic = db.store.mechanics[mechanic_id]

    # state precondition (priority 5): claim UNDER_REVIEW and referenced request COMPLETED
    if w["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    if sr["status"] != "COMPLETED":
        raise errors.invalid_state("Referenced service request is not COMPLETED.")

    # structural validation (priority 6)
    if "scheduled_start_utc" not in body or "scheduled_end_utc" not in body:
        raise errors.invalid_request("scheduled_start_utc and scheduled_end_utc are required.")
    start = validate.parse_dt(body["scheduled_start_utc"])
    end = validate.parse_dt(body["scheduled_end_utc"])
    if not (end > start):
        raise errors.invalid_request("scheduled_end_utc must be strictly after scheduled_start_utc.")

    # buffered callback slot conflict (priority 10)
    if scheduling.buffered_callback_conflict(mechanic_id, start, end):
        raise errors.callback_slot_conflict()

    # warranty window (priority 11): filed within WARRANTY_WINDOW_DAYS of completion.
    # The completion instant is the request's updated_at at COMPLETED; we compare the
    # claim's filed_at_utc against that completion using the logical clock semantics.
    completion = db._parse_iso(sr["updated_at"])
    filed = db._parse_iso(w["filed_at_utc"])
    window = timedelta(days=db.WARRANTY_WINDOW_DAYS)
    if filed - completion > window:
        raise errors.warranty_window_expired()

    # create free callback JobVisit (SCHEDULED, ON_SITE) for the same mechanic/zone
    visit = models.make_job_visit(db.store, sr["id"], mechanic_id,
                                  body["scheduled_start_utc"], body["scheduled_end_utc"],
                                  "ON_SITE")
    db.store.job_visits[visit["id"]] = visit

    w["callback_visit_id"] = visit["id"]
    w["status"] = "APPROVED"
    models.touch(w, db.store)
    return response.success(models.serialize(w), 200)


@bp.route("/warranty-claims/<wid>/deny", methods=["POST"])
def deny_claim(wid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    w = _get_claim(wid)
    if w["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    w["status"] = "DENIED"
    models.touch(w, db.store)
    return response.success(models.serialize(w), 200)
