import math
import os
import re
import uuid
from datetime import datetime, date, timedelta, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================================
# In-memory store (empty at every boot; no seeding anywhere)
# =========================================================================
db = {
    "fiscal_years": {},
    "enrollment_projections": {},
    "budget_versions": {},
    "budget_lines": {},
    "staffing_allocations": {},
    "positions": {},
    "revenue_estimates": {},
    "public_hearings": {},
    "elections": {},
    "bond_proposals": {},
    "bond_projects": {},
    "ballot_measures": {},
    "district_publications": {},
    "bond_sales": {},
    "project_expenditures": {},
    "capital_plan_amendments": {},
}

CLOCK = {"current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

ROLES = ["BudgetAnalyst", "BusinessManager", "BoardClerk",
         "Superintendent", "DistrictTreasurer", "Auditor"]

# =========================================================================
# Helpers
# =========================================================================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def ts_now():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def round_half_up_2(v):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4(v):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def round_half_up_0(v):
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:20]


class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def err(error_id, message, status):
    raise ApiError(error_id, message, status)


def success_obj(data, code=200):
    return jsonify({
        "meta": {"api_request_id": request_id(), "api_request_timestamp": ts_now()},
        "response_type": "object",
        "data": data,
    }), code


def success_list(items, total):
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return jsonify({
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": ts_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        },
        "response_type": "array",
        "data": page,
    }), 200


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({
        "meta": {"api_request_id": request_id(), "api_request_timestamp": ts_now()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        "meta": {"api_request_id": request_id(), "api_request_timestamp": ts_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        "meta": {"api_request_id": request_id(), "api_request_timestamp": ts_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }), 405


# -------------------------------------------------------------------------
# Auth middleware — runs before every /district and /_clock request
# -------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and role must be one of the six declared roles",
            401)
    if allowed_roles is not None and role not in allowed_roles:
        err("ERR_FORBIDDEN_ROLE", "Role not authorized for this endpoint", 403)
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        err("ERR_INVALID_REQUEST", f"Missing required field: {name}", 400)
    return data[name]


def as_number(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a number", 400)
    return v


def as_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", f"Field {name} must be an integer", 400)
    return v


def as_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a string", 400)
    return v


def as_enum(data, name, values):
    v = as_str(data, name)
    if v not in values:
        err("ERR_INVALID_REQUEST", f"Field {name} must be one of {values}", 400)
    return v


def parse_date(s, field="date"):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO date YYYY-MM-DD", 400)


def parse_datetime_lenient(s, field="datetime"):
    if not isinstance(s, str):
        err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string", 400)
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        err("ERR_INVALID_REQUEST", f"Field {field} must be ISO 8601", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def today():
    return CLOCK["current"].date()


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    days_in_month = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, days_in_month))


def get_or_404(coll, rid, error_id, message):
    obj = db[coll].get(rid)
    if obj is None:
        err(error_id, message, 404)
    return obj


# =========================================================================
# Serializers
# =========================================================================

def fy_view(f):
    return {
        "id": f["id"], "label": f["label"], "start_date": f["start_date"],
        "end_date": f["end_date"], "eav_current": f["eav_current"],
        "eav_prior": f["eav_prior"], "prior_year_extension": f["prior_year_extension"],
        "outstanding_debt_principal": f["outstanding_debt_principal"],
        "fte_ceiling": f["fte_ceiling"],
        "authorized_fte_total": f["authorized_fte_total"],
        "open_position_count": f["open_position_count"],
        "status": f["status"], "created_at": f["created_at"],
        "updated_at": f["updated_at"], "version": f["version"],
    }


def ep_view(e):
    return {
        "id": e["id"], "fiscal_year_id": e["fiscal_year_id"],
        "grade_band": e["grade_band"], "projected_pupils": e["projected_pupils"],
        "actual_pupils": e["actual_pupils"],
        "weighted_pupils_projected": e["weighted_pupils_projected"],
        "weighted_pupils_certified": e["weighted_pupils_certified"],
        "status": e["status"], "created_at": e["created_at"],
        "updated_at": e["updated_at"], "version": e["version"],
    }


def bv_view(b):
    return {
        "id": b["id"], "fiscal_year_id": b["fiscal_year_id"],
        "version_label": b["version_label"],
        "total_appropriations": b["total_appropriations"],
        "hearing_held_date": b["hearing_held_date"],
        "adopted_at": b["adopted_at"],
        "status": b["status"], "created_at": b["created_at"],
        "updated_at": b["updated_at"], "version": b["version"],
    }


def bl_view(l):
    return {
        "id": l["id"], "budget_version_id": l["budget_version_id"],
        "fund_code": l["fund_code"], "function_code": l["function_code"],
        "object_code": l["object_code"], "cost_center": l["cost_center"],
        "appropriation_amount": l["appropriation_amount"],
        "status": l["status"], "created_at": l["created_at"],
        "updated_at": l["updated_at"], "version": l["version"],
    }


def sa_view(s):
    return {
        "id": s["id"], "budget_version_id": s["budget_version_id"],
        "enrollment_projection_id": s["enrollment_projection_id"],
        "grade_band": s["grade_band"], "required_fte": s["required_fte"],
        "allocated_fte": s["allocated_fte"],
        "positions_fte_total": s["positions_fte_total"],
        "cost_estimate_projected": s["cost_estimate_projected"],
        "cost_estimate_actual": s["cost_estimate_actual"],
        "status": s["status"], "created_at": s["created_at"],
        "updated_at": s["updated_at"], "version": s["version"],
    }


def pos_view(p):
    return {
        "id": p["id"], "staffing_allocation_id": p["staffing_allocation_id"],
        "title": p["title"], "fte": p["fte"], "base_salary": p["base_salary"],
        "incumbent_salary": p["incumbent_salary"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def re_view(r):
    return {
        "id": r["id"], "budget_version_id": r["budget_version_id"],
        "operating_levy_request": r["operating_levy_request"],
        "debt_service_levy": r["debt_service_levy"],
        "other_revenue": r["other_revenue"], "cpi_rate": r["cpi_rate"],
        "capped_operating_levy": r["capped_operating_levy"],
        "total_levy": r["total_levy"], "eav_basis": r["eav_basis"],
        "state_aid": r["state_aid"], "operating_rate": r["operating_rate"],
        "debt_service_rate": r["debt_service_rate"],
        "total_tax_rate": r["total_tax_rate"],
        "total_revenue": r["total_revenue"],
        "state_aid_provisional": r["state_aid_provisional"],
        "total_revenue_provisional": r["total_revenue_provisional"],
        "status": r["status"], "created_at": r["created_at"],
        "updated_at": r["updated_at"], "version": r["version"],
    }


def ph_view(h):
    return {
        "id": h["id"], "budget_version_id": h["budget_version_id"],
        "venue": h["venue"], "hearing_date": h["hearing_date"],
        "notice_publication_date": h["notice_publication_date"],
        "status": h["status"], "created_at": h["created_at"],
        "updated_at": h["updated_at"], "version": h["version"],
    }


def el_view(e):
    return {
        "id": e["id"], "election_date": e["election_date"],
        "election_type": e["election_type"], "canvassed_at": e["canvassed_at"],
        "status": e["status"], "created_at": e["created_at"],
        "updated_at": e["updated_at"], "version": e["version"],
    }


def bp_view(b):
    return {
        "id": b["id"], "fiscal_year_id": b["fiscal_year_id"],
        "question_title": b["question_title"], "purpose": b["purpose"],
        "total_amount": b["total_amount"],
        "remaining_authorization": b["remaining_authorization"],
        "available_proceeds": b["available_proceeds"],
        "passed_at": b["passed_at"], "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def prj_view(p):
    return {
        "id": p["id"], "bond_proposal_id": p["bond_proposal_id"],
        "name": p["name"], "site_code": p["site_code"],
        "estimated_cost": p["estimated_cost"],
        "construction_start": p["construction_start"],
        "construction_end": p["construction_end"],
        "priority_rank": p["priority_rank"],
        "authorized_amount": p["authorized_amount"],
        "spent_amount": p["spent_amount"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def bm_view(m):
    return {
        "id": m["id"], "election_id": m["election_id"],
        "bond_proposal_id": m["bond_proposal_id"],
        "ballot_language": m["ballot_language"], "word_count": m["word_count"],
        "drafted_by_user_id": m["drafted_by_user_id"],
        "certified_by_user_id": m["certified_by_user_id"],
        "yes_votes": m["yes_votes"], "no_votes": m["no_votes"],
        "status": m["status"], "created_at": m["created_at"],
        "updated_at": m["updated_at"], "version": m["version"],
    }


def pub_view(p):
    return {
        "id": p["id"], "ballot_measure_id": p["ballot_measure_id"],
        "publication_type": p["publication_type"], "content": p["content"],
        "published_by_user_id": p["published_by_user_id"],
        "status": p["status"], "created_at": p["created_at"],
    }


def bs_view(s):
    return {
        "id": s["id"], "bond_proposal_id": s["bond_proposal_id"],
        "series_label": s["series_label"], "par_amount": s["par_amount"],
        "premium": s["premium"], "issuance_costs": s["issuance_costs"],
        "sale_date": s["sale_date"], "net_proceeds": s["net_proceeds"],
        "status": s["status"], "created_at": s["created_at"],
        "updated_at": s["updated_at"], "version": s["version"],
    }


def pe_view(e):
    return {
        "id": e["id"], "bond_project_id": e["bond_project_id"],
        "vendor_name": e["vendor_name"], "amount": e["amount"],
        "description": e["description"],
        "retainage_amount": e["retainage_amount"],
        "disbursed_amount": e["disbursed_amount"],
        "review_status": e["review_status"],
        "payment_status": e["payment_status"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ca_view(c):
    return {
        "id": c["id"], "bond_proposal_id": c["bond_proposal_id"],
        "reason": c["reason"], "adjustments": c["adjustments"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "status": c["status"], "created_at": c["created_at"],
        "updated_at": c["updated_at"], "version": c["version"],
    }


# =========================================================================
# Derived recomputation helpers
# =========================================================================

def touch(obj):
    obj["updated_at"] = ts_now()


def bump(obj):
    obj["version"] += 1
    touch(obj)


def fy_of_budget_version(bv):
    return db["fiscal_years"].get(bv["fiscal_year_id"])


def fy_of_allocation(sa):
    bv = db["budget_versions"].get(sa["budget_version_id"])
    return db["fiscal_years"].get(bv["fiscal_year_id"]) if bv else None


def fy_of_position(p):
    sa = db["staffing_allocations"].get(p["staffing_allocation_id"])
    return fy_of_allocation(sa) if sa else None


def fy_of_proposal(bp):
    return db["fiscal_years"].get(bp["fiscal_year_id"])


def recompute_total_appropriations(bv):
    total = sum(l["appropriation_amount"]
                for l in db["budget_lines"].values()
                if l["budget_version_id"] == bv["id"] and l["status"] != "SUPERSEDED")
    new = round_half_up_2(total)
    if new != bv["total_appropriations"]:
        bv["total_appropriations"] = new
        touch(bv)


def recompute_fy_staffing(fy):
    auth_total = sum(s["allocated_fte"] for s in db["staffing_allocations"].values()
                     if s["status"] == "AUTHORIZED"
                     and db["budget_versions"][s["budget_version_id"]]["fiscal_year_id"] == fy["id"])
    open_count = sum(1 for p in db["positions"].values()
                     if p["status"] == "OPEN"
                     and db["budget_versions"][
                         db["staffing_allocations"][p["staffing_allocation_id"]]["budget_version_id"]
                     ]["fiscal_year_id"] == fy["id"])
    fy["authorized_fte_total"] = round_half_up_2(auth_total)
    fy["open_position_count"] = open_count
    touch(fy)


def recompute_allocation(sa):
    positions = [p for p in db["positions"].values()
                 if p["staffing_allocation_id"] == sa["id"] and p["status"] != "ELIMINATED"]
    sa["positions_fte_total"] = round_half_up_2(sum(p["fte"] for p in positions))
    total = 0.0
    for p in positions:
        basis = p["incumbent_salary"] if p["status"] == "FILLED" else p["base_salary"]
        total += basis * p["fte"] * 1.34
    sa["cost_estimate_actual"] = round_half_up_2(total)
    sa["cost_estimate_projected"] = round_half_up_2(sa["allocated_fte"] * 62000 * 1.34)
    touch(sa)


def recompute_project(p):
    exps = [e for e in db["project_expenditures"].values()
            if e["bond_project_id"] == p["id"] and e["payment_status"] != "VOIDED"]
    p["spent_amount"] = round_half_up_2(sum(e["amount"] for e in exps))
    touch(p)


def recompute_proposal(bp):
    sales = [s for s in db["bond_sales"].values()
             if s["bond_proposal_id"] == bp["id"] and s["status"] in ("PLANNED", "CLOSED")]
    bp["remaining_authorization"] = round_half_up_2(
        bp["total_amount"] - sum(s["par_amount"] for s in sales))
    closed = [s for s in db["bond_sales"].values()
              if s["bond_proposal_id"] == bp["id"] and s["status"] == "CLOSED"]
    proceeds = sum(s["net_proceeds"] for s in closed)
    project_ids = {p["id"] for p in db["bond_projects"].values()
                   if p["bond_proposal_id"] == bp["id"]}
    spent = sum(e["amount"] for e in db["project_expenditures"].values()
                if e["bond_project_id"] in project_ids and e["payment_status"] != "VOIDED")
    bp["available_proceeds"] = round_half_up_2(proceeds - spent)
    touch(bp)


# =========================================================================
# Cascades
# =========================================================================

def supersede_budget_version(bv):
    """Retire an ADOPTED budget version to SUPERSEDED with full cascade."""
    for sa in [s for s in db["staffing_allocations"].values()
               if s["budget_version_id"] == bv["id"] and s["status"] == "AUTHORIZED"]:
        sa["status"] = "SUPERSEDED"
        touch(sa)
        for p in [p for p in db["positions"].values()
                  if p["staffing_allocation_id"] == sa["id"]
                  and p["status"] in ("PROPOSED", "OPEN", "FILLED")]:
            p["status"] = "ELIMINATED"
            touch(p)
        recompute_allocation(sa)
    for l in [l for l in db["budget_lines"].values()
              if l["budget_version_id"] == bv["id"] and l["status"] == "ADOPTED"]:
        l["status"] = "SUPERSEDED"
        touch(l)
    bv["status"] = "SUPERSEDED"
    bump(bv)
    fy = fy_of_budget_version(bv)
    if fy:
        recompute_fy_staffing(fy)


def authorize_allocation(sa, fy):
    sa["status"] = "AUTHORIZED"
    touch(sa)
    for p in [p for p in db["positions"].values()
              if p["staffing_allocation_id"] == sa["id"] and p["status"] == "PROPOSED"]:
        p["status"] = "OPEN"
        touch(p)
    recompute_allocation(sa)


# =========================================================================
# Logical clock
# =========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(ROLES)
    data = body()
    raw = req_field(data, "to_iso8601")
    dt = parse_datetime_lenient(raw, "to_iso8601")
    CLOCK["current"] = dt
    return success_obj({"current_utc": dt.strftime("%Y-%m-%dT%H:%M:%S.") +
                        f"{dt.microsecond // 1000:03d}Z"})


# =========================================================================
# FiscalYear
# =========================================================================

@app.route("/district/fiscal-years", methods=["POST"])
def create_fiscal_year():
    require_auth(["BusinessManager"])
    data = body()
    label = as_str(data, "label")
    start = as_str(data, "start_date")
    end = as_str(data, "end_date")
    eav_current = as_number(data, "eav_current")
    eav_prior = as_number(data, "eav_prior")
    prior_ext = as_number(data, "prior_year_extension")
    debt = as_number(data, "outstanding_debt_principal")
    ceiling = as_number(data, "fte_ceiling")
    sd = parse_date(start, "start_date")
    ed = parse_date(end, "end_date")
    if ed <= sd:
        err("ERR_INVALID_FIELD_VALUE", "end_date must be after start_date", 422)
    if any(f["label"] == label for f in db["fiscal_years"].values()):
        err("ERR_INVALID_FIELD_VALUE", "label must be unique", 422)
    ts = ts_now()
    fy = {
        "id": new_id(), "label": label, "start_date": start, "end_date": end,
        "eav_current": eav_current, "eav_prior": eav_prior,
        "prior_year_extension": prior_ext, "outstanding_debt_principal": debt,
        "fte_ceiling": ceiling, "authorized_fte_total": 0, "open_position_count": 0,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["fiscal_years"][fy["id"]] = fy
    return success_obj(fy_view(fy), 201)


@app.route("/district/fiscal-years", methods=["GET"])
def list_fiscal_years():
    require_auth(ROLES)
    items = sorted(db["fiscal_years"].values(), key=lambda f: f["created_at"])
    label = request.args.get("label")
    status = request.args.get("status")
    if label is not None:
        items = [f for f in items if f["label"] == label]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    return success_list([fy_view(f) for f in items], total)


@app.route("/district/fiscal-years/<fyId>", methods=["GET"])
def get_fiscal_year(fyId):
    require_auth(ROLES)
    fy = get_or_404("fiscal_years", fyId, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    return success_obj(fy_view(fy))


@app.route("/district/fiscal-years/<fyId>/open", methods=["POST"])
def open_fiscal_year(fyId):
    require_auth(["BusinessManager"])
    fy = get_or_404("fiscal_years", fyId, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    if fy["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Fiscal year is not DRAFT", 409)
    fy["status"] = "OPEN"
    bump(fy)
    return success_obj(fy_view(fy))


@app.route("/district/fiscal-years/<fyId>/close", methods=["POST"])
def close_fiscal_year(fyId):
    require_auth(["BusinessManager"])
    fy = get_or_404("fiscal_years", fyId, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    if fy["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Fiscal year is not OPEN", 409)
    adopted = any(b["fiscal_year_id"] == fyId and b["status"] == "ADOPTED"
                  for b in db["budget_versions"].values())
    if not adopted:
        err("ERR_NO_ADOPTED_BUDGET_VERSION",
            "Fiscal year close requires an ADOPTED budget version", 409)
    fy["status"] = "CLOSED"
    bump(fy)
    # Cascade: cancel NOTICE_PUBLISHED hearings of any version of this year
    bv_ids = {b["id"] for b in db["budget_versions"].values()
              if b["fiscal_year_id"] == fyId}
    for h in db["public_hearings"].values():
        if h["budget_version_id"] in bv_ids and h["status"] == "NOTICE_PUBLISHED":
            h["status"] = "CANCELLED"
            touch(h)
    return success_obj(fy_view(fy))


# =========================================================================
# EnrollmentProjection
# =========================================================================

BAND_WEIGHTS = {"ELEMENTARY": 1.00, "MIDDLE": 1.05, "HIGH": 1.15}
BAND_RATIOS = {"ELEMENTARY": 20, "MIDDLE": 22, "HIGH": 25}


@app.route("/district/fiscal-years/<fid>/enrollment-projections", methods=["POST"])
def create_enrollment_projection(fid):
    require_auth(["BudgetAnalyst"])
    fy = get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    data = body()
    band = as_enum(data, "grade_band", ["ELEMENTARY", "MIDDLE", "HIGH"])
    pupils = as_int(data, "projected_pupils")
    if pupils < 0:
        err("ERR_INVALID_FIELD_VALUE", "projected_pupils must be >= 0", 422)
    if fy["status"] != "OPEN":
        err("ERR_FISCAL_YEAR_NOT_OPEN", "Fiscal year is not OPEN", 409)
    if any(e["fiscal_year_id"] == fid and e["grade_band"] == band
           for e in db["enrollment_projections"].values()):
        err("ERR_DUPLICATE_GRADE_BAND",
            "An enrollment projection for this grade band already exists in the fiscal year", 409)
    weighted = round_half_up_0(pupils * BAND_WEIGHTS[band])
    ts = ts_now()
    ep = {
        "id": new_id(), "fiscal_year_id": fid, "grade_band": band,
        "projected_pupils": pupils, "actual_pupils": None,
        "weighted_pupils_projected": weighted, "weighted_pupils_certified": None,
        "status": "PROVISIONAL", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["enrollment_projections"][ep["id"]] = ep
    return success_obj(ep_view(ep), 201)


@app.route("/district/fiscal-years/<fid>/enrollment-projections", methods=["GET"])
def list_enrollment_projections(fid):
    require_auth(ROLES)
    get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
               "No fiscal year with the given id")
    items = sorted([e for e in db["enrollment_projections"].values()
                    if e["fiscal_year_id"] == fid], key=lambda e: e["created_at"])
    total = len(items)
    return success_list([ep_view(e) for e in items], total)


@app.route("/district/enrollment-projections/<epId>", methods=["GET"])
def get_enrollment_projection(epId):
    require_auth(ROLES)
    ep = get_or_404("enrollment_projections", epId,
                    "ERR_ENROLLMENT_PROJECTION_NOT_FOUND",
                    "No enrollment projection with the given id")
    return success_obj(ep_view(ep))


@app.route("/district/enrollment-projections/<epId>/certify", methods=["POST"])
def certify_enrollment_projection(epId):
    require_auth(["BusinessManager"])
    ep = get_or_404("enrollment_projections", epId,
                    "ERR_ENROLLMENT_PROJECTION_NOT_FOUND",
                    "No enrollment projection with the given id")
    data = body()
    if "actual_pupils" not in data or data["actual_pupils"] is None:
        err("ERR_INVALID_FIELD_VALUE", "actual_pupils must be supplied", 422)
    actual = data["actual_pupils"]
    if isinstance(actual, bool) or not isinstance(actual, int):
        err("ERR_INVALID_REQUEST", "actual_pupils must be an integer", 400)
    if actual < 0:
        err("ERR_INVALID_FIELD_VALUE", "actual_pupils must be >= 0", 422)
    if ep["status"] != "PROVISIONAL":
        err("ERR_INVALID_STATE", "Projection is not PROVISIONAL", 409)
    ep["actual_pupils"] = actual
    ep["weighted_pupils_certified"] = round_half_up_0(actual * BAND_WEIGHTS[ep["grade_band"]])
    ep["status"] = "CERTIFIED"
    bump(ep)
    return success_obj(ep_view(ep))


# =========================================================================
# BudgetVersion
# =========================================================================

@app.route("/district/fiscal-years/<fid>/budget-versions", methods=["POST"])
def create_budget_version(fid):
    require_auth(["BudgetAnalyst"])
    fy = get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    data = body()
    if "expected_fiscal_year_version" not in data or data["expected_fiscal_year_version"] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: expected_fiscal_year_version", 400)
    expected = data["expected_fiscal_year_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", "expected_fiscal_year_version must be an integer", 400)
    if fy["status"] != "OPEN":
        err("ERR_FISCAL_YEAR_NOT_OPEN", "Fiscal year is not OPEN", 409)
    if expected != fy["version"]:
        err("ERR_STALE_VERSION",
            "expected_fiscal_year_version does not match the fiscal year's current version", 412)
    # Supersede currently ADOPTED version of this fiscal year
    for bv in list(db["budget_versions"].values()):
        if bv["fiscal_year_id"] == fid and bv["status"] == "ADOPTED":
            supersede_budget_version(bv)
    count = sum(1 for b in db["budget_versions"].values() if b["fiscal_year_id"] == fid)
    ts = ts_now()
    bv = {
        "id": new_id(), "fiscal_year_id": fid,
        "version_label": f"v{count + 1}",
        "total_appropriations": 0, "hearing_held_date": None, "adopted_at": None,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["budget_versions"][bv["id"]] = bv
    fy["version"] += 1
    touch(fy)
    return success_obj(bv_view(bv), 201)


@app.route("/district/fiscal-years/<fid>/budget-versions", methods=["GET"])
def list_budget_versions(fid):
    require_auth(ROLES)
    get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
               "No fiscal year with the given id")
    items = sorted([b for b in db["budget_versions"].values()
                    if b["fiscal_year_id"] == fid], key=lambda b: b["created_at"])
    total = len(items)
    return success_list([bv_view(b) for b in items], total)


@app.route("/district/budget-versions/<bvId>", methods=["GET"])
def get_budget_version(bvId):
    require_auth(ROLES)
    bv = get_or_404("budget_versions", bvId, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    return success_obj(bv_view(bv))


@app.route("/district/budget-versions/<bvId>/propose", methods=["POST"])
def propose_budget_version(bvId):
    require_auth(["BoardClerk"])
    bv = get_or_404("budget_versions", bvId, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    if bv["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Budget version is not DRAFT", 409)
    bv["status"] = "PROPOSED"
    bump(bv)
    return success_obj(bv_view(bv))


@app.route("/district/budget-versions/<bvId>/return-to-draft", methods=["POST"])
def return_to_draft(bvId):
    require_auth(["BoardClerk"])
    bv = get_or_404("budget_versions", bvId, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    if bv["status"] not in ("PROPOSED", "HEARING_HELD"):
        err("ERR_INVALID_STATE",
            "Budget version is not PROPOSED or HEARING_HELD", 409)
    if bv["status"] == "PROPOSED":
        for h in db["public_hearings"].values():
            if h["budget_version_id"] == bvId and h["status"] == "NOTICE_PUBLISHED":
                h["status"] = "CANCELLED"
                touch(h)
    if bv["status"] == "HEARING_HELD":
        bv["hearing_held_date"] = None
    bv["status"] = "DRAFT"
    bump(bv)
    return success_obj(bv_view(bv))


@app.route("/district/budget-versions/<bvId>/adopt", methods=["POST"])
def adopt_budget_version(bvId):
    require_auth(["BoardClerk"])
    bv = get_or_404("budget_versions", bvId, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    if bv["status"] != "HEARING_HELD":
        err("ERR_BUDGET_VERSION_NOT_HEARING_HELD",
            "Adoption requires the budget version HEARING_HELD", 409)
    fy = fy_of_budget_version(bv)
    held = parse_date(bv["hearing_held_date"], "hearing_held_date")
    if today() < held + timedelta(days=7):
        err("ERR_ADOPTION_TOO_SOON",
            "Adoption attempted before hearing_held_date + 7 days", 409)
    fy_start = parse_date(fy["start_date"], "start_date")
    if today() >= fy_start:
        err("ERR_ADOPTION_DEADLINE_PASSED",
            "Adoption attempted on/after the fiscal year's start_date", 409)
    re_ = next((r for r in db["revenue_estimates"].values()
                if r["budget_version_id"] == bvId), None)
    if re_ is None:
        err("ERR_NO_REVENUE_ESTIMATE",
            "Adoption requires a revenue estimate on the budget version", 409)
    recompute_total_appropriations(bv)
    if bv["total_appropriations"] > re_["total_revenue"]:
        err("ERR_BUDGET_NOT_BALANCED",
            "total_appropriations > revenue estimate total_revenue at adoption", 422)
    # adoption cascade
    bv["status"] = "ADOPTED"
    bv["adopted_at"] = ts_now()
    for sa in [s for s in db["staffing_allocations"].values()
               if s["budget_version_id"] == bvId and s["status"] == "DRAFT"]:
        authorize_allocation(sa, fy)
    for l in [l for l in db["budget_lines"].values()
              if l["budget_version_id"] == bvId and l["status"] == "DRAFT"]:
        l["status"] = "ADOPTED"
        touch(l)
    # retire other adopted versions
    for other in list(db["budget_versions"].values()):
        if other["fiscal_year_id"] == bv["fiscal_year_id"] and other["id"] != bvId \
                and other["status"] == "ADOPTED":
            supersede_budget_version(other)
    bump(bv)
    recompute_fy_staffing(fy)
    return success_obj(bv_view(bv))


# =========================================================================
# BudgetLine & Transfers
# =========================================================================

@app.route("/district/budget-versions/<bid>/budget-lines", methods=["POST"])
def create_budget_line(bid):
    require_auth(["BudgetAnalyst"])
    bv = get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    data = body()
    fund = as_enum(data, "fund_code",
                   ["EDUCATION", "OPERATIONS", "TRANSPORTATION",
                    "DEBT_SERVICE", "CAPITAL_PROJECTS"])
    function_code = as_str(data, "function_code")
    object_code = as_str(data, "object_code")
    cost_center = as_str(data, "cost_center")
    amount = as_number(data, "appropriation_amount")
    if amount <= 0:
        err("ERR_INVALID_FIELD_VALUE", "appropriation_amount must be > 0", 422)
    if bv["status"] != "DRAFT":
        err("ERR_BUDGET_VERSION_NOT_DRAFT",
            "Budget line mutation requires the budget version DRAFT", 409)
    ts = ts_now()
    line = {
        "id": new_id(), "budget_version_id": bid, "fund_code": fund,
        "function_code": function_code, "object_code": object_code,
        "cost_center": cost_center,
        "appropriation_amount": round_half_up_2(amount),
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["budget_lines"][line["id"]] = line
    recompute_total_appropriations(bv)
    return success_obj(bl_view(line), 201)


@app.route("/district/budget-versions/<bid>/budget-lines", methods=["GET"])
def list_budget_lines(bid):
    require_auth(ROLES)
    get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
               "No budget version with the given id")
    items = sorted([l for l in db["budget_lines"].values()
                    if l["budget_version_id"] == bid], key=lambda l: l["created_at"])
    total = len(items)
    return success_list([bl_view(l) for l in items], total)


@app.route("/district/budget-versions/<bid>/transfers", methods=["POST"])
def create_transfer(bid):
    require_auth(["BudgetAnalyst"])
    bv = get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    data = body()
    from_id = as_str(data, "from_line_id")
    to_id = as_str(data, "to_line_id")
    amount = as_number(data, "amount")
    if amount <= 0:
        err("ERR_INVALID_FIELD_VALUE", "amount must be > 0", 422)
    from_line = db["budget_lines"].get(from_id)
    if from_line is None:
        err("ERR_BUDGET_LINE_NOT_FOUND", "No budget line with the given id", 404)
    to_line = db["budget_lines"].get(to_id)
    if to_line is None:
        err("ERR_BUDGET_LINE_NOT_FOUND", "No budget line with the given id", 404)
    if bv["status"] != "DRAFT":
        err("ERR_BUDGET_VERSION_NOT_DRAFT",
            "Transfer requires the budget version DRAFT", 409)
    if from_line["budget_version_id"] != bid or to_line["budget_version_id"] != bid \
            or from_id == to_id:
        err("ERR_TRANSFER_LINE_MISMATCH",
            "from_line_id / to_line_id are not lines of the same budget version (or are the same line)",
            422)
    if amount > from_line["appropriation_amount"]:
        err("ERR_TRANSFER_EXCEEDS_LINE",
            "Transfer amount > from-line appropriation_amount", 422)
    from_line["appropriation_amount"] = round_half_up_2(
        from_line["appropriation_amount"] - amount)
    to_line["appropriation_amount"] = round_half_up_2(
        to_line["appropriation_amount"] + amount)
    bump(from_line)
    bump(to_line)
    recompute_total_appropriations(bv)
    return success_obj({
        "from_line_id": from_id, "to_line_id": to_id,
        "amount": round_half_up_2(amount),
        "from_line_appropriation": from_line["appropriation_amount"],
        "to_line_appropriation": to_line["appropriation_amount"],
    }, 201)


# =========================================================================
# StaffingAllocation
# =========================================================================

def compute_required_fte(ep):
    pupils = ep["actual_pupils"] if ep["status"] == "CERTIFIED" else ep["projected_pupils"]
    if pupils < 40:
        return 1.0
    ratio = BAND_RATIOS[ep["grade_band"]]
    return math.ceil((pupils / ratio) * 2) / 2


@app.route("/district/budget-versions/<bid>/staffing-allocations", methods=["POST"])
def create_staffing_allocation(bid):
    require_auth(["BudgetAnalyst"])
    bv = get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    data = body()
    ep_id = as_str(data, "enrollment_projection_id")
    band = as_enum(data, "grade_band", ["ELEMENTARY", "MIDDLE", "HIGH"])
    alloc = as_number(data, "allocated_fte")
    # semantic field checks
    if alloc <= 0 or (round(alloc * 2) != alloc * 2):
        err("ERR_INVALID_FIELD_VALUE",
            "allocated_fte must be > 0 and a multiple of 0.5", 422)
    # body-referenced existence
    ep = db["enrollment_projections"].get(ep_id)
    if ep is None:
        err("ERR_ENROLLMENT_PROJECTION_NOT_FOUND",
            "No enrollment projection with the given id", 404)
    # state gate
    if bv["status"] != "DRAFT":
        err("ERR_BUDGET_VERSION_NOT_DRAFT",
            "Staffing allocation mutation requires the budget version DRAFT", 409)
    # uniqueness within version
    if any(s["budget_version_id"] == bid and s["grade_band"] == band
           and s["status"] != "SUPERSEDED"
           for s in db["staffing_allocations"].values()):
        err("ERR_DUPLICATE_GRADE_BAND",
            "An allocation for this grade band already exists in the budget version", 409)
    # cross-fiscal-year reference
    if ep["fiscal_year_id"] != bv["fiscal_year_id"]:
        err("ERR_CROSS_FISCAL_YEAR_REFERENCE",
            "enrollment_projection_id belongs to a different fiscal year than the budget version",
            422)
    if ep["grade_band"] != band:
        err("ERR_INVALID_FIELD_VALUE",
            "grade_band must equal the referenced projection's grade_band", 422)
    required = compute_required_fte(ep)
    if alloc > required:
        err("ERR_ALLOCATION_EXCEEDS_FORMULA",
            "allocated_fte > formula required_fte", 422)
    fy = fy_of_budget_version(bv)
    current_sum = sum(s["allocated_fte"] for s in db["staffing_allocations"].values()
                      if s["budget_version_id"] == bid and s["status"] in ("DRAFT", "AUTHORIZED"))
    if current_sum + alloc > fy["fte_ceiling"]:
        err("ERR_FTE_CEILING_EXCEEDED",
            "Sum of allocated_fte over the budget version's allocations would exceed the fiscal year's fte_ceiling",
            422)
    ts = ts_now()
    sa = {
        "id": new_id(), "budget_version_id": bid,
        "enrollment_projection_id": ep_id, "grade_band": band,
        "required_fte": required, "allocated_fte": alloc,
        "positions_fte_total": 0,
        "cost_estimate_projected": round_half_up_2(alloc * 62000 * 1.34),
        "cost_estimate_actual": 0,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["staffing_allocations"][sa["id"]] = sa
    return success_obj(sa_view(sa), 201)


@app.route("/district/budget-versions/<bid>/staffing-allocations", methods=["GET"])
def list_staffing_allocations(bid):
    require_auth(ROLES)
    get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
               "No budget version with the given id")
    items = sorted([s for s in db["staffing_allocations"].values()
                    if s["budget_version_id"] == bid], key=lambda s: s["created_at"])
    total = len(items)
    return success_list([sa_view(s) for s in items], total)


@app.route("/district/enrollment-projections/<eid>/staffing-allocations", methods=["GET"])
def list_allocations_by_projection(eid):
    require_auth(ROLES)
    get_or_404("enrollment_projections", eid, "ERR_ENROLLMENT_PROJECTION_NOT_FOUND",
               "No enrollment projection with the given id")
    items = sorted([s for s in db["staffing_allocations"].values()
                    if s["enrollment_projection_id"] == eid],
                   key=lambda s: s["created_at"])
    total = len(items)
    return success_list([sa_view(s) for s in items], total)


@app.route("/district/staffing-allocations/<saId>", methods=["GET"])
def get_staffing_allocation(saId):
    require_auth(ROLES)
    sa = get_or_404("staffing_allocations", saId, "ERR_STAFFING_ALLOCATION_NOT_FOUND",
                    "No staffing allocation with the given id")
    return success_obj(sa_view(sa))


# =========================================================================
# Position
# =========================================================================

@app.route("/district/staffing-allocations/<sid>/positions", methods=["POST"])
def create_position(sid):
    require_auth(["BudgetAnalyst"])
    sa = get_or_404("staffing_allocations", sid, "ERR_STAFFING_ALLOCATION_NOT_FOUND",
                    "No staffing allocation with the given id")
    data = body()
    title = as_str(data, "title")
    fte = as_number(data, "fte")
    base_salary = as_number(data, "base_salary")
    if fte not in (0.5, 1.0):
        err("ERR_INVALID_FIELD_VALUE", "fte must be 0.5 or 1.0", 422)
    if base_salary <= 0:
        err("ERR_INVALID_FIELD_VALUE", "base_salary must be > 0", 422)
    headroom = sa["allocated_fte"] - sum(
        p["fte"] for p in db["positions"].values()
        if p["staffing_allocation_id"] == sid and p["status"] != "ELIMINATED")
    if fte > headroom:
        err("ERR_POSITION_FTE_EXCEEDED",
            "Position fte exceeds the allocation's remaining FTE headroom", 422)
    ts = ts_now()
    status = "OPEN" if sa["status"] == "AUTHORIZED" else "PROPOSED"
    p = {
        "id": new_id(), "staffing_allocation_id": sid, "title": title,
        "fte": fte, "base_salary": base_salary, "incumbent_salary": None,
        "status": status, "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["positions"][p["id"]] = p
    recompute_allocation(sa)
    if status == "OPEN":
        fy = fy_of_allocation(sa)
        if fy:
            recompute_fy_staffing(fy)
    return success_obj(pos_view(p), 201)


@app.route("/district/staffing-allocations/<sid>/positions", methods=["GET"])
def list_positions(sid):
    require_auth(ROLES)
    get_or_404("staffing_allocations", sid, "ERR_STAFFING_ALLOCATION_NOT_FOUND",
               "No staffing allocation with the given id")
    items = sorted([p for p in db["positions"].values()
                    if p["staffing_allocation_id"] == sid],
                   key=lambda p: p["created_at"])
    total = len(items)
    return success_list([pos_view(p) for p in items], total)


@app.route("/district/positions/<pId>/fill", methods=["POST"])
def fill_position(pId):
    require_auth(["Superintendent"])
    p = get_or_404("positions", pId, "ERR_POSITION_NOT_FOUND",
                   "No position with the given id")
    data = body()
    salary = data.get("incumbent_salary")
    if salary is None:
        err("ERR_INVALID_FIELD_VALUE", "incumbent_salary must be supplied", 422)
    if isinstance(salary, bool) or not isinstance(salary, (int, float)):
        err("ERR_INVALID_REQUEST", "incumbent_salary must be a number", 400)
    if salary <= 0:
        err("ERR_INVALID_FIELD_VALUE", "incumbent_salary must be > 0", 422)
    if p["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Position is not OPEN", 409)
    p["status"] = "FILLED"
    p["incumbent_salary"] = salary
    bump(p)
    sa = db["staffing_allocations"][p["staffing_allocation_id"]]
    recompute_allocation(sa)
    fy = fy_of_position(p)
    if fy:
        recompute_fy_staffing(fy)
    return success_obj(pos_view(p))


@app.route("/district/positions/<pId>/vacate", methods=["POST"])
def vacate_position(pId):
    require_auth(["Superintendent"])
    p = get_or_404("positions", pId, "ERR_POSITION_NOT_FOUND",
                   "No position with the given id")
    if p["status"] != "FILLED":
        err("ERR_INVALID_STATE", "Position is not FILLED", 409)
    p["status"] = "OPEN"
    p["incumbent_salary"] = None
    bump(p)
    sa = db["staffing_allocations"][p["staffing_allocation_id"]]
    recompute_allocation(sa)
    fy = fy_of_position(p)
    if fy:
        recompute_fy_staffing(fy)
    return success_obj(pos_view(p))


@app.route("/district/positions/<pId>/eliminate", methods=["POST"])
def eliminate_position(pId):
    require_auth(["Superintendent"])
    p = get_or_404("positions", pId, "ERR_POSITION_NOT_FOUND",
                   "No position with the given id")
    if p["status"] == "FILLED":
        err("ERR_INVALID_STATE",
            "An operator may not eliminate a FILLED position", 409)
    if p["status"] not in ("PROPOSED", "OPEN"):
        err("ERR_INVALID_STATE",
            "Position is not PROPOSED or OPEN", 409)
    was_open = p["status"] == "OPEN"
    p["status"] = "ELIMINATED"
    bump(p)
    sa = db["staffing_allocations"][p["staffing_allocation_id"]]
    recompute_allocation(sa)
    if was_open:
        fy = fy_of_position(p)
        if fy:
            recompute_fy_staffing(fy)
    return success_obj(pos_view(p))


# =========================================================================
# RevenueEstimate
# =========================================================================

PTELL_CPI_MAX = 0.05
OPERATING_RATE_CAP = 1.8400
FOUNDATION_PER_PUPIL = 7600
LOCAL_CAPACITY_RATE = 0.023


def compute_estimate_fields(r, fy, variant):
    """variant: 'PROVISIONAL' uses projected pupils + eav_prior;
       'CERTIFIED' uses certified pupils + eav_current."""
    if variant == "PROVISIONAL":
        eav_basis = fy["eav_prior"]
        pupils_weight = sum(e["weighted_pupils_projected"]
                            for e in db["enrollment_projections"].values()
                            if e["fiscal_year_id"] == fy["id"])
        r["eav_basis"] = "PRIOR"
    else:
        eav_basis = fy["eav_current"]
        pupils_weight = sum(e["weighted_pupils_certified"] or 0
                            for e in db["enrollment_projections"].values()
                            if e["fiscal_year_id"] == fy["id"])
        r["eav_basis"] = "CURRENT"
    state_aid = max(0.0, FOUNDATION_PER_PUPIL * pupils_weight
                    - LOCAL_CAPACITY_RATE * eav_basis)
    r["state_aid"] = round_half_up_2(state_aid)
    r["operating_rate"] = round_half_up_4(
        r["capped_operating_levy"] / eav_basis * 100) if eav_basis else 0.0
    r["debt_service_rate"] = round_half_up_4(
        r["debt_service_levy"] / eav_basis * 100) if eav_basis else 0.0
    r["total_tax_rate"] = r["operating_rate"] + r["debt_service_rate"]
    r["total_levy"] = round_half_up_2(
        r["capped_operating_levy"] + r["debt_service_levy"])
    r["total_revenue"] = round_half_up_2(
        r["state_aid"] + r["total_levy"] + r["other_revenue"])


@app.route("/district/budget-versions/<bid>/revenue-estimates", methods=["POST"])
def create_revenue_estimate(bid):
    require_auth(["BusinessManager"])
    bv = get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    data = body()
    op_req = as_number(data, "operating_levy_request")
    debt_levy = as_number(data, "debt_service_levy")
    other_rev = as_number(data, "other_revenue")
    cpi = as_number(data, "cpi_rate")
    if op_req <= 0:
        err("ERR_INVALID_FIELD_VALUE", "operating_levy_request must be > 0", 422)
    if debt_levy < 0:
        err("ERR_INVALID_FIELD_VALUE", "debt_service_levy must be >= 0", 422)
    if other_rev < 0:
        err("ERR_INVALID_FIELD_VALUE", "other_revenue must be >= 0", 422)
    if any(r["budget_version_id"] == bid for r in db["revenue_estimates"].values()):
        err("ERR_REVENUE_ESTIMATE_EXISTS",
            "The budget version already has a revenue estimate", 409)
    fy = fy_of_budget_version(bv)
    ptell_cap = fy["prior_year_extension"] * (1 + min(cpi, PTELL_CPI_MAX))
    capped = min(op_req, ptell_cap)
    ts = ts_now()
    r = {
        "id": new_id(), "budget_version_id": bid,
        "operating_levy_request": op_req, "debt_service_levy": debt_levy,
        "other_revenue": other_rev, "cpi_rate": cpi,
        "capped_operating_levy": round_half_up_2(capped),
        "total_levy": 0, "eav_basis": "PRIOR",
        "state_aid": 0, "operating_rate": 0, "debt_service_rate": 0,
        "total_tax_rate": 0, "total_revenue": 0,
        "state_aid_provisional": None, "total_revenue_provisional": None,
        "status": "PROVISIONAL", "created_at": ts, "updated_at": ts, "version": 1,
    }
    compute_estimate_fields(r, fy, "PROVISIONAL")
    if r["operating_rate"] > OPERATING_RATE_CAP:
        err("ERR_TAX_RATE_CAP_EXCEEDED",
            "Rounded operating rate would exceed 1.8400", 422)
    db["revenue_estimates"][r["id"]] = r
    return success_obj(re_view(r), 201)


@app.route("/district/budget-versions/<bid>/revenue-estimates", methods=["GET"])
def list_revenue_estimates(bid):
    require_auth(ROLES)
    get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
               "No budget version with the given id")
    items = sorted([r for r in db["revenue_estimates"].values()
                    if r["budget_version_id"] == bid], key=lambda r: r["created_at"])
    total = len(items)
    return success_list([re_view(r) for r in items], total)


@app.route("/district/revenue-estimates/<reId>/recertify", methods=["POST"])
def recertify_revenue_estimate(reId):
    require_auth(["BusinessManager"])
    r = get_or_404("revenue_estimates", reId, "ERR_REVENUE_ESTIMATE_NOT_FOUND",
                   "No revenue estimate with the given id")
    if r["status"] != "PROVISIONAL":
        err("ERR_INVALID_STATE", "Revenue estimate is not PROVISIONAL", 409)
    bv = db["budget_versions"][r["budget_version_id"]]
    fy = fy_of_budget_version(bv)
    projections = [e for e in db["enrollment_projections"].values()
                   if e["fiscal_year_id"] == fy["id"]]
    if any(e["status"] != "CERTIFIED" for e in projections):
        err("ERR_PROJECTIONS_NOT_ALL_CERTIFIED",
            "Recertification requires every enrollment projection of the fiscal year to be CERTIFIED",
            409)
    r["state_aid_provisional"] = r["state_aid"]
    r["total_revenue_provisional"] = r["total_revenue"]
    compute_estimate_fields(r, fy, "CERTIFIED")
    if r["operating_rate"] > OPERATING_RATE_CAP:
        err("ERR_TAX_RATE_CAP_EXCEEDED",
            "Rounded operating rate would exceed 1.8400", 422)
    r["status"] = "RECERTIFIED"
    bump(r)
    return success_obj(re_view(r))


# =========================================================================
# PublicHearing
# =========================================================================

@app.route("/district/budget-versions/<bid>/hearings", methods=["POST"])
def create_hearing(bid):
    require_auth(["BoardClerk"])
    bv = get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
                    "No budget version with the given id")
    data = body()
    venue = as_str(data, "venue")
    hearing_date = as_str(data, "hearing_date")
    hd = parse_date(hearing_date, "hearing_date")
    if bv["status"] != "PROPOSED":
        err("ERR_INVALID_STATE",
            "Hearing creation requires the budget version PROPOSED", 409)
    notice = today()
    if hd < notice + timedelta(days=10):
        err("ERR_NOTICE_WINDOW_TOO_SHORT",
            "hearing_date < notice_publication_date + 10 days", 409)
    for h in db["public_hearings"].values():
        if h["status"] in ("NOTICE_PUBLISHED", "HELD") \
                and h["venue"] == venue and h["hearing_date"] == hearing_date:
            err("ERR_HEARING_VENUE_DATE_CONFLICT",
                "Another hearing with status NOTICE_PUBLISHED or HELD already occupies this venue on this date",
                409)
    ts = ts_now()
    h = {
        "id": new_id(), "budget_version_id": bid, "venue": venue,
        "hearing_date": hearing_date,
        "notice_publication_date": notice.strftime("%Y-%m-%d"),
        "status": "NOTICE_PUBLISHED", "created_at": ts, "updated_at": ts,
        "version": 1,
    }
    db["public_hearings"][h["id"]] = h
    return success_obj(ph_view(h), 201)


@app.route("/district/budget-versions/<bid>/hearings", methods=["GET"])
def list_hearings(bid):
    require_auth(ROLES)
    get_or_404("budget_versions", bid, "ERR_BUDGET_VERSION_NOT_FOUND",
               "No budget version with the given id")
    items = sorted([h for h in db["public_hearings"].values()
                    if h["budget_version_id"] == bid], key=lambda h: h["created_at"])
    total = len(items)
    return success_list([ph_view(h) for h in items], total)


@app.route("/district/public-hearings/<hId>/hold", methods=["POST"])
def hold_hearing(hId):
    require_auth(["BoardClerk"])
    h = get_or_404("public_hearings", hId, "ERR_PUBLIC_HEARING_NOT_FOUND",
                   "No public hearing with the given id")
    bv = db["budget_versions"][h["budget_version_id"]]
    if h["status"] != "NOTICE_PUBLISHED":
        err("ERR_INVALID_STATE", "Hearing is not NOTICE_PUBLISHED", 409)
    if bv["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", "Owning budget version is not PROPOSED", 409)
    if today() != parse_date(h["hearing_date"], "hearing_date"):
        err("ERR_HEARING_DATE_NOT_TODAY",
            "hold attempted when today's clock date != hearing_date", 409)
    h["status"] = "HELD"
    bump(h)
    bv["status"] = "HEARING_HELD"
    bv["hearing_held_date"] = h["hearing_date"]
    bump(bv)
    return success_obj(ph_view(h))


@app.route("/district/public-hearings/<hId>/cancel", methods=["POST"])
def cancel_hearing(hId):
    require_auth(["BoardClerk"])
    h = get_or_404("public_hearings", hId, "ERR_PUBLIC_HEARING_NOT_FOUND",
                   "No public hearing with the given id")
    if h["status"] != "NOTICE_PUBLISHED":
        err("ERR_INVALID_STATE", "Hearing is not NOTICE_PUBLISHED", 409)
    h["status"] = "CANCELLED"
    bump(h)
    return success_obj(ph_view(h))


# =========================================================================
# Election
# =========================================================================

def first_tuesday(year, month):
    d = date(year, month, 1)
    # weekday(): Monday=0 ... Sunday=6; Tuesday=1
    offset = (1 - d.weekday()) % 7
    return d + timedelta(days=offset)


def is_statutory_election_date(d):
    if d.month not in (3, 6, 11):
        return False
    return d == first_tuesday(d.year, d.month)


@app.route("/district/elections", methods=["POST"])
def create_election():
    require_auth(["BoardClerk"])
    data = body()
    election_date = as_str(data, "election_date")
    etype = as_enum(data, "election_type", ["REGULAR", "SPECIAL"])
    ed = parse_date(election_date, "election_date")
    if not is_statutory_election_date(ed):
        err("ERR_STATUTORY_ELECTION_DATE",
            "election_date is not the first Tuesday of March, June, or November", 409)
    ts = ts_now()
    e = {
        "id": new_id(), "election_date": election_date,
        "election_type": etype, "canvassed_at": None,
        "status": "SCHEDULED", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["elections"][e["id"]] = e
    return success_obj(el_view(e), 201)


@app.route("/district/elections", methods=["GET"])
def list_elections():
    require_auth(ROLES)
    items = sorted(db["elections"].values(), key=lambda e: e["created_at"])
    total = len(items)
    return success_list([el_view(e) for e in items], total)


@app.route("/district/elections/<eId>", methods=["GET"])
def get_election(eId):
    require_auth(ROLES)
    e = get_or_404("elections", eId, "ERR_ELECTION_NOT_FOUND",
                   "No election with the given id")
    return success_obj(el_view(e))


@app.route("/district/elections/<eId>/canvass", methods=["POST"])
def canvass_election(eId):
    require_auth(["BoardClerk"])
    e = get_or_404("elections", eId, "ERR_ELECTION_NOT_FOUND",
                   "No election with the given id")
    data = body()
    results = data.get("results")
    if results is None or not isinstance(results, list):
        err("ERR_INVALID_REQUEST", "results must be an array", 400)
    if e["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Election is not SCHEDULED", 409)
    ed = parse_date(e["election_date"], "election_date")
    if today() <= ed:
        err("ERR_CANVASS_BEFORE_ELECTION",
            "Canvass attempted when today <= election_date", 409)
    certified = [m for m in db["ballot_measures"].values()
                 if m["election_id"] == eId and m["status"] == "LANGUAGE_CERTIFIED"]
    certified_ids = {m["id"] for m in certified}
    seen = set()
    entries = []
    for entry in results:
        if not isinstance(entry, dict):
            err("ERR_INVALID_REQUEST", "Each results entry must be an object", 400)
        mid = entry.get("ballot_measure_id")
        if mid is None:
            err("ERR_INVALID_REQUEST",
                "Each results entry requires ballot_measure_id", 400)
        m = db["ballot_measures"].get(mid)
        if m is None or m["election_id"] != eId:
            err("ERR_BALLOT_MEASURE_NOT_FOUND",
                "No ballot measure with the given id", 404)
        if mid in seen or mid not in certified_ids:
            err("ERR_CANVASS_INCOMPLETE",
                "results do not cover every LANGUAGE_CERTIFIED measure of the election exactly once",
                422)
        yes = entry.get("yes_votes")
        no = entry.get("no_votes")
        if isinstance(yes, bool) or not isinstance(yes, int) or yes < 0:
            err("ERR_INVALID_FIELD_VALUE", "yes_votes must be a non-negative integer", 422)
        if isinstance(no, bool) or not isinstance(no, int) or no < 0:
            err("ERR_INVALID_FIELD_VALUE", "no_votes must be a non-negative integer", 422)
        seen.add(mid)
        entries.append((m, yes, no))
    if seen != certified_ids:
        err("ERR_CANVASS_INCOMPLETE",
            "results do not cover every LANGUAGE_CERTIFIED measure of the election exactly once",
            422)
    count = 0
    for m, yes, no in entries:
        m["yes_votes"] = yes
        m["no_votes"] = no
        passed = yes > no
        m["status"] = "PASSED" if passed else "FAILED"
        bump(m)
        count += 1
        bp = db["bond_proposals"].get(m["bond_proposal_id"])
        if bp is not None and bp["status"] == "REFERRED":
            if passed:
                bp["status"] = "PASSED"
                bp["passed_at"] = ts_now()
                bump(bp)
                for p in db["bond_projects"].values():
                    if p["bond_proposal_id"] == bp["id"] and p["status"] == "PLANNED":
                        p["status"] = "AUTHORIZED"
                        p["authorized_amount"] = p["estimated_cost"]
                        touch(p)
            else:
                bp["status"] = "FAILED"
                bump(bp)
    e["status"] = "CANVASSED"
    e["canvassed_at"] = ts_now()
    bump(e)
    return success_obj({"canvassed_count": count})


# =========================================================================
# BondProposal
# =========================================================================

DEBT_LIMIT_PCT = 0.069


@app.route("/district/fiscal-years/<fid>/bond-proposals", methods=["POST"])
def create_bond_proposal(fid):
    require_auth(["BoardClerk"])
    fy = get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
                    "No fiscal year with the given id")
    data = body()
    title = as_str(data, "question_title")
    purpose = as_str(data, "purpose")
    total = as_number(data, "total_amount")
    if total <= 0:
        err("ERR_INVALID_FIELD_VALUE", "total_amount must be > 0", 422)
    if fy["status"] != "OPEN":
        err("ERR_FISCAL_YEAR_NOT_OPEN", "Fiscal year is not OPEN", 409)
    ts = ts_now()
    bp = {
        "id": new_id(), "fiscal_year_id": fid, "question_title": title,
        "purpose": purpose, "total_amount": round_half_up_2(total),
        "remaining_authorization": round_half_up_2(total),
        "available_proceeds": 0, "passed_at": None, "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["bond_proposals"][bp["id"]] = bp
    return success_obj(bp_view(bp), 201)


@app.route("/district/fiscal-years/<fid>/bond-proposals", methods=["GET"])
def list_bond_proposals(fid):
    require_auth(ROLES)
    get_or_404("fiscal_years", fid, "ERR_FISCAL_YEAR_NOT_FOUND",
               "No fiscal year with the given id")
    items = sorted([b for b in db["bond_proposals"].values()
                    if b["fiscal_year_id"] == fid], key=lambda b: b["created_at"])
    total = len(items)
    return success_list([bp_view(b) for b in items], total)


@app.route("/district/bond-proposals/<bpId>", methods=["GET"])
def get_bond_proposal(bpId):
    require_auth(ROLES)
    bp = get_or_404("bond_proposals", bpId, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    return success_obj(bp_view(bp))


@app.route("/district/bond-proposals/<bpId>/approve-board", methods=["POST"])
def approve_board(bpId):
    require_auth(["BoardClerk"])
    bp = get_or_404("bond_proposals", bpId, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    if bp["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Bond proposal is not DRAFT", 409)
    planned = [p for p in db["bond_projects"].values()
               if p["bond_proposal_id"] == bpId and p["status"] == "PLANNED"]
    if not planned:
        err("ERR_EMPTY_PROJECT_LIST",
            "Board approval requires at least one PLANNED project on the proposal", 409)
    fy = fy_of_proposal(bp)
    consumed = fy["outstanding_debt_principal"]
    for other in db["bond_proposals"].values():
        if other["fiscal_year_id"] == fy["id"] and other["id"] != bpId \
                and other["status"] in ("BOARD_APPROVED", "REFERRED", "PASSED"):
            consumed += other["remaining_authorization"]
    legal_limit = DEBT_LIMIT_PCT * fy["eav_current"]
    if consumed + bp["total_amount"] > legal_limit:
        err("ERR_BOND_CAPACITY_EXCEEDED",
            "Approval would push consumed bond capacity over 6.9% of current EAV", 422)
    bp["status"] = "BOARD_APPROVED"
    bump(bp)
    return success_obj(bp_view(bp))


@app.route("/district/bond-proposals/<bpId>/revise", methods=["POST"])
def revise_bond_proposal(bpId):
    require_auth(["BoardClerk"])
    bp = get_or_404("bond_proposals", bpId, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    if bp["status"] != "FAILED":
        err("ERR_INVALID_STATE", "Bond proposal is not FAILED", 409)
    bp["status"] = "DRAFT"
    bump(bp)
    return success_obj(bp_view(bp))


# =========================================================================
# BondProject
# =========================================================================

SITE_BUFFER_DAYS = 14


@app.route("/district/bond-proposals/<bid>/projects", methods=["POST"])
def create_bond_project(bid):
    require_auth(["BoardClerk"])
    bp = get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    data = body()
    name = as_str(data, "name")
    site_code = as_str(data, "site_code")
    cost = as_number(data, "estimated_cost")
    cs = as_str(data, "construction_start")
    ce = as_str(data, "construction_end")
    rank = as_int(data, "priority_rank")
    if cost <= 0:
        err("ERR_INVALID_FIELD_VALUE", "estimated_cost must be > 0", 422)
    sd = parse_date(cs, "construction_start")
    ed = parse_date(ce, "construction_end")
    if ed <= sd:
        err("ERR_INVALID_FIELD_VALUE",
            "construction_end must be after construction_start", 422)
    if bp["status"] != "DRAFT":
        err("ERR_INVALID_STATE",
            "Projects may only be added while the proposal is DRAFT", 409)
    if any(p["bond_proposal_id"] == bid and p["status"] != "CANCELLED"
           and p["priority_rank"] == rank for p in db["bond_projects"].values()):
        err("ERR_DUPLICATE_PRIORITY_RANK",
            "priority_rank already used by another non-CANCELLED project of the proposal", 409)
    # site window conflict
    for q in db["bond_projects"].values():
        if q["site_code"] != site_code:
            continue
        if q["status"] not in ("PLANNED", "AUTHORIZED", "IN_PROGRESS"):
            continue
        qs = parse_date(q["construction_start"], "construction_start")
        qe = parse_date(q["construction_end"], "construction_end")
        overlap = (sd < qe) and (qs < ed)
        if overlap:
            err("ERR_SITE_WINDOW_CONFLICT",
                "Another non-CANCELLED project at the same site has an overlapping construction window",
                409)
        if qe <= sd:
            gap = (sd - qe).days
        else:
            gap = (qs - ed).days
        if gap < SITE_BUFFER_DAYS:
            err("ERR_SITE_WINDOW_CONFLICT",
                "Gap between construction windows at the same site is less than 14 days",
                409)
    current_sum = sum(p["estimated_cost"] for p in db["bond_projects"].values()
                      if p["bond_proposal_id"] == bid and p["status"] != "CANCELLED")
    if current_sum + cost > bp["total_amount"]:
        err("ERR_PROJECT_LIST_EXCEEDS_AMOUNT",
            "Sum of estimated_cost over the proposal's non-CANCELLED projects would exceed total_amount",
            422)
    ts = ts_now()
    p = {
        "id": new_id(), "bond_proposal_id": bid, "name": name,
        "site_code": site_code, "estimated_cost": round_half_up_2(cost),
        "construction_start": cs, "construction_end": ce,
        "priority_rank": rank, "authorized_amount": 0, "spent_amount": 0,
        "status": "PLANNED", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["bond_projects"][p["id"]] = p
    return success_obj(prj_view(p), 201)


@app.route("/district/bond-proposals/<bid>/projects", methods=["GET"])
def list_bond_projects(bid):
    require_auth(ROLES)
    get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
               "No bond proposal with the given id")
    items = sorted([p for p in db["bond_projects"].values()
                    if p["bond_proposal_id"] == bid], key=lambda p: p["created_at"])
    total = len(items)
    return success_list([prj_view(p) for p in items], total)


@app.route("/district/bond-projects/<prjId>", methods=["GET"])
def get_bond_project(prjId):
    require_auth(ROLES)
    p = get_or_404("bond_projects", prjId, "ERR_BOND_PROJECT_NOT_FOUND",
                   "No bond project with the given id")
    return success_obj(prj_view(p))


@app.route("/district/bond-projects/<prjId>/activate", methods=["POST"])
def activate_project(prjId):
    require_auth(["Superintendent"])
    p = get_or_404("bond_projects", prjId, "ERR_BOND_PROJECT_NOT_FOUND",
                   "No bond project with the given id")
    if p["status"] != "AUTHORIZED":
        err("ERR_INVALID_STATE", "Project is not AUTHORIZED", 409)
    has_closed = any(s["bond_proposal_id"] == p["bond_proposal_id"]
                     and s["status"] == "CLOSED"
                     for s in db["bond_sales"].values())
    if not has_closed:
        err("ERR_NO_CLOSED_BOND_SALE",
            "Project activation requires at least one CLOSED bond sale on the proposal", 409)
    p["status"] = "IN_PROGRESS"
    bump(p)
    return success_obj(prj_view(p))


@app.route("/district/bond-projects/<prjId>/complete", methods=["POST"])
def complete_project(prjId):
    require_auth(["Superintendent"])
    p = get_or_404("bond_projects", prjId, "ERR_BOND_PROJECT_NOT_FOUND",
                   "No bond project with the given id")
    if p["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", "Project is not IN_PROGRESS", 409)
    for e in db["project_expenditures"].values():
        if e["bond_project_id"] == prjId and e["payment_status"] != "VOIDED" \
                and e["review_status"] in ("PENDING_REVIEW", "FLAGGED"):
            err("ERR_UNREVIEWED_EXPENDITURES_EXIST",
                "Project completion blocked by expenditures still PENDING_REVIEW or FLAGGED",
                409)
    p["status"] = "COMPLETED"
    bump(p)
    for e in db["project_expenditures"].values():
        if e["bond_project_id"] == prjId and e["payment_status"] == "DISBURSED":
            e["payment_status"] = "RETAINAGE_RELEASED"
            touch(e)
    return success_obj(prj_view(p))


@app.route("/district/bond-projects/<prjId>/cancel", methods=["POST"])
def cancel_project(prjId):
    require_auth(["Superintendent"])
    p = get_or_404("bond_projects", prjId, "ERR_BOND_PROJECT_NOT_FOUND",
                   "No bond project with the given id")
    if p["status"] not in ("PLANNED", "AUTHORIZED"):
        err("ERR_INVALID_STATE", "Project is not PLANNED or AUTHORIZED", 409)
    if p["status"] == "AUTHORIZED":
        active = any(e["bond_project_id"] == prjId and e["payment_status"] != "VOIDED"
                     for e in db["project_expenditures"].values())
        if active:
            err("ERR_INVALID_STATE",
                "An AUTHORIZED project with active expenditures may not be cancelled", 409)
    p["status"] = "CANCELLED"
    p["authorized_amount"] = 0
    bump(p)
    return success_obj(prj_view(p))


# =========================================================================
# BallotMeasure
# =========================================================================

BALLOT_WORD_LIMIT = 200
CERTIFICATION_LEAD_DAYS = 61
CAMPAIGN_WINDOW_DAYS = 30


@app.route("/district/elections/<eid>/ballot-measures", methods=["POST"])
def create_ballot_measure(eid):
    uid, _ = require_auth(["BoardClerk"])
    election = get_or_404("elections", eid, "ERR_ELECTION_NOT_FOUND",
                          "No election with the given id")
    data = body()
    bp_id = as_str(data, "bond_proposal_id")
    language = as_str(data, "ballot_language")
    bp = db["bond_proposals"].get(bp_id)
    if bp is None:
        err("ERR_BOND_PROPOSAL_NOT_FOUND", "No bond proposal with the given id", 404)
    if bp["status"] != "BOARD_APPROVED":
        err("ERR_INVALID_STATE",
            "The referenced proposal must be BOARD_APPROVED", 409)
    if any(m["election_id"] == eid and m["bond_proposal_id"] == bp_id
           for m in db["ballot_measures"].values()):
        err("ERR_DUPLICATE_BALLOT_MEASURE",
            "The proposal already has a ballot measure on this election", 409)
    wc = len(language.split())
    ts = ts_now()
    m = {
        "id": new_id(), "election_id": eid, "bond_proposal_id": bp_id,
        "ballot_language": language, "word_count": wc,
        "drafted_by_user_id": uid, "certified_by_user_id": None,
        "yes_votes": None, "no_votes": None, "status": "LANGUAGE_DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["ballot_measures"][m["id"]] = m
    return success_obj(bm_view(m), 201)


@app.route("/district/elections/<eid>/ballot-measures", methods=["GET"])
def list_ballot_measures(eid):
    require_auth(ROLES)
    get_or_404("elections", eid, "ERR_ELECTION_NOT_FOUND",
               "No election with the given id")
    items = sorted([m for m in db["ballot_measures"].values()
                    if m["election_id"] == eid], key=lambda m: m["created_at"])
    total = len(items)
    return success_list([bm_view(m) for m in items], total)


@app.route("/district/bond-proposals/<bid>/ballot-measures", methods=["GET"])
def list_measures_by_proposal(bid):
    require_auth(ROLES)
    get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
               "No bond proposal with the given id")
    items = sorted([m for m in db["ballot_measures"].values()
                    if m["bond_proposal_id"] == bid], key=lambda m: m["created_at"])
    total = len(items)
    return success_list([bm_view(m) for m in items], total)


@app.route("/district/ballot-measures/<bmId>", methods=["GET"])
def get_ballot_measure(bmId):
    require_auth(ROLES)
    m = get_or_404("ballot_measures", bmId, "ERR_BALLOT_MEASURE_NOT_FOUND",
                   "No ballot measure with the given id")
    return success_obj(bm_view(m))


@app.route("/district/ballot-measures/<bmId>/certify", methods=["POST"])
def certify_ballot_measure(bmId):
    uid, _ = require_auth(["BoardClerk"])
    m = get_or_404("ballot_measures", bmId, "ERR_BALLOT_MEASURE_NOT_FOUND",
                   "No ballot measure with the given id")
    if m["status"] != "LANGUAGE_DRAFT":
        err("ERR_INVALID_STATE", "Ballot measure is not LANGUAGE_DRAFT", 409)
    if uid == m["drafted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "The certifying operator must differ from the drafting operator", 403)
    election = db["elections"][m["election_id"]]
    ed = parse_date(election["election_date"], "election_date")
    deadline = ed - timedelta(days=CERTIFICATION_LEAD_DAYS)
    if today() > deadline:
        err("ERR_CERTIFICATION_DEADLINE_PASSED",
            "Ballot certification attempted after election_date - 61 days", 409)
    if m["word_count"] > BALLOT_WORD_LIMIT:
        err("ERR_BALLOT_LANGUAGE_TOO_LONG",
            "Ballot language word_count > 200 at certification", 422)
    m["certified_by_user_id"] = uid
    m["status"] = "LANGUAGE_CERTIFIED"
    bump(m)
    bp = db["bond_proposals"].get(m["bond_proposal_id"])
    if bp is not None and bp["status"] == "BOARD_APPROVED":
        bp["status"] = "REFERRED"
        bump(bp)
    return success_obj(bm_view(m))


@app.route("/district/ballot-measures/<bmId>/publications", methods=["POST"])
def create_publication(bmId):
    uid, _ = require_auth(["BoardClerk"])
    m = get_or_404("ballot_measures", bmId, "ERR_BALLOT_MEASURE_NOT_FOUND",
                   "No ballot measure with the given id")
    data = body()
    ptype = as_enum(data, "publication_type", ["FACTUAL", "PROMOTIONAL"])
    content = as_str(data, "content")
    if ptype == "PROMOTIONAL":
        err("ERR_PROHIBITED_CAMPAIGN_ACTIVITY",
            "PROMOTIONAL district publication about a ballot measure is always prohibited",
            403)
    if m["status"] == "LANGUAGE_CERTIFIED":
        election = db["elections"][m["election_id"]]
        ed = parse_date(election["election_date"], "election_date")
        window_start = ed - timedelta(days=CAMPAIGN_WINDOW_DAYS)
        if window_start <= today() <= ed:
            err("ERR_CAMPAIGN_RESTRICTION_WINDOW",
                "FACTUAL publication about a certified measure inside the campaign restriction window",
                409)
    ts = ts_now()
    pub = {
        "id": new_id(), "ballot_measure_id": bmId,
        "publication_type": ptype, "content": content,
        "published_by_user_id": uid, "status": "PUBLISHED", "created_at": ts,
    }
    db["district_publications"][pub["id"]] = pub
    return success_obj(pub_view(pub), 201)


@app.route("/district/ballot-measures/<bmId>/publications", methods=["GET"])
def list_publications(bmId):
    require_auth(ROLES)
    get_or_404("ballot_measures", bmId, "ERR_BALLOT_MEASURE_NOT_FOUND",
               "No ballot measure with the given id")
    items = sorted([p for p in db["district_publications"].values()
                    if p["ballot_measure_id"] == bmId],
                   key=lambda p: p["created_at"])
    total = len(items)
    return success_list([pub_view(p) for p in items], total)


# =========================================================================
# BondSale
# =========================================================================

@app.route("/district/bond-proposals/<bid>/bond-sales", methods=["POST"])
def create_bond_sale(bid):
    require_auth(["DistrictTreasurer"])
    bp = get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    data = body()
    series = as_str(data, "series_label")
    par = as_number(data, "par_amount")
    premium = as_number(data, "premium")
    costs = as_number(data, "issuance_costs")
    sale_date = as_str(data, "sale_date")
    if "expected_bond_proposal_version" not in data \
            or data["expected_bond_proposal_version"] is None:
        err("ERR_INVALID_REQUEST",
            "Missing required field: expected_bond_proposal_version", 400)
    expected = data["expected_bond_proposal_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST",
            "expected_bond_proposal_version must be an integer", 400)
    if par <= 0:
        err("ERR_INVALID_FIELD_VALUE", "par_amount must be > 0", 422)
    if premium < 0:
        err("ERR_INVALID_FIELD_VALUE", "premium must be >= 0", 422)
    if costs < 0:
        err("ERR_INVALID_FIELD_VALUE", "issuance_costs must be >= 0", 422)
    sd = parse_date(sale_date, "sale_date")
    if expected != bp["version"]:
        err("ERR_STALE_VERSION",
            "expected_bond_proposal_version does not match the bond proposal's current version",
            412)
    if bp["status"] != "PASSED":
        err("ERR_INVALID_STATE",
            "Bond sales require the proposal PASSED", 409)
    # sale_date <= passed_at + 36 months
    passed_raw = bp["passed_at"]
    passed_dt = parse_datetime_lenient(passed_raw, "passed_at")
    lapse = add_months(passed_dt.date(), 36)
    if sd > lapse:
        err("ERR_AUTHORIZATION_LAPSED",
            "sale_date later than proposal passed_at + 36 months", 409)
    if any(s["bond_proposal_id"] == bid and s["status"] != "CANCELLED"
           and s["series_label"] == series for s in db["bond_sales"].values()):
        err("ERR_DUPLICATE_SERIES_LABEL",
            "series_label already used by a non-CANCELLED sale of the proposal", 409)
    recompute_proposal(bp)
    if par > bp["remaining_authorization"]:
        err("ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION",
            "par_amount > proposal remaining_authorization", 422)
    net = round_half_up_2(par + premium - costs)
    if net <= 0:
        err("ERR_NONPOSITIVE_NET_PROCEEDS",
            "par_amount + premium - issuance_costs <= 0", 422)
    ts = ts_now()
    s = {
        "id": new_id(), "bond_proposal_id": bid, "series_label": series,
        "par_amount": round_half_up_2(par), "premium": premium,
        "issuance_costs": costs, "sale_date": sale_date, "net_proceeds": net,
        "status": "PLANNED", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["bond_sales"][s["id"]] = s
    recompute_proposal(bp)
    bump(bp)
    return success_obj(bs_view(s), 201)


@app.route("/district/bond-proposals/<bid>/bond-sales", methods=["GET"])
def list_bond_sales(bid):
    require_auth(ROLES)
    get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
               "No bond proposal with the given id")
    items = sorted([s for s in db["bond_sales"].values()
                    if s["bond_proposal_id"] == bid], key=lambda s: s["created_at"])
    total = len(items)
    return success_list([bs_view(s) for s in items], total)


@app.route("/district/bond-sales/<bsId>/close", methods=["POST"])
def close_bond_sale(bsId):
    require_auth(["DistrictTreasurer"])
    s = get_or_404("bond_sales", bsId, "ERR_BOND_SALE_NOT_FOUND",
                   "No bond sale with the given id")
    if s["status"] != "PLANNED":
        err("ERR_INVALID_STATE", "Bond sale is not PLANNED", 409)
    sd = parse_date(s["sale_date"], "sale_date")
    if today() < sd:
        err("ERR_SALE_NOT_YET_EFFECTIVE",
            "Bond sale close attempted before sale_date", 409)
    s["status"] = "CLOSED"
    bump(s)
    bp = db["bond_proposals"][s["bond_proposal_id"]]
    fy = fy_of_proposal(bp)
    if fy:
        fy["outstanding_debt_principal"] = round_half_up_2(
            fy["outstanding_debt_principal"] + s["par_amount"])
        touch(fy)
    recompute_proposal(bp)
    return success_obj(bs_view(s))


@app.route("/district/bond-sales/<bsId>/cancel", methods=["POST"])
def cancel_bond_sale(bsId):
    require_auth(["DistrictTreasurer"])
    s = get_or_404("bond_sales", bsId, "ERR_BOND_SALE_NOT_FOUND",
                   "No bond sale with the given id")
    if s["status"] != "PLANNED":
        err("ERR_INVALID_STATE", "Bond sale is not PLANNED", 409)
    s["status"] = "CANCELLED"
    bump(s)
    bp = db["bond_proposals"][s["bond_proposal_id"]]
    recompute_proposal(bp)
    return success_obj(bs_view(s))


# =========================================================================
# ProjectExpenditure
# =========================================================================

RETAINAGE_PCT = 0.10


@app.route("/district/bond-projects/<pid>/expenditures", methods=["POST"])
def create_expenditure(pid):
    require_auth(["DistrictTreasurer"])
    p = get_or_404("bond_projects", pid, "ERR_BOND_PROJECT_NOT_FOUND",
                   "No bond project with the given id")
    data = body()
    vendor = as_str(data, "vendor_name")
    amount = as_number(data, "amount")
    desc = as_str(data, "description")
    if amount <= 0:
        err("ERR_INVALID_FIELD_VALUE", "amount must be > 0", 422)
    if p["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE",
            "Expenditures require the project IN_PROGRESS", 409)
    recompute_project(p)
    available_budget = round_half_up_2(p["authorized_amount"] - p["spent_amount"])
    if amount > available_budget:
        err("ERR_PROJECT_BUDGET_EXCEEDED",
            "Expenditure amount > project available_budget", 422)
    bp = db["bond_proposals"][p["bond_proposal_id"]]
    recompute_proposal(bp)
    if amount > bp["available_proceeds"]:
        err("ERR_INSUFFICIENT_PROCEEDS",
            "Expenditure amount > proposal available_proceeds", 422)
    ts = ts_now()
    e = {
        "id": new_id(), "bond_project_id": pid, "vendor_name": vendor,
        "amount": round_half_up_2(amount), "description": desc,
        "retainage_amount": 0, "disbursed_amount": 0,
        "review_status": "PENDING_REVIEW", "payment_status": "UNPAID",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["project_expenditures"][e["id"]] = e
    recompute_project(p)
    recompute_proposal(bp)
    return success_obj(pe_view(e), 201)


@app.route("/district/bond-projects/<pid>/expenditures", methods=["GET"])
def list_expenditures(pid):
    require_auth(ROLES)
    get_or_404("bond_projects", pid, "ERR_BOND_PROJECT_NOT_FOUND",
               "No bond project with the given id")
    items = sorted([e for e in db["project_expenditures"].values()
                    if e["bond_project_id"] == pid], key=lambda e: e["created_at"])
    total = len(items)
    return success_list([pe_view(e) for e in items], total)


@app.route("/district/project-expenditures/<peId>/review", methods=["POST"])
def review_expenditure(peId):
    require_auth(["BusinessManager"])
    e = get_or_404("project_expenditures", peId,
                   "ERR_PROJECT_EXPENDITURE_NOT_FOUND",
                   "No project expenditure with the given id")
    data = body()
    approved = data.get("approved")
    if not isinstance(approved, bool):
        err("ERR_INVALID_REQUEST", "approved must be a boolean", 400)
    if e["payment_status"] != "UNPAID":
        err("ERR_INVALID_STATE",
            "Review of an expenditure whose payment_status is not UNPAID", 409)
    if approved:
        if e["review_status"] not in ("PENDING_REVIEW", "FLAGGED"):
            err("ERR_INVALID_STATE",
                "Expenditure is not PENDING_REVIEW or FLAGGED", 409)
        e["review_status"] = "REVIEWED"
    else:
        if e["review_status"] != "PENDING_REVIEW":
            err("ERR_INVALID_STATE", "Expenditure is not PENDING_REVIEW", 409)
        e["review_status"] = "FLAGGED"
    bump(e)
    return success_obj(pe_view(e))


@app.route("/district/project-expenditures/<peId>/disburse", methods=["POST"])
def disburse_expenditure(peId):
    require_auth(["DistrictTreasurer"])
    e = get_or_404("project_expenditures", peId,
                   "ERR_PROJECT_EXPENDITURE_NOT_FOUND",
                   "No project expenditure with the given id")
    if e["payment_status"] != "UNPAID":
        err("ERR_INVALID_STATE", "Expenditure is not UNPAID", 409)
    if e["review_status"] != "REVIEWED":
        err("ERR_EXPENDITURE_NOT_REVIEWED",
            "Disburse attempted on an expenditure whose review_status is not REVIEWED",
            409)
    retainage = round_half_up_2(e["amount"] * RETAINAGE_PCT)
    e["retainage_amount"] = retainage
    e["disbursed_amount"] = round_half_up_2(e["amount"] - retainage)
    e["payment_status"] = "DISBURSED"
    bump(e)
    return success_obj(pe_view(e))


@app.route("/district/project-expenditures/<peId>/void", methods=["POST"])
def void_expenditure(peId):
    require_auth(["DistrictTreasurer"])
    e = get_or_404("project_expenditures", peId,
                   "ERR_PROJECT_EXPENDITURE_NOT_FOUND",
                   "No project expenditure with the given id")
    if e["payment_status"] not in ("UNPAID", "DISBURSED"):
        err("ERR_INVALID_STATE",
            "Expenditure is not UNPAID or DISBURSED", 409)
    was_disbursed = e["payment_status"] == "DISBURSED"
    e["payment_status"] = "VOIDED"
    if was_disbursed:
        e["retainage_amount"] = 0
        e["disbursed_amount"] = 0
    bump(e)
    p = db["bond_projects"][e["bond_project_id"]]
    recompute_project(p)
    bp = db["bond_proposals"][p["bond_proposal_id"]]
    recompute_proposal(bp)
    return success_obj(pe_view(e))


# =========================================================================
# CapitalPlanAmendment
# =========================================================================

@app.route("/district/bond-proposals/<bid>/amendments", methods=["POST"])
def create_amendment(bid):
    require_auth(["BudgetAnalyst"])
    bp = get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
                    "No bond proposal with the given id")
    data = body()
    reason = as_str(data, "reason")
    adjustments = data.get("adjustments")
    if adjustments is None or not isinstance(adjustments, list):
        err("ERR_INVALID_REQUEST", "adjustments must be an array", 400)
    for adj in adjustments:
        if not isinstance(adj, dict):
            err("ERR_INVALID_REQUEST", "Each adjustment must be an object", 400)
        if "bond_project_id" not in adj or adj["bond_project_id"] is None:
            err("ERR_INVALID_REQUEST",
                "Each adjustment requires bond_project_id", 400)
        if "delta_authorized" not in adj or adj["delta_authorized"] is None:
            err("ERR_INVALID_REQUEST",
                "Each adjustment requires delta_authorized", 400)
        dv = adj["delta_authorized"]
        if isinstance(dv, bool) or not isinstance(dv, (int, float)):
            err("ERR_INVALID_REQUEST", "delta_authorized must be a number", 400)
    # body-referenced project existence
    for adj in adjustments:
        proj = db["bond_projects"].get(adj["bond_project_id"])
        if proj is None:
            err("ERR_BOND_PROJECT_NOT_FOUND",
                "No bond project with the given id", 404)
    if bp["status"] != "PASSED":
        err("ERR_INVALID_STATE",
            "Amendments may only be drafted against a PASSED proposal", 409)
    ts = ts_now()
    c = {
        "id": new_id(), "bond_proposal_id": bid, "reason": reason,
        "adjustments": [
            {"bond_project_id": a["bond_project_id"],
             "delta_authorized": a["delta_authorized"]} for a in adjustments
        ],
        "submitted_by_user_id": None, "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db["capital_plan_amendments"][c["id"]] = c
    return success_obj(ca_view(c), 201)


@app.route("/district/bond-proposals/<bid>/amendments", methods=["GET"])
def list_amendments(bid):
    require_auth(ROLES)
    get_or_404("bond_proposals", bid, "ERR_BOND_PROPOSAL_NOT_FOUND",
               "No bond proposal with the given id")
    items = sorted([c for c in db["capital_plan_amendments"].values()
                    if c["bond_proposal_id"] == bid], key=lambda c: c["created_at"])
    total = len(items)
    return success_list([ca_view(c) for c in items], total)


@app.route("/district/capital-plan-amendments/<caId>/submit", methods=["POST"])
def submit_amendment(caId):
    uid, _ = require_auth(["BudgetAnalyst"])
    c = get_or_404("capital_plan_amendments", caId,
                   "ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND",
                   "No capital-plan amendment with the given id")
    if c["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Amendment is not DRAFT", 409)
    c["status"] = "SUBMITTED"
    c["submitted_by_user_id"] = uid
    bump(c)
    return success_obj(ca_view(c))


@app.route("/district/capital-plan-amendments/<caId>/approve", methods=["POST"])
def approve_amendment(caId):
    uid, _ = require_auth(["Superintendent"])
    c = get_or_404("capital_plan_amendments", caId,
                   "ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND",
                   "No capital-plan amendment with the given id")
    if c["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Amendment is not SUBMITTED", 409)
    if uid == c["submitted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "The approving operator must differ from the submitting operator", 403)
    bp = db["bond_proposals"][c["bond_proposal_id"]]
    # ownership
    for adj in c["adjustments"]:
        proj = db["bond_projects"].get(adj["bond_project_id"])
        if proj is None or proj["bond_proposal_id"] != c["bond_proposal_id"]:
            err("ERR_AMENDMENT_PROJECT_MISMATCH",
                "An adjustment references a project that does not belong to the amendment's proposal",
                422)
    # floors
    for adj in c["adjustments"]:
        proj = db["bond_projects"][adj["bond_project_id"]]
        recompute_project(proj)
        if proj["authorized_amount"] + adj["delta_authorized"] < proj["spent_amount"]:
            err("ERR_AMENDMENT_BELOW_SPENT",
                "Amendment would reduce a project's authorized_amount below its spent_amount",
                422)
    # ceiling
    deltas = {adj["bond_project_id"]: adj["delta_authorized"] for adj in c["adjustments"]}
    total_after = 0.0
    for proj in db["bond_projects"].values():
        if proj["bond_proposal_id"] == c["bond_proposal_id"] and proj["status"] != "CANCELLED":
            total_after += proj["authorized_amount"] + deltas.get(proj["id"], 0)
    if round_half_up_2(total_after) > bp["total_amount"]:
        err("ERR_AMENDMENT_EXCEEDS_AUTHORIZATION",
            "Amendment would push the sum of authorized amounts over the proposal's total_amount",
            422)
    for adj in c["adjustments"]:
        proj = db["bond_projects"][adj["bond_project_id"]]
        proj["authorized_amount"] = round_half_up_2(
            proj["authorized_amount"] + adj["delta_authorized"])
        touch(proj)
    c["status"] = "APPROVED"
    bump(c)
    return success_obj(ca_view(c))


@app.route("/district/capital-plan-amendments/<caId>/reject", methods=["POST"])
def reject_amendment(caId):
    require_auth(["Superintendent"])
    c = get_or_404("capital_plan_amendments", caId,
                   "ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND",
                   "No capital-plan amendment with the given id")
    if c["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Amendment is not SUBMITTED", 409)
    c["status"] = "REJECTED"
    bump(c)
    return success_obj(ca_view(c))


@app.route("/district/capital-plan-amendments/<caId>/revise", methods=["POST"])
def revise_amendment(caId):
    require_auth(["BudgetAnalyst"])
    c = get_or_404("capital_plan_amendments", caId,
                   "ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND",
                   "No capital-plan amendment with the given id")
    if c["status"] != "REJECTED":
        err("ERR_INVALID_STATE", "Amendment is not REJECTED", 409)
    c["status"] = "DRAFT"
    c["submitted_by_user_id"] = None
    bump(c)
    return success_obj(ca_view(c))


# =========================================================================
# Entry point
# =========================================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
