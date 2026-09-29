"""Derived rollups and the three named cascades (PRD 2.10, 2.11)."""

from calc import (SANCTION_PCT_BY_LEVEL, SUPPORTIVE_CAPS_CENTS, benefit_amount,
                  month_first_day, month_last_day, participation_predicate, pct)
from errors import fail
from store import apply_computed, db, ordered, touch


def lookup(table, key, error_id):
    """Path/body existence check (ladder 3 and 4)."""
    row = getattr(db, table).get(key) if isinstance(key, str) else None
    if row is None:
        fail(error_id)
    return row


def rows_where(table, **filters):
    result = []
    for row in getattr(db, table).values():
        if all(row.get(field) == value for field, value in filters.items()):
            result.append(row)
    return ordered(result)


def cases_of_household(household_id):
    return rows_where("cases", household_id=household_id)


def granted_extensions(case_id):
    return [e for e in rows_where("extensions", case_id=case_id)
            if e["status"] == "GRANTED"]


def extension_covers(extension, month):
    first = extension.get("first_effective_month")
    last = extension.get("last_effective_month")
    if not first or not last:
        return False
    return first <= month <= last


# --- time limit ledger ------------------------------------------------------

def recompute_tlm(row, case, granted=None):
    """Derive the two countability flags of one time-limit month (PRD 3.4).

    Ledger rows carry no version, so this write is not an audited mutation."""
    if granted is None:
        granted = granted_extensions(case["id"])
    issued = bool(row.get("assistance_issued"))
    child_only = case["family_type"] == "CHILD_ONLY"
    covered = any(extension_covers(ext, row["benefit_month"]) for ext in granted)
    row["federal_clock_countable"] = issued and not child_only
    row["state_clock_countable"] = issued and not child_only and not covered
    if child_only:
        row["non_countable_reason"] = "CHILD_ONLY_CASE"
    elif covered:
        row["non_countable_reason"] = "GRANTED_EXTENSION"
    else:
        row["non_countable_reason"] = "NONE"
    return row


def refresh_case_ledger(case):
    granted = granted_extensions(case["id"])
    for row in rows_where("time_limit_months", case_id=case["id"]):
        recompute_tlm(row, case, granted)


def recompute_household_clocks(household):
    """The four household rollups (PRD 3.4), across every case of the unit."""
    issued_countable = 0
    extension_months = 0
    state_countable = 0
    federal_countable = 0
    for case in cases_of_household(household["id"]):
        child_only = case["family_type"] == "CHILD_ONLY"
        for row in rows_where("time_limit_months", case_id=case["id"]):
            if not row.get("assistance_issued"):
                continue
            if not child_only:
                issued_countable += 1
                if row.get("non_countable_reason") == "GRANTED_EXTENSION":
                    extension_months += 1
            if row.get("state_clock_countable"):
                state_countable += 1
            if row.get("federal_clock_countable"):
                federal_countable += 1
    apply_computed(household, {
        "issued_countable_months": issued_countable,
        "extension_months_used": extension_months,
        "state_clock_months_used": household["prior_state_clock_months"] + state_countable,
        "federal_clock_months_used": household["prior_federal_clock_months"]
                                     + federal_countable,
    })
    return household


def tlm_issued(case_id, month):
    for row in getattr(db, "time_limit_months").values():
        if row["case_id"] == case_id and row["benefit_month"] == month \
                and row.get("assistance_issued"):
            return True
    return False


# --- money recovery --------------------------------------------------------

def overpayments_of_case(case_id):
    return rows_where("overpayments", case_id=case_id)


def pause_recoupment(case):
    for claim in overpayments_of_case(case["id"]):
        if claim["recoupment_status"] == "ACTIVE":
            claim["recoupment_status"] = "PAUSED"
            touch(claim)


def resume_recoupment(case):
    for claim in overpayments_of_case(case["id"]):
        if claim["recoupment_status"] == "PAUSED":
            claim["recoupment_status"] = "ACTIVE"
            touch(claim)


def recompute_overpayment_ledger(claim):
    total = 0
    for entry in rows_where("recovery_transactions", overpayment_id=claim["id"]):
        total += entry["signed_amount_cents"]
    claim["total_recovered_cents"] = total
    claim["balance_cents"] = claim["established_amount_cents"] - total
    return claim


# --- supportive services ---------------------------------------------------

def auths_of_case(case_id):
    return rows_where("supportive_auths", case_id=case_id)


def recompute_supportive_fy(case, fiscal_year):
    """Rollup tracks the CURRENT federal fiscal year (PRD 3.8)."""
    total = 0
    for auth in auths_of_case(case["id"]):
        if auth["status"] == "AUTHORIZED" and auth["fiscal_year"] == fiscal_year:
            total += auth["authorized_amount_cents"]
    apply_computed(case, {"supportive_fy_authorized_cents": total})
    return total


def supportive_waterfall(case, service_type, fiscal_year, requested_cents):
    """Three-step pinned waterfall (PRD 3.8)."""
    type_committed = 0
    case_committed = 0
    for auth in auths_of_case(case["id"]):
        if auth["status"] != "AUTHORIZED" or auth["fiscal_year"] != fiscal_year:
            continue
        case_committed += auth["authorized_amount_cents"]
        if auth["service_type"] == service_type:
            type_committed += auth["authorized_amount_cents"]
    type_headroom = SUPPORTIVE_CAPS_CENTS[service_type] - type_committed
    from calc import SUPPORTIVE_CASE_FY_CAP_CENTS
    case_headroom = SUPPORTIVE_CASE_FY_CAP_CENTS - case_committed
    return min(requested_cents, type_headroom, case_headroom)


def hold_requested_auths(case):
    for auth in auths_of_case(case["id"]):
        if auth["status"] == "REQUESTED":
            auth["status"] = "HELD"
            touch(auth)


def void_auths_of_assignment(assignment, fiscal_year):
    voided = False
    for auth in rows_where("supportive_auths", work_assignment_id=assignment["id"]):
        if auth["status"] in ("REQUESTED", "HELD", "AUTHORIZED"):
            auth["status"] = "VOIDED"
            auth["void_reason"] = "ASSIGNMENT_TERMINATED"
            auth["authorized_amount_cents"] = 0
            touch(auth)
            voided = True
    return voided


# --- work assignments and participation ------------------------------------

def assignments_of_case(case_id):
    return rows_where("work_assignments", case_id=case_id)


def reports_of_assignment(assignment_id):
    return rows_where("participation_reports", work_assignment_id=assignment_id)


def recompute_assignment_hours(assignment):
    total = 0
    for report in reports_of_assignment(assignment["id"]):
        if report["status"] == "VERIFIED" and report.get("verified_hours"):
            total += report["verified_hours"]
    apply_computed(assignment, {"cumulative_verified_hours": total})
    return total


def case_month_hours(case, month):
    core = 0
    non_core = 0
    for assignment in assignments_of_case(case["id"]):
        for report in reports_of_assignment(assignment["id"]):
            if report["status"] != "VERIFIED" or report["report_month"] != month:
                continue
            core += report.get("core_hours_credited") or 0
            non_core += report.get("non_core_hours_credited") or 0
    return core, non_core


def case_month_participated(case, month):
    core, non_core = case_month_hours(case, month)
    return participation_predicate(core, non_core,
                                   case["required_core_monthly_hours"],
                                   case["required_monthly_hours"])


def terminate_open_assignments(case, reason, fiscal_year):
    """Adverse system termination used by the two closure cascades (PRD 3.4/3.7)."""
    for assignment in assignments_of_case(case["id"]):
        if assignment["status"] in ("PROPOSED", "ACTIVE"):
            assignment["status"] = "TERMINATED"
            assignment["termination_reason"] = reason
            touch(assignment)
            void_auths_of_assignment(assignment, fiscal_year)
    recompute_supportive_fy(case, fiscal_year)


# --- case posture ----------------------------------------------------------

def episodes_of_case(case_id):
    return rows_where("compliance_episodes", case_id=case_id)


def recompute_case_sanction(case):
    """Case sanction rollup plus the six-step grant recompute (PRD 3.7)."""
    levels = [episode["sanction_level"] for episode in episodes_of_case(case["id"])
              if episode["status"] in ("SANCTION_IMPOSED", "CURE_PENDING")]
    level = max(levels) if levels else 0
    fraction = SANCTION_PCT_BY_LEVEL[level]
    benefit = benefit_amount(case["household_size"], case["countable_income_cents"],
                             fraction)
    apply_computed(case, {"sanction_level": level, "sanction_pct": pct(fraction),
                          "benefit_amount_cents": benefit})
    return level


def close_case(case, closure_reason, fiscal_year, terminate_reason="CASE_CLOSED"):
    case["benefit_status"] = "CLOSED"
    case["closure_reason"] = closure_reason
    touch(case)
    terminate_open_assignments(case, terminate_reason, fiscal_year)
    pause_recoupment(case)


def month_overlaps_assignment(month, assignment):
    """PRD 3.6: first day of month strictly before end_date and last day of
    month on or after start_date."""
    return (month_first_day(month) < assignment["end_date"]
            and month_last_day(month) >= assignment["start_date"])


def assignments_overlap(candidate_start, candidate_end, other):
    """Half-open assignment intervals (PRD 3.5)."""
    return candidate_start < other["end_date"] and other["start_date"] < candidate_end


def scheduled_capacity_ok(case_id, start_date, end_date, hours, exclude_id=None):
    total = hours
    for other in assignments_of_case(case_id):
        if other["id"] == exclude_id:
            continue
        if other["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        if assignments_overlap(start_date, end_date, other):
            total += other["scheduled_weekly_hours"]
    return total <= 60
