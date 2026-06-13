"""Lottery round + entry endpoints (PRD §3.9)."""
from flask import Blueprint, request

import errors
import serializers
from clock import now as clock_now
from db import db, stamp_create, touch
from helpers import parse_body, require_fields, parse_dt, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import calculations as calc
from services import domain

bp = Blueprint("lottery", __name__)


def get_round_or_404(round_id):
    r = db.lottery_rounds.get(round_id)
    if r is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lottery round not found")
    return r


def get_entry_or_404(entry_id):
    e = db.lottery_entries.get(entry_id)
    if e is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lottery entry not found")
    return e


@bp.post("/lottery-rounds")
def create_round():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    body = parse_body()
    require_fields(body, ["facility_id", "slot_start_at", "slot_end_at", "opens_at", "closes_at"])

    facility = db.facilities.get(body["facility_id"])
    if facility is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Facility not found")

    slot_start = parse_dt(body["slot_start_at"], "slot_start_at")
    slot_end = parse_dt(body["slot_end_at"], "slot_end_at")
    opens_at = parse_dt(body["opens_at"], "opens_at")
    closes_at = parse_dt(body["closes_at"], "closes_at")

    rec = {
        "facility_id": body["facility_id"],
        "slot_start_at": slot_start,
        "slot_end_at": slot_end,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "status": "OPEN",
        "entry_count": 0,
        "winning_entry_id": None,
    }
    stamp_create(rec)
    db.lottery_rounds[rec["id"]] = rec
    return success(serializers.lottery_round(rec), status=201)


@bp.get("/lottery-rounds/<round_id>")
def get_round(round_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    r = get_round_or_404(round_id)
    return success(serializers.lottery_round(r))


@bp.post("/lottery-rounds/<round_id>/entries")
def create_entry(round_id):
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    rnd = get_round_or_404(round_id)
    body = parse_body()
    require_fields(body, ["patron_id"])
    patron = db.patrons.get(body["patron_id"])
    if patron is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")

    if role == "Patron" and body["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only enter for themselves")

    # At most one ENTERED entry per patron per round.
    for e in db.lottery_entries.values():
        if (e["lottery_round_id"] == round_id and e["patron_id"] == body["patron_id"]
                and e["status"] == "ENTERED"):
            raise errors.err(errors.ERR_DUPLICATE_ENTRY,
                             "Patron already has an ENTERED entry in this round")

    seq = db.next_entry_seq(round_id)
    weight = calc.lottery_priority_weight(patron)
    rec = {
        "lottery_round_id": round_id,
        "patron_id": body["patron_id"],
        "priority_weight": weight,
        "entry_seq": seq,
        "status": "ENTERED",
    }
    stamp_create(rec)
    db.lottery_entries[rec["id"]] = rec

    rnd["entry_count"] += 1
    touch(rnd)
    return success(serializers.lottery_entry(rec), status=201)


@bp.get("/lottery-rounds/<round_id>/entries")
def list_round_entries(round_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    get_round_or_404(round_id)
    items = [e for e in db.lottery_entries.values() if e["lottery_round_id"] == round_id]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.lottery_entry(e) for e in page], pagination=meta)


@bp.get("/lottery-entries/<entry_id>")
def get_entry(entry_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    e = get_entry_or_404(entry_id)
    return success(serializers.lottery_entry(e))


@bp.post("/lottery-entries/<entry_id>/withdraw")
def withdraw_entry(entry_id):
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    e = get_entry_or_404(entry_id)

    if role == "Patron" and e["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only withdraw their own entry")

    rnd = db.lottery_rounds.get(e["lottery_round_id"])
    if rnd is None or rnd["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Parent round is not OPEN")
    if e["status"] != "ENTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ENTERED entry can be withdrawn")

    e["status"] = "WITHDRAWN"
    touch(e)
    rnd["entry_count"] -= 1
    touch(rnd)
    return success(serializers.lottery_entry(e))


@bp.post("/lottery-rounds/<round_id>/draw")
def draw_round(round_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    rnd = get_round_or_404(round_id)
    facility = db.facilities[rnd["facility_id"]]
    body = parse_body()

    # State.
    if rnd["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an OPEN round can be drawn")

    # OCC.
    require_fields(body, ["expected_facility_version"])
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err(errors.ERR_VALIDATION, "expected_facility_version must be an integer")
    if expected != facility["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_facility_version does not match")

    # Time gate.
    if clock_now() < rnd["closes_at"]:
        raise errors.err(errors.ERR_LOTTERY_NOT_CLOSED, "Round not yet closed")
    # Participation gate.
    if rnd["entry_count"] < 1:
        raise errors.err(errors.ERR_LOTTERY_NO_ENTRIES, "Round has no entries")
    # Slot availability gate (no buffer for lottery draw per PRD §3.9).
    if domain.slot_has_granted(facility["id"], rnd["slot_start_at"], rnd["slot_end_at"]):
        raise errors.err(errors.ERR_DOUBLE_BOOKING, "A GRANTED permit already occupies the slot")

    # Select winner: max priority_weight, tie-break lowest entry_seq.
    candidates = [e for e in db.lottery_entries.values()
                  if e["lottery_round_id"] == round_id and e["status"] == "ENTERED"]
    winner = min(candidates, key=lambda e: (-e["priority_weight"], e["entry_seq"]))

    for e in candidates:
        if e["id"] == winner["id"]:
            e["status"] = "WON"
        else:
            e["status"] = "LOST"
        touch(e)

    rnd["status"] = "DRAWN"
    rnd["winning_entry_id"] = winner["id"]

    # Synthesize a GRANTED permit for the winner.
    patron = db.patrons[winner["patron_id"]]
    final_fee = domain.compute_final_fee(facility, patron, rnd["slot_start_at"], rnd["slot_end_at"])
    _, prime_h, _ = calc.prime_overlap_hours(
        rnd["slot_start_at"], rnd["slot_end_at"],
        facility["prime_start_hour"], facility["prime_end_hour"]
    )
    tier = calc.resolve_residency(patron)
    permit = {
        "facility_id": facility["id"],
        "patron_id": winner["patron_id"],
        "coi_id": None,
        "league_id": None,
        "lottery_round_id": round_id,
        "start_at": rnd["slot_start_at"],
        "end_at": rnd["slot_end_at"],
        "is_prime_requested": prime_h > 0,
        "status": "GRANTED",
        "pricing_residency": tier,
        "quoted_fee_cents": final_fee,
        "final_fee_cents": final_fee,
        "deposit_held_cents": facility["deposit_cents"],
        "refunded_cents": 0,
        "cancelled_lead_hours": None,
    }
    stamp_create(permit)
    db.permits[permit["id"]] = permit

    domain.facility_grant_inc(facility)  # version bump on facility
    touch(rnd)
    return success(serializers.lottery_round(rnd))


@bp.post("/lottery-rounds/<round_id>/cancel")
def cancel_round(round_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    rnd = get_round_or_404(round_id)
    if rnd["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an OPEN round can be cancelled")

    for e in db.lottery_entries.values():
        if e["lottery_round_id"] == round_id and e["status"] == "ENTERED":
            e["status"] = "WITHDRAWN"
            touch(e)

    rnd["status"] = "CANCELLED"
    touch(rnd)
    return success(serializers.lottery_round(rnd))


@bp.get("/lottery-entries")
def list_entries():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    items = list(db.lottery_entries.values())
    for key in ("patron_id", "lottery_round_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.lottery_entry(e) for e in page], pagination=meta)


@bp.get("/lottery-rounds")
def list_rounds():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    items = list(db.lottery_rounds.values())
    for key in ("facility_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.lottery_round(r) for r in page], pagination=meta)
