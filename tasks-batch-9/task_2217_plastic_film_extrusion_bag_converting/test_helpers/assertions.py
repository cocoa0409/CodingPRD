"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    BagLotStatus,
    BlendRecipeStatus,
    ColorState,
    DossierStatus,
    ExtrusionRunStatus,
    FilmRollStatus,
    GaugeCapabilityState,
    LinePosture,
    PlateSetStatus,
    PrintJobStatus,
    RegistrationState,
)


def _assert_common(data: dict, entity: str) -> None:
    """id, created_at, updated_at and version are present on a mutable entity."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"


def _assert_append_only_common(data: dict, entity: str) -> None:
    """An append-only row carries id and created_at and nothing else common."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"


def _decimals(value, places: int, label: str) -> None:
    assert value is not None, f"{label} must not be null"
    text = f"{value:.{places + 3}f}".rstrip("0")
    rounded = round(float(value), places)
    assert abs(float(value) - rounded) < 1e-9, \
        f"{label} must carry at most {places} decimal places, got {value!r} ({text})"


# --------------------------------------------------------------------------
# Product
# --------------------------------------------------------------------------
def assert_product(data: dict) -> None:
    _assert_common(data, "Product")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert data["bag_style"] in ("FLAT", "GUSSETED", "BOTTOM_SEAL_LINER")
    assert isinstance(data["food_contact_required"], bool)
    assert isinstance(data["perforation_required"], bool)
    for field in ("target_gauge_micron", "gauge_tolerance_pct", "layflat_width_mm",
                  "bag_length_mm", "gusset_depth_mm", "min_bottom_seal_n_per_15mm",
                  "min_strength_index", "max_regrind_pct_food",
                  "max_regrind_pct_nonfood", "declared_recycled_content_pct",
                  "assumed_regrind_pcr_pct", "count_accuracy_tolerance_pct"):
        assert isinstance(data[field], (int, float)), f"Product.{field} must be numeric"
    for field in ("bags_per_case", "min_partial_case_bags", "cases_per_pallet",
                  "required_layer_count"):
        assert isinstance(data[field], int), f"Product.{field} must be an integer"


# --------------------------------------------------------------------------
# Resin grade
# --------------------------------------------------------------------------
def assert_resin_grade(data: dict) -> None:
    _assert_common(data, "ResinGrade")
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert data["material_class"] in ("VIRGIN_RESIN", "ADDITIVE_MASTERBATCH")
    assert data["polymer_family"] in ("LDPE", "LLDPE", "HDPE", "MDPE", "EVOH", "TIE")
    for field in ("melt_index", "density_kg_m3", "pcr_content_pct", "cost_per_kg",
                  "dart_impact_index", "haze_index", "cof_index",
                  "seal_initiation_temp_c"):
        assert isinstance(data[field], (int, float)), f"ResinGrade.{field} must be numeric"
    assert isinstance(data["food_contact_approved"], bool)
    assert isinstance(data["is_barrier"], bool)
    assert_cost_precision(data["cost_per_kg"])


# --------------------------------------------------------------------------
# Blend recipe
# --------------------------------------------------------------------------
def assert_blend_recipe(data: dict) -> None:
    _assert_common(data, "BlendRecipe")
    assert isinstance(data["recipe_code"], str) and data["recipe_code"]
    assert is_valid_uuid(data["product_id"])
    assert data["process_type"] in ("BLOWN", "CAST")
    assert isinstance(data["layer_count"], int) and data["layer_count"] >= 1
    assert data["status"] in [s.value for s in BlendRecipeStatus]
    assert isinstance(data["components"], list)
    assert isinstance(data["barrier_layer_present"], bool)
    assert isinstance(data["food_contact_eligible"], bool)
    assert isinstance(data["pinned_run_count"], int)
    assert isinstance(data["supersede_pending"], bool)


def assert_blend_recipe_derived_precision(data: dict) -> None:
    """Derived blend figures carry their declared decimal precision."""
    for field in ("total_weight_pct", "regrind_pct", "additive_pct", "hdpe_pct",
                  "virgin_pcr_pct", "regrind_cap_pct",
                  "nominal_recycled_content_pct"):
        _decimals(data[field], 3, f"BlendRecipe.{field}")
    for field in ("blend_cost_per_kg", "blended_density_kg_m3", "strength_index",
                  "clarity_index", "slip_index"):
        _decimals(data[field], 2, f"BlendRecipe.{field}")


# --------------------------------------------------------------------------
# Extrusion line
# --------------------------------------------------------------------------
def assert_extrusion_line(data: dict) -> None:
    _assert_common(data, "ExtrusionLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["process_type"] in ("BLOWN", "CAST")
    assert isinstance(data["max_layers"], int)
    for field in ("min_gauge_micron", "max_gauge_micron", "max_layflat_mm"):
        assert isinstance(data[field], (int, float))
    assert isinstance(data["purge_buffer_minutes"], int)
    assert isinstance(data["food_contact_certified"], bool)
    assert data["posture"] in [p.value for p in LinePosture]
    for field in ("incapable_run_count", "active_hold_count", "revoked_dossier_count"):
        assert isinstance(data[field], int) and data[field] >= 0


# --------------------------------------------------------------------------
# Extrusion run
# --------------------------------------------------------------------------
def assert_extrusion_run(data: dict) -> None:
    _assert_common(data, "ExtrusionRun")
    assert isinstance(data["run_code"], str) and data["run_code"]
    assert is_valid_uuid(data["line_id"])
    assert is_valid_uuid(data["blend_recipe_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in [s.value for s in ExtrusionRunStatus]
    assert isinstance(data["hold_count"], int) and data["hold_count"] >= 0
    assert isinstance(data["gauge_sample_count"], int)
    assert data["gauge_capability_state"] in [s.value for s in GaugeCapabilityState]


def assert_run_mass_balance(data: dict) -> None:
    """Good mass is gross output less scrap."""
    assert data["net_good_kg"] is not None, "net_good_kg must be written at completion"
    expected = round(data["gross_output_kg"] - data["scrap_kg"], 3)
    assert abs(data["net_good_kg"] - expected) < 0.0005, \
        f"net_good_kg {data['net_good_kg']} should equal gross - scrap ({expected})"
    _decimals(data["net_good_kg"], 3, "ExtrusionRun.net_good_kg")


# --------------------------------------------------------------------------
# Film roll
# --------------------------------------------------------------------------
def assert_film_roll(data: dict) -> None:
    _assert_common(data, "FilmRoll")
    assert is_valid_uuid(data["extrusion_run_id"])
    assert isinstance(data["roll_number"], int)
    assert isinstance(data["net_kg"], (int, float)) and data["net_kg"] > 0
    assert isinstance(data["layflat_mm"], (int, float))
    assert isinstance(data["gauge_micron_avg"], (int, float))
    assert data["status"] in [s.value for s in FilmRollStatus]


# --------------------------------------------------------------------------
# Regrind pool and transactions
# --------------------------------------------------------------------------
def assert_regrind_pool(data: dict) -> None:
    _assert_common(data, "RegrindPool")
    assert isinstance(data["pool_code"], str) and data["pool_code"]
    assert data["food_contact_status"] in ("FOOD_CONTACT_ELIGIBLE", "NON_FOOD_ONLY")
    assert data["polymer_family"] in ("LDPE", "LLDPE", "HDPE", "MDPE", "EVOH", "TIE")
    for field in ("available_kg", "cumulative_in_kg", "cumulative_out_kg",
                  "cumulative_in_pcr_kg"):
        assert isinstance(data[field], (int, float)) and data[field] >= 0, \
            f"RegrindPool.{field} must be a non-negative number"
    for field in ("generation_count", "reincorporation_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_pool_mass_invariants(data: dict) -> None:
    """available_kg is cumulative in less cumulative out, and never negative."""
    expected = round(data["cumulative_in_kg"] - data["cumulative_out_kg"], 3)
    assert abs(data["available_kg"] - expected) < 0.0005, \
        (f"available_kg {data['available_kg']} should equal cumulative_in_kg - "
         f"cumulative_out_kg ({expected})")
    assert data["available_kg"] >= 0, "available_kg must never fall below zero"


def assert_regrind_transaction(data: dict) -> None:
    """A ledger row carries only id and created_at as its system fields."""
    _assert_append_only_common(data, "RegrindTransaction")
    assert "updated_at" not in data, \
        "RegrindTransaction must not carry updated_at"
    assert "version" not in data, \
        "RegrindTransaction must not carry version"
    assert is_valid_uuid(data["pool_id"])
    assert data["direction"] in ("IN", "OUT")
    assert data["origin_kind"] in ("EXTRUSION_SCRAP", "ROLL_SCRAP", "LOT_SCRAP",
                                  "REINCORPORATION", "REVERSAL")
    assert isinstance(data["kg"], (int, float))
    assert isinstance(data["pcr_kg"], (int, float))
    assert isinstance(data["pool_available_kg_after"], (int, float))
    assert is_iso8601_timestamp(data["recorded_at"])


# --------------------------------------------------------------------------
# Print press, plate set, print job
# --------------------------------------------------------------------------
def assert_print_press(data: dict) -> None:
    _assert_common(data, "PrintPress")
    assert isinstance(data["press_code"], str) and data["press_code"]
    assert isinstance(data["cylinder_capacity"], int)
    assert isinstance(data["max_colors"], int)
    assert isinstance(data["registration_tolerance_micron"], (int, float))
    assert isinstance(data["max_delta_e"], (int, float))


def assert_plate_set(data: dict) -> None:
    _assert_common(data, "PlateSet")
    assert isinstance(data["plate_code"], str) and data["plate_code"]
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["color_count"], int)
    assert isinstance(data["wear_limit_impressions"], int)
    assert data["status"] in [s.value for s in PlateSetStatus]
    assert isinstance(data["impressions_count"], int)
    assert isinstance(data["nonconformance_count"], int)


def assert_print_job(data: dict) -> None:
    _assert_common(data, "PrintJob")
    assert isinstance(data["job_code"], str) and data["job_code"]
    assert is_valid_uuid(data["film_roll_id"])
    assert is_valid_uuid(data["plate_set_id"])
    assert is_valid_uuid(data["press_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["cylinders_required"], int)
    assert data["status"] in [s.value for s in PrintJobStatus]
    assert data["registration_state"] in [s.value for s in RegistrationState]
    assert data["color_state"] in [s.value for s in ColorState]
    assert isinstance(data["setup_attempt_count"], int)


# --------------------------------------------------------------------------
# Bag lot
# --------------------------------------------------------------------------
def assert_bag_lot(data: dict) -> None:
    _assert_common(data, "BagLot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert is_valid_uuid(data["print_job_id"])
    assert is_valid_uuid(data["product_id"])
    for field in ("bag_count_produced", "bag_count_scrapped", "bag_count_unpacked",
                  "packed_bag_count", "packed_case_count", "partial_case_bag_count",
                  "pallet_count"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"BagLot.{field} must be a non-negative integer"
    assert isinstance(data["seal_specimens"], list)
    assert isinstance(data["perforation_verified"], bool)
    assert isinstance(data["gusset_verified"], bool)
    assert isinstance(data["count_accuracy_conforming"], bool)
    assert data["status"] in [s.value for s in BagLotStatus]


def assert_bag_count_conservation(data: dict) -> None:
    """Good bags are either already packed or still waiting to be packed."""
    good = data["bag_count_produced"] - data["bag_count_scrapped"]
    total = data["packed_bag_count"] + data["bag_count_unpacked"]
    assert total == good, \
        (f"packed_bag_count + bag_count_unpacked ({total}) must equal "
         f"bag_count_produced - bag_count_scrapped ({good})")


# --------------------------------------------------------------------------
# Compliance dossier
# --------------------------------------------------------------------------
def assert_compliance_dossier(data: dict) -> None:
    _assert_common(data, "ComplianceDossier")
    assert isinstance(data["dossier_code"], str) and data["dossier_code"]
    assert is_valid_uuid(data["bag_lot_id"])
    assert isinstance(data["food_contact_declared"], bool)
    assert isinstance(data["recycled_content_claim_pct"], (int, float))
    assert data["status"] in [s.value for s in DossierStatus]
