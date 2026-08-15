"""CertificationProject endpoints (PRD 3.1, 3.2, 3.4, 3.7, 3.8)."""
from flask import Blueprint, request

from db import CLOCK, DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import (
    IN_REVIEW_FLIGHT,
    attempts_of_project,
    certification_fee_cents,
    get_project,
    level_of,
    locked_model,
    ser_analysis,
    ser_project,
    ser_report,
    sorted_created,
    stamp,
    sync_project_derived,
    touch,
)
from util import (
    COMPLIANCE_PATHS,
    DECISIONS,
    LEVELS,
    PHASES,
    RATING_SYSTEMS,
    RECERT_OUTCOMES,
    as_enum,
    as_int,
    as_str,
    body,
    pagination_args,
    required,
)

bp = Blueprint("projects", __name__)


@bp.post("/certification-projects")
def create_project():
    user_id, role = auth_headers()
    data = body()
    project_name = as_str(required(data, "project_name"), "project_name")
    rating_system = as_enum(required(data, "rating_system"), RATING_SYSTEMS, "rating_system")
    compliance_path = as_enum(
        required(data, "compliance_path"), COMPLIANCE_PATHS, "compliance_path"
    )
    gross_floor_area_sqft = as_int(
        required(data, "gross_floor_area_sqft"), "gross_floor_area_sqft"
    )
    if gross_floor_area_sqft <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "gross_floor_area_sqft must be > 0")
    target_level = as_enum(required(data, "target_level"), LEVELS, "target_level")
    fee_budget_cents = as_int(required(data, "fee_budget_cents"), "fee_budget_cents")
    if fee_budget_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "fee_budget_cents must be >= 0")
    require_role(role, {"ProjectAdministrator"})
    rec = stamp(
        {
            "project_name": project_name,
            "rating_system": rating_system,
            "compliance_path": compliance_path,
            "gross_floor_area_sqft": gross_floor_area_sqft,
            "target_level": target_level,
            "fee_budget_cents": fee_budget_cents,
            "administrator_id": user_id,
            "status": "REGISTERED",
            "fee_balance_cents": fee_budget_cents,
            "points_pursued_total": 0,
            "points_awarded_total": 0,
            "projected_level": "NONE",
            "conservative_level": "NONE",
            "prerequisites_satisfied": False,
            "certified_level": None,
            "certified_at": None,
            "plaque_marketing_rights_granted": False,
        }
    )
    DB["projects"][rec["id"]] = rec
    return ok(ser_project(rec), status=201)


@bp.get("/certification-projects")
def list_projects():
    auth_headers()
    status = request.args.get("status")
    administrator_id = request.args.get("administrator_id")
    items = list(DB["projects"].values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if administrator_id is not None:
        items = [p for p in items if p["administrator_id"] == administrator_id]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_project(p) for p in page], total, limit, offset)


@bp.get("/certification-projects/<project_id>")
def get_one_project(project_id):
    auth_headers()
    return ok(ser_project(get_project(project_id)))


@bp.post("/certification-projects/<project_id>/lock-strategy")
def lock_strategy(project_id):
    _user_id, role = auth_headers()
    data = body()
    expected = as_int(
        required(data, "expected_project_version"), "expected_project_version"
    )
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    # OCC precedes state and strategy checks (PRD 2.5, ladder stage 6).
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            412,
            "expected_project_version does not match the current project version",
        )
    if project["status"] != "REGISTERED":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", 409, "Project is not in REGISTERED"
        )
    live = [a for a in attempts_of_project(project["id"]) if a["status"] != "DROPPED"]
    if not live:
        raise ApiError(
            "ERR_EMPTY_CREDIT_STRATEGY", 422, "Strategy contains no credit attempts"
        )
    attempted_entry_ids = {a["credit_library_entry_id"] for a in live}
    for e in DB["credit_library_entries"].values():
        if e["is_prerequisite"] and e["id"] not in attempted_entry_ids:
            raise ApiError(
                "ERR_PREREQUISITE_CREDIT_MISSING",
                409,
                "A prerequisite credit has no attempt on this project",
            )
    project["status"] = "STRATEGY_LOCKED"
    touch(project)
    return ok(ser_project(project))


@bp.post("/certification-projects/<project_id>/submit-phase")
def submit_phase(project_id):
    user_id, role = auth_headers()
    data = body()
    phase = as_enum(required(data, "phase"), PHASES, "phase")
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    required_state = "STRATEGY_LOCKED" if phase == "DESIGN" else "DESIGN_REVIEWED"
    if project["status"] != required_state:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            f"Project must be in {required_state} to submit {phase}",
        )
    package = [
        a
        for a in attempts_of_project(project["id"])
        if a["phase"] == phase and a["status"] == "READY_FOR_SUBMITTAL"
    ]
    # Compliance gate (ladder stage 8): segregation of duties.
    for a in package:
        if a["documentation_owner_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                403,
                "Submitter is the documentation owner of an included attempt",
            )
    # Structural gates (ladder stage 10).
    if not package:
        raise ApiError(
            "ERR_EMPTY_SUBMISSION_PACKAGE",
            422,
            "No READY_FOR_SUBMITTAL attempts for this phase",
        )
    if (
        phase == "DESIGN"
        and project["compliance_path"] == "PERFORMANCE"
        and locked_model(project["id"], "PROPOSED") is None
    ):
        raise ApiError(
            "ERR_PROPOSED_MODEL_NOT_LOCKED",
            409,
            "PERFORMANCE path requires a LOCKED proposed model",
        )
    if phase == "CONSTRUCTION":
        for t in DB["commissioning_tasks"].values():
            if (
                t["project_id"] == project["id"]
                and t["is_prerequisite_linked"]
                and t["status"] != "PASSED"
            ):
                raise ApiError(
                    "ERR_COMMISSIONING_INCOMPLETE",
                    409,
                    "A prerequisite-linked commissioning task has not passed",
                )
    # Fiscal gate (ladder stage 11).
    fee = certification_fee_cents(phase, project["gross_floor_area_sqft"])
    if project["fee_balance_cents"] < fee:
        raise ApiError(
            "ERR_INSUFFICIENT_SUBMISSION_FUNDS",
            402,
            "Fee balance does not cover the phase certification fee",
        )
    for a in package:
        a["status"] = "SUBMITTED"
        a["submission_round"] += 1
        touch(a)
    project["fee_balance_cents"] -= fee
    project["status"] = "DESIGN_SUBMITTED" if phase == "DESIGN" else "CONSTRUCTION_SUBMITTED"
    sync_project_derived(project, explicit_bump=True)
    return ok(ser_project(project))


@bp.post("/certification-projects/<project_id>/withdraw-phase")
def withdraw_phase(project_id):
    _user_id, role = auth_headers()
    data = body()
    phase = as_enum(required(data, "phase"), PHASES, "phase")
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    expected_state = "DESIGN_SUBMITTED" if phase == "DESIGN" else "CONSTRUCTION_SUBMITTED"
    if project["status"] != expected_state:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            f"Project must be in {expected_state} to withdraw {phase}",
        )
    # Withdrawal is allowed only before the review body has engaged with the
    # package: any review comment on a submitted-phase attempt blocks it.
    for c in DB["review_comments"].values():
        a = DB["credit_attempts"][c["credit_attempt_id"]]
        if (
            a["project_id"] == project["id"]
            and a["phase"] == phase
            and a["status"] in IN_REVIEW_FLIGHT | {"AWARDED", "DENIED"}
        ):
            raise ApiError(
                "ERR_REVIEW_ALREADY_STARTED",
                409,
                "A review comment exists on the submitted package",
            )
    fee = certification_fee_cents(phase, project["gross_floor_area_sqft"])
    for a in attempts_of_project(project["id"]):
        if a["phase"] == phase and a["status"] == "SUBMITTED":
            a["status"] = "READY_FOR_SUBMITTAL"
            touch(a)
    project["fee_balance_cents"] += fee
    project["status"] = "STRATEGY_LOCKED" if phase == "DESIGN" else "DESIGN_REVIEWED"
    sync_project_derived(project, explicit_bump=True)
    return ok(ser_project(project))


@bp.post("/certification-projects/<project_id>/issue-decision")
def issue_decision(project_id):
    _user_id, role = auth_headers()
    data = body()
    decision = as_enum(required(data, "decision"), DECISIONS, "decision")
    require_role(role, {"CertificationReviewer"})
    project = get_project(project_id)
    if project["status"] != "CONSTRUCTION_REVIEWED":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", 409, "Project is not in CONSTRUCTION_REVIEWED"
        )
    if decision == "CERTIFY":
        # Compliance gate (stage 8) outranks the points floor (stage 10).
        prereqs_ok = all(
            a["status"] == "AWARDED"
            for a in attempts_of_project(project["id"])
            if a["is_prerequisite"] and a["status"] != "DROPPED"
        )
        if not prereqs_ok:
            raise ApiError(
                "ERR_PREREQUISITE_NOT_AWARDED",
                409,
                "A prerequisite credit attempt has not been awarded",
            )
        if project["points_awarded_total"] < 40:
            raise ApiError(
                "ERR_INSUFFICIENT_POINTS",
                422,
                "points_awarded_total is below the 40-point floor",
            )
        project["certified_level"] = level_of(project["points_awarded_total"])
        project["certified_at"] = CLOCK["current_utc"]
        project["plaque_marketing_rights_granted"] = True
        project["status"] = "CERTIFIED"
    else:
        project["status"] = "DENIED"
    touch(project)
    return ok(ser_project(project))


@bp.post("/certification-projects/<project_id>/submit-recertification")
def submit_recertification(project_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    if project["status"] != "PERFORMANCE_REPORTING":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", 409, "Project is not in PERFORMANCE_REPORTING"
        )
    accepted = [
        r
        for r in DB["performance_reports"].values()
        if r["project_id"] == project["id"] and r["status"] == "ACCEPTED"
    ]
    if len(accepted) < 2:
        raise ApiError(
            "ERR_INSUFFICIENT_PERFORMANCE_REPORTS",
            409,
            "Fewer than two accepted performance reports",
        )
    project["status"] = "RECERTIFICATION_REVIEW"
    touch(project)
    return ok(ser_project(project))


@bp.post("/certification-projects/<project_id>/confirm-recertification")
def confirm_recertification(project_id):
    _user_id, role = auth_headers()
    data = body()
    outcome = as_enum(required(data, "outcome"), RECERT_OUTCOMES, "outcome")
    require_role(role, {"CertificationReviewer"})
    project = get_project(project_id)
    if project["status"] != "RECERTIFICATION_REVIEW":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", 409, "Project is not in RECERTIFICATION_REVIEW"
        )
    if outcome == "RECERTIFY":
        project["status"] = "CERTIFIED"
        project["certified_at"] = CLOCK["current_utc"]
    else:
        project["status"] = "LAPSED"
    touch(project)
    return ok(ser_project(project))


@bp.get("/certification-projects/<project_id>/performance-reports")
def list_project_reports(project_id):
    auth_headers()
    project = get_project(project_id)
    items = sorted_created(
        [r for r in DB["performance_reports"].values() if r["project_id"] == project["id"]]
    )
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_report(r) for r in page], total, limit, offset)


@bp.get("/certification-projects/<project_id>/cost-premium-analysis")
def get_project_analysis(project_id):
    auth_headers()
    project = get_project(project_id)
    items = sorted_created(
        [
            a
            for a in DB["cost_premium_analyses"].values()
            if a["project_id"] == project["id"]
        ]
    )
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_analysis(a) for a in page], total, limit, offset)
