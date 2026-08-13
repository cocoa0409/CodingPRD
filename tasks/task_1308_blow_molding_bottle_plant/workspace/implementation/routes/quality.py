from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_QUALITY_TEST_LOT_NOT_FOUND, \
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST, \
    ERR_SEGREGATION_OF_DUTIES
from services import touch, ser_quality_test_lot, sorted_rows, hold_order
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("quality_test_lots", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "CustomerQualityRep"]
LOT_STATUSES = {"PENDING", "SAMPLED", "ACCEPTED", "REJECTED", "SCRAPPED",
                "VOIDED"}
TERMINAL = ("ACCEPTED", "SCRAPPED", "VOIDED")


def get_qtl_or_404(lot_id):
    lot = store.quality_test_lots.get(lot_id)
    if lot is None:
        raise_err(ERR_QUALITY_TEST_LOT_NOT_FOUND,
                  "QualityTestLot id does not resolve")
    return lot


@bp.get("/quality-test-lots")
def list_qtls():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    production_run_id = query_filter("production_run_id")
    status = query_filter("status", LOT_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.quality_test_lots.values())
    if production_run_id is not None:
        rows = [l for l in rows if l["production_run_id"] == production_run_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_quality_test_lot(l) for l in page], limit,
                        offset, len(rows))


@bp.get("/quality-test-lots/<lid>")
def get_qtl(lid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_quality_test_lot(get_qtl_or_404(lid)))


@bp.post("/quality-test-lots/<lid>/sample")
def sample_qtl(lid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    lot = get_qtl_or_404(lid)
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING lot can be sampled")
    lot["status"] = "SAMPLED"
    touch(lot)
    return success_object(ser_quality_test_lot(lot))


@bp.post("/quality-test-lots/<lid>/record-results")
def record_results(lid):
    user_id, role = authenticate()
    require_role(role, ["QualityTechnician"])
    body = check_fields(get_body(), {
        "leak_failures": ("int", True),
        "drop_failures": ("int", True),
    })
    lot = get_qtl_or_404(lid)
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] != "SAMPLED":
        raise_err(ERR_INVALID_STATE,
                  "Only a SAMPLED lot can have results recorded")
    if (body["leak_failures"] > lot["sample_size_n"]
            or body["drop_failures"] > lot["sample_size_n"]):
        raise_err(ERR_INVALID_REQUEST,
                  "Failure counts cannot exceed sample_size_n")
    # inclusive-accept boundary, both characteristics independent
    accepted = (body["leak_failures"] <= lot["accept_number_leak"]
                and body["drop_failures"] <= lot["accept_number_drop"])
    lot["leak_failures"] = body["leak_failures"]
    lot["drop_failures"] = body["drop_failures"]
    lot["recorded_by_user_id"] = user_id
    if accepted:
        lot["status"] = "ACCEPTED"
        touch(lot)
    else:
        lot["status"] = "REJECTED"
        touch(lot)
        # QC hold cascade: RUNNING order -> HELD, slots cancelled, line rests
        run = store.production_runs.get(lot["production_run_id"])
        if run is not None:
            order = store.production_orders.get(run["production_order_id"])
            if order is not None and order["status"] == "RUNNING":
                hold_order(order)
    return success_object(ser_quality_test_lot(lot))


@bp.post("/quality-test-lots/<lid>/disposition")
def disposition_qtl(lid):
    user_id, role = authenticate()
    require_role(role, ["QualityTechnician"])
    body = check_fields(get_body(), {
        "action": ("enum", True, {"SCRAP", "REWORK"}),
    })
    lot = get_qtl_or_404(lid)
    # segregation of duties (priority 2): dispositor must differ from recorder
    if (lot["recorded_by_user_id"] is not None
            and lot["recorded_by_user_id"] == user_id):
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Disposition must be performed by a different user than "
                  "the recorder")
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] != "REJECTED":
        raise_err(ERR_INVALID_STATE,
                  "Only a REJECTED lot can be dispositioned")
    lot["dispositioned_by_user_id"] = user_id
    if body["action"] == "SCRAP":
        lot["status"] = "SCRAPPED"
    else:  # REWORK: back to PENDING for another pass
        lot["status"] = "PENDING"
        lot["retest_count"] += 1
        lot["leak_failures"] = None
        lot["drop_failures"] = None
        lot["recorded_by_user_id"] = None
    touch(lot)
    return success_object(ser_quality_test_lot(lot))
