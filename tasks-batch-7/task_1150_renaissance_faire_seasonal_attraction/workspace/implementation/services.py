"""Domain services: readiness posture, lazy expiry, cascades, calculations.

Calculation constants and formulas come from SCAFFOLD.yaml section 1.3 and
PRD sections 2.6 / 2.7 / 3.
"""
from datetime import timedelta
from decimal import Decimal

from db import store, new_id, next_seq, clock_now
from util import mutate, touch, new_record, rhu, rhu2, dec, hours_between

# ---------------------------------------------------------------------------
# Pinned system constants
# ---------------------------------------------------------------------------
CONVENIENCE_FEE_CENTS = 150
GROUP_TIER1_PCT = Decimal("0.10")
GROUP_TIER2_PCT = Decimal("0.15")
GROUP_TIER3_PCT = Decimal("0.20")
GROUP_TIER2_MULT = 2
GROUP_TIER3_MULT = 4

TIER_RATES = {"PRIME": 120, "STANDARD": 80, "MEADOW": 50}  # cents/sqft/week
RAIN_CREDIT_PCT = Decimal("0.25")
PRIME_SURCHARGE_PCT = Decimal("0.05")
PRIME_SURCHARGE_THRESHOLD_CENTS = 20000
REHEARSAL_SHORTFALL_CENTS_PER_HOUR = 5000

# Fixed system values named symbolically in the spec (no numeric value pinned).
PERMIT_GRACE_DAYS = 30
MAX_INSPECTION_ATTEMPTS = 3

REHEARSAL_TURNOVER = timedelta(minutes=15)

CONTRACT_TERMINAL = {"COMPLETED", "TERMINATED"}
APPLICATION_TERMINAL = {"WITHDRAWN"}
BOOTH_TERMINAL = {"RELEASED", "SETTLED"}
PERMIT_TERMINAL = {"FAILED_FINAL", "REVOKED", "EXPIRED"}
SHIFT_TERMINAL = {"WORKED", "NO_SHOW", "CANCELLED"}
DAY_TERMINAL = {"COMPLETED", "CANCELLED_WEATHER"}
ORDER_REDEMPTION_TERMINAL = {"FULLY_REDEEMED", "RAINCHECKED", "VOID"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def season_of(record, key="season_id"):
    return store.seasons.get(record[key])


def applications_of_season(season_id):
    return [a for a in store.applications.values() if a["season_id"] == season_id]


def booths_of_season(season_id):
    return [b for b in store.booths.values() if b["season_id"] == season_id]


def booths_of_application(application_id):
    return [b for b in store.booths.values() if b["application_id"] == application_id]


def permits_of_application(application_id):
    return [p for p in store.permits.values() if p["application_id"] == application_id]


def tickets_of_order(order_id):
    return [t for t in store.tickets.values() if t["order_id"] == order_id]


def tickets_of_day(faire_day_id):
    return [t for t in store.tickets.values() if t["faire_day_id"] == faire_day_id]


def rain_checks_of_season(season_id):
    return [r for r in store.rain_checks.values() if r["season_id"] == season_id]


def contracts_of_season(season_id):
    return [c for c in store.contracts.values() if c["season_id"] == season_id]


def shifts_of_day(faire_day_id):
    return [s for s in store.shifts.values() if s["faire_day_id"] == faire_day_id]


def shifts_of_season(season_id):
    return [s for s in store.shifts.values() if s["season_id"] == season_id]


def tasks_of_season(season_id):
    return [t for t in store.tasks.values() if t["season_id"] == season_id]


def tickets_sold_count(day):
    """count(Ticket of this day with status in {VALID, REDEEMED})."""
    return sum(
        1
        for t in store.tickets.values()
        if t["faire_day_id"] == day["id"] and t["status"] in ("VALID", "REDEEMED")
    )


# ---------------------------------------------------------------------------
# Lazy expiry (PRD section 2.5)
# ---------------------------------------------------------------------------

def lazy_expire_permit(permit):
    """ISSUED permit past its expiry_date -> EXPIRED, with the booth cascade.

    At exactly expiry_date the permit still counts as valid, so the trigger is
    clock now strictly greater than expiry_date.
    """
    if permit["status"] != "ISSUED":
        return False
    expiry = permit.get("expiry_date")
    if expiry is None or clock_now() <= expiry:
        return False
    mutate(permit, status="EXPIRED")
    _suspend_booths_of_application(permit["application_id"])
    app = store.applications.get(permit["application_id"])
    if app is not None:
        season = store.seasons.get(app["season_id"])
        if season is not None:
            rederive_posture(season)
    return True


def lazy_expire_rain_check(check):
    """ISSUED rain check past redeem_by_date -> EXPIRED; outstanding -1."""
    if check["status"] != "ISSUED":
        return False
    if clock_now() <= check["redeem_by_date"]:
        return False
    mutate(check, status="EXPIRED")
    season = store.seasons.get(check["season_id"])
    if season is not None:
        adjust_outstanding(season, -1)
    return True


def _suspend_booths_of_application(application_id):
    for booth in booths_of_application(application_id):
        if booth["status"] == "CONFIRMED":
            mutate(booth, status="SUSPENDED")


# ---------------------------------------------------------------------------
# Season counters and readiness posture
# ---------------------------------------------------------------------------

def adjust_outstanding(season, delta):
    if delta:
        mutate(season, outstanding_admissions=season["outstanding_admissions"] + delta)


def adjust_volunteer_hours(season, delta):
    if delta:
        mutate(
            season,
            volunteer_confirmed_hours=season["volunteer_confirmed_hours"] + dec(delta),
        )


def _season_has_food_permit_gap(season):
    """A JURIED_IN FOOD/BEVERAGE application lacking an ISSUED, unexpired permit."""
    now = clock_now()
    for app in applications_of_season(season["id"]):
        if app["status"] != "JURIED_IN":
            continue
        vendor = store.vendors.get(app["vendor_id"])
        if vendor is None or vendor["category"] not in ("FOOD", "BEVERAGE"):
            continue
        ok = False
        for permit in permits_of_application(app["id"]):
            if (
                permit["status"] == "ISSUED"
                and permit.get("expiry_date") is not None
                and permit["expiry_date"] >= now
            ):
                ok = True
                break
        if not ok:
            return True
    return False


def rederive_posture(season):
    """PRD section 2.6 derivation, evaluated in the pinned order.

    Re-derivation is also a trigger for lazy food-permit expiry (PRD 2.5);
    those expiries fire their booth-suspension cascade first, then the
    posture value is computed once.
    """
    now = clock_now()
    # Lazy permit sweep for every permit of this season.
    for app in applications_of_season(season["id"]):
        for permit in permits_of_application(app["id"]):
            if (
                permit["status"] == "ISSUED"
                and permit.get("expiry_date") is not None
                and now > permit["expiry_date"]
            ):
                mutate(permit, status="EXPIRED")
                _suspend_booths_of_application(app["id"])

    build_open = any(
        t["phase"] == "BUILD" and t["status"] != "DONE"
        for t in tasks_of_season(season["id"])
    )
    if build_open:
        posture = "BLOCKED"
    else:
        food_gap = _season_has_food_permit_gap(season)
        hours_short = season["volunteer_confirmed_hours"] < season["volunteer_min_hours"]
        if food_gap or hours_short:
            posture = "CONDITIONAL"
        else:
            posture = "READY"
    mutate(season, readiness_posture=posture)


# ---------------------------------------------------------------------------
# TicketOrder redemption recompute (PRD section 3.5)
# ---------------------------------------------------------------------------

def recompute_order_redemption(order, cause):
    current = order["redemption_status"]
    if current in ORDER_REDEMPTION_TERMINAL:
        return
    tickets = tickets_of_order(order["id"])
    valid = sum(1 for t in tickets if t["status"] == "VALID")
    voided = sum(1 for t in tickets if t["status"] == "VOID")
    new = current
    if cause == "redeem":
        new = "FULLY_REDEEMED" if valid == 0 else "PARTIALLY_REDEEMED"
    elif cause == "raincheck":
        if tickets and all(t["status"] == "RAINCHECKED" for t in tickets):
            new = "RAINCHECKED"
    elif cause == "void":
        if valid == 0 and voided > 0:
            new = "VOID"
    if new != current:
        mutate(order, redemption_status=new)


# ---------------------------------------------------------------------------
# Pricing / fee / payout calculations (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

def price_order(season, order_type, quantity, unit_price_cents):
    """ticket_order_total: tiered group discount + DAY convenience fee."""
    base = quantity * unit_price_cents
    discount = Decimal("0")
    if order_type == "GROUP":
        gmin = season["group_min_size"]
        if quantity >= GROUP_TIER3_MULT * gmin:
            discount = GROUP_TIER3_PCT
        elif quantity >= GROUP_TIER2_MULT * gmin:
            discount = GROUP_TIER2_PCT
        elif quantity >= gmin:
            discount = GROUP_TIER1_PCT
    fee = quantity * CONVENIENCE_FEE_CENTS if order_type == "DAY" else 0
    total = rhu(Decimal(base) * (Decimal(1) - discount)) + fee
    return discount, total


def provisional_fee(application, season):
    rate = TIER_RATES[application["requested_location_tier"]]
    return application["booth_size_sqft"] * rate * season["season_weeks"]


def settlement_fees(booth, application):
    """booth_final_fee: pinned evaluation order (surcharge on post-credit subtotal)."""
    subtotal = booth["provisional_fee_cents"] - booth["weather_credit_cents"]
    surcharge = 0
    if (
        application["requested_location_tier"] == "PRIME"
        and subtotal >= PRIME_SURCHARGE_THRESHOLD_CENTS
    ):
        surcharge = rhu(Decimal(subtotal) * PRIME_SURCHARGE_PCT)
    final_fee = subtotal + surcharge
    delta = final_fee - booth["provisional_fee_cents"]
    return final_fee, delta


def weather_day_credit(booth):
    """weather_vendor_credit: per-day rounded quarter-fee over residency days."""
    days = (booth["residency_end_date"] - booth["residency_start_date"]).days
    return rhu(Decimal(booth["provisional_fee_cents"]) * RAIN_CREDIT_PCT / Decimal(days))


def cast_final_payout_completed(contract):
    """cast_final_payout on COMPLETED: guarantee floor minus rehearsal penalty, >= 0."""
    shortfall = max(
        Decimal(0),
        dec(contract["required_rehearsal_hours"]) - dec(contract["completed_rehearsal_hours"]),
    )
    penalty = rhu(shortfall * REHEARSAL_SHORTFALL_CENTS_PER_HOUR)
    guarantee = contract["guaranteed_days"] * contract["offered_day_rate_cents"]
    final = max(contract["accrued_payout_cents"], guarantee) - penalty
    return max(0, final)


def weather_accrual_line(contract):
    return rhu(Decimal(contract["offered_day_rate_cents"]) * dec(contract["weather_pay_pct"]))


def jury_score_of(craft, authenticity, safety):
    return rhu2(Decimal("0.5") * dec(craft) + Decimal("0.3") * dec(authenticity) + Decimal("0.2") * dec(safety))


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_faire_day_cascade(day, season):
    """PRD 3.6 five-part weather cascade, in narrative order."""
    mutate(day, status="CANCELLED_WEATHER")

    # First: VALID DAY tickets -> RAINCHECKED, 1:1 ISSUED rain checks.
    affected_orders = []
    for ticket in tickets_of_day(day["id"]):
        if ticket["ticket_type"] == "DAY" and ticket["status"] == "VALID":
            mutate(ticket, status="RAINCHECKED")
            check = new_record()
            check.update(
                {
                    "id": new_id(),
                    "_seq": next_seq(),
                    "season_id": season["id"],
                    "ticket_id": ticket["id"],
                    "issued_for_day_id": day["id"],
                    "status": "ISSUED",
                    "redeem_by_date": season["closing_date"]
                    + timedelta(days=season["rain_check_grace_days"]),
                    "redeemed_on_day_id": None,
                }
            )
            store.rain_checks[check["id"]] = check
            if ticket["order_id"] not in affected_orders:
                affected_orders.append(ticket["order_id"])
    # outstanding_admissions unchanged: each VALID ticket converts 1:1.
    for order_id in affected_orders:
        recompute_order_redemption(store.orders[order_id], "raincheck")

    # Second: SIGNED_UP/CONFIRMED shifts of the day -> CANCELLED.
    removed = Decimal(0)
    for shift in shifts_of_day(day["id"]):
        if shift["status"] in ("SIGNED_UP", "CONFIRMED"):
            if shift["status"] == "CONFIRMED":
                removed += dec(shift["hours"])
            mutate(shift, status="CANCELLED")
    adjust_volunteer_hours(season, -removed)

    # Third: readiness posture re-derived.
    rederive_posture(season)

    # Fourth: weather-rate cast payout for ACCEPTED/REHEARSING/PERFORMING.
    for contract in contracts_of_season(season["id"]):
        if contract["status"] in ("ACCEPTED", "REHEARSING", "PERFORMING"):
            mutate(
                contract,
                accrued_payout_cents=contract["accrued_payout_cents"]
                + weather_accrual_line(contract),
            )

    # Fifth: per-day booth weather credits for residencies covering the date.
    for booth in booths_of_season(season["id"]):
        if booth["status"] in ("RESERVED", "CONFIRMED", "SUSPENDED"):
            if booth["residency_start_date"] <= day["date"] < booth["residency_end_date"]:
                mutate(
                    booth,
                    weather_credit_cents=booth["weather_credit_cents"]
                    + weather_day_credit(booth),
                )


def complete_faire_day_cascade(day, season):
    mutate(day, status="COMPLETED")
    expired = 0
    for ticket in tickets_of_day(day["id"]):
        if ticket["ticket_type"] == "DAY" and ticket["status"] == "VALID":
            mutate(ticket, status="EXPIRED")
            expired += 1
    adjust_outstanding(season, -expired)
    for contract in contracts_of_season(season["id"]):
        if contract["status"] == "PERFORMING":
            mutate(
                contract,
                accrued_payout_cents=contract["accrued_payout_cents"]
                + contract["offered_day_rate_cents"],
            )


def season_open_cascade(season):
    for contract in contracts_of_season(season["id"]):
        if contract["status"] in ("ACCEPTED", "REHEARSING") and dec(
            contract["completed_rehearsal_hours"]
        ) >= dec(contract["required_rehearsal_hours"]):
            mutate(contract, status="PERFORMING")
    rederive_posture(season)


def season_strike_cascade(season):
    for contract in contracts_of_season(season["id"]):
        if contract["status"] in ("ACCEPTED", "REHEARSING", "PERFORMING"):
            mutate(
                contract,
                status="COMPLETED",
                final_payout_cents=cast_final_payout_completed(contract),
            )
    expired = 0
    for ticket in store.tickets.values():
        if ticket["ticket_type"] == "SEASON" and ticket["status"] == "VALID":
            order = store.orders.get(ticket["order_id"])
            if order is not None and order["season_id"] == season["id"]:
                mutate(ticket, status="EXPIRED")
                expired += 1
    adjust_outstanding(season, -expired)


def season_close_sweep(season):
    now = clock_now()
    expired = 0
    for check in rain_checks_of_season(season["id"]):
        if check["status"] == "ISSUED" and check["redeem_by_date"] < now:
            mutate(check, status="EXPIRED")
            expired += 1
    adjust_outstanding(season, -expired)


def terminate_contract_cascade(contract):
    mutate(
        contract,
        status="TERMINATED",
        final_payout_cents=contract["accrued_payout_cents"],
    )
    for slot in store.slots.values():
        if slot["contract_id"] == contract["id"] and slot["status"] == "SCHEDULED":
            mutate(slot, status="CANCELLED")


def revoke_permit_cascade(permit):
    """ISSUED -> REVOKED plus the booth-suspension and posture side effects."""
    mutate(permit, status="REVOKED")
    _suspend_booths_of_application(permit["application_id"])
    app = store.applications.get(permit["application_id"])
    if app is not None:
        season = store.seasons.get(app["season_id"])
        if season is not None:
            rederive_posture(season)


def promote_waitlist(season):
    """waitlist_promotion: jury_score DESC (nulls last), created_at ASC tie-break."""
    candidates = [
        a for a in applications_of_season(season["id"]) if a["status"] == "WAITLISTED"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda a: (a["jury_score"] is None, -(a["jury_score"] or 0), a["_seq"])
    )
    top = candidates[0]
    mutate(top, status="JURIED_IN")
    rederive_posture(season)
    return top


def ban_guest_cascade(order, season):
    voided = 0
    for ticket in tickets_of_order(order["id"]):
        if ticket["status"] == "VALID":
            mutate(ticket, status="VOID")
            voided += 1
    adjust_outstanding(season, -voided)
    if order["redemption_status"] in ("UNREDEEMED", "PARTIALLY_REDEEMED"):
        mutate(order, redemption_status="VOID")


def mint_tickets(order, count, faire_day_id, ticket_type):
    out = []
    for _ in range(count):
        ticket = new_record()
        ticket.update(
            {
                "id": new_id(),
                "_seq": next_seq(),
                "order_id": order["id"],
                "faire_day_id": faire_day_id,
                "ticket_type": ticket_type,
                "status": "VALID",
                "redeemed_at": None,
            }
        )
        store.tickets[ticket["id"]] = ticket
        out.append(ticket)
    return out


def task_reaches(start_id, target_id):
    """Can start_id reach target_id following depends_on_task_ids edges?"""
    seen = set()
    stack = [start_id]
    while stack:
        cur = stack.pop()
        if cur == target_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        task = store.tasks.get(cur)
        if task is not None:
            stack.extend(task["depends_on_task_ids"])
    return False
