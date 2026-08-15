"""Airline routes: create, get."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util

bp = Blueprint("airlines", __name__)


@bp.route("/deice-ops/airlines", methods=["POST"])
def create_airline():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["code", "name", "credit_limit_cents"])
    code = payload["code"]
    if not isinstance(code, str) or not code:
        raise errors.invalid_request("code must be a non-empty string")
    name = payload["name"]
    if not isinstance(name, str) or not name:
        raise errors.invalid_request("name must be a non-empty string")
    credit_limit_cents = util.to_int(payload["credit_limit_cents"], "credit_limit_cents")
    if credit_limit_cents < 0:
        raise errors.invalid_request("credit_limit_cents must be >= 0")
    for a in db.airlines.values():
        if a["code"] == code:
            raise errors.invalid_request("code must be unique")
    now = util.iso_now()
    airline = {
        "id": util.new_id(),
        "code": code,
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "monthly_billed_liters": 0,
        "month_key": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    airline["_created_dt"] = db.get_clock()
    db.airlines[airline["id"]] = airline
    return response.success_object(serializers.airline(airline), 201)


@bp.route("/deice-ops/airlines/<aid>", methods=["GET"])
def get_airline(aid):
    user_id, role = middleware.require_roles("StationAdmin", "AirlineRep", "BillingClerk")
    airline = db.airlines.get(aid)
    if airline is None:
        raise errors.not_found("airline not found")
    if role == "AirlineRep":
        middleware.require_own_airline(user_id, airline["id"])
    return response.success_object(serializers.airline(airline), 200)
