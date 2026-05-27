"""Corner (calculations) — additional boundaries on filing fee, RFE deadline,
and visa availability."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    publish_visa_bulletin,
    register_applicant,
    create_draft_case,
    file_case,
    make_applicant_headers,
    make_officer_headers,
    setup_under_review_i130,
    schedule_biometrics_for,
    rfe_respond_payload,
    issue_rfe_payload,
)


class TestFilingFeeI130NoBiometricsSurcharge:

    def test_i130_adult_filing_fee_is_56000(self, api):
        """PRD §3.2: "The base fee in whole cents is fixed per case type: an `I-130` is
        56,000 cents (560 dollars)"
        PRD §3.2: "A biometrics surcharge of 8,500 cents (85 dollars) is added when the
        case type is `I-485`, `I-765`, or `I-131`; the `I-130` case type skips
        biometrics in this scope (see §3.3) and therefore carries no surcharge."

        Design: Corner/calculations/filing_fee_i130_no_biometrics_surcharge
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant(date_of_birth="1985-01-01")
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        filed = file_case(case, applicant)
        assert filed["filing_fee_cents"] == 56_000


class TestFilingFeeI485AdultWithSurchargeNoDiscount:

    def test_i485_adult_filing_fee_is_150500(self, api):
        """PRD §3.2: "an `I-485` is 142,000 cents (1,420 dollars)"
        PRD §3.2: "A biometrics surcharge of 8,500 cents (85 dollars) is added when the
        case type is `I-485`, `I-765`, or `I-131`"
        PRD §3.2: "In every other configuration, no discount applies and the fee equals
        the subtotal (already a whole-cent integer)."

        Design: Corner/calculations/filing_fee_i485_adult_with_surcharge_no_discount
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant(date_of_birth="1990-01-01")
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        # 142_000 + 8_500 = 150_500; adult → no discount.
        assert filed["filing_fee_cents"] == 150_500


class TestRfeDeadlineCalendarDayArithmetic:

    def test_response_at_one_day_before_deadline_succeeds(self, api):
        """PRD §3.6: "The `response_deadline` stamped at issuance is exactly 87 calendar days
        after `issued_at`."
        PRD §3.6: "a response submitted when `ClockState.current_utc` is strictly less than
        `response_deadline` is accepted"

        Design: Corner/calculations/rfe_deadline_calendar_day_arithmetic_one_day_before_expiry_passes
        """
        # Setup: I-130 → UNDER_REVIEW → issue RFE at 2026-06-15.
        applicant, case_ur, officer = setup_under_review_i130(
            file_date_iso="2026-06-15T00:00:00Z"
        )
        rfe = get_success_data(api.issue_rfe(
            case_ur["id"], issue_rfe_payload(["doc_x"]), officer
        ))
        # 2026-06-15 + 87 days = 2026-09-10 per PRD §3.6.
        assert rfe["response_deadline"] == "2026-09-10"

        set_clock("2026-09-09T00:00:00Z")
        case_v = get_success_data(api.get_case(case_ur["id"], officer))
        applicant_headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_v["version"], "Just-in-time response"),
            applicant_headers,
        )
        validate_success(res, 200)
        case_after = get_success_data(api.get_case(case_ur["id"], officer))
        assert case_after["status"] == "UNDER_REVIEW"


class TestRfeDeadlineExactEqualityRejected:

    def test_response_at_exact_deadline_returns_deadline_passed(self, api):
        """PRD §3.6: "a response submitted when `ClockState.current_utc` is at or after
        `response_deadline` is rejected with `ERR_RFE_DEADLINE_PASSED`. Equality
        counts as late."

        Design: Corner/calculations/rfe_deadline_breach_at_exact_deadline_returns_error
        """
        applicant, case_ur, officer = setup_under_review_i130(
            file_date_iso="2026-06-15T00:00:00Z"
        )
        rfe = get_success_data(api.issue_rfe(
            case_ur["id"], issue_rfe_payload(["doc_y"]), officer
        ))
        # Move clock to exactly the response deadline.
        set_clock("2026-09-10T00:00:00Z")
        case_v = get_success_data(api.get_case(case_ur["id"], officer))
        applicant_headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_v["version"], "Exact-second response"),
            applicant_headers,
        )
        validate_error(res, "ERR_RFE_DEADLINE_PASSED")


class TestVisaAvailabilityCurrentKeywordShortCircuits:

    def test_cutoff_current_keyword_always_returns_current(self, api):
        """PRD §3.4: "if its `cutoff_date` equals `CURRENT`, the result is `CURRENT`"

        Design: Corner/calculations/visa_availability_current_keyword_short_circuits
        """
        set_clock("2026-06-15T00:00:00Z")
        publish_visa_bulletin("2026-06", "IR", "WORLDWIDE",
                              "FINAL_ACTION", "CURRENT")
        publish_visa_bulletin("2026-06", "IR", "WORLDWIDE",
                              "FILING_DATE", "CURRENT")
        applicant = register_applicant(country_of_chargeability="WORLDWIDE")
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        filed = file_case(case, applicant)
        headers = make_applicant_headers(applicant["id"])
        res = api.get_visa_availability(filed["id"], headers)
        body = validate_success(res, 200)
        assert body["final_action"] == "CURRENT"
        assert body["filing_date"] == "CURRENT"
