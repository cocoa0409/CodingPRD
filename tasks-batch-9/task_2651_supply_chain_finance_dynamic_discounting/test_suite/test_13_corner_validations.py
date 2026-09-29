"""Corner-case validation rules of the dynamic-discounting contract.

Every test builds its own state through the public API — the harness restarts
the server before each test, so the database starts empty — and asserts the
exact error identifier, HTTP status and absence of side effects that §2.7 of
the PRD pins down.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BANK_ACCOUNT_NOT_FOUND,
    ERR_BUYER_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_EARLY_PAYMENT_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_SCOPE,
    ERR_FUNDER_NOT_FOUND,
    ERR_INSUFFICIENT_DAYS_EARLY,
    ERR_INVALID_STATE,
    ERR_INVOICE_DISPUTE_SUPPRESSED,
    ERR_INVOICE_NOT_FOUND,
    ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED,
    ERR_OFFER_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
)
from test_helpers.assertions import assert_invoice, assert_offer
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import PLATFORM_OPS_HEADERS


def test_offer_naming_below_min_days_early_is_rejected():
    """Naming a rate whose pay date is fewer days early than the programme's
    floor must be refused at POST /discount-offers with 422, before any offer
    row comes into existence.

    PRD §3.6 states the rule verbatim:
    "Finally, the days-early floor of §3.8 must be satisfied on the pay-date basis, or the submission is rejected with `ERR_INSUFFICIENT_DAYS_EARLY`."

    Design: Corner/validations/offer_naming_below_min_days_early_is_rejected
    """
    ctx = fx.build_eligible_invoice(
        face_cents=50_000,
        net_due_date="2026-08-06T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
    )

    program = get_success_data(api_client.get_program(ctx.program_id, ctx.admin))
    assert program["min_days_early"] == 5, (
        "the programme under test must carry min_days_early 5, got {}".format(
            program["min_days_early"]
        )
    )
    before = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert before["status"] == "ELIGIBLE", (
        "the invoice must start ELIGIBLE, got {}".format(before["status"])
    )
    assert before["net_due_date"].startswith("2026-08-06"), (
        "the invoice must be due 2026-08-06, got {}".format(before["net_due_date"])
    )

    # 2026-08-06 minus 2026-08-03 is 3 whole days, below the floor of 5.
    resp = api_client.create_offer(
        f.offer_payload(
            ctx.invoice_id,
            ctx.session_id,
            ctx.invoice_version,
            offered_apr_bps=900,
            requested_pay_date="2026-08-03T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        ctx.supplier_headers,
    )
    validate_error(resp, ERR_INSUFFICIENT_DAYS_EARLY, 422)

    rows, meta = validate_paginated(
        api_client.list_offers(ctx.admin, session_id=ctx.session_id)
    )
    assert rows == [], "the refused naming must create no offer row, got {}".format(rows)
    assert meta["total_count"] == 0, (
        "meta.total_count must be 0 after the refusal, got {}".format(
            meta["total_count"]
        )
    )

    after = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(after, status="ELIGIBLE", version=before["version"])


def test_offer_naming_at_exactly_the_min_days_early_boundary_succeeds():
    """The days-early floor is inclusive: exactly min_days_early days early is
    accepted, so the offer is created and the invoice moves ELIGIBLE -> OFFERED.

    PRD §2.7 states the rule verbatim:
    "**Sufficient days early** — days early measured on the pay-date basis is at least the programme's `min_days_early`, and the pay date is not after the invoice's `net_due_date`."

    Design: Corner/validations/offer_naming_at_exactly_the_min_days_early_boundary_succeeds
    """
    ctx = fx.build_eligible_invoice(
        face_cents=50_000,
        net_due_date="2026-08-07T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
    )

    program = get_success_data(api_client.get_program(ctx.program_id, ctx.admin))
    assert program["min_days_early"] == 5, (
        "the programme under test must carry min_days_early 5, got {}".format(
            program["min_days_early"]
        )
    )

    # 2026-08-07 minus 2026-08-02 is exactly 5 whole days: the floor is met.
    resp = api_client.create_offer(
        f.offer_payload(
            ctx.invoice_id,
            ctx.session_id,
            ctx.invoice_version,
            offered_apr_bps=900,
            requested_pay_date="2026-08-02T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        ctx.supplier_headers,
    )
    offer = validate_success(resp, 201)
    assert_offer(
        offer,
        status="NAMED",
        offered_apr_bps=900,
        counter_round=0,
        counter_apr_bps=None,
        accepted_apr_bps=0,
        accepted_at=None,
        invoice_id=ctx.invoice_id,
        session_id=ctx.session_id,
        supplier_id=ctx.supplier_id,
    )

    invoice = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(invoice, status="OFFERED", version=ctx.invoice_version + 1)


def test_offer_on_a_dispute_suppressed_invoice_reports_suppression_not_invalid_state():
    """An OPEN dispute both suppresses the invoice (so the priority-11 state
    check is violated) and trips the priority-7 suppression check; the
    dispute-specific 409 must win over the generic ERR_INVALID_STATE.

    PRD §2.7 states the rule verbatim:
    "This check deliberately precedes the generic wrong-state check at position 11, because a suppressed invoice state is a derived consequence of an open dispute and the dispute-specific error is the actionable one."

    Design: Corner/validations/offer_on_a_dispute_suppressed_invoice_reports_suppression_not_invalid_state
    """
    ctx = fx.build_eligible_invoice(
        face_cents=50_000,
        net_due_date="2026-09-30T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
    )

    dispute = fx.raise_dispute(
        ctx.invoice_id, ctx.buyer_id, 10_000, reason_code="SHORT_SHIPMENT"
    )
    assert dispute["status"] == "OPEN", (
        "the dispute must open in OPEN, got {}".format(dispute["status"])
    )

    suppressed = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(suppressed, status="SUPPRESSED", dispute_suppressed=True)

    # The version is re-read after the cascade so the priority-12 stale-version
    # guard cannot fire and steal the rejection.
    fresh_version = suppressed["version"]

    resp = api_client.create_offer(
        f.offer_payload(
            ctx.invoice_id,
            ctx.session_id,
            fresh_version,
            offered_apr_bps=900,
            requested_pay_date="2026-08-05T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        ctx.supplier_headers,
    )
    validate_error(resp, ERR_INVOICE_DISPUTE_SUPPRESSED, 409)
    reported = resp.json()["data"]["error_id"]
    assert reported != ERR_INVALID_STATE, (
        "the suppression check at priority 7 must outrank the generic state check "
        "at priority 11, but the server reported {}".format(reported)
    )

    still_open = get_success_data(
        api_client.list_invoice_disputes(ctx.invoice_id, ctx.admin)
    )
    assert [d["status"] for d in still_open] == ["OPEN"], (
        "the refused naming must leave the single dispute OPEN, got {}".format(
            [d["status"] for d in still_open]
        )
    )

    rows, meta = validate_paginated(
        api_client.list_offers(ctx.admin, invoice_id=ctx.invoice_id)
    )
    assert rows == [], "no offer row may exist on the suppressed invoice, got {}".format(
        rows
    )
    assert meta["total_count"] == 0, (
        "meta.total_count must be 0 on the suppressed invoice, got {}".format(
            meta["total_count"]
        )
    )


def test_body_foreign_keys_that_do_not_resolve_are_rejected():
    """Each unresolvable top-level body foreign key must be reported with its own
    404 identifier, never with the priority-5 scope 403.

    PRD §2.7 states the rule verbatim:
    "**Body foreign-key existence** — every top-level foreign key supplied in the request body resolves to a live row, covering `program_id`, `session_id`, `supplier_id`, `bank_account_id`, `invoice_id`, `offer_id` and `funder_id`, and reported with the same not-found identifiers as check 4."
    and it pins the interaction with the scope check:
    "Because a scope test is only meaningful once the row exists, it is evaluated strictly after the addressed identifier has resolved: an identifier that resolves to no row is the 404 of check 4 or check 6, never this 403."

    Design: Corner/validations/body_foreign_keys_that_do_not_resolve_are_rejected
    """
    ctx = fx.build_eligible_invoice(
        face_cents=50_000,
        net_due_date="2026-09-30T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
    )
    before = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))

    # (1) buyer_id on POST /buyer-programs
    resp_buyer = api_client.create_program(
        f.program_payload(NON_EXISTENT_UUID, name="Orphan Programme"), ctx.admin
    )
    validate_error(resp_buyer, ERR_BUYER_NOT_FOUND, 404)

    # (2) program_id on POST /auction-sessions
    resp_program = api_client.create_session(
        f.session_payload(
            NON_EXISTENT_UUID,
            opens_at="2026-08-10T00:00:00Z",
            closes_at="2026-08-20T00:00:00Z",
        ),
        ctx.admin,
    )
    validate_error(resp_program, ERR_PROGRAM_NOT_FOUND, 404)

    # (3) session_id on POST /discount-offers — the invoice resolves, the session does not
    resp_session = api_client.create_offer(
        f.offer_payload(
            ctx.invoice_id,
            NON_EXISTENT_UUID,
            ctx.invoice_version,
            offered_apr_bps=900,
            requested_pay_date="2026-08-05T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        ctx.supplier_headers,
    )
    validate_error(resp_session, ERR_SESSION_NOT_FOUND, 404)

    # (4) invoice_id on POST /discount-offers — the session resolves, the invoice does not
    resp_invoice = api_client.create_offer(
        f.offer_payload(
            NON_EXISTENT_UUID,
            ctx.session_id,
            ctx.invoice_version,
            offered_apr_bps=900,
            requested_pay_date="2026-08-05T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        ctx.supplier_headers,
    )
    validate_error(resp_invoice, ERR_INVOICE_NOT_FOUND, 404)

    for label, resp in (
        ("buyer_id", resp_buyer),
        ("program_id", resp_program),
        ("session_id", resp_session),
        ("invoice_id", resp_invoice),
    ):
        reported = resp.json()["data"]["error_id"]
        assert reported != ERR_FORBIDDEN_RESOURCE_SCOPE, (
            "an unresolvable {} is a 404, never the scope 403, but the server "
            "reported {}".format(label, reported)
        )
        assert resp.status_code == 404, (
            "an unresolvable {} must carry HTTP 404, got {}".format(
                label, resp.status_code
            )
        )

    after = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(after, status="ELIGIBLE", version=before["version"])

    programs, meta = validate_paginated(
        api_client.list_buyer_programs(ctx.buyer_id, ctx.admin)
    )
    assert meta["total_count"] == 1, (
        "the orphan-buyer create must have persisted nothing, so the buyer keeps "
        "exactly 1 programme, got {}".format(meta["total_count"])
    )
    assert [p["id"] for p in programs] == [ctx.program_id], (
        "the only programme of this buyer must still be {}, got {}".format(
            ctx.program_id, [p["id"] for p in programs]
        )
    )


def test_path_parameters_that_do_not_resolve_are_rejected():
    """Six collections addressed by an id that was never minted must each report
    their own not-found identifier, on reads and on action endpoints alike, and
    the lookup must precede every body-shape and business rule.

    PRD §2.7 states the rule verbatim:
    "**Path-parameter existence** — every path parameter resolves to a live row, validated left to right along the path."
    and §2.9 confirms it for reverse lookups:
    "When a path carries more than one segment that must resolve, resolution proceeds strictly left to right and the first unresolved segment decides the error."

    Design: Corner/validations/path_parameters_that_do_not_resolve_are_rejected
    """
    # An empty system: only the logical clock is parked, no row of any kind exists.
    fx.set_clock(DEFAULT_CLOCK_UTC)

    resp_buyer = api_client.get_buyer(NON_EXISTENT_UUID, PLATFORM_OPS_HEADERS)
    validate_error(resp_buyer, ERR_BUYER_NOT_FOUND, 404)

    resp_offer = api_client.get_offer(NON_EXISTENT_UUID, PLATFORM_OPS_HEADERS)
    validate_error(resp_offer, ERR_OFFER_NOT_FOUND, 404)

    resp_funder = api_client.get_funder(NON_EXISTENT_UUID, PLATFORM_OPS_HEADERS)
    validate_error(resp_funder, ERR_FUNDER_NOT_FOUND, 404)

    resp_payment = api_client.get_early_payment(NON_EXISTENT_UUID, PLATFORM_OPS_HEADERS)
    validate_error(resp_payment, ERR_EARLY_PAYMENT_NOT_FOUND, 404)

    # A well-formed resolution on a dispute that does not exist still 404s.
    resp_dispute = api_client.resolve_dispute(
        NON_EXISTENT_UUID,
        f.dispute_resolution_payload("UPHELD"),
        PLATFORM_OPS_HEADERS,
    )
    validate_error(resp_dispute, ERR_DISPUTE_NOT_FOUND, 404)
    reported_dispute = resp_dispute.json()["data"]["error_id"]
    assert reported_dispute not in (ERR_INVALID_STATE, ERR_ALREADY_TERMINAL), (
        "the path lookup outranks every state rule, so a missing dispute is "
        "ERR_DISPUTE_NOT_FOUND, got {}".format(reported_dispute)
    )

    # A well-formed six-digit code on a bank account that does not exist still 404s.
    resp_bank = api_client.confirm_micro_deposit(
        NON_EXISTENT_UUID, f.micro_deposit_payload("021432"), PLATFORM_OPS_HEADERS
    )
    validate_error(resp_bank, ERR_BANK_ACCOUNT_NOT_FOUND, 404)
    reported_bank = resp_bank.json()["data"]["error_id"]
    assert reported_bank != ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED, (
        "the path lookup outranks the attempt-budget rule, so a missing bank "
        "account is ERR_BANK_ACCOUNT_NOT_FOUND, got {}".format(reported_bank)
    )
