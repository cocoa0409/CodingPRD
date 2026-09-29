"""Relationship walks and derived counters.

Every counter the PRD defines as a count/sum over children is derived from the
children themselves, so the aggregates can never drift from the records they
summarise. Version increments remain explicit, exactly where §3 names them.
"""

from decimal import Decimal

from db import db, by_creation
from services import calculations as calc

TERMINAL_EXAM_STATES = ("PUBLISHED", "ABORTED")
ENFORCEMENT_EXAM_STATES = ("NEGOTIATION", "ORDER_PENDING")
OPEN_CRITICISM_STATES = ("ISSUED", "RESPONDED")


# ------------------------------------------------------------- relationship walks
def scope_areas_of_exam(exam_id):
    return by_creation([a for a in db.scope_areas.values() if a["exam_id"] == exam_id])


def data_calls_of_area(area_id):
    return by_creation(
        [c for c in db.data_calls.values() if c["scope_area_id"] == area_id]
    )


def data_calls_of_exam(exam_id):
    area_ids = {a["id"] for a in db.scope_areas.values() if a["exam_id"] == exam_id}
    return by_creation(
        [c for c in db.data_calls.values() if c["scope_area_id"] in area_ids]
    )


def file_samples_of_call(call_id):
    return sorted(
        [s for s in db.file_samples.values() if s["data_call_id"] == call_id],
        key=lambda s: (s["population_index"], s["_seq"]),
    )


def file_samples_of_area(area_id):
    call_ids = {c["id"] for c in db.data_calls.values() if c["scope_area_id"] == area_id}
    return sorted(
        [s for s in db.file_samples.values() if s["data_call_id"] in call_ids],
        key=lambda s: (s["population_index"], s["_seq"]),
    )


def fieldwork_activities_of_exam(exam_id):
    return by_creation(
        [a for a in db.fieldwork_activities.values() if a["exam_id"] == exam_id]
    )


def criticisms_of_exam(exam_id):
    return by_creation([c for c in db.criticisms.values() if c["exam_id"] == exam_id])


def responses_of_criticism(criticism_id):
    return by_creation(
        [r for r in db.company_responses.values() if r["criticism_id"] == criticism_id]
    )


def plans_of_exam(exam_id):
    return by_creation([p for p in db.plans.values() if p["exam_id"] == exam_id])


def orders_of_exam(exam_id):
    return by_creation([o for o in db.consent_orders.values() if o["exam_id"] == exam_id])


def collaborations_of_exam(exam_id):
    return by_creation(
        [c for c in db.collaborations.values() if c["exam_id"] == exam_id]
    )


def by_creation_insurers():
    return by_creation(list(db.insurers.values()))


def by_creation_cycles():
    return by_creation(list(db.cycles.values()))


def by_creation_examinations():
    return by_creation(list(db.examinations.values()))


def by_creation_criticisms():
    return by_creation(list(db.criticisms.values()))


def scores_of_insurer(insurer_id):
    return by_creation(
        [s for s in db.analysis_scores.values() if s["insurer_id"] == insurer_id]
    )


def scores_of_cycle(cycle_id):
    return by_creation(
        [s for s in db.analysis_scores.values() if s["cycle_id"] == cycle_id]
    )


def examinations_of_cycle(cycle_id):
    return by_creation(
        [e for e in db.examinations.values() if e.get("cycle_id") == cycle_id]
    )


def examinations_of_insurer(insurer_id):
    return by_creation(
        [e for e in db.examinations.values() if e["insurer_id"] == insurer_id]
    )


def area_of_call(call):
    return db.scope_areas.get(call["scope_area_id"])


def call_of_sample(sample):
    return db.data_calls.get(sample["data_call_id"])


def exam_of_area(area):
    return db.examinations.get(area["exam_id"])


def exam_of_call(call):
    area = area_of_call(call)
    return exam_of_area(area) if area else None


def exam_of_sample(sample):
    call = call_of_sample(sample)
    return exam_of_call(call) if call else None


def exam_of_criticism(criticism):
    return db.examinations.get(criticism["exam_id"])


def exam_of_plan(plan):
    return db.examinations.get(plan["exam_id"])


def exam_of_order(order):
    return db.examinations.get(order["exam_id"])


def exam_of_collaboration(collaboration):
    return db.examinations.get(collaboration["exam_id"])


def executed_order_of_exam(exam_id):
    for order in orders_of_exam(exam_id):
        if order["status"] == "EXECUTED":
            return order
    return None


def draft_order_of_exam(exam_id):
    for order in orders_of_exam(exam_id):
        if order["status"] == "DRAFT":
            return order
    return None


def approved_plan_of_exam(exam_id):
    for plan in plans_of_exam(exam_id):
        if plan["status"] == "APPROVED":
            return plan
    return None


# --------------------------------------------------------------- derived counters
def area_metrics(area):
    samples = file_samples_of_area(area["id"])
    reviewed = [s for s in samples if s["review_status"] != "UNREVIEWED"]
    reviewed_sample_count = len(reviewed)
    error_count = len([s for s in reviewed if s["review_status"] == "ERROR"])
    material_error_count = len([s for s in reviewed if s["error_severity"] == "MATERIAL"])
    error_rate, material_rate = calc.error_rates(
        reviewed_sample_count, error_count, material_error_count
    )
    return {
        "reviewed_sample_count": reviewed_sample_count,
        "error_count": error_count,
        "material_error_count": material_error_count,
        "error_rate_pct": error_rate,
        "material_error_rate_pct": material_rate,
        "tolerance_breached": error_rate >= area["error_tolerance_pct"],
        "escalation_required": material_rate >= calc.MATERIAL_ESCALATION_PCT,
    }


def area_underpaid_total(area_id):
    return sum(
        s["underpaid_amount_cents"]
        for s in file_samples_of_area(area_id)
        if s["review_status"] == "ERROR"
    )


def exam_counters(exam):
    exam_id = exam["id"]
    areas = scope_areas_of_exam(exam_id)
    calls = data_calls_of_exam(exam_id)
    criticisms = criticisms_of_exam(exam_id)
    open_criticisms = [c for c in criticisms if c["status"] in OPEN_CRITICISM_STATES]
    sustained = [c for c in criticisms if c["status"] == "SUSTAINED"]
    return {
        "scope_area_count": len(areas),
        "rejected_data_call_count": len([c for c in calls if c["status"] == "REJECTED"]),
        "open_criticism_count": len(open_criticisms),
        "sustained_criticism_count": len(sustained),
        "pending_restitution_cents": sum(
            c["restitution_exposure_cents"] for c in open_criticisms
        ),
        "aggregate_restitution_cents": sum(
            c["restitution_exposure_cents"] for c in sustained
        ),
        "penalty_units_total": sum(c["penalty_units"] for c in sustained),
    }


def aggregate_restitution_cents(exam):
    return exam_counters(exam)["aggregate_restitution_cents"]


def insurer_counters(insurer_id):
    exams = examinations_of_insurer(insurer_id)
    lifetime = 0
    for exam in exams:
        for order in orders_of_exam(exam["id"]):
            if order["status"] == "EXECUTED":
                lifetime += order["restitution_cents"]
    return {
        "open_exam_count": len(
            [e for e in exams if e["status"] not in TERMINAL_EXAM_STATES]
        ),
        "pending_enforcement_exam_count": len(
            [e for e in exams if e["status"] in ENFORCEMENT_EXAM_STATES]
        ),
        "lifetime_restitution_ordered_cents": lifetime,
    }


def cycle_counters(cycle):
    scores = scores_of_cycle(cycle["id"])
    exams = examinations_of_cycle(cycle["id"])
    slots_committed = len(
        [e for e in exams if e["status"] not in TERMINAL_EXAM_STATES]
    )
    return {
        "scored_insurer_count": len(scores),
        "selected_target_count": len([s for s in scores if s["selected"]]),
        "slots_committed": slots_committed,
        "slots_available": cycle["target_slot_capacity"] - slots_committed,
    }


def windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) intersection; exact adjacency does not overlap."""
    return start_a < end_b and start_b < end_a


def as_float(value):
    return float(value) if isinstance(value, Decimal) else value
