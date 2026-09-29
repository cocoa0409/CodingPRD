"""Consent, revocation, script, suppression, policy, attempt and complaint states.

Every precondition is built from scratch through the documented endpoints, since
each test runs against an empty database and a logical clock that starts at
`2026-08-01T00:00:00Z`.
"""

from test_helpers import (
    AgentScriptStatus,
    AllegedViolationType,
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    CaptureMethod,
    ComplaintSource,
    ComplaintStatus,
    ConsentStatus,
    DEFAULT_CLOCK,
    EmergencyStatus,
    IntakeStatus,
    InternalDncStatus,
    ListType,
    OFFICER_ADJUDICATOR_USER_ID,
    PHONE_C3,
    PolicyStatus,
    PropagationStatus,
    RejectionReason,
    RemovalReason,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    SuppressionStatus,
    SuspensionReason,
    VoidReason,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    find_by_id,
    make_compliance_officer_headers,
)


def _contact_with_active_voice_consent(world, clock=DEFAULT_CLOCK, **consent_overrides):
    """Publish the CA policy, import one contact and capture one VOICE consent."""
    world.set_clock(clock)
    policy = world.create_ca_policy()
    contact = world.create_ca_contact()
    script = world.approved_script()
    consent = world.create_consent(contact["id"], script["id"], **consent_overrides)
    return policy, contact, script, consent


class TestConsentRecordTransitions:
    """ACTIVE, SUSPENDED, REVOKED and SUPERSEDED consent records."""

    def test_01_suspending_a_suspended_consent_rejected(self, world):
        """A consent record already under audit cannot be suspended again.

        PRD §3.2: "Suspending anything that is not `ACTIVE` is refused with
        `ERR_CONSENT_STATE_INVALID`."

        Design: Corner/state_machines/consent_suspend_twice_returns_state_invalid
        """
        _policy, contact, _script, consent = _contact_with_active_voice_consent(world)

        suspended = world.suspend_consent(
            consent["id"], reason="Signature evidence under review"
        )
        assert_status(suspended, ConsentStatus.SUSPENDED)

        response = world.api.suspend_consent_record(
            consent["id"],
            factories.consent_suspend_payload(reason="Second audit pass"),
            world.officer,
        )
        assert_error(response, ApiErrorId.CONSENT_STATE_INVALID)

        unchanged = assert_ok(
            world.api.get_consent_record(consent["id"], world.officer)
        )
        assert_status(unchanged, ConsentStatus.SUSPENDED)
        assert_fields_equal(
            unchanged, suspended_reason="Signature evidence under review"
        )

        census = world.read_contact(contact["id"])
        assert_fields_equal(
            census,
            total_consent_count=1,
            active_consent_count=0,
            suspended_consent_count=1,
        )
        assert_consent_census_conserved(census)

    def test_02_newer_capture_supersedes_previous_same_channel_record(self, world):
        """A second VOICE capture pushes the earlier VOICE record to SUPERSEDED.

        PRD §3.2: "If the consumer already had an `ACTIVE` record for that same
        contact-and-channel pair, that older record moves `ACTIVE → SUPERSEDED` and the
        contact's `active_consent_count` and `superseded_consent_count` are recomputed."

        Design: Corner/state_machines/newer_consent_capture_supersedes_the_previous_same_channel_record
        """
        _policy, contact, script, first = _contact_with_active_voice_consent(world)
        assert_status(first, ConsentStatus.ACTIVE)

        second = world.create_consent(
            contact["id"],
            script["id"],
            capture_method=CaptureMethod.PAPER_FORM,
            signature_evidence="evidence-c1-paper",
        )
        assert_status(second, ConsentStatus.ACTIVE)
        assert_fields_equal(second, capture_method=CaptureMethod.PAPER_FORM)

        superseded = assert_ok(world.api.get_consent_record(first["id"], world.officer))
        assert_status(superseded, ConsentStatus.SUPERSEDED)

        census = world.read_contact(contact["id"])
        assert_fields_equal(
            census,
            total_consent_count=2,
            active_consent_count=1,
            superseded_consent_count=1,
            suspended_consent_count=0,
            revoked_consent_count=0,
        )
        assert_consent_census_conserved(census)


class TestRevocationRequestTransitions:
    """Intake and propagation move on separate triggers."""

    def test_03_validating_a_validated_revocation_rejected(self, world):
        """Intake leaves RECEIVED exactly once, so a second validation is refused.

        PRD §3.3: "Attempting to validate a row whose `intake_status` is not `RECEIVED`
        is refused with `ERR_REVOCATION_STATE_INVALID`."

        Design: Corner/state_machines/revocation_validate_twice_returns_state_invalid
        """
        _policy, contact, _script, _consent = _contact_with_active_voice_consent(world)

        revocation = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.WEB,
            method=RevocationMethod.WEB_PORTAL,
            scope=RevocationScope.ALL_CHANNELS,
        )
        validated = world.validate_revocation(revocation["id"])
        assert_status(validated, IntakeStatus.VALIDATED, field="intake_status")

        response = world.api.validate_revocation_request(
            revocation["id"],
            factories.revocation_validate_payload(validation_note="Verified again"),
            world.officer,
        )
        assert_error(response, ApiErrorId.REVOCATION_STATE_INVALID)

        unchanged = assert_ok(
            world.api.get_revocation_request(revocation["id"], world.officer)
        )
        assert_status(unchanged, IntakeStatus.VALIDATED, field="intake_status")
        assert_status(
            unchanged, PropagationStatus.IN_PROGRESS, field="propagation_status"
        )
        assert_fields_equal(unchanged, consent_records_revoked_count=1)

        census = world.read_contact(contact["id"])
        assert_fields_equal(
            census, revoked_consent_count=1, active_consent_count=0
        )
        assert_consent_census_conserved(census)

    def test_04_rejection_terminates_intake_without_revoking_consent(self, world):
        """A rejected intake stops dead and never touches the consent census.

        PRD §3.3: "The officer supplies a `rejection_reason` of `NOT_CONSUMER`,
        `UNVERIFIABLE_IDENTITY` or `DUPLICATE`; `intake_status` moves
        `RECEIVED → REJECTED`, the reason is stored, and `propagation_status` stays
        exactly where it was at `NOT_STARTED`, because the two dimensions move under
        different triggers and a rejected intake never propagates."
        PRD §3.3: "No consent record is touched, so the consent census is untouched as
        well."

        Design: Corner/state_machines/revocation_reject_terminates_intake_without_revoking_consent
        """
        _policy, contact, _script, consent = _contact_with_active_voice_consent(world)

        revocation = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.MAIL,
            method=RevocationMethod.POSTAL_MAIL,
            scope=RevocationScope.ALL_CHANNELS,
        )
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
        assert_fields_equal(
            rejected,
            rejection_reason=RejectionReason.UNVERIFIABLE_IDENTITY,
            consent_records_revoked_count=0,
        )
        assert_status(
            rejected, PropagationStatus.NOT_STARTED, field="propagation_status"
        )
        assert_fields_null(rejected, "propagated_at")

        untouched = assert_ok(
            world.api.get_consent_record(consent["id"], world.officer)
        )
        assert_status(untouched, ConsentStatus.ACTIVE)
        assert_fields_null(untouched, "revoked_at")

        census = world.read_contact(contact["id"])
        assert_fields_equal(
            census,
            active_consent_count=1,
            revoked_consent_count=0,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )
        assert_consent_census_conserved(census)

        _rows, meta = assert_page(
            world.api.list_suppression_entries(
                world.officer,
                params={
                    "list_type": ListType.INTERNAL,
                    "status": SuppressionStatus.ACTIVE,
                },
            )
        )
        assert_total_count(meta, 0)

    def test_05_propagation_before_deadline_reaches_propagated(self, world):
        """Propagating inside the ten-business-day window lands on PROPAGATED.

        PRD §3.3: "`propagation_deadline_at` is ten business days after `received_at`,
        counted as follows."
        PRD §3.3: "Which terminal state it lands in depends on one inclusive
        comparison: if the current clock instant is at or before
        `propagation_deadline_at`, the dimension moves `IN_PROGRESS → PROPAGATED` and
        nothing else changes; if the current clock instant is later than
        `propagation_deadline_at`, it moves `IN_PROGRESS → OVERDUE` and, in addition,
        the consumer's `overdue_propagation_count` increases by one and the contact's
        `version` increments."

        Design: Corner/state_machines/revocation_propagated_before_deadline_reaches_terminal_propagated
        """
        _policy, contact, _script, consent = _contact_with_active_voice_consent(
            world, clock="2026-08-03T14:00:00Z"
        )

        revocation = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.SMS,
            method=RevocationMethod.REPLY_STOP,
            scope=RevocationScope.SMS,
        )
        assert_timestamp_equals(
            revocation["propagation_deadline_at"], "2026-08-17T14:00:00.000Z"
        )

        world.validate_revocation(revocation["id"])

        world.set_clock("2026-08-04T09:00:00Z")
        propagated = world.propagate_revocation(
            revocation["id"], target_systems=["DIALER", "CRM"]
        )
        assert_status(propagated, PropagationStatus.PROPAGATED, field="propagation_status")
        assert_timestamp_equals(propagated["propagated_at"], "2026-08-04T09:00:00.000Z")
        assert_fields_equal(propagated, consent_records_revoked_count=0)

        untouched = assert_ok(
            world.api.get_consent_record(consent["id"], world.officer)
        )
        assert_status(untouched, ConsentStatus.ACTIVE)

        census = world.read_contact(contact["id"])
        assert_fields_equal(census, overdue_propagation_count=0)


class TestAgentScriptReviewLoop:
    """DRAFT, IN_REVIEW and the terminal APPROVED script state."""

    def test_06_approving_a_draft_script_rejected(self, world):
        """Approval is only reachable from IN_REVIEW, never straight from DRAFT.

        PRD §3.6: "Submitting a script that is not `DRAFT`, or approving or requesting
        changes on a script that is not `IN_REVIEW`, is refused with
        `ERR_SCRIPT_STATE_INVALID`."

        Design: Corner/state_machines/agent_script_approve_from_draft_returns_state_invalid
        """
        world.set_clock(DEFAULT_CLOCK)
        script = world.create_script()
        assert_status(script, AgentScriptStatus.DRAFT)

        response = world.api.approve_agent_script(
            script["id"],
            factories.agent_script_approve_payload(),
            world.script_approver,
        )
        assert_error(response, ApiErrorId.SCRIPT_STATE_INVALID)

        unchanged = assert_ok(world.api.get_agent_script(script["id"], world.manager))
        assert_status(unchanged, AgentScriptStatus.DRAFT)
        assert_fields_null(unchanged, "approved_by_user_id", "approved_at")
        assert_fields_equal(unchanged, review_cycle_count=0)

    def test_07_approved_script_rejects_submit_review(self, world):
        """APPROVED is terminal, so a resubmission for review is refused.

        PRD §3.6: "Alternatively the officer approves it with an `approval_note`, moving
        it `IN_REVIEW → APPROVED`, recording their own `X-User-ID` in
        `approved_by_user_id` and stamping `approved_at` with the current clock instant.
        `APPROVED` is terminal."
        PRD §3.6: "Submitting a script that is not `DRAFT`, or approving or requesting
        changes on a script that is not `IN_REVIEW`, is refused with
        `ERR_SCRIPT_STATE_INVALID`."

        Design: Corner/state_machines/agent_script_approved_is_terminal_and_rejects_submit_review
        """
        world.set_clock(DEFAULT_CLOCK)
        script = world.approved_script()
        assert_status(script, AgentScriptStatus.APPROVED)

        response = world.api.submit_agent_script_review(script["id"], world.manager)
        assert_error(response, ApiErrorId.SCRIPT_STATE_INVALID)

        unchanged = assert_ok(world.api.get_agent_script(script["id"], world.manager))
        assert_status(unchanged, AgentScriptStatus.APPROVED)
        assert_fields_equal(unchanged, review_cycle_count=0)
        assert_version_is(unchanged, 3)


class TestSuppressionEntryRemoval:
    """A suppression entry is withdrawn exactly once."""

    def test_08_removing_a_removed_entry_rejected(self, world):
        """A withdrawn suppression entry cannot be withdrawn a second time.

        PRD §3.4: "Removing an entry that is already `REMOVED` is refused with
        `ERR_SUPPRESSION_ENTRY_STATE_INVALID`."

        Design: Corner/state_machines/suppression_entry_remove_twice_returns_state_invalid
        """
        world.set_clock(DEFAULT_CLOCK)
        entry = world.create_suppression(PHONE_C3)
        assert_status(entry, SuppressionStatus.ACTIVE)

        removed = world.remove_suppression(
            entry["id"], removal_reason=RemovalReason.REGISTRY_DELISTING
        )
        assert_status(removed, SuppressionStatus.REMOVED)
        assert_fields_equal(
            removed, removal_reason=RemovalReason.REGISTRY_DELISTING
        )
        assert_timestamp_equals(removed["removed_at"], "2026-08-03T00:00:00.000Z")

        response = world.api.remove_suppression_entry(
            entry["id"],
            factories.suppression_remove_payload(
                removal_reason=RemovalReason.DATA_ERROR
            ),
            world.officer,
        )
        assert_error(response, ApiErrorId.SUPPRESSION_ENTRY_STATE_INVALID)

        rows, _meta = assert_page(
            world.api.list_suppression_entries(world.officer)
        )
        unchanged = find_by_id(rows, entry["id"])
        assert unchanged is not None, "the removed entry should still be listable"
        assert_status(unchanged, SuppressionStatus.REMOVED)
        assert_fields_equal(
            unchanged, removal_reason=RemovalReason.REGISTRY_DELISTING
        )
        assert_timestamp_equals(unchanged["removed_at"], "2026-08-03T00:00:00.000Z")


class TestCallingWindowPolicyEmergency:
    """The emergency dimension moves independently of the policy's own status."""

    def test_09_second_emergency_declaration_rejected(self, world):
        """A policy already under an emergency refuses a second declaration.

        PRD §3.5: "The policy must be `ACTIVE` and its `emergency_status` must
        currently be `NONE`; a superseded policy, or one already under an emergency,
        refuses the call with `ERR_POLICY_STATE_INVALID`."

        Design: Corner/state_machines/policy_declare_emergency_twice_returns_state_invalid
        """
        world.set_clock(DEFAULT_CLOCK)
        policy = world.create_ca_policy()

        declared = assert_ok(
            world.api.declare_policy_emergency(
                policy["id"],
                factories.declare_emergency_payload(
                    emergency_note="Wildfire evacuation order"
                ),
                world.admin,
            )
        )
        assert_status(declared, EmergencyStatus.ACTIVE, field="emergency_status")

        response = world.api.declare_policy_emergency(
            policy["id"],
            factories.declare_emergency_payload(emergency_note="Second wildfire order"),
            world.admin,
        )
        assert_error(response, ApiErrorId.POLICY_STATE_INVALID)

        unchanged = assert_ok(
            world.api.get_calling_window_policy(policy["id"], world.admin)
        )
        assert_status(unchanged, PolicyStatus.ACTIVE)
        assert_status(unchanged, EmergencyStatus.ACTIVE, field="emergency_status")
        assert_fields_equal(unchanged, emergency_note="Wildfire evacuation order")
        assert_timestamp_equals(
            unchanged["emergency_declared_at"], "2026-08-03T00:00:00.000Z"
        )

    def test_10_emergency_declaration_suspends_targeting_campaigns(
        self, world, active_campaign
    ):
        """Declaring an emergency reaches into every campaign targeting that state.

        PRD §3.5: "It then reaches straight into the campaign layer: every `ACTIVE`
        campaign whose `target_state_codes` contains this policy's `state_code` moves
        `ACTIVE → SUSPENDED` with `suspension_reason` set to `EMERGENCY_RESTRICTION`,
        voiding each of those campaigns' pending attempts with the budget credits of
        §3.8 and incrementing each campaign's `version`."

        Design: Corner/state_machines/emergency_declaration_suspends_every_campaign_targeting_that_state
        """
        policy = active_campaign["policy"]
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        assert_fields_equal(attempt, outcome=AttemptOutcome.PENDING)

        declared = assert_ok(
            world.api.declare_policy_emergency(
                policy["id"],
                factories.declare_emergency_payload(
                    emergency_note="Wildfire evacuation order"
                ),
                world.admin,
            )
        )
        assert_status(declared, PolicyStatus.ACTIVE)
        assert_status(declared, EmergencyStatus.ACTIVE, field="emergency_status")
        assert_timestamp_equals(
            declared["emergency_declared_at"], "2026-08-03T00:00:00.000Z"
        )

        suspended = world.read_campaign(campaign["id"])
        assert_status(suspended, CampaignStatus.SUSPENDED)
        assert_fields_equal(
            suspended,
            suspension_reason=SuspensionReason.EMERGENCY_RESTRICTION,
            voided_attempt_count=1,
            permitted_attempt_count=0,
        )

        voided = assert_ok(
            world.api.get_contact_attempt(attempt["id"], world.operator)
        )
        assert_fields_equal(
            voided,
            outcome=AttemptOutcome.VOIDED,
            void_reason=VoidReason.CAMPAIGN_SUSPENDED,
        )

        credited = world.read_contact(contact["id"])
        assert_fields_equal(credited, attempts_charged=0, attempt_budget_remaining=3)
        assert_attempt_budget_conserved(credited)


class TestContactAttemptDisposition:
    """An attempt carries exactly one disposition for its whole life."""

    def test_11_recording_a_second_disposition_rejected(self, world, active_campaign):
        """Once an outcome is recorded the attempt has left PENDING for good.

        PRD §3.8: "The attempt must still be `PENDING`, or the call is refused with
        `ERR_ATTEMPT_STATE_INVALID`."

        Design: Corner/state_machines/contact_attempt_outcome_recorded_twice_returns_state_invalid
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        world.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        response = world.api.record_attempt_outcome(
            attempt["id"],
            factories.attempt_outcome_payload(outcome=AttemptOutcome.NO_ANSWER),
            world.operator,
        )
        assert_error(response, ApiErrorId.ATTEMPT_STATE_INVALID)

        unchanged = assert_ok(
            world.api.get_contact_attempt(attempt["id"], world.operator)
        )
        assert_fields_equal(unchanged, outcome=AttemptOutcome.CONNECTED_LIVE)

        tallies = world.read_campaign(campaign["id"])
        assert_fields_equal(
            tallies,
            live_answer_count_today=1,
            abandoned_count_today=0,
            no_answer_count_today=0,
        )
        assert_decimal_equals(tallies["regulatory_abandonment_rate_pct"], 0.00)


class TestComplaintAdjudication:
    """Both adjudicated complaint states are terminal."""

    def test_12_dismissing_a_substantiated_complaint_rejected(
        self, world, active_campaign
    ):
        """A substantiated complaint can never be dismissed afterwards.

        PRD §3.9: "Substantiating or dismissing a complaint that is not `OPEN` is
        refused with `ERR_COMPLAINT_STATE_INVALID`; both `SUBSTANTIATED` and
        `DISMISSED` are terminal."

        Design: Corner/state_machines/complaint_dismiss_after_substantiate_returns_state_invalid
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        world.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        complaint = world.create_complaint(
            contact["id"],
            campaign["id"],
            source=ComplaintSource.DIRECT,
            alleged_violation_type=AllegedViolationType.TIME_WINDOW,
            narrative="Consumer says the call arrived outside the permitted window.",
            litigation_flag=False,
        )
        assert_status(complaint, ComplaintStatus.OPEN)

        substantiated = world.substantiate_complaint(
            complaint["id"], willful=False, finding_note="Window breach confirmed"
        )
        assert_status(substantiated, ComplaintStatus.SUBSTANTIATED)

        response = world.api.dismiss_complaint(
            complaint["id"],
            factories.complaint_dismiss_payload(dismissal_note="Reconsidered"),
            make_compliance_officer_headers(OFFICER_ADJUDICATOR_USER_ID),
        )
        assert_error(response, ApiErrorId.COMPLAINT_STATE_INVALID)

        unchanged = assert_ok(world.api.get_complaint(complaint["id"], world.officer))
        assert_status(unchanged, ComplaintStatus.SUBSTANTIATED)
        assert_fields_null(unchanged, "dismissal_note")
        assert_fields_equal(
            unchanged,
            willful=False,
            verified_attempt_count=1,
            exposure_cents=50000,
        )
        assert_decimal_equals(unchanged["adjudicated_risk_score"], 22.00)
