"""Project routes: CRUD, posture lifecycle, daily scan."""
from flask import Blueprint

from authz import ALL_ROLES, PLATFORM_ADMIN, PROJECT_MANAGER, require_roles
from db import store
from errors import (
    closeout_blocked,
    invalid_project_state,
    invalid_request,
    project_not_found,
)
from respond import success
from serialize import ser_project
from services import require_active, run_daily_scan
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_int,
    opt_str,
    opt_str_list,
    paginate,
    req_date,
    opt_date,
    req_field,
    req_str,
    sorted_by_creation,
    touch,
)
from timeutil import parse_holidays

bp = Blueprint("projects", __name__)


def get_project_or_404(project_id):
    p = store.projects.get(project_id)
    if p is None:
        raise project_not_found()
    return p


@bp.route("/v1/projects", methods=["POST"])
def create_project():
    uid, role = require_roles([PLATFORM_ADMIN])
    data = json_body()
    project_name = req_str(data, "project_name")
    contract_start_date = opt_date(data, "contract_start_date", None)
    rfi_response_days = opt_int(data, "rfi_response_days", 10, minimum=1)
    ack_required_days = opt_int(data, "ack_required_days", 5, minimum=1)
    mobilization_buffer_days = opt_int(data, "mobilization_buffer_days", 2, minimum=0)
    long_lead_threshold_days = opt_int(data, "long_lead_threshold_days", 30, minimum=1)
    expedite_window_days = opt_int(data, "expedite_window_days", 10, minimum=0)
    initial_contingency_cents = opt_int(data, "initial_contingency_cents", 0, minimum=0)
    gc_tier_threshold_cents = opt_int(data, "gc_tier_threshold_cents", 1000000, minimum=0)
    holidays_raw = opt_str_list(data, "holiday_dates", []) or []
    try:
        holidays_set = parse_holidays(holidays_raw)
    except ValueError:
        raise invalid_request("holiday_dates members must be YYYY-MM-DD strings")

    project = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_name": project_name,
        "contract_start_date": contract_start_date,
        "rfi_response_days": rfi_response_days,
        "ack_required_days": ack_required_days,
        "mobilization_buffer_days": mobilization_buffer_days,
        "long_lead_threshold_days": long_lead_threshold_days,
        "expedite_window_days": expedite_window_days,
        "holiday_dates": holidays_raw,
        "_holidays_set": holidays_set,
        "initial_contingency_cents": initial_contingency_cents,
        "contingency_reserved_cents": 0,
        "contingency_spent_cents": 0,
        "contingency_available_cents": initial_contingency_cents,
        "gc_tier_threshold_cents": gc_tier_threshold_cents,
        "ops_scan_index": 0,
        "posture": "SETUP",
    }
    store.projects[project["id"]] = project
    return success(ser_project(project), status=201)


@bp.route("/v1/projects", methods=["GET"])
def list_projects():
    require_roles(ALL_ROLES)
    items = sorted_by_creation(store.projects.values())
    page, pagination = paginate(items)
    return success([ser_project(p) for p in page], response_type="array", pagination=pagination)


@bp.route("/v1/projects/<projectId>", methods=["GET"])
def get_project(projectId):
    require_roles(ALL_ROLES)
    project = get_project_or_404(projectId)
    return success(ser_project(project))


@bp.route("/v1/projects/<projectId>", methods=["PATCH"])
def patch_project(projectId):
    require_roles([PLATFORM_ADMIN])
    project = get_project_or_404(projectId)
    if project["posture"] != "SETUP":
        raise invalid_project_state("Project settings may only be edited while SETUP")
    data = json_body()
    if "project_name" in data and data["project_name"] is not None:
        project["project_name"] = req_str(data, "project_name")
    if "contract_start_date" in data:
        project["contract_start_date"] = opt_date(data, "contract_start_date", None)
    if "rfi_response_days" in data and data["rfi_response_days"] is not None:
        project["rfi_response_days"] = opt_int(data, "rfi_response_days", None, minimum=1)
    if "ack_required_days" in data and data["ack_required_days"] is not None:
        project["ack_required_days"] = opt_int(data, "ack_required_days", None, minimum=1)
    if "mobilization_buffer_days" in data and data["mobilization_buffer_days"] is not None:
        project["mobilization_buffer_days"] = opt_int(data, "mobilization_buffer_days", None, minimum=0)
    if "long_lead_threshold_days" in data and data["long_lead_threshold_days"] is not None:
        project["long_lead_threshold_days"] = opt_int(data, "long_lead_threshold_days", None, minimum=1)
    if "expedite_window_days" in data and data["expedite_window_days"] is not None:
        project["expedite_window_days"] = opt_int(data, "expedite_window_days", None, minimum=0)
    if "initial_contingency_cents" in data and data["initial_contingency_cents"] is not None:
        new_seed = opt_int(data, "initial_contingency_cents", None, minimum=0)
        # Keep conservation invariant: available = seed - reserved - spent.
        delta = new_seed - project["initial_contingency_cents"]
        project["initial_contingency_cents"] = new_seed
        project["contingency_available_cents"] += delta
    if "gc_tier_threshold_cents" in data and data["gc_tier_threshold_cents"] is not None:
        project["gc_tier_threshold_cents"] = opt_int(data, "gc_tier_threshold_cents", None, minimum=0)
    if "holiday_dates" in data and data["holiday_dates"] is not None:
        raw = opt_str_list(data, "holiday_dates", []) or []
        try:
            hs = parse_holidays(raw)
        except ValueError:
            raise invalid_request("holiday_dates members must be YYYY-MM-DD strings")
        project["holiday_dates"] = raw
        project["_holidays_set"] = hs
    touch(project)
    return success(ser_project(project))


def _posture_transition(projectId, from_state, to_state):
    require_roles([PROJECT_MANAGER])
    project = get_project_or_404(projectId)
    if project["posture"] != from_state:
        raise invalid_project_state(
            "Transition requires posture == %s (current: %s)" % (from_state, project["posture"])
        )
    project["posture"] = to_state
    touch(project)
    return success(ser_project(project))


@bp.route("/v1/projects/<projectId>/activate", methods=["POST"])
def activate_project(projectId):
    return _posture_transition(projectId, "SETUP", "ACTIVE")


@bp.route("/v1/projects/<projectId>/suspend", methods=["POST"])
def suspend_project(projectId):
    return _posture_transition(projectId, "ACTIVE", "SUSPENDED")


@bp.route("/v1/projects/<projectId>/resume", methods=["POST"])
def resume_project(projectId):
    return _posture_transition(projectId, "SUSPENDED", "ACTIVE")


@bp.route("/v1/projects/<projectId>/close", methods=["POST"])
def close_project(projectId):
    return _posture_transition(projectId, "CLOSEOUT", "CLOSED")


@bp.route("/v1/projects/<projectId>/begin-closeout", methods=["POST"])
def begin_closeout(projectId):
    require_roles([PROJECT_MANAGER])
    project = get_project_or_404(projectId)
    if project["posture"] != "ACTIVE":
        raise invalid_project_state("begin-closeout requires posture == ACTIVE")
    pid = project["id"]
    # Open-item gate (PRD 3.1)
    for s in store.submittals.values():
        if s["project_id"] != pid:
            continue
        if s["review_status"] in ("CLOSED", "VOID"):
            continue
        if s["deferral_status"] == "DEFERRED_APPROVED":
            continue
        raise closeout_blocked("Open submittal %s blocks closeout" % s["id"])
    for r in store.rfis.values():
        if r["project_id"] == pid and r["status"] not in ("CLOSED", "VOID"):
            raise closeout_blocked("Open RFI %s blocks closeout" % r["id"])
    for a in store.impact_assessments.values():
        if a["project_id"] == pid and a["status"] not in ("ACCEPTED", "WAIVED"):
            raise closeout_blocked("Open impact assessment %s blocks closeout" % a["id"])
    for d in store.distribution_records.values():
        if d["project_id"] == pid and d["status"] != "ACKNOWLEDGED":
            raise closeout_blocked("Unacknowledged distribution %s blocks closeout" % d["id"])
    for act in store.installation_activities.values():
        if act["project_id"] == pid and act["status"] not in ("COMPLETED", "CANCELLED"):
            raise closeout_blocked("Open installation activity %s blocks closeout" % act["id"])
    for rep in store.owner_reports.values():
        if rep["project_id"] == pid and rep["status"] == "DRAFT":
            raise closeout_blocked("DRAFT owner report %s blocks closeout" % rep["id"])
    project["posture"] = "CLOSEOUT"
    touch(project)
    return success(ser_project(project))


@bp.route("/v1/projects/<projectId>/run-daily-scan", methods=["POST"])
def run_daily_scan_endpoint(projectId):
    require_roles([PROJECT_MANAGER])
    project = get_project_or_404(projectId)
    require_active(project)
    run_daily_scan(project)
    project["ops_scan_index"] += 1
    touch(project)
    return success(ser_project(project))
