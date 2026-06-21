"""Difficulty Rule 8 — resource_temporal_overlap.

Two interval semantics:
  (a) AnnualReport — zero-width interval at (business_entity_id, period_year);
      ANY existing row (even VOIDED) blocks re-creation.
  (b) ForeignQualification — half-open [qualified_at, withdrawn_at) overlap
      at (business_entity_id, foreign_state_code).
"""
from test_helpers import (
    validate_error,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    file_annual_report,
    create_foreign_agent,
    create_pending_foreign_qualification,
    approve_foreign_qualification,
    make_filer_headers,
    make_state_admin_headers,
)


class TestAnnualReportZeroWidthPeriodUniqueness:
    """PRD §3.7: at most one AnnualReport per (business_entity_id, period_year)
    across the entity's lifetime — even VOIDED reports occupy the slot.
    """

    def test_second_create_same_period_year_returns_report_period_taken(self, api):
        """PRD §3.7: "At most one report may exist per `(business_entity_id,
        period_year)` pair across the entire lifetime of the entity — even a
        `VOIDED` report occupies that slot, so re-creation against the same period
        is rejected with `ERR_REPORT_PERIOD_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/rto_annual_report_zero_width_period_year_uniqueness
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="SIERRA LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar1 = create_draft_annual_report(be, 2024)
        file_annual_report(be, ar1["id"])
        set_clock("2025-06-01T00:00:00Z")
        res = api.create_annual_report(
            be["id"], {"period_year": 2024}, make_filer_headers(be["id"])
        )
        validate_error(res, "ERR_REPORT_PERIOD_TAKEN")

    def test_distinct_period_year_can_coexist_on_same_entity(self, api):
        """PRD §3.7: "An `AnnualReport` is created by a `Filer` against a
        `BusinessEntity` with a single payload field: `period_year`, an integer
        between 2020 and 2099 inclusive."
        PRD §3.7: "At most one report may exist per `(business_entity_id,
        period_year)` pair across the entire lifetime of the entity"

        Design: Difficulty/resource_temporal_overlap/rto_annual_report_zero_width_period_year_uniqueness
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="SIERRA2 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        # Two reports for distinct period_year values are both legal.
        ar_2023 = create_draft_annual_report(be, 2023)
        ar_2024 = create_draft_annual_report(be, 2024)
        assert ar_2023["period_year"] == 2023
        assert ar_2024["period_year"] == 2024
        assert ar_2023["id"] != ar_2024["id"]


class TestForeignQualificationHalfOpenIntervalOverlap:
    """PRD §3.10: at most one QUALIFIED FQ per (entity, foreign_state_code)
    whose half-open [qualified_at, withdrawn_at) interval covers current
    clock UTC.
    """

    def test_second_approve_same_entity_same_state_returns_fq_overlap(self, api):
        """PRD §3.10: "no other `QUALIFIED` `ForeignQualification` for the same
        `(business_entity_id, foreign_state_code)` pair whose half-open
        `[qualified_at, withdrawn_at)` interval covers the current clock UTC may
        exist (overlap is rejected with `ERR_FQ_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/rto_foreign_qualification_halfopen_interval_overlap
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="TANGO LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        foreign_agent = create_foreign_agent(be, foreign_state_code="CA")
        fq1 = create_pending_foreign_qualification(be, "CA", foreign_agent["id"])
        approve_foreign_qualification(fq1["id"])
        # Second FQ for same (entity, CA) — PENDING create is accepted, but
        # approve must fail with overlap.
        fq2 = create_pending_foreign_qualification(be, "CA", foreign_agent["id"])
        res = api.approve_foreign_qualification(fq2["id"], make_state_admin_headers())
        validate_error(res, "ERR_FQ_OVERLAP")

    def test_fq_same_entity_distinct_states_can_coexist(self, api):
        """PRD §3.10: "A `BusinessEntity` that wishes to do business in a state
        other than its `formation_state_code` files a `ForeignQualification`."
        PRD §3.10: "no other `QUALIFIED` `ForeignQualification` for the same
        `(business_entity_id, foreign_state_code)` pair"

        Design: Difficulty/resource_temporal_overlap/rto_foreign_qualification_halfopen_interval_overlap
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="TANGO2 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ca_agent = create_foreign_agent(be, foreign_state_code="CA")
        ny_agent = create_foreign_agent(be, foreign_state_code="NY")
        fq_ca = create_pending_foreign_qualification(be, "CA", ca_agent["id"])
        fq_ny = create_pending_foreign_qualification(be, "NY", ny_agent["id"])
        approved_ca = approve_foreign_qualification(fq_ca["id"])
        approved_ny = approve_foreign_qualification(fq_ny["id"])
        assert approved_ca["status"] == "QUALIFIED"
        assert approved_ny["status"] == "QUALIFIED"
        assert approved_ca["foreign_state_code"] != approved_ny["foreign_state_code"]
