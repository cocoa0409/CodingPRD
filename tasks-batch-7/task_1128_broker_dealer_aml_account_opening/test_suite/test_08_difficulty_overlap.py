"""Difficulty queue: resource temporal overlap (EDD half-open vs engagement closed)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_customer,
    create_edd_review,
    create_engagement,
    create_rep,
    set_clock,
    validate_error,
    validate_success,
)


class TestEddReviewHalfOpenOverlap:
    def _setup_account_with_review(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep S", crd_number="CRD-OV1")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="S Med",
            tax_id="TIN-OV1",
            country_risk_tier="MEDIUM",
        )
        account = create_account(customer["id"], rep, product_set=["CASH"])
        review_a = create_edd_review(
            account["id"],
            period_start="2026-01-01",
            period_end="2026-03-01",
            trigger_reason="baseline",
        )
        assert review_a["status"] == "PENDING"
        return account

    def test_interior_overlap_rejected(self, api):
        """PRD §3.4: "the half-open period must not overlap any existing non-`REJECTED`
        review for the same account (`ERR_OVERLAPPING_EDD_REVIEW`)".
        Existing [2026-01-01, 2026-03-01) and new [2026-02-15, 2026-04-01) share the
        interior of February, so the new review is rejected.

        Design: Difficulty/resource_temporal_overlap/edd_review_half_open_overlap
        """
        account = self._setup_account_with_review()
        resp = api_client.create_edd_review(
            account["id"],
            {
                "period_start": "2026-02-15",
                "period_end": "2026-04-01",
                "trigger_reason": "overlap",
            },
            TEST_USERS["analyst_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_OVERLAPPING_EDD_REVIEW)
        assert error["error_id"] == "ERR_OVERLAPPING_EDD_REVIEW"
        assert resp.status_code == 409

    def test_exact_adjacency_accepted_under_half_open_semantics(self, api):
        """PRD §3.4: "The period is half-open: it includes its start date and excludes
        its end date".
        A new period starting 2026-03-01 — exactly the existing period's excluded end —
        shares no date with [2026-01-01, 2026-03-01) and is accepted.

        Design: Difficulty/resource_temporal_overlap/edd_review_half_open_overlap
        """
        account = self._setup_account_with_review()
        resp = api_client.create_edd_review(
            account["id"],
            {
                "period_start": "2026-03-01",
                "period_end": "2026-05-01",
                "trigger_reason": "adjacent",
            },
            TEST_USERS["analyst_headers"],
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "PENDING"


class TestAuditEngagementClosedIntervalOverlap:
    def _setup_engagement_a(self):
        set_clock("2026-05-01T00:00:00Z")
        engagement = create_engagement(
            scope_unit="AML_PROGRAM", start_date="2026-01-01", end_date="2026-03-01"
        )
        assert engagement["status"] == "PLANNED"
        return engagement

    def test_adjacent_closed_intervals_conflict(self, api):
        """PRD §3.9: "An `IndependentAuditor` plans an engagement with a `scope_unit`
        ... plus `start_date` and `end_date` describing a closed interval — both dates
        inclusive" and "Engagement windows must not overlap any other non-`CLOSED`
        engagement of the same `scope_unit` (`ERR_OVERLAPPING_AUDIT_ENGAGEMENT`)."
        Existing [2026-01-01, 2026-03-01] and new [2026-03-01, 2026-04-01] share the
        inclusive endpoint 2026-03-01, so they conflict; a next-day start (2026-03-02)
        leaves a one-day gap and is accepted.

        Design: Difficulty/resource_temporal_overlap/audit_engagement_closed_interval_overlap
        """
        self._setup_engagement_a()
        resp = api_client.create_engagement(
            {
                "scope_unit": "AML_PROGRAM",
                "start_date": "2026-03-01",
                "end_date": "2026-04-01",
            },
            TEST_USERS["auditor_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_OVERLAPPING_AUDIT_ENGAGEMENT)
        assert error["error_id"] == "ERR_OVERLAPPING_AUDIT_ENGAGEMENT"
        assert resp.status_code == 409

        resp = api_client.create_engagement(
            {
                "scope_unit": "AML_PROGRAM",
                "start_date": "2026-03-02",
                "end_date": "2026-04-01",
            },
            TEST_USERS["auditor_headers"],
        )
        gap = validate_success(resp, expected_status=201)
        assert gap["status"] == "PLANNED"

    def test_different_scope_unit_same_dates_no_conflict(self, api):
        """PRD §3.9: "Engagement windows must not overlap any other non-`CLOSED`
        engagement of the same `scope_unit` (`ERR_OVERLAPPING_AUDIT_ENGAGEMENT`)."
        The overlap rule is scoped per `scope_unit`: a SANCTIONS_SCREENING engagement
        over dates already covered by an AML_PROGRAM engagement is accepted.

        Design: Difficulty/resource_temporal_overlap/audit_engagement_closed_interval_overlap
        """
        self._setup_engagement_a()
        resp = api_client.create_engagement(
            {
                "scope_unit": "SANCTIONS_SCREENING",
                "start_date": "2026-01-15",
                "end_date": "2026-02-15",
            },
            TEST_USERS["auditor_headers"],
        )
        other_scope = validate_success(resp, expected_status=201)
        assert other_scope["status"] == "PLANNED"
        assert other_scope["scope_unit"] == "SANCTIONS_SCREENING"
