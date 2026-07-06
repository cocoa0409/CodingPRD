"""Transient-occupancy-tax (TOT) computation, penalty accrual, and filing lifecycle.

Covers difficulty queue A instances for tot_due/penalty calculations and the
tax-filing amend loop, plus corner queue B instances for the penalty interest
branch and partial remittance.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TaxFilingStatus,
    make_host_headers, TEST_USERS,
    setup_filed_filing, setup_delinquent_filing, setup_issued_permit,
    create_draft_filing,
)

TAX_OFFICER = TEST_USERS["tax_officer_headers"]


def test_tot_due_base_tier_ten_nights(api):
    """PRD §3.8: "If nights_booked is at most 14, the percentage component is
    the gross revenue multiplied by 8%, rounded half up to whole cents."
    PRD §3.8: "Then compute the flat component as the number of nights booked
    times 300 cents, which is exact. The tot_due_cents is the percentage
    component plus the flat component."

    10 nights / gross 500000 => pct = round(500000 * 0.08) = 40000;
    flat = 10 * 300 = 3000; tot_due = 43000.

    Design: Difficulty/dual_variant_calc/tot_due_cost_accounting_on_tax_filing
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], period_year=2026, period_month=3,
                                nights_booked=10, gross_revenue_cents=500000)
    data = validate_success(api.file_tax_filing(draft["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.FILED.value
    assert data["tot_due_cents"] == 43000, f"expected 43000, got {data['tot_due_cents']}"


def test_tot_due_straddle_tier_rounds_each_share(api):
    """PRD §3.8: "two shares are formed and each rounded half up to whole cents
    independently: a base share of the per-night revenue times 14 times 8%, and
    a surge share of the per-night revenue times the number of nights beyond 14
    times 12%; the percentage component is the sum of those two rounded shares."

    20 nights / gross 600000: per_night = 30000; base = round(30000*14*0.08)=33600;
    surge = round(30000*6*0.12)=21600; pct = 55200; flat = 20*300 = 6000;
    tot_due = 61200.

    Design: Difficulty/combinatorial_formula/tot_due_straddle_round_per_share_then_sum
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], period_year=2026, period_month=3,
                                nights_booked=20, gross_revenue_cents=600000)
    data = validate_success(api.file_tax_filing(draft["id"], TAX_OFFICER))
    assert data["tot_due_cents"] == 61200, f"expected 61200, got {data['tot_due_cents']}"


def test_penalty_cap_branch_when_interest_overflows(api):
    """PRD §3.8: "The raw penalty is a flat 2500 cents ($25) plus that interest.
    The cap is the unpaid balance times 25%, rounded half up to whole cents. The
    penalty_cents is the lesser of the raw penalty and the cap, with the
    lesser-of comparison applied only after both the raw penalty and the cap have
    each been fully computed."

    tot_due 43000, unpaid, 60 days late: interest=round(43000*0.005*60)=12900;
    raw=2500+12900=15400; cap=round(43000*0.25)=10750; penalty=min=10750.

    Design: Difficulty/combinatorial_formula/tax_penalty_min_of_interest_and_cap_branch
    """
    _, host, _, permit, filing = setup_delinquent_filing(
        "2026-06-29T00:00:00Z",
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000},
    )
    assert filing["status"] == TaxFilingStatus.DELINQUENT.value
    assert filing["penalty_cents"] == 10750, f"expected 10750, got {filing['penalty_cents']}"


def test_penalty_interest_branch_below_cap(api):
    """PRD §3.8: "The interest is the unpaid balance times a daily rate of 0.50%
    times the number of days late, rounded half up to whole cents. The raw
    penalty is a flat 2500 cents ($25) plus that interest."

    tot_due 43000, unpaid, 5 days late: interest=round(43000*0.005*5)=1075;
    raw=2500+1075=3575; cap=10750; penalty=min=3575 (interest branch).

    Design: Corner/calculations/tax_penalty_interest_branch_below_cap
    """
    _, host, _, permit, filing = setup_delinquent_filing(
        "2026-05-05T00:00:00Z",
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000},
    )
    assert filing["status"] == TaxFilingStatus.DELINQUENT.value
    assert filing["penalty_cents"] == 3575, f"expected 3575, got {filing['penalty_cents']}"


def test_amend_filed_filing_resets_to_draft(api):
    """PRD §3.8: "A successful amendment moves the filing from FILED back to
    DRAFT, resets both tot_due_cents and due_at to null, and increments the
    filing's version; the officer can then correct and re-file."

    Design: Difficulty/non_linear_state_machine/tax_filing_cyclic_amend_loop
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    assert filed["tot_due_cents"] == 43000
    data = validate_success(api.amend_tax_filing(filed["id"], TAX_OFFICER))
    assert data["status"] == TaxFilingStatus.DRAFT.value
    assert data["tot_due_cents"] is None, f"expected null tot_due, got {data['tot_due_cents']}"


def test_amend_loop_can_refile_and_recompute(api):
    """PRD §3.8: "A tax officer may re-open a FILED filing for correction ...
    the officer can then correct and re-file."
    PRD §3.8: "On a successful file, the system computes tot_due_cents (below),
    sets due_at to the last day of the reported period plus 30 days, moves the
    filing from DRAFT to FILED, and increments its version."

    After amend (FILED->DRAFT) the filing re-files and recomputes tot_due.

    Design: Difficulty/non_linear_state_machine/tax_filing_cyclic_amend_loop
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    validate_success(api.amend_tax_filing(filed["id"], TAX_OFFICER))
    refiled = validate_success(api.file_tax_filing(filed["id"], TAX_OFFICER))
    assert refiled["status"] == TaxFilingStatus.FILED.value
    assert refiled["tot_due_cents"] == 43000


def test_partial_remittance_keeps_filed_status(api):
    """PRD §3.8: "From FILED, if the current clock time is before due_at and the
    cumulative amount_remitted_cents after this payment reaches or exceeds
    tot_due_cents, the filing transitions to REMITTED; if the payment is only
    partial it is recorded and the filing remains FILED with no error raised."

    Design: Corner/endpoints/partial_remittance_keeps_filed_status
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    data = validate_success(
        api.remit_tax_filing(filed["id"], {"payment_cents": 20000}, make_host_headers(host["id"]))
    )
    assert data["status"] == TaxFilingStatus.FILED.value
    assert data["amount_remitted_cents"] == 20000


def test_delinquent_remit_covers_due_plus_penalty(api):
    """PRD §3.8: "From DELINQUENT, a remittance transitions the filing to
    REMITTED only once the cumulative amount_remitted_cents reaches or exceeds
    tot_due_cents plus penalty_cents; a partial payment is recorded and the
    filing stays DELINQUENT."

    tot_due 43000 + penalty 3575 (5 days late) = 46575; paying 46575 => REMITTED.

    Design: Difficulty/compensating_invariant/filing_money_conservation_remit_covers_due_plus_penalty
    """
    _, host, _, permit, filing = setup_delinquent_filing(
        "2026-05-05T00:00:00Z",
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000},
    )
    assert filing["penalty_cents"] == 3575
    data = validate_success(
        api.remit_tax_filing(filing["id"], {"payment_cents": 46575}, make_host_headers(host["id"]))
    )
    assert data["status"] == TaxFilingStatus.REMITTED.value
    assert data["amount_remitted_cents"] == 46575
