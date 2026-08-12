"""Cure testing, assessment variants, lot release gating, retests, expiry dating."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_test,
    create_and_complete_run,
    create_formulation,
    create_mixed_batch,
    create_vessel,
    lot_under_review_with_passing_full,
    record_and_accept_test,
    record_test,
    release_lot,
    set_clock,
    validate_error,
    validate_success,
)


def _mixed_batch_with_lot(code, volume_ml=5000, **formulation_overrides):
    set_clock()
    formulation = create_formulation(code, activate=True, **formulation_overrides)
    vessel = create_vessel(f"V-{code}", capacity_liters=100)
    batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=volume_ml)
    return formulation, vessel, batch, batch["production_lot_id"]


class TestQuickPassFullFailDivergence:
    """Difficulty instance lot_release_quick_pass_full_fail_divergence."""

    def _setup(self):
        formulation, vessel, batch, lot_id = _mixed_batch_with_lot("EPX-QF-1", volume_ml=5000)
        run = create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=10,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        # QUICK 12.4 >= 12.0 passes; then a retest cycle and a failing FULL.
        t_quick = record_and_accept_test(lot_id, method="QUICK", specimens=[12.4])
        assert t_quick["assessment_pass"] is True
        from test_helpers import api_client, make_qa_manager_headers
        validate_success(api_client.request_retest(lot_id, make_qa_manager_headers("qm-1")))
        t_full = record_and_accept_test(
            lot_id, method="FULL", specimens=[12.1, 12.0, 11.8, 11.6, 13.0]
        )
        return lot_id, t_quick, t_full

    def test_variants_diverge_on_same_lot_data(self, api, qa_manager_headers):
        """PRD §3.6: "For `QUICK`, exactly 1 specimen is required; `evaluated_value_mpa` is that single specimen, and `assessment_pass` is true when the value is at least the formulation's `spec_min_bond_strength_mpa` — the comparison is inclusive. For `FULL`, exactly 5 specimens are required; the readings are sorted ascending, exactly one minimum and one maximum are dropped, the mean of the three retained specimens is taken and rounded half-up to two decimal places to produce `evaluated_value_mpa`, and `assessment_pass` is true only when both the trimmed mean is at least `spec_min_bond_strength_mpa` **and** the smallest retained specimen is no more than 2.0 MPa below `spec_min_bond_strength_mpa`."
        PRD §3.6: "The two variants are deliberately not interchangeable: the same lot data can pass `QUICK` while failing `FULL`, and vice versa."

        Design: Difficulty/dual_variant_calc/lot_release_quick_pass_full_fail_divergence
        """
        lot_id, t_quick, t_full = self._setup()
        quick = validate_success(api.get_cure_test(t_quick["id"], qa_manager_headers))
        assert quick["evaluated_value_mpa"] == pytest.approx(12.4)
        assert quick["assessment_pass"] is True
        assert quick["status"] == "SUPERSEDED"
        full = validate_success(api.get_cure_test(t_full["id"], qa_manager_headers))
        # Trimmed mean of retained [11.8, 12.0, 12.1] = 35.9/3 -> round_half_up 11.97.
        assert full["evaluated_value_mpa"] == pytest.approx(11.97)
        assert full["assessment_pass"] is False
        assert full["status"] == "ACCEPTED"

    def test_release_blocked_when_latest_full_fails(self, api, qa_manager_headers):
        """PRD §3.6: "the most recently `ACCEPTED` (and not subsequently `SUPERSEDED`) test must be a `FULL` assessment whose `assessment_pass` is true (else `ERR_BOND_STRENGTH_BELOW_SPEC` — a passing `QUICK` screen never suffices)"

        Design: Difficulty/dual_variant_calc/lot_release_quick_pass_full_fail_divergence
        """
        lot_id, _t_quick, _t_full = self._setup()
        resp = api.release_lot(lot_id, qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BOND_STRENGTH_BELOW_SPEC)
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"


class TestQuickAssessmentBoundary:
    def test_quick_assessment_inclusive_spec_boundary(self, api, qa_manager_headers):
        """PRD §3.6: "For `QUICK`, exactly 1 specimen is required; `evaluated_value_mpa` is that single specimen, and `assessment_pass` is true when the value is at least the formulation's `spec_min_bond_strength_mpa` — the comparison is inclusive."

        Design: Corner/calculations/quick_assessment_inclusive_spec_boundary
        """
        _formulation, _vessel, _batch, lot_id = _mixed_batch_with_lot("EPX-QB", volume_ml=1000)
        test = record_test(lot_id, method="QUICK", specimens=[12.0])
        accepted = accept_test(test["id"])
        assert accepted["evaluated_value_mpa"] == pytest.approx(12.0)
        assert accepted["assessment_pass"] is True


class TestLotTerminalLockdown:
    def test_lot_terminal_rejected_lockdown(self, api, qa_manager_headers, plant_manager_headers):
        """PRD §3.6: "**Reject** moves the lot to `REJECTED`; segregation of duties applies — the acting `X-User-ID` must differ from the `technician_id` of the accepted test, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.6: "Evaluated in order: the lot must be in `UNDER_REVIEW` (else `ERR_LOT_INVALID_STATE`); its `hold_status` must be `CLEAR` (else `ERR_LOT_ON_HOLD`); the most recently `ACCEPTED` (and not subsequently `SUPERSEDED`) test must be a `FULL` assessment whose `assessment_pass` is true (else `ERR_BOND_STRENGTH_BELOW_SPEC` — a passing `QUICK` screen never suffices); segregation of duties must hold between the releaser and the recording technician (else `ERR_SEGREGATION_OF_DUTIES`); and the formulation must still be `EFFECTIVE` (else `ERR_FORMULATION_NOT_EFFECTIVE`)."
        PRD §3.6: "the lot allows at most two retest cycles, so a request when `retest_count` has already reached 2 fails with `ERR_RETEST_LIMIT_EXCEEDED`, and a request from any other qa status fails with `ERR_LOT_INVALID_STATE`."

        Design: Corner/state_machines/lot_terminal_rejected_lockdown
        """
        _formulation, _vessel, batch, lot_id = _mixed_batch_with_lot("EPX-LOCK", volume_ml=5000)
        create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        lot_under_review_with_passing_full(lot_id)
        rejected = validate_success(api.reject_lot(lot_id, qa_manager_headers, {"reason": "visual defect"}))
        assert rejected["qa_status"] == "REJECTED"
        # Reject side effect: sealed units condemned.
        assert rejected["units_condemned"] == 3
        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["written_off_volume_ml"] == 948

        resp_release = api.release_lot(lot_id, qa_manager_headers)
        validate_error(resp_release, ApiErrorId.ERR_LOT_INVALID_STATE)
        resp_retest = api.request_retest(lot_id, qa_manager_headers)
        validate_error(resp_retest, ApiErrorId.ERR_LOT_INVALID_STATE)


class TestRetestLimit:
    def test_retest_limit_exceeded_returns_409(self, api, qa_manager_headers):
        """PRD §3.6: "**Request retest** returns the lot to `TESTING`, incrementing `retest_count` by one; the lot allows at most two retest cycles, so a request when `retest_count` has already reached 2 fails with `ERR_RETEST_LIMIT_EXCEEDED`, and a request from any other qa status fails with `ERR_LOT_INVALID_STATE`."

        Design: Corner/errors/retest_limit_exceeded_returns_409
        """
        _formulation, _vessel, _batch, lot_id = _mixed_batch_with_lot("EPX-RTX", volume_ml=5000)
        t1 = lot_under_review_with_passing_full(lot_id)
        validate_success(api.request_retest(lot_id, qa_manager_headers))
        t2 = record_and_accept_test(lot_id, method="FULL")
        validate_success(api.request_retest(lot_id, qa_manager_headers))
        t3 = record_and_accept_test(lot_id, method="FULL")

        resp = api.request_retest(lot_id, qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED)

        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"
        t1_after = validate_success(api.get_cure_test(t1["id"], qa_manager_headers))
        t2_after = validate_success(api.get_cure_test(t2["id"], qa_manager_headers))
        t3_after = validate_success(api.get_cure_test(t3["id"], qa_manager_headers))
        assert t1_after["status"] == "SUPERSEDED"
        assert t2_after["status"] == "SUPERSEDED"
        assert t3_after["status"] == "ACCEPTED"


class TestAcceptTestState:
    def test_accept_accepted_test_returns_409(self, api, qa_manager_headers):
        """PRD §3.6: "A `QAManager` accepts a `RECORDED` test; acceptance requires the lot's `qa_status` to be `TESTING` (a test out of place fails with `ERR_TEST_INVALID_STATE`, a lot out of state with `ERR_LOT_INVALID_STATE`)."

        Design: Corner/errors/accept_accepted_test_returns_409
        """
        _formulation, _vessel, _batch, lot_id = _mixed_batch_with_lot("EPX-ACC", volume_ml=5000)
        t1 = record_and_accept_test(lot_id, method="QUICK", specimens=[12.4])
        assert t1["status"] == "ACCEPTED"

        resp = api.accept_cure_test(t1["id"], qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_TEST_INVALID_STATE)


class TestExpiryDating:
    def test_expiry_date_month_end_clamp(self, api, qa_manager_headers, batch_operator_headers, plant_manager_headers):
        """PRD §3.3: "`manufacture_date` becomes the calendar date of `mixed_at` in `YYYY-MM-DD` form, and `expiry_date` becomes `manufacture_date` advanced by the formulation's `shelf_life_months` calendar months, with the day-of-month clamped to the last day of the target month when it would otherwise overflow (so a manufacture date of 2026-01-31 with a one-month shelf life yields an expiry of 2026-02-28)."

        Design: Corner/calculations/expiry_date_month_end_clamp
        """
        set_clock("2026-01-31T08:00:00Z")
        formulation = create_formulation(
            "EPX-CLP", activate=True, shelf_life_months=1, min_remaining_shelf_life_days=10
        )
        vessel = create_vessel("V-CLP", capacity_liters=100)
        batch = validate_success(
            api.create_batch(
                {
                    "formulation_id": formulation["id"],
                    "vessel_id": vessel["id"],
                    "mix_start_at": "2026-01-31T08:00:00Z",
                    "mix_end_at": "2026-01-31T09:00:00Z",
                    "batch_volume_ml": 1000,
                },
                batch_operator_headers,
            ),
            expected_status=201,
        )
        validate_success(api.complete_mix(batch["id"], batch_operator_headers))
        lot = validate_success(api.get_production_lot(batch["production_lot_id"], qa_manager_headers))
        assert lot["manufacture_date"] == "2026-01-31"
        assert lot["expiry_date"] == "2026-02-28"


class TestLotReleaseBlockedByWithdrawnFormulation:
    """Difficulty instance lot_release_blocked_by_withdrawn_formulation."""

    def _setup(self, api, plant_manager_headers):
        set_clock()
        formulation = create_formulation("EPX-XEN-1", activate=True)
        vessel = create_vessel("V-XEN-1", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=948)
        lot_id = batch["production_lot_id"]
        create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        lot_under_review_with_passing_full(lot_id)
        return formulation, batch, lot_id

    def test_fully_packed_batch_then_withdraw_succeeds(self, api, plant_manager_headers, qa_manager_headers):
        """PRD §3.1: "Withdrawal is refused with `ERR_FORMULATION_INVALID_STATE` when the formulation is not currently `EFFECTIVE`, and refused with `ERR_FORMULATION_HAS_INFLIGHT_BATCHES` when any batch referencing it is still in `MIXING`, `MIXED`, or `PACKING`."
        PRD §3.4: "A successful completion moves the run to `SEALED`, decrements the batch's `remaining_bulk_volume_ml` by `total_filled_ml`, increments the lot's `units_filled` by `units_produced`, and — when the remaining bulk volume reaches exactly zero — transitions the batch from `PACKING` to `PACKED`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_withdrawn_formulation
        """
        formulation, batch, _lot_id = self._setup(api, plant_manager_headers)
        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["status"] == "PACKED"
        assert batch_after["remaining_bulk_volume_ml"] == 0  # 3 x 316 = 948

        withdrawn = validate_success(api.withdraw_formulation(formulation["id"], plant_manager_headers))
        assert withdrawn["status"] == "WITHDRAWN"

    def test_release_rejected_after_formulation_withdrawn(self, api, plant_manager_headers, qa_manager_headers):
        """PRD §3.1: "Only an `EFFECTIVE` formulation accepts new batches or permits lot release — any attempt to create a batch, or to release a lot, against a formulation that has left `EFFECTIVE` is rejected with `ERR_FORMULATION_NOT_EFFECTIVE`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_withdrawn_formulation
        """
        formulation, _batch, lot_id = self._setup(api, plant_manager_headers)
        validate_success(api.withdraw_formulation(formulation["id"], plant_manager_headers))

        resp = api.release_lot(lot_id, qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORMULATION_NOT_EFFECTIVE)
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"
