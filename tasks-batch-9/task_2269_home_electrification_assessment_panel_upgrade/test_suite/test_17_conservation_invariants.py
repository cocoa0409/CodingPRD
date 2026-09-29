"""Two conserved quantities followed through their compensating actions, checkpoint by checkpoint."""

from test_helpers import (
    ClawbackReason,
    DEFAULT_LOW_TIER_CAP_CENTS,
    IncomeTier,
    InspectionStatus,
    InspectionType,
    MEASURE_HP_HVAC,
    ProjectStatus,
    REVIEWER_HEADERS,
    ReleaseReason,
    ReservationStatus,
    VerificationStatus,
    assert_household_cap,
    assert_household_cap_conserved,
    assert_program_budget_conserved,
    assert_program_buckets,
    build_assessment_measure,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_project_measure,
    build_world,
    create_approved_assessment,
    create_project,
    create_verified_household,
    pay_project,
    project_reservation,
    read_clawback_actions,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    read_reservation,
    record_result,
    reserve_project,
    review_project,
    schedule_inspection,
    set_clock,
    submit_project,
    sweep,
    validate_paginated,
)


def _reserved_amount_sum(api, program_id, status):
    """The supporting identity's right-hand side, read from the reservation list."""
    rows, _meta = validate_paginated(
        api.list_reservations(REVIEWER_HEADERS, {"program_id": program_id, "status": status})
    )
    return sum(row["reserved_amount_cents"] for row in rows)


def _record_spot_failure(api, inspection_id, inspector_id):
    """A failing SPOT result against a project that has already been paid."""
    return record_result(
        api,
        inspection_id,
        inspector_id,
        build_fail_result_payload(
            deficiency_count=3,
            deficiency_severity_max=5,
            notes="Equipment removed after payment",
        ),
    )


def _reserve_for(api, world, verified):
    """Carry a second household of the same program through to a RESERVED project."""
    assessment = create_approved_assessment(
        api,
        verified["household"]["id"],
        world["contractor_id"],
        [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
    )
    project = create_project(
        api,
        verified["household"]["id"],
        assessment["id"],
        world["contractor_id"],
        verified["income_verification"]["id"],
        [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
    )
    submit_project(api, project["id"], world["contractor_id"])
    review_project(api, project["id"])
    reserve_project(api, project["id"], world["program_id"])
    return read_project(api, project["id"])


class TestProgramAppropriationConserved:
    def test_the_appropriation_returns_to_its_pre_reservation_value_after_a_clawback(self, api):
        """800000 reserved, 700000 disbursed, 100000 released at commit, all 800000 back at the end.

        PRD §2.7: "After every mutation that touches any of these, the invariant holds that
        `budget_total_cents` equals the sum of `budget_available_cents`,
        `budget_reserved_cents`, and `budget_committed_cents`. Further,
        `budget_reserved_cents` equals the sum of `reserved_amount_cents` over that program's
        reservations in status `RESERVED`, and `budget_committed_cents` equals the same sum
        over its reservations in status `COMMITTED`. A reserve followed by its compensating
        action — expiry, failed-reinspection release, or post-payment clawback — must return
        `budget_available_cents` to exactly its pre-reservation value, with zero drift."

        PRD §3.9: "The disbursed amount is the smaller of that basis and the reservation's
        `initial_reserved_amount_cents`, and the release difference is the initial reserved
        amount less the disbursed amount — never negative, because the disbursement is capped
        by the initial reservation."

        PRD §3.9: "Caused by that reservation clawback, the program's
        `budget_committed_cents` is debited by the reservation's `reserved_amount_cents`, its
        `budget_available_cents` credited by the same amount, and its
        `budget_clawed_back_cents` incremented by the same amount, with the program's version
        incremented — note that the clawed-back counter grows while the three conserved
        buckets rebalance among themselves."

        Design: Difficulty/compensating_invariant/program_appropriation_conserved_across_reserve_pay_and_clawback
        """
        world = build_world(
            api,
            stage="verified",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        project_id = world["project_id"]
        program_id = world["program_id"]
        assert world["project"]["final_total_incentive_cents"] == 700000

        #  Checkpoint 1 — the encumbrance as it stood at reservation time; neither the
        #  installation report nor the passing inspection moves money.
        reserved_program = read_program(api, program_id)
        assert_program_budget_conserved(reserved_program)
        assert_program_buckets(
            reserved_program, available=49200000, reserved=800000, committed=0, clawed_back=0
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 800000
        assert _reserved_amount_sum(api, program_id, ReservationStatus.COMMITTED) == 0

        #  Checkpoint 2 — payment reconciles 800000 down to 700000 and the 100000 release
        #  difference goes back to available rather than evaporating.
        paid = pay_project(api, project_id, payment_reference="ACH-0001")
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 700000
        paid_program = read_program(api, program_id)
        assert_program_budget_conserved(paid_program)
        assert_program_buckets(
            paid_program, available=49300000, reserved=0, committed=700000, clawed_back=0
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.COMMITTED) == 700000
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 0

        spot = schedule_inspection(
            api,
            project_id,
            world["inspector_id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T10:00:00Z",
        )
        failed = _record_spot_failure(api, spot["id"], world["inspector_id"])
        assert failed["status"] == InspectionStatus.FAILED

        #  Checkpoint 3 — the compensating action lands the appropriation exactly where it
        #  started, and the clawed-back tally sits outside the identity.
        final_program = read_program(api, program_id)
        assert_program_budget_conserved(final_program)
        assert_program_buckets(
            final_program, available=50000000, reserved=0, committed=0, clawed_back=700000
        )
        actions = read_clawback_actions(api, project_id=project_id)
        assert len(actions) == 1
        assert actions[0]["reason"] == ClawbackReason.POST_PAYMENT_INSPECTION_FAILURE
        assert actions[0]["disbursed_before_cents"] == 700000
        assert actions[0]["recovered_cents"] == 700000
        assert actions[0]["program_budget_available_after_cents"] == 50000000
        assert final_program["budget_clawed_back_cents"] == sum(
            action["recovered_cents"] for action in actions
        )

        #  Nothing of this program is reserved or committed any longer.
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 0
        assert _reserved_amount_sum(api, program_id, ReservationStatus.COMMITTED) == 0
        reservation = read_reservation(api, world["reservation_id"])
        assert reservation["status"] == ReservationStatus.CLAWED_BACK
        assert reservation["release_reason"] == ReleaseReason.CLAWBACK
        clawed_project = read_project(api, project_id)
        assert clawed_project["status"] == ProjectStatus.CLAWED_BACK
        assert clawed_project["disbursed_amount_cents"] == 0
        assert (
            read_project_measures(api, project_id)[0]["verification_status"]
            == VerificationStatus.CLAWED_BACK
        )

    def test_the_identity_holds_with_a_second_reservation_still_live_alongside(self, api):
        """Only the clawed-back project's 700000 comes home; the untouched 800000 stays reserved.

        PRD §2.7: "Further, `budget_reserved_cents` equals the sum of `reserved_amount_cents`
        over that program's reservations in status `RESERVED`, and `budget_committed_cents`
        equals the same sum over its reservations in status `COMMITTED`."

        PRD §2.7: "The fourth field, `budget_clawed_back_cents`, is deliberately **not** one
        of the conserved buckets: it is a cumulative counter that equals the sum of
        `recovered_cents` over the clawback actions recorded against that program's projects.
        Money recovered in a clawback flows back into `budget_available_cents`; the counter
        merely records that it happened."

        PRD §3.9: "On the program side, `budget_reserved_cents` is debited by the
        reservation's `initial_reserved_amount_cents`, `budget_committed_cents` is credited by
        the disbursed amount, and `budget_available_cents` is credited by the release
        difference, with the program's version incremented."

        Design: Difficulty/compensating_invariant/program_appropriation_conserved_across_reserve_pay_and_clawback
        """
        world = build_world(
            api,
            stage="verified",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        program_id = world["program_id"]
        project_id = world["project_id"]

        #  A second dwelling of the same program holds its own untouched 800000.
        neighbour = create_verified_household(
            api,
            program_id,
            applicant_name="Ines Marchetti",
            email="ines@example.com",
            service_address_line1="88 Copper Way",
        )
        neighbour_project = _reserve_for(api, world, neighbour)
        assert neighbour_project["status"] == ProjectStatus.RESERVED

        both_reserved = read_program(api, program_id)
        assert_program_budget_conserved(both_reserved)
        assert_program_buckets(both_reserved, available=48400000, reserved=1600000, committed=0)
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 1600000

        pay_project(api, project_id)
        after_payment = read_program(api, program_id)
        assert_program_budget_conserved(after_payment)
        assert_program_buckets(
            after_payment, available=48500000, reserved=800000, committed=700000, clawed_back=0
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 800000
        assert _reserved_amount_sum(api, program_id, ReservationStatus.COMMITTED) == 700000

        spot = schedule_inspection(
            api,
            project_id,
            world["inspector_id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T10:00:00Z",
        )
        _record_spot_failure(api, spot["id"], world["inspector_id"])

        #  The recovery restores exactly the reconciled 700000, so the neighbour's
        #  encumbrance is untouched and the identity still closes.
        after_clawback = read_program(api, program_id)
        assert_program_budget_conserved(after_clawback)
        assert_program_buckets(
            after_clawback, available=49200000, reserved=800000, committed=0, clawed_back=700000
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 800000
        assert _reserved_amount_sum(api, program_id, ReservationStatus.COMMITTED) == 0
        assert (
            project_reservation(api, neighbour_project["id"])["status"]
            == ReservationStatus.RESERVED
        )
        assert read_project(api, neighbour_project["id"])["status"] == ProjectStatus.RESERVED
        assert after_clawback["budget_clawed_back_cents"] == 700000


class TestHouseholdEntitlementConserved:
    def test_the_expiry_sweep_restores_the_lifetime_headroom_with_zero_drift(self, api):
        """No cash moves, yet the household must end exactly where it began.

        PRD §2.7: "A household's lifetime entitlement is a separate conserved quantity with
        the same shape. After every mutation that touches it, `rebate_cap_cents` equals
        `lifetime_cap_remaining_cents` plus `encumbered_cents`, and `encumbered_cents` equals
        the sum of `reserved_amount_cents` over reservations whose project belongs to that
        household and whose status is `RESERVED` or `COMMITTED`. Reservations in `EXPIRED`,
        `RELEASED`, or `CLAWED_BACK` are excluded from the encumbrance."

        PRD §3.6: "Each due reservation moves `RESERVED → EXPIRED` with `release_reason` set
        to `EXPIRY`, and that transition drags a chain of cascade hops behind it: the
        program's `budget_reserved_cents` is debited and its `budget_available_cents` credited
        by the reservation's `reserved_amount_cents` with the program's version incremented;
        the household's `encumbered_cents` is debited and its `lifetime_cap_remaining_cents`
        credited by the same amount with the household's version incremented"

        PRD §3.6: "The sweep reports a `program_id`, a `swept_reservation_count`, a
        `released_cents` total summing the released reserved amounts, an `expired_project_ids`
        array in processing order, and the resulting `program_budget_available_cents`."

        Design: Difficulty/compensating_invariant/household_lifetime_entitlement_conserved_across_reserve_and_expiry
        """
        world = build_world(api, stage="assessment", catalog=[build_hvac_heat_pump_payload()])
        household_id = world["household_id"]

        #  Checkpoint 1 — the entitlement immediately after verification.
        intake = read_household(api, household_id)
        assert_household_cap_conserved(intake)
        assert_household_cap(
            intake,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert intake["income_tier"] == IncomeTier.LOW

        project = create_project(
            api,
            household_id,
            world["assessment_id"],
            world["contractor_id"],
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        submit_project(api, project["id"], world["contractor_id"])
        review_project(api, project["id"])
        reservation = reserve_project(api, project["id"], world["program_id"])
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["expires_at"].startswith("2026-11-29T00:00:00")

        #  Checkpoint 2 — the encumbrance equals the household's single live reservation.
        encumbered = read_household(api, household_id)
        assert_household_cap_conserved(encumbered)
        assert_household_cap(
            encumbered, remaining=600000, encumbered=800000, cap=DEFAULT_LOW_TIER_CAP_CENTS
        )
        assert (
            _reserved_amount_sum(api, world["program_id"], ReservationStatus.RESERVED)
            == encumbered["encumbered_cents"]
        )

        #  One day past expiry the sweep is unambiguously due.
        set_clock(api, "2026-11-30T00:00:00Z")
        report = sweep(api, world["program_id"])
        assert report["swept_reservation_count"] == 1
        assert report["released_cents"] == 800000
        assert report["expired_project_ids"] == [project["id"]]
        assert report["program_budget_available_cents"] == 50000000

        #  Checkpoint 3 — the entitlement is fully restored, and the tier was never touched.
        restored = read_household(api, household_id)
        assert_household_cap_conserved(restored)
        assert_household_cap(
            restored,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert restored["income_tier"] == IncomeTier.LOW
        assert _reserved_amount_sum(api, world["program_id"], ReservationStatus.RESERVED) == 0
        assert _reserved_amount_sum(api, world["program_id"], ReservationStatus.COMMITTED) == 0

        #  Both records are terminal, so this 800000 can never be re-encumbered here.
        expired_reservation = read_reservation(api, reservation["id"])
        assert expired_reservation["status"] == ReservationStatus.EXPIRED
        assert expired_reservation["release_reason"] == ReleaseReason.EXPIRY
        assert read_project(api, project["id"])["status"] == ProjectStatus.EXPIRED

    def test_two_reservations_of_one_household_unwind_one_at_a_time(self, api):
        """Partial restoration keeps the identity exact at every intermediate step.

        PRD §2.7: "After every mutation that touches it, `rebate_cap_cents` equals
        `lifetime_cap_remaining_cents` plus `encumbered_cents`, and `encumbered_cents` equals
        the sum of `reserved_amount_cents` over reservations whose project belongs to that
        household and whose status is `RESERVED` or `COMMITTED`."

        PRD §3.5: "*Stage 3* applies the household lifetime cap, and only after Stage 2 has
        settled. The available ceiling is the household's `lifetime_cap_remaining_cents` plus
        whatever this project has already encumbered for itself — that is, plus this project's
        own reservation's `reserved_amount_cents` when a reservation in status `RESERVED`
        exists, and plus 0 when none does."

        PRD §3.6: "A `ProgramAdmin` runs the expiry sweep for a program, which collects that
        program's reservations in status `RESERVED` whose `expires_at` is less than or equal
        to the logical clock — the comparison is inclusive, so a reservation expiring exactly
        now does expire — and processes them in `expires_at` ascending order and then
        `created_at` ascending order."

        Design: Difficulty/compensating_invariant/household_lifetime_entitlement_conserved_across_reserve_and_expiry
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        household_id = world["household_id"]
        program_id = world["program_id"]
        first_reservation = world["reservation"]
        assert first_reservation["reserved_amount_cents"] == 800000
        assert first_reservation["expires_at"].startswith("2026-11-29T00:00:00")

        #  A day later the same household opens a second project. Stage 3 caps it at the
        #  600000 of headroom that is left.
        set_clock(api, "2026-08-02T00:00:00Z")
        second = create_project(
            api,
            household_id,
            world["assessment_id"],
            world["contractor_id"],
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        assert second["provisional_total_incentive_cents"] == 600000
        submit_project(api, second["id"], world["contractor_id"])
        review_project(api, second["id"])
        second_reservation = reserve_project(api, second["id"], program_id)
        assert second_reservation["reserved_amount_cents"] == 600000
        assert second_reservation["expires_at"].startswith("2026-11-30T00:00:00")

        #  The entitlement is now fully encumbered, and the identity is exact.
        full = read_household(api, household_id)
        assert_household_cap_conserved(full)
        assert_household_cap(
            full, remaining=0, encumbered=DEFAULT_LOW_TIER_CAP_CENTS, cap=DEFAULT_LOW_TIER_CAP_CENTS
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 1400000
        assert_program_buckets(
            read_program(api, program_id), available=48600000, reserved=1400000, committed=0
        )

        #  At the earlier expiry only the first reservation is due.
        set_clock(api, "2026-11-29T00:00:00Z")
        first_report = sweep(api, program_id)
        assert first_report["swept_reservation_count"] == 1
        assert first_report["released_cents"] == 800000
        assert first_report["expired_project_ids"] == [world["project_id"]]
        half = read_household(api, household_id)
        assert_household_cap_conserved(half)
        assert_household_cap(
            half, remaining=800000, encumbered=600000, cap=DEFAULT_LOW_TIER_CAP_CENTS
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 600000
        assert read_reservation(api, second_reservation["id"])["status"] == ReservationStatus.RESERVED
        assert read_project(api, second["id"])["status"] == ProjectStatus.RESERVED

        #  One day later the second follows, and the household is whole again.
        set_clock(api, "2026-11-30T00:00:00Z")
        second_report = sweep(api, program_id)
        assert second_report["swept_reservation_count"] == 1
        assert second_report["released_cents"] == 600000
        assert second_report["expired_project_ids"] == [second["id"]]
        assert second_report["program_budget_available_cents"] == 50000000
        whole = read_household(api, household_id)
        assert_household_cap_conserved(whole)
        assert_household_cap(
            whole,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert _reserved_amount_sum(api, program_id, ReservationStatus.RESERVED) == 0
        assert read_reservation(api, first_reservation["id"])["status"] == ReservationStatus.EXPIRED
        assert read_reservation(api, second_reservation["id"])["status"] == ReservationStatus.EXPIRED
