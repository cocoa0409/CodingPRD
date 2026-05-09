"""Ranking + prize-payment list endpoints."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("rankings", __name__)


@bp.route("/events/<event_id>/rankings", methods=["GET"])
@require_auth(roles={"Organizer", "Referee", "Participant", "DisciplinaryOfficer"})
def list_rankings(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    limit, offset = get_pagination()
    rows = [r for r in db.ranking_entries.values() if r["event_id"] == event_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/events/<event_id>/prize-payments", methods=["GET"])
@require_auth(roles={"Organizer", "Participant", "DisciplinaryOfficer"})
def list_prize_payments(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows = [r for r in db.prize_payments.values() if r["event_id"] == event_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)
