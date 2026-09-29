"""Payload factories -- one per creatable resource, input fields only."""


# --------------------------------------------------------------------------
# Product
# --------------------------------------------------------------------------
def food_contact_product_payload(**overrides) -> dict:
    """Three-layer food-contact flat bag product."""
    payload = {
        "product_code": "P-FD-1",
        "customer_code": "CUST-FD",
        "bag_style": "FLAT",
        "food_contact_required": True,
        "target_gauge_micron": 50.0,
        "gauge_tolerance_pct": 8.0,
        "layflat_width_mm": 300.0,
        "bag_length_mm": 450.0,
        "gusset_depth_mm": 0.0,
        "perforation_required": False,
        "min_bottom_seal_n_per_15mm": 22.0,
        "min_strength_index": 30.0,
        "max_regrind_pct_food": 10.0,
        "max_regrind_pct_nonfood": 35.0,
        "declared_recycled_content_pct": 0.0,
        "assumed_regrind_pcr_pct": 5.0,
        "bags_per_case": 500,
        "min_partial_case_bags": 200,
        "cases_per_pallet": 40,
        "count_accuracy_tolerance_pct": 2.0,
        "required_layer_count": 3,
    }
    payload.update(overrides)
    return payload


def non_food_product_payload(**overrides) -> dict:
    """Single-layer gusseted, perforated non-food product."""
    payload = {
        "product_code": "P-NF-1",
        "customer_code": "CUST-NF",
        "bag_style": "GUSSETED",
        "food_contact_required": False,
        "target_gauge_micron": 40.0,
        "gauge_tolerance_pct": 10.0,
        "layflat_width_mm": 400.0,
        "bag_length_mm": 600.0,
        "gusset_depth_mm": 60.0,
        "perforation_required": True,
        "min_bottom_seal_n_per_15mm": 18.0,
        "min_strength_index": 25.0,
        "max_regrind_pct_food": 10.0,
        "max_regrind_pct_nonfood": 35.0,
        "declared_recycled_content_pct": 0.0,
        "assumed_regrind_pcr_pct": 25.0,
        "bags_per_case": 250,
        "min_partial_case_bags": 100,
        "cases_per_pallet": 30,
        "count_accuracy_tolerance_pct": 3.0,
        "required_layer_count": 1,
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    return non_food_product_payload(**overrides)


# --------------------------------------------------------------------------
# Resin grades
# --------------------------------------------------------------------------
def create_resin_grade_payload(**overrides) -> dict:
    payload = {
        "grade_code": "LL-1001",
        "material_class": "VIRGIN_RESIN",
        "polymer_family": "LLDPE",
        "melt_index": 1.0,
        "density_kg_m3": 918.0,
        "food_contact_approved": True,
        "pcr_content_pct": 0.0,
        "cost_per_kg": 1.45,
        "dart_impact_index": 42.0,
        "haze_index": 8.0,
        "cof_index": 0.42,
        "seal_initiation_temp_c": 105.0,
        "is_barrier": False,
    }
    payload.update(overrides)
    return payload


def lldpe_grade_payload(**overrides) -> dict:
    return create_resin_grade_payload(**overrides)


def barrier_grade_payload(**overrides) -> dict:
    """EVOH barrier resin."""
    payload = create_resin_grade_payload(
        grade_code="EV-4004",
        polymer_family="EVOH",
        melt_index=3.0,
        density_kg_m3=1170.0,
        cost_per_kg=8.9,
        dart_impact_index=12.0,
        haze_index=4.0,
        cof_index=0.35,
        seal_initiation_temp_c=180.0,
        is_barrier=True,
    )
    payload.update(overrides)
    return payload


def tie_grade_payload(**overrides) -> dict:
    payload = create_resin_grade_payload(
        grade_code="TI-5005",
        polymer_family="TIE",
        melt_index=2.0,
        density_kg_m3=930.0,
        cost_per_kg=3.4,
        dart_impact_index=20.0,
        haze_index=5.0,
        cof_index=0.45,
        seal_initiation_temp_c=120.0,
    )
    payload.update(overrides)
    return payload


def additive_grade_payload(**overrides) -> dict:
    payload = create_resin_grade_payload(
        grade_code="AD-6006",
        material_class="ADDITIVE_MASTERBATCH",
        polymer_family="LLDPE",
        melt_index=5.0,
        density_kg_m3=940.0,
        cost_per_kg=4.2,
        dart_impact_index=15.0,
        haze_index=12.0,
        cof_index=0.12,
        seal_initiation_temp_c=110.0,
    )
    payload.update(overrides)
    return payload


def hdpe_grade_payload(**overrides) -> dict:
    """Stiff HDPE grade -- carries the family strength penalty."""
    payload = create_resin_grade_payload(
        grade_code="HD-3003",
        polymer_family="HDPE",
        melt_index=0.05,
        density_kg_m3=952.0,
        cost_per_kg=1.28,
        dart_impact_index=18.0,
        haze_index=22.0,
        cof_index=0.3,
        seal_initiation_temp_c=125.0,
    )
    payload.update(overrides)
    return payload


def pcr_grade_payload(**overrides) -> dict:
    """Post-consumer resin that is NOT approved for food contact."""
    payload = create_resin_grade_payload(
        grade_code="PC-7007",
        polymer_family="LLDPE",
        melt_index=1.2,
        density_kg_m3=920.0,
        food_contact_approved=False,
        pcr_content_pct=100.0,
        cost_per_kg=1.1,
        dart_impact_index=30.0,
        haze_index=30.0,
        cof_index=0.55,
        seal_initiation_temp_c=108.0,
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Blend recipes and components
# --------------------------------------------------------------------------
def create_blend_recipe_payload(product_id, **overrides) -> dict:
    payload = {
        "recipe_code": "R-NF-1",
        "product_id": product_id,
        "process_type": "BLOWN",
        "layer_count": 1,
    }
    payload.update(overrides)
    return payload


def create_component_payload(**overrides) -> dict:
    payload = {
        "layer_index": 1,
        "component_kind": "VIRGIN",
        "weight_pct": 100.0,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Extrusion lines
# --------------------------------------------------------------------------
def create_extrusion_line_payload(**overrides) -> dict:
    payload = {
        "line_code": "L-NF",
        "process_type": "BLOWN",
        "max_layers": 3,
        "min_gauge_micron": 20.0,
        "max_gauge_micron": 120.0,
        "max_layflat_mm": 900.0,
        "purge_buffer_minutes": 45,
        "food_contact_certified": False,
    }
    payload.update(overrides)
    return payload


def food_certified_line_payload(**overrides) -> dict:
    payload = create_extrusion_line_payload(
        line_code="L-FD",
        max_layers=5,
        purge_buffer_minutes=60,
        food_contact_certified=True,
    )
    payload.update(overrides)
    return payload


def narrow_line_payload(**overrides) -> dict:
    """Line whose maximum layflat is narrower than the wide default."""
    payload = create_extrusion_line_payload(
        line_code="L-SM",
        max_layflat_mm=300.0,
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Extrusion runs
# --------------------------------------------------------------------------
def create_extrusion_run_payload(line_id, blend_recipe_id, **overrides) -> dict:
    payload = {
        "run_code": "RUN-NF-1",
        "line_id": line_id,
        "blend_recipe_id": blend_recipe_id,
        "scheduled_start": "2026-08-05T06:00:00Z",
        "scheduled_end": "2026-08-05T14:00:00Z",
        "target_output_kg": 500.0,
    }
    payload.update(overrides)
    return payload


def create_gauge_reading_payload(thickness_micron, **overrides) -> dict:
    payload = {"thickness_micron": thickness_micron}
    payload.update(overrides)
    return payload


def create_reincorporation_payload(pool_id, kg, expected_regrind_pool_version) -> dict:
    return {
        "pool_id": pool_id,
        "kg": kg,
        "expected_regrind_pool_version": expected_regrind_pool_version,
    }


# --------------------------------------------------------------------------
# Film rolls
# --------------------------------------------------------------------------
def create_film_roll_payload(extrusion_run_id, roll_number, net_kg, **overrides) -> dict:
    payload = {
        "extrusion_run_id": extrusion_run_id,
        "roll_number": roll_number,
        "net_kg": net_kg,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Regrind pools
# --------------------------------------------------------------------------
def create_regrind_pool_payload(**overrides) -> dict:
    payload = {
        "pool_code": "POOL-NF",
        "food_contact_status": "NON_FOOD_ONLY",
        "polymer_family": "LLDPE",
    }
    payload.update(overrides)
    return payload


def food_contact_pool_payload(**overrides) -> dict:
    payload = create_regrind_pool_payload(
        pool_code="POOL-FD",
        food_contact_status="FOOD_CONTACT_ELIGIBLE",
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Print presses, plate sets, print jobs
# --------------------------------------------------------------------------
def create_print_press_payload(**overrides) -> dict:
    payload = {
        "press_code": "PR-1",
        "cylinder_capacity": 8,
        "max_colors": 6,
        "registration_tolerance_micron": 80.0,
        "max_delta_e": 2.0,
    }
    payload.update(overrides)
    return payload


def create_plate_set_payload(product_id, **overrides) -> dict:
    payload = {
        "plate_code": "PL-1",
        "product_id": product_id,
        "color_count": 4,
    }
    payload.update(overrides)
    return payload


def create_print_job_payload(film_roll_id, plate_set_id, press_id, **overrides) -> dict:
    payload = {
        "job_code": "PJ-1",
        "film_roll_id": film_roll_id,
        "plate_set_id": plate_set_id,
        "press_id": press_id,
        "window_start": "2026-08-05T06:00:00Z",
        "window_end": "2026-08-05T18:00:00Z",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Bag lots and seal specimens
# --------------------------------------------------------------------------
def create_bag_lot_payload(print_job_id, product_id, bag_count_produced,
                           **overrides) -> dict:
    payload = {
        "lot_code": "BL-1",
        "print_job_id": print_job_id,
        "product_id": product_id,
        "bag_count_produced": bag_count_produced,
    }
    payload.update(overrides)
    return payload


def create_seal_test_payload(specimen_index, measured_n_per_15mm, **overrides) -> dict:
    payload = {
        "specimen_index": specimen_index,
        "measured_n_per_15mm": measured_n_per_15mm,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Compliance dossiers
# --------------------------------------------------------------------------
def create_compliance_dossier_payload(bag_lot_id, **overrides) -> dict:
    payload = {
        "dossier_code": "CD-1",
        "bag_lot_id": bag_lot_id,
        "food_contact_declared": False,
        "recycled_content_claim_pct": 0.0,
    }
    payload.update(overrides)
    return payload
