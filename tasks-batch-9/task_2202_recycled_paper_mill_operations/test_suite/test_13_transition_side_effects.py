"""Transitions that must write more than their own row: the cleaning ledger row, the
cancel sweep that charges no strike, the four writes a run start performs, and the
inclusive boundary that carries an order straight to fully allocated.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers,
    declare_tl_140, declare_standard_grades, publish_quote, register_customer,
    register_machine, register_permit, register_supplier, create_confirmed_po,
    record_receipt, setup_available_lot, setup_approved_batch, queue_batch,
    schedule_run, start_run, complete_run, wind_roll_set, wrap_roll_set,
    submit_order, schedule_order, solids_rows, solids_summary, machine_version,
    order_version, furnish_line, sublot, reel_reading,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]

TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
GULF_COAST = {"name": "Gulf Coast Box Co", "allocation_priority_tier": "P1",
              "max_roll_diameter_mm": 1400, "max_roll_width_mm": 2400,
              "wrap_spec": "KRAFT_ONLY"}
# Endpoint reels perfect, a heavy middle reel 0.71% off basis weight: the two indexes
# are computed from different populations and land on different numbers.
THREE_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
               reel_reading(2, 20.000, 141.0, 7.50, 2.50),
               reel_reading(3, 5.000, 140.0, 7.50, 2.50)]


def _screened_batch_of_twenty_tons():
    declare_tl_140()
    bundle = setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])
    get_success_data(api_client.start_pulp_batch(batch["id"], OPERATOR))
    return get_success_data(api_client.screen_pulp_batch(batch["id"], OPERATOR))


def _eighteen_ton_batch_run_with_a_sequenced_order():
    """Permit, PM1, an APPROVED 18.000-ton batch, a SCHEDULED run, an order on it."""
    register_permit()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(tons_charged=20.000, measured_reject_tons=2.000)
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=15.000)
    customer = register_customer(**GULF_COAST)
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2200,
                         roll_diameter_mm=1200, wrap_spec="KRAFT_ONLY")
    order = schedule_order(order["id"], run["id"])
    return machine, bundle["batch"], run, order


def test_cleaning_stores_the_weight_and_appends_the_pulp_reject_row():
    """PRD §3.3: "Cleaning stores the value and appends one row to the solids ledger with
    `source_kind` of `PULP_REJECT`, `source_ref_id` pointing at this batch,
    `dry_solids_tons` equal to `measured_reject_tons`, and `disposition` of `PENDING`."
    PRD §2.9: "The invariant is that `net_solids_tons` equals the sum of
    `manifested_dry_solids_tons` and `unmanifested_dry_solids_tons` rounded to 3 decimal
    places, which holds because every repulped row is matched by exactly one reversal row
    of equal tonnage."

    Design: Corner/state_machines/clean_transition_appends_pulp_reject_row_into_solids_ledger
    """
    batch = _screened_batch_of_twenty_tons()

    cleaned = validate_success(api_client.clean_pulp_batch(
        batch["id"], {"measured_reject_tons": 2.000}, OPERATOR))
    assert cleaned["status"] == "CLEANED"
    assert cleaned["measured_reject_tons"] == pytest.approx(2.000, abs=1e-6)

    rows = solids_rows(source_ref_id=batch["id"])
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "PULP_REJECT"
    assert rows[0]["dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert rows[0]["disposition"] == "PENDING"
    assert rows[0]["manifest_id"] is None
    assert rows[0]["reversal_of_id"] is None

    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["repulped_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)


def test_the_cancel_sweep_rejects_the_open_truck_without_charging_a_strike():
    """PRD §3.1: "Cancellation also sweeps the order's open receipts: every fiber receipt
    of this order still sitting in `SAMPLED` is flipped to `REJECTED` with its
    `accepted_grade_code` cleared to null."
    PRD §3.1: "Because this is an administrative rejection rather than a quality
    judgement, those sweep-rejected receipts carry no `dispositioned_by_user_id` and **no
    contamination strike is charged to the supplier** for them."
    PRD §3.1: "It is permitted only while `received_net_tons` reads exactly 0.00 — any
    receipt already accepted or downgraded against the order blocks it, and the attempt is
    rejected with `ERR_TONNAGE_ALREADY_BOOKED` (HTTP 409)."

    Design: Corner/state_machines/purchase_order_cancel_rejects_sampled_receipts_without_charging_a_strike
    """
    declare_standard_grades()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             index_basis="CURRENT_MONTH", priced_for_month="2026-08")
    receipt = record_receipt(po["id"], TWENTY_TWO_TON_SUBLOT)
    assert receipt["status"] == "SAMPLED"

    cancelled = validate_success(api_client.cancel_purchase_order(po["id"], BUYER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["received_net_tons"] == pytest.approx(0.00, abs=1e-6)

    swept = get_success_data(api_client.get_receipt(receipt["id"], SAMPLER))
    assert swept["status"] == "REJECTED"
    assert swept["accepted_grade_code"] is None
    assert swept["dispositioned_by_user_id"] is None

    party = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert party["contamination_strike_count"] == 0
    assert party["qualification_status"] == "QUALIFIED"
    assert party["probation_entered_at"] is None

    lots = api_client.list_inventory_lots(PLANNER, {"receipt_id": receipt["id"]})
    assert lots.json()["meta"]["total_count"] == 0


def test_starting_the_run_draws_the_pulp_and_pulls_its_order_into_production():
    """PRD §3.5: "Starting a run has four side effects. The run's `pulp_draw_tons` is
    added into the batch's `consumed_tons` and the batch's `available_tons` is recomputed.
    The acting operator's identifier is stored as `started_by_user_id`. Every customer
    order whose `scheduled_run_id` is this run advances `SCHEDULED → IN_PRODUCTION`, each
    such order's `version` incrementing. And the parent machine's `version` is bumped by
    one."

    Design: Corner/state_machines/run_start_moves_its_sequenced_order_to_in_production
    """
    machine, batch, run, order = _eighteen_ton_batch_run_with_a_sequenced_order()
    assert order["status"] == "SCHEDULED"
    version_before = machine_version(machine["id"])

    started = validate_success(api_client.start_run(machine["id"], run["id"], OPERATOR))
    assert started["run_status"] == "RUNNING"
    assert started["quality_status"] == "PENDING"
    assert started["started_by_user_id"] == OPERATOR["X-User-ID"]

    moved = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert moved["status"] == "IN_PRODUCTION"
    assert moved["scheduled_run_id"] == run["id"]
    assert moved["version"] > order["version"]

    drawn = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(15.000, abs=1e-6)
    assert drawn["available_tons"] == pytest.approx(3.000, abs=1e-6)

    assert machine_version(machine["id"]) == version_before + 1


def test_a_roll_set_that_exactly_covers_the_order_carries_it_straight_to_allocated():
    """PRD §3.6: "Each recomputation moves the order along: from `IN_PRODUCTION`, an
    allocation that leaves `allocated_tons` below `ordered_tons` advances the order
    `IN_PRODUCTION → PARTIALLY_ALLOCATED`, while an allocation that already covers
    `ordered_tons` advances it `IN_PRODUCTION → ALLOCATED` directly; from
    `PARTIALLY_ALLOCATED`, reaching `ordered_tons` or more advances `PARTIALLY_ALLOCATED →
    ALLOCATED` and sets `shortfall_tons` to 0.000, with the boundary inclusive so
    `allocated_tons` exactly equal to `ordered_tons` reaches `ALLOCATED`."
    PRD §3.5: "The **provisional quality index**, stored as `provisional_quality_index`,
    is the plain arithmetic mean of exactly two reel scores — the reel with the smallest
    `reel_no` and the reel with the largest `reel_no` — rounded half up to two decimal
    places, regardless of how many reels the run actually produced."
    PRD §3.5: "The **certified quality index** is the tonnage-weighted mean of **every**
    reel: the sum over all reel readings of `reel_tons` multiplied by that reel's
    already-rounded score, divided by the sum of all `reel_tons`, the quotient rounded
    half up to two decimal places."

    Design: Corner/state_machines/allocation_at_exact_ordered_tonnage_bubbles_order_to_allocated
    """
    machine, _, run, order = _eighteen_ton_batch_run_with_a_sequenced_order()
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1200,
                             roll_count=3, net_tons=6.000)
    complete_run(machine["id"], run["id"], THREE_REELS)
    wrap_roll_set(roll_set["id"], "KRAFT_ONLY")
    certified = validate_success(api_client.certify_run(machine["id"], run["id"],
                                                        CERTIFIER))
    assert certified["quality_status"] == "CERTIFIED"
    assert certified["provisional_quality_index"] == pytest.approx(100.00, abs=1e-6)
    assert certified["certified_quality_index"] == pytest.approx(98.09, abs=1e-6)
    assert certified["off_spec_reel_count"] == 0

    allocated = validate_success(api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": order_version(order["id"])},
        PLANNER))
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_order_id"] == order["id"]

    filled = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert filled["status"] == "ALLOCATED"
    assert filled["allocated_tons"] == pytest.approx(6.000, abs=1e-6)
    assert filled["shortfall_tons"] == pytest.approx(0.000, abs=1e-6)
    assert filled["shipped_tons"] == pytest.approx(0.000, abs=1e-6)
