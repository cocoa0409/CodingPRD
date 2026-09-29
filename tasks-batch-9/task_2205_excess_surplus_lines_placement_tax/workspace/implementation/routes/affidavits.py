"""Broker affidavits and the compliance-officer separation (PRD 3.6, 2.12)."""

from flask import Blueprint

import auth
import clock
import serialize
import store
import validation
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("affidavits", __name__)

AFFIDAVIT_TYPES = ("DILIGENT_SEARCH", "PREMIUM_TAX")
CLEARING_STATUSES = ("APPROVED", "CONDITIONAL")


@bp.post("/policies/<rec_id>/affidavits")
def create_affidavit(rec_id):
    auth.require("PlacementBroker")
    policy = auth.path_entity("policies", "policy", rec_id)
    data = validation.body()
    affidavit_type = validation.req_enum(data, "affidavit_type", AFFIDAVIT_TYPES)
    attested = validation.req_int(data, "declination_count_attested", minimum=0)
    auth.check_owner(policy.get("broker_id"))

    rec = db.insert("affidavits", {
        "policy_id": policy["id"],
        "affidavit_type": affidavit_type,
        "declination_count_attested": attested,
        "status": "DRAFT",
        "signed_by_user_id": None,
        "signed_at": None,
    })
    return created(serialize.public(rec))


@bp.get("/policies/<rec_id>/affidavits")
def list_affidavits(rec_id):
    auth.require(auth.ANY)
    policy = auth.path_entity("policies", "policy", rec_id)
    rows = filtered(store.where("affidavits", policy_id=policy["id"]),
                    affidavit_type=arg("affidavit_type"), status=arg("status"))
    return list_response(rows)


def _cleared_the_carrier(user_id, carrier_id):
    """True when this principal decided any APPROVED or CONDITIONAL review of the
    carrier — every such review counts, not merely the most recent one."""
    for review in store.reviews_of_carrier(carrier_id):
        if review.get("status") not in CLEARING_STATUSES:
            continue
        if review.get("reviewer_user_id") == user_id:
            return True
    return False


@bp.post("/affidavits/<rec_id>/sign")
def sign_affidavit(rec_id):
    auth.require("PlacementBroker", "ComplianceOfficer")
    rec = auth.path_entity("affidavits", "affidavit", rec_id)
    policy = db.get("policies", rec.get("policy_id"))
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")

    # Rung 7 applies to the broker only; a compliance officer holds no brokerage.
    auth.check_owner(policy.get("broker_id"))

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT affidavit may be signed.")

    if _cleared_the_carrier(auth.user_id(), policy.get("carrier_id")):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A reviewer who cleared this carrier may not sign the "
                       "affidavit.")

    placement = db.get("placements", policy.get("placement_id"))
    expected = int((placement or {}).get("declination_count") or 0)
    if int(rec.get("declination_count_attested") or 0) != expected:
        raise ApiError("ERR_AFFIDAVIT_COUNT_MISMATCH",
                       "The attested declination count does not match the "
                       "placement's recorded count of %d." % expected)

    rec["signed_by_user_id"] = auth.user_id()
    rec["signed_at"] = clock.now_raw()
    rec["status"] = "SIGNED"
    touch(rec)

    if rec.get("affidavit_type") == "DILIGENT_SEARCH" \
            and policy.get("compliance_status") == "NOTICES_AFFIXED":
        policy["compliance_status"] = "COMPLIANT"
        touch(policy)

    return ok(serialize.public(rec))
