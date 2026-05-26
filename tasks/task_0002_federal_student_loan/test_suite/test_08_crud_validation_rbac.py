"""CRUD, listing, validation errors, RBAC, OCC happy path, and immediate
consistency — corner-design coverage.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_loan_with_active_standard_plan,
    setup_loan_in_default,
    setup_discharge_application_under_review,
    create_and_certify_income,
    create_repayment_plan, create_and_activate_plan,
    post_payment,
    create_borrower_payload, create_loan_payload,
    create_qualifying_employment_payload,
    create_repayment_plan_payload,
    create_payment_payload,
    make_borrower_headers,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    build_user_headers,
)


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


# ─── entities ────────────────────────────────────────────

def test_borrower_create_defaults_version_and_is_veteran(api):
    """POST /borrowers without is_veteran defaults to false; the new entity
    has version=1.

    PRD §3.1: "is_veteran defaults to false when the field is not supplied at
    creation."
    PRD §2.4: "The version field is an integer starting at 1 on creation and
    incrementing by 1 on every mutation that produces a new persisted state
    for the resource."

    Design: Corner/entities/borrower_create_returns_id_and_defaults
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_borrower(
        {"full_name": "Defaults B", "ssn_last4": "1111"}, LS)
    borrower = validate_success(res, 201)
    assert borrower["version"] == 1
    assert borrower["is_veteran"] is False


def test_borrower_create_missing_full_name_returns_invalid_request(api):
    """POST /borrowers without full_name fails with ERR_INVALID_REQUEST.

    PRD §3.1: "They are created with a legal full_name, the last four digits
    of their Social Security number stored as ssn_last4 for audit display only
    (the field never participates in business decisions), and an is_veteran
    flag that marks eligibility to later file a total-permanent-disability
    discharge application; is_veteran defaults to false when the field is not
    supplied at creation."
    PRD §2.7: "13. General request shape — required fields and enum membership
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/borrower_create_missing_full_name_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_borrower({"ssn_last4": "0001"}, LS)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_loan_create_invalid_loan_type_enum_rejected(api):
    """POST /loans with an unknown loan_type enum value fails with
    ERR_INVALID_REQUEST.

    PRD §3.2: "the loan's loan_type from the enumeration DIRECT_SUB,
    DIRECT_UNSUB, or DIRECT_PLUS"
    PRD §2.7: "13. General request shape — required fields and enum membership
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/loan_create_invalid_loan_type_enum_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Enum B", ssn_last4="0002")
    res = api.create_loan({
        "borrower_id": borrower["id"],
        "loan_type": "DIRECT_BAD",
        "principal_cents": 100_000,
        "interest_rate_bps": 500,
        "disbursement_date": "2026-06-01T00:00:00Z",
    }, LS)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_loan_create_defaults_status_originated_and_version_one(api):
    """Newly-created Loan has status=ORIGINATED and version=1.

    PRD §3.2: "On creation, the loan enters ORIGINATED status,
    principal_balance_cents is initialized to principal_cents, both
    accrued_interest_cents and capitalized_interest_cents are zero, and
    last_accrual_date is set to disbursement_date so that interest begins
    accruing from the day of disbursement forward."
    PRD §2.4: "The version field is an integer starting at 1 on creation and
    incrementing by 1 on every mutation that produces a new persisted state
    for the resource."

    Design: Corner/entities/loan_create_defaults_status_originated
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Init B", ssn_last4="0003")
    res = api.create_loan(create_loan_payload(borrower["id"]), LS)
    loan = validate_success(res, 201)
    assert loan["status"] == "ORIGINATED"
    assert loan["version"] == 1


def test_loan_get_nonexistent_returns_loan_not_found(api):
    """GET /loans/{nonexistent uuid} returns ERR_LOAN_NOT_FOUND.

    PRD §2.7: "3. Existence of any path-referenced Loan (ERR_LOAN_NOT_FOUND)."

    Design: Corner/entities/loan_get_not_found_uuid_returns_loan_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_loan(NON_EXISTENT_UUID, LS)
    validate_error(res, ApiErrorId.ERR_LOAN_NOT_FOUND.value)


def test_loan_listing_returns_paginated_envelope(api):
    """GET /loans returns a paginated envelope including total_count, has_more,
    limit, and offset in meta.

    PRD §2.3: "Each list response embeds limit, offset, total_count, and
    has_more in the meta block of the envelope."

    Design: Corner/entities/loan_listing_paginates_with_total_count_and_has_more
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.list_loans(LS)
    data, meta = validate_paginated(res)
    assert "total_count" in meta
    assert "has_more" in meta
    assert "limit" in meta
    assert "offset" in meta


def test_loan_create_pslf_count_is_zero_at_creation(api):
    """Newly-created Loan returns pslf_qualifying_payment_count == 0 (it is a
    computed field and the loan has no payments yet).

    PRD §3.7: "Public Service Loan Forgiveness depends on the loan's
    pslf_qualifying_payment_count, an integer derived from the borrower's
    payment, employment, and status histories."
    PRD §3.7: "Reads of the count off the loan are guaranteed to reflect the
    latest such recomputation."

    Design: Corner/entities/loan_computed_pslf_count_ignores_input
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Cmp B", ssn_last4="0004")
    res = api.create_loan(create_loan_payload(borrower["id"]), LS)
    loan = validate_success(res, 201)
    assert loan["pslf_qualifying_payment_count"] == 0


# ─── calculations / validations ──────────────────────────

def test_payment_zero_amount_rejected_out_of_range(api):
    """POST /payments with amount_cents == 0 fails ERR_PAYMENT_AMOUNT_OUT_OF_RANGE.

    PRD §3.6: "The amount itself must not exceed the total outstanding
    obligation, defined as principal_balance_cents plus accrued_interest_cents;
    a value below 1 cent or above that ceiling is rejected with
    ERR_PAYMENT_AMOUNT_OUT_OF_RANGE."

    Design: Corner/validations/payment_negative_amount_returns_out_of_range
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Pay0", ssn_last4="0016",
    )
    res = api.create_payment(
        create_payment_payload(loan["id"], amount_cents=0,
                               payment_date="2026-06-01T00:00:00Z"),
        make_borrower_headers(borrower["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_OUT_OF_RANGE.value)


def test_payment_future_date_rejected(api):
    """POST /payments with payment_date > server clock fails with
    ERR_FUTURE_PAYMENT.

    PRD §3.6: "The submitted payment_date must be on or before the current
    server clock — a payment dated in the future is rejected with
    ERR_FUTURE_PAYMENT."

    Design: Corner/validations/payment_future_date_returns_future_payment
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Fut B", ssn_last4="0017",
    )
    res = api.create_payment(
        create_payment_payload(
            loan["id"], amount_cents=10_000,
            payment_date="2030-01-01T00:00:00Z"),
        make_borrower_headers(borrower["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FUTURE_PAYMENT.value)


def test_qualifying_employment_invalid_period_rejected(api):
    """POST /qualifying-employments with period_end <= period_start fails
    ERR_INVALID_PERIOD.

    PRD §3.1: "The end of the employment window must be strictly later than
    the start; a submission whose period_end is on or before period_start is
    rejected with ERR_INVALID_PERIOD."

    Design: Corner/validations/qualifying_employment_invalid_period_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Per B", ssn_last4="0018")
    res = api.create_qualifying_employment(
        create_qualifying_employment_payload(
            borrower["id"],
            employer_name="Bad period", employer_type="GOVERNMENT",
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-01-01T00:00:00Z",
        ),
        make_borrower_headers(borrower["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PERIOD.value)


def test_plan_already_active_returns_error(api):
    """Activating a second plan while one is already ACTIVE for the same loan
    fails ERR_PLAN_ALREADY_ACTIVE.

    PRD §3.5: "Activation has three preconditions: the plan must currently be
    PENDING, the parent loan must be in REPAYMENT, and no other plan with the
    same loan_id may already be ACTIVE."
    PRD §3.5: "The third precondition is the source of ERR_PLAN_ALREADY_ACTIVE;"

    Design: Corner/validations/plan_already_active_returns_plan_already_active
    """
    borrower, loan, plan1 = setup_loan_with_active_standard_plan(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Dup B", ssn_last4="0019",
        loan_type="DIRECT_UNSUB", principal_cents=100_000,
        interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
        plan_effective_date="2026-06-01T00:00:00Z",
    )
    # Certify income so the IBR plan can be created (IDR plans use it).
    create_and_certify_income(
        borrower["id"], agi_cents=6_000_000, family_size=2,
        state_code="CA", effective_date="2026-05-01T00:00:00Z",
    )
    # Get the loan's current version (it bumped on first plan create + activate).
    loan_now = validate_success(api.get_loan(loan["id"], LS), 200)
    plan2 = create_repayment_plan(
        loan["id"], loan_now["version"],
        plan_type="IBR", effective_date="2026-06-01T00:00:00Z",
    )
    res = api.activate_repayment_plan(plan2["id"], LS)
    validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE.value)


def test_not_veteran_discharge_rejected(api):
    """Approve VETERAN_TOTAL_DISABILITY when is_veteran=false fails
    ERR_NOT_VETERAN.

    PRD §3.9: "when discharge_type is VETERAN_TOTAL_DISABILITY, the borrower's
    is_veteran must be true, and a false value rejects with ERR_NOT_VETERAN;"

    Design: Corner/validations/not_veteran_discharge_rejected
    """
    borrower, loan, app = setup_discharge_application_under_review(
        clock_iso="2026-06-01T00:00:00Z",
        is_veteran=False,
        discharge_type="VETERAN_TOTAL_DISABILITY",
        full_name="Nv B", ssn_last4="0021",
    )
    res = api.approve_discharge(
        app["id"],
        {"review_notes": "x",
         "expected_application_version": app["version"]},
        LS,
    )
    validate_error(res, ApiErrorId.ERR_NOT_VETERAN.value)


def test_rehabilitation_with_zero_post_default_payments_rejected(api):
    """Rehabilitate when zero post-default APPLIED payments exist fails with
    ERR_REHABILITATION_NOT_QUALIFIED.

    PRD §3.8: "the transition's business precondition is that the loan must
    have at least 9 payments with status APPLIED whose payment_date is strictly
    later than the effective_at of the most recent StatusChange carrying
    reason_code DEFAULT_DECLARATION. When that count is less than 9, the
    transition is rejected with ERR_REHABILITATION_NOT_QUALIFIED."

    Design: Corner/validations/rehabilitation_count_insufficient_returns_rehab_not_qualified
    """
    borrower, loan = setup_loan_in_default(
        clock_start_iso="2025-06-01T00:00:00Z",
        clock_after_iso="2026-03-10T00:00:00Z",
        full_name="Reh B", ssn_last4="0022",
    )
    res = api.rehabilitate(loan["id"], CA)
    validate_error(res, ApiErrorId.ERR_REHABILITATION_NOT_QUALIFIED.value)


def test_stale_loan_version_on_plan_create(api):
    """A second POST /repayment-plans using the SAME expected_loan_version as
    the first one (the first plan-create bumped Loan.version) fails with
    ERR_STALE_LOAN_VERSION.

    PRD §2.5: "the server compares this value to the loan's current version;
    if another writer (for instance, an earlier plan creation that has already
    taken effect) has advanced the loan's version since the client last read
    it, the create is rejected with ERR_STALE_LOAN_VERSION (HTTP 412),
    preventing the client from inserting a plan against a loan state it has
    not actually observed."

    Design: Corner/validations/stale_loan_version_on_plan_create
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Stl B", ssn_last4="0023",
        loan_type="DIRECT_UNSUB", principal_cents=100_000,
        interest_rate_bps=500,
    )
    pre_version = loan["version"]
    # First create — succeeds and bumps loan.version.
    create_repayment_plan(
        loan["id"], pre_version,
        plan_type="STANDARD", effective_date="2026-06-01T00:00:00Z",
    )
    # Second create with the now-stale expected_loan_version.
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], pre_version,
            plan_type="IBR", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    validate_error(res, ApiErrorId.ERR_STALE_LOAN_VERSION.value)


# ─── endpoints ───────────────────────────────────────────

def test_status_changes_listed_in_chronological_order(api):
    """Status-change listing returns three rows in ASC effective_at order after
    ORIGINATED → IN_SCHOOL → GRACE → REPAYMENT.

    PRD §3.10: "Listings of these rows for a loan return them in ascending
    order — first by effective_at, then by created_at as the tiebreaker."

    Design: Corner/endpoints/get_loan_status_changes_returns_chronological_list
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Sch B", ssn_last4="0026",
    )
    res = api.list_status_changes(loan["id"], LS)
    data, _meta = validate_paginated(res)
    assert len(data) == 3
    # Ascending — first transition is ORIGINATED → IN_SCHOOL, last is
    # GRACE → REPAYMENT.
    assert data[0]["to_status"] == "IN_SCHOOL"
    assert data[-1]["to_status"] == "REPAYMENT"


def test_payments_filtered_by_loan_id(api):
    """GET /payments?loan_id=X returns only the payments whose loan_id == X.

    PRD §4: "List payments (filter by loan_id, repayment_plan_id, and/or
    reversed_by_payment_id)"

    Design: Corner/endpoints/payments_filtered_by_loan_id
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Flt B", ssn_last4="0027")
    loan1 = create_loan(
        borrower["id"], principal_cents=100_000,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan1["id"])
    loan2 = create_loan(
        borrower["id"], principal_cents=200_000,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan2["id"])
    post_payment(loan1["id"], borrower["id"],
                 amount_cents=1_000, payment_date="2026-06-01T00:00:00Z")
    post_payment(loan2["id"], borrower["id"],
                 amount_cents=2_000, payment_date="2026-06-01T00:00:00Z")

    res = api.list_payments(LS, params={"loan_id": loan1["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert all(p["loan_id"] == loan1["id"] for p in data)


# ─── errors ──────────────────────────────────────────────

def test_unauthenticated_when_headers_missing(api):
    """POST /borrowers without X-User-Role / X-User-ID returns
    ERR_UNAUTHENTICATED.

    PRD §2.1: "A request that omits either header, or whose values are
    malformed, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_missing_headers
    """
    # No clock set — PRD doesn't require it before the auth check; that check
    # always runs first regardless.
    res = api.create_borrower(
        {"full_name": "Anon B", "ssn_last4": "0028"},
        headers={"Content-Type": "application/json"},  # no auth headers
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_resource_not_found_on_repayment_plan_activate(api):
    """POST /repayment-plans/{nonexistent}/activate returns
    ERR_RESOURCE_NOT_FOUND.

    PRD §2.7: "5. Existence of any other path-referenced resource —
    RepaymentPlan, Payment, DischargeApplication, IncomeCertification, or
    QualifyingEmployment (ERR_RESOURCE_NOT_FOUND)."

    Design: Corner/errors/err_resource_not_found_on_repayment_plan_activate
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.activate_repayment_plan(NON_EXISTENT_UUID, LS)
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ─── rbac ────────────────────────────────────────────────

def test_borrower_cannot_certify_income(api):
    """Borrower role calling /income-certifications/{id}/certify (LoanServicer-
    exclusive) returns ERR_UNAUTHORIZED.

    PRD §4: "POST /loan-servicing/income-certifications/{id}/certify | Transition
    SUBMITTED to CERTIFIED | LoanServicer"
    PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation under the role matrix is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/borrower_cannot_certify_income
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Rbac B", ssn_last4="0029")
    # Borrower files an IncomeCertification (allowed) but tries to certify it
    # (LoanServicer-only).
    from prd_bench_local_runner.testing import get_success_data
    ic = get_success_data(api.create_income_certification(
        {"borrower_id": borrower["id"], "agi_cents": 6_000_000,
         "family_size": 2, "state_code": "CA",
         "effective_date": "2026-05-01T00:00:00Z"},
        make_borrower_headers(borrower["id"]),
    ))
    res = api.certify_income_certification(
        ic["id"], make_borrower_headers(borrower["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_collections_agent_cannot_post_payment(api):
    """CollectionsAgent role calling POST /payments fails ERR_UNAUTHORIZED —
    payments are restricted to Borrower and LoanServicer.

    PRD §4: "POST /loan-servicing/payments | Post a payment (PENDING) |
    Borrower, LoanServicer"
    PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation under the role matrix is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/collections_agent_cannot_post_payment
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Coll B", ssn_last4="0031",
    )
    res = api.create_payment(
        create_payment_payload(loan["id"], amount_cents=1_000,
                               payment_date="2026-06-01T00:00:00Z"),
        TEST_USERS["collections_agent_headers"],
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_loan_servicer_cannot_declare_default(api):
    """LoanServicer calling /declare-default (CollectionsAgent-exclusive)
    fails ERR_UNAUTHORIZED — peer-role enforcement.

    PRD §4: "POST /loan-servicing/loans/{id}/declare-default | Transition
    REPAYMENT to DEFAULT | CollectionsAgent"
    PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation under the role matrix is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/loan_servicer_cannot_declare_default
    """
    set_clock("2025-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Peer B", ssn_last4="0032")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    set_clock("2026-03-10T00:00:00Z")
    res = api.declare_default(loan["id"], LS)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


# ─── complexity_layers / consistency_model ───────────────

def test_occ_correct_version_plan_create_succeeds(api):
    """A plan create with the loan's CURRENT version succeeds and the new plan
    is PENDING (positive OCC path).

    PRD §3.5: "A successful creation places the plan in PENDING, increments
    Loan.version by one, and computes the plan's monthly_payment_cents
    immediately so that the figure is visible from the moment of creation."

    Design: Corner/complexity_layers/occ_correct_version_succeeds
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Occ B", ssn_last4="0033",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="STANDARD", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "PENDING"


def test_payment_apply_balance_visible_immediately(api):
    """POST /payments/{id}/apply response immediately reflects the post-apply
    balances and a subsequent GET /loans/{id} shows the updated balance.

    PRD §3.6: "On application, the engine allocates amount_cents by a strict
    waterfall: cents are applied first to accrued_interest_cents until that
    bucket is exhausted, then to principal_balance_cents. The actual splits
    are recorded as interest_applied_cents and principal_applied_cents;
    allocation is capped so that neither bucket can become negative."

    Design: Corner/consistency_model/immediate_consistency_payment_apply_balance_visible_in_response
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Imm B", ssn_last4="0034",
        loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
        interest_rate_bps=500,
    )
    pay = post_payment(
        loan["id"], borrower["id"],
        amount_cents=50_000, payment_date="2026-06-01T00:00:00Z",
    )
    applied = validate_success(api.apply_payment(pay["id"], LS), 200)
    assert applied["status"] == "APPLIED"
    # accrued_interest is 0 (loan was just placed in REPAYMENT at clock
    # 2026-06-01); the full 50000 routes to principal.
    assert applied["principal_applied_cents"] == 50_000

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["principal_balance_cents"] == 950_000
