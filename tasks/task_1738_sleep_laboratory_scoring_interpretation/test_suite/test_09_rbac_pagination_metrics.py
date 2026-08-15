"""Cross-cutting concerns: authentication and role authorization, list
pagination, and the accreditation quality-metrics summary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_acquisition_ws,
    create_bed_payload,
    create_order,
    create_patient,
    create_patient_payload,
    create_report,
    create_scorer,
    make_scorer_headers,
    open_inter_rater_case,
    score_primary,
    set_clock,
    setup_double_scored_study,
    setup_study_in_progress,
    sign_report,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


class TestAuthenticationAndRoles:
    def test_missing_auth_header_returns_401(self, api):
        """PRD: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the
        operational capacity in which they act. A request with missing headers
        or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-AUTH-01"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_scheduler_cannot_adjudicate_case(self, api):
        """PRD: "Each operation is restricted to a designated set of roles
        (enumerated per endpoint in §4); an authenticated caller whose role is
        not permitted for the operation is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." — §4 restricts POST
        `/inter-rater-cases/{interRaterCaseId}/adjudicate` to `LabDirector`.

        Design: Corner/rbac/scheduler_cannot_adjudicate_case
        """
        ws = setup_double_scored_study()
        case = open_inter_rater_case(ws)

        resp = api.adjudicate_inter_rater_case(case["id"], 900, SCHED)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        reread = validate_success(
            api.get_inter_rater_case(case["id"], DIRECTOR))
        assert reread["status"] == "OPEN"

    def test_scorer_cannot_create_beds(self, api):
        """PRD: "Each operation is restricted to a designated set of roles
        (enumerated per endpoint in §4); an authenticated caller whose role is
        not permitted for the operation is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." — §4 restricts POST `/beds` to `LabDirector`.

        Design: Corner/rbac/scorer_cannot_create_beds
        """
        scorer = create_scorer()

        resp = api.create_bed(create_bed_payload(room_label="B-X"),
                              make_scorer_headers(scorer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestListPagination:
    def test_list_pagination_limit_offset(self, api):
        """PRD: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and
        defaults to 0."
        PRD: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_limit_offset
        """
        patient = create_patient()
        for study_type in ("HST", "PSG_DIAGNOSTIC", "SPLIT_NIGHT"):
            create_order(patient["id"], requested_study_type=study_type)

        page1, meta1 = validate_paginated(api.list_referral_orders(
            SCHED, {"patient_id": patient["id"], "limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_referral_orders(
            SCHED, {"patient_id": patient["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestQualityMetricsSummary:
    def test_quality_metrics_summary_aggregation(self, api):
        """PRD: "the quality summary, which reports `reports_signed_total` and
        how many of them breached the turnaround SLA as `sla_breached_total`,
        the resulting `sla_compliance_percent`, the reliability program's
        `cases_adjudicated_total` and `cases_concordant_total` with the
        resulting `inter_rater_concordant_percent`, and the current
        `scorers_in_remediation_total`. Percentages are reported with two
        decimals round-half-up, and a metric whose denominator is empty
        reports 100.00."

        Design: Corner/calculations/quality_metrics_summary_aggregation
        """
        # Study A: acquisition Mon 2026-08-03 09:00Z, signed Tue 08-04 10:00Z
        # (10.0 business hours — compliant). Study B: same acquisition, signed
        # Fri 08-14 09:00Z (81.0 business hours — breach).
        ws_a = setup_study_in_progress(study_type="HST",
                                       scheduled_date="2026-08-03")
        ws_b = setup_study_in_progress(study_type="HST",
                                       scheduled_date="2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        for ws in (ws_a, ws_b):
            complete_acquisition_ws(ws, total_recording_time_minutes=480)
        for ws in (ws_a, ws_b):
            score_primary(ws, obstructive_apneas=20, hypopneas=20)
            create_report(ws)

        set_clock("2026-08-04T10:00:00Z")
        report_a = sign_report(ws_a)
        set_clock("2026-08-14T09:00:00Z")
        report_b = sign_report(ws_b)

        assert report_a["sla_breached"] is False
        assert report_a["turnaround_business_hours"] == pytest.approx(10.0)
        assert report_b["sla_breached"] is True
        assert report_b["turnaround_business_hours"] == pytest.approx(81.0)

        summary = validate_success(api.get_quality_metrics_summary(DIRECTOR))
        assert summary["reports_signed_total"] == 2
        assert summary["sla_breached_total"] == 1
        assert summary["sla_compliance_percent"] == pytest.approx(50.00)
        # No reliability cases adjudicated: empty denominators report 100.00.
        assert summary["cases_adjudicated_total"] == 0
        assert summary["cases_concordant_total"] == 0
        assert summary["inter_rater_concordant_percent"] == \
            pytest.approx(100.00)
        assert summary["scorers_in_remediation_total"] == 0
