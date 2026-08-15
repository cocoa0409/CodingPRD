"""Odor events, the plant odor score, and the posture gate (PRD §2.7, §3.2, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    close_settlement,
    confirm_odor_event,
    confirm_severities,
    create_odor_event,
    create_plant,
    create_route,
    create_supplier,
    create_active_agreement,
    create_vehicle,
    get_settlement,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
CO3 = TEST_USERS["compliance_officer_3_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
FA = TEST_USERS["finance_analyst_headers"]
ANY = TEST_USERS["any_headers"]


class TestOdorEventResolution:
    def test_odor_event_double_confirm_rejected(self, api):
        """PRD §3.2: "Confirmation requires the event still `REPORTED` — an already-resolved
        event, whether `CONFIRMED` or `DISMISSED`, rejects with
        `ERR_ODOR_EVENT_ALREADY_RESOLVED` — and the confirmer must differ from `reported_by`
        (`ERR_SOD_VIOLATION`)."
        PRD §3.2: "applies the severity penalty to the plant's `odor_score`: 50 points for
        `LOW`, 100 for `MEDIUM`, 150 for `HIGH`, never driving the score below 0."

        Design: Corner/state_machines/odor_event_double_confirm_rejected
        """
        plant = create_plant()
        event = create_odor_event(plant["id"], severity="LOW")
        confirmed = validate_success(api.confirm_odor_event(event["id"], CO2), 200)
        assert confirmed["status"] == "CONFIRMED"

        # Both re-confirmation and dismissal of a resolved event are rejected.
        res1 = api.confirm_odor_event(event["id"], CO3)
        validate_error(res1, ApiErrorId.ERR_ODOR_EVENT_ALREADY_RESOLVED, expected_status=409)
        res2 = api.dismiss_odor_event(event["id"], CO3)
        validate_error(res2, ApiErrorId.ERR_ODOR_EVENT_ALREADY_RESOLVED, expected_status=409)

        # Exactly one 50-point LOW penalty was applied.
        fetched = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert fetched["odor_score"] == 950


class TestOdorScoreBoundary:
    def test_odor_score_exactly_600_stays_operating(self, api):
        """PRD §3.2: "If the penalized score falls below 600 while the plant is `OPERATING`,
        posture drops to `RESTRICTED`."
        PRD §3.2: "A confirm-time penalty only pushes posture to `RESTRICTED` when it crosses
        below 600; recovery only restores `OPERATING` when the score reaches at least 700
        (§3.9). Scores from 600 up to 699 cause no posture transition in either direction."

        Design: Difficulty/boundary_precision_check/odor_score_600_boundary
        """
        plant = create_plant()
        # HIGH (150) + HIGH (150) + MEDIUM (100) = 400 penalty: 1000 - 400 = 600.
        events = confirm_severities(plant["id"], ["HIGH", "HIGH", "MEDIUM"])
        for event in events:
            assert event["status"] == "CONFIRMED"
            assert event["confirmed_by"] == "co-2"
            # No ACTIVE permit exists, so the event links no permit.
            assert event["permit_id"] is None

        fetched = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert fetched["odor_score"] == 600
        # 600 is not below 600: the posture gate does not fire.
        assert fetched["posture"] == "OPERATING"

    def test_odor_score_below_600_flips_restricted(self, api):
        """PRD §3.2: "If the penalized score falls below 600 while the plant is `OPERATING`,
        posture drops to `RESTRICTED`."
        PRD §3.2: "applies the severity penalty to the plant's `odor_score`: 50 points for
        `LOW`, 100 for `MEDIUM`, 150 for `HIGH`, never driving the score below 0."

        Design: Difficulty/boundary_precision_check/odor_score_600_boundary
        """
        plant = create_plant()
        # HIGH + HIGH + MEDIUM lands exactly on 600 (still OPERATING)...
        confirm_severities(plant["id"], ["HIGH", "HIGH", "MEDIUM"])
        mid = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert mid["odor_score"] == 600
        assert mid["posture"] == "OPERATING"

        # ...then LOW (50) takes the score to 550, crossing below 600.
        confirm_severities(plant["id"], ["LOW"])
        after = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert after["odor_score"] == 550
        assert after["posture"] == "RESTRICTED"


class TestOdorRecovery:
    def test_odor_recovery_on_quiet_period_only(self, api):
        """PRD §3.9: "if the just-closed settlement recorded zero `confirmed_odor_events`,
        the plant's `odor_score` increases by 50, never exceeding the 1000 cap; after
        recovery, a `RESTRICTED` plant whose score has reached at least 700 returns to
        `OPERATING`, provided its `ACTIVE` permit, if any, is not `SUSPENDED`, `REVOKED`, or
        `EXPIRED`."

        Design: Corner/calculations/odor_recovery_on_quiet_period_only
        """
        plant = create_plant()
        # One confirmed LOW event in period 1: score 950.
        confirm_severities(plant["id"], ["LOW"])
        close_settlement(plant["id"], period_index=1)

        # Advance with a confirmed event in the closing period: no recovery.
        advanced = validate_success(api.advance_period(plant["id"], FA), 200)
        assert advanced["current_period_index"] == 2
        assert advanced["odor_score"] == 950
        assert advanced["posture"] == "OPERATING"

        settlement2 = get_settlement(plant["id"], period_index=2)
        assert settlement2["status"] == "OPEN"
        assert settlement2["confirmed_odor_events"] == 0

        # Quiet period 2: recovery of +50 applies, capped at 1000.
        close_settlement(plant["id"], period_index=2)
        advanced2 = validate_success(api.advance_period(plant["id"], FA), 200)
        assert advanced2["current_period_index"] == 3
        assert advanced2["odor_score"] == 1000
        assert advanced2["posture"] == "OPERATING"


class TestPostureGate:
    def test_posture_restricted_blocks_dispatch(self, api):
        """PRD §2.7: "While a plant is `RESTRICTED`, operations otherwise remain open, but
        two specific actions are forbidden: dispatching a collection route and starting a
        cook run. Attempting either returns `ERR_PLANT_RESTRICTED` (HTTP 409)."

        Design: Corner/validations/posture_restricted_blocks_dispatch
        """
        plant = create_plant()
        # Three confirmed HIGH events: 1000 - 450 = 550 < 600 -> RESTRICTED.
        confirm_severities(plant["id"], ["HIGH", "HIGH", "HIGH"])
        restricted = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert restricted["odor_score"] == 550
        assert restricted["posture"] == "RESTRICTED"

        # Routes and stops remain writable while RESTRICTED; only dispatch is gated.
        supplier = create_supplier(plant["id"])
        agreement = create_active_agreement(plant["id"], supplier["id"])
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        add_stop(route["id"], supplier["id"], agreement["id"], plant["id"])

        res = api.dispatch_route(route["id"], RD)
        validate_error(res, ApiErrorId.ERR_PLANT_RESTRICTED, expected_status=409)

        fetched = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert fetched["status"] == "PLANNED"
