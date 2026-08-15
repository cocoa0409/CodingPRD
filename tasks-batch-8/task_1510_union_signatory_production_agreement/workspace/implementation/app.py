"""Union Signatory Production Agreement API — Flask entry point.

All endpoints from the scaffold endpoint table, with the validation pipeline
ordered per PRD section 2.10:
  auth -> role -> ProducerRep ownership -> body validation -> existence ->
  OCC -> production-state -> posture (frozen before restricted) -> entity
  from-states -> signatory precondition -> business rules.
"""

import os

from flask import Flask

import db
import helpers as h
import services as svc
from errors import (
    ApiError, err_validation, err_not_found, err_stale_version,
    err_application_state, err_production_state, err_posture_frozen,
    err_posture_restricted, err_bond_state, err_assignment_state,
    err_worklog_state, err_grievance_state, err_report_state, err_audit_state,
    err_fm_state, err_company_not_signatory, err_min_staff_unmet,
    err_filing_window_expired, err_cross_production_reference,
    err_log_already_reported, err_duplicate_active_assignment,
    err_duplicate_work_log, err_duplicate_report_period, err_fm_overlap,
    err_segregation_of_duties, err_review_rounds_exhausted, err_empty_report,
    err_invalid_worklog_times, err_tier_cap_exceeded,
    err_bond_amount_insufficient, err_overpayment, err_refund_exceeds_paid,
)
from helpers import (
    authenticate, require_role, check_ownership, get_json_body,
    reject_unknown_fields, req_string, opt_string, req_enum, req_int, opt_int,
    req_date, opt_date, parse_datetime_iso, new_entity, bump, clock_stamp,
    clock_date, parse_pagination, paginate,
    get_company, get_application, get_production, get_bond, get_assignment,
    get_worklog, get_grievance, get_report, get_audit, get_fm_event,
    bond_of_production,
)
from response import success_object, success_list, error_response

app = Flask(__name__)

BASE = "/union-compliance"
READ_ROLES = h.ALL_ROLES

AGREEMENT_SCOPES = {"THEATRICAL", "TELEVISION", "NEW_MEDIA"}
AGREEMENT_TIERS = set(svc.TIER_ORDER)
DEPARTMENTS = {"CAMERA", "GRIP_ELECTRIC", "SOUND"}
CLASSIFICATIONS = {
    "DIRECTOR_OF_PHOTOGRAPHY", "CAMERA_OPERATOR", "GAFFER",
    "KEY_GRIP", "BOOM_OPERATOR", "SOUND_MIXER",
}
GRIEVANCE_CATEGORIES = {"WORK_RULE", "PAY", "CLASSIFICATION", "SAFETY", "OTHER"}
FM_EVENT_TYPES = {"STRIKE", "NATURAL_DISASTER", "OTHER"}
APPLICATION_DECISIONS = {"APPROVE", "DENY"}
SETTLEMENT_RESPONSES = {"ACCEPT", "REJECT"}
REVIEW_DECISIONS = {"ACCEPT", "REJECT"}
ASSIGNMENT_TARGETS = {"ACTIVE", "WRAPPED", "TERMINATED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_response(exc.error_id, exc.message, exc.http_status)
    return body, status


@app.errorhandler(404)
def handle_404(exc):
    body, status = error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)
    return body, status


@app.errorhandler(405)
def handle_405(exc):
    body, status = error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)
    return body, status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unexpected error")
    body, status = error_response("ERR_VALIDATION", "Internal error", 500)
    return body, status


def list_response(items):
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


def production_company_id(production):
    return production["producer_company_id"]


def assignment_company_id(assignment):
    return production_company_id(db.productions[assignment["production_id"]])


def worklog_company_id(log):
    return assignment_company_id(db.crew_assignments[log["crew_assignment_id"]])


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    reject_unknown_fields(body, {"to_iso8601"})
    dt = parse_datetime_iso(body.get("to_iso8601"), "to_iso8601")
    with db.lock:
        db.set_clock(dt)
    return success_object({})


# ---------------------------------------------------------------------------
# ProducerCompany
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/producer-companies")
def create_company():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"legal_name", "fein"})
    legal_name = req_string(body, "legal_name")
    fein = req_string(body, "fein")
    with db.lock:
        ent = new_entity()
        ent.update({
            "legal_name": legal_name,
            "fein": fein,
            "status": "PENDING",
            "signatory_since": None,
        })
        db.companies[ent["id"]] = ent
        return success_object(ent, 201)


@app.get(f"{BASE}/producer-companies/<cid>")
def read_company(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        company = get_company(cid)
        check_ownership(role, user_id, company["id"])
        return success_object(company)


@app.get(f"{BASE}/producer-companies/<cid>/signatory-applications")
def list_company_applications(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        company = get_company(cid)
        check_ownership(role, user_id, company["id"])
        items = sorted_by_created(
            a for a in db.applications.values() if a["producer_company_id"] == cid
        )
        return list_response(items)


@app.get(f"{BASE}/producer-companies/<cid>/productions")
def list_company_productions(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        company = get_company(cid)
        check_ownership(role, user_id, company["id"])
        items = sorted_by_created(
            p for p in db.productions.values() if p["producer_company_id"] == cid
        )
        return list_response(items)


# ---------------------------------------------------------------------------
# SignatoryApplication
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/signatory-applications")
def create_application():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"producer_company_id", "requested_agreement_scope",
               "estimated_slate_budget_cents"})
    company_id = req_string(body, "producer_company_id")
    scope = req_enum(body, "requested_agreement_scope", AGREEMENT_SCOPES)
    budget = req_int(body, "estimated_slate_budget_cents", min_v=0)
    with db.lock:
        company = get_company(company_id)
        check_ownership(role, user_id, company["id"])
        ent = new_entity()
        ent.update({
            "producer_company_id": company_id,
            "requested_agreement_scope": scope,
            "estimated_slate_budget_cents": budget,
            "status": "DRAFT",
            "review_rounds": 0,
            "denial_reason": None,
        })
        db.applications[ent["id"]] = ent
        return success_object(ent, 201)


def _load_application_for_action(aid, user_id, role, allowed_roles):
    require_role(role, allowed_roles)
    application = get_application(aid)
    company = db.companies[application["producer_company_id"]]
    check_ownership(role, user_id, company["id"])
    return application


@app.post(f"{BASE}/signatory-applications/<aid>/submit")
def submit_application(aid):
    user_id, role = authenticate()
    with db.lock:
        application = _load_application_for_action(aid, user_id, role, ["ProducerRep"])
        if application["status"] != "DRAFT":
            raise err_application_state()
        application["status"] = "UNDER_REVIEW"
        bump(application)
        return success_object(application)


@app.post(f"{BASE}/signatory-applications/<aid>/request-info")
def request_info(aid):
    user_id, role = authenticate()
    with db.lock:
        application = _load_application_for_action(aid, user_id, role, ["UnionRep"])
        body = get_json_body()
        reject_unknown_fields(body, {"info_request_note"})
        opt_string(body, "info_request_note")
        if application["status"] != "UNDER_REVIEW":
            raise err_application_state()
        if application["review_rounds"] >= svc.MAX_REVIEW_ROUNDS:
            raise err_review_rounds_exhausted()
        application["review_rounds"] += 1
        application["status"] = "INFO_REQUESTED"
        bump(application)
        return success_object(application)


@app.post(f"{BASE}/signatory-applications/<aid>/provide-info")
def provide_info(aid):
    user_id, role = authenticate()
    with db.lock:
        application = _load_application_for_action(aid, user_id, role, ["ProducerRep"])
        body = get_json_body()
        reject_unknown_fields(body, {"info_response"})
        opt_string(body, "info_response")
        if application["status"] != "INFO_REQUESTED":
            raise err_application_state()
        application["status"] = "UNDER_REVIEW"
        bump(application)
        return success_object(application)


@app.post(f"{BASE}/signatory-applications/<aid>/decide")
def decide_application(aid):
    user_id, role = authenticate()
    with db.lock:
        application = _load_application_for_action(aid, user_id, role, ["UnionRep"])
        body = get_json_body()
        reject_unknown_fields(body, {"decision", "denial_reason"})
        decision = req_enum(body, "decision", APPLICATION_DECISIONS)
        if decision == "DENY":
            denial_reason = req_string(body, "denial_reason")
        else:
            denial_reason = opt_string(body, "denial_reason")
        if application["status"] != "UNDER_REVIEW":
            raise err_application_state()
        if decision == "APPROVE":
            application["status"] = "APPROVED"
            bump(application)
            company = db.companies[application["producer_company_id"]]
            if company["status"] == "PENDING":
                company["status"] = "SIGNATORY"
                company["signatory_since"] = clock_stamp()
                bump(company)
        else:
            application["denial_reason"] = denial_reason
            application["status"] = "DENIED"
            bump(application)
        return success_object(application)


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/productions")
def create_production():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"producer_company_id", "title", "agreement_tier", "budget_cents"})
    company_id = req_string(body, "producer_company_id")
    title = req_string(body, "title")
    tier = req_enum(body, "agreement_tier", AGREEMENT_TIERS)
    budget = req_int(body, "budget_cents", min_v=1)
    with db.lock:
        company = get_company(company_id)
        check_ownership(role, user_id, company["id"])
        # Cross-entity state check (priority 18).
        if company["status"] != "SIGNATORY":
            raise err_company_not_signatory()
        # Business: tier coverage (priority 31; boundary inclusive).
        if not svc.tier_covers(tier, budget):
            raise err_tier_cap_exceeded()

        production = new_entity()
        production.update({
            "producer_company_id": company_id,
            "title": title,
            "agreement_tier": tier,
            "budget_cents": budget,
            "status": "REGISTERED",
            "pre_suspension_status": None,
            "compliance_posture": "CLEAR",
        })
        db.productions[production["id"]] = production

        # Side effect: exactly one Bond auto-created (PENDING).
        bond = new_entity()
        bond.update({
            "production_id": production["id"],
            "amount_required_cents": svc.BOND_REQUIRED_BY_TIER[tier],
            "amount_held_cents": 0,
            "total_posted_cents": 0,
            "total_released_cents": 0,
            "total_forfeited_cents": 0,
            "status": "PENDING",
        })
        db.bonds[bond["id"]] = bond
        return success_object(production, 201)


@app.get(f"{BASE}/productions/<pid>")
def read_production(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        production = get_production(pid)
        check_ownership(role, user_id, production_company_id(production))
        return success_object(production)


@app.post(f"{BASE}/productions/<pid>/budget-revisions")
def budget_revision(pid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"new_budget_cents", "expected_production_version"})
    new_budget = req_int(body, "new_budget_cents", min_v=1)
    expected_version = req_int(body, "expected_production_version")
    with db.lock:
        production = get_production(pid)
        check_ownership(role, user_id, production_company_id(production))
        # OCC (priority 6).
        if expected_version != production["version"]:
            raise err_stale_version()
        # Production-state gate (priority 7).
        if production["status"] not in (
                "REGISTERED", "STAFFING", "IN_PRODUCTION", "SUSPENDED", "WRAPPED"):
            raise err_production_state()
        production["budget_cents"] = new_budget
        # Tier re-evaluation: never downgrades; upgrade picks smallest covering tier.
        if not svc.tier_covers(production["agreement_tier"], new_budget):
            production["agreement_tier"] = svc.smallest_covering_tier(new_budget)
            svc.apply_tier_upgrade_cascade(production)
        bump(production)
        return success_object(production)


@app.post(f"{BASE}/productions/<pid>/start-production")
def start_production(pid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        production = get_production(pid)
        check_ownership(role, user_id, production_company_id(production))
        if production["status"] != "STAFFING":
            raise err_production_state()
        # Posture: frozen fires before restricted.
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        if production["compliance_posture"] != "CLEAR":
            raise err_posture_restricted()
        # Minimum staffing (inclusive boundary).
        minimums = svc.MIN_CREW_BY_TIER_DEPT[production["agreement_tier"]]
        for dept, minimum in minimums.items():
            count = sum(
                1 for a in db.crew_assignments.values()
                if a["production_id"] == pid
                and a["department"] == dept
                and a["status"] in ("HIRED", "ACTIVE")
            )
            if count < minimum:
                raise err_min_staff_unmet()
        production["status"] = "IN_PRODUCTION"
        bump(production)
        return success_object(production)


@app.post(f"{BASE}/productions/<pid>/wrap-production")
def wrap_production(pid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        production = get_production(pid)
        check_ownership(role, user_id, production_company_id(production))
        if production["status"] != "IN_PRODUCTION":
            raise err_production_state()
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        for a in db.crew_assignments.values():
            if (a["production_id"] == pid
                    and a["status"] not in ("WRAPPED", "TERMINATED")):
                raise err_production_state(
                    "Every crew assignment must be WRAPPED or TERMINATED")
        production["status"] = "WRAPPED"
        bump(production)
        return success_object(production)


@app.post(f"{BASE}/productions/<pid>/close")
def close_production(pid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        production = get_production(pid)
        check_ownership(role, user_id, production_company_id(production))
        if production["status"] != "WRAPPED":
            raise err_production_state()
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        for r in db.contribution_reports.values():
            if r["production_id"] == pid and r["status"] != "ACCEPTED":
                raise err_production_state(
                    "Every contribution report must be ACCEPTED")
        for g in db.grievances.values():
            if g["production_id"] == pid and g["status"] != "CLOSED":
                raise err_production_state("Every grievance must be CLOSED")
        for a in db.audits.values():
            if a["production_id"] == pid and a["status"] != "CLOSED":
                raise err_production_state("Every audit must be CLOSED")
        bond = bond_of_production(pid)
        if bond is None or bond["status"] not in ("POSTED", "RELEASED"):
            raise err_production_state("Bond must be POSTED or RELEASED")
        production["status"] = "CLOSED"
        bump(production)
        return success_object(production)


def _list_child_of_production(pid, store, user_id, role):
    production = get_production(pid)
    check_ownership(role, user_id, production_company_id(production))
    items = sorted_by_created(
        e for e in store.values() if e["production_id"] == pid)
    return list_response(items)


@app.get(f"{BASE}/productions/<pid>/bonds")
def list_production_bonds(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.bonds, user_id, role)


@app.get(f"{BASE}/productions/<pid>/crew-assignments")
def list_production_crew(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.crew_assignments, user_id, role)


@app.get(f"{BASE}/productions/<pid>/grievances")
def list_production_grievances(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.grievances, user_id, role)


@app.get(f"{BASE}/productions/<pid>/contribution-reports")
def list_production_reports(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.contribution_reports, user_id, role)


@app.get(f"{BASE}/productions/<pid>/audits")
def list_production_audits(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.audits, user_id, role)


@app.get(f"{BASE}/productions/<pid>/force-majeure-events")
def list_production_fm_events(pid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        return _list_child_of_production(pid, db.force_majeure_events, user_id, role)


# ---------------------------------------------------------------------------
# Bond
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/bonds/<bid>/post")
def post_bond(bid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    with db.lock:
        bond = get_bond(bid)
        production = db.productions[bond["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if bond["status"] not in ("PENDING", "FORFEITED"):
            raise err_bond_state()
        if amount < bond["amount_required_cents"]:
            raise err_bond_amount_insufficient()
        was_pending = bond["status"] == "PENDING"
        bond["total_posted_cents"] += amount
        svc.bond_recompute_held(bond)
        bond["status"] = "POSTED"
        bump(bond)
        if was_pending and production["status"] == "REGISTERED":
            production["status"] = "STAFFING"
            bump(production)
        if not was_pending:
            # Re-post after forfeiture: company reinstatement check.
            company = db.companies[production["producer_company_id"]]
            svc.company_reinstatement_check(company)
        svc.recompute_posture(production)
        return success_object(bond)


@app.post(f"{BASE}/bonds/<bid>/top-up")
def top_up_bond(bid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    with db.lock:
        bond = get_bond(bid)
        production = db.productions[bond["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if bond["status"] != "UNDERFUNDED":
            raise err_bond_state()
        svc.bond_recompute_held(bond)
        if amount < bond["amount_required_cents"] - bond["amount_held_cents"]:
            raise err_bond_amount_insufficient()
        bond["total_posted_cents"] += amount
        svc.bond_recompute_held(bond)
        bond["status"] = "POSTED"
        bump(bond)
        svc.recompute_posture(production)
        return success_object(bond)


@app.post(f"{BASE}/bonds/<bid>/release")
def release_bond(bid):
    user_id, role = authenticate()
    require_role(role, ["FundTrustee"])
    body = get_json_body()
    reject_unknown_fields(body, set())
    with db.lock:
        bond = get_bond(bid)
        production = db.productions[bond["production_id"]]
        if bond["status"] != "POSTED" or production["status"] != "CLOSED":
            raise err_bond_state()
        bond["total_released_cents"] += bond["amount_held_cents"]
        svc.bond_recompute_held(bond)  # amount_held_cents := 0
        bond["status"] = "RELEASED"
        bump(bond)
        return success_object(bond)


# ---------------------------------------------------------------------------
# CrewAssignment
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/crew-assignments")
def create_assignment():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"production_id", "crew_member_ref", "department",
               "classification", "daily_rate_cents"})
    production_id = req_string(body, "production_id")
    crew_member_ref = req_string(body, "crew_member_ref")
    department = req_enum(body, "department", DEPARTMENTS)
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    daily_rate = req_int(body, "daily_rate_cents", min_v=1)
    with db.lock:
        production = get_production(production_id)
        check_ownership(role, user_id, production_company_id(production))
        if production["status"] not in ("STAFFING", "IN_PRODUCTION"):
            raise err_production_state()
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        if production["compliance_posture"] != "CLEAR":
            raise err_posture_restricted()
        for a in db.crew_assignments.values():
            if (a["production_id"] == production_id
                    and a["crew_member_ref"] == crew_member_ref
                    and a["status"] in ("HIRED", "ACTIVE")):
                raise err_duplicate_active_assignment()
        ent = new_entity()
        ent.update({
            "production_id": production_id,
            "crew_member_ref": crew_member_ref,
            "department": department,
            "classification": classification,
            "daily_rate_cents": daily_rate,
            "status": "HIRED",
        })
        db.crew_assignments[ent["id"]] = ent
        return success_object(ent, 201)


@app.get(f"{BASE}/crew-assignments/<aid>")
def read_assignment(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        assignment = get_assignment(aid)
        check_ownership(role, user_id, assignment_company_id(assignment))
        return success_object(assignment)


@app.get(f"{BASE}/crew-assignments/<aid>/work-day-logs")
def list_assignment_worklogs(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        assignment = get_assignment(aid)
        check_ownership(role, user_id, assignment_company_id(assignment))
        items = sorted_by_created(
            l for l in db.work_day_logs.values() if l["crew_assignment_id"] == aid)
        return list_response(items)


@app.get(f"{BASE}/crew-assignments/<aid>/grievances")
def list_assignment_grievances(aid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    with db.lock:
        assignment = get_assignment(aid)
        check_ownership(role, user_id, assignment_company_id(assignment))
        items = sorted_by_created(
            g for g in db.grievances.values() if g.get("crew_assignment_id") == aid)
        return list_response(items)


@app.post(f"{BASE}/crew-assignments/<aid>/transition")
def transition_assignment(aid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"to_state"})
    to_state = req_enum(body, "to_state", ASSIGNMENT_TARGETS)
    with db.lock:
        assignment = get_assignment(aid)
        production = db.productions[assignment["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        # Production-state gate (priority 7).
        if to_state == "ACTIVE":
            if production["status"] != "IN_PRODUCTION":
                raise err_production_state()
        elif to_state == "WRAPPED":
            if production["status"] != "IN_PRODUCTION":
                raise err_production_state()
        else:  # TERMINATED
            if production["status"] == "CLOSED":
                raise err_production_state()
        # Posture gate (priority 8): transitions require not FROZEN.
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        # Assignment from-state (priority 12).
        if to_state == "ACTIVE":
            if assignment["status"] != "HIRED":
                raise err_assignment_state()
        else:
            if assignment["status"] not in ("HIRED", "ACTIVE"):
                raise err_assignment_state()
        assignment["status"] = to_state
        bump(assignment)
        return success_object(assignment)


# ---------------------------------------------------------------------------
# WorkDayLog
# ---------------------------------------------------------------------------

def validate_meal_breaks(raw):
    if not isinstance(raw, list):
        raise err_validation("meal_breaks must be an array")
    breaks = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err_validation("meal_breaks entries must be objects")
        for key in entry:
            if key not in ("start_minutes", "end_minutes"):
                raise err_validation(f"Unknown meal break field: {key}")
        start = entry.get("start_minutes")
        end = entry.get("end_minutes")
        for name, v in (("start_minutes", start), ("end_minutes", end)):
            if not isinstance(v, int) or isinstance(v, bool):
                raise err_validation(f"meal_breaks.{name} must be an integer")
        breaks.append({"start_minutes": start, "end_minutes": end})
    return breaks


@app.post(f"{BASE}/work-day-logs")
def create_worklog():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"crew_assignment_id", "work_date", "call_time_minutes",
               "wrap_time_minutes", "meal_breaks"})
    assignment_id = req_string(body, "crew_assignment_id")
    work_date = req_date(body, "work_date")
    call = req_int(body, "call_time_minutes")
    wrap = req_int(body, "wrap_time_minutes")
    if "meal_breaks" not in body:
        raise err_validation("Missing required field: meal_breaks")
    breaks = validate_meal_breaks(body["meal_breaks"])
    with db.lock:
        assignment = get_assignment(assignment_id)
        production = db.productions[assignment["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        # Production-state gate (priority 7).
        if production["status"] != "IN_PRODUCTION":
            raise err_production_state()
        # Posture gate (priority 8).
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        # Assignment-state gate (priority 12).
        if assignment["status"] != "ACTIVE":
            raise err_assignment_state()
        # Duplicate day-point occupancy (priority 24).
        for l in db.work_day_logs.values():
            if (l["crew_assignment_id"] == assignment_id
                    and l["work_date"] == work_date.isoformat()
                    and l["status"] != "VOIDED"):
                raise err_duplicate_work_log()
        # Time sanity (priority 30).
        if not (0 <= call < 1440) or not (0 <= wrap < 1440) or wrap <= call:
            raise err_invalid_worklog_times()
        for b in breaks:
            if not (b["start_minutes"] < b["end_minutes"]):
                raise err_invalid_worklog_times()
            if b["start_minutes"] < call or b["end_minutes"] > wrap:
                raise err_invalid_worklog_times()
        ent = new_entity()
        ent.update({
            "crew_assignment_id": assignment_id,
            "work_date": work_date.isoformat(),
            "call_time_minutes": call,
            "wrap_time_minutes": wrap,
            "meal_breaks": breaks,
            "status": "OPEN",
        })
        svc.compute_log_penalties(ent)
        db.work_day_logs[ent["id"]] = ent
        return success_object(ent, 201)


@app.post(f"{BASE}/work-day-logs/<lid>/submit")
def submit_worklog(lid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        log = get_worklog(lid)
        assignment = db.crew_assignments[log["crew_assignment_id"]]
        production = db.productions[assignment["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        if log["status"] != "OPEN":
            raise err_worklog_state()
        log["status"] = "SUBMITTED"
        svc.compute_log_penalties(log)
        bump(log)
        return success_object(log)


@app.post(f"{BASE}/work-day-logs/<lid>/void")
def void_worklog(lid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        log = get_worklog(lid)
        assignment = db.crew_assignments[log["crew_assignment_id"]]
        production = db.productions[assignment["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        if log["status"] not in ("OPEN", "SUBMITTED"):
            raise err_worklog_state()
        log["status"] = "VOIDED"
        bump(log)
        return success_object(log)


# ---------------------------------------------------------------------------
# Grievance
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/grievances")
def file_grievance():
    user_id, role = authenticate()
    require_role(role, ["UnionRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"production_id", "crew_assignment_id", "category",
               "incident_date", "description"})
    production_id = req_string(body, "production_id")
    has_assignment = ("crew_assignment_id" in body
                      and body["crew_assignment_id"] is not None)
    assignment_id = None
    if has_assignment:
        assignment_id = body["crew_assignment_id"]
        if not isinstance(assignment_id, str):
            raise err_validation("crew_assignment_id must be a string")
    category = req_enum(body, "category", GRIEVANCE_CATEGORIES)
    incident_date = req_date(body, "incident_date")
    description = req_string(body, "description")
    with db.lock:
        production = get_production(production_id)
        assignment = None
        if assignment_id is not None:
            assignment = get_assignment(assignment_id)
        # Filing window (priority 20).
        deadline = svc.compute_filing_deadline(production_id, incident_date)
        if clock_date() > deadline:
            raise err_filing_window_expired()
        # Cross-production reference (priority 21).
        if assignment is not None and assignment["production_id"] != production_id:
            raise err_cross_production_reference()
        ent = new_entity()
        ent.update({
            "production_id": production_id,
            "crew_assignment_id": assignment_id,
            "category": category,
            "incident_date": incident_date.isoformat(),
            "description": description,
            "filed_by_user_id": user_id,
            "intake_user_id": None,
            "proposal_amount_cents": None,
            "proposal_status": "NONE",
            "settlement_agreed_cents": 0,
            "settlement_paid_cents": 0,
            "status": "FILED",
        })
        db.grievances[ent["id"]] = ent
        svc.recompute_posture(production)
        return success_object(ent, 201)


def _load_grievance_for_role(gid, role, allowed_roles):
    require_role(role, allowed_roles)
    grievance = get_grievance(gid)
    production = db.productions[grievance["production_id"]]
    return grievance, production


@app.post(f"{BASE}/grievances/<gid>/accept-intake")
def accept_intake(gid):
    user_id, role = authenticate()
    with db.lock:
        grievance, production = _load_grievance_for_role(gid, role, ["UnionRep"])
        if grievance["status"] != "FILED":
            raise err_grievance_state()
        grievance["intake_user_id"] = user_id
        grievance["status"] = "INVESTIGATING"
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/propose-settlement")
def propose_settlement(gid):
    user_id, role = authenticate()
    require_role(role, ["UnionRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"proposal_amount_cents", "expected_grievance_version"})
    amount = req_int(body, "proposal_amount_cents", min_v=0)
    expected_version = req_int(body, "expected_grievance_version")
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        # OCC (priority 6).
        if expected_version != grievance["version"]:
            raise err_stale_version()
        # State gate (priority 14).
        if grievance["status"] != "INVESTIGATING":
            raise err_grievance_state()
        # Segregation of duties (priority 27).
        if user_id == grievance["intake_user_id"]:
            raise err_segregation_of_duties()
        if grievance["proposal_status"] == "OPEN":
            grievance["proposal_status"] = "SUPERSEDED"
        grievance["proposal_amount_cents"] = amount
        grievance["proposal_status"] = "OPEN"
        grievance["status"] = "PROPOSED_SETTLEMENT"
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/respond-settlement")
def respond_settlement(gid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"decision"})
    decision = req_enum(body, "decision", SETTLEMENT_RESPONSES)
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if (grievance["status"] != "PROPOSED_SETTLEMENT"
                or grievance["proposal_status"] != "OPEN"):
            raise err_grievance_state()
        if decision == "ACCEPT":
            grievance["proposal_status"] = "ACCEPTED"
            grievance["settlement_agreed_cents"] = grievance["proposal_amount_cents"]
            if grievance["settlement_agreed_cents"] == 0:
                grievance["status"] = "CLOSED"
                svc.recompute_posture(production)
            else:
                grievance["status"] = "RESOLVED"
        else:
            grievance["proposal_status"] = "REJECTED"
            grievance["status"] = "INVESTIGATING"
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/escalate")
def escalate_grievance(gid):
    user_id, role = authenticate()
    require_role(role, ["UnionRep", "ProducerRep"])
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if grievance["status"] not in ("INVESTIGATING", "PROPOSED_SETTLEMENT"):
            raise err_grievance_state()
        if grievance["proposal_status"] == "OPEN":
            grievance["proposal_status"] = "SUPERSEDED"
        grievance["status"] = "ESCALATED"
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/decide")
def decide_grievance(gid):
    user_id, role = authenticate()
    require_role(role, ["Arbitrator"])
    body = get_json_body()
    reject_unknown_fields(body, {"award_cents", "decision_notes"})
    award = req_int(body, "award_cents", min_v=0)
    opt_string(body, "decision_notes")
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        if grievance["status"] != "ESCALATED":
            raise err_grievance_state()
        grievance["settlement_agreed_cents"] = award
        if award == 0:
            grievance["status"] = "CLOSED"
            svc.recompute_posture(production)
        else:
            grievance["status"] = "DECIDED"
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/payments")
def pay_grievance(gid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if grievance["status"] not in ("RESOLVED", "DECIDED"):
            raise err_grievance_state()
        if (amount <= 0
                or grievance["settlement_paid_cents"] + amount
                > grievance["settlement_agreed_cents"]):
            raise err_overpayment()
        grievance["settlement_paid_cents"] += amount
        if grievance["settlement_paid_cents"] == grievance["settlement_agreed_cents"]:
            grievance["status"] = "CLOSED"
            svc.recompute_posture(production)
        bump(grievance)
        return success_object(grievance)


@app.post(f"{BASE}/grievances/<gid>/refunds")
def refund_grievance(gid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    with db.lock:
        grievance = get_grievance(gid)
        production = db.productions[grievance["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if grievance["status"] not in ("RESOLVED", "DECIDED"):
            raise err_grievance_state()
        if amount <= 0 or amount > grievance["settlement_paid_cents"]:
            raise err_refund_exceeds_paid()
        grievance["settlement_paid_cents"] -= amount
        bump(grievance)
        return success_object(grievance)


# ---------------------------------------------------------------------------
# ContributionReport
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/contribution-reports")
def create_report():
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"production_id", "period_index", "work_day_log_ids"})
    production_id = req_string(body, "production_id")
    period_index = req_int(body, "period_index", min_v=1)
    if "work_day_log_ids" not in body:
        raise err_validation("Missing required field: work_day_log_ids")
    raw_ids = body["work_day_log_ids"]
    if not isinstance(raw_ids, list):
        raise err_validation("work_day_log_ids must be an array")
    for v in raw_ids:
        if not isinstance(v, str):
            raise err_validation("work_day_log_ids elements must be strings")
    with db.lock:
        production = get_production(production_id)
        check_ownership(role, user_id, production_company_id(production))
        # Existence of every referenced log (priority 5).
        logs = [get_worklog(lid) for lid in raw_ids]
        # Production-state gate (priority 7).
        if production["status"] not in ("IN_PRODUCTION", "WRAPPED"):
            raise err_production_state()
        # Posture gate (priority 8).
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        # VOIDED log in the set (priority 13).
        for log in logs:
            if log["status"] == "VOIDED":
                raise err_worklog_state("A VOIDED log cannot be listed on a report")
        # Cross-production reference (priority 21).
        for log in logs:
            assignment = db.crew_assignments[log["crew_assignment_id"]]
            if assignment["production_id"] != production_id:
                raise err_cross_production_reference()
        # Already reported (priority 22).
        listed = set(raw_ids)
        for r in db.contribution_reports.values():
            if (r["production_id"] == production_id and r["status"] == "ACCEPTED"
                    and listed.intersection(r["work_day_log_ids"])):
                raise err_log_already_reported()
        # Duplicate live period (priority 25).
        for r in db.contribution_reports.values():
            if (r["production_id"] == production_id
                    and r["period_index"] == period_index
                    and r["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED")):
                raise err_duplicate_report_period()
        # Non-empty inclusion set (priority 29).
        if not raw_ids:
            raise err_empty_report()

        # Provisional variant: OPEN and SUBMITTED listed logs, tier at creation.
        provisional_logs = [l for l in logs if l["status"] in ("OPEN", "SUBMITTED")]
        gross, due = svc.compute_dues(
            production, provisional_logs, production["agreement_tier"])

        ent = new_entity()
        ent.update({
            "production_id": production_id,
            "period_index": period_index,
            "work_day_log_ids": list(raw_ids),
            "provisional_gross_wages_cents": gross,
            "provisional_contributions_due_cents": due,
            "final_gross_wages_cents": None,
            "final_contributions_due_cents": None,
            "status": "DRAFT",
            "rejection_reason": None,
        })
        db.contribution_reports[ent["id"]] = ent
        return success_object(ent, 201)


@app.post(f"{BASE}/contribution-reports/<rid>/submit")
def submit_report(rid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    with db.lock:
        report = get_report(rid)
        production = db.productions[report["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if production["compliance_posture"] == "FROZEN":
            raise err_posture_frozen()
        if report["status"] != "DRAFT":
            raise err_report_state()
        # Final variant: only SUBMITTED listed logs, tier at submit time.
        logs = []
        for lid in report["work_day_log_ids"]:
            log = db.work_day_logs.get(lid)
            if log is not None and log["status"] == "SUBMITTED":
                logs.append(log)
        gross, due = svc.compute_dues(
            production, logs, production["agreement_tier"])
        report["final_gross_wages_cents"] = gross
        report["final_contributions_due_cents"] = due
        report["status"] = "SUBMITTED"
        bump(report)
        return success_object(report)


@app.post(f"{BASE}/contribution-reports/<rid>/review")
def review_report(rid):
    user_id, role = authenticate()
    require_role(role, ["FundTrustee"])
    body = get_json_body()
    reject_unknown_fields(body, {"decision", "rejection_reason"})
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    if decision == "REJECT":
        rejection_reason = req_string(body, "rejection_reason")
    else:
        rejection_reason = opt_string(body, "rejection_reason")
    with db.lock:
        report = get_report(rid)
        if report["status"] != "SUBMITTED":
            raise err_report_state()
        if decision == "ACCEPT":
            report["status"] = "ACCEPTED"
        else:
            report["rejection_reason"] = rejection_reason
            report["status"] = "REJECTED"
        bump(report)
        return success_object(report)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@app.post(f"{BASE}/audits")
def open_audit():
    user_id, role = authenticate()
    require_role(role, ["FundTrustee"])
    body = get_json_body()
    reject_unknown_fields(body, {"production_id", "scope_period_indices"})
    production_id = req_string(body, "production_id")
    if "scope_period_indices" not in body:
        raise err_validation("Missing required field: scope_period_indices")
    raw_scope = body["scope_period_indices"]
    if not isinstance(raw_scope, list) or not raw_scope:
        raise err_validation("scope_period_indices must be a non-empty array")
    for v in raw_scope:
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise err_validation("scope_period_indices elements must be integers >= 1")
    with db.lock:
        production = get_production(production_id)
        ent = new_entity()
        ent.update({
            "production_id": production_id,
            "scope_period_indices": list(raw_scope),
            "opened_by_user_id": user_id,
            "closed_by_user_id": None,
            "assessment_cents": None,
            "alt_assessment_cents": None,
            "assessment_paid_cents": 0,
            "status": "OPEN",
        })
        db.audits[ent["id"]] = ent
        return success_object(ent, 201)


@app.post(f"{BASE}/audits/<aid>/issue-findings")
def issue_findings(aid):
    user_id, role = authenticate()
    require_role(role, ["FundTrustee"])
    with db.lock:
        audit = get_audit(aid)
        production = db.productions[audit["production_id"]]
        if audit["status"] != "OPEN":
            raise err_audit_state()
        assessment, alt_assessment = svc.compute_assessment(
            production, audit["scope_period_indices"])
        audit["assessment_cents"] = assessment
        audit["alt_assessment_cents"] = alt_assessment
        audit["status"] = "FINDINGS_ISSUED"
        bump(audit)
        svc.recompute_posture(production)
        return success_object(audit)


@app.post(f"{BASE}/audits/<aid>/payments")
def pay_audit(aid):
    user_id, role = authenticate()
    require_role(role, ["ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    with db.lock:
        audit = get_audit(aid)
        production = db.productions[audit["production_id"]]
        check_ownership(role, user_id, production_company_id(production))
        if audit["status"] != "FINDINGS_ISSUED":
            raise err_audit_state()
        assessment = audit["assessment_cents"] or 0
        if amount <= 0 or audit["assessment_paid_cents"] + amount > assessment:
            raise err_overpayment()
        audit["assessment_paid_cents"] += amount
        bump(audit)
        svc.recompute_posture(production)
        return success_object(audit)


@app.post(f"{BASE}/audits/<aid>/close")
def close_audit(aid):
    user_id, role = authenticate()
    require_role(role, ["FundTrustee"])
    with db.lock:
        audit = get_audit(aid)
        production = db.productions[audit["production_id"]]
        if audit["status"] not in ("OPEN", "FINDINGS_ISSUED"):
            raise err_audit_state()
        # Segregation of duties (priority 27).
        if user_id == audit["opened_by_user_id"]:
            raise err_segregation_of_duties()
        audit["closed_by_user_id"] = user_id
        was_findings = audit["status"] == "FINDINGS_ISSUED"
        audit["status"] = "CLOSED"
        bump(audit)
        if was_findings:
            assessment = audit["assessment_cents"] or 0
            if audit["assessment_paid_cents"] < assessment:
                # Forfeit cascade: bond {POSTED, UNDERFUNDED} -> FORFEITED,
                # company SIGNATORY -> SUSPENDED, posture recomputed.
                bond = bond_of_production(production["id"])
                if bond is not None and bond["status"] in ("POSTED", "UNDERFUNDED"):
                    svc.forfeit_bond(bond)
        svc.recompute_posture(production)
        return success_object(audit)


# ---------------------------------------------------------------------------
# ForceMajeureEvent
# ---------------------------------------------------------------------------

def _fm_effective_end_for_overlap(event):
    if event["end_date"] is not None:
        return svc._to_date(event["end_date"])
    if event["lifted_date"] is not None:
        return svc._to_date(event["lifted_date"])
    return None  # open-ended (infinity)


@app.post(f"{BASE}/force-majeure-events")
def declare_fm_event():
    user_id, role = authenticate()
    require_role(role, ["UnionRep", "ProducerRep"])
    body = get_json_body()
    reject_unknown_fields(
        body, {"production_id", "event_type", "start_date", "end_date"})
    production_id = req_string(body, "production_id")
    event_type = req_enum(body, "event_type", FM_EVENT_TYPES)
    start_date = req_date(body, "start_date")
    end_date = opt_date(body, "end_date")
    with db.lock:
        production = get_production(production_id)
        check_ownership(role, user_id, production_company_id(production))
        if production["status"] not in ("STAFFING", "IN_PRODUCTION"):
            raise err_production_state()
        # Interval overlap (half-open; adjacency allowed).
        new_start = start_date
        new_end = end_date  # None = +infinity
        for event in db.force_majeure_events.values():
            if event["production_id"] != production_id:
                continue
            ex_start = svc._to_date(event["start_date"])
            ex_end = _fm_effective_end_for_overlap(event)
            # overlap iff new_start < ex_end (or ex_end is None)
            #             and ex_start < new_end (or new_end is None)
            if ((ex_end is None or new_start < ex_end)
                    and (new_end is None or ex_start < new_end)):
                raise err_fm_overlap()
        ent = new_entity()
        ent.update({
            "production_id": production_id,
            "event_type": event_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date is not None else None,
            "lifted_date": None,
            "status": "ACTIVE",
        })
        db.force_majeure_events[ent["id"]] = ent
        # Suspend the production.
        production["pre_suspension_status"] = production["status"]
        production["status"] = "SUSPENDED"
        bump(production)
        svc.recompute_posture(production)
        return success_object(ent, 201)


@app.post(f"{BASE}/force-majeure-events/<eid>/lift")
def lift_fm_event(eid):
    user_id, role = authenticate()
    require_role(role, ["UnionRep"])
    with db.lock:
        event = get_fm_event(eid)
        production = db.productions[event["production_id"]]
        if event["status"] != "ACTIVE":
            raise err_fm_state()
        event["lifted_date"] = clock_date().isoformat()
        event["status"] = "LIFTED"
        bump(event)
        # Restore the production when no other event remains ACTIVE.
        any_active = any(
            e["production_id"] == production["id"] and e["status"] == "ACTIVE"
            for e in db.force_majeure_events.values()
        )
        if not any_active and production["status"] == "SUSPENDED":
            production["status"] = production["pre_suspension_status"]
            production["pre_suspension_status"] = None
            bump(production)
        svc.recompute_posture(production)
        return success_object(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
