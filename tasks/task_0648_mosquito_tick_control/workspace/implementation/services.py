"""Business logic: calculations, schedule generation, state-machine side
effects, and cascades (PRD §3).

All monetary amounts are integer cents. Charge calculations follow a strict
sum-then-round discipline (PRD §2.8): components accumulated at full precision,
rounded exactly once at the end via round-half-up. We use decimal.Decimal for
the per-zone component and round once at the end.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import db
from clock import clock
from helpers import parse_date

# --- Constants (PRD §3.6, scaffold calculations) ---
AREA_TIER_BREAKS_SQFT = [5000, 10000, 20000]
AREA_TIER_SURCHARGE_CENTS = [0, 1500, 3500, 6000]
ZONE_RATE_CENTS_PER_1000_SQFT = {
    "TURF": 120,
    "PERIMETER": 200,
    "WATER_FEATURE": 350,
    "WOODLINE": 280,
}
SPECIAL_EVENT_SURCHARGE_CENTS = 4000
TICK_BARRIER_SEASON_CENTS = 8000

RESCHEDULE_LIMIT = 3
QUALIFYING_SEVERITIES = {"RAIN_HEAVY", "WIND_HIGH"}


def _round_half_up(value):
    """Round a Decimal value half-up to the nearest whole cent (integer)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _area_surcharge(total_sqft):
    if total_sqft <= AREA_TIER_BREAKS_SQFT[0]:
        return AREA_TIER_SURCHARGE_CENTS[0]
    elif total_sqft <= AREA_TIER_BREAKS_SQFT[1]:
        return AREA_TIER_SURCHARGE_CENTS[1]
    elif total_sqft <= AREA_TIER_BREAKS_SQFT[2]:
        return AREA_TIER_SURCHARGE_CENTS[2]
    return AREA_TIER_SURCHARGE_CENTS[3]


def _active_zones(property_id):
    return [
        z for z in db.treatment_zones.values()
        if z["property_id"] == property_id and z["status"] == "ACTIVE"
    ]


def _total_treatable_sqft(property_id):
    return sum(z["area_sqft"] for z in _active_zones(property_id))


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def visit_charge(visit, subscription, plan, prop):
    """Per-completed-visit charge (PRD §3.6).

    base + tiered area surcharge + summed per-zone component, rounded ONCE at
    the end. For a SPECIAL_EVENT visit: add a flat 4000-cent surcharge and
    DOUBLE the tiered area surcharge before the single final rounding.
    """
    base = plan["per_visit_price_cents"]
    total_sqft = _total_treatable_sqft(prop["id"])
    area_surcharge = _area_surcharge(total_sqft)

    is_special = visit["visit_kind"] == "SPECIAL_EVENT"
    if is_special:
        area_surcharge = area_surcharge * 2

    # Per-zone application component, accumulated at full precision.
    zone_component = Decimal(0)
    for z in _active_zones(prop["id"]):
        rate = ZONE_RATE_CENTS_PER_1000_SQFT[z["zone_type"]]
        zone_component += (Decimal(z["area_sqft"]) / Decimal(1000)) * Decimal(rate)

    raw = Decimal(base) + Decimal(area_surcharge) + zone_component
    if is_special:
        raw += Decimal(SPECIAL_EVENT_SURCHARGE_CENTS)

    return _round_half_up(raw)


def seasonal_charge(subscription, plan, planned_recurring_count):
    """Forward-looking seasonal charge (PRD §3.6).

    base + tick add-on, with a volume discount selected from the planned
    recurring visit count, applied as multiply-then-round-once.
    """
    base = plan["seasonal_price_cents"]
    tick_addon = TICK_BARRIER_SEASON_CENTS if plan["includes_tick_barrier"] else 0

    if planned_recurring_count >= 10:
        discount_bps = 1200
    elif planned_recurring_count >= 6:
        discount_bps = 700
    else:
        discount_bps = 0

    raw = Decimal(base) + Decimal(tick_addon)
    discounted = raw * Decimal(10000 - discount_bps) / Decimal(10000)
    return _round_half_up(discounted)


def retreat_guarantee_window_open(visit, plan):
    """PRD §3.5: open iff logical current date <= completed_at_date + days."""
    completed = parse_date(visit["completed_at_date"])
    deadline = completed + timedelta(days=plan["retreat_guarantee_days"])
    return clock.today() <= deadline


def cancellation_proration_refund(subscription, seasonal_invoice):
    """PRD §3.7: floor( amount * unserved / total )."""
    recurring = [
        v for v in db.visits.values()
        if v["subscription_id"] == subscription["id"] and v["visit_kind"] == "RECURRING"
    ]
    total_recurring = len(recurring)
    served = sum(1 for v in recurring if v["status"] == "COMPLETED")
    unserved = total_recurring - served
    if total_recurring == 0:
        return 0
    amount = Decimal(seasonal_invoice["amount_cents"]) * Decimal(unserved) / Decimal(total_recurring)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Schedule generation (Subscription DRAFT -> ACTIVE)
# ---------------------------------------------------------------------------
def generate_recurring_schedule(subscription, plan):
    """Generate one RECURRING Visit every visit_interval_days starting at
    season_start_date, sequence_index 1..N, while scheduled_date <=
    season_end_date (PRD §3.2). Returns the list of created visits."""
    start = parse_date(subscription["season_start_date"])
    end = parse_date(subscription["season_end_date"])
    interval = plan["visit_interval_days"]

    created = []
    seq = 1
    current = start
    while current <= end:
        visit = {
            "subscription_id": subscription["id"],
            "visit_kind": "RECURRING",
            "scheduled_date": current.isoformat(),
            "sequence_index": seq,
            "status": "SCHEDULED",
            "crew_route_id": None,
            "weather_event_id": None,
            "parent_visit_id": None,
            "reschedule_count": 0,
            "completed_at_date": None,
        }
        db.stamp_create_full(visit)
        db.visits[visit["id"]] = visit
        created.append(visit)
        seq += 1
        current = current + timedelta(days=interval)
    return created


def activate_subscription(subscription, plan):
    """Side effects of DRAFT -> ACTIVE (PRD §3.2 / §3.6).

    Generate the recurring schedule, transition to ACTIVE, and for SEASONAL
    billing issue the single seasonal invoice. Increments the subscription's
    version."""
    created = generate_recurring_schedule(subscription, plan)
    subscription["status"] = "ACTIVE"
    if subscription["billing_mode"] == "SEASONAL":
        amount = seasonal_charge(subscription, plan, len(created))
        invoice = {
            "subscription_id": subscription["id"],
            "visit_id": None,
            "invoice_type": "SEASONAL",
            "amount_cents": amount,
            "status": "ISSUED",
            "paid_amount_cents": 0,
        }
        db.stamp_create_full(invoice)
        db.invoices[invoice["id"]] = invoice
    db.touch(subscription)


# ---------------------------------------------------------------------------
# Off-season roll-over and pre-renewal (Subscription ACTIVE -> OFF_SEASON)
# ---------------------------------------------------------------------------
def off_season_transition(subscription):
    """Side effects of ACTIVE -> OFF_SEASON (PRD §3.9).

    Skip remaining SCHEDULED/WEATHER_HOLD visits; if auto_renew mint a DRAFT
    successor shifted 365 days forward and set renewed_into_subscription_id.
    Increments the subscription's version. Caller has already verified
    preconditions."""
    for v in db.visits.values():
        if v["subscription_id"] == subscription["id"] and v["status"] in ("SCHEDULED", "WEATHER_HOLD"):
            v["status"] = "SKIPPED"
            db.touch(v)

    subscription["status"] = "OFF_SEASON"

    if subscription["auto_renew"]:
        new_start = parse_date(subscription["season_start_date"]) + timedelta(days=365)
        new_end = parse_date(subscription["season_end_date"]) + timedelta(days=365)
        successor = {
            "property_id": subscription["property_id"],
            "service_plan_id": subscription["service_plan_id"],
            "billing_mode": subscription["billing_mode"],
            "season_start_date": new_start.isoformat(),
            "season_end_date": new_end.isoformat(),
            "status": "DRAFT",
            "auto_renew": subscription["auto_renew"],
            "renewed_into_subscription_id": None,
        }
        db.stamp_create_full(successor)
        db.subscriptions[successor["id"]] = successor
        subscription["renewed_into_subscription_id"] = successor["id"]

    db.touch(subscription)


def can_off_season(subscription):
    """Precondition: ACTIVE, logical date strictly > season_end_date, no
    DISPATCHED visit (PRD §3.9)."""
    if subscription["status"] != "ACTIVE":
        return False
    if not (clock.today() > parse_date(subscription["season_end_date"])):
        return False
    for v in db.visits.values():
        if v["subscription_id"] == subscription["id"] and v["status"] == "DISPATCHED":
            return False
    return True


def auto_roll_over_seasons():
    """Invoked on clock advance. Auto-transition every ACTIVE subscription whose
    season_end_date < new logical date to OFF_SEASON (PRD §1.5 _clock endpoint,
    §3.9). Iterate over a snapshot ordered by creation for determinism."""
    actives = [s for s in db.subscriptions.values() if s["status"] == "ACTIVE"]
    actives.sort(key=lambda s: (s["created_at"], s["_seq"]))
    for s in actives:
        if can_off_season(s):
            off_season_transition(s)


# ---------------------------------------------------------------------------
# Cancellation cascade (Subscription -> CANCELLED)
# ---------------------------------------------------------------------------
def cancel_active_cascade(subscription):
    """Side effects of ACTIVE -> CANCELLED (PRD §3.7).

    Cancel-cascade non-terminal visits; for SEASONAL with an ISSUED seasonal
    invoice, void it and credit a prorated refund to the wallet. Increments the
    subscription's version. Caller verified preconditions."""
    for v in db.visits.values():
        if v["subscription_id"] == subscription["id"] and v["status"] in (
            "SCHEDULED", "WEATHER_HOLD", "RETREAT_REQUESTED", "RETREAT_SCHEDULED"
        ):
            v["status"] = "CANCELLED"
            db.touch(v)

    subscription["status"] = "CANCELLED"

    if subscription["billing_mode"] == "SEASONAL":
        seasonal_inv = None
        for i in db.invoices.values():
            if (i["subscription_id"] == subscription["id"]
                    and i["invoice_type"] == "SEASONAL" and i["status"] == "ISSUED"):
                seasonal_inv = i
                break
        if seasonal_inv is not None:
            refund = cancellation_proration_refund(subscription, seasonal_inv)
            seasonal_inv["status"] = "VOID"
            db.touch(seasonal_inv)
            credit_wallet(subscription, refund)

    db.touch(subscription)


# ---------------------------------------------------------------------------
# Wallet (conserved credit, PRD §2.8 / §3.7)
# ---------------------------------------------------------------------------
def credit_wallet(subscription, amount_cents):
    """Credit amount_cents to the owning account holder's wallet."""
    if amount_cents <= 0:
        return
    prop = db.properties.get(subscription["property_id"])
    if prop is None:
        return
    holder = db.account_holders.get(prop["account_holder_id"])
    if holder is None:
        return
    holder["wallet_credit_cents"] += amount_cents
    db.touch(holder)


# ---------------------------------------------------------------------------
# Per-visit invoice on completion (PRD §3.4 / §3.6)
# ---------------------------------------------------------------------------
def issue_per_visit_invoice(visit, subscription, plan, prop):
    """For PER_VISIT billing on a non-RETREAT visit completion: issue a
    PER_VISIT invoice. RETREAT visits never bill."""
    if visit["visit_kind"] == "RETREAT":
        return None
    amount = visit_charge(visit, subscription, plan, prop)
    invoice = {
        "subscription_id": subscription["id"],
        "visit_id": visit["id"],
        "invoice_type": "PER_VISIT",
        "amount_cents": amount,
        "status": "ISSUED",
        "paid_amount_cents": 0,
    }
    db.stamp_create_full(invoice)
    db.invoices[invoice["id"]] = invoice
    return invoice
