"""Fund registration, monitoring updates, share-class change, QDIA selection."""
from flask import Blueprint, request

import calc
from core import (D, as_bool, as_dec, as_enum, as_int, as_str, authenticate,
                  body, fail, new_row, ok, ok_list, opt_field, paginate, public,
                  q_bool, q_str, req_field, store, touch)
from helpers import filter_rows, get_row, require_posture, resolve_body_refs

bp = Blueprint("funds", __name__)

GLIDEPATH_FIELDS = ("glidepath_type", "construction", "equity_at_65_pct",
                    "landing_point_age")


def _refresh_plan(plan):
    calc.recompute_posture(plan)
    touch(plan)


def _fund_plan(fund):
    return store.plans.get(fund["plan_id"])


@bp.route("/governance/funds", methods=["POST"])
def create_fund():
    authenticate(("InvestmentConsultant", "Recordkeeper"))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans"})
    plan = refs.get("plan_id")
    ticker = as_str(req_field(payload, "ticker"), "ticker", 1, 20)
    fund_name = as_str(req_field(payload, "fund_name"), "fund_name", 1, 160)
    asset_class = as_enum(req_field(payload, "asset_class_code"),
                          "asset_class_code", calc.ASSET_CLASSES)
    share_class = as_enum(req_field(payload, "share_class_code"),
                          "share_class_code", calc.SHARE_CLASSES)
    gross = as_int(req_field(payload, "gross_expense_ratio_bps"),
                   "gross_expense_ratio_bps", 0, 300)
    net = as_int(req_field(payload, "net_expense_ratio_bps"),
                 "net_expense_ratio_bps", 0, 300)
    revenue = as_int(req_field(payload, "revenue_share_bps"),
                     "revenue_share_bps", 0, 100)
    peer = as_int(req_field(payload, "peer_median_expense_bps"),
                  "peer_median_expense_bps", 1, 300)
    track = as_int(req_field(payload, "track_record_quarters"),
                   "track_record_quarters", 0)
    tenure = as_int(req_field(payload, "manager_tenure_quarters"),
                    "manager_tenure_quarters", 0)
    change_flag = as_bool(opt_field(payload, "manager_change_flag", False),
                          "manager_change_flag")
    drift = as_dec(req_field(payload, "style_drift_r2"), "style_drift_r2", 4,
                   "0.0000", "1.0000")
    assets = as_int(opt_field(payload, "plan_assets_cents", 0),
                    "plan_assets_cents", 0)
    is_suite = as_bool(opt_field(payload, "is_target_date_suite", False),
                       "is_target_date_suite")
    glidepath_type = payload.get("glidepath_type")
    construction = payload.get("construction")
    equity = payload.get("equity_at_65_pct")
    landing = payload.get("landing_point_age")

    if net > gross:
        fail("ERR_INVALID_REQUEST",
             "net_expense_ratio_bps may not exceed gross_expense_ratio_bps")
    if is_suite:
        for name in GLIDEPATH_FIELDS:
            if payload.get(name) is None:
                fail("ERR_INVALID_REQUEST",
                     "%s is required for a target-date suite" % name)
        glidepath_type = as_enum(glidepath_type, "glidepath_type",
                                 calc.GLIDEPATH_TYPES)
        construction = as_enum(construction, "construction", calc.CONSTRUCTIONS)
        equity = as_dec(equity, "equity_at_65_pct", 2, "0.00", "100.00")
        landing = as_int(landing, "landing_point_age", 60, 95)
    else:
        if glidepath_type is not None:
            glidepath_type = as_enum(glidepath_type, "glidepath_type",
                                     calc.GLIDEPATH_TYPES)
        if construction is not None:
            construction = as_enum(construction, "construction",
                                   calc.CONSTRUCTIONS)
        if equity is not None:
            equity = as_dec(equity, "equity_at_65_pct", 2, "0.00", "100.00")
        if landing is not None:
            landing = as_int(landing, "landing_point_age", 60, 95)

    for other in calc.plan_funds(plan["id"]):
        if other["ticker"] == ticker and other["menu_status"] != "REMOVED":
            fail("ERR_DUPLICATE_RESOURCE", "ticker already registered on this plan")

    fund = new_row({
        "plan_id": plan["id"],
        "ticker": ticker,
        "fund_name": fund_name,
        "asset_class_code": asset_class,
        "share_class_code": share_class,
        "gross_expense_ratio_bps": gross,
        "net_expense_ratio_bps": net,
        "revenue_share_bps": revenue,
        "peer_median_expense_bps": peer,
        "track_record_quarters": track,
        "manager_tenure_quarters": tenure,
        "manager_change_flag": change_flag,
        "style_drift_r2": drift,
        "plan_assets_cents": assets,
        "menu_status": "CANDIDATE",
        "watch_status": "CLEAR",
        "watch_started_quarter_index": None,
        "consecutive_breach_quarters": 0,
        "latest_composite_score": None,
        "accrued_revenue_credit_cents": 0,
        "credit_accrual_status": "NOT_ACCRUING",
        "levelized_credit_cents": 0,
        "watch_status_before_last_review": None,
        "menu_status_before_last_review": None,
        "last_scored_quarter_index": None,
        "is_target_date_suite": is_suite,
        "glidepath_type": glidepath_type,
        "construction": construction,
        "equity_at_65_pct": equity,
        "landing_point_age": landing,
        "glidepath_fit_score": None,
        "qdia_flag": False,
    })
    calc.refresh_glidepath(fund)
    store.funds[fund["id"]] = fund
    _refresh_plan(plan)
    return ok(public(fund), 201)


@bp.route("/governance/funds", methods=["GET"])
def list_funds():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    rows = filter_rows(list(store.funds.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("asset_class_code"), "asset_class_code"),
                        (q_str("menu_status"), "menu_status"),
                        (q_str("watch_status"), "watch_status"),
                        (q_bool("is_target_date_suite"), "is_target_date_suite"),
                        (q_str("share_class_code"), "share_class_code"),
                        (q_str("ticker"), "ticker")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/funds/<fund_id>", methods=["GET"])
def get_fund(fund_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    return ok(public(get_row("funds", fund_id, "fundId")))


@bp.route("/governance/funds/<fund_id>", methods=["PATCH"])
def patch_fund(fund_id):
    authenticate(("Recordkeeper", "InvestmentConsultant"))
    fund = get_row("funds", fund_id, "fundId")
    payload = body()
    updates = {}
    if payload.get("gross_expense_ratio_bps") is not None:
        updates["gross_expense_ratio_bps"] = as_int(
            payload["gross_expense_ratio_bps"], "gross_expense_ratio_bps", 0, 300)
    if payload.get("net_expense_ratio_bps") is not None:
        updates["net_expense_ratio_bps"] = as_int(
            payload["net_expense_ratio_bps"], "net_expense_ratio_bps", 0, 300)
    if payload.get("revenue_share_bps") is not None:
        updates["revenue_share_bps"] = as_int(payload["revenue_share_bps"],
                                              "revenue_share_bps", 0, 100)
    if payload.get("peer_median_expense_bps") is not None:
        updates["peer_median_expense_bps"] = as_int(
            payload["peer_median_expense_bps"], "peer_median_expense_bps", 1, 300)
    if payload.get("track_record_quarters") is not None:
        updates["track_record_quarters"] = as_int(
            payload["track_record_quarters"], "track_record_quarters", 0)
    if payload.get("manager_tenure_quarters") is not None:
        updates["manager_tenure_quarters"] = as_int(
            payload["manager_tenure_quarters"], "manager_tenure_quarters", 0)
    if payload.get("manager_change_flag") is not None:
        updates["manager_change_flag"] = as_bool(payload["manager_change_flag"],
                                                 "manager_change_flag")
    if payload.get("style_drift_r2") is not None:
        updates["style_drift_r2"] = as_dec(payload["style_drift_r2"],
                                           "style_drift_r2", 4, "0.0000", "1.0000")
    if payload.get("plan_assets_cents") is not None:
        updates["plan_assets_cents"] = as_int(payload["plan_assets_cents"],
                                              "plan_assets_cents", 0)
    if payload.get("equity_at_65_pct") is not None:
        updates["equity_at_65_pct"] = as_dec(payload["equity_at_65_pct"],
                                             "equity_at_65_pct", 2, "0.00", "100.00")
    if payload.get("landing_point_age") is not None:
        updates["landing_point_age"] = as_int(payload["landing_point_age"],
                                              "landing_point_age", 60, 95)
    if not updates:
        fail("ERR_INVALID_REQUEST", "no updatable field supplied")
    gross = updates.get("gross_expense_ratio_bps", fund["gross_expense_ratio_bps"])
    net = updates.get("net_expense_ratio_bps", fund["net_expense_ratio_bps"])
    if net > gross:
        fail("ERR_INVALID_REQUEST",
             "net_expense_ratio_bps may not exceed gross_expense_ratio_bps")

    fund.update(updates)
    calc.refresh_glidepath(fund)
    touch(fund)
    _refresh_plan(_fund_plan(fund))
    return ok(public(fund))


@bp.route("/governance/funds/<fund_id>/share-class-change", methods=["POST"])
def share_class_change(fund_id):
    authenticate(("InvestmentConsultant", "Recordkeeper"))
    fund = get_row("funds", fund_id, "fundId")
    payload = body()
    plan = _fund_plan(fund)
    share_class = as_enum(req_field(payload, "share_class_code"),
                          "share_class_code", calc.SHARE_CLASSES)
    net = as_int(req_field(payload, "net_expense_ratio_bps"),
                 "net_expense_ratio_bps", 0, 300)
    gross = as_int(opt_field(payload, "gross_expense_ratio_bps",
                             fund["gross_expense_ratio_bps"]),
                   "gross_expense_ratio_bps", 0, 300)
    revenue = as_int(req_field(payload, "revenue_share_bps"),
                     "revenue_share_bps", 0, 100)

    seated_slot = None
    for slot in calc.plan_slots(plan["id"]):
        if slot.get("current_fund_id") == fund["id"] and slot["status"] != "RETIRED":
            seated_slot = slot
            break
    require_posture(plan, seated_slot)

    if net >= fund["net_expense_ratio_bps"]:
        fail("ERR_SHARE_CLASS_INELIGIBLE",
             "the new share class is not strictly cheaper")
    if revenue > fund["revenue_share_bps"]:
        fail("ERR_SHARE_CLASS_INELIGIBLE",
             "the new share class raises revenue sharing")
    for proposal in calc.plan_proposals(plan["id"]):
        if proposal["status"] not in ("APPROVED", "NOTICE_ISSUED"):
            continue
        if fund["id"] in (proposal.get("outgoing_fund_id"),
                          proposal.get("incoming_fund_id")):
            fail("ERR_SHARE_CLASS_INELIGIBLE",
                 "the fund sits inside an APPROVED or NOTICE_ISSUED proposal")
    # PRD 2.12 priority 38 does not list the net-versus-gross relation among the
    # request-shape rules, and PRD 3.3 states it as a creation-time domain
    # constraint, so a share class that is merely more expensive answers with the
    # eligibility error above rather than a 400. The invariant is still upheld
    # here, after the eligibility ladder has had its say.
    if net > gross:
        fail("ERR_INVALID_REQUEST",
             "net_expense_ratio_bps may not exceed gross_expense_ratio_bps")

    fund["share_class_code"] = share_class
    fund["net_expense_ratio_bps"] = net
    fund["gross_expense_ratio_bps"] = gross
    fund["revenue_share_bps"] = revenue
    calc.refresh_glidepath(fund)
    touch(fund)
    _refresh_plan(plan)
    return ok(public(fund))


@bp.route("/governance/funds/<fund_id>/target-date-selection", methods=["POST"])
def target_date_selection(fund_id):
    authenticate(("CommitteeChair",))
    fund = get_row("funds", fund_id, "fundId")
    payload = body()
    plan = _fund_plan(fund)
    refs = resolve_body_refs(payload, {"!approving_motion_id": "motions"},
                             extra_rows={"_fund": ("funds", fund)})
    motion = refs.get("approving_motion_id")
    glidepath_type = payload.get("glidepath_type")
    if glidepath_type is None:
        glidepath_type = fund.get("glidepath_type")
    if glidepath_type is None:
        fail("ERR_INVALID_REQUEST", "glidepath_type is required")
    glidepath_type = as_enum(glidepath_type, "glidepath_type", calc.GLIDEPATH_TYPES)

    if fund["menu_status"] != "CANDIDATE":
        fail("ERR_FUND_NOT_CANDIDATE", "the fund is not a CANDIDATE")
    slot = calc.qdia_slot(plan["id"])
    if slot is None:
        fail("ERR_QDIA_SLOT_REQUIRED", "the plan has no QDIA-designated slot")
    require_posture(plan, slot)
    if motion["subject_type"] != "TARGET_DATE_SELECTION" or \
            motion["subject_id"] != fund["id"]:
        fail("ERR_MOTION_SUBJECT_MISMATCH", "the motion's subject is not this fund")
    if motion["status"] != "CARRIED":
        fail("ERR_MOTION_NOT_CARRIED", "the referenced motion did not carry")
    calc.require_minutes_approved(motion)

    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")
    calc.require_ips_eligible(fund, adopted)
    if not fund.get("is_target_date_suite"):
        fail("ERR_QDIA_REQUIRES_TARGET_DATE_SUITE",
             "the fund is not a target-date suite")
    pool = calc.target_date_pool(plan["id"], glidepath_type, adopted)
    if not pool:
        fail("ERR_NO_ELIGIBLE_TARGET_DATE_SUITE",
             "no target-date candidate qualifies")
    winner = pool[0]
    if winner["id"] != fund["id"]:
        fail("ERR_INVALID_REQUEST",
             "the top-ranked candidate is %s" % winner["ticker"])
    if slot["status"] == "EMPTY" and plan["available_menu_slots"] < 1:
        fail("ERR_MENU_CAPACITY_EXHAUSTED", "no available menu slot remains")

    prior = store.funds.get(slot.get("current_fund_id"))
    if prior is not None and prior["id"] != fund["id"]:
        if prior["menu_status"] == "ACTIVE":
            prior["menu_status"] = "PENDING_REMOVAL"
        prior["qdia_flag"] = False
        touch(prior)
    slot["current_fund_id"] = fund["id"]
    if slot["status"] == "EMPTY":
        slot["status"] = "ACTIVE"
    touch(slot)
    fund["menu_status"] = "ACTIVE"
    fund["qdia_flag"] = True
    fund["credit_accrual_status"] = "ACCRUING"
    touch(fund)
    _refresh_plan(plan)
    return ok(public(fund))
