"""RFI routes: create (OCC), route, answer, reopen, distribute, close, void."""
from flask import Blueprint, request

import calc
from authz import (
    ALL_ROLES,
    PROJECT_ENGINEER,
    PROJECT_MANAGER,
    REVIEWER,
    SUBCONTRACTOR_REP,
    require_roles,
)
from db import store
from errors import (
    already_distributed,
    assessment_open_on_close,
    invalid_request,
    no_distribution_targets,
    no_eligible_reviewer,
    discipline_mismatch,
    project_not_found,
    reopen_blocked_by_priced,
    reviewer_not_assigned,
    reviewer_not_found,
    rfi_invalid_state,
    rfi_not_found,
    stale_project_version,
    subcontractor_not_found,
    submittal_not_found,
    submittal_terminal,
    spec_section_not_found,
)
from respond import success
from serialize import ser_rfi, ser_distribution
from services import (
    affected_subcontractor_ids,
    create_distribution_records,
    require_active,
)
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_enum,
    opt_int,
    opt_str,
    opt_bool,
    paginate,
    req_bool,
    req_field,
    req_int,
    req_str,
    sorted_by_creation,
    touch,
)

bp = Blueprint("rfis", __name__)

PRIORITIES = ("LOW", "NORMAL", "HIGH", "CRITICAL")
DISCIPLINES = ("ARCH", "STRUCT", "MEP", "CIVIL")


def get_rfi_or_404(rfi_id):
    r = store.rfis.get(rfi_id)
    if r is None:
        raise rfi_not_found()
    return r


def _next_rfi_number(project_id):
    n = sum(1 for r in store.rfis.values() if r["project_id"] == project_id) + 1
    return "RFI-%04d" % n


@bp.route("/v1/projects/<projectId>/rfis", methods=["POST"])
def create_rfi(projectId):
    uid, role = require_roles([PROJECT_ENGINEER, SUBCONTRACTOR_REP])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    data = json_body()
    subject = req_str(data, "subject")
    question_text = req_str(data, "question_text")
    expected_project_version = req_int(data, "expected_project_version")
    spec_section_id = opt_str(data, "spec_section_id", None)
    submittal_id = opt_str(data, "submittal_id", None)
    priority = opt_enum(data, "priority", PRIORITIES, "NORMAL")
    required_discipline = opt_enum(data, "required_discipline", DISCIPLINES, "ARCH")

    # Body FK existence within the same project
    if spec_section_id is not None:
        sec = store.spec_sections.get(spec_section_id)
        if sec is None or sec["project_id"] != projectId:
            raise spec_section_not_found()
    if submittal_id is not None:
        sub = store.submittals.get(submittal_id)
        if sub is None or sub["project_id"] != projectId:
            raise submittal_not_found()

    # SubcontractorRep creators must belong to the project
    if role == SUBCONTRACTOR_REP:
        sub_entity = store.subcontractors.get(uid)
        if sub_entity is None or sub_entity["project_id"] != projectId:
            raise subcontractor_not_found()

    # OCC (PRD §2.10 step 6) precedes posture (7) and state (8)
    if project["version"] != expected_project_version:
        raise stale_project_version()

    require_active(project)

    if submittal_id is not None:
        if sub["review_status"] in ("CLOSED", "VOID"):
            raise submittal_terminal()

    opened = calc.clock_date()
    due = calc.add_business_days(opened, project["rfi_response_days"], calc.holidays_set(project))
    rfi = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "rfi_number": _next_rfi_number(projectId),
        "subject": subject,
        "question_text": question_text,
        "spec_section_id": spec_section_id,
        "submittal_id": submittal_id,
        "priority": priority,
        "required_discipline": required_discipline,
        "status": "OPEN",
        "cycle_count": 0,
        "opened_date": opened,
        "due_date": due,
        "is_overdue": False,
        "routed_reviewer_id": None,
        "routed_date": None,
        "answer_text": None,
        "answered_date": None,
        "answered_by_reviewer_id": None,
        "is_late_answer": False,
        "cost_impact_flag": False,
        "schedule_impact_flag": False,
        "estimated_schedule_days": None,
    }
    store.rfis[rfi["id"]] = rfi
    touch(project)
    return success(ser_rfi(rfi), status=201)


@bp.route("/v1/projects/<projectId>/rfis", methods=["GET"])
def list_project_rfis(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [r for r in store.rfis.values() if r["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_rfi(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/rfis", methods=["GET"])
def list_rfis():
    require_roles(ALL_ROLES)
    items = list(store.rfis.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [r for r in items if r["project_id"] == project_id]
    spec_section_id = request.args.get("spec_section_id")
    if spec_section_id:
        items = [r for r in items if r.get("spec_section_id") == spec_section_id]
    submittal_id = request.args.get("submittal_id")
    if submittal_id:
        items = [r for r in items if r.get("submittal_id") == submittal_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    is_overdue = request.args.get("is_overdue")
    if is_overdue is not None:
        target = is_overdue.lower() == "true"
        items = [r for r in items if r["is_overdue"] == target]
    routed_reviewer_id = request.args.get("routed_reviewer_id")
    if routed_reviewer_id:
        items = [r for r in items if r.get("routed_reviewer_id") == routed_reviewer_id]
    answered_by_reviewer_id = request.args.get("answered_by_reviewer_id")
    if answered_by_reviewer_id:
        items = [r for r in items if r.get("answered_by_reviewer_id") == answered_by_reviewer_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_rfi(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/rfis/<rfiId>", methods=["GET"])
def get_rfi(rfiId):
    require_roles(ALL_ROLES)
    rfi = get_rfi_or_404(rfiId)
    return success(ser_rfi(rfi))


@bp.route("/v1/rfis/<rfiId>/route", methods=["POST"])
def route_rfi(rfiId):
    require_roles([PROJECT_ENGINEER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] != "OPEN":
        raise rfi_invalid_state()
    data = json_body()
    reviewer_id = opt_str(data, "reviewer_id", None)
    if reviewer_id is not None:
        reviewer = store.reviewers.get(reviewer_id)
        if reviewer is None or reviewer["project_id"] != project["id"]:
            raise reviewer_not_found()
        if reviewer["reviewer_status"] != "ACTIVE":
            raise no_eligible_reviewer("Reviewer is not ACTIVE")
        if reviewer["discipline"] != rfi["required_discipline"]:
            raise discipline_mismatch()
        if reviewer["open_review_count"] >= reviewer["review_capacity"]:
            from errors import reviewer_at_capacity
            raise reviewer_at_capacity()
    else:
        reviewer = calc.select_reviewer(project["id"], rfi["required_discipline"])
        if reviewer is None:
            raise no_eligible_reviewer()
    rfi["routed_reviewer_id"] = reviewer["id"]
    rfi["routed_date"] = calc.clock_date()
    rfi["status"] = "ROUTED"
    touch(rfi)
    return success(ser_rfi(rfi))


@bp.route("/v1/rfis/<rfiId>/answer", methods=["POST"])
def answer_rfi(rfiId):
    uid, role = require_roles([REVIEWER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] != "ROUTED":
        raise rfi_invalid_state()
    if uid != rfi.get("routed_reviewer_id"):
        raise reviewer_not_assigned()
    data = json_body()
    answer_text = req_str(data, "answer_text")
    cost_impact_flag = req_bool(data, "cost_impact_flag")
    schedule_impact_flag = req_bool(data, "schedule_impact_flag")
    estimated_cost_cents = None
    estimated_schedule_days = None
    if cost_impact_flag:
        estimated_cost_cents = req_int(data, "estimated_cost_cents", minimum=0)
    if schedule_impact_flag:
        estimated_schedule_days = req_int(data, "estimated_schedule_days", minimum=0)

    answered = calc.clock_date()
    rfi["answer_text"] = answer_text
    rfi["answered_date"] = answered
    rfi["answered_by_reviewer_id"] = uid
    rfi["cost_impact_flag"] = cost_impact_flag
    rfi["schedule_impact_flag"] = schedule_impact_flag
    rfi["estimated_schedule_days"] = estimated_schedule_days
    rfi["is_late_answer"] = answered > rfi["due_date"] if rfi.get("due_date") else False
    rfi["status"] = "ANSWERED"

    # Auto-create ImpactAssessment when cost_impact_flag
    if cost_impact_flag:
        assessment = {
            "id": new_id(),
            "_seq": next(store.seq),
            **new_common_fields(),
            "project_id": project["id"],
            "rfi_id": rfi["id"],
            "status": "ESTIMATED",
            "estimated_cost_cents": estimated_cost_cents,
            "provisional_delta_cents": calc.impact_cost_delta_provisional(estimated_cost_cents),
            "sub_quote_cents": None,
            "gc_markup_tier": None,
            "final_delta_cents": None,
            "priced_by_user_id": None,
            "decided_by_user_id": None,
            "price_cycle": 0,
        }
        store.impact_assessments[assessment["id"]] = assessment
    touch(rfi)
    return success(ser_rfi(rfi))


@bp.route("/v1/rfis/<rfiId>/reopen", methods=["POST"])
def reopen_rfi(rfiId):
    require_roles([PROJECT_ENGINEER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] != "ANSWERED":
        raise rfi_invalid_state()
    # Block when an assessment holds a reservation
    for a in store.impact_assessments.values():
        if a["rfi_id"] == rfi["id"] and a["status"] in ("PRICED", "DISPUTED"):
            raise reopen_blocked_by_priced()
    # Auto-void a lingering ESTIMATED assessment
    for a in store.impact_assessments.values():
        if a["rfi_id"] == rfi["id"] and a["status"] == "ESTIMATED":
            a["status"] = "WAIVED"
            touch(a)
    rfi["cycle_count"] += 1
    rfi["answer_text"] = None
    rfi["answered_date"] = None
    rfi["answered_by_reviewer_id"] = None
    rfi["cost_impact_flag"] = False
    rfi["schedule_impact_flag"] = False
    rfi["estimated_schedule_days"] = None
    rfi["is_overdue"] = False
    rfi["is_late_answer"] = False
    rfi["due_date"] = calc.add_business_days(
        calc.clock_date(), project["rfi_response_days"], calc.holidays_set(project)
    )
    rfi["status"] = "ROUTED"
    touch(rfi)
    return success(ser_rfi(rfi))


@bp.route("/v1/rfis/<rfiId>/distribute", methods=["POST"])
def distribute_rfi(rfiId):
    require_roles([PROJECT_ENGINEER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] != "ANSWERED":
        raise rfi_invalid_state()
    # Repeat distribute check
    existing = [
        d for d in store.distribution_records.values()
        if d["source_type"] == "RFI" and d["source_id"] == rfi["id"]
    ]
    if existing:
        raise already_distributed()
    section = store.spec_sections.get(rfi["spec_section_id"]) if rfi.get("spec_section_id") else None
    subs = affected_subcontractor_ids(project["id"], section, rfi.get("submittal_id"))
    if not subs:
        raise no_distribution_targets()
    records = create_distribution_records(project["id"], "RFI", rfi["id"], subs)
    return success([ser_distribution(d) for d in records], response_type="array", pagination={
        "limit": len(records), "offset": 0, "total_count": len(records), "has_more": False,
    })


@bp.route("/v1/rfis/<rfiId>/close", methods=["POST"])
def close_rfi(rfiId):
    require_roles([PROJECT_ENGINEER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] != "ANSWERED":
        raise rfi_invalid_state()
    for a in store.impact_assessments.values():
        if a["rfi_id"] == rfi["id"] and a["status"] in ("ESTIMATED", "PRICED", "DISPUTED"):
            raise assessment_open_on_close()
    rfi["status"] = "CLOSED"
    touch(rfi)
    return success(ser_rfi(rfi))


@bp.route("/v1/rfis/<rfiId>/void", methods=["POST"])
def void_rfi(rfiId):
    require_roles([PROJECT_MANAGER])
    rfi = get_rfi_or_404(rfiId)
    project = store.projects.get(rfi["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rfi["status"] in ("CLOSED", "VOID"):
        raise rfi_invalid_state()
    rfi["status"] = "VOID"
    touch(rfi)
    return success(ser_rfi(rfi))
