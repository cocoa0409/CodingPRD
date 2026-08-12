"""Billing claims: provisional vs final payer split variants, nested min/max
clipping, per-line subsidy rounding, the pool waterfall snapshot order, payment
and void conservation, the overdue sweep cascade, and the invoice lifecycle
error ladder (PRD §2.4, §3.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assert_invoice_money_conservation,
    assert_payment,
    book_and_check_in,
    create_invoice_payload,
    create_payment_payload,
    get_invoice,
    get_pool_by_term,
    get_student,
    make_invoice,
    make_policy,
    make_pool,
    make_provider,
    make_student,
    make_verified_policy,
    set_clock,
    setup_chargeable_encounter,
    setup_issued_invoice,
    setup_overdue_invoice_scenario,
    validate_error,
    validate_success,
)

POLICY_TERMS = {
    "payer_type": "EXTERNAL",
    "copay_cents": 2500,
    "deductible_cents": 5000,
    "coinsurance_pct": 0.2,
    "coverage_start": "2026-04-01T00:00:00Z",
    "coverage_end": "2027-03-31T00:00:00Z",
}

ZERO_POLICY_TERMS = {
    "payer_type": "EXTERNAL",
    "copay_cents": 0,
    "deductible_cents": 0,
    "coinsurance_pct": 0.0,
    "coverage_start": "2026-04-01T00:00:00Z",
    "coverage_end": "2027-03-31T00:00:00Z",
}


def _policy_for_student(api, student_id, headers):
    policies = validate_success(api.list_student_policies(student_id, headers), 200)
    assert len(policies) >= 1
    return policies[0]


# ---------------------------------------------------------------------------
# Depth probes: PROVISIONAL vs FINAL payer-split variants on identical charges
# ---------------------------------------------------------------------------

def _setup_billing_scenario():
    """Clock 2026-05-01; student with an UNVERIFIED EXTERNAL policy; checked-in
    SPORTS_PHYSICAL encounter. Returns (student, provider, encounter, policy)."""
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S100", "Ann Able")
    policy = make_policy(student, policy_number="EX-1", **POLICY_TERMS)
    provider = make_provider("Dr B")
    _, encounter = book_and_check_in(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    return student, provider, encounter, policy


def test_provisional_invoice_makes_patient_pay_everything(api, billing_officer_headers):
    """PRD §3.8: "At generation time the invoice is `PROVISIONAL` and the
    patient pays everything: `insurer_pays_cents` is zero and
    `patient_responsibility_cents` equals `charge_total_cents`, regardless of
    any policy on file."

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_payer_split
    """
    _, _, encounter, _ = _setup_billing_scenario()
    invoice = validate_success(
        api.create_invoice(
            encounter["id"],
            create_invoice_payload([
                {"service_category": "SPORTS_FEE", "charge_cents": 10000}
            ]),
            billing_officer_headers,
        ),
        201,
    )
    assert_invoice(invoice)
    assert invoice["status"] == "DRAFT"
    assert invoice["variant"] == "PROVISIONAL"
    assert invoice["charge_total_cents"] == 10000
    assert invoice["patient_responsibility_cents"] == 10000
    assert invoice["insurer_pays_cents"] == 0


def test_final_issue_adjudicates_split_and_diverges(api, billing_officer_headers):
    """PRD §3.8: "When a `BillingOfficer` issues the invoice ... the variant
    flips to `FINAL` and the split is recomputed. If a `VERIFIED` policy exists
    for the student at issue time, the adjudicated split applies: the amount
    after copay is `charge_total_cents` minus `copay_cents`, floored at zero;
    the deductible remaining is `deductible_cents` minus the policy's
    `deductible_met_cents`, floored at zero; the deductible applied to this
    invoice is the smaller of those two figures; the coinsurance base is the
    after-copay amount minus the deductible applied; the patient's coinsurance
    share is that base multiplied by `coinsurance_pct`, rounded half-up to
    integer cents." (charge 10000, copay 2500, deductible 5000/0 met, 0.2 ->
    patient 2500+5000+500 = 8000, insurer 2000.)
    PRD §3.8: "issue stamps `issued_at` with the current logical time, sets
    `due_date` to thirty calendar days after the issue date, and initializes
    `balance_cents` equal to `patient_responsibility_cents`."
    PRD §3.8: "As a side effect of issue, the policy's `deductible_met_cents`
    accumulates the deductible applied."

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_payer_split
    """
    student, _, encounter, policy = _setup_billing_scenario()
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 10000}
    ])
    provisional_patient = invoice["patient_responsibility_cents"]

    validate_success(api.verify_insurance_policy(policy["id"], billing_officer_headers),
                     200)
    issued = validate_success(
        api.issue_invoice(invoice["id"], billing_officer_headers), 200
    )
    assert_invoice(issued)
    assert issued["variant"] == "FINAL"
    assert issued["status"] == "ISSUED"
    assert issued["patient_responsibility_cents"] == 8000
    assert issued["insurer_pays_cents"] == 2000
    assert issued["balance_cents"] == 8000
    assert issued["due_date"] == "2026-05-31", "issue date 2026-05-01 + 30 days"
    assert provisional_patient == 10000 and issued["patient_responsibility_cents"] == 8000, (
        "provisional and final variants must diverge on identical charge data"
    )

    policy_after = _policy_for_student(api, student["id"], billing_officer_headers)
    assert policy_after["deductible_met_cents"] == 5000


# ---------------------------------------------------------------------------
# Depth probes: nested min/max clipping inside the adjudicated split
# ---------------------------------------------------------------------------

def _setup_clipping_scenario():
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S300", "Clip Test")
    make_verified_policy(student, policy_number="EX-2", **POLICY_TERMS)
    provider = make_provider("Dr D")
    _, encounter = book_and_check_in(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    return student, encounter


def test_payer_split_deductible_clipped_by_after_copay(api, billing_officer_headers):
    """PRD §3.8: "the amount after copay is `charge_total_cents` minus
    `copay_cents`, floored at zero; ... the deductible applied to this invoice
    is the smaller of those two figures; the coinsurance base is the after-copay
    amount minus the deductible applied". With charge 3000, copay 2500,
    deductible 5000: after_copay 500 clips the deductible (min(500, 5000)),
    zeroing the coinsurance base, so the patient pays 2500+500+0 = 3000 and the
    insurer pays 0.

    Design: Difficulty/combinatorial_formula/payer_split_nested_min_max_clipping
    """
    _, encounter = _setup_clipping_scenario()
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 3000}
    ])
    issued = validate_success(
        api.issue_invoice(invoice["id"], billing_officer_headers), 200
    )
    assert issued["variant"] == "FINAL"
    assert issued["charge_total_cents"] == 3000
    assert issued["patient_responsibility_cents"] == 3000
    assert issued["insurer_pays_cents"] == 0


def test_payer_split_issue_accumulates_deductible_met(api, billing_officer_headers):
    """PRD §3.8: "As a side effect of issue, the policy's
    `deductible_met_cents` accumulates the deductible applied." Here the applied
    deductible is min(500 after copay, 5000 remaining) = 500.

    Design: Difficulty/combinatorial_formula/payer_split_nested_min_max_clipping
    """
    student, encounter = _setup_clipping_scenario()
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 3000}
    ])
    validate_success(api.issue_invoice(invoice["id"], billing_officer_headers), 200)
    policy_after = _policy_for_student(api, student["id"], billing_officer_headers)
    assert policy_after["deductible_met_cents"] == 500


# ---------------------------------------------------------------------------
# Depth probes: per-line subsidy rounding, then sum
# ---------------------------------------------------------------------------

def _setup_travel_scenario(ref, budget):
    set_clock("2026-05-01T00:00:00Z")
    make_pool(term_code="SP26", budget_cents=budget)
    student = make_student(ref, "Travel Patient")
    make_verified_policy(student, policy_number=f"EX-{ref}", **ZERO_POLICY_TERMS)
    provider = make_provider("Dr E")
    return student, provider


def test_travel_subsidy_rounded_per_line_then_summed(api, billing_officer_headers):
    """PRD §3.8: "The rounding order is pinned — subsidy is rounded **per line
    first, then summed**; the alternative of summing travel charges and rounding
    once is rejected because it yields different cents (two 3333-cent lines at
    one-half produce per-line subsidies of 1667 + 1667 = 3334, versus 3333 if
    rounded only after summing)."
    PRD §3.8: "The invoice's `subsidy_cents` is the sum of applied subsidies,
    each line's net is its charge minus its applied subsidy, and
    `charge_total_cents` is the sum of the per-line nets."

    Design: Difficulty/combinatorial_formula/per_line_subsidy_rounding_then_sum
    """
    student, provider = _setup_travel_scenario("S301", 100000)
    _, encounter = book_and_check_in(
        student["id"], provider["id"], "TRAVEL_CLINIC",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    invoice = validate_success(
        api.create_invoice(
            encounter["id"],
            create_invoice_payload([
                {"service_category": "TRAVEL_VACCINE", "charge_cents": 3333},
                {"service_category": "TRAVEL_VACCINE", "charge_cents": 3333},
                {"service_category": "CONSULT", "charge_cents": 5000},
            ]),
            billing_officer_headers,
        ),
        201,
    )
    assert_invoice(invoice)
    assert invoice["subsidy_cents"] == 3334, "1667 + 1667 + 0 (per-line, not 3333)"
    assert invoice["charge_total_cents"] == 8332, "1666 + 1666 + 5000"
    assert invoice["variant"] == "PROVISIONAL"
    assert invoice["patient_responsibility_cents"] == 8332


def test_travel_subsidy_debits_pool_once_by_applied_total(api, billing_officer_headers):
    """PRD §3.8: "Only after the whole invoice is built is the pool debited, in
    a single step, by the total applied subsidy."

    Design: Difficulty/combinatorial_formula/per_line_subsidy_rounding_then_sum
    """
    student, provider = _setup_travel_scenario("S301", 100000)
    _, encounter = book_and_check_in(
        student["id"], provider["id"], "TRAVEL_CLINIC",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    make_invoice(encounter["id"], [
        {"service_category": "TRAVEL_VACCINE", "charge_cents": 3333},
        {"service_category": "TRAVEL_VACCINE", "charge_cents": 3333},
        {"service_category": "CONSULT", "charge_cents": 5000},
    ])
    pool = get_pool_by_term("SP26")
    assert pool["spent_cents"] == 3334, (
        f"single debit of the total applied subsidy, got {pool['spent_cents']}"
    )


# ---------------------------------------------------------------------------
# Depth probes: pool waterfall snapshot evaluation order
# ---------------------------------------------------------------------------

def _setup_waterfall_scenario():
    student, provider = _setup_travel_scenario("S302", 10000)
    encounters = []
    for day in ("2026-05-02", "2026-05-03", "2026-05-04"):
        _, enc = book_and_check_in(
            student["id"], provider["id"], "TRAVEL_CLINIC",
            f"{day}T10:00:00Z", f"{day}T10:30:00Z",
        )
        encounters.append(enc)
    return student, provider, encounters


def test_pool_waterfall_snapshots_remaining_per_invoice(api, billing_officer_headers):
    """PRD §3.8: "The pool's remaining budget — `budget_cents` minus
    `spent_cents` — is snapshotted before this invoice. The lines are then
    walked in request order, and each line's applied subsidy is the smaller of
    its tentative subsidy and the snapshot's current remainder, which is then
    reduced by the applied amount before the next line." With a 10000 budget:
    invoice 1 (16000 travel charge) applies min(8000, 10000) = 8000; invoice 2
    (10000 travel charge) applies min(5000, 2000) = 2000, not a recomputed
    value.

    Design: Difficulty/combinatorial_formula/pool_waterfall_snapshot_evaluation_order
    """
    _, _, encounters = _setup_waterfall_scenario()
    inv1 = validate_success(
        api.create_invoice(
            encounters[0]["id"],
            create_invoice_payload([
                {"service_category": "TRAVEL_VACCINE", "charge_cents": 16000}
            ]),
            billing_officer_headers,
        ),
        201,
    )
    assert inv1["subsidy_cents"] == 8000
    assert inv1["charge_total_cents"] == 8000

    inv2 = validate_success(
        api.create_invoice(
            encounters[1]["id"],
            create_invoice_payload([
                {"service_category": "TRAVEL_VACCINE", "charge_cents": 10000}
            ]),
            billing_officer_headers,
        ),
        201,
    )
    assert inv2["subsidy_cents"] == 2000, (
        "tentative 5000 capped by the 2000 remaining after invoice 1"
    )
    assert inv2["charge_total_cents"] == 8000


def test_pool_waterfall_exhaustion_blocks_further_subsidy(api, billing_officer_headers):
    """PRD §3.8: "when the line's `service_category` is `TRAVEL_VACCINE`, the
    encounter's visit type is `TRAVEL_CLINIC`, and an `OPEN`, non-exhausted
    health-fee pool exists, the line's tentative subsidy is its `charge_cents`
    multiplied by one-half"; "the `exhausted` flag is derived and turns true
    exactly when `spent_cents` reaches or exceeds `budget_cents`, a
    boundary-inclusive comparison." At spent 10000 == budget 10000 the pool is
    exhausted, so a third 4000 travel line draws zero subsidy.

    Design: Difficulty/combinatorial_formula/pool_waterfall_snapshot_evaluation_order
    """
    _, _, encounters = _setup_waterfall_scenario()
    make_invoice(encounters[0]["id"], [
        {"service_category": "TRAVEL_VACCINE", "charge_cents": 16000}
    ])
    make_invoice(encounters[1]["id"], [
        {"service_category": "TRAVEL_VACCINE", "charge_cents": 10000}
    ])
    inv3 = validate_success(
        api.create_invoice(
            encounters[2]["id"],
            create_invoice_payload([
                {"service_category": "TRAVEL_VACCINE", "charge_cents": 4000}
            ]),
            billing_officer_headers,
        ),
        201,
    )
    assert inv3["subsidy_cents"] == 0
    assert inv3["charge_total_cents"] == 4000

    pool = get_pool_by_term("SP26")
    assert pool["spent_cents"] == 10000
    assert pool["exhausted"] is True, "spent == budget must flag exhausted (inclusive)"


# ---------------------------------------------------------------------------
# Depth probes: payment then void conserves money
# ---------------------------------------------------------------------------

def _setup_adjudicated_issued_invoice():
    return setup_issued_invoice(
        external_ref="S1001", charge_cents=10000, policy_terms={
            **POLICY_TERMS, "policy_number": "EX-5",
        },
    )


def test_partial_payment_reduces_balance_immediately(api, billing_officer_headers):
    """PRD §3.8: "After every posting, the invoice's balance is recomputed as
    `patient_responsibility_cents` minus the sum of all `POSTED` payments, and
    the status is re-derived: ... a positive balance below the full patient
    responsibility is `PARTIALLY_PAID`".

    Design: Difficulty/compensating_invariant/invoice_payment_then_void_conserves_money
    """
    student, _, _, _, invoice = _setup_adjudicated_issued_invoice()
    assert invoice["patient_responsibility_cents"] == 8000
    assert invoice["due_date"] == "2026-05-31"

    payment = validate_success(
        api.create_payment(invoice["id"], create_payment_payload(3000, "CARD"),
                           billing_officer_headers),
        201,
    )
    assert_payment(payment)
    assert payment["status"] == "POSTED"

    after = get_invoice(invoice["id"])
    assert after["balance_cents"] == 5000
    assert after["status"] == "PARTIALLY_PAID"
    assert_invoice_money_conservation(after, 3000)


def test_void_restores_balance_and_reverts_to_issued(api, billing_officer_headers):
    """PRD §3.8: "Money is conserved as an invariant: the patient responsibility
    always equals the outstanding balance plus the sum of posted payments, so a
    post followed by a void of the same payment leaves `balance_cents`
    unchanged." and "a `PAID` invoice returns to `ISSUED` when its `due_date` is
    still in the future" — here a `PARTIALLY_PAID` invoice whose balance returns
    to the full responsibility likewise returns to `ISSUED` (due 2026-05-31,
    clock 2026-05-01).

    Design: Difficulty/compensating_invariant/invoice_payment_then_void_conserves_money
    """
    _, _, _, _, invoice = _setup_adjudicated_issued_invoice()
    payment = validate_success(
        api.create_payment(invoice["id"], create_payment_payload(3000, "CARD"),
                           billing_officer_headers),
        201,
    )
    voided = validate_success(
        api.void_payment(payment["id"], billing_officer_headers), 200
    )
    assert voided["status"] == "VOIDED"

    after = get_invoice(invoice["id"])
    assert after["balance_cents"] == 8000, (
        "post(3000) then void restores the balance to the full responsibility"
    )
    assert after["status"] == "ISSUED", "due date still in the future"
    assert_invoice_money_conservation(after, 0)


# ---------------------------------------------------------------------------
# Depth probes: sweep OVERDUE -> posture -> elective cancellation (depth 3)
# ---------------------------------------------------------------------------

def test_sweep_marks_invoice_overdue_and_imposes_financial_hold(api):
    """PRD §3.8: "The clock sweep ages receivables: an `ISSUED` or
    `PARTIALLY_PAID` invoice whose `due_date` falls before the current logical
    date with a positive balance transitions to `OVERDUE`. That transition
    recomputes the student's posture into `REGISTRATION_HOLD` with `FINANCIAL`
    added to `active_hold_types`".

    Design: Difficulty/transitive_cascade/sweep_overdue_invoice_to_elective_cancellation
    """
    student, _, invoice, _, _ = setup_overdue_invoice_scenario()

    aged = get_invoice(invoice["id"])
    assert aged["status"] == "OVERDUE", (
        "due_date 2026-05-31 < 2026-06-01 with balance 5000 > 0"
    )
    assert aged["balance_cents"] == 5000

    held = get_student(student["id"])
    assert held["compliance_posture"] == "REGISTRATION_HOLD"
    assert "FINANCIAL" in held["active_hold_types"]


def test_overdue_sweep_cancels_only_future_elective_appointments(api,
                                                                 front_desk_headers):
    """PRD §3.8: "auto-cancels every still-`BOOKED` future elective appointment
    (`SPORTS_PHYSICAL` or `TRAVEL_CLINIC` with `scheduled_start` in the future)
    with `cancel_reason` set to `HOLD`" — urgent visits are not elective and
    survive the cascade.

    Design: Difficulty/transitive_cascade/sweep_overdue_invoice_to_elective_cancellation
    """
    _, _, _, elective, urgent = setup_overdue_invoice_scenario()

    elective_after = validate_success(
        api.get_appointment(elective["id"], front_desk_headers), 200
    )
    assert elective_after["status"] == "CANCELLED"
    assert elective_after["cancel_reason"] == "HOLD"

    urgent_after = validate_success(
        api.get_appointment(urgent["id"], front_desk_headers), 200
    )
    assert urgent_after["status"] == "BOOKED", (
        "urgent appointments are never cascade-cancelled"
    )


# ---------------------------------------------------------------------------
# Corner: the full invoice/payment lifecycle error ladder
# ---------------------------------------------------------------------------

def test_invoice_lifecycle_error_chain(api, billing_officer_headers):
    """PRD §3.8: payment "applies to invoices in `ISSUED`, `PARTIALLY_PAID`, or
    `OVERDUE` (anything else is rejected with `ERR_INVOICE_NOT_PAYABLE`)".
    PRD §3.8: "issuing anything else is rejected with `ERR_INVOICE_NOT_DRAFT`".
    PRD §3.8: "Exactly one invoice may exist per encounter: a second generation
    attempt is rejected with `ERR_INVOICE_EXISTS`".
    PRD §3.8: "The amount must be positive (`ERR_INVALID_QUANTITY`) and must not
    exceed the invoice's current `balance_cents` (`ERR_OVERPAYMENT`)".
    PRD §3.8: "a `BillingOfficer` voids a `POSTED` payment (any other status
    fails with `ERR_PAYMENT_NOT_VOIDABLE`)".

    Design: Corner/state_machines/invoice_lifecycle_error_chain
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, encounter = setup_chargeable_encounter(external_ref="S15")
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 5000}
    ])
    assert invoice["status"] == "DRAFT"
    assert invoice["variant"] == "PROVISIONAL"

    # Payment on a DRAFT invoice.
    res1 = api.create_payment(invoice["id"], create_payment_payload(100, "CARD"),
                              billing_officer_headers)
    validate_error(res1, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)

    # Issue: FINAL, self-pay (no policy), due thirty days after 2026-05-01.
    issued = validate_success(
        api.issue_invoice(invoice["id"], billing_officer_headers), 200
    )
    assert issued["status"] == "ISSUED"
    assert issued["variant"] == "FINAL"
    assert issued["due_date"] == "2026-05-31"
    assert issued["balance_cents"] == 5000

    # Double issue.
    res2 = api.issue_invoice(invoice["id"], billing_officer_headers)
    validate_error(res2, ApiErrorId.ERR_INVOICE_NOT_DRAFT, expected_status=409)

    # Second invoice for the same encounter.
    res3 = api.create_invoice(
        encounter["id"],
        create_invoice_payload([{"service_category": "SPORTS_FEE", "charge_cents": 5000}]),
        billing_officer_headers,
    )
    validate_error(res3, ApiErrorId.ERR_INVOICE_EXISTS, expected_status=409)

    # Overpayment: 5001 > balance 5000.
    res4 = api.create_payment(invoice["id"], create_payment_payload(5001, "CARD"),
                              billing_officer_headers)
    validate_error(res4, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)

    # Exact payoff -> PAID with zero balance.
    payment = validate_success(
        api.create_payment(invoice["id"], create_payment_payload(5000, "CARD"),
                           billing_officer_headers),
        201,
    )
    paid = get_invoice(invoice["id"])
    assert paid["status"] == "PAID"
    assert paid["balance_cents"] == 0

    # PAID is terminal for payments.
    res5 = api.create_payment(invoice["id"], create_payment_payload(1, "CARD"),
                              billing_officer_headers)
    validate_error(res5, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)

    # Void restores the balance; due date still in the future -> ISSUED.
    voided = validate_success(
        api.void_payment(payment["id"], billing_officer_headers), 200
    )
    assert voided["status"] == "VOIDED"
    restored = get_invoice(invoice["id"])
    assert restored["balance_cents"] == 5000
    assert restored["status"] == "ISSUED"

    # Double void.
    res6 = api.void_payment(payment["id"], billing_officer_headers)
    validate_error(res6, ApiErrorId.ERR_PAYMENT_NOT_VOIDABLE, expected_status=409)


# ---------------------------------------------------------------------------
# Corner: financial hold released by full payment
# ---------------------------------------------------------------------------

def test_financial_hold_released_by_full_payment(api, billing_officer_headers):
    """PRD §3.8: "Whenever a payment or void changes an `OVERDUE` invoice's
    balance, the student's compliance posture is recomputed — a financial hold
    releases the moment no overdue invoice remains." and "A payment that exactly
    covers the balance therefore moves the invoice ... `OVERDUE → PAID`".
    PRD §3.1: with no hold source left, "otherwise it is `CLEAR`" and the
    hold-type list is empty.

    Design: Corner/calculations/financial_hold_released_by_full_payment
    """
    student, _, invoice, _, _ = setup_overdue_invoice_scenario()

    held = get_student(student["id"])
    assert held["compliance_posture"] == "REGISTRATION_HOLD"
    assert "FINANCIAL" in held["active_hold_types"]

    payment = validate_success(
        api.create_payment(invoice["id"], create_payment_payload(5000, "CARD"),
                           billing_officer_headers),
        201,
    )
    assert payment["status"] == "POSTED"

    settled = get_invoice(invoice["id"])
    assert settled["status"] == "PAID"
    assert settled["balance_cents"] == 0

    released = get_student(student["id"])
    assert released["compliance_posture"] == "CLEAR"
    assert released["active_hold_types"] == []


# ---------------------------------------------------------------------------
# Corner: immediate consistency of balance recomputation
# ---------------------------------------------------------------------------

def test_payment_immediately_visible_on_invoice_read(api, billing_officer_headers):
    """PRD §3.8: "After every posting, the invoice's balance is recomputed as
    `patient_responsibility_cents` minus the sum of all `POSTED` payments, and
    the status is re-derived: ... a positive balance below the full patient
    responsibility is `PARTIALLY_PAID`" — the very next read reflects it.

    Design: Corner/consistency_model/payment_immediately_visible_on_invoice_read
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, _, invoice = setup_issued_invoice(external_ref="S80", charge_cents=5000)
    validate_success(
        api.create_payment(invoice["id"], create_payment_payload(2000, "CASH"),
                           billing_officer_headers),
        201,
    )
    after = get_invoice(invoice["id"])
    assert after["balance_cents"] == 3000
    assert after["status"] == "PARTIALLY_PAID"
