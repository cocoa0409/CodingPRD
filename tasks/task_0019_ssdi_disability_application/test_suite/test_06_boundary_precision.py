"""Boundary precision: SSI resource limit (strict > $2000); ALJ hearing
lead time (≥ 75 days)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_awarded,
    setup_hearing_in_requested,
    schedule_hearing_payload,
)


# =========================================================================
# Instance: ssi_resource_limit_strict_inequality_at_200000_cents
# =========================================================================

class TestSsiResourceLimitStrictInequalityAt200000Cents:
    """Strict-inequality boundary on countable_resources_cents. At exactly
    200_000 → ACTIVE; at 200_001 → INELIGIBLE_RESOURCES."""

    def test_resources_at_200001_cents_returns_ineligible(self, api):
        """PRD §3.7: "If the claimant's `countable_resources_cents` is
        strictly greater than 200000 cents — the federal SSI resource
        limit of $2,000.00, applied with strict boundary precision — the
        supplement is created in `status` of `INELIGIBLE_RESOURCES`, both
        `monthly_supplement_cents` and `state_supplement_cents` are zeroed,
        and no further computation runs."

        Design: Difficulty/boundary_precision_check/ssi_resource_limit_strict_inequality_at_200000_cents
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "8080",
                "full_name": "Border Resource",
                "date_of_birth": "1985-01-01T00:00:00Z",
                "filing_state": "TX",
                "monthly_income_cents": 0,
                "countable_resources_cents": 200_001,
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
            earnings_cents=1_200_000,
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        app = ctx["application"]
        res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                               params={"application_id": app["id"]})
        sups = get_success_data(res)
        assert len(sups) == 1
        sup = sups[0]
        assert sup["status"] == "INELIGIBLE_RESOURCES", \
            f"Expected INELIGIBLE_RESOURCES at 200001 cents, got {sup['status']}"
        assert sup["monthly_supplement_cents"] == 0

    def test_resources_at_exactly_200000_cents_passes_resource_test(self, api):
        """PRD §3.7: "A claimant whose countable resources are exactly
        200000 cents passes the test."

        Design: Difficulty/boundary_precision_check/ssi_resource_limit_strict_inequality_at_200000_cents
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "8081",
                "full_name": "On Limit",
                "date_of_birth": "1985-01-01T00:00:00Z",
                "filing_state": "TX",
                "monthly_income_cents": 0,
                "countable_resources_cents": 200_000,
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
            earnings_cents=1_200_000,
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        app = ctx["application"]
        res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                               params={"application_id": app["id"]})
        sups = get_success_data(res)
        assert len(sups) == 1
        sup = sups[0]
        assert sup["status"] != "INELIGIBLE_RESOURCES", \
            f"At exactly 200000 cents the resource gate must pass; got {sup['status']}"


# =========================================================================
# Instance: hearing_lead_time_exact_74_days_rejected_endpoint_schedule
# =========================================================================

class TestHearingLeadTimeExact74DaysRejectedEndpointSchedule:
    """Temporal-interval boundary on the hearing lead time. At 74 days →
    rejected with ERR_HEARING_LEAD_TIME. At ≥75 days → accepted."""

    def test_74_day_lead_time_rejected(self, api):
        """PRD §3.5: "the supplied `scheduled_date` must be at least 75
        days after the hearing's server-recorded `requested_date` — that
        is, `scheduled_date` is on or after `requested_date` plus 75 days.
        A `scheduled_date` that is earlier than that threshold is rejected
        with `ERR_HEARING_LEAD_TIME` (422)."

        Design: Difficulty/boundary_precision_check/hearing_lead_time_exact_74_days_rejected_endpoint_schedule
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "9090",
                "full_name": "Lead Time",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        # requested_date is at 2026-01-15 (current clock). 74 days later = 2026-03-30.
        payload = schedule_hearing_payload("2026-03-30T00:00:00Z")
        res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["alj_headers"])
        validate_error(res, "ERR_HEARING_LEAD_TIME", expected_status=422)

    def test_75_day_lead_time_accepted(self, api):
        """PRD §3.5: "the supplied `scheduled_date` must be at least 75
        days after the hearing's server-recorded `requested_date` — that
        is, `scheduled_date` is on or after `requested_date` plus 75 days."
        PRD §3.5: "On success, the server sets the hearing's `status` to
        `SCHEDULED`, stamps the calling judge's `X-User-ID` into
        `alj_user_id`, persists the supplied `scheduled_date`, and
        increments the hearing's `version`."

        Design: Difficulty/boundary_precision_check/hearing_lead_time_exact_74_days_rejected_endpoint_schedule
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "9091",
                "full_name": "Lead Time OK",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        # 75 days after 2026-01-15 = 2026-03-31.
        payload = schedule_hearing_payload("2026-03-31T00:00:00Z")
        res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["alj_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SCHEDULED"
