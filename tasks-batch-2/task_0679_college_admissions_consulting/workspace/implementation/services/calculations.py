"""Calculation rules per SCAFFOLD §1.3 / PRD §3."""
from decimal import Decimal, ROUND_HALF_UP

from db import store


def _round_half_up(value, places):
    """Round a numeric value half-up to `places` decimal places, return float."""
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal('0.01')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


def _round_half_up_cents(value):
    """Round a numeric value half-up to a whole integer (cents)."""
    d = Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(d)


TIER_WEIGHT = {1: 1.0, 2: 0.7, 3: 0.4, 4: 0.2}


# --------------------------------------------------------------------------
# student_profile_strength
# --------------------------------------------------------------------------
def compute_profile_strength(student):
    gpa = student.get("gpa", 0.0)
    sat_total = student.get("sat_total", 0)

    gpa_component = (gpa / 4.0) * 40.0
    if sat_total == 0:
        sat_component = 0.0
    else:
        sat_component = ((sat_total - 400) / 1200.0) * 30.0
    academics = gpa_component + sat_component

    raw_activity = 0.0
    for act in store.activities.values():
        if act.get("student_id") != student["id"]:
            continue
        hpw = act.get("hours_per_week", 0)
        wpy = act.get("weeks_per_year", 0)
        tier = act.get("tier", 4)
        raw_activity += (hpw * wpy / 100.0) * TIER_WEIGHT.get(tier, 0.0)
    resume = min(30.0, raw_activity)

    academics_r = _round_half_up(academics, 2)
    resume_r = _round_half_up(resume, 2)
    total = _round_half_up(academics_r + resume_r, 2)
    return total


def recompute_profile_strength(student):
    student["profile_strength"] = compute_profile_strength(student)
    # admit_probability/classification for the student's items depend on this.
    recompute_student_school_items(student)


# --------------------------------------------------------------------------
# admit_probability + school_classification
# --------------------------------------------------------------------------
def compute_admit_probability(item, student):
    admit_rate = item.get("admit_rate")
    median_sat = item.get("median_sat")
    sat_total = student.get("sat_total", 0)
    profile_strength = student.get("profile_strength", 0)

    base = admit_rate
    if sat_total == 0:
        sat_gap = 0
    else:
        sat_gap = sat_total - median_sat

    if sat_gap >= 100:
        mult = 1.6
    elif sat_gap >= 0:
        mult = 1.0 + (sat_gap / 100.0) * 0.6
    elif sat_gap > -100:
        mult = 1.0 + (sat_gap / 100.0) * 0.5
    else:
        mult = 0.5

    strength_bonus = (profile_strength - 50) / 100.0 * 0.3
    raw = base * mult + strength_bonus
    clamped = max(0.0, min(1.0, raw))
    return _round_half_up(clamped, 4)


def compute_classification(admit_probability):
    if admit_probability >= 0.60:
        return "SAFETY"
    if admit_probability < 0.20:
        return "REACH"
    return "TARGET"


def recompute_school_item(item, student):
    p = compute_admit_probability(item, student)
    item["admit_probability"] = p
    item["classification"] = compute_classification(p)


def recompute_student_school_items(student):
    from common import touch
    for item in store.school_list_items.values():
        if item.get("student_id") != student["id"]:
            continue
        old_p = item.get("admit_probability")
        old_c = item.get("classification")
        recompute_school_item(item, student)
        # Recompute is a mutation only if values actually changed.
        if item.get("admit_probability") != old_p or item.get("classification") != old_c:
            touch(item)


# --------------------------------------------------------------------------
# list_balance_lock
# --------------------------------------------------------------------------
def compute_list_locked(student):
    selected = [
        it for it in store.school_list_items.values()
        if it.get("student_id") == student["id"] and it.get("status") == "SELECTED"
    ]
    n_safety = sum(1 for it in selected if it.get("classification") == "SAFETY")
    n_total = len(selected)
    n_ed = sum(1 for it in selected if it.get("round") == "ED")
    return (n_safety >= 1) and (n_total >= 3) and (n_ed <= 1)


def recompute_list_locked(student):
    student["list_locked"] = compute_list_locked(student)


# --------------------------------------------------------------------------
# retainer_ledger + projected_retainer_balance
# --------------------------------------------------------------------------
def compute_ledger(contract):
    charged = 0
    credited = 0
    for entry in store.billing_entries.values():
        if entry.get("contract_id") != contract["id"]:
            continue
        if entry.get("entry_type") == "CHARGE":
            charged += entry.get("amount_cents", 0)
        elif entry.get("entry_type") == "CREDIT":
            credited += entry.get("amount_cents", 0)
    balance = credited - charged
    return charged, credited, balance


def compute_pending_task_cost(student_id):
    total = 0
    # applications belonging to this student
    app_ids = {
        a["id"] for a in store.applications.values()
        if a.get("student_id") == student_id
    }
    for task in store.application_tasks.values():
        if task.get("application_id") not in app_ids:
            continue
        if task.get("status") not in ("OPEN", "IN_PROGRESS", "BLOCKED"):
            continue
        if task.get("task_type") == "ESSAY":
            continue
        cost = task.get("estimated_cost_cents", 0)
        if cost > 0:
            total += cost
    return total


def recompute_contract_balances(contract):
    charged, credited, balance = compute_ledger(contract)
    contract["charged_cents"] = charged
    contract["credited_cents"] = credited
    contract["retainer_balance_cents"] = balance
    pending = compute_pending_task_cost(contract.get("student_id"))
    contract["projected_balance_cents"] = balance - pending


def recompute_balances_for_student(student_id):
    """Recompute projected balance for the student's ACTIVE/relevant contracts.
    Projected balance depends on the student's open tasks, so any contract for
    the student is refreshed."""
    from common import touch
    for contract in store.contracts.values():
        if contract.get("student_id") != student_id:
            continue
        old_proj = contract.get("projected_balance_cents")
        old_charged = contract.get("charged_cents")
        old_credited = contract.get("credited_cents")
        old_bal = contract.get("retainer_balance_cents")
        recompute_contract_balances(contract)
        if (contract.get("projected_balance_cents") != old_proj
                or contract.get("charged_cents") != old_charged
                or contract.get("credited_cents") != old_credited
                or contract.get("retainer_balance_cents") != old_bal):
            touch(contract)


# --------------------------------------------------------------------------
# appointment_billed_amount
# --------------------------------------------------------------------------
def compute_billed_minutes(start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    return int(seconds // 60)


def compute_appointment_amount(billed_minutes, hourly_rate_cents):
    raw = (billed_minutes / 60.0) * hourly_rate_cents
    return _round_half_up_cents(raw)


# --------------------------------------------------------------------------
# net_aid_amount
# --------------------------------------------------------------------------
COORDINATION_CAP_CENTS = 4000000
TYPE_RANK = {"MERIT": 0, "EXTERNAL": 1, "NEED": 2}


def recompute_net_aid(student_id):
    from common import touch
    awards = [
        a for a in store.scholarships.values()
        if a.get("student_id") == student_id
    ]
    accepted = [a for a in awards if a.get("status") == "ACCEPTED"]
    accepted.sort(key=lambda a: (TYPE_RANK.get(a.get("award_type"), 99), a.get("created_at", ""), a.get("id", "")))

    running = 0
    accepted_ids = set()
    for award in accepted:
        allow = min(award.get("gross_amount_cents", 0), COORDINATION_CAP_CENTS - running)
        if allow < 0:
            allow = 0
        new_net = allow
        running += allow
        accepted_ids.add(award["id"])
        _set_net(award, new_net, touch)

    for award in awards:
        if award["id"] in accepted_ids:
            continue
        status = award.get("status")
        if status == "OFFERED":
            _set_net(award, award.get("gross_amount_cents", 0), touch)
        elif status == "DECLINED":
            _set_net(award, 0, touch)


def _set_net(award, value, touch_fn):
    if award.get("net_amount_cents") != value:
        award["net_amount_cents"] = value
        touch_fn(award)
