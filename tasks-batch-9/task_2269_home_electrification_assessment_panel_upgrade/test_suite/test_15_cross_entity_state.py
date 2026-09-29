"""Three blockers that live on another row: the grandparent program, the parent contractor, the sibling inspection."""

from test_helpers import (
    ApiErrorId,
    ContractorStatus,
    InspectionStatus,
    InspectionType,
    InstallStatus,
    MEASURE_HP_HVAC,
    ProgramStatus,
    ProjectStatus,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    SuspensionReason,
    assert_household_cap,
    assert_program_buckets,
    assert_version_unchanged,
    build_assessment_measure,
    build_hvac_heat_pump_payload,
    build_installation_payload,
    build_measure_result,
    build_reservation_payload,
    build_world,
    cancel_inspection,
    create_approved_assessment,
    create_project,
    create_verified_household,
    program_version,
    read_contractor,
    read_household,
    read_inspection,
    read_program,
    read_project,
    read_project_measures,
    read_reservation,
    reinstate_contractor,
    review_project,
    schedule_inspection,
    set_program_status,
    submit_project,
    suspend_contractor,
    validate_error,
    validate_success,
)


class TestReservationNeedsAnOpenProgram:
    def test_a_fully_approved_project_cannot_reserve_while_its_program_is_suspended(self, api):
        """Nothing on the project row changes, yet the same call flips from 409 to 201.

        PRD §3.1: "`OPEN → SUSPENDED` requires the program to be `OPEN`; suspension does
        **not** pause any clock, so existing reservations keep their `expires_at` exactly as
        it stood, and while suspended, reservation creation and payment are refused with
        `ERR_PROGRAM_NOT_OPEN` while the expiry sweep continues to run normally. `SUSPENDED →
        OPEN` returns a suspended program to service, which makes the program machine
        cyclic."

        PRD §2.10: "**State gate.** The source entity is in a state from which the requested
        transition is declared, and the enclosing program is `OPEN` where the transition
        requires it."

        PRD §3.1: "Every one of these five transitions increments the program's version by
        one."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_open_program_not_merely_approved_project
        """
        world = build_world(api, stage="approved", catalog=[build_hvac_heat_pump_payload()])
        project_id = world["project_id"]
        program_id = world["program_id"]
        open_version = program_version(api, program_id)

        approved_before = read_project(api, project_id)
        assert approved_before["status"] == ProjectStatus.APPROVED
        assert approved_before["provisional_total_incentive_cents"] == 800000

        #  Suspending the program touches the program row only.
        suspended = set_program_status(
            api, program_id, ProgramStatus.SUSPENDED, status_note="Appropriation under review"
        )
        assert suspended["status"] == ProgramStatus.SUSPENDED
        assert suspended["version"] == open_version + 1
        assert_version_unchanged(approved_before, read_project(api, project_id), "project")

        validate_error(
            api.create_reservation(
                project_id,
                build_reservation_payload(suspended["version"]),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_PROGRAM_NOT_OPEN,
            expected_status=409,
        )

        #  The refusal moved neither the project nor a single cent.
        after_refusal = read_project(api, project_id)
        assert after_refusal["status"] == ProjectStatus.APPROVED
        assert_version_unchanged(approved_before, after_refusal, "project")
        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0
        )

        reopened = set_program_status(api, program_id, ProgramStatus.OPEN)
        assert reopened["status"] == ProgramStatus.OPEN
        assert reopened["version"] == open_version + 2

        reservation = validate_success(
            api.create_reservation(
                project_id,
                build_reservation_payload(reopened["version"]),
                REVIEWER_TWO_HEADERS,
            ),
            201,
        )
        assert reservation["status"] == ReservationStatus.RESERVED
        assert reservation["reserved_amount_cents"] == 800000
        assert read_project(api, project_id)["status"] == ProjectStatus.RESERVED
        assert_program_buckets(
            read_program(api, program_id), available=49200000, reserved=800000, committed=0
        )
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=600000, encumbered=800000
        )

    def test_the_program_state_is_read_before_the_version_token(self, api):
        """A stale token against a suspended program reports the suspension, not the staleness.

        PRD §2.10: "**State gate.** The source entity is in a state from which the requested
        transition is declared, and the enclosing program is `OPEN` where the transition
        requires it. This is the umbrella rung, and an entity in a terminal state always
        fails here."

        PRD §2.10: "**Concurrency token.** The declared parent version matches, per §2.8 →
        otherwise `ERR_STALE_PROGRAM_VERSION` or `ERR_STALE_HOUSEHOLD_VERSION` (412). Applies
        to `POST /rebate-projects/{id}/reservations` and `POST /assessments`. It sits after
        the state gate deliberately: a caller holding a stale token against an
        already-terminal entity learns about the state problem first."

        PRD §2.8: "If it does not equal the program's current `version`, the request is
        rejected with `ERR_STALE_PROGRAM_VERSION` (412)."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_open_program_not_merely_approved_project
        """
        world = build_world(api, stage="approved", catalog=[build_hvac_heat_pump_payload()])
        project_id = world["project_id"]
        program_id = world["program_id"]
        open_version = program_version(api, program_id)

        suspended = set_program_status(api, program_id, ProgramStatus.SUSPENDED)
        assert suspended["version"] == open_version + 1

        #  Two rungs are violated at once; rung 8 answers.
        validate_error(
            api.create_reservation(
                project_id, build_reservation_payload(open_version), REVIEWER_TWO_HEADERS
            ),
            ApiErrorId.ERR_PROGRAM_NOT_OPEN,
            expected_status=409,
        )

        reopened = set_program_status(api, program_id, ProgramStatus.OPEN)
        assert reopened["status"] == ProgramStatus.OPEN

        #  With the state gate satisfied the version rung becomes visible, and the token
        #  observed while the program was suspended is now one version behind.
        validate_error(
            api.create_reservation(
                project_id, build_reservation_payload(suspended["version"]), REVIEWER_TWO_HEADERS
            ),
            ApiErrorId.ERR_STALE_PROGRAM_VERSION,
            expected_status=412,
        )
        assert read_project(api, project_id)["status"] == ProjectStatus.APPROVED
        assert_program_buckets(read_program(api, program_id), available=50000000, reserved=0)

        reservation = validate_success(
            api.create_reservation(
                project_id, build_reservation_payload(reopened["version"]), REVIEWER_TWO_HEADERS
            ),
            201,
        )
        assert reservation["status"] == ReservationStatus.RESERVED
        assert read_project(api, project_id)["status"] == ProjectStatus.RESERVED


class TestInstallationBlockedByContractorHold:
    def test_the_held_project_refuses_the_report_and_the_reinstated_one_accepts_it(self, api):
        """The project's own state answers, not the contractor's, and no money moves either way.

        PRD §3.3: "That transition cascades: every other rebate project of this contractor
        sitting in `RESERVED` moves `RESERVED → CONTRACTOR_HOLD`, and each of those projects
        has its own version incremented."

        PRD §3.3: "Reinstating a suspended contractor moves it `SUSPENDED →
        ENROLLED_ACTIVE` — permitted only when `license_expires_on` is still later than the
        logical clock's date — and cascades in the opposite direction: every project of this
        contractor in `CONTRACTOR_HOLD` whose reservation is still in status `RESERVED` moves
        `CONTRACTOR_HOLD → RESERVED`."

        PRD §3.7: "The report moves the project `RESERVED → INSTALLED` and is permitted only
        when the project is `RESERVED`, the acting contractor's identifier equals the
        project's `contractor_id`, the project's reservation is still in status `RESERVED`
        with the logical clock strictly before its `expires_at`, the contractor is
        `ENROLLED_ACTIVE` with both `license_expires_on` and `insurance_expires_on` on or
        after the logical clock's date"

        PRD §2.10: "Its errors are all 409: `ERR_INVALID_STATE_TRANSITION`,
        `ERR_PROGRAM_NOT_OPEN`, `ERR_ASSESSMENT_NOT_APPROVED`,
        `ERR_PROJECT_NOT_APPROVED_FOR_RESERVATION`, `ERR_RESERVATION_NOT_ACTIVE`,
        `ERR_RESERVATION_EXPIRED`, `ERR_INSPECTION_ALREADY_RECORDED`,
        `ERR_OPEN_INSPECTION_PENDING`, and `ERR_INCOME_TIER_ALREADY_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/installation_blocked_by_contractor_hold_cascade_and_released_on_reinstatement
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]

        suspended = suspend_contractor(
            api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION
        )
        assert suspended["status"] == ContractorStatus.SUSPENDED

        #  The hold freezes work, not funding.
        held = read_project(api, project_id)
        assert held["status"] == ProjectStatus.CONTRACTOR_HOLD
        assert held["version"] > world["project"]["version"]
        reservation = read_reservation(api, world["reservation_id"])
        assert reservation["status"] == ReservationStatus.RESERVED
        assert reservation["reserved_amount_cents"] == 800000

        payload = build_installation_payload(
            [build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            actual_project_cost_cents=700000,
        )
        validate_error(
            api.report_installation(project_id, payload, world["contractor_headers"]),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            expected_status=409,
        )
        refused = read_project(api, project_id)
        assert refused["install_start_date"] is None
        assert refused["actual_project_cost_cents"] is None
        assert read_project_measures(api, project_id)[0]["install_status"] == InstallStatus.PLANNED

        reinstated = reinstate_contractor(api, contractor_id)
        assert reinstated["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert read_project(api, project_id)["status"] == ProjectStatus.RESERVED

        #  The byte-identical payload now lands.
        installed = validate_success(
            api.report_installation(project_id, payload, world["contractor_headers"])
        )
        assert installed["status"] == ProjectStatus.INSTALLED
        assert installed["actual_project_cost_cents"] == 700000
        assert installed["install_start_date"] == "2026-08-10"
        line = read_project_measures(api, project_id)[0]
        assert line["install_status"] == InstallStatus.INSTALLED
        assert line["actual_cost_cents"] == 700000

        #  The hold-and-release cycle moved no money at all.
        assert_program_buckets(
            read_program(api, world["program_id"]), available=49200000, reserved=800000, committed=0
        )
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=600000, encumbered=800000
        )

    def test_only_reserved_siblings_ride_the_cascade_in_either_direction(self, api):
        """An approved-but-unreserved project of the same contractor is untouched both ways.

        PRD §3.3: "Suspending an `ENROLLED_ACTIVE` contractor moves it `ENROLLED_ACTIVE →
        SUSPENDED` and sets `suspension_reason` to `ADMIN_ACTION` when the administrator
        initiated it, or to `QUALITY_SCORE` when the system initiated it as a quality
        cascade. That transition cascades: every other rebate project of this contractor
        sitting in `RESERVED` moves `RESERVED → CONTRACTOR_HOLD`, and each of those projects
        has its own version incremented. The cascade is caused by the suspension itself,
        never directly by whatever request produced the suspension."

        PRD §3.3: "and cascades in the opposite direction: every project of this contractor
        in `CONTRACTOR_HOLD` whose reservation is still in status `RESERVED` moves
        `CONTRACTOR_HOLD → RESERVED`. Because a contractor can go from active to suspended
        and back again, this machine is cyclic. Each suspension or reinstatement increments
        the contractor's version by one."

        Design: Difficulty/cross_entity_state_dependency/installation_blocked_by_contractor_hold_cascade_and_released_on_reinstatement
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        contractor_id = world["contractor_id"]
        reserved_project_id = world["project_id"]

        #  A second dwelling of the same installer, approved but never reserved.
        second = create_verified_household(
            api,
            world["program_id"],
            applicant_name="Ines Marchetti",
            email="ines@example.com",
            service_address_line1="88 Copper Way",
        )
        second_assessment = create_approved_assessment(
            api,
            second["household"]["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        second_project = create_project(
            api,
            second["household"]["id"],
            second_assessment["id"],
            contractor_id,
            second["income_verification"]["id"],
        )
        submit_project(api, second_project["id"], contractor_id)
        approved = review_project(api, second_project["id"])
        assert approved["status"] == ProjectStatus.APPROVED

        contractor_before = read_contractor(api, contractor_id)
        suspended = suspend_contractor(
            api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION
        )
        assert suspended["version"] == contractor_before["version"] + 1
        assert suspended["suspension_reason"] == SuspensionReason.ADMIN_ACTION

        #  Only the reserved project rides the cascade.
        assert read_project(api, reserved_project_id)["status"] == ProjectStatus.CONTRACTOR_HOLD
        still_approved = read_project(api, second_project["id"])
        assert still_approved["status"] == ProjectStatus.APPROVED
        assert_version_unchanged(approved, still_approved, "unreserved project")

        reinstated = reinstate_contractor(api, contractor_id)
        assert reinstated["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert reinstated["version"] == suspended["version"] + 1
        assert read_project(api, reserved_project_id)["status"] == ProjectStatus.RESERVED
        assert_version_unchanged(
            approved, read_project(api, second_project["id"]), "unreserved project"
        )

        #  Work resumes on the released project.
        installed = validate_success(
            api.report_installation(
                reserved_project_id,
                build_installation_payload(
                    [build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            )
        )
        assert installed["status"] == ProjectStatus.INSTALLED
        assert_program_buckets(
            read_program(api, world["program_id"]), available=49200000, reserved=800000
        )


class TestPaymentBlockedBySpotInspection:
    def test_a_scheduled_spot_audit_withholds_disbursement_until_it_is_cancelled(self, api):
        """The blocker is a sibling row in SCHEDULED; cancelling it releases the money.

        PRD §3.9: "Disbursement is the last money-moving step, available to a
        `ProgramReviewer` or `ProgramAdmin` with an optional `payment_reference`. It requires
        the project to be `VERIFIED`, the program to be `OPEN`, the project's reservation to
        be in status `RESERVED`, no inspection of the project to be in `SCHEDULED` —
        otherwise `ERR_OPEN_INSPECTION_PENDING` — and the acting `X-User-ID` to differ from
        the project's `reviewed_by_user_id`."

        PRD §2.10: "When the blocking condition is specifically a sibling inspection still in
        `SCHEDULED` — as when payment is requested, or a re-inspection is scheduled out of
        `REMEDIATION` — the error is `ERR_OPEN_INSPECTION_PENDING` rather than the generic
        `ERR_INVALID_STATE_TRANSITION`."

        PRD §3.8: "A scheduled inspection may be cancelled by a `ProgramReviewer` or
        `ProgramAdmin` with an optional `cancellation_reason`, moving it `SCHEDULED →
        CANCELLED` and incrementing its version"

        PRD §3.9: "The operation writes `disbursed_amount_cents` on the project and
        reconciles the reservation's `reserved_amount_cents` down to the same figure, moving
        the reservation `RESERVED → COMMITTED` and stamping `committed_at` from the logical
        clock."

        Design: Difficulty/cross_entity_state_dependency/payment_blocked_by_scheduled_spot_inspection_until_cancelled
        """
        world = build_world(
            api,
            stage="verified",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        project_id = world["project_id"]
        assert world["project"]["status"] == ProjectStatus.VERIFIED
        assert world["project"]["final_total_incentive_cents"] == 700000

        spot = schedule_inspection(
            api,
            project_id,
            world["inspector_id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T10:00:00Z",
        )
        assert spot["inspection_type"] == InspectionType.SPOT
        assert spot["status"] == InspectionStatus.SCHEDULED

        validate_error(
            api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, {"payment_reference": "ACH-0001"}),
            ApiErrorId.ERR_OPEN_INSPECTION_PENDING,
            expected_status=409,
        )
        withheld = read_project(api, project_id)
        assert withheld["status"] == ProjectStatus.VERIFIED
        assert withheld["disbursed_amount_cents"] == 0
        assert read_reservation(api, world["reservation_id"])["status"] == ReservationStatus.RESERVED
        assert_program_buckets(
            read_program(api, world["program_id"]), available=49200000, reserved=800000, committed=0
        )

        cancelled = cancel_inspection(
            api, spot["id"], cancellation_reason="Spot check deferred to next quarter"
        )
        assert cancelled["status"] == InspectionStatus.CANCELLED

        paid = validate_success(
            api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, {"payment_reference": "ACH-0001"})
        )
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 700000
        committed = read_reservation(api, world["reservation_id"])
        assert committed["status"] == ReservationStatus.COMMITTED
        assert committed["reserved_amount_cents"] == 700000
        assert committed["initial_reserved_amount_cents"] == 800000
        assert_program_buckets(
            read_program(api, world["program_id"]),
            available=49300000,
            reserved=0,
            committed=700000,
        )

        #  The passing post-install inspection was never the blocker.
        assert read_inspection(api, world["inspection_id"])["status"] == InspectionStatus.PASSED

    def test_the_gate_asks_whether_any_inspection_is_scheduled_not_whether_one_exists(self, api):
        """A cancelled audit stops blocking; a freshly scheduled replacement blocks again.

        PRD §3.9: "It requires the project to be `VERIFIED`, the program to be `OPEN`, the
        project's reservation to be in status `RESERVED`, no inspection of the project to be
        in `SCHEDULED` — otherwise `ERR_OPEN_INSPECTION_PENDING` — and the acting `X-User-ID`
        to differ from the project's `reviewed_by_user_id`."

        PRD §3.8: "A scheduled inspection may be cancelled by a `ProgramReviewer` or
        `ProgramAdmin` with an optional `cancellation_reason`, moving it `SCHEDULED →
        CANCELLED` and incrementing its version; the cancelled window stops participating in
        the conflict rule."

        PRD §3.9: "On the household side, `encumbered_cents` is reconciled to the disbursed
        amount and `lifetime_cap_remaining_cents` is credited by the release difference, with
        the household's version incremented."

        Design: Difficulty/cross_entity_state_dependency/payment_blocked_by_scheduled_spot_inspection_until_cancelled
        """
        world = build_world(
            api,
            stage="verified",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            installation_overrides={"actual_project_cost_cents": 700000},
        )
        project_id = world["project_id"]

        first_spot = schedule_inspection(
            api,
            project_id,
            world["inspector_id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T10:00:00Z",
        )
        validate_error(
            api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, None),
            ApiErrorId.ERR_OPEN_INSPECTION_PENDING,
            expected_status=409,
        )
        assert cancel_inspection(api, first_spot["id"])["status"] == InspectionStatus.CANCELLED

        #  A second audit in the freed window blocks exactly as the first one did, so the
        #  gate is reading status and not mere existence.
        second_spot = schedule_inspection(
            api,
            project_id,
            world["inspector_id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T10:00:00Z",
        )
        assert second_spot["status"] == InspectionStatus.SCHEDULED
        validate_error(
            api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, None),
            ApiErrorId.ERR_OPEN_INSPECTION_PENDING,
            expected_status=409,
        )
        assert read_project(api, project_id)["disbursed_amount_cents"] == 0

        cancel_inspection(api, second_spot["id"], cancellation_reason="Audit sample reduced")
        assert read_inspection(api, first_spot["id"])["status"] == InspectionStatus.CANCELLED
        assert read_inspection(api, second_spot["id"])["status"] == InspectionStatus.CANCELLED

        paid = validate_success(api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, None))
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 700000
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=700000, encumbered=700000
        )
