"""Participant endpoints."""
from flask import Blueprint, request, g

import db
from clock import parse_iso, now
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import sync
from services.validation import (
    get_body, require_field, require_str, require_int, require_enum,
    require_country, opt_team, check_version,
)


bp = Blueprint("participants", __name__)


VALID_REGIONS = {"AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA"}


@bp.route("/events/<event_id>/participants", methods=["POST"])
@require_auth(roles={"Organizer"})
def register_participant(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    body = get_body()
    # State validity
    if ev["status"] not in ("OPEN", "REGISTRATION_CLOSED", "DRAFT"):
        raise err("ERR_INVALID_STATE", "event not accepting registrations")
    if ev["status"] == "DRAFT":
        # Can't register on draft — return invalid_state? PRD says register accepted only when OPEN.
        raise err("ERR_INVALID_STATE", "event in DRAFT")
    if ev["status"] == "REGISTRATION_CLOSED":
        raise err("ERR_REGISTRATION_CLOSED", "registration closed")
    # Window check (status == OPEN at this point)
    n = now()
    if not (parse_iso(ev["registration_opens_at"]) <= n < parse_iso(ev["registration_closes_at"])):
        raise err("ERR_REGISTRATION_CLOSED", "now() outside registration window")
    # Capacity
    if ev["registered_count"] >= ev["capacity_max"]:
        raise err("ERR_CAPACITY_EXCEEDED", "capacity_max reached")

    athlete_external_id = require_str(body, "athlete_external_id", min_len=1)
    display_name = require_str(body, "display_name", min_len=1, max_len=80)
    team_code = opt_team(body, "team_code")
    country_code = require_country(body, "country_code")
    require_field(body, "world_ranking")
    wr = body["world_ranking"]
    if wr is not None and (isinstance(wr, bool) or not isinstance(wr, int)):
        raise err("ERR_VALIDATION", "world_ranking must be integer or null")
    region = require_enum(body, "region", VALID_REGIONS)
    entry_fee_paid = require_int(body, "entry_fee_paid_cents", ge=0)

    # Entry fee validation (after capacity per validation order)
    if entry_fee_paid != ev["entry_fee_cents"]:
        raise err("ERR_ENTRY_FEE_MISMATCH", "entry_fee_paid_cents != entry_fee_cents")

    p = {
        "event_id": event_id,
        "athlete_external_id": athlete_external_id,
        "display_name": display_name,
        "team_code": team_code,
        "country_code": country_code,
        "world_ranking": wr,
        "region": region,
        "entry_fee_paid_cents": entry_fee_paid,
        "status": "REGISTERED",
        "bracket_seed": None,
        "gross_prize_cents": 0,
        "net_prize_cents": 0,
        "final_rank": None,
    }
    db.stamp_create(p, common_fields=True)
    db.participants[p["id"]] = p
    ev["registered_count"] = ev["registered_count"] + 1
    db.stamp_update(ev)
    sync.emit(target_system="PAYMENT", kind="ENTRY_FEE_CHARGED",
              payload={"participant_id": p["id"],
                       "amount_cents": entry_fee_paid,
                       "event_id": event_id})
    return success(db.public(p), 201)


@bp.route("/events/<event_id>/participants", methods=["GET"])
@require_auth(roles={
    "Organizer", "Referee", "Participant", "DisciplinaryOfficer", "DopingOfficer"
})
def list_participants(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows = [p for p in db.participants.values() if p["event_id"] == event_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/participants/<participant_id>/withdraw", methods=["POST"])
@require_auth(roles={"Organizer"})
def withdraw(participant_id):
    p = db.participants.get(participant_id)
    if not p:
        raise err("ERR_NOT_FOUND", "participant not found")
    body = get_body()
    ev = db.events.get(p["event_id"])
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if p["status"] in ("REGISTERED",):
        if ev["status"] not in ("OPEN", "REGISTRATION_CLOSED"):
            raise err("ERR_INVALID_STATE", "event not in OPEN/REGISTRATION_CLOSED")
        check_version(p, body)
        p["status"] = "WITHDRAWN"
        db.stamp_update(p)
        ev["registered_count"] = max(0, ev["registered_count"] - 1)
        db.stamp_update(ev)
        sync.emit(target_system="PAYMENT", kind="ENTRY_FEE_CHARGED",
                  payload={"participant_id": p["id"],
                           "refund_cents": -p.get("entry_fee_paid_cents", 0)})
        return success(db.public(p), 200)
    if p["status"] == "SEEDED":
        if ev["status"] != "DRAWN":
            raise err("ERR_INVALID_STATE", "event not in DRAWN for seeded withdrawal")
        check_version(p, body)
        p["status"] = "WITHDRAWN"
        db.stamp_update(p)
        # Cascade: every scheduled Match featuring this participant -> VOIDED
        for m in db.matches.values():
            if m["event_id"] != p["event_id"]:
                continue
            sides = (m.get("home_participant_id"), m.get("away_participant_id"))
            if p["id"] not in sides:
                continue
            if m["status"] in ("SCHEDULED", "RESULT_PENDING", "DISPUTED", "LOCKED", "BYE"):
                m["status"] = "VOIDED"
                db.stamp_update(m)
                # Revoke any RefereeAssignment on this match
                for a in db.referee_assignments.values():
                    if a["match_id"] == m["id"] and a["status"] != "REVOKED":
                        a["status"] = "REVOKED"
                        db.stamp_update(a)
        sync.emit(target_system="PAYMENT", kind="ENTRY_FEE_CHARGED",
                  payload={"participant_id": p["id"],
                           "refund_cents": -p.get("entry_fee_paid_cents", 0)})
        ev["registered_count"] = max(0, ev["registered_count"] - 1)
        db.stamp_update(ev)
        return success(db.public(p), 200)
    raise err("ERR_INVALID_STATE", f"cannot withdraw participant in status {p['status']}")
