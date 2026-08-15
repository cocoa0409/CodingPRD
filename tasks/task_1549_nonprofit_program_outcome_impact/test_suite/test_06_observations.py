"""Observation recording: the ordered domain checks, segregation of duties,
the flag/validate branch, and immediate visibility."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_data_steward_headers,
    make_field_collector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_certification,
    create_cycle,
    create_indicator,
    create_instrument,
    create_logic_model,
    enroll_participant,
    grant_consent,
    publish_instrument,
    record_observation,
    set_clock,
    setup_active_cycle,
    setup_observation_world,
    setup_participant_with_consent,
    setup_program_with_approved_model,
    validate_observation,
)
from test_helpers.test_users import DIRECTOR, LEAD, PRIVACY, STEWARD


class TestObservationRecordingGuards:
    def test_observation_requires_cycle_active(self, api):
        """PRD section 3.6: "First, the owning cycle must be `ACTIVE` -
        observations are child mutations permitted only during live collection
        - else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/observation_requires_cycle_active
        """
        base = setup_program_with_approved_model(program_name="Tutoring",
                                                 program_code="TUT")
        cycle = create_cycle(base["program"]["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        participant = enroll_participant(cycle["id"])
        grant_consent(participant["id"])
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")

        obs_resp = api.record_observation(
            participant["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 42, "collected_at": "2026-08-10T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_INVALID_STATE)

        cycle_after = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_after["pinned_logic_model_id"] is None, (
            "cycle was never activated, so no logic model is pinned"
        )

    def test_observation_recording_blocked_on_enrolling_cycle(self, api):
        """PRD section 3.6: "First, the owning cycle must be `ACTIVE` -
        observations are child mutations permitted only during live collection
        - else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/observation_requires_cycle_active
        """
        base = setup_program_with_approved_model(program_name="Tutoring2",
                                                 program_code="TU2")
        cycle = create_cycle(base["program"]["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        participant = enroll_participant(cycle["id"])
        grant_consent(participant["id"])
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")

        obs_resp = api.record_observation(
            participant["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 42, "collected_at": "2026-08-10T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_INVALID_STATE)


class TestObservationPriorityPairs:
    def test_state_beats_consent_on_closed_cycle(self, api):
        """PRD section 3.6: "the domain checks fire **in exactly this order**,
        each failure masking all later ones. First, the owning cycle must be
        `ACTIVE` - observations are child mutations permitted only during live
        collection - else `ERR_INVALID_STATE` (HTTP 409). Second, consent: the
        participant must not be `WITHDRAWN` and their `consent_status` must be
        `CURRENT` - a granted consent whose `expires_at` has passed or whose
        `form_version` trails the program's current edition fails - else
        `ERR_CONSENT_NOT_CURRENT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_closed_cycle_observation
        """
        world = setup_observation_world(program_name="Reentry", program_code="RNT")
        # Withdraw the participant, then close data so the cycle is not ACTIVE.
        get_success_data(api.revoke_consent(world["consent"]["id"], PRIVACY))
        get_success_data(api.close_data(world["cycle"]["id"], DIRECTOR))

        obs_resp = api.record_observation(
            world["participant"]["id"],
            {"indicator_id": world["indicators"]["I1"]["id"],
             "instrument_id": world["instrument"]["id"],
             "value": 42, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        error_data = validate_error(obs_resp, ApiErrorId.ERR_INVALID_STATE)
        assert error_data["error_id"] == "ERR_INVALID_STATE"
        assert error_data["error_id"] != "ERR_CONSENT_NOT_CURRENT", (
            "state check (priority first) masks the consent check"
        )

    def test_consent_beats_certification_when_both_fail(self, api):
        """PRD section 3.6: "the domain checks fire **in exactly this order**,
        each failure masking all later ones. ... Second, consent: the
        participant must not be `WITHDRAWN` and their `consent_status` must be
        `CURRENT` ... else `ERR_CONSENT_NOT_CURRENT` (HTTP 422). ... Fifth, a
        `TrainingCertification` must exist pairing the acting collector's
        `X-User-ID` (as `staff_user_id`) with the instrument, else
        `ERR_CERTIFICATION_MISSING` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_expired_consent_no_cert
        """
        base = setup_program_with_approved_model(program_name="Recovery",
                                                 program_code="RCV")
        cycle = setup_active_cycle(base["program"])
        participant = enroll_participant(cycle["id"])
        grant_consent(participant["id"], form_version=1)
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        # NOTE: deliberately no certification for collector-1.

        # Bump consent form -> prior GRANTED consent becomes SUPERSEDED,
        # participant's consent_status becomes EXPIRED.
        get_success_data(api.consent_form_bump(base["program"]["id"], PRIVACY))

        participant_after = get_success_data(
            api.get_participant(participant["id"], PRIVACY))
        assert participant_after["consent_status"] == "EXPIRED"

        obs_resp = api.record_observation(
            participant["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 42, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        error_data = validate_error(obs_resp, ApiErrorId.ERR_CONSENT_NOT_CURRENT)
        assert error_data["error_id"] == "ERR_CONSENT_NOT_CURRENT"
        assert error_data["error_id"] != "ERR_CERTIFICATION_MISSING", (
            "consent check (earlier) masks the certification check"
        )


class TestObservationPriorityPairsIsolated:
    def test_closed_cycle_blocks_even_when_consent_current(self, api):
        """PRD section 3.6: "the domain checks fire **in exactly this order**,
        each failure masking all later ones. First, the owning cycle must be
        `ACTIVE` - observations are child mutations permitted only during live
        collection - else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_closed_cycle_observation
        """
        # Consent fully CURRENT here -- only the state check can fire.
        world = setup_observation_world(program_name="Reentry2", program_code="RN2")
        get_success_data(api.close_data(world["cycle"]["id"], DIRECTOR))

        obs_resp = api.record_observation(
            world["participant"]["id"],
            {"indicator_id": world["indicators"]["I1"]["id"],
             "instrument_id": world["instrument"]["id"],
             "value": 42, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_INVALID_STATE)

    def test_expired_consent_blocks_when_otherwise_valid(self, api):
        """PRD section 3.6: "Second, consent: the participant must not be
        `WITHDRAWN` and their `consent_status` must be `CURRENT` - a granted
        consent whose `expires_at` has passed or whose `form_version` trails
        the program's current edition fails - else `ERR_CONSENT_NOT_CURRENT`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_expired_consent_no_cert
        """
        # Certification exists and is valid here -- only the consent check
        # can fire. This isolates the consent branch.
        base = setup_program_with_approved_model(program_name="Recovery2",
                                                 program_code="RC2")
        cycle = setup_active_cycle(base["program"])
        participant = enroll_participant(cycle["id"])
        grant_consent(participant["id"], form_version=1)
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")

        get_success_data(api.consent_form_bump(base["program"]["id"], PRIVACY))

        obs_resp = api.record_observation(
            participant["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 42, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_CONSENT_NOT_CURRENT)


class TestObservationBusinessChecks:
    def test_observation_requires_published_instrument(self, api):
        """PRD section 3.6: "Third, the instrument must be `PUBLISHED`, else
        `ERR_INSTRUMENT_NOT_PUBLISHED` (HTTP 422)."

        Design: Corner/validations/observation_requires_published_instrument
        """
        base = setup_program_with_approved_model(program_name="DraftInstr",
                                                 program_code="DFI")
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        draft_instr = create_instrument(base["program"]["id"],
                                        code="DRAFT-I", title="Unpublished")

        obs_resp = api.record_observation(
            pc["participant"]["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": draft_instr["id"],
             "value": 10, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_INSTRUMENT_NOT_PUBLISHED)

    def test_indicator_outside_pinned_model_rejected(self, api):
        """PRD section 3.6: "Fourth, the indicator must be `ACTIVE` and
        belong to the cycle's pinned logic model, else
        `ERR_INDICATOR_NOT_IN_MODEL` (HTTP 422)."
        PRD section 3.4: "Both pins are immutable thereafter, so a later
        logic-model approval or consent-form change cannot retroactively
        redefine what an in-flight cycle was measuring".

        Design: Corner/validations/indicator_outside_pinned_model_rejected
        """
        base = setup_program_with_approved_model(program_name="Pinned",
                                                 program_code="PIN")
        cycle = setup_active_cycle(base["program"])
        m1_id = base["model"]["id"]

        # Approve a replacement model M2; cycle pin must stay on M1.
        m2 = create_logic_model(base["program"]["id"], title="M2")
        ind_b = create_indicator(m2["id"], code="B")
        get_success_data(api.submit_logic_model(m2["id"], LEAD))
        program_now = get_success_data(
            api.get_program(base["program"]["id"], DIRECTOR))
        get_success_data(api.approve_logic_model(
            m2["id"], {"expected_program_version": program_now["version"]}, LEAD))

        pc = setup_participant_with_consent(cycle["id"])
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1")

        obs_resp = api.record_observation(
            pc["participant"]["id"],
            {"indicator_id": ind_b["id"],
             "instrument_id": instr["id"],
             "value": 10, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_INDICATOR_NOT_IN_MODEL)

        cycle_after = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_after["pinned_logic_model_id"] == m1_id, (
            "the cycle keeps its originally pinned logic model"
        )

    def test_uncertified_collector_rejected(self, api):
        """PRD section 3.6: "Fifth, a `TrainingCertification` must exist
        pairing the acting collector's `X-User-ID` (as `staff_user_id`) with
        the instrument, else `ERR_CERTIFICATION_MISSING` (HTTP 422)."

        Design: Corner/validations/uncertified_collector_rejected
        """
        base = setup_program_with_approved_model(program_name="NoCert",
                                                 program_code="NCT")
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        # No certification row for collector-1.

        obs_resp = api.record_observation(
            pc["participant"]["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 10, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(obs_resp, ApiErrorId.ERR_CERTIFICATION_MISSING)

    def test_certification_expiry_boundary(self, api):
        """PRD section 3.6: "Seventh and last, the certification must be in
        `CERTIFIED` status with `expires_at` strictly in the future - a
        suspended, expired, or past-due certification fails - else
        `ERR_CERTIFICATION_EXPIRED` (HTTP 422)."

        Design: Corner/validations/certification_expiry_boundary
        """
        base = setup_program_with_approved_model(program_name="CertExp",
                                                 program_code="CXP")
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        instr = create_instrument(base["program"]["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        create_certification(instr["id"], staff_user_id="collector-1",
                             expires_at="2026-09-01T00:00:00Z")

        set_clock("2026-08-31T23:59:59Z")
        ok_resp = api.record_observation(
            pc["participant"]["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 10, "collected_at": "2026-08-31T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_success(ok_resp, expected_status=201)

        set_clock("2026-09-01T00:00:00Z")
        expired_resp = api.record_observation(
            pc["participant"]["id"],
            {"indicator_id": base["indicators"]["I1"]["id"],
             "instrument_id": instr["id"],
             "value": 11, "collected_at": "2026-09-01T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(expired_resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED)

    def test_observation_on_nonexistent_participant_returns_not_found(self, api):
        """PRD section 2.10: "The server resolves each identifier in order and
        responds with `ERR_NOT_FOUND` (HTTP 404) for the *first* identifier
        that does not resolve to an existing resource, without consulting
        later identifiers."

        Design: Corner/validations/observation_on_nonexistent_participant_returns_not_found
        """
        resp = api.record_observation(
            "11111111-2222-3333-4444-555555555555",
            {"indicator_id": "11111111-2222-3333-4444-555555555556",
             "instrument_id": "11111111-2222-3333-4444-555555555557",
             "value": 1, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestObservationReview:
    def test_observation_flag_then_validate_branch(self, api):
        """PRD section 3.6: "Validation moves an observation from `PENDING`
        or `FLAGGED` to `VALIDATED`".
        PRD section 3.6: "Flagging moves `PENDING → FLAGGED` and records the
        steward's `reason`; a flagged observation remains inside every
        denominator, so cycle counters and completeness are deliberately
        unchanged by a flag."
        PRD section 3.6: "Each validation recomputes the cycle's
        `validated_observation_count` and `total_observation_count`, refreshes
        `data_completeness_pct`".

        Design: Corner/state_machines/observation_flag_then_validate_branch
        """
        world = setup_observation_world(program_name="Branch", program_code="BRN")
        obs = record_observation(
            world["participant"]["id"], world["indicators"]["I1"]["id"],
            world["instrument"]["id"], value=55)

        flagged = get_success_data(api.flag_observation(
            obs["id"], {"reason": "value looks off"},
            make_data_steward_headers("steward-1")))
        assert flagged["review_status"] == "FLAGGED"

        validated = get_success_data(api.validate_observation(
            obs["id"], make_data_steward_headers("steward-1")))
        assert validated["review_status"] == "VALIDATED"

        cycle_after = get_success_data(api.get_cycle(world["cycle"]["id"], STEWARD))
        assert cycle_after["validated_observation_count"] == 1

    def test_segregation_validate_own_observation_rejected(self, api):
        """PRD section 2.9: "a `DataSteward` cannot validate an observation
        whose `collected_by_id` equals their own `X-User-ID`".
        PRD section 3.6: "when the steward's `X-User-ID` equals the
        observation's `collected_by_id`, the request is rejected with
        `ERR_SEGREGATION_OF_DUTY` (HTTP 422)."

        Design: Corner/validations/segregation_validate_own_observation_rejected
        """
        world = setup_observation_world(program_name="SoD", program_code="SOD",
                                        collector_user="user-shared")
        obs = record_observation(
            world["participant"]["id"], world["indicators"]["I1"]["id"],
            world["instrument"]["id"], value=10, collector_user="user-shared")

        self_resp = api.validate_observation(
            obs["id"], make_data_steward_headers("user-shared"))
        validate_error(self_resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

        other = get_success_data(api.validate_observation(
            obs["id"], make_data_steward_headers("steward-other")))
        assert other["review_status"] == "VALIDATED"


class TestObservationVisibility:
    def test_immediate_visibility_after_mutation(self, api):
        """PRD section 3.6: "At record time the server pins
        `instrument_version` to the instrument's current version, stamps
        `recorded_at` from the logical clock, captures `collected_by_id` as
        the acting collector's `X-User-ID` (the segregation-of-duties anchor
        used later), and computes `is_late`: true exactly when `recorded_at`
        falls after the owning cycle's `cycle_end`. The observation starts in
        `PENDING` review status, and its creation recomputes the cycle's
        `total_observation_count` and `data_completeness_pct`."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        world = setup_observation_world(program_name="Immediate", program_code="IMM")
        obs = record_observation(
            world["participant"]["id"], world["indicators"]["I1"]["id"],
            world["instrument"]["id"], value=10)
        assert obs["instrument_version"] == 1
        assert obs["collected_by_id"] == "collector-1"
        assert obs["review_status"] == "PENDING"
        assert obs["is_late"] is False

        cycle_after = get_success_data(
            api.get_cycle(world["cycle"]["id"], STEWARD))
        assert cycle_after["total_observation_count"] == 1, (
            "the create response is followed by immediate visibility on the cycle"
        )


class TestObservationListing:
    def test_observations_list_filter_by_review_status(self, api):
        """PRD section 3.6: "Observations are listable per cycle and per
        participant (each with a `review_status` filter), per instrument
        (also `review_status`), and through a global list accepting
        `participant_id`, `indicator_id`, `instrument_id`, and
        `review_status` filters."

        Design: Corner/endpoints/observations_list_filter_by_review_status
        """
        world = setup_observation_world(program_name="Filter2", program_code="FL2")
        ind = world["indicators"]["I1"]
        obs1 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=10)
        obs2 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=20)
        record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=30)
        validate_observation(obs1["id"])
        validate_observation(obs2["id"])

        validated, validated_meta = validate_paginated(
            api.list_observations(STEWARD, params={"review_status": "VALIDATED"}))
        assert validated_meta["total_count"] == 2

        pending, pending_meta = validate_paginated(
            api.list_observations(STEWARD, params={"review_status": "PENDING"}))
        assert pending_meta["total_count"] == 1
