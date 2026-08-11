"""Flat charges, invoice aging, the delinquency posture and the agency billing freeze."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_string,
    assert_invoice,
    issue_invoice,
    make_applicant_headers,
    mark_no_show,
    new_appointment,
    new_applicant,
    only_fee_assessment,
    open_invoice,
    run_aging,
    set_clock,
    setup_agency_billed_no_show_invoice,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]


def _suspended_agency_with_a_cancelled_appointment():
    world = setup_registry(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "Delinquent DA", "payer_regime_default": "AGENCY_BILLED"},
    )
    applicant = new_applicant(full_name="Ivan Moss")
    world["applicant"] = applicant
    no_show_appointment = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-01T10:00:00Z"
    )
    cancelled = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-03T10:00:00Z"
    )
    validate_success_cancel(cancelled["id"], make_applicant_headers(applicant["id"]))
    mark_no_show(no_show_appointment["id"], "2026-06-01T10:20:00Z")

    world["invoice"] = issue_invoice(open_invoice(world["agency"]["id"], "2026-06")["id"])
    set_clock("2026-08-16T00:00:00Z")
    run_aging()
    world["cancelled_appointment"] = cancelled
    return world


def validate_success_cancel(appointment_id, headers):
    from test_helpers import api_client

    return validate_success(api_client.cancel_appointment(appointment_id, headers), 200)


def test_the_billing_freeze_pre_empts_the_appointment_state_check(api):
    """PRD 2.9: "Three orderings in this ladder are deliberate and consequential, and they are called
    out where they occur: the agency billing freeze at rung 7 pre-empts every state, temporal and
    fiscal rung below it; the concurrency check at rung 9 pre-empts the state-precondition rung at
    10, so a client holding a stale parent version learns that before it learns that the target is in
    the wrong state; and segregation of duties at rung 11 sits *below* the state rung, so an operator
    who tries to decide their own purge request on a submission that is not awaiting a decision is
    told about the state, not about the conflict of interest."
    PRD 2.10: "`POST /livescan/service-types`, `POST /livescan/appointments`, `POST /livescan/cards`,
    `POST /livescan/cards/{id}/positions/{position_code}/attempts`,
    `POST /livescan/cards/{id}/positions/{position_code}/exception`,
    `POST /livescan/cards/{id}/exception-override`, `POST /livescan/cards/{id}/finalize`,
    `POST /livescan/submissions`, `POST /livescan/submissions/{id}/reprints`,
    `POST /livescan/rapback-subscriptions`, `POST /livescan/rapback-subscriptions/{id}/renew`,
    `POST /livescan/fitness-determinations`, and `POST /livescan/device-assignments`."

    Design: Difficulty/priority_pair_validation_conflict/billing_freeze_outranks_appointment_state_on_card_open
    """
    world = _suspended_agency_with_a_cancelled_appointment()

    response = api.create_card(
        {
            "appointment_id": world["cancelled_appointment"]["id"],
            "device_id": world["device"]["id"],
        },
        TECH,
    )

    error = validate_error(response, ApiErrorId.ERR_AGENCY_BILLING_SUSPENDED.value)
    assert error["error_id"] != ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value

    _rows, meta = validate_paginated(
        api.list_cards(TECH, {"appointment_id": world["cancelled_appointment"]["id"]})
    )
    assert meta["total_count"] == 0


def test_forty_six_days_of_aging_suspends_the_agency_and_compounds_the_late_fee(api):
    """PRD 3.9: "Over that set, `max_aging_days` is the largest `aging_days`, or 0 when the set is
    empty, and `outstanding_balance_cents` is the sum of `total_cents` less `paid_cents`. A
    `max_aging_days` of at least 45 makes `billing_status` `SUSPENDED`; otherwise a `max_aging_days`
    of at least 1 makes it `PAST_DUE`; otherwise it is `CURRENT`. The suspension boundary is
    inclusive — exactly 45 suspends, 44 does not."
    PRD 3.9: "For each invoice whose `status` is `ISSUED` or `PAST_DUE`, it recomputes `aging_days`;
    where that count is at least 1 and `paid_cents` is below `total_cents`, the invoice moves
    `ISSUED → PAST_DUE` and a late fee accrues — one and a half percent of the unpaid balance, that
    is of `total_cents` less `paid_cents`, rounded half up, added to `late_fee_cents`, after which
    `total_cents` is recomputed as `subtotal_cents` plus `late_fee_cents`."

    Design: Difficulty/priority_pair_validation_conflict/billing_freeze_outranks_appointment_state_on_card_open
    """
    world = _suspended_agency_with_a_cancelled_appointment()

    agency = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency["billing_status"] == "SUSPENDED"
    assert agency["max_aging_days"] == 46

    invoice = validate_success(api.get_invoice(world["invoice"]["id"], VA), 200)
    assert_invoice(invoice)
    assert invoice["status"] == "PAST_DUE"
    assert invoice["late_fee_cents"] == 23
    assert invoice["total_cents"] == 1523

    cancelled = validate_success(
        api.get_appointment(world["cancelled_appointment"]["id"], TECH), 200
    )
    assert cancelled["status"] == "CANCELLED"


def test_an_invoice_is_not_past_due_on_its_due_date(api):
    """PRD 3.9: "An invoice whose `status` is neither `ISSUED` nor `PAST_DUE`, or whose `due_on` is
    null, has `aging_days` 0. Otherwise `aging_days` is the number of whole calendar days from
    `due_on` to the clock date, floored at zero; the invoice is past due exactly when that count is
    at least 1, so an invoice on its `due_on` date is **not** yet past due. An invoice issued on
    2026-06-01 with 30-day terms is due 2026-07-01 and still shows an `aging_days` of 0 on
    2026-07-01."

    Design: Corner/calculations/invoice_is_not_past_due_on_its_due_date_and_ages_the_next_day
    """
    world = setup_agency_billed_no_show_invoice(agency_overrides={"name": "Slow Payer"})

    assert_date_string(world["invoice"]["due_on"], "2026-07-01", "due_on")
    assert world["invoice"]["subtotal_cents"] == 1500

    set_clock("2026-07-01T12:00:00Z")
    run_aging()

    invoice = validate_success(api.get_invoice(world["invoice"]["id"], VA), 200)
    assert invoice["status"] == "ISSUED"
    assert invoice["aging_days"] == 0
    assert invoice["late_fee_cents"] == 0

    agency = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency["billing_status"] == "CURRENT"


def test_the_next_day_ages_the_invoice_and_accrues_the_late_fee(api):
    """PRD 3.9: "An invoice with a `subtotal_cents` of 5692 and no payment accrues one and a half
    percent of 5692, which is 85.38 and rounds to 85, making its `total_cents` 5777 on its first
    past-due run."
    PRD 3.9: "Issuing it moves `DRAFT → ISSUED` and is admitted only when at least one fee assessment
    exists whose `status` is `ASSESSED`, whose `payer_regime` is `AGENCY_BILLED` and whose
    `agency_id` matches the invoice's. Every such assessment is attached, ordered by `created_at`
    ascending, each having its `invoice_id` set and its `status` moved `ASSESSED → INVOICED`."

    Design: Corner/calculations/invoice_is_not_past_due_on_its_due_date_and_ages_the_next_day
    """
    world = setup_agency_billed_no_show_invoice(agency_overrides={"name": "Slow Payer"})

    set_clock("2026-07-01T12:00:00Z")
    run_aging()
    set_clock("2026-07-02T12:00:00Z")
    run_aging()

    invoice = validate_success(api.get_invoice(world["invoice"]["id"], VA), 200)
    assert invoice["status"] == "PAST_DUE"
    assert invoice["aging_days"] == 1
    assert invoice["late_fee_cents"] == 23
    assert invoice["total_cents"] == 1523

    agency = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency["billing_status"] == "PAST_DUE"
    assert agency["max_aging_days"] == 1

    assessment = only_fee_assessment(appointment_id=world["appointment"]["id"])
    assert assessment["status"] == "INVOICED"
    assert assessment["assessment_kind"] == "NO_SHOW"
    assert assessment["total_cents"] == 1500


def test_an_agency_billed_charge_cannot_be_settled_at_the_counter(api):
    """PRD 3.9: "Applicant-borne assessments are settled at the counter. A `LivescanTechnician` or
    the applicant supplies `amount_cents`; the assessment's `payer_regime` must be `APPLICANT_PAID`,
    failing which the answer is `ERR_PAYER_REGIME_MISMATCH`, and the amount must equal `total_cents`
    less `paid_cents` exactly, failing which the answer is `ERR_INVALID_REQUEST`."
    PRD 3.3: "The no-show releases the interval, sets `no_show_fee_assessed` to true, and creates
    exactly one fee assessment whose `assessment_kind` is `NO_SHOW` and whose `total_cents` is the
    flat 1500 cents, with `payer_regime` copied from the owning agency's `payer_regime_default`."

    Design: Corner/validations/point_of_service_payment_rejects_an_agency_billed_assessment
    """
    world = setup_agency_billed_no_show_invoice(
        agency_overrides={"name": "Billed Agency"}, issue=False
    )
    assessment = world["assessment"]

    response = api.pay_fee_assessment(assessment["id"], 1500, TECH)

    validate_error(response, ApiErrorId.ERR_PAYER_REGIME_MISMATCH.value)

    unchanged = validate_success(api.get_fee_assessment(assessment["id"], VA), 200)
    assert unchanged["status"] == "ASSESSED"
    assert unchanged["paid_cents"] == 0
    assert unchanged["assessment_kind"] == "NO_SHOW"
    assert unchanged["total_cents"] == 1500

    appointment = validate_success(api.get_appointment(world["appointment"]["id"], TECH), 200)
    assert appointment["status"] == "NO_SHOW"
    assert appointment["no_show_fee_assessed"] is True


def test_a_counter_payment_must_match_the_balance_exactly(api):
    """PRD 2.9 rung 40: "**Payment exactness.** The supplied `amount_cents` equals the fee
    assessment's `total_cents` minus its `paid_cents` exactly, or the invoice's `total_cents` minus
    its `paid_cents` exactly. Neither underpayment nor overpayment is accepted. Otherwise
    `ERR_INVALID_REQUEST`, HTTP 400."
    PRD 3.9: "Acceptance sets `paid_cents` to `total_cents` and moves the assessment
    `ASSESSED → PAID`."

    Design: Corner/validations/applicant_paid_assessment_requires_the_exact_amount
    """
    world = setup_agency_billed_no_show_invoice(
        payer_regime_default="APPLICANT_PAID", issue=False
    )
    assessment = world["assessment"]
    applicant_headers = make_applicant_headers(world["applicant"]["id"])

    underpaid = api.pay_fee_assessment(assessment["id"], 1000, applicant_headers)
    validate_error(underpaid, ApiErrorId.ERR_INVALID_REQUEST.value)

    settled = validate_success(api.pay_fee_assessment(assessment["id"], 1500, applicant_headers), 200)

    assert settled["status"] == "PAID"
    assert settled["paid_cents"] == 1500
    assert settled["invoice_id"] is None
