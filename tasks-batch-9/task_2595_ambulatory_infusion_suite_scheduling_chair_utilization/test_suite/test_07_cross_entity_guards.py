"""Transitions whose guard lives on a different row than the one being moved."""

from test_helpers import (
    AUTH_SPECIALIST,
    ApiClient,
    ApiErrorId,
    AuthStatus,
    DoseTier,
    LotStatus,
    PHARMACIST,
    PreparationStatus,
    ReadinessStatus,
    ScheduleStatus,
    approve_authorization,
    assert_instant_equals,
    book_appointment,
    create_lot,
    confirm_visit,
    file_authorization,
    make_pend_decision_payload,
    read_appointment,
    read_authorization,
    read_chair,
    read_lot,
    read_preparation,
    request_dose,
    run_sweep,
    set_clock,
    setup_booked_visit,
    setup_suite,
    submit_authorization,
    validate_error,
    validate_success,
    SCHEDULER,
)


class TestConfirmationGuardLivesOnTheAuthorizationRow:
    """Nothing about the visit changes between the refused confirm and the accepted one."""

    def _pended_coverage(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
            drug_kind="gate",
            drug_overrides={
                "requires_lab_gate": False,
                "lab_min_anc": None,
                "lab_min_platelets": None,
            },
        )
        auth = file_authorization(api, appointment["id"])
        submit_authorization(api, auth["id"])
        validate_success(
            api.decide_authorization(
                auth["id"],
                make_pend_decision_payload("Clinical notes requested"),
                AUTH_SPECIALIST,
            ),
            200,
        )
        return suite, appointment, auth

    def test_confirmation_is_refused_while_the_coverage_sits_in_pended(self, api):
        """A visit with an authorization row but no APPROVED one is refused, and the visit
        stays exactly where it was.

        Design: Difficulty/cross_entity_state_dependency/confirm_refused_while_the_authorization_sits_in_pended_then_admitted_after_approval
        """
        _suite, appointment, auth = self._pended_coverage(api)

        response = api.confirm_appointment(appointment["id"], SCHEDULER)

        validate_error(response, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)

        assert (
            read_appointment(api, appointment["id"])["schedule_status"]
            == ScheduleStatus.TENTATIVE
        )
        coverage = read_authorization(api, auth["id"])
        assert coverage["status"] == AuthStatus.PENDED
        assert coverage["submission_count"] == 1

    def test_the_identical_call_is_admitted_once_only_the_other_row_has_moved(self, api):
        """Re-filing a pended request and recording the approval is enough on its own to
        let the same confirm call through.

        Design: Difficulty/cross_entity_state_dependency/confirm_refused_while_the_authorization_sits_in_pended_then_admitted_after_approval
        """
        _suite, appointment, auth = self._pended_coverage(api)
        api.confirm_appointment(appointment["id"], SCHEDULER)

        submit_authorization(api, auth["id"])
        approve_authorization(api, auth["id"], 4)

        coverage = read_authorization(api, auth["id"])
        assert coverage["status"] == AuthStatus.APPROVED
        assert coverage["submission_count"] == 2
        assert_instant_equals(coverage["expires_at"], "2026-09-04T07:00:00Z")

        confirmed = confirm_visit(api, appointment["id"])
        assert confirmed["schedule_status"] == ScheduleStatus.CONFIRMED
        assert confirmed["readiness_status"] == ReadinessStatus.FULLY_CLEARED

    def test_the_refused_confirmation_neither_reserved_nor_released_chair_minutes(self, api):
        """The chair has held the visit's minutes since the booking; the refused confirm
        does not touch them.

        Design: Difficulty/cross_entity_state_dependency/confirm_refused_while_the_authorization_sits_in_pended_then_admitted_after_approval
        """
        suite, appointment, auth = self._pended_coverage(api)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240

        api.confirm_appointment(appointment["id"], SCHEDULER)
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240

        submit_authorization(api, auth["id"])
        approve_authorization(api, auth["id"], 4)
        confirm_visit(api, appointment["id"])
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240


class TestCompoundingRechecksTheReferencedLot:
    """The lot leaves AVAILABLE underneath a dose that already points at it."""

    def _dose_whose_lot_the_sweep_expired(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            drug_kind="ungated",
            dose_tier=DoseTier.LOW,
            plan_overrides={"dose_mg_per_kg": 5, "total_cycles": 4},
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-SHORT",
            units_received=5,
            expires_on="2026-08-10T09:30:00Z",
        )
        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        prep = request_dose(api, appointment["id"], 2)
        set_clock(api, "2026-08-10T09:45:00Z")
        sweep = run_sweep(api, suite.center_id, "2026-08-11")
        return suite, lot, appointment, prep, sweep

    def test_the_sweep_expires_the_lot_without_touching_the_pinned_reference(self, api):
        """The ops checkpoint moves the lot out of AVAILABLE on the clock alone, leaving
        its committed units and the dose's foreign key exactly as they were.

        Design: Difficulty/cross_entity_state_dependency/prepare_refused_after_the_daily_sweep_expired_the_already_selected_lot
        """
        _suite, lot, _appointment, prep, sweep = self._dose_whose_lot_the_sweep_expired(api)

        assert sweep["expired_lot_count"] == 1
        assert sweep["expired_authorization_count"] == 0
        assert sweep["wasted_preparation_count"] == 0
        assert sweep["no_show_count"] == 0

        row = read_lot(api, lot["id"])
        assert row["status"] == LotStatus.EXPIRED
        assert row["units_committed"] == 2
        assert row["units_available"] == 3

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.REQUESTED
        assert dose["drug_lot_id"] == lot["id"]

    def test_mixing_checks_the_lot_state_and_not_only_the_dose_state(self, api):
        """The dose's own status is perfectly legal for mixing, so the refusal must name
        the backing lot instead.

        Design: Difficulty/cross_entity_state_dependency/prepare_refused_after_the_daily_sweep_expired_the_already_selected_lot
        """
        _suite, _lot, _appointment, prep, _sweep = self._dose_whose_lot_the_sweep_expired(
            api
        )

        response = api.prepare_dose(prep["id"], PHARMACIST)

        body = validate_error(response, ApiErrorId.ERR_LOT_NOT_AVAILABLE, 409)
        assert body["error_id"] != ApiErrorId.ERR_INVALID_PREPARATION_STATE

    def test_the_refusal_leaves_the_dose_unmixed_and_the_visit_unswept(self, api):
        """Nothing is stamped on a refused mix, and a sweep aimed at another service date
        never no-shows this visit.

        Design: Difficulty/cross_entity_state_dependency/prepare_refused_after_the_daily_sweep_expired_the_already_selected_lot
        """
        _suite, _lot, appointment, prep, _sweep = self._dose_whose_lot_the_sweep_expired(
            api
        )

        api.prepare_dose(prep["id"], PHARMACIST)

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.REQUESTED
        assert dose["prepared_at"] is None
        assert dose["usable_until"] is None

        assert (
            read_appointment(api, appointment["id"])["schedule_status"]
            == ScheduleStatus.TENTATIVE
        )
