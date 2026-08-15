"""CostProjection endpoints (PRD §3.6): OCC-guarded create-with-supersede."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_PACKAGE_NOT_APPROVED,
    ERR_SPLIT_NOT_ACTIVE,
    ERR_STALE_ASSIGNMENT_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import monthly_cost_cents, months_touched
from services.core import (
    new_record, open_split_of, policy_of_assignment, touch,
)
from util import parse_date
from validate import get_body, req_field, require_fk, require_path_resource

bp = Blueprint("cost_projections", __name__)


@bp.post("/mobility/cost-projections")
def create_projection():
    authorized(["FinanceController", "MobilityAdmin"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    ev = req_field(body, "expected_assignment_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise_error(ERR_INVALID_REQUEST, "expected_assignment_version must be an integer")
    # OCC guard before any other business check (PRD §3.6).
    if ev != asg["version"]:
        raise_error(
            ERR_STALE_ASSIGNMENT_VERSION,
            "expected_assignment_version does not match the assignment's current version",
        )
    # Referential gates: APPROVED package, ACTIVE split.
    package = None
    for p in db["compensation_packages"].values():
        if p["assignment_id"] == asg["id"] and p["status"] == "APPROVED":
            package = p
            break
    if package is None:
        raise_error(ERR_PACKAGE_NOT_APPROVED, "an APPROVED compensation package is required")
    split = None
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == asg["id"] and sp["status"] == "ACTIVE":
            split = sp
            break
    if split is None:
        raise_error(ERR_SPLIT_NOT_ACTIVE, "an ACTIVE payroll split is required")

    policy = policy_of_assignment(asg)
    start = parse_date(asg["start_date"])
    end = parse_date(asg["planned_end_date"])
    months = months_touched(start, end)
    monthly = monthly_cost_cents(
        home_base_annual_cents=package["home_base_annual_cents"],
        host_payroll_pct=split["host_payroll_pct"],
        coc_exempt=split["coc_exempt"],
        per_diem_daily_cents=policy["per_diem_daily_cents"],
        cola_pct=policy["cola_pct"],
        housing_monthly_cap_cents=policy["housing_monthly_cap_cents"],
    )
    posted_count = sum(
        1 for r in db["shadow_payroll_records"].values()
        if r["assignment_id"] == asg["id"] and r["status"] == "POSTED"
    )
    if posted_count == 0:
        variant = "PROVISIONAL"
        total = months * monthly
    else:
        variant = "ACTUALIZED"
        posted_sum = sum(
            e["amount_cents"]
            for e in db["chargeback_entries"].values()
            if e["assignment_id"] == asg["id"] and e["entry_type"] == "PERIOD_COST"
            and e["status"] in ("ACCRUED", "POSTED")
        )
        total = posted_sum + (months - posted_count) * monthly

    # Create-with-supersede: any prior CURRENT projection becomes SUPERSEDED.
    for p in db["cost_projections"].values():
        if p["assignment_id"] == asg["id"] and p["status"] == "CURRENT":
            p["status"] = "SUPERSEDED"
            touch(p)
    rec = new_record("cost_projections", {
        "assignment_id": asg["id"],
        "variant": variant,
        "projected_months": months,
        "monthly_cost_cents": monthly,
        "total_projected_cents": total,
        "status": "CURRENT",
    })
    # The superseding create advances the assignment version by exactly one.
    touch(asg)
    return success_object(public(rec), status=201)


@bp.get("/mobility/cost-projections/<rid>")
def get_projection(rid):
    return get_one("cost_projections", rid)


@bp.get("/mobility/cost-projections")
def list_projections():
    return list_response("cost_projections", {
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    })
