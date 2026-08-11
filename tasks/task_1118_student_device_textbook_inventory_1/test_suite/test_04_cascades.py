"""Transitive cascades: damage-confirm depth-3 chain (PRD §3.3, §3.6) and
begin-summer-collection depth-2 cascade (PRD §3.9)."""

from test_helpers import (
    add_active_insurance,
    confirm_damage_report,
    create_assignment_for,
    enroll_signed_student,
    file_damage_report,
    get_success_data,
    refresh_student,
    set_clock,
    setup_program_fleet_assets,
    setup_student_with_assignment,
    submit_damage_report,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_cap_exhaustion(api):
    """LOSS report at grade A (gross 100000) against a policy with cap 3000
    and deductible 1000: payout 3000 reaches the cap; family owes 97000."""
    ctx = setup_student_with_assignment(asset_grade="A", free_lunch=False)
    policy = add_active_insurance(
        ctx["program"]["id"], ctx["student"]["id"],
        deductible_cents=1000, coverage_cap_cents=3000,
    )
    ctx["policy"] = policy
    report = file_damage_report(
        ctx, damage_category="LOSS", observed_condition_grade="A"
    )
    assert report["provisional_fee_cents"] == 100000
    submit_damage_report(ctx, report["id"])
    confirmed = confirm_damage_report(ctx, report["id"])
    ctx["report"] = confirmed
    return ctx


class TestConfirmDamageReportDepth3Cascade:
    def test_confirm_creates_fee_and_recomputes_posture(self, api):
        """PRD §3.6: "The outcome becomes `final_fee_cents`, a fee row is created with `fee_type` `DAMAGE` — or `INSURANCE_DEDUCTIBLE` for the deductible component when insurance applies — the student's `lifetime_damage_count` increments by one, and their `financial_posture` is recomputed."
        PRD §3.6: "when it is not, the insurer pays only the remaining coverage and the family owes the gross minus that payout."

        gross 100000, coverage remaining 3000 < 99000 -> payout 3000, family
        owes 97000 -> outstanding 97000 >= 10000 -> SUSPENDED (link 1 -> 2).

        Design: Difficulty/transitive_cascade/confirm_damage_report_depth3_cascade
        """
        ctx = _setup_cap_exhaustion(api)
        assert ctx["report"]["status"] == "CONFIRMED"
        assert ctx["report"]["final_fee_cents"] == 97000, (
            f"Expected final 97000, got {ctx['report']['final_fee_cents']}"
        )
        student = refresh_student(ctx["program"]["id"], ctx["student"]["id"])
        assert student["lifetime_damage_count"] == 1
        assert student["outstanding_balance_cents"] == 97000
        assert student["financial_posture"] == "SUSPENDED"

    def test_confirm_exhausts_policy_when_payout_reaches_cap(self, api):
        """PRD §3.3: "Exhaustion is automatic: the moment cumulative payouts under the policy reach the `coverage_cap_cents`, the policy moves `ACTIVE → EXHAUSTED`."
        PRD §3.3: "Three exits close a policy, and each one flips `insurance_enrolled` back to false."

        The 3000 payout reaches the 3000 cap: the payout-driven exhaustion is
        link 3 of the cascade, fired by the fee creation, not by the confirm
        directly.

        Design: Difficulty/transitive_cascade/confirm_damage_report_depth3_cascade
        """
        ctx = _setup_cap_exhaustion(api)
        policy = get_success_data(
            api.get_insurance_policy(
                ctx["program"]["id"], ctx["student"]["id"],
                ctx["policy"]["id"], REGISTRAR,
            )
        )
        assert policy["status"] == "EXHAUSTED", (
            f"Expected EXHAUSTED after payout reached cap, got {policy['status']}"
        )
        student = refresh_student(ctx["program"]["id"], ctx["student"]["id"])
        assert student["insurance_enrolled"] is False


class TestBeginSummerCollectionCascade:
    def _setup_two_assignments(self, api, expected_return_date):
        program, fleet, assets = setup_program_fleet_assets(n_assets=2)
        s1 = enroll_signed_student(program["id"], "SIS-SC-1", "SC One")
        s2 = enroll_signed_student(program["id"], "SIS-SC-2", "SC Two")
        as1 = create_assignment_for(program["id"], s1["id"], assets[0]["id"],
                                    expected_return_date=expected_return_date)
        as2 = create_assignment_for(program["id"], s2["id"], assets[1]["id"],
                                    expected_return_date=expected_return_date)
        return program, s1, s2, as1, as2

    def test_begin_summer_collection_flips_past_due_assignments(self, api,
                                                                admin_headers):
        """PRD §3.9: "Beginning collection cascades through the fleet: every assignment still `ACTIVE` whose `expected_return_date` has passed flips to `OVERDUE`, and every `DEPLOYED` unit moves to `SUMMER_INTAKE` as its assignment closes, appending a `RETURN` event to the unit's trail."
        PRD §2.8: "Advancing the clock fires the system's nightly-scan-style transitions wherever their preconditions now hold: an assignment whose `expected_return_date` has passed without a check-in moves from `ACTIVE` to `OVERDUE`, and a loaner checkout that has been open longer than its `max_loaner_days` cap without a return moves from `OPEN` to `OVERDUE`."

        Design: Difficulty/transitive_cascade/begin_summer_collection_depth2_cascade
        """
        program, s1, s2, as1, as2 = self._setup_two_assignments(
            api, "2026-06-01T00:00:00Z"
        )
        set_clock("2026-06-15T00:00:00Z")
        program = validate_success(
            api.begin_summer_collection(program["id"], admin_headers), 200
        )
        assert program["status"] == "SUMMER_COLLECTION"
        for student, assignment in ((s1, as1), (s2, as2)):
            current = get_success_data(
                api.get_assignment(program["id"], student["id"],
                                   assignment["id"], REGISTRAR)
            )
            assert current["status"] == "OVERDUE", (
                f"Assignment {assignment['id']} expected OVERDUE, "
                f"got {current['status']}"
            )

    def test_begin_summer_collection_leaves_future_assignments_active(self, api,
                                                                      admin_headers):
        """PRD §3.9: "Beginning collection cascades through the fleet: every assignment still `ACTIVE` whose `expected_return_date` has passed flips to `OVERDUE`, and every `DEPLOYED` unit moves to `SUMMER_INTAKE` as its assignment closes, appending a `RETURN` event to the unit's trail."

        Only assignments whose expected_return_date has passed flip; an
        assignment due next year is untouched by the cascade.

        Design: Difficulty/transitive_cascade/begin_summer_collection_depth2_cascade
        """
        program, s1, s2, as1, as2 = self._setup_two_assignments(
            api, "2027-06-01T00:00:00Z"
        )
        set_clock("2026-06-15T00:00:00Z")
        program = validate_success(
            api.begin_summer_collection(program["id"], admin_headers), 200
        )
        assert program["status"] == "SUMMER_COLLECTION"
        for student, assignment in ((s1, as1), (s2, as2)):
            current = get_success_data(
                api.get_assignment(program["id"], student["id"],
                                   assignment["id"], REGISTRAR)
            )
            assert current["status"] == "ACTIVE", (
                f"Assignment {assignment['id']} expected ACTIVE, "
                f"got {current['status']}"
            )
