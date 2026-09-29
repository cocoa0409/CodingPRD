"""The seven calculations of PRD section 3, implemented with Decimal/ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP

import constants as C
from db import parse_dt, plus_days, store


def r2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON as a 2-decimal float."""
    if value is None:
        return None
    return float(r2(value))


def dec(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def dt_of(row, field):
    value = row.get(field)
    if value is None:
        return None
    try:
        return parse_dt(value)
    except Exception:
        return None


# ------------------------------------------------------------------ helpers


def areas_of_worksite(worksite_id):
    return [a for a in store.work_areas.values() if a["worksite_id"] == worksite_id]


def plans_of_worksite(worksite_id):
    return [p for p in store.prevention_plans.values() if p["worksite_id"] == worksite_id]


def governing_plan(worksite_id):
    """The worksite's plan whose status is ACTIVE or REVIEW_DUE, if any."""
    for plan in plans_of_worksite(worksite_id):
        if plan["status"] in ("ACTIVE", "REVIEW_DUE"):
            return plan
    return None


def assessments_of_plan(plan_id):
    return [h for h in store.hazard_assessments.values() if h["plan_id"] == plan_id]


def employees_of_worksite(worksite_id):
    return [e for e in store.employees.values() if e["worksite_id"] == worksite_id]


def seats_of_case(case_id):
    return [t for t in store.team_assignments.values() if t["case_id"] == case_id]


def actions_of_case(case_id):
    return [a for a in store.case_actions.values() if a["case_id"] == case_id]


def entries_of_worksite(worksite_id):
    return [e for e in store.log_entries.values() if e["worksite_id"] == worksite_id]


def drills_of_plan(plan_id):
    return [d for d in store.drills.values() if d["plan_id"] == plan_id]


def is_superseded_entry(entry):
    """superseded_flag is derived on read: some other entry supersedes this one."""
    target = entry["id"]
    for other in store.log_entries.values():
        if other.get("supersedes_entry_id") == target:
            return True
    return False


# ------------------------------------------------------------- hazard score


def hazard_score(assessment, area, variant):
    """calculation hazard_score -- SCREENING and VALIDATED variants."""
    incident_points = min(assessment["reported_incident_count"], C.INCIDENT_COUNT_CAP) * C.INCIDENT_POINT_UNIT
    proximity_points = C.PROXIMITY_POINTS[assessment["proximity_factor"]]
    cash_points = min(
        C.CASH_POINTS_CAP,
        (assessment["cash_on_hand_cents"] // C.CASH_BAND_CENTS) * C.CASH_BAND_POINTS,
    )
    staff = assessment["min_staff_per_shift"]
    if staff <= 1:
        understaffing_points = C.UNDERSTAFF_SOLO_POINTS
    elif staff == 2:
        understaffing_points = C.UNDERSTAFF_PAIR_POINTS
    else:
        understaffing_points = 0
    exposure_points = C.PUBLIC_ACCESS_POINTS if area["public_access_flag"] else 0
    night_points = C.NIGHT_SHIFT_POINTS if area["night_shift_flag"] else 0

    raw = (
        incident_points
        + proximity_points
        + cash_points
        + understaffing_points
        + exposure_points
        + night_points
    )
    if area["lone_worker_flag"]:
        raw = max(raw, C.LONE_WORKER_FLOOR)
    base = min(C.HAZARD_SCORE_CAP, raw)

    if variant == "SCREENING":
        score = r2(Decimal(base))
        verified = False
    else:
        credit = min(assessment["mitigation_credits"], C.MITIGATION_CREDIT_CAP) * C.MITIGATION_CREDIT_UNIT
        if assessment["barrier_installed"]:
            credit += C.BARRIER_CREDIT
        score = r2(Decimal(max(0, base - credit)))
        verified = bool(assessment["mitigation_credits"] >= 1 or assessment["barrier_installed"])

    if score >= C.TIER_1_THRESHOLD:
        tier = "TIER_1_ENGINEERING"
    elif score >= C.TIER_2_THRESHOLD:
        tier = "TIER_2_ADMINISTRATIVE"
    else:
        tier = "TIER_3_TRAINING_ONLY"

    return {
        "hazard_score": num(score),
        "score_variant": variant,
        "control_tier": tier,
        "mitigation_verified": verified,
    }


# --------------------------------------------------- incident severity class


def incident_severity(report):
    points = 0
    if report["weapon_involved"]:
        points += C.WEAPON_POINTS
    points += C.INJURY_POINTS[report["injury_level"]]
    points += C.TYPE_POINTS[report["incident_type"]]

    if points >= C.CRITICAL_THRESHOLD:
        severity_class = "CRITICAL"
    elif points >= C.SERIOUS_THRESHOLD:
        severity_class = "SERIOUS"
    else:
        severity_class = "MINOR"

    log_required = bool(
        severity_class != "MINOR"
        or report["weapon_involved"]
        or report["injury_level"] != "NONE"
    )
    return {
        "severity_points": points,
        "severity_class": severity_class,
        "log_required": log_required,
    }


# --------------------------------------------------------- behavioural risk


def prior_case_count(case):
    """Other cases sharing this case's non-null subject that were created earlier."""
    subject = case.get("subject_employee_id")
    if subject is None:
        return 0
    count = 0
    for other in store.threat_cases.values():
        if other["id"] == case["id"]:
            continue
        if other.get("subject_employee_id") != subject:
            continue
        if (other["created_at"], other["_seq"]) < (case["created_at"], case["_seq"]):
            count += 1
    return count


def interim_risk_score(case, report):
    severity_points = dec(report["severity_points"])
    priors = min(prior_case_count(case), C.PRIOR_CASE_CAP)
    total = C.SEVERITY_WEIGHT * severity_points + Decimal(C.PRIOR_CASE_POINTS * priors)
    if report["weapon_involved"]:
        total += Decimal(C.WEAPON_CASE_POINTS)
    return r2(min(Decimal(C.INTERIM_CAP), total))


def counted_ballot_seats(case):
    seats = []
    for seat in seats_of_case(case["id"]):
        if seat["status"] != "ASSIGNED":
            continue
        if seat["role_on_team"] not in ("LEAD", "VOTING_MEMBER"):
            continue
        if seat.get("ballot_value") is None:
            continue
        if seat.get("ballot_round") != case["assessment_round"]:
            continue
        seats.append(seat)
    return seats


def risk_band(score):
    score = Decimal(str(score))
    if score >= C.BAND_IMMINENT:
        return "IMMINENT"
    if score >= C.BAND_HIGH:
        return "HIGH"
    if score >= C.BAND_MODERATE:
        return "MODERATE"
    return "LOW"


def consensus_risk_score(case):
    """Returns (consensus Decimal, band, [(seat, weight, share Decimal)])."""
    seats = counted_ballot_seats(case)
    total_weight = Decimal("0")
    weights = []
    for seat in seats:
        weight = C.DISCIPLINE_WEIGHT[seat["discipline"]]
        weights.append((seat, weight))
        total_weight += weight

    shares = []
    weighted_raw = Decimal("0")
    if total_weight > 0:
        for seat, weight in weights:
            points = C.BALLOT_POINTS[seat["ballot_value"]]
            share = r2(points * weight / total_weight)
            shares.append((seat, weight, share))
            weighted_raw += share

    interim = dec(case.get("interim_risk_score"))
    consensus = r2(C.INTERIM_BLEND * interim + C.CONSENSUS_BLEND * weighted_raw)
    return consensus, risk_band(consensus), shares


# ------------------------------------------------------------------ quorum


def required_disciplines(report):
    required = set(C.BASE_REQUIRED_DISCIPLINES)
    if report is not None:
        if report["injury_level"] != "NONE":
            required.add("CLINICAL")
        if report["weapon_involved"] or report["incident_type"] == "TYPE_4_DOMESTIC":
            required.add("LEGAL")
    return required


def team_quorum(case, report):
    seats = [s for s in seats_of_case(case["id"]) if s["status"] == "ASSIGNED"]
    seated = set(s["discipline"] for s in seats)
    voting_seats = [s for s in seats if s["role_on_team"] in ("LEAD", "VOTING_MEMBER")]
    leads = [s for s in seats if s["role_on_team"] == "LEAD"]

    required = required_disciplines(report)
    missing = sorted(required - seated)
    quorum_met = bool(
        len(missing) == 0
        and len(voting_seats) >= C.MIN_VOTING_SEATS
        and len(leads) == 1
    )
    return {
        "quorum_met": quorum_met,
        "missing_disciplines": missing,
        "voting_seat_count": len(voting_seats),
        "lead_count": len(leads),
    }


def ballot_count_current_round(case):
    return len(counted_ballot_seats(case))


# --------------------------------------------------------- plan compliance


def plan_compliance_metrics(plan):
    worksite_id = plan["worksite_id"]
    clock = store.clock

    # hazard_coverage_pct
    areas = areas_of_worksite(worksite_id)
    area_count = len(areas)
    live_assessments = [h for h in assessments_of_plan(plan["id"]) if h["status"] != "SUPERSEDED"]
    covered = set(h["work_area_id"] for h in live_assessments)
    if area_count == 0:
        hazard_coverage = Decimal("100.00")
    else:
        hazard_coverage = r2(Decimal(len(covered)) / Decimal(area_count) * Decimal(100))

    # training_compliance_pct
    active_employees = [e for e in employees_of_worksite(worksite_id) if e["employment_status"] == "ACTIVE"]
    modules = list(store.training_modules.values())
    denominator = 0
    numerator = 0
    for employee in active_employees:
        for module in modules:
            if employee["job_function"] not in module["job_function_scope"]:
                continue
            denominator += 1
            for assignment in store.training_assignments.values():
                if assignment["employee_id"] != employee["id"]:
                    continue
                if assignment["module_id"] != module["id"]:
                    continue
                if assignment["status"] != "COMPLETED":
                    continue
                expires = dt_of(assignment, "expires_at")
                if expires is not None and expires > clock:
                    numerator += 1
                    break
    if denominator == 0:
        training_compliance = Decimal("100.00")
    else:
        training_compliance = r2(Decimal(numerator) / Decimal(denominator) * Decimal(100))

    # log_completeness_pct -- live entries are those that are not superseded
    live_entries = [e for e in entries_of_worksite(worksite_id) if not is_superseded_entry(e)]
    if len(live_entries) == 0:
        log_completeness = Decimal("100.00")
    else:
        present = sum(e["required_element_count_present"] for e in live_entries)
        log_completeness = r2(
            Decimal(present)
            / (Decimal(C.REQUIRED_LOG_ELEMENTS) * Decimal(len(live_entries)))
            * Decimal(100)
        )

    # unmitigated_hazard_count
    unmitigated = len([
        h for h in live_assessments
        if h["control_tier"] == "TIER_1_ENGINEERING" and not h["mitigation_verified"]
    ])

    # overdue_action_count
    case_ids = set(c["id"] for c in store.threat_cases.values() if c.get("plan_id") == plan["id"])
    overdue = len([
        a for a in store.case_actions.values()
        if a["action_class"] == "POST_INCIDENT"
        and a["status"] == "OVERDUE"
        and a["case_id"] in case_ids
    ])

    # drills_completed_12mo
    horizon = plus_days(clock, -365)
    drills = 0
    for drill in drills_of_plan(plan["id"]):
        if drill["status"] != "EXECUTED" or not drill["credited"]:
            continue
        executed = dt_of(drill, "executed_at")
        if executed is not None and horizon <= executed <= clock:
            drills += 1

    return {
        "hazard_coverage_pct": num(hazard_coverage),
        "training_compliance_pct": num(training_compliance),
        "log_completeness_pct": num(log_completeness),
        "unmitigated_hazard_count": unmitigated,
        "overdue_action_count": overdue,
        "drills_completed_12mo": drills,
    }


def compliance_posture(plan, worksite):
    """Derived from the plan's own status plus the risk state of its worksite."""
    if plan["status"] in ("DRAFT", "IN_REVIEW", "SUPERSEDED"):
        return "FROZEN"
    if plan["status"] == "REVIEW_DUE":
        return "RESTRICTED"
    if worksite is not None and worksite.get("high_risk_flag"):
        return "RESTRICTED"
    return "OPEN"


# ----------------------------------------------------- inspection readiness


def inspection_readiness(plan, metrics, posture):
    hazard = C.HAZARD_WEIGHT * dec(metrics["hazard_coverage_pct"]) / Decimal(100)
    training_pct = min(Decimal(100), dec(metrics["training_compliance_pct"]))
    training = C.TRAINING_WEIGHT * training_pct / Decimal(100)
    log = C.LOG_WEIGHT * dec(metrics["log_completeness_pct"]) / Decimal(100)
    drill = C.DRILL_WEIGHT * min(Decimal(1), Decimal(metrics["drills_completed_12mo"]) / C.DRILL_TARGET)
    overdue = metrics["overdue_action_count"]
    if overdue == 0:
        action = C.ACTION_FULL_POINTS
    elif overdue == 1:
        action = C.ACTION_PARTIAL_POINTS
    else:
        action = Decimal("0")

    # Step 1 -- rounded subtotal.
    subtotal = r2(hazard + training + log + drill + action)

    # Step 2 -- band from the ROUNDED subtotal.
    if subtotal >= C.STRONG_THRESHOLD:
        band = "STRONG"
        rate = C.PENALTY_RATE_STRONG
    elif subtotal >= C.ADEQUATE_THRESHOLD:
        band = "ADEQUATE"
        rate = C.PENALTY_RATE_ADEQUATE
    else:
        band = "WEAK"
        rate = C.PENALTY_RATE_WEAK

    # Step 3 -- penalty and score.
    penalty = r2(subtotal * rate * Decimal(metrics["unmitigated_hazard_count"]))
    score = r2(max(Decimal("0"), subtotal - penalty))

    # Step 4 -- readiness gate keyed off the posture.
    if posture == "FROZEN":
        ready = False
    elif posture == "RESTRICTED":
        ready = score >= C.READY_THRESHOLD_RESTRICTED
    else:
        ready = score >= C.READY_THRESHOLD_OPEN

    return {
        "readiness_subtotal": num(subtotal),
        "readiness_penalty_band": band,
        "readiness_penalty_points": num(penalty),
        "readiness_score": num(score),
        "inspection_ready": bool(ready),
    }


# ----------------------------------------------------- protective coverage


def coverage_gap(case):
    """Returns (coverage_gap_hours Decimal, protection_status)."""
    window_start = dt_of(case, "protection_window_start")
    window_end = dt_of(case, "protection_window_end")
    protected = case.get("protected_employee_id")

    if window_start is None or window_end is None:
        return Decimal("0.00"), "NOT_APPLICABLE"

    intervals = []
    for action in actions_of_case(case["id"]):
        if action["action_class"] != "PROTECTIVE":
            continue
        if action["status"] not in C.COVERED_STATUSES:
            continue
        if action["action_type"] == "RESTRAINING_ORDER_SUPPORT":
            continue
        starts = dt_of(action, "starts_at")
        ends = dt_of(action, "ends_at")
        if starts is None or ends is None:
            continue
        clipped_start = max(starts, window_start)
        clipped_end = min(ends, window_end)
        if clipped_end <= clipped_start:
            continue
        intervals.append((clipped_start, clipped_end))

    intervals.sort(key=lambda iv: (iv[0], iv[1]))
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    covered_minutes = 0
    for start, end in merged:
        covered_minutes += int((end - start).total_seconds() // 60)

    window_minutes = int((window_end - window_start).total_seconds() // 60)
    gap_minutes = max(0, window_minutes - covered_minutes)
    gap_hours = r2(Decimal(gap_minutes) / Decimal(60))

    if protected is None:
        status = "NOT_APPLICABLE"
    elif gap_hours == Decimal("0.00"):
        status = "COVERED"
    else:
        status = "GAP"
    return gap_hours, status
