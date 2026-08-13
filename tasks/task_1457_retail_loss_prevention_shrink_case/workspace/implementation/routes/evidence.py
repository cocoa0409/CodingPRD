"""Evidence item + custody event endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, opt_string, req_enum, req_datetime, get_or_404,
)
from services.entities import (
    make_evidence_item, make_custody_event, pub, touch,
)
from services.calculations import retention_until_for
from errors import (
    err403, err409,
    ERR_INVALID_STATE_TRANSITION, ERR_NOT_CASE_ASSIGNEE, ERR_CUSTODY_GAP,
    ERR_LEGAL_HOLD_ACTIVE, ERR_CASE_NOT_REFERRABLE,
    ERR_EVIDENCE_SEALED_IMMUTABLE,
)

bp = Blueprint("evidence", __name__)

EVIDENCE_TYPES = ["VIDEO_CLIP", "TRANSACTION_LOG", "PHOTO", "WRITTEN_STATEMENT", "AUDIO"]
RETENTION_CLASSES = ["STANDARD", "EXTENDED", "CASE_HOLD"]
CUSTODY_ACTIONS = ["COLLECTED", "SEALED", "ACCESSED", "TRANSFERRED",
                   "RELEASED_TO_LE", "RETURNED_FROM_LE"]

CASE_STATES_FOR_EVIDENCE = ("INVESTIGATING", "READY_FOR_INTERVIEW",
                            "INTERVIEWED", "ADJUDICATING")


@bp.route("/evidence-items", methods=["POST"])
def create_evidence():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    case_id = req_string(data, "case_id")
    evidence_type = req_enum(data, "evidence_type", EVIDENCE_TYPES)
    captured_at = req_datetime(data, "captured_at")
    retention_class = req_enum(data, "retention_class", RETENTION_CLASSES)

    case = get_or_404(db.cases, case_id, "case")
    if case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    if case["status"] not in CASE_STATES_FOR_EVIDENCE:
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case state %s does not permit evidence attachment"
                     % case["status"])

    retention_until = retention_until_for(retention_class, captured_at, case)
    item = make_evidence_item(case_id, evidence_type, captured_at,
                              retention_class, retention_until)
    db.evidence_items[item["id"]] = item
    return success_object(pub(item), status=201)


@bp.route("/evidence-items", methods=["GET"])
def list_evidence():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = _q("case_id")
    status = _q("status")
    evidence_type = _q("evidence_type")
    retention_class = _q("retention_class")
    items = sorted(db.evidence_items.values(),
                   key=lambda e: (e["created_at"], e["id"]))
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if evidence_type is not None:
        items = [e for e in items if e["evidence_type"] == evidence_type]
    if retention_class is not None:
        items = [e for e in items if e["retention_class"] == retention_class]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(e) for e in page], limit, offset, total)


@bp.route("/evidence-items/<evidence_id>", methods=["GET"])
def get_evidence(evidence_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    item = get_or_404(db.evidence_items, evidence_id, "evidence item")
    return success_object(pub(item))


def _has_collected(evidence_id):
    return any(c["evidence_id"] == evidence_id and c["action"] == "COLLECTED"
               for c in db.custody_events.values())


def _append_custody(evidence_id, action, actor_id, note=None):
    ce = make_custody_event(evidence_id, action, actor_id, note)
    db.custody_events[ce["id"]] = ce
    return ce


@bp.route("/evidence-items/<evidence_id>/seal", methods=["POST"])
def seal_evidence(evidence_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    item = get_or_404(db.evidence_items, evidence_id, "evidence item")
    if item["status"] != "ACTIVE":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Evidence must be ACTIVE to seal")
    if not _has_collected(evidence_id):
        raise err409(ERR_CUSTODY_GAP,
                     "A COLLECTED custody event is required before sealing")
    item["status"] = "SEALED"
    item["sealed_by"] = user_id
    touch(item)
    _append_custody(evidence_id, "SEALED", user_id)
    return success_object(pub(item))


@bp.route("/evidence-items/<evidence_id>/unseal", methods=["POST"])
def unseal_evidence(evidence_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    item = get_or_404(db.evidence_items, evidence_id, "evidence item")
    if item["status"] != "SEALED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Evidence must be SEALED to unseal")
    if item["legal_hold"]:
        raise err409(ERR_LEGAL_HOLD_ACTIVE,
                     "Evidence is under legal hold")
    item["status"] = "ACTIVE"
    touch(item)
    return success_object(pub(item))


@bp.route("/evidence-items/<evidence_id>/release", methods=["POST"])
def release_evidence(evidence_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    item = get_or_404(db.evidence_items, evidence_id, "evidence item")
    if item["status"] != "SEALED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Evidence must be SEALED to release")
    has_ack = any(p["case_id"] == item["case_id"] and p["status"] == "ACKNOWLEDGED"
                  for p in db.referral_packets.values())
    if not has_ack:
        raise err409(ERR_CASE_NOT_REFERRABLE,
                     "An ACKNOWLEDGED referral packet on the case is required")
    item["status"] = "RELEASED"
    touch(item)
    _append_custody(evidence_id, "RELEASED_TO_LE", user_id)
    return success_object(pub(item))


@bp.route("/evidence-items/<evidence_id>/custody-events", methods=["POST"])
def add_custody_event(evidence_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst", "LPManager"})
    data = body()
    action = req_enum(data, "action", CUSTODY_ACTIONS)
    note = opt_string(data, "note")
    item = get_or_404(db.evidence_items, evidence_id, "evidence item")
    if item["status"] == "SEALED" and action in ("ACCESSED", "TRANSFERRED"):
        raise err409(ERR_EVIDENCE_SEALED_IMMUTABLE,
                     "ACCESSED/TRANSFERRED are forbidden while SEALED")
    ce = _append_custody(evidence_id, action, user_id, note)
    return success_object(ce, status=201)


@bp.route("/custody-events", methods=["GET"])
def list_custody_events():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    evidence_id = _q("evidence_id")
    action = _q("action")
    items = sorted(db.custody_events.values(),
                   key=lambda c: (c["created_at"], c["id"]))
    if evidence_id is not None:
        items = [c for c in items if c["evidence_id"] == evidence_id]
    if action is not None:
        items = [c for c in items if c["action"] == action]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(list(page), limit, offset, total)


@bp.route("/custody-events/<custody_event_id>", methods=["GET"])
def get_custody_event(custody_event_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    ce = get_or_404(db.custody_events, custody_event_id, "custody event")
    return success_object(ce)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
