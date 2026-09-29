"""The true-up waterfall — how the obligation is folded, how the shortfall
cascade reaches the facility and its units, and how a reversal unwinds it."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allowance_account,
    assert_allowance_transaction,
    make_facility_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

REVERSAL_REASON = "counterparty deal cancelled before the transfer cleared"


def _account(account_id):
    return validate_success(
        api_client.get_allowance_account(account_id, fx.REVIEWER)
    )


def _facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, fx.REVIEWER))


def _unit(unit_id):
    return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))


def _transaction(transaction_id):
    return validate_success(
        api_client.get_allowance_transaction(transaction_id, fx.REVIEWER)
    )


def _bucket_sum(account):
    return round(
        account["holdings_prior_vintage_tons"]
        + account["holdings_current_vintage_tons"]
        + account["holdings_next_vintage_tons"],
        3,
    )


class TestObligationFolding:
    """Five inputs fold into one integer obligation and then drain buckets."""

    def _enforced_event_station(self):
        station = fx.setup_facility_and_unit(clock=fx.CLOCK_Q2)
        unit_id = station["unit"]["id"]
        cem = fx.setup_certified_cem(
            unit_id,
            span_value=2000.0,
            span_reference_value=1800.0,
            span_measured_value=1810.0,
        )
        station["system"] = cem["system"]
        report = fx.open_quarterly_report(unit_id)
        station["hours"] = fx.append_hours_bulk(
            unit_id, report["version"], fx.cems_hours(12, **fx.HIGH_EMISSION_HOUR)
        )
        station["permit_limit"] = fx.create_permit_limit(unit_id, limit_value=4900.0)
        station["permit_limit"] = fx.evaluate_permit_limit(
            station["permit_limit"]["id"], "2026-04-01T03:00:00Z"
        )
        events, _ = validate_paginated(
            api_client.list_excess_emission_events(
                fx.REVIEWER,
                {
                    "permit_limit_id": station["permit_limit"]["id"],
                    "status": "DETECTED",
                },
            )
        )
        station["event"] = events[0]
        fx.file_and_review_event(station["event"]["id"])
        station["event"] = validate_success(
            api_client.disposition_excess_emission_event(
                station["event"]["id"], {"decision": "ENFORCE"}, fx.REVIEWER
            )
        )
        lifecycle = fx.drive_report_to_accepted(report["id"])
        station["report"] = lifecycle["report"]
        station["account"] = fx.open_allowance_account(
            station["facility"]["id"],
            holdings_prior_vintage_tons=7.0,
            holdings_current_vintage_tons=18.0,
            holdings_next_vintage_tons=15.0,
        )
        fx.set_clock(fx.TRUE_UP_DEADLINE)
        return station

    def test_the_obligation_adds_an_enforceable_event_debit_to_a_ceiled_ton_sum(self):
        """ceil(29.880) plus ceil(1.6327) is 32, not 30 and not 31.

        PRD: "`obligation_tons` is the emitted tonnage **raised to the next whole
        number** plus that integral event tonnage — a ceiling on the emissions, so
        a fractional ton of SO2 obliges a whole allowance."

        Design: Difficulty/combinatorial_formula/combinatorial_true_up_obligation_nests_ceiling_over_rounded_ton_sum
        """
        station = self._enforced_event_station()

        first_hour = station["hours"][0]
        assert first_hour["heat_input_mmbtu"] == 1388.889
        assert first_hour["so2_mass_lbs"] == 4980.0

        report = station["report"]
        assert report["total_heat_input_mmbtu"] == 16666.668
        assert report["total_so2_lbs"] == 59760.0
        assert report["total_so2_tons"] == 29.880

        limit = validate_success(
            api_client.get_permit_limit(station["permit_limit"]["id"], fx.REVIEWER)
        )
        assert limit["current_rolling_value"] == 4980.0
        assert limit["evaluation_status"] == "EXCEEDED"

        event = station["event"]
        assert event["exceedance_magnitude"] == 80.0
        assert event["penalty_allowance_debit_tons"] == 2, (
            "80.0 / 4900.0 * 100 is 1.6327 percent, whose ceiling is 2 tons"
        )
        assert event["status"] == "ENFORCEABLE"

        trued_up = validate_success(
            api_client.run_true_up(station["account"]["id"], {}, fx.REVIEWER)
        )
        assert_allowance_account(trued_up)
        assert trued_up["obligation_tons"] == 32, (
            "the ceiling of 29.880 is 30, plus the 2-ton enforceable debit, got "
            f"{trued_up['obligation_tons']}"
        )

    def test_the_waterfall_drains_banked_first_and_doubles_the_residual(self):
        """25 surrendered, 7 short, 14 deducted, and the next bucket lands on 1.000.

        PRD: "Holdings are then drained banked-first: the amount taken from
        `holdings_prior_vintage_tons` is the smaller of `obligation_tons` and that
        bucket's balance; the amount taken from `holdings_current_vintage_tons` is
        the smaller of what remains and that bucket's balance."

        Design: Difficulty/combinatorial_formula/combinatorial_true_up_obligation_nests_ceiling_over_rounded_ton_sum
        """
        station = self._enforced_event_station()

        trued_up = validate_success(
            api_client.run_true_up(station["account"]["id"], {}, fx.REVIEWER)
        )
        assert trued_up["obligation_tons"] == 32
        assert trued_up["surrendered_tons"] == 25.000, (
            "min(32, 7) from the banked bucket plus min(25, 18) from the current one"
        )
        assert trued_up["shortfall_tons"] == 7.000
        assert trued_up["penalty_deducted_tons"] == 14.000, (
            "twice the uncovered tonnage"
        )
        assert trued_up["holdings_prior_vintage_tons"] == 0.000
        assert trued_up["holdings_current_vintage_tons"] == 0.000
        assert trued_up["holdings_next_vintage_tons"] == 1.000, (
            f"15.000 less the 14.000 penalty, got "
            f"{trued_up['holdings_next_vintage_tons']}"
        )
        assert trued_up["status"] == "TRUE_UP_LOCKED"


class TestShortfallCascade:
    """The shortfall walks account -> transactions -> facility -> units."""

    def test_the_true_up_records_a_surrender_and_a_punitive_deduction(self):
        """25.000 surrendered from two buckets and 10.000 taken from the next.

        PRD: "A second `SETTLED` transaction with `origin` of `TRUE_UP_PENALTY`
        and `transaction_type` of `PENALTY_DEDUCTION` is created for
        `shortfall_tons` multiplied by the penalty ratio of 2.0 — twice the
        uncovered tonnage — rounded half up to three decimals."

        Design: Difficulty/transitive_cascade/cascade_true_up_shortfall_creates_penalty_flips_posture_and_restricts_dispatch
        """
        station = fx.setup_true_up_shortfall_state(run_true_up=False)

        assert _unit(station["unit"]["id"])["dispatch_state"] == "ONLINE"
        assert _unit(station["unit"]["id"])["dispatch_restricted"] is False

        account = validate_success(
            api_client.run_true_up(station["account"]["id"], {}, fx.REVIEWER)
        )
        assert account["obligation_tons"] == 30
        assert account["surrendered_tons"] == 25.000
        assert account["shortfall_tons"] == 5.000
        assert account["penalty_deducted_tons"] == 10.000
        assert account["status"] == "TRUE_UP_LOCKED"
        assert account["holdings_prior_vintage_tons"] == 0.000
        assert account["holdings_current_vintage_tons"] == 0.000
        assert account["holdings_next_vintage_tons"] == 5.000

        rows, meta = validate_paginated(
            api_client.list_allowance_transactions(
                fx.REVIEWER, {"allowance_account_id": account["id"]}
            )
        )
        assert meta["total_count"] == 2
        surrender = next(row for row in rows if row["origin"] == "TRUE_UP_SURRENDER")
        penalty = next(row for row in rows if row["origin"] == "TRUE_UP_PENALTY")

        assert_allowance_transaction(surrender)
        assert surrender["transaction_type"] == "SURRENDER"
        assert surrender["status"] == "SETTLED"
        assert surrender["quantity_tons"] == 25.000
        assert surrender["debited_prior_tons"] == 7.000
        assert surrender["debited_current_tons"] == 18.000
        assert surrender["debited_next_tons"] == 0.000

        assert penalty["transaction_type"] == "PENALTY_DEDUCTION"
        assert penalty["status"] == "SETTLED"
        assert penalty["quantity_tons"] == 10.000
        assert penalty["debited_next_tons"] == 10.000

        assert _bucket_sum(account) == 5.000, (
            "40.000 endowed less 25.000 surrendered less 10.000 deducted"
        )

    def test_the_deficit_posture_restricts_dispatch_on_every_unit(self):
        """Both units are restricted, and the online one is pulled to reserve.

        PRD: "Every unit of the facility has `dispatch_restricted` set to true,
        and every unit standing at `ONLINE` is moved to `RESERVE_SHUTDOWN`."

        Design: Difficulty/transitive_cascade/cascade_true_up_shortfall_creates_penalty_flips_posture_and_restricts_dispatch
        """
        station = fx.setup_true_up_shortfall_state()

        assert _facility(station["facility"]["id"])["compliance_posture"] == "DEFICIT"

        first = _unit(station["unit"]["id"])
        assert first["dispatch_restricted"] is True
        assert first["dispatch_state"] == "RESERVE_SHUTDOWN"

        second = _unit(station["unit2"]["id"])
        assert second["dispatch_restricted"] is True
        assert second["dispatch_state"] == "OFFLINE", (
            "a unit that was not online is restricted without being moved"
        )

        blocked = api_client.set_unit_dispatch(
            station["unit"]["id"],
            {"dispatch_state": "ONLINE"},
            make_facility_operator_headers(station["facility"]["operator_org"]),
        )
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert _unit(station["unit"]["id"])["dispatch_state"] == "RESERVE_SHUTDOWN"


class TestReversingCascade:
    """Reversing the surrender voids the true-up rather than re-deriving it."""

    def test_reversing_the_penalty_row_requires_a_reason(self):
        """A reason-less reversal leaves the settled row exactly where it was.

        PRD: "Reversing any *other* row of a locked account leaves the account
        `TRUE_UP_LOCKED`, and only `surrendered_tons`, `penalty_deducted_tons` and
        `shortfall_tons` are refreshed."

        Design: Difficulty/transitive_cascade/cascade_reversing_true_up_surrender_unlocks_account_and_releases_dispatch
        """
        station = fx.setup_true_up_shortfall_state()
        penalty_id = station["penalty_transaction"]["id"]

        refused = api_client.transition_allowance_transaction(
            penalty_id, {"action": "REVERSE"}, fx.REPRESENTATIVE
        )
        validate_error(refused, ApiErrorId.ERR_REASON_REQUIRED.value)

        assert _transaction(penalty_id)["status"] == "SETTLED"
        account = _account(station["account"]["id"])
        assert account["status"] == "TRUE_UP_LOCKED"
        assert account["penalty_deducted_tons"] == 10.000

    def test_reversing_the_surrender_voids_the_true_up_and_releases_dispatch(self):
        """The stored per-bucket debits are credited back and the units are freed.

        PRD: "When the reversed row has `origin` of `TRUE_UP_SURRENDER`, the
        account transitions from `TRUE_UP_LOCKED` back to `OPEN` and the true-up is
        **voided rather than re-derived**: `obligation_tons` returns to 0,
        `surrendered_tons`, `penalty_deducted_tons` and `shortfall_tons` all return
        to 0.0, `true_up_utc` returns to null, and the account's `version`
        increments by one."

        Design: Difficulty/transitive_cascade/cascade_reversing_true_up_surrender_unlocks_account_and_releases_dispatch
        """
        station = fx.setup_true_up_shortfall_state()
        surrender_id = station["surrender_transaction"]["id"]
        penalty_id = station["penalty_transaction"]["id"]

        reversed_row = validate_success(
            api_client.transition_allowance_transaction(
                surrender_id,
                {"action": "REVERSE", "reason": REVERSAL_REASON},
                fx.REPRESENTATIVE,
            )
        )
        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["reversal_reason"] == REVERSAL_REASON

        account = _account(station["account"]["id"])
        assert account["status"] == "OPEN"
        assert account["holdings_prior_vintage_tons"] == 7.000
        assert account["holdings_current_vintage_tons"] == 18.000
        assert account["holdings_next_vintage_tons"] == 15.000, (
            "the penalty row's stored debit is credited back as well"
        )
        assert account["obligation_tons"] == 0
        assert account["surrendered_tons"] == 0.000
        assert account["penalty_deducted_tons"] == 0.000
        assert account["shortfall_tons"] == 0.000
        assert account["true_up_utc"] is None
        assert _bucket_sum(account) == 40.000

        assert _transaction(penalty_id)["status"] == "REVERSED"

        facility = _facility(station["facility"]["id"])
        assert facility["compliance_posture"] == "WATCH", (
            "the accepted quarter still projects more than the restored coverage"
        )

        first = _unit(station["unit"]["id"])
        assert first["dispatch_restricted"] is False
        assert first["dispatch_state"] == "RESERVE_SHUTDOWN", (
            "releasing the restriction does not put the unit back online"
        )
        second = _unit(station["unit2"]["id"])
        assert second["dispatch_restricted"] is False
        assert second["dispatch_state"] == "OFFLINE"

        restored = validate_success(
            api_client.set_unit_dispatch(
                station["unit"]["id"],
                {"dispatch_state": "ONLINE"},
                make_facility_operator_headers(station["facility"]["operator_org"]),
            )
        )
        assert restored["dispatch_state"] == "ONLINE"
