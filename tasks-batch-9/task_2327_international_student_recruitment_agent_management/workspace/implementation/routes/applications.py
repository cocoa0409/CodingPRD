"""The student file: disclosure, submission, milestones, withdrawal, documents."""

import uuid

from flask import Blueprint, request

import errors
import serializers
from db import db, base_record, touch, today, now_iso, creation_order
from errors import fail
from middleware import check_scope
from response import obj
from routes.common import auth, listing, need
from services import calc, domain
from validation import (body, fmt_date, opt_str, opt_str_array, parse_date, query_enum,
                        query_str, req_bool, req_country, req_date, req_enum, req_id,
                        req_int, req_str)

bp = Blueprint("applications", __name__)

DISCLOSURE_ACTIONS = ("ISSUE", "ACKNOWLEDGE")
DECISIONS = ("ADMIT", "DENY")
MILESTONE_PREDECESSOR = {
    "DEPOSIT_PAID": "ADMITTED",
    "ENROLLED": "DEPOSIT_PAID",
    "CENSUS_CONFIRMED": "ENROLLED",
    "PERSISTED": "CENSUS_CONFIRMED",
}
MILESTONE_DATE_FIELD = {
    "DEPOSIT_PAID": "deposit_paid_on",
    "ENROLLED": "enrolled_on",
    "CENSUS_CONFIRMED": "census_confirmed_on",
    "PERSISTED": "persisted_on",
}
MILESTONE_FLOOR_FIELD = {
    "DEPOSIT_PAID": "submitted_on",
    "ENROLLED": "deposit_paid_on",
    "CENSUS_CONFIRMED": "enrolled_on",
    "PERSISTED": "census_confirmed_on",
}
WITHDRAWABLE = ("SUBMITTED", "ADMITTED", "DEPOSIT_PAID", "ENROLLED", "CENSUS_CONFIRMED")
DISCLOSURE_CONTRACT_STATES = ("ACTIVE", "PENDING_COMPLIANCE_REVIEW", "PENDING_AGENCY_SIGNATURE")


def _peek(application_id, role, user_id):
    """Resolve without raising so group 3 can run before group 4."""
    app = db.applications.get(application_id)
    if app is not None:
        check_scope(role, user_id, app["agency_id"])
    return app


def _resolved(app):
    if app is None:
        fail(errors.ERR_APPLICATION_NOT_FOUND, "Application not found")
    return app


def _disclosure_contract(agency_id):
    contracts = calc.agency_contracts(agency_id)
    for state in DISCLOSURE_CONTRACT_STATES:
        candidates = [c for c in contracts if c["status"] == state]
        if candidates:
            return creation_order(candidates)[0]
    return None


# --- creation and reads -----------------------------------------------------

@bp.route("/recruitment/applications", methods=["POST"])
def create_application():
    user_id, role = auth("AgencyOwner")
    raw = request.get_json(silent=True)
    if isinstance(raw, dict) and isinstance(raw.get("agency_id"), str):
        check_scope(role, user_id, raw["agency_id"])

    data = body()
    agency_id = req_id(data, "agency_id")
    program_id = req_id(data, "program_id")
    student_ref = req_str(data, "student_ref", min_len=1)
    student_residence_country = req_country(data, "student_residence_country")
    student_us_person = req_bool(data, "student_us_person")

    agency = need(db.agencies, agency_id, errors.ERR_AGENCY_NOT_FOUND)
    program = need(db.programs, program_id, errors.ERR_PROGRAM_NOT_FOUND)

    if agency["compliance_posture"] in ("SUSPENDED", "DEBARRED"):
        fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
             "Compliance posture %s blocks new student files" % agency["compliance_posture"])
    for existing in db.applications.values():
        if existing["student_ref"] == student_ref:
            fail(errors.ERR_DUPLICATE_RESOURCE,
                 "student_ref '%s' already exists" % student_ref)

    record = base_record()
    record.update({
        "agency_id": agency["id"],
        "custody_agency_id": agency["id"],
        "program_id": program["id"],
        "pinned_contract_id": None,
        "pinned_schedule_id": None,
        "student_ref": student_ref,
        "student_residence_country": student_residence_country,
        "student_us_person": student_us_person,
        "recruitment_origin": calc.classify_origin(student_residence_country,
                                                   student_us_person),
        "status": "DRAFT",
        "disclosure_state": "NOT_ISSUED",
        "disclosure_template_version": None,
        "disclosure_ack_token": None,
        "disclosure_acknowledged_at": None,
        "submitted_on": None,
        "tier_snapshot_at_submission": None,
        "projected_commission_cents": 0,
        "net_commission_cents": 0,
        "integrity_hold": False,
        "deposit_paid_on": None,
        "enrolled_on": None,
        "census_confirmed_on": None,
        "persisted_on": None,
        "withdrawn_on": None,
        "withdrawal_reason": None,
    })
    db.applications[record["id"]] = record
    return obj(serializers.application(record), 201)


@bp.route("/recruitment/applications/<application_id>", methods=["GET"])
def read_application(application_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "Registrar", "AgencyOwner")
    app = _resolved(_peek(application_id, role, user_id))
    return obj(serializers.application(app))


@bp.route("/recruitment/applications", methods=["GET"])
def list_applications():
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "Registrar", "AgencyOwner")
    filters = {
        "agency_id": query_str("agency_id"),
        "custody_agency_id": query_str("custody_agency_id"),
        "program_id": query_str("program_id"),
        "pinned_contract_id": query_str("pinned_contract_id"),
        "pinned_schedule_id": query_str("pinned_schedule_id"),
    }
    status = query_enum("status", calc.APPLICATION_STATUSES)
    disclosure_state = query_enum("disclosure_state", calc.DISCLOSURE_STATES)
    recruitment_origin = query_enum("recruitment_origin", calc.RECRUITMENT_ORIGINS)

    records = list(db.applications.values())
    if role == "AgencyOwner":
        records = [r for r in records if r["agency_id"] == user_id]
    for key, value in filters.items():
        if value is not None:
            records = [r for r in records if r.get(key) == value]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if disclosure_state is not None:
        records = [r for r in records if r["disclosure_state"] == disclosure_state]
    if recruitment_origin is not None:
        records = [r for r in records if r["recruitment_origin"] == recruitment_origin]
    return listing(records, serializers.application)


# --- disclosure -------------------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/disclosure", methods=["POST"])
def application_disclosure(application_id):
    user_id, role = auth("RecruitmentOfficer", "AgencyOwner", "Applicant")
    raw = request.get_json(silent=True)
    raw_action = raw.get("action") if isinstance(raw, dict) else None
    if raw_action == "ISSUE" and role not in ("RecruitmentOfficer", "AgencyOwner"):
        fail(errors.ERR_UNAUTHORIZED, "Role %s may not issue a disclosure" % role)
    if raw_action == "ACKNOWLEDGE" and role != "Applicant":
        fail(errors.ERR_UNAUTHORIZED, "Role %s may not acknowledge a disclosure" % role)

    app = _peek(application_id, role, user_id)
    data = body()
    action = req_enum(data, "action", DISCLOSURE_ACTIONS)
    ack_token = opt_str(data, "ack_token")
    app = _resolved(app)
    agency_id = app["agency_id"]

    if action == "ISSUE":
        contract = _disclosure_contract(agency_id)
        if contract is None:
            fail(errors.ERR_INVALID_CONTRACT_STATE,
                 "The agency holds no contract that can back a disclosure")
    if app["status"] != "DRAFT":
        fail(errors.ERR_INVALID_APPLICATION_STATE,
             "A disclosure action requires the application to be in DRAFT")

    if action == "ISSUE":
        if app["disclosure_state"] not in ("NOT_ISSUED", "INVALIDATED"):
            fail(errors.ERR_DISCLOSURE_NOT_ACKNOWLEDGED,
                 "ISSUE is not defined from disclosure_state %s" % app["disclosure_state"])
        app["disclosure_state"] = "ISSUED"
        app["disclosure_template_version"] = contract["disclosure_template_version"]
        app["disclosure_ack_token"] = uuid.uuid4().hex
        app["disclosure_acknowledged_at"] = None
        touch(app)
    else:
        if app["disclosure_state"] != "ISSUED":
            fail(errors.ERR_DISCLOSURE_NOT_ACKNOWLEDGED,
                 "ACKNOWLEDGE is not defined from disclosure_state %s"
                 % app["disclosure_state"])
        if not ack_token or ack_token != app["disclosure_ack_token"]:
            fail(errors.ERR_DISCLOSURE_TOKEN_INVALID,
                 "The acknowledgement token does not match")
        app["disclosure_state"] = "ACKNOWLEDGED"
        app["disclosure_acknowledged_at"] = now_iso()
        touch(app)
    return obj(serializers.application(app))


# --- submission -------------------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/submit", methods=["POST"])
def application_submit(application_id):
    user_id, role = auth("AgencyOwner")
    app = _resolved(_peek(application_id, role, user_id))
    agency = db.agencies.get(app["agency_id"])
    program = db.programs.get(app["program_id"])
    current = today()

    active = [c for c in calc.agency_contracts(app["agency_id"]) if c["status"] == "ACTIVE"]
    if len(active) != 1:
        fail(errors.ERR_INVALID_CONTRACT_STATE,
             "The agency must hold exactly one ACTIVE contract to submit")
    contract = active[0]

    if app["status"] != "DRAFT":
        fail(errors.ERR_INVALID_APPLICATION_STATE, "Only a DRAFT application may be submitted")
    if app["disclosure_state"] != "ACKNOWLEDGED":
        fail(errors.ERR_DISCLOSURE_NOT_ACKNOWLEDGED,
             "The agent-relationship disclosure has not been acknowledged")
    if app["disclosure_template_version"] != contract["disclosure_template_version"]:
        fail(errors.ERR_DISCLOSURE_VERSION_STALE,
             "The pinned disclosure template version is stale")
    if agency is None or agency["vetting_state"] != "CLEARED":
        fail(errors.ERR_AGENCY_NOT_CLEARED, "The agency is not CLEARED")
    if agency["compliance_posture"] not in ("GOOD_STANDING", "WATCH"):
        fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
             "Compliance posture %s blocks submission" % agency["compliance_posture"])

    certs = calc.agency_certifications(app["agency_id"])
    for module in ("PROGRAM_ACCURACY", "PROHIBITED_CLAIMS"):
        live = [c for c in certs
                if c["module_code"] == module and c["status"] == "VALID"
                and current < parse_date(c["expires_on"])]
        if not live:
            fail(errors.ERR_TRAINING_LAPSED,
                 "A VALID %s certification is required" % module)

    passports = [d for d in calc.application_documents(application_id)
                 if d["doc_type"] == "PASSPORT" and d["verification_state"] == "VERIFIED"]
    if not passports:
        fail(errors.ERR_IDENTITY_DOCUMENT_UNVERIFIED,
             "A VERIFIED PASSPORT document is required")
    if app["integrity_hold"]:
        fail(errors.ERR_FRAUD_HOLD_ACTIVE, "The application carries an integrity hold")

    covered = False
    for assignment in calc.contract_assignments(contract["id"]):
        if assignment["status"] != "ACTIVE":
            continue
        if assignment["country_code"] != app["student_residence_country"]:
            continue
        if parse_date(assignment["start_date"]) <= current < parse_date(assignment["end_date"]):
            covered = True
            break
    if not covered:
        fail(errors.ERR_TERRITORY_NOT_COVERED,
             "The student's residence country is not covered by an active territory")

    schedule = None
    for candidate in calc.contract_schedules(contract["id"]):
        if parse_date(candidate["effective_from"]) <= current < parse_date(
                candidate["effective_to"]):
            schedule = candidate
            break
    if schedule is None:
        fail(errors.ERR_SCHEDULE_NOT_EFFECTIVE, "No rate card is effective today")

    submitted_on = current
    tier = calc.resolve_tier(app["agency_id"], submitted_on)
    app["status"] = "SUBMITTED"
    app["submitted_on"] = fmt_date(submitted_on)
    app["pinned_contract_id"] = contract["id"]
    app["pinned_schedule_id"] = schedule["id"]
    app["tier_snapshot_at_submission"] = tier
    app["projected_commission_cents"] = calc.provisional_projection(program, schedule, tier)
    touch(app)
    return obj(serializers.application(app))


# --- admission decision -----------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/decision", methods=["POST"])
def application_decision(application_id):
    auth("RecruitmentOfficer")
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    opt_str(data, "note")
    app = need(db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND)

    if app["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_APPLICATION_STATE,
             "A decision requires the application to be SUBMITTED")
    if decision == "ADMIT" and app["integrity_hold"]:
        fail(errors.ERR_FRAUD_HOLD_ACTIVE, "The application carries an integrity hold")

    app["status"] = "ADMITTED" if decision == "ADMIT" else "DENIED"
    touch(app)
    return obj(serializers.application(app))


# --- milestones -------------------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/milestones", methods=["POST"])
def application_milestone(application_id):
    auth("Registrar")
    data = body()
    milestone = req_enum(data, "milestone", calc.MILESTONES)
    event_date = req_date(data, "event_date")
    expected_version = req_int(data, "expected_application_version")
    app = need(db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND)

    if expected_version != app["version"]:
        fail(errors.ERR_STALE_APPLICATION_VERSION,
             "expected_application_version does not match the application version")

    if app["status"] != MILESTONE_PREDECESSOR[milestone]:
        fail(errors.ERR_MILESTONE_OUT_OF_ORDER,
             "%s is not the immediate successor of status %s" % (milestone, app["status"]))

    floor_value = app.get(MILESTONE_FLOOR_FIELD[milestone])
    floor_date = parse_date(floor_value) if floor_value else None
    current = today()
    if (floor_date is not None and event_date < floor_date) or event_date > current:
        fail(errors.ERR_MILESTONE_DATE_INVALID, "The milestone event_date is out of range")

    program = db.programs.get(app["program_id"])
    if milestone == "CENSUS_CONFIRMED" and program is not None:
        if event_date < parse_date(program["census_date"]):
            fail(errors.ERR_CENSUS_DATE_NOT_REACHED,
                 "The program census date has not been reached")
    if milestone == "PERSISTED" and program is not None:
        if event_date < parse_date(program["persistence_check_date"]):
            fail(errors.ERR_PERSISTENCE_DATE_NOT_REACHED,
                 "The program persistence check date has not been reached")

    app["status"] = milestone
    app[MILESTONE_DATE_FIELD[milestone]] = fmt_date(event_date)
    domain.create_accrual(app, milestone, event_date)
    app["net_commission_cents"] = calc.application_net_commission(app["id"])
    touch(app)

    agency = db.agencies.get(app["agency_id"])
    if agency is not None:
        domain.recompute_agency_ledger(agency)
    return obj(serializers.application(app))


# --- withdrawal -------------------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/withdraw", methods=["POST"])
def application_withdraw(application_id):
    auth("Registrar")
    data = body()
    withdrawal_date = req_date(data, "withdrawal_date")
    reason = req_str(data, "reason", min_len=1)
    app = need(db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND)

    if app["status"] not in WITHDRAWABLE:
        fail(errors.ERR_INVALID_APPLICATION_STATE,
             "Withdrawal is not defined from status %s" % app["status"])
    submitted_on = parse_date(app["submitted_on"]) if app.get("submitted_on") else None
    if (submitted_on is not None and withdrawal_date < submitted_on) or withdrawal_date > today():
        fail(errors.ERR_MILESTONE_DATE_INVALID, "The withdrawal_date is out of range")

    domain.clawback_ledger(app, withdrawal_date)
    app["status"] = "WITHDRAWN"
    app["withdrawn_on"] = fmt_date(withdrawal_date)
    app["withdrawal_reason"] = reason
    app["net_commission_cents"] = calc.application_net_commission(app["id"])
    touch(app)

    agency = db.agencies.get(app["agency_id"])
    if agency is not None:
        domain.recompute_agency_ledger(agency)
        domain.clawback_ratio_escalation(agency)
    return obj(serializers.application(app))


# --- commission projection --------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/commission-projection",
          methods=["GET"])
def application_projection(application_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "AgencyOwner")
    app = _resolved(_peek(application_id, role, user_id))
    entries = calc.application_entries(application_id)
    provisional = app["projected_commission_cents"]
    final_net = app["net_commission_cents"]
    return obj({
        "provisional_projection_cents": provisional,
        "final_net_cents": final_net,
        "variant_delta_cents": provisional - final_net,
        "tier_snapshot_at_submission": app["tier_snapshot_at_submission"],
        "pinned_schedule_id": app["pinned_schedule_id"],
        "accrued_entry_count": sum(1 for e in entries if e["kind"] == "ACCRUAL"),
        "clawback_entry_count": sum(1 for e in entries if e["kind"] == "CLAWBACK"),
    })


# --- documents --------------------------------------------------------------

@bp.route("/recruitment/applications/<application_id>/documents", methods=["POST"])
def upload_document(application_id):
    user_id, role = auth("AgencyOwner")
    app = _peek(application_id, role, user_id)
    data = body()
    doc_type = req_enum(data, "doc_type", calc.DOC_TYPES)
    content_hash = req_str(data, "content_hash", min_len=1, max_len=128)
    issuer_name = req_str(data, "issuer_name", min_len=1)
    declared_signals = opt_str_array(data, "declared_signals", calc.DECLARED_SIGNALS,
                                     default=[])
    app = _resolved(app)

    agency = db.agencies.get(app["agency_id"])
    if agency is not None and agency["compliance_posture"] in ("SUSPENDED", "DEBARRED"):
        fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
             "Compliance posture %s blocks document upload" % agency["compliance_posture"])

    signals, index = calc.fraud_signals_for(app["agency_id"], app["id"], content_hash,
                                            declared_signals)
    flagged = index >= calc.FLAG_THRESHOLD
    record = base_record()
    record.update({
        "application_id": app["id"],
        "doc_type": doc_type,
        "content_hash": content_hash,
        "issuer_name": issuer_name,
        "declared_signals": list(declared_signals),
        "fraud_signals": signals,
        "fraud_index": index,
        "verification_state": "FLAGGED" if flagged else "PENDING",
        "verified_by_user_id": None,
    })
    db.documents[record["id"]] = record

    if flagged:
        domain.commit(app, {"integrity_hold": True})
        if agency is not None:
            domain.recompute_document_counts(agency)
    return obj(serializers.document(record), 201)


@bp.route("/recruitment/applications/<application_id>/documents", methods=["GET"])
def list_documents(application_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    app = _peek(application_id, role, user_id)
    doc_type = query_enum("doc_type", calc.DOC_TYPES)
    verification_state = query_enum("verification_state", calc.VERIFICATION_STATES)
    app = _resolved(app)
    records = calc.application_documents(application_id)
    if doc_type is not None:
        records = [r for r in records if r["doc_type"] == doc_type]
    if verification_state is not None:
        records = [r for r in records if r["verification_state"] == verification_state]
    return listing(records, serializers.document)
