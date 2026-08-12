"""Forest tracts and stands."""
from flask import Blueprint

from core import (
    db, new_common, pub, success, require_roles, get_body, check_known,
    f_str, f_num, bad_request, paginate, get_tract, get_stand,
    get_party, err,
)

bp = Blueprint("tracts", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")


@bp.route("/forestry/tracts", methods=["POST"])
@require_roles("Forester")
def create_tract():
    body = get_body()
    # body reference existence first (validated left to right)
    lo = body.get("landowner_id")
    if isinstance(lo, str) and get_party(lo) is None:
        err("ERR_PARTY_NOT_FOUND", 404, "landowner not found: %s" % lo)
    fo = body.get("forester_id")
    if isinstance(fo, str) and fo not in db["foresters"]:
        err("ERR_PARTY_NOT_FOUND", 404, "forester not found: %s" % fo)
    check_known(body, {"name", "county", "total_acres", "landowner_id",
                       "forester_id"})
    name = f_str(body, "name")
    county = f_str(body, "county")
    total_acres = f_num(body, "total_acres", gt=0)
    landowner_id = f_str(body, "landowner_id")
    forester_id = f_str(body, "forester_id")
    if landowner_id not in db["landowners"]:
        err("ERR_PARTY_NOT_FOUND", 404, "landowner not found: %s" % landowner_id)
    if forester_id not in db["foresters"]:
        err("ERR_PARTY_NOT_FOUND", 404, "forester not found: %s" % forester_id)
    ent = new_common({
        "name": name,
        "county": county,
        "total_acres": total_acres,
        "landowner_id": landowner_id,
        "forester_id": forester_id,
        "status": "OPEN",
        "conservation_enrollment_start": None,
        "conservation_enrollment_end": None,
    })
    db["tracts"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/tracts/<tid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_tract_ep(tid):
    return success(pub(get_tract(tid)), 200)


@bp.route("/forestry/tracts", methods=["GET"])
@require_roles(*READ_ROLES)
def list_tracts():
    page, meta = paginate(db["tracts"].values(), {
        "landowner_id": "landowner_id",
        "forester_id": "forester_id",
        "status": "status",
    })
    return success([pub(t) for t in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/stands", methods=["POST"])
@require_roles("Forester")
def create_stand():
    body = get_body()
    tr = body.get("tract_id")
    if isinstance(tr, str):
        get_tract(tr)  # 404 if missing
    check_known(body, {"tract_id", "name", "acres", "primary_species"})
    tract_id = f_str(body, "tract_id")
    tract = get_tract(tract_id)
    name = f_str(body, "name")
    acres = f_num(body, "acres", gt=0)
    primary_species = f_str(body, "primary_species")
    if acres > tract["total_acres"]:
        bad_request("stand acres exceed tract total_acres")
    ent = new_common({
        "tract_id": tract_id,
        "name": name,
        "acres": acres,
        "primary_species": primary_species,
        "certified_cruise_id": None,
    })
    db["stands"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/stands/<sid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_stand_ep(sid):
    return success(pub(get_stand(sid)), 200)


@bp.route("/forestry/stands", methods=["GET"])
@require_roles(*READ_ROLES)
def list_stands():
    page, meta = paginate(db["stands"].values(), {
        "tract_id": "tract_id",
        "certified_cruise_id": "certified_cruise_id",
    })
    return success([pub(s) for s in page], 200, is_array=True, page_meta=meta)
