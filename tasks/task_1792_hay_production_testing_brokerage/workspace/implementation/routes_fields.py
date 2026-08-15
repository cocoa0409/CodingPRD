"""Fields and Cuttings: creation, weather-guarded mark-cut, abandon cascade."""

from flask import Blueprint, request

from auth import authorize
from db import store, new_id, stamp_new, touch
from domain import FORAGE_TYPES, window_open_on, grower_region_of_cutting
from errors import (
    ApiError, ERR_GROWER_NOT_FOUND, ERR_FIELD_NOT_FOUND, ERR_CUTTING_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP, ERR_INVALID_STATE, ERR_CUTTING_NOT_OPEN,
    ERR_CUTTING_WINDOW_RANGE, ERR_FIELD_WINDOW_OVERLAP,
    ERR_DUPLICATE_CUTTING_NUMBER, ERR_GROWER_SUSPENDED,
)
from response import success
from serializers import field_out, cutting_out
from util import (
    req, as_str, as_int, as_bool, as_enum, as_number, as_date,
    get_body, paginate, sorted_by_created, invalid,
)

bp = Blueprint("fields", __name__)


# --- Field ------------------------------------------------------------------

@bp.post("/api/fields")
def create_field():
    uid, role = authorize(["PlatformAdmin", "Grower"])
    body = get_body()
    grower_id = as_str(req(body, "grower_id"), "grower_id")
    name = as_str(req(body, "name"), "name")
    acres = as_number(req(body, "acres"), "acres")
    if acres <= 0:
        invalid("acres must be greater than zero")
    forage_type = as_enum(req(body, "forage_type"), "forage_type", FORAGE_TYPES)
    irrigated = False
    if "irrigated" in body and body["irrigated"] is not None:
        irrigated = as_bool(body["irrigated"], "irrigated")
    grower = store["growers"].get(grower_id)
    if grower is None:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "grower not found")
    if role == "Grower" and grower_id != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only create fields for themselves")
    if grower["status"] != "ACTIVE":
        raise ApiError(ERR_GROWER_SUSPENDED, 422, "referenced grower is suspended")
    field = stamp_new({
        "id": new_id(),
        "grower_id": grower_id,
        "name": name,
        "acres": float(acres),
        "forage_type": forage_type,
        "irrigated": irrigated,
    })
    store["fields"][field["id"]] = field
    return success(field_out(field), "object", 201)


@bp.get("/api/fields")
def list_fields():
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    items = list(store["fields"].values())
    grower_filter = request.args.get("grower_id")
    if role == "Grower":
        grower_filter = uid  # growers see only their own fields
    if grower_filter is not None:
        items = [f for f in items if f["grower_id"] == grower_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([field_out(f) for f in page], "array", 200, meta)


@bp.get("/api/fields/<field_id>")
def get_field(field_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    field = store["fields"].get(field_id)
    if field is None:
        raise ApiError(ERR_FIELD_NOT_FOUND, 404, "field not found")
    if role == "Grower" and field["grower_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only read their own fields")
    return success(field_out(field), "object", 200)


# --- Cutting ----------------------------------------------------------------

@bp.post("/api/cuttings")
def create_cutting():
    uid, role = authorize(["PlatformAdmin", "Grower"])
    body = get_body()
    field_id = as_str(req(body, "field_id"), "field_id")
    cutting_number = as_int(req(body, "cutting_number"), "cutting_number")
    season_year = as_int(req(body, "season_year"), "season_year")
    start = as_date(req(body, "planned_window_start"), "planned_window_start")
    end = as_date(req(body, "planned_window_end"), "planned_window_end")
    if end < start:
        invalid("planned_window_end must be on or after planned_window_start")
    field = store["fields"].get(field_id)
    if field is None:
        raise ApiError(ERR_FIELD_NOT_FOUND, 404, "field not found")
    if role == "Grower" and field["grower_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only schedule cuttings on their own fields")
    # Priority 8: half-open [start, end) overlap against non-ABANDONED cuttings
    # on the same field in the same season; adjacency (prev.end == next.start) is allowed.
    siblings = [
        c for c in store["cuttings"].values()
        if c["field_id"] == field_id and c["season_year"] == season_year and c["status"] != "ABANDONED"
    ]
    for other in siblings:
        if start < other["planned_window_end"] and other["planned_window_start"] < end:
            raise ApiError(ERR_FIELD_WINDOW_OVERLAP, 409,
                           "planned window overlaps an existing cutting on this field and season")
    # Priority 10: (cutting_number, field_id, season_year) unique among non-ABANDONED.
    for other in siblings:
        if other["cutting_number"] == cutting_number:
            raise ApiError(ERR_DUPLICATE_CUTTING_NUMBER, 409,
                           "cutting_number already used on this field for this season")
    cutting = stamp_new({
        "id": new_id(),
        "field_id": field_id,
        "cutting_number": cutting_number,
        "season_year": season_year,
        "planned_window_start": start,
        "planned_window_end": end,
        "actual_cut_date": None,
        "status": "SCHEDULED",
    })
    store["cuttings"][cutting["id"]] = cutting
    return success(cutting_out(cutting), "object", 201)


@bp.get("/api/cuttings")
def list_cuttings():
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    items = list(store["cuttings"].values())
    field_filter = request.args.get("field_id")
    status_filter = request.args.get("status")
    if field_filter is not None:
        items = [c for c in items if c["field_id"] == field_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    if role == "Grower":
        own_fields = {f["id"] for f in store["fields"].values() if f["grower_id"] == uid}
        items = [c for c in items if c["field_id"] in own_fields]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([cutting_out(c) for c in page], "array", 200, meta)


@bp.get("/api/cuttings/<cutting_id>")
def get_cutting(cutting_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    cutting = store["cuttings"].get(cutting_id)
    if cutting is None:
        raise ApiError(ERR_CUTTING_NOT_FOUND, 404, "cutting not found")
    if role == "Grower":
        field = store["fields"].get(cutting["field_id"])
        if field is None or field["grower_id"] != uid:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only read their own cuttings")
    return success(cutting_out(cutting), "object", 200)


@bp.post("/api/cuttings/<cutting_id>/mark-cut")
def mark_cut(cutting_id):
    uid, role = authorize(["PlatformAdmin", "Grower"])
    body = get_body()
    actual_cut_date = as_date(req(body, "actual_cut_date"), "actual_cut_date")
    cutting = store["cuttings"].get(cutting_id)
    if cutting is None:
        raise ApiError(ERR_CUTTING_NOT_FOUND, 404, "cutting not found")
    # Priority 5: ownership.
    if role == "Grower":
        field = store["fields"].get(cutting["field_id"])
        if field is None or field["grower_id"] != uid:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only mark their own cuttings")
    # Priority 6: must be WINDOW_OPEN, and the trailing 3 calendar days ending
    # on actual_cut_date must each be dry and drying-capable.
    if cutting["status"] != "WINDOW_OPEN":
        raise ApiError(ERR_CUTTING_NOT_OPEN, 409, "cutting is not WINDOW_OPEN")
    region = grower_region_of_cutting(cutting)
    if not window_open_on(region, actual_cut_date):
        raise ApiError(ERR_CUTTING_NOT_OPEN, 409,
                       "trailing 3 days ending on the cut date are not all dry and drying-capable")
    # Priority 8: actual_cut_date within [planned_window_start, planned_window_end] inclusive.
    if not (cutting["planned_window_start"] <= actual_cut_date <= cutting["planned_window_end"]):
        raise ApiError(ERR_CUTTING_WINDOW_RANGE, 422,
                       "actual_cut_date is outside the planned window")
    cutting["actual_cut_date"] = actual_cut_date
    cutting["status"] = "CUT"
    touch(cutting)
    return success(cutting_out(cutting), "object", 200)


@bp.post("/api/cuttings/<cutting_id>/abandon")
def abandon_cutting(cutting_id):
    uid, role = authorize(["PlatformAdmin", "Grower"])
    cutting = store["cuttings"].get(cutting_id)
    if cutting is None:
        raise ApiError(ERR_CUTTING_NOT_FOUND, 404, "cutting not found")
    if role == "Grower":
        field = store["fields"].get(cutting["field_id"])
        if field is None or field["grower_id"] != uid:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only abandon their own cuttings")
    if cutting["status"] not in ("SCHEDULED", "WINDOW_OPEN"):
        raise ApiError(ERR_INVALID_STATE, 409, "only SCHEDULED or WINDOW_OPEN cuttings may be abandoned")
    cutting["status"] = "ABANDONED"
    touch(cutting)
    # Conditional cascade: cancel baling orders awaiting execution for this cutting.
    for order in list(store["baling_service_orders"].values()):
        if order["cutting_id"] == cutting["id"] and order["status"] in ("REQUESTED", "SCHEDULED"):
            order["status"] = "CANCELLED"
            touch(order)
    return success(cutting_out(cutting), "object", 200)
