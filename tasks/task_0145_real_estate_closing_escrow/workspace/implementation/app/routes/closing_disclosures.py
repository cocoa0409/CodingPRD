"""ClosingDisclosure endpoints — the heart of the 3-business-day cooling-off rule."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.calculations import (
    add_three_business_days,
    compute_cash_to_close,
    emd_credited_total,
    proration_credits,
)
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body
from app.serializers import serialize_cd
from app.util import (
    new_uuid,
    now_ts,
    optional_enum,
    optional_number,
    parse_iso_dt,
    require_enum,
    require_int,
    require_number,
    require_str,
    round_half_up_money,
)

bp = Blueprint("closing_disclosures", __name__)

CD_STATES = {"DRAFT", "ISSUED", "ACKNOWLEDGED", "READY_TO_FUND", "REVISED", "VOIDED"}
TRIGGERING_CHANGE_KINDS = {
    "NONE",
    "APR_DELTA_OVER_THRESHOLD",
    "LOAN_PRODUCT_CHANGE",
    "PREPAYMENT_PENALTY_ADDED",
    "FEE_DELTA_UNDER_THRESHOLD",
}
MAJOR_CHANGES = {"APR_DELTA_OVER_THRESHOLD", "LOAN_PRODUCT_CHANGE", "PREPAYMENT_PENALTY_ADDED"}


def _refreeze_cash_to_close(cd: dict) -> None:
    f = store.escrow_files[cd["escrow_file_id"]]
    prop = store.properties[f["property_id"]]
    pror = proration_credits(
        tax_annual=Decimal(str(prop["tax_annual"])),
        hoa_annual_dues=Decimal(str(prop["hoa_annual_dues"])),
        seller_days_owned=int(cd["seller_days_owned"]),
    )
    cd["prorated_tax_credit"] = pror["prorated_tax_credit"]
    cd["prorated_hoa_credit"] = pror["prorated_hoa_credit"]
    emds = [e for e in store.earnest_money.values() if e["escrow_file_id"] == cd["escrow_file_id"]]
    emd_total = emd_credited_total(emds)
    cd["cash_to_close"] = compute_cash_to_close(
        purchase_price=Decimal(str(f["purchase_price"])),
        loan_amount=Decimal(str(f.get("loan_amount", 0))),
        emd_credited=emd_total,
        seller_credits=Decimal(str(cd.get("seller_credits", 0))),
        prorated_tax_credit=cd["prorated_tax_credit"],
        prorated_hoa_credit=cd["prorated_hoa_credit"],
        total_loan_costs=Decimal(str(cd.get("total_loan_costs", 0))),
    )


# ---------------------------------------------------------------------------
# Create / Read
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures")
def create_cd():
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    total_loan_costs = round_half_up_money(optional_number(body, "total_loan_costs", 0))
    seller_credits = round_half_up_money(optional_number(body, "seller_credits", 0))
    seller_days_owned = require_int(body, "seller_days_owned")
    if seller_days_owned < 0 or seller_days_owned > 366:
        raise ApiError("ERR_BAD_REQUEST", "seller_days_owned must be between 0 and 366.")
    if total_loan_costs < 0 or seller_credits < 0:
        raise ApiError("ERR_BAD_REQUEST", "Loan costs and seller credits must be non-negative.")

    cid = new_uuid()
    ts = now_ts()
    cd = {
        "id": cid,
        "escrow_file_id": file_id,
        "version_number": 1,
        "total_loan_costs": total_loan_costs,
        "seller_credits": seller_credits,
        "seller_days_owned": seller_days_owned,
        "prorated_tax_credit": Decimal("0.00"),
        "prorated_hoa_credit": Decimal("0.00"),
        "cash_to_close": Decimal("0.00"),
        "issued_at": None,
        "earliest_funding_at": None,
        "buyer_acknowledged_at": None,
        "status": "DRAFT",
        "triggering_change_kind": "NONE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    _refreeze_cash_to_close(cd)
    store.closing_disclosures[cid] = cd
    append_audit(
        escrow_file_id=file_id,
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="CD_CREATED",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/closing-disclosures/<cid>")
def read_cd(cid: str):
    user_id, role = require_role(["EscrowOfficer", "Buyer", "Seller"])
    cd = store.closing_disclosures.get(cid)
    if cd is None:
        raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
    if role in {"Buyer", "Seller"}:
        f = store.escrow_files.get(cd["escrow_file_id"])
        if role == "Buyer" and (not f or f["buyer_party_id"] != user_id):
            raise ApiError("ERR_FORBIDDEN_ROLE", "Buyer cannot read this CD.")
        if role == "Seller" and (not f or f["seller_party_id"] != user_id):
            raise ApiError("ERR_FORBIDDEN_ROLE", "Seller cannot read this CD.")
    return jsonify(success_envelope(serialize_cd(cd))), 200


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures/<cid>/issue")
def issue_cd(cid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        cd = store.closing_disclosures.get(cid)
        if cd is None:
            raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
        if cd["status"] not in {"DRAFT", "REVISED"}:
            raise ApiError("ERR_INVALID_STATE", "CD must be DRAFT or REVISED to issue.")
        check_version(cd, body)
        # Cross-entity precondition: parent file must be CONTINGENT_CD
        f = store.escrow_files.get(cd["escrow_file_id"])
        if f is None or f["status"] != "CONTINGENT_CD":
            raise ApiError(
                "ERR_CROSS_ENTITY_STATE",
                "EscrowFile must be in CONTINGENT_CD to issue a CD.",
            )
        is_reissue = cd["status"] == "REVISED"
        prior_change = cd.get("triggering_change_kind", "NONE")
        # Re-freeze cash_to_close on issuance.
        _refreeze_cash_to_close(cd)
        if is_reissue:
            cd["version_number"] = int(cd.get("version_number", 1)) + 1
        # Issued_at always advances to server_now on re-issue.
        cd["issued_at"] = now_ts(store.clock.now())
        if (not is_reissue) or prior_change in MAJOR_CHANGES or prior_change == "NONE":
            cd["earliest_funding_at"] = now_ts(add_three_business_days(store.clock.now()))
        elif prior_change == "FEE_DELTA_UNDER_THRESHOLD":
            # Preserve earliest_funding_at from prior version (no-op).
            pass
        else:
            cd["earliest_funding_at"] = now_ts(add_three_business_days(store.clock.now()))
        cd["status"] = "ISSUED"
        cd["triggering_change_kind"] = "NONE"  # reset on issue
        cd["updated_at"] = now_ts()
        cd["version"] = int(cd.get("version", 1)) + 1
        # Track who issued (for SoD).
        store.cd_issuer_by_escrow_file[cd["escrow_file_id"]] = user_id
    append_audit(
        escrow_file_id=cd["escrow_file_id"],
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="CD_ISSUED",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Acknowledge
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures/<cid>/acknowledge")
def acknowledge_cd(cid: str):
    user_id, _role = require_role(["Buyer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        cd = store.closing_disclosures.get(cid)
        if cd is None:
            raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
        f = store.escrow_files.get(cd["escrow_file_id"])
        if f is None or f["buyer_party_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Buyer can only acknowledge their own CD.")
        if cd["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "CD must be ISSUED to acknowledge.")
        check_version(cd, body)
        cd["status"] = "ACKNOWLEDGED"
        cd["buyer_acknowledged_at"] = now_ts(store.clock.now())
        cd["updated_at"] = now_ts()
        cd["version"] = int(cd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=cd["escrow_file_id"],
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="Buyer",
        action="CD_ACKNOWLEDGED",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Promote (cooling-off complete)
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures/<cid>/promote")
def promote_cd(cid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        cd = store.closing_disclosures.get(cid)
        if cd is None:
            raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
        if cd["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_INVALID_STATE", "CD must be ACKNOWLEDGED to promote.")
        check_version(cd, body)
        eligible_str = cd.get("earliest_funding_at")
        if not eligible_str:
            raise ApiError("ERR_CD_WAITING_PERIOD", "Cooling-off clock not initialized.")
        eligible_at = parse_iso_dt(eligible_str)
        if store.clock.now() < eligible_at:
            raise ApiError("ERR_CD_WAITING_PERIOD", "3-business-day cooling-off has not elapsed.")
        cd["status"] = "READY_TO_FUND"
        cd["updated_at"] = now_ts()
        cd["version"] = int(cd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=cd["escrow_file_id"],
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="CD_PROMOTED_READY_TO_FUND",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures/<cid>/revise")
def revise_cd(cid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        cd = store.closing_disclosures.get(cid)
        if cd is None:
            raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
        # PRD §2.6 / §3.5 — for the revise-vs-revise race on an ISSUED
        # disclosure, "the first writer wins on the
        # ClosingDisclosure.version row, and the second writer's
        # request is rejected with ERR_VERSION_MISMATCH". The OCC
        # version check therefore precedes the from-state check on
        # revise specifically: a stale `version` returns
        # ERR_VERSION_MISMATCH even if the row has already advanced
        # to REVISED.
        check_version(cd, body)
        if cd["status"] not in {"ISSUED", "ACKNOWLEDGED"}:
            raise ApiError("ERR_INVALID_STATE", "CD must be ISSUED or ACKNOWLEDGED to revise.")
        change_kind = require_enum(body, "triggering_change_kind", TRIGGERING_CHANGE_KINDS)
        # Optional updates
        if "total_loan_costs" in body and body["total_loan_costs"] is not None:
            cd["total_loan_costs"] = round_half_up_money(require_number(body, "total_loan_costs"))
        if "seller_credits" in body and body["seller_credits"] is not None:
            cd["seller_credits"] = round_half_up_money(require_number(body, "seller_credits"))
        if "seller_days_owned" in body and body["seller_days_owned"] is not None:
            cd["seller_days_owned"] = require_int(body, "seller_days_owned")
        prior_status = cd["status"]
        cd["status"] = "REVISED"
        cd["triggering_change_kind"] = change_kind
        if prior_status == "ACKNOWLEDGED":
            cd["buyer_acknowledged_at"] = None
        cd["updated_at"] = now_ts()
        cd["version"] = int(cd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=cd["escrow_file_id"],
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="CD_REVISED",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Void
# ---------------------------------------------------------------------------
@bp.post("/closing-disclosures/<cid>/void")
def void_cd(cid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        cd = store.closing_disclosures.get(cid)
        if cd is None:
            raise ApiError("ERR_NOT_FOUND", "Closing disclosure not found.")
        if cd["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE",
                "Only DRAFT CDs can be directly voided; cancel the file to void others.",
            )
        check_version(cd, body)
        cd["status"] = "VOIDED"
        cd["updated_at"] = now_ts()
        cd["version"] = int(cd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=cd["escrow_file_id"],
        subject_kind="CD",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="CD_VOIDED",
        payload_body=body,
    )
    response = success_envelope(serialize_cd(cd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
