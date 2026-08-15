"""Committee rating aggregation: the pinned severity-precedence bands,
including the rejected majority-vote variant and the OFI-branch precedence
inside the MAJOR_OFI band."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instant_equals,
    finalize_deliberation,
    get_case,
    get_case_deliberation,
    parse_instant,
    setup_case_in_deliberation,
    validate_success,
)
from datetime import timedelta

QD = TEST_USERS["quality_director_headers"]


class TestSeverityPrecedenceBands:
    def test_single_care_score_of_one_yields_unacceptable(self):
        """PRD §3.5: "If at least one of the three care appropriateness scores
        is 1, the rating is `UNACCEPTABLE`."
        PRD §3.5: "This severity-precedence rule is pinned: the committee
        considered and rejected a majority-vote banding alternative, under
        which a case scored 1, 5, 5 with no OFI scores would have come out
        `APPROPRIATE` — under the pinned rule that combination is always
        `UNACCEPTABLE`."

        Design: Difficulty/dual_variant_calc/rating_severity_precedence_vs_majority_variant
        """
        ctx = setup_case_in_deliberation(scores=((1, None), (5, None), (5, None)))
        deliberation = finalize_deliberation(
            ctx["case"]["id"], ctx["chair"]["id"], "one unacceptable vote controls")
        assert deliberation["rating"] == "UNACCEPTABLE", (
            f"any care score of 1 must control the rating, got {deliberation['rating']}")
        assert deliberation["rating"] != "APPROPRIATE"
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "NOTIFIED"

    def test_finalize_creates_notification_with_fourteen_day_deadline(self):
        """PRD §3.5: "The case then moves to `NOTIFIED` with its `version`
        incremented, and the notification cascade creates the case's single
        ProviderNotification — exactly one per case — with `sent_at` stamped
        at the current logical time and `response_deadline` computed as
        exactly fourteen days after `sent_at`, to the second."

        Design: Difficulty/dual_variant_calc/rating_severity_precedence_vs_majority_variant
        """
        ctx = setup_case_in_deliberation(scores=((1, None), (5, None), (5, None)))
        finalize_deliberation(ctx["case"]["id"], ctx["chair"]["id"], "rationale")
        notifications = validate_success(
            api_client.list_case_notifications(ctx["case"]["id"], QD))
        assert len(notifications) == 1
        notification = notifications[0]
        assert_instant_equals(notification["sent_at"], "2026-08-01T00:00:00Z")
        expected_deadline = parse_instant(notification["sent_at"]) + timedelta(days=14)
        assert parse_instant(notification["response_deadline"]) == expected_deadline, (
            f"response_deadline must equal sent_at + 14 days exactly, got "
            f"{notification['response_deadline']}")

    def test_ofi_pair_reaches_major_ofi_without_care_majority(self):
        """PRD §3.5: "Otherwise, if at least two of the three care scores are
        2 or lower, or at least two of the submitted (non-null) OFI scores are
        4 or higher, the rating is `MAJOR_OFI`."

        Design: Difficulty/combinatorial_formula/rating_multi_input_branch_precedence
        """
        # C=[2,4,4], O=[4,4]: the care-count arm (needs >= 2 scores <= 2) does
        # not fire; the OFI arm (two OFI scores >= 4) does.
        ctx = setup_case_in_deliberation(scores=((2, 4), (4, 4), (4, None)))
        deliberation = finalize_deliberation(
            ctx["case"]["id"], ctx["chair"]["id"], "ofi branch")
        assert deliberation["rating"] == "MAJOR_OFI", (
            f"the OFI branch inside the MAJOR_OFI band preempts the "
            f"MINOR_OFI band, got {deliberation['rating']}")
        assert deliberation["rating"] not in ("MINOR_OFI", "UNACCEPTABLE")

    def test_major_ofi_rating_persisted_on_finalized_deliberation(self):
        """PRD §3.5: "On success the aggregation above runs, the
        Deliberation's `rating` is set, its status becomes `FINALIZED`, its
        `finalized_at` is stamped with the current logical time, its `version`
        increments, and the chair's optional `rationale_note` is stored."

        Design: Difficulty/combinatorial_formula/rating_multi_input_branch_precedence
        """
        ctx = setup_case_in_deliberation(scores=((2, 4), (4, 4), (4, None)))
        finalize_deliberation(ctx["case"]["id"], ctx["chair"]["id"], "ofi branch")
        rows = get_case_deliberation(ctx["case"]["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "FINALIZED"
        assert rows[0]["rating"] == "MAJOR_OFI"
        assert rows[0]["rationale_note"] == "ofi branch"
        assert_instant_equals(rows[0]["finalized_at"], "2026-08-01T00:00:00Z")

    def test_all_clean_scores_yield_appropriate(self):
        """PRD §3.5: "Otherwise the rating is `APPROPRIATE`."

        Design: Corner/calculations/rating_all_appropriate_no_ofi
        """
        ctx = setup_case_in_deliberation(scores=((5, None), (4, None), (5, None)))
        deliberation = finalize_deliberation(ctx["case"]["id"], ctx["chair"]["id"])
        assert deliberation["rating"] == "APPROPRIATE"

    def test_single_mild_ofi_yields_minor_ofi(self):
        """PRD §3.5: "Otherwise, if exactly one care score is 2 or lower, or
        exactly one submitted OFI score is 4 or higher, or at least one OFI
        score was submitted at all, the rating is `MINOR_OFI`."

        Design: Corner/calculations/rating_minor_via_single_mild_ofi
        """
        # C=[4,4,4], O=[3]: no care score <= 2, no OFI >= 4, but one OFI was
        # submitted, so the MINOR_OFI band fires on its third arm.
        ctx = setup_case_in_deliberation(scores=((4, 3), (4, None), (4, None)))
        deliberation = finalize_deliberation(ctx["case"]["id"], ctx["chair"]["id"])
        assert deliberation["rating"] == "MINOR_OFI", (
            f"a single submitted OFI below the severity floor still reaches "
            f"MINOR_OFI, got {deliberation['rating']}")
