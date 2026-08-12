"""Calculation rules (SCAFFOLD section 1.3 / PRD section 3).

Every monetary result is Decimal, two decimal places, round-half-up.
"""
from decimal import Decimal

import consts as C
import lookup
import store
from store import D, add_days, money, rate4, ceil_int

ZERO = Decimal("0.00")


# --------------------------------------------------------------------------
# authority
# --------------------------------------------------------------------------
def effective_authorization_cap(client):
    if client["client_type"] == "LISTING_AGENT":
        brokerage = store.get("brokerages", client.get("brokerage_id"))
        cap = D(client.get("personal_authorization_cap"))
        if brokerage is not None:
            cap = min(cap, D(brokerage.get("authorization_cap")))
    else:
        cap = C.BROKERAGE_AUTHORIZATION_HARD_CAP
    return money(cap)


def redderive_caps_for_brokerage(brokerage):
    for client in store.where("clients", brokerage_id=brokerage["id"]):
        new_cap = effective_authorization_cap(client)
        if new_cap != client.get("effective_authorization_cap"):
            client["effective_authorization_cap"] = new_cap
            store.touch(client)


# --------------------------------------------------------------------------
# package / travel / contract value
# --------------------------------------------------------------------------
def travel_fee(prop):
    miles = D(prop.get("distance_miles"))
    if miles <= C.TRAVEL_ZONE_1_MAX_MILES:
        fee = C.TRAVEL_ZONE_1_FEE
    elif miles <= C.TRAVEL_ZONE_2_MAX_MILES:
        fee = C.TRAVEL_ZONE_2_FEE
    else:
        fee = C.TRAVEL_ZONE_3_FEE
    return money(fee)


def room_overage_charge(project, tier):
    rooms = max(0, int(project.get("room_count") or 0) - int(tier.get("room_cap") or 0))
    return money(D(rooms) * C.ROOM_OVERAGE_RATE)


def accessory_overage_charge(project, tier):
    sets = max(0, int(project.get("accessory_set_count") or 0)
               - int(tier.get("included_accessory_sets") or 0))
    return money(D(sets) * C.ACCESSORY_SET_OVERAGE_RATE)


def contract_value(project, tier=None):
    tier = tier or lookup.tier_of(project)
    prop = lookup.property_of(project)
    consultation = lookup.consultation_of(project)
    base = D(tier.get("base_price"))
    rooms = room_overage_charge(project, tier)
    access = accessory_overage_charge(project, tier)
    travel = travel_fee(prop)
    if project["pipeline"] == "VACANT_STAGING":
        forward = money(D(tier.get("monthly_rent_rate")) * C.MIN_LEASE_CYCLES)
        labour = ZERO
    else:
        forward = ZERO
        hours = D(consultation.get("estimated_hours") if consultation else 0)
        labour = money(C.OCCUPIED_HOURLY_RATE * hours) + C.OCCUPIED_FIRST_VISIT_SURCHARGE
    return money(base + rooms + access + travel + forward + labour)


def service_window_end_date(project):
    if project["pipeline"] != "OCCUPIED_PREP":
        return None
    anchor = project.get("authorized_at")
    if anchor is None:
        return None
    days = C.OCCUPIED_SERVICE_WINDOW_DAYS + \
        int(project.get("window_extension_count") or 0) * C.OCCUPIED_WINDOW_EXTENSION_DAYS
    return add_days(anchor, days)


def upgrade_adjustment(project, old_tier, new_tier):
    price_delta = D(new_tier["base_price"]) - D(old_tier["base_price"])
    lease = lookup.active_lease(project)
    if lease is not None and lease.get("end_date") is not None:
        remaining = max(0, store.floor_days(lease["end_date"] - store.now()))
        ratio = min(Decimal("1.0"), D(remaining) / D(C.UPGRADE_PRORATION_BASIS_DAYS))
    else:
        ratio = Decimal("1.0")
    prorated = price_delta * ratio
    overage_delta = (room_overage_charge(project, new_tier) - room_overage_charge(project, old_tier)
                     + accessory_overage_charge(project, new_tier)
                     - accessory_overage_charge(project, old_tier))
    return money(prorated + overage_delta)


def downgrade_adjustment(project, old_tier, new_tier):
    credit = (D(old_tier["base_price"]) - D(new_tier["base_price"])) * C.DOWNGRADE_CREDIT_PCT
    overage_delta = (room_overage_charge(project, new_tier) - room_overage_charge(project, old_tier)
                     + accessory_overage_charge(project, new_tier)
                     - accessory_overage_charge(project, old_tier))
    return money(C.DOWNGRADE_RESTOCK_FEE - credit + overage_delta)


# --------------------------------------------------------------------------
# visits / labour
# --------------------------------------------------------------------------
def visit_billable_hours(visit):
    if visit.get("state") != "COMPLETED":
        return money(0)
    return money(max(D(visit.get("hours_logged") or 0), C.OCCUPIED_MIN_BILLABLE_HOURS))


def occupied_labour_charge(project):
    visits = [v for v in lookup.project_visits(project) if v["state"] == "COMPLETED"]
    hours_total = Decimal("0")
    for visit in visits:
        hours_total += D(visit.get("billable_hours") or 0)
    surcharge = C.OCCUPIED_FIRST_VISIT_SURCHARGE if any(
        v.get("visit_index") == 1 for v in visits) else ZERO
    return money(hours_total * C.OCCUPIED_HOURLY_RATE) + surcharge


# --------------------------------------------------------------------------
# pull / inventory
# --------------------------------------------------------------------------
def line_monthly_rate(line, item=None, vendor=None):
    if line["source"] == "OWNED":
        rate = D(item.get("monthly_rate")) if item is not None else ZERO
    else:
        multiplier = D(vendor.get("rate_multiplier")) if vendor is not None else Decimal("1")
        rate = C.VENDOR_UNIT_BASE_RATE * multiplier * D(line.get("quantity") or 0)
    return money(rate)


def pull_counts(pull):
    lines = lookup.pull_lines(pull)
    requested = sum(int(l["quantity"]) for l in lines if l["state"] != "DROPPED")
    filled = sum(int(l["quantity"]) for l in lines
                 if l["state"] in ("ALLOCATED", "DEPLOYED", "RETURNED"))
    return requested, filled


def pull_fill_rate(requested, filled):
    if requested == 0:
        return rate4(0)
    return rate4(D(filled) / D(requested))


def recompute_pull(pull):
    requested, filled = pull_counts(pull)
    pull["requested_unit_count"] = requested
    pull["filled_unit_count"] = filled
    pull["fill_rate"] = pull_fill_rate(requested, filled)


# --------------------------------------------------------------------------
# lease
# --------------------------------------------------------------------------
def lease_monthly_rent(lease):
    project = store.get("projects", lease["project_id"])
    total = Decimal("0.00")
    for line in lookup.project_lines(project):
        if line["state"] in ("ALLOCATED", "DEPLOYED"):
            total += money(line.get("monthly_rate") or 0)
    return money(total)


def lease_end_date(lease):
    if lease.get("start_date") is None:
        return None
    return add_days(lease["start_date"], int(lease.get("billed_cycles") or 0) * C.LEASE_CYCLE_DAYS)


def derive_pickup_window(lease):
    end = lease.get("end_date")
    if end is None:
        lease["pickup_window_start"] = None
        lease["pickup_window_end"] = None
        return
    if lease.get("state") == "ENDING" and store.now() < end:
        anchor = store.now()
    else:
        anchor = end
    start = add_days(anchor, C.PICKUP_BUFFER_DAYS)
    lease["pickup_window_start"] = start
    lease["pickup_window_end"] = add_days(start, C.PICKUP_WINDOW_DAYS)


def initial_lease_charge(lease):
    if lease is None:
        return ZERO
    return money(D(lease.get("monthly_rent") or 0) * int(lease.get("initial_cycles") or 0))


def vendor_minimum_shortfall_charge(project, lease):
    if lease is None:
        return ZERO
    total = Decimal("0.00")
    for order in lookup.project_orders(project):
        if order["state"] not in ("DELIVERED", "RETURNED"):
            continue
        shortfall = max(0, int(order.get("effective_term_cycles") or 0)
                        - int(lease.get("billed_cycles") or 0))
        total += money(D(order.get("monthly_rate_total") or 0) * shortfall)
    return money(total)


# --------------------------------------------------------------------------
# vendor orders
# --------------------------------------------------------------------------
def vendor_effective_term_cycles(order, vendor):
    project = store.get("projects", order["project_id"])
    lease = lookup.active_lease(project) if project else None
    project_cycles = int(lease["initial_cycles"]) if lease is not None else C.MIN_LEASE_CYCLES
    return max(project_cycles, int(vendor.get("min_lease_cycles") or 0))


def vendor_order_monthly_rate(order, vendor):
    return money(D(order["unit_count"]) * C.VENDOR_UNIT_BASE_RATE * D(vendor.get("rate_multiplier")))


def vendor_cancellation_fee(order, late):
    pct = C.VENDOR_LATE_CANCEL_PCT if late else C.VENDOR_EARLY_CANCEL_PCT
    return money(D(order.get("monthly_rate_total") or 0) * pct)


# --------------------------------------------------------------------------
# extensions
# --------------------------------------------------------------------------
def line_survives(line, lease, requested_cycles):
    if line["source"] == "OWNED":
        return True
    order = store.get("orders", line.get("rental_order_id"))
    if order is None:
        return False
    needed = int(lease.get("billed_cycles") or 0) + int(requested_cycles)
    return int(order.get("effective_term_cycles") or 0) >= needed


def extension_charge(lines, granted_cycles):
    rate_base = Decimal("0.00")
    for line in lines:
        rate_base += money(line.get("monthly_rate") or 0)
    return money(rate_base * int(granted_cycles))


def partial_extension_swap_credit(returned_lines):
    total = Decimal("0.00")
    for line in returned_lines:
        total += money(line.get("monthly_rate") or 0)
    return money(total * C.PARTIAL_SWAP_CREDIT_PCT)


# --------------------------------------------------------------------------
# holdover
# --------------------------------------------------------------------------
def holdover_days(lease, project):
    latest = lookup.latest_pickup(project)
    grace = 0 if (latest is not None and latest["state"] == "REFUSED") else C.HOLDOVER_GRACE_DAYS
    window_end = lease.get("pickup_window_end")
    if window_end is None:
        return 0
    elapsed = store.floor_days(store.now() - window_end)
    return max(0, elapsed - grace)


def holdover_charge(days):
    total = Decimal("0.00")
    day_index = 0
    remaining = int(days)
    while remaining > 0:
        period_amount = Decimal("0.00")
        for _ in range(C.HOLDOVER_CAP_PERIOD_DAYS):
            if remaining <= 0:
                break
            day_index += 1
            rate = (C.HOLDOVER_TIER1_DAILY_RATE if day_index <= C.HOLDOVER_TIER1_MAX_DAYS
                    else C.HOLDOVER_TIER2_DAILY_RATE)
            period_amount += rate
            remaining -= 1
        total += min(period_amount, C.HOLDOVER_PERIOD_CAP)
    return money(total)


# --------------------------------------------------------------------------
# damage
# --------------------------------------------------------------------------
def item_age_band(item):
    age_months = store.floor_days(store.now() - item["acquired_at"]) // C.DEPRECIATION_MONTH_DAYS
    if age_months <= C.DEPRECIATION_BAND_1_MAX_MONTHS:
        factor = C.DEPRECIATION_BAND_1_FACTOR
    elif age_months <= C.DEPRECIATION_BAND_2_MAX_MONTHS:
        factor = C.DEPRECIATION_BAND_2_FACTOR
    elif age_months <= C.DEPRECIATION_BAND_3_MAX_MONTHS:
        factor = C.DEPRECIATION_BAND_3_FACTOR
    else:
        factor = C.DEPRECIATION_FLOOR_FACTOR
    return age_months, factor


def depreciated_replacement_value(line):
    if line["source"] == "OWNED":
        item = store.get("items", line.get("inventory_item_id"))
        if item is None:
            return ZERO
        _, factor = item_age_band(item)
        return money(D(item["replacement_value"]) * factor)
    return money(C.VENDOR_UNIT_REPLACEMENT_VALUE * D(line.get("quantity") or 0)
                 * (Decimal("1") + C.VENDOR_DAMAGE_SURCHARGE_PCT))


def damage_charge(assessment, drv):
    condition = assessment["condition_at_pickup"]
    if condition == "INTACT":
        return money(0), "NO_CHARGE"
    if condition == "MISSING":
        return money(drv), "REPLACE"
    estimate = D(assessment.get("repair_cost_estimate") or 0)
    if estimate > C.REPLACEMENT_THRESHOLD_PCT * drv:
        return money(drv * C.SALVAGE_RECOVERY_PCT), "REPLACE"
    return money(min(estimate, drv)), "REPAIR"


# --------------------------------------------------------------------------
# photography
# --------------------------------------------------------------------------
def mls_delivery_gate(project):
    return project.get("payer_type") == "PAY_AT_CLOSING"


def photo_overage_fee(shoot, tier):
    if shoot.get("is_reshoot"):
        return money(0)
    included = int(tier.get("included_photo_sessions") or 0) if tier else 0
    if int(shoot.get("session_index") or 0) > included:
        return money(C.PHOTO_SESSION_OVERAGE_FEE)
    return money(0)


def photo_sessions_consumed(project):
    return len([s for s in lookup.project_shoots(project)
                if not s.get("is_reshoot") and s["state"] in ("COMPLETED", "DELIVERED")])


def reshoot_credits_remaining(project):
    used = len([s for s in lookup.project_shoots(project)
                if s.get("is_reshoot") and s["state"] in ("SCHEDULED", "COMPLETED", "DELIVERED")])
    return C.RESHOOT_ENTITLEMENT_PER_PACKAGE - used


# --------------------------------------------------------------------------
# deposit
# --------------------------------------------------------------------------
def deposit_requirement(project):
    pct = C.DEPOSIT_PCT[project["payer_type"]]
    return money(D(project.get("contract_value") or 0) * pct)


def deposit_waterfall(deposit, project, invoice):
    lease = lookup.active_lease(project)
    pickup = lookup.active_pickup(project)
    avail = D(deposit.get("held_remaining") or 0)
    damage_total = D(pickup.get("damage_total") or 0) if pickup else ZERO
    holdover = D(lease.get("holdover_charge") or 0) if lease else ZERO
    balance_target = D(invoice.get("subtotal") or 0) + D(invoice.get("tax_amount") or 0)

    d = min(avail, damage_total)
    avail -= d
    h = min(avail, holdover)
    avail -= h
    b = min(avail, balance_target)
    avail -= b

    deposit["applied_to_damage"] = money(D(deposit.get("applied_to_damage") or 0) + money(d))
    deposit["applied_to_holdover"] = money(D(deposit.get("applied_to_holdover") or 0) + money(h))
    deposit["applied_to_balance"] = money(D(deposit.get("applied_to_balance") or 0) + money(b))
    deposit["held_remaining"] = money(avail)
    return money(d + h + b)


# --------------------------------------------------------------------------
# invoice
# --------------------------------------------------------------------------
def line_summary(project):
    tier = lookup.tier_of(project)
    prop = lookup.property_of(project)
    lease = lookup.active_lease(project)
    pickup = lookup.active_pickup(project)

    package = money(D(tier["base_price"]) + D(project.get("package_adjustments") or 0))
    rooms = room_overage_charge(project, tier)
    access = accessory_overage_charge(project, tier)
    travel = travel_fee(prop)

    if project["pipeline"] == "OCCUPIED_PREP":
        labour = occupied_labour_charge(project)
        lease_component = ZERO
    else:
        labour = ZERO
        lease_component = money(initial_lease_charge(lease)
                                + vendor_minimum_shortfall_charge(project, lease))

    extension = Decimal("0.00")
    if lease is not None:
        for ext in lookup.lease_extensions(lease):
            if ext["state"] == "APPLIED":
                extension += money(ext.get("extension_charge") or 0)

    holdover = money(lease.get("holdover_charge") or 0) if lease else ZERO
    damage = money(pickup.get("damage_total") or 0) if pickup else ZERO

    photo = Decimal("0.00")
    for shoot in lookup.project_shoots(project):
        photo += money(shoot.get("overage_fee") or 0)

    cancellation = Decimal("0.00")
    for order in lookup.project_orders(project):
        cancellation += money(order.get("cancellation_fee") or 0)

    escalation = money(project.get("closing_escalation_booked") or 0)

    return {
        "package": package,
        "room_overage": rooms,
        "accessory_overage": access,
        "labour": money(labour),
        "travel": travel,
        "lease": money(lease_component),
        "extension": money(extension),
        "holdover": holdover,
        "damage": damage,
        "photo": money(photo),
        "cancellation": money(cancellation),
        "closing_escalation": escalation,
    }


def invoice_subtotal(summary):
    subtotal = Decimal("0.00")
    for component in C.COMPONENT_ORDER:
        subtotal += money(summary.get(component, 0))
    return money(subtotal)


def tax_amount(project, summary, subtotal):
    if project["payer_type"] == "BROKERAGE":
        brokerage = store.get("brokerages", project.get("brokerage_id"))
        if brokerage is not None and brokerage.get("tax_exempt"):
            return money(0)
    if project["payer_type"] == "SELLER":
        rental_base = (money(summary["lease"]) + money(summary["extension"])
                       + money(summary["holdover"]))
        return money(rental_base * C.TAX_RATE_RENTAL_ONLY)
    return money(D(subtotal) * C.TAX_RATE_STANDARD)


def late_payment_interest(invoice, base):
    due = invoice.get("due_date")
    if due is None or store.now() <= due:
        return money(0)
    seconds = (store.now() - due).total_seconds()
    months = ceil_int(D(seconds) / D(30 * 86400))
    rate = (C.LATE_PAYMENT_MONTHLY_INTEREST_RATE if base > C.LATE_INTEREST_TIER_THRESHOLD
            else C.LATE_PAYMENT_REDUCED_RATE)
    return money(D(base) * rate * months)


def refresh_invoice(invoice):
    """The six pinned evaluation steps.  Never bumps the invoice version."""
    project = store.get("projects", invoice["project_id"])
    summary = line_summary(project)
    subtotal = invoice_subtotal(summary)                      # step 1
    tax = tax_amount(project, summary, subtotal)              # step 2
    base = money(subtotal + tax)                              # step 3
    interest = late_payment_interest(invoice, base)           # step 4
    deposit = lookup.project_deposit(project)                 # step 5
    if deposit is None:
        applied = ZERO
    else:
        applied = money(D(deposit.get("applied_to_balance") or 0)
                        + D(deposit.get("applied_to_damage") or 0)
                        + D(deposit.get("applied_to_holdover") or 0))
    total = money(max(ZERO, base + interest - applied))       # step 6

    invoice["line_summary"] = summary
    invoice["subtotal"] = subtotal
    invoice["tax_amount"] = tax
    invoice["interest_accrued"] = interest
    invoice["deposit_applied"] = applied
    invoice["total_due"] = total
    return invoice


def split_payer_allocation(invoice, project):
    agent = money(D(invoice.get("total_due") or 0) * D(project.get("payer_split_agent_pct") or 0))
    seller = money(D(invoice.get("total_due") or 0) - agent)
    return {"agent": agent, "seller": seller}
