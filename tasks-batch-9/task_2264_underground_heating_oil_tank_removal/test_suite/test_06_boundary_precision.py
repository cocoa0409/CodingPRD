"""Values sitting exactly on a limit, and the zero-count edge of a counted input."""
import pytest

from test_helpers import fixtures as fx, parse_instant, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import OMIT, custody_event_payload
from test_helpers.test_users import FIELD_TECHNICIAN, make_lab_analyst_headers


class TestContaminationActionLevelBoundary:
    def test_result_exactly_at_both_action_levels_classifies_clean(self, api):
        """PRD §2.10: "Concretely, a soil result sitting exactly on an action level is not an exceedance — contamination comparisons are strictly greater-than, so a sample at exactly 500.0 mg/kg of total petroleum hydrocarbons and exactly 0.5 mg/kg of benzene classifies as `CLEAN`."
        PRD §3.6: "When `contamination_class` is `CLEAN`, the project advances `ASSESSED → CLEARED` and nothing else changes."

        Design: Difficulty/boundary_precision_check/contamination_thresholds_exactly_at_action_level_classify_clean
        """
        ctx = fx.project_at_sampling()
        fx.collect_sample_with_result(ctx, 500.0, 0.5, "CONFIRMATION_FLOOR", 84)

        project = fx.read_project(ctx["project"]["id"])
        assert project["max_tph_mg_kg"] == pytest.approx(500.0, abs=0.01), (
            f"the round maximum must be the posted figure, got {project['max_tph_mg_kg']}"
        )
        assert project["max_benzene_mg_kg"] == pytest.approx(0.5, abs=0.01), (
            "the benzene maximum must be the posted figure, got "
            f"{project['max_benzene_mg_kg']}"
        )
        assert project["contamination_class"] == "CLEAN", (
            "sitting exactly on both action levels is not an exceedance, got "
            f"{project['contamination_class']}"
        )
        assert project["status"] == "CLEARED", (
            f"a clean classification routes the project to CLEARED, got {project['status']}"
        )

    def test_clean_classification_at_the_boundary_fires_no_remediation_cascade(
        self, api
    ):
        """PRD §3.7: "While the project's `remediation_started` latch is false, `remediation_cost_cents` is 0 regardless of what any change order says."
        PRD §3.9: "`CONTAMINATION_NOT_CLEARED` is present whenever the project's `contamination_class` is anything other than `CLEAN` — including `UNCLASSIFIED`."
        PRD §3.9: "The resulting codes are deduplicated and sorted lexicographically ascending — never by creation time or identifier — so the list is stable and directly comparable between reads."

        Design: Difficulty/boundary_precision_check/contamination_thresholds_exactly_at_action_level_classify_clean
        """
        ctx = fx.project_at_sampling()
        fx.collect_sample_with_result(ctx, 500.0, 0.5, "CONFIRMATION_FLOOR", 84)

        project = fx.read_project(ctx["project"]["id"])
        assert project["remediation_started"] is False, (
            "the project never entered REMEDIATION_ACTIVE, so the latch stays false"
        )
        assert project["contamination_disclosure_required"] is False, (
            "the classification never became ELEVATED or GROSS, so nothing latched"
        )
        assert project["remediation_cost_cents"] == 0, (
            "with the latch false the cost is 0, got "
            f"{project['remediation_cost_cents']}"
        )
        assert project["nfa_blockers"] == [], (
            "a cleared project with completed field work has nothing outstanding, got "
            f"{project['nfa_blockers']}"
        )


class TestZeroTankSweepEdge:
    def _connecticut_project(self):
        prop = fx.create_property(
            state_code="CT",
            county_code="FAIRFIELD",
            street_address="31 Cider Mill Road",
        )
        project = fx.create_project(
            prop["id"],
            baseline_scope_cubic_yards=OMIT,
            excavation_limit_cubic_yards=OMIT,
        )
        return prop, project

    def test_zero_tank_sweep_is_refused_by_the_tank_located_check(self, api):
        """PRD §3.1: "If the sweep locates nothing, that is, if `tanks_detected_count` is 0, the survey is refused with `ERR_NO_TANK_LOCATED` and the project stays in `INTAKE`; a project that never had a tank has no decommissioning to authorize."
        PRD §2.11: "Because body shape (rule 6) precedes the tank-located check (rule 11), a sweep survey reporting zero tanks and omitting the tank descriptors passes shape validation — the descriptors are only required when at least one tank was found — and is then refused with `ERR_NO_TANK_LOCATED`."

        Design: Difficulty/boundary_precision_check/sweep_survey_with_zero_tanks_detected_is_a_zero_count_edge
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        _, project = self._connecticut_project()

        response = api.record_sweep_survey(
            project["id"],
            {"survey_method": "MAGNETOMETER", "tanks_detected_count": 0},
            FIELD_TECHNICIAN,
        )
        validate_error(response, ApiErrorId.ERR_NO_TANK_LOCATED.value, 409)

    def test_refused_sweep_writes_no_survey_derived_fields(self, api):
        """PRD §3.1: "Both fields are read-only outputs of the survey; the method actually executed is captured separately, as `decommission_method`, when the crew begins work."
        PRD §3.1: "`baseline_scope_cubic_yards` is the contracted excavation volume before any change order and defaults to 8.0 cubic yards; `excavation_limit_cubic_yards` is the hard ceiling that change-order approvals are measured against and defaults to 40.0 cubic yards."

        Design: Difficulty/boundary_precision_check/sweep_survey_with_zero_tanks_detected_is_a_zero_count_edge
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        _, project = self._connecticut_project()
        api.record_sweep_survey(
            project["id"],
            {"survey_method": "MAGNETOMETER", "tanks_detected_count": 0},
            FIELD_TECHNICIAN,
        )

        stored = fx.read_project(project["id"])
        assert stored["status"] == "INTAKE", (
            f"the project must stay in INTAKE, got {stored['status']}"
        )
        assert stored["tanks_detected_count"] is None, (
            f"the refused count must not be persisted, got {stored['tanks_detected_count']}"
        )
        assert stored["method_score"] is None, (
            f"no score is derived without a located tank, got {stored['method_score']}"
        )
        assert stored["recommended_method"] is None, (
            "no recommendation is derived either, got "
            f"{stored['recommended_method']}"
        )
        assert stored["survey_completed_at"] is None, (
            "no completion instant is stamped, got "
            f"{stored['survey_completed_at']}"
        )
        assert stored["baseline_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "the omitted baseline takes its default, got "
            f"{stored['baseline_scope_cubic_yards']}"
        )
        assert stored["excavation_limit_cubic_yards"] == pytest.approx(
            40.0, abs=0.01
        ), (
            "the omitted ceiling takes its default, got "
            f"{stored['excavation_limit_cubic_yards']}"
        )


class TestHoldingTimeBoundary:
    #: Exactly 336 hours after the aliquots were collected.
    AT_THE_LIMIT = "2026-08-20T13:00:00Z"
    #: One minute beyond it, which is 336.02 hours once the figure is rounded.
    PAST_THE_LIMIT = "2026-08-20T13:01:00Z"

    def _two_dispatched_aliquots(self):
        ctx = fx.project_at_sampling(
            property_overrides={
                "state_code": "NY",
                "county_code": "SUFFOLK",
                "street_address": "88 Bayberry Drive",
            }
        )
        ctx["sample_a"] = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="NORTH_SIDEWALL",
            depth_inches=72,
        )
        ctx["sample_b"] = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="SOUTH_SIDEWALL",
            depth_inches=72,
        )
        fx.dispatch_sample(ctx["sample_a"]["id"])
        fx.dispatch_sample(ctx["sample_b"]["id"])
        return ctx

    def test_holding_time_exactly_at_the_permitted_maximum_is_compliant(self, api):
        """PRD §3.6: "An elapsed figure exactly equal to the permitted maximum is compliant and receipt proceeds."
        PRD §3.6: "Second, the holding time is computed and checked: `holding_time_elapsed_hours` is the interval from `collected_at` to the current logical instant expressed in hours and rounded half up to two decimal places."
        PRD §3.6: "`holding_time_hours` defaults to 336, which is the fourteen days a petroleum aliquot may sit between collection and laboratory receipt."

        Design: Difficulty/boundary_precision_check/holding_time_exactly_at_limit_is_compliant_one_second_past_is_not
        """
        ctx = self._two_dispatched_aliquots()
        fx.set_clock(self.AT_THE_LIMIT)

        received = fx.receive_sample(ctx["sample_a"]["id"], ctx["laboratory"]["id"])
        assert received["holding_time_elapsed_hours"] == pytest.approx(
            336.0, abs=0.01
        ), (
            "fourteen days is exactly 336.0 hours, got "
            f"{received['holding_time_elapsed_hours']}"
        )
        assert received["status"] == "AT_LAB", (
            f"receipt proceeds at the limit, got {received['status']}"
        )
        assert received["qc_flag"] == "NONE", (
            f"nothing is wrong with this aliquot, got {received['qc_flag']}"
        )
        assert parse_instant(received["received_at"]) == parse_instant(
            self.AT_THE_LIMIT
        ), (
            "the receipt instant is stamped from the logical clock, got "
            f"{received['received_at']}"
        )

    def test_holding_time_past_the_rounded_maximum_invalidates_the_aliquot(
        self, api
    ):
        """PRD §3.6: "If that figure **strictly exceeds** the lab's `holding_time_hours`, the aliquot is legally worthless, and the server records that fact before refusing: the sample transitions `IN_TRANSIT → INVALIDATED`, its `qc_flag` is set to `HOLDING_TIME_EXCEEDED`, `holding_time_elapsed_hours` is persisted, `received_at` is left null, the project's blocker list is recomputed and now names `INVALIDATED_SAMPLE_WITHOUT_RETEST`, and only then is the receipt rejected with `ERR_HOLDING_TIME_EXCEEDED`."
        PRD §2.10: "A holding time exactly equal to the laboratory's permitted maximum is compliant."
        PRD §2.9: "The laboratory timing figures `holding_time_elapsed_hours` and `turnaround_hours` are each rounded half up to 2 decimal places *before* they are compared to their thresholds."

        Design: Difficulty/boundary_precision_check/holding_time_exactly_at_limit_is_compliant_one_second_past_is_not
        """
        ctx = self._two_dispatched_aliquots()
        fx.set_clock(self.AT_THE_LIMIT)
        fx.receive_sample(ctx["sample_a"]["id"], ctx["laboratory"]["id"])

        fx.set_clock(self.PAST_THE_LIMIT)
        response = api.create_custody_event(
            ctx["sample_b"]["id"],
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_HOLDING_TIME_EXCEEDED.value, 409)

        stale = fx.read_sample(ctx["sample_b"]["id"])
        assert stale["status"] == "INVALIDATED", (
            "the lapse is recorded before the refusal, got "
            f"{stale['status']}"
        )
        assert stale["qc_flag"] == "HOLDING_TIME_EXCEEDED", (
            f"the quality flag must name the lapse, got {stale['qc_flag']}"
        )
        assert stale["received_at"] is None, (
            f"the lab never took custody, got {stale['received_at']}"
        )
        blockers = fx.read_project(ctx["project"]["id"])["nfa_blockers"]
        assert "INVALIDATED_SAMPLE_WITHOUT_RETEST" in blockers, (
            f"the discredited aliquot must block closure, got {blockers}"
        )
