"""Escalation cases and welfare check requests."""
from datetime import timedelta

from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_NO_OPEN_ESCALATION,
                    ERR_ESCALATION_STEP_NOT_DUE, ERR_SEGREGATION_OF_DUTIES)
from validate import Field, validate_payload, parse_pagination, sort_items
import calc
import cascade
import serialize

bp = Blueprint("escalations", __name__)

PC = ["ProgramCoordinator"]
QR = ["QualityReviewer"]
PC_QR = ["ProgramCoordinator", "QualityReviewer"]
PC_QR_ER = ["ProgramCoordinator", "QualityReviewer", "ExternalResponder"]


def get_escalation_or_404(eid):
    e = store.escalations.get(eid)
    if not e:
        raise_err(ERR_NOT_FOUND, "Escalation not found")
    return e


def get_welfare_or_404(wid):
    w = store.welfare.get(wid)
    if not w:
        raise_err(ERR_NOT_FOUND, "Welfare check request not found")
    return w


def program_or_404():
    g = calc.sole_program()
    if not g:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return g


@bp.route("/api/escalations", methods=["GET"])
@endpoint(PC_QR)
def list_escalations(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.escalations.values())
    for fname in ("participant_id", "supersedes_escalation_id",
                  "retry_assignment_id", "stage"):
        if fname in request.args:
            items = [e for e in items if e.get(fname) == request.args[fname]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.escalation(e) for e in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/escalations", methods=["POST"])
@endpoint(PC)
def create_escalation(uid, role):
    data = validate_payload(get_body(), [
        Field("participant_id", "str", required=True),
        Field("trigger_type", "enum", required=True,
              enum={"MANUAL", "CONCERN_IMMEDIATE"}),
        Field("expected_participant_version", "int", required=True),
        Field("note", "str"),
    ])
    p = store.participants.get(data["participant_id"])
    if not p:
        raise_err(ERR_NOT_FOUND, "Participant not found")
    if data["expected_participant_version"] != p["version"]:
        raise_err(ERR_STALE_VERSION, "Stale participant version")
    g = program_or_404()
    e = cascade.open_escalation(p, data["trigger_type"], uid, g,
                                note=data.get("note"))
    return ok(serialize.escalation(e), 201)


@bp.route("/api/escalations/<eid>", methods=["GET"])
@endpoint(PC_QR)
def get_escalation(eid, uid, role):
    return ok(serialize.escalation(get_escalation_or_404(eid)))


@bp.route("/api/escalations/<eid>/advance", methods=["POST"])
@endpoint(PC)
def advance(eid, uid, role):
    e = get_escalation_or_404(eid)
    g = program_or_404()
    if e["stage"] in cascade.TERMINAL_ESCALATION:
        raise_err(ERR_NO_OPEN_ESCALATION, "Escalation is terminal")
    if e["stage"] == "STEP_3_WELFARE":
        raise_err(ERR_INVALID_STATE, "STEP_3_WELFARE cannot be advanced")
    if not cascade.advance_eligible(e, g):
        raise_err(ERR_ESCALATION_STEP_NOT_DUE,
                  "Step deadline has not passed and work precondition is unmet")
    cascade.advance_escalation(e, g)
    return ok(serialize.escalation(e))


@bp.route("/api/escalations/<eid>/record-contact-attempt", methods=["POST"])
@endpoint(PC)
def record_contact_attempt(eid, uid, role):
    e = get_escalation_or_404(eid)
    data = validate_payload(get_body(), [
        Field("contact_id", "str", required=True),
        Field("outcome", "enum", required=True, enum={"REACHED", "UNREACHABLE", "REFUSED"}),
    ])
    c = store.contacts.get(data["contact_id"])
    if not c or c["participant_id"] != e["participant_id"]:
        raise_err(ERR_NOT_FOUND, "Emergency contact not found")
    if e["stage"] in cascade.TERMINAL_ESCALATION:
        raise_err(ERR_NO_OPEN_ESCALATION, "Escalation is terminal")
    if e["stage"] != "STEP_2_CONTACT":
        raise_err(ERR_INVALID_STATE, "Contact attempts are recorded at STEP_2_CONTACT")
    e["contact_attempts"].append({
        "contact_id": c["id"],
        "outcome": data["outcome"],
        "attempted_at": now(),
    })
    touch(e)
    if data["outcome"] == "UNREACHABLE" and c["status"] == "ACTIVE":
        c["status"] = "UNREACHABLE"
        touch(c)
    return ok(serialize.escalation(e))


ALLOWED_RESOLUTIONS = {
    "STEP_1_RETRY": {"RESOLVED_OK", "RESOLVED_CONTACT_CONFIRMED", "CLOSED_FALSE_ALARM"},
    "STEP_2_CONTACT": {"RESOLVED_CONTACT_CONFIRMED", "CLOSED_FALSE_ALARM"},
    "STEP_3_WELFARE": {"CLOSED_FALSE_ALARM"},
}


@bp.route("/api/escalations/<eid>/resolve", methods=["POST"])
@endpoint(QR)
def resolve(eid, uid, role):
    e = get_escalation_or_404(eid)
    data = validate_payload(get_body(), [
        Field("resolution", "enum", required=True,
              enum={"RESOLVED_OK", "RESOLVED_CONTACT_CONFIRMED", "CLOSED_FALSE_ALARM"}),
        Field("note", "str"),
    ])
    g = program_or_404()
    if e["stage"] in cascade.TERMINAL_ESCALATION:
        raise_err(ERR_NO_OPEN_ESCALATION, "Escalation is terminal")
    resolution = data["resolution"]
    if resolution not in ALLOWED_RESOLUTIONS[e["stage"]]:
        raise_err(ERR_INVALID_STATE,
                  "Resolution %s is not available at stage %s" % (resolution, e["stage"]))
    if e["stage"] == "STEP_2_CONTACT" and resolution == "RESOLVED_CONTACT_CONFIRMED":
        if not any(att["outcome"] == "REACHED" for att in e["contact_attempts"]):
            raise_err(ERR_INVALID_STATE,
                      "RESOLVED_CONTACT_CONFIRMED requires a REACHED contact attempt")
    if e["stage"] == "STEP_3_WELFARE" and resolution == "CLOSED_FALSE_ALARM":
        for w in store.welfare.values():
            if (w["escalation_id"] == e["id"]
                    and w["status"] in ("REQUESTED", "DISPATCHED")):
                raise_err(ERR_INVALID_STATE,
                          "A welfare check is still REQUESTED or DISPATCHED")
    if uid == e["opened_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Resolver must differ from opener")
    cascade.finalize_resolution(e, resolution, g, note=data.get("note"))
    return ok(serialize.escalation(e))


# ---------------- welfare checks ----------------

@bp.route("/api/escalations/<eid>/welfare-checks", methods=["GET"])
@endpoint(PC_QR_ER)
def list_welfare_of_escalation(eid, uid, role):
    e = get_escalation_or_404(eid)
    limit, offset = parse_pagination(request.args)
    items = [w for w in store.welfare.values() if w["escalation_id"] == e["id"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.welfare_check(w) for w in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/welfare-checks", methods=["GET"])
@endpoint(PC_QR_ER)
def list_welfare(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.welfare.values())
    for fname in ("participant_id", "status"):
        if fname in request.args:
            items = [w for w in items if w.get(fname) == request.args[fname]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.welfare_check(w) for w in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/welfare-checks/<wid>", methods=["GET"])
@endpoint(PC_QR_ER)
def get_welfare(wid, uid, role):
    return ok(serialize.welfare_check(get_welfare_or_404(wid)))


@bp.route("/api/welfare-checks/<wid>/dispatch", methods=["POST"])
@endpoint(["ExternalResponder"])
def dispatch_welfare(wid, uid, role):
    w = get_welfare_or_404(wid)
    if w["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Welfare check is not REQUESTED")
    w["status"] = "DISPATCHED"
    w["dispatched_at"] = now()
    touch(w)
    return ok(serialize.welfare_check(w))


@bp.route("/api/welfare-checks/<wid>/complete", methods=["POST"])
@endpoint(["ExternalResponder"])
def complete_welfare(wid, uid, role):
    w = get_welfare_or_404(wid)
    data = validate_payload(get_body(), [
        Field("disposition", "enum", required=True,
              enum={"OK", "ASSIST_NEEDED", "NOT_FOUND"}),
        Field("note", "str"),
    ])
    if w["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE, "Welfare check is not DISPATCHED")
    g = program_or_404()
    w["status"] = "COMPLETED"
    w["completed_at"] = now()
    w["disposition"] = data["disposition"]
    if data.get("note") is not None:
        w["responder_note"] = data["note"]
    touch(w)
    p = store.participants.get(w["participant_id"])
    if p and p.get("open_escalation_id"):
        e = store.escalations.get(p["open_escalation_id"])
        if e and e["stage"] in calc.OPEN_STAGES:
            if data["disposition"] == "OK":
                cascade.finalize_resolution(e, "RESOLVED_OK", g)
            elif data["disposition"] == "ASSIST_NEEDED":
                cascade.finalize_resolution(e, "RESOLVED_WITH_REFERRAL", g)
                r = new_entity()
                r.update({
                    "participant_id": p["id"],
                    "source_call_log_id": None,
                    "escalation_id": e["id"],
                    "service_type": "HOME_HEALTH",
                    "priority": "URGENT",
                    "status": "SUBMITTED",
                    "submitted_at": now(),
                    "sla_due_at": now() + timedelta(hours=24),
                    "decline_reason": None,
                })
                store.referrals[r["id"]] = r
            # NOT_FOUND: no automatic resolution
    return ok(serialize.welfare_check(w))


@bp.route("/api/welfare-checks/<wid>/decline", methods=["POST"])
@endpoint(["ExternalResponder"])
def decline_welfare(wid, uid, role):
    w = get_welfare_or_404(wid)
    validate_payload(get_body(), [Field("reason", "str", required=True)])
    if w["status"] not in ("REQUESTED", "DISPATCHED"):
        raise_err(ERR_INVALID_STATE, "Welfare check is not REQUESTED or DISPATCHED")
    w["status"] = "DECLINED"
    touch(w)
    return ok(serialize.welfare_check(w))
