"""State composite filings: per-partner rounding order, inclusive minimum
income, the file/outcome cycle, and aggregate apportionment bounds."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_fund, create_partner, create_tax_year,
    create_composite_filing_payload,
    setup_tax_year_with_locked_run,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]

TWO_HALF_PARTNERS = [
    {
        "key": "a", "legal_name": "A", "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED", "residency_state": "CA",
        "ownership_pct_bps": 5000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
    {
        "key": "b", "legal_name": "B", "partner_type": "US_ENTITY",
        "partner_class": "LIMITED", "residency_state": "DE",
        "ownership_pct_bps": 5000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
]


def _locked_two_partner_scenario(api):
    """Fee-free fund, partners A and B at 5000bps, 2025 net ordinary 1000000
    with a LOCKED FINAL run (500000 allocated to each)."""
    return setup_tax_year_with_locked_run(
        partner_specs=TWO_HALF_PARTNERS,
        tax_year_overrides={
            "gross_ordinary_income_cents": 1000000,
            "capital_gain_cents": 0,
            "interest_income_cents": 0,
        },
    )


def _create_ny_filing(api, ty_id, apportionment=3001, rate=700, min_income=1):
    resp = api.create_composite_filing(
        create_composite_filing_payload(
            ty_id, state_code="NY", apportionment_pct_bps=apportionment,
            composite_rate_bps=rate, min_income_cents=min_income,
        ),
        PREPARER,
    )
    return validate_success(resp, 201)


class TestPerPartnerRoundingOrder:
    def test_file_computes_included_partners_and_state_source_total(self, api):
        """PRD §3.6: "Each eligible partner’s state-source income is their
        allocated total multiplied by `apportionment_pct_bps` and divided by
        ten thousand, rounded half-up; each partner’s composite tax is their
        state-source income multiplied by `composite_rate_bps` and divided by
        ten thousand, again rounded half-up."
        PRD §3.6: "The filing’s `total_state_source_income_cents` and
        `total_composite_tax_cents` are the sums of those rounded per-partner
        values over the included partners, and `included_partner_ids` lists the
        included partners sorted by partner `created_at` ascending."
        PRD §3.6: "Filing, performed by a `TaxPreparer`, moves the filing from
        `DRAFT` to `FILED` and enforces three prerequisites: the tax year must
        be `ALLOCATED`, `UNDER_REVIEW`, `APPROVED`, or `COMPLETED`, else
        `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`; a `LOCKED` `FINAL` run must exist,
        else `ERR_ALLOCATION_NOT_LOCKED`, and must not be `STALE`, else
        `ERR_ALLOCATION_STALE`; and the recomputed `included_partner_ids` must
        be non-empty, else `ERR_COMPOSITE_PARTNER_INELIGIBLE`."

        Design: Difficulty/combinatorial_formula/composite_tax_per_partner_rounding_order
        """
        scenario = _locked_two_partner_scenario(api)
        filing = _create_ny_filing(api, scenario["tax_year"]["id"])
        resp = api.file_composite_filing(filing["id"], PREPARER)
        filed = validate_success(resp, 200)
        assert filed["status"] == "FILED"
        expected_order = [scenario["partners"]["a"]["id"], scenario["partners"]["b"]["id"]]
        assert filed["included_partner_ids"] == expected_order, (
            f"included partners sorted by created_at ASC: {filed['included_partner_ids']}"
        )
        # 2 x round_half_up(500000 x 3001/10000) = 2 x 150050
        assert filed["total_state_source_income_cents"] == 300100

    def test_composite_tax_is_rounded_per_partner_then_summed(self, api):
        """PRD §3.6: "The rounding order is pinned per-partner-then-sum, and
        the alternative of summing first and rounding once is forbidden because
        it yields different cents."
        PRD §3.6: "Each eligible partner’s state-source income is their
        allocated total multiplied by `apportionment_pct_bps` and divided by
        ten thousand, rounded half-up; each partner’s composite tax is their
        state-source income multiplied by `composite_rate_bps` and divided by
        ten thousand, again rounded half-up."

        Design: Difficulty/combinatorial_formula/composite_tax_per_partner_rounding_order
        """
        scenario = _locked_two_partner_scenario(api)
        filing = _create_ny_filing(api, scenario["tax_year"]["id"])
        filed = validate_success(api.file_composite_filing(filing["id"], PREPARER), 200)
        # pinned: 2 x round_half_up(150050 x 700/10000) = 2 x 10504 = 21008;
        # the forbidden sum-then-round order would yield 21007.
        assert filed["total_composite_tax_cents"] == 21008, (
            f"per-partner-then-sum must yield 21008: {filed['total_composite_tax_cents']}"
        )


class TestMinIncomeInclusiveBoundary:
    def test_income_exactly_at_minimum_is_included(self, api):
        """PRD §3.6: "Four conditions must all hold: the partner is not
        foreign, because foreign partners are withheld federally and never
        composited — they are silently excluded from eligibility, and an
        explicitly empty result errors only at filing time; the partner’s
        `residency_state` differs from the filing’s `state_code`, since
        residents file individually; the partner is `ACTIVE`; and the partner’s
        rounded state-source income is at least `min_income_cents`, with income
        exactly equal to the minimum included."

        Design: Difficulty/boundary_precision_check/composite_min_income_inclusive_boundary
        """
        scenario = _locked_two_partner_scenario(api)
        # state-source income is exactly 150050 for each partner
        filing = _create_ny_filing(api, scenario["tax_year"]["id"], min_income=150050)
        filed = validate_success(api.file_composite_filing(filing["id"], PREPARER), 200)
        assert filed["status"] == "FILED"
        assert filed["included_partner_ids"] == [
            scenario["partners"]["a"]["id"], scenario["partners"]["b"]["id"],
        ], "income exactly equal to the inclusive minimum must be included"

    def test_inclusive_minimum_yields_pinned_tax_total(self, api):
        """PRD §3.6: "The rounding order is pinned per-partner-then-sum, and
        the alternative of summing first and rounding once is forbidden because
        it yields different cents."
        PRD §3.6: "the partner’s rounded state-source income is at least
        `min_income_cents`, with income exactly equal to the minimum included."

        Design: Difficulty/boundary_precision_check/composite_min_income_inclusive_boundary
        """
        scenario = _locked_two_partner_scenario(api)
        filing = _create_ny_filing(api, scenario["tax_year"]["id"], min_income=150050)
        filed = validate_success(api.file_composite_filing(filing["id"], PREPARER), 200)
        assert filed["total_composite_tax_cents"] == 21008
        assert filed["total_state_source_income_cents"] == 300100

    def test_one_cent_above_minimum_excludes_everyone(self, api):
        """PRD §3.6: "the partner’s rounded state-source income is at least
        `min_income_cents`, with income exactly equal to the minimum included."
        PRD §3.6: "Filing, performed by a `TaxPreparer`, moves the filing from
        `DRAFT` to `FILED` and enforces three prerequisites: the tax year must
        be `ALLOCATED`, `UNDER_REVIEW`, `APPROVED`, or `COMPLETED`, else
        `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`; a `LOCKED` `FINAL` run must exist,
        else `ERR_ALLOCATION_NOT_LOCKED`, and must not be `STALE`, else
        `ERR_ALLOCATION_STALE`; and the recomputed `included_partner_ids` must
        be non-empty, else `ERR_COMPOSITE_PARTNER_INELIGIBLE`."

        Design: Corner/validations/composite_file_with_empty_included_set_rejected
        """
        scenario = _locked_two_partner_scenario(api)
        filing = _create_ny_filing(api, scenario["tax_year"]["id"], min_income=150051)
        resp = api.file_composite_filing(filing["id"], PREPARER)
        validate_error(resp, ApiErrorId.ERR_COMPOSITE_PARTNER_INELIGIBLE)
        after = validate_success(api.get_composite_filing(filing["id"], PREPARER), 200)
        assert after["status"] == "DRAFT"


class TestFilingLifecycle:
    def _draft_filing(self, api):
        fund = create_fund()
        partner = create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        from test_helpers import close_books, create_and_lock_final_run
        close_books(ty["id"])
        create_and_lock_final_run(ty["id"])
        filing = _create_ny_filing(api, ty["id"], apportionment=5000, rate=800)
        return filing

    def test_composite_rejected_returns_to_draft_and_refilable(self, api):
        """PRD §3.6: "An outcome of `ACCEPTED` moves the filing from `FILED` to
        `ACCEPTED`, its terminal state. An outcome of `REJECTED` returns the
        filing to `DRAFT`, resets `filed_at` to null, and leaves the filing
        free to be corrected and re-filed."

        Design: Corner/state_machines/composite_rejected_returns_to_draft_and_refilable
        """
        filing = self._draft_filing(api)
        filed = validate_success(api.file_composite_filing(filing["id"], PREPARER), 200)
        assert filed["status"] == "FILED"
        assert filed["filed_at"], "filed_at stamped from the logical clock at filing"
        rejected = validate_success(
            api.record_composite_outcome(filing["id"], {"outcome": "REJECTED"}, ADMIN), 200,
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["filed_at"] is None, "rejection resets filed_at to null"
        refiled = validate_success(api.file_composite_filing(filing["id"], PREPARER), 200)
        assert refiled["status"] == "FILED"
        assert refiled["filed_at"], "re-file stamps filed_at again"
        accepted = validate_success(
            api.record_composite_outcome(filing["id"], {"outcome": "ACCEPTED"}, ADMIN), 200,
        )
        assert accepted["status"] == "ACCEPTED"


class TestFilingUniquenessAndBounds:
    def test_duplicate_composite_filing_rejected(self, api):
        """PRD §3.6: "A second filing for the same state in the same tax year
        is rejected with `ERR_DUPLICATE_COMPOSITE_FILING`, and the sum of
        `apportionment_pct_bps` across all of a tax year’s filings must not
        exceed ten thousand — a sum of exactly ten thousand is allowed — else
        `ERR_APPORTIONMENT_OVERFLOW`."

        Design: Corner/validations/duplicate_composite_filing_rejected
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        _create_ny_filing(api, ty["id"], apportionment=5000, rate=800)
        resp = api.create_composite_filing(
            create_composite_filing_payload(
                ty["id"], state_code="NY", apportionment_pct_bps=1000,
                composite_rate_bps=500, min_income_cents=100,
            ),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPOSITE_FILING)

    def test_apportionment_overflow_at_capacity_edge(self, api):
        """PRD §3.6: "A second filing for the same state in the same tax year
        is rejected with `ERR_DUPLICATE_COMPOSITE_FILING`, and the sum of
        `apportionment_pct_bps` across all of a tax year’s filings must not
        exceed ten thousand — a sum of exactly ten thousand is allowed — else
        `ERR_APPORTIONMENT_OVERFLOW`."

        Design: Corner/validations/apportionment_overflow_at_capacity_edge
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        _create_ny_filing(api, ty["id"], apportionment=6000, rate=800)
        resp_nj = api.create_composite_filing(
            create_composite_filing_payload(
                ty["id"], state_code="NJ", apportionment_pct_bps=4000,
                composite_rate_bps=700, min_income_cents=1,
            ),
            PREPARER,
        )
        nj = validate_success(resp_nj, 201)
        assert nj["state_code"] == "NJ", "sum exactly 10000 must be allowed"
        resp_ct = api.create_composite_filing(
            create_composite_filing_payload(
                ty["id"], state_code="CT", apportionment_pct_bps=1,
                composite_rate_bps=500, min_income_cents=1,
            ),
            PREPARER,
        )
        validate_error(resp_ct, ApiErrorId.ERR_APPORTIONMENT_OVERFLOW)
