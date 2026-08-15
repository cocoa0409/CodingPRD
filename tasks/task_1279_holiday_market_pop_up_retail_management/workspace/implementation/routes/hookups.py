"""UtilityHookup endpoints (PRD 3.5)."""
from flask import Blueprint

import db
from errors import ApiError, invalid_state, posture_forbidden
from middleware import auth, require_roles
from response import success
from services import posture
from services.core import (
    HOOKUP_TYPES,
    arg,
    as_enum,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("hookups", __name__)

CREW = ("UtilityCrew",)
GET_ROLES = ("MarketOperator", "UtilityCrew")
ELECTRIC = ("ELECTRIC_15A", "ELECTRIC_30A")


def _resolve(marketId, hookupId):
    get_market(marketId)
    return get_child("hookups", hookupId, marketId)


def _active_assignment_for_booth(market_id, booth_id):
    for a in db.STORES["assignments"].values():
        if (
            a["market_id"] == market_id
            and a["booth_id"] == booth_id
            and a["status"] == "ACTIVE"
        ):
            return a
    return None


def _latest_assignment_for_booth(market_id, booth_id):
    best = None
    for a in db.STORES["assignments"].values():
        if a["market_id"] == market_id and a["booth_id"] == booth_id:
            if best is None or (a["created_at"], a["_seq"]) > (best["created_at"], best["_seq"]):
                best = a
    return best


@bp.post("/markets/<marketId>/hookups")
def create_hookup(marketId):
    user = auth()
    require_roles(user, CREW)
    get_market(marketId)
    data = body()
    booth_id = as_str(required(data, "booth_id"), "booth_id")
    booth = get_child("booths", booth_id, marketId)
    hookup_type = as_enum(required(data, "hookup_type"), "hookup_type", HOOKUP_TYPES)
    if hookup_type in ELECTRIC and not booth["has_power"]:
        raise ApiError(
            "ERR_BOOTH_UNAVAILABLE", "booth lacks has_power for ELECTRIC_* hookups", 409
        )
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "booth_id": booth_id,
            "hookup_type": hookup_type,
            "amps_drawn": 0,
            "status": "REQUESTED",
        }
    )
    db.STORES["hookups"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/hookups/<hookupId>")
def get_hookup(marketId, hookupId):
    user = auth()
    require_roles(user, GET_ROLES)
    return success(serialize(_resolve(marketId, hookupId)))


@bp.get("/markets/<marketId>/hookups")
def list_hookups(marketId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    status = arg("status")
    hookup_type = arg("hookup_type")
    booth_id = arg("booth_id")
    records = []
    for h in db.STORES["hookups"].values():
        if h["market_id"] != marketId:
            continue
        if status is not None and h["status"] != status:
            continue
        if hookup_type is not None and h["hookup_type"] != hookup_type:
            continue
        if booth_id is not None and h["booth_id"] != booth_id:
            continue
        records.append(h)
    return list_response(records)


@bp.post("/markets/<marketId>/hookups/<hookupId>/install")
def install_hookup(marketId, hookupId):
    user = auth()
    require_roles(user, CREW)
    market = get_market(marketId)
    hookup = get_child("hookups", hookupId, marketId)
    if posture.derive_posture(market) != "SETUP":
        raise posture_forbidden("hookup installation requires SETUP posture")
    if hookup["status"] != "REQUESTED":
        raise invalid_state("only a REQUESTED hookup can be installed")
    if hookup["hookup_type"] in ELECTRIC:
        booth = db.STORES["booths"].get(hookup["booth_id"])
        if booth is None or not booth["has_power"]:
            raise ApiError(
                "ERR_BOOTH_UNAVAILABLE", "booth lacks has_power for ELECTRIC_* hookups", 409
            )
    hookup["status"] = "INSTALLED"
    touch(hookup)
    return success(serialize(hookup))


@bp.post("/markets/<marketId>/hookups/<hookupId>/energize")
def energize_hookup(marketId, hookupId):
    user = auth()
    require_roles(user, CREW)
    market = get_market(marketId)
    hookup = get_child("hookups", hookupId, marketId)
    if posture.derive_posture(market) not in ("SETUP", "OPEN"):
        raise posture_forbidden("energizing requires SETUP or OPEN posture")
    if hookup["status"] != "INSTALLED":
        raise invalid_state("only an INSTALLED hookup can be energized")
    if hookup["hookup_type"] == "PROPANE":
        assignment = _active_assignment_for_booth(marketId, hookup["booth_id"])
        has_permit = False
        if assignment is not None:
            has_permit = any(
                p["market_id"] == marketId
                and p["assignment_id"] == assignment["id"]
                and p["permit_type"] == "PROPANE_HEAT"
                and p["status"] == "ACTIVE"
                for p in db.STORES["permits"].values()
            )
        if not has_permit:
            raise ApiError(
                "ERR_PERMIT_REQUIRED",
                "energizing PROPANE requires an ACTIVE PROPANE_HEAT permit for the booth's ACTIVE assignment",
                409,
            )
    hookup["status"] = "ENERGIZED"
    touch(hookup)
    return success(serialize(hookup))


@bp.post("/markets/<marketId>/hookups/<hookupId>/decommission")
def decommission_hookup(marketId, hookupId):
    user = auth()
    require_roles(user, CREW)
    market = get_market(marketId)
    hookup = get_child("hookups", hookupId, marketId)
    if hookup["status"] != "ENERGIZED":
        raise invalid_state("only an ENERGIZED hookup can be decommissioned")
    p = posture.derive_posture(market)
    assignment = _latest_assignment_for_booth(marketId, hookup["booth_id"])
    assignment_gone = assignment is not None and assignment["status"] in (
        "RELEASED",
        "FORFEITED",
    )
    if p not in ("WEATHER_ALERT", "CLOSED_SEASON") and not assignment_gone:
        raise posture_forbidden(
            "decommission requires WEATHER_ALERT/CLOSED_SEASON posture or a RELEASED/FORFEITED assignment"
        )
    hookup["status"] = "DECOMMISSIONED"
    touch(hookup)
    return success(serialize(hookup))
