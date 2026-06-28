"""MitigationJob endpoints: design, quote, schedule, complete-install, cancel
(PRD §3.4, §3.5)."""

from flask import Blueprint, request

from db import store, format_iso8601_millis
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services import calc
from services.domain import (
    _common_create_fields,
    public,
    touch,
    now_clock,
    recompute_property_derived,
    append_payment,
    recompute_job_payments,
)
from services.listing import paginate

bp = Blueprint("mitigation_jobs", __name__)

SYSTEM_DESIGNS = {"SUB_SLAB_DEPRESSURIZATION", "SUB_MEMBRANE_DEPRESSURIZATION"}
REFUND_METHODS = {"STRAIGHT_LINE", "STEP_TIER"}
GET_ROLES = {
    "PlatformAdmin",
    "MitigationDesigner",
    "CrewLead",
    "ComplianceOfficer",
    "ClientContact",
}


@bp.route("/mitigation-jobs", methods=["POST"])
def create_job():
    _, role = get_user_context()
    require_role(role, {"MitigationDesigner"})
    body = get_json_body()

    property_id = validate.require_string(body, "property_id")
    triggering_test_id = validate.require_string(body, "triggering_test_id")
    system_design = validate.optional_enum(
        body, "system_design", SYSTEM_DESIGNS, "SUB_SLAB_DEPRESSURIZATION"
    )
    num_suction_points = validate.optional_int(body, "num_suction_points", 1, minimum=1)
    has_sump_pump = validate.optional_bool(body, "has_sump_pump", False)
    is_rush = validate.optional_bool(body, "is_rush", False)
    warranty_term_days = validate.optional_int(body, "warranty_term_days", 1825, minimum=1)
    warranty_guarantee_ceiling = validate.optional_number(
        body, "warranty_guarantee_ceiling_pci_l", 2.0, strictly_positive=True
    )
    warranty_refund_method = validate.optional_enum(
        body, "warranty_refund_method", REFUND_METHODS, "STRAIGHT_LINE"
    )
    retest_interval_days = validate.optional_int(body, "retest_interval_days", 730, minimum=1)

    # body FK existence (priority 4).
    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError(errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "property_id not found.")
    trig = store.radon_tests.get(triggering_test_id)
    if trig is None:
        raise ApiError(
            errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "triggering_test_id not found."
        )

    entity = _common_create_fields()
    entity.update(
        {
            "property_id": property_id,
            "triggering_test_id": triggering_test_id,
            "crew_id": None,
            "system_design": system_design,
            "num_suction_points": num_suction_points,
            "has_sump_pump": has_sump_pump,
            "is_rush": is_rush,
            "warranty_term_days": warranty_term_days,
            "warranty_guarantee_ceiling_pci_l": warranty_guarantee_ceiling,
            "warranty_refund_method": warranty_refund_method,
            "retest_interval_days": retest_interval_days,
            "quote_subtotal_cents": None,
            "rush_surcharge_cents": 0,
            "quote_total_cents": None,
            "deposit_required_cents": None,
            "deposit_paid_cents": 0,
            "balance_paid_cents": 0,
            "permit_id": None,
            "install_start_utc": None,
            "install_end_utc": None,
            "_install_start_dt": None,
            "_install_end_dt": None,
            "retest_passed": False,
            "status": "DESIGN",
        }
    )
    store.mitigation_jobs[entity["id"]] = entity
    return object_response(public(entity), 201)


@bp.route("/mitigation-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    job = store.mitigation_jobs.get(job_id)
    if job is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Mitigation job not found.")
    return object_response(public(job), 200)


@bp.route("/mitigation-jobs", methods=["GET"])
def list_jobs():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "property_id": request.args.get("property_id"),
        "triggering_test_id": request.args.get("triggering_test_id"),
        "crew_id": request.args.get("crew_id"),
        "status": request.args.get("status"),
    }
    items, total = paginate(store.mitigation_jobs, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)


@bp.route("/mitigation-jobs/<job_id>/quote", methods=["POST"])
def quote_job(job_id):
    _, role = get_user_context()
    require_role(role, {"MitigationDesigner"})
    job = store.mitigation_jobs.get(job_id)
    if job is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Mitigation job not found.")

    # state (priority 5).
    if job["status"] != "DESIGN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Job is not in DESIGN state.")

    # business: posture MITIGATION_REQUIRED and triggering test ACTION_RECOMMENDED (priority 11).
    prop = store.properties.get(job["property_id"])
    trig = store.radon_tests.get(job["triggering_test_id"])
    if (
        prop is None
        or prop["posture"] != "MITIGATION_REQUIRED"
        or trig is None
        or trig.get("action_outcome") != "ACTION_RECOMMENDED"
    ):
        raise ApiError(
            errors.ERR_NO_ACTIONABLE_RESULT,
            409,
            "Quoting requires MITIGATION_REQUIRED posture and an ACTION_RECOMMENDED trigger.",
        )

    subtotal, rush, total, deposit = calc.mitigation_quote(
        prop["foundation_type"],
        prop["floor_area_sqft"],
        job["num_suction_points"],
        job["has_sump_pump"],
        job["is_rush"],
    )
    job["quote_subtotal_cents"] = subtotal
    job["rush_surcharge_cents"] = rush
    job["quote_total_cents"] = total
    job["deposit_required_cents"] = deposit
    job["status"] = "QUOTED"
    touch(job)
    return object_response(public(job), 200)


@bp.route("/mitigation-jobs/<job_id>/schedule", methods=["POST"])
def schedule_job(job_id):
    _, role = get_user_context()
    require_role(role, {"MitigationDesigner"})
    job = store.mitigation_jobs.get(job_id)
    if job is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Mitigation job not found.")
    body = get_json_body()

    crew_id = validate.require_string(body, "crew_id")
    install_start = validate.require_datetime(body, "install_start_utc")
    install_end = validate.require_datetime(body, "install_end_utc")
    expected_version = validate.require_int(body, "expected_property_version")

    # body FK existence (priority 4): crew.
    crew = store.crews.get(crew_id)
    if crew is None:
        raise ApiError(errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "crew_id not found.")

    # state (priority 5): schedule allowed from QUOTED or REWORK.
    if job["status"] not in {"QUOTED", "REWORK"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Job cannot be scheduled from its state.")

    prop = store.properties.get(job["property_id"])

    # OCC on the parent property (priority 6).
    if expected_version != prop["version"]:
        raise ApiError(
            errors.ERR_STALE_PROPERTY_VERSION,
            412,
            "expected_property_version does not match the live property version.",
        )

    is_rework = job["status"] == "REWORK"

    # deposit gate only on the initial QUOTED->SCHEDULED (rework is free) (priority 16).
    if not is_rework:
        if job["deposit_paid_cents"] < job["deposit_required_cents"]:
            raise ApiError(
                errors.ERR_DEPOSIT_NOT_SATISFIED, 409, "Deposit has not been satisfied."
            )

    # crew ACTIVE (priority 8 mapped to ERR_CREW_SUSPENDED).
    if crew["status"] != "ACTIVE":
        raise ApiError(errors.ERR_CREW_SUSPENDED, 409, "Assigned crew is SUSPENDED.")

    # window well-formed (priority 12 -> ERR_INVALID_WINDOW).
    if not (install_start < install_end):
        raise ApiError(errors.ERR_INVALID_WINDOW, 409, "install_start_utc must be before install_end_utc.")

    # rush deadline (priority 12 -> ERR_RUSH_DEADLINE_MISSED). Only on initial schedule
    # when the job is_rush; rework path per PRD §3.5 checks crew/window only.
    if (not is_rework) and job["is_rush"]:
        closing = prop.get("_closing_dt")
        if closing is None or install_end > closing:
            raise ApiError(
                errors.ERR_RUSH_DEADLINE_MISSED,
                409,
                "Rush install window runs past the closing deadline.",
            )

    # crew window conflict / capacity (priority 13).
    _check_crew_window(crew, job_id, install_start, install_end)

    # commit.
    job["crew_id"] = crew_id
    job["install_start_utc"] = format_iso8601_millis(install_start)
    job["install_end_utc"] = format_iso8601_millis(install_end)
    job["_install_start_dt"] = install_start
    job["_install_end_dt"] = install_end
    job["status"] = "SCHEDULED"
    touch(job)

    # Property posture -> MITIGATING; Property.version increments by one (PRD §3.5).
    recompute_property_derived(prop)

    return object_response(public(job), 200)


def _check_crew_window(crew, job_id, install_start, install_end):
    """Crew window must not overlap an existing SCHEDULED job's window for that
    crew (half-open [start,end), adjacency allowed), and must not exceed
    max_jobs_per_day on the install calendar day (PRD §3.5)."""
    same_crew_scheduled = [
        j
        for j in store.mitigation_jobs.values()
        if j["id"] != job_id
        and j["crew_id"] == crew["id"]
        and j["status"] == "SCHEDULED"
        and j.get("_install_start_dt") is not None
    ]

    # Overlap on half-open intervals: a < existing_end and existing_start < b.
    for j in same_crew_scheduled:
        es = j["_install_start_dt"]
        ee = j["_install_end_dt"]
        if install_start < ee and es < install_end:
            raise ApiError(
                errors.ERR_CREW_WINDOW_CONFLICT,
                409,
                "Crew install window overlaps an existing scheduled window.",
            )

    # max_jobs_per_day on the install day (UTC calendar date of the window start).
    install_day = install_start.date()
    count_same_day = sum(
        1 for j in same_crew_scheduled if j["_install_start_dt"].date() == install_day
    )
    if count_same_day + 1 > crew["max_jobs_per_day"]:
        raise ApiError(
            errors.ERR_CREW_WINDOW_CONFLICT,
            409,
            "Crew exceeds max_jobs_per_day for the install day.",
        )


@bp.route("/mitigation-jobs/<job_id>/complete-install", methods=["POST"])
def complete_install(job_id):
    _, role = get_user_context()
    require_role(role, {"CrewLead"})
    job = store.mitigation_jobs.get(job_id)
    if job is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Mitigation job not found.")

    # state (priority 5).
    if job["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Job is not in SCHEDULED state.")

    # permit gate (priority 9).
    permit_id = job.get("permit_id")
    permit = store.permits.get(permit_id) if permit_id else None
    if permit is None or permit["status"] != "ISSUED":
        raise ApiError(errors.ERR_PERMIT_REQUIRED, 409, "An ISSUED permit is required.")

    # install window due: clock >= install_start_utc (ERR_INSTALL_NOT_DUE).
    if now_clock() < job["_install_start_dt"]:
        raise ApiError(errors.ERR_INSTALL_NOT_DUE, 409, "Install window has not started.")

    job["status"] = "INSTALLED"
    touch(job)
    return object_response(public(job), 200)


@bp.route("/mitigation-jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    _, role = get_user_context()
    require_role(role, {"MitigationDesigner", "PlatformAdmin"})
    job = store.mitigation_jobs.get(job_id)
    if job is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Mitigation job not found.")

    # state (priority 5): only DESIGN or QUOTED.
    if job["status"] not in {"DESIGN", "QUOTED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only DESIGN or QUOTED jobs can be cancelled.")

    job["status"] = "CANCELLED"
    # If a deposit was collected, append a compensating REFUND and reset to 0.
    if job["deposit_paid_cents"] > 0:
        refund = -job["deposit_paid_cents"]
        append_payment(job, "REFUND", refund)
        job["deposit_paid_cents"] = 0
    touch(job)

    prop = store.properties.get(job["property_id"])
    recompute_property_derived(prop)
    return object_response(public(job), 200)
