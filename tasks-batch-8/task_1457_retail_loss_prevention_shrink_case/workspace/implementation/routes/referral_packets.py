"""Referral packet endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import db, clock_now, fmt_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, opt_string, req_enum, get_or_404,
)
from services.entities import make_referral_packet, pub, touch
from errors import (
    err403, err409,
    ERR_INVALID_STATE_TRANSITION, ERR_NOT_CASE_ASSIGNEE,
    ERR_EVIDENCE_UNSEALED, ERR_CUSTODY_GAP, ERR_PACKET_NOT_READY,
)

bp = Blueprint("referral_packets", __name__)


@bp.route("/referral-packets", methods=["POST"])
def create_packet():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    case_id = req_string(data, "case_id")
    jurisdiction_code = req_string(data, "jurisdiction_code")
    case = get_or_404(db.cases, case_id, "case")
    if case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    if case["status"] != "CLOSED_SUBSTANTIATED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Packet drafting requires case CLOSED_SUBSTANTIATED")
    packet = make_referral_packet(case_id, jurisdiction_code)
    db.referral_packets[packet["id"]] = packet
    return success_object(pub(packet), status=201)


@bp.route("/referral-packets", methods=["GET"])
def list_packets():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = _q("case_id")
    status = _q("status")
    items = sorted(db.referral_packets.values(),
                   key=lambda p: (p["created_at"], p["id"]))
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(p) for p in page], limit, offset, total)


@bp.route("/referral-packets/<packet_id>", methods=["GET"])
def get_packet(packet_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    packet = get_or_404(db.referral_packets, packet_id, "referral packet")
    return success_object(pub(packet))


@bp.route("/referral-packets/<packet_id>/seal", methods=["POST"])
def seal_packet(packet_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    packet = get_or_404(db.referral_packets, packet_id, "referral packet")
    case = db.cases.get(packet["case_id"])
    if case is not None and case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    if packet["status"] != "DRAFT":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Packet must be DRAFT to seal")
    items = [e for e in db.evidence_items.values()
             if e["case_id"] == packet["case_id"]]
    # every still-ACTIVE item must be sealed first; EXPIRED/PURGED excluded
    if any(e["status"] == "ACTIVE" for e in items):
        raise err409(ERR_EVIDENCE_UNSEALED,
                     "Every ACTIVE evidence item of the case must be sealed first")
    # every SEALED item must show a COLLECTED custody event
    for e in items:
        if e["status"] == "SEALED":
            has_collected = any(
                c["evidence_id"] == e["id"] and c["action"] == "COLLECTED"
                for c in db.custody_events.values())
            if not has_collected:
                raise err409(ERR_CUSTODY_GAP,
                             "A sealed evidence item lacks a COLLECTED custody "
                             "event")
    packet["packet_exposure_cents"] = case["total_loss_cents"] if case else 0
    packet["status"] = "SEALED"
    touch(packet)
    return success_object(pub(packet))


@bp.route("/referral-packets/<packet_id>/submit", methods=["POST"])
def submit_packet(packet_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    packet = get_or_404(db.referral_packets, packet_id, "referral packet")
    if packet["status"] != "SEALED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Packet must be SEALED to submit")
    case = db.cases.get(packet["case_id"])
    if case is None or case["status"] != "CLOSED_SUBSTANTIATED":
        raise err409(ERR_PACKET_NOT_READY,
                     "Case must be CLOSED_SUBSTANTIATED")
    has_draft_demand = any(
        d["case_id"] == packet["case_id"] and d["status"] == "DRAFT"
        for d in db.civil_demands.values())
    if has_draft_demand:
        raise err409(ERR_PACKET_NOT_READY,
                     "A DRAFT civil demand exists on the case")
    packet["submitted_at"] = fmt_iso(clock_now())
    packet["status"] = "SUBMITTED"
    touch(packet)
    # legal hold on every SEALED/ACTIVE evidence item of the case
    for e in db.evidence_items.values():
        if e["case_id"] == packet["case_id"] and e["status"] in ("SEALED", "ACTIVE"):
            if not e["legal_hold"]:
                e["legal_hold"] = True
                touch(e)
    return success_object(pub(packet))


@bp.route("/referral-packets/<packet_id>/acknowledge", methods=["POST"])
def acknowledge_packet(packet_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    outcome = req_enum(data, "outcome", ["ACKNOWLEDGED", "RETURNED"])
    return_reason = opt_string(data, "return_reason")
    packet = get_or_404(db.referral_packets, packet_id, "referral packet")
    if packet["status"] != "SUBMITTED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Packet must be SUBMITTED to acknowledge")
    if outcome == "ACKNOWLEDGED":
        packet["status"] = "ACKNOWLEDGED"
        touch(packet)
    else:
        packet["status"] = "RETURNED"
        packet["return_reason"] = return_reason
        touch(packet)
        for e in db.evidence_items.values():
            if e["case_id"] == packet["case_id"] and e["legal_hold"]:
                e["legal_hold"] = False
                touch(e)
    return success_object(pub(packet))


@bp.route("/referral-packets/<packet_id>/revise", methods=["POST"])
def revise_packet(packet_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    packet = get_or_404(db.referral_packets, packet_id, "referral packet")
    case = db.cases.get(packet["case_id"])
    if case is not None and case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    if packet["status"] != "RETURNED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Packet must be RETURNED to revise")
    packet["status"] = "DRAFT"
    touch(packet)
    return success_object(pub(packet))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
