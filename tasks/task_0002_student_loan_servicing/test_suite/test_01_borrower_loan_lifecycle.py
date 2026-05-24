"""Borrower CRUD, Loan origination, and Loan state-machine basics.

Covers corner-design entity/state-machine claims plus the non-linear-state
difficulty claim for the cyclic FORBEARANCE/REPAYMENT loop.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_borrower, assert_loan,
    create_borrower_payload, create_loan_payload,
    create_servicing_event_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    advance_clock, create_borrower, create_loan,
    fire_servicing_event, get_loan,
    setup_loan_in_repayment_with_standard_plan,
    setup_loan_paid_off,
)


# ─── Borrower CRUD ────────────────────────────────────


def test_create_borrower_minimum_required_fields_returns_201(api, servicer_headers):
    """PRD §3.1: "An optional `military_status` may be supplied at creation;
    if omitted, the field defaults to `NONE` and may later be amended via the
    dedicated military-status update endpoint (typically when a borrower
    presents discharge papers)."
    PRD §3.1: "On creation, the new borrower carries
    `aggregate_outstanding_principal_cents` of zero and a `borrower_status`
    of `CURRENT` (no loans yet)."

    Design: Corner/entities/create_borrower_minimum_required_fields_returns_201
    """
    advance_clock("2026-06-01T00:00:00Z")
    payload = {
        "ssn_last4": "9999",
        "full_name": "Mini Test",
        "date_of_birth": "1992-05-05",
        "email": "mini-min@example.com",
    }
    res = api.create_borrower(payload, servicer_headers)
    borrower = validate_success(res, 201)
    assert_borrower(borrower)
    assert borrower["full_name"] == "Mini Test"
    assert borrower["ssn_last4"] == "9999"
    assert borrower["military_status"] == "NONE"
    assert borrower["borrower_status"] == "CURRENT"
    assert borrower["aggregate_outstanding_principal_cents"] == 0


def test_get_borrower_not_found_returns_404(api, servicer_headers):
    """PRD §2.9: "Existence of every entity referenced by the URL path or
    request body is then verified, with `ERR_NOT_FOUND`, and path identifiers
    are validated left-to-right (a non-existent `borrower_id` in the path is
    reported before a non-existent `loan_id` further down, and parent path
    identifiers are checked before any body reference)."

    Design: Corner/entities/get_borrower_not_found_returns_404
    """
    advance_clock("2026-06-01T00:00:00Z")
    res = api.get_borrower(NON_EXISTENT_UUID, servicer_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_borrowers_paginated_returns_total_count_and_has_more(api, servicer_headers):
    """PRD §2.3: "For endpoints that return lists of resources, pagination is
    controlled via two query parameters. The `limit` parameter specifies the
    maximum number of items to return; if not provided, it defaults to 10,
    with a minimum of 1 and a maximum of 100. The `offset` parameter
    specifies the number of items to skip and defaults to 0."
    PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` envelope."

    Design: Corner/entities/list_borrowers_paginated_returns_total_count_and_has_more
    """
    advance_clock("2026-06-01T00:00:00Z")
    for i in range(3):
        create_borrower(email=f"list-paged-{i}@example.com", full_name=f"B{i}")

    data, meta = validate_paginated(
        api.list_borrowers(servicer_headers, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_missing_required_field_email_returns_invalid_request(api, servicer_headers):
    """PRD §3.1: "The submission carries `ssn_last4` (exactly four numeric
    digits, the last four of the social security number used for matching
    rather than the full SSN), `full_name` as it appears on the legal record,
    `date_of_birth` in ISO 8601 YYYY-MM-DD form, and a contact `email`."
    PRD §2.9: "A malformed body that does not match any more specific rule
    falls back to `ERR_INVALID_REQUEST`."

    Design: Corner/entities/missing_required_field_email_returns_invalid_request
    """
    advance_clock("2026-06-01T00:00:00Z")
    res = api.create_borrower(
        {"ssn_last4": "1234", "full_name": "NoEmail", "date_of_birth": "1990-01-01"},
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_borrower_email_uniqueness_collision_returns_409(api, servicer_headers):
    """PRD §3.1: "The `email` is unique across all borrowers, evaluated
    case-insensitively; an attempt to reuse an existing email is rejected
    with `ERR_EMAIL_DUPLICATE`."

    Design: Corner/entities/borrower_email_uniqueness_collision_returns_409
    """
    advance_clock("2026-06-01T00:00:00Z")
    validate_success(api.create_borrower(create_borrower_payload(
        email="Dup-coll@example.com", full_name="First",
    ), servicer_headers), 201)
    res = api.create_borrower(create_borrower_payload(
        email="dup-coll@example.com", full_name="Second",
    ), servicer_headers)
    validate_error(res, "ERR_EMAIL_DUPLICATE", expected_status=409)


# ─── Loan origination ────────────────────────────────


def test_loan_initial_state_is_in_school(api, servicer_headers):
    """PRD §3.1: "The loan is born with `status` of `IN_SCHOOL`, with
    `outstanding_principal_cents` initialized to `original_principal_cents`,
    with `accrued_interest_cents` and `capitalized_interest_cents` both at
    zero, and with `days_delinquent` at zero."

    Design: Corner/state_machines/loan_initial_state_is_in_school
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="init-school@example.com")
    res = api.create_loan(
        create_loan_payload(
            borrower["id"],
            loan_type="DIRECT_SUBSIDIZED",
            original_principal_cents=100_000,
            interest_rate_bps=533,
            disbursement_date="2026-06-01",
        ),
        servicer_headers,
    )
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["status"] == "IN_SCHOOL"
    # First version after creation must be a positive integer; PRD §2.4
    # leaves the seed value implicit but every "version" field is "a
    # non-negative integer that begins at the row's initial value and
    # increments by one on every mutation".


def test_loan_invalid_loan_type_enum_returns_invalid_request(api, servicer_headers):
    """PRD §3.1: "Once a borrower exists, a `LoanServicer` originates a `Loan`
    by referencing the `borrower_id`, declaring the `loan_type` as one of
    `DIRECT_SUBSIDIZED`, `DIRECT_UNSUBSIDIZED`, or `DIRECT_PLUS`, supplying
    the `original_principal_cents` actually disbursed..."
    PRD §2.9: "A malformed body that does not match any more specific rule
    falls back to `ERR_INVALID_REQUEST`."

    Design: Corner/entities/loan_invalid_loan_type_enum_returns_invalid_request
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="invalid-type@example.com")
    res = api.create_loan(
        {
            "borrower_id": borrower["id"],
            "loan_type": "DIRECT_OTHER",
            "original_principal_cents": 100_000,
            "interest_rate_bps": 500,
            "disbursement_date": "2026-06-01",
        },
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_foreign_key_borrower_nonexistent_on_loan_create_returns_not_found(
    api, servicer_headers,
):
    """PRD §2.9: "Existence of every entity referenced by the URL path or
    request body is then verified, with `ERR_NOT_FOUND`, and path identifiers
    are validated left-to-right (a non-existent `borrower_id` in the path is
    reported before a non-existent `loan_id` further down, and parent path
    identifiers are checked before any body reference)."

    Design: Corner/entities/foreign_key_borrower_nonexistent_on_loan_create_returns_not_found
    """
    advance_clock("2026-06-01T00:00:00Z")
    res = api.create_loan(
        {
            "borrower_id": NON_EXISTENT_UUID,
            "loan_type": "DIRECT_UNSUBSIDIZED",
            "original_principal_cents": 100_000,
            "interest_rate_bps": 0,
            "disbursement_date": "2026-06-01",
        },
        servicer_headers,
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_loan_computed_aggregate_outstanding_principal_correct(api, servicer_headers):
    """PRD §2.8: "The borrower's `aggregate_outstanding_principal_cents` is
    the sum of `outstanding_principal_cents` across all non-terminal loans.
    Both fields recompute whenever any of the borrower's loans transitions or
    their balances change."

    Design: Corner/entities/loan_computed_aggregate_outstanding_principal_correct
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="agg-principal@example.com")
    create_loan(borrower["id"], original_principal_cents=100_000, interest_rate_bps=0)
    create_loan(borrower["id"], original_principal_cents=250_000, interest_rate_bps=0)
    res = api.get_borrower(borrower["id"], servicer_headers)
    fetched = validate_success(res, 200)
    assert fetched["aggregate_outstanding_principal_cents"] == 350_000


# ─── Loan state transitions ──────────────────────────


def test_loan_terminal_state_paid_off_lockdown(api, servicer_headers):
    """PRD §3.2: "When a discharge approval cascades into the loan, the loan's
    `status` advances directly to `DISCHARGED` from whichever non-terminal
    state it occupied; the loan's `outstanding_principal_cents` and
    `accrued_interest_cents` are left as historical record (no further
    accrual occurs), any open `DelinquencyRecord` closes with `outcome` of
    `CURED`, and any `ACTIVE` `RepaymentPlan` on the loan transitions to
    `EXPIRED`."
    PRD §3.2: "Forbearance follows a parallel structure: `FORBEARANCE_BEGIN`
    is accepted from either `REPAYMENT` or `DELINQUENT` with reason among
    `ECONOMIC_HARDSHIP`, `NATURAL_DISASTER`, `ADMIN_FORBEARANCE`, or
    `MEDICAL`."

    A FORBEARANCE_BEGIN on a PAID_OFF loan therefore fails the §3.2
    precondition; per §2.9 the rejection is ERR_INVALID_STATE.

    Design: Corner/state_machines/loan_terminal_state_paid_off_lockdown
    """
    _, paid_off = setup_loan_paid_off(
        clock_set_to="2026-06-01T00:00:00Z",
        disbursement_date="2025-12-01",
        grace_begin_on="2025-12-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        payment_posted_on="2026-06-01",
    )
    assert paid_off["status"] == "PAID_OFF"
    res = api.create_servicing_event(
        paid_off["id"],
        create_servicing_event_payload(
            "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_forbearance_end_from_repayment_invalid(api, servicer_headers):
    """PRD §3.2: "`FORBEARANCE_END`, requiring the loan to be in `FORBEARANCE`,
    returns the loan to `REPAYMENT` and triggers a capitalization of the
    full `accrued_interest_cents`."

    Design: Corner/state_machines/forbearance_end_from_repayment_invalid
    """
    _, loan, _ = setup_loan_in_repayment_with_standard_plan()
    res = api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload("FORBEARANCE_END", "2026-06-01", "OTHER"),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_deferment_end_from_repayment_invalid(api, servicer_headers):
    """PRD §3.2: "A `DEFERMENT_END` event, requiring the loan to be in
    `DEFERMENT`, returns the loan to `REPAYMENT` and triggers a
    capitalization that capitalizes only the unsubsidized portion of
    `accrued_interest_cents` (for Direct Subsidized loans this is zero
    because `subsidy_active` held throughout the deferment window; for
    non-subsidized loans the entire accrued interest capitalizes)."

    Design: Corner/state_machines/deferment_end_from_repayment_invalid
    """
    _, loan, _ = setup_loan_in_repayment_with_standard_plan()
    res = api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload("DEFERMENT_END", "2026-06-01", "OTHER"),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_grace_begin_from_repayment_invalid(api, servicer_headers):
    """PRD §3.2: "The transition from `IN_SCHOOL` to `GRACE` fires on a
    `GRACE_BEGIN` event when the loan is currently in `IN_SCHOOL` and the
    supplied `effective_on` is on or after the loan's `disbursement_date`;
    on success the loan's `status` advances to `GRACE` and `subsidy_active`
    recomputes (still true for a Direct Subsidized loan)."

    Design: Corner/state_machines/grace_begin_from_repayment_invalid
    """
    _, loan, _ = setup_loan_in_repayment_with_standard_plan()
    res = api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload("GRACE_BEGIN", "2026-06-01", "OTHER"),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Cyclic state machine (Difficulty Rule 3) ────────


def test_loan_cyclic_forbearance_repayment_repeats(api, servicer_headers):
    """PRD §3.2: "Forbearance follows a parallel structure: `FORBEARANCE_BEGIN`
    is accepted from either `REPAYMENT` or `DELINQUENT` with reason among
    `ECONOMIC_HARDSHIP`, `NATURAL_DISASTER`, `ADMIN_FORBEARANCE`, or
    `MEDICAL`."
    PRD §3.2: "`FORBEARANCE_END`, requiring the loan to be in `FORBEARANCE`,
    returns the loan to `REPAYMENT` and triggers a capitalization of the
    full `accrued_interest_cents`."

    After REPAYMENT→FORBEARANCE→REPAYMENT→FORBEARANCE→REPAYMENT the loan
    is still in REPAYMENT — the state machine cycles legally.

    Design: Difficulty/non_linear_state_machine/loan_cyclic_repayment_forbearance_repayment
    """
    _, loan, _ = setup_loan_in_repayment_with_standard_plan()
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-06-01", "OTHER")
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-06-01", "OTHER")
    after = get_loan(loan["id"])
    assert after["status"] == "REPAYMENT", (
        f"Expected REPAYMENT after the second FORBEARANCE_END, got {after['status']}"
    )


def test_loan_cyclic_forbearance_repayment_each_end_capitalizes(api, servicer_headers):
    """PRD §3.2: "`FORBEARANCE_END`, requiring the loan to be in `FORBEARANCE`,
    returns the loan to `REPAYMENT` and triggers a capitalization of the
    full `accrued_interest_cents`."
    PRD §2.7: "When a capitalization fires, the system follows a pinned
    three-step order: first, the capitalizable amount is added to
    `outstanding_principal_cents` and to the cumulative
    `capitalized_interest_cents` on the loan; next, `accrued_interest_cents`
    is set to zero; finally, the loan's `version` is incremented by one."

    A loan that enters and exits FORBEARANCE twice records two capitalization
    cycles; both leave accrued_interest_cents at zero.

    Design: Difficulty/non_linear_state_machine/loan_cyclic_repayment_forbearance_repayment
    """
    _, loan, _ = setup_loan_in_repayment_with_standard_plan()
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-06-01", "OTHER")
    after_first_cycle = get_loan(loan["id"])
    assert after_first_cycle["accrued_interest_cents"] == 0
    assert after_first_cycle["status"] == "REPAYMENT"

    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-06-01", "OTHER")
    after_second_cycle = get_loan(loan["id"])
    assert after_second_cycle["accrued_interest_cents"] == 0
    assert after_second_cycle["status"] == "REPAYMENT"


# ─── ServicingEvent list shape ───────────────────────


def test_servicing_event_immutable_event_record_listing(api, servicer_headers):
    """PRD §2.4: "A `ServicingEvent`, once logged, captures a point-in-time
    transition (its `event_type`, `effective_on`, `reason_code`, `loan_id`,
    and `created_by_user_id`) and is never edited; it therefore carries only
    `id` and `created_at`, and exposes neither `updated_at` nor `version`."
    PRD §3.2: "Each event is stamped with `created_by_user_id` from the
    acting servicer's `X-User-ID`."

    Design: Corner/entities/servicing_event_immutable_no_update_endpoint
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="immutable-event@example.com")
    loan = create_loan(
        borrower["id"],
        original_principal_cents=100_000, interest_rate_bps=0,
        disbursement_date="2026-06-01",
    )
    fire_servicing_event(loan["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")

    data, _ = validate_paginated(api.list_servicing_events(loan["id"], servicer_headers))
    assert len(data) >= 1
    grace = next((e for e in data if e["event_type"] == "GRACE_BEGIN"), None)
    assert grace is not None, "GRACE_BEGIN event missing from list"
    assert grace["created_by_user_id"] == "svc-test-1", (
        "ServicingEvent.created_by_user_id should be the acting servicer's X-User-ID"
    )
    # Append-only event records expose neither updated_at nor version.
    assert "updated_at" not in grace, (
        "ServicingEvent must not expose updated_at (event record, not mutable resource)"
    )
    assert "version" not in grace, (
        "ServicingEvent must not expose version (event record, not mutable resource)"
    )
