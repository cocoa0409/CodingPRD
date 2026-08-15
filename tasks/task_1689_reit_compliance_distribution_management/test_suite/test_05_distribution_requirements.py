"""Annual distribution requirement: 90% computation, zero floor, year-end
close preconditions, and the declare-side POSTED gate (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_distribution_requirement,
    create_approved_dividend,
    create_declared_dividend,
    create_posted_ep_adjustment,
    create_posted_requirement,
    create_quarter,
    create_reit,
    get_reit,
    setup_reit_with_open_quarter,
    validate_error,
    validate_success,
)


def test_distribution_requirement_90_percent_and_floor(
        api, compliance_officer_headers):
    """PRD §3.5: "When the officer posts a `DRAFT` requirement, the system
    computes `required_amount_cents` as 90% of the excess of
    `taxable_income_cents` over `net_capital_gain_cents`. If that excess is
    zero or negative, the requirement floors at 0 — there is no negative
    requirement."

    Design: Corner/calculations/distribution_requirement_90_percent_and_floor
    """
    reit = create_reit(legal_name="C3 REIT")
    req26 = create_posted_requirement(reit["id"], taxable_year=2026,
                                      taxable_income_cents=900_000,
                                      net_capital_gain_cents=100_000)
    assert_distribution_requirement(req26)
    assert req26["required_amount_cents"] == 720_000

    req27 = create_posted_requirement(reit["id"], taxable_year=2027,
                                      taxable_income_cents=100_000,
                                      net_capital_gain_cents=200_000)
    assert req27["required_amount_cents"] == 0


def test_distribution_requirement_half_cent_rounding(
        api, compliance_officer_headers):
    """PRD §3.5: "Otherwise the 90% figure is rounded half-up to whole cents."

    Design: Corner/calculations/distribution_requirement_half_cent_rounding
    """
    reit = create_reit(legal_name="C4 REIT")
    req = create_posted_requirement(reit["id"], taxable_year=2026,
                                    taxable_income_cents=1_000_001,
                                    net_capital_gain_cents=0)
    assert req["required_amount_cents"] == 900_001


def test_close_with_open_dividends_rejected_then_succeeds(
        api, tax_director_headers, compliance_officer_headers):
    """PRD §3.5: "At year-end a `TaxDirector` closes it, but only when every
    sibling dividend for the same `(reit_id, taxable_year)` has reached a
    terminal state of `PAID` or `VOID`; a close request with any declaration
    still in `PENDING_APPROVAL`, `APPROVED`, or `DECLARED` is rejected with
    `ERR_DECLARATIONS_OPEN`".
    PRD §3.5: "On close, the `deficiency_cents` is frozen as the greater of
    zero or the excess of `required_amount_cents` over
    `distributed_amount_cents`."

    Design: Corner/validations/requirement_close_with_open_dividends_rejected
    """
    reit, quarter = setup_reit_with_open_quarter()
    create_posted_ep_adjustment(reit["id"], quarter["id"],
                                kind="TAXABLE_INCOME", amount_cents=600_000,
                                effective_date="2026-01-15")
    req = create_posted_requirement(reit["id"], taxable_year=2026,
                                    taxable_income_cents=500_000,
                                    net_capital_gain_cents=0)
    assert req["required_amount_cents"] == 450_000
    dividend = create_declared_dividend(reit["id"], taxable_year=2026,
                                        amount_cents=450_000)

    blocked = api.close_distribution_requirement(req["id"],
                                                 tax_director_headers)
    validate_error(blocked, ApiErrorId.ERR_DECLARATIONS_OPEN)

    validate_success(
        api.pay_dividend_declaration(dividend["id"],
                                     compliance_officer_headers),
        200,
    )
    closed = validate_success(
        api.close_distribution_requirement(req["id"], tax_director_headers),
        200,
    )
    assert_distribution_requirement(closed)
    assert closed["status"] == "CLOSED"
    assert closed["deficiency_cents"] == 0
    assert closed["distributed_amount_cents"] == 450_000
    assert get_reit(reit["id"])["dividend_distribution_deficit_cents"] == 0


class TestDeclareRequiresPostedRequirement:
    def test_declare_while_requirement_draft_then_posted(
            self, api, compliance_officer_headers):
        """PRD §3.6: "A `ComplianceOfficer` declares a dividend that is in
        `APPROVED`, against a REIT that is `ACTIVE`, with `five_fifty_blocked`
        false, with their own `X-User-ID` different from the declaration's
        `approved_by_director_id` — a same-identifier attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — and with a `POSTED`
        `DistributionRequirement` existing for the same `(reit_id,
        taxable_year)`. A missing or unposted requirement yields
        `ERR_REQUIREMENT_NOT_POSTED`."

        Design: Difficulty/cross_entity_state_dependency/dividend_declare_requires_posted_requirement
        """
        reit = create_reit(legal_name="X2 REIT")
        req = validate_success(
            api.create_distribution_requirement(
                {
                    "reit_id": reit["id"],
                    "taxable_year": 2026,
                    "taxable_income_cents": 500_000,
                    "net_capital_gain_cents": 0,
                },
                compliance_officer_headers,
            ),
            201,
        )
        dividend = create_approved_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=40_000)

        blocked = api.declare_dividend_declaration(
            dividend["id"], compliance_officer_headers
        )
        validate_error(blocked, ApiErrorId.ERR_REQUIREMENT_NOT_POSTED)

        validate_success(
            api.post_distribution_requirement(req["id"],
                                              compliance_officer_headers),
            200,
        )
        declared = validate_success(
            api.declare_dividend_declaration(dividend["id"],
                                             compliance_officer_headers),
            200,
        )
        assert declared["status"] == "DECLARED"

    def test_declare_with_no_requirement_rejected(
            self, api, compliance_officer_headers):
        """PRD §3.6: "A missing or unposted requirement yields
        `ERR_REQUIREMENT_NOT_POSTED`."

        Design: Difficulty/cross_entity_state_dependency/dividend_declare_requires_posted_requirement
        """
        reit = create_reit(legal_name="X2 REIT 2")
        dividend = create_approved_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=40_000)
        resp = api.declare_dividend_declaration(dividend["id"],
                                                compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_POSTED)
