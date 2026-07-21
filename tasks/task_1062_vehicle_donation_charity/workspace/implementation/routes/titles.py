"""Title clearance through the DMV (PRD section 3.4)."""

import uuid

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import domain

bp = Blueprint("titles", __name__)

TITLE_STATES = {"DRAFT", "SUBMITTED", "CLEARED", "REJECTED", "ABANDONED"}
READ_ROLES = ("TitleClerk", "ProgramAdmin", "AuctionManager", "FinanceOfficer")
SUBMITTABLE_DONATION_STATES = ("ACCEPTED", "PICKUP_BLOCKED", "IN_CUSTODY", "UNSOLD")


def _mint_reference():
    return "DMV-" + uuid.uuid4().hex[:12].upper()


@bp.post("/api/title-records")
def create_title_record():
    mw.auth("TitleClerk")
    data = mw.body()
    donation_id = mw.req_string(data, "donation_id")
    title_number = mw.req_string(data, "title_number")
    owner_name = mw.req_string(data, "owner_name")
    lien_holder = mw.opt_string(data, "lien_holder", None)

    mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    if domain.title_for_donation(donation_id) is not None:
        raise ApiError(
            "ERR_DUPLICATE_TITLE_RECORD", "This donation already has a title record."
        )

    rec = db.new_record()
    rec["donation_id"] = donation_id
    rec["title_number"] = title_number
    rec["owner_name"] = owner_name
    rec["lien_holder"] = lien_holder
    rec["state"] = "DRAFT"
    rec["rejection_count"] = 0
    rec["rejection_reason"] = None
    rec["dmv_filing_reference"] = None
    rec["submitted_at_utc"] = None
    db.title_records[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/title-records/<record_id>")
def get_title_record(record_id):
    mw.auth(*READ_ROLES)
    rec = mw.resolve(db.title_records, record_id, "ERR_TITLE_RECORD_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/title-records")
def list_title_records():
    mw.auth(*READ_ROLES)
    donation_filter = request.args.get("donation_id")
    state = mw.query_enum("state", TITLE_STATES)
    limit, offset = mw.pagination()
    rows = []
    for rec in db.title_records.values():
        if donation_filter is not None and rec["donation_id"] != donation_filter:
            continue
        if state is not None and rec["state"] != state:
            continue
        rows.append(rec)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/title-records/<record_id>/submit-dmv")
def submit_dmv(record_id):
    mw.auth("TitleClerk")
    rec = mw.resolve(db.title_records, record_id, "ERR_TITLE_RECORD_NOT_FOUND")
    if rec["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_TITLE_STATE", "Only a draft title may be filed.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] not in SUBMITTABLE_DONATION_STATES:
        raise ApiError(
            "ERR_INVALID_DONATION_STATE",
            "The donation's disposition does not admit a DMV filing.",
        )

    rec["state"] = "SUBMITTED"
    rec["dmv_filing_reference"] = _mint_reference()
    rec["submitted_at_utc"] = db.now()
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/title-records/<record_id>/dmv-decision")
def dmv_decision(record_id):
    mw.auth("TitleClerk")
    rec = mw.resolve(db.title_records, record_id, "ERR_TITLE_RECORD_NOT_FOUND")
    data = mw.body()
    outcome = mw.req_enum(data, "outcome", {"CLEARED", "REJECTED"})
    rejection_reason = mw.opt_string(data, "rejection_reason", None)
    if rec["state"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_TITLE_STATE", "Only a submitted title may receive a decision."
        )

    if outcome == "CLEARED":
        rec["state"] = "CLEARED"
    else:
        rec["state"] = "REJECTED"
        rec["rejection_count"] += 1
        rec["rejection_reason"] = rejection_reason
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/title-records/<record_id>/resubmit")
def resubmit_title(record_id):
    mw.auth("TitleClerk")
    rec = mw.resolve(db.title_records, record_id, "ERR_TITLE_RECORD_NOT_FOUND")
    data = mw.body()
    title_number = mw.opt_string(data, "title_number", rec["title_number"], nullable=False)
    owner_name = mw.opt_string(data, "owner_name", rec["owner_name"], nullable=False)
    if rec["state"] != "REJECTED":
        raise ApiError("ERR_INVALID_TITLE_STATE", "Only a rejected title may be refiled.")
    if rec["rejection_count"] > db.TITLE_RESUBMIT_LIMIT:
        raise ApiError(
            "ERR_TITLE_RESUBMIT_LIMIT", "This title has exhausted its resubmission budget."
        )

    rec["title_number"] = title_number
    rec["owner_name"] = owner_name
    rec["state"] = "SUBMITTED"
    rec["dmv_filing_reference"] = _mint_reference()
    rec["submitted_at_utc"] = db.now()
    db.touch(rec)
    return resp.ok(rec)


@bp.post("/api/title-records/<record_id>/abandon")
def abandon_title(record_id):
    mw.auth("TitleClerk")
    rec = mw.resolve(db.title_records, record_id, "ERR_TITLE_RECORD_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    if rec["state"] != "REJECTED":
        raise ApiError("ERR_INVALID_TITLE_STATE", "Only a rejected title may be abandoned.")

    rec["state"] = "ABANDONED"
    db.touch(rec)
    domain.create_task(
        rec["donation_id"],
        "TITLE_STALE",
        "TitleClerk",
        db.now() + db.days(db.REMITTANCE_FOLLOWUP_DAYS),
    )
    return resp.ok(rec)
