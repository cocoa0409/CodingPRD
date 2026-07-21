"""Donation intake, screening and the two state axes (PRD section 3.2, 3.7)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import domain

bp = Blueprint("donations", __name__)

INTAKE_CHANNELS = {"WEB", "PHONE", "PARTNER"}
CONDITIONS = {"EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE"}
EXCEPTION_TYPES = {"NONE", "MATERIAL_IMPROVEMENT", "GIFT_TO_NEEDY", "SIGNIFICANT_USE"}
DONATION_STATUSES = {
    "PENDING_REVIEW",
    "ACCEPTED",
    "PICKUP_BLOCKED",
    "IN_CUSTODY",
    "SOLD",
    "UNSOLD",
    "CLOSED",
    "DECLINED",
    "CANCELLED",
}
PAYOUT_STATUSES = {"PENDING", "ACCRUED", "REMITTED", "WITHHELD"}
ENTRY_TYPES = {
    "PROCEEDS_CREDIT",
    "PROGRAM_FEE_DEBIT",
    "TOW_COST_DEBIT",
    "ADMIN_FEE_DEBIT",
    "REVERSAL",
    "REMITTANCE_SETTLEMENT",
    "CHARITY_FEE_DEBIT",
}
TASK_TYPES = {"RECEIPT_DELIVERY", "PICKUP_ESCALATION", "TITLE_STALE", "REMITTANCE_PENDING"}
TASK_STATUSES = {"OPEN", "ESCALATED", "DONE"}

ALL_ROLES = (
    "IntakeAgent",
    "TitleClerk",
    "AuctionManager",
    "FinanceOfficer",
    "ProgramAdmin",
    "CharityAdmin",
    "Donor",
)


@bp.post("/api/donations")
def create_donation():
    mw.auth("IntakeAgent", "ProgramAdmin")
    data = mw.body()
    donor_id = mw.req_string(data, "donor_id")
    charity_id = mw.req_string(data, "charity_id")
    channel = mw.req_enum(data, "intake_channel", INTAKE_CHANNELS)
    condition = mw.req_enum(data, "declared_condition", CONDITIONS)
    pickup_required = mw.opt_bool(data, "pickup_required", True)

    donor = mw.resolve(db.donors, donor_id, "ERR_DONOR_NOT_FOUND")
    charity = mw.resolve(db.charities, charity_id, "ERR_CHARITY_NOT_FOUND")

    if donor["status"] != "ACTIVE":
        raise ApiError("ERR_DONOR_BLOCKED", "This donor is blocked.")
    if charity["status"] != "ACTIVE":
        raise ApiError("ERR_CHARITY_SUSPENDED", "This charity affiliate is suspended.")

    rec = db.new_record()
    rec["donor_id"] = donor_id
    rec["charity_id"] = charity_id
    rec["intake_channel"] = channel
    rec["declared_condition"] = condition
    rec["pickup_required"] = pickup_required
    rec["status"] = "PENDING_REVIEW"
    rec["payout_status"] = "PENDING"
    rec["pickup_attempts"] = 0
    rec["exception_type"] = "NONE"
    rec["fmv_estimate_cents"] = None
    rec["gross_proceeds_cents"] = 0
    rec["program_fee_cents"] = 0
    rec["tow_allowance_cents"] = 0
    rec["net_to_charity_cents"] = 0
    rec["deduction_amount_cents"] = None
    db.donations[rec["id"]] = rec

    donor["donation_count"] += 1
    db.touch(donor)
    return resp.created(rec)


@bp.get("/api/donations/<donation_id>")
def get_donation(donation_id):
    mw.auth(*ALL_ROLES)
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/donations")
def list_donations():
    user_id, role = mw.auth(*ALL_ROLES)
    donor_filter = request.args.get("donor_id")
    charity_filter = request.args.get("charity_id")

    if role == "Donor" and donor_filter is not None and donor_filter != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNER", "Donors may only list their own donations.")
    if role == "CharityAdmin" and charity_filter is not None and charity_filter != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_OWNER", "Charity admins may only list their own donations."
        )

    status = mw.query_enum("status", DONATION_STATUSES)
    payout_status = mw.query_enum("payout_status", PAYOUT_STATUSES)
    limit, offset = mw.pagination()

    rows = []
    for rec in db.donations.values():
        if donor_filter is not None and rec["donor_id"] != donor_filter:
            continue
        if charity_filter is not None and rec["charity_id"] != charity_filter:
            continue
        if status is not None and rec["status"] != status:
            continue
        if payout_status is not None and rec["payout_status"] != payout_status:
            continue
        rows.append(rec)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/donations/<donation_id>/accept")
def accept_donation(donation_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    if rec["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_DONATION_STATE", "Only a pending offer may be accepted.")
    donor = db.donors.get(rec["donor_id"])
    charity = db.charities.get(rec["charity_id"])
    if donor and donor["status"] != "ACTIVE":
        raise ApiError("ERR_DONOR_BLOCKED", "This donor is blocked.")
    if charity and charity["status"] != "ACTIVE":
        raise ApiError("ERR_CHARITY_SUSPENDED", "This charity affiliate is suspended.")

    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/decline")
def decline_donation(donation_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    if rec["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_DONATION_STATE", "Only a pending offer may be declined.")

    rec["status"] = "DECLINED"
    rec["payout_status"] = "WITHHELD"
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/cancel")
def cancel_donation(donation_id):
    user_id, role = mw.auth("Donor", "ProgramAdmin")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    if role == "Donor" and rec["donor_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNER", "This donation belongs to another donor.")
    data = mw.body()
    mw.req_string(data, "reason")
    if rec["status"] not in ("PENDING_REVIEW", "ACCEPTED"):
        raise ApiError(
            "ERR_INVALID_DONATION_STATE",
            "Only a pending or accepted donation may be cancelled.",
        )

    rec["status"] = "CANCELLED"
    db.touch(rec)

    donor = db.donors.get(rec["donor_id"])
    if donor:
        donor["donation_count"] -= 1
        db.touch(donor)

    for order in db.ordered(list(db.pickup_orders.values())):
        if order["donation_id"] != rec["id"] or order["status"] != "SCHEDULED":
            continue
        order["status"] = "CANCELLED"
        db.touch(order)
        vendor = db.tow_vendors.get(order["tow_vendor_id"])
        if vendor:
            vendor["booked_slots_count"] -= 1
            db.touch(vendor)
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/receive-dropoff")
def receive_dropoff(donation_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    if rec["status"] != "ACCEPTED" or rec["pickup_required"]:
        raise ApiError(
            "ERR_INVALID_DONATION_STATE",
            "Drop-off requires an accepted donation that expects no tow.",
        )
    rec["status"] = "IN_CUSTODY"
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/reset-pickup")
def reset_pickup(donation_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    if rec["status"] != "PICKUP_BLOCKED":
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "Only a blocked donation may be reset."
        )

    rec["status"] = "ACCEPTED"
    rec["pickup_attempts"] = 0
    db.touch(rec)
    domain.complete_tasks(rec["id"], "PICKUP_ESCALATION", "pickup reset")
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/withhold-payout")
def withhold_payout(donation_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    if rec["payout_status"] not in ("PENDING", "ACCRUED"):
        raise ApiError(
            "ERR_INVALID_PAYOUT_STATE", "The payout axis does not admit withholding."
        )
    was_accrued = rec["payout_status"] == "ACCRUED"
    if was_accrued and domain.is_settled(rec["id"]):
        raise ApiError(
            "ERR_DONATION_SETTLED", "This donation is frozen into a settled batch."
        )

    if was_accrued:
        charity = db.charities.get(rec["charity_id"])
        if charity:
            domain.reverse_accrual(rec, charity, "payout withheld")
    rec["payout_status"] = "WITHHELD"
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/donations/<donation_id>/exception")
def record_exception(donation_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    data = mw.body()
    exception_type = mw.req_enum(data, "exception_type", EXCEPTION_TYPES)
    rec["exception_type"] = exception_type
    db.touch(rec)
    return resp.ok(rec)


@bp.get("/api/donations/<donation_id>/ledger-entries")
def list_donation_ledger(donation_id):
    mw.auth("FinanceOfficer", "ProgramAdmin", "AuctionManager", "CharityAdmin")
    mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    entry_type = mw.query_enum("entry_type", ENTRY_TYPES)
    limit, offset = mw.pagination()
    rows = [
        e
        for e in domain.donation_entries(donation_id)
        if entry_type is None or e["entry_type"] == entry_type
    ]
    return resp.listing(rows, limit, offset)


@bp.get("/api/donations/<donation_id>/follow-up-tasks")
def list_donation_tasks(donation_id):
    mw.auth("IntakeAgent", "TitleClerk", "FinanceOfficer", "ProgramAdmin")
    mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    status = mw.query_enum("status", TASK_STATUSES)
    task_type = mw.query_enum("task_type", TASK_TYPES)
    limit, offset = mw.pagination()
    rows = []
    for task in domain.donation_tasks(donation_id):
        if status is not None and task["status"] != status:
            continue
        if task_type is not None and task["task_type"] != task_type:
            continue
        rows.append(task)
    return resp.listing(rows, limit, offset)
