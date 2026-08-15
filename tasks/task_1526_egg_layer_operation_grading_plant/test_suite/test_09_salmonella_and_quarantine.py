"""Salmonella sampling cadence, quarantine gates, and result-recording SoD."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_collected_salmonella_test,
    record_test_result,
    salmonella_test_payload,
    set_clock,
    setup_confirmed_lot,
    setup_laying_flock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    GRADER,
    QA_MANAGER,
    get_flock,
    get_lot,
    get_salmonella_test,
)


class TestSamplingCadence:
    def _setup_collected_and_pending(self, api):
        """LAYING flock; T1 (ENVIRONMENTAL, scheduled 2026-08-01) collected at
        the startup clock; T2 (EGG_POOL, scheduled 2026-08-05) pending."""
        ctx = setup_laying_flock()
        t1 = create_collected_salmonella_test(
            ctx["flock"]["id"], scheduled_date="2026-08-01"
        )
        t2 = validate_success(
            api.create_salmonella_test(
                salmonella_test_payload(
                    ctx["flock"]["id"], test_type="EGG_POOL",
                    scheduled_date="2026-08-05",
                ),
                GRADER,
            ),
            201,
        )
        return ctx, t1, t2

    def test_second_collection_within_7_days_rejected(self, api):
        """PRD §3.7: "the gap between this collection and the most recent test
        on that house that reached `COLLECTED` or beyond must be no less than
        7 days — exactly 7 days is allowed — else `ERR_SAMPLING_TOO_SOON`
        (HTTP 409)."

        Design: Corner/validations/second_collection_within_7_days_rejected
        """
        ctx, _t1, t2 = self._setup_collected_and_pending(api)
        set_clock("2026-08-05T00:00:00Z")  # 4 days after the 2026-08-01 collection
        resp = api.collect_salmonella_test(t2["id"], GRADER)
        validate_error(resp, ApiErrorId.ERR_SAMPLING_TOO_SOON)
        assert get_salmonella_test(t2["id"])["status"] == "SCHEDULED"

    def test_collection_exactly_7_days_after_succeeds(self, api):
        """PRD §3.7: "the gap between this collection and the most recent test
        on that house that reached `COLLECTED` or beyond must be no less than
        7 days — exactly 7 days is allowed — else `ERR_SAMPLING_TOO_SOON`
        (HTTP 409)."
        PRD §3.7: "Collecting stamps `collected_date` to the clock date and
        `collected_by` to the caller's `X-User-ID`, and increments the test's
        `version` by 1."

        Design: Corner/validations/second_collection_within_7_days_rejected
        """
        ctx, _t1, t2 = self._setup_collected_and_pending(api)
        set_clock("2026-08-08T00:00:00Z")  # exactly 7 days after 2026-08-01
        collected = validate_success(api.collect_salmonella_test(t2["id"], GRADER))
        assert collected["status"] == "COLLECTED"
        assert collected["collected_date"][:10] == "2026-08-08"


class TestQuarantineGates:
    def test_clear_hold_blocked_while_flock_quarantined(self, api):
        """PRD §3.7: "While a flock is `QUARANTINED`, lot release, manual
        clear-hold, and induce-molt are all refused with
        `ERR_UNRESOLVED_POSITIVE` (HTTP 409)."
        PRD §3.7: "Link two places every egg lot of that flock whose lifecycle
        is `FRESH`, `RELEASED`, or `ALLOCATED` and whose hold is `CLEAR` into
        `HELD`"

        Design: Corner/validations/clear_hold_blocked_while_flock_quarantined
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        test = create_collected_salmonella_test(ctx["flock"]["id"])
        resulted = record_test_result(test["id"], "POSITIVE")
        assert resulted["result"] == "POSITIVE"

        lot = get_lot(lot_id)
        assert lot["hold_status"] == "HELD", "the positive cascade holds the lot"
        assert get_flock(ctx["flock"]["id"])["quarantine_status"] == "QUARANTINED"

        resp = api.clear_hold_lot(lot_id, QA_MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_POSITIVE)
        assert get_lot(lot_id)["hold_status"] == "HELD", (
            "quarantine holds are system-owned and cannot be cleared by hand"
        )


class TestResultRecordingSoD:
    def test_sod_test_result_same_collector_rejected(self, api):
        """PRD §3.7: "Segregation of duties applies: the recorder's
        `X-User-ID` must differ from `collected_by`, else `ERR_SOD_VIOLATION`
        (HTTP 403)."
        PRD §2.1: "the operator recording a salmonella result must not be the
        operator recorded in that test's `collected_by`."

        Design: Corner/rbac/sod_test_result_same_collector_rejected
        """
        ctx = setup_laying_flock()
        collector = build_user_headers("grader-9", "QualityGrader")
        test = create_collected_salmonella_test(
            ctx["flock"]["id"], collector_headers=collector
        )
        assert test["collected_by"] == "grader-9"

        same_operator_as_qa = build_user_headers("grader-9", "QAManager")
        resp = api.record_salmonella_result(
            test["id"], {"result": "NEGATIVE"}, same_operator_as_qa
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = get_salmonella_test(test["id"])
        assert after["status"] == "COLLECTED"
        assert after["result"] is None
