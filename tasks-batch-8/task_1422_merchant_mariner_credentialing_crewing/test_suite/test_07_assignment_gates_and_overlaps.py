"""Assignment creation/confirmation gate battery: endorsement, rank,
channel, rotation window, posture, union dispatch, and the two overlap
semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_assignment,
    create_activated_mariner,
    create_assignment_payload,
    create_mariner,
    create_manning_slot,
    issue_credential,
    issue_medical_certificate,
    make_union_dispatcher_headers,
    propose_assignment,
    record_negative_drug_test,
    set_clock,
    setup_active_vessel_with_slot,
    setup_confirmed_assignment,
    setup_crewing_scenario,
    setup_onboard_assignment,
    setup_union_mariner,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]
CAPTAIN = TEST_USERS["port_captain_headers"]


class TestAssignmentServerFields:

    def test_assignment_server_fields_input_ignored(self):
        """PRD section 3.7: "The vessel is denormalized onto the assignment
        as `vessel_id` from the billet's vessel. A new assignment is
        `PROPOSED`, with `travel_status` `PENDING` and `repatriation_status`
        `NOT_DUE`."

        Design: Corner/entities/assignment_server_fields_input_ignored
        """
        ctx = setup_crewing_scenario()
        bogus_vessel = "11111111-2222-3333-4444-555555555555"
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["mariner"]["id"], ctx["slot"]["id"],
                travel_status="READY", repatriation_status="DUE",
                vessel_id=bogus_vessel),
            CREWING)
        data = validate_success(resp, expected_status=201)
        assert data["assignment_status"] == "PROPOSED"
        assert data["travel_status"] == "PENDING", \
            f"injected travel_status must be ignored, got {data['travel_status']}"
        assert data["repatriation_status"] == "NOT_DUE"
        assert data["vessel_id"] == ctx["vessel"]["id"], \
            "vessel_id must be denormalized from the billet's vessel"


class TestEndorsementAndRankGates:

    def test_endorsement_mismatch_blocks_assignment(self):
        """PRD section 3.7: "a filler lacking a `VALID` credential carrying
        the billet's `required_endorsement_code` (`ERR_ENDORSEMENT_MISMATCH`)"

        Design: Corner/errors/endorsement_mismatch_blocks_assignment
        """
        mariner = create_activated_mariner()
        env = setup_active_vessel_with_slot(
            slot_overrides={
                "position_code": "MASTER", "min_rank_grade": 5,
                "required_endorsement_code": "MASTER_UNL",
                "is_critical_position": True, "standard_tour_days": 120},
            plan_overrides={"standard_tour_days": 120})
        resp = api_client.create_assignment(
            create_assignment_payload(mariner["id"], env["slot"]["id"]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_MISMATCH)

    def test_rank_below_minimum_blocks_assignment(self):
        """PRD section 3.7: "a mariner whose `rank_track` differs from the
        billet's `rank_track` or whose `rank_grade` is below the billet's
        `min_rank_grade` (`ERR_RANK_BELOW_MINIMUM`)"

        Design: Corner/errors/rank_below_minimum_blocks_assignment
        """
        low = create_activated_mariner(rank_grade=2)
        high = create_activated_mariner(rank_grade=8)
        env = setup_active_vessel_with_slot(
            slot_overrides={"position_code": "OICNW", "min_rank_grade": 5})

        resp = api_client.create_assignment(
            create_assignment_payload(low["id"], env["slot"]["id"]), CREWING)
        validate_error(resp, ApiErrorId.ERR_RANK_BELOW_MINIMUM)

        ok = validate_success(
            api_client.create_assignment(
                create_assignment_payload(high["id"], env["slot"]["id"]),
                CREWING),
            expected_status=201)
        assert ok["assignment_status"] == "PROPOSED", \
            "grade 8 passes the same billet"


class TestChannelAndRotationWindowGates:

    def test_channel_mismatch_rejected(self):
        """PRD section 3.7: "A `UNION_DISPATCH` assignment requires the acting
        role to be `UnionDispatcher`, the mariner's `hire_channel` to be
        `UNION_HALL`, the referenced registration to be in `REGISTERED`
        status, and the registration's `dues_current_until` to be on or after
        the `sign_on_date` — violations surface as `ERR_CHANNEL_NOT_PERMITTED`,
        `ERR_UNION_REGISTRATION_INVALID`, or `ERR_DUES_NOT_CURRENT`"

        Design: Corner/errors/channel_mismatch_rejected
        """
        ctx = setup_union_mariner()
        hall, mariner, registration = (
            ctx["hall"], ctx["mariner"], ctx["registration"])
        validate_success(
            api_client.extend_registration_dues(
                hall["id"], registration["id"],
                {"new_dues_current_until": "2027-01-01T00:00:00Z"},
                make_union_dispatcher_headers(hall["id"])))
        env = setup_active_vessel_with_slot()

        # A CrewingManager may not drive the union channel, even with a valid
        # registration id.
        resp = api_client.create_assignment(
            create_assignment_payload(
                mariner["id"], env["slot"]["id"],
                assignment_channel="UNION_DISPATCH",
                union_registration_id=registration["id"]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_PERMITTED)

    def test_no_active_rotation_window_rejected(self):
        """PRD section 3.7: "First, the rotation-window gate: the vessel must
        have an `ACTIVE` rotation plan whose `effective_from` is on or before
        the `sign_on_date` and whose `effective_to` is strictly after it, else
        `ERR_NO_ACTIVE_ROTATION_WINDOW`."

        Design: Corner/errors/no_active_rotation_window_rejected
        """
        mariner = create_activated_mariner()
        env = setup_active_vessel_with_slot(with_rotation_plan=False)
        resp = api_client.create_assignment(
            create_assignment_payload(mariner["id"], env["slot"]["id"]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ROTATION_WINDOW)


class TestConfirmGatedByMarinerPosture:

    def _setup_posture_gate(self):
        """Mariner CLEAR at the default clock (medical 2026-09-01 is 31 days
        out); one PROPOSED assignment."""
        mariner = create_activated_mariner(
            medical_expiry="2026-09-01T00:00:00Z")
        assert mariner["readiness_posture"] == "CLEAR"
        env = setup_active_vessel_with_slot()
        assignment = propose_assignment(
            mariner["id"], env["slot"]["id"],
            sign_on_date="2026-10-01T00:00:00Z",
            planned_relief_date="2027-01-01T00:00:00Z", local_join=True)
        return {"mariner": mariner, "assignment": assignment, **env}

    def test_confirm_blocked_after_medical_expiry_sweep(self):
        """PRD section 3.7: "the mariner's posture must be `CLEAR`, or
        `RESTRICTED` with the `planned_relief_date` on or before the earliest
        restricting expiry (else `ERR_MARINER_NOT_CLEAR` or
        `ERR_RESTRICTED_WINDOW_EXCEEDED`)"
        PRD section 2.6: "Medical certificates in `VALID` or `SUSPENDED` whose
        `expiry_date` is strictly earlier than the new clock become
        `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_mariner_posture
        """
        ctx = self._setup_posture_gate()
        set_clock("2026-09-02T00:00:00Z")  # sweeps the medical certificate

        mariner = validate_success(api_client.get_mariner(ctx["mariner"]["id"],
                                                          CREWING))
        assert mariner["readiness_posture"] == "BLOCKED"
        assert "NO_VALID_MEDICAL" in mariner["readiness_reasons"]

        resp = api_client.confirm_assignment(ctx["assignment"]["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_CLEAR)

    def test_confirm_succeeds_after_fresh_medical_restores_clear(self):
        """PRD section 3.5: "A certificate is created `VALID` and remains
        valid while its `expiry_date` is on or after the current clock;
        issuance recomputes the mariner's posture."
        PRD section 3.7: "Confirmation moves `PROPOSED` to `CONFIRMED` — any
        other source state is `ERR_INVALID_STATE` — and re-runs the full gate
        battery against the now-current state of the world"

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_mariner_posture
        """
        ctx = self._setup_posture_gate()
        set_clock("2026-09-02T00:00:00Z")
        resp = api_client.confirm_assignment(ctx["assignment"]["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_CLEAR)

        # A fresh medical certificate (a CredentialingOfficer write on a
        # different aggregate) reopens the gate.
        issue_medical_certificate(
            ctx["mariner"]["id"], issue_date="2026-09-02T00:00:00Z",
            expiry_date="2027-09-01T00:00:00Z")
        mariner = validate_success(api_client.get_mariner(ctx["mariner"]["id"],
                                                          CREWING))
        assert mariner["readiness_posture"] == "CLEAR"

        confirmed = confirm_assignment(ctx["assignment"]["id"])
        assert confirmed["assignment_status"] == "CONFIRMED"


class TestUnionDispatchGates:

    def test_union_dispatch_blocked_by_stale_dues_then_allowed(self):
        """PRD section 3.7: "A `UNION_DISPATCH` assignment requires the acting
        role to be `UnionDispatcher`, the mariner's `hire_channel` to be
        `UNION_HALL`, the referenced registration to be in `REGISTERED`
        status, and the registration's `dues_current_until` to be on or after
        the `sign_on_date` — violations surface as `ERR_CHANNEL_NOT_PERMITTED`,
        `ERR_UNION_REGISTRATION_INVALID`, or `ERR_DUES_NOT_CURRENT`"
        PRD section 3.7: "The registration is created `REGISTERED` with
        `dues_current_until` initialized to the `seniority_date`"

        Design: Difficulty/cross_entity_state_dependency/union_dispatch_gated_by_registration_and_dues
        """
        ctx = setup_union_mariner(seniority_date="2026-01-01T00:00:00Z")
        hall, mariner, registration = (
            ctx["hall"], ctx["mariner"], ctx["registration"])
        dispatcher = make_union_dispatcher_headers(hall["id"])
        assert registration["dues_current_until"] == "2026-01-01T00:00:00Z", \
            "dues initialized to the seniority date"

        env = setup_active_vessel_with_slot()
        payload = create_assignment_payload(
            mariner["id"], env["slot"]["id"],
            assignment_channel="UNION_DISPATCH",
            union_registration_id=registration["id"])
        resp = api_client.create_assignment(payload, dispatcher)
        validate_error(resp, ApiErrorId.ERR_DUES_NOT_CURRENT)

        validate_success(
            api_client.extend_registration_dues(
                hall["id"], registration["id"],
                {"new_dues_current_until": "2027-01-01T00:00:00Z"}, dispatcher))
        created = validate_success(
            api_client.create_assignment(payload, dispatcher),
            expected_status=201)
        assert created["assignment_status"] == "PROPOSED"

    def test_union_dispatch_confirm_gated_by_registration_status(self):
        """PRD section 3.7: "and for union dispatch the registration and dues
        checks are re-run."
        PRD section 3.7: "the referenced registration to be in `REGISTERED`
        status ... violations surface as `ERR_CHANNEL_NOT_PERMITTED`,
        `ERR_UNION_REGISTRATION_INVALID`, or `ERR_DUES_NOT_CURRENT`"

        Design: Difficulty/cross_entity_state_dependency/union_dispatch_gated_by_registration_and_dues
        """
        ctx = setup_union_mariner()
        hall, mariner, registration = (
            ctx["hall"], ctx["mariner"], ctx["registration"])
        dispatcher = make_union_dispatcher_headers(hall["id"])
        validate_success(
            api_client.extend_registration_dues(
                hall["id"], registration["id"],
                {"new_dues_current_until": "2027-01-01T00:00:00Z"}, dispatcher))
        env = setup_active_vessel_with_slot()
        assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    mariner["id"], env["slot"]["id"],
                    assignment_channel="UNION_DISPATCH",
                    union_registration_id=registration["id"]),
                dispatcher),
            expected_status=201)

        validate_success(
            api_client.suspend_registration(
                hall["id"], registration["id"], dispatcher))
        resp = api_client.confirm_assignment(assignment["id"], dispatcher)
        validate_error(resp, ApiErrorId.ERR_UNION_REGISTRATION_INVALID)

        validate_success(
            api_client.reinstate_registration(
                hall["id"], registration["id"], dispatcher))
        confirmed = validate_success(
            api_client.confirm_assignment(assignment["id"], dispatcher))
        assert confirmed["assignment_status"] == "CONFIRMED", \
            "reinstated registration reopens the gate"


class TestMarinerOverlapSemantics:

    def _setup_with_confirmed(self):
        """CLEAR mariner with one CONFIRMED assignment on slot 1
        [2026-08-10, 2026-11-10); vessel also carries slot 2."""
        ctx = setup_confirmed_assignment()
        slot2 = create_manning_slot(
            ctx["vessel"]["id"], position_code="OS", min_rank_grade=1)
        return {**ctx, "slot2": slot2}

    def test_mariner_one_day_overlap_rejected(self):
        """PRD section 3.7: "Second, mariner double-booking uses strict
        half-open interval semantics with zero tolerance: over the mariner's
        own assignments in `CONFIRMED`, `ONBOARD`, or `SUSPENDED`, an overlap
        exists exactly when the new `sign_on_date` is strictly before the
        existing `planned_relief_date` and the existing `sign_on_date` is
        strictly before the new `planned_relief_date`"

        Design: Difficulty/resource_temporal_overlap/mariner_strict_half_open_zero_tolerance
        """
        ctx = self._setup_with_confirmed()
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["mariner"]["id"], ctx["slot2"]["id"],
                sign_on_date="2026-11-09T00:00:00Z",
                planned_relief_date="2027-02-09T00:00:00Z"),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_MARINER_ASSIGNMENT_OVERLAP)

    def test_mariner_touching_endpoints_accepted(self):
        """PRD section 3.7: "touching endpoints — a new sign-on exactly equal
        to an existing planned relief — do not overlap, and a true overlap is
        `ERR_MARINER_ASSIGNMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/mariner_strict_half_open_zero_tolerance
        """
        ctx = self._setup_with_confirmed()
        created = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    ctx["mariner"]["id"], ctx["slot2"]["id"],
                    sign_on_date="2026-11-10T00:00:00Z",
                    planned_relief_date="2027-02-10T00:00:00Z"),
                CREWING),
            expected_status=201)
        assert created["assignment_status"] == "PROPOSED"
        confirmed = confirm_assignment(created["id"])
        assert confirmed["assignment_status"] == "CONFIRMED", \
            "half-open semantics: touching at 2026-11-10 is not an overlap"


class TestSlotHandoverSemantics:

    def test_handover_overlap_exactly_max_days_allowed(self):
        """PRD section 3.7: "the handover is allowed only when that overlap is
        at most the active plan's `max_handover_overlap_days` — equality is
        allowed — else `ERR_HANDOVER_WINDOW_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/handover_overlap_exactly_max_days_allowed
        """
        ctx = setup_onboard_assignment()  # M1 ONBOARD [08-10, 11-10)
        m3 = create_activated_mariner()
        created = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    m3["id"], ctx["slot"]["id"],
                    sign_on_date="2026-11-07T00:00:00Z",
                    planned_relief_date="2027-02-07T00:00:00Z"),
                CREWING),
            expected_status=201)
        assert created["assignment_status"] == "PROPOSED"
        confirmed = confirm_assignment(created["id"])
        assert confirmed["assignment_status"] == "CONFIRMED", \
            "3-day overlap <= max_handover_overlap_days 3: equality allowed"

    def test_handover_overlap_beyond_max_days_rejected(self):
        """PRD section 3.7: "the handover is allowed only when that overlap is
        at most the active plan's `max_handover_overlap_days` — equality is
        allowed — else `ERR_HANDOVER_WINDOW_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/handover_overlap_exactly_max_days_allowed
        """
        ctx = setup_onboard_assignment()  # M1 ONBOARD [08-10, 11-10)
        m2 = create_activated_mariner()
        resp = api_client.create_assignment(
            create_assignment_payload(
                m2["id"], ctx["slot"]["id"],
                sign_on_date="2026-11-06T00:00:00Z",
                planned_relief_date="2027-02-06T00:00:00Z"),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_HANDOVER_WINDOW_EXCEEDED)

    def test_same_mariner_overlap_rejected_where_slot_handover_allows(self):
        """PRD section 3.7: "Second, mariner double-booking uses strict
        half-open interval semantics with zero tolerance"
        PRD section 3.7: "Third, slot handover is a bounded buffer: over the
        other assignments on the same billet in `CONFIRMED` or `ONBOARD`"

        Design: Difficulty/resource_temporal_overlap/slot_buffered_handover_window
        """
        ctx = setup_onboard_assignment()  # M1 ONBOARD on slot 1
        slot2 = create_manning_slot(
            ctx["vessel"]["id"], position_code="OS", min_rank_grade=1)
        # The same mariner overlapping by 2 days on ANOTHER billet hits the
        # zero-tolerance mariner check.
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["mariner"]["id"], slot2["id"],
                sign_on_date="2026-11-08T00:00:00Z",
                planned_relief_date="2027-02-08T00:00:00Z"),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_MARINER_ASSIGNMENT_OVERLAP)

    def test_other_mariner_two_day_overlap_accepted_on_same_slot(self):
        """PRD section 3.7: "the overlap in whole days is the earlier of the
        two `planned_relief_date` values minus the later of the two
        `sign_on_date` values, floored to whole days with a negative result
        treated as zero; the handover is allowed only when that overlap is at
        most the active plan's `max_handover_overlap_days`"

        Design: Difficulty/resource_temporal_overlap/slot_buffered_handover_window
        """
        ctx = setup_onboard_assignment()  # M1 ONBOARD on the slot
        m2 = create_activated_mariner()
        created = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    m2["id"], ctx["slot"]["id"],
                    sign_on_date="2026-11-08T00:00:00Z",
                    planned_relief_date="2027-02-08T00:00:00Z",
                    relief_of_assignment_id=ctx["assignment"]["id"]),
                CREWING),
            expected_status=201)
        assert created["assignment_status"] == "PROPOSED"
        confirmed = confirm_assignment(created["id"])
        assert confirmed["assignment_status"] == "CONFIRMED", \
            "identical 2-day overlap accepted on the billet: 2 <= 3"
