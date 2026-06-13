"""Validation rules and error catalogue: payment, plan, school, contest, collections."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_enrollment_payload,
    create_installment_plan_payload,
    create_contest_request_payload,
    create_schedule_payload,
    make_driver_headers,
)
from test_helpers.fixtures import (
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    file_contest,
    pay_citation_in_full,
    set_clock,
    CLERK,
)


def test_overpayment_returns_error(api):
    """PRD §3.4: "The tendered `amount_cents` must be positive and must not exceed
    the current `balance_cents`; a non-positive amount or an amount above the
    balance is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/overpayment_returns_error
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    assert cit["balance_cents"] == 29000
    res = api.create_payment(
        cit["id"], create_payment_payload(30000, method="CARD"),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_OVERPAYMENT")
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert citation["amount_paid_cents"] == 0
    assert citation["balance_cents"] == 29000


def test_installment_too_small_returns_error(api):
    """PRD §3.5: "If the computed base falls below the jurisdiction's
    `min_installment_cents`, or the requested `term_count` is outside the 2-to-12
    range, the plan is rejected with `ERR_INSTALLMENT_TOO_SMALL`."

    Design: Corner/validations/installment_too_small_returns_error
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    # base 4167 -> assessed_total = 4167 + 5000 + round_half_up(4167*0.20=833.4)=833 = 10000
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC22500", description="Parking",
            base_fine_cents=4167, points=0,
        ),
        CLERK,
    )
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    assert assessed["balance_cents"] == 10000
    # term 12 -> base (10000+2500)/12 = floor(1041.6) = 1041 < min 2000
    res = api.create_installment_plan(
        cit["id"],
        create_installment_plan_payload(12, assessed["version"]),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_INSTALLMENT_TOO_SMALL")


def test_school_ineligible_points_exceed_cap(api):
    """PRD §3.9: "The total demerit points across the citation's charges must not
    exceed the jurisdiction's `school_eligible_max_points` ... A request that fails
    any of these is rejected with `ERR_SCHOOL_INELIGIBLE`."

    Design: Corner/validations/school_ineligible_points_exceed_cap
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()  # school_eligible_max_points 1
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    # Single 2-point charge -> exceeds cap of 1.
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC23103", description="Reckless",
            base_fine_cents=10000, points=2,
        ),
        CLERK,
    )
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    pay_citation_in_full(assessed, driver["id"])
    res = api.create_enrollment(
        cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_SCHOOL_INELIGIBLE")


def test_school_completion_after_deadline_returns_error(api):
    """PRD §3.9: "A clerk marks the course **completed**, moving the enrollment from
    `ENROLLED` to `COMPLETED`, but only when the server clock has not yet passed the
    `completion_due_at` — a late completion is rejected with
    `ERR_SCHOOL_DEADLINE_PASSED` — and only when the citation's `financial_status`
    is already `PAID`, since the fine must be settled first; an unpaid fine is
    rejected with `ERR_FINE_UNPAID`."

    Design: Corner/validations/school_completion_after_deadline_returns_error
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    pay_citation_in_full(cit, driver["id"])
    enrollment = validate_success(
        api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-03-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    set_clock("2026-03-02T00:00:00Z")  # past completion_due_at
    res = api.complete_enrollment(enrollment["id"], CLERK)
    validate_error(res, "ERR_SCHOOL_DEADLINE_PASSED")


def test_void_with_posted_payment_returns_has_payments(api):
    """PRD §3.10: "A `CourtClerk` may **void** a citation that is still `DRAFT` or
    `ASSESSED`, provided no posted payment exists against it — a void with payments
    present is rejected with `ERR_HAS_PAYMENTS`."

    Design: Corner/validations/void_with_posted_payment_returns_has_payments
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(10000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    res = api.void_citation(cit["id"], CLERK)
    validate_error(res, "ERR_HAS_PAYMENTS")
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert citation["financial_status"] == "PARTIALLY_PAID"


def test_second_contest_returns_already_contested(api):
    """PRD §3.7: "A citation that is already `CONTESTED`, `DISMISSED`, or `UPHELD`
    cannot accept a second contest; the attempt is rejected with
    `ERR_ALREADY_CONTESTED`."

    Design: Corner/validations/second_contest_returns_already_contested
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    file_contest(cit["id"], driver["id"], grounds="first")
    res = api.create_contest_request(
        cit["id"], create_contest_request_payload(grounds="second"),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_ALREADY_CONTESTED")


def test_invalid_hearing_date_in_past_returns_error(api):
    """PRD §3.7: "recording the supplied `hearing_at`, which must be in the future
    relative to the server clock; a past or present hearing time is rejected with
    `ERR_INVALID_HEARING_DATE`."

    Design: Corner/validations/invalid_hearing_date_in_past_returns_error
    """
    set_clock("2026-02-01T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-03-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    contest = file_contest(cit["id"], driver["id"])
    res = api.schedule_hearing(
        contest["id"], create_schedule_payload("2026-01-01T00:00:00Z"), CLERK
    )
    validate_error(res, "ERR_INVALID_HEARING_DATE")


def test_apply_late_penalty_before_appear_by_returns_not_yet_late(api):
    """PRD §3.6: "The server clock must have reached or passed the `appear_by`
    deadline — an attempt before that instant is rejected with `ERR_NOT_YET_LATE` —
    and the penalty must not already have been applied, guarded by the
    `late_penalty_applied` flag; a second attempt is rejected with
    `ERR_PENALTY_ALREADY_APPLIED`."

    Design: Corner/endpoints/apply_late_penalty_before_appear_by_returns_not_yet_late
    """
    set_clock("2026-01-20T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    res = api.apply_late_penalty(cit["id"], CLERK)  # clock before appear_by
    validate_error(res, "ERR_NOT_YET_LATE")
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert citation["penalty_cents"] == 0
    assert citation["late_penalty_applied"] is False


def test_mark_default_before_due_returns_not_yet_late(api):
    """PRD §3.6: "A clerk may mark an `ACTIVE` installment plan as **defaulted** once
    at least one of its installments is past its `due_at` while still `SCHEDULED`; if
    no installment is yet past due, the action is rejected with `ERR_NOT_YET_LATE`."

    Design: Corner/endpoints/mark_default_before_due_returns_not_yet_late
    """
    set_clock("2026-01-20T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    plan = validate_success(
        api.create_installment_plan(
            cit["id"],
            create_installment_plan_payload(4, cit["version"],
                                            first_due_at="2026-03-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    set_clock("2026-02-15T00:00:00Z")  # before any due date
    res = api.mark_default(plan["id"], CLERK)
    validate_error(res, "ERR_NOT_YET_LATE")
    after = validate_success(api.get_installment_plan(plan["id"], CLERK), 200)
    assert after["status"] == "ACTIVE"


def test_cancel_plan_with_payment_returns_has_payments(api):
    """PRD §3.5: "A driver or clerk may cancel an `ACTIVE` plan ... but only when no
    posted payment has been allocated to any of the plan's installments; a cancel
    attempted with such a payment present is rejected with `ERR_HAS_PAYMENTS`."

    Design: Corner/state_machines/cancel_plan_with_payment_returns_has_payments
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    plan = validate_success(
        api.create_installment_plan(
            cit["id"], create_installment_plan_payload(4, cit["version"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    installments = validate_success(
        api.list_installments(CLERK, params={"installment_plan_id": plan["id"]}), 200
    )
    rows = installments if isinstance(installments, list) else installments.get("items", [])
    inst1 = sorted(rows, key=lambda r: r["sequence_no"])[0]
    validate_success(
        api.create_payment(
            cit["id"],
            create_payment_payload(inst1["amount_cents"], method="CARD", installment_id=inst1["id"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    res = api.cancel_plan(plan["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_HAS_PAYMENTS")
    after = validate_success(api.get_installment_plan(plan["id"], CLERK), 200)
    assert after["status"] == "ACTIVE"


def test_collections_fee_uses_balance_at_referral(api):
    """PRD §3.10: "freezes `outstanding_at_referral_cents` as the citation's current
    `balance_cents`, and computes `collections_fee_cents` as that outstanding amount
    multiplied by the jurisdiction's `collections_fee_pct`, rounded half-up to a
    whole cent."

    Design: Corner/calculations/collections_fee_input_set_filter_on_balance
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    # Partial payment of 9000 -> balance 20000 before referral.
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(9000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    set_clock("2026-03-06T00:00:00Z")  # 30 days past appear_by
    referral = validate_success(api.create_collections_referral(cit["id"], CLERK), 201)
    assert referral["outstanding_at_referral_cents"] == 20000
    # round_half_up(20000 * 0.25) = 5000
    assert referral["collections_fee_cents"] == 5000
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert citation["balance_cents"] == 25000  # 20000 + 5000
