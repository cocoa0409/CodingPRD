"""Corner-case coverage of the state machines in the dynamic-discounting contract.

Each test drives one declared edge — or one deliberately refused edge — of a
single state machine through the public API and then asserts every axis the PRD
pins for that transition: the source and target enum members, the cascaded
sibling rows, the recomputed analytics block and, where the PRD fixes it, the
exact ``version`` the row must carry afterwards.

The harness restarts the API server before every test, so each test builds all
of its own state from an empty database using the shared builders in
``test_helpers.fixtures``.
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
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_invoice,
    assert_invoice_face_conserved,
    assert_offer,
    assert_program,
    assert_supplier_axes,
    assert_two_decimal_percentage,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_funder_headers,
    make_supplier_headers,
)


def test_program_open_moves_draft_to_open_and_zeroes_the_analytics_block():
    """Opening a fresh DRAFT programme flips it to OPEN and runs the adoption
    recomputation over an empty invoice set, so every analytics figure is written
    at its zero branch and the programme's version lands on exactly 2.

    PRD 3.1: "Opening a programme moves it from `DRAFT` to `OPEN`."
    PRD 3.1: "Opening also runs the adoption recomputation described in §3.10, which on a fresh programme leaves both counters at 0 and `adoption_rate_pct` at exactly 0.00, and bumps the programme's `version` by one."
    PRD 3.10: "A brand-new programme with no invoices therefore sits at 0.00 percent in `DISCOVERY`."
    Design: Corner/state_machines/program_open_moves_draft_to_open_and_zeroes_the_analytics_block
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Open Edge Buyer", credit_limit_cents=9_000_000)
    draft = fx.new_program(
        buyer["id"],
        name="Open Edge Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    assert draft["status"] == "DRAFT", (
        "a new programme is persisted in DRAFT, got {!r}".format(draft["status"])
    )
    assert draft["version"] == 1, (
        "version starts at 1 on creation, got {}".format(draft["version"])
    )

    opened = validate_success(
        api_client.open_program(draft["id"], make_buyer_admin_headers(buyer["id"])), 200
    )

    assert_program(
        opened,
        id=draft["id"],
        status="OPEN",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
        weighted_avg_accepted_apr_bps=0,
        max_acceptable_apr_bps=1200,
        version=2,
    )
    assert_two_decimal_percentage(opened["adoption_rate_pct"], 0.00)

    # The same figures must be persisted, not merely echoed by the open call.
    reread = validate_success(
        api_client.get_program(draft["id"], make_buyer_admin_headers(buyer["id"])), 200
    )
    assert_program(
        reread,
        status="OPEN",
        rate_posture="DISCOVERY",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        version=2,
    )
    assert_two_decimal_percentage(reread["adoption_rate_pct"], 0.00)

    buyer_row = validate_success(
        api_client.get_buyer(buyer["id"], PLATFORM_OPS_HEADERS), 200
    )
    assert buyer_row["status"] == "ACTIVE", (
        "opening a programme leaves the owning buyer ACTIVE, got {!r}".format(
            buyer_row["status"]
        )
    )


def test_reopening_a_closed_program_returns_already_terminal():
    """CLOSED is the only terminal programme state, so a second open attempt is
    caught by the terminal check at precedence 10 rather than by the
    wrong-source-state check at 11, and nothing the close cascade wrote moves.

    PRD 3.1: "A programme that is not in `DRAFT` when opening is attempted is rejected with `ERR_INVALID_STATE`, unless it has already reached `CLOSED`, in which case the terminal-state check reports `ERR_ALREADY_TERMINAL` first."
    PRD 3.1: "Third, if after this close no programme of that buyer holds `status` `DRAFT`, `OPEN` or `PAUSED`, the buyer itself moves from `ACTIVE` to `SUSPENDED`."
    Design: Corner/state_machines/reopening_a_closed_program_returns_already_terminal
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Terminal Lock Buyer", credit_limit_cents=9_000_000)
    program = fx.new_program(
        buyer["id"],
        name="Terminal Lock Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    fx.open_program(program["id"], buyer["id"])
    closed = fx.set_program_status(program["id"], buyer["id"], "CLOSE")
    assert closed["status"] == "CLOSED", (
        "CLOSE moves an OPEN programme to CLOSED, got {!r}".format(closed["status"])
    )
    closed_version = closed["version"]

    resp = api_client.open_program(program["id"], make_buyer_admin_headers(buyer["id"]))
    validate_error(resp, ERR_ALREADY_TERMINAL, 409)

    reread = validate_success(
        api_client.get_program(program["id"], make_buyer_admin_headers(buyer["id"])), 200
    )
    assert_program(reread, status="CLOSED", version=closed_version)

    buyer_row = validate_success(
        api_client.get_buyer(buyer["id"], PLATFORM_OPS_HEADERS), 200
    )
    assert buyer_row["status"] == "SUSPENDED", (
        "the close cascade suspended the sole-programme buyer and the rejected "
        "re-open must not undo it, got {!r}".format(buyer_row["status"])
    )


def test_opening_an_already_open_program_returns_invalid_state():
    """A repeated open on a live OPEN programme is not idempotent and is not the
    terminal error either: OPEN is simply the wrong source state for this edge,
    so precedence 11 fires and the version stays at 2.

    PRD 3.1: "A programme that is not in `DRAFT` when opening is attempted is rejected with `ERR_INVALID_STATE`, unless it has already reached `CLOSED`, in which case the terminal-state check reports `ERR_ALREADY_TERMINAL` first."
    Design: Corner/state_machines/opening_an_already_open_program_returns_invalid_state
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Double Open Buyer", credit_limit_cents=9_000_000)
    program = fx.new_program(
        buyer["id"],
        name="Double Open Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    opened = fx.open_program(program["id"], buyer["id"])
    assert opened["version"] == 2, (
        "the first open bumps version 1 -> 2, got {}".format(opened["version"])
    )

    resp = api_client.open_program(program["id"], make_buyer_admin_headers(buyer["id"]))
    validate_error(resp, ERR_INVALID_STATE, 409)

    reread = validate_success(
        api_client.get_program(program["id"], make_buyer_admin_headers(buyer["id"])), 200
    )
    assert_program(reread, status="OPEN", version=2)


def test_idv_adjudication_before_onboarding_submit_returns_invalid_state():
    """The identity axis has not been forked yet on a DRAFT supplier — idv_status
    is NOT_STARTED rather than PENDING — so adjudication is refused and writes
    nothing at all, leaving identity_score at 0 and the row at version 1.

    PRD 3.2: "Adjudication requires that `onboarding_status` is `VERIFYING` and that `idv_status` is currently either `PENDING` or `MANUAL_REVIEW`."
    PRD 2.7: "**Correct source state** — the addressed resource satisfies the preconditions of the requested transition, whether that means being in the right non-terminal source state or having a fork-join precondition met such as identity verification already having passed."
    Design: Corner/state_machines/idv_adjudication_before_onboarding_submit_returns_invalid_state
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    supplier = fx.new_supplier(
        legal_name="Premature Adjudication Ltd",
        tax_id_last4="3344",
        remittance_email="ar@premature.example",
    )
    assert_supplier_axes(
        supplier, onboarding_status="DRAFT", idv_status="NOT_STARTED",
        bank_status="NOT_STARTED",
    )

    resp = api_client.adjudicate_idv(
        supplier["id"], f.idv_payload("PASSED", 95), PLATFORM_OPS_HEADERS
    )
    validate_error(resp, ERR_INVALID_STATE, 409)

    reread = validate_success(
        api_client.get_supplier(supplier["id"], PLATFORM_OPS_HEADERS), 200
    )
    assert_supplier_axes(
        reread, onboarding_status="DRAFT", idv_status="NOT_STARTED",
        bank_status="NOT_STARTED",
    )
    assert reread["identity_score"] == 0, (
        "identity_score remains 0 until idv_status leaves PENDING, got {}".format(
            reread["identity_score"]
        )
    )
    assert reread["idv_verified_at"] is None, (
        "idv_verified_at is stamped only by a PASSED decision, got {!r}".format(
            reread["idv_verified_at"]
        )
    )
    assert reread["payment_ready_at"] is None, (
        "payment_ready_at is stamped only at the fork-join, got {!r}".format(
            reread["payment_ready_at"]
        )
    )
    assert reread["version"] == 1, (
        "a rejected adjudication must not bump the supplier's version, got {}".format(
            reread["version"]
        )
    )


def test_freshly_created_rows_start_in_their_declared_initial_states():
    """Seven collections are created in one chain and each must land on its own
    declared initial state rather than a neighbour's: a bank account opens in
    MICRO_DEPOSIT_SENT (never the supplier axis value NOT_STARTED), a session in
    SCHEDULED even though its window is still in the future, an unflagged
    invoice in ELIGIBLE.

    PRD 3.1: "A new programme is persisted in `status` `DRAFT` with every analytics counter at zero — `eligible_invoice_count` and `adopted_invoice_count` at 0, `adoption_rate_pct` at 0.00, `weighted_avg_accepted_apr_bps` at 0 — and `rate_posture` at `DISCOVERY`."
    PRD 3.2: "A newly registered supplier sits in `onboarding_status` `DRAFT` with `idv_status` `NOT_STARTED`, `bank_status` `NOT_STARTED`, `sanctions_hold` false, `identity_score` 0, and `idv_verified_at`, `payment_ready_at` and `verified_account_last4` all null."
    PRD 3.2: "The new row is persisted in `status` `MICRO_DEPOSIT_SENT` with `micro_deposit_attempts` at 0, and the supplier's `bank_status` is set to `MICRO_DEPOSIT_SENT`."
    PRD 3.5: "A new session is persisted in `status` `SCHEDULED` with `named_offer_count` at 0 and `clearing_apr_bps` at 0."
    PRD 3.7: "A new funder opens in `status` `ACTIVE` with `encumbered_capital_cents` at 0 and `available_capital_cents` at 0, since no tranche has been committed yet."
    PRD 3.7: "Tranches are persisted in `status` `ACTIVE`, and the only other tranche state is the terminal `EXPIRED`."
    PRD 3.3: "Rows without the flag, or with it set to false, produce invoices in `ELIGIBLE`."
    Design: Corner/state_machines/freshly_created_rows_start_in_their_declared_initial_states
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Initial State Buyer", credit_limit_cents=9_000_000)
    admin = make_buyer_admin_headers(buyer["id"])

    program = validate_success(
        api_client.create_program(
            f.program_payload(
                buyer["id"],
                name="Initial State Programme",
                program_type="SUPPLIER_NAMED",
                max_acceptable_apr_bps=1200,
            ),
            admin,
        ),
        201,
    )
    assert_program(
        program,
        status="DRAFT",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        weighted_avg_accepted_apr_bps=0,
        rate_posture="DISCOVERY",
        version=1,
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)
    fx.open_program(program["id"], buyer["id"])

    supplier = validate_success(
        api_client.create_supplier(
            f.supplier_payload(
                legal_name="Initial State Supply",
                tax_id_last4="4455",
                remittance_email="ar@initial.example",
            ),
            PLATFORM_OPS_HEADERS,
        ),
        201,
    )
    assert_supplier_axes(
        supplier, onboarding_status="DRAFT", idv_status="NOT_STARTED",
        bank_status="NOT_STARTED",
    )
    assert supplier["sanctions_hold"] is False, (
        "a new supplier carries sanctions_hold false, got {!r}".format(
            supplier["sanctions_hold"]
        )
    )
    assert supplier["identity_score"] == 0, (
        "a new supplier carries identity_score 0, got {}".format(
            supplier["identity_score"]
        )
    )
    assert supplier["verified_account_last4"] is None, (
        "verified_account_last4 opens null, got {!r}".format(
            supplier["verified_account_last4"]
        )
    )

    submitted = fx.submit_onboarding(supplier["id"])
    assert_supplier_axes(
        submitted, onboarding_status="VERIFYING", idv_status="PENDING",
        bank_status="NOT_STARTED",
    )

    bank = validate_success(
        api_client.create_bank_account(
            supplier["id"],
            f.bank_account_payload("011000015", "8899"),
            make_supplier_headers(supplier["id"]),
        ),
        201,
    )
    assert bank["status"] == "MICRO_DEPOSIT_SENT", (
        "a bank account opens in MICRO_DEPOSIT_SENT, never in the supplier-axis "
        "value NOT_STARTED, got {!r}".format(bank["status"])
    )
    assert bank["micro_deposit_attempts"] == 0, (
        "micro_deposit_attempts opens at 0, got {}".format(
            bank["micro_deposit_attempts"]
        )
    )

    session = validate_success(
        api_client.create_session(
            f.session_payload(
                program["id"], "2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"
            ),
            admin,
        ),
        201,
    )
    assert session["status"] == "SCHEDULED", (
        "a session opens in SCHEDULED, never LIVE, got {!r}".format(session["status"])
    )
    assert session["named_offer_count"] == 0, (
        "named_offer_count opens at 0, got {}".format(session["named_offer_count"])
    )
    assert session["clearing_apr_bps"] == 0, (
        "clearing_apr_bps opens at 0, got {}".format(session["clearing_apr_bps"])
    )

    funder = validate_success(
        api_client.create_funder(
            f.funder_payload(
                legal_name="Initial State Capital",
                capital_limit_cents=2_000_000,
                min_apr_bps=500,
                fee_spread_bps=10,
                max_single_invoice_cents=1_000_000,
            ),
            PLATFORM_OPS_HEADERS,
        ),
        201,
    )
    assert funder["status"] == "ACTIVE", (
        "a funder opens in ACTIVE, got {!r}".format(funder["status"])
    )
    assert funder["encumbered_capital_cents"] == 0, (
        "encumbered_capital_cents opens at 0, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert funder["available_capital_cents"] == 0, (
        "available_capital_cents opens at 0 before any tranche, got {}".format(
            funder["available_capital_cents"]
        )
    )

    tranche = validate_success(
        api_client.create_commitment(
            funder["id"],
            f.commitment_payload(
                committed_amount_cents=1_000_000,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-08-31T00:00:00Z",
            ),
            make_funder_headers(funder["id"]),
        ),
        201,
    )
    assert tranche["status"] == "ACTIVE", (
        "a capital tranche is persisted in ACTIVE, got {!r}".format(tranche["status"])
    )

    payable_file = fx.ingest_file(
        program["id"],
        buyer["id"],
        [
            f.payable_row(
                supplier["id"],
                invoice_number="INIT-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
                tax_rate_bps=0,
            )
        ],
        filename="AP-INIT.csv",
    )
    invoices = fx.invoices_of_file(payable_file["id"], buyer["id"])
    assert len(invoices) == 1, (
        "one accepted row produces exactly one invoice, got {}".format(len(invoices))
    )
    assert_invoice(
        invoices[0],
        status="ELIGIBLE",
        face_amount_cents=100_000,
        face_covered_cents=0,
        remaining_face_cents=100_000,
        dispute_suppressed=False,
        version=1,
    )


def test_registering_a_replacement_bank_account_demotes_the_active_supplier():
    """Registering a second settlement account on an already ACTIVE supplier fires
    the whole replace chain: the prior row goes REPLACED, the bank axis rewinds to
    MICRO_DEPOSIT_SENT, verified_account_last4 is cleared and the supplier drops
    ACTIVE -> VERIFYING with payment_ready_at nulled — while the identity axis
    keeps idv_status PASSED, proving only the bank branch was rewound.

    PRD 3.2: "Any earlier account row of the same supplier whose `status` is `MICRO_DEPOSIT_SENT`, `VERIFIED` or `FAILED` becomes `REPLACED`; the supplier's `bank_status` is set to `MICRO_DEPOSIT_SENT` to mirror the new row and `verified_account_last4` is cleared to null; and if the supplier's `onboarding_status` had already reached `ACTIVE`, it drops back to `VERIFYING` and `payment_ready_at` is cleared to null."
    PRD 3.2: "The displaced account row and the supplier row each have their `version` incremented by one."
    PRD 3.2: "The platform pushes a micro deposit carrying a six-digit `micro_deposit_code`, and that code is fully determined by the account itself: it is the zero-padded decimal formed by concatenating the last three digits of `routing_number` with the first three digits of `account_last4`."
    Design: Corner/state_machines/registering_a_replacement_bank_account_demotes_the_active_supplier
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    supplier = fx.onboard_supplier(
        routing_number="021000021",
        account_last4="4321",
        identity_score=88,
        legal_name="Bank Swap Supply Co",
        tax_id_last4="5566",
        remittance_email="ar@bankswap.example",
    )
    supplier_id = supplier["id"]
    bank_one_id = supplier["bank_account_id"]
    assert_supplier_axes(
        supplier, onboarding_status="ACTIVE", idv_status="PASSED", bank_status="VERIFIED"
    )
    assert supplier["verified_account_last4"] == "4321", (
        "a confirmed micro deposit copies account_last4 onto the supplier, got "
        "{!r}".format(supplier["verified_account_last4"])
    )
    assert supplier["payment_ready_at"] is not None, (
        "the fork-join stamps payment_ready_at when both axes complete"
    )

    bank_two = validate_success(
        api_client.create_bank_account(
            supplier_id,
            f.bank_account_payload("011000015", "8899"),
            make_supplier_headers(supplier_id),
        ),
        201,
    )
    assert bank_two["status"] == "MICRO_DEPOSIT_SENT", (
        "the replacement account opens in MICRO_DEPOSIT_SENT, got {!r}".format(
            bank_two["status"]
        )
    )
    assert bank_two["micro_deposit_attempts"] == 0, (
        "the replacement account opens with 0 attempts, got {}".format(
            bank_two["micro_deposit_attempts"]
        )
    )
    assert bank_two["micro_deposit_code"] == f.expected_micro_deposit_code(
        "011000015", "8899"
    ), (
        "the code is the last three routing digits plus the first three "
        "account_last4 digits, expected '015889', got {!r}".format(
            bank_two["micro_deposit_code"]
        )
    )

    accounts, meta = validate_paginated(
        api_client.list_bank_accounts(supplier_id, make_supplier_headers(supplier_id))
    )
    assert meta["total_count"] == 2, (
        "the supplier now owns two account rows, got {}".format(meta["total_count"])
    )
    by_id = {row["id"]: row for row in accounts}
    assert by_id[bank_one_id]["status"] == "REPLACED", (
        "the displaced VERIFIED account becomes REPLACED, got {!r}".format(
            by_id[bank_one_id]["status"]
        )
    )
    assert by_id[bank_one_id]["version"] == 3, (
        "the displaced row's version is 1 at creation, 2 after the micro-deposit "
        "confirmation and 3 after the replace edge, got {}".format(
            by_id[bank_one_id]["version"]
        )
    )
    assert by_id[bank_two["id"]]["status"] == "MICRO_DEPOSIT_SENT", (
        "the new account stays MICRO_DEPOSIT_SENT, got {!r}".format(
            by_id[bank_two["id"]]["status"]
        )
    )

    reread = validate_success(
        api_client.get_supplier(supplier_id, PLATFORM_OPS_HEADERS), 200
    )
    assert_supplier_axes(
        reread,
        onboarding_status="VERIFYING",
        idv_status="PASSED",
        bank_status="MICRO_DEPOSIT_SENT",
    )
    assert reread["verified_account_last4"] is None, (
        "verified_account_last4 is cleared to null by the replace edge, got {!r}".format(
            reread["verified_account_last4"]
        )
    )
    assert reread["payment_ready_at"] is None, (
        "payment_ready_at is cleared to null when ACTIVE is rewound, got {!r}".format(
            reread["payment_ready_at"]
        )
    )
    assert reread["identity_score"] == 88, (
        "the identity axis is untouched, so identity_score stays 88, got {}".format(
            reread["identity_score"]
        )
    )
    assert reread["idv_verified_at"] is not None, (
        "the identity axis keeps its PASSED stamp through a bank replacement"
    )


def test_cancelling_a_live_session_expires_its_named_offers():
    """Cancelling a LIVE window reaches every NAMED offer on it and stops there:
    no clearing rate is written, so clearing_apr_bps stays 0, and the two invoices
    stay OFFERED rather than reverting to ELIGIBLE.

    PRD 3.5: "With `mode` set to `CANCEL`, the session may be `SCHEDULED` or `LIVE` and it moves to `CANCELLED`, expiring outstanding offers in ascending `created_at` order but writing no clearing rate."
    PRD 3.6: "Offers reach their terminal states from several directions, all covered elsewhere: a session closing or being cancelled and the invoice maturity sweep both drive `NAMED → EXPIRED` and `COUNTERED → EXPIRED`; a newer offer on the same invoice drives `NAMED → SUPERSEDED` and `COUNTERED → SUPERSEDED`; and the dispute cascade drives `NAMED → VOIDED_BY_SUPPRESSION`, `COUNTERED → VOIDED_BY_SUPPRESSION` and `ACCEPTED → VOIDED_BY_SUPPRESSION`."
    Design: Corner/state_machines/cancelling_a_live_session_expires_its_named_offers
    """
    ctx = fx.build_base(
        buyer_overrides={"legal_name": "Cancel Cascade Buyer"},
        program_overrides={"name": "Cancel Cascade Programme"},
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CAN-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CAN-2",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=200_000,
            ),
        ],
        filename="AP-CANCEL.csv",
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    assert len(invoices) == 2, "the file produced two invoices, got {}".format(
        len(invoices)
    )
    invoice_a, invoice_b = invoices[0], invoices[1]

    offer_a = fx.name_offer(
        invoice_a["id"], ctx.session_id, ctx.supplier_id, invoice_a["version"],
        offered_apr_bps=800,
    )
    offer_b = fx.name_offer(
        invoice_b["id"], ctx.session_id, ctx.supplier_id, invoice_b["version"],
        offered_apr_bps=900,
    )
    assert_offer(offer_a, status="NAMED")
    assert_offer(offer_b, status="NAMED")

    cancelled = validate_success(
        api_client.close_session(
            ctx.session_id, f.session_close_payload("CANCEL"), ctx.admin
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED", (
        "mode CANCEL moves a LIVE session to CANCELLED, got {!r}".format(
            cancelled["status"]
        )
    )
    assert cancelled["clearing_apr_bps"] == 0, (
        "the CANCELLED edge writes no clearing rate, so it stays 0, got {}".format(
            cancelled["clearing_apr_bps"]
        )
    )

    sessions, _ = validate_paginated(
        api_client.list_program_sessions(ctx.program_id, ctx.admin)
    )
    persisted = {row["id"]: row for row in sessions}[ctx.session_id]
    assert persisted["status"] == "CANCELLED", (
        "the cancellation must be persisted, got {!r}".format(persisted["status"])
    )
    assert persisted["clearing_apr_bps"] == 0, (
        "clearing_apr_bps stays 0 on a cancelled window, got {}".format(
            persisted["clearing_apr_bps"]
        )
    )

    offers, offers_meta = validate_paginated(
        api_client.list_offers(ctx.admin, session_id=ctx.session_id)
    )
    assert offers_meta["total_count"] == 2, (
        "both offers remain readable after the cascade, got {}".format(
            offers_meta["total_count"]
        )
    )
    assert_created_at_ascending(offers)
    for row in offers:
        assert row["status"] == "EXPIRED", (
            "every NAMED offer on the cancelled session becomes EXPIRED, got "
            "{!r} on offer {}".format(row["status"], row["id"])
        )

    for invoice_id in (invoice_a["id"], invoice_b["id"]):
        reread = validate_success(
            api_client.get_invoice(invoice_id, ctx.admin), 200
        )
        assert_invoice(reread, status="OFFERED")

    program = validate_success(api_client.get_program(ctx.program_id, ctx.admin), 200)
    assert_program(
        program,
        eligible_invoice_count=2,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)


def test_upheld_dispute_matures_the_suppressed_invoice_permanently():
    """UPHELD is the one resolution that does not return the payable to the
    programme: the invoice leaves SUPPRESSED for the terminal MATURED while
    dispute_suppressed deliberately stays true, and because SUPPRESSED invoices
    were never in the adoption denominator the recompute leaves
    eligible_invoice_count at 1 — the non-suppressed sibling — rather than 0.

    PRD 3.4: "A `resolution` of `UPHELD`, likewise available to a platform operator, moves the dispute `OPEN → RESOLVED_UPHELD` and takes the opposite view: the payable genuinely was wrong, so the invoice moves `SUPPRESSED → MATURED`, leaving the discounting programme altogether to be paid on net terms."
    PRD 3.3: "When a row's `suppression_flag` is true, its invoice is created directly in `SUPPRESSED` with `dispute_suppressed` true, and the platform simultaneously raises a dispute on it with `reason_code` `BUYER_FILE_SUPPRESSION`, `status` `OPEN` and `disputed_amount_cents` equal to the full invoice face."
    PRD 3.10: "Note which invoices are excluded from **both** the numerator and the denominator: invoices in `SUPPRESSED` and invoices in `MATURED`."
    Design: Corner/state_machines/upheld_dispute_matures_the_suppressed_invoice_permanently
    """
    ctx = fx.build_base(
        buyer_overrides={"legal_name": "Upheld Dispute Buyer"},
        program_overrides={"name": "Upheld Dispute Programme"},
        onboard=False,
        supplier_overrides={"legal_name": "Upheld Dispute Supply"},
        session_window=None,
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="UPH-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="UPH-2",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=200_000,
                suppression_flag=True,
            ),
        ],
        filename="AP-UPHELD.csv",
    )
    assert ctx.payable_file["ingest_status"] == "ACCEPTED", (
        "no row failed validation, so ingest_status is ACCEPTED, got {!r}".format(
            ctx.payable_file["ingest_status"]
        )
    )
    assert ctx.payable_file["suppressed_row_count"] == 1, (
        "suppressed_row_count counts exactly the flagged accepted rows, got "
        "{}".format(ctx.payable_file["suppressed_row_count"])
    )

    invoices = fx.load_invoices(ctx)
    invoice_a, invoice_b = invoices[0], invoices[1]
    assert_invoice(invoice_a, status="ELIGIBLE", dispute_suppressed=False)
    assert_invoice(
        invoice_b,
        status="SUPPRESSED",
        dispute_suppressed=True,
        face_amount_cents=200_000,
    )

    disputes, disputes_meta = validate_paginated(
        api_client.list_invoice_disputes(invoice_b["id"], ctx.admin)
    )
    assert disputes_meta["total_count"] == 1, (
        "ingestion raised exactly one dispute on the flagged invoice, got "
        "{}".format(disputes_meta["total_count"])
    )
    auto_dispute = disputes[0]
    assert auto_dispute["status"] == "OPEN", (
        "the ingestion dispute is raised in OPEN, got {!r}".format(
            auto_dispute["status"]
        )
    )
    assert auto_dispute["reason_code"] == "BUYER_FILE_SUPPRESSION", (
        "the ingestion cascade uses reason_code BUYER_FILE_SUPPRESSION, got "
        "{!r}".format(auto_dispute["reason_code"])
    )
    assert auto_dispute["disputed_amount_cents"] == 200_000, (
        "a file-suppression dispute carries the full invoice face, got {}".format(
            auto_dispute["disputed_amount_cents"]
        )
    )

    resolved = validate_success(
        api_client.resolve_dispute(
            auto_dispute["id"],
            f.dispute_resolution_payload(
                "UPHELD", "Short shipment confirmed by receiving"
            ),
            PLATFORM_OPS_HEADERS,
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED_UPHELD", (
        "an UPHELD resolution moves the dispute to RESOLVED_UPHELD, got {!r}".format(
            resolved["status"]
        )
    )
    assert resolved["resolution_note"] == "Short shipment confirmed by receiving", (
        "the resolution note is stored on the dispute, got {!r}".format(
            resolved["resolution_note"]
        )
    )

    matured = validate_success(api_client.get_invoice(invoice_b["id"], ctx.admin), 200)
    assert_invoice(matured, status="MATURED", dispute_suppressed=True)
    sibling = validate_success(api_client.get_invoice(invoice_a["id"], ctx.admin), 200)
    assert_invoice(sibling, status="ELIGIBLE", dispute_suppressed=False)

    program = validate_success(api_client.get_program(ctx.program_id, ctx.admin), 200)
    assert_program(
        program,
        eligible_invoice_count=1,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)


def test_withdrawn_dispute_returns_the_invoice_to_eligible():
    """The revert edge fires only because this resolution leaves zero OPEN disputes
    on the invoice: dispute_suppressed clears to false, the invoice returns to
    ELIGIBLE and re-enters the adoption denominator, lifting
    eligible_invoice_count from 1 back to 2 — and it resurrects no offer.

    PRD 3.4: "A `resolution` of `WITHDRAWN`, available to a programme owner, moves the dispute `OPEN → WITHDRAWN`."
    PRD 3.4: "Both of those outcomes mean the payable was not genuinely contested, and both cascade identically: once no dispute on that invoice still holds `status` `OPEN`, the invoice's `dispute_suppressed` returns to false and the invoice moves `SUPPRESSED → ELIGIBLE`."
    PRD 3.4: "This revert edge is what makes the invoice lifecycle non-linear — a payable may be suppressed and released repeatedly — but it does not resurrect anything: offers voided by the suppression stay `VOIDED_BY_SUPPRESSION`, and the supplier must name a fresh rate."
    Design: Corner/state_machines/withdrawn_dispute_returns_the_invoice_to_eligible
    """
    ctx = fx.build_base(
        buyer_overrides={"legal_name": "Withdrawn Dispute Buyer"},
        program_overrides={"name": "Withdrawn Dispute Programme"},
        onboard=False,
        supplier_overrides={"legal_name": "Withdrawn Dispute Supply"},
        session_window=None,
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="WD-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="WD-2",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=200_000,
                suppression_flag=True,
            ),
        ],
        filename="AP-WITHDRAW.csv",
    )
    invoices = fx.load_invoices(ctx)
    invoice_b = invoices[1]
    assert_invoice(invoice_b, status="SUPPRESSED", dispute_suppressed=True)

    before = validate_success(api_client.get_program(ctx.program_id, ctx.admin), 200)
    assert_program(before, eligible_invoice_count=1)

    open_disputes, open_meta = validate_paginated(
        api_client.list_invoice_disputes(invoice_b["id"], ctx.admin, status="OPEN")
    )
    assert open_meta["total_count"] == 1, (
        "exactly one OPEN dispute stands on the suppressed invoice, got {}".format(
            open_meta["total_count"]
        )
    )
    dispute_id = open_disputes[0]["id"]

    withdrawn = fx.resolve_dispute(
        dispute_id, ctx.buyer_id, "WITHDRAWN", "Buyer released the hold"
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        "a WITHDRAWN resolution moves the dispute OPEN -> WITHDRAWN, got {!r}".format(
            withdrawn["status"]
        )
    )

    released = validate_success(api_client.get_invoice(invoice_b["id"], ctx.admin), 200)
    assert_invoice(released, status="ELIGIBLE", dispute_suppressed=False)
    assert_invoice_face_conserved(released)

    program = validate_success(api_client.get_program(ctx.program_id, ctx.admin), 200)
    assert_program(
        program,
        eligible_invoice_count=2,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)

    _offers, offers_meta = validate_paginated(
        api_client.list_offers(ctx.admin, invoice_id=invoice_b["id"])
    )
    assert offers_meta["total_count"] == 0, (
        "the revert resurrects no offer, so the invoice carries none, got "
        "{}".format(offers_meta["total_count"])
    )


def test_clock_sweep_matures_an_overdue_invoice_and_expires_its_offer():
    """Sweep step four fires on the date comparison alone — the clock lands on
    2026-08-11, strictly past the net_due_date of 2026-08-10 — and reaches the live
    NAMED offer, while the still-open session is left LIVE by step two: the offer
    therefore dies of invoice maturity, not of session closure.

    PRD 3.5: "Step four matures invoices: every invoice in `ELIGIBLE` or `OFFERED` whose `net_due_date` has passed becomes `MATURED`, processed in ascending `net_due_date` order and then ascending `created_at` order."
    PRD 3.5: "Maturing an invoice also expires every `NAMED` or `COUNTERED` offer on it, recomputes the programme's `eligible_invoice_count`, `adoption_rate_pct` and `rate_posture`, and increments the invoice's `version`."
    PRD 3.5: "A session becomes `LIVE` only when the new clock instant is at or after its `opens_at` and strictly before its `closes_at`, and only while the governing programme is `OPEN` or `PAUSED`."
    Design: Corner/state_machines/clock_sweep_matures_an_overdue_invoice_and_expires_its_offer
    """
    ctx = fx.build_named_offer(
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-09T00:00:00Z",
        face_cents=100_000,
        net_due_date="2026-08-10T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        buyer_overrides={"legal_name": "Maturity Sweep Buyer"},
        program_overrides={"name": "Maturity Sweep Programme", "min_days_early": 5},
    )
    assert_offer(ctx.offer, status="NAMED", offered_apr_bps=800)
    before = validate_success(api_client.get_invoice(ctx.invoice_id, ctx.admin), 200)
    assert_invoice(before, status="OFFERED")

    swept = validate_success(
        api_client.set_clock("2026-08-11T00:00:00Z", PLATFORM_OPS_HEADERS), 200
    )
    assert swept == {}, (
        "the clock endpoint answers 200 with an empty object in data, got "
        "{!r}".format(swept)
    )

    invoice = validate_success(api_client.get_invoice(ctx.invoice_id, ctx.admin), 200)
    assert_invoice(
        invoice,
        status="MATURED",
        face_covered_cents=0,
        remaining_face_cents=100_000,
        face_amount_cents=100_000,
    )

    offer = validate_success(api_client.get_offer(ctx.offer_id, ctx.admin), 200)
    assert_offer(offer, status="EXPIRED")

    sessions, _ = validate_paginated(
        api_client.list_program_sessions(ctx.program_id, ctx.admin)
    )
    session = {row["id"]: row for row in sessions}[ctx.session_id]
    assert session["status"] == "LIVE", (
        "closes_at 2026-08-31 has not been reached, so the session stays LIVE, got "
        "{!r}".format(session["status"])
    )

    program = validate_success(api_client.get_program(ctx.program_id, ctx.admin), 200)
    assert_program(
        program,
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)


def test_funder_withdrawal_expires_every_active_commitment():
    """Withdrawal is admissible only because encumbered_capital_cents is exactly 0,
    and its cascade expires both tranches — including the future-dated September
    one that was not yet covering the clock date — driving available_capital_cents
    from 1000000 to 0.

    PRD 3.7: "`WITHDRAW` moves either `ACTIVE` or `PAUSED` to the terminal `WITHDRAWN`, and it carries one hard precondition: the funder's `encumbered_capital_cents` must be exactly zero, so a funder cannot walk away while money is still standing behind live payments."
    PRD 3.7: "Withdrawal cascades — every `ACTIVE` tranche of that funder becomes `EXPIRED`, in ascending `created_at` order, each with its own `version` increment — and the funder's `available_capital_cents` is recomputed to 0."
    PRD 3.7: "Committed capital at a date is the sum of `committed_amount_cents` over that funder's tranches whose `status` is `ACTIVE` and whose closed interval contains that date; expired tranches contribute nothing."
    Design: Corner/state_machines/funder_withdrawal_expires_every_active_commitment
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    funder = fx.new_funder(
        legal_name="Exiting Capital Partners",
        capital_limit_cents=2_000_000,
        min_apr_bps=500,
        fee_spread_bps=20,
        max_single_invoice_cents=900_000,
    )
    funder_id = funder["id"]
    tranche_one = fx.add_commitment(
        funder_id,
        committed_amount_cents=1_000_000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-31T00:00:00Z",
    )
    tranche_two = fx.add_commitment(
        funder_id,
        committed_amount_cents=500_000,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
    )

    before = validate_success(
        api_client.get_funder(funder_id, make_funder_headers(funder_id)), 200
    )
    assert before["status"] == "ACTIVE", (
        "the funder is ACTIVE before withdrawing, got {!r}".format(before["status"])
    )
    assert before["encumbered_capital_cents"] == 0, (
        "no early payment names this funder, so encumbrance is 0, got {}".format(
            before["encumbered_capital_cents"]
        )
    )
    assert before["available_capital_cents"] == 1_000_000, (
        "only the August tranche covers the clock date 2026-08-01, so available "
        "capital is 1000000, got {}".format(before["available_capital_cents"])
    )

    withdrawn = validate_success(
        api_client.set_funder_participation(
            funder_id,
            f.funder_participation_payload("WITHDRAW"),
            make_funder_headers(funder_id),
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        "WITHDRAW moves an ACTIVE funder to the terminal WITHDRAWN, got {!r}".format(
            withdrawn["status"]
        )
    )

    tranches, meta = validate_paginated(
        api_client.list_commitments(funder_id, make_funder_headers(funder_id))
    )
    assert meta["total_count"] == 2, (
        "both tranches remain readable after the cascade, got {}".format(
            meta["total_count"]
        )
    )
    assert_created_at_ascending(tranches)
    by_id = {row["id"]: row for row in tranches}
    assert by_id[tranche_one["id"]]["status"] == "EXPIRED", (
        "the tranche covering the clock date becomes EXPIRED, got {!r}".format(
            by_id[tranche_one["id"]]["status"]
        )
    )
    assert by_id[tranche_two["id"]]["status"] == "EXPIRED", (
        "the future-dated tranche is expired by the same cascade, got {!r}".format(
            by_id[tranche_two["id"]]["status"]
        )
    )

    after = validate_success(
        api_client.get_funder(funder_id, make_funder_headers(funder_id)), 200
    )
    assert after["available_capital_cents"] == 0, (
        "expired tranches contribute nothing, so available capital is 0, got "
        "{}".format(after["available_capital_cents"])
    )
    assert after["encumbered_capital_cents"] == 0, (
        "the encumbrance was 0 and stays 0, got {}".format(
            after["encumbered_capital_cents"]
        )
    )


def test_cancelling_a_session_that_holds_an_accepted_offer_returns_invalid_state():
    """The CANCEL edge carries a cross-entity precondition that SETTLE does not —
    zero ACCEPTED offers on the session — so with one accepted award present the
    request is refused and nothing moves: the session stays LIVE at the version it
    already held with no clearing rate, the offer stays ACCEPTED at its accepted
    version and the invoice stays AWARDED.

    PRD 3.5: "Cancellation carries one extra precondition that settlement does not: no offer on the session may currently hold `status` `ACCEPTED`."
    PRD 3.5: "Attempting to cancel a session that has an accepted offer, or to settle a session that is not `LIVE`, is rejected with `ERR_INVALID_STATE`; acting on a session that is already `CLOSED` or `CANCELLED` reports `ERR_ALREADY_TERMINAL`."
    Design: Corner/state_machines/cancelling_a_session_that_holds_an_accepted_offer_returns_invalid_state
    """
    ctx = fx.build_accepted_offer(
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        face_cents=100_000,
        buyer_overrides={"legal_name": "Cancel Guard Buyer"},
        program_overrides={"name": "Cancel Guard Programme"},
    )
    assert_offer(ctx.offer, status="ACCEPTED", accepted_apr_bps=800)
    accepted_version = ctx.offer_version

    before, _ = validate_paginated(
        api_client.list_program_sessions(ctx.program_id, ctx.admin)
    )
    version_before = {row["id"]: row for row in before}[ctx.session_id]["version"]

    resp = api_client.close_session(
        ctx.session_id, f.session_close_payload("CANCEL"), ctx.admin
    )
    validate_error(resp, ERR_INVALID_STATE, 409)

    sessions, _ = validate_paginated(
        api_client.list_program_sessions(ctx.program_id, ctx.admin)
    )
    session = {row["id"]: row for row in sessions}[ctx.session_id]
    assert session["status"] == "LIVE", (
        "the refused cancellation leaves the session LIVE, got {!r}".format(
            session["status"]
        )
    )
    assert session["version"] == version_before, (
        "the refused cancellation mutates no field on the session row, so its "
        "version is unchanged at {}, got {}".format(version_before, session["version"])
    )
    assert session["clearing_apr_bps"] == 0, (
        "no clearing rate is written while the window is still open, got {}".format(
            session["clearing_apr_bps"]
        )
    )

    offer = validate_success(api_client.get_offer(ctx.offer_id, ctx.admin), 200)
    assert_offer(offer, status="ACCEPTED", version=accepted_version)

    invoice = validate_success(api_client.get_invoice(ctx.invoice_id, ctx.admin), 200)
    assert_invoice(invoice, status="AWARDED", accepted_apr_bps=800)
