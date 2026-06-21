"""Composite setup helpers.

Each helper encapsulates a multi-step API sequence so tests can focus on
assertions. Helpers use get_success_data() (lenient) internally so a setup
failure surfaces as a clear "Setup failed" rather than a confusing assertion.

The test harness restarts the API server (empty DB) before every test, so each
helper builds all of its preconditions from scratch using only PRD-declared
endpoints. The Applicator role is entity-backed: helpers that confirm restricted
applications build the Applicator headers from the real Applicator.id via
make_applicator_headers() (PRD §2.1, §3.4).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_applicator_headers,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ---------------------------------------------------------------------------
# Clock control (PRD §3.10) — FarmManager-only
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, FM))


# ---------------------------------------------------------------------------
# Tier 0: single-entity registry creators
# ---------------------------------------------------------------------------
def create_parcel(name="Test Parcel", acreage=100.0, soil_type="LOAM"):
    return get_success_data(api_client.create_parcel(
        {"name": name, "acreage": acreage, "soil_type": soil_type}, FM))


def create_seed_product(name="Seed", unit_cost=0.5):
    return get_success_data(api_client.create_input_product(
        {"name": name, "category": "SEED", "unit": "SEED_UNIT", "unit_cost": unit_cost}, FM))


def create_input_product(**fields):
    payload = {"name": "Product", "category": "FERTILIZER", "unit": "GAL", "unit_cost": 5.0}
    payload.update(fields)
    return get_success_data(api_client.create_input_product(payload, FM))


def create_restricted_product(name="RU Chem", unit_cost=10.0, reentry_interval_hours=48,
                              preharvest_interval_days=7, max_seasonal_rate_per_acre=None):
    payload = {
        "name": name, "category": "CHEMICAL", "unit": "GAL", "unit_cost": unit_cost,
        "restricted_use": True,
        "reentry_interval_hours": reentry_interval_hours,
        "preharvest_interval_days": preharvest_interval_days,
    }
    if max_seasonal_rate_per_acre is not None:
        payload["max_seasonal_rate_per_acre"] = max_seasonal_rate_per_acre
    return get_success_data(api_client.create_input_product(payload, FM))


def create_input_lot(product_id, lot_code="L", quantity_received=500.0):
    return get_success_data(api_client.create_input_lot(
        {"input_product_id": product_id, "lot_code": lot_code,
         "quantity_received": quantity_received}, FM))


def create_applicator(full_name="Applicator", license_no="RU-1", certified=True):
    return get_success_data(api_client.create_applicator(
        {"full_name": full_name, "license_no": license_no, "certified": certified}, FM))


def create_equipment_asset(name="Asset", kind="TRACTOR", hourly_cost=50.0):
    return get_success_data(api_client.create_equipment_asset(
        {"name": name, "kind": kind, "hourly_cost": hourly_cost}, FM))


def create_sale_contract(crop="CORN", buyer_name="Buyer", contracted_quantity=2000.0,
                         price_per_unit=5.0, min_quality=None):
    payload = {"crop": crop, "buyer_name": buyer_name,
               "contracted_quantity": contracted_quantity, "price_per_unit": price_per_unit}
    if min_quality is not None:
        payload["min_quality"] = min_quality
    return get_success_data(api_client.create_sale_contract(payload, SA))


# ---------------------------------------------------------------------------
# Tier 1: crop-plan state progression
# ---------------------------------------------------------------------------
def create_draft_plan(parcel_id, crop="CORN", planned_acres=50.0, season_year=2026,
                      budget_input_cost=1.0, budget_labor_cost=1.0, budget_equipment_cost=1.0):
    return get_success_data(api_client.create_crop_plan({
        "parcel_id": parcel_id, "crop": crop, "season_year": season_year,
        "planned_acres": planned_acres,
        "budget_input_cost": budget_input_cost,
        "budget_labor_cost": budget_labor_cost,
        "budget_equipment_cost": budget_equipment_cost,
    }, AG))


def approve_plan(plan_id, expected_parcel_version):
    return get_success_data(api_client.approve_crop_plan(
        plan_id, {"expected_parcel_version": expected_parcel_version}, FM))


def create_and_approve_plan(parcel, crop="CORN", planned_acres=50.0, season_year=2026,
                            budgets=(1.0, 1.0, 1.0)):
    """Create a DRAFT plan on `parcel` and approve it. Returns (plan, parcel_version_after)."""
    plan = create_draft_plan(
        parcel["id"], crop=crop, planned_acres=planned_acres, season_year=season_year,
        budget_input_cost=budgets[0], budget_labor_cost=budgets[1], budget_equipment_cost=budgets[2])
    approve_plan(plan["id"], parcel["version"])
    parcel_now = get_success_data(api_client.get_parcel(parcel["id"], FM))
    return plan, parcel_now["version"]


def record_planting(plan_id, lot_id, acres_planted, seed_rate_per_acre=1.0):
    return get_success_data(api_client.create_planting_event({
        "crop_plan_id": plan_id, "input_lot_id": lot_id,
        "acres_planted": acres_planted, "seed_rate_per_acre": seed_rate_per_acre}, AG))


def create_growing_plan(parcel, crop="CORN", planned_acres=100.0, season_year=2026,
                        budgets=(1.0, 1.0, 1.0), seed_quantity=500.0, planted_acres=None):
    """Build a plan all the way to GROWING.

    parcel -> seed product + lot -> create plan -> approve -> planting -> begin-growing.
    Returns dict with parcel, plan, seed_product, seed_lot.
    """
    if planted_acres is None:
        planted_acres = planned_acres
    seed_product = create_seed_product()
    seed_lot = create_input_lot(seed_product["id"], quantity_received=seed_quantity)
    plan, _ = create_and_approve_plan(parcel, crop=crop, planned_acres=planned_acres,
                                      season_year=season_year, budgets=budgets)
    record_planting(plan["id"], seed_lot["id"], planted_acres, seed_rate_per_acre=1.0)
    plan = get_success_data(api_client.begin_growing(plan["id"], AG))
    return {"parcel": parcel, "plan": plan, "seed_product": seed_product, "seed_lot": seed_lot}


def setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0, season_year=2026,
                       budgets=(1.0, 1.0, 1.0), parcel_name="Field", soil_type="LOAM"):
    """Fresh parcel driven through to a GROWING plan. Returns dict (parcel, plan, ...)."""
    parcel = create_parcel(name=parcel_name, acreage=acreage, soil_type=soil_type)
    return create_growing_plan(parcel, crop=crop, planned_acres=planned_acres,
                               season_year=season_year, budgets=budgets)


def setup_harvesting_plan(crop="CORN", planned_acres=100.0, acreage=100.0, season_year=2026,
                          budgets=(1.0, 1.0, 1.0)):
    """GROWING plan with no restricted applications -> begin-harvest -> HARVESTING.
    Returns dict (parcel, plan, seed_product, seed_lot)."""
    ctx = setup_growing_plan(crop=crop, planned_acres=planned_acres, acreage=acreage,
                             season_year=season_year, budgets=budgets)
    ctx["plan"] = get_success_data(api_client.begin_harvest(ctx["plan"]["id"], AG))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: harvest inventory (lots + grading)
# ---------------------------------------------------------------------------
def record_harvest(plan_id, acres_harvested=100.0, gross_quantity=1000.0, moisture_pct=0.0):
    return get_success_data(api_client.create_harvest_event({
        "crop_plan_id": plan_id, "acres_harvested": acres_harvested,
        "gross_quantity": gross_quantity, "moisture_pct": moisture_pct}, AG))


def create_lot(harvest_event_id, quantity):
    return get_success_data(api_client.create_harvest_lot(
        {"harvest_event_id": harvest_event_id, "quantity": quantity}, AG))


def create_graded_lot(harvest_event_id, quantity, grade):
    lot = create_lot(harvest_event_id, quantity)
    lot = get_success_data(api_client.grade_harvest_lot(lot["id"], {"grade": grade}, AG))
    return lot


def setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A", acreage=100.0,
                     harvest_acres=100.0):
    """HARVESTING plan -> one harvest event -> one graded lot.
    Returns dict (parcel, plan, harvest_event, lot)."""
    ctx = setup_harvesting_plan(crop=crop, planned_acres=harvest_acres, acreage=acreage)
    he = record_harvest(ctx["plan"]["id"], acres_harvested=harvest_acres,
                        gross_quantity=quantity, moisture_pct=0.0)
    lot = create_graded_lot(he["id"], quantity, grade)
    ctx["harvest_event"] = he
    ctx["lot"] = lot
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: restricted-application compliance cascade (PRD §3.4)
# ---------------------------------------------------------------------------
def log_application(plan_id, product_id, applicator_id, rate_per_acre=1.0, acres_treated=50.0,
                    as_headers=None):
    headers = as_headers if as_headers is not None else AG
    return get_success_data(api_client.create_application_record({
        "crop_plan_id": plan_id, "input_product_id": product_id,
        "applicator_user_id": applicator_id, "rate_per_acre": rate_per_acre,
        "acres_treated": acres_treated}, headers))


def confirm_application(record_id, applicator_id):
    """Confirm as the entity-backed Applicator whose id matches applicator_user_id."""
    return get_success_data(api_client.confirm_application(
        record_id, make_applicator_headers(applicator_id)))


def setup_confirmed_restricted_application(reentry_interval_hours=48, preharvest_interval_days=7,
                                           confirm_clock="2026-06-10T00:00:00Z",
                                           rate_per_acre=1.0, acres_treated=50.0,
                                           initial_clock="2026-06-01T00:00:00Z"):
    """GROWING plan + a restricted CHEMICAL application confirmed at confirm_clock.

    Confirming flips the parcel to RESTRICTED, creates an ACTIVE ComplianceRecord,
    and sets reentry_blocked_until. Returns dict with
    parcel, plan, chem_product, applicator, app_record, confirmed_record.
    """
    set_clock(initial_clock)
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    chem = create_restricted_product(
        reentry_interval_hours=reentry_interval_hours,
        preharvest_interval_days=preharvest_interval_days)
    applicator = create_applicator(license_no="RU-CONF")
    set_clock(confirm_clock)
    rec = log_application(ctx["plan"]["id"], chem["id"], applicator["id"],
                          rate_per_acre=rate_per_acre, acres_treated=acres_treated)
    confirmed = confirm_application(rec["id"], applicator["id"])
    ctx.update({
        "chem_product": chem,
        "applicator": applicator,
        "app_record": rec,
        "confirmed_record": confirmed,
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: sale-contract commit scenarios
# ---------------------------------------------------------------------------
def commit_lot(contract_id, lot_id, commit_quantity):
    return get_success_data(api_client.commit_lot(
        contract_id, {"harvest_lot_id": lot_id, "commit_quantity": commit_quantity}, SA))


def setup_partially_committed_contract(lot_quantity=1000.0, contracted_quantity=2000.0,
                                       commit_quantity=400.0, price_per_unit=5.0,
                                       min_quality=None, crop="CORN", grade="GRADE_A"):
    """A graded lot partially committed to an OPEN contract (now PARTIALLY_FILLED).
    Returns dict (parcel, plan, harvest_event, lot, contract)."""
    ctx = setup_graded_lot(crop=crop, quantity=lot_quantity, grade=grade)
    contract = create_sale_contract(crop=crop, contracted_quantity=contracted_quantity,
                                    price_per_unit=price_per_unit, min_quality=min_quality)
    commit_lot(contract["id"], ctx["lot"]["id"], commit_quantity)
    ctx["contract"] = contract
    return ctx


def setup_filled_contract(lot_quantity=1000.0, contracted_quantity=1000.0, price_per_unit=5.0,
                          crop="CORN", grade="GRADE_A"):
    """A graded lot fully committed to a contract that reaches FILLED.
    Returns dict (parcel, plan, harvest_event, lot, contract)."""
    ctx = setup_graded_lot(crop=crop, quantity=lot_quantity, grade=grade)
    contract = create_sale_contract(crop=crop, contracted_quantity=contracted_quantity,
                                    price_per_unit=price_per_unit)
    commit_lot(contract["id"], ctx["lot"]["id"], lot_quantity)
    ctx["contract"] = contract
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: equipment usage (booked windows)
# ---------------------------------------------------------------------------
def book_usage(asset_id, plan_id, window_start, window_end):
    return get_success_data(api_client.create_equipment_usage({
        "equipment_asset_id": asset_id, "crop_plan_id": plan_id,
        "window_start": window_start, "window_end": window_end}, AG))


def setup_asset_with_usage(window_start="2026-06-15T08:00:00Z", window_end="2026-06-15T10:00:00Z",
                           hourly_cost=50.0):
    """ACTIVE equipment asset with one RECORDED usage on a GROWING plan.
    Returns dict (parcel, plan, asset, usage)."""
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    asset = create_equipment_asset(hourly_cost=hourly_cost)
    usage = book_usage(asset["id"], ctx["plan"]["id"], window_start, window_end)
    ctx["asset"] = asset
    ctx["usage"] = usage
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: irrigation
# ---------------------------------------------------------------------------
def schedule_irrigation(parcel_id, window_start, window_end, inches_applied=1.0):
    return get_success_data(api_client.create_irrigation_event({
        "parcel_id": parcel_id, "window_start": window_start, "window_end": window_end,
        "inches_applied": inches_applied}, AG))
