"""Annual FAA inspections."""
from flask import Blueprint

from db import store, base_entity, touch, serialize, month_index
from errors import (
    ApiError, ERR_INSPECTION_NOT_FOUND, ERR_DUPLICATE_INSPECTION_YEAR,
    ERR_VALIDATION_FAILED, ERR_INSPECTION_NOT_BEGINNABLE,
    ERR_INSPECTION_NOT_IN_PROGRESS, ERR_INSPECTION_NOT_CONCLUDABLE,
    ERR_INSPECTION_BLOCKING_NOTIFICATIONS, ERR_NO_VALID_CERTIFIED_DRILL,
    ERR_PROFILE_NOT_COMPLIANT, ERR_PROFILE_NOT_FOUND,
)
from middleware import require, json_body, need_date_str, ALL_ROLES
from response import success, paginated

bp = Blueprint("inspections", __name__)


def get_inspection_or_404(iid):
    i = store.inspections.get(iid)
    if i is None:
        raise ApiError(ERR_INSPECTION_NOT_FOUND, 404, "FAA inspection id does not exist")
    return i


@bp.post("/arff/faa-inspections")
def create_inspection():
    require(["AirportManager"])
    data = json_body()
    year = data.get("inspection_year")
    if isinstance(year, bool) or not isinstance(year, int):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'inspection_year' is required and must be an integer")
    scheduled = need_date_str(data, "scheduled_on")
    if any(i["inspection_year"] == year for i in store.inspections.values()):
        raise ApiError(ERR_DUPLICATE_INSPECTION_YEAR, 409,
                       "An inspection already exists for inspection_year")
    ins = base_entity()
    ins.update({
        "inspection_year": year,
        "scheduled_on": scheduled,
        "findings_count": None,
        "concluded_outcome": None,
        "status": "SCHEDULED",
    })
    store.inspections[ins["id"]] = ins
    return success(serialize(ins), "object", 201)


@bp.get("/arff/faa-inspections")
def list_inspections():
    require(ALL_ROLES)
    return paginated(list(store.inspections.values()))


@bp.get("/arff/faa-inspections/<iid>")
def get_inspection(iid):
    require(ALL_ROLES)
    return success(serialize(get_inspection_or_404(iid)), "object", 200)


@bp.post("/arff/faa-inspections/<iid>/begin")
def begin_inspection(iid):
    require(["FaaInspector"])
    ins = get_inspection_or_404(iid)
    if ins["status"] != "SCHEDULED":
        raise ApiError(ERR_INSPECTION_NOT_BEGINNABLE, 409,
                       "Inspection must be SCHEDULED to begin")
    ins["status"] = "IN_PROGRESS"
    touch(ins)
    return success(serialize(ins), "object", 200)


@bp.post("/arff/faa-inspections/<iid>/issue-findings")
def issue_findings(iid):
    require(["FaaInspector"])
    ins = get_inspection_or_404(iid)
    data = json_body()
    count = data.get("findings_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'findings_count' must be an integer >= 0")
    if ins["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INSPECTION_NOT_IN_PROGRESS, 409,
                       "Inspection must be IN_PROGRESS to issue findings")
    ins["findings_count"] = count
    ins["status"] = "FINDINGS_ISSUED"
    touch(ins)
    return success(serialize(ins), "object", 200)


@bp.post("/arff/faa-inspections/<iid>/conclude")
def conclude_inspection(iid):
    require(["FaaInspector"])
    ins = get_inspection_or_404(iid)
    data = json_body()
    outcome = data.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'outcome' must be PASS or FAIL")
    if ins["status"] != "FINDINGS_ISSUED":
        raise ApiError(ERR_INSPECTION_NOT_CONCLUDABLE, 409,
                       "Inspection must be FINDINGS_ISSUED to conclude")
    if outcome == "PASS":
        if any(n["status"] in ("PENDING", "ACKNOWLEDGED", "OVERDUE")
               for n in store.notifications.values()):
            raise ApiError(ERR_INSPECTION_BLOCKING_NOTIFICATIONS, 422,
                           "An open index downgrade notification blocks conclusion")
        mi_now = month_index(store.clock.date())
        valid_drill = any(
            d["status"] == "CERTIFIED" and d.get("_executed_dt") is not None
            and mi_now - month_index(d["_executed_dt"].date()) <= 12
            for d in store.drills.values()
        )
        if not valid_drill:
            raise ApiError(ERR_NO_VALID_CERTIFIED_DRILL, 422,
                           "No CERTIFIED drill within the preceding 12 calendar months")
        if store.profile is None:
            raise ApiError(ERR_PROFILE_NOT_FOUND, 404, "Airport profile not yet created")
        if store.profile["index_compliance_status"] != "COMPLIANT":
            raise ApiError(ERR_PROFILE_NOT_COMPLIANT, 422,
                           "Profile index_compliance_status must be COMPLIANT")
        ins["concluded_outcome"] = "PASS"
        ins["status"] = "CLOSED_PASS"
    else:
        ins["concluded_outcome"] = "FAIL"
        ins["status"] = "CLOSED_FAIL"
    touch(ins)
    return success(serialize(ins), "object", 200)
