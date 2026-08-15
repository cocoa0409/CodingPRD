"""Volunteer intake, background screening initiation, and adjudication."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_background_check,
    assert_clock_instant,
    assert_volunteer,
    adjudicate_check,
    create_active_volunteer,
    create_background_check_payload,
    create_lincoln_campus,
    create_open_opportunity,
    create_orient_module,
    create_volunteer_applied,
    create_volunteer_payload,
    get_success_data,
    get_volunteer,
    initiate_background_check,
    record_training,
    request_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestVolunteerCreation:
    def test_volunteer_creation_defaults_and_system_stamps(self, api):
        """PRD: "A new application starts in `APPLIED` status with an empty
        `restriction_flags` array, zeroed service-hour totals and
        `recognition_points`, a `recognition_tier` of `NONE`, null
        `clearance_expires_at`, null `prior_status`, and null
        `suspension_incident_id`."
        PRD: "A volunteer's required level, recorded at intake as
        `required_check_level`, is `BASIC` for a `SUPERVISED` contact type and
        `ENHANCED` for an `UNSUPERVISED` contact type."
        PRD: "Every primary resource is assigned an `id` at creation: a
        server-minted UUID with no type prefix."
        PRD: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z; before any set call the clock continues to read
        this default and never falls back to wall-clock time."

        Design: Corner/entities/volunteer_creation_defaults_and_system_stamps
        """
        resp = api.create_volunteer(
            create_volunteer_payload(full_name="Default Dana",
                                     email="dana@x.com",
                                     contact_type="SUPERVISED"), DC)
        volunteer = validate_success(resp, 201)
        assert_volunteer(volunteer)
        assert volunteer["status"] == "APPLIED"
        assert volunteer["required_check_level"] == "BASIC"
        assert volunteer["total_verified_hours"] == pytest.approx(0.0)
        assert volunteer["total_provisional_hours"] == pytest.approx(0.0)
        assert volunteer["recognition_points"] == pytest.approx(0.0)
        assert volunteer["recognition_tier"] == "NONE"
        assert volunteer["restriction_flags"] == []
        assert volunteer["clearance_expires_at"] is None
        assert volunteer["prior_status"] is None
        assert volunteer["suspension_incident_id"] is None
        # created_at is stamped from the logical clock, which reads the startup
        # default before any set call.
        assert_clock_instant(volunteer["created_at"], "2026-08-01T00:00:00")

        fetched = validate_success(api.get_volunteer(volunteer["id"], DC), 200)
        assert_volunteer(fetched)
        assert fetched["status"] == "APPLIED"

    def test_volunteer_create_schema_violations_rejected(self, api):
        """PRD: "Required fields are present, enum values fall inside their
        declared sets, and numeric and date shapes hold — `hours` positive and
        carrying at most two decimal places, `capacity` at least one,
        `starts_at` strictly before `ends_at`, well-formed ISO 8601 datetimes.
        Failures yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/volunteer_create_schema_violations_rejected
        """
        missing_email = api.create_volunteer(
            {"full_name": "No Email", "contact_type": "SUPERVISED"}, DC)
        validate_error(missing_email, ApiErrorId.ERR_INVALID_REQUEST)

        bad_enum = api.create_volunteer(
            {"full_name": "Bad Enum", "email": "enum@x.com",
             "contact_type": "ROAMING"}, DC)
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_volunteers(DC))
        assert meta["total_count"] == 0, "Rejected creates must leave no partial writes"

    def test_uniqueness_violations_rejected(self, api):
        """PRD: "The email must be unique across all volunteers in any status;
        a taken email is rejected with `ERR_EMAIL_TAKEN`."
        PRD: "A `DistrictCoordinator` creates each Campus with a display `name`,
        a district-wide unique `campus_code` — rejected as a duplicate with
        `ERR_CAMPUS_CODE_TAKEN` and immutable once created"
        PRD: "A `DistrictCoordinator` creates each TrainingModule with a unique
        `module_code` (a duplicate is rejected with `ERR_MODULE_CODE_TAKEN`)"

        Design: Corner/entities/uniqueness_violations_rejected
        """
        validate_success(api.create_volunteer(
            create_volunteer_payload(full_name="First", email="dup@x.com",
                                     contact_type="SUPERVISED"), DC), 201)
        validate_success(api.create_campus(
            {"name": "Lincoln Elementary", "campus_code": "LNC",
             "badge_prefix": "LNC"}, DC), 201)
        validate_success(api.create_training_module(
            {"module_code": "ORIENT", "title": "Volunteer Orientation",
             "required_contact_types": ["SUPERVISED"]}, DC), 201)

        dup_volunteer = api.create_volunteer(
            create_volunteer_payload(full_name="Second", email="dup@x.com",
                                     contact_type="UNSUPERVISED"), DC)
        validate_error(dup_volunteer, ApiErrorId.ERR_EMAIL_TAKEN)

        dup_campus = api.create_campus(
            {"name": "Lincoln North", "campus_code": "LNC",
             "badge_prefix": "LCN"}, DC)
        validate_error(dup_campus, ApiErrorId.ERR_CAMPUS_CODE_TAKEN)

        dup_module = api.create_training_module(
            {"module_code": "ORIENT", "title": "Duplicate",
             "required_contact_types": ["UNSUPERVISED"]}, DC)
        validate_error(dup_module, ApiErrorId.ERR_MODULE_CODE_TAKEN)

    def test_entity_not_found_returns_404(self, api):
        """PRD: "Every identifier in the URL path resolves to an existing
        entity, validated strictly left to right, and then every foreign-key
        identifier in the request body resolves, validated in payload field
        order; the first unresolvable identifier yields `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_not_found_returns_404
        """
        volunteer = create_volunteer_applied("Real Ruth", "ruth@x.com",
                                             "SUPERVISED")

        missing_get = api.get_volunteer(NON_EXISTENT_UUID, DC)
        validate_error(missing_get, ApiErrorId.ERR_NOT_FOUND)

        # An unresolvable body FK is an existence failure (stage 3), which the
        # ordered pipeline evaluates before the OCC version check (stage 9).
        missing_fk = api.create_background_check(
            create_background_check_payload(NON_EXISTENT_UUID,
                                            volunteer["version"],
                                            level="BASIC"), DC)
        validate_error(missing_fk, ApiErrorId.ERR_NOT_FOUND)


class TestAdjudicationFork:
    def _two_pending_volunteers(self):
        module = create_orient_module()
        gail = create_volunteer_applied("Good Gail", "gail@x.com", "SUPERVISED")
        gail_check = initiate_background_check(gail, level="BASIC")
        record_training(gail["id"], module["id"])
        bob = create_volunteer_applied("Bad Bob", "bob@x.com", "SUPERVISED")
        bob_check = initiate_background_check(bob, level="BASIC")
        record_training(bob["id"], module["id"])
        return gail, gail_check, bob, bob_check

    def test_adjudication_fork_cleared_vs_denied(self, api):
        """PRD: "A finding of `NONE` decides the check as `CLEARED` with an
        empty flag set."
        PRD: "A `DISQUALIFYING` finding is the severe path: the volunteer
        transitions to the terminal `DENIED` status, and the system runs the
        full removal cascade described in §3.7."
        PRD: "Check initiation is permitted only while the volunteer is in
        `APPLIED`, `ACTIVE`, or `RESCREEN_REQUIRED` status; any other status is
        rejected with `ERR_VOLUNTEER_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/background_check_branching_outcomes
        """
        gail, gail_check, bob, bob_check = self._two_pending_volunteers()

        cleared = validate_success(
            api.adjudicate_background_check(gail_check["id"],
                                            {"findings": "NONE"}, DC), 200)
        assert cleared["status"] == "CLEARED"
        assert_clock_instant(cleared["expires_at"], "2028-07-31T00:00:00")

        denied = validate_success(
            api.adjudicate_background_check(bob_check["id"],
                                            {"findings": "DISQUALIFYING"}, DC),
            200)
        assert denied["status"] == "DENIED"
        assert denied["expires_at"] is None

        gail_after = get_volunteer(gail["id"])
        assert gail_after["status"] == "ACTIVE"
        bob_after = get_volunteer(bob["id"])
        assert bob_after["status"] == "DENIED"

        # DENIED is terminal: a fresh screening attempt is a state rejection.
        rescreen = api.create_background_check(
            create_background_check_payload(bob["id"], bob_after["version"],
                                            level="BASIC"), DC)
        validate_error(rescreen, ApiErrorId.ERR_VOLUNTEER_INVALID_STATE)

    def test_cleared_branch_expiry_and_denied_branch_terminal(self, api):
        """PRD: "A cleared check's `expires_at` is its `decided_at` plus the
        validity window for its `level`, measured as whole-day durations of
        twenty-four hours: seven hundred thirty days for a `BASIC` check — two
        years — and three hundred sixty-five days for an `ENHANCED` check — one
        year. The field stays null while the check is `PENDING`, and stays null
        permanently for a `DENIED` check."
        PRD: "The adjudication stamps `decided_at` from the logical clock"

        Design: Difficulty/non_linear_state_machine/background_check_branching_outcomes
        """
        gail, gail_check, bob, bob_check = self._two_pending_volunteers()

        cleared = validate_success(
            api.adjudicate_background_check(gail_check["id"],
                                            {"findings": "NONE"}, DC), 200)
        assert_background_check(cleared)
        assert cleared["findings"] == "NONE"
        assert_clock_instant(cleared["decided_at"], "2026-08-01T00:00:00")
        # BASIC validity is 730 days from the clock-default decision instant.
        assert_clock_instant(cleared["expires_at"], "2028-07-31T00:00:00")
        assert get_volunteer(gail["id"])["status"] == "ACTIVE"

        denied = validate_success(
            api.adjudicate_background_check(bob_check["id"],
                                            {"findings": "DISQUALIFYING"}, DC),
            200)
        assert_background_check(denied)
        assert denied["findings"] == "DISQUALIFYING"
        assert_clock_instant(denied["decided_at"], "2026-08-01T00:00:00")
        assert denied["expires_at"] is None
        assert get_volunteer(bob["id"])["status"] == "DENIED"


class TestDecisionMatrixMinorFlags:
    def _flagged_unsupervised_setup(self):
        module = create_orient_module()
        volunteer = create_volunteer_applied("Mentor Mary", "mary@x.com",
                                             "UNSUPERVISED")
        check = initiate_background_check(volunteer, level="ENHANCED")
        record_training(volunteer["id"], module["id"])
        return volunteer, check

    def test_minor_findings_unsupervised_flags_and_restricted_role(self, api):
        """PRD: "A finding of `MINOR` decides the check as `CLEARED_WITH_FLAGS`
        and assigns the flag `NO_TRANSPORT`, plus the additional flag
        `NO_ONE_ON_ONE` when the volunteer's `contact_type` is `UNSUPERVISED`."
        PRD: "then the three screening gates run in order — clearance level
        adequate for the opportunity's `required_contact_type`
        (`ERR_CLEARANCE_LEVEL_INSUFFICIENT`), no restriction flag blocking the
        opportunity's `restricted_category` (`ERR_RESTRICTED_ROLE`), and
        training compliance complete at confirm time
        (`ERR_TRAINING_INCOMPLETE`)"

        Design: Difficulty/combinatorial_formula/screening_decision_matrix_minor_unsupervised_flags
        """
        volunteer, check = self._flagged_unsupervised_setup()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Reading Mentor",
            required_contact_type="UNSUPERVISED",
            restricted_category="ONE_ON_ONE", capacity=2)

        decided = validate_success(
            api.adjudicate_background_check(check["id"],
                                            {"findings": "MINOR"}, DC), 200)
        assert decided["status"] == "CLEARED_WITH_FLAGS"

        after = get_volunteer(volunteer["id"])
        assert after["status"] == "ACTIVE"
        assert after["restriction_flags"] == ["NO_ONE_ON_ONE", "NO_TRANSPORT"]

        placement = request_placement(opp["id"], volunteer["id"])
        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_RESTRICTED_ROLE)

    def test_minor_findings_unsupervised_check_and_volunteer_state(self, api):
        """PRD: "Whatever flags the matrix yields are stored on the volunteer's
        `restriction_flags` as a sorted array, a subset of `NO_TRANSPORT` and
        `NO_ONE_ON_ONE`, with an empty array when the findings are `NONE`."
        PRD: "The volunteer's own branch is then decided by adequacy crossed
        with training compliance: an adequate cleared outcome with training
        complete activates the volunteer"

        Design: Difficulty/combinatorial_formula/screening_decision_matrix_minor_unsupervised_flags
        """
        volunteer, check = self._flagged_unsupervised_setup()
        decided = validate_success(
            api.adjudicate_background_check(check["id"],
                                            {"findings": "MINOR"}, DC), 200)
        assert decided["status"] == "CLEARED_WITH_FLAGS"
        assert decided["findings"] == "MINOR"

        after = get_volunteer(volunteer["id"])
        # Adequate ENHANCED outcome + complete training -> ACTIVE; the sorted
        # flag array carries both restriction flags.
        assert after["status"] == "ACTIVE"
        assert after["restriction_flags"] == ["NO_ONE_ON_ONE", "NO_TRANSPORT"]
        assert after["restriction_flags"] == sorted(after["restriction_flags"])


class TestCheckInitiationRules:
    def test_adjudicate_non_pending_check_rejected(self, api):
        """PRD: "Adjudication by a `DistrictCoordinator` records the `findings`
        — `NONE`, `MINOR`, or `DISQUALIFYING` — on a check that must still be
        `PENDING`; adjudicating an already-decided check is rejected with
        `ERR_CHECK_INVALID_STATE`."

        Design: Corner/state_machines/adjudicate_non_pending_check_rejected
        """
        recruited = create_active_volunteer("Twice Tom", "tom@x.com",
                                            "SUPERVISED")
        check_id = recruited["check"]["id"]
        assert recruited["check"]["status"] == "CLEARED"

        second = api.adjudicate_background_check(check_id,
                                                 {"findings": "NONE"}, DC)
        validate_error(second, ApiErrorId.ERR_CHECK_INVALID_STATE)

        still = get_success_data(api.get_background_check(check_id, DC))
        assert still["status"] == "CLEARED"

    def test_duplicate_pending_check_rejected(self, api):
        """PRD: "A volunteer may have at most one unresolved check at a time:
        initiating while another check is still `PENDING` is rejected with
        `ERR_CHECK_ALREADY_PENDING`."

        Design: Corner/endpoints/duplicate_pending_check_rejected
        """
        # The one-pending-check rule must be exercised from a status the
        # initiation state gate (pipeline stage 4) admits — APPLIED, ACTIVE,
        # or RESCREEN_REQUIRED — or the stage-4 ERR_VOLUNTEER_INVALID_STATE
        # pre-empts the stage-8 uniqueness rejection. A first check from
        # APPLIED leaves the volunteer UNDER_SCREENING, so the scenario runs
        # as a proactive re-screen of an ACTIVE volunteer (PRD §3.3).
        recruited = create_active_volunteer("Pending Pete", "pete@x.com",
                                            "SUPERVISED")
        volunteer = recruited["volunteer"]
        first = initiate_background_check(volunteer, level="BASIC")
        assert first["status"] == "PENDING"

        current = get_volunteer(volunteer["id"])
        # The uniqueness constraint fires even with a current OCC version.
        duplicate = api.create_background_check(
            create_background_check_payload(volunteer["id"],
                                            current["version"],
                                            level="ENHANCED"), DC)
        validate_error(duplicate, ApiErrorId.ERR_CHECK_ALREADY_PENDING)

        data, meta = validate_paginated(api.list_background_checks(
            DC, params={"volunteer_id": volunteer["id"]}))
        # The adjudicated first check plus the pending re-screen; the rejected
        # attempt must not create a third.
        assert meta["total_count"] == 2

    def test_occ_background_check_stale_version_rejected(self, api):
        """PRD: "The request must carry `expected_volunteer_version` matching
        the volunteer's current `version`. If another writer has advanced the
        volunteer's version since the client last read it — for example, a
        check was created that supersedes the client's view of the screening
        posture — the create is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from initiating screening against a volunteer
        record it has not observed."
        PRD: "in all cases the initiation increments the volunteer's `version`
        by one"

        Design: Corner/cross_cutting_complexity_layers/occ_background_check_stale_version_rejected
        """
        module = create_orient_module()
        volunteer = create_volunteer_applied("Version Vic", "vic@x.com",
                                             "SUPERVISED")
        stale_version = volunteer["version"]
        check = initiate_background_check(volunteer, level="BASIC")
        record_training(volunteer["id"], module["id"])
        adjudicate_check(check["id"], "NONE")

        current = get_volunteer(volunteer["id"])
        assert current["status"] == "ACTIVE"

        stale = api.create_background_check(
            create_background_check_payload(volunteer["id"], stale_version,
                                            level="ENHANCED"), DC)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.create_background_check(
            create_background_check_payload(volunteer["id"],
                                            current["version"],
                                            level="ENHANCED"), DC), 201)
        assert fresh["status"] == "PENDING"

        after = get_volunteer(volunteer["id"])
        assert after["version"] == current["version"] + 1, (
            "Check initiation increments the volunteer's version by one")
