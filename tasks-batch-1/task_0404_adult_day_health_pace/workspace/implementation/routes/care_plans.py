"""Care plan + goals + signing + review/activation lifecycle. PRD §3.3."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c

bp = Blueprint("care_plans", __name__)

DISCIPLINES = {"RN", "SW", "PT", "DIETICIAN", "MEDICAL_DIRECTOR"}
GOAL_STATUSES = {"OPEN", "MET", "DISCONTINUED"}


def care_plan_view(p):
    return dict(p)


def goal_view(g):
    return dict(g)


def _discontinue_plan_orders(care_plan_id):
    """Cascade: MedicationOrders of a plan in {ORDERED, ACTIVE, HELD} →
    DISCONTINUED (PRD §3.3 / §3.8)."""
    for order in db.medication_orders.values():
        if order["care_plan_id"] == care_plan_id and order["status"] in (
                "ORDERED", "ACTIVE", "HELD"):
            order["status"] = "DISCONTINUED"
            c.touch(order)


# --- Create / read ---
@bp.post("/pace/care-plans")
@require_roles("IntakeCoordinator")
def create_care_plan():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    supersedes = c.as_str(body, "supersedes_care_plan_id", required=False, default=None)
    required = body.get("required_disciplines", None)
    c.find_or_404(db.participants, participant_id)
    if supersedes is not None:
        c.find_or_404(db.care_plans, supersedes)

    if required is None:
        required_disciplines = ["RN", "SW", "MEDICAL_DIRECTOR"]
    else:
        if not isinstance(required, list) or not all(
                isinstance(x, str) and x in DISCIPLINES for x in required):
            raise err("ERR_INVALID_REQUEST", "required_disciplines invalid")
        required_disciplines = list(required)

    p = c.base_fields()
    p.update({
        "participant_id": participant_id,
        "supersedes_care_plan_id": supersedes,
        "idt_disciplines_signed": [],
        "required_disciplines": required_disciplines,
        "goal_count": 0,
        "status": "DRAFT",
    })
    db.care_plans[p["id"]] = p
    return success(care_plan_view(p), status=201)


@bp.get("/pace/care-plans/<care_plan_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_care_plan(care_plan_id):
    p = c.find_or_404(db.care_plans, care_plan_id)
    return success(care_plan_view(p))


@bp.get("/pace/care-plans")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def list_care_plans():
    limit, offset = c.get_pagination()
    items = list(db.care_plans.values())
    for key in ("participant_id", "supersedes_care_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([care_plan_view(p) for p in page], limit, offset, total)


# --- Goals ---
@bp.post("/pace/care-plans/<care_plan_id>/goals")
@require_roles("IntakeCoordinator", "MedicalDirector")
def add_goal(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    body = c.get_body()
    discipline = c.as_enum(body, "discipline", DISCIPLINES)
    description = c.as_str(body, "description")
    target = c.as_int(body, "target_attendance_days", required=False, default=0, min_val=0)

    g = c.base_fields()
    g.update({
        "care_plan_id": care_plan_id,
        "discipline": discipline,
        "description": description,
        "target_attendance_days": target,
        "status": "OPEN",
    })
    db.care_plan_goals[g["id"]] = g
    plan["goal_count"] = plan["goal_count"] + 1
    c.touch(plan)
    return success(goal_view(g), status=201)


@bp.get("/pace/care-plan-goals/<goal_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_goal(goal_id):
    g = c.find_or_404(db.care_plan_goals, goal_id)
    return success(goal_view(g))


@bp.get("/pace/care-plan-goals")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def list_goals():
    limit, offset = c.get_pagination()
    items = list(db.care_plan_goals.values())
    for key in ("care_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [g for g in items if g.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([goal_view(g) for g in page], limit, offset, total)


# --- Sign ---
@bp.post("/pace/care-plans/<care_plan_id>/sign")
@require_roles("MedicalDirector", "NurseStaff", "IntakeCoordinator")
def sign_care_plan(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    body = c.get_body()
    discipline = c.as_enum(body, "discipline", DISCIPLINES)
    # idempotent set insertion
    if discipline not in plan["idt_disciplines_signed"]:
        plan["idt_disciplines_signed"].append(discipline)
    c.touch(plan)
    return success(care_plan_view(plan))


# --- Lifecycle ---
@bp.post("/pace/care-plans/<care_plan_id>/submit")
@require_roles("IntakeCoordinator")
def submit_care_plan(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    # DRAFT or REVISION → IN_REVIEW
    if plan["status"] not in ("DRAFT", "REVISION"):
        raise err("ERR_INVALID_STATE", "Care plan not DRAFT/REVISION")
    if plan["goal_count"] < 1:
        raise err("ERR_CARE_PLAN_NO_GOALS", "Care plan has no goals")
    plan["status"] = "IN_REVIEW"
    c.touch(plan)
    return success(care_plan_view(plan))


@bp.post("/pace/care-plans/<care_plan_id>/request-revision")
@require_roles("MedicalDirector")
def request_revision(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    if plan["status"] not in ("IN_REVIEW", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Care plan not IN_REVIEW/ACTIVE")
    plan["status"] = "REVISION"
    plan["idt_disciplines_signed"] = []
    c.touch(plan)
    return success(care_plan_view(plan))


@bp.post("/pace/care-plans/<care_plan_id>/activate")
@require_roles("MedicalDirector")
def activate_care_plan(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    if plan["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Care plan not IN_REVIEW")
    # IDT completeness: required ⊆ signed (priority 11)
    required = set(plan["required_disciplines"])
    signed = set(plan["idt_disciplines_signed"])
    if not required.issubset(signed):
        raise err("ERR_IDT_INCOMPLETE", "Required IDT signature missing")

    participant = db.participants.get(plan["participant_id"])
    prior_id = participant.get("active_care_plan_id") if participant else None
    # Supersede the prior active plan (if any, and different)
    if prior_id and prior_id != plan["id"]:
        prior = db.care_plans.get(prior_id)
        if prior and prior["status"] == "ACTIVE":
            prior["status"] = "SUPERSEDED"
            c.touch(prior)
            _discontinue_plan_orders(prior["id"])

    plan["status"] = "ACTIVE"
    c.touch(plan)
    if participant:
        participant["active_care_plan_id"] = plan["id"]
        c.touch(participant)
    return success(care_plan_view(plan))


@bp.post("/pace/care-plans/<care_plan_id>/void")
@require_roles("IntakeCoordinator")
def void_care_plan(care_plan_id):
    plan = c.find_or_404(db.care_plans, care_plan_id)
    participant = db.participants.get(plan["participant_id"])
    if participant and participant.get("active_care_plan_id") == plan["id"]:
        raise err("ERR_CANNOT_VOID_ACTIVE", "Cannot void the active care plan")
    if plan["status"] not in ("DRAFT", "IN_REVIEW", "REVISION"):
        raise err("ERR_INVALID_STATE", "Care plan not DRAFT/IN_REVIEW/REVISION")
    plan["status"] = "VOID"
    c.touch(plan)
    return success(care_plan_view(plan))
