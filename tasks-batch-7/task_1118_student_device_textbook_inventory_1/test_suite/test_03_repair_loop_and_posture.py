"""AssetUnit cyclic repair loop and StudentAccount parallel state dimensions
(PRD §3.2, §3.5, §3.6)."""

from test_helpers import (
    create_assignment_for,
    enroll_signed_student,
    file_damage_report,
    get_success_data,
    list_fees,
    refresh_student,
    set_clock,
    settle_fee_payload,
    setup_program_fleet_assets,
    setup_student_with_assignment,
    submit_damage_report,
    confirm_damage_report,
    return_assignment_payload,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


class TestAssetUnitCyclicRepairLoop:
    def _setup_in_repair(self, api):
        """Unit DEPLOYED, then a FUNCTIONAL/F report sends it to IN_REPAIR."""
        ctx = setup_student_with_assignment(asset_grade="B")
        report = file_damage_report(
            ctx, damage_category="FUNCTIONAL", observed_condition_grade="F"
        )
        asset = get_success_data(
            api.get_asset_unit(ctx["program"]["id"], ctx["asset"]["id"], ADMIN)
        )
        assert asset["lifecycle_status"] == "IN_REPAIR", (
            "PRD §3.6: FUNCTIONAL damage observed at grade F sends the unit "
            "DEPLOYED -> IN_REPAIR at filing time"
        )
        submit_damage_report(ctx, report["id"])
        return ctx, report

    def test_dismiss_reverts_unit_from_in_repair_to_deployed(self, api):
        """PRD §3.6: "Dismissal moves `SUBMITTED → DISMISSED`: no fee is created, and if the unit had been sent `IN_REPAIR` on account of this report, the system reverts it to `DEPLOYED` and appends a `CORRECTION` event whose `supersedes_event_id` points at the earlier `REPAIR_START` event — the repair was a false alarm."

        Design: Difficulty/non_linear_state_machine/asset_unit_cyclic_repair_loop
        """
        ctx, report = self._setup_in_repair(api)
        dismissed = validate_success(
            api.dismiss_damage_report(
                ctx["program"]["id"], ctx["student"]["id"],
                ctx["assignment"]["id"], report["id"], TECH,
            ),
            200,
        )
        assert dismissed["status"] == "DISMISSED"
        asset = get_success_data(
            api.get_asset_unit(ctx["program"]["id"], ctx["asset"]["id"], ADMIN)
        )
        assert asset["lifecycle_status"] == "DEPLOYED", (
            f"Expected revert to DEPLOYED, got {asset['lifecycle_status']}"
        )
        assert list_fees(ctx) == [], "Dismissal must not create any fee"

    def test_dismiss_appends_correction_superseding_repair_start(self, api):
        """PRD §3.6: "if the unit had been sent `IN_REPAIR` on account of this report, the system reverts it to `DEPLOYED` and appends a `CORRECTION` event whose `supersedes_event_id` points at the earlier `REPAIR_START` event — the repair was a false alarm."

        Design: Difficulty/non_linear_state_machine/asset_unit_cyclic_repair_loop
        """
        ctx, report = self._setup_in_repair(api)
        validate_success(
            api.dismiss_damage_report(
                ctx["program"]["id"], ctx["student"]["id"],
                ctx["assignment"]["id"], report["id"], TECH,
            ),
            200,
        )
        events, _ = validate_paginated(
            api.list_lifecycle_events(ctx["program"]["id"], ctx["asset"]["id"], ADMIN)
        )
        by_type = {}
        for ev in events:
            by_type.setdefault(ev["event_type"], []).append(ev)
        assert "REPAIR_START" in by_type, f"No REPAIR_START event in {events}"
        assert "CORRECTION" in by_type, f"No CORRECTION event in {events}"
        correction = by_type["CORRECTION"][-1]
        repair_start = by_type["REPAIR_START"][-1]
        assert correction["supersedes_event_id"] == repair_start["id"], (
            f"CORRECTION supersedes {correction['supersedes_event_id']}, "
            f"expected REPAIR_START {repair_start['id']}"
        )


class TestStudentAccountParallelDimensions:
    def _setup_late_fee(self, api, tech_headers):
        """Signed student; a 5-day-late return generates a 500-cent fee."""
        ctx = setup_student_with_assignment(
            expected_return_date="2026-05-06T00:00:00Z"
        )
        set_clock("2026-05-11T00:00:00Z")
        returned = validate_success(
            api.return_assignment(
                ctx["program"]["id"], ctx["student"]["id"],
                ctx["assignment"]["id"],
                return_assignment_payload(return_condition_grade="A"),
                tech_headers,
            ),
            200,
        )
        assert returned["late_return_days"] == 5
        return ctx

    def test_late_fee_moves_posture_while_agreement_stays_signed(self, api,
                                                                 tech_headers):
        """PRD §3.2: "A zero balance yields `CLEAR`. A positive balance below 10,000 cents (one hundred dollars) yields `FEES_OUTSTANDING`."

        The agreement axis (SIGNED) and the posture axis (CLEAR ->
        FEES_OUTSTANDING) are independent dimensions: a late fee moves the
        posture without touching the agreement.

        Design: Difficulty/non_linear_state_machine/student_account_parallel_dimensions
        """
        ctx = self._setup_late_fee(api, tech_headers)
        student = refresh_student(ctx["program"]["id"], ctx["student"]["id"])
        assert student["family_agreement_status"] == "SIGNED"
        assert student["financial_posture"] == "FEES_OUTSTANDING", (
            f"Expected FEES_OUTSTANDING, got {student['financial_posture']}"
        )
        assert student["outstanding_balance_cents"] == 500

    def test_settling_fee_restores_clear_without_touching_agreement(self, api,
                                                                    tech_headers,
                                                                    admin_headers):
        """PRD §3.2: "The posture is recomputed on every fee mutation — creation, appeal, appeal grant or denial, settlement, waiver, or write-off."

        Settling the only open fee returns the posture axis to CLEAR while the
        agreement axis stays SIGNED — the two dimensions evolve independently.

        Design: Difficulty/non_linear_state_machine/student_account_parallel_dimensions
        """
        ctx = self._setup_late_fee(api, tech_headers)
        fee = list_fees(ctx)[0]
        settled = validate_success(
            api.settle_fee(
                ctx["program"]["id"], ctx["student"]["id"], fee["id"],
                settle_fee_payload(fee["amount_cents"]), admin_headers,
            ),
            200,
        )
        assert settled["status"] == "SETTLED"
        student = refresh_student(ctx["program"]["id"], ctx["student"]["id"])
        assert student["financial_posture"] == "CLEAR"
        assert student["family_agreement_status"] == "SIGNED"


def test_posture_derivation_excludes_settled_fees(api, admin_headers,
                                                  tech_headers):
    """PRD §3.2: "The `outstanding_balance_cents` is the sum, across the student's fee rows in `ASSESSED` or `APPEALED` status, of `amount_cents` minus `waived_cents` minus `paid_cents`."

    A SETTLED 10000-cent fee contributes nothing: after a second ASSESSED fee
    of 55000 (SCREEN on a grade-A unit), outstanding is exactly 55000 and the
    posture is SUSPENDED — not 65000.

    Design: Corner/calculations/financial_posture_excludes_terminal_fees
    """
    program, fleet, assets = setup_program_fleet_assets(n_assets=2)
    student = enroll_signed_student(program["id"], "SIS-PS-1", "Posture Student")
    ctx = {
        "program": program, "fleet": fleet, "asset": assets[0],
        "student": student,
        "assignment": create_assignment_for(program["id"], student["id"],
                                            assets[0]["id"]),
    }
    # First fee: COSMETIC on grade A -> 100000 * 0.10 * 1.00 = 10000.
    report1 = file_damage_report(ctx, "COSMETIC", "A")
    submit_damage_report(ctx, report1["id"])
    confirm_damage_report(ctx, report1["id"])
    fee1 = list_fees(ctx)[0]
    assert fee1["amount_cents"] == 10000
    settled = validate_success(
        api.settle_fee(program["id"], student["id"], fee1["id"],
                       settle_fee_payload(10000), admin_headers),
        200,
    )
    assert settled["status"] == "SETTLED"

    # Return the first unit on time and undamaged; check out the second.
    validate_success(
        api.return_assignment(program["id"], student["id"],
                              ctx["assignment"]["id"],
                              return_assignment_payload(return_condition_grade="A"),
                              tech_headers),
        200,
    )
    ctx["asset"] = assets[1]
    ctx["assignment"] = create_assignment_for(program["id"], student["id"],
                                              assets[1]["id"])
    # Second fee: SCREEN on grade A -> 100000 * 0.55 * 1.00 = 55000.
    report2 = file_damage_report(ctx, "SCREEN", "B")
    submit_damage_report(ctx, report2["id"])
    confirm_damage_report(ctx, report2["id"])

    student = refresh_student(program["id"], student["id"])
    assert student["outstanding_balance_cents"] == 55000, (
        f"SETTLED fee must be excluded: expected 55000, "
        f"got {student['outstanding_balance_cents']}"
    )
    assert student["financial_posture"] == "SUSPENDED"
