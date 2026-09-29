"""Lookups and the ordered guards of the request admission order (PRD 2.8)."""
import db
from errors import ApiError

# admission step 4 / 5: existence, per resource type
NOT_FOUND = {
    "engineer": "ERR_ENGINEER_NOT_FOUND",
    "reviewer": "ERR_REVIEWER_NOT_FOUND",
    "project": "ERR_PROJECT_NOT_FOUND",
    "hazard_area": "ERR_HAZARD_AREA_NOT_FOUND",
    "flow_test": "ERR_FLOW_TEST_NOT_FOUND",
    "calculation": "ERR_CALCULATION_NOT_FOUND",
    "evaluation": "ERR_EVALUATION_NOT_FOUND",
    "pump": "ERR_FIRE_PUMP_NOT_FOUND",
    "aux": "ERR_AUXILIARY_SYSTEM_NOT_FOUND",
    "shop_drawing": "ERR_SHOP_DRAWING_NOT_FOUND",
    "trade_clearance": "ERR_TRADE_CLEARANCE_NOT_FOUND",
    "submittal": "ERR_SUBMITTAL_NOT_FOUND",
    "comment": "ERR_REVIEW_COMMENT_NOT_FOUND",
    "acceptance_test": "ERR_ACCEPTANCE_TEST_NOT_FOUND",
}

STORES = {
    "engineer": db.engineers,
    "reviewer": db.ahj_reviewers,
    "project": db.projects,
    "hazard_area": db.hazard_areas,
    "flow_test": db.flow_tests,
    "calculation": db.calculations,
    "evaluation": db.evaluations,
    "pump": db.pumps,
    "aux": db.aux_systems,
    "shop_drawing": db.shop_drawings,
    "trade_clearance": db.trade_clearances,
    "submittal": db.submittals,
    "comment": db.review_comments,
    "acceptance_test": db.acceptance_tests,
}


def must(kind, row_id):
    """Resolve a row of `kind` or raise that kind's 404."""
    row = STORES[kind].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[kind], "No %s exists with id %r." % (kind.replace("_", " "), row_id))
    return row


def must_fk(kind, row_id):
    """Step 5 form: a null/absent key is deferred to the schema check."""
    if row_id is None:
        return None
    return must(kind, row_id)


def project_of(row):
    return db.projects.get(row.get("project_id"))


def require_lead_engineer(actor, project):
    """Admission step 6 - the acting DesignEngineer owns the project."""
    if actor.role != "DesignEngineer":
        return
    if project is None or actor.user_id != project.get("lead_engineer_id"):
        raise ApiError(
            "ERR_NOT_PROJECT_ENGINEER",
            "Only the project's lead engineer may perform this write.",
        )


def require_assigned_reviewer(actor, project, witness_reviewer_id=None):
    """Admission step 7 - the acting AhjReviewer is the project's examiner."""
    if actor.role == "AhjReviewer":
        if project is None or actor.user_id != project.get("ahj_reviewer_id"):
            raise ApiError(
                "ERR_NOT_ASSIGNED_REVIEWER",
                "Only the project's assigned authority reviewer may perform this write.",
            )
    if witness_reviewer_id is not None:
        if project is None or witness_reviewer_id != project.get("ahj_reviewer_id"):
            raise ApiError(
                "ERR_NOT_ASSIGNED_REVIEWER",
                "witness_reviewer_id must name the project's assigned reviewer.",
            )


def require_segregation(actor, calculation):
    """Admission step 8 - a QcReviewer may not review their own calculation."""
    if actor.role != "QcReviewer":
        return
    if actor.user_id == calculation.get("authored_by_engineer_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The author of a calculation may not perform its independent QC review.",
        )


def require_not_frozen(project):
    """Admission step 13 - the frozen design-mutation set (PRD 2.5)."""
    if project.get("design_posture") == "FROZEN":
        raise ApiError(
            "ERR_PROJECT_POSTURE_FROZEN",
            "The project's design posture is FROZEN; design mutations are refused.",
        )


def require_not_gated(project):
    """Admission step 14 - the three package-advancing writes (PRD 2.5)."""
    if project.get("design_posture") == "GATED":
        raise ApiError(
            "ERR_PROJECT_POSTURE_GATED",
            "The project's design posture is GATED; this write is refused while a MAJOR comment is open.",
        )


def require_project_open(project):
    """Admission step 15 - CLOSED_OUT is terminal for the project (PRD 2.12)."""
    if project.get("status") == "CLOSED_OUT":
        raise ApiError(
            "ERR_TERMINAL_STATE_LOCKED",
            "The project is CLOSED_OUT; nothing further may be written against it.",
        )


def terminal(message="The target row is in a terminal state."):
    raise ApiError("ERR_TERMINAL_STATE_LOCKED", message)


def invalid_transition(message="The requested transition is not declared for the row's current state."):
    raise ApiError("ERR_INVALID_STATE_TRANSITION", message)
