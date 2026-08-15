"""Composite setup helpers.

Each helper builds a multi-step scenario against the API using only endpoints
the PRD declares, so test bodies stay focused on assertions. All helpers use
the lenient get_success_data() validator: a failed setup step raises a clear
"Setup step failed" error rather than a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_batch_payload,
    create_contract_payload,
    create_cook_run_payload,
    create_odor_event_payload,
    create_order_payload,
    create_permit_payload,
    create_plant_payload,
    create_price_index_entry_payload,
    create_route_payload,
    create_stop_payload,
    create_supplier_payload,
    create_vehicle_payload,
    create_wash_ticket_payload,
)
from .test_users import TEST_USERS, make_headers

PM = TEST_USERS["plant_manager_headers"]
PM2 = TEST_USERS["plant_manager_2_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
CO3 = TEST_USERS["compliance_officer_3_headers"]
REG = TEST_USERS["regulator_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
PROC2 = TEST_USERS["procurement_manager_2_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
SH = TEST_USERS["scalehouse_operator_headers"]
SH2 = TEST_USERS["scalehouse_operator_2_headers"]
PS = TEST_USERS["production_supervisor_headers"]
QL = TEST_USERS["quality_lab_tech_headers"]
SM = TEST_USERS["sales_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FA2 = TEST_USERS["finance_analyst_2_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators
# ---------------------------------------------------------------------------
def create_plant(cooker_capacity=2, standard_cost_cents_per_lb=38, **overrides):
    """Create a plant (auto-opens period-1 OPEN settlement). Returns plant."""
    payload = create_plant_payload(
        cooker_capacity=cooker_capacity,
        standard_cost_cents_per_lb=standard_cost_cents_per_lb,
        **overrides,
    )
    return get_success_data(api_client.create_plant(payload, PM))


def create_supplier(plant_id, headers=None, **overrides):
    """Onboard a supplier (starts ACTIVE). Returns supplier."""
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(plant_id, **overrides),
                                   headers or PROC)
    )


def create_draft_agreement(plant_id, supplier_id, creator_headers=None, **overrides):
    """Create a supplier agreement (DRAFT); created_by = caller. Returns agreement."""
    return get_success_data(
        api_client.create_supplier_agreement(
            create_agreement_payload(supplier_id, plant_id, **overrides),
            creator_headers or PROC,
        )
    )


def activate_agreement(agreement, approver_headers=None):
    """Submit + approve a DRAFT agreement with an approver != creator."""
    api = api_client
    get_success_data(api.submit_agreement(agreement["id"], PROC))
    return get_success_data(api.approve_agreement(agreement["id"], approver_headers or PM))


def create_active_agreement(plant_id, supplier_id, **overrides):
    """Create -> submit -> approve. Returns the ACTIVE agreement."""
    draft = create_draft_agreement(plant_id, supplier_id, **overrides)
    return activate_agreement(draft)


def setup_plant_with_agreement(**overrides):
    """Plant + supplier + ACTIVE agreement. Returns (plant, supplier, agreement)."""
    plant = create_plant()
    supplier = create_supplier(plant["id"])
    agreement = create_active_agreement(plant["id"], supplier["id"], **overrides)
    return plant, supplier, agreement


def create_vehicle(plant_id, headers=None, **overrides):
    """Register a vehicle (starts SANITIZED). Returns vehicle."""
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(plant_id, **overrides),
                                  headers or RD)
    )


def create_route(plant_id, vehicle_id, headers=None, **overrides):
    """Create a collection route (PLANNED). Returns route."""
    return get_success_data(
        api_client.create_collection_route(
            create_route_payload(plant_id, vehicle_id, **overrides), headers or RD
        )
    )


def read_route_version(route_id):
    """Current OCC version of a route (fresh read)."""
    return get_success_data(api_client.get_collection_route(route_id, ANY))["version"]


def add_stop(route_id, supplier_id, agreement_id, plant_id, **overrides):
    """Add a stop, reading the route's current version first. Returns stop."""
    version = overrides.pop("expected_route_version", None) or read_route_version(route_id)
    payload = create_stop_payload(
        route_id, supplier_id, agreement_id, plant_id, version, **overrides
    )
    return get_success_data(api_client.create_route_stop(payload, RD))


def create_walkin_batch(plant_id, supplier_id, agreement_id, headers=None, **overrides):
    """Walk-in receiving (RECEIVED, PENDING). Returns batch."""
    return get_success_data(
        api_client.create_inbound_batch(
            create_batch_payload(plant_id, supplier_id, agreement_id, **overrides),
            headers or SH,
        )
    )


def create_accepted_batch(plant_id, supplier_id, agreement_id, screener_headers=None, **overrides):
    """Walk-in batch screened PASS -> ACCEPTED. Returns batch."""
    batch = create_walkin_batch(plant_id, supplier_id, agreement_id, **overrides)
    return get_success_data(
        api_client.screen_batch(batch["id"], {"screening_result": "PASS"},
                                screener_headers or SH)
    )


def create_staged_cook_run(plant_id, planned_inputs, **overrides):
    """Stage a cook run (STAGED, theoretical yields computed). Returns run."""
    return get_success_data(
        api_client.create_cook_run(
            create_cook_run_payload(plant_id, planned_inputs, **overrides), PS
        )
    )


def advance_run_to_pressing(run_id):
    """STAGED -> COOKING -> SETTLING -> PRESSING. Returns the PRESSING run."""
    get_success_data(api_client.start_cook_run(run_id, PS))
    get_success_data(api_client.advance_cook_run(run_id, PS))
    return get_success_data(api_client.advance_cook_run(run_id, PS))


def complete_cook_run(run_id, actual_fat_output_lbs, actual_meal_output_lbs, **extra):
    """PRESSING -> COMPLETED with measured outputs. Returns run."""
    payload = {
        "actual_fat_output_lbs": actual_fat_output_lbs,
        "actual_meal_output_lbs": actual_meal_output_lbs,
    }
    payload.update(extra)
    return get_success_data(api_client.complete_cook_run(run_id, payload, PS))


def setup_completed_cook_run(
    species="BOVINE",
    batch_weight_lbs=5000,
    run_weight_lbs=None,
    actual_fat_output_lbs=800,
    actual_meal_output_lbs=1200,
    cook_start="2026-08-04T06:00:00Z",
    cook_end="2026-08-04T09:00:00Z",
    cooker_capacity=2,
    standard_cost_cents_per_lb=38,
):
    """Full chain: plant -> supplier -> ACTIVE agreement -> ACCEPTED batch ->
    cook run -> PRESSING -> COMPLETED. Returns dict of the whole scenario."""
    plant = create_plant(
        cooker_capacity=cooker_capacity,
        standard_cost_cents_per_lb=standard_cost_cents_per_lb,
    )
    supplier = create_supplier(plant["id"])
    agreement = create_active_agreement(
        plant["id"], supplier["id"], species_scope=[species]
    )
    batch = create_accepted_batch(
        plant["id"], supplier["id"], agreement["id"],
        species=species, weight_lbs=batch_weight_lbs,
    )
    run = create_staged_cook_run(
        plant["id"],
        [{"batch_id": batch["id"], "weight_lbs": run_weight_lbs or batch_weight_lbs}],
        cook_start=cook_start,
        cook_end=cook_end,
    )
    advance_run_to_pressing(run["id"])
    run = complete_cook_run(run["id"], actual_fat_output_lbs, actual_meal_output_lbs)
    return {
        "plant": plant,
        "supplier": supplier,
        "agreement": agreement,
        "batch": batch,
        "run": run,
    }


def get_lot_for_run(run_id, product_type):
    """Fetch the product lot of the given type created by a completed run."""
    lots, _meta = _list(
        api_client.list_product_lots(
            ANY, params={"cook_run_id": run_id, "product_type": product_type}
        )
    )
    assert len(lots) >= 1, f"expected a {product_type} lot for run {run_id}"
    return lots[0]


def grade_lot(lot_id, lab_moisture_pct, lab_ffa_pct, lab_protein_pct, headers=None):
    """Record lab values; server computes the grade. Returns lot."""
    payload = {
        "lab_moisture_pct": lab_moisture_pct,
        "lab_ffa_pct": lab_ffa_pct,
        "lab_protein_pct": lab_protein_pct,
    }
    return get_success_data(api_client.grade_lot(lot_id, payload, headers or QL))


def release_lot(lot_id, headers=None):
    """GRADED -> RELEASED (releaser must differ from grader). Returns lot."""
    return get_success_data(api_client.release_lot(lot_id, headers or PS))


def setup_released_tallow_lot(
    lab_moisture_pct=0.2,
    lab_ffa_pct=1.5,
    lab_protein_pct=0,
    standard_cost_cents_per_lb=38,
    **run_kwargs,
):
    """Completed BOVINE run -> TALLOW lot graded (default PREMIUM) and released.
    Returns dict with plant/supplier/agreement/batch/run/lot."""
    scenario = setup_completed_cook_run(
        standard_cost_cents_per_lb=standard_cost_cents_per_lb, **run_kwargs
    )
    lot = get_lot_for_run(scenario["run"]["id"], "TALLOW")
    lot = grade_lot(lot["id"], lab_moisture_pct, lab_ffa_pct, lab_protein_pct)
    lot = release_lot(lot["id"])
    scenario["lot"] = lot
    return scenario


# ---------------------------------------------------------------------------
# Contracts / orders
# ---------------------------------------------------------------------------
def create_draft_contract(plant_id, creator_headers=None, **overrides):
    """Create a customer contract (DRAFT); created_by = caller. Returns contract.

    An override value of None REMOVES the field from the payload (used to build
    INDEX_LINKED contracts, which must omit the fixed base price entirely).
    """
    payload = create_contract_payload(plant_id, **overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return get_success_data(
        api_client.create_customer_contract(payload, creator_headers or SM)
    )


def create_active_contract(plant_id, **overrides):
    """Create -> submit -> approve. Returns the ACTIVE contract."""
    draft = create_draft_contract(plant_id, **overrides)
    get_success_data(api_client.submit_contract(draft["id"], SM))
    return get_success_data(api_client.approve_contract(draft["id"], PM))


def read_contract_version(contract_id):
    """Current OCC version of a contract (fresh read)."""
    return get_success_data(api_client.get_customer_contract(contract_id, ANY))["version"]


def create_order(contract_id, plant_id, headers=None, **overrides):
    """Create a sales order (DRAFT), reading the contract version first."""
    version = (
        overrides.pop("expected_contract_version", None)
        or read_contract_version(contract_id)
    )
    payload = create_order_payload(contract_id, plant_id, version, **overrides)
    return get_success_data(api_client.create_sales_order(payload, headers or SM))


def create_priced_order(contract, quantity_lbs=100, requested_ship_date="2026-08-20",
                        expected_grade="STANDARD", headers=None):
    """Create + price an order. Returns the PRICED order."""
    order = create_order(
        contract["id"], contract["plant_id"],
        quantity_lbs=quantity_lbs, requested_ship_date=requested_ship_date,
    )
    return get_success_data(
        api_client.price_order(order["id"], {"expected_grade": expected_grade},
                               headers or SM)
    )


def publish_index_entry(plant_id, headers=None, **overrides):
    """Publish a price index entry (append-only). Returns entry."""
    return get_success_data(
        api_client.create_price_index_entry(
            create_price_index_entry_payload(plant_id, **overrides), headers or FA
        )
    )


# ---------------------------------------------------------------------------
# Routes in motion
# ---------------------------------------------------------------------------
def setup_planned_route_with_stop(service_date="2026-08-10", **stop_overrides):
    """Plant + supplier + ACTIVE agreement + SANITIZED RAW vehicle +
    PLANNED route with one SCHEDULED stop.
    Returns dict(plant, supplier, agreement, vehicle, route, stop)."""
    plant, supplier, agreement = setup_plant_with_agreement()
    vehicle = create_vehicle(plant["id"])
    route = create_route(plant["id"], vehicle["id"], service_date=service_date)
    stop = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                    **stop_overrides)
    return {
        "plant": plant,
        "supplier": supplier,
        "agreement": agreement,
        "vehicle": vehicle,
        "route": route,
        "stop": stop,
    }


def setup_dispatched_route_with_arrived_stop(**kwargs):
    """Planned route dispatched; its stop ARRIVED (route -> IN_PROGRESS)."""
    ctx = setup_planned_route_with_stop(**kwargs)
    get_success_data(api_client.dispatch_route(ctx["route"]["id"], RD))
    stop = get_success_data(api_client.arrive_stop(ctx["stop"]["id"], RD))
    ctx["stop"] = stop
    return ctx


def setup_collected_stop(actual_weight_lbs=5000, actual_distance_miles=20,
                         temperature_f=62.0, **kwargs):
    """Stop collected: COLLECTED, final fee settled, batch created, accruals posted."""
    ctx = setup_dispatched_route_with_arrived_stop(**kwargs)
    stop = get_success_data(
        api_client.collect_stop(
            ctx["stop"]["id"],
            {
                "actual_weight_lbs": actual_weight_lbs,
                "actual_distance_miles": actual_distance_miles,
                "temperature_f": temperature_f,
            },
            RD,
        )
    )
    ctx["stop"] = stop
    ctx["batch"] = get_batch_for_stop(stop["id"])
    return ctx


def get_batch_for_stop(stop_id):
    """Reverse-lookup the inbound batch created by a stop collection."""
    batches, _meta = _list(
        api_client.list_inbound_batches(ANY, params={"route_stop_id": stop_id})
    )
    assert len(batches) >= 1, f"expected an inbound batch for stop {stop_id}"
    return batches[0]


# ---------------------------------------------------------------------------
# Permits / odor
# ---------------------------------------------------------------------------
def create_active_permit(plant_id, **overrides):
    """Create -> submit -> issue. Returns the ACTIVE permit."""
    permit = get_success_data(
        api_client.create_permit(create_permit_payload(plant_id, **overrides), CO)
    )
    get_success_data(api_client.submit_permit(permit["id"], CO))
    return get_success_data(api_client.issue_permit(permit["id"], REG))


def create_odor_event(plant_id, reporter_headers=None, **overrides):
    """Log an odor complaint (REPORTED). Returns event."""
    return get_success_data(
        api_client.create_odor_event(
            create_odor_event_payload(plant_id, **overrides), reporter_headers or CO
        )
    )


def confirm_odor_event(event_id, confirmer_headers=None):
    """Confirm a REPORTED event (confirmer must differ from reporter)."""
    return get_success_data(
        api_client.confirm_odor_event(event_id, confirmer_headers or CO2)
    )


def confirm_severities(plant_id, severities, reporter_headers=None, confirmer_headers=None):
    """Report + confirm one odor event per severity, in order. Returns events."""
    events = []
    for i, severity in enumerate(severities):
        event = create_odor_event(
            plant_id,
            reporter_headers=reporter_headers,
            reported_at=f"2026-08-05T{9 + i:02d}:00:00Z",
            severity=severity,
        )
        events.append(confirm_odor_event(event["id"], confirmer_headers))
    return events


def drive_plant_to_restricted(plant_id):
    """Push posture to RESTRICTED via 3 confirmed HIGH events (score 1000 -> 550)."""
    confirm_severities(plant_id, ["HIGH", "HIGH", "HIGH"])
    plant = get_success_data(api_client.get_plant(plant_id, ANY))
    assert plant["posture"] == "RESTRICTED", (
        f"expected RESTRICTED at score 550, got {plant['posture']} "
        f"(score {plant['odor_score']})"
    )
    return plant


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------
def get_settlement(plant_id, period_index=1):
    """Fetch the settlement for (plant, period_index) via the list filter."""
    settlements, _meta = _list(
        api_client.list_period_settlements(
            ANY, params={"plant_id": plant_id, "period_index": period_index}
        )
    )
    assert len(settlements) >= 1, (
        f"expected a settlement for plant {plant_id} period {period_index}"
    )
    return settlements[0]


def close_settlement(plant_id, period_index=1, closer_headers=None):
    """Close the given period's settlement. Returns the CLOSED settlement."""
    settlement = get_settlement(plant_id, period_index)
    return get_success_data(
        api_client.close_settlement(settlement["id"], closer_headers or FA)
    )


def advance_period(plant_id, headers=None):
    """Advance the settlement calendar (current settlement must be CLOSED)."""
    return get_success_data(api_client.advance_period(plant_id, headers or FA))


def set_clock(to_iso8601, headers=None):
    """Advance the server's logical clock."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or PM)
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _list(response):
    """Validate a list response and return (data_list, meta)."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
