"""Optimistic concurrency on both guarded parents, and the agreement ledger's thresholds."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    SCORE_SHEET_ONE_CRITICAL,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_instant,
    create_brand,
    create_rubric_draft,
    finalize_visit,
    live_brand_version,
    make_auditor_headers,
    rescore_payload,
    rubric_version_payload,
    schedule_visit,
    score_visit,
    setup_brand_program,
    setup_submitted_visit,
    start_visit,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_LEDGER_VISIT_START = "2026-08-19T09:00:00Z"
SECOND_LEDGER_VISIT_END = "2026-08-19T13:00:00Z"
FIRST_SWEEP_AT = "2026-08-09T00:00:00Z"
SECOND_SWEEP_AT = "2026-08-23T00:00:00Z"

# Only FS-1 falls short of its maximum, so every visit on this sheet produces
# exactly one CRITICAL corrective action and still grades PASS.
ONLY_FS1_SHORT = {
    "FS-1": 27, "FS-2": 20, "BS-1": 15, "BS-2": 15, "FC-1": 12, "FC-2": 8,
}


class TestBrandVersionGuard:
    def test_a_second_rubric_draft_needs_the_brand_version_the_first_one_moved(self):
        """The stale echo is refused, and the same body succeeds after a re-read.

        PRD: "A successful draft itself advances `Brand.version` by one, so a client that drafts
        two rubric versions in sequence must re-read the brand between them."

        Design: Corner/cross_cutting_complexity_layers/rubric_version_create_rejects_a_stale_expected_brand_version
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        brand_id = brand["id"]
        assert brand["version"] == 1, "a freshly registered brand is at its first version"

        first = create_rubric_draft(
            brand_id, expected_brand_version=brand["version"], version_label="RV-2026.1",
        )
        assert first["status"] == "DRAFT"

        successor = rubric_version_payload(
            brand_id, brand["version"], version_label="RV-2026.2",
            effective_from="2026-10-01T00:00:00Z",
        )
        validate_error(
            api_client.create_rubric_version(successor, ADMIN_HEADERS),
            ApiErrorId.ERR_STALE_BRAND_VERSION,
            expected_status=412,
        )

        refreshed = validate_success(api_client.get_brand(brand_id, ADMIN_HEADERS))
        assert refreshed["version"] == 2, "the accepted draft advanced the brand it was drafted on"

        successor["expected_brand_version"] = refreshed["version"]
        second = validate_success(
            api_client.create_rubric_version(successor, ADMIN_HEADERS),
            expected_status=201,
        )
        assert second["status"] == "DRAFT", "the identical body is accepted once the echo is fresh"
        assert second["version_label"] == "RV-2026.2"

        assert live_brand_version(brand_id) == 3, \
            "the second accepted draft advanced the brand again"

        rows, meta = validate_paginated(
            api_client.list_rubric_versions(
                ADMIN_HEADERS, params={"brand_id": brand_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, "the refused attempt persisted nothing"
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


class TestVisitVersionGuard:
    def test_a_replayed_rescore_token_is_refused_and_consumes_no_rescore(self):
        """The refusal costs neither a version nor one of the two allowed rescores.

        PRD: "If that value does not equal the visit's current `version`, the request is rejected
        with `ERR_STALE_VISIT_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/visit_rescore_rejects_a_stale_expected_visit_version
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit_id = program["visit"]["id"]
        scored_fs1 = program["scored"]["FS-1"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        submitted = program["visit"]
        assert submitted["composite_score"] == pytest.approx(90.70, abs=0.01)
        stale_version = submitted["version"]

        first = validate_success(
            api_client.rescore_audit_visit(
                visit_id, rescore_payload(scored_fs1, 30, stale_version), auditor_headers,
            )
        )
        assert first["composite_score"] == pytest.approx(97.20, abs=0.01)
        assert first["rescore_count"] == 1
        assert first["version"] == stale_version + 1

        validate_error(
            api_client.rescore_audit_visit(
                visit_id, rescore_payload(scored_fs1, 28, stale_version), auditor_headers,
            ),
            ApiErrorId.ERR_STALE_VISIT_VERSION,
            expected_status=412,
        )

        middle = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert middle["composite_score"] == pytest.approx(97.20, abs=0.01)
        assert middle["rescore_count"] == 1, "the refused write consumed no rescore"
        assert middle["version"] == first["version"], "and advanced no version"

        retried = validate_success(
            api_client.rescore_audit_visit(
                visit_id, rescore_payload(scored_fs1, 27, middle["version"]), auditor_headers,
            )
        )
        assert retried["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert retried["rescore_count"] == 2
        assert retried["version"] == middle["version"] + 1


class TestAgreementThresholds:
    def test_the_ledger_crosses_every_agreement_threshold_and_saturates_at_three(self):
        """Two sweeps and one repeat violation walk the location to termination.

        PRD: "The status then follows directly from the level: level zero is `GOOD_STANDING`,
        level one is `NOTICE_OF_DEFAULT`, level two is `CURE_PERIOD`, and level three or higher is
        `TERMINATION_RECOMMENDED`."

        Design: Corner/cross_cutting_complexity_layers/escalation_ledger_crosses_each_agreement_threshold_and_saturates_at_three
        """
        program = setup_brand_program()
        location_id = program["location"]["id"]

        first_visit = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        start_visit(program, first_visit["id"], at=FIRST_VISIT_START)
        score_visit(program, first_visit["id"], ONLY_FS1_SHORT)
        submit_visit(program, first_visit["id"])
        finalized_first = finalize_visit(program, first_visit["id"], at=FIRST_VISIT_END)
        assert finalized_first["composite_score"] == pytest.approx(93.50, abs=0.01)
        assert finalized_first["grade"] == "PASS"

        before = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert before["escalation_level"] == 0
        assert before["franchise_agreement_status"] == "GOOD_STANDING"
        assert before["standing_score"] == pytest.approx(93.50, abs=0.01)
        assert before["repeat_violation_count"] == 0, \
            "a single critical violation appends no ledger entry at all"

        advance_clock(FIRST_SWEEP_AT)
        first_sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert first_sweep["escalated_count"] == 1

        at_level_one = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert at_level_one["escalation_level"] == 1
        assert at_level_one["franchise_agreement_status"] == "NOTICE_OF_DEFAULT"
        assert at_level_one["cure_period_started_at"] is None, \
            "level one does not open a cure period"

        second_visit = schedule_visit(
            program, SECOND_LEDGER_VISIT_START, SECOND_LEDGER_VISIT_END
        )
        start_visit(program, second_visit["id"], at=SECOND_LEDGER_VISIT_START)
        score_visit(program, second_visit["id"], ONLY_FS1_SHORT)
        submit_visit(program, second_visit["id"])
        finalized_second = finalize_visit(
            program, second_visit["id"], at=SECOND_LEDGER_VISIT_END
        )
        assert finalized_second["composite_score"] == pytest.approx(93.50, abs=0.01)

        at_level_two = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert at_level_two["repeat_violation_count"] == 1, \
            "FS-1 reached its second critical violation inside the trailing window"
        assert at_level_two["escalation_level"] == 2
        assert at_level_two["franchise_agreement_status"] == "CURE_PERIOD"
        assert_instant(
            at_level_two["cure_period_started_at"], SECOND_LEDGER_VISIT_END,
            "cure_period_started_at",
        )
        assert at_level_two["standing_score"] == pytest.approx(93.00, abs=0.01), \
            "93.50 less 0.50 for the one repeat violation"

        advance_clock(SECOND_SWEEP_AT)
        second_sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert second_sweep["escalated_count"] == 1

        saturated = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert saturated["escalation_level"] == 3
        assert saturated["franchise_agreement_status"] == "TERMINATION_RECOMMENDED"
        assert saturated["open_corrective_action_count"] == 0

        franchisee = validate_success(
            api_client.get_franchisee(program["franchisee"]["id"], ADMIN_HEADERS)
        )
        assert franchisee["termination_recommended"] is True
        assert franchisee["open_default_location_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_location_escalation_events(
                location_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        assert [row["event_type"] for row in rows] == [
            "OVERDUE_CRITICAL", "REPEAT_CRITICAL", "OVERDUE_CRITICAL",
        ]
        assert [row["resulting_escalation_level"] for row in rows] == [1, 2, 3]
        assert [row["resulting_agreement_status"] for row in rows] == [
            "NOTICE_OF_DEFAULT", "CURE_PERIOD", "TERMINATION_RECOMMENDED",
        ]
        assert all(row["level_delta"] == 1 for row in rows), \
            "both raising entry kinds carry a delta of positive one"

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["open_critical_action_count"] == 2, \
            "an escalated action still counts as an open critical action"
        assert risk["default_location_count"] == 1
        assert risk["brand_risk_index"] == pytest.approx(26.20, abs=0.01), \
            "0.60 * 7.00 plus 6.00 for each of the two critical actions plus 10.00"
        assert risk["brand_risk_tier"] == "BASELINE"
