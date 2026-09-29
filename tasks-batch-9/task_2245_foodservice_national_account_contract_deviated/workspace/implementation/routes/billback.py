"""Manufacturer bill-back claims and the cash-application waterfall."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch, values
from errors import fail
from routes.common import PREFIX, listing, require_state, unique_or_reject
from services import billback
from util import half_open_overlap

bp = Blueprint("billback", __name__)

REVERSIBLE_CLAIM_STATUSES = ("SUBMITTED", "PARTIALLY_RECOVERED", "RECOVERED", "DISPUTED")


# --- claims ----------------------------------------------------------------

@bp.post(PREFIX + "/bill-back-claims")
def create_claim():
    middleware.authenticate(["RebateAccountant"])
    data = validation.body(("deviation_agreement_id", "claim_period_start",
                            "claim_period_end", "expected_deviation_agreement_version"))
    deviation = middleware.get_deviation(
        db, validation.raw_fk(data, "deviation_agreement_id"))
    claim_period_start = validation.get_dt(data, "claim_period_start")
    claim_period_end = validation.get_dt(data, "claim_period_end")
    if claim_period_end <= claim_period_start:
        fail(errors.ERR_INVALID_REQUEST,
             "claim_period_end must be strictly after claim_period_start.")
    expected_version = validation.get_int(
        data, "expected_deviation_agreement_version", minimum=1)

    if expected_version != deviation["version"]:
        fail(errors.ERR_STALE_DEVIATION_VERSION)

    for other in values(db.bill_back_claims):
        if other["deviation_agreement_id"] != deviation["id"]:
            continue
        if other["status"] == "WRITTEN_OFF":
            continue
        if half_open_overlap(claim_period_start, claim_period_end,
                             other["claim_period_start"], other["claim_period_end"]):
            fail(errors.ERR_CLAIM_PERIOD_OVERLAP)

    lines = billback.sweep_lines(deviation["id"], claim_period_start, claim_period_end)
    claimed_cases, claimed_amount = billback.claim_figures(lines)
    if claimed_cases == 0:
        fail(errors.ERR_NO_QUALIFYING_LINES)

    record = insert(db.bill_back_claims, {
        "deviation_agreement_id": deviation["id"],
        "manufacturer_id": deviation["manufacturer_id"],
        "claim_period_start": claim_period_start,
        "claim_period_end": claim_period_end,
        "claimed_cases": claimed_cases,
        "claimed_amount_cents": claimed_amount,
        "recovered_amount_cents": 0,
        "status": "ACCRUED",
        "submitted_by_user_id": None,
        "submitted_at": None,
        "write_off_reason": None,
    })

    for line in lines:
        if line["billback_status"] == "ACCRUED":
            line["billback_status"] = "CLAIMED"
        line["bill_back_claim_id"] = record["id"]
        touch(line)

    touch(deviation)

    manufacturer = db.manufacturers.get(record["manufacturer_id"])
    if manufacturer is not None:
        billback.recompute_exposure(manufacturer)

    return response.created(response.serialize(record))


@bp.get(PREFIX + "/bill-back-claims/<bill_back_claim_id>")
def read_claim(bill_back_claim_id):
    middleware.authenticate(["RebateAccountant", "ManufacturerRep", "ContractAuditor",
                             "NationalAccountManager", "PricingAnalyst"])
    record = middleware.get_claim(db, bill_back_claim_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/bill-back-claims")
def list_claims():
    middleware.authenticate(["RebateAccountant", "ManufacturerRep", "ContractAuditor",
                             "NationalAccountManager", "PricingAnalyst"])
    return listing(db.bill_back_claims, (
        ("deviation_agreement_id", "deviation_agreement_id", None),
        ("manufacturer_id", "manufacturer_id", None),
        ("status", "status", validation.CLAIM_STATUSES),
    ))


@bp.post(PREFIX + "/bill-back-claims/<bill_back_claim_id>/submit")
def submit_claim(bill_back_claim_id):
    caller = middleware.authenticate(["RebateAccountant"])
    claim = middleware.get_claim(db, bill_back_claim_id)
    validation.body(())
    require_state(claim, ("ACCRUED", "DISPUTED"), errors.ERR_CLAIM_INVALID_STATE)
    manufacturer = db.manufacturers.get(claim["manufacturer_id"])
    if manufacturer is None or manufacturer["status"] != "ACTIVE":
        fail(errors.ERR_MANUFACTURER_SUSPENDED)
    if claim["claimed_amount_cents"] < 1:
        fail(errors.ERR_CLAIM_INVALID_STATE,
             "A claim with nothing recoverable may not be submitted.")

    claim["status"] = "SUBMITTED"
    claim["submitted_by_user_id"] = caller.user_id
    claim["submitted_at"] = clock()
    touch(claim)

    billback.recompute_exposure(manufacturer)
    touch(manufacturer)
    return response.ok(response.serialize(claim))


@bp.post(PREFIX + "/bill-back-claims/<bill_back_claim_id>/dispute")
def dispute_claim(bill_back_claim_id):
    caller = middleware.authenticate(["ManufacturerRep"])
    claim = middleware.get_claim(db, bill_back_claim_id)
    middleware.require_owner(caller, claim["manufacturer_id"])
    data = validation.body(("note",))
    validation.get_str(data, "note")
    require_state(claim, ("SUBMITTED", "PARTIALLY_RECOVERED"), errors.ERR_CLAIM_INVALID_STATE)

    claim["status"] = "DISPUTED"
    billback.recompute_claim_amount(claim)
    touch(claim)

    manufacturer = db.manufacturers.get(claim["manufacturer_id"])
    if manufacturer is not None:
        billback.recompute_exposure(manufacturer)
    return response.ok(response.serialize(claim))


@bp.post(PREFIX + "/bill-back-claims/<bill_back_claim_id>/write-off")
def write_off_claim(bill_back_claim_id):
    caller = middleware.authenticate(["ContractAuditor"])
    claim = middleware.get_claim(db, bill_back_claim_id)
    data = validation.body(("write_off_reason",))
    reason = validation.get_str(data, "write_off_reason")
    require_state(claim, ("SUBMITTED", "PARTIALLY_RECOVERED", "DISPUTED"),
                  errors.ERR_CLAIM_INVALID_STATE)
    if caller.user_id == claim["submitted_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    claim["status"] = "WRITTEN_OFF"
    claim["write_off_reason"] = reason
    touch(claim)

    for line in billback.lines_of_claim(claim["id"]):
        if line["billback_status"] == "CLAIMED":
            line["billback_status"] = "WRITTEN_OFF"
            touch(line)

    manufacturer = db.manufacturers.get(claim["manufacturer_id"])
    if manufacturer is not None:
        billback.recompute_exposure(manufacturer)
        touch(manufacturer)
    return response.ok(response.serialize(claim))


# --- remittances -----------------------------------------------------------

@bp.post(PREFIX + "/bill-back-remittances")
def create_remittance():
    middleware.authenticate(["RebateAccountant"])
    data = validation.body(("manufacturer_id", "remitted_amount_cents",
                            "remittance_reference"))
    manufacturer = middleware.get_manufacturer(
        db, validation.raw_fk(data, "manufacturer_id"))
    remitted = validation.get_int(data, "remitted_amount_cents", minimum=1)
    reference = validation.get_str(data, "remittance_reference")
    unique_or_reject(db.bill_back_remittances, "remittance_reference", reference,
                     "manufacturer_id", manufacturer["id"])

    record = insert(db.bill_back_remittances, {
        "manufacturer_id": manufacturer["id"],
        "remitted_amount_cents": remitted,
        "remittance_reference": reference,
        "applied_claim_ids": [],
        "applied_amount_cents": 0,
        "unapplied_amount_cents": 0,
        "received_at": clock(),
        "status": "APPLIED",
    })
    billback.apply_waterfall(record, manufacturer)
    touch(manufacturer)
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/bill-back-remittances/<bill_back_remittance_id>")
def read_remittance(bill_back_remittance_id):
    middleware.authenticate(["RebateAccountant", "ManufacturerRep", "ContractAuditor"])
    record = middleware.get_remittance(db, bill_back_remittance_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/bill-back-remittances")
def list_remittances():
    middleware.authenticate(["RebateAccountant", "ManufacturerRep", "ContractAuditor"])
    return listing(db.bill_back_remittances, (
        ("manufacturer_id", "manufacturer_id", None),
        ("status", "status", validation.REMITTANCE_STATUSES),
    ))


@bp.post(PREFIX + "/bill-back-remittances/<bill_back_remittance_id>/reverse")
def reverse_remittance(bill_back_remittance_id):
    middleware.authenticate(["RebateAccountant"])
    remittance = middleware.get_remittance(db, bill_back_remittance_id)
    data = validation.body(("reason",))
    validation.get_str(data, "reason")
    require_state(remittance, ("APPLIED",), errors.ERR_REMITTANCE_INVALID_STATE)

    for claim_id in remittance["applied_claim_ids"]:
        claim = db.bill_back_claims.get(claim_id)
        if claim is not None and claim["status"] not in REVERSIBLE_CLAIM_STATUSES:
            fail(errors.ERR_CLAIM_INVALID_STATE,
                 "A written-off claim blocks the reversal of this remittance.")

    manufacturer = db.manufacturers[remittance["manufacturer_id"]]
    billback.reverse_waterfall(remittance, manufacturer)
    remittance["status"] = "REVERSED"
    touch(remittance)
    touch(manufacturer)
    return response.ok(response.serialize(remittance))
