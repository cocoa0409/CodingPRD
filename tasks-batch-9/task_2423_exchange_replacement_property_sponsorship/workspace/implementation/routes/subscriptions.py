"""Subscription endpoints (PRD 3.6)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("subscriptions", __name__)


def _has_identification_for_property(exchange_file_id, property_id):
    for row in db.sorted_rows(db.identifications):
        if row["exchange_file_id"] == exchange_file_id and row["status"] == "ACTIVE" \
                and row["property_id"] == property_id:
            return True
    return False


def _check_investor_gates(investor, offering, create):
    """Rungs 28, 29, (30 on create only) and 31."""
    if investor["accreditation_status"] != "VERIFIED":
        raise ApiError("ERR_INVESTOR_NOT_ACCREDITED")
    expires_at = investor.get("accreditation_expires_at")
    if expires_at is None or clock.now() >= expires_at:
        raise ApiError("ERR_ACCREDITATION_EXPIRED")
    if create and offering["exemption_rule"] == "RULE_506C" \
            and investor["accreditation_method"] in C.SELF_CERT_METHODS:
        raise ApiError("ERR_ACCREDITATION_METHOD_NOT_PERMITTED")
    if investor["suitability_status"] != "APPROVED":
        raise ApiError("ERR_SUITABILITY_NOT_APPROVED")


@bp.post("/subscriptions")
def create_subscription():
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    offering_id = middleware.req_str(payload, "offering_id")
    investor_id = middleware.req_str(payload, "investor_id")
    exchange_file_id = middleware.req_str(payload, "exchange_file_id")
    units_requested = middleware.req_int(payload, "units_requested", 1)
    expected_offering_version = middleware.req_int(payload, "expected_offering_version")

    offering = domain.require("offering", offering_id)
    investor = domain.require("investor", investor_id)
    exchange_file = domain.require("exchange_file", exchange_file_id)

    # rung 8 — optimistic concurrency on the capacity-bearing parent
    if expected_offering_version != offering["version"]:
        raise ApiError("ERR_STALE_OFFERING_VERSION")

    trust = domain.trust_of_offering(offering)
    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("FUNDING",))
    if offering["status"] != "EFFECTIVE":
        raise ApiError("ERR_OFFERING_NOT_EFFECTIVE")
    if exchange_file["status"] != "IDENTIFIED":
        raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")

    _check_investor_gates(investor, offering, create=True)

    if clock.now() > exchange_file["exchange_deadline"]:
        raise ApiError("ERR_EXCHANGE_DEADLINE_PASSED")
    if investor.get("suitability_offering_id") != offering["id"]:
        raise ApiError("ERR_SUITABILITY_OFFERING_MISMATCH")
    if exchange_file["investor_id"] != investor["id"]:
        raise ApiError("ERR_EXCHANGE_FILE_INVESTOR_MISMATCH")
    if not _has_identification_for_property(exchange_file["id"], trust["property_id"]):
        raise ApiError("ERR_IDENTIFICATION_MISSING_FOR_TRUST")

    if units_requested < offering["min_units_per_investor"]:
        raise ApiError("ERR_BELOW_MINIMUM_INVESTMENT")

    investment_amount_cents = units_requested * offering["unit_price_cents"]
    if investment_amount_cents > (investor.get("suitability_cap_cents") or 0):
        raise ApiError("ERR_SUITABILITY_CAP_EXCEEDED")

    boot_cents = calc.subscription_boot(
        domain.loan_principal(trust), units_requested, trust["total_units"],
        investment_amount_cents, exchange_file["net_proceeds_cents"],
        exchange_file["debt_retired_cents"],
    )
    if boot_cents > exchange_file["boot_tolerance_cents"]:
        raise ApiError("ERR_BOOT_EXCEEDS_TOLERANCE")

    target_equity = offering["target_equity_cents"] or 0
    if (offering["equity_committed_cents"] or 0) >= target_equity or \
            (offering["units_committed"] or 0) + units_requested > trust["total_units"]:
        raise ApiError("ERR_OFFERING_OVERSUBSCRIBED")

    row = db.new_row(db.subscriptions, {
        "offering_id": offering["id"],
        "investor_id": investor["id"],
        "exchange_file_id": exchange_file["id"],
        "units_requested": units_requested,
        "investment_amount_cents": investment_amount_cents,
        "boot_cents": boot_cents,
        "closing_sequence_no": None,
        "closed_at": None,
        "rescission_deadline": None,
        "status": "RESERVED",
    })
    domain.recompute_offering_totals(offering, force=True)
    return created_response(db.serialize(row))


@bp.get("/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    return read_one("subscription", C.READ_EXCHANGE_SIDE, subscription_id)


@bp.get("/subscriptions")
def list_subscriptions():
    return listing(db.subscriptions, C.READ_EXCHANGE_SIDE,
                   str_filters=("offering_id", "investor_id", "exchange_file_id",
                                "status"))


@bp.post("/subscriptions/<subscription_id>/close")
def close_subscription(subscription_id):
    user_id, _role = middleware.actor([C.SPONSOR])

    # rung 4 — the officer who approved suitability may not take the money
    candidate = domain.lookup("subscription", subscription_id)
    if candidate is not None:
        investor = db.investors.get(candidate["investor_id"])
        if investor is not None and investor.get("suitability_reviewed_by_user_id") \
                and investor["suitability_reviewed_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    sub = domain.require("subscription", subscription_id)
    offering = db.offerings[sub["offering_id"]]
    trust = domain.trust_of_offering(offering)
    investor = db.investors[sub["investor_id"]]
    exchange_file = db.exchange_files[sub["exchange_file_id"]]

    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("FUNDING",))
    if offering["status"] != "EFFECTIVE":
        raise ApiError("ERR_OFFERING_NOT_EFFECTIVE")
    if sub["status"] != "RESERVED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")
    if exchange_file["status"] != "IDENTIFIED":
        raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")

    _check_investor_gates(investor, offering, create=False)

    if clock.now() > exchange_file["exchange_deadline"]:
        raise ApiError("ERR_EXCHANGE_DEADLINE_PASSED")
    if not _has_identification_for_property(exchange_file["id"], trust["property_id"]):
        raise ApiError("ERR_IDENTIFICATION_MISSING_FOR_TRUST")

    domain.close_subscription(sub)
    return object_response(db.serialize(sub))


@bp.post("/subscriptions/<subscription_id>/reject")
def reject_subscription(subscription_id):
    middleware.actor([C.COMPLIANCE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    sub = domain.require("subscription", subscription_id)
    offering = db.offerings[sub["offering_id"]]
    domain.check_frozen(domain.trust_of_offering(offering))
    if sub["status"] not in ("RESERVED", "REVISION_REQUIRED"):
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")

    sub["status"] = "REJECTED"
    db.touch(sub)
    domain.recompute_offering_totals(offering, force=True)
    return object_response(db.serialize(sub))


@bp.post("/subscriptions/<subscription_id>/rescind")
def rescind_subscription(subscription_id):
    user_id, _role = middleware.actor([C.INVESTOR])

    candidate = domain.lookup("subscription", subscription_id)
    if candidate is not None:
        domain.check_investor_owns(user_id, candidate["investor_id"])

    sub = domain.require("subscription", subscription_id)
    trust = domain.trust_of_subscription(sub)
    domain.check_frozen(trust)
    if sub["status"] != "CLOSED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")
    if sub.get("rescission_deadline") is None or clock.now() > sub["rescission_deadline"]:
        raise ApiError("ERR_RESCISSION_WINDOW_CLOSED")

    domain.rescind_subscription(sub)
    return object_response(db.serialize(sub))
