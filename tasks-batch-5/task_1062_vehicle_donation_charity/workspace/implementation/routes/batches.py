"""Remittance batches: open, close, pay, dispute, reopen (PRD section 3.9)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import calc, domain

bp = Blueprint("batches", __name__)

BATCH_STATUSES = {"OPEN", "CLOSED", "PAID", "DISPUTED"}
ENTRY_TYPES = {
    "PROCEEDS_CREDIT",
    "PROGRAM_FEE_DEBIT",
    "TOW_COST_DEBIT",
    "ADMIN_FEE_DEBIT",
    "REVERSAL",
    "REMITTANCE_SETTLEMENT",
    "CHARITY_FEE_DEBIT",
}
READ_ROLES = ("FinanceOfficer", "ProgramAdmin", "CharityAdmin")


@bp.post("/api/remittance-batches")
def create_batch():
    mw.auth("FinanceOfficer")
    data = mw.body()
    charity_id = mw.req_string(data, "charity_id")
    start = mw.req_datetime(data, "period_start_utc")
    end = mw.req_datetime(data, "period_end_utc")

    charity = mw.resolve(db.charities, charity_id, "ERR_CHARITY_NOT_FOUND")
    if charity["status"] != "ACTIVE":
        raise ApiError("ERR_CHARITY_SUSPENDED", "This charity affiliate is suspended.")
    if end <= start:
        raise ApiError(
            "ERR_BATCH_PERIOD_INVALID", "The period end must be strictly after its start."
        )

    batch = domain.create_batch(charity_id, start, end)
    return resp.created(batch)


@bp.get("/api/remittance-batches/<batch_id>")
def get_batch(batch_id):
    mw.auth(*READ_ROLES)
    batch = mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")
    if batch["status"] == "OPEN":
        domain.refresh_provisional(batch)
    return resp.ok(batch)


@bp.get("/api/remittance-batches")
def list_batches():
    mw.auth(*READ_ROLES)
    charity_filter = request.args.get("charity_id")
    status = mw.query_enum("status", BATCH_STATUSES)
    limit, offset = mw.pagination()
    rows = []
    for batch in db.remittance_batches.values():
        if charity_filter is not None and batch["charity_id"] != charity_filter:
            continue
        if status is not None and batch["status"] != status:
            continue
        rows.append(batch)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.get("/api/remittance-batches/<batch_id>/ledger-entries")
def list_batch_ledger(batch_id):
    mw.auth(*READ_ROLES)
    mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")
    entry_type = mw.query_enum("entry_type", ENTRY_TYPES)
    limit, offset = mw.pagination()
    rows = [
        e
        for e in domain.batch_entries(batch_id)
        if entry_type is None or e["entry_type"] == entry_type
    ]
    return resp.listing(rows, limit, offset)


@bp.post("/api/remittance-batches/<batch_id>/close")
def close_batch(batch_id):
    user_id, _role = mw.auth("FinanceOfficer")
    batch = mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")

    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Only an open batch may be closed.")
    charity = db.charities.get(batch["charity_id"])
    if charity is not None and charity["status"] != "ACTIVE":
        raise ApiError("ERR_CHARITY_SUSPENDED", "This charity affiliate is suspended.")

    members = domain.eligible_members(batch)
    if not members:
        raise ApiError("ERR_BATCH_EMPTY", "The batch has no eligible member donations.")

    pct = charity["remittance_fee_pct"] if charity else 0
    gross = sum(d["net_to_charity_cents"] for d in members)
    fees = {d["id"]: calc.line_fee(d["net_to_charity_cents"], pct) for d in members}
    fee_total = sum(fees.values())

    batch["status"] = "CLOSED"
    batch["donation_count"] = len(members)
    batch["gross_cents"] = gross
    batch["fee_cents"] = fee_total
    batch["net_cents"] = gross - fee_total
    batch["closed_by_user_id"] = user_id
    batch["_member_ids"] = [d["id"] for d in members]
    batch["_member_fees"] = fees
    db.touch(batch)

    for donation in members:
        domain.append_entry(
            "REMITTANCE_SETTLEMENT",
            "DEBIT",
            donation["net_to_charity_cents"],
            "settlement of donation net into remittance batch",
            donation_id=donation["id"],
            remittance_batch_id=batch["id"],
        )
    domain.append_entry(
        "CHARITY_FEE_DEBIT",
        "DEBIT",
        fee_total,
        "program fee retained on remittance batch",
        donation_id=None,
        remittance_batch_id=batch["id"],
    )
    return resp.ok(batch)


@bp.post("/api/remittance-batches/<batch_id>/pay")
def pay_batch(batch_id):
    user_id, _role = mw.auth("FinanceOfficer")
    batch = mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")
    data = mw.body()
    payment_reference = mw.req_string(data, "payment_reference")
    expected_version = mw.req_int(data, "expected_batch_version")

    if batch["closed_by_user_id"] is not None and user_id == batch["closed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who closed a batch may not pay it.",
        )
    if expected_version != batch["version"]:
        raise ApiError(
            "ERR_STALE_BATCH_VERSION", "The batch has advanced since it was read."
        )
    if batch["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Only a closed batch may be paid.")

    members = [
        db.donations[did] for did in batch["_member_ids"] if did in db.donations
    ]
    for donation in members:
        if donation["payout_status"] != "ACCRUED":
            raise ApiError(
                "ERR_INVALID_PAYOUT_STATE",
                "A member donation is no longer in the accrued state.",
            )

    batch["status"] = "PAID"
    batch["paid_by_user_id"] = user_id
    batch["payment_reference"] = payment_reference
    db.touch(batch)

    charity = db.charities.get(batch["charity_id"])
    for donation in members:
        donation["payout_status"] = "REMITTED"
        db.touch(donation)
        if charity is not None:
            share = donation["net_to_charity_cents"] - batch["_member_fees"].get(
                donation["id"], 0
            )
            charity["pledged_balance_cents"] -= donation["net_to_charity_cents"]
            charity["remitted_balance_cents"] += share
            db.touch(charity)
        domain.complete_tasks(donation["id"], "REMITTANCE_PENDING", "batch paid")
    return resp.ok(batch)


@bp.post("/api/remittance-batches/<batch_id>/dispute")
def dispute_batch(batch_id):
    user_id, _role = mw.auth("CharityAdmin")
    batch = mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")
    if batch["charity_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNER", "This batch belongs to another charity.")
    data = mw.body()
    dispute_reason = mw.req_string(data, "dispute_reason")
    if batch["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Only a closed batch may be disputed.")

    batch["status"] = "DISPUTED"
    batch["dispute_reason"] = dispute_reason
    db.touch(batch)
    return resp.ok(batch)


@bp.post("/api/remittance-batches/<batch_id>/reopen")
def reopen_batch(batch_id):
    mw.auth("FinanceOfficer")
    batch = mw.resolve(db.remittance_batches, batch_id, "ERR_BATCH_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    if batch["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Only a disputed batch may be reopened.")

    for entry_id in [
        e["id"]
        for e in db.ledger_entries.values()
        if e["remittance_batch_id"] == batch["id"]
        and e["entry_type"] in ("REMITTANCE_SETTLEMENT", "CHARITY_FEE_DEBIT")
    ]:
        del db.ledger_entries[entry_id]

    batch["status"] = "OPEN"
    batch["donation_count"] = 0
    batch["gross_cents"] = 0
    batch["fee_cents"] = 0
    batch["net_cents"] = 0
    batch["closed_by_user_id"] = None
    batch["_member_ids"] = []
    batch["_member_fees"] = {}
    db.touch(batch)
    return resp.ok(batch)
