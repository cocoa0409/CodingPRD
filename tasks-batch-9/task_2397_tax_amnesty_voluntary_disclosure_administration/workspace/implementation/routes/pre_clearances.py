"""Anonymous pre-clearance, the mediated negotiation and its round history."""

from flask import Blueprint

import calc
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import (COMPLIANCE_AUDITOR, DISCLOSURE_OFFICER,
                        PROGRAM_ADMINISTRATOR, REPRESENTATIVE)

bp = Blueprint("pre_clearances", __name__)

READERS = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR, REPRESENTATIVE]
TERMINAL = ("ACCEPTED", "REJECTED", "EXPIRED")


def _require_active(user_id):
    representative = db.representatives.get(user_id)
    if representative is not None and representative["status"] == "SUSPENDED":
        raise err("ERR_REPRESENTATIVE_SUSPENDED")


def _program_of(pre_clearance):
    return db.programs.get(pre_clearance["program_id"])


@bp.post("/amnesty/pre-clearances")
def create_pre_clearance():
    user_id, _ = mw.identity([REPRESENTATIVE])
    body = validate.get_body()
    program = mw.body_fk(body, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")

    program_id = validate.vid(body, "program_id")
    tax_type = validate.venum(body, "tax_type", validate.TAX_TYPES)
    alias = validate.vstr(body, "anonymous_alias")
    estimated = validate.vint(body, "estimated_liability_cents", minimum=1)
    under_audit = validate.vbool(body, "self_reported_under_audit")
    validate.vdate(body, "earliest_unfiled_period_start")

    services.check_program_open(program)
    _require_active(user_id)
    services.check_window_live(program)

    rec = db.insert(db.pre_clearances, {
        "program_id": program_id,
        "representative_id": user_id,
        "disclosed_taxpayer_id": None,
        "tax_type": tax_type,
        "anonymous_alias": alias,
        "estimated_liability_cents": estimated,
        "self_reported_under_audit": under_audit,
        "earliest_unfiled_period_start": body["earliest_unfiled_period_start"],
        "status": "SUBMITTED",
        "screening_result": None,
        "rejection_reason": None,
        "round_index": 0,
        "counter_count": 0,
        "current_offer_lookback_months": None,
        "current_offer_penalty_waiver_pct": None,
        "current_offer_interest_waiver_pct": None,
        "last_offer_officer_user_id": None,
    })
    return response.created(services.pre_clearance_out(rec))


@bp.get("/amnesty/pre-clearances")
def list_pre_clearances():
    mw.identity(READERS)
    limit, offset = response.pagination()
    rows = db.ordered(list(db.pre_clearances.values()))
    for field in ("program_id", "representative_id", "disclosed_taxpayer_id", "status"):
        rows = mw.filter_equals(rows, field)
    return response.paginate(rows, limit, offset, services.pre_clearance_out)


@bp.get("/amnesty/pre-clearances/<pre_clearance_id>")
def read_pre_clearance(pre_clearance_id):
    mw.identity(READERS)
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/begin-review")
def begin_review(pre_clearance_id):
    mw.identity([DISCLOSURE_OFFICER])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    services.check_program_open(_program_of(rec))
    if rec["status"] != "SUBMITTED":
        raise err("ERR_PRE_CLEARANCE_NOT_SUBMITTED")

    if rec["self_reported_under_audit"]:
        rec["screening_result"] = "INELIGIBLE_SELF_REPORTED_AUDIT"
        rec["rejection_reason"] = "INELIGIBLE_SELF_REPORTED_AUDIT"
        rec["status"] = "REJECTED"
    else:
        rec["screening_result"] = "ELIGIBLE"
        rec["status"] = "UNDER_REVIEW"
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/offer-terms")
def offer_terms(pre_clearance_id):
    user_id, _ = mw.identity([DISCLOSURE_OFFICER])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    body = validate.get_body()

    expected_version = validate.vint(body, "expected_pre_clearance_version")
    lookback_months = validate.vint(body, "offered_lookback_months")
    penalty_pct = validate.vpct(body, "offered_penalty_waiver_pct")
    interest_pct = validate.vpct(body, "offered_interest_waiver_pct")
    note = validate.vstr(body, "offer_note", required=False, allow_blank=True)

    if expected_version != rec["version"]:
        raise err("ERR_STALE_PRE_CLEARANCE_VERSION")
    program = _program_of(rec)
    services.check_program_open(program)
    if rec["status"] not in ("UNDER_REVIEW", "COUNTERED"):
        raise err("ERR_PRE_CLEARANCE_NOT_NEGOTIABLE")
    # only the first offer is bounded by the program's published lookback depth
    if rec["status"] == "UNDER_REVIEW" and lookback_months > program["lookback_months"]:
        raise err("ERR_LOOKBACK_EXCEEDS_PROGRAM_LIMIT")

    rec["round_index"] = rec["round_index"] + 1
    db.insert(db.negotiation_rounds, {
        "pre_clearance_id": rec["id"],
        "round_index": rec["round_index"],
        "proposed_by": "STATE",
        "lookback_months": lookback_months,
        "penalty_waiver_pct": penalty_pct,
        "interest_waiver_pct": interest_pct,
        "note": note,
        "actor_user_id": user_id,
    }, versioned=False)

    rec["current_offer_lookback_months"] = lookback_months
    rec["current_offer_penalty_waiver_pct"] = penalty_pct
    rec["current_offer_interest_waiver_pct"] = interest_pct
    rec["last_offer_officer_user_id"] = user_id
    rec["status"] = "TERMS_OFFERED"
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/counter")
def counter(pre_clearance_id):
    user_id, role = mw.identity([REPRESENTATIVE])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    mw.require_pre_clearance_owner(rec, user_id, role)
    body = validate.get_body()

    lookback_months = validate.vint(body, "counter_lookback_months")
    penalty_pct = validate.vpct(body, "counter_penalty_waiver_pct")
    interest_pct = validate.vpct(body, "counter_interest_waiver_pct")
    note = validate.vstr(body, "counter_note", required=False, allow_blank=True)

    services.check_program_open(_program_of(rec))
    if rec["status"] != "TERMS_OFFERED":
        raise err("ERR_PRE_CLEARANCE_NOT_OFFERED")
    _require_active(user_id)
    if rec["counter_count"] >= calc.MAX_REPRESENTATIVE_COUNTERS:
        raise err("ERR_NEGOTIATION_ROUND_LIMIT")

    rec["round_index"] = rec["round_index"] + 1
    db.insert(db.negotiation_rounds, {
        "pre_clearance_id": rec["id"],
        "round_index": rec["round_index"],
        "proposed_by": "REPRESENTATIVE",
        "lookback_months": lookback_months,
        "penalty_waiver_pct": penalty_pct,
        "interest_waiver_pct": interest_pct,
        "note": note,
        "actor_user_id": user_id,
    }, versioned=False)

    rec["counter_count"] = rec["counter_count"] + 1
    rec["status"] = "COUNTERED"
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/disclose-identity")
def disclose_identity(pre_clearance_id):
    user_id, role = mw.identity([REPRESENTATIVE])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    body = validate.get_body()
    mw.body_fk(body, "taxpayer_id", db.taxpayers, "ERR_TAXPAYER_NOT_FOUND")
    mw.require_pre_clearance_owner(rec, user_id, role)
    taxpayer_id = validate.vid(body, "taxpayer_id")

    if rec["status"] != "TERMS_OFFERED":
        raise err("ERR_PRE_CLEARANCE_NOT_OFFERED")
    _require_active(user_id)
    if rec["disclosed_taxpayer_id"]:
        raise err("ERR_IDENTITY_ALREADY_DISCLOSED")

    rec["disclosed_taxpayer_id"] = taxpayer_id
    # the criminal test is evaluated before the audit test
    if services.open_criminal_case(taxpayer_id) is not None:
        rec["screening_result"] = "INELIGIBLE_CRIMINAL_INVESTIGATION"
        rec["rejection_reason"] = "INELIGIBLE_CRIMINAL_INVESTIGATION"
        rec["status"] = "REJECTED"
    elif services.open_audit_case(taxpayer_id, [rec["tax_type"]]) is not None:
        rec["screening_result"] = "INELIGIBLE_AUDIT_IN_PROGRESS"
        rec["rejection_reason"] = "INELIGIBLE_AUDIT_IN_PROGRESS"
        rec["status"] = "REJECTED"
    else:
        rec["screening_result"] = "ELIGIBLE"
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/accept")
def accept(pre_clearance_id):
    user_id, role = mw.identity([REPRESENTATIVE])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    mw.require_pre_clearance_owner(rec, user_id, role)
    services.check_program_open(_program_of(rec))
    if rec["status"] != "TERMS_OFFERED":
        raise err("ERR_PRE_CLEARANCE_NOT_OFFERED")
    _require_active(user_id)
    if not rec["disclosed_taxpayer_id"]:
        raise err("ERR_IDENTITY_NOT_DISCLOSED")

    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.post("/amnesty/pre-clearances/<pre_clearance_id>/reject")
def reject(pre_clearance_id):
    mw.identity([DISCLOSURE_OFFICER])
    rec = mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    body = validate.get_body()
    rejection_reason = validate.vstr(body, "rejection_reason")
    if rec["status"] in TERMINAL:
        raise err("ERR_PRE_CLEARANCE_TERMINAL")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = rejection_reason
    db.touch(rec)
    return response.ok(services.pre_clearance_out(rec))


@bp.get("/amnesty/pre-clearances/<pre_clearance_id>/negotiation-rounds")
def list_rounds(pre_clearance_id):
    mw.identity(READERS)
    mw.find(db.pre_clearances, pre_clearance_id, "ERR_PRE_CLEARANCE_NOT_FOUND")
    limit, offset = response.pagination()
    rows = [r for r in db.ordered(list(db.negotiation_rounds.values()))
            if r["pre_clearance_id"] == pre_clearance_id]
    rows = mw.filter_equals(rows, "proposed_by")
    return response.paginate(rows, limit, offset, services.round_out)


@bp.get("/amnesty/negotiation-rounds/<round_id>")
def read_round(round_id):
    mw.identity(READERS)
    rec = mw.find(db.negotiation_rounds, round_id, "ERR_NEGOTIATION_ROUND_NOT_FOUND")
    return response.ok(services.round_out(rec))
