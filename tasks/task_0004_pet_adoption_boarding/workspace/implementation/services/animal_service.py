from db import (
    animals,
    vaccination_records,
    compliance_holds,
    shelters,
    boarding_reservations,
    utc_now,
    now_iso,
    parse_iso,
)
from services.rounding import round_half_up_2


SPECIES_VACCINE_MAP_ADOPTION = {
    "DOG": ["RABIES", "DHPP"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}

SPECIES_VACCINE_MAP_BOARDING = {
    "DOG": ["RABIES", "DHPP", "BORDETELLA"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}


def vaccination_compliant(animal, variant="adoption"):
    species = animal.get("species")
    mapping = SPECIES_VACCINE_MAP_BOARDING if variant == "boarding" else SPECIES_VACCINE_MAP_ADOPTION
    required = mapping.get(species, [])
    if not required:
        return True
    now = utc_now()
    animal_id = animal["id"]
    for vaccine in required:
        found = False
        for rec in vaccination_records.values():
            if rec["animal_id"] != animal_id:
                continue
            if rec["vaccine_name"] != vaccine:
                continue
            exp = parse_iso(rec["expiry_date"])
            if exp is not None and exp > now:
                found = True
                break
        if not found:
            return False
    return True


def active_holds_for_animal(animal_id):
    return [h for h in compliance_holds.values()
            if h["animal_id"] == animal_id and h["status"] == "ACTIVE"]


def has_active_high_critical_hold(animal_id):
    for h in active_holds_for_animal(animal_id):
        if h["severity"] in ("HIGH", "CRITICAL"):
            return True
    return False


def active_hold_count(animal_id):
    return len(active_holds_for_animal(animal_id))


def adoption_eligible(animal):
    if animal["status"] != "AVAILABLE":
        return False
    if not vaccination_compliant(animal, "adoption"):
        return False
    if has_active_high_critical_hold(animal["id"]):
        return False
    return True


def compute_boarding_zone_hint(animal):
    if animal.get("temperament") == "AGGRESSIVE":
        return "ISOLATION"
    if animal.get("temperament") == "ENERGETIC":
        return "ACTIVE"
    if animal.get("species") in ("CAT", "BIRD", "RABBIT"):
        return "SMALL_ANIMAL"
    return "GENERAL"


def serialize_animal(animal):
    return {
        "id": animal["id"],
        "created_at": animal["created_at"],
        "updated_at": animal["updated_at"],
        "version": animal["version"],
        "shelter_id": animal["shelter_id"],
        "name": animal["name"],
        "species": animal["species"],
        "breed": animal["breed"],
        "age_months": animal["age_months"],
        "weight_kg": animal["weight_kg"],
        "temperament": animal["temperament"],
        "special_needs": animal.get("special_needs", []),
        "vaccination_compliant": vaccination_compliant(animal, "adoption"),
        "active_hold_count": active_hold_count(animal["id"]),
        "adoption_eligible": adoption_eligible(animal),
        "boarding_zone_hint": compute_boarding_zone_hint(animal),
        "status": animal["status"],
    }


def current_boarding_count(shelter_id):
    return sum(1 for r in boarding_reservations.values()
               if r["shelter_id"] == shelter_id and r["status"] == "CHECKED_IN")


def adoption_count(shelter_id):
    from db import adoption_applications
    return sum(1 for a in adoption_applications.values()
               if a["shelter_id"] == shelter_id and a["status"] == "COMPLETED")


def shelter_compliance_score(shelter_id):
    animals_at_shelter = [a for a in animals.values()
                          if a["shelter_id"] == shelter_id and a["status"] != "ADOPTED"]
    if not animals_at_shelter:
        return 100.00
    total = len(animals_at_shelter)
    compliant_count = sum(1 for a in animals_at_shelter if vaccination_compliant(a, "adoption"))
    from decimal import Decimal, ROUND_HALF_UP
    base = Decimal(100) * Decimal(compliant_count) / Decimal(total)
    total_holds = 0
    for a in animals_at_shelter:
        total_holds += active_hold_count(a["id"])
    penalty = Decimal(5) * Decimal(total_holds)
    score = base - penalty
    if score < 0:
        score = Decimal(0)
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def revenue_pending_cents(shelter_id):
    from db import fee_invoices
    total = 0
    for inv in fee_invoices.values():
        if inv["shelter_id"] != shelter_id:
            continue
        if inv.get("settlement_batch_id") is not None:
            continue
        if inv["status"] == "PAID":
            total += inv["total_amount_cents"]
        elif inv["status"] == "REFUNDED":
            total -= inv["refund_amount_cents"]
    return total


def revenue_settled_cents(shelter_id):
    from db import settlement_batches
    total = 0
    for b in settlement_batches.values():
        if b["shelter_id"] != shelter_id:
            continue
        if b["status"] in ("APPROVED", "PAID"):
            total += b["net_amount_cents"]
    return total


def serialize_shelter(shelter):
    return {
        "id": shelter["id"],
        "created_at": shelter["created_at"],
        "updated_at": shelter["updated_at"],
        "version": shelter["version"],
        "name": shelter["name"],
        "address": shelter["address"],
        "contact_email": shelter["contact_email"],
        "boarding_capacity": shelter["boarding_capacity"],
        "tax_rate": shelter["tax_rate"],
        "current_boarding_count": current_boarding_count(shelter["id"]),
        "adoption_count": adoption_count(shelter["id"]),
        "compliance_score": shelter_compliance_score(shelter["id"]),
        "revenue_pending_cents": revenue_pending_cents(shelter["id"]),
        "revenue_settled_cents": revenue_settled_cents(shelter["id"]),
        "status": shelter["status"],
    }


def serialize_vaccination(rec):
    now = utc_now()
    exp = parse_iso(rec["expiry_date"])
    is_valid = exp is not None and exp > now
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "animal_id": rec["animal_id"],
        "vaccine_name": rec["vaccine_name"],
        "administered_date": rec["administered_date"],
        "expiry_date": rec["expiry_date"],
        "batch_number": rec["batch_number"],
        "veterinarian_id": rec["veterinarian_id"],
        "is_currently_valid": is_valid,
    }


def adopter_adoption_history_count(adopter_id):
    from db import adoption_applications
    return sum(1 for a in adoption_applications.values()
               if a["adopter_id"] == adopter_id and a["status"] == "COMPLETED")


def adopter_latest_home_visit(adopter_id):
    from db import home_visits
    relevant = [hv for hv in home_visits.values()
                if hv.get("adopter_id") == adopter_id and hv["status"] == "COMPLETED"]
    if not relevant:
        return None, None
    relevant.sort(key=lambda h: h["updated_at"], reverse=True)
    return relevant[0]["id"], relevant[0].get("result")


def serialize_adopter(adopter):
    hv_id, hv_result = adopter_latest_home_visit(adopter["id"])
    return {
        "id": adopter["id"],
        "created_at": adopter["created_at"],
        "updated_at": adopter["updated_at"],
        "version": adopter["version"],
        "shelter_id": adopter["shelter_id"],
        "full_name": adopter["full_name"],
        "email": adopter["email"],
        "phone": adopter["phone"],
        "home_type": adopter["home_type"],
        "has_yard": adopter["has_yard"],
        "has_other_pets": adopter["has_other_pets"],
        "other_pet_species": adopter.get("other_pet_species", []),
        "adoption_history_count": adopter_adoption_history_count(adopter["id"]),
        "latest_home_visit_id": hv_id,
        "latest_home_visit_result": hv_result,
        "status": adopter["status"],
    }


def compute_requires_home_visit(animal):
    if animal.get("species") == "DOG":
        return True
    try:
        if float(animal.get("weight_kg", 0)) >= 25:
            return True
    except (TypeError, ValueError):
        pass
    return False


def serialize_application(app):
    animal = animals.get(app["animal_id"])
    return {
        "id": app["id"],
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
        "shelter_id": app["shelter_id"],
        "animal_id": app["animal_id"],
        "adopter_id": app["adopter_id"],
        "reason": app["reason"],
        "home_visit_id": app.get("home_visit_id"),
        "animal_version_pinned": app.get("animal_version_pinned"),
        "adopter_version_pinned": app.get("adopter_version_pinned"),
        "reviewer_id": app.get("reviewer_id"),
        "approver_id": app.get("approver_id"),
        "rejection_reason": app.get("rejection_reason"),
        "fee_invoice_id": app.get("fee_invoice_id"),
        "requires_home_visit": compute_requires_home_visit(animal) if animal else False,
        "status": app["status"],
    }


def compute_home_visit_score_and_result(animal, yard_adequate, space_adequate,
                                        safety_hazards_found, existing_pets_compatible):
    species = animal.get("species") if animal else None
    if species in ("CAT", "BIRD", "RABBIT"):
        # yard_optional variant: yard weight 0, space weight 55
        yard_pts = 0
        space_pts = 55 if space_adequate else 0
    else:
        yard_pts = 25 if yard_adequate else 0
        space_pts = 30 if space_adequate else 0
    hazard_pts = 0 if safety_hazards_found else 25
    pets_pts = 20 if existing_pets_compatible else 0
    score = yard_pts + space_pts + hazard_pts + pets_pts
    if score >= 70:
        result = "PASS"
    elif score >= 50:
        result = "CONDITIONAL_PASS"
    else:
        result = "FAIL"
    return score, result


def serialize_home_visit(hv):
    return {
        "id": hv["id"],
        "created_at": hv["created_at"],
        "updated_at": hv["updated_at"],
        "version": hv["version"],
        "application_id": hv["application_id"],
        "adopter_id": hv.get("adopter_id"),
        "case_worker_id": hv.get("case_worker_id"),
        "scheduled_date": hv["scheduled_date"],
        "yard_adequate": hv.get("yard_adequate"),
        "space_adequate": hv.get("space_adequate"),
        "safety_hazards_found": hv.get("safety_hazards_found"),
        "existing_pets_compatible": hv.get("existing_pets_compatible"),
        "notes": hv.get("notes"),
        "overall_score": hv.get("overall_score"),
        "result": hv.get("result"),
        "status": hv["status"],
    }
