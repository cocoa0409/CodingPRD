"""Event endpoints."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, g

import db
from clock import parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import event_lifecycle as evlc
from services.validation import (
    get_body, require_field, require_str, require_int, require_enum,
    require_country, check_version,
)


bp = Blueprint("events", __name__)


VALID_EVENT_TYPES = {"SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"}
VALID_CURRENCIES = {"USD", "EUR", "JPY", "GBP"}


READ_ROLES_ALL = {
    "Organizer", "Referee", "Participant", "DisciplinaryOfficer",
    "DopingOfficer", "AppealsBoard",
}


@bp.route("/events", methods=["POST"])
@require_auth(roles={"Organizer"})
def create_event():
    body = get_body()
    name = require_str(body, "name", min_len=1, max_len=120)
    event_type = require_enum(body, "event_type", VALID_EVENT_TYPES)
    country_code = require_country(body, "country_code")
    regulations_text = require_str(body, "regulations_text", min_len=1, max_len=4000)
    require_field(body, "registration_opens_at")
    require_field(body, "registration_closes_at")
    require_field(body, "starts_at")
    try:
        ropens = parse_iso(body["registration_opens_at"])
        rcloses = parse_iso(body["registration_closes_at"])
        sat = parse_iso(body["starts_at"])
    except ValueError as e:
        raise err("ERR_VALIDATION", str(e))
    if not (rcloses > ropens):
        raise err("ERR_VALIDATION", "registration_closes_at must be > registration_opens_at")
    if not (sat >= rcloses):
        raise err("ERR_VALIDATION", "starts_at must be >= registration_closes_at")
    entry_fee = require_int(body, "entry_fee_cents", ge=0)
    settlement_currency = require_enum(body, "settlement_currency", VALID_CURRENCIES)
    capacity_min = require_int(body, "capacity_min", ge=2)
    capacity_max = require_int(body, "capacity_max", ge=2, le=256)
    if capacity_max < capacity_min:
        raise err("ERR_VALIDATION", "capacity_max must be >= capacity_min")
    prize_pool = require_int(body, "prize_pool_cents", ge=0)
    require_field(body, "tax_withholding_pct")
    raw_tax = body["tax_withholding_pct"]
    if isinstance(raw_tax, bool):
        raise err("ERR_VALIDATION", "tax_withholding_pct must be a number")
    try:
        tax_pct = Decimal(str(raw_tax))
    except (InvalidOperation, ValueError):
        raise err("ERR_VALIDATION", "tax_withholding_pct must be a number")
    if tax_pct < Decimal("0") or tax_pct > Decimal("50"):
        raise err("ERR_TAX_OUT_OF_RANGE", "tax_withholding_pct out of [0, 50]")

    ev = {
        "name": name,
        "event_type": event_type,
        "country_code": country_code,
        "regulations_text": regulations_text,
        "registration_opens_at": body["registration_opens_at"],
        "registration_closes_at": body["registration_closes_at"],
        "starts_at": body["starts_at"],
        "entry_fee_cents": entry_fee,
        "settlement_currency": settlement_currency,
        "capacity_min": capacity_min,
        "capacity_max": capacity_max,
        "prize_pool_cents": prize_pool,
        "tax_withholding_pct": float(tax_pct),
        "status": "DRAFT",
        "registered_count": 0,
        "prize_paid_total_cents": 0,
        "posture": "CLEAN",
    }
    db.stamp_create(ev, common_fields=True)
    db.events[ev["id"]] = ev
    return success(db.public(ev), 201)


@bp.route("/events/<event_id>", methods=["GET"])
@require_auth(roles=READ_ROLES_ALL)
def get_event(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    return success(db.public(ev), 200)


@bp.route("/events", methods=["GET"])
@require_auth(roles=READ_ROLES_ALL)
def list_events():
    limit, offset = get_pagination()
    status = request.args.get("status")
    country_code = request.args.get("country_code")
    rows = []
    for ev in db.events.values():
        if status and ev["status"] != status:
            continue
        if country_code and ev["country_code"] != country_code:
            continue
        rows.append(ev)
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/events/<event_id>/open", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_open(event_id):
    body = get_body()
    ev = evlc.open_event(event_id, body, g.user_id, g.user_role)
    return success(db.public(ev), 200)


@bp.route("/events/<event_id>/close-registration", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_close_registration(event_id):
    body = get_body()
    ev = evlc.close_registration(event_id, body)
    return success(db.public(ev), 200)


@bp.route("/events/<event_id>/draw", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_draw(event_id):
    body = get_body()
    ev = evlc.draw_event(event_id, body)
    return success(db.public(ev), 200)


@bp.route("/events/<event_id>/start", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_start(event_id):
    body = get_body()
    ev = evlc.start_event(event_id, body)
    return success(db.public(ev), 200)


@bp.route("/events/<event_id>/complete", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_complete(event_id):
    body = get_body()
    ev = evlc.complete_event(event_id, body)
    return success(db.public(ev), 200)


@bp.route("/events/<event_id>/cancel", methods=["POST"])
@require_auth(roles={"Organizer"})
def post_cancel(event_id):
    body = get_body()
    ev = evlc.cancel_event(event_id, body)
    return success(db.public(ev), 200)
