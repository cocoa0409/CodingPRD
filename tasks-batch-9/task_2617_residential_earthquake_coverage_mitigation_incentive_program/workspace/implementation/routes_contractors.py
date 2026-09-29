"""Contractors, retrofit projects, inspections and the verification cascade
(PRD 3.6)."""

import calc
import envelope
import guards
import store
from errors import ApiError
from flask import Blueprint

bp = Blueprint("contractors", __name__)

PROJECT_OPEN_STATUSES = ("SCHEDULED", "IN_PROGRESS", "AWAITING_INSPECTION",
                         "REWORK_REQUIRED")


# --- contractors ----------------------------------------------------------

@bp.post("/contractors")
def create_contractor():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("business_name", "license_no", "certified_scopes",
                           "certification_expires_at"))
    business_name = guards.required_string(body, "business_name")
    license_no = guards.required_string(body, "license_no")
    scopes = guards.enum_list(body, "certified_scopes", "scope")
    expires = guards.instant(body, "certification_expires_at")
    guards.unique_violation("contractors", "license_no", license_no)
    row = store.insert("contractors", {
        "business_name": business_name,
        "license_no": license_no,
        "certified_scopes": scopes,
        "certification_status": "CERTIFIED",
        "certification_expires_at": store.iso(expires),
        "open_project_count": 0,
        "failed_inspection_count": 0,
    })
    return envelope.created(store.public(row))


@bp.post("/contractors/<row_id>/certification")
def set_certification(row_id):
    guards.auth(("ProgramAdmin",))
    contractor = guards.path_row("contractors", row_id)
    body = guards.body()
    guards.required(body, ("certification_status",))
    target = guards.enum(body, "certification_status", "certification_status")
    expires = guards.instant(body, "certification_expires_at", optional=True)
    current = contractor["certification_status"]
    if target == "SUSPENDED":
        if current != "CERTIFIED":
            raise ApiError("ERR_CONTRACTOR_INVALID_CERTIFICATION_TRANSITION")
    else:
        if current not in ("PROBATION", "SUSPENDED"):
            raise ApiError("ERR_CONTRACTOR_INVALID_CERTIFICATION_TRANSITION")
    contractor["certification_status"] = target
    if expires is not None:
        contractor["certification_expires_at"] = store.iso(expires)
    store.touch(contractor)
    return envelope.object_response(store.public(contractor))


@bp.get("/contractors/<row_id>")
def read_contractor(row_id):
    role = guards.auth(("ProgramAdmin", "GrantReviewer", "FieldInspector",
                        "CertifiedContractor", "Policyholder"))
    contractor = guards.path_row("contractors", row_id)
    if role == "CertifiedContractor":
        guards.owner_must_be(contractor["id"])
    return envelope.object_response(store.public(contractor))


@bp.get("/contractors")
def list_contractors():
    guards.auth(("ProgramAdmin", "GrantReviewer", "FieldInspector", "Policyholder"))
    rows = guards.filtered(store.all_rows("contractors"),
                           (("certification_status", "certification_status"),))
    return envelope.list_response(rows)


# --- retrofit projects ----------------------------------------------------

def _open_projects(contractor_id):
    return [row for row in store.DB["projects"].values()
            if row["contractor_id"] == contractor_id
            and row["status"] in PROJECT_OPEN_STATUSES]


@bp.post("/retrofit-projects")
def create_project():
    role = guards.auth(("ProgramAdmin", "CertifiedContractor"))
    body = guards.body()
    fks = guards.body_fks(body, ("grant_id", "contractor_id"))
    contractor = fks.get("contractor_id")
    if role == "CertifiedContractor" and contractor is not None:
        guards.owner_must_be(contractor["id"])
    guards.required(body, ("grant_id", "contractor_id"))
    grant = fks["grant_id"]
    if contractor["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_CERTIFIED")
    if store.dt_of(contractor, "certification_expires_at") <= store.clock_now():
        raise ApiError("ERR_CONTRACTOR_CERTIFICATION_EXPIRED")
    if grant["status"] != "FUNDS_RESERVED":
        raise ApiError("ERR_GRANT_FUNDS_NOT_RESERVED")
    if len(_open_projects(contractor["id"])) >= calc.MAX_OPEN_PROJECTS_PER_CONTRACTOR:
        raise ApiError("ERR_CONTRACTOR_PROJECT_CAP")
    row = store.insert("projects", {
        "grant_id": grant["id"],
        "contractor_id": contractor["id"],
        "scope_code": grant["requested_scope"],
        "status": "SCHEDULED",
        "inspection_attempts": 0,
        "started_at": None,
        "verified_at": None,
    })
    contractor["open_project_count"] += 1
    store.touch(contractor)
    return envelope.created(store.public(row))


@bp.post("/retrofit-projects/<row_id>/start-work")
def start_work(row_id):
    role = guards.auth(("CertifiedContractor", "ProgramAdmin"))
    project = guards.path_row("projects", row_id)
    if role == "CertifiedContractor":
        guards.owner_must_be(project["contractor_id"])
    if project["status"] not in ("SCHEDULED", "REWORK_REQUIRED"):
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    first_start = project["status"] == "SCHEDULED"
    project["status"] = "IN_PROGRESS"
    if first_start:
        project["started_at"] = store.now_iso()
    store.touch(project)
    return envelope.object_response(store.public(project))


@bp.post("/retrofit-projects/<row_id>/request-inspection")
def request_inspection(row_id):
    guards.auth(("CertifiedContractor",))
    project = guards.path_row("projects", row_id)
    guards.owner_must_be(project["contractor_id"])
    if project["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    project["status"] = "AWAITING_INSPECTION"
    store.touch(project)
    return envelope.object_response(store.public(project))


@bp.post("/retrofit-projects/<row_id>/abandon")
def abandon_project(row_id):
    guards.auth(("ProgramAdmin",))
    project = guards.path_row("projects", row_id)
    guards.body()
    if project["status"] not in PROJECT_OPEN_STATUSES:
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    project["status"] = "ABANDONED"
    store.touch(project)
    contractor = store.DB["contractors"].get(project["contractor_id"])
    if contractor is not None:
        contractor["open_project_count"] = max(0, contractor["open_project_count"] - 1)
        store.touch(contractor)
    return envelope.object_response(store.public(project))


@bp.get("/retrofit-projects/<row_id>")
def read_project(row_id):
    role = guards.auth(("ProgramAdmin", "GrantReviewer", "FieldInspector",
                        "CertifiedContractor", "Policyholder"))
    project = guards.path_row("projects", row_id)
    if role == "CertifiedContractor":
        guards.owner_must_be(project["contractor_id"])
    return envelope.object_response(store.public(project))


@bp.get("/retrofit-projects")
def list_projects():
    role = guards.auth(("ProgramAdmin", "GrantReviewer", "FieldInspector",
                        "CertifiedContractor"))
    rows = store.all_rows("projects")
    if role == "CertifiedContractor":
        owner = guards.acting_id()
        rows = [row for row in rows if row["contractor_id"] == owner]
    rows = guards.filtered(rows, (("grant_id", "grant_id"),
                                  ("contractor_id", "contractor_id"),
                                  ("status", "status")))
    return envelope.list_response(rows)


# --- inspections ----------------------------------------------------------

def _calendar_conflict(contractor_id, start, end):
    """Rung 60: the requested window widened by sixty minutes on both sides
    must not intersect the half-open window of any PENDING inspection of the
    same contractor whose project is not ABANDONED."""
    wide_start = store.plus_minutes(start, -calc.INSPECTION_BUFFER_MINUTES)
    wide_end = store.plus_minutes(end, calc.INSPECTION_BUFFER_MINUTES)
    for other in store.DB["inspections"].values():
        if other["contractor_id"] != contractor_id or other["result"] != "PENDING":
            continue
        project = store.DB["projects"].get(other["project_id"])
        if project is None or project["status"] == "ABANDONED":
            continue
        other_start = store.dt_of(other, "window_start")
        other_end = store.dt_of(other, "window_end")
        if wide_start < other_end and other_start < wide_end:
            return True
    return False


@bp.post("/inspections")
def book_inspection():
    guards.auth(("FieldInspector", "ProgramAdmin"))
    body = guards.body()
    fks = guards.body_fks(body, ("project_id", "contractor_id"))
    guards.required(body, ("project_id", "window_start", "window_end"))
    start = guards.instant(body, "window_start")
    end = guards.instant(body, "window_end")
    guards.window(start, end)
    project = fks["project_id"]
    if project["status"] != "AWAITING_INSPECTION":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    contractor = store.DB["contractors"][project["contractor_id"]]
    if contractor["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_CERTIFIED")
    if store.dt_of(contractor, "certification_expires_at") <= store.clock_now():
        raise ApiError("ERR_CONTRACTOR_CERTIFICATION_EXPIRED")
    supplied = fks.get("contractor_id")
    if supplied is not None and supplied["id"] != project["contractor_id"]:
        raise ApiError("ERR_INSPECTION_PROJECT_MISMATCH")
    minutes = (end - start).total_seconds() / 60
    if minutes < calc.INSPECTION_MIN_MINUTES or minutes > calc.INSPECTION_MAX_MINUTES:
        raise ApiError("ERR_INSPECTION_DURATION_INVALID")
    if start < store.clock_now():
        raise ApiError("ERR_INSPECTION_IN_PAST")
    if _calendar_conflict(project["contractor_id"], start, end):
        raise ApiError("ERR_INSPECTION_SLOT_OVERLAP")
    row = store.insert("inspections", {
        "project_id": project["id"],
        "contractor_id": project["contractor_id"],
        "window_start": store.iso(start),
        "window_end": store.iso(end),
        "result": "PENDING",
        "inspector_user_id": None,
        "recorded_at": None,
        "deficiency_note": "",
    })
    return envelope.created(store.public(row))


def _pass_cascade(project, contractor):
    """The four-hop verification cascade of PRD 3.6, in the pinned order."""
    now = store.now_iso()
    # hop 1 (the project half; the inspection half is written by the caller)
    project["status"] = "VERIFIED"
    project["verified_at"] = now
    grant = store.DB["grants"].get(project["grant_id"])
    if grant is None:
        return
    # hop 2
    dwelling = store.DB["dwellings"].get(grant["dwelling_id"])
    dwelling_verified = False
    if dwelling is not None:
        dwelling["retrofit_status"] = "VERIFIED"
        dwelling["verified_retrofit_scope"] = project["scope_code"]
        store.touch(dwelling)
        dwelling_verified = True
    grant_completed = grant["status"] == "FUNDS_RESERVED"
    if grant_completed:
        grant["status"] = "VERIFIED_COMPLETE"
        store.touch(grant)
    # hop 3
    if grant_completed:
        cycle = store.DB["cycles"].get(grant["grant_cycle_id"])
        if cycle is not None:
            award = grant["approved_amount_cents"]
            cycle["reserved_cents"] -= award
            cycle["disbursed_cents"] += award
            calc.recompute_uncommitted(cycle)
            store.touch(cycle)
    # hop 3-b
    policy = store.DB["policies"].get(grant["policy_id"]) if grant["policy_id"] else None
    if (dwelling_verified and policy is not None
            and policy["mitigation_status"] == "RETROFIT_PENDING"):
        policy["mitigation_status"] = "RETROFIT_VERIFIED"
        store.touch(policy)
        # hop 4 fires only on a policy that is still ACTIVE
        if policy["lifecycle_status"] == "ACTIVE":
            discount, credit = calc.mitigation_discount(policy, dwelling, grant)
            policy["mitigation_discount_cents"] = discount
            policy["annual_premium_cents"] = policy["base_premium_cents"] - discount
            policy["prorated_credit_cents"] = credit
            policy["mitigation_status"] = "DISCOUNT_APPLIED"
            store.touch(policy)


@bp.post("/inspections/<row_id>/record-result")
def record_result(row_id):
    guards.auth(("FieldInspector",), need_user_id=True)
    inspection = guards.path_row("inspections", row_id)
    body = guards.body()
    guards.required(body, ("result",))
    result = guards.enum(body, "result", "result")
    note = guards.optional_string(body, "deficiency_note")
    project = store.DB["projects"][inspection["project_id"]]
    grant = store.DB["grants"].get(project["grant_id"])
    if grant is not None:
        guards.sod(grant["approved_by_user_id"], "ERR_SOD_INSPECTOR_CONFLICT")
    if inspection["result"] != "PENDING":
        raise ApiError("ERR_INSPECTION_ALREADY_RECORDED")
    if project["status"] != "AWAITING_INSPECTION":
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    contractor = store.DB["contractors"][inspection["contractor_id"]]
    if result == "PASS" and project["scope_code"] not in contractor["certified_scopes"]:
        raise ApiError("ERR_RETROFIT_SCOPE_MISMATCH")
    if store.clock_now() < store.dt_of(inspection, "window_start"):
        raise ApiError("ERR_INSPECTION_WINDOW_NOT_REACHED")
    inspection["result"] = result
    inspection["inspector_user_id"] = guards.acting_id()
    inspection["recorded_at"] = store.now_iso()
    inspection["deficiency_note"] = note
    project["inspection_attempts"] += 1
    if result == "PASS":
        _pass_cascade(project, contractor)
    elif result == "FAIL":
        contractor["failed_inspection_count"] += 1
        if (contractor["failed_inspection_count"] >= calc.PROBATION_FAIL_THRESHOLD
                and contractor["certification_status"] == "CERTIFIED"):
            contractor["certification_status"] = "PROBATION"
        store.touch(contractor)
        project["status"] = "REWORK_REQUIRED"
    store.touch(project)
    store.touch(inspection)
    return envelope.object_response(store.public(inspection))


@bp.get("/inspections/<row_id>")
def read_inspection(row_id):
    role = guards.auth(("ProgramAdmin", "FieldInspector", "CertifiedContractor",
                        "GrantReviewer", "Policyholder"))
    inspection = guards.path_row("inspections", row_id)
    if role == "CertifiedContractor":
        guards.owner_must_be(inspection["contractor_id"])
    return envelope.object_response(store.public(inspection))


@bp.get("/inspections")
def list_inspections():
    role = guards.auth(("ProgramAdmin", "FieldInspector", "CertifiedContractor"))
    rows = store.all_rows("inspections")
    if role == "CertifiedContractor":
        owner = guards.acting_id()
        rows = [row for row in rows if row["contractor_id"] == owner]
    rows = guards.filtered(rows, (("project_id", "project_id"),
                                  ("contractor_id", "contractor_id"),
                                  ("result", "result")))
    return envelope.list_response(rows)
