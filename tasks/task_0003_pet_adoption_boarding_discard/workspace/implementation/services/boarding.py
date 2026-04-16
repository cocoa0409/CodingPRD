"""Boarding compatibility scoring and zone assignment."""

import db
from db import new_id, now_iso


SPECIES_MISMATCH_PENALTY = 10
AGGRESSIVE_PENALTY = 25
TEMPERAMENT_CLASH_PENALTY = 15
SPECIAL_NEEDS_PENALTY = 5


def create_boarding_match(reservation_id, animal_id, shelter_id):
    """Create a BoardingMatch with compatibility scoring."""
    animal = db.animals[animal_id]

    # Find concurrent checked-in animals at the same shelter
    concurrent = []
    for res in db.boarding_reservations.values():
        if (res["shelter_id"] == shelter_id
                and res["status"] == "CHECKED_IN"
                and res["animal_id"] != animal_id):
            other = db.animals.get(res["animal_id"])
            if other:
                concurrent.append(other)

    base_score = 100
    penalties = 0
    conflict_flags = []

    for other in concurrent:
        if other["species"] != animal["species"]:
            penalties += SPECIES_MISMATCH_PENALTY
            if "SPECIES_MISMATCH" not in conflict_flags:
                conflict_flags.append("SPECIES_MISMATCH")
        if other["temperament"] == "AGGRESSIVE" or animal["temperament"] == "AGGRESSIVE":
            penalties += AGGRESSIVE_PENALTY
            if animal["temperament"] == "AGGRESSIVE" and other["temperament"] == "CALM":
                if "AGGRESSIVE_NEAR_CALM" not in conflict_flags:
                    conflict_flags.append("AGGRESSIVE_NEAR_CALM")
            if other["temperament"] == "AGGRESSIVE" and animal["temperament"] == "CALM":
                if "AGGRESSIVE_NEAR_CALM" not in conflict_flags:
                    conflict_flags.append("AGGRESSIVE_NEAR_CALM")
        if ((other["temperament"] == "ENERGETIC" and animal["temperament"] == "CALM")
                or (animal["temperament"] == "ENERGETIC" and other["temperament"] == "CALM")):
            penalties += TEMPERAMENT_CLASH_PENALTY

    special_needs = animal.get("special_needs", [])
    penalties += SPECIAL_NEEDS_PENALTY * len(special_needs)

    compatibility_score = max(0, base_score - penalties)

    # Zone assignment
    if animal["temperament"] == "AGGRESSIVE":
        boarding_zone = "ISOLATION"
    elif animal["temperament"] == "ENERGETIC":
        boarding_zone = "ACTIVE"
    elif animal["species"] in ("CAT", "BIRD", "RABBIT"):
        boarding_zone = "SMALL_ANIMAL"
    else:
        boarding_zone = "GENERAL"

    match = {
        "id": new_id(),
        "created_at": now_iso(),
        "reservation_id": reservation_id,
        "animal_id": animal_id,
        "shelter_id": shelter_id,
        "compatibility_score": compatibility_score,
        "boarding_zone": boarding_zone,
        "conflict_flags": conflict_flags,
    }
    db.boarding_matches[match["id"]] = match
    return match


def check_date_overlap(animal_id, check_in_str, check_out_str, exclude_reservation_id=None):
    """Check if there's an overlapping CONFIRMED or CHECKED_IN reservation for this animal."""
    from services.fees import _parse_dt
    ci = _parse_dt(check_in_str)
    co = _parse_dt(check_out_str)

    for res in db.boarding_reservations.values():
        if res["animal_id"] != animal_id:
            continue
        if res["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if exclude_reservation_id and res["id"] == exclude_reservation_id:
            continue
        existing_ci = _parse_dt(res["check_in_date"])
        existing_co = _parse_dt(res["check_out_date"])
        # Overlap check
        if ci < existing_co and co > existing_ci:
            return True
    return False
