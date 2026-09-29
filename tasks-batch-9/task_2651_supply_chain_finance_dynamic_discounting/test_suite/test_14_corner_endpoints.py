"""Corner-case endpoint behaviour of the dynamic-discounting contract.

Bulk ingestion that skips rather than rolls back, the widest configuration
cascade, the two-basis analytics read model, reverse-reachability reads, the
temporal precondition on settlement confirmation and empty-but-successful
filtered lists. Every test builds its own state through the public API because
the harness restarts the server — and empties the database — before each test.
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
    ERR_FILE_TOTALS_MISMATCH,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_analytics,
    assert_cash_breakdown,
    assert_created_at_ascending,
    assert_invoice,
    assert_pagination_meta,
    assert_payment_axes,
    assert_program,
    assert_two_decimal_percentage,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC, DEFAULT_LIMIT, DEFAULT_OFFSET
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_supplier_headers,
)


def test_payable_file_with_one_duplicate_row_partially_accepts():
    """Ingestion skips the offending row instead of rolling the file back: the
    two good rows become invoices, the file lands in PARTIALLY_ACCEPTED and the
    control totals reconcile against the accepted rows only.

    PRD §3.3 states the row-level rule verbatim:
    "A row whose `invoice_number` duplicates an invoice number already present for the same combination of programme and supplier is rejected with reason `DUPLICATE_INVOICE_NUMBER`; `invoice_number` is between 1 and 40 characters and is unique per programme-and-supplier pair."
    and the derived file figures:
    "`accepted_row_count` is the number of rows that produced an invoice; `rejected_row_count` is the number that failed row-level validation and produced none; `computed_total_cents` is the sum of the computed face over the accepted rows, so rejected rows contribute nothing to it; and `rejection_reasons` is an ordered array of objects, each pairing a `row_index` — the zero-based position of the failing row inside the submitted `rows` array — with a `reason` drawn from the five values above, sorted by `row_index` ascending."
    and the file outcome:
    "The file's `ingest_status` is derived rather than supplied, and it takes one of three values: `ACCEPTED` when `rejected_row_count` is zero, `REJECTED` when `accepted_row_count` is zero, and `PARTIALLY_ACCEPTED` in every other case."
    and the reconciliation basis:
    "Rows rejected for row-level reasons are excluded from both sides of the comparison, so a file whose rejected rows account for exactly the difference between the buyer's raw extract and the platform's accepted set still passes."

    Design: Corner/endpoints/payable_file_with_one_duplicate_row_partially_accepts
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer()
    admin = make_buyer_admin_headers(buyer["id"])
    program = fx.new_open_program(buyer["id"])
    supplier = fx.new_supplier()

    rows = [
        f.payable_row(
            supplier["id"],
            invoice_number="DUP-1",
            approval_date="2026-07-20T00:00:00Z",
            net_due_date="2026-09-30T00:00:00Z",
            line_amount_cents=50_000,
        ),
        f.payable_row(
            supplier["id"],
            invoice_number="DUP-1",
            approval_date="2026-07-20T00:00:00Z",
            net_due_date="2026-09-30T00:00:00Z",
            line_amount_cents=70_000,
        ),
        f.payable_row(
            supplier["id"],
            invoice_number="DUP-3",
            approval_date="2026-07-20T00:00:00Z",
            net_due_date="2026-09-30T00:00:00Z",
            line_amount_cents=30_000,
        ),
    ]

    # Declared over the accepted rows only: 2 rows totalling 80000 cents.
    resp = api_client.create_payable_file(
        f.payable_file_payload(
            program["id"],
            rows,
            filename="AP-PARTIAL.csv",
            declared_row_count=2,
            declared_total_cents=80_000,
        ),
        admin,
    )
    reported = resp.json().get("data", {})
    assert reported.get("error_id") != ERR_FILE_TOTALS_MISMATCH, (
        "the declared totals reconcile against the two accepted rows, so the "
        "control-total check must not fire; got {}".format(reported.get("error_id"))
    )
    payable_file = validate_success(resp, 201)

    assert payable_file["ingest_status"] == "PARTIALLY_ACCEPTED", (
        "one accepted-and-one-rejected mix is PARTIALLY_ACCEPTED, got {}".format(
            payable_file["ingest_status"]
        )
    )
    assert payable_file["accepted_row_count"] == 2, (
        "two rows produced invoices, got accepted_row_count {}".format(
            payable_file["accepted_row_count"]
        )
    )
    assert payable_file["rejected_row_count"] == 1, (
        "exactly one row was rejected, got rejected_row_count {}".format(
            payable_file["rejected_row_count"]
        )
    )
    assert payable_file["computed_total_cents"] == 80_000, (
        "computed_total_cents sums the accepted rows only (50000 + 30000), got "
        "{}".format(payable_file["computed_total_cents"])
    )
    assert payable_file["suppressed_row_count"] == 0, (
        "no row carried suppression_flag, got suppressed_row_count {}".format(
            payable_file["suppressed_row_count"]
        )
    )

    reasons = payable_file["rejection_reasons"]
    assert len(reasons) == 1, (
        "exactly one rejection must be recorded, got {}".format(reasons)
    )
    assert reasons[0]["row_index"] == 1, (
        "row_index is the zero-based position of the duplicate row, got {}".format(
            reasons[0]["row_index"]
        )
    )
    assert reasons[0]["reason"] == "DUPLICATE_INVOICE_NUMBER", (
        "the second DUP-1 row fails on the per-programme-and-supplier uniqueness "
        "rule, got reason {}".format(reasons[0]["reason"])
    )

    invoices, meta = validate_paginated(
        api_client.list_invoices(admin, file_id=payable_file["id"])
    )
    assert meta["total_count"] == 2, (
        "only the two accepted rows may have produced invoices, got "
        "total_count {}".format(meta["total_count"])
    )
    assert_created_at_ascending(invoices)
    assert [inv["invoice_number"] for inv in invoices] == ["DUP-1", "DUP-3"], (
        "invoices appear in submitted-row order, got {}".format(
            [inv["invoice_number"] for inv in invoices]
        )
    )
    faces = [inv["face_amount_cents"] for inv in invoices]
    assert faces == [50_000, 30_000], (
        "the accepted faces are 50000 then 30000, got {}".format(faces)
    )
    assert 70_000 not in faces, (
        "the rejected row must have created no invoice, yet a face of 70000 "
        "exists: {}".format(faces)
    )
    for invoice in invoices:
        assert_invoice(invoice, status="ELIGIBLE", dispute_suppressed=False)


def test_program_close_from_paused_cascades_to_sessions_and_the_buyer():
    """CLOSE is reachable from PAUSED, and closing the buyer's only non-terminal
    programme cancels its SCHEDULED session and suspends the buyer in one call.

    PRD §3.1 states the edge and the version rule verbatim:
    "`CLOSE` moves either `OPEN` or `PAUSED` to `CLOSED`, which is terminal."
    "Each of the three actions increments the programme's `version` by one."
    and the two cascade hops:
    "First, every auction session of this programme whose `status` is `SCHEDULED` or `LIVE` becomes `CANCELLED`, processed in ascending `created_at` order."
    "Third, if after this close no programme of that buyer holds `status` `DRAFT`, `OPEN` or `PAUSED`, the buyer itself moves from `ACTIVE` to `SUSPENDED`."
    "Each of those cascaded rows has its own `version` incremented and its `updated_at` refreshed."

    Design: Corner/endpoints/program_close_from_paused_cascades_to_sessions_and_the_buyer
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer()
    admin = make_buyer_admin_headers(buyer["id"])

    created = fx.new_program(buyer["id"])
    assert created["version"] == 1, (
        "a freshly created programme carries version 1, got {}".format(
            created["version"]
        )
    )
    assert created["status"] == "DRAFT", (
        "a new programme opens in DRAFT, got {}".format(created["status"])
    )
    program_id = created["id"]

    opened = fx.open_program(program_id, buyer["id"])
    assert (opened["status"], opened["version"]) == ("OPEN", 2), (
        "opening moves DRAFT -> OPEN and bumps version to 2, got {}".format(
            (opened["status"], opened["version"])
        )
    )

    # The session never opens: the clock stays at 2026-08-01.
    session = fx.new_session(
        program_id, buyer["id"], "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    assert (session["status"], session["version"]) == ("SCHEDULED", 1), (
        "a new window is persisted SCHEDULED at version 1, got {}".format(
            (session["status"], session["version"])
        )
    )

    paused = fx.set_program_status(program_id, buyer["id"], "PAUSE")
    assert (paused["status"], paused["version"]) == ("PAUSED", 3), (
        "PAUSE moves OPEN -> PAUSED and bumps version to 3, got {}".format(
            (paused["status"], paused["version"])
        )
    )

    buyer_before = get_success_data(api_client.get_buyer(buyer["id"], admin))
    assert buyer_before["status"] == "ACTIVE", (
        "the buyer must still be ACTIVE before the close, got {}".format(
            buyer_before["status"]
        )
    )

    resp = api_client.set_program_status(
        program_id, f.program_status_payload("CLOSE"), admin
    )
    closed = validate_success(resp, 200)
    assert_program(closed, status="CLOSED", version=4)

    sessions, meta = validate_paginated(
        api_client.list_program_sessions(program_id, admin)
    )
    assert meta["total_count"] == 1, (
        "the programme keeps its single window, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert sessions[0]["id"] == session["id"], (
        "the listed window must be the one created above, got {}".format(
            sessions[0]["id"]
        )
    )
    assert sessions[0]["status"] == "CANCELLED", (
        "the SCHEDULED window is CANCELLED by the closing programme, got {}".format(
            sessions[0]["status"]
        )
    )
    assert sessions[0]["version"] == 2, (
        "the cascaded window has its own version incremented to 2, got {}".format(
            sessions[0]["version"]
        )
    )

    buyer_after = get_success_data(api_client.get_buyer(buyer["id"], admin))
    assert buyer_after["status"] == "SUSPENDED", (
        "with no DRAFT, OPEN or PAUSED programme left the buyer moves ACTIVE -> "
        "SUSPENDED, got {}".format(buyer_after["status"])
    )


def test_program_analytics_read_reports_both_concentration_bases():
    """One settled invoice and one still-eligible invoice make the two
    concentration bases disagree inside the same response, while the read model
    echoes the adoption band and the ceiling the settlement cascade tightened —
    and writes nothing.

    PRD §3.10 states the two bases verbatim:
    "`concentration_top_supplier_face_pct` is the largest face-basis share held by any single supplier on the programme, computed exactly as the acceptance gate of §3.6 computes it but without the forward-looking addition: the numerator is that supplier's invoices on the programme in `AWARDED` or `EARLY_PAID` summed at `face_amount_cents`, and the denominator is every invoice on the programme in `ELIGIBLE`, `OFFERED`, `AWARDED` or `EARLY_PAID` summed at `face_amount_cents`."
    "`concentration_top_supplier_funded_pct` is the largest funded-basis share: the numerator is the sum of `net_payment_cents` over that supplier's early payments on the programme whose `funding_status` is `DEPLOYED` or `RELEASED`, and the denominator is the sum of `net_payment_cents` over every early payment on the programme with those same funding statuses."
    the adoption band:
    "An adoption rate at 25.00 percent or above but below 60.00 percent is `OPTIMISED` — so 25.00 is `OPTIMISED` and 59.99 is still `OPTIMISED`."
    the ceiling rule:
    "Under `OPTIMISED`, the candidate is the weighted average accepted APR multiplied by 90 percent, truncated toward zero to a whole basis point, and then raised to 200 basis points if that product fell below it."
    "The programme's `max_acceptable_apr_bps` is then set to the smaller of its current value and that candidate."
    and the read surface itself:
    "The analytics view returns `eligible_invoice_count`, `adopted_invoice_count`, `adoption_rate_pct`, `rate_posture`, `weighted_avg_accepted_apr_bps`, `max_acceptable_apr_bps`, `concentration_top_supplier_face_pct`, `concentration_top_supplier_funded_pct` and `concentration_cap_pct`, and it writes nothing."

    Design: Corner/endpoints/program_analytics_read_reports_both_concentration_bases
    """
    ctx = fx.build_base()
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="ANL-BIG",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.supplier_id,
                invoice_number="ANL-SMALL",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=50_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    invoices = fx.load_invoices(ctx)
    assert [inv["invoice_number"] for inv in invoices] == ["ANL-BIG", "ANL-SMALL"], (
        "the file must have produced ANL-BIG then ANL-SMALL, got {}".format(
            [inv["invoice_number"] for inv in invoices]
        )
    )
    big, small = invoices[0], invoices[1]
    assert (big["face_amount_cents"], small["face_amount_cents"]) == (100_000, 50_000), (
        "faces must be 100000 and 50000, got {}".format(
            (big["face_amount_cents"], small["face_amount_cents"])
        )
    )

    offer = fx.name_offer(
        big["id"],
        ctx.session_id,
        ctx.supplier_id,
        big["version"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    payment = fx.reserve_payment(offer["id"], accepted["version"], ctx.buyer_id)
    fx.set_clock("2026-08-05T00:00:00Z")
    fx.execute_payment(payment["id"], ctx.buyer_id)
    fx.set_clock("2026-08-07T00:00:00Z")
    settled = fx.confirm_settlement(payment["id"], ctx.buyer_id)

    # Value-date basis: 2026-09-30 minus 2026-08-07 is 54 days, so the discount
    # is 100000 * 1000 * 54 / (10000 * 360) = 1500 and the net paid is 98500.
    assert_payment_axes(settled, funding_status="RELEASED", settlement_status="CONFIRMED")
    assert_cash_breakdown(
        settled, days_early=54, discount_amount_cents=1500, net_payment_cents=98_500
    )

    program_before = get_success_data(api_client.get_program(ctx.program_id, ctx.admin))

    view = validate_success(
        api_client.get_program_analytics(ctx.program_id, ctx.treasury), 200
    )
    assert_analytics(
        view,
        eligible_invoice_count=2,
        adopted_invoice_count=1,
        adoption_rate_pct=50.00,
        rate_posture="OPTIMISED",
        weighted_avg_accepted_apr_bps=1000,
        max_acceptable_apr_bps=900,
        concentration_top_supplier_face_pct=66.67,
        concentration_top_supplier_funded_pct=100.00,
        concentration_cap_pct=100.00,
    )
    assert_two_decimal_percentage(view["concentration_top_supplier_face_pct"], 66.67)
    assert_two_decimal_percentage(view["concentration_top_supplier_funded_pct"], 100.00)
    assert (
        view["concentration_top_supplier_face_pct"]
        != view["concentration_top_supplier_funded_pct"]
    ), (
        "the two bases must disagree on this portfolio: face 66.67 counts the "
        "ELIGIBLE invoice in its denominator while funded 100.00 does not, got "
        "{} and {}".format(
            view["concentration_top_supplier_face_pct"],
            view["concentration_top_supplier_funded_pct"],
        )
    )

    program_after = get_success_data(api_client.get_program(ctx.program_id, ctx.admin))
    assert program_after["version"] == program_before["version"], (
        "the analytics read writes nothing, so the programme version must stay "
        "{}, got {}".format(program_before["version"], program_after["version"])
    )
    small_after = get_success_data(api_client.get_invoice(small["id"], ctx.admin))
    assert_invoice(small_after, status="ELIGIBLE", version=small["version"])


def test_reverse_reachability_reads_return_only_the_addressed_parents_children():
    """Each nested collection exposes only the children of the parent named in
    the path: lines in line_no order, the dispute on the invoice that carries it,
    an empty array for the sibling that has none, and one bank account.

    PRD §2.9 states the empty-child rule verbatim:
    "Reverse-lookup collections that do resolve but have no children return an empty array with `total_count` 0."
    PRD §2.3 pins the child ordering:
    "Rows that were created inside a single request retain the order in which they were submitted, so the invoices of one approved-payables file appear in submitted-row order and the lines of one invoice appear in ascending `line_no` order."
    and §3.3 pins the per-line arithmetic those children must expose:
    "For each line, compute `line_tax_cents` as the line's `line_amount_cents` multiplied by its `tax_rate_bps`, divided by ten thousand, and rounded half up to a whole cent."
    "Then compute `line_total_cents` as `line_amount_cents` plus `line_tax_cents`."

    Design: Corner/endpoints/reverse_reachability_reads_return_only_the_addressed_parents_children
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer()
    admin = make_buyer_admin_headers(buyer["id"])
    program = fx.new_open_program(buyer["id"])

    supplier = fx.new_supplier()
    supplier_headers = make_supplier_headers(supplier["id"])
    fx.submit_onboarding(supplier["id"])
    bank = fx.add_bank_account(supplier["id"], "011000015", "8899")

    payable_file = fx.ingest_file(
        program["id"],
        buyer["id"],
        [
            f.payable_row(
                supplier["id"],
                invoice_number="LNK-P",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=[f.invoice_line(1, 30_000, 1000), f.invoice_line(2, 20_000, 0)],
            ),
            f.payable_row(
                supplier["id"],
                invoice_number="LNK-Q",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=[f.invoice_line(1, 40_000, 0)],
            ),
        ],
    )
    invoices = fx.invoices_of_file(payable_file["id"], buyer["id"])
    assert [inv["invoice_number"] for inv in invoices] == ["LNK-P", "LNK-Q"], (
        "the two rows must appear in submitted-row order, got {}".format(
            [inv["invoice_number"] for inv in invoices]
        )
    )
    invoice_p, invoice_q = invoices[0], invoices[1]

    dispute = fx.raise_dispute(
        invoice_p["id"], buyer["id"], 5_000, reason_code="PRICE_VARIANCE"
    )

    lines_p, meta_p = validate_paginated(
        api_client.list_invoice_lines(invoice_p["id"], admin)
    )
    assert meta_p["total_count"] == 2, (
        "LNK-P has exactly two lines, got total_count {}".format(meta_p["total_count"])
    )
    assert [line["line_no"] for line in lines_p] == [1, 2], (
        "lines are read back in ascending line_no order, got {}".format(
            [line["line_no"] for line in lines_p]
        )
    )
    assert [line["invoice_id"] for line in lines_p] == [invoice_p["id"]] * 2, (
        "every line must belong to LNK-P, got {}".format(
            [line["invoice_id"] for line in lines_p]
        )
    )
    assert (
        lines_p[0]["line_amount_cents"],
        lines_p[0]["tax_rate_bps"],
        lines_p[0]["line_tax_cents"],
        lines_p[0]["line_total_cents"],
    ) == (30_000, 1000, 3_000, 33_000), (
        "line 1 prices to 30000 + 3000 tax = 33000, got {}".format(lines_p[0])
    )
    assert (
        lines_p[1]["line_amount_cents"],
        lines_p[1]["tax_rate_bps"],
        lines_p[1]["line_tax_cents"],
        lines_p[1]["line_total_cents"],
    ) == (20_000, 0, 0, 20_000), (
        "line 2 is untaxed, so its total is 20000, got {}".format(lines_p[1])
    )

    lines_q, meta_q = validate_paginated(
        api_client.list_invoice_lines(invoice_q["id"], admin)
    )
    assert meta_q["total_count"] == 1, (
        "LNK-Q has exactly one line and none of LNK-P's may leak in, got "
        "total_count {}".format(meta_q["total_count"])
    )
    assert (
        lines_q[0]["line_no"],
        lines_q[0]["line_amount_cents"],
        lines_q[0]["line_total_cents"],
    ) == (1, 40_000, 40_000), (
        "LNK-Q's only line is (1, 40000, 40000), got {}".format(lines_q[0])
    )
    assert lines_q[0]["invoice_id"] == invoice_q["id"], (
        "LNK-Q's line must reference LNK-Q, got {}".format(lines_q[0]["invoice_id"])
    )

    disputes_q, meta_dq = validate_paginated(
        api_client.list_invoice_disputes(invoice_q["id"], admin)
    )
    assert disputes_q == [], (
        "LNK-Q carries no dispute, so its nested collection is an empty array, "
        "got {}".format(disputes_q)
    )
    assert meta_dq["total_count"] == 0, (
        "an empty reverse lookup reports total_count 0, got {}".format(
            meta_dq["total_count"]
        )
    )

    disputes_p, meta_dp = validate_paginated(
        api_client.list_invoice_disputes(invoice_p["id"], admin)
    )
    assert meta_dp["total_count"] == 1, (
        "LNK-P carries exactly one dispute, got total_count {}".format(
            meta_dp["total_count"]
        )
    )
    assert disputes_p[0]["id"] == dispute["id"], (
        "the listed dispute must be {}, got {}".format(
            dispute["id"], disputes_p[0]["id"]
        )
    )
    assert (disputes_p[0]["status"], disputes_p[0]["invoice_id"]) == (
        "OPEN",
        invoice_p["id"],
    ), "the dispute must be OPEN on LNK-P, got {}".format(disputes_p[0])

    accounts, meta_bank = validate_paginated(
        api_client.list_bank_accounts(supplier["id"], supplier_headers)
    )
    assert meta_bank["total_count"] == 1, (
        "the supplier has exactly one bank account, got total_count {}".format(
            meta_bank["total_count"]
        )
    )
    assert accounts[0]["id"] == bank["id"], (
        "the listed account must be {}, got {}".format(bank["id"], accounts[0]["id"])
    )
    assert accounts[0]["status"] == "MICRO_DEPOSIT_SENT", (
        "an unconfirmed account sits in MICRO_DEPOSIT_SENT, got {}".format(
            accounts[0]["status"]
        )
    )

    p_after = get_success_data(api_client.get_invoice(invoice_p["id"], admin))
    q_after = get_success_data(api_client.get_invoice(invoice_q["id"], admin))
    assert_invoice(
        p_after, status="SUPPRESSED", dispute_suppressed=True, face_amount_cents=53_000
    )
    assert_invoice(
        q_after, status="ELIGIBLE", dispute_suppressed=False, face_amount_cents=40_000
    )


def test_settlement_confirm_before_the_value_date_reports_invalid_state():
    """Confirmation one day short of the value date is refused with
    ERR_INVALID_STATE — the row is DEPLOYED, which is not terminal — and leaves
    every axis untouched; the identical call on the value date succeeds and
    rewrites the discount on the value-date basis.

    PRD §3.8 states the precondition verbatim:
    "It requires `funding_status` `DEPLOYED`, `settlement_status` `REMITTED`, and the logical clock's date to be no earlier than the payment's `value_date`."
    PRD §2.7 supplies the identifier and excludes the terminal check:
    "**Correct source state** — the addressed resource satisfies the preconditions of the requested transition, whether that means being in the right non-terminal source state or having a fork-join precondition met such as identity verification already having passed."
    "Terminal for this purpose means: a discount offer in `ACCEPTED`, `EXPIRED`, `SUPERSEDED` or `VOIDED_BY_SUPPRESSION`; a dispute in `WITHDRAWN`, `RESOLVED_UPHELD` or `RESOLVED_REJECTED`; an early payment whose `funding_status` is `VOID` or whose `settlement_status` is `CONFIRMED` or `FAILED`; a bank account in `VERIFIED`, `FAILED` or `REPLACED`; an auction session in `CLOSED` or `CANCELLED`; a buyer programme in `CLOSED`."
    and §3.8 pins what the successful call recomputes:
    "On the **value-date basis**, used only at settlement confirmation, the basis date is the payment's `value_date`, which is the `execution_date` advanced by the two-day settlement lag; this variant charges only for the days the funds were genuinely out, and is therefore exactly two days shorter than the pay-date figure."

    Design: Corner/endpoints/settlement_confirm_before_the_value_date_reports_invalid_state
    """
    ctx = fx.build_deployed_payment(
        execute_at="2026-08-05T00:00:00Z",
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        face_cents=100_000,
        net_due_date="2026-09-30T00:00:00Z",
        approval_date="2026-07-20T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
    )
    executed = ctx.payment
    assert executed["value_date"].startswith("2026-08-07"), (
        "value_date is the execution date advanced by two days, expected "
        "2026-08-07, got {}".format(executed["value_date"])
    )
    assert_payment_axes(
        executed, funding_status="DEPLOYED", settlement_status="REMITTED"
    )
    # Pay-date basis: 2026-09-30 minus 2026-08-05 is 56 days, so the discount is
    # 100000 * 1000 * 56 / (10000 * 360) = 1555.55... rounded half up to 1556.
    assert_cash_breakdown(
        executed, days_early=56, discount_amount_cents=1556, net_payment_cents=98_444
    )
    version_after_exec = executed["version"]

    fx.set_clock("2026-08-06T00:00:00Z")
    early = api_client.confirm_settlement(ctx.payment_id, ctx.treasury)
    validate_error(early, ERR_INVALID_STATE, 409)
    reported = early.json()["data"]["error_id"]
    assert reported != ERR_ALREADY_TERMINAL, (
        "a DEPLOYED / REMITTED payment is not terminal, so the refusal is "
        "ERR_INVALID_STATE, got {}".format(reported)
    )

    unchanged = fx.read_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        unchanged,
        funding_status="DEPLOYED",
        settlement_status="REMITTED",
        accounting_status="UNCLASSIFIED",
    )
    assert unchanged["version"] == version_after_exec, (
        "the refused confirmation must not bump the payment version away from "
        "{}, got {}".format(version_after_exec, unchanged["version"])
    )
    assert_cash_breakdown(
        unchanged, days_early=56, discount_amount_cents=1556, net_payment_cents=98_444
    )
    invoice_mid = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(invoice_mid, status="AWARDED", provisional_discount_cents=1556)
    buyer_mid = get_success_data(api_client.get_buyer(ctx.buyer_id, ctx.admin))
    assert buyer_mid["credit_used_cents"] == 98_444, (
        "the refusal releases nothing, so the buyer's credit stays encumbered at "
        "98444, got {}".format(buyer_mid["credit_used_cents"])
    )

    fx.set_clock("2026-08-07T00:00:00Z")
    confirmed = validate_success(
        api_client.confirm_settlement(ctx.payment_id, ctx.treasury), 200
    )
    assert_payment_axes(
        confirmed, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    # Value-date basis: 2026-09-30 minus 2026-08-07 is 54 days, exactly two days
    # shorter, giving a discount of 1500 and a net payment of 98500.
    assert_cash_breakdown(
        confirmed, days_early=54, discount_amount_cents=1500, net_payment_cents=98_500
    )

    invoice_final = get_success_data(api_client.get_invoice(ctx.invoice_id, ctx.admin))
    assert_invoice(
        invoice_final,
        status="EARLY_PAID",
        final_discount_cents=1500,
        provisional_discount_cents=1556,
        discount_true_up_cents=-56,
    )
    buyer_final = get_success_data(api_client.get_buyer(ctx.buyer_id, ctx.admin))
    assert buyer_final["credit_used_cents"] == 0, (
        "confirming settlement releases the buyer's credit in full, got {}".format(
            buyer_final["credit_used_cents"]
        )
    )


def test_unknown_filter_value_returns_an_empty_list_not_an_error():
    """A filter value that matches nothing — a status no row currently holds and
    a supplier_id that names no row at all — is a 200 with an empty array and
    total_count 0, never a 404 and never a 400; the same read with a matching
    status proves the filter is really applied rather than ignored.

    PRD §2.3 states the rule verbatim:
    "A filter whose value is syntactically acceptable but matches nothing returns an empty collection rather than an error; for instance, filtering invoices by a `status` value that no invoice currently holds yields an empty array with `total_count` 0."
    and pins the meta of such a page:
    "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."

    Design: Corner/endpoints/unknown_filter_value_returns_an_empty_list_not_an_error
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(legal_name="Filter Buyer", tax_id="336667778")
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    program = fx.new_open_program(buyer_id, name="Filter Programme")
    supplier = fx.new_supplier(legal_name="Filter Supply", tax_id_last4="1818")

    payable_file = fx.ingest_file(
        program["id"],
        buyer_id,
        [
            f.payable_row(
                supplier["id"],
                invoice_number="FLT-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                lines=[f.invoice_line(1, 50_000)],
            )
        ],
        filename="AP-FILTER.csv",
    )
    file_id = payable_file["id"]

    # (1) A status no invoice currently holds: the single row is ELIGIBLE.
    empty_status, meta_status = validate_paginated(
        api_client.list_invoices(admin, file_id=file_id, status="SUPPRESSED")
    )
    assert empty_status == [], (
        "no invoice of the file is SUPPRESSED, so the page must be empty, got "
        "{}".format([row["invoice_number"] for row in empty_status])
    )
    assert_pagination_meta(meta_status, DEFAULT_LIMIT, DEFAULT_OFFSET, 0, False)

    # (2) A supplier_id used as a filter, not as a path segment: still an empty page.
    resp_supplier = api_client.list_invoices(
        PLATFORM_OPS_HEADERS, supplier_id=NON_EXISTENT_UUID
    )
    empty_supplier, meta_supplier = validate_paginated(resp_supplier)
    assert resp_supplier.status_code == 200, (
        "a filter naming no supplier is a 200 empty page, got HTTP {}".format(
            resp_supplier.status_code
        )
    )
    reported = resp_supplier.json().get("data")
    assert not isinstance(reported, dict) or "error_id" not in reported, (
        "an unmatched supplier_id filter must not report ERR_SUPPLIER_NOT_FOUND, "
        "got {}".format(reported)
    )
    assert empty_supplier == [], (
        "no invoice belongs to the sentinel supplier, so the page must be empty, "
        "got {}".format(empty_supplier)
    )
    assert_pagination_meta(meta_supplier, DEFAULT_LIMIT, DEFAULT_OFFSET, 0, False)

    # (3) A reverse-lookup collection that resolves but whose filter matches
    #     nothing: the buyer exists and holds one OPEN programme, none CLOSED.
    empty_programs, meta_programs = validate_paginated(
        api_client.list_buyer_programs(buyer_id, admin, status="CLOSED")
    )
    assert empty_programs == [], (
        "the buyer holds no CLOSED programme, so the page must be empty, got "
        "{}".format([p["status"] for p in empty_programs])
    )
    assert_pagination_meta(meta_programs, DEFAULT_LIMIT, DEFAULT_OFFSET, 0, False)

    # (4) The matching status proves the filter is applied, not ignored.
    matched, meta_matched = validate_paginated(
        api_client.list_invoices(admin, file_id=file_id, status="ELIGIBLE")
    )
    assert len(matched) == 1, (
        "exactly the one ELIGIBLE invoice of the file must come back, got "
        "{}".format([row["invoice_number"] for row in matched])
    )
    assert_pagination_meta(meta_matched, DEFAULT_LIMIT, DEFAULT_OFFSET, 1, False)
    assert_invoice(
        matched[0],
        invoice_number="FLT-1",
        status="ELIGIBLE",
        face_amount_cents=50_000,
        supplier_id=supplier["id"],
        program_id=program["id"],
    )
    all_programs, meta_all = validate_paginated(
        api_client.list_buyer_programs(buyer_id, admin)
    )
    assert [p["status"] for p in all_programs] == ["OPEN"], (
        "the unfiltered read must still show the one OPEN programme, got "
        "{}".format([p["status"] for p in all_programs])
    )
    assert_pagination_meta(meta_all, DEFAULT_LIMIT, DEFAULT_OFFSET, 1, False)
