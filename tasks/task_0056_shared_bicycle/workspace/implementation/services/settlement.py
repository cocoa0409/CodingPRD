"""Ride fare settlement calculation (PRD §3.4 / SCAFFOLD ride_fare_settlement)."""
from __future__ import annotations

from typing import Dict, Any

from constants import (
    DAILY_CAP_EBIKE_CENTS,
    DAILY_CAP_STD_CENTS,
    PER_MIN_OVER_RATE_EBIKE_CENTS,
    PER_MIN_OVER_RATE_STD_CENTS,
    PER_MIN_RATE_EBIKE_CENTS,
    PER_MIN_RATE_STD_CENTS,
    SEGMENT_BREAK_MIN,
)
from db import regions
from services.geofence_lookup import fence_kind_at


def settle_ride(
    *,
    ride: Dict[str, Any],
    rider: Dict[str, Any],
    bike: Dict[str, Any],
    end_minute: int,
    end_lat: float,
    end_lng: float,
    fault_waiver: bool,
) -> Dict[str, Any]:
    """Compute every settlement field on `ride`. Returns the mutated ride.

    Does not mutate rider wallet here — the caller is responsible for the
    wallet debit/credit and the insufficient-balance check, because the
    check must happen against the *would-be* post-settlement value before
    we commit.
    """
    region = regions[ride["region_id"]]

    start_minute = int(ride["start_minute"])
    duration = max(end_minute - start_minute, 1)

    bike_model = bike["model"]
    pass_active = rider.get("monthly_pass_expires_minute", 0) > end_minute

    # Step 1: free-period coverage.
    applied_free = min(rider.get("free_minutes_remaining", 0), duration)
    remaining = duration - applied_free

    # Step 2: monthly pass — STANDARD only.
    if pass_active and bike_model == "STANDARD":
        pass_covered = remaining
    else:
        pass_covered = 0
    chargeable = remaining - pass_covered

    # Step 3: per-minute / segment rates by model.
    if bike_model == "STANDARD":
        per_min_rate = PER_MIN_RATE_STD_CENTS
        over_rate = PER_MIN_OVER_RATE_STD_CENTS
        daily_cap = DAILY_CAP_STD_CENTS
    else:  # E_BIKE
        per_min_rate = PER_MIN_RATE_EBIKE_CENTS
        over_rate = PER_MIN_OVER_RATE_EBIKE_CENTS
        daily_cap = DAILY_CAP_EBIKE_CENTS

    first_seg = min(chargeable, SEGMENT_BREAK_MIN)
    over_seg = max(chargeable - SEGMENT_BREAK_MIN, 0)
    base_fare = first_seg * per_min_rate + over_seg * over_rate

    # Step 4: daily cap clamp.
    if base_fare >= daily_cap:
        base_fare_capped = daily_cap
        settlement_variant = "DAILY_CAP"
    else:
        base_fare_capped = base_fare
        settlement_variant = "PER_MINUTE"

    # Step 5: fence at end location (FORBIDDEN already blocked upstream).
    end_kind = fence_kind_at(ride["region_id"], end_lat, end_lng)
    if end_kind == "FORBIDDEN":
        end_kind = "NONE"  # safety guard; settlement only runs after check

    if end_kind == "RESTRICTED" and not fault_waiver:
        penalty = int(region.get("out_of_zone_penalty_cents", 0))
    else:
        penalty = 0
    if end_kind == "ALLOWED_PARKING":
        reward = int(region.get("in_zone_return_reward_cents", 0))
    else:
        reward = 0

    final_fare = base_fare_capped + penalty

    ride["start_minute"] = start_minute
    ride["end_minute"] = end_minute
    ride["end_lat"] = end_lat
    ride["end_lng"] = end_lng
    ride["end_fence_kind"] = end_kind
    ride["applied_free_minutes"] = applied_free
    ride["pass_covered_minutes"] = pass_covered
    ride["chargeable_minutes"] = chargeable
    ride["base_fare_cents"] = base_fare_capped
    ride["penalty_cents"] = penalty
    ride["reward_cents"] = reward
    ride["final_fare_cents"] = final_fare
    ride["settlement_variant"] = settlement_variant
    return ride
