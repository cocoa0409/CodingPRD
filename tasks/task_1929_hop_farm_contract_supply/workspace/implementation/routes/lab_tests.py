"""Lab test endpoints — alpha-acid posting and the regrade cascade (PRD §3.3)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_LAB_TECHNICIAN
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_num, req_enum
from errors import ApiError, ERR_LOT_NOT_DRIED, ERR_PROVISIONAL_REQUIRED, ERR_DUPLICATE_FINAL_TEST
from services.core import (
    base_record_light, touch, public, get_lab_test, get_harvest_lot,
    posted_alpha, regrade_cascade, filtered_sorted, TEST_TYPES,
)

bp = Blueprint("lab_tests", __name__)


@bp.route("/api/lab-tests", methods=["POST"])
def create_lab_test():
    require_roles([ROLE_LAB_TECHNICIAN])
    body = get_body()
    check_unknown_fields(body, {"harvest_lot_id", "test_type", "alpha_pct"})
    harvest_lot_id = req_str(body, "harvest_lot_id")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    alpha_raw = req_num(body, "alpha_pct", gt=0, lte=25)

    lot = get_harvest_lot(harvest_lot_id)

    # the lot must have left the kiln (DRIED or CONSUMED)
    if lot["status"] not in ("DRIED", "CONSUMED"):
        raise ApiError(ERR_LOT_NOT_DRIED, 422,
                       "Harvest lot has not completed the kiln pipeline")

    if test_type == "FINAL":
        has_provisional = any(
            t["harvest_lot_id"] == harvest_lot_id and t["test_type"] == "PROVISIONAL"
            for t in store.lab_tests.values())
        if not has_provisional:
            raise ApiError(ERR_PROVISIONAL_REQUIRED, 422,
                           "A FINAL test requires a prior PROVISIONAL test on the lot")
        has_final = any(
            t["harvest_lot_id"] == harvest_lot_id and t["test_type"] == "FINAL"
            for t in store.lab_tests.values())
        if has_final:
            raise ApiError(ERR_DUPLICATE_FINAL_TEST, 422,
                           "A FINAL test already exists for the harvest lot")

    alpha = posted_alpha(alpha_raw)

    rec = base_record_light()
    rec.update({
        "harvest_lot_id": harvest_lot_id,
        "test_type": test_type,
        "alpha_pct": alpha,
    })
    store.lab_tests[rec["id"]] = rec

    if test_type == "PROVISIONAL":
        # latest posted provisional wins
        lot["alpha_pct_provisional"] = alpha
        touch(lot)
    else:
        lot["alpha_pct_final"] = alpha
        touch(lot)
        regrade_cascade(lot)

    return success_object(public(rec), status=201)


@bp.route("/api/lab-tests/<test_id>", methods=["GET"])
def get_lab_test_endpoint(test_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_lab_test(test_id)))


@bp.route("/api/lab-tests", methods=["GET"])
def list_lab_tests():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.lab_tests.values()), request.args, {
        "harvest_lot_id": ("str", "harvest_lot_id"),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)
