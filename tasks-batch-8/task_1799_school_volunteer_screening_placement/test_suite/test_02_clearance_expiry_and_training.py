"""Clearance validity windows, the re-screening cycle, and training gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_clock_instant,
    adjudicate_check,
    create_active_volunteer,
    create_core_module_never_expires,
    create_lincoln_campus,
    create_open_opportunity,
    create_orient_module,
    create_volunteer_applied,
    get_placement,
    get_success_data,
    get_volunteer,
    initiate_background_check,
    record_training,
    request_placement,
    set_clock,
    validate_error,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestClearanceValidityWindow:
    def test_enhanced_clearance_expires_in_365_days(self, api):
        """PRD: "A cleared check's `expires_at` is its `decided_at` plus the
        validity window for its `level`, measured as whole-day durations of
        twenty-four hours: seven hundred thirty days for a `BASIC` check — two
        years — and three hundred sixty-five days for an `ENHANCED` check — one
        year."
        PRD: "The volunteer-level `clearance_expires_at` is selected from the
        volunteer's checks that are in `CLEARED` or `CLEARED_WITH_FLAGS` with
        an adequate level: among that set the check with the latest
        `decided_at` wins, ties are broken in favor of the later-created check,
        and the winning check's `expires_at` becomes the volunteer's value."
        PRD: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Corner/calculations/enhanced_clearance_expires_in_365_days
        """
        module = create_core_module_never_expires()
        volunteer = create_volunteer_applied("Expiry Eve", "eve@x.com",
                                             "UNSUPERVISED")
        check = initiate_background_check(volunteer, level="ENHANCED")
        record_training(volunteer["id"], module["id"])

        decided = validate_success(
            api.adjudicate_background_check(check["id"],
                                            {"findings": "NONE"}, DC), 200)
        assert decided["status"] == "CLEARED"
        # Decided at the logical clock default; ENHANCED validity is 365 days.
        assert_clock_instant(decided["decided_at"], "2026-08-01T00:00:00")
        assert_clock_instant(decided["expires_at"], "2027-08-01T00:00:00")

        after = get_volunteer(volunteer["id"])
        assert after["status"] == "ACTIVE"
        assert after["required_check_level"] == "ENHANCED"
        assert_clock_instant(after["clearance_expires_at"],
                             "2027-08-01T00:00:00")


class TestRescreenCycle:
    def _active_unsupervised_with_core(self, name, email):
        module = create_core_module_never_expires()
        volunteer = create_volunteer_applied(name, email, "UNSUPERVISED")
        check = initiate_background_check(volunteer, level="ENHANCED")
        record_training(volunteer["id"], module["id"])
        adjudicated = adjudicate_check(check["id"], "NONE")
        return get_volunteer(volunteer["id"]), adjudicated, module

    def test_active_to_rescreen_to_active_cycle(self, api):
        """PRD: "First, every background check in `CLEARED` or
        `CLEARED_WITH_FLAGS` whose `expires_at` is at or before the new current
        time transitions to `EXPIRED`. Second, each affected volunteer's
        `clearance_expires_at` is recomputed, and every `ACTIVE` volunteer left
        without a valid clearance — meaning the recomputed value is null or is
        at or before the new current time — is demoted from `ACTIVE` to
        `RESCREEN_REQUIRED`, with each affected volunteer's `version`
        incremented by one."
        PRD: "The district office initiates a fresh check for the
        `RESCREEN_REQUIRED` volunteer — permitted from that status — and
        adjudication then follows the §3.2 branches: an adequate cleared
        outcome returns the volunteer to `ACTIVE` when training compliance is
        complete, or to `CLEARANCE_GRANTED` when retraining is still owed"

        Design: Difficulty/non_linear_state_machine/volunteer_active_rescreen_active_cycle
        """
        volunteer, check1, _ = self._active_unsupervised_with_core(
            "Cyclic Cy", "cy@x.com")
        assert volunteer["status"] == "ACTIVE"

        # Advance one second past the ENHANCED expiry instant.
        sweep = set_clock("2027-08-01T00:00:01Z")
        assert sweep["expired_check_count"] == 1
        assert sweep["volunteers_rescreened_count"] == 1

        expired = get_success_data(api.get_background_check(check1["id"], DC))
        assert expired["status"] == "EXPIRED"
        demoted = get_volunteer(volunteer["id"])
        assert demoted["status"] == "RESCREEN_REQUIRED"

        # Re-screen: a fresh ENHANCED check adjudicated NONE reactivates.
        check2 = initiate_background_check(demoted, level="ENHANCED")
        decided2 = adjudicate_check(check2["id"], "NONE")
        assert decided2["status"] == "CLEARED"
        # decided at 2027-08-01T00:00:01Z; 365 whole days later.
        assert_clock_instant(decided2["expires_at"], "2028-07-31T00:00:01")

        restored = get_volunteer(volunteer["id"])
        assert restored["status"] == "ACTIVE"

    def test_clock_sweep_expires_check_and_demotes_volunteer(self, api):
        """PRD: "The capability responds with the new `current_utc` plus three
        sweep counters: `expired_check_count`, `volunteers_rescreened_count`,
        and `opportunities_completed_count`."
        PRD: "Second, each affected volunteer's `clearance_expires_at` is
        recomputed, and every `ACTIVE` volunteer left without a valid clearance
        — meaning the recomputed value is null or is at or before the new
        current time — is demoted from `ACTIVE` to `RESCREEN_REQUIRED`, with
        each affected volunteer's `version` incremented by one."

        Design: Difficulty/non_linear_state_machine/volunteer_active_rescreen_active_cycle
        """
        volunteer, check1, _ = self._active_unsupervised_with_core(
            "Sweep Sam", "sweep.sam@x.com")
        version_before = volunteer["version"]

        sweep = set_clock("2027-08-01T00:00:01Z")
        assert sweep["expired_check_count"] == 1
        assert sweep["volunteers_rescreened_count"] == 1

        expired = get_success_data(api.get_background_check(check1["id"], DC))
        assert expired["status"] == "EXPIRED"

        demoted = get_volunteer(volunteer["id"])
        assert demoted["status"] == "RESCREEN_REQUIRED"
        assert demoted["clearance_expires_at"] is None
        assert demoted["version"] == version_before + 1


class TestTrainingCompliance:
    def test_training_completion_auto_activates(self, api):
        """PRD: "A volunteer in `UNDER_SCREENING` with an adequate cleared
        outcome moves to `ACTIVE` when training compliance is complete at that
        moment, or to `CLEARANCE_GRANTED` when it is not"
        PRD: "When a newly recorded completion makes a `CLEARANCE_GRANTED`
        volunteer's training compliance complete, the volunteer transitions
        automatically from `CLEARANCE_GRANTED` to `ACTIVE`, and the volunteer's
        `version` is incremented by one."

        Design: Corner/state_machines/training_completion_auto_activates_clearance_granted
        """
        module = create_orient_module()
        volunteer = create_volunteer_applied("Parked Pat", "pat@x.com",
                                             "SUPERVISED")
        check = initiate_background_check(volunteer, level="BASIC")

        # Adjudicated before any training record: clearance granted, training owed.
        adjudicate_check(check["id"], "NONE")
        parked = get_volunteer(volunteer["id"])
        assert parked["status"] == "CLEARANCE_GRANTED"

        record_training(volunteer["id"], module["id"])
        activated = get_volunteer(volunteer["id"])
        assert activated["status"] == "ACTIVE"

    def test_expired_training_blocks_confirm(self, api):
        """PRD: "The volunteer is compliant exactly when every module in that
        required set has at least one completion record that is currently valid
        — meaning the module never expires, or the record's `expires_at` is
        strictly after the current time. This verdict is consulted at three
        moments: during adjudication branch selection, whenever a new
        completion record is created, and at placement confirmation."
        PRD: "then the three screening gates run in order — clearance level
        adequate for the opportunity's `required_contact_type`
        (`ERR_CLEARANCE_LEVEL_INSUFFICIENT`), no restriction flag blocking the
        opportunity's `restricted_category` (`ERR_RESTRICTED_ROLE`), and
        training compliance complete at confirm time
        (`ERR_TRAINING_INCOMPLETE`)"

        Design: Corner/validations/expired_training_blocks_confirm
        """
        module = create_orient_module(validity_days=365)
        volunteer = create_volunteer_applied("Stale Trainee", "st@x.com",
                                             "UNSUPERVISED")
        check = initiate_background_check(volunteer, level="ENHANCED")
        # Completed 2026-07-01 with 365-day validity: expires 2027-07-01.
        record_training(volunteer["id"], module["id"], "2026-07-01T00:00:00Z")
        adjudicate_check(check["id"], "NONE")
        assert get_volunteer(volunteer["id"])["status"] == "ACTIVE"

        # Training lapsed on 2027-07-01; the ENHANCED clearance runs to
        # 2027-08-01, so the volunteer remains ACTIVE at 2027-07-15.
        set_clock("2027-07-15T00:00:00Z")
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Mentor Day",
            required_contact_type="UNSUPERVISED", capacity=2,
            starts_at="2027-08-10T14:00:00Z", ends_at="2027-08-10T17:00:00Z")
        placement = request_placement(opp["id"], volunteer["id"])

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_TRAINING_INCOMPLETE)

        assert get_placement(placement["id"])["status"] == "REQUESTED"
        # Expired training gates; it does not demote the volunteer.
        assert get_volunteer(volunteer["id"])["status"] == "ACTIVE"

    def test_insufficient_clearance_level_rejected(self, api):
        """PRD: "A held check level is **adequate** for a required level
        whenever its rank is at least the rank of the required level — so an
        `ENHANCED` check satisfies either requirement, while a `BASIC` check
        satisfies only a `BASIC` requirement."
        PRD: "The same rank comparison decides opportunity gating: the
        volunteer's latest cleared check level must be adequate for the level
        implied by the opportunity's `required_contact_type`."
        PRD: "Placement confirmation and the opportunity matching selector
        apply three gates in this exact order: first clearance-level adequacy
        for the opportunity's required contact intensity, rejected as
        `ERR_CLEARANCE_LEVEL_INSUFFICIENT`"

        Design: Corner/endpoints/insufficient_clearance_level_rejected
        """
        recruited = create_active_volunteer("Basic Barb", "barb@x.com",
                                            "SUPERVISED", level="BASIC")
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Solo Mentor",
            required_contact_type="UNSUPERVISED", capacity=2)
        placement = request_placement(opp["id"], recruited["volunteer"]["id"])

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_CLEARANCE_LEVEL_INSUFFICIENT)
        assert get_placement(placement["id"])["status"] == "REQUESTED"
