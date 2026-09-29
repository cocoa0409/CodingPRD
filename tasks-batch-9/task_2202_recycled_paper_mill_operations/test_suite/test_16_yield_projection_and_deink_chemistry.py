"""The two yield numbers a batch carries — the book projection struck at the charge and
the weighed figure struck at approval — plus the decaying chemistry of the deink loop.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    declare_fiber_grade, declare_tl_140, declare_tis_16, publish_quote,
    setup_available_lot, setup_deink_lot, queue_batch, drive_batch_to_cleaned,
    approve_batch, run_deink_pass, record_brightness, furnish_line, sublot,
    solids_rows, solids_summary,
)

BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]

TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
TWENTY_TON_DEINK_SUBLOT = [sublot(1, 22.000, 2.000, 8.00, 1.00)]
FULL_CHEMICAL_CHARGE = {"caustic_kg": 100.000, "peroxide_kg": 50.000,
                        "surfactant_kg": 20.000}


def _cleaned_tissue_batch_of_ten_tons():
    """10.000 tons of 1.00%-contamination deink furnish on DIP_LINE, driven to CLEANED."""
    declare_tis_16(min_brightness_iso=82.0)
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=2.00, max_moisture_pct=10.00,
                        nominal_yield_pct=80.00, deink_required=True, rank_order=2)
    bundle = setup_deink_lot(sublots_list=TWENTY_TON_DEINK_SUBLOT, declare_grade=False)
    batch = queue_batch("TIS_16", [furnish_line(bundle["lot"]["id"], 10.000)],
                        pulper_line="DIP_LINE")
    drive_batch_to_cleaned(batch["id"], 1.000)
    return batch


def test_a_dirty_mixed_paper_charge_is_lifted_to_the_yield_floor():
    """PRD §3.3: "And `provisional_accepted_tons` is the book-yield projection: walking the
    furnish lines in ascending lot `created_at` order and, for lots created at the same
    instant, in ascending `rank_order` of the lot's grade, each line's **effective yield**
    is the grade's `nominal_yield_pct` reduced by 1.8 percentage points for every whole
    percentage point of the lot's `contamination_pct`, but never allowed below a yield floor
    of 45.00 percent — that is, the effective yield is the larger of 45.00 and the nominal
    yield minus 1.8 times the lot contamination."
    PRD §3.3: "And the blend must be clean enough: the batch's computed
    `blend_contamination_pct` must be no greater than 3.500, and a dirtier blend is rejected
    with `ERR_FURNISH_CONTAMINATION_EXCEEDED` (HTTP 409)."
    PRD §3.3: "As side effects of the charge, each furnish line's `tons_charged` is added
    into its lot's `tons_consumed`, each affected lot's `tons_available` is recomputed, and
    any lot whose recomputed `tons_available` lands on exactly 0.000 flips from `AVAILABLE`
    to `DEPLETED`."

    Design: Corner/calculations/effective_yield_is_clamped_at_the_yield_floor_for_dirty_furnish
    """
    declare_tl_140()
    declare_fiber_grade(grade_code="MXP_54", index_symbol="PPI_ONP",
                        max_contamination_pct=3.00, max_moisture_pct=10.00,
                        nominal_yield_pct=48.00, rank_order=4)
    publish_quote(index_symbol="PPI_ONP", effective_month="2026-07",
                  published_price_per_ton=90.00)
    bundle = setup_available_lot(sublots_list=[sublot(1, 12.000, 2.000, 8.00, 3.00)],
                                grade_code="MXP_54", contracted_tons=100.00,
                                freight_per_ton=10.00,
                                supplier_name="Curbside Mixed Collectors",
                                declare_grades=False, publish_index=False)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 10.000)])

    charged = validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))

    assert charged["status"] == "PULPING"
    assert charged["charged_tons"] == pytest.approx(10.000, abs=1e-6)
    assert charged["blend_contamination_pct"] == pytest.approx(3.000, abs=1e-6)
    assert charged["provisional_accepted_tons"] == pytest.approx(4.500, abs=1e-6), \
        "48.00 - 1.8 * 3.00 is 42.60, which the floor lifts to 45.00"

    lot = get_success_data(api_client.get_inventory_lot(bundle["lot"]["id"], OPERATOR))
    assert lot["tons_consumed"] == pytest.approx(10.000, abs=1e-6)
    assert lot["tons_available"] == pytest.approx(0.000, abs=1e-6)
    assert lot["status"] == "DEPLETED"


def test_book_projection_and_weighed_final_diverge_by_the_yield_variance():
    """PRD §3.3: "`final_accepted_tons` is the batch's `charged_tons` minus its
    `measured_reject_tons` minus the total deink sludge charged against the batch, rounded
    half up to three decimal places, where the deink sludge total is the sum of
    `dry_solids_tons` over every non-reversal solids-ledger row whose `source_kind` is
    `DEINK_SLUDGE` and whose `source_ref_id` is this batch, taken across all passes in
    ascending creation order."
    PRD §3.3: "`yield_variance_tons` is `final_accepted_tons` minus
    `provisional_accepted_tons`, rounded to three decimal places and signed — it may
    legitimately be negative."
    PRD §3.3: "The two yield figures are deliberately kept side by side: the provisional
    number is a projection from grade book yields discounted for contamination, the final
    number is physical weight subtraction, they differ for identical furnish, and nothing in
    this system ever reconciles them back together."

    Design: Corner/calculations/provisional_and_final_yield_diverge_by_exactly_the_yield_variance
    """
    declare_tl_140()
    bundle = setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])
    drive_batch_to_cleaned(batch["id"], 2.000)

    approved = approve_batch(batch["id"])

    assert approved["status"] == "APPROVED"
    assert approved["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6)
    assert approved["final_accepted_tons"] == pytest.approx(18.000, abs=1e-6)
    assert approved["yield_variance_tons"] == pytest.approx(1.120, abs=1e-6)
    assert approved["available_tons"] == pytest.approx(18.000, abs=1e-6), \
        "available tonnage follows the weighed number, never the projection"
    assert approved["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert approved["deink_pass_count"] == 0

    rows = solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")
    assert len(rows) == 1
    assert rows[0]["dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)


def test_a_second_deink_pass_costs_the_same_but_removes_a_decayed_share():
    """PRD §3.3: "The **pass cost** equals that raw cost when the target product's `family`
    is `CONTAINERBOARD`, and equals the raw cost multiplied by 1.10 — a ten percent tissue
    premium — rounded half up to two decimal places when the family is `TISSUE`; identical
    chemical charges therefore cost different money depending on where the pulp is going."
    PRD §3.3: "**Effectiveness** decays across passes: it is 0.65 raised to the power of the
    pass index minus one, rounded half up to four decimal places, so the first pass runs at
    full effectiveness, the second at 0.6500, the third at 0.4225."
    PRD §3.3: "The pass's **sludge tonnage** is `charged_tons` multiplied by an assumed ink
    load of 4.50 percent, divided by 100, multiplied by the removal fraction, rounded half
    up to three decimal places; that is the figure written into the appended `DEINK_SLUDGE`
    row."
    PRD §3.3: "Finally, `cumulative_chemical_cost` becomes its previous value plus this
    pass's cost, rounded half up to two decimal places, so the field accumulates across
    every pass the batch ever runs."

    Design: Corner/calculations/second_deink_pass_costs_the_same_money_but_removes_decayed_ink
    """
    batch = _cleaned_tissue_batch_of_ten_tons()
    run_deink_pass(batch["id"], **FULL_CHEMICAL_CHARGE)
    held = record_brightness(batch["id"], 70.0)
    assert held["status"] == "DEINK_HOLD"
    assert held["cumulative_chemical_cost"] == pytest.approx(206.25, abs=1e-6)
    run_deink_pass(batch["id"], **FULL_CHEMICAL_CHARGE)

    approved = record_brightness(batch["id"], 85.0)

    assert approved["status"] == "APPROVED"
    assert approved["deink_pass_count"] == 2
    assert approved["cumulative_chemical_cost"] == pytest.approx(412.50, abs=1e-6), \
        "the tissue premium is charged again in full; only removal decays"
    assert approved["provisional_accepted_tons"] == pytest.approx(7.820, abs=1e-6)
    assert approved["final_accepted_tons"] == pytest.approx(8.621, abs=1e-6)
    assert approved["yield_variance_tons"] == pytest.approx(0.801, abs=1e-6)
    assert approved["available_tons"] == pytest.approx(8.621, abs=1e-6)

    sludge = solids_rows(source_ref_id=batch["id"], source_kind="DEINK_SLUDGE")
    assert len(sludge) == 2
    assert sludge[0]["dry_solids_tons"] == pytest.approx(0.230, abs=1e-6)
    assert sludge[1]["dry_solids_tons"] == pytest.approx(0.149, abs=1e-6)


def test_reversing_the_first_sludge_row_moves_the_ledger_but_not_the_yield():
    """PRD §3.7: "A row weighed in error is reversed rather than edited."
    PRD §3.7: "Reversing requires the addressed row's `disposition` to be `PENDING`,
    failing with `ERR_ENV_RECORD_INVALID_STATE` otherwise, and produces a **new** solids row
    whose `reversal_of_id` is the addressed row and whose `dry_solids_tons` equals the
    addressed row's tonnage."
    PRD §3.3: "`final_accepted_tons` is the batch's `charged_tons` minus its
    `measured_reject_tons` minus the total deink sludge charged against the batch, rounded
    half up to three decimal places, where the deink sludge total is the sum of
    `dry_solids_tons` over every non-reversal solids-ledger row whose `source_kind` is
    `DEINK_SLUDGE` and whose `source_ref_id` is this batch, taken across all passes in
    ascending creation order."
    PRD §2.9: "The solids ledger reports `gross_solids_tons` (the sum of `dry_solids_tons`
    over rows that are not reversals, to 3 decimal places), `reversed_solids_tons` (the same
    sum over rows that *are* reversals), `net_solids_tons` (gross minus reversed, to 3
    decimal places), and three disposition splits over non-reversal rows:
    `manifested_dry_solids_tons` for rows whose disposition is `MANIFESTED`,
    `unmanifested_dry_solids_tons` for rows whose disposition is `PENDING`, and
    `repulped_dry_solids_tons` for rows whose disposition is `REPULPED`."

    Design: Corner/calculations/reversing_a_deink_sludge_row_moves_the_ledger_but_not_the_final_yield
    """
    batch = _cleaned_tissue_batch_of_ten_tons()
    run_deink_pass(batch["id"], **FULL_CHEMICAL_CHARGE)
    record_brightness(batch["id"], 70.0)
    first_sludge = solids_rows(source_ref_id=batch["id"],
                               source_kind="DEINK_SLUDGE")[0]
    validate_success(api_client.reverse_reject_stream(first_sludge["id"], ENV), 201)
    run_deink_pass(batch["id"], **FULL_CHEMICAL_CHARGE)

    approved = record_brightness(batch["id"], 85.0)

    assert approved["final_accepted_tons"] == pytest.approx(8.621, abs=1e-6), \
        "the reversed original is still a non-reversal sludge row for the yield"
    assert approved["yield_variance_tons"] == pytest.approx(0.801, abs=1e-6)

    reversed_row = get_success_data(
        api_client.get_reject_stream(first_sludge["id"], ENV))
    assert reversed_row["disposition"] == "REPULPED"
    assert reversed_row["reversal_of_id"] is None
    mirror = solids_rows(reversal_of_id=first_sludge["id"])
    assert len(mirror) == 1
    assert mirror[0]["dry_solids_tons"] == pytest.approx(0.230, abs=1e-6)

    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(1.379, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.230, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(1.149, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(1.149, abs=1e-6)
    assert summary["repulped_dry_solids_tons"] == pytest.approx(0.230, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
