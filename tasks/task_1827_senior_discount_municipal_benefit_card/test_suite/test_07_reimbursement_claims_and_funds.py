"""Monthly reimbursement claims and the program fund: the provisional/final
bases, per-line rounding, the merchant monthly cap, the fiscal gates, and the
fund ledger invariant (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_fund_invariant,
    assert_program_fund,
    create_merchant,
    create_program_fund,
    create_program_fund_payload,
    file_claim,
    make_merchant_operator_headers,
    onboard_cardholder,
    post_transactions,
    set_clock,
    setup_merchant_with_offer,
    setup_submitted_claim,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["program_administrator_headers"]  # X-User-ID: admin-1


def _setup_five_transaction_divergence():
    """Cardholder + merchant (rate 50, cap 100000, GROCERY offer 10% max 1000)
    + fund FY2026 (allocated 1000000) + five August purchases of 10000 (each
    discounting 1000; the fifth is auto-flagged by the calendar-day velocity
    rule) + clock advanced to 2026-09-01 so period 2026-08 is closed."""
    onboard = onboard_cardholder(full_name="Ada Lovelace",
                                 date_of_birth="1961-08-01",
                                 annual_income_cents=1000000,
                                 residency_address="1 Main St")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Corner Grocery",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 100000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    fund = create_program_fund(fiscal_year=2026, allocated_cents=1000000)
    set_clock("2026-08-10T12:00:00Z")
    txns = post_transactions(onboard["card"]["id"], merchant["id"], 5, 10000)
    assert txns[4]["status"] == "FLAGGED", (
        "the fifth same-day transaction is auto-flagged by the velocity rule")
    set_clock("2026-09-01T00:00:00Z")
    return onboard, merchant, fund


def test_provisional_includes_flagged_final_excludes(api):
    """PRD §3.8: "The two bases differ only in which transactions are
    eligible: the provisional basis, used at submission, includes transactions
    standing in `POSTED` or `FLAGGED` as they stand at the submission clock,
    while the final basis, used at approval, includes only transactions
    standing in `POSTED` at the approval clock — transactions still `FLAGGED`
    and unresolved are excluded, as are `VOIDED` ones."
    PRD §3.8: "Each eligible transaction contributes a line amount: the
    transaction's `discount_cents` multiplied by the merchant's
    `reimbursement_rate_pct` and divided by one hundred, rounded half-up to a
    whole cent."
    The identical five-transaction set yields 2500 provisionally (five lines
    of round_half_up(1000 * 50 / 100) = 500) but only 2000 finally (the
    FLAGGED fifth transaction is excluded).

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_basis_divergence
    """
    _, merchant, _ = _setup_five_transaction_divergence()
    claim = file_claim(merchant["id"], "2026-08")
    assert claim["provisional_amount_cents"] == 2500, (
        "POSTED+FLAGGED basis: five lines of 500")

    approved = validate_success(api.approve_claim(claim["id"], ADMIN_HEADERS), 200)
    assert approved["status"] == "APPROVED"
    assert approved["final_amount_cents"] == 2000, (
        "POSTED-only basis: the unresolved FLAGGED fifth transaction is excluded")
    assert approved["provisional_amount_cents"] == 2500, (
        "the provisional figure stays frozen at submission")
    assert approved["final_amount_cents"] != approved["provisional_amount_cents"], (
        "two valid bases over one transaction set produce different cents")


def test_approval_debits_fund_by_final_amount(api, program_administrator_headers):
    """PRD §3.8: "On approval the claim stores `final_amount_cents` and binds
    `program_fund_id` to the resolved fund, the fund's `paid_cents` increases
    by the final amount — a fund mutation that increments the fund's `version`
    — and the merchant's `current_month_reimbursed_cents` is recomputed as the
    sum of `final_amount_cents` over the merchant's `APPROVED` claims whose
    approval timestamp falls inside the clock's current calendar month."
    The fund is debited by the 2000-cent final amount, not the 2500-cent
    provisional figure.

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_basis_divergence
    """
    _, merchant, fund = _setup_five_transaction_divergence()
    claim = file_claim(merchant["id"], "2026-08")
    approved = validate_success(api.approve_claim(claim["id"], ADMIN_HEADERS), 200)
    assert approved["program_fund_id"] == fund["id"]

    fund_after = validate_success(
        api.get_program_fund(fund["id"], program_administrator_headers), 200)
    assert fund_after["paid_cents"] == 2000
    assert fund_after["available_cents"] == 998000
    assert_fund_invariant(fund_after)


def _setup_three_101_discount_transactions(with_fund=False):
    """Cardholder + merchant (rate 50, cap 100000, GROCERY offer 10% max 1000)
    + three August purchases of 1010 (each discounting 101) + clock advanced
    to 2026-09-01."""
    onboard = onboard_cardholder(full_name="Rhea Rounding",
                                 date_of_birth="1958-07-07",
                                 annual_income_cents=700000,
                                 residency_address="5 Birch St")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Round Drugs",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 100000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    fund = create_program_fund(fiscal_year=2026, allocated_cents=100000) if with_fund else None
    set_clock("2026-08-05T10:00:00Z")
    txns = post_transactions(onboard["card"]["id"], merchant["id"], 3, 1010)
    set_clock("2026-09-01T00:00:00Z")
    return merchant, txns, fund


def test_claim_rounds_per_line_then_sums(api):
    """PRD §3.8: "Each eligible transaction contributes a line amount: the
    transaction's `discount_cents` multiplied by the merchant's
    `reimbursement_rate_pct` and divided by one hundred, rounded half-up to a
    whole cent. The claim amount is the sum of those per-line rounded amounts
    — rounding strictly precedes summation, each line being rounded first and
    only the rounded line amounts added; summing unrounded contributions and
    rounding once at the end is a different rule and is not how the program
    computes claims."
    Three lines of 101 at 50% round to 51 each and sum to 153; the
    sum-then-round alternative would give round_half_up(303 * 0.5) = 152.

    Design: Difficulty/combinatorial_formula/claim_rounding_per_line_then_sum
    """
    merchant, txns, _ = _setup_three_101_discount_transactions()
    for txn in txns:
        assert txn["discount_cents"] == 101, "round_half_up(1010 * 10 / 100) = 101"

    claim = file_claim(merchant["id"], "2026-08")
    assert claim["provisional_amount_cents"] == 153, (
        "3 x round_half_up(101 * 50 / 100) = 3 x 51 = 153, not the "
        "sum-then-round 152 — the rounding order is pinned per line first")


def test_final_amount_recomputes_under_posted_only_basis(api,
                                                         program_administrator_headers):
    """PRD §3.8: "The two bases differ only in which transactions are
    eligible: the provisional basis, used at submission, includes transactions
    standing in `POSTED` or `FLAGGED` as they stand at the submission clock,
    while the final basis, used at approval, includes only transactions
    standing in `POSTED` at the approval clock — transactions still `FLAGGED`
    and unresolved are excluded, as are `VOIDED` ones."
    PRD §3.8: "On approval the claim stores `final_amount_cents` and binds
    `program_fund_id` to the resolved fund, the fund's `paid_cents` increases
    by the final amount — a fund mutation that increments the fund's `version`
    — and the merchant's `current_month_reimbursed_cents` is recomputed as the
    sum of `final_amount_cents` over the merchant's `APPROVED` claims whose
    approval timestamp falls inside the clock's current calendar month."
    With no flags outstanding, the final basis matches the provisional: 153.

    Design: Difficulty/combinatorial_formula/claim_rounding_per_line_then_sum
    """
    merchant, _, fund = _setup_three_101_discount_transactions(with_fund=True)
    claim = file_claim(merchant["id"], "2026-08")

    approved = validate_success(api.approve_claim(claim["id"], ADMIN_HEADERS), 200)
    assert approved["status"] == "APPROVED"
    assert approved["final_amount_cents"] == 153, (
        "all three lines stand POSTED, so the final basis includes them all")
    assert approved["program_fund_id"] == fund["id"]

    fund_after = validate_success(
        api.get_program_fund(fund["id"], program_administrator_headers), 200)
    assert fund_after["paid_cents"] == 153
    assert_fund_invariant(fund_after)


def _setup_monthly_cap_boundary():
    """Merchant with monthly cap 1000 and rate 50; an August pair of 1000-cent
    discounts (claim final exactly 1000) and a September trio discounting
    1000, 1000, and 2 (claim final 1001). Claims are filed, not yet decided."""
    onboard = onboard_cardholder(full_name="Cap Boundary",
                                 residency_address="13 Limit Rd")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Cap Corner",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 1000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    fund = create_program_fund(fiscal_year=2026, allocated_cents=100000)
    set_clock("2026-08-05T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 2, 10000)
    set_clock("2026-09-01T00:00:00Z")
    claim1 = file_claim(merchant["id"], "2026-08")
    set_clock("2026-09-10T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 2, 10000)
    post_transactions(onboard["card"]["id"], merchant["id"], 1, 20)
    set_clock("2026-10-01T00:00:00Z")
    claim2 = file_claim(merchant["id"], "2026-09")
    return merchant, fund, claim1, claim2


def test_claim_at_exact_monthly_cap_approved(api):
    """PRD §3.8: "And the merchant's monthly cap must hold: the sum of
    `final_amount_cents` over the merchant's other `APPROVED` claims for the
    same `period_month`, plus this claim's final amount, must not exceed the
    merchant's `monthly_reimbursement_cap_cents`, else
    `ERR_MERCHANT_MONTHLY_CAP_EXCEEDED` (HTTP 422)."
    The August claim's final amount is exactly the 1000-cent cap — "must not
    exceed" is inclusive, so the claim is approved.

    Design: Difficulty/boundary_precision_check/merchant_monthly_cap_exact_boundary
    """
    _, _, claim1, _ = _setup_monthly_cap_boundary()
    approved = validate_success(api.approve_claim(claim1["id"], ADMIN_HEADERS), 200)
    assert approved["final_amount_cents"] == 1000, (
        "2 x round_half_up(1000 * 50 / 100) = 1000")
    assert approved["status"] == "APPROVED", (
        "a period total exactly equal to the cap passes (<= inclusive)")


def test_claim_one_cent_over_monthly_cap_rejected(api):
    """PRD §3.8: "And the merchant's monthly cap must hold: the sum of
    `final_amount_cents` over the merchant's other `APPROVED` claims for the
    same `period_month`, plus this claim's final amount, must not exceed the
    merchant's `monthly_reimbursement_cap_cents`, else
    `ERR_MERCHANT_MONTHLY_CAP_EXCEEDED` (HTTP 422)."
    The September claim's final amount is 1001 — one cent over the 1000-cent
    cap (500 + 500 + round_half_up(2 * 50 / 100)).

    Design: Difficulty/boundary_precision_check/merchant_monthly_cap_exact_boundary
    """
    _, _, claim1, claim2 = _setup_monthly_cap_boundary()
    validate_success(api.approve_claim(claim1["id"], ADMIN_HEADERS), 200)
    res = api.approve_claim(claim2["id"], ADMIN_HEADERS)
    validate_error(res, ApiErrorId.ERR_MERCHANT_MONTHLY_CAP_EXCEEDED)


def _setup_denied_claim_with_insufficient_fund():
    """A claim whose recomputed final amount (150) exceeds the fund's
    available balance (100), and which has already been DENIED."""
    scenario = setup_submitted_claim(
        purchase_amount_cents=1000, transaction_count=3,
        fund_allocated_cents=100,
        merchant_overrides={"name": "Prio Pharmacy",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 100000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    claim = scenario["claim"]
    assert claim["provisional_amount_cents"] == 150, (
        "3 x round_half_up(100 * 50 / 100) = 150 — the fiscal conflict is real")
    denied = validate_success(
        api_client.deny_claim(claim["id"], "documentation incomplete",
                              ADMIN_HEADERS), 200)
    assert denied["status"] == "DENIED"
    return scenario


def test_approve_denied_claim_reports_state_error(api):
    """PRD §3.8: "Approval is the administrator's settlement act, guarded in
    the order of §2.10. The claim must stand in `SUBMITTED`, else
    `ERR_CLAIM_NOT_SUBMITTED` (HTTP 409)."
    PRD §2.10: "The server evaluates guards in a pinned order and reports the
    earliest failing tier, so the error a client observes is deterministic"
    PRD §2.10: "**Resource state** — whether the target resource is in the
    state the operation requires (an application that can be reviewed, a
    document not yet reviewed, a card that is `ACTIVE`, a claim still
    `SUBMITTED`, a merchant still `ACTIVE`); failures surface as the 409 state
    family."
    The claim is DENIED (state tier) and the recomputed final would also
    exceed the fund's available balance (fiscal tier): the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/claim_approve_state_vs_fiscal_priority
    """
    scenario = _setup_denied_claim_with_insufficient_fund()
    res = api.approve_claim(scenario["claim"]["id"], ADMIN_HEADERS)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)


def test_failed_priority_probe_changes_nothing(api, program_administrator_headers):
    """PRD §3.8: "The claim must stand in `SUBMITTED`, else
    `ERR_CLAIM_NOT_SUBMITTED` (HTTP 409)."
    PRD §3.8: "The fund's `paid_cents` is the sum of `final_amount_cents` over
    approved claims bound to it, and its `available_cents` is the
    appropriation minus what has been paid; the invariant that
    `allocated_cents` always equals `available_cents` plus `paid_cents` holds
    at all times."
    After the rejected approval the claim stays DENIED and the fund is
    untouched — the fiscal conflict (final 150 > available 100) was never
    allowed to debit anything.

    Design: Difficulty/priority_pair_validation_conflict/claim_approve_state_vs_fiscal_priority
    """
    scenario = _setup_denied_claim_with_insufficient_fund()
    validate_error(
        api.approve_claim(scenario["claim"]["id"], ADMIN_HEADERS),
        ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)

    claims = validate_success(
        api.list_reimbursement_claims(scenario["merchant"]["id"],
                                      program_administrator_headers), 200)
    claim_after = [c for c in claims if c["id"] == scenario["claim"]["id"]][0]
    assert claim_after["status"] == "DENIED"

    fund_after = validate_success(
        api.get_program_fund(scenario["fund"]["id"], program_administrator_headers),
        200)
    assert fund_after["paid_cents"] == 0
    assert fund_after["available_cents"] == 100
    assert_fund_invariant(fund_after)


def test_fund_ledger_reconciles_across_approvals(api, program_administrator_headers):
    """PRD §3.8: "The fund's `paid_cents` is the sum of `final_amount_cents`
    over approved claims bound to it, and its `available_cents` is the
    appropriation minus what has been paid; the invariant that
    `allocated_cents` always equals `available_cents` plus `paid_cents` holds
    at all times."
    Two approved claims in two periods (150 for August, 50 for September)
    reconcile the fund to paid 200 / available 9800 on a 10000 appropriation.

    Design: Corner/calculations/fund_ledger_reconciles_across_approvals
    """
    onboard = onboard_cardholder(full_name="Fund Fred", residency_address="40 Ledger Ln")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Fund Foods",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 100000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    fund = create_program_fund(fiscal_year=2026, allocated_cents=10000)

    set_clock("2026-08-05T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 3, 1000)
    set_clock("2026-09-01T00:00:00Z")
    claim1 = file_claim(merchant["id"], "2026-08")
    approved1 = validate_success(api.approve_claim(claim1["id"], ADMIN_HEADERS), 200)
    assert approved1["final_amount_cents"] == 150

    set_clock("2026-09-10T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 1, 1000)
    set_clock("2026-10-01T00:00:00Z")
    claim2 = file_claim(merchant["id"], "2026-09")
    approved2 = validate_success(api.approve_claim(claim2["id"], ADMIN_HEADERS), 200)
    assert approved2["final_amount_cents"] == 50

    fund_after = validate_success(
        api.get_program_fund(fund["id"], program_administrator_headers), 200)
    assert_program_fund(fund_after)
    assert fund_after["paid_cents"] == 200, "150 + 50 across the two periods"
    assert fund_after["available_cents"] == 9800
    assert_fund_invariant(fund_after)


def test_current_month_reimbursed_reconciles_with_clock(api,
                                                        program_administrator_headers):
    """PRD §3.8: "On approval the claim stores `final_amount_cents` and binds
    `program_fund_id` to the resolved fund, the fund's `paid_cents` increases
    by the final amount — a fund mutation that increments the fund's `version`
    — and the merchant's `current_month_reimbursed_cents` is recomputed as the
    sum of `final_amount_cents` over the merchant's `APPROVED` claims whose
    approval timestamp falls inside the clock's current calendar month."
    The approval lands in the clock's September window; once the clock moves
    to October the same approval no longer counts.

    Design: Corner/cross_cutting_complexity_layers/merchant_month_reimbursed_reconciles_with_clock_month
    """
    scenario = setup_submitted_claim(
        purchase_amount_cents=1000, transaction_count=3,
        fund_allocated_cents=10000,
        merchant_overrides={"name": "Month Mart",
                            "reimbursement_rate_pct": 50,
                            "monthly_reimbursement_cap_cents": 100000},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    merchant_id = scenario["merchant"]["id"]

    validate_success(
        api.approve_claim(scenario["claim"]["id"], ADMIN_HEADERS), 200)
    at_approval = validate_success(
        api.get_merchant(merchant_id, program_administrator_headers), 200)
    assert at_approval["current_month_reimbursed_cents"] == 150, (
        "approved at clock 2026-09-01, inside the September window")

    set_clock("2026-10-01T00:00:00Z")
    next_month = validate_success(
        api.get_merchant(merchant_id, program_administrator_headers), 200)
    assert next_month["current_month_reimbursed_cents"] == 0, (
        "the September approval is outside the clock's current (October) month")


def test_claim_for_current_period_rejected(api):
    """PRD §3.8: "The period must be strictly earlier than the clock's current
    calendar month — a claim for the current or a future month is rejected
    with `ERR_CLAIM_PERIOD_NOT_CLOSED` (HTTP 422) — and the merchant may hold
    at most one non-denied claim per period: if a claim for the same merchant
    and `period_month` stands in `SUBMITTED` or `APPROVED`, refiling is
    rejected with `ERR_DUPLICATE_PENDING_CLAIM` (HTTP 409), so refiling
    becomes possible only after every prior claim for that period has been
    denied."
    At clock 2026-09-15 the period 2026-09 is the current month.

    Design: Corner/validations/claim_for_current_period_rejected
    """
    merchant = create_merchant(name="Period Pantry", reimbursement_rate_pct=50,
                               monthly_reimbursement_cap_cents=100000)
    set_clock("2026-09-15T10:00:00Z")
    res = api.create_reimbursement_claim(
        merchant["id"], "2026-09", make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_PERIOD_NOT_CLOSED)


def test_duplicate_fiscal_year_fund_rejected(api, program_administrator_headers):
    """PRD §3.8: "A `ProgramAdministrator` creates a program fund for a
    `fiscal_year` with its `allocated_cents` appropriation, which must be
    positive; one fund exists per fiscal year, and a duplicate is rejected
    with `ERR_DUPLICATE_FISCAL_YEAR` (HTTP 409)."

    Design: Corner/validations/duplicate_fiscal_year_fund_rejected
    """
    validate_success(api.create_program_fund(
        create_program_fund_payload(2026, 10000), program_administrator_headers), 201)
    res = api.create_program_fund(
        create_program_fund_payload(2026, 20000), program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR)


def test_duplicate_pending_claim_rejected(api):
    """PRD §3.8: "The period must be strictly earlier than the clock's current
    calendar month — a claim for the current or a future month is rejected
    with `ERR_CLAIM_PERIOD_NOT_CLOSED` (HTTP 422) — and the merchant may hold
    at most one non-denied claim per period: if a claim for the same merchant
    and `period_month` stands in `SUBMITTED` or `APPROVED`, refiling is
    rejected with `ERR_DUPLICATE_PENDING_CLAIM` (HTTP 409), so refiling
    becomes possible only after every prior claim for that period has been
    denied."

    Design: Corner/validations/duplicate_pending_claim_rejected
    """
    scenario = setup_submitted_claim(
        purchase_amount_cents=1000, transaction_count=1,
        merchant_overrides={"name": "Dup Drugs", "reimbursement_rate_pct": 50},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    assert scenario["claim"]["status"] == "SUBMITTED"
    res = api.create_reimbursement_claim(
        scenario["merchant"]["id"], "2026-08",
        make_merchant_operator_headers(scenario["merchant"]["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PENDING_CLAIM)


def test_claim_approve_without_fund_rejected(api, program_administrator_headers):
    """PRD §3.8: "A program fund must exist whose `fiscal_year` equals the
    year of the claim's `period_month`, else `ERR_NO_FUND_FOR_PERIOD`
    (HTTP 422)."
    PRD §3.8: "A new claim enters `SUBMITTED` with `program_fund_id` and
    `final_amount_cents` empty, and its `provisional_amount_cents` is computed
    and frozen at submission."

    Design: Corner/validations/claim_approve_without_fund_rejected
    """
    scenario = setup_submitted_claim(
        purchase_amount_cents=1000, transaction_count=1,
        merchant_overrides={"name": "Fundless Foods",
                            "reimbursement_rate_pct": 50},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    assert scenario["claim"]["provisional_amount_cents"] == 50

    res = api.approve_claim(scenario["claim"]["id"], program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_NO_FUND_FOR_PERIOD)

    claims = validate_success(
        api.list_reimbursement_claims(scenario["merchant"]["id"],
                                      program_administrator_headers), 200)
    claim_after = [c for c in claims if c["id"] == scenario["claim"]["id"]][0]
    assert claim_after["status"] == "SUBMITTED"
    assert claim_after["final_amount_cents"] is None


def test_claim_approve_fund_insufficient_rejected(api, program_administrator_headers):
    """PRD §3.8: "The recomputed `final_amount_cents` must fit within that
    fund's `available_cents`, else `ERR_FUND_INSUFFICIENT` (HTTP 402)."
    The fund holds 100 cents; the recomputed final amount is 150. The failed
    approval debits nothing.

    Design: Corner/validations/claim_approve_fund_insufficient_rejected
    """
    scenario = setup_submitted_claim(
        purchase_amount_cents=1000, transaction_count=3,
        fund_allocated_cents=100,
        merchant_overrides={"name": "Short Shops",
                            "reimbursement_rate_pct": 50},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    assert scenario["claim"]["provisional_amount_cents"] == 150

    res = api.approve_claim(scenario["claim"]["id"], program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_FUND_INSUFFICIENT)

    fund_after = validate_success(
        api.get_program_fund(scenario["fund"]["id"], program_administrator_headers),
        200)
    assert fund_after["paid_cents"] == 0, "no partial debit on a failed approval"
    assert fund_after["available_cents"] == 100
    assert_fund_invariant(fund_after)

    claims = validate_success(
        api.list_reimbursement_claims(scenario["merchant"]["id"],
                                      program_administrator_headers), 200)
    claim_after = [c for c in claims if c["id"] == scenario["claim"]["id"]][0]
    assert claim_after["status"] == "SUBMITTED"
