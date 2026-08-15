"""Core domain services: ledger, balances, tiers, budget posture, awards,
manager chains, and the ordered clock-advance sweep."""
from datetime import timedelta, date, datetime, timezone

import db
from db import now, today, touch

# Tier thresholds (SCAFFOLD calculations.tier_assignment; inclusive bounds)
SILVER_AT = 1000
GOLD_AT = 5000
PLATINUM_AT = 20000

# Budget posture thresholds in basis points
RESTRICTED_THRESHOLD_BP = 8500
EXHAUSTED_THRESHOLD_BP = 10000

RESTRICTED_APPROVAL_CAP_POINTS = 500

NON_TERMINAL_NOMINATION_STATUSES = {"PENDING_REVIEW", "RETURNED_FOR_REVISION"}


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def post_ledger(employee, entry_type, points, reference_type, reference_id,
                idem_key, note):
    entry = {
        "id": db.new_id(),
        "employee_id": employee["id"],
        "entry_type": entry_type,
        "points": points,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "idempotency_key": idem_key,
        "note": note,
        "created_at": now(),
    }
    db.ledger.append(entry)
    return entry


def recompute_tier(employee):
    pts = employee["lifetime_granted_points"]
    if pts >= PLATINUM_AT:
        tier = "PLATINUM"
    elif pts >= GOLD_AT:
        tier = "GOLD"
    elif pts >= SILVER_AT:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    employee["recognition_tier"] = tier


# Employee balance mutations (derived counters maintained transactionally).
def emp_grant(emp, points):
    emp["available_points"] += points
    emp["lifetime_granted_points"] += points
    recompute_tier(emp)
    touch(emp)


def emp_hold(emp, points):
    emp["available_points"] -= points
    emp["held_points"] += points
    touch(emp)


def emp_settle(emp, points):
    emp["held_points"] -= points
    emp["lifetime_redeemed_points"] += points
    touch(emp)


def emp_refund_from_held(emp, points):
    emp["held_points"] -= points
    emp["available_points"] += points
    touch(emp)


def emp_refund_to_available(emp, points):
    # Return refund: credits available points and removes the refunded points
    # from lifetime_redeemed (the order's redeemed residue is its fee).
    emp["available_points"] += points
    emp["lifetime_redeemed_points"] -= points
    touch(emp)


def emp_restocking_fee(emp, fee):
    # The fee moves out of escrow into spent; it stays counted in
    # lifetime_redeemed_points precisely because the return refund only
    # removed (points_total - fee). No counter change here.
    touch(emp)


def emp_expiry(emp, points):
    emp["available_points"] -= points
    emp["lifetime_expired_points"] += points
    touch(emp)


def emp_clawback(emp, points):
    emp["available_points"] -= points
    emp["lifetime_granted_points"] -= points
    recompute_tier(emp)
    touch(emp)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def recompute_posture(budget):
    """Posture is a stored derived column recomputed after every mutation of
    reserved/committed/allocated and on clock advance. CLOSED is terminal and
    wins over utilization; boundaries are inclusive (>=)."""
    if budget["posture"] == "CLOSED":
        return
    if today() >= budget["period_end_date"]:
        budget["posture"] = "CLOSED"
        budget["reserved_points"] = 0
        return
    util_bp = ((budget["reserved_points"] + budget["committed_points"]) * 10000
               // budget["allocated_points"])
    if util_bp >= EXHAUSTED_THRESHOLD_BP:
        budget["posture"] = "EXHAUSTED"
    elif util_bp >= RESTRICTED_THRESHOLD_BP:
        budget["posture"] = "RESTRICTED"
    else:
        budget["posture"] = "OPEN"


def budget_mutated(budget):
    recompute_posture(budget)
    touch(budget)


def select_budget(program_id, department_id, on_date):
    """The (unique, overlap-free) budget whose half-open window contains the
    given date. Returns None when no window matches or the match is CLOSED."""
    for b in db.budgets.values():
        if b["program_id"] != program_id or b["department_id"] != department_id:
            continue
        if b["period_start_date"] <= on_date < b["period_end_date"]:
            if b["posture"] == "CLOSED":
                return None
            return b
    return None


def budget_for_award(award, employee):
    """Budget whose window contains award.granted_at for the employee's
    department (used for committed release on expiry/revocation)."""
    grant_date = award["granted_at"].date()
    for b in db.budgets.values():
        if b["program_id"] != award["program_id"]:
            continue
        if b["department_id"] != employee["department_id"]:
            continue
        if b["period_start_date"] <= grant_date < b["period_end_date"]:
            return b
    return None


def budget_gate_check(budget, points_requested, nomination=None):
    """Two-stage submission gate. Returns an error pair to raise, or None.

    Stage 1 (RESTRICTED policy cap): points_requested <= 500 while RESTRICTED.
    Stage 2 (capacity): reserved + committed + requested <= allocated (== ok).
    When re-running for a resubmission, the nomination's existing reservation
    is excluded from the prospective sum.
    """
    from errors import raise_err, ERR_BUDGET_RESTRICTED_AMOUNT, ERR_BUDGET_EXHAUSTED
    if budget["posture"] == "RESTRICTED" and points_requested > RESTRICTED_APPROVAL_CAP_POINTS:
        raise_err(ERR_BUDGET_RESTRICTED_AMOUNT,
                  "Budget posture RESTRICTED caps points_requested at %d"
                  % RESTRICTED_APPROVAL_CAP_POINTS)
    reserved = budget["reserved_points"]
    if nomination is not None and nomination["status"] in NON_TERMINAL_NOMINATION_STATUSES \
            and nomination["budget_id"] == budget["id"]:
        reserved -= nomination["points_requested"]
    prospective = reserved + budget["committed_points"] + points_requested
    if prospective > budget["allocated_points"]:
        raise_err(ERR_BUDGET_EXHAUSTED,
                  "Budget capacity exceeded: %d > %d"
                  % (prospective, budget["allocated_points"]))


# ---------------------------------------------------------------------------
# Manager chain
# ---------------------------------------------------------------------------

def in_manager_chain(approver_id, nominee):
    """True when approver_id appears in the nominee's transitive manager chain."""
    seen = set()
    cur = nominee.get("manager_id")
    while cur:
        if cur == approver_id:
            return True
        if cur in seen:
            break
        seen.add(cur)
        nxt = db.employees.get(cur)
        if nxt is None:
            break
        cur = nxt.get("manager_id")
    return False


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

def active_awards(employee_id):
    """Employee's ACTIVE awards in FIFO order: granted_at ASC, tie created_at
    ASC (insertion order is stable for exact ties; ids are never used)."""
    rows = [a for a in db.awards.values()
            if a["employee_id"] == employee_id and a["status"] == "ACTIVE"]
    rows.sort(key=lambda a: (a["granted_at"], a["created_at"]))
    return rows


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    if m == 12:
        last = date(y, 12, 31).day
    else:
        last = (date(y, m + 1, 1) - timedelta(days=1)).day
    return dt.replace(year=y, month=m, day=min(dt.day, last))


def create_award(program_id, employee, points, source, nomination_id=None,
                 revoked_by_flag_id=None):
    award = {
        "id": db.new_id(),
        "program_id": program_id,
        "employee_id": employee["id"],
        "nomination_id": nomination_id,
        "source": source,
        "points": points,
        "points_remaining": points,
        "status": "ACTIVE",
        "granted_at": now(),
        "expires_at": add_months(now(), 12),
        "revoked_by_flag_id": revoked_by_flag_id,
    }
    db.stamp(award)
    db.awards[award["id"]] = award
    return award


def consume_awards_fifo(employee, points):
    """Settlement consumption across ACTIVE awards, granted_at ASC then
    created_at ASC; awards drained to zero become FULLY_REDEEMED."""
    remaining = points
    for award in active_awards(employee["id"]):
        if remaining <= 0:
            break
        take = min(award["points_remaining"], remaining)
        if take <= 0:
            continue
        award["points_remaining"] -= take
        remaining -= take
        if award["points_remaining"] == 0:
            award["status"] = "FULLY_REDEEMED"
        touch(award)
    return remaining  # 0 in normal operation (balance was pre-checked)


def release_committed_for_award(award, employee, points):
    """Release committed points on the award's originating budget when that
    budget is not CLOSED; recompute posture."""
    b = budget_for_award(award, employee)
    if b is not None and b["posture"] != "CLOSED":
        b["committed_points"] = max(0, b["committed_points"] - points)
        budget_mutated(b)


def revoke_award(award, employee, flag_id=None, idem_base=None):
    """Revocation side effects (PRD section 3.4): CLAWBACK ledger entry,
    budget committed release, tier recompute, zeroed points_remaining."""
    pts = award["points_remaining"]
    ref_type = "ABUSE_FLAG" if flag_id else "AWARD"
    ref_id = flag_id if flag_id else award["id"]
    key = (idem_base or ("revoke:%s" % award["id"])) + ":CLAWBACK"
    post_ledger(employee, "CLAWBACK", -pts, ref_type, ref_id, key,
                "Clawback of %d remaining points" % pts)
    emp_clawback(employee, pts)
    release_committed_for_award(award, employee, pts)
    award["points_remaining"] = 0
    award["status"] = "REVOKED"
    award["revoked_by_flag_id"] = flag_id
    touch(award)


def expire_award(award, employee):
    """Expiry side effects: EXPIRY ledger entry, budget committed release,
    zeroed points_remaining, status EXPIRED."""
    pts = award["points_remaining"]
    post_ledger(employee, "EXPIRY", -pts, "AWARD", award["id"],
                "system:EXPIRY:%s" % award["id"],
                "Expiry of %d remaining points" % pts)
    emp_expiry(employee, pts)
    release_committed_for_award(award, employee, pts)
    award["points_remaining"] = 0
    award["status"] = "EXPIRED"
    touch(award)


# ---------------------------------------------------------------------------
# Abuse flags (system-raised)
# ---------------------------------------------------------------------------

def raise_system_flag(employee_id, program_id, rule_code, details):
    flag = {
        "id": db.new_id(),
        "employee_id": employee_id,
        "program_id": program_id,
        "rule_code": rule_code,
        "details": details,
        "status": "OPEN",
        "raised_by": "system",
        "resolved_by": None,
    }
    db.stamp(flag)
    db.abuse_flags[flag["id"]] = flag
    return flag


# ---------------------------------------------------------------------------
# Clock-advance sweep (PRD section 2.5 — ordering is load-bearing)
# ---------------------------------------------------------------------------

def run_clock_sweep(new_now):
    """(1) nomination auto-expiry, (2) award expiry sweep, (3) budget close."""
    # 1. Nominations past review_deadline -> EXPIRED (strictly before now).
    for n in list(db.nominations.values()):
        if n["status"] in NON_TERMINAL_NOMINATION_STATUSES \
                and n["review_deadline"] is not None \
                and n["review_deadline"] < new_now:
            b = db.budgets.get(n["budget_id"])
            if b is not None and b["posture"] != "CLOSED":
                b["reserved_points"] = max(0, b["reserved_points"] - n["points_requested"])
                budget_mutated(b)
            n["status"] = "EXPIRED"
            touch(n)

    # 2. Awards with expires_at <= now -> EXPIRED (FIFO order).
    expiring = [a for a in db.awards.values()
                if a["status"] == "ACTIVE" and a["expires_at"] <= new_now]
    expiring.sort(key=lambda a: (a["granted_at"], a["created_at"]))
    for award in expiring:
        emp = db.employees.get(award["employee_id"])
        if emp is not None:
            expire_award(award, emp)

    # 3. Budgets whose period_end_date has been reached -> CLOSED.
    d = new_now.date()
    for b in list(db.budgets.values()):
        if b["posture"] != "CLOSED" and d >= b["period_end_date"]:
            b["reserved_points"] = 0
            b["posture"] = "CLOSED"
            touch(b)
