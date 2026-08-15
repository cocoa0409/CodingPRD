"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Fields carried by every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean(data: dict):
    """Immutable records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["resin_index_basis"] in ("MONTHLY_AVG", "SHIPMENT_DATE")
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert isinstance(data["open_exposure_cents"], int)


def assert_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["profile_code"], str) and data["profile_code"]
    dims = data["critical_dimensions"]
    assert isinstance(dims, list) and len(dims) >= 1
    for d in dims:
        for key in ("name", "nominal_mm", "tol_plus_mm", "tol_minus_mm", "ucl_mm", "lcl_mm"):
            assert key in d, f"critical_dimensions entry missing {key}"
    assert isinstance(data["spc_subgroup_size"], int)
    assert isinstance(data["sample_every_m"], int)
    assert isinstance(data["resin_content_kg_per_m"], (int, float))
    assert isinstance(data["min_line_speed_mpm"], (int, float))
    assert isinstance(data["max_line_speed_mpm"], (int, float))


def assert_die(data: dict):
    _assert_common(data)
    assert isinstance(data["profile_id"], str)
    assert isinstance(data["die_code"], str) and data["die_code"]
    assert isinstance(data["tooling_cost_cents"], int)
    assert isinstance(data["committed_length_m"], (int, float))
    assert isinstance(data["committed_weight_kg"], (int, float))
    assert data["amortization_mode"] in ("PER_METER", "PER_KG")
    assert isinstance(data["buffer_hours"], int)
    assert isinstance(data["min_screw_mm"], (int, float))
    assert isinstance(data["max_screw_mm"], (int, float))
    assert isinstance(data["amortized_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert data["status"] in ("DRAFT", "TRIAL", "QUALIFIED", "IN_SERVICE", "MAINTENANCE", "RETIRED")


def assert_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["screw_diameter_mm"], (int, float))
    assert data["status"] in ("IDLE", "SETUP", "RUNNING", "DOWN")


def assert_resin_lot(data: dict):
    _assert_common(data)
    assert data["lot_kind"] in ("VIRGIN", "REGRIND", "COLORANT")
    assert isinstance(data["resin_type"], str) and data["resin_type"]
    assert data["color_family"] in (
        "NATURAL", "WHITE", "YELLOW", "RED", "BLUE", "GREEN", "BROWN", "BLACK",
    )
    assert isinstance(data["received_kg"], (int, float))
    assert isinstance(data["consumed_kg"], (int, float))
    assert isinstance(data["available_kg"], (int, float))
    assert data["status"] in ("RECEIVED", "QC_PASSED", "QC_REJECTED", "DEPLETED")


def assert_formulation(data: dict):
    _assert_common(data)
    assert isinstance(data["profile_id"], str)
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert isinstance(data["base_resin_type"], str)
    assert isinstance(data["let_down_ratio"], (int, float))
    assert isinstance(data["max_regrind_pct"], (int, float))


def assert_blend_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["formulation_id"], str)
    assert isinstance(data["virgin_lot_id"], str)
    assert isinstance(data["colorant_lot_id"], str)
    assert isinstance(data["target_batch_kg"], (int, float))
    assert isinstance(data["colorant_kg"], (int, float))
    assert isinstance(data["regrind_kg"], (int, float))
    assert isinstance(data["virgin_kg"], (int, float))
    assert isinstance(data["actual_regrind_pct"], (int, float))
    assert data["status"] in ("BLENDED", "QC_RELEASED", "CONSUMED", "QUARANTINED")


def assert_work_order(data: dict):
    _assert_common(data)
    for key in ("customer_id", "profile_id", "formulation_id", "die_id"):
        assert isinstance(data[key], str)
    assert isinstance(data["ordered_length_m"], (int, float))
    assert isinstance(data["cut_length_mm"], int)
    assert isinstance(data["pieces_per_bundle"], int)
    assert isinstance(data["base_unit_price_cents_per_m"], (int, float))
    assert isinstance(data["quote_month"], str)
    assert isinstance(data["quote_index_cents_per_kg"], (int, float))
    assert isinstance(data["pass_through_adj_cents_per_m"], (int, float))
    assert isinstance(data["current_unit_price_cents_per_m"], (int, float))
    assert isinstance(data["produced_good_length_m"], (int, float))
    assert data["status"] in ("QUOTED", "CONFIRMED", "SCHEDULED", "IN_PRODUCTION", "CLOSED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED")


def assert_line_assignment(data: dict):
    _assert_common(data)
    for key in ("work_order_id", "die_id", "line_id"):
        assert isinstance(data[key], str)
    assert isinstance(data["planned_start"], str)
    assert isinstance(data["planned_end"], str)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED")


def assert_production_run(data: dict):
    _assert_common(data)
    assert isinstance(data["assignment_id"], str)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["line_speed_mpm"], (int, float))
    assert data["status"] in ("RUNNING", "HOLD", "COMPLETED")
    assert isinstance(data["samples_posted"], int)


def assert_spc_sample(data: dict):
    _assert_lean(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["dimension_name"], str)
    assert isinstance(data["measurements"], list)
    assert isinstance(data["xbar_mm"], (int, float))
    assert isinstance(data["range_mm"], (int, float))
    assert isinstance(data["ooc"], bool)
    assert isinstance(data["spec_violations"], int)


def assert_cut_bundle(data: dict):
    _assert_lean(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["bundle_seq"], int)
    assert isinstance(data["pieces"], int)
    assert isinstance(data["partial"], bool)
    assert isinstance(data["total_length_mm"], int)


def assert_purge_event(data: dict):
    _assert_lean(data)
    assert isinstance(data["line_id"], str)
    assert data["transition_class"] in (
        "SAME_RESIN_SAME_COLOR", "SAME_RESIN_LIGHT_TO_DARK",
        "SAME_RESIN_DARK_TO_LIGHT", "RESIN_CHANGE",
    )
    assert isinstance(data["scrap_kg"], (int, float))
    assert data["purge_grade"] in ("STANDARD", "HIGH_EFFICIENCY")


def assert_resin_index_point(data: dict):
    _assert_common(data)
    assert isinstance(data["month"], str)
    assert isinstance(data["index_cents_per_kg"], (int, float))


def assert_amortization_invariant(die: dict):
    """PRD §2.9: amortized_cents + remaining_balance_cents == tooling_cost_cents."""
    total = die["amortized_cents"] + die["remaining_balance_cents"]
    assert total == die["tooling_cost_cents"], (
        f"Amortization invariant broken: {die['amortized_cents']} + "
        f"{die['remaining_balance_cents']} != {die['tooling_cost_cents']}"
    )
    assert 0 <= die["amortized_cents"] <= die["tooling_cost_cents"]
    assert 0 <= die["remaining_balance_cents"] <= die["tooling_cost_cents"]


def assert_mass_balance(lot: dict):
    """PRD §2.9: available_kg == received_kg - consumed_kg."""
    assert abs(lot["available_kg"] - (lot["received_kg"] - lot["consumed_kg"])) < 1e-6, (
        f"Mass-balance invariant broken: available {lot['available_kg']} != "
        f"received {lot['received_kg']} - consumed {lot['consumed_kg']}"
    )
