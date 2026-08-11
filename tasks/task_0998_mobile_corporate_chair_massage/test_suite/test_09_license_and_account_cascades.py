"""License suspend/reinstate cycle, license-revoke cascade, and corporate
account suspension cascade."""
from test_helpers import (
    assign_therapist,
    create_event_booking,
    create_region,
    create_therapist_license,
    create_wellness_program,
    get_chair,
    get_wellness_program,
    open_booking,
    setup_region_account_therapist,
    validate_success,
)


class TestLicenseSuspendReinstateCycle:
    def test_suspend_records_reason_and_reinstate_clears_it(self, api):
        """PRD §3.2: "Compliance review can suspend a license: the suspension
        request carries a free-text `reason`, which the server records in the
        license's `suspension_reason`."
        PRD §3.2: "Reinstatement (`SUSPENDED` → `ACTIVE`) requires the expiry
        date to be on or after the current logical date, and clears
        `suspension_reason`."

        Design: Difficulty/non_linear_state_machine/therapist_license_suspend_reinstate_cycle
        """
        ctx = setup_region_account_therapist()
        license_id = ctx["license"]["id"]
        suspended = validate_success(
            api.suspend_therapist_license(license_id, {"reason": "audit flag"}, ctx["admin"])
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "audit flag"
        reinstated = validate_success(api.reinstate_therapist_license(license_id, ctx["admin"]))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] == "", (
            f"Reinstatement clears suspension_reason, got {reinstated['suspension_reason']!r}"
        )

    def test_suspend_reinstate_cycle_repeats(self, api):
        """PRD §3.2: "Compliance review can suspend a license: the suspension
        request carries a free-text `reason`, which the server records in the
        license's `suspension_reason`."
        PRD §3.2: "Reinstatement (`SUSPENDED` → `ACTIVE`) requires the expiry
        date to be on or after the current logical date, and clears
        `suspension_reason`."

        Design: Difficulty/non_linear_state_machine/therapist_license_suspend_reinstate_cycle
        """
        ctx = setup_region_account_therapist()
        license_id = ctx["license"]["id"]
        validate_success(
            api.suspend_therapist_license(license_id, {"reason": "first"}, ctx["admin"])
        )
        validate_success(api.reinstate_therapist_license(license_id, ctx["admin"]))
        second = validate_success(
            api.suspend_therapist_license(license_id, {"reason": "second flag"}, ctx["admin"])
        )
        assert second["status"] == "SUSPENDED"
        assert second["suspension_reason"] == "second flag"


class TestLicenseRevokeCascade:
    def test_revoke_releases_assigned_chairs_in_license_region(self, api):
        """PRD §3.2: "Revocation (`ACTIVE` → `REVOKED`) is terminal and
        cascades: every `ASSIGNED` chair slot staffed by that therapist whose
        booking is delivered in the license's region and whose `event_date`
        falls on or after the current logical date transitions to `RELEASED`,
        and each such release decrements the therapist's booked-minutes tally
        for that date."

        Design: Difficulty/transitive_cascade/license_revoke_cascades_chair_release_and_booking_minutes
        """
        ctx = setup_region_account_therapist()
        booking = create_event_booking(ctx)
        booking, chairs = open_booking(ctx, booking["id"])
        assign_therapist(ctx, chairs[0]["id"], ctx["therapist"]["id"])
        revoked = validate_success(
            api.revoke_therapist_license(ctx["license"]["id"], ctx["admin"])
        )
        assert revoked["status"] == "REVOKED"
        chair_after = get_chair(ctx, chairs[0]["id"])
        assert chair_after["status"] == "RELEASED", (
            f"Revocation must cascade the ASSIGNED chair to RELEASED, "
            f"got {chair_after['status']}"
        )

    def test_revoke_leaves_chairs_in_other_regions_assigned(self, api):
        """PRD §3.2: "Revocation (`ACTIVE` → `REVOKED`) is terminal and
        cascades: every `ASSIGNED` chair slot staffed by that therapist whose
        booking is delivered in the license's region and whose `event_date`
        falls on or after the current logical date transitions to `RELEASED`,
        and each such release decrements the therapist's booked-minutes tally
        for that date."

        Design: Difficulty/transitive_cascade/license_revoke_cascades_chair_release_and_booking_minutes
        """
        ctx = setup_region_account_therapist()
        therapist_id = ctx["therapist"]["id"]
        # Same-region booking: chair assigned under the license being revoked.
        b_same = create_event_booking(ctx, event_date="2026-06-10")
        b_same, same_chairs = open_booking(ctx, b_same["id"])
        assign_therapist(ctx, same_chairs[0]["id"], therapist_id)
        # Other-region booking (different date to avoid double-booking): the
        # therapist holds a separate license there.
        other_region = create_region(code="R1", name="Region One")
        create_therapist_license(therapist_id, other_region["id"], license_number="LIC-R1")
        b_other = create_event_booking(
            ctx, region_id=other_region["id"], event_date="2026-06-11",
        )
        b_other, other_chairs = open_booking(ctx, b_other["id"])
        assign_therapist(ctx, other_chairs[0]["id"], therapist_id)
        # Revoke only the home-region license.
        validate_success(api.revoke_therapist_license(ctx["license"]["id"], ctx["admin"]))
        assert get_chair(ctx, same_chairs[0]["id"])["status"] == "RELEASED"
        assert get_chair(ctx, other_chairs[0]["id"])["status"] == "ASSIGNED", (
            "Chairs delivered outside the revoked license's region must be untouched"
        )


class TestCorporateSuspendCascade:
    def test_corporate_suspend_cascades_program_pause(self, api):
        """PRD §3.1: "Suspension moves an account from `ACTIVE` to
        `SUSPENDED` and, as a cascade, pauses every one of its wellness
        programs currently `ACTIVE` (§3.5)."
        PRD §3.5: "An `Organizer` of the account that owns the program may
        pause an `ACTIVE` program, which sets `next_occurrence_date` to null;
        resume a `PAUSED` program, which recomputes it; or terminate the
        program from either `ACTIVE` or `PAUSED`."

        Design: Difficulty/transitive_cascade/corporate_suspend_cascades_program_pause
        """
        ctx = setup_region_account_therapist()
        p1 = create_wellness_program(ctx, name="P1", cadence="WEEKLY")
        p2 = create_wellness_program(
            ctx, name="P2", cadence="MONTHLY", chair_count=2,
            slot_minutes=20, window_start_time="14:00",
            window_duration_minutes=120, recurrence_discount_pct=0.20,
        )
        assert p1["next_occurrence_date"] and p2["next_occurrence_date"]
        suspended = validate_success(
            api.suspend_corporate_account(ctx["account"]["id"], ctx["admin"])
        )
        assert suspended["status"] == "SUSPENDED"
        for program_id in (p1["id"], p2["id"]):
            program = get_wellness_program(ctx, program_id)
            assert program["status"] == "PAUSED", (
                f"Program {program_id} must cascade to PAUSED, got {program['status']}"
            )
            assert program["next_occurrence_date"] is None

    def test_reactivation_does_not_resume_paused_programs(self, api):
        """PRD §3.1: "Reactivation returns a `SUSPENDED` account to
        `ACTIVE`."
        PRD §3.1: "Suspension moves an account from `ACTIVE` to `SUSPENDED`
        and, as a cascade, pauses every one of its wellness programs currently
        `ACTIVE` (§3.5)."

        Design: Difficulty/transitive_cascade/corporate_suspend_cascades_program_pause
        """
        ctx = setup_region_account_therapist()
        program = create_wellness_program(ctx, name="P1", cadence="WEEKLY")
        validate_success(api.suspend_corporate_account(ctx["account"]["id"], ctx["admin"]))
        reactivated = validate_success(
            api.reactivate_corporate_account(ctx["account"]["id"], ctx["admin"])
        )
        assert reactivated["status"] == "ACTIVE"
        program_after = get_wellness_program(ctx, program["id"])
        assert program_after["status"] == "PAUSED", (
            "Only suspension cascades; reactivation must not resume programs"
        )
        assert program_after["next_occurrence_date"] is None
