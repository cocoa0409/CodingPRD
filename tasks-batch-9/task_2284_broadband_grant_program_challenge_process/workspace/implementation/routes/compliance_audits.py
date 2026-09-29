"""ComplianceAudit, clawback and remediation endpoints (PRD section 3.9)."""

from datetime import timedelta

from flask import Blueprint

from db import db, new_record, parse_ts, serialize
from errors import ApiError
from middleware import (authenticate, get_cents, get_enum, get_id_list, get_str,
                        get_ts, json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import cascades, domain

bp = Blueprint("compliance_audits", __name__)

READ_ROLES = ("ProgramAdmin", "AuditOfficer", "Subgrantee")
AUDIT_TYPES = ("SPEED_TEST", "SERVICE_AVAILABILITY", "COMBINED")
AUDIT_AWARD_STATES = ("IN_CONSTRUCTION", "CLOSED")
TERMINAL_AUDIT_STATES = ("PASSED", "REMEDIATED", "CLAWBACK_SETTLED", "CLAWBACK_WAIVED")


@bp.post("/broadband/awards/<award_id>/compliance-audits")
def create_audit(award_id):
    user_id, _role = authenticate("AuditOfficer")
    body = json_body()
    audit_type = get_enum(body, "audit_type", AUDIT_TYPES)
    start_raw, start_dt = get_ts(body, "window_start")
    end_raw, end_dt = get_ts(body, "window_end")

    award = domain.require_award(award_id)                               # priority 25
    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")

    buffer = timedelta(hours=calc.AUDIT_BUFFER_HOURS)                    # priority 68
    for other in domain.audits_of_award(award["id"]):
        if other["audit_state"] in TERMINAL_AUDIT_STATES:
            continue
        other_start = parse_ts(other["window_start"])
        other_end = parse_ts(other["window_end"])
        if start_dt <= other_end + buffer and other_start - buffer <= end_dt:
            raise ApiError("ERR_AUDIT_WINDOW_BUFFER_CONFLICT")

    if not (start_dt < end_dt):                                          # priority 70
        raise ApiError("ERR_WINDOW_ORDER_INVALID")

    audit = new_record({
        "award_id": award["id"],
        "audit_type": audit_type,
        "window_start": start_raw,
        "window_end": end_raw,
        "auditor_user_id": user_id,
        "audit_state": "SCHEDULED",
        "tested_location_count": 0,
        "failed_location_ids": [],
        "failed_location_count": 0,
        "noncompliant_share": None,
        "penalty_multiplier": None,
        "recovery_amount_cents": None,
        "settled_amount_cents": None,
        "appeal_count": 0,
        "notice_issued_by_user_id": None,
    })
    db.audits[audit["id"]] = audit
    return object_response(serialize(audit), 201)


@bp.get("/broadband/awards/<award_id>/compliance-audits")
def list_audits(award_id):
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    award = domain.require_award(award_id)
    return paginated(domain.audits_of_award(award["id"]), limit, offset)


@bp.post("/broadband/awards/<award_id>/compliance-audits/<audit_id>/record-result")
def record_result(award_id, audit_id):
    user_id, _role = authenticate("AuditOfficer")
    body = json_body()
    result = get_enum(body, "result", ("PASSED", "FAILED"))
    tested_ids = get_id_list(body, "tested_location_ids")
    failed_ids = get_id_list(body, "failed_location_ids", required=False, default=[])

    award = domain.require_award(award_id)                               # priority 25
    audit = domain.require_audit(award, audit_id)                        # priority 27

    if award.get("last_verifier_user_id") == user_id:                    # priority 32
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if audit["audit_state"] != "SCHEDULED":                              # priority 47
        raise ApiError("ERR_AUDIT_STATE_INVALID")

    if result == "FAILED":
        if not failed_ids:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'failed_location_ids' must not be empty on a failure.")
        for location_id in failed_ids:                                   # priority 60
            location = db.locations.get(location_id)
            if (location is None
                    or location.get("awarded_award_id") != award["id"]
                    or location["eligibility_state"] != "AWARD_BOUND"):
                raise ApiError("ERR_LOCATION_NOT_IN_AWARD_SCOPE")

    if db.now() < parse_ts(audit["window_start"]):
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       "The observation window has not started yet.")

    assign(audit, "tested_location_count", len(tested_ids))
    if result == "PASSED":
        assign(audit, "audit_state", "PASSED")
        assign(audit, "failed_location_ids", [])
        assign(audit, "failed_location_count", 0)
        touch(audit)
        return object_response(serialize(audit))

    share = calc.noncompliant_share(len(failed_ids), award["confirmed_location_count"])
    multiplier = calc.penalty_multiplier(share) if share is not None else None
    assign(audit, "audit_state", "FAILED")
    assign(audit, "failed_location_ids", list(failed_ids))
    assign(audit, "failed_location_count", len(failed_ids))
    assign(audit, "noncompliant_share", float(share) if share is not None else None)
    assign(audit, "penalty_multiplier", float(multiplier) if multiplier is not None else None)
    touch(audit)

    cascades.audit_failure_cascade(audit, award)
    return object_response(serialize(audit))


@bp.post("/broadband/awards/<award_id>/compliance-audits/<audit_id>/issue-clawback-notice")
def issue_clawback_notice(award_id, audit_id):
    user_id, _role = authenticate("AuditOfficer", "ProgramAdmin")
    award = domain.require_award(award_id)                               # priority 25
    audit = domain.require_audit(award, audit_id)                        # priority 27

    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if audit["audit_state"] not in ("FAILED", "APPEALED"):               # priority 47
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    if int(award["disbursed_to_date_cents"]) <= 0:
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       "Nothing has been disbursed on this award, so nothing can be recovered.")

    recovery = calc.recovery_amount(award["disbursed_to_date_cents"],
                                    audit["failed_location_count"],
                                    award["confirmed_location_count"],
                                    audit["penalty_multiplier"])
    assign(audit, "audit_state", "CLAWBACK_NOTICE_ISSUED")
    assign(audit, "recovery_amount_cents", int(recovery))
    assign(audit, "notice_issued_by_user_id", user_id)
    touch(audit)
    return object_response(serialize(audit))


@bp.post("/broadband/awards/<award_id>/compliance-audits/<audit_id>/appeal")
def appeal(award_id, audit_id):
    user_id, _role = authenticate("Subgrantee")
    body = json_body()
    get_str(body, "appeal_basis")                                        # priority 14

    award = domain.require_award(award_id)                               # priority 25
    audit = domain.require_audit(award, audit_id)                        # priority 27
    application = domain.application_of_award(award)

    if application is None or user_id != application["subgrantee_id"]:    # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if audit["audit_state"] != "CLAWBACK_NOTICE_ISSUED":                 # priority 47
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    if int(audit["appeal_count"]) >= 2:
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       "The appeal cycle for this audit is exhausted.")

    assign(audit, "audit_state", "APPEALED")
    assign(audit, "appeal_count", int(audit["appeal_count"]) + 1)
    touch(audit)
    return object_response(serialize(audit))


@bp.post("/broadband/awards/<award_id>/compliance-audits/<audit_id>/resolve-clawback")
def resolve_clawback(award_id, audit_id):
    user_id, _role = authenticate("ProgramAdmin")
    body = json_body()
    resolution = get_enum(body, "resolution", ("SETTLED", "WAIVED"))
    settled_amount = get_cents(body, "settled_amount_cents", required=False)

    award = domain.require_award(award_id)                               # priority 25
    audit = domain.require_audit(award, audit_id)                        # priority 27
    program = domain.program_of_award(award)

    if (resolution == "WAIVED"                                           # priority 32
            and audit.get("notice_issued_by_user_id")
            and audit["notice_issued_by_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    expected_state = "CLAWBACK_NOTICE_ISSUED" if resolution == "SETTLED" else "APPEALED"
    if audit["audit_state"] != expected_state:                           # priority 47
        raise ApiError("ERR_AUDIT_STATE_INVALID")

    if resolution == "WAIVED":
        assign(audit, "audit_state", "CLAWBACK_WAIVED")
        assign(audit, "settled_amount_cents", 0)
        touch(audit)
        return object_response(serialize(audit))

    recovery = audit.get("recovery_amount_cents")
    if recovery is None or int(recovery) > int(award["disbursed_to_date_cents"]):
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       "The recorded recovery amount exceeds what was disbursed.")
    if settled_amount is None:
        settled_amount = int(recovery)
    elif settled_amount < 1 or settled_amount > int(recovery):           # priority 93
        raise ApiError("ERR_CLAWBACK_AMOUNT_INVALID")

    assign(audit, "audit_state", "CLAWBACK_SETTLED")
    assign(audit, "settled_amount_cents", int(settled_amount))
    touch(audit)

    domain.append_ledger(award, "CLAWBACK_RECOVERY", int(settled_amount),
                         "audit:%s" % audit["id"],
                         "Recovery of disbursed funds settled on a failed deployment audit")

    for location_id in list(audit.get("failed_location_ids") or []):
        location = db.locations.get(location_id)
        if location is None:
            continue
        if location["service_state"] == "AUDIT_FAILED" and location.get("certified_at") is not None:
            assign(location, "certified_at", None)
            touch(location)

    assign(award, "compliance_state", "CURED")
    domain.refresh_award(award)
    touch(award)
    if program is not None:
        domain.refresh_program(program)
    return object_response(serialize(audit))


@bp.post("/broadband/awards/<award_id>/compliance-audits/<audit_id>/verify-remediation")
def verify_remediation(award_id, audit_id):
    user_id, _role = authenticate("AuditOfficer", "ProgramAdmin")
    body = json_body()
    get_str(body, "remediation_note", required=False)

    award = domain.require_award(award_id)                               # priority 25
    audit = domain.require_audit(award, audit_id)                        # priority 27

    if award.get("last_verifier_user_id") == user_id:                    # priority 32
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if award["award_state"] not in AUDIT_AWARD_STATES:                   # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if audit["audit_state"] != "FAILED":                                 # priority 47
        raise ApiError("ERR_AUDIT_STATE_INVALID")

    assign(audit, "audit_state", "REMEDIATED")
    touch(audit)
    cascades.remediation_cascade(audit, award)
    return object_response(serialize(audit))
