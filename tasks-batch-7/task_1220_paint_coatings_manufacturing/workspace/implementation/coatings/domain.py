"""Domain logic: constants, calculations, serializers, cascades."""
from datetime import timedelta
from decimal import Decimal

from .errors import not_found
from .store import next_batch_code, now, store
from .util import D, add_months, fmt_ts, round0, round2, touch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PRODUCT_CATEGORIES = ("FLAT", "NONFLAT", "PRIMER", "INDUSTRIAL_MAINTENANCE", "TRAFFIC_MARKING")
BASE_FAMILIES = ("LATEX_INTERIOR", "LATEX_EXTERIOR", "ALKYD")
SIZE_CODES = ("QUART", "GALLON", "FIVE_GALLON")
CLAIM_TYPES = ("FREEZE_DAMAGE", "SHELF_LIFE_EXPIRY")
DISPOSAL_REASONS = ("OBSOLETE_STOCK", "RETURNED_GOODS", "BATCH_REJECT", "DAMAGED_STOCK")
ADJUSTMENT_KINDS = ("THINNER", "THICKENER", "TINT_SHOT", "EXEMPT_SOLVENT")

SIZES = {
    "QUART": {"nominal": 1150, "volume": Decimal("0.25"), "liters": Decimal("0.946")},
    "GALLON": {"nominal": 4600, "volume": Decimal("1.0"), "liters": Decimal("3.785")},
    "FIVE_GALLON": {"nominal": 23000, "volume": Decimal("5.0"), "liters": Decimal("18.927")},
}

RETENTION_MONTHS = {
    "FLAT": 24,
    "NONFLAT": 24,
    "PRIMER": 18,
    "INDUSTRIAL_MAINTENANCE": 36,
    "TRAFFIC_MARKING": 12,
}

GAL_TO_L = Decimal("3.78541")
THINNER_VOC_G_PER_ML = Decimal("0.9")
WASHDOWN_BUFFER_MIN = 30
MAX_REWORK = 2
CUSTOM_SETUP_FEE_CENTS = 7500
RUSH_PCT = Decimal("0.12")
RUSH_PCT_THRESHOLD_CENTS = 200000
RUSH_FLAT_CENTS = 15000
CUSTOM_MIN_GALLONS = 50
CUSTOM_MIN_GALLONS_RUSH = 100
RUSH_DAILY_LIMIT = 3
WASTE_RECOVERY = Decimal("0.5")
REWORK_FEE_CENTS = 25000
BAND_FULL_DAYS = 540
BAND_MID_DAYS = 360
BAND_LOW_DAYS = 180
FREEZE_PENALTY_FACTOR = Decimal("0.5")
FREEZE_PENALTY_EXPOSURE_THRESHOLD = 2
CLAIM_WINDOW_DAYS = 30
HAZMAT_VOC_THRESHOLD_GPL = Decimal("250")
RATE_HAZMAT_CENTS_PER_KG = 250
RATE_NONHAZMAT_CENTS_PER_KG = 90
MANIFEST_FEE_CENTS = 45000
PAIL_RECOVERY_CENTS = 300
RECOVERY_CAP_PCT = Decimal("0.20")
QUANTITY_TOLERANCE_PCT = 2
RECON_TOLERANCE_PCT = Decimal("0.5")

# PRD §2.10: the reservation is released only "when the batch is cancelled or
# reaches DISPOSED"; §3.7: a condemned batch's mill reservation is "finally
# released" at the DISPOSED transition — so DISPOSAL_PENDING still holds it.
RESERVED_STATES = (
    "PLANNED", "ON_HOLD", "MILLING", "TINTING", "QC_PENDING", "REWORK", "QC_APPROVED", "FILLING",
    "DISPOSAL_PENDING",
)
MILL_BUSY_STATES = ("MILLING", "TINTING", "QC_PENDING", "REWORK", "QC_APPROVED", "FILLING")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get(table, rid):
    rec = getattr(store, table).get(rid)
    if rec is None:
        raise not_found()
    return rec


def formula_of(batch):
    return store.formulas.get(batch["formula_id"])


def base_of_formula(formula):
    return store.tint_bases.get(formula["tint_base_id"])


def base_of_batch(batch):
    f = formula_of(batch)
    return base_of_formula(f) if f else None


def lines_of_formula(formula_id):
    return [l for l in store.formula_lines.values() if l["formula_id"] == formula_id]


def adjustments_of_batch(batch_id):
    return [a for a in store.batch_adjustments.values() if a["batch_id"] == batch_id]


def containers_of_batch(batch_id):
    return [c for c in store.containers.values() if c["batch_id"] == batch_id]


def reconcile_filled_net(batch):
    total = Decimal("0")
    for c in containers_of_batch(batch["id"]):
        if c["status"] != "REJECTED":
            total += c["net_weight_kg"]
    batch["filled_net_kg"] = total


def mill_reserved_minutes(mill_id):
    total = 0
    for b in store.batches.values():
        if b["mill_id"] == mill_id and b["status"] in RESERVED_STATES:
            total += b["_window_minutes"]
    return total


def set_status(rec, status):
    rec["status"] = status
    touch(rec)


def block_order_of_batch(batch, from_statuses):
    oid = batch.get("order_id")
    if not oid:
        return
    order = store.orders.get(oid)
    if order is not None and order["status"] in from_statuses:
        set_status(order, "BLOCKED")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_voc_actual_gpl(batch):
    formula = formula_of(batch)
    base = base_of_formula(formula)
    actual_gallons = D(batch["actual_gallons"])
    batch_L = actual_gallons * GAL_TO_L
    water_L = batch_L * D(base["water_fraction_pct"]) / Decimal("100")
    exempt_L = Decimal("0")
    colorant_voc = Decimal("0")
    thinner_voc = Decimal("0")
    for line in lines_of_formula(formula["id"]):
        colorant = store.colorants.get(line["colorant_id"])
        colorant_voc += D(line["shots_per_gallon"]) * actual_gallons * D(colorant["voc_g_per_unit"])
    for adj in adjustments_of_batch(batch["id"]):
        if adj["kind"] == "EXEMPT_SOLVENT":
            exempt_L += D(adj["quantity"]) / Decimal("1000")
        elif adj["kind"] == "TINT_SHOT":
            colorant = store.colorants.get(adj["colorant_id"])
            colorant_voc += D(adj["quantity"]) * D(colorant["voc_g_per_unit"])
        elif adj["kind"] == "THINNER":
            thinner_voc += D(adj["quantity"]) * THINNER_VOC_G_PER_ML
    voc_mass_g = D(base["base_voc_gpl"]) * batch_L + colorant_voc + thinner_voc
    denominator_L = batch_L - water_L - exempt_L
    return round2(voc_mass_g / denominator_L)


def weigh_passes(nominal_fill_g, actual_fill_g):
    tolerance = max(round0(D(nominal_fill_g) * Decimal("0.015")), 10)
    return abs(actual_fill_g - nominal_fill_g) <= tolerance


def theoretical_cost_cents(base, formula, planned_gallons):
    per_gal = D(base["base_cost_per_gal_cents"])
    for line in lines_of_formula(formula["id"]):
        colorant = store.colorants.get(line["colorant_id"])
        per_gal += D(line["shots_per_gallon"]) * D(colorant["cost_per_shot_cents"])
    return round0(D(planned_gallons) * per_gal)


def final_cost_cents(batch):
    formula = formula_of(batch)
    base = base_of_formula(formula)
    actual = D(batch["actual_gallons"])
    total = actual * D(base["base_cost_per_gal_cents"])
    for line in lines_of_formula(formula["id"]):
        colorant = store.colorants.get(line["colorant_id"])
        total += D(line["shots_per_gallon"]) * actual * D(colorant["cost_per_shot_cents"])
    for adj in adjustments_of_batch(batch["id"]):
        if adj["kind"] == "TINT_SHOT":
            colorant = store.colorants.get(adj["colorant_id"])
            total += D(adj["quantity"]) * D(colorant["cost_per_shot_cents"])
    waste = round0(D(batch["waste_gallons"]) * D(base["base_cost_per_gal_cents"]) * WASTE_RECOVERY)
    total += waste
    total += batch["rework_count"] * REWORK_FEE_CENTS
    return round0(total)


def credit_band_pct(remaining_days):
    if remaining_days >= BAND_FULL_DAYS:
        return Decimal("1.00")
    if remaining_days >= BAND_MID_DAYS:
        return Decimal("0.60")
    if remaining_days >= BAND_LOW_DAYS:
        return Decimal("0.30")
    return Decimal("0.00")


def credit_cents(invoice_value_cents, remaining_days, claim_type, exposure_count):
    band = credit_band_pct(remaining_days)
    factor = Decimal("1")
    if claim_type == "FREEZE_DAMAGE" and exposure_count > FREEZE_PENALTY_EXPOSURE_THRESHOLD:
        factor = FREEZE_PENALTY_FACTOR
    return round0(D(invoice_value_cents) * band * factor)


def order_line_gallons(order):
    total = Decimal("0")
    for line in order["lines"]:
        total += D(line["gallons"])
    return total


def shipped_volume_gal(order_id):
    total = Decimal("0")
    for c in store.containers.values():
        if c.get("order_id") == order_id and c["status"] == "SHIPPED":
            total += c["volume_gal"]
    return total


def batch_is_hazmat(batch):
    voc = batch.get("voc_actual_gpl")
    if voc is not None and voc > HAZMAT_VOC_THRESHOLD_GPL:
        return True
    formula = formula_of(batch)
    if formula is None:
        return False
    for line in lines_of_formula(formula["id"]):
        colorant = store.colorants.get(line["colorant_id"])
        if colorant is not None and colorant["is_hazmat"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def _ts(v):
    return fmt_ts(v) if v is not None else None


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def ser_customer(r):
    out = {
        "name": r["name"],
        "home_state_code": r["home_state_code"],
        "annual_credit_cap_cents": r["annual_credit_cap_cents"],
        "credit_balance_cents": r["credit_balance_cents"],
        "credit_used_ytd_cents": r["credit_used_ytd_cents"],
    }
    out.update(_common(r))
    return out


def ser_tint_base(r):
    out = {
        "base_code": r["base_code"],
        "product_category": r["product_category"],
        "base_family": r["base_family"],
        "base_voc_gpl": r["base_voc_gpl"],
        "water_fraction_pct": r["water_fraction_pct"],
        "density_kg_per_gal": r["density_kg_per_gal"],
        "base_cost_per_gal_cents": r["base_cost_per_gal_cents"],
        "unit_price_per_gal_cents": r["unit_price_per_gal_cents"],
        "shelf_life_months": r["shelf_life_months"],
        "grind_spec_um": r["grind_spec_um"],
    }
    out.update(_common(r))
    return out


def ser_colorant(r):
    out = {
        "colorant_code": r["colorant_code"],
        "voc_g_per_unit": r["voc_g_per_unit"],
        "cost_per_shot_cents": r["cost_per_shot_cents"],
        "is_hazmat": r["is_hazmat"],
    }
    out.update(_common(r))
    return out


def ser_formula(r):
    out = {
        "formula_code": r["formula_code"],
        "color_name": r["color_name"],
        "tint_base_id": r["tint_base_id"],
        "is_custom": r["is_custom"],
        "target_delta_e": r["target_delta_e"],
        "min_batch_gallons": r["min_batch_gallons"],
        "formula_version_no": r["formula_version_no"],
        "predecessor_formula_id": r["predecessor_formula_id"],
        "status": r["status"],
        "activated_at": _ts(r["activated_at"]),
    }
    out.update(_common(r))
    return out


def ser_formula_line(r):
    return {
        "id": r["id"],
        "formula_id": r["formula_id"],
        "colorant_id": r["colorant_id"],
        "shots_per_gallon": r["shots_per_gallon"],
        "sequence": r["sequence"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_voc_rule(r):
    out = {
        "category": r["category"],
        "state_code": r["state_code"],
        "max_voc_gpl": r["max_voc_gpl"],
        "effective_from": r["effective_from"],
        "effective_to": r["effective_to"],
        "exempt_container_l": r["exempt_container_l"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_mill(r):
    out = {
        "mill_code": r["mill_code"],
        "capacity_gallons": r["capacity_gallons"],
        "status": r["status"],
        "reserved_minutes": mill_reserved_minutes(r["id"]),
    }
    out.update(_common(r))
    return out


def ser_batch(r):
    out = {
        "batch_code": r["batch_code"],
        "formula_id": r["formula_id"],
        "pinned_formula_version_no": r["pinned_formula_version_no"],
        "product_category": r["product_category"],
        "base_family": r["base_family"],
        "mill_id": r["mill_id"],
        "order_id": r["order_id"],
        "planned_gallons": r["planned_gallons"],
        "actual_gallons": r["actual_gallons"],
        "mill_window_start": r["mill_window_start"],
        "mill_window_end": r["mill_window_end"],
        "status": r["status"],
        "rework_count": r["rework_count"],
        "dispersion_cycles": r["dispersion_cycles"],
        "voc_actual_gpl": _num(r["voc_actual_gpl"]),
        "theoretical_cost_cents": r["theoretical_cost_cents"],
        "actual_cost_cents": r["actual_cost_cents"],
        "filled_net_kg": _num(r["filled_net_kg"]),
        "waste_gallons": r["waste_gallons"],
        "closed_at": _ts(r["closed_at"]),
    }
    out.update(_common(r))
    return out


def ser_batch_adjustment(r):
    return {
        "id": r["id"],
        "batch_id": r["batch_id"],
        "kind": r["kind"],
        "quantity": r["quantity"],
        "colorant_id": r["colorant_id"],
        "voc_contribution_g": _num(r["voc_contribution_g"]),
        "cycle_index": r["cycle_index"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_color_match(r):
    out = {
        "batch_id": r["batch_id"],
        "cycle_index": r["cycle_index"],
        "measured_delta_e": r["measured_delta_e"],
        "threshold_delta_e": r["threshold_delta_e"],
        "measured_by_user_id": r["measured_by_user_id"],
        "status": r["status"],
        "decided_by_user_id": r["decided_by_user_id"],
        "decided_at": _ts(r["decided_at"]),
        "retain_sample_id": r["retain_sample_id"],
        "retain_until": _ts(r["retain_until"]),
        "retain_purged_at": _ts(r["retain_purged_at"]),
    }
    out.update(_common(r))
    return out


def ser_container(r):
    out = {
        "batch_id": r["batch_id"],
        "size_code": r["size_code"],
        "nominal_fill_g": r["nominal_fill_g"],
        "actual_fill_g": r["actual_fill_g"],
        "fill_variance_g": r["fill_variance_g"],
        "net_weight_kg": _num(r["net_weight_kg"]),
        "volume_gal": _num(r["volume_gal"]),
        "size_liters": _num(r["size_liters"]),
        "status": r["status"],
        "order_id": r["order_id"],
        "destination_state_code": r["destination_state_code"],
        "manufactured_at": _ts(r["manufactured_at"]),
        "expiry_date": _ts(r["expiry_date"]),
        "freeze_exposure_count": r["freeze_exposure_count"],
        "shipped_at": _ts(r["shipped_at"]),
        "disposal_request_id": r["disposal_request_id"],
        "pre_disposal_status": r["pre_disposal_status"],
    }
    out.update(_common(r))
    return out


def ser_order(r):
    out = {
        "customer_id": r["customer_id"],
        "destination_state_code": r["destination_state_code"],
        "rush_flag": r["rush_flag"],
        "lines": r["lines"],
        "is_custom_order": r["is_custom_order"],
        "subtotal_cents": r["subtotal_cents"],
        "setup_fee_cents": r["setup_fee_cents"],
        "rush_fee_cents": r["rush_fee_cents"],
        "total_cents": r["total_cents"],
        "status": r["status"],
        "rush_approved_date": r["rush_approved_date"],
    }
    out.update(_common(r))
    return out


def ser_credit_claim(r):
    out = {
        "customer_id": r["customer_id"],
        "container_id": r["container_id"],
        "claim_type": r["claim_type"],
        "invoice_value_cents": r["invoice_value_cents"],
        "claimed_exposure_count": r["claimed_exposure_count"],
        "verified_exposure_count": r["verified_exposure_count"],
        "remaining_days_at_claim": r["remaining_days_at_claim"],
        "provisional_credit_cents": r["provisional_credit_cents"],
        "final_credit_cents": r["final_credit_cents"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
        "approved_by_user_id": r["approved_by_user_id"],
        "settled_by_user_id": r["settled_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_disposal_request(r):
    out = {
        "reason": r["reason"],
        "container_ids": r["container_ids"],
        "batch_ids": r["batch_ids"],
        "hazmat_class": r["hazmat_class"],
        "manifest_no": r["manifest_no"],
        "expected_destroyed_kg": _num(r["expected_destroyed_kg"]),
        "actual_destroyed_kg": _num(r["actual_destroyed_kg"]),
        "gross_cost_cents": r["gross_cost_cents"],
        "recovery_credit_cents": r["recovery_credit_cents"],
        "net_cost_cents": r["net_cost_cents"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


# ---------------------------------------------------------------------------
# Formula deprecation cascade (activation successor link + manual deprecate)
# ---------------------------------------------------------------------------
def deprecate_formula_cascade(formula):
    set_status(formula, "DEPRECATED")
    for b in store.batches.values():
        if b["formula_id"] == formula["id"] and b["status"] == "PLANNED":
            set_status(b, "ON_HOLD")
            oid = b.get("order_id")
            if oid:
                order = store.orders.get(oid)
                if order is not None and order["status"] == "SCHEDULED":
                    set_status(order, "BLOCKED")
