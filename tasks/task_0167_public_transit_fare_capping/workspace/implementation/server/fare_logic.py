"""Fare calculation and cap-period bookkeeping. §3.5 / §3.8 / §1.3 calculations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .clock import iso_format, now, parse_iso
from .common import bump, stamp_new
from .store import gen_id, store


BASE_FARE_CENTS = 275
DAILY_CAP_CENTS = 600
WEEKLY_CAP_CENTS = 3300
TRANSFER_WINDOW_MINUTES = 120
LOW_INCOME_DISCOUNT_RATE = Decimal("0.60")
REDUCED_FARE_DISCOUNT_RATE = Decimal("0.50")
LOW_INCOME_THRESHOLD_CENTS = 3_000_000


# ---------- helpers ----------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def utc_day_window(dt: datetime) -> tuple[datetime, datetime]:
    start = dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=24)
    return start, end


def utc_iso_week_window(dt: datetime) -> tuple[datetime, datetime]:
    """ISO week begins Monday at 00:00 UTC; window_end is +7 days."""
    base = dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    # Python: Monday is weekday() == 0.
    offset_days = base.weekday()
    monday = base - timedelta(days=offset_days)
    return monday, monday + timedelta(days=7)


# ---------- cap-period plumbing ----------

def ensure_cap_period(card_id: str, scope: str, window_start: datetime, window_end: datetime) -> dict[str, Any]:
    for period in store.cap_periods.values():
        if (
            period["card_id"] == card_id
            and period["scope"] == scope
            and period["window_start"] == iso_format(window_start)
        ):
            return period
    cap_cents = DAILY_CAP_CENTS if scope == "DAILY" else WEEKLY_CAP_CENTS
    period = {
        "card_id": card_id,
        "scope": scope,
        "window_start": iso_format(window_start),
        "window_end": iso_format(window_end),
        "accumulated_cents": 0,
        "cap_cents": cap_cents,
        "cap_reached_at": None,
    }
    stamp_new(period)
    store.cap_periods[period["id"]] = period
    return period


def get_or_create_periods_for(card_id: str, tap_in_at: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    d_start, d_end = utc_day_window(tap_in_at)
    w_start, w_end = utc_iso_week_window(tap_in_at)
    daily = ensure_cap_period(card_id, "DAILY", d_start, d_end)
    weekly = ensure_cap_period(card_id, "WEEKLY", w_start, w_end)
    return daily, weekly


def increment_period(period: dict[str, Any], delta: int, marker_time: datetime | None = None) -> None:
    period["accumulated_cents"] = int(period["accumulated_cents"]) + int(delta)
    cap = int(period["cap_cents"])
    if delta > 0:
        if period["cap_reached_at"] is None and period["accumulated_cents"] >= cap:
            period["cap_reached_at"] = iso_format(marker_time or now())
    else:
        # Negative delta (refund / underflow) can clear the marker.
        if period["accumulated_cents"] < cap:
            period["cap_reached_at"] = None
    bump(period)


# ---------- discount/base-fare resolution ----------

def base_fare_after_discount(card: dict[str, Any], rider: dict[str, Any]) -> int:
    dc = card.get("discount_class", "STANDARD")
    if dc == "STANDARD":
        return BASE_FARE_CENTS
    if dc == "REDUCED_FARE":
        return round_half_up_int(Decimal(BASE_FARE_CENTS) * REDUCED_FARE_DISCOUNT_RATE)
    if dc == "LOW_INCOME":
        if rider.get("low_income_verified"):
            return round_half_up_int(Decimal(BASE_FARE_CENTS) * LOW_INCOME_DISCOUNT_RATE)
        return BASE_FARE_CENTS  # fall back to standard
    return BASE_FARE_CENTS


# ---------- transfer eligibility ----------

def find_eligible_prior_trip(
    card_id: str,
    this_tap_in_at: datetime,
    *,
    candidates: list[dict[str, Any]] | None = None,
    ignored_link_holders: set[str] | None = None,
) -> dict[str, Any] | None:
    """Half-open lower bound: 0 < delta_minutes <= 120; tie-break by max tap_in_at, then max id."""
    pool = candidates if candidates is not None else list(store.trips.values())
    ignored = ignored_link_holders if ignored_link_holders is not None else _set_of_first_legs()

    eligible: list[tuple[datetime, str, dict[str, Any]]] = []
    for t in pool:
        if t["card_id"] != card_id:
            continue
        if t.get("travel_status") != "COMPLETED":
            continue
        if t["id"] in ignored:
            continue
        try:
            prior_at = parse_iso(t["tap_in_at"])
        except Exception:
            continue
        delta = this_tap_in_at - prior_at
        delta_minutes = delta.total_seconds() / 60.0
        if delta_minutes <= 0:
            continue
        if delta_minutes > TRANSFER_WINDOW_MINUTES:
            continue
        eligible.append((prior_at, t["id"], t))

    if not eligible:
        return None
    eligible.sort(key=lambda kv: (kv[0], kv[1]), reverse=True)
    return eligible[0][2]


def _set_of_first_legs() -> set[str]:
    return {tl["first_trip_id"] for tl in store.transfer_links.values()}


# ---------- provisional fare computation ----------

def compute_provisional_pre_cap(card: dict[str, Any], rider: dict[str, Any], tap_in_at: datetime) -> tuple[int, dict[str, Any] | None]:
    base_after = base_fare_after_discount(card, rider)
    prior = find_eligible_prior_trip(card["id"], tap_in_at)
    if prior is not None:
        return 0, prior
    return base_after, None


def apply_cap_minimum(pre_cap: int, daily: dict[str, Any], weekly: dict[str, Any]) -> int:
    remaining_daily = max(0, int(daily["cap_cents"]) - int(daily["accumulated_cents"]))
    remaining_weekly = max(0, int(weekly["cap_cents"]) - int(weekly["accumulated_cents"]))
    return min(pre_cap, remaining_daily, remaining_weekly)


# ---------- FSA split ----------

def fsa_split(rider: dict[str, Any], card: dict[str, Any], provisional: int) -> tuple[int, int, dict[str, Any] | None]:
    """Returns (paid_from_fsa, remainder_from_wallet, account_or_None).

    Raises ApiError(ERR_INSUFFICIENT_FUNDS) if combined funds can't cover the provisional charge.
    """
    from .errors import ApiError

    account: dict[str, Any] | None = None
    if rider.get("employer_id"):
        for acc in store.fsa_accounts.values():
            if acc["rider_id"] == rider["id"]:
                account = acc
                break

    if not rider.get("employer_id") or account is None or account.get("status") != "ACTIVE":
        paid_from_fsa = 0
    else:
        paid_from_fsa = min(provisional, int(account["balance_cents"]))
    remainder = provisional - paid_from_fsa

    wallet_balance = int(card.get("wallet_balance_cents", 0))
    if remainder > wallet_balance:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", "Wallet plus FSA cannot cover the provisional fare")
    return paid_from_fsa, remainder, account


# ---------- refund-split allocator ----------

def refund_split(provisional: int, effective_settled: int, paid_from_fsa: int) -> tuple[int, int]:
    """Returns (refund_to_fsa, refund_to_wallet). Wallet absorbs rounding drift."""
    refund_total = max(0, provisional - effective_settled)
    if refund_total == 0:
        return 0, 0
    if provisional > 0:
        share = Decimal(refund_total) * Decimal(paid_from_fsa) / Decimal(provisional)
        refund_to_fsa = round_half_up_int(share)
    else:
        refund_to_fsa = 0
    refund_to_wallet = refund_total - refund_to_fsa
    return refund_to_fsa, refund_to_wallet


# ---------- create the transfer-link record ----------

def make_transfer_link(first_trip: dict[str, Any], second_trip: dict[str, Any]) -> dict[str, Any]:
    first_at = parse_iso(first_trip["tap_in_at"])
    second_at = parse_iso(second_trip["tap_in_at"])
    minutes = int((second_at - first_at).total_seconds() // 60)
    link = {
        "id": gen_id(),
        "first_trip_id": first_trip["id"],
        "second_trip_id": second_trip["id"],
        "window_minutes": minutes,
        "created_at": iso_format(now()),
    }
    store.transfer_links[link["id"]] = link
    return link


# ---------- chronological settlement ----------

def chronological_settle(card_id: str, window_start: datetime, window_end: datetime, scope: str = "DAILY") -> list[dict[str, Any]]:
    """Recompute settled fares chronologically for trips in [window_start, window_end).

    Trips currently in DISPUTED fare_status are excluded.
    Returns the list of trips (in order) for downstream delta application.
    """
    from .errors import ApiError  # noqa: F401

    ws_iso = iso_format(window_start)
    we_iso = iso_format(window_end)

    in_window: list[dict[str, Any]] = []
    for trip in store.trips.values():
        if trip["card_id"] != card_id:
            continue
        if trip.get("fare_status") == "DISPUTED":
            continue
        tap_at = parse_iso(trip["tap_in_at"])
        if window_start <= tap_at < window_end:
            in_window.append(trip)

    in_window.sort(key=lambda t: (parse_iso(t["tap_in_at"]), t["id"]))

    # Per-trip recompute. We need both daily and weekly remaining views.
    # For DAILY-driven settlement we walk this window; weekly remaining is computed against
    # the running tally of settled fares in the weekly window so far.
    running_daily = 0
    completed_pool: list[dict[str, Any]] = []
    completed_ids: set[str] = set()
    consumed_link_priors: set[str] = set()

    # For weekly remaining lookup, build per-(card, weekly_window_start) running counters.
    # Easier: compute weekly_remaining_at_T by summing settled_fare for trips already settled
    # in the same weekly window plus this card.
    settled_outputs: list[dict[str, Any]] = []
    card = store.cards.get(card_id)
    rider = store.riders.get(card["rider_id"]) if card else None

    weekly_ws, weekly_we = utc_iso_week_window(window_start)

    for trip in in_window:
        # Step 1: post-discount base fare.
        base_after = base_fare_after_discount(card, rider) if card and rider else BASE_FARE_CENTS

        # Step 2: transfer eligibility against chronological history.
        tap_at = parse_iso(trip["tap_in_at"])
        prior = find_eligible_prior_trip(
            card_id,
            tap_at,
            candidates=completed_pool,
            ignored_link_holders=consumed_link_priors,
        )
        if prior is not None:
            pre_cap = 0
        else:
            pre_cap = base_after

        # Step 3: apply cap.
        remaining_daily = max(0, DAILY_CAP_CENTS - running_daily)

        # Compute weekly_remaining_at_T by summing settled values for trips on this card whose tap_in_at
        # falls in the weekly window AND we've already processed (or settled earlier in another sweep).
        weekly_running = _sum_weekly_settled(card_id, weekly_ws, weekly_we, exclude_id=trip["id"], include_in_window=settled_outputs)
        remaining_weekly = max(0, WEEKLY_CAP_CENTS - weekly_running)

        settled_T = max(0, min(pre_cap, remaining_daily, remaining_weekly))

        trip["_pending_settled"] = settled_T
        trip["_pending_pre_cap"] = pre_cap
        trip["_pending_prior_id"] = prior["id"] if prior else None
        settled_outputs.append(trip)
        running_daily += settled_T

        # All trips in the window are considered completed for chronological transfer
        # tracking — settlement happens after travel completion.
        if trip.get("travel_status") in ("COMPLETED", "INCOMPLETE_FORCED"):
            completed_pool.append(trip)
            completed_ids.add(trip["id"])
            if prior is not None:
                consumed_link_priors.add(prior["id"])
    return settled_outputs


def _sum_weekly_settled(card_id: str, weekly_ws: datetime, weekly_we: datetime, *, exclude_id: str, include_in_window: list[dict[str, Any]]) -> int:
    total = 0
    in_window_ids = {t["id"] for t in include_in_window if t["id"] != exclude_id}
    for trip in store.trips.values():
        if trip["card_id"] != card_id or trip["id"] == exclude_id:
            continue
        if trip.get("fare_status") == "DISPUTED":
            continue
        tap_at = parse_iso(trip["tap_in_at"])
        if not (weekly_ws <= tap_at < weekly_we):
            continue
        if trip["id"] in in_window_ids:
            total += int(trip.get("_pending_settled", 0))
            continue
        if trip.get("fare_status") == "SETTLED":
            total += int(trip.get("settled_fare_cents") or 0)
        else:
            total += int(trip.get("provisional_fare_cents") or 0)
    return total
