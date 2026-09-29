"""Endpoint preconditions that are re-evaluated on every single call.

A live secure window is demanded per progress post, dissolution needs both a
status and a clean assignment history, and the screening junction checks both of
its ends before enforcing its own uniqueness.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_money, assert_pace_2dp, assert_status
from test_helpers.constants import BOGUS_UUID_3
from test_helpers.factories import (
    progress_payload,
    screening_payload,
    session_lifecycle_payload,
)
from test_helpers.fixtures import REVIEWER_ADA
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestProgressRequiresALiveSessionWindow:
    """Closing the window mid-assignment stops the coding, not the assignment."""

    def test_a_fresh_active_session_restores_the_same_assignment(
        self, started_assignment
    ):
        """PRD §3.7: "Progress additionally requires live confidentiality coverage and,
        separately, that the reviewer hold a secure-environment session on this matter
        in `ACTIVE` whose half-open window contains the logical clock; without one the
        call is refused with `ERR_NO_ACTIVE_SESSION`."

        The refusal records nothing and does not push the assignment back to assigned,
        and the closed window neither overlaps nor holds a seat.

        Design: Corner/endpoints/progress_requires_a_live_session_window
        """
        ladder = started_assignment["ladder"]
        assignment_id = started_assignment["assignment_id"]
        ada_id = started_assignment["ada_id"]
        headers = started_assignment["ada_headers"]
        first_session_id = started_assignment["ada_session_id"]

        validate_success(
            ladder.api.set_session_lifecycle(
                first_session_id, session_lifecycle_payload("CLOSED"), headers
            )
        )

        validate_error(
            ladder.api.record_progress(
                assignment_id, progress_payload(200, 210), headers
            ),
            e.ERR_NO_ACTIVE_SESSION,
            409,
        )
        assert ladder.read_assignment(assignment_id)["documents_coded"] == 0

        second_session = ladder.schedule_session(
            ada_id, started_assignment["matter_id"]
        )
        ladder.activate_session(second_session["id"], ada_id)

        recorded = validate_success(
            ladder.api.record_progress(
                assignment_id, progress_payload(200, 210), headers
            )
        )
        assert recorded["documents_coded"] == 200
        assert recorded["minutes_logged"] == 210
        assert_pace_2dp(recorded["pace_dph"], 57.14)

        assert_status(ladder.read_assignment(assignment_id), "IN_PROGRESS")
        assert_status(
            validate_success(
                ladder.api.get_session(first_session_id, STAFFING_COORDINATOR)
            ),
            "CLOSED",
        )
        assert_status(
            validate_success(
                ladder.api.get_session(second_session["id"], STAFFING_COORDINATOR)
            ),
            "ACTIVE",
        )


class TestDissolveAllowedOnlyWhileCreatedAndUnassigned:
    """An assigned batch cannot be dissolved; its untouched sibling can."""

    def test_the_untouched_sibling_returns_its_documents_and_moves_no_money(
        self, assigned_batch
    ):
        """PRD §3.6: "An `EngagementManager` dissolves a batch only while it is
        `CREATED` and only while it carries no assignment row whose status is anything
        other than `VOIDED`; a batch that fails either condition answers
        `ERR_BATCH_NOT_DISSOLVABLE`."

        Dissolving a batch that never carried an assignment returns its documents to the
        unbatched pool without touching the committed spend.

        Design: Corner/endpoints/dissolve_allowed_only_while_created_and_unassigned
        """
        ladder = assigned_batch["ladder"]
        second = ladder.carve_batch(150)

        validate_error(
            ladder.api.dissolve_batch(assigned_batch["batch_id"], ENGAGEMENT_MANAGER),
            e.ERR_BATCH_NOT_DISSOLVABLE,
            409,
        )
        assert_status(ladder.read_batch(assigned_batch["batch_id"]), "ASSIGNED")

        dissolved = validate_success(
            ladder.api.dissolve_batch(second["id"], ENGAGEMENT_MANAGER)
        )
        assert_status(dissolved, "DISSOLVED")

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["unbatched_document_count"] == 200
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(STAFFING_COORDINATOR, batch_id=second["id"])
        )
        assert assignments == []


class TestScreeningLinkNeedsBothPartiesAndStaysSingleton:
    """Both ends must resolve, and then only one open link may exist."""

    def test_an_unknown_reviewer_is_refused_and_the_pair_is_linked_only_once(
        self, matter_in_intake
    ):
        """PRD §3.4: "Opening a screening is refused while the matter is `SUSPENDED`,
        refused when the reviewer is already `REMOVED`, and refused with
        `ERR_SCREENING_ALREADY_OPEN` when that reviewer-and-matter pair already has a
        screening in `PENDING`, `WAIVER_REQUIRED` or `CLEARED` — those three are the
        non-terminal statuses, so a pair whose only prior screening is `BLOCKED` may be
        screened afresh."

        The second request for the same pair is refused because the first link is still
        open, so the stored declaration is the one first supplied.

        Design: Corner/endpoints/screening_link_needs_both_parties_and_stays_singleton
        """
        ladder = matter_in_intake["ladder"]
        matter_id = matter_in_intake["matter_id"]
        ada = ladder.source_reviewer(REVIEWER_ADA)

        validate_error(
            ladder.api.create_screening(
                screening_payload(BOGUS_UUID_3, matter_id, declared_adverse_parties=[]),
                STAFFING_COORDINATOR,
            ),
            e.ERR_REVIEWER_NOT_FOUND,
            404,
        )

        screening = validate_success(
            ladder.api.create_screening(
                screening_payload(ada["id"], matter_id, declared_adverse_parties=[]),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_status(screening, "PENDING")
        assert screening["reviewer_id"] == ada["id"]
        assert screening["matter_id"] == matter_id

        validate_error(
            ladder.api.create_screening(
                screening_payload(
                    ada["id"],
                    matter_id,
                    declared_adverse_parties=["Calder Holdings LLC"],
                ),
                STAFFING_COORDINATOR,
            ),
            e.ERR_SCREENING_ALREADY_OPEN,
            409,
        )

        screenings, _ = validate_paginated(
            ladder.api.list_screenings(STAFFING_COORDINATOR, reviewer_id=ada["id"])
        )
        assert len(screenings) == 1
        assert screenings[0]["declared_adverse_parties"] == []
