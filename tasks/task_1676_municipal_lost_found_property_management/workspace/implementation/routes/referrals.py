"""Law-enforcement referral cases (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from validate import (
    require_path, pagination_params, opt_query_enum, opt_query_str, paginate,
)

bp = Blueprint("referrals", __name__)

LIAISON = {"PoliceLiaison"}


@bp.get("/referrals")
def list_referrals():
    limit, offset = pagination_params()
    item_id = opt_query_str("item_id")
    status = opt_query_enum("status", core.REFERRAL_STATUSES)
    authorized(STAFF_ROLES)
    recs = list(db["referrals"].values())
    if item_id is not None:
        recs = [r for r in recs if r["item_id"] == item_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/referrals/<referral_id>")
def get_referral(referral_id):
    authorized(STAFF_ROLES)
    rec = require_path("referrals", referral_id)
    return success_object(rec)


@bp.post("/referrals/<referral_id>/confirm-pickup")
def confirm_pickup(referral_id):
    authorized(LIAISON)
    referral = require_path("referrals", referral_id)
    item = db["items"].get(referral["item_id"])
    if referral["status"] != "REFERRED" or item is None or item["status"] != "REFERRED_TO_LE":
        raise_error(ERR_INVALID_STATE,
                    "pickup requires referral REFERRED and item REFERRED_TO_LE")
    referral["status"] = "IN_CUSTODY"
    core.touch(referral)
    item["status"] = "IN_LE_CUSTODY"  # frees the storage slot (PRD 2.9)
    core.touch(item)
    return success_object(referral)


@bp.post("/referrals/<referral_id>/return-to-custody")
def return_to_custody(referral_id):
    authorized(LIAISON)
    referral = require_path("referrals", referral_id)
    item = db["items"].get(referral["item_id"])
    if referral["status"] != "IN_CUSTODY" or item is None or item["status"] != "IN_LE_CUSTODY":
        raise_error(ERR_INVALID_STATE,
                    "return requires referral IN_CUSTODY and item IN_LE_CUSTODY")
    referral["status"] = "RETURNED"
    core.touch(referral)
    item["status"] = "STORED"  # re-occupies the storage slot
    core.touch(item)
    # Restore each STAYED claim to its captured pre_stay_status (3.6).
    for claim in db["claims"].values():
        if claim["item_id"] == item["id"] and claim["status"] == "STAYED":
            claim["status"] = claim["pre_stay_status"]
            claim["pre_stay_status"] = None
            core.touch(claim)
    return success_object(referral)


@bp.post("/referrals/<referral_id>/convert-to-evidence")
def convert_to_evidence(referral_id):
    authorized(LIAISON)
    referral = require_path("referrals", referral_id)
    item = db["items"].get(referral["item_id"])
    if referral["status"] != "IN_CUSTODY" or item is None or item["status"] != "IN_LE_CUSTODY":
        raise_error(ERR_INVALID_STATE,
                    "conversion requires referral IN_CUSTODY and item IN_LE_CUSTODY")
    referral["status"] = "CONVERTED_TO_EVIDENCE"
    core.touch(referral)
    item["status"] = "EVIDENCE"
    core.touch(item)
    # Auto-reject every open or stayed claim on the item (3.6).
    for claim in db["claims"].values():
        if claim["item_id"] == item["id"] and claim["status"] in (
            "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "STAYED",
        ):
            claim["status"] = "REJECTED"
            claim["decision_reason"] = "ITEM_EVIDENCE"
            core.touch(claim)
    return success_object(referral)
