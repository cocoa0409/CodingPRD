"""Shutdown cascades (species sighting, equipment outage), shutdown-hours
accrual, explicit resumption, and terminal-state lockdowns
(PRD §2.4, §3.3, §3.5, §3.6, §3.8).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_plant_payload,
    set_clock, get_project, get_event, report_sighting, clear_sighting,
    resume_event, file_claim, create_project, add_permit,
    setup_dredging_reach, setup_completed_event, setup_species_shutdown,
    open_event,
)


class TestSpeciesSightingCascade:
    def _two_active_events(self):
        """Reach DREDGING with two ACTIVE events on one plant."""
        ctx = setup_dredging_reach()
        ev1 = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                         "2026-05-10T00:00:00Z")
        ev2 = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                         "2026-05-10T01:00:00Z")
        ctx["event"] = ev1
        ctx["event2"] = ev2
        return ctx

    def test_species_sighting_suspends_project_and_shuts_events(
        self, api, monitor_headers
    ):
        """PRD §3.6: "Creation is the cascade origin: the posture recompute
        lands on `SUSPENDED`, and every `ACTIVE` event of the project shuts down
        with reason `SPECIES`, `last_shutdown_at` stamped, standby hours
        accruing from that instant."

        Design: Difficulty/transitive_cascade/species_sighting_cascade_depth4
        """
        ctx = self._two_active_events()
        set_clock("2026-05-10T06:00:00Z")
        report_sighting(ctx["project"]["id"], "FISH", "2026-05-10T06:00:00Z")
        project = get_project(ctx["project"]["id"])
        assert project["compliance_posture"] == "SUSPENDED"
        for key in ("event", "event2"):
            event_after = get_event(ctx[key]["id"])
            assert event_after["status"] == "SHUTDOWN"
            assert event_after["shutdown_reason"] == "SPECIES"
            assert event_after["last_shutdown_at"] is not None

    def test_species_cascade_accrues_hours_and_no_auto_resume(
        self, api, contractor_headers, monitor_headers
    ):
        """PRD §3.5: "Resuming settles the open shutdown interval: the hours
        between `last_shutdown_at` and the current logical time, rounded half up
        to 2 decimal places, are added into `shutdown_accumulated_hours`".
        PRD §3.6: "The asymmetry bears repeating: clearing never resumes
        anything. Each shutdown event requires its own explicit resume under
        §3.5."
        PRD §3.8: "`payable_hours` is `claimed_hours` minus the standing
        deductible of 4 hours, floored at zero".

        Design: Difficulty/transitive_cascade/species_sighting_cascade_depth4
        """
        ctx = self._two_active_events()
        set_clock("2026-05-10T06:00:00Z")
        sighting = report_sighting(ctx["project"]["id"], "FISH",
                                   "2026-05-10T06:00:00Z")
        set_clock("2026-05-10T16:00:00Z")
        clear_sighting(sighting["id"])
        resumed = resume_event(ctx["event"]["id"])
        # 06:00 -> 16:00 settles exactly 10.0 hours.
        assert resumed["shutdown_accumulated_hours"] == pytest.approx(10.0,
                                                                      abs=1e-4)
        assert resumed["status"] == "ACTIVE"
        # The sibling event is NOT auto-resumed by the clear or by the resume.
        event2_after = get_event(ctx["event2"]["id"])
        assert event2_after["status"] == "SHUTDOWN"
        # Link 4: the accrued hours back a SPECIES_SHUTDOWN claim; 10.0 - 4.0.
        claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                           "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                           10.0, "SPECIES_SHUTDOWN")
        assert claim["payable_hours"] == pytest.approx(6.0, abs=1e-4)


class TestSightingClearCooldown:
    def test_sighting_clear_cooldown_boundary(self, api, monitor_headers):
        """PRD §3.6: "Clearing a sighting is allowed only once the stand-down
        has elapsed: the current logical time must be at or after `observed_utc`
        plus the governing issued permit's `species_standdown_hours` — equality
        is allowed — otherwise the clear is rejected with
        `ERR_SPECIES_COOLDOWN_ACTIVE` (HTTP 409)."

        Design: Corner/state_machines/sighting_clear_cooldown_boundary
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-CD")
        add_permit(project["id"])  # species_standdown_hours = 6
        set_clock("2026-05-10T06:00:00Z")
        sighting = report_sighting(project["id"], "MAMMAL",
                                   "2026-05-10T06:00:00Z")
        # +5h: inside the cooldown — rejected.
        set_clock("2026-05-10T11:00:00Z")
        res = api.clear_species_sighting(sighting["id"], monitor_headers)
        validate_error(res, ApiErrorId.ERR_SPECIES_COOLDOWN_ACTIVE,
                       expected_status=409)
        # +6h exactly: equality is allowed — cleared.
        set_clock("2026-05-10T12:00:00Z")
        cleared = validate_success(
            api.clear_species_sighting(sighting["id"], monitor_headers), 200
        )
        assert cleared["status"] == "CLEARED"


class TestResumeGates:
    def test_resume_rejected_while_sighting_active(self, api, contractor_headers,
                                                   monitor_headers):
        """PRD §3.5: "A `ContractorOps` resume moves a `SHUTDOWN` event back to
        `ACTIVE` only when the project's posture is no longer `SUSPENDED` — else
        `ERR_EVENT_NOT_RESUMABLE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/resume_gated_on_species_sighting_state
        """
        ctx = setup_dredging_reach()
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        set_clock("2026-05-10T06:00:00Z")
        report_sighting(ctx["project"]["id"], "BIRD", "2026-05-10T06:00:00Z")
        # Posture SUSPENDED while the sighting is ACTIVE.
        res = api.resume_dredge_event(event["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_EVENT_NOT_RESUMABLE,
                       expected_status=409)

    def test_resume_after_clear_settles_shutdown_hours(self, api,
                                                       contractor_headers,
                                                       monitor_headers):
        """PRD §3.6: "Clearing a sighting is allowed only once the stand-down
        has elapsed"; PRD §3.5: "Resuming settles the open shutdown interval:
        the hours between `last_shutdown_at` and the current logical time,
        rounded half up to 2 decimal places, are added into
        `shutdown_accumulated_hours`, and `shutdown_reason` and
        `last_shutdown_at` are cleared to null."

        Design: Difficulty/cross_entity_state_dependency/resume_gated_on_species_sighting_state
        """
        ctx = setup_dredging_reach()
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        set_clock("2026-05-10T06:00:00Z")
        sighting = report_sighting(ctx["project"]["id"], "BIRD",
                                   "2026-05-10T06:00:00Z")
        set_clock("2026-05-10T16:00:00Z")
        clear_sighting(sighting["id"])
        resumed = resume_event(event["id"])
        assert resumed["status"] == "ACTIVE"
        assert resumed["shutdown_accumulated_hours"] == pytest.approx(10.0,
                                                                      abs=1e-4)


class TestEquipmentCascade:
    def test_plant_out_of_service_cascade(self, api, contractor_headers):
        """PRD §3.3: "While registered it may be set `OUT_OF_SERVICE` — which
        forces every `ACTIVE` dredge event of that plant into `SHUTDOWN` with
        `shutdown_reason` `EQUIPMENT`, stamps each event's `last_shutdown_at`
        with the current logical time, and starts their shutdown-hours accrual —
        and later returned to `REGISTERED`, a transition that pointedly does not
        resume anything: each equipment-shutdown event needs its own explicit
        resume (§3.5)."
        PRD §3.5: "for events shut down with reason `EQUIPMENT`, only when the
        plant is again `REGISTERED`, else the same `ERR_EVENT_NOT_RESUMABLE`."

        Design: Corner/complexity_layers/plant_out_of_service_cascade
        """
        ctx = setup_dredging_reach(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        set_clock("2026-05-10T06:00:00Z")
        validate_success(
            api.patch_plant(ctx["plant"]["id"], {"status": "OUT_OF_SERVICE"},
                            contractor_headers),
            200,
        )
        event_after = get_event(event["id"])
        assert event_after["status"] == "SHUTDOWN"
        assert event_after["shutdown_reason"] == "EQUIPMENT"
        # Resume refused while the plant is down.
        res = api.resume_dredge_event(event["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_EVENT_NOT_RESUMABLE,
                       expected_status=409)
        # Plant back: explicit resume succeeds, settling 06:00 -> 10:00 = 4.0h.
        validate_success(
            api.patch_plant(ctx["plant"]["id"], {"status": "REGISTERED"},
                            contractor_headers),
            200,
        )
        set_clock("2026-05-10T10:00:00Z")
        resumed = validate_success(
            api.resume_dredge_event(event["id"], contractor_headers), 200
        )
        assert resumed["status"] == "ACTIVE"
        assert resumed["shutdown_accumulated_hours"] == pytest.approx(4.0,
                                                                      abs=1e-4)


class TestTerminalLockdowns:
    def test_retired_plant_cannot_be_modified(self, api, contractor_headers):
        """PRD §3.3: "`RETIRED` is terminal, and any attempt to move a retired
        plant elsewhere is a wrong-from-state rejection."; PRD §2.9: "the target
        must be in a valid from-state for the requested transition, with
        terminal states locked down: `ERR_INVALID_STATE`".

        Design: Corner/state_machines/retired_plant_cannot_be_modified
        """
        res = api.create_plant(
            create_plant_payload(contractor_ref="DGE-R", plant_type="BACKHOE",
                                 rated_daily_production_cy=1200),
            contractor_headers,
        )
        plant = validate_success(res, 201)
        validate_success(
            api.patch_plant(plant["id"], {"status": "RETIRED"},
                            contractor_headers),
            200,
        )
        res2 = api.patch_plant(plant["id"], {"status": "REGISTERED"},
                               contractor_headers)
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        plant_after = validate_success(api.get_plant(plant["id"],
                                                     contractor_headers))
        assert plant_after["status"] == "RETIRED"

    def test_completed_event_cannot_resume(self, api, contractor_headers):
        """PRD §3.5: "`COMPLETED` is terminal; only completed events can have
        their placed material reported (§3.7)."
        PRD §3.5: "A `ContractorOps` resume moves a `SHUTDOWN` event back to
        `ACTIVE`"; PRD §2.9: "the target must be in a valid from-state for the
        requested transition, with terminal states locked down:
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/completed_event_cannot_resume
        """
        ctx = setup_completed_event()
        res = api.resume_dredge_event(ctx["event"]["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
