"""Registry routes: clock, associations, landowners, parcels, burn bosses, contractors."""
from flask import Blueprint, request

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    iso,
    ok,
    paginate,
    parse_datetime,
    require_role,
    set_clock,
    stamp_new,
    touch,
)
from domain import (
    get_association,
    get_boss,
    get_contractor,
    get_landowner,
    get_parcel,
    hazard_score,
    landowner_standing,
    run_sweeps,
    ser_association,
    ser_boss,
    ser_contractor,
    ser_landowner,
    ser_parcel,
    ser_assignment,
)

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    v = Validator(data, {"to_iso8601"})
    v.datetime("to_iso8601")
    v.finish()
    target = parse_datetime(data["to_iso8601"])
    set_clock(target)
    run_sweeps()
    return ok({"current_utc": iso(target)})


# ---------------------------------------------------------------------------
# Associations
# ---------------------------------------------------------------------------


@bp.post("/associations")
def create_association():
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    v = Validator(
        data,
        {
            "name",
            "airshed_daily_acres_cap",
            "single_claim_cap_cents",
            "landowner_liability_cap_cents",
            "initial_fund_cents",
        },
    )
    for f in (
        "airshed_daily_acres_cap",
        "single_claim_cap_cents",
        "landowner_liability_cap_cents",
        "initial_fund_cents",
    ):
        v.req(f, int)
        if v.typed(f, int) is not None and v.typed(f, int) < 0:
            v.invalid(f"Field {f} must be >= 0")
    v.req("name", str)
    if v.typed("name", str) is not None and v.typed("name", str).strip() == "":
        v.invalid("Field name must be non-empty")
    v.finish()
    assoc = stamp_new(
        {
            "name": data["name"],
            "airshed_daily_acres_cap": data["airshed_daily_acres_cap"],
            "single_claim_cap_cents": data["single_claim_cap_cents"],
            "landowner_liability_cap_cents": data["landowner_liability_cap_cents"],
            "fund_balance_cents": data["initial_fund_cents"],
        }
    )
    DB["associations"][assoc["id"]] = assoc
    return ok(ser_association(assoc), 201)


@bp.get("/associations/<aid>")
def get_assoc(aid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_association(get_association(aid)))


@bp.post("/associations/<aid>/fund-deposits")
def fund_deposit(aid):
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    assoc = get_association(aid)
    v = Validator(data, {"amount_cents"})
    v.req("amount_cents", int)
    if v.typed("amount_cents", int) is not None and v.typed("amount_cents", int) <= 0:
        v.invalid("amount_cents must be a positive integer")
    v.finish()
    assoc["fund_balance_cents"] += data["amount_cents"]
    touch(assoc)
    return ok(ser_association(assoc))


# ---------------------------------------------------------------------------
# Landowners
# ---------------------------------------------------------------------------


@bp.post("/landowners")
def create_landowner():
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    v = Validator(data, {"name", "contact_email", "liability_waiver_signed"})
    v.req("name", str)
    v.req("contact_email", str)
    v.req("liability_waiver_signed", bool)
    v.finish()
    land = stamp_new(
        {
            "name": data["name"],
            "contact_email": data["contact_email"],
            "liability_waiver_signed": data["liability_waiver_signed"],
            "outstanding_liability_cents": 0,
        }
    )
    DB["landowners"][land["id"]] = land
    return ok(ser_landowner(land), 201)


@bp.get("/landowners/<lid>")
def get_land(lid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_landowner(get_landowner(lid)))


@bp.get("/landowners")
def list_landowners():
    _, role = auth()
    require_role(role, None)
    items = list(DB["landowners"].values())
    standing = request.args.get("standing")
    if standing:
        items = [l for l in items if landowner_standing(l) == standing]
    return paginate(items, ser_landowner)


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------


@bp.post("/parcels")
def create_parcel():
    data = body()
    uid, role = auth()
    require_role(role, {"Landowner"})
    # existence of the referenced landowner
    landowner_id = data.get("landowner_id")
    landowner = None
    if isinstance(landowner_id, str):
        landowner = DB["landowners"].get(landowner_id)
        if landowner is None:
            raise ApiError("ERR_LANDOWNER_NOT_FOUND", 404, "Landowner not found")
    # ownership: landowner_id must equal X-User-ID
    if landowner_id is not None and landowner_id != uid:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", 403, "landowner_id must equal the caller's X-User-ID"
        )
    v = Validator(
        data,
        {
            "landowner_id",
            "name",
            "acreage",
            "fuel_model",
            "slope_class",
            "wui_adjacent",
            "airshed_id",
            "drought_index",
        },
    )
    v.req("landowner_id", str)
    # waiver gate (priority 9) before field-level checks (priority 14)
    if landowner is not None and not landowner["liability_waiver_signed"]:
        raise ApiError(
            "ERR_LANDOWNER_WAIVER_UNSIGNED",
            403,
            "liability_waiver_signed must be true to register parcels",
        )
    v.req("name", str)
    v.req("acreage", int)
    if v.typed("acreage", int) is not None and v.typed("acreage", int) <= 0:
        v.prescription("acreage must be a positive integer")
    v.enum("fuel_model", {"GRASS", "BRUSH", "TIMBER"})
    v.enum("slope_class", {"FLAT", "MODERATE", "STEEP"})
    v.req("wui_adjacent", bool)
    v.req("airshed_id", str)
    v.req("drought_index", int)
    di = v.typed("drought_index", int)
    if di is not None and not (0 <= di <= 30):
        v.invalid("drought_index must be between 0 and 30")
    v.finish()
    parcel = stamp_new(
        {
            "landowner_id": data["landowner_id"],
            "name": data["name"],
            "acreage": data["acreage"],
            "fuel_model": data["fuel_model"],
            "slope_class": data["slope_class"],
            "wui_adjacent": data["wui_adjacent"],
            "airshed_id": data["airshed_id"],
            "drought_index": data["drought_index"],
        }
    )
    parcel["hazard_score"] = hazard_score(parcel)
    DB["parcels"][parcel["id"]] = parcel
    return ok(ser_parcel(parcel), 201)


@bp.get("/parcels/<pid>")
def get_p(pid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_parcel(get_parcel(pid)))


@bp.get("/parcels")
def list_parcels():
    _, role = auth()
    require_role(role, None)
    items = list(DB["parcels"].values())
    landowner_id = request.args.get("landowner_id")
    if landowner_id:
        items = [p for p in items if p["landowner_id"] == landowner_id]
    return paginate(items, ser_parcel)


# ---------------------------------------------------------------------------
# Burn bosses
# ---------------------------------------------------------------------------


@bp.post("/burn-bosses")
def create_boss():
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    v = Validator(data, {"name", "certification_tier"})
    v.req("name", str)
    v.enum("certification_tier", {"RXB1", "RXB2", "RXB3"})
    v.finish()
    boss = stamp_new({"name": data["name"], "certification_tier": data["certification_tier"]})
    DB["bosses"][boss["id"]] = boss
    return ok(ser_boss(boss), 201)


@bp.get("/burn-bosses/<bid>")
def get_b(bid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_boss(get_boss(bid)))


# ---------------------------------------------------------------------------
# Contractors
# ---------------------------------------------------------------------------


@bp.post("/contractors")
def create_contractor():
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    v = Validator(
        data,
        {
            "name",
            "resource_type",
            "capacity_units",
            "personnel_per_unit",
            "day_rate_cents_per_unit",
        },
    )
    v.req("name", str)
    v.enum("resource_type", {"ENGINE", "HAND_CREW", "DOZER", "WATER_TENDER"})
    for f in ("capacity_units", "personnel_per_unit", "day_rate_cents_per_unit"):
        v.req(f, int)
        if v.typed(f, int) is not None and v.typed(f, int) < 0:
            v.invalid(f"Field {f} must be >= 0")
    v.finish()
    contractor = stamp_new(
        {
            "name": data["name"],
            "resource_type": data["resource_type"],
            "capacity_units": data["capacity_units"],
            "personnel_per_unit": data["personnel_per_unit"],
            "day_rate_cents_per_unit": data["day_rate_cents_per_unit"],
            "no_show_count": 0,
        }
    )
    DB["contractors"][contractor["id"]] = contractor
    return ok(ser_contractor(contractor), 201)


@bp.get("/contractors/<cid>")
def get_c(cid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_contractor(get_contractor(cid)))


@bp.get("/contractors")
def list_contractors():
    _, role = auth()
    require_role(role, None)
    items = list(DB["contractors"].values())
    resource_type = request.args.get("resource_type")
    if resource_type:
        items = [c for c in items if c["resource_type"] == resource_type]
    return paginate(items, ser_contractor)


@bp.get("/contractors/<cid>/assignments")
def list_contractor_assignments(cid):
    _, role = auth()
    require_role(role, None)
    contractor = get_contractor(cid)
    items = [a for a in DB["assignments"].values() if a["contractor_id"] == contractor["id"]]
    return paginate(items, ser_assignment)
