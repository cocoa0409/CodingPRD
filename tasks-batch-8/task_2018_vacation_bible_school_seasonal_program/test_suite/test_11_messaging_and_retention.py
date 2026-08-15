"""Family messaging, attendance-rate variants, next-year retention, and
read-after-write consistency (PRD §2.10, §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_plan,
    create_message,
    create_plan,
    create_volunteer_with_assignment,
    generate_retention,
    get_classroom,
    get_registration,
    register_child,
    run_session_days,
    send_message,
    setup_family_with_children,
    setup_in_session_program,
    setup_open_program_with_classroom,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    complete_program,
)
from test_helpers.test_users import TEST_USERS

_DIRECTOR = TEST_USERS["program_director_headers"]


def _get_retention_entry(api, program_id, child_id) -> dict:
    data, meta = validate_paginated(
        api.list_retention_entries(
            _DIRECTOR, params={"program_id": program_id, "child_id": child_id}
        )
    )
    assert meta["total_count"] == 1, "exactly one retention entry per qualifying child"
    return data[0]


class TestFamilyMessaging:
    def test_classroom_audience_requires_classroom_id(self, api, program_director_headers):
        """PRD §3.8: "`classroom_id` is required exactly when the audience is
        `CLASSROOM` and forbidden otherwise (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/message_classroom_audience_missing_required_classroom_id
        """
        from test_helpers import create_program
        program = create_program()
        resp = api.create_message(
            {"program_id": program["id"], "subject": "Koalas update",
             "body": "Bring smocks", "audience": "CLASSROOM"},
            program_director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_recipient_count_dedups_families(self, api):
        """PRD §3.8: "for `ALL_FAMILIES`, the distinct families with at least
        one child holding an `ENROLLED`, `WAITLISTED`, or `OFFERED`
        registration in the program; for `CLASSROOM`, the same rule restricted to
        registrations in the message's classroom; for `ALLERGY_ALERT`, the
        distinct families with at least one child holding an `APPROVED`
        `FOOD_ALLERGY` plan and an `ENROLLED` registration in the program; for
        `VOLUNTEERS`, the program's volunteers in `CLEARED`. Family-level dedup
        applies throughout: one recipient per family no matter how many
        qualifying children it has."

        Design: Corner/calculations/recipient_count_dedups_families
        """
        program, classroom = setup_open_program_with_classroom(capacity=10)
        family_1, kids_1 = setup_family_with_children(count=2)
        family_2, kids_2 = setup_family_with_children(count=1)
        register_child(kids_1[0]["id"], classroom["id"], family_1["id"])
        register_child(kids_1[1]["id"], classroom["id"], family_1["id"])
        register_child(kids_2[0]["id"], classroom["id"], family_2["id"])

        plan = create_plan(kids_1[0]["id"], family_1["id"], allergens=["PEANUT"],
                           instructions="No peanut snacks")
        submit_plan(plan["id"], family_1["id"])
        approve_plan(plan["id"], expected_child_version=kids_1[0]["version"])

        msg_all = create_message(program["id"], subject="Welcome",
                                 body="See you Monday", audience="ALL_FAMILIES")
        sent_all = send_message(msg_all["id"])
        assert sent_all["recipient_count"] == 2, (
            "3 enrolled children but only 2 distinct families"
        )

        msg_alert = create_message(program["id"], subject="Allergy menu",
                                   body="Peanut-free week", audience="ALLERGY_ALERT")
        sent_alert = send_message(msg_alert["id"])
        assert sent_alert["recipient_count"] == 1, (
            "only the first family holds an APPROVED FOOD_ALLERGY plan"
        )


class TestAttendanceRateVariants:
    def _setup_partial_week(self):
        """IN_SESSION program with 5 days; the child attended (checked out on)
        days 1-2; days 3-5 remain SCHEDULED."""
        ctx = setup_in_session_program(child_count=1)
        child = ctx["children"][0]
        run_session_days(ctx, [[child["id"]], [child["id"]]])
        return ctx, child

    def test_counters_and_provisional_rate(self, api, program_director_headers):
        """PRD §3.7: "a per-child attendance summary reports `attended_days`
        (records in `CHECKED_OUT`), `days_closed`, `total_days`, and two rates,
        each rounded half-up to four decimal places: `provisional_rate`,
        attended days divided by days closed so far — zero when no day has
        closed, so a mid-program child with perfect attendance reads 1.0000".

        Design: Difficulty/dual_variant_calc/attendance_rate_provisional_vs_final
        """
        ctx, child = self._setup_partial_week()
        resp = api.get_attendance_summary(
            ctx["program"]["id"], child["id"], program_director_headers
        )
        summary = validate_success(resp)
        assert summary["attended_days"] == 2
        assert summary["days_closed"] == 2
        assert summary["total_days"] == 5
        assert summary["provisional_rate"] == pytest.approx(1.0, abs=1e-9), (
            "provisional divides by days_closed: 2/2"
        )

    def test_projected_final_differs_mid_program(self, api, program_director_headers):
        """PRD §3.7: "`projected_final_rate`, attended days divided by all
        program days regardless of status — zero when the program has no days.
        Whenever unclosed days remain, the projected figure sits below the
        provisional one for identical attendance data." — identical attendance
        data, different denominator: 2/5 == 0.4000.

        Design: Difficulty/dual_variant_calc/attendance_rate_provisional_vs_final
        """
        ctx, child = self._setup_partial_week()
        resp = api.get_attendance_summary(
            ctx["program"]["id"], child["id"], program_director_headers
        )
        summary = validate_success(resp)
        assert summary["projected_final_rate"] == pytest.approx(0.4, abs=1e-9)


class TestRetentionTierBoundary:
    def _setup_completed_week(self):
        """Five-day program run to COMPLETED. Child X (family 1) attended days
        1-4 (rate 0.8000); child Y (family 2) days 1-3 (0.6000, no bonus);
        child Z (family 3) days 1-3 (0.6000) with a family-linked volunteer who
        reached a CONFIRMED assignment (bonus). Day 5: everyone ABSENT."""
        ctx = setup_in_session_program(child_count=3, one_family=False)
        kid_x, kid_y, kid_z = [c["id"] for c in ctx["children"]]

        # Family-linked volunteer for child Z's family only: a
        # SNACK_COORDINATOR assignment that reaches CONFIRMED via auto-confirm
        # at clearance (PRD §3.4).
        create_volunteer_with_assignment(
            ctx["program"]["id"], ctx["classroom"]["id"], "SNACK_COORDINATOR",
            decide_count=3, family_id=ctx["families"][2]["id"],
        )

        run_session_days(ctx, [
            [kid_x, kid_y, kid_z],
            [kid_x, kid_y, kid_z],
            [kid_x, kid_y, kid_z],
            [kid_x],
            [],
        ])
        complete_program(ctx["program"]["id"])
        return ctx

    def test_rate_at_0800_qualifies_for_tier_a(self, api):
        """PRD §3.8: "tier `A` when the rate is at least 0.80, or at least 0.60
        with the bonus; otherwise tier `B` when the rate is at least 0.50, or
        the bonus holds at any rate; otherwise tier `C`. The comparisons are
        inclusive against the four-decimal rounded rate — 0.8000 earns `A`;
        0.7999 does not."

        Design: Difficulty/boundary_precision_check/retention_tier_ratio_boundary
        """
        ctx = self._setup_completed_week()
        result = generate_retention(ctx["program"]["id"])
        assert result["created_count"] == 3, (
            "one RetentionEntry per child with at least one CHECKED_OUT day (§3.8)"
        )
        entry_x = _get_retention_entry(api, ctx["program"]["id"], ctx["children"][0]["id"])
        assert entry_x["attendance_rate"] == pytest.approx(0.8, abs=1e-9)
        assert entry_x["priority_tier"] == "A", "rate exactly at the 0.80 boundary"

    def test_0600_with_and_without_bonus(self, api):
        """PRD §3.8: "tier `A` when the rate is at least 0.80, or at least 0.60
        with the bonus; otherwise tier `B` when the rate is at least 0.50, or
        the bonus holds at any rate"; and "`family_volunteer_bonus` is true
        when some volunteer whose `family_id` equals the child's family holds
        an assignment that reached `CONFIRMED` — whether still `CONFIRMED` or
        since `RELEASED`." — 0.6000 alone reaches only B; 0.6000 with the bonus
        reaches A (the bonus arm's boundary is equally inclusive).

        Design: Difficulty/boundary_precision_check/retention_tier_ratio_boundary
        """
        ctx = self._setup_completed_week()
        generate_retention(ctx["program"]["id"])

        entry_y = _get_retention_entry(api, ctx["program"]["id"], ctx["children"][1]["id"])
        assert entry_y["attendance_rate"] == pytest.approx(0.6, abs=1e-9)
        assert entry_y["family_volunteer_bonus"] is False
        assert entry_y["priority_tier"] == "B"

        entry_z = _get_retention_entry(api, ctx["program"]["id"], ctx["children"][2]["id"])
        assert entry_z["attendance_rate"] == pytest.approx(0.6, abs=1e-9)
        assert entry_z["family_volunteer_bonus"] is True
        assert entry_z["priority_tier"] == "A"


class TestRetentionRegeneration:
    def test_regenerate_without_force_rejected_and_force_preserves_responses(self, api):
        """PRD §3.8: "Regenerating while entries already exist is rejected with
        `ERR_RETENTION_EXISTS` unless the caller passes `force` true, which
        regenerates entries still `LISTED` or `INVITED` and preserves those
        already `RESPONDED_YES` or `RESPONDED_NO`; the response reports
        `created_count` and whether the run was a `regenerated` one."; and "The
        director then works the list: inviting moves `LISTED` → `INVITED`, and
        recording a response with `outcome` `YES` or `NO` moves `INVITED` →
        `RESPONDED_YES` or `INVITED` → `RESPONDED_NO`".

        Design: Corner/validations/retention_regenerate_without_force_rejected
        """
        ctx = setup_in_session_program(
            child_count=1, n_days=1,
            program_overrides={"name": "VBS Mini", "end_date": "2026-08-17"},
        )
        child = ctx["children"][0]
        run_session_days(ctx, [[child["id"]]])
        complete_program(ctx["program"]["id"])

        first = generate_retention(ctx["program"]["id"])
        assert first["created_count"] == 1
        entry = _get_retention_entry(api, ctx["program"]["id"], child["id"])
        assert entry["attendance_rate"] == pytest.approx(1.0, abs=1e-9)
        assert entry["priority_tier"] == "A"

        validate_success(api.invite_retention_entry(entry["id"], _DIRECTOR))
        responded = validate_success(
            api.record_retention_response(entry["id"], {"outcome": "YES"}, _DIRECTOR)
        )
        assert responded["status"] == "RESPONDED_YES"

        resp_again = api.generate_retention_list(ctx["program"]["id"], {}, _DIRECTOR)
        validate_error(resp_again, ApiErrorId.ERR_RETENTION_EXISTS, 409)

        forced = generate_retention(ctx["program"]["id"], force=True)
        assert forced["regenerated"] is True
        assert forced["created_count"] == 0, (
            "force regenerates LISTED/INVITED entries only; none existed"
        )
        entry_after = validate_success(api.get_retention_entry(entry["id"], _DIRECTOR))
        assert entry_after["status"] == "RESPONDED_YES", (
            "responded entries survive forced regeneration"
        )


class TestImmediateConsistency:
    def test_mutation_and_cascade_visible_immediately(self, api):
        """PRD §2.10: "Consistency is immediate: every mutation and all of its
        cascades are visible in the same request's response and in any
        subsequent read."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        program, classroom = setup_open_program_with_classroom(capacity=2)
        family, children = setup_family_with_children(count=1)
        registration = register_child(children[0]["id"], classroom["id"], family["id"])

        from test_helpers.test_users import make_parent_headers
        resp = api.cancel_registration(
            registration["id"], make_parent_headers(family["id"])
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED", (
            "mutation result visible in the same response"
        )

        reread = get_registration(registration["id"])
        assert reread["status"] == "CANCELLED"
        assert get_classroom(classroom["id"])["enrolled_count"] == 0, (
            "the cascaded counter change reads back without any refresh"
        )
