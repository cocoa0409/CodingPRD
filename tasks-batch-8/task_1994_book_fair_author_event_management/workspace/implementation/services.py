"""Business logic: state-machine side effects, cascades, and calculations.

Calculation rounding doctrine (PRD section 2.7): publisher remittance and
return credits round half-up PER LINE then sum; the school profit share and
scrip uplift carry the full computation unrounded and round half-up once.
"""

import uuid
from datetime import timedelta

import db
from db import now_iso, fmt_dt
from util import D, rhu, floor_int, parse_dt_loose

AGREEMENT_MAX_ROUNDS = 6
BOOKING_MAX_ROUNDS = 4
SHRINK_TOLERANCE_UNITS = 2

BOOKING_TERMINAL = ("SETTLED", "CANCELLED", "DECLINED")
SESSION_TERMINAL = ("RECONCILED", "CANCELLED")
AGREEMENT_LIVE = ("PROPOSED", "COUNTERED")
PAYOUT_NON_TERMINAL = ("DRAFT", "CALCULATED", "APPROVED")


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity(**fields):
    ts = now_iso()
    entity = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
    entity.update(fields)
    return entity


def touch(entity):
    """Every state- or field-mutating write bumps version and updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def recompute_availability(line):
    """Copy-conservation invariant anchor (scaffold calc stock_qty_available)."""
    line["qty_available_for_sale"] = (
        line["qty_delivered"]
        - line["qty_held_preorder"]
        - line["qty_sold"]
        - line["qty_damaged"]
        - line["qty_returned_shipped"]
    )


# ---------------------------------------------------------------------------
# Offer expiry (PRD section 2.5): agreements only, never bookings
# ---------------------------------------------------------------------------

def agreement_lazy_expire(agreement):
    """Any access to a live agreement whose expiry has been reached EXPIRES it."""
    if agreement["status"] in AGREEMENT_LIVE and db.logical_clock >= parse_dt_loose(
        agreement["offer_expires_at"]
    ):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        return True
    return False


def sweep_agreement_expiry():
    expired = []
    for agreement in db.agreements.values():
        if agreement_lazy_expire(agreement):
            expired.append(agreement["id"])
    return expired


# ---------------------------------------------------------------------------
# Cancellation cascades (PRD sections 3.1 / 3.4)
# ---------------------------------------------------------------------------

def void_session_tickets(session):
    for ticket in db.tickets.values():
        if ticket["session_id"] == session["id"] and ticket["status"] in ("ISSUED", "ADMITTED"):
            ticket["status"] = "VOIDED"


def cancel_session(session):
    session["status"] = "CANCELLED"
    touch(session)
    void_session_tickets(session)


def recompute_honorarium(fair):
    total = 0
    for booking in db.bookings.values():
        if booking["fair_id"] != fair["id"]:
            continue
        if booking["status"] == "SETTLED":
            total += booking["settled_total_cents"] or 0
        elif booking["status"] == "CANCELLED":
            total += booking["kill_fee_cents"] or 0
    fair["honorarium_total_cents"] = total
    touch(fair)


def cancel_booking(booking):
    """Kill-fee schedule: 0 from INVITED/NEGOTIATING, 25% from CONFIRMED,
    50% from TRAVEL_BOOKED (round half-up of base_honorarium_cents)."""
    status = booking["status"]
    base = D(booking["base_honorarium_cents"])
    if status == "CONFIRMED":
        booking["kill_fee_cents"] = rhu(D("0.25") * base)
    elif status == "TRAVEL_BOOKED":
        booking["kill_fee_cents"] = rhu(D("0.50") * base)
    else:
        booking["kill_fee_cents"] = 0
    booking["status"] = "CANCELLED"
    touch(booking)
    for session in list(db.sessions.values()):
        if session["booking_id"] == booking["id"] and session["status"] in (
            "SCHEDULED",
            "OPEN_FOR_SIGNING",
            "CLOSED_FOR_SIGNING",
        ):
            cancel_session(session)
    recompute_honorarium(db.fairs[booking["fair_id"]])


def cancel_preorder(preorder):
    if preorder["status"] == "ALLOCATED":
        line = db.stock_lines[preorder["stock_line_id"]]
        line["qty_held_preorder"] -= preorder["qty"]
        recompute_availability(line)
        touch(line)
    preorder["status"] = "CANCELLED"
    touch(preorder)


def cascade_fair_cancel(fair):
    """Deliberate order: slots -> bookings (kill fees) -> their sessions ->
    their tickets -> preorders."""
    for slot in db.venue_slots.values():
        if slot["fair_id"] == fair["id"] and slot["status"] in ("HELD", "CONFIRMED"):
            slot["status"] = "RELEASED"
            touch(slot)
    for booking in db.bookings.values():
        if booking["fair_id"] == fair["id"] and booking["status"] not in BOOKING_TERMINAL:
            cancel_booking(booking)
    for preorder in db.preorders.values():
        if preorder["fair_id"] == fair["id"] and preorder["status"] in ("PLACED", "ALLOCATED"):
            cancel_preorder(preorder)


# ---------------------------------------------------------------------------
# Preorder allocation at STOCKING -> OPEN (scaffold calc preorder_allocation)
# ---------------------------------------------------------------------------

def run_preorder_allocation(fair):
    candidates = [
        p for p in db.preorders.values() if p["fair_id"] == fair["id"] and p["status"] == "PLACED"
    ]
    # Pinned order: created_at ASC, qty ASC, customer_name ASC (never id).
    candidates.sort(key=lambda p: (p["created_at"], p["qty"], p["customer_name"]))
    for preorder in candidates:
        line = db.stock_lines[preorder["stock_line_id"]]
        if preorder["qty"] <= line["qty_available_for_sale"]:
            preorder["status"] = "ALLOCATED"
            line["qty_held_preorder"] += preorder["qty"]
            recompute_availability(line)
            touch(line)
        else:
            preorder["status"] = "CONVERTED_BACKLIST"
        touch(preorder)


# ---------------------------------------------------------------------------
# Overlap regimes (PRD section 2.8)
# ---------------------------------------------------------------------------

def venue_conflict(venue_key, start_at, end_at, setup_minutes, teardown_minutes):
    """Buffered HALF-OPEN interval intersection against non-RELEASED slots
    sharing the venue_key. Touching endpoints do not conflict."""
    c_start = start_at - timedelta(minutes=setup_minutes)
    c_end = end_at + timedelta(minutes=teardown_minutes)
    for slot in db.venue_slots.values():
        if slot["venue_key"] != venue_key or slot["status"] == "RELEASED":
            continue
        s = parse_dt_loose(slot["start_at"]) - timedelta(minutes=slot["setup_buffer_minutes"])
        e = parse_dt_loose(slot["end_at"]) + timedelta(minutes=slot["teardown_buffer_minutes"])
        if c_start < e and s < c_end:
            return True
    return False


def signing_floor_exceeded(fair, start_at, end_at, line_space_units):
    """CLOSED-interval overlap: windows touching at an endpoint do overlap."""
    used = 0
    for session in db.sessions.values():
        if session["fair_id"] != fair["id"] or session["status"] == "CANCELLED":
            continue
        s = parse_dt_loose(session["start_at"])
        e = parse_dt_loose(session["end_at"])
        if start_at <= e and s <= end_at:
            used += session["line_space_units"]
    return (used + line_space_units) > fair["signing_floor_capacity_units"]


# ---------------------------------------------------------------------------
# Markdown band (validation 21)
# ---------------------------------------------------------------------------

def markdown_floor_cents(line):
    agreement = db.agreements[line["agreement_id"]]
    return floor_int(D(line["list_price_cents"]) * (1 - D(agreement["markdown_allowance_pct"])))


def price_within_band(line, unit_price_cents):
    return markdown_floor_cents(line) <= unit_price_cents <= line["list_price_cents"]


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------

def compute_provisional_lines(fair_id):
    """Per DELIVERED/RECONCILED line, expected_on_hand from CURRENT counters."""
    out = []
    lines = sorted(db.stock_lines.values(), key=lambda e: e["created_at"])
    for line in lines:
        if line["fair_id"] == fair_id and line["status"] in ("DELIVERED", "RECONCILED"):
            expected = (
                line["qty_delivered"]
                - line["qty_sold"]
                - line["qty_damaged"]
                - line["qty_returned_shipped"]
                - line["qty_held_preorder"]
            )
            out.append({"stock_line_id": line["id"], "expected_on_hand": expected})
    return out


def recompute_variance(recon):
    expected_map = {p["stock_line_id"]: p["expected_on_hand"] for p in recon["provisional_lines"]}
    variance_lines = []
    total = 0
    for counted in recon["counted_lines"]:
        expected = expected_map.get(counted["stock_line_id"])
        if expected is None:
            continue
        variance = counted["qty_on_hand"] - expected
        variance_lines.append(
            {
                "stock_line_id": counted["stock_line_id"],
                "expected_on_hand": expected,
                "qty_on_hand": counted["qty_on_hand"],
                "variance": variance,
            }
        )
        total += abs(variance)
    recon["variance_lines"] = variance_lines
    recon["total_abs_variance"] = total


def latest_reconciliation(fair_id):
    recs = [r for r in db.reconciliations.values() if r["fair_id"] == fair_id]
    if not recs:
        return None
    recs.sort(key=lambda r: r["created_at"])
    return recs[-1]


def accepted_agreements(fair_id):
    return [
        a for a in db.agreements.values() if a["fair_id"] == fair_id and a["status"] == "ACCEPTED"
    ]


def compute_remittance(fair_id):
    """Per FRONTLIST DELIVERED line: round_half_up(qty_sold * list * (1 - discount)),
    rounded per line first, then summed (pinned per-line-then-sum order)."""
    total = 0
    for line in db.stock_lines.values():
        if line["fair_id"] != fair_id or line["status"] != "DELIVERED":
            continue
        if line["line_type"] != "FRONTLIST":
            continue
        agreement = db.agreements[line["agreement_id"]]
        amount = D(line["qty_sold"]) * D(line["list_price_cents"]) * (1 - D(agreement["discount_pct"]))
        total += rhu(amount)
    return total


# ---------------------------------------------------------------------------
# Return credit waterfall (scaffold calc return_credit)
# ---------------------------------------------------------------------------

def compute_return_credit(ra):
    agreement = db.agreements[ra["agreement_id"]]
    discount = D(agreement["discount_pct"])
    restocking = D(agreement["restocking_fee_pct"])
    cap_pct = D(agreement["return_cap_pct"])
    total = 0
    for ra_line in ra["lines"]:
        line = db.stock_lines[ra_line["stock_line_id"]]
        cap = floor_int(cap_pct * D(line["qty_delivered"]))
        prior = 0
        for other in db.return_authorizations.values():
            if other["fair_id"] != ra["fair_id"] or other["id"] == ra["id"]:
                continue
            if other["status"] not in ("APPROVED", "SHIPPED", "CREDITED"):
                continue
            if other["created_at"] >= ra["created_at"]:
                continue
            for other_line in other["lines"]:
                if other_line["stock_line_id"] == line["id"]:
                    prior += other_line["qty"]
        qty = ra_line["qty"]
        in_cap = max(0, min(qty, cap - prior))
        over_cap = qty - in_cap
        price = D(line["list_price_cents"]) * (1 - discount)
        credit = rhu(D(in_cap) * price) + rhu(D(over_cap) * price * (1 - restocking))
        total += credit
    return total


# ---------------------------------------------------------------------------
# School payout (scaffold calc school_payout; pinned five-step evaluation)
# ---------------------------------------------------------------------------

def compute_payout(fair):
    gross = fair["gross_sales_cents"]
    promo_spend = sum(
        b["spend_cents"]
        for b in db.media_blasts.values()
        if b["fair_id"] == fair["id"] and b["status"] in ("APPROVED", "PUBLISHED")
    )
    costs = (
        fair["firm_purchases_cents"]
        + fair["publisher_remittance_cents"]
        - fair["return_credits_cents"]
        + fair["honorarium_total_cents"]
        + promo_spend
    )
    net_revenue = gross - costs
    if net_revenue <= 0:
        share = 0
    else:
        net = D(net_revenue)
        tier1 = D("0.20") * min(net, D(200000))
        tier2 = D("0.25") * max(D(0), min(net, D(600000)) - D(200000))
        tier3 = D("0.30") * max(D(0), net - D(600000))
        share = rhu(tier1 + tier2 + tier3)  # single final rounding
    cash = share
    scrip = rhu(D(share) * D("1.15"))
    return net_revenue, share, cash, scrip


# ---------------------------------------------------------------------------
# Signing bonus (scaffold calc signing_bonus)
# ---------------------------------------------------------------------------

def compute_session_bonus(session, booking):
    if session["mode"] == "FREE":
        return 0
    attendance = session["attendance_count"]
    threshold = booking["bonus_threshold_attendees"]
    if attendance >= threshold:
        return booking["bonus_base_cents"] + booking["bonus_per_attendee_cents"] * (
            attendance - threshold
        )
    return 0


def count_tickets(session_id, statuses):
    return sum(
        1
        for t in db.tickets.values()
        if t["session_id"] == session_id and t["status"] in statuses
    )


# ---------------------------------------------------------------------------
# Offer helpers for the two negotiation cycles
# ---------------------------------------------------------------------------

def offer_expired(entity):
    return db.logical_clock >= parse_dt_loose(entity["offer_expires_at"])


def reset_offer_expiry(entity, offer_expiry_hours):
    entity["offer_expires_at"] = fmt_dt(db.logical_clock + timedelta(hours=offer_expiry_hours))
