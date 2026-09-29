"""Covenant monitoring, attestations and recapture events (PRD 3.8)."""

from flask import Blueprint

import calc
import services
from auth import own_project, require
from clock import clock
from db import base_record, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch
from validate import as_date, bad, body, req_date, req_enum, req_str

bp = Blueprint("compliance", __name__)

COVENANT_TYPES = (
    "USE_RESTRICTION",
    "OWNERSHIP_HOLD",
    "MAINTENANCE_STANDARD",
    "INSURANCE_COVERAGE",
    "REPORTING",
)
FREQUENCIES = ("ANNUAL", "SEMIANNUAL")
OUTCOMES = ("SATISFIED", "EXCEPTION")

CLIENT_EVENT_TYPES = (
    "OWNERSHIP_TRANSFER",
    "CESSATION_OF_USE",
    "LEASE_TO_DISQUALIFIED",
    "COVENANT_BREACH",
)

COVENANT_READ_ROLES = ("PlatformAdmin", "Developer", "ComplianceMonitor", "InvestorAdmin")
EVENT_READ_ROLES = ("PlatformAdmin", "Developer", "ComplianceMonitor", "InvestorAdmin")


# --------------------------------------------------------------------------
# covenants
# --------------------------------------------------------------------------


@bp.post("/compliance-covenants")
def create_covenant():
    uid, role = require("ComplianceMonitor", "Developer")
    data = body()
    project_id = req_str(data, "project_id")
    covenant_type = req_enum(data, "covenant_type", COVENANT_TYPES)
    frequency = req_enum(data, "monitoring_frequency", FREQUENCIES)
    window_start = req_date(data, "window_start_date")
    window_end = req_date(data, "window_end_date")

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    if role == "Developer":
        own_project(project, uid)

    if project["placed_in_service_date"] is None:
        raise ApiError("ERR_PROJECT_NOT_PLACED_IN_SERVICE")

    # Band 11: covenant-window coherence reports ERR_INVALID_REQUEST.
    if window_end <= window_start:
        raise bad("Field 'window_end_date' must fall strictly after 'window_start_date'.")

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "covenant_type": covenant_type,
            "monitoring_frequency": frequency,
            "window_start_date": window_start.isoformat(),
            "window_end_date": window_end.isoformat(),
            "status": "PENDING_ATTESTATION",
            "attestation_count": 0,
            "exception_count": 0,
            "last_attested_period_end": None,
            "cure_deadline_date": None,
        }
    )
    store.compliance_covenants[record["id"]] = record
    return created_response(public(record))


def _close_monitoring_period(project, period_end):
    """IN_SERVICE_MONITORING -> COMPLIANT_CLOSED once the five years have run."""
    if project["compliance_status"] != "IN_SERVICE_MONITORING":
        return False
    if period_end < services.monitoring_end_date(project):
        return False
    if project["recapture_balance_cents"] != 0:
        return False
    covenants = services.project_covenants(project["id"])
    if not covenants or any(c["status"] != "COMPLIANT" for c in covenants):
        return False
    project["compliance_status"] = "COMPLIANT_CLOSED"
    return True


@bp.post("/compliance-covenants/<covenant_id>/attest")
def attest_covenant(covenant_id):
    uid, role = require("Developer", "ComplianceMonitor")
    data = body()
    period_end = req_date(data, "period_end_date")
    outcome = req_enum(data, "outcome", OUTCOMES)

    covenant = fetch(store.compliance_covenants, covenant_id, "ERR_COMPLIANCE_COVENANT_NOT_FOUND")
    project = store.projects[covenant["project_id"]]
    if role == "Developer":
        own_project(project, uid)

    # --- band 8: project milestone, then the declared covenant transition ---
    if project["placed_in_service_date"] is None:
        raise ApiError("ERR_PROJECT_NOT_PLACED_IN_SERVICE")

    status = covenant["status"]
    if outcome == "SATISFIED":
        if status not in ("PENDING_ATTESTATION", "CURED", "BREACHED"):
            raise ApiError(
                "ERR_COVENANT_INVALID_STATE",
                "A satisfied attestation is not declared from %s." % status,
            )
        if status == "BREACHED":
            deadline = as_date(covenant["cure_deadline_date"])
            if deadline is not None and period_end > deadline:
                raise ApiError(
                    "ERR_COVENANT_INVALID_STATE",
                    "The cure window for this covenant has closed.",
                )
    else:
        if status not in ("PENDING_ATTESTATION", "COMPLIANT", "CURED"):
            raise ApiError(
                "ERR_COVENANT_INVALID_STATE",
                "An exception attestation is not declared from %s." % status,
            )

    # --- band 11: period coherence -----------------------------------------
    if period_end > clock.today():
        raise bad("Field 'period_end_date' may not be later than the current logical date.")
    previous = as_date(covenant["last_attested_period_end"])
    if previous is not None and period_end <= previous:
        raise bad(
            "Field 'period_end_date' must fall strictly after the last attested period end."
        )

    covenant["attestation_count"] += 1
    covenant["last_attested_period_end"] = period_end.isoformat()

    project_changed = False
    if outcome == "EXCEPTION":
        covenant["exception_count"] += 1
        covenant["status"] = "BREACHED"
        covenant["cure_deadline_date"] = calc.add_days(
            as_date(covenant["window_end_date"]), calc.CURE_WINDOW_DAYS
        ).isoformat()
        touch(covenant)
        # Cascade hops 1-3: posture, then every admitted interest, then the max.
        if services.enter_cure_pending(project):
            project_changed = True
        elif services.rescore_in_service(project):
            project_changed = True
    elif status == "BREACHED":
        covenant["status"] = "CURED"
        touch(covenant)
        if services.rescore_in_service(project):
            project_changed = True
        if services.leave_cure_pending(project):
            project_changed = True
    else:
        covenant["status"] = "COMPLIANT"
        touch(covenant)
        if _close_monitoring_period(project, period_end):
            project_changed = True

    if project_changed:
        touch(project)
    return object_response(public(covenant))


@bp.get("/compliance-covenants/<covenant_id>")
def read_covenant(covenant_id):
    require(*COVENANT_READ_ROLES)
    record = fetch(store.compliance_covenants, covenant_id, "ERR_COMPLIANCE_COVENANT_NOT_FOUND")
    return object_response(public(record))


# --------------------------------------------------------------------------
# recapture events
# --------------------------------------------------------------------------


@bp.post("/recapture-events")
def create_recapture_event():
    require("ComplianceMonitor")
    data = body()
    project_id = req_str(data, "project_id")
    event_type = req_enum(data, "event_type", CLIENT_EVENT_TYPES)
    event_date = req_date(data, "event_date")

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    if project["placed_in_service_date"] is None:
        raise ApiError("ERR_PROJECT_NOT_PLACED_IN_SERVICE")

    # --- band 11: the event must land inside the five-year period ----------
    placed = as_date(project["placed_in_service_date"])
    if event_date < placed:
        raise ApiError("ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD")
    elapsed_years = calc.days_between(placed, event_date) // calc.DAYS_PER_YEAR
    if elapsed_years >= calc.COMPLIANCE_PERIOD_YEARS:
        raise ApiError("ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD")
    if project["compliance_status"] == "COMPLIANT_CLOSED":
        raise ApiError("ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD")

    event = services.assess_recapture(project, event_type, event_date, "REPORTED")

    if event_type == "OWNERSHIP_TRANSFER":
        if project["compliance_status"] in ("IN_SERVICE_MONITORING", "CURE_PENDING"):
            project["compliance_status"] = "RECAPTURED"
        services.disqualify_master_lessees(project)
    else:
        if event_type == "LEASE_TO_DISQUALIFIED":
            services.disqualify_master_lessees(project)
        if event["recapture_amount_cents"] > 0:
            if not services.enter_cure_pending(project):
                services.rescore_in_service(project)
        else:
            services.refresh_max_risk(project)

    touch(project)
    return created_response(public(event))


@bp.get("/recapture-events/<event_id>")
def read_recapture_event(event_id):
    require(*EVENT_READ_ROLES)
    record = fetch(store.recapture_events, event_id, "ERR_RECAPTURE_EVENT_NOT_FOUND")
    return object_response(public(record))
