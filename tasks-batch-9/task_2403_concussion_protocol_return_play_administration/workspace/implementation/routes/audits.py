"""Protocol auditing, penalty pricing and club sanctions (PRD §3.10)."""
from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import audits as audit_service
from services import calc
from services import posture

bp = Blueprint("audits", __name__)

_FINDINGS_FROM_STATES = ("OPEN", "CLUB_RESPONDED")
_CLOSE_FROM_STATES = ("OPEN", "FINDINGS_ISSUED", "CLUB_RESPONDED")


@bp.post("/protocol-audits")
def open_audit():
    actor = V.authenticate(["LeagueAuditor"])
    b = V.body()
    club_id = V.req_id(b, "club_id")
    case_id = V.opt_id(b, "case_id")
    evaluation_id = V.opt_id(b, "sideline_evaluation_id")

    club = V.get_club(club_id)
    if case_id is not None:
        V.get_case(case_id)
    if evaluation_id is not None:
        V.get_evaluation(evaluation_id)

    audit = audit_service.new_audit_row(
        club["id"],
        case_id=case_id,
        sideline_evaluation_id=evaluation_id,
        opened_by_user_id=actor.user_id,
        auto_opened=False,
    )
    club["open_violation_count"] = calc.open_violation_count(club["id"])
    touch(club)
    return created(S.audit_out(audit))


@bp.post("/protocol-audits/<row_id>/findings")
def issue_findings(row_id):
    actor = V.authenticate(["LeagueAuditor"])
    b = V.body()
    violation_codes = V.req_enum_array(
        b, "violation_codes", C.VIOLATION_CODE_CANONICAL_ORDER, allow_empty=False)
    exposure_days = V.req_int(b, "exposure_days", 0, 30)

    audit = V.get_audit(row_id)
    if audit["status"] not in _FINDINGS_FROM_STATES:
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       message="Findings may only be issued from OPEN or CLUB_RESPONDED.")
    opened_by = audit.get("opened_by_user_id")
    if opened_by is not None and opened_by == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    club = db.clubs.get(audit["club_id"])

    # Step 1: tier band of the preliminary score with THIS audit excluded.
    tier = calc.tier_for_score(
        calc.preliminary_score(audit["club_id"], exclude_audit_id=audit["id"]))

    # Price the findings on a probe row so the fine cap can be tested first.
    probe = {
        "case_id": audit.get("case_id"),
        "violation_codes": list(violation_codes),
        "exposure_days": exposure_days,
    }
    fine = calc.compute_fine_cents(probe, tier)
    projected = calc.outstanding_fine_cents(
        audit["club_id"], override_audit_id=audit["id"], override_value=fine)
    if projected > C.SEASON_FINE_CAP_CENTS:
        raise ApiError("ERR_CLUB_FINE_CAP_EXCEEDED")

    audit["escalation_tier_at_issuance"] = tier          # step 1
    audit["violation_codes"] = list(violation_codes)     # step 2
    audit["exposure_days"] = exposure_days
    audit["assessed_fine_cents"] = fine                  # step 3
    audit["status"] = "FINDINGS_ISSUED"                  # step 4
    audit["findings_issued_at"] = db.now
    audit["findings_issued_by_user_id"] = actor.user_id
    touch(audit)

    if club is not None:                                 # step 5
        posture.propagate(club)
    return ok(S.audit_out(audit))


@bp.post("/protocol-audits/<row_id>/respond")
def respond_to_audit(row_id):
    actor = V.authenticate(["ClubComplianceOfficer"])
    b = V.body()
    response_note = V.req_str(b, "response_note")

    audit = V.get_audit(row_id)
    V.officer_scope(actor, audit["club_id"])
    if audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       message="Only an audit in FINDINGS_ISSUED may be answered.")
    if int(audit["response_round_count"]) >= C.MAX_AUDIT_RESPONSE_ROUNDS:
        raise ApiError("ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED")

    audit["status"] = "CLUB_RESPONDED"
    audit["club_response_note"] = response_note
    audit["response_round_count"] = int(audit["response_round_count"]) + 1
    touch(audit)
    return ok(S.audit_out(audit))


@bp.post("/protocol-audits/<row_id>/close")
def close_audit(row_id):
    actor = V.authenticate(["LeagueAuditor"])
    b = V.body()
    disposition = V.req_enum(b, "disposition", C.CLOSE_DISPOSITIONS)
    closing_note = V.opt_str(b, "closing_note")

    audit = V.get_audit(row_id)
    if audit["status"] not in _CLOSE_FROM_STATES:
        raise ApiError("ERR_AUDIT_STATE_INVALID", message="The audit is already closed.")
    if disposition == "UPHELD" and (
            audit["status"] == "OPEN" or not (audit.get("violation_codes") or [])):
        raise ApiError("ERR_AUDIT_STATE_INVALID",
                       message="An audit with no findings may not be upheld.")
    issued_by = audit.get("findings_issued_by_user_id")
    if issued_by is not None and issued_by == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    audit["disposition"] = disposition
    audit["closed_at"] = db.now
    audit["closed_by_user_id"] = actor.user_id
    if closing_note is not None:
        audit["closing_note"] = closing_note
    if disposition == "UPHELD":
        audit["status"] = "CLOSED_UPHELD"
    else:
        audit["status"] = "CLOSED_DISMISSED"
        audit["assessed_fine_cents"] = 0
    touch(audit)

    club = db.clubs.get(audit["club_id"])
    if club is not None:
        posture.propagate(club)
    return ok(S.audit_out(audit))


@bp.get("/protocol-audits/<row_id>")
def get_audit(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    audit = V.get_audit(row_id)
    V.role_identity(actor)
    return ok(S.audit_out(audit))


@bp.get("/protocol-audits")
def list_audits():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    club_id = V.filter_str("club_id")
    case_id = V.filter_str("case_id")
    evaluation_id = V.filter_str("sideline_evaluation_id")
    status = V.filter_enum("status", C.AUDIT_STATUSES)
    auto_opened = V.filter_bool("auto_opened")
    V.role_identity(actor)

    rows = sort_rows(list(db.protocol_audits.values()))
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if case_id is not None:
        rows = [r for r in rows if r.get("case_id") == case_id]
    if evaluation_id is not None:
        rows = [r for r in rows if r.get("sideline_evaluation_id") == evaluation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if auto_opened is not None:
        rows = [r for r in rows if bool(r["auto_opened"]) == auto_opened]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.audit_out(r) for r in page], limit, offset, total)
