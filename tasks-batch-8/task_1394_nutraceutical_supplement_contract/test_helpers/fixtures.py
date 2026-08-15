"""Composite setup helpers for the nutraceutical contract manufacturing API.

Every helper builds its preconditions from scratch through the public API and
uses the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors. Ownership-gated order calls thread the real
Customer.id through make_brandrep_headers(); segregation-of-duties workflows
(§2.10) thread distinct operator identities for recording and review steps.

Batch lifecycle ladder used by run_batch():
  SCHEDULED -> IN_PROCESS -> COMPLETED -> RECORD_REVIEWED
    -> ASSAY_ACCEPTED (quality QC_READY) -> STUDY_COMPLETED -> RELEASED
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACTUAL_BULK_MASS_G,
    ACTUAL_YIELD_UNITS,
    CONSUMPTION_QTY,
    DEFAULT_CHEMIST_ID,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_OPERATOR_ID,
    DEFAULT_QA_MANAGER_ID,
    LINE_DEFAULTS,
    LOT_QTY_RECEIVED,
    ORDERED_QTY,
    WINDOW_DAY1,
    WINDOW_DAY2,
)
from .factories import (
    create_amendment_payload,
    create_assay_payload,
    create_assay_review_payload,
    create_cleaning_validation_payload,
    create_coa_review_payload,
    create_completion_payload,
    create_consumption_payload,
    create_customer_payload,
    create_formula_line_payload,
    create_formula_payload,
    create_identity_test_payload,
    create_manufacturing_order_payload,
    create_material_lot_payload,
    create_production_line_payload,
    create_raw_material_payload,
    create_recall_payload,
    create_schedule_payload,
    create_stability_chamber_payload,
    create_stability_study_payload,
    create_study_completion_payload,
    create_swab_payload,
)
from .test_users import (
    TEST_USERS,
    make_brandrep_headers,
    make_production_operator_headers,
    make_qa_chemist_headers,
    make_qa_manager_headers,
)

PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]
CHEMIST = TEST_USERS["qa_chemist_headers"]
QA = TEST_USERS["qa_manager_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_INSTANT):
    """Advance the logical clock; restricted to ProductionPlanner/QAManager."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, QA))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and read helpers
# ---------------------------------------------------------------------------

def create_customer(brand_name="Acme") -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(brand_name), PLANNER)
    )


def get_customer(customer_id, headers=None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or QA))


def create_raw_material(name="VitC", allergen_class="NONE") -> dict:
    return get_success_data(
        api_client.create_raw_material(
            create_raw_material_payload(name, allergen_class), PLANNER
        )
    )


def create_production_line(name="L1") -> dict:
    return get_success_data(
        api_client.create_production_line(create_production_line_payload(name), PLANNER)
    )


def get_production_line(line_id, headers=None) -> dict:
    return get_success_data(api_client.get_production_line(line_id, headers or QA))


def create_stability_chamber(name="CH1", capacity_units=50000) -> dict:
    return get_success_data(
        api_client.create_stability_chamber(
            create_stability_chamber_payload(name, capacity_units), PLANNER
        )
    )


def get_stability_chamber(chamber_id, headers=None) -> dict:
    return get_success_data(api_client.get_stability_chamber(chamber_id, headers or QA))


def create_material_lot(
    raw_material_id,
    qty_received=LOT_QTY_RECEIVED,
    supplier_name="SuppCo",
    supplier_coa_ref="COA-1",
    op_id=DEFAULT_OPERATOR_ID,
) -> dict:
    """Receive a supplier lot; it enters QUARANTINE (PRD §3.2)."""
    return get_success_data(
        api_client.create_material_lot(
            create_material_lot_payload(
                raw_material_id, supplier_name, supplier_coa_ref, qty_received
            ),
            make_production_operator_headers(op_id),
        )
    )


def get_material_lot(lot_id, headers=None) -> dict:
    return get_success_data(api_client.get_material_lot(lot_id, headers or QA))


def submit_identity_test(lot_id, result="PASS", coa_match=True,
                         chemist_id=DEFAULT_CHEMIST_ID) -> dict:
    return get_success_data(
        api_client.submit_identity_test(
            lot_id,
            create_identity_test_payload(result, coa_match),
            make_qa_chemist_headers(chemist_id),
        )
    )


def coa_review(test_id, review_outcome="APPROVE", qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.coa_review_identity_test(
            test_id, create_coa_review_payload(review_outcome), make_qa_manager_headers(qm_id)
        )
    )


def create_released_lot(raw_material_id, qty_received=LOT_QTY_RECEIVED,
                        chemist_id=DEFAULT_CHEMIST_ID, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    """Lot walked through identity PASS + COA APPROVE to RELEASED (PRD §3.2)."""
    lot = create_material_lot(raw_material_id, qty_received=qty_received)
    test = submit_identity_test(lot["id"], result="PASS", coa_match=True,
                                chemist_id=chemist_id)
    coa_review(test["id"], "APPROVE", qm_id=qm_id)
    return get_material_lot(lot["id"])


# ---------------------------------------------------------------------------
# Tier 1: formulas
# ---------------------------------------------------------------------------

def default_lines(raw_material_id, theoretical=None, overage_pct=None,
                  label_claim=None) -> list:
    return [
        create_formula_line_payload(
            raw_material_id,
            theoretical_qty_mg_per_unit=(
                theoretical if theoretical is not None
                else LINE_DEFAULTS["theoretical_qty_mg_per_unit"]
            ),
            overage_pct=(
                overage_pct if overage_pct is not None else LINE_DEFAULTS["overage_pct"]
            ),
            label_claim_mg_per_unit=(
                label_claim if label_claim is not None
                else LINE_DEFAULTS["label_claim_mg_per_unit"]
            ),
        )
    ]


def create_formula(customer_id, raw_material_id=None, *, lines=None,
                   price_tiers=None, **overrides) -> dict:
    """Create a DRAFT formula (PRD §3.1). Builds the standard single label-claim
    line referencing raw_material_id unless lines are supplied explicitly."""
    if lines is None and raw_material_id is not None:
        lines = default_lines(raw_material_id)
    payload = create_formula_payload(lines=lines, price_tiers=price_tiers, **overrides)
    return get_success_data(api_client.create_formula(customer_id, payload, PLANNER))


def get_formula(formula_id, headers=None) -> dict:
    return get_success_data(api_client.get_formula(formula_id, headers or QA))


def list_formula_lines(formula_id, headers=None) -> list:
    resp = api_client.list_formula_lines(formula_id, headers or QA)
    return get_success_data(resp)


def approve_formula(formula_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.approve_formula(formula_id, {}, make_qa_manager_headers(qm_id))
    )


def create_and_approve_formula(customer_id, raw_material_id=None, **kwargs) -> dict:
    formula = create_formula(customer_id, raw_material_id, **kwargs)
    return approve_formula(formula["id"])


def revise_formula(formula_id) -> dict:
    return get_success_data(api_client.revise_formula(formula_id, {}, PLANNER))


# ---------------------------------------------------------------------------
# Tier 2: orders and batches
# ---------------------------------------------------------------------------

def place_order(customer_id, formula_id, ordered_qty=ORDERED_QTY) -> dict:
    """Brand places an order; BrandRep identity is the Customer.id (PRD §2.1)."""
    return get_success_data(
        api_client.create_manufacturing_order(
            create_manufacturing_order_payload(customer_id, formula_id, ordered_qty),
            make_brandrep_headers(customer_id),
        )
    )


def get_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_manufacturing_order(order_id, headers or QA))


def schedule_order(order_id, line_id, planned_start=WINDOW_DAY1[0],
                   planned_end=WINDOW_DAY1[1]) -> dict:
    """Schedule a PLACED order; returns the created Batch (PRD §3.3)."""
    return get_success_data(
        api_client.schedule_manufacturing_order(
            order_id,
            create_schedule_payload(line_id, planned_start, planned_end),
            PLANNER,
        )
    )


def get_batch(batch_id, headers=None) -> dict:
    return get_success_data(api_client.get_batch(batch_id, headers or QA))


def start_batch(batch_id, op_id=DEFAULT_OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.start_batch(batch_id, {}, make_production_operator_headers(op_id))
    )


def record_consumption(batch_id, lot_id, qty_consumed=CONSUMPTION_QTY,
                       op_id=DEFAULT_OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.record_consumption(
            batch_id,
            create_consumption_payload(lot_id, qty_consumed),
            make_production_operator_headers(op_id),
        )
    )


def void_consumption(batch_id, consumption_id, op_id=DEFAULT_OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.void_consumption(
            batch_id, consumption_id, {}, make_production_operator_headers(op_id)
        )
    )


def complete_batch(batch_id, actual_yield_units=ACTUAL_YIELD_UNITS,
                   actual_bulk_mass_g=ACTUAL_BULK_MASS_G,
                   op_id=DEFAULT_OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.complete_batch(
            batch_id,
            create_completion_payload(actual_yield_units, actual_bulk_mass_g),
            make_production_operator_headers(op_id),
        )
    )


def amend_batch(batch_id, actual_yield_units, actual_bulk_mass_g,
                expected_batch_version, op_id=DEFAULT_OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.amend_batch(
            batch_id,
            create_amendment_payload(
                actual_yield_units, actual_bulk_mass_g, expected_batch_version
            ),
            make_production_operator_headers(op_id),
        )
    )


def record_review_batch(batch_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.record_review_batch(batch_id, {}, make_qa_manager_headers(qm_id))
    )


def release_batch(batch_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.release_batch(batch_id, {}, make_qa_manager_headers(qm_id))
    )


def reject_batch(batch_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.reject_batch(batch_id, {}, make_qa_manager_headers(qm_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: assay, stability, cleaning, recall step helpers
# ---------------------------------------------------------------------------

def submit_assay(batch_id, assayed_mg_per_unit=470,
                 chemist_id=DEFAULT_CHEMIST_ID) -> dict:
    return get_success_data(
        api_client.submit_assay_result(
            batch_id,
            create_assay_payload(assayed_mg_per_unit),
            make_qa_chemist_headers(chemist_id),
        )
    )


def review_assay(assay_id, review_outcome="ACCEPT", qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.review_assay_result(
            assay_id, create_assay_review_payload(review_outcome),
            make_qa_manager_headers(qm_id),
        )
    )


def enroll_study(batch_id, chamber_id, protocol="REAL_TIME",
                 chemist_id=DEFAULT_CHEMIST_ID) -> dict:
    return get_success_data(
        api_client.enroll_stability_study(
            batch_id,
            create_stability_study_payload(chamber_id, protocol),
            make_qa_chemist_headers(chemist_id),
        )
    )


def complete_study(study_id, pull_results=None, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.complete_stability_study(
            study_id, create_study_completion_payload(pull_results),
            make_qa_manager_headers(qm_id),
        )
    )


def record_cleaning(line_id, op_id=DEFAULT_OPERATOR_ID, notes=None) -> dict:
    return get_success_data(
        api_client.record_cleaning_validation(
            line_id,
            create_cleaning_validation_payload(notes),
            make_production_operator_headers(op_id),
        )
    )


def swab_cleaning(validation_id, result="PASS", chemist_id=DEFAULT_CHEMIST_ID) -> dict:
    return get_success_data(
        api_client.swab_cleaning_validation(
            validation_id, create_swab_payload(result), make_qa_chemist_headers(chemist_id)
        )
    )


def approve_cleaning(validation_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.approve_cleaning_validation(
            validation_id, {}, make_qa_manager_headers(qm_id)
        )
    )


def validate_line_cleaning(line_id, op_id=DEFAULT_OPERATOR_ID,
                           chemist_id=DEFAULT_CHEMIST_ID,
                           qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    """Record + swab PASS + approve: line returns to CLEAN_VALIDATED (PRD §3.6)."""
    validation = record_cleaning(line_id, op_id=op_id)
    swab_cleaning(validation["id"], "PASS", chemist_id=chemist_id)
    return approve_cleaning(validation["id"], qm_id=qm_id)


def create_recall_event(scope_type, scope_id, reason="supplier contamination",
                        qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.create_recall(
            create_recall_payload(scope_type, scope_id, reason),
            make_qa_manager_headers(qm_id),
        )
    )


def close_recall_event(recall_id, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.close_recall(recall_id, {}, make_qa_manager_headers(qm_id))
    )


# ---------------------------------------------------------------------------
# Tier 3/4: composite scenario builders
# ---------------------------------------------------------------------------

def make_catalog(*, clock=None, customer_name="Acme", material_name="VitC",
                 material_allergen="NONE", formula_name="C500",
                 formula_allergen="NONE", min_order_qty=1000,
                 batch_size_units=10000, shelf_life_months=24,
                 overage_basis="THEORETICAL", theoretical=None, overage_pct=None,
                 label_claim=None, price_tiers=None, line_name="L1",
                 lot_qty=LOT_QTY_RECEIVED, release_lot=True,
                 chamber_capacity=None) -> dict:
    """Customer + raw material + APPROVED formula + production line + material
    lot (RELEASED unless release_lot=False) [+ stability chamber]."""
    if clock is not None:
        set_clock(clock)
    customer = create_customer(customer_name)
    material = create_raw_material(material_name, material_allergen)
    formula = create_and_approve_formula(
        customer["id"],
        None,
        name=formula_name,
        allergen_class=formula_allergen,
        min_order_qty=min_order_qty,
        batch_size_units=batch_size_units,
        shelf_life_months=shelf_life_months,
        overage_basis=overage_basis,
        lines=default_lines(material["id"], theoretical, overage_pct, label_claim),
        price_tiers=price_tiers,
    )
    line = create_production_line(line_name)
    if release_lot:
        lot = create_released_lot(material["id"], qty_received=lot_qty)
    else:
        lot = create_material_lot(material["id"], qty_received=lot_qty)
    ctx = {
        "customer": customer,
        "material": material,
        "formula": formula,
        "line": line,
        "lot": lot,
    }
    if chamber_capacity is not None:
        ctx["chamber"] = create_stability_chamber(capacity_units=chamber_capacity)
    return ctx


def run_batch(ctx, *, ordered_qty=ORDERED_QTY, window=WINDOW_DAY1,
              consumption_qty=CONSUMPTION_QTY, stage="COMPLETED",
              actual_yield=ACTUAL_YIELD_UNITS, actual_mass=ACTUAL_BULK_MASS_G,
              assayed=470, assay_outcome="ACCEPT", pull_results=None,
              protocol="REAL_TIME", op_id=DEFAULT_OPERATOR_ID,
              chemist_id=DEFAULT_CHEMIST_ID, qm_id=DEFAULT_QA_MANAGER_ID) -> dict:
    """Place a fresh order on the context's APPROVED formula, schedule it on the
    context's line, and walk the batch up the lifecycle ladder to `stage`.

    Ladder: SCHEDULED -> IN_PROCESS (start + consumption) -> COMPLETED ->
    RECORD_REVIEWED -> ASSAY_ACCEPTED (submit + review; quality QC_READY) ->
    STUDY_COMPLETED (enroll + complete; expiry mirrored) -> RELEASED.
    """
    out = {}
    mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], ordered_qty)
    out["mo"] = mo
    batch = schedule_order(mo["id"], ctx["line"]["id"], window[0], window[1])
    out["batch"] = batch
    if stage == "SCHEDULED":
        return out

    out["batch"] = start_batch(batch["id"], op_id=op_id)
    out["consumption"] = record_consumption(
        batch["id"], ctx["lot"]["id"], consumption_qty, op_id=op_id
    )
    if stage == "IN_PROCESS":
        return out

    out["batch"] = complete_batch(batch["id"], actual_yield, actual_mass, op_id=op_id)
    if stage == "COMPLETED":
        return out

    out["batch"] = record_review_batch(batch["id"], qm_id=qm_id)
    if stage == "RECORD_REVIEWED":
        return out

    assay = submit_assay(batch["id"], assayed, chemist_id=chemist_id)
    out["assay"] = assay
    if assay_outcome is not None:
        out["assay"] = review_assay(assay["id"], assay_outcome, qm_id=qm_id)
    out["batch"] = get_batch(batch["id"])
    if stage == "ASSAY_ACCEPTED":
        return out

    study = enroll_study(batch["id"], ctx["chamber"]["id"], protocol,
                         chemist_id=chemist_id)
    out["study"] = complete_study(study["id"], pull_results, qm_id=qm_id)
    out["batch"] = get_batch(batch["id"])
    if stage == "STUDY_COMPLETED":
        return out

    out["batch"] = release_batch(batch["id"], qm_id=qm_id)
    return out


def setup_batch_at_stage(stage="COMPLETED", *, catalog_overrides=None, **run_kw) -> dict:
    """Full single-batch context walked to the requested lifecycle stage."""
    ctx = make_catalog(**(catalog_overrides or {}))
    ctx.update(run_batch(ctx, stage=stage, **run_kw))
    return ctx


def setup_releasable_batch(*, clock=None, chamber_capacity=50000, **run_kw) -> dict:
    """Batch fully positioned for release: RECORD_REVIEWED, ACCEPTED in-range
    assay (QC_READY), COMPLETED stability study, component lot RELEASED."""
    return setup_batch_at_stage(
        "STUDY_COMPLETED",
        catalog_overrides={"clock": clock, "chamber_capacity": chamber_capacity},
        **run_kw,
    )


def setup_released_batch(*, clock=None, chamber_capacity=50000, **run_kw) -> dict:
    """Full lifecycle through quality RELEASED (order COMPLETED)."""
    return setup_batch_at_stage(
        "RELEASED",
        catalog_overrides={"clock": clock, "chamber_capacity": chamber_capacity},
        **run_kw,
    )


def setup_two_completed_batches(*, clock=None, lot_qty=50000000,
                                yields=(ACTUAL_YIELD_UNITS, ACTUAL_YIELD_UNITS),
                                masses=(ACTUAL_BULK_MASS_G, ACTUAL_BULK_MASS_G),
                                catalog_overrides=None) -> tuple:
    """Two COMPLETED batches of the same formula on one line (consecutive days).
    The second start is a like-for-like allergen continuation (PRD §3.4)."""
    overrides = {"clock": clock, "lot_qty": lot_qty}
    overrides.update(catalog_overrides or {})
    ctx = make_catalog(**overrides)
    run1 = run_batch(ctx, window=WINDOW_DAY1, stage="COMPLETED",
                     actual_yield=yields[0], actual_mass=masses[0])
    run2 = run_batch(ctx, window=WINDOW_DAY2, stage="COMPLETED",
                     actual_yield=yields[1], actual_mass=masses[1])
    return ctx, run1, run2


def setup_two_released_batches_same_lot(*, clock=None) -> tuple:
    """Two RELEASED batches consuming the same RELEASED lot (recall fixture)."""
    ctx = make_catalog(clock=clock, lot_qty=50000000, chamber_capacity=50000)
    run1 = run_batch(ctx, window=WINDOW_DAY1, stage="RELEASED")
    validate_line_cleaning(ctx["line"]["id"])
    run2 = run_batch(ctx, window=WINDOW_DAY2, stage="RELEASED")
    return ctx, run1, run2
