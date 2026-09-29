"""Worksheet concurrency, the reassessment threshold and immediate cascade visibility."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_STALE_REQUIREMENT_VERSION
from test_helpers.assertions import (
    assert_partition_counts,
    assert_percentage,
    assert_requirement_dimensions,
    assert_segment_state,
    assert_total_count,
    assert_version_bumped_by,
)
from test_helpers.constants import FACILITY_DC_WEST
from test_helpers.factories import ccw_payload
from test_helpers.fixtures import (
    Scenario,
    add_complete_evidence,
    add_component,
    build_fieldwork_engagement,
    conclude,
    declare_segment,
    draft_ccw,
    open_requirement,
    plan_segmentation,
    read_engagement,
    record_change,
    record_verdict,
    set_clock,
    start_testing,
)
from test_helpers.test_users import make_lead_headers

SCORE_TOLERANCE = 0.01


def _requirement_gapped_after_a_read(api) -> Scenario:
    """Take requirement 1.2.1 to NOT_IN_PLACE, keeping the version read before it.

    The caller reads the requirement while it is still IN_TESTING, exactly as a
    client that had the row on screen would, and only then records the failing
    conclusion that moves it on.
    """
    scenario = build_fieldwork_engagement(api)
    lead_id = scenario["lead_id"]
    lead_headers = make_lead_headers(lead_id)
    requirement = open_requirement(
        api,
        scenario["engagement_id"],
        lead_id,
        requirement_ref="1.2.1",
        requirement_family="R1",
        testing_procedure_count=3,
    )
    start_testing(api, requirement["id"], lead_id)
    add_complete_evidence(
        api,
        requirement["id"],
        lead_id,
        "1.2.1",
        scenario["component_ids"]["pay-01"],
    )
    observed = validate_success(
        api.get_requirement_assessment(requirement["id"], lead_headers)
    )
    scenario["version_before_conclusion"] = observed["version"]
    scenario["requirement"] = conclude(
        api,
        requirement["id"],
        lead_id,
        conclusion="NOT_IN_PLACE",
        conclusion_rationale="Two documented services are not restricted by the ruleset.",
    )
    scenario["requirement_id"] = requirement["id"]
    return scenario


def _requirement_version(api, requirement_id: str, lead_id: str) -> int:
    row = validate_success(
        api.get_requirement_assessment(requirement_id, make_lead_headers(lead_id))
    )
    return row["version"]


class TestWorksheetDraftGuardsTheRequirementRevision:
    """Drafting a worksheet proves the client is working from the current requirement."""

    def test_a_version_read_before_the_conclusion_is_refused_then_retried(self, api):
        """The stale draft answers 412 and the refreshed retry is accepted whole.

        PRD: If that value does not equal the requirement's current `version`, the
        draft is refused with `ERR_STALE_REQUIREMENT_VERSION` (HTTP 412).

        Design: Corner/cross_cutting_complexity_layers/layer_optimistic_concurrency_on_worksheet_creation
        """
        scenario = _requirement_gapped_after_a_read(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        requirement_id = scenario["requirement_id"]
        stale_version = scenario["version_before_conclusion"]

        refused = api.create_ccw(
            requirement_id, ccw_payload(stale_version), lead_headers
        )
        validate_error(refused, ERR_STALE_REQUIREMENT_VERSION, 412)

        assert_total_count(
            api.list_ccws(
                lead_headers, {"requirement_assessment_id": requirement_id}
            ),
            0,
        )

        # The failing conclusion is the single write that moved the requirement on.
        fresh_version = _requirement_version(api, requirement_id, lead_id)
        assert_version_bumped_by(stale_version, fresh_version)

        worksheet = draft_ccw(api, requirement_id, lead_id, fresh_version)

        assert worksheet["status"] == "DRAFT"
        assert worksheet["reviewer_note"] is None
        assert worksheet["decided_at"] is None
        assert worksheet["engagement_id"] == scenario["engagement_id"]
        assert worksheet["thin_control_capped"] is False
        assert worksheet["control_depth_points"] == pytest.approx(
            80.00, abs=SCORE_TOLERANCE
        )
        assert worksheet["monitoring_factor"] == pytest.approx(
            80.00, abs=SCORE_TOLERANCE
        )
        assert worksheet["risk_offset_points"] == pytest.approx(
            55.00, abs=SCORE_TOLERANCE
        )
        # Four distinct controls verified weekly on an R1 requirement.
        assert worksheet["rigor_score"] == pytest.approx(73.75, abs=SCORE_TOLERANCE)

        held = validate_success(
            api.get_requirement_assessment(requirement_id, lead_headers)
        )
        assert_requirement_dimensions(
            held, test_status="NOT_IN_PLACE", remediation_status="GAP_OPEN"
        )
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["open_gap_count"] == 1
        assert engagement["accepted_ccw_count"] == 0

    def test_a_stale_draft_cannot_supersede_the_worksheet_it_never_read(self, api):
        """The earlier draft survives the refusal and only the current view retires it.

        PRD: The reason is symmetrical: a new worksheet supersedes the requirement's
        prior draft or rejected worksheet, so a writer working from a stale view of
        the requirement would supersede a worksheet whose rejection note it has not
        read.

        Design: Corner/cross_cutting_complexity_layers/layer_optimistic_concurrency_on_worksheet_creation
        """
        scenario = _requirement_gapped_after_a_read(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        requirement_id = scenario["requirement_id"]

        first = draft_ccw(
            api, requirement_id, lead_id, scenario["requirement"]["version"]
        )
        assert first["status"] == "DRAFT"

        current_version = _requirement_version(api, requirement_id, lead_id)
        refused = api.create_ccw(
            requirement_id, ccw_payload(current_version - 1), lead_headers
        )
        validate_error(refused, ERR_STALE_REQUIREMENT_VERSION, 412)

        held = validate_success(api.get_ccw(first["id"], lead_headers))
        assert held["status"] == "DRAFT"
        assert held["version"] == first["version"]
        assert_total_count(
            api.list_ccws(
                lead_headers, {"requirement_assessment_id": requirement_id}
            ),
            1,
        )

        # Drafting from the current view is what legitimately retires the first sheet.
        second = draft_ccw(api, requirement_id, lead_id, current_version)
        assert second["status"] == "DRAFT"
        retired = validate_success(api.get_ccw(first["id"], lead_headers))
        assert retired["status"] == "SUPERSEDED"
        assert_total_count(
            api.list_ccws(
                lead_headers, {"requirement_assessment_id": requirement_id}
            ),
            2,
        )


def _record_the_first_four_changes(api, scenario: Scenario) -> list:
    """Log four in-year changes of which only two qualify as scope-affecting."""
    entries = [
        record_change(
            api,
            scenario["engagement_id"],
            scenario["lead_id"],
            "COMPONENT_ADDED_TO_CDE",
            "A reporting server was joined to the cardholder network.",
            True,
        ),
        record_change(
            api,
            scenario["engagement_id"],
            scenario["lead_id"],
            "APPLICATION_UPDATED",
            "Payment application patched to 4.2.1.",
            True,
        ),
        record_change(
            api,
            scenario["engagement_id"],
            scenario["lead_id"],
            "SEGMENT_RECLASSIFIED",
            "The warehouse VLAN was reclassified as connected.",
            False,
        ),
        record_change(
            api,
            scenario["engagement_id"],
            scenario["lead_id"],
            "SEGMENT_RECLASSIFIED",
            "The call-centre VLAN was reclassified as connected.",
            True,
        ),
    ]
    return entries


class TestReassessmentThresholdCountsOnlyQualifyingChanges:
    """The in-year change ledger is a filtered count with an inclusive threshold."""

    def test_only_qualifying_changes_count_toward_the_threshold(
        self, api, scoping_engagement
    ):
        """Four logged changes leave the count at two and the flag still down.

        PRD: `triggers_reassessment` is true only when both halves hold:
        `affects_scope` is true *and* `change_type` is one of
        `COMPONENT_ADDED_TO_CDE`, `SEGMENT_RECLASSIFIED` or `THIRD_PARTY_ADDED`.

        Design: Corner/cross_cutting_complexity_layers/layer_rate_threshold_flips_reassessment_at_the_third_qualifying_change
        """
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scoping_engagement["engagement_id"]

        entries = _record_the_first_four_changes(api, scoping_engagement)

        # A patched application never qualifies, and a reclassification the client
        # says does not touch the cardholder environment does not either.
        assert [entry["triggers_reassessment"] for entry in entries] == [
            True,
            False,
            False,
            True,
        ]

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["scope_affecting_change_count"] == 2
        assert engagement["reassessment_required"] is False
        assert engagement["reassessment_due_date"] is None

        assert_total_count(
            api.list_change_log_entries(lead_headers, {"engagement_id": engagement_id}),
            4,
        )
        assert_total_count(
            api.list_change_log_entries(
                lead_headers,
                {"engagement_id": engagement_id, "triggers_reassessment": True},
            ),
            2,
        )

    def test_the_third_qualifying_change_pins_the_accelerated_due_date(
        self, api, scoping_engagement
    ):
        """The third qualifying entry flips the flag and fixes the date for good.

        PRD: At the moment `reassessment_required` first flips true, the
        engagement's `reassessment_due_date` is pulled forward to the logical-clock
        date advanced by 90 days, overwriting any 365-day date a submission had
        previously set; the accelerated date is never pushed back out again.

        Design: Corner/cross_cutting_complexity_layers/layer_rate_threshold_flips_reassessment_at_the_third_qualifying_change
        """
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scoping_engagement["engagement_id"]
        _record_the_first_four_changes(api, scoping_engagement)

        third = record_change(
            api,
            engagement_id,
            lead_id,
            "THIRD_PARTY_ADDED",
            "A managed hosting provider took over the DC-EAST cage.",
            True,
        )

        assert third["triggers_reassessment"] is True
        flipped = read_engagement(api, engagement_id, lead_id)
        assert flipped["scope_affecting_change_count"] == 3
        assert flipped["reassessment_required"] is True
        # The clock stands at 2026-08-01, so the accelerated date is 90 days on.
        assert flipped["reassessment_due_date"] == "2026-10-30"

        set_clock(api, "2026-09-01T00:00:00Z")
        fourth = record_change(
            api,
            engagement_id,
            lead_id,
            "COMPONENT_ADDED_TO_CDE",
            "A second reporting server was joined to the cardholder network.",
            True,
        )

        assert fourth["triggers_reassessment"] is True
        summary = validate_success(
            api.get_engagement_summary(engagement_id, lead_headers)
        )
        assert summary["scope_affecting_change_count"] == 4
        assert summary["reassessment_required"] is True
        after = read_engagement(api, engagement_id, lead_id)
        assert after["reassessment_due_date"] == "2026-10-30"

        # Logging changes never moves the engagement forward by itself.
        assert after["status"] == "SCOPING"
        assert after["posture"] == "OPEN"
        assert_total_count(
            api.list_change_log_entries(lead_headers, {"engagement_id": engagement_id}),
            6,
        )
        assert_total_count(
            api.list_change_log_entries(
                lead_headers,
                {"engagement_id": engagement_id, "triggers_reassessment": True},
            ),
            4,
        )


def _operations_zone_awaiting_verdict(api, scenario: Scenario) -> Scenario:
    """Declare a connected operations zone holding one host and plan its test."""
    lead_id = scenario["lead_id"]
    zone = declare_segment(
        api,
        scenario["engagement_id"],
        lead_id,
        "CONNECTED-OPS",
        segment_class="CONNECTED",
        parent_segment_id=scenario["segment_id"],
    )
    scenario["ops_zone_id"] = zone["id"]
    scenario["ops_component"] = add_component(
        api,
        scenario["engagement_id"],
        lead_id,
        zone["id"],
        "ops-01",
        component_type="SERVER",
        function_class="CONNECTED_SUPPORT",
        facility_name=FACILITY_DC_WEST,
        facility_type="DATA_CENTER",
    )
    plan_segmentation(
        api,
        zone["id"],
        lead_id,
        test_method="TRAFFIC_ANALYSIS",
        planned_date="2026-08-12",
    )
    return scenario


_SHARED_POSITION_FIELDS = [
    "posture",
    "cde_component_count",
    "connected_component_count",
    "out_of_scope_component_count",
    "open_gap_count",
    "unvalidated_segment_count",
]


def _agreeing_position(api, engagement_id: str, lead_id: str) -> dict:
    """Read the engagement and its roll-up and insist the two answers agree."""
    lead_headers = make_lead_headers(lead_id)
    engagement = read_engagement(api, engagement_id, lead_id)
    summary = validate_success(
        api.get_engagement_summary(engagement_id, lead_headers)
    )
    for field in _SHARED_POSITION_FIELDS:
        assert engagement[field] == summary[field], (
            "the engagement and its roll-up disagree on %s: %r versus %r"
            % (field, engagement[field], summary[field])
        )
    assert_percentage(
        summary["as_found_compliance_percentage"],
        engagement["as_found_compliance_percentage"],
    )
    assert_percentage(
        summary["as_attested_compliance_percentage"],
        engagement["as_attested_compliance_percentage"],
    )
    position = {field: engagement[field] for field in _SHARED_POSITION_FIELDS}
    position["as_found_compliance_percentage"] = engagement[
        "as_found_compliance_percentage"
    ]
    position["as_attested_compliance_percentage"] = engagement[
        "as_attested_compliance_percentage"
    ]
    return position


class TestFailedBoundaryIsFullyRecomputedInsideTheRequest:
    """One failing verdict returns an already-recomputed world to every reader."""

    def test_the_verdict_answers_with_the_whole_consequence_of_the_failure(
        self, api, engagement_with_in_place_requirement
    ):
        """The response names the failure and the very next read shows every effect.

        PRD: Posture is not stored by any caller and is never latched; it is
        recomputed from scratch at the end of every write that touches the
        engagement or any of its children, from three inputs plus the engagement's
        own `status`.

        Design: Corner/consistency_model/consistency_every_cascade_effect_is_visible_in_the_triggering_response
        """
        scenario = _operations_zone_awaiting_verdict(
            api, engagement_with_in_place_requirement
        )
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        before = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(before, cde=3, connected=1, out_of_scope=0)

        verdict = record_verdict(
            api,
            scenario["ops_zone_id"],
            lead_id,
            outcome="FAIL",
            note="Operational traffic reaches the cardholder network.",
        )

        # The caller learns the outcome from the verdict itself.
        assert_segment_state(
            verdict,
            segmentation_status="FAILED",
            effective_class="CDE",
            segment_class="CONNECTED",
            scope_expanded_by_failure=True,
        )

        # First read after the verdict, with no intervening write of any kind.
        summary = validate_success(
            api.get_engagement_summary(engagement_id, lead_headers)
        )
        assert summary["posture"] == "RESTRICTED"
        assert summary["cde_component_count"] == 4
        assert summary["connected_component_count"] == 0
        assert summary["open_gap_count"] == 0
        assert summary["unvalidated_segment_count"] == 1

        plans = validate_success(
            api.list_sampling_plans(lead_headers, {"engagement_id": engagement_id})
        )
        assert [row["status"] for row in plans] == ["STALE"]

        host = validate_success(
            api.get_system_component(scenario["ops_component"]["id"], lead_headers)
        )
        assert host["scope_class"] == "CDE"
        assert host["declared_scope_class"] == "CONNECTED"

        after = read_engagement(api, engagement_id, lead_id)
        assert after["active_plan_stale"] is True
        assert after["active_sampling_plan_id"] is None
        assert_version_bumped_by(before["version"], after["version"])

    def test_repeated_reads_of_both_projections_never_diverge(
        self, api, engagement_with_in_place_requirement
    ):
        """Nothing settles late: the second read matches the first exactly.

        PRD: Every one of those numbers is derived on read from the engagement's
        children, never stored by a caller.

        Design: Corner/consistency_model/consistency_every_cascade_effect_is_visible_in_the_triggering_response
        """
        scenario = _operations_zone_awaiting_verdict(
            api, engagement_with_in_place_requirement
        )
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]
        before = _agreeing_position(api, engagement_id, lead_id)
        assert before["cde_component_count"] == 3
        assert before["connected_component_count"] == 1

        record_verdict(
            api,
            scenario["ops_zone_id"],
            lead_id,
            outcome="FAIL",
            note="Operational traffic reaches the cardholder network.",
        )

        first = _agreeing_position(api, engagement_id, lead_id)
        second = _agreeing_position(api, engagement_id, lead_id)

        assert first == second
        assert first["posture"] == "RESTRICTED"
        assert first["cde_component_count"] == 4
        assert first["connected_component_count"] == 0
        assert first["open_gap_count"] == 0
        # The requirement programme is untouched by a segmentation verdict.
        assert_percentage(first["as_found_compliance_percentage"], 100.00)
        assert_percentage(first["as_attested_compliance_percentage"], 100.00)
