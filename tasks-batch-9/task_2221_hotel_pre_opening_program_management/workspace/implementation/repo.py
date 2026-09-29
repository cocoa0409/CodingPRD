"""Lookup helpers, enum vocabularies and serialization."""
from db import db, sort_created
from errors import ApiError

# --- enum vocabularies -----------------------------------------------------
SCHEDULE_STATES = ("PLANNING", "BASELINED", "CONSTRUCTION_COMPLETE", "LICENSING",
                   "SOFT_OPENING", "STABILIZED")
COMMERCIAL_STATES = ("BOOKING_CLOSED", "BOOKING_OPEN", "BOOKING_SUSPENDED",
                     "SELLING_STABILIZED")
POSTURES = ("MOBILIZING", "ON_TRACK", "RESTRICTED", "FROZEN")
MILESTONE_STATES = ("NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETE", "REOPENED")
DEPENDENCY_TYPES = ("FINISH_START", "START_START")
PERMIT_TYPES = ("CERTIFICATE_OF_OCCUPANCY", "LIQUOR_LICENSE", "FOOD_SERVICE",
                "ELEVATOR", "FIRE_ALARM", "SIGNAGE")
MANDATORY_PERMIT_TYPES = ("CERTIFICATE_OF_OCCUPANCY", "LIQUOR_LICENSE",
                          "FOOD_SERVICE", "ELEVATOR")
PERMIT_PREREQUISITES = {
    "CERTIFICATE_OF_OCCUPANCY": ("ELEVATOR",),
    "LIQUOR_LICENSE": ("CERTIFICATE_OF_OCCUPANCY", "FOOD_SERVICE"),
    "FOOD_SERVICE": (),
    "ELEVATOR": (),
    "FIRE_ALARM": (),
    "SIGNAGE": (),
}
PERMIT_STATES = ("DRAFT", "SUBMITTED", "DEFICIENT", "ISSUED")
SYSTEM_TYPES = ("PMS", "POS", "KEY", "REVENUE")
SYSTEM_STATES = ("PLANNED", "TESTING", "FAILED", "CERTIFIED")
DEPARTMENTS = ("ROOMS", "FOOD_BEVERAGE", "ENGINEERING", "SALES_MARKETING", "ADMIN")
SESSION_DEPARTMENTS = ("ALL",) + DEPARTMENTS
HIRE_STATES = ("OFFERED", "ACCEPTED", "DECLINED", "ONBOARDED", "WITHDRAWN")
READINESS_FLAGS = ("NOT_READY", "READY")
SESSION_STATES = ("SCHEDULED", "COMPLETED", "CANCELLED")
BUDGET_CATEGORIES = ("PAYROLL", "MARKETING", "SETUP")
ORDER_STATES = ("COMMITTED", "STORED", "CANCELLED")
BLOCK_STATES = ("ACCEPTED", "GUARANTEED", "AT_RISK", "RELOCATED", "CANCELLED", "HONORED")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
PUNCH_STATES = ("OPEN", "READY_FOR_VERIFICATION", "REJECTED", "VERIFIED")

BLOCK_LIVE_STATES = ("ACCEPTED", "GUARANTEED", "AT_RISK")


# --- lookups ---------------------------------------------------------------

def _get(collection, rid, error_id):
    rec = getattr(db, collection).get(rid)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_program(rid):
    return _get("programs", rid, "ERR_PROGRAM_NOT_FOUND")


def get_milestone(rid):
    return _get("milestones", rid, "ERR_MILESTONE_NOT_FOUND")


def get_permit(rid):
    return _get("permits", rid, "ERR_PERMIT_APPLICATION_NOT_FOUND")


def get_system(rid):
    return _get("systems", rid, "ERR_SYSTEM_IMPLEMENTATION_NOT_FOUND")


def get_plan(rid):
    return _get("hiring_plans", rid, "ERR_HIRING_PLAN_NOT_FOUND")


def get_hire(rid):
    return _get("hires", rid, "ERR_HIRE_NOT_FOUND")


def get_session(rid):
    return _get("training_sessions", rid, "ERR_TRAINING_SESSION_NOT_FOUND")


def get_budget_line(rid):
    return _get("budget_lines", rid, "ERR_BUDGET_LINE_NOT_FOUND")


def get_order(rid):
    return _get("ose_orders", rid, "ERR_OSE_ORDER_NOT_FOUND")


def get_block(rid):
    return _get("reservation_blocks", rid, "ERR_RESERVATION_BLOCK_NOT_FOUND")


def get_punch(rid):
    return _get("punch_items", rid, "ERR_PUNCH_LIST_ITEM_NOT_FOUND")


# --- child collections -----------------------------------------------------

def _children(collection, field, value):
    return sort_created([r for r in getattr(db, collection).values() if r.get(field) == value])


def milestones_of(program_id):
    return _children("milestones", "program_id", program_id)


def permits_of(program_id):
    return _children("permits", "program_id", program_id)


def systems_of(program_id):
    return _children("systems", "program_id", program_id)


def plans_of(program_id):
    return _children("hiring_plans", "program_id", program_id)


def sessions_of(program_id):
    return _children("training_sessions", "program_id", program_id)


def budget_lines_of(program_id):
    return _children("budget_lines", "program_id", program_id)


def orders_of(program_id):
    return _children("ose_orders", "program_id", program_id)


def blocks_of(program_id):
    return _children("reservation_blocks", "program_id", program_id)


def punch_items_of(program_id):
    return _children("punch_items", "program_id", program_id)


def hires_of_plan(plan_id):
    return _children("hires", "hiring_plan_id", plan_id)


def hires_of_program(program_id):
    plan_ids = {p["id"] for p in plans_of(program_id)}
    return sort_created([h for h in db.hires.values() if h["hiring_plan_id"] in plan_ids])


def test_runs_of(system_id):
    return _children("test_runs", "system_implementation_id", system_id)


def dependencies_of_program(program_id):
    ids = {m["id"] for m in db.milestones.values() if m["program_id"] == program_id}
    return sort_created([
        d for d in db.dependencies.values()
        if d["predecessor_milestone_id"] in ids and d["successor_milestone_id"] in ids
    ])


def program_of_hire(hire):
    plan = db.hiring_plans.get(hire["hiring_plan_id"])
    if plan is None:
        return None
    return db.programs.get(plan["program_id"])


# --- serialization ---------------------------------------------------------

def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_many(records):
    return [serialize(r) for r in records]
