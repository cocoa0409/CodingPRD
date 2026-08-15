"""Post-verification correction cascade and consent-revoke suppression (PRD §3.3, §3.4, §3.6, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    get_report,
    list_flags,
    list_publications,
    make_tenant_rep_headers,
    setup_published_cycle_with_verified_report,
    setup_verified_report,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
UTILITY = TEST_USERS["utility_agent_headers"]

FULL_YEAR_2027 = {
    "period_start": "2027-01-01T00:00:00Z",
    "period_end": "2028-01-01T00:00:00Z",
}


class TestUsageVoidCorrectionCascade:
    def test_void_recomputes_verified_report_and_reopens(self, api):
        """PRD §3.4: "First, the building's report for the matching cycle year —
        whatever its status — recomputes `aggregated_kbtu` and `site_eui`; reports in
        `DRAFT` or `FLAGGED` recompute `data_completeness_pct` as well. Second, when
        that report is `VERIFIED` or `CERTIFIED`, the post-verification correction
        check of §3.6 runs, and a delta beyond tolerance drops the report to
        `FLAGGED` with a fresh anomaly flag."
        PRD §3.6: "A delta strictly greater than the cycle's
        `correction_tolerance_pct` — exactly at tolerance does not reopen — moves the
        report to `FLAGGED` and opens an `AnomalyFlag` of `anomaly_type`
        `VERIFICATION_REOPENED`."

        Voiding the only record moves EUI from 81.89 to 0.00: a 100.00 pct delta,
        beyond the 5 pct tolerance.

        Design: Difficulty/transitive_cascade/usage_void_downgrades_report_and_supersedes_disclosure
        """
        ctx = setup_published_cycle_with_verified_report()
        record = ctx["usage_records"][0]

        voided = validate_success(
            api.void_usage_record(
                record["id"], {"reason": "Meter misread; full-year correction pending"}, UTILITY
            )
        )
        assert voided["status"] == "VOIDED"

        report = get_report(ctx["report"]["id"])
        assert report["aggregated_kbtu"] == 0, "link 1: aggregates recomputed without the voided record"
        assert report["site_eui"] == pytest.approx(0.00, abs=0.005)
        assert report["status"] == "FLAGGED", "link 2: correction check downgraded the report"

        open_flags = [f for f in list_flags(report_id=ctx["report"]["id"]) if f["status"] == "OPEN"]
        assert len(open_flags) == 1
        assert open_flags[0]["anomaly_type"] == "VERIFICATION_REOPENED"

    def test_reopened_report_supersedes_published_disclosure(self, api):
        """PRD §3.4: "Third, if the affected report is included in a currently
        `PUBLISHED` disclosure publication, that publication is superseded per §3.9."
        PRD §3.9: "On either trigger the publication moves `PUBLISHED → SUPERSEDED`,
        stamps `superseded_at`, and the system immediately creates a replacement
        publication for the same cycle in `DRAFT` whose `publication_version` is one
        greater than the superseded version"

        Link 3 of the same cascade: the PUBLISHED v1 is superseded and a replacement
        DRAFT at version 2 appears in the same request.

        Design: Difficulty/transitive_cascade/usage_void_downgrades_report_and_supersedes_disclosure
        """
        ctx = setup_published_cycle_with_verified_report()
        assert ctx["publication"]["status"] == "PUBLISHED"
        assert ctx["publication"]["publication_version"] == 1
        record = ctx["usage_records"][0]

        validate_success(
            api.void_usage_record(
                record["id"], {"reason": "Meter misread; full-year correction pending"}, UTILITY
            )
        )

        superseded = list_publications(cycle_id=ctx["cycle"]["id"], status="SUPERSEDED")
        assert len(superseded) == 1
        assert superseded[0]["publication_version"] == 1
        assert superseded[0]["superseded_at"] is not None

        drafts = list_publications(cycle_id=ctx["cycle"]["id"], status="DRAFT")
        assert len(drafts) == 1
        assert drafts[0]["publication_version"] == 2

    def test_correction_at_exact_tolerance_stays_verified(self, api):
        """PRD §3.6: "A delta strictly greater than the cycle's
        `correction_tolerance_pct` — exactly at tolerance does not reopen — moves the
        report to `FLAGGED` and opens an `AnomalyFlag` of `anomaly_type`
        `VERIFICATION_REOPENED`."

        The correction moves site_eui from 100.00 to 95.00: a delta of exactly 5.00
        pct, which is NOT strictly greater than the 5 pct tolerance. Only the
        aggregates move.

        Design: Corner/calculations/c_correction_delta_exactly_at_tolerance_no_downgrade
        """
        ctx = setup_verified_report(
            building_overrides={"gross_floor_area_sqft": 40000},
            unit_specs=[("U1", 20000, "OFFICE"), ("U2", 10000, "RETAIL")],
            consent_indexes=(0, 1),
            usage_records=[dict(FULL_YEAR_2027, consumption_value=40000)],
            account_overrides={"commodity": "NATURAL_GAS"},
        )
        assert ctx["report"]["verified_site_eui"] == pytest.approx(100.00, abs=0.005)
        record = ctx["usage_records"][0]

        validate_success(
            api.void_usage_record(
                record["id"],
                {
                    "reason": "Calibrated meter correction",
                    "replacement_period_start": "2027-01-01T00:00:00Z",
                    "replacement_period_end": "2028-01-01T00:00:00Z",
                    "replacement_consumption_value": 38000,
                },
                UTILITY,
            )
        )

        report = get_report(ctx["report"]["id"])
        assert report["status"] == "VERIFIED", "exactly at tolerance does not reopen"
        assert report["aggregated_kbtu"] == 3800000
        assert report["site_eui"] == pytest.approx(95.00, abs=0.005)

        assert list_flags(report_id=ctx["report"]["id"]) == [], "no anomaly raised"


class TestConsentRevokeSuppression:
    def test_consent_revoke_suppresses_verified_scores(self, api):
        """PRD §3.3: "Revocation recomputes `data_completeness_pct` on **all** of the
        building's reports for the affected cycles regardless of their status —
        `DRAFT`, `FLAGGED`, `SUBMITTED`, `VERIFIED`, and `CERTIFIED` alike — and
        where the recomputed completeness of a `VERIFIED` or `CERTIFIED` report falls
        below the score-eligibility floor of 75 percent, that report's
        `score_as_reported` and `score_weather_normalized` are suppressed to null and
        its `label_grade` becomes `INSUFFICIENT_DATA`, while the report's status is
        left unchanged."

        The verified report carried score 46 / label D at completeness 90.00; the
        revoke drops completeness to 60.00 and suppresses the scores in place.

        Design: Corner/cross_cutting/x_consent_revoke_suppresses_verified_score
        """
        ctx = setup_verified_report(
            usage_records=[dict(FULL_YEAR_2027, consumption_value=1200000)]
        )
        assert ctx["report"]["score_as_reported"] == 46
        assert ctx["report"]["label_grade"] == "D"

        validate_success(
            api.revoke_consent(ctx["grants"][1]["id"], make_tenant_rep_headers(ctx["units"][1]["id"]))
        )

        report = get_report(ctx["report"]["id"])
        assert report["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)
        assert report["status"] == "VERIFIED", "suppression is not a state downgrade"
        assert report["score_as_reported"] is None
        assert report["score_weather_normalized"] is None
        assert report["label_grade"] == "INSUFFICIENT_DATA"
