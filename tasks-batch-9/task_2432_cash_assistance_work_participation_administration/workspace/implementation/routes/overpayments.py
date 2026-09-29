"""Overpayment claims, the recovery ledger and fraud referral (PRD 3.9)."""

from flask import Blueprint

import guards
from calc import established_amount, monthly_recoupment
from domain import (lookup, recompute_overpayment_ledger, rows_where, tlm_issued)
from errors import fail
from guards import (Fields, body_str, raw_body, require, require_different_actor)
from respond import created, filter_value, listing, ok, pagination
from store import db, new_record, touch

bp = Blueprint("overpayments", __name__)

CLAIM_TYPES = ("AGENCY_ERROR", "CLIENT_ERROR", "SUSPECTED_FRAUD")
COMPUTATION_METHODS = ("GROSS", "NET")
RECOVERY_METHODS = ("BENEFIT_RECOUPMENT", "CASH_PAYMENT", "TAX_INTERCEPT",
                    "RECOUPMENT_REVERSAL")
DISPOSITIONS = ("SUBSTANTIATED", "UNSUBSTANTIATED")
LEDGER_OPEN_STATUSES = ("ESTABLISHED", "IN_RECOVERY", "SATISFIED")


def _claim(overpayment_id):
    return lookup("overpayments", overpayment_id, "ERR_OVERPAYMENT_NOT_FOUND")


@bp.post("/overpayments")
def draft_claim():
    require(guards.FISCAL, guards.FRAUD)
    body = raw_body()
    candidate = body_str(body, "case_id")
    if candidate is not None:
        lookup("cases", candidate, "ERR_CASE_NOT_FOUND")
    fields = Fields(body)
    fields.identifier("case_id")
    fields.enum("claim_type", CLAIM_TYPES)
    fields.month_list("months_covered")
    fields.integer("gross_amount_cents", minimum=1)
    fields.enum("computation_method", COMPUTATION_METHODS)
    fields.integer("offsetting_underpayment_cents", required=False, default=0)

    claim = new_record({
        "case_id": fields["case_id"],
        "claim_type": fields["claim_type"],
        "months_covered": fields["months_covered"],
        "gross_amount_cents": fields["gross_amount_cents"],
        "offsetting_underpayment_cents": fields["offsetting_underpayment_cents"],
        "computation_method": fields["computation_method"],
        "established_amount_cents": 0,
        "total_recovered_cents": 0,
        "balance_cents": 0,
        "monthly_recoupment_cents": 0,
        "status": "DRAFT",
        "recoupment_status": "NOT_STARTED",
        "fraud_referral_status": "NOT_REFERRED",
        "established_by_user_id": None,
        "write_off_reason": None,
        "referral_note": None,
    })
    db.overpayments[claim["id"]] = claim
    return created(claim)


@bp.get("/overpayments/<overpayment_id>")
def read_claim(overpayment_id):
    require(*guards.STAFF_ROLES)
    return ok(_claim(overpayment_id))


@bp.get("/cases/<case_id>/overpayments")
def list_case_claims(case_id):
    require(*guards.STAFF_ROLES)
    lookup("cases", case_id, "ERR_CASE_NOT_FOUND")
    limit, offset = pagination()
    rows = rows_where("overpayments", case_id=case_id)
    for name in ("status", "recoupment_status"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/overpayments/<overpayment_id>/establish")
def establish(overpayment_id):
    actor = require(guards.FISCAL, guards.FRAUD)
    claim = _claim(overpayment_id)
    if claim["status"] != "DRAFT":
        fail("ERR_INVALID_OVERPAYMENT_STATE",
             "Only a DRAFT claim may be established.")
    for month in claim["months_covered"]:
        if not tlm_issued(claim["case_id"], month):
            fail("ERR_OVERPAID_MONTH_NOT_ISSUED",
                 "Month %s was never issued on this case." % month)
    case = db.cases[claim["case_id"]]
    amount = established_amount(claim["gross_amount_cents"],
                                claim["offsetting_underpayment_cents"],
                                claim["computation_method"])
    claim["established_amount_cents"] = amount
    claim["monthly_recoupment_cents"] = monthly_recoupment(
        case["benefit_amount_cents"], claim["claim_type"],
        claim["fraud_referral_status"])
    claim["balance_cents"] = amount - claim["total_recovered_cents"]
    claim["established_by_user_id"] = actor.user_id
    claim["recoupment_status"] = "NOT_STARTED"
    claim["status"] = "ESTABLISHED"
    touch(claim)
    return ok(claim)


@bp.post("/overpayments/<overpayment_id>/recovery-transactions")
def post_recovery(overpayment_id):
    require(guards.FISCAL)
    claim = _claim(overpayment_id)
    fields = Fields(raw_body())
    fields.enum("method", RECOVERY_METHODS)
    fields.integer("amount_cents", minimum=1)
    fields.month("applied_month")
    fields.integer("expected_overpayment_version")
    if fields["expected_overpayment_version"] != claim["version"]:
        fail("ERR_STALE_OVERPAYMENT_VERSION",
             "The overpayment has changed since it was read.")
    if claim["status"] not in LEDGER_OPEN_STATUSES:
        fail("ERR_INVALID_OVERPAYMENT_STATE",
             "The claim is not open for recovery entries.")
    method = fields["method"]
    amount = fields["amount_cents"]
    case = db.cases[claim["case_id"]]
    if method == "BENEFIT_RECOUPMENT" and case["benefit_status"] != "ACTIVE":
        fail("ERR_CASE_NOT_ACTIVE",
             "Benefit recoupment requires an ACTIVE case.")
    if method != "RECOUPMENT_REVERSAL" and amount > claim["balance_cents"]:
        fail("ERR_RECOVERY_EXCEEDS_BALANCE",
             "The recovery amount exceeds the outstanding balance.")
    if method == "RECOUPMENT_REVERSAL" and amount > claim["total_recovered_cents"]:
        fail("ERR_REVERSAL_EXCEEDS_RECOVERED",
             "The reversal amount exceeds the amount recovered.")

    entry = new_record({
        "overpayment_id": claim["id"],
        "method": method,
        "amount_cents": amount,
        "applied_month": fields["applied_month"],
        "signed_amount_cents": -amount if method == "RECOUPMENT_REVERSAL" else amount,
    }, audited=False)
    db.recovery_transactions[entry["id"]] = entry

    recompute_overpayment_ledger(claim)
    claim["status"] = "IN_RECOVERY"
    claim["recoupment_status"] = "ACTIVE"
    if claim["balance_cents"] == 0:
        claim["status"] = "SATISFIED"
        claim["recoupment_status"] = "NOT_STARTED"
    touch(claim)
    return created(entry)


@bp.get("/overpayments/<overpayment_id>/recovery-transactions")
def list_recovery(overpayment_id):
    require(*guards.STAFF_ROLES)
    _claim(overpayment_id)
    limit, offset = pagination()
    rows = rows_where("recovery_transactions", overpayment_id=overpayment_id)
    for name in ("method", "applied_month"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/overpayments/<overpayment_id>/write-off")
def write_off(overpayment_id):
    actor = require(guards.FISCAL)
    claim = _claim(overpayment_id)
    fields = Fields(raw_body())
    fields.text("write_off_reason")
    require_different_actor(actor, claim["established_by_user_id"])
    if claim["status"] not in ("ESTABLISHED", "IN_RECOVERY"):
        fail("ERR_INVALID_OVERPAYMENT_STATE",
             "Only an ESTABLISHED or IN_RECOVERY claim may be written off.")
    claim["status"] = "WRITTEN_OFF"
    claim["write_off_reason"] = fields["write_off_reason"]
    claim["recoupment_status"] = "NOT_STARTED"
    touch(claim)
    return ok(claim)


@bp.post("/overpayments/<overpayment_id>/fraud-referral")
def fraud_referral(overpayment_id):
    require(guards.FRAUD)
    claim = _claim(overpayment_id)
    fields = Fields(raw_body())
    fields.text("referral_note")
    if claim["status"] not in LEDGER_OPEN_STATUSES or \
            claim["fraud_referral_status"] != "NOT_REFERRED":
        fail("ERR_INVALID_OVERPAYMENT_STATE",
             "This claim may not be referred for investigation.")
    claim["fraud_referral_status"] = "REFERRED"
    claim["referral_note"] = fields["referral_note"]
    touch(claim)
    return ok(claim)


@bp.post("/overpayments/<overpayment_id>/fraud-disposition")
def fraud_disposition(overpayment_id):
    require(guards.FRAUD)
    claim = _claim(overpayment_id)
    fields = Fields(raw_body())
    fields.enum("disposition", DISPOSITIONS)
    if claim["fraud_referral_status"] != "REFERRED":
        fail("ERR_INVALID_OVERPAYMENT_STATE",
             "Only a REFERRED claim may receive a disposition.")
    claim["fraud_referral_status"] = fields["disposition"]
    if fields["disposition"] == "SUBSTANTIATED":
        case = db.cases[claim["case_id"]]
        claim["monthly_recoupment_cents"] = monthly_recoupment(
            case["benefit_amount_cents"], claim["claim_type"], "SUBSTANTIATED")
    touch(claim)
    return ok(claim)
