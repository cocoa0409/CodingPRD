"""E&P ledger: preview variants, current-vs-frozen balance views, post
semantics, and the post/declare compensating pair (PRD §3.6, §3.7, §3.10)."""
from test_helpers import (
    assert_ep_adjustment,
    create_declared_dividend,
    create_posted_ep_adjustment,
    create_posted_requirement,
    create_quarter,
    create_reit,
    get_reit,
    setup_reit_with_ep_balance,
    setup_reit_with_open_quarter,
    validate_success,
)


class TestCharacterizationPreviewVariants:
    """E&P 600000, capital-gain pool 400000, hypothetical amount 800000."""

    def _setup_preview_reit(self):
        reit, quarter = setup_reit_with_open_quarter()
        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=600_000,
                                    effective_date="2026-02-01")
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=1_000_000,
                                  net_capital_gain_cents=400_000)
        return reit

    def test_waterfall_preview(self, api, tax_director_headers):
        """PRD §3.10: "The default mode is the waterfall described in §3.6 —
        ordinary income keyed to the REIT's current E&P balance first (conduit
        theory), then the capital-gain pool, then return of capital."
        PRD §3.10: the preview "takes an `amount_cents`, a `taxable_year`,
        and an optional `mode`, and returns `ordinary_cents`,
        `capital_gain_cents`, `return_of_capital_cents`, and the `mode`
        echoed back."

        Design: Difficulty/dual_variant_calc/dividend_characterization_waterfall_vs_pro_rata
        """
        reit = self._setup_preview_reit()
        resp = api.get_dividend_characterization_preview(
            reit["id"], tax_director_headers,
            params={"amount_cents": 800_000, "taxable_year": 2026,
                    "mode": "WATERFALL"},
        )
        data = validate_success(resp, 200)
        assert data["ordinary_cents"] == 600_000
        assert data["capital_gain_cents"] == 200_000
        assert data["return_of_capital_cents"] == 0
        assert data["mode"] == "WATERFALL"

    def test_pro_rata_preview_diverges(self, api, tax_director_headers):
        """PRD §3.10: "The alternative `PRO_RATA` mode reports what the
        characterization would be under a pro-rata allocation:
        `ordinary_cents` becomes the gross amount multiplied by the ratio of
        the clamped E&P balance to the sum of the clamped E&P balance and the
        clamped capital-gain pool, rounded half-up to whole cents (or 0 when
        that denominator is zero), `capital_gain_cents` becomes the remainder
        capped at the pool, and return of capital absorbs whatever is left."

        Design: Difficulty/dual_variant_calc/dividend_characterization_waterfall_vs_pro_rata
        """
        reit = self._setup_preview_reit()
        waterfall = validate_success(
            api.get_dividend_characterization_preview(
                reit["id"], tax_director_headers,
                params={"amount_cents": 800_000, "taxable_year": 2026,
                        "mode": "WATERFALL"},
            ),
            200,
        )
        pro_rata = validate_success(
            api.get_dividend_characterization_preview(
                reit["id"], tax_director_headers,
                params={"amount_cents": 800_000, "taxable_year": 2026,
                        "mode": "PRO_RATA"},
            ),
            200,
        )
        assert pro_rata["ordinary_cents"] == 480_000
        assert pro_rata["capital_gain_cents"] == 320_000
        assert pro_rata["return_of_capital_cents"] == 0
        assert pro_rata["mode"] == "PRO_RATA"
        assert waterfall["ordinary_cents"] != pro_rata["ordinary_cents"]


class TestEpBalanceVariants:
    """Ledger: +500000 TAXABLE_INCOME (2026-01-10), +100000
    DISALLOWED_DEDUCTION (2026-03-31), -50000 FEDERAL_TAX (2027-01-15)."""

    def _setup_ledger(self):
        reit = create_reit(legal_name="EP REIT")
        q26 = create_quarter(reit["id"], label="2026-Q1",
                             period_start="2026-01-01", period_end="2026-03-31")
        q27 = create_quarter(reit["id"], label="2027-Q1",
                             period_start="2027-01-01", period_end="2027-03-31")
        create_posted_ep_adjustment(reit["id"], q26["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=500_000,
                                    effective_date="2026-01-10")
        create_posted_ep_adjustment(reit["id"], q26["id"],
                                    kind="DISALLOWED_DEDUCTION",
                                    amount_cents=100_000,
                                    effective_date="2026-03-31")
        create_posted_ep_adjustment(reit["id"], q27["id"], kind="FEDERAL_TAX",
                                    amount_cents=50_000,
                                    effective_date="2027-01-15")
        return reit

    def test_current_view_includes_all_posted(self, api, tax_director_headers):
        """PRD §3.7: "The default is the live running balance just described."
        PRD §3.7: "walk every `POSTED` adjustment for the REIT ordered by
        `effective_date` ascending with `created_at` ascending as the
        tie-break (never `id`), adding `amount_cents` for `TAXABLE_INCOME` and
        `DISALLOWED_DEDUCTION` and subtracting for `FEDERAL_TAX`".

        Design: Difficulty/dual_variant_calc/ep_balance_current_vs_frozen_year_end
        """
        reit = self._setup_ledger()
        data = validate_success(
            api.get_ep_balance(reit["id"], tax_director_headers), 200
        )
        assert data["ep_balance_cents"] == 550_000
        assert isinstance(data["variant"], str) and data["variant"]

    def test_frozen_year_end_view_excludes_late_accruals(
            self, api, tax_director_headers):
        """PRD §3.7: "The frozen year-end view, selected by passing an `as_of`
        query parameter set to a taxable year's last day, replays only
        adjustments whose `effective_date` falls on or before that boundary
        and ignores later adjustments entirely — no late-arrival inclusion —
        so the same ledger yields a smaller balance whenever late accruals
        exist."

        Design: Difficulty/dual_variant_calc/ep_balance_current_vs_frozen_year_end
        """
        reit = self._setup_ledger()
        current = validate_success(
            api.get_ep_balance(reit["id"], tax_director_headers), 200
        )
        frozen = validate_success(
            api.get_ep_balance(reit["id"], tax_director_headers,
                               params={"as_of": "2026-12-31"}),
            200,
        )
        assert frozen["ep_balance_cents"] == 600_000
        assert current["ep_balance_cents"] == 550_000
        assert frozen["ep_balance_cents"] != current["ep_balance_cents"]


def test_ep_adjustment_draft_then_post(api, tax_director_headers):
    """PRD §3.7: "A fresh adjustment lands in `DRAFT`, and creating one
    increments the REIT's `version` by one."
    PRD §3.7: "Posting folds the adjustment into the running balance."

    Design: Corner/state_machines/ep_adjustment_initial_state_draft_and_post_transition
    """
    reit, quarter = setup_reit_with_open_quarter()
    draft = validate_success(
        api.create_ep_adjustment(
            {
                "reit_id": reit["id"],
                "quarter_id": quarter["id"],
                "kind": "TAXABLE_INCOME",
                "amount_cents": 42_000,
                "effective_date": "2026-02-01",
                "expected_reit_version": get_reit(reit["id"])["version"],
            },
            tax_director_headers,
        ),
        201,
    )
    assert_ep_adjustment(draft)
    assert draft["status"] == "DRAFT"
    assert get_reit(reit["id"])["current_ep_balance_cents"] == 0

    posted = validate_success(
        api.post_ep_adjustment(draft["id"], tax_director_headers), 200
    )
    assert posted["status"] == "POSTED"
    assert get_reit(reit["id"])["current_ep_balance_cents"] == 42_000


class TestEpPostAndDeclareConserve:
    def test_post_then_full_declare_restores_balance(
            self, api, compliance_officer_headers):
        """PRD §3.7: "When the director posts a `DRAFT` adjustment, the system
        recomputes the REIT's `current_ep_balance_cents` by chronological
        replay: walk every `POSTED` adjustment for the REIT ordered by
        `effective_date` ascending with `created_at` ascending as the
        tie-break (never `id`), adding `amount_cents` for `TAXABLE_INCOME` and
        `DISALLOWED_DEDUCTION` and subtracting for `FEDERAL_TAX`, then
        subtract the sum of `ordinary_cents` over all declarations for the
        REIT in `DECLARED` or `PAID` status."
        PRD §3.6: "the E&P balance is debited immediately by
        `ordinary_cents`."

        Design: Difficulty/compensating_invariant/ep_balance_post_and_dividend_debit_conserve
        """
        reit, quarter = setup_reit_with_open_quarter()
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=900_000,
                                  net_capital_gain_cents=0)
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 0

        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=500_000,
                                    effective_date="2026-01-20")
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 500_000

        declared = create_declared_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=500_000)
        assert declared["ordinary_cents"] == 500_000
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 0

    def test_partial_declare_then_pay_leaves_balance(
            self, api, compliance_officer_headers):
        """PRD §3.6: "A `ComplianceOfficer` pays a declaration that is in
        `DECLARED`; no E&P change occurs because the allocation already
        happened at declare time, and the requirement's amounts are
        unchanged."

        Design: Difficulty/compensating_invariant/ep_balance_post_and_dividend_debit_conserve
        """
        reit, quarter = setup_reit_with_open_quarter()
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=900_000,
                                  net_capital_gain_cents=0)
        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME",
                                    amount_cents=500_000,
                                    effective_date="2026-01-20")
        declared = create_declared_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=200_000)
        assert declared["ordinary_cents"] == 200_000
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 300_000

        paid = validate_success(
            api.pay_dividend_declaration(declared["id"],
                                         compliance_officer_headers),
            200,
        )
        assert paid["status"] == "PAID"
        assert get_reit(reit["id"])["current_ep_balance_cents"] == 300_000


def test_post_immediately_visible(api, tax_director_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.7: "Posting folds the adjustment into the running balance."

    Design: Corner/consistency_model/mutation_visible_in_same_response
    """
    reit, quarter = setup_reit_with_open_quarter()
    draft = validate_success(
        api.create_ep_adjustment(
            {
                "reit_id": reit["id"],
                "quarter_id": quarter["id"],
                "kind": "DISALLOWED_DEDUCTION",
                "amount_cents": 77_000,
                "effective_date": "2026-01-10",
                "expected_reit_version": get_reit(reit["id"])["version"],
            },
            tax_director_headers,
        ),
        201,
    )
    posted = validate_success(
        api.post_ep_adjustment(draft["id"], tax_director_headers), 200
    )
    assert posted["status"] == "POSTED"
    follow_up = validate_success(api.get_reit(reit["id"], tax_director_headers),
                                 200)
    assert follow_up["current_ep_balance_cents"] == 77_000
