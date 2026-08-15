"""Transitive cascades, compensating invariants, derived fields, parallel card
dimensions, and the BIN effective window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_auth,
    create_open_account,
    create_program_with_bin_and_publish,
    get_pending_activation_token_value,
    get_success_data,
    issue_card_for_account,
    set_card_pin,
    set_clock,
    setup_active_card_scenario,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PA = TEST_USERS["platform_admin_headers"]
CH = TEST_USERS["cardholder_ops_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestCardCompromiseCascade:
    def _setup_four_active_cards(self, code: str, bin_prefix: str):
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish(code, bin_prefix=bin_prefix)
        acct = create_open_account(prog["id"], f"{code}-A7", daily_spend_cap_cents=10000)
        cards = [
            issue_card_for_account(acct["id"]) for _ in range(4)
        ]
        for i, card in enumerate(cards, start=1):
            set_card_pin(card["id"], f"000{i}")
            token = get_pending_activation_token_value(card["id"])
            from test_helpers import activate_card
            activate_card(card["id"], token)
        return prog, acct, cards

    def test_card_compromise_cascade_depth_3(self, api):
        """PRD §3.4: "if this is the third or later card under the same account
        to flip `ACTIVE` → `COMPROMISED` within a rolling seven-day window
        measured from the clock at the transition, the account's `risk_tier` is
        set to `RESTRICTED` and the account itself is suspended `OPEN` →
        `SUSPENDED`; that suspension then cascades as usual, flipping every
        other `ACTIVE` card on the account to `SUSPENDED` with PIN state
        preserved."

        Design: Difficulty/transitive_cascade/card_compromise_cascade_depth_3
        """
        _prog, acct, cards = self._setup_four_active_cards("P-VISA-7", "466666")
        c1, c2, c3, c4 = cards
        # First two compromises do not breach the threshold.
        get_success_data(api.mark_card_compromised(c1["id"], CO))
        get_success_data(api.mark_card_compromised(c2["id"], CO))
        # The third compromise crosses the threshold and fires the cascade.
        get_success_data(api.mark_card_compromised(c3["id"], CO))
        acct_after = get_success_data(api.get_account(acct["id"], PM))
        assert acct_after["risk_tier"] == "RESTRICTED", (
            f"Third compromise in window must set risk_tier RESTRICTED, got "
            f"{acct_after['risk_tier']}"
        )
        assert acct_after["lifecycle_status"] == "SUSPENDED", (
            f"Account must suspend on third compromise, got "
            f"{acct_after['lifecycle_status']}"
        )
        c4_after = get_success_data(api.get_card(c4["id"], PM))
        assert c4_after["lifecycle_status"] == "SUSPENDED", (
            f"Sibling ACTIVE card must be cascaded to SUSPENDED, got "
            f"{c4_after['lifecycle_status']}"
        )

    def test_first_two_compromises_do_not_suspend_account(self, api):
        """PRD §3.4: "if this is the third or later card under the same account
        to flip `ACTIVE` → `COMPROMISED` within a rolling seven-day window
        measured from the clock at the transition, the account's `risk_tier` is
        set to `RESTRICTED` and the account itself is suspended `OPEN` →
        `SUSPENDED`".

        Two compromises remain below the threshold: the account stays OPEN.

        Design: Difficulty/transitive_cascade/card_compromise_cascade_depth_3
        """
        _prog, acct, cards = self._setup_four_active_cards("P-VISA-7B", "466667")
        c1, c2, _c3, c4 = cards
        get_success_data(api.mark_card_compromised(c1["id"], CO))
        get_success_data(api.mark_card_compromised(c2["id"], CO))
        acct_after = get_success_data(api.get_account(acct["id"], PM))
        assert acct_after["lifecycle_status"] == "OPEN", (
            f"Below the third-card threshold the account must stay OPEN, got "
            f"{acct_after['lifecycle_status']}"
        )
        c4_after = get_success_data(api.get_card(c4["id"], PM))
        assert c4_after["lifecycle_status"] == "ACTIVE"


class TestCompensatingInvariants:
    def test_card_cancel_restores_pan_inventory(self, api):
        """PRD §3.4: "Issuing consumes one PAN: `pans_allocated` increases by
        one." and "Cancelling from any of `ISSUED`, `ACTIVE`, or `SUSPENDED`
        releases the PAN (`pans_allocated` decreases by one)".

        Design: Difficulty/compensating_invariant/card_cancel_restores_pan_inventory
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, bin_range = create_program_with_bin_and_publish("P-VISA-17", bin_prefix="477700")
        acct = create_open_account(prog["id"], "A-17", daily_spend_cap_cents=100000)
        card = issue_card_for_account(acct["id"], bin_range_id=bin_range["id"])
        after_issue = get_success_data(api.get_bin_range(bin_range["id"], PM))
        assert after_issue["pans_allocated"] == 1, (
            f"Issuance consumes one PAN; got {after_issue['pans_allocated']}"
        )
        get_success_data(api.cancel_card(card["id"], PM))
        after_cancel = get_success_data(api.get_bin_range(bin_range["id"], PM))
        assert after_cancel["pans_allocated"] == 0, (
            f"Cancel releases the PAN; pans_allocated must return to 0, got "
            f"{after_cancel['pans_allocated']}"
        )

    def test_card_issue_then_cancel_twice_keeps_inventory_balanced(self, api):
        """PRD §3.4: "Issuing consumes one PAN: `pans_allocated` increases by
        one." and "Cancelling from any of `ISSUED`, `ACTIVE`, or `SUSPENDED`
        releases the PAN (`pans_allocated` decreases by one)".

        Two issue/cancel cycles leave the range at its original allocation.

        Design: Difficulty/compensating_invariant/card_cancel_restores_pan_inventory
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, bin_range = create_program_with_bin_and_publish("P-VISA-17B", bin_prefix="477701")
        acct = create_open_account(prog["id"], "A-17B", daily_spend_cap_cents=100000)
        for _ in range(2):
            card = issue_card_for_account(acct["id"], bin_range_id=bin_range["id"])
            mid = get_success_data(api.get_bin_range(bin_range["id"], PM))
            assert mid["pans_allocated"] >= 1
            get_success_data(api.cancel_card(card["id"], PM))
        final = get_success_data(api.get_bin_range(bin_range["id"], PM))
        assert final["pans_allocated"] == 0, (
            f"Balanced issue/cancel cycles must conserve pans_allocated at 0, "
            f"got {final['pans_allocated']}"
        )

    def test_account_fund_then_settle_conserves_cash(self, api):
        """PRD §3.5: "On `APPROVED`, the amount is subtracted from
        `available_balance_cents`; on any decline the balance is untouched."
        PRD §3.6: "When the settled amount falls short of the authorized
        amount, the remainder is released back to the account's
        `available_balance_cents`."

        A full settlement releases nothing — the balance is conserved at
        funded-minus-authorized with no double-debit.

        Design: Difficulty/compensating_invariant/account_fund_then_settle_conserves_cash
        """
        sc = setup_active_card_scenario(
            "P-VISA-18", account_daily_cap_cents=100000, fund_cents=50000,
            bin_prefix="488800",
        )
        acct_id = sc["account"]["id"]
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        after_auth = get_success_data(api.get_account(acct_id, PM))
        assert after_auth["available_balance_cents"] == 40000, (
            f"50000 - 10000 = 40000 after approval; got "
            f"{after_auth['available_balance_cents']}"
        )
        settle = api.settle_authorization(auth["id"], 10000, FC)
        validate_success(settle, expected_status=201)
        after_settle = get_success_data(api.get_account(acct_id, PM))
        assert after_settle["available_balance_cents"] == 40000, (
            f"Full settlement must not double-debit; balance stays 40000, got "
            f"{after_settle['available_balance_cents']}"
        )

    def test_approved_auth_debits_exactly_amount(self, api):
        """PRD §3.5: "On `APPROVED`, the amount is subtracted from
        `available_balance_cents`; on any decline the balance is untouched."

        Design: Difficulty/compensating_invariant/account_fund_then_settle_conserves_cash
        """
        sc = setup_active_card_scenario(
            "P-VISA-18B", account_daily_cap_cents=100000, fund_cents=50000,
            bin_prefix="488801",
        )
        acct_id = sc["account"]["id"]
        create_approved_auth(sc["card"]["id"], amount_cents=7000, mcc="5411")
        create_approved_auth(sc["card"]["id"], amount_cents=3000, mcc="5411")
        acct = get_success_data(api.get_account(acct_id, PM))
        assert acct["available_balance_cents"] == 40000, (
            f"50000 - 7000 - 3000 = 40000; got {acct['available_balance_cents']}"
        )


class TestDerivedFieldsAndCascades:
    def test_derived_field_open_card_count(self, api):
        """PRD §3.4: "A successful activation consumes the token — it flips to
        `CONSUMED` with `consumed_at` stamped — and increments the program's
        `open_card_count`." and "cancelling an `ACTIVE` card additionally
        decrements `open_card_count`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_open_card_count
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-OC")
        acct = create_open_account(prog["id"], "A-OC", daily_spend_cap_cents=10000)
        card = issue_card_for_account(acct["id"])
        set_card_pin(card["id"], "1234")
        token = get_pending_activation_token_value(card["id"])
        from test_helpers import activate_card
        activate_card(card["id"], token)
        after_activate = get_success_data(api.get_program(prog["id"], PM))
        assert after_activate["open_card_count"] == 1, (
            f"Activation increments open_card_count to 1; got "
            f"{after_activate['open_card_count']}"
        )
        get_success_data(api.cancel_card(card["id"], PM))
        after_cancel = get_success_data(api.get_program(prog["id"], PM))
        assert after_cancel["open_card_count"] == 0, (
            f"Cancelling the ACTIVE card decrements open_card_count to 0; got "
            f"{after_cancel['open_card_count']}"
        )

    def test_cascading_account_suspend_suspends_cards(self, api):
        """PRD §3.4: "Suspending an account (`OPEN` → `SUSPENDED`) cascades:
        every card of the account that is `ACTIVE` flips to `SUSPENDED` with
        its `pin_status` preserved."

        Design: Corner/cross_cutting_complexity_layers/cascading_account_suspend_suspends_cards
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-CAS")
        acct = create_open_account(prog["id"], "A-CAS", daily_spend_cap_cents=10000)
        from test_helpers import activate_card
        cards = [issue_card_for_account(acct["id"]) for _ in range(2)]
        for i, card in enumerate(cards, start=1):
            set_card_pin(card["id"], f"111{i}")
            token = get_pending_activation_token_value(card["id"])
            activate_card(card["id"], token)
        get_success_data(api.suspend_account(acct["id"], PM))
        for card in cards:
            after = get_success_data(api.get_card(card["id"], PM))
            assert after["lifecycle_status"] == "SUSPENDED", (
                f"Account suspension must cascade ACTIVE cards to SUSPENDED; got "
                f"{after['lifecycle_status']}"
            )
            assert after["pin_status"] == "SET", (
                f"pin_status must be preserved through the cascade; got "
                f"{after['pin_status']}"
            )


class TestCardParallelDimensions:
    def test_card_parallel_dimensions_lifecycle_x_pin(self, api):
        """PRD §3.4: "The card's two dimensions evolve independently." and
        "Changing a PIN is a `SET` → `SET` self-loop that additionally requires
        `current_pin` to match the stored PIN, and it still increments the
        card's `version`".

        Setting, blocking, and resetting the PIN moves pin_status while
        lifecycle_status stays ISSUED-then-ACTIVE; card activation moves
        lifecycle_status without touching pin_status.

        Design: Difficulty/non_linear_state_machine/card_parallel_dimensions_lifecycle_x_pin
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-6", bin_prefix="455555")
        acct = create_open_account(prog["id"], "A-6", daily_spend_cap_cents=100000)
        card = issue_card_for_account(acct["id"])
        # PIN dimension moves while lifecycle is still ISSUED.
        set_card_pin(card["id"], "7777")
        mid = get_success_data(api.get_card(card["id"], CH))
        assert mid["lifecycle_status"] == "ISSUED"
        assert mid["pin_status"] == "SET"
        # Activation moves lifecycle without touching pin_status.
        from test_helpers import activate_card
        token = get_pending_activation_token_value(card["id"])
        activated = activate_card(card["id"], token)
        assert activated["lifecycle_status"] == "ACTIVE"
        assert activated["pin_status"] == "SET"
        # Block + reset + re-set the PIN while lifecycle stays ACTIVE.
        get_success_data(api.pin_block(card["id"], PA))
        blocked = get_success_data(api.get_card(card["id"], CH))
        assert blocked["pin_status"] == "BLOCKED"
        assert blocked["lifecycle_status"] == "ACTIVE"
        get_success_data(api.pin_reset_request(card["id"], CH))
        get_success_data(api.set_pin(card["id"], "8888", CH))
        final = get_success_data(api.get_card(card["id"], CH))
        assert final["pin_status"] == "SET", (
            f"PIN dimension returns to SET after reset; got {final['pin_status']}"
        )
        assert final["lifecycle_status"] == "ACTIVE", (
            f"Lifecycle must be unaffected by PIN transitions; got "
            f"{final['lifecycle_status']}"
        )

    def test_pin_change_self_loop_keeps_lifecycle(self, api):
        """PRD §3.4: "Changing a PIN is a `SET` → `SET` self-loop that
        additionally requires `current_pin` to match the stored PIN, and it
        still increments the card's `version`." and "The card's two dimensions
        evolve independently."

        Design: Difficulty/non_linear_state_machine/card_parallel_dimensions_lifecycle_x_pin
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-6B", bin_prefix="455556")
        acct = create_open_account(prog["id"], "A-6B", daily_spend_cap_cents=100000)
        card = issue_card_for_account(acct["id"])
        set_card_pin(card["id"], "7777")
        from test_helpers import activate_card
        token = get_pending_activation_token_value(card["id"])
        activated = activate_card(card["id"], token)
        # PIN change self-loop: SET → SET with current_pin matching.
        resp = api.set_pin(card["id"], "9999", CH, current_pin="7777")
        changed = validate_success(resp)
        assert changed["pin_status"] == "SET"
        assert changed["lifecycle_status"] == "ACTIVE"
        assert changed["version"] > activated["version"], (
            f"Self-loop PIN change must still increment version; "
            f"{activated['version']} -> {changed['version']}"
        )


class TestBinEffectiveWindow:
    def test_bin_range_effective_window_card_issuance(self, api):
        """PRD §3.4: "Issuance requires the chosen range to be inside its
        effective window — the clock must be at or after `effective_from` and
        strictly before `effective_until`, else `ERR_BIN_NOT_IN_WINDOW`".

        Design: Difficulty/resource_temporal_overlap/bin_range_effective_window_card_issuance
        """
        set_clock("2026-08-15T00:00:00Z")
        # A currently-active range lets the account open; the range under test
        # has not yet reached its effective_from.
        prog, _active_bin = create_program_with_bin_and_publish(
            "P-VISA-16", bin_prefix="466600",
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2030-12-31T23:59:59Z",
        )
        from test_helpers import create_bin_range
        future_bin = create_bin_range(
            prog["id"], bin_prefix="466601",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-12-01T00:00:00Z",
        )
        acct = create_open_account(prog["id"], "A-16", daily_spend_cap_cents=100000)
        # Issuing explicitly against the not-yet-effective range must be refused.
        resp = api.issue_card(
            acct["id"],
            {"expiry_month": 12, "expiry_year": 2030, "form_factor": "PHYSICAL",
             "bin_range_id": future_bin["id"]},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BIN_NOT_IN_WINDOW.value)

    def test_bin_range_issuance_succeeds_at_effective_from_boundary(self, api):
        """PRD §3.4: "Issuance requires the chosen range to be inside its
        effective window — the clock must be at or after `effective_from` and
        strictly before `effective_until`, else `ERR_BIN_NOT_IN_WINDOW`".

        At clock == effective_from the lower bound is inclusive, so issuance
        succeeds.

        Design: Difficulty/resource_temporal_overlap/bin_range_effective_window_card_issuance
        """
        from test_helpers import create_bin_range, create_program, publish_program
        set_clock("2026-08-15T00:00:00Z")
        # Create the program and the range while the range is still
        # PENDING_ACTIVATION (clock < effective_from). Publish must wait until
        # the range flips ACTIVE, which happens lazily once the clock reaches
        # effective_from.
        prog = create_program("P-VISA-16B")
        bin_range = create_bin_range(
            prog["id"], bin_prefix="466601",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-12-01T00:00:00Z",
        )
        # Advance the clock to exactly effective_from: the lazy transition
        # flips the range PENDING_ACTIVATION → ACTIVE on this call, so the
        # subsequent publish finds an ACTIVE range.
        set_clock("2026-09-01T00:00:00Z")
        publish_program(prog["id"])
        acct = create_open_account(prog["id"], "A-16B", daily_spend_cap_cents=100000)
        resp = api.issue_card(
            acct["id"],
            {"expiry_month": 12, "expiry_year": 2030, "form_factor": "PHYSICAL",
             "bin_range_id": bin_range["id"]},
            PM,
        )
        card = validate_success(resp, expected_status=201)
        assert card["lifecycle_status"] == "ISSUED"
        assert card["bin_range_id"] == bin_range["id"]
