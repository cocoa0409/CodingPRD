"""Token minting, redemption ladder, reversal, and vendor standing (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_market, create_active_vendor, create_standard_batches,
    create_verified_shopper, create_open_day, create_program,
    setup_booth_scenario, issue_tokens, minted_tokens, redeem_serials,
    create_submission,
    make_vendor_headers,
    assert_token,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]


class TestMintedTokenState:
    def test_minted_token_initial_state(self, api):
        """PRD §3.1: "Every token minted anywhere in the program records its
        `serial_number`, the `kind` and `denomination_cents` copied from its
        supplying batch, the `issuance_id` that minted it, the `token_batch_id`
        its serial was drawn from, and two lifecycle references that start
        empty: `redeemed_vendor_id`, set when a vendor accepts the token, and
        `submission_id`, set while a reimbursement claim holds the token."
        PRD §3.5: "A successful redemption moves the token `ISSUED → REDEEMED`,
        records the accepting vendor in the token's `redeemed_vendor_id`,
        raises the issuing day's `redeemed_value_cents` by the token's face
        value with `variance_cents` recomputed, and increments both the
        token's and the day's `version`."

        Design: Corner/state_machines/c_sm_token_minted_into_initial_state_issued
        """
        sc = setup_booth_scenario(with_vendor=False)
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        assert len(tokens) == 2, "charge 100 mints 1 base + 1 match token"
        token = tokens[0]
        assert_token(token)
        assert token["status"] == "ISSUED", "minted tokens start ISSUED"
        assert token["redeemed_vendor_id"] is None
        assert token["submission_id"] is None


class TestSerialTriage:
    def test_redeem_unknown_and_unminted_serials_distinguished(self, api):
        """PRD §3.5: "The serial must map to a minted token: a serial outside
        every batch range of the program is rejected with
        `ERR_TOKEN_UNKNOWN_SERIAL`, while a serial that falls inside a batch
        range but has not yet been minted is treated as a counterfeit signal
        and rejected with `ERR_TOKEN_NOT_MINTED`."

        Design: Corner/validations/c_val_redeem_unknown_and_unminted_serials_distinguished
        """
        sc = setup_booth_scenario()
        issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_headers = make_vendor_headers(sc["vendor"]["id"])

        unknown = api.redeem_token(999999, vend_headers)
        validate_error(unknown, ApiErrorId.ERR_TOKEN_UNKNOWN_SERIAL)

        unminted = api.redeem_token(200050, vend_headers)
        validate_error(unminted, ApiErrorId.ERR_TOKEN_NOT_MINTED)


class TestDeadAndMislocatedScrip:
    def test_redeem_voided_token_rejected(self, api):
        """PRD §3.5: "A `VOIDED` or `CONFISCATED` token is refused with
        `ERR_TOKEN_VOID`."

        Design: Corner/validations/c_val_redeem_voided_token_rejected
        """
        sc = setup_booth_scenario()
        issuance, _tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        validate_success(api.void_issuance(issuance["id"], BOOTH))

        resp = api.redeem_token(200001, make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TOKEN_VOID)

    def test_cross_market_redemption_rejected(self, api):
        """PRD §3.5: "The acting vendor must be `ACTIVE`
        (`ERR_VENDOR_NOT_ACTIVE`) and must belong to the same market whose
        market day issued the token — a cross-market redemption is rejected
        with `ERR_TOKEN_VENDOR_MISMATCH`."

        Design: Corner/validations/c_val_cross_market_redemption_rejected
        """
        program = create_program()
        market_a = create_market(program["id"], name="MA")
        market_b = create_market(program["id"], name="MB")
        create_standard_batches(market_a["id"])
        shopper = create_verified_shopper(program["id"])
        day = create_open_day(market_a["id"])
        vendor_b = create_active_vendor(market_b["id"], legal_name="VB", stall_number="S9")

        shopper_now = get_success_data(api.get_shopper(shopper["id"], BOOTH))
        issuance = validate_success(api.create_issuance({
            "shopper_id": shopper["id"], "market_day_id": day["id"],
            "benefit_charged_cents": 100,
            "expected_shopper_version": shopper_now["version"],
        }, BOOTH), expected_status=201)
        assert issuance["status"] == "ACTIVE"

        resp = api.redeem_token(200001, make_vendor_headers(vendor_b["id"]))
        validate_error(resp, ApiErrorId.ERR_TOKEN_VENDOR_MISMATCH)

        tokens = minted_tokens(issuance["id"])
        assert tokens[0]["status"] == "ISSUED", "token stays ISSUED after rejected cross-market redeem"


class TestVendorStandingGate:
    def _suspended_vendor_scenario(self, api):
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        validate_success(api.set_vendor_status(sc["vendor"]["id"], "SUSPENDED", ADMIN))
        return sc, issuance, tokens

    def test_suspended_vendor_redeem_rejected(self, api):
        """PRD §3.5: "Redemption attempts and claim submissions by a vendor
        that is not `ACTIVE` are rejected with `ERR_VENDOR_NOT_ACTIVE`."
        PRD §3.5: "The acting vendor must be `ACTIVE`
        (`ERR_VENDOR_NOT_ACTIVE`) and must belong to the same market whose
        market day issued the token — a cross-market redemption is rejected
        with `ERR_TOKEN_VENDOR_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/redeem_gated_by_vendor_active
        """
        sc, _issuance, tokens = self._suspended_vendor_scenario(api)
        serial = tokens[0]["serial_number"]
        resp = api.redeem_token(serial, make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

    def test_suspended_vendor_redeem_no_side_effects(self, api):
        """PRD §3.5: "Redemption attempts and claim submissions by a vendor
        that is not `ACTIVE` are rejected with `ERR_VENDOR_NOT_ACTIVE`."
        PRD §3.5: "A successful redemption moves the token `ISSUED → REDEEMED`,
        records the accepting vendor in the token's `redeemed_vendor_id`,
        raises the issuing day's `redeemed_value_cents` by the token's face
        value with `variance_cents` recomputed, and increments both the
        token's and the day's `version`."

        Design: Difficulty/cross_entity_state_dependency/redeem_gated_by_vendor_active
        """
        sc, issuance, tokens = self._suspended_vendor_scenario(api)
        serial = tokens[0]["serial_number"]
        resp = api.redeem_token(serial, make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

        token = get_success_data(api.get_token(tokens[0]["id"], ADMIN))
        assert token["status"] == "ISSUED", "rejected redemption leaves the token ISSUED"
        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["redeemed_value_cents"] == 0


class TestVendorStatusCycle:
    def test_vendor_suspend_reinstate_cycle_gates_redemption(self, api):
        """PRD §3.5: "From `ACTIVE` a vendor can be suspended and later
        reinstated — the status cycle between `ACTIVE` and `SUSPENDED` is
        driven by an administrator supplying a target `to` status — and the
        vendor state machine has no terminal state."
        PRD §3.5: "Redemption attempts and claim submissions by a vendor
        that is not `ACTIVE` are rejected with `ERR_VENDOR_NOT_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/vendor_suspend_reinstate_cycle_gates_redemption
        """
        sc = setup_booth_scenario()
        _issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        serial = tokens[0]["serial_number"]

        validate_success(api.set_vendor_status(vend_id, "SUSPENDED", ADMIN))
        blocked = api.redeem_token(serial, make_vendor_headers(vend_id))
        validate_error(blocked, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

        validate_success(api.set_vendor_status(vend_id, "ACTIVE", ADMIN))
        redeemed = validate_success(api.redeem_token(serial, make_vendor_headers(vend_id)))
        assert redeemed["status"] == "REDEEMED", "reinstatement re-enables redemption"
        assert redeemed["redeemed_vendor_id"] == vend_id

    def test_vendor_cycle_version_progression(self, api):
        """PRD §2.5: "`version` (integer): starts at 1 at creation and
        increments by one on every mutation — including mutations caused by
        cascade side effects originating on another resource. A token voided by
        a batch recall, a market day whose totals recompute after a redemption,
        and a shopper whose season usage changes at issuance all increment
        their own `version` and refresh their own `updated_at`."
        PRD §3.5: "From `ACTIVE` a vendor can be suspended and later
        reinstated — the status cycle between `ACTIVE` and `SUSPENDED` is
        driven by an administrator supplying a target `to` status — and the
        vendor state machine has no terminal state."

        Design: Difficulty/non_linear_state_machine/vendor_suspend_reinstate_cycle_gates_redemption
        """
        sc = setup_booth_scenario()
        vend_id = sc["vendor"]["id"]
        assert sc["vendor"]["version"] == 2, "create 1, approve 2"

        suspended = validate_success(api.set_vendor_status(vend_id, "SUSPENDED", ADMIN))
        assert suspended["version"] == 3
        reinstated = validate_success(api.set_vendor_status(vend_id, "ACTIVE", ADMIN))
        assert reinstated["version"] == 4, "one bump per status mutation"
        assert reinstated["status"] == "ACTIVE"


class TestRedemptionReversal:
    def test_redeem_reverse_conserves_issued_unit_count(self, api):
        """PRD §3.5: "A successful redemption moves the token `ISSUED →
        REDEEMED`, records the accepting vendor in the token's
        `redeemed_vendor_id`, raises the issuing day's `redeemed_value_cents`
        by the token's face value with `variance_cents` recomputed, and
        increments both the token's and the day's `version`."
        PRD §3.5: "The reversal moves the token `REDEEMED → ISSUED`, clears
        `redeemed_vendor_id`, lowers the day's `redeemed_value_cents` by the
        face value, recomputes the variance, and increments both versions."

        Design: Difficulty/compensating_invariant/redeem_reverse_conserves_issued_unit_count
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]

        def issued_count():
            return sum(1 for t in minted_tokens(issuance["id"]) if t["status"] == "ISSUED")

        assert issued_count() == 6, "3 base + 3 match all ISSUED"
        redeem_serials(vend_id, [t0["serial_number"]])
        assert issued_count() == 5, "one redeemed, five still ISSUED"

        reversed_token = validate_success(
            api.reverse_redemption(t0["id"], make_vendor_headers(vend_id)))
        assert reversed_token["status"] == "ISSUED"
        assert issued_count() == 6, "reversal restores the issued unit count exactly"

    def test_reverse_clears_vendor_and_day_redeemed_total(self, api):
        """PRD §3.5: "The reversal moves the token `REDEEMED → ISSUED`, clears
        `redeemed_vendor_id`, lowers the day's `redeemed_value_cents` by the
        face value, recomputes the variance, and increments both versions."

        Design: Difficulty/compensating_invariant/redeem_reverse_conserves_issued_unit_count
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]

        redeem_serials(vend_id, [t0["serial_number"]])
        mid = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert mid["redeemed_value_cents"] == 100

        reversed_token = validate_success(
            api.reverse_redemption(t0["id"], make_vendor_headers(vend_id)))
        assert reversed_token["redeemed_vendor_id"] is None, "reversal clears the vendor reference"
        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["redeemed_value_cents"] == 0, "day ledger returns to zero with no residual"
        assert day["variance_cents"] == 600

    def test_reverse_redemption_by_other_vendor_forbidden(self, api):
        """PRD §3.5: "A vendor may undo its own redemption as a same-day
        correction: the token must be `REDEEMED`, the acting vendor must be the
        vendor recorded in `redeemed_vendor_id` — any other vendor is refused
        with `ERR_FORBIDDEN` — the token's `submission_id` must be empty, since
        a token already attached to a claim cannot be reversed and the attempt
        is rejected with `ERR_TOKEN_ALREADY_SUBMITTED`, and the issuing market
        day must still be `OPEN` (`ERR_MARKET_DAY_NOT_OPEN`)."

        Design: Corner/state_machines/c_sm_reverse_redemption_by_other_vendor_forbidden
        """
        sc = setup_booth_scenario()
        vendor_b = create_active_vendor(sc["market"]["id"], legal_name="VB", stall_number="S2")
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        t0 = tokens[0]
        redeem_serials(sc["vendor"]["id"], [200001])

        resp = api.reverse_redemption(t0["id"], make_vendor_headers(vendor_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        token = get_success_data(api.get_token(t0["id"], ADMIN))
        assert token["status"] == "REDEEMED"
        assert token["redeemed_vendor_id"] == sc["vendor"]["id"]

    def test_reverse_redemption_after_attach_rejected(self, api):
        """PRD §3.5: "A vendor may undo its own redemption as a same-day
        correction: the token must be `REDEEMED`, the acting vendor must be the
        vendor recorded in `redeemed_vendor_id` — any other vendor is refused
        with `ERR_FORBIDDEN` — the token's `submission_id` must be empty, since
        a token already attached to a claim cannot be reversed and the attempt
        is rejected with `ERR_TOKEN_ALREADY_SUBMITTED`, and the issuing market
        day must still be `OPEN` (`ERR_MARKET_DAY_NOT_OPEN`)."

        Design: Corner/state_machines/c_sm_reverse_redemption_after_attach_rejected
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [200001])
        create_submission(vend_id, sc["market_day"]["id"], [t0["id"]])

        resp = api.reverse_redemption(t0["id"], make_vendor_headers(vend_id))
        validate_error(resp, ApiErrorId.ERR_TOKEN_ALREADY_SUBMITTED)

        token = get_success_data(api.get_token(t0["id"], ADMIN))
        assert token["status"] == "REDEEMED"
        assert token["submission_id"] is not None, "token stays attached"
