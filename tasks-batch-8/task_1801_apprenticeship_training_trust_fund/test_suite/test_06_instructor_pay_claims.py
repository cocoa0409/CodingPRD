"""Instructor pay claims: scheduled vs actual pay bases, overtime cap,
ownership, duplicate claims, committee review, disbursement (PRD §3.5)."""
from test_helpers import (
    ADMIN,
    CM1,
    ApiErrorId,
    assert_pay_claim,
    approve_claim,
    create_fund,
    create_pay_claim,
    create_pay_claim_payload,
    get_fund,
    get_pay_claim,
    make_instructor_headers,
    setup_approved_claim,
    setup_completed_class,
    validate_error,
    validate_success,
)


def test_scheduled_basis_pays_published_window(api):
    """PRD §3.5: "A `SCHEDULED`-basis claim pays the published window
    regardless of time actually taught: the class's
    `instructor_rate_cents_per_hour` multiplied by the window length, divided
    by sixty, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/dual_variant_instructor_pay_scheduled_vs_actual
    """
    fund = create_fund()
    klass = setup_completed_class(
        fund_id=fund["id"], instructor_user_id="inst-1", rate=6000,
        start_minute=600, end_minute=720,
    )
    resp = api.create_pay_claim(
        create_pay_claim_payload(klass["id"], "SCHEDULED"),
        make_instructor_headers("inst-1"),
    )
    claim = validate_success(resp, 201)
    assert_pay_claim(claim)
    assert claim["status"] == "SUBMITTED"
    assert claim["instructor_user_id"] == "inst-1"
    assert claim["payable_cents"] == 12000, "6000c/h x 120 min / 60"


def test_actual_basis_at_overtime_cap_pays_declared_minutes(api):
    """PRD §3.5: "An `ACTUAL`-basis claim substitutes the declared
    `actual_minutes` for the window length in the same computation, diverging
    from the scheduled figure whenever the declared minutes differ."
    PRD §3.5: "The declared minutes are capped at the window length multiplied
    by one and a quarter, rounded half-up to a whole minute; a claim whose
    `actual_minutes` exceeds that cap is rejected with
    `ERR_OVERTIME_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/dual_variant_instructor_pay_scheduled_vs_actual
    """
    fund = create_fund()
    klass = setup_completed_class(
        fund_id=fund["id"], instructor_user_id="inst-1", rate=6000,
        start_minute=800, end_minute=920, facility="SHOP-B",
        course_code="CN-102",
    )
    resp = api.create_pay_claim(
        create_pay_claim_payload(klass["id"], "ACTUAL", actual_minutes=150),
        make_instructor_headers("inst-1"),
    )
    claim = validate_success(resp, 201)
    assert claim["payable_cents"] == 15000, (
        "6000c/h x 150 min / 60; 150 is exactly the cap on the 120-minute "
        "window (round_half_up(120 x 1.25)), and the cap rejects only "
        "minutes that exceed it"
    )


def test_actual_minutes_over_cap_rejected(api):
    """PRD §3.5: "The declared minutes are capped at the window length
    multiplied by one and a quarter, rounded half-up to a whole minute; a
    claim whose `actual_minutes` exceeds that cap is rejected with
    `ERR_OVERTIME_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/error_overtime_cap_exceeded
    """
    fund = create_fund()
    klass = setup_completed_class(
        fund_id=fund["id"], instructor_user_id="inst-1",
        start_minute=600, end_minute=720,
    )
    resp = api.create_pay_claim(
        create_pay_claim_payload(klass["id"], "ACTUAL", actual_minutes=151),
        make_instructor_headers("inst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_OVERTIME_CAP_EXCEEDED)


def test_claim_wrong_instructor_and_duplicate_rejected(api):
    """PRD §3.5: "The caller's `X-User-ID` must equal the class's
    `instructor_user_id`, else `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.5: "At most one open claim — one in `SUBMITTED` or `APPROVED` — may
    exist per class; a second open claim is rejected with
    `ERR_DUPLICATE_CLAIM`."

    Design: Corner/errors/error_duplicate_claim_and_pay_claim_create_by_wrong_instructor_rejected
    """
    fund = create_fund()
    klass = setup_completed_class(
        fund_id=fund["id"], instructor_user_id="inst-1",
        start_minute=600, end_minute=720,
    )
    resp = api.create_pay_claim(
        create_pay_claim_payload(klass["id"], "SCHEDULED"),
        make_instructor_headers("inst-2"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    claim = create_pay_claim(klass, pay_basis="SCHEDULED")
    assert claim["status"] == "SUBMITTED"

    resp = api.create_pay_claim(
        create_pay_claim_payload(klass["id"], "ACTUAL", actual_minutes=100),
        make_instructor_headers("inst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


def test_pay_rejected_or_paid_claim_rejected(api):
    """PRD §3.5: "A `TrustAdmin` pays an `APPROVED` claim; any other source
    status is rejected with `ERR_CLAIM_NOT_PAYABLE`."

    Design: Corner/state_machines/pay_claim_terminal_lockdown
    """
    fund = create_fund()
    klass1 = setup_completed_class(
        fund_id=fund["id"], course_code="CN-101",
        instructor_user_id="inst-1", facility="SHOP-A",
        start_minute=600, end_minute=720,
    )
    claim1 = create_pay_claim(klass1, pay_basis="SCHEDULED")
    validate_success(api.reject_pay_claim(claim1["id"], CM1), 200)

    klass2 = setup_completed_class(
        fund_id=fund["id"], course_code="CN-102",
        instructor_user_id="inst-1", facility="SHOP-B",
        start_minute=800, end_minute=920,
    )
    claim2 = create_pay_claim(klass2, pay_basis="SCHEDULED")
    approve_claim(claim2["id"])
    validate_success(api.pay_claim(claim2["id"], ADMIN), 200)

    resp1 = api.pay_claim(claim1["id"], ADMIN)
    validate_error(resp1, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
    resp2 = api.pay_claim(claim2["id"], ADMIN)
    validate_error(resp2, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
    assert get_pay_claim(claim1["id"])["status"] == "REJECTED"
    assert get_pay_claim(claim2["id"])["status"] == "PAID"


def test_approve_paid_claim_rejected(api):
    """PRD §3.5: "Approval sets the claim `APPROVED` and stamps
    `approved_by_user_id` with the approver's identity; rejection sets it
    `REJECTED`. Either action attempted on a claim not in `SUBMITTED` is
    rejected with `ERR_CLAIM_NOT_APPROVABLE`."

    Design: Corner/errors/error_claim_not_approvable_on_paid
    """
    _fund, claim = setup_approved_claim()
    validate_success(api.pay_claim(claim["id"], ADMIN), 200)

    resp = api.approve_pay_claim(claim["id"], CM1)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_APPROVABLE)
    assert get_pay_claim(claim["id"])["status"] == "PAID"


def test_pay_claim_disburses_fund(api):
    """PRD §3.5: "Payment adds the claim's `payable_cents` to the fund's
    `disbursed_cents`, recomputes `available_cents`, advances the fund's
    `version` by one, stamps `paid_at` (null until this moment), and moves the
    claim to `PAID`, its terminal state alongside `REJECTED`."

    Design: Corner/endpoints/pay_claim_pay_disburses_fund
    """
    fund, claim = setup_approved_claim()
    assert claim["payable_cents"] == 12000
    assert claim["approved_by_user_id"] is not None
    assert claim["paid_at"] is None

    resp = api.pay_claim(claim["id"], ADMIN)
    paid = validate_success(resp, 200)
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None

    fund_after = get_fund(fund["id"])
    assert fund_after["disbursed_cents"] == 12000
