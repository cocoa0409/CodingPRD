"""Binding: one accept call propagating four levels deep.

The quote creates the policy, the policy creates its coverage parts, the Side C
part changes what the insurer has committed to this insured, and that commitment
re-derives the insured's posture.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    UNDERWRITER,
    assert_capacity_derivation,
    assert_coverage_part,
    assert_coverage_part_creation_order,
    assert_instant_equals,
    assert_policy,
    find_part,
    make_risk_manager_headers,
    read_insured,
    read_quote,
    read_submission,
    resolve_term_as_insured,
    setup_offered_quote,
)

# 5,000,000 of Side C against this cap is a utilisation of exactly 0.80.
RESTRICTED_CAP = 6_250_000


def _quote_ready_to_bind():
    scenario = setup_offered_quote(
        insured_overrides={"entity_capacity_cap_usd": RESTRICTED_CAP}
    )
    resolve_term_as_insured(
        scenario["conduct_term"]["id"], scenario["insured"]["id"], "AGREE"
    )
    return scenario


def test_accept_creates_the_policy_and_its_three_coverage_parts_in_order(api):
    """PRD 3.4: "the accepted quote creates the policy with `coverage_status`
    `INCEPTED` and `premium_status` `INVOICED`" and "`premium_due_date` is set to
    the binding instant plus 30 days". "Second, creating the policy creates its
    coverage parts, in a fixed order that later rounding rules depend on: `SIDE_A`
    first, then `SIDE_B`, then `SIDE_C` — and `SIDE_C` only when the accepted
    `offered_side_c_sublimit_usd` is strictly greater than 0." "`SIDE_A` carries a
    `retention_usd` of 0, since non-indemnified individual loss is not subject to
    the retention; `SIDE_B` and `SIDE_C` each carry the policy's retention."

    Design: Difficulty/transitive_cascade/bind_cascade_policy_parts_insured_capacity
    """
    scenario = _quote_ready_to_bind()
    insured_id = scenario["insured"]["id"]

    response = api.accept_quote(
        scenario["quote"]["id"], make_risk_manager_headers(insured_id)
    )

    policy = validate_success(response, 201)
    assert_policy(policy)
    assert policy["coverage_status"] == "INCEPTED"
    assert policy["premium_status"] == "INVOICED"
    assert policy["shared_aggregate_limit_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert policy["retention_usd"] == pytest.approx(250_000, abs=0.01)
    # The only AGREED term carries premium_impact_pct 0.00, so the bound premium
    # equals the quoted gross premium exactly.
    assert policy["gross_premium_usd"] == pytest.approx(236_468.57, abs=0.01)
    assert_instant_equals(policy["premium_due_date"], "2026-08-31T00:00:00Z",
                          "premium_due_date")
    assert policy["aggregate_remaining_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert policy["total_eroded_usd"] == pytest.approx(0, abs=0.01)
    assert policy["placed_limit_usd"] == pytest.approx(0, abs=0.01)
    assert policy["tower_posture"] == "INCOMPLETE"
    assert policy["tower_sealed"] is False
    assert policy["open_claim_count"] == 0
    assert policy["version"] == 1

    assert read_quote(scenario["quote"]["id"])["status"] == "ACCEPTED"
    submission = read_submission(scenario["submission"]["id"])
    assert submission["status"] == "BOUND"
    # Created 1, score 2, quote issue 3, accept 4.
    assert submission["version"] == 4

    parts, meta = validate_paginated(
        api.list_coverage_parts(policy["id"], UNDERWRITER)
    )
    assert meta["total_count"] == 3
    assert_coverage_part_creation_order(parts)
    for part in parts:
        assert_coverage_part(part)
        assert part["status"] == "ACTIVE"
        assert part["eroded_usd"] == pytest.approx(0, abs=0.01)
        assert part["remaining_limit_usd"] == pytest.approx(part["limit_usd"], abs=0.01)
    assert find_part(parts, "SIDE_A")["limit_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert find_part(parts, "SIDE_A")["retention_usd"] == pytest.approx(0, abs=0.01)
    assert find_part(parts, "SIDE_B")["limit_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert find_part(parts, "SIDE_B")["retention_usd"] == pytest.approx(250_000, abs=0.01)
    assert find_part(parts, "SIDE_C")["limit_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert find_part(parts, "SIDE_C")["retention_usd"] == pytest.approx(250_000, abs=0.01)


def test_the_created_side_c_part_drives_the_insured_capacity_posture(api):
    """PRD 3.4: "The insured's `aggregate_bound_side_c_usd` is the sum of
    `limit_usd` over every `SIDE_C` coverage part that is `ACTIVE` and whose policy
    belongs to this insured with a `coverage_status` of `INCEPTED`, `ACTIVE` or
    `RUNOFF`. `available_side_c_capacity_usd` is `entity_capacity_cap_usd` less
    `aggregate_bound_side_c_usd`, floored at 0." Utilisation "drives
    `capacity_posture`: `EXHAUSTED` when utilisation is greater than or equal to
    1.00, `RESTRICTED` when it is greater than or equal to 0.80 but below 1.00, and
    `OPEN` otherwise."

    Design: Difficulty/transitive_cascade/bind_cascade_policy_parts_insured_capacity
    """
    scenario = _quote_ready_to_bind()
    insured_id = scenario["insured"]["id"]

    before = read_insured(insured_id)
    assert before["aggregate_bound_side_c_usd"] == pytest.approx(0, abs=0.01)
    assert before["available_side_c_capacity_usd"] == pytest.approx(
        RESTRICTED_CAP, abs=0.01
    )
    assert before["capacity_posture"] == "OPEN"
    assert before["open_policy_count"] == 0
    assert before["version"] == 1

    validate_success(
        api.accept_quote(scenario["quote"]["id"], make_risk_manager_headers(insured_id)),
        201,
    )

    after = read_insured(insured_id)
    # The created SIDE_C part's limit, not the whole 10,000,000 policy limit.
    assert after["aggregate_bound_side_c_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert after["available_side_c_capacity_usd"] == pytest.approx(1_250_000, abs=0.01)
    assert after["capacity_posture"] == "RESTRICTED", (
        "utilisation is exactly 0.80, the lower edge of RESTRICTED"
    )
    assert_capacity_derivation(after)
    assert after["open_policy_count"] == 1
    # PRD 3.4: "Both the insured's `version` and the submission's `version`
    # increment by 1 on a successful bind."
    assert after["version"] == 2
