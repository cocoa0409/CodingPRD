"""Vehicle-block derived state, temporal exclusions and fleet-sizing ceiling."""
import calculations as calc
import clock
import db

ACTIVE_ASSIGNMENT_STATES = ("OFFERED", "ACCEPTED", "ONBOARD")


def assignments_of(block_id):
    return db.by_created_at(
        [a for a in db.pool_assignments.values() if a["block_id"] == block_id])


def active_assignments(block_id):
    return [a for a in assignments_of(block_id)
            if a["state"] in ACTIVE_ASSIGNMENT_STATES]


def _stop_indexes(assignment):
    trip = db.trip_requests.get(assignment["trip_request_id"])
    if trip is None:
        return []
    indexes = []
    for key in ("origin_stop_id", "destination_stop_id"):
        stop = db.virtual_stops.get(trip.get(key))
        if stop is not None:
            indexes.append(stop["corridor_index"])
    return indexes


def recompute_seq_pickup(block_id):
    """1-based pickup order along the corridor over the active manifest."""
    active = active_assignments(block_id)

    def key(assignment):
        trip = db.trip_requests.get(assignment["trip_request_id"]) or {}
        stop = db.virtual_stops.get(trip.get("origin_stop_id")) or {}
        return (stop.get("corridor_index", 0), assignment["created_at"],
                assignment["_seq"])

    for position, assignment in enumerate(sorted(active, key=key), start=1):
        assignment["seq_pickup"] = position


def recompute_block(block):
    """Recompute the block's committed capacity and corridor envelope."""
    assignments = assignments_of(block["id"])
    active = [a for a in assignments if a["state"] in ACTIVE_ASSIGNMENT_STATES]

    seats = sum(a["seats_held"] for a in active)
    wav = sum(a["wav_positions_held"] for a in active)
    indexes = []
    for assignment in active:
        indexes.extend(_stop_indexes(assignment))
    index_min = min(indexes) if indexes else None
    index_max = max(indexes) if indexes else None
    boardings = sum(a["seats_held"] for a in assignments if a["state"] == "COMPLETED")

    changed = (
        block["seats_committed"] != seats
        or block["wav_positions_committed"] != wav
        or block["committed_index_min"] != index_min
        or block["committed_index_max"] != index_max
        or block["boardings_count"] != boardings
    )
    block["seats_committed"] = seats
    block["wav_positions_committed"] = wav
    block["committed_index_min"] = index_min
    block["committed_index_max"] = index_max
    block["boardings_count"] = boardings
    recompute_seq_pickup(block["id"])
    if changed:
        db.touch(block)
    return changed


def window(block):
    return clock.parse_dt(block["start_utc"]), clock.parse_dt(block["end_utc"])


# --------------------------------------------------------------------------
# temporal exclusions on create (PRD Section 3.4)
# --------------------------------------------------------------------------

LIVE_BLOCK_STATES = ("SCHEDULED", "OPEN")


def vehicle_occupied(vehicle_id, new_start, new_end):
    """Half-open occupation; exact adjacency is allowed, no buffer applied."""
    for block in db.vehicle_blocks.values():
        if block["vehicle_id"] != vehicle_id:
            continue
        if block["state"] not in LIVE_BLOCK_STATES:
            continue
        existing_start, existing_end = window(block)
        if existing_start < new_end and new_start < existing_end:
            return True
    return False


def driver_rest_violated(driver_id, new_start, new_end):
    """Shifted-window test; exact adjacency is rejected, a 30-minute gap is not."""
    buffer_minutes = calc.DRIVER_REST_BUFFER_MINUTES
    for block in db.vehicle_blocks.values():
        if block["driver_id"] != driver_id:
            continue
        if block["state"] not in LIVE_BLOCK_STATES:
            continue
        existing_start, existing_end = window(block)
        shifted_existing_start = clock.plus_minutes(existing_start, -buffer_minutes)
        shifted_new_start = clock.plus_minutes(new_start, -buffer_minutes)
        if shifted_existing_start < new_end and shifted_new_start < existing_end:
            return True
    return False


# --------------------------------------------------------------------------
# peak-surge fleet sizing ceiling (PRD Section 3.4)
# --------------------------------------------------------------------------

def fleet_size_exceeded(block):
    block_start, block_end = window(block)
    forecasts = []
    for forecast in db.demand_forecasts.values():
        if forecast["zone_id"] != block["zone_id"]:
            continue
        if forecast["state"] != "PUBLISHED":
            continue
        f_start = clock.parse_dt(forecast["window_start_utc"])
        f_end = clock.parse_dt(forecast["window_end_utc"])
        if calc.overlaps_half_open(f_start, f_end, block_start, block_end):
            forecasts.append((forecast, f_start, f_end))
    if not forecasts:
        return False

    for forecast, f_start, f_end in forecasts:
        count = 0
        for other in db.vehicle_blocks.values():
            if other["zone_id"] != forecast["zone_id"]:
                continue
            if other["block_type"] != block["block_type"]:
                continue
            # count the world as it would stand after this open succeeded
            state = "OPEN" if other["id"] == block["id"] else other["state"]
            if state != "OPEN":
                continue
            o_start, o_end = window(other)
            if not calc.overlaps_half_open(o_start, o_end, f_start, f_end):
                continue
            count += 1
        ceiling = (forecast["required_base_blocks"] if block["block_type"] == "BASE"
                   else forecast["required_surge_blocks"])
        if count > ceiling:
            return True
    return False
