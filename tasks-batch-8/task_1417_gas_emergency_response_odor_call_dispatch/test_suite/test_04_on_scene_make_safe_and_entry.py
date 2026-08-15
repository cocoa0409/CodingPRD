"""On-scene operations: make-safe actions, completion gates, entry-status
parallel dimension, and severity threshold constants (PRD §2.6, §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, set_clock, get_incident, record_reading, record_action,
    complete_make_safe, setup_on_scene_incident, setup_closed_incident,
    TEST_USERS, make_technician_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestZeroReadingsBlocksMakeSafeCompletion:
    def test_odor_incident_without_reading_rejected_422(self, api):
        """PRD §3.5: "First, when any linked call reported odor and the
        incident has no atmospheric reading at all, completion is rejected
        with `ERR_ATMOSPHERIC_READING_REQUIRED` (HTTP 422); this reading
        requirement applies even when `no_make_safe_required` is true."

        Design: Difficulty/boundary_precision_check/zero_readings_blocks_make_safe_completion
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="25 Hickory St", caller_name="Pam",
            caller_phone="555-0115")

        resp = api_client.complete_make_safe(
            call["incident_id"],
            {"leak_confirmed": False, "no_make_safe_required": True},
            make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_ATMOSPHERIC_READING_REQUIRED)

        incident = get_incident(call["incident_id"])
        assert incident["make_safe_completed"] is False
        assert incident["lifecycle_status"] == "ON_SCENE"

    def test_single_reading_flips_gate_to_pass(self, api):
        """PRD §3.5: "Either way, completion sets `make_safe_completed` to
        true, stores the submitted `leak_confirmed`, increments the incident
        `version`, and marks covering draft or rejected reports stale." and
        "A completion submitted with `no_make_safe_required` true takes the
        incident directly from `ON_SCENE` to `MONITORING` under the same
        preconditions."

        Design: Difficulty/boundary_precision_check/zero_readings_blocks_make_safe_completion
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="25 Hickory St", caller_name="Pam",
            caller_phone="555-0115")

        resp = api_client.complete_make_safe(
            call["incident_id"],
            {"leak_confirmed": False, "no_make_safe_required": True},
            make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_ATMOSPHERIC_READING_REQUIRED)

        record_reading(call["incident_id"], tech["id"], pct_lel=0.0, co_ppm=0,
                       reading_context="INSIDE")
        completed = complete_make_safe(call["incident_id"], tech["id"],
                                       leak_confirmed=False,
                                       no_make_safe_required=True)
        assert completed["lifecycle_status"] == "MONITORING"
        assert completed["make_safe_completed"] is True


class TestStateBeatsSafetyOnClosedMakeSafeComplete:
    def test_closed_incident_completion_returns_state_error(self, api):
        """PRD §2.6: "The server evaluates every request against a fixed
        validation cascade, and the ordering matters because an earlier
        failure masks all later ones." with state legality (step 6) preceding
        safety gates (step 7); §3.5: "The incident must be in `ON_SCENE` or
        `MAKE_SAFE_IN_PROGRESS` — anything else is `ERR_INCIDENT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_closed_make_safe_complete
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_closed_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="12 Spruce Way", caller_name="Liam",
            caller_phone="555-0111")

        resp = api_client.complete_make_safe(
            call["incident_id"], {"leak_confirmed": True},
            make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)

    def test_failed_completion_leaves_incident_untouched(self, api):
        """PRD §3.5: "The incident must be in `ON_SCENE` or
        `MAKE_SAFE_IN_PROGRESS` — anything else is `ERR_INCIDENT_NOT_ACTIVE`."
        A rejected completion must leave the closed incident's fields
        unchanged (no partial side effects).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_closed_make_safe_complete
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_closed_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="12 Spruce Way", caller_name="Liam",
            caller_phone="555-0111")
        before = get_incident(call["incident_id"])

        resp = api_client.complete_make_safe(
            call["incident_id"], {"leak_confirmed": True},
            make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)

        after = get_incident(call["incident_id"])
        assert after["lifecycle_status"] == "CLOSED"
        assert after["make_safe_completed"] == before["make_safe_completed"]
        assert after["leak_confirmed"] == before["leak_confirmed"]
        assert after["version"] == before["version"]


class TestFirstMakeSafeActionTransition:
    def test_first_action_moves_to_make_safe_in_progress(self, api):
        """PRD §3.5: "The very first make-safe action on an incident
        automatically moves it from `ON_SCENE` to `MAKE_SAFE_IN_PROGRESS`."

        Design: Corner/state_machines/first_make_safe_action_moves_incident_to_make_safe_in_progress
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="17 Safe St", caller_name="R", caller_phone="555-0215")

        record_action(call["incident_id"], tech["id"], "VENTILATE")
        after_first = get_incident(call["incident_id"])
        assert after_first["lifecycle_status"] == "MAKE_SAFE_IN_PROGRESS"

        record_action(call["incident_id"], tech["id"], "SECURE_AREA")
        after_second = get_incident(call["incident_id"])
        assert after_second["lifecycle_status"] == "MAKE_SAFE_IN_PROGRESS"

        data, meta = validate_paginated(api_client.list_make_safe_actions(
            call["incident_id"], SUPERVISOR))
        assert meta["total_count"] == 2
        assert [a["action_type"] for a in data] == ["VENTILATE", "SECURE_AREA"]


class TestEntryStatusParallelDimension:
    def test_entry_status_moves_do_not_disturb_lifecycle(self, api):
        """PRD §3.5: "Premise entry runs on a second, parallel state dimension
        that never disturbs the lifecycle dimension except where explicitly
        stated." and "`EMERGENCY_FORCED` and `WARRANT` methods are restricted
        to a `Supervisor` and move it `AWAITING_AUTHORIZATION → FORCED`."

        Design: Corner/state_machines/entry_status_dimension_independent_of_lifecycle
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="19 Entry St", caller_name="S", caller_phone="555-0216",
            location_context="METER_AREA", hissing_reported=True)

        resp = api_client.set_entry_status(
            call["incident_id"], {"to_status": "AWAITING_AUTHORIZATION"},
            make_technician_headers(tech["id"]))
        updated = validate_success(resp)
        assert updated["entry_status"] == "AWAITING_AUTHORIZATION"
        assert updated["lifecycle_status"] == "ON_SCENE"

        resp = api_client.create_entry_authorization(
            call["incident_id"],
            {"method": "EMERGENCY_FORCED", "authorized_by_name": "Fire Chief"},
            SUPERVISOR)
        auth = validate_success(resp, expected_status=201)
        assert auth["method"] == "EMERGENCY_FORCED"

        incident = get_incident(call["incident_id"])
        assert incident["entry_status"] == "FORCED"
        assert incident["lifecycle_status"] == "ON_SCENE"

        data, meta = validate_paginated(api_client.list_entry_authorizations(
            call["incident_id"], SUPERVISOR))
        assert meta["total_count"] == 1
        assert data[0]["method"] == "EMERGENCY_FORCED"


class TestPctLelEvacuationThreshold:
    def test_pct_lel_below_threshold_leaves_evacuation_false(self, api):
        """PRD §3.5: "Separately, the `evacuation_required` flag is true
        exactly when any reading on the incident has `pct_lel` of at least
        10.0 — the same ten-percent threshold that drives the top LEL factor."
        and the LEL factor is "0.5 when it is at least 5.0 but below 10.0" so
        9.9 yields 40*0.5 + 20*0.3 = 26.

        Design: Corner/calculations/pct_lel_exactly_at_evacuation_threshold
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="21 Lel St", caller_name="T1c", caller_phone="555-0217")

        record_reading(call["incident_id"], tech["id"], pct_lel=9.9, co_ppm=0,
                       reading_context="INSIDE")
        incident = get_incident(call["incident_id"])
        assert incident["evacuation_required"] is False
        assert incident["severity_score"] == 26  # 40*0.5 + 25*0 + 20*0.3 + 15*0

    def test_pct_lel_exactly_at_threshold_sets_evacuation_true(self, api):
        """PRD §3.5: "Let the incident's maximum `pct_lel` over all of its
        readings — zero when no readings exist — determine the LEL factor: 1.0
        when that maximum is at least 10.0" and "the `evacuation_required`
        flag is true exactly when any reading on the incident has `pct_lel` of
        at least 10.0".

        Design: Corner/calculations/pct_lel_exactly_at_evacuation_threshold
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="22 Lel St", caller_name="T2c", caller_phone="555-0218")

        record_reading(call["incident_id"], tech["id"], pct_lel=10.0, co_ppm=0,
                       reading_context="INSIDE")
        incident = get_incident(call["incident_id"])
        assert incident["evacuation_required"] is True
        assert incident["severity_score"] == 46  # 40*1.0 + 25*0 + 20*0.3 + 15*0
