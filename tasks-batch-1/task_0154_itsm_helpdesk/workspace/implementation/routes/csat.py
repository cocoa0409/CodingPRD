"""CSAT survey routes (PRD §3.7)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from response import success_object, success_array
from services import serialize
from services.common import stamp_create, paginate, require_fields, sorted_by_created
from services.sla import whole_minutes_between, CSAT_WINDOW_MINUTES

bp = Blueprint("csat", __name__)


def _body():
    return request.get_json(silent=True) or {}


@bp.route("/csat-surveys", methods=["POST"])
def create_survey():
    require_auth(["Requester"])
    body = _body()
    require_fields(body, ["ticket_id", "score"])
    ticket_id = body["ticket_id"]
    ticket = store.tickets.get(ticket_id)
    if ticket is None:
        raise err("ERR_FK_NOT_FOUND", "ticket_id does not resolve.")

    # Referential / temporal ordering per §3.10:
    # duplicate-survey (priority 14) comes after CSAT window (priority 13).
    # But window depends on resolved_at; a ticket never resolved has no window.
    resolved_at = ticket.get("resolved_at")
    now = store.now()
    if resolved_at is None:
        # Not resolved -> cannot survey; treated as window-closed boundary.
        raise err("ERR_CSAT_WINDOW_CLOSED", "Ticket is not resolved; survey window not open.")

    elapsed = whole_minutes_between(now, resolved_at)
    within_window = elapsed <= CSAT_WINDOW_MINUTES
    if not within_window:
        raise err("ERR_CSAT_WINDOW_CLOSED", "CSAT survey submitted past the window.")

    # duplicate survey (priority 14)
    for s in store.csat_surveys.values():
        if s["ticket_id"] == ticket_id:
            raise err("ERR_DUPLICATE_SURVEY", "A survey already exists for this ticket.")

    # score validity (priority 16)
    score = body["score"]
    if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 5:
        raise err("ERR_INVALID_FIELD_VALUE", "score must be an integer 1..5.")

    comment = body.get("comment")
    rec = {
        "ticket_id": ticket_id,
        "score": score,
        "comment": comment,
        "counts_toward_index": within_window,
    }
    stamp_create(rec)
    store.csat_surveys[rec["id"]] = rec
    return success_object(serialize.csat_survey(rec), 201)


@bp.route("/csat-surveys/<sid>", methods=["GET"])
def get_survey(sid):
    rec = store.csat_surveys.get(sid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "CSAT survey not found.")
    return success_object(serialize.csat_survey(rec), 200)


@bp.route("/csat-surveys", methods=["GET"])
def list_surveys():
    items = list(store.csat_surveys.values())
    ticket_id = request.args.get("ticket_id")
    if ticket_id is not None:
        items = [s for s in items if s["ticket_id"] == ticket_id]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.csat_survey(s) for s in window], limit, offset, total)
