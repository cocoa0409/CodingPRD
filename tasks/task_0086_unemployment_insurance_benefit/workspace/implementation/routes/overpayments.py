"""Overpayment + OverpaymentRecovery endpoints."""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import (
    as_enum, as_int, as_string, check_occ, get_json_body, paginate, serialize,
)
from services import calculations as calc

bp = Blueprint("overpayments", __name__)

ESTABLISHED = "ESTABLISHED"
RECOVERING = "RECOVERING"
SATISFIED = "SATISFIED"
WAIVED = "WAIVED"


@bp.route("/ui/overpayments", methods=["POST"])
def create_overpayment():
    p = authenticate()
    require_role(p, {"Adjudicator"})
    body = get_json_body()
    claim_id = as_string(body, "claim_id")
    if claim_id not in db.claims:
        raise err("ERR_NOT_FOUND", "claim_id not found.")
    cause = as_enum(body, "cause", {"FRAUD", "NONFRAUD"})
    principal = as_int(body, "principal_cents", minimum=1)
    if principal <= 0:
        raise err("ERR_INVALID_REQUEST", "principal_cents must be > 0.")

    penalty, total_assessed = calc.overpayment_penalty(cause, principal)
    rec = {
        "claim_id": claim_id,
        "cause": cause,
        "principal_cents": principal,
        "penalty_cents": penalty,
        "total_assessed_cents": total_assessed,
        "recovered_cents": 0,
        "status": ESTABLISHED,
    }
    db.stamp_create(rec)
    db.overpayments[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/overpayments/<oid>", methods=["GET"])
def get_overpayment(oid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant", "BenefitPaymentOfficer"})
    rec = db.overpayments.get(oid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Overpayment not found.")
    return object_response(serialize(rec))


@bp.route("/ui/claims/<cid>/overpayments", methods=["GET"])
def list_claim_overpayments(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant", "BenefitPaymentOfficer"})
    if cid not in db.claims:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    items = [o for o in db.overpayments.values() if o["claim_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/overpayments/<oid>/recoveries", methods=["POST"])
def create_recovery(oid):
    p = authenticate()
    require_role(p, {"BenefitPaymentOfficer"})
    op = db.overpayments.get(oid)
    if not op:
        raise err("ERR_NOT_FOUND", "Overpayment not found.")
    body = get_json_body()
    recovery_method = as_enum(body, "recovery_method", {"OFFSET", "CASH"})
    amount = as_int(body, "amount_cents", minimum=1)
    if amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0.")
    # expected_overpayment_version REQUIRED (§2.6)
    if "expected_overpayment_version" not in body or body["expected_overpayment_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_overpayment_version is required.")

    wc = None
    wc_id = body.get("weekly_certification_id")
    if recovery_method == "OFFSET":
        if wc_id is None:
            raise err("ERR_INVALID_REQUEST",
                      "weekly_certification_id is required for an OFFSET recovery.")
    if wc_id is not None:
        wc = db.weekly_certifications.get(wc_id)
        if wc is None:
            raise err("ERR_NOT_FOUND", "weekly_certification_id not found.")

    # state check (priority 7): defined from ESTABLISHED or RECOVERING
    if op["status"] not in (ESTABLISHED, RECOVERING):
        raise err("ERR_INVALID_STATE", "Overpayment cannot accept recoveries from its state.")

    # business fiscal (priority 13): over-recovery
    new_recovered = op["recovered_cents"] + amount
    if new_recovered > op["total_assessed_cents"]:
        raise err("ERR_OVER_RECOVERY",
                  "Recovery would exceed total_assessed_cents.")

    # OCC (specific code) last
    check_occ(body, "expected_overpayment_version", op,
              "ERR_STALE_OVERPAYMENT_VERSION", required=True)

    # Create recovery
    rec = {
        "overpayment_id": oid,
        "weekly_certification_id": wc_id,
        "recovery_method": recovery_method,
        "amount_cents": amount,
        "status": "APPLIED",
    }
    db.stamp_create(rec)
    db.overpayment_recoveries[rec["id"]] = rec

    # Apply to overpayment
    op["recovered_cents"] = new_recovered
    if new_recovered == op["total_assessed_cents"]:
        op["status"] = SATISFIED
    else:
        op["status"] = RECOVERING

    # Cascade: OFFSET drives PAID -> OFFSET on the referenced week
    if recovery_method == "OFFSET" and wc is not None:
        if wc["payment_status"] == "PAID":
            wc["payment_status"] = "OFFSET"
            db.touch(wc)

    db.touch(op)
    return object_response(serialize(rec), 201)


@bp.route("/ui/overpayments/<oid>/recoveries", methods=["GET"])
def list_recoveries(oid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "BenefitPaymentOfficer"})
    if oid not in db.overpayments:
        raise err("ERR_NOT_FOUND", "Overpayment not found.")
    items = [r for r in db.overpayment_recoveries.values()
             if r["overpayment_id"] == oid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/weekly-certifications/<wcid>/recoveries", methods=["GET"])
def list_week_recoveries(wcid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "BenefitPaymentOfficer"})
    if wcid not in db.weekly_certifications:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    items = [r for r in db.overpayment_recoveries.values()
             if r.get("weekly_certification_id") == wcid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/overpayments/<oid>/waive", methods=["POST"])
def waive_overpayment(oid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    op = db.overpayments.get(oid)
    if not op:
        raise err("ERR_NOT_FOUND", "Overpayment not found.")
    body = get_json_body()
    # state check: waive defined from ESTABLISHED
    if op["status"] != ESTABLISHED:
        raise err("ERR_INVALID_STATE", "Overpayment is not ESTABLISHED.")
    # waiver eligibility (priority 12)
    if op["cause"] != "NONFRAUD" or op["recovered_cents"] != 0:
        raise err("ERR_WAIVER_NOT_ALLOWED",
                  "Only a NONFRAUD overpayment with nothing recovered may be waived.")
    check_occ(body, "expected_overpayment_version", op, "ERR_STALE_VERSION")
    op["status"] = WAIVED
    db.touch(op)
    return object_response(serialize(op))
