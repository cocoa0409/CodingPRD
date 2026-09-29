"""Dual-variant calculations: book yield versus measured yield, and the two
run quality indexes that are struck from the same reel readings.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_approved_batch, setup_available_lot, setup_completed_run,
    setup_batch_at_deink_hold, run_deink_pass, record_brightness,
    approve_batch, solids_rows, reel_reading, TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
LAB = TEST_USERS["lab_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def test_receipt_net_tonnage_and_weighted_samples_pinned_at_creation():
    """PRD §3.2: "The receipt's `moisture_deduction_tons` is the sum of the
    per-sublot deductions, rounded to three decimal places, and its `net_tons` is
    the sum of the per-sublot **already-rounded** dry tonnages, rounded half up to
    two decimal places."
    PRD §3.2: "`weighted_moisture_pct` is the sum over sublots of wet tonnage
    multiplied by that sublot's `moisture_pct`, divided by the sum of the wet
    tonnages, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/pulp_batch_book_yield_versus_measured_reject_variance
    """
    bundle = setup_available_lot()
    receipt = get_success_data(api_client.get_receipt(bundle["receipt"]["id"], LAB))

    assert receipt["net_tons"] == pytest.approx(36.00, abs=1e-6), \
        f"19.500 + 16.500 must give net_tons 36.00, got {receipt['net_tons']}"
    assert receipt["moisture_deduction_tons"] == pytest.approx(0.500, abs=1e-6)
    assert receipt["weighted_moisture_pct"] == pytest.approx(12.92, abs=1e-6)
    assert receipt["weighted_contamination_pct"] == pytest.approx(2.73, abs=1e-6)

    lot = get_success_data(api_client.get_inventory_lot(bundle["lot"]["id"], OPERATOR))
    assert lot["tons_received"] == pytest.approx(36.00, abs=1e-6)
    assert lot["contamination_pct"] == pytest.approx(2.73, abs=1e-6)


def test_book_projection_and_measured_yield_diverge_by_the_stored_variance():
    """PRD §3.3: "Each line then contributes its `tons_charged` multiplied by that
    effective yield and divided by 100, rounded half up to three decimal places,
    and `provisional_accepted_tons` is the sum of those per-line contributions
    rounded half up to three decimal places."
    PRD §3.3: "`yield_variance_tons` is `final_accepted_tons` minus
    `provisional_accepted_tons`, rounded to three decimal places and signed — it
    may legitimately be negative."

    Design: Difficulty/dual_variant_calc/pulp_batch_book_yield_versus_measured_reject_variance
    """
    bundle = setup_approved_batch()
    batch = get_success_data(api_client.get_pulp_batch(bundle["batch"]["id"], OPERATOR))

    assert batch["status"] == "APPROVED"
    assert batch["charged_tons"] == pytest.approx(30.000, abs=1e-6)
    assert batch["blend_contamination_pct"] == pytest.approx(2.730, abs=1e-6)
    assert batch["provisional_accepted_tons"] == pytest.approx(24.926, abs=1e-6), \
        f"book yield 88.00 - 1.8*2.73 over 30.000 t must give 24.926, got {batch['provisional_accepted_tons']}"
    assert batch["final_accepted_tons"] == pytest.approx(25.500, abs=1e-6), \
        f"30.000 - 4.500 must give 25.500, got {batch['final_accepted_tons']}"
    assert batch["yield_variance_tons"] == pytest.approx(0.574, abs=1e-6)
    assert batch["available_tons"] == pytest.approx(25.500, abs=1e-6)
    assert batch["provisional_accepted_tons"] != batch["final_accepted_tons"], \
        "the two yield variants are never reconciled onto one number"


def test_deink_route_final_yield_subtracts_every_pass_sludge_row():
    """PRD §3.3: "`final_accepted_tons` is the batch's `charged_tons` minus its
    `measured_reject_tons` minus the total deink sludge charged against the batch,
    rounded half up to three decimal places, where the deink sludge total is the
    sum of `dry_solids_tons` over every non-reversal solids-ledger row whose
    `source_kind` is `DEINK_SLUDGE` and whose `source_ref_id` is this batch, taken
    across all passes in ascending creation order."

    Design: Difficulty/dual_variant_calc/deink_path_yield_variance_with_sludge_subtraction
    """
    bundle = setup_batch_at_deink_hold()
    batch_id = bundle["batch"]["id"]
    run_deink_pass(batch_id, 55.0, 35.0, 9.0)
    batch = record_brightness(batch_id, 82.0)

    assert batch["status"] == "APPROVED"
    assert batch["deink_pass_count"] == 2
    assert batch["provisional_accepted_tons"] == pytest.approx(10.357, abs=1e-6)
    sludge = solids_rows(source_ref_id=batch_id, source_kind="DEINK_SLUDGE")
    tonnages = sorted(row["dry_solids_tons"] for row in sludge)
    assert len(sludge) == 2, f"two passes must leave two DEINK_SLUDGE rows, got {len(sludge)}"
    assert tonnages == pytest.approx([0.175, 0.258], abs=1e-6)
    assert batch["final_accepted_tons"] == pytest.approx(12.567, abs=1e-6), \
        f"15.000 - 2.000 - 0.433 must give 12.567, got {batch['final_accepted_tons']}"
    assert batch["yield_variance_tons"] == pytest.approx(2.210, abs=1e-6)


def test_deink_chemical_cost_accumulates_across_both_passes():
    """PRD §3.3: "Finally, `cumulative_chemical_cost` becomes its previous value
    plus this pass's cost, rounded half up to two decimal places, so the field
    accumulates across every pass the batch ever runs."

    Design: Difficulty/dual_variant_calc/deink_path_yield_variance_with_sludge_subtraction
    """
    bundle = setup_batch_at_deink_hold()
    batch_id = bundle["batch"]["id"]
    after_first = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert after_first["cumulative_chemical_cost"] == pytest.approx(81.35, abs=1e-6), \
        "pass 1 raw cost 73.95 with the ten percent tissue premium is 81.35"

    run_deink_pass(batch_id, 55.0, 35.0, 9.0)
    batch = record_brightness(batch_id, 82.0)
    assert batch["cumulative_chemical_cost"] == pytest.approx(196.80, abs=1e-6), \
        f"81.35 + 115.45 must give 196.80, got {batch['cumulative_chemical_cost']}"


REELS_PROVISIONAL_HIGH = [
    reel_reading(1, 1.000, 140.0, 7.50, 2.50),
    reel_reading(2, 12.000, 146.8, 7.50, 2.50),
    reel_reading(3, 12.000, 146.8, 7.50, 2.50),
    reel_reading(4, 1.000, 140.0, 7.50, 2.50),
]


def test_provisional_index_reads_only_the_first_and_last_reel():
    """PRD §3.5: "The **provisional quality index**, stored as
    `provisional_quality_index`, is the plain arithmetic mean of exactly two reel
    scores — the reel with the smallest `reel_no` and the reel with the largest
    `reel_no` — rounded half up to two decimal places, regardless of how many
    reels the run actually produced."

    Design: Difficulty/dual_variant_calc/run_quality_endpoints_unweighted_versus_all_reels_weighted_divergence
    """
    bundle = setup_completed_run(reel_readings=REELS_PROVISIONAL_HIGH,
                                 run_overrides={"pulp_draw_tons": 20.000},
                                 machine_overrides={"wire_width_mm": 4200,
                                                    "max_tons_per_hour": 20.00,
                                                    "changeover_buffer_minutes": 60,
                                                    "steam_tph_per_ton": 1.400})
    run = get_success_data(api_client.get_run(bundle["run"]["id"], PLANNER))

    assert run["run_status"] == "COMPLETED"
    assert run["quality_status"] == "PROVISIONAL"
    assert run["provisional_quality_index"] == pytest.approx(100.00, abs=1e-6), \
        f"reels 1 and 4 are exactly on target, got {run['provisional_quality_index']}"
    assert run["off_spec_reel_count"] == 0, \
        "a 4.857 percent basis-weight deviation is inside the 5.00 percent gate"


def test_certified_index_weights_every_reel_and_can_fall_below_the_gate():
    """PRD §3.5: "The **certified quality index** is the tonnage-weighted mean of
    **every** reel: the sum over all reel readings of `reel_tons` multiplied by
    that reel's already-rounded score, divided by the sum of all `reel_tons`, the
    quotient rounded half up to two decimal places."
    PRD §3.5: "It also computes and stores `certified_quality_index` — the number
    is struck whichever way the verdict goes."

    Design: Difficulty/dual_variant_calc/run_quality_endpoints_unweighted_versus_all_reels_weighted_divergence
    """
    bundle = setup_completed_run(reel_readings=REELS_PROVISIONAL_HIGH,
                                 run_overrides={"pulp_draw_tons": 20.000},
                                 machine_overrides={"wire_width_mm": 4200,
                                                    "max_tons_per_hour": 20.00,
                                                    "changeover_buffer_minutes": 60,
                                                    "steam_tph_per_ton": 1.400})
    resp = api_client.hold_run(bundle["machine"]["id"], bundle["run"]["id"], CERTIFIER)
    run = validate_success(resp)

    assert run["quality_status"] == "HELD"
    assert run["run_status"] == "COMPLETED", "the run axis is untouched by a quality hold"
    assert run["certified_quality_index"] == pytest.approx(82.06, abs=1e-6), \
        f"tonnage-weighted over all four reels must give 82.06, got {run['certified_quality_index']}"
    assert run["provisional_quality_index"] >= 85.00 > run["certified_quality_index"], \
        "the same reels certify under one variant and hold under the other"
