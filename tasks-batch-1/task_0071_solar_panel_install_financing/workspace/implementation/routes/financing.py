from flask import Blueprint, request
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, is_int, is_num, list_response
from services import calc

bp = Blueprint("financing", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def _get_plan(fpid):
    p = db.financing_plans.get(fpid)
    if not p:
        raise err("ERR_NOT_FOUND", "Financing plan not found.")
    return p


@bp.route("/solar/financing-plans", methods=["POST"])
def create_plan():
    user_id, role = authenticate({"Homeowner"})
    body = get_body()
    require_fields(body, ["project_id", "model", "term_years"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    if project["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    model = body["model"]
    if model not in ("PPA", "LEASE", "LOAN"):
        raise err("ERR_INVALID_REQUEST", "model must be PPA, LEASE, or LOAN.")
    term = body["term_years"]
    if not is_int(term) or term < 1 or term > 25:
        raise err("ERR_INVALID_REQUEST", "term_years must be integer in [1,25].")

    # model-specific required fields -> ERR_FINANCING_FIELDS_MISSING
    ppa_rate = body.get("ppa_rate_cents_per_kwh")
    ppa_esc = body.get("ppa_escalator_pct")
    lease_monthly = body.get("lease_monthly_cents")
    loan_principal = body.get("loan_principal_cents")
    loan_apr = body.get("loan_apr")

    if model == "PPA":
        if ppa_rate is None or ppa_esc is None:
            raise err("ERR_FINANCING_FIELDS_MISSING", "PPA requires rate and escalator.")
        if not is_num(ppa_rate) or ppa_rate < 0:
            raise err("ERR_INVALID_REQUEST", "ppa_rate_cents_per_kwh must be >= 0.")
        if not is_num(ppa_esc) or ppa_esc < 0.0 or ppa_esc > 0.10:
            raise err("ERR_INVALID_REQUEST", "ppa_escalator_pct must be in [0,0.10].")
    elif model == "LEASE":
        if lease_monthly is None:
            raise err("ERR_FINANCING_FIELDS_MISSING", "LEASE requires lease_monthly_cents.")
        if not is_int(lease_monthly) or lease_monthly < 0:
            raise err("ERR_INVALID_REQUEST", "lease_monthly_cents must be integer >= 0.")
    elif model == "LOAN":
        if loan_principal is None or loan_apr is None:
            raise err("ERR_FINANCING_FIELDS_MISSING", "LOAN requires principal and apr.")
        if not is_int(loan_principal) or loan_principal < 0:
            raise err("ERR_INVALID_REQUEST", "loan_principal_cents must be integer >= 0.")
        if not is_num(loan_apr) or loan_apr < 0.0 or loan_apr > 0.30:
            raise err("ERR_INVALID_REQUEST", "loan_apr must be in [0,0.30].")

    if model == "LOAN":
        srec_owner = "HOMEOWNER"
        itc_beneficiary = "HOMEOWNER"
    else:
        srec_owner = "FINANCIER"
        itc_beneficiary = "FINANCIER"

    with db.lock:
        fpid = new_id()
        rec = {
            "id": fpid,
            "project_id": body["project_id"],
            "model": model,
            "status": "DRAFT",
            "term_years": term,
            "ppa_rate_cents_per_kwh": ppa_rate if ppa_rate is not None else 0.0,
            "ppa_escalator_pct": ppa_esc if ppa_esc is not None else 0.0,
            "lease_monthly_cents": lease_monthly if lease_monthly is not None else 0,
            "loan_principal_cents": loan_principal if loan_principal is not None else 0,
            "loan_apr": loan_apr if loan_apr is not None else 0.0,
            "monthly_payment_cents": 0,
            "srec_owner": srec_owner,
            "itc_beneficiary": itc_beneficiary,
        }
        rec.update(_common_create())
        db.financing_plans[fpid] = rec
    return ok(rec, 201)


@bp.route("/solar/financing-plans/<fpid>", methods=["GET"])
def get_plan(fpid):
    authenticate({"Homeowner", "PlatformAdmin"})
    return ok(_get_plan(fpid), 200)


@bp.route("/solar/financing-plans", methods=["GET"])
def list_plans():
    authenticate({"Homeowner", "PlatformAdmin"})
    rows = list(db.financing_plans.values())
    proj = request.args.get("project_id")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    return list_response(rows)


@bp.route("/solar/financing-plans/<fpid>/activate", methods=["POST"])
def activate(fpid):
    user_id, role = authenticate({"Homeowner"})
    plan = _get_plan(fpid)
    project = db.projects.get(plan["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    if project["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    if plan["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Plan not in DRAFT.")
    if project["status"] != "DESIGNED":
        raise err("ERR_INVALID_STATE", "Project not in DESIGNED.")

    body = get_body()
    require_fields(body, ["expected_project_version"])
    epv = body["expected_project_version"]
    if not is_int(epv):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be integer.")

    # business: at most one non-TERMINATED plan
    for other in db.financing_plans.values():
        if other["id"] == fpid:
            continue
        if other["project_id"] == project["id"] and other["status"] != "TERMINATED" \
                and other["status"] == "ACTIVE":
            raise err("ERR_FINANCING_ALREADY_ACTIVE", "Project already has an active plan.")

    # OCC
    if epv != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version mismatch.")

    with db.lock:
        plan["status"] = "ACTIVE"
        plan["monthly_payment_cents"] = calc.financing_monthly_payment(plan, project)
        project["financing_plan_id"] = plan["id"]
        # recompute ITC attribution
        if plan["model"] == "LOAN":
            beneficiary = "HOMEOWNER"
        else:
            beneficiary = "FINANCIER"
        plan["itc_beneficiary"] = beneficiary
        homeowner = db.homeowners.get(project["homeowner_id"])
        project["itc_credit_cents"] = calc.itc_credit(
            project["gross_system_cost_cents"], homeowner["state_code"])
        db.touch(project)
        db.touch(plan)
    return ok(plan, 200)
