"""Domain constants, calculations, serialization, and lazy-expiry reconciliation."""
from core import db, iso_now, parse_iso, round_half_up, ceil_div_area


# ---------------------------------------------------------------------------
# Constants (from PRD §3 / scaffold §1.3)
# ---------------------------------------------------------------------------
MATERIAL_RATE = {"ALUMINUM": 1800, "ACRYLIC": 2600, "STEEL": 3400}  # cents/sqft
COLOR_SETUP_CENTS = 4500
SUBSTRATE_LABOR_MULT = {"ALUMINUM": 1.00, "ACRYLIC": 1.25, "STEEL": 1.50}
ILLUM_PCT = "0.15"
RUSH_PCT = "0.20"

PERMIT_FEE = {
    "CITY_A": {"STRUCTURAL": 25000, "ELECTRICAL": 18000},
    "CITY_B": {"STRUCTURAL": 32000, "ELECTRICAL": 21000},
    "COUNTY_C": {"STRUCTURAL": 0, "ELECTRICAL": 12000},
}

HANDS_MAX_FT = 8
LADDER_MAX_FT = 20

COVERAGE_DAYS = {"ELECTRICAL": 365, "STRUCTURAL": 1825, "COSMETIC": 90}
CREW_BUFFER_MIN = 60

JURISDICTIONS = {"CITY_A", "CITY_B", "COUNTY_C"}
SIGN_TYPES = {"MONUMENT", "PYLON", "WALL", "BLADE"}
SUBSTRATES = {"ALUMINUM", "ACRYLIC", "STEEL"}
PERMIT_KINDS = {"STRUCTURAL", "ELECTRICAL"}
DEFECT_KINDS = {"ELECTRICAL", "STRUCTURAL", "COSMETIC"}
EQUIPMENT_CLASSES = {"LADDER", "BUCKET_TRUCK"}


# ---------------------------------------------------------------------------
# Common-field stamping
# ---------------------------------------------------------------------------
def stamp_new(entity):
    """Set id/created_at/updated_at/version + a stable creation sequence."""
    from core import new_id
    ts = iso_now()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Mark an entity as mutated: refresh updated_at, bump version."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def price_estimate(width_in, height_in, substrate, color_count, illuminated, rush):
    """Run the full estimate pricing. Returns a dict of computed cents fields."""
    area_sqft = ceil_div_area(width_in, height_in)
    material_rate = MATERIAL_RATE[substrate]
    material_cost = area_sqft * material_rate

    color_labor = color_count * COLOR_SETUP_CENTS
    labor_cost = round_half_up(color_labor * SUBSTRATE_LABOR_MULT[substrate])

    subtotal = material_cost + labor_cost

    if illuminated:
        illum_surcharge = round_half_up(_pct(subtotal, ILLUM_PCT))
    else:
        illum_surcharge = 0
    rush_base = subtotal + illum_surcharge
    if rush:
        rush_surcharge = round_half_up(_pct(rush_base, RUSH_PCT))
    else:
        rush_surcharge = 0
    surcharge = illum_surcharge + rush_surcharge
    total = subtotal + surcharge

    return {
        "area_sqft": area_sqft,
        "material_rate_cents_per_sqft": material_rate,
        "material_cost_cents": material_cost,
        "labor_cost_cents": labor_cost,
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "total_cents": total,
    }


def _pct(amount, pct_str):
    from decimal import Decimal
    return Decimal(str(amount)) * Decimal(pct_str)


def equipment_class_required(placement_height_ft, overhead_obstruction):
    """Derive NONE | LADDER | BUCKET_TRUCK from height + obstruction."""
    if placement_height_ft <= LADDER_MAX_FT and not overhead_obstruction:
        if placement_height_ft <= HANDS_MAX_FT:
            return "NONE"
        return "LADDER"
    return "BUCKET_TRUCK"


# ---------------------------------------------------------------------------
# Lazy expiry reconciliation
# ---------------------------------------------------------------------------
def reconcile_estimate(est):
    """A SENT estimate past valid_until_iso becomes EXPIRED (observed on read/accept)."""
    if est.get("status") == "SENT":
        vu = parse_iso(est.get("valid_until_iso"))
        if vu is not None and db.now() >= vu:
            est["status"] = "EXPIRED"
            touch(est)


def reconcile_permit(permit):
    """An APPROVED permit past expires_iso becomes EXPIRED (observed on read/release)."""
    if permit.get("status") == "APPROVED":
        exp = parse_iso(permit.get("expires_iso"))
        if exp is not None and db.now() >= exp:
            permit["status"] = "EXPIRED"
            touch(permit)


def reconcile_project(project):
    """Re-evaluate auto-expiries of a project's time-sensitive children on read."""
    pid = project["id"]
    for est in db.estimates.values():
        if est["sign_project_id"] == pid:
            reconcile_estimate(est)
    for permit in db.permits.values():
        if permit["sign_project_id"] == pid:
            reconcile_permit(permit)


# ---------------------------------------------------------------------------
# Serialization — strip internal fields, expose public shape
# ---------------------------------------------------------------------------
_INTERNAL_PREFIX = "_"


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith(_INTERNAL_PREFIX)}
