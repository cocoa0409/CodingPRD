"""Corner-case coverage of the role model of the dynamic-discounting contract.

Five distinct refusals and permissions are exercised here: the BuyerAdmin /
BuyerTreasury segregation of duties, which splits rate discovery from cash
movement across two roles that authenticate as the very same corporate
``X-User-ID``; the one endpoint whose permitted role depends on the addressed
row's current status (offer acceptance); the shared operations PlatformOps
performs as back office; and the resource-scope gate, which refuses a caller
holding an accepted role but not the addressed row's ownership with
ERR_FORBIDDEN_RESOURCE_SCOPE rather than ERR_UNAUTHORIZED.

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
    ERR_FORBIDDEN_RESOURCE_SCOPE,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_buyer,
    assert_cash_breakdown,
    assert_invoice,
    assert_offer,
    assert_payment,
    assert_payment_axes,
    assert_program,
    assert_supplier_axes,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
    make_platform_ops_headers,
    make_supplier_headers,
)


def test_buyer_treasury_cannot_open_a_program():
    """Programme configuration is BuyerAdmin-exclusive. The treasury officer of
    the very same buyer — same ``X-User-ID``, different ``X-User-Role`` — is
    refused with 403 ERR_UNAUTHORIZED even though the programme really is in
    DRAFT and the transition would otherwise be legal, and the programme is left
    in DRAFT at version 1. The identical call as BuyerAdmin then succeeds, so the
    refusal was about the role and not about the buyer.

    PRD §2.1: "When the headers are well formed but the acting role is not among the roles authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.8: "Creating a programme, opening it, changing its lifecycle status, scheduling an auction session, closing an auction session early, ingesting an approved-payables file, countering an offer, and accepting an offer that is in `NAMED` are exclusive to `BuyerAdmin`."
    PRD §3.1: "Opening a programme moves it from `DRAFT` to `OPEN`."
    Design: Corner/rbac/buyer_treasury_cannot_open_a_program
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Role Split Buyer", credit_limit_cents=100_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    treasury = make_buyer_treasury_headers(buyer_id)

    program = fx.new_program(buyer_id, name="Role Split Programme")
    program_id = program["id"]
    assert_program(program, status="DRAFT", version=1)

    validate_error(api_client.open_program(program_id, treasury), ERR_UNAUTHORIZED, 403)

    unchanged = validate_success(api_client.get_program(program_id, admin), 200)
    assert_program(unchanged, id=program_id, status="DRAFT", version=1)
    assert unchanged["updated_at"] == program["updated_at"], (
        "the refused open must not refresh updated_at: {!r} -> {!r}".format(
            program["updated_at"], unchanged["updated_at"]
        )
    )

    # The very same call, the very same X-User-ID, only the role differs.
    opened = validate_success(api_client.open_program(program_id, admin), 200)
    assert_program(opened, id=program_id, status="OPEN", version=2)


def test_offer_acceptance_role_depends_on_the_offers_current_status():
    """POST /discount-offers/{id}/accept is the one endpoint whose permitted role
    is decided by the addressed row's status. A Supplier reaching for a NAMED
    offer and a BuyerAdmin reaching for a COUNTERED offer are both refused with
    403 ERR_UNAUTHORIZED — not ERR_INVALID_STATE, because each offer *is* in a
    status that admits acceptance, just not by that caller — and the right-side
    Supplier acceptance of the COUNTERED offer then locks the buyer's countered
    rate rather than the supplier's original bid.

    PRD §2.1: "Acceptance of a discount offer is permitted to two roles, but which of the two may act depends on the offer's current negotiation state: a `BuyerAdmin` may accept an offer that is in `NAMED`, a `Supplier` may accept an offer that is in `COUNTERED`, and neither may accept the other's."
    PRD §2.1: "A `BuyerAdmin` attempting to accept a `COUNTERED` offer, or a `Supplier` attempting to accept a `NAMED` offer, is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.6: "From `COUNTERED`, only the supplier may accept — the supplier is taking the buyer's counter — and the locked `accepted_apr_bps` is copied from `counter_apr_bps` instead."
    Design: Corner/rbac/offer_acceptance_role_depends_on_the_offers_current_status
    """
    ctx = fx.build_base()
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id, invoice_number="RBA-A", line_amount_cents=50_000
            ),
            f.payable_row(
                ctx.supplier_id, invoice_number="RBA-B", line_amount_cents=60_000
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    assert len(invoices) == 2, (
        "the file must have produced exactly two invoices, got {}".format(len(invoices))
    )
    invoice_a, invoice_b = invoices[0], invoices[1]
    assert invoice_a["face_amount_cents"] == 50_000
    assert invoice_b["face_amount_cents"] == 60_000

    offer_a = fx.name_offer(
        invoice_a["id"], ctx.session_id, ctx.supplier_id, invoice_a["version"],
        offered_apr_bps=900,
    )
    offer_b = fx.name_offer(
        invoice_b["id"], ctx.session_id, ctx.supplier_id, invoice_b["version"],
        offered_apr_bps=900,
    )

    # A counter must be strictly greater than the offer's current offered_apr_bps
    # and at most the programme ceiling of 1200 (PRD §3.6).
    countered = validate_success(
        api_client.counter_offer(offer_b["id"], f.counter_payload(1000), ctx.admin), 200
    )
    assert_offer(countered, id=offer_b["id"], status="COUNTERED", counter_apr_bps=1000)
    assert validate_success(
        api_client.get_offer(offer_a["id"], ctx.admin), 200
    )["status"] == "NAMED", "offer_a must still be NAMED before the trigger"

    # Wrong side 1: the Supplier reaching for its own NAMED offer.
    validate_error(
        api_client.accept_offer(offer_a["id"], ctx.supplier_headers),
        ERR_UNAUTHORIZED,
        403,
    )
    # Wrong side 2: the BuyerAdmin reaching for the COUNTERED offer.
    validate_error(
        api_client.accept_offer(offer_b["id"], ctx.admin), ERR_UNAUTHORIZED, 403
    )

    # Right side: the Supplier accepts the buyer's counter.
    accepted = validate_success(
        api_client.accept_offer(offer_b["id"], ctx.supplier_headers), 200
    )
    assert_offer(
        accepted,
        id=offer_b["id"],
        status="ACCEPTED",
        accepted_apr_bps=1000,
    )
    assert accepted["accepted_at"] is not None, (
        "acceptance stamps accepted_at from the logical clock, got None"
    )
    assert_invoice(
        validate_success(api_client.get_invoice(invoice_b["id"], ctx.admin), 200),
        id=invoice_b["id"],
        status="AWARDED",
        accepted_apr_bps=1000,
    )

    # The two refusals changed nothing on the other offer or its invoice.
    assert_offer(
        validate_success(api_client.get_offer(offer_a["id"], ctx.admin), 200),
        id=offer_a["id"],
        status="NAMED",
        version=offer_a["version"],
        accepted_apr_bps=0,
    )
    assert_invoice(
        validate_success(api_client.get_invoice(invoice_a["id"], ctx.admin), 200),
        id=invoice_a["id"],
        status="OFFERED",
    )


def test_buyer_admin_cannot_reserve_an_early_payment_segregation_of_duties():
    """Rate discovery and cash movement are split across two roles that share one
    ``X-User-ID`` — the buyer's own row id. The BuyerAdmin that accepted the rate
    cannot reserve the money, and the BuyerTreasury that reserves the money
    cannot counter an offer; both refusals are 403 ERR_UNAUTHORIZED. Because the
    role gate sits at position 2 and the source-state gate at position 11, the
    treasury's counter attempt on an already-ACCEPTED offer still reports the
    role error rather than ERR_INVALID_STATE. The identical treasury reservation
    then succeeds, proving the payload was never the problem.

    PRD §1: "A programme owner may negotiate a rate but never reserve the money; a treasury officer may move the money but never negotiate the rate."
    PRD §2.8: "Reserving an early payment, executing it, and recording its accounting classification are exclusive to `BuyerTreasury`."
    PRD §2.7: "Every check below is evaluated in the numbered order given, and the first violated check decides both the `error_id` and the HTTP status; later checks are never reached."
    Design: Corner/rbac/buyer_admin_cannot_reserve_an_early_payment_segregation_of_duties
    """
    ctx = fx.build_accepted_offer()
    offer_version = ctx.offer_version
    face_cents = ctx.invoice["face_amount_cents"]
    assert face_cents == 100_000, "the fixture invoice face must be 100000 cents"

    # days early on the pay-date basis: 2026-09-30 minus 2026-08-05 == 56.
    expected_days_early = 56
    expected_discount = f.expected_discount_cents(face_cents, 900, expected_days_early)
    assert expected_discount == 1_400, (
        "100000 * 900 * 56 / (10000 * 360) is exactly 1400, got {}".format(
            expected_discount
        )
    )
    expected_net = face_cents - expected_discount
    assert expected_net == 98_600

    before = validate_success(api_client.get_buyer(ctx.buyer_id, ctx.treasury), 200)
    assert_buyer(before, id=ctx.buyer_id, credit_used_cents=0)

    # Refusal 1: POST /early-payments is BuyerTreasury-exclusive.
    validate_error(
        api_client.create_early_payment(
            f.early_payment_payload(ctx.offer_id, offer_version), ctx.admin
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # Refusal 2: countering is BuyerAdmin-exclusive, and the role gate outranks
    # the state gate even though the offer is already ACCEPTED.
    validate_error(
        api_client.counter_offer(ctx.offer_id, f.counter_payload(1000), ctx.treasury),
        ERR_UNAUTHORIZED,
        403,
    )

    # Neither refusal wrote anything.
    assert_offer(
        validate_success(api_client.get_offer(ctx.offer_id, ctx.admin), 200),
        id=ctx.offer_id,
        status="ACCEPTED",
        version=offer_version,
    )
    assert_buyer(
        validate_success(api_client.get_buyer(ctx.buyer_id, ctx.treasury), 200),
        id=ctx.buyer_id,
        credit_used_cents=0,
    )

    # The treasury officer performs the very same reservation successfully.
    payment = validate_success(
        api_client.create_early_payment(
            f.early_payment_payload(ctx.offer_id, offer_version), ctx.treasury
        ),
        201,
    )
    assert_payment(
        payment,
        offer_id=ctx.offer_id,
        invoice_id=ctx.invoice_id,
        funding_source="BUYER_SELF",
        funder_id=None,
        face_covered_cents=face_cents,
        version=1,
    )
    assert_payment_axes(
        payment,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert_cash_breakdown(
        payment,
        days_early=expected_days_early,
        discount_amount_cents=expected_discount,
        funder_fee_cents=0,
        net_payment_cents=expected_net,
    )
    assert_buyer(
        validate_success(api_client.get_buyer(ctx.buyer_id, ctx.treasury), 200),
        id=ctx.buyer_id,
        credit_used_cents=expected_net,
    )


def test_platform_ops_performs_the_shared_supplier_and_funder_operations():
    """Every operation PlatformOps shares with another role must actually work
    when the back office performs it: onboarding submit, bank-account
    registration, micro-deposit confirmation and capital-tranche commitment. The
    fork-join behaves identically too — after the back office confirms the deposit
    the supplier is still VERIFYING with ``bank_status`` VERIFIED and a null
    ``payment_ready_at``, and only the PlatformOps-exclusive identity
    adjudication closes the join. PlatformOps still cannot create a programme,
    which is BuyerAdmin-exclusive, and its opaque operator identifier is never
    compared to any entity's id.

    PRD §2.1: "When `X-User-Role` is `PlatformOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`, and a platform operator has read access to every collection."
    PRD §2.8: "Submitting supplier onboarding, adding a bank account and confirming a micro-deposit code are open to `Supplier` and `PlatformOps`."
    PRD §2.8: "Changing funder participation and committing a capital tranche are open to `Funder` and `PlatformOps`."
    PRD §3.2: "The platform pushes a micro deposit carrying a six-digit `micro_deposit_code`, and that code is fully determined by the account itself: it is the zero-padded decimal formed by concatenating the last three digits of `routing_number` with the first three digits of `account_last4`."
    PRD §3.2: "Whenever `idv_status` is `PASSED`, `bank_status` is `VERIFIED` and `sanctions_hold` is false, the supplier moves `VERIFYING → ACTIVE` and `payment_ready_at` is stamped with the logical-clock instant; the join is reachable from either branch completing last, and the supplier's `version` increments."
    Design: Corner/rbac/platform_ops_performs_the_shared_supplier_and_funder_operations
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    ops = make_platform_ops_headers("ops-back-office-7")

    buyer = fx.new_buyer(legal_name="Back Office Buyer", credit_limit_cents=100_000_000)
    buyer_id = buyer["id"]
    supplier = fx.new_supplier(legal_name="Back Office Supply", tax_id_last4="2121")
    supplier_id = supplier["id"]
    funder = fx.new_funder(legal_name="Back Office Capital")
    funder_id = funder["id"]
    assert_supplier_axes(
        supplier,
        onboarding_status="DRAFT",
        idv_status="NOT_STARTED",
        bank_status="NOT_STARTED",
    )

    # Shared operation 1: onboarding submit.
    submitted = validate_success(api_client.submit_onboarding(supplier_id, ops), 200)
    assert_supplier_axes(
        submitted,
        onboarding_status="VERIFYING",
        idv_status="PENDING",
        bank_status="NOT_STARTED",
    )

    # Shared operation 2: bank-account registration.
    bank = validate_success(
        api_client.create_bank_account(
            supplier_id, f.bank_account_payload("011000015", "8899"), ops
        ),
        201,
    )
    expected_code = f.expected_micro_deposit_code("011000015", "8899")
    assert expected_code == "015889", (
        "the code is routing '015' followed by account '889', got {!r}".format(
            expected_code
        )
    )
    assert bank["micro_deposit_code"] == expected_code, (
        "micro_deposit_code should be {!r}, got {!r}".format(
            expected_code, bank["micro_deposit_code"]
        )
    )
    assert bank["status"] == "MICRO_DEPOSIT_SENT", (
        "a new account is persisted in MICRO_DEPOSIT_SENT, got {!r}".format(
            bank["status"]
        )
    )

    # Shared operation 3: micro-deposit confirmation.
    confirmed = validate_success(
        api_client.confirm_micro_deposit(
            bank["id"], f.micro_deposit_payload(expected_code), ops
        ),
        200,
    )
    assert confirmed["status"] == "VERIFIED", (
        "a matching code moves the account to VERIFIED, got {!r}".format(
            confirmed["status"]
        )
    )
    assert confirmed["micro_deposit_attempts"] == 1, (
        "a matching code still increments micro_deposit_attempts to 1, got {}".format(
            confirmed["micro_deposit_attempts"]
        )
    )
    half_joined = validate_success(api_client.get_supplier(supplier_id, ops), 200)
    assert_supplier_axes(
        half_joined,
        onboarding_status="VERIFYING",
        idv_status="PENDING",
        bank_status="VERIFIED",
    )
    assert half_joined["verified_account_last4"] == "8899", (
        "verified_account_last4 is set from the account, got {!r}".format(
            half_joined["verified_account_last4"]
        )
    )
    assert half_joined["payment_ready_at"] is None, (
        "the identity axis is still open, so payment_ready_at must stay null, got {!r}".format(
            half_joined["payment_ready_at"]
        )
    )

    # Shared operation 4: committing a capital tranche.
    tranche = validate_success(
        api_client.create_commitment(
            funder_id,
            f.commitment_payload(
                committed_amount_cents=60_000_000,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-30T00:00:00Z",
            ),
            ops,
        ),
        201,
    )
    assert tranche["status"] == "ACTIVE", (
        "tranches are persisted in ACTIVE, got {!r}".format(tranche["status"])
    )
    funder_after = validate_success(api_client.get_funder(funder_id, ops), 200)
    assert funder_after["encumbered_capital_cents"] == 0
    assert funder_after["available_capital_cents"] == 60_000_000, (
        "available capital is the committed figure at the clock date minus the "
        "encumbrance, expected 60000000, got {}".format(
            funder_after["available_capital_cents"]
        )
    )

    # PlatformOps-exclusive: identity adjudication closes the join.
    adjudicated = validate_success(
        api_client.adjudicate_idv(supplier_id, f.idv_payload("PASSED", 90), ops), 200
    )
    assert_supplier_axes(
        adjudicated,
        onboarding_status="ACTIVE",
        idv_status="PASSED",
        bank_status="VERIFIED",
    )
    assert adjudicated["payment_ready_at"] is not None, (
        "the join stamps payment_ready_at from the logical clock, got None"
    )
    assert adjudicated["idv_verified_at"] is not None, (
        "a PASSED decision stamps idv_verified_at, got None"
    )
    assert adjudicated["identity_score"] == 90

    # BuyerAdmin-exclusive: programme creation is refused to the back office.
    validate_error(
        api_client.create_program(
            f.minimal_program_payload(buyer_id, name="Back Office Programme"), ops
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    programs, programs_meta = validate_paginated(
        api_client.list_buyer_programs(buyer_id, ops)
    )
    assert programs_meta["total_count"] == 0, (
        "the refused programme create must not have persisted a row, got "
        "total_count {}".format(programs_meta["total_count"])
    )
    assert programs == [], "no programme may exist, got {!r}".format(programs)


def test_buyer_admin_of_another_buyer_cannot_read_this_program():
    """Both callers hold a role the endpoint accepts, so the refusal is not about
    the role but about ownership: a BuyerAdmin reading another buyer's programme
    and a Supplier reading another supplier's record are each refused with 403
    ERR_FORBIDDEN_RESOURCE_SCOPE — distinct from the 403 ERR_UNAUTHORIZED a wrong
    role earns and from the 404 a non-existent identifier earns, because the scope
    test is evaluated strictly after the addressed identifier has resolved. The
    identical read of the caller's own programme succeeds.

    PRD §2.1: "When `X-User-Role` is `BuyerAdmin`, `X-User-ID` is the `id` of the acting buyer, and ownership checks on any resource that references a buyer compare the resource's buyer foreign key to `X-User-ID`."
    PRD §2.1: "When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting supplier, and ownership checks compare the addressed resource's supplier foreign key to `X-User-ID`."
    PRD §2.7: "Because a scope test is only meaningful once the row exists, it is evaluated strictly after the addressed identifier has resolved: an identifier that resolves to no row is the 404 of check 4 or check 6, never this 403."
    Design: Corner/rbac/buyer_admin_of_another_buyer_cannot_read_this_program
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer_1 = fx.new_buyer(legal_name="Scope Buyer One", credit_limit_cents=100_000_000)
    buyer_2 = fx.new_buyer(legal_name="Scope Buyer Two", credit_limit_cents=100_000_000)
    program_1 = fx.new_program(buyer_1["id"], name="Scope Programme One")
    program_2 = fx.new_program(buyer_2["id"], name="Scope Programme Two")
    supplier_1 = fx.new_supplier(legal_name="Scope Supply One", tax_id_last4="2222")
    supplier_2 = fx.new_supplier(legal_name="Scope Supply Two", tax_id_last4="2323")

    admin_1 = make_buyer_admin_headers(buyer_1["id"])

    # A BuyerAdmin is an authorised role on GET /buyer-programs/{id}; it is the
    # buyer_id on the addressed programme that does not match X-User-ID.
    validate_error(
        api_client.get_program(program_2["id"], admin_1),
        ERR_FORBIDDEN_RESOURCE_SCOPE,
        403,
    )
    # A Supplier is an authorised role on GET /suppliers/{id}; the addressed
    # supplier's own id does not match X-User-ID.
    validate_error(
        api_client.get_supplier(
            supplier_2["id"], make_supplier_headers(supplier_1["id"])
        ),
        ERR_FORBIDDEN_RESOURCE_SCOPE,
        403,
    )

    # The identical read of the caller's own programme is permitted.
    own = validate_success(api_client.get_program(program_1["id"], admin_1), 200)
    assert_program(own, id=program_1["id"], status="DRAFT", version=1)

    # Neither refusal wrote anything on the rows it was refused.
    other = validate_success(
        api_client.get_program(program_2["id"], PLATFORM_OPS_HEADERS), 200
    )
    assert_program(other, id=program_2["id"], status="DRAFT", version=1)
    assert other["updated_at"] == program_2["updated_at"], (
        "a refused cross-buyer read must not refresh updated_at: {!r} -> {!r}".format(
            program_2["updated_at"], other["updated_at"]
        )
    )
    other_supplier = validate_success(
        api_client.get_supplier(supplier_2["id"], PLATFORM_OPS_HEADERS), 200
    )
    assert other_supplier["version"] == supplier_2["version"] == 1, (
        "a refused cross-supplier read must not advance the version, got {}".format(
            other_supplier["version"]
        )
    )
