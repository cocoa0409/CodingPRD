from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("engagements", __name__)

ACTIONS = ("START_READINESS", "START_OBSERVATION", "START_FIELDWORK", "START_REPORTING",
           "ISSUE", "ABANDON")

ACTION_ROLES = {
    "START_READINESS": {"ComplianceLead"},
    "START_OBSERVATION": {"ComplianceLead"},
    "START_FIELDWORK": {"ComplianceLead"},
    "START_REPORTING": {"Auditor"},
    "ISSUE": {"Auditor"},
    "ABANDON": {"ComplianceLead"},
}

EDGES = {
    ("SCOPING", "START_READINESS"): "READINESS",
    ("READINESS", "START_OBSERVATION"): "OBSERVATION",
    ("OBSERVATION", "START_FIELDWORK"): "FIELDWORK",
    ("FIELDWORK", "START_REPORTING"): "REPORTING",
    ("REPORTING", "ISSUE"): "ISSUED",
    ("SCOPING", "ABANDON"): "ABANDONED",
    ("READINESS", "ABANDON"): "ABANDONED",
}


def view(engagement):
    services.refresh_coverage(engagement)
    return store.public(engagement)


@bp.post("/soc/engagements")
def create_engagement():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    client_name = v.req_str(body, "client_name", 1, 200)
    report_type = v.req_enum(body, "report_type", calcs.REPORT_TYPES)
    start = v.req_dt(body, "observation_period_start")
    end = v.req_dt(body, "observation_period_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION")
    categories = v.req_enum_array(body, "required_criteria_categories", calcs.CATEGORIES)
    max_recipients = v.opt_int(body, "max_distribution_recipients", minv=1, default=5)

    engagement = store.new_row(
        "engagements",
        {
            "client_name": client_name,
            "report_type": report_type,
            "observation_period_start": store.fmt_iso(start),
            "observation_period_end": store.fmt_iso(end),
            "required_criteria_categories": categories,
            "max_distribution_recipients": max_recipients,
            "status": "SCOPING",
            "gap_posture": "OPEN",
            "gap_debt_points": 0.0,
            "base_debt_points": 0,
            "open_exception_count": 0,
            "readiness_score": 0.0,
            "criteria_in_scope_count": 0,
            "covered_criteria_count_readiness": 0,
            "covered_criteria_count_attestation": 0,
            "criteria_coverage_pct_readiness": 0.0,
            "criteria_coverage_pct_attestation": 0.0,
            "boundary_locked": False,
            "approved_system_description_id": None,
            "observation_period_days": store.floor_days(end, start),
            "readiness_assessed_at": None,
            "calendar_epoch": 0,
        },
    )
    services.refresh_engagement(engagement)
    return ok(store.public(engagement), 201)


@bp.get("/soc/engagements/<engagement_id>")
def read_engagement(engagement_id):
    auth.authenticate(ALL_ROLES)
    engagement = store.get_or_404("engagements", engagement_id)
    return ok(view(engagement))


@bp.get("/soc/engagements")
def list_engagements():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("engagements")
    status = request.args.get("status")
    report_type = request.args.get("report_type")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if report_type is not None:
        items = [e for e in items if e["report_type"] == report_type]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([view(e) for e in page], limit, offset, total)


@bp.post("/soc/engagements/<engagement_id>/transitions")
def transition_engagement(engagement_id):
    _uid, role = auth.authenticate({"ComplianceLead", "Auditor"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), ACTION_ROLES)
    engagement = store.get_or_404("engagements", engagement_id)
    action = v.req_enum(body, "action", ACTIONS)
    v.opt_str(body, "reason", 0, 2000)

    services.refresh_coverage(engagement)

    if action in ("START_REPORTING", "ISSUE"):
        services.require_posture_open(engagement)

    target = EDGES.get((engagement["status"], action))
    if target is None:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action == "START_READINESS":
        if engagement["approved_system_description_id"] is None:
            raise ApiError("ERR_INVALID_STATE")
        if not engagement["boundary_locked"]:
            raise ApiError("ERR_INVALID_STATE")
        if engagement["criteria_in_scope_count"] < 1:
            raise ApiError("ERR_INVALID_STATE")
    elif action == "START_OBSERVATION":
        if engagement["readiness_assessed_at"] is None:
            raise ApiError("ERR_INVALID_STATE")
        if engagement["gap_posture"] == "FROZEN":
            raise ApiError("ERR_INVALID_STATE")
        for control in services.controls_of(engagement["id"]):
            if not control["in_scope"]:
                continue
            if control["design_status"] != "DESIGN_APPROVED":
                raise ApiError("ERR_INVALID_STATE")
            if control["owner_user_id"] is None:
                raise ApiError("ERR_INVALID_STATE")
            if control["evidence_scheduled_count"] < 1:
                raise ApiError("ERR_INVALID_STATE")
    elif action == "START_FIELDWORK":
        end = store.parse_iso(engagement["observation_period_end"])
        if store.now_dt() < end:
            raise ApiError("ERR_INVALID_STATE")
        for req in services.evidence_of_engagement(engagement["id"]):
            if req["status"] in ("SCHEDULED", "SUBMITTED"):
                raise ApiError("ERR_INVALID_STATE")
    elif action == "START_REPORTING":
        for control in services.controls_of(engagement["id"]):
            if not control["in_scope"]:
                continue
            if control["operating_status"] not in ("TESTED_EFFECTIVE", "TESTED_EXCEPTION"):
                raise ApiError("ERR_INVALID_STATE")
        for exc in services.exceptions_of_engagement(engagement["id"]):
            if exc["disposition"] == "UNEVALUATED":
                raise ApiError("ERR_INVALID_STATE")
        for org in store.rows("subservice_organizations"):
            if org["engagement_id"] != engagement["id"]:
                continue
            if org["method"] == "CARVE_OUT" and not org["csoc_articulated"]:
                raise ApiError("ERR_CSOC_NOT_ARTICULATED")
    elif action == "ISSUE":
        if float(engagement["criteria_coverage_pct_attestation"]) != 100.00:
            raise ApiError("ERR_INVALID_STATE")

    engagement["status"] = target
    if action == "ABANDON":
        services.abandon_engagement(engagement)
    if action == "START_OBSERVATION":
        services.start_observation_cascade(engagement)
    services.bump_engagement_version(engagement)
    services.refresh_engagement(engagement)
    return ok(store.public(engagement))


@bp.get("/soc/engagements/<engagement_id>/readiness-summary")
def readiness_summary(engagement_id):
    auth.authenticate(ALL_ROLES)
    engagement = store.get_or_404("engagements", engagement_id)
    services.refresh_engagement(engagement)
    base, surcharge, total = services.debt_parts(engagement)
    return ok(
        {
            "criteria_in_scope_count": engagement["criteria_in_scope_count"],
            "covered_criteria_count_readiness": engagement["covered_criteria_count_readiness"],
            "covered_criteria_count_attestation": engagement["covered_criteria_count_attestation"],
            "criteria_coverage_pct_readiness": engagement["criteria_coverage_pct_readiness"],
            "criteria_coverage_pct_attestation": engagement["criteria_coverage_pct_attestation"],
            "readiness_score": engagement["readiness_score"],
            "base_debt_points": base,
            "surcharge_points": float(surcharge),
            "gap_debt_points": float(total),
            "gap_posture": engagement["gap_posture"],
            "open_exception_count": engagement["open_exception_count"],
            "open_gap_count": services.open_gap_count(engagement),
        }
    )


@bp.post("/soc/engagements/<engagement_id>/readiness-assessment")
def readiness_assessment(engagement_id):
    auth.authenticate({"ComplianceLead"})
    engagement = store.get_or_404("engagements", engagement_id)
    services.require_phase(engagement, {"READINESS"})
    services.refresh_coverage(engagement)
    services.run_readiness_assessment(engagement)
    services.bump_engagement_version(engagement)
    services.refresh_engagement(engagement)
    return ok(store.public(engagement))


@bp.post("/soc/engagements/<engagement_id>/calendar-run")
def calendar_run(engagement_id):
    auth.authenticate({"ComplianceLead", "PlatformAdmin"})
    engagement = store.get_or_404("engagements", engagement_id)
    report = services.calendar_run(engagement)
    return ok(report)
