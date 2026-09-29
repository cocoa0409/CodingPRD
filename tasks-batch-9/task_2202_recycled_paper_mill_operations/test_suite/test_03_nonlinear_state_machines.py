"""Non-linear lifecycles: the run's two independent axes, the deink self-loop with
its pass ceiling, and the three-way weighbridge disposition fork.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, declare_standard_grades, publish_quote, register_supplier,
    create_confirmed_po, record_receipt, disposition, lots_of_receipt,
    setup_completed_run, setup_batch_at_deink_hold, run_deink_pass,
    record_brightness, solids_rows, reel_reading, sublot, _paginated,
    TEST_USERS, make_supplier_headers,
)

PLANNER = TEST_USERS["planner_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
OPERATOR = TEST_USERS["operator_headers"]
BUYER = TEST_USERS["buyer_headers"]

OFF_SPEC_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
                  reel_reading(2, 5.000, 155.0, 7.50, 2.50)]
REWORKED_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
                  reel_reading(2, 5.000, 142.0, 7.50, 2.50)]

MACHINE = {"wire_width_mm": 4200, "max_tons_per_hour": 20.00,
           "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}
PERMIT = {"permit_number": "MILL-NPDES-01", "bod_limit_kg_per_day": 100.00,
          "tss_limit_kg_per_day": 200.00, "flow_limit_m3_per_day": 5000.00,
          "rolling_window_days": 7}


def _completed_off_spec_run():
    return setup_completed_run(reel_readings=OFF_SPEC_REELS,
                               machine_overrides=MACHINE,
                               permit_overrides=PERMIT,
                               run_overrides={"pulp_draw_tons": 20.000})


def test_quality_hold_and_rework_leave_the_run_axis_at_completed():
    """PRD §3.5: "This gives the cycle `PROVISIONAL → HELD → REWORK → PROVISIONAL`,
    which runs entirely on the quality axis while `run_status` stays `COMPLETED`
    throughout."
    PRD §3.5: "Rework, `HELD → REWORK`, requires the quality axis to read `HELD` and
    flips every `QUARANTINED` roll set of the run to `REWOUND`, incrementing each
    set's `rewind_count`."

    Design: Difficulty/non_linear_state_machine/production_run_quality_axis_cycles_while_run_axis_frozen
    """
    bundle = _completed_off_spec_run()
    machine_id, run_id = bundle["machine"]["id"], bundle["run"]["id"]

    assert bundle["run"]["provisional_quality_index"] == pytest.approx(78.57, abs=1e-6), \
        "reel 2 at 155.0 gsm scores 57.14, so the two-reel mean is 78.57"
    assert bundle["run"]["off_spec_reel_count"] == 1

    held = validate_success(api_client.hold_run(machine_id, run_id, CERTIFIER))
    assert held["quality_status"] == "HELD"
    assert held["certified_quality_index"] == pytest.approx(78.57, abs=1e-6)
    assert held["run_status"] == "COMPLETED"

    reworked = validate_success(api_client.rework_run(machine_id, run_id, PLANNER))
    assert reworked["quality_status"] == "REWORK"
    assert reworked["run_status"] == "COMPLETED", \
        "the run axis is frozen while the quality axis cycles"


def test_requality_re_enters_provisional_with_a_new_index_then_certifies():
    """PRD §3.5: "Resubmission replaces the stored `reel_readings` and recomputes
    both `off_spec_reel_count` and the provisional quality index, putting the run
    back in front of the certification gate."
    PRD §3.5: "Certification stores `certified_quality_index`, records the acting
    identifier as `certified_by_user_id`, and makes every `WRAPPED` roll set of the
    run eligible for allocation."

    Design: Difficulty/non_linear_state_machine/production_run_quality_axis_cycles_while_run_axis_frozen
    """
    bundle = _completed_off_spec_run()
    machine_id, run_id = bundle["machine"]["id"], bundle["run"]["id"]
    api_client.hold_run(machine_id, run_id, CERTIFIER)
    api_client.rework_run(machine_id, run_id, PLANNER)

    resubmitted = validate_success(api_client.resubmit_run_quality(
        machine_id, run_id, {"reel_readings": REWORKED_REELS}, CERTIFIER))
    assert resubmitted["quality_status"] == "PROVISIONAL", \
        "the run re-occupies a state it has already left"
    assert resubmitted["provisional_quality_index"] == pytest.approx(97.15, abs=1e-6), \
        f"the replacement readings mean 100.00 and 94.29, so 97.15, got {resubmitted['provisional_quality_index']}"
    assert resubmitted["off_spec_reel_count"] == 0
    assert resubmitted["run_status"] == "COMPLETED"

    certified = validate_success(api_client.certify_run(machine_id, run_id, CERTIFIER))
    assert certified["quality_status"] == "CERTIFIED"
    assert certified["certified_quality_index"] == pytest.approx(97.15, abs=1e-6)
    assert certified["certified_by_user_id"] == "ql_cert"
    assert certified["run_status"] == "COMPLETED"


def test_fourth_deink_pass_is_refused_and_the_batch_stays_held():
    """PRD §3.3: "Moving `DEINK_HOLD → DEINKING` requires the batch to be in
    `DEINK_HOLD` and requires `deink_pass_count` to be below 3; it replaces
    `caustic_kg`, `peroxide_kg` and `surfactant_kg` with the new pass's charges."
    PRD §3.3: "Since the counter starts at 0, this allows three passes in total, and
    the pass that would be the fourth — attempted when `deink_pass_count` already
    reads 3 — is rejected with `ERR_DEINK_PASS_LIMIT` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/pulp_batch_deink_loop_reentry_until_pass_limit
    """
    bundle = setup_batch_at_deink_hold(caustic_kg=40.0, peroxide_kg=25.0,
                                       surfactant_kg=6.0, failing_brightness=70.0)
    batch_id = bundle["batch"]["id"]
    run_deink_pass(batch_id, 55.0, 35.0, 9.0)
    record_brightness(batch_id, 74.0)
    run_deink_pass(batch_id, 60.0, 40.0, 12.0)
    record_brightness(batch_id, 77.0)

    response = api_client.deink_pulp_batch(
        batch_id, {"caustic_kg": 60.0, "peroxide_kg": 40.0, "surfactant_kg": 12.0},
        OPERATOR)
    validate_error(response, ApiErrorId.ERR_DEINK_PASS_LIMIT.value, 409)

    batch = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert batch["status"] == "DEINK_HOLD", "the refusal parks the batch, it does not fail forward"
    assert batch["deink_pass_count"] == 3
    assert batch["final_accepted_tons"] is None


def test_effectiveness_decay_shrinks_the_sludge_won_by_each_successive_lap():
    """PRD §3.3: "**Effectiveness** decays across passes: it is 0.65 raised to the
    power of the pass index minus one, rounded half up to four decimal places, so
    the first pass runs at full effectiveness, the second at 0.6500, the third at
    0.4225."
    PRD §3.3: "Finally, `cumulative_chemical_cost` becomes its previous value plus
    this pass's cost, rounded half up to two decimal places, so the field
    accumulates across every pass the batch ever runs."

    Design: Difficulty/non_linear_state_machine/pulp_batch_deink_loop_reentry_until_pass_limit
    """
    bundle = setup_batch_at_deink_hold(caustic_kg=40.0, peroxide_kg=25.0,
                                       surfactant_kg=6.0, failing_brightness=70.0)
    batch_id = bundle["batch"]["id"]
    run_deink_pass(batch_id, 55.0, 35.0, 9.0)
    record_brightness(batch_id, 74.0)
    run_deink_pass(batch_id, 60.0, 40.0, 12.0)
    batch = record_brightness(batch_id, 77.0)

    assert batch["cumulative_chemical_cost"] == pytest.approx(333.20, abs=1e-6), \
        f"81.35 + 115.45 + 136.40 must give 333.20, got {batch['cumulative_chemical_cost']}"
    rows = solids_rows(source_ref_id=batch_id, source_kind="DEINK_SLUDGE")
    assert len(rows) == 3, f"three laps must leave three sludge rows, got {len(rows)}"
    tonnages = sorted((row["dry_solids_tons"] for row in rows), reverse=True)
    assert tonnages == pytest.approx([0.258, 0.175, 0.118], abs=1e-6), \
        "each lap wins strictly less sludge than the last despite heavier chemistry"


def test_three_dispositions_out_of_sampled_have_divergent_side_effect_sets():
    """PRD §3.2: "Acceptance sets `accepted_grade_code` equal to `declared_grade_code`
    and creates exactly one fiber inventory lot whose `grade_code` is that accepted
    grade, whose `tons_received` is the receipt's `net_tons`, whose
    `contamination_pct` is copied from the receipt's `weighted_contamination_pct`,
    and whose lot `status` is `AVAILABLE`."
    PRD §3.2: "Rejection sets `accepted_grade_code` to null and — this is where the
    branch diverges sharply from the other two — creates **no** inventory lot and
    leaves the parent order's `received_net_tons` completely unchanged."

    Design: Difficulty/non_linear_state_machine/fiber_receipt_fork_join_with_divergent_side_effect_sets
    """
    declare_standard_grades()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=200.00,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                             negotiated_delta_per_ton=0.00)
    clean = record_receipt(po["id"], [sublot(1, 22.000, 2.000, 10.00, 2.50)], "TRK-F-001")
    dirty = record_receipt(po["id"], [sublot(1, 12.000, 2.000, 10.00, 4.50)], "TRK-F-002")
    filthy = record_receipt(po["id"], [sublot(1, 7.000, 2.000, 10.00, 7.00)], "TRK-F-003")
    disposition(clean["id"], "ACCEPT")
    disposition(dirty["id"], "DOWNGRADE")

    rejected = validate_success(api_client.disposition_receipt(
        filthy["id"], {"disposition": "REJECT"}, DISPOSER))

    assert rejected["status"] == "REJECTED"
    assert rejected["accepted_grade_code"] is None
    assert rejected["net_tons"] == pytest.approx(5.00, abs=1e-6), \
        "a rejected truck still carries its weighed tonnage"
    accepted = get_success_data(api_client.get_receipt(clean["id"], DISPOSER))
    assert accepted["status"] == "ACCEPTED" and accepted["accepted_grade_code"] == "OCC_11"
    assert accepted["net_tons"] == pytest.approx(20.00, abs=1e-6)
    downgraded = get_success_data(api_client.get_receipt(dirty["id"], DISPOSER))
    assert downgraded["status"] == "DOWNGRADED"
    assert downgraded["accepted_grade_code"] == "MIX_54", \
        "downgrade mints its lot at the fallback grade, not the ordered grade"
    assert downgraded["net_tons"] == pytest.approx(10.00, abs=1e-6)
    assert lots_of_receipt(filthy["id"]) == [], "rejection mints nothing"


def test_only_the_two_lot_minting_branches_book_tonnage_and_only_two_take_strikes():
    """PRD §3.2: "The receipt's `accepted_grade_code` is set to the fallback grade
    code, and a single inventory lot is created at that fallback grade with
    `tons_received` equal to the receipt's `net_tons` and lot status `AVAILABLE`; the
    receipt's `net_tons` is added into the parent order's `received_net_tons` exactly
    as on acceptance, so the same order auto-transition may follow."
    PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three
    strikes makes it `PROBATION`; anything below two leaves it `QUALIFIED`."

    Design: Difficulty/non_linear_state_machine/fiber_receipt_fork_join_with_divergent_side_effect_sets
    """
    declare_standard_grades()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=200.00,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                             negotiated_delta_per_ton=0.00)
    clean = record_receipt(po["id"], [sublot(1, 22.000, 2.000, 10.00, 2.50)], "TRK-F-001")
    dirty = record_receipt(po["id"], [sublot(1, 12.000, 2.000, 10.00, 4.50)], "TRK-F-002")
    filthy = record_receipt(po["id"], [sublot(1, 7.000, 2.000, 10.00, 7.00)], "TRK-F-003")
    disposition(clean["id"], "ACCEPT")
    disposition(dirty["id"], "DOWNGRADE")
    disposition(filthy["id"], "REJECT")

    order = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert order["received_net_tons"] == pytest.approx(30.00, abs=1e-6), \
        f"only ACCEPT and DOWNGRADE book tonnage, so 20.00 + 10.00, got {order['received_net_tons']}"
    assert order["status"] == "PARTIALLY_RECEIVED"

    occ_lots, occ_meta = _paginated(api_client.list_inventory_lots(
        OPERATOR, {"grade_code": "OCC_11"}))
    mix_lots, mix_meta = _paginated(api_client.list_inventory_lots(
        OPERATOR, {"grade_code": "MIX_54"}))
    assert occ_meta["total_count"] == 1 and occ_lots[0]["tons_received"] == pytest.approx(20.00, abs=1e-6)
    assert mix_meta["total_count"] == 1 and mix_lots[0]["tons_received"] == pytest.approx(10.00, abs=1e-6)

    sup = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert sup["contamination_strike_count"] == 2, \
        "DOWNGRADE and REJECT each take a strike; ACCEPT does not"
    assert sup["qualification_status"] == "PROBATION"
