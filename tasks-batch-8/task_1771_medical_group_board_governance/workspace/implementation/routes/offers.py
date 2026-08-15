"""BuyInOffer routes."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import clock, _format_iso, _parse_iso
from middleware import get_auth, require_roles, check_ownership
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_OFFER_NOT_OPEN,
    ERR_OFFER_WINDOW_OVERLAP, ERR_PHYSICIAN_EXITING, ERR_INVALID_STATE,
    ERR_INSUFFICIENT_TREASURY_SHARES, ERR_INSTALLMENT_AMOUNT_MISMATCH,
)
from services.core import (
    get_body, check_unknown_fields, req_enum, req_int, dec,
    round_half_up_cents, new_entity, touch, get_or_404, pagination_params,
    paginate, serialize_offer, tenure_years, recalc_ownership,
)

bp = Blueprint("offers", __name__)


def compute_buy_in_price(physician, target_tier, installment_count, offered_at):
    pol = db.policy
    ty = tenure_years(physician, at=offered_at)
    discount = min(dec(ty) * dec(pol["tenure_discount_pct_per_year"]),
                   dec(pol["max_tenure_discount_pct"]))
    tier_base = (pol["buy_in_base_shareholder_cents"] if target_tier == "SHAREHOLDER"
                 else pol["buy_in_base_partner_cents"])
    month = offered_at.month
    fy_start = pol["fiscal_year_start_month"]
    fiscal_month_index = ((month - fy_start) % 12) + 1  # July -> 1
    proration_twelfths = 13 - fiscal_month_index        # July -> 12
    discounted = dec(tier_base) * (Decimal(1) - discount)
    prorated = round_half_up_cents(discounted * Decimal(proration_twelfths) / Decimal(12))
    final_amount = max(prorated, pol["min_buy_in_cents"])
    base = final_amount // installment_count
    first = base + (final_amount - base * installment_count)
    schedule = [first] + [base] * (installment_count - 1)
    return {
        "tenure_years_at_offer": ty,
        "discount_pct_applied": float(discount),
        "proration_twelfths": proration_twelfths,
        "final_amount_cents": final_amount,
        "installment_schedule_cents": schedule,
    }


@bp.post("/governance/buy-in-offers")
def create_offer():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["physician_id", "target_tier", "share_grant",
                                "installment_count"])
    require_roles(role, ("BoardAdmin",))

    physician_id = body.get("physician_id")
    if not isinstance(physician_id, str) or not physician_id:
        raise_err(ERR_INVALID_REQUEST, "physician_id is required")
    target_tier = req_enum(body, "target_tier", ("PARTNER_TRACK", "SHAREHOLDER"))
    share_grant = req_int(body, "share_grant", min_val=0)
    installment_count = req_int(body, "installment_count")
    if installment_count < 1 or installment_count > 5:
        raise_err(ERR_INVALID_REQUEST, "installment_count must be 1..5")
    if target_tier == "SHAREHOLDER" and share_grant <= 0:
        raise_err(ERR_INVALID_REQUEST,
                  "share_grant must be > 0 for SHAREHOLDER tier")
    if target_tier == "PARTNER_TRACK" and share_grant != 0:
        raise_err(ERR_INVALID_REQUEST,
                  "share_grant must be 0 for PARTNER_TRACK tier")

    phys = db.physicians.get(physician_id)
    if phys is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")

    # state gates
    if phys["partnership_status"] == "EXITED":
        raise_err(ERR_INVALID_STATE, "EXITED physician is immutable")
    if phys["partnership_status"] == "EXITING":
        raise_err(ERR_PHYSICIAN_EXITING,
                  "EXITING physician may not receive new buy-in offers")
    if phys["partnership_status"] == "SHAREHOLDER":
        raise_err(ERR_INVALID_STATE, "Physician is already a SHAREHOLDER")
    if target_tier == "PARTNER_TRACK" and phys["partnership_status"] != "ASSOCIATE":
        raise_err(ERR_INVALID_STATE,
                  "PARTNER_TRACK offers only from ASSOCIATE")

    # cardinality: at most one open-window offer per physician
    now = clock.now()
    for o in db.buy_in_offers.values():
        if o["physician_id"] == physician_id and o["status"] == "OFFERED":
            deadline = _parse_iso(o["acceptance_deadline"])
            if now <= deadline:
                raise_err(ERR_OFFER_WINDOW_OVERLAP,
                          "Physician already has an open offer window")

    if db.policy is None:
        raise_err(ERR_INVALID_STATE, "GovernancePolicy not configured")

    offered_at = clock.now()
    deadline = offered_at + timedelta(days=db.policy["offer_window_days"])
    calc = compute_buy_in_price(phys, target_tier, installment_count, offered_at)

    o = new_entity(db.buy_in_offers, {
        "physician_id": physician_id,
        "target_tier": target_tier,
        "share_grant": share_grant,
        "installment_count": installment_count,
        "offered_at": _format_iso(offered_at),
        "acceptance_deadline": _format_iso(deadline),
        "tenure_years_at_offer": calc["tenure_years_at_offer"],
        "discount_pct_applied": calc["discount_pct_applied"],
        "proration_twelfths": calc["proration_twelfths"],
        "final_amount_cents": calc["final_amount_cents"],
        "installment_schedule_cents": calc["installment_schedule_cents"],
        "paid_installment_count": 0,
        "status": "OFFERED",
    })
    return success_object(serialize_offer(o), 201)


@bp.get("/governance/buy-in-offers")
def list_offers():
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin", "Physician"))
    items = list(db.buy_in_offers.values())
    f_pid = request.args.get("physician_id")
    f_status = request.args.get("status")
    if f_pid is not None:
        items = [o for o in items if o["physician_id"] == f_pid]
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_offer(o) for o in page], limit, offset, total)


@bp.get("/governance/buy-in-offers/<oid>")
def get_offer(oid):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin", "Physician"))
    o = get_or_404(db.buy_in_offers, oid, "BuyInOffer")
    return success_object(serialize_offer(o))


@bp.post("/governance/buy-in-offers/<oid>/respond")
def respond_offer(oid):
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["decision"])
    require_roles(role, ("Physician",))
    o = get_or_404(db.buy_in_offers, oid, "BuyInOffer")
    decision = body.get("decision")
    if decision not in ("ACCEPT", "DECLINE"):
        raise_err(ERR_INVALID_REQUEST, "decision must be ACCEPT or DECLINE")
    check_ownership(role, user_id, o["physician_id"])
    if o["status"] != "OFFERED":
        raise_err(ERR_OFFER_NOT_OPEN, "Offer is not OFFERED")
    o["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(o)
    return success_object(serialize_offer(o))


@bp.post("/governance/buy-in-offers/<oid>/pay-installment")
def pay_installment(oid):
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["amount_cents"])
    require_roles(role, ("Physician", "BoardAdmin"))
    o = get_or_404(db.buy_in_offers, oid, "BuyInOffer")
    amount = body.get("amount_cents")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    check_ownership(role, user_id, o["physician_id"])
    if o["status"] != "ACCEPTED":
        raise_err(ERR_OFFER_NOT_OPEN, "Offer is not ACCEPTED")
    expected = o["installment_schedule_cents"][o["paid_installment_count"]]
    if amount != expected:
        raise_err(ERR_INSTALLMENT_AMOUNT_MISMATCH,
                  "Installment payment must equal the scheduled amount")

    o["paid_installment_count"] += 1
    if o["paid_installment_count"] == o["installment_count"]:
        # complete: advance physician tier
        phys = db.physicians[o["physician_id"]]
        o["status"] = "COMPLETED"
        if o["target_tier"] == "PARTNER_TRACK":
            phys["partnership_status"] = "PARTNER_TRACK"
        else:
            # SHAREHOLDER: treasury check
            treasury = db.policy["total_shares_authorized"] - sum(
                p["shares_held"] for p in db.physicians.values())
            if o["share_grant"] > treasury:
                raise_err(ERR_INSUFFICIENT_TREASURY_SHARES,
                          "Treasury does not hold enough shares")
            phys["partnership_status"] = "SHAREHOLDER"
            phys["shares_held"] += o["share_grant"]
        touch(phys)
        recalc_ownership()
    touch(o)
    return success_object(serialize_offer(o))
