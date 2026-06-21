"""Resource creation, field validation, payment fiscal rules, term-close
constraints, listing, and role-based access control.

Corner queue: entities, validations, endpoints, errors, rbac sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    fixtures,
    factories,
    ApiErrorId,
    TEST_USERS,
    make_student_headers,
    NON_EXISTENT_UUID,
    assert_institution,
    assert_student,
)

REGISTRAR = TEST_USERS["registrar_headers"]
BURSAR = TEST_USERS["bursar_headers"]
ANON = {}


# ===========================================================================
# Corner: entities / creation + defaults + computed + system fields
# ===========================================================================
def test_create_institution_returns_201_with_default_policy_and_version(api):
    """PRD 2.4: "a `refund_policy` that selects which withdrawal-proration
    variant the institution uses — either `DATE_BASED` (the default) or
    `SCHEDULE_BASED`."
    PRD 2.5: "a `version`, an integer that begins at its initial value and
    increments by one on every mutation"

    Design: Corner/entities/create_institution_returns_201_with_fields
    """
    resp = api.create_institution(
        factories.create_institution_payload(name="Inst Corner", currency="USD"), REGISTRAR
    )
    data = validate_success(resp, expected_status=201)
    assert_institution(data)
    assert data["refund_policy"] == "DATE_BASED", data
    assert data["version"] == 1, data


def test_get_missing_enrollment_returns_not_found(api):
    """PRD 2.4: "A reference to a resource that does not exist within the
    institution always yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_enrollment_not_found_returns_404
    """
    fixtures.create_institution()
    resp = api.get_enrollment(NON_EXISTENT_UUID, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_term_missing_required_field_rejected(api):
    """PRD 3.1: "An `AcademicTerm` belongs to an institution and is created with
    an `institution_id`, a `code` ... and four dates: `term_start` ...,
    `term_end` ..., `enroll_open`, and `enroll_close`."
    PRD 3.10: "request-body well-formedness is checked on create endpoints ...
    yielding `ERR_INVALID_REQUEST`"

    Omitting the required enroll_close is rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_term_missing_required_field_returns_invalid_request
    """
    inst = fixtures.create_institution()
    payload = factories.create_term_payload(inst["id"])
    del payload["enroll_close"]
    resp = api.create_term(payload, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_enrollment_defaults_autopay_false(api):
    """PRD 3.2: "an optional `autopay_enabled` flag (defaulting to false)
    declaring whether installments are to be auto-charged on their due dates."

    Design: Corner/entities/create_enrollment_autopay_default_false
    """
    base = fixtures.setup_base()
    resp = api.create_enrollment(
        factories.create_enrollment_payload(
            base["student"]["id"], base["term"]["id"], base["template"]["id"]
        ),
        REGISTRAR,
    )
    data = validate_success(resp, expected_status=201)
    assert data["autopay_enabled"] is False, data


def test_pending_enrollment_computed_balances_zero(api):
    """PRD 2.9: "An enrollment derives `gross_charges_cents` as the sum of
    `amount_cents` over its charges in `POSTED` status ... and
    `net_after_aid_cents` as the greater of zero and `gross_charges_cents`
    minus `total_aid_cents`."

    A freshly created PENDING enrollment with no charges has gross_charges_cents
    0 and net_after_aid_cents 0.

    Design: Corner/entities/enrollment_computed_balances_zero_before_charges
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    assert enr["gross_charges_cents"] == 0, enr
    assert enr["net_after_aid_cents"] == 0, enr


def test_charge_amount_zero_rejected(api):
    """PRD 3.3: "an `amount_cents` that must be strictly greater than zero — a
    non-positive amount is rejected with `ERR_INVALID_AMOUNT`."

    Design: Corner/entities/charge_amount_zero_returns_invalid_amount
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    resp = api.create_charge(
        factories.create_charge_payload(enr["id"], kind="TUITION", amount_cents=0), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_plan_template_pct_out_of_range_rejected(api):
    """PRD 3.1: "a `down_payment_pct` — the fraction of net-after-aid collected
    up front, which must be at least 0 and at most 0.5" ... "or
    `down_payment_pct` falls outside zero through one-half, the template is
    rejected with `ERR_INVALID_PLAN_TEMPLATE`."

    Design: Corner/entities/plan_template_pct_out_of_range_rejected
    """
    inst = fixtures.create_institution()
    resp = api.create_plan_template(
        factories.create_plan_template_payload(
            inst["id"], name="BAD", down_payment_pct=0.75
        ),
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_TEMPLATE.value)


def test_term_window_malformed_rejected(api):
    """PRD 3.1: "if `term_end` precedes `term_start` so that this length would
    be below 1, or more generally if the windows are malformed, creation is
    rejected with `ERR_INVALID_TERM_WINDOW`."

    Design: Corner/entities/term_window_malformed_rejected
    """
    inst = fixtures.create_institution()
    resp = api.create_term(
        factories.create_term_payload(
            inst["id"],
            code="BADTERM",
            term_start="2026-12-31T00:00:00.000Z",
            term_end="2026-09-01T00:00:00.000Z",
        ),
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_WINDOW.value)


def test_create_student_mints_system_fields(api):
    """PRD 3.2: "Each student also carries a computed `has_active_hold` flag,
    false at creation"
    PRD 2.5: "a `version`, an integer that begins at its initial value and
    increments by one on every mutation"

    Design: Corner/entities/system_fields_generated_not_client_set
    """
    inst = fixtures.create_institution()
    resp = api.create_student(factories.create_student_payload(inst["id"]), REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert_student(data)
    assert data["has_active_hold"] is False, data
    assert data["version"] == 1, data


def test_list_students_returns_paginated_envelope(api):
    """PRD 2.3: "Each list response includes the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope."

    Design: Corner/entities/list_students_paginated_envelope
    """
    inst = fixtures.create_institution()
    fixtures.create_student(inst["id"])
    resp = api.list_students(REGISTRAR, params={"institution_id": inst["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta


# ===========================================================================
# Corner: validations
# ===========================================================================
def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "Every request to the API must carry two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    operational capacity in which they act. If either header is missing or
    malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    inst = fixtures.create_institution()
    resp = api.get_institution(inst["id"], ANON)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_close_term_with_open_balances_rejected(api):
    """PRD 3.1: "closing ... additionally requires that no enrollment on the
    term is in `PENDING` or `ACTIVE` status while still carrying a positive
    `scheduled_balance_cents` — if any serviced enrollment retains an open
    scheduled balance, the close is rejected with `ERR_TERM_HAS_OPEN_BALANCES`."

    Design: Corner/validations/term_close_with_open_balances_rejected
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr = base["enrollment"]
    assert enr["scheduled_balance_cents"] == 320000, enr
    fixtures.get_success_data(api.lock_term(base["term"]["id"], REGISTRAR))

    resp = api.close_term(base["term"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_TERM_HAS_OPEN_BALANCES.value)


def test_settle_down_payment_twice_rejected(api):
    """PRD 3.6: "When the purpose is `DOWN_PAYMENT`, settling requires that the
    down payment has not already been collected; a second down-payment
    settlement is rejected with `ERR_DOWN_PAYMENT_ALREADY_PAID`."

    Design: Corner/validations/settle_down_payment_twice_returns_already_paid
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    # A second PENDING down payment, then attempt to settle it.
    pay2 = fixtures.get_success_data(
        api.create_payment(
            factories.create_payment_payload(enr_id, "DOWN_PAYMENT", 80000), BURSAR
        )
    )
    resp = api.settle_payment(pay2["id"], BURSAR)
    validate_error(resp, ApiErrorId.ERR_DOWN_PAYMENT_ALREADY_PAID.value)


# ===========================================================================
# Corner: errors / installment not payable after paid
# ===========================================================================
def test_settle_installment_after_paid_rejected(api):
    """PRD 3.6: "When the purpose is `INSTALLMENT` or `AUTOPAY`, settling
    requires the targeted installment to be in `SCHEDULED` or `OVERDUE` status;
    settling against an installment in any other status is rejected with
    `ERR_INSTALLMENT_NOT_PAYABLE`."

    Design: Corner/errors/settle_installment_not_payable_after_paid
    """
    # Two installments so that paying the first to PAID leaves a second SCHEDULED
    # installment open: the enrollment stays ACTIVE (not every installment is
    # PAID, so the PRD 3.6 completion bubble does not fire), and the re-settle
    # attempt against the now-PAID installment reaches the installment-payability
    # check rather than the earlier enrollment-ACTIVE guard.
    base = fixtures.setup_base(installment_count=2, down_payment_pct=0, plan_fee_cents=0)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 120000)
    fixtures.activate(enr["id"])
    inst = fixtures.list_installments(enr["id"])[0]
    fixtures.settle_installment(enr["id"], inst["id"], inst["amount_cents"])  # installment now PAID

    pay2 = fixtures.get_success_data(
        api.create_payment(
            factories.create_payment_payload(
                enr["id"], "INSTALLMENT", inst["amount_cents"], installment_id=inst["id"]
            ),
            BURSAR,
        )
    )
    resp = api.settle_payment(pay2["id"], BURSAR)
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value)


# ===========================================================================
# Corner: endpoints / list installments reverse-reachability
# ===========================================================================
def test_list_installments_by_enrollment(api):
    """PRD 3.4: "It then runs the **installment schedule** calculation to
    compute the down payment and the financed split and to lay down the
    installment rows"

    Activating a 4PAY enrollment lays down 4 installments, returned by the list
    endpoint as an array.

    Design: Corner/endpoints/list_installments_by_enrollment_reverse_reachability
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    resp = api.list_installments(BURSAR, params={"enrollment_id": enr_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 4, meta


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_bursar_cannot_create_charge(api):
    """PRD 2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."
    PRD 3.3: "A `Registrar` posts a `Charge` against an enrollment"

    Charge creation is Registrar-only; a Bursar attempt is rejected
    ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/bursar_cannot_create_charge
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    resp = api.create_charge(
        factories.create_charge_payload(enr["id"], kind="TUITION", amount_cents=500000), BURSAR
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_student_cannot_settle_payment(api):
    """PRD 2.1: "Creating and settling payments is shared: a payment may be
    created by either a `Bursar` or a `Student`, while settling and failing a
    payment are reserved for the `Bursar`."

    A Student creates a down payment (allowed) but cannot settle it ->
    ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/student_cannot_settle_payment
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    student_id = base["student"]["id"]
    student_headers = make_student_headers(student_id)

    pay = fixtures.get_success_data(
        api.create_payment(
            factories.create_payment_payload(enr_id, "DOWN_PAYMENT", 80000), student_headers
        )
    )
    resp = api.settle_payment(pay["id"], student_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
