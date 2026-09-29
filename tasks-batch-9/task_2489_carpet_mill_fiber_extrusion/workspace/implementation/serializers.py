"""Entity -> JSON projections.  Field lists come straight from SCAFFOLD entities."""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "account": (
        "id", "account_code", "account_type", "credit_limit_cents",
        "credit_used_cents", "status",
    ) + COMMON[1:],
    "polymer_lot": (
        "id", "lot_code", "polymer_type", "received_kg", "available_kg",
        "reserved_kg", "consumed_kg", "scrapped_kg", "recycled_content_pct",
        "segregated", "reclaim_source", "melt_flow_index", "status",
    ) + COMMON[1:],
    "reclamation_batch": (
        "id", "batch_code", "source_roll_good_id", "intake_lbs",
        "face_fiber_type", "contamination_pct", "depolymerized_kg",
        "output_polymer_lot_id", "status",
    ) + COMMON[1:],
    "fiber_batch": (
        "id", "batch_code", "polymer_lot_id", "input_kg", "blend_polymer_lot_id",
        "blend_input_kg", "denier_target", "filament_count", "dye_method",
        "solution_color_code", "throughput_g_per_min", "spin_speed_m_per_min",
        "denier_actual", "extruded_kg", "status",
    ) + COMMON[1:],
    "style": (
        "id", "style_code", "line_type", "gauge_code", "pile_construction",
        "pile_height_mm", "pattern_repeat_mm", "plies", "target_face_weight_oz",
        "dye_method", "solution_color_code", "list_price_cents_per_yard",
        "open_backorder_yards", "replenishment_flag", "status",
    ) + COMMON[1:],
    "machine": (
        "id", "machine_code", "native_gauge_code", "min_pile_height_mm",
        "max_pile_height_mm", "changeover_minutes", "needle_bar_width_in",
        "status",
    ) + COMMON[1:],
    "vessel": (
        "id", "vessel_code", "vessel_type", "capacity_kg", "status",
    ) + COMMON[1:],
    "run": (
        "id", "run_code", "style_id", "machine_id", "fiber_batch_id",
        "scheduled_start_utc", "scheduled_end_utc", "gauge_loaded_code",
        "pile_height_set_mm", "pattern_repeat_loaded_mm", "stitch_rate_per_inch",
        "greige_yards", "face_weight_oz_per_sy", "sbr_pct", "filler_load_pct",
        "cure_temp_c", "cure_seconds", "secondary_backing_type",
        "delamination_strength_lbf", "recoat_count", "status",
    ) + COMMON[1:],
    "dye_lot": (
        "id", "lot_code", "production_run_id", "vessel_id", "parent_dye_lot_id",
        "color_code", "target_lab_l", "target_lab_a", "target_lab_b",
        "measured_lab_l", "measured_lab_a", "measured_lab_b", "delta_e",
        "shade_band", "lot_kg", "dye_start_utc", "dye_end_utc", "dyed_yards",
        "scrapped_yards", "uncommitted_yards", "shipped_basis_uncommitted_yards",
        "redye_count", "status",
    ) + COMMON[1:],
    "roll_good": (
        "id", "roll_number", "production_run_id", "dye_lot_id", "parent_roll_id",
        "width_ft", "initial_yards", "available_yards", "shade_band",
        "is_remnant", "qa_status", "inventory_status",
    ) + COMMON[1:],
    "product_test": (
        "id", "style_id", "roll_good_id", "test_type", "result_value", "verdict",
        "tested_by_user_id", "tested_at_utc", "created_at",
    ),
    "certification": (
        "id", "style_id", "cert_type", "accounting_basis", "source_test_ids",
        "recorded_recycled_content_pct", "certified_by_user_id", "issued_at_utc",
        "expires_at_utc", "status",
    ) + COMMON[1:],
    "cut_order": (
        "id", "order_code", "account_id", "style_id", "order_type",
        "requested_yards", "shade_tolerance", "allocated_yards",
        "reserved_credit_cents", "gross_cents", "freight_cents",
        "remnant_credit_cents", "net_invoice_cents", "status",
    ) + COMMON[1:],
    "cut_allocation": (
        "id", "cut_order_id", "roll_good_id", "yards", "shade_band",
        "from_remnant", "line_cents", "status",
    ) + COMMON[1:],
}


def dump(kind, rec):
    fields = FIELDS[kind]
    out = {}
    for name in fields:
        out[name] = rec.get(name)
    return out


def dump_all(kind, recs):
    return [dump(kind, r) for r in recs]
