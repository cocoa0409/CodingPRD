"""Apprentice program: readiness variants, running average, exam (PRD §3.10)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_apprentice,
    make_apprentice_payload, make_record_progress_payload,
    create_main_tariff, register_endorsed_pilot, register_boat,
    place_order, make_dispatch_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def _enroll(api, track="STANDARD", full_name="App X"):
    return validate_success(
        api.create_apprentice(make_apprentice_payload(full_name=full_name, track=track),
                              ADMIN), 201)


def _log(api, apprentice_id, trips_delta, evaluation_score):
    return validate_success(api.record_apprentice_progress(
        apprentice_id, make_record_progress_payload(trips_delta, evaluation_score),
        ADMIN), 200)


class TestReadinessVariants:
    def test_standard_track_45_trips_readiness_not_met(self, api):
        """PRD §3.10: "a `STANDARD` apprentice qualifies on trips alone,
        needing at least 50 completed trips". "Failing the variant rejects
        advancement with `ERR_READINESS_NOT_MET`."

        45 trips and a 90-point evaluation average: one trip short under
        STANDARD, and the high average cannot compensate.

        Design: Difficulty/dual_variant_calc/apprentice_readiness_standard_vs_accelerated
        """
        sa = _enroll(api, track="STANDARD", full_name="App Standard")
        _log(api, sa["id"], 45, 90)

        res = api.advance_apprentice(sa["id"], {}, ADMIN)
        validate_error(res, ApiErrorId.ERR_READINESS_NOT_MET)

        data, _meta = validate_paginated(api.list_apprentices(ADMIN))
        refreshed = [a for a in data if a["id"] == sa["id"]][0]
        assert refreshed["status"] == "ENROLLED", "rejected advance changes nothing"

    def test_accelerated_track_45_trips_90_avg_qualifies(self, api):
        """PRD §3.10: "an `ACCELERATED` apprentice faces a blended bar — at
        least 40 trips and an `evaluation_avg` of at least 85 — so identical
        trip and evaluation data can yield opposite verdicts across tracks."

        The same 45 trips / 90 average that fails STANDARD satisfies the
        ACCELERATED bar.

        Design: Difficulty/dual_variant_calc/apprentice_readiness_standard_vs_accelerated
        """
        sb = _enroll(api, track="ACCELERATED", full_name="App Accelerated")
        _log(api, sb["id"], 45, 90)

        advanced = validate_success(api.advance_apprentice(sb["id"], {}, ADMIN), 200)
        assert advanced["status"] == "QUALIFIED"


class TestRunningAverage:
    def test_calc_apprentice_running_average_and_counts(self, api):
        """PRD §3.10: "the prior average times the prior count, plus the new
        score, divided by the new count, rounded half-up to two decimal places
        — then `evaluations_count` increments."

        Scores 80 then 90 over two records: (80 x 1 + 90) / 2 = 85.00; trips
        accumulate 10 + 15 = 25.

        Design: Corner/calculations/calc_apprentice_running_average_and_counts
        """
        ax = _enroll(api)
        _log(api, ax["id"], 10, 80)
        after = _log(api, ax["id"], 15, 90)
        assert_apprentice(after)
        assert after["evaluation_avg"] == pytest.approx(85.0, abs=0.001)
        assert after["trips_completed"] == 25
        assert after["evaluations_count"] == 2


class TestExamGate:
    def test_error_exam_not_passed_then_certified(self, api):
        """PRD §3.10: "From `QUALIFIED` to `CERTIFIED`, the admin supplies
        `exam_result`, and only the value `PASS` advances the apprentice;
        anything else (or its absence) is rejected with `ERR_EXAM_NOT_PASSED`."

        Design: Corner/errors/error_exam_not_passed_then_certified
        """
        ax = _enroll(api)
        _log(api, ax["id"], 50, 70)
        qualified = validate_success(api.advance_apprentice(ax["id"], {}, ADMIN), 200)
        assert qualified["status"] == "QUALIFIED"

        res = api.advance_apprentice(ax["id"], {"exam_result": "FAIL"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_EXAM_NOT_PASSED)

        certified = validate_success(
            api.advance_apprentice(ax["id"], {"exam_result": "PASS"}, ADMIN), 200)
        assert certified["status"] == "CERTIFIED"


class TestDispatchApprenticeGate:
    def test_error_apprentice_not_enrolled_on_dispatch(self, api):
        """PRD §3.3: "When an `apprentice_id` is supplied, it must reference an
        apprentice whose `status` is `ENROLLED` — dispatching against a
        `QUALIFIED` or `CERTIFIED` apprentice is rejected with
        `ERR_APPRENTICE_NOT_ENROLLED`."

        The nominated apprentice has already advanced to QUALIFIED.

        Design: Corner/errors/error_apprentice_not_enrolled_on_dispatch
        """
        ax = _enroll(api)
        _log(api, ax["id"], 50, 70)
        validate_success(api.advance_apprentice(ax["id"], {}, ADMIN), 200)

        create_main_tariff()
        register_endorsed_pilot()
        register_boat("Boat A")
        order = place_order()

        res = api.dispatch_order(order["id"], make_dispatch_payload(
            "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
            apprentice_id=ax["id"]), TEST_USERS["dispatcher_headers"])
        validate_error(res, ApiErrorId.ERR_APPRENTICE_NOT_ENROLLED)
