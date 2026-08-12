"""Settlements: rounding order, fee tiering, late interest (PRD §3.6)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_verified_ticket,
    create_scale_ticket_payload,
    create_settlement_payload,
    setup_contract_harvesting,
    setup_per_unit_settlement_draft,
    setup_sale_awarded,
)

ADMIN = TEST_USERS["admin_headers"]


def test_per_unit_settlement_rounding_order(api):
    """PRD §3.6: "`gross_cents` is the sum over them of the winning bid's
    per-species rate applied to each ticket's `bf_governing` divided by 1000 —
    each ticket line rounded half up to whole cents *before* the lines are
    summed, never sum-then-round."

    Design: Difficulty/combinatorial_formula/per_unit_settlement_rounding_order
    """
    # Rate 45555/MBF, two tickets of 100 bf each.
    # Per-ticket line = round_half_up(45555 * 100 / 1000) = round_half_up(4555.5) = 4556.
    # Gross = 4556 + 4556 = 9112 (sum-then-round would be 9111).
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_555}],
                       "deposit_cents": 100_000},
    )
    add_verified_ticket(base, scaled_date="2026-06-20", log_count=1)
    add_verified_ticket(base, scaled_date="2026-06-21", log_count=1)
    fh = base["forester_headers"]
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-09-01"),
        fh,
    ), 201)
    assert settlement["gross_cents"] == 9112, (
        f"per-ticket-round-then-sum yields 9112, got {settlement['gross_cents']}"
    )
    assert settlement["gross_cents"] != 9111
    assert settlement["holdback_cents"] == 911
    assert settlement["fee_cents"] == 729
    assert settlement["net_cents"] == 7472


def test_per_unit_settlement_rounding_per_ticket_lines(api):
    """PRD §3.6: "each ticket line rounded half up to whole cents *before*
    the lines are summed, never sum-then-round."

    Design: Difficulty/combinatorial_formula/per_unit_settlement_rounding_order
    """
    # Verify rounding occurs per ticket: single ticket of 100 bf at 45555 -> 4556.
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_555}],
                       "deposit_cents": 100_000},
    )
    add_verified_ticket(base, scaled_date="2026-06-20", log_count=1)
    fh = base["forester_headers"]
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-09-01"),
        fh,
    ), 201)
    assert settlement["gross_cents"] == 4556


def test_consulting_fee_tier_keyed_on_cumulative_gross(api):
    """PRD §3.6: "first form the tentative billed total as the contract's
    `billed_total_cents` before this settlement plus this settlement's
    `gross_cents`; then select the tier from that tentative figure — 8.0
    percent when it is at most 5,000,000 cents, 6.5 percent when it is at
    most 20,000,000 cents, and 5.0 percent above that; then `fee_cents` is
    this settlement's gross multiplied by the tier percentage, rounded half
    up."

    Design: Difficulty/combinatorial_formula/consulting_fee_tier_keyed_on_cumulative_gross
    """
    # Rate 50000/MBF; settlement 1: 98000 bf ticket -> gross 4900000 (tier 8%).
    # Settlement 2: 4000 bf ticket -> gross 200000; tentative = 5100000 -> tier 6.5%.
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 50_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    # One 980-log ticket = 98000 bf -> gross 98000*50000/1000 = 4900000.
    tk1 = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-10", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=980),
        ch,
    ))
    get_success_data(api.verify_scale_ticket(tk1["id"], fh))
    stl1 = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    ), 201)
    assert stl1["gross_cents"] == 4_900_000
    assert stl1["fee_cents"] == 392_000

    # Second ticket: 40 logs = 4000 bf -> gross 200000.
    tk2 = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-07-10", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=40),
        ch,
    ))
    get_success_data(api.verify_scale_ticket(tk2["id"], fh))
    stl2 = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-07-01",
                                  period_end="2026-08-01"),
        fh,
    ), 201)
    assert stl2["gross_cents"] == 200_000
    # Tier keyed on tentative billed 5100000 -> 6.5% fee.
    assert stl2["fee_cents"] == 13_000
    assert stl2["fee_cents"] != 16_000
    # holdback = 20000, fee = 13000, net = 200000 - 20000 - 13000 = 167000.
    assert stl2["net_cents"] == 167_000


def test_consulting_fee_tier1_boundary(api):
    """PRD §3.6: "8.0 percent when it is at most 5,000,000 cents, 6.5 percent
    when it is at most 20,000,000 cents, and 5.0 percent above that".

    Design: Difficulty/combinatorial_formula/consulting_fee_tier_keyed_on_cumulative_gross
    """
    # A small settlement keeps cumulative billed under 5M -> tier 8%.
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 50_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    # 100 bf ticket -> gross 5000 -> fee 8% = 400.
    tk = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-10", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=1),
        ch,
    ))
    get_success_data(api.verify_scale_ticket(tk["id"], fh))
    stl = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    ), 201)
    assert stl["gross_cents"] == 5_000
    assert stl["fee_cents"] == 400


def test_lump_sum_vs_per_unit_settlement_divergence(api):
    """PRD §3.6: "Mobilization and midpoint each pay forty percent of
    `awarded_value_cents`, rounded half up; mobilization requires the contract
    to be `HARVESTING`".
    PRD §3.6: "`gross_cents` is the sum over them of the winning bid's
    per-species rate applied to each ticket's `bf_governing` divided by 1000".

    Design: Difficulty/dual_variant_calc/lump_sum_vs_per_unit_settlement_divergence
    """
    # PER_UNIT contract: 3 verified tickets of 1000/1000/500 bf at 45000/MBF.
    per_unit = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    stl_per_unit = per_unit["settlement"]
    assert stl_per_unit["gross_cents"] == 112_500
    assert stl_per_unit["holdback_cents"] == 11_250
    assert stl_per_unit["fee_cents"] == 9_000
    assert stl_per_unit["net_cents"] == 92_250

    # LUMP_SUM contract: awarded 9000001, MOBILIZATION milestone.
    # Default harvest window (2026-06-01..2026-10-01) and start clock
    # (2026-06-15) are used so the harvest start falls inside both the sale's
    # harvest window and the prescription window (PRD §3.5 start-harvest gate).
    lump = setup_contract_harvesting(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 8_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 9_000_001, "deposit_cents": 200_000},
    )
    fh_l = lump["forester_headers"]
    stl_lump = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=lump["contract"]["id"],
                                  kind="LUMP_MILESTONE",
                                  milestone="MOBILIZATION"),
        fh_l,
    ), 201)
    # 40% of 9000001 = 3600000.4 -> round_half_up -> 3600000.
    assert stl_lump["gross_cents"] == 3_600_000
    assert stl_lump["holdback_cents"] == 0
    assert stl_lump["gross_cents"] != stl_per_unit["gross_cents"]


def test_lump_milestone_sequence_and_completion_remainder(api):
    """PRD §3.6: "Mobilization and midpoint each pay forty percent of
    `awarded_value_cents`, rounded half up; mobilization requires the contract
    to be `HARVESTING`, while midpoint additionally requires
    `cumulative_verified_bf` to have reached at least half of the certified
    total volume, the half itself rounded half up to whole board feet.
    Completion pays the remainder — the awarded value minus the mobilization
    and midpoint grosses — and requires the contract to be `HARVEST_COMPLETE`."

    Design: Corner/calculations/lump_milestone_sequence_and_completion_remainder
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 8_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 9_000_001, "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    ch = base["contractor_headers"]

    m1 = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="LUMP_MILESTONE", milestone="MOBILIZATION"),
        fh,
    ), 201)
    assert m1["gross_cents"] == 3_600_000
    assert m1["fee_cents"] == 288_000

    # 1501 logs at 100 bf each -> cumulative 150100 >= round_half_up(300125*0.5) = 150063.
    tk = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=1501),
        ch,
    ))
    get_success_data(api.verify_scale_ticket(tk["id"], fh))

    m2 = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="LUMP_MILESTONE", milestone="MIDPOINT"),
        fh,
    ), 201)
    assert m2["gross_cents"] == 3_600_000
    # cumulative billed = 7200000 -> tier 6.5%.
    assert m2["fee_cents"] == 234_000

    get_success_data(api.complete_harvest(base["contract"]["id"], ch))
    m3 = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="LUMP_MILESTONE", milestone="COMPLETION"),
        fh,
    ), 201)
    # 9000001 - 3600000 - 3600000 = 1800001.
    assert m3["gross_cents"] == 1_800_001
    # cumulative billed = 10800001 -> tier 6.5%.
    assert m3["fee_cents"] == 117_000
    assert 3_600_000 + 3_600_000 + 1_800_001 == 9_000_001


def test_settlement_empty_period_zero_sweep(api):
    """PRD §3.6: "A period that sweeps no eligible ticket at all is refused
    with `ERR_SETTLEMENT_PERIOD_EMPTY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/settlement_empty_period_zero_sweep
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    resp = api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_EMPTY)


def test_settlement_period_overlap_rejected(api):
    """PRD §3.6: "the period may not overlap the period of any existing
    non-`VOID` period settlement on the same contract
    (`ERR_SETTLEMENT_PERIOD_OVERLAP`, HTTP 422), and touching endpoints do not
    overlap."

    Design: Corner/validations/settlement_period_overlap_rejected
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    add_verified_ticket(base, scaled_date="2026-06-16", log_count=1)
    get_success_data(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    ))
    resp = api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-15",
                                  period_end="2026-07-15"),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP)


def test_late_interest_floor_at_29_and_accrual_at_61_days(api):
    """PRD §3.6: "whenever an `APPROVED` settlement is fetched or listed and
    the clock's date has passed `due_date`, `accrued_interest_cents` is
    computed on the fly as simple interest on the net — the number of whole
    30-day periods contained in the days late, times 1.5 percent of
    `net_cents` per period, the final product rounded down to whole cents.
    Negative days late count as zero, no compounding occurs, and a payment 29
    days late accrues nothing at all."

    Design: Corner/calculations/late_interest_floor_at_29_and_accrual_at_61_days
    """
    base = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    settlement = base["settlement"]
    assert settlement["net_cents"] == 92_250

    # Approve at 2026-06-20 -> due 2026-07-20.
    get_success_data(api.set_clock({"to_iso8601": "2026-06-20T00:00:00Z"}, ADMIN))
    settlement = validate_success(api.approve_settlement(settlement["id"], lh))
    assert settlement["due_date"] == "2026-07-20"

    # 29 days late -> 0.
    get_success_data(api.set_clock({"to_iso8601": "2026-08-18T00:00:00Z"}, ADMIN))
    s29 = get_success_data(api.get_settlement(settlement["id"], fh))
    assert s29["accrued_interest_cents"] == 0

    # 30 days late -> floor(92250 * 0.015 * 1) = floor(1383.75) = 1383.
    get_success_data(api.set_clock({"to_iso8601": "2026-08-19T00:00:00Z"}, ADMIN))
    s30 = get_success_data(api.get_settlement(settlement["id"], fh))
    assert s30["accrued_interest_cents"] == 1383

    # 61 days late -> floor(92250 * 0.015 * 2) = floor(2767.5) = 2767.
    get_success_data(api.set_clock({"to_iso8601": "2026-09-19T00:00:00Z"}, ADMIN))
    s61 = get_success_data(api.get_settlement(settlement["id"], fh))
    assert s61["accrued_interest_cents"] == 2767


def test_disburse_refund_transfer_conservation(api):
    """PRD §3.6: "Disbursement by a forester moves `APPROVED → PAID` and adds
    `net_cents` into the contract's `disbursed_total_cents`. A payment made
    in error is unwound by refunding: `PAID → REFUNDED` subtracts `net_cents`
    from `disbursed_total_cents` and adds it to `refunded_total_cents`, a
    compensating move that keeps the sum of disbursed and refunded conserved."

    Design: Difficulty/compensating_invariant/disburse_refund_transfer_conservation
    """
    base = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    settlement = base["settlement"]
    assert settlement["net_cents"] == 92_250
    get_success_data(api.approve_settlement(settlement["id"], lh))

    get_success_data(api.disburse_settlement(settlement["id"], fh))
    contract1 = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract1["disbursed_total_cents"] == 92_250
    assert contract1["refunded_total_cents"] == 0

    get_success_data(api.refund_settlement(settlement["id"], fh))
    contract2 = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract2["disbursed_total_cents"] == 0
    assert contract2["refunded_total_cents"] == 92_250
    # Conservation invariant: disbursed + refunded unchanged.
    assert (contract1["disbursed_total_cents"] + contract1["refunded_total_cents"]) == \
           (contract2["disbursed_total_cents"] + contract2["refunded_total_cents"]) == 92_250
    # billed and holdback are untouched by refund.
    assert contract2["holdback_balance_cents"] == 11_250
    assert contract2["billed_total_cents"] == 112_500


def test_disburse_moves_net_into_disbursed(api):
    """PRD §3.6: "Disbursement by a forester moves `APPROVED → PAID` and adds
    `net_cents` into the contract's `disbursed_total_cents`."

    Design: Difficulty/compensating_invariant/disburse_refund_transfer_conservation
    """
    base = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    settlement = base["settlement"]
    get_success_data(api.approve_settlement(settlement["id"], lh))
    get_success_data(api.disburse_settlement(settlement["id"], fh))
    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["disbursed_total_cents"] == settlement["net_cents"]
    assert contract["refunded_total_cents"] == 0
