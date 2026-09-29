"""Subscription processing and the capital-account cascade (PRD 3.4)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from db import ZERO6
from errors import fail
from middleware import (ALL_ROLES, INVESTOR, OPERATOR_ROLES, SYNDICATION_COUNSEL,
                        ctx, endpoint, find_investor, find_offering_document,
                        lookup, require_owner, user_id)
from routes.offering_documents import in_window, sweep
from services import ledger
from services import queries as q

bp = Blueprint("subscriptions", __name__)

SUBSCRIPTION_STATUSES = ("SUBMITTED", "RETURNED_FOR_CURE", "ACCEPTED",
                         "REJECTED", "RESCINDED")
MAX_CURE_ROUNDS = 2


def _find_subscription(subscription_id):
    return lookup("subscriptions", subscription_id,
                  errors.ERR_SUBSCRIPTION_NOT_FOUND)


def _require_effective(document):
    """Cross-entity gate 9: DRAFT / WITHDRAWN report not-effective here, while
    EXPIRED is deferred to the temporal rules so it reports the more specific
    ERR_OFFERING_EXPIRED (PRD 2.10)."""
    if document["status"] in ("DRAFT", "WITHDRAWN"):
        fail(errors.ERR_OFFERING_NOT_EFFECTIVE,
             "The offering instrument is not EFFECTIVE.")


def _require_window(document):
    if document["status"] == "EXPIRED" or not in_window(document):
        fail(errors.ERR_OFFERING_EXPIRED,
             "The offering instrument's effective window has lapsed.")


@bp.post("/subscriptions")
@endpoint((INVESTOR,))
def create_subscription():
    data = v.body()
    document_id = v.req_id(data, "offering_document_id")
    investor_id = v.req_id(data, "investor_id")
    units = v.req_int(data, "units", 1)

    document = find_offering_document(document_id)
    investor = find_investor(investor_id)
    sweep(document)

    require_owner(investor_id)
    _require_effective(document)
    if investor["accreditation_status"] != "ACCREDITED":
        fail(errors.ERR_INVESTOR_NOT_ACCREDITED,
             "Only an ACCREDITED investor may subscribe.")
    _require_window(document)

    row = db.insert("subscriptions", {
        "offering_document_id": document_id,
        "investor_id": investor_id,
        "units": units,
        "amount_cents": units * document["unit_price_cents"],
        "status": "SUBMITTED",
        "cure_round_count": 0,
        "defect_note": None,
        "rescission_reason": None,
    })
    ctx().created(row)
    ctx().force(document)
    ledger.refresh_offering_document(ctx(), document)
    return response.obj(row, 201)


@bp.post("/subscriptions/<subscription_id>/return-for-cure")
@endpoint((SYNDICATION_COUNSEL,))
def return_for_cure(subscription_id):
    subscription = _find_subscription(subscription_id)
    data = v.body()
    note = v.req_str(data, "defect_note")
    document = db.get("offering_documents", subscription["offering_document_id"])

    if subscription["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_SUBSCRIPTION_STATE,
             "Only a SUBMITTED subscription may be returned for cure.")

    ctx().force(document)
    ctx().watch(subscription)
    subscription["cure_round_count"] += 1
    subscription["defect_note"] = note
    subscription["status"] = (
        "RETURNED_FOR_CURE"
        if subscription["cure_round_count"] <= MAX_CURE_ROUNDS else "REJECTED")
    ledger.refresh_offering_document(ctx(), document)
    return response.obj(subscription)


@bp.post("/subscriptions/<subscription_id>/resubmit")
@endpoint((INVESTOR,))
def resubmit_subscription(subscription_id):
    subscription = _find_subscription(subscription_id)
    data = v.body()
    units = v.req_int(data, "units", 1)
    document = db.get("offering_documents", subscription["offering_document_id"])
    sweep(document)

    require_owner(subscription["investor_id"])
    if subscription["status"] != "RETURNED_FOR_CURE":
        fail(errors.ERR_INVALID_SUBSCRIPTION_STATE,
             "Only a RETURNED_FOR_CURE subscription may be resubmitted.")
    _require_effective(document)
    _require_window(document)

    ctx().force(document)
    ctx().watch(subscription)
    subscription["units"] = units
    subscription["amount_cents"] = units * document["unit_price_cents"]
    subscription["status"] = "SUBMITTED"
    ledger.refresh_offering_document(ctx(), document)
    return response.obj(subscription)


@bp.post("/subscriptions/<subscription_id>/accept")
@endpoint((SYNDICATION_COUNSEL,))
def accept_subscription(subscription_id):
    subscription = _find_subscription(subscription_id)
    document = db.get("offering_documents", subscription["offering_document_id"])
    sweep(document)
    production = db.get("productions", document["production_id"])
    investor = db.get("investors", subscription["investor_id"])

    if subscription["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_SUBSCRIPTION_STATE,
             "Only a SUBMITTED subscription may be accepted.")
    _require_effective(document)

    if investor["accreditation_status"] != "ACCREDITED":
        fail(errors.ERR_INVESTOR_NOT_ACCREDITED,
             "Only an ACCREDITED investor's subscription may be accepted.")
    holders = {s["investor_id"] for s in q.subs_of_doc(document["id"])
               if s["status"] == "ACCEPTED"}
    holders.add(subscription["investor_id"])
    if len(holders) > document["max_investors"]:
        fail(errors.ERR_MAX_INVESTORS_EXCEEDED,
             "The instrument may not carry another distinct accepted investor.")

    _require_window(document)

    if (document["accepted_amount_cents"] + subscription["amount_cents"]
            > document["offering_amount_cents"]):
        fail(errors.ERR_OVERSUBSCRIPTION,
             "The acceptance would push accepted_amount_cents above the offering amount.")

    ctx().force(document)
    ctx().force(production)
    ctx().watch(subscription)
    subscription["status"] = "ACCEPTED"

    account = q.account_for(production["id"], subscription["investor_id"])
    if account is None:
        account = db.insert("investor_accounts", {
            "production_id": production["id"],
            "investor_id": subscription["investor_id"],
            "units_total": 0,
            "contributed_cents": 0,
            "ownership_pct": ZERO6,
            "basis": ("NET_PROFIT"
                      if production["recoupment_status"] == "RECOUPED"
                      else "RECOUPMENT_RETURN"),
            "recoupment_credited_cents": 0,
            "declared_distribution_cents": 0,
            "distributions_paid_cents": 0,
        })
        ctx().created(account)

    ledger.investor_ownership_allocation(ctx(), production)
    ledger.recompute_production_capital(ctx(), production)
    if (production["offering_status"] == "OFFERING"
            and production["capital_raised_cents"]
            >= production["capitalization_target_cents"]):
        production["offering_status"] = "FULLY_SUBSCRIBED"
    ledger.refresh_offering_document(ctx(), document)
    return response.obj(subscription)


@bp.post("/subscriptions/<subscription_id>/rescind")
@endpoint((SYNDICATION_COUNSEL,))
def rescind_subscription(subscription_id):
    subscription = _find_subscription(subscription_id)
    data = v.body()
    reason = v.req_str(data, "rescission_reason")
    document = db.get("offering_documents", subscription["offering_document_id"])
    production = db.get("productions", document["production_id"])

    if subscription["status"] != "ACCEPTED":
        fail(errors.ERR_INVALID_SUBSCRIPTION_STATE,
             "Only an ACCEPTED subscription may be rescinded.")
    if production["offering_status"] not in ("OFFERING", "FULLY_SUBSCRIBED"):
        fail(errors.ERR_INVALID_OFFERING_STATE,
             "Rescission is closed off once capital has been released.")

    ctx().force(document)
    ctx().force(production)
    ctx().watch(subscription)
    subscription["status"] = "RESCINDED"
    subscription["rescission_reason"] = reason

    ledger.investor_ownership_allocation(ctx(), production)
    ledger.recompute_production_capital(ctx(), production)
    if (production["offering_status"] == "FULLY_SUBSCRIBED"
            and production["capital_raised_cents"]
            < production["capitalization_target_cents"]):
        production["offering_status"] = "OFFERING"
    ledger.refresh_offering_document(ctx(), document)
    return response.obj(subscription)


@bp.get("/subscriptions/<subscription_id>")
@endpoint(ALL_ROLES)
def read_subscription(subscription_id):
    subscription = _find_subscription(subscription_id)
    require_owner(subscription["investor_id"])
    return response.obj(subscription)


@bp.get("/subscriptions")
@endpoint(OPERATOR_ROLES)
def list_subscriptions():
    document_id = v.q_str("offering_document_id")
    investor_id = v.q_str("investor_id")
    status = v.q_enum("status", SUBSCRIPTION_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("subscriptions")
            if (document_id is None or r["offering_document_id"] == document_id)
            and (investor_id is None or r["investor_id"] == investor_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
