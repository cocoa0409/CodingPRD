"""Enrollment capacity, waitlist, OCC on the group, and validation ordering
(PRD §2.8, §2.10, §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    confirm_enrollment,
    get_success_data,
    make_active_group,
    make_active_participant,
    make_confirmed_enrollment,
    make_enrollment,
    make_incident,
    make_participant,
    make_program,
    make_session,
    make_scheduled_session,
    reset_clock,
    schedule_session,
    setup_certified_facilitator,
    setup_in_progress_session,
    validate_error,
    validate_success,
)


class TestSeatAndAgreementParallelDimensions:
    def test_waitlist_orders_by_reserved_at_and_renumbers_on_promotion(self, api):
        """PRD §3.4: "among the group's `WAITLISTED` enrollments, entries sort
        by `reserved_at` ascending with `created_at` ascending as the tiebreak;
        the first entry is promoted back to `RESERVED`, its `waitlist_position`
        is cleared, the group's `active_enrollment_count` is incremented
        because a reserved seat again occupies capacity, and every remaining
        waitlisted entry is renumbered to a fresh 1-based `waitlist_position`
        in that same order."

        Design: Difficulty/non_linear_state_machine/enrollment_seat_and_agreement_parallel_dimensions
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=1)
        pa, _ = make_active_participant(full_name="A")
        pb, _ = make_active_participant(full_name="B")
        pc, _ = make_active_participant(full_name="C")
        ea = make_confirmed_enrollment(program["id"], group["id"], pa["id"])
        eb = make_enrollment(program["id"], group["id"], pb["id"])
        ec = make_enrollment(program["id"], group["id"], pc["id"])
        assert eb["seat_status"] == "WAITLISTED" and eb["waitlist_position"] == 1
        assert ec["seat_status"] == "WAITLISTED" and ec["waitlist_position"] == 2

        get_success_data(api.release_enrollment(program["id"], group["id"], ea["id"], ADMIN))

        eb_after = validate_success(
            api.get_enrollment(program["id"], group["id"], eb["id"], ADMIN))
        assert eb_after["seat_status"] == "RESERVED"
        assert eb_after.get("waitlist_position") is None
        ec_after = validate_success(
            api.get_enrollment(program["id"], group["id"], ec["id"], ADMIN))
        assert ec_after["seat_status"] == "WAITLISTED"
        assert ec_after["waitlist_position"] == 1, (
            "remaining waitlisted entries must be renumbered to a fresh 1-based position")


class TestCapacityBoundary:
    def test_confirm_at_exact_capacity_lands_on_waitlist(self, api):
        """PRD §3.4: "Capacity gates confirmation: confirming while
        `active_enrollment_count` has reached `base_capacity` is rejected with
        `ERR_GROUP_AT_CAPACITY` (HTTP 409), and when a confirmation attempt
        finds the group full the system instead moves the seat from `RESERVED`
        to `WAITLISTED`, assigning a `waitlist_position`."

        Design: Difficulty/boundary_precision_check/enrollment_confirm_at_exact_capacity_goes_to_waitlist_not_reject
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=2)
        participants = [make_active_participant(full_name=n)[0] for n in ("A", "B", "C")]
        enrollments = [
            make_enrollment(program["id"], group["id"], p["id"]) for p in participants]
        confirm_enrollment(program["id"], group["id"], enrollments[0]["id"])
        confirm_enrollment(program["id"], group["id"], enrollments[1]["id"])

        group_mid = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert group_mid["active_enrollment_count"] == 2, "boundary: count == base_capacity"

        # C's confirmation attempt at exactly full capacity: seat lands on the
        # waitlist rather than reaching CONFIRMED.
        api.confirm_enrollment(
            program["id"], group["id"], enrollments[2]["id"],
            {"expected_group_version": group_mid["version"]}, ADMIN)
        ec_after = validate_success(
            api.get_enrollment(program["id"], group["id"], enrollments[2]["id"], ADMIN))
        assert ec_after["seat_status"] == "WAITLISTED"
        assert ec_after["waitlist_position"] == 1
        group_after = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert group_after["active_enrollment_count"] == 2

    def test_confirm_one_below_capacity_succeeds(self, api):
        """PRD §3.4: "Confirmation moves a seat from `RESERVED` to `CONFIRMED`."
        PRD §3.4: "A successful confirmation sets `agreement_status` to
        `SIGNED`, stamps `confirmed_at`, increments the group's
        `active_enrollment_count`, and increments the group's `version` by 1 —
        which is exactly what makes a concurrent confirmer's stored
        `expected_group_version` go stale."

        Design: Difficulty/boundary_precision_check/enrollment_confirm_at_exact_capacity_goes_to_waitlist_not_reject
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=2)
        pa, _ = make_active_participant(full_name="A")
        pb, _ = make_active_participant(full_name="B")
        make_confirmed_enrollment(program["id"], group["id"], pa["id"])
        eb = make_enrollment(program["id"], group["id"], pb["id"])

        # count is 1 < capacity 2: the confirmation must succeed.
        confirmed = confirm_enrollment(program["id"], group["id"], eb["id"])
        assert confirmed["seat_status"] == "CONFIRMED"
        assert confirmed["agreement_status"] == "SIGNED"
        assert confirmed.get("confirmed_at") is not None


class TestEnrollmentOptimisticConcurrency:
    def test_confirm_with_stale_group_version_rejected(self, api):
        """PRD §2.8: "Confirming an enrollment requires the request to carry
        `expected_group_version`, the `version` of the parent PeerGroup as the
        client last observed it. If the group's current `version` does not
        match — for example because another writer has since confirmed or
        released an enrollment, which advances the group's `version` and may
        have promoted a waitlisted entry — the confirmation is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/enrollment_confirm_occ_stale_group_version
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=5)
        pa, _ = make_active_participant(full_name="A")
        pb, _ = make_active_participant(full_name="B")
        ea = make_enrollment(program["id"], group["id"], pa["id"])
        stale_version = validate_success(
            api.get_group(program["id"], group["id"], ADMIN))["version"]
        # Another writer confirms an enrollment, advancing the group's version.
        make_confirmed_enrollment(program["id"], group["id"], pb["id"])

        resp = api.confirm_enrollment(
            program["id"], group["id"], ea["id"],
            {"expected_group_version": stale_version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_confirm_immediately_reflects_in_group_counter(self, api):
        """PRD §3.4: "A successful confirmation sets `agreement_status` to
        `SIGNED`, stamps `confirmed_at`, increments the group's
        `active_enrollment_count`, and increments the group's `version` by 1"
        PRD §2.5: "Recomputes of derived fields on an entity (for example, a
        program's posture or a group's occupancy counter) are mutations and
        therefore refresh `updated_at` and increment `version` on that entity."

        Design: Corner/consistency_model/immediate_consistency_enrollment_confirm_reflects_in_group
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=5)
        pa, _ = make_active_participant(full_name="A")
        ea = make_enrollment(program["id"], group["id"], pa["id"])

        confirmed = confirm_enrollment(program["id"], group["id"], ea["id"])
        assert confirmed["seat_status"] == "CONFIRMED"
        group_after = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert group_after["active_enrollment_count"] == 1, (
            "immediately after confirm returns, the group read must show the "
            f"incremented counter, got {group_after['active_enrollment_count']}")


class TestStateVersusLockdownOrdering:
    def _lockdown_with_released_enrollment(self, api):
        """Enrollment released (invalid for confirm) + program in LOCKDOWN."""
        env = setup_in_progress_session()
        pa, _ = make_active_participant(full_name="A")
        enrollment = make_enrollment(env.program["id"], env.group["id"], pa["id"])
        get_success_data(api.release_enrollment(
            env.program["id"], env.group["id"], enrollment["id"], ADMIN))
        make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="CRITICAL", category="SAFETY")
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "LOCKDOWN"
        return env, enrollment

    def test_released_enrollment_confirm_during_lockdown_reports_state_error(self, api):
        """PRD §2.10: "the server evaluates them in one fixed order so the
        surfaced error is deterministic. The order is: ... sixth, that the
        target entity is in a state permitting the requested transition
        (`ERR_INVALID_STATE`); seventh, the program lockdown gate
        (`ERR_PROGRAM_LOCKED_DOWN`)"
        PRD §3.4: "Releasing a seat, by an admin or the participant themself,
        moves it from `RESERVED` or `CONFIRMED` to the terminal `RELEASED`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_confirm_on_cancelled_group_during_lockdown
        """
        env, enrollment = self._lockdown_with_released_enrollment(api)
        current = validate_success(api.get_enrollment(
            env.program["id"], env.group["id"], enrollment["id"], ADMIN))
        assert current["seat_status"] == "RELEASED"

        version = validate_success(
            api.get_group(env.program["id"], env.group["id"], ADMIN))["version"]
        resp = api.confirm_enrollment(
            env.program["id"], env.group["id"], enrollment["id"],
            {"expected_group_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reserved_enrollment_confirm_during_lockdown_reports_lockdown(self, api):
        """PRD §2.7: "Under `LOCKDOWN`, three write operations are blocked and
        rejected with `ERR_PROGRAM_LOCKED_DOWN` (HTTP 409): scheduling a
        session, confirming an enrollment, and checking in an attendance
        record."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_confirm_on_cancelled_group_during_lockdown
        """
        env = setup_in_progress_session()
        pa, _ = make_active_participant(full_name="A")
        enrollment = make_enrollment(env.program["id"], env.group["id"], pa["id"])
        make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="CRITICAL", category="SAFETY")

        version = validate_success(
            api.get_group(env.program["id"], env.group["id"], ADMIN))["version"]
        resp = api.confirm_enrollment(
            env.program["id"], env.group["id"], enrollment["id"],
            {"expected_group_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_LOCKED_DOWN)
