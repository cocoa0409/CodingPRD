"""Benchmark lifecycle (PRD §3.3, §3.4): dual due-date bases, the inclusive
on-time boundary, fulfilled_on window validation, evidence-note linkage,
school-enrollment member-set gate, and the fulfill/rescind partition
invariant.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    date_part,
    assert_service_benchmark, assert_benchmark_partition, setup_arrived_case,
    set_clock, get_benchmark_by_type, list_case_benchmarks, make_service_delivery_note,
    make_case_note, fulfill_benchmark, waive_benchmark,
    rescind_benchmark,
)
from test_helpers.fixtures import CM, AD


def _arrived_case_with_note(case_number, members=(), household_size=1,
                            clock="2026-09-10T00:00:00Z",
                            note_service_date="2026-09-09", note_body="Service"):
    """Arrived case + one SERVICE_DELIVERY note + clock advanced."""
    ctx = setup_arrived_case(case_number=case_number, household_size=household_size,
                             members=members)
    note = make_service_delivery_note(ctx["case"]["id"], body=note_body,
                                      service_date=note_service_date)
    set_clock(clock)
    return ctx, note


class TestDualDueDateBasisDivergence:
    def test_actual_basis_scores_on_time_when_scheduled_basis_would_be_late(self, api):
        """PRD §3.3: "The planning view, `planned_due_date`, is the
        `scheduled_arrival_date` plus the rule's offset. The compliance view,
        `due_date`, is the `actual_arrival_date` plus the same offset.
        Whenever actual arrival differs from schedule, the two bases diverge,
        and the same fulfillment date can be late under the scheduled basis
        yet on time under the actual basis; only the actual basis drives
        compliance."

        Design: Difficulty/dual_variant_calc/benchmark_due_basis_divergence
        """
        ctx = setup_arrived_case(case_number="CASE-DV1", household_size=2,
                                 scheduled_arrival_date="2026-08-10",
                                 actual_arrival_date="2026-08-20")
        note = make_service_delivery_note(ctx["case"]["id"],
                                          body="Home visit completed",
                                          service_date="2026-09-15")
        set_clock("2026-09-15T00:00:00Z")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        fulfilled = fulfill_benchmark(bm["id"], "2026-09-15", note["id"])
        assert fulfilled["status"] == "MET"
        assert fulfilled["on_time"] is True

    def test_planned_and_actual_due_dates_stored_at_seeding(self, api):
        """PRD §3.3: "Every benchmark is stored with two due dates computed
        at seeding time from its `due_rule`: 30 days for `DAYS_30`, 90 days
        for `DAYS_90`. The planning view, `planned_due_date`, is the
        `scheduled_arrival_date` plus the rule's offset. The compliance view,
        `due_date`, is the `actual_arrival_date` plus the same offset."

        Design: Difficulty/dual_variant_calc/benchmark_due_basis_divergence
        """
        ctx = setup_arrived_case(case_number="CASE-DV1C", household_size=2,
                                 scheduled_arrival_date="2026-08-10",
                                 actual_arrival_date="2026-08-20")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        assert date_part(bm["planned_due_date"]) == "2026-09-09"
        assert date_part(bm["due_date"]) == "2026-09-19"


class TestFulfillOnDueDateBoundary:
    def test_fulfill_exactly_on_due_date_is_on_time(self, api):
        """PRD §3.4: "A successful fulfillment moves the benchmark `PENDING →
        MET`, stores `fulfilled_on` and `evidence_note_id` from the request,
        and sets `on_time` by comparing `fulfilled_on` against the
        actual-basis `due_date`: fulfillment on or before the due date counts
        on time, with the boundary inclusive, so fulfilling exactly on the
        due date is on time and fulfilling one day after is late."

        Design: Difficulty/boundary_precision_check/fulfill_on_due_date_boundary
        """
        ctx, note = _arrived_case_with_note("CASE-BP1", note_body="Home visit")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        assert date_part(bm["due_date"]) == "2026-09-09"
        fulfilled = fulfill_benchmark(bm["id"], "2026-09-09", note["id"])
        assert fulfilled["status"] == "MET"
        assert fulfilled["on_time"] is True

    def test_fulfill_one_day_after_due_date_is_late(self, api):
        """PRD §3.4: "fulfillment on or before the due date counts on time,
        with the boundary inclusive, so fulfilling exactly on the due date is
        on time and fulfilling one day after is late."

        Design: Difficulty/boundary_precision_check/fulfill_on_due_date_boundary
        """
        ctx, note = _arrived_case_with_note("CASE-BP1B", note_body="Health screening",
                                            note_service_date="2026-09-10")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HEALTH_SCREENING")
        assert date_part(bm["due_date"]) == "2026-09-09"
        fulfilled = fulfill_benchmark(bm["id"], "2026-09-10", note["id"])
        assert fulfilled["status"] == "MET"
        assert fulfilled["on_time"] is False


class TestFulfilledOnWindow:
    def test_fulfilled_on_before_arrival_rejected(self, api):
        """PRD §3.4: "The `fulfilled_on` date must fall on or after the
        case's `actual_arrival_date` and on or before the current logical
        clock date; outside that window the request fails with
        `ERR_VALIDATION`."

        Design: Corner/validations/fulfilled_on_before_arrival_returns_invalid_request
        """
        ctx, note = _arrived_case_with_note("CASE-V2", clock="2026-08-20T00:00:00Z",
                                            note_service_date="2026-08-05",
                                            note_body="Visit")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-08-05", "evidence_note_id": note["id"]}, CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_fulfilled_on_after_clock_rejected(self, api):
        """PRD §3.4: "The `fulfilled_on` date must fall on or after the
        case's `actual_arrival_date` and on or before the current logical
        clock date; outside that window the request fails with
        `ERR_VALIDATION`."

        Design: Corner/validations/fulfilled_on_after_clock_returns_invalid_request
        """
        ctx, note = _arrived_case_with_note("CASE-V3", clock="2026-08-20T00:00:00Z",
                                            note_service_date="2026-09-01",
                                            note_body="Visit")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-09-01", "evidence_note_id": note["id"]}, CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestEvidenceNoteLinkage:
    def test_general_note_rejected_as_evidence(self, api):
        """PRD §3.4: "The evidence note must exist, must belong to the same
        case as the benchmark, and must be a `SERVICE_DELIVERY` note; any
        other linkage is rejected with `ERR_EVIDENCE_NOTE_INVALID`
        (HTTP 422)."

        Design: Corner/validations/evidence_note_wrong_type_returns_invalid_evidence
        """
        ctx = setup_arrived_case(case_number="CASE-V9", household_size=1)
        note = make_case_note(ctx["case"]["id"], note_type="GENERAL",
                              body="General observation")
        set_clock("2026-08-20T00:00:00Z")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-08-15", "evidence_note_id": note["id"]}, CM)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOTE_INVALID)


class TestSchoolEnrollmentMemberSet:
    def _case_with_two_school_age_children(self):
        return setup_arrived_case(
            case_number="CASE-V8", household_size=3,
            members=[{"full_name": "Adult V", "date_of_birth": "1988-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True},
                     {"full_name": "Child V1", "date_of_birth": "2016-05-20",
                      "relationship": "CHILD", "work_eligible": False},
                     {"full_name": "Child V2", "date_of_birth": "2014-03-10",
                      "relationship": "CHILD", "work_eligible": False}])

    def test_partial_school_age_set_rejected(self, api):
        """PRD §3.4: "For a `SCHOOL_ENROLLMENT` benchmark there is one
        further eligibility gate: `enrolled_member_ids` must equal exactly
        the set of the case's members with `school_age_at_arrival` true — no
        missing school-age child and no extra member — else
        `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/validations/school_fulfillment_wrong_member_set_returns_not_eligible
        """
        ctx = self._case_with_two_school_age_children()
        child1 = ctx["members"][1]
        note = make_service_delivery_note(ctx["case"]["id"],
                                          body="School enrollment",
                                          service_date="2026-08-15")
        set_clock("2026-08-20T00:00:00Z")
        bm = get_benchmark_by_type(ctx["case"]["id"], "SCHOOL_ENROLLMENT")
        resp = api.fulfill_benchmark(
            bm["id"], {"fulfilled_on": "2026-08-15", "evidence_note_id": note["id"],
                       "enrolled_member_ids": [child1["id"]]}, CM)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE)

    def test_full_school_age_set_fulfills(self, api):
        """PRD §3.4: "`enrolled_member_ids` must equal exactly the set of the
        case's members with `school_age_at_arrival` true — no missing
        school-age child and no extra member — else `ERR_MEMBER_NOT_ELIGIBLE`
        (HTTP 422). A successful fulfillment moves the benchmark `PENDING →
        MET`, stores `fulfilled_on` and `evidence_note_id` from the request,
        and sets `on_time` by comparing `fulfilled_on` against the
        actual-basis `due_date`".

        Design: Corner/validations/school_fulfillment_wrong_member_set_returns_not_eligible
        """
        ctx = self._case_with_two_school_age_children()
        child1, child2 = ctx["members"][1], ctx["members"][2]
        note = make_service_delivery_note(ctx["case"]["id"],
                                          body="School enrollment",
                                          service_date="2026-08-15")
        set_clock("2026-08-20T00:00:00Z")
        bm = get_benchmark_by_type(ctx["case"]["id"], "SCHOOL_ENROLLMENT")
        fulfilled = fulfill_benchmark(
            bm["id"], "2026-08-15", note["id"],
            enrolled_member_ids=[child1["id"], child2["id"]])
        assert fulfilled["status"] == "MET"
        assert fulfilled["on_time"] is True


class TestBenchmarkPartitionConservation:
    def _seven_benchmark_case(self):
        ctx = setup_arrived_case(
            case_number="CASE-CI2", household_size=2,
            members=[{"full_name": "Adult I", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True},
                     {"full_name": "Child I", "date_of_birth": "2016-05-20",
                      "relationship": "CHILD", "work_eligible": False}])
        note = make_service_delivery_note(ctx["case"]["id"],
                                          body="Home visit done",
                                          service_date="2026-08-15")
        set_clock("2026-08-20T00:00:00Z")
        return ctx, note

    def test_fulfill_moves_one_from_pending_to_met(self, api):
        """PRD §3.3: "Every benchmark is stored with two due dates computed
        at seeding time from its `due_rule`" and "Each seeded benchmark
        starts `PENDING` with `fulfilled_on`, `evidence_note_id`, `on_time`,
        and `waived_reason` all null." PRD §3.4: "A successful fulfillment
        moves the benchmark `PENDING → MET`, stores `fulfilled_on` and
        `evidence_note_id` from the request".

        Design: Difficulty/compensating_invariant/benchmark_status_count_conservation
        """
        ctx, note = self._seven_benchmark_case()
        case_id = ctx["case"]["id"]
        before = assert_benchmark_partition(list_case_benchmarks(case_id, headers=CM), 7)
        assert before == {"PENDING": 7, "MET": 0, "WAIVED": 0}
        bm = get_benchmark_by_type(case_id, "HOME_VISIT")
        fulfilled = fulfill_benchmark(bm["id"], "2026-08-15", note["id"])
        assert fulfilled["status"] == "MET"
        after = assert_benchmark_partition(list_case_benchmarks(case_id, headers=CM), 7)
        assert after == {"PENDING": 6, "MET": 1, "WAIVED": 0}

    def test_rescind_restores_pending_and_clears_fields(self, api):
        """PRD §3.4: "And a `MET` benchmark may be rescinded back to
        `PENDING` by a `CaseManager` when the documentation was wrong —
        rescinding clears `fulfilled_on`, `evidence_note_id`, and `on_time`
        back to null."

        Design: Difficulty/compensating_invariant/benchmark_status_count_conservation
        """
        ctx, note = self._seven_benchmark_case()
        case_id = ctx["case"]["id"]
        bm = get_benchmark_by_type(case_id, "HOME_VISIT")
        fulfill_benchmark(bm["id"], "2026-08-15", note["id"])
        rescinded = rescind_benchmark(bm["id"])
        assert rescinded["status"] == "PENDING"
        assert rescinded["fulfilled_on"] is None
        assert rescinded["evidence_note_id"] is None
        assert rescinded["on_time"] is None
        restored = assert_benchmark_partition(list_case_benchmarks(case_id, headers=CM), 7)
        assert restored == {"PENDING": 7, "MET": 0, "WAIVED": 0}


class TestWaiveAndRescindRoundTrip:
    def test_waive_records_reason(self, api):
        """PRD §3.4: "A benchmark in `PENDING` may be waived by an
        `AgencyDirector` supplying a `reason`, which is stored in
        `waived_reason`; manual waiver requires the case to have no open
        transfer."

        Design: Difficulty/compensating_invariant/benchmark_status_count_conservation
        """
        ctx = setup_arrived_case(case_number="CASE-BM-W1", household_size=1)
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT", headers=AD)
        waived = waive_benchmark(bm["id"], reason="Service delivered by another affiliate")
        assert waived["status"] == "WAIVED"
        assert waived["waived_reason"] == "Service delivered by another affiliate"
        assert_service_benchmark(waived)
