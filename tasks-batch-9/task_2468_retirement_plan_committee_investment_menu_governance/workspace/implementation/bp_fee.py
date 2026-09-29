"""Fee levelization runs and service provider engagements."""
import datetime

from flask import Blueprint

import calc
from core import (D, as_dec, as_enum, as_int, as_str, authenticate, body, clock,
                  fail, new_row, ok, ok_list, opt_field, paginate, parse_date,
                  public, q_bool, q_int, q_str, req_field, require_actor_plan,
                  resolve_committee_identity, store, touch)
from helpers import filter_rows, get_row, resolve_body_refs

bp = Blueprint("fee", __name__)

READ_ROLES = ("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
              "InvestmentConsultant", "Recordkeeper", "PlanAuditor")


# --------------------------------------------------------------------------- #
# Shared levelization helpers
# --------------------------------------------------------------------------- #

def _pool_funds(run):
    out = []
    for fund_id in run["pool_fund_ids"]:
        fund = store.funds.get(fund_id)
        if fund is not None:
            out.append(fund)
    return out


def _accrual_sum(funds):
    total = 0
    for fund in funds:
        total += calc.fund_accrual(fund)
    return total


def _require_pool_eligible(run, plan):
    """Priority 82's second arm: every pool fund is on the plan and ACCRUING."""
    for fund_id in run["pool_fund_ids"]:
        fund = store.funds.get(fund_id)
        if fund is None or fund["plan_id"] != plan["id"]:
            fail("ERR_POOL_FUND_INELIGIBLE",
                 "a pool fund does not belong to this plan")
        if fund["credit_accrual_status"] != "ACCRUING":
            fail("ERR_POOL_FUND_INELIGIBLE",
                 "pool fund %s is not ACCRUING" % fund["ticker"])


def _require_accounts(run, plan):
    if run["method"] == "PER_CAPITA" and plan["participant_account_count"] <= 0:
        fail("ERR_NO_PARTICIPANT_ACCOUNTS",
             "the plan has no participant accounts")


def _snapshot_pool(run, plan, requested_pool=None):
    """PRD 3.8: "Creation derives `pool_fund_ids` ... and snapshots
    `credit_pool_cents`" -- the accrual of the pool funds and the capped snapshot,
    and nothing else."""
    funds = _pool_funds(run)
    calc.accrue_fund_credit(plan, funds)
    total_accrual = _accrual_sum(funds)
    if requested_pool is None:
        requested_pool = total_accrual
    run["credit_pool_cents"] = min(requested_pool, total_accrual)
    calc.recompute_ledger(plan)
    touch(plan)


def _allocate(run, plan):
    """PRD 3.8's three passes, run where the spec puts them: at approval, which
    "freezes `allocation_lines`, `per_account_cents`, `allocated_total_cents` and
    `remainder_cents`", and at recomputation, which "recomputes" them. A newly
    created run "starts `DRAFT` with `allocation_lines` empty,
    `allocated_total_cents` and `remainder_cents` at 0, and `per_account_cents`
    ... null", so creation must not run them."""
    calc.compute_allocation(run, plan)
    run.pop("_eligible_pool_cents", None)


# --------------------------------------------------------------------------- #
# Fee levelization runs
# --------------------------------------------------------------------------- #

@bp.route("/governance/fee-levelization-runs", methods=["POST"])
def create_run():
    authenticate(("InvestmentConsultant", "Recordkeeper"))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans",
                                       "pool_fund_ids": "funds"})
    plan = refs.get("plan_id")
    quarter_index = as_int(req_field(payload, "quarter_index"), "quarter_index", 0)
    method = as_enum(req_field(payload, "method"), "method", calc.LEVEL_METHODS)
    requested = payload.get("credit_pool_cents")
    if requested is not None:
        requested = as_int(requested, "credit_pool_cents", 0)

    supplied = payload.get("pool_fund_ids")
    if supplied is not None:
        pool_ids = []
        for fund_id in supplied:
            if fund_id in pool_ids:
                fail("ERR_INVALID_REQUEST", "pool_fund_ids contains duplicates")
            pool_ids.append(fund_id)
    else:
        pool_ids = [f["id"] for f in calc.pool_order(
            [f for f in calc.plan_funds(plan["id"])
             if f["credit_accrual_status"] == "ACCRUING"])]

    for other in calc.plan_runs(plan["id"]):
        if other["status"] != "VOID" and other["quarter_index"] == quarter_index:
            fail("ERR_DUPLICATE_RESOURCE",
                 "the plan already has a live run for that quarter")

    run = new_row({
        "plan_id": plan["id"],
        "approving_motion_id": None,
        "quarter_index": quarter_index,
        "method": method,
        "credit_pool_cents": 0,
        "pool_fund_ids": pool_ids,
        "per_account_cents": None,
        "allocation_lines": [],
        "allocated_total_cents": 0,
        "remainder_cents": 0,
        "status": "DRAFT",
        "posted_at": None,
        "reversed_at": None,
    })
    _require_pool_eligible(run, plan)
    _require_accounts(run, plan)
    _snapshot_pool(run, plan, requested)
    store.runs[run["id"]] = run
    return ok(public(run), 201)


@bp.route("/governance/fee-levelization-runs", methods=["GET"])
def list_runs():
    authenticate(READ_ROLES)
    rows = filter_rows(list(store.runs.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("approving_motion_id"), "approving_motion_id"),
                        (q_int("quarter_index"), "quarter_index"),
                        (q_str("method"), "method"),
                        (q_str("status"), "status")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/fee-levelization-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    authenticate(READ_ROLES)
    return ok(public(get_row("runs", run_id, "runId")))


@bp.route("/governance/fee-levelization-runs/<run_id>/approve", methods=["POST"])
def approve_run(run_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    run = get_row("runs", run_id, "runId")
    plan = store.plans.get(run["plan_id"])
    require_actor_plan(actor, plan["id"])
    payload = body()
    refs = resolve_body_refs(payload, {"!approving_motion_id": "motions"},
                             extra_rows={"_run": ("runs", run)})
    motion = refs.get("approving_motion_id")

    if run["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "only a DRAFT run may be approved")
    calc.require_carried_motion(motion["id"], "FEE_LEVELIZATION", run["id"])
    calc.require_minutes_approved(motion)
    if run["quarter_index"] != plan["fiscal_quarter_index"]:
        fail("ERR_QUARTER_CLOSED", "the run's quarter is not the current quarter")
    if run["credit_pool_cents"] > plan["revenue_credit_balance_cents"]:
        fail("ERR_CREDIT_POOL_INSUFFICIENT",
             "the credit pool exceeds the plan's credit balance")
    _require_pool_eligible(run, plan)
    _require_accounts(run, plan)

    # PRD 3.8: approval is where the three passes land and freeze.
    _allocate(run, plan)
    run["approving_motion_id"] = motion["id"]
    run["status"] = "APPROVED"
    touch(run)
    return ok(public(run))


@bp.route("/governance/fee-levelization-runs/<run_id>/post", methods=["POST"])
def post_run(run_id):
    authenticate(("Recordkeeper",))
    run = get_row("runs", run_id, "runId")
    plan = store.plans.get(run["plan_id"])

    if run["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION", "only an APPROVED run may be posted")
    if run["credit_pool_cents"] > plan["revenue_credit_balance_cents"]:
        fail("ERR_CREDIT_POOL_INSUFFICIENT",
             "the credit pool exceeds the plan's credit balance")
    if run["allocated_total_cents"] + run["remainder_cents"] != \
            run["credit_pool_cents"]:
        fail("ERR_ALLOCATION_NOT_BALANCED",
             "the allocation no longer balances against the credit pool")
    if plan["fee_disclosure_status"] == "RESTATEMENT_REQUIRED":
        fail("ERR_FEE_DISCLOSURE_RESTATEMENT_REQUIRED",
             "the plan's fee disclosure requires restatement")
    if run["allocated_total_cents"] > plan["revenue_credit_balance_cents"]:
        fail("ERR_CREDIT_POOL_INSUFFICIENT",
             "posting would drive the credit balance below zero")

    # No per-fund floor: under PRO_RATA a fund may legitimately be handed a cent
    # it did not itself accrue, and the plan-level ledger identity still holds
    # because posting only *moves* cents between a fund's two credit figures.
    for line in run["allocation_lines"]:
        fund = store.funds.get(line["fund_id"])
        if fund is None:
            continue
        amount = line["allocated_cents"]
        fund["levelized_credit_cents"] += amount
        fund["accrued_revenue_credit_cents"] -= amount
        touch(fund)
    plan["revenue_credit_allocated_cents"] += run["allocated_total_cents"]
    calc.recompute_ledger(plan)
    touch(plan)

    run["posted_at"] = clock.iso()
    run["status"] = "POSTED"
    touch(run)
    return ok(public(run))


@bp.route("/governance/fee-levelization-runs/<run_id>/reverse", methods=["POST"])
def reverse_run(run_id):
    authenticate(("PlanSponsorAdmin",))
    run = get_row("runs", run_id, "runId")
    plan = store.plans.get(run["plan_id"])
    payload = body()
    reason = as_str(req_field(payload, "reason"), "reason", 1, 500)

    if run["status"] != "POSTED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a POSTED run may be reversed")
    if plan["fiscal_quarter_index"] - run["quarter_index"] > 1:
        fail("ERR_QUARTER_CLOSED", "the run's quarter is closed to reversal")

    for line in run["allocation_lines"]:
        fund = store.funds.get(line["fund_id"])
        if fund is None:
            continue
        amount = line["allocated_cents"]
        fund["levelized_credit_cents"] -= amount
        fund["accrued_revenue_credit_cents"] += amount
        touch(fund)
    plan["revenue_credit_allocated_cents"] -= run["allocated_total_cents"]
    calc.recompute_ledger(plan)
    touch(plan)

    run["reversal_reason"] = reason
    run["reversed_at"] = clock.iso()
    run["status"] = "REVERSED"
    touch(run)
    return ok(public(run))


@bp.route("/governance/fee-levelization-runs/<run_id>/recompute", methods=["POST"])
def recompute_run(run_id):
    authenticate(("InvestmentConsultant",))
    run = get_row("runs", run_id, "runId")
    plan = store.plans.get(run["plan_id"])
    payload = body()
    method = payload.get("method")
    if method is not None:
        method = as_enum(method, "method", calc.LEVEL_METHODS)
    requested = payload.get("credit_pool_cents")
    if requested is not None:
        requested = as_int(requested, "credit_pool_cents", 0)

    if run["status"] != "RECALC_REQUIRED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a RECALC_REQUIRED run may be recomputed")
    if run["quarter_index"] != plan["fiscal_quarter_index"]:
        fail("ERR_QUARTER_CLOSED", "the run's quarter is not the current quarter")

    if method is not None:
        run["method"] = method
    kept = []
    for fund_id in run["pool_fund_ids"]:
        fund = store.funds.get(fund_id)
        if fund is not None and fund["credit_accrual_status"] == "ACCRUING":
            kept.append(fund_id)
    run["pool_fund_ids"] = kept
    run["approving_motion_id"] = None
    _require_accounts(run, plan)
    _snapshot_pool(run, plan, requested)
    _allocate(run, plan)
    run["status"] = "DRAFT"
    touch(run)
    return ok(public(run))


# --------------------------------------------------------------------------- #
# Service provider engagements
# --------------------------------------------------------------------------- #

def _require_no_overlap(engagement, plan):
    start = parse_date(engagement["term_start_date"], "term_start_date")
    end = parse_date(engagement["term_end_date"], "term_end_date")
    for other in calc.plan_engagements(plan["id"]):
        if other["id"] == engagement["id"]:
            continue
        if other["provider_role"] != engagement["provider_role"]:
            continue
        if other["status"] not in calc.LIVE_ENGAGEMENT_STATES:
            continue
        o_start = parse_date(other["term_start_date"], "term_start_date")
        o_end = parse_date(other["term_end_date"], "term_end_date")
        if calc.intervals_overlap(start, end, o_start, o_end):
            fail("ERR_ENGAGEMENT_TERM_OVERLAP",
                 "the term overlaps a live engagement for this provider role")


@bp.route("/governance/service-provider-engagements", methods=["POST"])
def create_engagement():
    authenticate(("PlanSponsorAdmin",))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans"})
    plan = refs.get("plan_id")
    provider_name = as_str(req_field(payload, "provider_name"),
                           "provider_name", 1, 160)
    provider_role = as_enum(req_field(payload, "provider_role"), "provider_role",
                            calc.ENGAGEMENT_ROLES)
    start_raw = as_str(req_field(payload, "term_start_date"), "term_start_date")
    end_raw = as_str(req_field(payload, "term_end_date"), "term_end_date")
    start = parse_date(start_raw, "term_start_date")
    end = parse_date(end_raw, "term_end_date")
    per_head = as_int(req_field(payload, "per_head_fee_cents"),
                      "per_head_fee_cents", 0)
    asset_bps = as_int(req_field(payload, "asset_based_bps"),
                       "asset_based_bps", 0, 200)
    percentile = payload.get("benchmark_percentile")
    if percentile is not None:
        percentile = as_int(percentile, "benchmark_percentile", 1, 100)
    last_rfp = payload.get("last_rfp_quarter_index")
    if last_rfp is not None:
        last_rfp = as_int(last_rfp, "last_rfp_quarter_index", 0)
    if end < start:
        fail("ERR_INVALID_REQUEST",
             "term_end_date may not precede term_start_date")

    engagement = new_row({
        "plan_id": plan["id"],
        "successor_engagement_id": None,
        "approving_motion_id": None,
        "provider_name": provider_name,
        "provider_role": provider_role,
        "term_start_date": start_raw,
        "term_end_date": end_raw,
        "per_head_fee_cents": per_head,
        "asset_based_bps": asset_bps,
        "benchmark_percentile": percentile,
        "last_benchmarked_quarter_index": None,
        "last_rfp_quarter_index": last_rfp,
        "gross_cost_bps": None,
        "fee_credit_tier": None,
        "total_cost_bps": None,
        "rfp_required": False,
        "status": "PENDING",
    })
    _require_no_overlap(engagement, plan)
    store.engagements[engagement["id"]] = engagement
    return ok(public(engagement), 201)


@bp.route("/governance/service-provider-engagements", methods=["GET"])
def list_engagements():
    authenticate(READ_ROLES)
    rows = filter_rows(list(store.engagements.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("successor_engagement_id"),
                         "successor_engagement_id"),
                        (q_str("approving_motion_id"), "approving_motion_id"),
                        (q_str("provider_role"), "provider_role"),
                        (q_str("fee_credit_tier"), "fee_credit_tier"),
                        (q_str("status"), "status"),
                        (q_bool("rfp_required"), "rfp_required")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/service-provider-engagements/<engagement_id>",
          methods=["GET"])
def get_engagement(engagement_id):
    authenticate(READ_ROLES)
    return ok(public(get_row("engagements", engagement_id, "engagementId")))


@bp.route("/governance/service-provider-engagements/<engagement_id>/benchmark",
          methods=["POST"])
def benchmark_engagement(engagement_id):
    authenticate(("InvestmentConsultant",))
    engagement = get_row("engagements", engagement_id, "engagementId")
    plan = store.plans.get(engagement["plan_id"])
    payload = body()
    percentile = payload.get("benchmark_percentile")
    if percentile is None:
        percentile = engagement.get("benchmark_percentile")
        if percentile is None:
            fail("ERR_INVALID_REQUEST", "benchmark_percentile is required")
    percentile = as_int(percentile, "benchmark_percentile", 1, 100)

    status = engagement["status"]
    if status not in ("PENDING", "ACTIVE", "UNDER_RFP"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "a terminal engagement may not be benchmarked")
    if status == "ACTIVE":
        last = engagement.get("last_benchmarked_quarter_index")
        if last is not None and plan["fiscal_quarter_index"] <= last:
            fail("ERR_BENCHMARK_ALREADY_CURRENT",
                 "the engagement was already benchmarked this quarter")
    if status == "PENDING":
        _require_no_overlap(engagement, plan)

    engagement["benchmark_percentile"] = percentile
    gross, tier, total, rfp_required = calc.provider_cost(engagement, plan)
    engagement["gross_cost_bps"] = gross
    engagement["fee_credit_tier"] = tier
    engagement["total_cost_bps"] = total
    engagement["rfp_required"] = rfp_required
    engagement["last_benchmarked_quarter_index"] = plan["fiscal_quarter_index"]

    if status in ("PENDING", "ACTIVE"):
        engagement["status"] = "UNDER_RFP" if rfp_required else "ACTIVE"
    else:
        if not rfp_required:
            engagement["status"] = "ACTIVE"
            engagement["last_rfp_quarter_index"] = plan["fiscal_quarter_index"]
    touch(engagement)
    return ok(public(engagement))


@bp.route("/governance/service-provider-engagements/<engagement_id>/rfp-award",
          methods=["POST"])
def award_rfp(engagement_id):
    authenticate(("PlanSponsorAdmin",))
    engagement = get_row("engagements", engagement_id, "engagementId")
    plan = store.plans.get(engagement["plan_id"])
    payload = body()
    refs = resolve_body_refs(payload, {"!approving_motion_id": "motions",
                                       "!successor_engagement_id": "engagements"},
                             extra_rows={"_engagement": ("engagements",
                                                         engagement)})
    motion = refs.get("approving_motion_id")
    successor = refs.get("successor_engagement_id")

    if engagement["status"] != "UNDER_RFP":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an UNDER_RFP engagement may be awarded")
    role = engagement["provider_role"]
    for vote in motion.get("votes") or []:
        if vote["vote"] != "FOR":
            continue
        member = store.members.get(vote["member_id"])
        if member is None or member["status"] != "ACTIVE":
            continue
        if (member.get("affiliated_provider_role") or "NONE") == role:
            fail("ERR_RECUSAL_REQUIRED",
                 "an affiliated member voted FOR on the award motion")
    calc.require_carried_motion(motion["id"], "RFP_AWARD", engagement["id"])
    calc.require_minutes_approved(motion)

    if successor["id"] == engagement["id"] or \
            successor["plan_id"] != engagement["plan_id"] or \
            successor["provider_role"] != role or \
            successor["status"] != "PENDING":
        fail("ERR_RESOURCE_NOT_FOUND",
             "successor_engagement_id is not a PENDING engagement for this role")

    successor_start = parse_date(successor["term_start_date"], "term_start_date")
    clamp = successor_start - datetime.timedelta(days=1)
    engagement["successor_engagement_id"] = successor["id"]
    engagement["approving_motion_id"] = motion["id"]
    engagement["term_end_date"] = clamp.isoformat()
    engagement["status"] = "SUPERSEDED"
    touch(engagement)

    successor["status"] = "ACTIVE"
    successor["approving_motion_id"] = motion["id"]
    successor["last_rfp_quarter_index"] = plan["fiscal_quarter_index"]
    touch(successor)
    return ok(public(engagement))


@bp.route("/governance/service-provider-engagements/<engagement_id>/terminate",
          methods=["POST"])
def terminate_engagement(engagement_id):
    authenticate(("PlanSponsorAdmin",))
    engagement = get_row("engagements", engagement_id, "engagementId")
    plan = store.plans.get(engagement["plan_id"])
    payload = body()
    reason = as_str(req_field(payload, "reason"), "reason", 1, 500)

    if engagement["status"] not in ("PENDING", "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a PENDING or ACTIVE engagement may be terminated")
    if engagement["provider_role"] == "RECORDKEEPER":
        survivor = False
        for other in calc.plan_engagements(plan["id"]):
            if other["id"] == engagement["id"]:
                continue
            if other["provider_role"] != "RECORDKEEPER":
                continue
            if other["status"] in ("PENDING", "ACTIVE"):
                survivor = True
                break
        if not survivor:
            fail("ERR_RECORDKEEPER_REQUIRED",
                 "the plan would be left without a recordkeeper")
    for proposal in calc.plan_proposals(plan["id"]):
        if proposal["status"] == "NOTICE_ISSUED":
            fail("ERR_ENGAGEMENT_HAS_PENDING_MAPPING",
                 "a noticed mapping is still outstanding on the plan")

    today = clock.date()
    end = parse_date(engagement["term_end_date"], "term_end_date")
    if end > today:
        engagement["term_end_date"] = today.isoformat()
    engagement["termination_reason"] = reason
    engagement["status"] = "TERMINATED"
    touch(engagement)
    return ok(public(engagement))
