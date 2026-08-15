"""Routes: capital projects, funding draws, lease strategies."""
from flask import Blueprint

from core import (
    store, ALL_ROLES, SPACE_TYPES, ApiError,
    auth_user, require_role, body, req_str, req_int, req_pos_int, req_enum, opt_bool,
    get_or_404, new_record, touch,
    success_object, list_response,
    bad_request, forbidden, conflict, unprocessable, stale,
    projects_of_plan, draws_of_project, strategies_of_asset,
    plan_capital_buckets, project_drawn, portfolio_posture, spend_vector,
    cancel_project, rhu_div,
    ser_project, ser_draw, ser_strategy,
)

bp = Blueprint("routes_c", __name__)


# ---------------------------------------------------------------------------
# Capital projects
# ---------------------------------------------------------------------------

@bp.route("/api/capital-projects", methods=["POST"])
def c_create_project():
    uid, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    aid = req_str(b, "asset_id")
    get_or_404(store.assets, aid, "asset")
    pid = req_str(b, "plan_id")
    plan = get_or_404(store.plans, pid, "business plan")
    if plan["asset_id"] != aid:
        raise unprocessable("ERR_REFERENTIAL_INTEGRITY",
                            "plan_id does not belong to the given asset_id")
    name = req_str(b, "name")
    amount = req_pos_int(b, "requested_amount_cents")
    s = req_int(b, "sched_start_month")
    e = req_int(b, "sched_end_month")
    if not (1 <= s <= 12) or not (1 <= e <= 12):
        raise bad_request("sched_start_month and sched_end_month must be in 1..12")
    if s > e:
        raise bad_request("sched_start_month must not be after sched_end_month")
    emerg = opt_bool(b, "is_emergency", False)
    rec = new_record()
    rec.update({"asset_id": aid, "plan_id": pid, "name": name, "is_emergency": emerg,
                "requested_amount_cents": amount, "sched_start_month": s,
                "sched_end_month": e, "approved_amount_cents": None,
                "proposed_by_user_id": uid, "status": "PROPOSED"})
    store.projects[rec["id"]] = rec
    return success_object(ser_project(rec), 201)


@bp.route("/api/capital-projects/<string:rid>", methods=["GET"])
def c_get_project(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_project(get_or_404(store.projects, rid, "capital project")))


@bp.route("/api/capital-projects/<string:rid>/approve", methods=["POST"])
def c_approve_project(rid):
    uid, role = auth_user()
    if role not in ("InvestmentCommittee", "PortfolioDirector"):
        raise forbidden()
    pr = get_or_404(store.projects, rid, "capital project")
    if pr["is_emergency"] and role != "PortfolioDirector":
        raise forbidden("Emergency capital projects may only be approved by a PortfolioDirector")
    b = body()
    expected = req_int(b, "expected_plan_version")
    plan = store.plans.get(pr["plan_id"])
    if plan is None:
        raise unprocessable("ERR_REFERENTIAL_INTEGRITY", "project plan does not exist")
    if expected != plan["version"]:
        raise stale("ERR_STALE_PLAN_VERSION",
                    "expected_plan_version does not match the plan's current version")
    if pr["status"] != "PROPOSED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED project may be approved")
    if plan["status"] != "APPROVED":
        raise conflict("ERR_PLAN_NOT_APPROVED", "The project's plan must be APPROVED")
    if uid == pr["proposed_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                       "The approver must differ from the project's proposer")
    if not pr["is_emergency"]:
        asset = store.assets.get(pr["asset_id"])
        if portfolio_posture(asset["portfolio_id"]) == "RESTRICTED":
            raise conflict("ERR_PORTFOLIO_RESTRICTED",
                           "Portfolio risk posture is RESTRICTED")
        total_cap, _, _, available = plan_capital_buckets(plan)
        if pr["requested_amount_cents"] > available:
            raise conflict("ERR_CAPITAL_BUDGET_EXCEEDED",
                           "requested_amount_cents exceeds the plan's available capital")
        monthly_cap = total_cap // 12
        others = [p for p in projects_of_plan(plan["id"])
                  if p["id"] != pr["id"] and p["status"] in ("APPROVED", "IN_PROGRESS")]
        vecs = [spend_vector(p["approved_amount_cents"], p["sched_start_month"],
                             p["sched_end_month"]) for p in others]
        cand = spend_vector(pr["requested_amount_cents"], pr["sched_start_month"],
                            pr["sched_end_month"])
        for m in range(pr["sched_start_month"], pr["sched_end_month"] + 1):
            committed = sum(v.get(m, 0) for v in vecs)
            if committed + cand[m] > monthly_cap:
                raise conflict("ERR_CAPITAL_SCHEDULE_OVER_COMMITTED",
                               "Monthly committed capital would exceed "
                               "floor(total_capital_budget_cents / 12)")
    pr["approved_amount_cents"] = pr["requested_amount_cents"]
    pr["status"] = "APPROVED"
    touch(pr)
    touch(plan)
    return success_object(ser_project(pr))


@bp.route("/api/capital-projects/<string:rid>/reject", methods=["POST"])
def c_reject_project(rid):
    _, role = auth_user()
    if role not in ("InvestmentCommittee", "PortfolioDirector"):
        raise forbidden()
    pr = get_or_404(store.projects, rid, "capital project")
    if pr["status"] != "PROPOSED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED project may be rejected")
    pr["status"] = "REJECTED"
    touch(pr)
    return success_object(ser_project(pr))


@bp.route("/api/capital-projects/<string:rid>/start", methods=["POST"])
def c_start_project(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    pr = get_or_404(store.projects, rid, "capital project")
    if pr["status"] != "APPROVED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED project may be started")
    pr["status"] = "IN_PROGRESS"
    touch(pr)
    return success_object(ser_project(pr))


@bp.route("/api/capital-projects/<string:rid>/complete", methods=["POST"])
def c_complete_project(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    pr = get_or_404(store.projects, rid, "capital project")
    if pr["status"] != "IN_PROGRESS":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only an IN_PROGRESS project may be completed")
    if project_drawn(pr) <= 0:
        raise conflict("ERR_PROJECT_NEVER_FUNDED", "Completion requires drawn_cents > 0")
    pr["status"] = "COMPLETED"
    touch(pr)
    plan = store.plans.get(pr["plan_id"])
    if plan is not None:
        touch(plan)
    return success_object(ser_project(pr))


@bp.route("/api/capital-projects/<string:rid>/cancel", methods=["POST"])
def c_cancel_project(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    pr = get_or_404(store.projects, rid, "capital project")
    if pr["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED or IN_PROGRESS project may be cancelled")
    cancel_project(pr)
    plan = store.plans.get(pr["plan_id"])
    if plan is not None:
        touch(plan)
    return success_object(ser_project(pr))


@bp.route("/api/capital-projects/<string:rid>/funding-draws", methods=["GET"])
def c_project_draws(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    pr = get_or_404(store.projects, rid, "capital project")
    return list_response(draws_of_project(pr["id"]), ser_draw)


# ---------------------------------------------------------------------------
# Funding draws
# ---------------------------------------------------------------------------

@bp.route("/api/funding-draws", methods=["POST"])
def c_create_draw():
    uid, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    pid = req_str(b, "project_id")
    pr = get_or_404(store.projects, pid, "capital project")
    if pr["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise conflict("ERR_PROJECT_NOT_FUNDABLE",
                       "Draws require the project to be APPROVED or IN_PROGRESS")
    amount = req_pos_int(b, "amount_cents")
    rec = new_record()
    rec.update({"project_id": pid, "amount_cents": amount, "status": "REQUESTED",
                "requested_by_user_id": uid})
    store.draws[rec["id"]] = rec
    return success_object(ser_draw(rec), 201)


@bp.route("/api/funding-draws/<string:rid>/approve", methods=["POST"])
def c_approve_draw(rid):
    _, role = auth_user()
    require_role(role, ["InvestmentCommittee"])
    d = get_or_404(store.draws, rid, "funding draw")
    if d["status"] != "REQUESTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED draw may be approved")
    pr = store.projects.get(d["project_id"])
    if pr is None or pr["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise conflict("ERR_PROJECT_NOT_FUNDABLE",
                       "The project must be APPROVED or IN_PROGRESS")
    if project_drawn(pr) + d["amount_cents"] > pr["approved_amount_cents"]:
        raise conflict("ERR_DRAW_EXCEEDS_AUTHORIZATION",
                       "drawn_cents + amount_cents would exceed approved_amount_cents")
    d["status"] = "APPROVED"
    touch(d)
    return success_object(ser_draw(d))


@bp.route("/api/funding-draws/<string:rid>/reject", methods=["POST"])
def c_reject_draw(rid):
    _, role = auth_user()
    require_role(role, ["InvestmentCommittee"])
    d = get_or_404(store.draws, rid, "funding draw")
    if d["status"] != "REQUESTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED draw may be rejected")
    d["status"] = "REJECTED"
    touch(d)
    return success_object(ser_draw(d))


@bp.route("/api/funding-draws/<string:rid>/release", methods=["POST"])
def c_release_draw(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    d = get_or_404(store.draws, rid, "funding draw")
    if d["status"] != "APPROVED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED draw may be released")
    d["status"] = "RELEASED"
    touch(d)
    pr = store.projects.get(d["project_id"])
    if pr is not None:
        touch(pr)
        plan = store.plans.get(pr["plan_id"])
        if plan is not None:
            touch(plan)
    return success_object(ser_draw(d))


# ---------------------------------------------------------------------------
# Lease strategies
# ---------------------------------------------------------------------------

@bp.route("/api/lease-strategies", methods=["POST"])
def c_create_strategy():
    uid, role = auth_user()
    if role not in ("AssetManager", "PropertyManager"):
        raise forbidden()
    b = body()
    aid = req_str(b, "asset_id")
    asset = get_or_404(store.assets, aid, "asset")
    if role == "PropertyManager" and asset["property_manager_id"] != uid:
        raise forbidden("A property manager may only draft strategies for assets it manages")
    space = req_enum(b, "space_type", SPACE_TYPES)
    occ = req_int(b, "current_occupancy_pct")
    if occ < 0 or occ > 100:
        raise bad_request("current_occupancy_pct must be in 0..100")
    proposed = req_pos_int(b, "proposed_asking_rate_psf_cents")
    market = req_pos_int(b, "market_comp_rate_psf_cents")
    rec = new_record()
    rec.update({"asset_id": aid, "space_type": space, "current_occupancy_pct": occ,
                "proposed_asking_rate_psf_cents": proposed,
                "market_comp_rate_psf_cents": market,
                "recommended_rate_psf_cents": None, "status": "DRAFT"})
    store.strategies[rec["id"]] = rec
    return success_object(ser_strategy(rec), 201)


@bp.route("/api/lease-strategies/<string:rid>/recommend", methods=["POST"])
def c_recommend_strategy(rid):
    _, role = auth_user()
    require_role(role, ["Analyst"])
    s = get_or_404(store.strategies, rid, "lease strategy")
    if s["status"] != "DRAFT":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT strategy may be recommended")
    occ = s["current_occupancy_pct"]
    if occ < 70:
        adj = -1000
    elif occ < 85:
        adj = -500
    elif occ < 95:
        adj = 0
    else:
        adj = 500
    market = s["market_comp_rate_psf_cents"]
    adjusted = rhu_div(market * (10000 + adj), 10000)
    floor_rate = rhu_div(s["proposed_asking_rate_psf_cents"] * 9500, 10000)
    ceiling = rhu_div(market * 11000, 10000)
    s["recommended_rate_psf_cents"] = min(max(adjusted, floor_rate), ceiling)
    s["status"] = "RECOMMENDED"
    touch(s)
    return success_object(ser_strategy(s))


@bp.route("/api/lease-strategies/<string:rid>/ratify", methods=["POST"])
def c_ratify_strategy(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    s = get_or_404(store.strategies, rid, "lease strategy")
    if s["status"] != "RECOMMENDED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a RECOMMENDED strategy may be ratified")
    asset = store.assets.get(s["asset_id"])
    if asset is None or asset["status"] not in ("OWNED", "LISTED_FOR_SALE"):
        raise conflict("ERR_ASSET_NOT_OPERATING",
                       "Ratification requires the asset to be OWNED or LISTED_FOR_SALE")
    for other in strategies_of_asset(s["asset_id"]):
        if other["id"] != s["id"] and other["space_type"] == s["space_type"] \
                and other["status"] == "RATIFIED":
            other["status"] = "SUPERSEDED"
            touch(other)
    s["status"] = "RATIFIED"
    touch(s)
    return success_object(ser_strategy(s))


@bp.route("/api/lease-strategies/<string:rid>/reject", methods=["POST"])
def c_reject_strategy(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    s = get_or_404(store.strategies, rid, "lease strategy")
    if s["status"] != "RECOMMENDED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a RECOMMENDED strategy may be rejected")
    s["status"] = "REJECTED"
    touch(s)
    return success_object(ser_strategy(s))
