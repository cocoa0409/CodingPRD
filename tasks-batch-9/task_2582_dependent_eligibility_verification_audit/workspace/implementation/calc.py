"""Every calculation in section 3, with the rounding order each one pins."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import constants as K
import db


def round_half_up(value):
    """Round a Decimal half up (away from zero) to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------- documentation rules


def find_rule(program_id, relationship_type, phase):
    for rule in db.ordered("doc_rules"):
        if (
            rule["program_id"] == program_id
            and rule["relationship_type"] == relationship_type
            and rule["phase"] == phase
        ):
            return rule
    return None


def governing_rule(program, dependent):
    """Select the rule the completeness test runs against.

    POINT_OF_ENROLLMENT when the dependent's poe_program_id is set and the
    program in context is that same program; AUDIT in every other case.
    """
    if program is None:
        return None
    poe_program_id = dependent.get("poe_program_id")
    phase = (
        "POINT_OF_ENROLLMENT"
        if poe_program_id is not None and poe_program_id == program["id"]
        else "AUDIT"
    )
    return find_rule(program["id"], dependent["relationship_type"], phase)


def documentation_completeness(dependent, program):
    """Returns (accepted_proof_type_count, documentation_complete)."""
    accepted_types = set()
    for sub in db.ordered("submissions"):
        if sub["dependent_id"] != dependent["id"]:
            continue
        if sub["review_status"] != "ACCEPTED":
            continue
        if sub["privacy_status"] not in ("NOT_REQUIRED", "REDACTED", "PURGED"):
            continue
        accepted_types.add(sub["proof_type"])
    count = len(accepted_types)
    rule = governing_rule(program, dependent)
    if rule is None:
        return count, False
    return count, count >= rule["min_accepted_documents"]


# ------------------------------------------------------- scope selection


def enrolled_dependents(employee_id, is_enrolled=None):
    if is_enrolled is None:
        is_enrolled = lambda d: d["coverage_status"] == "ENROLLED"
    return [
        d
        for d in db.ordered("dependents")
        if d["employee_id"] == employee_id and is_enrolled(d)
    ]


def scope_candidate_selection(
    scope_type, targeted_employee_ids, since_date, is_enrolled=None
):
    """Returns [(employee, [dependent, ...]), ...] in pinned processing order.

    `is_enrolled` lets a re-scope evaluate the census as it will look once the
    previous SELECTED case set has been voided, without mutating anything yet.
    """
    employees = list(db.collection("employees").values())
    employees.sort(key=lambda e: (e["created_at"], e["work_email"], e["_seq"]))
    selected = []
    for employee in employees:
        enrolled = enrolled_dependents(employee["id"], is_enrolled)
        if scope_type == "FULL_CENSUS":
            if not enrolled:
                continue
            in_scope = enrolled
        elif scope_type == "TARGETED":
            if employee["id"] not in (targeted_employee_ids or []):
                continue
            if not enrolled:
                continue
            in_scope = enrolled
        else:  # NEW_DEPENDENT_ONLY
            fresh = [d for d in enrolled if d["enrolled_at"] >= since_date]
            if not fresh:
                continue
            in_scope = fresh
        selected.append((employee, in_scope))
    return selected


# ------------------------------------------------------- priority score


def case_escalation_priority_score(case, program):
    in_scope_count = len(case.get("in_scope_dependent_ids") or [])
    unverified = 0
    sensitive_flag = 0
    for dep_id in case.get("in_scope_dependent_ids") or []:
        dependent = db.get("dependents", dep_id)
        if dependent is None:
            continue
        if dependent["coverage_status"] in K.UNRESOLVED_COVERAGE_STATUSES:
            unverified += 1
        if dependent["relationship_type"] in K.SENSITIVE_RELATIONSHIP_TYPES:
            sensitive_flag = 1
    reminders = case.get("reminders_sent_count") or 0
    max_reminders = (program or {}).get("max_reminders") or 0

    unverified_ratio = Decimal(unverified) / Decimal(max(1, in_scope_count))
    reminder_ratio = Decimal(reminders) / Decimal(max(1, max_reminders))
    silence_flag = 1 if (case.get("proof_submission_count") or 0) == 0 else 0

    weighted = (
        Decimal(K.WEIGHT_UNVERIFIED) * unverified_ratio
        + Decimal(K.WEIGHT_SENSITIVE_RELATIONSHIP) * Decimal(sensitive_flag)
        + Decimal(K.WEIGHT_REMINDERS) * reminder_ratio
        + Decimal(K.WEIGHT_SILENCE) * Decimal(silence_flag)
    )
    return min(K.SCORE_CEILING, round_half_up(weighted))


# ------------------------------------------------------- savings


def savings(program, variant):
    """section 3.9 savings measurement over the program's in-scope population."""
    total = 0
    for dependent in in_scope_dependents(program):
        status = dependent["coverage_status"]
        monthly = dependent.get("monthly_cost_cents") or 0
        if variant == "PROVISIONAL":
            if status in ("AMNESTY_REMOVED", "TERMINATION_PENDING", "TERMINATED"):
                total += monthly * 12
        else:
            if status in ("AMNESTY_REMOVED", "TERMINATED"):
                month = clock.month_no(dependent.get("coverage_end_date"))
                if month is None:
                    continue
                total += monthly * (12 - month)
    return total


def in_scope_dependent_ids(program):
    """section 2.9: ids inside in_scope_dependent_ids of the program's non-voided cases."""
    ids = []
    for case in db.ordered("cases", lambda c: c["program_id"] == program["id"]):
        if case["status"] == "VOIDED":
            continue
        ids.extend(case.get("in_scope_dependent_ids") or [])
    return ids


def in_scope_dependents(program):
    result = []
    for dep_id in in_scope_dependent_ids(program):
        dependent = db.get("dependents", dep_id)
        if dependent is not None:
            result.append(dependent)
    return result


# ------------------------------------------------------- claims recovery


def claims_recovery_amount(dependent, notice, program, variant, onset_date):
    """section 3.9 recoverable subtotal for the selected variant."""
    window_end = dependent.get("coverage_end_date") or notice.get("effective_date")
    if variant == "STRICT":
        window_start = onset_date
    else:
        announcement = (program or {}).get("announcement_at")
        window_start = (
            clock.fmt_date(announcement.date()) if announcement else onset_date
        )
    lines = [
        line
        for line in db.collection("claim_lines").values()
        if line["dependent_id"] == dependent["id"]
    ]
    lines.sort(key=lambda l: (l["service_date"], l["created_at"], l["_seq"]))
    subtotal = 0
    for line in lines:
        service_date = line["service_date"]
        if window_start is not None and service_date < window_start:
            continue
        if window_end is not None and service_date > window_end:
            continue
        if variant == "STRICT":
            subtotal += line["paid_cents"]
        else:
            net = line["paid_cents"] - (line.get("employee_premium_offset_cents") or 0)
            subtotal += net if net > 0 else 0
    return subtotal


def net_recovery_demand(subtotal, waiver_credit_cents):
    """Pinned order: tier from the subtotal, one rounding step, waiver last."""
    if subtotal < K.ADMIN_FEE_TIER_1_MAX_CENTS:
        pct = Decimal(K.ADMIN_FEE_PCT_TIER_1)
    elif subtotal < K.ADMIN_FEE_TIER_2_MAX_CENTS:
        pct = Decimal(K.ADMIN_FEE_PCT_TIER_2)
    else:
        pct = Decimal(K.ADMIN_FEE_PCT_TIER_3)
    admin_fee_cents = round_half_up(Decimal(subtotal) * pct)
    net = subtotal + admin_fee_cents - waiver_credit_cents
    return float(pct), admin_fee_cents, net


# ------------------------------------------------------- continuation


def continuation_premium(relationship_type):
    """Three rounding steps - one per component - then an exact sum."""
    components = K.COMPONENT_COST_CENTS.get(relationship_type)
    if not components:
        return 0
    factor = Decimal(K.CONTINUATION_LOAD_FACTOR)
    total = 0
    for name in K.COMPONENT_ORDER:
        total += round_half_up(Decimal(components[name]) * factor)
    return total


# ------------------------------------------------------- notice dates


def termination_effective_date(origin, issued_at, program, dependent):
    if origin == "AUDIT_ESCALATION":
        base = clock.add_days(issued_at.date(), K.TERMINATION_GRACE_DAYS)
        deadline = (program or {}).get("response_deadline_at")
        if deadline is not None:
            floor = deadline.date()
            anchor = base if base >= floor else floor
        else:
            anchor = base
    else:
        poe_deadline = dependent.get("poe_deadline_at")
        anchor_source = poe_deadline.date() if poe_deadline else issued_at.date()
        anchor = clock.add_days(anchor_source, K.TERMINATION_GRACE_DAYS)
    return clock.last_day_of_month(anchor)


def continuation_dates(effective_date_iso):
    start = clock.add_days(clock.parse_date(effective_date_iso), 1)
    end = clock.add_months(start, K.CONTINUATION_MONTHS)
    return clock.fmt_date(start), clock.fmt_date(end)


# ------------------------------------------------------- amnesty


def amnesty_coverage_end(instant):
    return clock.fmt_date(clock.last_day_of_month(instant.date()))


def amnesty_savings_contribution(dependent, coverage_end_date):
    month = clock.month_no(coverage_end_date)
    return (dependent.get("monthly_cost_cents") or 0) * (12 - month)


# ------------------------------------------------------- reminder cadence


def reminder_gap_days(case, instant):
    anchor = case.get("last_reminder_at") or case.get("notified_at")
    if anchor is None:
        return None
    return clock.whole_days_between(anchor, instant)


# ------------------------------------------------------- POE program selection


def poe_program_candidates(relationship_type, instant):
    year = instant.year
    candidates = []
    for program in db.ordered("programs"):
        if not program.get("poe_verification_enabled"):
            continue
        if program.get("plan_year") != year:
            continue
        if program.get("status") not in ("AMNESTY_OPEN", "RESPONSE_WINDOW", "ESCALATION"):
            continue
        rule = find_rule(program["id"], relationship_type, "POINT_OF_ENROLLMENT")
        if rule is None:
            continue
        candidates.append((program, rule))

    def sort_key(entry):
        program = entry[0]
        amnesty_end = program.get("amnesty_end_at")
        return (
            program["created_at"],
            amnesty_end if amnesty_end is not None else program["created_at"],
        )

    candidates.sort(key=sort_key)
    return candidates


def poe_selection_is_ambiguous(candidates):
    if len(candidates) < 2:
        return False
    first, second = candidates[0][0], candidates[1][0]
    return first["created_at"] == second["created_at"] and first.get(
        "amnesty_end_at"
    ) == second.get("amnesty_end_at")
