"""Domain control validation (PRD 3.4)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import cascade
from services.lookup import get_authorization, get_profile, get_subscriber
from validation import DCV_METHODS, check_domain_name, enum_value, req_str

bp = Blueprint("authorizations", __name__)

LIVE_STATES = ("PENDING", "VALIDATED")


@bp.route("/ca/domain-authorizations", methods=["POST"])
def create_authorization():
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    subscriber_id = req_str(body, "subscriber_id")
    profile_id = req_str(body, "profile_id")
    domain_name = req_str(body, "domain_name")
    method = req_str(body, "method")
    check_domain_name(domain_name)
    enum_value(method, DCV_METHODS, "method")

    profile = get_profile(profile_id)
    subscriber = get_subscriber(subscriber_id)

    if profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE.")
    if subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")

    if method not in profile["allowed_dcv_methods"]:
        fail("ERR_DCV_METHOD_NOT_ALLOWED", "The profile does not approve method %s." % method)

    for existing in db.authorizations.values():
        if (existing["subscriber_id"] == subscriber["id"]
                and existing["profile_id"] == profile["id"]
                and existing["domain_name"] == domain_name
                and existing["state"] in LIVE_STATES):
            fail(
                "ERR_AUTHORIZATION_ALREADY_OPEN",
                "A live authorization already exists for this subscriber, profile and domain.",
            )

    record = make_record({
        "subscriber_id": subscriber["id"],
        "profile_id": profile["id"],
        "domain_name": domain_name,
        "method": method,
        "challenge_token": db.next_challenge_token(),
        "state": "PENDING",
        "attempt_count": 0,
        "validated_at": None,
        "expires_at": None,
        "reuse_count": 0,
        "invalidated_at": None,
        "invalidation_count": 0,
    })
    db.authorizations[record["id"]] = record
    return created(public(record))


@bp.route("/ca/domain-authorizations", methods=["GET"])
def list_authorizations():
    read_only(ALL_ROLES)
    records = apply_filters(db.authorizations.values(), {
        "subscriber_id": "str",
        "profile_id": "str",
        "domain_name": "str",
        "state": "str",
        "method": "str",
    })
    return paginated(sort_records(records))


@bp.route("/ca/domain-authorizations/<authorization_id>", methods=["GET"])
def get_one_authorization(authorization_id):
    read_only(ALL_ROLES)
    return ok(public(get_authorization(authorization_id)))


@bp.route("/ca/domain-authorizations/<authorization_id>/validate", methods=["POST"])
def validate_authorization(authorization_id):
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    token = req_str(body, "challenge_token")

    auth = get_authorization(authorization_id)
    profile = db.profiles.get(auth["profile_id"])
    subscriber = db.subscribers.get(auth["subscriber_id"])

    if profile is not None and profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE.")
    if subscriber is not None and subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")
    if auth["state"] not in ("PENDING", "FAILED"):
        fail("ERR_AUTHORIZATION_NOT_VALIDATABLE", "The authorization cannot be validated.")

    auth["attempt_count"] += 1
    if token == auth["challenge_token"]:
        now = db.now()
        auth["state"] = "VALIDATED"
        auth["validated_at"] = now
        auth["expires_at"] = now + datetime.timedelta(days=profile["dcv_reuse_days"])
    elif auth["attempt_count"] >= 3:
        auth["state"] = "EXHAUSTED"
    else:
        auth["state"] = "FAILED"
    touch(auth)
    return ok(public(auth))


@bp.route("/ca/domain-authorizations/<authorization_id>/invalidate", methods=["POST"])
def invalidate_authorization(authorization_id):
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    req_str(body, "reason")

    auth = get_authorization(authorization_id)
    if auth["state"] != "VALIDATED":
        fail("ERR_AUTHORIZATION_NOT_VALIDATED", "Only a VALIDATED authorization may be invalidated.")

    cascade.cascade_invalidated_authorization(auth)

    auth["state"] = "PENDING"
    auth["invalidated_at"] = db.now()
    auth["invalidation_count"] += 1
    auth["attempt_count"] = 0
    auth["validated_at"] = None
    auth["expires_at"] = None
    auth["challenge_token"] = db.next_challenge_token()
    touch(auth)
    return ok(public(auth))
