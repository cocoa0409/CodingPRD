"""Entity -> response-dict serializers.

Records are stored as plain dicts shaped close to the output contract; serializers
return fresh dicts (omitting internal bookkeeping like _seq) so callers cannot
mutate the store and internal fields never leak into responses.

Order escrow figures are computed live from POSTED deposits / WIRED disbursements
(PRD §3.7) at serialize time so they always reflect the current ledger.
"""

from db import db


def serialize_agency(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "name": a["name"],
        "remit_split_pct": a["remit_split_pct"],
        "status": a["status"],
    }


def serialize_plant_record(p):
    # TitlePlantRecord carries only id + created_at (PRD §2.4): immutable, no
    # updated_at / version.
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "parcel_id": p["parcel_id"],
        "county": p["county"],
        "instrument_type": p["instrument_type"],
        "recorded_date": p["recorded_date"],
        "sequence_no": p["sequence_no"],
        "grantor": p["grantor"],
        "grantee": p["grantee"],
    }


def _order_escrow_figures(o):
    deposit_total = 0
    for d in db.deposits.values():
        if d["order_id"] == o["id"] and d["status"] == "POSTED":
            deposit_total += d["amount_cents"]
    disbursed_total = 0
    for d in db.disbursements.values():
        if d["order_id"] == o["id"] and d["status"] == "WIRED":
            disbursed_total += d["amount_cents"]
    return deposit_total, disbursed_total, deposit_total - disbursed_total


def serialize_order(o):
    deposit_total, disbursed_total, balance = _order_escrow_figures(o)
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "agency_id": o["agency_id"],
        "parcel_id": o["parcel_id"],
        "county": o["county"],
        "transaction_type": o["transaction_type"],
        "sales_price_cents": o["sales_price_cents"],
        "loan_amount_cents": o["loan_amount_cents"],
        "status": o["status"],
        "escrow_deposit_total_cents": deposit_total,
        "escrow_disbursed_total_cents": disbursed_total,
        "escrow_balance_cents": balance,
        "gap_open": o["gap_open"],
    }


def serialize_title_search(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "order_id": s["order_id"],
        "searched_parcel_id": s["searched_parcel_id"],
        "effective_date": s["effective_date"],
        "status": s["status"],
        "chain_verified": s["chain_verified"],
        "gap_from_date": s["gap_from_date"],
        "gap_to_date": s["gap_to_date"],
    }


def _commitment_open_exception_count(c):
    count = 0
    for e in db.exceptions.values():
        if e["commitment_id"] == c["id"] and e["status"] in ("RAISED", "CURATIVE_PENDING"):
            count += 1
    return count


def serialize_commitment(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "order_id": c["order_id"],
        "effective_date": c["effective_date"],
        "expiry_date": c["expiry_date"],
        "schedule_a_estate": c["schedule_a_estate"],
        "insured_amount_cents": c["insured_amount_cents"],
        "status": c["status"],
        "open_exception_count": _commitment_open_exception_count(c),
        "revision_no": c["revision_no"],
    }


def serialize_exception(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "commitment_id": e["commitment_id"],
        "exception_type": e["exception_type"],
        "description": e["description"],
        "curative_required": e["curative_required"],
        "status": e["status"],
    }


def serialize_policy(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "order_id": p["order_id"],
        "commitment_id": p["commitment_id"],
        "policy_type": p["policy_type"],
        "coverage_amount_cents": p["coverage_amount_cents"],
        "is_reissue": p["is_reissue"],
        "co_issued_with_owner": p["co_issued_with_owner"],
        "gross_premium_cents": p["gross_premium_cents"],
        "status": p["status"],
    }


def serialize_endorsement(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "policy_id": e["policy_id"],
        "form_code": e["form_code"],
        "charge_pct": e["charge_pct"],
        "charge_cents": e["charge_cents"],
        "status": e["status"],
    }


def serialize_deposit(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "order_id": d["order_id"],
        "amount_cents": d["amount_cents"],
        "source_ref": d["source_ref"],
        "status": d["status"],
    }


def serialize_disbursement(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "order_id": d["order_id"],
        "payee": d["payee"],
        "amount_cents": d["amount_cents"],
        "purpose": d["purpose"],
        "status": d["status"],
        "wire_window_start": d["wire_window_start"],
        "wire_window_end": d["wire_window_end"],
    }


def serialize_remittance(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "policy_id": r["policy_id"],
        "gross_premium_cents": r["gross_premium_cents"],
        "agency_retained_cents": r["agency_retained_cents"],
        "underwriter_remit_cents": r["underwriter_remit_cents"],
        "status": r["status"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "policy_id": c["policy_id"],
        "claim_type": c["claim_type"],
        "estimated_loss_cents": c["estimated_loss_cents"],
        "reserve_cents": c["reserve_cents"],
        "settled_loss_cents": c["settled_loss_cents"],
        "paid_cents": c["paid_cents"],
        "status": c["status"],
    }


def serialize_curative_action(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "order_id": c["order_id"],
        "subject_type": c["subject_type"],
        "subject_id": c["subject_id"],
        "action_type": c["action_type"],
        "status": c["status"],
    }
