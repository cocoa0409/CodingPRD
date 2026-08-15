"""Quality holds and disposition (PRD §3.7)."""
from decimal import Decimal

from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import ALL_ROLES, auth, body, is_int, paginate, require_fields
from response import success_list, success_object
from serializers import hold_json
from services.pricing import BLOOM_RELEASE_MAX_PCT, defect_rate_pct
from services.projection import recompute_window_of_lot
from routes.lots import get_lot_or_404

holds_bp = Blueprint("holds", __name__)

DEFECT_TYPES = ("BLOOM", "TEMPER_DEVIATION", "FOREIGN_MATERIAL", "OTHER")
DISPOSITION_ACTIONS = ("RELEASE", "SCRAP", "REWORK")


def get_hold_or_404(hid):
    h = store.quality_holds.get(hid)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", "Quality hold not found: %s" % hid)
    return h


@holds_bp.route("/quality-holds", methods=["POST"])
def create_hold():
    uid = auth(("QualityManager", "LineOperator"))
    b = body()
    # Existence: lot_id must resolve.
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in store.lots:
        raise ApiError("ERR_NOT_FOUND", "lot_id references a non-existent resource.")
    # Request shape.
    require_fields(b, ["lot_id", "defect_type", "affected_units"])
    if b["defect_type"] not in DEFECT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "defect_type must be one of BLOOM, TEMPER_DEVIATION, FOREIGN_MATERIAL, OTHER.")
    lot = store.lots[b["lot_id"]]
    if not is_int(b["affected_units"]) or b["affected_units"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "affected_units must be an integer > 0.")
    if b["affected_units"] > lot["qty_on_hand"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "affected_units must not exceed the lot's qty_on_hand at hold creation.")
    # State: a manual hold can only be opened on an ACTIVE lot.
    if lot["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "A manual quality hold requires an ACTIVE lot.")
    h = {
        "id": new_id(),
        "lot_id": lot["id"],
        "defect_type": b["defect_type"],
        "affected_units": b["affected_units"],
        "lot_qty_at_open": lot["qty_on_hand"],
        "defect_rate_pct": defect_rate_pct(b["affected_units"], lot["qty_on_hand"]),
        "opened_by": uid,
        "disposition_by": None,
        "status": "OPEN",
    }
    stamp_new(h)
    store.quality_holds[h["id"]] = h
    # The hold's creation blocks the lot and recomputes the window projection.
    lot["status"] = "BLOCKED"
    touch(lot)
    recompute_window_of_lot(lot)
    return success_object(hold_json(h), 201)


@holds_bp.route("/quality-holds", methods=["GET"])
def list_holds():
    auth(ALL_ROLES)
    items = list(store.quality_holds.values())
    f = request.args.get("lot_id")
    if f is not None:
        items = [h for h in items if h["lot_id"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [h for h in items if h["status"] == f]
    items.sort(key=lambda h: h["created_at"])
    page, meta = paginate(items)
    return success_list([hold_json(h) for h in page], meta)


@holds_bp.route("/quality-holds/<hid>", methods=["GET"])
def get_hold(hid):
    auth(ALL_ROLES)
    return success_object(hold_json(get_hold_or_404(hid)))


@holds_bp.route("/quality-holds/<hid>/disposition", methods=["POST"])
def disposition_hold(hid):
    uid = auth(("QualityManager",))
    h = get_hold_or_404(hid)
    b = body()
    if "action" not in b or b["action"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: action.")
    if b["action"] not in DISPOSITION_ACTIONS:
        raise ApiError("ERR_INVALID_REQUEST", "action must be one of RELEASE, SCRAP, REWORK.")
    if h["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN hold can be dispositioned.")
    action = b["action"]
    lot = store.lots[h["lot_id"]]
    if action == "RELEASE":
        # Bloom gate: at a rounded defect rate of 2.00 percent or worse,
        # release is forbidden and only scrap or rework remain.
        if (h["defect_type"] == "BLOOM"
                and Decimal(str(h["defect_rate_pct"])) >= BLOOM_RELEASE_MAX_PCT):
            raise ApiError("ERR_BLOOM_RELEASE_FORBIDDEN",
                           "A BLOOM hold with defect_rate_pct >= 2.00 cannot be released.")
        h["disposition_by"] = uid
        h["status"] = "RELEASED"
        touch(h)
        # Trim the affected units off the lot; the remainder unblocks unless
        # the trim consumed the entire lot.
        lot["qty_on_hand"] -= h["affected_units"]
        lot["qty_scrapped"] += h["affected_units"]
        if lot["qty_on_hand"] == 0 and lot["qty_reserved_rework"] == 0:
            lot["status"] = "DEPLETED"
        else:
            lot["status"] = "ACTIVE"
        touch(lot)
        recompute_window_of_lot(lot)
    elif action == "SCRAP":
        h["disposition_by"] = uid
        h["status"] = "SCRAPPED"
        touch(h)
        # Write the lot off entirely: all remaining on-hand units move to
        # qty_scrapped.
        lot["qty_scrapped"] += lot["qty_on_hand"]
        lot["qty_on_hand"] = 0
        lot["status"] = "SCRAPPED"
        touch(lot)
        recompute_window_of_lot(lot)
    else:  # REWORK
        h["disposition_by"] = uid
        h["status"] = "REWORK_PENDING"
        touch(h)
        # The lot remains BLOCKED and becomes eligible as a REWORK run source.
    return success_object(hold_json(h))
