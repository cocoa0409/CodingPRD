"""Business logic: calculations, posture aggregation, cascades, scheduler."""
import uuid
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from core import (
    ASSET_RETURN_GRACE_DAYS,
    BENEFITS_DEADLINE_DAYS,
    BUSINESS_DAY_STATES,
    CALENDAR_DAY_STATES,
    CLOCK,
    COVENANT_REMIND_DAYS,
    DAMAGE_FRACTION_DAMAGED,
    DB,
    DEDUPE_WINDOW_MINUTES,
    DEP_BPS_BY_KIND,
    DEP_BPS_DEFAULT,
    HOURS_PER_DAY,
    LATE_FEE_CENTS,
    MAX_DEPRECIATION_BPS,
    NOTICE_CAP_DAYS,
    PTO_PAYOUT_STATES,
    RESIGNATION_TYPES,
    RESIGNATION_NOTICE_THRESHOLD_HOURS,
    REVOKE_OFFSET_HOURS,
    TERMINATION_TYPES,
    WAITING_TIME_CAP_DAYS,
    bump,
    next_seq,
    now_dt,
)

MAX_REVOKE_RETRIES = 3


# --------------------------------------------------------------------------
# Entity accessors
# --------------------------------------------------------------------------
def tasks_of(case_id):
    return [t for t in DB["tasks"].values() if t["offboarding_case_id"] == case_id]


def assets_of(case_id):
    return [a for a in DB["assets"].values() if a["offboarding_case_id"] == case_id]


def statement_of(case_id):
    for s in DB["statements"].values():
        if s["offboarding_case_id"] == case_id:
            return s
    return None


def plan_of(case_id):
    for p in DB["plans"].values():
        if p["offboarding_case_id"] == case_id:
            return p
    return None


def review_of(case_id):
    for r in DB["reviews"].values():
        if r["offboarding_case_id"] == case_id:
            return r
    return None


def interviews_of(case_id):
    return [i for i in DB["interviews"].values() if i["offboarding_case_id"] == case_id]


def notices_of(case_id):
    return [n for n in DB["notices"].values() if n["offboarding_case_id"] == case_id]


def acks_of(case_id):
    return [k for k in DB["acks"].values() if k["offboarding_case_id"] == case_id]


def sessions_of(plan_id):
    return [s for s in DB["sessions"].values() if s["knowledge_transfer_plan_id"] == plan_id]


# --------------------------------------------------------------------------
# Calculation rules
# --------------------------------------------------------------------------
def _midnight(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def calc_last_day_determination(case):
    """determined_last_day: dual-variant threshold rule, date at midnight UTC."""
    notice = case["notice_received_date"]
    requested = case["requested_last_day"]
    if case["case_type"] in RESIGNATION_TYPES:
        cap = notice + timedelta(days=NOTICE_CAP_DAYS)
        d = _midnight(min(requested, cap))
        # weekend rolls FORWARD to Monday
        while d.weekday() >= 5:
            d += timedelta(days=1)
    else:
        d = _midnight(max(notice, requested))
        # weekend rolls BACKWARD to Friday
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def _next_payday(dl):
    y, m = dl.year, dl.month
    last_day = monthrange(y, m)[1]
    candidates = [
        datetime(y, m, 15, 17, 0, 0, tzinfo=dl.tzinfo),
        datetime(y, m, last_day, 17, 0, 0, tzinfo=dl.tzinfo),
    ]
    for c in sorted(candidates):
        if c > dl:
            return c
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime(ny, nm, 15, 17, 0, 0, tzinfo=dl.tzinfo)


def calc_final_pay_deadline(case, determined_last_day):
    """Returns (due_at, state_law_variant)."""
    state = case["work_state_code"]
    ctype = case["case_type"]
    dl = determined_last_day
    if state in CALENDAR_DAY_STATES:
        if ctype in TERMINATION_TYPES:
            return dl, "IMMEDIATE_ON_TERMINATION"
        notice_hours = (
            case["requested_last_day"] - case["notice_received_date"]
        ).total_seconds() / 3600.0
        if notice_hours >= RESIGNATION_NOTICE_THRESHOLD_HOURS:
            return dl, "WITHIN_FIXED_DAYS"
        return dl + timedelta(hours=RESIGNATION_NOTICE_THRESHOLD_HOURS), "WITHIN_FIXED_DAYS"
    if state in BUSINESS_DAY_STATES:
        d = dl + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d, "WITHIN_FIXED_DAYS"
    # NEXT_PAYDAY_STATES (TX, FL)
    return _next_payday(dl), "NEXT_PAYDAY"


def calc_pto_payout(case):
    """Dual-variant PTO payout; pays the GREATER of state-law and company-policy."""
    wage = Decimal(case["hourly_wage_cents"])
    balance = Decimal(str(case["pto_balance_hours"]))
    tenure = Decimal(str(case["tenure_years"]))
    # Variant S: state law — uncapped full balance in payout states
    if case["work_state_code"] in PTO_PAYOUT_STATES:
        variant_s = balance * wage
    else:
        variant_s = Decimal(0)
    # Variant C: company policy — tenure-tiered cap, half-hour floor rounding
    if tenure < 2:
        cap_hours = Decimal(40)
    elif tenure < 5:
        cap_hours = Decimal(80)
    else:
        cap_hours = Decimal(120)
    payable = min(balance, cap_hours)
    payable = (payable * 2).to_integral_value(rounding=ROUND_FLOOR) / 2
    variant_c = payable * wage
    final = max(variant_s, variant_c)
    return int(final.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_final_net_pay(regular_wages_cents, pto_payout_cents, case_deduction_total_cents):
    """Pinned waterfall: gross -> capped deduction -> net (never below zero)."""
    gross = regular_wages_cents + pto_payout_cents
    deduction = min(case_deduction_total_cents, gross)
    net = gross - deduction
    return deduction, net


def calc_asset_deduction_default(item):
    """Default variant: depreciated value keyed on age from issued_date."""
    age_seconds = (item["return_due_at"] - item["issued_date"]).total_seconds()
    age_days = int(Decimal(str(age_seconds)) // Decimal(86400))  # floor, discards partial days
    rate = DEP_BPS_BY_KIND.get(item["asset_kind"], DEP_BPS_DEFAULT)
    depreciation_bps = min(age_days * rate, MAX_DEPRECIATION_BPS)
    value = Decimal(item["replacement_cost_cents"]) * Decimal(10000 - depreciation_bps) / Decimal(10000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_asset_deduction_damage(item, condition):
    """Damage variant: flat fraction of replacement cost (DESTROYED = full)."""
    cost = Decimal(item["replacement_cost_cents"])
    if condition == "DESTROYED":
        base = cost
    else:  # DAMAGED
        base = cost * Decimal(DAMAGE_FRACTION_DAMAGED)
    return int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_late_penalty(due_at, as_of, hourly_wage_cents):
    """Waiting-time penalty: daily wage per late calendar day (ceil), capped 30."""
    delta = as_of - due_at
    seconds = Decimal(str(delta.total_seconds()))
    late_days = int((seconds / Decimal(86400)).to_integral_value(rounding=ROUND_CEILING))
    late_days = max(0, min(late_days, WAITING_TIME_CAP_DAYS))
    return late_days * hourly_wage_cents * HOURS_PER_DAY


def calc_revocation_schedule(system_name, determined_last_day):
    """Anchor 17:00 UTC on the determined last day, shifted by per-system offset."""
    anchor = determined_last_day.replace(hour=17, minute=0, second=0, microsecond=0)
    return anchor + timedelta(hours=REVOKE_OFFSET_HOURS[system_name])


def calc_benefits_deadline(notice_kind, base):
    """send_by: base + per-kind calendar days, pinned to 17:00 UTC on target date."""
    days = BENEFITS_DEADLINE_DAYS[notice_kind]
    target = base + timedelta(days=days)
    return target.replace(hour=17, minute=0, second=0, microsecond=0)


def calc_covenant_reminder(determined_last_day):
    """remind_at: determined_last_day + 3 days at 09:00 UTC."""
    target = determined_last_day + timedelta(days=COVENANT_REMIND_DAYS)
    return target.replace(hour=9, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------
# Posture aggregation
# --------------------------------------------------------------------------
def compute_revocation_posture(tasks):
    if tasks and all(t["status"] in ("VERIFIED", "WAIVED") for t in tasks):
        return "COMPLETE"
    if any(t["status"] in ("FAILED", "RETRY_SCHEDULED") and t["retry_count"] >= MAX_REVOKE_RETRIES
           for t in tasks):
        return "BLOCKED"
    if any(t["status"] in ("READY", "EXECUTED", "RETRY_SCHEDULED") for t in tasks):
        return "IN_PROGRESS"
    return "NOT_STARTED"


def compute_asset_posture(items):
    if not items:
        return "NOT_STARTED"
    if all(i["status"] in ("RETURNED", "WAIVED") for i in items):
        return "COMPLETE"
    if any(i["status"] in ("DEFAULTED", "OVERDUE") for i in items):
        return "DEFAULTED"
    return "IN_PROGRESS"


def compute_deduction_total(case_id):
    return sum(
        i["deduction_amount_cents"]
        for i in assets_of(case_id)
        if i["deduction_status"] == "APPLIED"
    )


# --------------------------------------------------------------------------
# Notifications (append-only, deduplicated within a 60-minute window)
# --------------------------------------------------------------------------
def emit_notification(case_id, kind):
    t = now_dt()
    suppressed = False
    window = timedelta(minutes=DEDUPE_WINDOW_MINUTES)
    for n in DB["notifications"]:
        if (n["offboarding_case_id"] == case_id
                and n["notification_kind"] == kind
                and not n["suppressed"]
                and n["sent_at"] <= t < n["sent_at"] + window):
            suppressed = True
            break
    DB["notifications"].append({
        "id": str(uuid.uuid4()),
        "created_at": t,
        "offboarding_case_id": case_id,
        "notification_kind": kind,
        "sent_at": t,
        "recipient_manager_ref": None,
        "suppressed": suppressed,
        "_seq": next_seq(),
    })


# --------------------------------------------------------------------------
# Case-level reconciliation (postures + automatic state transitions)
# --------------------------------------------------------------------------
def ready_gate(case):
    """The §3.7 readiness gate evaluated against live child state."""
    items = assets_of(case["id"])
    if items and compute_asset_posture(items) not in ("COMPLETE", "DEFAULTED"):
        return False
    for iv in interviews_of(case["id"]):
        if iv["status"] in ("SCHEDULED", "RESCHEDULE_REQUESTED"):
            return False
    pl = plan_of(case["id"])
    if pl is None or pl["status"] not in ("COMPLETE", "WAIVED"):
        return False
    return True


def reconcile_case(case):
    """Fire case-level automatic transitions whose preconditions hold.

    Bumps the case version at most once per call. Returns True if the case
    record changed.
    """
    changed = False
    if case["status"] == "APPROVED":
        ts = tasks_of(case["id"])
        if any(t["status"] in ("READY", "EXECUTED") for t in ts):
            case["status"] = "REVOCATION_IN_PROGRESS"
            emit_notification(case["id"], "REVOCATION_STARTED")
            changed = True
    if case["status"] == "REVOCATION_IN_PROGRESS" and case["revocation_posture"] == "COMPLETE":
        emit_notification(case["id"], "REVOCATION_COMPLETE")
        for n in notices_of(case["id"]):
            if n["status"] == "DRAFT":
                n["status"] = "QUEUED"
                n["send_by"] = calc_benefits_deadline(n["notice_kind"], case["determined_last_day"])
                bump(n)
        for k in acks_of(case["id"]):
            if k["status"] == "PENDING" and k["remind_at"] is None:
                k["remind_at"] = calc_covenant_reminder(case["determined_last_day"])
                bump(k)
        st = statement_of(case["id"])
        if st is not None and st["status"] in ("APPROVED", "DISBURSED", "LATE"):
            case["status"] = "CLEARANCE_IN_PROGRESS"
        else:
            case["status"] = "PAYROLL_PENDING"
        changed = True
    if case["status"] == "CLEARANCE_IN_PROGRESS" and ready_gate(case):
        case["status"] = "READY_TO_CLOSE"
        pl = plan_of(case["id"])
        if pl is not None and pl["status"] == "ACTIVE":
            pl["status"] = "INCOMPLETE_AT_CLOSE"
            bump(pl)
        changed = True
    if changed:
        bump(case)
    return changed


def after_task_mutation(case):
    """Recompute revocation posture, then reconcile the case."""
    posture = compute_revocation_posture(tasks_of(case["id"]))
    posture_changed = posture != case["revocation_posture"]
    if posture_changed:
        case["revocation_posture"] = posture
    transitioned = reconcile_case(case)
    if posture_changed and not transitioned:
        bump(case)


def after_asset_mutation(case):
    """Recompute asset posture, then reconcile the case."""
    posture = compute_asset_posture(assets_of(case["id"]))
    posture_changed = posture != case["asset_posture"]
    if posture_changed:
        case["asset_posture"] = posture
    transitioned = reconcile_case(case)
    if posture_changed and not transitioned:
        bump(case)


def after_session_mutation(plan):
    """calc_kt_progress: recompute completed count; auto-complete the plan."""
    count = sum(1 for s in sessions_of(plan["id"]) if s["status"] == "COMPLETED")
    changed = count != plan["completed_session_count"]
    plan["completed_session_count"] = count
    if (plan["status"] == "ACTIVE"
            and plan["required_session_count"] > 0
            and count >= plan["required_session_count"]):
        plan["status"] = "COMPLETE"
        changed = True
    if changed:
        bump(plan)
    case = DB["cases"].get(plan["offboarding_case_id"])
    if case is not None:
        reconcile_case(case)


def apply_deduction_cascade(case):
    """After a default: recompute case total and refresh a live statement."""
    total_changed = False
    new_total = compute_deduction_total(case["id"])
    if new_total != case["deduction_total_cents"]:
        case["deduction_total_cents"] = new_total
        total_changed = True
    st = statement_of(case["id"])
    if st is not None and st["status"] in ("CALCULATED", "APPROVED"):
        ded, net = calc_final_net_pay(
            st["regular_wages_cents"], st["pto_payout_cents"], case["deduction_total_cents"]
        )
        if ded != st["deduction_total_cents"] or net != st["net_pay_cents"]:
            st["deduction_total_cents"] = ded
            st["net_pay_cents"] = net
            bump(st)
    return total_changed


# --------------------------------------------------------------------------
# System scheduler sweep — fires every due time-based transition to fixpoint
# --------------------------------------------------------------------------
def _lower_siblings_terminal(task):
    for t in tasks_of(task["offboarding_case_id"]):
        if t["id"] == task["id"]:
            continue
        if t["sequence_rank"] < task["sequence_rank"] and t["status"] not in ("VERIFIED", "WAIVED"):
            return False
    return True


def sweep():
    now = now_dt()
    while True:
        changed = False
        # Revocation tasks -> READY (ordered by rank so gates release in order)
        ordered = sorted(DB["tasks"].values(), key=lambda t: (t["sequence_rank"], t["_seq"]))
        for t in ordered:
            if (t["status"] in ("PENDING", "RETRY_SCHEDULED")
                    and t["scheduled_at"] is not None
                    and now >= t["scheduled_at"]
                    and _lower_siblings_terminal(t)):
                case = DB["cases"].get(t["offboarding_case_id"])
                if case is None or case["status"] in ("CLOSED", "VOIDED"):
                    continue
                t["status"] = "READY"
                bump(t)
                changed = True
                after_task_mutation(case)
        # Exit interviews -> NO_SHOW
        for iv in DB["interviews"].values():
            if iv["status"] == "SCHEDULED" and now > iv["scheduled_end"]:
                iv["status"] = "NO_SHOW"
                bump(iv)
                changed = True
                case = DB["cases"].get(iv["offboarding_case_id"])
                if case is not None:
                    reconcile_case(case)
        # KT sessions -> NO_SHOW
        for s in DB["sessions"].values():
            if s["status"] == "SCHEDULED" and now > s["scheduled_end"]:
                s["status"] = "NO_SHOW"
                bump(s)
                changed = True
                plan = DB["plans"].get(s["knowledge_transfer_plan_id"])
                if plan is not None:
                    after_session_mutation(plan)
        # Asset items TRACKED -> OVERDUE
        for a in DB["assets"].values():
            if (a["status"] == "TRACKED"
                    and a["return_due_at"] is not None
                    and now > a["return_due_at"]):
                a["status"] = "OVERDUE"
                bump(a)
                changed = True
                case = DB["cases"].get(a["offboarding_case_id"])
                if case is not None:
                    after_asset_mutation(case)
        # Benefits notices QUEUED -> FAILED
        for n in DB["notices"].values():
            if n["status"] == "QUEUED" and n["send_by"] is not None and now > n["send_by"]:
                n["status"] = "FAILED"
                n["failure_count"] += 1
                bump(n)
                changed = True
        # Covenant reminders PENDING -> REMINDED
        for k in DB["acks"].values():
            if (k["status"] == "PENDING"
                    and k["remind_at"] is not None
                    and now >= k["remind_at"]):
                k["status"] = "REMINDED"
                bump(k)
                changed = True
        # Approved statements -> LATE
        for st in DB["statements"].values():
            if st["status"] == "APPROVED" and st["due_at"] is not None and now > st["due_at"]:
                st["status"] = "LATE"
                case = DB["cases"].get(st["offboarding_case_id"])
                wage = case["hourly_wage_cents"] if case is not None else 0
                st["late_penalty_cents"] = calc_late_penalty(st["due_at"], now, wage)
                bump(st)
                changed = True
        if not changed:
            break
