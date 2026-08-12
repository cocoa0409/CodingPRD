"""Call sheets: rest-floor boundary, waiver path, and validation priorities."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_published_call,
    create_rehearsal_call,
    create_rehearsal_call_payload,
    create_rehearsal_room,
    make_contracts_officer_headers,
    setup_contract_with_confirmed_call,
    transition_rehearsal_call,
    validate_error,
    validate_success,
)

CO = TEST_USERS["contracts_officer_headers"]
ANY = TEST_USERS["any_headers"]


class TestRestFloorBoundary:
    def test_rest_floor_exactly_twelve_hours_passes_and_eleven_fails(self, api):
        """PRD §3.6: "Let the floor F be the contract's `rest_floor_hours` converted to seconds. For the new participant's call, consider every other call on which the same contract already holds a participant in `CONFIRMED` or `CHECKED_IN` status and which is itself `PUBLISHED` or `COMPLETED`. A pair is rest-compliant when the new call starts at least F seconds after the other call ends, or the other call starts at least F seconds after the new call ends. If any committed pair is not compliant — including any pair whose calls overlap — the rest floor is violated. A gap of exactly F seconds passes."
        PRD §3.6: "when the flag is false or absent, the creation is rejected with `ERR_REST_FLOOR_VIOLATION` (HTTP 422)."

        Call A Mon 08:00-20:00 (CONFIRMED). Call B Tue 08:00 (gap exactly 12h,
        passes); call C Tue 07:00 (gap 11h, rejected).

        Design: Difficulty/boundary_precision_check/rest_floor_exactly_twelve_hours
        """
        scenario = setup_contract_with_confirmed_call()
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_b = create_published_call(production["id"], room["id"],
                                       "2026-06-02T08:00:00Z", "2026-06-02T20:00:00Z",
                                       call_type="BLOCKING")
        room2 = create_rehearsal_room(name="Studio 2", capacity=30, hourly_rate_cents=4_000)
        call_c = create_published_call(production["id"], room2["id"],
                                       "2026-06-02T07:00:00Z", "2026-06-02T11:00:00Z",
                                       call_type="STAGING")

        resp = api.create_call_participant(
            {"call_id": call_b["id"], "contract_id": contract["id"]}, CO
        )
        participant_b = validate_success(resp, 201)
        assert participant_b["status"] == "INVITED", (
            "gap of exactly 12h passes the rest floor"
        )

        resp = api.create_call_participant(
            {"call_id": call_c["id"], "contract_id": contract["id"]}, CO
        )
        validate_error(resp, ApiErrorId.ERR_REST_FLOOR_VIOLATION)

    def test_rest_floor_exactly_twelve_hours_reverse_direction_passes(self, api):
        """PRD §3.6: "A pair is rest-compliant when the new call starts at least F seconds after the other call ends, or the other call starts at least F seconds after the new call ends. If any committed pair is not compliant — including any pair whose calls overlap — the rest floor is violated. A gap of exactly F seconds passes."

        The confirmed call D sits AFTER the new call E: D Wed 08:00-12:00,
        E Tue 16:00-20:00 — D starts exactly 12h after E ends, so the second
        disjunct passes at exact equality.

        Design: Difficulty/boundary_precision_check/rest_floor_exactly_twelve_hours
        """
        scenario = setup_contract_with_confirmed_call(
            call_starts_at="2026-06-03T08:00:00Z", call_ends_at="2026-06-03T12:00:00Z"
        )
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_e = create_published_call(production["id"], room["id"],
                                       "2026-06-02T16:00:00Z", "2026-06-02T20:00:00Z",
                                       call_type="STAGING")
        resp = api.create_call_participant(
            {"call_id": call_e["id"], "contract_id": contract["id"]}, CO
        )
        participant_e = validate_success(resp, 201)
        assert participant_e["status"] == "INVITED", (
            "other call starts exactly F seconds after the new call ends: passes"
        )


class TestStateBeatsRestFloor:
    def test_add_participant_to_cancelled_call_returns_call_not_open(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline. Earlier failures mask later ones: a request that fails step 1 never reaches step 2, a request that fails shape validation never reaches the fiscal check, and so on."
        PRD §2.9: "8. **State legality.** The target entity's current state must permit the requested transition or action."
        PRD §3.6: "The call must still be open — `DRAFT` or `PUBLISHED` — since participant operations on a `COMPLETED` or `CANCELLED` call are rejected with `ERR_CALL_NOT_OPEN`."

        The cancelled call C (Tue 06:00-10:00) would ALSO violate the 12h rest
        floor against call A (Mon 08:00-20:00); the state failure (step 8) masks
        the rest-floor failure (step 12).

        Design: Difficulty/priority_pair_validation_conflict/cancelled_call_state_beats_rest_violation
        """
        scenario = setup_contract_with_confirmed_call()
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_c = create_rehearsal_call(production["id"], room["id"],
                                       "2026-06-02T06:00:00Z", "2026-06-02T10:00:00Z",
                                       call_type="BLOCKING")
        transition_rehearsal_call(call_c["id"], "CANCELLED")

        resp = api.create_call_participant(
            {"call_id": call_c["id"], "contract_id": contract["id"]}, CO
        )
        validate_error(resp, ApiErrorId.ERR_CALL_NOT_OPEN)

    def test_add_participant_to_completed_call_returns_call_not_open(self, api):
        """PRD §3.6: "The call must still be open — `DRAFT` or `PUBLISHED` — since participant operations on a `COMPLETED` or `CANCELLED` call are rejected with `ERR_CALL_NOT_OPEN`."

        Same state-vs-rest-floor pair, with the call in COMPLETED rather than
        CANCELLED: call D Tue 06:00-10:00 is played to COMPLETED while its timing
        would also violate the 12h rest floor against call A (Mon 08:00-20:00).

        Design: Difficulty/priority_pair_validation_conflict/cancelled_call_state_beats_rest_violation
        """
        scenario = setup_contract_with_confirmed_call()
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_d = create_published_call(production["id"], room["id"],
                                       "2026-06-02T06:00:00Z", "2026-06-02T10:00:00Z",
                                       call_type="BLOCKING")
        transition_rehearsal_call(call_d["id"], "COMPLETED")

        resp = api.create_call_participant(
            {"call_id": call_d["id"], "contract_id": contract["id"]}, CO
        )
        validate_error(resp, ApiErrorId.ERR_CALL_NOT_OPEN)


class TestDuplicateBeatsRestFloor:
    def test_duplicate_participant_beats_rest_violation(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline. Earlier failures mask later ones: a request that fails step 1 never reaches step 2, a request that fails shape validation never reaches the fiscal check, and so on."
        PRD §3.6: "At most one non-terminal participant may exist for the same call and contract pair — a prior participant in `INVITED`, `WAIVER_PENDING`, `CONFIRMED`, or `CHECKED_IN` blocks the add with `ERR_DUPLICATE_PARTICIPANT` (HTTP 409), while a `DECLINED` or `REMOVED` one does not."
        PRD §3.6: "A violation is handled according to `waive_rest_floor`: when the flag is true, the participant is created in `WAIVER_PENDING` instead of being rejected; when the flag is false or absent, the creation is rejected with `ERR_REST_FLOOR_VIOLATION` (HTTP 422)."

        Call B (Tue 06:00-10:00) violates the rest floor against call A; the
        waived first add lands in WAIVER_PENDING, and the second add hits the
        referential guard (step 10) before the rest floor (step 12).

        Design: Difficulty/priority_pair_validation_conflict/duplicate_participant_referential_beats_rest_violation
        """
        scenario = setup_contract_with_confirmed_call()
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_b = create_published_call(production["id"], room["id"],
                                       "2026-06-02T06:00:00Z", "2026-06-02T10:00:00Z",
                                       call_type="BLOCKING")

        resp = api.create_call_participant(
            {"call_id": call_b["id"], "contract_id": contract["id"],
             "waive_rest_floor": True},
            CO,
        )
        participant_b = validate_success(resp, 201)
        assert participant_b["status"] == "WAIVER_PENDING", (
            "the waive flag routed the rest-floor violation to WAIVER_PENDING"
        )

        resp = api.create_call_participant(
            {"call_id": call_b["id"], "contract_id": contract["id"]}, CO
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTICIPANT)

    def test_declined_participant_does_not_block_readd(self, api):
        """PRD §3.6: "At most one non-terminal participant may exist for the same call and contract pair — a prior participant in `INVITED`, `WAIVER_PENDING`, `CONFIRMED`, or `CHECKED_IN` blocks the add with `ERR_DUPLICATE_PARTICIPANT` (HTTP 409), while a `DECLINED` or `REMOVED` one does not."

        The declined call E sits a full week after the confirmed call A, so no
        rest-floor question arises and the re-add succeeds cleanly.

        Design: Difficulty/priority_pair_validation_conflict/duplicate_participant_referential_beats_rest_violation
        """
        scenario = setup_contract_with_confirmed_call()
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_e = create_published_call(production["id"], room["id"],
                                       "2026-06-08T08:00:00Z", "2026-06-08T12:00:00Z",
                                       call_type="STAGING")
        resp = api.create_call_participant(
            {"call_id": call_e["id"], "contract_id": contract["id"]}, CO
        )
        participant_e = validate_success(resp, 201)
        resp = api.transition_call_participant(participant_e["id"], "DECLINED", CO)
        declined = validate_success(resp, 200)
        assert declined["status"] == "DECLINED"

        resp = api.create_call_participant(
            {"call_id": call_e["id"], "contract_id": contract["id"]}, CO
        )
        readded = validate_success(resp, 201)
        assert readded["status"] == "INVITED", (
            "a DECLINED participant is terminal and does not block a re-add"
        )


class TestWaiverSegregationOfDuties:
    def test_sod_waiver_same_user_forbidden(self, api):
        """PRD §2.10: "Approving a rest-floor waiver on a call participant must be performed by a `ContractsOfficer` whose `X-User-ID` differs from the `created_by_user_id` recorded on the underlying contract."
        PRD §2.10: "Either violation is rejected with `ERR_SOD_SAME_USER_FORBIDDEN` (HTTP 403)."

        Officer-1 creates the contract and parks a rest-violating participant in
        WAIVER_PENDING; officer-1's approval is rejected, officer-2's succeeds.

        Design: Corner/rbac/sod_waiver_same_user_forbidden
        """
        scenario = setup_contract_with_confirmed_call(officer_user_id="officer-1")
        production, room, contract = (
            scenario["production"], scenario["room"], scenario["contract"],
        )
        call_b = create_published_call(production["id"], room["id"],
                                       "2026-06-02T06:00:00Z", "2026-06-02T10:00:00Z",
                                       call_type="BLOCKING")
        officer1 = make_contracts_officer_headers("officer-1")
        officer2 = make_contracts_officer_headers("officer-2")

        resp = api.create_call_participant(
            {"call_id": call_b["id"], "contract_id": contract["id"],
             "waive_rest_floor": True},
            officer1,
        )
        participant_b = validate_success(resp, 201)
        assert participant_b["status"] == "WAIVER_PENDING"

        resp = api.approve_waiver(participant_b["id"], officer1)
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER_FORBIDDEN)

        resp = api.approve_waiver(participant_b["id"], officer2)
        approved = validate_success(resp, 200)
        assert approved["status"] == "CONFIRMED", (
            "a different ContractsOfficer approves: WAIVER_PENDING -> CONFIRMED"
        )
