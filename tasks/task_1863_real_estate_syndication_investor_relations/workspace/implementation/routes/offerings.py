"""Offering lifecycle (PRD 3.2)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_offering
from services import domain
from services.domain import stamp_new, touch, sorted_items
from validate import (
    get_body, req_int, req_str, opt_number, opt_version, pagination, apply_filters,
)

bp = Blueprint("offerings", __name__)
RS = {"strict_slashes": False}


@bp.route("/syndications/<syndicationId>/offerings", methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_offering(caller, syndicationId):
    resolve.syndication(syndicationId)
    body = get_body()
    property_id = req_str(body, "property_id")
    resolve.property_(property_id)
    o = {
        "syndication_id": syndicationId,
        "property_id": property_id,
        "offering_name": req_str(body, "offering_name"),
        "target_raise_cents": req_int(body, "target_raise_cents", minimum=0),
        "min_subscription_cents": req_int(body, "min_subscription_cents", minimum=0),
        "max_non_accredited_count": req_int(body, "max_non_accredited_count", minimum=0),
        "preferred_return_pct_annual": opt_number(body, "preferred_return_pct_annual", minimum=0),
        "carried_interest_pct": opt_number(body, "carried_interest_pct", minimum=0),
        "total_distributed_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(o)
    db["offerings"][o["id"]] = o
    return success_object(ser_offering(o), 201)


@bp.route("/syndications/<syndicationId>/offerings", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_offerings(caller, syndicationId):
    resolve.syndication(syndicationId)
    limit, offset = pagination()
    items = [o for o in db["offerings"].values() if o["syndication_id"] == syndicationId]
    items = apply_filters(sorted_items(items), {"status": "status"})
    page = items[offset:offset + limit]
    return success_list([ser_offering(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_offering(caller, syndicationId, offeringId):
    return success_object(ser_offering(resolve.offering(syndicationId, offeringId)))


def _check_version(body, off):
    opt_version(body, "expected_offering_version", off["version"],
                "ERR_STALE_OFFERING_VERSION")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/open", methods=["POST"], **RS)
@endpoint(SPONSOR)
def open_offering(caller, syndicationId, offeringId):
    syn = resolve.syndication(syndicationId)
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    _check_version(body, off)
    if off["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot open an offering in status {off['status']}")
    if syn["status"] != "ACTIVE":
        raise_error("ERR_SYNDICATION_NOT_ACTIVE", "syndication must be ACTIVE to open an offering")
    prop = db["properties"].get(off["property_id"])
    if prop is None or prop["status"] != "OWNED":
        raise_error("ERR_PROPERTY_NOT_OWNED", "property must be OWNED to open an offering")
    # Economics freeze at open: copy syndication defaults for unset overrides.
    if off["preferred_return_pct_annual"] is None:
        off["preferred_return_pct_annual"] = syn["preferred_return_pct_annual"]
    if off["carried_interest_pct"] is None:
        off["carried_interest_pct"] = syn["carried_interest_pct"]
    off["status"] = "OPEN"
    touch(off)
    return success_object(ser_offering(off))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/close-to-new", methods=["POST"], **RS)
@endpoint(SPONSOR)
def close_to_new(caller, syndicationId, offeringId):
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    _check_version(body, off)
    if off["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE",
                    f"cannot close-to-new an offering in status {off['status']}")
    off["status"] = "CLOSED_TO_NEW_SUBSCRIPTIONS"
    touch(off)
    return success_object(ser_offering(off))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/reopen", methods=["POST"], **RS)
@endpoint(SPONSOR)
def reopen_offering(caller, syndicationId, offeringId):
    syn = resolve.syndication(syndicationId)
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    _check_version(body, off)
    if off["status"] != "CLOSED_TO_NEW_SUBSCRIPTIONS":
        raise_error("ERR_INVALID_STATE",
                    f"cannot reopen an offering in status {off['status']}")
    if syn["status"] != "ACTIVE":
        raise_error("ERR_SYNDICATION_NOT_ACTIVE", "syndication must be ACTIVE to reopen")
    off["status"] = "OPEN"
    touch(off)
    return success_object(ser_offering(off))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/final-close", methods=["POST"], **RS)
@endpoint(SPONSOR)
def final_close(caller, syndicationId, offeringId):
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    _check_version(body, off)
    if off["status"] != "CLOSED_TO_NEW_SUBSCRIPTIONS":
        raise_error("ERR_INVALID_STATE",
                    f"cannot final-close an offering in status {off['status']}")
    open_states = ("DRAFT", "SUBMITTED", "ACCREDITATION_VERIFIED",
                   "SUITABILITY_APPROVED", "AWAITING_FUNDING")
    if any(s["status"] in open_states for s in domain.offering_subscriptions(offeringId)):
        raise_error("ERR_OFFERING_HAS_OPEN_SUBSCRIPTIONS",
                    "offering has subscriptions in a non-final state")
    # Only issued capital calls block; a DRAFT call was never issued (PRD 3.2).
    if any(c["offering_id"] == offeringId and c["status"] in ("ISSUED", "PARTIALLY_FUNDED")
           for c in db["capital_calls"].values()):
        raise_error("ERR_OFFERING_HAS_OPEN_CAPITAL_CALLS",
                    "issued capital calls must be FULLY_FUNDED or CANCELLED")
    off["status"] = "FINAL_CLOSE"
    touch(off)
    return success_object(ser_offering(off))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/dissolve", methods=["POST"], **RS)
@endpoint(SPONSOR)
def dissolve_offering(caller, syndicationId, offeringId):
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    _check_version(body, off)
    if off["status"] != "FINAL_CLOSE":
        raise_error("ERR_INVALID_STATE",
                    f"cannot dissolve an offering in status {off['status']}")
    if domain.offering_unreturned_capital(offeringId) != 0:
        raise_error("ERR_OFFERING_UNRETURNED_CAPITAL",
                    "offering still has unreturned LP capital")
    if any(d["offering_id"] == offeringId and d["status"] not in ("PAID", "CANCELLED")
           for d in db["distributions"].values()):
        raise_error("ERR_DISTRIBUTION_NOT_PAID",
                    "all distributions must be PAID or CANCELLED before dissolve")
    for s in domain.offering_subscriptions(offeringId):
        if s["status"] == "FUNDED":
            domain.freeze_accrual(s, off)
            s["status"] = "WITHDRAWN"
            touch(s)
    off["status"] = "DISSOLVED"
    touch(off)
    return success_object(ser_offering(off))
