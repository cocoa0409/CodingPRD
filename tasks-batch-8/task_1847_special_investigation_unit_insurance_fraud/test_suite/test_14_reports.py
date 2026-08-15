"""Regulatory report creation and period validation."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_compliance_headers, create_report_payload,
)
from test_helpers.api_client import api_client


class TestReportPeriod:
    def test_period_end_equal_to_start_rejected(self, api):
        """PRD §3.9: "The period is rejected with `ERR_REPORT_PERIOD_INVALID` when
        the end is not after the start or lies in the future."

        Design: Corner/errors/err_report_period_invalid_trigger
        """
        ch = make_compliance_headers()
        resp = api_client.create_report(
            create_report_payload(period_start_at="2026-08-01T00:00:00Z",
                                  period_end_at="2026-08-01T00:00:00Z"),
            ch)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_INVALID)
