"""ZoneClearance endpoints."""
from flask import Blueprint, request
from decimal import Decimal

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_referential, err_not_found,
)
from services.core import (
    serialize_zone_clearance, get_zone_clearance, get_zone_clearance_by_id,
    get_market, get_distributor, new_entity_common, touch,
)
from util import parse_dt, iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("zones", __name__)


def _z_scope(z, did):
    m = db.markets.get(z["market_id"])
    return m and m["distributor_id"] == did


@bp.route("/distributors/<did>/markets/<mid>/zone-clearances", methods=["POST"])
@require_roles("Booker")
def create_zone_clearance(did, mid, _user_id, _role):
    get_market(did, mid)
    body = get_json_body()
    require_fields(body, ["film_id", "theatre_id", "clearance_radius_km",
                          "effective_from_utc", "effective_until_utc"])
    film = db.films.get(body["film_id"])
    if not film or film["distributor_id"] != did:
        raise err_referential("film_id not resolvable")
    theatre = db.theatres.get(body["theatre_id"])
    if not theatre or theatre["distributor_id"] != did:
        raise err_referential("theatre_id not resolvable")
    ef = parse_dt(body["effective_from_utc"])
    eu = parse_dt(body["effective_until_utc"])
    if ef is None or eu is None:
        raise err_invalid_request("effective_from_utc/until_utc must be ISO 8601")
    try:
        radius = Decimal(str(body["clearance_radius_km"]))
    except Exception:
        raise err_invalid_request("clearance_radius_km must be numeric")
    parent_id = body.get("parent_dispute_id")
    if parent_id is not None:
        parent = db.zone_clearances.get(parent_id)
        if not parent:
            raise err_referential("parent_dispute_id not resolvable")
    common = new_entity_common()
    z = {
        **common,
        "market_id": mid,
        "film_id": body["film_id"],
        "theatre_id": body["theatre_id"],
        "clearance_radius_km": radius,
        "effective_from_utc": iso_from_dt(ef),
        "effective_until_utc": iso_from_dt(eu),
        "parent_dispute_id": parent_id,
        "status": "GRANTED",
        "granted_by_user_id": _user_id,
    }
    db.zone_clearances[z["id"]] = z
    return success_object(serialize_zone_clearance(z), 201)


@bp.route("/distributors/<did>/markets/<mid>/zone-clearances/<zid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def read_zone_clearance(did, mid, zid, _user_id, _role):
    return success_object(serialize_zone_clearance(get_zone_clearance(did, mid, zid)))


@bp.route("/distributors/<did>/markets/<mid>/zone-clearances", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_zone_clearances_market(did, mid, _user_id, _role):
    get_market(did, mid)
    items = [z for z in db.zone_clearances.values() if z["market_id"] == mid]
    filters = {}
    for k in ("film_id", "theatre_id", "status", "market_id", "parent_dispute_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_zone_clearance, filters)


@bp.route("/distributors/<did>/zone-clearances", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_zone_clearances_distributor(did, _user_id, _role):
    get_distributor(did)
    items = [z for z in db.zone_clearances.values() if _z_scope(z, did)]
    filters = {}
    for k in ("film_id", "theatre_id", "market_id", "status", "parent_dispute_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_zone_clearance, filters)


@bp.route("/distributors/<did>/films/<fid>/zone-clearances", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_zone_clearances_film(did, fid, _user_id, _role):
    from services.core import get_film
    get_film(did, fid)
    items = [z for z in db.zone_clearances.values() if z["film_id"] == fid and _z_scope(z, did)]
    return paginate_list(items, serialize_zone_clearance)


@bp.route("/distributors/<did>/theatres/<tid>/zone-clearances", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_zone_clearances_theatre(did, tid, _user_id, _role):
    from services.core import get_theatre
    get_theatre(did, tid)
    items = [z for z in db.zone_clearances.values() if z["theatre_id"] == tid and _z_scope(z, did)]
    return paginate_list(items, serialize_zone_clearance)


@bp.route("/distributors/<did>/zone-clearances/<zid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def read_zone_clearance_by_id(did, zid, _user_id, _role):
    return success_object(serialize_zone_clearance(get_zone_clearance_by_id(did, zid)))


@bp.route("/distributors/<did>/zone-clearances/<zid>/children", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_zone_clearance_children(did, zid, _user_id, _role):
    get_zone_clearance_by_id(did, zid)
    items = [z for z in db.zone_clearances.values()
             if z.get("parent_dispute_id") == zid and _z_scope(z, did)]
    return paginate_list(items, serialize_zone_clearance)


@bp.route("/distributors/<did>/markets/<mid>/zone-clearances/<zid>/challenge", methods=["POST"])
@require_roles("Exhibitor")
def challenge_zone_clearance(did, mid, zid, _user_id, _role):
    z = get_zone_clearance(did, mid, zid)
    if z["status"] != "GRANTED":
        raise err_invalid_state("ZoneClearance must be GRANTED")
    # Challenger must differ from granted theatre (compare to user who granted)
    if z.get("granted_by_user_id") == _user_id:
        raise err_invalid_request("Challenger must differ from granted theatre's user")
    z["status"] = "CHALLENGED"
    touch(z)
    return success_object(serialize_zone_clearance(z))


@bp.route("/distributors/<did>/markets/<mid>/zone-clearances/<zid>/rule", methods=["POST"])
@require_roles("Booker")
def rule_zone_clearance(did, mid, zid, _user_id, _role):
    z = get_zone_clearance(did, mid, zid)
    body = get_json_body()
    require_fields(body, ["ruling"])
    ruling = body["ruling"]
    if ruling not in ("UPHELD", "OVERRULED"):
        raise err_invalid_request("ruling must be UPHELD or OVERRULED")
    if z["status"] != "CHALLENGED":
        raise err_invalid_state("ZoneClearance must be CHALLENGED")
    if ruling == "UPHELD":
        z["status"] = "UPHELD"
        touch(z)
        return success_object(serialize_zone_clearance(z))
    # OVERRULED
    z["status"] = "OVERRULED"
    touch(z)
    # Create superseding clearance
    common = new_entity_common()
    sup = {
        **common,
        "market_id": z["market_id"],
        "film_id": z["film_id"],
        "theatre_id": z["theatre_id"],
        "clearance_radius_km": z["clearance_radius_km"],
        "effective_from_utc": z["effective_from_utc"],
        "effective_until_utc": z["effective_until_utc"],
        "parent_dispute_id": z["id"],
        "status": "GRANTED",
        "granted_by_user_id": _user_id,
    }
    db.zone_clearances[sup["id"]] = sup
    # Cancel PROPOSED/COUNTERED bookings for original theatre
    for b in db.booking_agreements.values():
        if b["theatre_id"] == z["theatre_id"] and b["deal_status"] in ("PROPOSED", "COUNTERED"):
            b["deal_status"] = "CANCELLED"
            touch(b)
    return success_object(serialize_zone_clearance(z))
