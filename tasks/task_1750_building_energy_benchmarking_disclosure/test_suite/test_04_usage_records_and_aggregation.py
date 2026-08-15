"""Usage records: half-open overlap, per-record kBtu rounding, void/replace (PRD §2.6, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_utility_account,
    create_building,
    create_owner,
    get_report,
    make_owner_headers,
    setup_report_scenario,
    upload_usage,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
UTILITY = TEST_USERS["utility_agent_headers"]


class TestUsagePeriodOverlap:
    def _setup_account_with_january_record(self):
        owner = create_owner()
        building = create_building(owner["id"])
        account = add_utility_account(building["id"], owner["id"], account_number="E-1")
        r1 = upload_usage(account["id"], "2027-01-01T00:00:00Z", "2027-02-01T00:00:00Z", 100000)
        return account, r1

    def test_back_to_back_usage_periods_accepted(self, api):
        """PRD §3.4: "Within one account, the half-open periods of `ACTIVE` records
        may never intersect: two half-open periods overlap whenever each one's start
        falls strictly before the other's end, and an intersecting upload is rejected
        with `ERR_USAGE_PERIOD_OVERLAP`."

        A record starting exactly at the existing record's period_end shares no time
        with it under half-open semantics.

        Design: Difficulty/resource_temporal_overlap/usage_periods_half_open_adjacency
        """
        account, _r1 = self._setup_account_with_january_record()

        resp = api.create_usage_record(
            account["id"],
            {
                "period_start": "2027-02-01T00:00:00Z",
                "period_end": "2027-03-01T00:00:00Z",
                "consumption_value": 50000,
            },
            UTILITY,
        )
        record = validate_success(resp, 201)
        assert record["status"] == "ACTIVE"
        assert record["kbtu"] == 170600, "50000 kWh * 3.412 rounded per record"

    def test_interior_overlapping_usage_rejected(self, api):
        """PRD §3.4: "Within one account, the half-open periods of `ACTIVE` records
        may never intersect: two half-open periods overlap whenever each one's start
        falls strictly before the other's end, and an intersecting upload is rejected
        with `ERR_USAGE_PERIOD_OVERLAP`."

        [2027-01-15, 2027-02-15) starts strictly before the existing record's end and
        the existing record starts strictly before the candidate's end: an overlap.

        Design: Difficulty/resource_temporal_overlap/usage_periods_half_open_adjacency
        """
        account, _r1 = self._setup_account_with_january_record()

        resp = api.create_usage_record(
            account["id"],
            {
                "period_start": "2027-01-15T00:00:00Z",
                "period_end": "2027-02-15T00:00:00Z",
                "consumption_value": 1000,
            },
            UTILITY,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_PERIOD_OVERLAP)


class TestAccountNumberUniqueness:
    def test_duplicate_account_number_scoped_per_building(self, api):
        """PRD §3.4: "Each account carries an `account_number`, which must be unique
        within its building — a duplicate is refused with `ERR_DUPLICATE_ACCOUNT`"

        Design: Corner/validations/v_duplicate_account_number_rejected
        """
        owner = create_owner()
        b1 = create_building(owner["id"], address="65 Main St")
        b2 = create_building(owner["id"], address="66 Main St")
        add_utility_account(b1["id"], owner["id"], account_number="E-1", commodity="ELECTRICITY")

        dup = api.create_utility_account(
            b1["id"],
            {"account_number": "E-1", "commodity": "NATURAL_GAS"},
            make_owner_headers(owner["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACCOUNT)

        ok = api.create_utility_account(
            b2["id"],
            {"account_number": "E-1", "commodity": "ELECTRICITY"},
            make_owner_headers(owner["id"]),
        )
        created = validate_success(ok, 201)
        assert created["account_number"] == "E-1", "same number on another building is fine"


class TestPerRecordRounding:
    def _setup_three_small_records(self):
        ctx = setup_report_scenario(
            consent_indexes=(),
            usage_records=[
                {
                    "period_start": "2027-01-01T00:00:00Z",
                    "period_end": "2027-02-01T00:00:00Z",
                    "consumption_value": 10.5,
                },
                {
                    "period_start": "2027-02-01T00:00:00Z",
                    "period_end": "2027-03-01T00:00:00Z",
                    "consumption_value": 10.5,
                },
                {
                    "period_start": "2027-03-01T00:00:00Z",
                    "period_end": "2027-04-01T00:00:00Z",
                    "consumption_value": 10.5,
                },
            ],
        )
        return ctx

    def test_usage_kbtu_rounded_per_record(self, api):
        """PRD §2.6: "Each record's `kbtu` is its `consumption_value` multiplied by
        its commodity's factor, rounded half-up to a whole integer of kBtu; the
        whole-building total is the sum of those already-rounded integers."

        10.5 kWh * 3.412 = 35.826 -> 36 on each of the three records.

        Design: Difficulty/combinatorial_formula/per_record_kbtu_rounding_then_sum
        """
        ctx = self._setup_three_small_records()

        data, meta = validate_paginated(
            api.list_usage_records(OFFICER, params={"utility_account_id": ctx["account"]["id"]})
        )
        assert meta["total_count"] == 3
        for rec in data:
            assert rec["kbtu"] == 36, "per-record round-half-up of 35.826 kBtu"

    def test_aggregation_sums_per_record_rounded_kbtu(self, api):
        """PRD §2.6: "Rounding order is pinned and non-negotiable: conversion and
        rounding happen **per usage record**, and only then are the per-record values
        summed."
        PRD §2.6: "Raw consumption values are never summed first and converted
        afterward."

        36 + 36 + 36 = 108; the forbidden sum-then-round order would give
        round(31.5 * 3.412) = 107.

        Design: Difficulty/combinatorial_formula/per_record_kbtu_rounding_then_sum
        """
        ctx = self._setup_three_small_records()
        report = get_report(ctx["report"]["id"])
        assert report["aggregated_kbtu"] == 108, "sum of per-record rounded integers"


class TestAggregationInputSet:
    def test_aggregation_excludes_voided_and_straddling(self, api):
        """PRD §3.5: "The aggregate includes exactly the `ACTIVE` usage records
        belonging to the building's utility accounts whose half-open period is fully
        contained in the cycle year: `period_start` on or after midnight of January 1
        of the `cycle_year`, and `period_end` on or before midnight of January 1 of
        the following year."
        PRD §3.5: "Records that straddle the year boundary are excluded entirely, as
        are `VOIDED` records."

        A (Jan, 341200 kBtu) counts; B (Dec 15 -> Jan 15) straddles and is excluded;
        C is voided and excluded.

        Design: Corner/calculations/c_aggregation_excludes_voided_and_straddling_records
        """
        ctx = setup_report_scenario(
            consent_indexes=(),
            usage_records=[
                {
                    "period_start": "2027-01-01T00:00:00Z",
                    "period_end": "2027-02-01T00:00:00Z",
                    "consumption_value": 100000,
                },
                {
                    "period_start": "2027-12-15T00:00:00Z",
                    "period_end": "2028-01-15T00:00:00Z",
                    "consumption_value": 999999,
                },
                {
                    "period_start": "2027-03-01T00:00:00Z",
                    "period_end": "2027-04-01T00:00:00Z",
                    "consumption_value": 50000,
                },
            ],
        )
        # Void the third record; the report (DRAFT) recomputes.
        r_c = ctx["usage_records"][2]
        voided = validate_success(
            api.void_usage_record(r_c["id"], {"reason": "Erroneous upload"}, UTILITY)
        )
        assert voided["status"] == "VOIDED"

        report = get_report(ctx["report"]["id"])
        assert report["aggregated_kbtu"] == 341200, "only the fully-contained ACTIVE record counts"

        active, meta = validate_paginated(
            api.list_usage_records(
                OFFICER, params={"utility_account_id": ctx["account"]["id"], "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 2, "the straddling record is still ACTIVE yet excluded"
        active_ids = {r["id"] for r in active}
        assert ctx["usage_records"][1]["id"] in active_ids


class TestVoidWithReplacement:
    def _setup_two_records_with_report(self):
        ctx = setup_report_scenario(
            consent_indexes=(),
            usage_records=[
                {
                    "period_start": "2027-01-01T00:00:00Z",
                    "period_end": "2027-02-01T00:00:00Z",
                    "consumption_value": 100000,
                },
                {
                    "period_start": "2027-02-01T00:00:00Z",
                    "period_end": "2027-03-01T00:00:00Z",
                    "consumption_value": 50000,
                },
            ],
        )
        return ctx

    def test_identical_replacement_conserves_aggregated_kbtu(self, api):
        """PRD §3.4: "On success the system creates the replacement as a new `ACTIVE`
        record on the same account, its `replaces_usage_record_id` pointing at the
        voided record and its own `kbtu` computed per §2.6."
        PRD §3.4: "First, the building's report for the matching cycle year —
        whatever its status — recomputes `aggregated_kbtu` and `site_eui`"

        Voiding the February record with a byte-identical replacement leaves the
        total at exactly 511800 (341200 + 170600): forward and compensating writes
        cancel with zero drift.

        Design: Difficulty/compensating_invariant/usage_void_with_identical_replacement_conserves_kbtu
        """
        ctx = self._setup_two_records_with_report()
        r2 = ctx["usage_records"][1]
        assert ctx["report"]["aggregated_kbtu"] == 511800

        voided = validate_success(
            api.void_usage_record(
                r2["id"],
                {
                    "reason": "Correction re-keyed identically",
                    "replacement_period_start": "2027-02-01T00:00:00Z",
                    "replacement_period_end": "2027-03-01T00:00:00Z",
                    "replacement_consumption_value": 50000,
                },
                UTILITY,
            )
        )
        assert voided["status"] == "VOIDED"

        report = get_report(ctx["report"]["id"])
        assert report["aggregated_kbtu"] == 511800, "invariant conserved"

    def test_replacement_record_links_back_to_voided(self, api):
        """PRD §3.4: "On success the system creates the replacement as a new `ACTIVE`
        record on the same account, its `replaces_usage_record_id` pointing at the
        voided record and its own `kbtu` computed per §2.6."

        Design: Difficulty/compensating_invariant/usage_void_with_identical_replacement_conserves_kbtu
        """
        ctx = self._setup_two_records_with_report()
        r2 = ctx["usage_records"][1]

        validate_success(
            api.void_usage_record(
                r2["id"],
                {
                    "reason": "Correction re-keyed identically",
                    "replacement_period_start": "2027-02-01T00:00:00Z",
                    "replacement_period_end": "2027-03-01T00:00:00Z",
                    "replacement_consumption_value": 50000,
                },
                UTILITY,
            )
        )

        data, meta = validate_paginated(
            api.list_usage_records(OFFICER, params={"replaces_usage_record_id": r2["id"]})
        )
        assert meta["total_count"] == 1, "exactly one replacement points at the voided record"
        replacement = data[0]
        assert replacement["status"] == "ACTIVE"
        assert replacement["kbtu"] == 170600
        assert replacement["replaces_usage_record_id"] == r2["id"]

        original = validate_success(api.get_usage_record(r2["id"], OFFICER))
        assert original["status"] == "VOIDED"

    def test_voided_record_cannot_be_voided_again(self, api):
        """PRD §3.4: "A `UtilityAgent` voids an `ACTIVE` record — a record in any
        other state yields `ERR_INVALID_STATE_TRANSITION`"

        Design: Corner/state_machines/s_usage_void_from_voided_rejected
        """
        ctx = self._setup_two_records_with_report()
        r1 = ctx["usage_records"][0]
        validate_success(api.void_usage_record(r1["id"], {"reason": "Duplicate upload"}, UTILITY))

        resp = api.void_usage_record(r1["id"], {"reason": "Second void attempt"}, UTILITY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
