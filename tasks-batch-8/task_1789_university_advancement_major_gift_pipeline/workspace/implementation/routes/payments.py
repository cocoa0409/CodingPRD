"""Gift payments: recording, waterfall allocation, splits, and reversal."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_money, req_enum, req_bool, parse_dt, now, new_entity, touch,
    dec_rhu_int, success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    ApiError, fail, ERR_INVALID_REQUEST, ERR_PROSPECT_NOT_FOUND,
    ERR_PLEDGE_NOT_FOUND, ERR_FUND_NOT_FOUND, ERR_CAMPAIGN_NOT_FOUND,
    ERR_PAYMENT_NOT_FOUND, ERR_PLEDGE_NOT_ACTIVE, ERR_FUND_NOT_ACTIVE,
    ERR_CAMPAIGN_INVALID_STATE, ERR_STEWARDSHIP_LAPSED, ERR_FUND_PLEDGE_MISMATCH,
    ERR_OUTSIDE_COUNTING_WINDOW, ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_SPLIT_PERCENT_SUM_INVALID, ERR_PAYMENT_ALREADY_REVERSED,
)
from services import (
    ser_payment, ser_credit_split, pledge_outstanding_cents, open_installments,
    reevaluate_pledge_status, recompute_campaign_totals,
    refresh_prospect_recognition,
)

bp = Blueprint("payments", __name__)


def _validate_splits_shape(splits):
    """Priority 3: structural well-formedness of the splits array."""
    if not isinstance(splits, list) or len(splits) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "splits must be a non-empty array")
    for entry in splits:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "each split must be an object")
        for key in entry:
            if key not in ("prospect_id", "credit_type", "split_pct"):
                raise ApiError(ERR_INVALID_REQUEST, 400, f"unknown split field: {key}")
        if not isinstance(entry.get("prospect_id"), str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "split prospect_id must be a string")
        if entry.get("credit_type") not in ("HARD", "SOFT"):
            raise ApiError(ERR_INVALID_REQUEST, 400, "split credit_type must be HARD or SOFT")
        pct = entry.get("split_pct")
        if not isinstance(pct, int) or isinstance(pct, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "split_pct must be an integer")


def _validate_splits_semantics(splits, donor_prospect_id):
    """Priority 13: exactly one HARD split to the donor, pcts 1..100, sum 100."""
    hard = [s for s in splits if s["credit_type"] == "HARD"]
    if len(hard) != 1 or hard[0]["prospect_id"] != donor_prospect_id:
        fail(ERR_SPLIT_PERCENT_SUM_INVALID,
             "Exactly one HARD split naming the donor_prospect_id is required")
    for s in splits:
        if s["split_pct"] < 1 or s["split_pct"] > 100:
            fail(ERR_SPLIT_PERCENT_SUM_INVALID, "split_pct must be between 1 and 100")
    if sum(s["split_pct"] for s in splits) != 100:
        fail(ERR_SPLIT_PERCENT_SUM_INVALID, "split_pct values must sum to 100")


def _compute_split_amounts(amount_cents, splits):
    """Smallest-pct-first rounding (half up); the largest split absorbs the residual."""
    order = sorted(range(len(splits)), key=lambda i: (splits[i]["split_pct"], i))
    amounts = [0] * len(splits)
    running = 0
    for pos, idx in enumerate(order):
        if pos == len(order) - 1:
            amounts[idx] = amount_cents - running
        else:
            amt = dec_rhu_int(Decimal(amount_cents) * Decimal(splits[idx]["split_pct"]) / Decimal(100))
            amounts[idx] = amt
            running += amt
    return amounts


@bp.post("/advancement/gift-payments")
def create_payment():
    user_id, role = authenticate()
    authorize(role, ["FinanceSteward"])
    body = body_json()
    check_unknown_fields(body, {"donor_prospect_id", "pledge_id", "fund_id", "campaign_id",
                                "amount_cents", "received_at", "payment_method",
                                "corporate_matched", "splits"})
    donor_prospect_id = req_str(body, "donor_prospect_id")
    amount_cents = req_money(body, "amount_cents")
    received_at = parse_dt(body.get("received_at"), "received_at")
    payment_method = req_enum(body, "payment_method", {"CHECK", "WIRE", "CARD", "STOCK"})
    pledge_id = opt_str(body, "pledge_id")
    fund_id = opt_str(body, "fund_id")
    campaign_id = opt_str(body, "campaign_id")
    corporate_matched = req_bool(body, "corporate_matched", default=False)
    splits = body.get("splits")
    if splits is not None:
        _validate_splits_shape(splits)
    # existence (priority 4)
    donor = store["prospects"].get(donor_prospect_id)
    if donor is None:
        fail(ERR_PROSPECT_NOT_FOUND, "donor_prospect_id does not resolve")
    pledge = None
    if pledge_id is not None:
        pledge = store["pledges"].get(pledge_id)
        if pledge is None:
            fail(ERR_PLEDGE_NOT_FOUND, "pledge_id does not resolve")
    payload_fund = None
    if fund_id is not None:
        payload_fund = store["funds"].get(fund_id)
        if payload_fund is None:
            fail(ERR_FUND_NOT_FOUND, "fund_id does not resolve")
    campaign = None
    if campaign_id is not None:
        campaign = store["campaigns"].get(campaign_id)
        if campaign is None:
            fail(ERR_CAMPAIGN_NOT_FOUND, "campaign_id does not resolve")
    if splits is not None:
        for entry in splits:
            if entry["prospect_id"] not in store["prospects"]:
                fail(ERR_PROSPECT_NOT_FOUND, "split prospect_id does not resolve")
    # state preconditions (priority 8)
    if pledge is not None and pledge["status"] != "ACTIVE":
        fail(ERR_PLEDGE_NOT_ACTIVE, "Pledge-linked payment requires an ACTIVE pledge")
    credited_fund = None
    if pledge is not None:
        if pledge["fund_id"] is not None:
            credited_fund = store["funds"].get(pledge["fund_id"])
    elif payload_fund is not None:
        credited_fund = payload_fund
    if credited_fund is not None and credited_fund["status"] == "CLOSED":
        fail(ERR_FUND_NOT_ACTIVE, "Payment cannot credit a CLOSED fund")
    if campaign is not None and campaign["status"] != "ACTIVE":
        fail(ERR_CAMPAIGN_INVALID_STATE, "Campaign must be ACTIVE to receive a payment")
    # stewardship gate (priority 9)
    if credited_fund is not None and credited_fund["status"] == "SPENDING_FROZEN":
        fail(ERR_STEWARDSHIP_LAPSED, "Payment cannot credit a SPENDING_FROZEN fund")
    # cross-reference consistency (priority 10)
    if pledge is not None and fund_id is not None and fund_id != pledge["fund_id"]:
        fail(ERR_FUND_PLEDGE_MISMATCH, "fund_id must equal the pledge's fund_id")
    # temporal window (priority 12)
    if campaign is not None and not (campaign["counting_start"] <= received_at <= campaign["counting_end"]):
        fail(ERR_OUTSIDE_COUNTING_WINDOW, "received_at is outside the campaign counting window")
    # fiscal limits (priority 13)
    if pledge is not None and amount_cents > pledge_outstanding_cents(pledge):
        fail(ERR_PAYMENT_EXCEEDS_OUTSTANDING, "Payment exceeds the pledge's outstanding balance")
    if splits is not None:
        _validate_splits_semantics(splits, donor_prospect_id)

    entity = new_entity()
    entity.update({
        "donor_prospect_id": donor_prospect_id,
        "pledge_id": pledge_id,
        "fund_id": credited_fund["id"] if credited_fund is not None else None,
        "campaign_id": campaign_id,
        "amount_cents": amount_cents,
        "received_at": received_at,
        "payment_method": payment_method,
        "corporate_matched": corporate_matched,
        "splits": splits,
        "applied_allocations": [],
        "reversed": False,
        "reversed_at": None,
    })
    store["payments"][entity["id"]] = entity

    # waterfall: earliest obligation first (due_date ASC, sequence_number ASC)
    if pledge is not None:
        remaining = amount_cents
        targets = sorted(open_installments(pledge), key=lambda i: (i["due_date"], i["sequence_number"]))
        for inst in targets:
            if remaining <= 0:
                break
            open_cents = inst["amount_cents"] - inst["paid_cents"] - inst["written_off_cents"]
            applied = min(remaining, open_cents)
            inst["paid_cents"] += applied
            remaining -= applied
            if inst["paid_cents"] >= inst["amount_cents"] and inst["written_off_cents"] == 0:
                inst["status"] = "PAID"
            elif inst["paid_cents"] + inst["written_off_cents"] >= inst["amount_cents"] and inst["paid_cents"] > 0:
                inst["status"] = "PAID"
            touch(inst)
            entity["applied_allocations"].append(
                {"installment_id": inst["id"], "applied_cents": applied})
        reevaluate_pledge_status(pledge)
        touch(pledge)

    # fund credit and activation threshold
    if credited_fund is not None:
        credited_fund["balance_cents"] += amount_cents
        if (credited_fund["status"] == "PENDING_MINIMUM"
                and credited_fund["balance_cents"] >= credited_fund["minimum_activation_cents"]):
            credited_fund["status"] = "ACTIVE"
        touch(credited_fund)

    # credit splits (smallest-rounded-first; largest absorbs the residual)
    # Created BEFORE the campaign recompute: the HARD split's amount is the
    # payment's counted contribution (PRD §3.7), so the rows must exist first.
    if splits is not None:
        amounts = _compute_split_amounts(amount_cents, splits)
        for idx, entry in enumerate(splits):
            split = new_entity()
            split.update({
                "campaign_id": campaign_id,
                "gift_payment_id": entity["id"],
                "prospect_id": entry["prospect_id"],
                "credit_type": entry["credit_type"],
                "split_pct": entry["split_pct"],
                "amount_cents": amounts[idx],
            })
            store["credit_splits"][split["id"]] = split

    # campaign totals under both variants
    if campaign is not None:
        recompute_campaign_totals(campaign)

    # donor aggregates and recognition recompute
    refresh_prospect_recognition(donor)
    touch(donor)

    return success_object(ser_payment(entity), 201)


@bp.get("/advancement/gift-payments/<gid>")
def get_payment(gid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    payment = store["payments"].get(gid)
    if payment is None:
        fail(ERR_PAYMENT_NOT_FOUND, "Payment not found")
    return success_object(ser_payment(payment))


@bp.get("/advancement/gift-payments")
def list_payments():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store["payments"].values())
    for param in ("pledge_id", "fund_id", "campaign_id", "donor_prospect_id"):
        value = request.args.get(param)
        if value is not None:
            items = [g for g in items if g.get(param) == value]
    page, limit, offset, total = paginate(items)
    return success_list([ser_payment(g) for g in page], limit, offset, total)


@bp.post("/advancement/gift-payments/<gid>/reverse")
def reverse_payment(gid):
    user_id, role = authenticate()
    authorize(role, ["FinanceSteward"])
    body_json()  # no documented inputs
    payment = store["payments"].get(gid)
    if payment is None:
        fail(ERR_PAYMENT_NOT_FOUND, "Payment not found")
    if payment["reversed"]:
        fail(ERR_PAYMENT_ALREADY_REVERSED, "Payment is already reversed")
    payment["reversed"] = True
    payment["reversed_at"] = now()
    touch(payment)

    # withdraw allocations; reopen PAID installments
    current = now()
    for alloc in payment["applied_allocations"]:
        inst = store["installments"].get(alloc["installment_id"])
        if inst is None:
            continue
        inst["paid_cents"] -= alloc["applied_cents"]
        if inst["status"] == "PAID":
            if current > inst["due_date"] + timedelta(days=30):
                inst["status"] = "OVERDUE"
            elif inst["reminder_count"] > 0:
                inst["status"] = "REMINDED"
            else:
                inst["status"] = "SCHEDULED"
        touch(inst)

    # pledge re-evaluation (FULFILLED -> ACTIVE, etc.)
    if payment["pledge_id"] is not None:
        pledge = store["pledges"].get(payment["pledge_id"])
        if pledge is not None:
            reevaluate_pledge_status(pledge)
            touch(pledge)

    # fund debit and de-activation
    if payment["fund_id"] is not None:
        fund = store["funds"].get(payment["fund_id"])
        if fund is not None:
            fund["balance_cents"] -= payment["amount_cents"]
            if fund["status"] == "ACTIVE" and fund["balance_cents"] < fund["minimum_activation_cents"]:
                fund["status"] = "PENDING_MINIMUM"
            touch(fund)

    # campaign totals decrement (unless frozen at close)
    if payment["campaign_id"] is not None:
        campaign = store["campaigns"].get(payment["campaign_id"])
        if campaign is not None:
            recompute_campaign_totals(campaign)

    # donor aggregates and recognition recompute
    donor = store["prospects"].get(payment["donor_prospect_id"])
    if donor is not None:
        refresh_prospect_recognition(donor)
        touch(donor)

    return success_object(ser_payment(payment))


@bp.get("/advancement/gift-payments/<gid>/credit-splits")
def list_payment_credit_splits(gid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    if gid not in store["payments"]:
        fail(ERR_PAYMENT_NOT_FOUND, "Payment not found")
    items = [s for s in store["credit_splits"].values() if s["gift_payment_id"] == gid]
    credit_type = request.args.get("credit_type")
    if credit_type is not None:
        items = [s for s in items if s["credit_type"] == credit_type]
    page, limit, offset, total = paginate(items)
    return success_list([ser_credit_split(s) for s in page], limit, offset, total)
