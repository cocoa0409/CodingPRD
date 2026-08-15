"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so nothing is
carried over). Setup calls use get_success_data() so a failed precondition
surfaces as a clear "Setup step failed" message rather than a confusing
assertion error deep in a test.

Date arithmetic helpers are included because the PRD's temporal rules
(lead time, herbicide age, survey window, handling deadline, stock age) are
all judged against the logical clock (PRD §2.5).
"""
import math
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_landowner_payload,
    create_seed_zone_payload,
    create_seed_lot_payload,
    create_crop_batch_payload,
    create_seedling_order_payload,
    create_allocation_payload,
    create_storage_unit_payload,
    create_storage_placement_payload,
    create_planting_contract_payload,
    create_crew_payload,
    create_crew_assignment_payload,
    create_shipment_payload,
    create_survival_survey_payload,
    create_cost_share_enrollment_payload,
)
from .test_users import TEST_USERS, make_landowner_headers

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]
FA = TEST_USERS["field_auditor_headers"]
PA = TEST_USERS["program_administrator_headers"]


# ─── Date helpers ────────────────────────────────────────────────────────────

def _date_add_days(iso_date_str: str, days: int) -> str:
    d = date.fromisoformat(iso_date_str)
    return (d + timedelta(days=days)).isoformat()


def _datetime_add_hours(iso_dt_str: str, hours: int) -> str:
    dt = datetime.fromisoformat(iso_dt_str.replace("Z", "+00:00"))
    return (dt + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def compute_required_seedlings(acres, trees_per_acre, contingency_pct) -> int:
    """required_seedlings per PRD §3.5: ceil(acres * TPA * (1 + c_eff)) with the
    +0.05 large-site surcharge at acres >= 50."""
    c_eff = contingency_pct + (0.05 if acres >= 50 else 0)
    return math.ceil(acres * trees_per_acre * (1 + c_eff))


# ─── Tier 1: single-entity creation shortcuts ───────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, NM))


def create_landowner(**overrides) -> dict:
    return get_success_data(api_client.create_landowner(create_landowner_payload(**overrides), CO))


def get_landowner(landowner_id, headers=None) -> dict:
    return get_success_data(api_client.get_landowner(landowner_id, headers or CO))


def create_seed_zone(zone_min=1000, zone_max=2000, **overrides) -> dict:
    payload = create_seed_zone_payload(
        min_elevation_ft=zone_min, max_elevation_ft=zone_max, **overrides
    )
    return get_success_data(api_client.create_seed_zone(payload, NM))


def create_seed_lot(zone_id, species="DOUGLAS_FIR", quantity_grams=500,
                    germination_pct=0.85, collected_on="2026-07-15") -> dict:
    payload = create_seed_lot_payload(
        zone_id, species=species, collected_on=collected_on,
        quantity_grams=quantity_grams, germination_pct=germination_pct,
    )
    return get_success_data(api_client.create_seed_lot(payload, NM))


def create_crop_batch(lot_id, expected_seed_lot_version, **overrides) -> dict:
    payload = create_crop_batch_payload(lot_id, expected_seed_lot_version, **overrides)
    return get_success_data(api_client.create_crop_batch(payload, NM))


def sow_batch(batch_id, sown_grams, actual_sow_date="2026-09-01") -> dict:
    payload = {"actual_sow_date": actual_sow_date, "sown_grams": sown_grams}
    return get_success_data(api_client.sow_crop_batch(batch_id, payload, NM))


def lift_batch(batch_id, lifted_on="2027-03-10", lifted_count=9500) -> dict:
    payload = {"lifted_on": lifted_on, "lifted_count": lifted_count}
    return get_success_data(api_client.lift_crop_batch(batch_id, payload, NM))


def grade_batch(batch_id, plantable_count) -> dict:
    return get_success_data(
        api_client.grade_crop_batch(batch_id, {"plantable_count": plantable_count}, NM)
    )


def create_order(landowner_id, zone_id, quantity, species="DOUGLAS_FIR",
                 ship_date="2027-04-05") -> dict:
    """Create a seedling order as the entity-backed Landowner (PRD §3.3:
    landowner_id must equal X-User-ID)."""
    payload = create_seedling_order_payload(
        landowner_id, zone_id, species=species, quantity=quantity,
        requested_ship_date=ship_date,
    )
    return get_success_data(
        api_client.create_seedling_order(payload, make_landowner_headers(landowner_id))
    )


def confirm_order(order_id) -> dict:
    return get_success_data(api_client.confirm_seedling_order(order_id, CO))


def cancel_order(order_id, landowner_id=None) -> dict:
    headers = make_landowner_headers(landowner_id) if landowner_id else CO
    return get_success_data(api_client.cancel_seedling_order(order_id, headers))


def create_allocation(order_id, batch_id, quantity) -> dict:
    payload = create_allocation_payload(batch_id, quantity)
    return get_success_data(api_client.create_allocation(order_id, payload, CO))


def create_contract(landowner_id, order_id, zone_id, acres=10, trees_per_acre=400,
                    contingency_pct=0, window_start="2027-04-01",
                    window_end="2027-04-30") -> dict:
    payload = create_planting_contract_payload(
        landowner_id, order_id, zone_id,
        acres=acres, trees_per_acre=trees_per_acre, contingency_pct=contingency_pct,
        planting_window_start=window_start, planting_window_end=window_end,
    )
    return get_success_data(api_client.create_planting_contract(payload, CO))


def record_site_prep(contract_id, herbicide_applied_on="2027-03-01") -> dict:
    return get_success_data(
        api_client.record_site_prep(contract_id, {"herbicide_applied_on": herbicide_applied_on}, CO)
    )


def verify_site_prep(contract_id) -> dict:
    return get_success_data(api_client.verify_site_prep(contract_id, FA))


def mark_ready(contract_id) -> dict:
    return get_success_data(api_client.mark_ready(contract_id, CO))


def start_planting(contract_id) -> dict:
    return get_success_data(api_client.start_planting(contract_id, CO))


def complete_planting(contract_id, planted_qty) -> dict:
    return get_success_data(
        api_client.complete_planting(contract_id, {"planted_qty": planted_qty}, CO)
    )


def create_crew(capacity_per_day=5000, **overrides) -> dict:
    return get_success_data(
        api_client.create_crew(create_crew_payload(capacity_per_day=capacity_per_day, **overrides), CO)
    )


def create_assignment(crew_id, contract_id, start_date, end_date, planned_seedlings) -> dict:
    payload = create_crew_assignment_payload(
        crew_id, contract_id, start_date, end_date, planned_seedlings
    )
    return get_success_data(api_client.create_crew_assignment(payload, CO))


def confirm_assignment(assignment_id) -> dict:
    return get_success_data(api_client.confirm_crew_assignment(assignment_id, CO))


def create_storage_unit(capacity_units=20000, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_unit(
            create_storage_unit_payload(capacity_units=capacity_units, **overrides), NM
        )
    )


def create_placement(batch_id, unit_id, quantity, placed_on="2027-03-12") -> dict:
    payload = create_storage_placement_payload(batch_id, unit_id, quantity, placed_on=placed_on)
    return get_success_data(api_client.create_storage_placement(payload, NM))


def create_shipment(contract_id, batch_id, quantity) -> dict:
    payload = create_shipment_payload(contract_id, batch_id, quantity)
    return get_success_data(api_client.create_shipment(payload, NM))


def deliver_shipment(shipment_id, delivered_at) -> dict:
    return get_success_data(
        api_client.deliver_shipment(shipment_id, {"delivered_at": delivered_at}, NM)
    )


def confirm_shipment_planted(shipment_id, planted_confirmed_at) -> dict:
    return get_success_data(
        api_client.confirm_shipment_planted(
            shipment_id, {"planted_confirmed_at": planted_confirmed_at}, CO
        )
    )


def create_survey(contract_id, surveyed_on, alive_count) -> dict:
    payload = create_survival_survey_payload(contract_id, surveyed_on, alive_count)
    return get_success_data(api_client.create_survival_survey(payload, FA))


def create_enrollment(landowner_id, program_code="EQIP-27", enrolled_acres=10,
                      rate_per_acre_cents=15000, cap_cents=200000) -> dict:
    payload = create_cost_share_enrollment_payload(
        landowner_id, program_code=program_code, enrolled_acres=enrolled_acres,
        rate_per_acre_cents=rate_per_acre_cents, cap_cents=cap_cents,
    )
    return get_success_data(
        api_client.create_cost_share_enrollment(payload, make_landowner_headers(landowner_id))
    )


def submit_enrollment(enrollment_id, landowner_id, documented_acres, documented_cost_cents) -> dict:
    payload = {
        "documented_acres": documented_acres,
        "documented_cost_cents": documented_cost_cents,
    }
    return get_success_data(
        api_client.submit_cost_share_enrollment(
            enrollment_id, payload, make_landowner_headers(landowner_id)
        )
    )


def approve_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.approve_cost_share_enrollment(enrollment_id, PA))


def create_approved_enrollment(landowner_id, enrolled_acres=10, rate_per_acre_cents=15000,
                               cap_cents=200000, documented_acres=10,
                               documented_cost_cents=90000) -> dict:
    """Landowner enrolls and submits documentation; ProgramAdministrator approves."""
    enr = create_enrollment(
        landowner_id, enrolled_acres=enrolled_acres,
        rate_per_acre_cents=rate_per_acre_cents, cap_cents=cap_cents,
    )
    submit_enrollment(enr["id"], landowner_id, documented_acres, documented_cost_cents)
    return approve_enrollment(enr["id"])


# ─── Tier 2: supply-side composites ─────────────────────────────────────────

def setup_sown_batch(quantity_grams=500, germination_pct=0.85, sown_grams=300,
                     species="DOUGLAS_FIR", zone_min=1000, zone_max=2000) -> dict:
    """Zone + lot + batch sown. Returns ctx dict with zone, lot, batch (SOWN)."""
    zone = create_seed_zone(zone_min=zone_min, zone_max=zone_max)
    lot = create_seed_lot(
        zone["id"], species=species, quantity_grams=quantity_grams,
        germination_pct=germination_pct,
    )
    batch = create_crop_batch(lot["id"], lot["version"])
    batch = sow_batch(batch["id"], sown_grams)
    return {"zone": zone, "lot": lot, "batch": batch}


def setup_graded_batch(quantity_grams=500, germination_pct=0.85, sown_grams=300,
                       lifted_count=21000, plantable_count=20000,
                       species="DOUGLAS_FIR", zone_min=1000, zone_max=2000,
                       lifted_on="2027-03-10") -> dict:
    """Zone + lot + batch walked to GRADED. Returns ctx with zone, lot, batch."""
    ctx = setup_sown_batch(
        quantity_grams=quantity_grams, germination_pct=germination_pct,
        sown_grams=sown_grams, species=species, zone_min=zone_min, zone_max=zone_max,
    )
    batch = lift_batch(ctx["batch"]["id"], lifted_on=lifted_on, lifted_count=lifted_count)
    batch = grade_batch(batch["id"], plantable_count)
    ctx["batch"] = batch
    return ctx


def setup_confirmed_order(landowner_id, zone_id, quantity, species="DOUGLAS_FIR",
                          ship_date="2027-04-05") -> dict:
    order = create_order(landowner_id, zone_id, quantity, species=species, ship_date=ship_date)
    return confirm_order(order["id"])


# ─── Tier 3: full pipeline to READY_TO_PLANT ────────────────────────────────

def setup_ready_world(
    *,
    acres=10,
    trees_per_acre=400,
    contingency_pct=0,
    order_quantity=None,
    allocation_quantity=None,
    species="DOUGLAS_FIR",
    germination_pct=0.85,
    lot_quantity_grams=500,
    sown_grams=300,
    lifted_count=21000,
    plantable_count=20000,
    grade=True,
    ship_date="2027-04-05",
    window_start="2027-04-01",
    window_end="2027-04-30",
    herbicide_applied_on="2027-03-01",
    prep_clock="2027-03-15T00:00:00Z",
    unit_capacity=25000,
    placement_quantities="auto",
    with_storage=True,
    enrollment=None,
    do_mark_ready=True,
) -> dict:
    """
    Full world up to a READY_TO_PLANT contract (unless do_mark_ready=False):
    source zone (midpoint 1500) + destination zone (midpoint 1900, inside the
    500 ft seed-transfer tolerance), landowner, lot, batch (sown; optionally
    lifted and graded), landowner's own order (confirmed), allocation, contract,
    optional APPROVED cost-share enrollment, site prep recorded + verified,
    mark-ready. With storage: one cold-storage unit and placements.

    Returns a ctx dict with every created entity.
    """
    z_src = create_seed_zone(zone_min=1000, zone_max=2000)
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    landowner = create_landowner()

    lot = create_seed_lot(
        z_src["id"], species=species, quantity_grams=lot_quantity_grams,
        germination_pct=germination_pct,
    )
    batch = create_crop_batch(lot["id"], lot["version"])
    batch = sow_batch(batch["id"], sown_grams)
    if grade:
        batch = lift_batch(batch["id"], lifted_count=lifted_count)
        batch = grade_batch(batch["id"], plantable_count)

    required = compute_required_seedlings(acres, trees_per_acre, contingency_pct)
    if order_quantity is None:
        order_quantity = required
    if allocation_quantity is None:
        allocation_quantity = order_quantity

    order = create_order(landowner["id"], z_dst["id"], order_quantity,
                         species=species, ship_date=ship_date)
    order = confirm_order(order["id"])
    allocation = None
    if allocation_quantity:
        allocation = create_allocation(order["id"], batch["id"], allocation_quantity)
        order = get_success_data(api_client.get_seedling_order(order["id"], CO))

    contract = create_contract(
        landowner["id"], order["id"], z_dst["id"],
        acres=acres, trees_per_acre=trees_per_acre, contingency_pct=contingency_pct,
        window_start=window_start, window_end=window_end,
    )

    enrollment_rec = None
    if enrollment is not None:
        enrollment_rec = create_approved_enrollment(landowner["id"], **enrollment)

    set_clock(prep_clock)
    contract = record_site_prep(contract["id"], herbicide_applied_on)
    contract = verify_site_prep(contract["id"])
    if do_mark_ready:
        contract = mark_ready(contract["id"])

    unit = None
    placements = []
    if with_storage and grade:
        unit = create_storage_unit(capacity_units=unit_capacity)
        if placement_quantities == "auto":
            placement_quantities = [(min(plantable_count, unit_capacity), "2027-03-12")]
        for qty, placed_on in placement_quantities:
            placements.append(create_placement(batch["id"], unit["id"], qty, placed_on))

    return {
        "z_src": z_src,
        "z_dst": z_dst,
        "landowner": landowner,
        "lot": lot,
        "batch": batch,
        "order": order,
        "allocation": allocation,
        "contract": contract,
        "enrollment": enrollment_rec,
        "unit": unit,
        "placements": placements,
        "required_seedlings": required,
    }


# ─── Tier 4: pipeline to PLANTED ─────────────────────────────────────────────

def drive_to_planted(ctx, *, plant_date="2027-04-01", planted_qty=None,
                     crew_capacity=5000, assignment_days=2, planned_seedlings=None,
                     extra_assignments=(), ship=True) -> dict:
    """
    From a READY_TO_PLANT ctx: crew + one CONFIRMED assignment covering
    plant_date (plus any extra assignments), clock to plant_date,
    start-planting, optional shipment -> deliver -> confirm-planted,
    complete-planting. Mutates and returns ctx with crew/assignment/shipment.
    """
    contract_id = ctx["contract"]["id"]
    if planted_qty is None:
        planted_qty = ctx["required_seedlings"]
    if planned_seedlings is None:
        planned_seedlings = planted_qty

    crew = create_crew(capacity_per_day=crew_capacity)
    assignment = create_assignment(
        crew["id"], contract_id, plant_date,
        _date_add_days(plant_date, assignment_days), planned_seedlings,
    )
    assignment = confirm_assignment(assignment["id"])

    extras = []
    for spec in extra_assignments:
        ex = create_assignment(
            crew["id"], contract_id, spec["start_date"], spec["end_date"],
            spec["planned_seedlings"],
        )
        if spec.get("confirm"):
            ex = confirm_assignment(ex["id"])
        extras.append(ex)

    set_clock(f"{plant_date}T00:00:00Z")
    contract = start_planting(contract_id)

    shipment = None
    if ship:
        shipment = create_shipment(contract_id, ctx["batch"]["id"], planted_qty)
        deliver_shipment(shipment["id"], f"{plant_date}T08:00:00Z")
        confirm_shipment_planted(
            shipment["id"], f"{_date_add_days(plant_date, 1)}T09:00:00Z"
        )

    contract = complete_planting(contract_id, planted_qty)

    ctx.update({
        "crew": crew,
        "assignment": assignment,
        "extra_assignments": extras,
        "shipment": shipment,
        "contract": contract,
        "planted_qty": planted_qty,
        "plant_date": plant_date,
    })
    return ctx


# ─── Tier 5: survival survey / replant-cycle composites ─────────────────────

def setup_replant_required_world(*, acres=10, trees_per_acre=400, contingency_pct=0,
                                 order_quantity=None, alive_count=2700,
                                 surveyed_on="2028-02-15", enrollment=None,
                                 extra_assignments=(), window_end="2028-12-31",
                                 plant_date="2027-04-01", crew_capacity=5000,
                                 assignment_days=2, **world_kwargs) -> dict:
    """
    Full pipeline through a failing survival survey: READY_TO_PLANT world,
    planted, then surveyed below threshold so the contract flips to
    REPLANT_REQUIRED with an OPEN obligation (PRD §3.6 CASCADE B).
    Returns ctx including survey.
    """
    ctx = setup_ready_world(
        acres=acres, trees_per_acre=trees_per_acre, contingency_pct=contingency_pct,
        order_quantity=order_quantity, window_end=window_end, enrollment=enrollment,
        **world_kwargs,
    )
    ctx = drive_to_planted(
        ctx, plant_date=plant_date, crew_capacity=crew_capacity,
        assignment_days=assignment_days, extra_assignments=extra_assignments,
    )
    set_clock(f"{surveyed_on}T00:00:00Z")
    survey = create_survey(ctx["contract"]["id"], surveyed_on, alive_count)
    ctx["survey"] = survey
    ctx["contract"] = get_success_data(
        api_client.get_planting_contract(ctx["contract"]["id"], CO)
    )
    return ctx


def setup_contract_with_fulfilled_replant(
    *,
    acres=40, trees_per_acre=430, contingency_pct=0.05,
    order_quantity=19000,
    first_alive=11000, first_surveyed_on="2028-02-15",
    replant_herbicide_date="2028-05-20", prep_clock="2028-06-01T00:00:00Z",
    replant_date="2028-06-10",
) -> dict:
    """
    Full first failure + completed replant cycle + obligation fulfilled:
    world planted at required_seedlings -> failing survey (OPEN obligation)
    -> schedule-replant -> site prep recorded/verified -> mark-ready ->
    new confirmed crew -> start-planting on replant_date -> complete-planting
    at the owed quantity -> fulfill-replant. Returns ctx with survey_1 and
    owed_1. Used to reach a contract whose obligation_count is 1.
    """
    ctx = setup_ready_world(
        acres=acres, trees_per_acre=trees_per_acre, contingency_pct=contingency_pct,
        order_quantity=order_quantity, window_end="2028-12-31",
        lot_quantity_grams=500, sown_grams=300, lifted_count=21000,
        plantable_count=20000, unit_capacity=25000,
    )
    ctx = drive_to_planted(
        ctx, plant_date="2027-04-01", crew_capacity=5000, assignment_days=4,
    )

    set_clock(f"{first_surveyed_on}T00:00:00Z")
    survey_1 = create_survey(ctx["contract"]["id"], first_surveyed_on, first_alive)
    owed_1 = survey_1["owed_quantity"]

    set_clock(prep_clock)
    survey_1 = get_success_data(
        api_client.schedule_replant(survey_1["id"], {"replant_date": replant_date}, CO)
    )
    record_site_prep(ctx["contract"]["id"], replant_herbicide_date)
    verify_site_prep(ctx["contract"]["id"])
    mark_ready(ctx["contract"]["id"])

    asg = create_assignment(
        ctx["crew"]["id"], ctx["contract"]["id"], replant_date,
        _date_add_days(replant_date, 2), owed_1,
    )
    confirm_assignment(asg["id"])

    set_clock(f"{replant_date}T00:00:00Z")
    start_planting(ctx["contract"]["id"])
    contract = complete_planting(ctx["contract"]["id"], owed_1)

    survey_1 = get_success_data(api_client.fulfill_replant(survey_1["id"], CO))

    ctx["survey_1"] = survey_1
    ctx["owed_1"] = owed_1
    ctx["contract"] = contract
    return ctx
