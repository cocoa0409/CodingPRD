"""The nine-step obligation pass: match rounding, high-cost deferral, funding."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_award_payload,
    obligate_award,
    read_application,
    read_location,
    read_program,
    select_application,
    setup_obligated_award,
    setup_scored_application,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def test_match_requirement_rounds_each_claim_then_sums_exactly():
    """The match is built claim by claim, each share rounded to a whole cent
    before the exact integer sum, which lands a cent above the figure that
    rounding the aggregate product once would give.

    PRD 3.7: "Walking the retained claims in ascending `created_at` order, each
    claim's `match_share_cents` is its `claimed_cost_cents` multiplied by the
    program's `min_match_pct` divided by 100, rounded half up to a whole cent;
    `match_requirement_cents` is then the exact integer sum of those per-claim
    shares."
    PRD 3.7: "Rounding the aggregate product instead — taking
    `total_eligible_cost_cents` times `min_match_pct` divided by 100 and rounding
    that once — is explicitly wrong: the two disagree by whole cents whenever
    individual shares round up."

    Design: Difficulty/combinatorial_formula/award_match_per_location_round_then_sum
    """
    ctx = setup_obligated_award()
    award = ctx["award"]

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert len(claims) == 3
    for claim in claims:
        assert claim["claimed_cost_cents"] == 900002
        assert claim["match_share_cents"] == 225001, (
            "900002 at a 25.0 percent match is 225000.5, rounded half up to "
            "225001"
        )

    assert award["total_eligible_cost_cents"] == 2700006
    assert award["match_requirement_cents"] == 675003, (
        "Three per-claim shares of 225001 sum to 675003; rounding the aggregate "
        "2700006 times 25 over 100 once would give 675002 instead"
    )
    assert award["match_requirement_cents"] != 675002


def test_obligation_and_holdback_follow_from_the_summed_match():
    """The federal share is the eligible cost less the summed match, and the
    holdback ceiling is that share net of the holdback percentage, rounded half
    up to a whole cent.

    PRD 3.7: "`obligation_amount_cents` is `total_eligible_cost_cents` minus
    `match_requirement_cents` — the federal share."
    PRD 3.7: "`holdback_cap_cents` is `obligation_amount_cents` multiplied by the
    quantity 100 minus the program's `holdback_pct`, divided by 100, rounded half
    up to a whole cent; it is the cumulative ceiling on everything disbursed
    before the final milestone, so at the default ten percent holdback a
    subgrantee can draw at most ninety percent of its obligation across all
    non-final milestones."

    Design: Difficulty/combinatorial_formula/award_match_per_location_round_then_sum
    """
    ctx = setup_obligated_award()
    award = ctx["award"]

    assert award["final_per_location_cost_cents"] == 900002
    assert award["obligation_amount_cents"] == 2025003, "2700006 less 675003"
    assert award["holdback_cap_cents"] == 1822503, (
        "2025003 times 90 over 100 is 1822502.7, rounded half up to 1822503"
    )
    assert award["disbursed_to_date_cents"] == 0
    assert award["confirmed_location_count"] == 3


def test_obligation_applies_every_effect_in_one_pass():
    """A single obligation request stamps the award's whole arithmetic, binds
    every retained claim and its location, moves the application and appends the
    ledger entry that re-derives the program's balances.

    PRD 3.7: "The obligation runs as a single pinned pass of nine steps."
    PRD 3.7: "Every retained claim moves to `AWARD_BOUND` and its location moves
    on the eligibility axis to `AWARD_BOUND` with `awarded_award_id` stamped to
    the new award — `AFFIRMED → AWARD_BOUND` for a location the challenge process
    left alone, and `RECLASSIFIED → AWARD_BOUND` for one a sustained challenge
    reclassified, and in both cases only when a claim on that location for this
    application is `CLAIMED_ELIGIBLE` and either its `claimed_cost_cents` is at
    most the extremely-high-cost threshold or the program has disabled the
    waiver."

    Design: Difficulty/combinatorial_formula/award_obligation_single_pass_ehcl_order
    """
    ctx = setup_scored_application()
    select_application(ctx["application_id"])

    before = read_program(ctx["program_id"])
    assert before["uncommitted_balance_cents"] == 100000000
    assert before["obligated_balance_cents"] == 0

    award = obligate_award(ctx["application_id"])
    assert award["award_state"] == "OBLIGATED"
    assert award["compliance_state"] == "COMPLIANT"
    assert award["ehcl_deferred_count"] == 0
    assert award["certified_location_count"] == 0
    assert award["failed_location_count"] == 0

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert {c["claim_state"] for c in claims} == {"AWARD_BOUND"}
    assert {c["is_ehcl"] for c in claims} == {False}

    for key in ("L2", "L3", "L5"):
        location = read_location(ctx["location_ids"][key])
        assert location["eligibility_state"] == "AWARD_BOUND"
        assert location["awarded_award_id"] == award["id"]

    assert read_application(ctx["application_id"])["application_state"] == "AWARDED"

    entries, _ = validate_paginated(api_client.list_ledger_entries(award["id"], ADMIN))
    assert [e["entry_type"] for e in entries] == ["OBLIGATION"]
    assert entries[0]["amount_cents"] == award["obligation_amount_cents"]

    after = read_program(ctx["program_id"])
    assert after["obligated_balance_cents"] == award["obligation_amount_cents"]
    assert after["uncommitted_balance_cents"] == 100000000 - award[
        "obligation_amount_cents"
    ]


def test_disabled_waiver_funds_the_flagged_claim_without_a_second_pass():
    """With the waiver off the flagged claim is still funded, the deferred count
    stays at zero, and the frozen per-location cost may exceed the threshold
    without triggering any further deferral.

    PRD 3.7: "Otherwise the retained set is the whole base set and
    `ehcl_deferred_count` is 0 — which is how a program that disables the waiver
    funds even an extremely expensive location."
    PRD 3.7: "This figure is frozen at obligation: even if it now exceeds
    `ehcl_threshold_cents`, no further deferral occurs."

    Design: Difficulty/combinatorial_formula/award_obligation_single_pass_ehcl_order
    """
    ctx = setup_scored_application(
        location_keys=("L2", "L3"),
        claims=[("L2", 3000000), ("L3", 2400000)],
        program_overrides={
            "name": "BEAD Round 1 No-Waiver Tranche",
            "ehcl_waiver_enabled": False,
        },
    )
    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])

    assert award["ehcl_deferred_count"] == 0
    assert award["confirmed_location_count"] == 2
    assert award["total_eligible_cost_cents"] == 5400000
    assert award["final_per_location_cost_cents"] == 2700000, (
        "5400000 over two retained claims is 2700000, above the 2500000 "
        "threshold yet still funded"
    )
    assert award["match_requirement_cents"] == 1350000
    assert award["obligation_amount_cents"] == 4050000

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    flagged = {c["claimed_cost_cents"]: c for c in claims}
    assert flagged[3000000]["is_ehcl"] is True
    assert flagged[3000000]["claim_state"] == "AWARD_BOUND"
    assert flagged[2400000]["is_ehcl"] is False
    assert read_location(ctx["location_ids"]["L2"])["eligibility_state"] == "AWARD_BOUND"


def test_ehcl_flag_needs_a_cost_strictly_above_the_threshold():
    """The high-cost test is strictly greater than, so a claim sitting exactly on
    the threshold is retained while one cent more is deferred out of the award.

    PRD 3.1: "`ehcl_threshold_cents` is the extremely-high-cost-location
    threshold, strictly above which a single claimed location is an extremely
    high cost location, and defaults to 2500000 — twenty-five thousand dollars
    per location."
    PRD 3.7: "For every claim in the base set, `is_ehcl` is set to true exactly
    when its `claimed_cost_cents` is strictly greater than the program's
    `ehcl_threshold_cents`, and false otherwise."

    Design: Difficulty/boundary_precision_check/ehcl_threshold_strict_greater_than_edge
    """
    ctx = setup_scored_application(
        location_keys=("L2", "L3"),
        claims=[("L2", 2500000), ("L3", 2500001)],
        program_overrides={"name": "BEAD High Cost Tranche"},
    )
    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    by_cost = {c["claimed_cost_cents"]: c for c in claims}
    assert by_cost[2500000]["is_ehcl"] is False, "Exactly at the threshold is not high cost"
    assert by_cost[2500001]["is_ehcl"] is True, "One cent above the threshold is"

    assert award["ehcl_deferred_count"] == 1
    assert award["confirmed_location_count"] == 1
    assert award["total_eligible_cost_cents"] == 2500000
    assert award["final_per_location_cost_cents"] == 2500000
    assert award["match_requirement_cents"] == 625000
    assert award["obligation_amount_cents"] == 1875000


def test_deferral_moves_the_flagged_claim_and_its_location_off_the_award():
    """Deferral is a state change on both the claim and its location, and the
    deferred claim never enters the retained arithmetic.

    PRD 3.7: "If the program's `ehcl_waiver_enabled` is true and at least one
    claim is flagged, every flagged claim moves to `claim_state` `EHCL_DEFERRED`
    and its location moves on the eligibility axis `AFFIRMED →
    DEFERRED_HIGH_COST`; the retained set is the base set minus the deferred
    claims and `ehcl_deferred_count` records how many were deferred."

    Design: Difficulty/boundary_precision_check/ehcl_threshold_strict_greater_than_edge
    """
    ctx = setup_scored_application(
        location_keys=("L2", "L3"),
        claims=[("L2", 2500000), ("L3", 2500001)],
        program_overrides={"name": "BEAD High Cost Tranche"},
    )
    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    by_cost = {c["claimed_cost_cents"]: c for c in claims}
    assert by_cost[2500001]["claim_state"] == "EHCL_DEFERRED"
    assert by_cost[2500000]["claim_state"] == "AWARD_BOUND"

    retained_location = read_location(ctx["location_ids"]["L2"])
    assert retained_location["eligibility_state"] == "AWARD_BOUND"
    assert retained_location["awarded_award_id"] == award["id"]

    deferred_location = read_location(ctx["location_ids"]["L3"])
    assert deferred_location["eligibility_state"] == "DEFERRED_HIGH_COST"
    assert deferred_location["awarded_award_id"] is None


def test_obligation_reports_application_state_before_appropriation_exhaustion():
    """A SCORED application whose obligation would also exhaust the
    appropriation reports the priority 44 state error, and only once it is
    selected does the priority 91 fiscal error surface.

    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation
    stops at the first violation."
    PRD 2.12: "12. **Priority 44 — obligation eligibility.** Award obligation
    requires the application to be `SELECTED`; a `SCORED` or `NOT_SELECTED`
    application cannot be obligated → `ERR_APPLICATION_NOT_SELECTED`."
    PRD 3.7: "9. If `obligation_amount_cents` exceeds the program's
    `uncommitted_balance_cents`, the obligation is refused with
    `ERR_PROGRAM_FUNDS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/application_state_beats_program_funds_on_award
    """
    ctx = setup_scored_application(
        location_keys=("L2", "L3"),
        claims=[("L2", 900002), ("L3", 900002)],
        program_overrides={
            "name": "BEAD Pilot Tranche",
            "total_appropriation_cents": 1000000,
        },
    )
    assert read_application(ctx["application_id"])["application_state"] == "SCORED"

    state_first = api_client.create_award(
        create_award_payload(ctx["application_id"]), ADMIN
    )
    validate_error(state_first, ApiErrorId.ERR_APPLICATION_NOT_SELECTED)

    select_application(ctx["application_id"])
    funds_second = api_client.create_award(
        create_award_payload(ctx["application_id"]), ADMIN
    )
    validate_error(funds_second, ApiErrorId.ERR_PROGRAM_FUNDS_EXHAUSTED)


def test_state_refusal_stops_before_the_appropriation_is_touched():
    """Evaluation stops at the first violation, so the refused obligation leaves
    no award and no movement in the program's balances.

    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation
    stops at the first violation."
    PRD 2.12: "12. **Priority 44 — obligation eligibility.** Award obligation
    requires the application to be `SELECTED`; a `SCORED` or `NOT_SELECTED`
    application cannot be obligated → `ERR_APPLICATION_NOT_SELECTED`."
    PRD 2.11: "The invariant that must hold after every mutation is that
    `total_appropriation_cents` equals the sum of `uncommitted_balance_cents`,
    `obligated_balance_cents` and `disbursed_balance_cents`."

    Design: Difficulty/priority_pair_validation_conflict/application_state_beats_program_funds_on_award
    """
    ctx = setup_scored_application(
        location_keys=("L2", "L3"),
        claims=[("L2", 900002), ("L3", 900002)],
        program_overrides={
            "name": "BEAD Pilot Tranche",
            "total_appropriation_cents": 1000000,
        },
    )

    refused = api_client.create_award(
        create_award_payload(ctx["application_id"]), ADMIN
    )
    validate_error(refused, ApiErrorId.ERR_APPLICATION_NOT_SELECTED)

    awards, meta = validate_paginated(
        api_client.list_application_awards(ctx["application_id"], ADMIN)
    )
    assert awards == []
    assert meta["total_count"] == 0

    program = read_program(ctx["program_id"])
    assert program["uncommitted_balance_cents"] == 1000000
    assert program["obligated_balance_cents"] == 0
    assert program["disbursed_balance_cents"] == 0
    assert read_application(ctx["application_id"])["application_state"] == "SCORED"

    unchanged = validate_success(api_client.get_program(ctx["program_id"], ADMIN))
    assert (
        unchanged["total_appropriation_cents"]
        == unchanged["uncommitted_balance_cents"]
        + unchanged["obligated_balance_cents"]
        + unchanged["disbursed_balance_cents"]
    )
