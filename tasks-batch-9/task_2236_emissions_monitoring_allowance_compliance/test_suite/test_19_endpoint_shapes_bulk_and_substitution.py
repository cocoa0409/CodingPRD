"""Endpoint mechanics: the partial facility update and its filtered list, the
all-or-nothing bulk hour append, a transfer settlement across two accounts, and
the substitution procedure's half-open range."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allowance_account,
    assert_allowance_transaction,
    assert_facility,
    assert_operating_hour,
    assert_quarterly_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import bulk_hours_payload, cems_hour_payload, facility_payload

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
CLOCK_APRIL = "2026-04-02T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
OUT_OF_CONTROL_REASON = (
    "Daily calibration drift confirmed out of control from the 04:00 hour."
)


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


def _unit(unit_id):
    return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))


def _hours(unit_id):
    return validate_paginated(
        api_client.list_operating_hours(fx.PREPARER, {"unit_id": unit_id, "limit": 100})
    )


def _account(account_id):
    return validate_success(api_client.get_allowance_account(account_id, fx.TRADER))


class TestFacilityCrudAndFilteredListing:
    """Create, read, partially update, then find the updated row by filter."""

    def test_a_partial_patch_moves_only_two_fields_and_the_filtered_list_sees_it(self):
        """version 1 to 2 on two supplied fields; the other five stand still.

        PRD: "An optional `max_concurrent_control_outages` caps how much control
        equipment the station may have out of service at once; it defaults to 2 and
        must be at least 1. A new facility begins with `status` of `OPERATING` and a
        `compliance_posture` of `COMPLIANT`. The reviewer may later revise
        `true_up_deadline_utc`, `max_concurrent_control_outages` or `status` — the
        latter moving the facility to `RETIRED` — and each such revision increments
        the facility's `version` by one."

        PRD: "Facilities: `state_code`, `status`, `compliance_posture`,
        `operator_org`."

        Design: Corner/endpoints/ep_facility_create_read_update_and_list_all_work
        """
        fx.set_clock(CLOCK_AUGUST)

        created = validate_success(
            api_client.create_facility(
                facility_payload(true_up_deadline_utc="2027-03-01T00:00:00Z"),
                fx.REVIEWER,
            ),
            201,
        )
        assert_facility(created)
        assert created["version"] == 1
        assert created["status"] == "OPERATING"
        assert created["compliance_posture"] == "COMPLIANT"
        facility_id = created["id"]

        read_back = validate_success(api_client.get_facility(facility_id, fx.TRADER))
        assert read_back["id"] == facility_id
        assert read_back["max_concurrent_control_outages"] == 2, (
            "the omitted ceiling defaults to 2, got "
            f"{read_back['max_concurrent_control_outages']}"
        )
        assert read_back["version"] == 1, "a read never advances the version"

        patched = validate_success(
            api_client.update_facility(
                facility_id,
                {
                    "true_up_deadline_utc": "2027-04-01T00:00:00Z",
                    "max_concurrent_control_outages": 4,
                },
                fx.REVIEWER,
            )
        )
        assert patched["true_up_deadline_utc"] == "2027-04-01T00:00:00Z"
        assert patched["max_concurrent_control_outages"] == 4
        assert patched["version"] == 2, (
            f"one revision moves the version to 2, got {patched['version']}"
        )
        for field in ("name", "orispl_code", "state_code", "operator_org", "programs"):
            assert patched[field] == created[field], (
                f"{field} was not in the partial body and must be untouched"
            )
        assert patched["status"] == "OPERATING"

        rows, meta = validate_paginated(
            api_client.list_facilities(
                fx.REVIEWER,
                {"state_code": "OH", "status": "OPERATING", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["version"] == 2, "the list serves the updated row"

        other_state, other_meta = validate_paginated(
            api_client.list_facilities(fx.REVIEWER, {"state_code": "PA"})
        )
        assert other_meta["total_count"] == 0, (
            "state_code is an exact-match filter, so PA matches nothing"
        )
        assert other_state == []


class TestBulkAppendRefusals:
    """An empty array and an in-batch duplicate both take the whole batch down."""

    def _empty_report(self):
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        station["report"] = fx.open_quarterly_report(station["unit"]["id"])
        return station

    def test_an_empty_array_and_an_in_batch_duplicate_persist_nothing(self):
        """The individually valid 01:00 hour dies with its batch.

        PRD: "The array must hold at least 1 and at most 200 entries, else
        `ERR_BULK_SIZE_INVALID`."

        PRD: "The operation is strictly all-or-nothing: **any** per-item violation —
        a duplicate hour, a method field mismatch, an unanalysed sample, an
        out-of-range value, an hour outside the report period — rejects the entire
        array, persists nothing, and leaves the report's `version` exactly where it
        was."

        Design: Corner/endpoints/ep_bulk_hour_append_is_all_or_nothing_and_spends_one_version
        """
        station = self._empty_report()
        unit_id = station["unit"]["id"]
        report = station["report"]
        assert report["version"] == 1

        validate_error(
            api_client.append_operating_hours_bulk(
                unit_id, bulk_hours_payload(report["version"], []), fx.PREPARER
            ),
            ApiErrorId.ERR_BULK_SIZE_INVALID.value,
        )

        duplicated_inside = [
            cems_hour_payload("2026-04-01T00:00:00Z"),
            cems_hour_payload("2026-04-01T01:00:00Z"),
            cems_hour_payload("2026-04-01T00:00:00Z", so2_conc_ppm=100.0),
        ]
        validate_error(
            api_client.append_operating_hours_bulk(
                unit_id,
                bulk_hours_payload(report["version"], duplicated_inside),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_DUPLICATE_OPERATING_HOUR.value,
        )

        rows, meta = _hours(unit_id)
        assert meta["total_count"] == 0, (
            "the 01:00 hour was valid on its own but is discarded with the batch, got "
            f"{meta['total_count']} persisted hours"
        )
        assert rows == []
        assert _report(report["id"])["version"] == 1, (
            "a refused batch spends no report version"
        )


class TestBulkAppendOrderingAndVersionSpend:
    """A descending batch lands ascending and costs exactly one version."""

    def test_a_descending_two_hour_batch_spends_one_version_then_a_collision_refuses(
        self,
    ):
        """00:00 before 01:00 in the response, version 1 to 2, then a 409.

        PRD: "Hours are applied in `hour_begin_utc` ascending order regardless of the
        order they appear in the array, and exactly **one** report recompute runs
        after all of them are applied, so a successful bulk append advances the
        report's `version` by exactly one no matter how many hours it carried."

        PRD: "the pair of unit and `hour_begin_utc` is unique across all quarters,
        and a repeat is `ERR_DUPLICATE_OPERATING_HOUR`."

        PRD: "`total_heat_input_mmbtu` is the sum of the hours' `heat_input_mmbtu`,
        rounded half up to three decimals."

        Design: Corner/endpoints/ep_bulk_hour_append_is_all_or_nothing_and_spends_one_version
        """
        station = fx.setup_certified_so2_station(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id)

        descending = [
            cems_hour_payload("2026-04-01T01:00:00Z"),
            cems_hour_payload("2026-04-01T00:00:00Z"),
        ]
        appended = validate_success(
            api_client.append_operating_hours_bulk(
                unit_id, bulk_hours_payload(report["version"], descending), fx.PREPARER
            ),
            201,
        )
        assert len(appended) == 2
        assert [row["hour_begin_utc"] for row in appended] == [
            "2026-04-01T00:00:00Z",
            "2026-04-01T01:00:00Z",
        ], "the array was descending; the applied order is ascending"
        for row in appended:
            assert_operating_hour(row)
            assert row["quarterly_report_version_after"] == 2, (
                "one recompute for the whole batch, not one per hour, got "
                f"{row['quarterly_report_version_after']}"
            )

        after_batch = _report(report["id"])
        assert after_batch["version"] == 2

        collides_with_persisted = [
            cems_hour_payload("2026-04-01T02:00:00Z"),
            cems_hour_payload("2026-04-01T00:00:00Z"),
        ]
        validate_error(
            api_client.append_operating_hours_bulk(
                unit_id,
                bulk_hours_payload(after_batch["version"], collides_with_persisted),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_DUPLICATE_OPERATING_HOUR.value,
        )

        _, meta = _hours(unit_id)
        assert meta["total_count"] == 2, (
            "the fresh 02:00 hour is discarded along with the colliding one, got "
            f"{meta['total_count']}"
        )

        final = _report(report["id"])
        assert_quarterly_report(final)
        assert final["version"] == 2, "the refused batch left the version alone"
        assert final["operating_hour_count"] == 2
        assert final["total_heat_input_mmbtu"] == 1111.112, (
            f"two hours of 555.556 mmBtu, got {final['total_heat_input_mmbtu']}"
        )
        assert final["total_so2_lbs"] == 584.4
        assert final["total_nox_lbs"] == 200.0
        assert final["total_co2_tons"] == 119.400
        assert final["total_so2_tons"] == 0.292


class TestTransferOutAcrossTwoAccounts:
    """The sender drains oldest-first; the receiver is credited undivided."""

    def test_a_transfer_out_drains_two_buckets_and_credits_the_counterparty_in_one(self):
        """2.000 banked plus 1.000 current leave A; 3.000 lands in B's current.

        PRD: "(9) Every foreign key supplied in the request **body** resolves,
        checked in the order the fields are declared for that endpoint; this covers
        `allowance_account_id` and then `counterparty_account_id` on a transaction
        proposal, `fuel_sample_id` on a single or bulk operating-hour append, and
        `retest_of_rata_test_id` on scheduling an audit."

        PRD: "An accepted proposal stands at `PROPOSED` with `origin` of `MANUAL`,
        all three `debited_*` amounts 0.0, `reversal_reason` null, and no holdings
        moved yet; it reports `allowance_account_version_after`."

        PRD: "A `SURRENDER` or `TRANSFER_OUT` drains **oldest vintage first**:
        `debited_prior_tons` is the smaller of the quantity still to be taken and
        `holdings_prior_vintage_tons`; the remainder is then taken as
        `debited_current_tons`, the smaller of what is left and
        `holdings_current_vintage_tons`; if anything still remains the settlement is
        rejected with `ERR_INSUFFICIENT_ALLOWANCES`; `debited_next_tons` stays 0.0,
        because a client-initiated debit never touches the next-vintage bucket."

        PRD: "The two drained buckets are reduced by exactly those recorded amounts,
        and for a `TRANSFER_OUT` the counterparty account's bucket for the same
        `vintage_year` is credited by the full `quantity_tons`, incrementing that
        account's `version` by one."

        PRD: "`surrendered_tons` becomes the total `quantity_tons` across the
        account's `SETTLED` `SURRENDER` rows"

        Design: Corner/endpoints/ep_transfer_out_settlement_links_two_accounts
        """
        fx.set_clock(CLOCK_AUGUST)
        sender = fx.create_facility()
        receiver = fx.create_facility(
            name="Harrier Energy Center",
            orispl_code="7102",
            state_code="IN",
            operator_org="op_beta",
        )
        account_a = fx.open_allowance_account(
            sender["id"],
            holdings_current_vintage_tons=10.000,
            holdings_prior_vintage_tons=2.000,
            holdings_next_vintage_tons=0.000,
        )
        account_b = fx.open_allowance_account(
            receiver["id"],
            holdings_current_vintage_tons=0.000,
            holdings_prior_vintage_tons=0.000,
            holdings_next_vintage_tons=0.000,
        )

        validate_error(
            api_client.propose_allowance_transaction(
                {
                    "expected_allowance_account_version": account_a["version"],
                    "allowance_account_id": account_a["id"],
                    "transaction_type": "TRANSFER_OUT",
                    "quantity_tons": 3.000,
                    "vintage_year": 2026,
                    "counterparty_account_id": UNKNOWN_ID,
                },
                fx.TRADER,
            ),
            ApiErrorId.ERR_ALLOWANCE_ACCOUNT_NOT_FOUND.value,
        )
        _, empty_meta = validate_paginated(
            api_client.list_allowance_transactions(fx.TRADER)
        )
        assert empty_meta["total_count"] == 0, (
            "the unresolved counterparty created nothing"
        )

        proposed = validate_success(
            api_client.propose_allowance_transaction(
                {
                    "expected_allowance_account_version": account_a["version"],
                    "allowance_account_id": account_a["id"],
                    "transaction_type": "TRANSFER_OUT",
                    "quantity_tons": 3.000,
                    "vintage_year": 2026,
                    "counterparty_account_id": account_b["id"],
                },
                fx.TRADER,
            ),
            201,
        )
        assert_allowance_transaction(proposed)
        assert proposed["status"] == "PROPOSED"
        assert proposed["origin"] == "MANUAL"
        assert proposed["counterparty_account_id"] == account_b["id"]
        assert proposed["debited_prior_tons"] == 0.0
        assert proposed["debited_current_tons"] == 0.0
        assert proposed["debited_next_tons"] == 0.0

        recorded = fx.transition_transaction(proposed["id"], "RECORD")
        assert recorded["status"] == "RECORDED"
        mid = _account(account_a["id"])
        assert mid["holdings_prior_vintage_tons"] == 2.000, (
            "recording is not settling; no holdings may move yet"
        )
        assert mid["holdings_current_vintage_tons"] == 10.000
        assert mid["holdings_next_vintage_tons"] == 0.000

        settled = fx.transition_transaction(proposed["id"], "SETTLE")
        assert settled["status"] == "SETTLED"
        assert settled["debited_prior_tons"] == 2.000, (
            f"the banked bucket drains first, got {settled['debited_prior_tons']}"
        )
        assert settled["debited_current_tons"] == 1.000
        assert settled["debited_next_tons"] == 0.0

        after_a = _account(account_a["id"])
        assert_allowance_account(after_a)
        assert after_a["holdings_prior_vintage_tons"] == 0.000
        assert after_a["holdings_current_vintage_tons"] == 9.000
        assert after_a["surrendered_tons"] == 0.000, (
            "a transfer is not a surrender, so the surrendered ledger stays at zero"
        )

        after_b = _account(account_b["id"])
        assert after_b["holdings_current_vintage_tons"] == 3.000, (
            "the credit lands whole in the bucket B's own compliance_year selects, got "
            f"{after_b['holdings_current_vintage_tons']}"
        )
        assert after_b["holdings_prior_vintage_tons"] == 0.000
        assert after_b["holdings_next_vintage_tons"] == 0.000


class TestSubstitutionRangeRefusals:
    """An all-measured range, an inverted range and a zero-length range."""

    def test_all_measured_inverted_and_zero_length_ranges_are_each_refused(self):
        """The half-open range means from == to encloses nothing at all.

        PRD: "A range whose start is at or after its end is `ERR_INVALID_INTERVAL`; a
        range containing no hour whose `data_quality` is `UNAVAILABLE` is
        `ERR_NO_SUBSTITUTABLE_HOURS`, rather than being silently accepted as a no-op
        — re-running the procedure over an already-substituted range would let the
        tier drift as availability changes."

        Design: Corner/endpoints/ep_substitution_runs_only_over_unavailable_hours
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=5, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]

        validate_error(
            api_client.run_missing_data_substitution(
                unit_id,
                {
                    "from_hour_utc": "2026-04-01T00:00:00Z",
                    "to_hour_utc": "2026-04-01T05:00:00Z",
                },
                fx.PREPARER,
            ),
            ApiErrorId.ERR_NO_SUBSTITUTABLE_HOURS.value,
        )
        validate_error(
            api_client.run_missing_data_substitution(
                unit_id,
                {
                    "from_hour_utc": "2026-04-01T05:00:00Z",
                    "to_hour_utc": "2026-04-01T04:00:00Z",
                },
                fx.PREPARER,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
        )
        validate_error(
            api_client.run_missing_data_substitution(
                unit_id,
                {
                    "from_hour_utc": "2026-04-01T04:00:00Z",
                    "to_hour_utc": "2026-04-01T04:00:00Z",
                },
                fx.PREPARER,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
        )

        rows, meta = _hours(unit_id)
        assert meta["total_count"] == 5
        assert all(row["data_quality"] == "MEASURED" for row in rows), (
            "three refusals must leave every hour measured"
        )
        assert all(row["substitution_method"] == "NONE" for row in rows)
        assert _unit(unit_id)["data_availability_pct"] == 100.0


class TestSubstitutionPricesOneHourThenRefusesTheRerun:
    """One flipped hour is priced from its lookback set, and only once."""

    def test_one_unavailable_hour_is_substituted_and_the_repeat_run_is_refused(self):
        """292.2 lb from a 220 ppm lookback, then ERR_NO_SUBSTITUTABLE_HOURS.

        PRD: "**Link 2**, caused by the QA state change rather than by the
        calibration itself. Every operating hour of this system's unit whose
        `hour_begin_utc` is at or after `out_of_control_since_utc` truncated to the
        hour, and whose `data_quality` is `MEASURED`, is set to `data_quality` of
        `UNAVAILABLE` with its `so2_mass_lbs` cleared to null."

        PRD: "First, availability for a target hour is computed **excluding that hour
        itself and every hour whose `hour_begin_utc` is at or after it**; this is what
        breaks the circularity."

        PRD: "Otherwise, if availability is **at or above** 95.0 percent,
        `substitution_method` is `T1_90TH_PERCENTILE` and the value is the 90th
        percentile of the lookback set."

        PRD: "The tier's value is written to `substituted_so2_conc_ppm` as a whole
        number, taken verbatim from the lookback set rather than interpolated,
        `data_quality` becomes `SUBSTITUTED`, and `so2_mass_lbs` is recomputed as the
        SO2 mass conversion constant 0.000000166 multiplied by the substitute
        concentration, by `flow_scfh` and by `op_time_fraction`, rounded half up to
        one decimal."

        PRD: "Hours that are `SUBSTITUTED` and hours that are `UNAVAILABLE` are both
        in the denominator and neither is in the numerator, which is what makes an
        unmonitored hour costly."

        Design: Corner/endpoints/ep_substitution_runs_only_over_unavailable_hours
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=5, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report_id = station["report"]["id"]

        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T04:00:00Z",
            reason=OUT_OF_CONTROL_REASON,
        )

        rows, _ = _hours(unit_id)
        flipped = [
            row for row in rows if row["hour_begin_utc"] == "2026-04-01T04:00:00Z"
        ]
        assert len(flipped) == 1
        assert flipped[0]["data_quality"] == "UNAVAILABLE"
        assert flipped[0]["so2_mass_lbs"] is None, (
            "an unavailable hour carries no SO2 mass"
        )
        assert flipped[0]["heat_input_mmbtu"] == 555.556, (
            "only the mass is cleared; heat input survives the flip"
        )
        assert _unit(unit_id)["data_availability_pct"] == 80.0, (
            "4 measured of 5 operating hours"
        )
        assert _report(report_id)["total_so2_lbs"] == 1168.8, (
            "the flipped hour contributes nothing to the report total"
        )

        substituted = validate_success(
            api_client.run_missing_data_substitution(
                unit_id,
                {
                    "from_hour_utc": "2026-04-01T04:00:00Z",
                    "to_hour_utc": "2026-04-01T05:00:00Z",
                },
                fx.PREPARER,
            )
        )
        assert len(substituted) == 1, (
            f"only the unavailable hour is in range, got {len(substituted)} rows"
        )
        hour = substituted[0]
        assert_operating_hour(hour)
        assert hour["hour_begin_utc"] == "2026-04-01T04:00:00Z"
        assert hour["data_quality"] == "SUBSTITUTED"
        assert hour["monitor_data_availability_pct_at_substitution"] == 100.0, (
            "the four hours strictly earlier than 04:00 are all measured, got "
            f"{hour['monitor_data_availability_pct_at_substitution']}"
        )
        assert hour["substitution_method"] == "T1_90TH_PERCENTILE", (
            "100.0 is at or above 95.0, so the first non-empty-lookback tier wins"
        )
        assert hour["substituted_so2_conc_ppm"] == 220.0, (
            "every member of the lookback set is 220 ppm"
        )
        assert hour["so2_mass_lbs"] == 292.2, (
            f"0.000000166 * 220 * 8000000 * 1.0 is 292.2, got {hour['so2_mass_lbs']}"
        )

        after = _report(report_id)
        assert after["total_so2_lbs"] == 1461.0, (
            f"1168.8 plus the substituted 292.2, got {after['total_so2_lbs']}"
        )
        assert after["substituted_hour_count"] == 1
        assert after["measured_hour_count"] == 4
        assert _unit(unit_id)["data_availability_pct"] == 80.0, (
            "a substituted hour is in the denominator and not in the numerator"
        )

        validate_error(
            api_client.run_missing_data_substitution(
                unit_id,
                {
                    "from_hour_utc": "2026-04-01T04:00:00Z",
                    "to_hour_utc": "2026-04-01T05:00:00Z",
                },
                fx.PREPARER,
            ),
            ApiErrorId.ERR_NO_SUBSTITUTABLE_HOURS.value,
        )
