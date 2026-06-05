"""Corner — validations section: intermittent-cert required, hours-per-episode
cap, recert-too-soon, payment-amount bounds.
"""
from test_helpers import (
    apply_payment_payload,
    ApiErrorId,
    list_benefit_ledgers_for_case,
    receive_certification,
    request_recertification,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
    setup_case_in_certification_pending,
    submit_certification,
    TEST_USERS,
    validate_error,
)


class TestIntermittentCertRequiredFieldsMissing:
    def test_mark_complete_on_intermittent_cert_without_required_fields_returns_intermittent_cert_required(self, api):
        """PRD §3.5: "Marking complete advances `RECEIVED` to `COMPLETE`, but only when (a) for an `INTERMITTENT` or `REDUCED_SCHEDULE` case, both `intermittent_frequency_per_month` is at least one and `intermittent_hours_per_episode` is strictly greater than zero — otherwise `ERR_INTERMITTENT_CERT_REQUIRED` is returned"

        Design: Corner/validations/intermittent_cert_required_fields_missing
        """
        base = setup_case_in_certification_pending(
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="INTERMITTENT",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-12-01T00:00:00.000Z",
        )
        cert = submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=26,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
            # intermittent_frequency_per_month + intermittent_hours_per_episode omitted
        )
        receive_certification(cert["id"])
        res = api.mark_certification_complete(
            cert["id"], TEST_USERS["hr_admin_headers"]
        )
        validate_error(res, ApiErrorId.ERR_INTERMITTENT_CERT_REQUIRED)


class TestIntermittentHoursPerEpisodeExceeded:
    def test_interval_hours_taken_exceeds_certified_per_episode_returns_hours_exceeded(self, api):
        """PRD §3.6: "For those same cases, `hours_taken` on a single interval must not exceed the certification's `intermittent_hours_per_episode` — otherwise `ERR_INTERMITTENT_HOURS_EXCEEDED`."

        Design: Corner/validations/intermittent_hours_per_episode_exceeded
        """
        bundle = setup_approved_case(
            employer_state="FED",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="INTERMITTENT",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-12-01T00:00:00.000Z",
            cert_expected_duration_weeks=26,
            cert_intermittent_frequency_per_month=4,
            cert_intermittent_hours_per_episode=8,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        from test_helpers import create_interval_payload

        res = api.create_interval(
            create_interval_payload(
                bundle.case["id"],
                "2026-06-02T00:00:00.000Z",
                "2026-06-02T10:00:00.000Z",
                10,  # > 8
            ),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INTERMITTENT_HOURS_EXCEEDED)


class TestRecertTooSoon:
    def test_recertification_request_within_30_days_returns_recert_too_soon(self, api):
        """PRD §3.5: "Recertification is opened by an HR officer against an `APPROVED` or `ACTIVE` case. The request is rejected with `ERR_RECERT_TOO_SOON` if fewer than thirty days have elapsed since the prior `COMPLETE` certification's `received_at`."

        Design: Corner/validations/recert_too_soon
        """
        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-09-01T00:00:00.000Z",
            cert_expected_duration_weeks=12,
            # received_at stamped during fixture; default clock at receive is the
            # submission clock 2026-05-01.
        )
        # The fixture's mark-receive happened at 2026-05-01 (submission_clock).
        # Advance clock to less than 30 days later than that → recert too soon.
        set_clock("2026-05-15T00:00:00.000Z")
        res = api.request_recertification(
            bundle.case["id"], TEST_USERS["hr_admin_headers"]
        )
        validate_error(res, ApiErrorId.ERR_RECERT_TOO_SOON)


class TestPaymentAmountZeroOrNegative:
    def test_apply_payment_zero_amount_returns_invalid_payment_amount(self, api):
        """PRD §3.7: "An HR officer applies a payment to a ledger row by supplying `amount_cents`. The amount must be strictly greater than zero and at most the row's outstanding balance — `employee_premium_share_cents` minus `payments_received_cents`. A negative, zero, or over-balance amount is rejected with `ERR_INVALID_PAYMENT_AMOUNT`."

        Design: Corner/validations/payment_amount_zero_or_negative
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            monthly_premium_total_cents=10000,
            employer_premium_share_pct=0.50,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-07-01T00:00:00.000Z",
            interval_hours=160,
        )
        ledgers = list_benefit_ledgers_for_case(bundle["case"]["id"])
        ledger_id = ledgers[0]["id"]
        res = api.apply_payment(
            ledger_id, apply_payment_payload(0), TEST_USERS["hr_admin_headers"]
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)


class TestPaymentAmountOverBalance:
    def test_apply_payment_over_balance_returns_invalid_payment_amount(self, api):
        """PRD §3.7: "The amount must be strictly greater than zero and at most the row's outstanding balance — `employee_premium_share_cents` minus `payments_received_cents`. A negative, zero, or over-balance amount is rejected with `ERR_INVALID_PAYMENT_AMOUNT`."

        Design: Corner/validations/payment_amount_over_balance
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            monthly_premium_total_cents=10000,
            employer_premium_share_pct=0.50,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-07-01T00:00:00.000Z",
            interval_hours=160,
        )
        ledgers = list_benefit_ledgers_for_case(bundle["case"]["id"])
        ledger_id = ledgers[0]["id"]
        # Balance is 5000; submit 999999 (way over).
        res = api.apply_payment(
            ledger_id,
            apply_payment_payload(999999),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)
