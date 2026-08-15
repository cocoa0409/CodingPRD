"""Service referrals."""
from datetime import timedelta

from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_CONCERN_NOT_FLAGGED)
from validate import (Field, validate_payload, parse_pagination, sort_items,
                      parse_bool_filter)
import calc
import serialize

bp = Blueprint("referrals", __name__)

PC = ["ProgramCoordinator"]
PC_QR = ["ProgramCoordinator", "QualityReviewer"]
SERVICE_TYPES = {"MEALS", "TRANSPORT", "HOME_HEALTH", "ADULT_DAY",
                 "CAREGIVER_SUPPORT", "BEHAVIORAL_HEALTH"}
SLA_HOURS = {"URGENT": 24, "STANDARD": 72, "ROUTINE": 168}


def get_referral_or_404(rid):
    r = store.referrals.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "Service referral not found")
    return r


@bp.route("/api/service-referrals", methods=["GET"])
@endpoint(PC_QR)
def list_referrals(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.referrals.values())
    for fname in ("participant_id", "escalation_id", "source_call_log_id", "status"):
        if fname in request.args:
            items = [r for r in items if r.get(fname) == request.args[fname]]
    ov = parse_bool_filter(request.args, "overdue")
    if ov is not None:
        items = [r for r in items if calc.referral_overdue(r) == ov]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.referral(r) for r in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/service-referrals", methods=["POST"])
@endpoint(PC_QR)
def create_referral(uid, role):
    data = validate_payload(get_body(), [
        Field("participant_id", "str", required=True),
        Field("service_type", "enum", required=True, enum=SERVICE_TYPES),
        Field("priority", "enum", enum={"URGENT", "STANDARD", "ROUTINE"},
              default="STANDARD"),
        Field("source_call_log_id", "str"),
        Field("notes", "str"),
    ])
    p = store.participants.get(data["participant_id"])
    if not p:
        raise_err(ERR_NOT_FOUND, "Participant not found")
    if data.get("source_call_log_id") is not None:
        if data["source_call_log_id"] not in store.logs:
            raise_err(ERR_NOT_FOUND, "Source call log not found")
    r = new_entity()
    r.update({
        "participant_id": data["participant_id"],
        "source_call_log_id": data.get("source_call_log_id"),
        "escalation_id": None,
        "service_type": data["service_type"],
        "priority": data.get("priority", "STANDARD"),
        "status": "DRAFT",
        "submitted_at": None,
        "sla_due_at": None,
        "decline_reason": None,
    })
    store.referrals[r["id"]] = r
    return ok(serialize.referral(r), 201)


@bp.route("/api/service-referrals/<rid>", methods=["GET"])
@endpoint(PC_QR)
def get_referral(rid, uid, role):
    return ok(serialize.referral(get_referral_or_404(rid)))


@bp.route("/api/service-referrals/<rid>/submit", methods=["POST"])
@endpoint(PC)
def submit_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    if r["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Referral is not DRAFT")
    if r.get("source_call_log_id"):
        lg = store.logs.get(r["source_call_log_id"])
        if not lg or not lg["concern_flag"]:
            raise_err(ERR_CONCERN_NOT_FLAGGED,
                      "Source call log is not concern-flagged")
    r["status"] = "SUBMITTED"
    r["submitted_at"] = now()
    r["sla_due_at"] = now() + timedelta(hours=SLA_HOURS[r["priority"]])
    touch(r)
    return ok(serialize.referral(r))


@bp.route("/api/service-referrals/<rid>/accept", methods=["POST"])
@endpoint(PC)
def accept_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Referral is not SUBMITTED")
    r["status"] = "ACCEPTED"
    touch(r)
    return ok(serialize.referral(r))


@bp.route("/api/service-referrals/<rid>/decline", methods=["POST"])
@endpoint(PC)
def decline_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    data = validate_payload(get_body(), [Field("reason", "str")])
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Referral is not SUBMITTED")
    r["status"] = "DECLINED"
    r["decline_reason"] = data.get("reason")
    touch(r)
    return ok(serialize.referral(r))


@bp.route("/api/service-referrals/<rid>/revise", methods=["POST"])
@endpoint(PC)
def revise_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    if r["status"] != "DECLINED":
        raise_err(ERR_INVALID_STATE, "Referral is not DECLINED")
    r["status"] = "DRAFT"
    r["decline_reason"] = None
    r["submitted_at"] = None
    r["sla_due_at"] = None
    touch(r)
    return ok(serialize.referral(r))


@bp.route("/api/service-referrals/<rid>/withdraw", methods=["POST"])
@endpoint(PC)
def withdraw_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    if r["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE, "Referral is not DRAFT or SUBMITTED")
    r["status"] = "WITHDRAWN"
    touch(r)
    return ok(serialize.referral(r))


@bp.route("/api/service-referrals/<rid>/close", methods=["POST"])
@endpoint(["QualityReviewer"])
def close_referral(rid, uid, role):
    r = get_referral_or_404(rid)
    if r["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "Referral is not ACCEPTED")
    r["status"] = "CLOSED"
    touch(r)
    return ok(serialize.referral(r))
