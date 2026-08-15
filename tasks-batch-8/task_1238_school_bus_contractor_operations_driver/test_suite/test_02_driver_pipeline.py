"""Driver pipeline: initial state, training thresholds, retest loop,
credentials gating, discipline, and termination cascade."""
from test_helpers import (
    ApiErrorId,
    advance_driver_to_testing,
    build_service_day,
    create_active_driver,
    create_credential,
    create_district,
    create_driver_applicant,
    get_success_data,
    log_training,
    post_driver_event,
    set_clock,
    setup_ops_scenario,
    suspend_driver,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HR, OPS


class TestDriverInitialState:
    def test_initial_state_driver_applicant(self, api):
        """PRD section 3.3: "The record is born `APPLICANT` with all computed
        counters — `behind_wheel_minutes`, `classroom_minutes`, `test_fail_count`,
        `weekly_assigned_minutes` — at zero and `hired_on` null."

        Design: Corner/state_machines/initial_state_driver_applicant
        """
        district = create_district(name="D-SM1")
        driver = validate_success(
            api.create_driver(
                {"primary_district_id": district["id"], "full_name": "D Init",
                 "license_number": "L220", "license_class": "A",
                 "hourly_wage_cents": 3000},
                HR),
            201)
        assert driver["status"] == "APPLICANT"
        assert driver["behind_wheel_minutes"] == 0
        assert driver["classroom_minutes"] == 0
        assert driver["test_fail_count"] == 0
        assert driver["weekly_assigned_minutes"] == 0
        assert driver["hired_on"] is None


class TestDriverRetestLoop:
    def _driver_in_testing(self, name, license_number):
        district = create_district(name=name)
        driver = create_driver_applicant(district["id"], full_name="D Loop",
                                         license_number=license_number)
        advance_driver_to_testing(driver["id"])
        return driver

    def test_test_fail_cycles_back_to_training(self, api):
        """PRD section 3.3: "The testing loop is cyclic: `TEST_FAIL` sends the
        driver back to `TRAINING` and increments `test_fail_count`, while
        `TEST_PASS` promotes to `CERTIFIED` — but only if the driver already
        holds a credential of `kind` `CDL_B` with status `ACTIVE`, failing with
        `ERR_CREDENTIAL_EXPIRED` otherwise."

        Design: Difficulty/non_linear_state_machine/driver_retest_loop_cycle
        """
        driver = self._driver_in_testing("D-LOOP", "L500")
        after_fail = post_driver_event(driver["id"], "TEST_FAIL",
                                       reason="Failed pretrip")
        assert after_fail["status"] == "TRAINING", (
            f"TEST_FAIL must cycle TESTING -> TRAINING, got {after_fail['status']}")
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["test_fail_count"] == 1
        assert fetched["status"] == "TRAINING"

    def test_retest_then_pass_reaches_certified(self, api):
        """PRD section 3.3: "The testing loop is cyclic: `TEST_FAIL` sends the
        driver back to `TRAINING` and increments `test_fail_count`, while
        `TEST_PASS` promotes to `CERTIFIED` — but only if the driver already
        holds a credential of `kind` `CDL_B` with status `ACTIVE`, failing with
        `ERR_CREDENTIAL_EXPIRED` otherwise."

        Design: Difficulty/non_linear_state_machine/driver_retest_loop_cycle
        """
        driver = self._driver_in_testing("D-LOOP2", "L501")
        post_driver_event(driver["id"], "TEST_FAIL", reason="Failed pretrip")
        retest = post_driver_event(driver["id"], "SCHEDULE_TEST")
        assert retest["status"] == "TESTING", (
            f"second SCHEDULE_TEST must re-enter TESTING, got {retest['status']}")
        create_credential(driver["id"], "CDL_B")
        certified = post_driver_event(driver["id"], "TEST_PASS")
        assert certified["status"] == "CERTIFIED"
        assert certified["test_fail_count"] == 1


class TestTrainingHoursThreshold:
    def test_exactly_2400_behind_wheel_qualifies(self, api):
        """PRD section 3.3: "`SCHEDULE_TEST` moves `TRAINING` to `TESTING`, and
        is gated on both aggregates: at least 2400 behind-wheel minutes and at
        least 1200 classroom minutes, both thresholds inclusive, so exactly 2400
        and 1200 qualifies while 2399 behind-wheel fails with
        `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/training_hours_inclusive_threshold
        """
        district = create_district(name="D-BND2")
        driver = create_driver_applicant(district["id"], full_name="D Exact",
                                         license_number="L120")
        post_driver_event(driver["id"], "SCREEN")
        post_driver_event(driver["id"], "ENROLL")
        log_training(driver["id"], "BEHIND_WHEEL", 2400)
        log_training(driver["id"], "CLASSROOM", 1200, occurred_on="2026-04-02")
        promoted = post_driver_event(driver["id"], "SCHEDULE_TEST")
        assert promoted["status"] == "TESTING", (
            "exactly 2400 behind-wheel + 1200 classroom must satisfy the "
            f"inclusive threshold, got {promoted['status']}")

    def test_2399_behind_wheel_rejected(self, api):
        """PRD section 3.3: "`SCHEDULE_TEST` moves `TRAINING` to `TESTING`, and
        is gated on both aggregates: at least 2400 behind-wheel minutes and at
        least 1200 classroom minutes, both thresholds inclusive, so exactly 2400
        and 1200 qualifies while 2399 behind-wheel fails with
        `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/training_hours_inclusive_threshold
        """
        district = create_district(name="D-BND2B")
        driver = create_driver_applicant(district["id"], full_name="D Short",
                                         license_number="L121")
        post_driver_event(driver["id"], "SCREEN")
        post_driver_event(driver["id"], "ENROLL")
        log_training(driver["id"], "BEHIND_WHEEL", 2399)
        log_training(driver["id"], "CLASSROOM", 1200, occurred_on="2026-04-02")
        resp = api.post_driver_event(driver["id"], {"event_type": "SCHEDULE_TEST"}, HR)
        validate_error(resp, ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT, 422)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["status"] == "TRAINING", "rejected driver stays TRAINING"


class TestSafetyMinutesExcluded:
    def test_driver_safety_minutes_excluded_from_eligibility(self, api):
        """PRD section 3.3: "every logged event recomputes the driver's
        aggregates, with `behind_wheel_minutes` summing only `BEHIND_WHEEL`
        events and `classroom_minutes` summing only `CLASSROOM` events —
        `SAFETY` minutes count toward neither."
        PRD section 3.3: "`SCHEDULE_TEST` moves `TRAINING` to `TESTING`, and is
        gated on both aggregates: at least 2400 behind-wheel minutes and at
        least 1200 classroom minutes, both thresholds inclusive, so exactly 2400
        and 1200 qualifies while 2399 behind-wheel fails with
        `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422)."

        Design: Corner/calculations/driver_safety_minutes_excluded_from_eligibility
        """
        district = create_district(name="D-CALC4")
        driver = create_driver_applicant(district["id"], full_name="D Safe",
                                         license_number="L251")
        post_driver_event(driver["id"], "SCREEN")
        post_driver_event(driver["id"], "ENROLL")
        log_training(driver["id"], "BEHIND_WHEEL", 2300)
        log_training(driver["id"], "SAFETY", 200, occurred_on="2026-04-02")
        log_training(driver["id"], "CLASSROOM", 1200, occurred_on="2026-04-03")

        resp = api.post_driver_event(driver["id"], {"event_type": "SCHEDULE_TEST"}, HR)
        validate_error(resp, ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT, 422)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["behind_wheel_minutes"] == 2300, (
            "SAFETY minutes must not substitute for BEHIND_WHEEL")
        assert fetched["status"] == "TRAINING"


class TestCredentialGating:
    def test_error_credential_expired_on_test_pass_returns_409(self, api):
        """PRD section 3.3: "Or the logical clock may advance past it: any
        credential whose `expires_on` falls before the new clock date flips from
        `ACTIVE` to `EXPIRED`."
        PRD section 3.3: "`TEST_PASS` promotes to `CERTIFIED` — but only if the
        driver already holds a credential of `kind` `CDL_B` with status `ACTIVE`,
        failing with `ERR_CREDENTIAL_EXPIRED` otherwise."

        Design: Corner/errors/error_credential_expired_on_test_pass_returns_409
        """
        district = create_district(name="D-ERR18")
        driver = create_driver_applicant(district["id"], full_name="D Err18",
                                         license_number="L286")
        advance_driver_to_testing(driver["id"])
        credential = create_credential(driver["id"], "CDL_B",
                                       issued_on="2025-04-10", expires_on="2026-04-01")
        set_clock("2026-05-02T00:00:00Z")

        cred = validate_success(api.get_credential(credential["id"], HR))
        assert cred["status"] == "EXPIRED", (
            "expires_on 2026-04-01 precedes the new clock date 2026-05-02")

        resp = api.post_driver_event(driver["id"], {"event_type": "TEST_PASS"}, HR)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRED, 409)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["status"] == "TESTING", (
            "no suspension cascade fires — the driver was not ACTIVE")

    def test_error_endorsement_missing_on_activate_returns_409(self, api):
        """PRD section 3.3: "Finally, `ACTIVATE` moves `CERTIFIED` to `ACTIVE`
        provided the driver holds an active `S_ENDORSEMENT` credential (else
        `ERR_ENDORSEMENT_MISSING`), and stamps `hired_on` with the logical clock
        date."

        Design: Corner/errors/error_endorsement_missing_on_activate_returns_409
        """
        district = create_district(name="D-ERR19")
        driver = create_driver_applicant(district["id"], full_name="D Err19",
                                         license_number="L287")
        advance_driver_to_testing(driver["id"])
        create_credential(driver["id"], "CDL_B")
        certified = post_driver_event(driver["id"], "TEST_PASS")
        assert certified["status"] == "CERTIFIED"

        resp = api.post_driver_event(driver["id"], {"event_type": "ACTIVATE"}, HR)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_MISSING, 409)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["status"] == "CERTIFIED"
        assert fetched["hired_on"] is None


class TestReinstateRequiresCredentials:
    def _suspended_driver_with_lapsed_endorsement(self, api):
        district = create_district(name="D-XD3")
        driver = create_active_driver(district["id"], full_name="D Xd3",
                                      license_number="L132",
                                      s_endorsement_expires_on="2026-06-10")
        suspend_driver(driver["id"], reason="Discipline")
        set_clock("2026-06-11T00:00:00Z")
        return district, driver

    def test_reinstate_blocked_by_expired_endorsement(self, api):
        """PRD section 3.3: "An `action` of `REINSTATE` on a `SUSPENDED` driver
        returns them to `ACTIVE` and clears `suspension_reason` to null — but
        only when the driver once again holds both an active `CDL_B` (else
        `ERR_CREDENTIAL_EXPIRED`) and an active `S_ENDORSEMENT` (else
        `ERR_ENDORSEMENT_MISSING`)."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_valid_credentials
        """
        _district, driver = self._suspended_driver_with_lapsed_endorsement(api)
        resp = api.post_driver_discipline(driver["id"], {"action": "REINSTATE"}, OPS)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_MISSING, 409)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["status"] == "SUSPENDED", "failed reinstate leaves SUSPENDED"

    def test_suspension_reason_survives_failed_reinstate(self, api):
        """PRD section 3.3: "An `action` of `SUSPEND` on an `ACTIVE` driver moves them to `SUSPENDED` with `suspension_reason` `DISCIPLINE` and fires the same assignment cascade: future `CONFIRMED` assignments on days dated on or after the clock date are cancelled with reason `DRIVER_SUSPENDED`, and each affected service day recomputes its `covered_routes`, `uncovered_routes`, and `shortage_flag`."
        PRD section 3.3: "Or the logical clock may advance past it: any
        credential whose `expires_on` falls before the new clock date flips from
        `ACTIVE` to `EXPIRED`. Either way, when the lost credential is a `CDL_B` or `S_ENDORSEMENT` and its holder is an `ACTIVE` driver, the same protective cascade fires: the driver is suspended with `suspension_reason` `CREDENTIAL_LAPSED`, their future `CONFIRMED` assignments are cancelled with reason `DRIVER_SUSPENDED`, and every affected service day recomputes its coverage and shortage fields."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_valid_credentials
        """
        _district, driver = self._suspended_driver_with_lapsed_endorsement(api)
        resp = api.post_driver_discipline(driver["id"], {"action": "REINSTATE"}, OPS)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_MISSING, 409)
        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["suspension_reason"] == "DISCIPLINE", (
            "the clock cascade only touches ACTIVE drivers; the discipline "
            "reason is unchanged")


class TestDriverTerminateCascade:
    def test_driver_terminate_cascades_future_assignments(self, api):
        """PRD section 3.3: "`TERMINATE` ends the line from any non-terminal
        state — `APPLICANT`, `SCREENING`, `TRAINING`, `TESTING`, `CERTIFIED`,
        `ACTIVE`, or `SUSPENDED` — moving the driver to terminal `TERMINATED`
        and cancelling every assignment of theirs in `PLANNED` or `CONFIRMED` on
        service days dated on or after the clock date with `cancellation_reason`
        `DRIVER_SUSPENDED`, recomputing each affected day's shortage fields."

        Design: Corner/cross_cutting_layers/driver_terminate_cascades_future_assignments
        """
        ctx = setup_ops_scenario(district_name="D-CC4")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm = get_success_data(api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS))
        assert confirm["status"] == "CONFIRMED"

        terminated = post_driver_event(ctx["driver"]["id"], "TERMINATE",
                                       reason="Resigned")
        assert terminated["status"] == "TERMINATED"

        assignment = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert assignment["status"] == "CANCELLED"
        assert assignment["cancellation_reason"] == "DRIVER_SUSPENDED"

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["uncovered_routes"] == 1
        assert day_after["shortage_flag"] is True
