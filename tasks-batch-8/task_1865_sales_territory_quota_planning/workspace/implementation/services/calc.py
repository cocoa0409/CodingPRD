"""Calculation engines per SCAFFOLD §1.3. All money in integer cents.

Implements:
  - allocation_largest_remainder
  - assignment_resolution
  - rep_base_share / rep_final_share
  - ramp_quota
  - reconciliation_final
  - credit_split_at_booking
  - credit_transition_transfer
  - attainment_rollup
  - coverage_model
  - dispute_sla_escalation
And the shared cascade machinery (retained quotas, share recompute, pct recompute).
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store, logical_today
from util import touch


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_plan_year(p):
    return {
        "id": p["id"],
        "label": p["label"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "company_target_cents": p["company_target_cents"],
        "productivity_per_rep_cents": p["productivity_per_rep_cents"],
        "reconciliation_policy": p["reconciliation_policy"],
        "credit_transition_policy": p["credit_transition_policy"],
        "lock_date": p["lock_date"],
        "status": p["status"],
        "communicated_at": p["communicated_at"],
        "locked_at": p["locked_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_territory(t):
    return {
        "id": t["id"],
        "plan_year_id": t["plan_year_id"],
        "parent_territory_id": t["parent_territory_id"],
        "name": t["name"],
        "potential_cents": t["potential_cents"],
        "headcount_capacity": t["headcount_capacity"],
        "assigned_quota_cents": t["assigned_quota_cents"],
        "final_quota_cents": t["final_quota_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_rule(r):
    return {
        "id": r["id"],
        "plan_year_id": r["plan_year_id"],
        "rule_type": r["rule_type"],
        "priority": r["priority"],
        "country_code": r["country_code"],
        "state_code": r["state_code"],
        "segment": r["segment"],
        "named_account_id": r["named_account_id"],
        "territory_id": r["territory_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_account(a):
    return {
        "id": a["id"],
        "plan_year_id": a["plan_year_id"],
        "name": a["name"],
        "country_code": a["country_code"],
        "state_code": a["state_code"],
        "segment": a["segment"],
        "annual_potential_cents": a["annual_potential_cents"],
        "assigned_territory_id": a["assigned_territory_id"],
        "assignment_source": a["assignment_source"],
        "assignment_rule_id": a["assignment_rule_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_rep(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "hire_date": r["hire_date"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_ramp_schedule(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "multipliers": s["multipliers"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_rep_assignment(a):
    return {
        "id": a["id"],
        "plan_year_id": a["plan_year_id"],
        "rep_id": a["rep_id"],
        "territory_id": a["territory_id"],
        "ramp_schedule_id": a["ramp_schedule_id"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "status": a["status"],
        "base_quota_cents": a["base_quota_cents"],
        "ramped_quota_cents": a["ramped_quota_cents"],
        "final_quota_cents": a["final_quota_cents"],
        "attainment_cents": a["attainment_cents"],
        "attainment_pct": a["attainment_pct"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_allocation(al):
    return {
        "id": al["id"],
        "plan_year_id": al["plan_year_id"],
        "scope_territory_id": al["scope_territory_id"],
        "pool_cents": al["pool_cents"],
        "status": al["status"],
        "results": al["results"],
        "created_at": al["created_at"],
        "updated_at": al["updated_at"],
        "version": al["version"],
    }


def ser_submission(s):
    return {
        "id": s["id"],
        "plan_year_id": s["plan_year_id"],
        "territory_id": s["territory_id"],
        "submitted_by_rep_id": s["submitted_by_rep_id"],
        "proposed_quota_cents": s["proposed_quota_cents"],
        "rationale": s["rationale"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_reconciliation_run(r):
    return {
        "id": r["id"],
        "plan_year_id": r["plan_year_id"],
        "policy_used": r["policy_used"],
        "results": r["results"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_change_request(c):
    return {
        "id": c["id"],
        "plan_year_id": c["plan_year_id"],
        "account_id": c["account_id"],
        "from_territory_id": c["from_territory_id"],
        "to_territory_id": c["to_territory_id"],
        "effective_date": c["effective_date"],
        "reason": c["reason"],
        "created_by_user_id": c["created_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "quota_transfer_cents": c["quota_transfer_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_credit_event(e):
    return {
        "id": e["id"],
        "plan_year_id": e["plan_year_id"],
        "account_id": e["account_id"],
        "rep_id": e["rep_id"],
        "event_type": e["event_type"],
        "amount_cents": e["amount_cents"],
        "booking_date": e["booking_date"],
        "source_change_request_id": e["source_change_request_id"],
        "parent_credit_event_id": e["parent_credit_event_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "plan_year_id": d["plan_year_id"],
        "account_id": d["account_id"],
        "claimant_territory_id": d["claimant_territory_id"],
        "filed_by_rep_id": d["filed_by_rep_id"],
        "reason": d["reason"],
        "filed_date": d["filed_date"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


# ---------------------------------------------------------------------------
# Retained quotas and share splits
# ---------------------------------------------------------------------------

def _children_of(territory_id, status="ACTIVE"):
    kids = [t for t in store.territories.values()
            if t.get("parent_territory_id") == territory_id and t["status"] == status]
    kids.sort(key=lambda t: (t["created_at"], t["id"]))
    return kids


def retained_topdown(territory):
    """assigned - sum(ACTIVE children's assigned). None while assigned is None."""
    if territory["assigned_quota_cents"] is None:
        return None
    child_sum = sum(
        (c["assigned_quota_cents"] or 0) for c in _children_of(territory["id"])
    )
    return territory["assigned_quota_cents"] - child_sum


def retained_final(territory):
    """final - sum(ACTIVE children's finals, 0 for null child final)."""
    if territory["final_quota_cents"] is None:
        return None
    child_sum = sum(
        (c["final_quota_cents"] or 0) for c in _children_of(territory["id"])
    )
    return territory["final_quota_cents"] - child_sum


def _split_equal(amount, n):
    """floor + remainder one cent each in given order. Returns (base, remainder)."""
    base = amount // n
    rem = amount - base * n
    return base, rem


def ramp_quota(base_annual_cents, hire_date_str, plan_start_str, multipliers):
    """Pinned two-step rounding per ramp_quota calculation.

    multipliers: list of 12 floats/Decimals, or None (fully ramped -> all 1.00).
    Returns integer cents.
    """
    if base_annual_cents is None:
        return None
    B = Decimal(base_annual_cents)
    monthly_base = int((B / Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    sy, sm, _ = int(plan_start_str[0:4]), int(plan_start_str[5:7]), int(plan_start_str[8:10])
    hy, hm, hd = int(hire_date_str[0:4]), int(hire_date_str[5:7]), int(hire_date_str[8:10])

    M = multipliers if multipliers is not None else [1.0] * 12

    total = 0
    for m in range(1, 13):
        plan_abs = sy * 12 + (sm + m - 1)
        hire_abs = hy * 12 + hm
        ti = plan_abs - hire_abs + 1
        if hd > 15:
            ti -= 1
        if ti <= 0:
            mult = Decimal("0")
        elif ti >= 13:
            mult = Decimal("1")
        else:
            mult = Decimal(str(M[ti - 1]))
        contribution = int((Decimal(monthly_base) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += contribution
    return total


def _assignment_multipliers(assignment):
    rsid = assignment.get("ramp_schedule_id")
    if rsid is None:
        return None
    sched = store.ramp_schedules.get(rsid)
    if sched is None:
        return None
    return sched["multipliers"]


def _recompute_assignment_shares_for_territory(territory):
    """rep_base_share + ramp for ACTIVE assignments on a territory.

    Also recomputes final shares when plan is reconciled-or-later, and
    attainment_pct for all assignments on the territory.
    ENDED assignments are frozen — never touched.
    """
    plan = store.plan_years.get(territory["plan_year_id"])
    actives = [a for a in store.rep_assignments.values()
               if a["territory_id"] == territory["id"] and a["status"] == "ACTIVE"]
    actives.sort(key=lambda a: (a["created_at"], a["id"]))

    retained = retained_topdown(territory)
    plan_reconciled = plan is not None and plan["status"] in ("RECONCILED", "COMMUNICATED", "LOCKED")

    if not actives:
        # No ACTIVE assignments: existing values stand unchanged; nothing to do.
        return

    if retained is None:
        for a in actives:
            if a["base_quota_cents"] is not None or a["ramped_quota_cents"] is not None:
                a["base_quota_cents"] = None
                a["ramped_quota_cents"] = None
                touch(a)
            elif a["base_quota_cents"] is None:
                # still bump nothing; null is the steady state — but per spec,
                # "While retained is null, every member's base share is null".
                # Keep them null without version churn.
                pass
    else:
        n = len(actives)
        base, rem = _split_equal(retained, n)
        for i, a in enumerate(actives):
            share = base + (1 if i < rem else 0)
            rep = store.reps.get(a["rep_id"])
            new_ramped = ramp_quota(share, rep["hire_date"], plan["start_date"],
                                    _assignment_multipliers(a)) if rep else None
            if a["base_quota_cents"] != share or a["ramped_quota_cents"] != new_ramped:
                a["base_quota_cents"] = share
                a["ramped_quota_cents"] = new_ramped
                touch(a)

    if plan_reconciled:
        _recompute_final_shares_for_territory(territory)
    else:
        # Pre-reconciliation: attainment_pct denominator is ramped_quota_cents.
        for a in actives:
            _recompute_attainment_pct(a)


def _recompute_final_shares_for_territory(territory):
    """rep_final_share + ramp_quota -> final_quota_cents for ACTIVE assignments."""
    plan = store.plan_years.get(territory["plan_year_id"])
    actives = [a for a in store.rep_assignments.values()
               if a["territory_id"] == territory["id"] and a["status"] == "ACTIVE"]
    actives.sort(key=lambda a: (a["created_at"], a["id"]))
    if not actives:
        return
    retained = retained_final(territory)
    if retained is None:
        for a in actives:
            if a["final_quota_cents"] is not None:
                a["final_quota_cents"] = None
                touch(a)
            _recompute_attainment_pct(a)
        return
    n = len(actives)
    base, rem = _split_equal(retained, n)
    for i, a in enumerate(actives):
        share = base + (1 if i < rem else 0)
        rep = store.reps.get(a["rep_id"])
        new_final = ramp_quota(share, rep["hire_date"], plan["start_date"],
                               _assignment_multipliers(a)) if rep else None
        if a["final_quota_cents"] != new_final:
            a["final_quota_cents"] = new_final
            touch(a)
        _recompute_attainment_pct(a)


def recompute_territory_assignment_cascade(territory_ids):
    """Hop-2/3 cascade over a set of territory ids (dedup, stable order)."""
    seen = []
    for tid in territory_ids:
        if tid not in seen:
            seen.append(tid)
    for tid in seen:
        t = store.territories.get(tid)
        if t is not None:
            _recompute_assignment_shares_for_territory(t)


def _recompute_attainment_pct(assignment):
    plan = store.plan_years.get(assignment["plan_year_id"])
    if plan is None:
        return
    if plan["status"] in ("RECONCILED", "COMMUNICATED", "LOCKED"):
        denom = assignment["final_quota_cents"]
    else:
        denom = assignment["ramped_quota_cents"]
    if denom is None or denom == 0:
        new_pct = None
    else:
        val = (Decimal(assignment["attainment_cents"]) * Decimal(100)) / Decimal(denom)
        new_pct = float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if assignment["attainment_pct"] != new_pct:
        assignment["attainment_pct"] = new_pct
        touch(assignment)


def recompute_attainment_rollup(rep_id, plan_year_id):
    """attainment_cents = signed sum of POSTED events for rep+plan; pct recompute
    for every assignment of that rep in that plan."""
    total = 0
    for e in store.credit_events.values():
        if (e["rep_id"] == rep_id and e["plan_year_id"] == plan_year_id
                and e["status"] == "POSTED"):
            total += e["amount_cents"]
    for a in store.rep_assignments.values():
        if a["rep_id"] == rep_id and a["plan_year_id"] == plan_year_id:
            if a["attainment_cents"] != total:
                a["attainment_cents"] = total
                touch(a)
            _recompute_attainment_pct(a)


# ---------------------------------------------------------------------------
# allocation_largest_remainder
# ---------------------------------------------------------------------------

def allocation_largest_remainder(pool_cents, children):
    """children: ACTIVE child territories sorted by created_at ASC.
    Returns list of (child, allocated_cents) in created_at order."""
    if not children:
        return []
    W = sum(c["potential_cents"] for c in children)
    if W > 0:
        raws = [Fraction(pool_cents * c["potential_cents"], W) for c in children]
        shares = [r.numerator // r.denominator for r in raws]
        remainder = pool_cents - sum(shares)
        # order by fractional part DESC, tie-break created_at ASC (list already sorted)
        order = sorted(range(len(children)),
                       key=lambda i: (-(raws[i] - shares[i]), children[i]["created_at"], children[i]["id"]))
        for k in range(remainder):
            shares[order[k]] += 1
    else:
        n = len(children)
        base = pool_cents // n
        shares = [base] * n
        remainder = pool_cents - base * n
        for k in range(remainder):
            shares[k] += 1
    return list(zip(children, shares))


# ---------------------------------------------------------------------------
# assignment_resolution
# ---------------------------------------------------------------------------

def resolve_assignment(account):
    """Runs the named/geo passes; mutates the account and returns whether the
    assignment (territory, source, rule) changed."""
    plan_id = account["plan_year_id"]
    rules = [r for r in store.assignment_rules.values()
             if r["plan_year_id"] == plan_id and r["status"] == "ACTIVE"]

    # NAMED pass
    named = [r for r in rules
             if r["rule_type"] == "NAMED_ACCOUNT" and r["named_account_id"] == account["id"]]
    old = (account["assigned_territory_id"], account["assignment_source"], account["assignment_rule_id"])
    if named:
        winner = named[0]
        account["assigned_territory_id"] = winner["territory_id"]
        account["assignment_source"] = "NAMED_RULE"
        account["assignment_rule_id"] = winner["id"]
    else:
        # GEO pass
        candidates = []
        for r in rules:
            if r["rule_type"] != "GEO_SEGMENT":
                continue
            if r["country_code"] is not None and r["country_code"] != account["country_code"]:
                continue
            if r["state_code"] is not None and r["state_code"] != account["state_code"]:
                continue
            if r["segment"] is not None and r["segment"] != account["segment"]:
                continue
            specificity = sum(1 for f in ("country_code", "state_code", "segment") if r[f] is not None)
            candidates.append((specificity, r))
        if not candidates:
            account["assigned_territory_id"] = None
            account["assignment_source"] = "UNASSIGNED"
            account["assignment_rule_id"] = None
        else:
            candidates.sort(key=lambda cr: (-cr[0], cr[1]["priority"], cr[1]["created_at"], cr[1]["id"]))
            winner = candidates[0][1]
            account["assigned_territory_id"] = winner["territory_id"]
            account["assignment_source"] = "GEO_RULE"
            account["assignment_rule_id"] = winner["id"]
    new = (account["assigned_territory_id"], account["assignment_source"], account["assignment_rule_id"])
    return old != new


# ---------------------------------------------------------------------------
# reconciliation_final
# ---------------------------------------------------------------------------

def compute_reconciliation_results(plan):
    """One row per ACTIVE territory ordered by created_at ASC."""
    territories = [t for t in store.territories.values()
                   if t["plan_year_id"] == plan["id"] and t["status"] == "ACTIVE"]
    territories.sort(key=lambda t: (t["created_at"], t["id"]))
    policy = plan["reconciliation_policy"]
    results = []
    for t in territories:
        top_down = t["assigned_quota_cents"] if t["assigned_quota_cents"] is not None else 0
        locked = [s for s in store.submissions.values()
                  if s["plan_year_id"] == plan["id"] and s["territory_id"] == t["id"]
                  and s["status"] == "LOCKED_IN"]
        locked.sort(key=lambda s: (s["created_at"], s["id"]))
        bottom_up = locked[0]["proposed_quota_cents"] if locked else None

        if policy == "TOP_DOWN_WINS":
            final = top_down
            if bottom_up is None:
                escalated = False
            elif top_down == 0:
                escalated = bottom_up > 0
            else:
                escalated = abs(bottom_up - top_down) * 100 > top_down * 10
        else:  # BLENDED
            if bottom_up is None:
                final = top_down
                escalated = False
            elif top_down == 0:
                final = bottom_up
                escalated = bottom_up > 0
            elif abs(bottom_up - top_down) * 100 <= top_down * 10:
                final = int(((Decimal(top_down) + Decimal(bottom_up)) / Decimal(2)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP))
                escalated = False
            else:
                final = top_down
                escalated = True

        if top_down > 0 and bottom_up is not None:
            dev = (Decimal(bottom_up - top_down) * Decimal(100)) / Decimal(top_down)
            deviation_pct = float(dev.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        else:
            deviation_pct = None

        results.append({
            "territory_id": t["id"],
            "top_down_cents": top_down,
            "bottom_up_cents": bottom_up,
            "deviation_pct": deviation_pct,
            "final_cents": final,
            "escalated": escalated,
        })
    return results


# ---------------------------------------------------------------------------
# credit_split_at_booking
# ---------------------------------------------------------------------------

def credited_reps_for(territory_id, booking_date_str):
    """ACTIVE assignments whose half-open window covers booking_date."""
    out = []
    for a in store.rep_assignments.values():
        if a["territory_id"] != territory_id or a["status"] != "ACTIVE":
            continue
        if a["effective_from"] > booking_date_str:
            continue
        if a["effective_to"] is not None and booking_date_str >= a["effective_to"]:
            continue
        out.append(a)
    out.sort(key=lambda a: (a["created_at"], a["id"]))
    return out


def split_amount(amount_cents, n):
    base = amount_cents // n
    rem = amount_cents - base * n
    return [(base + (1 if i < rem else 0)) for i in range(n)]


# ---------------------------------------------------------------------------
# credit_transition_transfer
# ---------------------------------------------------------------------------

def run_credit_transition(plan, change_request, apply_date):
    """Hop 3 of change-request apply. Creates TRANSFER_OUT/TRANSFER_IN events."""
    from util import stamp_new

    account_id = change_request["account_id"]
    eff = date.fromisoformat(change_request["effective_date"])
    transition_month_start = date(eff.year, eff.month, 1)
    policy = plan["credit_transition_policy"]

    sources = [e for e in store.credit_events.values()
               if e["event_type"] == "BOOKING" and e["status"] == "POSTED"
               and e["account_id"] == account_id
               and transition_month_start.isoformat() <= e["booking_date"] <= apply_date.isoformat()]
    sources.sort(key=lambda e: (e["booking_date"], e["created_at"], e["id"]))

    to_territory_id = change_request["to_territory_id"]
    dest_assignments = [a for a in store.rep_assignments.values()
                        if a["territory_id"] == to_territory_id and a["status"] == "ACTIVE"]
    dest_assignments.sort(key=lambda a: (a["created_at"], a["id"]))

    affected_reps = set()

    for src in sources:
        A = src["amount_cents"]
        bdate = date.fromisoformat(src["booking_date"])
        in_transition_month = (bdate.year == eff.year and bdate.month == eff.month)
        if in_transition_month:
            if policy == "PRORATE_BY_DAY":
                days_in_month = monthrange(eff.year, eff.month)[1]
                new_days = days_in_month - eff.day + 1
                fraction = Fraction(new_days, days_in_month)
            else:  # MONTH_SNAPSHOT
                fraction = Fraction(1, 1) if eff.day <= 15 else Fraction(0, 1)
        else:
            fraction = Fraction(1, 1)

        out_amount = int((Decimal(A) * Decimal(fraction.numerator) / Decimal(fraction.denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if out_amount == 0:
            continue

        # TRANSFER_OUT on original rep
        ev_out = stamp_new({
            "plan_year_id": plan["id"],
            "account_id": account_id,
            "rep_id": src["rep_id"],
            "event_type": "TRANSFER_OUT",
            "amount_cents": -out_amount,
            "booking_date": apply_date.isoformat(),
            "source_change_request_id": change_request["id"],
            "parent_credit_event_id": src["id"],
            "status": "POSTED",
        })
        store.credit_events[ev_out["id"]] = ev_out
        affected_reps.add(src["rep_id"])

        # TRANSFER_IN distributed among destination ACTIVE reps
        k = len(dest_assignments)
        if k > 0:
            shares = split_amount(out_amount, k)
            for a, amt in zip(dest_assignments, shares):
                ev_in = stamp_new({
                    "plan_year_id": plan["id"],
                    "account_id": account_id,
                    "rep_id": a["rep_id"],
                    "event_type": "TRANSFER_IN",
                    "amount_cents": amt,
                    "booking_date": apply_date.isoformat(),
                    "source_change_request_id": change_request["id"],
                    "parent_credit_event_id": src["id"],
                    "status": "POSTED",
                })
                store.credit_events[ev_in["id"]] = ev_in
                affected_reps.add(a["rep_id"])

    for rep_id in affected_reps:
        recompute_attainment_rollup(rep_id, plan["id"])


# ---------------------------------------------------------------------------
# coverage_model
# ---------------------------------------------------------------------------

def coverage_report(plan):
    territories = [t for t in store.territories.values()
                   if t["plan_year_id"] == plan["id"] and t["assigned_quota_cents"] is not None]
    territories.sort(key=lambda t: (t["created_at"], t["id"]))
    rows = []
    total_required = 0
    total_active = 0
    for t in territories:
        retained = retained_topdown(t)
        active_rep_count = sum(1 for a in store.rep_assignments.values()
                               if a["territory_id"] == t["id"] and a["status"] == "ACTIVE")
        if retained and retained > 0:
            p = plan["productivity_per_rep_cents"]
            required = (retained + p - 1) // p  # ceil; exact multiples divide evenly
        else:
            required = 0
        gap = required - active_rep_count
        if retained == 0:
            status = "NO_QUOTA"
        elif active_rep_count == 0:
            status = "GAP"
        elif active_rep_count < required:
            status = "UNDERSTAFFED"
        else:
            status = "COVERED"
        total_required += required
        total_active += active_rep_count
        rows.append({
            "territory_id": t["id"],
            "retained_quota_cents": retained,
            "active_rep_count": active_rep_count,
            "required_headcount": required,
            "staffing_gap": gap,
            "coverage_status": status,
        })
    uncovered = sum(1 for a in store.accounts.values()
                    if a["plan_year_id"] == plan["id"] and a["assigned_territory_id"] is None)
    return {
        "plan_year_id": plan["id"],
        "territory_count": len(rows),
        "uncovered_account_count": uncovered,
        "total_required_headcount": total_required,
        "total_active_assignments": total_active,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# dispute_sla_escalation
# ---------------------------------------------------------------------------

REVIEW_SLA_DAYS = 7


def process_dispute_slas(plan):
    today = logical_today()
    overdue = []
    for d in store.disputes.values():
        if d["plan_year_id"] != plan["id"] or d["status"] != "FILED":
            continue
        filed = date.fromisoformat(d["filed_date"])
        if (today - filed).days > REVIEW_SLA_DAYS:
            overdue.append(d)
    overdue.sort(key=lambda d: (d["created_at"], d["id"]))
    ids = []
    for d in overdue:
        d["status"] = "ESCALATED"
        touch(d)
        ids.append(d["id"])
    return {"escalated_count": len(ids), "escalated_dispute_ids": ids}
