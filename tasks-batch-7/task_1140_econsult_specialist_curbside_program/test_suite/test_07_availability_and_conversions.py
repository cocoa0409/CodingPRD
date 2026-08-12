"""Availability windows (half-open overlap) and in-person conversions (buffered)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, complete_review, create_consult, create_membership,
    create_specialist, create_track, create_window, get_membership,
    make_specialist_headers, open_review, set_clock,
    setup_answered_consult, setup_assigned_consult, setup_late_answered_consult,
    setup_panel_scenario, submit_response, validate_error, validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestAvailabilityAndConversions:
    def test_overlapping_availability_window_rejected(self, api):
        """PRD §3.2: "Two windows belonging to the same membership may not overlap
        while both are `ACTIVE`: a new window conflicts with an existing `ACTIVE`
        window whenever the new window starts before the existing one ends and the
        existing one starts before the new one ends."
        PRD §3.2: "A genuine overlap is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/availability_windows_half_open_adjacency
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        spec = create_specialist(npi="2000000141")
        membership = create_membership(spec["id"], track["id"])
        create_window(membership["id"], spec["id"],
                      window_start="2026-06-10T10:00:00Z",
                      window_end="2026-06-10T12:00:00Z")
        # [11:00, 13:00) strictly overlaps ACTIVE [10:00, 12:00).
        res = api.create_availability_window(
            {"membership_id": membership["id"],
             "window_start": "2026-06-10T11:00:00Z",
             "window_end": "2026-06-10T13:00:00Z"},
            make_specialist_headers(spec["id"]),
        )
        validate_error(res, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP,
                       expected_status=409)

    def test_adjacent_availability_window_accepted(self, api):
        """PRD §3.2: "Adjacency is not a conflict — a new window starting exactly when
        an existing one ends is allowed."
        PRD §3.2: "The windows of a membership can be listed with an optional `status`
        filter."

        Design: Difficulty/resource_temporal_overlap/availability_windows_half_open_adjacency
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        spec = create_specialist(npi="2000000141")
        membership = create_membership(spec["id"], track["id"])
        create_window(membership["id"], spec["id"],
                      window_start="2026-06-10T10:00:00Z",
                      window_end="2026-06-10T12:00:00Z")
        # Start equals the existing window's end: allowed under half-open semantics.
        adjacent = validate_success(api.create_availability_window(
            {"membership_id": membership["id"],
             "window_start": "2026-06-10T12:00:00Z",
             "window_end": "2026-06-10T14:00:00Z"},
            make_specialist_headers(spec["id"]),
        ), 201)
        assert adjacent["status"] == "ACTIVE"
        windows, _meta = validate_paginated(api.list_membership_windows(
            membership["id"], COORD, params={"status": "ACTIVE"}
        ))
        assert len(windows) == 2

    def test_window_cancel_frees_overlapping_slot(self, api):
        """PRD §3.2: "Two windows belonging to the same membership may not overlap
        while both are `ACTIVE`" — and cancelling moves a window out of `ACTIVE`:
        "the specialist who owns the underlying membership may cancel it, moving it to
        `CANCELLED`"

        Design: Corner/state_machines/window_cancel_frees_overlapping_slot
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        spec = create_specialist(npi="2000002012")
        membership = create_membership(spec["id"], track["id"])
        w1 = create_window(membership["id"], spec["id"],
                           window_start="2026-06-10T10:00:00Z",
                           window_end="2026-06-10T12:00:00Z")
        cancelled = validate_success(api.cancel_availability_window(
            w1["id"], make_specialist_headers(spec["id"])
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        # The cancelled window no longer participates in the overlap check.
        recreated = validate_success(api.create_availability_window(
            {"membership_id": membership["id"],
             "window_start": "2026-06-10T10:00:00Z",
             "window_end": "2026-06-10T12:00:00Z"},
            make_specialist_headers(spec["id"]),
        ), 201)
        assert recreated["status"] == "ACTIVE"

    def test_window_end_before_start_returns_invalid_range(self, api):
        """PRD §3.2: "The end must be strictly later than the start, or creation fails
        with `ERR_WINDOW_INVALID_RANGE`."

        Design: Corner/validations/window_end_before_start_returns_invalid_range
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        spec = create_specialist(npi="2000004015")
        membership = create_membership(spec["id"], track["id"])
        res = api.create_availability_window(
            {"membership_id": membership["id"],
             "window_start": "2026-06-10T12:00:00Z",
             "window_end": "2026-06-10T10:00:00Z"},
            make_specialist_headers(spec["id"]),
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_INVALID_RANGE, expected_status=422)

    def _setup_suspended_membership_with_window(self):
        """Drive a membership to SUSPENDED: late answer (blend 5100 -> PROBATION),
        then REBUKE composite 4000 (blend 2400 < 5000 -> SUSPENDED)."""
        scenario = setup_late_answered_consult(
            patient_ref="PAT-PP2", provider_npi="1000000091",
            specialist_npi="2000000091", reviewer_npi="2000000092",
            consult_overrides={
                "question_text": "Post-MI patient asks about cardiac rehab intensity and return-to-work timing after stent.",
                "icd10_primary": "I21",
            },
        )
        review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
        complete_review(review["id"], scenario["reviewer"]["id"],
                        timeliness_score=2, appropriateness_score=1,
                        clarity_score=4, verdict="REBUKE")
        return scenario

    def test_suspension_setup_reaches_suspended_with_accepting_off(self, api):
        """PRD §3.7: "A membership in `PROBATION` drops to `SUSPENDED` when its score
        falls below 5000 or its `rebuke_count` reaches 2"
        PRD §3.7: "The moment a membership enters `SUSPENDED`, its `is_accepting`
        flips to false"

        Design: Difficulty/priority_pair_validation_conflict/window_create_safety_error_beats_temporal_error
        """
        scenario = self._setup_suspended_membership_with_window()
        membership = get_membership(scenario["membership"]["id"])
        # Review component 4000, timeliness 0 (the only response was late):
        # blend = 0.6 * 4000 + 0.4 * 0 = 2400 < 5000.
        assert membership["quality_score_bps"] == 2400
        assert membership["standing"] == "SUSPENDED"
        assert membership["is_accepting"] is False

    def test_suspended_window_create_safety_error_beats_temporal_error(self, api):
        """PRD §3.2: "A membership whose standing is `SUSPENDED` may not create new
        windows at all; the attempt is rejected with `ERR_MEMBERSHIP_SUSPENDED`."
        PRD §2.8: "Only then are state-machine preconditions evaluated, then the
        standing and segregation-of-duties gates, then uniqueness and cap rules, then
        interval and overlap rules"

        Design: Difficulty/priority_pair_validation_conflict/window_create_safety_error_beats_temporal_error
        """
        scenario = self._setup_suspended_membership_with_window()
        assert get_membership(scenario["membership"]["id"])["standing"] == "SUSPENDED"
        # The requested span [06-15, 06-20) also half-open-overlaps the ACTIVE
        # covering window [2026-05-01, 2027-01-01): both the safety gate (standing)
        # and the temporal gate (overlap) are violated. The standing gate is
        # evaluated earlier, so the safety error is the one returned.
        res = api.create_availability_window(
            {"membership_id": scenario["membership"]["id"],
             "window_start": "2026-06-15T00:00:00Z",
             "window_end": "2026-06-20T00:00:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        error_data = validate_error(res, ApiErrorId.ERR_MEMBERSHIP_SUSPENDED,
                                    expected_status=403)
        assert error_data["error_id"] != "ERR_AVAILABILITY_WINDOW_OVERLAP"

    def _setup_three_conversion_consults(self, api):
        """Three consults answered CONVERT_TO_VISIT by the same specialist; a first
        conversion SCHEDULED [2026-06-10T10:00, 2026-06-10T11:00)."""
        scenario = setup_panel_scenario(provider_npi="1000000151",
                                        specialist_npi="2000000151")
        track_id = scenario["track"]["id"]
        prov_id = scenario["provider"]["id"]
        spec_id = scenario["specialist"]["id"]
        consults = []
        for patient_ref, question, icd in (
            ("PAT-TO1", "Exertional dyspnea with EF 35 percent on echo; convert to heart-failure clinic visit please.", "I50"),
            ("PAT-TO2", "Recurrent presyncope with family history of sudden death; needs in-person evaluation and testing.", "R42"),
            ("PAT-TO3", "Complex congenital history with new symptoms; clearly needs face-to-face congenital clinic visit.", "Q24"),
        ):
            consult = create_consult(track_id, prov_id, patient_ref=patient_ref,
                                     question_text=question, icd10_primary=icd)
            submit_response(consult["id"], spec_id, disposition="CONVERT_TO_VISIT")
            consults.append(consult)
        conv1 = validate_success(api.create_conversion(
            consults[0]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T11:00:00Z"},
            make_specialist_headers(spec_id),
        ), 201)
        return scenario, consults, conv1

    def test_conversion_exactly_thirty_minute_gap_accepted(self, api):
        """PRD §3.8: "Each scheduled appointment effectively occupies its interval
        plus a 30-minute buffer on each side, and a new conversion conflicts with an
        existing `SCHEDULED` conversion of the same specialist whenever the new
        appointment starts before the existing appointment's buffered end — its end
        plus 30 minutes — and the existing appointment starts before the new
        appointment's buffered end. Because both comparisons are strict, a gap of
        exactly 30 minutes between one appointment's end and the next one's start does
        not conflict."

        Design: Difficulty/resource_temporal_overlap/conversion_appointments_buffered_thirty_minutes
        """
        scenario, consults, conv1 = self._setup_three_conversion_consults(api)
        # Exactly 30 minutes after the first appointment's end: no conflict.
        conv2 = validate_success(api.create_conversion(
            consults[1]["id"],
            {"appointment_start": "2026-06-10T11:30:00Z",
             "appointment_end": "2026-06-10T12:00:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        ), 201)
        assert conv2["status"] == "SCHEDULED"

    def test_conversion_twenty_nine_minute_gap_rejected(self, api):
        """PRD §3.8: "A conflicting proposal is rejected with
        `ERR_APPOINTMENT_WINDOW_OVERLAP`." — a start 29 minutes after the previous end
        falls strictly inside the 30-minute buffered end and conflicts.

        Design: Difficulty/resource_temporal_overlap/conversion_appointments_buffered_thirty_minutes
        """
        scenario, consults, conv1 = self._setup_three_conversion_consults(api)
        res = api.create_conversion(
            consults[2]["id"],
            {"appointment_start": "2026-06-10T11:29:00Z",
             "appointment_end": "2026-06-10T12:00:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPOINTMENT_WINDOW_OVERLAP,
                       expected_status=409)

    def test_conversion_create_blocked_until_consult_answered(self, api):
        """PRD §3.8: "The consult must be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`)"

        Design: Difficulty/cross_entity_state_dependency/conversion_create_gated_by_consult_answered
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-CE2", provider_npi="1000000131",
            specialist_npi="2000000131",
            consult_overrides={
                "question_text": "Syncope with exertion in 62-year-old; likely needs in-person structural workup, confirm conversion.",
                "icd10_primary": "R55",
            },
        )
        assert scenario["consult"]["status"] == "ASSIGNED"
        res = api.create_conversion(
            scenario["consult"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONSULT_NOT_ANSWERED, expected_status=409)

    def test_conversion_create_leaves_no_row_when_blocked(self, api):
        """PRD §3.8: "The consult must be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`)"
        PRD §3.8: "Conversions can be listed with filters on `consult_id`,
        `specialist_id`, or `status`."

        Design: Difficulty/cross_entity_state_dependency/conversion_create_gated_by_consult_answered
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-CE2", provider_npi="1000000131",
            specialist_npi="2000000131",
        )
        res = api.create_conversion(
            scenario["consult"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONSULT_NOT_ANSWERED, expected_status=409)
        conversions, _meta = validate_paginated(api.list_conversions(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert conversions == [], "no InPersonConversion row may persist"

    def test_conversion_requires_convert_disposition_rejected(self, api):
        """PRD §3.8: "the response's disposition must be `CONVERT_TO_VISIT`
        (`ERR_DISPOSITION_NOT_CONVERSION`)"

        Design: Corner/validations/conversion_requires_convert_disposition_rejected
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-V9", provider_npi="1000004011",
            specialist_npi="2000004014", disposition="MANAGE_IN_PRIMARY_CARE",
            consult_overrides={
                "question_text": "Cholesterol recheck timing after starting rosuvastatin 20mg; asks about fasting requirement.",
                "icd10_primary": "E78",
            },
            response_overrides={
                "recommendation_text": "Recheck lipid panel at 8 to 12 weeks; fasting not required with modern assays.",
            },
        )
        res = api.create_conversion(
            scenario["consult"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISPOSITION_NOT_CONVERSION,
                       expected_status=409)
        conversions, _meta = validate_paginated(api.list_conversions(
            COORD, params={"consult_id": scenario["consult"]["id"]}
        ))
        assert conversions == []

    def test_complete_conversion_after_cancel_returns_invalid_state(self, api):
        """PRD §3.8: "Both acts require the conversion to still be `SCHEDULED`
        (`ERR_CONVERSION_NOT_SCHEDULED`)"

        Design: Corner/state_machines/complete_conversion_after_cancel_returns_invalid_state
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-S8", provider_npi="1000002009",
            specialist_npi="2000002009", disposition="CONVERT_TO_VISIT",
            consult_overrides={
                "question_text": "Severe aortic stenosis on echo with exertional symptoms; needs valve clinic in person.",
                "icd10_primary": "I35",
            },
        )
        spec_h = make_specialist_headers(scenario["specialist"]["id"])
        conversion = validate_success(api.create_conversion(
            scenario["consult"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            spec_h,
        ), 201)
        cancelled = validate_success(api.cancel_conversion(conversion["id"], spec_h), 200)
        assert cancelled["status"] == "CANCELLED"
        res = api.complete_conversion(conversion["id"], spec_h)
        validate_error(res, ApiErrorId.ERR_CONVERSION_NOT_SCHEDULED,
                       expected_status=409)
