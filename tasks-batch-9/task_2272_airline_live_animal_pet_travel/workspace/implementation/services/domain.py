"""Derived-field recomputation, cascades and shared domain queries."""
from datetime import timedelta

from db import format_instant, parse_iso, sorted_rows, store, touch
from errors import ApiError
from services import calc

ROUTINGS = ("CABIN", "CHECKED", "CARGO")
BOOKED_FIELD = {
    "CABIN": "booked_cabin_count",
    "CHECKED": "booked_checked_count",
    "CARGO": "booked_cargo_count",
}
LIMIT_FIELD = {
    "CABIN": "cabin_animal_limit",
    "CHECKED": "checked_animal_limit",
    "CARGO": "cargo_animal_limit",
}
ACTIVE_SLOT_STATUSES = ("RESERVED", "ACCEPTED")


# --------------------------------------------------------------------------
# queries
# --------------------------------------------------------------------------
def animals_of_reservation(reservation):
    return [a for a in sorted_rows(store.animals)
            if a["reservation_id"] == reservation["id"]]


def segments_of_animal(animal):
    return sorted([s for s in store.segments.values()
                   if s["animal_record_id"] == animal["id"]],
                  key=lambda s: s["sequence_index"])


def segments_of_leg(leg):
    return [s for s in sorted_rows(store.segments) if s["flight_leg_id"] == leg["id"]]


def segments_of_reservation(reservation):
    ids = set(a["id"] for a in animals_of_reservation(reservation))
    return [s for s in sorted_rows(store.segments) if s["animal_record_id"] in ids]


def documents_of_animal(animal):
    return [d for d in sorted_rows(store.docs) if d["animal_record_id"] == animal["id"]]


def allocations_of_animal(animal):
    return [a for a in sorted_rows(store.allocations)
            if a["animal_record_id"] == animal["id"]]


def welfare_checks_of_segment(segment):
    return [w for w in sorted_rows(store.welfare_checks)
            if w["segment_assignment_id"] == segment["id"]]


def reservation_of_animal(animal):
    return store.reservations[animal["reservation_id"]]


def animal_of_segment(segment):
    return store.animals[segment["animal_record_id"]]


def reservation_of_segment(segment):
    return reservation_of_animal(animal_of_segment(segment))


def leg_of_segment(segment):
    return store.legs[segment["flight_leg_id"]]


def final_segment(animal):
    """Highest sequence_index slot that is not RELEASED."""
    live = [s for s in segments_of_animal(animal) if s["status"] != "RELEASED"]
    if not live:
        return None
    return max(live, key=lambda s: s["sequence_index"])


def first_segment(animal):
    for seg in segments_of_animal(animal):
        if seg["sequence_index"] == 1 and seg["status"] != "RELEASED":
            return seg
    return None


def is_snub_nosed(animal):
    breed = (animal["breed_name"] or "").lower()
    for row in store.breeds.values():
        if row["species_profile_id"] != animal["species_profile_id"]:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["restriction_type"] != "SNUB_NOSED":
            continue
        if (row["breed_name"] or "").lower() == breed:
            return True
    return False


def active_breed_restrictions(animal):
    breed = (animal["breed_name"] or "").lower()
    return [r for r in sorted_rows(store.breeds)
            if r["species_profile_id"] == animal["species_profile_id"]
            and r["status"] == "ACTIVE"
            and (r["breed_name"] or "").lower() == breed]


# --------------------------------------------------------------------------
# derived counters
# --------------------------------------------------------------------------
def recompute_breed_restriction_count(species):
    count = len([r for r in store.breeds.values()
                 if r["species_profile_id"] == species["id"] and r["status"] == "ACTIVE"])
    species["breed_restriction_count"] = count


def recompute_reserved_bay_count(station):
    total = 0
    for alloc in store.allocations.values():
        if alloc["station_id"] == station["id"] and alloc["status"] in ("RESERVED", "OCCUPIED"):
            total += alloc["bay_count"]
    station["reserved_bay_count"] = total


def recompute_animal_count(reservation):
    """Animal records attached to the reservation whose status is not DENIED."""
    reservation["animal_count"] = len([a for a in animals_of_reservation(reservation)
                                       if a["status"] != "DENIED"])


def recompute_completed_welfare_checks(segment):
    segment["completed_welfare_check_count"] = len(welfare_checks_of_segment(segment))


def block_minutes(departure_iso, arrival_iso):
    delta = parse_iso(arrival_iso) - parse_iso(departure_iso)
    return int(delta.total_seconds() // 60)


# --------------------------------------------------------------------------
# leg posture / embargo
# --------------------------------------------------------------------------
def derive_posture(leg):
    if leg["status"] == "CANCELLED":
        return "CLOSED"
    if leg["governing_embargo_rule_id"] is not None:
        return "EMBARGOED"
    if leg["status"] in ("DEPARTED", "ARRIVED"):
        return "CLOSED"
    for routing in ROUTINGS:
        limit = leg[LIMIT_FIELD[routing]]
        booked = leg[BOOKED_FIELD[routing]]
        if limit > 0 and booked * calc.RESTRICTED_LOAD_NUMERATOR >= \
                limit * calc.RESTRICTED_LOAD_DENOMINATOR:
            return "RESTRICTED"
    return "OPEN"


def reconcile_leg(leg, force_touch=False):
    """Recompute booked counters and posture; a change is a mutation."""
    before = (leg["booked_cabin_count"], leg["booked_checked_count"],
              leg["booked_cargo_count"], leg["posture"])
    counts = {"CABIN": 0, "CHECKED": 0, "CARGO": 0}
    for seg in store.segments.values():
        if seg["flight_leg_id"] == leg["id"] and seg["status"] in ACTIVE_SLOT_STATUSES:
            counts[seg["routing_type"]] += 1
    for routing in ROUTINGS:
        leg[BOOKED_FIELD[routing]] = counts[routing]
    leg["posture"] = derive_posture(leg)
    after = (leg["booked_cabin_count"], leg["booked_checked_count"],
             leg["booked_cargo_count"], leg["posture"])
    if force_touch or before != after:
        touch(leg)


def select_governing_rule(leg):
    """embargo_determination without any write: returns the rule id or None."""
    month_day = parse_iso(leg["scheduled_departure_utc"]).strftime("%m-%d")
    candidates = []
    for rule in store.embargo_rules.values():
        if rule["status"] != "ACTIVE":
            continue
        if rule["direction"] == "ORIGIN":
            if rule["station_id"] != leg["origin_station_id"]:
                continue
        else:
            if rule["station_id"] != leg["destination_station_id"]:
                continue
        if not calc.season_contains(month_day, rule["season_start_month_day"],
                                    rule["season_end_month_day"]):
            continue
        breach = (calc.dec(leg["forecast_high_c"]) >= calc.dec(rule["forecast_high_limit_c"])
                  or calc.dec(leg["forecast_low_c"]) <= calc.dec(rule["forecast_low_limit_c"]))
        if breach:
            candidates.append(rule)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (calc.dec(r["forecast_high_limit_c"]),
                                   r["created_at"], r["_seq"]))
    return candidates[0]["id"]


def embargo_determination(leg):
    leg["governing_embargo_rule_id"] = select_governing_rule(leg)
    reconcile_leg(leg)


def release_embargoed_slots(leg):
    """Release RESERVED slots whose routing the governing rule embargoes."""
    if leg["posture"] != "EMBARGOED" or leg["governing_embargo_rule_id"] is None:
        return
    rule = store.embargo_rules.get(leg["governing_embargo_rule_id"])
    if rule is None:
        return
    routings = rule["applies_to_routings"]
    for seg in segments_of_leg(leg):
        if seg["status"] == "RESERVED" and seg["routing_type"] in routings:
            release_segment(seg)


# --------------------------------------------------------------------------
# money
# --------------------------------------------------------------------------
def run_charge_assembly(reservation):
    fee_total = sum(s["segment_fee_amount"] for s in segments_of_reservation(reservation))
    subtotal, tier, discount, net = calc.charge_assembly(
        fee_total, reservation["irops_fee_total"], reservation["refunded_amount"])
    before = (reservation["subtotal_amount"], reservation["loyalty_tier_pct"],
              reservation["loyalty_discount_amount"], reservation["net_payable_amount"])
    reservation["subtotal_amount"] = subtotal
    reservation["loyalty_tier_pct"] = calc.tier_pct_out(tier)
    reservation["loyalty_discount_amount"] = discount
    reservation["net_payable_amount"] = net
    after = (reservation["subtotal_amount"], reservation["loyalty_tier_pct"],
             reservation["loyalty_discount_amount"], reservation["net_payable_amount"])
    if before != after:
        touch(reservation)


def apply_provisional_fees(animal):
    """Screening basis: declared_weight_kg rewrites every RESERVED slot."""
    container = store.containers[animal["container_model_id"]]
    chargeable = calc.chargeable_weight_kg(animal["declared_weight_kg"], container)
    if animal["chargeable_weight_kg"] != chargeable:
        animal["chargeable_weight_kg"] = chargeable
    snub = is_snub_nosed(animal)
    for seg in segments_of_animal(animal):
        if seg["status"] != "RESERVED":
            continue
        leg = leg_of_segment(seg)
        fee = calc.animal_travel_fee(chargeable, seg["routing_type"], snub,
                                     leg["block_minutes"], animal["animal_kind"])
        if seg["segment_fee_amount"] != fee or \
                seg["fee_variant"] != "PROVISIONAL_AT_RESERVATION":
            seg["segment_fee_amount"] = fee
            seg["fee_variant"] = "PROVISIONAL_AT_RESERVATION"
            touch(seg)
    return chargeable


def provisional_fee_for_segment(animal, routing_type, leg):
    container = store.containers[animal["container_model_id"]]
    chargeable = calc.chargeable_weight_kg(animal["declared_weight_kg"], container)
    return calc.animal_travel_fee(chargeable, routing_type, is_snub_nosed(animal),
                                  leg["block_minutes"], animal["animal_kind"])


def apply_final_fee(animal, segment):
    """Acceptance basis: measured_weight_kg rewrites only the accepted slot."""
    container = store.containers[animal["container_model_id"]]
    chargeable = calc.chargeable_weight_kg(animal["measured_weight_kg"], container)
    if animal["chargeable_weight_kg"] != chargeable:
        animal["chargeable_weight_kg"] = chargeable
        touch(animal)
    leg = leg_of_segment(segment)
    segment["segment_fee_amount"] = calc.animal_travel_fee(
        chargeable, segment["routing_type"], is_snub_nosed(animal),
        leg["block_minutes"], animal["animal_kind"])
    segment["fee_variant"] = "FINAL_AT_ACCEPTANCE"


# --------------------------------------------------------------------------
# container compliance
# --------------------------------------------------------------------------
def evaluate_container(animal):
    reservation = reservation_of_animal(animal)
    container = store.containers[animal["container_model_id"]]
    species = store.species[animal["species_profile_id"]]
    chargeable = calc.chargeable_weight_kg(animal["declared_weight_kg"], container)
    gross = calc.gross_weight_kg(animal["declared_weight_kg"], container)
    codes = calc.container_deficiency_codes(animal, container, species,
                                            reservation["routing_type"], chargeable, gross)
    animal["chargeable_weight_kg"] = chargeable
    animal["deficiency_codes"] = codes
    animal["container_compliance_state"] = "COMPLIANT" if not codes else "DEFICIENT"
    return codes


# --------------------------------------------------------------------------
# connection welfare window
# --------------------------------------------------------------------------
def connection_window(animal, sequence_index, routing_type, leg):
    """Returns (connection_minutes, required_welfare_check_count)."""
    if sequence_index == 1:
        return None, 0
    previous = None
    for seg in segments_of_animal(animal):
        if seg["sequence_index"] == sequence_index - 1 and seg["status"] != "RELEASED":
            previous = seg
            break
    if previous is None:
        return None, 0
    previous_leg = leg_of_segment(previous)
    delta = parse_iso(leg["scheduled_departure_utc"]) - \
        parse_iso(previous_leg["scheduled_arrival_utc"])
    minutes = int(delta.total_seconds() // 60)
    return minutes, calc.required_welfare_checks(max(minutes, 0))


def refresh_connection_window(segment):
    animal = animal_of_segment(segment)
    leg = leg_of_segment(segment)
    minutes, required = connection_window(animal, segment["sequence_index"],
                                          segment["routing_type"], leg)
    changed = (segment["connection_minutes"] != minutes
               or segment["required_welfare_check_count"] != required)
    segment["connection_minutes"] = minutes
    segment["required_welfare_check_count"] = required
    if changed:
        touch(segment)
    return minutes


def downstream_segments(leg, statuses):
    """Slots that connect off a slot on this leg (same animal, next index)."""
    out = []
    for seg in segments_of_leg(leg):
        animal = animal_of_segment(seg)
        for candidate in segments_of_animal(animal):
            if candidate["sequence_index"] == seg["sequence_index"] + 1 \
                    and candidate["status"] in statuses:
                if candidate["id"] not in [row["id"] for row in out]:
                    out.append(candidate)
    return out


# --------------------------------------------------------------------------
# kennel capacity
# --------------------------------------------------------------------------
def effective_end(allocation_end):
    return allocation_end + timedelta(minutes=calc.KENNEL_SANITATION_BUFFER_MINUTES)


def projected_peak(station, bay_count, start, end):
    candidate_end = effective_end(end)
    total = bay_count
    for alloc in store.allocations.values():
        if alloc["station_id"] != station["id"]:
            continue
        if alloc["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        row_start = parse_iso(alloc["occupancy_start_utc"])
        row_end = effective_end(parse_iso(alloc["occupancy_end_utc"]))
        if row_start < candidate_end and row_end > start:
            total += alloc["bay_count"]
    return total


# --------------------------------------------------------------------------
# document requirements
# --------------------------------------------------------------------------
def destination_requirements_for(animal):
    """Returns (requirements, arrival_datetime) for the animal's final slot."""
    seg = final_segment(animal)
    if seg is None:
        return [], None
    leg = leg_of_segment(seg)
    country = store.stations[leg["destination_station_id"]]["country_code"]
    arrival = parse_iso(leg["scheduled_arrival_utc"])
    reqs = [r for r in sorted_rows(store.dest_reqs)
            if r["species_profile_id"] == animal["species_profile_id"]
            and r["destination_country_code"] == country
            and r["status"] == "ACTIVE"
            and r["mandatory"]]
    return reqs, arrival


def verified_docs_of_type(animal, document_type):
    return [d for d in documents_of_animal(animal)
            if d["document_type"] == document_type and d["status"] == "VERIFIED"]


def whole_days_between(issued_at, arrival):
    return int((arrival - issued_at).total_seconds() // 86400)


def check_documents(animals):
    """Ladder 33 then 34 across the whole set; returns (error_id, backing_docs)."""
    plans = []
    for animal in animals:
        reqs, arrival = destination_requirements_for(animal)
        if not reqs:
            continue
        plans.append((animal, reqs, arrival))
    # 33 - every mandatory requirement backed by a VERIFIED document
    for animal, reqs, arrival in plans:
        for req in reqs:
            if not verified_docs_of_type(animal, req["document_type"]):
                return "ERR_REQUIRED_DOCUMENT_MISSING", []
    # 34 - the backing document must not be too old for the arrival instant
    backing = []
    for animal, reqs, arrival in plans:
        for req in reqs:
            fresh = [d for d in verified_docs_of_type(animal, req["document_type"])
                     if whole_days_between(parse_iso(d["issued_at"]), arrival)
                     <= req["max_age_days_at_arrival"]]
            if not fresh:
                return "ERR_DOCUMENT_STALE_FOR_DESTINATION", []
            for doc in fresh:
                if doc["id"] not in [d["id"] for d in backing]:
                    backing.append(doc)
    return None, backing


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------
def _recompute_booking_status_after_release(reservation):
    if reservation["booking_status"] not in ("PENDING", "CONFIRMED", "HOLD_PARTIAL",
                                             "REBOOK_REQUIRED"):
        return
    retains = any(s["status"] in ACTIVE_SLOT_STATUSES
                  for s in segments_of_reservation(reservation))
    new_status = "HOLD_PARTIAL" if retains else "REBOOK_REQUIRED"
    if reservation["booking_status"] != new_status:
        reservation["booking_status"] = new_status
        touch(reservation)


def release_segment(segment, refund=True, recompute_booking=True):
    segment["status"] = "RELEASED"
    touch(segment)
    reconcile_leg(leg_of_segment(segment), force_touch=True)
    reservation = reservation_of_segment(segment)
    if refund:
        reservation["refunded_amount"] += segment["segment_fee_amount"]
        touch(reservation)
    if recompute_booking:
        _recompute_booking_status_after_release(reservation)
    run_charge_assembly(reservation)


def offload_segment(segment, refund=True, mark_interrupted=True):
    segment["status"] = "OFFLOADED"
    touch(segment)
    reconcile_leg(leg_of_segment(segment), force_touch=True)
    reservation = reservation_of_segment(segment)
    if refund:
        reservation["refunded_amount"] += segment["segment_fee_amount"]
        touch(reservation)
    if mark_interrupted and reservation["booking_status"] == "IN_TRANSIT":
        reservation["booking_status"] = "INTERRUPTED"
        touch(reservation)
    run_charge_assembly(reservation)


def release_allocation(allocation):
    allocation["status"] = "RELEASED"
    touch(allocation)
    station = store.stations[allocation["station_id"]]
    recompute_reserved_bay_count(station)
    touch(station)


def cascade_animal_removal(animal, terminal_status):
    """Death / loss cascade: animal terminal, slots freed, kennels released."""
    reservation = reservation_of_animal(animal)
    was_in_transit = reservation["booking_status"] == "IN_TRANSIT"
    animal["status"] = terminal_status
    touch(animal)
    for seg in segments_of_animal(animal):
        if seg["status"] == "RESERVED":
            release_segment(seg, refund=True, recompute_booking=False)
        elif seg["status"] == "ACCEPTED":
            offload_segment(seg, refund=True, mark_interrupted=False)
    for alloc in allocations_of_animal(animal):
        if alloc["status"] in ("RESERVED", "OCCUPIED"):
            release_allocation(alloc)
    return reservation, was_in_transit


def require(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)


def clock_iso():
    return format_instant(store.clock)
