"""Field-level rules at the exact point where they flip.

Completion is equality rather than a ratio, the deadline comparison is strict,
remote access needs both authorisations, and the cumulative progress counters are
non-strict upward and strict downward.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_money, assert_pace_2dp, assert_status
from test_helpers.factories import assignment_payload, progress_payload, session_payload
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestSubmitWithIncompleteCodingRejected:
    """One document short of the batch is still short."""

    def test_three_hundred_and_ninety_nine_of_four_hundred_is_refused_and_bills_nothing(
        self, started_assignment
    ):
        """PRD §3.7: "Two completeness conditions must hold, and both produce
        `ERR_ASSIGNMENT_INCOMPLETE`: `documents_coded` must equal the batch's
        `document_count`, and `privilege_hits_logged` must equal the number of privilege
        log entries this reviewer has actually authored on this batch."

        Billing is frozen at submit, so the refused submit leaves the ledger holding
        nothing but the original commitment.

        Design: Corner/validations/submit_with_incomplete_coding_rejected
        """
        ladder = started_assignment["ladder"]
        assignment_id = started_assignment["assignment_id"]
        ada_id = started_assignment["ada_id"]

        ladder.progress(assignment_id, ada_id, 399, 420)

        validate_error(
            ladder.api.submit_assignment(
                assignment_id, started_assignment["ada_headers"]
            ),
            e.ERR_ASSIGNMENT_INCOMPLETE,
            409,
        )

        assignment = ladder.read_assignment(assignment_id)
        assert_status(assignment, "IN_PROGRESS")
        assert assignment["documents_coded"] == 399
        assert_money(assignment["billable_amount_cents"], 0, "billable_amount_cents")
        assert assignment["billable_minutes"] == 0

        rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                assignment_id, ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("COMMITMENT", 85200)
        ]

        assert_status(ladder.read_batch(started_assignment["batch_id"]), "IN_PROGRESS")

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, STAFFING_COORDINATOR, limit=100)
        )
        assert events == []


class TestDeadlineGateIsStrictlyBeforeTheDeadline:
    """Standing exactly on the deadline is already too late."""

    def test_one_second_earlier_the_identical_assignment_is_accepted(
        self, batched_matter
    ):
        """PRD §2.5: "The logical clock is strictly before the matter's `deadline_utc` —
        otherwise `ERR_MATTER_DEADLINE_PASSED` (HTTP 409), on batch carving,
        named-reviewer assignment creation and auto-assignment."

        The refusal leaves the batch untouched at version one, so the very same version
        guard still fits the retry a second before the deadline.

        Design: Corner/validations/deadline_gate_is_strictly_before_the_deadline
        """
        ladder = batched_matter["ladder"]
        batch_id = batched_matter["batch_id"]
        batch_version = batched_matter["batch_version"]

        ladder.set_clock("2026-09-30T00:00:00Z")
        validate_error(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(
                    batch_version, batched_matter["ada_id"], "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            e.ERR_MATTER_DEADLINE_PASSED,
            409,
        )

        refused = ladder.read_batch(batch_id)
        assert_status(refused, "CREATED")
        assert refused["version"] == batch_version == 1

        ladder.set_clock("2026-09-29T23:59:59Z")
        created = validate_success(
            ladder.api.create_assignment(
                batch_id,
                assignment_payload(
                    batch_version, batched_matter["ada_id"], "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_money(
            created["committed_amount_cents"], 85200, "committed_amount_cents"
        )
        assert created["created_at"].startswith("2026-09-29T23:59:59")

        assigned = ladder.read_batch(batch_id)
        assert_status(assigned, "ASSIGNED")
        assert assigned["version"] == 2


class TestRemoteSessionRequiresBothAuthorisationFlags:
    """The matter permits remote work; the reviewer must be cleared for it too."""

    def test_the_gate_is_conditional_on_the_workstation_class(
        self, two_reviewer_matter
    ):
        """PRD §3.5: "A `REMOTE_VDI` window is gated by three independent authorisations
        that must **all** be true — the matter's `remote_work_permitted`, the reviewer's
        `remote_work_authorized`, and the `remote_work_addendum` on the governing
        executed agreement — and any of the three being false is refused with
        `ERR_REMOTE_WORK_NOT_AUTHORIZED`."

        The reviewer without the addendum is refused a remote seat yet allowed the
        identical window onsite, while the reviewer who holds it is admitted.

        Design: Corner/validations/remote_session_requires_both_authorisation_flags
        """
        ladder = two_reviewer_matter["ladder"]
        matter_id = two_reviewer_matter["matter_id"]

        validate_error(
            ladder.api.create_session(
                session_payload(
                    two_reviewer_matter["ada_id"],
                    matter_id,
                    workstation_class="REMOTE_VDI",
                ),
                two_reviewer_matter["ada_headers"],
            ),
            e.ERR_REMOTE_WORK_NOT_AUTHORIZED,
            403,
        )

        ben_session = validate_success(
            ladder.api.create_session(
                session_payload(
                    two_reviewer_matter["ben_id"],
                    matter_id,
                    workstation_class="REMOTE_VDI",
                ),
                two_reviewer_matter["ben_headers"],
            ),
            expected_status=201,
        )
        assert_status(ben_session, "SCHEDULED")
        assert ben_session["workstation_class"] == "REMOTE_VDI"

        ada_session = validate_success(
            ladder.api.create_session(
                session_payload(
                    two_reviewer_matter["ada_id"],
                    matter_id,
                    workstation_class="ONSITE_SECURE",
                ),
                two_reviewer_matter["ada_headers"],
            ),
            expected_status=201,
        )
        assert ada_session["workstation_class"] == "ONSITE_SECURE"

        sessions, _ = validate_paginated(
            ladder.api.list_sessions(STAFFING_COORDINATOR, matter_id=matter_id)
        )
        assert len(sessions) == 2
        assert sorted(row["workstation_class"] for row in sessions) == [
            "ONSITE_SECURE",
            "REMOTE_VDI",
        ]


class TestProgressAcceptsAnUnchangedCountAndRejectsADecrease:
    """Cumulative counters may stand still but never move backwards."""

    def test_an_unchanged_repost_is_a_no_op_while_a_decrease_and_an_overrun_are_refused(
        self, started_assignment
    ):
        """PRD §3.7: "All three counters are monotonic — none of them may ever decrease,
        though repeating an unchanged value is accepted — and `documents_coded` may
        never exceed the batch's `document_count`."

        Both a step down to ninety-nine and a step past the batch's four hundred are
        answered by the same counter rule, and neither is recorded.

        Design: Corner/validations/progress_accepts_an_unchanged_count_and_rejects_a_decrease
        """
        ladder = started_assignment["ladder"]
        assignment_id = started_assignment["assignment_id"]
        headers = started_assignment["ada_headers"]

        first = validate_success(
            ladder.api.record_progress(
                assignment_id, progress_payload(100, 120), headers
            )
        )
        assert first["documents_coded"] == 100
        assert first["minutes_logged"] == 120
        assert_pace_2dp(first["pace_dph"], 50.00)

        repeated = validate_success(
            ladder.api.record_progress(
                assignment_id, progress_payload(100, 120), headers
            )
        )
        assert repeated["documents_coded"] == 100
        assert repeated["minutes_logged"] == 120

        validate_error(
            ladder.api.record_progress(
                assignment_id, progress_payload(99, 130), headers
            ),
            e.ERR_DOCUMENT_COUNT_EXCEEDED,
            422,
        )
        validate_error(
            ladder.api.record_progress(
                assignment_id, progress_payload(401, 500), headers
            ),
            e.ERR_DOCUMENT_COUNT_EXCEEDED,
            422,
        )

        assignment = ladder.read_assignment(assignment_id)
        assert assignment["documents_coded"] == 100
        assert assignment["minutes_logged"] == 120
        assert_status(assignment, "IN_PROGRESS")
        assert_money(assignment["billable_amount_cents"], 0, "billable_amount_cents")
