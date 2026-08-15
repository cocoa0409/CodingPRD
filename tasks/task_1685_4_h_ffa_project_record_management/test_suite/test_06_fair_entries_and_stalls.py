"""Fair entry ownership windows, posture gating, referential integrity, pens."""
from test_helpers import (
    assert_fair_entry,
    assert_stall_assignment,
    create_active_member,
    create_fair_entry,
    create_fair_entry_payload,
    create_pen,
    create_project_payload,
    create_stall_assignment_payload,
    make_member_headers,
    make_volunteer_headers,
    record_attendance_and_hold,
    setup_active_member_with_project,
    setup_club_with_volunteers,
    setup_confirmed_fair_entry,
    setup_eligible_member,
    validate_error,
    validate_success,
)


class TestOwnershipDaysBoundary:
    def test_beef_owned_exactly_60_days_confirms(self, api):
        """PRD §3.8: "confirming an entry (ENTERED → CONFIRMED) requires the
        member's `eligibility_posture` to be ELIGIBLE and the entry's
        `ownership_days_at_entry` to meet the species minimum — at least 60 days
        for BEEF, at least 30 days for SHEEP or SWINE, with exactly the required
        number of days qualifying." PRD §3.8: "The entry starts in ENTERED
        status, and at creation the system computes `ownership_days_at_entry`
        against the fixed program-year fair-entry deadline of
        2026-08-01T00:00:00Z."

        owned_since 2026-06-02 -> exactly 60 whole days at the deadline.

        Design: Difficulty/boundary_precision_check/ownership_days_exactly_at_threshold
        """
        setup = setup_eligible_member(
            project_type="BEEF", species="BEEF", owned_since="2026-06-02T00:00:00Z"
        )
        entry = create_fair_entry(setup["member"]["id"], setup["project"]["id"])
        assert_fair_entry(entry)
        assert entry["ownership_days_at_entry"] == 60, (
            f"2026-06-02 to the 2026-08-01 deadline is exactly 60 whole days, "
            f"got {entry['ownership_days_at_entry']}"
        )
        confirmed = validate_success(
            api.confirm_fair_entry(
                entry["id"], make_volunteer_headers(setup["ctx"]["vol1"]["id"])
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED", (
            "exactly the required number of days qualifies (>= is inclusive)"
        )

    def test_beef_owned_59_days_rejected(self, api):
        """PRD §3.8: "An entry that falls short of its species minimum is
        rejected with `ERR_OWNERSHIP_PERIOD_SHORT` (HTTP 422)."

        owned_since 2026-06-03 -> 59 whole days, one short of the BEEF minimum.

        Design: Difficulty/boundary_precision_check/ownership_days_exactly_at_threshold
        """
        setup = setup_eligible_member(
            project_type="BEEF", species="BEEF", owned_since="2026-06-03T00:00:00Z"
        )
        entry = create_fair_entry(setup["member"]["id"], setup["project"]["id"])
        assert entry["ownership_days_at_entry"] == 59
        res = api.confirm_fair_entry(
            entry["id"], make_volunteer_headers(setup["ctx"]["vol1"]["id"])
        )
        validate_error(res, "ERR_OWNERSHIP_PERIOD_SHORT")

    def test_sheep_owned_exactly_30_days_confirms(self, api):
        """PRD §3.8: "at least 60 days for BEEF, at least 30 days for SHEEP or
        SWINE, with exactly the required number of days qualifying."

        owned_since 2026-07-02 -> exactly 30 whole days at the 2026-08-01
        deadline; the SHEEP boundary is inclusive.

        Design: Difficulty/boundary_precision_check/ownership_days_exactly_at_threshold
        """
        setup = setup_eligible_member(
            project_type="SHEEP", species="SHEEP", owned_since="2026-07-02T00:00:00Z"
        )
        entry = create_fair_entry(setup["member"]["id"], setup["project"]["id"])
        assert entry["ownership_days_at_entry"] == 30
        confirmed = validate_success(
            api.confirm_fair_entry(
                entry["id"], make_volunteer_headers(setup["ctx"]["vol1"]["id"])
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"


class TestConfirmRequiresEligibleMember:
    def test_ineligible_member_blocks_confirm(self, api):
        """PRD §3.8: "Confirmation is a volunteer's act and the gateway to the
        grounds: confirming an entry (ENTERED → CONFIRMED) requires the member's
        `eligibility_posture` to be ELIGIBLE and the entry's
        `ownership_days_at_entry` to meet the species minimum — at least 60 days
        for BEEF, at least 30 days for SHEEP or SWINE, with exactly the required
        number of days qualifying." PRD §2.9: "the target
        resource is in a valid from-state for the requested transition;
        otherwise `ERR_INVALID_STATE` (HTTP 409)."

        A member with no attendance evidence and no approved book is INELIGIBLE
        (PRD §3.7: "It is INELIGIBLE in every other case."), so confirmation of
        their ENTERED entry fails the transition's preconditions.

        Design: Difficulty/cross_entity_state_dependency/fair_entry_confirm_requires_member_eligible
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, project_type="FOODS")
        member_now = validate_success(
            api.get_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert member_now["eligibility_posture"] == "INELIGIBLE"
        entry = create_fair_entry(member["id"], project["id"])
        assert entry["status"] == "ENTERED"

        res = api.confirm_fair_entry(entry["id"], make_volunteer_headers(ctx["vol1"]["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_conditional_member_blocks_confirm(self, api):
        """PRD §3.8: "confirming an entry (ENTERED → CONFIRMED) requires the
        member's `eligibility_posture` to be ELIGIBLE". PRD §3.7: "It is
        CONDITIONAL when the attendance percentage is at least 75 and exactly
        one of the two documentary conditions holds". PRD §2.9: "the
        target resource is in a valid from-state for the
        requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Attendance 100% with no approved record book lands CONDITIONAL (the
        non-livestock tag leg is satisfied vacuously); CONDITIONAL is not
        ELIGIBLE, so confirmation fails.

        Design: Difficulty/cross_entity_state_dependency/fair_entry_confirm_requires_member_eligible
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, project_type="FOODS")
        record_attendance_and_hold(ctx, member["id"], ["PRESENT"])
        member_now = validate_success(
            api.get_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert member_now["eligibility_posture"] == "CONDITIONAL", (
            f"attendance-only member must be CONDITIONAL, got {member_now['eligibility_posture']}"
        )
        entry = create_fair_entry(member["id"], project["id"])

        res = api.confirm_fair_entry(entry["id"], make_volunteer_headers(ctx["vol1"]["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestFairEntryReferentialIntegrity:
    def test_project_of_other_member_rejected(self, api):
        """PRD §3.8: "The project must belong to the entering member; a mismatch
        is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422)."

        Design: Corner/endpoints/fair_entry_referential_integrity_project_member_mismatch
        """
        ctx = setup_club_with_volunteers()
        member_a = create_active_member(ctx["club"]["id"], ctx["vol1"]["id"], birth_date="2009-01-01")
        member_b = create_active_member(ctx["club"]["id"], ctx["vol1"]["id"], birth_date="2009-02-01")
        project_a = validate_success(
            api.create_project(
                create_project_payload(member_a["id"]), make_member_headers(member_a["id"])
            ),
            201,
        )
        validate_success(api.start_project(project_a["id"], make_member_headers(member_a["id"])), 200)

        res = api.create_fair_entry(
            create_fair_entry_payload(member_b["id"], project_a["id"]),
            make_member_headers(member_b["id"]),
        )
        validate_error(res, "ERR_REFERENTIAL_INTEGRITY")


class TestPenCapacity:
    def test_assignments_up_to_capacity_succeed(self, api):
        """PRD §3.8: "The check is an aggregate count, not an interval rule: an
        assignment that would push the pen's count of ASSIGNED stall assignments
        beyond its `animal_capacity` is rejected with
        `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 422)."

        Count reaching exactly the capacity is not "beyond", so both assignments
        into a capacity-2 pen succeed.

        Design: Difficulty/resource_temporal_overlap/pen_capacity_aggregate_count
        """
        pen = create_pen(animal_capacity=2)
        first = setup_confirmed_fair_entry(species="SHEEP")
        second = setup_confirmed_fair_entry(species="SHEEP")
        for setup in (first, second):
            vol_headers = make_volunteer_headers(setup["ctx"]["vol1"]["id"])
            assigned = validate_success(
                api.create_stall_assignment(
                    create_stall_assignment_payload(setup["fair_entry"]["id"], pen["id"]),
                    vol_headers,
                ),
                201,
            )
            assert_stall_assignment(assigned)
            assert assigned["status"] == "ASSIGNED"

    def test_assignment_beyond_capacity_rejected(self, api):
        """PRD §3.8: "an assignment that would push the pen's count of ASSIGNED
        stall assignments beyond its `animal_capacity` is rejected with
        `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 422)."

        The third assignment into a capacity-2 pen holding two ASSIGNED rows is
        the one that pushes the count beyond capacity.

        Design: Difficulty/resource_temporal_overlap/pen_capacity_aggregate_count
        """
        pen = create_pen(animal_capacity=2)
        setups = [setup_confirmed_fair_entry(species="SHEEP") for _ in range(3)]
        for setup in setups[:2]:
            validate_success(
                api.create_stall_assignment(
                    create_stall_assignment_payload(setup["fair_entry"]["id"], pen["id"]),
                    make_volunteer_headers(setup["ctx"]["vol1"]["id"]),
                ),
                201,
            )
        res = api.create_stall_assignment(
            create_stall_assignment_payload(setups[2]["fair_entry"]["id"], pen["id"]),
            make_volunteer_headers(setups[2]["ctx"]["vol1"]["id"]),
        )
        validate_error(res, "ERR_PEN_CAPACITY_EXCEEDED")
