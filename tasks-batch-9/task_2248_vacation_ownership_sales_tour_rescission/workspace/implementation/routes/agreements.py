"""Purchase agreements: trade-in equity, contract financials, the rescission
window and funding (PRD 3.7 and 3.8)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_agreement, get_presentation, page
from store import db, ordered

bp = Blueprint("agreements", __name__)

RESCISSION_STATUSES = ("OPEN", "EXPIRED", "RESCINDED")
FULFILLMENT_STATUSES = (
    "AWAITING_FUNDING",
    "FUNDED",
    "RECORDED",
    "DOCS_DELIVERED",
    "TRADED_IN",
    "VOIDED",
)
PRODUCT_TYPES = ("DEEDED_INTEREST", "RIGHT_TO_USE")


@bp.post("/purchase-agreements")
def create_agreement():
    user_id, _ = auth.require(auth.SALES_REPRESENTATIVE)
    data = validators.body()
    presentation_id = validators.identifier(data, "presentation_id")
    product_type = validators.enum(data, "product_type", PRODUCT_TYPES)
    state_code = validators.enum(data, "state_code", calc.STATE_CODES)
    price = validators.integer(data, "purchase_price_cents", 100000)
    down_payment = validators.integer(data, "down_payment_cents", 0)
    pos_delivered_at = validators.datetime_field(data, "pos_delivered_at")
    traded_in_id = validators.identifier(data, "traded_in_agreement_id", required=False)

    presentation = get_presentation(presentation_id)
    prior = get_agreement(traded_in_id) if traded_in_id is not None else None

    if presentation["rep_id"] != user_id:
        fail(
            errors.ERR_REPRESENTATIVE_MISMATCH,
            "the acting representative does not own this presentation",
        )
    if presentation["disclosure_status"] != "COMPLETE":
        fail(errors.ERR_DISCLOSURES_INCOMPLETE, "disclosure_status is not COMPLETE")
    if presentation["review_status"] != "CLEARED":
        fail(errors.ERR_PRESENTATION_NOT_CLEARED, "review_status is not CLEARED")

    booking = db.bookings.get(presentation["booking_id"])
    prospect_id = booking["prospect_id"] if booking is not None else None

    now = db.now()
    if pos_delivered_at < now - calc.POS_WINDOW_BEFORE or (
        pos_delivered_at > now + calc.POS_WINDOW_AFTER
    ):
        fail(
            errors.ERR_POS_NOT_DELIVERED,
            "pos_delivered_at falls outside the permitted delivery window",
        )

    if prior is not None:
        if prior["prospect_id"] != prospect_id:
            fail(
                errors.ERR_TRADE_IN_OWNER_MISMATCH,
                "the surrendered agreement belongs to another household",
            )
        if not (
            prior["fulfillment_status"] == "DOCS_DELIVERED"
            and prior["rescission_status"] == "EXPIRED"
        ):
            fail(
                errors.ERR_TRADE_IN_NOT_ELIGIBLE,
                "the surrendered agreement is not eligible for trade-in",
            )

    for existing in db.agreements.values():
        if existing["presentation_id"] == presentation["id"]:
            fail(
                errors.ERR_AGREEMENT_ALREADY_EXISTS,
                "an agreement already exists for this presentation",
            )

    if prior is None:
        credit = 0
    else:
        held = calc.years_held(prior["funded_at"], now)
        credit = calc.trade_in_equity_credit(prior["purchase_price_cents"], held)

    money = calc.agreement_financials(price, credit, down_payment)
    if down_payment < money["down_payment_required_cents"]:
        fail(
            errors.ERR_DOWN_PAYMENT_INSUFFICIENT,
            "down_payment_cents is below the required %d"
            % money["down_payment_required_cents"],
        )

    window = calc.rescission_deadline(state_code, now, pos_delivered_at)

    agreement = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "presentation_id": presentation["id"],
        "prospect_id": prospect_id,
        "rep_id": presentation["rep_id"],
        "traded_in_agreement_id": prior["id"] if prior is not None else None,
        "product_type": product_type,
        "state_code": state_code,
        "purchase_price_cents": price,
        "down_payment_cents": down_payment,
        "pos_delivered_at": pos_delivered_at,
        "executed_at": now,
        "trade_in_equity_credit_cents": credit,
        "total_due_cents": money["total_due_cents"],
        "down_payment_required_cents": money["down_payment_required_cents"],
        "base_financed_cents": money["base_financed_cents"],
        "doc_stamp_cents": money["doc_stamp_cents"],
        "closing_cost_fee_cents": money["closing_cost_fee_cents"],
        "financed_amount_cents": money["financed_amount_cents"],
        "escrow_collected_cents": money["escrow_collected_cents"],
        "total_collected_cents": 0,
        "retained_cents": 0,
        "anchor_mode": window["anchor_mode"],
        "statutory_rescission_days": window["statutory_rescission_days"],
        "rescission_anchor_utc": window["rescission_anchor_utc"],
        "rescission_deadline_utc": window["rescission_deadline_utc"],
        "business_day_rolled": window["business_day_rolled"],
        "refund_policy": window["refund_policy"],
        "rescission_status": "OPEN",
        "fulfillment_status": "AWAITING_FUNDING",
        "funded_at": None,
        "funding_reference": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.agreements[agreement["id"]] = agreement

    rep = db.reps.get(agreement["rep_id"])
    if rep is not None:
        derive.setf(rep, "executed_agreement_count", rep["executed_agreement_count"] + 1)
        derive.recompute_rep_cancellation(rep)
    if prior is not None:
        derive.setf(prior, "fulfillment_status", "TRADED_IN")
    return created(agreement)


@bp.post("/purchase-agreements/<agreement_id>/fund")
def fund_agreement(agreement_id):
    auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    funding_reference = validators.string(data, "funding_reference", 1, 120)
    collected = validators.integer(data, "collected_amount_cents", 0)
    agreement = get_agreement(agreement_id)

    if agreement["fulfillment_status"] != "AWAITING_FUNDING":
        fail(errors.ERR_INVALID_AGREEMENT_STATE, "fulfillment_status is not AWAITING_FUNDING")
    if agreement["rescission_status"] != "EXPIRED":
        fail(
            errors.ERR_RESCISSION_PERIOD_ACTIVE,
            "the statutory rescission window has not expired",
        )

    financed = agreement["financed_amount_cents"]
    if financed > 0:
        approved = None
        for application in ordered(db.financings.values()):
            if (
                application["agreement_id"] == agreement["id"]
                and application["status"] == "APPROVED"
            ):
                approved = application
        if approved is None:
            fail(errors.ERR_FINANCING_NOT_APPROVED, "no APPROVED financing application")
        if approved["approved_amount_cents"] < financed:
            fail(
                errors.ERR_FINANCING_AMOUNT_SHORTFALL,
                "approved_amount_cents does not cover financed_amount_cents",
            )
    if collected != financed:
        fail(
            errors.ERR_FUNDING_AMOUNT_MISMATCH,
            "collected_amount_cents must equal financed_amount_cents (%d)" % financed,
        )

    now = db.now()
    derive.setf(agreement, "fulfillment_status", "FUNDED")
    derive.setf(agreement, "funded_at", now)
    derive.setf(agreement, "funding_reference", funding_reference)
    derive.setf(
        agreement,
        "total_collected_cents",
        agreement["escrow_collected_cents"] + collected,
    )

    package = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "agreement_id": agreement["id"],
        "instrument_type": (
            "DEED" if agreement["product_type"] == "DEEDED_INTEREST" else "RTU_CERTIFICATE"
        ),
        "recording_jurisdiction": None,
        "recording_reference": None,
        "recorded_at": None,
        "delivery_method": None,
        "documents_delivered_at": None,
        "status": "AWAITING_RECORDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.packages[package["id"]] = package

    derive.recompute_prospect_owner(db.prospects.get(agreement["prospect_id"]))
    return ok(agreement)


@bp.get("/purchase-agreements/<agreement_id>")
def read_agreement(agreement_id):
    auth.require_any()
    return ok(get_agreement(agreement_id))


@bp.get("/purchase-agreements")
def list_agreements():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.agreements,
        (
            ("presentation_id", "presentation_id"),
            ("prospect_id", "prospect_id"),
            ("rep_id", "rep_id"),
            ("traded_in_agreement_id", "traded_in_agreement_id"),
            ("rescission_status", "rescission_status", RESCISSION_STATUSES),
            ("fulfillment_status", "fulfillment_status", FULFILLMENT_STATUSES),
        ),
    )
    return listing(rows, limit, offset)


@bp.get("/purchase-agreements/<agreement_id>/rescission-window")
def rescission_window(agreement_id):
    auth.require_any()
    agreement = get_agreement(agreement_id)
    now = db.now()
    return ok(
        {
            "agreement_id": agreement["id"],
            "state_code": agreement["state_code"],
            "anchor_mode": agreement["anchor_mode"],
            "anchor_utc": agreement["rescission_anchor_utc"],
            "statutory_days": agreement["statutory_rescission_days"],
            "business_day_rolled": agreement["business_day_rolled"],
            "rescission_deadline_utc": agreement["rescission_deadline_utc"],
            "rescission_status": agreement["rescission_status"],
            "clock_now": now,
            "is_open_now": (
                agreement["rescission_status"] == "OPEN"
                and now <= agreement["rescission_deadline_utc"]
            ),
        }
    )
