"""Scoping periods and the issues recorded against them: the half-open interval
rule partitioned by kind, the parent-state dependency of issue creation, the two
close refusals, and the coverage count that finalisation and reopening conserve.
"""
from test_helpers import (
    NEPA_COORDINATOR_HEADERS,
    RESOURCE_SPECIALIST_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    approx_score,
    assert_scoping_period,
    assert_sequence_contiguous,
    entries_with_code,
    finalize_analysis_payload,
    find_entry,
    fixtures,
    issue_payload,
    scoping_period_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The canonical first public period: [2026-08-03, 2026-09-02).
FIRST_PUBLIC_PERIOD = {"start_at": "2026-08-03T00:00:00Z",
                       "end_at": "2026-09-02T00:00:00Z"}
#: A period beginning exactly where the first one ends.
ADJACENT_PUBLIC_PERIOD = {"start_at": "2026-09-02T00:00:00Z",
                          "end_at": "2026-10-02T00:00:00Z"}
#: A period sharing interior instants with the first one.
OVERLAPPING_PUBLIC_PERIOD = {"start_at": "2026-09-01T00:00:00Z",
                             "end_at": "2026-10-01T00:00:00Z"}


class TestScopingPeriodIntervals:
    """Periods occupy half-open intervals, and the collision test is partitioned
    by `scoping_kind`."""

    def test_touching_endpoints_are_accepted_but_a_shared_instant_is_not(self, client):
        """A period beginning exactly at the predecessor's `end_at` is accepted,
        while one starting a day earlier shares interior instants and is refused.

        PRD 2.7: "A scoping period occupies the half-open interval that begins at
        `start_at` inclusive and ends at `end_at` exclusive."
        PRD 2.7: "Two scoping periods on the same action with the same
        `scoping_kind` collide when the new period's `start_at` is strictly earlier
        than the existing period's `end_at` and the existing period's `start_at` is
        strictly earlier than the new period's `end_at`; comparison is strictly
        pairwise against each existing period, and touching endpoints do not
        collide, so a period beginning exactly when another ends is accepted."

        Design: Difficulty/resource_temporal_overlap/scoping_period_half_open_intervals_allow_adjacency_per_kind
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        first = fixtures.open_scoping_period(action_id, **FIRST_PUBLIC_PERIOD)
        assert first["duration_days"] == 30, (
            "thirty whole days elapse from 2026-08-03 to 2026-09-02"
        )
        assert first["status"] == "OPEN"
        assert_scoping_period(first)

        adjacent = validate_success(
            client.create_scoping_period(
                action_id,
                scoping_period_payload(scoping_kind="PUBLIC",
                                       **ADJACENT_PUBLIC_PERIOD),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert adjacent["duration_days"] == 30, (
            "the predecessor's end_at is exclusive, so the adjacent period is free"
        )
        assert adjacent["status"] == "OPEN"

        refused = client.create_scoping_period(
            action_id,
            scoping_period_payload(scoping_kind="PUBLIC",
                                   **OVERLAPPING_PUBLIC_PERIOD),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.SCOPING_PERIOD_OVERLAP.value,
                       expected_status=409)

        _, meta = validate_paginated(
            client.list_scoping_periods(action_id, NEPA_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 2, "the refused period created no row"

    def test_an_agency_period_may_coincide_with_a_public_one(self, client):
        """The collision test only compares periods of the same kind, so an agency
        period covering exactly the public interval is accepted.

        PRD 3.5: "Several periods may run on one action; a new period must not
        overlap an existing period of the same `scoping_kind` under the half-open
        rule of §2.7, and an overlap is rejected with
        `ERR_SCOPING_PERIOD_OVERLAP`."
        PRD 3.5: "Opening the first period advances the action `CLASSIFIED →
        SCOPING` and appends no record entry; opening an additional period while
        the stage is already `SCOPING` leaves `review_stage` untouched."

        Design: Difficulty/resource_temporal_overlap/scoping_period_half_open_intervals_allow_adjacency_per_kind
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        fixtures.open_scoping_period(action_id, **FIRST_PUBLIC_PERIOD)
        fixtures.open_scoping_period(action_id, scoping_kind="PUBLIC",
                                     **ADJACENT_PUBLIC_PERIOD)

        coinciding = validate_success(
            client.create_scoping_period(
                action_id,
                scoping_period_payload(scoping_kind="AGENCY", **FIRST_PUBLIC_PERIOD),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert coinciding["scoping_kind"] == "AGENCY"
        assert coinciding["duration_days"] == 30
        assert coinciding["status"] == "OPEN"

        rows, meta = validate_paginated(
            client.list_scoping_periods(action_id, NEPA_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 3, (
            "two public periods and one agency period coexist on the action"
        )
        assert len(rows) == 3

        action = fixtures.read_action(action_id)
        assert action["review_stage"] == "SCOPING", (
            "the first period advanced the stage and the later ones left it alone"
        )
        assert action["record_entry_count"] == 2, (
            "opening a scoping period appends no record entry"
        )


class TestClosingAScopingPeriod:
    """The two refusals that guard the close."""

    def test_close_without_an_adopted_statement_is_refused(self, client):
        """The period satisfies every one of its own preconditions, but the action
        carries only a draft statement.

        PRD 3.5: "A `NepaCoordinator` may close a period whose `status` is `OPEN`,
        provided the action already has a `PurposeNeedStatement` with `status`
        `ADOPTED` — a close attempted without one is rejected with
        `ERR_NO_ADOPTED_PURPOSE_NEED`."

        Design: Corner/state_machines/corner_close_scoping_period_without_adopted_purpose_need_is_rejected
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        statement = fixtures.draft_purpose_need(action_id)
        period = fixtures.open_scoping_period(action_id, **FIRST_PUBLIC_PERIOD)
        assert statement["status"] == "DRAFT"

        refused = client.close_scoping_period(period["id"], NEPA_COORDINATOR_HEADERS)
        validate_error(refused, ApiErrorId.NO_ADOPTED_PURPOSE_NEED.value,
                       expected_status=409)

        unchanged = validate_success(
            client.get_scoping_period(period["id"], NEPA_COORDINATOR_HEADERS)
        )
        assert unchanged["status"] == "OPEN"
        assert unchanged["duration_days"] == 30

        action = fixtures.read_action(action_id)
        assert action["review_stage"] == "SCOPING"
        assert action["record_entry_count"] == 2, (
            "the refused close appended no SCOPING_CLOSED entry"
        )

    def test_short_public_period_is_refused_while_an_agency_period_is_exempt(
        self, client
    ):
        """Twenty-nine whole days is one day under the office minimum for a public
        period, and the length rule does not reach an agency period.

        PRD 3.5: "A period whose `scoping_kind` is `PUBLIC` must additionally have
        `duration_days` greater than or equal to the office's `min_scoping_days`,
        or the close is rejected with `ERR_SCOPING_PERIOD_TOO_SHORT`; a period
        whose `scoping_kind` is `AGENCY` is exempt from that length rule
        entirely."
        PRD 3.5: "The action's stage advances `SCOPING → ANALYSIS` only once every
        `ScopingPeriod` of the action has `status` `CLOSED`; closing one of several
        still-open periods closes that period, leaves `review_stage` at `SCOPING`,
        and appends no record entry."

        Design: Corner/state_machines/corner_close_public_scoping_period_shorter_than_minimum_is_rejected
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        assert ctx["office"]["min_scoping_days"] == 30

        statement = fixtures.draft_purpose_need(action_id)
        short_public = fixtures.open_scoping_period(
            action_id, scoping_kind="PUBLIC",
            start_at="2026-08-03T00:00:00Z", end_at="2026-09-01T00:00:00Z",
        )
        agency_period = fixtures.open_scoping_period(
            action_id, scoping_kind="AGENCY",
            start_at="2026-09-05T00:00:00Z", end_at="2026-10-04T00:00:00Z",
        )
        fixtures.adopt_purpose_need(statement["id"], action_id)
        assert short_public["duration_days"] == 29
        assert agency_period["duration_days"] == 29

        refused = client.close_scoping_period(short_public["id"],
                                             NEPA_COORDINATOR_HEADERS)
        validate_error(refused, ApiErrorId.SCOPING_PERIOD_TOO_SHORT.value,
                       expected_status=409)
        assert fixtures.read_scoping_period(short_public["id"])["status"] == "OPEN"

        closed = validate_success(
            client.close_scoping_period(agency_period["id"],
                                        NEPA_COORDINATOR_HEADERS)
        )
        assert closed["status"] == "CLOSED", (
            "an agency period of the same length closes without objection"
        )
        assert fixtures.read_action(action_id)["review_stage"] == "SCOPING", (
            "a public period is still open, so the stage cannot advance"
        )


class TestIssueCreationDependsOnItsPeriod:
    """Whether an issue may be recorded depends on the state of the period it
    names, not on the issue or the action."""

    def test_issue_is_refused_once_the_named_period_is_closed(self, client):
        """The action is perfectly willing to accept issues; the closed period is
        the only obstacle.

        PRD 3.5: "A `NepaCoordinator` records one with a `scoping_period_id`
        naming a period that belongs to the same action and whose `status` is
        `OPEN`, a `resource_area` of `BIOLOGICAL`, `CULTURAL`, `AIR`, `WATER` or
        `SOCIOECONOMIC`, an `origin` of `PUBLIC` or `AGENCY` recording whether the
        input came from public or agency scoping, a `significance` of `SIGNIFICANT`
        or `NON_SIGNIFICANT` recording whether the issue must be carried into
        analysis, and a one-line `summary`."
        PRD 2.5: "State admissibility of the target row and of every row named in
        the transition's preconditions — `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/issue_creation_blocked_by_closed_scoping_period
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        period_id = ctx["scoping_period"]["id"]
        fixtures.record_issue(action_id, period_id)

        closed = fixtures.close_scoping_period(period_id)
        assert closed["status"] == "CLOSED"

        refused = client.create_issue(
            action_id,
            issue_payload(period_id, resource_area="WATER", origin="AGENCY",
                          significance="SIGNIFICANT",
                          summary="Downstream turbidity during culvert work"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.INVALID_STATE.value, expected_status=409)

        rows, meta = validate_paginated(
            client.list_issues(NEPA_COORDINATOR_HEADERS,
                               params={"action_id": action_id})
        )
        assert meta["total_count"] == 1, "no issue row was created"
        assert rows[0]["resource_area"] == "BIOLOGICAL"

        action = fixtures.read_action(action_id)
        assert action["significant_issue_count"] == 1
        assert action["unaddressed_issue_count"] == 1

    def test_the_identical_payload_succeeds_while_the_period_is_open(self, client):
        """The same body that is accepted while the period is open is refused once
        the period closes, so the parent's state is the only difference.

        PRD 3.5: "Issues are recorded against an action while a period is open."
        PRD 3.5: "The `significant_issue_count` is the number of that action's
        issues whose `significance` is `SIGNIFICANT` and whose `status` is either
        `OPEN` or `ANALYZED`."

        Design: Difficulty/cross_entity_state_dependency/issue_creation_blocked_by_closed_scoping_period
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        period_id = ctx["scoping_period"]["id"]
        body = issue_payload(period_id, resource_area="WATER", origin="AGENCY",
                             significance="SIGNIFICANT",
                             summary="Downstream turbidity during culvert work")

        accepted = validate_success(
            client.create_issue(action_id, body, NEPA_COORDINATOR_HEADERS),
            expected_status=201,
        )
        assert accepted["status"] == "OPEN"

        fixtures.close_scoping_period(period_id)

        refused = client.create_issue(action_id, body, NEPA_COORDINATOR_HEADERS)
        validate_error(refused, ApiErrorId.INVALID_STATE.value, expected_status=409)

        _, meta = validate_paginated(
            client.list_issues(NEPA_COORDINATOR_HEADERS,
                               params={"action_id": action_id})
        )
        assert meta["total_count"] == 1, (
            "only the submission made while the period was open created a row"
        )

        action = fixtures.read_action(action_id)
        assert action["review_stage"] == "ANALYSIS", (
            "closing the only period carried the review into analysis"
        )
        assert action["significant_issue_count"] == 1
        assert action["unaddressed_issue_count"] == 1


class TestUnaddressedIssueCoverage:
    """Finalisation and reopening conserve the coverage count exactly."""

    def _analysis_stage_context(self):
        """An action at ANALYSIS with one open significant biological issue, the
        four included baseline entries, and a draft biological analysis."""
        ctx = fixtures.setup_analysis_stage_action(
            with_issue=True, with_alternatives=False, with_consultation=False,
            with_baseline=True,
        )
        ctx["analysis"] = fixtures.open_analysis(ctx["action"]["id"])
        return ctx

    def test_finalizing_the_analysis_covers_the_open_significant_issue(self, client):
        """Finalisation moves the issue to `ANALYZED`, so the unaddressed count
        falls to zero while the significant count stays where it was.

        PRD 3.5: "The `unaddressed_issue_count` is the number of that action's
        issues whose `significance` is `SIGNIFICANT`, whose `status` is `OPEN`, and
        for which the action has no `ResourceAnalysis` on the same `resource_area`
        whose `status` is `FINAL`."
        PRD 3.7: "Finalisation moves the analysis `DRAFT → FINAL` and propagates
        outward. Every `Issue` of the action on the same `resource_area` whose
        `status` is `OPEN` moves `OPEN → ANALYZED`."

        Design: Difficulty/compensating_invariant/unaddressed_issue_coverage_restored_exactly_after_finalize_then_reopen
        """
        ctx = self._analysis_stage_context()
        action_id = ctx["action"]["id"]

        before = fixtures.read_action(action_id)
        assert before["unaddressed_issue_count"] == 1
        assert before["significant_issue_count"] == 1
        assert before["finalized_analysis_count"] == 0
        assert before["record_entry_count"] == 4, (
            "the screen adjudication, the classification, the adoption and the "
            "scoping close are the only recorded events so far"
        )

        validate_success(
            client.finalize_resource_analysis(
                ctx["analysis"]["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )

        after = fixtures.read_action(action_id)
        assert after["unaddressed_issue_count"] == 0, (
            "the biological issue is now addressed by a final analysis"
        )
        assert after["significant_issue_count"] == 1, (
            "an ANALYZED issue still counts as significant"
        )
        assert after["finalized_analysis_count"] == 1
        assert after["max_unmitigated_score"] == approx_score(70.21)
        assert after["cumulative_intensity_index"] == approx_score(60.04)
        assert after["record_entry_count"] == 5
        assert fixtures.read_issue(ctx["issue"]["id"])["status"] == "ANALYZED"

    def test_reopening_restores_the_count_and_leaves_the_record_intact(self, client):
        """Reopening returns the coverage count to exactly its pre-finalisation
        value while the record only grows.

        PRD 3.7: "Reopening clears `significance_score`,
        `significance_determination` and `variant_applied` back to null, moves
        every `Issue` of the action on the same `resource_area` whose `status` is
        `ANALYZED` back `ANALYZED → OPEN`, recomputes the same four action rollups,
        and appends an `ANALYSIS_REOPENED` entry with the corresponding increment
        to `record_entry_count`."
        PRD 2.4: "The action's `record_entry_count` is always the number of entries
        bearing that `action_id`, and it is monotonically non-decreasing: no
        operation, including a compensating one such as reopening an analysis or
        vacating a decision, ever deletes or renumbers an entry."

        Design: Difficulty/compensating_invariant/unaddressed_issue_coverage_restored_exactly_after_finalize_then_reopen
        """
        ctx = self._analysis_stage_context()
        action_id = ctx["action"]["id"]
        analysis_id = ctx["analysis"]["id"]

        pre_finalize_unaddressed = fixtures.read_action(action_id)[
            "unaddressed_issue_count"
        ]
        fixtures.finalize_analysis(analysis_id, "UNMITIGATED")
        finalized = fixtures.read_action(action_id)
        assert finalized["record_entry_count"] == 5

        reopened = validate_success(
            client.reopen_resource_analysis(analysis_id, RESOURCE_SPECIALIST_HEADERS)
        )
        assert reopened["status"] == "DRAFT"
        for field in ("significance_score", "significance_determination",
                      "variant_applied"):
            assert reopened[field] is None, (
                f"reopening clears {field} back to null"
            )

        after = fixtures.read_action(action_id)
        assert after["unaddressed_issue_count"] == pre_finalize_unaddressed == 1, (
            "the compensating move restores the coverage count exactly"
        )
        assert after["finalized_analysis_count"] == 0
        assert after["max_unmitigated_score"] == approx_score(0.00), (
            "no final analysis remains, so the rollup returns to its baseline"
        )
        assert after["cumulative_intensity_index"] == approx_score(0.00)
        assert after["significant_issue_count"] == 1
        assert fixtures.read_issue(ctx["issue"]["id"])["status"] == "OPEN"
        assert after["record_entry_count"] == 6, (
            "the reopening appended an entry rather than removing one"
        )

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert_sequence_contiguous(entries)
        assert len(entries_with_code(entries, "ANALYSIS_FINALIZED")) == 1
        reopen_entry = find_entry(entries, "ANALYSIS_REOPENED")
        assert reopen_entry is not None
        assert reopen_entry["sequence_no"] == 6, (
            "the reopening is the sixth recorded event on the action"
        )
