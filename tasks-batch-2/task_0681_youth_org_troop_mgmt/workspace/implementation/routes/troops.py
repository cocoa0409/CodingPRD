"""Troop endpoints incl. charter lifecycle + recharter sweep (PRD §3.1, §3.7)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from clock import clock
from errors import (
    err,
    ERR_DUPLICATE_UNIT_NUMBER,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_INSUFFICIENT_TROOP_FUNDS,
    ERR_RECHARTER_NOT_READY,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_roles, REGISTRAR_ONLY, BOTH_ROLES
from response import object_response, array_response
from serializers import serialize_troop, serialize_fund_ledger_entry
from util import new_id, iso_now
from routes import helpers as h
from services import recompute, calculations
from services.ledger import post_ledger_entry

bp = Blueprint("troops", __name__)

PROGRAM_TYPES = {"CUB", "SCOUTS", "VENTURING"}


@bp.post("/councils/<council_id>/troops")
def create_troop(council_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    council = h.get_or_404(db.councils, council_id)
    body = h.get_json_body()

    unit_number = h.require_string(body, "unit_number")
    program_type = h.require_enum(body, "program_type", PROGRAM_TYPES)

    # PRD §3.1: unit_number must be unique within its council.
    for t in db.troops.values():
        if t["council_id"] == council["id"] and t["unit_number"] == unit_number:
            raise err(ERR_DUPLICATE_UNIT_NUMBER, "unit_number already used in council")

    now = iso_now(datetime.now(timezone.utc))
    troop = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "council_id": council["id"],
        "unit_number": unit_number,
        "program_type": program_type,
        "charter_status": "PROVISIONAL",
        "recharter_posture": "BLOCKED",
        "registered_youth_count": 0,
        "cleared_leader_count": 0,
        "charter_expires_at": None,
        "_charter_expires_dt": None,
        "dues_account_cents": 0,
        "_seq": db.next_seq(),
    }
    # Compute initial posture (BLOCKED for a fresh troop) — no version bump.
    recompute.refresh_troop_read(troop)
    db.troops[troop["id"]] = troop
    return object_response(serialize_troop(troop), status=201)


@bp.get("/troops/<troop_id>")
def get_troop(troop_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    troop = h.get_or_404(db.troops, troop_id)
    recompute.refresh_troop_read(troop)
    return object_response(serialize_troop(troop))


@bp.get("/troops")
def list_troops():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    council_id = request.args.get("council_id")
    limit, offset = h.parse_pagination()
    rows = [
        t for t in db.troops.values()
        if council_id is None or t["council_id"] == council_id
    ]
    rows = h.sort_by_creation(rows)
    for t in rows:
        recompute.refresh_troop_read(t)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_troop(t) for t in page], limit, offset, total)


@bp.get("/troops/<troop_id>/ledger")
def list_troop_ledger(troop_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    troop = h.get_or_404(db.troops, troop_id)
    account = request.args.get("account")
    limit, offset = h.parse_pagination()
    rows = [
        e for e in db.fund_ledger_entries.values()
        if e["troop_id"] == troop["id"]
        and (account is None or e["account"] == account)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_fund_ledger_entry(e) for e in page], limit, offset, total
    )


@bp.post("/troops/<troop_id>/recharter")
def recharter_troop(troop_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    troop = h.get_or_404(db.troops, troop_id)
    body = h.get_json_body()

    # Recompute derived posture/funds before gating (reflect current reality).
    recompute.refresh_troop_read(troop)

    # Validation order (PRD §3.9): state -> OCC -> funds -> posture.
    # State: recharter only from PROVISIONAL or LAPSED (PRD §3.1).
    if troop["charter_status"] not in ("PROVISIONAL", "LAPSED"):
        raise err(ERR_INVALID_STATE, "recharter not defined from current charter_status")

    # OCC: expected_troop_version is required and must match (PRD §2.6).
    expected = h.require_field(body, "expected_troop_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_troop_version must be an integer")
    if expected != troop["version"]:
        raise err(ERR_STALE_VERSION, "expected_troop_version does not match current version")

    council = db.councils[troop["council_id"]]

    # Fiscal gate: settled TROOP_DUES >= charter_fee_cents (PRD §3.7).
    settled = calculations.settled_troop_dues(troop["id"])
    if settled < council["charter_fee_cents"]:
        raise err(ERR_INSUFFICIENT_TROOP_FUNDS, "settled troop funds below charter fee")

    # Posture gate (PRD §3.1).
    if troop["recharter_posture"] != "READY":
        raise err(ERR_RECHARTER_NOT_READY, "recharter_posture is not READY")

    # Success: transition + charter expiry + sweep.
    troop["charter_status"] = "CHARTERED"
    # charter_expires_at = Dec 31 23:59:59Z of program_year (PRD §3.1).
    expires = datetime(council["program_year"], 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    troop["_charter_expires_dt"] = expires
    troop["charter_expires_at"] = iso_now(expires)

    fee = council["charter_fee_cents"]
    # Sweep: -fee from TROOP_DUES, +fee to COUNCIL_CASH (source_kind=RECHARTER).
    post_ledger_entry(
        council["id"], "TROOP_DUES", -fee, "RECHARTER", troop["id"], troop_id=troop["id"]
    )
    post_ledger_entry(
        council["id"], "COUNCIL_CASH", fee, "RECHARTER", troop["id"], troop_id=None
    )

    # Recompute dues_account / cash, then bump version by 1.
    recompute.recompute_troop_counts(troop, bump=True)
    recompute.refresh_council_read(council)
    return object_response(serialize_troop(troop))


@bp.post("/troops/<troop_id>/lapse")
def lapse_troop(troop_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    troop = h.get_or_404(db.troops, troop_id)
    if troop["charter_status"] != "CHARTERED":
        raise err(ERR_INVALID_STATE, "lapse only defined from CHARTERED")
    troop["charter_status"] = "LAPSED"
    recompute.bump_troop_version(troop)
    recompute.refresh_troop_read(troop)
    return object_response(serialize_troop(troop))


@bp.post("/troops/<troop_id>/drop")
def drop_troop(troop_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    troop = h.get_or_404(db.troops, troop_id)
    if troop["charter_status"] != "LAPSED":
        raise err(ERR_INVALID_STATE, "drop only defined from LAPSED")
    troop["charter_status"] = "DROPPED"
    recompute.bump_troop_version(troop)
    recompute.refresh_troop_read(troop)
    return object_response(serialize_troop(troop))
