"""Referral endpoints and compensation (PRD §3.6)."""
from flask import Blueprint

import clock
import serialize
from db import db, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import parse_pagination, paginate
from routes.lookup import get_path

bp = Blueprint("referrals", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider"]


@bp.route("/visits/<vid>/referrals", methods=["GET"])
def list_visit_referrals(vid):
    authorize(READ_ROLES)
    visit = get_path("visit", vid)
    limit, offset = parse_pagination()
    items = [r for r in db.referrals.values() if r["visit_id"] == visit["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.referral(r) for r in page], limit, offset, len(items))


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    authorize(READ_ROLES)
    referral = get_path("referral", rid)
    return ok_object(serialize.referral(referral))


@bp.route("/referrals/<rid>/accept", methods=["POST"])
def accept_referral(rid):
    authorize(["ClinicManager"])
    referral = get_path("referral", rid)
    if referral["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "referral not INITIATED")
    referral["status"] = "ACCEPTED"
    referral["accepted_at"] = clock.now()
    touch(referral)
    return ok_object(serialize.referral(referral))


@bp.route("/referrals/<rid>/cancel", methods=["POST"])
def cancel_referral(rid):
    authorize(["ClinicManager"])
    referral = get_path("referral", rid)
    if referral["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "referral not INITIATED")
    visit = db.visits.get(referral["visit_id"])
    if visit is None or visit["clinical_status"] != "TRANSFERRED":
        raise err("ERR_INVALID_STATE", "source visit not TRANSFERRED")

    referral["status"] = "CANCELLED"
    touch(referral)

    # Compensation: revert the source visit TRANSFERRED -> CHARTING, clear disposition.
    visit["clinical_status"] = "CHARTING"
    visit["disposition"] = None
    touch(visit)

    return ok_object(serialize.referral(referral))
