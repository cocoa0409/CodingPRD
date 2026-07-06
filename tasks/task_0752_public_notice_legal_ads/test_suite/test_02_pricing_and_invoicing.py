"""Pricing, cost finalization, invoice assembly, and account balances.

Difficulty queue A: dual-variant calculations (notice cost estimated vs final; account
balance outstanding vs committed) and combinatorial pricing formulas (per-insertion
ceiling; affidavit-fee subtotal-tier waiver). Corner queue B: invoice line-item
reverse reachability.
"""
from prd_bench_local_runner.testing import validate_success, get_success_data
from test_helpers import (
    make_advertiser_headers,
    create_notice_payload, FORECLOSURE_BODY_100,
    provision_reference, setup_published_notice,
)


# ===========================================================================
# Difficulty rule 1 — dual-variant calculations
# ===========================================================================

class TestNoticeCostEstimatedVsFinal:
    def test_estimated_cost_from_submitted_line_count(self, api):
        """PRD §3.2: "each projected insertion uses the notice's `line_count`, and the
        per-insertion charge follows the newspaper's pricing basis (§2.6) — under
        `PER_LINE`, the first projected insertion is priced with `line_rate_first_cents`
        and every remaining projected insertion with `line_rate_subsequent_cents`, each
        multiplied by `line_count`."

        Design: Difficulty/dual_variant_calc/notice_cost_estimated_vs_final_divergence
        """
        ref = provision_reference(api)
        data = validate_success(
            api.create_notice(
                create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"]),
                make_advertiser_headers(ref["account"]["id"])), 201)
        # line_count 2: seq1 2*500 + seq2 2*300 = 1600
        assert data["estimated_cost_cents"] == 1600, data["estimated_cost_cents"]

    def test_final_cost_uses_actual_lines_and_diverges(self, api):
        """PRD §3.6: "Because it uses each insertion's reported `line_count_actual` and
        excludes skipped, cancelled, and make-good insertions, the final charge diverges
        from `estimated_cost_cents` whenever the paper reformats copy or a run is skipped
        and made good for free."

        Design: Difficulty/dual_variant_calc/notice_cost_estimated_vs_final_divergence
        """
        ref = setup_published_notice(api, line_count_actual=3)
        notice = ref["notice"]
        # final: seq1 3*500 + seq2 3*300 = 2400; estimated was 1600
        assert notice["final_cost_cents"] == 2400, notice["final_cost_cents"]
        assert notice["estimated_cost_cents"] == 1600
        assert notice["final_cost_cents"] != notice["estimated_cost_cents"]
        assert notice["status"] == "PUBLISHED"


class TestAccountBalanceOutstandingVsCommitted:
    def test_outstanding_excludes_draft_invoice(self, api):
        """PRD §3.7: "The `outstanding_balance_cents` is the settled view: it is the sum
        of `total_cents` across the account's `ISSUED` invoices, minus the sum of
        `amount_cents` across all the account's payments."

        Design: Difficulty/dual_variant_calc/account_balance_outstanding_vs_committed_divergence
        """
        ref = setup_published_notice(api, line_count_actual=2)  # DRAFT invoice, not issued
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["outstanding_balance_cents"] == 0, acct["outstanding_balance_cents"]

    def test_committed_adds_draft_invoice_total(self, api):
        """PRD §3.7: "The `committed_balance_cents` is the exposure view used by the
        credit-limit gate at submit time: it is the `outstanding_balance_cents` plus the
        sum of `total_cents` across the account's `DRAFT` invoices, so that a notice
        which has published but not yet been affidavited still consumes credit."

        Design: Difficulty/dual_variant_calc/account_balance_outstanding_vs_committed_divergence
        """
        ref = setup_published_notice(api, line_count_actual=2)  # subtotal 1600 + fee 2500 = 4100
        acct = validate_success(
            api.get_account(ref["account"]["id"],
                          make_advertiser_headers(ref["account"]["id"])), 200)
        assert acct["committed_balance_cents"] == 4100, acct["committed_balance_cents"]
        assert acct["outstanding_balance_cents"] != acct["committed_balance_cents"]


# ===========================================================================
# Difficulty rule 2 — combinatorial pricing formulas
# ===========================================================================

class TestPerInsertionLineCeiling:
    def test_line_count_ceiled_per_insertion(self, api):
        """PRD §2.6: "This ceiling is always applied per insertion on that insertion's
        own text — the system never sums characters across multiple insertions and takes
        a single ceiling."

        Design: Difficulty/combinatorial_formula/notice_line_count_ceil_per_insertion_then_sum
        """
        ref = provision_reference(api)
        data = validate_success(
            api.create_notice(
                create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"],
                                      title="Big Estate", body_text=FORECLOSURE_BODY_100),
                make_advertiser_headers(ref["account"]["id"])), 201)
        assert data["line_count"] == 3, data["line_count"]

    def test_estimated_sums_per_insertion_line_charges(self, api):
        """PRD §3.2: "The projected per-insertion charges are summed to yield
        `estimated_cost_cents`."

        Design: Difficulty/combinatorial_formula/notice_line_count_ceil_per_insertion_then_sum
        """
        ref = provision_reference(api)
        data = validate_success(
            api.create_notice(
                create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"],
                                      title="Big Estate", body_text=FORECLOSURE_BODY_100),
                make_advertiser_headers(ref["account"]["id"])), 201)
        # line_count 3: seq1 3*500 + seq2 3*300 = 2400
        assert data["estimated_cost_cents"] == 2400, data["estimated_cost_cents"]


class TestAffidavitFeeSubtotalWaiver:
    def _publish_foreclosure_3(self, api):
        return setup_published_notice(
            api, line_count_actual=3,
            statutory_overrides={"notice_type": "FORECLOSURE", "county": "SPRINGFIELD",
                                 "min_insertions": 3, "min_days_before_deadline": 7},
            notice_overrides={"notice_type": "FORECLOSURE", "title": "Foreclosure Sale",
                              "body_text": FORECLOSURE_BODY_100, "deadline_date": "2026-04-01"})

    def test_subtotal_equals_final_cost(self, api):
        """PRD §3.6: "The invoice's `subtotal_cents` equals the notice's
        `final_cost_cents`, and is itemized into one `InvoiceLineItem` per `PUBLISHED`
        non-make-good insertion."

        Design: Difficulty/combinatorial_formula/invoice_affidavit_fee_waiver_subtotal_tier
        """
        ref = self._publish_foreclosure_3(api)
        # final: 3*500 + 3*300 + 3*300 = 3300
        assert ref["notice"]["final_cost_cents"] == 3300, ref["notice"]["final_cost_cents"]
        assert ref["invoice"]["subtotal_cents"] == 3300, ref["invoice"]["subtotal_cents"]

    def test_fee_waived_when_subtotal_at_threshold(self, api):
        """PRD §3.6: "the invoice's `affidavit_fee_cents` is 0 when `subtotal_cents` is
        at least the waiver threshold of 3,000 cents, and otherwise equals the
        newspaper's flat `affidavit_fee_cents`."
        PRD §3.6: "The invoice's `total_cents` is `subtotal_cents` plus its
        `affidavit_fee_cents`."

        Design: Difficulty/combinatorial_formula/invoice_affidavit_fee_waiver_subtotal_tier
        """
        ref = self._publish_foreclosure_3(api)
        assert ref["invoice"]["affidavit_fee_cents"] == 0, ref["invoice"]["affidavit_fee_cents"]
        assert ref["invoice"]["total_cents"] == 3300, ref["invoice"]["total_cents"]


# ===========================================================================
# Corner queue B — invoice line-item reverse reachability
# ===========================================================================

def test_invoice_line_items_reverse_reachable(api):
    """PRD §3.6: "When the fee is not waived, it is itemized as an additional line with
    a null `insertion_id`, a `description` of "Affidavit of publication fee", a
    `line_count` of 0, a `rate_cents` equal to the fee, and an `amount_cents` equal to
    the fee."
    PRD §3.8: "invoice line items by `invoice_id` and `insertion_id`".

    Design: Corner/endpoints/invoice_line_items_reverse_reachable
    """
    ref = setup_published_notice(api, line_count_actual=2)  # subtotal 1600 < 3000 -> fee 2500
    headers = make_advertiser_headers(ref["account"]["id"])
    rows = get_success_data(
        api.list_invoice_line_items(headers, params={"invoice_id": ref["invoice"]["id"]}))
    assert len(rows) == 3, f"expected 2 insertion lines + 1 fee line, got {len(rows)}"
    fee_lines = [r for r in rows if r["insertion_id"] is None]
    assert len(fee_lines) == 1, "exactly one affidavit-fee line"
    assert fee_lines[0]["amount_cents"] == 2500, fee_lines[0]["amount_cents"]
