"""Request-payload factories: one per write endpoint body.

Each factory returns only the fields a caller supplies. System-managed
properties (``id``, ``created_at``, ``updated_at``, ``version``) and every
derived field are never included — the API assigns those.

The defaults describe a coherent, valid shop: a P-group insert grade, a MEDIUM
CNMG geometry, a single-layer PVD stack, a catalogue insert priced at 4550
cents with a minimum order of 25, and a solid-carbide end mill that is long
enough to be reground. Pass keyword overrides to move one field off its
default while everything else stays valid.
"""

from typing import Optional


def _merge(base: dict, overrides: dict) -> dict:
    base.update(overrides)
    return base


# ─── Carbide grades ─────────────────────────────────────────────────────────

def carbide_grade_payload(**overrides) -> dict:
    """A P-group insert grade: 6.0 % cobalt binder, 1.2 um WC grain, 1600 HV."""
    return _merge(
        {
            "grade_code": "WC-P25",
            "target_workpiece_group": "P",
            "co_binder_pct": 6.0,
            "wc_grain_um": 1.2,
            "hardness_hv": 1600,
            "trs_mpa": 2100,
        },
        overrides,
    )


def endmill_grade_payload(**overrides) -> dict:
    """A K-group fine-grain grade used for the solid-carbide end mill."""
    return _merge(
        {
            "grade_code": "WC-K10",
            "target_workpiece_group": "K",
            "co_binder_pct": 6.0,
            "wc_grain_um": 0.8,
            "hardness_hv": 1750,
            "trs_mpa": 1900,
        },
        overrides,
    )


def stainless_grade_payload(**overrides) -> dict:
    """An M-group grade at 10.0 % cobalt — the grade-factor pivot point."""
    return _merge(
        {
            "grade_code": "WC-M15",
            "target_workpiece_group": "M",
            "co_binder_pct": 10.0,
            "wc_grain_um": 1.5,
            "hardness_hv": 1450,
            "trs_mpa": 2600,
        },
        overrides,
    )


def revise_grade_payload(**overrides) -> dict:
    """Restates the four metallurgical targets and records a revision note."""
    return _merge(
        {
            "co_binder_pct": 6.5,
            "wc_grain_um": 1.1,
            "hardness_hv": 1620,
            "trs_mpa": 2150,
            "revision_note": "Finer WC grain for edge-line stability",
        },
        overrides,
    )


def retire_grade_payload(**overrides) -> dict:
    return _merge({"retire_note": "Superseded by the next generation blend"}, overrides)


# ─── Powder blend batches ───────────────────────────────────────────────────

def powder_blend_batch_payload(grade_id: str, **overrides) -> dict:
    return _merge(
        {"grade_id": grade_id, "batch_code": "BLD-1", "planned_mass_kg": 120.0},
        overrides,
    )


def press_payload(**overrides) -> dict:
    return _merge({"pressed_units": 200}, overrides)


def sinter_payload(**overrides) -> dict:
    """Sinter figures that pass QC: density exactly 14.35, yield exactly 90.00 %."""
    return _merge(
        {
            "sintered_units": 180,
            "scrap_units": 20,
            "measured_density_gcc": 14.35,
            "measured_hardness_hv": 1580,
        },
        overrides,
    )


def failing_sinter_payload(**overrides) -> dict:
    """Sinter figures that fail QC on density alone (14.34), yield exactly 85.00 %."""
    return _merge(
        {
            "sintered_units": 170,
            "scrap_units": 30,
            "measured_density_gcc": 14.34,
            "measured_hardness_hv": 1580,
        },
        overrides,
    )


def quarantine_payload(**overrides) -> dict:
    return _merge(
        {"quarantine_reason": "Late eta-phase finding on the retained sample"},
        overrides,
    )


# ─── Insert geometries ──────────────────────────────────────────────────────

def insert_geometry_payload(**overrides) -> dict:
    """A MEDIUM-class CNMG turning geometry with a 0.8 mm nose radius."""
    return _merge(
        {
            "geometry_code": "CNMG-MM",
            "iso_designation": "CNMG120408",
            "application_class": "MEDIUM",
            "chipbreaker_code": "MM",
            "rake_angle_deg": 12.0,
            "nose_radius_mm": 0.8,
            "max_depth_of_cut_mm": 4.0,
            "edge_prep": "HONED",
        },
        overrides,
    )


def endmill_geometry_payload(**overrides) -> dict:
    """A four-flute end mill geometry, MEDIUM class, sharp edge."""
    return _merge(
        {
            "geometry_code": "EM-4F-30",
            "iso_designation": "EM10-4F",
            "application_class": "MEDIUM",
            "chipbreaker_code": "NONE",
            "rake_angle_deg": 10.0,
            "nose_radius_mm": 0.5,
            "max_depth_of_cut_mm": 10.0,
            "edge_prep": "SHARP",
        },
        overrides,
    )


def revise_geometry_payload(**overrides) -> dict:
    """Changes the chip breaker and edge preparation of a released geometry."""
    return _merge(
        {
            "chipbreaker_code": "MF",
            "rake_angle_deg": 14.0,
            "nose_radius_mm": 0.8,
            "max_depth_of_cut_mm": 4.0,
            "edge_prep": "CHAMFERED",
            "revision_note": "Softer chip breaker for gummy steels",
        },
        overrides,
    )


# ─── Coating recipes ────────────────────────────────────────────────────────

def coating_recipe_payload(**overrides) -> dict:
    """A single-layer PVD stack: 3.0 um of TiAlN, total 3.00 um."""
    return _merge(
        {
            "recipe_code": "PVD-TIALN-3",
            "deposition_type": "PVD",
            "layers": [{"material": "TiAlN", "thickness_um": 3.0}],
        },
        overrides,
    )


def cvd_recipe_payload(**overrides) -> dict:
    """A single-layer CVD stack: 4.0 um of TiCN."""
    return _merge(
        {
            "recipe_code": "CVD-TICN-4",
            "deposition_type": "CVD",
            "layers": [{"material": "TiCN", "thickness_um": 4.0}],
        },
        overrides,
    )


def duo_layer_recipe_payload(**overrides) -> dict:
    """Two unlike adjacent layers: TiN 2.0 then TiAlN 1.5, total 3.50 um."""
    return _merge(
        {
            "recipe_code": "PVD-DUO-35",
            "deposition_type": "PVD",
            "layers": [
                {"material": "TiN", "thickness_um": 2.0},
                {"material": "TiAlN", "thickness_um": 1.5},
            ],
        },
        overrides,
    )


def revise_recipe_payload(**overrides) -> dict:
    return _merge(
        {
            "layers": [
                {"material": "AlCrN", "thickness_um": 2.5},
                {"material": "TiN", "thickness_um": 1.0},
            ],
            "revision_note": "AlCrN base for higher hot hardness",
        },
        overrides,
    )


# ─── Coating runs ───────────────────────────────────────────────────────────

def coating_run_payload(recipe_id: str, **overrides) -> dict:
    """A six-hour half-open chamber window carrying 2500.00 cm2 in CH1."""
    return _merge(
        {
            "recipe_id": recipe_id,
            "chamber_id": "CH1",
            "window_start": "2026-08-05T06:00:00Z",
            "window_end": "2026-08-05T12:00:00Z",
            "loaded_area_cm2": 2500.00,
        },
        overrides,
    )


def complete_coating_run_payload(**overrides) -> dict:
    """Adhesion class 2 and 3.10 um measured against a 3.00 um nominal stack."""
    return _merge({"adhesion_hf_class": 2, "measured_thickness_um": 3.10}, overrides)


# ─── Grinding wheels and runs ───────────────────────────────────────────────

def grinding_wheel_payload(**overrides) -> dict:
    return _merge(
        {"wheel_code": "WH-1", "spec_code": "D64-C100", "initial_life_units": 1000},
        overrides,
    )


def grinding_run_payload(wheel_id: str, product_id: str, **overrides) -> dict:
    """A four-hour closed cell window in CELL_A planned for 43 tools."""
    return _merge(
        {
            "wheel_id": wheel_id,
            "product_id": product_id,
            "cell_id": "CELL_A",
            "window_start": "2026-08-12T06:00:00Z",
            "window_end": "2026-08-12T10:00:00Z",
            "planned_units": 43,
        },
        overrides,
    )


def complete_grinding_run_payload(**overrides) -> dict:
    """40 good and 3 scrapped tools at a 4.5 um diameter deviation."""
    return _merge(
        {"produced_units": 40, "scrap_units": 3, "measured_diameter_dev_um": 4.5},
        overrides,
    )


def void_grinding_run_payload(**overrides) -> dict:
    return _merge(
        {"void_reason": "Metrology dispute; the deviation record is not traceable"},
        overrides,
    )


def dress_wheel_payload(**overrides) -> dict:
    return _merge({"dress_note": "Rotary dress to full profile"}, overrides)


# ─── Tool products ──────────────────────────────────────────────────────────

def tool_product_payload(grade_id: str, geometry_id: str, **overrides) -> dict:
    """A catalogue insert at 4550 cents with a minimum order of 25 pieces."""
    return _merge(
        {
            "sku": "CAT-INS-1",
            "order_class": "CATALOG",
            "grade_id": grade_id,
            "geometry_id": geometry_id,
            "tool_type": "INSERT",
            "list_price_cents": 4550,
            "min_order_qty": 25,
            "nominal_length_mm": 12.7,
            "min_regrind_length_mm": 12.2,
            "regrind_step_mm": 0.5,
            "grind_units_per_tool": 20,
        },
        overrides,
    )


def endmill_product_payload(grade_id: str, geometry_id: str, **overrides) -> dict:
    """A regrindable end mill: 100.0 mm long, floor 70.0 mm, 2.5 mm per pass."""
    return _merge(
        {
            "sku": "EM-10-1",
            "order_class": "CATALOG",
            "grade_id": grade_id,
            "geometry_id": geometry_id,
            "tool_type": "SOLID_CARBIDE_ENDMILL",
            "list_price_cents": 12000,
            "min_order_qty": 1,
            "nominal_length_mm": 100.0,
            "min_regrind_length_mm": 70.0,
            "regrind_step_mm": 2.5,
            "grind_units_per_tool": 20,
        },
        overrides,
    )


def special_product_payload(
    grade_id: str,
    geometry_id: str,
    coating_recipe_id: str,
    base_catalog_product_id: str,
    **overrides,
) -> dict:
    """An engineered special derived from a released catalogue insert."""
    return _merge(
        {
            "sku": "SPE-PVD-1",
            "order_class": "SPECIAL",
            "grade_id": grade_id,
            "geometry_id": geometry_id,
            "coating_recipe_id": coating_recipe_id,
            "base_catalog_product_id": base_catalog_product_id,
            "tool_type": "INSERT",
            "list_price_cents": 5800,
            "min_order_qty": 5,
            "nominal_length_mm": 12.7,
            "min_regrind_length_mm": 12.2,
            "regrind_step_mm": 0.5,
            "grind_units_per_tool": 20,
        },
        overrides,
    )


def set_supply_status_payload(supply_status: str) -> dict:
    return {"supply_status": supply_status}


def withdraw_product_payload(**overrides) -> dict:
    return _merge({"withdraw_reason": "Replaced by the next catalogue generation"}, overrides)


def speeds_feeds_params(**overrides) -> dict:
    """Query parameters for the speeds-and-feeds recommendation read."""
    return _merge(
        {"workpiece_group": "P", "machine_rigidity": "RIGID", "coolant": "FLOOD"},
        overrides,
    )


# ─── Qualification dossiers ─────────────────────────────────────────────────

def dossier_payload(product_id: str, **overrides) -> dict:
    return _merge({"product_id": product_id, "dossier_code": "DOS-1"}, overrides)


def approve_dossier_payload(**overrides) -> dict:
    return _merge({"decision_note": "Qualified on P and M"}, overrides)


def reject_dossier_payload(**overrides) -> dict:
    return _merge({"decision_note": "Evidence is too thin on the M group"}, overrides)


# ─── Machining trials ───────────────────────────────────────────────────────

def trial_payload(dossier_id: str, batch_id: str, **overrides) -> dict:
    """A P-group trial on C45E under flood coolant, drawing 20 test tools."""
    return _merge(
        {
            "dossier_id": dossier_id,
            "batch_id": batch_id,
            "trial_code": "TRL-1",
            "workpiece_material_code": "C45E",
            "workpiece_group": "P",
            "units_consumed": 20,
            "cutting_speed_vc": 250.0,
            "feed_fz": 0.25,
            "depth_ap": 2.0,
            "coolant": "FLOOD",
        },
        overrides,
    )


def second_trial_payload(dossier_id: str, batch_id: str, **overrides) -> dict:
    """An M-group trial on SS316L through the tool, drawing 20 test tools."""
    return _merge(
        {
            "dossier_id": dossier_id,
            "batch_id": batch_id,
            "trial_code": "TRL-2",
            "workpiece_material_code": "SS316L",
            "workpiece_group": "M",
            "units_consumed": 20,
            "cutting_speed_vc": 180.0,
            "feed_fz": 0.20,
            "depth_ap": 2.0,
            "coolant": "THROUGH_TOOL",
        },
        overrides,
    )


def complete_trial_payload(**overrides) -> dict:
    """A six-point wear curve that crosses 300 um between 18 and 24 minutes."""
    return _merge(
        {
            "wear_measurements": [
                {"minutes": 0, "vb_um": 0},
                {"minutes": 6, "vb_um": 150},
                {"minutes": 12, "vb_um": 225},
                {"minutes": 18, "vb_um": 290},
                {"minutes": 24, "vb_um": 320},
                {"minutes": 30, "vb_um": 340},
            ],
            "measured_surface_ra_um": 1.20,
        },
        overrides,
    )


def complete_second_trial_payload(**overrides) -> dict:
    """A five-point wear curve that crosses 300 um between 16 and 24 minutes."""
    return _merge(
        {
            "wear_measurements": [
                {"minutes": 0, "vb_um": 0},
                {"minutes": 8, "vb_um": 160},
                {"minutes": 16, "vb_um": 250},
                {"minutes": 24, "vb_um": 305},
                {"minutes": 32, "vb_um": 330},
            ],
            "measured_surface_ra_um": 1.50,
        },
        overrides,
    )


# ─── Customers and orders ───────────────────────────────────────────────────

def customer_payload(**overrides) -> dict:
    return _merge(
        {
            "customer_code": "CU-1",
            "name": "Acme Machining",
            "tier": "PREFERRED",
            "regrind_credit_cents": 50000,
        },
        overrides,
    )


def credit_adjustment_payload(delta_cents: int, **overrides) -> dict:
    return _merge(
        {
            "delta_cents": delta_cents,
            "reason": "Chargeback on the prior reconditioning cycle",
        },
        overrides,
    )


def close_customer_payload(**overrides) -> dict:
    return _merge({"close_reason": "Account consolidated into the parent group"}, overrides)


def tool_order_payload(
    customer_id: str, product_id: str, expected_product_version: int, **overrides
) -> dict:
    """A 100-piece catalogue order — the tier that carries the 7 % discount."""
    return _merge(
        {
            "customer_id": customer_id,
            "product_id": product_id,
            "order_code": "SO-1",
            "quantity": 100,
            "expedite_requested": False,
            "expected_product_version": expected_product_version,
        },
        overrides,
    )


def cancel_order_payload(**overrides) -> dict:
    return _merge({"cancel_reason": "Customer rescheduled the programme"}, overrides)


# ─── Reconditioning jobs ────────────────────────────────────────────────────

def recondition_job_payload(
    customer_id: str,
    product_id: str,
    expected_customer_version: int,
    predecessor_job_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Intake of 10 tools — a reservation of 10 x 1850 = 18500 cents."""
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "job_code": "RJ-1",
        "units_received": 10,
        "expected_customer_version": expected_customer_version,
    }
    if predecessor_job_id is not None:
        payload["predecessor_job_id"] = predecessor_job_id
    return _merge(payload, overrides)


def inspect_job_payload(**overrides) -> dict:
    """A measured length of 82.5 mm — five 2.5 mm passes above the 70.0 mm floor."""
    return _merge(
        {
            "units_inspected": 10,
            "measured_length_mm": 82.5,
            "measured_corner_wear_um": 120,
        },
        overrides,
    )


def refurbish_job_payload(wheel_id: str, **overrides) -> dict:
    return _merge({"wheel_id": wheel_id, "recoat_applied": False}, overrides)


def return_job_payload(**overrides) -> dict:
    return _merge({"units_returned": 10}, overrides)


def scrap_job_payload(**overrides) -> dict:
    return _merge(
        {"scrap_reason": "Measured length is below the minimum regrind length"},
        overrides,
    )
