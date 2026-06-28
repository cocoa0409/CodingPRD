"""Loan origination, funding, the amortization calculation, and origination gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, validate_error_is_one_of,
    ApiErrorId,
    assert_loan, assert_installment,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    create_account, create_verified_account,
    setup_eligible_account_with_loan_disclosure, create_pending_loan, fund_loan,
    issue_disclosure, acknowledge_disclosure,
)


# =========================================================================
# Corner / entities + state_machines: loan creation
# =========================================================================

def test_loan_initial_state_pending(api):
    """PRD §3.3: "A newly created loan is in `lifecycle_status` of `PENDING`, `delinquency_status` of `CURRENT`, with `principal_paid_cents`, `interest_paid_cents`, `outstanding_principal_cents`, `on_time_streak`, and `missed_count` all at 0."

    Design: Corner/state_machines/loan_initial_state_pending
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA")
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_loan(data)
    assert data["lifecycle_status"] == "PENDING"
    assert data["delinquency_status"] == "CURRENT"


def test_create_loan_missing_required_field_rejected(api):
    """PRD §3.3: "supplying the `account_id`, the `disclosure_id` to pin, the `principal_cents` to lock into savings, and the `term_months`."
    PRD §2.5 (priority 17): "body well-formedness ... (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_loan_missing_required_field_rejected
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA")
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"], "principal_cents": 60000},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_loan_invalid_term_rejected(api):
    """PRD §3.3: "`term_months` must be exactly 12 or 24; a value outside these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_loan_invalid_term_rejected
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA")
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 18},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_loan_wrong_parent_account_not_found(api):
    """PRD §2.5: "a referenced account, loan, card, disclosure, payment, quote, or enrollment that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated."

    Design: Corner/entities/create_loan_wrong_parent_account_not_found
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    resp = api.create_loan(
        {"account_id": "22222222-2222-4222-8222-222222222222", "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_loans_filtered_by_account(api):
    """PRD §4: "List loans (filter by account_id, disclosure_id, lifecycle_status, delinquency_status)"
    PRD §2.3: "list results are ordered by their creation timestamp (`created_at`) in ascending order."

    Design: Corner/entities/fk_reverse_loans_by_account_filtered_list
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA")
    loan = create_pending_loan(acct["id"], disc["id"])
    resp = api.list_loans(make_borrower_headers(acct["id"]), params={"account_id": acct["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == loan["id"]


# =========================================================================
# Corner / validations: origination gates
# =========================================================================

def test_disclosure_not_acknowledged_blocks_loan_create(api):
    """PRD §3.3: "Creation requires the owning account's posture to be `ELIGIBLE` (otherwise `ERR_ACCOUNT_NOT_ELIGIBLE`) and requires the pinned disclosure to be `ACKNOWLEDGED` with a `product_kind` of `LOAN` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, HTTP 409)."

    Design: Corner/validations/disclosure_not_acknowledged_blocks_loan_create
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)  # ISSUED, not acknowledged
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    # Posture is BLOCKED here (disclosure_status still UNACKNOWLEDGED), so the eligibility
    # gate (priority 5) and the disclosure-ack check (priority 8) both describe this
    # rejection; the PRD does not uniquely pin which 409 surfaces.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ACCOUNT_NOT_ELIGIBLE, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED]
    )


# =========================================================================
# Difficulty / cross_entity_state_dependency
# =========================================================================

def test_loan_create_requires_account_eligible(api):
    """PRD §2.6: "Any origination or acknowledgement attempt made while the posture is not `ELIGIBLE` — that is, while it is `BLOCKED` or `FROZEN` — is rejected with `ERR_ACCOUNT_NOT_ELIGIBLE` (HTTP 409). This gate applies to loan creation-and-funding, secured-card creation, secured-card deposit posting, and secured-card activation."

    Design: Difficulty/cross_entity_state_dependency/loan_fund_requires_account_eligible
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)  # not acknowledged -> BLOCKED
    resp = api.create_loan(
        {"account_id": acct["id"], "disclosure_id": disc["id"],
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ACCOUNT_NOT_ELIGIBLE, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED]
    )
    refetched = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched["posture"] == "BLOCKED"


# =========================================================================
# Difficulty / priority_pair_validation_conflict
# =========================================================================

def test_not_found_beats_account_not_eligible(api):
    """PRD §2.5: "The same precedence holds for foreign keys supplied in a request body: a referenced account, loan, card, disclosure, payment, quote, or enrollment that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated."
    PRD §2.5: "so a stale version is never reported before a missing resource, and a posture failure surfaces ahead of a state-machine guard."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_account_not_eligible
    """
    # Account created but NOT verified and NO disclosure acknowledged -> posture BLOCKED.
    acct = create_account(state_code="CA")
    resp = api.create_loan(
        {"account_id": acct["id"],
         "disclosure_id": "00000000-0000-4000-8000-000000000000",
         "principal_cents": 60000, "term_months": 12},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# =========================================================================
# Difficulty / combinatorial_formula: amortized payment + split rounding
# =========================================================================

def test_amortized_payment_nonlinear(api):
    """PRD §3.3: "otherwise the exact payment is `principal_cents` multiplied by the monthly rate multiplied by (one plus the monthly rate) raised to the power of `term_months`, all divided by ((one plus the monthly rate) raised to the power of `term_months`, minus one). The resulting exact payment is rounded half up to whole cents in a single rounding step and stored as `monthly_payment_cents`."

    Design: Difficulty/combinatorial_formula/amortized_payment_nonlinear_mode_a
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=1599)
    acknowledge_disclosure(disc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=120000, term_months=12)
    resp = api.fund_loan(loan["id"], {}, make_loan_servicer_headers())
    data = validate_success(resp)
    assert data["monthly_payment_cents"] == 10887
    assert data["apr_bps"] == 1599


def test_amortization_split_rounding_order(api):
    """PRD §3.3: "For each period in order, the period's interest component is the running balance multiplied by the monthly rate, rounded half up to whole cents on that line (per-line rounding is pinned — the schedule is not a "sum then round" calculation)."
    PRD §3.3: "For the final period, the principal component is whatever balance remains (so the schedule fully amortizes), and that period's `amount_due_cents` is its principal component plus its interest component — the last installment thus absorbs the rounding remainder."

    Design: Difficulty/combinatorial_formula/amortization_split_rounding_order_mode_b
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=1599)
    acknowledge_disclosure(disc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=120000, term_months=12)
    fund_loan(loan["id"])
    resp = api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    rows, _meta = validate_paginated(resp)
    by_period = {r["period_index"]: r for r in rows}
    assert by_period[1]["interest_component_cents"] == 1599
    assert by_period[1]["principal_component_cents"] == 9288
    assert by_period[2]["interest_component_cents"] == 1475
    assert by_period[2]["principal_component_cents"] == 9412
    assert by_period[12]["amount_due_cents"] == 10887
    assert by_period[12]["principal_component_cents"] == 10744
    assert by_period[12]["interest_component_cents"] == 143
    assert sum(r["principal_component_cents"] for r in rows) == 120000


def test_loan_apr_copied_from_disclosure(api):
    """PRD §3.3: "copies the disclosure's APR into the loan's own `apr_bps` (which is immutable thereafter)"

    Design: Corner/entities/loan_computed_apr_copied_from_disclosure_input_ignored
    """
    acct = create_verified_account(state_code="CA")
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=1599)
    acknowledge_disclosure(disc["id"], acct["id"])
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=120000, term_months=12)
    data = validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers()))
    assert data["apr_bps"] == 1599
    assert data["monthly_payment_cents"] == 10887


def test_zero_apr_level_payment_correct(api):
    """PRD §3.3: "If that monthly rate is 0, the exact payment is `principal_cents` divided by `term_months`"

    Design: Corner/calculations/zero_apr_level_payment_correct
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=60000, term_months=12)
    data = validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers()))
    assert data["monthly_payment_cents"] == 5000
    rows, _ = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    p1 = next(r for r in rows if r["period_index"] == 1)
    assert p1["interest_component_cents"] == 0
    assert p1["principal_component_cents"] == 5000


# =========================================================================
# Corner / consistency_model + boundary_precision (empty schedule)
# =========================================================================

def test_funded_schedule_immediately_visible(api):
    """PRD §3.3: "Immediately after the payment is computed, the system builds the per-period amortization split, generating one `InstallmentSchedule` row per period."
    PRD §3.3: "Each schedule row records its `loan_id`, a 1-based `period_index` running from 1 to `term_months`, a `due_date`, an `amount_due_cents`, a `principal_component_cents`, an `interest_component_cents`, an `amount_paid_cents` starting at 0, and a `status` of `SCHEDULED`."

    Design: Corner/consistency_model/immediate_visibility_of_funded_schedule
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=60000, term_months=12)
    fund_loan(loan["id"])
    rows, meta = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]), params={"limit": 100})
    )
    assert meta["total_count"] == 12
    for r in rows:
        assert_installment(r)
        assert r["status"] == "SCHEDULED"


def test_empty_schedule_on_pending_loan(api):
    """PRD §3.3: "A newly created loan is in `lifecycle_status` of `PENDING`"
    PRD §3.3: "Immediately after the payment is computed, the system builds the per-period amortization split, generating one `InstallmentSchedule` row per period."

    Design: Difficulty/boundary_precision_check/empty_schedule_on_pending_loan
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=60000, term_months=12)
    rows, meta = validate_paginated(
        api.list_schedule(loan["id"], make_borrower_headers(acct["id"]))
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert meta["has_more"] is False
