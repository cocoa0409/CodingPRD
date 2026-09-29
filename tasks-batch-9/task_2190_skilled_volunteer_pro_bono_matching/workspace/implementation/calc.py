"""The ten declared calculations plus the three conservation ledgers.

Every conserved figure (cycle slots, window hours, lifetime valued dollars) is
derived here from the rows that own it rather than incremented in place, so the
invariants of PRD 2.8, 2.9 and 2.10 hold by construction.
"""
from decimal import Decimal, ROUND_HALF_UP

import config as C
import store as S


# --------------------------------------------------------------------------- #
# numeric helpers -- round-half-up everywhere, never float
# --------------------------------------------------------------------------- #
def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rnd(value, places):
    if value is None:
        return None
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


ZERO2 = Decimal("0.00")


# --------------------------------------------------------------------------- #
# 1. partner_capacity_class
# --------------------------------------------------------------------------- #
def partner_capacity(annual_budget_usd):
    budget = dec(annual_budget_usd) or ZERO2
    for upper, cls, ceiling in C.CAPACITY_TIERS:
        if upper is None or budget < upper:
            return cls, ceiling
    return "LARGE", 6


# --------------------------------------------------------------------------- #
# 9. cycle_posture -- the cycle slot ledger
# --------------------------------------------------------------------------- #
def cycle_engagements(cycle_id):
    return [e for e in S.all_rows("engagements") if e["cycle_id"] == cycle_id]


def cycle_metrics(cycle):
    total = int(cycle["capacity_slot_total"])
    committed = 0
    for eng in cycle_engagements(cycle["id"]):
        if eng["work_status"] in C.LIVE_WORK_STATUSES:
            committed += 1
    reserved = 0
    for offer in S.all_rows("match_offers"):
        if offer["status"] != "OFFERED":
            continue
        req = S.get("project_requests", offer["project_request_id"])
        if req is not None and req["cycle_id"] == cycle["id"]:
            reserved += 1
    available = max(0, total - committed - reserved)
    utilization = rnd(Decimal(committed + reserved) / Decimal(total), 4)
    if utilization >= C.POSTURE_FROZEN_AT:
        posture = "FROZEN"
    elif utilization >= C.POSTURE_RESTRICTED_AT:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return {
        "slots_committed": committed,
        "slots_reserved": reserved,
        "slots_available": available,
        "utilization_ratio": utilization,
        "posture": posture,
    }


def cycle_posture(cycle):
    return cycle_metrics(cycle)["posture"]


# --------------------------------------------------------------------------- #
# volunteer hour custody -- the availability window ledger
# --------------------------------------------------------------------------- #
def window_metrics(window):
    offered = dec(window["hours_offered"])
    committed = ZERO2
    for offer in S.all_rows("match_offers"):
        if offer["status"] == "OFFERED" and offer["availability_window_id"] == window["id"]:
            committed += dec(offer["reserved_hours"])
    for eng in S.all_rows("engagements"):
        if (
            eng["availability_window_id"] == window["id"]
            and eng["work_status"] in C.LIVE_WORK_STATUSES
        ):
            committed += dec(eng["committed_hours"])
    committed = rnd(committed, 2)
    remaining = rnd(offered - committed, 2)
    if S.now() >= window["ends_at"]:
        status = "EXPIRED"
    elif remaining <= 0:
        status = "EXHAUSTED"
    else:
        status = "OPEN"
    return {
        "hours_committed": committed,
        "hours_remaining": remaining,
        "status": status,
    }


def window_remaining(window):
    return window_metrics(window)["hours_remaining"]


def window_approved_hours(window):
    """Hours already approved against a window, across its engagements."""
    total = ZERO2
    eng_ids = {
        e["id"]
        for e in S.all_rows("engagements")
        if e["availability_window_id"] == window["id"]
    }
    for log in S.all_rows("time_logs"):
        if log["engagement_id"] in eng_ids and log["approved"]:
            total += dec(log["hours"])
    return rnd(total, 2)


# --------------------------------------------------------------------------- #
# 2. match_score
# --------------------------------------------------------------------------- #
def required_hours(scope):
    return rnd(dec(scope["estimated_hours"]) * dec(scope["complexity_factor"]), 2)


def eligible_windows(volunteer_id):
    clock = S.now()
    out = []
    for w in S.where("availability_windows", volunteer_id=volunteer_id):
        if not (w["starts_at"] <= clock < w["ends_at"]):
            continue
        if window_remaining(w) <= 0:
            continue
        out.append(w)
    return out


def select_window(volunteer_id):
    """Remaining hours DESC, HARD before SOFT, created_at ASC. Never by id."""
    windows = eligible_windows(volunteer_id)
    if not windows:
        return None
    windows.sort(
        key=lambda w: (
            -window_remaining(w),
            0 if w["window_kind"] == "HARD" else 1,
            w["created_at"],
            w["_seq"],
        )
    )
    return windows[0]


def score_candidate(request, scope, volunteer, claim, window):
    req_hours = required_hours(scope)
    tier = C.SKILL_TIER_WEIGHT[int(claim["proficiency"])]
    bonus = C.VERIFIED_SKILL_BONUS if claim.get("verified") else Decimal("0")
    skill_component = min(Decimal("1.00"), tier + bonus)

    remaining = window_remaining(window)
    availability_component = min(Decimal("1.00"), rnd(remaining / req_hours, 4))

    shortfall = max(ZERO2, rnd(req_hours - remaining, 2))
    penalty = min(
        C.SHORTFALL_PENALTY_CAP, rnd(shortfall * C.SHORTFALL_PENALTY_PER_HOUR, 4)
    )

    w_avail = C.URGENCY_AVAILABILITY_WEIGHT[request["urgency"]]
    w_skill = rnd(Decimal("1.00") - w_avail - C.RELIABILITY_WEIGHT, 4)
    reliability = reliability_score(volunteer["id"])
    raw = rnd(
        w_skill * skill_component
        + w_avail * availability_component
        + C.RELIABILITY_WEIGHT * reliability,
        6,
    )
    floored = max(Decimal("0.0000"), raw - penalty)
    return rnd(floored * C.SENIORITY_MULTIPLIER[volunteer["seniority"]], 4)


def match_candidates(request, scope):
    """The eligible, scored and ranked candidate pool for one matching round."""
    excluded = set()
    for offer in S.where("match_offers", project_request_id=request["id"]):
        if offer["status"] in ("OFFERED", "DECLINED", "EXPIRED", "WITHDRAWN"):
            excluded.add(offer["volunteer_id"])

    candidates = []
    for volunteer in S.all_rows("volunteers"):
        if volunteer["id"] in excluded:
            continue
        if volunteer["status"] != "ACTIVE":
            continue
        if volunteer["credential_verified_at"] is None:
            continue
        if volunteer_open_engagements(volunteer["id"]) >= C.VOLUNTEER_MAX_CONCURRENT:
            continue
        claims = [
            c
            for c in S.where("skill_profiles", volunteer_id=volunteer["id"])
            if c["skill_code"] == request["required_skill_code"]
            and int(c["proficiency"]) >= int(request["min_proficiency"])
        ]
        if not claims:
            continue
        window = select_window(volunteer["id"])
        if window is None:
            continue
        # one pair per volunteer: the best-scoring surviving claim
        best = None
        for claim in claims:
            score = score_candidate(request, scope, volunteer, claim, window)
            if best is None or score > best[0]:
                best = (score, claim)
        candidates.append(
            {
                "volunteer": volunteer,
                "skill_profile": best[1],
                "window": window,
                "score": best[0],
            }
        )

    candidates.sort(
        key=lambda c: (
            -c["score"],
            -reliability_score(c["volunteer"]["id"]),
            c["volunteer"]["created_at"],
            c["volunteer"]["_seq"],
        )
    )
    return candidates


# --------------------------------------------------------------------------- #
# engagement counters
# --------------------------------------------------------------------------- #
def volunteer_open_engagements(volunteer_id):
    """PRD 3.2: the volunteer's open count covers NOT_STARTED, IN_PROGRESS and
    SUBMITTED -- deliberately narrower than the partner's four live values."""
    return sum(
        1
        for e in S.all_rows("engagements")
        if e["volunteer_id"] == volunteer_id
        and e["work_status"] in ("NOT_STARTED", "IN_PROGRESS", "SUBMITTED")
    )


def volunteer_terminal_engagements(volunteer_id):
    return [
        e
        for e in S.all_rows("engagements")
        if e["volunteer_id"] == volunteer_id
        and e["work_status"] in ("HANDED_OFF", "TERMINATED")
    ]


def partner_open_engagements(partner_org_id):
    count = 0
    for eng in S.all_rows("engagements"):
        if eng["work_status"] not in C.LIVE_WORK_STATUSES:
            continue
        req = S.get("project_requests", eng["project_request_id"])
        if req is not None and req["partner_org_id"] == partner_org_id:
            count += 1
    return count


def engagement_missed_checkins(engagement_id):
    return sum(
        1
        for m in S.where("milestones", engagement_id=engagement_id)
        if m["checkin_status"] == "MISSED"
    )


# --------------------------------------------------------------------------- #
# 7. scope_creep_pct
# --------------------------------------------------------------------------- #
def approved_hours(engagement):
    total = ZERO2
    for log in S.where("time_logs", engagement_id=engagement["id"]):
        if log["approved"]:
            total += dec(log["hours"])
    return rnd(total, 2)


def pending_change_hours(engagement, exclude_id=None):
    total = ZERO2
    for scr in S.where("scope_change_requests", engagement_id=engagement["id"]):
        if scr["id"] == exclude_id:
            continue
        if scr["status"] in ("PENDING", "ESCALATED"):
            total += dec(scr["additional_hours"])
    return rnd(total, 2)


def creep_level(pct):
    if pct >= C.CREEP_BREACH:
        return "BREACH"
    if pct >= C.CREEP_ESCALATED:
        return "ESCALATED"
    if pct >= C.CREEP_WATCH:
        return "WATCH"
    return "NONE"


def creep(engagement):
    baseline = dec(engagement["committed_hours"])
    approved = approved_hours(engagement)
    pending = pending_change_hours(engagement)
    pct = rnd((approved + pending - baseline) / baseline, 4)
    return pct, creep_level(pct)


# --------------------------------------------------------------------------- #
# 8. scope_change_projection
# --------------------------------------------------------------------------- #
def projection(engagement, additional_hours, exclude_id=None):
    baseline = dec(engagement["committed_hours"])
    approved = approved_hours(engagement)
    others = pending_change_hours(engagement, exclude_id=exclude_id)
    return rnd(
        (approved + others + dec(additional_hours) - baseline) / baseline, 4
    )


def decision_tier(projected_pct, additional_deliverable_count):
    if projected_pct >= C.CREEP_BREACH:
        return "RESCOPE_REQUIRED"
    if projected_pct < C.CREEP_WATCH and int(additional_deliverable_count) == 0:
        return "AUTO_APPROVABLE"
    return "MANAGER_REVIEW"


# --------------------------------------------------------------------------- #
# 5. volunteer_reliability_score (two variants)
# --------------------------------------------------------------------------- #
def _terminal_at(engagement):
    return engagement["handoff_at"] or engagement["terminated_at"] or engagement["created_at"]


def _base_points(engagement):
    work = engagement["work_status"]
    gate = engagement["quality_gate"]
    reason = engagement["termination_reason"]
    if work == "HANDED_OFF" and gate == "PASSED":
        return Decimal("1.00")
    if work == "HANDED_OFF" and gate == "CONDITIONAL":
        return Decimal("0.70")
    if work == "TERMINATED" and reason == "QUALITY_FAILURE":
        return Decimal("0.00")
    if work == "TERMINATED" and reason in ("SCOPE_BREACH", "ADMIN"):
        return Decimal("0.25")
    if work == "TERMINATED" and reason in ("AGREEMENT_VOIDED", "PARTNER_SUSPENDED"):
        return Decimal("0.60")
    return Decimal("0.00")


def _points(engagement):
    missed = engagement_missed_checkins(engagement["id"])
    return max(
        ZERO2,
        rnd(_base_points(engagement) - C.MISSED_CHECKIN_PENALTY * missed, 4),
    )


def reliability_score(volunteer_id):
    """The decay-weighted gating figure, always derived from live rows."""
    return reliability(volunteer_id)[0]


def reliability(volunteer_id):
    terminal = volunteer_terminal_engagements(volunteer_id)
    if not terminal:
        return C.RELIABILITY_BASELINE, C.RELIABILITY_BASELINE
    terminal.sort(key=lambda e: (_terminal_at(e), e["_seq"]), reverse=True)
    recent = terminal[: min(C.DECAY_WINDOW_N, len(terminal))]
    weighted = Decimal("0")
    weight_sum = Decimal("0")
    for i, eng in enumerate(recent):
        w = rnd(C.DECAY_LAMBDA ** i, 6)
        weighted += w * _points(eng)
        weight_sum += w
    decay = rnd(weighted / weight_sum, 4)
    lifetime = rnd(
        sum((_points(e) for e in terminal), Decimal("0")) / Decimal(len(terminal)), 4
    )
    return decay, lifetime


# --------------------------------------------------------------------------- #
# 6. deliverable_quality_score
# --------------------------------------------------------------------------- #
def active_deliverables(scope_definition_id):
    rows = [
        d
        for d in S.where("deliverables", scope_definition_id=scope_definition_id)
        if d["review_status"] != "WAIVED"
    ]
    rows.sort(key=lambda d: (int(d["sequence_no"]), d["created_at"], d["_seq"]))
    return rows


def quality_score(scope_definition_id):
    active = active_deliverables(scope_definition_id)
    active_total = rnd(
        sum((dec(d["weight_pct"]) for d in active), Decimal("0")), 2
    )
    total = Decimal("0")
    for d in active:
        norm = rnd(dec(d["weight_pct"]) / active_total, 6)
        total += rnd(norm * dec(d["review_score"]) * C.SCORE_SCALE, 2)
    score = rnd(total, 2)
    if score >= C.PASS_THRESHOLD:
        outcome = "PASS"
    elif score >= C.CONDITIONAL_THRESHOLD:
        outcome = "CONDITIONAL"
    else:
        outcome = "FAIL"
    return score, outcome


def deliverable_weight_total(scope_definition_id):
    active = active_deliverables(scope_definition_id)
    return rnd(sum((dec(d["weight_pct"]) for d in active), Decimal("0")), 2)


# --------------------------------------------------------------------------- #
# 3 + 4. volunteer_hour_valuation and engagement_admin_overhead
# --------------------------------------------------------------------------- #
def approved_logs(engagement_id):
    rows = [
        l
        for l in S.where("time_logs", engagement_id=engagement_id)
        if l["approved"]
    ]
    rows.sort(key=lambda l: (l["work_date"], l["created_at"], l["_seq"]))
    return rows


def valuation_amounts(engagement, volunteer, method):
    ceiling = C.MARKET_RATE_CAP_USD[volunteer["seniority"]]
    logs = approved_logs(engagement["id"])
    if method == "MARKET_RATE":
        admitted = [l for l in logs if l["activity_class"] in ("DELIVERY", "ADMIN")]
        base = Decimal("0")
        hours_included = Decimal("0")
        for log in admitted:
            rate = min(dec(log["rate_basis_usd"]), ceiling)
            factor = C.CLASS_FACTOR[log["activity_class"]]
            base += rnd(dec(log["hours"]) * rate * factor, 2)
            hours_included += dec(log["hours"])
        base_amount = rnd(base, 2)
        hours_included = rnd(hours_included, 2)
        rate_applied = min(
            dec(volunteer["professional_rate_usd_per_hour"]), ceiling
        )
    else:
        hours_included = rnd(
            sum((dec(l["hours"]) for l in logs), Decimal("0")), 2
        )
        rate_applied = C.INDEPENDENT_SECTOR_RATE_USD
        base_amount = rnd(hours_included * rate_applied, 2)

    overhead_rate = None
    for upper, rate in C.OVERHEAD_TIERS:
        if upper is None or base_amount < upper:
            overhead_rate = rate
            break
    overhead = max(C.ADMIN_OVERHEAD_MIN_USD, rnd(base_amount * overhead_rate, 2))
    total = rnd(base_amount + overhead, 2)
    return {
        "hours_included": hours_included,
        "rate_applied_usd": rnd(rate_applied, 2),
        "base_amount_usd": base_amount,
        "admin_overhead_usd": rnd(overhead, 2),
        "total_amount_usd": total,
    }


def lifetime_valued_usd(volunteer_id):
    """Conserved: the sum over non-superseded INDEPENDENT_SECTOR records."""
    eng_ids = {
        e["id"]
        for e in S.all_rows("engagements")
        if e["volunteer_id"] == volunteer_id
    }
    total = Decimal("0")
    for rec in S.all_rows("valuation_records"):
        if rec["engagement_id"] not in eng_ids:
            continue
        if rec["method"] != "INDEPENDENT_SECTOR":
            continue
        if rec["superseded_at"] is not None:
            continue
        total += dec(rec["total_amount_usd"])
    return rnd(total, 2)


# --------------------------------------------------------------------------- #
# 10. partner_satisfaction_index
# --------------------------------------------------------------------------- #
def satisfaction_composite(expertise, responsiveness, deliverable_fit):
    weighted = (
        C.SATISFACTION_WEIGHTS["expertise"] * dec(expertise)
        + C.SATISFACTION_WEIGHTS["deliverable_fit"] * dec(deliverable_fit)
        + C.SATISFACTION_WEIGHTS["responsiveness"] * dec(responsiveness)
    )
    return rnd(weighted * Decimal("20"), 2)


def satisfaction_pool(partner_org_id):
    """Surveys whose engagement reached HANDED_OFF, newest first."""
    pool = []
    for survey in S.where("satisfaction_surveys", partner_org_id=partner_org_id):
        eng = S.get("engagements", survey["engagement_id"])
        if eng is not None and eng["work_status"] == "HANDED_OFF":
            pool.append(survey)
    pool.sort(key=lambda s: (s["submitted_at"], s["created_at"], s["_seq"]), reverse=True)
    return pool


def satisfaction_index(used):
    if not used:
        return None
    weights = list(C.RECENCY_WEIGHTS[: len(used)])
    weight_sum = rnd(sum(weights, Decimal("0")), 4)
    total = Decimal("0")
    for weight, survey in zip(weights, used):
        norm = rnd(weight / weight_sum, 6)
        total += rnd(norm * dec(survey["composite_score"]), 4)
    return rnd(total, 2)
