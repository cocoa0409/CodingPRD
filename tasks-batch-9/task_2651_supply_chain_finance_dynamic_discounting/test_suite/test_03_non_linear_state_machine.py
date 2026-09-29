"""Depth tests for the ``non_linear_state_machine`` rule.

Three lifecycles in this contract are not simple chains. The discount offer is a
cycle whose loop counter advances on only one of its two edges and stops the
ladder at three rounds; the early payment carries three state axes that advance
on different triggers and stay independent; and supplier onboarding is a
fork-join that leaves ``VERIFYING`` only when both axes have completed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_COUNTER_ROUNDS_EXHAUSTED,
    ERR_INVALID_STATE,
    ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED,
    ERR_RECLASS_OVERRIDE_REASON_REQUIRED,
)
from test_helpers.assertions import (
    assert_cash_breakdown,
    assert_invoice_face_conserved,
    assert_payment_axes,
    assert_supplier_axes,
)
from test_helpers.test_users import PLATFORM_OPS_HEADERS, make_supplier_headers

THREE_LINE_ROW = [
    f.invoice_line(1, 33333, 875),
    f.invoice_line(2, 33333, 875),
    f.invoice_line(3, 33334, 875),
]
FACE_108751 = 108751


def _self_only_reserved_payment():
    """A RESERVED, buyer-self-funded payment on an invoice of face 108751 at 800
    basis points with a requested pay date 56 days before the net due date."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
            "reclass_days_threshold": 30,
            "reclass_apr_threshold_bps": 900,
        },
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=THREE_LINE_ROW,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.load_invoices(ctx)
    assert ctx.invoice["face_amount_cents"] == FACE_108751, (
        "the three-line row prices at 108751, got {}".format(
            ctx.invoice["face_amount_cents"]
        )
    )
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-10T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    ctx.offer_id = accepted["id"]
    ctx.payment = fx.reserve_payment(accepted["id"], accepted["version"], ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    return ctx


def test_offer_counter_rename_cycle_bounded_at_three_rounds():
    """The counter edge leaves ``counter_round`` alone and the rename edge advances
    it, so the ladder 700/800/810/900/910/1000/1010 completes three rounds and the
    fourth counter is refused while the offer stays NAMED and acceptable.

    PRD (§3.6): "Countering requires the offer to be `NAMED`, the session to be
    `LIVE` with the clock inside the window, the programme to be `OPEN`, the
    programme's `program_type` to be `SUPPLIER_NAMED` — a fixed-rate programme has
    nothing to negotiate — the countered rate to be strictly greater than the
    offer's current `offered_apr_bps` and at most the programme's
    `max_acceptable_apr_bps`, and the offer's `counter_round` to be strictly below
    three. A counter attempted once three rounds have been completed is rejected
    with `ERR_COUNTER_ROUNDS_EXHAUSTED`."
    PRD (§3.6): "It overwrites `offered_apr_bps` with the new rate, increments
    `counter_round` by one, clears `counter_apr_bps` back to null, and returns the
    offer `COUNTERED → NAMED`, incrementing its `version`."
    PRD (§3.6): "From `NAMED`, only a programme owner may accept — the buyer is
    taking the supplier's named rate — and the locked `accepted_apr_bps` is copied
    from the offer's `offered_apr_bps`."

    Design: Difficulty/non_linear_state_machine/offer_counter_rename_cycle_bounded_at_three_rounds
    """
    ctx = fx.build_named_offer(offered_apr_bps=700, face_cents=500_000)
    offer_v0 = ctx.offer["version"]
    assert ctx.offer["counter_round"] == 0, (
        "a freshly named offer has completed no rounds, got {}".format(
            ctx.offer["counter_round"]
        )
    )

    ladder = [(800, 810), (900, 910), (1000, 1010)]
    for round_no, (counter_apr, rename_apr) in enumerate(ladder, start=1):
        countered = validate_success(
            api_client.counter_offer(
                ctx.offer_id, f.counter_payload(counter_apr), ctx.admin
            )
        )
        assert countered["status"] == "COUNTERED", (
            "round {}: countering moves the offer to COUNTERED, got {}".format(
                round_no, countered["status"]
            )
        )
        assert countered["counter_apr_bps"] == counter_apr, (
            "round {}: the countered rate is stored, got {}".format(
                round_no, countered["counter_apr_bps"]
            )
        )
        assert countered["counter_round"] == round_no - 1, (
            "round {}: the counter edge does not advance counter_round, got {}".format(
                round_no, countered["counter_round"]
            )
        )

        renamed = validate_success(
            api_client.rename_offer(
                ctx.offer_id, f.rename_payload(rename_apr), ctx.supplier_headers
            )
        )
        assert renamed["status"] == "NAMED", (
            "round {}: re-naming returns the offer to NAMED, got {}".format(
                round_no, renamed["status"]
            )
        )
        assert renamed["counter_round"] == round_no, (
            "round {}: the rename edge advances counter_round, got {}".format(
                round_no, renamed["counter_round"]
            )
        )
        assert renamed["offered_apr_bps"] == rename_apr, (
            "round {}: the new rate overwrites offered_apr_bps, got {}".format(
                round_no, renamed["offered_apr_bps"]
            )
        )
        assert renamed["counter_apr_bps"] is None, (
            "round {}: re-naming clears counter_apr_bps to null, got {!r}".format(
                round_no, renamed["counter_apr_bps"]
            )
        )

    # The fourth counter is refused on the rounds budget alone: 1100 is strictly
    # above the current 1010 and at most the programme ceiling of 1200.
    exhausted = api_client.counter_offer(
        ctx.offer_id, f.counter_payload(1100), ctx.admin
    )
    validate_error(exhausted, ERR_COUNTER_ROUNDS_EXHAUSTED, 409)

    unchanged = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert unchanged["status"] == "NAMED", (
        "the refused counter leaves the offer in NAMED, got {}".format(
            unchanged["status"]
        )
    )
    assert unchanged["counter_round"] == 3, (
        "counter_round stays at the three completed rounds, got {}".format(
            unchanged["counter_round"]
        )
    )
    assert unchanged["offered_apr_bps"] == 1010, (
        "the last re-named rate stands, got {}".format(unchanged["offered_apr_bps"])
    )
    assert unchanged["version"] == offer_v0 + 6, (
        "six loop edges bumped the version and the refused counter did not, so the "
        "version is {} + 6, got {}".format(offer_v0, unchanged["version"])
    )

    accepted = fx.accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    assert accepted["status"] == "ACCEPTED", (
        "a rounds-exhausted offer is still acceptable, got {}".format(
            accepted["status"]
        )
    )
    assert accepted["accepted_apr_bps"] == 1010, (
        "acceptance from NAMED locks offered_apr_bps, got {}".format(
            accepted["accepted_apr_bps"]
        )
    )
    assert accepted["version"] == offer_v0 + 7, (
        "acceptance adds the seventh version bump, got {}".format(accepted["version"])
    )
    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice["status"] == "AWARDED", (
        "acceptance drives the invoice OFFERED -> AWARDED, got {}".format(
            invoice["status"]
        )
    )
    assert invoice["accepted_apr_bps"] == 1010, (
        "the locked APR is copied onto the invoice, got {}".format(
            invoice["accepted_apr_bps"]
        )
    )


def test_accounting_axis_moves_while_the_funding_axis_stays_reserved():
    """The accounting axis is written while funding is still RESERVED and survives
    the execute call that advances the other two axes; the off-default request is
    refused until a justification accompanies it.

    PRD (§3.9): "A payment funded from the buyer's own balance sheet —
    `funding_source` `BUYER_SELF` — always defaults to `TRADE_PAYABLE`, because no
    third party has interposed itself."
    PRD (§3.9): "Whenever the submitted `classification` differs from the payment's
    `default_accounting_status`, `override_reason` must be present and non-empty
    after trimming whitespace; a missing or blank justification on a diverging
    classification is rejected with `ERR_RECLASS_OVERRIDE_REASON_REQUIRED`."
    PRD (§3.8): "The cash axis moves `RESERVED → DEPLOYED` and, on the very same
    call, the remittance axis moves `UNSENT → REMITTED`."
    PRD (§3.8): "The two axes remain independent even though both moved here:
    settlement can subsequently fail while the cash axis stays `DEPLOYED` until the
    failure path voids it, and `accounting_status` is untouched throughout."

    Design: Difficulty/non_linear_state_machine/early_payment_three_independent_axes_funding_settlement_accounting
    """
    ctx = _self_only_reserved_payment()
    reserved = ctx.payment
    assert_payment_axes(
        reserved,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert reserved["funding_source"] == "BUYER_SELF", (
        "a SELF_ONLY programme funds from the buyer, got {}".format(
            reserved["funding_source"]
        )
    )
    assert reserved["default_accounting_status"] == "TRADE_PAYABLE", (
        "a BUYER_SELF payment always defaults to TRADE_PAYABLE, got {}".format(
            reserved["default_accounting_status"]
        )
    )
    assert_cash_breakdown(
        reserved,
        days_early=56,
        discount_amount_cents=1353,
        funder_fee_cents=0,
        net_payment_cents=107_398,
    )
    reserved_version = reserved["version"]

    # The off-default classification without a justification is refused.
    refused = api_client.classify_accounting(
        ctx.payment_id, f.classification_payload("DEBT_RECLASSIFIED"), ctx.treasury
    )
    validate_error(refused, ERR_RECLASS_OVERRIDE_REASON_REQUIRED, 422)
    after_refusal = fx.read_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        after_refusal,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert after_refusal["version"] == reserved_version, (
        "the refused classification wrote nothing, so version stays {}, got {}".format(
            reserved_version, after_refusal["version"]
        )
    )

    classified = validate_success(
        api_client.classify_accounting(
            ctx.payment_id,
            f.classification_payload(
                "DEBT_RECLASSIFIED",
                override_reason="Controller treats the arrangement as disclosed debt",
            ),
            ctx.treasury,
        )
    )
    assert_payment_axes(
        classified,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="DEBT_RECLASSIFIED",
    )
    assert classified["version"] == reserved_version + 1, (
        "the classification bumps the version by exactly one, got {}".format(
            classified["version"]
        )
    )
    assert classified["default_accounting_status"] == "TRADE_PAYABLE", (
        "the default is computed once at reservation and never recomputed, got {}".format(
            classified["default_accounting_status"]
        )
    )

    fx.set_clock("2026-08-05T00:00:00Z")
    executed = fx.execute_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        executed,
        funding_status="DEPLOYED",
        settlement_status="REMITTED",
        accounting_status="DEBT_RECLASSIFIED",
    )
    assert_cash_breakdown(
        executed,
        days_early=56,
        discount_amount_cents=1353,
        funder_fee_cents=0,
        net_payment_cents=107_398,
    )
    assert str(executed["execution_date"])[:10] == "2026-08-05", (
        "execution_date is stamped from the logical clock, got {!r}".format(
            executed["execution_date"]
        )
    )
    assert str(executed["value_date"])[:10] == "2026-08-07", (
        "value_date is the execution date advanced by two days, got {!r}".format(
            executed["value_date"]
        )
    )
    buyer = validate_success(api_client.get_buyer(ctx.buyer_id, PLATFORM_OPS_HEADERS))
    assert buyer["credit_used_cents"] == 107_398, (
        "a DEPLOYED BUYER_SELF payment keeps its net on the buyer's credit, got {}".format(
            buyer["credit_used_cents"]
        )
    )


def test_accounting_axis_remains_writable_after_the_funding_axis_is_void():
    """Once settlement has failed and the cash axis is the terminal VOID, the
    accounting axis still accepts movements in both directions.

    PRD (§3.9): "This axis carries no funding or settlement precondition whatever —
    the payment need only exist, and classification is permitted at any
    `funding_status` including `VOID` and at any `settlement_status` including
    `FAILED`."
    PRD (§3.9): "Re-classification is permitted without limit, because this axis has
    no terminal state — a controller may revisit the judgement as often as the
    auditors require."
    PRD (§3.8): "The remittance axis moves `REMITTED → FAILED` and the cash axis
    moves `DEPLOYED → VOID`, releasing the funder's `encumbered_capital_cents` or
    the buyer's `credit_used_cents` in full."

    Design: Difficulty/non_linear_state_machine/early_payment_three_independent_axes_funding_settlement_accounting
    """
    ctx = _self_only_reserved_payment()
    classified = validate_success(
        api_client.classify_accounting(
            ctx.payment_id, f.classification_payload("TRADE_PAYABLE"), ctx.treasury
        )
    )
    assert classified["accounting_status"] == "TRADE_PAYABLE", (
        "a classification matching the default needs no justification, got {}".format(
            classified["accounting_status"]
        )
    )

    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(ctx.payment_id, ctx.buyer_id)
    failed = fx.fail_settlement(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        failed,
        funding_status="VOID",
        settlement_status="FAILED",
        accounting_status="TRADE_PAYABLE",
    )

    buyer = validate_success(api_client.get_buyer(ctx.buyer_id, PLATFORM_OPS_HEADERS))
    assert buyer["credit_used_cents"] == 0, (
        "voiding the payment frees the buyer's credit in full, got {}".format(
            buyer["credit_used_cents"]
        )
    )
    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice["status"] == "AWARDED", (
        "a failed settlement deliberately leaves the invoice AWARDED, got {}".format(
            invoice["status"]
        )
    )
    assert invoice["face_covered_cents"] == 0, (
        "the face ledger is restored, got face_covered {}".format(
            invoice["face_covered_cents"]
        )
    )
    assert invoice["remaining_face_cents"] == FACE_108751, (
        "remaining_face_cents returns to the full face, got {}".format(
            invoice["remaining_face_cents"]
        )
    )
    assert invoice["provisional_discount_cents"] == 0, (
        "the provisional discount returns to 0, got {}".format(
            invoice["provisional_discount_cents"]
        )
    )
    assert_invoice_face_conserved(invoice)

    # The accounting axis is still writable in both directions at terminal VOID.
    reclassified = validate_success(
        api_client.classify_accounting(
            ctx.payment_id,
            f.classification_payload(
                "DEBT_RECLASSIFIED",
                override_reason="Audit committee reclassified the failed remittance",
            ),
            ctx.treasury,
        )
    )
    assert_payment_axes(
        reclassified,
        funding_status="VOID",
        settlement_status="FAILED",
        accounting_status="DEBT_RECLASSIFIED",
    )
    back_again = validate_success(
        api_client.classify_accounting(
            ctx.payment_id, f.classification_payload("TRADE_PAYABLE"), ctx.treasury
        )
    )
    assert_payment_axes(
        back_again,
        funding_status="VOID",
        settlement_status="FAILED",
        accounting_status="TRADE_PAYABLE",
    )
    assert back_again["version"] == reclassified["version"] + 1, (
        "each classification increments the version by one, got {} after {}".format(
            back_again["version"], reclassified["version"]
        )
    )


def test_supplier_onboarding_fork_join_of_identity_and_bank_axes():
    """Submitting onboarding opens only the identity axis, a MANUAL_REVIEW decision
    is a self-loop, a verified bank account alone does not fire the join, and the
    supplier reaches ACTIVE on the call that completes the last axis.

    PRD (§3.2): "It sets `idv_status` to `PENDING`, opening the identity axis, and
    it deliberately leaves `bank_status` at `NOT_STARTED`, because the bank axis
    opens only when a settlement account is registered."
    PRD (§3.2): "A decision of `PASSED` or `MANUAL_REVIEW` writes only
    identity-axis fields and leaves `onboarding_status` at `VERIFYING`"
    PRD (§3.2): "Whenever `idv_status` is `PASSED`, `bank_status` is `VERIFIED` and
    `sanctions_hold` is false, the supplier moves `VERIFYING → ACTIVE` and
    `payment_ready_at` is stamped with the logical-clock instant; the join is
    reachable from either branch completing last, and the supplier's `version`
    increments."

    Design: Difficulty/non_linear_state_machine/supplier_onboarding_fork_join_of_identity_and_bank_axes
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    supplier = fx.new_supplier(legal_name="Join Order Supplier S")
    supplier_id = supplier["id"]
    assert_supplier_axes(
        supplier,
        onboarding_status="DRAFT",
        idv_status="NOT_STARTED",
        bank_status="NOT_STARTED",
    )

    submitted = fx.submit_onboarding(supplier_id)
    assert_supplier_axes(
        submitted,
        onboarding_status="VERIFYING",
        idv_status="PENDING",
        bank_status="NOT_STARTED",
    )
    assert submitted["identity_score"] == 0, (
        "identity_score stays 0 until idv_status leaves PENDING, got {}".format(
            submitted["identity_score"]
        )
    )

    # The identity axis self-loops on MANUAL_REVIEW.
    reviewed = fx.adjudicate_idv(supplier_id, "MANUAL_REVIEW", 55)
    assert_supplier_axes(
        reviewed,
        onboarding_status="VERIFYING",
        idv_status="MANUAL_REVIEW",
        bank_status="NOT_STARTED",
    )
    assert reviewed["identity_score"] == 55, (
        "the adjudicated score is written to the supplier, got {}".format(
            reviewed["identity_score"]
        )
    )
    assert reviewed["idv_verified_at"] is None, (
        "only a PASSED decision stamps idv_verified_at, got {!r}".format(
            reviewed["idv_verified_at"]
        )
    )
    assert reviewed["payment_ready_at"] is None, (
        "the join has not fired, so payment_ready_at is null, got {!r}".format(
            reviewed["payment_ready_at"]
        )
    )

    # The bank axis completes first.
    bank = fx.add_bank_account(supplier_id, "021000021", "4321")
    assert bank["micro_deposit_code"] == f.expected_micro_deposit_code(
        "021000021", "4321"
    ), "the code is the routing tail plus the account head, got {!r}".format(
        bank["micro_deposit_code"]
    )
    confirmed = fx.confirm_micro_deposit(bank["id"], supplier_id, bank["micro_deposit_code"])
    assert confirmed["status"] == "VERIFIED", (
        "the matching code verifies the account, got {}".format(confirmed["status"])
    )
    assert confirmed["micro_deposit_attempts"] == 1, (
        "a successful confirmation still increments the attempt count, got {}".format(
            confirmed["micro_deposit_attempts"]
        )
    )

    half_joined = validate_success(
        api_client.get_supplier(supplier_id, PLATFORM_OPS_HEADERS)
    )
    assert_supplier_axes(
        half_joined,
        onboarding_status="VERIFYING",
        idv_status="MANUAL_REVIEW",
        bank_status="VERIFIED",
    )
    assert half_joined["verified_account_last4"] == "4321", (
        "verification records the account tail, got {!r}".format(
            half_joined["verified_account_last4"]
        )
    )
    assert half_joined["payment_ready_at"] is None, (
        "one completed axis does not fire the join, got payment_ready_at {!r}".format(
            half_joined["payment_ready_at"]
        )
    )

    # The identity axis completes last, and that call fires the join.
    joined = fx.adjudicate_idv(supplier_id, "PASSED", 87)
    assert_supplier_axes(
        joined,
        onboarding_status="ACTIVE",
        idv_status="PASSED",
        bank_status="VERIFIED",
    )
    assert joined["identity_score"] == 87, (
        "the final score overwrites the review score, got {}".format(
            joined["identity_score"]
        )
    )
    assert joined["idv_verified_at"] is not None, (
        "a PASSED decision stamps idv_verified_at"
    )
    assert joined["payment_ready_at"] is not None, (
        "the join stamps payment_ready_at"
    )
    assert str(joined["payment_ready_at"]).startswith("2026-08-01"), (
        "payment_ready_at carries the logical-clock instant, got {!r}".format(
            joined["payment_ready_at"]
        )
    )
    assert joined["version"] > half_joined["version"], (
        "the join increments the supplier's version, got {} after {}".format(
            joined["version"], half_joined["version"]
        )
    )


def test_dead_bank_axis_strands_a_passed_supplier_in_verifying():
    """A supplier whose identity axis has PASSED but whose bank axis died after
    three wrong codes stays in VERIFYING, and the fourth attempt is refused before
    the correct code is even compared.

    PRD (§3.2): "If the code differs and the incremented attempt count is still
    below three, `micro_deposit_attempts` increments by one and the account stays in
    `MICRO_DEPOSIT_SENT`, re-armed for another try"
    PRD (§3.2): "If the code differs and the incremented attempt count reaches
    three, `micro_deposit_attempts` increments to three, the account moves
    `MICRO_DEPOSIT_SENT → FAILED`, the supplier's `bank_status` mirrors `FAILED`,
    and both `version` fields increment; any further confirmation attempt on that
    row is rejected with `ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED`, and the supplier's
    only route forward is a replacement account row."
    PRD (§3.2): "Confirming the micro deposit means submitting a `code` for
    evaluation. Before the code is even compared, the attempt budget is checked:
    `micro_deposit_attempts` must be strictly below three, and a supplier's
    `sanctions_hold` must be false."

    Design: Difficulty/non_linear_state_machine/supplier_onboarding_fork_join_of_identity_and_bank_axes
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    supplier = fx.new_supplier(legal_name="Dead Bank Supplier T")
    supplier_id = supplier["id"]
    fx.submit_onboarding(supplier_id)

    # Identity first this time: the join still waits for the bank axis.
    identity_done = fx.adjudicate_idv(supplier_id, "PASSED", 84)
    assert_supplier_axes(
        identity_done,
        onboarding_status="VERIFYING",
        idv_status="PASSED",
        bank_status="NOT_STARTED",
    )
    assert identity_done["payment_ready_at"] is None, (
        "identity-first order also waits for the bank axis, got {!r}".format(
            identity_done["payment_ready_at"]
        )
    )

    bank = fx.add_bank_account(supplier_id, "011000015", "8899")
    correct_code = f.expected_micro_deposit_code("011000015", "8899")
    assert correct_code == "015889", (
        "the derived code for 011000015 / 8899 is 015889, got {!r}".format(correct_code)
    )
    assert bank["micro_deposit_code"] == correct_code, (
        "the platform pushes the derived code, got {!r}".format(
            bank["micro_deposit_code"]
        )
    )
    assert bank["micro_deposit_attempts"] == 0, (
        "a new account row starts with 0 attempts, got {}".format(
            bank["micro_deposit_attempts"]
        )
    )

    headers = make_supplier_headers(supplier_id)
    for attempt, (wrong_code, expected_status) in enumerate(
        [
            ("000000", "MICRO_DEPOSIT_SENT"),
            ("111111", "MICRO_DEPOSIT_SENT"),
            ("222222", "FAILED"),
        ],
        start=1,
    ):
        row = validate_success(
            api_client.confirm_micro_deposit(
                bank["id"], f.micro_deposit_payload(wrong_code), headers
            )
        )
        assert row["micro_deposit_attempts"] == attempt, (
            "attempt {}: the counter increments on every wrong code, got {}".format(
                attempt, row["micro_deposit_attempts"]
            )
        )
        assert row["status"] == expected_status, (
            "attempt {}: the account should be {}, got {}".format(
                attempt, expected_status, row["status"]
            )
        )

    # The budget is spent, so even the correct code is refused.
    refused = api_client.confirm_micro_deposit(
        bank["id"], f.micro_deposit_payload(correct_code), headers
    )
    validate_error(refused, ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED, 409)

    stranded = validate_success(api_client.get_supplier(supplier_id, PLATFORM_OPS_HEADERS))
    assert_supplier_axes(
        stranded,
        onboarding_status="VERIFYING",
        idv_status="PASSED",
        bank_status="FAILED",
    )
    assert stranded["payment_ready_at"] is None, (
        "a dead bank axis never fires the join, got payment_ready_at {!r}".format(
            stranded["payment_ready_at"]
        )
    )
    assert stranded["verified_account_last4"] is None, (
        "no account was ever verified, got {!r}".format(
            stranded["verified_account_last4"]
        )
    )


def test_neither_cycle_edge_is_available_from_the_other_edges_source_state():
    """The two edges of the negotiation cycle are not interchangeable: re-naming is
    refused while the offer is ``NAMED`` and countering is refused while it is
    ``COUNTERED``, both with `ERR_INVALID_STATE`. Neither refusal advances
    ``counter_round``, bumps the offer's ``version`` or disturbs the session's
    ``named_offer_count``, which counts the offer once whichever end of the cycle
    it currently sits at.

    PRD (§2.7 check 11): "the addressed resource satisfies the preconditions of
    the requested transition, whether that means being in the right non-terminal
    source state or having a fork-join precondition met such as identity
    verification already having passed. Otherwise `ERR_INVALID_STATE` (409)."

    PRD (§3.6): "A programme owner counters a `NAMED` offer by supplying a
    `counter_apr_bps`, which moves the offer `NAMED → COUNTERED` and stores the
    countered rate."

    PRD (§3.6): "Re-naming requires the offer to be `COUNTERED`, the session to be
    `LIVE` with the clock inside the window, the new rate to be strictly greater
    than the previous `offered_apr_bps`"

    PRD (§3.5): "The session's `named_offer_count` tracks live and settled
    negotiation activity: it counts the offers on that session whose `status` is
    `NAMED`, `COUNTERED` or `ACCEPTED`."

    Design: Difficulty/non_linear_state_machine/offer_counter_rename_cycle_bounded_at_three_rounds
    """
    ctx = fx.build_named_offer(offered_apr_bps=700, face_cents=500_000)
    offer_v0 = ctx.offer["version"]

    def session_count():
        rows, _meta = validate_paginated(
            api_client.list_program_sessions(ctx.program_id, ctx.admin)
        )
        match = [row for row in rows if row["id"] == ctx.session_id]
        assert len(match) == 1, "the programme lists its session exactly once"
        return match[0]["named_offer_count"]

    assert session_count() == 1, (
        "a NAMED offer is inside the counted set, got {}".format(session_count())
    )

    # Rename is the COUNTERED -> NAMED edge, so it has no source state here.
    too_soon = api_client.rename_offer(
        ctx.offer_id, f.rename_payload(810), ctx.supplier_headers
    )
    body = validate_error(too_soon, ERR_INVALID_STATE, 409)
    assert body["error_id"] != ERR_COUNTER_ROUNDS_EXHAUSTED, (
        "the rounds budget is untouched — this is a source-state failure"
    )

    still_named = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert still_named["status"] == "NAMED", (
        "the refused rename leaves the offer in NAMED, got {}".format(
            still_named["status"]
        )
    )
    assert still_named["offered_apr_bps"] == 700, (
        "the refused rename must not overwrite offered_apr_bps, got {}".format(
            still_named["offered_apr_bps"]
        )
    )
    assert still_named["counter_round"] == 0, (
        "a refused edge advances no loop counter, got {}".format(
            still_named["counter_round"]
        )
    )
    assert still_named["version"] == offer_v0, (
        "a refused edge is not a mutation, so the version stays at {}, got {}".format(
            offer_v0, still_named["version"]
        )
    )

    countered = validate_success(
        api_client.counter_offer(ctx.offer_id, f.counter_payload(800), ctx.admin)
    )
    assert countered["status"] == "COUNTERED", (
        "the counter edge is available from NAMED, got {}".format(countered["status"])
    )
    assert countered["counter_round"] == 0, (
        "the counter edge does not advance the loop counter, got {}".format(
            countered["counter_round"]
        )
    )
    assert countered["version"] == offer_v0 + 1
    assert session_count() == 1, (
        "COUNTERED is inside the same counted set, got {}".format(session_count())
    )

    # And countering again has no source state, because the offer left NAMED.
    twice = api_client.counter_offer(ctx.offer_id, f.counter_payload(900), ctx.admin)
    second_body = validate_error(twice, ERR_INVALID_STATE, 409)
    assert second_body["error_id"] != ERR_COUNTER_ROUNDS_EXHAUSTED, (
        "only one of three rounds has been opened, so the budget is not the cause"
    )

    frozen = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert frozen["status"] == "COUNTERED", (
        "the refused counter leaves the offer in COUNTERED, got {}".format(
            frozen["status"]
        )
    )
    assert frozen["counter_apr_bps"] == 800, (
        "the stored counter rate must not be overwritten, got {}".format(
            frozen["counter_apr_bps"]
        )
    )
    assert frozen["counter_round"] == 0
    assert frozen["version"] == offer_v0 + 1, (
        "still exactly one successful edge, got version {}".format(frozen["version"])
    )

    # The cycle then closes normally from its real source state.
    renamed = validate_success(
        api_client.rename_offer(ctx.offer_id, f.rename_payload(810), ctx.supplier_headers)
    )
    assert renamed["status"] == "NAMED", (
        "the rename edge is available from COUNTERED, got {}".format(renamed["status"])
    )
    assert renamed["counter_round"] == 1, (
        "one full cycle has completed, got {}".format(renamed["counter_round"])
    )
    assert renamed["counter_apr_bps"] is None, (
        "re-naming clears the counter rate, got {!r}".format(renamed["counter_apr_bps"])
    )
    assert renamed["offered_apr_bps"] == 810
    assert renamed["version"] == offer_v0 + 2, (
        "two successful edges and two refusals leave the version at {} + 2, got {}".format(
            offer_v0, renamed["version"]
        )
    )
    assert session_count() == 1, (
        "traversing the cycle never double-counts the offer, got {}".format(
            session_count()
        )
    )
    assert_invoice_face_conserved(fx.read_invoice(ctx.invoice_id, ctx.buyer_id))
