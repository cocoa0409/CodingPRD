"""The monthly cycle: issuing, paying, activation, suspension and reinstatement."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_equals,
    assert_invoice_conservation,
    create_family,
    create_invoice_payload,
    enroll,
    family_version,
    find_invoice,
    get_invoice,
    get_membership,
    get_physician,
    issue_invoice,
    open_invoice,
    pay_invoice,
    set_clock,
    setup_active_membership,
    setup_pending_membership,
    setup_practice,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# ==========================================================================
# Payment is the activation gate
# ==========================================================================


def test_pending_membership_refuses_consult_booking_until_the_invoice_is_paid(api):
    """PRD §3.8: "The membership must be `ACTIVE`, refusing anything else with
    `ERR_MEMBERSHIP_NOT_ACTIVE`."
    PRD §3.3: "There is no other route to activation: a membership whose family never
    pays its cycle invoice simply never activates."

    Design: Difficulty/cross_entity_state_dependency/membership_activation_gated_on_family_invoice_reaching_paid
    """
    scenario = setup_pending_membership(clock="2026-06-01T00:00:00Z", household_name="Rossi")
    membership, doc = scenario["membership"], scenario["physician"]

    assert membership["status"] == "PENDING_ACTIVATION"
    assert scenario["invoice"]["status"] == "DRAFT"

    resp = api.create_consult_booking(
        {
            "membership_id": membership["id"],
            "consult_type": "LACTATION_CONSULT",
            "consultant_physician_id": doc["id"],
            "scheduled_start": "2026-06-20T09:00:00Z",
            "scheduled_end": "2026-06-20T09:45:00Z",
            "modality": "IN_PERSON",
            "patient_state_code": "CA",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
    assert resp.status_code == 409

    assert float(get_physician(doc["id"])["weighted_occupancy"]) == 2.0, (
        "a PENDING_ACTIVATION membership already occupies its slot weight"
    )


def test_paying_the_cycle_invoice_activates_the_pending_membership(api):
    """PRD §3.3: "Payment is also the **activation gate for the whole practice**: as a
    side effect, every membership of that household sitting in `PENDING_ACTIVATION` whose
    `start_date` falls between the invoice's `cycle_start_date` and `cycle_end_date`,
    both bounds inclusive, transitions `PENDING_ACTIVATION → ACTIVE` and has its own
    `version` incremented by 1."
    PRD §3.3: "On success the paid amount is recorded in `amount_paid_cents` and
    `paid_date` is stamped with today's date."

    Design: Difficulty/cross_entity_state_dependency/membership_activation_gated_on_family_invoice_reaching_paid
    """
    scenario = setup_pending_membership(clock="2026-06-01T00:00:00Z", household_name="Rossi")
    membership, doc = scenario["membership"], scenario["physician"]
    invoice = scenario["invoice"]

    issue_invoice(invoice["id"])
    paid = pay_invoice(invoice["id"], 40000)

    assert paid["status"] == "PAID"
    assert_date_equals(paid["paid_date"], "2026-06-01", "Invoice.paid_date")
    assert paid["amount_paid_cents"] == 40000

    activated = get_membership(membership["id"])
    assert activated["status"] == "ACTIVE", (
        "no call was made against the membership itself; the invoice flipped it"
    )

    booking = validate_success(
        api.create_consult_booking(
            {
                "membership_id": membership["id"],
                "consult_type": "LACTATION_CONSULT",
                "consultant_physician_id": doc["id"],
                "scheduled_start": "2026-06-20T09:00:00Z",
                "scheduled_end": "2026-06-20T09:45:00Z",
                "modality": "IN_PERSON",
                "patient_state_code": "CA",
            },
            COORDINATOR,
        ),
        201,
    )
    assert booking["status"] == "SCHEDULED"
    assert float(get_physician(doc["id"])["weighted_occupancy"]) == 2.0


def test_paying_an_amount_other_than_the_total_is_refused(api):
    """PRD §3.3: "The supplied `amount_paid_cents` must equal the invoice's `total_cents`
    precisely; a partial payment, or an overpayment, is refused with `ERR_VALIDATION`."
    PRD §2.7: "No later rule runs and no partial mutation is persisted."

    Design: Corner/validations/corner_pay_invoice_with_wrong_amount_returns_invalid_request
    """
    scenario = setup_pending_membership(clock="2026-06-01T00:00:00Z", household_name="Mroz")
    invoice = issue_invoice(scenario["invoice"]["id"])
    assert invoice["total_cents"] == 40000

    resp = api.pay_invoice(invoice["id"], {"amount_paid_cents": 39999}, BILLING)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400

    unchanged = get_invoice(invoice["id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["amount_paid_cents"] == 0
    assert unchanged["paid_date"] is None
    assert get_membership(scenario["membership"]["id"])["status"] == "PENDING_ACTIVATION"


def test_invoice_cycle_start_must_be_the_first_of_a_month(api):
    """PRD §3.3: "A `BillingSpecialist` or `PracticeAdmin` opens an invoice by naming the
    `family_id` and a `cycle_start_date`, which must be the 1st day of a calendar month —
    any other day is `ERR_INVALID_DATE_RANGE`"

    Design: Corner/validations/corner_invoice_cycle_start_not_first_of_month_returns_invalid_date_range
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Kelso")

    resp = api.create_invoice(create_invoice_payload(family["id"], "2026-07-15"), BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
    assert resp.status_code == 400

    rows, meta = validate_paginated(
        api.list_invoices(BILLING, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


# ==========================================================================
# Freezing an issued invoice
# ==========================================================================


def test_issued_invoice_is_frozen_against_a_later_enrolment(api):
    """PRD §3.3: "Only `DRAFT` invoices are ever recomputed."
    PRD §3.3: "From that moment the invoice is frozen: later enrolments and cancellations
    in the same household no longer rewrite its lines, no matter how much the ladder moves
    underneath it."
    PRD §3.2: "If an invoice for that cycle already exists but has reached `ISSUED` or
    `PAID`, it is left completely untouched and **no replacement invoice is created** —
    the newly enrolled child is simply unbilled for that already-closed cycle."

    Design: Corner/state_machines/corner_issued_invoice_is_frozen_against_a_later_enrollment
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family = create_family(household_name="Quintero", family_monthly_cap_cents=100000)
    child_a = validate_success(
        api.create_child(
            {"family_id": family["id"], "first_name": "Pia", "date_of_birth": "2026-04-01"}, ADMIN
        ),
        201,
    )
    child_b = validate_success(
        api.create_child(
            {"family_id": family["id"], "first_name": "Rio", "date_of_birth": "2024-06-01"}, ADMIN
        ),
        201,
    )

    mem_a = enroll(child_a["id"], plan_id, doc_id, "2026-06-01", family["id"])
    invoice = find_invoice(family["id"])
    issue_invoice(invoice["id"])

    mem_b = validate_success(
        api.create_membership(
            {
                "child_id": child_b["id"],
                "plan_id": plan_id,
                "physician_id": doc_id,
                "start_date": "2026-06-11",
                "expected_family_version": family_version(family["id"]),
            },
            ADMIN,
        ),
        201,
    )

    assert mem_b["enrollment_sequence"] == 2
    assert float(mem_b["discount_pct"]) == 0.20
    assert mem_b["monthly_rate_cents"] == 32000

    refreshed_a = get_membership(mem_a["id"])
    assert refreshed_a["enrollment_sequence"] == 1
    assert refreshed_a["monthly_rate_cents"] == 40000

    frozen = get_invoice(invoice["id"])
    assert frozen["status"] == "ISSUED"
    assert len(frozen["lines"]) == 1
    assert frozen["subtotal_cents"] == 40000
    assert frozen["total_cents"] == 40000

    rows, meta = validate_paginated(
        api.list_invoices(BILLING, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 1, "no replacement June invoice was created"


def test_cancellation_proration_bills_only_the_leading_days(api):
    """PRD §3.3: "Under the **cancellation** shape — a membership whose
    `cancellation_effective_date` falls on or between the `cycle_start_date` and the
    `cycle_end_date` — the counted window runs from the later of `start_date` and
    `cycle_start_date` through the `cancellation_effective_date`, both inclusive; the
    leading edge is billed and the trailing edge is cut."
    PRD §3.3: "a membership starting 2026-06-11 in a 30-day cycle bills 20 days under
    the enrolment shape, while the same membership cancelled effective 2026-06-11 bills
    11 days under the cancellation shape."

    Design: Corner/calculations/corner_cancellation_proration_counts_leading_days_only
    """
    scenario = setup_pending_membership(
        clock="2026-06-01T00:00:00Z", household_name="Delgado", child_first_name="Sole"
    )
    membership, family = scenario["membership"], scenario["family"]
    invoice_before = get_invoice(scenario["invoice"]["id"])

    assert invoice_before["total_cents"] == 40000
    assert invoice_before["lines"][0]["covered_days"] == 30

    set_clock("2026-06-11T00:00:00Z")

    cancelled = validate_success(
        api.cancel_membership(
            membership["id"],
            {"effective_date": "2026-06-11", "expected_family_version": family_version(family["id"])},
            ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert_date_equals(
        cancelled["cancellation_effective_date"], "2026-06-11", "cancellation_effective_date"
    )

    invoice_after = get_invoice(invoice_before["id"])
    assert invoice_after["lines"][0]["covered_days"] == 11
    assert invoice_after["lines"][0]["prorated_cents"] == 14667
    assert invoice_after["subtotal_cents"] == 14667
    assert invoice_after["total_cents"] == 14667
    assert invoice_after["total_cents"] != 26667, (
        "the enrolment shape would have selected the trailing 20 days instead"
    )
    assert_invoice_conservation(invoice_after)


# ==========================================================================
# Suspension and reinstatement
# ==========================================================================


def _household_with_past_due_july_invoice():
    """ACTIVE membership, June invoice PAID, July invoice ISSUED and past due."""
    scenario = setup_active_membership(clock="2026-06-01T00:00:00Z", household_name="Duarte")
    july = open_invoice(scenario["family"]["id"], "2026-07-01")
    july = issue_invoice(july["id"])
    set_clock("2026-06-16T00:00:00Z")
    scenario["july_invoice"] = july
    return scenario


def test_suspending_for_non_payment_records_the_reason_and_keeps_the_slot(api):
    """PRD §3.3: "A `PracticeAdmin` or `BillingSpecialist` suspends an `ACTIVE` membership
    for non-payment, supplying a `reason` that is recorded in `suspension_reason`."
    PRD §3.3: "Suspension is financially inert on both sides: the membership keeps its
    panel slot weight, so the physician's `weighted_occupancy` is unchanged, and it keeps
    its invoice line, so no draft invoice is recomputed."
    PRD §3.3: "Issuance stamps `issued_date` with today's date and sets `due_date` to
    fourteen days after that."

    Design: Difficulty/non_linear_state_machine/membership_traverses_active_suspended_active_cycle
    """
    scenario = _household_with_past_due_july_invoice()
    membership, doc = scenario["membership"], scenario["physician"]
    july = get_invoice(scenario["july_invoice"]["id"])

    assert july["total_cents"] == 40000
    assert_date_equals(july["due_date"], "2026-06-15", "Invoice.due_date")

    suspended = validate_success(
        api.suspend_membership(membership["id"], {"reason": "July invoice past due"}, BILLING)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "July invoice past due"
    assert suspended["enrollment_sequence"] == 1

    assert float(get_physician(doc["id"])["weighted_occupancy"]) == 2.0, (
        "suspension does not release panel weight"
    )


def test_reinstating_after_clearing_the_past_due_invoice_returns_to_active(api):
    """PRD §3.3: "Reinstatement runs the mirror test — the household must hold **zero**
    invoices in `ISSUED` whose `due_date` is strictly before today, and any remaining
    past-due invoice refuses the reinstatement with the same
    `ERR_ENROLLMENT_INVOICE_UNPAID` — and on success moves the membership
    `SUSPENDED → ACTIVE` and clears `suspension_reason` back to null."

    Design: Difficulty/non_linear_state_machine/membership_traverses_active_suspended_active_cycle
    """
    scenario = _household_with_past_due_july_invoice()
    membership = scenario["membership"]

    validate_success(
        api.suspend_membership(membership["id"], {"reason": "July invoice past due"}, BILLING)
    )
    pay_invoice(scenario["july_invoice"]["id"], 40000)

    reinstated = validate_success(api.reinstate_membership(membership["id"], BILLING))
    assert reinstated["status"] == "ACTIVE", "the row ends in the state it started in"
    assert reinstated["suspension_reason"] is None
    assert reinstated["enrollment_sequence"] == 1


def test_suspending_without_a_past_due_invoice_is_refused(api):
    """PRD §3.3: "The operation requires the household to hold at least one invoice in
    `ISSUED` whose `due_date` is strictly before today; with no such past-due invoice the
    suspension is refused with `ERR_ENROLLMENT_INVOICE_UNPAID`."

    Design: Corner/state_machines/corner_suspend_without_past_due_invoice_returns_enrollment_invoice_unpaid
    """
    scenario = setup_active_membership(clock="2026-06-01T00:00:00Z", household_name="Jansen")
    membership = scenario["membership"]

    resp = api.suspend_membership(
        membership["id"], {"reason": "Speculative suspension"}, BILLING
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVOICE_UNPAID)
    assert resp.status_code == 409

    unchanged = get_membership(membership["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["suspension_reason"] is None


def test_reinstating_while_a_past_due_invoice_remains_is_refused(api):
    """PRD §3.3: "Reinstatement runs the mirror test — the household must hold **zero**
    invoices in `ISSUED` whose `due_date` is strictly before today, and any remaining
    past-due invoice refuses the reinstatement with the same
    `ERR_ENROLLMENT_INVOICE_UNPAID`"

    Design: Corner/state_machines/corner_reinstate_with_past_due_invoice_returns_enrollment_invoice_unpaid
    """
    scenario = _household_with_past_due_july_invoice()
    membership = scenario["membership"]

    validate_success(
        api.suspend_membership(membership["id"], {"reason": "July invoice past due"}, BILLING)
    )

    resp = api.reinstate_membership(membership["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVOICE_UNPAID)
    assert resp.status_code == 409

    still = get_membership(membership["id"])
    assert still["status"] == "SUSPENDED"
    assert still["suspension_reason"] == "July invoice past due"

    july = get_invoice(scenario["july_invoice"]["id"])
    assert july["status"] == "ISSUED"
    assert_date_equals(july["due_date"], "2026-06-15", "Invoice.due_date")


def test_reinstating_an_active_membership_is_an_invalid_transition(api):
    """PRD §3.3: "Suspending something that is not `ACTIVE`, or reinstating something that
    is not `SUSPENDED`, is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_reinstate_active_membership_returns_invalid_state
    """
    scenario = setup_active_membership(clock="2026-06-01T00:00:00Z", household_name="Ibarra")
    membership = scenario["membership"]
    assert membership["status"] == "ACTIVE"

    resp = api.reinstate_membership(membership["id"], BILLING)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_ENROLLMENT_INVOICE_UNPAID.value

    assert get_membership(membership["id"])["status"] == "ACTIVE"


def test_cancelling_a_cancelled_membership_is_refused_and_fires_no_cascade(api):
    """PRD §3.4: "A membership already in `CANCELLED` refuses the operation with
    `ERR_INVALID_STATE`."
    PRD §2.7: "No later rule runs and no partial mutation is persisted."

    Design: Corner/state_machines/corner_cancel_membership_twice_returns_invalid_state
    """
    scenario = setup_pending_membership(clock="2026-06-01T00:00:00Z", household_name="Grigoriev")
    membership, family, doc = scenario["membership"], scenario["family"], scenario["physician"]

    validate_success(
        api.cancel_membership(
            membership["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(family["id"])},
            ADMIN,
        )
    )
    token_after_cancel = family_version(family["id"])

    resp = api.cancel_membership(
        membership["id"],
        {"effective_date": "2026-06-01", "expected_family_version": token_after_cancel},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    row = get_membership(membership["id"])
    assert row["status"] == "CANCELLED"
    assert float(row["slot_weight"]) == 0.0
    assert float(get_physician(doc["id"])["weighted_occupancy"]) == 0.0
    assert family_version(family["id"]) == token_after_cancel, (
        "the rejected cancel advanced nothing"
    )
