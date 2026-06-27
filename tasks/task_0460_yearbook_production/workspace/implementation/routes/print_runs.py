"""PrintRun routes: create (OCC-guarded), get, list, ship, deliver (cascade)."""
from flask import Blueprint, request

from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_int, parse_pagination, invalid,
)
from lookups import get_print_run_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.calculations import production_cost
from services.derive import recompute_yearbook
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_STALE_VERSION,
)

bp = Blueprint("print_runs", __name__)


@bp.route("/yearbooks/print-runs", methods=["POST"])
def create_print_run():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()

    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    yb = get_ref(db.yearbooks, yearbook_id)
    quantity = as_int(require(body, "quantity"), "quantity")
    if quantity < 1:
        invalid("quantity must be >= 1")
    delivery_address = as_str(require(body, "delivery_address"), "delivery_address")
    # expected_yearbook_version is required (structural)
    expected_version = as_int(require(body, "expected_yearbook_version"),
                              "expected_yearbook_version")

    # OCC: compare against current Yearbook.version (412 on mismatch)
    if expected_version != yb["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_yearbook_version does not match the current version")

    cost_cents = production_cost(yb["unit_cost_cents"], yb["target_page_count"], quantity)

    run = {
        "yearbook_id": yearbook_id,
        "quantity": quantity,
        "delivery_address": delivery_address,
        "cost_cents": cost_cents,
        "status": "COMMITTED",
    }
    stamp_create(run)
    db.print_runs[run["id"]] = run

    # mirror cost onto yearbook + advance version
    yb["production_cost_cents"] = cost_cents
    touch(yb)
    # derived posture may also change (e.g. recompute), and it bumps version again
    recompute_yearbook(yb)
    return success_object(ser.print_run(run), 201)


@bp.route("/yearbooks/print-runs/<print_run_id>", methods=["GET"])
def get_print_run(print_run_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    run = get_print_run_path(print_run_id)
    return success_object(ser.print_run(run), 200)


@bp.route("/yearbooks/print-runs", methods=["GET"])
def list_print_runs():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    records = list(db.print_runs.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.print_run(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/print-runs/<print_run_id>/ship", methods=["POST"])
def ship_print_run(print_run_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    run = get_print_run_path(print_run_id)
    if run["status"] != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "print run is not COMMITTED")
    run["status"] = "SHIPPED"
    touch(run)
    return success_object(ser.print_run(run), 200)


@bp.route("/yearbooks/print-runs/<print_run_id>/deliver", methods=["POST"])
def deliver_print_run(print_run_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    run = get_print_run_path(print_run_id)
    if run["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_STATE, 409, "print run is not SHIPPED")

    run["status"] = "DELIVERED"
    touch(run)

    yb_id = run["yearbook_id"]
    # cascade: every PAID order -> FULFILLED, each creating a DistributionRecord
    paid_orders = [
        o for o in sorted_by_created(list(db.presale_orders.values()))
        if o["yearbook_id"] == yb_id and o["status"] == "PAID"
    ]
    for order in paid_orders:
        order["status"] = "FULFILLED"
        touch(order)
        record = {
            "yearbook_id": yb_id,
            "presale_order_id": order["id"],
            "recipient_name": order["buyer_name"],
            "copies_handed": order["quantity"],
            "status": "HANDED_OUT",
        }
        stamp_create(record)
        db.distribution_records[record["id"]] = record

    yb = db.yearbooks.get(yb_id)
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.print_run(run), 200)
