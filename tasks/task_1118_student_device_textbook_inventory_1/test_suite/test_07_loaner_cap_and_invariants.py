"""Loaner duration-cap interval semantics (PRD §2.8/§3.8) and compensating
invariants across checkout/return and fee transitions (PRD §3.4, §3.7)."""

from test_helpers import (
    create_assignment_for,
    create_loaner_checkout_for,
    enroll_signed_student,
    get_loaner_checkout,
    get_success_data,
    refresh_student,
    set_clock,
    setup_confirmed_damage_fee,
    setup_loaner_pool,
    setup_program_fleet_assets,
    make_family_headers,
    return_assignment_payload,
    settle_fee_payload,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


class TestLoanerDurationCapInterval:
    def _setup_open_loaner(self, api):
        """One pool unit checked out with max_loaner_days=14 at the boot
        clock (2026-05-01); floor set to 0 so the pool may drain."""
        program, fleet, loaners, _ = setup_loaner_pool(
            n_units=1, n_loaners=1, threshold_pct=0.0
        )
        student = enroll_signed_student(program["id"], "SIS-LC-1", "Loaner")
        checkout = create_loaner_checkout_for(
            program["id"], student["id"],
            loaner_asset_unit_id=loaners[0]["id"], max_loaner_days=14,
        )
        assert checkout["status"] == "OPEN"
        return program, student, checkout

    def test_checkout_still_open_at_exactly_cap_days(self, api):
        """PRD §3.8: "The clock-driven scan moves a still-open checkout from `OPEN` to `OVERDUE` once it has been out longer than its cap with `returned_at` still null."

        At exactly 14 days the checkout has not been out LONGER than its cap,
        so it remains OPEN (strict greater-than boundary).

        Design: Difficulty/resource_temporal_overlap/loaner_checkout_max_loaner_days_interval_cap
        """
        program, student, checkout = self._setup_open_loaner(api)
        set_clock("2026-05-15T00:00:00Z")  # exactly 14 days later
        current = get_loaner_checkout(program["id"], student["id"], checkout["id"])
        assert current["status"] == "OPEN", (
            f"Exactly at the 14-day cap must remain OPEN, got {current['status']}"
        )

    def test_checkout_overdue_beyond_cap_days(self, api):
        """PRD §2.8: "Advancing the clock fires the system's nightly-scan-style transitions wherever their preconditions now hold: an assignment whose `expected_return_date` has passed without a check-in moves from `ACTIVE` to `OVERDUE`, and a loaner checkout that has been open longer than its `max_loaner_days` cap without a return moves from `OPEN` to `OVERDUE`."

        At 15 days the checkout has been out longer than its 14-day cap and
        moves to OVERDUE.

        Design: Difficulty/resource_temporal_overlap/loaner_checkout_max_loaner_days_interval_cap
        """
        program, student, checkout = self._setup_open_loaner(api)
        set_clock("2026-05-16T00:00:00Z")  # 15 days later
        current = get_loaner_checkout(program["id"], student["id"], checkout["id"])
        assert current["status"] == "OVERDUE", (
            f"Beyond the 14-day cap must be OVERDUE, got {current['status']}"
        )


class TestAssignmentReturnConservesFleetUnitCount:
    def test_checkout_and_return_keep_fleet_unit_count_constant(self, api,
                                                                admin_headers,
                                                                tech_headers):
        """PRD §3.4: "The unit itself transitions `READY → DEPLOYED`, its `assigned_to_student_id` is set to the student, and a `DEPLOY` event is appended to its lifecycle trail."
        PRD §3.5: "the unit's lifecycle moves to `READY`, or to `IN_REPAIR` when damage was observed."

        Checkout (READY -> DEPLOYED) then an on-time, undamaged return
        (DEPLOYED -> READY) are exactly compensating: the fleet's unit count
        never changes and the status distribution returns to its origin.

        Design: Difficulty/compensating_invariant/assignment_return_conserves_fleet_unit_count
        """
        program, fleet, assets = setup_program_fleet_assets(n_assets=1)
        student = enroll_signed_student(program["id"], "SIS-INV-1", "Inv")
        before, _ = validate_paginated(
            api.list_asset_units(program["id"], fleet["id"], admin_headers)
        )
        assignment = create_assignment_for(
            program["id"], student["id"], assets[0]["id"]
        )
        during = get_success_data(
            api.get_asset_unit(program["id"], assets[0]["id"], admin_headers)
        )
        assert during["lifecycle_status"] == "DEPLOYED"
        validate_success(
            api.return_assignment(program["id"], student["id"], assignment["id"],
                                  return_assignment_payload(
                                      return_condition_grade="A"),
                                  tech_headers),
            200,
        )
        after_unit = get_success_data(
            api.get_asset_unit(program["id"], assets[0]["id"], admin_headers)
        )
        assert after_unit["lifecycle_status"] == "READY"
        after, _ = validate_paginated(
            api.list_asset_units(program["id"], fleet["id"], admin_headers)
        )
        assert len(after) == len(before), (
            f"Unit count drifted: {len(before)} before, {len(after)} after"
        )

    def test_checkout_increments_student_and_asset_versions(self, api,
                                                            admin_headers):
        """PRD §3.4: "The operation is a cross-aggregate mutation: the student account's `version` increments by one, and the asset unit's `version` increments by one as well."

        Design: Difficulty/compensating_invariant/assignment_return_conserves_fleet_unit_count
        """
        program, fleet, assets = setup_program_fleet_assets(n_assets=1)
        student = enroll_signed_student(program["id"], "SIS-INV-2", "Inv2")
        student_before = refresh_student(program["id"], student["id"])
        asset_before = get_success_data(
            api.get_asset_unit(program["id"], assets[0]["id"], admin_headers)
        )
        create_assignment_for(program["id"], student["id"], assets[0]["id"])
        student_after = refresh_student(program["id"], student["id"])
        asset_after = get_success_data(
            api.get_asset_unit(program["id"], assets[0]["id"], admin_headers)
        )
        assert student_after["version"] == student_before["version"] + 1
        assert asset_after["version"] == asset_before["version"] + 1


class TestFeeConservationInvariant:
    def test_appeal_grant_waives_residual_conserving_total(self, api,
                                                           admin_headers):
        """PRD §3.7: "Granting the appeal moves `APPEALED → WAIVED` and sets `waived_cents` to the `amount_cents` minus whatever `paid_cents` has already been collected, wiping the remaining obligation."

        fee amount 10000, paid 0 -> appeal-grant sets waived to the full
        residual 10000: paid + waived == amount, nothing created or destroyed.

        Design: Difficulty/compensating_invariant/settle_then_appeal_grant_conserves_total_collected_plus_outstanding
        """
        ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                         observed_condition_grade="A")
        fee = ctx["fee"]
        assert fee["amount_cents"] == 10000
        appealed = validate_success(
            api.appeal_fee(ctx["program"]["id"], ctx["student"]["id"],
                           fee["id"], make_family_headers(ctx["student"]["id"])),
            200,
        )
        assert appealed["status"] == "APPEALED"
        waived = validate_success(
            api.appeal_grant_fee(ctx["program"]["id"], ctx["student"]["id"],
                                 fee["id"], admin_headers),
            200,
        )
        assert waived["status"] == "WAIVED"
        assert waived["paid_cents"] == 0
        assert waived["waived_cents"] == 10000
        assert waived["paid_cents"] + waived["waived_cents"] == waived["amount_cents"]

    def test_full_settle_conserves_total(self, api, admin_headers):
        """PRD §3.7: "a `DistrictAdmin` records a `payment_cents` amount, which is added to the fee's `paid_cents`, and the fee moves `ASSESSED → SETTLED` only once the collected `paid_cents` plus the `waived_cents` together reach the `amount_cents` — an attempt to settle short of that mark is rejected with `ERR_UNDERPAID` (HTTP 422)."

        A payment equal to the full amount settles the fee:
        paid 10000 + waived 0 == amount 10000.

        Design: Difficulty/compensating_invariant/settle_then_appeal_grant_conserves_total_collected_plus_outstanding
        """
        ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                         observed_condition_grade="A")
        fee = ctx["fee"]
        settled = validate_success(
            api.settle_fee(ctx["program"]["id"], ctx["student"]["id"],
                           fee["id"], settle_fee_payload(10000), admin_headers),
            200,
        )
        assert settled["status"] == "SETTLED"
        assert settled["paid_cents"] == 10000
        assert settled["waived_cents"] == 0
        assert settled["paid_cents"] + settled["waived_cents"] == settled["amount_cents"]
