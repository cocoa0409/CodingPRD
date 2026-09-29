"""Values that sit exactly on a documented threshold, and their nearest
one-hundredth or one-thousandth neighbours on the far side of it.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    declare_standard_grades, declare_tl_140, publish_quote, register_supplier,
    create_confirmed_po, record_receipt, disposition, sublot, lots_of_receipt,
    po_version, setup_available_lot, queue_batch, furnish_line,
    register_permit, register_machine, setup_approved_batch, schedule_run,
    start_run, complete_run, log_reading, reel_reading, TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
ENV = TEST_USERS["env_officer_headers"]

MILL_PERMIT = {"permit_number": "MILL-NPDES-01", "bod_limit_kg_per_day": 100.00,
               "tss_limit_kg_per_day": 200.00, "flow_limit_m3_per_day": 5000.00,
               "rolling_window_days": 7}
PM1 = {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}


def _permit_sitting_exactly_on_its_bod_limit():
    """Two readings averaging 100.000 kg BOD against a 100.00 limit, the second
    discharging exactly 5000.00 m3 against a 5000.00 flow limit."""
    permit = register_permit(**MILL_PERMIT)
    log_reading(permit["id"], reading_date="2026-07-28", flow_m3=4000.00,
                bod_kg=90.00, tss_kg=100.00)
    log_reading(permit["id"], reading_date="2026-07-29", flow_m3=5000.00,
                bod_kg=110.00, tss_kg=120.00)
    return permit


def _mix_54_contract_for_one_hundred_tons():
    declare_standard_grades()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=195.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    return create_confirmed_po(supplier["id"], "MIX_54", contracted_tons=100.00,
                               index_basis="PRIOR_MONTH", priced_for_month="2026-08")


def test_a_ratio_of_exactly_one_and_a_flow_exactly_at_the_limit_only_reach_watch():
    """PRD §3.7: "The boundaries deserve care in both directions: a ratio of exactly
    1.00 is **not** an exceedance, because the comparison is strict, so a permit
    sitting exactly at its limit lands on `WATCH`; and a `flow_m3` exactly equal to
    `flow_limit_m3_per_day` does not count as an exceedance day."

    Design: Difficulty/boundary_precision_check/effluent_ratio_exactly_one_and_flow_exactly_at_limit_stay_watch
    """
    permit = _permit_sitting_exactly_on_its_bod_limit()

    posture = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(100.000, abs=1e-6)
    assert posture["rolling_tss_kg_per_day"] == pytest.approx(110.000, abs=1e-6)
    assert posture["exceedance_day_count"] == 0, \
        "5000.00 m3 is not strictly greater than the 5000.00 flow limit"
    assert posture["compliance_posture"] == "WATCH", \
        "a BOD ratio of exactly 1.00 sits on WATCH, not EXCEEDANCE"


def test_the_second_over_limit_flow_day_tips_the_posture_without_any_ratio_breach():
    """PRD §3.7: "The posture is `EXCEEDANCE` when either ratio is strictly greater
    than 1.00, or when `exceedance_day_count` is 2 or more."

    Design: Difficulty/boundary_precision_check/effluent_ratio_exactly_one_and_flow_exactly_at_limit_stay_watch
    """
    permit = _permit_sitting_exactly_on_its_bod_limit()
    log_reading(permit["id"], reading_date="2026-07-30", flow_m3=5000.01,
                bod_kg=90.00, tss_kg=100.00)

    one_bad_day = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert one_bad_day["rolling_bod_kg_per_day"] == pytest.approx(96.667, abs=1e-6)
    assert one_bad_day["exceedance_day_count"] == 1
    assert one_bad_day["compliance_posture"] == "WATCH"

    log_reading(permit["id"], reading_date="2026-07-31", flow_m3=5000.01,
                bod_kg=90.00, tss_kg=100.00)

    two_bad_days = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert two_bad_days["rolling_bod_kg_per_day"] == pytest.approx(95.000, abs=1e-6)
    assert two_bad_days["rolling_tss_kg_per_day"] == pytest.approx(105.000, abs=1e-6)
    assert two_bad_days["exceedance_day_count"] == 2
    assert two_bad_days["compliance_posture"] == "EXCEEDANCE", \
        "both ratios are still under 1.00; the day count alone carries the posture"


def test_ninety_seven_point_nine_nine_tons_leaves_the_order_partially_received():
    """PRD §3.1: "From `CONFIRMED`, if the recomputed tonnage is below 98 percent of
    `contracted_tons` the order advances `CONFIRMED → PARTIALLY_RECEIVED`; if the very
    first disposition already brings it to 98 percent of `contracted_tons` or more,
    the order goes straight `CONFIRMED → CLOSED`."

    Design: Difficulty/boundary_precision_check/purchase_order_closes_at_exactly_ninety_eight_percent_received
    """
    po = _mix_54_contract_for_one_hundred_tons()
    receipt = record_receipt(po["id"], [sublot(1, 59.990, 2.000, 10.00, 5.00),
                                        sublot(2, 42.000, 2.000, 10.00, 5.00)])
    assert receipt["net_tons"] == pytest.approx(97.99, abs=1e-6)
    assert receipt["moisture_deduction_tons"] == pytest.approx(0.000, abs=1e-6)

    before = po_version(po["id"])
    disposition(receipt["id"], "ACCEPT")

    after = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert after["received_net_tons"] == pytest.approx(97.99, abs=1e-6)
    assert after["status"] == "PARTIALLY_RECEIVED", \
        "97.99 is one hundredth of a ton below the 98.00 threshold"
    assert after["version"] == before + 1


def test_the_final_hundredth_of_a_ton_closes_the_order_on_the_inclusive_threshold():
    """PRD §3.1: "The comparison threshold is `contracted_tons` multiplied by 0.98,
    and the boundary is inclusive: tonnage exactly equal to that product closes the
    order."

    Design: Difficulty/boundary_precision_check/purchase_order_closes_at_exactly_ninety_eight_percent_received
    """
    po = _mix_54_contract_for_one_hundred_tons()
    first = record_receipt(po["id"], [sublot(1, 59.990, 2.000, 10.00, 5.00),
                                      sublot(2, 42.000, 2.000, 10.00, 5.00)])
    disposition(first["id"], "ACCEPT")

    second = record_receipt(po["id"], [sublot(1, 1.010, 1.000, 10.00, 5.00)])
    assert second["net_tons"] == pytest.approx(0.01, abs=1e-6)
    disposition(second["id"], "ACCEPT")

    closed = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert closed["received_net_tons"] == pytest.approx(98.00, abs=1e-6)
    assert closed["status"] == "CLOSED", \
        "98.00 equals 100.00 x 0.98 exactly, and that closes the contract"
    assert len(lots_of_receipt(first["id"])) == 1
    assert len(lots_of_receipt(second["id"])) == 1


def test_charging_one_thousandth_more_than_the_lot_holds_is_refused():
    """PRD §3.3: "Each line's `tons_charged` must be covered by that lot's
    `tons_available`, with the boundary inclusive so charging exactly the remaining
    tonnage is allowed; charging more is rejected with `ERR_INSUFFICIENT_FIBER`
    (HTTP 409)." PRD §3.3: "The batch opens in `QUEUED`, and while it sits there it
    has reserved nothing."

    Design: Difficulty/boundary_precision_check/exact_lot_depletion_is_inclusive_at_pulper_charge
    """
    declare_tl_140()
    bundle = setup_available_lot()
    lot = bundle["lot"]
    assert lot["tons_available"] == pytest.approx(36.000, abs=1e-6)
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 36.001)])

    response = api_client.start_pulp_batch(batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FIBER.value, 409)

    still_queued = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert still_queued["status"] == "QUEUED"
    untouched = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert untouched["tons_consumed"] == pytest.approx(0.000, abs=1e-6)
    assert untouched["tons_available"] == pytest.approx(36.000, abs=1e-6)
    assert untouched["status"] == "AVAILABLE"


def test_charging_the_lot_out_to_the_last_thousandth_depletes_it_and_pulps():
    """PRD §3.3: "As side effects of the charge, each furnish line's `tons_charged` is
    added into its lot's `tons_consumed`, each affected lot's `tons_available` is
    recomputed, and any lot whose recomputed `tons_available` lands on exactly 0.000
    flips from `AVAILABLE` to `DEPLETED`."

    Design: Difficulty/boundary_precision_check/exact_lot_depletion_is_inclusive_at_pulper_charge
    """
    declare_tl_140()
    bundle = setup_available_lot()
    lot = bundle["lot"]
    assert lot["contamination_pct"] == pytest.approx(2.73, abs=1e-6)
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 36.000)])

    charged = get_success_data(api_client.start_pulp_batch(batch["id"], OPERATOR))
    assert charged["status"] == "PULPING"
    assert charged["charged_tons"] == pytest.approx(36.000, abs=1e-6)
    assert charged["blend_contamination_pct"] == pytest.approx(2.730, abs=1e-6)
    assert charged["provisional_accepted_tons"] == pytest.approx(29.911, abs=1e-6), \
        "88.00 nominal less 1.8 x 2.73 gives an 83.086 percent effective yield"

    depleted = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert depleted["tons_consumed"] == pytest.approx(36.000, abs=1e-6)
    assert depleted["tons_available"] == pytest.approx(0.000, abs=1e-6)
    assert depleted["status"] == "DEPLETED"


def _two_completed_runs_on_pm1(gsm_a, gsm_b):
    """One approved batch feeding two non-overlapping windows on PM1, each run
    completed with a pair of identical reels so the weighted mean is that reel's
    score. Returns (machine_id, run_a, run_b)."""
    register_permit()
    machine = register_machine(**PM1)
    # PRD §3.5 declares the reel's measured `basis_weight_gsm` "at one decimal
    # place", so the spec target is set to 120.0 gsm: a one-decimal reel reading
    # of 124.5 is a 3.75 percent deviation, which is exactly the 15.00-point
    # basis-weight penalty that lands the score on the 85.00 gate.
    declare_tl_140(basis_weight_gsm=120.0)
    bundle = setup_approved_batch(declare_spec=False)
    runs = []
    for gsm, start, end in ((gsm_a, "2026-08-09T00:00:00Z", "2026-08-09T06:00:00Z"),
                            (gsm_b, "2026-08-09T08:00:00Z", "2026-08-09T12:00:00Z")):
        run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                           window_start=start, window_end=end, pulp_draw_tons=10.000)
        start_run(machine["id"], run["id"])
        runs.append(complete_run(machine["id"], run["id"],
                                 [reel_reading(1, 5.000, gsm, 7.50, 2.20),
                                  reel_reading(2, 5.000, gsm, 7.50, 2.20)]))
    return machine["id"], runs[0], runs[1]


def test_a_certified_index_of_exactly_eighty_five_clears_the_certification_gate():
    """PRD §3.5: "Certification, `PROVISIONAL → CERTIFIED`, is a `QualityLab` act with
    four requirements evaluated in this order: the quality axis must read
    `PROVISIONAL`; the acting `X-User-ID` must differ from the run's
    `started_by_user_id`, and an operator certifying their own run is rejected with
    `ERR_SOD_SAME_OPERATOR` (HTTP 409); `off_spec_reel_count` must be exactly 0; and
    the certified quality index must be at least 85.00."

    Design: Difficulty/boundary_precision_check/certified_index_exactly_eighty_five_certifies_one_hundredth_below_holds
    """
    machine_id, on_the_line, _below = _two_completed_runs_on_pm1(124.5, 124.6)
    assert on_the_line["provisional_quality_index"] == pytest.approx(85.00, abs=1e-6)
    assert on_the_line["off_spec_reel_count"] == 0, \
        "3.75 percent basis-weight deviation is not strictly greater than 5.00"

    certified = get_success_data(
        api_client.certify_run(machine_id, on_the_line["id"], CERTIFIER))
    assert certified["quality_status"] == "CERTIFIED"
    assert certified["certified_quality_index"] == pytest.approx(85.00, abs=1e-6), \
        "a 15.00-point basis-weight penalty lands the score exactly on the gate"
    assert certified["run_status"] == "COMPLETED"


def test_a_certified_index_one_hundredth_below_the_gate_must_be_held_instead():
    """PRD §3.5: "A run failing either of the last two conditions cannot be certified
    and must be held instead; the certification attempt is rejected with
    `ERR_QUALITY_INVALID_STATE`." PRD §3.5: "It also computes and stores
    `certified_quality_index` — the number is struck whichever way the verdict goes."

    Design: Difficulty/boundary_precision_check/certified_index_exactly_eighty_five_certifies_one_hundredth_below_holds
    """
    machine_id, _on_the_line, just_below = _two_completed_runs_on_pm1(124.5, 124.6)
    assert just_below["provisional_quality_index"] == pytest.approx(84.67, abs=1e-6)
    assert just_below["off_spec_reel_count"] == 0

    refused = api_client.certify_run(machine_id, just_below["id"], CERTIFIER)
    validate_error(refused, ApiErrorId.ERR_QUALITY_INVALID_STATE.value, 409)

    held = get_success_data(api_client.hold_run(machine_id, just_below["id"], CERTIFIER))
    assert held["quality_status"] == "HELD"
    assert held["certified_quality_index"] == pytest.approx(84.67, abs=1e-6), \
        "one tenth of a gram more basis weight drops the score below the 85.00 gate"
    assert held["run_status"] == "COMPLETED"
