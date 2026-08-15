"""Facility load scoring: dual variants, pinned rounding order, and
compensating invariants across hold create/release and cancel/decline."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bed,
    add_physician,
    assert_instant_equal,
    create_accepted_request,
    create_admission,
    create_boarding_record_payload,
    create_facility,
    create_request_with_hold,
    create_transfer_request,
    get_success_data,
    make_accepting_physician_headers,
    make_coordinator_headers,
    place_hold,
    respond_consult,
    dispatch_consult,
    set_clock,
    setup_facility_with_physician,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _build_load_facility(api, name):
    """The five-bed fixture: 3 occupied (one of them an ED bed with an open
    boarding record), 1 held by an inbound HOLD_PLACED request, 1 available.

    Resulting counters: staffed 5, occupied 3, held 1, boarders 1, inbound 1.
    """
    facility = create_facility(name=name)
    b1 = add_bed(facility["id"], unit="ICU-1", label="B1", service="CARDIAC",
                 max_acuity="ACUITY_1_CRITICAL", isolation_capability="AIRBORNE")
    b2 = add_bed(facility["id"], unit="ICU-1", label="B2", service="CARDIAC",
                 max_acuity="ACUITY_1_CRITICAL", isolation_capability="AIRBORNE")
    b3 = add_bed(facility["id"], unit="ED-1", label="B3", service="MEDICAL")
    b4 = add_bed(facility["id"], unit="M-1", label="B4", service="MEDICAL")
    add_bed(facility["id"], unit="N-1", label="B5", service="NEURO",
            max_acuity="ACUITY_2_STEPDOWN")
    create_admission(facility["id"], b1["id"], patient_ref="P1",
                     acuity="ACUITY_1_CRITICAL", service="CARDIAC")
    adm3 = create_admission(facility["id"], b3["id"], patient_ref="P3",
                            service="MEDICAL")
    create_admission(facility["id"], b4["id"], patient_ref="P4",
                     service="MEDICAL")
    get_success_data(api.create_boarding_record(
        facility["id"], create_boarding_record_payload(adm3["id"]), COORD))
    physician = add_physician(facility["id"], full_name="Dr Card",
                              services=("CARDIAC",))
    create_request_with_hold(
        facility["id"], physician["id"], b2["id"], patient_ref="PT1",
        acuity="ACUITY_3_MEDICAL_SURGICAL", service="CARDIAC")
    return facility


class TestDualVariantLoadScore:
    def test_load_score_raw_vs_weighted_values(self, api):
        """PRD §3.2: "The raw score, exposed as `load_score_raw` on the
        facility, is one hundred times the number of staffed `OCCUPIED` beds
        divided by `staffed_beds`, rounded half-up to one decimal place".
        PRD §3.2: "The pressure-weighted score, exposed as
        `load_score_weighted`, builds a pressure numerator in which occupied
        beds count in full, each staffed `HELD` bed contributes one half, each
        boarding waiter contributes three quarters, and each inbound transfer
        in a non-terminal status contributes one half".

        Design: Difficulty/dual_variant_calc/load_score_raw_vs_weighted_variants
        """
        set_clock()
        facility = _build_load_facility(api, "Load Facility")
        data = validate_success(
            api.get_facility_load_score(facility["id"], COORD))
        assert data["staffed_beds"] == 5
        assert data["occupied_beds"] == 3
        assert data["held_beds"] == 1
        assert data["boarding_waiters"] == 1
        assert data["active_inbound_transfers"] == 1
        # raw: 100 * 3/5 = 60.0; weighted: 100 * (3 + 0.5 + 0.75 + 0.5)/5 = 95.0
        assert data["raw_occupancy_pct"] == pytest.approx(60.0, abs=0.01)
        assert data["pressure_weighted_pct"] == pytest.approx(95.0, abs=0.01)

    def test_weighted_variant_alone_crosses_diversion_threshold(self, api):
        """PRD §3.2: "The flag `diversion_recommended` turns true exactly when
        the weighted score reaches or exceeds 95.0 — a score of 95.0 triggers
        it, and anything below does not."
        PRD §3.2: "the two variants diverge whenever any held bed, boarder, or
        inbound transfer exists."

        Design: Difficulty/dual_variant_calc/load_score_raw_vs_weighted_variants
        """
        set_clock()
        facility = _build_load_facility(api, "Load Facility 2")
        data = validate_success(
            api.get_facility_load_score(facility["id"], COORD))
        assert data["raw_occupancy_pct"] == pytest.approx(60.0, abs=0.01)
        assert data["diversion_recommended"] is True, (
            "weighted 95.0 reaches the threshold even though raw sits at 60.0")


class TestServiceWeightedOccupancy:
    def _build_occupancy_facility(self, api, name):
        facility = create_facility(name=name)
        c1 = add_bed(facility["id"], unit="C-1", label="C1", service="CARDIAC",
                     max_acuity="ACUITY_1_CRITICAL")
        add_bed(facility["id"], unit="C-1", label="C2", service="CARDIAC",
                max_acuity="ACUITY_1_CRITICAL")
        add_bed(facility["id"], unit="C-1", label="C3", service="CARDIAC",
                max_acuity="ACUITY_1_CRITICAL")
        m1 = add_bed(facility["id"], unit="M-1", label="M1", service="MEDICAL")
        m2 = add_bed(facility["id"], unit="M-1", label="M2", service="MEDICAL")
        add_bed(facility["id"], unit="M-2", label="M3", service="MEDICAL")
        add_bed(facility["id"], unit="N-1", label="N1", service="NEURO",
                max_acuity="ACUITY_2_STEPDOWN")
        create_admission(facility["id"], c1["id"], patient_ref="PC",
                         acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        create_admission(facility["id"], m1["id"], patient_ref="PM1",
                         service="MEDICAL")
        create_admission(facility["id"], m2["id"], patient_ref="PM2",
                         service="MEDICAL")
        return facility

    def test_service_weighted_occupancy_rounding_order(self, api):
        """PRD §3.2: "The rounding order is pinned: per-service percentages are
        rounded first, then the weighted aggregate is rounded; the alternative
        aggregate-then-round order is documented and explicitly not used,
        because it yields different values."
        PRD §3.2: "each is multiplied by a fixed service weight — 0.5 for
        `CARDIAC`, 0.3 for `MEDICAL`, and 0.2 each for `NEURO`, `TRAUMA`,
        `SURGICAL`, and `ONCOLOGY`".

        Design: Difficulty/combinatorial_formula/service_weighted_occupancy_rounding_order
        """
        set_clock()
        facility = self._build_occupancy_facility(api, "Occ Facility")
        data = validate_success(
            api.get_facility_load_score(facility["id"], COORD))
        # CARDIAC 1/3 -> 33.3; MEDICAL 2/3 -> 66.7; NEURO 0/1 -> 0.0.
        # Weighted: (0.5*33.3 + 0.3*66.7 + 0.2*0.0) / (0.5+0.3+0.2) = 36.65 -> 36.7
        assert data["service_weighted_occupancy_pct"] == pytest.approx(36.7, abs=0.01)

    def test_raw_occupancy_differs_from_service_weighted(self, api):
        """PRD §3.2: "the alternative aggregate-then-round order is documented
        and explicitly not used, because it yields different values."
        PRD §3.2: "The raw score, exposed as `load_score_raw` on the facility,
        is one hundred times the number of staffed `OCCUPIED` beds divided by
        `staffed_beds`, rounded half-up to one decimal place".

        Design: Difficulty/combinatorial_formula/service_weighted_occupancy_rounding_order
        """
        set_clock()
        facility = self._build_occupancy_facility(api, "Occ Facility 2")
        data = validate_success(
            api.get_facility_load_score(facility["id"], COORD))
        # 3 occupied of 7 staffed => raw 42.9; pinned service-weighted is 36.7,
        # so the same payload makes the divergence visible.
        assert data["raw_occupancy_pct"] == pytest.approx(42.9, abs=0.01)
        assert data["service_weighted_occupancy_pct"] == pytest.approx(36.7, abs=0.01)


class TestBedStatusCountConservation:
    def _three_bed_scenario(self, api):
        bundle = setup_facility_with_physician(name="Invariant Facility")
        facility, physician = bundle["facility"], bundle["physician"]
        b1 = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                     max_acuity="ACUITY_1_CRITICAL",
                     isolation_capability="AIRBORNE")
        add_bed(facility["id"], unit="C-1", label="B2", service="CARDIAC",
                max_acuity="ACUITY_1_CRITICAL")
        add_bed(facility["id"], unit="C-2", label="B3", service="CARDIAC",
                max_acuity="ACUITY_1_CRITICAL")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PI1",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        return facility, b1, request

    def test_hold_create_then_release_restores_census(self, api):
        """PRD §3.4: "Its creation moves the bed from `AVAILABLE` to `HELD`
        (clearing any `cooling_until`), moves the request from `ACCEPTED` to
        `HOLD_PLACED` with a version increment, and recomputes the facility's
        bed counts and load scores."
        PRD §3.4: "Release and expiry have identical downstream effects: the
        bed returns from `HELD` to `AVAILABLE` with `cooling_until` set to the
        end time plus the bed's `turnover_minutes`, the served request falls
        back from `HOLD_PLACED` to `ACCEPTED` with a version increment (the
        placement loop reopens), and facility counts and load scores are
        recomputed."

        Design: Difficulty/compensating_invariant/bed_status_count_conservation_hold_release
        """
        set_clock()
        facility, b1, request = self._three_bed_scenario(api)
        before = validate_success(api.get_facility(facility["id"], COORD))
        assert before["available_beds"] == 3
        assert before["held_beds"] == 0
        assert before["occupied_beds"] == 0
        assert before["out_of_service_beds"] == 0
        hold = place_hold(request["id"], bed_id=b1["id"])
        during = validate_success(api.get_facility(facility["id"], COORD))
        assert during["available_beds"] == 2
        assert during["held_beds"] == 1
        get_success_data(api.release_bed_hold(
            hold["id"], make_coordinator_headers("coord_1")))
        after = validate_success(api.get_facility(facility["id"], COORD))
        assert after["available_beds"] == 3
        assert after["held_beds"] == 0

    def test_census_sum_invariant_and_cooling_recorded(self, api):
        """PRD §3.2: "`staffed_beds` counts the facility's beds flagged
        `staffed`, across all units including ED units. `occupied_beds` counts
        staffed beds in `OCCUPIED` status, `held_beds` counts staffed beds in
        `HELD` status, and `available_beds` counts staffed beds in `AVAILABLE`
        status. `out_of_service_beds` counts all beds in `OUT_OF_SERVICE`
        status regardless of the staffing flag."
        PRD §3.4: "the bed returns from `HELD` to `AVAILABLE` with
        `cooling_until` set to the end time plus the bed's `turnover_minutes`".

        Design: Difficulty/compensating_invariant/bed_status_count_conservation_hold_release
        """
        set_clock()
        facility, b1, request = self._three_bed_scenario(api)
        hold = place_hold(request["id"], bed_id=b1["id"])
        for label in ("during hold",):
            f = validate_success(api.get_facility(facility["id"], COORD))
            total = (f["available_beds"] + f["held_beds"] + f["occupied_beds"]
                     + f["out_of_service_beds"])
            assert total == f["staffed_beds"] == 3, (
                f"census conservation violated {label}: {total}")
        get_success_data(api.release_bed_hold(
            hold["id"], make_coordinator_headers("coord_1")))
        f = validate_success(api.get_facility(facility["id"], COORD))
        total = (f["available_beds"] + f["held_beds"] + f["occupied_beds"]
                 + f["out_of_service_beds"])
        assert total == f["staffed_beds"] == 3
        bed = validate_success(api.get_bed(b1["id"], COORD))
        assert bed["status"] == "AVAILABLE"
        assert_instant_equal(bed["cooling_until"], "2026-08-01T00:45:00Z")


class TestPipelineCountConservation:
    def _three_request_facility(self, api, name):
        bundle = setup_facility_with_physician(name=name)
        facility, physician = bundle["facility"], bundle["physician"]
        tr1 = create_transfer_request(facility["id"], patient_ref="PTA")
        tr2 = create_transfer_request(facility["id"], patient_ref="PTB")
        tr3 = create_transfer_request(facility["id"], patient_ref="PTC",
                                      priority="ELECTIVE")
        return facility, physician, tr1, tr2, tr3

    def test_cancel_and_decline_conserve_pipeline_count(self, api):
        """PRD §3.2: "`active_inbound_transfers` counts the facility's transfer
        requests in any non-terminal status: `INTAKE`, `CONSULT_PENDING`,
        `DECLINED`, `EXPIRED`, `ACCEPTED`, `HOLD_PLACED`, or `ASSIGNED`."
        PRD §3.3: "A coordinator may cancel a request from any non-terminal
        status — `INTAKE`, `CONSULT_PENDING`, `DECLINED`, `EXPIRED`,
        `ACCEPTED`, `HOLD_PLACED`, or `ASSIGNED` — moving it to the terminal
        `CANCELLED` status".

        Design: Difficulty/compensating_invariant/transfer_pipeline_count_conservation_cancel
        """
        set_clock()
        facility, physician, tr1, tr2, _tr3 = self._three_request_facility(
            api, "Pipeline Facility")
        get_success_data(api.cancel_transfer_request(
            tr1["id"], make_coordinator_headers("coord_1")))
        dispatch_consult(tr2["id"], physician["id"])
        respond_consult(tr2["id"], physician["id"], decision="DECLINE",
                        decline_reason="NO_CAPACITY")
        facility_after = validate_success(api.get_facility(facility["id"], COORD))
        assert facility_after["active_inbound_transfers"] == 2
        cancelled = validate_success(api.get_transfer_request(tr1["id"], COORD))
        assert cancelled["status"] == "CANCELLED"
        declined = validate_success(api.get_transfer_request(tr2["id"], COORD))
        assert declined["status"] == "DECLINED"

    def test_declined_request_remains_in_pipeline(self, api):
        """PRD §3.2: "`active_inbound_transfers` counts the facility's transfer
        requests in any non-terminal status: `INTAKE`, `CONSULT_PENDING`,
        `DECLINED`, `EXPIRED`, `ACCEPTED`, `HOLD_PLACED`, or `ASSIGNED`."
        PRD §3.3: "A `DECLINE` decision moves the request to `DECLINED`,
        records the physician-supplied `decline_reason` — one of
        `PHYSICIAN_DECLINED`, `NO_CAPACITY`, or `CLINICAL` — clears
        `accepting_physician_id` and `consult_deadline`, and increments
        `version`".

        Design: Difficulty/compensating_invariant/transfer_pipeline_count_conservation_cancel
        """
        set_clock()
        facility, physician, tr1, tr2, tr3 = self._three_request_facility(
            api, "Pipeline Facility 2")
        before = validate_success(api.get_facility(facility["id"], COORD))
        assert before["active_inbound_transfers"] == 3
        get_success_data(api.cancel_transfer_request(
            tr1["id"], make_coordinator_headers("coord_1")))
        dispatch_consult(tr2["id"], physician["id"])
        respond_consult(tr2["id"], physician["id"], decision="DECLINE",
                        decline_reason="NO_CAPACITY")
        after = validate_success(api.get_facility(facility["id"], COORD))
        # DECLINED is non-terminal (re-consultable): 2 non-terminal + 1
        # terminal == 3 created; no phantom requests appear or vanish.
        assert after["active_inbound_transfers"] == 2
        tr3_after = validate_success(api.get_transfer_request(tr3["id"], COORD))
        assert tr3_after["status"] == "INTAKE"
