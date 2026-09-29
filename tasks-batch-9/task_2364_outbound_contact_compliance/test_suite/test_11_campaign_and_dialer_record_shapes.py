"""Record shapes, derived counters and identity handling for campaigns, scrub
jobs, dialer profiles, agent scripts, calling-window policies, contact attempts
and complaints.

Every test builds its own preconditions through the documented endpoints,
because the database is empty when the test starts.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    DialerMode,
    DialerProfileStatus,
    ListType,
    PHONE_C2,
    REGULATORY_ABANDONMENT_CEILING_PCT,
    ScrubJobStatus,
    assert_created,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    make_dialer_operator_headers,
)

# The canonical working instant every recipe below drives the logical clock to,
# and the millisecond rendering the server is required to stamp rows with while
# the clock sits there.
_CLOCK_STAMP = "2026-08-03T00:00:00.000Z"
# 31 days after the instant above, the end of a completed scrub's validity.
_SCRUB_EXPIRY_STAMP = "2026-09-03T00:00:00.000Z"
# Just past the per-consumer cooldown, so a second attempt is permitted.
_AFTER_COOLDOWN_ISO = "2026-08-03T00:31:00Z"


class TestDialerProfileDraftShape:
    """Drafting a dialer profile."""

    def test_01_omitted_optional_pacing_fields_take_their_declared_defaults(
        self, clocked_world
    ):
        """A profile drafted with all four optional pacing fields omitted takes
        each declared default, opens in `DRAFT` with its approval stamps null,
        and needs no waiver because the defaulted ceiling equals the regulatory
        one.

        PRD 3.6: "Four optional fields carry defaults: `abandonment_limit_pct`,
        the operator-configured abandonment ceiling compared against the
        regulatory rate, which must lie between 0.01 and 100.00 inclusive at two
        decimal places and defaults to 3.00; `amd_enabled`, defaulting to false,
        which decides whether answering-machine detection runs at all;
        `amd_abandon_on_machine`, defaulting to false, recording whether a
        detected machine is dropped without an agent — this flag is kept for
        audit and never changes any rate; and `abandon_message_seconds`, the
        length in seconds of the recorded abandonment message played on
        abandoned calls, which must lie between 1 and 10 inclusive and defaults
        to 2."
        PRD 3.6: "A new profile is created with `status` `DRAFT`,
        `waiver_reference` and `locked_reason` and `approved_by_user_id` null,
        `max_lines_last_computed` equal to `agents_available`, and
        `requires_waiver` set to true exactly when `abandonment_limit_pct` is
        strictly greater than the regulatory ceiling of 3.00 percent and false
        otherwise."

        Design: Corner/entities/dialer_profile_defaults_applied_when_optional_inputs_omitted
        """
        profile = assert_created(
            clocked_world.api.create_dialer_profile(
                factories.dialer_profile_payload(
                    mode=DialerMode.POWER,
                    agents_available=4,
                    abandonment_limit_pct=None,
                    amd_enabled=None,
                    amd_abandon_on_machine=None,
                    abandon_message_seconds=None,
                ),
                clocked_world.operator,
            )
        )

        assert_decimal_equals(
            profile["abandonment_limit_pct"], REGULATORY_ABANDONMENT_CEILING_PCT
        )
        assert_fields_equal(
            profile,
            mode=DialerMode.POWER,
            agents_available=4,
            amd_enabled=False,
            amd_abandon_on_machine=False,
            abandon_message_seconds=2,
            status=DialerProfileStatus.DRAFT,
            requires_waiver=False,
            max_lines_last_computed=4,
        )
        assert_fields_null(
            profile, "waiver_reference", "locked_reason", "approved_by_user_id"
        )
        assert_version_is(profile, 1)
        assert_timestamp_equals(profile["created_at"], _CLOCK_STAMP)

    def test_02_a_mode_outside_the_declared_set_is_refused(self, clocked_world):
        """A profile whose `mode` is not one of the three declared pacing modes
        is refused as a malformed request.

        PRD 3.6: "Its `mode` is `PREVIEW`, `POWER` or `PREDICTIVE`, and
        `agents_available` — the staffed agent count that feeds the pacing
        calculation — must lie between 1 and 500 inclusive."
        PRD 2.8: "Request well-formedness on every endpoint — body parses, every
        required field present, every enum value a member of its declared set,
        every number inside its declared range, phone numbers in E.164 form,
        timestamps and dates parseable, `limit` within 1 to 100 —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/dialer_profile_unknown_mode_enum_rejected
        """
        response = clocked_world.api.create_dialer_profile(
            factories.dialer_profile_payload(mode="BLAST", agents_available=4),
            clocked_world.operator,
        )
        assert_error(response, ApiErrorId.INVALID_REQUEST)


class TestScrubJobDerivedCounters:
    """Executing a scrub resolves the target set."""

    def test_03_completed_scrub_counts_examined_suppressed_and_eligible_targets(
        self, world, draft_campaign
    ):
        """With two California contacts of which one carries an active national
        suppression, a completed scrub reports two examined, one suppressed and
        one eligible target, stamps its validity window, and promotes the drafted
        campaign.

        PRD 3.4: "`contacts_scrubbed_count` is the number of contacts whose
        `state_code` appears in the campaign's `target_state_codes`."
        PRD 3.4: "`eligible_target_count` is `contacts_scrubbed_count` less
        `contacts_suppressed_count`, and can never be negative because the
        suppressed contacts are a subset of the examined ones."
        PRD 3.4: "The job's `completed_at` is stamped at the current clock
        instant and `expires_at` is set to 31 days after `completed_at`."

        Design: Corner/entities/scrub_job_counter_fields_are_computed_from_the_target_set
        """
        campaign = draft_campaign["campaign"]

        # A second California consumer who is on the national do-not-call list.
        world.create_second_ca_contact()
        world.create_fresh_national_list(PHONE_C2)

        job = world.create_scrub_job(
            campaign["id"], list_types=[ListType.NATIONAL, ListType.INTERNAL]
        )
        completed = world.execute_scrub_job(job["id"])

        assert_status(completed, ScrubJobStatus.COMPLETED)
        assert_fields_equal(
            completed,
            contacts_scrubbed_count=2,
            contacts_suppressed_count=1,
            eligible_target_count=1,
        )
        assert (
            completed["eligible_target_count"]
            == completed["contacts_scrubbed_count"]
            - completed["contacts_suppressed_count"]
        ), "the eligible count must be the examined count less the suppressed count"
        assert_timestamp_equals(completed["completed_at"], _CLOCK_STAMP)
        assert_timestamp_equals(completed["expires_at"], _SCRUB_EXPIRY_STAMP)
        assert_fields_null(completed, "failure_reason", "invalidation_reason")

        promoted = world.read_campaign(campaign["id"])
        assert_status(promoted, CampaignStatus.PENDING_LAUNCH)
        assert_fields_equal(
            promoted,
            latest_scrub_status=ScrubJobStatus.COMPLETED,
            eligible_target_count=1,
        )


class TestContactAttemptListing:
    """Narrowing the attempt log."""

    def test_04_attempts_narrow_by_campaign_and_by_outcome(
        self, world, active_campaign
    ):
        """Two attempts to the same consumer with different outcomes are both
        returned when narrowing by campaign, and only the live answer is returned
        when the `outcome` filter is added.

        PRD 3.8: "Attempts may be listed and narrowed by `campaign_id`, by
        `contact_id`, by the `consent_record_id` relied on, by the
        `calling_window_policy_id` applied, and by `outcome`, with `limit` and
        `offset`."
        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` counts the rows matching the filters before pagination is
        applied and `has_more` says whether any matching row remains beyond the
        returned page."

        Design: Corner/entities/contact_attempt_listing_filters_by_campaign_and_outcome
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        answered = world.connected_attempt(campaign["id"], contact["id"])

        # Step past the per-consumer cooldown before dialling the same number.
        world.set_clock(_AFTER_COOLDOWN_ISO)
        second = world.create_attempt(campaign["id"], contact["id"])
        unanswered = world.record_outcome(
            second["id"], outcome=AttemptOutcome.NO_ANSWER
        )

        all_rows, all_meta = assert_page(
            world.api.list_contact_attempts(
                world.operator, {"campaign_id": campaign["id"]}
            )
        )
        assert_total_count(all_meta, 2)
        assert {row["id"] for row in all_rows} == {
            answered["id"],
            unanswered["id"],
        }, "both attempts of this campaign must be listed"

        answered_rows, answered_meta = assert_page(
            world.api.list_contact_attempts(
                world.operator,
                {
                    "campaign_id": campaign["id"],
                    "outcome": AttemptOutcome.CONNECTED_LIVE,
                },
            )
        )
        assert_total_count(answered_meta, 1)
        assert len(answered_rows) == 1, (
            "the outcome filter must drop the unanswered attempt, got %d rows"
            % len(answered_rows)
        )
        assert_fields_equal(
            answered_rows[0],
            id=answered["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
        )
        assert answered_meta["has_more"] is False, (
            "the single matching row fits on the page"
        )


class TestUnknownRowReferences:
    """Unknown identifiers are diagnosed per resource family."""

    def test_05_reading_an_unknown_campaign_is_not_found(self, clocked_world):
        """Reading a syntactically valid but unknown campaign identifier is
        refused as a missing campaign.

        PRD 2.8: "Then the `Campaign` named by a path identifier or a payload
        `campaign_id`, on `GET /compliance/campaigns/{id}`,
        `POST /compliance/campaigns/{id}/launch`,
        `POST /compliance/campaigns/{id}/suspend`,
        `POST /compliance/campaigns/{id}/resume`,
        `POST /compliance/campaigns/{id}/close`,
        `GET /compliance/campaigns/{id}/scrub-jobs`,
        `POST /compliance/scrub-jobs`, `POST /compliance/contact-attempts` and
        `POST /compliance/complaints` — `ERR_CAMPAIGN_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/campaign_get_unknown_id_not_found
        """
        response = clocked_world.api.get_campaign(
            NON_EXISTENT_UUID, clocked_world.manager
        )
        error = assert_error(response, ApiErrorId.CAMPAIGN_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_06_executing_an_unknown_scrub_job_is_not_found(self, clocked_world):
        """Executing a syntactically valid but unknown scrub-job identifier is
        refused as a missing scrub job.

        PRD 2.8: "Then the `ScrubJob` on
        `POST /compliance/scrub-jobs/{id}/execute` — `ERR_SCRUB_JOB_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/scrub_job_execute_unknown_id_not_found
        """
        response = clocked_world.api.execute_scrub_job(
            NON_EXISTENT_UUID, clocked_world.manager
        )
        error = assert_error(response, ApiErrorId.SCRUB_JOB_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_07_reading_an_unknown_dialer_profile_is_not_found(
        self, clocked_world
    ):
        """Reading a syntactically valid but unknown dialer-profile identifier is
        refused as a missing dialer profile.

        PRD 2.8: "Then the `DialerProfile` named by a path identifier or a
        payload `dialer_profile_id`, on `GET /compliance/dialer-profiles/{id}`,
        `POST /compliance/dialer-profiles/{id}/approve` and
        `POST /compliance/campaigns` — `ERR_DIALER_PROFILE_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/dialer_profile_get_unknown_id_not_found
        """
        response = clocked_world.api.get_dialer_profile(
            NON_EXISTENT_UUID, make_dialer_operator_headers()
        )
        error = assert_error(response, ApiErrorId.DIALER_PROFILE_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_08_reading_an_unknown_agent_script_is_not_found(self, clocked_world):
        """Reading a syntactically valid but unknown agent-script identifier is
        refused as a missing agent script.

        PRD 2.8: "Then the `AgentScript` named by a path identifier, by a payload
        `agent_script_id`, or by a payload `disclosure_script_id`, on
        `GET /compliance/agent-scripts/{id}`,
        `POST /compliance/agent-scripts/{id}/submit-review`,
        `POST /compliance/agent-scripts/{id}/approve`,
        `POST /compliance/agent-scripts/{id}/request-changes`,
        `POST /compliance/campaigns` and `POST /compliance/consent-records` —
        `ERR_AGENT_SCRIPT_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/agent_script_get_unknown_id_not_found
        """
        response = clocked_world.api.get_agent_script(
            NON_EXISTENT_UUID, clocked_world.officer
        )
        error = assert_error(response, ApiErrorId.AGENT_SCRIPT_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_09_reading_an_unknown_calling_window_policy_is_not_found(
        self, clocked_world
    ):
        """Reading a syntactically valid but unknown calling-window-policy
        identifier is refused as a missing policy.

        PRD 2.8: "Then the `CallingWindowPolicy` named by a path identifier or a
        payload `supersedes_policy_id`, on
        `GET /compliance/calling-window-policies/{id}`,
        `POST /compliance/calling-window-policies/{id}/declare-emergency` and
        `POST /compliance/calling-window-policies` —
        `ERR_CALLING_WINDOW_POLICY_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/calling_window_policy_get_unknown_id_not_found
        """
        response = clocked_world.api.get_calling_window_policy(
            NON_EXISTENT_UUID, clocked_world.officer
        )
        error = assert_error(response, ApiErrorId.CALLING_WINDOW_POLICY_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_10_reading_an_unknown_contact_attempt_is_not_found(
        self, clocked_world
    ):
        """Reading a syntactically valid but unknown contact-attempt identifier
        is refused as a missing contact attempt.

        PRD 2.8: "Then the `ContactAttempt` on
        `GET /compliance/contact-attempts/{id}`,
        `POST /compliance/contact-attempts/{id}/outcome` and
        `POST /compliance/contact-attempts/{id}/void` —
        `ERR_CONTACT_ATTEMPT_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/contact_attempt_get_unknown_id_not_found
        """
        response = clocked_world.api.get_contact_attempt(
            NON_EXISTENT_UUID, make_dialer_operator_headers()
        )
        error = assert_error(response, ApiErrorId.CONTACT_ATTEMPT_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_11_substantiating_an_unknown_complaint_is_not_found(
        self, clocked_world
    ):
        """Substantiating a syntactically valid but unknown complaint identifier
        is refused as a missing complaint.

        PRD 2.8: "Then the `Complaint` on `GET /compliance/complaints/{id}`,
        `POST /compliance/complaints/{id}/substantiate` and
        `POST /compliance/complaints/{id}/dismiss` — `ERR_COMPLAINT_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/complaint_substantiate_unknown_id_not_found
        """
        response = clocked_world.api.substantiate_complaint(
            NON_EXISTENT_UUID,
            factories.complaint_substantiate_payload(),
            clocked_world.officer,
        )
        error = assert_error(response, ApiErrorId.COMPLAINT_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_12_creating_a_campaign_on_an_unknown_script_is_not_found(
        self, clocked_world
    ):
        """A campaign naming a real dialer profile but an unknown
        `agent_script_id` is refused as a missing agent script, and no campaign
        row is written.

        PRD 2.8: "Then the `AgentScript` named by a path identifier, by a payload
        `agent_script_id`, or by a payload `disclosure_script_id`, on
        `GET /compliance/agent-scripts/{id}`,
        `POST /compliance/agent-scripts/{id}/submit-review`,
        `POST /compliance/agent-scripts/{id}/approve`,
        `POST /compliance/agent-scripts/{id}/request-changes`,
        `POST /compliance/campaigns` and `POST /compliance/consent-records` —
        `ERR_AGENT_SCRIPT_NOT_FOUND`."
        PRD 2.9: "Creating a campaign whose `dialer_profile_id` and
        `agent_script_id` are both unknown is reported as
        `ERR_DIALER_PROFILE_NOT_FOUND`; capturing a consent whose `contact_id`
        and `disclosure_script_id` are both unknown is reported as
        `ERR_CONTACT_NOT_FOUND`; logging a complaint whose `contact_id` and
        `campaign_id` are both unknown is reported as `ERR_CONTACT_NOT_FOUND`."

        Design: Corner/entities/campaign_create_with_unknown_agent_script_id_not_found
        """
        profile = clocked_world.approved_dialer_profile()

        response = clocked_world.api.create_campaign(
            factories.campaign_payload(
                dialer_profile_id=profile["id"],
                agent_script_id=NON_EXISTENT_UUID,
                name="Ghost Script Campaign",
            ),
            clocked_world.manager,
        )
        assert_error(response, ApiErrorId.AGENT_SCRIPT_NOT_FOUND)

        rows, meta = assert_page(
            clocked_world.api.list_campaigns(clocked_world.manager)
        )
        assert_total_count(meta, 0)
        assert rows == [], "the refused create must not have written a campaign"
