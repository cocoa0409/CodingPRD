"""Dog endpoints: register, list, read, verify/reject, resubmit."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_MEMBER_NOT_FOUND, ERR_DOG_NOT_FOUND,
    ERR_NOT_OWNER, ERR_DOG_NOT_VERIFIABLE, ERR_DOG_NOT_RESUBMITTABLE,
    ERR_VACCINATION_EXPIRED,
)
from helpers import (
    get_body, req_string, req_enum, parse_date, today,
    parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("dogs", __name__)


def _get_member_or_404(member_id):
    member = store.members.get(member_id)
    if member is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, 404, "Member not found")
    return member


def _get_dog_or_404(dog_id):
    dog = store.dogs.get(dog_id)
    if dog is None:
        raise ApiError(ERR_DOG_NOT_FOUND, 404, "Dog not found")
    return dog


@bp.route("/dog-park/members/<memberId>/dogs", methods=["POST"])
def register_dog(memberId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members register dogs only on their own account")
    body = get_body()
    name = req_string(body, "name")
    size_class = req_enum(body, "size_class", ("SMALL", "LARGE"))
    license_number = req_string(body, "license_number")
    vaccination = req_string(body, "vaccination_expires_on")
    if parse_date(vaccination) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "vaccination_expires_on must be an ISO date YYYY-MM-DD")
    _get_member_or_404(memberId)
    dog = domain.new_entity(store.dogs, {
        "member_id": memberId,
        "name": name,
        "size_class": size_class,
        "license_number": license_number,
        "vaccination_expires_on": vaccination,
        "verification_status": "SUBMITTED",
        "rejection_reason": None,
    })
    return ok(domain.public(dog), 201)


@bp.route("/dog-park/members/<memberId>/dogs", methods=["GET"])
def list_dogs(memberId):
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members may only list their own dogs")
    limit, offset = parse_pagination()
    _get_member_or_404(memberId)
    dogs = [d for d in store.dogs.values() if d["member_id"] == memberId]
    page, meta = slice_page(dogs, limit, offset)
    return ok([domain.public(d) for d in page], 200, meta)


@bp.route("/dog-park/dogs/<dogId>", methods=["GET"])
def get_dog(dogId):
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    dog = _get_dog_or_404(dogId)
    if role == "Member" and dog["member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members may only read their own dogs")
    return ok(domain.public(dog))


@bp.route("/dog-park/dogs/<dogId>/verify", methods=["POST"])
def verify_dog(dogId):
    require_auth(["ParkAdmin"])
    body = get_body()
    decision = req_enum(body, "decision", ("VERIFIED", "REJECTED"))
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason must be a string or null")
    dog = _get_dog_or_404(dogId)
    # Stage 8 state precondition before stage 9 vaccination currency.
    if dog["verification_status"] != "SUBMITTED":
        raise ApiError(ERR_DOG_NOT_VERIFIABLE, 409,
                       "Verify requires a dog in SUBMITTED status")
    if decision == "VERIFIED":
        expires = parse_date(dog["vaccination_expires_on"])
        if expires is None or expires < today():
            raise ApiError(ERR_VACCINATION_EXPIRED, 422,
                           "vaccination_expires_on is before the current date")
        dog["verification_status"] = "VERIFIED"
    else:
        dog["verification_status"] = "REJECTED"
        dog["rejection_reason"] = reason
    domain.touch(dog)
    return ok(domain.public(dog))


@bp.route("/dog-park/dogs/<dogId>/resubmit", methods=["POST"])
def resubmit_dog(dogId):
    uid, role = require_auth(["Member"])
    body = get_body()
    vaccination = req_string(body, "vaccination_expires_on")
    new_expiry = parse_date(vaccination)
    if new_expiry is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "vaccination_expires_on must be an ISO date YYYY-MM-DD")
    license_number = req_string(body, "license_number")
    dog = _get_dog_or_404(dogId)
    if dog["member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members may only resubmit their own dogs")
    if dog["verification_status"] not in ("REJECTED", "EXPIRED"):
        raise ApiError(ERR_DOG_NOT_RESUBMITTABLE, 409,
                       "Resubmit requires REJECTED or EXPIRED status")
    if new_expiry < today():
        raise ApiError(ERR_VACCINATION_EXPIRED, 422,
                       "vaccination_expires_on is before the current date")
    dog["vaccination_expires_on"] = vaccination
    dog["license_number"] = license_number
    dog["verification_status"] = "SUBMITTED"
    dog["rejection_reason"] = None
    domain.touch(dog)
    return ok(domain.public(dog))
