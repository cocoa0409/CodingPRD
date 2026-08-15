"""Incident case endpoints (PRD §3.2 intake/classification, §3.3 day counts,
§3.6 severe-injury reports, §3.9 finalization)."""
from datetime import timedelta

from flask import Blueprint

from db import (STORE, now_dt, now_iso, fmt_iso, parse_datetime, parse_date,
                new_id)
from errors import (raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_DUPLICATE,
                    ERR_ESTABLISHMENT_EXEMPT,
                    ERR_RECORDABILITY_WINDOW_PASSED, ERR_SUMMARY_LOCKED,
                    ERR_SEVERE_REPORT_REQUIRED, ERR_INVESTIGATION_OPEN,
                    ERR_DAY_COUNT_OPEN, ERR_CORRECTIVE_ACTION_OPEN,
                    ERR_DAY_INTERVAL_INVALID, ERR_CROSS_COMPANY_REFERENCE)
from middleware import get_auth, require_roles, ALL_ROLES, RATES_READ_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, req_enum, opt_enum, opt_bool,
                           req_dt, req_date, req_version, base_fields, bump,
                           serialize, serialize_case, lookup, paginated,
                           query_str, rollup_case, day_count_closed,
                           on_case_mutation, recompute_posture)

bp = Blueprint("cases", __name__)

EVENT_TYPES = ("INJURY", "SKIN_DISORDER", "RESPIRATORY", "POISONING",
               "HEARING_LOSS", "OTHER_ILLNESS")
SEVERE_EVENTS = ("NONE", "FATALITY", "INPATIENT_HOSPITALIZATION", "AMPUTATION",
                 "EYE_LOSS")
REPORT_KINDS = ("FATALITY", "INPATIENT_HOSPITALIZATION", "AMPUTATION",
                "EYE_LOSS")
CLASSIFICATIONS = ("FIRST_AID_ONLY", "MEDICAL_TREATMENT",
                   "JOB_TRANSFER_RESTRICTION", "DAYS_AWAY", "DEATH")
DART_CLASSES = ("JOB_TRANSFER_RESTRICTION", "DAYS_AWAY", "DEATH")
DAY_TYPES = ("DAYS_AWAY", "RESTRICTED")

INTAKE_ROLES = ("SafetyOfficer", "RecordkeepingCoordinator")
SO = ("SafetyOfficer",)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.post("/safety/cases")
def create_case():
    auth = get_auth()
    require_roles(auth, INTAKE_ROLES)
    data = get_body()
    establishment_id = req_str(data, "establishment_id")
    employee_id = req_str(data, "employee_id")
    occurred = req_dt(data, "occurred_at")
    description = req_str(data, "description")
    body_part = req_str(data, "body_part")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    is_privacy = opt_bool(data, "is_privacy_case", False)
    is_severe = opt_enum(data, "is_severe_event", SEVERE_EVENTS, "NONE")

    est = lookup(STORE.establishments, establishment_id)
    emp = lookup(STORE.employees, employee_id)
    if emp["company_id"] != est["company_id"]:
        raise_error(ERR_CROSS_COMPANY_REFERENCE,
                    "Employee and establishment belong to different companies")

    # Intake is atomic: INTAKE -> PENDING_REVIEW with all intake side effects.
    seq = STORE.next_case_seq(est["id"])
    case = base_fields()
    case.update({
        "establishment_id": est["id"],
        "employee_id": emp["id"],
        "case_number": "CASE-%d-%04d-%03d" % (est["_seq_num"],
                                              occurred.year, seq),
        "occurred_at": fmt_iso(occurred),
        "reported_at": now_iso(),
        "description": description,
        "body_part": body_part,
        "event_type": event_type,
        "is_privacy_case": is_privacy,
        "is_severe_event": is_severe,
        "status": "PENDING_REVIEW",
        "classification": "NONE",
        "is_recordable": False,
        "is_dart": False,
        "days_away_count": 0,
        "restricted_days_count": 0,
        "recordability_deadline": fmt_iso(occurred + timedelta(days=7)),
        "log_year": occurred.year,
        "revision_index": 0,
        "_manual_day_close": False,
    })
    STORE.cases[case["id"]] = case
    return success_object(serialize_case(case), status=201)


@bp.get("/safety/cases/<caseId>")
def get_case(caseId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    case = lookup(STORE.cases, caseId)
    return success_object(serialize_case(case))


# ---------------------------------------------------------------------------
# Classification / reclassification (OCC-guarded, PRD §2.8)
# ---------------------------------------------------------------------------

def _void_active_entries(case):
    for e in STORE.day_entries.values():
        if e["case_id"] == case["id"] and e["status"] == "ACTIVE":
            e["status"] = "VOIDED"


def _check_case_version(case, data):
    expected = req_version(data, "expected_case_version")
    if expected != case["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_case_version does not match the current case "
                    "version")


@bp.post("/safety/cases/<caseId>/classify")
def classify_case(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    classification = req_enum(data, "classification", CLASSIFICATIONS)
    privacy = opt_bool(data, "is_privacy_case", None)
    _check_case_version(case, data)

    est = STORE.establishments[case["establishment_id"]]
    status = case["status"]
    if status == "PENDING_REVIEW":
        if est["is_partially_exempt"]:
            raise_error(ERR_ESTABLISHMENT_EXEMPT,
                        "Partially exempt establishment does not keep a 300 "
                        "log; classification refused")
        deadline = parse_datetime(case["recordability_deadline"])
        if classification != "DEATH" and now_dt() > deadline:
            raise_error(ERR_RECORDABILITY_WINDOW_PASSED,
                        "Recordability determination is past occurred_at + 7 "
                        "days")
        if classification == "FIRST_AID_ONLY":
            case["status"] = "NOT_RECORDABLE"
            case["is_recordable"] = False
            case["is_dart"] = False
        else:
            case["status"] = "RECORDABLE"
            case["is_recordable"] = True
            case["is_dart"] = classification in DART_CLASSES
        case["classification"] = classification
    elif status == "RECORDABLE":
        # Line-of-duty correction straight to NOT_RECORDABLE, only while the
        # case has never been through the reclassification loop.
        if classification != "FIRST_AID_ONLY" or case["revision_index"] != 0:
            raise_error(ERR_INVALID_STATE,
                        "Transition not allowed from current state")
        case["status"] = "NOT_RECORDABLE"
        case["classification"] = classification
        case["is_recordable"] = False
        case["is_dart"] = False
        _void_active_entries(case)
    elif status == "RECLASSIFIED":
        if classification == case["classification"]:
            raise_error(ERR_INVALID_STATE,
                        "New classification must differ from the current one")
        if classification == "FIRST_AID_ONLY":
            case["status"] = "NOT_RECORDABLE"
            case["is_recordable"] = False
            case["is_dart"] = False
            _void_active_entries(case)
        else:
            case["status"] = "RECORDABLE"
            case["is_recordable"] = True
            case["is_dart"] = classification in DART_CLASSES
        case["classification"] = classification
    else:
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")

    if privacy is not None:
        case["is_privacy_case"] = privacy
    rollup_case(case)
    bump(case)
    on_case_mutation(case)
    recompute_posture(est)
    return success_object(serialize_case(case))


@bp.post("/safety/cases/<caseId>/reclassify")
def reclassify_case(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    new_classification = opt_enum(data, "new_classification", CLASSIFICATIONS)
    _check_case_version(case, data)
    if case["status"] != "RECORDABLE":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    has_entries = any(e["case_id"] == case["id"] and e["status"] != "VOIDED"
                      for e in STORE.day_entries.values())
    if not has_entries and new_classification is None:
        raise_error(ERR_INVALID_STATE,
                    "Reclassification requires a non-voided day-count entry "
                    "or a new_classification")
    for s in STORE.summaries.values():
        if (s["establishment_id"] == case["establishment_id"]
                and s["year"] == case["log_year"] and s["status"] == "POSTED"):
            raise_error(ERR_SUMMARY_LOCKED,
                        "Annual summary for the case's log year is POSTED")
    case["status"] = "RECLASSIFIED"
    case["revision_index"] += 1
    bump(case)
    on_case_mutation(case)
    return success_object(serialize_case(case))


@bp.post("/safety/cases/<caseId>/close-day-count")
def close_day_count(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    _check_case_version(case, data)
    if case["status"] not in ("RECORDABLE", "RECLASSIFIED"):
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    case["_manual_day_close"] = True
    bump(case)
    return success_object(serialize_case(case))


@bp.post("/safety/cases/<caseId>/finalize")
def finalize_case(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    _check_case_version(case, data)
    if case["status"] != "RECORDABLE":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    # Business gates run in the pinned order of PRD §2.9: severe-injury clock
    # consistency before referential integrity.
    if case["is_severe_event"] != "NONE":
        has_report = any(r["case_id"] == case["id"]
                         for r in STORE.severe_reports.values())
        if not has_report:
            raise_error(ERR_SEVERE_REPORT_REQUIRED,
                        "Case has a severe event but no agency report on "
                        "file")
    inv = next((i for i in STORE.investigations.values()
                if i["case_id"] == case["id"]), None)
    if inv is None or inv["status"] != "CLOSED":
        raise_error(ERR_INVESTIGATION_OPEN,
                    "Investigation does not exist or is not CLOSED")
    if not day_count_closed(case):
        raise_error(ERR_DAY_COUNT_OPEN, "Day counting is still open")
    open_actions = [a for a in STORE.corrective_actions.values()
                    if a.get("case_id") == case["id"]
                    and a["status"] not in ("VERIFIED", "CANCELLED")]
    if open_actions:
        raise_error(ERR_CORRECTIVE_ACTION_OPEN,
                    "Linked corrective actions must be VERIFIED or CANCELLED")
    case["status"] = "FINALIZED"
    bump(case)
    return success_object(serialize_case(case))


# ---------------------------------------------------------------------------
# Day-count entries (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.get("/safety/cases/<caseId>/day-entries")
def list_day_entries(caseId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.cases, caseId)
    status = query_str("status")
    items = [e for e in STORE.day_entries.values()
             if e["case_id"] == caseId
             and (status is None or e["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.post("/safety/cases/<caseId>/day-entries")
def create_day_entry(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    day_type = req_enum(data, "day_type", DAY_TYPES)
    start = req_date(data, "start_date")
    end = req_date(data, "end_date")
    if case["status"] not in ("RECORDABLE", "RECLASSIFIED"):
        raise_error(ERR_INVALID_STATE,
                    "Day entries attach only to RECORDABLE or RECLASSIFIED "
                    "cases")
    if end < start:
        raise_error(ERR_DAY_INTERVAL_INVALID,
                    "end_date must not be earlier than start_date")
    for e in STORE.day_entries.values():
        if (e["case_id"] == case["id"] and e["status"] == "ACTIVE"
                and e["day_type"] == day_type):
            s2 = parse_date(e["start_date"])
            e2 = parse_date(e["end_date"])
            if start <= e2 and s2 <= end:
                raise_error(ERR_DAY_INTERVAL_INVALID,
                            "Interval overlaps an ACTIVE %s interval"
                            % day_type)
    entry = {
        "id": new_id(),
        "case_id": case["id"],
        "day_type": day_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "calendar_days": (end - start).days + 1,
        "status": "ACTIVE",
        "created_at": now_iso(),
        "_seq": STORE.next_seq(),
    }
    STORE.day_entries[entry["id"]] = entry
    rollup_case(case)
    on_case_mutation(case)
    return success_object(serialize(entry), status=201)


@bp.post("/safety/cases/<caseId>/day-entries/<entryId>/void")
def void_day_entry(caseId, entryId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    entry = STORE.day_entries.get(entryId)
    if entry is None or entry["case_id"] != case["id"]:
        raise_error(ERR_NOT_FOUND, "Day-count entry not found on this case")
    if case["status"] == "FINALIZED":
        raise_error(ERR_INVALID_STATE, "Case is FINALIZED and locked")
    if entry["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Entry is not ACTIVE")
    entry["status"] = "VOIDED"
    rollup_case(case)
    on_case_mutation(case)
    return success_object(serialize(entry))


# ---------------------------------------------------------------------------
# Investigation / severe-report / corrective-action reverse lookups on a case
# ---------------------------------------------------------------------------

@bp.get("/safety/cases/<caseId>/investigation")
def get_case_investigation(caseId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    lookup(STORE.cases, caseId)
    items = [i for i in STORE.investigations.values()
             if i["case_id"] == caseId]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(i) for i in page], limit, offset, total)


@bp.get("/safety/cases/<caseId>/severe-reports")
def list_case_severe_reports(caseId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.cases, caseId)
    items = [r for r in STORE.severe_reports.values()
             if r["case_id"] == caseId]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/safety/cases/<caseId>/corrective-actions")
def list_case_corrective_actions(caseId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.cases, caseId)
    items = [a for a in STORE.corrective_actions.values()
             if a.get("case_id") == caseId]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Severe-injury agency reports (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/safety/cases/<caseId>/severe-reports")
def create_severe_report(caseId):
    auth = get_auth()
    require_roles(auth, SO)
    case = lookup(STORE.cases, caseId)
    data = get_body()
    report_kind = req_enum(data, "report_kind", REPORT_KINDS)
    occurred = req_dt(data, "occurred_at")
    reported = req_dt(data, "reported_to_agency_at")

    # Severe-injury clock consistency (priority 5) runs before uniqueness (8).
    if occurred != parse_datetime(case["occurred_at"]):
        raise_error(ERR_SEVERE_REPORT_REQUIRED,
                    "occurred_at must equal the case's occurred_at")
    if any(r["case_id"] == case["id"] for r in STORE.severe_reports.values()):
        raise_error(ERR_DUPLICATE,
                    "A severe-injury report already exists for this case")

    hours = 8 if report_kind == "FATALITY" else 24
    deadline = occurred + timedelta(hours=hours)
    within_clock = reported <= deadline   # boundary inclusive, to the second
    report = base_fields()
    report.update({
        "case_id": case["id"],
        "report_kind": report_kind,
        "occurred_at": fmt_iso(occurred),
        "reported_to_agency_at": fmt_iso(reported),
        "deadline": fmt_iso(deadline),
        "within_clock": within_clock,
        "status": "TIMELY" if within_clock else "LATE",
    })
    STORE.severe_reports[report["id"]] = report
    if report["status"] == "LATE":
        est = STORE.establishments.get(case["establishment_id"])
        if est:
            recompute_posture(est)
    return success_object(serialize(report), status=201)
