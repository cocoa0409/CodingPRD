"""Optimistic concurrency tokens, the quality threshold edge and read-your-write consistency."""

import pytest

from test_helpers import (
    ApiErrorId,
    ContractorStatus,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_QUALITY_SUSPENSION_THRESHOLD,
    DEFAULT_RECERTIFICATION_THRESHOLD,
    IncomeTier,
    InspectionStatus,
    MEASURE_HP_HVAC,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    SuspensionReason,
    assert_household_cap,
    assert_program_buckets,
    build_assessment_measure,
    build_assessment_payload,
    build_conditional_pass_result_payload,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_project_measure,
    build_project_payload,
    build_reservation_payload,
    build_verify_decision_payload,
    build_world,
    create_approved_assessment,
    create_enrolled_contractor,
    create_household,
    create_inspector,
    create_project,
    create_verified_household,
    decide_assessment,
    file_income_verification,
    find_measure_line,
    household_version,
    make_contractor_headers,
    program_version,
    read_contractor,
    read_eligible_measures,
    read_household,
    read_inspection,
    read_program,
    read_project,
    read_project_measures,
    read_quality_review,
    record_result,
    report_installation,
    review_project,
    schedule_inspection,
    set_clock,
    submit_project,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification,
)


class TestStaleProgramVersion:
    def test_the_second_reservation_waits_for_a_fresh_program_version(self, api):
        """A 412 on project B alone, and the identical retry succeeds after a re-read.

        PRD §2.8: "Creating a reservation for a project — the request addressed to
        `POST /rebate-projects/{id}/reservations` — requires a non-optional
        `expected_program_version` field carrying the client's last observed `version`
        of the `Program`. If it does not equal the program's current `version`, the
        request is rejected with `ERR_STALE_PROGRAM_VERSION` (412)."

        PRD §2.8: "Reserving funds for a second approved project is perfectly
        legitimate, so no state precondition can catch this case; the stale version is
        precisely what tells the reviewer that their view of `budget_available_cents`
        predates somebody else's reservation."

        Design: Corner/cross_cutting_complexity_layers/stale_program_version_blocks_the_second_reservation_until_re_read
        """
        world = build_world(api, stage="approved", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        contractor_id = world["contractor_id"]
        project_a = world["project_id"]

        #  A second household of the same program with its own approved project.
        other = create_verified_household(
            api,
            program_id,
            applicant_name="Bravo Okafor",
            email="bravo@example.com",
            service_address_line1="352 Concord Ave",
        )
        assessment_b = create_approved_assessment(
            api,
            other["household"]["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        project = create_project(
            api,
            other["household"]["id"],
            assessment_b["id"],
            contractor_id,
            other["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        project_b = project["id"]
        submit_project(api, project_b, contractor_id)
        review_project(api, project_b)

        observed = program_version(api, program_id)
        reservation_a = validate_success(
            api.create_reservation(
                project_a, build_reservation_payload(observed), REVIEWER_TWO_HEADERS
            ),
            expected_status=201,
        )
        assert reservation_a["reserved_amount_cents"] == 800000
        assert_program_buckets(
            read_program(api, program_id), available=49200000, reserved=800000, committed=0
        )

        #  The very same token is now one write out of date.
        validate_error(
            api.create_reservation(
                project_b, build_reservation_payload(observed), REVIEWER_TWO_HEADERS
            ),
            ApiErrorId.ERR_STALE_PROGRAM_VERSION,
        )
        assert read_project(api, project_b)["status"] == ProjectStatus.APPROVED
        _rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"project_id": project_b})
        )
        assert meta["total_count"] == 0

        #  The refusal moved no money and bumped no version.
        refreshed = read_program(api, program_id)
        assert_program_buckets(refreshed, available=49200000, reserved=800000, committed=0)
        assert refreshed["version"] == observed + 1

        #  Re-read, retry the identical request, and it lands.
        reservation_b = validate_success(
            api.create_reservation(
                project_b,
                build_reservation_payload(program_version(api, program_id)),
                REVIEWER_TWO_HEADERS,
            ),
            expected_status=201,
        )
        assert reservation_b["reserved_amount_cents"] == 800000
        assert reservation_b["status"] == ReservationStatus.RESERVED
        assert_program_buckets(
            read_program(api, program_id), available=48400000, reserved=1600000, committed=0
        )
        rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"program_id": program_id})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {reservation_a["id"], reservation_b["id"]}


class TestStaleHouseholdVersion:
    def test_a_write_the_contractor_never_made_invalidates_its_assessment_token(self, api):
        """The reviewer's income decision bumps the household, so the filed token is stale.

        PRD §2.8: "Creating an assessment — the request addressed to `POST /assessments`
        — requires a non-optional `expected_household_version` field carrying the
        client's last observed `version` of the `Household`. A mismatch against the
        household's current `version` is rejected with `ERR_STALE_HOUSEHOLD_VERSION`
        (412)."

        PRD §3.2: "The household's version increments by one."

        PRD §3.4: "Creating the assessment also increments the household's version by
        one."

        Design: Corner/cross_cutting_complexity_layers/stale_household_version_blocks_the_assessment_filed_across_an_income_decision
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        contractor = create_enrolled_contractor(api, program_id)
        contractor_headers = make_contractor_headers(contractor["id"])
        household = create_household(api, program_id, applicant_name="Stan Petrov")
        packet = file_income_verification(api, household["id"])

        intake = read_household(api, household["id"])
        assert intake["version"] == 1
        assert intake["income_tier"] is None
        stale_version = intake["version"]

        #  The tier decision is somebody else's write against the same parent.
        verify_income_verification(api, packet["id"])

        measures = [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)]
        validate_error(
            api.create_assessment(
                build_assessment_payload(
                    household["id"], contractor["id"], stale_version, measures
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION,
        )

        #  Repeating the stale write does not eventually succeed.
        validate_error(
            api.create_assessment(
                build_assessment_payload(
                    household["id"],
                    contractor["id"],
                    stale_version,
                    [build_assessment_measure(MEASURE_HP_HVAC, 1, 999999)],
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION,
        )
        _rows, meta = validate_paginated(
            api.list_assessments(REVIEWER_HEADERS, {"household_id": household["id"]})
        )
        assert meta["total_count"] == 0

        #  Only the VERIFY bumped the household; neither 412 did.
        fresh_version = household_version(api, household["id"])
        assert fresh_version == stale_version + 1 == 2

        assessment = validate_success(
            api.create_assessment(
                build_assessment_payload(
                    household["id"], contractor["id"], fresh_version, measures
                ),
                contractor_headers,
            ),
            expected_status=201,
        )
        assert assessment["qualified_measure_count"] == 1
        assert assessment["estimated_total_incentive_cents"] == 800000
        assert assessment["effective_panel_amps"] == 200
        assert household_version(api, household["id"]) == 3


class TestVersionLedger:
    def test_every_write_advances_the_household_version_and_no_read_ever_does(self, api):
        """1 at intake, 2 after the tier decision, 3 after the assessment, 4 at reservation.

        PRD §2.4: "`version` (integer): a counter that increments by one on every
        mutation of the record, including mutations caused by a cascade from another
        resource rather than by a request addressed to this one."

        PRD §2.4: "When a computed field changes — a budget bucket on a program, a cap
        balance on a household, an incentive amount on a project or a measure line —
        that is a mutation of the owning record: `updated_at` is refreshed and `version`
        increments by one."

        PRD §3.7: "The same operation debits the program's `budget_available_cents` and
        credits its `budget_reserved_cents` by the reserved amount, incrementing the
        program's version; debits the household's `lifetime_cap_remaining_cents` and
        credits its `encumbered_cents` by the same amount, incrementing the household's
        version; and moves the project `APPROVED → RESERVED`, incrementing the
        project's version."

        PRD §3.5: "Every later incentive computation reads the pinned copies and never
        the live catalog item, so retiring or re-pricing a measure afterwards changes
        nothing about a project already open."

        Design: Corner/cross_cutting_complexity_layers/version_advances_once_per_write_and_never_on_reads
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        contractor = create_enrolled_contractor(api, program_id)
        household = create_household(api, program_id, applicant_name="Lou Delgado")
        packet = file_income_verification(api, household["id"])

        #  Two identical reads, one version.
        assert read_household(api, household["id"])["version"] == 1
        assert read_household(api, household["id"])["version"] == 1

        verify_income_verification(api, packet["id"])
        after_verify = read_household(api, household["id"])
        assert after_verify["version"] == 2
        assert after_verify["income_tier"] == IncomeTier.LOW
        assert after_verify["rebate_cap_cents"] == DEFAULT_LOW_TIER_CAP_CENTS

        assessment = create_approved_assessment(
            api,
            household["id"],
            contractor["id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            expected_household_version=after_verify["version"],
        )
        assert household_version(api, household["id"]) == 3

        #  Project creation carries no concurrency token and moves no household money,
        #  and the derived quote read moves nothing at all.
        project = create_project(
            api,
            household["id"],
            assessment["id"],
            contractor["id"],
            packet["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        validate_success(
            api.get_incentive_quote(project["id"], make_contractor_headers(contractor["id"]))
        )
        assert household_version(api, household["id"]) == 3

        submit_project(api, project["id"], contractor["id"])
        review_project(api, project["id"])
        validate_success(
            api.create_reservation(
                project["id"],
                build_reservation_payload(program_version(api, program_id)),
                REVIEWER_TWO_HEADERS,
            ),
            expected_status=201,
        )

        after_reservation = read_household(api, household["id"])
        assert after_reservation["version"] == 4
        assert_household_cap(
            after_reservation,
            remaining=600000,
            encumbered=800000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  Create, submit, review, reserve — four writes on the project itself.
        assert read_project(api, project["id"])["version"] == 4
        line = find_measure_line(read_project_measures(api, project["id"]), MEASURE_HP_HVAC)
        assert line["pinned_unit_incentive_cents"] == 800000


class TestQualitySuspensionThreshold:
    def test_a_score_of_exactly_seventy_survives_and_the_next_failure_suspends(self, api):
        """Strict `<` on the threshold, and two different integers from one history.

        PRD §3.3: "The **rolling-window** measure takes at most the ten most recent
        candidates in that order, weights each equally, and is the sum of their point
        values divided by the number of candidates counted, rounded half up to a whole
        number."

        PRD §3.3: "When it lands strictly below the program's
        `quality_suspension_threshold`, the contractor is automatically taken
        `ENROLLED_ACTIVE → SUSPENDED` with `suspension_reason` set to `QUALITY_SCORE`,
        dragging the contractor-hold cascade behind it."

        PRD §3.3: "It takes every candidate whose `result_recorded_at` falls at or after
        365 days before the logical clock's instant — with no cap on how many that is —
        and weights each candidate by one plus its `deficiency_count`."

        PRD §3.3: "Because a single failure carrying many deficiencies can dominate the
        weighted sum, the same inspection history routinely yields a different integer
        under the two measures."

        Design: Corner/cross_cutting_complexity_layers/quality_suspension_fires_below_seventy_not_at_exactly_seventy
        """
        world = build_world(
            api,
            stage="installed",
            catalog=[build_hvac_heat_pump_payload()],
            project_measures=[build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 1000000)],
        )
        program_id = world["program_id"]
        contractor_id = world["contractor_id"]
        project_a = world["project_id"]

        #  A second project of the same installer, installed over a later window so
        #  crew capacity is never the blocker.
        other = create_verified_household(
            api,
            program_id,
            applicant_name="Bravo Threshold",
            email="th-b@example.com",
            service_address_line1="382 Threshold Trc",
        )
        assessment_b = create_approved_assessment(
            api,
            other["household"]["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        project = create_project(
            api,
            other["household"]["id"],
            assessment_b["id"],
            contractor_id,
            other["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        project_b = project["id"]
        submit_project(api, project_b, contractor_id)
        review_project(api, project_b)
        validate_success(
            api.create_reservation(
                project_b,
                build_reservation_payload(program_version(api, program_id)),
                REVIEWER_TWO_HEADERS,
            ),
            expected_status=201,
        )
        report_installation(
            api,
            project_b,
            contractor_id,
            [build_measure_result(MEASURE_HP_HVAC, 1, 1000000)],
            install_start_date="2026-09-01",
            install_end_date="2026-09-10",
            installed_panel_amps=200,
            actual_project_cost_cents=1000000,
        )

        inspector = create_inspector(api, program_id, inspector_name="Tess Aldana")
        inspection_a = schedule_inspection(
            api,
            project_a,
            inspector["id"],
            scheduled_start="2026-09-14T09:00:00Z",
            scheduled_end="2026-09-14T11:00:00Z",
        )
        inspection_b = schedule_inspection(
            api,
            project_b,
            inspector["id"],
            scheduled_start="2026-09-15T09:00:00Z",
            scheduled_end="2026-09-15T11:00:00Z",
        )

        #  One conditional pass: 70 points over one candidate is exactly the threshold.
        set_clock(api, "2026-09-14T12:00:00Z")
        record_result(
            api,
            inspection_a["id"],
            inspector["id"],
            build_conditional_pass_result_payload(deficiency_count=2, deficiency_severity_max=2),
        )
        standing = read_contractor(api, contractor_id)
        assert standing["quality_score_rolling"] == DEFAULT_QUALITY_SUSPENSION_THRESHOLD == 70
        assert standing["completed_inspection_count"] == 1
        assert standing["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert standing["suspension_reason"] is None

        review = read_quality_review(api, contractor_id)
        assert review["rolling_window_score"] == 70
        assert review["rolling_window_inspection_count"] == 1
        assert review["severity_weighted_score"] == 70
        assert review["weighted_inspection_count"] == 1
        assert review["suspension_threshold"] == DEFAULT_QUALITY_SUSPENSION_THRESHOLD
        assert review["recertification_threshold"] == DEFAULT_RECERTIFICATION_THRESHOLD
        assert review["recertification_eligible"] is False

        #  A failure carrying six deficiencies: the mean drops to 35 and trips the gate.
        set_clock(api, "2026-09-15T12:00:00Z")
        record_result(
            api,
            inspection_b["id"],
            inspector["id"],
            build_fail_result_payload(
                [MEASURE_HP_HVAC], deficiency_count=6, deficiency_severity_max=4
            ),
        )
        suspended = read_contractor(api, contractor_id)
        assert suspended["quality_score_rolling"] == 35
        assert suspended["completed_inspection_count"] == 2
        assert suspended["status"] == ContractorStatus.SUSPENDED
        assert suspended["suspension_reason"] == SuspensionReason.QUALITY_SCORE

        #  Weights 1+2 and 1+6 make the weighted mean 21, not the rolling 35.
        weighted = read_quality_review(api, contractor_id)
        assert weighted["rolling_window_score"] == 35
        assert weighted["severity_weighted_score"] == 21
        assert weighted["weighted_inspection_count"] == 2

        #  The suspension came from the score, not from either project's own fate.
        assert read_project(api, project_b)["status"] == ProjectStatus.INSPECTION_FAILED
        passed_project = read_project(api, project_a)
        assert passed_project["status"] == ProjectStatus.VERIFIED
        assert passed_project["conditional_pass_flag"] is True

        first = read_inspection(api, inspection_a["id"])
        second = read_inspection(api, inspection_b["id"])
        assert first["status"] == InspectionStatus.CONDITIONAL_PASS
        assert second["status"] == InspectionStatus.FAILED
        assert first["result_recorded_at"].startswith("2026-09-14T12:00:00")
        assert second["result_recorded_at"].startswith("2026-09-15T12:00:00")


class TestImmediateConsistency:
    def test_each_write_response_already_carries_what_the_next_read_reports(self, api):
        """The tier, the provisional total and the moved budget need no settling call.

        PRD §3.2: "The decision writes `computed_ami_percent`, `assigned_income_tier`,
        and `assigned_cap_cents` onto the verification, along with `verified_by_user_id`
        and a `verified_at` stamped from the logical clock."

        PRD §3.4: "The assessment also records `qualified_measure_count`, the number of
        child rows whose `qualified` flag is true, and `estimated_total_incentive_cents`,
        the sum of `estimated_incentive_cents` over the qualified rows after the group
        and household cap allocation of §3.5 has been applied to the estimate."

        PRD §3.7: "Its `reserved_amount_cents` and its immutable
        `initial_reserved_amount_cents` are both set to the project's
        `provisional_total_incentive_cents`; `reserved_at` is the logical clock's
        instant; `expires_at` is that instant plus the program's `reservation_ttl_days`
        days; `extension_count` and `extension_days_granted` start at 0; `committed_at`
        and `release_reason` are null."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        contractor = create_enrolled_contractor(api, program_id)
        contractor_headers = make_contractor_headers(contractor["id"])
        household = create_household(api, program_id, applicant_name="Immediate Ines")
        packet = file_income_verification(api, household["id"])

        #  The decision response itself already carries the assignment.
        decided = validate_success(
            api.verify_income_verification(
                packet["id"], build_verify_decision_payload(), REVIEWER_HEADERS
            )
        )
        assert decided["computed_ami_percent"] == pytest.approx(80.0, abs=0.01)
        assert decided["assigned_income_tier"] == IncomeTier.LOW
        assert decided["assigned_cap_cents"] == DEFAULT_LOW_TIER_CAP_CENTS

        #  The very next read agrees exactly.
        after_verify = read_household(api, household["id"])
        assert after_verify["income_tier"] == IncomeTier.LOW
        assert after_verify["ami_percent"] == pytest.approx(80.0, abs=0.01)
        assert_household_cap(
            after_verify,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        assessment = validate_success(
            api.create_assessment(
                build_assessment_payload(
                    household["id"],
                    contractor["id"],
                    after_verify["version"],
                    [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
                ),
                contractor_headers,
            ),
            expected_status=201,
        )
        assert assessment["qualified_measure_count"] == 1
        assert assessment["effective_panel_amps"] == 200
        assert assessment["estimated_total_incentive_cents"] == 800000
        eligible = read_eligible_measures(api, assessment["id"])
        assert len(eligible) == 1
        assert eligible[0]["qualified"] is True
        decide_assessment(api, assessment["id"])

        #  The create response computes the provisional total from its own body.
        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    household["id"],
                    assessment["id"],
                    contractor["id"],
                    packet["id"],
                    [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
                    estimated_project_cost_cents=1000000,
                ),
                contractor_headers,
            ),
            expected_status=201,
        )
        assert project["provisional_total_incentive_cents"] == 800000
        line = find_measure_line(read_project_measures(api, project["id"]), MEASURE_HP_HVAC)
        assert line["pinned_unit_incentive_cents"] == 800000
        assert line["provisional_incentive_cents"] == 800000

        submit_project(api, project["id"], contractor["id"])
        review_project(api, project["id"])

        observed = program_version(api, program_id)
        reservation = validate_success(
            api.create_reservation(
                project["id"], build_reservation_payload(observed), REVIEWER_TWO_HEADERS
            ),
            expected_status=201,
        )
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["initial_reserved_amount_cents"] == 800000

        #  Both parent ledgers have already moved by the time the next read lands.
        program = read_program(api, program_id)
        assert_program_buckets(program, available=49200000, reserved=800000, committed=0)
        assert program["version"] == observed + 1
        assert_household_cap(
            read_household(api, household["id"]),
            remaining=600000,
            encumbered=800000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
