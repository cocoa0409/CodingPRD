"""Subscription intake and the subscription machine, plus share-lot reads.

PRD §3.4 and §3.5.
"""

from datetime import timedelta

from flask import Blueprint

import calc
import domain
import validate as V
from auth import require_roles, require_transition_role, role, user_id
from errors import fail
from routes.helpers import listing, new, resolve, single
from store import DB, all_rows, fmt_instant, logical_now, new_row, touch

bp = Blueprint("subscriptions", __name__)

SUBSCRIPTION_STATES = ("PENDING", "ESCROWED", "ACCEPTED", "REJECTED",
                       "REFUNDED", "RESCINDED")
LOT_STATES = ("OPEN", "CLOSED", "RESCINDED")

# PRD §2.1 / §3.5 — who may drive which subscription status.
STATUS_ROLES = {
    "ESCROWED": ("TransferAgent",),
    "REFUNDED": ("TransferAgent",),
    "RESCINDED": ("TransferAgent",),
    "ACCEPTED": ("SponsorOperator",),
    "REJECTED": ("SponsorOperator",),
}

READ_ROLES = ("SponsorOperator", "ComplianceOfficer", "TransferAgent",
              "BrokerDealerRep", "InvestorUser")


@bp.post("/subscriptions")
def create_subscription():
    require_roles("SponsorOperator", "BrokerDealerRep")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    share_class_id = V.fk(body, "share_class_id")
    investor_id = V.fk(body, "investor_id")
    selling_agreement_id = V.fk(body, "selling_agreement_id")
    gross = V.integer(body, "gross_investment_cents", minimum=1)

    offering = resolve("offerings", offering_id)
    cls = resolve("share_classes", share_class_id)
    investor = resolve("investors", investor_id)
    agreement = resolve("selling_agreements", selling_agreement_id)

    # Level 5 — a representative places business only under its own firm.
    if role() == "BrokerDealerRep" and agreement["broker_dealer_id"] != user_id():
        fail("ERR_NOT_RESOURCE_OWNER")

    # Level 8 — dependency states in the fixed order.
    if offering["registration_status"] != "EFFECTIVE":
        fail("ERR_OFFERING_NOT_EFFECTIVE")
    if cls["status"] == "CLOSED_TO_NEW":
        fail("ERR_SHARE_CLASS_CLOSED")
    if agreement["status"] != "ACTIVE":
        fail("ERR_SELLING_AGREEMENT_NOT_ACTIVE")
    firm = DB["broker_dealers"].get(agreement["broker_dealer_id"])
    if firm is not None and firm["supervision_status"] == "BARRED":
        fail("ERR_BROKER_DEALER_BARRED")

    # Level 10 — investor-protection gates, in order.
    if agreement["suitability_documentation_required"] and \
            investor["suitability_status"] in ("INCOMPLETE", "FLAGGED"):
        fail("ERR_SUITABILITY_NOT_DOCUMENTED")
    if investor["cumulative_invested_cents"] + gross > investor["concentration_limit_cents"]:
        fail("ERR_CONCENTRATION_LIMIT_EXCEEDED")
    prior = [s for s in domain.subscriptions_of_offering(offering["id"])
             if s["investor_id"] == investor["id"]]
    minimum = (calc.MINIMUM_ADDITIONAL_INVESTMENT_CENTS if prior
               else calc.MINIMUM_INITIAL_INVESTMENT_CENTS)
    if gross < minimum:
        fail("ERR_BELOW_MINIMUM_INVESTMENT")

    # Level 11 — the agreement's commission ceiling.
    if cls["upfront_selling_commission_bps"] + cls["dealer_manager_fee_bps"] > \
            agreement["max_commission_bps"]:
        fail("ERR_COMMISSION_CAP_EXCEEDED")

    # Level 13 — the registered maximum.
    if offering["gross_proceeds_cents"] + gross > offering["maximum_offering_amount_cents"]:
        fail("ERR_OFFERING_MAXIMUM_EXCEEDED")

    price = domain.transaction_price_cents(cls)
    figures = calc.subscription_figures(
        gross, cls["upfront_selling_commission_bps"],
        cls["dealer_manager_fee_bps"], price)

    row = new_row("subscriptions", {
        "offering_id": offering["id"],
        "share_class_id": cls["id"],
        "investor_id": investor["id"],
        "selling_agreement_id": agreement["id"],
        "gross_investment_cents": gross,
        "transaction_price_cents": price,
        "upfront_selling_commission_cents": figures["upfront_selling_commission_cents"],
        "dealer_manager_fee_cents": figures["dealer_manager_fee_cents"],
        "net_invested_cents": figures["net_invested_cents"],
        "shares_issued_e4": figures["shares_issued_e4"],
        "unapplied_cash_cents": figures["unapplied_cash_cents"],
        "status": "PENDING",
        "rejection_reason": None,
        "accepted_at": None,
    })
    return new(row)


@bp.get("/subscriptions")
def list_subscriptions():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    share_class_id = V.query_string("share_class_id")
    investor_id = V.query_string("investor_id")
    selling_agreement_id = V.query_string("selling_agreement_id")
    status = V.query_enum("status", SUBSCRIPTION_STATES)
    rows = [s for s in all_rows("subscriptions")
            if (offering_id is None or s["offering_id"] == offering_id)
            and (share_class_id is None or s["share_class_id"] == share_class_id)
            and (investor_id is None or s["investor_id"] == investor_id)
            and (selling_agreement_id is None
                 or s["selling_agreement_id"] == selling_agreement_id)
            and (status is None or s["status"] == status)]
    return listing(rows, limit, offset)


@bp.get("/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    require_roles(*READ_ROLES)
    return single(resolve("subscriptions", subscription_id))


@bp.post("/subscriptions/<subscription_id>/status")
def drive_subscription(subscription_id):
    require_roles("SponsorOperator", "TransferAgent")
    peek = V.json_body(silent=True)
    require_transition_role(STATUS_ROLES, peek.get("to_status"))
    body = V.json_body()
    to_status = V.enum(body, "to_status", SUBSCRIPTION_STATES)
    reason = V.string(body, "rejection_reason", required=False, default=None, min_len=0)

    sub = resolve("subscriptions", subscription_id)
    offering = DB["offerings"].get(sub["offering_id"])
    cls = DB["share_classes"].get(sub["share_class_id"])
    investor = DB["investors"].get(sub["investor_id"])
    current = sub["status"]

    if to_status == "ESCROWED":
        if current != "PENDING":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering["escrow_status"] != "COLLECTING":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The offering's escrow is no longer collecting.")
        if offering["registration_status"] != "EFFECTIVE":
            fail("ERR_OFFERING_NOT_EFFECTIVE")
        sub["status"] = "ESCROWED"
        touch(sub)

    elif to_status == "ACCEPTED":
        if current != "PENDING":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering["escrow_status"] != "BROKEN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Subscriptions are accepted one at a time only after escrow has broken.")
        if offering["registration_status"] != "EFFECTIVE":
            fail("ERR_OFFERING_NOT_EFFECTIVE")
        if domain.latest_published(sub["share_class_id"]) is None:
            fail("ERR_NO_PUBLISHED_NAV")
        if offering["gross_proceeds_cents"] + sub["gross_investment_cents"] > \
                offering["maximum_offering_amount_cents"]:
            fail("ERR_OFFERING_MAXIMUM_EXCEEDED")
        sub["status"] = "ACCEPTED"
        sub["accepted_at"] = fmt_instant(logical_now())
        touch(sub)
        if cls is not None:
            domain.mint_lot(sub, cls)
        domain.note_lot_minted(investor)
        domain.sync_derived()
        domain.reevaluate_suitability(investor)

    elif to_status == "REJECTED":
        if current != "PENDING":
            fail("ERR_INVALID_STATE_TRANSITION")
        sub["status"] = "REJECTED"
        sub["rejection_reason"] = reason
        touch(sub)

    elif to_status == "REFUNDED":
        if current != "ESCROWED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering["escrow_status"] not in ("COLLECTING", "FAILED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A refund is available only while escrow is collecting or has failed.")
        sub["status"] = "REFUNDED"
        sub["rejection_reason"] = reason
        touch(sub)

    elif to_status == "RESCINDED":
        if current != "ACCEPTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        lots = domain.lots_of_subscription(sub["id"])
        lot = lots[0] if lots else None
        window = timedelta(days=offering["rescission_window_days"])
        if lot is not None and logical_now() > lot["_issued_at"] + window:
            fail("ERR_RESCISSION_WINDOW_EXPIRED")
        if lot is not None and lot["remaining_shares_e4"] != lot["original_shares_e4"]:
            fail("ERR_LOT_PARTIALLY_REPURCHASED")
        sub["status"] = "RESCINDED"
        sub["rejection_reason"] = reason
        touch(sub)
        if lot is not None:
            lot["status"] = "RESCINDED"
            lot["remaining_shares_e4"] = 0
            touch(lot)
        domain.sync_derived()
        domain.reevaluate_suitability(investor)
        domain.note_position_possibly_closed(investor)

    else:  # PENDING — no transition leads back to the initial state.
        fail("ERR_INVALID_STATE_TRANSITION")

    domain.sync_derived()
    return single(sub)


# --------------------------------------------------------------------------
# ShareLot (read-only)
# --------------------------------------------------------------------------

@bp.get("/share-lots")
def list_share_lots():
    require_roles("TransferAgent", "SponsorOperator", "ComplianceOfficer",
                  "InvestorUser")
    limit, offset = V.pagination()
    subscription_id = V.query_string("subscription_id")
    investor_id = V.query_string("investor_id")
    share_class_id = V.query_string("share_class_id")
    converted_from = V.query_string("converted_from_share_class_id")
    status = V.query_enum("status", LOT_STATES)
    rows = [l for l in all_rows("share_lots")
            if (subscription_id is None or l["subscription_id"] == subscription_id)
            and (investor_id is None or l["investor_id"] == investor_id)
            and (share_class_id is None or l["share_class_id"] == share_class_id)
            and (converted_from is None
                 or l["converted_from_share_class_id"] == converted_from)
            and (status is None or l["status"] == status)]
    return listing(rows, limit, offset)


@bp.get("/share-lots/<share_lot_id>")
def get_share_lot(share_lot_id):
    require_roles("TransferAgent", "SponsorOperator", "ComplianceOfficer",
                  "InvestorUser")
    return single(resolve("share_lots", share_lot_id))
