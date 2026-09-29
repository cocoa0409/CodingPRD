"""Calculations and cross-aggregate recomputations (PRD 3.4, 3.7, 3.8, 3.9)."""

from decimal import Decimal

from core import (
    BASE_BAG_FEE_CENTS,
    BOX_FACE_VALUE_CENTS,
    CLAIM_WEIGHT,
    COUNTERFEIT_WEIGHT,
    GRADE_A_MIN,
    GRADE_B_MIN,
    GRADE_C_MIN,
    HAIRCUT_PCT_BY_TIER,
    MIXED_HANDLING_SURCHARGE_CENTS,
    PER_KG_COIN_RATE_CENTS,
    PER_NOTE_RATE_MILLICENTS,
    PROVISIONAL_CREDIT_CAP_CENTS,
    SCORE_CEILING,
    SCORE_FLOOR,
    VARIANCE_WEIGHT,
    VOLUME_DISCOUNT_1_PCT,
    VOLUME_DISCOUNT_2_PCT,
    VOLUME_TIER_1_CENTS,
    VOLUME_TIER_2_CENTS,
    bags_of_ticket,
    db,
    round_half_up,
    rhu_int,
    touch,
)

COUNTED_STATES = ("COUNTED", "ADJUSTED")


# --------------------------------------------------------------------------
# Vault coin position
# --------------------------------------------------------------------------
def recompute_vault_coin_face_value(vault):
    total = 0
    for row in db.inventory.values():
        if row["vault_id"] == vault["id"]:
            total += row["on_hand_boxes"] * BOX_FACE_VALUE_CENTS[row["denomination"]]
    vault["coin_face_value_on_hand_cents"] = total


def recompute_available_boxes(inv):
    inv["available_boxes"] = max(inv["on_hand_boxes"] - inv["reserved_boxes"], 0)


# --------------------------------------------------------------------------
# Bag / ticket recomputation
# --------------------------------------------------------------------------
def recompute_bag_settlement(bag):
    bag["settlement_amount_cents"] = (
        bag["counted_amount_cents"] + bag["claim_adjustment_cents"] - bag["seized_amount_cents"]
    )


def recompute_ticket_declared_total(ticket):
    ticket["declared_total_cents"] = sum(
        b["declared_amount_cents"] for b in bags_of_ticket(ticket["id"])
    )


def recompute_ticket_counted_total(ticket):
    ticket["counted_total_cents"] = sum(
        b["settlement_amount_cents"]
        for b in bags_of_ticket(ticket["id"])
        if b["count_status"] in COUNTED_STATES
    )


def recompute_ticket_processing_fee_total(ticket):
    # Exact integer sum of already-rounded per-bag fees; never re-rounded.
    ticket["processing_fee_total_cents"] = sum(
        b["processing_fee_cents"]
        for b in bags_of_ticket(ticket["id"])
        if b["count_status"] in COUNTED_STATES
    )


# --------------------------------------------------------------------------
# bag_processing_fee (PRD 3.4)
# --------------------------------------------------------------------------
def bag_processing_fee_cents(bag):
    raw = BASE_BAG_FEE_CENTS
    raw += (Decimal(bag["counted_note_count"]) * PER_NOTE_RATE_MILLICENTS) / Decimal(1000)
    raw += (Decimal(bag["counted_coin_weight_grams"]) / Decimal(1000)) * PER_KG_COIN_RATE_CENTS
    if bag["bag_type"] == "MIXED":
        raw += MIXED_HANDLING_SURCHARGE_CENTS
    return rhu_int(raw)


# --------------------------------------------------------------------------
# deposit_credit_amount (PRD 3.3 / 3.7)
# --------------------------------------------------------------------------
def provisional_credit_amount(ticket, account):
    eligible = sum(
        b["declared_amount_cents"]
        for b in bags_of_ticket(ticket["id"])
        if b["custody_status"] in ("VAULT_RECEIVED", "OPENED")
    )
    haircut = HAIRCUT_PCT_BY_TIER[account["tier"]]
    rounded = rhu_int(Decimal(eligible) * (Decimal(1) - haircut))
    return min(rounded, PROVISIONAL_CREDIT_CAP_CENTS)


def final_settlement_amounts(ticket):
    gross = sum(
        b["settlement_amount_cents"]
        for b in bags_of_ticket(ticket["id"])
        if b["count_status"] in COUNTED_STATES
    )
    if gross >= VOLUME_TIER_2_CENTS:
        discount = VOLUME_DISCOUNT_2_PCT
    elif gross >= VOLUME_TIER_1_CENTS:
        discount = VOLUME_DISCOUNT_1_PCT
    else:
        discount = Decimal("0.00")
    fee_final = rhu_int(Decimal(ticket["processing_fee_total_cents"]) * (Decimal(1) - discount))
    final_settlement = gross - fee_final
    delta = final_settlement - ticket["provisional_credit_cents"]
    return final_settlement, delta


# --------------------------------------------------------------------------
# customer_risk_grade (PRD 3.7)
# --------------------------------------------------------------------------
def _grade_for(score):
    if score >= GRADE_A_MIN:
        return "A"
    if score >= GRADE_B_MIN:
        return "B"
    if score >= GRADE_C_MIN:
        return "C"
    return "D"


def _risk_from(tickets, counterfeit_count, denied_claim_count):
    total_declared = 0
    total_abs_variance = 0
    for ticket in tickets:
        total_declared += ticket["declared_total_cents"]
        for bag in bags_of_ticket(ticket["id"]):
            if bag["count_status"] in COUNTED_STATES:
                total_abs_variance += abs(bag["variance_cents"])

    if total_declared == 0:
        variance_ratio_pct = Decimal("0.00")
    else:
        variance_ratio_pct = round_half_up(
            Decimal(100) * Decimal(total_abs_variance) / Decimal(total_declared), 2
        )

    raw = (
        Decimal(100)
        - VARIANCE_WEIGHT * variance_ratio_pct
        - COUNTERFEIT_WEIGHT * Decimal(counterfeit_count)
        - CLAIM_WEIGHT * Decimal(denied_claim_count)
    )
    clamped = max(SCORE_FLOOR, min(SCORE_CEILING, raw))
    score = round_half_up(clamped, 2)
    return score, _grade_for(score)


def _tickets_of_account(account_id):
    return [t for t in db.tickets.values() if t["customer_account_id"] == account_id]


def risk_settled_only(account):
    tickets = [t for t in _tickets_of_account(account["id"]) if t["status"] == "SETTLED"]
    return _risk_from(tickets, account["counterfeit_incident_count"], account["denied_claim_count"])


POINT_IN_TIME_STATES = (
    "VERIFIED",
    "PROVISIONAL_CREDITED",
    "HELD",
    "SETTLEMENT_READY",
    "SETTLED",
)


def _draft_report_count_for_account(account_id):
    count = 0
    for report in db.reports.values():
        if report["status"] != "DRAFT":
            continue
        lot = db.lots.get(report["fitness_lot_id"])
        if lot is None:
            continue
        session = db.sessions.get(lot["count_session_id"])
        if session is None:
            continue
        bag = db.bags.get(session["sealed_bag_id"])
        if bag is None:
            continue
        ticket = db.tickets.get(bag["deposit_ticket_id"])
        if ticket is None:
            continue
        if ticket["customer_account_id"] == account_id:
            count += 1
    return count


def risk_point_in_time(account):
    tickets = [
        t for t in _tickets_of_account(account["id"]) if t["status"] in POINT_IN_TIME_STATES
    ]
    counterfeit = account["counterfeit_incident_count"] + _draft_report_count_for_account(
        account["id"]
    )
    return _risk_from(tickets, counterfeit, account["denied_claim_count"])


def apply_settled_only_risk(account):
    score, grade = risk_settled_only(account)
    account["risk_score"] = score
    account["risk_grade"] = grade


def recompute_account_available(account):
    account["available_balance_cents"] = (
        account["ledger_balance_cents"] + account["provisional_credit_cents"]
    )


# --------------------------------------------------------------------------
# coin_order_allocation (PRD 3.9)
# --------------------------------------------------------------------------
def fill_ratio(total_allocated, total_requested):
    if total_requested == 0:
        return Decimal("0.00")
    return round_half_up(
        Decimal(100) * Decimal(total_allocated) / Decimal(total_requested), 2
    )
