"""Maintenance-visit spacing / temporal rules and claim resolution gating
(PRD §3.7, §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_completed_install,
    setup_approved_claim,
    create_maintenance_visit_payload,
    api_client,
    OPS,
    ADJUSTER,
    ApiErrorId,
)


class TestVisitMinGapBuffer:
    def test_visit_within_min_gap_rejected(self, api):
        """PRD §3.7: "the `scheduled_date` must be at least `MIN_VISIT_GAP_DAYS` (300 days)
        away from every other visit already on that warranty; a date closer than that buffer
        to any existing visit is rejected with `ERR_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/maintenance_visit_min_gap_buffer
        """
        ctx = setup_completed_install()  # auto visit dated 2027-05-01
        # 2027-08-01 is 92 days after the auto visit -> within the 300-day buffer.
        res = api.create_maintenance_visit(
            create_maintenance_visit_payload(ctx["warranty"]["id"], "2027-08-01T00:00:00Z"),
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_VISIT_TOO_SOON.value)

    def test_visit_beyond_min_gap_allowed(self, api):
        """PRD §3.7: "the `scheduled_date` must be at least `MIN_VISIT_GAP_DAYS` (300 days)
        away from every other visit already on that warranty; a date closer than that buffer
        to any existing visit is rejected with `ERR_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/maintenance_visit_min_gap_buffer
        """
        ctx = setup_completed_install()  # auto visit dated 2027-05-01
        # 2028-06-01 is well beyond 300 days from the auto visit -> accepted.
        visit = validate_success(
            api.create_maintenance_visit(
                create_maintenance_visit_payload(ctx["warranty"]["id"],
                                                 "2028-06-01T00:00:00Z"),
                OPS,
            ),
            201,
        )
        assert visit["status"] == "SCHEDULED", visit


class TestVisitTemporalViolations:
    def test_visit_date_in_past_rejected(self, api):
        """PRD §3.7: "The `scheduled_date` must be strictly in the future relative to the
        current logical clock, or the request is rejected with `ERR_VISIT_DATE_IN_PAST`."

        Design: Corner/validations/visit_date_in_past_returns_error
        """
        ctx = setup_completed_install()  # logical clock still at default 2026-05-01
        res = api.create_maintenance_visit(
            create_maintenance_visit_payload(ctx["warranty"]["id"], "2026-01-01T00:00:00Z"),
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_VISIT_DATE_IN_PAST.value)

    def test_mark_missed_before_due_rejected(self, api):
        """PRD §3.7: "marking missed requires that the current logical clock be strictly past
        the visit's `scheduled_date`, otherwise the request is rejected with
        `ERR_VISIT_NOT_DUE`."

        Design: Corner/validations/mark_missed_not_due_returns_error
        """
        ctx = setup_completed_install()  # auto visit 2027-05-01; clock still 2026-05-01
        res = api.mark_missed_visit(ctx["visit"]["id"], OPS)
        validate_error(res, ApiErrorId.ERR_VISIT_NOT_DUE.value)


class TestClaimResolutionGating:
    def test_resolve_before_remediation_complete_rejected(self, api):
        """PRD §3.8: "resolution requires that the spawned remediation job have reached
        `COMPLETED` fulfillment, and an attempt to resolve before the remediation job
        completes is rejected with `ERR_REMEDIATION_NOT_COMPLETE`."

        Design: Corner/validations/claim_resolve_remediation_not_complete_returns_error
        """
        ctx = setup_approved_claim(reported_settlement_inches=1.0)
        # Remediation job was just created (UNSCHEDULED), not COMPLETED.
        res = api.resolve_claim(ctx["claim"]["id"], ADJUSTER)
        validate_error(res, ApiErrorId.ERR_REMEDIATION_NOT_COMPLETE.value)
