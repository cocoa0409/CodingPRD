"""Business logic: serializers, derived fields, calculations, side effects.

Every formula traces to SCAFFOLD.yaml Table 3 / PRD.md section 3:
- spot_unit_rate (ratings tier x dow factor x demand tier, round-half-up once)
- trade_valuation / trade_available_balance (ledger replay)
- affidavit_billing_total (per-line rounding THEN sum)
- hour_spot_capacity (SPOT_BREAK pool units+seconds; LIVE_READ_WINDOW units)
- spin_compliance (song sep -> artist sep -> spin cap)
- ratings_lookup / clock_pin_selection / preemption_selector
- endorsement_contracted_total / event_delivery_evaluation
"""
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP

import store
from helpers import DAYPART_HOURS, err, weekday_of

AGENCY_COMMISSION_PCT = Decimal("0.15")


# ---------------------------------------------------------------------------
# Generic entity helpers
# ---------------------------------------------------------------------------
def stamp_new(rec):
    ts = store.now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """One mutation: refresh updated_at and increment version by 1."""
    rec["updated_at"] = store.now_iso()
    rec["version"] += 1


def find(table, entity_id):
    rec = table.get(entity_id)
    if rec is None:
        err("ERR_NOT_FOUND", f"Resource {entity_id} does not exist")
    return rec


# ---------------------------------------------------------------------------
# Derived counters (computed on read; per-entity version bumps stay explicit)
# ---------------------------------------------------------------------------
def ledger_entries_of(agreement_id):
    return sorted(
        (e for e in store.trade_ledger_entries.values()
         if e["agreement_id"] == agreement_id),
        key=lambda e: e["entry_seq"])


def trade_totals(agreement):
    entries = ledger_entries_of(agreement["id"])
    consumed = sum(e["amount_cents"] for e in entries
                   if e["entry_kind"] == "DEBIT")
    consumed -= sum(e["amount_cents"] for e in entries
                    if e["entry_kind"] == "REVERSAL")
    adjustments = sum(e["amount_cents"] for e in entries
                      if e["entry_kind"] == "ADJUSTMENT")
    available = agreement["credit_limit_cents"] - consumed + adjustments
    return consumed, adjustments, available


def order_units(order):
    mine = [s for s in store.spots.values() if s["order_id"] == order["id"]]
    scheduled = sum(1 for s in mine
                    if s["status"] in ("SCHEDULED", "AIRED")
                    and s["makeup_of_spot_id"] is None)
    aired = sum(1 for s in mine if s["status"] == "AIRED")
    return scheduled, aired


def log_unresolved_count(log):
    return sum(1 for d in store.discrepancies.values()
               if d["log_id"] == log["id"] and d["status"] == "UNRESOLVED")


def contract_reads_completed(contract):
    return sum(1 for r in store.live_reads.values()
               if r["contract_id"] == contract["id"] and r["status"] == "AIRED")


def event_spots_delivered(event):
    return sum(1 for s in store.spots.values()
               if s["event_id"] == event["id"] and s["status"] == "AIRED"
               and s["air_date"] == event["event_date"])


# ---------------------------------------------------------------------------
# Serializers (derived fields computed fresh on every read)
# ---------------------------------------------------------------------------
def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_station(r):
    out = _base(r)
    out.update({"call_sign": r["call_sign"], "market_name": r["market_name"],
                "default_share_fallback": r["default_share_fallback"]})
    return out


def ser_clock(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "name": r["name"],
                "applies_weekdays": list(r["applies_weekdays"]),
                "slots": [dict(s) for s in r["slots"]], "status": r["status"]})
    return out


def ser_category(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "code": r["code"],
                "min_song_separation_min": r["min_song_separation_min"],
                "min_artist_separation_min": r["min_artist_separation_min"],
                "max_spins_per_day": r["max_spins_per_day"],
                "status": r["status"]})
    return out


def ser_song(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "category_id": r["category_id"],
                "title": r["title"], "artist": r["artist"],
                "duration_sec": r["duration_sec"], "status": r["status"]})
    return out


def ser_ratings_book(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "survey_name": r["survey_name"],
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "share_value": r["share_value"], "status": r["status"]})
    return out


def ser_rate_card(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "daypart": r["daypart"],
                "weekday_set": list(r["weekday_set"]),
                "base_rate_cents": r["base_rate_cents"],
                "min_rate_cents": r["min_rate_cents"],
                "effective_from": r["effective_from"],
                "effective_to": r["effective_to"], "status": r["status"]})
    return out


def ser_clearance(r):
    out = _base(r)
    out.update({"station_id": r["station_id"],
                "program_name": r["program_name"], "provider": r["provider"],
                "weekday_set": list(r["weekday_set"]),
                "start_hour": r["start_hour"],
                "duration_hours": r["duration_hours"],
                "barter_avails_per_hour": r["barter_avails_per_hour"],
                "effective_from": r["effective_from"],
                "effective_to": r["effective_to"], "status": r["status"]})
    return out


def ser_agreement(r):
    out = _base(r)
    consumed, adjustments, available = trade_totals(r)
    out.update({"station_id": r["station_id"], "vendor_name": r["vendor_name"],
                "credit_limit_cents": r["credit_limit_cents"],
                "trade_ratio": r["trade_ratio"],
                "consumed_cents": consumed,
                "adjustments_cents": adjustments,
                "available_cents": available, "status": r["status"]})
    return out


def ser_ledger_entry(r):
    # TradeLedgerEntry is append-only: id + created_at only, no updated_at /
    # version.
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "agreement_id": r["agreement_id"],
        "entry_kind": r["entry_kind"],
        "amount_cents": r["amount_cents"],
        "spot_id": r["spot_id"],
        "note": r["note"],
        "entry_seq": r["entry_seq"],
    }


def ser_order(r):
    out = _base(r)
    scheduled, aired = order_units(r)
    out.update({"station_id": r["station_id"],
                "advertiser_name": r["advertiser_name"],
                "order_kind": r["order_kind"],
                "trade_agreement_id": r["trade_agreement_id"],
                "created_by_user_id": r["created_by_user_id"],
                "flight_start": r["flight_start"],
                "flight_end": r["flight_end"],
                "rate_tier": r["rate_tier"],
                "reprice_policy": r["reprice_policy"],
                "daypart_targets": [dict(t) for t in r["daypart_targets"]],
                "units_scheduled": scheduled, "units_aired": aired,
                "status": r["status"]})
    return out


def ser_log(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "log_date": r["log_date"],
                "clock_id": r["clock_id"], "clock_version": r["clock_version"],
                "posture": r["posture"],
                "reconciled_by_user_id": r["reconciled_by_user_id"],
                "affidavit_issued_by_user_id": r["affidavit_issued_by_user_id"],
                "unresolved_discrepancy_count": log_unresolved_count(r),
                "affidavit_total_cents": r["affidavit_total_cents"],
                "music_placements": [dict(p) for p in r["music_placements"]]})
    return out


def ser_spot(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "order_id": r["order_id"],
                "log_id": r["log_id"], "event_id": r["event_id"],
                "air_date": r["air_date"], "daypart": r["daypart"],
                "hour": r["hour"], "duration_sec": r["duration_sec"],
                "unit_rate_cents": r["unit_rate_cents"],
                "billed_rate_cents": r["billed_rate_cents"],
                "cash_equivalent_cents": r["cash_equivalent_cents"],
                "makeup_of_spot_id": r["makeup_of_spot_id"],
                "make_good_reason": r["make_good_reason"],
                "status": r["status"]})
    return out


def ser_barter_avail(r):
    out = _base(r)
    out.update({"station_id": r["station_id"],
                "clearance_id": r["clearance_id"], "log_id": r["log_id"],
                "air_date": r["air_date"], "hour": r["hour"],
                "duration_sec": r["duration_sec"], "status": r["status"]})
    return out


def ser_contract(r):
    out = _base(r)
    out.update({"station_id": r["station_id"],
                "advertiser_name": r["advertiser_name"],
                "host_name": r["host_name"],
                "program_weekdays": list(r["program_weekdays"]),
                "program_start_hour": r["program_start_hour"],
                "program_end_hour": r["program_end_hour"],
                "reads_per_week": r["reads_per_week"],
                "start_date": r["start_date"], "end_date": r["end_date"],
                "contracted_reads_total": r["contracted_reads_total"],
                "reads_completed": contract_reads_completed(r),
                "status": r["status"]})
    return out


def ser_live_read(r):
    out = _base(r)
    out.update({"station_id": r["station_id"],
                "contract_id": r["contract_id"], "log_id": r["log_id"],
                "air_date": r["air_date"], "hour": r["hour"],
                "duration_sec": r["duration_sec"],
                "makeup_of_live_read_id": r["makeup_of_live_read_id"],
                "status": r["status"]})
    return out


def ser_discrepancy(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "log_id": r["log_id"],
                "spot_id": r["spot_id"], "live_read_id": r["live_read_id"],
                "barter_avail_id": r["barter_avail_id"],
                "discrepancy_kind": r["discrepancy_kind"],
                "status": r["status"],
                "resolution_note": r["resolution_note"],
                "resolved_by_user_id": r["resolved_by_user_id"]})
    return out


def ser_remote_event(r):
    out = _base(r)
    out.update({"station_id": r["station_id"], "event_name": r["event_name"],
                "sponsor_name": r["sponsor_name"],
                "event_date": r["event_date"],
                "spot_units_promised": r["spot_units_promised"],
                "package_price_cents": r["package_price_cents"],
                "spots_delivered": event_spots_delivered(r),
                "status": r["status"]})
    return out


# ---------------------------------------------------------------------------
# Trade ledger appends + balance recompute + ACTIVE<->EXHAUSTED auto-flip
# ---------------------------------------------------------------------------
def append_ledger(agreement, kind, amount_cents, spot_id=None, note=None):
    seq = len(ledger_entries_of(agreement["id"])) + 1
    entry = {
        "id": store.new_id(),
        "created_at": store.now_iso(),
        "agreement_id": agreement["id"],
        "entry_kind": kind,
        "amount_cents": amount_cents,
        "spot_id": spot_id,
        "note": note,
        "entry_seq": seq,
        "_seq": store.next_seq(),
    }
    store.trade_ledger_entries[entry["id"]] = entry
    # Recompute + auto-transition, then one version bump per append.
    _, _, available = trade_totals(agreement)
    if agreement["status"] == "ACTIVE" and available == 0:
        agreement["status"] = "EXHAUSTED"
    elif agreement["status"] == "EXHAUSTED" and available > 0:
        agreement["status"] = "ACTIVE"
    touch(agreement)
    return entry


def spot_outstanding_debit(spot):
    """Original DEBIT minus any REVERSALs already posted for this spot."""
    debit = sum(e["amount_cents"] for e in store.trade_ledger_entries.values()
                if e["spot_id"] == spot["id"] and e["entry_kind"] == "DEBIT")
    reversal = sum(e["amount_cents"]
                   for e in store.trade_ledger_entries.values()
                   if e["spot_id"] == spot["id"]
                   and e["entry_kind"] == "REVERSAL")
    return debit - reversal


def post_trade_reversal(spot):
    """Append a REVERSAL equal to the spot's outstanding DEBIT, if any."""
    order = store.orders.get(spot["order_id"])
    if not order or order["order_kind"] != "TRADE":
        return
    outstanding = spot_outstanding_debit(spot)
    if outstanding <= 0:
        return
    agreement = store.trade_agreements.get(order["trade_agreement_id"])
    if agreement is None:
        return
    append_ledger(agreement, "REVERSAL", outstanding, spot_id=spot["id"])


# ---------------------------------------------------------------------------
# Ratings lookup + spot unit rate
# ---------------------------------------------------------------------------
def ratings_lookup(station, air_date):
    """Share of the PUBLISHED book covering air_date; else station fallback."""
    d = _date.fromisoformat(air_date) if isinstance(air_date, str) else air_date
    for book in store.ratings_books.values():
        if (book["station_id"] == station["id"]
                and book["status"] == "PUBLISHED"
                and book["period_start"] <= d.isoformat()
                and d.isoformat() <= book["period_end"]):
            return Decimal(str(book["share_value"]))
    return Decimal(str(station["default_share_fallback"]))


def find_rate_card(station_id, daypart, air_date):
    wd = weekday_of(_date.fromisoformat(air_date))
    candidates = [
        r for r in store.rate_card_entries.values()
        if r["station_id"] == station_id and r["status"] == "ACTIVE"
        and r["daypart"] == daypart and wd in r["weekday_set"]
        and r["effective_from"] <= air_date <= r["effective_to"]]
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return candidates[0] if candidates else None


def _ratings_multiplier(share):
    if share < Decimal("2.0"):
        return Decimal("0.80")
    if share < Decimal("4.0"):
        return Decimal("1.00")
    if share < Decimal("6.0"):
        return Decimal("1.25")
    return Decimal("1.50")


def demand_utilization(log, daypart):
    """u = scheduled_units(L, D) / capacity_units(L, D) over the daypart's
    hours, counting Spot+BarterAvail in SCHEDULED|AIRED; capacity from the
    pinned clock's SPOT_BREAK slots. No pinned clock (DRAFT log) -> u = 0."""
    if not log["clock_id"]:
        return Decimal("0")
    clock = store.clocks.get(log["clock_id"])
    if clock is None:
        return Decimal("0")
    hours = DAYPART_HOURS[daypart]
    cap = sum(s["capacity_units"] for s in clock["slots"]
              if s["slot_type"] == "SPOT_BREAK" and s["hour"] in hours)
    if cap <= 0:
        return Decimal("0")
    used = sum(1 for s in store.spots.values()
               if s["log_id"] == log["id"] and s["hour"] in hours
               and s["status"] in ("SCHEDULED", "AIRED"))
    used += sum(1 for a in store.barter_avails.values()
                if a["log_id"] == log["id"] and a["hour"] in hours
                and a["status"] in ("SCHEDULED", "AIRED"))
    return Decimal(used) / Decimal(cap)


def _demand_multiplier(u):
    if u < Decimal("0.70"):
        return Decimal("1.00")
    if u < Decimal("0.85"):
        return Decimal("1.15")
    return Decimal("1.30")


def compute_unit_rate(station, log, daypart, air_date, rate_card=None):
    """spot_unit_rate: base x ratings x dow x demand, round-half-up once,
    floored at min_rate_cents. Raises ERR_NO_RATE_CARD when no entry matches.
    Returns (unit_rate_cents, rate_card_entry)."""
    if rate_card is None:
        rate_card = find_rate_card(station["id"], daypart, air_date)
    if rate_card is None:
        err("ERR_NO_RATE_CARD",
            "No ACTIVE RateCardEntry matches (station, daypart, weekday, "
            "air_date)")
    share = ratings_lookup(station, air_date)
    m_r = _ratings_multiplier(share)
    wd = weekday_of(_date.fromisoformat(air_date))
    m_d = Decimal("0.85") if wd in ("SAT", "SUN") else Decimal("1.00")
    m_u = _demand_multiplier(demand_utilization(log, daypart))
    raw = (Decimal(rate_card["base_rate_cents"]) * m_r * m_d * m_u)
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(rate_card["min_rate_cents"], rounded), rate_card


def trade_value_of(cash_equivalent_cents, trade_ratio):
    raw = Decimal(cash_equivalent_cents) * Decimal(str(trade_ratio))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Hour pools (SPOT_BREAK units+seconds; LIVE_READ_WINDOW units only)
# ---------------------------------------------------------------------------
def spot_pool(log, hour):
    """None when the log has no pinned clock (unlimited). Else
    (cap_units, cap_seconds, occ_units, occ_seconds)."""
    if not log["clock_id"]:
        return None
    clock = store.clocks.get(log["clock_id"])
    if clock is None:
        return None
    cap_units = sum(s["capacity_units"] for s in clock["slots"]
                    if s["slot_type"] == "SPOT_BREAK" and s["hour"] == hour)
    cap_seconds = sum(s["capacity_seconds"] for s in clock["slots"]
                      if s["slot_type"] == "SPOT_BREAK" and s["hour"] == hour)
    occ_units = 0
    occ_seconds = 0
    for s in store.spots.values():
        if (s["log_id"] == log["id"] and s["hour"] == hour
                and s["status"] in ("SCHEDULED", "AIRED")):
            occ_units += 1
            occ_seconds += s["duration_sec"]
    for a in store.barter_avails.values():
        if (a["log_id"] == log["id"] and a["hour"] == hour
                and a["status"] in ("SCHEDULED", "AIRED")):
            occ_units += 1
            occ_seconds += a["duration_sec"]
    return cap_units, cap_seconds, occ_units, occ_seconds


def live_read_pool(log, hour):
    if not log["clock_id"]:
        return None
    clock = store.clocks.get(log["clock_id"])
    if clock is None:
        return None
    cap_units = sum(s["capacity_units"] for s in clock["slots"]
                    if s["slot_type"] == "LIVE_READ_WINDOW"
                    and s["hour"] == hour)
    occ = sum(1 for r in store.live_reads.values()
              if r["log_id"] == log["id"] and r["hour"] == hour
              and r["status"] in ("SCHEDULED", "AIRED"))
    return cap_units, occ


def spot_fits(log, hour, duration_sec):
    pool = spot_pool(log, hour)
    if pool is None:
        return True
    cap_units, cap_seconds, occ_units, occ_seconds = pool
    return (occ_units + 1 <= cap_units
            and occ_seconds + duration_sec <= cap_seconds)


def live_read_fits(log, hour):
    pool = live_read_pool(log, hour)
    if pool is None:
        return True
    cap_units, occ = pool
    return occ + 1 <= cap_units


def select_preemption_victims(log, hour, duration_sec):
    """preemption_selector: PREEMPTIBLE SCHEDULED spots at (log, hour),
    ranked unit_rate_cents ASC then created_at ASC; minimum prefix whose
    removal fits the new unit. Returns victim list, or None when even the
    full pool is insufficient (caller raises ERR_HOUR_CAPACITY_EXCEEDED and
    commits nothing)."""
    pool = spot_pool(log, hour)
    if pool is None:
        return []
    cap_units, cap_seconds, occ_units, occ_seconds = pool
    victims = [
        s for s in store.spots.values()
        if s["log_id"] == log["id"] and s["hour"] == hour
        and s["status"] == "SCHEDULED"
        and store.orders[s["order_id"]]["rate_tier"] == "PREEMPTIBLE"]
    victims.sort(key=lambda s: (s["unit_rate_cents"], s["created_at"],
                                s["_seq"]))
    chosen = []
    freed_units = 0
    freed_seconds = 0
    for v in victims:
        if (occ_units - freed_units + 1 <= cap_units
                and occ_seconds - freed_seconds + duration_sec
                <= cap_seconds):
            break
        chosen.append(v)
        freed_units += 1
        freed_seconds += v["duration_sec"]
    if not (occ_units - freed_units + 1 <= cap_units
            and occ_seconds - freed_seconds + duration_sec <= cap_seconds):
        return None
    return chosen


# ---------------------------------------------------------------------------
# Make-good / discrepancy helpers
# ---------------------------------------------------------------------------
def create_discrepancy(log, kind, spot_id=None, live_read_id=None,
                       barter_avail_id=None):
    rec = {
        "id": store.new_id(),
        "station_id": log["station_id"],
        "log_id": log["id"],
        "spot_id": spot_id,
        "live_read_id": live_read_id,
        "barter_avail_id": barter_avail_id,
        "discrepancy_kind": kind,
        "status": "UNRESOLVED",
        "resolution_note": None,
        "resolved_by_user_id": None,
    }
    stamp_new(rec)
    store.discrepancies[rec["id"]] = rec
    return rec


def auto_resolve_linked_discrepancy(kind, fk_field, fk_value):
    """System cascade: linked MISSED_SPOT / MISSED_READ discrepancy flips
    UNRESOLVED -> RESOLVED with the system recorded as resolver."""
    for d in store.discrepancies.values():
        if (d["discrepancy_kind"] == kind and d[fk_field] == fk_value
                and d["status"] == "UNRESOLVED"):
            d["status"] = "RESOLVED"
            d["resolved_by_user_id"] = "system"
            touch(d)
            log = store.logs.get(d["log_id"])
            if log is not None:
                touch(log)  # unresolved_discrepancy_count recomputed
            return d
    return None
