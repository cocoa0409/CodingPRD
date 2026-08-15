"""Entity-surface claims: defaults, required fields, computed fields, 404s,
immutability, enum constraints, pagination envelope, FK integrity, and
server-minted system fields."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_weather_assessment,
    create_aircraft,
    create_base,
    create_mission_request,
    create_patient,
    get_success_data,
    is_valid_uuid,
    post_go_weather,
    set_clock,
    setup_planning_mission,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestAircraftCreationAppliesDefaultStatus:
    def test_new_aircraft_enters_service_available_at_version_1(self):
        """PRD §3.1: "A newly registered aircraft enters service as
        `AVAILABLE`."
        PRD §2.4: "`version`, an integer that increments by exactly one on every
        mutation of the resource."

        Design: Corner/entities/aircraft_creation_applies_default_status
        """
        base = create_base(name="Base A")
        aircraft = create_aircraft(
            base["id"], tail_number="N100DF", medical_config="ALS_CAPABLE"
        )
        assert aircraft["status"] == "AVAILABLE", (
            f"Default status must be AVAILABLE, got {aircraft['status']}"
        )
        assert aircraft["version"] == 1


class TestCrewMemberMissingRequiredCrewRole:
    def test_omitting_crew_role_is_a_shape_failure(self):
        """PRD §2.8: "then request shape — required fields present, types
        correct, enum members valid, ranges respected, which covers the clinical
        subscales within 0 to 10, mile figures greater than zero, cent amounts
        positive, and a shift's planned end strictly after its planned start —
        reported as `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "An `OpsAdmin` enrolls a crew member with their home
        `base_id`, `full_name`, and `crew_role` — one of `PILOT`, `NURSE`, or
        `PARAMEDIC`."

        Design: Corner/entities/crew_member_missing_required_crew_role_returns_invalid_request
        """
        base = create_base(name="Base A")
        resp = api_client.create_crew_member(
            {"base_id": base["id"], "full_name": "No Role"}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestMissionRequestComputedTriageScore:
    def test_intake_computes_triage_score_and_lands_received(self):
        """PRD §3.2: "Intake computes the request's `triage_acuity_score`: a
        weighted sum that weights the cardio subscale at 0.30, respiratory at
        0.30, neuro at 0.20, and interventions at 0.20, rounded half-up to two
        decimal places. The request lands in `RECEIVED`."

        Design: Corner/entities/mission_request_computed_triage_score_present
        """
        set_clock()
        patient = create_patient(full_name="Comp Uted", date_of_birth="1992-02-02", weight_kg=75)
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 1, "resp": 2, "neuro": 3, "interv": 4},
            transport_class="EMERGENCY_SCENE",
            origin_facility="Scene",
            onset_iso="2026-07-31T20:00:00Z",
        )
        # 1*.30 + 2*.30 + 3*.20 + 4*.20 = 0.3+0.6+0.6+0.8 = 2.30.
        assert request["triage_acuity_score"] == 2.3, (
            f"Expected server-computed triage score 2.3, got {request['triage_acuity_score']}"
        )
        assert request["status"] == "RECEIVED"


class TestGetMissionRequestNotFound:
    def test_reading_nonexistent_request_returns_not_found(self):
        """PRD §2.8: "Every referenced identifier must exist: the system
        validates existence of path and body identifiers in a logical
        left-to-right order, and the first missing reference rejects the request
        with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs."

        Design: Corner/entities/get_mission_request_not_found_returns_404
        """
        resp = api_client.get_mission_request(NON_EXISTENT_UUID, DISP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestWeatherAssessmentImmutableRecord:
    def test_creation_response_carries_no_version_or_updated_at(self):
        """PRD §2.4: "A `WeatherAssessment` is an immutable observation: it
        carries `id` and `created_at` only, and both `updated_at` and `version`
        are absent."

        Design: Corner/entities/weather_assessment_immutable_record
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        wa = post_go_weather(ctx["mission"]["id"], pilot)
        assert_weather_assessment(wa)
        assert wa["decision"] == "GO"


class TestAircraftInvalidEnumMedicalConfig:
    def test_unknown_medical_config_member_rejected(self):
        """PRD §3.1: "the `medical_config`, which declares the highest clinical
        capability the tail is outfitted for: `BLS_CAPABLE`, `ALS_CAPABLE`, or
        `CCT_CAPABLE`"
        PRD §2.8: "then request shape — required fields present, types correct,
        enum members valid, ranges respected ... reported as `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/entities/aircraft_invalid_enum_medical_config_returns_invalid_request
        """
        base = create_base(name="Base A")
        resp = api_client.create_aircraft(
            {
                "base_id": base["id"],
                "tail_number": "N100XX",
                "aircraft_class": "ROTOR_WING",
                "medical_config": "JET",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestListMissionRequestsPaginationEnvelope:
    def test_limit_offset_window_reports_total_count_and_has_more(self):
        """PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, and any supplied value must be at least 1
        and at most 100. The `offset` parameter controls how many items are
        skipped and defaults to 0."

        Design: Corner/entities/list_mission_requests_pagination_envelope
        """
        set_clock()
        patient = create_patient(full_name="Page Nate", date_of_birth="1991-01-01", weight_kg=70)
        for scene in ("Scene A", "Scene B"):
            create_mission_request(
                patient["id"],
                subscales={"cardio": 1, "resp": 1, "neuro": 1, "interv": 1},
                transport_class="EMERGENCY_SCENE",
                origin_facility=scene,
                onset_iso="2026-07-31T20:00:00Z",
            )
        resp = api_client.list_mission_requests(DISP, params={"limit": 1, "offset": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1&offset=1 must return exactly 1 row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False


class TestGroundLegRequiresExistingMissionFk:
    def test_ground_leg_with_nonexistent_mission_rejected(self):
        """PRD §2.8: "Every referenced identifier must exist: the system
        validates existence of path and body identifiers in a logical
        left-to-right order, and the first missing reference rejects the request
        with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs."

        Design: Corner/entities/ground_leg_requires_existing_mission_fk
        """
        resp = api_client.create_ground_leg(
            {
                "mission_id": NON_EXISTENT_UUID,
                "leg_type": "ORIGIN",
                "provider_name": "City EMS",
                "scheduled_pickup_iso": "2026-08-01T09:00:00Z",
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestPatientSystemFieldsServerMinted:
    def test_patient_id_is_uuid_and_created_at_follows_logical_clock(self):
        """PRD §2.4: "Every primary resource carries a standard set of
        system-managed fields: `id`, a server-minted UUID with no type prefix;
        `created_at`, an ISO 8601 UTC timestamp with three fractional digits
        recorded at creation"
        PRD §2.4: "At startup, before any clock-setting call has been made, the
        logical clock reads 2026-08-01T00:00:00Z; it never silently falls back
        to wall-clock time thereafter."
        PRD §3.2: "a `Dispatcher` registers them with a `full_name`, a
        `date_of_birth` in ISO `YYYY-MM-DD` form, and a `weight_kg` that must be
        greater than zero."

        Design: Corner/entities/patient_system_fields_server_minted
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_patient(
            {"full_name": "Sys Fields", "date_of_birth": "2000-01-01", "weight_kg": 60},
            DISP,
        )
        patient = get_success_data(resp, 201)
        assert is_valid_uuid(patient["id"]), "id must be a server-minted UUID"
        # created_at is stamped from the logical clock, not wall-clock.
        assert patient["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must follow the logical clock, got {patient['created_at']}"
        )
