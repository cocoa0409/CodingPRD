"""Invoice routes: create (OCC-guarded), get, list, issue, void."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc

bp = Blueprint("invoices", __name__)


@bp.route("/deice-ops/invoices", methods=["POST"])
def create_invoice():
    middleware.require_roles("BillingClerk")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["operation_id", "expected_airline_version"])
    op = db.deice_operations.get(payload["operation_id"])
    if op is None:
        raise errors.not_found("operation not found")
    expected = util.to_int(payload["expected_airline_version"], "expected_airline_version")
    if op["status"] != "CLEARED":
        raise errors.invalid_state("operation must be CLEARED to invoice")
    req = db.deice_requests.get(op["request_id"])
    if req is None:
        raise errors.not_found("request not found")
    airline = db.airlines.get(req["airline_id"])
    if airline is None:
        raise errors.not_found("airline not found")
    if expected != airline["version"]:
        raise errors.stale_version()
    # Existing invoice state for this operation.
    superseded_id = None
    for inv in db.invoices.values():
        if inv["operation_id"] == op["id"] and inv["status"] == "ISSUED":
            raise errors.invalid_state("an ISSUED invoice already exists for this operation")
    for inv in db.invoices.values():
        if inv["operation_id"] == op["id"] and inv["status"] == "DRAFT":
            inv["status"] = "SUPERSEDED"
            inv["version"] += 1
            inv["updated_at"] = util.iso_now()
            superseded_id = inv["id"]
    station = db.stations.get(op["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    # Lazy month reset, then compute charges with the reset base.
    calc.lazy_month_reset(airline)
    charges = calc.compute_invoice_charges(op, airline, station)
    now = util.iso_now()
    invoice = {
        "id": util.new_id(),
        "airline_id": airline["id"],
        "station_id": op["station_id"],
        "operation_id": op["id"],
        "supersedes_invoice_id": superseded_id,
        "pad_fee_cents": charges["pad_fee_cents"],
        "fluid_charge_cents": charges["fluid_charge_cents"],
        "storm_surcharge_cents": charges["storm_surcharge_cents"],
        "total_cents": charges["total_cents"],
        "pricing_variant": "MARGINAL_TIER",
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    invoice["_created_dt"] = db.get_clock()
    db.invoices[invoice["id"]] = invoice
    airline["version"] += 1
    airline["updated_at"] = now
    return response.success_object(serializers.invoice(invoice), 201)


@bp.route("/deice-ops/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = middleware.require_roles("StationAdmin", "BillingClerk", "AirlineRep")
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found("invoice not found")
    if role == "AirlineRep":
        middleware.require_own_airline(user_id, invoice["airline_id"])
    return response.success_object(serializers.invoice(invoice), 200)


@bp.route("/deice-ops/invoices", methods=["GET"])
def list_invoices():
    user_id, role = middleware.require_roles("StationAdmin", "BillingClerk", "AirlineRep")
    limit, offset = util.get_pagination()
    airline_id = request.args.get("airline_id")
    station_id = request.args.get("station_id")
    operation_id = request.args.get("operation_id")
    status = request.args.get("status")
    supersedes_invoice_id = request.args.get("supersedes_invoice_id")
    items = list(db.invoices.values())
    if role == "AirlineRep":
        items = [i for i in items if i["airline_id"] == user_id]
    if airline_id is not None:
        items = [i for i in items if i["airline_id"] == airline_id]
    if station_id is not None:
        items = [i for i in items if i["station_id"] == station_id]
    if operation_id is not None:
        items = [i for i in items if i["operation_id"] == operation_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if supersedes_invoice_id is not None:
        items = [i for i in items if i.get("supersedes_invoice_id") == supersedes_invoice_id]
    items.sort(key=lambda i: i["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.invoice(i) for i in page], limit, offset, total)


@bp.route("/deice-ops/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    middleware.require_roles("BillingClerk")
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found("invoice not found")
    if invoice["status"] != "DRAFT":
        raise errors.invalid_state("invoice must be DRAFT to issue")
    airline = db.airlines.get(invoice["airline_id"])
    if airline is None:
        raise errors.not_found("airline not found")
    op = db.deice_operations.get(invoice["operation_id"])
    if op is None:
        raise errors.not_found("operation not found")
    calc.lazy_month_reset(airline)
    airline["outstanding_balance_cents"] = int(airline["outstanding_balance_cents"]) + int(invoice["total_cents"])
    airline["monthly_billed_liters"] = int(airline["monthly_billed_liters"]) + int(op["actual_liters"])
    airline["version"] += 1
    airline["updated_at"] = util.iso_now()
    invoice["status"] = "ISSUED"
    invoice["version"] += 1
    invoice["updated_at"] = util.iso_now()
    return response.success_object(serializers.invoice(invoice), 200)


@bp.route("/deice-ops/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    middleware.require_roles("BillingClerk")
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found("invoice not found")
    if invoice["status"] != "ISSUED":
        raise errors.invalid_state("invoice must be ISSUED to void")
    airline = db.airlines.get(invoice["airline_id"])
    if airline is None:
        raise errors.not_found("airline not found")
    op = db.deice_operations.get(invoice["operation_id"])
    if op is None:
        raise errors.not_found("operation not found")
    calc.lazy_month_reset(airline)
    airline["outstanding_balance_cents"] = int(airline["outstanding_balance_cents"]) - int(invoice["total_cents"])
    airline["monthly_billed_liters"] = int(airline["monthly_billed_liters"]) - int(op["actual_liters"])
    airline["version"] += 1
    airline["updated_at"] = util.iso_now()
    invoice["status"] = "VOID"
    invoice["version"] += 1
    invoice["updated_at"] = util.iso_now()
    return response.success_object(serializers.invoice(invoice), 200)
