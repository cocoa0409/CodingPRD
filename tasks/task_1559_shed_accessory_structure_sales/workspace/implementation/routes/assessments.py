"""SiteAssessment endpoints: list per order, get, report (with verdict cascade)."""

from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state
from middleware import authenticate, require_roles, check_customer_owns_order
from response import success_object, success_list
from services.common import (
    get_body, require, optional, get_order, get_assessment, paginate, MISSING,
)
from services.pricing import compute_verdict, compute_order_pricing
from services.cascade import bump, create_permit_application, advance_order_to_ready

bp = Blueprint("assessments", __name__)

READ_ROLES = ("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
              "FinanceManager", "OperationsAdmin")


@bp.get("/api/orders/<oid>/site-assessments")
def list_order_assessments(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    rows = [a for a in db.site_assessments.values() if a["order_id"] == oid]
    rows.sort(key=lambda a: a["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/site-assessments/<aid>")
def read_assessment(aid):
    authenticate()
    require_roles(*READ_ROLES)
    assessment = get_assessment(aid)
    order = db.orders.get(assessment["order_id"])
    if order is not None:
        check_customer_owns_order(order)
    return success_object(assessment)


@bp.post("/api/site-assessments/<aid>/report")
def report_assessment(aid):
    authenticate()
    require_roles("InstallCrew")
    body = get_body()
    measured_access_width_in = require(body, "measured_access_width_in", "int")
    measured_slope_pct = require(body, "measured_slope_pct", "num")
    setback_front_ft = require(body, "setback_front_ft", "num")
    setback_side_ft = require(body, "setback_side_ft", "num")
    setback_rear_ft = require(body, "setback_rear_ft", "num")
    ground_prep_needed = require(body, "ground_prep_needed", "bool")
    prep_cost_cents = optional(body, "prep_cost_cents", "int", default=None, allow_none=True)
    if ground_prep_needed and prep_cost_cents is None:
        raise invalid_request("prep_cost_cents is required when ground_prep_needed")

    assessment = get_assessment(aid)
    if assessment["status"] != "REQUESTED":
        raise invalid_state("Report can only be filed while the assessment is REQUESTED")

    order = db.orders[assessment["order_id"]]
    jurisdiction = db.jurisdictions[order["jurisdiction_id"]]

    report = {
        "measured_access_width_in": measured_access_width_in,
        "measured_slope_pct": measured_slope_pct,
        "setback_front_ft": setback_front_ft,
        "setback_side_ft": setback_side_ft,
        "setback_rear_ft": setback_rear_ft,
        "ground_prep_needed": ground_prep_needed,
    }
    verdict = compute_verdict(order, jurisdiction, report)

    assessment["measured_access_width_in"] = measured_access_width_in
    assessment["measured_slope_pct"] = measured_slope_pct
    assessment["setback_front_ft"] = setback_front_ft
    assessment["setback_side_ft"] = setback_side_ft
    assessment["setback_rear_ft"] = setback_rear_ft
    assessment["ground_prep_needed"] = ground_prep_needed
    assessment["prep_cost_cents"] = prep_cost_cents
    assessment["verdict"] = verdict
    assessment["reported_at"] = db.now_iso()
    assessment["status"] = "REPORTED"
    bump(assessment)

    # Cascade to the parent order (PRD §3.3)
    if order["status"] == "SITE_REVIEW":
        if verdict in ("SUITABLE", "SUITABLE_WITH_PREP"):
            if verdict == "SUITABLE_WITH_PREP":
                order["site_prep_required"] = True
                order["site_prep_fee_cents"] = prep_cost_cents or 0
                model = db.models[order["model_id"]]
                priced = compute_order_pricing(order, model, jurisdiction)
                order["quoted_total_cents"] = priced["total_cents"]
            order["status"] = "PERMIT_REVIEW"
            bump(order)
            app = create_permit_application(order)
            if not app["permit_required"]:
                app["status"] = "NOT_REQUIRED"
                bump(app)
                advance_order_to_ready(order)
        else:  # UNSUITABLE
            order["status"] = "DRAFT"
            bump(order)

    return success_object(assessment)
