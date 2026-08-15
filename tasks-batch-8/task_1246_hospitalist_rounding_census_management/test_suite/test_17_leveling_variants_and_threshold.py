"""Census-leveling variant divergence, assignment-accept side effects,
distribution_eligible threshold trigger, and immediate read-after-write
consistency.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, discharge_patient,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _leveling_scenario(api):
    """H1 holds P1, P2 (census 2); H2 empty; P3 OFFERED to H2 un-accepted.

    Uses the shift-window trick: H2's shift starts later, so the early
    admissions can only go to H1; once the clock enters H2's coverage, P3 is
    offered to H2.
    """
    h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
    h2 = create_hospitalist("H Two", "INTERNAL_MEDICINE", max_census_cap=16)
    create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
    create_shift(h2["id"], "DAY", "2026-05-01T10:00:00Z", "2026-05-01T22:00:00Z", activate=True)
    set_clock("2026-05-01T09:00:00Z")
    p1 = create_patient(mrn="K005", acuity="MEDIUM", admit_source="ED",
                        stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
    admit_and_accept(p1["id"])
    p2 = create_patient(mrn="K006", acuity="LOW", admit_source="DIRECT",
                        stay_type="INPATIENT", admitted_at="2026-05-01T08:05:00Z")
    admit_and_accept(p2["id"])
    set_clock("2026-05-01T11:00:00Z")
    p3 = create_patient(mrn="K007", acuity="HIGH", admit_source="ED",
                        stay_type="INPATIENT", admitted_at="2026-05-01T08:10:00Z")
    a3 = get_success_data(api.create_admission({"patient_id": p3["id"]}, ADMIN))
    assert a3["status"] == "OFFERED"
    assert a3["offered_to_hospitalist_id"] == h2["id"]
    return h1, h2, p1, p2, p3, a3


class TestLevelingForwardVsChronologicalDiverge:
    """Corner instance: leveling_forward_vs_chronological_diverge."""

    def test_variants_diverge_with_pending_offer(self, api):
        """PRD §3.4: "Each row of the report's `rows` array carries two
        variants side by side: `deviation_forward`, computed on the projected
        census, and `deviation_chronological`, computed on the raw current
        census — identical inputs yield different values whenever outstanding
        offers or horizon-window discharge orders exist".
        PRD §3.4: "each deviation is the projected census minus
        `group_avg_census`, divided by the larger of 1 and
        `group_avg_census`, rounded half up to four decimals."

        Design: Corner/calculations/leveling_forward_vs_chronological_diverge
        """
        h1, h2, p1, p2, p3, a3 = _leveling_scenario(api)
        report = get_success_data(api.get_census_leveling_report(ADMIN))
        assert report["group_avg_census"] == pytest.approx(1.0, abs=0.0001)
        rows = {r["hospitalist_id"]: r for r in report["rows"]}
        # H2: current 0, projected 1 -> deviation_forward (1-1)/1 = 0.0;
        # chronological (0-1)/1 = -1.0. Variants diverge on identical inputs.
        assert rows[h2["id"]]["current_census"] == 0
        assert rows[h2["id"]]["projected_census"] == 1
        assert rows[h2["id"]]["deviation_forward"] == pytest.approx(0.0, abs=0.0001)
        assert rows[h2["id"]]["deviation_chronological"] == pytest.approx(-1.0, abs=0.0001)
        # H1: current 2, projected 2 -> both variants (2-1)/1 = 1.0
        assert rows[h1["id"]]["deviation_forward"] == pytest.approx(1.0, abs=0.0001)
        assert rows[h1["id"]]["deviation_chronological"] == pytest.approx(1.0, abs=0.0001)


class TestAssignmentAcceptSideEffects:
    """Corner instance: assignment_accept_side_effects."""

    def test_accept_fans_out_all_effects(self, api):
        """PRD §3.3: "A successful acceptance is a fan-out of effects in one
        mutation. A new assignment is born `ACTIVE` for the patient and the
        offered hospitalist, its `assigned_at` stamped and its
        `continuity_flag` set from the same 30-day continuity predicate the
        selector uses. The admission becomes terminally `ACCEPTED`, recording
        `assignment_id` and `decided_at`. The hospitalist's `pending_offers`
        decrements by one and `current_census` increments by one".
        PRD §3.3: "its `continuity_flag` set from the same 30-day continuity
        predicate" — a fresh admission has no CLOSED pairing, so the flag is
        false.

        Design: Corner/state_machines/assignment_accept_side_effects
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S009", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h1["id"]
        # pending_offers incremented by the offer
        h_mid = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        assert h_mid["pending_offers"] == 1

        acc = get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"])))
        assert acc["status"] == "ACCEPTED"
        asg_id = acc["assignment_id"]
        assert asg_id is not None

        asg = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg["status"] == "ACTIVE"
        assert asg["continuity_flag"] is False
        assert asg["assigned_at"] is not None

        h_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        assert h_now["current_census"] == 1
        assert h_now["pending_offers"] == 0


class TestRateThresholdDistributionEligibleFlip:
    """Corner instance: rate_threshold_distribution_eligible_flip."""

    def test_cap_crossing_flips_flag_and_discharge_resets(self, api):
        """PRD §2.5: "Capacity flips are threshold events, not gradual ones.
        When an acceptance raises a hospitalist's `current_census` to exactly
        equal `max_census_cap`, `distribution_eligible` flips to false in the
        same mutation; when a closure drops `current_census` back below the
        cap, `distribution_eligible` is recomputed and flips back to true."
        PRD §3.3: "When the pool is empty the admission simply remains
        `QUEUED`".

        Design: Corner/complexity_layers/rate_threshold_distribution_eligible_flip
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=1)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="L002", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        # census 1 == cap 1 -> distribution_eligible false
        h_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        assert h_now["current_census"] == 1
        assert h_now["distribution_eligible"] is False
        # New admission queues (pool empty: H1 excluded by the flag)
        p2 = create_patient(mrn="L003", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:05:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        assert a2["status"] == "QUEUED"
        # Discharge P1 -> census drops below cap -> flag resets
        discharge_patient(p1["id"], h1["id"])
        h_after = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        assert h_after["current_census"] == 0
        assert h_after["distribution_eligible"] is True


class TestImmediateReadAfterWrite:
    """Corner instance: immediate_read_after_write."""

    def test_accept_then_immediate_reads_agree(self, api):
        """PRD §1: "Every mutation and its cascaded side effects are
        immediately consistent — visible in the triggering response and in
        any subsequent read."
        PRD §3.3: "The admission becomes terminally `ACCEPTED`, recording
        `assignment_id` and `decided_at`."
        PRD §3.3: "A new assignment is born `ACTIVE`".

        Design: Corner/consistency_model/immediate_read_after_write
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="L004", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        acc = get_success_data(api.accept_admission(
            a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])
        ))
        assert acc["status"] == "ACCEPTED"
        asg_id = acc["assignment_id"]
        assert asg_id is not None
        # Immediate re-reads agree
        a_now = get_success_data(api.get_admission(a1["id"], ADMIN))
        assert a_now["status"] == "ACCEPTED"
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "ACTIVE"
