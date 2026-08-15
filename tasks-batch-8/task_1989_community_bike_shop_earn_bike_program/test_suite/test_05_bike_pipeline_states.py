"""Bike pipeline non-linear state machine (queue A) and bike state-machine
corner cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_donor, make_bike, triage_bike, make_part, restock_part,
    make_lead_and_inspector, make_apprentice, log_usage, full_checklist,
    TEST_USERS, make_volunteer_headers, make_volunteer,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestBikeSafetyReworkCycle:
    def test_fail_loops_back_to_refurb_with_rework_count(self):
        """PRD §3.4: "On `FAIL`, the bike loops back `SAFETY_REVIEW →
        IN_REFURBISHMENT` for rework: `latest_inspection_result` becomes `FAIL`,
        `rework_count` increments by 1, and `version` bumps — and the bike may
        be resubmitted after further work."

        Design: Difficulty/non_linear_state_machine/bike_safety_rework_cycle
        """
        donor = make_donor(display_name="D C", donor_type="INDIVIDUAL", email="dc@x.org")
        lead, insp = make_lead_and_inspector()
        bike = make_bike(donor["id"], serial_number="SN-CY", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(bike["id"], "B", False)
        validate_success(
            api_client.route_bike(
                bike["id"],
                {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
                COORD,
            )
        )
        part = make_part(name="Tire 27", category="TIRES", unit_cost_cents=700)
        part = restock_part(part["id"], 10)
        log_usage(bike["id"], part["id"], 1, part["version"], lead["id"])
        validate_success(
            api_client.submit_safety(bike["id"], make_volunteer_headers(lead["id"]))
        )
        # FAIL
        validate_success(
            api_client.create_safety_inspection(
                bike["id"],
                {"result": "FAIL",
                 "checklist": {"brakes": False, "steering": True, "tires": True,
                               "drivetrain": True, "reflectors": True}},
                make_volunteer_headers(insp["id"]),
            ),
            expected_status=201,
        )
        mid = validate_success(api_client.get_bike(bike["id"], COORD))
        assert mid["status"] == "IN_REFURBISHMENT"
        assert mid["rework_count"] == 1
        assert mid["latest_inspection_result"] == "FAIL"

    def test_retry_pass_reaches_ready_and_accumulates_cost(self):
        """PRD §3.4: "On `PASS`, the bike moves `SAFETY_REVIEW →
        READY_FOR_DISPOSITION`, its `latest_inspection_result` becomes `PASS`,
        and its `version` bumps." and PRD §2.8: "A bike's `parts_cost_cents`
        rolls up committed part usages at their frozen snapshot costs".

        Design: Difficulty/non_linear_state_machine/bike_safety_rework_cycle
        """
        donor = make_donor(display_name="D C2", donor_type="INDIVIDUAL", email="dc2@x.org")
        lead, insp = make_lead_and_inspector()
        bike = make_bike(donor["id"], serial_number="SN-CY2", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(bike["id"], "B", False)
        validate_success(
            api_client.route_bike(
                bike["id"],
                {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
                COORD,
            )
        )
        part = make_part(name="Tire 27b", category="TIRES", unit_cost_cents=700)
        part = restock_part(part["id"], 10)
        log_usage(bike["id"], part["id"], 1, part["version"], lead["id"])
        validate_success(
            api_client.submit_safety(bike["id"], make_volunteer_headers(lead["id"]))
        )
        validate_success(
            api_client.create_safety_inspection(
                bike["id"],
                {"result": "FAIL",
                 "checklist": {"brakes": False, "steering": True, "tires": True,
                               "drivetrain": True, "reflectors": True}},
                make_volunteer_headers(insp["id"]),
            ),
            expected_status=201,
        )
        # rework: second usage + resubmit + PASS
        part_now = validate_success(api_client.get_part(part["id"], COORD))
        log_usage(bike["id"], part["id"], 1, part_now["version"], lead["id"])
        validate_success(
            api_client.submit_safety(bike["id"], make_volunteer_headers(lead["id"]))
        )
        validate_success(
            api_client.create_safety_inspection(
                bike["id"],
                {"result": "PASS", "checklist": full_checklist(True)},
                make_volunteer_headers(insp["id"]),
            ),
            expected_status=201,
        )
        final = validate_success(api_client.get_bike(bike["id"], COORD))
        assert final["status"] == "READY_FOR_DISPOSITION"
        assert final["rework_count"] == 1
        assert final["latest_inspection_result"] == "PASS"
        assert final["parts_cost_cents"] == 1400


class TestBikeStateCorners:
    def test_submit_safety_from_triaged_returns_invalid_state(self):
        """PRD §3.4: "When the accountable mechanic judges a bike finished, an
        `ACTIVE` volunteer submits it for safety review" — the transition is
        defined only from `IN_REFURBISHMENT`; PRD §2.7: "`ERR_INVALID_STATE`
        when no more specific code applies".

        Design: Corner/state_machines/submit_safety_from_triaged_returns_invalid_state
        """
        donor = make_donor(display_name="D IV", donor_type="INDIVIDUAL", email="div@x.org")
        bike = make_bike(donor["id"], serial_number="SN-IV", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(bike["id"], "B", False)
        v = make_volunteer(full_name="V S", email="vs@x.org")
        r = api_client.submit_safety(bike["id"], make_volunteer_headers(v["id"]))
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "TRIAGED"

    def test_triage_invalid_enum_returns_validation(self):
        """PRD §2.7: "Request well-formedness — required fields present, JSON
        types valid, enum members recognized, fixed numeric ranges such as the
        1-to-6-hour claim bound — runs alongside the envelope and auth checks,
        before any resource lookup, and fails with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/triage_invalid_enum_returns_invalid_request
        """
        donor = make_donor(display_name="D EN", donor_type="INDIVIDUAL", email="den@x.org")
        bike = make_bike(donor["id"], serial_number="SN-EN", bike_type="ROAD", wheel_size_inches=27)
        r = api_client.triage_bike(
            bike["id"], {"condition_grade": "Z", "frame_damage": False}, COORD
        )
        validate_error(r, ApiErrorId.ERR_VALIDATION)
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "RECEIVED"

    def test_grade_routing_rules(self):
        """PRD §3.2: "Routing with `destination` set to refurbish moves the bike
        `TRIAGED → IN_REFURBISHMENT` and is allowed only when the grade is `A`,
        `B`, or `C`; a grade-`D` bike routed to refurbishment is rejected with
        `ERR_GRADE_NOT_REFURBISHABLE`." and "Routing to harvest moves the bike
        `TRIAGED → HARVEST_QUEUE` and requires grade `C` or `D`; routing an `A`
        or `B` grade bike to harvest is rejected with
        `ERR_GRADE_NOT_HARVESTABLE`." and "Routing to scrap moves the bike
        `TRIAGED → SCRAP_PENDING` and is the strictest branch: the grade must be
        exactly `D` and `frame_damage` must be true, or the request fails with
        `ERR_SCRAP_CRITERIA_NOT_MET`."

        Design: Corner/validations/grade_routing_rules
        """
        donor = make_donor(display_name="D GR", donor_type="INDIVIDUAL", email="dgr@x.org")
        # An existing, eligible (APPRENTICE, ACTIVE) lead: with every other
        # precondition satisfied, the grade gate is the sole failing rule.
        lead = make_apprentice()
        b1 = make_bike(donor["id"], serial_number="SN-G1", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(b1["id"], "D", True)
        b2 = make_bike(donor["id"], serial_number="SN-G2", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(b2["id"], "A", False)
        b3 = make_bike(donor["id"], serial_number="SN-G3", bike_type="MTB", wheel_size_inches=29)
        triage_bike(b3["id"], "C", True)
        b4 = make_bike(donor["id"], serial_number="SN-G4", bike_type="BMX", wheel_size_inches=20)
        triage_bike(b4["id"], "D", False)

        r1 = api_client.route_bike(
            b1["id"],
            {"destination": "REFURBISH",
             "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
        validate_error(r1, ApiErrorId.ERR_GRADE_NOT_REFURBISHABLE)
        r2 = api_client.route_bike(b2["id"], {"destination": "HARVEST"}, COORD)
        validate_error(r2, ApiErrorId.ERR_GRADE_NOT_HARVESTABLE)
        r3 = api_client.route_bike(b3["id"], {"destination": "SCRAP"}, COORD)
        validate_error(r3, ApiErrorId.ERR_SCRAP_CRITERIA_NOT_MET)
        r4 = api_client.route_bike(b4["id"], {"destination": "SCRAP"}, COORD)
        validate_error(r4, ApiErrorId.ERR_SCRAP_CRITERIA_NOT_MET)
        ok = validate_success(api_client.route_bike(b1["id"], {"destination": "SCRAP"}, COORD))
        assert ok["status"] == "SCRAP_PENDING"
