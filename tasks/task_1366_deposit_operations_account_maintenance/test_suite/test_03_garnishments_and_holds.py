"""Garnishment registration, exempt-funds analysis variants, service-window
conflicts, resolution branches, hold conservation, and the validation
priority pairs that surface a single deterministic error."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    MANAGER_2,
    NON_EXISTENT_UUID,
    OFFICER,
    OFFICER_1,
    ApiErrorId,
    api_client,
    assert_account_invariants,
    assert_garnishment_order,
    get_account,
    make_ops_manager_headers,
    open_account,
    post_federal_benefit,
    register_garnishment,
    resolve_garnishment,
    resolve_payload,
    set_clock,
    transaction_payload,
    validate_error,
    validate_success,
)


class TestExemptFundsDualVariant:
    """Identical balance and benefit history; the exemption_method selects
    the analysis variant and changes the protected cents."""

    def _setup_pair(self):
        acct_a = open_account(opening_deposit_cents=200000,
                              primary_owner_name="Ann A", owner_tax_id="T1")
        acct_b = open_account(opening_deposit_cents=200000,
                              primary_owner_name="Bob B", owner_tax_id="T2")
        set_clock("2026-08-10T00:00:00Z")
        for acct in (acct_a, acct_b):
            post_federal_benefit(acct["id"], 40000, "2026-08-03")
            post_federal_benefit(acct["id"], 40000, "2026-08-10")
        return acct_a, acct_b

    def test_exempt_funds_federal_lookback_variant(self):
        """PRD section 3.5: "The lookback window is the closed sixty-day
        interval ending on the served date — from sixty days before
        `served_date` through `served_date` inclusive — and the benefit
        total is the sum of `amount_cents` over the account's
        `FEDERAL_BENEFIT_DEPOSIT` transactions whose `posted_date` falls
        inside that window; every other transaction type is excluded."
        PRD section 3.5: "Under `FEDERAL_LOOKBACK`, `exempt_amount_cents` is
        the lesser of the account's ledger balance and the benefit total,
        with no floor."
        PRD section 3.5: "The hold is placed at receipt: `held_amount_cents`
        is the lesser of the claimed amount and the account's
        `available_balance_cents` at that moment".

        Design: Difficulty/dual_variant_calc/garnishment_exempt_federal_vs_state_floor
        """
        acct_a, _ = self._setup_pair()
        order = register_garnishment(acct_a["id"], 150000, "2026-08-10",
                                     exemption_method="FEDERAL_LOOKBACK")
        assert_garnishment_order(order)
        # held = min(claim 150000, available 280000); benefit total 80000
        assert order["held_amount_cents"] == 150000
        assert order["exempt_amount_cents"] == 80000
        assert order["collectible_cents"] == 70000

    def test_exempt_funds_state_minimum_floor_variant(self):
        """PRD section 3.5: "Under `STATE_MINIMUM`, `exempt_amount_cents` is
        the lesser of the ledger balance and the greater of a statutory
        floor of 100000 cents (one thousand dollars) and the benefit total —
        the floor protects a full thousand dollars even when benefit
        deposits are smaller. `collectible_cents` is then the held amount
        minus the exempt amount, never below zero."

        Design: Difficulty/dual_variant_calc/garnishment_exempt_federal_vs_state_floor
        """
        acct_a, acct_b = self._setup_pair()
        order_a = register_garnishment(acct_a["id"], 150000, "2026-08-10",
                                       exemption_method="FEDERAL_LOOKBACK")
        order_b = register_garnishment(acct_b["id"], 150000, "2026-08-10",
                                       exemption_method="STATE_MINIMUM")
        # State floor 100000 exceeds the benefit total 80000.
        assert order_b["held_amount_cents"] == 150000
        assert order_b["exempt_amount_cents"] == 100000
        assert order_b["collectible_cents"] == 50000
        assert order_a["exempt_amount_cents"] != order_b["exempt_amount_cents"]


class TestExemptFundsNestedClauses:
    """Each nested clause of the analysis decides once: the claim binds the
    hold, the benefit total binds the exemption, and max clamps collectible
    to zero."""

    def test_exempt_funds_all_clauses_bind(self):
        """PRD section 3.5: "The hold is placed at receipt:
        `held_amount_cents` is the lesser of the claimed amount and the
        account's `available_balance_cents` at that moment".
        PRD section 3.5: "Under `FEDERAL_LOOKBACK`, `exempt_amount_cents` is
        the lesser of the account's ledger balance and the benefit total,
        with no floor."
        PRD section 3.5: "`collectible_cents` is then the held amount minus
        the exempt amount, never below zero."

        Design: Difficulty/combinatorial_formula/exempt_funds_nested_min_max_all_clauses_bind
        """
        # Balance at receipt: 20000 opening + 60000 benefit = 80000.
        acct = open_account(opening_deposit_cents=20000,
                            primary_owner_name="Ned N", owner_tax_id="T5")
        set_clock("2026-08-10T00:00:00Z")
        post_federal_benefit(acct["id"], 60000, "2026-08-05")

        order = register_garnishment(acct["id"], 50000, "2026-08-10",
                                     exemption_method="FEDERAL_LOOKBACK",
                                     order_type="TAX_LEVY",
                                     creditor_name="RevAuth")
        assert order["held_amount_cents"] == 50000    # claim binds
        assert order["exempt_amount_cents"] == 60000  # benefit total binds
        assert order["collectible_cents"] == 0        # max clamps at zero

    def test_exempt_funds_hold_reduces_available_balance(self):
        """PRD section 2.7: "An account's `total_held_cents` is the sum of
        `held_amount_cents` over exactly its garnishment orders in
        `FUNDS_HELD` status — orders in `REMITTED` or `RELEASED` contribute
        nothing — and its `available_balance_cents` is `balance_cents`
        minus `total_held_cents`."

        Design: Difficulty/combinatorial_formula/exempt_funds_nested_min_max_all_clauses_bind
        """
        acct = open_account(opening_deposit_cents=20000,
                            primary_owner_name="Ned N", owner_tax_id="T5")
        set_clock("2026-08-10T00:00:00Z")
        post_federal_benefit(acct["id"], 60000, "2026-08-05")
        register_garnishment(acct["id"], 50000, "2026-08-10",
                             exemption_method="FEDERAL_LOOKBACK",
                             order_type="TAX_LEVY", creditor_name="RevAuth")

        acct_after = get_account(acct["id"])
        assert acct_after["balance_cents"] == 80000
        assert acct_after["total_held_cents"] == 50000
        assert acct_after["available_balance_cents"] == 30000
        assert acct_after["restriction_status"] == "LEGAL_HOLD"
        assert_account_invariants(acct_after)


class TestGarnishmentInitialState:

    def test_garnishment_initial_state_funds_held(self):
        """PRD section 3.5: "Registration acts atomically. The hold is
        placed at receipt: `held_amount_cents` is the lesser of the claimed
        amount and the account's `available_balance_cents` at that moment,
        the receiving officer is recorded in `received_by_user_id`, and the
        order enters `FUNDS_HELD` while the account's restriction moves from
        `NONE` to `LEGAL_HOLD` — the account totals recompute and its
        `version` increments inside the same mutation."

        Design: Corner/state_machines/garnishment_initial_state_funds_held
        """
        acct = open_account(opening_deposit_cents=60000,
                            primary_owner_name="Init I", owner_tax_id="C11")
        order = register_garnishment(acct["id"], 20000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK",
                                     order_type="CHILD_SUPPORT",
                                     creditor_name="CSEA")
        assert_garnishment_order(order)
        assert order["status"] == "FUNDS_HELD"
        assert order["held_amount_cents"] == 20000

        acct_after = get_account(acct["id"])
        assert acct_after["restriction_status"] == "LEGAL_HOLD"
        assert acct_after["total_held_cents"] == 20000
        assert acct_after["version"] == acct["version"] + 1


class TestAvailableBalance:

    def test_available_balance_net_of_holds(self, auditor_headers):
        """PRD section 2.7: "An account's `total_held_cents` is the sum of
        `held_amount_cents` over exactly its garnishment orders in
        `FUNDS_HELD` status — orders in `REMITTED` or `RELEASED` contribute
        nothing — and its `available_balance_cents` is `balance_cents`
        minus `total_held_cents`. Both derived figures are recomputed
        whenever a garnishment order is registered or resolved and whenever
        any transaction posts."

        Design: Corner/calculations/available_balance_net_of_holds
        """
        acct = open_account(opening_deposit_cents=90000,
                            primary_owner_name="Avl A", owner_tax_id="C16")
        register_garnishment(acct["id"], 35000, "2026-08-01",
                             exemption_method="FEDERAL_LOOKBACK")

        data = validate_success(
            api_client.get_account(acct["id"], auditor_headers),
            expected_status=200,
        )
        assert data["balance_cents"] == 90000
        assert data["total_held_cents"] == 35000
        assert data["available_balance_cents"] == 55000
        assert_account_invariants(data)


class TestRemitDeadlineBoundary:

    def test_remit_on_answer_deadline_rejected(self):
        """PRD section 3.5: "The server computes the `answer_deadline_date`
        as twenty calendar days after the served date".
        PRD section 3.5: "Remitting — a `resolution` of `REMITTED` —
        additionally requires the answer period to have elapsed: the logical
        clock date must be strictly after `answer_deadline_date`, failing
        with `ERR_ANSWER_PERIOD_NOT_ELAPSED` otherwise."

        Design: Difficulty/boundary_precision_check/garnishment_remit_deadline_strictly_after
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Dead D", owner_tax_id="T15")
        order = register_garnishment(acct["id"], 50000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        assert order["answer_deadline_date"] == "2026-08-21"

        # Remit ON the deadline date: the strict inequality is not met.
        set_clock("2026-08-21T00:00:00Z")
        resp = api_client.resolve_garnishment(
            order["id"], resolve_payload("REMITTED"), MANAGER_2)
        validate_error(resp, ApiErrorId.ERR_ANSWER_PERIOD_NOT_ELAPSED)

    def test_remit_day_after_deadline_succeeds(self):
        """PRD section 3.5: "Remittance posts a `LEGAL_REMITTANCE` debit for
        the remitted amount, records it in `remitted_amount_cents`, and
        returns the rest of the hold, recording `released_amount_cents` as
        the held amount minus the remitted amount."
        PRD section 3.5: "Either branch records the resolver in
        `resolved_by_user_id`, subtracts the hold from `total_held_cents`,
        recomputes `available_balance_cents`, returns the account's
        restriction to `NONE` when no order remains in `FUNDS_HELD`, and
        increments the account's `version`."

        Design: Difficulty/boundary_precision_check/garnishment_remit_deadline_strictly_after
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Dead D", owner_tax_id="T15")
        order = register_garnishment(acct["id"], 50000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        assert order["collectible_cents"] == 50000

        set_clock("2026-08-22T00:00:00Z")
        resolved = resolve_garnishment(order["id"], "REMITTED")
        assert resolved["status"] == "REMITTED"
        # Default remit amount is collectible_cents.
        assert resolved["remitted_amount_cents"] == 50000
        assert resolved["released_amount_cents"] == 0

        acct_after = get_account(acct["id"])
        assert acct_after["balance_cents"] == 50000
        assert acct_after["total_held_cents"] == 0
        assert acct_after["restriction_status"] == "NONE"


class TestServiceWindowClosedInterval:

    def test_garnishment_served_on_prior_deadline_conflicts(self):
        """PRD section 3.5: "The server computes the `answer_deadline_date`
        as twenty calendar days after the served date, and the order's
        closed service window — from `served_date` through
        `answer_deadline_date`, both days inclusive — must not overlap the
        service window of any other order still holding funds on the
        account; a conflict is rejected with
        `ERR_LEGAL_ORDER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/garnishment_service_window_closed_interval
        """
        acct = open_account(opening_deposit_cents=500000,
                            primary_owner_name="Garn G", owner_tax_id="T19")
        order1 = register_garnishment(acct["id"], 100000, "2026-08-01",
                                      exemption_method="FEDERAL_LOOKBACK")
        assert order1["answer_deadline_date"] == "2026-08-21"
        set_clock("2026-08-22T00:00:00Z")

        # Closed interval: serving exactly ON the prior deadline collides.
        resp = api_client.register_garnishment(
            acct["id"],
            {"order_type": "TAX_LEVY", "creditor_name": "RevAuth",
             "amount_cents": 150000, "served_date": "2026-08-21",
             "exemption_method": "STATE_MINIMUM"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_LEGAL_ORDER_WINDOW_CONFLICT)

    def test_garnishment_served_after_deadline_accepted(self):
        """PRD section 3.5: "the order's closed service window — from
        `served_date` through `answer_deadline_date`, both days inclusive —
        must not overlap the service window of any other order still holding
        funds on the account; a conflict is rejected with
        `ERR_LEGAL_ORDER_WINDOW_CONFLICT`."
        PRD section 2.7: "An account's `total_held_cents` is the sum of
        `held_amount_cents` over exactly its garnishment orders in
        `FUNDS_HELD` status".

        Design: Difficulty/resource_temporal_overlap/garnishment_service_window_closed_interval
        """
        acct = open_account(opening_deposit_cents=500000,
                            primary_owner_name="Garn G", owner_tax_id="T19")
        register_garnishment(acct["id"], 100000, "2026-08-01",
                             exemption_method="FEDERAL_LOOKBACK")
        set_clock("2026-08-22T00:00:00Z")

        # Served strictly after the prior deadline: no overlap.
        order2 = register_garnishment(acct["id"], 150000, "2026-08-22",
                                      exemption_method="STATE_MINIMUM",
                                      order_type="TAX_LEVY",
                                      creditor_name="RevAuth")
        assert order2["status"] == "FUNDS_HELD"
        assert order2["held_amount_cents"] == 150000

        acct_after = get_account(acct["id"])
        assert acct_after["total_held_cents"] == 250000
        assert acct_after["available_balance_cents"] == 250000
        assert_account_invariants(acct_after)


class TestHoldConservationInvariant:

    def _setup_held_order(self):
        # Balance at receipt: 70000 opening + 30000 benefit = 100000.
        acct = open_account(opening_deposit_cents=70000,
                            primary_owner_name="Inv I", owner_tax_id="T20")
        set_clock("2026-08-10T00:00:00Z")
        post_federal_benefit(acct["id"], 30000, "2026-08-05")
        order = register_garnishment(acct["id"], 50000, "2026-08-10",
                                     exemption_method="FEDERAL_LOOKBACK")
        return acct, order

    def test_garnishment_remit_conserves_held_funds(self):
        """PRD section 3.5: "Remittance posts a `LEGAL_REMITTANCE` debit for
        the remitted amount, records it in `remitted_amount_cents`, and
        returns the rest of the hold, recording `released_amount_cents` as
        the held amount minus the remitted amount."

        Design: Difficulty/compensating_invariant/garnishment_hold_conservation_invariant
        """
        _acct, order = self._setup_held_order()
        assert order["held_amount_cents"] == 50000
        assert order["exempt_amount_cents"] == 30000
        assert order["collectible_cents"] == 20000

        set_clock("2026-09-01T00:00:00Z")
        resolved = resolve_garnishment(order["id"], "REMITTED")
        assert resolved["remitted_amount_cents"] == 20000
        assert resolved["released_amount_cents"] == 30000
        # The hold placed at receipt is fully accounted at resolve.
        assert order["held_amount_cents"] == \
            resolved["remitted_amount_cents"] + resolved["released_amount_cents"]

    def test_garnishment_resolve_reconciles_account_totals(self):
        """PRD section 3.5: "Either branch records the resolver in
        `resolved_by_user_id`, subtracts the hold from `total_held_cents`,
        recomputes `available_balance_cents`, returns the account's
        restriction to `NONE` when no order remains in `FUNDS_HELD`, and
        increments the account's `version`."
        PRD section 2.7: "Both derived figures are recomputed whenever a
        garnishment order is registered or resolved and whenever any
        transaction posts."

        Design: Difficulty/compensating_invariant/garnishment_hold_conservation_invariant
        """
        acct, order = self._setup_held_order()
        set_clock("2026-09-01T00:00:00Z")
        resolve_garnishment(order["id"], "REMITTED")

        acct_after = get_account(acct["id"])
        # 100000 at hold time minus exactly the 20000 remittance.
        assert acct_after["balance_cents"] == 80000
        assert acct_after["total_held_cents"] == 0
        assert acct_after["available_balance_cents"] == 80000
        assert acct_after["restriction_status"] == "NONE"
        assert_account_invariants(acct_after)


class TestValidationPriorityPairs:

    def test_resolve_terminal_order_reports_invalid_state_over_segregation(self):
        """PRD section 2.10: "When several checks could reject the same
        request, the server evaluates them in a fixed order so the surfaced
        error is deterministic. The tiers, from first to last:"
        PRD section 2.10: "5. **State and version** — the target resource's
        state permits the transition (`ERR_INVALID_STATE`), and where
        optimistic concurrency applies the presented
        `expected_account_version` matches the account's current `version`
        (`ERR_STALE_VERSION`)."
        PRD section 2.10: "6. **Compliance gates** — restriction posture
        (`ERR_ACCOUNT_RESTRICTED`), segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`), closure blocking
        (`ERR_CLOSURE_BLOCKED`), and required-document completeness
        (`ERR_DOCUMENTS_INCOMPLETE`)."

        Design: Difficulty/priority_pair_validation_conflict/resolve_terminal_order_state_beats_segregation
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Prio P", owner_tax_id="T12")
        order = register_garnishment(acct["id"], 50000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        set_clock("2026-08-22T00:00:00Z")

        # The receiving officer cannot resolve their own order.
        resp_sod = api_client.resolve_garnishment(
            order["id"], resolve_payload("REMITTED"),
            make_ops_manager_headers("u-off-1"))
        validate_error(resp_sod, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        resolved = resolve_garnishment(order["id"], "REMITTED")
        assert resolved["status"] == "REMITTED"

        # Second resolve by the receiver violates BOTH terminal state (tier
        # 5) and segregation (tier 6); the state error must surface.
        resp_final = api_client.resolve_garnishment(
            order["id"], resolve_payload("RELEASED"),
            make_ops_manager_headers("u-off-1"))
        validate_error(resp_final, ApiErrorId.ERR_INVALID_STATE)

    def test_second_resolve_after_remittance_rejected_invalid_state(self):
        """PRD section 3.5: "The order must still be `FUNDS_HELD`
        (`ERR_INVALID_STATE` otherwise), and the resolver must not be the
        officer recorded in `received_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES` otherwise)."
        PRD section 3.5: "`REMITTED` and `RELEASED` are both terminal".

        Design: Difficulty/priority_pair_validation_conflict/resolve_terminal_order_state_beats_segregation
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Prio P", owner_tax_id="T12")
        order = register_garnishment(acct["id"], 50000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        set_clock("2026-08-22T00:00:00Z")
        resolved = resolve_garnishment(order["id"], "REMITTED")
        assert resolved["status"] == "REMITTED"

        # A different manager (segregation satisfied) still hits the
        # terminal-state wall.
        resp = api_client.resolve_garnishment(
            order["id"], resolve_payload("RELEASED"),
            make_ops_manager_headers("u-mgr-3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdrawal_restricted_and_unaffordable_reports_restricted(self):
        """PRD section 3.1: "A `WITHDRAWAL`, by contrast, is rejected with
        `ERR_ACCOUNT_RESTRICTED` whenever the account's restriction is
        anything other than `NONE`, and with
        `ERR_INSUFFICIENT_AVAILABLE_FUNDS` when its amount exceeds the
        account's `available_balance_cents` — and when both failures
        coincide, the restriction gate reports first."

        Design: Difficulty/priority_pair_validation_conflict/withdrawal_legal_hold_beats_insufficient_funds
        """
        acct = open_account(opening_deposit_cents=1000,
                            primary_owner_name="Hold H", owner_tax_id="T13")
        order = register_garnishment(acct["id"], 5000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK",
                                     order_type="TAX_LEVY",
                                     creditor_name="RevAuth")
        assert order["held_amount_cents"] == 1000
        acct_held = get_account(acct["id"])
        assert acct_held["available_balance_cents"] == 0
        assert acct_held["restriction_status"] == "LEGAL_HOLD"

        # 500 exceeds available 0 AND the account is restricted.
        resp = api_client.post_transaction(
            acct["id"],
            transaction_payload("WITHDRAWAL", 500, customer_initiated=True),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)

    def test_withdrawal_under_legal_hold_blocked_even_when_balance_covers(self):
        """PRD section 3.1: "A `WITHDRAWAL`, by contrast, is rejected with
        `ERR_ACCOUNT_RESTRICTED` whenever the account's restriction is
        anything other than `NONE`".

        Design: Difficulty/priority_pair_validation_conflict/withdrawal_legal_hold_beats_insufficient_funds
        """
        acct = open_account(opening_deposit_cents=1000,
                            primary_owner_name="Hold H", owner_tax_id="T13")
        register_garnishment(acct["id"], 5000, "2026-08-01",
                             exemption_method="FEDERAL_LOOKBACK",
                             order_type="TAX_LEVY", creditor_name="RevAuth")

        # The ledger balance (1000) covers a 500 withdrawal, but the legal
        # hold posture alone blocks it.
        resp = api_client.post_transaction(
            acct["id"],
            transaction_payload("WITHDRAWAL", 500, customer_initiated=True),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)


class TestResolveValidations:

    def test_resolve_nonexistent_order_returns_not_found(self,
                                                         ops_manager_headers):
        """PRD section 2.9: "Standalone action paths address their target
        by a bare identifier — `signerId`, `documentId`, `requestId`,
        `caseId`, `orderId`, or `conversionId` — and the same existence rule
        applies to each."
        PRD section 2.9: "The first identifier that fails to resolve to an
        existing resource rejects the request with `ERR_NOT_FOUND`
        (HTTP 404) before any later validation runs".

        Design: Corner/validations/resolve_nonexistent_order_returns_not_found
        """
        resp = api_client.resolve_garnishment(
            NON_EXISTENT_UUID, resolve_payload("RELEASED"),
            ops_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_remit_override_exceeds_collectible_rejected(self):
        """PRD section 3.5: "The remitted amount defaults to
        `collectible_cents`; an explicit `remit_amount_cents` override is
        accepted only up to `collectible_cents`
        (`ERR_AMOUNT_EXCEEDS_COLLECTIBLE` beyond it)."

        Design: Corner/validations/remit_override_exceeds_collectible_rejected
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Ovr O", owner_tax_id="C20")
        set_clock("2026-08-10T00:00:00Z")
        post_federal_benefit(acct["id"], 30000, "2026-08-05")
        order = register_garnishment(acct["id"], 50000, "2026-08-10",
                                     exemption_method="FEDERAL_LOOKBACK")
        assert order["collectible_cents"] == 20000

        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.resolve_garnishment(
            order["id"],
            resolve_payload("REMITTED", remit_amount_cents=30000),
            MANAGER_2,
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_COLLECTIBLE)

    def test_withdrawal_exceeds_available_without_hold(self):
        """PRD section 3.1: "A `WITHDRAWAL`, by contrast, is rejected with
        `ERR_ACCOUNT_RESTRICTED` whenever the account's restriction is
        anything other than `NONE`, and with
        `ERR_INSUFFICIENT_AVAILABLE_FUNDS` when its amount exceeds the
        account's `available_balance_cents` — and when both failures
        coincide, the restriction gate reports first."

        Design: Corner/validations/withdrawal_exceeds_available_without_hold
        """
        acct = open_account(opening_deposit_cents=1000,
                            primary_owner_name="Ins I", owner_tax_id="C21")
        resp = api_client.post_transaction(
            acct["id"],
            transaction_payload("WITHDRAWAL", 1500, customer_initiated=True),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_FUNDS)
