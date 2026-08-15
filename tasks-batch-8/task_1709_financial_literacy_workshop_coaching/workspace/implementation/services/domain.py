"""Shared business logic: record lifecycle, lazy sweeps, cascades, schedule
overlap checks, waitlist promotion, incentive math, caseload/seat derivation,
and funder-report aggregation. Money uses Decimal with ROUND_HALF_UP only."""
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import db
from db import STORE, logical_now
from helpers import fmt_dt

NO_SHOW_LIMIT = 3
TRAVEL_BUFFER = timedelta(minutes=30)
REFERRAL_TTL = timedelta(days=30)
CERT_TTL = timedelta(days=365)

OPEN_CASE_STATUSES = {"INTAKE", "PLAN_DRAFT", "PLAN_ACTIVE", "ON_HOLD", "PLAN_STALLED"}
CASELOAD_STATUSES = {"INTAKE", "PLAN_DRAFT", "PLAN_ACTIVE", "ON_HOLD"}
STALLABLE_CASE_STATUSES = {"INTAKE", "PLAN_DRAFT", "PLAN_ACTIVE"}
ENROLLMENT_OPEN_STATUSES = {"ACTIVE", "MATCH_PAUSED", "GOAL_MET"}


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_common():
    """System fields for primary resources: id, created_at, updated_at, version."""
    now = logical_now()
    return {
        "id": str(uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_log():
    """System fields for append-only / frozen resources: id + created_at only."""
    return {"id": str(uuid4()), "created_at": logical_now(), "_seq": db.next_seq()}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = logical_now()


# ---------------------------------------------------------------------------
# Derived quantities (PRD §2.9 conservation invariants)
# ---------------------------------------------------------------------------

def confirmed_count(workshop_id):
    return sum(
        1
        for r in STORE["registrations"].values()
        if r["workshop_id"] == workshop_id and r["status"] == "REGISTERED"
    )


def active_caseload(coach_id):
    return sum(
        1
        for c in STORE["cases"].values()
        if c["coach_id"] == coach_id and c["status"] in CASELOAD_STATUSES
    )


# ---------------------------------------------------------------------------
# Lazy sweeps and cascades (PRD §2.4, §3.5)
# ---------------------------------------------------------------------------

def freeze_plan(plan):
    """GoalPlan ACTIVE -> FROZEN; pauses the linked ACTIVE enrollment (LINK 3)."""
    if plan["status"] != "ACTIVE":
        return
    plan["status"] = "FROZEN"
    touch(plan)
    for en in STORE["enrollments"].values():
        if en["goal_plan_id"] == plan["id"] and en["status"] == "ACTIVE":
            en["status"] = "MATCH_PAUSED"
            touch(en)


def activate_plan(plan):
    """GoalPlan FROZEN -> ACTIVE; resumes the paused enrollment."""
    if plan["status"] != "FROZEN":
        return
    plan["status"] = "ACTIVE"
    touch(plan)
    for en in STORE["enrollments"].values():
        if en["goal_plan_id"] == plan["id"] and en["status"] == "MATCH_PAUSED":
            en["status"] = "ACTIVE"
            touch(en)


def stall_cascade(coach_id):
    """LINK 1: open (non-hold) cases -> PLAN_STALLED; LINK 2/3 via freeze_plan."""
    for case in list(STORE["cases"].values()):
        if case["coach_id"] == coach_id and case["status"] in STALLABLE_CASE_STATUSES:
            case["status"] = "PLAN_STALLED"
            touch(case)
            for plan in STORE["goal_plans"].values():
                if plan["case_id"] == case["id"] and plan["status"] == "ACTIVE":
                    freeze_plan(plan)


def sweep_coach(coach):
    """CERTIFIED -> LAPSED when the certification expiry has been reached."""
    if (
        coach["status"] == "CERTIFIED"
        and coach.get("certification_expires_at") is not None
        and logical_now() >= coach["certification_expires_at"]
    ):
        coach["status"] = "LAPSED"
        touch(coach)
        stall_cascade(coach["id"])


def sweep_referral(ref):
    """SENT -> EXPIRED when expires_at has been reached."""
    if ref["status"] == "SENT" and logical_now() >= ref["expires_at"]:
        ref["status"] = "EXPIRED"
        touch(ref)


def sweep_all():
    for coach in list(STORE["coaches"].values()):
        sweep_coach(coach)
    for ref in list(STORE["referrals"].values()):
        sweep_referral(ref)


def exit_case(case):
    """Case -> EXITED with plan supersession; linked enrollments untouched."""
    case["status"] = "EXITED"
    touch(case)
    for plan in STORE["goal_plans"].values():
        if plan["case_id"] == case["id"] and plan["status"] in ("ACTIVE", "FROZEN"):
            plan["status"] = "SUPERSEDED"
            touch(plan)


# ---------------------------------------------------------------------------
# Schedule overlap rules (scaffold §1.3)
# ---------------------------------------------------------------------------

def coach_conflict(coach_id, start_at, end_at, exclude_id=None):
    """Half-open [start, end) overlap against the coach's SCHEDULED workshops."""
    for w in STORE["workshops"].values():
        if w["coach_id"] != coach_id or w["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and w["id"] == exclude_id:
            continue
        if start_at < w["end_at"] and w["start_at"] < end_at:
            return True
    return False


def participant_conflict(participant_id, start_at, end_at):
    """30-minute buffered overlap against the participant's REGISTERED workshops."""
    for r in STORE["registrations"].values():
        if r["participant_id"] != participant_id or r["status"] != "REGISTERED":
            continue
        w = STORE["workshops"].get(r["workshop_id"])
        if w is None:
            continue
        if start_at < w["end_at"] + TRAVEL_BUFFER and w["start_at"] < end_at + TRAVEL_BUFFER:
            return True
    return False


# ---------------------------------------------------------------------------
# Waitlist promotion (scaffold §1.3 waitlist_promotion)
# ---------------------------------------------------------------------------

def run_promotion(workshop):
    if workshop["status"] != "SCHEDULED":
        return
    if logical_now() >= workshop["start_at"]:
        return
    candidates = sorted(
        (
            r
            for r in STORE["registrations"].values()
            if r["workshop_id"] == workshop["id"] and r["status"] == "WAITLISTED"
        ),
        key=lambda r: r["waitlist_position"],
    )
    for r in candidates:
        p = STORE["participants"].get(r["participant_id"])
        if p is None or p["status"] != "ACTIVE":
            continue
        if participant_conflict(p["id"], workshop["start_at"], workshop["end_at"]):
            continue
        r["status"] = "REGISTERED"
        r["waitlist_position"] = None
        touch(r)
        return


# ---------------------------------------------------------------------------
# Incentive math (scaffold §1.3 session_incentive; PRD §2.6, §3.2)
# ---------------------------------------------------------------------------

def _duration_seconds_exact(workshop):
    td = workshop["end_at"] - workshop["start_at"]
    return (
        Decimal(td.days * 86400 + td.seconds)
        + Decimal(td.microseconds) / Decimal(1000000)
    )


def session_line_cents(module, workshop):
    """round_half_up(incentive_cents_per_hour x duration in hours), per session."""
    hours = _duration_seconds_exact(workshop) / Decimal(3600)
    cents = Decimal(module["incentive_cents_per_hour"]) * hours
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def incentive_summary(participant_id):
    attended = [
        r
        for r in STORE["registrations"].values()
        if r["participant_id"] == participant_id and r["status"] == "ATTENDED"
    ]
    registered = [
        r
        for r in STORE["registrations"].values()
        if r["participant_id"] == participant_id and r["status"] == "REGISTERED"
    ]

    def module_of(reg):
        w = STORE["workshops"].get(reg["workshop_id"])
        return STORE["modules"].get(w["module_id"]) if w else None

    attended_per_module = {}
    earned_sessions = 0
    for r in attended:
        m = module_of(r)
        if m is None:
            continue
        attended_per_module[m["id"]] = attended_per_module.get(m["id"], 0) + 1
        earned_sessions += r["incentive_earned_cents"]

    registered_per_module = {}
    for r in registered:
        m = module_of(r)
        if m is None:
            continue
        registered_per_module[m["id"]] = registered_per_module.get(m["id"], 0) + 1

    bonuses_earned = 0
    earned_module_ids = set()
    for mid, count in attended_per_module.items():
        m = STORE["modules"][mid]
        if count >= m["completion_threshold"]:
            bonuses_earned += m["completion_bonus_cents"]
            earned_module_ids.add(mid)

    earned_cents = earned_sessions + bonuses_earned

    provisional_cents = earned_cents
    for r in registered:
        w = STORE["workshops"].get(r["workshop_id"])
        m = module_of(r)
        if w is None or m is None:
            continue
        provisional_cents += session_line_cents(m, w)
    for mid, rcount in registered_per_module.items():
        if mid in earned_module_ids:
            continue
        m = STORE["modules"][mid]
        acount = attended_per_module.get(mid, 0)
        if acount + rcount >= m["completion_threshold"]:
            provisional_cents += m["completion_bonus_cents"]

    return {
        "earned_cents": earned_cents,
        "provisional_cents": provisional_cents,
        "attended_sessions": len(attended),
        "registered_sessions": len(registered),
        "completion_bonuses_earned_cents": bonuses_earned,
    }


# ---------------------------------------------------------------------------
# Funder outcome aggregation (scaffold §1.3 funder_outcome_aggregation; PRD §3.9)
# ---------------------------------------------------------------------------

def compute_funder_report(period_start, period_end, variant):
    """period_start/period_end are dates; window is [start, end) on the
    recorded_at / completion date."""
    included = []
    for p in STORE["participants"].values():
        cases = [c for c in STORE["cases"].values() if c["participant_id"] == p["id"]]
        if not cases:
            continue
        intake_dates = [c["_intake_date"] for c in cases]
        if variant == "COHORT":
            earliest = min(intake_dates)
            if period_start <= earliest < period_end:
                included.append(p["id"])
        else:  # ROLLING
            if any(d < period_end for d in intake_dates):
                included.append(p["id"])

    credit_deltas = []
    savings_deltas = []
    measured = 0
    for pid in included:
        snaps = [
            s
            for s in STORE["snapshots"].values()
            if s["participant_id"] == pid
            and period_start <= s["recorded_at"].date() < period_end
        ]
        snaps.sort(key=lambda s: (s["recorded_at"], s["created_at"], s["_seq"]))
        credit_vals = [s["credit_score"] for s in snaps if s.get("credit_score") is not None]
        saving_vals = [
            s["savings_balance_cents"]
            for s in snaps
            if s.get("savings_balance_cents") is not None
        ]
        qualifies = False
        if len(credit_vals) >= 2:
            credit_deltas.append(credit_vals[-1] - credit_vals[0])
            qualifies = True
        if len(saving_vals) >= 2:
            savings_deltas.append(saving_vals[-1] - saving_vals[0])
            qualifies = True
        if qualifies:
            measured += 1

    if credit_deltas:
        mean_credit = Decimal(sum(credit_deltas)) / Decimal(len(credit_deltas))
        avg_credit = float(
            mean_credit.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        )
    else:
        avg_credit = None

    if savings_deltas:
        mean_sav = Decimal(sum(savings_deltas)) / Decimal(len(savings_deltas))
        avg_savings = int(mean_sav.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        avg_savings = None

    completions = sum(
        1
        for c in STORE["cases"].values()
        if c.get("_completed_at") is not None
        and period_start <= c["_completed_at"].date() < period_end
    )

    return {
        "participants_measured": measured,
        "avg_credit_delta_points": avg_credit,
        "avg_savings_delta_cents": avg_savings,
        "completions_count": completions,
    }


# ---------------------------------------------------------------------------
# Serializers (exact field sets per SCAFFOLD.yaml §1.1 + common fields §2.5)
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_module(m):
    out = {
        "id": m["id"],
        "module_code": m["module_code"],
        "title": m["title"],
        "session_count": m["session_count"],
        "incentive_cents_per_hour": m["incentive_cents_per_hour"],
        "completion_bonus_cents": m["completion_bonus_cents"],
        "completion_threshold": m["completion_threshold"],
        "status": m["status"],
    }
    out.update(_common(m))
    return out


def ser_coach(c):
    out = {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "max_caseload": c["max_caseload"],
        "status": c["status"],
        "certification_expires_at": fmt_dt(c.get("certification_expires_at")),
        "active_caseload": active_caseload(c["id"]),
    }
    out.update(_common(c))
    return out


def ser_participant(p):
    out = {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "annual_income_cents": p["annual_income_cents"],
        "status": p["status"],
        "no_show_count": p["no_show_count"],
    }
    out.update(_common(p))
    return out


def ser_workshop(w):
    out = {
        "id": w["id"],
        "module_id": w["module_id"],
        "coach_id": w["coach_id"],
        "location": w["location"],
        "start_at": fmt_dt(w["start_at"]),
        "end_at": fmt_dt(w["end_at"]),
        "capacity": w["capacity"],
        "confirmed_count": confirmed_count(w["id"]),
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_registration(r):
    out = {
        "id": r["id"],
        "workshop_id": r["workshop_id"],
        "participant_id": r["participant_id"],
        "status": r["status"],
        "waitlist_position": r["waitlist_position"],
        "incentive_earned_cents": r["incentive_earned_cents"],
    }
    out.update(_common(r))
    return out


def ser_case(c):
    out = {
        "id": c["id"],
        "participant_id": c["participant_id"],
        "coach_id": c["coach_id"],
        "intake_date": c["intake_date"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_plan(p):
    out = {
        "id": p["id"],
        "case_id": p["case_id"],
        "monthly_savings_goal_cents": p["monthly_savings_goal_cents"],
        "credit_score_target": p["credit_score_target"],
        "status": p["status"],
        "plan_sequence": p["plan_sequence"],
    }
    out.update(_common(p))
    return out


def ser_snapshot(s):
    return {
        "id": s["id"],
        "participant_id": s["participant_id"],
        "recorded_at": fmt_dt(s["recorded_at"]),
        "credit_score": s.get("credit_score"),
        "savings_balance_cents": s.get("savings_balance_cents"),
        "created_at": fmt_dt(s["created_at"]),
    }


def ser_pool(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "total_funded_cents": p["total_funded_cents"],
        "income_threshold_cents": p["income_threshold_cents"],
        "match_ratio_below": p["match_ratio_below"],
        "match_ratio_above": p["match_ratio_above"],
        "per_participant_cap_cents": p["per_participant_cap_cents"],
        "uncommitted_cents": p["uncommitted_cents"],
        "paid_out_cents": p["paid_out_cents"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_enrollment(e):
    out = {
        "id": e["id"],
        "participant_id": e["participant_id"],
        "pool_id": e["pool_id"],
        "goal_plan_id": e["goal_plan_id"],
        "savings_goal_cents": e["savings_goal_cents"],
        "status": e["status"],
        "total_deposited_cents": e["total_deposited_cents"],
        "accrued_unpaid_cents": e["accrued_unpaid_cents"],
    }
    out.update(_common(e))
    return out


def ser_referral(r):
    out = {
        "id": r["id"],
        "participant_id": r["participant_id"],
        "coach_id": r["coach_id"],
        "partner_name": r["partner_name"],
        "partner_type": r["partner_type"],
        "status": r["status"],
        "sent_at": fmt_dt(r["sent_at"]),
        "expires_at": fmt_dt(r["expires_at"]),
    }
    out.update(_common(r))
    return out


def ser_report(r):
    return {
        "id": r["id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "variant": r["variant"],
        "participants_measured": r["participants_measured"],
        "avg_credit_delta_points": r["avg_credit_delta_points"],
        "avg_savings_delta_cents": r["avg_savings_delta_cents"],
        "completions_count": r["completions_count"],
        "created_at": fmt_dt(r["created_at"]),
    }


def sort_by_creation(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
