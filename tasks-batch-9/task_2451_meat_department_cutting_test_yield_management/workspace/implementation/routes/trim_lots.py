"""Trim lots, re-work generations and the pound ledger (PRD §3.5, §2.8)."""

from datetime import timedelta

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import REGRIND_GENERATION_LIMIT, rhu
from db import db, make, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import grind

bp = Blueprint("trim_lots", __name__)

LOT_ACTION_ROLES = {"DISCARD": (mw.MEAT_CUTTER,)}
COMMITTABLE = ("AVAILABLE", "PARTIALLY_COMMITTED")


@bp.route("/meat-ops/trim-lots", methods=["POST"])
def create_trim_lot():
    mw.authenticate((mw.MEAT_CUTTER,))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    lot_code = v.field_str(payload, "lot_code", required=True, min_len=2, max_len=24)
    received_lb = v.field_num(payload, "received_lb", required=True, gt=0, places=2)
    pack_date_raw, pack_date = v.field_date(payload, "pack_date", required=True)
    cutting_test_line_id = v.field_id(payload, "cutting_test_line_id")
    source_trim_lot_id = v.field_id(payload, "source_trim_lot_id")

    if (cutting_test_line_id is None) == (source_trim_lot_id is None):
        v.bad("Exactly one of 'cutting_test_line_id' and 'source_trim_lot_id' "
              "must be supplied")

    department = v.resolve("department", department_id)
    source_line = v.resolve_optional("cutting_test_line", cutting_test_line_id)
    source_lot = v.resolve_optional("trim_lot", source_trim_lot_id)

    if source_lot is not None:
        if source_lot["status"] not in COMMITTABLE:
            raise ApiError(errors.ERR_TRIM_LOT_NOT_AVAILABLE, 409,
                           "The source trim lot is %s" % source_lot["status"])
        if source_lot["rework_generation"] >= REGRIND_GENERATION_LIMIT:
            raise ApiError(errors.ERR_PROHIBITED_REGRIND, 422,
                           "The source lot is already a re-work")

    if source_lot is not None:
        if source_lot["department_id"] != department_id:
            raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                           "The source trim lot belongs to another department")
    else:
        test = db.cutting_tests.get(source_line["cutting_test_id"])
        purchase = (db.primal_purchases.get(test["primal_purchase_id"])
                    if test is not None else None)
        if purchase is None or purchase["department_id"] != department_id:
            raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                           "The cutting-test line belongs to another department")

    for existing in db.trim_lots.values():
        if (existing["department_id"] == department_id
                and existing["lot_code"] == lot_code):
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "lot_code is already in use in this department")

    if source_lot is not None:
        country = source_lot["country_of_origin"]
        lean_pct = source_lot["lean_pct"]
        cost_per_lb = source_lot["cost_per_lb_cents"]
        generation = source_lot["rework_generation"] + 1
    else:
        test = db.cutting_tests.get(source_line["cutting_test_id"])
        purchase = db.primal_purchases.get(test["primal_purchase_id"])
        country = purchase["country_of_origin"]
        lean_pct = source_line["lean_pct"]
        cost_per_lb = source_line["allocated_cost_per_lb_cents"]
        generation = 0

    sell_by = pack_date + timedelta(days=int(department["shelf_life_days_ground"]))

    lot = make("TrimLot", {
        "department_id": department_id,
        "lot_code": lot_code,
        "cutting_test_line_id": cutting_test_line_id,
        "source_trim_lot_id": source_trim_lot_id,
        "country_of_origin": country,
        "lean_pct": lean_pct,
        "cost_per_lb_cents": cost_per_lb,
        "received_lb": received_lb,
        "allocated_lb": rhu(0, 2),
        "consumed_lb": rhu(0, 2),
        "discarded_lb": rhu(0, 2),
        "remaining_lb": received_lb,
        "rework_generation": generation,
        "pack_date": pack_date_raw,
        "sell_by_date": sell_by.isoformat(),
        "status": "AVAILABLE",
    })
    db.trim_lots[lot["id"]] = lot
    return object_response(lot, 201)


@bp.route("/meat-ops/trim-lots/<lot_id>", methods=["GET"])
def get_trim_lot(lot_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    return object_response(v.resolve("trim_lot", lot_id))


@bp.route("/meat-ops/trim-lots", methods=["GET"])
def list_trim_lots():
    mw.authenticate(mw.NO_SERVICE_CLERK)
    limit, offset = v.pagination()
    department_id = v.query_filter("department_id")
    cutting_test_line_id = v.query_filter("cutting_test_line_id")
    source_trim_lot_id = v.query_filter("source_trim_lot_id")
    status = v.query_filter("status")
    rows = []
    for row in db.trim_lots.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if (cutting_test_line_id is not None
                and row.get("cutting_test_line_id") != cutting_test_line_id):
            continue
        if (source_trim_lot_id is not None
                and row.get("source_trim_lot_id") != source_trim_lot_id):
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


@bp.route("/meat-ops/trim-lots/<lot_id>/transitions", methods=["POST"])
def lot_transition(lot_id):
    _, role = mw.authenticate((mw.MEAT_CUTTER,))
    lot = v.resolve("trim_lot", lot_id)
    payload = v.body()
    action = v.field_enum(payload, "action", tuple(LOT_ACTION_ROLES), required=True)
    mw.check_action_role(role, action, LOT_ACTION_ROLES)

    if lot["status"] not in COMMITTABLE:
        raise ApiError(errors.ERR_TRIM_LOT_NOT_AVAILABLE, 409,
                       "The trim lot is %s" % lot["status"])

    if lot["allocated_lb"] > 0:
        raise ApiError(errors.ERR_TRIM_LOT_COMMITTED, 422,
                       "A lot with committed pounds may not be discarded")

    grind.discard_lot(lot)
    return object_response(lot)
