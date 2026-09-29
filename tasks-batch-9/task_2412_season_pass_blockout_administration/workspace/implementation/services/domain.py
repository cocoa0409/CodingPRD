"""Look-ups, derived values and cascades over the in-memory store."""

from datetime import timedelta

from db import db, fmt_day, parse_day, parse_instant
from errors import ApiError
from services import calc

LIVE_PASS_STATUSES = ("PENDING_PROCESSING", "ACTIVE", "SUSPENDED")
REVENUE_PASS_STATUSES = ("PENDING_PROCESSING", "ACTIVE", "SUSPENDED", "EXPIRED")
RELEASED_RESERVATION_STATUSES = (
    "CANCELLED_BY_HOLDER",
    "CANCELLED_BY_SUSPENSION",
    "CANCELLED_BY_BLOCKOUT",
)
OPEN_CASE_STATUSES = ("OPEN", "UNDER_REVIEW", "APPEAL_PENDING")


# ------------------------------------------------------------------ look-ups
def _fetch(table, record_id, error_id):
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    record = getattr(db, table).get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_program(program_id):
    return _fetch("pass_programs", program_id, "ERR_PROGRAM_NOT_FOUND")


def get_tier(tier_id):
    return _fetch("pass_tiers", tier_id, "ERR_TIER_NOT_FOUND")


def get_park_day(park_day_id):
    return _fetch("park_days", park_day_id, "ERR_PARK_DAY_NOT_FOUND")


def get_assignment(assignment_id):
    return _fetch("blockout_assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_passholder(passholder_id):
    return _fetch("passholders", passholder_id, "ERR_PASSHOLDER_NOT_FOUND")


def get_pass(pass_id):
    return _fetch("season_passes", pass_id, "ERR_PASS_NOT_FOUND")


def get_plan(plan_id):
    return _fetch("payment_plans", plan_id, "ERR_PLAN_NOT_FOUND")


def get_installment(installment_id):
    return _fetch("installments", installment_id, "ERR_INSTALLMENT_NOT_FOUND")


def get_reservation(reservation_id):
    return _fetch("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")


def get_visit(visit_id):
    return _fetch("visits", visit_id, "ERR_VISIT_NOT_FOUND")


def get_case(case_id):
    return _fetch("sharing_cases", case_id, "ERR_CASE_NOT_FOUND")


def get_upgrade_order(order_id):
    return _fetch("upgrade_orders", order_id, "ERR_UPGRADE_ORDER_NOT_FOUND")


# ------------------------------------------------------------------ helpers
def program_tiers(program_id):
    return [t for t in db.rows("pass_tiers") if t["program_id"] == program_id]


def program_park_days(program_id):
    return [d for d in db.rows("park_days") if d["program_id"] == program_id]


def program_passes(program_id):
    return [p for p in db.rows("season_passes") if p["program_id"] == program_id]


def pass_reservations(pass_id):
    return [r for r in db.rows("reservations") if r["season_pass_id"] == pass_id]


def day_reservations(park_day_id):
    return [r for r in db.rows("reservations") if r["park_day_id"] == park_day_id]


def pass_visits(pass_id):
    return [v for v in db.rows("visits") if v["season_pass_id"] == pass_id]


def pass_plans(pass_id):
    return [p for p in db.rows("payment_plans") if p["season_pass_id"] == pass_id]


def plan_installments(plan_id):
    return [i for i in db.rows("installments") if i["payment_plan_id"] == plan_id]


def pass_cases(pass_id):
    return [c for c in db.rows("sharing_cases") if c["season_pass_id"] == pass_id]


def pass_upgrade_orders(pass_id):
    return [o for o in db.rows("upgrade_orders") if o["season_pass_id"] == pass_id]


def active_plan(pass_id):
    for plan in pass_plans(pass_id):
        if plan["plan_status"] == "ACTIVE":
            return plan
    return None


def has_active_blockout(tier_id, park_day_id):
    for assignment in db.rows("blockout_assignments"):
        if (
            assignment["tier_id"] == tier_id
            and assignment["park_day_id"] == park_day_id
            and assignment["status"] == "ACTIVE"
        ):
            return True
    return False


def pass_under_hold(pass_id):
    for case in pass_cases(pass_id):
        if case["case_status"] in OPEN_CASE_STATUSES:
            return True
    return False


def sorted_installments(installments):
    return sorted(
        installments,
        key=lambda i: (i["due_date"], i["sequence_no"], i["created_at"]),
    )


# ------------------------------------------------------- derived: park day
def day_counters(park_day):
    reservations = day_reservations(park_day["id"])
    reserved = sum(1 for r in reservations if r["status"] == "CONFIRMED")
    released = sum(1 for r in reservations if r["status"] in RELEASED_RESERVATION_STATUSES)
    redeemed = sum(1 for r in reservations if r["status"] == "REDEEMED")
    no_show = sum(1 for r in reservations if r["status"] == "NO_SHOW")
    remaining = max(0, park_day["reservation_slot_capacity"] - reserved)
    return {
        "reserved_count": reserved,
        "released_count": released,
        "redeemed_count": redeemed,
        "no_show_count": no_show,
        "remaining_slot_count": remaining,
    }


# ------------------------------------------------------- derived: pass money
def pass_credited_cents(season_pass):
    total = 0
    for order in pass_upgrade_orders(season_pass["id"]):
        if order["status"] == "APPLIED":
            total += order["credit_cents"]
    return total


def pass_outstanding_cents(season_pass):
    return (
        season_pass["billed_total_cents"]
        - season_pass["paid_to_date_cents"]
        - pass_credited_cents(season_pass)
    )


def pass_visit_count(season_pass):
    return sum(1 for v in pass_visits(season_pass["id"]) if v["status"] in ("OPEN", "CLOSED"))


def pass_in_park_spend_cents(season_pass):
    return sum(v["spend_cents"] for v in pass_visits(season_pass["id"]) if v["status"] == "CLOSED")


# ------------------------------------------------------- derived: plan counts
def plan_counts(plan):
    installments = plan_installments(plan["id"])
    return {
        "missed_count": sum(1 for i in installments if i["status"] == "MISSED"),
        "settled_count": sum(1 for i in installments if i["status"] == "SETTLED"),
    }


# ------------------------------------------------------- derived: passholder
def holder_passes(passholder_id):
    return [p for p in db.rows("season_passes") if p["passholder_id"] == passholder_id]


def holder_photo_mismatch_count(passholder_id):
    total = 0
    pass_ids = {p["id"] for p in holder_passes(passholder_id)}
    for visit in db.rows("visits"):
        if visit["season_pass_id"] in pass_ids and visit["photo_match"] == "MISMATCH":
            total += 1
    return total


# ------------------------------------------------------- derived: program
def program_revenue(program_id):
    passes = program_passes(program_id)
    revenue_set = [p for p in passes if p["pass_status"] in REVENUE_PASS_STATUSES]
    forfeit_set = [p for p in passes if p["pass_status"] == "REVOKED"]
    base = sum(p["contract_value_cents"] for p in revenue_set)
    recognized = sum(p["paid_to_date_cents"] for p in revenue_set)
    deferred = sum(pass_outstanding_cents(p) for p in revenue_set)
    forfeited = sum(p["paid_to_date_cents"] for p in forfeit_set)
    active = sum(1 for p in passes if p["pass_status"] == "ACTIVE")
    revenue_ids = {p["id"] for p in revenue_set}
    visits = [v for v in db.rows("visits") if v["season_pass_id"] in revenue_ids]
    closed = [v for v in visits if v["status"] == "CLOSED"]
    spend = sum(v["spend_cents"] for v in closed)
    return {
        "base_revenue_cents": base,
        "recognized_revenue_cents": recognized,
        "deferred_revenue_cents": deferred,
        "forfeited_revenue_cents": forfeited,
        "active_pass_count": active,
        "total_visit_count": len(visits),
        "visits_per_active_pass": calc.visits_per_active_pass(len(visits), active),
        "total_in_park_spend_cents": spend,
        "spend_per_visit_cents": calc.spend_per_visit_cents(spend, len(closed)),
    }


# ------------------------------------------------------------------ cascades
def cancel_reservations(reservations, new_status):
    """Move CONFIRMED reservations to a cancellation state (counters are derived)."""
    count = 0
    for reservation in reservations:
        if reservation["status"] == "CONFIRMED":
            reservation["status"] = new_status
            count += 1
    return count


def cancel_blocked_reservations_for_tier(tier_id, park_day_id):
    victims = []
    for reservation in day_reservations(park_day_id):
        if reservation["status"] != "CONFIRMED":
            continue
        season_pass = db.season_passes.get(reservation["season_pass_id"])
        if season_pass is not None and season_pass["tier_id"] == tier_id:
            victims.append(reservation)
    return cancel_reservations(victims, "CANCELLED_BY_BLOCKOUT")


def install_capacity_blockouts(park_day):
    """Level one/two cascade when a day enters CAPACITY_LOCKED (PRD 3.2)."""
    program = get_program(park_day["program_id"])
    max_rank = program["capacity_lock_blockout_max_rank"]
    candidates = [
        tier
        for tier in program_tiers(park_day["program_id"])
        if tier["status"] == "PUBLISHED"
        and tier["tier_rank"] <= max_rank
        and not has_active_blockout(tier["id"], park_day["id"])
    ]
    candidates.sort(key=lambda t: (t["tier_rank"], t["created_at"]))
    for tier in candidates:
        db.insert(
            "blockout_assignments",
            {
                "tier_id": tier["id"],
                "park_day_id": park_day["id"],
                "source": "CAPACITY_ADJUSTED",
                "status": "ACTIVE",
                "lift_reason": None,
            },
        )
    # level two - every confirmed reservation whose tier is now blocked
    for reservation in day_reservations(park_day["id"]):
        if reservation["status"] != "CONFIRMED":
            continue
        season_pass = db.season_passes.get(reservation["season_pass_id"])
        if season_pass is None:
            continue
        if has_active_blockout(season_pass["tier_id"], park_day["id"]):
            reservation["status"] = "CANCELLED_BY_BLOCKOUT"


def release_capacity_blockouts(park_day):
    """Auto-lift capacity blockouts when a day leaves CAPACITY_LOCKED (PRD 3.2)."""
    for assignment in db.rows("blockout_assignments"):
        if (
            assignment["park_day_id"] == park_day["id"]
            and assignment["source"] == "CAPACITY_ADJUSTED"
            and assignment["status"] == "ACTIVE"
        ):
            assignment["status"] = "LIFTED"
            assignment["lift_reason"] = "CAPACITY_RELEASED"


def apply_posture(park_day, program):
    """Re-derive posture and run the directional cascades."""
    previous = park_day["day_class"]
    utilization, day_class, slot_capacity, window_capacity = calc.derive_posture(
        program, park_day["capacity_total"], park_day["forecast_attendance"]
    )
    park_day["forecast_utilization_pct"] = utilization
    park_day["day_class"] = day_class
    park_day["reservation_slot_capacity"] = slot_capacity
    park_day["window_slot_capacity"] = window_capacity
    if day_class == "CAPACITY_LOCKED" and previous != "CAPACITY_LOCKED":
        install_capacity_blockouts(park_day)
    elif previous == "CAPACITY_LOCKED" and day_class != "CAPACITY_LOCKED":
        release_capacity_blockouts(park_day)
    return previous, day_class


# ------------------------------------------------------------ pass lifecycle
def revoke_pass(season_pass):
    season_pass["pass_status"] = "REVOKED"
    plan = active_plan(season_pass["id"])
    if plan is not None:
        plan["plan_status"] = "TERMINATED_ON_REVOCATION"
        for installment in plan_installments(plan["id"]):
            if installment["status"] == "SCHEDULED":
                installment["status"] = "VOIDED"
    cancel_reservations(pass_reservations(season_pass["id"]), "CANCELLED_BY_SUSPENSION")


def restore_revoked_pass(season_pass):
    season_pass["pass_status"] = "ACTIVE"
    for plan in pass_plans(season_pass["id"]):
        if plan["plan_status"] == "TERMINATED_ON_REVOCATION":
            plan["plan_status"] = "ACTIVE"
            for installment in plan_installments(plan["id"]):
                if installment["status"] == "VOIDED":
                    installment["status"] = "SCHEDULED"


def expire_program_passes(program):
    for season_pass in program_passes(program["id"]):
        if season_pass["pass_status"] in LIVE_PASS_STATUSES:
            season_pass["pass_status"] = "EXPIRED"
            for reservation in pass_reservations(season_pass["id"]):
                if reservation["status"] == "CONFIRMED":
                    reservation["status"] = "NO_SHOW"


# ------------------------------------------------------------ risk scoring
def recompute_sharing_risk(season_pass, entered_day):
    """PRD 3.7 - variant selected by the entered day's day_class."""
    visits = pass_visits(season_pass["id"])
    if entered_day["day_class"] in ("PEAK", "CAPACITY_LOCKED"):
        gates_by_date = {}
        for visit in visits:
            park_day = db.park_days.get(visit["park_day_id"])
            if park_day is None:
                continue
            gates_by_date.setdefault(park_day["calendar_date"], set()).add(visit["gate_code"])
        distinct_gates = max([len(g) for g in gates_by_date.values()] or [0])
        mismatches = sum(1 for v in visits if v["photo_match"] == "MISMATCH")
        return (
            calc.GATE_CLUSTER_GATE_WEIGHT * max(0, distinct_gates - 1)
            + calc.GATE_CLUSTER_MISMATCH_WEIGHT * mismatches
        )
    now = db.now()
    floor_instant = now - timedelta(days=calc.ROLLING_WINDOW_DAYS)
    window = []
    for visit in visits:
        moment = parse_instant(visit["entry_at"])
        if floor_instant <= moment <= now:
            window.append(visit)
    mismatches = sum(1 for v in window if v["photo_match"] == "MISMATCH")
    return (
        calc.ROLLING_WINDOW_FREQUENCY_WEIGHT
        * max(0, len(window) - calc.ROLLING_WINDOW_FREE_ENTRIES)
        + calc.ROLLING_WINDOW_MISMATCH_WEIGHT * mismatches
    )


def maybe_auto_open_case(season_pass, program, score):
    if score < program["sharing_case_auto_open_score"]:
        return None
    if pass_under_hold(season_pass["id"]):
        return None
    return db.insert(
        "sharing_cases",
        {
            "season_pass_id": season_pass["id"],
            "opened_by_user_id": "SYSTEM",
            "opened_by_role": "SYSTEM",
            "evidence_visit_ids": [],
            "note": None,
            "case_status": "OPEN",
            "review_round": 0,
            "risk_score_at_open": score,
            "decided_by_user_id": None,
            "decision_rationale": None,
            "revocation_forfeit_cents": None,
        },
    )


# ------------------------------------------------------------ renewal quote
def renewal_quote(season_pass, target_tier):
    program = get_program(target_tier["program_id"])
    standard = target_tier["base_price_cents"]
    deadline = parse_day(program["early_bird_deadline"])
    early_bird = db.today() <= deadline
    if early_bird:
        discounted = standard - calc.early_bird_discount_cents(standard)
    else:
        discounted = standard
    raw_retention = calc.raw_retention_credit_cents(pass_visit_count(season_pass))
    retention = calc.retention_credit_cents(raw_retention, discounted)
    return {
        "season_pass_id": season_pass["id"],
        "target_tier_id": target_tier["id"],
        "standard_price_cents": standard,
        "early_bird_applied": early_bird,
        "discounted_price_cents": discounted,
        "raw_retention_credit_cents": raw_retention,
        "retention_credit_cents": retention,
        "quoted_price_cents": discounted - retention,
    }


def pass_is_renewable(season_pass):
    if season_pass["pass_status"] in ("PENDING_PROCESSING", "REVOKED"):
        return False
    for other in db.rows("season_passes"):
        if other["renewed_from_pass_id"] == season_pass["id"]:
            return False
    return True


def calendar_date_of(park_day):
    return parse_day(park_day["calendar_date"])


def fmt_calendar_date(value):
    return fmt_day(value)
