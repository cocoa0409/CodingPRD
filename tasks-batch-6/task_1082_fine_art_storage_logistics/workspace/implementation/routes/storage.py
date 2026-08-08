"""Routes: storage placements."""
from flask import Blueprint, request

import store
from store import db, new_record, touch, serialize
from common import auth, get_body, require_fields, get_or_404, fk_or_404, paginate
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt, iso_format
import calc
import domain

bp = Blueprint("storage", __name__)


@bp.route("/storage-placements", methods=["POST"])
def create_placement():
    auth(["Registrar"])
    body = get_body()
    artwork = fk_or_404("artworks", body.get("artwork_id"))
    vault = fk_or_404("vaults", body.get("vault_id"))
    require_fields(body, ["artwork_id", "vault_id", "start_at", "scheduled_end_at"])
    start = parse_dt(body["start_at"])
    end = parse_dt(body["scheduled_end_at"])
    # time window (priority 6)
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "scheduled_end_at must be after start_at")
    # business rules in the order from PRD §3.2
    if artwork["climate_class"] != vault["climate_class"]:
        raise err("ERR_CLIMATE_MISMATCH", "artwork climate does not match vault")
    if vault["status"] != "OPERATIONAL":
        raise err("ERR_VAULT_UNAVAILABLE", "vault is not operational")
    if vault["occupied_slots"] >= vault["capacity_slots"]:
        raise err("ERR_VAULT_FULL", "vault is full")

    provisional = calc.storage_fee(vault["climate_class"], artwork["size_class"],
                                   body["start_at"], body["scheduled_end_at"])
    rec = new_record({
        "artwork_id": artwork["id"],
        "vault_id": vault["id"],
        "start_at": body["start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "released_at": None,
        "provisional_fee_cents": provisional,
        "final_fee_cents": None,
        "status": "ACTIVE",
    })
    db["storage_placements"][rec["id"]] = rec
    domain.vault_slot_delta(vault, 1)
    if artwork["custody_status"] == "IN_INTAKE":
        artwork["custody_status"] = "IN_STORAGE"
        touch(artwork)
    return object_response(serialize(rec), 201)


@bp.route("/storage-placements/<rid>/state", methods=["POST"])
def placement_state(rid):
    auth(["Registrar"])
    rec = get_or_404("storage_placements", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in {"ACTIVE", "SUSPENDED", "RELEASED"}:
        raise err("ERR_VALIDATION", "invalid to_status")
    if to_status != "RELEASED" or rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "cannot move placement from %s to %s"
                  % (rec["status"], to_status))
    was_active = rec["status"] == "ACTIVE"
    clock = store.get_clock()
    rec["released_at"] = iso_format(clock)
    artwork = db["artworks"].get(rec["artwork_id"])
    vault = db["vaults"].get(rec["vault_id"])
    rec["final_fee_cents"] = calc.storage_fee(
        vault["climate_class"], artwork["size_class"], rec["start_at"], rec["released_at"])
    rec["status"] = "RELEASED"
    touch(rec)
    if was_active and vault is not None:
        domain.vault_slot_delta(vault, -1)
    return object_response(serialize(rec))


@bp.route("/storage-placements/<rid>", methods=["GET"])
def get_placement(rid):
    auth(["Registrar", "Coordinator"])
    rec = get_or_404("storage_placements", rid)
    return object_response(serialize(rec))


@bp.route("/storage-placements", methods=["GET"])
def list_placements():
    auth(["Registrar", "Coordinator"])
    aid = request.args.get("artwork_id")
    vid = request.args.get("vault_id")
    st = request.args.get("status")
    recs = [r for r in db["storage_placements"].values()
            if (aid is None or r["artwork_id"] == aid)
            and (vid is None or r["vault_id"] == vid)
            and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
