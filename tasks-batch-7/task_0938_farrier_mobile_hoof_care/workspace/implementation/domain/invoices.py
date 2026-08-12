"""Invoice assembly, its line rows and the trip-fee split (PRD 3.9).

The evaluation order below is PINNED: each step feeds the next and no
intermediate value is ever re-rounded.
"""

from core.constants import (
    LOYALTY_PREMIER_BP,
    LOYALTY_PREMIER_THRESHOLD_VISITS,
    LOYALTY_STANDARD_BP,
    LOYALTY_THRESHOLD_VISITS,
    MULTI_HORSE_DISCOUNT_BP,
    MULTI_HORSE_DISCOUNT_MIN_HORSES,
    PRODUCT_TAX_RATE_BP,
    TRIP_FEE_BILLABLE_STATUSES,
    ZONE_TO_TRIP_FEE_FIELD,
)
from core.store import db, order_key

from .money import apply_bp, round_half_up_div
from .rates import select_rate_card


def _lines(appointment, status):
    rows = [
        line
        for line in db.service_lines.values()
        if line["appointment_id"] == appointment["id"] and line["status"] == status
    ]
    rows.sort(key=order_key)
    return rows


def _reservations(appointment, status):
    rows = [
        r
        for r in db.shoe_reservations.values()
        if r["appointment_id"] == appointment["id"] and r["status"] == status
    ]
    rows.sort(key=order_key)
    return rows


def invoice_of_appointment(appointment):
    for invoice in db.invoices.values():
        if invoice["appointment_id"] == appointment["id"]:
            return invoice
    return None


def mint_invoice(appointment, card, fee_kind=None):
    horse = db.get("horses", appointment["horse_id"])
    invoice = db.mint(
        "invoices",
        {
            "appointment_id": appointment["id"],
            "client_id": horse["client_id"],
            "rate_card_id": card["id"] if card else None,
            "status": "DRAFT",
            "issued_on": None,
            "labor_subtotal_cents": 0,
            "product_subtotal_cents": 0,
            "multi_horse_discount_cents": 0,
            "loyalty_discount_cents": 0,
            "loyalty_discount_labor_cents": 0,
            "loyalty_discount_product_cents": 0,
            "labor_net_cents": 0,
            "trip_fee_share_cents": 0,
            "fee_cents": 0,
            "taxable_product_base_cents": 0,
            "tax_cents": 0,
            "total_cents": 0,
            "paid_cents": 0,
            "balance_cents": 0,
            "_fee_kind": fee_kind,
        },
    )
    build_invoice(invoice)
    return invoice


def build_invoice(invoice):
    """Run the pinned 13-step sequence and regenerate the invoice's line rows."""
    appointment = db.get("appointments", invoice["appointment_id"])
    horse = db.get("horses", appointment["horse_id"])
    client = db.get("clients", horse["client_id"])
    card = db.get("rate_cards", invoice["rate_card_id"])
    performed = _lines(appointment, "PERFORMED")
    committed = _reservations(appointment, "COMMITTED")
    stop = db.get("route_stops", appointment.get("route_stop_id"))

    # 1. labour subtotal -- each line's surcharge was already rounded on its own.
    labor_subtotal = sum(line["labor_cents"] for line in performed)

    # 2. product subtotal -- committed pairs plus one pad per padded performed line.
    pair_amount = 0
    for reservation in committed:
        sku = db.get("shoe_skus", reservation["sku_id"])
        if sku:
            pair_amount += reservation["pairs"] * sku["price_cents_per_pair"]
    pad_count = sum(1 for line in performed if line["with_pad"])
    pad_price = card["pad_price_cents"] if card else 0
    product_subtotal = pair_amount + pad_price * pad_count

    # 3. multi-horse discount -- labour only, and only at a stop billing enough horses.
    if stop is not None and stop["billable_horse_count"] >= MULTI_HORSE_DISCOUNT_MIN_HORSES:
        multi_horse = apply_bp(labor_subtotal, MULTI_HORSE_DISCOUNT_BP)
    else:
        multi_horse = 0

    # 4. labour after the multi-horse discount.
    labor_after_mh = labor_subtotal - multi_horse

    # 5. loyalty discount over labour-after-multi-horse plus product.
    loyalty_base = labor_after_mh + product_subtotal
    visits = client["completed_visit_count"]
    if visits >= LOYALTY_PREMIER_THRESHOLD_VISITS:
        bp = LOYALTY_PREMIER_BP
    elif visits >= LOYALTY_THRESHOLD_VISITS:
        bp = LOYALTY_STANDARD_BP
    else:
        bp = 0
    loyalty = apply_bp(loyalty_base, bp)

    # 6. split: the PRODUCT leg is the rounded one, labour absorbs the remainder.
    if loyalty_base == 0:
        loyalty_product = 0
    else:
        loyalty_product = round_half_up_div(loyalty * product_subtotal, loyalty_base)
    loyalty_labor = loyalty - loyalty_product

    # 7-8.
    labor_net = labor_after_mh - loyalty_labor
    taxable_product_base = product_subtotal - loyalty_product

    # 9. tax -- product base only; labour, trip fee and fees are always untaxed.
    tax = 0 if client["tax_exempt"] else apply_bp(taxable_product_base, PRODUCT_TAX_RATE_BP)

    # 10-11.
    trip_fee_share = invoice["trip_fee_share_cents"]
    fee = appointment["cancellation_fee_cents"]

    # 12-13.
    total = labor_net + taxable_product_base + trip_fee_share + fee + tax
    balance = total - invoice["paid_cents"]

    invoice["labor_subtotal_cents"] = labor_subtotal
    invoice["product_subtotal_cents"] = product_subtotal
    invoice["multi_horse_discount_cents"] = multi_horse
    invoice["loyalty_discount_cents"] = loyalty
    invoice["loyalty_discount_labor_cents"] = loyalty_labor
    invoice["loyalty_discount_product_cents"] = loyalty_product
    invoice["labor_net_cents"] = labor_net
    invoice["taxable_product_base_cents"] = taxable_product_base
    invoice["tax_cents"] = tax
    invoice["trip_fee_share_cents"] = trip_fee_share
    invoice["fee_cents"] = fee
    invoice["total_cents"] = total
    invoice["balance_cents"] = balance

    _rebuild_lines(invoice, appointment, performed, committed, card, pad_price)
    return invoice


LIMB_LABEL = {"LF": "left fore", "RF": "right fore", "LH": "left hind", "RH": "right hind"}


def _rebuild_lines(invoice, appointment, performed, committed, card, pad_price):
    for line_id in [
        row["id"] for row in db.invoice_lines.values() if row["invoice_id"] == invoice["id"]
    ]:
        del db.invoice_lines[line_id]

    def emit(**fields):
        row = {
            "invoice_id": invoice["id"],
            "line_kind": fields["line_kind"],
            "description": fields["description"],
            "limb": fields.get("limb"),
            "service_type": fields.get("service_type"),
            "sku_code": fields.get("sku_code"),
            "quantity": fields.get("quantity", 1),
            "unit_amount_cents": fields.get("unit_amount_cents", 0),
            "amount_cents": fields.get("amount_cents", 0),
            "taxable": fields.get("taxable", False),
        }
        db.mint("invoice_lines", row, versioned=False)

    for line in performed:
        emit(
            line_kind="LABOR",
            description="%s on the %s" % (line["service_type"], LIMB_LABEL[line["limb"]]),
            limb=line["limb"],
            service_type=line["service_type"],
            quantity=1,
            unit_amount_cents=line["labor_cents"],
            amount_cents=line["labor_cents"],
            taxable=False,
        )
    for reservation in committed:
        sku = db.get("shoe_skus", reservation["sku_id"])
        if not sku:
            continue
        emit(
            line_kind="PRODUCT",
            description="Shoe pairs %s" % sku["sku_code"],
            sku_code=sku["sku_code"],
            quantity=reservation["pairs"],
            unit_amount_cents=sku["price_cents_per_pair"],
            amount_cents=reservation["pairs"] * sku["price_cents_per_pair"],
            taxable=True,
        )
    for line in performed:
        if not line["with_pad"]:
            continue
        emit(
            line_kind="PAD",
            description="Pad on the %s" % LIMB_LABEL[line["limb"]],
            limb=line["limb"],
            quantity=1,
            unit_amount_cents=pad_price,
            amount_cents=pad_price,
            taxable=True,
        )
    if invoice["trip_fee_share_cents"]:
        emit(
            line_kind="TRIP_FEE",
            description="Share of the stop's trip fee",
            quantity=1,
            unit_amount_cents=invoice["trip_fee_share_cents"],
            amount_cents=invoice["trip_fee_share_cents"],
            taxable=False,
        )
    if invoice["fee_cents"]:
        kind = invoice.get("_fee_kind") or "CANCELLATION_FEE"
        emit(
            line_kind=kind,
            description="No-show fee" if kind == "NO_SHOW_FEE" else "Cancellation fee",
            quantity=1,
            unit_amount_cents=invoice["fee_cents"],
            amount_cents=invoice["fee_cents"],
            taxable=False,
        )
    if invoice["multi_horse_discount_cents"]:
        emit(
            line_kind="MULTI_HORSE_DISCOUNT",
            description="Multi-horse labour discount",
            quantity=1,
            unit_amount_cents=-invoice["multi_horse_discount_cents"],
            amount_cents=-invoice["multi_horse_discount_cents"],
            taxable=False,
        )
    if invoice["loyalty_discount_cents"]:
        emit(
            line_kind="LOYALTY_DISCOUNT",
            description="Loyalty discount",
            quantity=1,
            unit_amount_cents=-invoice["loyalty_discount_cents"],
            amount_cents=-invoice["loyalty_discount_cents"],
            taxable=False,
        )
    if invoice["tax_cents"]:
        emit(
            line_kind="TAX",
            description="Product tax",
            quantity=1,
            unit_amount_cents=invoice["tax_cents"],
            amount_cents=invoice["tax_cents"],
            taxable=False,
        )


def allocate_trip_fee(stop):
    """Pin the stop's trip fee and split it across the billable appointments.

    # Adjudication of friction 12: the split is a ONE-SHOT at stop completion.
    # The specification declares stop completion as its only trigger, and a
    # stop cannot close while any attached appointment is still workable, so
    # every appointment in the billable set is already terminal
    # (COMPLETED / NO_SHOW / CANCELLED_ONSITE) and none of them has any
    # remaining transition that could remove it from the set.  A recomputation
    # trigger would therefore be dead code; the one-shot reading strands
    # nothing.
    """
    route = db.get("routes", stop["route_id"])
    barn = db.get("barns", stop["barn_id"])
    card = select_rate_card(route["route_date"], required=True)
    billable = [
        a
        for a in _stop_appointments(stop)
        if a["status"] in TRIP_FEE_BILLABLE_STATUSES
    ]
    if not billable:
        stop["trip_fee_cents"] = 0
        stop["billable_horse_count"] = 0
        return
    fee = card[ZONE_TO_TRIP_FEE_FIELD[barn["zone"]]]
    count = len(billable)
    stop["trip_fee_cents"] = fee
    stop["billable_horse_count"] = count
    base = fee // count
    remainder = fee - base * count
    for index, appointment in enumerate(billable):
        share = base + 1 if index < remainder else base
        appointment["trip_fee_share_cents"] = share
        db.touch(appointment)
        invoice = invoice_of_appointment(appointment)
        if invoice is None:
            continue
        invoice["trip_fee_share_cents"] = share
        build_invoice(invoice)
        db.touch(invoice)


def _stop_appointments(stop):
    rows = [a for a in db.appointments.values() if a.get("route_stop_id") == stop["id"]]
    rows.sort(key=order_key)
    return rows
