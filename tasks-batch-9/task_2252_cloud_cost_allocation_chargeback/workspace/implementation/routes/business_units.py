"""Business units and the rollup tree (PRD 3.1)."""
from flask import Blueprint

from db import base_fields, db, touch
from middleware import authorize
from routes.common import lookup, optional_ref, serve, serve_list
from services import derived
from validation import body, opt_bool, opt_enum, opt_int, present, req_str

bp = Blueprint("business_units", __name__)

STATUSES = ("ACTIVE", "SUSPENDED", "ARCHIVED")
READERS = ("PlatformAdmin", "FinOpsAnalyst", "FinOpsController", "BusinessUnitOwner")


@bp.route("/finops/business-units", methods=["POST"])
@authorize("PlatformAdmin")
def create_business_unit():
    data = body()
    parent = None
    if present(data, "parent_business_unit_id"):
        parent = optional_ref("business_units", data.get("parent_business_unit_id"))
    name = req_str(data, "name")
    cost_center_code = req_str(data, "cost_center_code")
    chargeback_enabled = opt_bool(data, "chargeback_enabled", False)
    headcount = opt_int(data, "headcount", 0)
    revenue_cents = opt_int(data, "revenue_cents", 0)
    status = opt_enum(data, "status", STATUSES, "ACTIVE")

    bu = base_fields()
    bu.update(
        {
            "name": name,
            "parent_business_unit_id": parent["id"] if parent else None,
            "cost_center_code": cost_center_code,
            "chargeback_enabled": chargeback_enabled,
            "headcount": headcount,
            "revenue_cents": revenue_cents,
            "status": status,
            "resource_count": 0,
            "tracked_run_rate_cents": 0,
            "direct_spend_cents": 0,
            "showback_total_cents": 0,
            "chargeback_balance_cents": 0,
        }
    )
    db.business_units[bu["id"]] = bu
    return serve(bu, 201)


@bp.route("/finops/business-units", methods=["GET"])
@authorize(*READERS)
def list_business_units():
    for bu in list(db.business_units.values()):
        derived.bu_sync(bu, bump=False)
    return serve_list(
        db.business_units.values(),
        {"parent_business_unit_id": "parent_business_unit_id", "status": "status"},
    )


@bp.route("/finops/business-units/<bu_id>", methods=["GET"])
@authorize(*READERS)
def get_business_unit(bu_id):
    bu = lookup("business_units", bu_id)
    derived.bu_sync(bu, bump=False)
    return serve(bu)


@bp.route("/finops/business-units/<bu_id>", methods=["PATCH"])
@authorize("PlatformAdmin")
def update_business_unit(bu_id):
    bu = lookup("business_units", bu_id)
    data = body()
    if present(data, "chargeback_enabled"):
        bu["chargeback_enabled"] = opt_bool(data, "chargeback_enabled")
    if present(data, "headcount"):
        bu["headcount"] = opt_int(data, "headcount")
    if present(data, "revenue_cents"):
        bu["revenue_cents"] = opt_int(data, "revenue_cents")
    if present(data, "status"):
        bu["status"] = opt_enum(data, "status", STATUSES)
    touch(bu)
    derived.bu_sync(bu, bump=False)
    return serve(bu)
