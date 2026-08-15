"""Business logic core: computed fields, campaign settlement, state-machine
cascades, the operations sweep, withholding, risk scoring, bonus quote."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext

from flask import g, has_request_context

from db import store
from util import (floor_days, year_bounds, add_calendar_months,
                  round_half_up_cents, dec_pow_half)

# ---------------------------------------------------------------------------
# State vocabularies
# ---------------------------------------------------------------------------

REFERRAL_TERMINAL = {
    "COMPLETED", "REJECTED_DUPLICATE", "REJECTED_PRIOR_CANDIDATE",
    "REJECTED_OTHER", "NOT_SELECTED", "WITHDRAWN", "EXPIRED", "FORFEITED",
    "RETENTION_FAILED",
}
# Pre-hire pipeline states: the only states from which NOT_SELECTED / EXPIRED
# style cascades act.
REFERRAL_PRE_HIRE = {
    "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "QUALIFIED", "SCREENING",
    "INTERVIEWING", "OFFER_EXTENDED",
}
MILESTONE_TERMINAL = {"PAID", "FORFEITED", "CLAWED_BACK"}
BATCH_TERMINAL = {"CONFIRMED_PAID", "CANCELLED"}
CAMPAIGN_TERMINAL = {"ENDED", "CANCELLED"}
POLICY_TERMINAL = {"SUPERSEDED", "RETIRED"}
REQUISITION_TERMINAL = {"FILLED", "CANCELLED"}
ABUSE_TERMINAL = {"CONFIRMED", "DISMISSED"}

JOB_LEVELS = ("IC", "SENIOR", "MANAGER", "DIRECTOR", "EXECUTIVE")
CASE_TYPES = ("SELF_REFERRAL", "VELOCITY", "DUPLICATE_RING", "RESUME_FARM", "MANUAL")
FILING_STATUSES = ("SINGLE", "MARRIED", "HEAD_OF_HOUSEHOLD")
WITHHOLDING_METHODS = ("FLAT", "AGGREGATE")
ADVANCE_TARGETS = ("SCREENING", "INTERVIEWING", "OFFER_EXTENDED")
REJECT_REASONS = ("DUPLICATE", "PRIOR_CANDIDATE", "OTHER")
GROUP_BY_DIMS = ("REFERRER_LEVEL", "REQ_DEPARTMENT", "CAMPAIGN")

RISK_WEIGHTS = {
    "SELF_REFERRAL": 40,
    "VELOCITY": 25,
    "DUPLICATE_RING": 35,
    "RESUME_FARM": 50,
    "MANUAL": 20,
}
SUSPEND_THRESHOLD = 100
SCORE_CAP = 500
HALFLIFE_DAYS = 180

TIER_FIELD = {
    "IC": "tier_ic_cents",
    "SENIOR": "tier_senior_cents",
    "MANAGER": "tier_manager_cents",
    "DIRECTOR": "tier_director_cents",
    "EXECUTIVE": "tier_executive_cents",
}

FLAT_RATE_BPS = 2200
BRACKET_1_LIMIT = 500000
BRACKET_2_LIMIT = 1500000

POLICY_DEFAULTS = {
    "min_tenure_days": 90,
    "duplicate_cooldown_months": 6,
    "referral_expiry_days": 45,
    "hire_pct": 30,
    "retention_days": 180,
    "clawback_days": 90,
    "annual_cap_cents": 2000000,
    "velocity_limit": 5,
    "tier_ic_cents": 150000,
    "tier_senior_cents": 300000,
    "tier_manager_cents": 500000,
    "tier_director_cents": 650000,
    "tier_executive_cents": 800000,
}


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity(collection, fields):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    e["created_at"] = store.clock
    e["updated_at"] = store.clock
    e["version"] = 1
    e["_seq"] = store.next_seq()
    collection[e["id"]] = e
    return e


def touch(e):
    """Record a mutation: version +1 (at most once per entity per request)
    and updated_at refreshed from the logical clock."""
    bumped = False
    if has_request_context():
        dirty = g.setdefault("dirty", set())
        if id(e) in dirty:
            bumped = True
        else:
            dirty.add(id(e))
    if not bumped:
        e["version"] += 1
    e["updated_at"] = store.clock


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def milestones_of(referral_id):
    return sort_by_created(
        [m for m in store.milestones.values() if m["referral_id"] == referral_id])


def active_policy():
    for p in store.policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------

def tenure_days(emp):
    return max(0, floor_days(store.clock - emp["hire_date"]))


def ytd_paid_gross(employee_id):
    """Sum of amount_cents of the employee's milestones that reached PAID in
    the current calendar year (paid_at stamped at confirm-paid)."""
    now = store.clock
    start, end = year_bounds(now)
    total = 0
    for m in store.milestones.values():
        r = store.referrals.get(m["referral_id"])
        if r is None or r["referrer_id"] != employee_id:
            continue
        paid_at = m.get("_paid_at")
        if paid_at is not None and start <= paid_at < end:
            total += m["amount_cents"]
    return total


def annual_accumulators(employee_id):
    """(annual_provisional_cents, annual_committed_cents) per PRD 3.5."""
    now = store.clock
    start, end = year_bounds(now)
    provisional = 0
    committed = 0
    for m in store.milestones.values():
        r = store.referrals.get(m["referral_id"])
        if r is None or r["referrer_id"] != employee_id:
            continue
        earned_at = m["earned_at"]
        if earned_at is None or not (start <= earned_at < end):
            continue
        st = m["status"]
        if st in ("EARNED", "APPROVED", "BATCHED", "PAID"):
            provisional += m["amount_cents"]
        if st in ("APPROVED", "BATCHED", "PAID"):
            committed += m["amount_cents"]
        if st == "CLAWED_BACK":
            provisional -= m["amount_cents"]
            committed -= m["amount_cents"]
    return provisional, committed


def risk_score(employee_id):
    """Decayed weighted sum of CONFIRMED abuse cases (PRD 3.7)."""
    now = store.clock
    total = Decimal(0)
    for c in store.abuse_cases.values():
        if c["employee_id"] != employee_id or c["status"] != "CONFIRMED":
            continue
        if c["confirmed_at"] is None:
            continue
        days = floor_days(now - c["confirmed_at"])
        exponent = Decimal(days) / Decimal(HALFLIFE_DAYS)
        total += Decimal(c["risk_weight"]) * dec_pow_half(exponent)
    with localcontext() as ctx:
        ctx.prec = 40
        rounded = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(SCORE_CAP, rounded)


def candidate_cooldown_until(candidate):
    """last_terminal_outcome_at + duplicate_cooldown_months (calendar months,
    day clamped); null when last_terminal_outcome_at is null. Months come from
    the currently ACTIVE policy, else the documented default (6)."""
    lto = candidate["last_terminal_outcome_at"]
    if lto is None:
        return None
    policy = active_policy()
    months = policy["duplicate_cooldown_months"] if policy else POLICY_DEFAULTS["duplicate_cooldown_months"]
    return add_calendar_months(lto, months)


def campaign_remaining(campaign):
    return campaign["budget_cents"] - campaign["reserved_cents"] - campaign["spent_cents"]


def campaign_payouts_count(campaign):
    return sum(1 for r in store.referrals.values()
               if r["campaign_id"] == campaign["id"] and r["status"] not in REFERRAL_TERMINAL)


def open_referral_count(requisition):
    return sum(1 for r in store.referrals.values()
               if r["job_requisition_id"] == requisition["id"] and r["status"] not in REFERRAL_TERMINAL)


def batch_totals(batch):
    attached = [m for m in store.milestones.values() if m["payroll_batch_id"] == batch["id"]]
    gross = sum(m["amount_cents"] for m in attached if m["status"] == "BATCHED")
    gross -= sum(m["amount_cents"] for m in attached if m["status"] == "CLAWED_BACK")
    withholding = sum((m["withholding_cents"] or 0) for m in attached if m["status"] == "BATCHED")
    return {
        "total_gross_cents": gross,
        "total_withholding_cents": withholding,
        "total_net_cents": gross - withholding,
        "milestone_count": len(attached),
    }


# ---------------------------------------------------------------------------
# Referral audit trail
# ---------------------------------------------------------------------------

def append_event(referral, event_type, from_state, to_state, actor, note=None):
    e = {
        "id": str(uuid.uuid4()),
        "referral_id": referral["id"],
        "event_type": event_type,
        "from_state": from_state,
        "to_state": to_state,
        "actor_user_id": actor,
        "note": note,
        "created_at": store.clock,
        "_seq": store.next_seq(),
    }
    store.events[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Abuse cases
# ---------------------------------------------------------------------------

def create_abuse_case(employee_id, referral_id, case_type, raised_by, note=None):
    return new_entity(store.abuse_cases, {
        "employee_id": employee_id,
        "referral_id": referral_id,
        "case_type": case_type,
        "risk_weight": RISK_WEIGHTS[case_type],
        "status": "OPEN",
        "raised_by_user_id": raised_by,
        "decided_by_user_id": None,
        "confirmed_at": None,
        "resolution_note": None,
    })


def auto_velocity_check(referrer_id, new_referral, policy):
    """PRD 3.3 velocity detector: >= velocity_limit referrals in the closed
    7-day window [now - 7d, now] (new referral included) auto-raises VELOCITY."""
    now = store.clock
    start = now - timedelta(seconds=7 * 86400)
    n = sum(1 for r in store.referrals.values()
            if r["referrer_id"] == referrer_id and start <= r["submitted_at"] <= now)
    if n >= policy["velocity_limit"]:
        create_abuse_case(referrer_id, new_referral["id"], "VELOCITY", "system")


def auto_duplicate_ring_check(candidate_id, new_referral):
    """PRD 3.3 duplicate-ring detector: >= 3 distinct referrers over
    non-terminal referrals for the same candidate in [now - 90d, now]."""
    now = store.clock
    start = now - timedelta(days=90)
    referrers = {r["referrer_id"] for r in store.referrals.values()
                 if r["candidate_id"] == candidate_id
                 and r["status"] not in REFERRAL_TERMINAL
                 and start <= r["submitted_at"] <= now}
    if len(referrers) >= 3:
        create_abuse_case(new_referral["referrer_id"], new_referral["id"],
                          "DUPLICATE_RING", "system")


# ---------------------------------------------------------------------------
# Campaign settlement (PRD 3.2 / calculation campaign_settlement)
# ---------------------------------------------------------------------------

def hire_uplift_share(referral):
    policy = store.policies[referral["policy_version_id"]]
    return round_half_up_cents(referral["campaign_uplift_cents"] * policy["hire_pct"], 100)


def retention_uplift_share(referral):
    return referral["campaign_uplift_cents"] - hire_uplift_share(referral)


def maybe_exhaust(campaign):
    if campaign["status"] == "ACTIVE" and campaign["spent_cents"] == campaign["budget_cents"]:
        campaign["status"] = "EXHAUSTED"
        touch(campaign)


def maybe_unexhaust(campaign):
    if campaign["status"] == "EXHAUSTED" and campaign["spent_cents"] < campaign["budget_cents"]:
        campaign["status"] = "ACTIVE"
        touch(campaign)


def campaign_reserve(campaign, amount):
    if amount:
        campaign["reserved_cents"] += amount
        touch(campaign)


def campaign_convert(campaign, referral, share):
    """reserved -> spent at milestone earn; auto-exhausts at spent == budget."""
    share = max(0, min(share, campaign["reserved_cents"]))
    if share:
        campaign["reserved_cents"] -= share
        campaign["spent_cents"] += share
        referral["uplift_spent_cents"] += share
        touch(referral)
        touch(campaign)
        maybe_exhaust(campaign)


def campaign_release_reservation(campaign, referral):
    """Release the outstanding (not-yet-converted) uplift share from reserved."""
    outstanding = referral["campaign_uplift_cents"] - referral["uplift_spent_cents"]
    amount = max(0, min(outstanding, campaign["reserved_cents"]))
    if amount:
        campaign["reserved_cents"] -= amount
        touch(campaign)


def campaign_release_earned(campaign, referral, share):
    """Release an already-converted share from spent (forfeit / clawback);
    may flip EXHAUSTED back to ACTIVE."""
    amount = max(0, min(share, campaign["spent_cents"]))
    if amount:
        campaign["spent_cents"] -= amount
        referral["uplift_spent_cents"] = max(0, referral["uplift_spent_cents"] - amount)
        touch(referral)
        touch(campaign)
        maybe_unexhaust(campaign)


def release_referral_reservation(referral):
    if referral["campaign_id"]:
        campaign = store.campaigns.get(referral["campaign_id"])
        if campaign is not None:
            campaign_release_reservation(campaign, referral)


def end_campaign_releases(campaign):
    """Ending/ending-by-sweep: every attached non-terminal referral keeps
    campaign_id but its unpaid uplift share is released from reserved."""
    for r in store.referrals.values():
        if r["campaign_id"] == campaign["id"] and r["status"] not in REFERRAL_TERMINAL:
            campaign_release_reservation(campaign, r)


# ---------------------------------------------------------------------------
# Referral transitions and cascades
# ---------------------------------------------------------------------------

def maybe_return_candidate_to_available(candidate_id):
    """IN_PROCESS -> AVAILABLE when the candidate's last non-terminal referral
    reaches a terminal outcome; stamps last_terminal_outcome_at (cooldown
    recomputes from it)."""
    candidate = store.candidates.get(candidate_id)
    if candidate is None or candidate["global_status"] != "IN_PROCESS":
        return
    for r in store.referrals.values():
        if r["candidate_id"] == candidate_id and r["status"] not in REFERRAL_TERMINAL:
            return
    candidate["global_status"] = "AVAILABLE"
    candidate["last_terminal_outcome_at"] = store.clock
    touch(candidate)


def transition_referral_terminal(referral, to_state, event_type, actor,
                                 note=None, reason=None):
    old = referral["status"]
    referral["status"] = to_state
    if reason is not None:
        referral["last_decision_reason"] = reason
    touch(referral)
    release_referral_reservation(referral)
    append_event(referral, event_type, old, to_state, actor, note)
    maybe_return_candidate_to_available(referral["candidate_id"])


def forfeit_milestone(milestone, referral=None):
    """EARNED/APPROVED/BATCHED -> FORFEITED. BATCHED detaches from its batch
    (batch totals recompute, batch version increments). Releases the
    corresponding earned campaign share from spent."""
    if referral is None:
        referral = store.referrals[milestone["referral_id"]]
    if milestone["status"] == "BATCHED" and milestone["payroll_batch_id"]:
        batch = store.batches.get(milestone["payroll_batch_id"])
        milestone["payroll_batch_id"] = None
        if batch is not None:
            touch(batch)
    milestone["status"] = "FORFEITED"
    touch(milestone)
    if referral["campaign_id"]:
        campaign = store.campaigns.get(referral["campaign_id"])
        if campaign is not None:
            # Each milestone releases its own corresponding earned share (PRD 3.6):
            # the HIRE milestone the hire share, the RETENTION milestone the
            # retention share. The kind-share is exact; campaign_release_earned
            # clamps against the campaign's current spent as a safety net.
            if milestone["kind"] == "HIRE":
                share = hire_uplift_share(referral)
            else:
                share = retention_uplift_share(referral)
            if share > 0:
                campaign_release_earned(campaign, referral, share)


def forfeit_referral_cascade(referral, actor):
    """Abuse-confirmed FORFEIT cascade (PRD 3.7)."""
    old = referral["status"]
    referral["status"] = "FORFEITED"
    referral["last_decision_reason"] = "ABUSE_CONFIRMED"
    touch(referral)
    for m in milestones_of(referral["id"]):
        if m["status"] in ("EARNED", "APPROVED", "BATCHED"):
            forfeit_milestone(m, referral)
        elif m["status"] == "PENDING":
            m["status"] = "FORFEITED"
            touch(m)
        # PAID milestones remain PAID (recovery only via clawback)
    release_referral_reservation(referral)
    append_event(referral, "FORFEIT", old, "FORFEITED", actor)
    maybe_return_candidate_to_available(referral["candidate_id"])


def not_select_cascade(requisition, reason, actor, exclude_referral_id=None):
    """Every non-terminal pre-hire referral for the requisition -> NOT_SELECTED."""
    for r in sort_by_created(store.referrals.values()):
        if r["job_requisition_id"] != requisition["id"]:
            continue
        if r["id"] == exclude_referral_id:
            continue
        if r["status"] in REFERRAL_PRE_HIRE:
            transition_referral_terminal(r, "NOT_SELECTED", "NOT_SELECTED",
                                         actor, reason=reason)


def hire_referral(referral, hire_date, actor, note):
    """OFFER_EXTENDED -> HIRED with the full cascade (PRD 3.4)."""
    policy = store.policies[referral["policy_version_id"]]
    now = store.clock
    old = referral["status"]
    referral["hire_date"] = hire_date
    referral["retention_due_at"] = hire_date + timedelta(days=policy["retention_days"])
    referral["clawback_until"] = referral["retention_due_at"] + timedelta(days=policy["clawback_days"])
    referral["status"] = "HIRED"
    touch(referral)

    candidate = store.candidates[referral["candidate_id"]]
    candidate["global_status"] = "HIRED"
    candidate["hired_via_referral_id"] = referral["id"]
    touch(candidate)

    requisition = store.requisitions[referral["job_requisition_id"]]
    requisition["filled_count"] += 1
    if requisition["filled_count"] == requisition["openings"] and requisition["status"] == "OPEN":
        requisition["status"] = "FILLED"
        requisition["filled_by_candidate_id"] = candidate["id"]
        not_select_cascade(requisition, "REQ_FILLED", "system",
                           exclude_referral_id=referral["id"])
    touch(requisition)

    total = referral["bonus_total_cents"]
    hire_amount = round_half_up_cents(total * policy["hire_pct"], 100)
    retention_amount = total - hire_amount
    create_milestone(referral, "HIRE", hire_amount, earned=True)
    create_milestone(referral, "RETENTION", retention_amount, earned=False)

    if referral["campaign_id"]:
        campaign = store.campaigns.get(referral["campaign_id"])
        if campaign is not None:
            campaign_convert(campaign, referral, hire_uplift_share(referral))

    append_event(referral, "HIRE", old, "HIRED", actor, note)


def create_milestone(referral, kind, amount, earned):
    m = new_entity(store.milestones, {
        "referral_id": referral["id"],
        "kind": kind,
        "amount_cents": amount,
        "withholding_cents": None,
        "net_cents": None,
        "status": "EARNED" if earned else "PENDING",
        "earned_at": store.clock if earned else None,
        "payroll_batch_id": None,
        "recovery_status": None,
        "approved_by_user_id": None,
    })
    m["_paid_at"] = None
    return m


# ---------------------------------------------------------------------------
# Tax withholding (PRD 3.6)
# ---------------------------------------------------------------------------

def bracket_tax(x):
    """Progressive bracket tax on cumulative referral wages (exact Decimal)."""
    x = Decimal(x)
    if x < BRACKET_1_LIMIT:
        return x * Decimal("0.15")
    if x < BRACKET_2_LIMIT:
        return Decimal(75000) + (x - BRACKET_1_LIMIT) * Decimal("0.25")
    return Decimal(325000) + (x - BRACKET_2_LIMIT) * Decimal("0.35")


def compute_withholding(amount_cents, profile):
    """Variant selected by TaxProfile.withholding_method; base_ytd evaluated at
    the approve instant. Returns withholding_cents (integer, round-half-up)."""
    if profile["withholding_method"] == "FLAT":
        rate = profile["supplemental_rate_bps"]
        if rate is None:
            rate = FLAT_RATE_BPS
        return round_half_up_cents(amount_cents * rate, 10000)
    base_ytd = profile["ytd_carryover_cents"] + ytd_paid_gross(profile["employee_id"])
    difference = bracket_tax(base_ytd + amount_cents) - bracket_tax(base_ytd)
    with localcontext() as ctx:
        ctx.prec = 40
        return int(difference.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Operations sweep (PRD 3.5)
# ---------------------------------------------------------------------------

def run_sweep():
    now = store.clock
    tallies = {
        "retention_earned": 0,
        "retention_failed": 0,
        "clawed_back": 0,
        "expired": 0,
        "campaigns_ended": 0,
    }

    # 1. Retention outcomes for HIRED referrals.
    for r in sort_by_created(list(store.referrals.values())):
        if r["status"] != "HIRED":
            continue
        candidate = store.candidates.get(r["candidate_id"])
        departed = candidate is not None and candidate["global_status"] == "DEPARTED"
        if departed and candidate["departed_at"] < r["retention_due_at"]:
            # HIRED -> RETENTION_FAILED
            old = r["status"]
            r["status"] = "RETENTION_FAILED"
            touch(r)
            for m in milestones_of(r["id"]):
                if m["kind"] == "RETENTION" and m["status"] == "PENDING":
                    m["status"] = "FORFEITED"
                    touch(m)
            release_referral_reservation(r)
            append_event(r, "RETENTION_FAILED", old, "RETENTION_FAILED", "system")
            tallies["retention_failed"] += 1
        elif not departed and now >= r["retention_due_at"]:
            # HIRED -> COMPLETED
            old = r["status"]
            r["status"] = "COMPLETED"
            touch(r)
            for m in milestones_of(r["id"]):
                if m["kind"] == "RETENTION" and m["status"] == "PENDING":
                    m["status"] = "EARNED"
                    m["earned_at"] = now
                    touch(m)
            if r["campaign_id"]:
                campaign = store.campaigns.get(r["campaign_id"])
                if campaign is not None:
                    campaign_convert(campaign, r, retention_uplift_share(r))
            append_event(r, "RETENTION_MET", old, "COMPLETED", "system")
            tallies["retention_earned"] += 1

    # 2. Clawback of PAID retention milestones within the clawback window.
    for r in sort_by_created(list(store.referrals.values())):
        if r["clawback_until"] is None:
            continue
        candidate = store.candidates.get(r["candidate_id"])
        if candidate is None or candidate["global_status"] != "DEPARTED":
            continue
        if not (candidate["departed_at"] < r["clawback_until"]):
            continue
        for m in milestones_of(r["id"]):
            if m["kind"] == "RETENTION" and m["status"] == "PAID":
                m["status"] = "CLAWED_BACK"
                m["recovery_status"] = "PENDING"
                touch(m)
                if r["campaign_id"]:
                    campaign = store.campaigns.get(r["campaign_id"])
                    if campaign is not None:
                        # Clawback releases the retention uplift share (PRD 3.5).
                        share = retention_uplift_share(r)
                        if share > 0:
                            campaign_release_earned(campaign, r, share)
                tallies["clawed_back"] += 1

    # 3. Expire stale early-stage referrals (strictly later than
    #    submitted_at + referral_expiry_days of the pinned policy).
    for r in sort_by_created(list(store.referrals.values())):
        if r["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            policy = store.policies.get(r["policy_version_id"])
            if policy is None:
                continue
            deadline = r["submitted_at"] + timedelta(days=policy["referral_expiry_days"])
            if now > deadline:
                transition_referral_terminal(r, "EXPIRED", "EXPIRE", "system")
                tallies["expired"] += 1

    # 4. End elapsed campaigns (ACTIVE / PAUSED with window_end < now).
    for c in sort_by_created(list(store.campaigns.values())):
        if c["status"] in ("ACTIVE", "PAUSED") and c["window_end"] < now:
            c["status"] = "ENDED"
            touch(c)
            end_campaign_releases(c)
            tallies["campaigns_ended"] += 1

    return tallies
