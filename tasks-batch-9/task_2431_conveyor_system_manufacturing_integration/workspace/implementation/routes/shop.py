"""Shop surface: staging bays, fabrication lots and factory acceptance tests."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from errors import ApiError, bad_request
from lookups import get_lot, get_project, get_staging_bay
from response import list_response, object_response
from serializers import fabrication_lot_out, fat_test_out, staging_bay_out
from services import calculations as calc
from services.cascade import scrap_unwind
from services.scheduling import staging_bay_capacity_exceeded
from store import (
    fat_tests_of,
    new_record,
    ordered,
    segments_of,
    store,
    touch,
)
from validate import (
    body,
    pagination,
    paginate,
    query_filter,
    req_datetime,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("shop", __name__)

LOT_PLANNING_STATES = ("DESIGN_FROZEN", "IN_FABRICATION", "REBASELINE_REQUIRED")
LOT_RELEASE_STATES = ("DESIGN_FROZEN", "IN_FABRICATION")


def _guard_scrapped(lot):
    if lot["status"] == "SCRAPPED":
        raise ApiError("ERR_LOT_SCRAPPED", "A scrapped fabrication lot admits no operations.")


@bp.post("/staging-bays")
def create_staging_bay():
    authenticate(("ShopSupervisor",))
    data = body()
    bay_code = req_str(data, "bay_code")
    concurrent_capacity = req_int(data, "concurrent_capacity", minimum=1)

    bay = new_record()
    bay.update({"bay_code": bay_code, "concurrent_capacity": concurrent_capacity})
    store.staging_bays[bay["id"]] = bay
    return object_response(staging_bay_out(bay), 201)


@bp.post("/fabrication-lots")
def create_fabrication_lot():
    authenticate(("ShopSupervisor",))
    data = body()

    project_id = req_str(data, "project_id")
    lot_code = req_str(data, "lot_code")
    staging_bay_id = req_str(data, "staging_bay_id")
    segment_codes = req_str_array(data, "segment_codes")
    start_raw, start_dt = req_datetime(data, "occupancy_start_utc")
    end_raw, end_dt = req_datetime(data, "occupancy_end_utc")
    if end_dt <= start_dt:
        raise bad_request("Field 'occupancy_end_utc' must be strictly after 'occupancy_start_utc'.")

    project = get_project(project_id)
    bay = get_staging_bay(staging_bay_id)

    known_codes = {segment["segment_code"] for segment in segments_of(project["id"])}
    for code in segment_codes:
        if code not in known_codes:
            raise ApiError(
                "ERR_SEGMENT_NOT_FOUND",
                "segment_code %s does not resolve to a segment of this project." % code,
            )

    # Band 8 - a lot may only be planned against a frozen baseline.
    if project["delivery_status"] not in LOT_PLANNING_STATES:
        raise ApiError(
            "ERR_DESIGN_NOT_FROZEN",
            "Fabrication lots may only be planned once the design is frozen.",
        )

    # Band 12 - closed-interval bay occupancy.
    if staging_bay_capacity_exceeded(bay, start_dt, end_dt):
        raise ApiError(
            "ERR_STAGING_BAY_CAPACITY_EXCEEDED",
            "Staging bay %s would exceed its concurrent capacity of %d."
            % (bay["bay_code"], bay["concurrent_capacity"]),
        )

    lot = new_record()
    lot.update(
        {
            "project_id": project["id"],
            "staging_bay_id": bay["id"],
            "lot_code": lot_code,
            "segment_codes": list(segment_codes),
            "occupancy_start_utc": start_raw,
            "occupancy_end_utc": end_raw,
            "_occ_start_dt": start_dt,
            "_occ_end_dt": end_dt,
            "fat_target_cph": calc.fat_target_for(project),
            "fat_attempt_count": 0,
            "status": "PLANNED",
        }
    )
    store.fabrication_lots[lot["id"]] = lot

    # Planning a replacement lot closes the rebaseline cycle.
    if project["delivery_status"] == "REBASELINE_REQUIRED":
        project["delivery_status"] = "IN_FABRICATION"
    touch(project)

    return object_response(fabrication_lot_out(lot), 201)


@bp.get("/fabrication-lots/<lot_id>")
def read_fabrication_lot(lot_id):
    authenticate(ALL_ROLES)
    lot = get_lot(lot_id)
    return object_response(fabrication_lot_out(lot))


@bp.get("/fabrication-lots")
def list_fabrication_lots():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    project_id = query_filter("project_id")
    staging_bay_id = query_filter("staging_bay_id")
    status = query_filter("status")

    records = ordered(list(store.fabrication_lots.values()))
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if staging_bay_id is not None:
        records = [r for r in records if r["staging_bay_id"] == staging_bay_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_response([fabrication_lot_out(r) for r in page], limit, offset, total)


@bp.post("/fabrication-lots/<lot_id>/start-fabrication")
def start_fabrication(lot_id):
    authenticate(("ShopSupervisor",))
    lot = get_lot(lot_id)
    _guard_scrapped(lot)

    if lot["status"] == "PLANNED":
        project = get_project(lot["project_id"])
        if project["delivery_status"] not in LOT_RELEASE_STATES:
            raise ApiError(
                "ERR_DESIGN_NOT_FROZEN",
                "A lot may only be released while the project's design is frozen.",
            )
        lot["status"] = "FABRICATING"
        touch(lot)
        if project["delivery_status"] == "DESIGN_FROZEN":
            project["delivery_status"] = "IN_FABRICATION"
            touch(project)
    elif lot["status"] == "FAT_FAILED":
        if lot["fat_attempt_count"] >= calc.FAT_MAX_ATTEMPTS:
            raise ApiError(
                "ERR_LOT_INVALID_STATE",
                "The lot has exhausted its factory acceptance attempts.",
            )
        lot["status"] = "FABRICATING"
        touch(lot)
    else:
        raise ApiError(
            "ERR_LOT_INVALID_STATE",
            "A lot in %s cannot be released to the shop floor." % lot["status"],
        )

    return object_response(fabrication_lot_out(lot))


@bp.post("/fabrication-lots/<lot_id>/stage")
def stage_lot(lot_id):
    authenticate(("ShopSupervisor",))
    lot = get_lot(lot_id)
    _guard_scrapped(lot)

    if lot["status"] != "FABRICATING":
        raise ApiError(
            "ERR_LOT_INVALID_STATE", "Only a FABRICATING lot may be staged; this lot is %s." % lot["status"]
        )
    lot["status"] = "STAGED"
    touch(lot)
    return object_response(fabrication_lot_out(lot))


@bp.post("/fat-tests")
def create_fat_test():
    authenticate(("ShopSupervisor",))
    data = body()

    lot_id = req_str(data, "fabrication_lot_id")
    expected = req_int(data, "expected_fabrication_lot_version")
    measured_cph = req_int(data, "measured_cph", minimum=0)
    defect_count = req_int(data, "defect_count", minimum=0)

    lot = get_lot(lot_id)

    # Band 7 - optimistic concurrency on the lot.
    if expected != lot["version"]:
        raise ApiError(
            "ERR_STALE_LOT_VERSION",
            "expected_fabrication_lot_version %d does not match the lot's version %d."
            % (expected, lot["version"]),
        )

    # Band 8 - the lot's own state.
    _guard_scrapped(lot)
    if lot["status"] != "STAGED":
        raise ApiError(
            "ERR_LOT_INVALID_STATE",
            "A factory acceptance test may only be recorded against a STAGED lot; this lot is %s."
            % lot["status"],
        )

    attempt_no = lot["fat_attempt_count"] + 1
    target = lot["fat_target_cph"]
    result = calc.fat_result(measured_cph, defect_count, target)

    test = new_record(versioned=False)
    test.update(
        {
            "fabrication_lot_id": lot["id"],
            "attempt_no": attempt_no,
            "measured_cph": measured_cph,
            "defect_count": defect_count,
            "target_cph_at_test": target,
            "result": result,
        }
    )
    store.fat_tests[test["id"]] = test

    lot["fat_attempt_count"] = attempt_no
    if result == "PASS":
        lot["status"] = "FAT_PASSED"
        touch(lot)
    elif attempt_no < calc.FAT_MAX_ATTEMPTS:
        lot["status"] = "FAT_FAILED"
        touch(lot)
    else:
        # Scrap-unwind cascade: link 1 here, links 2 and 3 in the service.
        lot["status"] = "SCRAPPED"
        touch(lot)
        scrap_unwind(get_project(lot["project_id"]), lot)

    return object_response(fat_test_out(test), 201)


@bp.get("/fabrication-lots/<lot_id>/fat-tests")
def list_fat_tests(lot_id):
    authenticate(ALL_ROLES)
    lot = get_lot(lot_id)
    limit, offset = pagination()
    records = fat_tests_of(lot["id"])  # oldest attempt first
    page, total = paginate(records, limit, offset)
    return list_response([fat_test_out(r) for r in page], limit, offset, total)
