"""Dust/noise monitoring, the work_posture stop/resume cycle, and the
tonnage ledger with diversion accounting."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_debris_ticket_payload,
    append_dust_log, stop_project_with_exceedance,
    setup_demolition_active, setup_debris_clearance, setup_final_review,
    create_and_complete_survey,
    assert_dust_log, assert_iso8601_instant,
)

SUPERVISOR = TEST_USERS["site_supervisor_headers"]
HAULER = TEST_USERS["hauling_dispatcher_headers"]
INSPECTOR = TEST_USERS["municipal_inspector_headers"]
MONITOR = TEST_USERS["environmental_monitor_headers"]


class TestDustExposureFormula:
    def test_dust_exposure_multi_input_tiered_formula(self):
        """PRD §3.8: "The wind contributes a multiplier: 0.5 when
        `wind_speed_mph` is below 5, 1.0 from 5 up to and including 12, 1.6 above
        12 up to and including 20, and 2.4 above 20. The raw exposure is the
        product of `measured_value`, the wind multiplier, and `duration_hours`;
        the raw figure is capped at 1000, and the capped value divided by 10
        yields the `exposure_score`, reported to one decimal place. An event
        whose score reaches 75.0 is flagged `is_exceedance` true. Every event,
        exceedance or not, adds its score into the project's
        `cumulative_exposure_score`."

        Design: Difficulty/combinatorial_formula/dust_exposure_multi_input_tiered_formula
        """
        ctx = setup_demolition_active(name="Dust Lot", address="3 Birch St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        # Identical measured value and duration; only the wind tier differs.
        log1 = append_dust_log(pid, measured_value=100, wind_speed_mph=10, duration_hours=5)
        assert log1["exposure_score"] == 50.0  # 100 * 1.0 * 5 / 10
        assert log1["is_exceedance"] is False
        mid = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert mid["work_posture"] == "WORKABLE"
        log2 = append_dust_log(pid, measured_value=100, wind_speed_mph=15, duration_hours=5)
        assert log2["exposure_score"] == 80.0  # 100 * 1.6 * 5 / 10
        assert log2["is_exceedance"] is True
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "STOPPED"
        assert project["cumulative_exposure_score"] == 130.0

    def test_wind_factor_tier_boundaries(self):
        """PRD §3.8: "The wind contributes a multiplier: 0.5 when
        `wind_speed_mph` is below 5, 1.0 from 5 up to and including 12, 1.6 above
        12 up to and including 20, and 2.4 above 20."

        Design: Corner/calculations/wind_factor_tier_boundaries
        """
        ctx = setup_demolition_active(name="Wind", address="34 Pine St")
        pid = ctx["project"]["id"]
        expected = [
            (4.99, 0.5),   # below 5 -> 0.5
            (5.0, 1.0),    # [5, 12] inclusive
            (12.0, 1.0),
            (12.01, 1.6),  # (12, 20]
            (20.0, 1.6),
            (20.01, 2.4),  # above 20
        ]
        for wind, score in expected:
            log = append_dust_log(pid, measured_value=10, wind_speed_mph=wind, duration_hours=1)
            assert log["exposure_score"] == score, f"wind {wind}: expected {score}, got {log['exposure_score']}"
            assert log["is_exceedance"] is False
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["cumulative_exposure_score"] == 8.1  # 0.5+1.0+1.0+1.6+1.6+2.4

    def test_exposure_score_raw_cap_applies(self):
        """PRD §3.8: "The raw exposure is the product of `measured_value`, the
        wind multiplier, and `duration_hours`; the raw figure is capped at 1000,
        and the capped value divided by 10 yields the `exposure_score`, reported
        to one decimal place."
        PRD §2.5: "a dust event becomes an exceedance at an exposure score of
        75.0 or higher"

        Design: Corner/calculations/exposure_score_raw_cap_applies
        """
        ctx = setup_demolition_active(name="Cap", address="38 Pine St")
        pid = ctx["project"]["id"]
        log = append_dust_log(pid, measured_value=500, wind_speed_mph=25, duration_hours=2,
                              reading_type="PM10")
        # raw 500 * 2.4 * 2 = 2400 -> capped to 1000 -> score 100.0.
        assert log["exposure_score"] == 100.0
        assert log["is_exceedance"] is True
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "STOPPED"

    def test_dust_threshold_exactly_75_is_exceedance(self):
        """PRD §2.5: "a dust event becomes an exceedance at an exposure score of
        75.0 or higher"
        PRD §3.8: "An event whose score reaches 75.0 is flagged `is_exceedance`
        true."

        Design: Difficulty/boundary_precision_check/dust_threshold_exactly_75_is_exceedance
        """
        ctx = setup_demolition_active(name="Boundary Dust", address="41 Elm St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        # Scores are reported to one decimal place (PRD §2.5/§3.8), so the
        # just-below case is constructed to land exactly on 74.9:
        # 93.625 * 1.0 * 8 / 10 = 74.9.
        just_below = append_dust_log(pid, measured_value=93.625, wind_speed_mph=10,
                                     duration_hours=8)
        assert just_below["exposure_score"] == 74.9
        assert just_below["is_exceedance"] is False
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "WORKABLE"
        # Exactly 75.0: 93.75 * 1.0 * 8 / 10 = 75.0 — the boundary is inclusive.
        exactly = append_dust_log(pid, measured_value=93.75, wind_speed_mph=10,
                                  duration_hours=8)
        assert exactly["exposure_score"] == 75.0
        assert exactly["is_exceedance"] is True
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "STOPPED"

    def test_dust_threshold_just_above_75_stops_project(self):
        """PRD §2.5: "a dust event becomes an exceedance at an exposure score of
        75.0 or higher"
        PRD §3.8: "Every event, exceedance or not, adds its score into the
        project's `cumulative_exposure_score`."

        Design: Difficulty/boundary_precision_check/dust_threshold_exactly_75_is_exceedance
        """
        ctx = setup_demolition_active(name="Boundary75+", address="41B Elm St")
        pid = ctx["project"]["id"]
        # One step above the threshold at the reported 1-decimal precision:
        # 93.875 * 1.0 * 8 / 10 = 75.1.
        log = append_dust_log(pid, measured_value=93.875, wind_speed_mph=10, duration_hours=8)
        assert log["exposure_score"] == 75.1
        assert log["is_exceedance"] is True
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "STOPPED"
        assert project["cumulative_exposure_score"] == 75.1


    def test_dust_exposure_low_wind_tier_uses_half_factor(self):
        """PRD §3.8: "The wind contributes a multiplier: 0.5 when
        `wind_speed_mph` is below 5, 1.0 from 5 up to and including 12, 1.6 above
        12 up to and including 20, and 2.4 above 20."
        PRD §3.8: "Every event, exceedance or not, adds its score into the
        project's `cumulative_exposure_score`."

        Design: Difficulty/combinatorial_formula/dust_exposure_multi_input_tiered_formula
        """
        ctx = setup_demolition_active(name="DustLow", address="3B Birch St")
        pid = ctx["project"]["id"]
        log = append_dust_log(pid, measured_value=100, wind_speed_mph=3, duration_hours=5)
        # 100 * 0.5 * 5 / 10 = 25.0 — the below-5 tier, not the [5,12] tier.
        assert log["exposure_score"] == 25.0
        assert log["is_exceedance"] is False
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["cumulative_exposure_score"] == 25.0
        assert project["work_posture"] == "WORKABLE"


class TestDustLogEntityShape:
    def test_dust_log_is_immutable_event_entity(self):
        """PRD §2.4: "A dust-and-noise monitoring event is an **append-only**
        record: it carries `id` and `created_at` only — both `updated_at` and
        `version` are absent — and the API exposes no endpoint that updates one."
        PRD §3.8: "the server stamps `recorded_at` from the logical clock."

        Design: Corner/entities/dust_log_is_immutable_event_entity
        """
        ctx = setup_demolition_active(name="Evt", address="8 Pine St")
        pid = ctx["project"]["id"]
        log = append_dust_log(pid, measured_value=70, wind_speed_mph=3, duration_hours=1,
                              reading_type="NOISE_DB")
        assert_dust_log(log)
        assert_iso8601_instant(log["recorded_at"], "2026-08-05T09:00:00Z")
        assert log["exposure_score"] == 3.5  # 70 * 0.5 * 1 / 10
        assert log["is_exceedance"] is False


class TestWorkPostureCycle:
    def test_project_work_posture_stop_resume_cycle(self):
        """PRD §3.8: "When an event flagged `is_exceedance` is created while the
        project is in `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, `BACKFILL_PHASE`,
        or `FINAL_REVIEW`, the project's `work_posture` flips to `STOPPED` — the
        phase `status` itself does not move"
        PRD §3.8: "A `SiteSupervisor` resumes work with an optional `note`,
        flipping `work_posture` back to `WORKABLE` and incrementing `version`"

        Design: Difficulty/non_linear_state_machine/project_work_posture_stop_resume_cycle
        """
        ctx = setup_demolition_active(name="Posture Lot", address="4 Ash St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        stop_project_with_exceedance(pid)
        mid = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert mid["status"] == "DEMOLITION_ACTIVE", "phase unchanged"
        assert mid["work_posture"] == "STOPPED"
        resumed = get_success_data(api_client.resume_project(pid, {}, SUPERVISOR))
        assert resumed["status"] == "DEMOLITION_ACTIVE"
        assert resumed["work_posture"] == "WORKABLE"
        assert resumed["cumulative_exposure_score"] == 80.0

    def test_resume_when_not_stopped_rejected(self):
        """PRD §3.8: "resuming is defined for a project stopped during
        `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, or `BACKFILL_PHASE`, and is
        rejected with `ERR_INVALID_STATE` when the project is not `STOPPED`."

        Design: Difficulty/non_linear_state_machine/project_work_posture_stop_resume_cycle
        """
        ctx = setup_demolition_active(name="ResumeBad", address="4B Ash St")
        pid = ctx["project"]["id"]
        resp = api_client.resume_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_dust_exceedance_cascade_stops_work_and_cancels_inspections(self):
        """PRD §3.8: "When an event flagged `is_exceedance` is created while the
        project is in `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, `BACKFILL_PHASE`,
        or `FINAL_REVIEW`, the project's `work_posture` flips to `STOPPED` — the
        phase `status` itself does not move — every final inspection of the
        project still `SCHEDULED` is cancelled, and the project's `version`
        increments by 1."
        PRD §3.9: "A scheduled inspection never survives a work stoppage: the
        exceedance cascade of §3.8 moves every `SCHEDULED` inspection of the
        project to `CANCELLED`, its other terminal state."

        Design: Difficulty/transitive_cascade/dust_exceedance_cascade_stops_work_and_cancels_inspections
        """
        ctx = setup_final_review(name="Cascade C", address="21 Elm St",
                                 required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        log = stop_project_with_exceedance(pid)
        assert log["is_exceedance"] is True
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["work_posture"] == "STOPPED"
        assert project["status"] == "FINAL_REVIEW", "phase does not move"
        inspections = get_success_data(api_client.list_final_inspections(pid, INSPECTOR))
        assert inspections[0]["status"] == "CANCELLED"
        assert inspections[0]["id"] == ctx["inspection"]["id"]

    def test_stopped_posture_blocks_phase_transition(self):
        """PRD §3.8: "Every one of these advances requires the project to be
        `WORKABLE`; attempting one while the project is `STOPPED` is rejected
        with `ERR_PROJECT_STOPPED`."
        PRD §3.8: "While stopped, posture-gated writes fail with
        `ERR_PROJECT_STOPPED`."

        Design: Difficulty/transitive_cascade/dust_exceedance_cascade_stops_work_and_cancels_inspections
        """
        ctx = setup_demolition_active(name="StopGate", address="21B Elm St")
        pid = ctx["project"]["id"]
        stop_project_with_exceedance(pid)
        resp = api_client.transition_project(
            pid, {"action": "COMPLETE_STRUCTURE_REMOVAL"}, SUPERVISOR
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_STOPPED)

    def test_error_project_stopped_blocks_ticket_creation(self):
        """PRD §3.8: "Ticket creation is gated on the project being in
        `DEMOLITION_ACTIVE` or `DEBRIS_CLEARANCE` (else `ERR_INVALID_STATE`) and
        `WORKABLE` (else `ERR_PROJECT_STOPPED`)."
        PRD §3.8: "While stopped, posture-gated writes fail with
        `ERR_PROJECT_STOPPED`."

        Design: Corner/errors/error_project_stopped_blocks_ticket_creation
        """
        ctx = setup_demolition_active(name="Stopped", address="90 Pine St")
        pid = ctx["project"]["id"]
        stop_project_with_exceedance(pid)
        resp = api_client.create_debris_ticket(
            pid, create_debris_ticket_payload(ticket_number="T-X", gross_tons=5.0), HAULER
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_STOPPED)


class TestTicketLedgerAndDiversion:
    def test_ticket_create_requires_demolition_phase(self):
        """PRD §3.8: "Ticket creation is gated on the project being in
        `DEMOLITION_ACTIVE` or `DEBRIS_CLEARANCE` (else `ERR_INVALID_STATE`) and
        `WORKABLE` (else `ERR_PROJECT_STOPPED`)."

        Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_demolition_phase
        """
        project = get_success_data(
            api_client.create_project(
                {"name": "Phase Lot", "address": "71 Elm St", "lot_area_sqft": 20000},
                TEST_USERS["contractor_admin_headers"],
            )
        )
        create_and_complete_survey(project["id"])
        resp = api_client.create_debris_ticket(
            project["id"], create_debris_ticket_payload(ticket_number="T-X", gross_tons=5.0),
            HAULER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert after["in_transit_tons"] == 0

    def test_ticket_create_allowed_in_debris_clearance_phase(self):
        """PRD §3.8: "Ticket creation is gated on the project being in
        `DEMOLITION_ACTIVE` or `DEBRIS_CLEARANCE` (else `ERR_INVALID_STATE`) and
        `WORKABLE` (else `ERR_PROJECT_STOPPED`). A new ticket is `MANIFESTED`,
        and the project's `in_transit_tons` rises by its `gross_tons`."

        Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_demolition_phase
        """
        ctx = setup_debris_clearance(name="PhaseOk", address="71B Elm St")
        pid = ctx["project"]["id"]
        created = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-OK", gross_tons=5.0), HAULER)
        )
        assert created["status"] == "MANIFESTED"
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["in_transit_tons"] == 5.0

    def test_diversion_rate_sum_then_divide_rounding(self):
        """PRD §3.8: "The `diversion_rate` is then `diverted_tons` divided by the
        sum of `landfill_tons` and `diverted_tons`, rounded half-up exactly once
        to four decimal places — and zero whenever that denominator is zero. It
        is explicitly the ratio of the summed totals, never the average of
        per-ticket rates."
        PRD §3.8: "The `diversion_tier` reads `GOLD` when the rate reaches
        0.7500, `SILVER` when it reaches 0.5000, and `STANDARD` otherwise."

        Design: Difficulty/combinatorial_formula/diversion_rate_sum_then_divide_rounding
        """
        ctx = setup_demolition_active(name="Diversion Lot", address="7 Cedar St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        tk1 = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-1", gross_tons=10.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk1["id"], {"action": "RECEIVE", "diverted_tons": 4.0}, HAULER)
        )
        tk2 = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(
                    ticket_number="T-2", facility_type="RECYCLING",
                    material_class="CONCRETE", gross_tons=1.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk2["id"], {"action": "RECEIVE", "diverted_tons": 0.9}, HAULER)
        )
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        # Sum-then-divide: round_half_up(4.9/11, 4) == 0.4455 — averaging the
        # per-ticket rates (0.4 + 0.9)/2 == 0.65 would wrongly yield SILVER.
        assert project["diversion_rate"] == 0.4455
        assert project["diversion_tier"] == "STANDARD"
        assert project["landfill_tons"] == 6.1
        assert project["diverted_tons"] == 4.9

    def test_diversion_rate_zero_denominator_reads_zero(self):
        """PRD §3.8: "The `diversion_rate` is then `diverted_tons` divided by the
        sum of `landfill_tons` and `diverted_tons`, rounded half-up exactly once
        to four decimal places — and zero whenever that denominator is zero."
        PRD §3.8: "The denominator population is tickets in `RECEIVED`,
        `DISPUTED`, or `RECONCILED`"

        Design: Difficulty/combinatorial_formula/diversion_rate_sum_then_divide_rounding
        """
        ctx = setup_demolition_active(name="DivZero", address="7B Cedar St")
        pid = ctx["project"]["id"]
        # A MANIFESTED ticket is outside the denominator population.
        get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-0", gross_tons=10.0), HAULER)
        )
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["diversion_rate"] == 0
        assert project["diversion_tier"] == "STANDARD"
        assert project["in_transit_tons"] == 10.0

    def test_diversion_tier_gold_at_exactly_0_75(self):
        """PRD §3.8: "The `diversion_tier` reads `GOLD` when the rate reaches
        0.7500, `SILVER` when it reaches 0.5000, and `STANDARD` otherwise."
        PRD §2.5: "the diversion tiers split at 0.7500 and 0.5000"

        Design: Corner/calculations/diversion_tier_gold_at_exactly_0_75
        """
        ctx = setup_demolition_active(name="Gold", address="42 Pine St")
        pid = ctx["project"]["id"]
        for i, material in enumerate(("METAL", "CONCRETE"), start=1):
            tk = get_success_data(
                api_client.create_debris_ticket(
                    pid, create_debris_ticket_payload(
                        ticket_number=f"T-{i}", facility_type="RECYCLING",
                        material_class=material, gross_tons=10.0), HAULER)
            )
            get_success_data(
                api_client.transition_debris_ticket(
                    tk["id"], {"action": "RECEIVE", "diverted_tons": 7.5}, HAULER)
            )
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["diversion_rate"] == 0.75  # 15.0 / 20.0
        assert project["diversion_tier"] == "GOLD", "0.7500 boundary is inclusive"

    def test_ticket_receive_twice_rejected(self):
        """PRD §2.9: "the entity's state machine allows the requested transition
        from its current state ... violations surface as `ERR_INVALID_STATE`"
        PRD §3.8: "The project's counters move in step: `in_transit_tons` falls
        by the `gross_tons`, `landfill_tons` rises by the `disposed_tons`, and
        `diverted_tons` rises by the diverted amount."

        Design: Corner/state_machines/ticket_receive_twice_rejected
        """
        ctx = setup_demolition_active(name="Idem", address="24 Pine St")
        pid = ctx["project"]["id"]
        tk = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-1", gross_tons=10.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk["id"], {"action": "RECEIVE", "diverted_tons": 4.0}, HAULER)
        )
        resp = api_client.transition_debris_ticket(
            tk["id"], {"action": "RECEIVE", "diverted_tons": 4.0}, HAULER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["landfill_tons"] == 6.0, "counters must not double-apply"

    def test_ticket_diverted_exceeds_gross_rejected(self):
        """PRD §3.8: "Receiving a ticket takes a payload `diverted_tons` — the
        tonnage diverted from landfill — which must lie between zero and the
        ticket's `gross_tons` inclusive (else `ERR_TICKET_WEIGHT_INVALID`)"

        Design: Corner/validations/ticket_diverted_exceeds_gross_rejected
        """
        ctx = setup_demolition_active(name="Weights", address="60 Pine St")
        pid = ctx["project"]["id"]
        tk_a = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-A", gross_tons=10.0), HAULER)
        )
        tk_b = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(
                    ticket_number="T-B", facility_type="RECYCLING",
                    material_class="METAL", gross_tons=5.0), HAULER)
        )
        resp = api_client.transition_debris_ticket(
            tk_a["id"], {"action": "RECEIVE", "diverted_tons": 11.0}, HAULER
        )
        validate_error(resp, ApiErrorId.ERR_TICKET_WEIGHT_INVALID)
        full = get_success_data(
            api_client.transition_debris_ticket(
                tk_b["id"], {"action": "RECEIVE", "diverted_tons": 5.0}, HAULER)
        )
        assert full["status"] == "RECEIVED"
        assert full["disposed_tons"] == 0.0, "full diversion leaves zero disposed"

    def test_reconcile_delta_cap_boundary(self):
        """PRD §3.8: "the corrections may deviate from the ticket's current
        figures by at most 2.0 tons on either measure (else
        `ERR_RECONCILE_DELTA_EXCEEDED`), and the corrected diverted figure must
        lie between zero and the corrected gross figure inclusive (else
        `ERR_TICKET_WEIGHT_INVALID`). A successful reconciliation moves the
        ticket to the terminal `RECONCILED`, rewrites its tonnage figures,
        adjusts the project counters by the deltas, and recomputes the diversion
        math."

        Design: Corner/calculations/reconcile_delta_cap_boundary
        """
        ctx = setup_demolition_active(name="Delta", address="46 Pine St")
        pid = ctx["project"]["id"]
        tk1 = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-1", gross_tons=10.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk1["id"], {"action": "RECEIVE", "diverted_tons": 4.0}, HAULER)
        )
        tk2 = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-2", material_class="WOOD",
                                                  gross_tons=8.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk2["id"], {"action": "RECEIVE", "diverted_tons": 3.0}, HAULER)
        )
        # Delta 2.5 on gross exceeds the 2.0 cap.
        resp = api_client.transition_debris_ticket(
            tk1["id"],
            {"action": "RECONCILE", "corrected_gross_tons": 12.5, "corrected_diverted_tons": 4.0},
            HAULER,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILE_DELTA_EXCEEDED)
        # Delta exactly 2.0 is allowed.
        ok = get_success_data(
            api_client.transition_debris_ticket(
                tk2["id"],
                {"action": "RECONCILE", "corrected_gross_tons": 10.0,
                 "corrected_diverted_tons": 3.0},
                HAULER,
            )
        )
        assert ok["status"] == "RECONCILED"
        assert ok["gross_tons"] == 10.0
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["landfill_tons"] == 13.0  # 6.0 + (10.0 - 3.0)
        assert project["diverted_tons"] == 7.0

    def test_debris_mass_invariant_holds_across_manifest(self):
        """PRD §3.8: "A mass invariant closes the books: `in_transit_tons` plus
        `landfill_tons` plus `diverted_tons` plus `removed_tons` always equals
        the sum of `gross_tons` over every ticket ever created for the project,
        voided and cancelled tickets included."
        PRD §3.8: "A new ticket is `MANIFESTED`, and the project's
        `in_transit_tons` rises by its `gross_tons`."

        Design: Difficulty/compensating_invariant/debris_mass_invariant_through_receive_and_void
        """
        ctx = setup_demolition_active(name="MassOk", address="83B Elm St")
        pid = ctx["project"]["id"]
        tk = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-M", gross_tons=7.5), HAULER)
        )
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["in_transit_tons"] == 7.5
        assert project["landfill_tons"] == 0
        assert project["diverted_tons"] == 0
        assert project["removed_tons"] == 0
        # M = 7.5 == gross ever created, conserved at the MANIFESTED step.
        accounted = (project["in_transit_tons"] + project["landfill_tons"]
                     + project["diverted_tons"] + project["removed_tons"])
        assert accounted == 7.5

    def test_debris_mass_invariant_through_receive_and_void(self):
        """PRD §3.8: "A mass invariant closes the books: `in_transit_tons` plus
        `landfill_tons` plus `diverted_tons` plus `removed_tons` always equals
        the sum of `gross_tons` over every ticket ever created for the project,
        voided and cancelled tickets included."
        PRD §3.8: "Voiding removes a ticket from accounting: from `MANIFESTED`,
        `in_transit_tons` falls by the `gross_tons` and `removed_tons` rises by
        the same; from `RECEIVED`, `landfill_tons` falls by the `disposed_tons`,
        `diverted_tons` falls by the diverted figure, and `removed_tons` rises
        by the `gross_tons`."

        Design: Difficulty/compensating_invariant/debris_mass_invariant_through_receive_and_void
        """
        ctx = setup_demolition_active(name="Mass Lot", address="83 Elm St",
                                      required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        tk_a = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-A", gross_tons=10.0), HAULER)
        )
        tk_b = get_success_data(
            api_client.create_debris_ticket(
                pid, create_debris_ticket_payload(ticket_number="T-B", facility_type="TRANSFER",
                                                  material_class="METAL", gross_tons=6.0), HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(
                tk_a["id"], {"action": "RECEIVE", "diverted_tons": 4.0}, HAULER)
        )
        mid = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert mid["in_transit_tons"] == 6.0
        assert mid["landfill_tons"] == 6.0
        assert mid["diverted_tons"] == 4.0
        assert mid["removed_tons"] == 0
        # M = 6.0 + 6.0 + 4.0 + 0 == 16.0 == gross ever created.
        get_success_data(
            api_client.transition_debris_ticket(tk_b["id"], {"action": "VOID"}, HAULER)
        )
        get_success_data(
            api_client.transition_debris_ticket(tk_a["id"], {"action": "VOID"}, HAULER)
        )
        end = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert end["in_transit_tons"] == 0
        assert end["landfill_tons"] == 0
        assert end["diverted_tons"] == 0
        assert end["removed_tons"] == 16.0, "mass conserved: 16.0 accounted, zero drift"
        assert end["diversion_rate"] == 0, "denominator zero after both voids"
