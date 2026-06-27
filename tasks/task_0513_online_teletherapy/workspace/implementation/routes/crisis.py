"""Crisis escalation routes: raise, fetch, acknowledge, resolve."""
from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import err, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner
from validate import require_body, require_enum, ESCALATION_SEVERITIES
from services.domain import thread_for_match
import serialize
from response import success

bp = Blueprint("crisis", __name__)


def _freeze_client_threads(client_id):
    client_match_ids = {m["id"] for m in db.matches.values() if m["client_id"] == client_id}
    for t in db.threads.values():
        if t["match_id"] in client_match_ids and t["status"] == "OPEN":
            t["status"] = "FROZEN"
            touch(t)


def _unfreeze_client_threads(client_id):
    """Unfreeze a thread only when its owning match is still ACTIVE."""
    for t in db.threads.values():
        if t["status"] != "FROZEN":
            continue
        match = db.matches.get(t["match_id"])
        if match and match["client_id"] == client_id and match["status"] == "ACTIVE":
            t["status"] = "OPEN"
            touch(t)


def _has_other_open_acute(client_id, exclude_id):
    for e in db.crisis_escalations.values():
        if e["id"] == exclude_id:
            continue
        if e["client_id"] == client_id and e["severity"] == "ACUTE" and e["status"] in ("OPEN", "ACKNOWLEDGED"):
            return True
    return False


def _has_other_open_any(client_id, exclude_id):
    for e in db.crisis_escalations.values():
        if e["id"] == exclude_id:
            continue
        if e["client_id"] == client_id and e["status"] in ("OPEN", "ACKNOWLEDGED"):
            return True
    return False


@bp.route("/clients/<cid>/crisis-escalations", methods=["POST"])
def raise_escalation(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    client = get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    data = require_body(request.get_json(silent=True))
    severity = require_enum(data, "severity", ESCALATION_SEVERITIES)
    raised_by = {"Client": "CLIENT", "Therapist": "THERAPIST", "ClinicalAdmin": "SYSTEM"}[role]
    escalation = {
        **common_create_fields(),
        "client_id": cid,
        "raised_by_role": raised_by,
        "severity": severity,
        "status": "OPEN",
        "safety_resources_sent": True,
    }
    db.crisis_escalations[escalation["id"]] = escalation
    if severity == "ACUTE":
        client["risk_flag"] = "ACUTE"
        if client["status"] == "ACTIVE":
            client["status"] = "SUSPENDED"
            _freeze_client_threads(cid)
        touch(client)
    else:  # ELEVATED
        client["risk_flag"] = "ELEVATED"
        touch(client)
    return success(serialize.crisis_out(escalation), status=201)


@bp.route("/crisis-escalations/<eid>", methods=["GET"])
def get_escalation(eid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    escalation = get_or_404(db.crisis_escalations, eid)
    check_client_owner(role, user_id, escalation["client_id"])
    return success(serialize.crisis_out(escalation))


@bp.route("/crisis-escalations/<eid>/acknowledge", methods=["POST"])
def acknowledge(eid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    escalation = get_or_404(db.crisis_escalations, eid)
    if escalation["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Escalation not in OPEN")
    escalation["status"] = "ACKNOWLEDGED"
    touch(escalation)
    return success(serialize.crisis_out(escalation))


@bp.route("/crisis-escalations/<eid>/resolve", methods=["POST"])
def resolve(eid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    escalation = get_or_404(db.crisis_escalations, eid)
    if escalation["status"] != "ACKNOWLEDGED":
        raise err(ERR_INVALID_STATE, "Escalation not in ACKNOWLEDGED")
    escalation["status"] = "RESOLVED"
    touch(escalation)
    client = db.clients.get(escalation["client_id"])
    if client:
        if escalation["severity"] == "ACUTE":
            if not _has_other_open_acute(client["id"], eid):
                if client["status"] == "SUSPENDED":
                    client["status"] = "ACTIVE"
                client["risk_flag"] = "NONE"
                _unfreeze_client_threads(client["id"])
                touch(client)
        else:  # ELEVATED
            if not _has_other_open_any(client["id"], eid):
                client["risk_flag"] = "NONE"
                touch(client)
    return success(serialize.crisis_out(escalation))
