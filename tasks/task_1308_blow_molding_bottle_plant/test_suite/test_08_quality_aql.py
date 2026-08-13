"""Quality test lots: AQL band boundaries, inclusive accept boundary, reject-rework-retest loop, QC-reject cascade, and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_closed_run_scenario, setup_running_scenario,
    close_run, get_qtl_id_for_run, sample_lot, record_results,
    disposition_lot, get_order, get_order_summary, list_order_slots,
    close_production_run_payload, start_run,
    make_quality_technician_headers,
    api_client, ApiErrorId, TEST_USERS,
)

ENGINEER = TEST_USERS["process_engineer"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]


class TestAqlAcceptBoundary:
    def _setup_two_sampled_lots(self, api):
        """One RUNNING order with two closed runs of good_count 960 each (band 281..1200: n=50, c_leak=2, c_drop=2); both lots SAMPLED."""
        ctx = setup_running_scenario(order_overrides={"quantity_ordered": 2000})
        run1 = close_run(ctx["run"]["id"], cycles_completed=130, good_count=960,
                         scrap_count=40, actual_drawdown_kg=23.0)
        run2 = start_run(ctx["order"]["id"], ctx["line"]["id"],
                         ctx["mold"]["id"], ctx["lot"]["id"])
        run2 = close_run(run2["id"], cycles_completed=130, good_count=960,
                         scrap_count=40, actual_drawdown_kg=23.0)
        qtl1 = get_qtl_id_for_run(run1["id"])
        qtl2 = get_qtl_id_for_run(run2["id"])
        sample_lot(qtl1, user_id="qt-1")
        sample_lot(qtl2, user_id="qt-1")
        ctx.update(run1=run1, run2=run2, qtl1=qtl1, qtl2=qtl2)
        return ctx

    def test_accept_at_exactly_accept_number(self, api):
        """PRD §3.7: "from 281 through 1200 units the sample is 50 with accept numbers 2 and 2". "The accept decision treats the two characteristics independently and accepts on an inclusive boundary: the lot becomes `ACCEPTED` when `leak_failures` is at most `accept_number_leak` and `drop_failures` is at most `accept_number_drop`, so failure counts exactly equal to the accept numbers still accept".

Design: Difficulty/boundary_precision_check/aql_accept_at_exactly_c_reject_at_c_plus_1"""
        ctx = self._setup_two_sampled_lots(api)
        lot1 = get_success_data(api.get_quality_test_lot(ctx["qtl1"], TECH))
        assert lot1["sample_size_n"] == 50
        assert lot1["accept_number_leak"] == 2
        assert lot1["accept_number_drop"] == 2

        res = api.record_quality_test_results(
            ctx["qtl1"], {"leak_failures": 2, "drop_failures": 2},
            TEST_USERS["quality_technician"])
        decided = validate_success(res, 200)
        # exactly at both accept numbers — inclusive boundary accepts
        assert decided["status"] == "ACCEPTED"

    def test_reject_one_above_accept_number(self, api):
        """PRD §3.7: "if either characteristic exceeds its accept number the lot becomes `REJECTED`."

Design: Difficulty/boundary_precision_check/aql_accept_at_exactly_c_reject_at_c_plus_1"""
        ctx = self._setup_two_sampled_lots(api)
        res = api.record_quality_test_results(
            ctx["qtl2"], {"leak_failures": 3, "drop_failures": 0},
            TEST_USERS["quality_technician"])
        decided = validate_success(res, 200)
        # leak 3 > c_leak 2 → one above the accept number rejects
        assert decided["status"] == "REJECTED"


class TestRejectReworkRetestCycle:
    def _setup_rejected_band4_lot(self, api):
        """Closed run with good_count 11880 (band >= 10001: n=200, c_leak=5, c_drop=6); lot SAMPLED by qt-1."""
        ctx = setup_closed_run_scenario()
        sample_lot(ctx["qtl_id"], user_id="qt-1")
        return ctx

    def test_reject_then_rework_loops_to_pending(self, api):
        """PRD §3.7: "Disposition with `action` `REWORK` instead returns the lot to `PENDING` for another pass: `retest_count` increments by one and the recorded `leak_failures`, `drop_failures`, and `recorded_by_user_id` are cleared to null, ready for fresh sampling."

Design: Difficulty/non_linear_state_machine/quality_lot_reject_rework_retest_cycle"""
        ctx = self._setup_rejected_band4_lot(api)
        rejected = record_results(ctx["qtl_id"], 6, 6, user_id="qt-1")
        assert rejected["status"] == "REJECTED"  # leak 6 > c_leak 5

        reworked = disposition_lot(ctx["qtl_id"], "REWORK", user_id="qt-2")
        assert reworked["status"] == "PENDING"
        assert reworked["retest_count"] == 1
        assert reworked["leak_failures"] is None
        assert reworked["drop_failures"] is None
        assert reworked["recorded_by_user_id"] is None

    def test_reworked_lot_retest_accepts_at_boundary(self, api):
        """PRD §3.7: "the lot becomes `ACCEPTED` when `leak_failures` is at most `accept_number_leak` and `drop_failures` is at most `accept_number_drop`, so failure counts exactly equal to the accept numbers still accept". "Acceptance recomputes the order's `quantity_accepted` and `quantity_open_qc`."

Design: Difficulty/non_linear_state_machine/quality_lot_reject_rework_retest_cycle"""
        ctx = self._setup_rejected_band4_lot(api)
        record_results(ctx["qtl_id"], 6, 6, user_id="qt-1")
        disposition_lot(ctx["qtl_id"], "REWORK", user_id="qt-2")
        sample_lot(ctx["qtl_id"], user_id="qt-2")
        decided = record_results(ctx["qtl_id"], 5, 6, user_id="qt-2")
        # 5 <= 5 and 6 <= 6 — inclusive boundary accepts on retest
        assert decided["status"] == "ACCEPTED"
        summary = get_order_summary(ctx["order"]["id"])
        assert summary["quantity_accepted"] == 11880


class TestQcRejectCascade:
    def _record_rejection(self, api):
        """RUNNING order on a RUNNING line with an IN_PROGRESS slot; record a rejecting result on the SAMPLED lot (leak 6 > c_leak 5)."""
        ctx = setup_closed_run_scenario()
        sample_lot(ctx["qtl_id"], user_id="qt-1")
        lot = record_results(ctx["qtl_id"], 6, 0, user_id="qt-1")
        assert lot["status"] == "REJECTED"
        return ctx

    def test_reject_holds_order(self, api):
        """PRD §3.7: "Rejection is louder: the order drops from `RUNNING` to `HELD` as a QC hold".

Design: Difficulty/transitive_cascade/qc_reject_cascade_holds_order_frees_line"""
        ctx = self._record_rejection(api)
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "HELD", (
            f"lot rejection must place the order on QC hold, got "
            f"{order['status']}")

    def test_reject_cancels_slot_and_rests_line(self, api):
        """PRD §3.7: "the order drops from `RUNNING` to `HELD` as a QC hold, which cascades exactly like a manual hold — the order's `CONFIRMED` and `IN_PROGRESS` slots are cancelled and the line falls from `RUNNING` to `CHANGEOVER`."

Design: Difficulty/transitive_cascade/qc_reject_cascade_holds_order_frees_line"""
        ctx = self._record_rejection(api)
        slots = list_order_slots(ctx["order"]["id"])
        assert len(slots) == 1
        assert slots[0]["status"] == "CANCELLED"
        line = get_success_data(api.get_machine_line(ctx["line"]["id"], ENGINEER))
        assert line["status"] == "CHANGEOVER"
        # the mold stays installed through the hold
        mold = get_success_data(api.get_mold(ctx["mold"]["id"], ENGINEER))
        assert mold["status"] == "INSTALLED"


class TestAqlBandBoundary:
    def test_band_edges_280_vs_281(self, api):
        """PRD §3.7: "a lot of 280 units or fewer draws a `sample_size_n` of 20 with an `accept_number_leak` of 1 and an `accept_number_drop` of 1; from 281 through 1200 units the sample is 50 with accept numbers 2 and 2".

Design: Corner/calculations/aql_band_boundary_280_vs_281"""
        ctx = setup_running_scenario(order_overrides={"quantity_ordered": 2000})
        run_a = close_run(ctx["run"]["id"], cycles_completed=36, good_count=280,
                          scrap_count=8, actual_drawdown_kg=6.4)
        run_b = start_run(ctx["order"]["id"], ctx["line"]["id"],
                          ctx["mold"]["id"], ctx["lot"]["id"])
        run_b = close_run(run_b["id"], cycles_completed=36, good_count=281,
                          scrap_count=7, actual_drawdown_kg=6.4)

        lot_a = get_success_data(api.get_quality_test_lot(
            get_qtl_id_for_run(run_a["id"]), TECH))
        assert lot_a["lot_size"] == 280
        assert lot_a["sample_size_n"] == 20       # band 1 upper edge, inclusive
        assert lot_a["accept_number_leak"] == 1
        assert lot_a["accept_number_drop"] == 1

        lot_b = get_success_data(api.get_quality_test_lot(
            get_qtl_id_for_run(run_b["id"]), TECH))
        assert lot_b["lot_size"] == 281
        assert lot_b["sample_size_n"] == 50       # band 2 lower edge, inclusive
        assert lot_b["accept_number_leak"] == 2
        assert lot_b["accept_number_drop"] == 2


class TestSegregationOfDuties:
    def test_disposition_by_recorder_rejected(self, api):
        """PRD §3.7: "segregation of duties applies: the dispositor's `X-User-ID` must differ from the lot's `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; whoever dispositions is remembered in `dispositioned_by_user_id`. Disposition with `action` `SCRAP` moves the lot to `SCRAPPED` and recomputes the order's `quantity_qc_scrapped`".

Design: Corner/rbac/sod_disposition_same_user_rejected"""
        ctx = setup_closed_run_scenario()
        sample_lot(ctx["qtl_id"], user_id="qt-1")
        rejected = record_results(ctx["qtl_id"], 6, 0, user_id="qt-1")
        assert rejected["status"] == "REJECTED"
        assert rejected["recorded_by_user_id"] == "qt-1"

        res = api.disposition_quality_test_lot(
            ctx["qtl_id"], {"action": "SCRAP"},
            make_quality_technician_headers("qt-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        scrapped = disposition_lot(ctx["qtl_id"], "SCRAP", user_id="qt-2")
        assert scrapped["status"] == "SCRAPPED"
        assert scrapped["dispositioned_by_user_id"] == "qt-2"
        summary = get_order_summary(ctx["order"]["id"])
        assert summary["quantity_qc_scrapped"] == 11880
