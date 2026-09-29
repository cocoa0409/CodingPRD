"""The auditable premium build-up on a quote.

Pricing runs in two stages whose internal order is pinned: the technical premium
out of banded exposure, the entity-securities load and the stepped retention
credit; then the gross-up, the residual commission and the surplus lines tax.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    THREE_EVENT_HISTORY,
    THREE_PACKAGE_HISTORY,
    UNDERWRITER,
    assert_premium_stack,
    assert_quote,
    create_quote_payload,
    open_submission,
    read_submission,
    run_scoring,
    setup_insured_with_history,
)


def _scored_submission(insured_id, **submission_overrides):
    submission = open_submission(insured_id, **submission_overrides)
    return run_scoring(submission["id"], "INDICATIVE")


def test_offered_limit_is_decomposed_across_the_four_increased_limit_bands(api):
    """PRD 3.3: the exposure measure "sums, across four increased-limit bands, the
    amount of limit falling in the band expressed in millions of dollars
    multiplied by the band's factor: the first 5,000,000 of limit at a factor of
    1.00, the next 5,000,000 at 0.65, the next 10,000,000 at 0.45, and everything
    above 20,000,000 at 0.30." A 20,000,000 limit therefore measures
    5 + 3.25 + 4.5 = 12.75 units, never a flat 20.00.

    Design: Difficulty/combinatorial_formula/premium_tiered_ilf_bands_and_capped_retention_credit
    """
    scenario = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 40_000_000}
    )
    submission = _scored_submission(
        scenario["insured"]["id"],
        requested_limit_usd=20_000_000,
        requested_retention_usd=500_000,
        requested_side_c_sublimit_usd=20_000_000,
        requested_program_target_limit_usd=20_000_000,
    )

    response = api.create_quote(
        submission["id"],
        create_quote_payload(
            submission["version"],
            offered_limit_usd=20_000_000,
            offered_retention_usd=500_000,
            offered_side_c_sublimit_usd=20_000_000,
        ),
        UNDERWRITER,
    )

    data = validate_success(response, 201)
    assert_quote(data)
    assert data["risk_band_at_quote"] == "ELEVATED"
    # 22,000 x 12.75 x 1.20 (LISTED Side C load) x 0.90 (two retention blocks).
    assert data["net_premium_usd"] == pytest.approx(302_940.00, abs=0.01)
    assert data["gross_premium_usd"] == pytest.approx(346_217.14, abs=0.01)
    assert data["broker_commission_usd"] == pytest.approx(43_277.14, abs=0.01)
    assert data["premium_tax_usd"] == pytest.approx(12_117.60, abs=0.01)
    assert data["total_payable_usd"] == pytest.approx(358_334.74, abs=0.01)
    assert_premium_stack(data)
    assert read_submission(submission["id"])["status"] == "QUOTED"


def test_retention_credit_is_held_to_its_thirty_five_percent_cap(api):
    """PRD 3.3: "The retention credit is the lesser of 0.35 and 0.05 multiplied by
    the number of whole 250,000 blocks in `offered_retention_usd`, the block count
    being the quotient discarding any remainder." A 4,000,000 retention counts
    sixteen blocks for an uncapped 0.80, so the cap is what keeps the premium at
    22,000 x 8.25 x 1.20 x 0.65.

    Design: Difficulty/combinatorial_formula/premium_tiered_ilf_bands_and_capped_retention_credit
    """
    scenario = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 40_000_000}
    )
    submission = _scored_submission(
        scenario["insured"]["id"],
        requested_limit_usd=10_000_000,
        requested_retention_usd=4_000_000,
        requested_side_c_sublimit_usd=5_000_000,
        requested_program_target_limit_usd=10_000_000,
    )

    response = api.create_quote(
        submission["id"],
        create_quote_payload(
            submission["version"],
            offered_limit_usd=10_000_000,
            offered_retention_usd=4_000_000,
            offered_side_c_sublimit_usd=5_000_000,
        ),
        UNDERWRITER,
    )

    data = validate_success(response, 201)
    assert data["net_premium_usd"] == pytest.approx(141_570.00, abs=0.01)
    assert data["gross_premium_usd"] == pytest.approx(161_794.29, abs=0.01)
    assert data["broker_commission_usd"] == pytest.approx(20_224.29, abs=0.01)
    assert data["premium_tax_usd"] == pytest.approx(5_662.80, abs=0.01)
    assert data["total_payable_usd"] == pytest.approx(167_457.09, abs=0.01)
    assert_premium_stack(data)
    assert read_submission(submission["id"])["status"] == "QUOTED"


def test_gross_premium_is_the_net_divided_by_one_less_the_commission_rate(api):
    """PRD 3.3: "the broker commission is a percentage of the gross premium, while
    the gross premium is the net plus that commission. The pinned order resolves
    it. First, `gross_premium_usd` is `net_premium_usd` divided by one minus the
    commission rate of 0.125, rounded half-up to 2 decimal places." "Multiplying
    the net by one plus the commission rate is not an acceptable substitute: it
    under-collects, and it leaves net plus commission unequal to gross."

    Design: Difficulty/combinatorial_formula/commission_grossup_circular_order
    """
    scenario = setup_insured_with_history(
        package_overrides=THREE_PACKAGE_HISTORY,
        litigation_overrides=THREE_EVENT_HISTORY,
    )
    submission = run_scoring(
        open_submission(scenario["insured"]["id"])["id"], "UNDERWRITTEN"
    )

    response = api.create_quote(
        submission["id"], create_quote_payload(submission["version"]), UNDERWRITER
    )

    data = validate_success(response, 201)
    assert data["risk_band_at_quote"] == "SEVERE"
    assert data["net_premium_usd"] == pytest.approx(319_770.00, abs=0.01)
    assert data["gross_premium_usd"] == pytest.approx(365_451.43, abs=0.01)
    assert data["gross_premium_usd"] != pytest.approx(359_741.25, abs=0.01), (
        "the multiplicative shortcut net x 1.125 under-collects"
    )


def test_commission_is_the_residual_and_the_tax_is_charged_on_the_gross(api):
    """PRD 3.3: "Second, `broker_commission_usd` is taken as the residual —
    `gross_premium_usd` less `net_premium_usd` — so that net and commission always
    add back to gross exactly. Third, `premium_tax_usd` is the surplus lines tax
    of 0.035 applied to the already-rounded gross premium, never to the net,
    rounded half-up to 2 decimal places. Fourth, `total_payable_usd` is
    `gross_premium_usd` plus `premium_tax_usd`."

    Design: Difficulty/combinatorial_formula/commission_grossup_circular_order
    """
    scenario = setup_insured_with_history(
        package_overrides=THREE_PACKAGE_HISTORY,
        litigation_overrides=THREE_EVENT_HISTORY,
    )
    submission = run_scoring(
        open_submission(scenario["insured"]["id"])["id"], "UNDERWRITTEN"
    )

    data = validate_success(
        api.create_quote(
            submission["id"], create_quote_payload(submission["version"]), UNDERWRITER
        ),
        201,
    )

    assert data["broker_commission_usd"] == pytest.approx(45_681.43, abs=0.01)
    assert data["broker_commission_usd"] != pytest.approx(39_971.25, abs=0.01), (
        "net x 0.125 does not close the net + commission == gross identity"
    )
    assert data["premium_tax_usd"] == pytest.approx(12_790.80, abs=0.01)
    assert data["premium_tax_usd"] != pytest.approx(11_191.95, abs=0.01), (
        "the surplus lines tax is charged on the gross, never on the net"
    )
    assert data["total_payable_usd"] == pytest.approx(378_242.23, abs=0.01)
    assert_premium_stack(data)


def test_retention_credit_does_not_move_until_the_exact_block_multiple(api):
    """PRD 3.3: the credit counts "the number of whole 250,000 blocks in
    `offered_retention_usd`, the block count being the quotient discarding any
    remainder." One cent short of the first multiple therefore earns no credit at
    all, and the base premium passes through untouched.

    Design: Difficulty/boundary_precision_check/retention_credit_step_at_exact_block_multiple
    """
    scenario = setup_insured_with_history()
    insured_id = scenario["insured"]["id"]

    below = _scored_submission(
        insured_id, requested_retention_usd=249_999.99,
        requested_side_c_sublimit_usd=0, requested_program_target_limit_usd=10_000_000,
    )
    at_multiple = _scored_submission(
        insured_id, requested_retention_usd=250_000.00,
        requested_side_c_sublimit_usd=0, requested_program_target_limit_usd=10_000_000,
    )

    below_quote = validate_success(
        api.create_quote(
            below["id"],
            create_quote_payload(below["version"], offered_retention_usd=249_999.99,
                                 offered_side_c_sublimit_usd=0),
            UNDERWRITER,
        ),
        201,
    )
    at_multiple_quote = validate_success(
        api.create_quote(
            at_multiple["id"],
            create_quote_payload(at_multiple["version"], offered_retention_usd=250_000.00,
                                 offered_side_c_sublimit_usd=0),
            UNDERWRITER,
        ),
        201,
    )

    # No Side C sublimit, so PRD 3.3's entity-securities load is 0.00 and the
    # retention credit is the only moving part.
    assert below_quote["risk_band_at_quote"] == "ELEVATED"
    assert below_quote["net_premium_usd"] == pytest.approx(181_500.00, abs=0.01)
    assert below_quote["gross_premium_usd"] == pytest.approx(207_428.57, abs=0.01)
    assert at_multiple_quote["net_premium_usd"] == pytest.approx(172_425.00, abs=0.01)
    assert at_multiple_quote["gross_premium_usd"] == pytest.approx(197_057.14, abs=0.01)
    assert below_quote["net_premium_usd"] - at_multiple_quote["net_premium_usd"] == (
        pytest.approx(9_075.00, abs=0.01)
    ), "one cent more retention steps the credit from 0.00 to 0.05"


def test_retention_credit_is_flat_across_a_block_and_steps_again_at_the_next(api):
    """PRD 3.3: the credit is "0.05 multiplied by the number of whole 250,000
    blocks in `offered_retention_usd`, the block count being the quotient
    discarding any remainder", so every retention inside one block prices
    identically and the credit moves only on crossing the next multiple.

    Design: Difficulty/boundary_precision_check/retention_credit_step_at_exact_block_multiple
    """
    scenario = setup_insured_with_history()
    insured_id = scenario["insured"]["id"]

    nets = []
    for retention in (250_000.00, 499_999.99, 500_000.00):
        submission = _scored_submission(
            insured_id, requested_retention_usd=retention,
            requested_side_c_sublimit_usd=0,
            requested_program_target_limit_usd=10_000_000,
        )
        quote = validate_success(
            api.create_quote(
                submission["id"],
                create_quote_payload(submission["version"],
                                     offered_retention_usd=retention,
                                     offered_side_c_sublimit_usd=0),
                UNDERWRITER,
            ),
            201,
        )
        nets.append(quote["net_premium_usd"])

    one_block, top_of_block, two_blocks = nets
    assert one_block == pytest.approx(172_425.00, abs=0.01)
    assert top_of_block == pytest.approx(172_425.00, abs=0.01), (
        "the credit is flat across the whole 250,000-wide block"
    )
    assert two_blocks == pytest.approx(163_350.00, abs=0.01)
    assert 25_000.00 < two_blocks < 2_500_000.00, "no premium here is clamped"
