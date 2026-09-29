"""Derived-field reconciliation: counters, contingency, cost and posture.

PRD §2.6 (readiness posture), §2.7 (derived-field reconciliation),
§3.5 (system test aggregation), §3.7 (cost at completion),
§3.8 (cancellation contingency).
"""
from decimal import Decimal

import clock
import repo
from validate import round_half_up, dec

# --- contingency tiers (PRD §3.8) ------------------------------------------
TIER_1_LIMIT_CENTS = 500000
TIER_2_LIMIT_CENTS = 2000000
TIER_1_PCT = Decimal("0.05")
TIER_2_PCT = Decimal("0.08")
TIER_3_PCT = Decimal("0.12")

# --- readiness weights (PRD §2.6) -----------------------------------------
W_SYSTEMS = Decimal("0.30")
W_STAFFING = Decimal("0.25")
W_PERMITS = Decimal("0.25")
W_SCHEDULE = Decimal("0.20")
SLIP_NORMALIZER_DAYS = Decimal(30)
MANDATORY_PERMIT_TYPES = 4
ON_TRACK_SCORE_FLOOR = Decimal("0.85")


# ===========================================================================
# System test aggregation
# ===========================================================================

def run_pass_rate(cases_passed, cases_total):
    if cases_total == 0:
        return None
    return float(round_half_up(Decimal(cases_passed) / Decimal(cases_total), 4))


def run_result(pass_rate, blocker_count):
    if pass_rate is not None and pass_rate >= 0.95 and blocker_count == 0:
        return "PASSED"
    return "FAILED"


def latest_run(system_id):
    runs = repo.test_runs_of(system_id)
    if not runs:
        return None
    return sorted(
        runs,
        key=lambda r: (clock.parse_instant(r["executed_at"]), r["created_at"], r["_seq"]),
    )[-1]


def reconcile_system(system):
    runs = repo.test_runs_of(system["id"])
    system["test_run_count"] = len(runs)
    newest = latest_run(system["id"])
    if newest is None:
        system["latest_pass_rate"] = None
        system["cumulative_pass_rate"] = None
        system["open_blocker_count"] = 0
        return system
    system["latest_pass_rate"] = newest["pass_rate"]
    system["open_blocker_count"] = newest["blocker_count"]
    total = sum(r["cases_total"] for r in runs)
    passed = sum(r["cases_passed"] for r in runs)
    if total == 0:
        system["cumulative_pass_rate"] = None
    else:
        system["cumulative_pass_rate"] = float(
            round_half_up(Decimal(passed) / Decimal(total), 4))
    return system


# ===========================================================================
# Hiring plans
# ===========================================================================

def reconcile_plan(plan):
    hires = repo.hires_of_plan(plan["id"])
    offered = sum(1 for h in hires if h["state"] in ("OFFERED", "ACCEPTED", "ONBOARDED"))
    accepted = sum(1 for h in hires if h["state"] in ("ACCEPTED", "ONBOARDED"))
    onboarded = sum(1 for h in hires if h["state"] == "ONBOARDED")
    plan["offered_count"] = offered
    plan["accepted_count"] = accepted
    plan["onboarded_count"] = onboarded
    plan["staffing_ratio"] = float(
        round_half_up(Decimal(onboarded) / Decimal(plan["headcount_target"]), 4))
    plan["readiness_flag"] = (
        "READY" if onboarded * 100 >= plan["headcount_target"] * 80 else "NOT_READY")
    return plan


# ===========================================================================
# Training sessions
# ===========================================================================

def session_enrolled_count(session_id, exclude_hire_id=None):
    from db import db
    count = 0
    for hire in db.hires.values():
        if hire["orientation_session_id"] != session_id:
            continue
        if exclude_hire_id is not None and hire["id"] == exclude_hire_id:
            continue
        if hire["state"] in ("DECLINED", "WITHDRAWN"):
            continue
        count += 1
    return count


def reconcile_sessions(program):
    for session in repo.sessions_of(program["id"]):
        session["enrolled_count"] = session_enrolled_count(session["id"])


# ===========================================================================
# Reservation blocks / contingency liability
# ===========================================================================

def _tier_pct(base_relocation_cents):
    if base_relocation_cents < TIER_1_LIMIT_CENTS:
        return TIER_1_PCT
    if base_relocation_cents < TIER_2_LIMIT_CENTS:
        return TIER_2_PCT
    return TIER_3_PCT


def contingency_for(program, room_count, night_count, state):
    """Pinned order: base -> tier -> fee -> subtotal -> penalty."""
    displaced_room_nights = room_count * night_count
    base = displaced_room_nights * program["relocation_rate_cents"]
    pct = _tier_pct(base)
    admin_fee = int(round_half_up(Decimal(base) * pct, 0))
    subtotal = base + admin_fee
    if state == "GUARANTEED":
        subtotal += program["guarantee_penalty_cents"]
    return subtotal


def is_pre_opening(program, arrival_date_raw):
    projected = program.get("projected_opening_date_committed")
    if not projected:
        return False
    arrival = clock.parse_date_strict(arrival_date_raw)
    return arrival < clock.parse_date_strict(projected)


def reconcile_blocks(program):
    liability = 0
    committed_room_nights = 0
    for block in repo.blocks_of(program["id"]):
        block["room_nights"] = block["room_count"] * block["night_count"]
        block["revenue_cents"] = block["room_nights"] * block["rate_cents"]
        pre_opening = is_pre_opening(program, block["arrival_date"])
        block["is_pre_opening"] = pre_opening
        if block["state"] in repo.BLOCK_LIVE_STATES:
            committed_room_nights += block["room_nights"]
            if pre_opening:
                # A block swept from GUARANTEED into AT_RISK keeps the guarantee
                # penalty inside its contingency (PRD §3.8).
                pricing_state = block["state"]
                if pricing_state == "AT_RISK" and block.get("_guaranteed"):
                    pricing_state = "GUARANTEED"
                block["contingency_cents"] = contingency_for(
                    program, block["room_count"], block["night_count"], pricing_state)
                liability += block["contingency_cents"]
            else:
                block["contingency_cents"] = 0
        elif block["state"] == "RELOCATED":
            # contingency_cents is frozen at the value paid out (PRD §3.8)
            pass
        else:
            block["contingency_cents"] = 0
    program["committed_room_nights"] = committed_room_nights
    program["contingency_liability_cents"] = liability
    return program


# ===========================================================================
# Cost at completion
# ===========================================================================

def hire_pre_opening_days(program, hire):
    projected = program.get("projected_opening_date_committed")
    if not projected:
        return 0
    start = clock.parse_date_strict(hire["start_date"])
    end = clock.parse_date_strict(projected)
    return max(0, (end - start).days)


def reconcile_cost(program):
    payroll_accrual = 0
    for hire in repo.hires_of_program(program["id"]):
        if hire["state"] in ("ACCEPTED", "ONBOARDED"):
            days = hire_pre_opening_days(program, hire)
            amount = dec(hire["hourly_rate_cents"]) * dec(hire["scheduled_hours_per_day"]) * Decimal(days)
            hire["accrual_cents"] = int(round_half_up(amount, 0))
            payroll_accrual += hire["accrual_cents"]
        else:
            hire["accrual_cents"] = 0
    program["payroll_accrual_cents"] = payroll_accrual

    commitment_basis = 0
    accrual_basis = 0
    orders = repo.orders_of(program["id"])
    for line in repo.budget_lines_of(program["id"]):
        # Reconciled, never incrementally trusted (PRD §3.7).
        line["committed_cents"] = sum(
            o["amount_cents"] for o in orders
            if o["budget_line_id"] == line["id"] and o["state"] == "COMMITTED")
        line["spent_cents"] = sum(
            o["amount_cents"] for o in orders
            if o["budget_line_id"] == line["id"] and o["state"] == "STORED")
        line["available_cents"] = (line["authorized_cents"]
                                   - line["committed_cents"]
                                   - line["spent_cents"])
        commitment_basis += line["committed_cents"] + line["spent_cents"]
        if line["category"] == "PAYROLL":
            accrual_basis += line["spent_cents"]
        else:
            accrual_basis += line["committed_cents"] + line["spent_cents"]
    accrual_basis += payroll_accrual

    program["cost_at_completion_commitment_cents"] = commitment_basis
    program["cost_at_completion_accrual_cents"] = accrual_basis
    return program


# ===========================================================================
# Counters
# ===========================================================================

def reconcile_counters(program):
    program_id = program["id"]

    milestones = repo.milestones_of(program_id)
    program["critical_path_milestone_count"] = sum(
        1 for m in milestones if m["total_float_days"] == 0)

    punch_items = repo.punch_items_of(program_id)
    for item in punch_items:
        item["blocks_certificate_of_occupancy"] = (
            item["severity"] == "CRITICAL" and item["state"] != "VERIFIED")
    program["open_critical_punch_count"] = sum(
        1 for i in punch_items if i["severity"] == "CRITICAL" and i["state"] != "VERIFIED")

    systems = repo.systems_of(program_id)
    for system in systems:
        reconcile_system(system)
    required = [s for s in systems if s["is_required"]]
    program["required_system_count"] = len(required)
    program["certified_system_count"] = sum(1 for s in required if s["state"] == "CERTIFIED")

    permits = repo.permits_of(program_id)
    issued_mandatory = {p["permit_type"] for p in permits
                        if p["is_mandatory"] and p["state"] == "ISSUED"}
    program["issued_mandatory_permit_count"] = len(issued_mandatory)

    plans = repo.plans_of(program_id)
    for plan in plans:
        reconcile_plan(plan)
    program["hiring_plan_count"] = len(plans)
    program["departments_ready_count"] = sum(
        1 for p in plans if p["readiness_flag"] == "READY")

    reconcile_sessions(program)
    return program


def has_deficient_mandatory_permit(program):
    for permit in repo.permits_of(program["id"]):
        if permit["is_mandatory"] and permit["state"] == "DEFICIENT":
            return True
    return False


# ===========================================================================
# Readiness posture
# ===========================================================================

def _clamp(value):
    if value < 0:
        return Decimal(0)
    if value > 1:
        return Decimal(1)
    return value


def posture_components(program):
    if program["required_system_count"] == 0:
        systems_ratio = Decimal(0)
    else:
        systems_ratio = Decimal(program["certified_system_count"]) / Decimal(
            program["required_system_count"])
    if program["hiring_plan_count"] == 0:
        staffing_ratio = Decimal(0)
    else:
        staffing_ratio = Decimal(program["departments_ready_count"]) / Decimal(
            program["hiring_plan_count"])
    permit_ratio = Decimal(program["issued_mandatory_permit_count"]) / Decimal(
        MANDATORY_PERMIT_TYPES)
    schedule_term = Decimal(1) - (Decimal(program["schedule_slip_days"]) / SLIP_NORMALIZER_DAYS)
    return (_clamp(systems_ratio), _clamp(staffing_ratio),
            _clamp(permit_ratio), _clamp(schedule_term))


def compute_score(program):
    systems_ratio, staffing_ratio, permit_ratio, schedule_term = posture_components(program)
    raw = (W_SYSTEMS * systems_ratio
           + W_STAFFING * staffing_ratio
           + W_PERMITS * permit_ratio
           + W_SCHEDULE * schedule_term)
    return round_half_up(raw, 4)


def select_posture(program, score):
    if program["open_critical_punch_count"] > 0 or has_deficient_mandatory_permit(program):
        return "FROZEN"
    if program["schedule_slip_days"] > program["slip_tolerance_days"]:
        return "RESTRICTED"
    if score >= ON_TRACK_SCORE_FLOOR and program["issued_mandatory_permit_count"] == MANDATORY_PERMIT_TYPES:
        return "ON_TRACK"
    return "MOBILIZING"


def freeze_reason(program):
    if has_deficient_mandatory_permit(program):
        return "PERMIT_DEFICIENCY"
    if program["open_critical_punch_count"] > 0:
        return "CRITICAL_PUNCH_OPEN"
    return None


def _apply_freeze(program):
    """PRD §2.6 + §3.8: a freeze reaches into both other dimensions."""
    if program["schedule_state"] == "SOFT_OPENING":
        program["schedule_state"] = "LICENSING"
        program["soft_opening_date"] = None
        program["soft_opening_authorized_by_user_id"] = None
    if program["commercial_state"] == "BOOKING_OPEN":
        program["commercial_state"] = "BOOKING_SUSPENDED"
    reason = freeze_reason(program)
    for block in repo.blocks_of(program["id"]):
        if block["state"] in ("ACCEPTED", "GUARANTEED") and is_pre_opening(
                program, block["arrival_date"]):
            block["_guaranteed"] = block["state"] == "GUARANTEED"
            block["state"] = "AT_RISK"
            block["at_risk_reason"] = reason


def apply_posture(program):
    score = compute_score(program)
    program["readiness_score"] = float(score)
    posture = select_posture(program, score)
    program["readiness_posture"] = posture
    if posture == "FROZEN":
        _apply_freeze(program)
    return posture


# ===========================================================================
# Orchestration
# ===========================================================================

def reconcile(program, run_schedule=False):
    """Reconcile derived fields WITHOUT running the posture computation."""
    if run_schedule:
        from services import schedule as schedule_service
        schedule_service.compute(program)
    reconcile_counters(program)
    reconcile_blocks(program)
    reconcile_cost(program)
    return program


def refresh(program, run_schedule=False):
    """Reconcile every derived field of the program aggregate, posture included."""
    if run_schedule:
        from services import schedule as schedule_service
        schedule_service.compute(program)
    reconcile_counters(program)
    reconcile_blocks(program)
    reconcile_cost(program)
    posture = apply_posture(program)
    if posture == "FROZEN":
        # the freeze cascade may have moved blocks / the commercial dimension
        reconcile_blocks(program)
        reconcile_cost(program)
    return program
