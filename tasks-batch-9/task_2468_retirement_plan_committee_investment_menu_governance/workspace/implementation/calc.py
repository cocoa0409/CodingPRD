"""Calculations, derived aggregates and shared domain predicates."""
from decimal import Decimal

from core import (D, Q2, Q4, dfloor, fail, r0, r2, r4, sort_created, store,
                  touch, clock, parse_date)

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #

PLAN_TYPES = ("401K", "403B", "457B")
SEAT_CLASSES = ("CHAIR", "SPONSOR_FIDUCIARY", "FINANCE", "HR",
                "PARTICIPANT_REP", "INDEPENDENT")
PROVIDER_ROLES = ("NONE", "RECORDKEEPER", "ADVISOR", "AUDITOR", "CUSTODIAN")
ENGAGEMENT_ROLES = ("RECORDKEEPER", "ADVISOR", "AUDITOR", "CUSTODIAN")
MODULES = ("FIDUCIARY_DUTIES", "IPS_MECHANICS", "FEE_BENCHMARKING",
           "PROHIBITED_TRANSACTIONS")
REQUIRED_MODULES = ("FIDUCIARY_DUTIES", "IPS_MECHANICS")
ASSET_CLASSES = ("US_LARGE_CAP", "US_SMALL_CAP", "INTL_DEVELOPED",
                 "EMERGING_MKTS", "CORE_BOND", "TIPS", "STABLE_VALUE",
                 "TARGET_DATE", "REAL_ASSETS", "SELF_DIRECTED")
DESIGNATIONS = ("CORE", "SPECIALTY", "QDIA")
SHARE_CLASSES = ("R1", "R3", "R6", "INSTITUTIONAL", "ADMIN", "INVESTOR")
SCORING_VARIANTS = ("TRAILING_PERIOD", "ROLLING_SINCE_WATCH")
GLIDEPATH_TYPES = ("TO_RETIREMENT", "THROUGH_RETIREMENT")
CONSTRUCTIONS = ("OFF_THE_SHELF", "CUSTOM")
SUBJECT_TYPES = ("IPS_ADOPTION", "FUND_REPLACEMENT", "TARGET_DATE_SELECTION",
                 "FEE_LEVELIZATION", "RFP_AWARD", "WATCH_LIST_ACTION")
TALLY_BASES = ("VOTES_CAST", "ELIGIBLE_VOTERS")
VOTE_VALUES = ("FOR", "AGAINST", "ABSTAIN", "RECUSE")
MAPPING_STRATEGIES = ("DIRECT_MAP", "MAP_TO_QDIA", "REENROLLMENT")
LEVEL_METHODS = ("PER_CAPITA", "PRO_RATA")
END_TERM_REASONS = ("RESIGNATION", "REMOVAL_FOR_CAUSE", "TERM_EXPIRY")
WEIGHT_KEYS = ("performance", "peer", "expense", "style", "manager")

OCCUPIED_SLOT_STATES = ("ACTIVE", "AT_RISK", "PENDING_REPLACEMENT")
AT_RISK_SLOT_STATES = ("AT_RISK", "PENDING_REPLACEMENT")
RESERVING_PROPOSAL_STATES = ("APPROVED", "NOTICE_ISSUED")
NON_TERMINAL_PROPOSAL_STATES = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED",
                                "BLOCKED", "APPROVED", "NOTICE_ISSUED")
BLOCKABLE_PROPOSAL_STATES = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED")
NON_TERMINAL_MEMBER_STATES = ("APPOINTED", "TRAINING_ASSIGNED",
                              "ACCEPTANCE_PENDING", "ACTIVE")
LIVE_ENGAGEMENT_STATES = ("PENDING", "ACTIVE", "UNDER_RFP")

SUBJECT_COLLECTION = {
    "IPS_ADOPTION": "ips",
    "FUND_REPLACEMENT": "proposals",
    "TARGET_DATE_SELECTION": "funds",
    "FEE_LEVELIZATION": "runs",
    "RFP_AWARD": "engagements",
    "WATCH_LIST_ACTION": "funds",
}


# --------------------------------------------------------------------------- #
# Collection scans
# --------------------------------------------------------------------------- #

def plan_slots(plan_id):
    return [s for s in store.slots.values() if s["plan_id"] == plan_id]


def plan_funds(plan_id):
    return [f for f in store.funds.values() if f["plan_id"] == plan_id]


def plan_seats(plan_id):
    return [s for s in store.seats.values() if s["plan_id"] == plan_id]


def plan_members(plan_id):
    out = []
    for m in store.members.values():
        seat = store.seats.get(m["seat_id"])
        if seat is not None and seat["plan_id"] == plan_id:
            out.append(m)
    return out


def plan_meetings(plan_id):
    return [m for m in store.meetings.values() if m["plan_id"] == plan_id]


def plan_motions(plan_id):
    out = []
    for mo in store.motions.values():
        meeting = store.meetings.get(mo["meeting_id"])
        if meeting is not None and meeting["plan_id"] == plan_id:
            out.append(mo)
    return out


def meeting_motions(meeting_id):
    return [mo for mo in store.motions.values() if mo["meeting_id"] == meeting_id]


def plan_proposals(plan_id):
    return [p for p in store.proposals.values() if p["plan_id"] == plan_id]


def plan_runs(plan_id):
    return [r for r in store.runs.values() if r["plan_id"] == plan_id]


def plan_engagements(plan_id):
    return [e for e in store.engagements.values() if e["plan_id"] == plan_id]


def plan_reviews(plan_id):
    return [r for r in store.reviews.values() if r["plan_id"] == plan_id]


def plan_ips(plan_id):
    return [i for i in store.ips.values() if i["plan_id"] == plan_id]


def adopted_ips(plan_id):
    for row in plan_ips(plan_id):
        if row["status"] == "ADOPTED":
            return row
    return None


def member_plan_id(member):
    seat = store.seats.get(member["seat_id"])
    return seat["plan_id"] if seat else None


def slot_index_of(slot):
    return slot["slot_index"] if slot else 10 ** 9


def slot_order(slots):
    return sorted(slots, key=lambda s: (s["slot_index"], s["_seq"]))


def qdia_slot(plan_id):
    for slot in plan_slots(plan_id):
        if slot["designation"] == "QDIA" and slot["status"] != "RETIRED":
            return slot
    return None


# --------------------------------------------------------------------------- #
# Derived plan aggregates
# --------------------------------------------------------------------------- #

def recompute_capacity(plan):
    slots = plan_slots(plan["id"])
    occupied = len([s for s in slots if s["status"] in OCCUPIED_SLOT_STATES])
    reserved = len([p for p in plan_proposals(plan["id"])
                    if p["status"] in RESERVING_PROPOSAL_STATES])
    plan["occupied_menu_slots"] = occupied
    plan["reserved_menu_slots"] = reserved
    plan["available_menu_slots"] = plan["menu_slot_capacity"] - occupied - reserved
    plan["draft_proposal_count"] = len(
        [p for p in plan_proposals(plan["id"]) if p["status"] == "DRAFT"])


def recompute_assets(plan):
    total = 0
    for fund in plan_funds(plan["id"]):
        if fund["menu_status"] in ("ACTIVE", "PENDING_REMOVAL"):
            total += fund["plan_assets_cents"]
    plan["total_plan_assets_cents"] = total


def recompute_ledger(plan):
    accrued = 0
    for fund in plan_funds(plan["id"]):
        accrued += fund["accrued_revenue_credit_cents"] + fund["levelized_credit_cents"]
    plan["revenue_credit_accrued_cents"] = accrued
    plan["revenue_credit_balance_cents"] = (
        accrued - plan["revenue_credit_allocated_cents"])


def recompute_acceptance_count(plan):
    count = 0
    for member in plan_members(plan["id"]):
        if member.get("acceptance_signed_at") and member["status"] in (
                "ACCEPTANCE_PENDING", "ACTIVE"):
            count += 1
    plan["documented_acceptance_count"] = count


def at_risk_ratio(plan):
    slots = plan_slots(plan["id"])
    denominator = len([s for s in slots if s["status"] in OCCUPIED_SLOT_STATES])
    numerator = len([s for s in slots if s["status"] in AT_RISK_SLOT_STATES])
    if denominator == 0:
        return Decimal("0.0000")
    return r4(D(numerator) / D(denominator))


def active_voting_member_count(plan_id):
    count = 0
    for seat in plan_seats(plan_id):
        if not seat.get("voting") or seat["status"] != "FILLED":
            continue
        for member in store.members.values():
            if member["seat_id"] == seat["id"] and member["status"] == "ACTIVE":
                count += 1
                break
    return count


def compute_menu_posture(plan):
    """PRD 2.9 three-arm ladder, evaluated top down."""
    ratio = at_risk_ratio(plan)
    plan["at_risk_slot_ratio"] = ratio
    has_adopted_ips = adopted_ips(plan["id"]) is not None
    active_voters = active_voting_member_count(plan["id"])
    if (plan["charter_status"] != "ADOPTED"
            or not has_adopted_ips
            or active_voters < plan["quorum_min_voting_members"]
            or ratio >= Decimal("0.5000")):
        return "FROZEN"
    termination_pending = any(
        f["watch_status"] == "TERMINATION_PENDING" for f in plan_funds(plan["id"]))
    if (Decimal("0.2500") <= ratio < Decimal("0.5000")
            or termination_pending
            or plan["fee_disclosure_status"] == "RESTATEMENT_REQUIRED"):
        return "RESTRICTED"
    return "OPEN"


def recompute_derived(plan):
    recompute_capacity(plan)
    recompute_assets(plan)
    recompute_ledger(plan)
    recompute_acceptance_count(plan)
    plan["at_risk_slot_ratio"] = at_risk_ratio(plan)


def recompute_posture(plan, release_blocked=True):
    """Recompute the ratio and posture; release BLOCKED proposals when OPEN."""
    recompute_derived(plan)
    posture = compute_menu_posture(plan)
    plan["menu_posture"] = posture
    if release_blocked and posture == "OPEN":
        release_blocked_proposals(plan)
    return posture


def release_blocked_proposals(plan):
    """Restore BLOCKED proposals to pre_block_status; slot_index ASC then
    created_at ASC."""
    blocked = [p for p in plan_proposals(plan["id"]) if p["status"] == "BLOCKED"]
    ordered = sorted(
        blocked,
        key=lambda p: (slot_index_of(store.slots.get(p["slot_id"])),
                       p["created_at"], p["_seq"]))
    for proposal in ordered:
        prior = proposal.get("pre_block_status") or "DRAFT"
        proposal["status"] = prior
        proposal["pre_block_status"] = None
        touch(proposal)
    if ordered:
        recompute_capacity(plan)


def block_proposals_for_posture(plan, posture):
    """Finalize hop 4 / posture tightening sweep."""
    if posture == "OPEN":
        return
    at_risk_classes = set()
    for slot in plan_slots(plan["id"]):
        if slot["status"] in AT_RISK_SLOT_STATES:
            at_risk_classes.add(slot["asset_class_code"])
    candidates = [p for p in plan_proposals(plan["id"])
                  if p["status"] in BLOCKABLE_PROPOSAL_STATES]
    ordered = sorted(
        candidates,
        key=lambda p: (slot_index_of(store.slots.get(p["slot_id"])),
                       p["created_at"], p["_seq"]))
    for proposal in ordered:
        if posture == "RESTRICTED":
            incoming = store.funds.get(proposal["incoming_fund_id"])
            if incoming is None or incoming["asset_class_code"] not in at_risk_classes:
                continue
        proposal["pre_block_status"] = proposal["status"]
        proposal["status"] = "BLOCKED"
        touch(proposal)
    if ordered:
        recompute_capacity(plan)


# --------------------------------------------------------------------------- #
# Training currency
# --------------------------------------------------------------------------- #

def member_records(member_id):
    return [r for r in store.training.values() if r["member_id"] == member_id]


def record_is_current(record, fiscal_quarter_index):
    if record["status"] not in ("COMPLETED", "WAIVED"):
        return False
    if record.get("completed_quarter_index") is None:
        return False
    return (fiscal_quarter_index - record["completed_quarter_index"]
            < record["validity_quarters"])


def compute_training_status(member):
    plan_id = member_plan_id(member)
    plan = store.plans.get(plan_id)
    fqi = plan["fiscal_quarter_index"] if plan else 0
    records = member_records(member["id"])
    have_all = True
    all_current = True
    for module in REQUIRED_MODULES:
        # PRD 3.2: a module "has a record" once it was completed or waived, even
        # after the quarter sweep of PRD 3.9 has stamped that record EXPIRED --
        # a stale record makes the member EXPIRED, never PENDING.
        module_records = [r for r in records
                          if r["module_code"] == module
                          and r["status"] in ("COMPLETED", "WAIVED", "EXPIRED")
                          and r.get("completed_quarter_index") is not None]
        if not module_records:
            have_all = False
            all_current = False
            continue
        if not any(record_is_current(r, fqi) for r in module_records):
            all_current = False
    if all_current:
        return "CURRENT"
    if have_all:
        return "EXPIRED"
    return "PENDING"


def refresh_training_status(member):
    member["fiduciary_training_status"] = compute_training_status(member)
    return member["fiduciary_training_status"]


def member_is_fit(member):
    return (member["fiduciary_training_status"] == "CURRENT"
            and member.get("acceptance_signed_at") is not None)


# --------------------------------------------------------------------------- #
# IPS eligibility
# --------------------------------------------------------------------------- #

def ips_eligible(fund, ips):
    """Returns None when eligible, else the failing criterion index."""
    if fund["track_record_quarters"] < ips["min_track_record_quarters"]:
        return 1
    cap = dfloor(D(fund["peer_median_expense_bps"]) * D(ips["expense_peer_multiple"]))
    if fund["net_expense_ratio_bps"] > cap:
        return 2
    if D(fund["style_drift_r2"]) < D(ips["style_drift_r2_floor"]):
        return 3
    if fund["manager_change_flag"] and fund["manager_tenure_quarters"] < 4:
        return 4
    return None


def require_ips_eligible(fund, ips):
    failing = ips_eligible(fund, ips)
    if failing is not None:
        fail("ERR_FUND_FAILS_IPS_CRITERIA",
             "candidate fund fails IPS selection criterion %d" % failing)


# --------------------------------------------------------------------------- #
# Composite score and watch recommendation
# --------------------------------------------------------------------------- #

def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def composite_components(card, ips, variant):
    if variant == "ROLLING_SINCE_WATCH":
        excess = D(card["rolling_since_watch_return_bps"]) - \
            D(card["rolling_since_watch_benchmark_bps"])
        excess_bps = D(r0(excess))
    else:
        blended = (D("0.6") * (D(card["trailing_3y_return_bps"])
                              - D(card["benchmark_3y_return_bps"]))
                   + D("0.4") * (D(card["trailing_5y_return_bps"])
                                 - D(card["benchmark_5y_return_bps"])))
        excess_bps = D(r0(blended))

    performance = clamp(D("50.00") + excess_bps / D(10), D("0.00"), D("100.00"))
    peer = D("100.00") - D(card["peer_rank_pct"])
    over = card["net_expense_ratio_bps"] - card["peer_median_expense_bps"]
    if over < 0:
        over = 0
    expense = clamp(D("100.00") - D(over) * D(2), D("0.00"), D("100.00"))
    floor_r2 = D(ips["style_drift_r2_floor"])
    drift = D(card["style_drift_r2"])
    if drift >= floor_r2:
        style = D("100.00")
    else:
        style = D("100.00") - (floor_r2 - drift) * D(500)
        if style < D("0.00"):
            style = D("0.00")
    tenure = D(card["manager_tenure_quarters"])
    if card["manager_change_flag"]:
        manager = min(D("40.00"), tenure * D(2))
    else:
        manager = min(D("100.00"), D("40.00") + tenure * D(3))

    components = {
        "performance_component": r2(performance),
        "peer_component": r2(peer),
        "expense_component": r2(expense),
        "style_component": r2(style),
        "manager_component": r2(manager),
    }
    weights = ips["weights"]
    total = (D(weights["performance"]) * components["performance_component"]
             + D(weights["peer"]) * components["peer_component"]
             + D(weights["expense"]) * components["expense_component"]
             + D(weights["style"]) * components["style_component"]
             + D(weights["manager"]) * components["manager_component"])
    components["composite_score"] = r2(total)
    return components


def watch_recommendation(card, fund, ips):
    score = D(card["composite_score"])
    watch_max = D(ips["watch_trigger_score_max"])
    remediation_max = D(ips["remediation_trigger_score_max"])
    cure_margin = D(ips["cure_margin_points"])
    grace = ips["watch_grace_quarters"]
    breach = (score <= watch_max
              or D(card["style_drift_r2"]) < D(ips["style_drift_r2_floor"])
              or (card["manager_change_flag"] and score <= watch_max + cure_margin))
    breaches_next = fund["consecutive_breach_quarters"] + 1
    if breach and score <= remediation_max and breaches_next >= grace:
        return "TERMINATE"
    if breach and score <= remediation_max:
        return "REMEDIATION"
    if breach and fund["watch_status"] in ("WATCH", "REMEDIATION") \
            and breaches_next >= grace:
        return "REMEDIATION"
    if breach:
        return "WATCH"
    if fund["watch_status"] in ("WATCH", "REMEDIATION", "TERMINATION_PENDING") \
            and score > watch_max + cure_margin:
        return "NONE"
    return "NONE"


def clears_cure_margin(card, ips):
    """PRD 3.6: the cure needs a `composite_score` "strictly greater than
    `watch_trigger_score_max` plus `cure_margin_points`" -- "exactly 50.00 does
    not cure a watched fund while 50.01 does".  The ladder's sixth arm also
    answers `NONE`, but that one is "`NONE` with no change", so finalization has
    to re-read the score rather than trust the recommendation alone."""
    return (D(card["composite_score"])
            > D(ips["watch_trigger_score_max"]) + D(ips["cure_margin_points"]))


# --------------------------------------------------------------------------- #
# Glidepath fit
# --------------------------------------------------------------------------- #

def glidepath_fit(fund):
    if not fund.get("is_target_date_suite"):
        return None
    if fund["glidepath_type"] == "TO_RETIREMENT":
        target_equity, target_age = D("35.0"), D(65)
    else:
        target_equity, target_age = D("50.0"), D(80)
    allowance = D(45) if fund["construction"] == "CUSTOM" else D(30)
    equity_gap = abs(D(fund["equity_at_65_pct"]) - target_equity)
    landing_gap = abs(D(fund["landing_point_age"]) - target_age)
    over = D(fund["net_expense_ratio_bps"]) - allowance
    if over < 0:
        over = D(0)
    cost_penalty = over * D("0.5")
    raw = D("100.00") - equity_gap * D("1.5") - landing_gap * D(2) - cost_penalty
    rounded = r2(raw)
    if rounded < D("0.00"):
        rounded = D("0.00")
    return rounded


def refresh_glidepath(fund):
    fund["glidepath_fit_score"] = glidepath_fit(fund)


def target_date_pool(plan_id, glidepath_type, ips):
    """Eligible QDIA candidate pool, already ranked by the declared four keys."""
    pool = []
    for fund in plan_funds(plan_id):
        if not fund.get("is_target_date_suite"):
            continue
        if fund["menu_status"] != "CANDIDATE":
            continue
        if fund.get("glidepath_type") != glidepath_type:
            continue
        if ips_eligible(fund, ips) is not None:
            continue
        if fund["track_record_quarters"] < 12:
            continue
        pool.append(fund)
    pool.sort(key=lambda f: (-(D(f["glidepath_fit_score"] or 0)),
                             f["net_expense_ratio_bps"],
                             -f["track_record_quarters"],
                             f["ticker"]))
    return pool


# --------------------------------------------------------------------------- #
# Quorum and tally
# --------------------------------------------------------------------------- #

def quorum_evaluation(plan, attendee_ids):
    eligible = 0
    for seat in plan_seats(plan["id"]):
        if seat["status"] != "FILLED" or not seat.get("voting"):
            continue
        for member in store.members.values():
            if member["seat_id"] != seat["id"]:
                continue
            if member["status"] == "ACTIVE" and \
                    member["fiduciary_training_status"] == "CURRENT":
                eligible += 1
                break
    attending = 0
    for member_id in attendee_ids:
        member = store.members.get(member_id)
        if member is None:
            continue
        seat = store.seats.get(member["seat_id"])
        if seat is None or not seat.get("voting"):
            continue
        if member["status"] == "ACTIVE" and \
                member["fiduciary_training_status"] == "CURRENT":
            attending += 1
    quorum_met = (attending >= plan["quorum_min_voting_members"]
                  and attending * 2 > eligible)
    return eligible, attending, quorum_met


def recount_votes(motion):
    counts = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0, "RECUSE": 0}
    for entry in motion["votes"]:
        counts[entry["vote"]] = counts.get(entry["vote"], 0) + 1
    motion["for_count"] = counts["FOR"]
    motion["against_count"] = counts["AGAINST"]
    motion["abstain_count"] = counts["ABSTAIN"]
    motion["recuse_count"] = counts["RECUSE"]


def motion_tally(motion):
    if motion["tally_basis"] == "VOTES_CAST":
        denominator = (motion["for_count"] + motion["against_count"]
                       + motion["abstain_count"])
    else:
        denominator = motion["eligible_voter_count"] - motion["recuse_count"]
    if denominator <= 0:
        fail("ERR_NO_ELIGIBLE_VOTERS", "the tally denominator is zero")
    return r4(D(motion["for_count"]) * D(100) / D(denominator))


# --------------------------------------------------------------------------- #
# Notice lead days
# --------------------------------------------------------------------------- #

def notice_lead_days(plan, proposal, slot):
    lead = plan["notice_lead_days_required"]
    if proposal["mapping_strategy"] == "REENROLLMENT":
        lead += 30
    if slot["designation"] == "QDIA" and plan["erisa_covered"]:
        lead += 30
    if proposal["mapping_strategy"] == "MAP_TO_QDIA" and slot["designation"] != "QDIA":
        lead += 15
    return lead


# --------------------------------------------------------------------------- #
# Provider cost
# --------------------------------------------------------------------------- #

def provider_cost(engagement, plan):
    if plan["total_plan_assets_cents"] == 0:
        fail("ERR_NO_PLAN_ASSETS", "the plan holds no assets")
    head_cost_cents = D(engagement["per_head_fee_cents"]) * \
        D(plan["participant_account_count"])
    head_cost_bps = r2(head_cost_cents * D(10000) / D(plan["total_plan_assets_cents"]))
    gross = r2(D(engagement["asset_based_bps"]) + head_cost_bps)
    if gross <= D("25.00"):
        tier, offset = "TIER_A", D("0.00")
    elif gross <= D("45.00"):
        tier, offset = "TIER_B", D("5.00")
    else:
        tier, offset = "TIER_C", D("12.00")
    if plan["revenue_credit_balance_cents"] <= 0:
        offset = D("0.00")
    total = r2(gross - offset)
    if total < D("0.00"):
        total = D("0.00")
    percentile = engagement.get("benchmark_percentile")
    last_rfp = engagement.get("last_rfp_quarter_index")
    rfp_required = False
    if percentile is not None and D(percentile) >= D("75.00"):
        rfp_required = True
    if last_rfp is None:
        rfp_required = True
    elif plan["fiscal_quarter_index"] - last_rfp >= 20:
        rfp_required = True
    if total > D("60.00"):
        rfp_required = True
    return gross, tier, total, rfp_required


# --------------------------------------------------------------------------- #
# Levelization allocation
# --------------------------------------------------------------------------- #

def pool_order(funds):
    return sorted(funds, key=lambda f: (-f["plan_assets_cents"], f["created_at"],
                                        f["_seq"]))


def waterfall_order(funds):
    return sorted(funds, key=lambda f: (-f["plan_assets_cents"], f["created_at"],
                                        f["ticker"], f["_seq"]))


def fund_accrual(fund):
    return dfloor(D(fund["plan_assets_cents"]) * D(fund["revenue_share_bps"]) / D(10000))


def compute_allocation(run, plan):
    """Three-pass allocation. Mutates the run's allocation fields."""
    funds = []
    for fund_id in run["pool_fund_ids"]:
        fund = store.funds.get(fund_id)
        if fund is not None:
            funds.append(fund)
    ordered = pool_order(funds)
    accruals = {}
    total_accrual = 0
    for fund in ordered:
        value = fund_accrual(fund)
        accruals[fund["id"]] = value
        total_accrual += value

    eligible = min(run["credit_pool_cents"], total_accrual)
    if eligible < 0:
        eligible = 0

    lines = []
    if run["method"] == "PER_CAPITA":
        accounts = plan["participant_account_count"]
        if accounts <= 0:
            fail("ERR_NO_PARTICIPANT_ACCOUNTS", "the plan has no participant accounts")
        per_account = dfloor(D(eligible) / D(accounts))
        allocated_total = per_account * accounts
        remainder = eligible - allocated_total
        line_sum = 0
        for fund in ordered:
            if total_accrual > 0:
                amount = dfloor(D(allocated_total) * D(accruals[fund["id"]])
                                / D(total_accrual))
            else:
                amount = 0
            line_sum += amount
            lines.append({"fund_id": fund["id"],
                          "basis_cents": accruals[fund["id"]],
                          "allocated_cents": amount})
        remainder += allocated_total - line_sum
        allocated_total = line_sum
        run["per_account_cents"] = per_account
        run["allocated_total_cents"] = allocated_total
        run["remainder_cents"] = remainder
    else:
        total_assets = plan["total_plan_assets_cents"]
        amounts = {}
        assigned = 0
        for fund in ordered:
            if total_assets > 0:
                raw = D(eligible) * D(fund["plan_assets_cents"]) / D(total_assets)
                amount = dfloor(raw)
            else:
                amount = 0
            amounts[fund["id"]] = amount
            assigned += amount
        leftover = eligible - assigned
        wf = waterfall_order(funds)
        if wf and leftover > 0:
            index = 0
            while leftover > 0:
                fund = wf[index % len(wf)]
                amounts[fund["id"]] += 1
                leftover -= 1
                index += 1
        for fund in ordered:
            lines.append({"fund_id": fund["id"],
                          "basis_cents": fund["plan_assets_cents"],
                          "allocated_cents": amounts[fund["id"]]})
        run["per_account_cents"] = None
        run["allocated_total_cents"] = sum(l["allocated_cents"] for l in lines)
        run["remainder_cents"] = eligible - run["allocated_total_cents"]

    run["allocation_lines"] = lines
    run["_eligible_pool_cents"] = eligible
    if run["allocated_total_cents"] + run["remainder_cents"] != eligible:
        fail("ERR_ALLOCATION_NOT_BALANCED", "allocation does not balance")
    for line in lines:
        if line["allocated_cents"] < 0:
            fail("ERR_ALLOCATION_NOT_BALANCED", "a line amount is negative")
    return run


def accrue_fund_credit(plan, funds):
    """Raise each fund's generated revenue credit to its current accrual."""
    for fund in funds:
        target = fund_accrual(fund)
        generated = fund["accrued_revenue_credit_cents"] + fund["levelized_credit_cents"]
        if target > generated:
            fund["accrued_revenue_credit_cents"] += target - generated
            touch(fund)
    recompute_ledger(plan)


# --------------------------------------------------------------------------- #
# Motion gate helpers
# --------------------------------------------------------------------------- #

def require_carried_motion(motion_id, subject_type, subject_id):
    motion = store.motions.get(motion_id)
    if motion is None:
        fail("ERR_RESOURCE_NOT_FOUND", "approving_motion_id does not resolve")
    if motion["subject_type"] != subject_type or motion["subject_id"] != subject_id:
        fail("ERR_MOTION_NOT_CARRIED", "the motion's subject does not match")
    if motion["status"] != "CARRIED":
        fail("ERR_MOTION_NOT_CARRIED", "the referenced motion is not CARRIED")
    return motion


def require_minutes_approved(motion):
    meeting = store.meetings.get(motion["meeting_id"])
    if meeting is None or meeting["status"] != "MINUTES_APPROVED":
        fail("ERR_MINUTES_NOT_APPROVED", "the meeting minutes are not approved")
    return meeting


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #

def date_in_term(member):
    start = parse_date(member["term_start_date"], "term_start_date")
    end = parse_date(member["term_end_date"], "term_end_date")
    today = clock.date()
    return start <= today <= end


def intervals_overlap_or_adjacent(a_start, a_end, b_start, b_end):
    """True when the closed intervals intersect or merely abut."""
    if a_start > b_end:
        return (a_start - b_end).days <= 1
    if b_start > a_end:
        return (b_start - a_end).days <= 1
    return True


def intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end
