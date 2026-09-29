"""Which rows a computation is allowed to read, and what happens at the exact
boundary of each comparison: the true-up input set, the one-ton penalty floor,
rolling-average equality, window chronology and the forward-looking posture."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allowance_account,
    assert_allowance_transaction,
    assert_excess_emission_event,
    assert_permit_limit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

CLOCK_APRIL = "2026-04-02T00:00:00Z"
ANCHOR_03 = "2026-04-01T03:00:00Z"
EXCUSE_REASON = "Sudden and unavoidable malfunction; excused under the permit."


def _names_instant(value, instant):
    """An ISO 8601 timestamp naming `instant`, at whatever fractional
    precision the server serialises."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert value.startswith(instant[:-1]), (
        f"expected a timestamp at {instant}, got {value!r}"
    )


def _events(params):
    rows, meta = validate_paginated(
        api_client.list_excess_emission_events(fx.REVIEWER, params)
    )
    return rows, meta["total_count"]


def _account(account_id):
    return validate_success(
        api_client.get_allowance_account(account_id, fx.REVIEWER)
    )


def _facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, fx.REVIEWER))


class TestTrueUpInputSet:
    """Only ACCEPTED reports of the compliance year and only ENFORCEABLE events."""

    def test_an_excused_event_and_a_foreign_year_report_are_both_ignored(self):
        """The obligation is ceil(0.438) == 1, not 1 + the 17 excused tons.

        PRD: "Two preconditions gate it, in this order: the logical clock must be
        **at or after** the facility's `true_up_deadline_utc`, else
        `ERR_TRUE_UP_BEFORE_DEADLINE`; and every quarterly report of every unit of
        that facility for the account's `compliance_year` must stand at `ACCEPTED`,
        so a single report left at `DRAFT` or `REJECTED` blocks the year, else
        `ERR_REPORTS_NOT_ALL_ACCEPTED`."

        PRD: "Emitted tonnage is the sum of `total_so2_tons` across every report
        standing at `ACCEPTED` for a unit of this facility whose `year` equals the
        `compliance_year`, rounded half up to three decimals."

        PRD: "Event tonnage is the sum of `penalty_allowance_debit_tons` across
        every excess emission event standing at `ENFORCEABLE` on those units whose
        `detected_utc` falls in the compliance year."

        PRD: "`obligation_tons` is the emitted tonnage **raised to the next whole
        number** plus that integral event tonnage — a ceiling on the emissions, so a
        fractional ton of SO2 obliges a whole allowance."

        PRD: "If the shortfall is zero, the account moves straight to `CLOSED`,
        `penalty_deducted_tons` stays 0.0, no penalty transaction is created, the
        facility's `compliance_posture` is recomputed without reaching `DEFICIT` on
        account of this account, dispatch is left untouched, and the account's
        `version` increments by one."

        Design: Corner/calculations/calc_true_up_input_set_admits_only_accepted_reports_and_enforceable_events
        """
        station = fx.setup_certified_so2_station(
            clock=CLOCK_APRIL,
            facility_overrides={"true_up_deadline_utc": "2026-04-05T00:00:00Z"},
        )
        facility_id = station["facility"]["id"]
        first_unit = station["unit"]["id"]
        second_unit = fx.create_unit(facility_id, unit_identifier="U2")

        report = fx.open_quarterly_report(first_unit)
        fx.append_hours_bulk(first_unit, report["version"], fx.cems_hours(3))

        limit = fx.create_permit_limit(
            first_unit, limit_value=250.0, effective_from_utc="2026-04-01T00:00:00Z"
        )
        fx.evaluate_permit_limit(limit["id"], ANCHOR_03)
        rows, total = _events({"permit_limit_id": limit["id"]})
        assert total == 1, f"the exceedance raised one event, listing gave {total}"
        event_id = rows[0]["id"]

        fx.file_and_review_event(event_id)
        excused = validate_success(
            api_client.disposition_excess_emission_event(
                event_id, {"decision": "EXCUSE", "reason": EXCUSE_REASON}, fx.REVIEWER
            )
        )
        assert excused["status"] == "EXCUSED"
        assert excused["penalty_allowance_debit_tons"] == 17, (
            "the excused event is worth 17 tons, none of which may be obliged, got "
            f"{excused['penalty_allowance_debit_tons']}"
        )

        certified = fx.drive_report_to_certified(report["id"])["report"]
        assert certified["status"] == "CERTIFIED"
        assert certified["total_so2_tons"] == 0.438

        foreign_year = fx.open_quarterly_report(second_unit["id"], 2027, 1)
        assert foreign_year["status"] == "DRAFT"
        assert foreign_year["year"] == 2027

        account = fx.open_allowance_account(
            facility_id,
            holdings_prior_vintage_tons=5.0,
            holdings_current_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )

        validate_error(
            api_client.run_true_up(account["id"], {}, fx.REVIEWER),
            ApiErrorId.ERR_TRUE_UP_BEFORE_DEADLINE.value,
        )

        fx.set_clock("2026-04-06T00:00:00Z")
        validate_error(
            api_client.run_true_up(account["id"], {}, fx.REVIEWER),
            ApiErrorId.ERR_REPORTS_NOT_ALL_ACCEPTED.value,
        )

        accepted = fx.accept_report(report["id"])
        assert accepted["status"] == "ACCEPTED"

        trued_up = validate_success(
            api_client.run_true_up(account["id"], {}, fx.REVIEWER)
        )
        assert_allowance_account(trued_up)
        assert trued_up["obligation_tons"] == 1, (
            "0.438 emitted tons raised to the next whole number is 1, and the "
            f"EXCUSED event adds nothing, got {trued_up['obligation_tons']}"
        )
        assert trued_up["holdings_prior_vintage_tons"] == 4.000
        assert trued_up["holdings_current_vintage_tons"] == 0.000
        assert trued_up["surrendered_tons"] == 1.000
        assert trued_up["shortfall_tons"] == 0.000
        assert trued_up["penalty_deducted_tons"] == 0.0
        assert trued_up["status"] == "CLOSED"
        _names_instant(trued_up["true_up_utc"], "2026-04-06T00:00:00Z")

        transactions, tx_meta = validate_paginated(
            api_client.list_allowance_transactions(
                fx.REVIEWER, {"allowance_account_id": account["id"]}
            )
        )
        assert tx_meta["total_count"] == 1, (
            "a zero shortfall creates no penalty row, saw "
            f"{tx_meta['total_count']} transactions"
        )
        surrender = transactions[0]
        assert_allowance_transaction(surrender)
        assert surrender["origin"] == "TRUE_UP_SURRENDER"
        assert surrender["transaction_type"] == "SURRENDER"
        assert surrender["status"] == "SETTLED"
        assert surrender["debited_prior_tons"] == 1.000
        assert surrender["debited_current_tons"] == 0.000
        assert all(
            row["origin"] != "TRUE_UP_PENALTY" for row in transactions
        ), "no TRUE_UP_PENALTY row may exist when the shortfall is zero"

        assert _facility(facility_id)["compliance_posture"] == "COMPLIANT"

        untouched = validate_success(
            api_client.get_quarterly_report(foreign_year["id"], fx.PREPARER)
        )
        assert untouched["status"] == "DRAFT", (
            "the 2027 report never participated and was never moved"
        )


class TestPenaltyDebitFloorAndCeiling:
    """A 0.1 lb/hr exceedance still costs a ton; a 42.2 one costs seventeen."""

    def test_the_smallest_exceedance_costs_one_ton_and_16_88_percent_costs_17(self):
        """0.0342 percent and 16.8800 percent, both raised to the next whole number.

        PRD: "The server records `permit_limit_id` for the exceeded limit,
        denormalises `unit_id` from it so events can be filtered per unit, stamps
        `detected_utc` from the evaluation's anchor, captures `observed_value` from
        `current_rolling_value` and `limit_value_snapshot` from `limit_value` at
        detection, and derives `exceedance_magnitude` as `observed_value` minus
        `limit_value_snapshot`, rounded half up to four decimals."

        PRD: "It then sizes the allowance consequence: the exceedance percent is
        `exceedance_magnitude` divided by `limit_value_snapshot`, multiplied by 100,
        rounded half up to four decimals, and `penalty_allowance_debit_tons` is the
        **larger** of one ton and that percent **raised to the next whole number** —
        a ceiling, never a round, so a percent of exactly 20 gives 20 tons while a
        percent a hundredth above 20 gives 21."

        PRD: "The floor of one ton means even the smallest exceedance carries a
        consequence."

        Design: Corner/calculations/calc_penalty_debit_applies_the_minimum_ton_floor
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]

        tight = fx.create_permit_limit(
            unit_id, limit_value=292.1, effective_from_utc="2026-03-31T00:00:00Z"
        )
        loose = fx.create_permit_limit(
            unit_id, limit_value=250.0, effective_from_utc="2026-04-01T00:00:00Z"
        )

        evaluated_tight = fx.evaluate_permit_limit(tight["id"], ANCHOR_03)
        assert_permit_limit(evaluated_tight)
        assert evaluated_tight["evaluation_status"] == "EXCEEDED"
        assert evaluated_tight["current_rolling_value"] == 292.2
        assert evaluated_tight["window_sample_count"] == 3

        rows, total = _events({"permit_limit_id": tight["id"]})
        assert total == 1
        smallest = rows[0]
        assert_excess_emission_event(smallest)
        assert smallest["exceedance_magnitude"] == 0.1000, (
            f"292.2 minus 292.1 is 0.1000, got {smallest['exceedance_magnitude']}"
        )
        assert smallest["penalty_allowance_debit_tons"] == 1, (
            "0.1 / 292.1 * 100 is 0.0342 percent, whose ceiling is 1, and the floor "
            f"of one ton would give 1 in any case, got "
            f"{smallest['penalty_allowance_debit_tons']}"
        )

        fx.evaluate_permit_limit(loose["id"], ANCHOR_03)
        rows, total = _events({"permit_limit_id": loose["id"]})
        assert total == 1
        larger = rows[0]
        assert larger["exceedance_magnitude"] == 42.2000, (
            f"292.2 minus 250.0 is 42.2000, got {larger['exceedance_magnitude']}"
        )
        assert larger["penalty_allowance_debit_tons"] == 17, (
            "42.2 / 250.0 * 100 is 16.8800 percent, raised to the next whole number "
            f"is 17, got {larger['penalty_allowance_debit_tons']}"
        )

        for event, parent in ((smallest, tight), (larger, loose)):
            assert event["status"] == "DETECTED"
            assert event["limit_value_snapshot"] == parent["limit_value"], (
                "each event snapshots its own parent's limit_value"
            )
            assert event["observed_value"] == 292.2
            assert event["unit_id"] == unit_id

        _, unit_total = _events({"unit_id": unit_id})
        assert unit_total == 2, (
            f"two limits exceeded on the same hours, so two events, got {unit_total}"
        )


class TestRollingValueAtTheLimit:
    """Equality is in compliance; a hundredth below the value is exceeded."""

    def test_a_292_2_limit_is_in_compliance_while_a_292_1_limit_is_exceeded(self):
        """The same window, the same value, two verdicts either side of strict `>`.

        PRD: "For `LB_PER_HR` it is the sum of those masses divided by
        `window_sample_count`, rounded half up to one decimal."

        PRD: "The `evaluation_status` is then `EXCEEDED` when
        `current_rolling_value` is **strictly greater** than `limit_value`, and
        `IN_COMPLIANCE` otherwise — a rolling value exactly equal to the limit is in
        compliance."

        PRD: "An `EXCEEDED` result raises an **Excess Emission Event**."

        Design: Corner/calculations/calc_rolling_limit_equality_is_in_compliance_not_exceeded
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]

        at_the_limit = fx.create_permit_limit(
            unit_id, limit_value=292.2, effective_from_utc="2026-03-31T00:00:00Z"
        )
        under_the_limit = fx.create_permit_limit(
            unit_id, limit_value=292.1, effective_from_utc="2026-04-01T00:00:00Z"
        )

        equal = fx.evaluate_permit_limit(at_the_limit["id"], ANCHOR_03)
        assert_permit_limit(equal)
        assert equal["evaluation_status"] == "IN_COMPLIANCE", (
            "876.6 lb over 3 samples is exactly 292.2, which equals the limit"
        )
        assert equal["current_rolling_value"] == 292.2
        _names_instant(equal["window_evaluated_utc"], ANCHOR_03)

        _, none_raised = _events({"permit_limit_id": at_the_limit["id"]})
        assert none_raised == 0, (
            f"equality raises no excess emission event, saw {none_raised}"
        )

        exceeded = fx.evaluate_permit_limit(under_the_limit["id"], ANCHOR_03)
        assert exceeded["evaluation_status"] == "EXCEEDED"
        assert exceeded["current_rolling_value"] == 292.2, (
            "the rolling value is a property of the window, not of the limit"
        )

        rows, unit_total = _events({"unit_id": unit_id})
        assert unit_total == 1, (
            f"only the strictly-exceeded limit raised an event, saw {unit_total}"
        )
        assert rows[0]["permit_limit_id"] == under_the_limit["id"]


class TestWindowChronology:
    """The window is selected by hour_begin_utc, never by insertion order."""

    def test_hours_appended_out_of_order_still_form_one_chronological_window(self):
        """02:00 then 00:00 then 01:00 gives a 3-sample window at the 03:00 anchor.

        PRD: "The window admits operating hours of the limit's unit whose
        `hour_begin_utc` is **strictly earlier** than the anchor, **at or after** the
        anchor minus the basis span, **at or after** `effective_from_utc`, whose
        `op_time_fraction` is greater than zero, and whose `data_quality` is
        `MEASURED` or `SUBSTITUTED` — an `UNAVAILABLE` hour is excluded outright."

        PRD: "A window too thin to average is not a compliance judgement: if
        `window_sample_count` is **below** the minimum for the basis — 3 hours for
        `ROLLING_3_HOUR`, and 24 hours for both `ROLLING_30_DAY` and `ANNUAL` — the
        `evaluation_status` becomes `INSUFFICIENT_DATA` and `current_rolling_value`
        is null."

        PRD: "`total_so2_lbs` is the sum of the hours' `so2_mass_lbs`, counting a
        null as zero, rounded half up to one decimal."

        Design: Corner/calculations/calc_rolling_window_is_chronological_regardless_of_insert_order
        """
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id)
        limit = fx.create_permit_limit(
            unit_id, limit_value=300.0, effective_from_utc="2026-04-01T00:00:00Z"
        )

        third_hour = fx.append_hour(
            unit_id, report["version"], fx.cems_hours(1, start_hour=2)[0]
        )
        assert third_hour["quarterly_report_version_after"] == 2

        first_hour = fx.append_hour(
            unit_id,
            third_hour["quarterly_report_version_after"],
            fx.cems_hours(1, start_hour=0)[0],
        )
        assert first_hour["quarterly_report_version_after"] == 3

        thin = fx.evaluate_permit_limit(limit["id"], "2026-04-01T02:00:00Z")
        assert thin["window_sample_count"] == 1, (
            "only the 00:00 hour is strictly earlier than 02:00 and at or after "
            f"23:00, got {thin['window_sample_count']} samples"
        )
        assert thin["evaluation_status"] == "INSUFFICIENT_DATA"
        assert thin["current_rolling_value"] is None, (
            "a window too thin to average reports no value at all"
        )

        second_hour = fx.append_hour(
            unit_id,
            first_hour["quarterly_report_version_after"],
            fx.cems_hours(1, start_hour=1)[0],
        )
        assert second_hour["quarterly_report_version_after"] == 4, (
            "each single-hour append spends exactly one report version"
        )

        full = fx.evaluate_permit_limit(limit["id"], ANCHOR_03)
        assert full["window_sample_count"] == 3, (
            "the hour written last sits in the middle of the window, got "
            f"{full['window_sample_count']} samples"
        )
        assert full["evaluation_status"] == "IN_COMPLIANCE"
        assert full["current_rolling_value"] == 292.2

        rolled_up = validate_success(
            api_client.get_quarterly_report(report["id"], fx.PREPARER)
        )
        assert rolled_up["operating_hour_count"] == 3
        assert rolled_up["total_so2_lbs"] == 876.6
        assert rolled_up["total_heat_input_mmbtu"] == 1666.668


class TestForwardLookingPosture:
    """Submission creates the projection; a settled purchase covers it exactly."""

    def test_the_posture_walks_compliant_to_watch_and_back_on_exact_coverage(self):
        """Zero holdings against a projected 1 is WATCH; 1.000 held is COMPLIANT.

        PRD: "Otherwise the system looks forward: for each account, the projected
        obligation is the sum of `total_so2_tons` across the facility's reports
        standing at `SUBMITTED`, `CERTIFIED` or `ACCEPTED` whose `year` equals that
        account's `compliance_year`, rounded half up to three decimals and then
        raised to the next whole number; the covered tonnage is that account's
        `holdings_current_vintage_tons` plus `holdings_prior_vintage_tons`."

        PRD: "If the covered tonnage is **strictly less than** the projected
        obligation for any account, the posture is `WATCH` — the first such account
        settles it."

        PRD: "If no account is short, the posture is `COMPLIANT`, and coverage
        exactly equal to the projection is `COMPLIANT`, not `WATCH`."

        PRD: "A report standing at `DRAFT`, `VALIDATED` or `REJECTED` contributes
        nothing to the projection, which is why rejecting a report after
        certification lowers the projection and can move a station from `WATCH` back
        to `COMPLIANT`."

        Design: Corner/calculations/calc_posture_projects_submitted_emissions_before_any_true_up
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        facility_id = station["facility"]["id"]
        report_id = station["report"]["id"]
        assert station["report"]["total_so2_tons"] == 0.438

        account = fx.open_allowance_account(
            facility_id,
            holdings_current_vintage_tons=0.0,
            holdings_prior_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )

        validated = fx.validate_report(report_id)
        assert validated["status"] == "VALIDATED"
        assert _facility(facility_id)["compliance_posture"] == "COMPLIANT", (
            "a VALIDATED report contributes nothing to the projection, so an empty "
            "account is not yet short"
        )

        submitted = fx.submit_report(report_id)
        assert submitted["status"] == "SUBMITTED"
        assert _facility(facility_id)["compliance_posture"] == "WATCH", (
            "projected is ceil(0.438) == 1 and covered is 0.000 + 0.000 == 0.000"
        )

        settled = fx.settle_transaction(
            account["id"],
            account["version"],
            transaction_type="PURCHASE",
            quantity_tons=1.000,
            vintage_year=2026,
        )
        assert settled["status"] == "SETTLED"

        covered = _account(account["id"])
        assert covered["holdings_current_vintage_tons"] == 1.000, (
            "a vintage equal to the compliance year addresses the current bucket"
        )
        assert covered["shortfall_tons"] == 0.0, (
            "no true-up has run, so no account carries a shortfall and DEFICIT is "
            "never reachable in this scenario"
        )

        assert _facility(facility_id)["compliance_posture"] == "COMPLIANT", (
            "covered 1.000 is not strictly less than projected 1, so equality is "
            "COMPLIANT and not WATCH"
        )
