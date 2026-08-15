"""Material takeoffs: estimate, quote/revise cycle, conversion (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_JOB_ACCOUNT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_TAKEOFF_NOT_FOUND,
    ERR_BRANCH_NOT_FOUND,
    ERR_TAKEOFF_NOT_DRAFT,
    ERR_TAKEOFF_NOT_QUOTED,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import body, body_field, render_list, render_one
from services.core import create_record, get_or_404, mutate, credit_available
from services.calculations import takeoff_estimate
from services.order_ops import create_order_from_takeoff

bp = Blueprint("takeoffs", __name__)

TAKEOFF_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "Contractor"]


def _compute_estimate(rec):
    product = db["products"].get(rec["product_id"])
    shingle, accessory, bundles, amount = takeoff_estimate(
        product, rec["roof_squares"], rec["waste_factor_pct"],
        rec["valley_ridge_linear_feet"])
    rec["_shingle_bundles"] = shingle
    rec["estimated_bundles"] = bundles
    rec["estimated_amount_cents"] = amount


@bp.post("/roofing/job-accounts/<jid>/takeoffs")
def create_takeoff(jid):
    caller = authorized(["SalesRep", "Contractor"])
    job = get_or_404("job_accounts", jid, ERR_JOB_ACCOUNT_NOT_FOUND)
    check_contractor_owns(caller, job["contractor_account_id"])
    data = body()
    product_id = body_field(data, "product_id", required=True)
    if db["products"].get(product_id) is None:
        raise_error(ERR_PRODUCT_NOT_FOUND, f"product {product_id} does not exist")
    if data.get("roof_squares") is None:
        raise_error(ERR_INVALID_REQUEST, "roof_squares is required")
    waste = data.get("waste_factor_pct")
    if waste is None:
        raise_error(ERR_INVALID_REQUEST, "waste_factor_pct is required")
    try:
        waste_f = float(waste)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "waste_factor_pct must be a number")
    if waste_f < 0 or waste_f > 40:
        raise_error(ERR_INVALID_REQUEST, "waste_factor_pct must be >= 0 and <= 40")
    rec = create_record("takeoffs", {
        "job_account_id": job["id"],
        "product_id": product_id,
        "roof_squares": data.get("roof_squares"),
        "waste_factor_pct": data.get("waste_factor_pct"),
        "valley_ridge_linear_feet": int(data.get("valley_ridge_linear_feet") or 0),
        "estimated_bundles": 0,
        "estimated_amount_cents": 0,
        "status": "DRAFT",
    })
    _compute_estimate(rec)  # provisional variant: current list prices
    return render_one("takeoffs", rec, status=201)


@bp.get("/roofing/job-accounts/<jid>/takeoffs")
def list_job_takeoffs(jid):
    caller = authorized(TAKEOFF_READ_ROLES)
    job = get_or_404("job_accounts", jid, ERR_JOB_ACCOUNT_NOT_FOUND)
    check_contractor_owns(caller, job["contractor_account_id"])
    takeoffs = [t for t in db["takeoffs"].values() if t["job_account_id"] == job["id"]]
    return render_list(caller, "takeoffs", base_records=takeoffs)


@bp.get("/roofing/takeoffs")
def list_takeoffs():
    caller = authorized(TAKEOFF_READ_ROLES)
    return render_list(caller, "takeoffs",
                       filters={"product_id": request.args.get("product_id"),
                                "job_account_id": request.args.get("job_account_id"),
                                "status": request.args.get("status")})


@bp.get("/roofing/takeoffs/<rid>")
def get_takeoff(rid):
    caller = authorized(TAKEOFF_READ_ROLES)
    rec = get_or_404("takeoffs", rid, ERR_TAKEOFF_NOT_FOUND)
    job = db["job_accounts"].get(rec["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    return render_one("takeoffs", rec)


@bp.post("/roofing/takeoffs/<rid>/quote")
def quote_takeoff(rid):
    authorized(["SalesRep"])
    rec = get_or_404("takeoffs", rid, ERR_TAKEOFF_NOT_FOUND)
    if rec["status"] != "DRAFT":
        raise_error(ERR_TAKEOFF_NOT_DRAFT, "quote requires the takeoff to be in DRAFT")
    job = db["job_accounts"].get(rec["job_account_id"])
    account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
    if account is None or account["status"] != "ACTIVE":
        raise_error(ERR_ACCOUNT_NOT_ACTIVE,
                    "the contractor account behind the job must be ACTIVE to quote")
    _compute_estimate(rec)  # locked_at_quote variant: freeze at quote-time prices
    rec["status"] = "QUOTED"
    mutate(rec)
    return render_one("takeoffs", rec)


@bp.post("/roofing/takeoffs/<rid>/revise")
def revise_takeoff(rid):
    authorized(["SalesRep"])
    rec = get_or_404("takeoffs", rid, ERR_TAKEOFF_NOT_FOUND)
    if rec["status"] != "QUOTED":
        raise_error(ERR_TAKEOFF_NOT_QUOTED, "revise requires the takeoff to be in QUOTED")
    rec["status"] = "DRAFT"
    mutate(rec)
    return render_one("takeoffs", rec)


@bp.post("/roofing/takeoffs/<rid>/convert")
def convert_takeoff(rid):
    caller = authorized(["Contractor"])
    rec = get_or_404("takeoffs", rid, ERR_TAKEOFF_NOT_FOUND)
    job = db["job_accounts"].get(rec["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    if rec["status"] != "QUOTED":
        raise_error(ERR_TAKEOFF_NOT_QUOTED, "convert requires the takeoff to be in QUOTED")
    data = body()
    branch_id = body_field(data, "branch_id", required=True)
    branch = db["branches"].get(branch_id)
    if branch is None:
        raise_error(ERR_BRANCH_NOT_FOUND, f"branch {branch_id} does not exist")
    account = db["contractor_accounts"][job["contractor_account_id"]]
    order = create_order_from_takeoff(rec, branch)
    if credit_available(account) < order["total_cents"]:
        # Provisional order total is not covered: refuse before persisting.
        db["orders"].pop(order["id"], None)
        for line in [l for l in db["order_lines"].values() if l["order_id"] == order["id"]]:
            db["order_lines"].pop(line["id"], None)
        raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                    "credit_available_cents does not cover the provisional order total")
    rec["status"] = "CONVERTED"
    mutate(rec)
    return render_one("orders", order, status=201)
