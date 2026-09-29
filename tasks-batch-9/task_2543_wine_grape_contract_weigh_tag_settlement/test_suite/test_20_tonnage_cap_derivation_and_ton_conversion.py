"""Where the tonnage numbers come from. Pounds become tons at one constant divisor and one
rounding rule, and the ceiling a contract may deliver against is derived from a different
source on each of the three commercial bases.
"""
from test_helpers import (
    MANAGER,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    capture_tare,
    create_allocation,
    create_block,
    create_contract,
    create_crew,
    create_lane,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_allocation,
    read_appointment,
    read_settlement_summary,
    read_weigh_tag,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SLOT_TONS = 40.000
TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"

# 61240 - 17240 = 44000 lbs, which is exactly 22.000 tons at 2000 lbs per ton.
EVEN_GROSS_LBS = 61240
EVEN_TARE_LBS = 17240
# 50123 - 17000 = 33123 lbs, which is 16.5615 tons before rounding.
ODD_GROSS_LBS = 50123
ODD_TARE_LBS = 17000

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BIG_BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SMALL_BLOCK = {
    "block_code": "B-13",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 10.000,
    "expected_yield_tons_per_acre": 1.500,
    "ava_code": "NAPA-VALLEY",
}
LANE = {
    "lane_code": "L1",
    "daily_capacity_tons": 80.000,
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.0,
}


# --- Pounds into tons, once per load ------------------------------------------------


def _two_trucks_against_one_slot() -> dict:
    """An ACTIVE TONNAGE contract with a 40.000-ton slot on lane L1 and the clock inside the
    slot's window, ready to take two loads."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BIG_BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["lane"] = create_lane(**LANE)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-CONVERT",
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], SAMPLING_WINDOW[0], SAMPLING_WINDOW[1]
    )
    record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    call = issue_pick_call(contract["id"], ctx["block"]["id"], TARGET_PICK_AT, 45.000)
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], SLOT_TONS
    )

    move_clock(TRUCK_ARRIVES_AT)
    return ctx


def _both_loads_weighed_out(ctx: dict) -> dict:
    """The even load first, then the odd one against a refreshed slot token; both tared."""
    first = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        EVEN_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    ctx["token_after_the_first_tag"] = appointment_version(ctx["appointment"]["id"])
    ctx["first"] = capture_tare(first["id"], EVEN_TARE_LBS)

    second = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        ODD_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    ctx["second"] = capture_tare(second["id"], ODD_TARE_LBS)
    return ctx


def test_a_load_that_divides_evenly_lands_on_whole_thousandths():
    """44000 pounds is 22 tons exactly, so the rounding rule has nothing to do and the
    stored net weight is still a whole number of pounds.

    PRD: "The conversion is then trivial and exact: `net_weight_lbs` is `gross_weight_lbs`
    less `tare_weight_lbs`, a whole number of pounds; and `net_tons` is `net_weight_lbs`
    divided by 2000 pounds per ton, rounded half up to 3 decimals."

    Design: Corner/calculations/net_weight_conversion_honours_three_decimal_ton_rounding
    """
    ctx = _both_loads_weighed_out(_two_trucks_against_one_slot())

    assert ctx["first"]["net_weight_lbs"] == 44000
    assert float(ctx["first"]["net_tons"]) == 22.000


def test_a_load_that_lands_on_a_half_thousandth_rounds_up_not_down():
    """33123 pounds over the constant 2000 is 16.5615 tons, and the third decimal is settled
    half up — 16.562 — where truncation would have quietly shaved a ton-thousandth off the
    producer's cheque.

    PRD: "**Tonnage** is carried to exactly 3 decimal places and rounded half up. This applies
    to derived caps (`contract_cap_tons`, `hard_cap_tons`, `block_cap_tons`,
    `block_hard_cap_tons`), to the converted net weight (`net_tons`), to every tonnage slice on
    a weigh tag, to the tonnage on a settlement line, and to every delivered-tonnage rollup."

    Design: Corner/calculations/net_weight_conversion_honours_three_decimal_ton_rounding
    """
    ctx = _both_loads_weighed_out(_two_trucks_against_one_slot())

    assert ctx["second"]["net_weight_lbs"] == 33123
    assert float(ctx["second"]["net_tons"]) == 16.562


def test_the_conversion_settles_the_weight_and_decides_nothing_else():
    """Both loads have finished the weight dimension and neither has been looked at by the
    lab, so no tonnage has been poured into any bucket yet.

    PRD: "The tare also recomputes the appointment's `captured_net_tons`, and it leaves the
    receipt-decision dimension untouched at `PENDING`. `NET_FINAL` is the terminal state of the
    weight dimension."

    Design: Corner/calculations/net_weight_conversion_honours_three_decimal_ton_rounding
    """
    ctx = _both_loads_weighed_out(_two_trucks_against_one_slot())

    for tag in (ctx["first"], ctx["second"]):
        assert tag["weigh_status"] == "NET_FINAL"
        assert tag["disposition"] == "PENDING"
        assert float(read_weigh_tag(tag["id"])["contract_slice_tons"]) == 0.000


def test_the_slot_arrives_on_the_first_load_and_counts_the_second():
    """One slot legitimately takes several trucks: the first presentation moves the slot to
    arrived and the second only adds to the count.

    PRD: "The first weigh tag presented against a scheduled appointment drives `SCHEDULED →
    ARRIVED` as the tag's `weigh_tag_count` moves from 0 to 1."

    Design: Corner/calculations/net_weight_conversion_honours_three_decimal_ton_rounding
    """
    ctx = _two_trucks_against_one_slot()
    capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        EVEN_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    assert read_appointment(ctx["appointment"]["id"])["status"] == "ARRIVED"

    capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        ODD_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    slot = read_appointment(ctx["appointment"]["id"])
    assert slot["status"] == "ARRIVED"
    assert slot["weigh_tag_count"] == 2


def test_the_second_truck_had_to_present_a_refreshed_slot_token():
    """Presenting a load mutates the slot, so the token the scale house held for the first
    truck is no longer the one the second must quote.

    PRD: "The appointment's `weigh_tag_count` is recomputed and the appointment itself is
    mutated, so its `version` advances — which is precisely why the next tag against the same
    slot must carry the newer `expected_appointment_version`."

    Design: Corner/calculations/net_weight_conversion_honours_three_decimal_ton_rounding
    """
    ctx = _two_trucks_against_one_slot()
    token_before_any_truck = appointment_version(ctx["appointment"]["id"])

    _both_loads_weighed_out(ctx)
    assert ctx["token_after_the_first_tag"] > token_before_any_truck
    assert float(read_appointment(ctx["appointment"]["id"])["captured_net_tons"]) == 38.562


# --- The acreage basis reads the allocations, not the blocks -------------------------


def _a_producer_with_two_blocks() -> dict:
    """One producer with a 20.000-acre block yielding 2.000 t/acre and a 10.000-acre block
    yielding 1.500 — deliberately different from anything the allocations will carry."""
    move_clock(CLOCK_PINNED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BIG_BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["small_block"] = create_block(ctx["grower"]["id"], **SMALL_BLOCK)
    return ctx


def _an_accepted_acreage_contract(api) -> dict:
    """An ACREAGE contract at 2.500 contracted tons per acre with 10.500 and 4.250 acres
    allocated off the two blocks."""
    ctx = _a_producer_with_two_blocks()
    contract = validate_success(
        api.create_grape_contract(
            {
                "grower_id": ctx["grower"]["id"],
                "quality_spec_id": ctx["spec"]["id"],
                "contract_code": "GC-ACREAGE",
                "contract_basis": "ACREAGE",
                "contracted_yield_tons_per_acre": 2.500,
                "base_price_per_ton_cents": 450000,
                "over_delivery_policy": "ACCEPT_AT_CONTRACT",
                "term_start_vintage": 2026,
                "term_end_vintage": 2026,
                "installment_plan": single_installment_plan(),
            },
            MANAGER,
        ),
        201,
    )
    ctx["big_allocation"] = create_allocation(
        contract["id"], ctx["block"]["id"], allocated_acres=10.500
    )
    ctx["small_allocation"] = create_allocation(
        contract["id"], ctx["small_block"]["id"], allocated_acres=4.250
    )
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def test_the_acreage_cap_is_the_allocated_acreage_times_the_contracted_yield(api):
    """10.500 plus 4.250 allocated acres at 2.500 contracted tons apiece is 36.875 tons — not
    the 75.000 the two blocks' own acreage and their own expected yields would have produced.

    PRD: "On an `ACREAGE` contract the allocated acreage of every block allocation of the
    contract is summed, that total is multiplied by `contracted_yield_tons_per_acre`, and the
    product is rounded half up to 3 decimals; `cap_scope` is again `PER_CONTRACT`."

    Design: Corner/calculations/acreage_basis_cap_sums_allocated_acres_times_contracted_yield
    """
    ctx = _an_accepted_acreage_contract(api)

    assert float(ctx["contract"]["contract_cap_tons"]) == 36.875
    assert ctx["contract"]["cap_scope"] == "PER_CONTRACT"


def test_the_tolerance_band_on_the_acreage_cap_rounds_half_up(api):
    """36.875 tons plus the house 10 percent is 40.5625, and the third decimal is settled
    upwards to 40.563.

    PRD: "In every case, `hard_cap_tons` is `contract_cap_tons` multiplied by one plus
    `over_delivery_tolerance_pct` divided by 100, rounded half up to 3 decimals."

    Design: Corner/calculations/acreage_basis_cap_sums_allocated_acres_times_contracted_yield
    """
    ctx = _an_accepted_acreage_contract(api)

    assert float(ctx["contract"]["hard_cap_tons"]) == 40.563


def test_an_acreage_contract_holds_no_committed_tonnage_of_its_own(api):
    """The basis forbids the tonnage field, which is what leaves the allocation sum as the
    only possible source of the cap.

    PRD: "an `ACREAGE` contract requires `contracted_yield_tons_per_acre` and must not carry
    `committed_tons`"

    Design: Corner/calculations/acreage_basis_cap_sums_allocated_acres_times_contracted_yield
    """
    ctx = _an_accepted_acreage_contract(api)

    assert ctx["contract"]["committed_tons"] is None
    assert float(ctx["contract"]["contracted_yield_tons_per_acre"]) == 2.500


def test_the_acreage_allocations_keep_their_acres_and_no_caps_of_their_own(api):
    """The cap is contract-wide, so each allocation still reports the acreage it committed and
    carries no per-block ceiling.

    PRD: "On `PER_CONTRACT` contracts the per-allocation `block_cap_tons` and
    `block_hard_cap_tons` remain null."

    Design: Corner/calculations/acreage_basis_cap_sums_allocated_acres_times_contracted_yield
    """
    ctx = _an_accepted_acreage_contract(api)

    big = read_allocation(ctx["big_allocation"]["id"])
    assert float(big["allocated_acres"]) == 10.500
    assert big["block_cap_tons"] is None
    assert big["block_hard_cap_tons"] is None


def test_the_reconciliation_read_reports_the_derived_acreage_caps(api):
    """The summary is the same derivation seen from the money side, with nothing delivered
    against it yet.

    PRD: "It returns `contract_cap_tons`, `hard_cap_tons`, `cap_scope`,
    `delivered_contract_tons`, `delivered_over_tons`, `rejected_tons`, `tonnage_status`,
    `settlement_basis`, `provisional_settlement_cents`, `final_settlement_cents`,
    `prompt_pay_credit_cents`, `lien_holdback_cents`, `net_payable_cents`"

    Design: Corner/calculations/acreage_basis_cap_sums_allocated_acres_times_contracted_yield
    """
    ctx = _an_accepted_acreage_contract(api)

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert float(summary["contract_cap_tons"]) == 36.875
    assert float(summary["hard_cap_tons"]) == 40.563
    assert summary["cap_scope"] == "PER_CONTRACT"
    assert float(summary["delivered_contract_tons"]) == 0.000


# --- The block basis gives every block its own ceiling ------------------------------


def _an_accepted_block_contract(api) -> dict:
    """A BLOCK-basis contract over both blocks, carrying neither tonnage field."""
    ctx = _a_producer_with_two_blocks()
    contract = validate_success(
        api.create_grape_contract(
            {
                "grower_id": ctx["grower"]["id"],
                "quality_spec_id": ctx["spec"]["id"],
                "contract_code": "GC-BLOCK",
                "contract_basis": "BLOCK",
                "base_price_per_ton_cents": 450000,
                "over_delivery_policy": "ACCEPT_AT_CONTRACT",
                "term_start_vintage": 2026,
                "term_end_vintage": 2026,
                "installment_plan": single_installment_plan(),
            },
            MANAGER,
        ),
        201,
    )
    ctx["big_allocation"] = create_allocation(contract["id"], ctx["block"]["id"])
    ctx["small_allocation"] = create_allocation(contract["id"], ctx["small_block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def test_the_block_basis_is_the_only_one_that_scopes_the_caps_per_block(api):
    """Acceptance sets the scope that later decides which ceiling the delivery waterfall
    consumes.

    PRD: "`cap_scope` is set to `PER_BLOCK` when `contract_basis` is `BLOCK` and to
    `PER_CONTRACT` otherwise."

    Design: Corner/calculations/block_basis_cap_is_derived_per_block_and_summed
    """
    ctx = _an_accepted_block_contract(api)

    assert ctx["contract"]["cap_scope"] == "PER_BLOCK"


def test_each_block_allocation_carries_its_own_cap_and_its_own_band(api):
    """20.000 acres at 2.000 gives 40.000 with a band of 44.000; 10.000 acres at 1.500 gives
    15.000 with a band of 16.500 — each block's own 10 percent, not a share of the contract's.

    PRD: "for every allocation, `block_cap_tons` becomes the block's `acres` multiplied by its
    `expected_yield_tons_per_acre`, rounded half up to 3 decimals, and `block_hard_cap_tons`
    becomes that block cap multiplied by one plus `over_delivery_tolerance_pct` divided by 100,
    again rounded half up to 3 decimals"

    Design: Corner/calculations/block_basis_cap_is_derived_per_block_and_summed
    """
    ctx = _an_accepted_block_contract(api)

    big = read_allocation(ctx["big_allocation"]["id"])
    assert float(big["block_cap_tons"]) == 40.000
    assert float(big["block_hard_cap_tons"]) == 44.000

    small = read_allocation(ctx["small_allocation"]["id"])
    assert float(small["block_cap_tons"]) == 15.000
    assert float(small["block_hard_cap_tons"]) == 16.500


def test_the_contract_ceiling_is_the_sum_of_the_block_ceilings(api):
    """The contract-level figures are pinned separately from the per-block ones: 55.000 is the
    sum of the caps and 60.500 is the band applied to that sum.

    PRD: "the contract-level `contract_cap_tons` is the sum of the per-block caps, rounded half
    up to 3 decimals, and `cap_scope` is `PER_BLOCK`."

    Design: Corner/calculations/block_basis_cap_is_derived_per_block_and_summed
    """
    ctx = _an_accepted_block_contract(api)

    assert float(ctx["contract"]["contract_cap_tons"]) == 55.000
    assert float(ctx["contract"]["hard_cap_tons"]) == 60.500


def test_a_block_basis_contract_carries_neither_tonnage_field(api):
    """Neither the committed tonnage nor the contracted yield is admissible here, and the
    allocations carry no acreage either — so the caps can only have come from the blocks.

    PRD: "a `BLOCK` contract must carry neither."

    Design: Corner/calculations/block_basis_cap_is_derived_per_block_and_summed
    """
    ctx = _an_accepted_block_contract(api)

    assert ctx["contract"]["committed_tons"] is None
    assert ctx["contract"]["contracted_yield_tons_per_acre"] is None
    assert read_allocation(ctx["big_allocation"]["id"])["allocated_acres"] is None
