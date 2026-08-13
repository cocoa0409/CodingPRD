"""Year-end 1099 reporting: generation threshold and cash-vs-accrual totals
(PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_tax_form_1099,
    create_and_mark_payout_paid,
    create_carrier,
    create_policy,
    create_producer,
    create_product,
    create_schedule,
    create_statement,
    deliver_policy_disclosure,
    bind_policy,
    get_single_entry,
    setup_bound_policy,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestForm1099Threshold:
    """Difficulty instance: the cash-basis generation threshold is >= 60000
    cents — exactly 60000 qualifies, 59999 does not."""

    def _setup_two_producers(self):
        carrier = create_carrier(name="Carrier 9", carrier_code="C9")
        product = create_product(carrier["id"], product_code="P9")
        create_schedule(product["id"], commission_rate_bps=5000)
        producers = {}
        for name, lic, pol, payout in (
            ("Writer 9A", "LIC-9A", "P-9A", 60000),
            ("Writer 9B", "LIC-9B", "P-9B", 59999),
        ):
            producer = create_producer(
                name=name, license_number=lic, tax_form_on_file=True
            )
            policy = create_policy(
                product["id"],
                producer["id"],
                policy_number=pol,
                premium_annual_cents=2400000,
            )
            deliver_policy_disclosure(policy["id"])
            bind_policy(policy["id"])
            create_and_mark_payout_paid(producer["id"], payout)
            producers[name] = producer
        return producers

    def test_exactly_60000_generates_draft(self):
        """PRD §3.9: "A `DRAFT` form is created for a producer exactly when
        that producer's cash-basis total for the year is at least $600.00
        (60000 cents — a total of 59999 cents does not qualify) and no form
        in any status already exists for that producer and year; producers
        below the threshold or already holding a form are skipped."
        PRD §3.9: "The response reports `generated_count` alongside the
        `tax_form_ids` created, and each form's totals are computed as of
        generation."

        Design: Difficulty/boundary_precision_check/form_1099_threshold_exact_60000
        """
        producers = self._setup_two_producers()
        result = validate_success(
            api_client.generate_tax_forms({"tax_year": 2026}, ADMIN), 200
        )
        assert result["generated_count"] == 1

        forms, meta = validate_paginated(
            api_client.list_tax_forms(
                ADMIN,
                params={"producer_id": producers["Writer 9A"]["id"], "tax_year": 2026},
            )
        )
        assert len(forms) == 1
        assert_tax_form_1099(forms[0])
        assert forms[0]["status"] == "DRAFT"
        assert forms[0]["cash_basis_total_cents"] == 60000

    def test_59999_does_not_generate(self):
        """PRD §3.9: "A `DRAFT` form is created for a producer exactly when
        that producer's cash-basis total for the year is at least $600.00
        (60000 cents — a total of 59999 cents does not qualify) and no form
        in any status already exists for that producer and year; producers
        below the threshold or already holding a form are skipped."

        Design: Difficulty/boundary_precision_check/form_1099_threshold_exact_60000
        """
        producers = self._setup_two_producers()
        result = validate_success(
            api_client.generate_tax_forms({"tax_year": 2026}, ADMIN), 200
        )
        assert result["generated_count"] == 1

        forms, meta = validate_paginated(
            api_client.list_tax_forms(
                ADMIN,
                params={"producer_id": producers["Writer 9B"]["id"], "tax_year": 2026},
            )
        )
        assert forms == []
        assert meta["total_count"] == 0


class TestCashVsAccrualBasis:
    """Difficulty instance: the same producer-year reports two diverging
    totals — payouts actually paid (cash) versus entries matched against
    carrier statements (accrual)."""

    def _setup_producer_with_variance(self):
        bundle = setup_bound_policy(
            premium_annual_cents=3000000,
            commission_rate_bps=5000,
            policy_number="P-T1",
            producer_overrides={"tax_form_on_file": True},
        )
        # Cash basis: one 90000 payout marked PAID at the clock default
        # (2026-08-01, inside tax year 2026).
        create_and_mark_payout_paid(bundle["producer"]["id"], 90000)

        # Accrual basis: the carrier reports 140000 for the policy; the
        # |140000 - 1500000| shortfall flags VARIANCE, and accepting 140000
        # matches the BASE entry (1500000) and books a MATCHED negative
        # VARIANCE_ADJUSTMENT.
        statement = create_statement(
            bundle["carrier"]["id"],
            [
                {
                    "line_ref": bundle["policy"]["policy_number"],
                    "reported_amount_cents": 140000,
                }
            ],
        )
        validate_success(api_client.start_reconciliation(statement["id"], ADMIN), 200)
        entry = get_single_entry(bundle["policy"]["id"], "BASE")
        validate_success(
            api_client.resolve_variance(
                entry["id"], {"accept_amount_cents": 140000}, ADMIN
            ),
            200,
        )
        return bundle

    def test_generation_counts_cash_basis(self):
        """PRD §3.9: "The `cash_basis_total_cents` sums the `amount_cents` of
        the producer's payouts in `PAID` status whose `paid_at` falls within
        the tax year — from January 1 of the `tax_year` inclusive up to but
        excluding January 1 of the following year."
        PRD §3.9: "A `DRAFT` form is created for a producer exactly when that
        producer's cash-basis total for the year is at least $600.00 (60000
        cents — a total of 59999 cents does not qualify) and no form in any
        status already exists for that producer and year; producers below the
        threshold or already holding a form are skipped."

        Design: Difficulty/dual_variant_calc/cash_vs_accrual_1099_basis
        """
        bundle = self._setup_producer_with_variance()
        result = validate_success(
            api_client.generate_tax_forms({"tax_year": 2026}, ADMIN), 200
        )
        assert result["generated_count"] == 1

        forms, _ = validate_paginated(
            api_client.list_tax_forms(
                ADMIN,
                params={"producer_id": bundle["producer"]["id"], "tax_year": 2026},
            )
        )
        assert len(forms) == 1
        assert forms[0]["cash_basis_total_cents"] == 90000

    def test_accrual_basis_diverges_from_cash(self):
        """PRD §3.9: "The `accrual_basis_total_cents` sums the `amount_cents`
        of the producer's commission entries in `MATCHED` status whose
        `matched_at` falls within the tax year, across all entry types,
        including negative `VARIANCE_ADJUSTMENT` amounts. Identical producer
        data therefore yields two different totals on the same form: cash
        actually paid versus commissions matched against carrier
        statements."

        Design: Difficulty/dual_variant_calc/cash_vs_accrual_1099_basis
        """
        bundle = self._setup_producer_with_variance()
        validate_success(api_client.generate_tax_forms({"tax_year": 2026}, ADMIN), 200)
        forms, _ = validate_paginated(
            api_client.list_tax_forms(
                ADMIN,
                params={"producer_id": bundle["producer"]["id"], "tax_year": 2026},
            )
        )
        assert len(forms) == 1
        form = forms[0]
        # MATCHED entries: BASE 1500000 + VARIANCE_ADJUSTMENT -1360000.
        assert form["accrual_basis_total_cents"] == 140000
        assert form["cash_basis_total_cents"] == 90000
        assert form["cash_basis_total_cents"] != form["accrual_basis_total_cents"]
