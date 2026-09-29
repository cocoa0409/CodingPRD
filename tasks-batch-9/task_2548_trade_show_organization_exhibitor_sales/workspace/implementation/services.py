"""State transitions, compensating links and cascades (PRD 2.10, section 3)."""
import calc
from db import (add_days, by_created, db, fmt_date, fmt_dt, now, parse_date, touch)


# ------------------------------------------------------------------ exhibitor
def add_penalty_points(exhibitor, points):
    """Penalty accrual is purely additive and may suspend the account."""
    exhibitor["penalty_points"] += points
    if (exhibitor["penalty_points"] >= calc.SUSPENSION_PENALTY_THRESHOLD
            and exhibitor["status"] == "ACTIVE"):
        exhibitor["status"] = "SUSPENDED"
    touch(exhibitor)


# --------------------------------------------------------------------- booths
def hold_booths(contract, booths):
    for booth in booths:
        booth["status"] = "HELD"
        booth["space_contract_id"] = contract["id"]
        touch(booth)


def release_booth(booth):
    booth["status"] = "AVAILABLE"
    booth["space_contract_id"] = None
    touch(booth)


def contract_held_or_assigned_booths(contract):
    booths = []
    seen = set()
    for booth_id in contract["offered_booth_ids"]:
        booth = db.booths.get(booth_id)
        if booth is not None and booth["id"] not in seen:
            seen.add(booth["id"])
            booths.append(booth)
    for booth in db.booths.values():
        if booth["space_contract_id"] == contract["id"] and booth["id"] not in seen:
            seen.add(booth["id"])
            booths.append(booth)
    return booths


# ------------------------------------------------------------------- invoices
def reprice_exhibitor_contracts(exhibitor_id, show_id):
    """A sponsorship signing or cancellation reprices the exhibitor's
    non-terminal space contracts on the same show (PRD 3.5 / 3.7)."""
    for contract in by_created([c for c in db.space_contracts.values()
                                if c["exhibitor_id"] == exhibitor_id
                                and c["show_id"] == show_id
                                and c["status"] in calc.NON_TERMINAL_CONTRACT_STATUSES]):
        before = (contract["sponsorship_attached_cents"], contract["bundle_discount_pct"],
                  contract["bundle_discount_cents"], contract["invoice_total_cents"])
        calc.price_invoice(contract)
        after = (contract["sponsorship_attached_cents"], contract["bundle_discount_pct"],
                 contract["bundle_discount_cents"], contract["invoice_total_cents"])
        if before != after:
            touch(contract)


# ------------------------------------------------------------ space contracts
def apply_cancellation_waterfall(contract, fee):
    deposit = contract["deposit_paid_cents"]
    fee_applied = min(fee, deposit)
    contract["cancellation_fee_cents"] = fee
    contract["fee_applied_to_deposit_cents"] = fee_applied
    contract["refund_cents"] = deposit - fee_applied
    contract["balance_due_cents"] = fee - fee_applied


def cancel_space_contract(contract, reason, cascade=False):
    """Shared body of the OFFERED/COUNTERED/SIGNED -> CANCELLED transitions."""
    show = db.shows[contract["show_id"]]
    venue_contract = db.venue_contracts[show["venue_contract_id"]]
    was_signed = contract["status"] == "SIGNED"
    fee = calc.cancellation_fee_cents(contract, show, venue_contract, cascade=cascade)
    apply_cancellation_waterfall(contract, fee)
    contract["status"] = "CANCELLED"
    contract["cancellation_reason"] = reason
    contract["points_awarded"] = 0
    for booth in contract_held_or_assigned_booths(contract):
        if booth["status"] in ("HELD", "ASSIGNED"):
            release_booth(booth)
    if was_signed:
        for order in by_created(calc.contract_service_orders(contract["id"])):
            if order["status"] == "SUBMITTED":
                order["status"] = "CANCELLED"
                touch(order)
    touch(contract)
    exhibitor = db.exhibitors.get(contract["exhibitor_id"])
    if was_signed and exhibitor is not None:
        touch(exhibitor)


# ------------------------------------------------------------------ sponsorship
def credit_fulfillment_if_complete(deal):
    """Both edges into COMPLETE carry the credit exactly once."""
    if calc.derived_fulfillment_status(deal) != "COMPLETE":
        return
    if deal["fulfillment_credited"]:
        return
    package = db.sponsorship_packages.get(deal["sponsorship_package_id"])
    exhibitor = db.exhibitors.get(deal["exhibitor_id"])
    deal["fulfillment_credited"] = True
    if package is not None and exhibitor is not None:
        exhibitor["sponsorship_fulfillment_points"] += package["priority_point_value"]
        touch(exhibitor)


def cancel_sponsorship_deal(deal, reason):
    was_signed = deal["deal_status"] == "SIGNED"
    package = db.sponsorship_packages.get(deal["sponsorship_package_id"])
    exhibitor = db.exhibitors.get(deal["exhibitor_id"])
    deal["deal_status"] = "CANCELLED"
    deal["cancellation_reason"] = reason
    if was_signed and exhibitor is not None:
        if deal["fulfillment_credited"] and package is not None:
            exhibitor["sponsorship_fulfillment_points"] -= package["priority_point_value"]
            if exhibitor["sponsorship_fulfillment_points"] < 0:
                exhibitor["sponsorship_fulfillment_points"] = 0
        touch(exhibitor)
    touch(deal)
    if was_signed and package is not None:
        reprice_exhibitor_contracts(deal["exhibitor_id"], package["show_id"])


def materialise_obligations(deal, package, show):
    event_start = parse_date(show["event_start"])
    due = add_days(event_start, -calc.OBLIGATION_LEAD_DAYS)
    from db import base_row
    for code in package["obligation_codes"]:
        row = base_row()
        row.update({
            "sponsorship_deal_id": deal["id"],
            "obligation_code": code,
            "due_date": fmt_date(due),
            "status": "PENDING",
            "resolved_by_user_id": None,
            "note": None,
        })
        db.fulfillment_obligations[row["id"]] = row


def apply_breach_if_needed(deal):
    """A deal entering BREACHED costs the sponsor twenty penalty points once."""
    if calc.derived_fulfillment_status(deal) != "BREACHED":
        return
    if deal.get("_breach_charged"):
        return
    deal["_breach_charged"] = True
    exhibitor = db.exhibitors.get(deal["exhibitor_id"])
    if exhibitor is not None:
        add_penalty_points(exhibitor, calc.BREACH_PENALTY_POINTS)
    touch(deal)


# ------------------------------------------------------------------- cascades
def close_show(show):
    """ON_SITE -> CLOSED with its long tail (PRD 3.9)."""
    show["status"] = "CLOSED"
    contracts = by_created(calc.show_contracts(show["id"]))
    for contract in contracts:
        if contract["status"] == "SIGNED":
            contract["status"] = "CLOSED_OUT"
            touch(contract)
            exhibitor = db.exhibitors.get(contract["exhibitor_id"])
            if exhibitor is not None:
                touch(exhibitor)
    for contract in contracts:
        if contract["status"] in ("OFFERED", "COUNTERED"):
            cancel_space_contract(contract, "SHOW_CLOSED_UNSIGNED", cascade=True)
    touched_deals = []
    obligations = []
    for deal in calc.show_deals(show["id"]):
        if deal["deal_status"] != "SIGNED":
            continue
        for obligation in calc.deal_obligations(deal["id"]):
            if obligation["status"] == "PENDING":
                obligations.append((obligation, deal))
    for obligation, deal in sorted(obligations, key=lambda pair: (
            pair[0]["created_at"], pair[0]["_seq"])):
        obligation["status"] = "MISSED"
        touch(obligation)
        if deal["id"] not in [d["id"] for d in touched_deals]:
            touched_deals.append(deal)
    for deal in touched_deals:
        apply_breach_if_needed(deal)
    venue_contract = db.venue_contracts[show["venue_contract_id"]]
    shortfall, settlement = calc.attrition_figures(show, venue_contract)
    show["attrition_shortfall_sqft"] = shortfall
    show["attrition_settlement_cents"] = settlement
    touch(show)


def cancel_show(show, reason):
    """PLANNING/SPACE_SELECTION/SELLING/ON_SITE -> CANCELLED (PRD 3.9)."""
    show["status"] = "CANCELLED"
    show["cancellation_reason"] = reason
    for appointment in by_created(calc.show_appointments(show["id"])):
        if appointment["state"] in ("SCHEDULED", "ACTIVE"):
            appointment["state"] = "EXPIRED"
            touch(appointment)
    for contract in by_created(calc.show_contracts(show["id"])):
        if contract["status"] in calc.ACTIVE_CONTRACT_STATUSES:
            cancel_space_contract(contract, "SHOW_CANCELLED", cascade=True)
    for deal in by_created(calc.show_deals(show["id"])):
        if deal["deal_status"] in ("PROPOSED", "SIGNED"):
            cancel_sponsorship_deal(deal, "SHOW_CANCELLED")
    touch(show)


def terminate_venue_contract(venue_contract, effective_date, reason=None):
    venue_contract["status"] = "TERMINATED"
    venue_contract["terminated_effective_date"] = fmt_date(effective_date)
    if reason is not None:
        venue_contract["termination_reason"] = reason
    touch(venue_contract)
    for show in by_created(calc.venue_shows(venue_contract["id"])):
        if show["status"] in ("PLANNING", "SPACE_SELECTION", "SELLING", "ON_SITE"):
            cancel_show(show, "VENUE_CONTRACT_TERMINATED")


# ------------------------------------------------------------ appointments
def advance_selection_round(show):
    """PRD 3.4: increment the round, rank, activate, sweep and forfeit."""
    show["selection_round"] += 1
    round_index = show["selection_round"]
    appointments = calc.show_appointments(show["id"])
    previously_active = [a for a in appointments if a["state"] == "ACTIVE"]

    candidates = []
    for appointment in appointments:
        if appointment["state"] != "SCHEDULED":
            continue
        if appointment["round_index"] != round_index:
            continue
        exhibitor = db.exhibitors.get(appointment["exhibitor_id"])
        if exhibitor is None or exhibitor["status"] != "ACTIVE":
            continue
        window_end = _dt(appointment["window_end"])
        if window_end is None or not window_end > now():
            continue
        candidates.append((appointment, exhibitor))

    def order_key(pair):
        appointment, exhibitor = pair
        return (-calc.certified_priority_points(exhibitor),
                -exhibitor["consecutive_years"],
                exhibitor["created_at"],
                exhibitor["_seq"])

    candidates.sort(key=order_key)
    capacity = show["selection_desk_capacity"]
    for index, (appointment, exhibitor) in enumerate(candidates[:capacity]):
        appointment["rank"] = index + 1
        appointment["certified_points_at_rank"] = calc.certified_priority_points(exhibitor)
        appointment["state"] = "ACTIVE"
        touch(appointment)

    for appointment in by_created(appointments):
        if appointment["state"] != "SCHEDULED":
            continue
        exhibitor = db.exhibitors.get(appointment["exhibitor_id"])
        window_end = _dt(appointment["window_end"])
        elapsed = window_end is not None and window_end <= now()
        inactive = exhibitor is None or exhibitor["status"] != "ACTIVE"
        if elapsed or inactive:
            appointment["state"] = "EXPIRED"
            touch(appointment)

    for appointment in by_created(previously_active):
        appointment["state"] = "FORFEITED"
        touch(appointment)
        exhibitor = db.exhibitors.get(appointment["exhibitor_id"])
        if exhibitor is not None:
            add_penalty_points(exhibitor, calc.FORFEIT_PENALTY_POINTS)

    touch(show)


def _dt(value):
    from db import parse_dt
    return parse_dt(value)


# ------------------------------------------------- space contract creation
def open_space_contract(show, exhibitor, requested_sqft, premium, booths,
                        rebooked_from=None):
    """Shared body of POST /space-contracts, exercise and rebook (PRD 3.5)."""
    from db import base_row
    contract = base_row()
    contract.update({
        "show_id": show["id"],
        "exhibitor_id": exhibitor["id"],
        "rebooked_from_space_contract_id": rebooked_from,
        "status": "OFFERED",
        "requested_sqft": requested_sqft,
        "offered_booth_ids": [b["id"] for b in booths],
        "premium_placement_requested": premium,
        "requested_discount_pct": 0,
        "approved_discount_pct": 0,
        "negotiation_round": 0,
        "volume_tier_pct": 0,
        "space_fee_cents": 0,
        "sponsorship_attached_cents": 0,
        "bundle_discount_pct": 0,
        "bundle_discount_cents": 0,
        "invoice_total_cents": 0,
        "min_deposit_cents": 0,
        "deposit_paid_cents": 0,
        "cancellation_fee_cents": 0,
        "fee_applied_to_deposit_cents": 0,
        "refund_cents": 0,
        "balance_due_cents": 0,
        "points_awarded": 0,
        "signed_at": None,
        "last_offer_by_user_id": None,
        "cancellation_reason": None,
    })
    db.space_contracts[contract["id"]] = contract
    hold_booths(contract, booths)
    calc.price_space_fee(contract)
    return contract
