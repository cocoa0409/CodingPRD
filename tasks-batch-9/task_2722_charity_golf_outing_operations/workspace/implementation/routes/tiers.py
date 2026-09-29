"""PackageTier endpoints (PRD 3.2)."""

from flask import Blueprint

import derive
import enums
import serial
import store
import validate
from auth import (CHARITY_TREASURER, PARTICIPANT, SPONSORSHIP_MANAGER,
                  TOURNAMENT_DIRECTOR, auth)
from envelope import created, ok, paginate
from errors import fail
from lookup import outing as get_outing
from lookup import tier as get_tier

bp = Blueprint("tiers", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER,
              PARTICIPANT)

CREATE_FIELDS = ("outing_id", "code", "kind", "price_cents", "player_slots",
                 "gsv_cents", "inventory_cap", "entitled_asset_type",
                 "entitled_asset_count")


@bp.post("/outing-ops/package-tiers")
def create_tier():
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    fields = {
        "outing_id": outing_id,
        "code": validate.req_str(body, "code"),
        "kind": validate.req_enum(body, "kind", enums.TIER_KIND),
        "price_cents": validate.req_money(body, "price_cents"),
        "player_slots": validate.req_int(body, "player_slots", minimum=0, maximum=4),
        "gsv_cents": validate.opt_money(body, "gsv_cents", 0),
        "inventory_cap": validate.opt_int(body, "inventory_cap", default=999, minimum=1),
        "entitled_asset_type": validate.opt_enum(
            body, "entitled_asset_type", enums.ENTITLED_ASSET_TYPE, default="NONE"),
        "entitled_asset_count": validate.opt_int(
            body, "entitled_asset_count", default=0, minimum=0),
        "sold_count": 0,
    }
    get_outing(outing_id)
    for tier in derive.tiers_of(outing_id):
        if tier["code"] == fields["code"]:
            fail("ERR_TIER_CODE_DUPLICATE",
                 "The outing already publishes tier code %s." % fields["code"])
    row = store.new_row("PackageTier", fields)
    return created(serial.dump(row))


@bp.get("/outing-ops/package-tiers/<row_id>")
def read_tier(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_tier(row_id)))


@bp.get("/outing-ops/package-tiers")
def list_tiers():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    kind = validate.q_enum("kind", enums.TIER_KIND)
    rows = store.sorted_rows(store.package_tiers.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return paginate(rows, limit, offset, serial.dump)
