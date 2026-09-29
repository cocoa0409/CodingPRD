"""Pairs of failing conditions where only the higher-ranked one may be reported.

Each request below breaches two rules at once. The answer must name the rule
that sits higher in the shared precedence order, and the lower-ranked breach
must be provably reachable once the higher one is removed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_money, assert_status
from test_helpers.factories import assignment_payload, session_payload
from test_helpers.fixtures import REVIEWER_ADA, REVIEWER_BEN
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestProtocolGatePrecedesBudgetGate:
    """A superseded protocol is reported before an impossible commitment."""

    def _matter_awaiting_a_second_revision(self, tightly_capped_matter):
        ladder = tightly_capped_matter["ladder"]
        second = ladder.mint_protocol(
            issue_codes=[
                "RESPONSIVE",
                "NOT_RESPONSIVE",
                "PRIVILEGED",
                "HOT",
                "FOREIGN_LANGUAGE",
            ],
            privilege_criteria=["ATTORNEY_CLIENT", "WORK_PRODUCT", "COMMON_INTEREST"],
            second_level_required=True,
        )
        return second

    def test_an_unapproved_protocol_is_reported_even_though_the_cap_cannot_fit(
        self, tightly_capped_matter
    ):
        """PRD §2.5: "And the budget ceiling is the very last thing evaluated, so an
        assignment that would breach the cap still first has to pass every eligibility
        rule."

        A 400-document commitment of 85200 cannot fit a 50000 cap, but the missing
        approval is the higher-ranked breach.

        Design: Difficulty/priority_pair_validation_conflict/protocol_gate_precedes_budget_gate
        """
        ladder = tightly_capped_matter["ladder"]
        self._matter_awaiting_a_second_revision(tightly_capped_matter)

        response = ladder.api.create_assignment(
            tightly_capped_matter["batch_id"],
            assignment_payload(
                tightly_capped_matter["batch_version"],
                tightly_capped_matter["ada_id"],
                "FIRST_PASS",
            ),
            STAFFING_COORDINATOR,
        )
        body = validate_error(response, e.ERR_PROTOCOL_NOT_APPROVED, 409)
        assert body["error_id"] != e.ERR_BUDGET_WOULD_EXCEED

    def test_the_refusal_creates_no_assignment_and_moves_no_money(
        self, tightly_capped_matter
    ):
        """PRD §2.5: "The matter has exactly one review protocol whose `status` is
        `APPROVED` — otherwise `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409), on batch carving,
        named-reviewer assignment creation, auto-assignment, quality-control sample draw
        and batch release."

        The minting left revision one superseded and revision two in draft, and the
        refused assignment changed nothing at all.

        Design: Difficulty/priority_pair_validation_conflict/protocol_gate_precedes_budget_gate
        """
        ladder = tightly_capped_matter["ladder"]
        second = self._matter_awaiting_a_second_revision(tightly_capped_matter)

        ladder.api.create_assignment(
            tightly_capped_matter["batch_id"],
            assignment_payload(
                tightly_capped_matter["batch_version"],
                tightly_capped_matter["ada_id"],
                "FIRST_PASS",
            ),
            STAFFING_COORDINATOR,
        )

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(
                STAFFING_COORDINATOR, batch_id=tightly_capped_matter["batch_id"]
            )
        )
        assert assignments == []

        matter = validate_success(
            ladder.api.get_matter(
                tightly_capped_matter["matter_id"], ENGAGEMENT_MANAGER
            )
        )
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")
        assert_status(matter, "PROTOCOL_PENDING")

        first = validate_success(
            ladder.api.get_protocol(
                tightly_capped_matter["first_protocol_id"], ENGAGEMENT_MANAGER
            )
        )
        assert_status(first, "SUPERSEDED")
        assert_status(
            validate_success(
                ladder.api.get_protocol(second["id"], ENGAGEMENT_MANAGER)
            ),
            "DRAFT",
        )

        batch = ladder.read_batch(tightly_capped_matter["batch_id"])
        assert_status(batch, "CREATED")
        assert batch["version"] == tightly_capped_matter["batch_version"]


class TestRemoteAuthorizationPrecedesCoverageWindow:
    """An unauthorised remote seat is reported before a window outside coverage."""

    def _onboarded_without_a_session(self, matter_in_staffing):
        ladder = matter_in_staffing["ladder"]
        ada = ladder.onboard(REVIEWER_ADA)
        return ladder, ada

    def test_an_unauthorised_remote_window_is_refused_on_authorisation_not_coverage(
        self, matter_in_staffing
    ):
        """PRD §2.5: "A `REMOTE_VDI` session requires the matter's
        `remote_work_permitted` and the reviewer's `remote_work_authorized` both to be
        true — otherwise `ERR_REMOTE_WORK_NOT_AUTHORIZED` (HTTP 403), on session
        scheduling."

        The reviewer's own remote-work authorisation is false, and that is answered
        before the window is compared against her coverage.

        Design: Difficulty/priority_pair_validation_conflict/remote_authorization_gate_precedes_coverage_window_gate
        """
        ladder, ada = self._onboarded_without_a_session(matter_in_staffing)

        response = ladder.api.create_session(
            session_payload(
                ada["reviewer_id"],
                matter_in_staffing["matter_id"],
                workstation_class="REMOTE_VDI",
                starts_at_utc="2026-11-05T00:00:00Z",
                ends_at_utc="2026-11-06T00:00:00Z",
            ),
            ada["headers"],
        )
        body = validate_error(response, e.ERR_REMOTE_WORK_NOT_AUTHORIZED, 403)
        assert body["error_id"] != e.ERR_SESSION_OUTSIDE_COVERAGE

    def test_the_same_window_onsite_reaches_the_coverage_rule_and_creates_nothing(
        self, matter_in_staffing
    ):
        """PRD §2.5: "The requested session window lies entirely inside the reviewer's
        executed coverage interval for the matter, meaning `coverage_start_utc` is at or
        before `starts_at_utc` and `ends_at_utc` is at or before `coverage_end_utc` —
        otherwise `ERR_SESSION_OUTSIDE_COVERAGE` (HTTP 422), on session scheduling."

        Removing the remote element exposes the lower-ranked coverage breach, and
        neither attempt leaves a session behind.

        Design: Difficulty/priority_pair_validation_conflict/remote_authorization_gate_precedes_coverage_window_gate
        """
        ladder, ada = self._onboarded_without_a_session(matter_in_staffing)

        ladder.api.create_session(
            session_payload(
                ada["reviewer_id"],
                matter_in_staffing["matter_id"],
                workstation_class="REMOTE_VDI",
                starts_at_utc="2026-11-05T00:00:00Z",
                ends_at_utc="2026-11-06T00:00:00Z",
            ),
            ada["headers"],
        )
        onsite = ladder.api.create_session(
            session_payload(
                ada["reviewer_id"],
                matter_in_staffing["matter_id"],
                workstation_class="ONSITE_SECURE",
                starts_at_utc="2026-11-05T00:00:00Z",
                ends_at_utc="2026-11-06T00:00:00Z",
            ),
            ada["headers"],
        )
        validate_error(onsite, e.ERR_SESSION_OUTSIDE_COVERAGE, 422)

        sessions, _ = validate_paginated(
            ladder.api.list_sessions(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert sessions == []

        agreement = validate_success(
            ladder.api.get_agreement(ada["agreement_id"], STAFFING_COORDINATOR)
        )
        assert_status(agreement, "EXECUTED")


class TestCredentialGatePrecedesCapacityGate:
    """A lapsed credential is reported before a saturated capacity."""

    def _lapsed_but_saturated(self, matter_in_staffing):
        ladder = matter_in_staffing["ladder"]
        ada = ladder.onboard(REVIEWER_ADA, max_concurrent_batches=1)
        ladder.onboard(REVIEWER_BEN, remote_work_addendum=True)

        first_batch = ladder.carve_batch(400)
        first = ladder.assign(
            first_batch["id"], ada["reviewer_id"], "FIRST_PASS", first_batch["version"]
        )
        ladder.lapse_credential(ada["reviewer_id"])
        second_batch = ladder.carve_batch(200)
        return {
            "ladder": ladder,
            "ada_id": ada["reviewer_id"],
            "first_assignment_id": first["id"],
            "second_batch_id": second_batch["id"],
            "second_batch_version": second_batch["version"],
        }

    def test_a_lapsed_credential_is_reported_before_a_saturated_capacity(
        self, matter_in_staffing
    ):
        """PRD §2.5: "A reviewer who is both un-credentialed and over capacity surfaces
        as `ERR_CREDENTIAL_NOT_VERIFIED`, because rank 19 precedes rank 33."

        The reviewer already holds her one permitted live assignment, yet the credential
        breach outranks both capacity and minimum staffing.

        Design: Difficulty/priority_pair_validation_conflict/credential_gate_precedes_capacity_gate
        """
        state = self._lapsed_but_saturated(matter_in_staffing)
        ladder = state["ladder"]

        response = ladder.api.create_assignment(
            state["second_batch_id"],
            assignment_payload(
                state["second_batch_version"], state["ada_id"], "FIRST_PASS"
            ),
            STAFFING_COORDINATOR,
        )
        body = validate_error(response, e.ERR_CREDENTIAL_NOT_VERIFIED, 409)
        assert body["error_id"] != e.ERR_REVIEWER_CAPACITY_EXCEEDED
        assert body["error_id"] != e.ERR_MIN_STAFFING_UNMET

    def test_the_two_reviewer_status_axes_moved_independently_of_each_other(
        self, matter_in_staffing
    ):
        """PRD §3.3: "A reviewer can perfectly well be `CLEARED` on the engagement axis
        while still `UNVERIFIED` on the credential axis, and a credential lapse leaves
        engagement exactly where it was."

        The lapse blocked new work without touching engagement, the existing assignment
        or the second batch.

        Design: Difficulty/priority_pair_validation_conflict/credential_gate_precedes_capacity_gate
        """
        state = self._lapsed_but_saturated(matter_in_staffing)
        ladder = state["ladder"]

        ladder.api.create_assignment(
            state["second_batch_id"],
            assignment_payload(
                state["second_batch_version"], state["ada_id"], "FIRST_PASS"
            ),
            STAFFING_COORDINATOR,
        )

        reviewer = ladder.read_reviewer(state["ada_id"])
        assert_status(reviewer, "LAPSED", "credential_status")
        assert_status(reviewer, "ENGAGED", "engagement_status")

        assert_status(ladder.read_assignment(state["first_assignment_id"]), "ASSIGNED")

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 1
        assert_status(matter, "IN_REVIEW")

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(
                STAFFING_COORDINATOR, batch_id=state["second_batch_id"]
            )
        )
        assert assignments == []
        batch = ladder.read_batch(state["second_batch_id"])
        assert batch["version"] == state["second_batch_version"]
