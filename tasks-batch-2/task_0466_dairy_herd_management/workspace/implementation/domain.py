"""Cross-entity domain helpers: lactation production recompute, milk_eligible
recompute, pagination, and the lactation-tests ordering used by calculations.
"""
import db
import errors
import calculations
from errors import err
from records import touch
from util import iso_format
import clock


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items, args):
    """Apply limit/offset to a list already sorted by creation order.

    limit default 10, min 1, max 100; offset default 0, min 0. Out-of-range or
    malformed pagination params are rejected with ERR_INVALID_REQUEST (422).
    """
    limit = _parse_pagination_int(args.get("limit"), default=10, minimum=1, maximum=100)
    offset = _parse_pagination_int(args.get("offset"), default=0, minimum=0, maximum=None)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _parse_pagination_int(raw, default, minimum, maximum):
    if raw is None:
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid pagination parameter")
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Pagination parameter below minimum")
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "Pagination parameter above maximum")
    return val


def sorted_by_creation(records):
    """Sort by created_at ascending; tie-break by monotonic _seq (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Lactation production recompute (PRD §3.4)
# ---------------------------------------------------------------------------
def lactation_tests_sorted(lactation_id):
    """All TestDayRecords on the lactation ordered by day_in_milk ASC."""
    tdrs = [t for t in db.test_day_records.values()
            if t["lactation_id"] == lactation_id]
    tdrs.sort(key=lambda t: t["day_in_milk"])
    return tdrs


def recompute_lactation_production(lactation):
    """Recompute cumulative_milk_lbs and projected_305d_milk_lbs from all of the
    lactation's test-day records (PRD §3.4). Does NOT bump version — the
    production figures are computed reads keyed off the immutable test records;
    only mutations via the lactation's own lifecycle bump its version.
    """
    tdrs = lactation_tests_sorted(lactation["id"])
    pairs = [(t["day_in_milk"], t["milk_weight_lbs"]) for t in tdrs]
    cumulative = calculations.lactation_cumulative_milk(pairs)
    projected = calculations.lactation_projected_305d(pairs, cumulative)
    lactation["cumulative_milk_lbs"] = cumulative
    lactation["projected_305d_milk_lbs"] = projected


# ---------------------------------------------------------------------------
# milk_eligible recompute (PRD §3.9)
# ---------------------------------------------------------------------------
def has_live_milk_withhold(animal_id, exclude_treatment_id=None):
    """True if any ACTIVE treatment on the animal still has milk_withhold_until
    after the current clock."""
    now = clock.now()
    for t in db.health_treatments.values():
        if t["animal_id"] != animal_id:
            continue
        if t["status"] != "ACTIVE":
            continue
        if exclude_treatment_id is not None and t["id"] == exclude_treatment_id:
            continue
        if t["_milk_withhold_until_dt"] > now:
            return True
    return False


def recompute_milk_eligible(animal, exclude_treatment_id=None):
    """Set animal.milk_eligible true if no ACTIVE treatment still holds a live
    milk-withhold, else false. Terminal animals stay ineligible."""
    if animal["status"] in ("SOLD", "CULLED", "DIED"):
        animal["milk_eligible"] = False
        return
    animal["milk_eligible"] = not has_live_milk_withhold(
        animal["id"], exclude_treatment_id=exclude_treatment_id)


# ---------------------------------------------------------------------------
# Herd active animal count (PRD §2.8) — recomputed value lives as a read;
# we bump the herd version when a cascade touches it.
# ---------------------------------------------------------------------------
def bump_herd_for_count(herd_id):
    """A cascade that changes an animal's active/dry membership refreshes the
    herd's updated_at and increments its version (PRD §2.8). active_animal_count
    itself is computed on read."""
    herd = db.herds.get(herd_id)
    if herd is not None:
        touch(herd)


# ---------------------------------------------------------------------------
# Lactation lookups
# ---------------------------------------------------------------------------
def open_or_dry_lactation(animal_id):
    """Return the animal's lactation in OPEN or DRY status, if any."""
    for lac in db.lactations.values():
        if lac["animal_id"] == animal_id and lac["status"] in ("OPEN", "DRY"):
            return lac
    return None


def open_lactation(animal_id):
    for lac in db.lactations.values():
        if lac["animal_id"] == animal_id and lac["status"] == "OPEN":
            return lac
    return None
