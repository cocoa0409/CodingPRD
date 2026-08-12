"""Routes: association budgets, line items, assessment rates."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    opt_int, opt_bool, validation, err, invalid_state, new_entity, touch,
    get_or_404, check_body_fk, ok_object, filter_args, round_half_up,
    round_half_up_int, dec_num, BUDGET_NOTICE_LEAD_DAYS,
    ASSESSMENT_NOTICE_LEAD_DAYS, STATUTORY_CAP_PCT,
)
from serializers import budget_out, line_item_out, rate_out, budget_total_expense
from routes_core import paginate_pairs

bp = Blueprint("finance", __name__)

CTRL = ["DeclarantController"]

LINE_CATEGORIES = {
    "LANDSCAPE_MAINTENANCE", "AMENITY_OPERATIONS", "UTILITIES", "MANAGEMENT",
    "INSURANCE", "RESERVE_CONTRIBUTION", "EVENTS_PROGRAMMING", "CONTINGENCY",
}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@bp.route("/mpc/budgets", methods=["POST"])
def create_budget():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "fiscal_year",
                               "non_assessment_income_cents"})
    req_string(data, "community_id")
    fy = req_int(data, "fiscal_year", minimum=2020)
    income = opt_int(data, "non_assessment_income_cents", 0, minimum=0)
    for b in DB.budgets.values():
        if (b["community_id"] == community["id"] and b["fiscal_year"] == fy
                and b["status"] != "SUPERSEDED"):
            err("ERR_DUPLICATE_FISCAL_YEAR", 409,
                "A non-SUPERSEDED budget already exists for this fiscal year")
    b = new_entity()
    b.update({
        "community_id": community["id"],
        "fiscal_year": fy,
        "amendment_of_id": None,
        "non_assessment_income_cents": income,
        "adopted_by_user_id": None,
        "status": "DRAFT",
    })
    DB.budgets[b["id"]] = b
    return ok_object(budget_out(b), 201)


@bp.route("/mpc/budgets", methods=["GET"])
def list_budgets():
    actor()
    f = filter_args(["community_id", "amendment_of_id"])
    raw = [b for b in DB.budgets.values()
           if f.get("community_id") in (None, b["community_id"])
           and f.get("amendment_of_id") in (None, b["amendment_of_id"])]
    return paginate_pairs(raw, budget_out)


@bp.route("/mpc/budgets/<bid>", methods=["GET"])
def get_budget(bid):
    actor()
    b = get_or_404("budget", DB.budgets, bid)
    return ok_object(budget_out(b))


@bp.route("/mpc/line-items", methods=["POST"])
def create_line_item():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    budget = check_body_fk("budget", DB.budgets, data.get("budget_id"))
    check_no_undeclared(data, {"budget_id", "category", "amount_cents",
                               "is_reserve"})
    req_string(data, "budget_id")
    cat = data.get("category")
    if cat not in LINE_CATEGORIES:
        validation("category is not a valid budget line category")
    amount = req_int(data, "amount_cents", gt=0)
    is_reserve = opt_bool(data, "is_reserve", False)
    if budget["status"] != "DRAFT":
        invalid_state("Line items may be added only to a DRAFT budget")
    li = new_entity()
    li.update({
        "budget_id": budget["id"],
        "category": cat,
        "amount_cents": amount,
        "is_reserve": is_reserve,
    })
    DB.line_items[li["id"]] = li
    return ok_object(line_item_out(li), 201)


@bp.route("/mpc/line-items", methods=["GET"])
def list_line_items():
    actor()
    f = filter_args(["budget_id"])
    raw = [li for li in DB.line_items.values()
           if f.get("budget_id") in (None, li["budget_id"])]
    return paginate_pairs(raw, line_item_out)


@bp.route("/mpc/line-items/<liid>", methods=["GET"])
def get_line_item(liid):
    actor()
    li = get_or_404("line_item", DB.line_items, liid)
    return ok_object(line_item_out(li))


@bp.route("/mpc/budgets/<bid>/propose", methods=["POST"])
def propose_budget(bid):
    _, role = actor()
    require_roles(role, CTRL)
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["status"] != "DRAFT":
        invalid_state("Budget is not DRAFT")
    if not any(li["budget_id"] == b["id"] for li in DB.line_items.values()):
        err("ERR_BUDGET_EMPTY", 409, "Budget has no line items")
    b["status"] = "PROPOSED"
    touch(b)
    return ok_object(budget_out(b))


def _sent_budget_notice(budget):
    """SENT (non-SUPERSEDED) BUDGET_ADOPTION notices referencing this budget."""
    return [n for n in DB.notices.values()
            if n["notice_type"] == "BUDGET_ADOPTION"
            and n["budget_id"] == budget["id"]
            and n["status"] == "SENT"]


@bp.route("/mpc/budgets/<bid>/adopt", methods=["POST"])
def adopt_budget(bid):
    user_id, role = actor()
    require_roles(role, ["AssociationDirector", "OwnerDirector"])
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["status"] != "PROPOSED":
        invalid_state("Budget is not PROPOSED")
    community = DB.communities.get(b["community_id"])
    stage = community["transition_stage"] if community else "DECLARANT_CONTROL"
    # Role/stage matrix.
    if role == "AssociationDirector" and stage == "TURNOVER_COMPLETE":
        err("ERR_DECLARANT_AUTHORITY_ENDED", 409,
            "Declarant-side adoption power has ended")
    if role == "OwnerDirector" and stage != "TURNOVER_COMPLETE":
        err("ERR_FORBIDDEN_ROLE", 403,
            "OwnerDirector adopts only after turnover")
    # Statutory notice gates.
    notices = _sent_budget_notice(b)
    if not notices:
        err("ERR_NOTICE_NOT_SENT", 409,
            "No SENT BUDGET_ADOPTION notice exists for this budget")
    now = DB.now()
    lead_ok = any(n["sent_at"] is not None
                  and n["sent_at"] <= now - timedelta(days=BUDGET_NOTICE_LEAD_DAYS)
                  for n in notices)
    if not lead_ok:
        err("ERR_NOTICE_LEAD_TIME", 422,
            "Notice was sent inside the statutory lead window")
    b["adopted_by_user_id"] = user_id
    if stage in ("PARITY", "OWNER_MAJORITY"):
        b["status"] = "PENDING_RATIFICATION"
    else:
        b["status"] = "ADOPTED"
    touch(b)
    return ok_object(budget_out(b))


@bp.route("/mpc/budgets/<bid>/ratify", methods=["POST"])
def ratify_budget(bid):
    user_id, role = actor()
    require_roles(role, ["OwnerDirector"])
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["status"] != "PENDING_RATIFICATION":
        invalid_state("Budget is not PENDING_RATIFICATION")
    if user_id == b["adopted_by_user_id"]:
        err("ERR_ADOPTER_CANNOT_RATIFY", 403,
            "The budget adopter may not also ratify")
    b["status"] = "ADOPTED"
    touch(b)
    return ok_object(budget_out(b))


@bp.route("/mpc/budgets/<bid>/reject", methods=["POST"])
def reject_budget(bid):
    _, role = actor()
    require_roles(role, ["AssociationDirector"])
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["status"] not in ("PROPOSED", "PENDING_RATIFICATION"):
        invalid_state("Budget is not PROPOSED or PENDING_RATIFICATION")
    b["status"] = "REJECTED"
    touch(b)
    return ok_object(budget_out(b))


@bp.route("/mpc/budgets/<bid>/revise", methods=["POST"])
def revise_budget(bid):
    _, role = actor()
    require_roles(role, CTRL)
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["status"] != "REJECTED":
        invalid_state("Budget is not REJECTED")
    b["status"] = "DRAFT"
    touch(b)
    return ok_object(budget_out(b))


@bp.route("/mpc/budgets/<bid>/amendments", methods=["POST"])
def amend_budget(bid):
    _, role = actor()
    require_roles(role, CTRL)
    b = get_or_404("budget", DB.budgets, bid)
    data = body()
    check_no_undeclared(data, {"expected_budget_version"})
    expected = req_int(data, "expected_budget_version")
    if b["status"] != "ADOPTED":
        invalid_state("Only an ADOPTED budget can be amended")
    if expected != b["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_budget_version does not match the current version")
    # Supersede this budget; create successor DRAFT with copied line items.
    b["status"] = "SUPERSEDED"
    touch(b)
    succ = new_entity()
    succ.update({
        "community_id": b["community_id"],
        "fiscal_year": b["fiscal_year"],
        "amendment_of_id": b["id"],
        "non_assessment_income_cents": b["non_assessment_income_cents"],
        "adopted_by_user_id": None,
        "status": "DRAFT",
    })
    DB.budgets[succ["id"]] = succ
    for li in list(DB.line_items.values()):
        if li["budget_id"] == b["id"]:
            new_li = new_entity()
            new_li.update({
                "budget_id": succ["id"],
                "category": li["category"],
                "amount_cents": li["amount_cents"],
                "is_reserve": li["is_reserve"],
            })
            DB.line_items[new_li["id"]] = new_li
    for r in list(DB.rates.values()):
        if r["budget_id"] == b["id"] and r["status"] in ("CALCULATED", "ARMED"):
            r["status"] = "SUPERSEDED"
            touch(r)
    return ok_object(budget_out(succ), 201)


# ---------------------------------------------------------------------------
# Assessment rates
# ---------------------------------------------------------------------------
@bp.route("/mpc/assessment-rates", methods=["POST"])
def create_rate():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    budget = check_body_fk("budget", DB.budgets, data.get("budget_id"))
    check_no_undeclared(data, {"community_id", "budget_id", "fiscal_year",
                               "subsidy_elected"})
    req_string(data, "community_id")
    req_string(data, "budget_id")
    fy = req_int(data, "fiscal_year")
    subsidy = opt_bool(data, "subsidy_elected", False)
    # State rung.
    if budget["status"] != "ADOPTED":
        err("ERR_BUDGET_NOT_ADOPTED", 409, "Budget must be ADOPTED")
    prior = None
    for r in DB.rates.values():
        if (r["community_id"] == community["id"]
                and r["fiscal_year"] == fy - 1
                and r["status"] == "EFFECTIVE"):
            prior = r
            break
    if subsidy:
        if community["transition_stage"] != "DECLARANT_CONTROL":
            err("ERR_SUBSIDY_NOT_AVAILABLE", 409,
                "Subsidy election requires DECLARANT_CONTROL")
        if prior is None:
            err("ERR_NO_PRIOR_RATE", 409,
                "Subsidy election requires an EFFECTIVE prior-year rate")
    # Uniqueness rung.
    for r in DB.rates.values():
        if (r["community_id"] == community["id"] and r["fiscal_year"] == fy
                and r["status"] != "SUPERSEDED"):
            err("ERR_DUPLICATE_ASSESSMENT_YEAR", 409,
                "A non-SUPERSEDED rate already exists for this fiscal year")
    # Referential rung.
    if fy != budget["fiscal_year"]:
        err("ERR_FISCAL_YEAR_MISMATCH", 422,
            "Rate fiscal_year must equal its budget's fiscal_year")
    # Computation.
    gap = budget_total_expense(budget) - budget["non_assessment_income_cents"]
    units = community["total_planned_units"]
    if subsidy:
        per_unit = prior["per_unit_annual_cents"]
        subsidy_cents = gap - per_unit * units
        increase = 0.0
    else:
        per_unit = round_half_up_int(Decimal(gap) / Decimal(units))
        subsidy_cents = 0
        if prior is not None and prior["per_unit_annual_cents"]:
            increase = dec_num(round_half_up(
                Decimal(per_unit - prior["per_unit_annual_cents"])
                / Decimal(prior["per_unit_annual_cents"]) * 100, 2))
        else:
            increase = None
    q = round_half_up_int(Decimal(per_unit) / Decimal(4))
    quarters = [q, q, q, per_unit - 3 * q]
    r = new_entity()
    r.update({
        "community_id": community["id"],
        "budget_id": budget["id"],
        "fiscal_year": fy,
        "subsidy_elected": subsidy,
        "per_unit_annual_cents": per_unit,
        "quarterly_installments_cents": quarters,
        "prior_rate_id": prior["id"] if prior else None,
        "prior_per_unit_cents": prior["per_unit_annual_cents"] if prior else None,
        "increase_pct": increase,
        "declarant_subsidy_cents": subsidy_cents,
        "cap_override_approved_by": None,
        "cap_override_ratified_by": None,
        "status": "CALCULATED",
    })
    DB.rates[r["id"]] = r
    return ok_object(rate_out(r), 201)


@bp.route("/mpc/assessment-rates", methods=["GET"])
def list_rates():
    actor()
    f = filter_args(["community_id", "budget_id", "prior_rate_id"])
    raw = [r for r in DB.rates.values()
           if f.get("community_id") in (None, r["community_id"])
           and f.get("budget_id") in (None, r["budget_id"])
           and f.get("prior_rate_id") in (None, r["prior_rate_id"])]
    return paginate_pairs(raw, rate_out)


@bp.route("/mpc/assessment-rates/<rid>", methods=["GET"])
def get_rate(rid):
    actor()
    r = get_or_404("rate", DB.rates, rid)
    return ok_object(rate_out(r))


@bp.route("/mpc/assessment-rates/<rid>/approve-cap-override", methods=["POST"])
def approve_cap_override(rid):
    user_id, role = actor()
    require_roles(role, ["AssociationDirector", "OwnerDirector"])
    r = get_or_404("rate", DB.rates, rid)
    data = body()
    check_no_undeclared(data, set())
    if r["status"] != "CALCULATED":
        invalid_state("Rate is not CALCULATED")
    community = DB.communities.get(r["community_id"])
    stage = community["transition_stage"] if community else "DECLARANT_CONTROL"
    if role == "AssociationDirector" and stage == "TURNOVER_COMPLETE":
        err("ERR_DECLARANT_AUTHORITY_ENDED", 409,
            "Declarant-side cap-override approval has ended")
    if role == "OwnerDirector" and stage != "TURNOVER_COMPLETE":
        err("ERR_FORBIDDEN_ROLE", 403,
            "OwnerDirector approves cap overrides only after turnover")
    r["cap_override_approved_by"] = user_id
    touch(r)
    return ok_object(rate_out(r))


@bp.route("/mpc/assessment-rates/<rid>/ratify-cap-override", methods=["POST"])
def ratify_cap_override(rid):
    user_id, role = actor()
    require_roles(role, ["OwnerDirector"])
    r = get_or_404("rate", DB.rates, rid)
    data = body()
    check_no_undeclared(data, set())
    if r["status"] != "CALCULATED":
        invalid_state("Rate is not CALCULATED")
    if r["cap_override_approved_by"] is None:
        invalid_state("No cap override has been approved")
    if user_id == r["cap_override_approved_by"]:
        err("ERR_ADOPTER_CANNOT_RATIFY", 403,
            "The cap-override approver may not also ratify")
    r["cap_override_ratified_by"] = user_id
    touch(r)
    return ok_object(rate_out(r))


@bp.route("/mpc/assessment-rates/<rid>/arm", methods=["POST"])
def arm_rate(rid):
    _, role = actor()
    require_roles(role, ["DeclarantController", "OwnerDirector"])
    r = get_or_404("rate", DB.rates, rid)
    data = body()
    check_no_undeclared(data, set())
    if r["status"] != "CALCULATED":
        invalid_state("Rate is not CALCULATED")
    community = DB.communities.get(r["community_id"])
    stage = community["transition_stage"] if community else "DECLARANT_CONTROL"
    if role == "DeclarantController" and stage == "TURNOVER_COMPLETE":
        err("ERR_DECLARANT_AUTHORITY_ENDED", 409,
            "Declarant-side arming power has ended")
    if role == "OwnerDirector" and stage != "TURNOVER_COMPLETE":
        err("ERR_FORBIDDEN_ROLE", 403,
            "OwnerDirector arms rates only after turnover")
    # Notice gates.
    notices = [n for n in DB.notices.values()
               if n["notice_type"] == "ASSESSMENT_CHANGE"
               and n["assessment_rate_id"] == r["id"]
               and n["status"] == "SENT"]
    if not notices:
        err("ERR_NOTICE_NOT_SENT", 409,
            "No SENT ASSESSMENT_CHANGE notice exists for this rate")
    fy_start = datetime(r["fiscal_year"], 1, 1, tzinfo=timezone.utc)
    deadline = fy_start - timedelta(days=ASSESSMENT_NOTICE_LEAD_DAYS)
    if not any(n["sent_at"] is not None and n["sent_at"] <= deadline
               for n in notices):
        err("ERR_NOTICE_LEAD_TIME", 422,
            "Assessment notice was sent inside the statutory lead window")
    # Statutory cap.
    if r["increase_pct"] is not None and Decimal(str(r["increase_pct"])) > STATUTORY_CAP_PCT:
        if r["cap_override_approved_by"] is None:
            err("ERR_ASSESSMENT_CAP_EXCEEDED", 422,
                "increase_pct exceeds the statutory cap without override")
        if stage in ("PARITY", "OWNER_MAJORITY") and r["cap_override_ratified_by"] is None:
            err("ERR_ASSESSMENT_CAP_EXCEEDED", 422,
                "Cap override requires OwnerDirector ratification at this stage")
    r["status"] = "ARMED"
    touch(r)
    return ok_object(rate_out(r))
