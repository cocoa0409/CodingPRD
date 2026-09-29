"""Derived-field reconciliation (PRD Sections 2.9, 2.10, 3.5, 3.7, 3.8, 3.9)."""
from decimal import Decimal

import calc
import config
import store

OPEN_REVIEW_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "REOPENED")
LIVE_ASSIGNMENT_STATUSES = ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED")
NON_TERMINAL_PLAN_STATUSES = ("DRAFT", "ACTIVE", "REVISION_REQUESTED")
ROSTER_TYPES = ("LEVEL", "COMPLEX")

CLEARANCE_FOR_TYPE = {
    "LEVEL": "LEVEL_ASSIGNMENT",
    "COMPLEX": "LEVEL_ASSIGNMENT",
    "REHAB": "REHAB_START",
}


# ------------------------------------------------------------------- collections
def reviews_of(affiliate_id):
    return [r for r in store.reviews.values() if r["affiliate_id"] == affiliate_id]


def agreements_of(affiliate_id):
    return [a for a in store.agreements.values() if a["affiliate_id"] == affiliate_id]


def active_agreement(affiliate_id):
    rows = [a for a in agreements_of(affiliate_id) if a["status"] == "ACTIVE"]
    rows = store.sorted_rows(rows)
    return rows[-1] if rows else None


def gate_agreement(affiliate_id):
    """The affiliate's single agreement in SUBMITTED, ACTIVE or SUSPENDED."""
    rows = [a for a in agreements_of(affiliate_id)
            if a["status"] in ("SUBMITTED", "ACTIVE", "SUSPENDED")]
    rows = store.sorted_rows(rows)
    return rows[-1] if rows else None


def allocations_of_affiliate(affiliate_id):
    return [a for a in store.allocations.values() if a["affiliate_id"] == affiliate_id]


def allocations_of_member(staff_member_id):
    return [a for a in store.allocations.values()
            if a["staff_member_id"] == staff_member_id]


def assignments_of_affiliate(affiliate_id):
    return [a for a in store.assignments.values() if a["affiliate_id"] == affiliate_id]


def assignments_of_player(player_id):
    return [a for a in store.assignments.values() if a["player_id"] == player_id]


def plans_of_assignment(assignment_id):
    return [p for p in store.plans.values() if p["assignment_id"] == assignment_id]


def logs_of_assignment(assignment_id):
    return [w for w in store.workload_logs.values()
            if w["assignment_id"] == assignment_id]


def clearances_of_player(player_id):
    return [c for c in store.clearances.values() if c["player_id"] == player_id]


def option_years_of_assignment(assignment_id):
    return [o for o in store.option_years.values()
            if o["triggering_assignment_id"] == assignment_id]


def option_years_of_player(player_id):
    rows = []
    for oy in store.option_years.values():
        assignment = store.assignments.get(oy["triggering_assignment_id"])
        if assignment is not None and assignment["player_id"] == player_id:
            rows.append(oy)
    return rows


def reports_of_assignment(assignment_id):
    return [r for r in store.reports.values() if r["assignment_id"] == assignment_id]


def signings_of_pool(pool_id):
    return [s for s in store.signings.values() if s["pool_id"] == pool_id]


def signings_of_academy(affiliate_id):
    return [s for s in store.signings.values()
            if s["academy_affiliate_id"] == affiliate_id]


def plans_of_player(player_id):
    rows = []
    for plan in store.plans.values():
        assignment = store.assignments.get(plan["assignment_id"])
        if assignment is not None and assignment["player_id"] == player_id:
            rows.append(plan)
    return rows


def active_plan_of_player(player_id):
    rows = [p for p in plans_of_player(player_id) if p["status"] == "ACTIVE"]
    rows = store.sorted_rows(rows)
    return rows[-1] if rows else None


# ------------------------------------------------------------ simple predicates
def review_is_overdue(review):
    if review["status"] not in ("OPEN", "REOPENED"):
        return False
    due = store.parse_date(review.get("remediation_due_date"))
    if due is None:
        return False
    return store.clock_date() > due


def clearance_is_expired(clearance):
    if clearance["status"] != "ISSUED":
        return False
    expires = store.parse_date(clearance.get("expires_on"))
    if expires is None:
        return False
    return store.clock_date() > expires


def issued_clearances(player_id, clearance_type=None):
    rows = [c for c in clearances_of_player(player_id) if c["status"] == "ISSUED"]
    if clearance_type is not None:
        rows = [c for c in rows if c["clearance_type"] == clearance_type]
    return store.sorted_rows(rows)


def governing_clearance(assignment):
    required = CLEARANCE_FOR_TYPE[assignment["assignment_type"]]
    rows = [c for c in issued_clearances(assignment["player_id"], required)
            if not clearance_is_expired(c)]
    if not rows:
        rows = issued_clearances(assignment["player_id"], required)
    return rows[-1] if rows else None


def effective_ceiling(assignment):
    ceiling = assignment["workload_ceiling_index"]
    clearance = governing_clearance(assignment)
    if clearance is not None and clearance.get("cleared_workload_ceiling_index") is not None:
        cleared = clearance["cleared_workload_ceiling_index"]
        if cleared < ceiling:
            return cleared
    return ceiling


# ---------------------------------------------------------------- facility roll-up
def facility_rollup(affiliate_id):
    rows = reviews_of(affiliate_id)
    latest = {}
    for review in rows:
        if review["status"] == "WAIVED":
            continue
        key = review["category"]
        current = latest.get(key)
        candidate = (review["review_date"], review["created_at"], review["_seq"])
        if current is None or candidate > current[0]:
            latest[key] = (candidate, review)
    if latest:
        total = sum(Decimal(entry[1]["score"]) for entry in latest.values())
        score = calc.r2(total / Decimal(len(latest)))
    else:
        score = Decimal("100.00")
    major = 0
    minor = 0
    for review in rows:
        if review["status"] not in OPEN_REVIEW_STATUSES:
            continue
        if review["deficiency_level"] == "MAJOR":
            major += 1
        elif review["deficiency_level"] == "MINOR":
            minor += 1
    if major >= 1:
        status = "DEFICIENT"
    elif minor >= 1:
        status = "PROVISIONAL"
    else:
        status = "COMPLIANT"
    return score, major, minor, status


def recompute_affiliate(affiliate):
    affiliate_id = affiliate["id"]
    rows = assignments_of_affiliate(affiliate_id)
    affiliate["active_roster_count"] = len(
        [a for a in rows if a["status"] == "ACTIVE" and a["assignment_type"] in ROSTER_TYPES])
    affiliate["rehab_assignment_count"] = len(
        [a for a in rows if a["status"] == "ACTIVE" and a["assignment_type"] == "REHAB"])
    affiliate["reserve_list_count"] = len(
        [p for p in store.players.values()
         if p.get("current_affiliate_id") == affiliate_id
         and p.get("is_on_domestic_reserve_list")])
    score, major, minor, status = facility_rollup(affiliate_id)
    affiliate["facility_score"] = score
    affiliate["open_major_deficiency_count"] = major
    affiliate["_open_minor_deficiency_count"] = minor
    affiliate["facility_status"] = status


# ---------------------------------------------------------------------- posture
def compute_posture(agreement):
    affiliate = store.affiliates.get(agreement["affiliate_id"])
    if agreement["status"] != "ACTIVE":
        return "FROZEN"
    if affiliate is None:
        return "FROZEN"
    if affiliate["facility_status"] == "DEFICIENT":
        return "FROZEN"
    if affiliate["active_roster_count"] < agreement["minimum_active_players"]:
        return "RESTRICTED"
    covered = set(a["staff_role"] for a in allocations_of_affiliate(affiliate["id"])
                  if a["status"] == "ACTIVE")
    for role in agreement.get("required_staff_roles") or []:
        if role not in covered:
            return "RESTRICTED"
    return "OPEN"


# ----------------------------------------------------------------------- players
def player_workload(player):
    player_id = player["id"]
    window_end = store.clock_date()
    window_start = store.add_days(window_end, -(config.WORKLOAD_WINDOW_DAYS - 1))
    actual = Decimal(0)
    projected = Decimal(0)
    for assignment in assignments_of_player(player_id):
        if assignment["status"] not in ("ACTIVE", "SUSPENDED", "COMPLETED"):
            continue
        level = assignment["level_at_assignment"]
        for log in logs_of_assignment(assignment["id"]):
            log_date = store.parse_date(log["log_date"])
            if log_date is None or log_date < window_start or log_date > window_end:
                continue
            contribution = calc.outing_contribution(
                log["pitches_thrown"], log["innings_pitched"],
                log["high_intensity_minutes"], level)
            if log["is_rehab_outing"]:
                projected += contribution * config.REHAB_OUTING_WEIGHT
            else:
                actual += contribution
                projected += contribution
    plan = active_plan_of_player(player_id)
    allowance = plan["workload_limit_weekly_index"] if plan is not None else Decimal(0)
    return calc.cap_index(actual), calc.cap_index(projected + allowance)


def player_readiness(player, projected_index):
    plan = active_plan_of_player(player["id"])
    if plan is None:
        return Decimal("0.0000")
    return calc.readiness_score(
        plan["completed_module_count"], len(plan["curriculum_modules"]),
        projected_index, plan["workload_limit_weekly_index"],
        player["service_days_accrued"])


def recompute_player(player):
    player_id = player["id"]
    player["is_on_domestic_reserve_list"] = player["origin"] in ("DOMESTIC_DRAFT",
                                                                "FOREIGN_PRO")
    current = None
    for assignment in store.sorted_rows(assignments_of_player(player_id)):
        if assignment["status"] == "ACTIVE" and assignment["assignment_type"] in ROSTER_TYPES:
            current = assignment["affiliate_id"]
    player["current_affiliate_id"] = current
    used = len([o for o in option_years_of_player(player_id) if o["status"] == "CHARGED"])
    player["option_years_used"] = used
    remaining = config.OPTION_YEARS_TOTAL - used
    player["option_years_remaining"] = remaining if remaining > 0 else 0
    actual, projected = player_workload(player)
    player["workload_index"] = actual
    player["workload_index_projected"] = projected
    player["promotion_readiness"] = player_readiness(player, projected)


# -------------------------------------------------------------------- staff / plans
def recompute_staff_member(member):
    today = store.clock_date()
    total = 0
    for allocation in allocations_of_member(member["id"]):
        if allocation["status"] != "ACTIVE":
            continue
        start = store.parse_date(allocation["effective_start"])
        end = store.parse_date(allocation["effective_end"])
        if start is None or end is None:
            continue
        if start <= today < end:
            total += allocation["fte_pct"]
    member["total_committed_fte_pct"] = total


def recompute_plan(plan):
    modules = len(plan["curriculum_modules"])
    if modules == 0:
        plan["completion_pct"] = Decimal("0.00")
        return
    plan["completion_pct"] = calc.r2(
        Decimal(plan["completed_module_count"]) * Decimal(100) / Decimal(modules))


# ---------------------------------------------------------------- pools / reports
def recompute_pool(pool):
    approved = [s for s in signings_of_pool(pool["id"]) if s["status"] == "APPROVED"]
    allocated = sum(s["pool_charge_cents"] for s in approved)
    tax = sum(s["overage_tax_cents"] for s in approved)
    effective = pool["base_pool_cents"] + pool["trade_adjustment_cents"] - pool["forfeited_cents"]
    pool["allocated_cents"] = allocated
    pool["overage_tax_accrued_cents"] = tax
    pool["effective_pool_cents"] = effective
    pool["remaining_cents"] = effective - allocated


def recompute_report(report):
    if report["status"] not in ("PENDING", "FILED", "REJECTED_BY_LEAGUE"):
        return
    deadline = store.parse_date(report.get("filing_deadline"))
    if deadline is None:
        report["is_late"] = False
        report["late_fee_cents"] = 0
        return
    filed_at = store.parse_iso(report.get("filed_at")) if report.get("filed_at") else None
    reference = filed_at.date() if filed_at is not None else store.clock_date()
    days_late = store.days_between(deadline, reference)
    if days_late < 0:
        days_late = 0
    report["is_late"] = days_late > 0
    report["late_fee_cents"] = calc.late_fee_cents(days_late)


def recompute_assignment(assignment):
    assignment["option_year_charged"] = any(
        o["status"] == "CHARGED" for o in option_years_of_assignment(assignment["id"]))


# --------------------------------------------------------------------- reconcile
def reconcile_all():
    for review in store.reviews.values():
        review["is_overdue"] = review_is_overdue(review)
    for clearance in store.clearances.values():
        clearance["is_expired"] = clearance_is_expired(clearance)
    for member in store.staff_members.values():
        recompute_staff_member(member)
    for plan in store.plans.values():
        recompute_plan(plan)
    for assignment in store.assignments.values():
        recompute_assignment(assignment)
    for player in store.players.values():
        recompute_player(player)
    for affiliate in store.affiliates.values():
        recompute_affiliate(affiliate)
    for agreement in store.agreements.values():
        agreement["posture"] = compute_posture(agreement)
    for pool in store.pools.values():
        recompute_pool(pool)
    for report in store.reports.values():
        recompute_report(report)
