"""The balance as an unfiltered sum over the ledger, the payment boundary that may not be
crossed by a single cent, and the processing-transparency figures a read recomputes from
the logical clock."""

import pytest

from test_helpers import (
    APP_DENIED,
    DECISION_DENY,
    DEPUTY_HEADERS,
    ENTRY_ASSESSMENT,
    ENTRY_PAYMENT,
    ENTRY_WAIVER_CREDIT,
    ApiErrorId,
    assert_application_fields,
    assert_ledger_signature,
    decision_payload,
    ledger_sum,
    make_applicant_headers,
    payment_payload,
    validate_error,
    validate_success,
)


@pytest.fixture
def submitted_with_forty_eight_thousand_outstanding(setup):
    """A non-military nursing endorsement submitted at the startup instant, carrying the
    full unwaived assessment of 48000 cents and a two-row ledger."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Zeke Duarte")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-13004",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    return {"ap_id": applicant["id"], "app_id": application["id"]}


@pytest.fixture
def under_review_forty_five_days_in(setup):
    """A nursing endorsement submitted at 2026-08-01, moved under review, with the logical
    clock then wound forward 45 days to 2026-09-15 — still inside the 90-day standard."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Anya Kolar")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-13005",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.evaluation(application["id"], credential["id"])
    setup.set_clock("2026-09-15T00:00:00Z")
    return {"app_id": application["id"]}


class TestFeeBalanceAggregation:
    def test_two_partial_payments_walk_the_balance_down_to_zero(
        self, api, submitted_with_forty_eight_thousand_outstanding, setup
    ):
        """PRD §2.10: "An application's `fee_balance_cents` is, by construction, the
        arithmetic sum of the `amount_cents` of every ledger entry whose `application_id`
        is that application."  PRD §2.10: "There is no status filter on the sum and no
        notion of a voided entry, because entries are immutable; the read order of
        `created_at` ascending pins the audit trail but does not change the total."  PRD
        §3.4: "Each payment appends a `PAYMENT` entry whose `amount_cents` is the negative
        of the amount tendered, recomputes `fee_balance_cents`, and increments the
        application's `version`."

        Design: Corner/calculations/fee_balance_aggregation_is_running_sum_over_ledger
        """
        env = submitted_with_forty_eight_thousand_outstanding
        headers = make_applicant_headers(env["ap_id"])

        validate_success(api.create_payment(env["app_id"], payment_payload(20000), headers), 201)
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=28000
        )

        validate_success(api.create_payment(env["app_id"], payment_payload(28000), headers), 201)
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=0)

        ledger = setup.read_ledger(env["app_id"])
        assert_ledger_signature(
            ledger,
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -20000),
                (ENTRY_PAYMENT, -28000),
            ],
        )
        assert ledger_sum(ledger) == 0
        assert setup.ledger_meta(env["app_id"], entry_type=ENTRY_PAYMENT)["total_count"] == 2

    def test_a_payment_one_cent_over_the_balance_is_refused_outright(
        self, api, submitted_with_forty_eight_thousand_outstanding, setup
    ):
        """PRD §3.4: "An applicant settles the balance by recording payments, each of
        which supplies an `amount_cents` that must be strictly positive and, per check 37,
        at most the application's current `fee_balance_cents` — overpayment is refused
        with `ERR_PAYMENT_EXCEEDS_BALANCE`, so the ledger can never be driven
        credit-positive by a payment."  PRD §2.8: "No overpayment — a payment's
        `amount_cents` is at most the application's current `fee_balance_cents`.
        `ERR_PAYMENT_EXCEEDS_BALANCE`, 422. Applies to recording a payment."

        Design: Corner/calculations/payment_exceeding_balance_rejected
        """
        env = submitted_with_forty_eight_thousand_outstanding
        response = api.create_payment(
            env["app_id"], payment_payload(48001), make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)

        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=48000
        )
        assert setup.ledger_meta(env["app_id"], entry_type=ENTRY_PAYMENT)["total_count"] == 0
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2

    def test_a_payment_of_exactly_the_balance_is_admitted_at_the_boundary(
        self, api, submitted_with_forty_eight_thousand_outstanding, setup
    ):
        """PRD §2.8: "No overpayment — a payment's `amount_cents` is at most the
        application's current `fee_balance_cents`. `ERR_PAYMENT_EXCEEDS_BALANCE`, 422.
        Applies to recording a payment."  PRD §3.4: "The payment operation returns the
        ledger entry it created rather than the application."

        Design: Corner/calculations/payment_equal_to_balance_zeroes_the_ledger
        """
        env = submitted_with_forty_eight_thousand_outstanding
        entry = validate_success(
            api.create_payment(
                env["app_id"], payment_payload(48000), make_applicant_headers(env["ap_id"])
            ),
            201,
        )

        assert entry["entry_type"] == ENTRY_PAYMENT
        assert entry["amount_cents"] == -48000
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=0)
        assert setup.ledger_meta(env["app_id"])["total_count"] == 3


class TestProcessingTransparencyFigures:
    def test_an_undecided_file_counts_whole_days_against_the_live_clock(
        self, under_review_forty_five_days_in, setup
    ):
        """PRD §3.4: "The reference instant is the application's `decided_at` when a
        decision has been issued, and the current logical clock while the application is
        still undecided."  PRD §3.4: "`processing_elapsed_days` is 0 whenever
        `submitted_at` is null, and is otherwise the number of whole days from
        `submitted_at` to that reference instant, discarding any partial day."  PRD §3.4:
        "`processing_standard_met` is null while `decided_at` is null, and once a decision
        exists it is true exactly when `decided_at` is at or before `review_deadline_at`."

        Design: Corner/calculations/processing_time_metrics_recomputed_from_submitted_at
        """
        env = under_review_forty_five_days_in

        assert_application_fields(
            setup.read_application(env["app_id"]),
            processing_elapsed_days=45,
            processing_standard_met=None,
            decided_at=None,
            review_deadline_at="2026-10-30T00:00:00Z",
        )

    def test_a_denial_pins_the_metrics_to_the_decision_instant(
        self, api, under_review_forty_five_days_in, setup
    ):
        """PRD §3.4: "Every read of a single application refreshes its
        processing-transparency figures from the logical clock, without incrementing
        `version` or touching `updated_at`."  PRD §3.4: "`processing_standard_met` is null
        while `decided_at` is null, and once a decision exists it is true exactly when
        `decided_at` is at or before `review_deadline_at`."

        Design: Corner/calculations/processing_time_metrics_recomputed_from_submitted_at
        """
        env = under_review_forty_five_days_in
        validate_success(
            api.issue_decision(
                env["app_id"],
                decision_payload(DECISION_DENY, memo="credential scope insufficient"),
                DEPUTY_HEADERS,
            ),
            200,
        )

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_DENIED,
            decided_at="2026-09-15T00:00:00Z",
            processing_elapsed_days=45,
            processing_standard_met=True,
            review_deadline_at="2026-10-30T00:00:00Z",
        )
