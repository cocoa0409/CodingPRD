"""Consent lifecycle: form version pinning, lazy expiry, the withdrawal
cascade, and the grant/revoke headcount invariant."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    enroll_participant,
    grant_consent,
    record_observation,
    set_clock,
    setup_active_cycle,
    setup_observation_world,
    setup_participant_with_consent,
    setup_program_with_approved_model,
    setup_published_instrument,
)
from test_helpers.test_users import DIRECTOR, PRIVACY


class TestStaleConsentForm:
    def test_stale_consent_form_rejected(self, api):
        """PRD section 3.5: "The presented `form_version` must equal the
        program's `current_consent_form_version` - consent captured on a
        stale form edition is rejected with `ERR_STALE_CONSENT_FORM`
        (HTTP 422)."

        Design: Corner/validations/stale_consent_form_rejected
        """
        program = create_active_program(name="Forms", code="FRM")
        cycle = create_cycle(program["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        participant = enroll_participant(cycle["id"])

        get_success_data(api.consent_form_bump(program["id"], PRIVACY))

        stale_resp = api.grant_consent(
            participant["id"],
            {"form_version": 1, "scope": "FULL",
             "expires_at": "2027-01-01T00:00:00Z"},
            PRIVACY,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_CONSENT_FORM)

        ok_resp = api.grant_consent(
            participant["id"],
            {"form_version": 2, "scope": "FULL",
             "expires_at": "2027-01-01T00:00:00Z"},
            PRIVACY,
        )
        consent = validate_success(ok_resp, expected_status=201)
        assert consent["status"] == "GRANTED"
        assert consent["form_version"] == 2


class TestConsentLazyExpiry:
    def test_consent_lazy_time_expiry(self, api):
        """PRD section 2.5: "A `ConsentRecord` in `GRANTED` status whose
        `expires_at` is on or before the current logical time is treated as
        `EXPIRED` the next time any consent check or read touches it: its
        status flips to `EXPIRED`, its `version` increments, and the owning
        participant's `consent_status` is recomputed."
        PRD section 3.6: "the participant must not be `WITHDRAWN` and their
        `consent_status` must be `CURRENT` - a granted consent whose
        `expires_at` has passed or whose `form_version` trails the program's
        current edition fails - else `ERR_CONSENT_NOT_CURRENT` (HTTP 422)."

        Design: Corner/validations/consent_lazy_time_expiry
        """
        world = setup_observation_world(program_name="Expiry", program_code="EXP")
        # Re-grant a short-lived consent so it can expire under the clock.
        short_consent = grant_consent(
            world["participant"]["id"],
            form_version=1,
            expires_at="2026-08-10T00:00:00Z",
        )
        assert short_consent["status"] == "GRANTED"

        set_clock("2026-08-11T00:00:00Z")

        obs_resp = api.record_observation(
            world["participant"]["id"],
            {"indicator_id": world["indicators"]["I1"]["id"],
             "instrument_id": world["instrument"]["id"],
             "value": 10,
             "collected_at": "2026-08-11T00:00:00Z"},
            # FieldCollector headers pinned to the certified collector.
            __import__("test_helpers").make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_CONSENT_NOT_CURRENT)

        consents_data = get_success_data(
            api.list_consents(world["participant"]["id"], PRIVACY))
        consents = consents_data if isinstance(consents_data, list) else consents_data.get("data", [])
        short = next(c for c in consents if c["id"] == short_consent["id"])
        assert short["status"] == "EXPIRED"

        participant_after = get_success_data(
            api.get_participant(world["participant"]["id"], PRIVACY))
        assert participant_after["consent_status"] == "EXPIRED"
        assert participant_after["status"] == "ACTIVE", (
            "time expiry does not withdraw the participant"
        )


class TestConsentRevokeCascade:
    def test_consent_revoke_cascades_to_participant_observations_and_cycle(self, api):
        """PRD section 3.5: "When the `PrivacyOfficer` revokes a `GRANTED`
        record (`GRANTED → REVOKED`, stamping `revoked_at`) and the
        participant holds no other `GRANTED` consent, the participant -
        whether `ENROLLED`, `ACTIVE`, or `EXITED` - is withdrawn: status
        `WITHDRAWN`, `consent_status` recomputed to `NONE`. The cascade
        continues into the data plane: every observation of that participant
        in `PENDING`, `VALIDATED`, or `FLAGGED` review status transitions to
        `EXCLUDED` with `exclusion_reason` set to `CONSENT_REVOKED`. And it
        finishes in the aggregates: the cycle's observation counters,
        `data_completeness_pct`, and `active_participant_count` are
        recomputed, and if an audit exists for the cycle its data-quality
        fields are recomputed as well."

        Design: Difficulty/transitive_cascade/consent_revoke_depth3
        """
        world = setup_observation_world(program_name="Legal Aid", program_code="LGL")
        ind = world["indicators"]["I1"]
        obs1 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=80)
        from test_helpers.fixtures import validate_observation
        validate_observation(obs1["id"])
        obs2 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=20, collected_at="2026-09-06T00:00:00Z")

        get_success_data(api.revoke_consent(world["consent"]["id"], PRIVACY))

        participant_after = get_success_data(
            api.get_participant(world["participant"]["id"], PRIVACY))
        assert participant_after["status"] == "WITHDRAWN"
        assert participant_after["consent_status"] == "NONE"

        obs1_after = get_success_data(
            api.get_observation(obs1["id"],
                                __import__("test_helpers").STEWARD))
        assert obs1_after["review_status"] == "EXCLUDED"
        assert obs1_after["exclusion_reason"] == "CONSENT_REVOKED"

        obs2_after = get_success_data(
            api.get_observation(obs2["id"],
                                __import__("test_helpers").STEWARD))
        assert obs2_after["review_status"] == "EXCLUDED"
        assert obs2_after["exclusion_reason"] == "CONSENT_REVOKED"

        cycle_after = get_success_data(
            api.get_cycle(world["cycle"]["id"],
                          __import__("test_helpers").STEWARD))
        assert cycle_after["total_observation_count"] == 0
        assert cycle_after["validated_observation_count"] == 0
        assert cycle_after["active_participant_count"] == 0
        assert cycle_after["data_completeness_pct"] is None

    def test_consent_revoke_marks_consent_record_revoked(self, api):
        """PRD section 3.5: "When the `PrivacyOfficer` revokes a `GRANTED`
        record (`GRANTED → REVOKED`, stamping `revoked_at`)".

        Design: Difficulty/transitive_cascade/consent_revoke_depth3
        """
        world = setup_observation_world(program_name="LegalAid2", program_code="LG2")
        revoked = get_success_data(
            api.revoke_consent(world["consent"]["id"], PRIVACY))
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_at"] is not None


class TestConsentGrantRevokeInvariant:
    def test_grant_revoke_restores_active_participant_count(self, api):
        """PRD section 3.5: "an `ENROLLED` participant whose new consent is
        current - its `form_version` matches the program's
        `current_consent_form_version` and its `expires_at` lies strictly in
        the future - transitions `ENROLLED → ACTIVE` automatically, and the
        cycle's `active_participant_count` is recomputed."
        PRD section 3.4: "`active_participant_count` is the number of
        participants currently `ACTIVE`, maintained on every participant
        transition."

        Design: Difficulty/compensating_invariant/consent_grant_revoke_headcount_invariant
        """
        base = setup_program_with_approved_model(program_name="Foodbank",
                                                 program_code="FDB")
        cycle = setup_active_cycle(base["program"])
        participant = enroll_participant(cycle["id"], external_ref="P-001")

        cycle0 = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle0["active_participant_count"] == 0, (
            "ENROLLED does not count toward active_participant_count"
        )

        consent = grant_consent(participant["id"])
        cycle1 = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle1["active_participant_count"] == 1, (
            "CURRENT consent drives ENROLLED -> ACTIVE and recomputes the count"
        )

        get_success_data(api.revoke_consent(consent["id"], PRIVACY))
        cycle2 = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle2["active_participant_count"] == 0, (
            "revoke compensates the headcount back to zero"
        )

        participant_after = get_success_data(
            api.get_participant(participant["id"], PRIVACY))
        assert participant_after["status"] == "WITHDRAWN"

    def test_second_grant_supersedes_first_and_keeps_headcount(self, api):
        """PRD section 3.5: "At most one record per participant may be
        `GRANTED` at a time: a new grant supersedes any prior `GRANTED`
        record for the same participant, flipping it to `SUPERSEDED` and
        recomputing the participant's `consent_status`."

        Design: Difficulty/compensating_invariant/consent_grant_revoke_headcount_invariant
        """
        base = setup_program_with_approved_model(program_name="Foodbank2",
                                                 program_code="FD2")
        cycle = setup_active_cycle(base["program"])
        participant = enroll_participant(cycle["id"], external_ref="P-001")

        first = grant_consent(participant["id"], expires_at="2027-06-01T00:00:00Z")
        cycle1 = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle1["active_participant_count"] == 1

        second = grant_consent(participant["id"], expires_at="2027-12-01T00:00:00Z")
        assert second["status"] == "GRANTED"

        consents_data = get_success_data(
            api.list_consents(participant["id"], PRIVACY))
        consents = consents_data if isinstance(consents_data, list) else consents_data.get("data", [])
        by_id = {c["id"]: c for c in consents}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "GRANTED"

        cycle2 = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle2["active_participant_count"] == 1, (
            "supersede + grant pair conserves the active headcount"
        )
