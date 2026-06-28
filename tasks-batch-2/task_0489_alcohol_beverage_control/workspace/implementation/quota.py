"""quota_availability (PRD §3.6). cap = floor(population / persons_per_license);
used = count of applications in this region+class with quota_slot_held=true;
available = cap - used."""
from db import db

# Statuses that HOLD a quota slot. (Reflected in quota_slot_held, but we also
# anchor on the flag itself per the scaffold's formula.)
HOLDING_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "PROTEST_PERIOD", "PROTEST_HEARING",
    "APPROVED", "ISSUED",
}


def region_code_for_application(app):
    """Derive the application's region from its premise."""
    premise = db.premises.get(app["premise_id"])
    if premise is None:
        return None
    return premise["region_code"]


def quota_used(region_code, license_class_code):
    count = 0
    for app in db.license_applications.values():
        if not app.get("quota_slot_held"):
            continue
        if app["license_class_code"] != license_class_code:
            continue
        if region_code_for_application(app) != region_code:
            continue
        count += 1
    return count


def quota_status(region_code, license_class_code, license_class):
    region = None
    for r in db.quota_regions.values():
        if r["region_code"] == region_code:
            region = r
            break
    if region is None:
        return 0, 0, 0
    cap = region["population"] // region["persons_per_license"]
    used = quota_used(region_code, license_class_code)
    available = cap - used
    return cap, used, available
