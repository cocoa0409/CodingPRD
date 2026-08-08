"""Domain model: recompute functions, calculations, cascades, serializers."""
from datetime import timedelta
from decimal import Decimal

import state
from state import S, clock_dt, clock_date
from helpers import (round_half_up, ceil_div, fmt_instant, fmt_date, parse_date,
                     parse_instant, touch)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TURNOVER_BUFFER_DAYS = 2
MIN_NOTICE_DAYS = 14
NONPAYMENT_NOTICE_DAYS = 7
COMPLIANCE_NOTICE_DAYS = 14
STRIKE_WINDOW_DAYS = 90
STRIKE_SUSPENSION_THRESHOLD = 6
INCIDENT_WINDOW_DAYS = 30
RESTRICT_UPHELD_INCIDENT_COUNT = 3
MAX_APPLICATION_ROUNDS = 2
MAX_DISPUTE_ROUNDS = 2
MAX_CONCURRENT_VISITS_PER_HOUSE = 2
GRACE_DAYS = 3

INCOME_MULTIPLE = Decimal("3")
DEPOSIT_MULTIPLE = Decimal("1")
CONDITIONAL_DEPOSIT_MULTIPLE = Decimal("2")

LATE_FEE_TIER1_CEILING = 20000
LATE_FEE_TIER2_CEILING = 40000
LATE_FEE_TIER1 = 1500
LATE_FEE_TIER2 = 2500
LATE_FEE_TIER3 = 4000

SLA_HOURS = {"CRITICAL": 24, "HIGH": 72, "NORMAL": 168}
AREA_WEIGHT = {
    "ROOM": Decimal("1.00"),
    "SHARED_KITCHEN": Decimal("0.50"),
    "SHARED_BATH": Decimal("0.50"),
    "LAUNDRY": Decimal("0.25"),
    "COMMON_AREA": Decimal("0.25"),
}
MAINTENANCE_CREDIT_CAP_RATE = Decimal("0.25")
PLATFORM_FEE_RATE = Decimal("0.125")
PAYOUT_RESERVE_RATE = Decimal("0.05")
SEVERITY_POINTS = {"MINOR": 1, "MAJOR": 3, "SEVERE": 6}

_LIVE_TENANCY = {"PENDING_MOVE_IN", "ACTIVE", "NOTICE_GIVEN"}


# ---------------------------------------------------------------------------
# House room-state counts & compliance posture
# ---------------------------------------------------------------------------
def recompute_house_counts(house):
    hid = house["id"]
    rooms = [r for r in S.rooms.values() if r["house_id"] == hid]
    house["total_room_count"] = len(rooms)
    buckets = {
        "VACANT": "vacant_room_count",
        "RESERVED": "reserved_room_count",
        "OCCUPIED": "occupied_room_count",
        "NOTICE_PENDING": "notice_pending_room_count",
        "OUT_OF_SERVICE": "out_of_service_room_count",
    }
    for st, field in buckets.items():
        house[field] = sum(1 for r in rooms if r["occupancy_state"] == st)


def eval_posture(house):
    """Recompute counts and derive compliance_posture (frozen > restricted > open)."""
    recompute_house_counts(house)
    hid = house["id"]
    now = clock_dt()

    frozen = any(
        t["house_id"] == hid
        and t["severity"] == "CRITICAL"
        and t["status"] in ("OPEN", "SCHEDULED")
        and now > t["_sla_dt"]
        for t in S.tickets.values()
    )
    if frozen:
        house["compliance_posture"] = "FROZEN"
        return "FROZEN"

    notice_pending = house["notice_pending_room_count"]
    total = house["total_room_count"]
    turnover = (notice_pending * 2) > total  # strict > 0.5, exact rational

    window_start = now - timedelta(days=INCIDENT_WINDOW_DAYS)
    recent_upheld = sum(
        1 for i in S.incidents.values()
        if i["house_id"] == hid
        and i["status"] == "UPHELD"
        and i["_occurred_dt"] >= window_start
    )
    restricted = turnover or (recent_upheld >= RESTRICT_UPHELD_INCIDENT_COUNT)
    house["compliance_posture"] = "RESTRICTED" if restricted else "OPEN"
    return house["compliance_posture"]


# ---------------------------------------------------------------------------
# Member strike standing
# ---------------------------------------------------------------------------
def recompute_member_standing(member):
    mid = member["id"]
    membership_ids = {m["id"] for m in S.memberships.values() if m["member_id"] == mid}
    window_start = clock_dt() - timedelta(days=STRIKE_WINDOW_DAYS)
    pts = 0
    for i in S.incidents.values():
        if (i["membership_id"] in membership_ids
                and i["status"] == "UPHELD"
                and i["_occurred_dt"] >= window_start):
            pts += i["severity_points"]
    member["strike_points"] = pts
    if pts == 0:
        member["standing_band"] = "GOOD"
    elif pts < STRIKE_SUSPENSION_THRESHOLD:
        member["standing_band"] = "WATCH"
    else:
        member["standing_band"] = "PROBATION"


# ---------------------------------------------------------------------------
# Membership balance due
# ---------------------------------------------------------------------------
def recompute_balance(membership):
    mid = membership["id"]
    total = 0
    for inv in S.invoices.values():
        if inv["membership_id"] == mid and inv["status"] in ("OPEN", "PARTIAL", "PAST_DUE"):
            total += inv["total_amount_cents"] - inv["amount_paid_cents"]
    membership["balance_due_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Invoice charge assembly (STEP 1-3) and utility share
# ---------------------------------------------------------------------------
def occupied_rooms_at(house_id, period_start):
    """Count of distinct memberships covering period_start (a date)."""
    count = 0
    for m in S.memberships.values():
        if m["house_id"] != house_id:
            continue
        if m["tenancy_status"] not in ("ACTIVE", "NOTICE_GIVEN"):
            continue
        if parse_date(m["move_in_date"]) > period_start:
            continue
        amo = m["actual_move_out_date"]
        if amo is not None and parse_date(amo) < period_start:
            continue
        count += 1
    return count


def utility_share(house, membership, occupied_count):
    denom = max(occupied_count, 1)
    monthly_share = ceil_div(house["monthly_utility_budget_cents"], denom)
    if membership["billing_cycle"] == "MONTHLY":
        return monthly_share
    return ceil_div(monthly_share * 7, 30)


def period_subtotal_cents(membership, period_start):
    """base + utility for the period whose denominator is sampled at period_start."""
    house = S.houses[membership["house_id"]]
    occ = occupied_rooms_at(house["id"], period_start)
    base = membership["base_period_rate_cents"]
    util = utility_share(house, membership, occ)
    return base + util, occ, base, util


def late_fee_for_subtotal(subtotal):
    if subtotal < LATE_FEE_TIER1_CEILING:
        return LATE_FEE_TIER1
    if subtotal < LATE_FEE_TIER2_CEILING:
        return LATE_FEE_TIER2
    return LATE_FEE_TIER3


# ---------------------------------------------------------------------------
# Move-out proration
# ---------------------------------------------------------------------------
def target_period(membership, moveout_date):
    move_in = parse_date(membership["move_in_date"])
    pdays = membership["period_days"]
    k = (moveout_date - move_in).days // pdays
    if k < 0:
        k = 0
    start = move_in + timedelta(days=k * pdays)
    end = start + timedelta(days=pdays - 1)
    return start, end


def provisional_charge(membership, scheduled_move_out):
    """Variant A: full period subtotal, denominator sampled at notice instant."""
    start, _ = target_period(membership, scheduled_move_out)
    subtotal, _occ, _b, _u = period_subtotal_cents(membership, start)
    return subtotal


def matching_invoice(membership, moveout_date):
    """Invoice of this membership in OPEN/PARTIAL/PAST_DUE whose period covers moveout."""
    best = None
    for inv in S.invoices.values():
        if inv["membership_id"] != membership["id"]:
            continue
        if inv["status"] not in ("OPEN", "PARTIAL", "PAST_DUE"):
            continue
        ps = parse_date(inv["period_start"])
        pe = parse_date(inv["period_end"])
        if ps <= moveout_date <= pe:
            if best is None or ps > parse_date(best["period_start"]):
                best = inv
    return best


def final_settlement(membership, actual_move_out):
    """Variant B: daily accrual through actual_move_out inclusive."""
    start, _ = target_period(membership, actual_move_out)
    inv = matching_invoice(membership, actual_move_out)
    if inv is not None:
        subtotal = inv["subtotal_cents"]
    else:
        subtotal, _occ, _b, _u = period_subtotal_cents(membership, start)
    pdays = membership["period_days"]
    daily = round_half_up(Decimal(subtotal) / Decimal(pdays))
    occupied_days = (actual_move_out - start).days + 1
    final_charge = daily * occupied_days
    proration = final_charge - subtotal
    return final_charge, proration, inv


# ---------------------------------------------------------------------------
# Maintenance rent credit
# ---------------------------------------------------------------------------
def compute_ticket_credit(ticket):
    created = parse_instant(ticket["created_at"])
    resolved = ticket["_resolved_dt"]
    elapsed_hours = int((resolved - created).total_seconds() // 3600)
    sla = SLA_HOURS[ticket["severity"]]
    breach = max(0, elapsed_hours - sla)
    ticket["breach_hours"] = breach

    amid = ticket["affected_membership_id"]
    if amid is None or breach == 0:
        ticket["rent_credit_cents"] = 0
        return
    membership = S.memberships.get(amid)
    if membership is None:
        ticket["rent_credit_cents"] = 0
        return
    weight = AREA_WEIGHT[ticket["area"]]
    breach_days = ceil_div(breach, 24)
    daily = round_half_up(Decimal(membership["base_period_rate_cents"]) / Decimal(membership["period_days"]))
    raw = round_half_up(Decimal(daily) * breach_days * weight)
    cap = round_half_up(Decimal(membership["base_period_rate_cents"]) * MAINTENANCE_CREDIT_CAP_RATE)
    ticket["rent_credit_cents"] = min(raw, cap)


# ---------------------------------------------------------------------------
# Serializers  (strip internal underscore-prefixed keys)
# ---------------------------------------------------------------------------
def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_house(house):
    eval_posture(house)
    return serialize(house)


def serialize_member(member):
    recompute_member_standing(member)
    return serialize(member)


def serialize_membership(membership):
    recompute_balance(membership)
    return serialize(membership)
