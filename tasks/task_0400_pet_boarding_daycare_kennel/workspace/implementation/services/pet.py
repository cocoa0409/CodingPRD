"""Pet-related derivations: size_class from weight, vaccination_status from
records vs the facility business date (PRD §3.2, §3.3).
"""
from db import db
from services.common import touch, parse_date

# Required vaccines per species. The PRD names DOG | CAT species and the
# RABIES/DHPP/BORDETELLA/FVRCP vaccine set. DHPP/BORDETELLA are canine-core,
# FVRCP feline-core, RABIES universal.
REQUIRED_VACCINES = {
    "DOG": {"RABIES", "DHPP", "BORDETELLA"},
    "CAT": {"RABIES", "FVRCP"},
}


def size_class_for_weight(weight_kg):
    """TOY (<5) | SMALL (5–14.999) | MEDIUM (15–29.999) | LARGE (>=30)."""
    if weight_kg < 5:
        return "TOY"
    if weight_kg < 15:
        return "SMALL"
    if weight_kg < 30:
        return "MEDIUM"
    return "LARGE"


def _current_records_by_vaccine(pet_id):
    """Latest non-superseded record per vaccine for the pet."""
    out = {}
    for rec in db.vaccination_records.values():
        if rec["pet_id"] != pet_id:
            continue
        if rec.get("superseded"):
            continue
        out[rec["vaccine"]] = rec
    return out


def compute_vaccination_status(pet):
    """VALID when every species-required vaccine has a non-superseded record
    whose expires_on >= facility.current_date; else EXPIRED/MISSING.

    EXPIRED vs MISSING: if at least one required vaccine has a (non-superseded)
    record on file but it has lapsed, the dimension is EXPIRED; if a required
    vaccine has no record at all, it is MISSING.
    """
    facility = db.facilities.get(pet["facility_id"])
    current_date = facility["current_date"]
    cur = parse_date(current_date)
    required = REQUIRED_VACCINES.get(pet["species"], set())
    records = _current_records_by_vaccine(pet["id"])

    all_present = True
    any_present = False
    all_current = True
    for vac in required:
        rec = records.get(vac)
        if rec is None:
            all_present = False
            all_current = False
            continue
        any_present = True
        if parse_date(rec["expires_on"]) < cur:
            all_current = False
    if all_present and all_current:
        return "VALID"
    # Not valid: distinguish EXPIRED (some record on file, lapsed) vs MISSING.
    if any_present:
        return "EXPIRED"
    return "MISSING"


def recompute_vaccination_status(pet):
    """Recompute and, if changed, bump the pet's version (PRD §3.3)."""
    new_status = compute_vaccination_status(pet)
    if new_status != pet.get("vaccination_status"):
        pet["vaccination_status"] = new_status
        touch(pet)
        return True
    return False
