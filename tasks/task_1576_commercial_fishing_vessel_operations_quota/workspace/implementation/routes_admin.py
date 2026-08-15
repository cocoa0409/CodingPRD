"""Routes: logical clock, vessels, permits, quota holdings, season openings."""

from flask import Blueprint, request

from errors import ApiError
import store
from common import (
    ALL_ROLES,
    auth,
    body,
    f_dt,
    f_enum,
    f_int,
    f_str,
    get_holding,
    get_opening,
    get_permit,
    get_vessel,
    list_response,
    make_entity,
    ok_object,
    pub,
    require_roles,
    touch,
)
import domain
from store import iso, parse_dt

bp = Blueprint("admin", __name__)

REGULATOR = ["FisheriesRegulator"]
COVERAGE_CLASSES = ["FULL", "PARTIAL", "EXEMPT"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_uid, role = auth()
    require_roles(role, REGULATOR)
    payload = body()
    target = f_dt(payload, "to_iso8601")
    if target <= store.db.clock:
        raise ApiError(
            400,
            "ERR_CLOCK_REGRESSION",
            "to_iso8601 must be later than the current logical clock",
        )
    domain.advance_clock(target)
    return ok_object({"current_utc": iso(store.db.clock)})


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------

@bp.route("/vessels", methods=["POST"])
def create_vessel():
    _, role = auth()
    require_roles(role, REGULATOR)
    payload = body()
    vessel_name = f_str(payload, "vessel_name")
    license_number = f_str(payload, "license_number")
    home_port = f_str(payload, "home_port")
    length_ft = f_int(payload, "length_ft")
    coverage = f_enum(payload, "observer_coverage_class", COVERAGE_CLASSES)
    vms_unit_id = payload.get("vms_unit_id")
    if vms_unit_id is not None and not isinstance(vms_unit_id, str):
        raise ApiError(400, "ERR_INVALID_REQUEST", "vms_unit_id must be a string")
    if length_ft <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "length_ft must be > 0")
    if any(v["license_number"] == license_number for v in store.db.vessels.values()):
        raise ApiError(409, "ERR_DUPLICATE_LICENSE", "license_number already registered")
    vessel = make_entity(
        {
            "vessel_name": vessel_name,
            "license_number": license_number,
            "home_port": home_port,
            "length_ft": length_ft,
            "observer_coverage_class": coverage,
            "vms_unit_id": vms_unit_id,
            "compliance_points": 100,
            "status": "REGISTERED",
        }
    )
    store.db.vessels[vessel["id"]] = vessel
    return ok_object(pub(vessel), 201)


@bp.route("/vessels", methods=["GET"])
def list_vessels():
    auth()
    return list_response(
        store.db.vessels.values(), [("status", request.args.get("status"))]
    )


@bp.route("/vessels/<rid>", methods=["GET"])
def get_one_vessel(rid):
    auth()
    return ok_object(pub(get_vessel(rid)))


@bp.route("/vessels/<rid>/activate", methods=["POST"])
def activate_vessel(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    vessel = get_vessel(rid)
    if vessel["status"] != "REGISTERED":
        raise ApiError(409, "ERR_VESSEL_NOT_ACTIVE", "activate requires REGISTERED status")
    vessel["status"] = "ACTIVE"
    touch(vessel)
    return ok_object(pub(vessel))


@bp.route("/vessels/<rid>/reinstate", methods=["POST"])
def reinstate_vessel(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    vessel = get_vessel(rid)
    if vessel["status"] != "SUSPENDED":
        raise ApiError(409, "ERR_VESSEL_NOT_ACTIVE", "reinstate requires SUSPENDED status")
    if vessel["compliance_points"] < 50:
        raise ApiError(
            409,
            "ERR_COMPLIANCE_TOO_LOW",
            "reinstate requires compliance_points >= 50",
        )
    vessel["status"] = "ACTIVE"
    touch(vessel)
    for p in store.db.permits.values():
        if (
            p["vessel_id"] == vessel["id"]
            and p["status"] == "SUSPENDED"
            and parse_dt(p["valid_to"]) > store.db.clock
        ):
            p["status"] = "ISSUED"
            touch(p)
    return ok_object(pub(vessel))


@bp.route("/vessels/<rid>/decommission", methods=["POST"])
def decommission_vessel(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    vessel = get_vessel(rid)
    if vessel["status"] not in ("REGISTERED", "ACTIVE", "SUSPENDED"):
        raise ApiError(
            409, "ERR_VESSEL_NOT_ACTIVE", "vessel is already decommissioned"
        )
    open_trip = any(
        t["vessel_id"] == vessel["id"]
        and t["status"] in ("PLANNED", "DEPARTED", "RETURNED", "LANDING_FINALIZED")
        for t in store.db.trips.values()
    )
    if open_trip:
        raise ApiError(
            409, "ERR_VESSEL_HAS_OPEN_TRIPS", "vessel has trips in an open status"
        )
    vessel["status"] = "DECOMMISSIONED"
    touch(vessel)
    for p in store.db.permits.values():
        if p["vessel_id"] == vessel["id"] and p["status"] in ("ISSUED", "SUSPENDED"):
            p["status"] = "REVOKED"
            touch(p)
    return ok_object(pub(vessel))


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------

@bp.route("/vessels/<rid>/permits", methods=["POST"])
def create_permit(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    vessel = get_vessel(rid)
    payload = body()
    fishery = f_enum(payload, "fishery_code", domain.FISHERY_CODES)
    gear = f_enum(payload, "gear_type", domain.GEAR_TYPES)
    valid_from = f_dt(payload, "valid_from")
    valid_to = f_dt(payload, "valid_to")
    if valid_to <= valid_from:
        raise ApiError(
            400, "ERR_INVALID_TIME_WINDOW", "valid_to must be later than valid_from"
        )
    permit = make_entity(
        {
            "vessel_id": vessel["id"],
            "fishery_code": fishery,
            "gear_type": gear,
            "valid_from": iso(valid_from),
            "valid_to": iso(valid_to),
            "status": "ISSUED",
        }
    )
    store.db.permits[permit["id"]] = permit
    return ok_object(pub(permit), 201)


@bp.route("/vessels/<rid>/permits", methods=["GET"])
def list_permits(rid):
    auth()
    get_vessel(rid)
    items = [p for p in store.db.permits.values() if p["vessel_id"] == rid]
    return list_response(items)


@bp.route("/permits/<rid>/revoke", methods=["POST"])
def revoke_permit(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    permit = get_permit(rid)
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise ApiError(
            409, "ERR_PERMIT_NOT_ACTIVE", "revoke requires ISSUED or SUSPENDED status"
        )
    permit["status"] = "REVOKED"
    touch(permit)
    return ok_object(pub(permit))


# ---------------------------------------------------------------------------
# Quota share holdings
# ---------------------------------------------------------------------------

@bp.route("/vessels/<rid>/quota-holdings", methods=["POST"])
def create_holding(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    vessel = get_vessel(rid)
    payload = body()
    fishery = f_enum(payload, "fishery_code", domain.FISHERY_CODES)
    season_year = f_int(payload, "season_year")
    initial_pounds = f_int(payload, "initial_pounds")
    if initial_pounds <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "initial_pounds must be > 0")
    from common import find_holding

    if find_holding(vessel["id"], fishery, season_year) is not None:
        raise ApiError(
            409,
            "ERR_DUPLICATE_HOLDING",
            "a holding already exists for this vessel+fishery_code+season_year",
        )
    holding = make_entity(
        {
            "vessel_id": vessel["id"],
            "fishery_code": fishery,
            "season_year": season_year,
            "initial_pounds": initial_pounds,
            "landed_pounds": 0,
            "status": "ACTIVE",
        }
    )
    store.db.holdings[holding["id"]] = holding
    return ok_object(pub(holding), 201)


@bp.route("/vessels/<rid>/quota-holdings", methods=["GET"])
def list_holdings(rid):
    auth()
    get_vessel(rid)
    items = [h for h in store.db.holdings.values() if h["vessel_id"] == rid]
    return list_response(
        items,
        [
            ("fishery_code", request.args.get("fishery_code")),
            ("season_year", request.args.get("season_year")),
        ],
    )


@bp.route("/quota-holdings/<rid>", methods=["GET"])
def get_one_holding(rid):
    auth()
    return ok_object(pub(get_holding(rid)))


@bp.route("/quota-holdings/<rid>/availability", methods=["GET"])
def holding_availability(rid):
    auth()
    holding = get_holding(rid)
    return ok_object(domain.availability(holding))


# ---------------------------------------------------------------------------
# Season openings
# ---------------------------------------------------------------------------

@bp.route("/season-openings", methods=["POST"])
def create_opening():
    _, role = auth()
    require_roles(role, REGULATOR)
    payload = body()
    fishery = f_enum(payload, "fishery_code", domain.FISHERY_CODES)
    area_code = f_str(payload, "area_code")
    opens_at = f_dt(payload, "opens_at")
    closes_at = f_dt(payload, "closes_at")
    tac_pounds = f_int(payload, "tac_pounds")
    if tac_pounds <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "tac_pounds must be > 0")
    # Temporal rule (tier 7): same fishery+area, closed-interval semantics.
    for o in store.db.openings.values():
        if o["fishery_code"] != fishery or o["area_code"] != area_code:
            continue
        if opens_at <= parse_dt(o["closes_at"]) and closes_at >= parse_dt(o["opens_at"]):
            raise ApiError(
                409,
                "ERR_OPENING_WINDOW_OVERLAP",
                "opening window overlaps another opening for the same fishery+area",
            )
    if closes_at <= opens_at:
        raise ApiError(
            400, "ERR_INVALID_TIME_WINDOW", "closes_at must be later than opens_at"
        )
    opening = make_entity(
        {
            "fishery_code": fishery,
            "area_code": area_code,
            "opens_at": iso(opens_at),
            "closes_at": iso(closes_at),
            "tac_pounds": tac_pounds,
            "landed_against_tac_pounds": 0,
            "status": "SCHEDULED",
        }
    )
    store.db.openings[opening["id"]] = opening
    return ok_object(pub(opening), 201)


@bp.route("/season-openings", methods=["GET"])
def list_openings():
    auth()
    return list_response(
        store.db.openings.values(),
        [
            ("fishery_code", request.args.get("fishery_code")),
            ("area_code", request.args.get("area_code")),
            ("status", request.args.get("status")),
        ],
    )


@bp.route("/season-openings/<rid>", methods=["GET"])
def get_one_opening(rid):
    auth()
    return ok_object(pub(get_opening(rid)))


@bp.route("/season-openings/<rid>/close-early", methods=["POST"])
def close_opening_early(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    opening = get_opening(rid)
    if opening["status"] != "OPEN":
        raise ApiError(409, "ERR_OPENING_NOT_OPEN", "close-early requires OPEN status")
    domain.close_opening_cascade(opening, early=True)
    return ok_object(pub(opening))
