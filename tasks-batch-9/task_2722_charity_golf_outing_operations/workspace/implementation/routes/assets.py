"""SponsorshipAsset endpoints: the sellable inventory (PRD 3.4)."""

from flask import Blueprint

import derive
import enums
import serial
import store
import validate
from auth import CHARITY_TREASURER, SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, auth
from envelope import created, ok, paginate
from errors import fail
from lookup import asset as get_asset
from lookup import outing as get_outing
from store import touch

bp = Blueprint("assets", __name__)

READ_ROLES = (SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, CHARITY_TREASURER)

CREATE_FIELDS = ("outing_id", "asset_type", "label", "list_price_cents",
                 "hole_number", "capacity", "exclusive", "fulfillment_due_at")


@bp.post("/outing-ops/sponsorship-assets")
def create_asset():
    auth((SPONSORSHIP_MANAGER,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    asset_type = validate.req_enum(body, "asset_type", enums.ASSET_TYPE)
    label = validate.req_str(body, "label")
    list_price = validate.req_money(body, "list_price_cents")
    hole_number = validate.opt_int(body, "hole_number", minimum=1, maximum=18)
    capacity = validate.opt_int(body, "capacity", default=1, minimum=1)
    exclusive = validate.opt_bool(body, "exclusive", default=True)
    due_at = validate.opt_ts(body, "fulfillment_due_at")
    if asset_type in ("HOLE_SIGN", "CONTEST") and hole_number is None:
        fail("ERR_INVALID_REQUEST",
             "hole_number is required for a %s unit." % asset_type)
    get_outing(outing_id)
    row = store.new_row("SponsorshipAsset", {
        "outing_id": outing_id,
        "asset_type": asset_type,
        "label": label,
        "hole_number": hole_number,
        "capacity": capacity,
        "exclusive": exclusive,
        "list_price_cents": list_price,
        "fulfillment_due_at": due_at,
        "reserved_count": 0,
        "committed_count": 0,
        "fulfilled_count": 0,
        "remaining_capacity": capacity,
        "status": "AVAILABLE",
    })
    return created(serial.dump(row))


@bp.get("/outing-ops/sponsorship-assets/<row_id>")
def read_asset(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_asset(row_id)))


@bp.get("/outing-ops/sponsorship-assets")
def list_assets():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    asset_type = validate.q_enum("asset_type", enums.ASSET_TYPE)
    status = validate.q_enum("status", enums.ASSET_STATUS)
    rows = store.sorted_rows(store.sponsorship_assets.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if asset_type is not None:
        rows = [r for r in rows if r["asset_type"] == asset_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/sponsorship-assets/<row_id>/inventory")
def asset_inventory(row_id):
    auth((SPONSORSHIP_MANAGER,))
    body = validate.body()
    validate.only_fields(body, ("action",))
    action = validate.req_enum(body, "action", enums.ASSET_ACTIONS)
    asset = get_asset(row_id)
    if action == "WITHDRAW":
        if asset["status"] == "WITHDRAWN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The unit is already withdrawn.")
        if (asset["reserved_count"] or asset["committed_count"]
                or asset["fulfilled_count"]):
            fail("ERR_ASSET_OCCUPIED", "The unit carries occupancy.")
        asset["status"] = "WITHDRAWN"
        asset["remaining_capacity"] = 0
    else:
        if asset["status"] != "WITHDRAWN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "RESTORE is not an edge out of %s." % asset["status"])
        asset["status"] = "AVAILABLE"
        asset["remaining_capacity"] = asset["capacity"]
    touch(asset)
    return ok(serial.dump(asset))
