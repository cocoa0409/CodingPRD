"""Participation transfers: conservation, facility posture gating, minimums,
stubs, blackout windows, and transferor state rules (PRD §2.9, §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_participant,
    api_client,
    commit_participant,
    create_borrower,
    create_facility,
    create_payment,
    create_transfer_payload,
    declare_default,
    get_facility,
    get_participant,
    get_transfer,
    make_agent_headers,
    make_participant_headers,
    propose_transfer,
    settle_transfer,
    setup_committed_facility,
    setup_funded_facility,
    validate_error,
    validate_success,
)

AGENT = make_agent_headers()


class TestTransferConservation:
    def test_transfer_settle_conserves_total_commitment(self):
        """PRD §3.9: "The facility's `committed_cents` is unchanged by any
        transfer — the conservation invariant — while `share_bps` is recomputed
        for all participants".
        PRD §3.9: "The transferee side credits symmetrically: an existing
        participant's `commitment_cents` grows by the amount, or a new
        Participant is created whose status equals the transferor's current
        status and whose `commitment_cents` equals the amount;
        `transferee_resolved_participant_id` records who was credited."

        Design: Difficulty/compensating_invariant/transfer_settle_conserves_total_commitment
        """
        setup = setup_committed_facility(
            [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]
        )
        facility = setup["facility"]
        p1, p2, _ = setup["participants"]
        assert get_facility(facility["id"])["committed_cents"] == 10_000_000

        transfer = propose_transfer(
            facility["id"], p2["id"], 1_000_000, "2026-08-20",
            transferee_name="P4 Bank",
        )
        settled = settle_transfer(transfer["id"], p2["id"])
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None

        # Conservation: total identical before and after.
        assert get_facility(facility["id"])["committed_cents"] == 10_000_000
        assert get_participant(p2["id"])["commitment_cents"] == 2_000_000

        resolved = get_participant(settled["transferee_resolved_participant_id"])
        assert resolved["commitment_cents"] == 1_000_000
        assert resolved["status"] == "COMMITTED"  # transferor's current status

        assert get_participant(p1["id"])["share_bps"] == 6000
        assert get_participant(p2["id"])["share_bps"] == 2000
        assert resolved["share_bps"] == 1000

    def test_transfer_to_existing_participant_conserves_total(self):
        """PRD §3.9: "The transferee side credits symmetrically: an existing
        participant's `commitment_cents` grows by the amount".
        PRD §3.9: "The facility's `committed_cents` is unchanged by any transfer
        — the conservation invariant".

        Design: Difficulty/compensating_invariant/transfer_settle_conserves_total_commitment
        """
        setup = setup_committed_facility(
            [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]
        )
        facility = setup["facility"]
        p1, p2, p3 = setup["participants"]

        transfer = propose_transfer(
            facility["id"], p2["id"], 1_000_000, "2026-08-20",
            transferee_participant_id=p1["id"],
        )
        settled = settle_transfer(transfer["id"], p2["id"])
        assert settled["status"] == "SETTLED"
        assert settled["transferee_resolved_participant_id"] == p1["id"]

        assert get_facility(facility["id"])["committed_cents"] == 10_000_000
        assert get_participant(p1["id"])["commitment_cents"] == 7_000_000
        assert get_participant(p2["id"])["commitment_cents"] == 2_000_000
        assert get_participant(p1["id"])["share_bps"] == 7000
        assert get_participant(p2["id"])["share_bps"] == 2000
        assert get_participant(p3["id"])["share_bps"] == 1000


class TestTransferPostureGating:
    def test_transfer_default_posture_beats_commitment_overflow(self):
        """PRD §2.9: "When several validations could reject the same request, the
        server evaluates them in the following fixed priority order and returns
        the error from the first failing check only".
        PRD §2.9: "7. Cross-entity facility posture: the facility is not in
        `IN_DEFAULT`, `ACCELERATED`, `CLOSED`, or `TERMINATED` for solicitation,
        transfer propose and settle, and prepayment payments; the facility is
        `COMMITTED` for draw creation; the facility is in `FUNDING`, `ACTIVE`,
        `IN_DEFAULT`, or `ACCELERATED` for buyback demands — otherwise
        `ERR_FACILITY_IN_DEFAULT` or `ERR_FACILITY_NOT_COMMITTED` as the rule
        nominates."
        PRD §2.9: "13. Fiscal caps and thresholds: draw headroom, settlement
        amount equality and late-penalty equality, the distribution principal
        pool within outstanding principal, transfer minimums and residual stubs,
        acceleration and waiver thresholds, and write-downs within outstanding
        principal — otherwise `ERR_DRAW_EXCEEDS_COMMITMENT`,
        `ERR_FUNDING_AMOUNT_MISMATCH`, `ERR_PENALTY_AMOUNT_MISMATCH`,
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_TRANSFER_BELOW_MINIMUM`,
        `ERR_TRANSFER_EXCEEDS_COMMITMENT`, `ERR_TRANSFER_STUB_BELOW_MINIMUM`,
        `ERR_ACCELERATION_THRESHOLD_NOT_MET`, `ERR_WAIVER_THRESHOLD_NOT_MET`, or
        `ERR_WRITEDOWN_EXCEEDS_OUTSTANDING`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_default_posture_beats_commitment_overflow
        """
        setup = setup_funded_facility([("P1", 6_000_000), ("P2", 4_000_000)], 1_000_000)
        facility = setup["facility"]
        p1 = setup["participants"][0]
        declare_default(facility["id"], "PAYMENT_DEFAULT")
        assert get_facility(facility["id"])["status"] == "IN_DEFAULT"

        # The amount also exceeds P1's 6,000,000 commitment; posture (7) wins.
        resp = api_client.create_transfer(
            create_transfer_payload(
                facility["id"],
                transfer_amount_cents=9_999_999_999,
                settlement_date="2026-09-15",
                transferee_name="Overflow Buyer",
            ),
            make_participant_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_IN_DEFAULT, expected_status=409)

    def test_transfer_approve_blocked_by_default_posture(self):
        """PRD §3.9: "The agent then approves the proposal — `PROPOSED` →
        `AGENT_APPROVED`, under the same facility-posture rule — or rejects it
        outright into `REJECTED`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_default_posture_beats_commitment_overflow
        """
        setup = setup_funded_facility([("P1", 6_000_000), ("P2", 4_000_000)], 1_000_000)
        facility = setup["facility"]
        p2 = setup["participants"][1]

        transfer = propose_transfer(
            facility["id"], p2["id"], 1_000_000, "2026-09-10",
            transferee_name="Late Buyer",
        )
        declare_default(facility["id"], "PAYMENT_DEFAULT")

        resp = api_client.approve_transfer(transfer["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_FACILITY_IN_DEFAULT, expected_status=409)
        assert get_transfer(transfer["id"])["status"] == "PROPOSED"

    def test_transfer_settle_gated_on_facility_posture(self):
        """PRD §3.9: "Settlement moves `AGENT_APPROVED` → `SETTLED` and is
        optimistic-concurrency checked with
        `expected_from_participant_version` against the transferor's current
        `version` (§2.8); at settle time the facility posture is re-validated and
        the amount is re-checked against the transferor's current commitment,
        failing `ERR_TRANSFER_EXCEEDS_COMMITMENT` if the transferor's position
        has shrunk."
        PRD §3.9: "the facility must not be `IN_DEFAULT` or `ACCELERATED`
        (`ERR_FACILITY_IN_DEFAULT`)".

        Design: Difficulty/cross_entity_state_dependency/transfer_settle_gated_on_facility_posture
        """
        setup = setup_funded_facility([("P1", 6_000_000), ("P2", 4_000_000)], 1_000_000)
        facility = setup["facility"]
        p2 = setup["participants"][1]

        transfer = propose_transfer(
            facility["id"], p2["id"], 1_000_000, "2026-09-10",
            transferee_name="Gate Buyer",
        )
        validate_success(api_client.approve_transfer(transfer["id"], AGENT))

        # Facility falls into default between approve and settle.
        declare_default(facility["id"], "COVENANT_DEFAULT")
        transferor = get_participant(p2["id"])
        resp = api_client.settle_transfer(
            transfer["id"],
            {"expected_from_participant_version": transferor["version"]},
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_IN_DEFAULT, expected_status=409)
        assert get_transfer(transfer["id"])["status"] == "AGENT_APPROVED"

    def test_transfer_propose_blocked_while_in_default(self):
        """PRD §3.9: "Proposal carries a battery of guards, each with its own
        failure: the facility must not be `IN_DEFAULT` or `ACCELERATED`
        (`ERR_FACILITY_IN_DEFAULT`) nor `CLOSED` or `TERMINATED`
        (`ERR_INVALID_STATE_TRANSITION`)".

        Design: Difficulty/cross_entity_state_dependency/transfer_settle_gated_on_facility_posture
        """
        setup = setup_funded_facility([("P1", 6_000_000), ("P2", 4_000_000)], 1_000_000)
        facility = setup["facility"]
        p2 = setup["participants"][1]
        declare_default(facility["id"], "PAYMENT_DEFAULT")

        resp = api_client.create_transfer(
            create_transfer_payload(
                facility["id"],
                transfer_amount_cents=1_000_000,
                settlement_date="2026-09-10",
                transferee_name="Buyer",
            ),
            make_participant_headers(p2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_IN_DEFAULT, expected_status=409)


class TestTransferorStateRules:
    def test_exited_participant_terminal_lockdown_rejected(self):
        """PRD §2.9: "6. Target-state legality: the target resource's own state
        permits the transition; terminal states reject everything — otherwise
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.9: "a transfer that consumes the entire commitment exits the
        transferor to `EXITED`".

        Design: Corner/state_machines/exited_participant_terminal_lockdown_rejected
        """
        setup = setup_committed_facility([("P1", 6_000_000), ("P2", 4_000_000)])
        facility = setup["facility"]
        p2 = setup["participants"][1]

        transfer = propose_transfer(
            facility["id"], p2["id"], 4_000_000, "2026-08-10", transferee_name="Buyer"
        )
        settle_transfer(transfer["id"], p2["id"])
        assert get_participant(p2["id"])["status"] == "EXITED"

        resp = api_client.commit_participant(p2["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_transfer_settle_from_proposed_rejected(self):
        """PRD §3.9: "Settlement moves `AGENT_APPROVED` → `SETTLED`".
        PRD §2.9: "6. Target-state legality: the target resource's own state
        permits the transition; terminal states reject everything — otherwise
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/transfer_settle_from_proposed_rejected
        """
        setup = setup_committed_facility([("SP", 5_000_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]
        transfer = propose_transfer(
            facility["id"], participant["id"], 1_000_000, "2026-08-20",
            transferee_name="Buyer",
        )

        resp = api_client.settle_transfer(
            transfer["id"],
            {"expected_from_participant_version": get_participant(participant["id"])["version"]},
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


class TestTransferProposalGuards:
    def test_transfer_below_minimum_rejected(self):
        """PRD §3.9: "the amount must be at least the facility's
        `min_transfer_cents` (`ERR_TRANSFER_BELOW_MINIMUM`)".
        PRD §3.1: "`min_transfer_cents` defaults to 1000000".

        Design: Corner/validations/transfer_below_minimum_rejected
        """
        setup = setup_committed_facility([("MP", 5_000_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]

        resp = api_client.create_transfer(
            create_transfer_payload(
                facility["id"],
                transfer_amount_cents=999_999,
                settlement_date="2026-08-20",
                transferee_name="Buyer",
            ),
            make_participant_headers(participant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_BELOW_MINIMUM, expected_status=409)

    def test_transfer_stub_below_minimum_rejected(self):
        """PRD §3.9: "a partial transfer must leave either nothing or a residual
        stub of at least `min_transfer_cents` (`ERR_TRANSFER_STUB_BELOW_MINIMUM`)".

        Design: Corner/validations/transfer_stub_below_minimum_rejected
        """
        setup = setup_committed_facility([("SP", 1_500_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]

        # 1,100,000 clears the 1,000,000 minimum amount but leaves a 400,000
        # residual stub, below the 1,000,000 minimum stub.
        resp = api_client.create_transfer(
            create_transfer_payload(
                facility["id"],
                transfer_amount_cents=1_100_000,
                settlement_date="2026-08-20",
                transferee_name="Buyer",
            ),
            make_participant_headers(participant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_STUB_BELOW_MINIMUM, expected_status=409)

    def test_transfer_ambiguous_target_rejected(self):
        """PRD §3.9: "Supplying both or neither fails with
        `ERR_TRANSFER_TARGET_AMBIGUOUS`".

        Design: Corner/validations/transfer_ambiguous_target_rejected
        """
        setup = setup_committed_facility([("P1", 3_000_000), ("P2", 2_000_000)])
        facility = setup["facility"]
        p1, p2 = setup["participants"]

        payload = create_transfer_payload(
            facility["id"], transfer_amount_cents=1_000_000,
            settlement_date="2026-08-20",
        )
        payload["transferee_participant_id"] = p2["id"]  # both designators present
        resp = api_client.create_transfer(payload, make_participant_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_TARGET_AMBIGUOUS, expected_status=400)

    def test_self_transfer_rejected(self):
        """PRD §3.9: "naming oneself as transferee fails with
        `ERR_SELF_TRANSFER`".

        Design: Corner/validations/self_transfer_rejected
        """
        setup = setup_committed_facility([("SP", 5_000_000)], total_commitment_cents=5_000_000)
        facility = setup["facility"]
        participant = setup["participants"][0]

        payload = create_transfer_payload(
            facility["id"], transfer_amount_cents=1_000_000,
            settlement_date="2026-08-20",
        )
        payload.pop("transferee_name")
        payload["transferee_participant_id"] = participant["id"]
        resp = api_client.create_transfer(payload, make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_TRANSFER, expected_status=409)

    def test_transfer_settlement_blackout_rejected(self):
        """PRD §3.9: "the `settlement_date` must not fall inside the blackout
        window of any non-reversed payment on the facility — the closed interval
        from two days before to two days after the payment's `value_date` —
        failing `ERR_SETTLEMENT_IN_BLACKOUT`."

        Design: Corner/validations/transfer_settlement_blackout_rejected
        """
        setup = setup_funded_facility(
            [("P1", 3_000_000), ("P2", 2_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        p1 = setup["participants"][0]
        # A RECEIVED payment valued 2026-08-20 closes [2026-08-18, 2026-08-22].
        create_payment(facility["id"], setup["borrower"]["id"], 50_000, "2026-08-20")

        resp = api_client.create_transfer(
            create_transfer_payload(
                facility["id"], transfer_amount_cents=1_000_000,
                settlement_date="2026-08-19", transferee_name="Buyer",
            ),
            make_participant_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_IN_BLACKOUT, expected_status=409)

        ok = validate_success(
            api_client.create_transfer(
                create_transfer_payload(
                    facility["id"], transfer_amount_cents=1_000_000,
                    settlement_date="2026-08-17", transferee_name="Buyer",
                ),
                make_participant_headers(p1["id"]),
            ),
            expected_status=201,
        )
        assert ok["status"] == "PROPOSED"
