"""ScholarshipProgram lifecycle (PRD §3.2)."""

from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services.validate import (require_fields, req_string, req_int, req_enum,
                               opt_int, opt_bool, opt_list, req_iso_datetime)

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = {"MERIT", "NEED", "HYBRID"}
MATCH_POLICIES = {"STRICT", "HOLISTIC"}
STACKING_SCOPES = {"ANNUAL", "PER_TERM"}
COMPONENT_TYPES = {"ESSAY", "RECOMMENDATION", "TRANSCRIPT"}
NONTERMINAL_APP_STATUSES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "SELECTED", "WAITLISTED"}
ALL_READ_ROLES = ("ScholarshipCoordinator", "Student", "CommitteeReviewer",
                  "FinancialAidOfficer", "Donor")


def get_program_or_404(pid):
    p = db.get("programs", pid)
    if p is None:
        raise_err("ERR_NOT_FOUND", "ScholarshipProgram not found")
    return p


def _check_component_subset(components):
    for c in components:
        if c not in COMPONENT_TYPES:
            raise_err("ERR_VALIDATION", "required_components must be a subset of ESSAY/RECOMMENDATION/TRANSCRIPT")


@bp.route("/api/scholarship-programs", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_program():
    data = body()
    require_fields(data, ["name", "donor_id", "fund_id", "program_type", "match_policy",
                          "stacking_scope", "award_amount_cents", "max_recipients",
                          "min_gpa_hundredths", "application_open_at", "application_close_at"])
    name = req_string(data, "name")
    # Body-referenced existence, left to right: donor_id then fund_id.
    donor_id = data["donor_id"]
    if not isinstance(donor_id, str) or db.get("donors", donor_id) is None:
        raise_err("ERR_NOT_FOUND", "Donor not found")
    fund_id = data["fund_id"]
    if not isinstance(fund_id, str) or db.get("award_funds", fund_id) is None:
        raise_err("ERR_NOT_FOUND", "AwardFund not found")

    program_type = req_enum(data, "program_type", PROGRAM_TYPES)
    match_policy = req_enum(data, "match_policy", MATCH_POLICIES)
    stacking_scope = req_enum(data, "stacking_scope", STACKING_SCOPES)
    award_amount = req_int(data, "award_amount_cents", 1)
    max_recipients = req_int(data, "max_recipients", 1)
    min_gpa = req_int(data, "min_gpa_hundredths", 0, 500)
    open_at = req_iso_datetime(data, "application_open_at")
    close_at = req_iso_datetime(data, "application_close_at")

    eligible_majors = opt_list(data, "eligible_majors", default=[])
    required_tags = opt_list(data, "required_tags", default=[])
    required_components = opt_list(data, "required_components", default=[])
    _check_component_subset(required_components)

    residency = data.get("required_residency_state")
    if residency is not None and (not isinstance(residency, str) or len(residency) != 2):
        raise_err("ERR_VALIDATION", "required_residency_state must be a two-letter code or null")
    max_income = opt_int(data, "max_household_income_cents", 0, default=None)

    renewable = opt_bool(data, "renewable", False)
    renewal_gpa = opt_int(data, "renewal_min_gpa_hundredths", 0, 500, default=None)
    renewal_credits = opt_int(data, "renewal_min_credits", 0, default=None)
    max_renewals = opt_int(data, "max_renewals", 0, default=0)

    if clock.parse_iso(close_at) <= clock.parse_iso(open_at):
        raise_err("ERR_INVALID_DATE_RANGE", "application_close_at must be later than application_open_at")

    rec = db.create_record("programs", {
        "name": name,
        "donor_id": donor_id,
        "fund_id": fund_id,
        "program_type": program_type,
        "match_policy": match_policy,
        "stacking_scope": stacking_scope,
        "award_amount_cents": award_amount,
        "max_recipients": max_recipients,
        "min_gpa_hundredths": min_gpa,
        "eligible_majors": eligible_majors,
        "required_residency_state": residency,
        "max_household_income_cents": max_income,
        "required_tags": required_tags,
        "required_components": required_components,
        "application_open_at": open_at,
        "application_close_at": close_at,
        "renewable": renewable,
        "renewal_min_gpa_hundredths": renewal_gpa,
        "renewal_min_credits": renewal_credits,
        "max_renewals": max_renewals,
        "status": "DRAFT",
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/scholarship-programs", methods=["GET"])
@require_roles(*ALL_READ_ROLES)
def list_programs():
    items = db.all_records("programs")
    from flask import request
    donor_id = request.args.get("donor_id")
    fund_id = request.args.get("fund_id")
    status = request.args.get("status")
    if donor_id is not None:
        items = [p for p in items if p["donor_id"] == donor_id]
    if fund_id is not None:
        items = [p for p in items if p["fund_id"] == fund_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(p) for p in page], response_type="array", pagination=meta)


@bp.route("/api/scholarship-programs/<pid>", methods=["GET"])
@require_roles(*ALL_READ_ROLES)
def get_program(pid):
    return success(db.serialize(get_program_or_404(pid)))


_EDITABLE = ("name", "min_gpa_hundredths", "max_household_income_cents",
             "required_residency_state", "eligible_majors", "required_tags",
             "required_components", "award_amount_cents", "max_recipients",
             "renewal_min_gpa_hundredths", "renewal_min_credits", "max_renewals")


@bp.route("/api/scholarship-programs/<pid>", methods=["PUT"])
@require_roles("ScholarshipCoordinator")
def put_program(pid):
    program = get_program_or_404(pid)
    data = body()
    # OCC (priority 5) precedes remaining shape checks and the state gate.
    if "expected_program_version" not in data:
        raise_err("ERR_VALIDATION", "expected_program_version is required")
    expected = data["expected_program_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err("ERR_VALIDATION", "expected_program_version must be an integer")
    if expected != program["version"]:
        raise_err("ERR_STALE_VERSION", "Program version has advanced")

    updates = {}
    for f in _EDITABLE:
        if f not in data:
            continue
        v = data[f]
        if f == "name":
            if not isinstance(v, str) or not v:
                raise_err("ERR_VALIDATION", "name must be a non-empty string")
        elif f in ("min_gpa_hundredths", "renewal_min_gpa_hundredths"):
            if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 500):
                raise_err("ERR_VALIDATION", "%s must be an integer 0..500" % f)
        elif f in ("max_household_income_cents",):
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                raise_err("ERR_VALIDATION", "%s must be a non-negative integer or null" % f)
        elif f in ("award_amount_cents", "max_recipients", "renewal_min_credits", "max_renewals"):
            lo = 1 if f in ("award_amount_cents", "max_recipients") else 0
            if not isinstance(v, int) or isinstance(v, bool) or v < lo:
                raise_err("ERR_VALIDATION", "%s must be an integer >= %d" % (f, lo))
        elif f == "required_residency_state":
            if v is not None and (not isinstance(v, str) or len(v) != 2):
                raise_err("ERR_VALIDATION", "required_residency_state must be a two-letter code or null")
        elif f in ("eligible_majors", "required_tags", "required_components"):
            if not isinstance(v, list):
                raise_err("ERR_VALIDATION", "%s must be an array" % f)
            if f == "required_components":
                _check_component_subset(v)
        updates[f] = v

    if program["status"] not in ("DRAFT", "CLOSED"):
        raise_err("ERR_INVALID_STATE", "Program criteria editable only while DRAFT or CLOSED")
    db.mutate(program, **updates)
    return success(db.serialize(program))


@bp.route("/api/scholarship-programs/<pid>/publish", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def publish_program(pid):
    program = get_program_or_404(pid)
    if program["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT program can be published")
    if clock.now() < clock.parse_iso(program["application_open_at"]):
        raise_err("ERR_WINDOW_NOT_OPEN", "Application window has not opened")
    db.mutate(program, status="OPEN")
    return success(db.serialize(program))


@bp.route("/api/scholarship-programs/<pid>/close", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def close_program(pid):
    program = get_program_or_404(pid)
    if program["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Only an OPEN program can be closed")
    # Manual close simply flips the status (PRD §3.2).
    db.mutate(program, status="CLOSED")
    return success(db.serialize(program))


@bp.route("/api/scholarship-programs/<pid>/extend", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def extend_program(pid):
    program = get_program_or_404(pid)
    data = body()
    new_close = req_iso_datetime(data, "new_close_at")
    if program["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Only a CLOSED program can be extended")
    if clock.parse_iso(new_close) <= clock.parse_iso(program["application_close_at"]):
        raise_err("ERR_INVALID_DATE_RANGE", "new_close_at must be later than the current application_close_at")
    db.mutate(program, application_close_at=new_close, status="OPEN")
    return success(db.serialize(program))


@bp.route("/api/scholarship-programs/<pid>/archive", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def archive_program(pid):
    program = get_program_or_404(pid)
    if program["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Only a CLOSED program can be archived")
    for app in db.all_records("applications"):
        if app["program_id"] == pid and app["status"] in NONTERMINAL_APP_STATUSES:
            raise_err("ERR_INVALID_STATE", "Program has non-terminal applications")
    db.mutate(program, status="ARCHIVED")
    return success(db.serialize(program))
