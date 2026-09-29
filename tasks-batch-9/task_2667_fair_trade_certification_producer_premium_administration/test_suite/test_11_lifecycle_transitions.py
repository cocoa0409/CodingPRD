"""Where each lifecycle starts, which moves it offers, and what a refused move leaves behind."""

from test_helpers import (
    AUDITOR,
    AUDITOR_1_ID,
    CHAIR,
    OFFICER,
    api_errors as E,
    assert_clock_stamp,
    assert_fund_partition,
    assert_money,
    assert_new_node_position,
    assert_node_position,
    factories as f,
    make_producer_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCertificationGrant:
    """Granting certification is one write on the holder and one on each waiting node."""

    def test_certifying_a_pending_holder_activates_its_registered_node(self, api, clock):
        """The grant is stamped from the clock and carries the node from waiting to tradeable
        without touching the volumes booked at it.

        Design: Corner/state_machines/certify_moves_pending_holder_to_certified_and_activates_registered_nodes
        """
        holder = f.register_holder(api)
        headers = make_producer_representative_headers(holder["id"])
        node = f.register_node(api, headers, holder_id=holder["id"])
        assert node["status"] == "REGISTERED"

        certified = validate_success(api.certify_holder(holder["id"], OFFICER), 200)

        assert certified["certificate_status"] == "CERTIFIED"
        assert_clock_stamp(certified["certified_at"], clock, "certified_at")
        activated = f.read_node(api, node["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == node["version"] + 1, (
            "the cascade is a real write on the node"
        )
        assert_new_node_position(activated)

    def test_certifying_an_already_certified_holder_changes_nothing(self, api, clock):
        """The second grant is refused and the original grant instant survives the refusal.

        Design: Corner/state_machines/certify_twice_rejects_the_second_call
        """
        producer = f.build_certified_producer(api)
        before = f.read_holder(api, producer["holder_id"])
        f.set_clock(api, "2026-08-10T00:00:00Z")

        response = api.certify_holder(producer["holder_id"], OFFICER)

        validate_error(response, E.ERR_INVALID_STATE_TRANSITION, 409)
        after = f.read_holder(api, producer["holder_id"])
        assert_clock_stamp(after["certified_at"], clock, "certified_at")
        assert after["version"] == before["version"]
        assert after["certificate_status"] == "CERTIFIED"


class TestDeclaredInitialStates:
    """Every lifecycle in the service opens where the specification says it opens."""

    def test_a_holder_a_node_and_an_audit_all_open_in_their_first_state(self, api, clock):
        """A registration is pending, a node under a pending holder waits, and a freshly booked
        audit is scheduled with nothing recorded against it yet.

        Design: Corner/state_machines/holder_node_and_audit_start_in_their_declared_initial_states
        """
        holder = validate_success(api.create_holder(f.holder_payload(), OFFICER), 201)
        assert holder["certificate_status"] == "PENDING"

        node = validate_success(api.create_node(f.node_payload(holder["id"]), OFFICER), 201)
        assert node["status"] == "REGISTERED", "the owning holder was still pending"

        f.certify(api, holder["id"])
        audit = f.schedule_audit(
            api, holder["id"], window_start="2026-08-05", window_end="2026-08-07"
        )

        assert audit["status"] == "SCHEDULED"
        assert audit["nonconformity_count"] == 0
        assert audit["open_nonconformity_count"] == 0
        assert audit["started_at"] is None
        assert audit["closed_at"] is None
        assert audit["auditor_user_id"] == AUDITOR_1_ID
        assert audit["audit_type"] == "INITIAL"
        assert f.read_holder(api, holder["id"])["next_audit_due_at"] is None, (
            "the next audit falls due only once an audit has been closed"
        )


class TestTerminalCertificationState:
    """A withdrawn certification offers no moves at all."""

    def test_none_of_the_five_lifecycle_actions_work_on_a_decertified_holder(self, api, clock):
        """A denied application is terminal: certify, suspend, reinstate, sell-down and a second
        withdrawal are all refused, and none of them writes to the row.

        Design: Corner/state_machines/decertified_holder_cannot_be_certified_suspended_or_reinstated
        """
        holder = f.register_holder(api)
        headers = make_producer_representative_headers(holder["id"])
        f.register_node(api, headers, holder_id=holder["id"])
        denied = validate_success(
            api.decertify_holder(holder["id"], f.reason_payload("MANUAL"), OFFICER), 200
        )
        assert denied["certificate_status"] == "DECERTIFIED"
        dead_version = denied["version"]

        attempts = [
            api.certify_holder(holder["id"], OFFICER),
            api.suspend_holder(holder["id"], f.reason_payload("MANUAL"), OFFICER),
            api.reinstate_holder(holder["id"], OFFICER),
            api.transition_holder(holder["id"], OFFICER),
            api.decertify_holder(holder["id"], f.reason_payload("MANUAL"), OFFICER),
        ]

        for attempt in attempts:
            validate_error(attempt, E.ERR_INVALID_STATE_TRANSITION, 409)
        after = f.read_holder(api, holder["id"])
        assert after["certificate_status"] == "DECERTIFIED"
        assert after["version"] == dead_version, "no refused action wrote anything"


class TestTheTwoTradeDimensions:
    """Verification and settlement advance on their own, and each guards its own entry."""

    def test_settling_an_unverified_trade_is_refused_and_accrues_nothing(self, api, clock):
        """Money only moves after the auditor has spoken, so the refusal leaves the reservation,
        the fund and the ledger exactly as they were.

        Design: Corner/state_machines/settle_before_verification_is_rejected
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        trade = f.record_trade(api, chain, 10000)

        response = api.settle_trade(trade["id"], OFFICER)

        validate_error(response, E.ERR_INVALID_STATE_TRANSITION, 409)
        after = f.read_trade(api, trade["id"])
        assert after["settlement_status"] == "PENDING"
        assert after["verification_status"] == "UNVERIFIED"
        assert after["settled_at"] is None
        assert after["version"] == trade["version"]
        rows, meta = validate_paginated(
            api.list_ledger_entries(OFFICER, {"trade_transaction_id": trade["id"]})
        )
        assert meta["total_count"] == 0 and rows == []
        assert_fund_partition(
            f.read_fund(api, chain["producer_id"]), total_accrued_cents=0, balance_cents=0
        )
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            reserved_output_kg="10000.000", claimed_output_kg="0.000",
        )

    def test_disputing_a_trade_frees_the_credit_and_re_verifying_takes_it_back(self, api, clock):
        """A dispute puts the reserved tonnage back on the shelf; rehabilitating the trade
        reserves it again, and neither move touches the settled quantities.

        Design: Corner/state_machines/verify_disputed_releases_the_reservation_and_reverification_restores_it
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        trade = f.record_trade(api, chain, 10000)

        disputed = validate_success(
            api.verify_trade(trade["id"], {"outcome": "DISPUTED"}, AUDITOR), 200
        )

        assert disputed["verification_status"] == "DISPUTED"
        assert disputed["verified_at"] is None
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            reserved_output_kg="0.000", available_credit_kg="50000.000",
        )

        reverified = validate_success(
            api.verify_trade(trade["id"], {"outcome": "VERIFIED"}, AUDITOR), 200
        )

        assert reverified["verification_status"] == "VERIFIED"
        assert_clock_stamp(reverified["verified_at"], clock, "verified_at")
        assert reverified["settlement_status"] == "PENDING", "the money dimension never moved"
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            certified_input_kg="50000.000",
            reserved_output_kg="10000.000",
            claimed_output_kg="0.000",
            available_credit_kg="40000.000",
        )


class TestProposalEntryConditions:
    """A draft proposal has to be put to a vote before anything else can happen to it."""

    def test_revising_or_disbursing_a_draft_proposal_is_refused(self, api, clock):
        """Revision belongs to a returned proposal and disbursement to an approved one, so both
        are refused on a draft and neither touches the row, the fund or the committee.

        Design: Corner/state_machines/revise_and_disburse_from_draft_are_both_rejected
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        committee = f.constitute_committee(api, chain["producer_id"])
        chain["committee_id"] = committee["id"]
        f.record_settled_trade(api, chain, 10000)
        proposal = f.draft_proposal(api, chain, 500000)

        revise = api.revise_proposal(
            proposal["id"],
            f.revision_payload("School roof phase 2", "EDUCATION", 400000),
            CHAIR,
        )
        disburse = api.disburse_proposal(proposal["id"], OFFICER)

        validate_error(revise, E.ERR_INVALID_STATE_TRANSITION, 409)
        validate_error(disburse, E.ERR_INVALID_STATE_TRANSITION, 409)
        after = f.read_proposal(api, proposal["id"])
        assert after["status"] == "DRAFT"
        assert after["current_round"] == 0
        assert after["title"] == "School roof"
        assert_money(after["requested_amount_cents"], 500000, "requested_amount_cents")
        assert after["version"] == proposal["version"]
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund, balance_cents=800000, committed_cents=0, disbursed_cents=0
        )
        assert fund["pending_proposal_count"] == 1
        assert f.read_committee(api, committee["id"])["status"] == "FORMING", (
            "800000 cents never reached the million-cent activation threshold"
        )
