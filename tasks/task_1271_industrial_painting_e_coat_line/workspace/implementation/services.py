"""Business logic: calculations (PRD SS3 / scaffold SS1.3), cascades, VOC ledger."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, SEQ, clock_now
from response import now_iso

# --- calculation constants (scaffold SS1.3) ---
FILM_TRANSFER_K = Decimal("220.0")
TIER1_MAX_PARTS = 20
TIER2_MAX_PARTS = 40
TIER1_FACTOR = Decimal("1.00")
TIER2_FACTOR = Decimal("0.95")
TIER3_FACTOR = Decimal("0.88")

SOLIDS_FRACTION = Decimal("0.35")
TRANSFER_EFFICIENCY = Decimal("0.95")

BASE_COAT_RATE_CENTS_PER_DM2 = 110

SOLVENT_COST_CENTS_PER_L = 450
PURGE_FIXED_CENTS = 12000
PURGE_SOLVENT_VOC_G_PER_L = 880
PURGE_BUFFER_MIN = 30

STRIP_BASE_CENTS = 25000
STRIP_PER_PART_CENTS = 300
REPAINT_RATE_CENTS_PER_DM2 = 85
REWORK_MULTIPLIER = Decimal("1.33")
MAX_REWORK_COUNT = 2

STRIP_SOLVENT_L_PER_PART = Decimal("0.5")
STRIP_SOLVENT_VOC_G_PER_L = 900


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def round_half_up(v, places):
    return D(v).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_cents(v):
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- record lifecycle -------------------------------------------------------

def new_common():
    """Common fields for mutable resources: id/created_at/updated_at/version."""
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(SEQ),
    }


def new_event():
    """Event records carry only id + created_at."""
    return {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": next(SEQ),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# --- lookups ----------------------------------------------------------------

def stages_of_line(line_id):
    return [s for s in STORE["pretreatment_stages"].values() if s["paint_line_id"] == line_id]


def lot_outstanding(lot):
    return lot["part_quantity"] - lot["scrapped_quantity"] - lot["passed_quantity"]


def spec_of(lot):
    return STORE["coating_specs"].get(lot["spec_id"])


# --- chemistry cascade (PRD SS2.9) ------------------------------------------

def recompute_posture(line):
    hold = any(s["status"] in ("OUT_OF_RANGE", "ADJUSTING") for s in stages_of_line(line["id"]))
    new_posture = "CHEM_HOLD" if hold else "RUNNING"
    if line["posture"] != new_posture:
        line["posture"] = new_posture
        touch(line)


# --- calculations -----------------------------------------------------------

def density_factor(parts_per_hanger):
    if parts_per_hanger <= TIER1_MAX_PARTS:
        return TIER1_FACTOR
    if parts_per_hanger <= TIER2_MAX_PARTS:
        return TIER2_FACTOR
    return TIER3_FACTOR


def predicted_film_build_um(line_speed_fpm, parts_per_hanger):
    raw = FILM_TRANSFER_K / D(line_speed_fpm) * density_factor(parts_per_hanger)
    return round_half_up(raw, 1)


def theoretical_voc_kg(spec, outstanding_parts):
    avg_film_um = (D(spec["film_build_min_um"]) + D(spec["film_build_max_um"])) / 2
    theoretical_liters = (
        D(outstanding_parts)
        * D(spec["area_dm2_per_part"])
        * avg_film_um
        * Decimal("0.00001")
        / (SOLIDS_FRACTION * TRANSFER_EFFICIENCY)
    )
    return round_half_up(theoretical_liters * D(spec["voc_g_per_l"]) / 1000, 3)


def metered_voc_kg(paint_used_liters, voc_g_per_l):
    return round_half_up(D(paint_used_liters) * D(voc_g_per_l) / 1000, 3)


def purge_cost_cents(purge_solvent_liters):
    return round_cents(D(purge_solvent_liters) * SOLVENT_COST_CENTS_PER_L) + PURGE_FIXED_CENTS


def purge_voc_kg(purge_solvent_liters):
    return round_half_up(D(purge_solvent_liters) * PURGE_SOLVENT_VOC_G_PER_L / 1000, 3)


def strip_voc_kg(stripped_parts):
    return round_half_up(
        D(stripped_parts) * STRIP_SOLVENT_L_PER_PART * STRIP_SOLVENT_VOC_G_PER_L / 1000, 3
    )


def base_charge_cents(part_quantity, area_dm2_per_part):
    return part_quantity * round_cents(D(area_dm2_per_part) * BASE_COAT_RATE_CENTS_PER_DM2)


def strip_cost_cents(parts_to_rework):
    return STRIP_BASE_CENTS + STRIP_PER_PART_CENTS * parts_to_rework


def repaint_per_part_cents(area_dm2_per_part):
    return round_cents(D(area_dm2_per_part) * REPAINT_RATE_CENTS_PER_DM2 * REWORK_MULTIPLIER)


# --- VOC permit ledger (PRD SS2.10) -----------------------------------------

def covering_permit():
    """The VocPermit with status != CLOSED whose half-open period contains the
    current logical clock, else None."""
    now = clock_now()
    cands = [
        p for p in STORE["voc_permits"].values()
        if p["status"] != "CLOSED" and p["_period_start"] <= now < p["_period_end"]
    ]
    cands.sort(key=lambda p: p["_seq"])
    return cands[0] if cands else None


def post_emission(permit, source_type, voc_kg, variant, lot_id=None, color_change_id=None):
    """Append an EmissionEntry and grow permit.used_kg; automatic EXCEEDED."""
    entry = new_event()
    entry.update({
        "permit_id": permit["id"],
        "source_type": source_type,
        "source_lot_id": lot_id,
        "source_color_change_id": color_change_id,
        "voc_kg": round_half_up(voc_kg, 3),
        "entry_variant": variant,
    })
    STORE["emission_entries"][entry["id"]] = entry
    permit["_used_kg"] = round_half_up(permit["_used_kg"] + entry["voc_kg"], 3)
    if permit["status"] == "ACTIVE" and permit["_used_kg"] > D(permit["cap_kg"]):
        permit["status"] = "EXCEEDED"
    touch(permit)
    return entry


def adjust_reserved(permit, delta):
    permit["_reserved_kg"] = round_half_up(permit["_reserved_kg"] + D(delta), 3)
    touch(permit)


def cap_would_exceed(permit, new_emission_kg):
    """Strictly-greater rejects; landing exactly on cap_kg is allowed."""
    return (permit["_used_kg"] + permit["_reserved_kg"] + D(new_emission_kg)) > D(permit["cap_kg"])
