"""Buyer credit standing: the two exposure variants on the customer projection.

The same customer data feeds two figures that deliberately disagree — the
backward-looking settled receivable and the forward-looking conservative
exposure that adds unbilled stems valued at the current index price.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    OPS,
    add_confirmed_nomination,
    add_customer,
    add_nomination,
    api_client,
    apply_credit_review,
    assert_credit_exposure,
    build_confirmed_nomination,
    build_issued_invoice,
    build_reference_data,
    create_nomination_payload,
    read_credit_exposure,
    read_customer,
    read_nomination,
    submit_compliance_decision,
    validate_error,
    validate_success,
)

TIED_QUOTE_DATE = "2026-08-03T00:00:00Z"
TIED_QUOTES = [
    {"quote_date": TIED_QUOTE_DATE, "price_usd_per_mt": 705.00},
    {"quote_date": TIED_QUOTE_DATE, "price_usd_per_mt": 800.00},
]

BOUNDARY_QUOTE = {"quote_date": "2026-08-01T00:00:00Z", "price_usd_per_mt": 705.00}
EXACT_LIMIT_USD = 846000.00
SHORT_LIMIT_USD = 845999.99

WATCH_LIMIT_USD = 1000000.00
HOLD_LIMIT_USD = 900000.00
SETTLED_RECEIVABLE_USD = 941193.73


def _settled_and_committed_context():
    """One delivered, billed stem plus one confirmed, unbilled stem.

    Stem 1 for 1200.000 mt is delivered, noted and invoiced, and its invoice has
    been issued at 941193.73, closing that nomination. Stem 2 for 1000.000 mt is
    approved and confirmed with no delivery order and no invoice, so it sits in
    the open-commitment set. The logical clock rests at 2026-08-10T14:30:00Z, so
    the governing quote for the grade is 745.50.
    """
    ctx = build_issued_invoice()
    add_confirmed_nomination(
        ctx,
        store_as="unbilled_nomination",
        nominated_quantity_mt=1000.000,
        vessel_imo="9654321",
        vessel_name="MV Boreas",
        eca_documentation_ref="CHG-2026-0002",
    )
    return ctx


class TestCreditExposureVariants:
    """The settled and conservative variants of one exposure calculation."""

    def test_settled_receivable_counts_only_issued_invoices(self):
        """PRD §3.2: "The **settled receivables** figure is the sum, rounded to
        two decimal places, of `final_amount_usd` across every invoice belonging
        to the customer whose status is `ISSUED` or `CREDIT_APPLIED`; invoices
        that are still `PROVISIONAL` and invoices that have been made `VOID` are
        excluded entirely."
        PRD §3.2: "That figure is written to `outstanding_balance_usd` — the
        backward-looking books view, which counts only money actually invoiced,
        so a customer holding large unbilled stems still reads a comfortable
        standing."

        Design: Difficulty/dual_variant_calc/credit_exposure_conservative_vs_settled_divergence
        """
        ctx = _settled_and_committed_context()

        exposure = read_credit_exposure(ctx)

        assert_credit_exposure(exposure)
        assert exposure["outstanding_balance_usd"] == pytest.approx(941193.73, abs=0.01), (
            "Expected the single issued invoice's final amount as the settled "
            f"receivable, got {exposure['outstanding_balance_usd']}"
        )

    def test_conservative_exposure_adds_unbilled_stem_at_index_price(self):
        """PRD §3.2: "The **conservative exposure** written to
        `conservative_exposure_usd` is the settled receivables plus the open
        commitments, rounded to two decimal places; because it adds unbilled
        commitments on top of invoiced money, it is strictly larger than the
        settled figure whenever an unbilled confirmed stem exists."
        PRD §3.2: "Each qualifying nomination is valued at its
        `nominated_quantity_mt` multiplied by the governing index price of its
        grade at the current logical clock, and the sum is rounded to two decimal
        places."

        Design: Difficulty/dual_variant_calc/credit_exposure_conservative_vs_settled_divergence
        """
        ctx = _settled_and_committed_context()

        exposure = read_credit_exposure(ctx)

        assert exposure["conservative_exposure_usd"] == pytest.approx(1686693.73, abs=0.01), (
            "Expected settled receivables plus the unbilled stem, got "
            f"{exposure['conservative_exposure_usd']}"
        )
        divergence = (
            exposure["conservative_exposure_usd"] - exposure["outstanding_balance_usd"]
        )
        assert divergence == pytest.approx(745500.00, abs=0.01), (
            "Expected the 1000.000 mt unbilled stem valued at the 745.50 quote, "
            f"got a divergence of {divergence}"
        )
        assert exposure["open_commitment_count"] == 1, (
            "Expected exactly the confirmed unbilled stem in the commitment set, "
            f"got {exposure['open_commitment_count']}"
        )

    def test_available_credit_and_standing_read_from_different_figures(self):
        """PRD §3.2: "`available_credit_usd` is the customer's `credit_limit_usd`
        minus that conservative exposure, rounded to two decimal places, and is
        permitted to be negative."
        PRD §3.2: "Credit standing, however, is derived from the **settled**
        figure alone, not the conservative one."
        PRD §3.2: "When utilisation is at least 1.0000 the `credit_status`
        becomes `HOLD`; when it is at least 0.8000 but below 1.0000 it becomes
        `WATCH`; otherwise it is `OK`."

        Design: Difficulty/dual_variant_calc/credit_exposure_conservative_vs_settled_divergence
        """
        ctx = _settled_and_committed_context()

        exposure = read_credit_exposure(ctx)

        assert exposure["available_credit_usd"] == pytest.approx(3313306.27, abs=0.01), (
            "Expected the credit limit less the conservative exposure, got "
            f"{exposure['available_credit_usd']}"
        )
        assert exposure["credit_status"] == "OK", (
            "Settled utilisation is well below 0.8000, so the standing must stay "
            f"OK, got {exposure['credit_status']}"
        )


class TestGoverningQuoteTieBreak:
    """Two quotes bearing the same `quote_date`: the later posting governs."""

    def test_the_most_recently_posted_of_two_same_day_quotes_prices_the_stem(self):
        """PRD §2.12: "Whenever the system needs the governing price of a grade at a
        given instant, it selects the quote for that grade whose `quote_date` is the
        greatest value at or before that instant."
        PRD §2.12: "When two such quotes share the same `quote_date`, the one with the
        later `created_at` wins — the most recently posted quote governs."
        PRD §3.2: "Each qualifying nomination is valued at its `nominated_quantity_mt`
        multiplied by the governing index price of its grade at the current logical
        clock, and the sum is rounded to two decimal places."

        Both quotes are dated 2026-08-03 and the 800.00 one was posted second, so a
        1000.000 mt commitment must value at 800000.00 rather than 705000.00.

        Design: Corner/calculations/index_quote_tie_break_by_created_at
        """
        ctx = build_confirmed_nomination(
            quotes=TIED_QUOTES, nomination={"nominated_quantity_mt": 1000.000}
        )

        exposure = read_credit_exposure(ctx)

        assert_credit_exposure(exposure)
        assert exposure["conservative_exposure_usd"] == pytest.approx(
            800000.00, abs=0.01
        ), (
            "1000.000 mt at the later-posted 800.00 quote is 800000.00, got "
            f"{exposure['conservative_exposure_usd']}"
        )
        assert exposure["open_commitment_count"] == 1, (
            "The single confirmed stem is the only commitment, got "
            f"{exposure['open_commitment_count']}"
        )
        assert exposure["outstanding_balance_usd"] == pytest.approx(0.00, abs=0.01), (
            "Nothing has been invoiced, got "
            f"{exposure['outstanding_balance_usd']}"
        )
        assert exposure["available_credit_usd"] == pytest.approx(4200000.00, abs=0.01), (
            "5000000.00 less 800000.00 is 4200000.00, got "
            f"{exposure['available_credit_usd']}"
        )
        assert exposure["credit_status"] == "OK", (
            "Standing reads the settled figure alone, which is zero, got "
            f"{exposure['credit_status']}"
        )


class TestConservativeCreditCheckBoundary:
    """A prospective exposure exactly equal to the limit passes; a cent more fails."""

    def _two_buyers_at_the_boundary(self):
        """Two approved DRAFT stems of 1200.000 mt, priced at 705.00.

        One buyer's limit is exactly the 846000.00 the stem would commit, the
        other's is one cent short.
        """
        ctx = build_reference_data(
            customer={"name": "Exact Line", "credit_limit_usd": EXACT_LIMIT_USD},
            quotes=[BOUNDARY_QUOTE],
        )
        ctx["short_customer"] = add_customer(
            name="Short Line", credit_limit_usd=SHORT_LIMIT_USD
        )
        add_nomination(
            ctx,
            vessel_imo="9445566",
            vessel_name="MV Exactus",
            eca_documentation_ref="CHG-2026-0004",
        )
        submit_compliance_decision(ctx, "APPROVE")
        ctx["exact_nomination"] = ctx["nomination"]
        short = validate_success(
            api_client.create_nomination(
                create_nomination_payload(
                    ctx["short_customer"]["id"],
                    ctx["port"]["id"],
                    ctx["grade"]["id"],
                    vessel_imo="9556677",
                    vessel_name="MV Brevis",
                    eca_documentation_ref="CHG-2026-0005",
                ),
                OPS,
            ),
            201,
        )
        ctx["short_nomination"] = submit_compliance_decision(
            ctx, "APPROVE", nomination_id=short["id"]
        )
        return ctx

    def test_a_prospective_exposure_equal_to_the_limit_passes(self):
        """PRD §3.4: "The comparison is deliberately generous at the boundary: a
        prospective exposure exactly equal to `credit_limit_usd` passes, and only an
        exposure strictly greater than the limit fails."
        PRD §3.4: "The prospective commitment of the addressed nomination is its
        `nominated_quantity_mt` multiplied by the governing index price of its grade at
        the current logical clock, rounded to two decimal places."
        PRD §3.2: "`available_credit_usd` is the customer's `credit_limit_usd` minus
        that conservative exposure, rounded to two decimal places, and is permitted to be
        negative."

        1200.000 mt at 705.00 is exactly the buyer's 846000.00 limit, which leaves no
        headroom at all but breaks no rule.

        Design: Corner/calculations/credit_availability_boundary_at_exact_limit
        """
        ctx = self._two_buyers_at_the_boundary()

        confirmed = validate_success(
            api_client.confirm_nomination(ctx["exact_nomination"]["id"], OPS)
        )

        assert confirmed["fulfillment_status"] == "CONFIRMED", (
            f"The boundary stem must confirm, got {confirmed['fulfillment_status']}"
        )
        exposure = read_credit_exposure(ctx)
        assert exposure["conservative_exposure_usd"] == pytest.approx(
            EXACT_LIMIT_USD, abs=0.01
        ), (
            "The committed stem must value at exactly the limit, got "
            f"{exposure['conservative_exposure_usd']}"
        )
        assert exposure["available_credit_usd"] == pytest.approx(0.00, abs=0.01), (
            "The buyer must be left with no headroom at all, got "
            f"{exposure['available_credit_usd']}"
        )

    def test_a_limit_one_cent_short_of_the_commitment_fails(self):
        """PRD §3.4: "It moves `fulfillment_status` from `DRAFT` to `CONFIRMED` and is
        gated by three conditions in addition to the state check: the nomination's
        `compliance_status` must already be `APPROVED`, or the request is rejected with
        `ERR_COMPLIANCE_NOT_APPROVED`; the customer's `credit_status` must not be
        `HOLD`, or the request is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; and the
        conservative credit check must pass, or the request is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
        PRD §3.4: "The comparison is deliberately generous at the boundary: a
        prospective exposure exactly equal to `credit_limit_usd` passes, and only an
        exposure strictly greater than the limit fails."

        The second buyer's limit of 845999.99 is a single cent below the same
        846000.00 commitment, which is enough to fail.

        Design: Corner/calculations/credit_availability_boundary_at_exact_limit
        """
        ctx = self._two_buyers_at_the_boundary()
        short_stem = ctx["short_nomination"]

        response = api_client.confirm_nomination(short_stem["id"], OPS)

        validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        after = read_nomination(nomination_id=short_stem["id"])
        assert after["fulfillment_status"] == "DRAFT", (
            f"The refused stem must stay in DRAFT, got {after['fulfillment_status']}"
        )
        assert after["version"] == short_stem["version"], (
            f"A refused confirmation must not move the version, expected "
            f"{short_stem['version']}, got {after['version']}"
        )
        exposure = read_credit_exposure(customer_id=ctx["short_customer"]["id"])
        assert exposure["open_commitment_count"] == 0, (
            "A DRAFT stem never enters the commitment set, got "
            f"{exposure['open_commitment_count']}"
        )


class TestCreditReviewPartialUpdate:
    """The review replaces only what it names and re-derives standing each time."""

    def test_revising_only_the_limit_leaves_the_other_terms_alone(self):
        """PRD §3.2: "Both terms may later be revised by a periodic credit review,
        which accepts an optional replacement `credit_limit_usd`, an optional replacement
        `settlement_basis`, re-derives the customer's credit standing from settled
        receivables, and increments the customer's `version` by one."
        PRD §3.2: "Utilisation is the settled receivables divided by
        `credit_limit_usd`, rounded to four decimal places."
        PRD §3.2: "When utilisation is at least 1.0000 the `credit_status` becomes
        `HOLD`; when it is at least 0.8000 but below 1.0000 it becomes `WATCH`;
        otherwise it is `OK`."

        A 941193.73 receivable against the original 5000000.00 limit is 0.1882, but
        against a 1000000.00 limit it is 0.9412 — inside the watch band without any
        invoice changing.

        Design: Corner/endpoints/credit_review_partial_update_and_status_rederivation
        """
        ctx = build_issued_invoice()
        before = read_customer(ctx)
        assert before["outstanding_balance_usd"] == pytest.approx(
            SETTLED_RECEIVABLE_USD, abs=0.01
        ), (
            "The issued invoice must be the whole receivable, got "
            f"{before['outstanding_balance_usd']}"
        )
        assert before["credit_status"] == "OK", (
            f"Utilisation of 0.1882 is OK, got {before['credit_status']}"
        )

        revised = apply_credit_review(ctx, credit_limit_usd=WATCH_LIMIT_USD)

        assert revised["credit_limit_usd"] == pytest.approx(WATCH_LIMIT_USD, abs=0.01), (
            f"The named term must be replaced, got {revised['credit_limit_usd']}"
        )
        assert revised["credit_status"] == "WATCH", (
            f"Utilisation of 0.9412 is a watch, got {revised['credit_status']}"
        )
        assert revised["settlement_basis"] == before["settlement_basis"], (
            "An unnamed term must be left alone, expected "
            f"{before['settlement_basis']}, got {revised['settlement_basis']}"
        )
        assert revised["payment_terms_days"] == before["payment_terms_days"], (
            "An unnamed term must be left alone, expected "
            f"{before['payment_terms_days']}, got {revised['payment_terms_days']}"
        )
        assert revised["version"] == before["version"] + 1, (
            f"The review increments the version once, expected "
            f"{before['version'] + 1}, got {revised['version']}"
        )

    def test_a_limit_below_the_receivable_holds_the_buyer_and_goes_negative(self):
        """PRD §3.2: "`available_credit_usd` is the customer's `credit_limit_usd` minus
        that conservative exposure, rounded to two decimal places, and is permitted to be
        negative."
        PRD §3.2: "When utilisation is at least 1.0000 the `credit_status` becomes
        `HOLD`; when it is at least 0.8000 but below 1.0000 it becomes `WATCH`;
        otherwise it is `OK`."
        PRD §3.2: "Its input set is the customer's nominations whose
        `fulfillment_status` is `CONFIRMED`, `SCHEDULED`, `AWAITING_SCHEDULE` or
        `DELIVERED` and for which no delivery order carries an invoice in status
        `ISSUED` or `CREDIT_APPLIED`; nominations still in `DRAFT` and nominations
        already `CLOSED` are excluded."

        With the stem closed by issuance there is no open commitment left, so the
        conservative exposure equals the settled receivable and a 900000.00 limit
        leaves the buyer 41193.73 in deficit.

        Design: Corner/endpoints/credit_review_partial_update_and_status_rederivation
        """
        ctx = build_issued_invoice()
        apply_credit_review(ctx, credit_limit_usd=WATCH_LIMIT_USD)
        watched_version = ctx["customer"]["version"]

        held = apply_credit_review(ctx, credit_limit_usd=HOLD_LIMIT_USD)

        assert held["credit_status"] == "HOLD", (
            f"Utilisation of 1.0458 is a hold, got {held['credit_status']}"
        )
        assert held["version"] == watched_version + 1, (
            f"The second review increments the version again, expected "
            f"{watched_version + 1}, got {held['version']}"
        )
        exposure = read_credit_exposure(ctx)
        assert exposure["outstanding_balance_usd"] == pytest.approx(
            SETTLED_RECEIVABLE_USD, abs=0.01
        ), (
            "The receivable is untouched by a review, got "
            f"{exposure['outstanding_balance_usd']}"
        )
        assert exposure["open_commitment_count"] == 0, (
            "The closed stem is outside the commitment set, got "
            f"{exposure['open_commitment_count']}"
        )
        assert exposure["conservative_exposure_usd"] == pytest.approx(
            SETTLED_RECEIVABLE_USD, abs=0.01
        ), (
            "With no open commitment the two exposure variants coincide, got "
            f"{exposure['conservative_exposure_usd']}"
        )
        assert exposure["available_credit_usd"] == pytest.approx(-41193.73, abs=0.01), (
            "900000.00 less 941193.73 is -41193.73, got "
            f"{exposure['available_credit_usd']}"
        )
