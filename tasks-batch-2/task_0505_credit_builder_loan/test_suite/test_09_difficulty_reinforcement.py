"""Second-angle tests for each depth (difficulty) instance.

Each test reuses the same scenario as its primary counterpart but asserts a
distinct, uniquely-PRD-derivable observable, so every difficulty instance is
covered by at least two tests.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, validate_error_is_one_of,
    ApiErrorId,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    create_account, create_verified_account, issue_disclosure, acknowledge_disclosure,
    setup_eligible_account_with_loan_disclosure, setup_eligible_account_with_card_disclosure,
    create_pending_loan, fund_loan, setup_funded_loan, post_payment, loan_version,
    setup_eligible_account_with_active_card, setup_active_card, create_card, post_deposit,
    card_version, setup_graduated_loan_with_active_card,
    set_clock, run_delinquency_sweep, run_bureau_sweep, run_autopay,
)


# =========================================================================
# Difficulty / dual_variant_calc
# =========================================================================

def test_payoff_scheduled_remaining_exceeds_actual(api):
    """PRD §3.8: "The **comparison** figure, `scheduled_remaining_cents`, is the sum of `amount_due_cents` over every installment not yet `PAID` (those with status `SCHEDULED` or `LATE`); it represents the full remaining scheduled obligation including all future interest and is shown only for TILA comparison."
    PRD §3.8: "The **binding** figure, `payoff_amount_cents`, is the amount the borrower actually pays today: it is `outstanding_principal_cents`, plus accrued interest to date, plus the current outstanding late-fee balance."

    Design: Difficulty/dual_variant_calc/loan_payoff_actual_vs_scheduled
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=1599, principal_cents=120000, term_months=12,
        funded_at="2026-02-01T00:00:00Z",
    )
    post_payment(loan["id"], acct["id"], 10887, loan["version"])
    quote = validate_success(
        api.create_payoff_quote(loan["id"], {}, make_borrower_headers(acct["id"])),
        expected_status=201,
    )
    # scheduled_remaining (full future obligation) strictly exceeds the binding payoff.
    assert quote["scheduled_remaining_cents"] > quote["payoff_amount_cents"]
    assert quote["interest_savings_cents"] == (
        quote["scheduled_remaining_cents"] - quote["payoff_amount_cents"]
    )
    assert quote["status"] == "ACTIVE"


def test_score_optimistic_strictly_above_realized(api):
    """PRD §3.12: "the **optimistic projection** variant instead assumes the in-flight (current) cycle is reported on-time: it adds exactly one more on-time mark and zero late marks for the in-flight cycle before scoring, again persisting nothing."
    PRD §3.12: "Add a payment-history component: 6 points for each on-time installment reported"

    Design: Difficulty/dual_variant_calc/score_optimistic_vs_realized
    """
    set_clock("2026-01-15T00:00:00Z")
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], ldisc["id"], principal_cents=60000, term_months=12)
    loan = fund_loan(loan["id"])
    post_payment(loan["id"], acct["id"], 5000, loan_version(loan["id"], acct["id"]))
    run_bureau_sweep()

    optimistic = validate_success(
        api.get_score(acct["id"], make_borrower_headers(acct["id"]), params={"projection": "optimistic"})
    )
    realized = validate_success(api.get_score(acct["id"], make_borrower_headers(acct["id"])))
    # Exactly one extra on-time mark => +6 points and persists nothing.
    assert optimistic["simulated_score"] - realized["simulated_score"] == 6


# =========================================================================
# Difficulty / combinatorial_formula
# =========================================================================

def test_amortized_payment_apr_immutable_field(api):
    """PRD §3.3: "copies the disclosure's APR into the loan's own `apr_bps` (which is immutable thereafter)"
    PRD §3.3: "The resulting exact payment is rounded half up to whole cents in a single rounding step and stored as `monthly_payment_cents`."

    Design: Difficulty/combinatorial_formula/amortized_payment_nonlinear_mode_a
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=1599)
    acknowledge_disclosure(disc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=120000, term_months=12)
    funded = validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers()))
    assert funded["monthly_payment_cents"] == 10887
    # Re-reading the loan shows the same copied APR.
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["apr_bps"] == 1599
    assert refetched["monthly_payment_cents"] == 10887


def test_amortization_split_first_period_amount_due_equals_payment(api):
    """PRD §3.3: "For every period except the last, the principal component is `monthly_payment_cents` minus that period's interest component, and the period's `amount_due_cents` equals `monthly_payment_cents`."
    PRD §3.3: "the period's interest component is the running balance multiplied by the monthly rate, rounded half up to whole cents on that line"

    Design: Difficulty/combinatorial_formula/amortization_split_rounding_order_mode_b
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=1599)
    acknowledge_disclosure(disc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=120000, term_months=12)
    fund_loan(loan["id"])
    rows, _ = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    by_period = {r["period_index"]: r for r in rows}
    # Non-last periods: amount_due == monthly_payment; principal == payment - interest.
    for k in range(1, 12):
        assert by_period[k]["amount_due_cents"] == 10887
        assert by_period[k]["principal_component_cents"] == 10887 - by_period[k]["interest_component_cents"]


# =========================================================================
# Difficulty / non_linear_state_machine
# =========================================================================

def test_loan_lifecycle_stays_active_through_delinquency(api):
    """PRD §3.5: "Active loans are unaffected by a freeze — they keep accruing; only the origination of new products is gated by posture."
    PRD §3.5: "When that figure is between 1 and 30 inclusive, a loan whose `delinquency_status` is `CURRENT` advances to `DPD_30`"

    Design: Difficulty/non_linear_state_machine/loan_parallel_axes_independent
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=1599, principal_cents=120000, term_months=12,
        funded_at="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-10T00:00:00Z")
    run_delinquency_sweep()
    aged = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    # delinquency advanced on its own axis while lifecycle is untouched.
    assert aged["delinquency_status"] == "DPD_30"
    assert aged["lifecycle_status"] == "ACTIVE"
    assert aged["missed_count"] >= 1
    assert aged["on_time_streak"] == 0


def test_card_suspended_then_active_after_resume_spendable(api):
    """PRD §3.9: "A `LoanServicer` can suspend an `ACTIVE` card (`ACTIVE → SUSPENDED`), blocking spend while freezing the existing balance"
    PRD §3.9: "A `LoanServicer` can resume a `SUSPENDED` card (`SUSPENDED → ACTIVE`), provided the account posture is `ELIGIBLE`, making it spendable again."

    Design: Difficulty/non_linear_state_machine/card_suspend_resume_revert_cycle
    """
    acct, _cdisc, card = setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000)
    validate_success(api.suspend_card(card["id"], {"reason": "review"}, make_loan_servicer_headers()))
    resumed = validate_success(api.resume_card(card["id"], {}, make_loan_servicer_headers()))
    assert resumed["status"] == "ACTIVE"
    # After resume the line is spendable again up to the limit.
    charged = validate_success(
        api.charge_card(card["id"], {"amount_cents": 10000}, make_borrower_headers(acct["id"]))
    )
    assert charged["balance_cents"] == 10000


# =========================================================================
# Difficulty / transitive_cascade
# =========================================================================

def test_early_payoff_marks_installments_paid(api):
    """PRD §3.7: "On payoff the system marks every still-`SCHEDULED` or `LATE` installment as `PAID`, sets the `delinquency_status` to `CURRENT`"
    PRD §3.8: "the loan is driven to `PAID_OFF`, releasing the locked savings to the wallet via the payoff cascade."

    Design: Difficulty/transitive_cascade/early_payoff_release_cascade_depth3
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    quote = validate_success(
        api.create_payoff_quote(loan["id"], {}, make_borrower_headers(acct["id"])),
        expected_status=201,
    )
    validate_success(api.early_payoff(loan["id"], {"quote_id": quote["id"]}, make_borrower_headers(acct["id"])))
    rows, _ = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    assert all(r["status"] == "PAID" for r in rows)
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["delinquency_status"] == "CURRENT"


def test_release_deposit_stamps_released_and_closes(api):
    """PRD §3.10: "every `POSTED` deposit on the card is moved to `RELEASED` and stamped with `released_at`"
    PRD §3.10: "The card ends in CLOSED."

    Design: Difficulty/transitive_cascade/release_deposit_wallet_cascade_depth3
    """
    acct, _loan, card, _total = setup_graduated_loan_with_active_card(
        state_code="CA", principal_cents=60000, deposit_amounts=(50000,),
        servicer_user_id="servicer-S1",
    )
    closed = validate_success(api.release_deposit(card["id"], {}, make_compliance_officer_headers("compliance-C1")))
    assert closed["status"] == "CLOSED"
    deps, _ = validate_paginated(
        api.list_deposits(card["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    assert len(deps) >= 1
    for dep in deps:
        assert dep["status"] == "RELEASED"


# =========================================================================
# Difficulty / priority_pair_validation_conflict
# =========================================================================

def test_not_found_when_disclosure_missing_and_blocked(api):
    """PRD §2.5: "The same precedence holds for foreign keys supplied in a request body: a referenced account, loan, card, disclosure, payment, quote, or enrollment that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_account_not_eligible
    """
    acct = create_account(state_code="CA")  # BLOCKED (not verified, no acknowledged disclosure)
    resp = api.create_loan(
        {"account_id": acct["id"],
         "disclosure_id": "00000000-0000-4000-8000-000000000000",
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    # 404 surfaces even though the eligibility gate would also reject this account.
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_sod_conflict_precedes_releasability(api):
    """PRD §3.10: "If the same person who funded the loan attempts to release the card's deposit, the request is rejected with `ERR_SOD_CONFLICT` (HTTP 409)."
    PRD §3.10: "This check is evaluated ahead of the releasability check in the priority order of §2.5."

    Design: Difficulty/priority_pair_validation_conflict/sod_conflict_beats_deposit_not_releasable
    """
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])
    loan = validate_success(
        api.create_loan(
            {"account_id": acct["id"], "disclosure_id": ldisc["id"],
             "principal_cents": 60000, "term_months": 12},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers("dual-7")))
    card = setup_active_card(acct["id"], cdisc["id"], deposit_cents=50000)
    # Same user funded and now tries to release; card also not releasable -> SoD wins.
    resp = api.release_deposit(card["id"], {}, make_compliance_officer_headers("dual-7"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)


# =========================================================================
# Difficulty / boundary_precision_check
# =========================================================================

def test_deposit_just_under_cap_accepted(api):
    """PRD §3.9: "the total of posted deposits on a card must not exceed 250000 cents, which if breached yields `ERR_DEPOSIT_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/deposit_cap_exact_vs_over
    """
    acct, cdisc = setup_eligible_account_with_card_disclosure(state_code="CA")
    card = create_card(acct["id"], cdisc["id"])
    post_deposit(card["id"], acct["id"], 200000, card["version"])
    v2 = card_version(card["id"], acct["id"])
    # total -> 249999 (one cent under the cap) is accepted.
    ok = validate_success(
        api.create_deposit(
            card["id"], {"amount_cents": 49999, "expected_card_version": v2},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    assert ok["status"] == "POSTED"
    refetched = validate_success(api.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    assert refetched["deposit_cents"] == 249999


def test_pending_loan_has_no_schedule_rows(api):
    """PRD §3.3: "Immediately after the payment is computed, the system builds the per-period amortization split, generating one `InstallmentSchedule` row per period."
    PRD §3.3: "Funding is a `LoanServicer` action that drives the loan from `PENDING` to `ACTIVE`."

    Design: Difficulty/boundary_precision_check/empty_schedule_on_pending_loan
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=60000, term_months=12)
    rows, meta = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    # An unfunded PENDING loan exposes zero installments.
    assert len(rows) == 0
    assert meta["total_count"] == 0


# =========================================================================
# Difficulty / cross_entity_state_dependency
# =========================================================================

def test_loan_create_blocked_when_kyc_pending(api):
    """PRD §2.6: "it is `ELIGIBLE` exactly when the account's `kyc_status` is `VERIFIED` **and** its `disclosure_status` is `ACKNOWLEDGED` **and** its `status` is `OPEN`; it is `FROZEN` whenever the account `status` is `FROZEN`; and it is `BLOCKED` in every other case."
    PRD §2.6: "Any origination or acknowledgement attempt made while the posture is not `ELIGIBLE` — that is, while it is `BLOCKED` or `FROZEN` — is rejected with `ERR_ACCOUNT_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/loan_fund_requires_account_eligible
    """
    # Account VERIFIED but disclosure NOT acknowledged -> BLOCKED.
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    blocked = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert blocked["posture"] == "BLOCKED"
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ACCOUNT_NOT_ELIGIBLE, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED]
    )


def test_release_rejected_while_card_not_graduation_eligible(api):
    """PRD §3.10: "the card's `graduation_eligible` must be true and the card's `balance_cents` must be 0, otherwise the release is rejected with `ERR_DEPOSIT_NOT_RELEASABLE` (HTTP 409)."
    PRD §3.6: "if a secured card exists for the same account and that card's `balance_cents` is 0, the card's `graduation_eligible` flag is set to true" — only graduation sets it.

    Design: Difficulty/cross_entity_state_dependency/deposit_release_requires_loan_graduated
    """
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])
    loan = validate_success(
        api.create_loan(
            {"account_id": acct["id"], "disclosure_id": ldisc["id"],
             "principal_cents": 60000, "term_months": 12},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers("srv-A")))
    card = setup_active_card(acct["id"], cdisc["id"], deposit_cents=50000)
    # Loan never graduated -> card.graduation_eligible false -> release blocked (SoD satisfied).
    resp = api.release_deposit(card["id"], {}, make_compliance_officer_headers("cmp-Z2"))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_RELEASABLE)


# =========================================================================
# Difficulty / resource_temporal_overlap
# =========================================================================

def test_autopay_second_run_creates_no_extra_payment(api):
    """PRD §3.11: "when the current installment was already drafted in that window, no payment is created."
    PRD §3.11: "For each such enrollment it creates a payment with `source` of `AUTOPAY`, runs the same allocation waterfall"

    Design: Difficulty/resource_temporal_overlap/autopay_half_open_monthly_window_no_double_draft
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    validate_success(
        api.create_autopay(
            {"loan_id": loan["id"], "day_of_month": 5, "funding_wallet": False},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    set_clock("2026-03-05T00:00:00Z")
    run_autopay()
    pays_after_first, meta1 = validate_paginated(
        api.list_loan_payments(loan["id"], make_borrower_headers(acct["id"]), params={"source": "AUTOPAY"})
    )
    run_autopay()
    pays_after_second, meta2 = validate_paginated(
        api.list_loan_payments(loan["id"], make_borrower_headers(acct["id"]), params={"source": "AUTOPAY"})
    )
    assert meta1["total_count"] == 1
    assert meta2["total_count"] == 1  # idempotent: no extra draft in the same window


def test_bureau_second_sweep_no_extra_score_snapshot(api):
    """PRD §3.12: "At most one report exists per combination of `loan_id`, `tradeline_kind`, and `cycle_label` calendar-month bucket: re-running the sweep in the same YYYY-MM bucket creates no additional rows and skips emission where a row already exists."
    PRD §3.12: "the system persists one `ScoreSnapshot` per account per cycle"

    Design: Difficulty/resource_temporal_overlap/bureau_inclusive_calendar_bucket_one_report
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-20T00:00:00Z")
    run_bureau_sweep()
    run_bureau_sweep()
    # One snapshot per account per cycle, regardless of re-runs in the same bucket.
    snaps, meta = validate_paginated(
        api.list_score_snapshots(acct["id"], make_borrower_headers(acct["id"]))
    )
    assert meta["total_count"] == 1
    assert snaps[0]["cycle_label"] == "2026-03"


# =========================================================================
# Difficulty / compensating_invariant
# =========================================================================

def test_payoff_releases_exactly_principal_paid(api):
    """PRD §3.7: "credits the full `principal_paid_cents` to the account's `wallet_cents`."
    PRD §3.4: "After allocation, `principal_paid_cents` is increased by `applied_principal_cents`, `interest_paid_cents` is increased by `applied_interest_cents`, and `outstanding_principal_cents` is recomputed as `principal_cents` minus `principal_paid_cents`, floored at 0."

    Design: Difficulty/compensating_invariant/locked_savings_conserved_on_payoff
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    post_payment(loan["id"], acct["id"], 60000, loan["version"])
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    # Wallet gain equals exactly the principal paid; outstanding driven to 0.
    assert refetched["outstanding_principal_cents"] == 0
    assert refetched_acct["wallet_cents"] == refetched["principal_paid_cents"] == 60000


def test_release_credits_wallet_by_prior_deposit_total(api):
    """PRD §3.10: "the full `deposit_cents` is credited to the account's `wallet_cents` while `credit_limit_cents` and `deposit_cents` are both zeroed."
    PRD §3.9: "sets `credit_limit_cents` equal to `deposit_cents` (the line is one-to-one secured)."

    Design: Difficulty/compensating_invariant/card_deposit_conserved_on_release
    """
    acct, _loan, card, total_deposit = setup_graduated_loan_with_active_card(
        state_code="CA", principal_cents=60000, deposit_amounts=(40000, 30000),
        servicer_user_id="srv-Q",
    )
    pre = validate_success(api.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    pre_wallet = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))["wallet_cents"]
    assert pre["deposit_cents"] == total_deposit == 70000
    validate_success(api.release_deposit(card["id"], {}, make_compliance_officer_headers("cmp-R")))
    post_wallet = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))["wallet_cents"]
    # Wallet increases by exactly the prior deposit total — no cents created or lost.
    assert post_wallet - pre_wallet == total_deposit
