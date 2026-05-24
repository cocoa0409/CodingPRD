"""Repayment plan creation, IDR formulas, plan-type field shape rules, and
the OCC-guarded supersede semantics.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_repayment_plan,
    create_idr_plan_payload, create_standard_10yr_plan_payload,
    TEST_USERS,
    advance_clock, create_borrower, create_loan, fire_servicing_event,
    get_loan_version, get_loan,
    create_loan_in_repayment,
    setup_loan_in_repayment_with_standard_plan,
    attach_standard_10yr_plan, attach_idr_plan,
    make_borrower_headers,
)


# ─── STANDARD_10YR payment formula (corner) ─────────


def test_standard_10yr_payment_correct_known_inputs(api, servicer_headers):
    """PRD §3.3: "For a `STANDARD_10YR` plan, the monthly payment is the
    textbook fixed-payment amortization: when `r_monthly` is zero, the
    monthly payment is simply `P` divided by 120 (and then rounded). When
    `r_monthly` is positive, the monthly payment equals `P` multiplied by
    `r_monthly`, multiplied again by the quantity `(1 + r_monthly)` raised
    to the 120th power, divided by the quantity `(1 + r_monthly)` raised to
    the 120th power minus one. The result is rounded half-up to whole
    cents."

    P=$20,000, rate=5.33%, n=120 → monthly_payment_cents = 21537.

    Design: Corner/calculations/standard_10yr_payment_correct_known_inputs
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2026-06-01",
        grace_begin_on="2026-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000,
        interest_rate_bps=533,
    )
    v = get_loan_version(loan["id"])
    res = api.create_repayment_plan(
        create_standard_10yr_plan_payload(loan["id"], v),
        servicer_headers,
    )
    plan = validate_success(res, 201)
    assert_repayment_plan(plan)
    assert plan["monthly_payment_cents"] == 21_537


# ─── IDR field-shape constraint (corner) ────────────


def test_standard_plan_with_agi_cents_returns_invalid(api, servicer_headers):
    """PRD §3.3: "For a `STANDARD_10YR` plan, both `agi_cents` and
    `family_size` must be null; supplying either field is rejected with
    `ERR_PLAN_FIELDS_INVALID`."

    Design: Corner/calculations/standard_plan_fields_agi_set_returns_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment()
    v = get_loan_version(loan["id"])
    res = api.create_repayment_plan(
        {
            "loan_id": loan["id"],
            "plan_type": "STANDARD_10YR",
            "agi_cents": 5_000_000,
            "family_size": 2,
            "state_of_residence": "CONTIGUOUS",
            "expected_loan_version": v,
        },
        servicer_headers,
    )
    validate_error(res, "ERR_PLAN_FIELDS_INVALID", expected_status=422)


# ─── Difficulty Rule 1a: IDR divergence ─────────────


def test_ibr_paye_save_three_different_monthly_payments(api, servicer_headers):
    """PRD §3.3: "For an `IBR` plan, discretionary annual income is the
    borrower's `agi_cents` minus 150 percent of the looked-up annual poverty
    line (in cents), floored at zero (i.e., if `agi_cents` is less than 150
    percent of poverty, discretionary income is zero rather than negative).
    The IBR monthly payment is fifteen percent of discretionary annual
    income, divided by twelve, and rounded half-up to whole cents. IBR is
    then capped at the `STANDARD_10YR` reference payment computed above:
    the actual `monthly_payment_cents` is the smaller of the IBR figure and
    the standard reference."
    PRD §3.3: "For a `PAYE` plan, the structure is identical to `IBR` except
    the rate is ten percent rather than fifteen percent of discretionary
    income. The 150-percent poverty threshold and the standard reference
    cap both apply."
    PRD §3.3: "For a `SAVE` plan, discretionary annual income uses a more
    generous 225-percent poverty threshold instead of 150 percent (i.e.,
    the deduction is 225 percent of the poverty line, again floored at
    zero). The SAVE monthly payment is five percent of discretionary annual
    income, divided by twelve, and rounded half-up to whole cents. SAVE has
    no standard-payment cap..."

    On identical inputs (P=$30,000 @ 6.00%, AGI=$60,000, family_size=2,
    CONTIGUOUS) the three IDR variants diverge: IBR=33306 (cap-bound to
    standard), PAYE=24575 (uncapped, below standard), SAVE=5931 (225%
    threshold + 5%, no cap).

    Design: Difficulty/dual_variant_calc/plan_monthly_payment_idr_save_vs_ibr_divergence
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="three-plans@example.com")

    plans: dict[str, dict] = {}
    for plan_type in ("IBR", "PAYE", "SAVE"):
        loan = create_loan(
            borrower["id"],
            loan_type="DIRECT_UNSUBSIDIZED",
            original_principal_cents=3_000_000,
            interest_rate_bps=600,
            disbursement_date="2025-06-01",
        )
        fire_servicing_event(loan["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
        plan = attach_idr_plan(loan["id"], plan_type, 6_000_000, 2)
        plans[plan_type] = plan

    assert plans["IBR"]["monthly_payment_cents"] == 33_306
    assert plans["PAYE"]["monthly_payment_cents"] == 24_575
    assert plans["SAVE"]["monthly_payment_cents"] == 5_931
    # And no two are equal:
    assert plans["IBR"]["monthly_payment_cents"] != plans["PAYE"]["monthly_payment_cents"]
    assert plans["PAYE"]["monthly_payment_cents"] != plans["SAVE"]["monthly_payment_cents"]
    assert plans["IBR"]["monthly_payment_cents"] != plans["SAVE"]["monthly_payment_cents"]


def test_ibr_cap_binds_at_standard_10yr_when_idr_would_exceed_standard(
    api, servicer_headers,
):
    """PRD §3.3: "IBR is then capped at the `STANDARD_10YR` reference
    payment computed above: the actual `monthly_payment_cents` is the
    smaller of the IBR figure and the standard reference. (For borrowers
    with high principal and modest income, the IBR figure is lower than
    the standard and the cap is inactive; for borrowers with very small
    principal and modest income, the IBR figure may exceed the standard,
    in which case the cap binds and the borrower simply pays the
    standard.)"

    With AGI=$60,000, family_size=2, CONTIGUOUS and P=$30,000 @ 6.00%:
    the raw IBR figure (36863 cents) exceeds the standard reference
    (33306 cents), so the cap binds and the active monthly_payment_cents
    is the standard.

    Design: Difficulty/dual_variant_calc/plan_monthly_payment_idr_save_vs_ibr_divergence
    """
    advance_clock("2026-06-01T00:00:00Z")
    # IBR plan on the same loan parameters; verify the IBR figure
    # equals the standard reference (cap binds).
    _, loan_std = create_loan_in_repayment(
        original_principal_cents=3_000_000, interest_rate_bps=600,
    )
    v_std = get_loan_version(loan_std["id"])
    standard_plan = validate_success(api.create_repayment_plan(
        create_standard_10yr_plan_payload(loan_std["id"], v_std),
        servicer_headers,
    ), 201)
    standard_monthly = standard_plan["monthly_payment_cents"]
    assert standard_monthly == 33_306, (
        "Standard 10yr on $30k @ 6.00% must round to 33306 cents"
    )

    # Now an IBR plan on the same parameters.
    _, loan_ibr = create_loan_in_repayment(
        borrower_overrides={"email": "ibr-cap@example.com"},
        original_principal_cents=3_000_000, interest_rate_bps=600,
    )
    ibr_plan = attach_idr_plan(loan_ibr["id"], "IBR", 6_000_000, 2)
    assert ibr_plan["monthly_payment_cents"] == standard_monthly, (
        "IBR must be capped at the STANDARD_10YR reference when the raw "
        "IBR figure exceeds the standard."
    )


def test_save_floored_at_zero_when_agi_below_225_pct_poverty(api, servicer_headers):
    """PRD §3.3: "For a `SAVE` plan, discretionary annual income uses a more
    generous 225-percent poverty threshold instead of 150 percent (i.e.,
    the deduction is 225 percent of the poverty line, again floored at
    zero). The SAVE monthly payment is five percent of discretionary annual
    income, divided by twelve, and rounded half-up to whole cents. SAVE has
    no standard-payment cap..."

    SAVE plan with AGI=$30,000, family_size=2, CONTIGUOUS: 225% poverty =
    2.25 * $20,340 = $45,765 > $30,000, so discretionary annual is
    max(0, 30000 - 45765) cents = 0 → monthly_payment_cents = 0.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_idr_payment_save_zero_below_poverty
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    plan = attach_idr_plan(loan["id"], "SAVE", 3_000_000, 2)
    assert plan["monthly_payment_cents"] == 0


# ─── Difficulty Rule 2a: poverty table dependency ──


def test_idr_payment_three_input_nonlinear_tiered_pricing(api, servicer_headers):
    """PRD §3.3: "The three income-driven plans all share a common front end.
    Each consults the household poverty line for the borrower's
    `state_of_residence` and `family_size` — the `CONTIGUOUS` table is used
    for the forty-eight contiguous states, the `AK` table for Alaska, and
    the `HI` table for Hawaii."
    PRD §3.3: "For an `IBR` plan, discretionary annual income is the
    borrower's `agi_cents` minus 150 percent of the looked-up annual poverty
    line (in cents), floored at zero..."

    Same loan parameters (P=$30k @ 6.00%) and same household inputs (AGI
    $60k, family_size 2), only state_of_residence differs:
    CONTIGUOUS → 33306 (IBR cap-bound to standard).
    AK → 27338 (different poverty line; raw IBR figure remains under
    the standard cap).

    Design: Difficulty/combinatorial_formula/idr_payment_three_input_nonlinear_tiered_pricing
    """
    advance_clock("2026-06-01T00:00:00Z")

    brw1 = create_borrower(email="combo-contig@example.com")
    loan1 = create_loan(
        brw1["id"], loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=3_000_000, interest_rate_bps=600,
        disbursement_date="2025-06-01",
    )
    fire_servicing_event(loan1["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    plan_contig = attach_idr_plan(
        loan1["id"], "IBR", 6_000_000, 2, state_of_residence="CONTIGUOUS",
    )

    brw2 = create_borrower(email="combo-ak@example.com")
    loan2 = create_loan(
        brw2["id"], loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=3_000_000, interest_rate_bps=600,
        disbursement_date="2025-06-01",
    )
    fire_servicing_event(loan2["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    plan_ak = attach_idr_plan(
        loan2["id"], "IBR", 6_000_000, 2, state_of_residence="AK",
    )

    assert plan_contig["monthly_payment_cents"] == 33_306
    assert plan_ak["monthly_payment_cents"] == 27_338
    assert plan_contig["monthly_payment_cents"] != plan_ak["monthly_payment_cents"]


def test_idr_state_dependency_save_diverges_between_contiguous_and_hi(api, servicer_headers):
    """PRD §3.3: "The three income-driven plans all share a common front end.
    Each consults the household poverty line for the borrower's
    `state_of_residence` and `family_size` — the `CONTIGUOUS` table is used
    for the forty-eight contiguous states, the `AK` table for Alaska, and
    the `HI` table for Hawaii."
    PRD §3.3: "For a `SAVE` plan, discretionary annual income uses a more
    generous 225-percent poverty threshold instead of 150 percent (i.e.,
    the deduction is 225 percent of the poverty line, again floored at
    zero). The SAVE monthly payment is five percent of discretionary annual
    income, divided by twelve, and rounded half-up to whole cents. SAVE has
    no standard-payment cap..."

    Identical SAVE inputs (AGI=$60k, family_size=2, P=$30k @ 6.00%),
    different state: CONTIGUOUS poverty[2]=$20,340 → 225%=$45,765 →
    discretionary $14,235 → 5%/12 = $59.3125 → 5931 cents. HI
    poverty[2]=$23,390 → 225%=$52,627.50 → discretionary $7,372.50 →
    5%/12 ≈ $30.72 → 3072 cents. Two states yield different SAVE payments
    on otherwise-identical inputs, demonstrating the tiered table lookup.

    Design: Difficulty/combinatorial_formula/idr_payment_three_input_nonlinear_tiered_pricing
    """
    advance_clock("2026-06-01T00:00:00Z")

    brw1 = create_borrower(email="save-contig@example.com")
    loan1 = create_loan(
        brw1["id"], loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=3_000_000, interest_rate_bps=600,
        disbursement_date="2025-06-01",
    )
    fire_servicing_event(loan1["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    plan_contig = attach_idr_plan(
        loan1["id"], "SAVE", 6_000_000, 2, state_of_residence="CONTIGUOUS",
    )

    brw2 = create_borrower(email="save-hi@example.com")
    loan2 = create_loan(
        brw2["id"], loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=3_000_000, interest_rate_bps=600,
        disbursement_date="2025-06-01",
    )
    fire_servicing_event(loan2["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    plan_hi = attach_idr_plan(
        loan2["id"], "SAVE", 6_000_000, 2, state_of_residence="HI",
    )

    assert plan_contig["monthly_payment_cents"] == 5_931
    # HI: 225% * 23390 = 52627.5; discretionary = 60000 - 52627.5 = 7372.5
    # ($cents: 6000000 - 5262750 = 737250); monthly = 737250 * 0.05 / 12
    # = 3071.875 → round half up = 3072.
    assert plan_hi["monthly_payment_cents"] == 3_072
    assert plan_contig["monthly_payment_cents"] != plan_hi["monthly_payment_cents"]


# ─── Difficulty Rule 8a: supersede + OCC ────────────


def test_supersede_legitimate_then_stale_create_rejected_with_stale_version(
    api, servicer_headers,
):
    """PRD §3.3: "If a different plan with `status` of `ACTIVE` already exists
    for the same `loan_id`, the new plan still proceeds: on successful
    activation, the prior plan transitions from `ACTIVE` to `SUPERSEDED`
    and the new plan takes its place as the single `ACTIVE` row."
    PRD §2.5: "If the values do not match — because another writer has, for
    instance, posted a `Payment` or logged a `ServicingEvent` that bumped
    the loan's `version` since the client's last read — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    The two legitimate creates each observe a fresh loan.version. A third
    create that reuses the version observed BEFORE the second create's
    commit is stale and must be rejected with ERR_STALE_VERSION.

    Design: Difficulty/resource_temporal_overlap/active_repayment_plan_supersede_semantics
    """
    _, loan, plan1 = setup_loan_in_repayment_with_standard_plan()
    # plan2 observes the loan version after plan1 created/bumped
    v_after_plan1 = get_loan_version(loan["id"])
    plan2 = api.create_repayment_plan(
        create_idr_plan_payload(loan["id"], "IBR", 4_000_000, 2, v_after_plan1),
        servicer_headers,
    )
    plan2_data = validate_success(plan2, 201)

    # plan3 attempts with the same expected_loan_version that plan2 used,
    # but plan2 has since advanced the loan version → stale → 412.
    plan3 = api.create_repayment_plan(
        create_idr_plan_payload(loan["id"], "PAYE", 4_000_000, 2, v_after_plan1),
        servicer_headers,
    )
    validate_error(plan3, "ERR_STALE_VERSION", expected_status=412)

    # plan1 should have been superseded by plan2.
    plan1_now = validate_success(api.get_repayment_plan(plan1["id"], servicer_headers), 200)
    assert plan1_now["status"] == "SUPERSEDED"
    assert plan2_data["status"] == "ACTIVE"


def test_supersede_second_plan_becomes_active_first_becomes_superseded(
    api, servicer_headers,
):
    """PRD §3.3: "If a different plan with `status` of `ACTIVE` already exists
    for the same `loan_id`, the new plan still proceeds: on successful
    activation, the prior plan transitions from `ACTIVE` to `SUPERSEDED`
    and the new plan takes its place as the single `ACTIVE` row."

    With matching expected_loan_version, the legitimate supersede succeeds:
    the prior plan moves to SUPERSEDED, the new plan is the single ACTIVE
    row on the loan.

    Design: Difficulty/resource_temporal_overlap/active_repayment_plan_supersede_semantics
    """
    _, loan, plan1 = setup_loan_in_repayment_with_standard_plan()
    v_after_plan1 = get_loan_version(loan["id"])
    res = api.create_repayment_plan(
        create_idr_plan_payload(loan["id"], "IBR", 4_000_000, 2, v_after_plan1),
        servicer_headers,
    )
    plan2 = validate_success(res, 201)
    assert plan2["status"] == "ACTIVE"
    assert plan2["loan_id"] == loan["id"]

    plan1_now = validate_success(api.get_repayment_plan(plan1["id"], servicer_headers), 200)
    assert plan1_now["status"] == "SUPERSEDED"


# ─── OCC correct version succeeds (corner) ──────────


def test_occ_create_plan_with_matching_version_succeeds(api, servicer_headers):
    """PRD §2.5: "Creating a `RepaymentPlan` via a post to the
    repayment-plans collection requires `expected_loan_version` in the
    request body as a non-optional integer. The server compares this value
    to the target loan's current `version`."
    PRD §3.3: "A plan row is conceptually born with `status` of `PENDING` and
    is moved to `ACTIVE` synchronously by the same create request once all
    preconditions clear; clients never observe a persisted `PENDING` plan
    after a successful create."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=100_000, interest_rate_bps=0,
    )
    v = get_loan_version(loan["id"])
    res = api.create_repayment_plan(
        create_standard_10yr_plan_payload(loan["id"], v),
        servicer_headers,
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert plan["loan_id"] == loan["id"]


# ─── Borrower-role can create own RepaymentPlan ─────


def test_borrower_can_create_own_repayment_plan(api, servicer_headers):
    """PRD §4 (RBAC table for POST /v1/repayment-plans): "LoanServicer,
    Borrower" are the authorized roles.
    PRD §2.1: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of
    the acting `Borrower` entity. Ownership checks compare `X-User-ID` to
    the `borrower_id` carried (directly or transitively through a `Loan`)
    by any resource the Borrower attempts to read or write."

    Design: Corner/roles/borrower_can_create_own_repayment_plan
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower, loan = create_loan_in_repayment(
        borrower_overrides={"email": "self-plan@example.com"},
    )
    v = get_loan_version(loan["id"])
    own_headers = make_borrower_headers(borrower["id"])
    res = api.create_repayment_plan(
        create_standard_10yr_plan_payload(loan["id"], v),
        own_headers,
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert plan["loan_id"] == loan["id"]
