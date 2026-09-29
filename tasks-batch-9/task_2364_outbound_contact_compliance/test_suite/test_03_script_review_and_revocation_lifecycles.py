"""Two lifecycles that are not straight lines: the script review loop and the two
state dimensions of a revocation request.

The script walks back and forth between drafting and review while a counter records how
many rounds it took; the revocation row advances an intake dimension and a propagation
dimension under different triggers, against a ten-business-day clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from test_helpers import (
    AgentScriptStatus,
    ApiErrorId,
    ComplianceWorld,
    ConsentStatus,
    ConsentType,
    IntakeStatus,
    OFFICER_SCRIPT_APPROVER_USER_ID,
    PropagationStatus,
    RejectionReason,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    STATE_NV,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_status,
    assert_version_is,
    factories,
)

SCRIPT_CLOCK = "2026-08-03T00:00:00Z"
SCRIPT_APPROVED_AT = "2026-08-03T00:00:00.000Z"

# A Monday, so the ten counted business days run into the following fortnight.
INTAKE_AT = "2026-08-03T14:00:00Z"
CA_HOLIDAY = "2026-08-07"
# Ten business days after intake, skipping both weekends and the Friday holiday.
DEADLINE_WITH_HOLIDAY = "2026-08-18T14:00:00.000Z"
ONE_SECOND_LATE = "2026-08-18T14:00:01Z"
# The same count with no governing policy: weekends skipped, no holidays honoured.
DEADLINE_WEEKENDS_ONLY = "2026-08-17T14:00:00.000Z"


def _instant(value: str) -> datetime:
    """Parse a UTC timestamp the server wrote into a comparable instant."""
    assert isinstance(value, str) and value, "expected a timestamp, got %r" % (value,)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant_equals(actual: str, expected: str) -> None:
    """A derived timestamp names exactly the expected instant."""
    assert _instant(actual) == _instant(expected), "expected %s, got %s" % (
        expected,
        actual,
    )


def _consumer_with_voice_consent(
    world: ComplianceWorld, state_code: str, holiday_dates: Any = None
) -> Dict[str, Any]:
    """One consumer holding a single active voice consent, under an optional policy."""
    world.set_clock(INTAKE_AT)
    policy = None
    if holiday_dates is not None:
        policy = world.create_ca_policy(holiday_dates=holiday_dates)
    contact = world.create_contact(state_code=state_code)
    script = world.create_script()
    consent = world.create_consent(
        contact["id"], script["id"], consent_type=ConsentType.EXPRESS_WRITTEN
    )
    return {"policy": policy, "contact": contact, "consent": consent}


def _received_revocation(world: ComplianceWorld, contact_id: str) -> Dict[str, Any]:
    """A verbal, all-channel withdrawal logged at the intake instant."""
    return world.create_revocation(
        contact_id,
        channel_received=RevocationChannelReceived.VOICE,
        method=RevocationMethod.VERBAL_REQUEST,
        scope=RevocationScope.ALL_CHANNELS,
        received_note="Consumer asked the agent to stop calling",
    )


class TestAgentScriptReviewLoop:
    """The DRAFT -> IN_REVIEW -> DRAFT cycle and the counter that records it."""

    def test_01_two_revision_rounds_are_counted_before_approval(self, world):
        """Twice sent back and thrice submitted, the script approves with the loop count at 2.

        PRD §3.6:
        "From `IN_REVIEW`, a `ComplianceOfficer` may send it back with a `change_note`,
        which moves it `IN_REVIEW → DRAFT`, stores the note and increments
        `review_cycle_count` by one — that counter is the record of how many revision rounds
        a script went through."
        PRD §3.6:
        "Alternatively the officer approves it with an `approval_note`, moving it
        `IN_REVIEW → APPROVED`, recording their own `X-User-ID` in `approved_by_user_id` and
        stamping `approved_at` with the current clock instant."

        Design: Difficulty/non_linear_state_machine/agent_script_revision_loop_counts_two_cycles
        """
        world.set_clock(SCRIPT_CLOCK)
        script = world.create_script()
        world.submit_script(script["id"])
        world.request_script_changes(
            script["id"], change_note="Add the opt-out sentence verbatim"
        )
        world.submit_script(script["id"])
        world.request_script_changes(
            script["id"], change_note="Name the seller in the identification block"
        )
        world.submit_script(script["id"])

        approved = world.approve_script(
            script["id"], approval_note="Third pass acceptable"
        )

        assert_status(approved, AgentScriptStatus.APPROVED)
        assert_fields_equal(
            approved,
            review_cycle_count=2,
            approved_by_user_id=OFFICER_SCRIPT_APPROVER_USER_ID,
        )
        assert_fields_null(approved, "change_note")
        _assert_instant_equals(approved["approved_at"], SCRIPT_APPROVED_AT)
        assert_version_is(approved, 7)

    def test_02_a_send_back_returns_the_script_to_draft_and_the_resubmit_clears_the_note(
        self, world
    ):
        """One round leaves the counter at 1, and re-submitting wipes the stored note.

        PRD §3.6:
        "Submitting a script for review moves it `DRAFT → IN_REVIEW` and clears any
        `change_note` back to null."

        Design: Difficulty/non_linear_state_machine/agent_script_revision_loop_counts_two_cycles
        """
        world.set_clock(SCRIPT_CLOCK)
        script = world.create_script()
        world.submit_script(script["id"])

        sent_back = world.request_script_changes(
            script["id"], change_note="Add the opt-out sentence verbatim"
        )

        assert_status(sent_back, AgentScriptStatus.DRAFT)
        assert_fields_equal(
            sent_back,
            review_cycle_count=1,
            change_note="Add the opt-out sentence verbatim",
        )
        assert_fields_null(sent_back, "approved_by_user_id", "approved_at")

        resubmitted = world.submit_script(script["id"])

        assert_status(resubmitted, AgentScriptStatus.IN_REVIEW)
        assert_fields_equal(resubmitted, review_cycle_count=1)
        assert_fields_null(resubmitted, "change_note")

    def test_03_a_script_approved_on_its_first_review_never_entered_the_loop(self, world):
        """Approving straight out of the first review leaves the revision counter at zero.

        PRD §3.6:
        "A new script is created with `status` `DRAFT` and `review_cycle_count` 0, with
        `change_note`, `approved_by_user_id` and `approved_at` null, and returns a 201."

        Design: Difficulty/non_linear_state_machine/agent_script_revision_loop_counts_two_cycles
        """
        world.set_clock(SCRIPT_CLOCK)
        script = world.create_script()
        assert_status(script, AgentScriptStatus.DRAFT)
        assert_fields_equal(script, review_cycle_count=0)
        assert_fields_null(script, "change_note", "approved_by_user_id", "approved_at")

        world.submit_script(script["id"])
        approved = world.approve_script(script["id"])

        assert_status(approved, AgentScriptStatus.APPROVED)
        assert_fields_equal(approved, review_cycle_count=0)
        assert_version_is(approved, 3)

    def test_04_the_loop_can_only_be_travelled_from_the_node_that_owns_the_edge(
        self, world
    ):
        """Neither branch of the review fork is reachable from DRAFT, and APPROVED is terminal.

        PRD §3.6:
        "Submitting a script that is not `DRAFT`, or approving or requesting changes on a
        script that is not `IN_REVIEW`, is refused with `ERR_SCRIPT_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/agent_script_revision_loop_counts_two_cycles
        """
        world.set_clock(SCRIPT_CLOCK)
        drafted = world.create_script()

        assert_error(
            world.api.request_agent_script_changes(
                drafted["id"],
                factories.agent_script_request_changes_payload(),
                world.script_approver,
            ),
            ApiErrorId.SCRIPT_STATE_INVALID,
        )
        assert_error(
            world.api.approve_agent_script(
                drafted["id"],
                factories.agent_script_approve_payload(),
                world.script_approver,
            ),
            ApiErrorId.SCRIPT_STATE_INVALID,
        )

        approved = world.approved_script(name="Second CA VOICE Script")
        assert_error(
            world.api.submit_agent_script_review(approved["id"], world.manager),
            ApiErrorId.SCRIPT_STATE_INVALID,
        )
        assert_error(
            world.api.request_agent_script_changes(
                approved["id"],
                factories.agent_script_request_changes_payload(),
                world.script_approver,
            ),
            ApiErrorId.SCRIPT_STATE_INVALID,
        )


class TestRevocationStateDimensions:
    """Intake and propagation advance separately on one withdrawal row."""

    def test_05_validation_advances_both_dimensions_in_one_request(self, world):
        """Validation lands intake on VALIDATED and propagation on IN_PROGRESS, and revokes the consent.

        PRD §3.3:
        "Validation is where the compliance machinery earns its keep. A `ComplianceOfficer`
        accepts the withdrawal as genuine, supplying a `validation_note`, and the request's
        `intake_status` moves `RECEIVED → VALIDATED` with `validated_at` stamped at the
        current clock instant, while the propagation dimension moves
        `NOT_STARTED → IN_PROGRESS` in the same request."
        PRD §3.3:
        "Attempting to validate a row whose `intake_status` is not `RECEIVED` is refused
        with `ERR_REVOCATION_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/revocation_intake_and_propagation_dimensions_advance_independently
        """
        setup = _consumer_with_voice_consent(world, "CA", holiday_dates=[CA_HOLIDAY])
        revocation = _received_revocation(world, setup["contact"]["id"])

        assert_status(revocation, IntakeStatus.RECEIVED, field="intake_status")
        assert_status(
            revocation, PropagationStatus.NOT_STARTED, field="propagation_status"
        )
        assert_fields_null(revocation, "validated_at", "propagated_at")

        validated = world.validate_revocation(
            revocation["id"], validation_note="Voice recording confirms the request"
        )

        assert_status(validated, IntakeStatus.VALIDATED, field="intake_status")
        assert_status(
            validated, PropagationStatus.IN_PROGRESS, field="propagation_status"
        )
        _assert_instant_equals(validated["validated_at"], INTAKE_AT)
        assert_fields_equal(validated, consent_records_revoked_count=1)
        assert_fields_null(validated, "propagated_at")

        consent = assert_ok(
            world.api.get_consent_record(setup["consent"]["id"], world.officer)
        )
        assert_status(consent, ConsentStatus.REVOKED)

        assert_error(
            world.api.validate_revocation_request(
                revocation["id"],
                factories.revocation_validate_payload(),
                world.officer,
            ),
            ApiErrorId.REVOCATION_STATE_INVALID,
        )

    def test_06_propagating_at_exactly_the_deadline_is_on_time(self, world):
        """The deadline lands on 2026-08-18T14:00:00Z and propagating on it is not overdue.

        PRD §3.3:
        "Ten days remain to be counted; the cursor advances by one whole day at a time, and
        each day the cursor lands on reduces the remaining count by one only if that day's
        UTC date falls Monday through Friday and is not listed in the governing policy's
        `holiday_dates`."
        PRD §3.3:
        "Propagating at exactly the deadline instant is on time; one second later is late."

        Design: Difficulty/non_linear_state_machine/revocation_intake_and_propagation_dimensions_advance_independently
        """
        setup = _consumer_with_voice_consent(world, "CA", holiday_dates=[CA_HOLIDAY])
        revocation = _received_revocation(world, setup["contact"]["id"])
        _assert_instant_equals(
            revocation["propagation_deadline_at"], DEADLINE_WITH_HOLIDAY
        )

        world.validate_revocation(revocation["id"])
        world.set_clock("2026-08-18T14:00:00Z")

        propagated = world.propagate_revocation(
            revocation["id"], target_systems=["DIALER", "CRM", "SMS_GATEWAY"]
        )

        assert_status(propagated, IntakeStatus.VALIDATED, field="intake_status")
        assert_status(
            propagated, PropagationStatus.PROPAGATED, field="propagation_status"
        )
        _assert_instant_equals(propagated["propagated_at"], DEADLINE_WITH_HOLIDAY)

        contact = world.read_contact(setup["contact"]["id"])
        assert_fields_equal(contact, overdue_propagation_count=0)

    def test_07_propagating_one_second_late_lands_overdue_and_charges_the_consumer(
        self, world
    ):
        """A second past the deadline the propagation dimension goes OVERDUE while intake stands still.

        PRD §3.3:
        "Which terminal state it lands in depends on one inclusive comparison: if the
        current clock instant is at or before `propagation_deadline_at`, the dimension moves
        `IN_PROGRESS → PROPAGATED` and nothing else changes; if the current clock instant is
        later than `propagation_deadline_at`, it moves `IN_PROGRESS → OVERDUE` and, in
        addition, the consumer's `overdue_propagation_count` increases by one and the
        contact's `version` increments."

        Design: Difficulty/non_linear_state_machine/revocation_intake_and_propagation_dimensions_advance_independently
        """
        setup = _consumer_with_voice_consent(world, "CA", holiday_dates=[CA_HOLIDAY])
        revocation = _received_revocation(world, setup["contact"]["id"])
        _assert_instant_equals(
            revocation["propagation_deadline_at"], DEADLINE_WITH_HOLIDAY
        )

        world.validate_revocation(revocation["id"])
        world.set_clock(ONE_SECOND_LATE)

        propagated = world.propagate_revocation(
            revocation["id"], target_systems=["DIALER", "CRM", "SMS_GATEWAY"]
        )

        assert_status(propagated, IntakeStatus.VALIDATED, field="intake_status")
        assert_status(propagated, PropagationStatus.OVERDUE, field="propagation_status")
        _assert_instant_equals(propagated["propagated_at"], ONE_SECOND_LATE)
        assert_fields_equal(propagated, consent_records_revoked_count=1)

        contact = world.read_contact(setup["contact"]["id"])
        assert_fields_equal(contact, overdue_propagation_count=1)

        consent = assert_ok(
            world.api.get_consent_record(setup["consent"]["id"], world.officer)
        )
        assert_status(consent, ConsentStatus.REVOKED)

    def test_08_a_rejected_intake_leaves_the_propagation_dimension_where_it_was(
        self, world
    ):
        """Rejection moves intake to REJECTED, holds propagation at NOT_STARTED and touches no consent.

        PRD §3.3:
        "`intake_status` moves `RECEIVED → REJECTED`, the reason is stored, and
        `propagation_status` stays exactly where it was at `NOT_STARTED`, because the two
        dimensions move under different triggers and a rejected intake never propagates."
        PRD §3.3:
        "The call requires `propagation_status` to be `IN_PROGRESS` and `intake_status` to
        be `VALIDATED`, and is otherwise refused with `ERR_REVOCATION_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/revocation_intake_and_propagation_dimensions_advance_independently
        """
        setup = _consumer_with_voice_consent(world, "CA", holiday_dates=[CA_HOLIDAY])
        revocation = _received_revocation(world, setup["contact"]["id"])

        rejected = assert_ok(
            world.api.reject_revocation_request(
                revocation["id"],
                factories.revocation_reject_payload(
                    RejectionReason.UNVERIFIABLE_IDENTITY
                ),
                world.officer,
            )
        )

        assert_status(rejected, IntakeStatus.REJECTED, field="intake_status")
        assert_status(
            rejected, PropagationStatus.NOT_STARTED, field="propagation_status"
        )
        assert_fields_equal(
            rejected,
            rejection_reason=RejectionReason.UNVERIFIABLE_IDENTITY,
            consent_records_revoked_count=0,
        )
        assert_fields_null(rejected, "validated_at", "propagated_at")

        consent = assert_ok(
            world.api.get_consent_record(setup["consent"]["id"], world.officer)
        )
        assert_status(consent, ConsentStatus.ACTIVE)

        assert_error(
            world.api.propagate_revocation_request(
                revocation["id"],
                factories.revocation_propagate_payload(),
                world.officer,
            ),
            ApiErrorId.REVOCATION_STATE_INVALID,
        )

    def test_09_with_no_governing_policy_the_deadline_skips_weekends_only(self, world):
        """Without a policy for the consumer's state the Friday holiday is not honoured.

        PRD §3.3:
        "The governing policy is the single active calling-window policy selected for the
        consumer's `state_code` at the moment of intake, using the selection rule of §3.5;
        when no policy covers that state, only Saturdays and Sundays are skipped and no
        holidays apply."

        Design: Difficulty/non_linear_state_machine/revocation_intake_and_propagation_dimensions_advance_independently
        """
        setup = _consumer_with_voice_consent(world, STATE_NV)
        revocation = _received_revocation(world, setup["contact"]["id"])

        assert_status(revocation, IntakeStatus.RECEIVED, field="intake_status")
        _assert_instant_equals(
            revocation["propagation_deadline_at"], DEADLINE_WEEKENDS_ONLY
        )
