"""Purpose and need statements and the range of alternatives they constrain:
adoption side effects, the feasibility calculation, and the two refusals that
protect the range.
"""
from test_helpers import (
    DEFAULT_MIN_ALTERNATIVE_FEASIBILITY,
    NEPA_COORDINATOR_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    adopt_payload,
    alternative_payload,
    approx_score,
    assert_alternative,
    assert_purpose_need_statement,
    decision_payload,
    entries_with_code,
    fixtures,
    purpose_need_payload,
    screen_alternative_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The alternatives the design pins against the adopted goal codes
#: [ACCESS, SAFETY, HABITAT, COST] and a reference cost of 10000000 cents.
NO_ACTION_ALTERNATIVE = {
    "label": "A - No Action",
    "alternative_kind": "NO_ACTION",
    "goal_alignment_codes": [],
    "estimated_cost_cents": 0,
}
HIGH_COST_ALTERNATIVE = {
    "label": "C - Full Mechanical Removal",
    "alternative_kind": "REASONABLE_RANGE",
    "goal_alignment_codes": ["ACCESS"],
    "estimated_cost_cents": 30000000,
}


class TestAdoptionSideEffects:
    """Adopting a statement re-constrains the alternatives range."""

    def test_second_adoption_supersedes_the_first_and_stales_its_alternatives(
        self, client
    ):
        """The adoption chain supersedes the earlier statement, drags both
        alternatives pinned to it into `STALE`, and drops the screened-in count
        from two to zero.

        PRD 3.4: "Moving a statement `DRAFT → ADOPTED` sets off a chain: any other
        statement of the same action whose `status` is `ADOPTED` moves `ADOPTED →
        SUPERSEDED`; every `Alternative` of the action whose
        `pinned_pn_statement_id` names that newly superseded statement and whose
        `screening_status` is `PROPOSED` or `SCREENED_IN` moves to `STALE`, and for
        each such alternative that had been `SCREENED_IN` the action's
        `alternatives_screened_in_count` is decremented by one; the action's
        `version` increments by one; and a `PN_ADOPTED` entry is appended,
        incrementing `record_entry_count`."

        Design: Corner/state_machines/corner_adopting_second_purpose_need_supersedes_first_and_stales_alternatives
        """
        ctx = fixtures.setup_scoping_action()
        ctx = fixtures.setup_alternatives(ctx, screen_in=True)
        action_id = ctx["action"]["id"]
        first_statement = ctx["statement"]
        assert ctx["action"]["alternatives_screened_in_count"] == 2, (
            "both alternatives were screened in against the first statement"
        )

        second_statement = validate_success(
            client.create_purpose_need_statement(
                action_id,
                purpose_need_payload(
                    purpose_text=("Reduce hazardous fuel loading and restore aspen "
                                  "on the Ridgeline unit"),
                    need_text=("Fire behaviour and aspen decline both exceed "
                               "thresholds"),
                    goal_codes=["ACCESS", "SAFETY", "HABITAT", "COST", "ASPEN"],
                ),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert second_statement["version_no"] == 2, (
            "version_no is one more than the highest already on the action"
        )
        assert second_statement["status"] == "DRAFT"

        observed_version = fixtures.read_action(action_id)["version"]
        adopted = validate_success(
            client.adopt_purpose_need_statement(
                second_statement["id"], adopt_payload(observed_version),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert adopted["status"] == "ADOPTED"
        assert adopted["version_no"] == 2
        assert_purpose_need_statement(adopted)

        assert fixtures.read_statement(first_statement["id"])["status"] == "SUPERSEDED"

        stale_a = fixtures.read_alternative(ctx["alt_a"]["id"])
        stale_b = fixtures.read_alternative(ctx["alt_b"]["id"])
        assert stale_a["screening_status"] == "STALE"
        assert stale_b["screening_status"] == "STALE"
        assert fixtures.read_action(action_id)["alternatives_screened_in_count"] == 0, (
            "each screened-in alternative dragged into STALE decrements the counter"
        )
        assert stale_b["feasibility_score"] == approx_score(76.75), (
            "the score is computed at creation against the statement the "
            "alternative was pinned to and is not recomputed on adoption"
        )
        assert stale_b["pinned_pn_statement_id"] == first_statement["id"]

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert len(entries_with_code(entries, "PN_ADOPTED")) == 2, (
            "one PN_ADOPTED entry is appended per adoption"
        )

    def test_replayed_action_version_is_refused_on_the_second_adoption(self, client):
        """The version observed before the first adoption is stale afterwards, and
        the freshly read version makes the identical call succeed.

        PRD 2.9: "Adopting a purpose and need statement requires
        `expected_action_version` to equal the current `version` of the statement's
        `ProposedAction`."
        PRD 2.9: "A mismatch is rejected with `ERR_STALE_ACTION_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/corner_adopt_with_stale_expected_action_version_is_rejected
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        first_statement = fixtures.draft_purpose_need(action_id)
        fixtures.open_scoping_period(action_id)

        observed_version = fixtures.read_action(action_id)["version"]
        validate_success(
            client.adopt_purpose_need_statement(
                first_statement["id"], adopt_payload(observed_version),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )

        second_statement = fixtures.draft_purpose_need(
            action_id,
            purpose_text="Reduce hazardous fuel loading and restore stand structure",
            need_text="Revised fire behaviour modelling widens the treatment need",
            goal_codes=["ACCESS", "SAFETY"],
        )

        refused = client.adopt_purpose_need_statement(
            second_statement["id"], adopt_payload(observed_version),
            REVIEWING_OFFICIAL_HEADERS,
        )
        validate_error(refused, ApiErrorId.STALE_ACTION_VERSION.value,
                       expected_status=412)
        assert fixtures.read_statement(second_statement["id"])["status"] == "DRAFT", (
            "the refused adoption leaves the draft where it was"
        )
        assert fixtures.read_statement(first_statement["id"])["status"] == "ADOPTED", (
            "and leaves the adopted statement in place"
        )

        fresh_version = fixtures.read_action(action_id)["version"]
        assert fresh_version == observed_version + 1, (
            "only the first adoption moved the action version"
        )

        retried = validate_success(
            client.adopt_purpose_need_statement(
                second_statement["id"], adopt_payload(fresh_version),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert retried["status"] == "ADOPTED"
        assert fixtures.read_statement(first_statement["id"])["status"] == "SUPERSEDED"

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert len(entries_with_code(entries, "PN_ADOPTED")) == 2, (
            "the refused attempt appended nothing, so only the two accepted "
            "adoptions are recorded"
        )


class TestAlternativeFeasibility:
    """The feasibility score, and the gate that keeps an infeasible alternative
    out of the range."""

    def test_feasibility_score_weights_alignment_against_cost_overrun(self, client):
        """Three alternatives against the same adopted statement score 35.00,
        76.75 and 16.25, the last one showing the cost factor floored at zero.

        PRD 3.4: "The alignment ratio is the number of entries in
        `goal_alignment_codes` that also appear in the pinned statement's
        `goal_codes`, divided by the number of entries in that `goal_codes` list."
        PRD 3.4: "The cost factor is one minus that overrun ratio, floored at zero,
        so an alternative costing twice the reference contributes nothing on the
        cost axis."
        PRD 3.4: "The `feasibility_score` is one hundred multiplied by the sum of
        sixty-five hundredths of the alignment ratio and thirty-five hundredths of
        the cost factor, rounded half up to two decimal places."

        Design: Corner/calculations/corner_alternative_feasibility_score_weighted_components
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        statement_id = ctx["statement"]["id"]
        assert ctx["statement"]["goal_codes"] == ["ACCESS", "SAFETY", "HABITAT", "COST"]
        assert ctx["action"]["reference_cost_cents"] == 10000000

        no_action = validate_success(
            client.create_alternative(
                alternative_payload(action_id, **NO_ACTION_ALTERNATIVE),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        proposed = validate_success(
            client.create_alternative(alternative_payload(action_id),
                                      NEPA_COORDINATOR_HEADERS),
            expected_status=201,
        )
        high_cost = validate_success(
            client.create_alternative(
                alternative_payload(action_id, **HIGH_COST_ALTERNATIVE),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )

        assert no_action["feasibility_score"] == approx_score(35.00), (
            "no goal codes aligned, but the cost factor is a full 1.0"
        )
        assert proposed["feasibility_score"] == approx_score(76.75), (
            "three of four goal codes aligned against a cost factor of 0.8"
        )
        assert high_cost["feasibility_score"] == approx_score(16.25), (
            "one of four goal codes aligned and the cost factor floored at zero "
            "by a cost of three times the reference"
        )

        for alternative in (no_action, proposed, high_cost):
            assert_alternative(alternative)
            assert alternative["screening_status"] == "PROPOSED"
            assert alternative["pinned_pn_statement_id"] == statement_id, (
                "creation pins the alternative to whichever statement is adopted"
            )

    def test_below_minimum_feasibility_blocks_screen_in_except_for_no_action(
        self, client
    ):
        """The office minimum refuses the low-scoring reasonable-range
        alternative, while the no-action alternative is screened in on a still
        lower score.

        PRD 3.4: "Screening in additionally requires that the alternative's
        `alternative_kind` be `NO_ACTION`, or that its `feasibility_score` be
        greater than or equal to the office's `min_alternative_feasibility`; a
        no-action alternative is always eligible regardless of its score, because
        the range must always include it."
        PRD 3.4: "A non-no-action alternative below the office minimum is rejected
        with `ERR_ALTERNATIVE_NOT_FEASIBLE`."

        Design: Corner/errors/corner_error_alternative_not_feasible_rejects_screen_in
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        assert ctx["office"]["min_alternative_feasibility"] == approx_score(
            DEFAULT_MIN_ALTERNATIVE_FEASIBILITY
        )

        no_action = fixtures.create_alternative(action_id, **NO_ACTION_ALTERNATIVE)
        high_cost = fixtures.create_alternative(action_id, **HIGH_COST_ALTERNATIVE)

        refused = client.screen_alternative(
            high_cost["id"], screen_alternative_payload("SCREENED_IN"),
            REVIEWING_OFFICIAL_HEADERS,
        )
        validate_error(refused, ApiErrorId.ALTERNATIVE_NOT_FEASIBLE.value,
                       expected_status=409)
        assert fixtures.read_alternative(high_cost["id"])["screening_status"] == (
            "PROPOSED"
        ), "the refused screening leaves the alternative proposed"

        accepted = validate_success(
            client.screen_alternative(
                no_action["id"], screen_alternative_payload("SCREENED_IN"),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert accepted["screening_status"] == "SCREENED_IN"
        assert accepted["feasibility_score"] == approx_score(35.00), (
            "the no-action alternative is eligible below the office minimum"
        )
        assert fixtures.read_action(action_id)["alternatives_screened_in_count"] == 1, (
            "only the accepted screening moved the counter"
        )

    def test_stale_alternative_cannot_be_named_as_a_decision_selection(self, client):
        """An alternative left behind by a superseded statement is refused as
        stale when a decision names it, not as a plain coherence failure.

        PRD 3.4: "an alternative whose pinned statement has been superseded is
        rejected with `ERR_ALTERNATIVE_STALE`, and the same code applies when such
        an alternative is later named as a decision's selected alternative"
        PRD 3.4: "`STALE` and `SCREENED_OUT` are both terminal for an
        alternative."

        Design: Corner/errors/corner_error_alternative_stale_rejects_decision_selection
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        first_statement = ctx["statement"]
        alternative = fixtures.create_alternative(action_id)
        alternative = fixtures.screen_alternative(alternative["id"], "SCREENED_IN")
        assert alternative["screening_status"] == "SCREENED_IN"

        second_statement = fixtures.draft_purpose_need(
            action_id,
            purpose_text="Reduce hazardous fuel loading and restore stand structure",
            need_text="Revised fire behaviour modelling widens the treatment need",
            goal_codes=["ACCESS", "SAFETY"],
        )
        fixtures.adopt_purpose_need(second_statement["id"], action_id)

        refused = client.create_decision(
            decision_payload(action_id, alternative["id"], decision_type="FONSI"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.ALTERNATIVE_STALE.value,
                       expected_status=409)

        stale = fixtures.read_alternative(alternative["id"])
        assert stale["screening_status"] == "STALE"
        assert stale["pinned_pn_statement_id"] == first_statement["id"], (
            "the alternative stays pinned to the statement it was created against"
        )
        assert fixtures.read_statement(first_statement["id"])["status"] == "SUPERSEDED"
        assert fixtures.read_action(action_id)["alternatives_screened_in_count"] == 0

        _, meta = validate_paginated(
            client.list_decisions(NEPA_COORDINATOR_HEADERS,
                                  params={"action_id": action_id})
        )
        assert meta["total_count"] == 0, "the refused draft created no decision"
