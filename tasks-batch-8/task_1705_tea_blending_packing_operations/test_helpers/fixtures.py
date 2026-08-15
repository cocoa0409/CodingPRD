"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at exactly 2026-08-01T00:00:00Z). Setup calls
use get_success_data so failures surface as clear "Setup failed" errors.

Segregation-of-duties threading (PRD §2.9) is baked in: lots are registered
by pl-1, graded by gr-1, residue-tested by an-1, released by qa-1; batches
are blended by bm-1 and released by qa-1. Tests that deliberately violate
segregation build custom headers with build_user_headers inline.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_payload,
    create_batch_payload,
    create_blend_payload,
    create_certificate_payload,
    create_contract_payload,
    create_flavoring_application_payload,
    create_flavoring_payload,
    create_grade_assessment_payload,
    create_leaf_lot_payload,
    create_packaging_line_payload,
    create_recipe_payload,
    create_residue_test_payload,
    create_run_payload,
    create_supplier_payload,
    set_clock_payload,
    single_component,
)
from .test_users import TEST_USERS

PL = TEST_USERS["procurement_lead_headers"]       # pl-1
GR = TEST_USERS["sensory_grader_headers"]         # gr-1
AN = TEST_USERS["qa_lab_analyst_headers"]         # an-1
QA = TEST_USERS["qa_manager_headers"]             # qa-1
BM = TEST_USERS["blend_master_headers"]           # bm-1
PP = TEST_USERS["production_planner_headers"]     # pp-1
AM = TEST_USERS["account_manager_headers"]        # am-1
CO = TEST_USERS["certification_officer_headers"]  # co-1
ADM = TEST_USERS["platform_admin_headers"]        # adm-1


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation and state progression
# ---------------------------------------------------------------------------

def create_supplier(name="Assam Co", origin_region="Assam"):
    """Register a supplier (born ACTIVE). Returns the supplier dict."""
    return _ok("create_supplier", api_client.create_supplier(
        create_supplier_payload(name=name, origin_region=origin_region), PL))


def create_leaf_lot(supplier_id, leaf_type="BLACK", harvest_date="2026-02-01",
                    weight_kg=10.0, cost_per_kg_cents=900, moisture_pct=5.0):
    """Register a leaf lot (born REGISTERED). Returns the lot dict."""
    return _ok("create_leaf_lot", api_client.create_leaf_lot(
        create_leaf_lot_payload(
            supplier_id, leaf_type=leaf_type, harvest_date=harvest_date,
            weight_kg=weight_kg, cost_per_kg_cents=cost_per_kg_cents,
            moisture_pct=moisture_pct), PL))


def grade_lot(lot_id, aroma_score=80, briskness_score=80, appearance_score=80):
    """Submit a sensory assessment. Returns the GradeAssessment dict."""
    return _ok("grade_lot", api_client.create_grade_assessment(
        lot_id,
        create_grade_assessment_payload(
            aroma_score=aroma_score, briskness_score=briskness_score,
            appearance_score=appearance_score), GR))


def submit_residue_test(lot_id, measured_residue_ppm=0.20, lab_name="LabA",
                        test_method="GCMS"):
    """File a residue test. Returns the ResidueTest dict."""
    return _ok("submit_residue_test", api_client.create_residue_test(
        lot_id,
        create_residue_test_payload(
            lab_name=lab_name, measured_residue_ppm=measured_residue_ppm,
            test_method=test_method), AN))


def release_lot(lot_id):
    """QA-release a lot. Returns the RELEASED lot dict."""
    return _ok("release_lot", api_client.release_lot(lot_id, QA))


def get_lot(lot_id):
    return _ok("get_lot", api_client.get_leaf_lot(lot_id, QA))


def create_graded_lot(supplier_id, **kwargs):
    """Lot walked REGISTERED -> GRADED (scores default to grade B)."""
    aroma = kwargs.pop("aroma_score", 80)
    brisk = kwargs.pop("briskness_score", 80)
    app = kwargs.pop("appearance_score", 80)
    lot = create_leaf_lot(supplier_id, **kwargs)
    grade_lot(lot["id"], aroma, brisk, app)
    return get_lot(lot["id"])


def create_lab_submitted_lot(supplier_id, measured_residue_ppm=0.20, **kwargs):
    """Lot walked REGISTERED -> GRADED -> LAB_SUBMITTED (residue PASS)."""
    lot = create_graded_lot(supplier_id, **kwargs)
    submit_residue_test(lot["id"], measured_residue_ppm)
    return get_lot(lot["id"])


def create_released_lot(supplier_id, measured_residue_ppm=0.20, **kwargs):
    """Lot walked the full intake chain to RELEASED."""
    lot = create_lab_submitted_lot(
        supplier_id, measured_residue_ppm=measured_residue_ppm, **kwargs)
    return release_lot(lot["id"])


def create_flavoring(name="Bergamot", allergen_tags=None, natural_certified=True,
                     cost_per_kg_cents=2000):
    """Register a flavoring (born ACTIVE). Returns the flavoring dict."""
    return _ok("create_flavoring", api_client.create_flavoring(
        create_flavoring_payload(
            name=name, allergen_tags=allergen_tags or [],
            natural_certified=natural_certified,
            cost_per_kg_cents=cost_per_kg_cents), BM))


def create_recipe(name="House Blend", certification_target="CONVENTIONAL",
                  pack_format="LOOSE_PACK", components=None, flavoring_id=None,
                  flavoring_pct=0.0):
    """Create a recipe (born DRAFT). Returns the recipe dict."""
    payload = create_recipe_payload(
        name=name, certification_target=certification_target,
        pack_format=pack_format,
        components=components or [single_component()])
    if flavoring_id is not None:
        payload["flavoring_id"] = flavoring_id
        payload["flavoring_pct"] = flavoring_pct
    return _ok("create_recipe", api_client.create_recipe(payload, BM))


def activate_recipe(recipe_id):
    return _ok("activate_recipe", api_client.activate_recipe(recipe_id, BM))


def create_active_recipe(**kwargs):
    """Create + activate a recipe. Returns the ACTIVE recipe dict."""
    recipe = create_recipe(**kwargs)
    return activate_recipe(recipe["id"])


def create_batch(recipe_id, target_weight_kg=20.0):
    """Create a batch (born DRAFT, pack_format snapshotted)."""
    return _ok("create_batch", api_client.create_batch(
        create_batch_payload(recipe_id, target_weight_kg=target_weight_kg), BM))


def get_batch(batch_id):
    return _ok("get_batch", api_client.get_batch(batch_id, BM))


def lock_recipe(batch_id):
    """DRAFT -> RECIPE_LOCKED. Returns the locked batch dict."""
    return _ok("lock_recipe", api_client.lock_recipe(batch_id, BM))


def allocate(batch_id, lot_id, allocated_kg):
    """Post one allocation against a batch, refreshing the OCC batch version
    first so the expected_batch_version is always current. Returns the
    BatchLotAllocation dict."""
    version = get_batch(batch_id)["version"]
    return _ok("allocate", api_client.create_allocation(
        batch_id,
        create_allocation_payload(lot_id, allocated_kg, version), BM))


def finalize_allocation(batch_id):
    """RECIPE_LOCKED -> ALLOCATED. Returns the batch dict."""
    return _ok("finalize_allocation",
               api_client.finalize_allocation(batch_id, BM))


def blend_batch(batch_id, measured_moisture_pct=5.0):
    """ALLOCATED -> BLENDED (blender bm-1). Returns the batch dict."""
    return _ok("blend_batch", api_client.blend_batch(
        batch_id, create_blend_payload(measured_moisture_pct), BM))


def apply_flavoring(batch_id, flavoring_id, applied_kg):
    """BLENDED -> FLAVORED. Returns the FlavoringApplication dict."""
    return _ok("apply_flavoring", api_client.apply_flavoring(
        batch_id,
        create_flavoring_application_payload(flavoring_id, applied_kg), BM))


def submit_qc(batch_id):
    """Enter QC_REVIEW (unflavored/flavored/rework branch)."""
    return _ok("submit_qc", api_client.submit_qc(batch_id, BM))


def release_batch(batch_id):
    """QC_REVIEW -> RELEASED (releaser qa-1 differs from blender bm-1)."""
    return _ok("release_batch", api_client.release_batch(batch_id, QA))


def cancel_batch(batch_id):
    return _ok("cancel_batch", api_client.cancel_batch(batch_id, BM))


def recall_batch(batch_id):
    return _ok("recall_batch", api_client.recall_batch(batch_id, QA))


def create_packaging_line(name="LP-1", line_type="LOOSE_PACK"):
    """Register a packaging line (born ACTIVE). Returns the line dict."""
    return _ok("create_packaging_line", api_client.create_packaging_line(
        create_packaging_line_payload(name=name, line_type=line_type), PP))


def create_run(line_id, batch_id, planned_start, planned_end, planned_units,
               contract_id=None):
    """Schedule a production run. Returns the SCHEDULED run dict."""
    payload = create_run_payload(line_id, batch_id, planned_start,
                                 planned_end, planned_units)
    if contract_id is not None:
        payload["contract_id"] = contract_id
    return _ok("create_run", api_client.create_run(payload, PP))


def start_run(run_id):
    return _ok("start_run", api_client.start_run(run_id, PP))


def complete_run(run_id, actual_units):
    return _ok("complete_run", api_client.complete_run(
        run_id, {"actual_units": actual_units}, PP))


def get_run(run_id):
    return _ok("get_run", api_client.get_run(run_id, PP))


def create_contract(recipe_id, customer_name="Acme Foods",
                    minimum_units_per_run=100, contracted_total_units=1000,
                    base_unit_price_cents=200):
    """Create a contract (born DRAFT, fulfilled_units 0)."""
    return _ok("create_contract", api_client.create_contract(
        create_contract_payload(
            recipe_id, customer_name=customer_name,
            minimum_units_per_run=minimum_units_per_run,
            contracted_total_units=contracted_total_units,
            base_unit_price_cents=base_unit_price_cents), AM))


def activate_contract(contract_id):
    return _ok("activate_contract",
               api_client.activate_contract(contract_id, AM))


def create_active_contract(recipe_id, **kwargs):
    contract = create_contract(recipe_id, **kwargs)
    return activate_contract(contract["id"])


def get_contract(contract_id):
    return _ok("get_contract", api_client.get_contract(contract_id, AM))


def create_certificate(supplier_id, cert_type="ORGANIC",
                       total_volume_kg=10000.0, valid_from="2026-01-01",
                       valid_until="2026-12-31"):
    """Grant a certificate (born ACTIVE, consumed_volume_kg 0)."""
    return _ok("create_certificate", api_client.create_certificate(
        create_certificate_payload(
            supplier_id, cert_type=cert_type, total_volume_kg=total_volume_kg,
            valid_from=valid_from, valid_until=valid_until), CO))


def get_certificate(certificate_id):
    return _ok("get_certificate",
               api_client.get_certificate(certificate_id, CO))


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin). Returns response data."""
    return _ok("set_clock", api_client.set_clock(
        set_clock_payload(to_iso8601), ADM))


# ---------------------------------------------------------------------------
# Tier 2/3 — batch lifecycle composites
# ---------------------------------------------------------------------------

def create_locked_batch_with_allocations(recipe_id, target_weight_kg,
                                         allocations):
    """Create batch -> lock recipe -> post each allocation.

    allocations: list of (lot_id, allocated_kg) tuples.
    Returns the batch dict in RECIPE_LOCKED with allocations posted.
    """
    batch = create_batch(recipe_id, target_weight_kg)
    lock_recipe(batch["id"])
    for lot_id, kg in allocations:
        allocate(batch["id"], lot_id, kg)
    return get_batch(batch["id"])


def create_allocated_batch(recipe_id, target_weight_kg, allocations):
    """Batch walked through allocation finalization (ALLOCATED)."""
    batch = create_locked_batch_with_allocations(
        recipe_id, target_weight_kg, allocations)
    return finalize_allocation(batch["id"])


def create_blended_batch(recipe_id, target_weight_kg, allocations,
                         measured_moisture_pct=5.0):
    """Batch walked to BLENDED with measured moisture recorded."""
    batch = create_allocated_batch(recipe_id, target_weight_kg, allocations)
    return blend_batch(batch["id"], measured_moisture_pct)


def create_qc_batch(recipe, target_weight_kg, allocations,
                    measured_moisture_pct=5.0):
    """Batch walked to QC_REVIEW. For flavored recipes the flavoring is
    applied at the exact computed dose before submission."""
    batch = create_blended_batch(
        recipe["id"], target_weight_kg, allocations, measured_moisture_pct)
    if recipe.get("flavoring_id") is not None:
        apply_flavoring(batch["id"], recipe["flavoring_id"],
                        batch["flavoring_kg"])
    return submit_qc(batch["id"])


def create_released_batch(recipe, target_weight_kg, allocations,
                          measured_moisture_pct=5.0):
    """Batch walked the full pipeline to RELEASED.

    For ORGANIC/FAIR_TRADE recipes the caller MUST have already granted each
    contributing supplier an ACTIVE certificate covering the current clock
    date with sufficient remaining volume.
    """
    batch = create_qc_batch(recipe, target_weight_kg, allocations,
                            measured_moisture_pct)
    return release_batch(batch["id"])


# ---------------------------------------------------------------------------
# Tier 4/5 — full-scenario builders
# ---------------------------------------------------------------------------

def setup_single_lot_scenario(*, leaf_type="GREEN", lot_weight_kg=30.0,
                              lot_cost_per_kg_cents=800, lot_moisture_pct=5.0,
                              harvest_date="2026-02-01",
                              certification_target="CONVENTIONAL",
                              pack_format="LOOSE_PACK", min_grade="C",
                              target_weight_kg=20.0, allocated_kg=20.0,
                              measured_moisture_pct=5.0,
                              flavoring_spec=None,
                              cert_volume_kg=10000.0,
                              advance_to="RELEASED"):
    """End-to-end single-supplier/single-lot batch scenario.

    flavoring_spec: None or dict(name, allergen_tags, natural_certified,
        cost_per_kg_cents, pct) — when set, the recipe reserves that pct for
        the flavoring and the component pct becomes 100 - pct.
    advance_to: "RECIPE_LOCKED" | "ALLOCATED" | "BLENDED" | "QC_REVIEW" |
        "RELEASED".

    Returns dict(supplier, lot, flavoring, recipe, batch, certificate).
    """
    supplier = create_supplier()
    lot = create_released_lot(
        supplier["id"], leaf_type=leaf_type, weight_kg=lot_weight_kg,
        cost_per_kg_cents=lot_cost_per_kg_cents, moisture_pct=lot_moisture_pct,
        harvest_date=harvest_date)

    flavoring = None
    flavoring_id = None
    flavoring_pct = 0.0
    component_pct = 100.0
    if flavoring_spec is not None:
        flavoring = create_flavoring(
            name=flavoring_spec.get("name", "House Flavor"),
            allergen_tags=flavoring_spec.get("allergen_tags", []),
            natural_certified=flavoring_spec.get("natural_certified", True),
            cost_per_kg_cents=flavoring_spec.get("cost_per_kg_cents", 2000))
        flavoring_id = flavoring["id"]
        flavoring_pct = flavoring_spec["pct"]
        component_pct = 100.0 - flavoring_pct

    recipe = create_active_recipe(
        certification_target=certification_target, pack_format=pack_format,
        components=[single_component(leaf_type, min_grade, component_pct)],
        flavoring_id=flavoring_id, flavoring_pct=flavoring_pct)

    certificate = None
    if certification_target != "CONVENTIONAL" and advance_to == "RELEASED":
        certificate = create_certificate(
            supplier["id"], cert_type=certification_target,
            total_volume_kg=cert_volume_kg)

    alloc = [(lot["id"], allocated_kg)]
    if advance_to == "RECIPE_LOCKED":
        batch = create_locked_batch_with_allocations(
            recipe["id"], target_weight_kg, alloc)
    elif advance_to == "ALLOCATED":
        batch = create_allocated_batch(recipe["id"], target_weight_kg, alloc)
    elif advance_to == "BLENDED":
        batch = create_blended_batch(recipe["id"], target_weight_kg, alloc,
                                     measured_moisture_pct)
    elif advance_to == "QC_REVIEW":
        batch = create_qc_batch(recipe, target_weight_kg, alloc,
                                measured_moisture_pct)
    else:
        batch = create_released_batch(recipe, target_weight_kg, alloc,
                                      measured_moisture_pct)

    return {"supplier": supplier, "lot": lot, "flavoring": flavoring,
            "recipe": recipe, "batch": batch, "certificate": certificate}


def setup_released_batch_with_line(**kwargs):
    """setup_single_lot_scenario(advance_to=RELEASED) plus a matching-format
    packaging line. Returns the scenario dict plus key "line"."""
    line_name = kwargs.pop("line_name", "LP-1")
    ctx = setup_single_lot_scenario(advance_to="RELEASED", **kwargs)
    ctx["line"] = create_packaging_line(
        name=line_name, line_type=ctx["batch"]["pack_format"])
    return ctx
