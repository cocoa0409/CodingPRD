"""Cross-entity cascades: outcome recording/reversal, appeal withdrawal,
write-off approval/rescission side effects, the clock expiry sweep, the triage
recurrence sweep, and scorecard finalization."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store
from services import (
    ACTIVE_APPEAL_STATES,
    AUTO_TASK_DUE_DAYS,
    MAX_APPEAL_LEVEL,
    MONITORING_DAYS,
    OPEN_TASK_STATES,
    OUTCOME_STATES,
    WORKABLE_DENIAL_STATES,
    bump_scorecard,
    create_writeoff_record,
    effective_policy,
    emit_event,
    level1_deadline,
    make_record,
    matching_scorecard,
    next_level_deadline,
    recompute_payer_review_flag,
    recompute_priority,
    touch,
)
from util import now_iso, parse_date, today

TWO_DP = Decimal("0.01")


def _open_balance(denial):
    return (
        denial["denied_amount_cents"]
        - denial["recovered_amount_cents"]
        - denial["written_off_cents"]
    )


def refresh_open_balance(denial):
    denial["open_balance_cents"] = _open_balance(denial)


# ---------------------------------------------------------------------------
# Outcome recording cascade (Appeal SUBMITTED -> OVERTURNED / PARTIAL / UPHELD)
# ---------------------------------------------------------------------------


def apply_record_outcome(appeal, denial, outcome, amount, actor_role, actor_id):
    today_d = today()
    appeal["status"] = outcome
    appeal["outcome_amount_cents"] = amount
    appeal["outcome_recorded_at"] = now_iso()
    touch(appeal)

    denial["recovered_amount_cents"] += amount
    refresh_open_balance(denial)

    if outcome == "OVERTURNED":
        # Open balance reaches zero by construction of the amount gate.
        denial["next_appeal_deadline"] = None
        denial["status"] = (
            "RESOLVED_PAID" if denial["written_off_cents"] == 0 else "RESOLVED_WRITTEN_OFF"
        )
    else:
        # UPHELD or PARTIALLY_OVERTURNED with balance remaining.
        next_level = appeal["level_number"] + 1
        if appeal["level_number"] < MAX_APPEAL_LEVEL:
            deadline = next_level_deadline(denial["payer_id"], next_level, today_d)
        else:
            deadline = None
        if deadline is not None:
            denial["next_appeal_deadline"] = deadline
            denial["status"] = "IN_APPEAL"
        else:
            denial["next_appeal_deadline"] = None
            denial["status"] = "CLOSED_EXHAUSTED"

    sc = matching_scorecard(denial.get("root_cause_department"), today_d)
    if sc is not None and amount:
        bump_scorecard(sc, recovered_cents=amount)

    recompute_payer_review_flag(denial["payer_id"])
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "OUTCOME_RECORDED",
        actor_role,
        actor_id,
        "appeal_id=%s;outcome=%s;outcome_amount_cents=%d;recovered_amount_cents=%d;"
        "denial_status=%s"
        % (appeal["id"], outcome, amount, denial["recovered_amount_cents"], denial["status"]),
    )


# ---------------------------------------------------------------------------
# Outcome reversal cascade (Appeal outcome-state -> SUBMITTED)
# ---------------------------------------------------------------------------


def apply_reverse_outcome(appeal, denial, reason, actor_role, actor_id):
    today_d = today()
    amount = appeal["outcome_amount_cents"]
    appeal["status"] = "SUBMITTED"
    appeal["outcome_amount_cents"] = 0
    appeal["outcome_recorded_at"] = None
    appeal["reversal_reason"] = reason
    touch(appeal)

    denial["recovered_amount_cents"] -= amount
    refresh_open_balance(denial)

    payer = store.payers[denial["payer_id"]]
    next_level = appeal["level_number"] + 1
    if denial["status"] == "RESOLVED_PAID":
        denial["status"] = "IN_APPEAL"
        pol = (
            effective_policy(denial["payer_id"], next_level, today_d)
            if next_level <= MAX_APPEAL_LEVEL
            else None
        )
        days = pol["timely_filing_days"] if pol else payer["default_timely_filing_days"]
        denial["next_appeal_deadline"] = (today_d + timedelta(days=days)).isoformat()
    elif denial["status"] == "CLOSED_EXHAUSTED":
        pol = (
            effective_policy(denial["payer_id"], next_level, today_d)
            if next_level <= MAX_APPEAL_LEVEL
            else None
        )
        if pol is not None:
            denial["status"] = "IN_APPEAL"
            denial["next_appeal_deadline"] = (
                today_d + timedelta(days=pol["timely_filing_days"])
            ).isoformat()
    # Denials still IN_APPEAL keep status and existing deadline.

    sc = matching_scorecard(denial.get("root_cause_department"), today_d)
    if sc is not None and amount:
        bump_scorecard(sc, recovered_cents=-amount)

    recompute_payer_review_flag(denial["payer_id"])
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "OUTCOME_REVERSED",
        actor_role,
        actor_id,
        "appeal_id=%s;reversed_amount_cents=%d;recovered_amount_cents=%d;reason=%s"
        % (appeal["id"], amount, denial["recovered_amount_cents"], reason),
    )


# ---------------------------------------------------------------------------
# Appeal withdrawal cascade
# ---------------------------------------------------------------------------


def apply_withdraw(appeal, denial, actor_role, actor_id):
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    remaining = [
        a
        for a in store.appeals.values()
        if a["denial_case_id"] == denial["id"] and a["status"] != "WITHDRAWN"
    ]
    level = max((a["level_number"] for a in remaining), default=0)
    denial["current_appeal_level"] = level
    if level == 0 and denial["status"] == "IN_APPEAL":
        denial["status"] = "QUEUED"  # level-1 deadline still governs
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "APPEAL_WITHDRAWN",
        actor_role,
        actor_id,
        "appeal_id=%s;current_appeal_level=%d;denial_status=%s"
        % (appeal["id"], level, denial["status"]),
    )


# ---------------------------------------------------------------------------
# Write-off approval / rescission cascades
# ---------------------------------------------------------------------------


def apply_writeoff_approval(wo, denial, actor_role, actor_id):
    today_d = today()
    wo["denial_status_before"] = denial["status"]
    wo["decided_by_user_id"] = actor_id
    wo["decided_at"] = now_iso()
    wo["status"] = "APPROVED"
    touch(wo)

    denial["written_off_cents"] += wo["requested_amount_cents"]
    refresh_open_balance(denial)
    if denial["open_balance_cents"] == 0:
        denial["status"] = "RESOLVED_WRITTEN_OFF"
        denial["next_appeal_deadline"] = None
    sc = matching_scorecard(denial.get("root_cause_department"), today_d)
    if sc is not None:
        bump_scorecard(sc, written_off_cents=wo["requested_amount_cents"])
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "WRITE_OFF_APPROVED",
        actor_role,
        actor_id,
        "write_off_request_id=%s;approved_amount_cents=%d;written_off_cents=%d;"
        "denial_status=%s"
        % (
            wo["id"],
            wo["requested_amount_cents"],
            denial["written_off_cents"],
            denial["status"],
        ),
    )


def _latest_outcome_date(denial_id):
    dates = []
    for a in store.appeals.values():
        if a["denial_case_id"] == denial_id and a["status"] in OUTCOME_STATES:
            dates.append(parse_date(a["outcome_recorded_at"][:10]))
    return max(dates) if dates else None


def apply_writeoff_rescission(wo, denial, reason, actor_role, actor_id):
    today_d = today()
    wo["status"] = "RESCINDED"
    wo["decision_reason"] = reason
    wo["decided_by_user_id"] = actor_id
    wo["decided_at"] = now_iso()
    touch(wo)

    denial["written_off_cents"] -= wo["requested_amount_cents"]
    refresh_open_balance(denial)
    restored = wo["denial_status_before"]
    denial["status"] = restored
    payer = store.payers[denial["payer_id"]]
    if restored == "QUEUED":
        denial["next_appeal_deadline"] = level1_deadline(
            payer, denial["remittance_received_date"]
        )
    elif restored == "IN_APPEAL":
        outcome_date = _latest_outcome_date(denial["id"])
        if outcome_date is not None:
            next_level = denial["current_appeal_level"] + 1
            if next_level <= MAX_APPEAL_LEVEL:
                denial["next_appeal_deadline"] = next_level_deadline(
                    denial["payer_id"], next_level, outcome_date
                )
            else:
                denial["next_appeal_deadline"] = None
        else:
            denial["next_appeal_deadline"] = level1_deadline(
                payer, denial["remittance_received_date"]
            )
    else:
        denial["next_appeal_deadline"] = None
    sc = matching_scorecard(denial.get("root_cause_department"), today_d)
    if sc is not None:
        bump_scorecard(sc, written_off_cents=-wo["requested_amount_cents"])
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "WRITE_OFF_RESCINDED",
        actor_role,
        actor_id,
        "write_off_request_id=%s;rescinded_amount_cents=%d;written_off_cents=%d;"
        "denial_status=%s"
        % (wo["id"], wo["requested_amount_cents"], denial["written_off_cents"], denial["status"]),
    )


# ---------------------------------------------------------------------------
# Timely-filing expiry sweep (driven by the logical clock)
# ---------------------------------------------------------------------------


def _expire_denial(denial):
    today_d = today()
    denial["status"] = "CLOSED_EXPIRED"
    denial["next_appeal_deadline"] = None
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "EXPIRED",
        "system",
        "system",
        "status=CLOSED_EXPIRED;open_balance_cents=%d" % denial["open_balance_cents"],
    )
    created = False
    if denial["open_balance_cents"] > 0 and not any(
        w["denial_case_id"] == denial["id"] and w["status"] in ("PENDING_MANAGER", "ESCALATED_DIRECTOR")
        for w in store.writeoffs.values()
    ):
        create_writeoff_record(
            denial,
            denial["open_balance_cents"],
            "TIMELY_FILING_EXPIRED",
            "system",
            "system",
        )
        created = True
    sc = matching_scorecard(denial.get("root_cause_department"), today_d)
    if sc is not None:
        deltas = {"expired_denial_count": 1}
        if created:
            deltas["auto_writeoff_request_count"] = 1
        bump_scorecard(sc, **deltas)


def run_expiry_sweep():
    """Expire lapsed denials in created_at ASC order; recompute queue scores."""
    expired_ids = []
    today_d = today()
    ordered = sorted(store.denials.values(), key=lambda d: (d["created_at"], d["_seq"]))
    for denial in ordered:
        deadline = denial.get("next_appeal_deadline")
        if not deadline or today_d <= parse_date(deadline):
            continue
        if denial["status"] == "QUEUED":
            _expire_denial(denial)
            expired_ids.append(denial["id"])
        elif denial["status"] == "IN_APPEAL":
            shielded = any(
                a["denial_case_id"] == denial["id"] and a["status"] in ACTIVE_APPEAL_STATES
                for a in store.appeals.values()
            )
            if not shielded:
                _expire_denial(denial)
                expired_ids.append(denial["id"])
    for denial in store.denials.values():
        if denial["status"] in WORKABLE_DENIAL_STATES:
            if recompute_priority(denial):
                touch(denial)
    return expired_ids


# ---------------------------------------------------------------------------
# Triage: auto task creation + recurrence sweep
# ---------------------------------------------------------------------------


def auto_create_task(denial, actor_role, actor_id):
    today_d = today()
    task = make_record(
        {
            "denial_case_id": denial["id"],
            "department": denial["root_cause_department"],
            "task_type": "PROCESS_FIX",
            "description": "Auto-created PROCESS_FIX task for preventable denial %s"
            % denial["claim_number"],
            "due_date": (today_d + timedelta(days=AUTO_TASK_DUE_DAYS)).isoformat(),
            "status": "OPEN",
            "implemented_by_user_id": None,
            "fix_summary": "",
            "verified_at": None,
            "monitoring_until_date": None,
            "recurrence_of_task_id": None,
            "reopened_count": 0,
        }
    )
    store.tasks[task["id"]] = task
    sc = matching_scorecard(denial["root_cause_department"], today_d)
    if sc is not None:
        bump_scorecard(sc, open_task_count=1)
    emit_event(
        denial["id"],
        "TASK_AUTO_CREATED",
        actor_role,
        actor_id,
        "task_id=%s;department=%s;task_type=PROCESS_FIX"
        % (task["id"], denial["root_cause_department"]),
    )
    return task


def recurrence_sweep(new_denial):
    """Flip the single best-matching VERIFIED monitored task back to REOPENED."""
    today_d = today()
    candidates = []
    for task in store.tasks.values():
        if task["status"] != "VERIFIED":
            continue
        if task["department"] != new_denial["root_cause_department"]:
            continue
        mon = task.get("monitoring_until_date")
        if not mon or parse_date(mon) < today_d:
            continue
        old_denial = store.denials.get(task["denial_case_id"])
        if old_denial is None or old_denial["category"] != new_denial["category"]:
            continue
        candidates.append(task)
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["verified_at"] or "", t["created_at"], t["_seq"]))
    task = candidates[0]
    old_denial = store.denials[task["denial_case_id"]]
    task["status"] = "REOPENED"
    task["reopened_count"] += 1
    task["verified_at"] = None
    task["monitoring_until_date"] = None
    touch(task)
    sc = matching_scorecard(task["department"], today_d)
    if sc is not None:
        bump_scorecard(
            sc,
            verified_fix_count=-1,
            verified_linked_denied_cents=-old_denial["denied_amount_cents"],
            recurrence_count=1,
            recurrence_linked_denied_cents=new_denial["denied_amount_cents"],
            open_task_count=1,
        )
    emit_event(
        new_denial["id"],
        "TASK_REOPENED",
        "system",
        "system",
        "task_id=%s;reopened_count=%d" % (task["id"], task["reopened_count"]),
    )
    return task


# ---------------------------------------------------------------------------
# Scorecard finalization (calculations.prevention_scorecard_score)
# ---------------------------------------------------------------------------


def _rate(num, den):
    return Fraction(num, den) if den else Fraction(0, 1)


def finalize_scorecard(sc):
    today_d = today()
    dept_tasks = [t for t in store.tasks.values() if t["department"] == sc["department"]]
    open_tasks = [t for t in dept_tasks if t["status"] in OPEN_TASK_STATES]
    overdue_tasks = [t for t in open_tasks if parse_date(t["due_date"]) < today_d]

    def linked_denied(task):
        denial = store.denials.get(task["denial_case_id"])
        return denial["denied_amount_cents"] if denial else 0

    # Incidence variant (count-weighted)
    inc_rr = _rate(sc["recurrence_count"], sc["verified_fix_count"] + sc["recurrence_count"])
    inc_pr = _rate(sc["preventable_denial_count"], sc["denial_count"])
    inc_or = _rate(len(overdue_tasks), len(open_tasks))

    # Financial variant (dollar-weighted)
    fin_rr = _rate(
        sc["recurrence_linked_denied_cents"],
        sc["verified_linked_denied_cents"] + sc["recurrence_linked_denied_cents"],
    )
    fin_pr = _rate(sc["preventable_denied_cents"], sc["denied_cents"])
    fin_or = _rate(
        sum(linked_denied(t) for t in overdue_tasks),
        sum(linked_denied(t) for t in open_tasks),
    )

    def score(rr, pr, orate):
        raw = Fraction(100) - (50 * rr + 30 * pr + 20 * orate)
        if raw < 0:
            raw = Fraction(0)
        if raw > 100:
            raw = Fraction(100)
        dec = Decimal(raw.numerator) / Decimal(raw.denominator)
        return float(dec.quantize(TWO_DP, rounding=ROUND_HALF_UP))

    incidence = score(inc_rr, inc_pr, inc_or)
    financial = score(fin_rr, fin_pr, fin_or)
    inc_dec = Decimal(str(incidence))
    if inc_dec >= Decimal("90.00"):
        tier = "EXCELLENT"
    elif inc_dec >= Decimal("75.00"):
        tier = "GOOD"
    elif inc_dec >= Decimal("60.00"):
        tier = "WATCH"
    else:
        tier = "CRITICAL"

    sc["prevention_score_incidence"] = incidence
    sc["prevention_score_financial"] = financial
    sc["score_tier"] = tier
    sc["status"] = "FINALIZED"
    touch(sc)
