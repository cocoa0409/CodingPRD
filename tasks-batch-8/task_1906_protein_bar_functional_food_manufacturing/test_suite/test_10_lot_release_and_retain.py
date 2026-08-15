"""Completion, retain samples, and the lot-release decision gates: parallel
state axes, retain gate, yield gate, QC and segregation of duties
(PRD §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_2dp,
    fixtures,
    make_lab_technician_headers,
    make_quality_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


class TestParallelReleaseAxis:
    def test_completion_advances_both_axes_and_creates_lot_release(self, api):
        """PRD §3.6: "A successfully created run lands in `PLANNED` on its
        production axis and `NOT_READY` on its quality-disposition axis — the
        run carries two parallel state dimensions, `status` and
        `release_status`, and the release axis never mutates the production
        axis."
        PRD §3.8: "The run's `release_status` moves from `NOT_READY` to
        `PENDING_QC` on the quality axis"

        Design: Difficulty/non_linear_state_machine/production_run_parallel_release_axis
        """
        ns = fixtures.setup_completed_run(
            planned_cases=130, produced_cases=130, scrapped_cases=3
        )
        assert ns.run["status"] == "COMPLETED"
        assert ns.run["release_status"] == "PENDING_QC"
        # produced 130 <= expected 133 (slab 20 kg, batch 100 kg): completion
        # succeeds despite the scrapped cases.
        assert ns.release["qc_disposition"] == "PENDING"
        assert ns.release["decision"] == "PENDING"

    def test_release_axis_moves_without_touching_production_axis(self, api):
        """PRD §3.6: "the run carries two parallel state dimensions, `status`
        and `release_status`, and the release axis never mutates the
        production axis."
        PRD §3.8: "A decision of `HOLD_REWORK` from `PENDING` requires only
        the segregation-of-duties guard and moves the run's `release_status`
        to `HOLD_REWORK`"
        PRD §3.8: "When rework is abandoned, a `SCRAPPED` decision is also
        permitted directly from `HOLD_REWORK`, moving the run's
        `release_status` to `SCRAPPED` and incrementing both versions."

        Design: Difficulty/non_linear_state_machine/production_run_parallel_release_axis
        """
        ns = fixtures.setup_completed_run(
            planned_cases=130, produced_cases=130, scrapped_cases=3
        )
        fixtures.record_qc_passed(ns.release["id"])
        fixtures.register_retain_sample(ns.run["id"], cases_count=2)
        hold = validate_success(
            client.decide_lot_release(ns.release["id"], {"decision": "HOLD_REWORK"},
                                      make_quality_manager_headers("qm-001")),
            200,
        )
        assert hold["decision"] == "HOLD_REWORK"
        run = validate_success(client.get_production_run(ns.run["id"], QM), 200)
        assert run["release_status"] == "HOLD_REWORK"
        assert run["status"] == "COMPLETED"
        scrapped = validate_success(
            client.decide_lot_release(ns.release["id"], {"decision": "SCRAPPED"},
                                      make_quality_manager_headers("qm-001")),
            200,
        )
        assert scrapped["decision"] == "SCRAPPED"
        run = validate_success(client.get_production_run(ns.run["id"], QM), 200)
        assert run["release_status"] == "SCRAPPED"
        assert run["status"] == "COMPLETED"


class TestRetainSampleGate:
    def test_release_decision_requires_stored_retain_sample(self, api):
        """PRD §3.8: "A decision of `RELEASED` from `decision` `PENDING`
        enforces its four guards in order: the decider's `X-User-ID` must
        differ from `qc_recorded_by` (`ERR_SOD_VIOLATION`, HTTP 422);
        `retain_cases_stored` must be at least one
        (`ERR_RETAIN_SAMPLE_REQUIRED`, HTTP 422); the absolute value of
        `yield_variance_pct` must be no greater than 5.00 percent, with
        exactly 5.00 passing (`ERR_YIELD_VARIANCE_EXCEEDED`, HTTP 422); and
        `qc_disposition` must be `PASSED` (`ERR_QC_NOT_PASSED`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_stored_retain_sample
        """
        ns = fixtures.setup_completed_run(planned_cases=130, produced_cases=130)
        fixtures.record_qc_passed(ns.release["id"])
        # QC PASSED and variance 0.00, but no STORED retain sample yet.
        resp = client.decide_lot_release(
            ns.release["id"], {"decision": "RELEASED"},
            make_quality_manager_headers("qm-001"),
        )
        validate_error(resp, ApiErrorId.ERR_RETAIN_SAMPLE_REQUIRED, 422)

    def test_release_decision_succeeds_with_retain_and_rolls_up(self, api):
        """PRD §3.8: "Each registration recomputes the lot release's
        `retain_cases_stored`, the sum of `cases_count` over the run's stored
        samples."
        PRD §3.8: "A release decision moves the run's `release_status` to
        `RELEASED`, stamps `decided_by`, recomputes the agreement's
        `produced_cases_current_quarter` and `shortfall_cases` per §3.3"
        PRD §3.3: "The `shortfall_cases` is the committed volume minus that
        produced volume, floored at zero, so it can never report a negative
        shortfall."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_stored_retain_sample
        """
        ns = fixtures.setup_completed_run(planned_cases=130, produced_cases=130)
        fixtures.record_qc_passed(ns.release["id"])
        sample = fixtures.register_retain_sample(ns.run["id"], cases_count=2,
                                                 retain_until_utc="2026-09-15T00:00:00Z")
        assert sample["status"] == "STORED"
        decided = validate_success(
            client.decide_lot_release(ns.release["id"], {"decision": "RELEASED"},
                                      make_quality_manager_headers("qm-001")),
            200,
        )
        assert decided["decision"] == "RELEASED"
        assert decided["retain_cases_stored"] == 2
        run = validate_success(client.get_production_run(ns.run["id"], QM), 200)
        assert run["release_status"] == "RELEASED"
        agreement = validate_success(
            client.get_agreement(ns.plant.ag["id"], QM), 200
        )
        assert agreement["produced_cases_current_quarter"] == 130
        assert agreement["shortfall_cases"] == 170


class TestYieldVarianceGate:
    def test_variance_exactly_five_passes_and_six_fails(self, api):
        """PRD §3.8: "the absolute value of `yield_variance_pct` must be no
        greater than 5.00 percent, with exactly 5.00 passing
        (`ERR_YIELD_VARIANCE_EXCEEDED`, HTTP 422)"

        Design: Corner/calculations/c_yield_variance_boundary_and_excess
        """
        ns = fixtures.setup_yield_pair()
        # (105 - 100)/100 * 100 -> 5.00, inclusive boundary: release allowed.
        assert_2dp(ns.a.release["yield_variance_pct"], 5.00, "yield_variance_pct A")
        decided = validate_success(
            client.decide_lot_release(ns.a.release["id"], {"decision": "RELEASED"},
                                      make_quality_manager_headers("qm-001")),
            200,
        )
        assert decided["decision"] == "RELEASED"
        # (106 - 100)/100 * 100 -> 6.00 > 5.00: rejected, decision stays.
        assert_2dp(ns.b.release["yield_variance_pct"], 6.00, "yield_variance_pct B")
        resp = client.decide_lot_release(
            ns.b.release["id"], {"decision": "RELEASED"},
            make_quality_manager_headers("qm-001"),
        )
        validate_error(resp, ApiErrorId.ERR_YIELD_VARIANCE_EXCEEDED, 422)
        stayed = validate_success(client.get_lot_release(ns.b.release["id"], QM), 200)
        assert stayed["decision"] == "PENDING"


class TestLotReleaseGateSequence:
    def test_decide_gates_fire_in_order_then_release(self, api):
        """PRD §3.8: "A decision of `RELEASED` from `decision` `PENDING`
        enforces its four guards in order: the decider's `X-User-ID` must
        differ from `qc_recorded_by` (`ERR_SOD_VIOLATION`, HTTP 422);
        `retain_cases_stored` must be at least one
        (`ERR_RETAIN_SAMPLE_REQUIRED`, HTTP 422); the absolute value of
        `yield_variance_pct` must be no greater than 5.00 percent, with
        exactly 5.00 passing (`ERR_YIELD_VARIANCE_EXCEEDED`, HTTP 422); and
        `qc_disposition` must be `PASSED` (`ERR_QC_NOT_PASSED`, HTTP 422)."
        PRD §3.8: "The retain period must extend at least 30 days past the
        run's `completed_utc`; a shorter period is rejected with
        `ERR_RETAIN_PERIOD_TOO_SHORT` (HTTP 422)."

        Design: Corner/validations/c_lot_release_gate_sequence
        """
        ns = fixtures.setup_completed_run(planned_cases=130, produced_cases=130)
        release_id = ns.release["id"]
        # No STORED retain sample (QC still PENDING): retain gate fires.
        validate_error(
            client.decide_lot_release(release_id, {"decision": "RELEASED"},
                                      make_quality_manager_headers("qm-001")),
            ApiErrorId.ERR_RETAIN_SAMPLE_REQUIRED, 422,
        )
        # Retain until 2026-08-20 is earlier than completed 2026-08-06 + 30 days.
        validate_error(
            client.create_retain_sample(
                ns.run["id"],
                {"bin_id": "BIN-0", "cases_count": 1,
                 "retain_until_utc": "2026-08-20T00:00:00Z"},
                QM,
            ),
            ApiErrorId.ERR_RETAIN_PERIOD_TOO_SHORT, 422,
        )
        fixtures.register_retain_sample(ns.run["id"], bin_id="BIN-1",
                                        retain_until_utc="2026-09-15T00:00:00Z")
        # Retain satisfied but QC still PENDING.
        validate_error(
            client.decide_lot_release(release_id, {"decision": "RELEASED"},
                                      make_quality_manager_headers("qm-001")),
            ApiErrorId.ERR_QC_NOT_PASSED, 422,
        )
        # QC recorded by one user; the same user id cannot decide.
        validate_success(
            client.record_qc(release_id, {"qc_disposition": "PASSED"},
                             make_lab_technician_headers("shared-1")),
            200,
        )
        validate_error(
            client.decide_lot_release(release_id, {"decision": "RELEASED"},
                                      make_quality_manager_headers("shared-1")),
            ApiErrorId.ERR_SOD_VIOLATION, 422,
        )
        # All gates green with a different decider.
        decided = validate_success(
            client.decide_lot_release(release_id, {"decision": "RELEASED"},
                                      make_quality_manager_headers("qm-002")),
            200,
        )
        assert decided["decision"] == "RELEASED"
