"""Serializers, calculation contracts (PRD 2.6 / 3.x), and cascade helpers."""
from decimal import Decimal, ROUND_CEILING

import clock
import store
from util import bump, fmt_ts, fmt_value, round1, round3, round_cents


# ---------------------------------------------------------------------------
# domain constants
# ---------------------------------------------------------------------------
LEAF_TYPES = ["BLACK", "GREEN", "WHITE", "OOLONG", "HERBAL"]
ALLERGEN_TAGS = ["TREE_NUT", "SOY", "GLUTEN", "LACTOSE"]
CERT_TYPES = ["ORGANIC", "FAIR_TRADE"]
PACK_FORMATS = ["TEA_BAG", "LOOSE_PACK"]
CERT_TARGETS = ["CONVENTIONAL", "ORGANIC", "FAIR_TRADE"]
MIN_GRADES = ["A", "B", "C"]

GRADE_RANK = {"A": 3, "B": 2, "C": 1}

# sensory_composite_grade
W_AROMA = Decimal("0.40")
W_BRISKNESS = Decimal("0.35")
W_APPEARANCE = Decimal("0.25")
GRADE_A_MIN = Decimal("85.0")
GRADE_B_MIN = Decimal("70.0")
GRADE_C_MIN = Decimal("55.0")

# residue_verdict_threshold
RESIDUE_LIMIT_PPM = Decimal("0.50")
HARD_FAIL_MULTIPLIER = Decimal("2.0")

# moisture
TARGET_MOISTURE_PCT = Decimal("5.0")
RELEASE_MOISTURE_GATE_PCT = Decimal("7.0")

# batch_cost_accounting
WASTE_FACTOR = Decimal("0.02")

# packed_shelf_life
BASE_SHELF_DAYS = {"TEA_BAG": 540, "LOOSE_PACK": 365}
HARVEST_CEILING_DAYS = 730

# contract_unit_price
MIN_UNIT_PRICE_CENTS = 1

# batch states that transition to ON_HOLD on a lot/cert hold (cascade link 2)
BATCH_HOLDABLE_STATES = {
    "RECIPE_LOCKED", "ALLOCATED", "BLENDED", "FLAVORED", "QC_REVIEW", "RELEASED",
}
# batch states from which client cancel is allowed
BATCH_CANCELLABLE_STATES = {
    "DRAFT", "RECIPE_LOCKED", "ALLOCATED", "BLENDED", "FLAVORED", "QC_REVIEW",
    "ON_HOLD",
}
BATCH_TERMINAL_STATES = {"RECALLED", "CANCELLED"}
LOT_TERMINAL_STATES = {"REJECTED", "DEPLETED"}
RUN_TERMINAL_STATES = {"COMPLETED", "CANCELLED"}
CONTRACT_TERMINAL_STATES = {"FULFILLED", "CANCELLED"}


def grade_meets(lot_grade, min_grade):
    """Grade ordering A > B > C; lot satisfies min when at or above it."""
    return GRADE_RANK.get(lot_grade, 0) >= GRADE_RANK.get(min_grade, 99)


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def supplier_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "origin_region": r["origin_region"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def lot_out(r):
    return {
        "id": r["id"],
        "supplier_id": r["supplier_id"],
        "leaf_type": r["leaf_type"],
        "harvest_date": r["harvest_date"].isoformat(),
        "weight_kg": fmt_value(r["weight_kg"]),
        "cost_per_kg_cents": r["cost_per_kg_cents"],
        "moisture_pct": fmt_value(r["moisture_pct"]),
        "remaining_weight_kg": fmt_value(r["remaining_weight_kg"]),
        "registered_by_user_id": r["registered_by_user_id"],
        "composite_grade": r["composite_grade"],
        "latest_residue_verdict": r["latest_residue_verdict"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def assessment_out(r):
    return {
        "id": r["id"],
        "lot_id": r["lot_id"],
        "grader_user_id": r["grader_user_id"],
        "aroma_score": r["aroma_score"],
        "briskness_score": r["briskness_score"],
        "appearance_score": r["appearance_score"],
        "composite_score": fmt_value(r["composite_score"]),
        "composite_grade": r["composite_grade"],
        "created_at": fmt_ts(r["created_at"]),
    }


def residue_test_out(r):
    return {
        "id": r["id"],
        "lot_id": r["lot_id"],
        "lab_name": r["lab_name"],
        "measured_residue_ppm": fmt_value(r["measured_residue_ppm"]),
        "test_method": r["test_method"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "verdict": r["verdict"],
        "test_round": r["test_round"],
        "created_at": fmt_ts(r["created_at"]),
    }


def flavoring_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "allergen_tags": list(r["allergen_tags"]),
        "natural_certified": r["natural_certified"],
        "cost_per_kg_cents": r["cost_per_kg_cents"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def recipe_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "certification_target": r["certification_target"],
        "pack_format": r["pack_format"],
        "components": fmt_value(r["components"]),
        "flavoring_id": r["flavoring_id"],
        "flavoring_pct": fmt_value(r["flavoring_pct"]),
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def batch_out(r):
    return {
        "id": r["id"],
        "recipe_id": r["recipe_id"],
        "recipe_version": r["recipe_version"],
        "pack_format": r["pack_format"],
        "target_weight_kg": fmt_value(r["target_weight_kg"]),
        "required_components": fmt_value(r["required_components"]),
        "flavoring_kg": fmt_value(r["flavoring_kg"]),
        "allergen_tags": list(r["allergen_tags"]),
        "measured_moisture_pct": fmt_value(r["measured_moisture_pct"]),
        "yield_kg": fmt_value(r["yield_kg"]),
        "blended_by_user_id": r["blended_by_user_id"],
        "provisional_cost_cents": r["provisional_cost_cents"],
        "final_cost_cents": r["final_cost_cents"],
        "actual_weight_kg": fmt_value(r["actual_weight_kg"]),
        "cert_charges": fmt_value(r["cert_charges"]),
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def allocation_out(r):
    return {
        "id": r["id"],
        "batch_id": r["batch_id"],
        "lot_id": r["lot_id"],
        "allocated_kg": fmt_value(r["allocated_kg"]),
        "line_cost_cents": r["line_cost_cents"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def flavoring_application_out(r):
    return {
        "id": r["id"],
        "batch_id": r["batch_id"],
        "flavoring_id": r["flavoring_id"],
        "applied_kg": fmt_value(r["applied_kg"]),
        "applied_by_user_id": r["applied_by_user_id"],
        "flavoring_cost_cents": r["flavoring_cost_cents"],
        "created_at": fmt_ts(r["created_at"]),
    }


def line_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "line_type": r["line_type"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def run_out(r):
    return {
        "id": r["id"],
        "line_id": r["line_id"],
        "batch_id": r["batch_id"],
        "contract_id": r["contract_id"],
        "planned_start": fmt_ts(r["planned_start"]),
        "planned_end": fmt_ts(r["planned_end"]),
        "planned_units": r["planned_units"],
        "actual_units": r["actual_units"],
        "provisional_shelf_life_days": r["provisional_shelf_life_days"],
        "final_shelf_life_days": r["final_shelf_life_days"],
        "started_at": fmt_ts(r["started_at"]),
        "completed_at": fmt_ts(r["completed_at"]),
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def contract_out(r):
    return {
        "id": r["id"],
        "customer_name": r["customer_name"],
        "recipe_id": r["recipe_id"],
        "minimum_units_per_run": r["minimum_units_per_run"],
        "contracted_total_units": r["contracted_total_units"],
        "base_unit_price_cents": r["base_unit_price_cents"],
        "contract_unit_price_cents": r["contract_unit_price_cents"],
        "fulfilled_units": r["fulfilled_units"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def certificate_out(r):
    return {
        "id": r["id"],
        "supplier_id": r["supplier_id"],
        "cert_type": r["cert_type"],
        "total_volume_kg": fmt_value(r["total_volume_kg"]),
        "consumed_volume_kg": fmt_value(r["consumed_volume_kg"]),
        "valid_from": r["valid_from"].isoformat(),
        "valid_until": r["valid_until"].isoformat(),
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def active_allocations_of_batch(batch_id):
    return [
        a for a in store.allocations.values()
        if a["batch_id"] == batch_id and a["status"] == "ACTIVE"
    ]


def allocations_of_batch(batch_id):
    return [a for a in store.allocations.values() if a["batch_id"] == batch_id]


def latest_residue_test(lot_id):
    tests = [t for t in store.residue_tests.values() if t["lot_id"] == lot_id]
    if not tests:
        return None
    return max(tests, key=lambda t: t["test_round"])


def flavoring_applications_of_batch(batch_id):
    return [
        fa for fa in store.flavoring_applications.values()
        if fa["batch_id"] == batch_id
    ]


# ---------------------------------------------------------------------------
# calculation contracts
# ---------------------------------------------------------------------------
def compute_composite(aroma, briskness, appearance):
    """sensory_composite_grade: 1-decimal round-half-up, inclusive thresholds."""
    score = round1(
        Decimal(aroma) * W_AROMA
        + Decimal(briskness) * W_BRISKNESS
        + Decimal(appearance) * W_APPEARANCE
    )
    if score >= GRADE_A_MIN:
        grade = "A"
    elif score >= GRADE_B_MIN:
        grade = "B"
    elif score >= GRADE_C_MIN:
        grade = "C"
    else:
        grade = "REJECT"
    return score, grade


def compute_verdict(measured_ppm):
    """residue_verdict_threshold: 0.50 passes inclusive; hard-fail bound
    (> limit * 2.0) exclusive."""
    if measured_ppm <= RESIDUE_LIMIT_PPM:
        return "PASS"
    if measured_ppm > RESIDUE_LIMIT_PPM * HARD_FAIL_MULTIPLIER:
        return "FAIL_HARD"
    return "FAIL_SOFT"


def compute_recipe_scaling(target_weight_kg, components, flavoring_pct):
    """recipe_component_scaling: flavoring reserved BEFORE leaf normalization."""
    flavoring_kg = round3(target_weight_kg * flavoring_pct / Decimal(100))
    leaf_pool_kg = target_weight_kg - flavoring_kg
    leaf_pct_sum = sum(c["pct"] for c in components)
    required = []
    for c in components:
        required_kg = round3(leaf_pool_kg * c["pct"] / leaf_pct_sum)
        required.append({
            "leaf_type": c["leaf_type"],
            "min_grade": c["min_grade"],
            "required_kg": required_kg,
        })
    return required, flavoring_kg


def compute_line_cost_cents(allocated_kg, cost_per_kg_cents):
    return round_cents(allocated_kg * Decimal(cost_per_kg_cents))


def compute_provisional_cost_cents(batch_id):
    """batch_cost_accounting, provisional variant: per-line rounding then sum."""
    total = 0
    for a in active_allocations_of_batch(batch_id):
        lot = store.leaf_lots[a["lot_id"]]
        total += round_cents(a["allocated_kg"] * Decimal(lot["cost_per_kg_cents"]))
    return total


def compute_final_cost_cents(batch_id, provisional_cost_cents):
    """batch_cost_accounting, final variant: provisional + flavoring + 2% waste."""
    flavoring_total = sum(
        fa["flavoring_cost_cents"] for fa in flavoring_applications_of_batch(batch_id)
    )
    waste = round_cents(
        (Decimal(provisional_cost_cents) + Decimal(flavoring_total)) * WASTE_FACTOR
    )
    return provisional_cost_cents + flavoring_total + waste


def compute_yield_kg(batch_id):
    """moisture_adjusted_yield: per-line rounding THEN sum."""
    total = Decimal("0")
    for a in active_allocations_of_batch(batch_id):
        lot = store.leaf_lots[a["lot_id"]]
        m = lot["moisture_pct"]
        if m > TARGET_MOISTURE_PCT:
            factor = Decimal(1) - (m - TARGET_MOISTURE_PCT) / (
                Decimal(100) - TARGET_MOISTURE_PCT
            )
            total += round3(a["allocated_kg"] * factor)
        else:
            total += a["allocated_kg"]
    return total


def compute_provisional_shelf_life_days(batch):
    """packed_shelf_life, provisional variant: moisture-decay estimate only."""
    excess = batch["measured_moisture_pct"] - TARGET_MOISTURE_PCT
    if excess < 0:
        excess = Decimal(0)
    penalty_days = int((excess * 10).to_integral_value(rounding=ROUND_CEILING)) * 3
    return BASE_SHELF_DAYS[batch["pack_format"]] - penalty_days


def compute_final_shelf_life_days(run, batch, completion_dt):
    """packed_shelf_life, final variant: min of the provisional estimate and
    the oldest-lot harvest ceiling (PRD 3.7)."""
    provisional = run["provisional_shelf_life_days"]
    completion_date = completion_dt.date()
    harvest_terms = []
    for a in active_allocations_of_batch(batch["id"]):
        lot = store.leaf_lots[a["lot_id"]]
        age_days = (completion_date - lot["harvest_date"]).days
        harvest_terms.append(HARVEST_CEILING_DAYS - age_days)
    if harvest_terms:
        return min(provisional, min(harvest_terms))
    return provisional


def compute_contract_unit_price_cents(base_unit_price_cents, contracted_total_units,
                                      certification_target):
    """contract_unit_price: average-rate tier discount, cert multiplier, floor."""
    if contracted_total_units >= 100000:
        discount = Decimal("0.15")
    elif contracted_total_units >= 50000:
        discount = Decimal("0.10")
    elif contracted_total_units >= 10000:
        discount = Decimal("0.05")
    else:
        discount = Decimal("0.00")
    if certification_target == "ORGANIC":
        cert_mult = Decimal("1.20")
    elif certification_target == "FAIR_TRADE":
        cert_mult = Decimal("1.10")
    else:
        cert_mult = Decimal("1.00")
    price = round_cents(
        Decimal(base_unit_price_cents) * cert_mult * (Decimal(1) - discount)
    )
    return max(MIN_UNIT_PRICE_CENTS, price)


def supplier_contributions(batch):
    """Group the batch's ACTIVE allocations by lot.supplier_id, preserving
    first-allocation order. Returns list of (supplier_id, kg) pairs."""
    per_supplier = {}
    order = []
    for a in sorted(active_allocations_of_batch(batch["id"]),
                    key=lambda x: x["_seq"]):
        lot = store.leaf_lots[a["lot_id"]]
        sid = lot["supplier_id"]
        if sid not in per_supplier:
            per_supplier[sid] = Decimal("0")
            order.append(sid)
        per_supplier[sid] += a["allocated_kg"]
    return [(sid, per_supplier[sid]) for sid in order]


def find_valid_cert(supplier_id, cert_type):
    """The single ACTIVE cert of matching type whose closed validity interval
    contains the current logical-clock date."""
    today = clock.today()
    for c in store.certificates.values():
        if (
            c["supplier_id"] == supplier_id
            and c["cert_type"] == cert_type
            and c["status"] == "ACTIVE"
            and c["valid_from"] <= today <= c["valid_until"]
        ):
            return c
    return None


# ---------------------------------------------------------------------------
# cascade helpers (PRD 2.8)
# ---------------------------------------------------------------------------
def cancel_scheduled_runs_of_batch(batch):
    """Cascade link 3: SCHEDULED runs referencing the batch -> CANCELLED."""
    for run in store.production_runs.values():
        if run["batch_id"] == batch["id"] and run["status"] == "SCHEDULED":
            run["status"] = "CANCELLED"
            bump(run)


def hold_batches_for_lot(lot):
    """Cascade link 2 (+3): batches holding an ACTIVE allocation from a lot
    that just went ON_HOLD, in a holdable state, transition to ON_HOLD."""
    for a in store.allocations.values():
        if a["lot_id"] != lot["id"] or a["status"] != "ACTIVE":
            continue
        batch = store.batches.get(a["batch_id"])
        if batch is None or batch["status"] not in BATCH_HOLDABLE_STATES:
            continue
        batch["status"] = "ON_HOLD"
        bump(batch)
        cancel_scheduled_runs_of_batch(batch)


def release_batch_allocations(batch):
    """Cancel compensation: ACTIVE allocations -> RELEASED; each lot's
    remaining_weight_kg restored; DEPLETED lot back above 0 -> RELEASED."""
    for a in allocations_of_batch(batch["id"]):
        if a["status"] != "ACTIVE":
            continue
        a["status"] = "RELEASED"
        bump(a)
        lot = store.leaf_lots[a["lot_id"]]
        lot["remaining_weight_kg"] = lot["remaining_weight_kg"] + a["allocated_kg"]
        if lot["status"] == "DEPLETED" and lot["remaining_weight_kg"] > 0:
            lot["status"] = "RELEASED"
        bump(lot)


def certificate_expiry_sweep():
    """Clock side effect: ACTIVE/SUSPENDED grants whose valid_until date is
    earlier than the new current date transition to EXPIRED (PRD 2.5)."""
    today = clock.today()
    for c in store.certificates.values():
        if c["status"] in ("ACTIVE", "SUSPENDED") and c["valid_until"] < today:
            c["status"] = "EXPIRED"
            bump(c)
