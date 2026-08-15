"""Clock, Employer, Plan, PlanVersion, PlanYear, RegulatoryLimit routes."""

import re
from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from db import clock, store
from errors import (
    ApiError, ERR_CENSUS_INCOMPLETE, ERR_DUPLICATE, ERR_EMPLOYER_ARCHIVED,
    ERR_FK_INTEGRITY, ERR_INVALID_DATE_RANGE, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_PENDING_WORK, ERR_PLAN_TERMINATED,
    ERR_STALE_VERSION, ERR_UNRESOLVED_FAILURES,
)
from middleware import (
    READ_ROLES, ROLE_PLAN_ADMINISTRATOR, ROLE_PLATFORM_ADMIN, require_roles,
)
from response import success_list, success_object
from services import amendment as amendment_svc
from services import correction as correction_svc
from services import safe_harbor as sh_svc
from services.common import (
    active_limit_for_year, adopted_version_covering, bump, comp_sum,
    employees_of_year, fmt_dt, get_body, get_employer, get_plan,
    get_plan_version, get_plan_year, new_entity, opt_bool, opt_date,
    opt_enum, opt_filter, opt_int, opt_number, opt_string, page_slice,
    pagination_params, parse_date, plan_of_year, req_bool, req_date,
    req_enum, req_int, req_string, touch,
)
from services.determination import run_determination_sweep

bp = Blueprint("structure", __name__)

ENTITY_TYPES = {
    "CORPORATION", "S_CORPORATION", "PARTNERSHIP", "LLC",
    "SOLE_PROPRIETORSHIP", "NONPROFIT", "GOVERNMENTAL",
}
PLAN_TYPES = {"401K", "CAFETERIA_125", "DEPENDENT_CARE_FSA"}
COMP_DEFINITIONS = {"W2", "SEC415", "SEC3401"}
SAFE_HARBOR_DESIGNS = {"NONE", "BASIC_MATCH", "ENHANCED_MATCH", "QNEC_3PCT", "QACA"}
ENTRY_FREQUENCIES = {"IMMEDIATE", "MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"}
PLAN_YEAR_STATUSES = {
    "DRAFT", "CENSUS_COLLECTING", "CENSUS_LOCKED", "TESTING",
    "RESULTS_REVIEW", "CORRECTING", "FILED", "TERMINATED",
}
PLAN_YEAR_TERMINAL = {"FILED", "TERMINATED"}
EIN_RE = re.compile(r"^\d{9}$")
PLAN_NUMBER_RE = re.compile(r"^\d{3}$")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def employer_out(e):
    return {
        "id": e["id"], "legal_name": e["legal_name"], "ein": e["ein"],
        "entity_type": e["entity_type"],
        "controlled_group_id": e["controlled_group_id"],
        "status": e["status"], "created_at": e["created_at"],
        "updated_at": e["updated_at"], "version": e["version"],
    }


def plan_out(p):
    return {
        "id": p["id"], "employer_id": p["employer_id"],
        "plan_name": p["plan_name"], "plan_type": p["plan_type"],
        "plan_number": p["plan_number"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def plan_version_out(v, detail=None):
    out = {
        "id": v["id"], "plan_id": v["plan_id"],
        "effective_start": v["effective_start"],
        "effective_end": v["effective_end"],
        "comp_definition": v["comp_definition"],
        "safe_harbor_design": v["safe_harbor_design"],
        "sh_match_formula": v["sh_match_formula"],
        "entry_frequency": v["entry_frequency"],
        "is_amendment": v["is_amendment"],
        "status": v["status"], "created_at": v["created_at"],
        "updated_at": v["updated_at"], "version": v["version"],
    }
    if detail is not None:
        out["detail"] = detail
    return out


def plan_year_out(py):
    return {
        "id": py["id"], "plan_id": py["plan_id"],
        "year_label": py["year_label"], "year_start": py["year_start"],
        "year_end": py["year_end"],
        "census_lock_version": py["census_lock_version"],
        "status": py["status"],
        "prior_year_py_id": py["prior_year_py_id"],
        "adopted_version_id": py["adopted_version_id"],
        "created_at": py["created_at"], "updated_at": py["updated_at"],
        "version": py["version"],
    }


def regulatory_limit_out(lim):
    return {
        "id": lim["id"], "year_label": lim["year_label"],
        "hce_comp_threshold_cents": lim["hce_comp_threshold_cents"],
        "key_officer_comp_threshold_cents": lim["key_officer_comp_threshold_cents"],
        "sec402g_limit_cents": lim["sec402g_limit_cents"],
        "sec415_annual_additions_limit_cents": lim["sec415_annual_additions_limit_cents"],
        "dependent_care_limit_cents": lim["dependent_care_limit_cents"],
        "status": lim["status"], "created_at": lim["created_at"],
        "updated_at": lim["updated_at"], "version": lim["version"],
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/ndt/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles({ROLE_PLATFORM_ADMIN})
    body = get_body()
    to_iso = req_string(body, "to_iso8601")
    try:
        clock.set(to_iso)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be a valid ISO 8601 datetime")
    sh_svc.evaluate_notice_lapse()
    return success_object({"now_iso8601": clock.now_iso()})


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

@bp.route("/ndt/employers", methods=["POST"])
def create_employer():
    require_roles({ROLE_PLATFORM_ADMIN})
    body = get_body()
    legal_name = req_string(body, "legal_name")
    ein = req_string(body, "ein")
    entity_type = req_enum(body, "entity_type", ENTITY_TYPES)
    if not EIN_RE.match(ein):
        raise ApiError(ERR_INVALID_REQUEST, 400, "ein must be exactly 9 digits")
    controlled_group_id = opt_string(body, "controlled_group_id")
    if controlled_group_id is not None and controlled_group_id not in store.employers:
        raise ApiError(ERR_FK_INTEGRITY, 422,
                       "controlled_group_id does not reference an existing Employer")
    for existing in store.employers.values():
        if existing["ein"] == ein:
            raise ApiError(ERR_DUPLICATE, 409, "ein must be unique across Employers")
    employer = new_entity({
        "legal_name": legal_name, "ein": ein, "entity_type": entity_type,
        "controlled_group_id": controlled_group_id, "status": "ACTIVE",
    })
    store.employers[employer["id"]] = employer
    return success_object(employer_out(employer), status=201)


@bp.route("/ndt/employers/<eid>/archive", methods=["POST"])
def archive_employer(eid):
    require_roles({ROLE_PLATFORM_ADMIN})
    employer = get_employer(eid)
    if employer["status"] == "ARCHIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Employer is already ARCHIVED")
    for plan in store.plans.values():
        if plan["employer_id"] != eid or plan["status"] != "ACTIVE":
            continue
        for py in store.plan_years.values():
            if py["plan_id"] == plan["id"] and py["status"] not in PLAN_YEAR_TERMINAL:
                raise ApiError(ERR_INVALID_STATE, 409,
                               "Employer sponsors an ACTIVE plan with a non-terminal plan year")
    employer["status"] = "ARCHIVED"
    bump(employer)
    return success_object(employer_out(employer))


@bp.route("/ndt/employers/<eid>", methods=["GET"])
def fetch_employer(eid):
    require_roles(READ_ROLES)
    return success_object(employer_out(get_employer(eid)))


@bp.route("/ndt/employers", methods=["GET"])
def list_employers():
    require_roles(READ_ROLES)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    entity_type = opt_filter(request.args, "entity_type")
    cg_id = opt_filter(request.args, "controlled_group_id")
    items = list(store.employers.values())
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    if cg_id is not None:
        items = [e for e in items if e["controlled_group_id"] == cg_id]
    page, total = page_slice(items, limit, offset)
    return success_list([employer_out(e) for e in page], limit, offset, total)


@bp.route("/ndt/employers/<eid>/plans", methods=["GET"])
def list_plans_of_employer(eid):
    require_roles(READ_ROLES)
    get_employer(eid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    items = [p for p in store.plans.values() if p["employer_id"] == eid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([plan_out(p) for p in page], limit, offset, total)


@bp.route("/ndt/employers/<eid>/plans", methods=["POST"])
def create_plan(eid):
    require_roles({ROLE_PLATFORM_ADMIN, ROLE_PLAN_ADMINISTRATOR})
    employer = get_employer(eid)
    if employer["status"] != "ACTIVE":
        raise ApiError(ERR_EMPLOYER_ARCHIVED, 409,
                       "Cannot create a plan under an ARCHIVED employer")
    body = get_body()
    plan_name = req_string(body, "plan_name")
    plan_type = req_enum(body, "plan_type", PLAN_TYPES)
    plan_number = req_string(body, "plan_number")
    if not PLAN_NUMBER_RE.match(plan_number):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "plan_number must be three digits (001-999)")
    for existing in store.plans.values():
        if existing["employer_id"] == eid and existing["plan_number"] == plan_number:
            raise ApiError(ERR_DUPLICATE, 409,
                           "plan_number must be unique within the employer")
    plan = new_entity({
        "employer_id": eid, "plan_name": plan_name, "plan_type": plan_type,
        "plan_number": plan_number, "status": "ACTIVE",
    })
    store.plans[plan["id"]] = plan
    return success_object(plan_out(plan), status=201)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@bp.route("/ndt/plans/<pid>", methods=["GET"])
def fetch_plan(pid):
    require_roles(READ_ROLES)
    return success_object(plan_out(get_plan(pid)))


@bp.route("/ndt/plans/<pid>/plan-versions", methods=["GET"])
def list_plan_versions(pid):
    require_roles(READ_ROLES)
    get_plan(pid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    items = [v for v in store.plan_versions.values() if v["plan_id"] == pid]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([plan_version_out(v) for v in page], limit, offset, total)


@bp.route("/ndt/plans/<pid>/plan-versions", methods=["POST"])
def create_plan_version(pid):
    require_roles({ROLE_PLATFORM_ADMIN, ROLE_PLAN_ADMINISTRATOR})
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_TERMINATED, 409,
                       "Cannot create a plan version under a TERMINATED plan")
    body = get_body()
    effective_start = req_date(body, "effective_start")
    effective_end = opt_date(body, "effective_end")
    comp_definition = req_enum(body, "comp_definition", COMP_DEFINITIONS)
    safe_harbor_design = opt_enum(body, "safe_harbor_design", SAFE_HARBOR_DESIGNS, "NONE")
    sh_match_formula = opt_string(body, "sh_match_formula")
    entry_frequency = opt_enum(body, "entry_frequency", ENTRY_FREQUENCIES, "MONTHLY")
    is_amendment = opt_bool(body, "is_amendment", False)
    if safe_harbor_design in ("BASIC_MATCH", "ENHANCED_MATCH") and not sh_match_formula:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "sh_match_formula is required for match safe harbor designs")
    if effective_end is not None and not effective_start < effective_end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "effective_start must be strictly before effective_end")
    version = new_entity({
        "plan_id": pid,
        "effective_start": effective_start.isoformat(),
        "effective_end": effective_end.isoformat() if effective_end else None,
        "comp_definition": comp_definition,
        "safe_harbor_design": safe_harbor_design,
        "sh_match_formula": sh_match_formula,
        "entry_frequency": entry_frequency,
        "is_amendment": is_amendment,
        "status": "DRAFT",
    })
    store.plan_versions[version["id"]] = version
    return success_object(plan_version_out(version), status=201)


@bp.route("/ndt/plans/<pid>/plan-years", methods=["GET"])
def list_plan_years_of_plan(pid):
    require_roles(READ_ROLES)
    get_plan(pid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    items = [py for py in store.plan_years.values() if py["plan_id"] == pid]
    if status is not None:
        items = [py for py in items if py["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([plan_year_out(py) for py in page], limit, offset, total)


@bp.route("/ndt/plans/<pid>/plan-years", methods=["POST"])
def create_plan_year(pid):
    require_roles({ROLE_PLATFORM_ADMIN, ROLE_PLAN_ADMINISTRATOR})
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_TERMINATED, 409,
                       "Cannot create a plan year under a TERMINATED plan")
    body = get_body()
    year_label = req_int(body, "year_label")
    year_start = req_date(body, "year_start")
    year_end = req_date(body, "year_end")
    prior_year_py_id = opt_string(body, "prior_year_py_id")
    if prior_year_py_id is not None:
        prior = store.plan_years.get(prior_year_py_id)
        if prior is None or prior["plan_id"] != pid:
            raise ApiError(ERR_FK_INTEGRITY, 422,
                           "prior_year_py_id must reference a PlanYear of the same plan")
    if not year_start < year_end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "year_start must be strictly before year_end")
    py = new_entity({
        "plan_id": pid, "year_label": year_label,
        "year_start": year_start.isoformat(), "year_end": year_end.isoformat(),
        "census_lock_version": 0, "status": "DRAFT",
        "prior_year_py_id": prior_year_py_id, "adopted_version_id": None,
    })
    store.plan_years[py["id"]] = py
    return success_object(plan_year_out(py), status=201)


# ---------------------------------------------------------------------------
# PlanVersion
# ---------------------------------------------------------------------------

@bp.route("/ndt/plan-versions/<vid>", methods=["GET"])
def fetch_plan_version(vid):
    require_roles(READ_ROLES)
    return success_object(plan_version_out(get_plan_version(vid)))


@bp.route("/ndt/plan-versions/<vid>/adopt", methods=["POST"])
def adopt_plan_version(vid):
    require_roles({ROLE_PLATFORM_ADMIN, ROLE_PLAN_ADMINISTRATOR})
    version = get_plan_version(vid)
    if version["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT plan version can be adopted")
    start = date.fromisoformat(version["effective_start"])
    end = date.fromisoformat(version["effective_end"]) if version["effective_end"] else None
    if end is not None and not start < end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "effective_start must be strictly before effective_end")
    impact, _ = amendment_svc.adopt_version(version)
    detail = impact if version["is_amendment"] else None
    return success_object(plan_version_out(version, detail=detail))


# ---------------------------------------------------------------------------
# PlanYear
# ---------------------------------------------------------------------------

@bp.route("/ndt/plan-years", methods=["GET"])
def list_plan_years():
    require_roles(READ_ROLES)
    limit, offset = pagination_params()
    plan_id = opt_filter(request.args, "plan_id")
    status = opt_filter(request.args, "status")
    prior_year_py_id = opt_filter(request.args, "prior_year_py_id")
    adopted_version_id = opt_filter(request.args, "adopted_version_id")
    items = list(store.plan_years.values())
    if plan_id is not None:
        items = [py for py in items if py["plan_id"] == plan_id]
    if status is not None:
        items = [py for py in items if py["status"] == status]
    if prior_year_py_id is not None:
        items = [py for py in items if py["prior_year_py_id"] == prior_year_py_id]
    if adopted_version_id is not None:
        items = [py for py in items if py["adopted_version_id"] == adopted_version_id]
    page, total = page_slice(items, limit, offset)
    return success_list([plan_year_out(py) for py in page], limit, offset, total)


@bp.route("/ndt/plan-years/<pyid>", methods=["GET"])
def fetch_plan_year(pyid):
    require_roles(READ_ROLES)
    return success_object(plan_year_out(get_plan_year(pyid)))


@bp.route("/ndt/plan-years/<pyid>/open-census", methods=["POST"])
def open_census(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    if py["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "open-census requires the plan year to be DRAFT")
    if py["prior_year_py_id"] is not None:
        prior = store.plan_years.get(py["prior_year_py_id"])
        if prior is None or prior["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Prior plan year must be FILED before opening the census")
    py["status"] = "CENSUS_COLLECTING"
    bump(py)
    return success_object(plan_year_out(py))


@bp.route("/ndt/plan-years/<pyid>/lock-census", methods=["POST"])
def lock_census(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    if py["status"] != "CENSUS_COLLECTING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "lock-census requires the plan year to be CENSUS_COLLECTING")
    body = get_body() if request.data else {}
    expected = body.get("expected_plan_year_version") if isinstance(body, dict) else None
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "expected_plan_year_version must be an integer")
        if expected != py["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "Plan year version has advanced since the caller's view")
    plan = plan_of_year(py)
    adopted = adopted_version_covering(plan["id"], date.fromisoformat(py["year_start"]))
    if adopted is None:
        raise ApiError(ERR_CENSUS_INCOMPLETE, 422,
                       "No ADOPTED PlanVersion covers the plan year's year_start")
    limit = active_limit_for_year(py["year_label"])
    if limit is None:
        raise ApiError(ERR_CENSUS_INCOMPLETE, 422,
                       "No ACTIVE RegulatoryLimit exists for the plan year's year_label")
    comp_def = adopted["comp_definition"]
    employees = employees_of_year(py["id"])
    if not employees:
        raise ApiError(ERR_CENSUS_INCOMPLETE, 422,
                       "The census has no employees to lock")
    for e in employees:
        has_current = any(
            r["census_employee_id"] == e["id"]
            and r["comp_source"] == comp_def
            and r["period"] == "CURRENT_YEAR"
            for r in store.compensation_records.values())
        if not has_current:
            raise ApiError(ERR_CENSUS_INCOMPLETE, 422,
                           "Every census employee needs a CURRENT_YEAR compensation "
                           "record under the plan's compensation definition")
    py["adopted_version_id"] = adopted["id"]
    py["census_lock_version"] = int(py["census_lock_version"]) + 1
    py["status"] = "CENSUS_LOCKED"
    run_determination_sweep(py, adopted)
    for election in list(store.safe_harbor_elections.values()):
        if election["plan_year_id"] == py["id"]:
            sh_svc.evaluate_election_effectiveness(election)
    bump(py)
    return success_object(plan_year_out(py))


UNLOCK_SOURCE_STATES = {"CENSUS_LOCKED", "TESTING", "RESULTS_REVIEW", "CORRECTING"}


@bp.route("/ndt/plan-years/<pyid>/unlock-census", methods=["POST"])
def unlock_census(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    # Unlock re-opens a locked census. The §3.5 pending-work guard (QUEUED/
    # RUNNING runs, PROPOSED/APPROVED corrections) and the supersede cascade on
    # PASSED/FAILED runs are reachable only from post-lock states: queueing a
    # run moves the year CENSUS_LOCKED -> TESTING and corrections live in
    # CORRECTING, so the state gate admits every post-lock, non-terminal state.
    if py["status"] not in UNLOCK_SOURCE_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "unlock-census requires the plan year to be past census "
                       "lock and not terminal")
    for run in store.test_runs.values():
        if run["plan_year_id"] == py["id"] and run["status"] in ("QUEUED", "RUNNING"):
            raise ApiError(ERR_PENDING_WORK, 409,
                           "A TestRun is still QUEUED or RUNNING for this plan year")
    for correction in store.corrections.values():
        if correction["plan_year_id"] == py["id"] and correction["status"] in ("PROPOSED", "APPROVED"):
            raise ApiError(ERR_PENDING_WORK, 409,
                           "A Correction is still PROPOSED or APPROVED for this plan year")
    for run in store.test_runs.values():
        if run["plan_year_id"] == py["id"] and run["status"] in ("PASSED", "FAILED"):
            run["status"] = "SUPERSEDED"
            bump(run)
    py["status"] = "CENSUS_COLLECTING"
    bump(py)
    return success_object(plan_year_out(py))


@bp.route("/ndt/plan-years/<pyid>/terminate", methods=["POST"])
def terminate_plan_year(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    if py["status"] not in ("DRAFT", "CENSUS_COLLECTING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "terminate requires the plan year to be DRAFT or CENSUS_COLLECTING")
    py["status"] = "TERMINATED"
    plan = plan_of_year(py)
    if plan is not None and plan["status"] != "TERMINATED":
        plan["status"] = "TERMINATED"
        bump(plan)
    bump(py)
    return success_object(plan_year_out(py))


@bp.route("/ndt/plan-years/<pyid>/file", methods=["POST"])
def file_plan_year(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    if py["status"] != "CORRECTING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "file requires the plan year to be CORRECTING")
    for correction in store.corrections.values():
        if correction["plan_year_id"] == py["id"] \
                and correction["status"] not in ("EXECUTED", "VOIDED"):
            raise ApiError(ERR_UNRESOLVED_FAILURES, 409,
                           "Every correction must be EXECUTED or VOIDED before filing")
    executed = [c for c in store.corrections.values()
                if c["plan_year_id"] == py["id"] and c["status"] == "EXECUTED"]
    last_executed_at = max((c["created_at"] for c in executed), default=None)
    final_runs = [r for r in store.test_runs.values()
                  if r["plan_year_id"] == py["id"]
                  and r["run_mode"] == "FINAL"
                  and r["status"] in ("PASSED", "FAILED")]
    if last_executed_at is not None:
        final_runs = [r for r in final_runs if r["created_at"] > last_executed_at]
    for run in final_runs:
        if run["overall_result"] != "PASS":
            raise ApiError(ERR_UNRESOLVED_FAILURES, 409,
                           "The latest FINAL test runs must pass before filing")
    correction_svc.assess_excise_at_filing(py)
    py["status"] = "FILED"
    bump(py)
    return success_object(plan_year_out(py))


# ---------------------------------------------------------------------------
# Regulatory limits
# ---------------------------------------------------------------------------

@bp.route("/ndt/regulatory-limits", methods=["POST"])
def create_regulatory_limit():
    require_roles({ROLE_PLATFORM_ADMIN})
    body = get_body()
    year_label = req_int(body, "year_label")
    hce = req_int(body, "hce_comp_threshold_cents")
    officer = req_int(body, "key_officer_comp_threshold_cents")
    sec402g = req_int(body, "sec402g_limit_cents")
    sec415 = req_int(body, "sec415_annual_additions_limit_cents")
    dep_care = req_int(body, "dependent_care_limit_cents")
    for name, value in (("hce_comp_threshold_cents", hce),
                        ("key_officer_comp_threshold_cents", officer),
                        ("sec402g_limit_cents", sec402g),
                        ("sec415_annual_additions_limit_cents", sec415),
                        ("dependent_care_limit_cents", dep_care)):
        if value < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be >= 0" % name)
    for existing in store.regulatory_limits.values():
        if existing["year_label"] == year_label and existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            bump(existing)
    limit = new_entity({
        "year_label": year_label,
        "hce_comp_threshold_cents": hce,
        "key_officer_comp_threshold_cents": officer,
        "sec402g_limit_cents": sec402g,
        "sec415_annual_additions_limit_cents": sec415,
        "dependent_care_limit_cents": dep_care,
        "status": "ACTIVE",
    })
    store.regulatory_limits[limit["id"]] = limit
    return success_object(regulatory_limit_out(limit), status=201)


@bp.route("/ndt/regulatory-limits", methods=["GET"])
def list_regulatory_limits():
    require_roles(READ_ROLES)
    limit_param, offset = pagination_params()
    year_label_raw = opt_filter(request.args, "year_label")
    status = opt_filter(request.args, "status")
    items = list(store.regulatory_limits.values())
    if year_label_raw is not None:
        try:
            year_label = int(year_label_raw)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "year_label must be an integer")
        items = [l for l in items if l["year_label"] == year_label]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = page_slice(items, limit_param, offset)
    return success_list([regulatory_limit_out(l) for l in page],
                        limit_param, offset, total)
