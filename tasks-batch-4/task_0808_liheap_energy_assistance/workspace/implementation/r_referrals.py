"""Weatherization referral endpoints (§3.9)."""
from flask import request

from store import db, stamp_new, touch, public
from common import (
    endpoint, object_response, get_body, req_str, req_enum, opt_str, ApiError,
)
from calc import referral_priority
from helpers import get_path, get_ref, list_collection

REFERRAL_REASONS = {"HIGH_ENERGY_BURDEN", "TIER_1_AUTO", "VENDOR_REPORTED"}


def register(app):
    @app.route("/liheap/weatherization-referrals", methods=["POST"])
    @endpoint(["Caseworker"])
    def create_referral(role, user_id):
        body = get_body()
        household_id = req_str(body, "household_id")
        application_id = opt_str(body, "application_id", None)
        referral_reason = req_enum(body, "referral_reason", REFERRAL_REASONS)

        household = get_ref(db.households, household_id)
        if application_id is not None:
            get_ref(db.applications, application_id)

        referral = {
            "household_id": household_id,
            "application_id": application_id,
            "referral_reason": referral_reason,
            "priority": referral_priority(referral_reason,
                                          household["has_elderly_or_disabled"],
                                          household["has_child_under_6"]),
            "status": "REFERRED",
        }
        stamp_new(referral)
        db.weatherization_referrals[referral["id"]] = referral
        return object_response(public(referral), 201)

    @app.route("/liheap/weatherization-referrals/<id_>", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def get_referral(role, user_id, id_):
        referral = get_path(db.weatherization_referrals, id_)
        return object_response(public(referral), 200)

    @app.route("/liheap/weatherization-referrals", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def list_referrals(role, user_id):
        filters = {
            "household_id": request.args.get("household_id"),
            "application_id": request.args.get("application_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.weatherization_referrals, "weatherization_referrals", filters)

    @app.route("/liheap/weatherization-referrals/<id_>/schedule", methods=["POST"])
    @endpoint(["Caseworker"])
    def schedule_referral(role, user_id, id_):
        referral = get_path(db.weatherization_referrals, id_)
        if referral["status"] != "REFERRED":
            raise ApiError("ERR_INVALID_STATE", "Referral is not REFERRED")
        referral["status"] = "SCHEDULED"
        touch(referral)
        return object_response(public(referral), 200)
