"""Routes: diversion agreements, acceptance, service assignments."""

from decimal import Decimal
from flask import Blueprint, request, g

from errors import ApiError
from auth import endpoint, ALL_ROLES
from store import db, now, base_fields, touch, serialize
from envelope import success, parse_pagination, list_response
import bodyutil as B
import calc
from domain import (charges_of_case, account_of_case, diversion_of_case,
                    assignments_of_diversion, recompute_account, recompute_agreement,
                    maybe_complete_diversion)
from routes_core import get_case

bp_diversion = Blueprint("diversion", __name__)

ASSIGN_TYPES = {"COMMUNITY_SERVICE", "EDUCATION_CLASS"}


def get_diversion(did):
    d = db.diversion_agreements.get(did)
    if d is None:
        raise ApiError("ERR_DIVERSION_NOT_FOUND", "diversion agreement not found")
    return d


def get_assignment(aid):
    a = db.service_assignments.get(aid)
    if a is None:
        raise ApiError("ERR_SERVICE_ASSIGNMENT_NOT_FOUND", "service assignment not found")
    return a


def get_site(sid):
    s = db.service_sites.get(sid)
    if s is None:
        raise ApiError("ERR_SERVICE_SITE_NOT_FOUND", "service site not found")
    return s


# ---------------------------------------------------------------------------
# diversion agreements
# ---------------------------------------------------------------------------
@bp_diversion.post("/cases/<cid>/diversion-agreements")
@endpoint(["Judge"])
def grant_diversion(cid):
    case = get_case(cid)
    # state: case must be ARRAIGNED with an eligible plea
    if case["status"] != "ARRAIGNED":
        raise ApiError("ERR_INVALID_STATE", "case is not ARRAIGNED")
    arr = _held_arraignment(cid)
    if arr is None or arr.get("plea") not in ("GUILTY", "NO_CONTEST"):
        raise ApiError("ERR_INVALID_STATE", "recorded plea does not permit diversion")
    # business referential
    defendant = db.defendants[case["defendant_id"]]
    if defendant["prior_diversion_count"] >= calc.FIRST_OFFENDER_MAX_PRIOR:
        raise ApiError("ERR_NOT_FIRST_OFFENDER", "defendant is not a first offender")
    charges = charges_of_case(cid)
    if not any(c["is_diversion_eligible"] for c in charges):
        raise ApiError("ERR_CHARGE_NOT_ELIGIBLE", "no diversion-eligible charge on the case")
    # body validation (tier 11)
    body = B.get_body()
    mandated = B.req_decimal(body, "mandated_service_hours", minimum=Decimal("0"))
    sessions = B.req_int(body, "required_class_sessions", minimum=0)
    program_fee = B.req_decimal(body, "program_fee", minimum=Decimal("0"))
    deadline = B.req_datetime(body, "program_deadline")

    agr = base_fields()
    agr.update({
        "case_id": cid,
        "mandated_service_hours": mandated,
        "required_class_sessions": sessions,
        "program_fee": program_fee,
        "program_deadline": deadline,
        "assigned_service_hours": Decimal("0"),
        "completed_service_hours": Decimal("0"),
        "completed_class_sessions": 0,
        "provisional_compliance_pct": Decimal("0.00"),
        "final_compliance_pct": Decimal("0.00"),
        "status": "OFFERED",
    })
    db.diversion_agreements[agr["id"]] = agr

    # case -> DIVERSION_GRANTED
    case["status"] = "DIVERSION_GRANTED"
    touch(case)
    # finalize the ledger assessment
    acct = account_of_case(cid)
    fines, court_fee, surcharge, pf = calc.fine_components(charges, "final", program_fee)
    acct["_fines"] = fines
    acct["_court_fee"] = court_fee
    acct["_surcharge"] = surcharge
    acct["_program_fee"] = pf
    acct["status"] = "ASSESSED"
    recompute_account(acct)
    touch(acct, bump_version=False)
    recompute_agreement(agr)
    return success(serialize(agr), status=201)


def _held_arraignment(cid):
    held = [a for a in db.arraignments.values()
            if a["case_id"] == cid and a["status"] == "HELD"]
    if not held:
        return None
    held.sort(key=lambda r: r.get("_seq", 0))
    return held[-1]


@bp_diversion.get("/cases/<cid>/diversion-agreements")
@endpoint(ALL_ROLES)
def list_diversions(cid):
    get_case(cid)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.diversion_agreements.values() if d["case_id"] == cid]
    return list_response(items, limit, offset, serialize)


@bp_diversion.post("/diversion-agreements/<did>/accept")
@endpoint(["Defendant"])
def accept_diversion(did):
    agr = get_diversion(did)
    case = db.cases[agr["case_id"]]
    if g.user_id != case["defendant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "defendant may act only on their own case")
    if agr["status"] != "OFFERED" or case["status"] != "DIVERSION_GRANTED":
        raise ApiError("ERR_INVALID_STATE", "agreement is not in OFFERED state")
    agr["status"] = "IN_PROGRESS"
    touch(agr)
    return success(serialize(agr), status=200)


# ---------------------------------------------------------------------------
# service assignments
# ---------------------------------------------------------------------------
@bp_diversion.post("/diversion-agreements/<did>/service-assignments")
@endpoint(["ProbationOfficer"])
def create_assignment(did):
    agr = get_diversion(did)
    if agr["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "diversion agreement is not IN_PROGRESS")
    body = B.get_body()
    site_id = B.req_str(body, "service_site_id")
    atype = B.req_enum(body, "assignment_type", ASSIGN_TYPES)
    req_hours = B.req_decimal(body, "required_hours", minimum=Decimal("0"))
    start = B.req_datetime(body, "session_start")
    end = B.req_datetime(body, "session_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "session_end must be after session_start")
    site = get_site(site_id)
    if atype != site["site_type"]:
        raise ApiError("ERR_CHARGE_NOT_ELIGIBLE", "assignment_type must match the site's site_type")
    # capacity: count time-overlapping sessions already at this site
    overlap = 0
    for a in db.service_assignments.values():
        if a["service_site_id"] != site_id:
            continue
        if a["session_start"] < end and start < a["session_end"]:
            overlap += 1
    if overlap + 1 > site["concurrent_capacity"]:
        raise ApiError("ERR_SERVICE_SITE_AT_CAPACITY", "service site at concurrent capacity")

    rec = base_fields()
    rec.update({
        "diversion_id": did,
        "service_site_id": site_id,
        "assignment_type": atype,
        "required_hours": req_hours,
        "session_start": start,
        "session_end": end,
        "completed_hours": Decimal("0"),
        "assigned_by_officer_id": g.user_id,
        "status": "ASSIGNED",
    })
    db.service_assignments[rec["id"]] = rec
    recompute_agreement(agr)
    return success(serialize(rec), status=201)


@bp_diversion.get("/service-assignments/<aid>")
@endpoint(ALL_ROLES)
def fetch_assignment(aid):
    return success(serialize(get_assignment(aid)))


@bp_diversion.get("/service-assignments")
@endpoint(ALL_ROLES)
def list_assignments():
    limit, offset = parse_pagination(request.args)
    diversion_id = request.args.get("diversion_id")
    site_id = request.args.get("service_site_id")
    items = list(db.service_assignments.values())
    if diversion_id is not None:
        items = [a for a in items if a["diversion_id"] == diversion_id]
    if site_id is not None:
        items = [a for a in items if a["service_site_id"] == site_id]
    return list_response(items, limit, offset, serialize)


@bp_diversion.post("/service-assignments/<aid>/progress")
@endpoint(["ProbationOfficer"])
def progress_assignment(aid):
    a = get_assignment(aid)
    if a["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "assignment cannot accept progress")
    body = B.get_body()
    hours = B.req_decimal(body, "hours_logged", exclusive_min=Decimal("0"))
    a["completed_hours"] = calc.to_decimal(a["completed_hours"]) + hours
    if a["status"] == "ASSIGNED":
        a["status"] = "IN_PROGRESS"
    touch(a)
    agr = get_diversion(a["diversion_id"])
    recompute_agreement(agr)
    return success(serialize(a), status=200)


@bp_diversion.post("/service-assignments/<aid>/verify-completion")
@endpoint(["ProbationOfficer"])
def verify_assignment(aid):
    a = get_assignment(aid)
    agr = get_diversion(a["diversion_id"])
    # state
    if a["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "assignment is not IN_PROGRESS")
    if agr["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "owning diversion agreement is not IN_PROGRESS")
    # safety tier
    if g.user_id == a["assigned_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "verifier must differ from the assigning officer")
    if calc.to_decimal(a["completed_hours"]) < calc.to_decimal(a["required_hours"]):
        raise ApiError("ERR_ASSIGNMENT_NOT_VERIFIABLE", "completed_hours below required_hours")

    # tentatively complete, then attempt the agreement completion cascade;
    # roll back atomically if the ledger-settled gate blocks completion.
    old_status = a["status"]
    old_updated = a["updated_at"]
    old_version = a["version"]
    a["status"] = "COMPLETED"
    touch(a)
    recompute_agreement(agr)
    try:
        maybe_complete_diversion(agr)
    except ApiError:
        a["status"] = old_status
        a["updated_at"] = old_updated
        a["version"] = old_version
        recompute_agreement(agr)
        raise
    return success(serialize(a), status=200)


@bp_diversion.post("/service-assignments/<aid>/waive")
@endpoint(["Judge"])
def waive_assignment(aid):
    a = get_assignment(aid)
    agr = get_diversion(a["diversion_id"])
    if agr["status"] != "IN_PROGRESS" or a["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "assignment cannot be waived")
    a["status"] = "WAIVED"
    touch(a)
    recompute_agreement(agr)
    return success(serialize(a), status=200)
