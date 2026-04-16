import math
from db import (
    boarding_reservations,
    boarding_matches,
    animals,
    parse_iso,
)


def compute_planned_duration_days(check_in, check_out):
    ci = parse_iso(check_in)
    co = parse_iso(check_out)
    if ci is None or co is None:
        return None
    delta_seconds = (co - ci).total_seconds()
    if delta_seconds <= 0:
        return 0
    return int(math.ceil(delta_seconds / 86400.0))


def compute_actual_duration_days(actual_in, actual_out):
    ci = parse_iso(actual_in)
    co = parse_iso(actual_out)
    if ci is None or co is None:
        return None
    delta_seconds = (co - ci).total_seconds()
    if delta_seconds <= 0:
        return 1  # minimum one day if same timestamp
    return int(math.ceil(delta_seconds / 86400.0))


def compute_boarding_zone(animal):
    if animal.get("temperament") == "AGGRESSIVE":
        return "ISOLATION"
    if animal.get("temperament") == "ENERGETIC":
        return "ACTIVE"
    if animal.get("species") in ("CAT", "BIRD", "RABBIT"):
        return "SMALL_ANIMAL"
    return "GENERAL"


def compute_compatibility(animal, shelter_id):
    SPECIES_MISMATCH_PENALTY = 10
    AGGRESSIVE_PENALTY = 25
    TEMPERAMENT_CLASH_PENALTY = 15
    SPECIAL_NEEDS_PENALTY = 5

    penalty = 0
    conflict_flags = []

    # Other animals currently BOARDING at same shelter (have CHECKED_IN reservations)
    other_animals = []
    for r in boarding_reservations.values():
        if r["shelter_id"] != shelter_id:
            continue
        if r["status"] != "CHECKED_IN":
            continue
        if r["animal_id"] == animal["id"]:
            continue
        other = animals.get(r["animal_id"])
        if other:
            other_animals.append(other)

    for other in other_animals:
        if other.get("species") != animal.get("species"):
            penalty += SPECIES_MISMATCH_PENALTY
            if "SPECIES_MISMATCH" not in conflict_flags:
                conflict_flags.append("SPECIES_MISMATCH")
        if other.get("temperament") == "AGGRESSIVE" or animal.get("temperament") == "AGGRESSIVE":
            penalty += AGGRESSIVE_PENALTY
            flag = "AGGRESSIVE_PRESENT"
            if flag not in conflict_flags:
                conflict_flags.append(flag)
        if (other.get("temperament") == "ENERGETIC" and animal.get("temperament") == "CALM") or \
                (other.get("temperament") == "CALM" and animal.get("temperament") == "ENERGETIC"):
            penalty += TEMPERAMENT_CLASH_PENALTY
            flag = "AGGRESSIVE_NEAR_CALM"
            if flag not in conflict_flags:
                conflict_flags.append(flag)

    penalty += SPECIAL_NEEDS_PENALTY * len(animal.get("special_needs", []))

    score = max(0, 100 - penalty)
    return score, conflict_flags


def serialize_reservation(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "shelter_id": r["shelter_id"],
        "animal_id": r["animal_id"],
        "owner_name": r["owner_name"],
        "owner_contact": r["owner_contact"],
        "check_in_date": r["check_in_date"],
        "check_out_date": r["check_out_date"],
        "actual_check_in": r.get("actual_check_in"),
        "actual_check_out": r.get("actual_check_out"),
        "planned_duration_days": compute_planned_duration_days(r["check_in_date"], r["check_out_date"]),
        "actual_duration_days": (compute_actual_duration_days(r["actual_check_in"], r["actual_check_out"])
                                  if r.get("actual_check_in") and r.get("actual_check_out") else None),
        "special_instructions": r.get("special_instructions"),
        "boarding_match_id": r.get("boarding_match_id"),
        "fee_invoice_id": r.get("fee_invoice_id"),
        "status": r["status"],
    }


def serialize_boarding_match(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "reservation_id": m["reservation_id"],
        "animal_id": m["animal_id"],
        "shelter_id": m["shelter_id"],
        "compatibility_score": m["compatibility_score"],
        "boarding_zone": m["boarding_zone"],
        "conflict_flags": m.get("conflict_flags", []),
        "voided_at": m.get("voided_at"),
    }


def reservations_overlap(ci1, co1, ci2, co2):
    a_start = parse_iso(ci1)
    a_end = parse_iso(co1)
    b_start = parse_iso(ci2)
    b_end = parse_iso(co2)
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    # [start, end) half-open intervals
    return a_start < b_end and b_start < a_end
