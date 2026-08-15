"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh database,
using only PRD-declared endpoints, and threads real `SystemUser` ids into the
per-role headers (PRD §2.1: for SystemUser-backed roles, X-User-ID is the id
of the acting SystemUser; segregation-of-duties checks compare that id against
the recorded prior actor).

Segregation-of-duties discipline used throughout:
- NutrientProfile submit and approve use two DIFFERENT REGULATORY_AFFAIRS users.
- Formula approve (QA_MANAGER) differs from the submitter (REGULATORY_AFFAIRS).
- Label approve (QA_MANAGER) differs from the label submitter.
- Batch release (QA_MANAGER) differs from the test-results submitter
  (QUALITY_ANALYST).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_nutrient_profile_payload, create_system_user_payload,
    create_supplier_payload, create_audit_payload, create_ingredient_payload,
    create_ingredient_lot_payload, create_formula_payload,
    create_process_validation_payload, passing_test_results,
    create_production_batch_payload, create_label_submission_payload,
    create_complaint_payload, create_recall_campaign_payload,
    create_recall_scope_payload, create_allocation_plan_payload,
    create_allocation_entry_payload,
)
from .test_users import (
    TEST_USERS, make_regulatory_affairs_headers, make_qa_manager_headers,
    make_quality_analyst_headers, make_production_supervisor_headers,
    make_supply_chain_planner_headers, make_complaint_handler_headers,
)

# Validation type required by each process type for approval/production gating
# (PRD §3.3, §3.4).
VALIDATION_TYPE_FOR_PROCESS = {
    "DRY_BLEND": "DRY_BLEND_HOMOGENEITY",
    "WET_PROCESS": "WET_PROCESS_THERMAL",
    "COMBINATION": "COMBINATION_FULL",
}


# ---------------------------------------------------------------------------
# Tier 0: users and clock
# ---------------------------------------------------------------------------

def create_test_users() -> dict:
    """Create one SystemUser per SystemUser-backed role (two REGULATORY_AFFAIRS
    users so segregation-of-duties approvals have a distinct approver).

    Returns a dict: key -> {"user": <SystemUser>, "headers": <auth headers>};
    the "admin" entry carries headers only (ADMIN is an opaque role).
    """
    admin = TEST_USERS["admin_headers"]
    specs = {
        "ra1": ("ra-user-1", "Reg Affairs One", "REGULATORY_AFFAIRS",
                make_regulatory_affairs_headers),
        "ra2": ("ra-user-2", "Reg Affairs Two", "REGULATORY_AFFAIRS",
                make_regulatory_affairs_headers),
        "qm": ("qm-user-1", "QA Manager One", "QA_MANAGER",
               make_qa_manager_headers),
        "qa": ("qa-user-1", "Quality Analyst One", "QUALITY_ANALYST",
               make_quality_analyst_headers),
        "ps": ("ps-user-1", "Production Supervisor One", "PRODUCTION_SUPERVISOR",
               make_production_supervisor_headers),
        "scp": ("scp-user-1", "Supply Planner One", "SUPPLY_CHAIN_PLANNER",
                make_supply_chain_planner_headers),
        "ch": ("ch-user-1", "Complaint Handler One", "COMPLAINT_HANDLER",
               make_complaint_handler_headers),
    }
    users = {"admin": {"user": None, "headers": admin}}
    for key, (username, full_name, role, builder) in specs.items():
        res = api_client.create_system_user(
            create_system_user_payload(
                username=username, full_name=full_name, role=role,
                department="Operations"),
            admin)
        user = get_success_data(res, 201)
        users[key] = {"user": user, "headers": builder(user["id"])}
    return users


def set_clock(users, to_iso8601=DEFAULT_CLOCK):
    """Advance the logical clock (PRD §2.9)."""
    res = api_client.set_clock(to_iso8601, users["admin"]["headers"])
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: single-entity progression
# ---------------------------------------------------------------------------

def create_approved_nutrient_profile(
        users, profile_code="INF-0-6M", nutrient_specs=None,
        regulation_ref="21 CFR 107.100", effective_from="2026-01-01T00:00:00Z"):
    """Create profile (ra1) -> submit (ra1) -> approve (ra2, distinct user).
    Returns the APPROVED profile."""
    payload = create_nutrient_profile_payload(
        profile_code=profile_code, regulation_ref=regulation_ref,
        effective_from=effective_from)
    if nutrient_specs is not None:
        payload["nutrient_specs"] = nutrient_specs
    profile = get_success_data(
        api_client.create_nutrient_profile(payload, users["ra1"]["headers"]), 201)
    get_success_data(api_client.submit_nutrient_profile(
        profile["id"], users["ra1"]["headers"]))
    approved = get_success_data(api_client.approve_nutrient_profile(
        profile["id"], users["ra2"]["headers"]))
    return approved


def create_ingredient(users, code, name, category, risk_class, storage):
    ing = get_success_data(api_client.create_ingredient(
        create_ingredient_payload(
            ingredient_code=code, ingredient_name=name, category=category,
            pathogen_risk_class=risk_class, storage_condition=storage),
        users["qm"]["headers"]), 201)
    return ing


def create_qualified_supplier(users, code, categories, score=90.00,
                              audit_date="2026-07-01T00:00:00Z",
                              audit_frequency_days=180):
    """Create supplier (qm) + passing audit (qa) -> QUALIFIED supplier."""
    supplier = get_success_data(api_client.create_supplier(
        create_supplier_payload(
            supplier_code=code, legal_name=f"{code} Ltd",
            ingredient_categories=categories,
            audit_frequency_days=audit_frequency_days),
        users["qm"]["headers"]), 201)
    get_success_data(api_client.create_audit(
        supplier["id"], create_audit_payload(
            audit_date=audit_date, score=score),
        users["qa"]["headers"]), 201)
    return get_success_data(api_client.get_supplier(
        supplier["id"], users["qm"]["headers"]))


def create_ingredient_lot(users, ingredient_id, supplier_id, lot_number,
                          quantity_kg=500.000,
                          received_date="2026-07-15T00:00:00Z",
                          expiry_date="2027-07-15T00:00:00Z"):
    lot = get_success_data(api_client.create_ingredient_lot(
        create_ingredient_lot_payload(
            ingredient_id=ingredient_id, supplier_id=supplier_id,
            lot_number=lot_number, quantity_kg=quantity_kg,
            received_date=received_date, expiry_date=expiry_date),
        users["scp"]["headers"]), 201)
    return lot


def qc_pass_lot(users, lot_id):
    return get_success_data(api_client.qc_pass_lot(lot_id, users["qa"]["headers"]))


def create_qc_passed_lot(users, ingredient_id, supplier_id, lot_number,
                         quantity_kg=500.000, **kwargs):
    lot = create_ingredient_lot(users, ingredient_id, supplier_id, lot_number,
                                quantity_kg=quantity_kg, **kwargs)
    return qc_pass_lot(users, lot["id"])


# ---------------------------------------------------------------------------
# Tier 2: formula hierarchy
# ---------------------------------------------------------------------------

def create_draft_formula(users, formula_code, product_name, profile_id,
                         ing_a_id, ing_b_id, pct_a=60.000, pct_b=40.000,
                         process_type="DRY_BLEND"):
    """Create a formula with two ingredients summing to 100.000 (PRD §3.3)."""
    formula = get_success_data(api_client.create_formula(
        create_formula_payload(
            formula_code=formula_code, product_name=product_name,
            nutrient_profile_id=profile_id,
            ingredients=[
                {"ingredient_id": ing_a_id, "percentage_by_weight": pct_a,
                 "is_critical": True},
                {"ingredient_id": ing_b_id, "percentage_by_weight": pct_b,
                 "is_critical": False},
            ],
            process_type=process_type),
        users["ra1"]["headers"]), 201)
    return formula


def create_passed_validation(users, formula_id, process_type="DRY_BLEND",
                             validation_type=None, validity_days=365,
                             protocol_version="PV-2026-001"):
    """Create validation (qm) -> start (ps) -> complete with passing results (qa).
    Returns the PASSED ProcessValidation."""
    pv = get_success_data(api_client.create_process_validation(
        create_process_validation_payload(
            formula_id=formula_id,
            validation_type=validation_type or VALIDATION_TYPE_FOR_PROCESS[process_type],
            protocol_version=protocol_version,
            validation_validity_days=validity_days),
        users["qm"]["headers"]), 201)
    get_success_data(api_client.start_process_validation(
        pv["id"], users["ps"]["headers"]))
    passed = get_success_data(api_client.complete_process_validation(
        pv["id"], {"test_results": passing_test_results()},
        users["qa"]["headers"]))
    return passed


def create_approved_label(users, formula_id, label_text="Complete nutrition label"):
    """Create label (ra1) -> submit (ra1) -> assign reviewer (qm; reviewer is a
    real SystemUser with role QA_MANAGER) -> approve (qm, distinct from the
    ra1 submitter). Returns the APPROVED LabelSubmission."""
    label = get_success_data(api_client.create_label_submission(
        create_label_submission_payload(
            formula_id=formula_id, label_text=label_text),
        users["ra1"]["headers"]), 201)
    get_success_data(api_client.submit_label(label["id"], users["ra1"]["headers"]))
    get_success_data(api_client.assign_label_reviewer(
        label["id"], {"reviewer_id": users["qm"]["user"]["id"]},
        users["qm"]["headers"]))
    approved = get_success_data(api_client.approve_label(
        label["id"], users["qm"]["headers"]))
    return approved


def create_active_formula(users, formula_code="IF-START-1",
                          product_name="InfStart Stage 1",
                          profile_code="INF-0-6M", nutrient_specs=None,
                          process_type="DRY_BLEND", validity_days=365,
                          ing_a=None, ing_b=None):
    """Full chain to an ACTIVE formula: approved profile + two ingredients +
    formula submitted + matching PASSED validation + APPROVED label + activate.
    Returns a dict with every artifact."""
    profile = create_approved_nutrient_profile(
        users, profile_code=profile_code, nutrient_specs=nutrient_specs)
    ing_a = ing_a or create_ingredient(
        users, f"{formula_code}-A", "Base Ingredient A", "DAIRY_BASE",
        "LOW_RISK", "REFRIGERATED")
    ing_b = ing_b or create_ingredient(
        users, f"{formula_code}-B", "Base Ingredient B", "CARBOHYDRATE",
        "LOW_RISK", "AMBIENT")
    formula = create_draft_formula(
        users, formula_code, product_name, profile["id"],
        ing_a["id"], ing_b["id"], process_type=process_type)
    get_success_data(api_client.submit_formula_for_review(
        formula["id"], users["ra1"]["headers"]))
    pv = create_passed_validation(
        users, formula["id"], process_type=process_type,
        validity_days=validity_days)
    get_success_data(api_client.approve_formula(
        formula["id"], users["qm"]["headers"]))
    label = create_approved_label(users, formula["id"])
    active = get_success_data(api_client.activate_formula(
        formula["id"], users["qm"]["headers"]))
    return {
        "profile": profile, "ing_a": ing_a, "ing_b": ing_b,
        "formula": active, "validation": pv, "label": label,
    }


# ---------------------------------------------------------------------------
# Tier 3: batch lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_formula_version(users, formula_id):
    formula = get_success_data(api_client.get_formula(
        formula_id, users["qm"]["headers"]))
    return formula["version"]


def create_planned_batch(users, formula_id, batch_size_kg=100.000,
                         production_date="2026-08-01T00:00:00Z"):
    """Create a ProductionBatch with the OCC field read fresh from the formula
    (PRD §2.6, §3.4). Returns the PLANNED batch."""
    version = get_formula_version(users, formula_id)
    batch = get_success_data(api_client.create_production_batch(
        create_production_batch_payload(
            formula_id=formula_id, batch_size_kg=batch_size_kg,
            production_date=production_date,
            expected_formula_version=version),
        users["ps"]["headers"]), 201)
    return batch


def advance_batch_to_testing(users, batch_id, process_type="DRY_BLEND",
                             actual_yield_kg=98.000):
    """PLANNED -> IN_PRODUCTION -> (BLENDING_COMPLETE) -> PROCESSING_COMPLETE
    -> TESTING. Returns the TESTING batch."""
    get_success_data(api_client.start_production(batch_id, users["ps"]["headers"]))
    if process_type in ("DRY_BLEND", "COMBINATION"):
        get_success_data(api_client.complete_blending(batch_id, users["ps"]["headers"]))
    get_success_data(api_client.complete_processing(
        batch_id, {"actual_yield_kg": actual_yield_kg}, users["ps"]["headers"]))
    testing = get_success_data(api_client.submit_for_testing(
        batch_id, users["qa"]["headers"]))
    return testing


def advance_batch_to_hold(users, batch_id, nutrient_results, pathogen_results,
                          process_type="DRY_BLEND", actual_yield_kg=98.000):
    """Walk a PLANNED batch to POSITIVE_RELEASE_HOLD (test results submitted by
    the QUALITY_ANALYST user). Returns the batch in POSITIVE_RELEASE_HOLD."""
    advance_batch_to_testing(users, batch_id, process_type=process_type,
                             actual_yield_kg=actual_yield_kg)
    hold = get_success_data(api_client.submit_test_results(
        batch_id,
        {"nutrient_results": nutrient_results, "pathogen_results": pathogen_results},
        users["qa"]["headers"]))
    return hold


def create_released_batch_scenario(
        users, profile_code="TODDLER-12-36M", nutrient_specs=None,
        process_type="DRY_BLEND", batch_size_kg=100.000,
        production_date="2026-08-01T00:00:00Z",
        nutrient_results=None, pathogen_results=None,
        lot_a_kg=500.000, lot_b_kg=300.000, actual_yield_kg=98.000):
    """Full pipeline: ACTIVE formula + QUALIFIED supplier + two QC_PASSED lots
    + batch through production/testing/hold -> RELEASED (release by qm, results
    submitted by qa — segregation of duties preserved). Returns all artifacts.
    """
    if nutrient_specs is None:
        nutrient_specs = [{
            "nutrient_code": "PROTEIN", "unit": "g",
            "min_per_100kcal": 1.50, "max_per_100kcal": 3.00,
            "target_per_100kcal": 2.20,
        }]
    scenario = create_active_formula(
        users, profile_code=profile_code, nutrient_specs=nutrient_specs,
        process_type=process_type)
    supplier = create_qualified_supplier(
        users, f"SUP-{scenario['formula']['formula_code']}",
        ["DAIRY_BASE", "CARBOHYDRATE"])
    lot_a = create_qc_passed_lot(
        users, scenario["ing_a"]["id"], supplier["id"], "LOT-A-001",
        quantity_kg=lot_a_kg)
    lot_b = create_qc_passed_lot(
        users, scenario["ing_b"]["id"], supplier["id"], "LOT-B-001",
        quantity_kg=lot_b_kg)
    batch = create_planned_batch(
        users, scenario["formula"]["id"], batch_size_kg=batch_size_kg,
        production_date=production_date)
    if nutrient_results is None:
        nutrient_results = [{
            "nutrient_code": nutrient_specs[0]["nutrient_code"],
            "measured_per_100kcal": nutrient_specs[0]["target_per_100kcal"],
        }]
    if pathogen_results is None:
        pathogen_results = [{
            "pathogen_code": "SALMONELLA", "detected": False, "cfu_per_g": 0,
        }]
    advance_batch_to_hold(
        users, batch["id"], nutrient_results, pathogen_results,
        process_type=process_type, actual_yield_kg=actual_yield_kg)
    released = get_success_data(api_client.release_batch(
        batch["id"], users["qm"]["headers"]))
    scenario.update({
        "supplier": supplier, "lot_a": lot_a, "lot_b": lot_b,
        "batch": released,
    })
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: recalls and complaints
# ---------------------------------------------------------------------------

def create_recall_campaign(users, reason="PRECAUTIONARY", recall_class="CLASS_III",
                           scope_description="Precautionary recall"):
    campaign = get_success_data(api_client.create_recall_campaign(
        create_recall_campaign_payload(
            reason=reason, recall_class=recall_class,
            scope_description=scope_description),
        users["qm"]["headers"]), 201)
    return campaign


def create_recall_scope(users, recall_id, batch_id, quantity_shipped_kg,
                        withdrawal_level="RETAIL"):
    scope = get_success_data(api_client.create_recall_scope(
        recall_id,
        create_recall_scope_payload(
            batch_id=batch_id, withdrawal_level=withdrawal_level,
            quantity_shipped_kg=quantity_shipped_kg),
        users["qm"]["headers"]), 201)
    return scope


def create_investigating_complaint(users, formula_id, complaint_type="QUALITY_DEFECT",
                                   severity="LOW", description="Minor issue"):
    complaint = get_success_data(api_client.create_complaint(
        create_complaint_payload(
            product_formula_id=formula_id, complaint_type=complaint_type,
            severity=severity, description=description),
        users["ch"]["headers"]), 201)
    get_success_data(api_client.start_complaint_investigation(
        complaint["id"], users["ch"]["headers"]))
    return get_success_data(api_client.get_complaint(
        complaint["id"], users["ch"]["headers"]))


# ---------------------------------------------------------------------------
# Tier 5: allocation plans
# ---------------------------------------------------------------------------

def create_allocation_plan(users, formula_id, total_available_kg,
                           allocation_method):
    plan = get_success_data(api_client.create_allocation_plan(
        create_allocation_plan_payload(
            formula_id=formula_id, total_available_kg=total_available_kg,
            allocation_method=allocation_method),
        users["scp"]["headers"]), 201)
    return plan


def add_allocation_entry(users, plan_id, customer_code, requested_kg,
                         priority_tier=None, customer_name=None):
    payload = create_allocation_entry_payload(
        customer_code=customer_code,
        customer_name=customer_name or f"Customer {customer_code}",
        requested_kg=requested_kg)
    if priority_tier is not None:
        payload["priority_tier"] = priority_tier
    entry = get_success_data(api_client.create_allocation_entry(
        plan_id, payload, users["scp"]["headers"]), 201)
    return entry


def get_plan_version(users, plan_id):
    plan = get_success_data(api_client.get_allocation_plan(
        plan_id, users["scp"]["headers"]))
    return plan["version"]


def activate_plan(users, plan_id):
    """Activate with a fresh OCC read of the plan version (PRD §2.6)."""
    version = get_plan_version(users, plan_id)
    return get_success_data(api_client.activate_allocation_plan(
        plan_id, {"expected_plan_version": version}, users["scp"]["headers"]))


def get_entry(users, entry_id):
    return get_success_data(api_client.get_allocation_entry(
        entry_id, users["scp"]["headers"]))
