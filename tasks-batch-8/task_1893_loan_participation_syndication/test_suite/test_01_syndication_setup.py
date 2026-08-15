"""Borrower/facility/participant creation, defaults, pagination, and the
syndication commit path with its share-rounding rule (PRD §2.3, §2.5, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_participant,
    api_client,
    assert_borrower,
    assert_facility,
    assert_participant,
    commit_participant,
    create_borrower,
    create_borrower_payload,
    create_draw,
    create_facility,
    create_facility_payload,
    create_participant_payload,
    get_facility,
    get_participant,
    get_success_data,
    make_agent_headers,
    settlement_for_participant,
    setup_committed_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = make_agent_headers()


class TestCreationAndDefaults:
    def test_borrower_creation_defaults_and_system_fields(self):
        """PRD §3.1: "A new borrower's `status` starts at `ACTIVE`; the system —
        never a client — later moves it to `DELINQUENT` or `INSOLVENT` as default
        cases are declared against its facilities, and restores it to `ACTIVE`
        when those cases resolve (§3.7)."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/entities/borrower_creation_defaults_and_system_fields
        """
        created = validate_success(
            api_client.create_borrower(
                create_borrower_payload(legal_name="Acme"), AGENT
            ),
            expected_status=201,
        )
        assert_borrower(created)
        assert created["status"] == "ACTIVE"
        assert isinstance(created["version"], int)

        fetched = validate_success(api_client.get_borrower(created["id"], AGENT))
        assert_borrower(fetched)
        assert fetched["legal_name"] == "Acme"
        assert fetched["status"] == "ACTIVE"
        assert fetched["id"] == created["id"]

    def test_facility_optional_threshold_defaults(self):
        """PRD §3.1: "Four governance knobs carry defaults the caller may override:
        `majority_threshold_bps` defaults to 5001 and gates majority consents and
        default waivers; `supermajority_threshold_bps` defaults to 6667 and gates
        supermajority consents and acceleration; `quorum_bps` defaults to 5000 and
        sets the minimum cast share for a valid modification tally;
        `voting_window_days` defaults to 15 and lengths every solicitation window;
        and `min_transfer_cents` defaults to 1000000, setting both the smallest
        permissible participation transfer and the smallest residual stub a
        partial transfer may leave behind."
        PRD §3.1: "A facility is born in `STRUCTURING` status with every aggregate
        at zero."

        Design: Corner/entities/facility_optional_threshold_defaults
        """
        borrower = create_borrower(legal_name="Def B", sector="ENERGY",
                                   risk_rating="SPECULATIVE")
        facility = validate_success(
            api_client.create_facility(
                create_facility_payload(
                    borrower["id"],
                    facility_name="Fac Defaults",
                    total_commitment_cents=5_000_000,
                    interest_rate_bps=900,
                    day_count_basis="ACT_365",
                    servicing_fee_bps=10,
                    default_interest_addon_bps=300,
                    maturity_date="2030-01-01",
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert_facility(facility)
        assert facility["majority_threshold_bps"] == 5001
        assert facility["supermajority_threshold_bps"] == 6667
        assert facility["quorum_bps"] == 5000
        assert facility["voting_window_days"] == 15
        assert facility["min_transfer_cents"] == 1_000_000
        assert facility["status"] == "STRUCTURING"
        assert facility["committed_cents"] == 0
        assert facility["funded_principal_cents"] == 0
        assert facility["outstanding_principal_cents"] == 0
        assert facility["accrued_interest_cents"] == 0
        assert facility["undistributed_cash_cents"] == 0

    def test_facility_creation_missing_required_returns_invalid_request(self):
        """PRD §2.9: "5. Request shape: required fields present, enums within
        their domain, amounts strictly positive, `accrual_end_date` after
        `accrual_start_date`, `period_end_date` on or after `period_start_date`,
        the `terms` object containing exactly the key the `modification_type`
        requires, and exactly one of `transferee_participant_id` or
        `transferee_name` supplied — otherwise `ERR_INVALID_REQUEST`, or
        `ERR_TRANSFER_TARGET_AMBIGUOUS` for the transferee-pair violation."

        Design: Corner/entities/facility_creation_missing_required_returns_invalid_request
        """
        borrower = create_borrower(legal_name="Req B")
        payload = create_facility_payload(borrower["id"], facility_name="Fac Missing")
        del payload["interest_rate_bps"]
        resp = api_client.create_facility(payload, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_facility_invalid_enum_returns_invalid_request(self):
        """PRD §2.9: "5. Request shape: required fields present, enums within
        their domain, amounts strictly positive, `accrual_end_date` after
        `accrual_start_date`, `period_end_date` on or after `period_start_date`,
        the `terms` object containing exactly the key the `modification_type`
        requires, and exactly one of `transferee_participant_id` or
        `transferee_name` supplied — otherwise `ERR_INVALID_REQUEST`, or
        `ERR_TRANSFER_TARGET_AMBIGUOUS` for the transferee-pair violation."

        Design: Corner/entities/facility_invalid_enum_returns_invalid_request
        """
        borrower = create_borrower(legal_name="Enum B")
        payload = create_facility_payload(
            borrower["id"], facility_name="Fac Enum", day_count_basis="ACT_365X"
        )
        resp = api_client.create_facility(payload, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_participant_zero_commitment_rejected(self):
        """PRD §3.2: "The agent builds the lending group one Participant at a
        time, supplying the `facility_id`, the institution's `participant_name`,
        and a strictly positive `commitment_cents`."
        PRD §2.9: "5. Request shape: required fields present, enums within their
        domain, amounts strictly positive, `accrual_end_date` after
        `accrual_start_date`, `period_end_date` on or after `period_start_date`,
        the `terms` object containing exactly the key the `modification_type`
        requires, and exactly one of `transferee_participant_id` or
        `transferee_name` supplied — otherwise `ERR_INVALID_REQUEST`, or
        `ERR_TRANSFER_TARGET_AMBIGUOUS` for the transferee-pair violation."

        Design: Corner/entities/participant_zero_commitment_rejected
        """
        borrower = create_borrower(legal_name="Zero B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        resp = api_client.create_participant(
            create_participant_payload(
                facility["id"], participant_name="ZeroP", commitment_cents=0
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_participant_get_not_found_returns_404(self):
        """PRD §2.9: "4. Existence: every id in the path and every `*_id`
        reference in the body resolves to an existing resource — otherwise
        `ERR_NOT_FOUND`."

        Design: Corner/entities/participant_get_not_found_returns_404
        """
        resp = api_client.get_participant(NON_EXISTENT_UUID, AGENT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_participant_with_missing_facility_returns_not_found(self):
        """PRD §2.10: "The same rule applies to body references: a `facility_id`,
        `borrower_id`, `financial_statement_id`, `transferee_participant_id`, or
        any other `*_id` supplied in a request body must resolve to an existing
        resource, failing with `ERR_NOT_FOUND`."

        Design: Corner/entities/participant_with_missing_facility_returns_not_found
        """
        resp = api_client.create_participant(
            create_participant_payload(
                NON_EXISTENT_UUID, participant_name="Orphan", commitment_cents=1_000_000
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_participant_computed_fields_start_at_zero(self):
        """PRD §3.2: "Each participant starts `PROPOSED`."
        PRD §3.2: "The computation takes the eligible set — participants in
        `COMMITTED` or `FUNDED`; `PROPOSED`, `WITHDRAWN`, and `EXITED`
        participants always carry share zero".

        Design: Corner/entities/participant_computed_fields_start_at_zero
        """
        borrower = create_borrower(legal_name="Comp B", sector="TECHNOLOGY")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        participant = validate_success(
            api_client.create_participant(
                create_participant_payload(
                    facility["id"], participant_name="CompP", commitment_cents=1_000_000
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert_participant(participant)
        assert participant["status"] == "PROPOSED"
        assert participant["share_bps"] == 0
        assert participant["funded_cents"] == 0
        assert participant["cumulative_interest_cents"] == 0
        assert participant["cumulative_principal_cents"] == 0

    def test_facility_list_pagination_and_envelope(self):
        """PRD §2.3: "Endpoints that return lists of resources paginate via two
        query parameters. `limit` specifies the maximum number of items to
        return; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/facility_list_pagination_and_envelope
        """
        borrower = create_borrower(legal_name="List B", risk_rating="INVESTMENT_GRADE")
        create_facility(borrower["id"], facility_name="Fac L1",
                        total_commitment_cents=1_000_000)
        create_facility(borrower["id"], facility_name="Fac L2",
                        total_commitment_cents=2_000_000)

        resp = api_client.list_facilities(
            AGENT, params={"borrower_id": borrower["id"], "limit": 1, "offset": 0}
        )
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array"
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(data) == 1
        assert_facility(data[0])


class TestCommitAndBubbles:
    def test_participant_commit_valid_transition_and_bubbles(self):
        """PRD §3.2: "A successful commit recomputes the facility's
        `committed_cents` (a mutation that increments the Facility's `version`),
        recomputes every participant's `share_bps` as described below, and
        bubbles the facility upward: `STRUCTURING` → `SYNDICATING` on the first
        commit, and `SYNDICATING` → `COMMITTED` at the moment the committed
        total exactly equals the ceiling."

        Design: Corner/state_machines/participant_commit_valid_transition_and_bubbles
        """
        borrower = create_borrower(legal_name="Bub B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        participant = add_participant(facility["id"], "SP", 5_000_000)

        committed = validate_success(api_client.commit_participant(participant["id"], AGENT))
        assert_participant(committed)
        assert committed["status"] == "COMMITTED"
        assert committed["share_bps"] == 10_000

        refreshed = get_facility(facility["id"])
        assert refreshed["committed_cents"] == 5_000_000
        assert refreshed["status"] == "COMMITTED"

    def test_participant_commit_twice_rejected(self):
        """PRD §2.9: "6. Target-state legality: the target resource's own state
        permits the transition; terminal states reject everything — otherwise
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.2: "When the agent commits a proposed participant, two guards fire
        in validation order".

        Design: Corner/state_machines/participant_commit_twice_rejected
        """
        borrower = create_borrower(legal_name="Twice B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        participant = add_participant(facility["id"], "TP", 5_000_000)
        commit_participant(participant["id"])

        resp = api_client.commit_participant(participant["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_oversubscription_commit_rejected(self):
        """PRD §3.2: "the resulting committed total may not exceed
        `total_commitment_cents`, so a commit that would push `committed_cents`
        above the ceiling is rejected with `ERR_COMMITMENT_EXCEEDS_TOTAL`".

        Design: Corner/validations/oversubscription_commit_rejected
        """
        borrower = create_borrower(legal_name="Over B")
        facility = create_facility(borrower["id"], total_commitment_cents=10_000_000)
        p1 = add_participant(facility["id"], "P1", 7_000_000)
        p2 = add_participant(facility["id"], "P2", 4_000_000)
        commit_participant(p1["id"])

        resp = api_client.commit_participant(p2["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDS_TOTAL, expected_status=409)

    def test_facility_terminate_withdraws_participants_and_locks(self):
        """PRD §3.1: "Before any funding has occurred, the agent may abandon the
        deal: termination moves a facility from `STRUCTURING`, `SYNDICATING`, or
        `COMMITTED` to `TERMINATED`, and every participant still `PROPOSED` or
        `COMMITTED` is withdrawn with it, transitioning to `WITHDRAWN`."
        PRD §3.1: "Termination is refused with `ERR_INVALID_STATE_TRANSITION` if
        any draw with a status other than `CANCELLED` exists, and it is not
        offered at all from later facility states."

        Design: Corner/state_machines/facility_terminate_withdraws_participants_and_locks
        """
        borrower = create_borrower(legal_name="Ter B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        pa = add_participant(facility["id"], "A", 3_000_000)
        pb = add_participant(facility["id"], "B", 2_000_000)
        commit_participant(pa["id"])
        commit_participant(pb["id"])

        terminated = validate_success(api_client.terminate_facility(facility["id"], AGENT))
        assert_facility(terminated)
        assert terminated["status"] == "TERMINATED"
        assert get_participant(pa["id"])["status"] == "WITHDRAWN"
        assert get_participant(pb["id"])["status"] == "WITHDRAWN"

        resp = api_client.terminate_facility(facility["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


class TestVersioningAndShares:
    def test_version_increments_on_every_mutation(self):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, including mutations
        that only recompute derived fields."
        PRD §3.2: "A successful commit recomputes the facility's `committed_cents`
        (a mutation that increments the Facility's `version`)".

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        borrower = create_borrower(legal_name="Ver B")
        facility = create_facility(borrower["id"], total_commitment_cents=10_000_000)
        v0 = facility["version"]
        p1 = add_participant(facility["id"], "V1", 5_000_000)
        p2 = add_participant(facility["id"], "V2", 3_000_000)
        p3 = add_participant(facility["id"], "V3", 2_000_000)
        p1_v0 = p1["version"]

        committed = validate_success(api_client.commit_participant(p1["id"], AGENT))
        assert committed["version"] == p1_v0 + 1, (
            "participant commit mutates the participant exactly once"
        )
        commit_participant(p2["id"])
        commit_participant(p3["id"])

        final = get_facility(facility["id"])
        assert final["version"] == v0 + 3, (
            f"three commits must each increment the facility version by one: "
            f"{v0} -> {final['version']}"
        )

    def test_share_bps_floor_then_remainder_rounding_tie_goes_to_earliest(self):
        """PRD §3.2: "Flooring almost always leaves a remainder: the shortfall
        between ten thousand and the sum of the floored shares, which is always
        smaller than the number of eligible participants, is distributed one
        basis point at a time in descending order of `commitment_cents`, breaking
        ties by earlier `created_at` and then by ascending `participant_name`; a
        single pass always suffices."

        Design: Difficulty/combinatorial_formula/share_bps_floor_then_remainder_rounding
        """
        setup = setup_committed_facility(
            [("P1", 3_333_333), ("P2", 3_333_333), ("P3", 3_333_333)]
        )
        facility = setup["facility"]
        p1, p2, p3 = setup["participants"]
        assert facility["status"] == "COMMITTED"
        assert facility["committed_cents"] == 9_999_999

        # floor(10000 * 3,333,333 / 9,999,999) == 3333 each; the single remainder
        # bp goes to the earliest-created participant on the exact tie (P1).
        assert p1["share_bps"] == 3334
        assert p2["share_bps"] == 3333
        assert p3["share_bps"] == 3333
        assert p1["share_bps"] + p2["share_bps"] + p3["share_bps"] == 10_000

        # The draw's settlement dues expose the same rounding: dues floor per
        # participant share and sum exactly to the draw amount.
        draw = create_draw(facility["id"], 1_000_000)
        dues = [
            settlement_for_participant(p["id"], draw["id"])["due_cents"]
            for p in (p1, p2, p3)
        ]
        assert dues == [333_400, 333_300, 333_300]
        assert sum(dues) == 1_000_000

    def test_share_bps_remainder_goes_to_largest_commitment(self):
        """PRD §3.2: "Flooring almost always leaves a remainder: the shortfall
        between ten thousand and the sum of the floored shares, which is always
        smaller than the number of eligible participants, is distributed one
        basis point at a time in descending order of `commitment_cents`, breaking
        ties by earlier `created_at` and then by ascending `participant_name`; a
        single pass always suffices."

        Design: Difficulty/combinatorial_formula/share_bps_floor_then_remainder_rounding
        """
        setup = setup_committed_facility([("Big", 6_666_667), ("Small", 3_333_333)])
        big, small = setup["participants"]
        # raw shares: 6666.67 -> 6666 and 3333.33 -> 3333; the remainder bp goes
        # to the larger commitment (Big), not to an even split.
        assert big["share_bps"] == 6667
        assert small["share_bps"] == 3333
        assert big["share_bps"] + small["share_bps"] == 10_000
