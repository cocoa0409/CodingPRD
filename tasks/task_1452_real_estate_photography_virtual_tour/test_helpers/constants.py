"""Domain thresholds — numeric constants from PRD §3 calculation rules."""
from datetime import datetime, timedelta, timezone

# Logical clock default (PRD §2.10)
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# shoot_duration rule (PRD §3.1)
BASE_MINUTES_BY_PACKAGE = {"STANDARD": 60, "PREMIUM": 90, "LUXURY": 120}
INCLUDED_PHOTOS_BY_PACKAGE = {"STANDARD": 25, "PREMIUM": 40, "LUXURY": 60}
OVERAGE_STEP_PHOTOS = 5
OVERAGE_STEP_MINUTES = 10

# provisional_quote rule (PRD §3.1)
BASE_RATE_CENTS_BY_PACKAGE = {"STANDARD": 15000, "PREMIUM": 25000, "LUXURY": 40000}
OVERAGE_RATE_CENTS_PER_PHOTO = 300
TOUR_RATE_CENTS_BY_VARIANT = {"BRANDED": 12000, "UNBRANDED": 14000}
TWILIGHT_PREMIUM_BPS = 2500
VOLUME_DISCOUNT_FLOOR_CENTS = 50000
VOLUME_DISCOUNT_BPS = 1000

# addon_pricing rule (PRD §3.4)
ADDON_RATE_CENTS = {
    "DRONE_STILLS": 20000,
    "DRONE_VIDEO": 35000,
    "RUSH_EDIT": 15000,
    "VIRTUAL_STAGING": 10000,
    "TWILIGHT_UPGRADE": 0,
}
ADDON_EXTRA_MINUTES = {
    "DRONE_STILLS": 30,
    "DRONE_VIDEO": 45,
    "RUSH_EDIT": 0,
    "VIRTUAL_STAGING": 0,
    "TWILIGHT_UPGRADE": 0,
}

# turnaround_deadline rule (PRD §3.6)
WEATHER_SLA_EXTENSION_HOURS = 24
WEATHER_SLA_MAX_EVENTS = 2

# final_invoice rule (PRD §3.8)
LATE_DELIVERY_PENALTY_BPS = 1500
WEATHER_CREDIT_CAP_BPS = 3000

# license_fee rule (PRD §3.8)
LICENSE_FEE_CENTS = {"MLS_COMPLIANT": 0, "STANDARD_MARKETING": 5000, "EXTENDED": 15000}
UNBRANDED_SURCHARGE_CENTS = 4000

# paid_revision_fee rule (PRD §3.7)
FREE_REVISION_ROUNDS = 2
PAID_REVISION_BASE_CENTS = 7500
REVISION_HARD_CAP = 4

# reschedule policy (PRD §3.9)
RESCHEDULE_HARD_CAP = 3

# default checklist keys spawned at submit (PRD §3.1)
DEFAULT_CHECKLIST_KEYS = [
    "DECLUTTER_MAIN",
    "UTILITIES_ON",
    "PETS_SECURED",
    "ACCESS_CODES",
    "EXTERIOR_CLEAR",
]

NON_EXISTENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def iso(dt: datetime) -> str:
    """Format a datetime as PRD-style ISO 8601 UTC ('...Z')."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(iso_str: str) -> datetime:
    return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso_plus(iso_str: str, **delta_kwargs) -> str:
    return iso(parse(iso_str) + timedelta(**delta_kwargs))
