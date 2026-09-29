"""System-driven transitions and the cascades of PRD §2.7, §3.5, §3.7 and §3.10."""

from db import (
    add_days,
    add_months,
    db,
    new_record,
    now_iso,
    today_str,
    touch,
)
from services import calculations as calc
from services import derive


# ------------------------------------------------------------------ cycle closing
def maybe_close_cycle(cycle):
    """TARGETS_SELECTED -> CLOSED once the cycle's last live examination went terminal."""
    if cycle is None or cycle["status"] != "TARGETS_SELECTED":
        return
    counters = derive.cycle_counters(cycle)
    if counters["selected_target_count"] >= 1 and counters["slots_committed"] == 0:
        cycle["status"] = "CLOSED"
        cycle["closed_at"] = now_iso()
        touch(cycle)


def release_cycle_slot(exam):
    if exam.get("cycle_id"):
        maybe_close_cycle(db.cycles.get(exam["cycle_id"]))


# --------------------------------------------------------- examination bubble-ups
def exam_first_acceptance(exam):
    """DATA_CALL -> FIELDWORK on the first ACCEPTED data call of the examination."""
    if exam["status"] == "DATA_CALL":
        exam["status"] = "FIELDWORK"
        touch(exam)


def exam_maybe_enter_criticism(exam):
    """FIELDWORK -> CRITICISM when every scope area of the examination is TESTED."""
    if exam["status"] != "FIELDWORK":
        return
    areas = derive.scope_areas_of_exam(exam["id"])
    if not areas or any(area["status"] != "TESTED" for area in areas):
        return
    exam["status"] = "CRITICISM"
    exam["criticism_phase_opened_at"] = now_iso()
    touch(exam)
    # cascade hop 3: activate a collaboration still awaiting its lead assignment.
    for collaboration in derive.collaborations_of_exam(exam["id"]):
        if collaboration["status"] == "LEAD_ASSIGNED":
            collaboration["status"] = "ACTIVE"
            touch(collaboration)


def exam_maybe_enter_negotiation(exam):
    """CRITICISM -> NEGOTIATION once no criticism is open and at least one sustained."""
    if exam["status"] != "CRITICISM":
        return
    counters = derive.exam_counters(exam)
    if counters["open_criticism_count"] == 0 and counters["sustained_criticism_count"] >= 1:
        exam["status"] = "NEGOTIATION"
        touch(exam)


def exam_plan_approved(exam):
    """NEGOTIATION -> ORDER_PENDING when a corrective action plan is approved."""
    if exam["status"] == "NEGOTIATION":
        exam["status"] = "ORDER_PENDING"
        touch(exam)


# ------------------------------------------------------------------- scope areas
def area_after_review(area):
    """Recompute the area from its samples; close testing when nothing is unreviewed."""
    samples = derive.file_samples_of_area(area["id"])
    finished = bool(samples) and all(
        sample["review_status"] != "UNREVIEWED" for sample in samples
    )
    if area["status"] == "FIELDWORK" and finished:
        area["status"] = "TESTED"
        area["tested_at"] = now_iso()
    touch(area)
    exam = derive.exam_of_area(area)
    if exam is not None and area["status"] == "TESTED":
        exam_maybe_enter_criticism(exam)


def draw_samples(call, area):
    """Materialise the deterministic sample plan for an accepted data call."""
    interval, plan = calc.sample_plan(area)
    call["sample_draw_interval"] = interval
    for population_index, file_reference in plan:
        sample = new_record(
            {
                "data_call_id": call["id"],
                "file_reference": file_reference,
                "population_index": population_index,
                "review_status": "UNREVIEWED",
                "error_severity": "NONE",
                "underpaid_amount_cents": 0,
                "days_to_pay": 0,
                "reviewed_at": None,
            }
        )
        db.file_samples[sample["id"]] = sample
    return len(plan)


def apply_sample_review(sample, error_severity, underpaid_amount_cents, days_to_pay):
    """Write one file review onto its sample (PRD §3.5)."""
    sample["error_severity"] = error_severity
    sample["review_status"] = "COMPLIANT" if error_severity == "NONE" else "ERROR"
    sample["underpaid_amount_cents"] = underpaid_amount_cents
    sample["days_to_pay"] = days_to_pay
    sample["reviewed_at"] = now_iso()
    touch(sample)
    return sample


def area_revert_to_planned(area):
    """FIELDWORK -> PLANNED: void the whole sample so a replacement call can re-draw."""
    # samples_drawn_count is derived from the surviving samples, so deleting the
    # sample rows drives it to 0 on every ACCEPTED data call of this area.
    for sample in derive.file_samples_of_area(area["id"]):
        db.file_samples.pop(sample["id"], None)
    area["status"] = "PLANNED"
    area["tested_at"] = None
    touch(area)


# -------------------------------------------------------------------- publication
def publish_examination(exam, public_summary):
    counters = derive.exam_counters(exam)
    sustained_severities = [
        criticism["severity"]
        for criticism in derive.criticisms_of_exam(exam["id"])
        if criticism["status"] == "SUSTAINED"
    ]
    exam["status"] = "PUBLISHED"
    exam["report_published_at"] = now_iso()
    exam["public_summary"] = public_summary

    months = calc.followup_months(sustained_severities)
    if months is None:
        exam["followup_required"] = False
        exam["followup_due_date"] = None
    else:
        due_date = add_months(today_str(), months)
        exam["followup_required"] = True
        exam["followup_due_date"] = due_date
        followup = new_record(
            {
                "insurer_id": exam["insurer_id"],
                "cycle_id": None,
                "predecessor_exam_id": exam["id"],
                "exam_type": "TARGETED_EXAM",
                "mode": "DESK",
                "lead_state_code": exam["lead_state_code"],
                "fieldwork_start_date": due_date,
                "fieldwork_end_date": add_days(due_date, calc.FOLLOWUP_WINDOW_DAYS),
                "status": "SCOPING",
                "scope_locked": False,
                "criticism_phase_opened_at": None,
                "report_published_at": None,
                "public_summary": None,
                "followup_required": False,
                "followup_due_date": None,
                "abort_reason": None,
            }
        )
        db.examinations[followup["id"]] = followup

    for area in derive.scope_areas_of_exam(exam["id"]):
        if area["status"] == "TESTED":
            area["status"] = "CLOSED"
            touch(area)

    touch(exam)
    release_cycle_slot(exam)
    return counters


# ------------------------------------------------------------------- abandonment
def abort_examination(exam, abort_reason):
    """The compensating transaction of PRD §3.10, in its four hops."""
    # hop 1
    exam["abort_reason"] = abort_reason
    exam["status"] = "ABORTED"

    # hop 2 / hop 3 (the reversed accounting is derived from the swept records)
    for call in derive.data_calls_of_exam(exam["id"]):
        if call["status"] in ("ISSUED", "OVERDUE", "RESPONDED"):
            call["status"] = "CANCELLED"
            touch(call)
    for area in derive.scope_areas_of_exam(exam["id"]):
        if area["status"] in ("PLANNED", "FIELDWORK", "TESTED"):
            area["status"] = "CLOSED"
            touch(area)
    for criticism in derive.criticisms_of_exam(exam["id"]):
        if criticism["status"] in ("ISSUED", "RESPONDED"):
            criticism["status"] = "WITHDRAWN"
            touch(criticism)
    for plan in derive.plans_of_exam(exam["id"]):
        if plan["status"] in ("PROPOSED", "REVISION_REQUESTED"):
            plan["status"] = "REJECTED"
            touch(plan)
    for order in derive.orders_of_exam(exam["id"]):
        if order["status"] == "DRAFT":
            order["status"] = "VOIDED"
            touch(order)
    for collaboration in derive.collaborations_of_exam(exam["id"]):
        if collaboration["status"] in ("LEAD_ASSIGNED", "ACTIVE"):
            collaboration["status"] = "DISSOLVED"
            for participant in collaboration["participating_states"]:
                participant["allocated_cents"] = 0
            collaboration["allocation_completed_at"] = None
            touch(collaboration)

    touch(exam)
    # hop 4
    release_cycle_slot(exam)


# ------------------------------------------------------------------ logical clock
def sweep_overdue_data_calls(new_clock_date):
    swept = 0
    for call in db.data_calls.values():
        if call["status"] == "ISSUED" and call["response_due_date"] < new_clock_date:
            call["status"] = "OVERDUE"
            touch(call)
            swept += 1
    return swept
