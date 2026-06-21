"""Service of process."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("service_of_process", __name__)

METHODS = {"PERSONAL", "MAIL", "PUBLICATION"}


@bp.post("/service-of-process")
def create_sop():
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    filing_id = validate.require_str(data, "filing_id")
    served_party_id = validate.require_str(data, "served_party_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    filing = domain.get_or_404(db.filings, filing_id)
    party = domain.get_or_404(db.parties, served_party_id)

    method = validate.enum(data, "method", METHODS)
    validate.require(data, "service_date")
    service_date = data["service_date"]
    if calc.parse_dt(service_date) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid service_date")

    # Same-case referential integrity (priority 5).
    if filing["case_id"] != case_id or party["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "FK belongs to a different case")
    if party["role"] != "DEFENDANT":
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "served_party must be a DEFENDANT")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "filing_id": filing_id,
        "served_party_id": served_party_id,
        "method": method,
        "status": "ATTEMPTED",
        "service_date": service_date,
        "response_due_deadline_id": None,
    })
    db.service_of_process[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/service-of-process/<sop_id>")
def get_sop(sop_id):
    get_actor()
    rec = domain.get_or_404(db.service_of_process, sop_id)
    return success(domain._clean(rec), status=200)


@bp.get("/service-of-process")
def list_sop():
    get_actor()
    args = request.args
    items = list(db.service_of_process.values())
    for field in ("case_id", "filing_id", "served_party_id", "response_due_deadline_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(s) for s in window], status=200, pagination=pagination)


@bp.post("/service-of-process/<sop_id>/complete")
def complete_sop(sop_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    sop = domain.get_or_404(db.service_of_process, sop_id)
    case = db.cases[sop["case_id"]]

    if sop["status"] != "ATTEMPTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Service is not ATTEMPTED")
    if case["status"] != "OPEN":
        raise errors.err(errors.ERR_CASE_NOT_OPEN, "Case is not OPEN")

    party = db.parties[sop["served_party_id"]]
    if party["role"] != "DEFENDANT" or party.get("service_status") == "SERVED":
        raise errors.err(errors.ERR_PARTY_ALREADY_SERVED, "Defendant already served")

    sop["status"] = "COMPLETED"

    # Hop 1: party SERVED.
    party["service_status"] = "SERVED"
    party["served_at"] = _clock_iso()
    db.touch(party)

    # Hop 2: create RESPONSE deadline (COURT_DAYS, 30, anchored on service_date).
    court = db.courts[case["court_id"]]
    dl = db.base_record()
    dl.update({
        "case_id": case["id"],
        "deadline_type": "RESPONSE",
        "anchor_event": "SERVICE_COMPLETED",
        "anchor_date": sop["service_date"],
        "interval_days": 30,
        "counting_mode": "COURT_DAYS",
        "due_date": calc.due_date_calc(sop["service_date"], 30, "COURT_DAYS", court),
        "status": "PENDING",
        "parent_deadline_id": None,
        "satisfied_by_filing_id": None,
    })
    db.deadlines[dl["id"]] = dl
    sop["response_due_deadline_id"] = dl["id"]

    db.touch(sop)
    # Hop 3: case posture recompute + version bump.
    domain.bump_case(case)
    return success(domain._clean(sop), status=200)


@bp.post("/service-of-process/<sop_id>/fail")
def fail_sop(sop_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    sop = domain.get_or_404(db.service_of_process, sop_id)
    if sop["status"] != "ATTEMPTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Service is not ATTEMPTED")
    party = db.parties[sop["served_party_id"]]
    party["service_status"] = "SERVICE_FAILED"
    db.touch(party)
    sop["status"] = "FAILED"
    db.touch(sop)
    return success(domain._clean(sop), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
