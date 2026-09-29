"""
Acceptance: one decision, five mandatory hops, four resources rewritten.

PRD §3.3: "An `ACCEPT` decision takes the report from `IN_QA` to `ACCEPTED`,
stamps `accepted_at` from the logical clock, and triggers the five-hop
publication cascade that is the structural heart of this system. Every hop is
mandatory."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"


def _claimed_report_and_one_planning_cycle(client, roster, bridge):
    """
    A report sitting in `IN_QA` on Cedar Creek, with exactly one cycle in
    `PLANNING` so that the conditional fourth hop is armed.
    """
    cycle = fx.create_cycle(client, fiscal_year=2028, ranking_policy="CONDITION_BASED")
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)
    fx.submit_report(client, draft["inspection"]["id"], roster)
    fx.qa_claim(client, draft["inspection"]["id"], roster)
    return {"cycle": cycle, "inspection": draft["inspection"], "elements": draft["elements"]}


def test_no_candidate_exists_until_the_acceptance_fires(client, roster, bridge):
    """
    The candidate is written by the cascade, not by the client, so the cycle is
    empty right up to the moment the report is accepted.

    PRD §3.3: "Because these candidates are created by a cascade rather than by a
    client call, the candidate listing is the only channel through which a client
    can discover them."
    PRD §3.8: "Three counters track the candidate mix: `identified_count`,
    `programmed_count` and `deferred_count`, each counting the cycle's candidates
    in the corresponding status and each starting at 0."

    Design: Difficulty/transitive_cascade/inspection_accept_cascade_bridge_interval_candidate_cycle
    """
    setup = _claimed_report_and_one_planning_cycle(client, roster, bridge)

    assert fx.candidates_in_cycle(client, setup["cycle"]["id"]) == []
    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["identified_count"] == 0
    assert cycle["unprogrammed_cost_cents"] == 0
    assert cycle["status"] == "PLANNING"


def test_hop_one_and_two_publish_the_condition_picture_to_the_structure(
    client, roster, bridge
):
    """
    The acceptance stamps the report and then overwrites the structure's three
    component ratings, its minimum, its health index and its inventory totals.

    PRD §3.3: "**Hop 1** sets the report's status to `ACCEPTED` and its
    `accepted_at`."
    PRD §3.3: "The structure's `min_nbi_rating` is then recomputed as the smallest
    of the three component ratings, its `bridge_health_index` is copied from the
    report's, its `inventoried_quantity_total` is set to the sum of
    `total_quantity` across the report's element rows, its `deficiency_pct` is
    recomputed from that same data, and its `version` is incremented by one."
    PRD §3.3: "Totals of 1000, 300, 4 and 4 against deficient quantities of 200,
    200, 2 and 0 give 100 times 402 divided by 1308, which is 30.7339…, rounded to
    30.73."

    Design: Difficulty/transitive_cascade/inspection_accept_cascade_bridge_interval_candidate_cycle
    """
    setup = _claimed_report_and_one_planning_cycle(client, roster, bridge)

    accepted = fx.qa_decide(client, setup["inspection"]["id"], roster, "ACCEPT")

    assert accepted["status"] == "ACCEPTED"
    a.assert_instant_equals(accepted["accepted_at"], FIELD_DAY, "accepted_at")
    assert accepted["bridge_health_index"] == 65.47

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 3
    assert structure["substructure_rating"] == 8
    assert structure["min_nbi_rating"] == 3
    assert structure["bridge_health_index"] == 65.47
    assert structure["inventoried_quantity_total"] == 1308
    assert structure["deficiency_pct"] == 30.73


def test_hop_three_re_derives_the_cycle_and_the_next_due_date(
    client, roster, bridge
):
    """
    The new minimum rating of 3 drops the structure into the poor-condition base
    tier, and the routine due date is measured from the observation date rather
    than from the acceptance instant.

    PRD §3.3: "If the accepted report was `ROUTINE`, the structure's
    `last_routine_inspection_date` is set to the report's `inspection_date` and
    `next_inspection_due_date` becomes that date advanced by the new
    `inspection_interval_months`."
    PRD §2.11: "If the structure's `min_nbi_rating` is 4 or lower, the base is 12
    months."

    Design: Difficulty/transitive_cascade/inspection_accept_cascade_bridge_interval_candidate_cycle
    """
    setup = _claimed_report_and_one_planning_cycle(client, roster, bridge)

    fx.qa_decide(client, setup["inspection"]["id"], roster, "ACCEPT")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["inspection_interval_months"] == 12
    a.assert_date_equals(
        structure["last_routine_inspection_date"],
        "2026-09-02",
        "last_routine_inspection_date",
    )
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-09-02", "next_inspection_due_date"
    )


def test_hop_four_files_exactly_one_automatic_candidate(client, roster, bridge):
    """
    Both conditions hold — the new minimum rating is 3 and exactly one cycle is
    planning — so the cascade files a single candidate marked as coming from the
    inspection, priced and scored in the same pass.

    PRD §3.3: "**Hop 4**, also caused by the rating change in hop 2, is
    conditional on two facts holding together: the structure's *new*
    `min_nbi_rating` is 5 or lower, and exactly one programming cycle in the
    system is currently in `PLANNING`. When both hold, the system creates a
    project candidate for this structure inside that cycle, with `origin` set to
    `AUTO_FROM_INSPECTION`, `source_inspection_id` pointing at the just-accepted
    report, `status` `IDENTIFIED`".
    PRD §3.8: "a subtotal of 23,120,000, which multiplied by 1.15 gives
    26,588,000 cents."
    PRD §3.8: "Under `CONDITION_BASED` the score is 17.265 plus 20.00 plus 6.146,
    which is 43.411, rounded to 43.41."

    Design: Difficulty/transitive_cascade/inspection_accept_cascade_bridge_interval_candidate_cycle
    """
    setup = _claimed_report_and_one_planning_cycle(client, roster, bridge)

    fx.qa_decide(client, setup["inspection"]["id"], roster, "ACCEPT")

    candidates = fx.candidates_in_cycle(client, setup["cycle"]["id"])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["origin"] == "AUTO_FROM_INSPECTION"
    assert candidate["status"] == "IDENTIFIED"
    assert candidate["bridge_id"] == bridge["id"]
    assert candidate["source_inspection_id"] == setup["inspection"]["id"]
    assert candidate["program_cycle_id"] == setup["cycle"]["id"]
    assert candidate["work_type"] == "REPLACEMENT"
    assert candidate["estimated_cost_cents"] == 26588000
    assert candidate["priority_score"] == 43.41
    assert candidate["ranking_policy_applied"] == "CONDITION_BASED"
    assert candidate["programmed_at"] is None
    a.assert_common_fields(candidate, "project candidate")


def test_hop_five_refreshes_the_owning_cycle_without_committing_money(
    client, roster, bridge
):
    """
    The candidate insert propagates into the cycle's identification counters but
    leaves the reserve, the available total and the committed total untouched,
    because nothing has been programmed yet.

    PRD §3.3: "**Hop 5**, caused by the candidate insert in hop 4, refreshes the
    owning cycle: its `identified_count` and `unprogrammed_cost_cents` are
    recomputed and its `version` is incremented by one."
    PRD §3.8: "A cycle authorised at 10,000,000,000 cents with the default reserve
    fraction reserves 500,000,000 and makes 9,500,000,000 available, with the same
    amount remaining."

    Design: Difficulty/transitive_cascade/inspection_accept_cascade_bridge_interval_candidate_cycle
    """
    setup = _claimed_report_and_one_planning_cycle(client, roster, bridge)
    before = fx.read_cycle(client, setup["cycle"]["id"])

    fx.qa_decide(client, setup["inspection"]["id"], roster, "ACCEPT")

    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["identified_count"] == 1
    assert cycle["programmed_count"] == 0
    assert cycle["unprogrammed_cost_cents"] == 26588000
    assert cycle["committed_cents"] == 0
    assert cycle["reserve_cents"] == 500000000
    assert cycle["available_cents"] == 9500000000
    assert cycle["remaining_cents"] == 9500000000
    a.assert_budget_identity(cycle)
    a.assert_version_advanced_by(cycle["version"], before["version"], 1, "program cycle")

    summary = fx.read_allocation(client, setup["cycle"]["id"])
    a.assert_allocation_summary_matches_cycle(summary, cycle)
    assert summary["identity_holds"] is True
