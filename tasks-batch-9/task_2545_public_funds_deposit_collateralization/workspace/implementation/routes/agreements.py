"""Tri-party pledge agreements, the signature quorum and safekeeping receipts."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    AGREEMENT_STATUSES,
    AMENDMENT_ROUND_LIMIT,
    BENEFICIARY_TYPES,
    CONFIRMATION_STATUSES,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
    SIGNATURE_PARTIES,
)
from errors import fail
from response import list_response, record_response
from services import calc, state

bp = Blueprint("agreements", __name__)

PARTY_STAMP = {
    "DEPOSITORY": "depository_signed_at",
    "PUBLIC_UNIT": "public_unit_signed_at",
    "CUSTODIAN": "custodian_signed_at",
}


def _beneficiary_unit_id(agreement):
    if agreement["beneficiary_type"] != "DEPOSIT_ACCOUNT":
        return None
    account = db.get("deposit_accounts", agreement["deposit_account_id"])
    return None if account is None else account["public_unit_id"]


def _custodian_eligible(custodian):
    return (
        custodian is not None
        and custodian["approval_status"] == "APPROVED"
        and custodian["tri_party_capable"] is True
    )


@bp.post("/pledge-agreements")
def draft_agreement():
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    body = mw.body_json()
    depository = mw.resolve_fk("depositories", body.get("depository_id"))
    custodian = mw.resolve_fk("custodians", body.get("custodian_id"))
    program = mw.resolve_fk("pooled_programs", body.get("pooled_program_id"))
    account = mw.resolve_fk("deposit_accounts", body.get("deposit_account_id"))
    mw.req_id(body, "depository_id")
    mw.req_id(body, "custodian_id")
    beneficiary_type = mw.req_enum(body, "beneficiary_type", BENEFICIARY_TYPES)
    agreement_number = mw.req_text(body, "agreement_number")
    governing_law_state = mw.req_text(body, "governing_law_state")
    if beneficiary_type == "DEPOSIT_ACCOUNT":
        if account is None or program is not None:
            fail("ERR_BENEFICIARY_TARGET_INVALID")
    else:
        if program is None or account is not None:
            fail("ERR_BENEFICIARY_TARGET_INVALID")
        if depository["pooled_program_id"] != program["id"]:
            fail("ERR_BENEFICIARY_TARGET_INVALID")
    for existing in state.agreements_of_depository(depository["id"]):
        if existing["agreement_number"] == agreement_number:
            fail("ERR_DUPLICATE_IDENTIFIER")
    record = db.new_record(
        {
            "depository_id": depository["id"],
            "custodian_id": custodian["id"],
            "beneficiary_type": beneficiary_type,
            "deposit_account_id": account["id"] if account else None,
            "pooled_program_id": program["id"] if program else None,
            "agreement_number": agreement_number,
            "governing_law_state": governing_law_state,
            "status": "DRAFT",
            "depository_signed_at": None,
            "public_unit_signed_at": None,
            "custodian_signed_at": None,
            "signature_count": 0,
            "amendment_round": 0,
            "executed_at": None,
            "terminated_at": None,
            "total_pledged_par_cents": 0,
            "total_collateral_value_cents": 0,
            "active_allocation_count": 0,
        }
    )
    db.insert("pledge_agreements", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/pledge-agreements/<agreement_id>")
def read_agreement(agreement_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_CUSTODIAN,
        ROLE_SYSTEM_OPERATOR,
    )
    return record_response(mw.resolve("pledge_agreements", agreement_id))


@bp.get("/pledge-agreements")
def list_agreements():
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_CUSTODIAN,
    )
    limit, offset = mw.page_params()
    depository_id = mw.query_filter("depository_id")
    custodian_id = mw.query_filter("custodian_id")
    deposit_account_id = mw.query_filter("deposit_account_id")
    pooled_program_id = mw.query_filter("pooled_program_id")
    beneficiary_type = mw.query_filter("beneficiary_type", BENEFICIARY_TYPES)
    status_filter = mw.query_filter("status", AGREEMENT_STATUSES)
    records = db.rows("pledge_agreements")
    if depository_id is not None:
        records = [r for r in records if r["depository_id"] == depository_id]
    if custodian_id is not None:
        records = [r for r in records if r["custodian_id"] == custodian_id]
    if deposit_account_id is not None:
        records = [r for r in records if r["deposit_account_id"] == deposit_account_id]
    if pooled_program_id is not None:
        records = [r for r in records if r["pooled_program_id"] == pooled_program_id]
    if beneficiary_type is not None:
        records = [r for r in records if r["beneficiary_type"] == beneficiary_type]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/pledge-agreements/<agreement_id>/circulate")
def circulate_agreement(agreement_id):
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    agreement = mw.resolve("pledge_agreements", agreement_id)
    if agreement["status"] not in ("DRAFT", "AMENDMENT_REQUESTED"):
        fail("ERR_INVALID_STATE")
    depository = db.get("depositories", agreement["depository_id"])
    if depository is None or depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    custodian = db.get("custodians", agreement["custodian_id"])
    if not _custodian_eligible(custodian):
        fail("ERR_CUSTODIAN_NOT_ELIGIBLE")
    if agreement["status"] == "AMENDMENT_REQUESTED":
        if agreement["amendment_round"] > AMENDMENT_ROUND_LIMIT:
            fail("ERR_ROUND_LIMIT_REACHED")
    agreement["status"] = "PENDING_SIGNATURES"
    db.touch(agreement)
    state.recompute_all()
    return record_response(agreement)


@bp.post("/pledge-agreements/<agreement_id>/signatures")
def sign_agreement(agreement_id):
    user_id, role = mw.authorize(
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_CUSTODIAN,
        ROLE_STATE_REGULATOR,
    )
    agreement = mw.resolve("pledge_agreements", agreement_id)
    if role == ROLE_CUSTODIAN and agreement["custodian_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    if role == ROLE_PUBLIC_UNIT_TREASURER:
        owner = _beneficiary_unit_id(agreement)
        if owner is not None and owner != user_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    body = mw.body_json()
    party = mw.req_enum(body, "party", SIGNATURE_PARTIES)
    if agreement["status"] != "PENDING_SIGNATURES":
        fail("ERR_INVALID_STATE")
    if agreement[PARTY_STAMP[party]] is not None:
        fail("ERR_PARTY_ALREADY_SIGNED")
    if party == "DEPOSITORY":
        if role != ROLE_BANK_COMPLIANCE_OFFICER:
            fail("ERR_SIGNATURE_PARTY_MISMATCH")
    elif party == "CUSTODIAN":
        if role != ROLE_CUSTODIAN:
            fail("ERR_SIGNATURE_PARTY_MISMATCH")
    else:
        if agreement["beneficiary_type"] == "DEPOSIT_ACCOUNT":
            if role != ROLE_PUBLIC_UNIT_TREASURER:
                fail("ERR_SIGNATURE_PARTY_MISMATCH")
        elif role != ROLE_STATE_REGULATOR:
            fail("ERR_SIGNATURE_PARTY_MISMATCH")
    reaching_quorum = agreement["signature_count"] == 2
    agreement[PARTY_STAMP[party]] = db.now_ts()
    agreement["signature_count"] = sum(
        1 for field in PARTY_STAMP.values() if agreement[field] is not None
    )
    if reaching_quorum:
        agreement["status"] = "EXECUTED"
        agreement["signature_count"] = 3
        agreement["executed_at"] = db.now_ts()
    db.touch(agreement)
    state.recompute_all()
    return record_response(agreement)


@bp.post("/pledge-agreements/<agreement_id>/request-amendment")
def request_amendment(agreement_id):
    user_id, role = mw.authorize(ROLE_PUBLIC_UNIT_TREASURER, ROLE_STATE_REGULATOR)
    agreement = mw.resolve("pledge_agreements", agreement_id)
    if role == ROLE_PUBLIC_UNIT_TREASURER and _beneficiary_unit_id(agreement) != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    if agreement["status"] != "PENDING_SIGNATURES":
        fail("ERR_INVALID_STATE")
    if agreement["amendment_round"] + 1 > AMENDMENT_ROUND_LIMIT:
        fail("ERR_ROUND_LIMIT_REACHED")
    agreement["status"] = "AMENDMENT_REQUESTED"
    agreement["amendment_round"] = agreement["amendment_round"] + 1
    for field in PARTY_STAMP.values():
        agreement[field] = None
    agreement["signature_count"] = 0
    db.touch(agreement)
    state.recompute_all()
    return record_response(agreement)


@bp.post("/pledge-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    agreement = mw.resolve("pledge_agreements", agreement_id)
    if agreement["status"] != "EXECUTED":
        fail("ERR_INVALID_STATE")
    if state.has_inflight_substitution_for_agreement(agreement["id"]):
        fail("ERR_INVALID_STATE")
    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = db.now_ts()
    db.touch(agreement)
    for allocation in state.allocations_of_agreement(agreement["id"]):
        if allocation["status"] == "ACTIVE":
            state.release_allocation(allocation, "AGREEMENT_TERMINATED")
    state.recompute_all(apply_status=True)
    return record_response(agreement)


# --------------------------------------------------------- safekeeping receipts
@bp.get("/pledge-agreements/<agreement_id>/safekeeping-receipts")
def list_receipts(agreement_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_CUSTODIAN,
        ROLE_PUBLIC_UNIT_TREASURER,
    )
    agreement = mw.resolve("pledge_agreements", agreement_id)
    limit, offset = mw.page_params()
    status_filter = mw.query_filter("confirmation_status", CONFIRMATION_STATUSES)
    records = [
        r
        for r in db.rows("safekeeping_receipts")
        if r["pledge_agreement_id"] == agreement["id"]
    ]
    if status_filter is not None:
        records = [r for r in records if r["confirmation_status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/safekeeping-receipts")
def issue_receipt():
    user_id, _ = mw.authorize(ROLE_CUSTODIAN)
    body = mw.body_json()
    agreement = mw.resolve_fk("pledge_agreements", body.get("pledge_agreement_id"))
    if agreement is not None and agreement["custodian_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    mw.req_id(body, "pledge_agreement_id")
    receipt_number = mw.req_text(body, "receipt_number")
    reported_par = mw.req_int(body, "reported_par_cents", allow_zero=True)
    reported_count = mw.req_int(body, "reported_asset_count", allow_zero=True)
    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED")
    custodian = db.get("custodians", agreement["custodian_id"])
    if not _custodian_eligible(custodian):
        fail("ERR_CUSTODIAN_NOT_ELIGIBLE")
    for existing in db.rows("safekeeping_receipts"):
        if existing["pledge_agreement_id"] != agreement["id"]:
            continue
        if existing["receipt_number"] == receipt_number:
            fail("ERR_DUPLICATE_IDENTIFIER")
    as_of = db.now_ts()
    ledger_par = 0
    asset_ids = []
    for allocation in state.allocations_of_agreement(agreement["id"]):
        if allocation["status"] != "ACTIVE":
            continue
        if not calc.covers(allocation, as_of.dt):
            continue
        ledger_par += allocation["allocated_par_cents"]
        if allocation["collateral_asset_id"] not in asset_ids:
            asset_ids.append(allocation["collateral_asset_id"])
    record = db.new_record(
        {
            "pledge_agreement_id": agreement["id"],
            "receipt_number": receipt_number,
            "reported_par_cents": reported_par,
            "reported_asset_count": reported_count,
            "as_of": as_of,
            "ledger_par_cents": ledger_par,
            "ledger_asset_count": len(asset_ids),
            "discrepancy_par_cents": reported_par - ledger_par,
            "confirmation_status": "ISSUED",
            "confirmed_by_user_id": None,
            "confirmed_at": None,
        }
    )
    db.insert("safekeeping_receipts", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.post("/safekeeping-receipts/<receipt_id>/confirm")
def confirm_receipt(receipt_id):
    user_id, _ = mw.authorize(ROLE_STATE_REGULATOR)
    receipt = mw.resolve("safekeeping_receipts", receipt_id)
    if receipt["confirmation_status"] != "ISSUED":
        fail("ERR_INVALID_STATE")
    exact = (
        receipt["discrepancy_par_cents"] == 0
        and receipt["reported_asset_count"] == receipt["ledger_asset_count"]
    )
    receipt["confirmation_status"] = "CONFIRMED" if exact else "EXCEPTION"
    receipt["confirmed_by_user_id"] = user_id
    receipt["confirmed_at"] = db.now_ts()
    db.touch(receipt)
    state.recompute_all()
    return record_response(receipt)
