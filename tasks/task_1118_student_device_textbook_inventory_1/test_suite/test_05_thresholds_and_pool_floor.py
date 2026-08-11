"""Boundary precision: the 10000-cent suspension threshold (PRD §3.2/§3.4)
and the loaner pool floor (PRD §3.8)."""

from test_helpers import (
    ApiErrorId,
    create_assignment_for,
    create_assignment_payload,
    create_loaner_checkout_for,
    enroll_signed_student,
    file_damage_report,
    refresh_student,
    set_clock,
    setup_loaner_pool,
    setup_program_fleet_assets,
    submit_damage_report,
    confirm_damage_report,
    return_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


def _setup_student_with_confirmed_fee(api, damage_category, observed_grade,
                                      asset_grade="A"):
    """Two READY units; first checked out, damaged and confirmed. Returns
    (program, student, spare_asset, ctx)."""
    program, fleet, assets = setup_program_fleet_assets(n_assets=2)
    student = enroll_signed_student(program["id"], "SIS-BND-1", "Boundary")
    ctx = {
        "program": program, "fleet": fleet, "asset": assets[0],
        "student": student,
        "assignment": create_assignment_for(program["id"], student["id"],
                                            assets[0]["id"]),
    }
    report = file_damage_report(ctx, damage_category, observed_grade)
    submit_damage_report(ctx, report["id"])
    confirm_damage_report(ctx, report["id"])
    return program, refresh_student(program["id"], student["id"]), assets[1], ctx


def _attempt_second_assignment(api, program, student, spare_asset):
    payload = create_assignment_payload(spare_asset["id"], student["version"])
    return api.create_assignment(program["id"], student["id"], payload, REGISTRAR)


class TestSuspendThresholdBoundary:
    def test_outstanding_above_threshold_blocks_assignment(self, api):
        """PRD §3.2: "A balance of 10,000 cents or more yields `SUSPENDED`."
        PRD §3.4: "The student's `financial_posture` must not be `SUSPENDED` (`ERR_STUDENT_SUSPENDED`)."

        SCREEN on a grade-A unit: 100000 * 0.55 * 1.00 = 55000 outstanding.

        Design: Difficulty/boundary_precision_check/suspend_threshold_inclusive_boundary
        """
        program, student, spare, _ = _setup_student_with_confirmed_fee(
            api, "SCREEN", "A"
        )
        assert student["outstanding_balance_cents"] == 55000
        assert student["financial_posture"] == "SUSPENDED"
        res = _attempt_second_assignment(api, program, student, spare)
        validate_error(res, ApiErrorId.ERR_STUDENT_SUSPENDED)

    def test_outstanding_exactly_at_threshold_is_suspended(self, api):
        """PRD §3.2: "A balance of 10,000 cents or more yields `SUSPENDED`."

        COSMETIC on a grade-A unit: 100000 * 0.10 * 1.00 = 10000 — the
        boundary is inclusive, so exactly 10000 is already SUSPENDED.

        Design: Difficulty/boundary_precision_check/suspend_threshold_inclusive_boundary
        """
        program, student, spare, _ = _setup_student_with_confirmed_fee(
            api, "COSMETIC", "A"
        )
        assert student["outstanding_balance_cents"] == 10000
        assert student["financial_posture"] == "SUSPENDED"
        res = _attempt_second_assignment(api, program, student, spare)
        validate_error(res, ApiErrorId.ERR_STUDENT_SUSPENDED)

    def test_fees_outstanding_below_threshold_still_allows_assignment(self, api,
                                                                      tech_headers):
        """PRD §3.2: "A positive balance below 10,000 cents (one hundred dollars) yields `FEES_OUTSTANDING`."
        PRD §3.4: "The student's `financial_posture` must not be `SUSPENDED` (`ERR_STUDENT_SUSPENDED`)."

        A 4-day-late return creates a 400-cent fee: FEES_OUTSTANDING is below
        the suspension gate, so a new assignment still succeeds.

        Design: Difficulty/boundary_precision_check/suspend_threshold_inclusive_boundary
        """
        program, fleet, assets = setup_program_fleet_assets(n_assets=2)
        student = enroll_signed_student(program["id"], "SIS-BND-2", "Below")
        as1 = create_assignment_for(program["id"], student["id"], assets[0]["id"],
                                    expected_return_date="2026-05-06T00:00:00Z")
        set_clock("2026-05-10T00:00:00Z")
        returned = validate_success(
            api.return_assignment(program["id"], student["id"], as1["id"],
                                  return_assignment_payload(
                                      return_condition_grade="A"),
                                  tech_headers),
            200,
        )
        assert returned["late_return_days"] == 4
        student = refresh_student(program["id"], student["id"])
        assert student["outstanding_balance_cents"] == 400
        assert student["financial_posture"] == "FEES_OUTSTANDING"
        as2 = create_assignment_for(program["id"], student["id"], assets[1]["id"])
        assert as2["status"] == "ACTIVE"


class TestLoanerPoolFloor:
    def test_checkout_breaching_loaner_floor_rejected(self, api):
        """PRD §3.8: "And before any allocation commits, the floor is checked: the number of units remaining in `LOANER` after the checkout must be at least the program's `loaner_pool_threshold_pct` multiplied by the number of deployable units, rounded down to a whole number — an allocation that would breach the floor is rejected with `ERR_LOANER_FLOOR_BREACH`."

        10 deployable units, floor 0.10 -> at least 1 must remain in LOANER.
        Checking out the only pool unit would leave 0 -> rejected.

        Design: Difficulty/boundary_precision_check/loaner_floor_breach_zero_remaining
        """
        program, fleet, loaners, _ = setup_loaner_pool(
            n_units=10, n_loaners=1, threshold_pct=0.10
        )
        student = enroll_signed_student(program["id"], "SIS-POOL-1", "Pool")
        res = api.create_loaner_checkout(
            program["id"], student["id"],
            {"checkout_reason": "REPAIR",
             "loaner_asset_unit_id": loaners[0]["id"]},
            TECH,
        )
        validate_error(res, ApiErrorId.ERR_LOANER_FLOOR_BREACH)
        checkouts, _ = validate_paginated(
            api.list_loaner_checkouts(program["id"], student["id"], TECH)
        )
        assert checkouts == [], "No LoanerCheckout may be created on breach"

    def test_checkout_leaving_exactly_the_floor_allowed(self, api):
        """PRD §3.8: "the number of units remaining in `LOANER` after the checkout must be at least the program's `loaner_pool_threshold_pct` multiplied by the number of deployable units, rounded down to a whole number".

        10 deployable units, 2 in the pool, floor 1: checking one out leaves
        exactly 1, which satisfies the floor, so the checkout is born OPEN.

        Design: Difficulty/boundary_precision_check/loaner_floor_breach_zero_remaining
        """
        program, fleet, loaners, _ = setup_loaner_pool(
            n_units=10, n_loaners=2, threshold_pct=0.10
        )
        student = enroll_signed_student(program["id"], "SIS-POOL-2", "Pool")
        checkout = create_loaner_checkout_for(
            program["id"], student["id"],
            loaner_asset_unit_id=loaners[0]["id"],
        )
        assert checkout["status"] == "OPEN"
        assert checkout["loaner_asset_unit_id"] == loaners[0]["id"]
