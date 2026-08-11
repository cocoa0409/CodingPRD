"""GrantProgram and GrantApplication endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import now, stamp_new, store, touch
from errors import fail
from middleware import check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lookups
from services.calculations import grant_award_final, grant_award_provisional
from util import (
    body_json,
    fmt_dt,
    pagination_args,
    parse_dt,
    req_int,
    req_number,
    req_str,
    require_dt,
)

bp = Blueprint("grants", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

OPEN_APPLICATION_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED", "APPROVED", "CLAIMED")


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# GrantPrograms
# ---------------------------------------------------------------------------

@bp.route("/ct/grant-programs", methods=["POST"])
def create_program():
    require_roles("CollegeAdmin")
    body = body_json()
    code = req_str(body, "code")
    name = req_str(body, "name")
    appropriation = req_int(body, "appropriation_cents", min_value=1)
    max_share = req_number(body, "max_share_pct", min_value=0)
    if max_share > 1:
        fail("ERR_INVALID_REQUEST", "Field 'max_share_pct' must be <= 1")
    cap = req_int(body, "cap_per_trainee_cents", min_value=1)
    window_end = fmt_dt(require_dt(body.get("application_window_end"), "application_window_end"))
    claim_days = req_int(body, "claim_deadline_days", min_value=1)
    if any(p["code"] == code for p in store["programs"].values()):
        fail("ERR_INVALID_REQUEST", f"Grant program code '{code}' already exists")
    rec = stamp_new(
        {
            "id": db.new_id(),
            "code": code,
            "name": name,
            "appropriation_cents": appropriation,
            "max_share_pct": max_share,
            "cap_per_trainee_cents": cap,
            "application_window_end": window_end,
            "claim_deadline_days": claim_days,
            "available_cents": appropriation,
            "reserved_cents": 0,
            "committed_cents": 0,
            "reimbursed_cents": 0,
            "status": "OPEN",
        }
    )
    store["programs"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/grant-programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles(*READ_ROLES)
    return ok(serialize(lookups.get_or_404("programs", pid, "GrantProgram")))


@bp.route("/ct/grant-programs/<pid>/suspend", methods=["POST"])
def suspend_program(pid):
    require_roles("CollegeAdmin")
    program = lookups.get_or_404("programs", pid, "GrantProgram")
    if program["status"] != "OPEN":
        fail("ERR_INVALID_STATE", f"Cannot suspend a program in {program['status']}")
    program["status"] = "SUSPENDED"
    touch(program)
    return ok(serialize(program))


@bp.route("/ct/grant-programs/<pid>/reopen", methods=["POST"])
def reopen_program(pid):
    require_roles("CollegeAdmin")
    program = lookups.get_or_404("programs", pid, "GrantProgram")
    if program["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", f"Cannot reopen a program in {program['status']}")
    program["status"] = "OPEN"
    touch(program)
    return ok(serialize(program))


@bp.route("/ct/grant-programs/<pid>/close", methods=["POST"])
def close_program(pid):
    require_roles("CollegeAdmin")
    program = lookups.get_or_404("programs", pid, "GrantProgram")
    if program["status"] not in ("OPEN", "SUSPENDED"):
        fail("ERR_INVALID_STATE", f"Cannot close a program in {program['status']}")
    if program["reserved_cents"] != 0 or program["committed_cents"] != 0:
        fail("ERR_INVALID_STATE", "Program has reserved or committed funds")
    program["status"] = "CLOSED"
    touch(program)
    return ok(serialize(program))


# ---------------------------------------------------------------------------
# GrantApplications
# ---------------------------------------------------------------------------

@bp.route("/ct/cohorts/<cid>/grant-applications", methods=["POST"])
def create_application(cid):
    require_roles("WorkforceCoordinator")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    body = body_json()
    program_id = req_str(body, "program_id")
    requested = req_int(body, "requested_cents", min_value=1)
    expected = body.get("expected_cohort_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST", "Field 'expected_cohort_version' is required and must be an integer")
    program = store["programs"].get(program_id)
    if program is None:
        fail("ERR_INVALID_REQUEST", f"program_id {program_id} does not exist")
    if cohort["delivery_status"] not in ("SCHEDULED", "LAUNCHED", "IN_PROGRESS"):
        fail(
            "ERR_INVALID_STATE",
            f"Cannot create a grant application for a cohort in {cohort['delivery_status']}",
        )
    if expected != cohort["version"]:
        fail(
            "ERR_STALE_VERSION",
            f"expected_cohort_version {expected} does not match current version {cohort['version']}",
        )
    for existing in lookups.applications_of_cohort(cid):
        if existing["program_id"] == program_id and existing["status"] in OPEN_APPLICATION_STATES:
            fail(
                "ERR_INVALID_REQUEST",
                "An open application already exists for this cohort and program",
            )
    rec = stamp_new(
        {
            "id": db.new_id(),
            "cohort_id": cid,
            "program_id": program_id,
            "requested_cents": requested,
            "provisional_award_cents": None,
            "final_award_cents": None,
            "reserved_cents": 0,
            "committed_cents": 0,
            "reimbursed_cents": 0,
            "status": "DRAFT",
            "submitted_at": None,
            "decided_at": None,
            "claim_by": None,
            "claimed_at": None,
        }
    )
    store["applications"][rec["id"]] = rec
    touch(cohort)  # creation increments the cohort's version (PRD 3.3)
    return ok(serialize(rec), 201)


@bp.route("/ct/grant-applications/<aid>", methods=["GET"])
def get_application(aid):
    uid, role = require_roles(*READ_ROLES)
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    check_employer_scope(uid, role, lookups.employer_id_of_application(application))
    return ok(serialize(application))


@bp.route("/ct/grant-applications", methods=["GET"])
def list_applications():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["applications"].values())
    if role == "EmployerContact":
        items = [a for a in items if lookups.employer_id_of_application(a) == uid]
    f_program = request.args.get("program_id")
    f_cohort = request.args.get("cohort_id")
    f_status = request.args.get("status")
    if f_program is not None:
        items = [a for a in items if a["program_id"] == f_program]
    if f_cohort is not None:
        items = [a for a in items if a["cohort_id"] == f_cohort]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return _paginate(items)


@bp.route("/ct/cohorts/<cid>/grant-applications", methods=["GET"])
def list_cohort_applications(cid):
    uid, role = require_roles(*READ_ROLES)
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    check_employer_scope(uid, role, lookups.employer_id_of_cohort(cohort))
    return _paginate(lookups.applications_of_cohort(cid))


@bp.route("/ct/grant-applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    require_roles("WorkforceCoordinator")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE", f"Cannot submit an application in {application['status']}")
    program = store["programs"][application["program_id"]]
    if program["status"] != "OPEN":
        fail("ERR_GRANT_PROGRAM_NOT_OPEN", f"Grant program is {program['status']}")
    if now() > parse_dt(program["application_window_end"]):
        fail("ERR_GRANT_WINDOW_CLOSED", "The program application window has closed")
    application["status"] = "SUBMITTED"
    application["submitted_at"] = fmt_dt(now())
    touch(application)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/start_review", methods=["POST"])
def start_review(aid):
    require_roles("GrantOfficer")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", f"Cannot start review of an application in {application['status']}")
    application["status"] = "UNDER_REVIEW"
    touch(application)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/return", methods=["POST"])
def return_application(aid):
    require_roles("GrantOfficer")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", f"Cannot return an application in {application['status']}")
    application["status"] = "RETURNED"
    touch(application)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    require_roles("GrantOfficer")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", f"Cannot approve an application in {application['status']}")
    cohort = store["cohorts"][application["cohort_id"]]
    if cohort["delivery_status"] == "CANCELLED":
        fail("ERR_INVALID_STATE", "Cannot approve an application whose cohort is CANCELLED")
    agreement = store["agreements"][cohort["agreement_id"]]
    program = store["programs"][application["program_id"]]
    award = grant_award_provisional(application, cohort, agreement, program)
    if award > program["available_cents"]:
        fail("ERR_GRANT_CAPACITY_EXCEEDED", "Provisional award exceeds program available funds")
    decided = now()
    application["provisional_award_cents"] = award
    application["reserved_cents"] = award
    application["status"] = "APPROVED"
    application["decided_at"] = fmt_dt(decided)
    application["claim_by"] = fmt_dt(decided + timedelta(days=program["claim_deadline_days"]))
    touch(application)
    program["reserved_cents"] += award
    program["available_cents"] -= award
    touch(program)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    require_roles("GrantOfficer")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", f"Cannot deny an application in {application['status']}")
    application["status"] = "DENIED"
    application["decided_at"] = fmt_dt(now())
    touch(application)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/claim", methods=["POST"])
def claim_application(aid):
    require_roles("WorkforceCoordinator")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", f"Cannot claim an application in {application['status']}")
    cohort = store["cohorts"][application["cohort_id"]]
    if cohort["delivery_status"] != "CREDENTIALED":
        fail("ERR_COHORT_NOT_CREDENTIALED", "The cohort has not reached CREDENTIALED")
    if now() > parse_dt(application["claim_by"]):
        fail("ERR_GRANT_WINDOW_CLOSED", "The claim window has closed")
    program = store["programs"][application["program_id"]]
    final_award = grant_award_final(application, cohort, program)
    old_reserved = application["reserved_cents"]
    program["reserved_cents"] -= old_reserved
    program["available_cents"] += old_reserved - final_award
    program["committed_cents"] += final_award
    touch(program)
    application["final_award_cents"] = final_award
    application["committed_cents"] = final_award
    application["reserved_cents"] = 0
    application["claimed_at"] = fmt_dt(now())
    application["status"] = "CLAIMED"
    touch(application)
    return ok(serialize(application))


@bp.route("/ct/grant-applications/<aid>/mark_paid", methods=["POST"])
def mark_application_paid(aid):
    require_roles("GrantOfficer")
    application = lookups.get_or_404("applications", aid, "GrantApplication")
    if application["status"] != "CLAIMED":
        fail("ERR_INVALID_STATE", f"Cannot mark paid an application in {application['status']}")
    program = store["programs"][application["program_id"]]
    committed = application["committed_cents"]
    program["committed_cents"] -= committed
    program["reimbursed_cents"] += committed
    touch(program)
    application["reimbursed_cents"] = committed
    application["committed_cents"] = 0
    application["status"] = "PAID"
    touch(application)
    return ok(serialize(application))
