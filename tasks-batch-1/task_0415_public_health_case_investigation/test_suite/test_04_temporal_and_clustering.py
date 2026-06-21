"""Temporal-window admissibility, monitoring-period overlap/adjacency, and the
outbreak-cluster count boundary.

Queue A (Difficulty): resource_temporal_overlap (exposure-window edge, overlap-vs-adjacency)
and the cluster-formation instance of boundary_precision_check.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_epi_headers,
    ApiErrorId,
    create_monitoring_period_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Queue A — resource_temporal_overlap / exposure_event_outside_closed_infectious_window
# ===========================================================================
class TestExposureEventInfectiousWindowEdge:
    """The infectious window is a closed inclusive interval; the end edge is admissible but
    one day past it is rejected."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={"presymptomatic_days": 2, "infectious_tail_days": 10}
        )
        j = jurisdiction["id"]
        # symptom onset 2026-03-10 -> window [2026-03-08, 2026-03-20]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        ke = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-E")
        return j, ke["id"]

    def test_encounter_on_closed_end_edge_accepted(self, api):
        """PRD §3.10: "The encounter is admissible only when its `encounter_date` falls inside
        the index case's closed, inclusive infectious window — that is, on or after the case's
        `infectious_start_date` and on or before its `infectious_end_date`."

        Design: Difficulty/resource_temporal_overlap/exposure_event_outside_closed_infectious_window
        """
        j, contact_id = self._setup()
        res = api.create_exposure_event(
            contact_id, {"encounter_date": "2026-03-20T00:00:00.000Z"}, make_tracer_headers(j)
        )
        validate_success(res, expected_status=201)

    def test_encounter_one_day_past_end_rejected(self, api):
        """PRD §3.10: "An encounter outside that window is rejected with
        `ERR_ENCOUNTER_OUTSIDE_INFECTIOUS_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/exposure_event_outside_closed_infectious_window
        """
        j, contact_id = self._setup()
        res = api.create_exposure_event(
            contact_id, {"encounter_date": "2026-03-21T00:00:00.000Z"}, make_tracer_headers(j)
        )
        validate_error(res, ApiErrorId.ERR_ENCOUNTER_OUTSIDE_INFECTIOUS_WINDOW.value)


# ===========================================================================
# Queue A — resource_temporal_overlap / monitoring_period_overlap_vs_adjacency_on_contact
# ===========================================================================
class TestMonitoringPeriodOverlapAdjacency:
    """A new monitoring period sharing a day with an existing non-terminal period overlaps;
    a period starting the day after the prior end is adjacent and accepted."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        ko = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-O")
        fx.schedule_monitoring(ko["id"], j, "2026-03-16T00:00:00.000Z", "2026-03-29T00:00:00.000Z")
        return j, ko["id"]

    def test_overlapping_period_rejected(self, api):
        """PRD §3.8: "A new monitoring period must not share any day with an existing non-terminal
        monitoring period (one in `SCHEDULED` or `ACTIVE`) for the same contact; an overlap is
        rejected with `ERR_MONITORING_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitoring_period_overlap_vs_adjacency_on_contact
        """
        j, contact_id = self._setup()
        # second period starts on 2026-03-29, the day the first ends -> shares a day
        res = api.create_monitoring_period(
            contact_id,
            create_monitoring_period_payload("2026-03-29T00:00:00.000Z", "2026-04-05T00:00:00.000Z"),
            make_tracer_headers(j),
        )
        validate_error(res, ApiErrorId.ERR_MONITORING_PERIOD_OVERLAP.value)

    def test_adjacent_period_accepted(self, api):
        """PRD §3.8: "Adjacency is permitted: a period whose `start_date` equals the prior
        period's `end_date` plus one day does not overlap."

        Design: Difficulty/resource_temporal_overlap/monitoring_period_overlap_vs_adjacency_on_contact
        """
        j, contact_id = self._setup()
        # adjacent period starts 2026-03-30 = first end (2026-03-29) + 1 day
        res = api.create_monitoring_period(
            contact_id,
            create_monitoring_period_payload("2026-03-30T00:00:00.000Z", "2026-04-05T00:00:00.000Z"),
            make_tracer_headers(j),
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Queue A — boundary_precision_check / cluster_forms_at_third_confirmed_case
# ===========================================================================
class TestClusterFormsAtThirdConfirmedCase:
    """With cluster_min_cases 3, two co-located CONFIRMED cases form no cluster but the third
    crosses the >= 3 boundary and creates a cluster with member_case_count 3."""

    def test_two_confirmed_form_no_cluster(self, api):
        """PRD §3.11: "if the size of the prospective group is at least the condition's
        `cluster_min_cases`, a new `OutbreakCluster` is created in `ACTIVE` status".
        PRD §3.11: "If neither condition holds, there is no cluster change and the case's
        `cluster_id` stays unset."

        Design: Difficulty/boundary_precision_check/cluster_forms_at_third_confirmed_case
        """
        program, jurisdiction, _, case_ids = fx.setup_three_colocated_confirmed_cases(
            location_id="VENUE-7", cluster_min_cases=3, cluster_window_days=14
        )
        j = jurisdiction["id"]
        # The first two are already CONFIRMED in the fixture; neither should have a cluster.
        for cid in case_ids[:2]:
            data = validate_success(api.get_case(cid, make_investigator_headers(j)))
            assert data["cluster_id"] is None, f"case {cid} clustered prematurely: {data['cluster_id']}"

    def test_third_confirmed_forms_cluster_of_three(self, api):
        """PRD §3.11: "if the size of the prospective group is at least the condition's
        `cluster_min_cases`, a new `OutbreakCluster` is created in `ACTIVE` status: its
        `condition_code` and `exposure_setting_location_id` are the shared key, ... the cluster's
        `member_case_count` is set to the size of the group".

        Design: Difficulty/boundary_precision_check/cluster_forms_at_third_confirmed_case
        """
        program, jurisdiction, _, case_ids = fx.setup_three_colocated_confirmed_cases(
            location_id="VENUE-7", cluster_min_cases=3, cluster_window_days=14
        )
        j = jurisdiction["id"]
        third = validate_success(
            api.classify_case(case_ids[-1], {"classification": "CONFIRMED"}, make_investigator_headers(j))
        )
        assert third["cluster_id"] is not None
        cluster = validate_success(api.get_cluster(third["cluster_id"], make_epi_headers()))
        assert cluster["member_case_count"] == 3, cluster["member_case_count"]
        assert cluster["status"] == "ACTIVE"
