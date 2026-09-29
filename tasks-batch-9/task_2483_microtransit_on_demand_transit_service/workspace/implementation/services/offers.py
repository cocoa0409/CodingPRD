"""Offer creation, the candidate predicate and the ranking expression."""
import calculations as calc
import clock
import db
from services import blocks as block_service
from services import fares


def stop_indexes(trip):
    origin = db.virtual_stops[trip["origin_stop_id"]]
    destination = db.virtual_stops[trip["destination_stop_id"]]
    return origin["corridor_index"], destination["corridor_index"]


def geometry(trip, block):
    origin_ix, dest_ix = stop_indexes(trip)
    baseline = calc.baseline_direct_minutes(origin_ix, dest_ix)
    detour = calc.projected_detour_minutes(block, origin_ix, dest_ix)
    return baseline, detour


def promised_pickup(trip):
    """max(requested_pickup_utc, logical clock now), echoing the winning string."""
    requested_raw = trip["requested_pickup_utc"]
    requested_dt = clock.parse_dt(requested_raw)
    now_dt = clock.now()
    if requested_dt >= now_dt:
        return requested_raw, requested_dt
    return clock.now_raw(), now_dt


def curb_bucket_count(origin_stop_id, prospective_pickup_dt):
    """Non-terminal offers already holding the same quarter-hour curb bucket."""
    bucket = calc.epoch_minute_bucket(prospective_pickup_dt)
    count = 0
    for assignment in db.pool_assignments.values():
        if assignment["state"] not in block_service.ACTIVE_ASSIGNMENT_STATES:
            continue
        trip = db.trip_requests.get(assignment["trip_request_id"])
        if trip is None or trip["origin_stop_id"] != origin_stop_id:
            continue
        promised = trip.get("promised_pickup_utc")
        if not promised:
            continue
        if calc.epoch_minute_bucket(clock.parse_dt(promised)) == bucket:
            count += 1
    return count


# --------------------------------------------------------------------------
# candidate set and ranking (SCAFFOLD pool_match_selection)
# --------------------------------------------------------------------------

def candidates(trip):
    zone = db.service_zones[trip["zone_id"]]
    requested_dt = clock.parse_dt(trip["requested_pickup_utc"])
    origin_ix, dest_ix = stop_indexes(trip)
    baseline = calc.baseline_direct_minutes(origin_ix, dest_ix)
    allowance = calc.detour_allowance_minutes(zone, baseline)
    prospective_raw, prospective_dt = promised_pickup(trip)
    curb_used = curb_bucket_count(trip["origin_stop_id"], prospective_dt)

    found = []
    for block in db.vehicle_blocks.values():
        if block["zone_id"] != trip["zone_id"]:
            continue
        if block["state"] != "OPEN":
            continue
        vehicle = db.vehicles.get(block["vehicle_id"])
        driver = db.drivers.get(block["driver_id"])
        if vehicle is None or driver is None:
            continue
        if vehicle["status"] != "AVAILABLE" or driver["status"] != "ACTIVE":
            continue
        start_dt, end_dt = block_service.window(block)
        if not (start_dt <= requested_dt < end_dt):
            continue
        if block["seats_committed"] + trip["party_size"] > vehicle["seat_capacity"]:
            continue
        if trip["wav_required"]:
            headroom = vehicle["wav_positions"] - block["wav_positions_committed"]
            if headroom < 1 or not driver["wav_certified"]:
                continue
        detour = calc.projected_detour_minutes(block, origin_ix, dest_ix)
        if detour > allowance:
            continue
        if curb_used >= zone["curb_capacity_per_bucket"]:
            continue
        found.append((block, vehicle, detour))
    return found


def select_winner(trip, pool):
    """Lowest match_score wins; ties break on start_utc ASC then created_at ASC."""
    scored = []
    for block, vehicle, detour in pool:
        score = calc.match_score(trip, block, vehicle, detour)
        start_dt, _ = block_service.window(block)
        scored.append((score, start_dt, block["created_at"], block["_seq"],
                       block, score))
    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    winner = scored[0]
    return winner[4], winner[5]


# --------------------------------------------------------------------------
# the shared offer-creation side-effect set
# --------------------------------------------------------------------------

def create_offer(trip, block, offer_origin, score):
    zone = db.service_zones[trip["zone_id"]]
    rider = db.riders[trip["rider_id"]]
    baseline, detour = geometry(trip, block)
    pickup_raw, pickup_dt = promised_pickup(trip)

    assignment = db.base_record()
    assignment.update({
        "block_id": block["id"],
        "trip_request_id": trip["id"],
        "seats_held": trip["party_size"],
        "wav_positions_held": 1 if trip["wav_required"] else 0,
        "seq_pickup": None,
        "baseline_direct_minutes": baseline,
        "projected_detour_minutes": detour,
        "match_score": score,
        "offer_origin": offer_origin,
        "state": "OFFERED",
    })
    db.pool_assignments.add(assignment)

    trip["assigned_block_id"] = block["id"]
    trip["match_attempt_count"] += 1
    trip["baseline_direct_minutes"] = baseline
    trip["projected_detour_minutes"] = detour
    trip["promised_pickup_utc"] = pickup_raw
    dropoff_dt = clock.plus_minutes(pickup_dt, baseline + detour)
    trip["promised_dropoff_utc"] = clock.fmt_like(dropoff_dt, pickup_raw)
    trip["status"] = "OFFERED"
    if trip["fare_status"] == "UNPRICED":
        trip["fare_status"] = "QUOTED"
        trip["quoted_fare_cents"] = fares.quote(trip, zone, rider, baseline)
    db.touch(trip)

    block_service.recompute_block(block)
    return assignment
