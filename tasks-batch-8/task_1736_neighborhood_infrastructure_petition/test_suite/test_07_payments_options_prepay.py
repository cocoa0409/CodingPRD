"""Payment option election, prepayment, OCC on assessments, and the payment
waterfall basics (PRD §3.8, §2.5, §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_payment,
    assert_same_instant,
    billing_run,
    close_objection_window,
    create_payment_payload,
    drive_to_approved,
    drive_to_billing,
    drive_to_hearing_scheduled,
    get_assessment,
    list_assessment_payments,
    list_district_assessments,
    list_district_invoices,
    make_property_owner_headers,
    record_hearing_held,
    record_resolution,
    select_payment_option,
    set_clock,
    post_payment,
    api_client,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]

FOUR_PARCEL_FRONTAGES = (50.0, 75.0, 25.0, 50.0)


def _hearing_scheduled_xd1():
    return drive_to_hearing_scheduled(
        "XD1", frontages=FOUR_PARCEL_FRONTAGES, prefix="xd1",
        methodology="FRONT_FOOT", contract_price_cents=10000000,
        contingency_cents=500000, venue="City Hall Room A",
        sign_slice=(0, 1, 3),
    )


def _levy_first_assessment(ctx):
    """Walk the district from HEARING_SCHEDULED to APPROVED; return the first
    assessment (P-001) now in LEVIED."""
    district_id = ctx["district"]["id"]
    record_hearing_held(ctx["hearing"]["id"], at="2026-08-15T10:00:00Z")
    close_objection_window(district_id, at="2026-08-31T00:00:00Z")
    record_resolution(district_id, motion="APPROVE", votes_for=3, votes_against=0)
    return list_district_assessments(district_id)[0]


class TestPaymentGatedByAssessmentState:
    def test_payment_rejected_while_assessment_preliminary(self, api):
        """PRD §3.8: "A payment posts against a payable assessment — `LEVIED`
        on the prepay path above, or `SETTLEMENT_DUE`, `IN_REPAYMENT`, or
        `DELINQUENT` on the collection path; against any other status the
        posting is refused with `ERR_ASSESSMENT_NOT_LEVIED`".

        Design: Difficulty/cross_entity_state_dependency/payment_gated_by_assessment_state
        """
        ctx = _hearing_scheduled_xd1()
        assessment = list_district_assessments(ctx["district"]["id"])[0]
        assert assessment["status"] == "PRELIMINARY"
        owner = ctx["pairs"][0][0]
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=assessment["version"],
                    amount_cents=2625000,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_LEVIED,
        )

    def test_payment_accepted_once_levied_with_prepay_option(self, api):
        """PRD §3.8: "A prepaying owner then posts a single payment equal to
        the cent to the assessment's `preliminary_amount_cents`". PRD §3.8:
        "The full amount lands on principal: `total_paid_cents` accumulates it,
        `principal_balance_cents` falls to the preliminary amount minus the
        payment — zero, pending the true-up — and the assessment becomes
        `PREPAID` with its `version` advanced."

        Design: Difficulty/cross_entity_state_dependency/payment_gated_by_assessment_state
        """
        ctx = _hearing_scheduled_xd1()
        assessment = _levy_first_assessment(ctx)
        assert assessment["status"] == "LEVIED"
        owner = ctx["pairs"][0][0]
        select_payment_option(assessment["id"], owner["id"],
                              option="PREPAY_FULL", term_years=None)
        payment = post_payment(assessment["id"], owner["id"], 2625000)
        assert_payment(payment)
        assert payment["applied_principal_cents"] == 2625000
        after = get_assessment(assessment["id"])
        assert after["status"] == "PREPAID"


class TestPaymentValidationPriority:
    def test_state_gate_beats_amount_validation(self, api):
        """PRD §2.8: "Every endpoint applies its checks in a single fixed
        priority order, and the first failure wins — later checks are never
        evaluated once an earlier one has failed." PRD §2.8: "8. **State
        preconditions** (HTTP 409): ... `ERR_ASSESSMENT_NOT_LEVIED` ..." and
        "13. **Fiscal rules, last** (HTTP 422 unless noted):
        `ERR_INVALID_AMOUNT`".

        Design: Difficulty/priority_pair_validation_conflict/payment_state_gate_beats_amount_validation
        """
        ctx = _hearing_scheduled_xd1()
        assessment = list_district_assessments(ctx["district"]["id"])[0]
        owner = ctx["pairs"][0][0]
        # The payment is both state-invalid (PRELIMINARY) and fiscally invalid
        # (amount -5); the state gate must win.
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=assessment["version"],
                    amount_cents=-5,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_LEVIED,
        )

    def test_rejected_payment_creates_no_event_and_keeps_version(self, api):
        """PRD §2.8: "Every endpoint applies its checks in a single fixed
        priority order, and the first failure wins — later checks are never
        evaluated once an earlier one has failed." PRD §3.8: "Every accepted
        payment advances the assessment's `version`."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_gate_beats_amount_validation
        """
        ctx = _hearing_scheduled_xd1()
        assessment = list_district_assessments(ctx["district"]["id"])[0]
        owner = ctx["pairs"][0][0]
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=assessment["version"],
                    amount_cents=-5,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_LEVIED,
        )
        assert list_assessment_payments(assessment["id"]) == [], (
            "no Payment resource may be created by the rejected posting"
        )
        after = get_assessment(assessment["id"])
        assert after["version"] == assessment["version"], (
            "assessment unchanged by the rejected posting"
        )


class TestPaymentOptionElection:
    def test_prepay_amount_must_equal_preliminary(self, api):
        """PRD §3.8: "A prepaying owner then posts a single payment equal to
        the cent to the assessment's `preliminary_amount_cents`; any other
        amount against a `LEVIED` assessment — or a prepay attempted without
        the `PREPAY_FULL` option in force — fails with
        `ERR_INVALID_PREPAY_AMOUNT`".

        Design: Corner/validations/v_prepay_amount_must_equal_preliminary
        """
        ctx = drive_to_approved("VPA", prefix="vpa", methodology="PER_PARCEL",
                                contract_price_cents=100000, contingency_cents=0,
                                venue="VPA Room")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        select_payment_option(assessment["id"], owner["id"],
                              option="PREPAY_FULL", term_years=None)
        version = get_assessment(assessment["id"], owner["id"])["version"]
        # Under-payment (99,999 != preliminary 100,000): only the
        # exact-equality rule is live, so ERR_INVALID_PREPAY_AMOUNT is
        # unambiguous. (An over-payment would also trip ERR_OVERPAYMENT,
        # which PRD §2.8 lists ahead of ERR_INVALID_PREPAY_AMOUNT in the
        # level-13 fiscal order, making the winner under-determined there.)
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=version,
                    amount_cents=99999,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_INVALID_PREPAY_AMOUNT,
        )
        payment = post_payment(assessment["id"], owner["id"], 100000)
        assert payment["applied_principal_cents"] == 100000

    def test_installment_term_restricted(self, api):
        """PRD §3.8: "Choosing `INSTALLMENTS` requires a `term_years` of 5 or
        10, while `PREPAY_FULL` forbids it outright; a missing,
        present-but-wrong, or misplaced term draws `ERR_TERM_NOT_ALLOWED`."

        Design: Corner/validations/v_installment_term_restricted
        """
        ctx = drive_to_approved("VTR", prefix="vtr", methodology="PER_PARCEL",
                                contract_price_cents=100000, contingency_cents=0,
                                venue="VTR Room")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        validate_error(
            api_client.select_payment_option(
                assessment["id"], {"option": "INSTALLMENTS", "term_years": 7},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_TERM_NOT_ALLOWED,
        )
        validate_error(
            api_client.select_payment_option(
                assessment["id"], {"option": "PREPAY_FULL", "term_years": 5},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_TERM_NOT_ALLOWED,
        )
        selected = validate_success(
            api_client.select_payment_option(
                assessment["id"], {"option": "INSTALLMENTS", "term_years": 5},
                make_property_owner_headers(owner["id"]),
            )
        )
        assert selected["payment_option"] == "INSTALLMENTS"
        assert selected["term_years"] == 5

    def test_option_selection_once_only(self, api):
        """PRD §3.8: "the option may be chosen at most once
        (`ERR_ASSESSMENT_OPTION_ALREADY_SELECTED`)".

        Design: Corner/state_machines/sm_option_selection_once_only
        """
        ctx = drive_to_approved("SOS2", prefix="sos2", methodology="PER_PARCEL",
                                contract_price_cents=100000, contingency_cents=0,
                                venue="SOS2 Room")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        select_payment_option(assessment["id"], owner["id"],
                              option="PREPAY_FULL", term_years=None)
        validate_error(
            api_client.select_payment_option(
                assessment["id"], {"option": "INSTALLMENTS", "term_years": 5},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_ASSESSMENT_OPTION_ALREADY_SELECTED,
        )

    def test_payment_option_window_boundary(self, api):
        """PRD §3.8: "While the current time is on or before the district's
        `payment_option_deadline` — afterwards the window is shut and election
        attempts fail with `ERR_PAYMENT_OPTION_WINDOW_CLOSED`". PRD §3.5:
        "every `PRELIMINARY` assessment becomes `LEVIED`, the district's
        `levy_date` is stamped with the current time, and
        `payment_option_deadline` is fixed at thirty days after the levy."

        Design: Corner/errors/err_payment_option_window_closed_triggered
        """
        ctx = drive_to_approved("EPO", frontages=(100.0, 100.0), prefix="epo",
                                methodology="PER_PARCEL", contract_price_cents=100000,
                                contingency_cents=0, venue="EPO Room")
        assessments = ctx["assessments"]
        # Levy stamped at 2026-08-31T00:00:00Z -> deadline 2026-09-30T00:00:00Z.
        district = api_client.get_district(ctx["district"]["id"], FINANCE).json()["data"]
        assert_same_instant(district["payment_option_deadline"],
                            "2026-09-30T00:00:00Z", "payment_option_deadline")

        o1 = ctx["pairs"][0][0]
        o2 = ctx["pairs"][1][0]
        set_clock("2026-09-30T00:00:00Z")  # exactly the deadline (inclusive)
        selected = validate_success(
            api_client.select_payment_option(
                assessments[0]["id"], {"option": "INSTALLMENTS", "term_years": 5},
                make_property_owner_headers(o1["id"]),
            )
        )
        assert selected["payment_option"] == "INSTALLMENTS"

        set_clock("2026-10-01T00:00:01Z")  # one second past the deadline
        validate_error(
            api_client.select_payment_option(
                assessments[1]["id"], {"option": "PREPAY_FULL"},
                make_property_owner_headers(o2["id"]),
            ),
            ApiErrorId.ERR_PAYMENT_OPTION_WINDOW_CLOSED,
        )


class TestPaymentAmountRules:
    def _billing_with_issued_invoice(self, name, prefix):
        ctx = drive_to_billing(name, prefix=prefix, methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue=f"{name} Room", option="INSTALLMENTS",
                               term_years=5)
        set_clock("2027-09-20T00:00:00Z")  # issue the year-1 invoice
        billing_run(ctx["district"]["id"])
        return ctx

    def test_overpayment_above_payoff_rejected(self, api):
        """PRD §3.8: "The amount may not exceed the payoff quote computed at
        receipt time; an excess is rejected with `ERR_OVERPAYMENT`
        (HTTP 402)."

        Design: Corner/validations/v_overpayment_above_payoff_rejected
        """
        ctx = self._billing_with_issued_invoice("VOP", "vop")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        set_clock("2027-10-20T00:00:00Z")
        # Payoff at the year-1 due date: principal 100,000 + one full year of
        # accrued interest 4,000 = 104,000.
        version = get_assessment(assessment["id"], owner["id"])["version"]
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=version,
                    amount_cents=104001,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_OVERPAYMENT,
        )

    def test_zero_amount_payment_rejected(self, api):
        """PRD §3.8: "carrying `parcel_assessment_id`, a strictly positive
        `amount_cents` (`ERR_INVALID_AMOUNT`), and a `method` of `CHECK`,
        `ACH`, or `CARD`."

        Design: Corner/errors/err_invalid_amount_zero_payment
        """
        ctx = self._billing_with_issued_invoice("EIA", "eia")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        version = get_assessment(assessment["id"], owner["id"])["version"]
        validate_error(
            api_client.create_payment(
                create_payment_payload(
                    parcel_assessment_id=assessment["id"],
                    expected_parcel_assessment_version=version,
                    amount_cents=0,
                ),
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_INVALID_AMOUNT,
        )


class TestPaymentConcurrencyAndConsistency:
    def test_payment_stale_assessment_version_rejected(self, api):
        """PRD §2.7: "Posting a payment requires
        `expected_parcel_assessment_version` equal to the assessment's current
        `version`." and "a mismatch with the parent's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from
        writing against a state of the aggregate it has not observed."

        Design: Corner/cross_cutting_complexity_layers/x_occ_payment_stale_assessment_version
        """
        ctx = drive_to_billing("XOC3", prefix="xoc3", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="XOC3 Room", option="INSTALLMENTS", term_years=5)
        set_clock("2027-09-20T00:00:00Z")
        billing_run(ctx["district"]["id"])
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        version = get_assessment(assessment["id"], owner["id"])["version"]
        payload = create_payment_payload(
            parcel_assessment_id=assessment["id"],
            expected_parcel_assessment_version=version,
            amount_cents=5000,
        )
        validate_success(
            api_client.create_payment(payload, make_property_owner_headers(owner["id"])),
            expected_status=201,
        )
        # The first payment advanced the assessment version; the replayed
        # version is now stale.
        validate_error(
            api_client.create_payment(payload, make_property_owner_headers(owner["id"])),
            ApiErrorId.ERR_STALE_VERSION,
        )
        after = get_assessment(assessment["id"])
        assert after["total_paid_cents"] == 5000, (
            "balance reflects exactly one applied payment"
        )

    def test_immediate_read_after_write_payment(self, api):
        """PRD §3.8: "Billed invoices are filled first, oldest `due_date` first
        with creation-time tie-breaks, and within each invoice the order is
        penalty, then interest, then principal; an invoice moves `ISSUED` →
        `PARTIALLY_PAID` → `PAID` as it fills". PRD §3.8: "the waterfall
        records how the money split across `applied_penalty_cents`,
        `applied_interest_cents`, and `applied_principal_cents`."

        Design: Corner/consistency_model/k_immediate_read_after_write_payment
        """
        ctx = drive_to_billing("KIM", prefix="kim", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="KIM Room", option="INSTALLMENTS", term_years=5)
        set_clock("2027-09-20T00:00:00Z")
        billing_run(ctx["district"]["id"])
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]

        payment = post_payment(assessment["id"], owner["id"], 5000)
        # Year-1 invoice: 4,000 interest + 18,463 principal.
        assert payment["applied_interest_cents"] == 4000
        assert payment["applied_principal_cents"] == 1000
        assert payment["applied_penalty_cents"] == 0

        after = get_assessment(assessment["id"])
        assert after["principal_balance_cents"] == 99000
        assert after["total_paid_cents"] == 5000

        invoice = list_district_invoices(ctx["district"]["id"])[0]
        assert invoice["status"] == "PARTIALLY_PAID"
        assert invoice["paid_cents"] == 5000

    def test_payment_event_has_no_version(self, api):
        """PRD §2.5: "The single exception is the **Payment**: a payment is an
        append-only event and carries only `id` and `created_at` —
        `updated_at` and `version` are absent, because a payment is never
        modified after posting."

        Design: Corner/entities/e_payment_event_has_no_version
        """
        ctx = drive_to_billing("EIM", prefix="eim", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="EIM Room", option="INSTALLMENTS", term_years=5)
        set_clock("2027-09-20T00:00:00Z")
        billing_run(ctx["district"]["id"])
        set_clock("2027-10-20T00:00:00Z")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]

        response = api_client.create_payment(
            create_payment_payload(
                parcel_assessment_id=assessment["id"],
                expected_parcel_assessment_version=get_assessment(
                    assessment["id"], owner["id"])["version"],
                amount_cents=104000,
            ),
            make_property_owner_headers(owner["id"]),
        )
        payment = validate_success(response, expected_status=201)
        assert_payment(payment)  # asserts absence of version/updated_at
        assert "version" not in payment and "updated_at" not in payment

        fetched = validate_success(api_client.get_payment(payment["id"], FINANCE))
        assert fetched["amount_cents"] == 104000
        assert "version" not in fetched and "updated_at" not in fetched
        assert fetched["id"] == payment["id"]
        assert fetched["created_at"] == payment["created_at"]
