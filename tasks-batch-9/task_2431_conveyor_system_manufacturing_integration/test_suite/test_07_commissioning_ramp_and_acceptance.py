"""Commissioning ramp verdict boundaries and the acceptance prerequisite."""

from test_helpers import (
    PROJECT_DIRECTOR,
    SITE_MANAGER,
    ApiErrorId,
    assert_commissioning_ramp,
    create_acceptance_certificate_payload,
    make_completed_cutover,
    make_fat_passed_lot,
    make_scheduled_window,
    read_lot,
    read_project,
    record_ramp,
    validate_error,
    validate_paginated,
    validate_success,
)


def _commissioning_project(api, measured_cph=1313, defect_count=2):
    """Standard project driven to COMMISSIONING with one installed lot."""
    passed = make_fat_passed_lot(api, measured_cph=measured_cph, defect_count=defect_count)
    return make_completed_cutover(api, state=make_scheduled_window(api, state=passed))


class TestRampTargetRoundedUpAndInclusive:
    """The three-quarter target of a 1250 carton line rounds up to 938."""

    def test_the_half_rate_step_passes_and_the_target_is_rounded_up(self, api):
        """625 is exact at half rate; three quarters of 1250 rounds 937.5 up to 938.

        PRD §3.7: "The step's `target_cph` is the project's `required_throughput_cph`
        multiplied by `step_pct` and divided by 100, rounded **up** to the next whole
        carton per hour."

        Design: Difficulty/boundary_precision_check/ramp_measured_exactly_equal_to_target_passes
        """
        state = _commissioning_project(api)
        assert state["project"]["delivery_status"] == "COMMISSIONING"

        half = record_ramp(api, state["project"]["id"], 50, 700, 30)
        assert_commissioning_ramp(half)
        assert half["target_cph"] == 625
        assert half["min_sustained_minutes"] == 30
        assert half["verdict"] == "PASS"

        short = record_ramp(api, state["project"]["id"], 75, 937, 60)
        assert short["target_cph"] == 938
        assert short["min_sustained_minutes"] == 60
        assert short["verdict"] == "FAIL"

    def test_a_measured_rate_exactly_on_the_rounded_target_passes(self, api):
        """938 held for exactly sixty minutes satisfies both inclusive comparisons.

        PRD §3.7: "The step's `verdict` is `PASS` when `measured_cph` is greater than
        or equal to `target_cph` **and** `sustained_minutes` is greater than or equal to
        `min_sustained_minutes`; otherwise it is `FAIL`. Both comparisons are inclusive,
        so a rate exactly on target and a duration exactly at the minimum both pass."

        Design: Difficulty/boundary_precision_check/ramp_measured_exactly_equal_to_target_passes
        """
        state = _commissioning_project(api)
        record_ramp(api, state["project"]["id"], 50, 700, 30)
        record_ramp(api, state["project"]["id"], 75, 937, 60)

        exact = record_ramp(api, state["project"]["id"], 75, 938, 60)
        assert exact["target_cph"] == 938
        assert exact["measured_cph"] == 938
        assert exact["sustained_minutes"] == 60
        assert exact["verdict"] == "PASS"
        assert exact["recorded_by_user_id"] == SITE_MANAGER["X-User-ID"]

        steps, meta = validate_paginated(
            api.list_commissioning_ramps(state["project"]["id"], SITE_MANAGER)
        )
        assert meta["total_count"] == 3
        assert [step["verdict"] for step in steps if step["step_pct"] == 75] == ["FAIL", "PASS"]

    def test_the_failed_attempt_leaves_the_project_short_of_acceptance(self, api):
        """A passed 75 step is not enough; the full-rate demonstration is still missing.

        PRD §3.1: "That last flag is a derived predicate rather than a stored decision:
        it is true exactly when the project has a passing commissioning ramp step for
        each of the three demonstration levels 50, 75 and 100, **and** every site zone of
        the project has reached `CUTOVER_COMPLETE`."

        Design: Difficulty/boundary_precision_check/ramp_measured_exactly_equal_to_target_passes
        """
        state = _commissioning_project(api)
        record_ramp(api, state["project"]["id"], 50, 700, 30)
        record_ramp(api, state["project"]["id"], 75, 937, 60)
        record_ramp(api, state["project"]["id"], 75, 938, 60)

        project = read_project(api, state["project"]["id"])
        assert project["acceptance_ready"] is False
        assert project["delivery_status"] == "COMMISSIONING"

    def test_the_factory_test_on_target_with_two_defects_passed(self, api):
        """The lot reached the site because 1313 cartons and two defects both pass.

        PRD §3.5: "Its `result` is `PASS` when `measured_cph` is greater than or equal
        to `target_cph_at_test` **and** `defect_count` is no more than 2, and `FAIL` in
        every other case — a rate exactly equal to the target passes, and exactly two
        defects pass, while three defects fail regardless of rate."

        Design: Difficulty/boundary_precision_check/ramp_measured_exactly_equal_to_target_passes
        """
        state = _commissioning_project(api)

        assert state["fat_test"]["measured_cph"] == 1313
        assert state["fat_test"]["target_cph_at_test"] == 1313
        assert state["fat_test"]["defect_count"] == 2
        assert state["fat_test"]["result"] == "PASS"
        assert read_lot(api, state["lot"]["id"])["status"] == "INSTALLED"


class TestAcceptanceRequiresEveryRampStepPassed:
    """A failed full-rate demonstration blocks issuance."""

    def _commissioning_with_failed_full_rate(self, api):
        state = _commissioning_project(api)
        project_id = state["project"]["id"]
        record_ramp(api, project_id, 50, 700, 30)
        record_ramp(api, project_id, 75, 950, 60)
        state["full_rate"] = record_ramp(api, project_id, 100, 1249, 120)
        return state

    def test_issuance_is_refused_while_the_full_rate_step_failed(self, api):
        """1249 falls one carton short of the 1250 full-rate target.

        PRD §3.7: "Three gates guard it, and their relative order follows §2.12:
        `acceptance_ready` must be true, otherwise `ERR_ACCEPTANCE_PREREQ_NOT_MET`; the
        project's `commercial_status` must be `CLEAN` — equivalently, no change order of
        the project may be sitting in `SUBMITTED` or `REVISION_REQUESTED` — otherwise
        `ERR_OPEN_CHANGE_ORDER`; and only then, the issuing `X-User-ID` must differ from
        the `recorded_by_user_id` of the passing full-rate ramp step, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/certificate_issuance_requires_all_ramp_steps_passed
        """
        state = self._commissioning_with_failed_full_rate(api)
        assert state["full_rate"]["target_cph"] == 1250
        assert state["full_rate"]["min_sustained_minutes"] == 120
        assert state["full_rate"]["verdict"] == "FAIL"

        response = api.create_acceptance_certificate(
            create_acceptance_certificate_payload(state["project"]["id"]), PROJECT_DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_ACCEPTANCE_PREREQ_NOT_MET.value)

    def test_no_certificate_is_minted_and_the_project_stays_commissioning(self, api):
        """Failing rows never satisfy the predicate, so nothing is settled.

        PRD §3.7: "Issuing the acceptance certificate is a `ProjectDirector` act that
        advances the project's `delivery_status` from `COMMISSIONING` to `ACCEPTED`, its
        only terminal delivery state."

        Design: Difficulty/cross_entity_state_dependency/certificate_issuance_requires_all_ramp_steps_passed
        """
        state = self._commissioning_with_failed_full_rate(api)
        api.create_acceptance_certificate(
            create_acceptance_certificate_payload(state["project"]["id"]), PROJECT_DIRECTOR
        )

        _, meta = validate_paginated(
            api.list_acceptance_certificates(state["project"]["id"], PROJECT_DIRECTOR)
        )
        assert meta["total_count"] == 0

        project = read_project(api, state["project"]["id"])
        assert project["delivery_status"] == "COMMISSIONING"
        assert project["acceptance_ready"] is False

    def test_a_passing_full_rate_step_then_unlocks_issuance(self, api):
        """Recording a passing 100 per cent step refreshes the predicate.

        PRD §3.7: "Recording a step refreshes the project's `acceptance_ready`
        predicate and increments the project's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/certificate_issuance_requires_all_ramp_steps_passed
        """
        state = self._commissioning_with_failed_full_rate(api)
        passing = record_ramp(api, state["project"]["id"], 100, 1250, 120)
        assert passing["verdict"] == "PASS"

        ready = read_project(api, state["project"]["id"])
        assert ready["acceptance_ready"] is True

        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(state["project"]["id"]), PROJECT_DIRECTOR
            ),
            expected_status=201,
        )
        assert certificate["accepted_throughput_cph"] == 1250
        assert read_project(api, state["project"]["id"])["delivery_status"] == "ACCEPTED"
