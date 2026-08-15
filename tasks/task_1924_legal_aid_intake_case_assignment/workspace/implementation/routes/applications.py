"""IntakeApplication lifecycle (PRD sections 3.2, 3.4, 3.5) and conflict checks."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, new_id, now
from errors import (ERR_CONFLICT_CHECK_STALE, ERR_CONFLICT_UNRESOLVED,
                    ERR_DETERMINATION_MISMATCH, ERR_DUPLICATE_OPEN_CASE,
                    ERR_EXTENDED_REP_NOT_PERMITTED,
                    ERR_GRANT_BUDGET_EXHAUSTED, ERR_GRANT_CASE_TYPE_EXCLUDED,
                    ERR_GRANT_COUNTY_EXCLUDED, ERR_GRANT_INCOME_OVER_CAP,
                    ERR_GRANT_PERIOD_INACTIVE,
                    ERR_INVALID_APPLICATION_STATE, ERR_INVALID_REQUEST,
                    ERR_NO_EXTENDED_CAPACITY, ERR_NOT_FOUND,
                    ERR_SELF_SCREENING_APPROVAL, ERR_STALE_VERSION,
                    ERR_VENUE_UNDETERMINED, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services import calc, derived
from services.common import (create_unmet_record, delete_waitlist_entry_for,
                             get_or_404, list_response, stamp_new, touch)
from services.enums import CASE_TYPES, SERVICE_LEVELS
from services.serialize import application_json, conflict_check_json
from validators import (body, check_allowed, opt_str, req_enum, req_int,
                        req_str)

bp = Blueprint("applications", __name__)

CONFLICT_VALID_DAYS = 45


def _get_app(aid):
    return get_or_404(db.applications, aid)


def _require_state(app, states):
    if app["status"] not in states:
        fail(ERR_INVALID_APPLICATION_STATE,
             "Application is {} and cannot perform this transition".format(
                 app["status"]))


@bp.route("/intake-applications", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def create_application():
    b = body()
    check_allowed(b, ["client_id", "case_type", "opposing_party_name",
                      "incident_county", "incident_description"])
    client_id = req_str(b, "client_id")
    case_type = req_enum(b, "case_type", CASE_TYPES)
    opposing_party_name = req_str(b, "opposing_party_name")
    incident_county = req_str(b, "incident_county")
    incident_description = opt_str(b, "incident_description", "")
    # Body FK existence (priority 6).
    get_or_404(db.clients, client_id)
    rec = {
        "id": new_id(),
        "client_id": client_id,
        "case_type": case_type,
        "opposing_party_name": opposing_party_name,
        "incident_county": incident_county,
        "incident_description": incident_description,
        "status": "SUBMITTED",
        "venue": None,
        "gross_poverty_percentage": None,
        "countable_poverty_percentage": None,
        "priority_score": None,
        "eligibility_determination": None,
        "screened_by_staff_id": None,
        "screened_at": None,
        "promoted_from_waitlist": False,
    }
    stamp_new(rec)
    db.applications[rec["id"]] = rec
    return ok_object(application_json(rec), 201)


@bp.route("/intake-applications/<aid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_application(aid):
    return ok_object(application_json(_get_app(aid)))


@bp.route("/intake-applications", methods=["GET"])
@require_roles(ALL_ROLES)
def list_applications():
    records = list(db.applications.values())
    for param in ("client_id", "status", "case_type", "incident_county"):
        value = request.args.get(param)
        if value is not None:
            records = [a for a in records if a[param] == value]
    return list_response(records, application_json)


@bp.route("/intake-applications/<aid>/screen", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def screen_application(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, [])
    _require_state(app, ["SUBMITTED"])
    client = get_or_404(db.clients, app["client_id"])
    rule = derived.find_venue_rule(app["incident_county"], app["case_type"])
    if rule is None:
        fail(ERR_VENUE_UNDETERMINED,
             "No venue rule for ({}, {})".format(app["incident_county"],
                                                 app["case_type"]))
    gross_pct = calc.poverty_pct(client["annual_gross_income_cents"],
                                 client["household_size"])
    countable_pct = calc.poverty_pct(client["annual_countable_income_cents"],
                                     client["household_size"])
    passed = calc.standard_screen_pass(
        gross_pct, client["receives_means_tested_benefits"])
    app["venue"] = rule["venue"]
    app["gross_poverty_percentage"] = gross_pct
    app["countable_poverty_percentage"] = countable_pct
    app["priority_score"] = calc.priority_score(
        rule["priority_base_weight"], len(client["vulnerability_factors"]),
        app["case_type"])
    app["eligibility_determination"] = "ELIGIBLE" if passed else "INELIGIBLE"
    app["screened_by_staff_id"] = g.user_id
    app["screened_at"] = now()
    app["status"] = "SCREENED"
    touch(app)
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/request-documents", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def request_documents(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["request_note"])
    opt_str(b, "request_note")
    _require_state(app, ["SUBMITTED"])
    app["status"] = "DOCS_REQUESTED"
    touch(app)
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/submit-documents", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def submit_documents(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, [])
    _require_state(app, ["DOCS_REQUESTED"])
    app["status"] = "SUBMITTED"
    touch(app)
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/decide-eligibility", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def decide_eligibility(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["determination"])
    determination = req_enum(b, "determination", ["ELIGIBLE", "INELIGIBLE"])
    _require_state(app, ["SCREENED"])
    if determination != app["eligibility_determination"]:
        fail(ERR_DETERMINATION_MISMATCH,
             "Submitted determination {} contradicts computed {}".format(
                 determination, app["eligibility_determination"]))
    app["status"] = determination
    touch(app)
    if determination == "INELIGIBLE":
        create_unmet_record(app, "OVER_INCOME")
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/rescreen", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def rescreen_application(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["expected_application_version"])
    expected = req_int(b, "expected_application_version")
    _require_state(app, ["ELIGIBLE", "INELIGIBLE"])
    if expected != app["version"]:
        fail(ERR_STALE_VERSION,
             "expected_application_version {} does not match current "
             "version {}".format(expected, app["version"]))
    app["status"] = "SUBMITTED"
    touch(app)
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/enqueue-waitlist", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def enqueue_waitlist(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, [])
    _require_state(app, ["ELIGIBLE"])
    snapshot = app["priority_score"]
    entry = {
        "id": new_id(),
        "application_id": app["id"],
        "priority_score_snapshot": snapshot,
        "required_weight": (calc.EXTENDED_WEIGHT
                            if snapshot >= calc.EXTENDED_MIN_PRIORITY
                            else calc.ADVICE_WEIGHT),
    }
    from services.common import stamp_new_aux
    stamp_new_aux(entry)
    db.waitlist_entries[entry["id"]] = entry
    create_unmet_record(app, "NO_EXTENDED_CAPACITY")
    app["status"] = "WAITLISTED"
    touch(app)
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/withdraw", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def withdraw_application(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["withdrawal_reason"])
    opt_str(b, "withdrawal_reason")
    _require_state(app, ["SUBMITTED", "DOCS_REQUESTED", "SCREENED",
                         "ELIGIBLE", "INELIGIBLE", "WAITLISTED"])
    was_waitlisted = app["status"] == "WAITLISTED"
    was_ineligible = app["status"] == "INELIGIBLE"
    if was_waitlisted:
        delete_waitlist_entry_for(app["id"])
    app["status"] = "WITHDRAWN"
    touch(app)
    if not was_ineligible:
        create_unmet_record(app, "CLIENT_WITHDRAWN")
    return ok_object(application_json(app))


@bp.route("/intake-applications/<aid>/open-case", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def open_case(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["service_level", "grant_program_id"])
    service_level = req_enum(b, "service_level", SERVICE_LEVELS)
    grant_program_id = b.get("grant_program_id")
    if grant_program_id is not None and not isinstance(grant_program_id, str):
        fail(ERR_INVALID_REQUEST, "Field grant_program_id must be a string")
    # Body FK existence (priority 6).
    program = None
    if grant_program_id is not None:
        program = get_or_404(db.grant_programs, grant_program_id)
    # State legality (priority 7).
    _require_state(app, ["ELIGIBLE"])

    # ---- Pinned gauntlet (PRD 3.5) ----
    # 1. Self-screening segregation of duties.
    if g.user_id == app["screened_by_staff_id"]:
        fail(ERR_SELF_SCREENING_APPROVAL,
             "The attorney who screened this application may not open its case")
    # 2. Conflict resolution: latest check must exist and be CLEAR or WAIVED.
    latest = derived.latest_conflict_check(app["id"])
    if latest is None or latest["result"] not in ("CLEAR", "WAIVED"):
        fail(ERR_CONFLICT_UNRESOLVED,
             "Latest conflict check is missing or unresolved")
    # 3. Conflict recency: valid_until must not lie in the past.
    if latest["valid_until"] < now():
        fail(ERR_CONFLICT_CHECK_STALE, "Latest conflict clearance has expired")
    # 4. Duplicate open case for same client + case_type.
    for c in db.cases.values():
        other_app = db.applications.get(c["application_id"])
        if (other_app is not None
                and other_app["client_id"] == app["client_id"]
                and other_app["case_type"] == app["case_type"]
                and c["status"] in ("PENDING_ASSIGNMENT", "OPEN", "ON_HOLD")):
            fail(ERR_DUPLICATE_OPEN_CASE,
                 "Another open case exists for this client and case type")
    # 5. Service-level permission (stored priority_score, not recomputed).
    if service_level == "EXTENDED":
        rule = derived.find_venue_rule(app["incident_county"],
                                       app["case_type"])
        if (app["priority_score"] < calc.EXTENDED_MIN_PRIORITY
                or rule is None or not rule["extended_eligible"]):
            fail(ERR_EXTENDED_REP_NOT_PERMITTED,
                 "EXTENDED representation is not permitted for this matter")
        # 6. Extended-capacity pool, from pre-opening state.
        if not derived.any_active_attorney_with(calc.EXTENDED_WEIGHT):
            fail(ERR_NO_EXTENDED_CAPACITY,
                 "No ACTIVE attorney has at least 5 available units")
    # 7. Grant gates (only when a grant was named), in pinned order.
    weight = calc.case_weight(service_level)
    reservation = 0
    if program is not None:
        today = now().date()
        from validators import as_date
        if not (as_date(program["period_start"]) <= today
                <= as_date(program["period_end"])):
            fail(ERR_GRANT_PERIOD_INACTIVE,
                 "Logical clock is outside the grant period")
        if app["case_type"] not in program["allowed_case_types"]:
            fail(ERR_GRANT_CASE_TYPE_EXCLUDED,
                 "case_type is not covered by this grant")
        if app["incident_county"] not in program["allowed_counties"]:
            fail(ERR_GRANT_COUNTY_EXCLUDED,
                 "incident_county is not covered by this grant")
        if app["countable_poverty_percentage"] > program["income_cap_percentage"]:
            fail(ERR_GRANT_INCOME_OVER_CAP,
                 "countable_poverty_percentage exceeds the grant cap")
        reservation = calc.reservation_cents(program["per_case_rate_cents"],
                                             weight)
        available = (program["total_budget_cents"]
                     - derived.grant_reserved_cents(program["id"])
                     - derived.grant_spent_cents(program["id"]))
        if available < reservation:
            fail(ERR_GRANT_BUDGET_EXHAUSTED,
                 "Grant budget cannot cover this case's reservation")

    case = {
        "id": new_id(),
        "application_id": app["id"],
        "grant_program_id": grant_program_id,
        "assigned_attorney_id": None,
        "assigned_paralegal_id": None,
        "service_level": service_level,
        "venue": app["venue"],
        "placement": "INTERNAL",
        "status": "PENDING_ASSIGNMENT",
        "funding_status": ("GRANT_RESERVED" if program is not None
                           else "UNFUNDED"),
        "case_weight": weight,
        "reserved_cents": reservation,
        "outcome_code": None,
        "closure_reason": None,
        "advice_deadline": None,
        "opened_at": None,
        "closed_at": None,
    }
    stamp_new(case)
    db.cases[case["id"]] = case
    app["status"] = "OPENED"
    touch(app)
    if program is not None:
        touch(program)  # reserved_cents rose by the reservation (derived)
    from services.serialize import case_json
    return ok_object(case_json(case), 201)


# ---- Conflict checks (nested under applications) ----

@bp.route("/intake-applications/<aid>/conflict-checks", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def create_conflict_check(aid):
    app = _get_app(aid)
    b = body()
    check_allowed(b, ["result", "notes"])
    result = req_enum(b, "result", ["CLEAR", "POTENTIAL_CONFLICT"])
    notes = opt_str(b, "notes", "")
    checked_at = now()
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "result": result,
        "checked_by_staff_id": g.user_id,
        "checked_at": checked_at,
        "valid_until": checked_at + timedelta(days=CONFLICT_VALID_DAYS),
        "notes": notes,
        "waiver_reason": None,
        "resolved_by_staff_id": None,
        "resolved_at": None,
    }
    stamp_new(rec)
    db.conflict_checks[rec["id"]] = rec
    return ok_object(conflict_check_json(rec), 201)


@bp.route("/intake-applications/<aid>/conflict-checks", methods=["GET"])
@require_roles(["IntakeSpecialist", "SupervisingAttorney", "EthicsOfficer",
                "ProgramDirector"])
def list_conflict_checks(aid):
    _get_app(aid)
    records = [c for c in db.conflict_checks.values()
               if c["application_id"] == aid]
    return list_response(records, conflict_check_json)
