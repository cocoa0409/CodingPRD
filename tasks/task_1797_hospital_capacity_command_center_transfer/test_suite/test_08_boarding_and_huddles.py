"""ED boarding records, heartbeats, escalation huddles, and placement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bed,
    create_admission,
    create_boarding_record_payload,
    create_facility,
    get_success_data,
    make_coordinator_headers,
    make_house_supervisor_headers,
    set_clock,
    setup_ed_boarding_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["house_supervisor_headers"]


class TestBoardingCreation:
    def test_boarding_record_requires_ed_admission(self, api):
        """PRD §3.8: "The admission's bed must be in an ED unit — its bed's
        `unit` label beginning with ED — or creation is rejected with
        `ERR_ADMISSION_NOT_ED_BOARDER`".

        Design: Corner/validations/boarding_record_requires_ed_admission
        """
        set_clock()
        facility = create_facility(name="ED Fac")
        bed = add_bed(facility["id"], unit="M-1", label="M1", service="MEDICAL")
        admission = create_admission(facility["id"], bed["id"],
                                     patient_ref="PNED")
        resp = api.create_boarding_record(
            facility["id"], {"admission_id": admission["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_NOT_ED_BOARDER)

    def test_boarding_record_duplicate_open_rejected(self, api):
        """PRD §3.8: "an admission may have at most one open boarding record,
        where open means `placement_status` of `WAITING` or `OFFERED`, with a
        second attempt rejected as `ERR_BOARDING_RECORD_ALREADY_OPEN`."

        Design: Corner/validations/boarding_record_duplicate_open_rejected
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Dup Fac")
        resp = api.create_boarding_record(
            scenario["facility"]["id"],
            {"admission_id": scenario["admission"]["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_BOARDING_RECORD_ALREADY_OPEN)


class TestHeartbeatBoundary:
    def test_boarding_huddle_at_exactly_120_minutes(self, api):
        """PRD §3.8: "Whenever a heartbeat or a sweep evaluates the check, if
        the record's placement is `WAITING` or `OFFERED`, its escalation status
        is `NONE` or `HUDDLE_RESOLVED`, and `boarding_minutes` has reached at
        least 120 minutes — two hours — the system calls an escalation huddle
        automatically: an `EscalationHuddle` is created in `CALLED` status with
        `trigger_reason` of `AUTO_THRESHOLD`, and the record's
        `escalation_status` becomes `HUDDLE_CALLED`. A boarding time of 119
        minutes does not trigger; 120 does."

        Design: Difficulty/boundary_precision_check/boarding_huddle_at_exactly_120_minutes
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Boundary Facility")
        record = scenario["boarding_record"]
        below = validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 119},
            make_coordinator_headers("coord_1")), 200)
        assert below["boarding_minutes"] == 119
        assert below["escalation_status"] == "NONE"
        assert below["huddle_count_24h"] == 0
        at_threshold = validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 120},
            make_coordinator_headers("coord_1")), 200)
        assert at_threshold["escalation_status"] == "HUDDLE_CALLED"
        assert at_threshold["huddle_count_24h"] == 1
        huddles, meta = validate_paginated(
            api.list_huddles(record["id"], COORD))
        assert len(huddles) == 1
        assert huddles[0]["trigger_reason"] == "AUTO_THRESHOLD"
        assert huddles[0]["status"] == "CALLED"

    def test_boarding_minutes_below_threshold_only(self, api):
        """PRD §3.8: "A boarding time of 119 minutes does not trigger; 120
        does."
        PRD §3.8: "Each accepted heartbeat stores `observed_minutes` as
        `last_heartbeat_minutes` and recomputes `boarding_minutes`."

        Design: Difficulty/boundary_precision_check/boarding_huddle_at_exactly_120_minutes
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Boundary Facility 2")
        record = scenario["boarding_record"]
        result = validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 119},
            make_coordinator_headers("coord_1")), 200)
        assert result["boarding_minutes"] == 119
        assert result["last_heartbeat_minutes"] == 119
        assert result["escalation_status"] == "NONE"
        huddles, _meta = validate_paginated(
            api.list_huddles(record["id"], COORD))
        assert huddles == []


class TestParallelDimensions:
    def test_boarding_record_parallel_dimensions(self, api):
        """PRD §3.8: "Escalation runs as a dimension parallel to placement."
        PRD §3.8: "A coordinator offers an inpatient bed to a waiting boarder,
        moving `placement_status` from `WAITING` to `OFFERED`".

        Design: Difficulty/non_linear_state_machine/boarding_record_parallel_dimensions
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Boarding Facility")
        record = scenario["boarding_record"]
        # Heartbeat past the threshold: only the escalation dimension moves.
        escalated = validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 130},
            make_coordinator_headers("coord_1")), 200)
        assert escalated["placement_status"] == "WAITING"
        assert escalated["escalation_status"] == "HUDDLE_CALLED"
        huddles, _m = validate_paginated(api.list_huddles(record["id"], COORD))
        huddle = huddles[0]
        # Placement moves while escalation is mid-cycle.
        offered = validate_success(api.offer_boarding_record(
            record["id"], make_coordinator_headers("coord_1")), 200)
        assert offered["placement_status"] == "OFFERED"
        assert offered["escalation_status"] == "HUDDLE_CALLED"
        # Resolution touches only escalation.
        resolved = validate_success(api.resolve_huddle(
            huddle["id"], {"resolution": "Bed cleaning expedited"},
            make_house_supervisor_headers("hs_1")), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["trigger_reason"] == "AUTO_THRESHOLD"
        mid = validate_success(api.get_boarding_record(record["id"], COORD))
        assert mid["placement_status"] == "OFFERED"
        assert mid["escalation_status"] == "HUDDLE_RESOLVED"
        # Placement advances to its terminal state independently.
        placed = validate_success(api.place_boarding_record(
            record["id"], make_coordinator_headers("coord_1")), 200)
        assert placed["placement_status"] == "PLACED"
        assert placed["escalation_status"] == "HUDDLE_RESOLVED"

    def test_reescalation_after_resolution_is_cyclic(self, api):
        """PRD §3.8: "Because resolution returns escalation to
        `HUDDLE_RESOLVED`, a record whose boarding continues can escalate
        again: the 120-minute check fires anew on a later heartbeat or sweep,
        producing another huddle in a cyclic loop."

        Design: Difficulty/non_linear_state_machine/boarding_record_parallel_dimensions
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Boarding Facility 2")
        record = scenario["boarding_record"]
        validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 130},
            make_coordinator_headers("coord_1")), 200)
        huddles, _m = validate_paginated(api.list_huddles(record["id"], COORD))
        validate_success(api.resolve_huddle(
            huddles[0]["id"], {"resolution": "r1"},
            make_house_supervisor_headers("hs_1")), 200)
        # Second threshold crossing after resolution re-escalates.
        again = validate_success(api.heartbeat_boarding_record(
            record["id"], {"observed_minutes": 140},
            make_coordinator_headers("coord_1")), 200)
        assert again["escalation_status"] == "HUDDLE_CALLED"
        huddles_after, meta = validate_paginated(
            api.list_huddles(record["id"], COORD))
        assert meta["total_count"] == 2
        called = [h for h in huddles_after if h["status"] == "CALLED"]
        assert len(called) == 1
        assert called[0]["trigger_reason"] == "AUTO_THRESHOLD"


class TestPlacementTrack:
    def test_leave_ama_then_place_rejected(self, api):
        """PRD §3.8: "a patient who leaves against medical advice moves from
        `WAITING` or `OFFERED` to `LEFT_AMA`. `PLACED` and `LEFT_AMA` are
        terminal."
        PRD §3.8: "placement into the bed moves it from `OFFERED` to `PLACED`
        (likewise guarded by `ERR_BOARDING_INVALID_STATE`)".

        Design: Corner/state_machines/leave_ama_then_place_rejected
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="AMA Fac")
        record = scenario["boarding_record"]
        validate_success(api.offer_boarding_record(
            record["id"], make_coordinator_headers("coord_1")), 200)
        left = validate_success(api.leave_ama_boarding_record(
            record["id"], make_coordinator_headers("coord_1")), 200)
        assert left["placement_status"] == "LEFT_AMA"
        resp = api.place_boarding_record(
            record["id"], make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_BOARDING_INVALID_STATE)


class TestHuddleLifecycle:
    def test_huddle_resolve_twice_rejected(self, api):
        """PRD §3.8: "Resolving a huddle is also a `HouseSupervisor` action,
        requires the huddle to be `CALLED` (`ERR_HUDDLE_INVALID_STATE`)".

        Design: Corner/state_machines/huddle_resolve_twice_rejected
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Hud Fac")
        record = scenario["boarding_record"]
        huddle = get_success_data(api.create_huddle(
            record["id"], make_house_supervisor_headers("hs_1")))
        validate_success(api.resolve_huddle(
            huddle["id"], {"resolution": "first"},
            make_house_supervisor_headers("hs_1")), 200)
        resp = api.resolve_huddle(
            huddle["id"], {"resolution": "second"},
            make_house_supervisor_headers("hs_1"))
        validate_error(resp, ApiErrorId.ERR_HUDDLE_INVALID_STATE)

    def test_huddle_rolling_window_executive_escalation(self, api):
        """PRD §3.8: "Resolution stamps `resolved_at`, moves the huddle to
        `RESOLVED`, returns the boarding record's `escalation_status` from
        `HUDDLE_CALLED` to `HUDDLE_RESOLVED`, and recomputes
        `huddle_count_24h` — the count of this record's huddles whose
        `called_at` falls at or after the time exactly 24 hours before now, the
        boundary included. When that count reaches three,
        `executive_escalation` is set true."

        Design: Corner/calculations/huddle_rolling_window_executive_escalation
        """
        set_clock()
        scenario = setup_ed_boarding_scenario(name="Roll Fac")
        record = scenario["boarding_record"]

        def escalate_and_resolve(minutes):
            validate_success(api.heartbeat_boarding_record(
                record["id"], {"observed_minutes": minutes},
                make_coordinator_headers("coord_1")), 200)
            huddles, _m = validate_paginated(api.list_huddles(
                record["id"], COORD, params={"status": "CALLED"}))
            assert len(huddles) == 1
            validate_success(api.resolve_huddle(
                huddles[0]["id"], {"resolution": f"r{minutes}"},
                make_house_supervisor_headers("hs_1")), 200)

        escalate_and_resolve(130)
        escalate_and_resolve(140)
        mid = validate_success(api.get_boarding_record(record["id"], COORD))
        assert mid["huddle_count_24h"] == 2
        assert mid["executive_escalation"] is False
        escalate_and_resolve(150)
        final = validate_success(api.get_boarding_record(record["id"], COORD))
        assert final["huddle_count_24h"] == 3
        assert final["executive_escalation"] is True
