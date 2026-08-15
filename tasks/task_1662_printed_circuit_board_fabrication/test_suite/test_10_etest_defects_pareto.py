"""Electrical test runs, defect records, and the defect Pareto (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_defect_record, assert_same_instant,
    setup_in_production, setup_awaiting_etest, create_and_pass_etest,
    create_defect_payload,
    pareto_row_field,
    TEST_USERS,
)

QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ENG = TEST_USERS["process_engineer_headers"]


class TestEtestRuns:
    def test_etest_fail_keeps_order_awaiting(self, api):
        """PRD §3.8: "An outcome of `FAIL` lands the run in `COMPLETED_FAIL` and
        leaves the order in `AWAITING_ETEST`, free to schedule a fresh run."

        Design: Corner/state_machines/etest_fail_keeps_order_awaiting
        """
        ctx = setup_awaiting_etest(
            company_name="Etest Co", contact_email="etest@co.example",
            lot_code="LOT-ET1",
        )
        assert ctx["order"]["fab_status"] == "AWAITING_ETEST"

        run = get_success_data(
            api.create_etest_run(
                ctx["order"]["id"], {"fixture_id": "FX-1", "test_voltage": 250}, QI,
            )
        )
        get_success_data(api.start_etest_run(run["id"], QI))
        run = get_success_data(
            api.complete_etest_run(
                run["id"],
                {"outcome": "FAIL", "boards_tested": 100, "boards_failed": 2,
                 "opens_found": 1, "shorts_found": 1},
                QI,
            )
        )
        assert run["status"] == "COMPLETED_FAIL"
        assert run["boards_failed"] == 2

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "AWAITING_ETEST", (
            f"a FAIL run must not complete the order, got {order['fab_status']}"
        )

        # A fresh run can be scheduled on the still-awaiting order.
        run2 = get_success_data(
            api.create_etest_run(
                ctx["order"]["id"], {"fixture_id": "FX-2", "test_voltage": 250}, QI,
            )
        )
        assert run2["status"] == "SCHEDULED"

    def test_etest_pass_with_failure_counters_rejected(self, api):
        """PRD §3.8: "an outcome of `PASS` is accepted only when `boards_failed`,
        `opens_found`, and `shorts_found` are all zero — a passing verdict
        accompanied by nonzero failure counters is contradictory and rejected
        with `ERR_VALIDATION`".

        Design: Corner/validations/etest_pass_with_failures_rejected
        """
        ctx = setup_awaiting_etest(
            company_name="ETV Co", contact_email="etv@co.example",
            lot_code="LOT-EV1",
        )
        run = get_success_data(
            api.create_etest_run(
                ctx["order"]["id"], {"fixture_id": "FX-1", "test_voltage": 250}, QI,
            )
        )
        get_success_data(api.start_etest_run(run["id"], QI))
        resp = api.complete_etest_run(
            run["id"],
            {"outcome": "PASS", "boards_tested": 100, "boards_failed": 1,
             "opens_found": 0, "shorts_found": 0},
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "AWAITING_ETEST"
        # The contradictory completion must not move the run out of RUNNING.
        runs, meta = validate_paginated(api.list_etest_runs(ctx["order"]["id"], QI))
        assert runs[0]["status"] == "RUNNING"


class TestDefectRecords:
    def test_defect_record_retrieval_immutable(self, api):
        """PRD §3.8: "Defects observed anywhere in the build are logged by a
        `QualityInspector` as `DefectRecord` rows against the order". PRD §2.4:
        "a `CouponMeasurement` and a `DefectRecord` are append-only records that
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent from them."

        Design: Corner/entities/defect_record_retrieval_immutable
        """
        ctx = setup_in_production(
            company_name="Def Co", contact_email="def@co.example",
            lot_code="LOT-D1",
        )
        record = get_success_data(
            api.create_defect(
                ctx["order"]["id"],
                create_defect_payload(
                    ctx["array"]["id"], defect_code="OPEN", severity="MAJOR",
                    boards_affected=3, detected_at="2026-08-01T09:00:00Z",
                    source="AOI",
                ),
                QI,
            )
        )
        assert_defect_record(record)
        assert record["defect_code"] == "OPEN"
        assert record["severity"] == "MAJOR"
        assert record["boards_affected"] == 3

        data, meta = validate_paginated(
            api.list_order_defects(ctx["order"]["id"], QI)
        )
        assert meta["total_count"] == 1
        listed = data[0]
        assert listed["id"] == record["id"]
        assert_defect_record(listed)


class TestDefectPareto:
    def test_pareto_ordering_tiebreak_and_vital_few(self, api):
        """PRD §3.8: "Boards are aggregated per `defect_code` as the sum of
        `boards_affected`; rows are ordered by boards descending with ties
        broken by `defect_code` ascending in lexicographic order — never by
        record id. ... Each row carries its defect code, its boards total, its
        percentage share — one hundred times the row's boards divided by
        `total_boards`, rounded half-up to two decimal places — a running
        cumulative percentage computed from the unrounded board fractions of
        the rows so far and only then rounded half-up to two decimal places,
        and a vital-few flag that marks every row up to and including the first
        row at which the cumulative share reaches or crosses eighty percent (a
        row belongs to the vital few when the cumulative percentage before it
        is still below eighty)." and "The population is every `DefectRecord`
        whose `detected_at` falls inside the window and whose `severity` is
        `MAJOR` or `SCRAP`"; the window is "half-open ... from `from_iso`
        (inclusive) to `to_iso` (exclusive)".

        Design: Corner/calculations/defect_pareto_ordering_tiebreak_vitalfew
        """
        ctx = setup_in_production(
            company_name="Pareto Co", contact_email="pareto@co.example",
            lot_code="LOT-PA1",
        )
        order_id, array_id = ctx["order"]["id"], ctx["array"]["id"]

        def log(code, severity, boards, detected_at, source="AOI"):
            get_success_data(
                api.create_defect(
                    order_id,
                    create_defect_payload(
                        array_id, defect_code=code, severity=severity,
                        boards_affected=boards, detected_at=detected_at,
                        source=source,
                    ),
                    QI,
                )
            )

        log("OPEN", "MAJOR", 12, "2026-08-01T00:00:00Z")          # at from_iso: included
        log("SHORT", "MAJOR", 8, "2026-08-01T10:00:00Z")
        log("DRILL_BREAKOUT", "SCRAP", 8, "2026-08-01T11:00:00Z", source="MANUAL")
        log("SPACING", "MAJOR", 4, "2026-08-01T12:00:00Z")
        log("OVERETCH", "COSMETIC", 99, "2026-08-01T13:00:00Z")   # severity excluded
        log("SHORT", "MAJOR", 5, "2026-08-02T00:00:00Z", source="ETEST")  # at to_iso: excluded

        resp = api.get_defect_pareto(
            QI, params={"from_iso": "2026-08-01T00:00:00Z",
                        "to_iso": "2026-08-02T00:00:00Z"},
        )
        data = validate_success(resp, expected_status=200)
        # PRD §3.8 pins the window instants ("The response reports the
        # window_start, the window_end"), not their string serialization.
        assert_same_instant(data["window_start"], "2026-08-01T00:00:00Z")
        assert_same_instant(data["window_end"], "2026-08-02T00:00:00Z")
        assert data["total_boards"] == 32, (
            f"COSMETIC and to_iso-boundary records excluded: 12+8+8+4 = 32, "
            f"got {data['total_boards']}"
        )

        rows = data["rows"]
        assert len(rows) == 4

        expected = [
            ("OPEN", 12, 37.50, 37.50, True),
            ("DRILL_BREAKOUT", 8, 25.00, 62.50, True),   # tie 8: code ASC, D < S
            ("SHORT", 8, 25.00, 87.50, True),            # 62.50 < 80 at row entry
            ("SPACING", 4, 12.50, 100.00, False),        # 87.50 >= 80 at row entry
        ]
        for row, (code, boards, pct, cumulative, vital) in zip(rows, expected):
            assert pareto_row_field(row, "defect_code", "code") == code
            assert pareto_row_field(row, "boards", "boards_affected", "boards_total") == boards
            assert pareto_row_field(row, "pct", "percentage", "pct_share") == pytest.approx(pct, abs=1e-9)
            assert pareto_row_field(row, "cumulative", "cumulative_pct", "cumulative_percentage") == pytest.approx(cumulative, abs=1e-9)
            assert pareto_row_field(row, "vital_few", "is_vital_few", "vital") == vital

    def test_pareto_empty_window(self, api):
        """PRD §3.8: "An empty population yields empty `rows` and a
        `total_boards` of zero." and "The response reports the `window_start`,
        the `window_end`, the `total_boards` summed over all included codes,
        and the ordered `rows`."

        Design: Corner/calculations/defect_pareto_empty_window
        """
        resp = api.get_defect_pareto(
            ENG, params={"from_iso": "2027-01-01T00:00:00Z",
                         "to_iso": "2027-01-02T00:00:00Z"},
        )
        data = validate_success(resp, expected_status=200)
        assert data["rows"] == []
        assert data["total_boards"] == 0
        assert_same_instant(data["window_start"], "2027-01-01T00:00:00Z")
        assert_same_instant(data["window_end"], "2027-01-02T00:00:00Z")
