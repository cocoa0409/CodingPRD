"""Shared band checks of PRD §2.11 — existence, carrier ownership, terminality."""

from db import db
from errors import ApiError
from middleware import current_user_id, is_respondent
from services import derive


# ------------------------------------------------------------- band 5: existence
def get_insurer(insurer_id):
    insurer = db.insurers.get(insurer_id)
    if insurer is None:
        raise ApiError("ERR_INSURER_NOT_FOUND", "No such insurer.")
    return insurer


def get_cycle(cycle_id):
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", "No such market-analysis cycle.")
    return cycle


def get_exam(exam_id):
    exam = db.examinations.get(exam_id)
    if exam is None:
        raise ApiError("ERR_EXAMINATION_NOT_FOUND", "No such examination.")
    return exam


def _get_exam_record(collection, record_id, label):
    record = collection.get(record_id)
    if record is None:
        raise ApiError("ERR_EXAM_RECORD_NOT_FOUND", "No such %s." % label)
    return record


def get_area(area_id):
    return _get_exam_record(db.scope_areas, area_id, "scope area")


def get_call(call_id):
    return _get_exam_record(db.data_calls, call_id, "data call")


def get_sample(sample_id):
    return _get_exam_record(db.file_samples, sample_id, "file sample")


def get_criticism(criticism_id):
    return _get_exam_record(db.criticisms, criticism_id, "criticism")


def get_plan(plan_id):
    return _get_exam_record(db.plans, plan_id, "corrective action plan")


def get_order(order_id):
    return _get_exam_record(db.consent_orders, order_id, "consent order")


def get_collaboration(collaboration_id):
    return _get_exam_record(db.collaborations, collaboration_id, "collaboration")


# ----------------------------------------------------- band 3: carrier ownership
def ensure_exam_subject(exam):
    """An InsurerRespondent may only touch records of its own examinations."""
    if exam is not None and is_respondent() and exam["insurer_id"] != current_user_id():
        raise ApiError(
            "ERR_NOT_EXAM_SUBJECT",
            "This record belongs to another carrier's examination.",
        )
    return exam


# ------------------------------------------------------- band 8: terminal guard
def ensure_exam_writable(exam):
    """ERR_EXAM_ALREADY_TERMINAL guards every write on an examination or its
    descendants once that examination is PUBLISHED or ABORTED (PRD §2.11)."""
    if exam is not None and exam["status"] in derive.TERMINAL_EXAM_STATES:
        raise ApiError(
            "ERR_EXAM_ALREADY_TERMINAL",
            "The examination is already %s." % exam["status"],
        )
    return exam
