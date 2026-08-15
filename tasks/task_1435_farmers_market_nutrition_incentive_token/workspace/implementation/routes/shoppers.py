"""Shopper endpoints: enroll, read (self for Shopper role), verify, suspend."""

from flask import Blueprint

from db import STORE, stamp_new, touch
from errors import (
    ApiError,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
)
from middleware import ensure_valid_json, req_enum, req_str
from response import success_object
from routes.common import Pipeline, get_path_entity, ref_exists
from services.domain import serialize_shopper

bp = Blueprint("shoppers", __name__)


@bp.route("/shoppers", methods=["POST"])
def create_shopper():
    pipe = Pipeline(["BoothOperator"], is_write=True)
    body = pipe.body
    ref_exists("programs", body.get("program_id"))
    ensure_valid_json(body)
    program_id = req_str(body, "program_id")
    external_benefit_ref = req_str(body, "external_benefit_ref")
    benefit_type = req_enum(body, "benefit_type", {"SNAP", "WIC", "SENIOR"})
    # Priority 25: external_benefit_ref unique among non-SUSPENDED shoppers
    # of the same program.
    for other in STORE["shoppers"].values():
        if (
            other["program_id"] == program_id
            and other["external_benefit_ref"] == external_benefit_ref
            and other["status"] != "SUSPENDED"
        ):
            raise ApiError(ERR_DUPLICATE_ENROLLMENT, 409,
                           "external_benefit_ref already enrolled in this program")
    shopper = stamp_new({
        "program_id": program_id,
        "external_benefit_ref": external_benefit_ref,
        "benefit_type": benefit_type,
        "status": "ENROLLED",
    })
    STORE["shoppers"][shopper["id"]] = shopper
    env, status = success_object(serialize_shopper(shopper), 201)
    pipe.commit(status, env.get_json())
    return env, status


@bp.route("/shoppers/<sid>", methods=["GET"])
def get_shopper(sid):
    pipe = Pipeline(
        ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor", "Shopper"],
        is_write=False,
    )
    shopper = get_path_entity("shoppers", sid)
    if pipe.role == "Shopper" and pipe.user_id != shopper["id"]:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "A shopper may only read its own record")
    return success_object(serialize_shopper(shopper))


@bp.route("/shoppers/<sid>/verify", methods=["POST"])
def verify_shopper(sid):
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    shopper = get_path_entity("shoppers", sid)
    if shopper["status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Shopper in status {shopper['status']} cannot be verified")
    shopper["status"] = "ACTIVE"
    touch(shopper)
    env, status = success_object(serialize_shopper(shopper), 200)
    pipe.commit(status, env.get_json())
    return env, status


@bp.route("/shoppers/<sid>/suspend", methods=["POST"])
def suspend_shopper(sid):
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    shopper = get_path_entity("shoppers", sid)
    if shopper["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Shopper in status {shopper['status']} cannot be suspended")
    shopper["status"] = "SUSPENDED"
    touch(shopper)
    env, status = success_object(serialize_shopper(shopper), 200)
    pipe.commit(status, env.get_json())
    return env, status
