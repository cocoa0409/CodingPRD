"""Input validation at the edges: the low-emitter basis, the run-count bound,
the five composite uniqueness keys, the proposal guards, the locked account and
the inclusive vintage-year window."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allowance_account,
    assert_allowance_transaction,
    assert_facility,
    assert_operating_hour,
    assert_permit_limit,
    assert_quarterly_report,
    assert_rata_test,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    allowance_transaction_payload,
    cems_hour_payload,
    rata_runs_payload,
    rata_test_payload,
    single_hour_payload,
)

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
CLOCK_APRIL = "2026-04-02T00:00:00Z"
RATA_WINDOW = {
    "window_start_utc": "2026-08-02T00:00:00Z",
    "window_end_utc": "2026-08-03T00:00:00Z",
}
HIGH_EMITTER_RUNS = [
    {"reference_value": 0.400, "cems_value": 0.380} for _ in range(9)
]


def _rata(rata_test_id):
    return validate_success(api_client.get_rata_test(rata_test_id, fx.QA))


def _account(account_id):
    return validate_success(
        api_client.get_allowance_account(account_id, fx.REVIEWER)
    )


def _transaction_total(account_id):
    _, meta = validate_paginated(
        api_client.list_allowance_transactions(
            fx.REVIEWER, {"allowance_account_id": account_id}
        )
    )
    return meta["total_count"]


class TestApplicableStandardBasis:
    """The alternative denominator is reserved for genuinely low emitters."""

    def test_a_missing_standard_and_a_high_reference_mean_both_refuse_the_basis(self):
        """Two refusals, then the reference-mean basis evaluates the same runs.

        PRD: "Under `APPLICABLE_STANDARD` the denominator is
        `applicable_standard_value` instead, and that substitution is reserved for
        genuinely low-emitting sources: it requires `applicable_standard_value` to be
        present **and** `reference_mean` to be at or below the low-emitter threshold
        for the system's monitored `parameter` — 0.300 for `SO2`, `NOX_RATE` and
        `FLOW`, and 5.000 for `CO2`."

        PRD: "A request that fails either condition is rejected with
        `ERR_RA_BASIS_NOT_PERMITTED`."

        PRD: "The audit `PASSED` when that percentage is **at or below** 10.0 — the
        pass threshold is 10.0 for every monitored parameter, and equality passes —
        and `FAILED` when it is strictly above."

        Design: Corner/validations/val_applicable_standard_basis_is_reserved_for_low_emitters
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST, online=True)
        unit_id = station["unit"]["id"]

        so2_system = fx.install_monitoring_system(
            unit_id, parameter="SO2", system_type="CEM", span_value=400.0
        )
        nox_system = fx.install_monitoring_system(
            unit_id, parameter="NOX_RATE", system_type="CEM", span_value=0.8
        )

        without_standard = validate_success(
            api_client.schedule_rata_test(
                so2_system["id"], rata_test_payload(**RATA_WINDOW), fx.QA
            ),
            201,
        )
        assert without_standard["applicable_standard_value"] is None
        fx.record_rata_runs(without_standard["id"], fx.RATA_RUNS_PASSING)

        high_emitter = validate_success(
            api_client.schedule_rata_test(
                nox_system["id"],
                rata_test_payload(applicable_standard_value=0.500, **RATA_WINDOW),
                fx.QA,
            ),
            201,
        )
        recorded = fx.record_rata_runs(high_emitter["id"], HIGH_EMITTER_RUNS)
        assert recorded["reference_mean"] == 0.4000, (
            f"nine runs of 0.400 average to 0.4000, got {recorded['reference_mean']}"
        )

        validate_error(
            api_client.evaluate_rata_test(
                without_standard["id"], {"ra_basis": "APPLICABLE_STANDARD"}, fx.QA
            ),
            ApiErrorId.ERR_RA_BASIS_NOT_PERMITTED.value,
        )
        validate_error(
            api_client.evaluate_rata_test(
                high_emitter["id"], {"ra_basis": "APPLICABLE_STANDARD"}, fx.QA
            ),
            ApiErrorId.ERR_RA_BASIS_NOT_PERMITTED.value,
        )

        for refused in (without_standard["id"], high_emitter["id"]):
            frozen = _rata(refused)
            assert frozen["status"] == "RUNS_RECORDED", (
                "a refused evaluation leaves the audit where the runs left it"
            )
            assert frozen["relative_accuracy_pct"] is None
            assert frozen["ra_basis"] == "REFERENCE_MEAN", (
                "the refused basis was never written onto the row"
            )

        evaluated = fx.evaluate_rata_test(
            without_standard["id"], ra_basis="REFERENCE_MEAN"
        )
        assert_rata_test(evaluated)
        assert evaluated["ra_basis"] == "REFERENCE_MEAN"
        assert evaluated["relative_accuracy_pct"] == 10.0
        assert evaluated["status"] == "PASSED", (
            "the reference-mean basis is always permitted, and 10.0 is at the "
            "threshold, so equality passes"
        )


class TestRataRunBounds:
    """Nine through twelve pairs, every value positive."""

    def test_eight_thirteen_and_a_zero_reference_value_are_all_refused(self):
        """The bound is inclusive at both ends, and 9 clean pairs are accepted.

        PRD: "The array must hold at least 9 and at most 12 pairs, with every value
        positive, else `ERR_INSUFFICIENT_RATA_RUNS`; 8 pairs and 13 pairs are both
        rejected, because the statistical table this test relies on is defined only
        over that range."

        PRD: "`reference_mean` is the arithmetic mean of the reference values and
        `cems_mean` the arithmetic mean of the monitor values, each rounded half up
        to four decimals."

        Design: Corner/validations/val_rata_run_count_and_run_values_are_bounded
        """
        station = fx.setup_scheduled_rata_test(
            parameter="SO2", span_value=400.0, online=True, clock=CLOCK_AUGUST,
            **RATA_WINDOW,
        )
        rata_test_id = station["rata_test"]["id"]

        eight = fx.RATA_RUNS_PASSING[:8]
        thirteen = fx.RATA_RUNS_PASSING + [
            {"reference_value": 0.268, "cems_value": 0.250},
            {"reference_value": 0.266, "cems_value": 0.252},
            {"reference_value": 0.270, "cems_value": 0.244},
            {"reference_value": 0.272, "cems_value": 0.242},
        ]
        with_a_zero = [{"reference_value": 0.000, "cems_value": 0.246}] + list(
            fx.RATA_RUNS_PASSING[1:]
        )

        assert len(eight) == 8
        assert len(thirteen) == 13
        assert len(with_a_zero) == 9

        for runs in (eight, thirteen, with_a_zero):
            validate_error(
                api_client.record_rata_runs(
                    rata_test_id, rata_runs_payload(runs), fx.QA
                ),
                ApiErrorId.ERR_INSUFFICIENT_RATA_RUNS.value,
            )

        untouched = _rata(rata_test_id)
        assert untouched["status"] == "SCHEDULED"
        assert untouched["run_count"] == 0
        assert untouched["version"] == 1, (
            f"three refusals must spend no version, got {untouched['version']}"
        )

        accepted = fx.record_rata_runs(rata_test_id, fx.RATA_RUNS_PASSING)
        assert accepted["status"] == "RUNS_RECORDED"
        assert accepted["run_count"] == 9
        assert accepted["reference_mean"] == 0.2700
        assert accepted["cems_mean"] == 0.2481


class TestCompositeUniquenessKeys:
    """Five keys, five codes, and a near miss accepted for each of three."""

    def test_five_duplicate_keys_each_report_their_own_code(self):
        """Then a new quarter, a new year and a new basis are all accepted.

        PRD: "A `RegulatoryReviewer` brings a station into the system by registering
        a **Facility** with its plant `name`, its `orispl_code` (the EIA/EPA plant
        code, between 1 and 8 characters long and globally unique — a repeat is
        rejected with `ERR_DUPLICATE_ORISPL_CODE`), its `state_code` (exactly two
        uppercase letters), the legal operating company in `operator_org`, the
        allowance `programs` the station is subject to, and the
        `true_up_deadline_utc` before which no allowance true-up may be run."

        PRD: "One electronic report exists per unit per calendar quarter, so a
        second attempt at the same triple is rejected with
        `ERR_DUPLICATE_REPORT_PERIOD` — a rejected report is reopened, never
        re-created."

        PRD: "The hour itself is identified by `hour_begin_utc`, the start of the
        clock hour it covers, whose minutes, seconds and milliseconds must all be
        zero; the pair of unit and `hour_begin_utc` is unique across all quarters,
        and a repeat is `ERR_DUPLICATE_OPERATING_HOUR`."

        PRD: "Exactly one account exists per facility, program and compliance year;
        a repeat is `ERR_DUPLICATE_ALLOWANCE_ACCOUNT`."

        PRD: "A unit may carry several limits on the same pollutant provided the
        averaging basis or the effective date differs; an exact repeat of unit,
        pollutant, averaging basis and effective instant is
        `ERR_DUPLICATE_PERMIT_LIMIT`."

        Design: Corner/validations/val_every_uniqueness_key_is_enforced_with_its_own_code
        """
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        facility_id = station["facility"]["id"]
        unit_id = station["unit"]["id"]

        report = fx.open_quarterly_report(unit_id)
        first_hour = fx.append_hour(unit_id, report["version"], fx.cems_hours(1)[0])
        report_version = first_hour["quarterly_report_version_after"]
        assert report_version == 2

        fx.open_allowance_account(
            facility_id,
            holdings_current_vintage_tons=10.0,
            holdings_prior_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )
        fx.create_permit_limit(
            unit_id, limit_value=300.0, effective_from_utc="2026-04-01T00:00:00Z"
        )

        validate_error(
            api_client.create_facility(
                {
                    "name": "Kestrel Generating Station Unit 2 Plant",
                    "orispl_code": "7101",
                    "state_code": "PA",
                    "operator_org": "op_beta",
                    "programs": ["ARP_SO2"],
                    "true_up_deadline_utc": "2027-03-01T00:00:00Z",
                },
                fx.REVIEWER,
            ),
            ApiErrorId.ERR_DUPLICATE_ORISPL_CODE.value,
        )
        validate_error(
            api_client.open_quarterly_report(
                unit_id, {"year": 2026, "quarter": 2}, fx.PREPARER
            ),
            ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD.value,
        )
        validate_error(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report_version,
                    cems_hour_payload(
                        "2026-04-01T00:00:00Z",
                        op_time_fraction=0.5,
                        so2_conc_ppm=100.0,
                    ),
                ),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_DUPLICATE_OPERATING_HOUR.value,
        )
        validate_error(
            api_client.open_allowance_account(
                facility_id,
                {
                    "program": "ARP_SO2",
                    "compliance_year": 2026,
                    "holdings_current_vintage_tons": 1.0,
                    "holdings_prior_vintage_tons": 0.0,
                    "holdings_next_vintage_tons": 0.0,
                },
                fx.REVIEWER,
            ),
            ApiErrorId.ERR_DUPLICATE_ALLOWANCE_ACCOUNT.value,
        )
        validate_error(
            api_client.create_permit_limit(
                unit_id,
                {
                    "pollutant": "SO2",
                    "limit_value": 275.0,
                    "limit_units": "LB_PER_HR",
                    "averaging_basis": "ROLLING_3_HOUR",
                    "effective_from_utc": "2026-04-01T00:00:00Z",
                },
                fx.REVIEWER,
            ),
            ApiErrorId.ERR_DUPLICATE_PERMIT_LIMIT.value,
        )

        stored_hour = validate_success(
            api_client.get_operating_hour(first_hour["id"], fx.PREPARER)
        )
        assert_operating_hour(stored_hour)
        assert stored_hour["op_time_fraction"] == 1.0, (
            "the refused duplicate must not have overwritten the stored hour"
        )
        assert stored_hour["so2_mass_lbs"] == 292.2

        next_quarter = validate_success(
            api_client.open_quarterly_report(
                unit_id, {"year": 2026, "quarter": 3}, fx.PREPARER
            ),
            201,
        )
        assert_quarterly_report(next_quarter)
        assert next_quarter["quarter"] == 3

        next_year = validate_success(
            api_client.open_allowance_account(
                facility_id,
                {
                    "program": "ARP_SO2",
                    "compliance_year": 2027,
                    "holdings_current_vintage_tons": 1.0,
                    "holdings_prior_vintage_tons": 0.0,
                    "holdings_next_vintage_tons": 0.0,
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert_allowance_account(next_year)
        assert next_year["compliance_year"] == 2027

        other_basis = validate_success(
            api_client.create_permit_limit(
                unit_id,
                {
                    "pollutant": "SO2",
                    "limit_value": 275.0,
                    "limit_units": "LB_PER_HR",
                    "averaging_basis": "ROLLING_30_DAY",
                    "effective_from_utc": "2026-04-01T00:00:00Z",
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert_permit_limit(other_basis)
        assert other_basis["averaging_basis"] == "ROLLING_30_DAY", (
            "limit_value is not part of the key, but averaging_basis is"
        )

        unspent = validate_success(
            api_client.get_quarterly_report(report["id"], fx.PREPARER)
        )
        assert unspent["version"] == report_version, (
            "not one of the five refusals spent the report's version, expected "
            f"{report_version}, got {unspent['version']}"
        )


class TestAllowanceProposalGuards:
    """Four codes across six malformed proposals, and no row written."""

    def test_zero_tonnage_a_client_penalty_and_four_bad_counterparties(self):
        """Six refusals leave the account at version 1 with its holdings intact.

        PRD: "Five business rules guard the proposal, evaluated in this order:
        `quantity_tons` must be strictly greater than zero, since direction is
        carried by `transaction_type` and never by a sign (`ERR_INVALID_QUANTITY`);
        `transaction_type` must not be `PENALTY_DEDUCTION`, because only the true-up
        cascade may create a penalty and only the cascade may drive the next-vintage
        bucket negative (`ERR_PENALTY_TRANSACTION_NOT_CLIENT_CREATABLE`); a
        `TRANSFER_OUT` or `TRANSFER_IN` must carry a `counterparty_account_id` that
        differs from `allowance_account_id` and belongs to an account of the same
        `program`, while a `PURCHASE`, `SURRENDER` or `PENALTY_DEDUCTION` must not
        carry one at all, since allowances never cross program boundaries
        (`ERR_INVALID_COUNTERPARTY`); and `vintage_year` must fall within the
        compliance year of the target account minus one through that year plus one,
        both endpoints accepted, which is exactly what makes the three holdings
        buckets exhaustive (`ERR_VINTAGE_YEAR_INVALID`)."

        Design: Corner/validations/val_allowance_proposal_guards_are_all_enforced
        """
        fx.set_clock(CLOCK_AUGUST)
        facility = fx.create_facility(programs=["ARP_SO2", "CSAPR_SO2_G1"])
        arp = fx.open_allowance_account(
            facility["id"],
            program="ARP_SO2",
            holdings_current_vintage_tons=10.0,
            holdings_prior_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )
        csapr = fx.open_allowance_account(
            facility["id"],
            program="CSAPR_SO2_G1",
            holdings_current_vintage_tons=4.0,
            holdings_prior_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )
        version = arp["version"]

        refusals = (
            (
                {"transaction_type": "PURCHASE", "quantity_tons": 0.000},
                ApiErrorId.ERR_INVALID_QUANTITY,
            ),
            (
                {
                    "transaction_type": "PENALTY_DEDUCTION",
                    "quantity_tons": 2.000,
                    "vintage_year": 2027,
                },
                ApiErrorId.ERR_PENALTY_TRANSACTION_NOT_CLIENT_CREATABLE,
            ),
            (
                {"transaction_type": "TRANSFER_OUT", "quantity_tons": 2.000},
                ApiErrorId.ERR_INVALID_COUNTERPARTY,
            ),
            (
                {
                    "transaction_type": "PURCHASE",
                    "quantity_tons": 2.000,
                    "counterparty_account_id": csapr["id"],
                },
                ApiErrorId.ERR_INVALID_COUNTERPARTY,
            ),
            (
                {
                    "transaction_type": "TRANSFER_OUT",
                    "quantity_tons": 2.000,
                    "counterparty_account_id": csapr["id"],
                },
                ApiErrorId.ERR_INVALID_COUNTERPARTY,
            ),
            (
                {
                    "transaction_type": "TRANSFER_OUT",
                    "quantity_tons": 2.000,
                    "counterparty_account_id": arp["id"],
                },
                ApiErrorId.ERR_INVALID_COUNTERPARTY,
            ),
        )
        assert len(refusals) == 6

        for overrides, error_id in refusals:
            validate_error(
                api_client.propose_allowance_transaction(
                    allowance_transaction_payload(version, arp["id"], **overrides),
                    fx.TRADER,
                ),
                error_id.value,
            )

        assert _transaction_total(arp["id"]) == 0, (
            "not one refused proposal may leave a transaction row behind"
        )
        after = _account(arp["id"])
        assert after["version"] == version
        assert after["holdings_current_vintage_tons"] == 10.000


class TestLockedAccountRefusesProposals:
    """The lock is checked ahead of the fiscal sufficiency rule."""

    def test_a_locked_account_refuses_both_a_purchase_and_an_overdraw(self):
        """The shortfall locks the account and the lock error wins both times.

        PRD: "A second `SETTLED` transaction with `origin` of `TRUE_UP_PENALTY` and
        `transaction_type` of `PENALTY_DEDUCTION` is created for `shortfall_tons`
        multiplied by the penalty ratio of 2.0 — twice the uncovered tonnage —
        rounded half up to three decimals."

        PRD: "A proposal against an account standing at `TRUE_UP_LOCKED` or
        `CLOSED` is rejected with `ERR_ACCOUNT_TRUE_UP_LOCKED`."

        PRD: "(17) `ERR_ACCOUNT_TRUE_UP_LOCKED` — ahead of the fiscal sufficiency
        rule, so a locked account rejects an over-drawing surrender with the lock
        error."

        PRD: "If **any** allowance account of the facility carries `shortfall_tons`
        greater than zero, `compliance_posture` is `DEFICIT`, regardless of
        holdings."

        Design: Corner/validations/val_locked_account_refuses_further_transactions
        """
        station = fx.setup_certified_so2_station(
            clock=CLOCK_APRIL,
            facility_overrides={"true_up_deadline_utc": "2026-04-05T00:00:00Z"},
        )
        facility_id = station["facility"]["id"]
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id)
        fx.append_hours_bulk(unit_id, report["version"], fx.cems_hours(3))

        accepted = fx.drive_report_to_accepted(report["id"])["report"]
        assert accepted["status"] == "ACCEPTED"
        assert accepted["total_so2_tons"] == 0.438

        account = fx.open_allowance_account(
            facility_id,
            holdings_current_vintage_tons=0.0,
            holdings_prior_vintage_tons=0.0,
            holdings_next_vintage_tons=0.0,
        )
        fx.set_clock("2026-04-06T00:00:00Z")

        validate_success(api_client.run_true_up(account["id"], {}, fx.REVIEWER))
        locked = _account(account["id"])
        assert_allowance_account(locked)
        assert locked["status"] == "TRUE_UP_LOCKED"
        assert locked["obligation_tons"] == 1
        assert locked["shortfall_tons"] == 1.000
        assert locked["penalty_deducted_tons"] == 2.000, (
            "one uncovered ton at the penalty ratio of 2.0 is 2.000 tons, got "
            f"{locked['penalty_deducted_tons']}"
        )
        assert locked["holdings_next_vintage_tons"] == -2.000, (
            "only the penalty path may drive a bucket negative"
        )
        locked_version = locked["version"]

        validate_error(
            api_client.propose_allowance_transaction(
                allowance_transaction_payload(
                    locked_version,
                    account["id"],
                    transaction_type="PURCHASE",
                    quantity_tons=5.000,
                ),
                fx.TRADER,
            ),
            ApiErrorId.ERR_ACCOUNT_TRUE_UP_LOCKED.value,
        )
        validate_error(
            api_client.propose_allowance_transaction(
                allowance_transaction_payload(
                    locked_version,
                    account["id"],
                    transaction_type="SURRENDER",
                    quantity_tons=900.000,
                ),
                fx.TRADER,
            ),
            ApiErrorId.ERR_ACCOUNT_TRUE_UP_LOCKED.value,
        )

        assert _account(account["id"])["version"] == locked_version, (
            "neither refusal touched the account"
        )
        facility = validate_success(
            api_client.get_facility(facility_id, fx.REVIEWER)
        )
        assert_facility(facility)
        assert facility["compliance_posture"] == "DEFICIT"


class TestVintageYearWindow:
    """Compliance year minus one through plus one, both endpoints accepted."""

    def test_2024_and_2028_are_refused_while_2025_and_2027_land_in_their_buckets(self):
        """The window is inclusive, which is what makes the three buckets exhaustive.

        PRD: "Five business rules guard the proposal, evaluated in this order:
        `quantity_tons` must be strictly greater than zero, since direction is
        carried by `transaction_type` and never by a sign (`ERR_INVALID_QUANTITY`);
        `transaction_type` must not be `PENALTY_DEDUCTION`, because only the true-up
        cascade may create a penalty and only the cascade may drive the next-vintage
        bucket negative (`ERR_PENALTY_TRANSACTION_NOT_CLIENT_CREATABLE`); a
        `TRANSFER_OUT` or `TRANSFER_IN` must carry a `counterparty_account_id` that
        differs from `allowance_account_id` and belongs to an account of the same
        `program`, while a `PURCHASE`, `SURRENDER` or `PENALTY_DEDUCTION` must not
        carry one at all, since allowances never cross program boundaries
        (`ERR_INVALID_COUNTERPARTY`); and `vintage_year` must fall within the
        compliance year of the target account minus one through that year plus one,
        both endpoints accepted, which is exactly what makes the three holdings
        buckets exhaustive (`ERR_VINTAGE_YEAR_INVALID`)."

        PRD: "Settlement selects a bucket by comparing `vintage_year` with the
        account's `compliance_year`: a vintage earlier than the compliance year
        addresses `holdings_prior_vintage_tons`, a vintage equal to it addresses
        `holdings_current_vintage_tons`, and a vintage later than it addresses
        `holdings_next_vintage_tons`."

        PRD: "A `PURCHASE` or `TRANSFER_IN` adds `quantity_tons` to that bucket and
        records all three `debited_*` amounts as 0.0."

        Design: Corner/validations/val_vintage_year_window_accepts_both_endpoints
        """
        fx.set_clock(CLOCK_AUGUST)
        facility = fx.create_facility()
        account = fx.open_allowance_account(
            facility["id"],
            holdings_current_vintage_tons=1.0,
            holdings_prior_vintage_tons=1.0,
            holdings_next_vintage_tons=1.0,
        )
        assert account["compliance_year"] == 2026

        for vintage in (2024, 2028):
            validate_error(
                api_client.propose_allowance_transaction(
                    allowance_transaction_payload(
                        account["version"],
                        account["id"],
                        transaction_type="PURCHASE",
                        quantity_tons=3.000,
                        vintage_year=vintage,
                    ),
                    fx.TRADER,
                ),
                ApiErrorId.ERR_VINTAGE_YEAR_INVALID.value,
            )

        banked = fx.settle_transaction(
            account["id"],
            _account(account["id"])["version"],
            transaction_type="PURCHASE",
            quantity_tons=3.000,
            vintage_year=2025,
        )
        assert_allowance_transaction(banked)
        assert banked["debited_prior_tons"] == 0.0
        assert banked["debited_current_tons"] == 0.0
        assert banked["debited_next_tons"] == 0.0

        after_prior = _account(account["id"])
        assert after_prior["holdings_prior_vintage_tons"] == 4.000, (
            "2025 is earlier than the 2026 compliance year, so it banks, got "
            f"{after_prior['holdings_prior_vintage_tons']}"
        )
        assert after_prior["holdings_current_vintage_tons"] == 1.000
        assert after_prior["holdings_next_vintage_tons"] == 1.000

        fx.settle_transaction(
            account["id"],
            after_prior["version"],
            transaction_type="PURCHASE",
            quantity_tons=4.000,
            vintage_year=2027,
        )
        after_next = _account(account["id"])
        assert after_next["holdings_next_vintage_tons"] == 5.000, (
            "2027 is later than the compliance year, so it lands in next vintage, "
            f"got {after_next['holdings_next_vintage_tons']}"
        )
        assert after_next["holdings_prior_vintage_tons"] == 4.000
        assert after_next["holdings_current_vintage_tons"] == 1.000

        assert _transaction_total(account["id"]) == 2, (
            "the two refused proposals created no rows"
        )
