"""Declared initial states, refused triggers, terminal lockdown, refused
replays, the excess-event return cycle, and the slot a retirement releases."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_control_outage_window,
    assert_excess_emission_event,
    assert_fuel_sample,
    assert_rata_test,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    certification_payload,
    fuel_sample_payload,
    rata_runs_payload,
)

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
CLOCK_APRIL = "2026-04-02T00:00:00Z"
OPERATOR_ORG = "op_alpha"
STATEMENT = "I certify under penalty of law that the submitted data are true and complete."


def _read(getter, resource_id, headers=None):
    return validate_success(getter(resource_id, headers or fx.REVIEWER))


class TestDeclaredInitialStates:
    """Eight freshly created rows, none of which accepted a status input."""

    def test_every_new_row_sits_in_the_state_the_specification_declares(self):
        """A monitor starts on both axes at once and a proposal moves no holdings.

        PRD: "A new system starts with `qa_status` of `RECERTIFICATION_PENDING`,
        `cal_status` of `CAL_EXPIRED`, `bias_adjustment_factor` of 1.0 and
        `consecutive_failed_calibrations` of 0."

        PRD: "A first attempt records `attempt_number` of 1 and leaves
        `retest_of_rata_test_id` null."

        PRD: "A new sample stands at `PENDING` with no analysis values."

        PRD: "A planned window starts in `PLANNED` and leaves the unit's
        `control_status` untouched."

        Design: Corner/state_machines/sm_every_machine_starts_in_its_declared_initial_state
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST)
        facility_id = station["facility"]["id"]
        unit_id = station["unit"]["id"]

        system = fx.install_monitoring_system(
            unit_id, parameter="SO2", system_type="CEM", span_value=400.0
        )
        assert system["qa_status"] == "RECERTIFICATION_PENDING"
        assert system["cal_status"] == "CAL_EXPIRED", (
            "the two axes are initialised independently"
        )
        assert system["bias_adjustment_factor"] == 1.0
        assert system["consecutive_failed_calibrations"] == 0

        rata_test = validate_success(
            api_client.schedule_rata_test(
                system["id"],
                {
                    "window_start_utc": "2026-08-10T00:00:00Z",
                    "window_end_utc": "2026-08-11T00:00:00Z",
                },
                fx.QA,
            ),
            201,
        )
        assert_rata_test(rata_test)
        assert rata_test["status"] == "SCHEDULED"
        assert rata_test["attempt_number"] == 1
        assert rata_test["run_count"] == 0
        assert rata_test["retest_of_rata_test_id"] is None

        sample = validate_success(
            api_client.record_fuel_sample(
                unit_id,
                fuel_sample_payload(sample_utc=CLOCK_AUGUST),
                fx.make_facility_operator_headers(OPERATOR_ORG),
            ),
            201,
        )
        assert_fuel_sample(sample)
        assert sample["status"] == "PENDING"
        assert sample["analyzed_utc"] is None

        report = fx.open_quarterly_report(unit_id)
        assert report["status"] == "DRAFT"

        outage = fx.plan_control_outage(
            unit_id,
            OPERATOR_ORG,
            start_utc="2026-08-20T00:00:00Z",
            end_utc="2026-08-22T00:00:00Z",
        )
        assert_control_outage_window(outage)
        assert outage["status"] == "PLANNED"
        assert outage["activated_utc"] is None

        account = fx.open_allowance_account(
            facility_id,
            holdings_current_vintage_tons=10.000,
            holdings_prior_vintage_tons=0.000,
            holdings_next_vintage_tons=0.000,
        )
        assert account["status"] == "OPEN"
        assert account["shortfall_tons"] == 0.0
        assert account["true_up_utc"] is None

        transaction = fx.propose_transaction(
            account["id"],
            account["version"],
            transaction_type="PURCHASE",
            quantity_tons=4.000,
            vintage_year=2026,
        )
        assert transaction["status"] == "PROPOSED"
        assert transaction["origin"] == "MANUAL"
        assert transaction["debited_prior_tons"] == 0.0
        assert transaction["debited_current_tons"] == 0.0
        assert transaction["debited_next_tons"] == 0.0

        after = _read(api_client.get_allowance_account, account["id"], fx.TRADER)
        assert after["holdings_current_vintage_tons"] == 10.000, (
            "a proposal moves no holdings at all"
        )
        assert _read(api_client.get_unit, unit_id)["dispatch_state"] == "OFFLINE"


class TestRefusedTriggers:
    """A state accepts only the triggers declared out of it."""

    def test_a_draft_report_refuses_submit_certify_disposition_and_reopen(self):
        """Four refusals, then the one declared trigger works and repeats fail.

        PRD: "The lifecycle runs `DRAFT` → `VALIDATED` → `SUBMITTED` →
        `CERTIFIED` → `ACCEPTED`, with two loops back: `CERTIFIED` → `REJECTED` →
        `DRAFT`, and `VALIDATED` → `DRAFT`."

        PRD: "(47) `ERR_REASON_REQUIRED` — evaluated last of all, so a reason-less
        rejection of a report that is not certified reports
        `ERR_INVALID_STATE_TRANSITION` instead."

        Design: Corner/state_machines/sm_report_rejects_every_trigger_absent_from_its_current_state
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        report_id = station["report"]["id"]
        assert station["report"]["status"] == "DRAFT"
        assert station["report"]["version"] == 2, (
            "only the bulk append has moved the report so far"
        )

        refusals = (
            api_client.submit_quarterly_report(
                report_id, {"submission_format": "XML_ECMPS"}, fx.PREPARER
            ),
            api_client.sign_certification(
                report_id,
                certification_payload(
                    station["report"]["version"], statement_text=STATEMENT
                ),
                fx.REPRESENTATIVE,
            ),
            api_client.disposition_quarterly_report(
                report_id, {"decision": "ACCEPT"}, fx.REVIEWER
            ),
            api_client.reopen_quarterly_report(report_id, {}, fx.PREPARER),
        )
        for response in refusals:
            validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        untouched = _read(api_client.get_quarterly_report, report_id, fx.PREPARER)
        assert untouched["status"] == "DRAFT"
        assert untouched["version"] == 2, (
            f"four refusals spent no version, got {untouched['version']}"
        )

        validated = validate_success(
            api_client.validate_quarterly_report(report_id, {}, fx.PREPARER)
        )
        assert validated["status"] == "VALIDATED"
        assert validated["version"] == 3

        second_validate = api_client.validate_quarterly_report(
            report_id, {}, fx.PREPARER
        )
        validate_error(
            second_validate, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
        )
        assert (
            _read(api_client.get_quarterly_report, report_id, fx.PREPARER)["version"]
            == 3
        )

        _, meta = validate_paginated(
            api_client.list_certifications(
                fx.REVIEWER, {"quarterly_report_id": report_id}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused signature created no certification, got {meta['total_count']}"
        )

    def test_a_cancelled_window_and_a_passed_audit_refuse_everything(self):
        """Five triggers against two dead rows, and both versions stay frozen.

        PRD: "`CLOSED` and `CANCELLED` are both terminal."

        PRD: "`PASSED` and `VOIDED` are the two terminal outcomes; `FAILED` is not
        terminal, precisely because of this loop."

        Design: Corner/state_machines/sm_terminal_rows_refuse_every_further_trigger
        """
        station = fx.setup_scheduled_rata_test(
            parameter="SO2", span_value=400.0, online=True, clock=CLOCK_APRIL
        )
        unit_id = station["unit"]["id"]
        rata_id = station["rata_test"]["id"]

        outage = fx.plan_control_outage(
            unit_id,
            OPERATOR_ORG,
            start_utc="2026-04-20T00:00:00Z",
            end_utc="2026-04-22T00:00:00Z",
        )
        cancelled = fx.transition_control_outage(
            outage["id"],
            OPERATOR_ORG,
            "CANCEL",
            reason="Turbine outage deferred to the autumn window.",
        )
        assert cancelled["status"] == "CANCELLED"
        cancelled_version = cancelled["version"]

        fx.record_rata_runs(rata_id, fx.RATA_RUNS_PASSING)
        passed = fx.evaluate_rata_test(rata_id)
        assert passed["status"] == "PASSED"
        assert passed["relative_accuracy_pct"] == 10.0
        passed_version = passed["version"]

        operator = fx.make_facility_operator_headers(OPERATOR_ORG)
        for action in ("ACTIVATE", "CLOSE"):
            validate_error(
                api_client.transition_control_outage(
                    outage["id"], {"action": action}, operator
                ),
                ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            )
        validate_error(
            api_client.record_rata_runs(
                rata_id, rata_runs_payload(fx.RATA_RUNS_PASSING), fx.QA
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.evaluate_rata_test(
                rata_id, {"ra_basis": "REFERENCE_MEAN"}, fx.QA
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.reschedule_rata_test(
                rata_id,
                {
                    "window_start_utc": "2026-05-01T00:00:00Z",
                    "window_end_utc": "2026-05-02T00:00:00Z",
                },
                fx.QA,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

        outage_after = _read(api_client.get_control_outage, outage["id"])
        assert outage_after["status"] == "CANCELLED"
        assert outage_after["version"] == cancelled_version

        rata_after = _read(api_client.get_rata_test, rata_id, fx.QA)
        assert rata_after["status"] == "PASSED"
        assert rata_after["version"] == passed_version
        assert rata_after["window_start_utc"] == station["rata_test"]["window_start_utc"], (
            "the refused reschedule did not move the window"
        )

        assert _read(api_client.get_unit, unit_id)["control_status"] == "AVAILABLE", (
            "the refused ACTIVATE had no side effect on the unit"
        )

    def test_replaying_a_completed_trigger_is_refused_and_overwrites_nothing(self):
        """A second CERTIFY and a second ANALYZED both answer 409.

        PRD: "`RETIRED` is terminal on the QA axis, and every one of these four
        actions is rejected with `ERR_INVALID_STATE_TRANSITION` when the requested
        move is not one of those listed above."

        PRD: "With an `outcome` of `ANALYZED`, applied to a sample standing at
        either `PENDING` or `INVALIDATED`, the analyst must supply all three of
        `gcv_btu_per_lb` (the gross calorific value, between 1000 and 20000
        inclusive), `sulfur_content_pct` (the sulfur content as a weight percent,
        from 0.0 through 10.0 inclusive) and `analysis_method`, one of
        `ASTM_D5865`, `ASTM_D4239` or `GC_D1945`; any of the three missing is
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/sm_repeating_a_completed_trigger_is_refused_not_absorbed
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        system = fx.install_monitoring_system(
            unit_id, parameter="SO2", system_type="CEM", span_value=400.0
        )
        fx.record_daily_calibration(
            system["id"],
            system["version"],
            calibration_utc="2026-04-01T00:00:00Z",
            span_reference_value=360.0,
            span_measured_value=368.0,
        )
        sample = validate_success(
            api_client.record_fuel_sample(
                unit_id,
                fuel_sample_payload(),
                fx.make_facility_operator_headers(OPERATOR_ORG),
            ),
            201,
        )

        certified = fx.drive_qa_status(system["id"], "CERTIFY")
        assert certified["qa_status"] == "CERTIFIED"
        certified_version = certified["version"]

        validate_error(
            api_client.drive_qa_status(system["id"], {"action": "CERTIFY"}, fx.QA),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        assert (
            _read(api_client.get_monitoring_system, system["id"], fx.QA)["version"]
            == certified_version
        ), "the refused replay spent no version"

        analyzed = validate_success(
            api_client.record_fuel_analysis(
                sample["id"],
                {
                    "outcome": "ANALYZED",
                    "gcv_btu_per_lb": 12500.0,
                    "sulfur_content_pct": 0.85,
                    "analysis_method": "ASTM_D5865",
                },
                fx.QA,
            )
        )
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["gcv_btu_per_lb"] == 12500.0
        assert analyzed["sulfur_content_pct"] == 0.85
        analyzed_version = analyzed["version"]

        validate_error(
            api_client.record_fuel_analysis(
                sample["id"],
                {
                    "outcome": "ANALYZED",
                    "gcv_btu_per_lb": 12600.0,
                    "sulfur_content_pct": 0.90,
                    "analysis_method": "ASTM_D5865",
                },
                fx.QA,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        after = _read(api_client.get_fuel_sample, sample["id"], fx.QA)
        assert after["gcv_btu_per_lb"] == 12500.0, (
            "the replayed body must not overwrite the stored analysis"
        )
        assert after["sulfur_content_pct"] == 0.85
        assert after["version"] == analyzed_version


class TestCyclesAndReleasedSlots:
    """Two side effects of a transition: a counter, and a uniqueness slot."""

    def test_the_return_edge_is_a_real_cycle_counted_once(self):
        """DETECTED to EXCUSED via one RETURN, with return_count exactly 1.

        PRD: "`RETURN` requires a `reason`, records it as `disposition_reason`,
        raises `return_count` by one and sends the event **back** to `REPORTED` — a
        genuine loop, since the same row can be reviewed again."

        PRD: "`EXCUSED`, `ENFORCEABLE` and `WITHDRAWN` are the three terminal
        outcomes; a reason-less `RETURN` or `EXCUSE` is `ERR_REASON_REQUIRED`."

        Design: Corner/state_machines/sm_excess_event_return_loop_is_a_true_cycle_with_a_counter
        """
        station = fx.setup_exceeded_permit_limit(
            hour_count=3,
            limit_value=250.0,
            anchor_utc="2026-04-01T03:00:00Z",
            effective_from_utc="2026-04-01T00:00:00Z",
        )
        limit = station["permit_limit"]
        assert limit["evaluation_status"] == "EXCEEDED"
        assert limit["current_rolling_value"] == 292.2
        assert limit["window_sample_count"] == 3

        event = station["event"]
        assert_excess_emission_event(event)
        assert event["status"] == "DETECTED"
        assert event["observed_value"] == 292.2
        assert event["limit_value_snapshot"] == 250.0
        assert event["penalty_allowance_debit_tons"] == 17
        event_id = event["id"]

        narrative = "FGD absorber module tripped on low pH at 00:10 on 2026-04-01."
        reported = validate_success(
            api_client.file_excess_emission_report(
                event_id,
                {
                    "narrative": narrative,
                    "corrective_action": "Reagent feed pump replaced; module returned to service.",
                },
                fx.PREPARER,
            )
        )
        assert reported["status"] == "REPORTED"
        assert reported["narrative"] == narrative
        assert reported["return_count"] == 0

        under_review = validate_success(
            api_client.review_excess_emission_event(event_id, {}, fx.REVIEWER)
        )
        assert under_review["status"] == "UNDER_REVIEW"

        validate_error(
            api_client.disposition_excess_emission_event(
                event_id, {"decision": "RETURN"}, fx.REVIEWER
            ),
            ApiErrorId.ERR_REASON_REQUIRED.value,
        )
        still_under_review = _read(api_client.get_excess_emission_event, event_id)
        assert still_under_review["status"] == "UNDER_REVIEW"
        assert still_under_review["return_count"] == 0

        reason = "Narrative omits the root cause of the pH excursion."
        returned = validate_success(
            api_client.disposition_excess_emission_event(
                event_id, {"decision": "RETURN", "reason": reason}, fx.REVIEWER
            )
        )
        assert returned["status"] == "REPORTED", "the RETURN edge closes the loop"
        assert returned["return_count"] == 1
        assert returned["disposition_reason"] == reason

        second_review = validate_success(
            api_client.review_excess_emission_event(event_id, {}, fx.REVIEWER)
        )
        assert second_review["status"] == "UNDER_REVIEW"
        assert second_review["return_count"] == 1, "review is not a return"

        excused = validate_success(
            api_client.disposition_excess_emission_event(
                event_id,
                {
                    "decision": "EXCUSE",
                    "reason": "Malfunction was sudden and unavoidable; corrective action accepted.",
                },
                fx.REVIEWER,
            )
        )
        assert excused["status"] == "EXCUSED"
        assert excused["return_count"] == 1
        assert excused["penalty_allowance_debit_tons"] == 17
        assert excused["narrative"] == narrative, "the loop preserved the narrative"
        assert excused["version"] == 6, (
            "detect, report, review, return, review, excuse is six versions, got "
            f"{excused['version']}"
        )

    def test_retiring_the_incumbent_frees_the_parameter_slot_it_held(self):
        """A duplicate SO2 system is refused, then accepted after the RETIRE.

        PRD: "A unit may hold only one live system per parameter: a second system
        for the same `parameter` on the same unit is rejected with
        `ERR_DUPLICATE_MONITORING_SYSTEM` unless the incumbent has been retired,
        since retirement releases the slot."

        PRD: "`RETIRE` moves a system from `CERTIFIED` to `RETIRED`, increments the
        `version`, and releases the parameter slot on the unit so a replacement
        instrument can be installed for the same `parameter`."

        Design: Corner/state_machines/sm_retiring_a_monitor_releases_its_parameter_slot
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        incumbent = fx.setup_certified_cem(unit_id)["system"]

        duplicate = api_client.install_monitoring_system(
            unit_id,
            {
                "parameter": "SO2",
                "system_type": "CEM",
                "span_value": 500.0,
                "calibration_error_spec_pct": 2.5,
            },
            fx.QA,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_MONITORING_SYSTEM.value)

        other_parameter = validate_success(
            api_client.install_monitoring_system(
                unit_id,
                {
                    "parameter": "NOX_RATE",
                    "system_type": "CEM",
                    "span_value": 0.8,
                    "calibration_error_spec_pct": 2.5,
                },
                fx.QA,
            ),
            201,
        )
        assert other_parameter["parameter"] == "NOX_RATE", (
            "the slot is (unit, parameter), so a different parameter is free"
        )

        retired = fx.drive_qa_status(incumbent["id"], "RETIRE")
        assert retired["qa_status"] == "RETIRED"

        replacement = validate_success(
            api_client.install_monitoring_system(
                unit_id,
                {
                    "parameter": "SO2",
                    "system_type": "CEM",
                    "span_value": 500.0,
                    "calibration_error_spec_pct": 2.5,
                },
                fx.QA,
            ),
            201,
        )
        assert replacement["span_value"] == 500.0
        assert replacement["qa_status"] == "RECERTIFICATION_PENDING"
        assert replacement["cal_status"] == "CAL_EXPIRED"

        still_readable = _read(
            api_client.get_monitoring_system, incumbent["id"], fx.QA
        )
        assert still_readable["qa_status"] == "RETIRED", (
            "retirement is not deletion; the row is still addressable"
        )

        _, meta = validate_paginated(
            api_client.list_monitoring_systems(fx.QA, {"unit_id": unit_id})
        )
        assert meta["total_count"] == 3, (
            f"the retired row still counts in the listing, got {meta['total_count']}"
        )
