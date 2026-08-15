"""Exchange-versus-treatment determination: rounding, boundaries, partition,
recompute currency, ordering, and read-your-writes consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_determination_partition_conserved,
    current_determination,
    get_voyage,
    list_determinations,
    post_discharge,
    post_exchange_complete,
    post_treatment_complete,
    post_uptake,
    setup_voyage_in_progress,
    validate_success,
)
from test_helpers import api_client


class TestPerEventRounding:
    def _setup_two_half_discharges(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000004", vessel_name="MV Delfin", voyage_number="V2002"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T9", volume_m3=300.0,
                    salinity_ppt=33.0)
        post_treatment_complete(vessel["id"], voyage["id"], tank_id="T9", volume_m3=300.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T9", volume_m3=100.0005,
                       occurred_at="2026-07-30T06:00:00Z")
        post_discharge(vessel["id"], voyage["id"], tank_id="T9", volume_m3=100.0005,
                       occurred_at="2026-07-30T08:00:00Z")
        return vessel, voyage

    def test_determination_rounds_each_event_volume_before_summing(
            self, api, flag_surveyor_headers):
        """PRD section 2.6: "Volumes and percentages are carried to 3 decimal places
        and rounded half up."
        PRD section 3.3: "All volumes are carried to 3 decimal places, rounded half
        up."

        Design: Difficulty/combinatorial_formula/determination_per_event_rounding_before_summation
        """
        vessel, voyage = self._setup_two_half_discharges()
        # Each 100.0005 m3 discharge is carried as 100.001; the bucket sum is
        # 100.001 + 100.001 = 200.002 (round-then-sum, not sum-then-round 200.001).
        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["treatment_compliant_volume_m3"] == pytest.approx(200.002)
        assert determination["total_discharged_volume_m3"] == pytest.approx(200.002)
        assert determination["exchange_compliant_volume_m3"] == pytest.approx(0.0)

    def test_rounded_event_volumes_carry_into_basis_classification(
            self, api, flag_surveyor_headers):
        """PRD section 3.3: "The final `determination_basis` is `TREATMENT_COMPLIANT`
        when the noncompliant volume is zero and at least some volume is
        treatment-compliant"
        PRD section 2.6: "Volumes and percentages are carried to 3 decimal places and
        rounded half up."

        Design: Difficulty/combinatorial_formula/determination_per_event_rounding_before_summation
        """
        vessel, voyage = self._setup_two_half_discharges()
        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["determination_basis"] == "TREATMENT_COMPLIANT"
        assert determination["noncompliant_volume_m3"] == pytest.approx(0.0)
        assert_determination_partition_conserved(determination)


class TestExchangeDistanceBoundary:
    def _setup_exchange_voyage(self, voyage_number, exchange_distance):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000017", vessel_name="MV Razorbill", voyage_number=voyage_number,
            bwms_type="EXCHANGE_ONLY",
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                    salinity_ppt=32.0)
        post_exchange_complete(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                               distance_from_shore_nm=exchange_distance)
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                       latitude=33.7, longitude=-118.2, distance_from_shore_nm=250)
        return vessel, voyage

    def test_exchange_at_exactly_plan_distance_is_compliant(self, api, flag_surveyor_headers):
        """PRD section 3.3: "The exchange path is satisfied when an
        `EXCHANGE_COMPLETE` exists on the same tank in the same time window, its
        `distance_from_shore_nm` is at least the governing plan's
        `exchange_distance_nm`, and its coordinates fall inside the open-ocean
        exchange area (at least 200 nautical miles from shore)."
        PRD section 3.3: "`EXCHANGE_COMPLIANT` when the noncompliant and
        treatment-compliant volumes are both zero and the exchange-compliant volume is
        positive"

        Design: Difficulty/boundary_precision_check/exchange_distance_exactly_at_plan_minimum
        """
        vessel, voyage = self._setup_exchange_voyage("V7003A", 200.0)
        determination = current_determination(vessel["id"], voyage["id"])
        # distance 200.0 >= plan exchange_distance_nm 200: the boundary is inclusive.
        assert determination["determination_basis"] == "EXCHANGE_COMPLIANT"
        assert determination["exchange_compliant_volume_m3"] == pytest.approx(400.0)

    def test_exchange_just_below_plan_distance_is_noncompliant(self, api, flag_surveyor_headers):
        """PRD section 3.3: "its `distance_from_shore_nm` is at least the governing
        plan's `exchange_distance_nm`"
        PRD section 3.3: "`NONCOMPLIANT_NO_METHOD` when the noncompliant volume is
        positive and no compliant volume exists"

        Design: Difficulty/boundary_precision_check/exchange_distance_exactly_at_plan_minimum
        """
        vessel, voyage = self._setup_exchange_voyage("V7003B", 199.999)
        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["determination_basis"] == "NONCOMPLIANT_NO_METHOD"
        assert determination["noncompliant_volume_m3"] == pytest.approx(400.0)


class TestTreatmentPreferredWhenBothSatisfied:
    def test_determination_treatment_preferred_when_both_paths_satisfied(
            self, api, flag_surveyor_headers):
        """PRD section 3.3: "For each attributed, non-exempt discharge: if only the
        treatment path is satisfied, the volume adds to
        `treatment_compliant_volume_m3`; if only the exchange path is satisfied, it
        adds to `exchange_compliant_volume_m3`; if both are satisfied, treatment is
        preferred (the more stringent standard) and the volume adds to
        `treatment_compliant_volume_m3`; if neither is satisfied, it adds to
        `noncompliant_volume_m3`."

        Design: Corner/calculations/determination_treatment_preferred_when_both_paths_satisfied
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100036", vessel_name="MV Eiderdown", voyage_number="V9404"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400, salinity_ppt=32.0)
        post_treatment_complete(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400)
        post_exchange_complete(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                               occurred_at="2026-07-29T07:00:00Z", distance_from_shore_nm=220)
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                       latitude=33.7, longitude=-118.2, distance_from_shore_nm=250)

        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["treatment_compliant_volume_m3"] == pytest.approx(400.0)
        assert determination["exchange_compliant_volume_m3"] == pytest.approx(0.0)
        assert determination["noncompliant_volume_m3"] == pytest.approx(0.0)
        assert determination["determination_basis"] == "TREATMENT_COMPLIANT"


class TestDeterminationRecompute:
    def _setup_mixed_voyage(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000027", vessel_name="MV Albatross", voyage_number="V9102"
        )
        # Tank T1: treated stream -> 300 treatment-compliant.
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300, salinity_ppt=32.0)
        post_treatment_complete(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300)
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300)
        # Tank T2: no method -> 200 noncompliant.
        post_uptake(vessel["id"], voyage["id"], tank_id="T2", volume_m3=200,
                    occurred_at="2026-07-28T07:00:00Z", salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T2", volume_m3=200,
                       occurred_at="2026-07-30T08:00:00Z")
        return vessel, voyage

    def test_mixed_partition_sums_to_total(self, api, flag_surveyor_headers):
        """PRD section 3.3: "`NONCOMPLIANT_MIXED` when the noncompliant volume is
        positive and at least one of the compliant volumes is also positive"
        PRD section 3.3: "The `total_discharged_volume_m3` is the sum of all
        `DISCHARGE` event volumes."

        Design: Difficulty/compensating_invariant/determination_partition_conserved_across_recompute
        """
        vessel, voyage = self._setup_mixed_voyage()
        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["determination_basis"] == "NONCOMPLIANT_MIXED"
        assert determination["exchange_compliant_volume_m3"] == pytest.approx(0.0)
        assert determination["treatment_compliant_volume_m3"] == pytest.approx(300.0)
        assert determination["noncompliant_volume_m3"] == pytest.approx(200.0)
        assert determination["total_discharged_volume_m3"] == pytest.approx(500.0)
        assert_determination_partition_conserved(determination)

    def test_manual_recompute_flips_is_current_and_preserves_partition(
            self, api, shore_officer_headers, flag_surveyor_headers):
        """PRD section 3.3: "Each recomputation writes a new determination row with
        `computed_at` set to the current UTC, `trigger_reason` recording why it ran,
        and `is_current` true for the newest row per voyage (only one row is current
        at a time); the voyage's `determination_id` points at the current row."
        PRD section 3.3: "A manual recompute by a `ShoreComplianceOfficer` or
        `FlagSurveyor` runs the same algorithm with trigger reason `MANUAL_RECOMPUTE`,
        updates the voyage's `determination_id`, and increments the voyage's
        `version`."

        Design: Difficulty/compensating_invariant/determination_partition_conserved_across_recompute
        """
        vessel, voyage = self._setup_mixed_voyage()
        before = list_determinations(vessel["id"], voyage["id"])
        prior_current = before[0]
        assert prior_current["determination_basis"] == "NONCOMPLIANT_MIXED"

        resp = api.recompute_determination(vessel["id"], voyage["id"], shore_officer_headers)
        recomputed = validate_success(resp, 201)
        assert recomputed["trigger_reason"] == "MANUAL_RECOMPUTE"
        assert recomputed["is_current"] is True

        after = list_determinations(vessel["id"], voyage["id"])
        assert after[0]["id"] == recomputed["id"], "newest determination must list first"
        assert after[0]["is_current"] is True
        superseded = [d for d in after if d["id"] == prior_current["id"]][0]
        assert superseded["is_current"] is False, "exactly one current row per voyage"

        for row in (after[0], superseded):
            assert row["total_discharged_volume_m3"] == pytest.approx(500.0)
            assert row["exchange_compliant_volume_m3"] == pytest.approx(0.0)
            assert row["treatment_compliant_volume_m3"] == pytest.approx(300.0)
            assert row["noncompliant_volume_m3"] == pytest.approx(200.0)

        refreshed = get_voyage(vessel["id"], voyage["id"])
        assert refreshed["determination_id"] == recomputed["id"]


class TestDeterminationListing:
    def test_determinations_list_newest_first(self, api, psc_officer_headers):
        """PRD section 4: "| GET | /vessels/{vessel_id}/voyages/{voyage_id}/determinations | List determinations for a voyage, newest first | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |"
        PRD section 3.2: "Persisting an event increments the voyage's `version` by 1
        and triggers a recomputation of the compliance determination with trigger
        reason `BALLAST_EVENT_RECORDED`."

        Design: Corner/endpoints/determinations_list_newest_first
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100051", vessel_name="MV Yellowlegs", voyage_number="V9601"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=100, salinity_ppt=32.0)

        resp = api.list_determinations(vessel["id"], voyage["id"], psc_officer_headers)
        determinations = validate_success(resp, 200)
        assert len(determinations) == 2
        assert determinations[0]["trigger_reason"] == "BALLAST_EVENT_RECORDED"
        assert determinations[0]["is_current"] is True
        assert determinations[1]["trigger_reason"] == "VOYAGE_DEPARTURE"
        assert determinations[1]["is_current"] is False


class TestImmediateConsistency:
    def test_event_post_immediately_visible_in_determination(self, api, vessel_master_headers):
        """PRD section 3.2: "Persisting an event increments the voyage's `version` by
        1 and triggers a recomputation of the compliance determination with trigger
        reason `BALLAST_EVENT_RECORDED`."
        PRD section 3.3: "The `total_discharged_volume_m3` is the sum of all
        `DISCHARGE` event volumes."

        Design: Corner/consistency_model/event_post_immediately_visible_in_determination
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100069", vessel_name="MV Twite", voyage_number="V9901"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=200, salinity_ppt=32.0)
        version_before = get_voyage(vessel["id"], voyage["id"])["version"]

        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=200,
                       occurred_at="2026-07-29T06:00:00Z")

        # The very next read reflects the persisted discharge: no lag.
        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["total_discharged_volume_m3"] == pytest.approx(200.0)
        assert determination["trigger_reason"] == "BALLAST_EVENT_RECORDED"
        assert determination["is_current"] is True

        version_after = get_voyage(vessel["id"], voyage["id"])["version"]
        assert version_after == version_before + 1
