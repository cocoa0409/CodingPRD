"""The ten declared calculations, kept free of record mutation (PRD 2.5, 3.x)."""
from decimal import Decimal

from store import all_of, db, logical_now, sorted_records
from util import dec, days_between, minus_days, plus_days, rhu, rhu4

# --- constants --------------------------------------------------------------

TIER_MULTIPLIER = {
    "BRONZE": dec("1.00"),
    "SILVER": dec("1.10"),
    "GOLD": dec("1.25"),
    "PLATINUM": dec("1.45"),
}

CHANNEL_COMMISSION_PCT = {
    "INDIVIDUAL": dec("0.0000"),
    "CORPORATE": dec("0.0300"),
    "TRAVEL_PARTNER": dec("0.1000"),
}

SHORTFALL_LIABILITY_PCT = dec("0.60")
SALVAGE_RECOVERY_PCT = dec("0.35")
NON_TICKET_IRRECOVERABLE_PCT = dec("0.20")

DEPOSIT_PCT = dec("0.30")
SECOND_PCT = dec("0.40")
SCHEDULE_MIN_DAYS = 30
IMMEDIATE_DAYS = 3
SETTLEMENT_DUE_DAYS = 7

REBOOK_WINDOW_DAYS = 21
BUILD_BUFFER_MINUTES = 90

GAP_WEIGHT = 40
LAPSE_WEIGHT = 30
HORIZON_WEIGHT = 20
POSTPONED_WEIGHT = 10
HORIZON_NEAR_DAYS = 14
HORIZON_MID_DAYS = 30
CRITICAL_THRESHOLD = 70
ELEVATED_THRESHOLD = 40

LIVE_EVENT_STATUSES = ("SCHEDULED", "POSTPONED", "RESCHEDULED")
LIVE_BLOCK_STATES = ("OPEN", "EXHAUSTED")
RELEASED_TRANCHE_STATES = ("CONFIRMED", "SHORT_CONFIRMED")
LIVE_FULFILLMENT = ("RESERVED", "ALLOCATED", "CREDENTIALED", "REBOOK_PENDING")
EXPOSED_FULFILLMENT = ("RESERVED", "ALLOCATED", "CREDENTIALED", "DELIVERED", "REBOOK_PENDING")
OPEN_INSTALLMENT_STATES = ("SCHEDULED", "OVERDUE")


# --- relationship walks -----------------------------------------------------


def deals_of_event(event_id):
    return sorted_records([d for d in db.rights_deals.values() if d["event_id"] == event_id])


def live_deals_of_event(event_id):
    return [d for d in deals_of_event(event_id) if d["deal_status"] != "TERMINATED"]


def tranches_of_deal(deal_id):
    return sorted_records([t for t in db.release_tranches.values() if t["rights_deal_id"] == deal_id])


def blocks_of_deal(deal_id):
    return sorted_records([b for b in db.allocation_blocks.values() if b["rights_deal_id"] == deal_id])


def packages_of_event(event_id):
    return sorted_records([p for p in db.package_products.values() if p["event_id"] == event_id])


def components_of_package(package_id):
    return sorted_records(
        [c for c in db.package_components.values() if c["package_product_id"] == package_id]
    )


def bookings_of_package(package_id):
    return sorted_records([b for b in db.bookings.values() if b["package_product_id"] == package_id])


def bookings_of_block(block_id):
    return sorted_records([b for b in db.bookings.values() if b["allocation_block_id"] == block_id])


def bookings_of_client(client_id):
    return sorted_records([b for b in db.bookings.values() if b["client_id"] == client_id])


def bookings_of_event(event_id):
    out = []
    for booking in all_of(db.bookings):
        package = db.package_products.get(booking["package_product_id"])
        if package is not None and package["event_id"] == event_id:
            out.append(booking)
    return out


def installments_of_booking(booking_id):
    rows = [i for i in db.payment_installments.values() if i["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: (r["sequence_no"], r["created_at"], r["_seq"]))


def builds_of_event(event_id):
    return sorted_records([b for b in db.hospitality_builds.values() if b["event_id"] == event_id])


def assignments_of_booking(booking_id):
    return sorted_records([a for a in db.host_assignments.values() if a["booking_id"] == booking_id])


def assignments_of_host(host_id):
    return sorted_records([a for a in db.host_assignments.values() if a["on_site_host_id"] == host_id])


def event_of_package(package):
    return db.events.get(package["event_id"]) if package else None


def event_of_booking(booking):
    package = db.package_products.get(booking["package_product_id"])
    return event_of_package(package)


def package_of_booking(booking):
    return db.package_products.get(booking["package_product_id"])


def consumed_units(booking):
    """Rights-holder ticket units a booking draws from a block."""
    package = package_of_booking(booking)
    if package is None:
        return 0
    return booking["units"] * package["tickets_per_package"]


# --- 1. package component line pricing --------------------------------------


def component_line_values(component):
    line_cost = component["unit_cost_cents"] * component["quantity"]
    line_price = rhu(dec(line_cost) * (Decimal(1) + dec(component["markup_pct"])))
    return {"line_cost_cents": line_cost, "line_price_cents": line_price}


# --- 2. package list pricing ------------------------------------------------


def package_price_values(package, components):
    base_cost = 0
    subtotal = 0
    for component in components:
        values = component_line_values(component)
        base_cost += values["line_cost_cents"]
        subtotal += values["line_price_cents"]
    multiplier = TIER_MULTIPLIER[package["tier"]]
    list_price = rhu(dec(subtotal) * multiplier)
    if list_price == 0:
        margin = dec(0)
    else:
        margin = rhu4(dec(list_price - base_cost) / dec(list_price))
    return {
        "base_cost_cents": base_cost,
        "component_price_subtotal_cents": subtotal,
        "list_price_cents": list_price,
        "margin_pct": margin,
    }


# --- 3. booking net price ---------------------------------------------------


def volume_discount_pct_for(units):
    if units >= 20:
        return dec("0.1200")
    if units >= 10:
        return dec("0.0800")
    if units >= 5:
        return dec("0.0400")
    return dec("0.0000")


def event_has_ticket_exposure(event_id):
    for deal in deals_of_event(event_id):
        if deal["inventory_type"] != "TICKET":
            continue
        if deal["deal_status"] not in ("COMMITTED", "PARTIALLY_RELEASED", "SHORTFALL_DECLARED"):
            continue
        if deal["released_units"] < deal["contracted_units"]:
            return True
    return False


def booking_price_values(package, units, channel):
    gross = package["list_price_cents"] * units
    discount_pct = volume_discount_pct_for(units)
    discount_cents = rhu(dec(gross) * discount_pct)
    discounted_subtotal = gross - discount_cents
    commission = rhu(dec(discounted_subtotal) * CHANNEL_COMMISSION_PCT[channel])
    if event_has_ticket_exposure(package["event_id"]):
        if discounted_subtotal >= 5000000:
            surcharge_pct = dec("0.0200")
        elif discounted_subtotal >= 1000000:
            surcharge_pct = dec("0.0350")
        else:
            surcharge_pct = dec("0.0500")
        surcharge = rhu(dec(discounted_subtotal) * surcharge_pct)
    else:
        surcharge = 0
    net = discounted_subtotal - commission + surcharge
    return {
        "gross_price_cents": gross,
        "volume_discount_pct": discount_pct,
        "discounted_subtotal_cents": discounted_subtotal,
        "partner_commission_cents": commission,
        "guarantee_surcharge_cents": surcharge,
        "net_price_cents": net,
    }


# --- 4. rights deal minimum liability and the deal status function -----------


def deal_released_units(deal):
    total = 0
    for tranche in tranches_of_deal(deal["id"]):
        if tranche["tranche_state"] in RELEASED_TRANCHE_STATES:
            total += tranche["confirmed_units"]
    return total


def deal_pending_units(deal):
    total = 0
    for tranche in tranches_of_deal(deal["id"]):
        if tranche["tranche_state"] == "PENDING":
            total += tranche["promised_units"]
    return total


def deal_promised_units_in_states(deal, states):
    total = 0
    for tranche in tranches_of_deal(deal["id"]):
        if tranche["tranche_state"] in states:
            total += tranche["promised_units"]
    return total


def deal_liability_values(deal):
    released = deal_released_units(deal)
    if released >= deal["guaranteed_minimum_units"]:
        shortfall = 0
    else:
        shortfall = deal["guaranteed_minimum_units"] - released
    shortfall_unit_cost = rhu(dec(deal["unit_cost_cents"]) * SHORTFALL_LIABILITY_PCT)
    liability = released * deal["unit_cost_cents"] + shortfall * shortfall_unit_cost
    return {
        "released_units": released,
        "shortfall_units": shortfall,
        "minimum_liability_cents": liability,
    }


def deal_status_for(deal):
    released = deal_released_units(deal)
    pending = deal_pending_units(deal)
    if released >= deal["contracted_units"]:
        return "FULLY_RELEASED"
    if released + pending < deal["guaranteed_minimum_units"]:
        return "SHORTFALL_DECLARED"
    if released > 0:
        return "PARTIALLY_RELEASED"
    return "COMMITTED"


def deal_unallocated_units(deal):
    released = deal["released_units"]
    held = 0
    for block in blocks_of_deal(deal["id"]):
        if block["block_state"] in LIVE_BLOCK_STATES or block["block_state"] == "RECALLED":
            held += block["allocated_units"]
    return released - held


def deal_distributable_units(deal):
    recalled = 0
    for block in blocks_of_deal(deal["id"]):
        if block["block_state"] == "RECALLED":
            recalled += block["allocated_units"]
    return deal["released_units"] - recalled


def waterfall_candidates(deal):
    blocks = [b for b in blocks_of_deal(deal["id"]) if b["block_state"] in LIVE_BLOCK_STATES]
    return sorted(blocks, key=lambda b: (b["priority_rank"], b["created_at"], b["_seq"]))


# --- 6. event fulfillment risk ---------------------------------------------


def days_to_event(event):
    return days_between(logical_now(), event["event_date"])


def event_risk_values(event):
    promised = 0
    released = 0
    lapsed = 0
    for deal in live_deals_of_event(event["id"]):
        promised += deal["contracted_units"]
        released += deal["released_units"]
        for tranche in tranches_of_deal(deal["id"]):
            if tranche["tranche_state"] == "LAPSED":
                lapsed += tranche["promised_units"]
    committed = 0
    for booking in bookings_of_event(event["id"]):
        if booking["fulfillment_status"] in LIVE_FULFILLMENT:
            committed += consumed_units(booking)

    gap_numerator = max(0, committed - released)
    gap_fraction = dec(gap_numerator) / dec(max(1, committed))
    if gap_fraction > 1:
        gap_fraction = dec(1)
    gap_component = dec(GAP_WEIGHT) * gap_fraction

    lapse_fraction = dec(lapsed) / dec(max(1, promised))
    if lapse_fraction > 1:
        lapse_fraction = dec(1)
    lapse_component = dec(LAPSE_WEIGHT) * lapse_fraction

    distance = days_to_event(event)
    if distance <= HORIZON_NEAR_DAYS:
        horizon_component = dec(HORIZON_WEIGHT)
    elif distance <= HORIZON_MID_DAYS:
        horizon_component = dec(10)
    else:
        horizon_component = dec(0)

    status_component = dec(POSTPONED_WEIGHT) if event["status"] == "POSTPONED" else dec(0)

    score = rhu(gap_component + lapse_component + horizon_component + status_component)
    if score > 100:
        score = 100
    if score >= CRITICAL_THRESHOLD:
        posture = "CRITICAL"
    elif score >= ELEVATED_THRESHOLD:
        posture = "ELEVATED"
    else:
        posture = "NORMAL"
    return {"fulfillment_risk_score": score, "risk_posture": posture}


# --- 7. event margin report -------------------------------------------------


def margin_report(event, variant):
    rights_cost = 0
    build_cost = 0
    unsold_units = 0
    exposure_full = 0
    for deal in live_deals_of_event(event["id"]):
        rights_cost += deal["minimum_liability_cents"]
        sold = 0
        for block in blocks_of_deal(deal["id"]):
            if block["block_state"] in ("OPEN", "EXHAUSTED", "RECALLED"):
                sold += block["committed_units"]
        deal_unsold = max(0, deal["released_units"] - sold)
        unsold_units += deal_unsold
        exposure_full += deal_unsold * deal["unit_cost_cents"]
    for build in builds_of_event(event["id"]):
        if build["build_state"] in ("APPROVED", "READY", "CLOSED"):
            build_cost += build["total_cost_cents"]
    cost_cents = rights_cost + build_cost

    bookings = bookings_of_event(event["id"])
    if variant == "FINAL":
        revenue = 0
        for booking in bookings:
            if booking["fulfillment_status"] == "DELIVERED":
                revenue += booking["net_price_cents"]
            elif booking["fulfillment_status"] == "CANCELLED":
                revenue += booking["cancellation_fee_cents"]
        unsold_exposure = rhu(dec(exposure_full) * (Decimal(1) - SALVAGE_RECOVERY_PCT))
    else:
        revenue = 0
        for booking in bookings:
            if booking["fulfillment_status"] in EXPOSED_FULFILLMENT:
                revenue += booking["net_price_cents"]
        unsold_exposure = exposure_full

    margin_cents = revenue - cost_cents
    net_margin_cents = margin_cents - unsold_exposure
    if revenue == 0:
        margin_pct = dec(0)
    else:
        margin_pct = rhu4(dec(net_margin_cents) / dec(revenue))
    return {
        "variant": variant,
        "revenue_cents": revenue,
        "rights_cost_cents": rights_cost,
        "build_cost_cents": build_cost,
        "cost_cents": cost_cents,
        "unsold_units": unsold_units,
        "unsold_exposure_cents": unsold_exposure,
        "margin_cents": margin_cents,
        "net_margin_cents": net_margin_cents,
        "margin_pct": float(margin_pct),
    }


# --- 8. booking cancellation settlement ------------------------------------


def cancellation_settlement(booking, package, event, pre_paid_cents):
    if event["status"] == "POSTPONED":
        variant = "COST_RECOVERY"
        block_id = booking["allocation_block_id"]
        ticket_cost = 0
        if block_id is not None:
            block = db.allocation_blocks.get(block_id)
            deal = db.rights_deals.get(block["rights_deal_id"]) if block else None
            if deal is not None:
                ticket_cost = booking["units"] * package["tickets_per_package"] * deal["unit_cost_cents"]
        non_ticket_cost = rhu(
            dec(package["base_cost_cents"]) * dec(booking["units"]) * NON_TICKET_IRRECOVERABLE_PCT
        )
        fee = min(booking["net_price_cents"], ticket_cost + non_ticket_cost)
    else:
        variant = "TIER_SCHEDULE"
        distance = days_to_event(event)
        if distance >= 90:
            fee_pct = dec("0.10")
        elif distance >= 60:
            fee_pct = dec("0.25")
        elif distance >= 30:
            fee_pct = dec("0.50")
        elif distance >= 7:
            fee_pct = dec("0.80")
        else:
            fee_pct = dec("1.00")
        fee = rhu(dec(booking["net_price_cents"]) * fee_pct)
    refund = max(0, pre_paid_cents - fee)
    balance_due = max(0, fee - pre_paid_cents)
    return {
        "settlement_variant": variant,
        "cancellation_fee_cents": fee,
        "refund_cents": refund,
        "balance_due_cents": balance_due,
    }


# --- 9. payment schedule generation ----------------------------------------


def schedule_lines(booking, event):
    payable = max(0, booking["net_price_cents"] - booking["paid_cents"])
    now = logical_now()
    distance = days_between(now, event["event_date"])
    first_due = plus_days(now, IMMEDIATE_DAYS)
    if distance >= SCHEDULE_MIN_DAYS:
        first = rhu(dec(payable) * DEPOSIT_PCT)
        second = rhu(dec(payable) * SECOND_PCT)
        third = payable - first - second
        second_due = minus_days(event["event_date"], 90)
        if second_due < first_due:
            second_due = first_due
        third_due = minus_days(event["event_date"], 30)
        if third_due < second_due:
            third_due = second_due
        return [(first, first_due), (second, second_due), (third, third_due)]
    return [(payable, first_due)]


# --- 10. client credit exposure --------------------------------------------


def client_exposure_values(client):
    outstanding = 0
    overdue = 0
    for booking in bookings_of_client(client["id"]):
        if booking["fulfillment_status"] in EXPOSED_FULFILLMENT:
            outstanding += max(0, booking["net_price_cents"] - booking["paid_cents"])
        elif (
            booking["fulfillment_status"] == "CANCELLED"
            and booking["payment_status"] == "SETTLEMENT_DUE"
        ):
            outstanding += booking["balance_due_cents"]
        for installment in installments_of_booking(booking["id"]):
            if installment["installment_state"] == "OVERDUE":
                overdue += 1
    return {"outstanding_cents": outstanding, "overdue_installment_count": overdue}


def credit_standing_for(overdue_count):
    if overdue_count >= 3:
        return "BLOCKED"
    if overdue_count >= 1:
        return "ON_HOLD"
    return "ACTIVE"
