"""match_rank_score: candidate filter, block selection, ranking, offer batch."""

from datetime import date, timedelta

from db import clock, db
from util import D, rhu, utc_date

from services.calc import ADMIT, admission
from services.core import (
    CENTER,
    IN_HOME,
    OFFER_TTL_HOURS,
    PROBATION_FACTOR,
    REQUIRED_CREDENTIAL_TYPES,
    W_CAPACITY,
    W_CONTINUITY,
    W_MODE,
    W_QUALITY,
    block_occupancy,
    block_status,
    created_key,
    new_row,
    provider_quality,
    touch,
)


def required_seats_for(care_mode, dependent_count):
    return dependent_count if care_mode == CENTER else 1


def block_remaining(block):
    reserved, committed = block_occupancy(block)
    return block["total_slots"] - reserved - committed


def credentials_ok_for_care_date(provider_id, care_date):
    for credential_type in REQUIRED_CREDENTIAL_TYPES:
        found = False
        for credential in db.credentials.values():
            if credential["provider_id"] != provider_id:
                continue
            if credential["credential_type"] != credential_type:
                continue
            if credential["status"] != "VALID":
                continue
            if date.fromisoformat(credential["expires_on"]) < care_date:
                continue
            found = True
            break
        if not found:
            return False
    return True


def candidate_block(provider, reservation):
    care_date = reservation["care_date"]
    blocks = []
    for block in db.capacity_blocks.values():
        if block["provider_id"] != provider["id"]:
            continue
        if block["service_date"] != care_date:
            continue
        if block_status(block) != "OPEN":
            continue
        if block["start_time_utc"] > reservation["care_start_utc"]:
            continue
        if reservation["care_end_utc"] > block["end_time_utc"]:
            continue
        if admission(provider, block, reservation) != ADMIT:
            continue
        blocks.append(block)
    if not blocks:
        return None
    blocks.sort(
        key=lambda b: (-block_remaining(b), b["start_time_utc"], created_key(b))
    )
    return blocks[0]


def candidates(reservation):
    care_date = date.fromisoformat(reservation["care_date"])
    clock_date = utc_date(clock())
    excluded = set(reservation["excluded_provider_ids"])
    result = []
    for provider in db.providers.values():
        if provider["market_code"] != reservation["market_code"]:
            continue
        if provider["network_status"] not in ("CREDENTIALED", "PROBATION"):
            continue
        if reservation["requested_care_mode"] != "EITHER" and provider["care_mode"] != reservation[
            "requested_care_mode"
        ]:
            continue
        if provider["id"] in excluded:
            continue
        if not credentials_ok_for_care_date(provider["id"], care_date):
            continue
        if care_date == clock_date and not provider["same_day_available"]:
            continue
        block = candidate_block(provider, reservation)
        if block is None:
            continue
        result.append((provider, block))
    return result


def has_continuity(reservation, provider_id):
    for other in db.reservations.values():
        if other["employee_id"] != reservation["employee_id"]:
            continue
        if other["matched_provider_id"] != provider_id:
            continue
        if other["fulfillment_status"] == "COMPLETED":
            return True
    return False


def score_candidate(reservation, provider, block):
    seats = required_seats_for(provider["care_mode"], reservation["dependent_count"])
    remaining = block_remaining(block)
    quality = provider_quality(provider, "ROLLING_90D")
    quality_component = rhu(quality / D(100), 4)
    denominator = max(1, seats * 2)
    capacity_component = rhu(min(D(1), D(remaining) / D(denominator)), 4)
    if reservation["requested_care_mode"] == "EITHER":
        mode_component = D("1.0") if provider["care_mode"] == CENTER else D("0.6")
    else:
        mode_component = D("1.0")
    continuity_component = (
        D("1.0") if has_continuity(reservation, provider["id"]) else D("0.0")
    )
    base = (
        W_QUALITY * quality_component
        + W_CAPACITY * capacity_component
        + W_MODE * mode_component
        + W_CONTINUITY * continuity_component
    )
    on_probation = provider["network_status"] == "PROBATION"
    factor = PROBATION_FACTOR if on_probation else D(1)
    rank_score = rhu(base * factor, 4)
    return {
        "provider": provider,
        "block": block,
        "quality": quality,
        "rank_score": rank_score,
        "quality_component": quality_component,
        "capacity_component": capacity_component,
        "mode_component": mode_component,
        "continuity_component": continuity_component,
        "probation_penalty_applied": on_probation,
        "remaining_slots_at_offer": remaining,
    }


def expire_offers(reservation_id, statuses, reason_code):
    for offer in db.match_offers.values():
        if offer["reservation_id"] != reservation_id:
            continue
        if offer["offer_status"] not in statuses:
            continue
        offer["offer_status"] = "EXPIRED"
        offer["reason_code"] = reason_code
        touch(offer)


def offer_expiry_for(reservation):
    ttl = clock() + timedelta(hours=OFFER_TTL_HOURS)
    care_start = reservation["care_start_utc"]
    return ttl if ttl <= care_start else care_start


def run_match(reservation):
    """Publish a fresh offer batch. Returns True when at least one offer was made."""
    scored = [
        score_candidate(reservation, provider, block)
        for provider, block in candidates(reservation)
    ]
    scored.sort(
        key=lambda s: (
            -s["rank_score"],
            -s["quality"],
            created_key(s["provider"]),
        )
    )

    expire_offers(reservation["id"], ("PROPOSED",), "REMATCHED")

    if not scored:
        reservation["fulfillment_status"] = "UNFULFILLED"
        reservation["unfulfilled_reason_code"] = "NO_ELIGIBLE_PROVIDER"
        touch(reservation)
        return False

    expires_at = offer_expiry_for(reservation)
    position = 0
    selected_provider = None
    for entry in scored:
        position += 1
        offer = new_row(
            {
                "reservation_id": reservation["id"],
                "provider_id": entry["provider"]["id"],
                "rank_score": entry["rank_score"],
                "rank_position": position,
                "quality_component": entry["quality_component"],
                "capacity_component": entry["capacity_component"],
                "mode_component": entry["mode_component"],
                "continuity_component": entry["continuity_component"],
                "probation_penalty_applied": entry["probation_penalty_applied"],
                "remaining_slots_at_offer": entry["remaining_slots_at_offer"],
                "offer_expires_at": expires_at,
                "offer_status": "SELECTED" if position == 1 else "PROPOSED",
                "reason_code": None,
            }
        )
        db.match_offers[offer["id"]] = offer
        if position == 1:
            selected_provider = entry["provider"]

    reservation["fulfillment_status"] = "OFFERED"
    reservation["unfulfilled_reason_code"] = None
    reservation["matched_provider_id"] = selected_provider["id"]
    reservation["required_seats"] = required_seats_for(
        selected_provider["care_mode"], reservation["dependent_count"]
    )
    touch(reservation)
    return True


def selected_offer(reservation_id):
    for offer in db.match_offers.values():
        if offer["reservation_id"] == reservation_id and offer["offer_status"] == "SELECTED":
            return offer
    return None
