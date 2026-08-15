"""Stability enrollment, aggregate chamber capacity, pull evaluation, expiry."""
from test_helpers import (
    TEST_USERS,
    WINDOW_DAY1,
    WINDOW_DAY2,
    WINDOW_DAY3,
    ApiErrorId,
    complete_study,
    enroll_study,
    get_batch,
    get_stability_chamber,
    make_catalog,
    run_batch,
    validate_error,
    validate_success,
)

CHEMIST = TEST_USERS["qa_chemist_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _completed_batch_with_chamber(clock="2026-08-01T00:00:00Z", capacity=50000):
    ctx = make_catalog(clock=clock, chamber_capacity=capacity)
    ctx.update(run_batch(ctx, window=WINDOW_DAY1, stage="COMPLETED"))
    return ctx


class TestChamberAggregateCapacity:
    def _three_completed_batches(self):
        ctx = make_catalog(clock="2026-08-01T00:00:00Z", lot_qty=50000000,
                           chamber_capacity=20000)
        r1 = run_batch(ctx, window=WINDOW_DAY1, stage="COMPLETED")
        r2 = run_batch(ctx, window=WINDOW_DAY2, stage="COMPLETED")
        r3 = run_batch(ctx, window=WINDOW_DAY3, stage="COMPLETED")
        return ctx, r1, r2, r3

    def test_chamber_capacity_exact_equality_allowed(self, api):
        """PRD §3.7: "Aggregate capacity is enforced at enrollment: the chamber's
        `occupied_units` plus the batch's `theoretical_units` must not exceed
        `capacity_units`, with exact equality allowed; an overflow is rejected with
        `ERR_CHAMBER_CAPACITY_EXCEEDED`."
        PRD §3.7: "A successful enrollment creates the study in `ENROLLED` status
        and raises the chamber's `occupied_units` by the batch's
        `theoretical_units`".

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity
        """
        ctx, r1, r2, _r3 = self._three_completed_batches()
        ch_id = ctx["chamber"]["id"]

        s1 = enroll_study(r1["batch"]["id"], ch_id)
        assert s1["status"] == "ENROLLED"
        assert get_stability_chamber(ch_id)["occupied_units"] == 10000

        s2 = enroll_study(r2["batch"]["id"], ch_id)
        assert s2["status"] == "ENROLLED"
        # 10000 + 10000 == 20000 capacity exactly: allowed.
        assert get_stability_chamber(ch_id)["occupied_units"] == 20000

    def test_chamber_capacity_overflow_rejected(self, api):
        """PRD §3.7: "the chamber's `occupied_units` plus the batch's
        `theoretical_units` must not exceed `capacity_units`, with exact equality
        allowed; an overflow is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity
        """
        ctx, r1, r2, r3 = self._three_completed_batches()
        ch_id = ctx["chamber"]["id"]
        enroll_study(r1["batch"]["id"], ch_id)
        enroll_study(r2["batch"]["id"], ch_id)
        assert get_stability_chamber(ch_id)["occupied_units"] == 20000

        resp = api.enroll_stability_study(
            r3["batch"]["id"], {"chamber_id": ch_id, "protocol": "REAL_TIME"}, CHEMIST
        )
        validate_error(resp, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED)
        assert resp.status_code == 409
        assert get_stability_chamber(ch_id)["occupied_units"] == 20000, (
            "a rejected enrollment must not raise chamber occupancy"
        )


class TestStudyEnrollmentRules:
    def test_second_enrolled_study_per_batch_rejected(self, api):
        """PRD §3.7: "a batch that already has an `ENROLLED` study is rejected with
        `ERR_STUDY_STATE` — at most one study per batch may be in flight."

        Design: Corner/state_machines/study_enroll_second_active_rejected
        """
        ctx = _completed_batch_with_chamber()
        enroll_study(ctx["batch"]["id"], ctx["chamber"]["id"])

        resp = api.enroll_stability_study(
            ctx["batch"]["id"],
            {"chamber_id": ctx["chamber"]["id"], "protocol": "ACCELERATED"},
            CHEMIST,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_STATE)
        assert resp.status_code == 409


class TestStudyCompletion:
    def test_occupied_units_reconcile_on_enroll_and_complete(self, api):
        """PRD §3.7: "A successful enrollment creates the study in `ENROLLED` status
        and raises the chamber's `occupied_units` by the batch's
        `theoretical_units`" and "Completion moves the study to `COMPLETED`,
        mirrors `assigned_expiry_date` onto the batch's `expiry_date`, and lowers
        the chamber's `occupied_units` by the batch's `theoretical_units`."

        Design: Corner/cross_cutting_layers/chamber_occupied_units_reconcile_on_enroll_and_complete
        """
        ctx = _completed_batch_with_chamber()
        ch_id = ctx["chamber"]["id"]
        assert get_stability_chamber(ch_id)["occupied_units"] == 0

        study = enroll_study(ctx["batch"]["id"], ch_id)
        assert get_stability_chamber(ch_id)["occupied_units"] == 10000

        complete_study(study["id"], [{"pull_month": 3, "passed": True}])
        assert get_stability_chamber(ch_id)["occupied_units"] == 0

    def test_study_complete_twice_rejected(self, api):
        """PRD §3.7: "Completion is a `QAManager` action on a study still `ENROLLED`
        (`ERR_STUDY_STATE` otherwise)".

        Design: Corner/state_machines/study_complete_twice_rejected
        """
        ctx = _completed_batch_with_chamber()
        study = enroll_study(ctx["batch"]["id"], ctx["chamber"]["id"])
        complete_study(study["id"], [{"pull_month": 3, "passed": True}])
        assert get_stability_chamber(ctx["chamber"]["id"])["occupied_units"] == 0

        resp = api.complete_stability_study(
            study["id"], {"pull_results": [{"pull_month": 6, "passed": True}]}, QA
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_STATE)
        assert resp.status_code == 409
        assert get_stability_chamber(ctx["chamber"]["id"])["occupied_units"] == 0, (
            "the rejected second completion must not double-decrement occupancy"
        )


class TestExpiryAssignment:
    def test_expiry_end_of_month_rounding_nonleap_february(self, api):
        """PRD §3.7: "End-of-month rounding is pinned — a batch completed on
        2026-08-14 with three effective months expires 2026-11-30, and one completed
        on 2026-11-20 with three effective months expires 2027-02-28 in the non-leap
        year 2027."
        PRD §3.7: "the supported figure is the greatest `pull_month` strictly before
        that failure — zero when the earliest pull failed, or the final `pull_month`
        when none failed."

        Design: Corner/calculations/expiry_end_of_month_rounding_feb_nonleap
        """
        ctx = _completed_batch_with_chamber(clock="2026-11-20T00:00:00Z")
        study = enroll_study(ctx["batch"]["id"], ctx["chamber"]["id"])

        resp = api.complete_stability_study(
            study["id"],
            {"pull_results": [{"pull_month": 3, "passed": True}]},
            QA,
        )
        completed = validate_success(resp, 200)
        assert completed["status"] == "COMPLETED"
        assert completed["supported_months"] == 3
        # completed month 2026-11 + min(24, 3) months -> 2027-02; last day 2027-02-28.
        assert completed["assigned_expiry_date"] == "2027-02-28"
        assert get_batch(ctx["batch"]["id"])["expiry_date"] == "2027-02-28", (
            "the assigned expiry must be mirrored onto the batch"
        )

    def test_first_pull_failed_gives_zero_supported_months(self, api):
        """PRD §3.7: "The system then determines `supported_months` by scanning the
        pulls in ascending order and stopping at the first failed pull: the
        supported figure is the greatest `pull_month` strictly before that failure —
        zero when the earliest pull failed, or the final `pull_month` when none
        failed."
        PRD §3.7: "the effective shelf life is the smaller of the formula's
        `shelf_life_months` and the study's `supported_months`; that many months are
        added to the calendar month containing the batch's `completed_at`; and
        `assigned_expiry_date` is the last calendar day of the resulting month."

        Design: Corner/calculations/expiry_first_pull_failed_gives_zero_supported
        """
        ctx = _completed_batch_with_chamber(clock="2026-11-20T00:00:00Z")
        study = enroll_study(ctx["batch"]["id"], ctx["chamber"]["id"])

        resp = api.complete_stability_study(
            study["id"],
            {"pull_results": [
                {"pull_month": 3, "passed": False},
                {"pull_month": 6, "passed": True},
            ]},
            QA,
        )
        completed = validate_success(resp, 200)
        assert completed["supported_months"] == 0, (
            "a failed earliest pull truncates support to zero regardless of later passes"
        )
        # completed month 2026-11 + 0 months -> last calendar day of 2026-11.
        assert completed["assigned_expiry_date"] == "2026-11-30"
