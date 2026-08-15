"""GL coding, cost allocation, overcharge recovery, remittance, savings, and
analytics export.

Covers PRD §3.6 allocation math and GL account gating, §3.8 remittance
acknowledgement, and §3.9 recovery-claim limits and lifecycle, the savings
rollup, and the synchronous checksummed export.
"""
import hashlib

from test_helpers import (
    ADMIN,
    ANALYST,
    FINANCE,
    ApiErrorId,
    add_run_item,
    build_cleared_invoice,
    build_rate_mismatch_exception,
    build_settled_invoice,
    create_gl_account,
    create_invoice,
    create_payment_run,
    create_recovery_claim,
    finalize_invoice,
    find_line,
    list_run_advices,
    lock_run,
    make_carrier_rep_headers,
    notify_and_respond,
    release_run,
    rerate_invoice,
    settle_run,
    setup_standard_chain,
    validate_error,
    validate_success,
)

_TOLERANCE = {"audit_tolerance_minor": 500, "audit_tolerance_pct_bp": 200}


class TestCostAllocations:
    """The BASE_FREIGHT line of the canonical cleared invoice is rated 75000;
    that rated amount is what the allocation set splits."""

    def _setup(self, api):
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        line = find_line(invoice["id"], "BASE_FREIGHT")
        assert line["rated_amount_minor"] == 75000, "Setup failed: unexpected base rating"
        client_id = chain["client"]["id"]
        gl1 = create_gl_account(client_id, code="4000", business_unit="BU-NORTH")
        gl2 = create_gl_account(client_id, code="4100", business_unit="BU-SOUTH")
        gl3 = create_gl_account(client_id, code="4200", business_unit="BU-WEST")
        return line, gl1, gl2, gl3

    def test_even_split_conserves_the_line_amount(self, api):
        """PRD §3.6: "Each row's `allocated_minor` is that line amount
        multiplied by the row's `percentage_bp` and divided by ten thousand,
        rounded half up." A 5000/5000 bp split of 75000 allocates 37500 +
        37500: the shares sum to 10000 bp and the amounts sum to the line.

        Design: Difficulty/compensating_invariant/allocation_replace_percentage_conservation
        """
        line, gl1, gl2, _gl3 = self._setup(api)
        validate_success(
            api.replace_line_allocations(
                line["id"],
                {"allocations": [
                    {"gl_account_id": gl1["id"], "percentage_bp": 5000},
                    {"gl_account_id": gl2["id"], "percentage_bp": 5000},
                ]},
                FINANCE,
            ),
            200,
        )
        rows = {
            row["gl_account_id"]: row
            for row in validate_success(api.list_line_allocations(line["id"], FINANCE))
        }
        assert rows[gl1["id"]]["allocated_minor"] == 37500
        assert rows[gl2["id"]]["allocated_minor"] == 37500
        assert sum(row["allocated_minor"] for row in rows.values()) == 75000
        assert sum(row["percentage_bp"] for row in rows.values()) == 10000

    def test_replace_recomputes_with_remainder_to_largest_share(self, api):
        """PRD §3.6: "Because per-row rounding can drift from the line amount,
        the remainder — the line amount minus the sum of the rounded rows, in
        either direction — is applied to the row with the largest
        `percentage_bp`; ties break by the target account's `code` in ascending
        order and then by the allocation row's `created_at` in ascending order.
        Repeating the action replaces the set wholesale: the prior rows are
        deleted and the split is recomputed from scratch, so allocations never
        drift across edits."

        Replacing 5000/5000 with 3333/3333/3334 over 75000: round_half_up gives
        24998 + 24998 + 25005 = 75001, so the -1 remainder lands on the
        largest-share row (3334 bp), leaving 24998/24998/25004 — still exactly
        75000 with no drift.

        Design: Difficulty/compensating_invariant/allocation_replace_percentage_conservation
        """
        line, gl1, gl2, gl3 = self._setup(api)
        validate_success(
            api.replace_line_allocations(
                line["id"],
                {"allocations": [
                    {"gl_account_id": gl1["id"], "percentage_bp": 5000},
                    {"gl_account_id": gl2["id"], "percentage_bp": 5000},
                ]},
                FINANCE,
            ),
            200,
        )
        validate_success(
            api.replace_line_allocations(
                line["id"],
                {"allocations": [
                    {"gl_account_id": gl1["id"], "percentage_bp": 3333},
                    {"gl_account_id": gl2["id"], "percentage_bp": 3333},
                    {"gl_account_id": gl3["id"], "percentage_bp": 3334},
                ]},
                FINANCE,
            ),
            200,
        )
        rows = {
            row["gl_account_id"]: row
            for row in validate_success(api.list_line_allocations(line["id"], FINANCE))
        }
        assert len(rows) == 3, "replaced set must contain only the new rows"
        assert rows[gl1["id"]]["allocated_minor"] == 24998
        assert rows[gl2["id"]]["allocated_minor"] == 24998
        assert rows[gl3["id"]]["allocated_minor"] == 25004
        assert sum(row["allocated_minor"] for row in rows.values()) == 75000

    def test_shares_not_summing_to_10000_rejected(self, api):
        """PRD §3.6: "the shares across the set must sum to exactly 10000 basis
        points, failing with `ERR_ALLOCATION_SUM_INVALID` otherwise."

        A 4000 + 5000 = 9000 bp set is rejected and no rows persist.

        Design: Corner/validations/allocation_sum_not_10000_rejected
        """
        line, gl1, gl2, _gl3 = self._setup(api)
        res = api.replace_line_allocations(
            line["id"],
            {"allocations": [
                {"gl_account_id": gl1["id"], "percentage_bp": 4000},
                {"gl_account_id": gl2["id"], "percentage_bp": 5000},
            ]},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_ALLOCATION_SUM_INVALID, expected_status=422)
        rows = validate_success(api.list_line_allocations(line["id"], FINANCE))
        assert rows == []


class TestGlCoding:
    def test_coding_against_inactive_account_rejected(self, api):
        """PRD §3.6: "Assigning a line's primary GL code writes the line's
        `gl_account_id`; an inactive account refuses new coding with
        `ERR_GL_ACCOUNT_INACTIVE`."

        Design: Corner/validations/gl_code_inactive_rejected
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        line = find_line(invoice["id"], "BASE_FREIGHT")
        inactive = create_gl_account(
            chain["client"]["id"], code="4999", business_unit="BU-LEGACY", active=False
        )
        res = api.assign_line_gl_code(line["id"], {"gl_account_id": inactive["id"]}, FINANCE)
        validate_error(res, ApiErrorId.ERR_GL_ACCOUNT_INACTIVE, expected_status=409)
        current = validate_success(api.get_invoice_line(line["id"], FINANCE))
        assert current.get("gl_account_id") is None


class TestSavingsRollup:
    def test_rollup_counts_paid_avoidance_and_collected_recovery(self, api):
        """PRD §3.9: "`avoided_overcharge_minor` sums, over the client's
        invoices with payment status `PAID` or `SHORT_PAID`, the amount by
        which `billed_total_minor` exceeded `approved_amount_minor` (never
        below zero per invoice), converted to the home currency at the
        invoice-date variant — the identity when the invoice currency already
        is the home currency. `recovered_minor` sums the `recovered_minor` of
        the client's `COLLECTED` claims, converted at the invoice-date variant
        when the claim's invoice currency differs from home.
        `savings_realized_minor` is the sum of those two components."

        The 91000-billed invoice resolves ACCEPT at its 87500 rated total and
        settles PAID: avoidance 3500. The 2000 claim collects 1200. Total
        4700, and nothing remains outstanding.

        Design: Corner/calculations/savings_rollup_includes_only_paid_and_collected
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, exception = build_rate_mismatch_exception(chain)
        notify_and_respond(exception["id"], chain["carrier"]["id"])
        validate_success(
            api.resolve_exception(exception["id"], {"outcome": "ACCEPT"}, ANALYST), 200
        )
        rerate_invoice(invoice["id"])
        cleared = finalize_invoice(invoice["id"])
        assert cleared["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        run = create_payment_run(chain["client"]["id"])
        add_run_item(run["id"], invoice["id"])
        lock_run(run["id"])
        release_run(run["id"])
        settle_run(run["id"])
        paid = validate_success(api.get_invoice(invoice["id"], ADMIN))
        assert paid["payment_status"] == "PAID", "Setup failed: not PAID"
        claim = create_recovery_claim(
            invoice["id"], claimed_amount_minor=2000, channel="OFFSET"
        )
        validate_success(api.file_recovery_claim(claim["id"], ANALYST), 200)
        validate_success(
            api.respond_recovery_claim(
                claim["id"],
                {"outcome": "ACKNOWLEDGE"},
                make_carrier_rep_headers(chain["carrier"]["id"]),
            ),
            200,
        )
        collected = validate_success(
            api.collect_recovery_claim(claim["id"], {"recovered_minor": 1200}, FINANCE), 200
        )
        assert collected["status"] == "COLLECTED", "Setup failed: not COLLECTED"
        savings = validate_success(api.get_client_savings(chain["client"]["id"], ADMIN))
        assert savings["avoided_overcharge_minor"] == 3500
        assert savings["recovered_minor"] == 1200
        assert savings["savings_realized_minor"] == 4700
        assert savings["outstanding_liability_minor"] == 0
        assert savings["currency"] == "USD"


class TestRecoveryClaims:
    def test_rebut_then_refile_cycle_reaches_collected(self, api):
        """PRD §3.9: "Filing moves `DRAFTED` → `FILED`. The carrier answers
        through a `CarrierRep` whose identity matches the invoice's
        `carrier_id` (`ERR_FORBIDDEN_FOR_ROLE` otherwise): an `outcome` of
        `ACKNOWLEDGE` moves `FILED` → `ACKNOWLEDGED`, an `outcome` of `REBUT`
        moves `FILED` → `REBUTTED`. A rebutted claim can be filed again
        (`REBUTTED` → `FILED`) or given up". PRD §3.9: "Collection is the
        finance act: a `FinanceController` collects an `ACKNOWLEDGED` claim
        into `COLLECTED`, recording the actual `recovered_minor`, which must
        not exceed the `claimed_amount_minor` (`ERR_RECOVERY_EXCEEDS_CLAIMED`)."

        Design: Corner/state_machines/recovery_claim_rebut_refiling_cycle
        """
        chain = setup_standard_chain()
        invoice, _run = build_settled_invoice(chain)
        assert invoice["payment_status"] == "PAID", "Setup failed: not PAID"
        claim = create_recovery_claim(
            invoice["id"], claimed_amount_minor=2000, channel="CREDIT_MEMO"
        )
        assert claim["status"] == "DRAFTED"
        filed = validate_success(api.file_recovery_claim(claim["id"], ANALYST), 200)
        assert filed["status"] == "FILED"
        rebutted = validate_success(
            api.respond_recovery_claim(
                claim["id"],
                {"outcome": "REBUT"},
                make_carrier_rep_headers(chain["carrier"]["id"]),
            ),
            200,
        )
        assert rebutted["status"] == "REBUTTED"
        refiled = validate_success(api.file_recovery_claim(claim["id"], ANALYST), 200)
        assert refiled["status"] == "FILED"
        acknowledged = validate_success(
            api.respond_recovery_claim(
                claim["id"],
                {"outcome": "ACKNOWLEDGE"},
                make_carrier_rep_headers(chain["carrier"]["id"]),
            ),
            200,
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        collected = validate_success(
            api.collect_recovery_claim(claim["id"], {"recovered_minor": 1200}, FINANCE), 200
        )
        assert collected["status"] == "COLLECTED"
        assert collected["recovered_minor"] == 1200

    def test_claim_and_recovery_amount_limits_enforced(self, api):
        """PRD §3.9: "Drafting requires the invoice's payment status to be
        `PAID` or `SHORT_PAID` (`ERR_INVALID_STATE` otherwise), and the claim
        may not exceed the invoice's `paid_minor` (`ERR_CLAIM_EXCEEDS_PAID`)."
        PRD §3.9: "a `FinanceController` collects an `ACKNOWLEDGED` claim into
        `COLLECTED`, recording the actual `recovered_minor`, which must not
        exceed the `claimed_amount_minor` (`ERR_RECOVERY_EXCEEDS_CLAIMED`)."

        Paid 87500: a 999999 claim fails at draft; on a 2000 claim, collecting
        2500 fails, then collecting 1200 succeeds.

        Design: Corner/validations/recovery_amount_limits_enforced
        """
        chain = setup_standard_chain()
        invoice, _run = build_settled_invoice(chain)
        assert invoice["paid_minor"] == 87500, "Setup failed: unexpected paid_minor"
        res = api.create_recovery_claim(
            invoice["id"],
            {"claimed_amount_minor": 999999, "channel": "REFUND"},
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_EXCEEDS_PAID, expected_status=409)
        claim = create_recovery_claim(
            invoice["id"], claimed_amount_minor=2000, channel="REFUND"
        )
        validate_success(api.file_recovery_claim(claim["id"], ANALYST), 200)
        validate_success(
            api.respond_recovery_claim(
                claim["id"],
                {"outcome": "ACKNOWLEDGE"},
                make_carrier_rep_headers(chain["carrier"]["id"]),
            ),
            200,
        )
        res = api.collect_recovery_claim(claim["id"], {"recovered_minor": 2500}, FINANCE)
        validate_error(res, ApiErrorId.ERR_RECOVERY_EXCEEDS_CLAIMED, expected_status=409)
        collected = validate_success(
            api.collect_recovery_claim(claim["id"], {"recovered_minor": 1200}, FINANCE), 200
        )
        assert collected["status"] == "COLLECTED"


class TestRemittanceAdvice:
    def test_advice_sent_at_settle_then_acknowledged_by_carrier(self, api):
        """PRD §3.8: "Every remittance advice of the run moves `GENERATED` →
        `SENT`." PRD §3.8: "A carrier acknowledges receipt of its remittance: a
        `CarrierRep` whose identity matches the advice's `carrier_id` moves the
        advice `SENT` → `ACKNOWLEDGED` (`ERR_FORBIDDEN_FOR_ROLE` otherwise)."

        Design: Corner/endpoints/remittance_advice_acknowledge_flow
        """
        chain = setup_standard_chain()
        _invoice, run = build_settled_invoice(chain)
        advices = list_run_advices(run["id"])
        assert len(advices) == 1, "Setup failed: expected exactly one advice"
        assert advices[0]["status"] == "SENT"
        acknowledged = validate_success(
            api.acknowledge_remittance_advice(
                advices[0]["id"], make_carrier_rep_headers(chain["carrier"]["id"])
            ),
            200,
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"


class TestAnalyticsExport:
    def test_row_count_deterministic_checksum_and_range_validation(self, api):
        """PRD §3.9: "The export completes synchronously at creation, moving
        `REQUESTED` → `COMPLETED`: `row_count` counts the invoices in range
        (after the status filter), and `checksum` is the literal string
        `sha256:` followed by the SHA-256 hexadecimal digest of the
        comma-joined invoice numbers, ordered by each invoice's `created_at`
        ascending and then `invoice_number` ascending." PRD §3.9: "a `date_to`
        earlier than `date_from` is rejected with `ERR_EXPORT_RANGE_INVALID`".

        Two invoices in range (INV-A created before INV-B): row_count 2 and
        checksum over "INV-A,INV-B", identical across two identical exports.

        Design: Corner/endpoints/analytics_export_row_count_and_deterministic_checksum
        """
        chain = setup_standard_chain(with_contract=False)
        for number, amount in (("INV-A", 100), ("INV-B", 200)):
            create_invoice(
                chain["client"]["id"],
                chain["carrier"]["id"],
                invoice_number=number,
                invoice_date="2026-08-03" if number == "INV-A" else "2026-08-04",
                billed_total_minor=amount,
                lines=[{"charge_code": "OTHER", "billed_amount_minor": amount}],
            )
        export1 = validate_success(
            api.create_analytics_export(
                chain["client"]["id"],
                {"date_from": "2026-08-01", "date_to": "2026-08-31"},
                FINANCE,
            ),
            201,
        )
        assert export1["status"] == "COMPLETED"
        assert export1["row_count"] == 2
        expected = "sha256:" + hashlib.sha256(b"INV-A,INV-B").hexdigest()
        assert export1["checksum"] == expected
        export2 = validate_success(
            api.create_analytics_export(
                chain["client"]["id"],
                {"date_from": "2026-08-01", "date_to": "2026-08-31"},
                FINANCE,
            ),
            201,
        )
        assert export2["checksum"] == export1["checksum"]
        res = api.create_analytics_export(
            chain["client"]["id"],
            {"date_from": "2026-08-31", "date_to": "2026-08-01"},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_EXPORT_RANGE_INVALID, expected_status=422)
