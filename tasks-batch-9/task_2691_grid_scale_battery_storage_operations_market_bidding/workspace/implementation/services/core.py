"""Shared lookups, derived-field recomputes, gates and cascades."""

from decimal import Decimal

import db
import errors
from errors import ApiError
from numeric import D, rnd, f, r2, r3, r4
from services import calc

# ---------------------------------------------------------------------------
# Existence (PRD 2.6 steps 4 and 5)
# ---------------------------------------------------------------------------
def _find(collection, row_id, error_id, label):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, 404, "%s not found." % label)
    return row


def get_asset(asset_id):
    return _find(db.assets, asset_id, errors.ERR_ASSET_NOT_FOUND, "Storage asset")


def get_reservation(reservation_id):
    return _find(db.reservations, reservation_id,
                 errors.ERR_RESERVATION_NOT_FOUND, "Reservation")


def get_bid(bid_id):
    return _find(db.bids, bid_id, errors.ERR_BID_NOT_FOUND, "Market offer")


def get_dispatch(dispatch_id):
    return _find(db.dispatches, dispatch_id, errors.ERR_DISPATCH_NOT_FOUND,
                 "Dispatch instruction")


def get_event(event_id):
    return _find(db.safety_events, event_id, errors.ERR_SAFETY_EVENT_NOT_FOUND,
                 "Safety event")


def get_obligation(obligation_id):
    return _find(db.obligations, obligation_id, errors.ERR_OBLIGATION_NOT_FOUND,
                 "Capacity obligation")


def get_test(test_id):
    return _find(db.capacity_tests, test_id, errors.ERR_TEST_NOT_FOUND,
                 "Capacity test")


def get_claim(claim_id):
    return _find(db.warranty_claims, claim_id, errors.ERR_CLAIM_NOT_FOUND,
                 "Warranty claim")


# ---------------------------------------------------------------------------
# Child collections
# ---------------------------------------------------------------------------
def reservations_of(asset_id):
    return [r for r in db.reservations.values() if r["asset_id"] == asset_id]


def bids_of_asset(asset_id):
    return [b for b in db.bids.values() if b["asset_id"] == asset_id]


def bids_of_reservation(reservation_id):
    return [b for b in db.bids.values() if b["reservation_id"] == reservation_id]


def dispatches_of_asset(asset_id):
    return [d for d in db.dispatches.values() if d["asset_id"] == asset_id]


def dispatches_of_bid(bid_id):
    return [d for d in db.dispatches.values() if d["bid_id"] == bid_id]


def dispatches_of_reservation(reservation_id):
    out = []
    for d in db.dispatches.values():
        bid = db.bids.get(d["bid_id"])
        if bid is not None and bid["reservation_id"] == reservation_id:
            out.append(d)
    return out


def samples_of(dispatch_id):
    return [s for s in db.telemetry.values() if s["dispatch_id"] == dispatch_id]


def events_of(asset_id):
    return [e for e in db.safety_events.values() if e["asset_id"] == asset_id]


def obligations_of(asset_id):
    return [o for o in db.obligations.values() if o["asset_id"] == asset_id]


def tests_of(asset_id):
    return [t for t in db.capacity_tests.values() if t["asset_id"] == asset_id]


def claims_of(asset_id):
    return [c for c in db.warranty_claims.values() if c["asset_id"] == asset_id]


def reservation_of_bid(bid):
    return db.reservations.get(bid["reservation_id"])


# ---------------------------------------------------------------------------
# Derived asset fields (PRD 3.1) — never written directly
# ---------------------------------------------------------------------------
def rated_energy(asset):
    total = D(asset["nameplate_energy_mwh"])
    for claim in claims_of(asset["id"]):
        if claim["status"] == "REMEDIED" and claim["remedy_energy_add_mwh"] is not None:
            total += D(claim["remedy_energy_add_mwh"])
    return r3(total)


def soh_from_tests(asset):
    """measured_soh_pct of the most recent COMPLETED test — greatest
    scheduled_date, then greatest created_at."""
    best = None
    best_key = None
    for test in tests_of(asset["id"]):
        if test["status"] != "COMPLETED" or test["measured_soh_pct"] is None:
            continue
        key = (db.parse_dt(test["scheduled_date"]), test["_seq"])
        if best_key is None or key > best_key:
            best, best_key = test, key
    if best is None:
        return 100.0
    return best["measured_soh_pct"]


def recompute_rated(asset):
    asset["rated_energy_mwh"] = rated_energy(asset)


def recompute_available(asset):
    asset["available_energy_mwh"] = r3(
        D(asset["rated_energy_mwh"]) * D(asset["soh_pct"]) / Decimal("100"))


def recompute_efc(asset):
    available = D(asset["available_energy_mwh"])
    if available <= 0:
        asset["equivalent_full_cycles_ytd"] = 0.0
        return
    asset["equivalent_full_cycles_ytd"] = r4(
        D(asset["cumulative_throughput_mwh"]) / (Decimal("2") * available))


def soc_floor_mwh(asset):
    return rnd(D(asset["nameplate_energy_mwh"]) * D(asset["soc_floor_pct"])
               / Decimal("100"), 3)


def usable_ceiling_mwh(asset):
    """The smaller of soc_mwh and available_energy_mwh * soc_ceiling_pct / 100;
    the smaller value is the one that gets rounded."""
    stored = D(asset["soc_mwh"])
    ceiling = D(asset["available_energy_mwh"]) * D(asset["soc_ceiling_pct"]) / Decimal("100")
    return rnd(stored if stored < ceiling else ceiling, 3)


def held_reserved_total(asset):
    total = Decimal("0")
    for res in reservations_of(asset["id"]):
        if res["status"] == "HELD":
            total += D(res["reserved_mwh"])
    return rnd(total, 3)


def recompute_reserved_total(asset):
    asset["reserved_mwh_total"] = f(held_reserved_total(asset), 3)


def free_dispatchable(asset, reserved_total=None):
    if reserved_total is None:
        reserved_total = D(asset["reserved_mwh_total"])
    value = rnd(usable_ceiling_mwh(asset) - soc_floor_mwh(asset)
                - D(reserved_total), 3)
    if value < 0:
        value = Decimal("0")
    return f(value, 3)


def recompute_free(asset):
    asset["free_dispatchable_mwh"] = free_dispatchable(asset)


def recompute_pool(asset):
    """reserved_mwh_total then free_dispatchable_mwh — the pool figures."""
    recompute_reserved_total(asset)
    recompute_free(asset)


def recompute_energy_chain(asset):
    """rated -> available -> efc -> free (free always last)."""
    recompute_rated(asset)
    recompute_available(asset)
    recompute_efc(asset)
    recompute_free(asset)


# ---------------------------------------------------------------------------
# Gates (PRD 3.7 — the lockout, market-availability and derate gates)
# ---------------------------------------------------------------------------
def gate_lockout(asset):
    if asset["safety_state"] == "LOCKOUT":
        raise ApiError(errors.ERR_ASSET_SAFETY_LOCKOUT, 409,
                       "The asset is in safety lockout.")


def gate_market_available(asset):
    if asset["market_state"] != "AVAILABLE":
        raise ApiError(errors.ERR_ASSET_NOT_MARKET_AVAILABLE, 409,
                       "The asset is not market-available.")


DERATE_POWER_FRACTION_PCT = Decimal("50.0")


def gate_derate(asset, power_mw):
    """Guards exactly two operations: offer submission and dispatch
    acceptance.  Only while safety_state is ELEVATED."""
    if asset["safety_state"] != "ELEVATED":
        return
    ceiling = D(asset["power_rating_mw"]) * DERATE_POWER_FRACTION_PCT / Decimal("100")
    if D(power_mw) > ceiling:
        raise ApiError(errors.ERR_ASSET_DERATED, 409,
                       "The asset is derated while its safety posture is ELEVATED.")


# ---------------------------------------------------------------------------
# Safety posture derivation (PRD 3.7)
# ---------------------------------------------------------------------------
SAFETY_SEVERITY = {"NONE": -1, "NORMAL": 0, "ELEVATED": 1, "ALARM": 2, "LOCKOUT": 3}
NON_CLOSED_EVENT_STATUSES = ("OPEN", "SUPPRESSION_ACTIVE")


def imposed_safety_state(event_type, severity):
    if event_type == "THERMAL_RUNAWAY":
        return "LOCKOUT"
    if severity == "CRITICAL":
        return "ALARM"
    if severity == "WARNING":
        return "ELEVATED"
    return "NONE"


def derive_safety_state(asset):
    """The most severe imposed_safety_state among the asset's non-closed
    events; NORMAL when there is none."""
    posture = "NORMAL"
    for event in events_of(asset["id"]):
        if event["status"] not in NON_CLOSED_EVENT_STATUSES:
            continue
        imposed = event["imposed_safety_state"]
        if SAFETY_SEVERITY.get(imposed, -1) > SAFETY_SEVERITY[posture]:
            posture = imposed
    return posture


def has_blocking_event(asset):
    """Commissioning requires that no event of this asset is OPEN or
    SUPPRESSION_ACTIVE."""
    for event in events_of(asset["id"]):
        if event["status"] in NON_CLOSED_EVENT_STATUSES:
            return True
    return False


# ---------------------------------------------------------------------------
# Deterministic cascade orderings (PRD 2.9)
# ---------------------------------------------------------------------------
def by_delivery_start(bids):
    return sorted(bids, key=lambda b: (db.parse_dt(b["delivery_start"]), b["_seq"]))


def by_setpoint_start(rows):
    return sorted(rows, key=lambda d: (db.parse_dt(d["setpoint_start"]), d["_seq"]))


def by_program_year(rows):
    return sorted(rows, key=lambda o: (o["program_year"], o["_seq"]))


def by_window_end(rows):
    return sorted(rows, key=lambda r: (db.parse_dt(r["window_end"]), r["_seq"]))


def by_sample_index(rows):
    return sorted(rows, key=lambda s: s["sample_index"])


# ---------------------------------------------------------------------------
# DRAFT offer re-pricing (PRD 3.3, cascade link 4 of PRD 3.9)
# ---------------------------------------------------------------------------
def reprice_draft_bids(asset):
    """While an offer is DRAFT its price tracks the asset's available energy,
    cycle position and lifetime throughput."""
    for bid in by_delivery_start([b for b in bids_of_asset(asset["id"])
                                 if b["status"] == "DRAFT"]):
        start = db.parse_dt(bid["delivery_start"])
        end = db.parse_dt(bid["delivery_end"])
        bid["expected_energy_mwh"] = calc.expected_energy(bid["offer_mw"], start, end)
        bid["cycle_debit_efc"] = calc.cycle_debit(bid["expected_energy_mwh"],
                                                 asset["available_energy_mwh"])
        bid["offer_price_usd_per_mwh"] = calc.offer_price(
            asset, bid["product"], bid["direction"], bid["price_adder_usd_per_mwh"])
        db.touch(bid)


# ---------------------------------------------------------------------------
# Reservation lifecycle helpers (PRD 3.2)
# ---------------------------------------------------------------------------
PRIORITY_RANKS = {"CAPACITY": 1, "ANCILLARY": 2, "ENERGY_ARBITRAGE": 3}


def expire_reservations(asset, now):
    """Step one of the waterfall: the asset's own elapsed positions expire, in
    ascending window_end order and, among ties, ascending created_at."""
    expired = []
    candidates = [r for r in reservations_of(asset["id"]) if r["status"] == "HELD"
                  and db.parse_dt(r["window_end"]) <= now]
    for res in by_window_end(candidates):
        res["status"] = "EXPIRED"
        res["released_reason"] = "WINDOW_EXPIRED"
        db.touch(res)
        expired.append(res)
        recompute_pool(asset)
    return expired


def overlapping_held(asset, window_start, window_end, exclude_id=None):
    """Half-open geometry: an existing hold overlaps when its window_start is
    strictly before the requested window_end and its window_end is strictly
    after the requested window_start."""
    out = []
    for res in reservations_of(asset["id"]):
        if res["status"] != "HELD" or res["id"] == exclude_id:
            continue
        start = db.parse_dt(res["window_start"])
        end = db.parse_dt(res["window_end"])
        if start < window_end and end > window_start:
            out.append(res)
    return out


def _snapshot(rows):
    return [(row, dict(row)) for row in rows]


def _restore(snapshot):
    for row, saved in snapshot:
        row.clear()
        row.update(saved)


def withdraw_bids_of_reservation(reservation, statuses, reason):
    changed = []
    for bid in by_delivery_start([b for b in bids_of_reservation(reservation["id"])
                                 if b["status"] in statuses]):
        bid["status"] = "WITHDRAWN"
        bid["withdrawn_reason"] = reason
        db.touch(bid)
        changed.append(bid)
    return changed


def reservation_waterfall(asset, purpose, reserved_mwh, window_start, window_end,
                          now):
    """The five-step waterfall.  Returns nothing; raises ERR_SOC_INSUFFICIENT
    when the request does not fit.  The expiry sweep of step one is not part of
    the preemption rollback — only ladder releases are unwound."""
    expire_reservations(asset, now)

    floor = soc_floor_mwh(asset)
    usable = usable_ceiling_mwh(asset)

    overlapping = overlapping_held(asset, window_start, window_end)
    overlap_sum = rnd(sum((D(r["reserved_mwh"]) for r in overlapping), Decimal("0")), 3)
    headroom = rnd(usable - floor - overlap_sum, 3)

    requested = D(reserved_mwh)
    if requested <= headroom:
        return

    if purpose != "CAPACITY":
        raise ApiError(errors.ERR_SOC_INSUFFICIENT, 422,
                       "The request does not fit the asset's remaining "
                       "state-of-charge headroom.")

    candidates = [r for r in overlapping if r["purpose"] == "ENERGY_ARBITRAGE"]
    candidates.sort(key=lambda r: (-r["priority_rank"],
                                   db.parse_dt(r["window_start"]), r["_seq"]))

    touched = []
    for candidate in candidates:
        touched.extend([candidate])
        touched.extend(bids_of_reservation(candidate["id"]))
    snapshot = _snapshot(touched)

    for candidate in candidates:
        candidate["status"] = "RELEASED"
        candidate["released_reason"] = "CAPACITY_PREEMPTION"
        db.touch(candidate)
        withdraw_bids_of_reservation(candidate, ("SUBMITTED", "CLEARED"),
                                     "ASSET_SUSPENDED")
        headroom = rnd(headroom + D(candidate["reserved_mwh"]), 3)
        if headroom >= requested:
            return

    _restore(snapshot)
    recompute_pool(asset)
    raise ApiError(errors.ERR_SOC_INSUFFICIENT, 422,
                   "The capacity preemption ladder could not free enough "
                   "state-of-charge headroom.")


# ---------------------------------------------------------------------------
# The suspension cascade (PRD 3.7, links one to six)
# ---------------------------------------------------------------------------
def safety_suspension_cascade(asset, now):
    """Recompute the posture and, when the market axis actually moves
    AVAILABLE -> SUSPENDED in this request, run links three to six."""
    posture = derive_safety_state(asset)          # link one
    asset["safety_state"] = posture

    suspended_now = False
    if posture in ("ALARM", "LOCKOUT"):           # link two
        reason = "SAFETY_ALARM" if posture == "ALARM" else "SAFETY_LOCKOUT"
        if asset["market_state"] == "AVAILABLE":
            asset["market_state"] = "SUSPENDED"
            asset["suspension_reason"] = reason
            asset["suspended_at"] = db.fmt_dt(now)
            suspended_now = True
        elif asset["market_state"] == "SUSPENDED":
            # ALARM -> LOCKOUT on an already-suspended asset: only the reason
            # changes and market_state stays SUSPENDED.
            asset["suspension_reason"] = reason

    if not suspended_now:
        return

    # link three — every live offer of this asset is withdrawn
    withdrawn = []
    for bid in by_delivery_start([b for b in bids_of_asset(asset["id"])
                                 if b["status"] in ("DRAFT", "SUBMITTED", "CLEARED")]):
        bid["status"] = "WITHDRAWN"
        bid["withdrawn_reason"] = "ASSET_SUSPENDED"
        db.touch(bid)
        withdrawn.append(bid)

    # link four — each withdrawn offer's held reservation is released
    for bid in withdrawn:
        res = reservation_of_bid(bid)
        if res is not None and res["status"] == "HELD":
            res["status"] = "RELEASED"
            res["released_reason"] = "BID_WITHDRAWN"
            db.touch(res)
    recompute_pool(asset)

    # link five — every live instruction of this asset fails
    live = [d for d in dispatches_of_asset(asset["id"])
            if d["execution_status"] in ("PENDING", "ACCEPTED", "EXECUTING")]
    for instruction in by_setpoint_start(live):
        instruction["execution_status"] = "FAILED"
        instruction["failure_reason"] = "ASSET_SUSPENDED"
        db.touch(instruction)

    # link six — open an unavailability accrual on this programme year
    year = now.year
    accruing = [o for o in obligations_of(asset["id"])
                if o["status"] in ("ACTIVE", "SHORTFALL", "PENALIZED")
                and o["program_year"] == year]
    for obligation in by_program_year(accruing):
        obligation["accrual_started_at"] = db.fmt_dt(now)
        db.touch(obligation)


def safety_resume_recompute(asset, now):
    """The closure recompute (PRD 3.7): five possible landings, and the
    resumption folds every open accrual into unavailable_hours."""
    posture = derive_safety_state(asset)
    asset["safety_state"] = posture

    if posture in ("ALARM", "LOCKOUT"):
        if asset["market_state"] == "SUSPENDED":
            asset["suspension_reason"] = ("SAFETY_ALARM" if posture == "ALARM"
                                          else "SAFETY_LOCKOUT")
        return

    if asset["market_state"] != "SUSPENDED":
        return

    asset["market_state"] = "AVAILABLE"
    started_raw = asset["suspended_at"]
    asset["suspension_reason"] = None
    asset["suspended_at"] = None

    open_accruals = [o for o in obligations_of(asset["id"])
                     if o["accrual_started_at"] is not None]
    for obligation in by_program_year(open_accruals):
        started = db.parse_dt(obligation["accrual_started_at"])
        elapsed = Decimal(str(db.hours_between(started, now)))
        obligation["unavailable_hours"] = f(
            rnd(D(obligation["unavailable_hours"]) + elapsed, 2), 2)
        obligation["accrual_started_at"] = None
        db.touch(obligation)
    return started_raw


def rederate_obligations(asset):
    """Cascade link three of the capacity-test completion chain."""
    candidates = [o for o in obligations_of(asset["id"])
                  if o["status"] in ("ACTIVE", "SHORTFALL")]
    for obligation in by_program_year(candidates):
        derated = calc.derated_committed(asset["available_energy_mwh"], obligation)
        if derated is None:
            continue
        obligation["status"] = "SHORTFALL"
        obligation["derated_committed_mw"] = derated
        obligation["penalty_exposure_usd"] = preliminary_penalty(obligation)
        db.touch(obligation)


def preliminary_penalty(obligation):
    """penalty_exposure_usd recomputed under the PRELIMINARY variant, without
    restating the obligation's other assessment outputs."""
    now = db.clock_now()
    period = preliminary_period_hours(obligation, now)
    result = calc.assess_obligation(obligation, "PRELIMINARY", period, None)
    return result["penalty_exposure_usd"]


def preliminary_period_hours(obligation, now):
    from datetime import datetime, timezone
    year_start = datetime(obligation["program_year"], 1, 1, tzinfo=timezone.utc)
    hours = Decimal(str(db.hours_between(year_start, now)))
    if hours < 0:
        hours = Decimal("0")
    return hours


# ---------------------------------------------------------------------------
# Listing (PRD 2.3)
# ---------------------------------------------------------------------------
def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def newest_first(rows):
    return db.sort_newest_first(rows)


# ---------------------------------------------------------------------------
# Safety event creation — shared by the manual report and the telemetry cascade
# ---------------------------------------------------------------------------
def open_safety_event(asset, event_type, severity, detected_temp, source,
                      opened_by, source_dispatch_id=None,
                      source_sample_index=None):
    event = db.new_row()
    event.update({
        "asset_id": asset["id"],
        "source_dispatch_id": source_dispatch_id,
        "source_sample_index": source_sample_index,
        "event_type": event_type,
        "severity": severity,
        "detected_max_cell_temp_c": detected_temp,
        "source": source,
        "imposed_safety_state": imposed_safety_state(event_type, severity),
        "status": "OPEN",
        "suppression_discharged": False,
        "suppression_agent_kg": None,
        "emergency_response_ack_at": None,
        "emergency_ack_agencies": [],
        "responder_cleared": False,
        "opened_by_user_id": opened_by,
        "closed_by_user_id": None,
    })
    db.safety_events[event["id"]] = event

    safety_suspension_cascade(asset, db.clock_now())
    db.touch(asset)
    return event
