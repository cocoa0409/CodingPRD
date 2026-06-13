"""Garment endpoints: provisioning, emblem, wash cycle, retire (PRD §3.3-3.6)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, touch, public_view, sort_by_created
from services.ledger import (
    recompute_account, create_charge, damage_fee, DAMAGE_RETIRE_STRIKES,
)
from services import validate

bp = Blueprint("garments", __name__)


def _ensure_account(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    return acct


def _ensure_garment(garment_id):
    g = db.garments.get(garment_id)
    if g is None:
        raise errors.not_found("Garment not found.")
    return g


def _linked_assignment(garment_id):
    """Return the currently-ASSIGNED assignment for a garment, if any."""
    for a in db.assignments.values():
        if a["garment_id"] == garment_id and a["status"] == "ASSIGNED":
            return a
    return None


@bp.route("/accounts/<account_id>/garments", methods=["POST"])
def provision_garment(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    acct = _ensure_account(account_id)
    body = validate.get_body()

    garment_type_id = validate.require_str(body, "garment_type_id")
    tag_code = validate.require_str(body, "tag_code")
    emblem_text = validate.optional_str(body, "emblem_text", default=None)
    if emblem_text is not None and emblem_text.strip() == "":
        # A provided but blank emblem_text is malformed.
        raise errors.invalid_request("emblem_text must not be blank when provided.")

    # priority 4: FK integrity on garment_type_id.
    if garment_type_id not in db.garment_types:
        raise errors.fk_integrity("garment_type_id does not resolve.")

    # priority 12: tag_code unique per account.
    for g in db.garments.values():
        if g["account_id"] == account_id and g["tag_code"] == tag_code:
            raise errors.duplicate_key("tag_code already in use for this account.")

    g = make_record("garments", {
        "account_id": account_id,
        "garment_type_id": garment_type_id,
        "tag_code": tag_code,
        "lifecycle_status": "IN_STOCK",
        "wash_location": "AT_PLANT",
        "emblem_text": emblem_text,
        "soil_strikes": 0,
        "cycled_through_wash_this_visit": False,
        "wash_station_id": None,
        "slot_start_min": None,
        "slot_end_min": None,
    })
    return object_response(public_view(g), 201)


@bp.route("/accounts/<account_id>/garments", methods=["GET"])
def list_account_garments(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager", "CleanroomTech"})
    _ensure_account(account_id)
    limit, offset = parse_pagination()
    lifecycle = request.args.get("lifecycle_status")
    wash = request.args.get("wash_location")

    rows = [g for g in db.garments.values() if g["account_id"] == account_id]
    if lifecycle is not None:
        rows = [g for g in rows if g["lifecycle_status"] == lifecycle]
    if wash is not None:
        rows = [g for g in rows if g["wash_location"] == wash]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(g) for g in page], limit, offset, total)


@bp.route("/garments/<garment_id>", methods=["GET"])
def get_garment(garment_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager", "CleanroomTech"})
    g = _ensure_garment(garment_id)
    return object_response(public_view(g), 200)


@bp.route("/garments/<garment_id>/apply-emblem", methods=["POST"])
def apply_emblem(garment_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    g = _ensure_garment(garment_id)
    body = validate.get_body()

    # emblem_text required and non-blank -> ERR_EMBLEM_TEXT_INVALID on blank.
    if "emblem_text" not in body or body["emblem_text"] is None:
        raise errors.emblem_text_invalid("emblem_text is required.")
    emblem_text = body["emblem_text"]
    if not isinstance(emblem_text, str) or emblem_text.strip() == "":
        raise errors.emblem_text_invalid()

    first_emblem = g["emblem_text"] is None
    g["emblem_text"] = emblem_text
    touch(g)

    if first_emblem:
        gt = db.garment_types[g["garment_type_id"]]
        create_charge(None, g["account_id"], "EMBLEM_SETUP", gt["emblem_setup_cents"])
        acct = db.accounts[g["account_id"]]
        recompute_account(acct)

    return object_response(public_view(g), 200)


@bp.route("/garments/<garment_id>/start-wash", methods=["POST"])
def start_wash(garment_id):
    role = get_role()
    require_role(role, {"CleanroomTech"})
    g = _ensure_garment(garment_id)
    body = validate.get_body()

    wash_station_id = validate.require_str(body, "wash_station_id")
    slot_start = validate.require_int(body, "slot_start_min")
    slot_end = validate.require_int(body, "slot_end_min")

    # priority 4: FK integrity on wash_station_id.
    station = db.wash_stations.get(wash_station_id)
    if station is None:
        raise errors.fk_integrity("wash_station_id does not resolve.")

    # priority 5: state legality (wash dimension must be IN_SOIL).
    if g["wash_location"] != "IN_SOIL":
        raise errors.invalid_state("start-wash requires wash_location IN_SOIL.")

    # priority 14-style window well-formedness: 0 <= start < end <= 1440.
    if not (0 <= slot_start < slot_end <= 1440):
        raise errors.invalid_request("Slot window must satisfy 0 <= start < end <= 1440.")

    # priority 10: aggregate-capacity overlap on the station, counting the new slot.
    if _would_exceed_capacity(station, slot_start, slot_end):
        raise errors.wash_station_full()

    g["wash_location"] = "IN_WASH"
    g["wash_station_id"] = wash_station_id
    g["slot_start_min"] = slot_start
    g["slot_end_min"] = slot_end
    touch(g)
    return object_response(public_view(g), 200)


def _would_exceed_capacity(station, new_start, new_end):
    """Aggregate-capacity interval check (PRD §3.5).

    Reject if at any instant within [new_start, new_end) more than capacity
    slots (existing IN_WASH slots on this station + the new one) overlap.
    Half-open slots: an instant counts a slot when start <= t < end. We only
    need to test at the existing slots' start points and the new start, since
    overlap counts can only rise at a slot's start boundary.
    """
    station_id = station["id"]
    existing = [
        (g["slot_start_min"], g["slot_end_min"])
        for g in db.garments.values()
        if g.get("wash_station_id") == station_id
        and g["wash_location"] == "IN_WASH"
        and g["slot_start_min"] is not None
    ]
    slots = existing + [(new_start, new_end)]
    # Candidate instants: every slot start that lies within the new interval,
    # plus the new start itself.
    candidates = {new_start}
    for s, e in slots:
        if new_start <= s < new_end:
            candidates.add(s)
    for t in candidates:
        count = sum(1 for s, e in slots if s <= t < e)
        if count > station["capacity"]:
            return True
    return False


@bp.route("/garments/<garment_id>/finish-wash", methods=["POST"])
def finish_wash(garment_id):
    role = get_role()
    require_role(role, {"CleanroomTech"})
    g = _ensure_garment(garment_id)

    if g["wash_location"] != "IN_WASH":
        raise errors.invalid_state("finish-wash requires wash_location IN_WASH.")

    g["wash_location"] = "AT_PLANT"
    g["wash_station_id"] = None
    g["slot_start_min"] = None
    g["slot_end_min"] = None
    g["cycled_through_wash_this_visit"] = True
    touch(g)
    return object_response(public_view(g), 200)


@bp.route("/garments/<garment_id>/retire", methods=["POST"])
def retire_garment(garment_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    g = _ensure_garment(garment_id)

    # State legality: retire defined from ASSIGNED or IN_STOCK lifecycle,
    # and only when soil_strikes >= DAMAGE_RETIRE_STRIKES (retire-for-damage).
    if g["lifecycle_status"] not in ("ASSIGNED", "IN_STOCK"):
        raise errors.invalid_state("retire requires lifecycle ASSIGNED or IN_STOCK.")
    if g["soil_strikes"] < DAMAGE_RETIRE_STRIKES:
        raise errors.invalid_state("retire requires soil_strikes at the damage threshold.")

    linked = _linked_assignment(garment_id)
    g["lifecycle_status"] = "RETIRED"
    touch(g)

    if linked is not None:
        gt = db.garment_types[g["garment_type_id"]]
        create_charge(None, g["account_id"], "DAMAGE", damage_fee(g, gt))
        acct = db.accounts[g["account_id"]]
        recompute_account(acct)

    return object_response(public_view(g), 200)
