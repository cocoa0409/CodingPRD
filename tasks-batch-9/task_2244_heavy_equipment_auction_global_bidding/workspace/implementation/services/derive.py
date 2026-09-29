"""Derived-field recomputation, invoice stamping and the cascades."""
from datetime import timedelta
from decimal import Decimal

from db import db, new_entity, touch
from errors import ApiError
from services import constants as C
from services.calculations import (
    base_headroom, buyer_premium, commission_for, deficiency_claim,
    forecast_exposure, payment_terms_for, prior_hammer_total,
    registration_forecast_cap, sale_sort_key, storage_accrual,
)
from services.money import pct, round_half_up


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def fetch(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def rows_of(collection, **filters):
    out = []
    for row in collection.values():
        for field, expected in filters.items():
            if row.get(field) != expected:
                break
        else:
            out.append(row)
    return out


def lot_of_invoice(invoice):
    sale = db.sales[invoice["sale_id"]]
    return db.lots[sale["lot_id"]]


def consignment_of_lot(lot):
    return db.consignments[lot["consignment_id"]]


def consignor_of_lot(lot):
    return db.consignors[consignment_of_lot(lot)["consignor_id"]]


# --------------------------------------------------------------------------
# derived counters
# --------------------------------------------------------------------------
def recompute_bay(bay):
    total = 0
    for slot in db.loadout_slots.values():
        if slot["bay_id"] == bay["id"] and slot["status"] in ("BOOKED", "CHECKED_IN"):
            total += slot["tonnage_kg"] or 0
    bay["reserved_tonnage_kg"] = total


def recompute_all_bays():
    for bay in db.loadout_bays.values():
        recompute_bay(bay)


def recompute_consignor(consignor):
    open_states = ("DRAFT", "SUBMITTED", "INTAKE_ACCEPTED", "CATALOGED")
    consignor["open_consignment_count"] = len([
        c for c in db.consignments.values()
        if c["consignor_id"] == consignor["id"] and c["status"] in open_states
    ])
    lifetime = 0
    for settlement in db.consignor_settlements.values():
        if settlement["status"] != "POSTED":
            continue
        sale = db.sales.get(settlement["sale_id"])
        if not sale:
            continue
        lot = db.lots.get(sale["lot_id"])
        if not lot:
            continue
        consignment = db.consignments.get(lot["consignment_id"])
        if not consignment or consignment["consignor_id"] != consignor["id"]:
            continue
        lifetime += settlement["net_proceeds_cents"] or 0
    consignor["lifetime_net_proceeds_cents"] = lifetime


def recompute_consignment(consignment):
    lots = [l for l in db.lots.values() if l["consignment_id"] == consignment["id"]]
    consignment["unsold_lot_count"] = len(
        [l for l in lots if l["lifecycle_status"] == "UNSOLD"])
    consignment["reoffer_lot_count"] = len(
        [l for l in lots if l["lifecycle_status"] == "REOFFER_QUEUED"])
    recovered = 0
    for settlement in db.consignor_settlements.values():
        if settlement["status"] != "POSTED":
            continue
        sale = db.sales.get(settlement["sale_id"])
        if not sale:
            continue
        lot = db.lots.get(sale["lot_id"])
        if not lot or lot["consignment_id"] != consignment["id"]:
            continue
        recovered += settlement["advance_recovery_cents"] or 0
    consignment["advance_outstanding_cents"] = max(
        0, (consignment["advance_paid_cents"] or 0) - recovered)


def recompute_lot_high_bid(lot):
    best = 0
    for bid in db.bids.values():
        if bid["lot_id"] == lot["id"] and bid["status"] == "ACTIVE":
            if bid["amount_cents"] > best:
                best = bid["amount_cents"]
    lot["high_bid_cents"] = best


def recompute_auction(auction):
    lots = [l for l in db.lots.values() if l["auction_id"] == auction["id"]]
    auction["assigned_lot_count"] = len(
        [l for l in lots if l["lifecycle_status"] != "WITHDRAWN"])
    auction["unsold_lot_count"] = len(
        [l for l in lots if l["lifecycle_status"] == "UNSOLD"])
    sales = [s for s in db.sales.values() if s["auction_id"] == auction["id"]]
    sold_states = ("PROVISIONAL", "CONSIGNOR_COUNTERED", "CONFIRMED", "SETTLED",
                   "DEFAULTED")
    auction["sold_lot_count"] = len([s for s in sales if s["status"] in sold_states])
    auction["gross_hammer_cents"] = sum(
        (s["hammer_price_cents"] or 0) for s in sales
        if s["status"] in ("CONFIRMED", "SETTLED"))


def recompute_bidder(bidder):
    exposure = 0
    lifetime = 0
    for invoice in db.invoices.values():
        if invoice["bidder_id"] != bidder["id"]:
            continue
        sale = db.sales.get(invoice["sale_id"])
        if not sale:
            continue
        if (invoice["payment_status"] in ("UNPAID", "PARTIALLY_PAID")
                and sale["status"] in ("CONFIRMED", "SETTLED")):
            exposure += invoice["total_due_cents"] or 0
    for sale in db.sales.values():
        if sale["status"] != "SETTLED":
            continue
        registration = db.bidder_registrations.get(sale["registration_id"])
        if registration and registration["bidder_id"] == bidder["id"]:
            lifetime += sale["hammer_price_cents"] or 0
    bidder["open_exposure_cents"] = exposure
    bidder["lifetime_purchase_cents"] = lifetime
    bidder["deposit_total_cents"] = (
        bidder["deposit_held_cents"] + bidder["deposit_available_cents"]
        + bidder["deposit_forfeited_cents"])


def recompute_registration_cap(registration):
    if registration["status"] == "SUSPENDED":
        registration["bid_cap_cents"] = 0
        return
    if registration["leverage_multiplier"] is None:
        registration["bid_cap_cents"] = 0
        return
    cap, _exposure = registration_forecast_cap(registration)
    registration["bid_cap_cents"] = cap


# --------------------------------------------------------------------------
# invoice stamping (PRD 3.7)
# --------------------------------------------------------------------------
def invoice_context(invoice):
    sale = db.sales[invoice["sale_id"]]
    lot = db.lots[sale["lot_id"]]
    auction = db.auctions[sale["auction_id"]]
    yard = db.yards[auction["yard_id"]]
    registration = db.bidder_registrations[invoice["registration_id"]]
    bidder = db.bidders[registration["bidder_id"]]
    return sale, lot, auction, yard, registration, bidder


def compute_invoice_fields(invoice, variant):
    sale, lot, auction, yard, registration, bidder = invoice_context(invoice)
    hammer = sale["hammer_price_cents"] or 0
    cross_border = bidder["country_code"] != yard["country_code"]

    premium = buyer_premium(hammer, auction, prior_hammer_total(sale))
    doc_fee = (C.DOC_FEE_CROSS_BORDER_CENTS if cross_border
               else C.DOC_FEE_DOMESTIC_CENTS)
    title_fee = C.TITLE_TRANSFER_FEE_CENTS if lot["title_required"] else 0
    financing_fee = (pct(hammer, C.FINANCING_FEE_RATE)
                     if registration["financing_approved"] else 0)
    subtotal = hammer + premium + doc_fee + title_fee + financing_fee

    zero_rated = False
    if variant == "FINAL" and cross_border:
        for packet in db.export_packets.values():
            if (packet["invoice_id"] == invoice["id"]
                    and packet["status"] == "EXPORT_CLEARED"):
                zero_rated = True
                break
    if zero_rated:
        rate = Decimal("0")
    else:
        rate = C.TAX_RATE_BY_COUNTRY.get(bidder["country_code"], C.DEFAULT_TAX_RATE)
    tax = pct(subtotal, rate)

    terms = payment_terms_for(registration)
    grace_end_at = sale["hammered_at"] + timedelta(
        days=C.FREE_STORAGE_DAYS_BY_TERMS[terms])
    payment_due_at = sale["hammered_at"] + timedelta(days=C.DUE_DAYS_BY_TERMS[terms])

    if variant == "PROVISIONAL":
        storage_days, storage_fee = 0, 0
    else:
        storage_days, storage_fee = storage_accrual(
            grace_end_at, db.now(), lot["weight_kg"], hammer)

    return {
        "settlement_variant": variant,
        "hammer_price_cents": hammer,
        "is_cross_border": cross_border,
        "buyer_premium_cents": premium,
        "documentation_fee_cents": doc_fee,
        "title_transfer_fee_cents": title_fee,
        "financing_fee_cents": financing_fee,
        "subtotal_cents": subtotal,
        "tax_rate_applied": round_half_up(rate, 4),
        "tax_cents": tax,
        "chargeable_storage_days": storage_days,
        "storage_fee_cents": storage_fee,
        "grace_end_at": grace_end_at,
        "payment_due_at": payment_due_at,
    }


def gross_before_deposit(fields, credit_memo_cents):
    return (fields["subtotal_cents"] + fields["tax_cents"]
            + fields["storage_fee_cents"] - credit_memo_cents)


def _waterfall_key(invoice):
    sale = db.sales.get(invoice["sale_id"])
    hammered = sale["hammered_at"] if sale else invoice["created_at"]
    return (hammered, invoice["created_at"], invoice["_seq"])


def recompute_deposit_waterfall(registration):
    """Consume the registration's hold across its invoices, oldest sale first."""
    invoices = sorted(
        [i for i in db.invoices.values()
         if i["registration_id"] == registration["id"]],
        key=_waterfall_key,
    )
    remaining = registration["deposit_hold_cents"] or 0
    applied_total = 0
    for invoice in invoices:
        gross = (invoice["subtotal_cents"] + invoice["tax_cents"]
                 + invoice["storage_fee_cents"] - invoice["credit_memo_cents"])
        applied = min(remaining, max(0, gross))
        remaining -= applied
        applied_total += applied
        invoice["deposit_applied_cents"] = applied
        invoice["total_due_cents"] = gross - applied
        invoice["outstanding_cents"] = max(
            0, invoice["total_due_cents"] - invoice["amount_paid_cents"])
    registration["deposit_applied_total_cents"] = applied_total


def preview_deposit_applied(target_invoice, target_gross):
    invoices = sorted(
        [i for i in db.invoices.values()
         if i["registration_id"] == target_invoice["registration_id"]],
        key=_waterfall_key,
    )
    registration = db.bidder_registrations[target_invoice["registration_id"]]
    remaining = registration["deposit_hold_cents"] or 0
    result = 0
    for invoice in invoices:
        if invoice["id"] == target_invoice["id"]:
            gross = target_gross
        else:
            gross = (invoice["subtotal_cents"] + invoice["tax_cents"]
                     + invoice["storage_fee_cents"] - invoice["credit_memo_cents"])
        applied = min(remaining, max(0, gross))
        remaining -= applied
        if invoice["id"] == target_invoice["id"]:
            result = applied
    return result


def refresh_registration_money(registration):
    recompute_deposit_waterfall(registration)
    recompute_registration_cap(registration)
    bidder = db.bidders.get(registration["bidder_id"])
    if bidder:
        recompute_bidder(bidder)


def stamp_invoice(invoice, variant):
    invoice.update(compute_invoice_fields(invoice, variant))
    registration = db.bidder_registrations[invoice["registration_id"]]
    refresh_registration_money(registration)


def apply_payment_status(invoice):
    if invoice["payment_status"] in ("IN_DEFAULT", "WRITTEN_OFF"):
        return
    if invoice["outstanding_cents"] <= 0:
        invoice["payment_status"] = "PAID"
    elif invoice["amount_paid_cents"] > 0:
        invoice["payment_status"] = "PARTIALLY_PAID"
    else:
        invoice["payment_status"] = "UNPAID"


def recompute_invoice_paid(invoice):
    paid = 0
    for payment in db.payments.values():
        if payment["invoice_id"] == invoice["id"] and payment["status"] == "SETTLED":
            paid += payment["amount_cents"]
    invoice["amount_paid_cents"] = paid
    invoice["outstanding_cents"] = max(0, invoice["total_due_cents"] - paid)


def create_invoice_for_sale(sale):
    registration = db.bidder_registrations[sale["registration_id"]]
    invoice = new_entity()
    invoice.update({
        "sale_id": sale["id"],
        "bidder_id": registration["bidder_id"],
        "registration_id": registration["id"],
        "settlement_variant": "PROVISIONAL",
        "hammer_price_cents": sale["hammer_price_cents"],
        "is_cross_border": False,
        "buyer_premium_cents": 0,
        "documentation_fee_cents": 0,
        "title_transfer_fee_cents": 0,
        "financing_fee_cents": 0,
        "subtotal_cents": 0,
        "tax_rate_applied": 0,
        "tax_cents": 0,
        "chargeable_storage_days": 0,
        "storage_fee_cents": 0,
        "credit_memo_cents": 0,
        "deposit_applied_cents": 0,
        "total_due_cents": 0,
        "amount_paid_cents": 0,
        "outstanding_cents": 0,
        "grace_end_at": None,
        "payment_due_at": None,
        "deficiency_claim_cents": 0,
        "payment_status": "UNPAID",
        "release_status": "HELD",
    })
    db.invoices[invoice["id"]] = invoice
    stamp_invoice(invoice, "PROVISIONAL")
    return invoice


# --------------------------------------------------------------------------
# hammer / close (PRD 3.6)
# --------------------------------------------------------------------------
def reserve_is_met(lot, auction, hammer_price_cents):
    if auction["reserve_policy"] == "UNRESERVED":
        return True
    if lot["reserve_price_cents"] is None:
        return True
    return hammer_price_cents >= lot["reserve_price_cents"]


def knock_down(lot, auction):
    """Turn the leading ACTIVE bid into a Sale (and Invoice when reserve is met)."""
    active = [b for b in db.bids.values()
              if b["lot_id"] == lot["id"] and b["status"] == "ACTIVE"]
    active.sort(key=lambda b: (-b["amount_cents"], b["_seq"]))
    winner = active[0]
    for bid in active:
        bid["status"] = "WINNING" if bid["id"] == winner["id"] else "LOSING"

    lot["lifecycle_status"] = "HAMMERED"
    touch(lot)

    hammer_price = winner["amount_cents"]
    reserve_met = reserve_is_met(lot, auction, hammer_price)
    sale = new_entity()
    sale.update({
        "lot_id": lot["id"],
        "auction_id": auction["id"],
        "winning_bid_id": winner["id"],
        "registration_id": winner["registration_id"],
        "hammer_price_cents": hammer_price,
        "reserve_met": reserve_met,
        "hammered_at": db.now(),
        "counter_round": 0,
        "counter_price_cents": None,
        "reject_reason": None,
        "status": "CONFIRMED" if reserve_met else "PROVISIONAL",
    })
    db.sales[sale["id"]] = sale

    if reserve_met:
        create_invoice_for_sale(sale)

    recompute_auction(auction)
    registration = db.bidder_registrations[sale["registration_id"]]
    refresh_registration_money(registration)
    return sale


def close_auction(auction):
    auction["status"] = "CLOSED"
    lots = [l for l in db.lots.values()
            if l["auction_id"] == auction["id"] and l["lifecycle_status"] == "ASSIGNED"]
    for lot in sorted(lots, key=lambda l: (l["created_at"], l["_seq"])):
        if (lot["high_bid_cents"] or 0) > 0:
            knock_down(lot, auction)
        else:
            lot["lifecycle_status"] = "UNSOLD"
            touch(lot)
            recompute_consignment(db.consignments[lot["consignment_id"]])
    recompute_auction(auction)
    touch(auction)


# --------------------------------------------------------------------------
# consignor settlement (PRD 3.9)
# --------------------------------------------------------------------------
def post_settlement(sale):
    lot = db.lots[sale["lot_id"]]
    consignment = db.consignments[lot["consignment_id"]]
    gross = sale["hammer_price_cents"] or 0

    commission = commission_for(consignment["commission_schedule_code"], gross)

    refurb_actual = 0
    for order in db.refurbishment_orders.values():
        if order["lot_id"] == lot["id"] and order["status"] == "COMPLETED":
            refurb_actual += order["actual_cost_cents"] or 0

    already_recharged = 0
    for settlement in db.consignor_settlements.values():
        if settlement["status"] != "POSTED":
            continue
        other_sale = db.sales.get(settlement["sale_id"])
        if not other_sale:
            continue
        other_lot = db.lots.get(other_sale["lot_id"])
        if not other_lot or other_lot["consignment_id"] != consignment["id"]:
            continue
        already_recharged += settlement["refurb_recharge_cents"] or 0
    remaining_authorization = max(
        0, (consignment["refurb_authorization_cap_cents"] or 0) - already_recharged)
    refurb_recharge = min(refurb_actual, remaining_authorization)
    house_absorbed = refurb_actual - refurb_recharge

    remaining = gross - commission - refurb_recharge
    advance_recovery = min(
        consignment["advance_outstanding_cents"] or 0, max(0, remaining))

    no_sale_fee = 0
    net = gross - commission - refurb_recharge - advance_recovery - no_sale_fee

    settlement = new_entity()
    settlement.update({
        "sale_id": sale["id"],
        "gross_proceeds_cents": gross,
        "commission_cents": commission,
        "refurb_recharge_cents": refurb_recharge,
        "house_absorbed_refurb_cents": house_absorbed,
        "advance_recovery_cents": advance_recovery,
        "no_sale_fee_cents": no_sale_fee,
        "net_proceeds_cents": net,
        "status": "POSTED",
    })
    db.consignor_settlements[settlement["id"]] = settlement

    sale["status"] = "SETTLED"
    touch(sale)

    if lot["lifecycle_status"] == "HAMMERED":
        lot["lifecycle_status"] = "SETTLED"
        touch(lot)

    recompute_consignment(consignment)
    recompute_consignor(db.consignors[consignment["consignor_id"]])
    auction = db.auctions.get(sale["auction_id"])
    if auction:
        recompute_auction(auction)
    registration = db.bidder_registrations.get(sale["registration_id"])
    if registration:
        refresh_registration_money(registration)
    return settlement


def reverse_settlement(settlement):
    settlement["gross_proceeds_cents"] = 0
    settlement["commission_cents"] = 0
    settlement["refurb_recharge_cents"] = 0
    settlement["advance_recovery_cents"] = 0
    settlement["no_sale_fee_cents"] = C.NO_SALE_FEE_CENTS
    settlement["net_proceeds_cents"] = -C.NO_SALE_FEE_CENTS
    settlement["status"] = "REVERSED"
    touch(settlement)


# --------------------------------------------------------------------------
# abandonment cascade (PRD 3.8)
# --------------------------------------------------------------------------
def abandon_invoice(invoice):
    sale = db.sales[invoice["sale_id"]]
    lot = db.lots[sale["lot_id"]]
    registration = db.bidder_registrations[invoice["registration_id"]]
    bidder = db.bidders[registration["bidder_id"]]

    # ---- depth 1: the invoice itself -------------------------------------
    invoice["payment_status"] = "WRITTEN_OFF"
    invoice["release_status"] = "ABANDONED"

    grace_end_at = invoice["grace_end_at"]
    storage_days, storage_fee = storage_accrual(
        grace_end_at, db.now(), lot["weight_kg"], sale["hammer_price_cents"] or 0)
    invoice["chargeable_storage_days"] = storage_days
    invoice["storage_fee_cents"] = storage_fee

    cash_tendered = invoice["amount_paid_cents"]
    invoice["deficiency_claim_cents"] = deficiency_claim(
        sale["hammer_price_cents"] or 0,
        storage_fee,
        registration["deposit_hold_cents"] or 0,
        cash_tendered,
    )

    for payment in db.payments.values():
        if payment["invoice_id"] == invoice["id"] and payment["status"] == "SETTLED":
            payment["status"] = "REVERSED"
    invoice["amount_paid_cents"] = 0

    touched_bays = set()
    for slot in db.loadout_slots.values():
        if slot["invoice_id"] == invoice["id"] and slot["status"] in (
                "BOOKED", "CHECKED_IN"):
            slot["status"] = "CANCELLED"
            slot["cancel_reason"] = "ABANDONED"
            touch(slot)
            touched_bays.add(slot["bay_id"])
    for bay_id in touched_bays:
        bay = db.loadout_bays.get(bay_id)
        if bay:
            recompute_bay(bay)

    hold = registration["deposit_hold_cents"] or 0
    forfeit = min(hold, bidder["deposit_held_cents"])
    bidder["deposit_held_cents"] -= forfeit
    bidder["deposit_forfeited_cents"] += forfeit

    # ---- depth 2: the sale ----------------------------------------------
    settlement_reversed = False
    if sale["status"] in ("SETTLED", "CONFIRMED"):
        sale["status"] = "DEFAULTED"
        touch(sale)
    bidder["default_strike_count"] += 1
    if bidder["default_strike_count"] >= C.MAX_DEFAULT_STRIKES:
        for reg in db.bidder_registrations.values():
            if reg["bidder_id"] == bidder["id"] and reg["status"] == "APPROVED":
                reg["status"] = "SUSPENDED"
                reg["bid_cap_cents"] = 0
                touch(reg)
    auction = db.auctions.get(sale["auction_id"])
    if auction:
        recompute_auction(auction)

    # ---- depth 3: the consignor settlement -------------------------------
    for settlement in db.consignor_settlements.values():
        if settlement["sale_id"] == sale["id"] and settlement["status"] == "POSTED":
            reverse_settlement(settlement)
            settlement_reversed = True
    consignment = db.consignments[lot["consignment_id"]]
    if settlement_reversed:
        recompute_consignment(consignment)
        recompute_consignor(db.consignors[consignment["consignor_id"]])

    # ---- depth 4: the lot ------------------------------------------------
    if settlement_reversed and lot["lifecycle_status"] == "SETTLED":
        lot["lifecycle_status"] = "REOFFER_QUEUED"
        touch(lot)
        recompute_consignment(consignment)

    refresh_registration_money(registration)
    recompute_bidder(bidder)
    touch(invoice)
