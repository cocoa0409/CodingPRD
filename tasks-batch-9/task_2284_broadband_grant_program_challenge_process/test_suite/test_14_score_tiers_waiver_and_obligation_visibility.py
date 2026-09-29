"""Cost-tier edges, the disabled high-cost waiver, and obligation visibility."""

from test_helpers import (
    api_client,
    assert_award,
    assert_ledger_entry,
    assert_ledger_reconciliation,
    assert_program_balance_invariant,
    assert_score_sheet,
    obligate_award,
    read_application,
    read_award,
    read_location,
    read_program,
    read_subgrantee,
    score_application,
    select_application,
    setup_challenge_open_program,
    setup_qualified_subgrantee,
    setup_scored_application,
    setup_submitted_application,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN, advance_program_to_scoring


def test_the_first_cost_tier_edge_is_inclusive_by_a_single_cent():
    """Two applications differing by one cent of claimed cost land on opposite sides
    of the first tier edge: the cost at the boundary earns the top 30.00, one cent
    over earns 24.00, and the six-point gap is carried through the same 1.05
    multiplier into a 6.30 difference in the totals.

    PRD 3.6: "It is 30.00 when that cost is at most 100000 cents — a thousand
    dollars a location — 24.00 when it is at most 250000, 16.00 when it is at most
    500000, 8.00 when it is at most 1000000, and 0.00 above that."
    PRD 3.6: "Each tier boundary is inclusive on its upper edge, so a cost of
    exactly 250000 cents earns 24.00 rather than 16.00."
    PRD 3.6: "The subtotal is the sum of the four component figures as stored;
    `total_score` is that subtotal multiplied by `capability_multiplier`, rounded
    half up to 2 decimals, and then capped at 100.00."
    PRD 3.6: "`capability_multiplier` is 1.05 when the applicant's
    `capability_index` is at least 90.00, and 1.00 otherwise."

    Design: Corner/calculations/application_total_score_cost_tier_first_breakpoint
    """
    ctx = setup_challenge_open_program(("L3", "L2"))
    edge_applicant = setup_qualified_subgrantee(ctx["program_id"])
    over_edge_applicant = setup_qualified_subgrantee(ctx["program_id"])
    assert read_subgrantee(edge_applicant["id"])["capability_index"] == 90.00
    assert read_subgrantee(over_edge_applicant["id"])["capability_index"] == 90.00

    edge_application, _ = setup_submitted_application(
        ctx["program_id"], edge_applicant["id"], [(ctx["location_ids"]["L3"], 100000)]
    )
    over_edge_application, _ = setup_submitted_application(
        ctx["program_id"],
        over_edge_applicant["id"],
        [(ctx["location_ids"]["L2"], 100001)],
    )
    advance_program_to_scoring(ctx["program_id"])

    at_edge = score_application(edge_application["id"])
    assert_score_sheet(at_edge)
    assert at_edge["basis_confirmed_location_count"] == 1
    assert at_edge["basis_final_cost_per_location_cents"] == 100000
    assert at_edge["cost_points"] == 30.00, "100000 cents is at most 100000"
    assert at_edge["speed_points"] == 30.00
    assert at_edge["affordability_points"] == 20.00
    assert at_edge["workforce_points"] == 9.00
    assert at_edge["total_score"] == 93.45, "89.00 raised by the 1.05 multiplier"
    assert at_edge["score_state"] == "FINAL"

    over_edge = score_application(over_edge_application["id"])
    assert_score_sheet(over_edge)
    assert over_edge["basis_final_cost_per_location_cents"] == 100001
    assert over_edge["cost_points"] == 24.00, "One cent over the edge drops a tier"
    assert over_edge["speed_points"] == 30.00
    assert over_edge["affordability_points"] == 20.00
    assert over_edge["workforce_points"] == 9.00
    assert over_edge["total_score"] == 87.15, "83.00 raised by the same multiplier"

    assert round(at_edge["total_score"] - over_edge["total_score"], 2) == 6.30
    assert read_application(edge_application["id"])["current_total_score"] == 93.45
    assert read_application(over_edge_application["id"])["current_total_score"] == 87.15


def test_a_program_with_the_waiver_disabled_funds_its_extreme_location():
    """The single claim costs more than the high-cost threshold and is flagged as
    such, but the program has switched the waiver off, so the flagged claim stays in
    the retained set and is funded rather than deferred.

    PRD 3.7: "For every claim in the base set, `is_ehcl` is set to true exactly
    when its `claimed_cost_cents` is strictly greater than the program's
    `ehcl_threshold_cents`, and false otherwise."
    PRD 3.7: "Otherwise the retained set is the whole base set and
    `ehcl_deferred_count` is 0 — which is how a program that disables the waiver
    funds even an extremely expensive location."
    PRD 3.7: "`obligation_amount_cents` is `total_eligible_cost_cents` minus
    `match_requirement_cents` — the federal share."

    Design: Corner/validations/ehcl_waiver_disabled_retains_high_cost_location
    """
    ctx = setup_scored_application(
        location_keys=("L3",),
        claims=[("L3", 3000000)],
        program_overrides={"ehcl_waiver_enabled": False},
    )
    assert ctx["program"]["ehcl_waiver_enabled"] is False
    assert ctx["program"]["ehcl_threshold_cents"] == 2500000

    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])
    assert_award(award)
    assert award["ehcl_deferred_count"] == 0, (
        "With the waiver disabled nothing is deferred, however expensive"
    )
    assert award["confirmed_location_count"] == 1
    assert award["total_eligible_cost_cents"] == 3000000
    assert award["match_requirement_cents"] == 750000
    assert award["obligation_amount_cents"] == 2250000
    assert award["holdback_cap_cents"] == 2025000
    assert award["final_per_location_cost_cents"] == 3000000

    claims, meta = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert meta["total_count"] == 1
    funded = claims[0]
    assert funded["is_ehcl"] is True, "The flag is still stamped on the claim"
    assert funded["claim_state"] == "AWARD_BOUND"
    assert funded["match_share_cents"] == 750000

    location = read_location(ctx["location_ids"]["L3"])
    assert location["eligibility_state"] == "AWARD_BOUND"
    assert location["awarded_award_id"] == award["id"]

    program = read_program(ctx["program_id"])
    assert program["obligated_balance_cents"] == 2250000
    assert program["uncommitted_balance_cents"] == 97750000
    assert_program_balance_invariant(program)


def test_one_obligation_is_visible_across_every_entity_it_touched():
    """The obligating call writes across five families at once, and each is already
    consistent on the very next read: the award, the application, its claims, the
    bound locations and the program's ledger-derived balances.

    PRD 3.7: "When all nine steps pass, an **Award** is created with `award_state`
    `OBLIGATED` and `compliance_state` `COMPLIANT`, its `confirmed_location_count`
    counting the claims now bound to it, `disbursed_to_date_cents` at 0, and
    `certified_location_count` and `failed_location_count` at 0."
    PRD 3.7: "An `OBLIGATION` ledger entry for the obligation amount is appended,
    and the program's balances are re-derived from the ledger as described in
    §2.11."
    PRD 2.11: "The invariant that must hold after every mutation is that
    `total_appropriation_cents` equals the sum of `uncommitted_balance_cents`,
    `obligated_balance_cents` and `disbursed_balance_cents`."

    Design: Corner/consistency model/immediate_visibility_of_obligation_across_four_entities
    """
    ctx = setup_scored_application()
    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])

    fetched_award = read_award(award["id"])
    assert fetched_award["award_state"] == "OBLIGATED"
    assert fetched_award["compliance_state"] == "COMPLIANT"
    assert fetched_award["confirmed_location_count"] == 3
    assert fetched_award["disbursed_to_date_cents"] == 0
    assert fetched_award["certified_location_count"] == 0
    assert fetched_award["failed_location_count"] == 0
    assert fetched_award["obligation_amount_cents"] == 2025003
    assert fetched_award["holdback_cap_cents"] == 1822503

    application = read_application(ctx["application_id"])
    assert application["application_state"] == "AWARDED"
    awards, award_meta = validate_paginated(
        api_client.list_application_awards(ctx["application_id"], ADMIN)
    )
    assert award_meta["total_count"] == 1
    assert awards[0]["id"] == award["id"]

    claims, claim_meta = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert claim_meta["total_count"] == 3
    assert {c["claim_state"] for c in claims} == {"AWARD_BOUND"}
    assert {c["match_share_cents"] for c in claims} == {225001}
    assert sum(c["match_share_cents"] for c in claims) == 675003

    for location_id in ctx["location_ids"].values():
        location = read_location(location_id)
        assert location["eligibility_state"] == "AWARD_BOUND"
        assert location["awarded_award_id"] == award["id"]

    entries, entry_meta = validate_paginated(
        api_client.list_ledger_entries(award["id"], ADMIN)
    )
    assert entry_meta["total_count"] == 1
    entry = entries[0]
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "OBLIGATION"
    assert entry["amount_cents"] == 2025003
    assert entry["award_id"] == award["id"]
    assert entry["program_uncommitted_after_cents"] == 97974997

    program = read_program(ctx["program_id"])
    assert program["obligated_balance_cents"] == 2025003
    assert program["disbursed_balance_cents"] == 0
    assert program["uncommitted_balance_cents"] == 97974997
    assert_program_balance_invariant(program)
    assert_ledger_reconciliation(program, entries)
