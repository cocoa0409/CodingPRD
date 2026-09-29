"""Three cascade chains: the failed-reinspection release, the expiry sweep, and the anchor strand."""

from test_helpers import (
    ApiErrorId,
    ClawbackReason,
    ContractorStatus,
    DEFAULT_LOW_TIER_CAP_CENTS,
    InspectionStatus,
    InstallStatus,
    LineRejectionReason,
    MEASURE_HPWH,
    MEASURE_HP_HVAC,
    MEASURE_PANEL_200A,
    ProjectStatus,
    REVIEWER_HEADERS,
    ReleaseReason,
    ReservationStatus,
    SuspensionReason,
    VerificationStatus,
    assert_household_cap,
    assert_measure_codes_in_order,
    assert_program_buckets,
    build_assessment_measure,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_panel_200a_payload,
    build_pass_result_payload,
    build_project_measure,
    build_water_heater_payload,
    build_world,
    create_approved_assessment,
    create_inspector,
    create_project,
    create_verified_household,
    find_measure_line,
    open_remediation,
    project_reservation,
    read_clawback_actions,
    read_contractor,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    record_result,
    schedule_inspection,
    set_clock,
    suspend_contractor,
    sweep,
    validate_error,
    validate_paginated,
)


class TestFailedReinspectionReleaseCascade:
    def test_the_failure_at_the_remediation_cap_unwinds_the_reservation_ledgers_and_audit_row(
        self, api
    ):
        """Four hops: FAILED_FINAL, then RELEASED, then both ledgers, then the audit row.

        PRD §3.8: "A `POST_INSTALL` failure on a project whose `remediation_count` has
        already reached the program's `max_remediations_per_project` is the end of the
        road: the project moves `INSTALLED → FAILED_FINAL`, which is terminal, and the
        money unwinds. The project's reservation moves `RESERVED → RELEASED` with
        `release_reason` set to `FAILED_REINSPECTION`."

        PRD §3.8: "Caused by that release, the program's `budget_reserved_cents` is
        debited and its `budget_available_cents` credited by the reservation's
        `reserved_amount_cents` with the program's version incremented, and the
        household's `lifetime_cap_remaining_cents` is credited and its `encumbered_cents`
        debited by the same amount with the household's version incremented."

        PRD §3.8: "Also caused by that release, a clawback action is appended with
        `reason` `FAILED_REINSPECTION`, `recovered_cents` of 0 — nothing was ever paid, so
        nothing is recovered from the household — and `released_reservation_cents` equal
        to the released amount. Every measure line of the project has `install_status`
        set to `VOID` and `verification_status` set to `REJECTED`."

        PRD §3.9: "Besides its `reason`, it names the `project_id` the recovery applies
        to, the `reservation_id` whose funds were released or recovered, and the
        `triggered_by_inspection_id` of the failed inspection that caused it."

        PRD §3.8: "Scheduling a `POST_INSTALL` inspection for a project sitting in
        `REMEDIATION` also returns that project `REMEDIATION → INSTALLED` for
        re-inspection, creating the re-inspection in `SCHEDULED` and incrementing the
        project's version."

        Design: Difficulty/transitive_cascade/failed_reinspection_release_cascade_depth_four
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        inspector_id = world["inspector_id"]
        reservation_id = world["reservation_id"]

        assert world["reservation"]["reserved_amount_cents"] == 800000
        assert_program_buckets(read_program(api, program_id), available=49200000, reserved=800000)
        assert_household_cap(
            read_household(api, household_id), remaining=600000, encumbered=800000
        )

        #  One failure, one remediation cycle: the project is back at INSTALLED with
        #  remediation_count at the program's limit of 1.
        first = record_result(
            api,
            world["inspection_id"],
            inspector_id,
            build_fail_result_payload(
                [MEASURE_HP_HVAC], deficiency_count=1, deficiency_severity_max=4
            ),
        )
        assert first["status"] == InspectionStatus.FAILED
        assert read_project(api, project_id)["status"] == ProjectStatus.INSPECTION_FAILED
        remediated = open_remediation(
            api, project_id, contractor_id, remediation_notes="Commissioning repeated"
        )
        assert remediated["remediation_count"] == 1
        second_inspection = schedule_inspection(
            api,
            project_id,
            inspector_id,
            scheduled_start="2026-08-25T09:00:00Z",
            scheduled_end="2026-08-25T11:00:00Z",
        )
        assert second_inspection["status"] == InspectionStatus.SCHEDULED
        assert read_project(api, project_id)["status"] == ProjectStatus.INSTALLED

        second = record_result(
            api,
            second_inspection["id"],
            inspector_id,
            build_fail_result_payload(
                [MEASURE_HP_HVAC],
                deficiency_count=1,
                deficiency_severity_max=5,
                notes="Deficiency not corrected",
            ),
        )
        assert second["status"] == InspectionStatus.FAILED

        #  Hop 1: the project takes the terminal edge rather than the INSPECTION_FAILED one.
        failed_final = read_project(api, project_id)
        assert failed_final["status"] == ProjectStatus.FAILED_FINAL
        assert failed_final["remediation_count"] == 1

        #  Hop 2 exists only because hop 1 happened.
        reservation = project_reservation(api, project_id)
        assert reservation["id"] == reservation_id
        assert reservation["status"] == ReservationStatus.RELEASED
        assert reservation["release_reason"] == ReleaseReason.FAILED_REINSPECTION
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["initial_reserved_amount_cents"] == 800000
        assert reservation["committed_at"] is None

        #  Hop 3 exists only because hop 2 released the encumbrance.
        program = read_program(api, program_id)
        assert_program_buckets(
            program, available=50000000, reserved=0, committed=0, clawed_back=0
        )
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  Hop 4 exists only because hop 3 restored those two balances, which it records.
        actions = read_clawback_actions(api, project_id=project_id)
        assert len(actions) == 1
        action = actions[0]
        assert action["reason"] == ClawbackReason.FAILED_REINSPECTION
        assert action["project_id"] == project_id
        assert action["reservation_id"] == reservation_id
        assert action["triggered_by_inspection_id"] == second_inspection["id"]
        assert action["disbursed_before_cents"] == 0
        assert action["recovered_cents"] == 0
        assert action["released_reservation_cents"] == 800000
        assert action["program_budget_available_after_cents"] == 50000000
        assert action["household_cap_remaining_after_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        assert action["recorded_by_user_id"] == inspector_id

        #  Both dimensions of every line are driven to their terminal values.
        lines = read_project_measures(api, project_id)
        assert_measure_codes_in_order(lines, [MEASURE_HP_HVAC])
        assert lines[0]["install_status"] == InstallStatus.VOID
        assert lines[0]["verification_status"] == VerificationStatus.REJECTED

    def test_the_first_failure_releases_nothing_and_the_release_is_never_swept_twice(self, api):
        """Hops two through four wait for the remediation cap, and fire exactly once.

        PRD §3.8: "A `POST_INSTALL` failure on a project whose `remediation_count` is
        still strictly below the program's `max_remediations_per_project` moves the
        project `INSTALLED → INSPECTION_FAILED` and unrolls a three-hop cascade."

        PRD §3.9: "The distinction between the two reasons is exactly the distinction
        between releasing and recovering: `FAILED_REINSPECTION` releases a
        still-reserved amount and recovers nothing from the household, while
        `POST_PAYMENT_INSPECTION_FAILURE` recovers an amount that had already been
        disbursed."

        PRD §3.9: "Clawback actions can be listed filtered by `project_id`,
        `reservation_id`, `triggered_by_inspection_id`, and `reason`."

        PRD §3.6: "Reservations in `COMMITTED`, `RELEASED`, `EXPIRED`, or `CLAWED_BACK`
        are skipped, and a `SUSPENDED` or `CLOSED` program is still swept."

        PRD §2.10: "**State gate.** The source entity is in a state from which the
        requested transition is declared, and the enclosing program is `OPEN` where the
        transition requires it. This is the umbrella rung, and an entity in a terminal
        state always fails here."

        Design: Difficulty/transitive_cascade/failed_reinspection_release_cascade_depth_four
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        inspector_id = world["inspector_id"]
        first_inspection_id = world["inspection_id"]

        record_result(
            api,
            first_inspection_id,
            inspector_id,
            build_fail_result_payload(
                [MEASURE_HP_HVAC], deficiency_count=1, deficiency_severity_max=4
            ),
        )

        #  The recoverable failure stops at hop three of its own chain: no release, no
        #  ledger movement, no audit row.
        assert read_project(api, project_id)["status"] == ProjectStatus.INSPECTION_FAILED
        assert project_reservation(api, project_id)["status"] == ReservationStatus.RESERVED
        assert_program_buckets(read_program(api, program_id), available=49200000, reserved=800000)
        assert_household_cap(
            read_household(api, household_id), remaining=600000, encumbered=800000
        )
        _empty, empty_meta = validate_paginated(
            api.list_clawback_actions(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert empty_meta["total_count"] == 0

        open_remediation(api, project_id, contractor_id)
        second_inspection = schedule_inspection(
            api,
            project_id,
            inspector_id,
            scheduled_start="2026-08-25T09:00:00Z",
            scheduled_end="2026-08-25T11:00:00Z",
        )
        record_result(
            api,
            second_inspection["id"],
            inspector_id,
            build_fail_result_payload(
                [MEASURE_HP_HVAC], deficiency_count=1, deficiency_severity_max=5
            ),
        )
        assert read_project(api, project_id)["status"] == ProjectStatus.FAILED_FINAL

        #  The single audit row is filed against the inspection that actually caused it.
        by_second, second_meta = validate_paginated(
            api.list_clawback_actions(
                REVIEWER_HEADERS, {"triggered_by_inspection_id": second_inspection["id"]}
            )
        )
        assert second_meta["total_count"] == 1
        assert by_second[0]["released_reservation_cents"] == 800000
        _by_first, first_meta = validate_paginated(
            api.list_clawback_actions(
                REVIEWER_HEADERS, {"triggered_by_inspection_id": first_inspection_id}
            )
        )
        assert first_meta["total_count"] == 0
        by_reason, reason_meta = validate_paginated(
            api.list_clawback_actions(
                REVIEWER_HEADERS, {"reason": ClawbackReason.FAILED_REINSPECTION}
            )
        )
        assert reason_meta["total_count"] == 1
        assert by_reason[0]["id"] == by_second[0]["id"]

        #  A terminal project has no remediation edge left.
        validate_error(
            api.open_remediation(project_id, world["contractor_headers"]),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        #  And the released reservation is skipped by the sweep, so the 800000 cannot be
        #  handed back to the appropriation a second time.
        set_clock(api, "2026-12-01T00:00:00Z")
        swept = sweep(api, program_id)
        assert swept["swept_reservation_count"] == 0
        assert swept["released_cents"] == 0
        assert swept["expired_project_ids"] == []
        assert swept["program_budget_available_cents"] == 50000000
        assert_program_buckets(read_program(api, program_id), available=50000000, reserved=0)
        assert len(read_clawback_actions(api, project_id=project_id)) == 1


class TestSweepExpiryCascade:
    def test_the_clock_alone_expires_the_reservation_voids_the_line_and_cancels_the_visit(
        self, api
    ):
        """Nobody touched the project: the sweep reached it through its reservation.

        PRD §3.6: "A `ProgramAdmin` runs the expiry sweep for a program, which collects
        that program's reservations in status `RESERVED` whose `expires_at` is less than
        or equal to the logical clock — the comparison is inclusive, so a reservation
        expiring exactly now does expire — and processes them in `expires_at` ascending
        order and then `created_at` ascending order."

        PRD §3.6: "Each due reservation moves `RESERVED → EXPIRED` with `release_reason`
        set to `EXPIRY`, and that transition drags a chain of cascade hops behind it: the
        program's `budget_reserved_cents` is debited and its `budget_available_cents`
        credited by the reservation's `reserved_amount_cents` with the program's version
        incremented; the household's `encumbered_cents` is debited and its
        `lifetime_cap_remaining_cents` credited by the same amount with the household's
        version incremented; the project moves to `EXPIRED` from either `RESERVED` or
        `CONTRACTOR_HOLD`; caused by that project transition, every measure line of the
        project has `install_status` set to `VOID`; and, also caused by it, every
        inspection of the project still in `SCHEDULED` is moved to `CANCELLED`."

        PRD §3.6: "The sweep reports a `program_id`, a `swept_reservation_count`, a
        `released_cents` total summing the released reserved amounts, an
        `expired_project_ids` array in processing order, and the resulting
        `program_budget_available_cents`."

        PRD §3.8: "The occupied windows are every inspection of the **same** inspector —
        across every program and every project, since the candidate project is irrelevant
        — whose status is `SCHEDULED`, `PASSED`, `CONDITIONAL_PASS`, or `FAILED`; a
        `CANCELLED` inspection frees its slot."

        Design: Difficulty/transitive_cascade/sweep_expiry_cascade_depth_three_voids_measures_and_cancels_inspection
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]

        #  Reserved at 2026-08-01T00:00:00Z with a 120-day term.
        assert world["reservation"]["reserved_amount_cents"] == 800000
        assert world["reservation"]["expires_at"].startswith("2026-11-29T00:00:00")

        inspector = create_inspector(api, program_id, inspector_name="Lena Fuchs")
        inspection = schedule_inspection(
            api,
            project_id,
            inspector["id"],
            scheduled_start="2026-12-01T09:00:00Z",
            scheduled_end="2026-12-01T11:00:00Z",
        )
        assert inspection["status"] == InspectionStatus.SCHEDULED

        #  The clock lands exactly on expires_at, which the sweep treats inclusively.
        set_clock(api, "2026-11-29T00:00:00Z")
        result = sweep(api, program_id)
        assert result["program_id"] == program_id
        assert result["swept_reservation_count"] == 1
        assert result["released_cents"] == 800000
        assert result["expired_project_ids"] == [project_id]
        assert result["program_budget_available_cents"] == 50000000

        #  Hop 1 and its two ledger restorations.
        reservation = project_reservation(api, project_id)
        assert reservation["status"] == ReservationStatus.EXPIRED
        assert reservation["release_reason"] == ReleaseReason.EXPIRY
        assert reservation["reserved_amount_cents"] == 800000
        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0, clawed_back=0
        )
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  Hop 2 exists only because hop 1 expired that reservation.
        assert read_project(api, project_id)["status"] == ProjectStatus.EXPIRED

        #  Hop 3 exists only because hop 2 moved the project, and it reaches a window
        #  that is still two days in the future.
        lines = read_project_measures(api, project_id)
        assert lines[0]["install_status"] == InstallStatus.VOID
        assert lines[0]["verification_status"] == VerificationStatus.PENDING
        cancelled = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": project_id})
        )[0][0]
        assert cancelled["id"] == inspection["id"]
        assert cancelled["status"] == InspectionStatus.CANCELLED

        #  The cancelled visit no longer occupies the inspector, so the identical window
        #  is bookable again for another project of the same inspector.
        other = create_verified_household(
            api,
            program_id,
            applicant_name="Sol Okonkwo",
            email="sol@example.com",
            service_address_line1="332 Ledger St",
        )
        other_assessment = create_approved_assessment(
            api,
            other["household"]["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            assessed_panel_amps=200,
        )
        other_project = create_project(
            api,
            other["household"]["id"],
            other_assessment["id"],
            contractor_id,
            other["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        rebooked = schedule_inspection(
            api,
            other_project["id"],
            inspector["id"],
            scheduled_start="2026-12-01T09:00:00Z",
            scheduled_end="2026-12-01T11:00:00Z",
        )
        assert rebooked["status"] == InspectionStatus.SCHEDULED
        assert rebooked["inspector_id"] == inspector["id"]

    def test_the_same_chain_runs_when_the_project_is_parked_in_contractor_hold(self, api):
        """The hold state is the other declared source of the project's expiry edge.

        PRD §3.3: "That transition cascades: every other rebate project of this
        contractor sitting in `RESERVED` moves `RESERVED → CONTRACTOR_HOLD`, and each of
        those projects has its own version incremented."

        PRD §3.6: "Each due reservation moves `RESERVED → EXPIRED` with `release_reason`
        set to `EXPIRY`, and that transition drags a chain of cascade hops behind it: the
        program's `budget_reserved_cents` is debited and its `budget_available_cents`
        credited by the reservation's `reserved_amount_cents` with the program's version
        incremented; the household's `encumbered_cents` is debited and its
        `lifetime_cap_remaining_cents` credited by the same amount with the household's
        version incremented; the project moves to `EXPIRED` from either `RESERVED` or
        `CONTRACTOR_HOLD`; caused by that project transition, every measure line of the
        project has `install_status` set to `VOID`; and, also caused by it, every
        inspection of the project still in `SCHEDULED` is moved to `CANCELLED`."

        PRD §3.6: "suspension does **not** pause any clock, so existing reservations keep
        their `expires_at` exactly as it stood"

        Design: Difficulty/transitive_cascade/sweep_expiry_cascade_depth_three_voids_measures_and_cancels_inspection
        """
        world = build_world(
            api,
            stage="reserved",
            catalog=[build_hvac_heat_pump_payload(), build_water_heater_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
            ],
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        assert world["reservation"]["reserved_amount_cents"] == 975000

        inspector = create_inspector(api, program_id, inspector_name="Lena Fuchs")
        inspection = schedule_inspection(api, project_id, inspector["id"])

        #  The suspension parks the project without touching its term.
        suspended = suspend_contractor(api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION)
        assert suspended["status"] == ContractorStatus.SUSPENDED
        assert read_project(api, project_id)["status"] == ProjectStatus.CONTRACTOR_HOLD
        assert project_reservation(api, project_id)["expires_at"].startswith("2026-11-29T00:00:00")

        set_clock(api, "2026-11-29T00:00:00Z")
        result = sweep(api, program_id)
        assert result["swept_reservation_count"] == 1
        assert result["released_cents"] == 975000
        assert result["expired_project_ids"] == [project_id]

        #  The chain is identical, only its hop-2 source state differs.
        reservation = project_reservation(api, project_id)
        assert reservation["status"] == ReservationStatus.EXPIRED
        assert reservation["release_reason"] == ReleaseReason.EXPIRY
        assert read_project(api, project_id)["status"] == ProjectStatus.EXPIRED
        lines = read_project_measures(api, project_id)
        assert_measure_codes_in_order(lines, [MEASURE_HP_HVAC, MEASURE_HPWH])
        assert [line["install_status"] for line in lines] == [
            InstallStatus.VOID,
            InstallStatus.VOID,
        ]
        cancelled = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": project_id})
        )[0][0]
        assert cancelled["id"] == inspection["id"]
        assert cancelled["status"] == InspectionStatus.CANCELLED
        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0, clawed_back=0
        )
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  Reinstatement has nothing to pull back: the contractor is still suspended and
        #  the project left the hold state by expiring, not by returning.
        assert read_contractor(api, contractor_id)["status"] == ContractorStatus.SUSPENDED


class TestAnchorRejectionCascade:
    def test_rejecting_the_only_anchor_strands_the_panel_line_and_zeroes_the_final_total(
        self, api
    ):
        """The inspector named one line; two lines end rejected for two different reasons.

        PRD §3.8: "First, every measure line named in `rejected_measure_codes` moves
        `verification_status` from `PENDING` to `REJECTED` with `rejection_reason` set to
        `INSPECTION_DEFICIENCY` and its `final_incentive_cents` set to 0."

        PRD §3.8: "Second — and caused by that first hop, not by the request — every
        measure line whose `pinned_is_panel_upgrade` is true and whose qualifying
        appliance anchor line has now become `REJECTED` also moves `verification_status`
        from `PENDING` to `REJECTED`, this time with `rejection_reason` set to
        `ANCHOR_REJECTED`."

        PRD §3.8: "Third — and caused by the second hop — the project's
        `final_total_incentive_cents` is recomputed by the final allocation over only the
        lines still eligible for verification, so the project total drops by whatever the
        rejected lines had been allocated."

        PRD §2.11: "Each hop in a cascade is caused by the hop before it, not directly by
        the request, and the ordering matters because later hops read state that earlier
        hops wrote."

        PRD §3.5: "Only lines whose `install_status` is not `VOID` and whose
        `verification_status` is not `REJECTED` participate; voided and rejected lines
        contribute 0 and are excluded from the proration ordering entirely."

        Design: Difficulty/transitive_cascade/anchor_rejection_cascade_strands_panel_upgrade_and_zeroes_final_total
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload(), build_panel_200a_payload()],
            household_overrides={"existing_panel_amps": 100},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_PANEL_200A, 1, 380000),
            ],
            installation_overrides={
                "installed_panel_amps": 200,
                "actual_project_cost_cents": 1080000,
            },
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]

        #  800000 in HVAC_GROUP plus the 400000 panel ceiling: 1200000 encumbered.
        assert world["reservation"]["reserved_amount_cents"] == 1200000
        assert_household_cap(
            read_household(api, household_id), remaining=200000, encumbered=1200000
        )

        failed = record_result(
            api,
            world["inspection_id"],
            world["inspector_id"],
            build_fail_result_payload(
                [MEASURE_HP_HVAC],
                deficiency_count=2,
                deficiency_severity_max=4,
                notes="Heat pump commissioning failed",
            ),
        )
        assert failed["status"] == InspectionStatus.FAILED
        assert failed["rejected_measure_codes"] == [MEASURE_HP_HVAC]

        lines = read_project_measures(api, project_id)
        anchor = find_measure_line(lines, MEASURE_HP_HVAC)
        assert anchor["verification_status"] == VerificationStatus.REJECTED
        assert anchor["rejection_reason"] == LineRejectionReason.INSPECTION_DEFICIENCY
        assert anchor["final_incentive_cents"] == 0

        #  The inspector never named this line; hop one did.
        panel = find_measure_line(lines, MEASURE_PANEL_200A)
        assert panel["verification_status"] == VerificationStatus.REJECTED
        assert panel["rejection_reason"] == LineRejectionReason.ANCHOR_REJECTED
        assert panel["final_incentive_cents"] == 0
        assert panel["pinned_is_panel_upgrade"] is True

        #  Both rejections leave the physical dimension exactly where it was.
        assert [line["install_status"] for line in lines] == [
            InstallStatus.INSTALLED,
            InstallStatus.INSTALLED,
        ]

        #  Hop three: nothing participates, so the final total is 0 rather than the
        #  380000 the panel line would otherwise have allocated.
        project = read_project(api, project_id)
        assert project["status"] == ProjectStatus.INSPECTION_FAILED
        assert project["final_total_incentive_cents"] == 0
        assert project["remediation_count"] == 0

        #  A recoverable failure releases nothing and records nothing.
        reservation = project_reservation(api, project_id)
        assert reservation["status"] == ReservationStatus.RESERVED
        assert reservation["reserved_amount_cents"] == 1200000
        assert_program_buckets(read_program(api, program_id), available=48800000, reserved=1200000)
        assert_household_cap(
            read_household(api, household_id), remaining=200000, encumbered=1200000
        )
        _rows, meta = validate_paginated(
            api.list_clawback_actions(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 0

    def test_the_cascade_never_travels_from_the_panel_line_back_to_its_anchor(self, api):
        """Rejecting the panel upgrade strands nothing, and remediation restores the pair.

        PRD §3.8: "Second — and caused by that first hop, not by the request — every
        measure line whose `pinned_is_panel_upgrade` is true and whose qualifying
        appliance anchor line has now become `REJECTED` also moves `verification_status`
        from `PENDING` to `REJECTED`, this time with `rejection_reason` set to
        `ANCHOR_REJECTED`."

        PRD §3.5: "If `pinned_is_panel_upgrade` is true, the line amount is further
        reduced to the smaller of itself and the program's `panel_upgrade_cap_cents`."

        PRD §3.8: "The cycle increments `remediation_count` by one and resets every
        measure line whose `verification_status` is `REJECTED` back to `PENDING`,
        clearing each line's `rejection_reason` and incrementing each line's version."

        PRD §3.8: "On a `POST_INSTALL` inspection of an installed project it moves the
        project `INSTALLED → VERIFIED`: every measure line moves `verification_status`
        from `PENDING` to `VERIFIED` and stores its `verified_quantity` from the result
        payload, the final allocation runs over the project and writes each line's
        `final_incentive_cents` and the project's `final_total_incentive_cents`, and the
        project's active stacking declaration, if one exists, is recomputed along with
        the project's `stacking_adjusted_state_incentive_cents`."

        Design: Difficulty/transitive_cascade/anchor_rejection_cascade_strands_panel_upgrade_and_zeroes_final_total
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload(), build_panel_200a_payload()],
            household_overrides={"existing_panel_amps": 100},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_PANEL_200A, 1, 380000),
            ],
            installation_overrides={
                "installed_panel_amps": 200,
                "actual_project_cost_cents": 1080000,
            },
        )
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]
        inspector_id = world["inspector_id"]

        #  This time the panel upgrade is the line the inspector names.
        record_result(
            api,
            world["inspection_id"],
            inspector_id,
            build_fail_result_payload(
                [MEASURE_PANEL_200A],
                deficiency_count=1,
                deficiency_severity_max=3,
                notes="Service conductors undersized",
            ),
        )
        lines = read_project_measures(api, project_id)
        panel = find_measure_line(lines, MEASURE_PANEL_200A)
        assert panel["verification_status"] == VerificationStatus.REJECTED
        assert panel["rejection_reason"] == LineRejectionReason.INSPECTION_DEFICIENCY
        assert panel["final_incentive_cents"] == 0

        #  The anchor is not a panel upgrade and has no anchor of its own, so no second
        #  hop can reach it.
        anchor = find_measure_line(lines, MEASURE_HP_HVAC)
        assert anchor["verification_status"] == VerificationStatus.PENDING
        assert anchor["rejection_reason"] is None
        assert anchor["install_status"] == InstallStatus.INSTALLED

        #  Only the surviving anchor allocates: min(800000, 800000, floor(700000 * 1.00)).
        failed_project = read_project(api, project_id)
        assert failed_project["status"] == ProjectStatus.INSPECTION_FAILED
        assert failed_project["final_total_incentive_cents"] == 700000

        #  Remediation puts the rejected line back in the running.
        remediated = open_remediation(
            api, project_id, contractor_id, remediation_notes="Feeders re-pulled"
        )
        assert remediated["status"] == ProjectStatus.REMEDIATION
        assert remediated["remediation_count"] == 1
        reopened = find_measure_line(read_project_measures(api, project_id), MEASURE_PANEL_200A)
        assert reopened["verification_status"] == VerificationStatus.PENDING
        assert reopened["rejection_reason"] is None

        second_inspection = schedule_inspection(
            api,
            project_id,
            inspector_id,
            scheduled_start="2026-08-25T09:00:00Z",
            scheduled_end="2026-08-25T11:00:00Z",
        )
        assert read_project(api, project_id)["status"] == ProjectStatus.INSTALLED
        record_result(api, second_inspection["id"], inspector_id, build_pass_result_payload())

        #  700000 for the anchor plus min(400000, 400000, 380000) for the panel line.
        verified = read_project(api, project_id)
        assert verified["status"] == ProjectStatus.VERIFIED
        assert verified["final_total_incentive_cents"] == 1080000
        final_lines = read_project_measures(api, project_id)
        assert [line["verification_status"] for line in final_lines] == [
            VerificationStatus.VERIFIED,
            VerificationStatus.VERIFIED,
        ]
        assert [line["final_incentive_cents"] for line in final_lines] == [700000, 380000]
