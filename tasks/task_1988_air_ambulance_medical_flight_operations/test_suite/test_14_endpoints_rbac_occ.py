"""Endpoint side-effect claims, RBAC exclusive grants/denials, segregation of
duties, optimistic concurrency, list filtering, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    accept_request,
    advance_ground_leg,
    api_client,
    create_aircraft,
    create_base,
    create_crew_member,
    create_ground_leg,
    create_mission_request,
    create_patient,
    create_pcr,
    get_success_data,
    make_flight_crew_headers,
    make_qa_reviewer_headers,
    post_go_weather,
    post_weather,
    qa_review,
    set_clock,
    setup_base_with_crew,
    setup_completed_mission,
    setup_planning_mission,
    setup_repatriation_mission,
    setup_triaged_request,
    submit_pcr,
    triage_request,
    update_membership_safe,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


class TestAcceptCreatesMissionWithSnapshots:
    def test_accept_returns_201_and_mission_snapshots_request_fields(self):
        """PRD §3.3: "A successful acceptance writes several records at once.
        The request moves `TRIAGED` to `ACCEPTED`. Exactly one `Mission` is
        created per request, carrying the `mission_request_id` back-reference,
        born in `PLANNING`, and snapshotting `transport_class`, `acuity_tier`,
        and `destination_facility` from the request at that moment. The tail
        transitions `AVAILABLE` to `ASSIGNED` and its `version` bumps. One
        `CrewAssignment` per roster entry is created in `ASSIGNED` status."
        PRD §4: "Operations that create a new resource return `201 Created`."

        Design: Corner/endpoints/accept_creates_mission_with_snapshots
        """
        ctx_ready = None
        set_clock()
        base, aircraft, roster = setup_base_with_crew(medical_config="CCT_CAPABLE")
        _, request = setup_triaged_request()  # ALS (5.8, stale onset: no bonus)
        resp = api_client.accept_mission_request(
            request["id"],
            {
                "aircraft_id": aircraft["id"],
                "crew": [
                    {"crew_member_id": roster["PILOT"]["id"], "role_in_mission": "PILOT"},
                    {"crew_member_id": roster["NURSE"]["id"], "role_in_mission": "NURSE"},
                ],
                "estimated_loaded_miles": 55,
                "planned_launch_iso": "2026-08-01T06:00:00Z",
                "planned_duration_min": 120,
            },
            DISP,
        )
        mission = get_success_data(resp, 201)
        assert mission["id"]
        assert mission["transport_class"] == "EMERGENCY_INTERFACILITY"
        assert mission["acuity_tier"] == "ALS", (
            f"Snapshot of the 5.8 acceptance score tier, got {mission['acuity_tier']}"
        )
        assert mission["destination_facility"] == "County General"
        assert mission["status"] == "PLANNING"
        assert mission["version"] == 1
        req_after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert req_after["status"] == "ACCEPTED"
        aircraft_after = get_success_data(api_client.get_aircraft(aircraft["id"], DISP))
        assert aircraft_after["status"] == "ASSIGNED"


class TestGroundLegCompletionDrivesCoordinationStatus:
    def test_leg_completion_flips_pending_to_coordinated(self):
        """PRD §3.6: "The mission's `ground_coordination_status` summarizes all
        of this for the read view, and it is recomputed on every relevant
        change. ... Otherwise it reads `PENDING` when any non-`CANCELLED` leg
        has not yet reached `COMPLETED`. Otherwise — every surviving leg
        completed, and no orphaned cancellation — it reads `COORDINATED`."
        PRD §3.6: "reaching `COMPLETED` recomputes the mission's
        ground-coordination indicator."

        Design: Corner/endpoints/ground_leg_completion_drives_coordination_status
        """
        ctx = setup_planning_mission(estimated_loaded_miles=55)
        mission = ctx["mission"]
        leg = create_ground_leg(mission["id"], leg_type="DESTINATION")
        mid = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert mid["ground_coordination_status"] == "PENDING"
        advance_ground_leg(leg["id"], "ENROUTE")
        advance_ground_leg(leg["id"], "AT_BEDSIDE")
        advance_ground_leg(leg["id"], "COMPLETED")
        after = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert after["ground_coordination_status"] == "COORDINATED", (
            f"All surviving legs completed -> COORDINATED, got {after['ground_coordination_status']}"
        )


class TestRbacExclusiveDenials:
    def test_dispatcher_cannot_triage(self):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a caller whose role is not listed
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.2: "Clinical triage belongs to the `MedicalDirector`."

        Design: Corner/rbac/dispatcher_cannot_triage_returns_forbidden
        """
        set_clock()
        patient = create_patient(full_name="Rbac One", date_of_birth="1990-01-01", weight_kg=70)
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 1, "resp": 1, "neuro": 1, "interv": 1},
            transport_class="EMERGENCY_SCENE", origin_facility="Scene",
            onset_iso="2026-07-31T10:00:00Z",
        )
        resp = api_client.triage_mission_request(
            request["id"],
            {"verified_cardio": 1, "verified_resp": 1, "verified_neuro": 1, "verified_interventions": 1},
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "RECEIVED"

    def test_flightcrew_cannot_verify_repatriation(self):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a caller whose role is not listed
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the repatriation verify endpoint is authorized for
        MedicalDirector only.

        Design: Corner/rbac/flightcrew_cannot_verify_repatriation_returns_forbidden
        """
        ctx, case = setup_repatriation_mission()
        pilot = ctx["roster"]["PILOT"]
        resp = api_client.verify_repatriation_case(
            case["id"], make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
        assert after["status"] == "COLLECTING"

    def test_qa_reviewer_cannot_create_aircraft(self):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a caller whose role is not listed
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: aircraft registration is authorized for OpsAdmin only.

        Design: Corner/rbac/qa_reviewer_cannot_create_aircraft_returns_forbidden
        """
        base = create_base(name="Base A")
        resp = api_client.create_aircraft(
            {
                "base_id": base["id"],
                "tail_number": "N700QA",
                "aircraft_class": "ROTOR_WING",
                "medical_config": "BLS_CAPABLE",
            },
            make_qa_reviewer_headers("qa-officer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        data, meta = validate_paginated(
            api_client.list_aircraft(OPS, params={"base_id": base["id"]})
        )
        assert meta["total_count"] == 0, "No aircraft may be persisted by the rejected call"

    def test_pcr_author_identity_mismatch_forbidden(self):
        """PRD §2.1: "clinical-record create, submit, and amend require the
        record's `author_crew_id` to equal `X-User-ID`, and shift create and
        close require the shift's `crew_member_id` to equal `X-User-ID`; a
        mismatch is rejected with `ERR_FORBIDDEN`."
        PRD §3.9: "A `FlightCrew` caller opens the record with the `mission_id`,
        an `author_crew_id` that must equal the caller's `X-User-ID` (else
        `ERR_FORBIDDEN`)."

        Design: Corner/rbac/pcr_author_identity_mismatch_forbidden
        """
        ctx = setup_completed_mission(transport_class="EMERGENCY_SCENE", origin_facility="Scene")
        pilot = ctx["roster"]["PILOT"]
        nurse = ctx["roster"]["NURSE"]
        # The pilot attempts to author a record in the nurse's name.
        resp = api_client.create_patient_care_report(
            {
                "mission_id": ctx["mission"]["id"],
                "author_crew_id": nurse["id"],
                "vitals_summary": "x",
                "interventions_summary": "x",
                "meds_summary": "x",
            },
            make_flight_crew_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        data, meta = validate_paginated(
            api_client.list_patient_care_reports(DISP, params={"mission_id": ctx["mission"]["id"]})
        )
        assert meta["total_count"] == 0, "No PCR may be persisted under a mismatched author"

    def test_qa_self_review_forbidden(self):
        """PRD §2.1: "A `QaReviewer` performs clinical quality-assurance review
        and may never review a record they authored; when a `QaReviewer`
        caller's `X-User-ID` equals the record's `author_crew_id`, the review is
        rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403) rather than the
        generic `ERR_FORBIDDEN`."

        Design: Corner/rbac/qa_self_review_forbidden
        """
        ctx = setup_completed_mission(transport_class="EMERGENCY_SCENE", origin_facility="Scene")
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        submit_pcr(pcr["id"], pilot)
        resp = api_client.qa_review_patient_care_report(
            pcr["id"],
            {"outcome": "APPROVED", "deficiency_points": 0},
            make_qa_reviewer_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN, 403)
        after = get_success_data(api_client.get_patient_care_report(pcr["id"], DISP))
        assert after["status"] == "SUBMITTED"


class TestBillingSpecialistMembershipLifecycleAllowed:
    def test_create_lapse_reinstate_full_cycle(self):
        """PRD §3.2: "A `BillingSpecialist` enrolls a patient by supplying the
        `patient_id`, a `tier` of `STANDARD` or `FAMILY`, and an
        `effective_from` date; the subscription is born `ACTIVE` ... When a
        subscriber stops paying, the specialist lapses the subscription:
        `ACTIVE` to `LAPSED`, which stamps `lapsed_at` with the logical now.
        Reinstatement — `LAPSED` back to `ACTIVE` — is permitted only within 30
        days of the lapse ... and a successful reinstatement clears `lapsed_at`
        back to null."

        Design: Corner/rbac/billing_specialist_membership_lifecycle_allowed
        """
        set_clock("2026-08-01T12:00:00Z")
        patient = create_patient(full_name="Mem Ber", date_of_birth="1988-08-08", weight_kg=70)
        membership = get_success_data(
            api_client.create_membership(
                {"patient_id": patient["id"], "tier": "FAMILY", "effective_from": "2026-08-01"},
                BILL,
            ),
            201,
        )
        assert membership["status"] == "ACTIVE"
        lapsed = update_membership_safe(membership["id"], "LAPSED")
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapsed_at"].startswith("2026-08-01T12:00:00"), (
            f"Lapse stamps lapsed_at with the logical now, got {lapsed['lapsed_at']}"
        )
        reinstated = update_membership_safe(membership["id"], "ACTIVE")
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("lapsed_at") is None


class TestOccWeatherStaleVersionRejected:
    def test_second_assessment_with_stale_expected_version_rejected(self):
        """PRD §2.6: "filing a weather assessment against a mission requires the
        request to carry `expected_mission_version`, equal to the mission's
        current `version` as last observed by the client. Each filed assessment
        itself mutates the mission (it rewrites `last_weather_decision` and
        bumps the mission's `version`), so a writer holding a stale observed
        version must re-read the mission before filing; a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_weather_stale_version_rejected
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        observed_version = mission["version"]
        wa1 = post_weather(mission["id"], observed_version, pilot)
        assert wa1["id"]
        # Mission.version advanced to observed_version + 1; replaying the stale
        # observed version must be rejected.
        resp = api_client.create_weather_assessment(
            {
                "mission_id": mission["id"],
                "ceiling_ft": 1200, "visibility_sm": 6.0, "wind_kt": 8,
                "precip": "NONE", "day_night": "DAY", "terrain": "FLAT",
                "expected_mission_version": observed_version,
            },
            make_flight_crew_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        data, meta = validate_paginated(
            api_client.list_weather_assessments(DISP, params={"mission_id": mission["id"]})
        )
        assert meta["total_count"] == 1, "Only the first assessment may be persisted"


class TestOccPcrAmendStaleVersionRejected:
    def test_sequential_amends_guarded_by_version(self):
        """PRD §2.6: "amending a quality-flagged clinical record requires the
        request to carry `expected_patient_care_report_version`, equal to the
        record's current `version`. A successful amend leaves the record in
        `AMENDED` and bumps its `version`, so the version arithmetic is the only
        staleness signal on sequential amends; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_pcr_amend_stale_version_rejected
        """
        ctx = setup_completed_mission(transport_class="EMERGENCY_SCENE", origin_facility="Scene")
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        submit_pcr(pcr["id"], pilot)
        # 3 points: below the 15 remediation threshold, no hold fires.
        qa_review(pcr["id"], "FLAGGED", 3, reviewer_id="qa-officer-6")
        current = get_success_data(api_client.get_patient_care_report(pcr["id"], DISP))
        amended = get_success_data(
            api_client.amend_patient_care_report(
                pcr["id"],
                {
                    "expected_patient_care_report_version": current["version"],
                    "vitals_summary": "corrected vitals",
                },
                make_flight_crew_headers(pilot["id"]),
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["version"] == current["version"] + 1
        # Replay the now-stale observed version: only the version guard can fire.
        resp = api_client.amend_patient_care_report(
            pcr["id"],
            {
                "expected_patient_care_report_version": current["version"],
                "meds_summary": "second stale amend",
            },
            make_flight_crew_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        member = get_success_data(api_client.get_crew_member(pilot["id"], DISP))
        assert member["deficiency_points_90d"] == 3, "Below the threshold: no remediation hold"
        assert member["status"] == "ACTIVE"


class TestMissionRequestListStatusFilter:
    def test_status_filter_partitions_the_list(self):
        """PRD §2.3: "In addition to the paging pair, each list endpoint accepts
        resource-matched filter parameters."
        PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/complexity_layers/mission_request_list_status_filter
        """
        set_clock()
        patient = create_patient(full_name="Filter Test", date_of_birth="1991-01-01", weight_kg=70)
        req_a = create_mission_request(
            patient["id"], subscales={"cardio": 1, "resp": 1, "neuro": 1, "interv": 1},
            transport_class="EMERGENCY_SCENE", origin_facility="Scene A",
            onset_iso="2026-07-31T20:00:00Z",
        )
        req_b = create_mission_request(
            patient["id"], subscales={"cardio": 2, "resp": 2, "neuro": 2, "interv": 2},
            transport_class="EMERGENCY_SCENE", origin_facility="Scene B",
            onset_iso="2026-07-31T20:00:00Z",
        )
        triage_request(req_a["id"], subscales={"cardio": 1, "resp": 1, "neuro": 1, "interv": 1})
        data_t, meta_t = validate_paginated(
            api_client.list_mission_requests(DISP, params={"status": "TRIAGED"})
        )
        assert meta_t["total_count"] == 1
        assert data_t[0]["id"] == req_a["id"]
        data_r, meta_r = validate_paginated(
            api_client.list_mission_requests(DISP, params={"status": "RECEIVED"})
        )
        assert meta_r["total_count"] == 1
        assert data_r[0]["id"] == req_b["id"]


class TestWritesImmediatelyVisibleOnReread:
    def test_create_and_mutation_visible_on_immediate_reread(self):
        """PRD §2.4: "Every primary resource carries a standard set of
        system-managed fields: `id`, a server-minted UUID with no type prefix;
        ... and `version`, an integer that increments by exactly one on every
        mutation of the resource."
        PRD §3.1: "A newly registered aircraft enters service as `AVAILABLE`."
        PRD §3.1: "an `OpsAdmin` may set an `AVAILABLE` tail to `MAINTENANCE`
        and return a `MAINTENANCE` tail to `AVAILABLE`."

        Design: Corner/consistency_model/writes_immediately_visible_on_reread
        """
        base = create_base(name="Base A")
        created = get_success_data(
            api_client.create_aircraft(
                {
                    "base_id": base["id"],
                    "tail_number": "N900IC",
                    "aircraft_class": "FIXED_WING",
                    "medical_config": "ALS_CAPABLE",
                },
                OPS,
            ),
            201,
        )
        assert created["status"] == "AVAILABLE"
        assert created["version"] == 1
        reread = get_success_data(api_client.get_aircraft(created["id"], OPS))
        assert reread["status"] == "AVAILABLE", "Create visible on immediate reread"
        updated = get_success_data(
            api_client.update_aircraft(created["id"], {"status": "MAINTENANCE"}, OPS)
        )
        assert updated["status"] == "MAINTENANCE"
        assert updated["version"] == 2, "Mutation visible in its own response"
        reread2 = get_success_data(api_client.get_aircraft(created["id"], DISP))
        assert reread2["status"] == "MAINTENANCE"
        assert reread2["version"] == 2, "A different role sees the same committed state"
