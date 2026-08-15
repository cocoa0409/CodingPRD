"""Composite setup helpers.

These encapsulate the multi-step workflows of PRD §3 (customer onboarding,
consignment intake, recipe approval, tank cleaning/validation, batch release,
charging, completion packaging) so tests can focus on assertions.

All helpers use ``get_success_data`` so a setup failure surfaces as a clear
"Setup failed" message instead of a confusing assertion error. Every helper
builds its preconditions from scratch against an empty database (the runner
restarts the server before each test).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START, ZONE_FOR_GHS
from .factories import (
    batch_charge_payload,
    batch_job_payload,
    cleaning_record_payload,
    customer_payload,
    heel_disposal_payload,
    lot_payload,
    package_config_payload,
    pricing_agreement_payload,
    recipe_component,
    recipe_payload,
    sds_payload,
    shipment_payload,
    tank_payload,
)
from .test_users import TEST_USERS

QM = TEST_USERS["quality_manager_headers"]
SCHED = TEST_USERS["batch_scheduler_headers"]
OPERATOR = TEST_USERS["tank_operator_headers"]
QA = TEST_USERS["qa_validator_headers"]
SDS_AUTHOR = TEST_USERS["sds_author_headers"]
CLERK = TEST_USERS["shipping_clerk_headers"]


def _setup_ok(response, what):
    assert response.status_code < 300, (
        f"Setup failed ({what}): HTTP {response.status_code} — {response.text}")
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_customer(legal_name=None, credit_hold=None, headers=None) -> dict:
    """Create a customer (born ACTIVE, version 1)."""
    overrides = {}
    if legal_name is not None:
        overrides["legal_name"] = legal_name
    if credit_hold is not None:
        overrides["credit_hold"] = credit_hold
    resp = api_client.create_customer(customer_payload(**overrides), headers or QM)
    return _setup_ok(resp, "create customer")


def suspend_customer(customer_id) -> dict:
    return _setup_ok(api_client.suspend_customer(customer_id, QM), "suspend customer")


def create_pricing_agreement(customer_id, activate=False, **overrides) -> dict:
    """Create a pricing agreement (DRAFT); optionally activate it (OCC-guarded)."""
    resp = api_client.create_pricing_agreement(
        customer_id, pricing_agreement_payload(**overrides), QM)
    agreement = _setup_ok(resp, "create pricing agreement")
    if activate:
        agreement = activate_pricing_agreement(customer_id, agreement)
    return agreement


def activate_pricing_agreement(customer_id, agreement) -> dict:
    """Activate a DRAFT agreement using its current version (OCC)."""
    resp = api_client.activate_pricing_agreement(
        customer_id, agreement["id"], agreement["version"], QM)
    return _setup_ok(resp, "activate pricing agreement")


def receive_lot(customer_id, material_code="M-A", ghs_class="NON_HAZ",
                quantity_kg_received=1000, storage_zone=None, **overrides) -> dict:
    """Receive a consignment lot; zone defaults to the one admitting the class."""
    if storage_zone is None:
        storage_zone = ZONE_FOR_GHS[ghs_class]
    payload = lot_payload(material_code=material_code, ghS_class=ghs_class,
                          quantity_kg_received=quantity_kg_received,
                          storage_zone=storage_zone, **overrides)
    resp = api_client.create_lot(customer_id, payload, SCHED)
    return _setup_ok(resp, "receive lot")


def create_recipe(customer_id, components=None, **overrides) -> dict:
    """Create a recipe (DRAFT). Create lots first so hazard profiling resolves."""
    if components is None:
        components = [recipe_component()]
    resp = api_client.create_recipe(
        recipe_payload(customer_id, components=components, **overrides), QM)
    return _setup_ok(resp, "create recipe")


def approve_recipe(recipe_id) -> dict:
    return _setup_ok(api_client.approve_recipe(recipe_id, QM), "approve recipe")


def create_approved_recipe(customer_id, components=None, **overrides) -> dict:
    recipe = create_recipe(customer_id, components=components, **overrides)
    return approve_recipe(recipe["id"])


def create_tank(zone="Z_GENERAL", capacity_l=1000, working_capacity_l=1000,
                **overrides) -> dict:
    """Register a tank (AVAILABLE / DIRTY, last_product_ghs null)."""
    resp = api_client.create_tank(
        tank_payload(capacity_l=capacity_l, working_capacity_l=working_capacity_l,
                     current_zone=zone, **overrides), QM)
    return _setup_ok(resp, "create tank")


def open_cleaning_record(tank_id, operator_headers=None, **overrides) -> dict:
    """Open a cleaning record on a DIRTY, AVAILABLE tank (validation PENDING)."""
    resp = api_client.create_cleaning_record(
        tank_id, cleaning_record_payload(**overrides), operator_headers or OPERATOR)
    return _setup_ok(resp, "open cleaning record")


def submit_cleaning_record(tank_id, record_id, operator_headers=None) -> dict:
    resp = api_client.submit_cleaning_record(tank_id, record_id,
                                             operator_headers or OPERATOR)
    return _setup_ok(resp, "submit cleaning record")


def validate_cleaning_record(tank_id, record_id, decision="PASS",
                             validator_headers=None) -> dict:
    resp = api_client.validate_cleaning_record(tank_id, record_id, decision,
                                               validator_headers or QA)
    return _setup_ok(resp, "validate cleaning record")


def clean_validate_tank(tank_id, **record_overrides) -> dict:
    """Run the full maker-checker cleaning cycle to CLEAN_VALIDATED."""
    record = open_cleaning_record(tank_id, **record_overrides)
    submit_cleaning_record(tank_id, record["id"])
    validate_cleaning_record(tank_id, record["id"], decision="PASS")
    return get_tank(tank_id)


def create_clean_validated_tank(zone="Z_GENERAL", **overrides) -> dict:
    """Register a tank and drive its cleaning axis to CLEAN_VALIDATED."""
    tank = create_tank(zone=zone, **overrides)
    return clean_validate_tank(tank["id"])


def get_tank(tank_id) -> dict:
    return _setup_ok(api_client.get_tank(tank_id, QM), "get tank")


def get_batch_job(customer_id, batch_job_id) -> dict:
    return _setup_ok(api_client.get_batch_job(customer_id, batch_job_id, QM),
                     "get batch job")


def get_lot(customer_id, lot_id) -> dict:
    return _setup_ok(api_client.get_lot(customer_id, lot_id, QM), "get lot")


# ---------------------------------------------------------------------------
# Tier 2/3: batch job hierarchy and lifecycle
# ---------------------------------------------------------------------------

def create_batch_job(customer_id, recipe_id, pricing_agreement_id, tank_id,
                     **overrides) -> dict:
    """Create a batch job (born INTAKE, version 1, quote computed)."""
    resp = api_client.create_batch_job(
        customer_id,
        batch_job_payload(recipe_id, pricing_agreement_id, tank_id, **overrides),
        SCHED)
    return _setup_ok(resp, "create batch job")


def release_batch_job(customer_id, batch_job) -> dict:
    """Release an INTAKE batch using its current version (OCC)."""
    resp = api_client.release_batch_job(
        customer_id, batch_job["id"], batch_job["version"], SCHED)
    return _setup_ok(resp, "release batch job")


def post_batch_charge(customer_id, batch_job_id, lot_id, charge_order=1,
                      charged_qty_kg=100) -> dict:
    resp = api_client.create_batch_charge(
        customer_id, batch_job_id,
        batch_charge_payload(lot_id, charge_order=charge_order,
                             charged_qty_kg=charged_qty_kg),
        OPERATOR)
    return _setup_ok(resp, "post batch charge")


def author_sds(customer_id, batch_job_id, ghs_classification="NON_HAZ",
               **overrides) -> dict:
    resp = api_client.create_sds(
        customer_id, batch_job_id,
        sds_payload(ghs_classification, **overrides), SDS_AUTHOR)
    return _setup_ok(resp, "author SDS")


def issue_sds(customer_id, batch_job_id, sds_id) -> dict:
    return _setup_ok(api_client.issue_sds(customer_id, batch_job_id, sds_id,
                                          SDS_AUTHOR), "issue SDS")


def author_and_issue_sds(customer_id, batch_job_id, ghs_classification="NON_HAZ",
                         **overrides) -> dict:
    sds = author_sds(customer_id, batch_job_id, ghs_classification, **overrides)
    return issue_sds(customer_id, batch_job_id, sds["id"])


def create_package_config(customer_id, batch_job_id, **overrides) -> dict:
    resp = api_client.create_package_config(
        customer_id, batch_job_id, package_config_payload(**overrides), CLERK)
    return _setup_ok(resp, "create package config")


def create_shipment(customer_id, batch_job_id, **overrides) -> dict:
    resp = api_client.create_shipment(
        customer_id, batch_job_id, shipment_payload(**overrides), CLERK)
    return _setup_ok(resp, "create shipment")


def create_and_post_heel_disposal(customer_id, batch_job_id, lot_id,
                                  **overrides) -> dict:
    record = _setup_ok(
        api_client.create_heel_disposal(
            customer_id, batch_job_id,
            heel_disposal_payload(lot_id, **overrides), OPERATOR),
        "create heel disposal")
    return _setup_ok(
        api_client.post_heel_disposal(customer_id, batch_job_id, record["id"],
                                      OPERATOR),
        "post heel disposal")


# ---------------------------------------------------------------------------
# Tier 4/5: full scenario builders
# ---------------------------------------------------------------------------

def setup_batch_context(ghs_class="NON_HAZ", pricing_mode="TOLLING_FEE",
                        density=1.0, yield_pct=100.0, batch_size_l=100,
                        lot_quantity_kg=1000, material_code="M-A",
                        pricing_overrides=None, batch_overrides=None,
                        activate_agreement=True, tank_overrides=None,
                        materials=None, components=None) -> dict:
    """Build the standard landscape: ACTIVE customer, consignment lot(s),
    APPROVED recipe, pricing agreement, CLEAN_VALIDATED tank, and an INTAKE
    batch job. Returns a context dict.

    ``materials``: list of {"material_code", "ghs_class", "quantity_kg_received"}.
    ``components``: recipe components; defaults to a single 100% component on
    the first material. Lots are received before recipe creation so the
    recipe's hazard profile resolves (PRD §3.3).
    """
    if materials is None:
        materials = [{"material_code": material_code, "ghs_class": ghs_class,
                      "quantity_kg_received": lot_quantity_kg}]
    if components is None:
        components = [recipe_component(materials[0]["material_code"], 100.0, 1)]

    customer = create_customer()
    lots = {}
    for m in materials:
        lots[m["material_code"]] = receive_lot(
            customer["id"], material_code=m["material_code"],
            ghs_class=m["ghs_class"],
            quantity_kg_received=m["quantity_kg_received"])
    recipe = create_approved_recipe(
        customer["id"], components=components,
        target_density_kg_per_l=density, theoretical_yield_pct=yield_pct)
    pa_overrides = dict(pricing_overrides or {})
    pa_overrides.setdefault("pricing_mode", pricing_mode)
    agreement = create_pricing_agreement(customer["id"],
                                         activate=activate_agreement,
                                         **pa_overrides)
    highest_ghs = recipe["highest_component_ghs"]
    tank_kw = dict(tank_overrides or {})
    tank = create_clean_validated_tank(zone=ZONE_FOR_GHS[highest_ghs], **tank_kw)

    batch_kw = dict(batch_overrides or {})
    batch_kw.setdefault("batch_size_l", batch_size_l)
    batch = create_batch_job(customer["id"], recipe["id"], agreement["id"],
                             tank["id"], **batch_kw)
    return {"customer": customer, "lots": lots, "recipe": recipe,
            "agreement": agreement, "tank": tank, "batch": batch}


def setup_released_batch(**kwargs) -> dict:
    """Context with the batch driven INTAKE -> RELEASED (tank RESERVED)."""
    ctx = setup_batch_context(**kwargs)
    ctx["batch"] = release_batch_job(ctx["customer"]["id"], ctx["batch"])
    ctx["tank"] = get_tank(ctx["tank"]["id"])
    return ctx


def drive_batch_to_hold_qa(ctx, charge_qty_kg=100, charge_qty_by_order=None) -> dict:
    """From RELEASED: commit one charge per recipe component, then
    start-charging -> start-mixing -> hold-for-qa."""
    customer_id = ctx["customer"]["id"]
    batch_id = ctx["batch"]["id"]
    for comp in ctx["recipe"]["components"]:
        qty = charge_qty_kg
        if charge_qty_by_order and comp["charge_order"] in charge_qty_by_order:
            qty = charge_qty_by_order[comp["charge_order"]]
        lot = ctx["lots"][comp["material_code"]]
        post_batch_charge(customer_id, batch_id, lot["id"],
                          charge_order=comp["charge_order"], charged_qty_kg=qty)
    ctx["batch"] = _setup_ok(
        api_client.start_charging(customer_id, batch_id, OPERATOR), "start charging")
    ctx["batch"] = _setup_ok(
        api_client.start_mixing(customer_id, batch_id, OPERATOR), "start mixing")
    ctx["batch"] = _setup_ok(
        api_client.hold_for_qa(customer_id, batch_id, OPERATOR), "hold for qa")
    ctx["tank"] = get_tank(ctx["tank"]["id"])
    return ctx


def setup_batch_in_hold_qa(charge_qty_kg=100, **kwargs) -> dict:
    """Context with the batch driven all the way to HOLD_QA."""
    ctx = setup_released_batch(**kwargs)
    return drive_batch_to_hold_qa(ctx, charge_qty_kg=charge_qty_kg)


def setup_batch_ready_for_completion(sds=True, package=True, heel=True,
                                     package_overrides=None, heel_returned_kg=5,
                                     charge_qty_kg=100, with_shipment=False,
                                     **kwargs) -> dict:
    """Context with the batch in HOLD_QA plus (optionally) an ISSUED SDS, a
    package configuration, and a POSTED heel disposal for the charged lot —
    the full gauntlet of completion preconditions (PRD §3.6)."""
    ctx = setup_batch_in_hold_qa(charge_qty_kg=charge_qty_kg, **kwargs)
    customer_id = ctx["customer"]["id"]
    batch_id = ctx["batch"]["id"]
    ghs = ctx["batch"]["highest_component_ghs_snapshot"]
    if sds:
        ctx["sds"] = author_and_issue_sds(customer_id, batch_id, ghs)
    if package:
        pkg_kw = {"un_rated": ghs != "NON_HAZ"}
        pkg_kw.update(package_overrides or {})
        ctx["package_config"] = create_package_config(customer_id, batch_id,
                                                      **pkg_kw)
    if heel:
        for comp in ctx["recipe"]["components"]:
            lot = ctx["lots"][comp["material_code"]]
            ctx.setdefault("heels", {})[comp["material_code"]] = \
                create_and_post_heel_disposal(customer_id, batch_id, lot["id"],
                                              heel_returned_kg=heel_returned_kg)
    if with_shipment:
        placards = []
        if package and ctx["package_config"]["placard_required"]:
            placards = [ctx["package_config"]["placard_class"]]
        ctx["shipment"] = create_shipment(customer_id, batch_id,
                                          vehicle_placards=placards)
    return ctx


def setup_completed_batch(actual_output_kg=95, **kwargs) -> dict:
    """Full lifecycle through COMPLETED."""
    ctx = setup_batch_ready_for_completion(**kwargs)
    ctx["batch"] = _setup_ok(
        api_client.complete_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                      actual_output_kg, QA),
        "complete batch job")
    ctx["tank"] = get_tank(ctx["tank"]["id"])
    return ctx
