"""Calculation rules from SCAFFOLD.yaml Table 3 / PRD §3.5, §3.8-§3.10.

All money math uses Decimal. Percentages 2dp; adjusted tons 4dp round-half-up;
monetary values integer cents round-half-up; sugar pounds 2dp round-half-up;
final price 4dp round-half-up.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

LBS_PER_TON = Decimal("2000")
FREE_TRASH_PCT = Decimal("3.00")
HEAVY_TRASH_PCT = Decimal("10.00")
HEAVY_MULTIPLIER = Decimal("1.5")
REJECT_TRASH_PCT = Decimal("20.00")

REF_SUGAR_PCT = Decimal("16.00")
FACTOR_SLOPE = Decimal("0.04")
PROV_CLAMP_MIN = Decimal("0.70")
PROV_CLAMP_MAX = Decimal("1.30")
LOW_SUGAR_PCT = Decimal("13.00")
LOW_SUGAR_PENALTY = Decimal("0.05")

DAILY_LOSS_PCT = Decimal("0.0008")
LOSS_DECLARED_PCT = Decimal("5.00")

# transport rate bands (cents per adjusted net ton), left-closed right-open
BANDS = [
    (Decimal("15"), Decimal("120")),
    (Decimal("40"), Decimal("180")),
    (Decimal("80"), Decimal("240")),
]
BAND_4_RATE = Decimal("300")


def D(v):
    """Coerce input to Decimal without going through float."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q2(v):
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(v):
    return v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q0(v):
    return v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# net_weight_and_trash_deduction
# ---------------------------------------------------------------------------

def adjusted_net_tons(net_weight_lbs, trash_pct):
    """Adjusted net tons for a given net weight (lbs) and trash pct.

    deductible_pct = max(0, t - 3.00)
    multiplier = 1.5 if t >= 10.00 else 1.0
    deducted_pct = min(deductible_pct * multiplier, t)
    adjusted = round_half_up(net_lbs / 2000 * (1 - deducted_pct/100), 4)
    """
    net = D(net_weight_lbs)
    t = D(trash_pct)
    deductible = t - FREE_TRASH_PCT
    if deductible < 0:
        deductible = Decimal("0")
    multiplier = HEAVY_MULTIPLIER if t >= HEAVY_TRASH_PCT else Decimal("1.0")
    deducted = deductible * multiplier
    if deducted > t:
        deducted = t
    adjusted = (net / LBS_PER_TON) * (Decimal("1") - deducted / Decimal("100"))
    return q4(adjusted)


# ---------------------------------------------------------------------------
# payment_factor
# ---------------------------------------------------------------------------

def payment_factor_provisional(sugar_pct):
    base = Decimal("1.00") + (D(sugar_pct) - REF_SUGAR_PCT) * FACTOR_SLOPE
    if base < PROV_CLAMP_MIN:
        base = PROV_CLAMP_MIN
    if base > PROV_CLAMP_MAX:
        base = PROV_CLAMP_MAX
    return q4(base)


def payment_factor_final(sugar_pct):
    s = D(sugar_pct)
    f = Decimal("1.00") + (s - REF_SUGAR_PCT) * FACTOR_SLOPE
    if s < LOW_SUGAR_PCT:
        f = f - LOW_SUGAR_PENALTY
    return q4(f)


# ---------------------------------------------------------------------------
# provisional_value
# ---------------------------------------------------------------------------

def provisional_value_cents(provisional_adjusted_net_tons, base_price_cents_per_ton, provisional_factor):
    v = D(provisional_adjusted_net_tons) * D(base_price_cents_per_ton) * D(provisional_factor)
    return int(q0(v))


# ---------------------------------------------------------------------------
# transport_allowance (round each ticket first, then sum)
# ---------------------------------------------------------------------------

def transport_rate_for_miles(miles):
    m = D(miles)
    if m < BANDS[0][0]:
        return BANDS[0][1]
    if m < BANDS[1][0]:
        return BANDS[1][1]
    if m < BANDS[2][0]:
        return BANDS[2][1]
    return BAND_4_RATE


def transport_allowance_cents_for_ticket(adjusted_net_tons_final, member):
    rate = transport_rate_for_miles(member["haul_distance_miles"])
    return int(q0(D(adjusted_net_tons_final) * rate))


# ---------------------------------------------------------------------------
# deterioration_loss
# ---------------------------------------------------------------------------

def table_rate_loss(sealed_stored_lbs, sealed_at, survey_at):
    days = int((survey_at - sealed_at).total_seconds() // 86400)
    loss = D(sealed_stored_lbs) * DAILY_LOSS_PCT * Decimal(days)
    return q2(loss)


def resurvey_loss(sealed_stored_lbs, prior_confirmed_loss_lbs, measured_remaining_lbs):
    loss = D(sealed_stored_lbs) - D(prior_confirmed_loss_lbs) - D(measured_remaining_lbs)
    return q2(loss)


# ---------------------------------------------------------------------------
# loss_allocation (waterfall)
# ---------------------------------------------------------------------------

def allocate_loss(loss_lbs, allocations):
    """Distribute loss across ACTIVE allocations.

    allocations: list of allocation dicts (mutable).
    Returns (distributed_total_decimal, per_allocation_share: dict id->Decimal).
    """
    loss = D(loss_lbs)
    actives = [a for a in allocations if a["status"] == "ACTIVE"]
    total_remaining = sum((D(a["remaining_lbs"]) for a in actives), Decimal("0"))
    if total_remaining == 0 or not actives:
        return Decimal("0"), {}

    shares = {}
    for a in actives:
        raw = loss * D(a["remaining_lbs"]) / total_remaining
        # floor toward zero to 2 decimal places
        share = raw.quantize(Decimal("0.01"), rounding="ROUND_FLOOR")
        shares[a["id"]] = share

    remainder = loss - sum(shares.values(), Decimal("0"))
    # distribute remainder in 0.01-lb units, ordered by remaining_lbs DESC,
    # tie-break allocation created_at ASC, one unit per pass, largest first
    units = int((remainder / Decimal("0.01")).to_integral_value(rounding="ROUND_FLOOR"))
    order = sorted(actives, key=lambda a: (-D(a["remaining_lbs"]), a["created_at"]))
    i = 0
    while units > 0 and order:
        a = order[i % len(order)]
        shares[a["id"]] = shares[a["id"]] + Decimal("0.01")
        units -= 1
        i += 1

    distributed = sum(shares.values(), Decimal("0"))
    return distributed, shares


# ---------------------------------------------------------------------------
# waitlist_promotion (selector)
# ---------------------------------------------------------------------------

def waitlist_promotion_scan(station):
    """Promote eligible WAITLISTED bookings at the station until none fit."""
    import services.cascade as cascade  # local import to avoid cycle

    while True:
        capacity = D(station["booking_capacity_tons"])
        booked = D(station["booked_tons"])
        free = capacity - booked
        candidates = [
            b for b in db.bookings.values()
            if b["station_id"] == station["id"]
            and b["status"] == "WAITLISTED"
            and D(b["estimated_tons"]) <= free
        ]
        if not candidates:
            return

        def rank_key(b):
            m = db.members.get(b["member_id"])
            code = m["member_code"] if m else ""
            return (b["created_at"], code)

        candidates.sort(key=rank_key)
        top = candidates[0]
        top["status"] = "CONFIRMED"
        db.touch(top)
        station["booked_tons"] = D(station["booked_tons"]) + D(top["estimated_tons"])
        db.touch(station)
        cascade.recompute_station(station["id"])


# ---------------------------------------------------------------------------
# installment_waterfall
# ---------------------------------------------------------------------------

def installment_waterfall(installment, pool, campaign):
    """Compute per-member advances. Returns list of (member, amount_cents)."""
    target = int(installment["target_amount_cents"])
    # E_m = sum of provisional_value_cents over member's CREDITED tickets
    E = {}
    for t in db.tickets.values():
        if t["status"] != "CREDITED":
            continue
        bkg = db.bookings.get(t["booking_id"])
        if not bkg or bkg["campaign_id"] != campaign["id"]:
            continue
        E[t["member_id"]] = E.get(t["member_id"], 0) + int(t["provisional_value_cents"] or 0)

    eligible = {mid: e for mid, e in E.items() if e > 0}
    if not eligible:
        return []

    sumE = sum(eligible.values())
    floors = {}
    for mid, e in eligible.items():
        raw = Decimal(target) * Decimal(e) / Decimal(sumE)
        floors[mid] = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
    remainder = target - sum(floors.values())

    order = sorted(
        eligible.keys(),
        key=lambda mid: (-eligible[mid], db.members[mid]["member_code"]),
    )
    extra = {mid: 0 for mid in eligible}
    i = 0
    while remainder > 0 and order:
        mid = order[i % len(order)]
        extra[mid] += 1
        remainder -= 1
        i += 1

    result = []
    for mid in eligible:
        gross = floors[mid] + extra[mid]
        # cap: advance <= E_m - already_advanced_m (net ADVANCE_CREDIT for this pool)
        already = 0
        for le in db.ledger_entries.values():
            if le["member_id"] == mid and le["pool_id"] == pool["id"] and le["kind"] in ("ADVANCE_CREDIT", "REVERSAL"):
                # REVERSAL of an advance carries negated amount; including both kinds nets out
                if le["installment_id"] is not None or le["kind"] == "REVERSAL":
                    already += int(le["amount_cents"])
        cap = eligible[mid] - already
        adv = gross if gross < cap else cap
        if adv < 0:
            adv = 0
        if adv > 0:
            result.append((db.members[mid], int(adv)))
    return result


# ---------------------------------------------------------------------------
# final_pool_price
# ---------------------------------------------------------------------------

def ticket_sugar_lbs(ticket):
    """Post-loss sugar pounds for a CREDITED ticket: remaining_lbs_total * final_sugar_pct / 100, 2dp."""
    remaining_total = sum(
        (D(a["remaining_lbs"]) for a in db.pile_allocations.values() if a["ticket_id"] == ticket["id"]),
        Decimal("0"),
    )
    return q2(remaining_total * D(ticket["final_sugar_pct"]) / Decimal("100"))


def total_sugar_lbs_for_campaign(campaign_id):
    total = Decimal("0")
    for t in db.tickets.values():
        if t["status"] != "CREDITED":
            continue
        bkg = db.bookings.get(t["booking_id"])
        if not bkg or bkg["campaign_id"] != campaign_id:
            continue
        total += ticket_sugar_lbs(t)
    return total


def final_pool_price(gross_pool_value_cents, total_sugar_lbs):
    return q4(D(gross_pool_value_cents) / total_sugar_lbs)
