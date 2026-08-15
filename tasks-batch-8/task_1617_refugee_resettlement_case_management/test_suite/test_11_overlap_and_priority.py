"""Interval overlap geometry and validation priority pairs (PRD §2.5, §2.7,
§3.2, §3.4): half-open housing adjacency vs the orientation buffer, and the
fixed error-selection order when two rules fail at once.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_case, make_housing_unit, make_housing_setup,
    setup_arrived_case, set_clock, get_benchmark_by_type, waive_benchmark,
    make_service_delivery_note,
)
from test_helpers.fixtures import CM, HC, AD


class TestHousingHalfOpenAdjacency:
    def _unit_with_existing_window(self):
        case_a = make_case(case_number="CASE-TO1A", household_size=2)
        unit = make_housing_unit(address="190 Alder St", bedrooms=1)
        make_housing_setup(case_a["id"], unit["id"],
                           occupancy_start="2026-08-10",
                           occupancy_end="2027-02-10")
        return unit

    def test_adjacent_window_starting_at_existing_end_allowed(self, api):
        """PRD §2.7: "Occupancy windows and report periods are half-open
        intervals: the start date is included and the end date is excluded,
        so two windows that merely touch at a boundary do not overlap."
        PRD §3.2: "the new occupancy window must not overlap the window of
        any other non-terminal setup on the same unit, where overlap is
        judged on half-open intervals so a window starting the day another
        ends is allowed".

        Design: Difficulty/resource_temporal_overlap/housing_half_open_adjacency
        """
        unit = self._unit_with_existing_window()
        case_b = make_case(case_number="CASE-TO1B", household_size=2,
                           scheduled_arrival_date="2027-02-10")
        resp = api.create_housing_setup(
            {"case_id": case_b["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2027-02-10", "occupancy_end": "2027-08-10"}, HC)
        setup = validate_success(resp, 201)
        assert setup["status"] == "PREPARING"

    def test_window_one_day_into_existing_window_rejected(self, api):
        """PRD §3.2: "a genuine overlap is rejected with
        `ERR_UNIT_OCCUPANCY_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/housing_half_open_adjacency
        """
        unit = self._unit_with_existing_window()
        case_c = make_case(case_number="CASE-TO1C", household_size=2,
                           scheduled_arrival_date="2027-02-09")
        resp = api.create_housing_setup(
            {"case_id": case_c["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2027-02-09", "occupancy_end": "2027-08-09"}, HC)
        validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPANCY_CONFLICT)


class TestBenchmarkStateBeatsEvidenceLinkage:
    def _waived_benchmark_and_foreign_note(self):
        ctx_a = setup_arrived_case(case_number="CASE-PV1A", household_size=1)
        bm = get_benchmark_by_type(ctx_a["case"]["id"], "HOME_VISIT", headers=AD)
        waive_benchmark(bm["id"],
                        reason="Service delivered by another affiliate before case reassignment")
        case_b = make_case(case_number="CASE-PV1B", household_size=1,
                           scheduled_arrival_date="2026-09-01")
        note_b = make_service_delivery_note(
            case_b["id"], body="Unrelated service on another case",
            service_date="2026-08-15")
        set_clock("2026-08-20T00:00:00Z")
        return bm, note_b

    def test_waived_benchmark_with_wrong_case_note_yields_not_pending(self, api):
        """PRD §2.5: "Sixth, state-machine legality — wrong from-state,
        terminal lockdown, state-gated creates — else `ERR_INVALID_STATE` or
        `ERR_BENCHMARK_NOT_PENDING`. ... Tenth, evidence linkage on benchmark
        fulfillment, else `ERR_EVIDENCE_NOTE_INVALID`." PRD §3.4: "The
        benchmark must be `PENDING` — fulfilling or waiving a benchmark in
        any other state is rejected with `ERR_BENCHMARK_NOT_PENDING`
        (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/benchmark_state_vs_referential_priority
        """
        bm, note_b = self._waived_benchmark_and_foreign_note()
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-08-15",
                       "evidence_note_id": note_b["id"]}, CM)
        validate_error(resp, ApiErrorId.ERR_BENCHMARK_NOT_PENDING)

    def test_priority_winner_is_not_evidence_error(self, api):
        """PRD §2.5: "When a request violates more than one rule, the API
        reports exactly one error, chosen by the following priority order,
        highest first." and "Sixth, state-machine legality — wrong
        from-state, terminal lockdown, state-gated creates — else
        `ERR_INVALID_STATE` or `ERR_BENCHMARK_NOT_PENDING`. ... Tenth,
        evidence linkage on benchmark fulfillment, else
        `ERR_EVIDENCE_NOTE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/benchmark_state_vs_referential_priority
        """
        bm, note_b = self._waived_benchmark_and_foreign_note()
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-08-15",
                       "evidence_note_id": note_b["id"]}, CM)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_BENCHMARK_NOT_PENDING"
        assert body["data"]["error_id"] != "ERR_EVIDENCE_NOTE_INVALID"
        assert resp.status_code == 409


class TestHousingCapacityBeatsOccupancyConflict:
    def _occupied_unit_and_large_case(self):
        case_a = make_case(case_number="CASE-PV2A", household_size=2)
        unit = make_housing_unit(address="130 Elm Ct", bedrooms=1)
        make_housing_setup(case_a["id"], unit["id"],
                           occupancy_start="2026-08-10",
                           occupancy_end="2027-02-10")
        case_b = make_case(case_number="CASE-PV2B", household_size=4,
                           scheduled_arrival_date="2026-09-01")
        return unit, case_b

    def test_capacity_error_wins_over_overlap_error(self, api):
        """PRD §2.5: "Seventh, housing capacity, else
        `ERR_HOUSING_CAPACITY_INSUFFICIENT`. Eighth, temporal interval
        conflicts, else the matching one of `ERR_UNIT_OCCUPANCY_CONFLICT`,
        `ERR_SESSION_SCHEDULE_CONFLICT`, or `ERR_REPORT_PERIOD_OVERLAP`."
        PRD §3.2: "The capacity rule prevents overcrowding: the unit's
        `bedrooms` must be at least the household size divided by two and
        rounded up to a whole number — a household of five therefore needs at
        least three bedrooms — and a unit that is too small is rejected with
        `ERR_HOUSING_CAPACITY_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/housing_safety_vs_temporal_priority
        """
        unit, case_b = self._occupied_unit_and_large_case()
        resp = api.create_housing_setup(
            {"case_id": case_b["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-09-01", "occupancy_end": "2027-03-01"}, HC)
        validate_error(resp, ApiErrorId.ERR_HOUSING_CAPACITY_INSUFFICIENT)

    def test_priority_winner_is_not_occupancy_conflict(self, api):
        """PRD §2.5: "When a request violates more than one rule, the API
        reports exactly one error, chosen by the following priority order,
        highest first." and "Seventh, housing capacity, else
        `ERR_HOUSING_CAPACITY_INSUFFICIENT`. Eighth, temporal interval
        conflicts, else the matching one of `ERR_UNIT_OCCUPANCY_CONFLICT`,
        `ERR_SESSION_SCHEDULE_CONFLICT`, or `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/housing_safety_vs_temporal_priority
        """
        unit, case_b = self._occupied_unit_and_large_case()
        resp = api.create_housing_setup(
            {"case_id": case_b["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-09-01", "occupancy_end": "2027-03-01"}, HC)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_HOUSING_CAPACITY_INSUFFICIENT"
        assert body["data"]["error_id"] != "ERR_UNIT_OCCUPANCY_CONFLICT"
        assert resp.status_code == 422
