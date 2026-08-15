"""Routes: business plans, budget lines, actuals reports."""
from flask import Blueprint

from core import (
    store, ALL_ROLES, ALL_CATS, REVENUE_CATS, NON_CAPITAL_CATS,
    auth_user, require_role, body, req_str, req_int, req_nonneg_int, req_enum,
    get_or_404, new_record, touch,
    success_object, success_array, list_response,
    bad_request, forbidden, conflict, unprocessable, stale,
    plans_of_asset, lines_of_plan, reports_of_plan, projects_of_plan,
    reforecasts_of_plan, fiscal_month, annualized_noi_for_plan,
    ser_plan, ser_line, ser_report, ser_project, ser_reforecast,
)

bp = Blueprint("routes_b", __name__)


# ---------------------------------------------------------------------------
# Business plans
# ---------------------------------------------------------------------------

@bp.route("/api/business-plans", methods=["POST"])
def b_create_plan():
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    aid = req_str(b, "asset_id")
    asset = get_or_404(store.assets, aid, "asset")
    fy = req_int(b, "fiscal_year")
    expected = req_int(b, "expected_asset_version")
    if expected != asset["version"]:
        raise stale("ERR_STALE_ASSET_VERSION",
                    "expected_asset_version does not match the asset's current version")
    siblings = [p for p in plans_of_asset(aid) if p["fiscal_year"] == fy]
    if any(p["status"] in ("DRAFT", "SUBMITTED") for p in siblings):
        raise conflict("ERR_DUPLICATE_PLAN",
                       "A DRAFT or SUBMITTED plan already exists for (asset_id, fiscal_year)")
    approved = [p for p in siblings if p["status"] == "APPROVED"]
    if approved:
        ap = approved[0]
        if any(pr["status"] in ("APPROVED", "IN_PROGRESS")
               for pr in projects_of_plan(ap["id"])):
            raise conflict("ERR_PLAN_HAS_ACTIVE_PROJECTS",
                           "The APPROVED plan has capital projects in APPROVED or IN_PROGRESS")
        ap["status"] = "SUPERSEDED"
        touch(ap)
        for rf in reforecasts_of_plan(ap["id"]):
            if rf["status"] in ("DRAFT", "SUBMITTED"):
                rf["status"] = "REJECTED"
                touch(rf)
        asset["current_plan_id"] = None
        touch(asset)
    rec = new_record()
    rec.update({"asset_id": aid, "fiscal_year": fy, "status": "DRAFT", "reforecast_count": 0})
    store.plans[rec["id"]] = rec
    return success_object(ser_plan(rec), 201)


@bp.route("/api/business-plans/<string:rid>", methods=["GET"])
def b_get_plan(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_plan(get_or_404(store.plans, rid, "business plan")))


@bp.route("/api/business-plans/<string:rid>/submit", methods=["POST"])
def b_submit_plan(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    plan = get_or_404(store.plans, rid, "business plan")
    if plan["status"] == "DRAFT":
        asset = store.assets.get(plan["asset_id"])
        if asset is None or asset["status"] != "OWNED":
            raise conflict("ERR_ASSET_NOT_OPERATING",
                           "Plan submission requires the asset to be OWNED")
    elif plan["status"] != "REJECTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT or REJECTED plan may be submitted")
    present = {l["category"] for l in lines_of_plan(plan["id"])}
    if any(c not in present for c in ALL_CATS):
        raise unprocessable("ERR_PLAN_LINES_INCOMPLETE",
                            "Every one of the 10 budget categories must have at least one line")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(ser_plan(plan))


@bp.route("/api/business-plans/<string:rid>/approve", methods=["POST"])
def b_approve_plan(rid):
    from core import close_plan, portfolio_posture
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    plan = get_or_404(store.plans, rid, "business plan")
    if plan["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED plan may be approved")
    asset = store.assets.get(plan["asset_id"])
    manager = store.managers.get(asset["property_manager_id"]) if asset else None
    if manager is None or manager["status"] != "ACTIVE":
        raise conflict("ERR_MANAGER_SUSPENDED",
                       "The asset's property manager is not ACTIVE")
    if portfolio_posture(asset["portfolio_id"]) == "RESTRICTED":
        raise conflict("ERR_PORTFOLIO_RESTRICTED",
                       "Portfolio risk posture is RESTRICTED")
    # Year-rollover handoff: other-fiscal-year APPROVED plans of this asset close.
    for other in plans_of_asset(plan["asset_id"]):
        if other["id"] != plan["id"] and other["status"] == "APPROVED" \
                and other["fiscal_year"] != plan["fiscal_year"]:
            close_plan(other)
    plan["status"] = "APPROVED"
    touch(plan)
    asset["current_plan_id"] = plan["id"]
    touch(asset)
    return success_object(ser_plan(plan))


@bp.route("/api/business-plans/<string:rid>/reject", methods=["POST"])
def b_reject_plan(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    plan = get_or_404(store.plans, rid, "business plan")
    if plan["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED plan may be rejected")
    plan["status"] = "REJECTED"
    touch(plan)
    return success_object(ser_plan(plan))


@bp.route("/api/business-plans/<string:rid>/variance-summary", methods=["GET"])
def b_variance_summary(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, "business plan")
    lines = lines_of_plan(plan["id"])
    cats = []
    for cat in ALL_CATS:
        cl = [l for l in lines if l["category"] == cat]
        budget = sum(l["budget_amount_cents"] for l in cl)
        posted = [l for l in cl if l["has_actual"]]
        actual = sum(l["actual_amount_cents"] for l in posted)
        if posted:
            var = sum(l["actual_amount_cents"] - l["budget_amount_cents"] for l in posted)
            fav = (var >= 0) if cat in REVENUE_CATS else (var <= 0)
        else:
            var = None
            fav = None
        line_out = []
        for l in cl:
            lo = ser_line(l)
            if l["has_actual"]:
                d = l["actual_amount_cents"] - l["budget_amount_cents"]
                lo["favorable"] = (d >= 0) if cat in REVENUE_CATS else (d <= 0)
            else:
                lo["favorable"] = None
            line_out.append(lo)
        cats.append({"category": cat, "budget_amount_cents": budget,
                     "actual_amount_cents": actual, "variance_cents": var,
                     "favorable": fav, "lines": line_out})
    ser = ser_plan(plan)
    return success_object({
        "plan_id": plan["id"],
        "categories": cats,
        "total_budget_noi_cents": ser["budgeted_noi_cents"],
        "ytd_actual_noi_cents": ser["ytd_actual_noi_cents"],
        "annualized_actual_noi_cents": annualized_noi_for_plan(plan),
    })


# --- Plan sub-resource lists ---------------------------------------------------

@bp.route("/api/business-plans/<string:rid>/budget-lines", methods=["GET"])
def b_plan_lines(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, "business plan")
    return list_response(lines_of_plan(plan["id"]), ser_line)


@bp.route("/api/business-plans/<string:rid>/actuals-reports", methods=["GET"])
def b_plan_reports(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, "business plan")
    return list_response(reports_of_plan(plan["id"]), ser_report)


@bp.route("/api/business-plans/<string:rid>/capital-projects", methods=["GET"])
def b_plan_projects(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, "business plan")
    return list_response(projects_of_plan(plan["id"]), ser_project)


@bp.route("/api/business-plans/<string:rid>/reforecasts", methods=["GET"])
def b_plan_reforecasts(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, "business plan")
    return list_response(reforecasts_of_plan(plan["id"]), ser_reforecast)


# ---------------------------------------------------------------------------
# Budget lines (bulk-atomic creation)
# ---------------------------------------------------------------------------

@bp.route("/api/budget-lines", methods=["POST"])
def b_create_budget_lines():
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    pid = req_str(b, "plan_id")
    plan = get_or_404(store.plans, pid, "business plan")
    if plan["status"] not in ("DRAFT", "REJECTED"):
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Budget lines may only be created while the plan is DRAFT or REJECTED")
    raw = b.get("lines")
    if not isinstance(raw, list) or len(raw) == 0:
        raise bad_request("lines must be a non-empty array")
    parsed = []
    seen = set()
    for e in raw:
        if not isinstance(e, dict):
            raise bad_request("each entry of lines must be an object")
        cat = req_enum(e, "category", ALL_CATS)
        month = req_int(e, "month_index")
        if month < 1 or month > 12:
            raise bad_request("month_index must be in 1..12")
        amount = req_nonneg_int(e, "budget_amount_cents")
        if (cat, month) in seen:
            raise conflict("ERR_DUPLICATE_BUDGET_LINE",
                           "Duplicate (category, month_index) within the batch")
        seen.add((cat, month))
        parsed.append((cat, month, amount))
    existing = {(l["category"], l["month_index"]) for l in lines_of_plan(pid)}
    for key in seen:
        if key in existing:
            raise conflict("ERR_DUPLICATE_BUDGET_LINE",
                           "A line already exists for (plan_id, category, month_index)")
    created = []
    for cat, month, amount in parsed:
        rec = new_record()
        rec.update({"plan_id": pid, "category": cat, "month_index": month,
                    "budget_amount_cents": amount, "actual_amount_cents": 0,
                    "has_actual": False})
        store.budget_lines[rec["id"]] = rec
        created.append(rec)
    touch(plan)
    return success_array([ser_line(l) for l in created], 201)


# ---------------------------------------------------------------------------
# Actuals reports
# ---------------------------------------------------------------------------

@bp.route("/api/actuals-reports", methods=["POST"])
def b_create_actuals():
    uid, role = auth_user()
    require_role(role, ["PropertyManager"])
    b = body()
    pid = req_str(b, "plan_id")
    plan = get_or_404(store.plans, pid, "business plan")
    asset = store.assets.get(plan["asset_id"])
    if asset is None or asset["property_manager_id"] != uid:
        raise forbidden("A property manager may only post actuals for assets it manages")
    # Existence of body-referenced budget lines precedes state checks (tier 3).
    raw = b.get("lines")
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and isinstance(e.get("budget_line_id"), str):
                get_or_404(store.budget_lines, e["budget_line_id"], "budget line")
    if plan["status"] != "APPROVED":
        raise conflict("ERR_PLAN_NOT_APPROVED", "Actuals require the plan to be APPROVED")
    month = req_int(b, "month_index")
    if month < 1 or month > 12:
        raise bad_request("month_index must be in 1..12")
    if not isinstance(raw, list) or len(raw) == 0:
        raise bad_request("lines must be a non-empty array")
    seen_ids = set()
    entries = []
    for e in raw:
        if not isinstance(e, dict):
            raise bad_request("each entry of lines must be an object")
        lid = req_str(e, "budget_line_id")
        amt = req_nonneg_int(e, "actual_amount_cents")
        if lid in seen_ids:
            raise bad_request("duplicate budget_line_id within lines")
        seen_ids.add(lid)
        line = store.budget_lines[lid]
        if line["plan_id"] != pid or line["month_index"] != month:
            raise unprocessable("ERR_REFERENTIAL_INTEGRITY",
                                "Every line must belong to plan_id and match the report month_index")
        entries.append((line, amt))
    if any(r["month_index"] == month and r["status"] == "ACCEPTED"
           for r in reports_of_plan(pid)):
        raise conflict("ERR_DUPLICATE_ACTUALS",
                       "An ACCEPTED actuals report already exists for (plan_id, month_index)")
    if any(line["has_actual"] for line, _ in entries):
        raise conflict("ERR_DUPLICATE_ACTUALS",
                       "A referenced line already has an accepted actual")
    if month > fiscal_month(plan):
        raise unprocessable("ERR_FUTURE_PERIOD",
                            "month_index exceeds the plan's current fiscal month")
    rec = new_record()
    rec.update({"plan_id": pid, "month_index": month,
                "lines": [{"budget_line_id": line["id"], "actual_amount_cents": amt}
                          for line, amt in entries],
                "status": "SUBMITTED", "submitted_by_user_id": uid})
    store.actuals[rec["id"]] = rec
    return success_object(ser_report(rec), 201)


@bp.route("/api/actuals-reports/<string:rid>/accept", methods=["POST"])
def b_accept_actuals(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    rep = get_or_404(store.actuals, rid, "actuals report")
    if rep["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED report may be accepted")
    plan = store.plans.get(rep["plan_id"])
    for e in rep["lines"]:
        line = store.budget_lines[e["budget_line_id"]]
        line["actual_amount_cents"] = e["actual_amount_cents"]
        line["has_actual"] = True
        touch(line)
    rep["status"] = "ACCEPTED"
    touch(rep)
    if plan is not None:
        touch(plan)
    return success_object(ser_report(rep))


@bp.route("/api/actuals-reports/<string:rid>/reject", methods=["POST"])
def b_reject_actuals(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    rep = get_or_404(store.actuals, rid, "actuals report")
    if rep["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED report may be rejected")
    rep["status"] = "REJECTED"
    touch(rep)
    return success_object(ser_report(rep))
