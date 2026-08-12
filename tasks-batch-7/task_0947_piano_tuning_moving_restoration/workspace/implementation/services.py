"""Shared domain services: the ledger, the climate re-evaluation, route-day
recomputation, warranty voiding and the three cascade chains (PRD 2.10-2.12)."""

import calc
from core import (
    CLOCK, DB, add_days, by_created, date_str, days_between, make_append_row,
    parse_date, parse_iso, touch,
)


# ---------------------------------------------------------------------------
# Ledger (PRD 2.12)
# ---------------------------------------------------------------------------

def post_ledger(client_id, entry_type, amount_cents, memo=None,
                service_order_id=None, warranty_claim_id=None,
                consignment_agreement_id=None, reverses_entry_id=None):
    row = make_append_row(
        client_id=client_id,
        service_order_id=service_order_id,
        warranty_claim_id=warranty_claim_id,
        consignment_agreement_id=consignment_agreement_id,
        reverses_entry_id=reverses_entry_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
        memo=memo,
        posted_at_utc=CLOCK.stamp(),
    )
    DB.ledger_entries[row["id"]] = row
    return row


def recompute_balance(client_row, bump=False):
    """PRD 2.10 'Client money': the plain sum over EVERY row of the client."""
    if client_row is None:
        return
    total = sum(e["amount_cents"] for e in DB.ledger_entries.values()
                if e["client_id"] == client_row["id"])
    client_row["account_credit_cents"] = total
    if bump:
        touch(client_row)


def recompute_balance_for(client_id, bump=False):
    recompute_balance(DB.clients.get(client_id), bump=bump)


# ---------------------------------------------------------------------------
# Climate (PRD 3.1)
# ---------------------------------------------------------------------------

def evaluate_location(location, bump=False):
    window_start = CLOCK.dt - _days(calc.CLIMATE_LOOKBACK_WINDOW_DAYS)
    rhs = []
    for reading in DB.climate_readings.values():
        if reading["location_id"] != location["id"]:
            continue
        recorded = parse_iso(reading["recorded_at_utc"])
        if recorded is None:
            continue
        if window_start <= recorded <= CLOCK.dt:
            rhs.append(reading["relative_humidity_pct"])
    n, out_count, flag = calc.climate_evaluation(rhs)
    location["readings_in_window"] = n
    location["out_of_band_count"] = out_count
    location["out_of_band_flag"] = flag
    if bump:
        touch(location)


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)


def reevaluate_all_locations():
    """Clock-set re-run: every location holding at least one reading."""
    with_readings = set(r["location_id"] for r in DB.climate_readings.values())
    count = 0
    for loc in by_created(list(DB.locations.values())):
        if loc["id"] in with_readings:
            evaluate_location(loc)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Route day minutes (PRD 2.10 'Route minutes')
# ---------------------------------------------------------------------------

def recompute_route_day(route_day):
    if route_day is None:
        return
    stops = [a for a in DB.appointments.values()
             if a["route_day_id"] == route_day["id"]
             and a["scheduling_status"] in ("SCHEDULED", "CONFIRMED")]
    route_day["committed_minutes"] = sum(a["total_block_minutes"] for a in stops)
    route_day["stop_count"] = len(stops)
    touch(route_day)


# ---------------------------------------------------------------------------
# Recall helpers (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------

def governing_recall(instrument_id):
    """PRD 3.3 selector: eligible recalls ranked created_at DESC, then
    due_date DESC, then days_overdue DESC."""
    cands = [r for r in DB.tuning_recalls.values()
             if r["instrument_id"] == instrument_id
             and r["status"] in ("PENDING", "NOTIFIED", "SCHEDULED")]
    if not cands:
        return None
    cands.sort(key=lambda r: (r["created_at"], r["due_date"] or "",
                              r["days_overdue"] or 0), reverse=True)
    return cands[0]


# ---------------------------------------------------------------------------
# Warranty voiding and claim denial -- CASCADE A hops 3..5 (PRD 2.11)
# ---------------------------------------------------------------------------

def provisional_credit_entry(claim_id):
    rows = [e for e in DB.ledger_entries.values()
            if e["entry_type"] == "WARRANTY_CREDIT"
            and e["warranty_claim_id"] == claim_id]
    if not rows:
        return None
    return by_created(rows)[0]


def deny_claim(claim):
    """Hops 3..5: DENY the claim, reverse its provisional credit, recompute."""
    claim["status"] = "DENIED"
    touch(claim)
    original = provisional_credit_entry(claim["id"])
    if original is None:
        # FREE_RESERVICE claims never carried a provisional credit: hops 4 and 5
        # are skipped.
        return
    warranty = DB.warranties.get(claim["warranty_id"])
    client_id = original["client_id"]
    post_ledger(client_id, "REVERSAL", -original["amount_cents"],
                warranty_claim_id=claim["id"],
                reverses_entry_id=original["id"])
    recompute_balance_for(client_id, bump=True)
    return warranty


def void_warranty(warranty, reason):
    """Every void -- manual, cascade A, the lapse sweep or the climate gate --
    denies the warranty's open claims (PRD 3.9)."""
    warranty["status"] = "VOIDED"
    warranty["void_reason"] = reason
    touch(warranty)
    open_claims = [c for c in DB.warranty_claims.values()
                   if c["warranty_id"] == warranty["id"]
                   and c["status"] in ("SUBMITTED", "UNDER_REVIEW")]
    for claim in by_created(open_claims):
        deny_claim(claim)


# ---------------------------------------------------------------------------
# CASCADE A -- the unauthorised move
# ---------------------------------------------------------------------------

def cascade_a(instrument):
    targets = [w for w in DB.warranties.values()
               if w["instrument_id"] == instrument["id"]
               and w["status"] in ("ACTIVE", "TRANSFERRED")]
    for warranty in by_created(targets):
        void_warranty(warranty, "UNAUTHORIZED_MOVE")


# ---------------------------------------------------------------------------
# CASCADE B -- the rebuild supersession
# ---------------------------------------------------------------------------

def cascade_b(instrument_id):
    orders = [o for o in DB.service_orders.values()
              if o["instrument_id"] == instrument_id
              and o["service_type"] in ("TUNE", "PITCH_RAISE", "REGULATE", "VOICE")
              and o["status"] in ("PENDING", "IN_PROGRESS", "ON_HOLD")]
    for order in by_created(orders):
        order["status"] = "VOIDED_BY_REBUILD"
        touch(order)
        cancelled_any = _cancel_order_children(order)
        if cancelled_any:
            refund = order["deposit_held_cents"] - order["deposit_applied_cents"]
            order["deposit_refunded_cents"] = refund
            post_ledger(order["client_id"], "DEPOSIT_REFUND", refund,
                        service_order_id=order["id"])
            recompute_balance_for(order["client_id"], bump=True)


def _cancel_order_children(order):
    """Milestones PENDING/READY/RELEASED -> CANCELLED (sequence_index ASC);
    allocations RESERVED/PARTIAL -> RELEASED.  Returns True when at least one
    milestone was cancellable."""
    stones = [m for m in DB.milestones.values()
              if m["service_order_id"] == order["id"]
              and m["status"] in ("PENDING", "READY", "RELEASED")]
    stones.sort(key=lambda m: m["sequence_index"])
    for stone in stones:
        stone["status"] = "CANCELLED"
        touch(stone)
    for alloc in by_created([a for a in DB.parts_allocations.values()
                             if a["service_order_id"] == order["id"]
                             and a["status"] in ("RESERVED", "PARTIAL")]):
        release_allocation(alloc)
    return bool(stones)


# ---------------------------------------------------------------------------
# CASCADE C -- the consignment sale
# ---------------------------------------------------------------------------

def cascade_c(instrument, buyer_client_id, consignor_client_id, sale_date):
    instrument["custody_status"] = "SOLD"
    instrument["client_id"] = buyer_client_id
    touch(instrument)
    warranties = [w for w in DB.warranties.values()
                  if w["instrument_id"] == instrument["id"]
                  and w["status"] == "ACTIVE"]
    for warranty in by_created(warranties):
        start = parse_date(warranty["start_date"])
        new_term = calc.warranty_transfer_term(warranty["term_days"], start,
                                               sale_date)
        warranty["status"] = "TRANSFERRED"
        warranty["transferred_from_client_id"] = consignor_client_id
        warranty["client_id"] = buyer_client_id
        warranty["term_days"] = new_term
        warranty["start_date"] = date_str(sale_date)
        warranty["end_date"] = date_str(add_days(sale_date, new_term))
        touch(warranty)
    orders = [o for o in DB.service_orders.values()
              if o["instrument_id"] == instrument["id"]
              and o["status"] in ("PENDING", "IN_PROGRESS", "ON_HOLD")]
    for order in by_created(orders):
        order["client_id"] = buyer_client_id
        touch(order)


# ---------------------------------------------------------------------------
# Parts allocation movements
# ---------------------------------------------------------------------------

def consume_allocation(alloc):
    lot = DB.parts_lots.get(alloc["parts_lot_id"])
    alloc["status"] = "CONSUMED"
    touch(alloc)
    if lot is not None:
        lot["allocated_qty"] -= alloc["allocated_qty"]
        lot["consumed_qty"] += alloc["allocated_qty"]
        if lot["on_hand_qty"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)


def release_allocation(alloc):
    lot = DB.parts_lots.get(alloc["parts_lot_id"])
    alloc["status"] = "RELEASED"
    touch(alloc)
    if lot is not None:
        lot["allocated_qty"] -= alloc["allocated_qty"]
        lot["on_hand_qty"] += alloc["allocated_qty"]
        if lot["on_hand_qty"] > 0:
            lot["status"] = "OPEN"
        touch(lot)


# ---------------------------------------------------------------------------
# Service-order completion side effects (PRD 3.2, 3.6, 3.9)
# ---------------------------------------------------------------------------

def mint_warranty(order):
    from core import make_row
    term = calc.warranty_term(order["service_type"])
    start = CLOCK.date
    row = make_row(
        service_order_id=order["id"],
        instrument_id=order["instrument_id"],
        client_id=order["client_id"],
        service_type=order["service_type"],
        term_days=term,
        start_date=date_str(start),
        end_date=date_str(add_days(start, term)),
        covered_price_cents=order["contract_total_cents"],
        claim_count=0,
        transferred_from_client_id=None,
        void_reason=None,
        status="ACTIVE",
    )
    DB.warranties[row["id"]] = row
    return row


def advance_condition_on_complete(order, instrument):
    service = order["service_type"]
    current = instrument["condition_status"]
    if service == "REGULATE" and current == "NEEDS_REGULATION":
        instrument["condition_status"] = "NEEDS_VOICING"
        touch(instrument)
    elif service == "VOICE" and current == "NEEDS_VOICING":
        instrument["condition_status"] = "SERVICEABLE"
        touch(instrument)
    elif service == "REBUILD" and current == "REBUILD_REQUIRED" \
            and instrument["custody_status"] == "IN_SHOP":
        instrument["condition_status"] = "RESTORED"
        touch(instrument)


# ---------------------------------------------------------------------------
# The daily operations sweep (PRD 3.4)
# ---------------------------------------------------------------------------

def daily_sweep():
    counts = {
        "evaluated_recall_count": 0,
        "lapsed_recall_count": 0,
        "expired_quote_count": 0,
        "expired_consignment_count": 0,
        "expired_warranty_count": 0,
        "voided_warranty_count": 0,
    }

    # -- step 1 ---------------------------------------------------------
    recalls = [r for r in DB.tuning_recalls.values()
               if r["status"] in ("PENDING", "NOTIFIED", "SCHEDULED")]
    for recall in by_created(recalls):
        due = parse_date(recall["due_date"])
        overdue = calc.days_overdue_for(CLOCK.date, due)
        recall["days_overdue"] = overdue
        recall["overdue_tier"] = calc.overdue_tier_for(overdue)
        counts["evaluated_recall_count"] += 1
        if recall["status"] in ("PENDING", "NOTIFIED") \
                and overdue >= calc.LAPSE_MIN_DAYS:
            recall["status"] = "LAPSED"
            recall["overdue_tier"] = "LAPSED_TIER"
            touch(recall)
            counts["lapsed_recall_count"] += 1
            targets = [w for w in DB.warranties.values()
                       if w["instrument_id"] == recall["instrument_id"]
                       and w["status"] == "ACTIVE"]
            for warranty in by_created(targets):
                void_warranty(warranty, "TUNING_CYCLE_LAPSED")
                counts["voided_warranty_count"] += 1

    # -- step 2 ---------------------------------------------------------
    for quote in by_created([q for q in DB.quotes.values()
                             if q["status"] == "ISSUED"]):
        expires = parse_iso(quote["expires_at"]) if quote["expires_at"] else None
        if expires is not None and CLOCK.dt >= expires:
            quote["status"] = "EXPIRED"
            touch(quote)
            counts["expired_quote_count"] += 1

    # -- step 3 ---------------------------------------------------------
    for agreement in by_created([a for a in DB.consignment_agreements.values()
                                 if a["status"] in ("ACTIVE", "LISTED")]):
        expires = parse_iso(agreement["expires_at"]) if agreement["expires_at"] else None
        if expires is not None and CLOCK.dt >= expires:
            agreement["status"] = "EXPIRED"
            touch(agreement)
            counts["expired_consignment_count"] += 1
            detach_instrument(agreement)

    # -- step 4 ---------------------------------------------------------
    for warranty in by_created([w for w in DB.warranties.values()
                                if w["status"] in ("ACTIVE", "TRANSFERRED")]):
        end = parse_date(warranty["end_date"])
        if end is not None and CLOCK.date > end:
            warranty["status"] = "EXPIRED"
            touch(warranty)
            counts["expired_warranty_count"] += 1

    return counts


def detach_instrument(agreement):
    """Withdrawal / expiry: clear the link and bring the piano off the floor."""
    instrument = DB.instruments.get(agreement["instrument_id"])
    if instrument is None:
        return
    changed = False
    if instrument.get("consignment_agreement_id") == agreement["id"]:
        instrument["consignment_agreement_id"] = None
        changed = True
    if instrument["custody_status"] == "SHOWROOM_FLOOR":
        instrument["custody_status"] = "AT_CLIENT_SITE"
        changed = True
    if changed:
        touch(instrument)


# ---------------------------------------------------------------------------
# Small shared predicates
# ---------------------------------------------------------------------------

def order_unapplied_deposit(order):
    """PRD 3.6 / rung 60: held less applied less refunded less forfeited."""
    return (order["deposit_held_cents"] - order["deposit_applied_cents"]
            - order["deposit_refunded_cents"] - order["deposit_forfeited_cents"])


def lead_hours_from_clock(start_dt):
    from core import D
    delta = start_dt - CLOCK.dt
    return D(delta.total_seconds()) / D(3600)
