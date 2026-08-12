"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every single test. Setup calls use the lenient
``get_success_data`` validator so a broken precondition reports as a setup
failure rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    complete_filling_payload,
    create_adjustment_payload,
    create_batch_payload,
    create_color_match_payload,
    create_colorant_payload,
    create_credit_claim_payload,
    create_customer_payload,
    create_disposal_request_payload,
    create_fill_payload,
    create_formula_payload,
    create_mill_payload,
    create_order_payload,
    create_tint_base_payload,
    create_voc_rule_payload,
    ship_payload,
    submit_qc_payload,
)
from .test_users import (
    LAB_TECHNICIAN,
    PLANT_MANAGER,
    PLANT_MANAGER_2,
    PRODUCTION_OPERATOR,
    QC_INSPECTOR,
    REGULATORY_CLERK,
    make_dealer_headers,
)


# ─── Tier 0: clock and primitive creators ─────────────


def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Move the logical clock; only a PlantManager may drive it (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, PLANT_MANAGER))


def create_tb1(**overrides) -> dict:
    """Canonical NONFLAT / LATEX_EXTERIOR base (voc 80, water 40%, spec 25)."""
    defaults = dict(base_code="B-100")
    defaults.update(overrides)
    return get_success_data(
        api_client.create_tint_base(create_tint_base_payload(**defaults), LAB_TECHNICIAN)
    )


def create_tb2(**overrides) -> dict:
    """Canonical FLAT / LATEX_INTERIOR base (voc 30, water 50%, spec 20)."""
    defaults = dict(
        base_code="B-200C", product_category="FLAT", base_family="LATEX_INTERIOR",
        base_voc_gpl=30, water_fraction_pct=50, density_kg_per_gal=4.4,
        base_cost_per_gal_cents=1800, unit_price_per_gal_cents=4100,
        shelf_life_months=24, grind_spec_um=20,
    )
    defaults.update(overrides)
    return get_success_data(
        api_client.create_tint_base(create_tint_base_payload(**defaults), LAB_TECHNICIAN)
    )


def create_tb3(**overrides) -> dict:
    """Canonical PRIMER / LATEX_INTERIOR base (voc 30, spec 20).

    Density is 4.6 kg/gal so that a batch filled into nominal-weight GALLON
    cans reconciles: with 4.4 the weigh gate (>= 4531 g per can) and the
    0.5% reconciliation band (<= 4422 g per can at 2 gal) admit no common
    fill weight, making it impossible to drive a TB3 batch to FILLED."""
    defaults = dict(
        base_code="B-300P", product_category="PRIMER", base_family="LATEX_INTERIOR",
        base_voc_gpl=30, water_fraction_pct=50, density_kg_per_gal=4.6,
        base_cost_per_gal_cents=1800, unit_price_per_gal_cents=4100,
        shelf_life_months=24, grind_spec_um=20,
    )
    defaults.update(overrides)
    return get_success_data(
        api_client.create_tint_base(create_tint_base_payload(**defaults), LAB_TECHNICIAN)
    )


def create_c1(**overrides) -> dict:
    """Canonical MAG-7 colorant (5 g voc/shot, 30c/shot, non-hazmat)."""
    defaults = dict(colorant_code="MAG-7")
    defaults.update(overrides)
    return get_success_data(
        api_client.create_colorant(create_colorant_payload(**defaults), LAB_TECHNICIAN)
    )


def create_c2(**overrides) -> dict:
    """Canonical BLK-H colorant (12 g voc/shot, 45c/shot, HAZMAT)."""
    defaults = dict(
        colorant_code="BLK-H", voc_g_per_unit=12, cost_per_shot_cents=45,
        is_hazmat=True,
    )
    defaults.update(overrides)
    return get_success_data(
        api_client.create_colorant(create_colorant_payload(**defaults), LAB_TECHNICIAN)
    )


def create_f1(tint_base_id, colorant_id, **overrides) -> dict:
    """Canonical stock formula on TB1 (dE 0.8, C1 x 4 shots/gal); stays DRAFT."""
    defaults = dict(formula_code="CLR-8841", color_name="Desert Dusk")
    defaults.update(overrides)
    return get_success_data(
        api_client.create_formula(
            create_formula_payload(tint_base_id, colorant_id, **defaults),
            LAB_TECHNICIAN,
        )
    )


def create_f2(tint_base_id, colorant_id, **overrides) -> dict:
    """Canonical custom formula on TB2 (dE 0.5, C2 x 6 shots/gal); stays DRAFT."""
    defaults = dict(
        formula_code="CLR-C100", color_name="Custom Ember", is_custom=True,
        target_delta_e=0.5,
        lines=[{"colorant_id": colorant_id, "shots_per_gallon": 6, "sequence": 1}],
    )
    defaults.update(overrides)
    return get_success_data(
        api_client.create_formula(
            create_formula_payload(tint_base_id, colorant_id, **defaults),
            LAB_TECHNICIAN,
        )
    )


def create_f3(tint_base_id, colorant_id, **overrides) -> dict:
    """Canonical primer formula on TB3 (dE 0.8, C1 x 2 shots/gal); stays DRAFT."""
    defaults = dict(
        formula_code="CLR-P9", color_name="Primer Grey", target_delta_e=0.8,
        lines=[{"colorant_id": colorant_id, "shots_per_gallon": 2, "sequence": 1}],
    )
    defaults.update(overrides)
    return get_success_data(
        api_client.create_formula(
            create_formula_payload(tint_base_id, colorant_id, **defaults),
            LAB_TECHNICIAN,
        )
    )


def activate_formula(formula_id) -> dict:
    return get_success_data(api_client.activate_formula(formula_id, LAB_TECHNICIAN))


def create_mill(**overrides) -> dict:
    defaults = dict(mill_code="M-1", capacity_gallons=200)
    defaults.update(overrides)
    return get_success_data(
        api_client.create_mill(create_mill_payload(**defaults), PLANT_MANAGER)
    )


def read_mill(mill_id) -> dict:
    return get_success_data(api_client.get_mill(mill_id, PLANT_MANAGER))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), PLANT_MANAGER)
    )


def read_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, PLANT_MANAGER))


def create_active_voc_rule(**overrides) -> dict:
    """Create a VOC rule and activate it. Returns the ACTIVE rule."""
    rule = get_success_data(
        api_client.create_voc_rule(create_voc_rule_payload(**overrides), REGULATORY_CLERK)
    )
    return get_success_data(api_client.activate_voc_rule(rule["id"], REGULATORY_CLERK))


# ─── Tier 1: batch state progression ──────────────────


def plan_batch(formula_id, mill_id, planned_gallons=3, order_id=None,
               window=("2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z")) -> dict:
    """Plan a batch (lands in PLANNED, reserves the mill window)."""
    payload = create_batch_payload(
        formula_id,
        mill_id,
        planned_gallons=planned_gallons,
        mill_window_start=window[0],
        mill_window_end=window[1],
    )
    if order_id is not None:
        payload["order_id"] = order_id
    return get_success_data(api_client.create_batch(payload, PRODUCTION_OPERATOR))


def start_batch(batch_id) -> dict:
    """PLANNED -> MILLING."""
    return get_success_data(api_client.start_mill(batch_id, PRODUCTION_OPERATOR))


def dispersion_pass(batch_id, grind_reading=18) -> dict:
    """A passing grind reading: MILLING -> TINTING."""
    return get_success_data(
        api_client.dispersion_check(batch_id, {"grind_reading": grind_reading},
                                    PRODUCTION_OPERATOR)
    )


def record_adjustment(batch_id, **overrides) -> dict:
    return get_success_data(
        api_client.record_adjustment(
            batch_id, create_adjustment_payload(**overrides), PRODUCTION_OPERATOR
        )
    )


def submit_qc(batch_id, actual_gallons=3) -> dict:
    """TINTING -> QC_PENDING (recomputes the batch VOC)."""
    return get_success_data(
        api_client.submit_qc(batch_id, submit_qc_payload(actual_gallons),
                             PRODUCTION_OPERATOR)
    )


def enter_measurement(batch_id, measured_delta_e=0.42,
                      measured_by=None) -> dict:
    """Enter a PENDING color measurement for a batch in QC_PENDING."""
    return get_success_data(
        api_client.create_color_match(
            create_color_match_payload(batch_id, measured_delta_e),
            measured_by or LAB_TECHNICIAN,
        )
    )


def approve_match(match_id, headers=None) -> dict:
    return get_success_data(
        api_client.approve_color_match(match_id, headers or QC_INSPECTOR)
    )


def reject_match(match_id, headers=None) -> dict:
    return get_success_data(
        api_client.reject_color_match(match_id, headers or QC_INSPECTOR)
    )


def read_batch(batch_id) -> dict:
    return get_success_data(api_client.get_batch(batch_id, PRODUCTION_OPERATOR))


def read_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, PLANT_MANAGER))


def read_container(container_id) -> dict:
    return get_success_data(api_client.get_container(container_id, PLANT_MANAGER))


def read_formula(formula_id) -> dict:
    return get_success_data(api_client.get_formula(formula_id, LAB_TECHNICIAN))


def read_color_match(match_id) -> dict:
    return get_success_data(api_client.get_color_match(match_id, PLANT_MANAGER))


def read_claim(claim_id) -> dict:
    return get_success_data(api_client.get_credit_claim(claim_id, PLANT_MANAGER))


def read_disposal_request(request_id) -> dict:
    return get_success_data(api_client.get_disposal_request(request_id, PLANT_MANAGER))


# ─── Tier 2/3: full batch lifecycle shortcuts ─────────


def drive_batch_to_qc_approved(batch_id, actual_gallons=3,
                               measured_delta_e=0.42,
                               milling_adjustments=None,
                               tinting_adjustments=None):
    """Walk a PLANNED batch to QC_APPROVED.

    milling_adjustments / tinting_adjustments: lists of adjustment payload
    overrides recorded while MILLING / TINTING respectively.
    Returns (batch, approved_match).
    """
    start_batch(batch_id)
    for adj in (milling_adjustments or []):
        record_adjustment(batch_id, **adj)
    dispersion_pass(batch_id)
    for adj in (tinting_adjustments or []):
        record_adjustment(batch_id, **adj)
    submit_qc(batch_id, actual_gallons)
    match = enter_measurement(batch_id, measured_delta_e)
    approve_match(match["id"])
    return read_batch(batch_id), read_color_match(match["id"])


def fill_container(batch_id, size_code="GALLON", actual_fill_g=4600) -> dict:
    return get_success_data(
        api_client.record_fill(
            batch_id, create_fill_payload(size_code, actual_fill_g),
            PRODUCTION_OPERATOR,
        )
    )


def complete_filling(batch_id, waste_gallons=0) -> dict:
    return get_success_data(
        api_client.complete_filling(
            batch_id, complete_filling_payload(waste_gallons), PRODUCTION_OPERATOR
        )
    )


def drive_batch_to_filled(batch_id, actual_gallons=3, fills=None,
                          waste_gallons=0, measured_delta_e=0.42,
                          milling_adjustments=None, tinting_adjustments=None):
    """Walk a PLANNED batch to FILLED, recording the given fills.
    Returns (batch, containers)."""
    drive_batch_to_qc_approved(
        batch_id, actual_gallons, measured_delta_e,
        milling_adjustments, tinting_adjustments,
    )
    containers = []
    for size_code, grams in (fills if fills is not None else
                             [("GALLON", 4600)] * int(actual_gallons)):
        containers.append(fill_container(batch_id, size_code, grams))
    batch = complete_filling(batch_id, waste_gallons)
    return batch, containers


# ─── Tier 2: catalogue and order composites ───────────


def setup_lab_catalog():
    """TB1 + C1 + F1 (DRAFT). Returns (tb1, c1, f1)."""
    tb1 = create_tb1()
    c1 = create_c1()
    f1 = create_f1(tb1["id"], c1["id"])
    return tb1, c1, f1


def setup_lab_catalog_active():
    """TB1 + C1 + F1 ACTIVE. Returns (tb1, c1, f1)."""
    tb1, c1, f1 = setup_lab_catalog()
    activate_formula(f1["id"])
    return tb1, c1, read_formula(f1["id"])


def setup_plant():
    """TB1 + C1 + F1 ACTIVE + mill M1. Returns (tb1, c1, f1, m1)."""
    tb1, c1, f1 = setup_lab_catalog_active()
    m1 = create_mill()
    return tb1, c1, f1, m1


def setup_plant_with_order(line_gallons=3, size_code="GALLON",
                           destination_state_code="AZ", rush_flag=False,
                           planned_gallons=None, window=None):
    """Plant + customer + one dealer order (not yet scheduled).
    Returns dict with tb1, c1, f1, m1, cu1, o1 keys."""
    tb1, c1, f1, m1 = setup_plant()
    cu1 = create_customer()
    order = get_success_data(
        api_client.create_order(
            create_order_payload(
                cu1["id"], f1["id"],
                destination_state_code=destination_state_code,
                rush_flag=rush_flag,
                lines=[{"formula_id": f1["id"], "gallons": line_gallons,
                        "size_code": size_code}],
            ),
            make_dealer_headers(cu1["id"]),
        )
    )
    return {"tb1": tb1, "c1": c1, "f1": f1, "m1": m1, "cu1": cu1, "o1": order}


# ─── Tier 5: shipped-container chain (credit claims) ──


def setup_shipped_container(freeze_events=0, line_gallons=3,
                            ship_clock="2026-06-15T09:00:00Z"):
    """Full production chain ending with one SHIPPED GALLON container.

    Containers are filled at logical time 2026-06-10T10:00:00Z, so with the
    canonical 24-month shelf life the expiry_date lands on 2028-06-10 — the
    date the credit-band tests calibrate `remaining_days_at_claim` against.

    Returns dict: tb1, c1, f1, m1, vr_nat, cu1, b1, o1, k1, others (the two
    extra cans filled alongside K1).
    """
    tb1, c1, f1, m1 = setup_plant()
    vr_nat = create_active_voc_rule(category="NONFLAT", state_code="*",
                                    max_voc_gpl=250, effective_from="2026-01-01")
    cu1 = create_customer(name="Sunbelt Paints AZ", home_state_code="AZ",
                          annual_credit_cap_cents=50000)
    b1 = plan_batch(f1["id"], m1["id"], planned_gallons=line_gallons)
    set_clock("2026-06-10T10:00:00Z")
    batch, containers = drive_batch_to_filled(
        b1["id"], actual_gallons=line_gallons,
        fills=[("GALLON", 4600)] * line_gallons, waste_gallons=0,
    )
    k1, others = containers[0], containers[1:]
    o1 = get_success_data(
        api_client.create_order(
            create_order_payload(
                cu1["id"], f1["id"],
                lines=[{"formula_id": f1["id"], "gallons": line_gallons,
                        "size_code": "GALLON"}],
            ),
            make_dealer_headers(cu1["id"]),
        )
    )
    set_clock(ship_clock)
    shipped = get_success_data(
        api_client.ship_container(k1["id"], ship_payload(o1["id"]),
                                  PRODUCTION_OPERATOR)
    )
    for _ in range(freeze_events):
        get_success_data(api_client.mark_freeze_exposure(k1["id"], PRODUCTION_OPERATOR))
    return {
        "tb1": tb1, "c1": c1, "f1": f1, "m1": m1, "vr_nat": vr_nat, "cu1": cu1,
        "b1": batch, "o1": o1, "k1": read_container(k1["id"]), "others": others,
        "shipped": shipped,
    }


def submit_claim(customer_id, container_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_credit_claim(
            create_credit_claim_payload(customer_id, container_id, **overrides),
            make_dealer_headers(customer_id),
        )
    )


def setup_approved_claim(freeze_events=3, claimed_exposure_count=1,
                         invoice_value_cents=40000,
                         claim_type="FREEZE_DAMAGE",
                         claim_clock="2026-06-20T08:00:00Z",
                         annual_credit_cap_cents=50000):
    """Full chain ending with an APPROVED credit claim.

    Returns dict with the shipped-container chain plus cl1 (approved claim).
    """
    env = setup_shipped_container(freeze_events=freeze_events)
    set_clock(claim_clock)
    cl1 = submit_claim(
        env["cu1"]["id"], env["k1"]["id"],
        claim_type=claim_type, invoice_value_cents=invoice_value_cents,
        claimed_exposure_count=claimed_exposure_count,
    )
    get_success_data(api_client.review_credit_claim(cl1["id"], REGULATORY_CLERK))
    approved = get_success_data(
        api_client.approve_credit_claim(cl1["id"], PLANT_MANAGER)
    )
    env["cl1"] = approved
    return env


def create_disposal_request(**overrides) -> dict:
    return get_success_data(
        api_client.create_disposal_request(
            create_disposal_request_payload(**overrides), REGULATORY_CLERK
        )
    )


def run_daily_sweep() -> dict:
    return get_success_data(api_client.run_daily_sweep(PLANT_MANAGER))
