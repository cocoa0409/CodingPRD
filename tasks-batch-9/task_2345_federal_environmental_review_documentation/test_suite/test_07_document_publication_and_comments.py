"""Publication, the comment period and response to comments: the two independent
axes of a NEPA document, the ordered publication gates, and the four counters the
comment traffic recomputes.
"""
from test_helpers import (
    DEFAULT_MIN_EA_COMMENT_DAYS,
    DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EA,
    NEPA_COORDINATOR_HEADERS,
    PUBLIC_COMMENTER_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    approx_score,
    assert_comment,
    assert_document,
    assert_instant_equals,
    comment_payload,
    comment_response_payload,
    document_payload,
    find_entry,
    fixtures,
    publish_document_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A comment period ten days long, well under the office minimum for an
#: environmental assessment.
SHORT_COMMENT_PERIOD_END = "2026-09-15T00:00:00Z"
#: One instant before the planned exclusive end of the comment period.
JUST_BEFORE_PERIOD_END = "2026-10-04T23:59:59Z"

#: The second and third substantive comments the design pins.
WATER_COMMENT = {
    "commenter_name": "K. Osei",
    "resource_area": "WATER",
    "is_substantive": True,
    "body": "Turbidity monitoring frequency is not specified",
}
AIR_COMMENT = {
    "commenter_name": "L. Marchetti",
    "resource_area": "AIR",
    "is_substantive": True,
    "body": "Smoke dispersion assumptions should cite the regional model",
}
THREE_SUBSTANTIVE_COMMENTS = [{}, WATER_COMMENT, AIR_COMMENT]

#: The water issue that no final analysis covers.
WATER_ISSUE = {
    "resource_area": "WATER",
    "origin": "PUBLIC",
    "significance": "SIGNIFICANT",
    "summary": "Downstream turbidity during culvert replacement",
}


def _draft_document_at_analysis(**opts):
    """An action at ANALYSIS with a DRAFT environmental assessment and the clock
    standing at the planned publication instant."""
    ctx = fixtures.setup_analysis_stage_action(**opts)
    ctx["document"] = fixtures.create_document(ctx["action"]["id"])
    fixtures.set_clock(fixtures.PUBLICATION_INSTANT)
    return ctx


class TestPublicationAndCommentAxes:
    """The publication axis and the comment axis are a product, not a chain."""

    def test_publish_moves_both_axes_and_closing_comments_moves_only_one(
        self, client
    ):
        """Publication is the single operation that advances both dimensions;
        closing the comment period leaves the publication dimension where it was.

        PRD 3.8: "A successful publication sets `publication_status` to `PUBLISHED`
        and `comment_status` to `OPEN`, records `comment_period_start_at` as the
        current logical time, computes `comment_period_days` as the floor of the
        elapsed days from that start to `comment_period_end_at`, advances the action
        `ANALYSIS → DRAFT_PUBLISHED`, and appends a `DOCUMENT_PUBLISHED` entry with
        the corresponding `record_entry_count` increment."
        PRD 3.8: "The move is `OPEN → CLOSED` on the comment axis, and
        `publication_status` is explicitly not changed — it remains `PUBLISHED`."

        Design: Difficulty/non_linear_state_machine/document_publication_and_comment_axes_advance_independently
        """
        ctx = _draft_document_at_analysis(with_baseline=True, with_analysis=True)
        action_id = ctx["action"]["id"]

        published = validate_success(
            client.publish_document(
                ctx["document"]["id"],
                publish_document_payload(fixtures.COMMENT_PERIOD_END),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert published["publication_status"] == "PUBLISHED"
        assert published["comment_status"] == "OPEN"
        assert_instant_equals(published["comment_period_start_at"],
                              fixtures.PUBLICATION_INSTANT,
                              "comment_period_start_at is the publication instant")
        assert published["comment_period_days"] == 30
        assert fixtures.read_action(action_id)["review_stage"] == "DRAFT_PUBLISHED"
        assert_document(published)

        fixtures.submit_comment(ctx["document"]["id"])
        fixtures.set_clock(fixtures.COMMENT_PERIOD_END)

        closed = validate_success(
            client.close_comment_period(ctx["document"]["id"],
                                        NEPA_COORDINATOR_HEADERS)
        )
        assert closed["comment_status"] == "CLOSED"
        assert closed["publication_status"] == "PUBLISHED", (
            "closing the comment period does not touch the publication axis"
        )
        assert fixtures.read_action(action_id)["review_stage"] == "COMMENT_CLOSED"

    def test_finalizing_moves_only_the_publication_axis(self, client):
        """With the comment axis already CLOSED, finalisation advances the
        publication axis alone and the comment axis stays where it is.

        PRD 3.8: "A `NepaCoordinator` may move `publication_status` `PUBLISHED →
        FINAL` only when `comment_status` is `CLOSED` and
        `unresolved_substantive_count` is exactly zero; a residual unresolved
        substantive comment is rejected with `ERR_UNRESOLVED_COMMENTS`."
        PRD 3.8: "The comment dimension, `comment_status`, runs through `NOT_OPEN`,
        `OPEN` and `CLOSED`."

        Design: Difficulty/non_linear_state_machine/document_publication_and_comment_axes_advance_independently
        """
        ctx = fixtures.setup_comment_closed_document(with_baseline=True)
        action_id = ctx["action"]["id"]
        document_id = ctx["document"]["id"]
        assert ctx["document"]["comment_status"] == "CLOSED"
        assert ctx["document"]["publication_status"] == "PUBLISHED"

        responded = validate_success(
            client.respond_to_comment(
                ctx["comments"][0]["id"],
                comment_response_payload("ANALYSIS_REVISED"),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert responded["disposition"] == "RESPONDED"
        assert_comment(responded)

        answered = fixtures.read_document(document_id)
        assert answered["substantive_comment_count"] == 1
        assert answered["responded_substantive_count"] == 1
        assert answered["unresolved_substantive_count"] == 0
        assert answered["response_completeness_pct"] == approx_score(100.00)

        finalized = validate_success(
            client.finalize_document(document_id, NEPA_COORDINATOR_HEADERS)
        )
        assert finalized["publication_status"] == "FINAL"
        assert finalized["comment_status"] == "CLOSED", (
            "the comment axis has already run its course and does not move again"
        )
        assert fixtures.read_action(action_id)["review_stage"] == "COMMENT_CLOSED", (
            "the stage advanced when the comment period closed, not on finalisation"
        )


class TestPublishGateOrdering:
    """The publication gates are checked in the order the contract states them."""

    def test_an_unfinished_required_consultation_outranks_a_short_period(
        self, client
    ):
        """With both defects present the response names the consultation gate.

        PRD 3.8: "For every consultation track in the action's required set, there
        must be a `ConsultationRequest` of that `consultation_type` whose `status`
        is `CONCURRED` or `CONDITIONAL_CONCURRENCE`; a missing or unfinished
        required track is rejected with `ERR_REQUIRED_CONSULTATION_INCOMPLETE`."
        PRD 2.5: "Publication completeness at publish time: unaddressed significant
        issues, then required consultations."

        Design: Difficulty/priority_pair_validation_conflict/publish_consultation_completeness_outranks_comment_period_length
        """
        ctx = _draft_document_at_analysis(with_issue=False, with_baseline=False,
                                         respond_consultation_flag=False)
        action_id = ctx["action"]["id"]
        assert ctx["consultation"]["status"] == "PENDING"

        refused = client.publish_document(
            ctx["document"]["id"],
            publish_document_payload(SHORT_COMMENT_PERIOD_END),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.REQUIRED_CONSULTATION_INCOMPLETE.value,
                       expected_status=409)

        consultation = fixtures.read_consultation(ctx["consultation"]["id"])
        assert consultation["status"] == "PENDING"
        assert consultation["is_required"] is True

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "DRAFT"
        assert document["comment_status"] == "NOT_OPEN"
        assert document["comment_period_start_at"] is None
        assert document["comment_period_days"] == 0
        assert fixtures.read_action(action_id)["review_stage"] == "ANALYSIS"

    def test_the_period_length_gate_surfaces_only_once_the_consultation_concurs(
        self, client
    ):
        """The lower-priority temporal gate is reached only after the consultation
        gate is satisfied, and a full-length period then publishes.

        PRD 3.8: "Finally, the number of whole days from the current logical time
        to `comment_period_end_at` must be at least the office minimum for the
        document type — `min_ea_comment_days` for an environmental assessment and
        `min_eis_comment_days` for an environmental impact statement — or the
        request is rejected with `ERR_COMMENT_PERIOD_TOO_SHORT`."
        PRD 2.5: "Interval, duration and deadline rules — `ERR_TEMPORAL_CONFLICT`
        and its specialisations."

        Design: Difficulty/priority_pair_validation_conflict/publish_consultation_completeness_outranks_comment_period_length
        """
        ctx = _draft_document_at_analysis(with_issue=False, with_baseline=False,
                                         respond_consultation_flag=False)
        assert ctx["office"]["min_ea_comment_days"] == DEFAULT_MIN_EA_COMMENT_DAYS

        concurred = fixtures.respond_consultation(ctx["consultation"]["id"],
                                                 ctx["agency"]["id"], "CONCURRED")
        assert concurred["status"] == "CONCURRED"

        still_refused = client.publish_document(
            ctx["document"]["id"],
            publish_document_payload(SHORT_COMMENT_PERIOD_END),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(still_refused, ApiErrorId.COMMENT_PERIOD_TOO_SHORT.value,
                       expected_status=409)
        assert fixtures.read_document(ctx["document"]["id"])[
            "publication_status"
        ] == "DRAFT"

        published = validate_success(
            client.publish_document(
                ctx["document"]["id"],
                publish_document_payload(fixtures.COMMENT_PERIOD_END),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert published["publication_status"] == "PUBLISHED"
        assert published["comment_status"] == "OPEN"
        assert published["comment_period_days"] == 30, (
            "thirty whole days meets the office minimum exactly"
        )

    def test_an_empty_screened_in_range_is_refused(self, client):
        """A screened-in count of zero fails the alternatives minimum.

        PRD 3.8: "The action's `alternatives_screened_in_count` must be at least
        the office minimum for the document type — `min_screened_in_alternatives_ea`
        for an environmental assessment and `min_screened_in_alternatives_eis` for
        an environmental impact statement — or the request is rejected with
        `ERR_INSUFFICIENT_ALTERNATIVES`."
        PRD 3.4: "A successful `PROPOSED → SCREENED_IN` increments the action's
        `alternatives_screened_in_count` by one; a `PROPOSED → SCREENED_OUT` changes
        no counter."

        Design: Difficulty/boundary_precision_check/publish_rejected_when_screened_in_alternative_count_is_zero
        """
        ctx = _draft_document_at_analysis(with_issue=False, with_baseline=False,
                                         screen_alternatives=False)
        action_id = ctx["action"]["id"]
        assert ctx["office"]["min_screened_in_alternatives_ea"] == (
            DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EA
        )
        fixtures.screen_alternative(ctx["alt_a"]["id"], "SCREENED_OUT")
        assert fixtures.read_action(action_id)["alternatives_screened_in_count"] == 0, (
            "one alternative was eliminated and the other is still only proposed"
        )

        refused = client.publish_document(
            ctx["document"]["id"],
            publish_document_payload(fixtures.COMMENT_PERIOD_END),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.INSUFFICIENT_ALTERNATIVES.value,
                       expected_status=409)

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "DRAFT"
        assert document["comment_status"] == "NOT_OPEN"
        assert fixtures.read_action(action_id)["review_stage"] == "ANALYSIS"

    def test_a_single_screened_in_alternative_is_enough(self, client):
        """The very next count above the empty range clears the same gate.

        PRD 2.10: "`min_screened_in_alternatives_ea` is the number of screened-in
        alternatives an environmental assessment must have behind it before
        publication, defaulting to 1 and required to be non-negative, and
        `min_screened_in_alternatives_eis` is the corresponding number for an
        environmental impact statement, defaulting to 2 and required to be at least
        `min_screened_in_alternatives_ea`."
        PRD 3.4: "The `feasibility_score` is one hundred multiplied by the sum of
        sixty-five hundredths of the alignment ratio and thirty-five hundredths of
        the cost factor, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/publish_rejected_when_screened_in_alternative_count_is_zero
        """
        ctx = _draft_document_at_analysis(with_issue=False, with_baseline=False,
                                         screen_alternatives=False)
        action_id = ctx["action"]["id"]
        fixtures.screen_alternative(ctx["alt_a"]["id"], "SCREENED_OUT")

        screened_in = fixtures.screen_alternative(ctx["alt_b"]["id"], "SCREENED_IN")
        assert screened_in["screening_status"] == "SCREENED_IN"
        assert screened_in["feasibility_score"] == approx_score(76.75)
        assert fixtures.read_action(action_id)["alternatives_screened_in_count"] == 1

        published = validate_success(
            client.publish_document(
                ctx["document"]["id"],
                publish_document_payload(fixtures.COMMENT_PERIOD_END),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert published["publication_status"] == "PUBLISHED"
        assert published["comment_status"] == "OPEN"
        assert published["comment_period_days"] == 30

    def test_an_uncovered_significant_issue_blocks_publication(self, client):
        """A significant water issue with no final water analysis is the refusal,
        even though the required consultation has concurred.

        PRD 3.8: "The action's `unaddressed_issue_count` must be exactly zero, or
        the request is rejected with `ERR_UNADDRESSED_ISSUES`."
        PRD 3.5: "The `unaddressed_issue_count` is the number of that action's
        issues whose `significance` is `SIGNIFICANT`, whose `status` is `OPEN`, and
        for which the action has no `ResourceAnalysis` on the same `resource_area`
        whose `status` is `FINAL`."

        Design: Corner/errors/corner_error_unaddressed_issues_rejects_publish
        """
        ctx = fixtures.setup_scoping_action()
        action_id = ctx["action"]["id"]
        issue = fixtures.record_issue(action_id, ctx["scoping_period"]["id"],
                                      **WATER_ISSUE)
        ctx = fixtures.setup_alternatives(ctx)
        ctx = fixtures.setup_required_consultation(ctx)
        fixtures.close_scoping_period(ctx["scoping_period"]["id"])
        analysis = fixtures.open_analysis(action_id)
        fixtures.finalize_analysis(analysis["id"], "UNMITIGATED")
        document = fixtures.create_document(action_id)
        fixtures.set_clock(fixtures.PUBLICATION_INSTANT)

        refused = client.publish_document(
            document["id"],
            publish_document_payload(fixtures.COMMENT_PERIOD_END),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.UNADDRESSED_ISSUES.value,
                       expected_status=409)

        action = fixtures.read_action(action_id)
        assert action["unaddressed_issue_count"] == 1, (
            "the biological analysis covers no water issue"
        )
        assert action["significant_issue_count"] == 1
        assert fixtures.read_issue(issue["id"])["status"] == "OPEN"
        assert fixtures.read_consultation(ctx["consultation"]["id"])["status"] == (
            "CONCURRED"
        )

        document = fixtures.read_document(document["id"])
        assert document["publication_status"] == "DRAFT"
        assert document["comment_status"] == "NOT_OPEN"

    def test_publication_succeeds_when_every_gate_is_satisfied(self, client):
        """The positive control for the whole gate stack.

        PRD 3.8: "Publication is the only operation that advances both axes at
        once, and it is heavily gated."
        PRD 3.8: "The document's `publication_status` must be `DRAFT`, its
        `document_type` must still match the action's `classification`, and the
        action's `review_stage` must be `ANALYSIS`."

        Design: Corner/validations/corner_publish_with_every_condition_satisfied_succeeds
        """
        ctx = _draft_document_at_analysis(**fixtures.NO_ISSUE_NO_BASELINE_NO_ANALYSIS)
        action_id = ctx["action"]["id"]

        published = validate_success(
            client.publish_document(
                ctx["document"]["id"],
                publish_document_payload(fixtures.COMMENT_PERIOD_END),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert published["publication_status"] == "PUBLISHED"
        assert published["comment_status"] == "OPEN"
        assert_instant_equals(published["comment_period_start_at"],
                              fixtures.PUBLICATION_INSTANT)
        assert_instant_equals(published["comment_period_end_at"],
                              fixtures.COMMENT_PERIOD_END)
        assert published["comment_period_days"] == 30

        action = fixtures.read_action(action_id)
        assert action["review_stage"] == "DRAFT_PUBLISHED"
        assert action["alternatives_screened_in_count"] == 2
        assert action["unaddressed_issue_count"] == 0

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert find_entry(entries, "DOCUMENT_PUBLISHED") is not None

    def test_the_publish_response_already_carries_the_derived_fields(self, client):
        """No follow-up read is needed: the publish response is already the
        settled state, and the subsequent reads repeat it.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD 3.8: "The `response_completeness_pct` is exactly 100.00 when
        `substantive_comment_count` is zero, and otherwise one hundred multiplied by
        `responded_substantive_count` divided by `substantive_comment_count`,
        rounded half up to two decimal places."

        Design: Corner/consistency_model/corner_publish_response_already_carries_every_derived_field
        """
        ctx = _draft_document_at_analysis(**fixtures.NO_ISSUE_NO_BASELINE_NO_ANALYSIS)
        action_id = ctx["action"]["id"]

        published = validate_success(
            client.publish_document(
                ctx["document"]["id"],
                publish_document_payload(fixtures.COMMENT_PERIOD_END),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert published["publication_status"] == "PUBLISHED"
        assert published["comment_status"] == "OPEN"
        assert published["comment_period_days"] == 30
        assert published["response_completeness_pct"] == approx_score(100.00), (
            "with no substantive comment yet the completeness is fully satisfied"
        )

        reread = validate_success(
            client.get_document(ctx["document"]["id"], NEPA_COORDINATOR_HEADERS)
        )
        for field in ("publication_status", "comment_status", "comment_period_days",
                      "comment_period_start_at", "comment_period_end_at",
                      "response_completeness_pct", "version"):
            assert reread[field] == published[field], (
                f"{field} differs between the write response and the following "
                f"read, with no intervening write"
            )

        action = validate_success(
            client.get_proposed_action(action_id, NEPA_COORDINATOR_HEADERS)
        )
        assert action["review_stage"] == "DRAFT_PUBLISHED"
        assert action["record_entry_count"] >= 1

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert action["record_entry_count"] == len(entries)
        entry = find_entry(entries, "DOCUMENT_PUBLISHED")
        assert entry is not None
        assert_instant_equals(entry["occurred_at"], fixtures.PUBLICATION_INSTANT,
                              "the entry is stamped with the publication instant")


class TestDocumentInitialStateAndAxisGuards:
    """Drafting, closing and finalising each read the axis they belong to."""

    def test_a_new_document_is_draft_with_its_comment_axis_not_open(self, client):
        """Creation places the document at the product initial state with an empty
        comment window and empty counters.

        PRD 3.8: "A new document is `DRAFT` on the publication axis and `NOT_OPEN`
        on the comment axis, with `comment_period_start_at` and
        `comment_period_end_at` null and `comment_period_days` at 0."
        PRD 3.8: "The publication dimension, `publication_status`, runs through
        `DRAFT`, `PUBLISHED`, `FINAL` and the terminal `SUPERSEDED`."

        Design: Corner/state_machines/corner_new_document_starts_draft_with_comment_axis_not_open
        """
        ctx = fixtures.setup_analysis_stage_action(with_issue=False,
                                                  with_baseline=False)
        action_id = ctx["action"]["id"]

        created = validate_success(
            client.create_document(action_id, document_payload(),
                                   NEPA_COORDINATOR_HEADERS),
            expected_status=201,
        )
        assert created["publication_status"] == "DRAFT"
        assert created["comment_status"] == "NOT_OPEN"
        assert created["comment_period_start_at"] is None
        assert created["comment_period_end_at"] is None
        assert created["comment_period_days"] == 0
        assert created["substantive_comment_count"] == 0
        assert created["responded_substantive_count"] == 0
        assert created["unresolved_substantive_count"] == 0
        assert created["version"] == 1
        assert_document(created)
        assert fixtures.read_action(action_id)["review_stage"] == "ANALYSIS", (
            "drafting a document does not advance the review stage"
        )

    def test_finalizing_while_the_comment_axis_is_open_is_refused(self, client):
        """The publication axis cannot overtake the comment axis.

        PRD 3.8: "Finalising the document is the last publication-axis step before
        a decision may be signed."
        PRD 2.5: "State admissibility of the target row and of every row named in
        the transition's preconditions — `ERR_INVALID_STATE`."

        Design: Corner/state_machines/corner_finalize_document_while_comment_axis_open_is_rejected
        """
        ctx = fixtures.setup_published_document(**fixtures.NO_ISSUE_NO_BASELINE)
        action_id = ctx["action"]["id"]

        refused = client.finalize_document(ctx["document"]["id"],
                                          NEPA_COORDINATOR_HEADERS)
        validate_error(refused, ApiErrorId.INVALID_STATE.value, expected_status=409)

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "PUBLISHED", (
            "the refused finalisation leaves both axes untouched"
        )
        assert document["comment_status"] == "OPEN"
        assert document["comment_period_days"] == 30
        assert fixtures.read_action(action_id)["review_stage"] == "DRAFT_PUBLISHED"

    def test_closing_the_comment_period_before_its_end_instant_is_refused(
        self, client
    ):
        """One second before the planned end the close is refused; at the end
        instant itself it succeeds.

        PRD 3.8: "A `NepaCoordinator` may do so when the document's
        `comment_status` is `OPEN` and the current logical time is at or after
        `comment_period_end_at`; an earlier attempt is rejected with
        `ERR_COMMENT_PERIOD_NOT_ENDED`."
        PRD 3.8: "Closing the comment period touches only the comment axis."

        Design: Corner/state_machines/corner_close_comment_period_before_end_instant_is_rejected
        """
        ctx = fixtures.setup_published_document(**fixtures.NO_ISSUE_NO_BASELINE)
        document_id = ctx["document"]["id"]

        fixtures.set_clock(JUST_BEFORE_PERIOD_END)
        too_early = client.close_comment_period(document_id,
                                                NEPA_COORDINATOR_HEADERS)
        validate_error(too_early, ApiErrorId.COMMENT_PERIOD_NOT_ENDED.value,
                       expected_status=409)
        assert fixtures.read_document(document_id)["comment_status"] == "OPEN"

        fixtures.set_clock(fixtures.COMMENT_PERIOD_END)
        closed = validate_success(
            client.close_comment_period(document_id, NEPA_COORDINATOR_HEADERS)
        )
        assert closed["comment_status"] == "CLOSED", (
            "the end instant itself is late enough to close the period"
        )
        assert closed["publication_status"] == "PUBLISHED"


class TestCommentSubmissionWindow:
    """A comment may only be submitted while the comment axis is OPEN."""

    def test_a_comment_is_refused_once_the_comment_axis_has_closed(self, client):
        """The document is still PUBLISHED, yet the closed comment axis alone
        refuses the submission.

        PRD 3.8: "Submitting against a document whose `comment_status` is anything
        other than `OPEN` is rejected with `ERR_COMMENT_PERIOD_NOT_OPEN`."
        PRD 3.8: "The `substantive_comment_count` is the number of that document's
        comments whose `is_substantive` is true and whose `disposition` is
        `RECEIVED` or `RESPONDED`."

        Design: Difficulty/cross_entity_state_dependency/comment_creation_blocked_by_closed_document_comment_axis
        """
        ctx = fixtures.setup_comment_closed_document(with_baseline=True)
        document_id = ctx["document"]["id"]

        refused = client.create_comment(
            comment_payload(document_id, **WATER_COMMENT), PUBLIC_COMMENTER_HEADERS
        )
        validate_error(refused, ApiErrorId.COMMENT_PERIOD_NOT_OPEN.value,
                       expected_status=409)

        document = fixtures.read_document(document_id)
        assert document["publication_status"] == "PUBLISHED", (
            "the parent document is untouched; only its comment axis has closed"
        )
        assert document["comment_status"] == "CLOSED"
        assert document["substantive_comment_count"] == 1
        assert document["unresolved_substantive_count"] == 1

        rows, meta = validate_paginated(
            client.list_comments(NEPA_COORDINATOR_HEADERS,
                                 params={"document_id": document_id})
        )
        assert meta["total_count"] == 1, "the refused submission created no comment"
        assert len(rows) == 1

    def test_the_same_payload_is_refused_before_publication_and_taken_after_it(
        self, client
    ):
        """`NOT_OPEN` is refused with the same code as `CLOSED`, and the identical
        payload is accepted the moment the axis opens.

        PRD 3.8: "While a document's `comment_status` is `OPEN`, a
        `PublicCommenter` may submit a comment naming the `document_id`, an optional
        `assigned_issue_id` mapping the comment onto a tracked scoping issue and
        defaulting to null when the comment raises no tracked issue, a
        `commenter_name`, a `resource_area`, an optional `is_substantive` flag
        defaulting to false that records whether a written response is required, and
        the comment `body`."
        PRD 3.8: "A new comment has `disposition` `RECEIVED`, with `response_text`
        and `response_category` null."

        Design: Difficulty/cross_entity_state_dependency/comment_creation_blocked_by_closed_document_comment_axis
        """
        ctx = _draft_document_at_analysis(with_issue=False, with_baseline=False)
        document_id = ctx["document"]["id"]
        assert ctx["document"]["comment_status"] == "NOT_OPEN"

        too_early = client.create_comment(
            comment_payload(document_id, **WATER_COMMENT), PUBLIC_COMMENTER_HEADERS
        )
        validate_error(too_early, ApiErrorId.COMMENT_PERIOD_NOT_OPEN.value,
                       expected_status=409)

        fixtures.publish_document(document_id, fixtures.COMMENT_PERIOD_END)

        accepted = validate_success(
            client.create_comment(comment_payload(document_id, **WATER_COMMENT),
                                  PUBLIC_COMMENTER_HEADERS),
            expected_status=201,
        )
        assert accepted["disposition"] == "RECEIVED"
        assert accepted["response_text"] is None
        assert accepted["response_category"] is None
        assert accepted["assigned_issue_id"] is None
        assert_comment(accepted)

        document = fixtures.read_document(document_id)
        assert document["substantive_comment_count"] == 1
        assert document["responded_substantive_count"] == 0
        assert document["unresolved_substantive_count"] == 1
        assert document["response_completeness_pct"] == approx_score(0.00)


class TestResponseToComments:
    """The four counters, and what an out-of-scope response does to them."""

    def test_one_response_out_of_three_is_stored_as_thirty_three_and_a_third(
        self, client
    ):
        """The non-terminating ratio is carried at two decimals.

        PRD 2.8: "Scores, percentages and credit quantities are carried to exactly
        two decimal places and rounded half up."
        PRD 3.8: "Any category other than `OUT_OF_SCOPE` records both fields and
        moves the comment `RECEIVED → RESPONDED`, which raises
        `responded_substantive_count`, lowers `unresolved_substantive_count` and
        lifts `response_completeness_pct`."

        Design: Corner/calculations/corner_response_completeness_pct_rounds_half_up_to_two_decimals
        """
        ctx = fixtures.setup_comment_closed_document(
            comments=THREE_SUBSTANTIVE_COMMENTS, with_baseline=True
        )
        document_id = ctx["document"]["id"]

        responded = validate_success(
            client.respond_to_comment(
                ctx["comments"][0]["id"],
                comment_response_payload("ANALYSIS_REVISED"),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert responded["disposition"] == "RESPONDED"
        assert responded["response_category"] == "ANALYSIS_REVISED"

        document = fixtures.read_document(document_id)
        assert document["substantive_comment_count"] == 3
        assert document["responded_substantive_count"] == 1
        assert document["unresolved_substantive_count"] == 2
        assert document["response_completeness_pct"] == approx_score(33.33), (
            "one third is carried to two decimals rather than truncated"
        )

    def test_an_out_of_scope_response_shrinks_the_denominator(self, client):
        """A duplicate-dispositioned comment leaves both counters, so completeness
        rises without the responded count moving.

        PRD 3.8: "An `OUT_OF_SCOPE` category records both fields, with
        `response_category` set to `OUT_OF_SCOPE`, and moves the comment `RECEIVED →
        DUPLICATE`, which removes it from `substantive_comment_count` altogether and
        recomputes `response_completeness_pct` over the smaller denominator."
        PRD 3.8: "Comments dispositioned `DUPLICATE` drop out of both counters."

        Design: Corner/cross_cutting_complexity_layers/corner_document_counters_reconcile_after_out_of_scope_response
        """
        ctx = fixtures.setup_comment_closed_document(
            comments=THREE_SUBSTANTIVE_COMMENTS, with_baseline=True
        )
        document_id = ctx["document"]["id"]
        fixtures.respond_comment(ctx["comments"][0]["id"], "ANALYSIS_REVISED")
        assert fixtures.read_document(document_id)[
            "response_completeness_pct"
        ] == approx_score(33.33)

        out_of_scope = validate_success(
            client.respond_to_comment(
                ctx["comments"][1]["id"],
                comment_response_payload(
                    "OUT_OF_SCOPE",
                    response_text=("Turbidity permitting is administered under a "
                                   "separate authority"),
                ),
                NEPA_COORDINATOR_HEADERS,
            )
        )
        assert out_of_scope["disposition"] == "DUPLICATE"
        assert out_of_scope["response_category"] == "OUT_OF_SCOPE"
        assert out_of_scope["is_substantive"] is True, (
            "the flag is unchanged; only the disposition excludes the comment"
        )

        document = fixtures.read_document(document_id)
        assert document["substantive_comment_count"] == 2
        assert document["responded_substantive_count"] == 1, (
            "the numerator did not move; the denominator shrank"
        )
        assert document["unresolved_substantive_count"] == 1
        assert document["response_completeness_pct"] == approx_score(50.00)

        blocked = client.finalize_document(document_id, NEPA_COORDINATOR_HEADERS)
        validate_error(blocked, ApiErrorId.UNRESOLVED_COMMENTS.value,
                       expected_status=409)

    def test_an_unanswered_substantive_comment_blocks_finalization(self, client):
        """Finalisation reads the unresolved count, not the comment period, and the
        same call succeeds once the response is prepared.

        PRD 3.8: "The `unresolved_substantive_count` is the first figure minus the
        second."
        PRD 3.8: "Finalisation appends a `DOCUMENT_FINALIZED` entry and increments
        `record_entry_count`."

        Design: Corner/errors/corner_error_unresolved_comments_rejects_document_finalize
        """
        ctx = fixtures.setup_comment_closed_document(with_baseline=True)
        action_id = ctx["action"]["id"]
        document_id = ctx["document"]["id"]

        refused = client.finalize_document(document_id, NEPA_COORDINATOR_HEADERS)
        validate_error(refused, ApiErrorId.UNRESOLVED_COMMENTS.value,
                       expected_status=409)

        pending = fixtures.read_document(document_id)
        assert pending["publication_status"] == "PUBLISHED"
        assert pending["comment_status"] == "CLOSED"
        assert pending["unresolved_substantive_count"] == 1
        assert pending["response_completeness_pct"] == approx_score(0.00)

        fixtures.respond_comment(ctx["comments"][0]["id"], "ANALYSIS_REVISED")
        answered = fixtures.read_document(document_id)
        assert answered["unresolved_substantive_count"] == 0
        assert answered["response_completeness_pct"] == approx_score(100.00)

        finalized = validate_success(
            client.finalize_document(document_id, NEPA_COORDINATOR_HEADERS)
        )
        assert finalized["publication_status"] == "FINAL"
        assert fixtures.read_action(action_id)["review_stage"] == "COMMENT_CLOSED"

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert find_entry(entries, "DOCUMENT_FINALIZED") is not None
