"""Admin/system routes: clock advance + three sweeps."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from ..auth import require_auth
from ..clock import iso_format, now, parse_iso, set_clock
from ..common import bump, get_json_body, require_fields
from ..errors import ApiError
from ..fare_logic import (
    BASE_FARE_CENTS,
    base_fare_after_discount,
    chronological_settle,
    increment_period,
    refund_split,
    utc_iso_week_window,
)
from ..response import respond
from ..store import store


bp = Blueprint("admin", __name__)


@bp.post("/transit/_clock/advance")
@require_auth("AgencyOfficer", "Auditor")
def clock_advance():
    body = get_json_body()
    require_fields(body, "to")
    try:
        target = parse_iso(body["to"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    set_clock(target)
    return respond({"now": iso_format(now())}, 200)


# ---------- Incomplete-trip sweep ----------

@bp.post("/transit/_sweep/incomplete-trips")
@require_auth("AgencyOfficer")
def sweep_incomplete():
    now_dt = now()
    closed = []
    with store.lock:
        for trip in list(store.trips.values()):
            if trip.get("travel_status") != "TAPPED_IN":
                continue
            tap_in_at = parse_iso(trip["tap_in_at"])
            if now_dt < tap_in_at + timedelta(minutes=180):
                continue

            card = store.cards.get(trip["card_id"])
            rider = store.riders.get(card["rider_id"]) if card else None

            # Force-close
            forced_out = tap_in_at + timedelta(minutes=180)
            trip["tap_out_at"] = iso_format(forced_out)
            trip["travel_status"] = "INCOMPLETE_FORCED"

            # If provisional was discounted (e.g., transfer => 0), charge difference up to
            # post-discount base; this charge cascades into the cap period.
            base_after = base_fare_after_discount(card, rider) if (card and rider) else BASE_FARE_CENTS
            current_prov = int(trip.get("provisional_fare_cents") or 0)
            shortfall = base_after - current_prov
            if shortfall > 0:
                wallet = int(card.get("wallet_balance_cents", 0)) if card else 0
                # Charge from wallet (we already debited paid_from_fsa at tap-in; force-charge falls on wallet)
                actually_charged = min(shortfall, wallet)
                if card and actually_charged > 0:
                    card["wallet_balance_cents"] = wallet - actually_charged
                    bump(card)
                trip["provisional_fare_cents"] = current_prov + actually_charged
                # Cascade: bump the cap periods covering this tap_in_at
                for period in list(store.cap_periods.values()):
                    if period["card_id"] != trip["card_id"]:
                        continue
                    ws = parse_iso(period["window_start"])
                    we = parse_iso(period["window_end"])
                    if ws <= tap_in_at < we:
                        increment_period(period, actually_charged, marker_time=now_dt)
            bump(trip)
            closed.append(trip["id"])
    return respond({"closed_count": len(closed), "closed_trip_ids": closed}, 200)


# ---------- Settlement sweep ----------

@bp.post("/transit/_sweep/settle")
@require_auth("AgencyOfficer")
def sweep_settle():
    now_dt = now()
    touched_trips: list[str] = []
    with store.lock:
        # Per-card DAILY periods whose window_end <= now()
        periods = [
            p for p in store.cap_periods.values()
            if p.get("scope") == "DAILY" and parse_iso(p["window_end"]) <= now_dt
        ]
        # Order by window_start to apply chronologically
        periods.sort(key=lambda p: parse_iso(p["window_start"]))

        for period in periods:
            window_start = parse_iso(period["window_start"])
            window_end = parse_iso(period["window_end"])
            card_id = period["card_id"]
            card = store.cards.get(card_id)
            rider = store.riders.get(card["rider_id"]) if card else None
            account = None
            if rider and rider.get("employer_id"):
                for acc in store.fsa_accounts.values():
                    if acc.get("rider_id") == rider["id"]:
                        account = acc
                        break

            ordered = chronological_settle(card_id, window_start, window_end, scope="DAILY")
            for trip in ordered:
                # Skip already settled trips
                if trip.get("fare_status") == "SETTLED":
                    # Clear pending markers
                    trip.pop("_pending_settled", None)
                    trip.pop("_pending_pre_cap", None)
                    trip.pop("_pending_prior_id", None)
                    continue
                if trip.get("fare_status") != "PROVISIONAL":
                    trip.pop("_pending_settled", None)
                    trip.pop("_pending_pre_cap", None)
                    trip.pop("_pending_prior_id", None)
                    continue
                if trip.get("travel_status") not in ("COMPLETED", "INCOMPLETE_FORCED"):
                    trip.pop("_pending_settled", None)
                    trip.pop("_pending_pre_cap", None)
                    trip.pop("_pending_prior_id", None)
                    continue

                settled_T = int(trip.pop("_pending_settled", 0))
                trip.pop("_pending_pre_cap", None)
                trip.pop("_pending_prior_id", None)
                provisional = int(trip.get("provisional_fare_cents") or 0)
                paid_from_fsa = int(trip.get("paid_from_fsa_cents") or 0)

                if settled_T < provisional:
                    # Refund delta
                    refund_to_fsa, refund_to_wallet = refund_split(provisional, settled_T, paid_from_fsa)
                    if account is not None and refund_to_fsa > 0:
                        account["balance_cents"] = int(account["balance_cents"]) + refund_to_fsa
                        bump(account)
                    elif refund_to_fsa > 0:
                        refund_to_wallet += refund_to_fsa
                    if card and refund_to_wallet > 0:
                        card["wallet_balance_cents"] = int(card["wallet_balance_cents"]) + refund_to_wallet
                        bump(card)
                elif settled_T > provisional:
                    extra = settled_T - provisional
                    # Wallet first, then FSA
                    if card:
                        from_wallet = min(extra, int(card.get("wallet_balance_cents", 0)))
                        if from_wallet > 0:
                            card["wallet_balance_cents"] = int(card["wallet_balance_cents"]) - from_wallet
                            bump(card)
                        extra -= from_wallet
                    if extra > 0 and account is not None:
                        from_fsa = min(extra, int(account.get("balance_cents", 0)))
                        if from_fsa > 0:
                            account["balance_cents"] = int(account["balance_cents"]) - from_fsa
                            bump(account)
                        # If still positive, ignore (best-effort; insufficient back-charge funds).

                trip["settled_fare_cents"] = settled_T
                trip["fare_status"] = "SETTLED"
                bump(trip)
                touched_trips.append(trip["id"])
        # Clean any lingering pending markers
        for trip in store.trips.values():
            trip.pop("_pending_settled", None)
            trip.pop("_pending_pre_cap", None)
            trip.pop("_pending_prior_id", None)
    return respond({"settled_count": len(touched_trips), "trip_ids": touched_trips}, 200)


# ---------- Low-income expiry sweep ----------

@bp.post("/transit/_sweep/low-income-expiry")
@require_auth("AgencyOfficer")
def sweep_low_income_expiry():
    now_dt = now()
    expired = []
    with store.lock:
        for verif in list(store.low_income_verifications.values()):
            if verif.get("status") != "ACTIVE":
                continue
            approved_at = verif.get("approved_at")
            if approved_at is None:
                continue
            try:
                ts = parse_iso(approved_at)
            except Exception:
                continue
            if now_dt < ts + timedelta(days=365):
                continue
            verif["status"] = "EXPIRED"
            bump(verif)
            expired.append(verif["id"])

            rider_id = verif["rider_id"]
            # Recompute rider.low_income_verified
            still_active = False
            for other in store.low_income_verifications.values():
                if other["id"] == verif["id"]:
                    continue
                if other.get("rider_id") != rider_id:
                    continue
                if other.get("status") == "ACTIVE":
                    still_active = True
                    break
            rider = store.riders.get(rider_id)
            if rider is not None and not still_active and rider.get("low_income_verified"):
                rider["low_income_verified"] = False
                bump(rider)
                # Cascade: downgrade LOW_INCOME cards
                for card in store.cards.values():
                    if card.get("rider_id") != rider_id:
                        continue
                    if card.get("discount_class") == "LOW_INCOME":
                        card["discount_class"] = "STANDARD"
                        bump(card)
    return respond({"expired_count": len(expired), "verification_ids": expired}, 200)
