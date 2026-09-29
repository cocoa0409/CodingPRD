"""The violent incident log and prevention drills (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as C
import sync
from db import new_log_row, new_row, store
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes.common import filtered, lookup, paged, single
from serialize import dump_log_entry
from validation import (bool_field, body, dt_field, enum_field, id_field,
                        int_field, qs_bool, qs_enum, qs_str, str_field)

bp = Blueprint("logbook", __name__)

LOG_ROLES = ("ComplianceAuditor", "SafetyOfficer", "SiteManager", "ThreatTeamLead", "ProgramAdmin")
DRILL_READ_ROLES = ("SafetyOfficer", "SiteManager", "ComplianceAuditor", "ProgramAdmin")


# ------------------------------------------------------ violent incident log


@bp.get("/violent-incident-log/<log_entry_id>")
def get_log_entry(log_entry_id):
    authenticate(LOG_ROLES)
    entry = lookup(store.log_entries, log_entry_id, "ERR_LOG_ENTRY_NOT_FOUND")
    return object_response(dump_log_entry(entry))


@bp.get("/violent-incident-log")
def list_log_entries():
    authenticate(LOG_ROLES)
    filters = {
        "worksite_id": qs_str("worksite_id"),
        "incident_report_id": qs_str("incident_report_id"),
        "case_id": qs_str("case_id"),
        "supersedes_entry_id": qs_str("supersedes_entry_id"),
        "retention_status": qs_enum("retention_status", C.RETENTION_STATUSES),
    }
    rows = filtered(list(store.log_entries.values()), filters)
    superseded = qs_bool("superseded_flag")
    if superseded is not None:
        rows = [r for r in rows if calc.is_superseded_entry(r) == superseded]
    return paged(rows, dump_log_entry)


@bp.post("/violent-incident-log/<log_entry_id>/amendments")
def amend_log_entry(log_entry_id):
    authenticate(("SafetyOfficer",))
    data = body()
    amendment_reason = str_field(data, "amendment_reason", True, 1)
    has_class = "perpetrator_class" in data and data["perpetrator_class"] is not None
    perpetrator_class = enum_field(data, "perpetrator_class", C.PERPETRATOR_CLASSES, False)
    has_notified = "law_enforcement_notified" in data and data["law_enforcement_notified"] is not None
    law_enforcement_notified = bool_field(data, "law_enforcement_notified", False)
    consequence_narrative = str_field(data, "consequence_narrative", False)
    controls_summary = str_field(data, "controls_summary", False)

    target = lookup(store.log_entries, log_entry_id, "ERR_LOG_ENTRY_NOT_FOUND")

    # Step 10 -- corrections always chain from the newest live entry.
    if calc.is_superseded_entry(target) or target["retention_status"] != "ACTIVE":
        raise ApiError("ERR_LOG_ENTRY_IMMUTABLE",
                       "Only a live, in-retention entry may be amended.")

    fields = {
        "worksite_id": target["worksite_id"],
        "incident_report_id": target["incident_report_id"],
        "case_id": target["case_id"],
        "supersedes_entry_id": target["id"],
        "incident_at": target["incident_at"],
        "work_area_name": target["work_area_name"],
        "incident_type": target["incident_type"],
        "perpetrator_class": perpetrator_class if has_class else target["perpetrator_class"],
        "injury_level": target["injury_level"],
        "weapon_involved": target["weapon_involved"],
        "law_enforcement_notified": (
            law_enforcement_notified if has_notified else target["law_enforcement_notified"]
        ),
        "consequence_narrative": (
            consequence_narrative if consequence_narrative is not None
            else target["consequence_narrative"]
        ),
        "controls_summary": (
            controls_summary if controls_summary is not None else target["controls_summary"]
        ),
        "required_element_count_present": 0,
        "amendment_reason": amendment_reason,
        "retention_expiry_date": target["retention_expiry_date"],
        "retention_status": "ACTIVE",
    }
    fields["required_element_count_present"] = sync.count_required_elements(fields)
    row = new_log_row(fields)
    store.log_entries[row["id"]] = row

    # The register's completeness moved, so the plan is rescored.
    sync.sync_plans_of_worksite(target["worksite_id"])

    return object_response(dump_log_entry(row), 201)


# ------------------------------------------------------------------- drills


@bp.post("/drills")
def create_drill():
    authenticate(("SafetyOfficer",))
    data = body()
    plan_id = id_field(data, "plan_id", True)
    scenario_type = enum_field(data, "scenario_type", C.SCENARIO_TYPES, True)
    scheduled_at, _ = dt_field(data, "scheduled_at", True)

    lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND")

    row = new_row({
        "plan_id": plan_id,
        "scenario_type": scenario_type,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "executed_at": None,
        "participant_count": None,
        "findings_count": None,
        "participation_pct": None,
        "credited": False,
    })
    store.drills[row["id"]] = row
    return single(row, 201)


@bp.get("/drills/<drill_id>")
def get_drill(drill_id):
    authenticate(DRILL_READ_ROLES)
    return single(lookup(store.drills, drill_id, "ERR_DRILL_NOT_FOUND"))


@bp.get("/drills")
def list_drills():
    authenticate(DRILL_READ_ROLES)
    filters = {
        "plan_id": qs_str("plan_id"),
        "scenario_type": qs_enum("scenario_type", C.SCENARIO_TYPES),
        "status": qs_enum("status", C.DRILL_STATUSES),
        "credited": qs_bool("credited"),
    }
    return paged(filtered(list(store.drills.values()), filters))


@bp.post("/drills/<drill_id>/execute")
def execute_drill(drill_id):
    authenticate(("SafetyOfficer",))
    data = body()
    participant_count = int_field(data, "participant_count", True, 0)
    findings_count = int_field(data, "findings_count", True, 0)

    drill = lookup(store.drills, drill_id, "ERR_DRILL_NOT_FOUND")
    plan = store.prevention_plans.get(drill["plan_id"])

    # Step 9 -- state, including the plan that owns the drill.
    if drill["status"] != "SCHEDULED":
        raise ApiError("ERR_DRILL_INVALID_STATE", "Only a SCHEDULED drill may be executed.")
    if plan is None or plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_DRILL_INVALID_STATE", "The drill's plan has been SUPERSEDED.")

    worksite = store.worksites.get(plan["worksite_id"])
    headcount = worksite["employee_count"] if worksite is not None else 0

    # Step 28 -- participation bounds protect the participation denominator.
    if participant_count > headcount or findings_count > 50:
        raise ApiError("ERR_PARTICIPANT_COUNT_EXCEEDS_HEADCOUNT",
                       "Participation must stay within the declared headcount.")

    if headcount > 0:
        pct = calc.r2(Decimal(participant_count) / Decimal(headcount) * Decimal(100))
    else:
        pct = Decimal("0.00")

    sync.assign(drill, {
        "status": "EXECUTED",
        "executed_at": store.clock_raw,
        "participant_count": participant_count,
        "findings_count": findings_count,
        "participation_pct": calc.num(pct),
        "credited": bool(pct >= C.DRILL_CREDIT_THRESHOLD),
    })

    sync.sync_plan(plan)
    return single(drill)
