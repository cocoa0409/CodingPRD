"""Post-acceptance enrollment change events and rate-guarantee handling."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    add_enrollment_event,
    setup_approved_case,
    setup_case_with_proposed_quote,
    make_broker_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestEnrollmentThresholdBoundary:
    def test_enrollment_change_exact_threshold_not_voided(self):
        """PRD section 3.8: "When the absolute value of `enrollment_change_pct`
        is at most the quote's `enrollment_change_threshold`, the guarantee
        holds: the event becomes `PROCESSED`, `guarantee_voided` is false, and
        `rate_adjustment_factor` is exactly 1.0."
        PRD section 3.8: "Processing computes the `revised_enrollment` as the
        census `enrolled_employees` plus the event's `change_count`, and the
        `enrollment_change_pct` as `change_count` divided by
        `enrolled_employees`, rounded half-up to four decimal places."

        Design: Difficulty/boundary_precision_check/enrollment_change_exact_threshold_not_voided
        """
        broker, case, plan, quote, disc = setup_approved_case()
        event = add_enrollment_event(case["id"], quote["id"], change_count=40)
        data = validate_success(
            api_client.process_enrollment_change(event["id"], UW)
        )
        # 40 / 400 = 0.1000, exactly at the 0.10 threshold -> not voided.
        assert data["status"] == "PROCESSED"
        assert data["enrollment_change_pct"] == pytest.approx(0.1, abs=1e-9)
        assert data["guarantee_voided"] is False
        assert data["rate_adjustment_factor"] == pytest.approx(1.0, abs=1e-9)
        assert data["revised_enrollment"] == 440
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["pepm_rate_cents"] == 5338

    def test_enrollment_change_just_below_threshold_processed(self):
        """PRD section 3.8: "When the absolute value of `enrollment_change_pct`
        is at most the quote's `enrollment_change_threshold`, the guarantee
        holds: the event becomes `PROCESSED`, `guarantee_voided` is false, and
        `rate_adjustment_factor` is exactly 1.0."

        Design: Difficulty/boundary_precision_check/enrollment_change_exact_threshold_not_voided
        """
        broker, case, plan, quote, disc = setup_approved_case()
        # 39 / 400 = 0.0975 < 0.10 -> comfortably inside the threshold.
        event = add_enrollment_event(case["id"], quote["id"], change_count=39)
        data = validate_success(
            api_client.process_enrollment_change(event["id"], UW)
        )
        assert data["status"] == "PROCESSED"
        assert data["enrollment_change_pct"] == pytest.approx(0.0975, abs=1e-9)
        assert data["guarantee_voided"] is False
        assert data["rate_adjustment_factor"] == pytest.approx(1.0, abs=1e-9)
        assert data["revised_enrollment"] == 439


class TestEnrollmentVoidAndCeilStep:
    def test_enrollment_void_first_ceil_step(self):
        """PRD section 3.8: "When the absolute change exceeds the threshold, the
        guarantee is voided: `guarantee_voided` is set true, the event becomes
        `VOIDED_GUARANTEE`, and the rate adjusts upward by 2 percent for every 5
        percent of excess swing beyond the threshold — the excess measured as the
        absolute change percentage minus the threshold, divided into 0.05 bands
        rounded up to a whole band count, each band adding 0.02 to a base factor
        of 1.0."

        Design: Corner/calculations/enrollment_void_and_ceil_step
        """
        broker, case, plan, quote, disc = setup_approved_case()
        # 41 / 400 = 0.1025; excess 0.0025 -> ceil(0.0025/0.05) = 1 -> 1.02
        event = add_enrollment_event(case["id"], quote["id"], change_count=41)
        data = validate_success(
            api_client.process_enrollment_change(event["id"], UW)
        )
        assert data["status"] == "VOIDED_GUARANTEE"
        assert data["enrollment_change_pct"] == pytest.approx(0.1025, abs=1e-9)
        assert data["guarantee_voided"] is True
        assert data["rate_adjustment_factor"] == pytest.approx(1.02, abs=1e-9)
        assert data["revised_enrollment"] == 441

    def test_enrollment_void_second_ceil_step(self):
        """PRD section 3.8: "the rate adjusts upward by 2 percent for every 5
        percent of excess swing beyond the threshold — the excess measured as the
        absolute change percentage minus the threshold, divided into 0.05 bands
        rounded up to a whole band count, each band adding 0.02 to a base factor
        of 1.0."

        Design: Corner/calculations/enrollment_void_and_ceil_step
        """
        broker, case, plan, quote, disc = setup_approved_case()
        # 61 / 400 = 0.1525; excess 0.0525 -> ceil(0.0525/0.05) = 2 -> 1.04
        event = add_enrollment_event(
            case["id"], quote["id"], change_count=61,
            event_type="PLAN_MIGRATION", headers=make_broker_headers(broker["id"]),
        )
        data = validate_success(
            api_client.process_enrollment_change(event["id"], UW)
        )
        assert data["status"] == "VOIDED_GUARANTEE"
        assert data["enrollment_change_pct"] == pytest.approx(0.1525, abs=1e-9)
        assert data["rate_adjustment_factor"] == pytest.approx(1.04, abs=1e-9)
        assert data["revised_enrollment"] == 461


class TestEnrollmentGuards:
    def test_process_enrollment_event_twice_fails(self):
        """PRD section 3.8: "the event must be `REPORTED` (else
        `ERR_ENROLLMENT_NOT_REPORTED`)".

        Design: Corner/state_machines/process_enrollment_event_twice_fails
        """
        broker, case, plan, quote, disc = setup_approved_case()
        event = add_enrollment_event(
            case["id"], quote["id"], change_count=20,
            headers=make_broker_headers(broker["id"]),
        )
        first = validate_success(
            api_client.process_enrollment_change(event["id"], UW)
        )
        assert first["status"] == "PROCESSED"
        resp = api_client.process_enrollment_change(event["id"], UW)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_REPORTED)
        event = get_success_data(api_client.get_enrollment_change(event["id"], UW))
        assert event["status"] == "PROCESSED"
        assert event["revised_enrollment"] == 420
        assert event["enrollment_change_pct"] == pytest.approx(0.05, abs=1e-9)

    def test_process_enrollment_before_approval_fails(self):
        """PRD section 3.8: "Processing is the underwriter's job and is gated
        twice: the event must be `REPORTED` (else `ERR_ENROLLMENT_NOT_REPORTED`)
        and the parent case must be `APPROVED` (else `ERR_CASE_NOT_APPROVED`)."

        Design: Corner/validations/process_enrollment_before_approval_fails
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        event = add_enrollment_event(case["id"], quote["id"], change_count=5)
        resp = api_client.process_enrollment_change(event["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_APPROVED)
        event = get_success_data(api_client.get_enrollment_change(event["id"], UW))
        assert event["status"] == "REPORTED"
