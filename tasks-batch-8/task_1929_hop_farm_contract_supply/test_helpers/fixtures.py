"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use get_success_data() so failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_field_payload, create_kiln_payload, create_planting_plan_payload,
    create_contract_payload, create_harvest_lot_payload, create_load_kiln_payload,
    create_redry_payload, create_finish_drying_payload, create_lab_test_payload,
    create_pellet_lot_payload, create_allocation_run_payload, create_spot_sale_payload,
    create_sample_payload, create_insurance_claim_payload, set_clock_payload,
)
from .constants import WINDOW_DAY1_AM, WINDOW_DAY1_PM, WINDOW_DAY2_AM, WINDOW_DAY2_PM
from .test_users import (
    TEST_USERS, make_farm_manager_headers, make_insurance_adjuster_headers,
)

FM = TEST_USERS["farm_manager_headers"]
LT = TEST_USERS["lab_technician_headers"]
CM = TEST_USERS["contract_manager_headers"]
IA = TEST_USERS["insurance_adjuster_headers"]


# ─── Tier 1: single-resource creation ────────────────────────────────────────

def create_field(name="F1", acreage=100):
    """Create a field. Returns the field."""
    return get_success_data(api_client.create_field(
        create_field_payload(name=name, acreage=acreage), FM))


def create_kiln(name="K1"):
    """Create a kiln. Returns the kiln."""
    return get_success_data(api_client.create_kiln(create_kiln_payload(name=name), FM))


def create_plan(field_id, crop_year=2026, variety="CASCADE", planned_acreage=40):
    """Create a planting plan (opens DRAFT). Returns the plan."""
    return get_success_data(api_client.create_planting_plan(
        create_planting_plan_payload(
            field_id, crop_year=crop_year, variety=variety,
            planned_acreage=planned_acreage),
        FM))


def create_growing_plan(field_id, crop_year=2026, variety="CASCADE", planned_acreage=40):
    """Plan walked DRAFT -> GROWING. Returns the plan."""
    plan = create_plan(field_id, crop_year, variety, planned_acreage)
    return get_success_data(api_client.approve_plan(plan["id"], FM))


def create_harvesting_plan(field_id, crop_year=2026, variety="CASCADE", planned_acreage=40):
    """Plan walked DRAFT -> GROWING -> HARVESTING. Returns the plan."""
    plan = create_growing_plan(field_id, crop_year, variety, planned_acreage)
    return get_success_data(api_client.open_harvest(plan["id"], FM))


def create_contract(**overrides):
    """Create a supply contract (opens DRAFT). Returns the contract."""
    return get_success_data(api_client.create_contract(
        create_contract_payload(**overrides), CM))


def create_active_contract(**overrides):
    """Contract walked DRAFT -> ACTIVE. Returns the contract."""
    contract = create_contract(**overrides)
    return get_success_data(api_client.activate_contract(contract["id"], CM))


def set_clock(to_iso8601):
    """Advance the server-held logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), FM))


# ─── Tier 2: farm hierarchy ──────────────────────────────────────────────────

def setup_field_with_plan(crop_year=2026, variety="CASCADE", planned_acreage=40,
                          field_acreage=100, plan_state="DRAFT",
                          field_name="F1"):
    """Field plus a plan walked to plan_state (DRAFT | GROWING | HARVESTING).
    Returns (field, plan)."""
    field = create_field(name=field_name, acreage=field_acreage)
    if plan_state == "GROWING":
        plan = create_growing_plan(field["id"], crop_year, variety, planned_acreage)
    elif plan_state == "HARVESTING":
        plan = create_harvesting_plan(field["id"], crop_year, variety, planned_acreage)
    else:
        plan = create_plan(field["id"], crop_year, variety, planned_acreage)
    return field, plan


def setup_harvesting_plan_with_kiln(crop_year=2026, variety="CASCADE",
                                    planned_acreage=40, field_name="F1",
                                    kiln_name="K1"):
    """Field + HARVESTING plan + kiln. Returns dict(field, plan, kiln)."""
    field, plan = setup_field_with_plan(
        crop_year=crop_year, variety=variety, planned_acreage=planned_acreage,
        plan_state="HARVESTING", field_name=field_name)
    kiln = create_kiln(name=kiln_name)
    return {"field": field, "plan": plan, "kiln": kiln}


# ─── Tier 3: kiln pipeline lifecycle ─────────────────────────────────────────

def create_harvested_lot(plan_id, wet_lbs):
    """Harvest lot against a HARVESTING plan (opens HARVESTED). Returns the lot."""
    return get_success_data(api_client.create_harvest_lot(
        create_harvest_lot_payload(plan_id, wet_lbs), FM))


def create_in_kiln_lot(plan_id, kiln_id, wet_lbs,
                       window_start=WINDOW_DAY1_AM[0], window_end=WINDOW_DAY1_AM[1]):
    """Harvest lot loaded into a kiln (IN_KILN). Returns the lot."""
    lot = create_harvested_lot(plan_id, wet_lbs)
    return get_success_data(api_client.load_kiln(
        lot["id"], create_load_kiln_payload(kiln_id, window_start, window_end), FM))


def create_moisture_check_lot(plan_id, kiln_id, wet_lbs, dried_lbs,
                              window_start=WINDOW_DAY1_AM[0],
                              window_end=WINDOW_DAY1_AM[1]):
    """Lot finished drying (MOISTURE_CHECK) with moisture_pct computed.
    Returns the lot."""
    lot = create_in_kiln_lot(plan_id, kiln_id, wet_lbs, window_start, window_end)
    return get_success_data(api_client.finish_drying(
        lot["id"], create_finish_drying_payload(dried_lbs), FM))


def create_dried_lot(plan_id, kiln_id, wet_lbs, dried_lbs,
                     window_start=WINDOW_DAY1_AM[0], window_end=WINDOW_DAY1_AM[1],
                     provisional_alpha=None, final_alpha=None):
    """Lot walked through the kiln to DRIED, optionally with alpha tests posted.
    A FINAL requires a prior PROVISIONAL (PRD §3.3), so passing final_alpha
    defaults the provisional to the same value when none is given.
    Returns the lot."""
    if final_alpha is not None and provisional_alpha is None:
        provisional_alpha = final_alpha
    lot = create_moisture_check_lot(
        plan_id, kiln_id, wet_lbs, dried_lbs, window_start, window_end)
    dried = get_success_data(api_client.release_lot(lot["id"], FM))
    if provisional_alpha is not None:
        get_success_data(api_client.create_lab_test(
            create_lab_test_payload(dried["id"], "PROVISIONAL", provisional_alpha), LT))
    if final_alpha is not None:
        get_success_data(api_client.create_lab_test(
            create_lab_test_payload(dried["id"], "FINAL", final_alpha), LT))
    return get_success_data(api_client.get_harvest_lot(dried["id"], FM))


# ─── Tier 4: pelletizing, contracts, allocations ─────────────────────────────

def create_pellet_lot(source_lot_ids, storage_room="R1"):
    """Pelletize DRIED harvest lots into a pellet lot. Returns the pellet lot."""
    return get_success_data(api_client.create_pellet_lot(
        create_pellet_lot_payload(source_lot_ids, storage_room), FM))


def run_allocation(crop_year=2026, variety="CASCADE"):
    """Trigger an allocation run. Returns the run response data."""
    return get_success_data(api_client.create_allocation_run(
        create_allocation_run_payload(crop_year, variety), CM))


def find_allocation(contract_id=None, crop_year=None, status=None):
    """Return the single allocation row matching the given list filters."""
    params = {}
    if contract_id is not None:
        params["contract_id"] = contract_id
    if crop_year is not None:
        params["crop_year"] = crop_year
    if status is not None:
        params["status"] = status
    res = api_client.list_allocations(CM, params=params)
    data, _meta = validate_paginated(res)
    assert len(data) >= 1, f"expected at least one allocation for filters {params}"
    return data[0]


def confirm_allocation(allocation_id):
    return get_success_data(api_client.confirm_allocation(allocation_id, CM))


def deliver_allocation(allocation_id):
    return get_success_data(api_client.deliver_allocation(allocation_id, CM))


def settle_allocation(allocation_id):
    return get_success_data(api_client.settle_allocation(allocation_id, CM))


def setup_pellet_lot_single_source(wet_lbs=3000, dried_lbs=800,
                                   provisional_alpha=None, final_alpha=None,
                                   crop_year=2026, variety="CASCADE",
                                   storage_room="R1"):
    """Field + HARVESTING plan + kiln + one DRIED lot (tests per arguments)
    pelletized into a single-source pellet lot. Returns dict with the farm
    context and the pellet lot."""
    ctx = setup_harvesting_plan_with_kiln(crop_year=crop_year, variety=variety)
    lot = create_dried_lot(
        ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs, dried_lbs,
        window_start=WINDOW_DAY1_AM[0], window_end=WINDOW_DAY1_AM[1],
        provisional_alpha=provisional_alpha, final_alpha=final_alpha)
    pellet = create_pellet_lot([lot["id"]], storage_room=storage_room)
    ctx.update({"lot": lot, "pellet": pellet})
    return ctx


def setup_delivered_allocation(sources, contract_overrides=None, crop_year=2026,
                               variety="CASCADE"):
    """Full pipeline: farm context -> DRIED lots (with tests) -> pellet lot ->
    ACTIVE contract -> allocation run -> confirm -> deliver.

    sources: list of dicts with keys wet_lbs, dried_lbs, and optional
        provisional_alpha / final_alpha / window (defaults spread across the
        standard non-conflicting kiln windows).
    Returns dict(field, plan, kiln, lots, pellet, contract, allocation).
    """
    ctx = setup_harvesting_plan_with_kiln(crop_year=crop_year, variety=variety)
    windows = [WINDOW_DAY1_AM, WINDOW_DAY1_PM, WINDOW_DAY2_AM, WINDOW_DAY2_PM]
    lots = []
    for i, src in enumerate(sources):
        window = src.get("window", windows[i % len(windows)])
        lots.append(create_dried_lot(
            ctx["plan"]["id"], ctx["kiln"]["id"], src["wet_lbs"], src["dried_lbs"],
            window_start=window[0], window_end=window[1],
            provisional_alpha=src.get("provisional_alpha"),
            final_alpha=src.get("final_alpha")))
    pellet = create_pellet_lot([lot["id"] for lot in lots])
    contract = create_active_contract(
        variety=variety, **(contract_overrides or {}))
    run_allocation(crop_year=crop_year, variety=variety)
    allocation = find_allocation(contract_id=contract["id"], crop_year=crop_year)
    confirm_allocation(allocation["id"])
    delivered = deliver_allocation(allocation["id"])
    ctx.update({
        "lots": lots, "pellet": pellet, "contract": contract,
        "allocation": delivered,
    })
    return ctx


def setup_settled_allocation(sources, contract_overrides=None, crop_year=2026,
                             variety="CASCADE"):
    """setup_delivered_allocation extended through settle. Returns the context
    with the settled allocation."""
    ctx = setup_delivered_allocation(
        sources, contract_overrides=contract_overrides,
        crop_year=crop_year, variety=variety)
    ctx["allocation"] = settle_allocation(ctx["allocation"]["id"])
    return ctx


def setup_two_consecutive_shortfall_years(volume_lbs=2000, dried_per_year=1000,
                                          alpha=12.0, crop_years=(2026, 2027),
                                          final_crop_year=2028):
    """Contract (default CASCADE 2026-2028) with two consecutive shortfall years
    delivered and a leftover PROJECTED allocation in the final year.

    Year one and two each get a single-source pellet lot whose quantity is under
    the contracted volume; both allocations are confirmed and delivered. The
    final year's run creates a PROJECTED allocation against zero inventory.
    Returns dict(c_id, a_first, a_second, a_final, pellets).
    """
    ctx = setup_harvesting_plan_with_kiln()
    contract = create_active_contract(annual_volume_lbs=volume_lbs)

    pellets = []
    allocation_ids = []
    windows = [WINDOW_DAY1_AM, WINDOW_DAY2_AM]
    for idx, year in enumerate(crop_years):
        lot = create_dried_lot(
            ctx["plan"]["id"], ctx["kiln"]["id"], 3750, dried_per_year,
            window_start=windows[idx][0], window_end=windows[idx][1],
            final_alpha=alpha)
        pellets.append(create_pellet_lot([lot["id"]], storage_room=f"R{idx + 1}"))
        run_allocation(crop_year=year, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=year)
        confirm_allocation(allocation["id"])
        deliver_allocation(allocation["id"])
        allocation_ids.append(allocation["id"])

    run_allocation(crop_year=final_crop_year, variety="CASCADE")
    final_allocation = find_allocation(
        contract_id=contract["id"], crop_year=final_crop_year)
    return {
        "farm": ctx,
        "c_id": contract["id"],
        "a_first": allocation_ids[0],
        "a_second": allocation_ids[1],
        "a_final": final_allocation["id"],
        "pellets": pellets,
    }


# ─── Tier 5: samples, spot sales, insurance claims ───────────────────────────

def create_sample(pellet_lot_id, brewery_name="CraftBrew"):
    return get_success_data(api_client.create_sample(
        create_sample_payload(pellet_lot_id, brewery_name), CM))


def decide_sample(sample_id, outcome):
    return get_success_data(api_client.decide_sample(sample_id, {"outcome": outcome}, CM))


def create_spot_sale(pellet_lot_id, **overrides):
    return get_success_data(api_client.create_spot_sale(
        create_spot_sale_payload(pellet_lot_id, **overrides), CM))


def file_claim(plan_id, filer_user_id="grower-1", price_election_cents_per_lb=300,
               coverage_pct=None):
    """File an insurance claim as the given FarmManager user id. Returns the
    claim."""
    payload = create_insurance_claim_payload(
        plan_id, price_election_cents_per_lb=price_election_cents_per_lb)
    if coverage_pct is not None:
        payload["coverage_pct"] = coverage_pct
    return get_success_data(api_client.create_insurance_claim(
        payload, make_farm_manager_headers(filer_user_id)))


def file_claim_on_growing_plan(filer_user_id="grower-1", price_election_cents_per_lb=300,
                               coverage_pct=None, variety="CASCADE",
                               planned_acreage=40):
    """Field + GROWING plan + claim filed by filer_user_id.
    Returns dict(field, plan, claim)."""
    field, plan = setup_field_with_plan(
        variety=variety, planned_acreage=planned_acreage, plan_state="GROWING")
    claim = file_claim(
        plan["id"], filer_user_id=filer_user_id,
        price_election_cents_per_lb=price_election_cents_per_lb,
        coverage_pct=coverage_pct)
    return {"field": field, "plan": plan, "claim": claim}


def drive_claim_to_approved(claim_id, adjuster_user_id="adjuster-9"):
    """FILED -> UNDER_REVIEW -> APPROVED by a different adjuster id.
    Returns the approved claim."""
    headers = make_insurance_adjuster_headers(adjuster_user_id)
    get_success_data(api_client.begin_review_claim(claim_id, headers))
    return get_success_data(api_client.decide_claim(claim_id, {"outcome": "APPROVED"}, headers))
