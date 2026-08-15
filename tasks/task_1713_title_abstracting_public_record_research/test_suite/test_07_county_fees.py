"""County retrievals and the pass-through fee ledger (PRD §2.6, §2.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_document,
    create_retrieval,
    create_retrieval_payload,
    get_order,
    get_retrieval,
    make_abstracter_headers,
    make_examiner_headers,
    make_ops_headers,
    post_fee,
    reverse_fee,
    setup_delivered_order,
    setup_order_with_assignment,
    validate_error,
)


class TestRetrievalFeeVariants:
    def _setup_two_retrievals(self, api):
        """One 10-page PER_PAGE retrieval and one PER_DOCUMENT retrieval."""
        ctx = setup_order_with_assignment(
            "client_702", "abs_702", search_type="LIEN_JUDGMENT_TAX"
        )
        doc_mortgage = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_702",
            instrument_type="MORTGAGE", grantor_name="Bob Jones", grantee_name="First Bank",
            instrument_number="INST-702-A", recording_date="2015-04-01",
        )
        doc_deed = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_702",
            instrument_type="DEED", grantor_name="Alice Smith", grantee_name="Bob Jones",
            instrument_number="INST-702-B", recording_date="2010-06-01",
        )
        ret_page = create_retrieval(
            ctx["order"]["id"], doc_mortgage["id"], "abs_702",
            fee_mode="PER_PAGE", page_count=10,
        )
        ret_doc = create_retrieval(
            ctx["order"]["id"], doc_deed["id"], "abs_702", fee_mode="PER_DOCUMENT"
        )
        ctx["ret_page"] = ret_page
        ctx["ret_doc"] = ret_doc
        return ctx

    def test_per_page_and_per_document_modes_price_same_instrument_differently(self, api):
        """PRD §3.9: "Posting the fee moves a retrieval from `REQUESTED` to
        `FEE_POSTED` and computes `fee_cents`: a flat 2500 cents when the mode is
        `PER_DOCUMENT`, regardless of any page count; or `page_count` times 125
        cents when the mode is `PER_PAGE` — a ten-page instrument therefore costs
        1250 cents instead of 2500."

        Design: Difficulty/dual_variant_calc/retrieval_fee_per_page_vs_per_document
        """
        ctx = self._setup_two_retrievals(api)
        posted_page = post_fee(ctx["ret_page"]["id"])
        posted_doc = post_fee(ctx["ret_doc"]["id"])
        assert posted_page["fee_cents"] == 1250, (
            f"10 pages * 125 = 1250, got {posted_page['fee_cents']}"
        )
        assert posted_doc["fee_cents"] == 2500, (
            f"flat per-document charge = 2500, got {posted_doc['fee_cents']}"
        )
        assert posted_page["fee_cents"] != posted_doc["fee_cents"], (
            "two valid pricing variants on the same retrieval subject must diverge"
        )

    def test_posted_retrieval_fees_aggregate_into_running_fee(self, api):
        """PRD §3.9: "Posting then recomputes the order's running fee per §2.6: the
        base fee of 40000 cents plus the sum of `fee_cents` over every retrieval of
        the order in `FEE_POSTED` or `INVOICED` status — `REQUESTED` retrievals
        carry no fee and `FEE_REVERSED` retrievals are excluded — plus, for `RUSH`
        orders only, the twenty-five-percent premium computed once on that whole
        subtotal and rounded half up; the liability cap is recomputed alongside."

        Design: Difficulty/dual_variant_calc/retrieval_fee_per_page_vs_per_document
        """
        ctx = self._setup_two_retrievals(api)
        post_fee(ctx["ret_page"]["id"])
        post_fee(ctx["ret_doc"]["id"])

        order = get_order(ctx["order"]["id"])
        assert order["accrued_fees_cents"] == 43750, (
            f"40000 base + 1250 + 2500 with no STANDARD premium, got {order['accrued_fees_cents']}"
        )


class TestRushPremiumRoundingOrder:
    def _setup_three_per_page_posted(self, api):
        ctx = setup_order_with_assignment("client_712", "abs_712", sla_tier="RUSH")
        docs = [
            create_document(
                ctx["order"]["id"], ctx["assignment"]["id"], "abs_712",
                instrument_type=inst, grantor_name=g, grantee_name=ge,
                instrument_number=num, recording_date=date,
            )
            for inst, g, ge, num, date in (
                ("DEED", "A Smith", "B Jones", "INST-712-A", "2008-01-10"),
                ("DEED", "B Jones", "C Lee", "INST-712-B", "2012-05-20"),
                ("MORTGAGE", "C Lee", "Second Bank", "INST-712-C", "2014-09-02"),
            )
        ]
        retrievals = [
            create_retrieval(
                ctx["order"]["id"], d["id"], "abs_712", fee_mode="PER_PAGE", page_count=3
            )
            for d in docs
        ]
        for r in retrievals:
            post_fee(r["id"])
        ctx["retrievals"] = retrievals
        return ctx

    def test_rush_premium_rounded_once_on_whole_subtotal(self, api):
        """PRD §2.6: "One rounding order is pinned and non-negotiable: the rush
        premium is computed exactly once, on the whole subtotal formed by the base
        fee plus the full sum of contributing retrieval fees. Computing the premium
        per retrieval line and summing is a forbidden variant, because per-line
        rounding drifts the total — three per-page lines of 375 cents each yield a
        premium of 10281 cents when computed once on the subtotal of 41125, but
        10282 cents when rounded line by line."

        Design: Difficulty/combinatorial_formula/rush_premium_rounded_once_on_subtotal
        """
        ctx = self._setup_three_per_page_posted(api)
        for retrieval in ctx["retrievals"]:
            posted = get_retrieval(retrieval["id"])
            assert posted["fee_cents"] == 375, f"3 pages * 125, got {posted['fee_cents']}"

        order = get_order(ctx["order"]["id"])
        assert order["accrued_fees_cents"] == 51406, (
            f"41125 + round_half_up(41125*0.25)=10281 -> 51406, got {order['accrued_fees_cents']}"
        )

    def test_per_line_premium_rounding_is_forbidden_variant(self, api):
        """PRD §2.6: "One rounding order is pinned and non-negotiable: the rush
        premium is computed exactly once, on the whole subtotal formed by the base
        fee plus the full sum of contributing retrieval fees. Computing the premium
        per retrieval line and summing is a forbidden variant, because per-line
        rounding drifts the total — three per-page lines of 375 cents each yield a
        premium of 10281 cents when computed once on the subtotal of 41125, but
        10282 cents when rounded line by line."

        Design: Difficulty/combinatorial_formula/rush_premium_rounded_once_on_subtotal
        """
        ctx = self._setup_three_per_page_posted(api)
        order = get_order(ctx["order"]["id"])
        premium_slice = order["accrued_fees_cents"] - 41125
        assert premium_slice == 10281, (
            f"premium over the 41125 subtotal must be the once-rounded 10281, got {premium_slice}"
        )
        assert order["accrued_fees_cents"] != 51407, (
            "51407 is the value produced by the forbidden per-line rounding variant"
        )


class TestFeeLifecycleGuards:
    def _setup_requested_retrieval(self, api, client_ref="client_891", abstracter_ref="abs_891"):
        ctx = setup_order_with_assignment(client_ref, abstracter_ref)
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], abstracter_ref,
            instrument_number="INST-891-A", recording_date="2001-01-01",
        )
        retrieval = create_retrieval(
            ctx["order"]["id"], doc["id"], abstracter_ref, fee_mode="PER_DOCUMENT"
        )
        ctx["document"] = doc
        ctx["retrieval"] = retrieval
        return ctx

    def test_double_post_fee_rejected(self, api):
        """PRD §3.9: "Posting against a retrieval already in `FEE_POSTED` or
        `FEE_REVERSED` is refused with `ERR_FEE_ALREADY_POSTED` (HTTP 409); posting
        against an `INVOICED` retrieval, or reversing one, is refused with
        `ERR_ALREADY_INVOICED` (HTTP 409) — an invoiced fee can never be touched."

        Design: Corner/validations/double_post_fee_rejected
        """
        ctx = self._setup_requested_retrieval(api)
        post_fee(ctx["retrieval"]["id"])

        resp = api.post_retrieval_fee(ctx["retrieval"]["id"], make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_FEE_ALREADY_POSTED)

        after = get_retrieval(ctx["retrieval"]["id"])
        assert after["fee_cents"] == 2500, "no double-post drift on the posted fee"

    def test_examiner_cannot_post_fee(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or whose `X-User-ID` fails an attribute-ownership rule — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/county-retrievals/{id}/post-fee is authorized for
        OperationsManager only.

        Design: Corner/rbac/examiner_cannot_post_fee
        """
        ctx = self._setup_requested_retrieval(api, "client_863", "abs_863")
        resp = api.post_retrieval_fee(
            ctx["retrieval"]["id"], make_examiner_headers("ex_863")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = get_retrieval(ctx["retrieval"]["id"])
        assert after["status"] == "REQUESTED", "rejected posting leaves the retrieval untouched"

    def test_per_page_retrieval_without_page_count_rejected(self, api):
        """PRD §3.9: "a `PER_PAGE` request without a `page_count` of at least 1 is
        rejected with `ERR_PAGE_COUNT_INVALID` (HTTP 422), while for the
        per-document mode the field is ignored."

        Design: Corner/validations/per_page_retrieval_without_page_count_rejected
        """
        ctx = setup_order_with_assignment("client_829", "abs_829")
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_829",
            instrument_number="INST-829-A", recording_date="2001-01-01",
        )
        resp = api.create_county_retrieval(
            create_retrieval_payload(
                ctx["order"]["id"], doc["id"], county="Travis", fee_mode="PER_PAGE"
            ),
            make_abstracter_headers("abs_829"),
        )
        validate_error(resp, ApiErrorId.ERR_PAGE_COUNT_INVALID)

    def test_reverse_invoiced_fee_rejected(self, api):
        """PRD §3.9: "Posting against a retrieval already in `FEE_POSTED` or
        `FEE_REVERSED` is refused with `ERR_FEE_ALREADY_POSTED` (HTTP 409); posting
        against an `INVOICED` retrieval, or reversing one, is refused with
        `ERR_ALREADY_INVOICED` (HTTP 409) — an invoiced fee can never be touched."

        Design: Corner/validations/reverse_invoiced_fee_rejected
        """
        ctx = setup_delivered_order(
            "client_830", "abs_830", "ex_830",
            retrieval_specs=[{"fee_mode": "PER_DOCUMENT"}],
        )
        retrieval = ctx["retrievals"][0]
        assert get_retrieval(retrieval["id"])["status"] == "INVOICED", "scenario precondition"

        resp = api.reverse_retrieval_fee(
            retrieval["id"], {"reason": "attempted post-invoice reversal"}, make_ops_headers()
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_INVOICED)


class TestFeeCompensatingPair:
    def _setup_rush_order_with_requested_retrieval(self, api):
        ctx = setup_order_with_assignment("client_781", "abs_781", sla_tier="RUSH")
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_781",
            instrument_number="INST-781-A", recording_date="2010-01-01",
        )
        retrieval = create_retrieval(
            ctx["order"]["id"], doc["id"], "abs_781", fee_mode="PER_DOCUMENT"
        )
        ctx["document"] = doc
        ctx["retrieval"] = retrieval
        return ctx

    def test_posting_fee_recomputes_running_fee_and_cap(self, api):
        """PRD §3.9: "Posting then recomputes the order's running fee per §2.6: the
        base fee of 40000 cents plus the sum of `fee_cents` over every retrieval of
        the order in `FEE_POSTED` or `INVOICED` status — `REQUESTED` retrievals
        carry no fee and `FEE_REVERSED` retrievals are excluded — plus, for `RUSH`
        orders only, the twenty-five-percent premium computed once on that whole
        subtotal and rounded half up; the liability cap is recomputed alongside."

        Design: Difficulty/compensating_invariant/fee_post_then_reverse_conserves_accrued_fees
        """
        ctx = self._setup_rush_order_with_requested_retrieval(api)
        assert ctx["order"]["accrued_fees_cents"] == 50000, (
            f"RUSH init = 40000 + 25%*40000, got {ctx['order']['accrued_fees_cents']}"
        )

        post_fee(ctx["retrieval"]["id"])
        order = get_order(ctx["order"]["id"])
        assert order["accrued_fees_cents"] == 53125, (
            f"42500 + round_half_up(42500*0.25)=10625, got {order['accrued_fees_cents']}"
        )
        assert order["liability_cap_cents"] == 159375, (
            f"min(3*53125, 200000), got {order['liability_cap_cents']}"
        )

    def test_reversing_posted_fee_restores_running_fee_and_cap_exactly(self, api):
        """PRD §2.6: "Posting a fee and later reversing it is a compensating pair —
        after the pair, `accrued_fees_cents` returns to exactly the value it held
        before the post."

        Design: Difficulty/compensating_invariant/fee_post_then_reverse_conserves_accrued_fees
        """
        ctx = self._setup_rush_order_with_requested_retrieval(api)
        baseline = ctx["order"]["accrued_fees_cents"]
        assert baseline == 50000

        post_fee(ctx["retrieval"]["id"])
        reversed_retrieval = reverse_fee(ctx["retrieval"]["id"], "county rejected the pull")
        assert reversed_retrieval["status"] == "FEE_REVERSED"

        order = get_order(ctx["order"]["id"])
        assert order["accrued_fees_cents"] == baseline, (
            f"post + reverse conserves the fee total exactly, got {order['accrued_fees_cents']}"
        )
        assert order["liability_cap_cents"] == 150000, (
            f"cap tracks the conserved quantity: min(3*50000, 200000), got {order['liability_cap_cents']}"
        )
