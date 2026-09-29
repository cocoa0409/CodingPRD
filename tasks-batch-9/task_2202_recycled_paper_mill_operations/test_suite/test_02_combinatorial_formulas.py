"""Multi-input formulas whose intermediate rounding and evaluation order are
pinned: indexed fiber pricing, weighbridge summation, deink chemistry, and the
banded cogeneration credit.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    declare_standard_grades, declare_fiber_grade, declare_tis_16, publish_quote,
    register_supplier, create_draft_po, create_confirmed_po, record_receipt,
    disposition, lots_of_receipt, queue_batch, drive_batch_to_cleaned,
    record_brightness, request_steam, solids_rows, sublot, TEST_USERS,
)

BUYER = TEST_USERS["buyer_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENERGY = TEST_USERS["energy_headers"]


def test_volume_tier_stays_keyed_on_the_provisional_extended_value():
    """PRD §3.1: "Third, the **volume discount** tier is selected from that
    provisional extended value alone: a provisional value strictly below 100000.00
    United States dollars earns a discount of exactly 0.000, a value of 100000.00 or
    more but strictly below 250000.00 earns exactly 0.015, and a value of 250000.00
    or more earns exactly 0.030; both tier boundaries are inclusive at the lower
    edge."
    PRD §3.1: "The discount tier is chosen from the provisional extended value and
    is **never** re-derived from the final `extended_contract_value`, even when
    adding freight and the fuel surcharge pushes the final figure across the
    100000.00 or 250000.00 boundaries."

    Design: Difficulty/combinatorial_formula/indexed_price_tier_frozen_on_provisional_extended_value
    """
    declare_standard_grades()
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=240.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    po = create_draft_po(supplier["id"], "OCC_11", contracted_tons=500.00,
                         index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                         negotiated_delta_per_ton=5.00)

    priced = validate_success(api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": po["version"]}, BUYER))

    assert priced["status"] == "PRICED"
    assert priced["index_quote_month_used"] == "2026-07", \
        "PRIOR_MONTH must ignore the 2026-08 quote"
    assert priced["fuel_surcharge_per_ton"] == pytest.approx(4.07, abs=1e-6)
    assert priced["quoted_unit_price_per_ton"] == pytest.approx(221.07, abs=1e-6), \
        f"provisional 97500.00 earns discount 0.000, so 195.00 + 22.00 + 4.07 = 221.07, got {priced['quoted_unit_price_per_ton']}"
    assert priced["extended_contract_value"] == pytest.approx(110535.00, abs=1e-6)
    assert priced["quoted_unit_price_per_ton"] != pytest.approx(218.15, abs=1e-6), \
        "re-deriving the tier from the final extended value would give 218.15"
    assert priced["extended_contract_value"] != pytest.approx(109075.00, abs=1e-6)


def test_net_tons_sums_already_rounded_per_sublot_dry_tonnages():
    """PRD §3.2: "Working through the sublots in ascending `sublot_no` order, each
    sublot's **wet tonnage** is its `gross_tons` minus its `tare_tons`, rounded half
    up to three decimal places."
    PRD §3.2: "The receipt's `moisture_deduction_tons` is the sum of the per-sublot
    deductions, rounded to three decimal places, and its `net_tons` is the sum of
    the per-sublot **already-rounded** dry tonnages, rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/receipt_net_tons_per_sublot_rounding_before_summation
    """
    declare_fiber_grade(grade_code="MIX_54", index_symbol="PPI_OCC",
                        max_contamination_pct=6.00, max_moisture_pct=14.00,
                        nominal_yield_pct=78.00, deink_required=False,
                        downgrade_target_grade_code=None, rank_order=5)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                  published_price_per_ton=190.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=22.00)
    po = create_confirmed_po(supplier["id"], "MIX_54", contracted_tons=200.00,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                             negotiated_delta_per_ton=0.00)
    ten_identical = [sublot(n, 8.100, 1.000, 14.50, 5.00) for n in range(1, 11)]

    receipt = record_receipt(po["id"], ten_identical, truck_reference="TRK-M-010")

    assert receipt["status"] == "SAMPLED"
    assert receipt["moisture_deduction_tons"] == pytest.approx(0.360, abs=1e-6), \
        "raw 0.03550 quantises to 0.036 per sublot before it is summed"
    assert receipt["net_tons"] == pytest.approx(70.64, abs=1e-6), \
        f"ten dry tonnages of 7.064 must sum to 70.64, got {receipt['net_tons']}"
    assert receipt["net_tons"] != pytest.approx(70.65, abs=1e-6), \
        "summing raw deductions and rounding once would land on 70.65"
    assert receipt["weighted_moisture_pct"] == pytest.approx(14.50, abs=1e-6)
    assert receipt["weighted_contamination_pct"] == pytest.approx(5.00, abs=1e-6)


def test_surfactant_dose_denominator_is_guarded_at_one_ton():
    """PRD §3.3: "The **removal fraction** is the base removal of 0.35 plus 0.08
    multiplied by the surfactant dose per ton of furnish — where the dose is
    `surfactant_kg` divided by the larger of 1.000 and `charged_tons`, guarding
    against a divide-by-tiny on a token batch — the sum then multiplied by the
    effectiveness, the product capped at a maximum removal fraction of 0.95, and the
    result rounded half up to four decimal places."
    PRD §3.3: "The pass's **sludge tonnage** is `charged_tons` multiplied by an
    assumed ink load of 4.50 percent, divided by 100, multiplied by the removal
    fraction, rounded half up to three decimal places; that is the figure written
    into the appended `DEINK_SLUDGE` row."

    Design: Difficulty/combinatorial_formula/deink_removal_fraction_nested_min_max_with_unit_tonnage_guard
    """
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=2.00, max_moisture_pct=10.00,
                        nominal_yield_pct=72.00, deink_required=True,
                        downgrade_target_grade_code=None, rank_order=3)
    declare_tis_16(min_brightness_iso=80.0, rank_order=20)
    publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                  published_price_per_ton=150.00)
    supplier = register_supplier(name="Northgate Recovered", freight_per_ton=18.00)
    po = create_confirmed_po(supplier["id"], "DLK_37", contracted_tons=150.00,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                             negotiated_delta_per_ton=0.00)
    receipt = record_receipt(po["id"], [sublot(1, 2.000, 1.000, 8.00, 1.50)],
                             truck_reference="TRK-D-002")
    disposition(receipt["id"], "ACCEPT")
    lot = lots_of_receipt(receipt["id"])[0]
    assert lot["tons_received"] == pytest.approx(1.00, abs=1e-6)
    batch = queue_batch("TIS_16", [{"inventory_lot_id": lot["id"], "tons_charged": 0.800}],
                        pulper_line="DIP_LINE")
    drive_batch_to_cleaned(batch["id"], measured_reject_tons=0.200)

    after = validate_success(api_client.deink_pulp_batch(
        batch["id"], {"caustic_kg": 5.0, "peroxide_kg": 3.0, "surfactant_kg": 6.0},
        OPERATOR))

    assert after["status"] == "DEINKING"

    # PRD §3.3: "Brightness closes a deink pass" and both brightness outcomes
    # "share three side effects: `deink_pass_count` is incremented by one, the
    # pass's chemical cost is added into `cumulative_chemical_cost`, and one
    # solids-ledger row is appended with `source_kind` of `DEINK_SLUDGE`".
    closed = record_brightness(batch["id"], 82.0)

    assert closed["deink_pass_count"] == 1
    assert closed["cumulative_chemical_cost"] == pytest.approx(29.65, abs=1e-6)
    assert closed["provisional_accepted_tons"] == pytest.approx(0.554, abs=1e-6)
    rows = solids_rows(source_ref_id=batch["id"], source_kind="DEINK_SLUDGE")
    assert len(rows) == 1, f"one pass must append one sludge row, got {len(rows)}"
    assert rows[0]["dry_solids_tons"] == pytest.approx(0.030, abs=1e-6), \
        f"the max(1.000, 0.800) guard holds the dose at 6.0 so removal is 0.8300, got {rows[0]['dry_solids_tons']}"
    assert rows[0]["dry_solids_tons"] != pytest.approx(0.034, abs=1e-6), \
        "dropping the guard would saturate removal at the 0.95 ceiling"


def test_cogen_credit_rounds_each_band_before_summing_the_three():
    """PRD §3.8: "Each band's contribution is its tonnes per hour multiplied by its
    rate — 4.10 dollars per tonne-per-hour-hour for the first band, 6.75 for the
    second, 9.20 for the third — multiplied by the duration in hours, and **each
    band's product is rounded half up to four decimal places before the three are
    summed**; `cogen_credit_usd` is that sum rounded half up to two decimal places."
    PRD §3.8: "This per-band-then-total rounding order is pinned: summing the three
    unrounded products and rounding once produces a different cent on
    fractional-hour windows and is not the behaviour required."

    Design: Difficulty/combinatorial_formula/cogen_credit_per_tier_rounding_before_total
    """
    alloc = request_steam(consumer_kind="EVAPORATOR",
                          window_start="2026-08-01T06:00:00Z",
                          window_end="2026-08-01T06:35:00Z",
                          demand_tph=90.000, priority_rank=1)

    assert alloc["status"] == "GRANTED"
    assert alloc["granted_tph"] == pytest.approx(90.000, abs=1e-6)
    assert alloc["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert alloc["cogen_credit_usd"] == pytest.approx(350.86, abs=1e-6), \
        f"71.7459 + 118.1183 + 160.9908 must give 350.86, got {alloc['cogen_credit_usd']}"
    assert alloc["cogen_credit_usd"] != pytest.approx(350.85, abs=1e-6), \
        "rounding only the total would land on 350.85"


def test_thirty_five_minute_window_duration_is_pinned_to_four_decimals():
    """PRD §3.8: "The window's `duration_hours` is its length in seconds divided by
    3600, rounded half up to four decimal places."
    PRD §3.8: "The exportable rate is 180.000 minus the consumed figure minus this
    allocation's own `granted_tph`, floored at 0.000 and rounded half up to three
    decimal places."

    Design: Difficulty/combinatorial_formula/cogen_credit_per_tier_rounding_before_total
    """
    alloc = request_steam(consumer_kind="EVAPORATOR",
                          window_start="2026-08-01T06:00:00Z",
                          window_end="2026-08-01T06:35:00Z",
                          demand_tph=90.000, priority_rank=1)
    fetched = get_success_data(api_client.get_steam_allocation(alloc["id"], ENERGY))

    assert fetched["cogen_credit_usd"] == pytest.approx(350.86, abs=1e-6), \
        "the credit is durable, not recomputed per read"
    assert fetched["granted_tph"] == pytest.approx(90.000, abs=1e-6), \
        "an empty header grants the full demand, leaving 90.000 tph exportable"
