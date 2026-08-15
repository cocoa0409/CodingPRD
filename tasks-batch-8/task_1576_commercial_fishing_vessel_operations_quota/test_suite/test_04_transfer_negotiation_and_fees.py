"""Quota lease negotiation: counter cycles, acceptance gates, state lockdown,
OCC on rounds, tiered settlement fees, and season-end expiry (PRD §3.7, §2.5)."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_holding,
    create_permit,
    get_availability,
    get_holding,
    get_permit_status,
    get_transfer,
    make_vessel_owner_headers,
    propose_transfer,
    setup_transfer_pair,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestCounterOfferCycle:
    def test_counter_offer_cycles_rounds_and_sides(self):
        """PRD §3.7: "A counter replaces `pounds` and `price_per_lb_cents` with the
        payload values, increments `round_number` by one, flips `last_offered_by` to
        the other side, and toggles the status — `PROPOSED` to `COUNTERED`, or
        `COUNTERED` back to `PROPOSED`." and "Acceptance likewise belongs to the side
        that did not table the current offer".

        Design: Difficulty/non_linear_state_machine/transfer_counter_offer_cycle
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        v1, v2 = ctx["v1"]["id"], ctx["v2"]["id"]
        transfer = propose_transfer(v1, v2, pounds=5000, price_per_lb_cents=400)
        assert transfer["status"] == "PROPOSED"
        assert transfer["round_number"] == 1
        assert transfer["last_offered_by"] == "FROM_VESSEL"

        c1 = validate_success(api_client.counter_quota_transfer(
            transfer["id"],
            {"pounds": 4500, "price_per_lb_cents": 450,
             "expected_transfer_version": transfer["version"]},
            make_vessel_owner_headers(v2)), 200)
        assert c1["status"] == "COUNTERED"
        assert c1["round_number"] == 2
        assert c1["last_offered_by"] == "TO_VESSEL"

        c2 = validate_success(api_client.counter_quota_transfer(
            transfer["id"],
            {"pounds": 4500, "price_per_lb_cents": 475,
             "expected_transfer_version": c1["version"]},
            make_vessel_owner_headers(v1)), 200)
        assert c2["status"] == "PROPOSED"
        assert c2["round_number"] == 3
        assert c2["last_offered_by"] == "FROM_VESSEL"

        accepted = validate_success(api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(v2)), 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["pounds"] == 4500
        assert accepted["price_per_lb_cents"] == 475

        assert get_availability(ctx["h1"]["id"])["available_committed_pounds"] == 15500
        assert get_availability(ctx["h2"]["id"])["available_committed_pounds"] == 9500

    def test_countered_offer_declined_restores_availability(self):
        """PRD §3.7: "Declining is available to the non-tabling side from `PROPOSED`
        or `COUNTERED` and moves the transfer to `DECLINED`." After decline no offer
        is open, so the §3.2 conservative subtraction no longer applies.

        Design: Difficulty/non_linear_state_machine/transfer_counter_offer_cycle
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        v1, v2 = ctx["v1"]["id"], ctx["v2"]["id"]
        transfer = propose_transfer(v1, v2, pounds=5000, price_per_lb_cents=400)
        countered = validate_success(api_client.counter_quota_transfer(
            transfer["id"],
            {"pounds": 4500, "price_per_lb_cents": 450,
             "expected_transfer_version": transfer["version"]},
            make_vessel_owner_headers(v2)), 200)
        assert countered["status"] == "COUNTERED"
        declined = validate_success(api_client.decline_quota_transfer(
            transfer["id"], make_vessel_owner_headers(v1)), 200)
        assert declined["status"] == "DECLINED"
        availability = get_availability(ctx["h1"]["id"])
        assert availability["available_committed_pounds"] == 20000
        assert availability["available_conservative_pounds"] == 20000


class TestAcceptanceGates:
    def test_accept_rechecks_to_vessel_permit(self):
        """PRD §3.7: "At acceptance the platform re-checks that both vessels still
        hold an `ISSUED` permit for the fishery (`ERR_PERMIT_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/transfer_accept_gated_by_permit_state
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        get_success = validate_success(
            api_client.revoke_permit(ctx["p2"]["id"], REG), 200)
        assert get_success["status"] == "REVOKED"
        resp = api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(ctx["v2"]["id"]))
        validate_error(resp, "ERR_PERMIT_NOT_ACTIVE", 409)
        assert get_transfer(transfer["id"])["status"] == "PROPOSED"
        assert get_availability(ctx["h1"]["id"])["available_committed_pounds"] == 20000

    def test_accept_rechecks_from_vessel_permit(self):
        """PRD §3.7: "At acceptance the platform re-checks that both vessels still
        hold an `ISSUED` permit for the fishery (`ERR_PERMIT_NOT_ACTIVE`)" — the
        from-side permit is re-checked too.

        Design: Difficulty/cross_entity_state_dependency/transfer_accept_gated_by_permit_state
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        revoked = validate_success(api_client.revoke_permit(ctx["p1"]["id"], REG), 200)
        assert revoked["status"] == "REVOKED"
        resp = api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(ctx["v2"]["id"]))
        validate_error(resp, "ERR_PERMIT_NOT_ACTIVE", 409)
        assert get_transfer(transfer["id"])["status"] == "PROPOSED"

    def test_transfer_revoked_permit_beats_quota_error(self):
        """PRD §2.7 evaluates "8. **Cross-entity link state** — vessels must be
        `ACTIVE`, fishery permits must be `ISSUED`, and quota holdings must exist
        for the required fishery and year (`ERR_VESSEL_NOT_ACTIVE` and
        `ERR_PERMIT_NOT_ACTIVE` are 409; `ERR_QUOTA_HOLDING_NOT_FOUND` is 404)."
        before "10. **Fiscal gates** — quota sufficiency and settlement solvency
        (`ERR_QUOTA_EXCEEDED` is 402; `ERR_SETTLEMENT_UNDERWATER` is 422)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_permit_referential_beats_quota_fiscal
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        validate_success(api_client.revoke_permit(ctx["p2"]["id"], REG), 200)
        resp = api_client.create_quota_transfer(
            {"from_vessel_id": ctx["v1"]["id"], "to_vessel_id": ctx["v2"]["id"],
             "fishery_code": "HALIBUT", "season_year": 2026,
             "pounds": 999999, "price_per_lb_cents": 100},
            make_vessel_owner_headers(ctx["v1"]["id"]))
        validate_error(resp, "ERR_PERMIT_NOT_ACTIVE", 409)

    def test_transfer_missing_holding_beats_quota_error(self):
        """PRD §2.7 item 8: "8. **Cross-entity link state** — vessels must be
        `ACTIVE`, fishery permits must be `ISSUED`, and quota holdings must exist
        for the required fishery and year (`ERR_VESSEL_NOT_ACTIVE` and
        `ERR_PERMIT_NOT_ACTIVE` are 409; `ERR_QUOTA_HOLDING_NOT_FOUND` is 404).",
        evaluated before item 10 fiscal gates. PRD §2.9:
        "`ERR_QUOTA_HOLDING_NOT_FOUND` doubles as the failure when no holding
        matches a required fishery-and-year combination implied by a request
        body."

        Design: Difficulty/priority_pair_validation_conflict/transfer_permit_referential_beats_quota_fiscal
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        # Remove the to-side's holding coverage by negotiating a fishery it has
        # a permit for but no holding: issue SABLEFISH permits to both, holding
        # only on the from-side.
        create_permit(ctx["v1"]["id"], fishery_code="SABLEFISH", gear_type="LONGLINE")
        create_permit(ctx["v2"]["id"], fishery_code="SABLEFISH", gear_type="POT")
        create_holding(ctx["v1"]["id"], fishery_code="SABLEFISH", initial_pounds=20000)
        resp = api_client.create_quota_transfer(
            {"from_vessel_id": ctx["v1"]["id"], "to_vessel_id": ctx["v2"]["id"],
             "fishery_code": "SABLEFISH", "season_year": 2026,
             "pounds": 999999, "price_per_lb_cents": 100},
            make_vessel_owner_headers(ctx["v1"]["id"]))
        validate_error(resp, "ERR_QUOTA_HOLDING_NOT_FOUND", 404)


class TestTransferStateMachine:
    def test_settle_proposed_transfer_rejected(self):
        """PRD §3.7: "An `ACCEPTED` transfer is settled by a `SettlementClerk` — any
        other status yields `ERR_TRANSFER_NOT_ACCEPTED` — moving it to `SETTLED` and
        computing `transfer_fee_cents`, which remains null until this point."

        Design: Corner/state_machines/settle_proposed_transfer_rejected
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        resp = api_client.settle_quota_transfer(transfer["id"], CLERK)
        validate_error(resp, "ERR_TRANSFER_NOT_ACCEPTED", 409)
        current = get_transfer(transfer["id"])
        assert current["status"] == "PROPOSED"
        assert current["transfer_fee_cents"] is None

    def test_counter_settled_transfer_terminal_lockdown(self):
        """PRD §3.7: "A counter-offer is valid from either `PROPOSED` or `COUNTERED`
        (`ERR_TRANSFER_NOT_OPEN` otherwise)". PRD §3.7 fee rule: "When the settled
        poundage is at most 1,000 pounds, the fee is a flat 25,000 cents."

        Design: Corner/state_machines/counter_settled_transfer_terminal_lockdown
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        v1, v2 = ctx["v1"]["id"], ctx["v2"]["id"]
        transfer = propose_transfer(v1, v2, pounds=1000, price_per_lb_cents=500)
        validate_success(api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(v2)), 200)
        settled = validate_success(
            api_client.settle_quota_transfer(transfer["id"], CLERK), 200)
        assert settled["status"] == "SETTLED"
        assert settled["transfer_fee_cents"] == 25000
        resp = api_client.counter_quota_transfer(
            transfer["id"],
            {"pounds": 900, "price_per_lb_cents": 600,
             "expected_transfer_version": settled["version"]},
            make_vessel_owner_headers(v1))
        validate_error(resp, "ERR_TRANSFER_NOT_OPEN", 409)
        assert get_transfer(transfer["id"])["transfer_fee_cents"] == 25000

    def test_accept_own_offer_rejected(self):
        """PRD §3.7: "Acceptance likewise belongs to the side that did not table the
        current offer, from `PROPOSED` or `COUNTERED` (`ERR_TRANSFER_NOT_OPEN`,
        `ERR_TRANSFER_OWN_OFFER` as applicable)."

        Design: Corner/state_machines/accept_own_offer_rejected
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        resp = api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(ctx["v1"]["id"]))
        validate_error(resp, "ERR_TRANSFER_OWN_OFFER", 409)
        assert get_transfer(transfer["id"])["status"] == "PROPOSED"

    def test_occ_transfer_counter_stale_version(self):
        """PRD §2.6: "Countering a quota transfer requires `expected_transfer_version`,
        matching the transfer's current `version`; a counter supersedes the prior
        negotiation round, so the caller must have observed the latest round. In all
        four cases, a value that does not match the parent entity's current `version`
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_transfer_counter_stale_version
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        stale_version = transfer["version"] - 1
        resp = api_client.counter_quota_transfer(
            transfer["id"],
            {"pounds": 4500, "price_per_lb_cents": 450,
             "expected_transfer_version": stale_version},
            make_vessel_owner_headers(ctx["v2"]["id"]))
        validate_error(resp, "ERR_STALE_VERSION", 412)
        current = get_transfer(transfer["id"])
        assert current["status"] == "PROPOSED"
        assert current["round_number"] == 1


class TestTransferFeeSchedule:
    def test_transfer_fee_tier_schedule(self):
        """PRD §3.7: "When the settled poundage is at most 1,000 pounds, the fee is a
        flat 25,000 cents. When the poundage is greater than 1,000 and at most 10,000
        pounds, the fee is 25,000 cents plus 4 percent of the lease's total value —
        pounds multiplied by the price per pound in cents — with that percentage
        component rounded half-up to whole cents. When the poundage exceeds 10,000
        pounds, the fee is 25,000 cents plus 4 percent of the value of the first
        10,000 pounds (10,000 times the price per pound), rounded half-up, plus
        7 percent of the value of the pounds above 10,000, that component also
        rounded half-up to whole cents."

        Design: Corner/calculations/transfer_fee_tier_schedule
        """
        ctx = setup_transfer_pair(holding1_pounds=100000, holding2_pounds=5000)
        v1, v2 = ctx["v1"]["id"], ctx["v2"]["id"]
        expected_fees = []
        for pounds in (1000, 2000, 12000):
            transfer = propose_transfer(v1, v2, pounds=pounds, price_per_lb_cents=500)
            validate_success(api_client.accept_quota_transfer(
                transfer["id"], make_vessel_owner_headers(v2)), 200)
            expected_fees.append((transfer["id"], pounds))
        fees = []
        for transfer_id, pounds in expected_fees:
            settled = validate_success(
                api_client.settle_quota_transfer(transfer_id, CLERK), 200)
            fees.append((pounds, settled["transfer_fee_cents"]))
        assert fees[0] == (1000, 25000), f"flat tier: {fees[0]}"
        assert fees[1] == (2000, 65000), (
            f"mid tier 25000 + 4% of 1000000 = 65000, got {fees[1]}")
        assert fees[2] == (12000, 295000), (
            f"high tier 25000 + 200000 + 70000 = 295000, got {fees[2]}")


class TestSeasonEndExpiry:
    def test_clock_driven_permit_and_transfer_expiry(self):
        """PRD §2.5: "A permit in `ISSUED` or `SUSPENDED` moves to `EXPIRED` once
        the clock passes its `valid_to`."
        PRD §2.5: "A quota transfer in `PROPOSED`, `COUNTERED`, or `ACCEPTED` moves
        to `EXPIRED` once the clock passes the end of the transfer's `season_year`
        — that is, past 23:59:59 UTC on December 31 of that year."
        PRD §2.5: "A quota share holding in `ACTIVE` moves to `CLOSED` once the
        clock passes the end of its `season_year`."

        Design: Corner/state_machines/clock_driven_permit_and_transfer_expiry
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        advance_clock("2027-01-01T00:00:00Z")
        assert get_permit_status(ctx["v1"]["id"]) == "EXPIRED"
        assert get_transfer(transfer["id"])["status"] == "EXPIRED"
        assert get_holding(ctx["h1"]["id"])["status"] == "CLOSED"
