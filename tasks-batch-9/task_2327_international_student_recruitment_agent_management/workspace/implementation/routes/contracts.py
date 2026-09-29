"""Contract negotiation, territories, rate cards and termination (PRD 3.2, 3.3, 3.9)."""

from flask import Blueprint

import errors
import serializers
from db import db, base_record, touch, today, creation_order
from errors import fail
from middleware import check_scope
from response import arr, obj
from routes.common import auth, listing, need
from services import calc, domain
from validation import (COUNTRY_RE, body, fmt_date, opt_id, opt_int, opt_str, pagination,
                        parse_date, query_enum, query_req_date, query_req_str, query_str,
                        req_country, req_date, req_enum, req_id, req_int, req_str)

bp = Blueprint("contracts", __name__)

LIFECYCLE_SOURCE = {
    "SEND_FOR_SIGNATURE": "DRAFT",
    "AGENCY_SIGN": "PENDING_AGENCY_SIGNATURE",
    "REQUEST_AMENDMENT": "PENDING_COMPLIANCE_REVIEW",
    "COMPLIANCE_APPROVE": "PENDING_COMPLIANCE_REVIEW",
    "SUSPEND": "ACTIVE",
    "REINSTATE": "SUSPENDED",
}
LIFECYCLE_ACTIONS = tuple(LIFECYCLE_SOURCE.keys())


# --- drafting and reads -----------------------------------------------------

@bp.route("/recruitment/contracts", methods=["POST"])
def create_contract():
    user_id, _role = auth("RecruitmentOfficer")
    data = body()
    agency_id = req_id(data, "agency_id")
    contract_ref = req_str(data, "contract_ref", min_len=1)
    exclusivity_model = req_enum(data, "exclusivity_model", calc.EXCLUSIVITY_MODELS)
    term_start_date = req_date(data, "term_start_date")
    term_end_date = req_date(data, "term_end_date")
    annual_commission_cap_cents = req_int(data, "annual_commission_cap_cents", minimum=1)

    agency = need(db.agencies, agency_id, errors.ERR_AGENCY_NOT_FOUND)

    if not (term_end_date > term_start_date):
        fail(errors.ERR_TERM_WINDOW_INVALID, "term_end_date must be after term_start_date")
    for existing in db.contracts.values():
        if existing["contract_ref"] == contract_ref:
            fail(errors.ERR_DUPLICATE_RESOURCE,
                 "contract_ref '%s' already exists" % contract_ref)
    for existing in calc.agency_contracts(agency_id):
        if existing["status"] in calc.LIVE_CONTRACT_STATUSES:
            fail(errors.ERR_DUPLICATE_RESOURCE,
                 "The agency already holds a live contract")

    record = base_record()
    record.update({
        "agency_id": agency["id"],
        "contract_ref": contract_ref,
        "status": "DRAFT",
        "exclusivity_model": exclusivity_model,
        "term_start_date": fmt_date(term_start_date),
        "term_end_date": fmt_date(term_end_date),
        "annual_commission_cap_cents": annual_commission_cap_cents,
        "disclosure_template_version": 1,
        "amendment_round": 0,
        "created_by_user_id": user_id,
        "agency_signed_by_user_id": None,
        "compliance_approved_by_user_id": None,
        "terminated_on": None,
        "termination_reason_code": None,
        "suspension_reason": None,
    })
    db.contracts[record["id"]] = record
    return obj(serializers.contract(record), 201)


@bp.route("/recruitment/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "AgencyOwner")
    contract = db.contracts.get(contract_id)
    if contract is not None:
        check_scope(role, user_id, contract["agency_id"])
    else:
        fail(errors.ERR_CONTRACT_NOT_FOUND, "Contract not found")
    return obj(serializers.contract(contract))


@bp.route("/recruitment/contracts", methods=["GET"])
def list_contracts():
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "AgencyOwner")
    agency_id = query_str("agency_id")
    status = query_enum("status", calc.CONTRACT_STATUSES)
    records = list(db.contracts.values())
    if role == "AgencyOwner":
        records = [r for r in records if r["agency_id"] == user_id]
    if agency_id is not None:
        records = [r for r in records if r["agency_id"] == agency_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return listing(records, serializers.contract)


# --- lifecycle --------------------------------------------------------------

@bp.route("/recruitment/contracts/<contract_id>/lifecycle", methods=["POST"])
def contract_lifecycle(contract_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    contract = db.contracts.get(contract_id)
    if contract is not None:
        check_scope(role, user_id, contract["agency_id"])

    data = body()
    action = req_enum(data, "action", LIFECYCLE_ACTIONS)
    note = opt_str(data, "note")
    opt_int(data, "revised_annual_commission_cap_cents")

    if contract is None:
        fail(errors.ERR_CONTRACT_NOT_FOUND, "Contract not found")
    agency = db.agencies.get(contract["agency_id"])

    # group 8 - segregation of duties precedes state legality
    if action == "COMPLIANCE_APPROVE" and user_id == contract["created_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The drafter of a contract may not countersign it")

    # group 9 - state legality
    if contract["status"] != LIFECYCLE_SOURCE[action]:
        fail(errors.ERR_INVALID_CONTRACT_STATE,
             "Action %s is not defined from status %s" % (action, contract["status"]))
    if action == "REINSTATE" and today() > parse_date(contract["term_end_date"]):
        fail(errors.ERR_INVALID_CONTRACT_STATE,
             "The contract term has already ended")

    # groups 10 and 11 - business safety and referential gates
    if action == "SEND_FOR_SIGNATURE":
        if agency is None or agency["vetting_state"] not in ("SCREENING", "INFO_REQUESTED",
                                                            "CLEARED"):
            fail(errors.ERR_AGENCY_NOT_CLEARED,
                 "The agency's due diligence has not started or was rejected")
        if not calc.contract_schedules(contract_id):
            fail(errors.ERR_SCHEDULE_NOT_EFFECTIVE,
                 "The contract carries no rate card yet")
    elif action in ("COMPLIANCE_APPROVE", "REINSTATE"):
        if agency is None or agency["vetting_state"] != "CLEARED":
            fail(errors.ERR_AGENCY_NOT_CLEARED, "The agency is not CLEARED")
        if agency["compliance_posture"] not in ("GOOD_STANDING", "WATCH"):
            fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
                 "Compliance posture %s blocks this action" % agency["compliance_posture"])
    elif action == "REQUEST_AMENDMENT":
        if contract["amendment_round"] >= 3:
            fail(errors.ERR_AMENDMENT_LIMIT_REACHED,
                 "The contract has already been amended three times")

    # apply
    if action == "SEND_FOR_SIGNATURE":
        domain.commit(contract, {"status": "PENDING_AGENCY_SIGNATURE"})
    elif action == "AGENCY_SIGN":
        contract["status"] = "PENDING_COMPLIANCE_REVIEW"
        contract["agency_signed_by_user_id"] = user_id
        touch(contract)
    elif action == "COMPLIANCE_APPROVE":
        contract["status"] = "ACTIVE"
        contract["compliance_approved_by_user_id"] = user_id
        touch(contract)
    elif action == "REQUEST_AMENDMENT":
        contract["status"] = "DRAFT"
        contract["amendment_round"] += 1
        contract["disclosure_template_version"] += 1
        contract["agency_signed_by_user_id"] = None
        touch(contract)
        for app in creation_order(calc.agency_applications(contract["agency_id"])):
            if app["disclosure_state"] == "ISSUED":
                domain.invalidate_disclosure(app)
    elif action == "SUSPEND":
        domain.suspend_contract(contract, note if note else "SUSPENDED")
    elif action == "REINSTATE":
        contract["status"] = "ACTIVE"
        contract["suspension_reason"] = None
        touch(contract)
    return obj(serializers.contract(contract))


# --- termination ------------------------------------------------------------

@bp.route("/recruitment/contracts/<contract_id>/terminate", methods=["POST"])
def contract_terminate(contract_id):
    auth("ComplianceOfficer")
    data = body()
    reason_code = req_enum(data, "reason_code", calc.TERMINATION_REASONS)
    effective_date = req_date(data, "effective_date")
    req_str(data, "transition_note", min_len=1)
    successor_agency_id = opt_id(data, "successor_agency_id")

    contract = need(db.contracts, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    successor = None
    if successor_agency_id is not None:
        successor = need(db.agencies, successor_agency_id, errors.ERR_AGENCY_NOT_FOUND)

    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        fail(errors.ERR_INVALID_CONTRACT_STATE,
             "Termination is not defined from status %s" % contract["status"])

    if successor is not None:
        eligible = (successor["id"] != contract["agency_id"]
                    and successor["vetting_state"] == "CLEARED"
                    and successor["compliance_posture"] in ("GOOD_STANDING", "WATCH")
                    and any(c["status"] == "ACTIVE"
                            for c in calc.agency_contracts(successor["id"])))
        if not eligible:
            fail(errors.ERR_SUCCESSOR_NOT_ELIGIBLE,
                 "The nominated successor agency is not eligible")

    agency_id = contract["agency_id"]
    agency = db.agencies.get(agency_id)
    to_agency_id = successor["id"] if successor is not None else None

    contract["status"] = "TERMINATED"
    contract["terminated_on"] = fmt_date(effective_date)
    contract["termination_reason_code"] = reason_code
    touch(contract)

    # hop 1 - release the contract's active territories
    for assignment in creation_order(calc.contract_assignments(contract_id)):
        if assignment["status"] == "ACTIVE":
            domain.release_assignment(assignment)

    # hop 2 - transition the in-flight student files
    for app in creation_order(list(db.applications.values())):
        if app["custody_agency_id"] != agency_id:
            continue
        if app["status"] not in ("DRAFT", "SUBMITTED", "ADMITTED", "DEPOSIT_PAID"):
            continue
        from_agency_id = app["custody_agency_id"]
        domain.write_file_transition(app, from_agency_id, to_agency_id, contract, reason_code)
        domain.commit(app, {"custody_agency_id": to_agency_id,
                            "disclosure_state": "INVALIDATED",
                            "disclosure_ack_token": None})

    # hop 3 and 4 - forfeiture and ledger recompute
    domain.forfeit_for_termination(contract, reason_code)
    if agency is not None:
        domain.recompute_agency_ledger(agency)
        if reason_code == "FOR_CAUSE":
            domain.escalate_posture(agency, "DEBARRED", "TERMINATION_FOR_CAUSE")
    return obj(serializers.contract(contract))


# --- territory assignments --------------------------------------------------

@bp.route("/recruitment/contracts/<contract_id>/territory-assignments", methods=["POST"])
def create_assignment(contract_id):
    auth("RecruitmentOfficer")
    data = body()
    country_code = req_country(data, "country_code")
    exclusivity = req_enum(data, "exclusivity", calc.EXCLUSIVITIES)
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")

    contract = need(db.contracts, contract_id, errors.ERR_CONTRACT_NOT_FOUND)

    actives = calc.country_active_assignments(country_code)
    if exclusivity == "EXCLUSIVE":
        for other in actives:
            o_start = parse_date(other["start_date"])
            o_end = parse_date(other["end_date"])
            if calc.intervals_overlap(start_date, end_date, o_start, o_end):
                fail(errors.ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                     "An active assignment already occupies this interval")
            if other["exclusivity"] == "EXCLUSIVE" and calc.intervals_overlap(
                    start_date, end_date, o_start, calc.cooloff_end(other)):
                fail(errors.ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                     "An exclusive cool-off shadow reaches into this interval")
    else:
        for other in actives:
            if other["exclusivity"] != "EXCLUSIVE":
                continue
            o_start = parse_date(other["start_date"])
            if calc.intervals_overlap(start_date, end_date, o_start,
                                      calc.cooloff_end(other)):
                fail(errors.ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                     "An exclusive assignment or its cool-off covers this interval")
        non_exclusive = [a for a in actives if a["exclusivity"] == "NON_EXCLUSIVE"]
        points = set([start_date])
        for other in non_exclusive:
            o_start = parse_date(other["start_date"])
            if start_date < o_start < end_date:
                points.add(o_start)
        for point in sorted(points):
            concurrent = 1
            for other in non_exclusive:
                o_start = parse_date(other["start_date"])
                o_end = parse_date(other["end_date"])
                if o_start <= point < o_end:
                    concurrent += 1
            if concurrent > calc.MAX_CONCURRENT_NON_EXCLUSIVE:
                fail(errors.ERR_TERRITORY_CAPACITY_EXCEEDED,
                     "The country already carries the maximum concurrent non-exclusive"
                     " assignments")

    if not (end_date > start_date):
        fail(errors.ERR_TERM_WINDOW_INVALID, "end_date must be after start_date")
    if (start_date < parse_date(contract["term_start_date"])
            or end_date > parse_date(contract["term_end_date"])):
        fail(errors.ERR_TERM_WINDOW_INVALID,
             "The assignment window must lie inside the contract term")

    if exclusivity == "EXCLUSIVE" and contract["exclusivity_model"] != "EXCLUSIVE_ALLOWED":
        fail(errors.ERR_EXCLUSIVITY_NOT_PERMITTED,
             "This contract does not permit exclusive territories")

    record = base_record()
    record.update({
        "contract_id": contract["id"],
        "country_code": country_code,
        "exclusivity": exclusivity,
        "start_date": fmt_date(start_date),
        "end_date": fmt_date(end_date),
        "status": "ACTIVE",
        "released_on": None,
    })
    db.assignments[record["id"]] = record
    return obj(serializers.assignment(record), 201)


@bp.route("/recruitment/contracts/<contract_id>/territory-assignments", methods=["GET"])
def list_assignments(contract_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    contract = db.contracts.get(contract_id)
    if contract is not None:
        check_scope(role, user_id, contract["agency_id"])
    country_code = query_str("country_code")
    status = query_enum("status", calc.ASSIGNMENT_STATUSES)
    if contract is None:
        fail(errors.ERR_CONTRACT_NOT_FOUND, "Contract not found")
    records = calc.contract_assignments(contract_id)
    if country_code is not None:
        records = [r for r in records if r["country_code"] == country_code]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return listing(records, serializers.assignment)


@bp.route("/recruitment/contracts/<contract_id>/territory-assignments/<assignment_id>/release",
          methods=["POST"])
def release_assignment(contract_id, assignment_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    contract = need(db.contracts, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    assignment = db.assignments.get(assignment_id)
    if assignment is None or assignment["contract_id"] != contract["id"]:
        fail(errors.ERR_ASSIGNMENT_NOT_FOUND, "Territory assignment not found")
    if assignment["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_CONTRACT_STATE,
             "Only an ACTIVE territory assignment may be released")
    domain.release_assignment(assignment)
    return obj(serializers.assignment(assignment))


# --- commission schedules ---------------------------------------------------

@bp.route("/recruitment/contracts/<contract_id>/commission-schedules", methods=["POST"])
def create_schedule(contract_id):
    auth("RecruitmentOfficer")
    data = body()
    effective_from = req_date(data, "effective_from")
    effective_to = req_date(data, "effective_to")
    deposit_rate_bps = req_int(data, "deposit_rate_bps", minimum=0, maximum=2000)
    enrollment_rate_bps = req_int(data, "enrollment_rate_bps", minimum=0, maximum=2000)
    census_rate_bps = req_int(data, "census_rate_bps", minimum=0, maximum=2000)
    persistence_rate_bps = req_int(data, "persistence_rate_bps", minimum=0, maximum=2000)
    rate_cap_bps = req_int(data, "rate_cap_bps", minimum=0, maximum=2000)
    per_milestone_cap_cents = req_int(data, "per_milestone_cap_cents", minimum=1)
    clawback_window_days = req_int(data, "clawback_window_days", minimum=1)
    expected_contract_version = req_int(data, "expected_contract_version")

    contract = need(db.contracts, contract_id, errors.ERR_CONTRACT_NOT_FOUND)

    if expected_contract_version != contract["version"]:
        fail(errors.ERR_STALE_CONTRACT_VERSION,
             "expected_contract_version does not match the contract version")

    existing = calc.contract_schedules(contract_id)
    if not existing:
        if effective_from != parse_date(contract["term_start_date"]):
            fail(errors.ERR_SCHEDULE_INTERVAL_CONFLICT,
                 "The first rate card must start on the contract term start date")
    else:
        frontier = max(parse_date(s["effective_to"]) for s in existing)
        if effective_from < frontier:
            fail(errors.ERR_SCHEDULE_INTERVAL_CONFLICT,
                 "The rate card overlaps an existing card")
        if effective_from > frontier:
            fail(errors.ERR_SCHEDULE_GAP, "The rate card leaves an uncovered stretch")

    if not (effective_to > effective_from):
        fail(errors.ERR_TERM_WINDOW_INVALID, "effective_to must be after effective_from")
    if effective_to > parse_date(contract["term_end_date"]):
        fail(errors.ERR_TERM_WINDOW_INVALID,
             "The rate card may not extend past the contract term end")

    record = base_record()
    record.update({
        "contract_id": contract["id"],
        "version_no": len(existing) + 1,
        "effective_from": fmt_date(effective_from),
        "effective_to": fmt_date(effective_to),
        "deposit_rate_bps": deposit_rate_bps,
        "enrollment_rate_bps": enrollment_rate_bps,
        "census_rate_bps": census_rate_bps,
        "persistence_rate_bps": persistence_rate_bps,
        "rate_cap_bps": rate_cap_bps,
        "per_milestone_cap_cents": per_milestone_cap_cents,
        "clawback_window_days": clawback_window_days,
    })
    db.schedules[record["id"]] = record
    touch(contract)
    return obj(serializers.schedule(record), 201)


@bp.route("/recruitment/contracts/<contract_id>/commission-schedules", methods=["GET"])
def list_schedules(contract_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer",
                         "AgencyOwner")
    contract = db.contracts.get(contract_id)
    if contract is not None:
        check_scope(role, user_id, contract["agency_id"])
    if contract is None:
        fail(errors.ERR_CONTRACT_NOT_FOUND, "Contract not found")
    records = calc.contract_schedules(contract_id)
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return arr([serializers.schedule(r) for r in page], limit, offset, total)


# --- territory occupancy ----------------------------------------------------

@bp.route("/recruitment/territory-occupancy", methods=["GET"])
def territory_occupancy():
    auth("RecruitmentOfficer", "ComplianceOfficer")
    country_code = query_req_str("country_code", pattern=COUNTRY_RE)
    at_date = query_req_date("at_date")
    snapshot = calc.occupancy_snapshot(country_code, at_date)
    return obj({
        "country_code": country_code,
        "at_date": fmt_date(at_date),
        "exclusive_active_count": snapshot["exclusive_active_count"],
        "non_exclusive_active_count": snapshot["non_exclusive_active_count"],
        "exclusive_cooloff_until": fmt_date(snapshot["exclusive_cooloff_until"]),
        "exclusive_slot_available": snapshot["exclusive_slot_available"],
    })
