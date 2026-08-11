"""Rental-history reporting corners: window boundary, correction
supersession (PRD 3.9)."""
from test_helpers import (
    ApiErrorId,
    create_rental_history_report_payload,
    get_report,
    make_landlord_headers,
    set_clock,
    setup_case_filed,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestReportWindowExactBoundary:
    """Corner instance: report at exactly event_at + 30 days succeeds; one
    second later fails."""

    def test_exact_boundary_then_lapsed(self, api):
        """PRD 3.9: "a FILING, JUDGMENT, or SATISFACTION report must be filed
        no later than 30 days after its event_at, else
        ERR_REPORT_WINDOW_LAPSED (HTTP 422)". PRD 3.9: "For a FILING report
        the anchor is the accepted_at of the first ACCEPTED filing package on
        a case of that tenancy".

        Design: Corner/validations/report_window_exact_boundary
        """
        ctx = setup_case_filed("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        accepted_at = ctx["package"]["accepted_at"]

        # File at exactly accepted_at + 30 days (<= boundary): succeeds.
        from datetime import datetime, timedelta

        anchor = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        boundary = (anchor + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_clock(boundary)
        report = validate_success(api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload("FILING"), ll), 201)
        assert report["event_at"] == accepted_at

        # One second later the window has lapsed.
        set_clock((anchor + timedelta(days=30, seconds=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"))
        resp = api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload("FILING"), ll)
        validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_LAPSED, 422)


class TestCorrectionSupersedesAndRejectsRecorrection:
    """Corner instance: a CORRECTION flips the reference's superseded flag;
    a second correction against the same reference is rejected."""

    def test_correction_supersedes_reference_and_blocks_second(self, api):
        """PRD 3.9: "Filing the correction sets the referenced report's
        superseded flag to true" and "The target must exist, must belong to
        the same tenancy, must not itself be a CORRECTION, and must not
        already be superseded; any violation is rejected with
        ERR_CORRECTION_TARGET_INVALID (HTTP 422)." and "CORRECTION reports
        are exempt from this window."

        Design: Corner/validations/correction_supersedes_and_rejects_recorrection
        """
        ctx = setup_case_filed("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])

        set_clock("2026-06-02T09:00:00Z")
        r1 = validate_success(api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload("FILING"), ll), 201)
        assert r1["superseded"] is False

        r2 = validate_success(api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload(
                "CORRECTION", reference_report_id=r1["id"]), ll), 201)
        assert r2["report_type"] == "CORRECTION"
        assert get_report(r1["id"])["superseded"] is True

        resp = api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload(
                "CORRECTION", reference_report_id=r1["id"]), ll)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_TARGET_INVALID, 422)
