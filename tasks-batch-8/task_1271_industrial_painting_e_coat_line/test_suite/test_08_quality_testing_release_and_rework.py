"""Quality testing gates, lot release, and the strip-and-repaint rework loop."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_lot_curing, setup_lot_qc_pending, setup_lot_qc_hold,
    setup_rework_approved, setup_lot_requeued_after_rework,
    record_quality_test, record_oven_cycle,
    create_quality_test_payload,
    get_lot, get_permit, get_rework_order,
    schedule_slot, run_lot_through_second_pass,
    assert_lot_part_accountability,
    TEST_USERS, make_qc_inspector_headers, make_quality_manager_headers,
)

SCHED = TEST_USERS["scheduler_headers"]
QM = TEST_USERS["qm_headers"]


class TestQualityTestStateGate:
    def test_quality_test_before_cure_pass_rejected(self, api):
        """PRD §3.6: "Testing is only meaningful after a passed cure: the lot must be
        in `QC_PENDING`, and a test attempted at any other time is rejected with
        `ERR_CURE_NOT_PASSED`."

        Design: Corner/errors/quality_test_before_cure_pass_returns_cure_not_passed
        """
        ctx = setup_lot_curing()  # lot is CURING, no oven cycle yet
        res = api.create_quality_test(
            create_quality_test_payload(ctx["lot"]["id"], test_type="ADHESION", measured_value=3),
            make_qc_inspector_headers("qc-1"),
        )
        validate_error(res, "ERR_CURE_NOT_PASSED", expected_status=409)
        tests = validate_success(api.list_quality_tests_of_lot(ctx["lot"]["id"], SCHED), 200)
        assert len(tests) == 0


class TestReleaseEvidenceGate:
    def test_release_blocked_until_both_evidence_legs_pass(self, api):
        """PRD §3.6: "Evidence must exist: at least one `PASS` quality test of type
        `ADHESION` recorded after the lot's latest `PASS` oven cycle, and at least one
        `PASS` test of type `IMPACT` recorded after that same cycle — the current cure
        epoch — with a missing leg rejected as `ERR_TESTS_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_gated_by_quality_test_states
        """
        ctx = setup_lot_qc_pending()
        record_quality_test(ctx["lot"]["id"], "ADHESION", 3)  # adhesion leg only

        res = api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-1"))
        validate_error(res, "ERR_TESTS_INCOMPLETE", expected_status=409)

        record_quality_test(ctx["lot"]["id"], "IMPACT", 50.0)
        released = validate_success(
            api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-1")), 200
        )
        assert released["status"] == "RELEASED"
        assert released["passed_quantity"] == 100
        # Base only: 100 parts x round_half_up(12 dm2 x 110 cents) = 132000.
        assert released["total_charge_cents"] == 132000

    def test_release_with_no_quality_tests_at_all_rejected(self, api):
        """PRD §3.6: "Evidence must exist: at least one `PASS` quality test of type
        `ADHESION` recorded after the lot's latest `PASS` oven cycle, and at least one
        `PASS` test of type `IMPACT` recorded after that same cycle — the current cure
        epoch — with a missing leg rejected as `ERR_TESTS_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_gated_by_quality_test_states
        """
        ctx = setup_lot_qc_pending()  # cure passed, zero quality tests recorded
        res = api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-1"))
        validate_error(res, "ERR_TESTS_INCOMPLETE", expected_status=409)
        assert get_lot(ctx["lot"]["id"])["status"] == "QC_PENDING"


class TestReworkCycle:
    def test_full_rework_cycle_returns_lot_to_queued(self, api):
        """PRD §3.7: "When `scrapped_quantity` is less than `parts_to_rework`, the
        stripped remainder goes back through the plant: the lot returns from
        `STRIPPING` to `QUEUED` and may be scheduled again — this is the rework cycle
        edge `QUEUED → … → QC_HOLD → STRIPPING → QUEUED`."

        Design: Difficulty/non_linear_state_machine/lot_rework_cycle_returns_to_queued
        """
        ctx = setup_lot_qc_pending()
        # IMPACT fail (measured 10.0 < min 40.0) -> QC_HOLD + auto DRAFT rework order.
        failing = record_quality_test(ctx["lot"]["id"], "IMPACT", 10.0)
        assert failing["verdict"] == "FAIL"
        lot_held = get_lot(ctx["lot"]["id"])
        assert lot_held["status"] == "QC_HOLD"

        orders = validate_success(api.list_rework_orders_of_lot(ctx["lot"]["id"], QM), 200)
        assert len(orders) == 1
        order = orders[0]
        assert order["status"] == "DRAFT"
        assert order["parts_to_rework"] == 100

        approved = validate_success(
            api.approve_rework_order(order["id"], make_quality_manager_headers("qm-1")), 200
        )
        assert approved["status"] == "APPROVED"
        assert get_lot(ctx["lot"]["id"])["status"] == "STRIPPING"

        completed = validate_success(
            api.complete_strip(order["id"], {"scrapped_quantity": 0},
                               make_quality_manager_headers("qm-1")),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["repaint_charge_cents"] == 135700
        assert completed["total_charge_cents"] == 190700

        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["status"] == "QUEUED"
        assert lot_after["rework_count"] == 1
        assert lot_after["scrapped_quantity"] == 0

    def test_second_qc_cycle_after_rework_can_release(self, api):
        """PRD §3.7: "When `scrapped_quantity` is less than `parts_to_rework`, the
        stripped remainder goes back through the plant: the lot returns from
        `STRIPPING` to `QUEUED` and may be scheduled again — this is the rework cycle
        edge `QUEUED → … → QC_HOLD → STRIPPING → QUEUED`."

        Design: Difficulty/non_linear_state_machine/lot_rework_cycle_returns_to_queued
        """
        ctx = setup_lot_requeued_after_rework(scrapped_quantity=0)
        assert ctx["lot"]["status"] == "QUEUED"

        run_lot_through_second_pass(ctx)
        assert get_lot(ctx["lot"]["id"])["status"] == "QC_PENDING"

        record_quality_test(ctx["lot"]["id"], "ADHESION", 3)
        record_quality_test(ctx["lot"]["id"], "IMPACT", 50.0)
        released = validate_success(
            api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-1")), 200
        )
        assert released["status"] == "RELEASED"


class TestReworkChargeRounding:
    def test_per_part_repaint_rounding_order_pinned(self, api):
        """PRD §3.7: "The repaint charge follows a pinned rounding order that is part
        of the contract. The per-part repaint amount — the specification's
        `area_dm2_per_part` multiplied by the repaint rate of 85 cents per square
        decimeter, multiplied by the rework multiplier 1.33 — is rounded half-up to a
        whole cent **first**, and only then multiplied by the repainted part count
        (`parts_to_rework` minus `scrapped_quantity`) to give `repaint_charge_cents`.
        Multiplying first and rounding last yields different cents and is not the
        specified behavior."

        Design: Difficulty/combinatorial_formula/rework_charge_per_part_rounding_pinned
        """
        ctx = setup_rework_approved()
        order = ctx["rework_order"]
        # Strip cost pinned at approve: 25000 + 300 x 100 = 55000.
        assert order["strip_cost_cents"] == 55000

        completed = validate_success(
            api.complete_strip(order["id"], {"scrapped_quantity": 5},
                               make_quality_manager_headers("qm-1")),
            200,
        )
        # Per-part repaint: round_half_up(12 x 85 x 1.33) = 1357; x 95 = 128915.
        assert completed["repaint_charge_cents"] == 128915
        assert completed["total_charge_cents"] == 183915

        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["status"] == "QUEUED"
        assert lot_after["rework_count"] == 1
        assert lot_after["scrapped_quantity"] == 5

        # Strip emission: 95 stripped parts x 0.5 L x 900 g/L / 1000 = 42.750 kg,
        # plus the metered 0.304 kg posted at slot completion.
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["used_kg"] == pytest.approx(43.054, abs=1e-9)

    def test_strip_cost_constants_applied_at_approve(self, api):
        """PRD §3.7: "Approval prices the strip immediately — `strip_cost_cents` is a
        fixed 25,000 cents plus 300 cents per part in `parts_to_rework` — and moves the
        lot from `QC_HOLD` to `STRIPPING`."

        Design: Difficulty/combinatorial_formula/rework_charge_per_part_rounding_pinned
        """
        ctx = setup_lot_qc_hold()
        order = ctx["rework_order"]
        assert order["parts_to_rework"] == 100
        approved = validate_success(
            api.approve_rework_order(order["id"], make_quality_manager_headers("qm-1")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["strip_cost_cents"] == 55000
        assert get_lot(ctx["lot"]["id"])["status"] == "STRIPPING"


class TestReworkGuards:
    def test_scrapped_quantity_above_parts_to_rework_rejected(self, api):
        """PRD §3.7: "Strip completion reports the `scrapped_quantity` — parts written
        off rather than stripped — which must lie between zero and `parts_to_rework`
        inclusive, else `ERR_PART_ACCOUNT_MISMATCH`; the order must be `APPROVED`
        (otherwise `ERR_INVALID_STATE`)."

        Design: Corner/validations/part_account_mismatch_on_complete_strip
        """
        ctx = setup_rework_approved()
        order = ctx["rework_order"]
        res = api.complete_strip(
            order["id"], {"scrapped_quantity": 101}, make_quality_manager_headers("qm-1")
        )
        validate_error(res, "ERR_PART_ACCOUNT_MISMATCH", expected_status=422)
        order_after = get_rework_order(order["id"])
        assert order_after["status"] == "APPROVED"
        assert get_lot(ctx["lot"]["id"])["status"] == "STRIPPING"

    def test_third_rework_approval_rejected_at_limit(self, api):
        """PRD §3.7: "Approval requires the order to be `DRAFT` (otherwise
        `ERR_INVALID_STATE`) and the lot to have rework headroom: `rework_count` must
        be below the plant maximum of two completed strip-and-repaint cycles, or
        approval is rejected with `ERR_REWORK_LIMIT_EXCEEDED`."

        Design: Corner/validations/rework_limit_exceeded_at_third_approve
        """
        ctx = setup_lot_requeued_after_rework(scrapped_quantity=0)
        assert ctx["lot"]["rework_count"] == 1

        # Second full pass: schedule on a fresh day, fail adhesion again, strip again.
        run_lot_through_second_pass(
            ctx, slot_start="2026-05-06T08:00:00Z", slot_end="2026-05-06T10:00:00Z",
            cycle_overrides={"entered_at": "2026-05-06T10:05:00Z",
                             "exited_at": "2026-05-06T10:45:00Z"},
        )
        record_quality_test(ctx["lot"]["id"], "ADHESION", 1)
        orders = validate_success(api.list_rework_orders_of_lot(ctx["lot"]["id"], QM), 200)
        ro2 = orders[1]
        validate_success(
            api.approve_rework_order(ro2["id"], make_quality_manager_headers("qm-1")), 200
        )
        validate_success(
            api.complete_strip(ro2["id"], {"scrapped_quantity": 0},
                               make_quality_manager_headers("qm-1")),
            200,
        )
        lot_now = get_lot(ctx["lot"]["id"])
        assert lot_now["rework_count"] == 2
        assert lot_now["status"] == "QUEUED"

        # Third pass: QC fail creates a third DRAFT order; its approval hits the limit.
        run_lot_through_second_pass(
            ctx, slot_start="2026-05-07T08:00:00Z", slot_end="2026-05-07T10:00:00Z",
            cycle_overrides={"entered_at": "2026-05-07T10:05:00Z",
                             "exited_at": "2026-05-07T10:45:00Z"},
        )
        record_quality_test(ctx["lot"]["id"], "ADHESION", 1)
        orders = validate_success(api.list_rework_orders_of_lot(ctx["lot"]["id"], QM), 200)
        ro3 = orders[2]
        assert ro3["status"] == "DRAFT"

        res = api.approve_rework_order(ro3["id"], make_quality_manager_headers("qm-1"))
        validate_error(res, "ERR_REWORK_LIMIT_EXCEEDED", expected_status=422)
        assert get_rework_order(ro3["id"])["status"] == "DRAFT"
        assert get_lot(ctx["lot"]["id"])["status"] == "QC_HOLD"
