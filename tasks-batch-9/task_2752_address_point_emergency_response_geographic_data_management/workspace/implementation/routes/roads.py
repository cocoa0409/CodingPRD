"""Road centerline maintenance: names, ranges and the validation ladder."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, sorted_rows, touch

bp = Blueprint("roads", __name__)

PARITIES = ["EVEN", "ODD"]
ROAD_STATUSES = ["DRAFT", "VALIDATED", "PUBLISHED", "RETIRED"]


def _check_side_geometry(low, high, parity):
    if low is None or high is None or parity is None:
        raise ApiError("ERR_RANGE_GEOMETRY_INVALID",
                       "A side must supply both of its bounds.")
    if low > high:
        raise ApiError("ERR_RANGE_GEOMETRY_INVALID",
                       "from_addr %d exceeds to_addr %d." % (low, high))
    want = 0 if parity == "EVEN" else 1
    if low % 2 != want or high % 2 != want:
        raise ApiError("ERR_RANGE_GEOMETRY_INVALID",
                       "Bounds %d-%d do not carry the declared parity %s." % (low, high, parity))


def _check_geometry(row):
    _check_side_geometry(row["from_addr_left"], row["to_addr_left"], row["parity_left"])
    _check_side_geometry(row["from_addr_right"], row["to_addr_right"], row["parity_right"])


def _assert_not_frozen(road):
    if calc.open_discrepancy_case_count(road["id"]) > 0:
        raise ApiError("ERR_ROAD_FROZEN_BY_DISCREPANCY")


@bp.post("/road-centerlines")
def create_road():
    v.auth(["GisAnalyst"])
    data = v.body()
    jurisdiction = v.maybe_find("jurisdiction", v.raw_ref(data, "jurisdiction_id"))
    primary_name = v.req_str(data, "primary_name", 1, 120)
    v.req_id(data, "jurisdiction_id")
    from_left = v.req_int(data, "from_addr_left", 0, 999999)
    to_left = v.req_int(data, "to_addr_left", 0, 999999)
    parity_left = v.req_enum(data, "parity_left", PARITIES)
    from_right = v.req_int(data, "from_addr_right", 0, 999999)
    to_right = v.req_int(data, "to_addr_right", 0, 999999)
    parity_right = v.req_enum(data, "parity_right", PARITIES)
    if parity_left == parity_right:
        v.bad("parity_right", "must differ from parity_left")

    row = base_record()
    row.update({
        "primary_name": primary_name,
        "normalized_name": calc.normalized_road_name(primary_name),
        "jurisdiction_id": jurisdiction["id"],
        "from_addr_left": from_left,
        "to_addr_left": to_left,
        "parity_left": parity_left,
        "from_addr_right": from_right,
        "to_addr_right": to_right,
        "parity_right": parity_right,
        "status": "DRAFT",
        "qc_dirty": True,
        "retired_at": None,
        "retire_reason": None,
    })
    _check_geometry(row)
    db.roads[row["id"]] = row
    return created(ser.road(row))


@bp.get("/road-centerlines/<identifier>")
def get_road(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("road", identifier)
    return ok(ser.road(row))


@bp.get("/road-centerlines")
def list_roads():
    v.auth(v.ALL_ROLES)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    normalized_name = v.q_str("normalized_name")
    status = v.q_enum("status", ROAD_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.roads.values()))
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if normalized_name is not None:
        rows = [r for r in rows if r["normalized_name"] == normalized_name]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.road(r) for r in page], limit, offset, total)


@bp.patch("/road-centerlines/<identifier>")
def edit_road(identifier):
    v.auth(["GisAnalyst"])
    road = v.find("road", identifier)
    data = v.body()
    expected = v.req_int(data, "expected_road_version")
    primary_name = v.opt_str(data, "primary_name", 1, 120, non_blank=True)
    merged = {
        "from_addr_left": v.opt_int(data, "from_addr_left", 0, 999999, road["from_addr_left"]),
        "to_addr_left": v.opt_int(data, "to_addr_left", 0, 999999, road["to_addr_left"]),
        "parity_left": v.opt_enum(data, "parity_left", PARITIES, road["parity_left"]),
        "from_addr_right": v.opt_int(data, "from_addr_right", 0, 999999, road["from_addr_right"]),
        "to_addr_right": v.opt_int(data, "to_addr_right", 0, 999999, road["to_addr_right"]),
        "parity_right": v.opt_enum(data, "parity_right", PARITIES, road["parity_right"]),
    }
    if merged["parity_left"] == merged["parity_right"]:
        v.bad("parity_right", "must differ from parity_left")

    if road["status"] not in ("DRAFT", "VALIDATED"):
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "A %s centerline cannot be edited." % road["status"])
    if expected != road["version"]:
        raise ApiError("ERR_STALE_ROAD_VERSION",
                       "expected_road_version %d does not match the stored version %d."
                       % (expected, road["version"]))
    _assert_not_frozen(road)
    _check_geometry(merged)

    demoted = road["status"] == "VALIDATED"
    road.update(merged)
    if primary_name is not None:
        road["primary_name"] = primary_name
        road["normalized_name"] = calc.normalized_road_name(primary_name)
    road["qc_dirty"] = True
    if demoted:
        road["status"] = "DRAFT"
    touch(road)
    cascade.pin_staleness_for_road(road)
    if demoted:
        cascade.confidence_refresh(road)
    return ok(ser.road(road))


@bp.post("/road-centerlines/<identifier>/validate")
def validate_road(identifier):
    v.auth(["GisAnalyst"])
    road = v.find("road", identifier)
    if road["status"] != "DRAFT":
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "Only a DRAFT centerline may be validated; this one is %s."
                       % road["status"])
    _assert_not_frozen(road)
    _check_geometry(road)
    conflict = calc.find_range_conflict(road, ("VALIDATED", "PUBLISHED"))
    if conflict is not None:
        own, peer, other = conflict
        raise ApiError("ERR_ROAD_RANGE_OVERLAP",
                       "%s (centerline %s)." % (calc.conflict_detail(own, other), peer["id"]))
    road["status"] = "VALIDATED"
    road["qc_dirty"] = False
    touch(road)
    cascade.pin_staleness_for_road(road)
    cascade.confidence_refresh(road)
    return ok(ser.road(road))


@bp.post("/road-centerlines/<identifier>/publish")
def publish_road(identifier):
    v.auth(["QcCertifier"])
    road = v.find("road", identifier)
    if road["status"] != "VALIDATED":
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "Only a VALIDATED centerline may be published; this one is %s."
                       % road["status"])
    if road["qc_dirty"]:
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "The centerline is qc_dirty and must be re-validated before publication.")
    _assert_not_frozen(road)
    road["status"] = "PUBLISHED"
    touch(road)
    cascade.pin_staleness_for_road(road)
    cascade.confidence_refresh(road)
    return ok(ser.road(road))


@bp.post("/road-centerlines/<identifier>/retire")
def retire_road(identifier):
    v.auth(["GisAnalyst"])
    road = v.find("road", identifier)
    data = v.body()
    reason = v.req_str(data, "retire_reason", 1)
    if road["status"] not in ("DRAFT", "VALIDATED", "PUBLISHED"):
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "A %s centerline cannot be retired." % road["status"])
    _assert_not_frozen(road)

    road["status"] = "RETIRED"
    road["retired_at"] = db.now()
    road["retire_reason"] = reason
    touch(road)
    cascade.pin_staleness_for_road(road)
    cascade.road_retirement_cascade(road)
    return ok(ser.road(road))
