"""Inspections, permission to operate, and withdrawal lockdown/cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    api_client,
    assert_instant_equal,
    create_draft_application,
    create_inspection_payload,
    create_meter_exchange_payload,
    drive_to_pto_granted,
    drive_to_screen_passed,
    get_account,
    get_application,
    get_program,
    get_success_data,
    make_inspector_headers,
    make_technician_headers,
    record_inspection_result_payload,
    schedule_and_complete_exchange,
    set_clock,
    setup_program_with_grid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]

SCHEDULED_AT = "2026-08-05T09:00:00Z"
OCCURRED_AT = "2026-08-05T10:00:00Z"


def _screen_passed(name, with_tariff=True):
    sc = setup_program_with_grid(name, with_tariff=with_tariff)
    ctx = add_customer_account(sc, "1")
    app = drive_to_screen_passed(sc, ctx, size=10_000, production=15_000_000)
    return sc, ctx, app


def _exchange_done(app_id, technician_id="tech-1", serial="MTR-1"):
    return schedule_and_complete_exchange(
        app_id, technician_id=technician_id, meter_serial=serial)


def _schedule_inspection(ctx, app_id, scheduled_date=SCHEDULED_AT):
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(app_id, scheduled_date=scheduled_date),
        ctx["applicant"]))


def _pto_ready(name, technician_id="tech-1"):
    """SCREEN_PASSED + COMPLETED exchange + SCHEDULED inspection, clock at
    2026-08-06 (after the inspection date)."""
    sc, ctx, app = _screen_passed(name)
    _exchange_done(app["id"], technician_id=technician_id)
    inspection = _schedule_inspection(ctx, app["id"])
    set_clock("2026-08-06T00:00:00Z")
    return sc, ctx, app, inspection


class TestRecordResultPriority:
    def test_state_error_beats_temporal_error(self, api):
        """PRD §2.10: "Every request is evaluated against an ordered pipeline
        of checks, and when several checks could reject the same request, the
        earliest check in this order determines the error returned."
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline). Ninth,
        segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Tenth, temporal
        windows (`ERR_ESTIMATE_EXPIRED`, `ERR_INSPECTION_DATE_INVALID`,
        `ERR_TRUE_UP_WINDOW_NOT_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/pvc_state_beats_temporal_on_record_result
        """
        sc, ctx, app, inspection = _pto_ready("PV1")
        get_success_data(
            api.cancel_inspection(inspection["id"], ctx["applicant"]))

        # The inspection is CANCELLED (state violation, eighth) AND the
        # occurred_at instant is after the clock (temporal violation, tenth).
        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": "2026-08-07T00:00:00Z"},
            make_inspector_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_inspection(inspection["id"], ADMIN))
        assert after["inspection_status"] == "CANCELLED"

    def test_state_error_beats_temporal_error_on_recorded_inspection(
            self, api):
        """PRD §2.10: "when several checks could reject the same request, the
        earliest check in this order determines the error returned."
        PRD §3.7: "A recorded result moves the inspection to `RESULT_RECORDED`
        and stores `inspector_user_id`"

        Design: Difficulty/priority_pair_validation_conflict/pvc_state_beats_temporal_on_record_result
        """
        sc, ctx, app, inspection = _pto_ready("PV1B")
        recorded = validate_success(api.record_inspection_result(
            inspection["id"],
            record_inspection_result_payload(outcome="PASSED",
                                             occurred_at=OCCURRED_AT),
            make_inspector_headers("insp-1")))
        assert recorded["inspection_status"] == "RESULT_RECORDED"

        # Re-recording violates the state machine; the future occurred_at also
        # violates the temporal window. State (eighth) wins.
        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": "2026-08-07T00:00:00Z"},
            make_inspector_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_inspection(inspection["id"], ADMIN))
        assert after["outcome"] == "PASSED"


class TestSegregationOfDuties:
    def test_safety_beats_missing_defects_constraint(self, api):
        """PRD §2.10: "Ninth, segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`). Tenth, temporal windows
        (`ERR_ESTIMATE_EXPIRED`, `ERR_INSPECTION_DATE_INVALID`,
        `ERR_TRUE_UP_WINDOW_NOT_OPEN`). Eleventh, structural business rules
        such as window overlaps, one-active-record uniqueness, document-set
        completeness, and eligibility limits."
        PRD §3.7: "Segregation of duties is enforced at this point: the
        inspector recording the result must not be the same individual as the
        `technician_user_id` who completed that application's meter exchange,
        and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/pvc_safety_beats_constraint_on_record_result
        """
        # The exchange was completed by technician user "tech-x".
        sc, ctx, app, inspection = _pto_ready("PV2", technician_id="tech-x")

        # The recording inspector IS that technician (ninth), and the FAILED
        # outcome omits the defects narrative (eleventh) — safety wins.
        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "FAILED", "occurred_at": OCCURRED_AT},
            make_inspector_headers("tech-x"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        after = validate_success(api.get_inspection(inspection["id"], ADMIN))
        assert after["inspection_status"] == "SCHEDULED"

    def test_exchange_technician_cannot_record_result(self, api):
        """PRD §3.7: "the inspector recording the result must not be the same
        individual as the `technician_user_id` who completed that application's
        meter exchange, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/pvc_safety_beats_constraint_on_record_result
        """
        sc, ctx, app, inspection = _pto_ready("PV2B", technician_id="tech-x")

        # Same individual, otherwise-clean request: still rejected.
        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "FAILED", "occurred_at": OCCURRED_AT,
             "defects": "missing rapid shutdown label"},
            make_inspector_headers("tech-x"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

        # A different inspector records the same FAILED outcome cleanly.
        recorded = validate_success(api.record_inspection_result(
            inspection["id"],
            {"outcome": "FAILED", "occurred_at": OCCURRED_AT,
             "defects": "missing rapid shutdown label"},
            make_inspector_headers("insp-9")))
        assert recorded["inspection_status"] == "RESULT_RECORDED"
        assert recorded["outcome"] == "FAILED"
        assert recorded["inspector_user_id"] == "insp-9"


class TestPermissionToOperateGates:
    def test_exchange_gate_then_inspection_gate(self, api):
        """PRD §3.8: "Four gates guard the grant, and the order between two of
        them is pinned: the account must be `ACTIVE`
        (`ERR_ACCOUNT_NOT_ACTIVE`); a completed meter exchange must exist for
        the application (`ERR_METER_EXCHANGE_NOT_COMPLETED`, checked before the
        inspection gate); the latest inspection — the one with the greatest
        `created_at` — must be `RESULT_RECORDED` with `outcome` `PASSED`
        (`ERR_INSPECTION_NOT_PASSED`); and a tariff schedule of the program
        must be effective at the current clock time
        (`ERR_NO_EFFECTIVE_TARIFF`)."

        Design: Difficulty/cross_entity_state_dependency/cesd_pto_requires_exchange_and_passed_inspection
        """
        sc = setup_program_with_grid("PTO")
        ctx1 = add_customer_account(sc, "1")
        app1 = drive_to_screen_passed(sc, ctx1, size=10_000,
                                      production=15_000_000)

        ctx2 = add_customer_account(sc, "2")
        app2 = drive_to_screen_passed(sc, ctx2, size=10_000,
                                      production=15_000_000)
        _exchange_done(app2["id"], technician_id="tech-2")
        inspection2 = _schedule_inspection(ctx2, app2["id"])
        set_clock("2026-08-06T00:00:00Z")
        recorded = validate_success(api.record_inspection_result(
            inspection2["id"],
            {"outcome": "FAILED", "occurred_at": OCCURRED_AT,
             "defects": "missing rapid shutdown label"},
            make_inspector_headers("insp-2")))
        assert recorded["outcome"] == "FAILED"

        # app1: no completed exchange exists — the exchange gate fires.
        resp = api.grant_pto(app1["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_METER_EXCHANGE_NOT_COMPLETED, 422)

        # app2: exchange completed but the latest inspection FAILED.
        resp = api.grant_pto(app2["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED, 422)

        assert (get_application(app1["id"])["application_status"]
                == "SCREEN_PASSED")
        assert (get_application(app2["id"])["application_status"]
                == "SCREEN_PASSED")

    def test_latest_inspection_controls_the_gate(self, api):
        """PRD §3.8: "the latest inspection — the one with the greatest
        `created_at` — must be `RESULT_RECORDED` with `outcome` `PASSED`
        (`ERR_INSPECTION_NOT_PASSED`)"

        Design: Difficulty/cross_entity_state_dependency/cesd_pto_requires_exchange_and_passed_inspection
        """
        sc, ctx, app, inspection1 = _pto_ready("PTO2")
        recorded = validate_success(api.record_inspection_result(
            inspection1["id"],
            {"outcome": "FAILED", "occurred_at": OCCURRED_AT,
             "defects": "mislabeled disconnect"},
            make_inspector_headers("insp-1")))
        assert recorded["outcome"] == "FAILED"

        # A newer inspection that passes supersedes the failed verdict.
        inspection2 = _schedule_inspection(ctx, app["id"],
                                           scheduled_date="2026-08-07T09:00:00Z")
        set_clock("2026-08-08T00:00:00Z")
        validate_success(api.record_inspection_result(
            inspection2["id"],
            {"outcome": "PASSED", "occurred_at": "2026-08-07T10:00:00Z"},
            make_inspector_headers("insp-2")))

        app = validate_success(api.grant_pto(app["id"], COORDINATOR))
        assert app["application_status"] == "PTO_GRANTED"
        assert (get_account(ctx["account"]["id"])["metering_status"]
                == "NET_METERING")

    def test_pto_requires_effective_tariff(self, api):
        """PRD §3.8: "a tariff schedule of the program must be effective at the
        current clock time (`ERR_NO_EFFECTIVE_TARIFF`)."

        Design: Corner/validations/v_pto_requires_effective_tariff
        """
        # No tariff schedule exists on this program at all.
        sc = setup_program_with_grid("NTG2", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = drive_to_screen_passed(sc, ctx, size=10_000,
                                     production=15_000_000)
        _exchange_done(app["id"])
        inspection = _schedule_inspection(ctx, app["id"])
        set_clock("2026-08-06T00:00:00Z")
        validate_success(api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": OCCURRED_AT},
            make_inspector_headers("insp-1")))

        resp = api.grant_pto(app["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_TARIFF, 422)
        assert (get_application(app["id"])["application_status"]
                == "SCREEN_PASSED")


class TestInspectionTemporalWindow:
    def test_occurred_at_before_scheduled_rejected(self, api):
        """PRD §3.7: "the `occurred_at` instant must fall on or after
        `scheduled_date` and on or before the current clock time — outside
        that window the record is rejected with `ERR_INSPECTION_DATE_INVALID`"

        Design: Corner/validations/v_occurred_at_before_scheduled_rejected
        """
        sc, ctx, app, inspection = _pto_ready("OB")
        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": "2026-08-04T10:00:00Z"},
            make_inspector_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_DATE_INVALID, 422)
        after = validate_success(api.get_inspection(inspection["id"], ADMIN))
        assert after["inspection_status"] == "SCHEDULED"

    def test_scheduled_date_in_the_past_rejected(self, api):
        """PRD §3.7: "With a completed exchange in place, the applicant
        requests an inspection, proposing a `scheduled_date` that must not be
        earlier than the current clock time (otherwise
        `ERR_INSPECTION_DATE_INVALID`)"
        PRD §2.10: "Tenth, temporal windows (`ERR_ESTIMATE_EXPIRED`,
        `ERR_INSPECTION_DATE_INVALID`, `ERR_TRUE_UP_WINDOW_NOT_OPEN`).
        Eleventh, structural business rules such as window overlaps,
        one-active-record uniqueness, document-set completeness, and
        eligibility limits. Twelfth, cross-entity gates such as program and
        account status, metering status, and prerequisite field work."

        Design: Corner/validations/v_inspection_scheduled_in_past_rejected
        """
        # SCREEN_PASSED without a meter exchange: the temporal check (tenth)
        # fires before the completed-exchange gate (twelfth).
        sc, ctx, app = _screen_passed("IP")
        resp = api.create_inspection(
            create_inspection_payload(
                app["id"], scheduled_date="2026-07-01T09:00:00Z"),
            ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INSPECTION_DATE_INVALID, 422)

    def test_occurred_at_equal_to_now_accepted(self, api):
        """PRD §3.7: "the `occurred_at` instant must fall on or after
        `scheduled_date` and on or before the current clock time — outside
        that window the record is rejected with `ERR_INSPECTION_DATE_INVALID`"

        Design: Corner/cross_cutting_complexity_layers/cc_temporal_occurred_at_equals_now_allowed
        """
        sc, ctx, app = _screen_passed("TW2")
        _exchange_done(app["id"])
        inspection = _schedule_inspection(ctx, app["id"])
        # The clock IS the occurred instant: both window ends are closed.
        set_clock(OCCURRED_AT)
        recorded = validate_success(api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": OCCURRED_AT},
            make_inspector_headers("insp-1")))
        assert recorded["inspection_status"] == "RESULT_RECORDED"
        assert recorded["outcome"] == "PASSED"


class TestWithdrawalRules:
    def test_pto_granted_blocks_withdrawal(self, api):
        """PRD §3.6: "Any application in a non-terminal status other than
        `PTO_GRANTED` or `OPERATING` may be withdrawn — attempting withdrawal
        from those two states is rejected with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/sm_pto_granted_blocks_withdrawal
        """
        sc = setup_program_with_grid("SP")
        ctx = add_customer_account(sc, "1")
        result = drive_to_pto_granted(sc, ctx, size=10_000,
                                      production=15_000_000)
        resp = api.withdraw_application(result["app"]["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert (get_application(result["app"]["id"])["application_status"]
                == "PTO_GRANTED")

    def test_withdrawn_application_is_terminal(self, api):
        """PRD §3.6: "Any application in a non-terminal status other than
        `PTO_GRANTED` or `OPERATING` may be withdrawn — attempting withdrawal
        from those two states is rejected with `ERR_INVALID_STATE` — and lands
        in `WITHDRAWN` with `withdrawal_reason` `APPLICANT_WITHDRAWN`."

        Design: Corner/state_machines/sm_withdraw_terminal_lockdown
        """
        sc = setup_program_with_grid("SW", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        app = validate_success(
            api.withdraw_application(app["id"], ctx["applicant"]))
        assert app["application_status"] == "WITHDRAWN"
        assert app["withdrawal_reason"] == "APPLICANT_WITHDRAWN"

        resp = api.withdraw_application(app["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert (get_application(app["id"])["application_status"]
                == "WITHDRAWN")

    def test_withdraw_cancels_only_non_terminal_children(self, api):
        """PRD §3.6: "Dependent records are settled in kind: `OPEN`
        supplemental reviews move to `CLOSED`, still-`ISSUED` cost estimates
        move to `CANCELLED`, `SCHEDULED` inspections move to `CANCELLED`, and
        `SCHEDULED` or `FAILED` meter exchanges move to `CANCELLED`."

        Design: Corner/cross_cutting_complexity_layers/cc_withdraw_cancels_only_non_terminal_children
        """
        sc, ctx, app = _screen_passed("WC")
        ex1 = _exchange_done(app["id"], technician_id="tech-1",
                             serial="MTR-1")
        inspection = _schedule_inspection(ctx, app["id"])
        # A second exchange is schedulable because the first is COMPLETED.
        ex2 = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-2",
                window_start="2026-08-12T09:00:00Z",
                window_end="2026-08-12T11:00:00Z"), TECHNICIAN))
        assert ex2["exchange_status"] == "SCHEDULED"

        app = validate_success(
            api.withdraw_application(app["id"], ctx["applicant"]))
        assert app["application_status"] == "WITHDRAWN"
        assert app["capacity_reserved_watts"] == 0

        after_insp = validate_success(
            api.get_inspection(inspection["id"], ADMIN))
        assert after_insp["inspection_status"] == "CANCELLED"
        after_ex2 = validate_success(api.get_meter_exchange(ex2["id"], ADMIN))
        assert after_ex2["exchange_status"] == "CANCELLED"
        after_ex1 = validate_success(api.get_meter_exchange(ex1["id"], ADMIN))
        assert after_ex1["exchange_status"] == "COMPLETED", (
            "terminal children are untouched by the withdrawal cascade")

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 0
        assert program["available_capacity_watts"] == 1_000_000


class TestOneScheduledInspection:
    def test_second_scheduled_inspection_rejected(self, api):
        """PRD §3.7: "the request requires the application to be
        `SCREEN_PASSED`, a completed meter exchange to exist for it (otherwise
        `ERR_METER_EXCHANGE_NOT_COMPLETED`), and no other `SCHEDULED`
        inspection to be outstanding for the same application (otherwise
        `ERR_INSPECTION_EXISTS`)."

        Design: Corner/errors/err_inspection_exists_blocks_second
        """
        sc, ctx, app = _screen_passed("IE")
        _exchange_done(app["id"])
        _schedule_inspection(ctx, app["id"])

        resp = api.create_inspection(
            create_inspection_payload(
                app["id"], scheduled_date="2026-08-06T09:00:00Z"),
            ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INSPECTION_EXISTS, 422)
