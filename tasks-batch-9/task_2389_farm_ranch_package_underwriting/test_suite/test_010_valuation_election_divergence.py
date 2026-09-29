"""Replacement-cost versus actual-cash-value elections, and per-head versus
blanket livestock limits, priced on otherwise identical inputs."""

from test_helpers import (
    UW,
    add_livestock_group,
    add_scheduled_item,
    bootstrap_zone,
    get_success_data,
    open_policy,
    rate_policy_ok,
    read_policy,
    setup_draft_policy_with_dwelling,
    validate_success,
)


def _equipment(basis: str, description: str) -> dict:
    """Two equipment rows whose only difference is the valuation election."""
    return {
        "item_class": "EQUIPMENT",
        "description": description,
        "valuation_basis": basis,
        "stated_value_cents": 30_001_000,
        "age_years": 12,
        "condition_grade": "B",
    }


def test_rc_and_acv_elections_diverge_on_byte_identical_equipment_rows(api):
    """"Step two branches on `valuation_basis`, and the two branches carry equal
    weight." The RC branch insures the smaller of the effective value and the
    class cap, so the 30001000-cent sprayer is insured in full, while the ACV
    branch depreciates it by the capped 0.60 fraction and the 0.92 condition
    factor for grade B down to 11040368 cents. `age_years` and
    `condition_grade` "are read on this branch but contribute nothing at all",
    so the two rows differ by 18960632 cents on the election alone.

    Design: Difficulty/dual_variant_calc/scheduled_item_rc_vs_acv_valuation_divergence
    """
    scenario = bootstrap_zone()

    rc_row = get_success_data(
        api.create_scheduled_item(
            scenario.policy_id,
            _equipment("RC", "Combine harvester (RC election)"),
            scenario.agent_headers,
        )
    )
    acv_row = get_success_data(
        api.create_scheduled_item(
            scenario.policy_id,
            _equipment("ACV", "Combine harvester (ACV election)"),
            scenario.agent_headers,
        )
    )

    assert rc_row["insured_value_cents"] == 30_001_000
    assert acv_row["insured_value_cents"] == 11_040_368
    assert rc_row["insured_value_cents"] - acv_row["insured_value_cents"] == 18_960_632

    assert rc_row["valuation_basis"] == "RC"
    assert acv_row["valuation_basis"] == "ACV"
    for field in ("item_class", "stated_value_cents", "age_years", "condition_grade"):
        assert rc_row[field] == acv_row[field], (
            f"the two rows must agree on {field}; only valuation_basis differs"
        )


def test_property_premium_carries_one_line_per_valuation_election(api):
    """"Each `ACTIVE` item then contributes one line: its `insured_value_cents`
    multiplied by the property rate for its `item_class`, multiplied by the
    credit, rounded half up to a whole cent on that line." At the 0.90
    deductible credit the RC line prices at 243008 and the ACV line at 89427,
    summing to 332435, and the divergence propagates through
    `exposed_tiv_cents` into the catastrophe load.

    Design: Difficulty/dual_variant_calc/scheduled_item_rc_vs_acv_valuation_divergence
    """
    scenario = bootstrap_zone()
    get_success_data(
        api.create_scheduled_item(
            scenario.policy_id,
            _equipment("RC", "Combine harvester (RC election)"),
            scenario.agent_headers,
        )
    )
    get_success_data(
        api.create_scheduled_item(
            scenario.policy_id,
            _equipment("ACV", "Combine harvester (ACV election)"),
            scenario.agent_headers,
        )
    )

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["uw_status"] == "RATED"
    assert rated["property_premium_cents"] == 332_435
    assert rated["exposed_tiv_cents"] == 41_041_368
    assert rated["cat_load_cents"] == 128_459
    assert rated["total_premium_cents"] == 460_894


def test_per_head_and_blanket_elections_fix_different_covered_limits(api):
    """"On the `PER_HEAD` election it is the smaller of two figures:
    `head_count` multiplied by `per_head_value_cents`, and the per-head
    aggregate cap of 30000000 cents. On the `BLANKET` election it is
    `blanket_limit_cents` multiplied by the blanket coinsurance percentage of
    0.80, rounded half up." The same 170-head herd valued at 150000 cents a
    head is therefore covered for 25500000 per head but only 20400000 under a
    blanket limit set to that identical aggregate.

    Design: Difficulty/dual_variant_calc/livestock_per_head_vs_blanket_limit_divergence
    """
    scenario = setup_draft_policy_with_dwelling()
    second_policy = open_policy(
        scenario.agent_headers,
        scenario.account_id,
        term_start_date="2027-09-01",
        term_end_date="2028-08-31",
    )
    add_scheduled_item(scenario.agent_headers, second_policy["id"])

    per_head = add_livestock_group(
        scenario.agent_headers,
        scenario.policy_id,
        head_count=170,
        per_head_value_cents=150_000,
        limit_basis="PER_HEAD",
    )
    blanket = add_livestock_group(
        scenario.agent_headers,
        second_policy["id"],
        head_count=170,
        per_head_value_cents=150_000,
        limit_basis="BLANKET",
        blanket_limit_cents=25_500_000,
    )

    assert per_head["covered_limit_cents"] == 25_500_000
    assert blanket["covered_limit_cents"] == 20_400_000
    assert blanket["head_count"] == 170
    assert blanket["per_head_value_cents"] == 150_000


def test_livestock_premium_and_catastrophe_load_follow_the_limit_election(api):
    """"Each group contributes its `covered_limit_cents` multiplied by the
    species rate, multiplied by the peril-restriction factor, multiplied by the
    same deductible credit the property line used, rounded half up per group."
    The per-head herd charges 286875 and the blanket herd 229500, a 57375-cent
    gap that also moves `exposed_tiv_cents` and therefore the catastrophe load.

    Design: Difficulty/dual_variant_calc/livestock_per_head_vs_blanket_limit_divergence
    """
    scenario = setup_draft_policy_with_dwelling()
    second_policy = open_policy(
        scenario.agent_headers,
        scenario.account_id,
        term_start_date="2027-09-01",
        term_end_date="2028-08-31",
    )
    add_scheduled_item(scenario.agent_headers, second_policy["id"])
    add_livestock_group(
        scenario.agent_headers,
        scenario.policy_id,
        head_count=170,
        per_head_value_cents=150_000,
        limit_basis="PER_HEAD",
    )
    add_livestock_group(
        scenario.agent_headers,
        second_policy["id"],
        head_count=170,
        per_head_value_cents=150_000,
        limit_basis="BLANKET",
        blanket_limit_cents=25_500_000,
    )

    per_head_policy = rate_policy_ok(scenario.policy_id)
    blanket_policy = rate_policy_ok(second_policy["id"])

    assert per_head_policy["livestock_premium_cents"] == 286_875
    assert blanket_policy["livestock_premium_cents"] == 229_500
    assert (
        per_head_policy["livestock_premium_cents"] - blanket_policy["livestock_premium_cents"]
        == 57_375
    )
    assert per_head_policy["exposed_tiv_cents"] == 65_500_000
    assert blanket_policy["exposed_tiv_cents"] == 60_400_000
    assert per_head_policy["cat_load_cents"] == 205_015
    assert blanket_policy["cat_load_cents"] == 189_052
    assert per_head_policy["total_premium_cents"] == 635_890
    assert blanket_policy["total_premium_cents"] == 562_552

    reread = validate_success(api.get_farm_policy(second_policy["id"], UW))
    assert reread["livestock_premium_cents"] == 229_500
    assert read_policy(scenario.policy_id)["livestock_premium_cents"] == 286_875
