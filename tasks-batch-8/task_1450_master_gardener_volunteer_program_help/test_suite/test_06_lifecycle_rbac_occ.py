"""Year-end close cascade, volunteer lifecycle, RBAC/auth, OCC, and envelope
behavior."""
import pytest

from test_helpers import (ApiErrorId, NON_EXISTENT_UUID, assert_same_instant,
                          create_accepted_volunteer, create_active_volunteer,
                          create_and_open_cycle, create_cycle,
                          create_credit_entry_payload, create_cycle_payload,
                          create_enrollment_payload, create_shift,
                          create_specialist, get_record_for, get_success_data,
                          log_service_entry, make_specialist_headers,
                          make_volunteer_headers, move_cycle_to_recertification,
                          set_clock, setup_cycle_closed_with_shortfall_volunteer,
                          setup_cycle_with_active_volunteer, sign_up,
                          validate_error, validate_paginated, validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]


class TestYearEndCloseCascade:
    def test_cycle_close_shortfall_four_hop_cascade_record_and_volunteer(
            self, api):
        """PRD §3.8: "Link two applies the volunteer consequences: a
        `RECERTIFIED` volunteer stays `ACTIVE` and has
        `consecutive_shortfall_cycles` reset to zero, while a `SHORTFALL`
        volunteer transitions `ACTIVE → INACTIVE` and has
        `consecutive_shortfall_cycles` incremented by one."

        Design: Difficulty/transitive_cascade/cycle_close_shortfall_four_hop_cascade
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"], capacity=1,
                             start_time="2026-12-05T09:00:00Z",
                             end_time="2026-12-05T12:00:00Z")
        su = sign_up(shift["id"], vol["id"])
        assert get_success_data(
            api.get_shift(shift["id"], COORD))["status"] == "FULL"
        move_cycle_to_recertification(cycle["id"])
        get_success_data(api.close_cycle(cycle["id"], COORD))

        cyc_after = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cyc_after["status"] == "CLOSED"
        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["status"] == "SHORTFALL"
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_after["status"] == "INACTIVE"
        assert vol_after["consecutive_shortfall_cycles"] == 1

    def test_cycle_close_shortfall_four_hop_cascade_signup_and_shift(
            self, api):
        """PRD §3.8: "Link three runs the deactivation cascade for each
        volunteer deactivated at link two: their `SIGNED_UP` signups become
        `CANCELLED`, their `PENDING` credit entries become `VOIDED`, and
        their `ENROLLED` enrollments become `DROPPED`. Link four settles
        shift capacity: each signup cancelled at link three decrements its
        shift's `filled_count` by one, and a shift that was `FULL` reverts to
        `OPEN`."

        Design: Difficulty/transitive_cascade/cycle_close_shortfall_four_hop_cascade
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"], capacity=1,
                             start_time="2026-12-05T09:00:00Z",
                             end_time="2026-12-05T12:00:00Z")
        su = sign_up(shift["id"], vol["id"])
        move_cycle_to_recertification(cycle["id"])
        get_success_data(api.close_cycle(cycle["id"], COORD))

        su_after = get_success_data(api.get_signup(su["id"], COORD))
        assert su_after["status"] == "CANCELLED"
        shift_after = get_success_data(api.get_shift(shift["id"], COORD))
        assert shift_after["status"] == "OPEN"
        assert shift_after["filled_count"] == 0


class TestVolunteerLifecycleCycle:
    def test_volunteer_active_inactive_reactivation_cycle_statuses(self, api):
        """PRD §3.8: "The volunteer lifecycle is thus cyclic across years:
        `TRAINEE` at intake, `ACTIVE ↔ INACTIVE` across recertifications and
        reactivations, and `EXITED` or `WITHDRAWN` as the terminal exits."
        PRD §3.8: "The reverse path is reactivation, a coordinator action
        valid only on an `INACTIVE` volunteer (otherwise
        `ERR_VOLUNTEER_NOT_INACTIVE`) and only while at least one cycle is
        `OPEN` (otherwise `ERR_NO_OPEN_CYCLE`)."

        Design: Difficulty/non_linear_state_machine/volunteer_active_inactive_reactivation_cycle
        """
        cycle1, vol = setup_cycle_closed_with_shortfall_volunteer()
        assert vol["status"] == "INACTIVE"
        assert vol["consecutive_shortfall_cycles"] == 1

        cycle2 = create_and_open_cycle(year_label="2027",
                                       start_date="2027-01-01",
                                       end_date="2027-12-31",
                                       recert_opens_at="2027-11-01T00:00:00Z")
        resp = api.reactivate_volunteer(vol["id"], COORD)
        reactivated = validate_success(resp)
        assert reactivated["status"] == "ACTIVE"
        rec2 = get_record_for(vol["id"], cycle2["id"])
        assert rec2["status"] == "PENDING"

    def test_volunteer_second_consecutive_shortfall_exits(self, api):
        """PRD §3.8: "Finally, any volunteer whose
        `consecutive_shortfall_cycles` reaches two at link two continues from
        `INACTIVE` to terminal `EXITED` within the same close run."

        Design: Difficulty/non_linear_state_machine/volunteer_active_inactive_reactivation_cycle
        """
        cycle1, vol = setup_cycle_closed_with_shortfall_volunteer()
        cycle2 = create_and_open_cycle(year_label="2027",
                                       start_date="2027-01-01",
                                       end_date="2027-12-31",
                                       recert_opens_at="2027-11-01T00:00:00Z")
        get_success_data(api.reactivate_volunteer(vol["id"], COORD))
        # No approved hours in cycle2 either: second consecutive shortfall.
        move_cycle_to_recertification(cycle2["id"],
                                      clock="2027-11-02T00:00:00Z")
        get_success_data(api.close_cycle(cycle2["id"], COORD))

        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_after["status"] == "EXITED"
        assert vol_after["consecutive_shortfall_cycles"] == 2
        rec1 = get_record_for(vol["id"], cycle1["id"])
        rec2 = get_record_for(vol["id"], cycle2["id"])
        assert rec1["status"] == "SHORTFALL"
        assert rec2["status"] == "SHORTFALL"

    def test_reactivate_without_open_cycle_returns_409(self, api):
        """PRD §3.8: "The reverse path is reactivation, a coordinator action
        valid only on an `INACTIVE` volunteer (otherwise
        `ERR_VOLUNTEER_NOT_INACTIVE`) and only while at least one cycle is
        `OPEN` (otherwise `ERR_NO_OPEN_CYCLE`)."

        Design: Corner/errors/reactivate_without_open_cycle_returns_409
        """
        _cycle, vol = setup_cycle_closed_with_shortfall_volunteer()
        assert vol["status"] == "INACTIVE"
        resp = api.reactivate_volunteer(vol["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_CYCLE)
        after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert after["status"] == "INACTIVE"

    def test_volunteer_withdraw_cascades_signup_and_entry(self, api):
        """PRD §3.8: "Withdrawal — invoked by a coordinator or by the
        volunteer themself — moves a `TRAINEE`, `ACTIVE`, or `INACTIVE`
        volunteer to terminal `WITHDRAWN` and runs the same deactivation
        cascade: signups cancelled with their `filled_count` decrements and
        `FULL → OPEN` reverts, `PENDING` entries voided, and `ENROLLED`
        enrollments dropped."

        Design: Corner/state_machines/volunteer_withdraw_cascades_signup_and_entry
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"], capacity=2)
        su = sign_up(shift["id"], vol["id"])
        entry = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-05")

        resp = api.withdraw_volunteer(vol["id"], COORD)
        withdrawn = validate_success(resp)
        assert withdrawn["status"] == "WITHDRAWN"

        su_after = get_success_data(api.get_signup(su["id"], COORD))
        assert su_after["status"] == "CANCELLED"
        shift_after = get_success_data(api.get_shift(shift["id"], COORD))
        assert shift_after["filled_count"] == 0
        entry_after = get_success_data(api.get_credit_entry(entry["id"],
                                                            COORD))
        assert entry_after["status"] == "VOIDED"


class TestRbacAndAuth:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api._request("POST", "/program-cycles",
                            create_cycle_payload(), headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_volunteer_cannot_approve_credit_entry(self, api):
        """PRD §2.1: "An authenticated caller whose role is not listed for an
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /credit-entries/{entryId}/approve — "ProgramCoordinator"

        Design: Corner/validations/volunteer_cannot_approve_credit_entry
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-05")
        resp = api.approve_credit_entry(
            entry["id"], make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_credit_entry(entry["id"], COORD))
        assert after["status"] == "PENDING"

    def test_volunteer_cannot_cancel_other_volunteers_signup(self, api):
        """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the
        `id` of the acting `Volunteer`; ownership checks on any resource that
        references a `Volunteer` compare the resource's foreign-key field to
        `X-User-ID` — the `volunteerId` path segment on self-service credit
        entries, a signup's `volunteer_id`, an inquiry's `volunteer_id`, and
        a project's `organizer_volunteer_id`. ... Any entity-backed identity
        mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/volunteer_cannot_cancel_other_volunteers_signup
        """
        cycle = create_and_open_cycle()
        vol1 = create_active_volunteer(cycle["id"],
                                       applicant_name="Alice Arbor",
                                       email="alice@example.org")
        vol2 = create_accepted_volunteer(cycle["id"],
                                         applicant_name="Bob Birch",
                                         email="bob@example.org",
                                         county="Cecil",
                                         prior_gardening_years=3)
        shift = create_shift(cycle["id"])
        su1 = sign_up(shift["id"], vol1["id"])
        resp = api.cancel_signup(su1["id"], make_volunteer_headers(vol2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        after = get_success_data(api.get_signup(su1["id"], COORD))
        assert after["status"] == "SIGNED_UP"

    def test_not_found_beats_ownership_returns_404(self, api):
        """PRD §2.9: "(4) existence — path identifiers and referenced body
        identifiers (`cycle_id`, `volunteer_id`, `source_id`,
        `specialist_id`, `follow_up_of_id`, `new_volunteer_id`) must resolve
        to existing resources — `ERR_NOT_FOUND` (HTTP 404); (5) entity-backed
        ownership — `ERR_NOT_RESOURCE_OWNER`;"

        Design: Corner/validations/not_found_beats_ownership_returns_404
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        resp = api.create_credit_entry(
            NON_EXISTENT_UUID,
            create_credit_entry_payload(cycle["id"], hours=2.0),
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_schema_beats_existence_returns_400(self, api):
        """PRD §2.9: "Every request is validated in a fixed sequence of
        tiers, and the first failing tier produces the response; later tiers
        are never consulted once an earlier tier fails. The sequence is: ...
        (3) schema validation of required fields, types, enum membership, and
        static ranges — `ERR_INVALID_REQUEST` (HTTP 400) for missing fields,
        wrong types, invalid enum members, or malformed values ...; (4)
        existence — path identifiers and referenced body identifiers
        (`cycle_id`, `volunteer_id`, `source_id`, `specialist_id`,
        `follow_up_of_id`, `new_volunteer_id`) must resolve to existing
        resources — `ERR_NOT_FOUND` (HTTP 404);"

        Design: Corner/validations/schema_beats_existence_returns_400
        """
        resp = api.create_application(
            {"cycle_id": NON_EXISTENT_UUID, "applicant_name": "No Email",
             "county": "Harford", "prior_gardening_years": 2}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_volunteer_get_unknown_id_returns_404(self, api):
        """PRD §2.9: "(4) existence — path identifiers and referenced body
        identifiers (`cycle_id`, `volunteer_id`, `source_id`,
        `specialist_id`, `follow_up_of_id`, `new_volunteer_id`) must resolve
        to existing resources — `ERR_NOT_FOUND` (HTTP 404);"

        Design: Corner/entities/volunteer_get_unknown_id_returns_404
        """
        resp = api.get_volunteer(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_specialist_cannot_triage_inquiry_returns_403(self, api):
        """PRD §2.1: "An authenticated caller whose role is not listed for an
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /inquiries/{inquiryId}/triage — "ProgramCoordinator"

        Design: Corner/rbac/specialist_cannot_triage_inquiry_returns_403
        """
        from test_helpers import (log_inquiry, setup_staffed_help_desk_shift)
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq = log_inquiry(shift["id"], vol["id"])
        resp = api.triage_inquiry(inq["id"], {"category": "PEST"},
                                  make_specialist_headers(spec["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_inquiry(inq["id"], COORD))
        assert after["status"] == "LOGGED"

    def test_specialist_cannot_start_review_others_referral(self, api):
        """PRD §3.5: "Starting review requires the referral to be `OPEN`
        (otherwise `ERR_REFERRAL_NOT_OPEN`) and the caller to be the assignee
        (`ERR_NOT_RESOURCE_OWNER`), moving it `OPEN → IN_REVIEW`."
        PRD §3.5: "Ranking is by `open_referral_count` ascending, then
        `rolling_score` descending, then `created_at` ascending, and the
        top-ranked specialist is assigned."

        Design: Corner/rbac/specialist_cannot_start_review_others_referral
        """
        from test_helpers import (create_referral, setup_triaged_inquiry)
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One")
        s2 = create_specialist(name="Dr. Pest Two")
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        ref = create_referral(inq["id"])
        assert ref["specialist_id"] == s1["id"]  # 0/0 tie, created first
        resp = api.start_review(ref["id"], make_specialist_headers(s2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        after = get_success_data(api.get_referral(ref["id"], COORD))
        assert after["status"] == "OPEN"

    def test_shared_read_endpoints_allow_all_roles(self, api):
        """PRD §4: "Rows marked "All roles" are readable by
        `ProgramCoordinator`, `Volunteer`, and `Specialist` alike."

        Design: Corner/rbac/shared_read_endpoints_allow_all_roles
        """
        cycle = create_and_open_cycle()
        vol = create_accepted_volunteer(cycle["id"])
        spec = create_specialist()
        r_coord = validate_success(api.get_volunteer(vol["id"], COORD))
        r_vol = validate_success(api.get_volunteer(
            vol["id"], make_volunteer_headers(vol["id"])))
        r_spec = validate_success(api.get_volunteer(
            vol["id"], make_specialist_headers(spec["id"])))
        assert r_coord["id"] == r_vol["id"] == r_spec["id"] == vol["id"]
        assert r_coord["full_name"] == r_vol["full_name"] == \
            r_spec["full_name"]


class TestOptimisticConcurrency:
    def test_cycle_update_with_stale_version_returns_412(self, api):
        """PRD §2.8: "A `PUT /program-cycles/{cycleId}` request, the cycle
        configuration edit, must carry `expected_cycle_version`, a
        non-optional field holding the cycle's `version` the client last
        observed; if another permitted update has advanced the cycle's
        version since then, the edit is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §2.8: "A successful guarded write increments the parent
        resource's `version` by exactly one."

        Design: Corner/cross_cutting_complexity_layers/cycle_update_with_stale_version_returns_412
        """
        cycle = create_cycle()
        resp = api.update_cycle(
            cycle["id"],
            {"expected_cycle_version": cycle["version"],
             "hour_requirement": 36.0}, COORD)
        updated = validate_success(resp)
        assert updated["version"] == 2

        resp = api.update_cycle(
            cycle["id"],
            {"expected_cycle_version": cycle["version"],  # stale (1)
             "ce_requirement": 8.0}, COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION)

        cur = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cur["version"] == 2
        assert cur["hour_requirement"] == pytest.approx(36.0, abs=0.01)
        assert cur["ce_requirement"] == pytest.approx(10.0, abs=0.01)

    def test_project_amend_with_stale_version_returns_412(self, api):
        """PRD §2.8: "A `PUT /projects/{projectId}` request, the project
        amendment, must likewise carry `expected_project_version`, and a
        mismatch with the project's current `version` — whether advanced by a
        prior accepted amendment or by a state transition such as submission
        — is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/project_amend_with_stale_version_returns_412
        """
        from test_helpers import create_project
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_project(cycle["id"], vol["id"], title="Seed Library",
                              description="v1",
                              estimated_hours_per_volunteer=8.0)
        hdrs = make_volunteer_headers(vol["id"])
        resp = api.amend_project(
            proj["id"], {"expected_project_version": proj["version"],
                         "title": "Seed Library v2"}, hdrs)
        updated = validate_success(resp)
        assert updated["version"] == 2

        resp = api.amend_project(
            proj["id"], {"expected_project_version": proj["version"],
                         "title": "Seed Library v3"}, hdrs)
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
        cur = get_success_data(api.get_project(proj["id"], COORD))
        assert cur["title"] == "Seed Library v2"

    def test_specialist_patch_with_stale_version_returns_412(self, api):
        """PRD §2.8: "A `PATCH /specialists/{specialistId}` request, the
        capacity or availability update, must carry
        `expected_specialist_version`, and a mismatch with the specialist's
        current `version` is rejected with `ERR_STALE_SPECIALIST_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/specialist_patch_with_stale_version_returns_412
        """
        spec = create_specialist()
        resp = api.update_specialist(
            spec["id"], {"expected_specialist_version": spec["version"],
                         "max_concurrent_referrals": 5}, COORD)
        updated = validate_success(resp)
        assert updated["version"] == 2

        resp = api.update_specialist(
            spec["id"], {"expected_specialist_version": spec["version"],
                         "max_concurrent_referrals": 1}, COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_SPECIALIST_VERSION)
        cur = get_success_data(api.get_specialist(spec["id"], COORD))
        assert cur["max_concurrent_referrals"] == 5


class TestEnvelopeAndClock:
    def test_clock_default_and_set_roundtrip(self, api):
        """PRD §2.5: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z, and the server must not fall back to wall-clock
        time under any circumstance."
        PRD §2.5: "A `ProgramCoordinator`-only test-driving capability
        advances the logical clock to a supplied `to_iso8601` instant and
        reports the resulting `current_utc`."

        Design: Corner/endpoints/clock_default_and_set_roundtrip
        """
        resp = api.create_cycle(create_cycle_payload(), COORD)
        cycle = validate_success(resp, expected_status=201)
        # §2.5: created_at reads the logical clock (never wall clock);
        # compared at second precision per §2.7.
        assert_same_instant(cycle["created_at"], "2026-08-01T00:00:00Z")

        resp = api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, COORD)
        clock_data = validate_success(resp)
        assert clock_data["current_utc"] == "2026-08-15T00:00:00Z"

        resp = api.create_application(
            {"cycle_id": cycle["id"], "applicant_name": "Alice Arbor",
             "email": "alice@example.org", "county": "Harford",
             "prior_gardening_years": 7}, COORD)
        app = validate_success(resp, expected_status=201)
        assert_same_instant(app["created_at"], "2026-08-15T00:00:00Z")

    def test_volunteers_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry four fields in the
        `meta` object of the envelope — `limit`, `offset`, `total_count`, and
        `has_more` — so clients can page deterministically through a full
        result set."

        Design: Corner/entities/volunteers_list_pagination_envelope
        """
        cycle = create_and_open_cycle()
        create_accepted_volunteer(cycle["id"], applicant_name="Alice Arbor",
                                  email="alice@example.org")
        create_accepted_volunteer(cycle["id"], applicant_name="Bob Birch",
                                  email="bob@example.org", county="Cecil",
                                  prior_gardening_years=3)
        resp = api.list_volunteers(COORD, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_specialist_create_applies_defaults(self, api):
        """PRD §3.5: "The specialist registry is coordinator-maintained:
        registering a `Specialist` takes a `name`, a `specialty` from the
        same five-value enumeration as inquiry categories, a
        `max_concurrent_referrals` quota of at least one, and an optional
        `accepting_referrals` flag that defaults to true. Counters
        (`open_referral_count`, `answered_count`, `late_referral_count`,
        `returned_count`) start at zero and both performance scores at
        100.0."

        Design: Corner/entities/specialist_create_applies_defaults
        """
        resp = api.create_specialist(
            {"name": "Dr. Pest", "specialty": "PEST",
             "max_concurrent_referrals": 3}, COORD)
        spec = validate_success(resp, expected_status=201)
        assert spec["accepting_referrals"] is True
        assert spec["open_referral_count"] == 0
        assert spec["answered_count"] == 0
        assert spec["late_referral_count"] == 0
        assert spec["returned_count"] == 0
        assert spec["rolling_score"] == pytest.approx(100.0, abs=0.01)
        assert spec["lifetime_score"] == pytest.approx(100.0, abs=0.01)


class TestEnrollmentPostureConflict:
    def test_cycle_posture_beats_duplicate_enrollment_error(self, api):
        """PRD §2.9: "The sequence is: ... (7) parent cycle posture — the
        three errors of §2.6; (8) target-resource state ...; (9) segregation
        of duties — `ERR_SEGREGATION_OF_DUTIES`; (10) uniqueness, capacity,
        and overlap conflicts — the duplicate, fullness, conflict, and limit
        error families;"
        PRD §2.6: "First, credit-entry writes (creation, approval, rejection,
        revocation), shift creation, community-project creation, and training
        enrollment creation, progress, and completion all require the target
        cycle to be `OPEN`; against any other posture they fail with
        `ERR_CYCLE_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/cycle_posture_beats_duplicate_enrollment
        """
        cycle = create_and_open_cycle()
        vol = create_accepted_volunteer(cycle["id"])
        get_success_data(api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD))
        move_cycle_to_recertification(cycle["id"])
        # The volunteer already holds an ENROLLED enrollment (duplicate would
        # fail at tier 10), but the cycle posture (tier 7) runs first.
        resp = api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_cycle_posture_beats_duplicate_enrollment_no_phantom_seat(
            self, api):
        """PRD §3.2: "A new enrollment starts `ENROLLED` with
        `modules_completed` at 0, `quiz_average` at 0.0, and `completed_at`
        unset, and its creation increments the cycle's `enrolled_count` by
        one."
        PRD §2.6: "First, credit-entry writes (creation, approval, rejection,
        revocation), shift creation, community-project creation, and training
        enrollment creation, progress, and completion all require the target
        cycle to be `OPEN`; against any other posture they fail with
        `ERR_CYCLE_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/cycle_posture_beats_duplicate_enrollment
        """
        cycle = create_and_open_cycle()
        vol = create_accepted_volunteer(cycle["id"])
        get_success_data(api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD))
        move_cycle_to_recertification(cycle["id"])
        api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD)
        cyc_after = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cyc_after["enrolled_count"] == 1
