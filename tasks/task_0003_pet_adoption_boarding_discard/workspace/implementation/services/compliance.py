"""Compliance hold and scoring logic."""

from decimal import Decimal, ROUND_HALF_UP
import db
from db import now_iso


HOLD_PENALTY_POINTS = 5


def has_active_high_critical_hold(animal_id):
    """Check if animal has any ACTIVE hold with severity HIGH or CRITICAL."""
    for hold in db.compliance_holds.values():
        if (hold["animal_id"] == animal_id
                and hold["status"] == "ACTIVE"
                and hold["severity"] in ("HIGH", "CRITICAL")):
            return True
    return False


def has_active_critical_hold_in_shelter(shelter_id):
    """Check if any animal in shelter has ACTIVE CRITICAL hold."""
    shelter_animal_ids = {
        a["id"] for a in db.animals.values() if a["shelter_id"] == shelter_id
    }
    for hold in db.compliance_holds.values():
        if (hold["animal_id"] in shelter_animal_ids
                and hold["status"] == "ACTIVE"
                and hold["severity"] == "CRITICAL"):
            return True
    return False


def recompute_animal_eligibility(animal_id):
    """Recompute adoption_eligible on an animal."""
    animal = db.animals.get(animal_id)
    if not animal:
        return
    animal["adoption_eligible"] = (
        animal.get("vaccination_compliant", False)
        and animal["status"] == "AVAILABLE"
        and not has_active_high_critical_hold(animal_id)
    )


def recompute_boarding_compatible_tags(animal_id):
    """Recompute boarding_compatible_tags from species, temperament, special_needs."""
    animal = db.animals.get(animal_id)
    if not animal:
        return
    tags = [animal["species"], animal["temperament"]]
    tags.extend(animal.get("special_needs", []))
    animal["boarding_compatible_tags"] = tags


def recompute_shelter_compliance_score(shelter_id):
    """Recompute shelter compliance_score."""
    shelter = db.shelters.get(shelter_id)
    if not shelter:
        return

    animals_in_shelter = [
        a for a in db.animals.values()
        if a["shelter_id"] == shelter_id and a["status"] != "ADOPTED"
    ]

    if len(animals_in_shelter) == 0:
        shelter["compliance_score"] = 100.0
        return

    compliant_count = sum(1 for a in animals_in_shelter if a.get("vaccination_compliant", False))
    active_holds = sum(
        1 for h in db.compliance_holds.values()
        if h["status"] == "ACTIVE" and h["animal_id"] in {a["id"] for a in animals_in_shelter}
    )

    base_score = Decimal(str(compliant_count)) / Decimal(str(len(animals_in_shelter))) * Decimal("100")
    penalty = Decimal(str(active_holds * HOLD_PENALTY_POINTS))
    score = max(Decimal("0"), base_score - penalty)
    shelter["compliance_score"] = float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def maybe_transition_animal_on_hold(animal_id, hold_severity):
    """When a HIGH/CRITICAL hold is created, transition animal to UNAVAILABLE."""
    if hold_severity not in ("HIGH", "CRITICAL"):
        return
    animal = db.animals.get(animal_id)
    if not animal:
        return
    if animal["status"] in ("AVAILABLE", "BOARDING"):
        animal["status"] = "UNAVAILABLE"
        animal["adoption_eligible"] = False
        animal["updated_at"] = now_iso()
        animal["version"] += 1


def maybe_revert_animal_on_hold_resolve(animal_id):
    """When all HIGH/CRITICAL holds resolved, revert to AVAILABLE if UNAVAILABLE."""
    animal = db.animals.get(animal_id)
    if not animal:
        return
    if animal["status"] != "UNAVAILABLE":
        return
    if not has_active_high_critical_hold(animal_id):
        animal["status"] = "AVAILABLE"
        animal["updated_at"] = now_iso()
        animal["version"] += 1
        recompute_animal_eligibility(animal_id)
