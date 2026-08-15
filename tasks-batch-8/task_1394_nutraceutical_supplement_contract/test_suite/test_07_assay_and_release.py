"""Assay submission/review, dual-axis batch posture, release gates and cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_assay_result,
    create_recall_event,
    get_batch,
    get_customer,
    get_material_lot,
    get_order,
    make_qa_manager_headers,
    record_review_batch,
    setup_batch_at_stage,
    setup_releasable_batch,
    setup_released_batch,
    setup_two_completed_batches,
    submit_assay,
    review_assay,
    validate_error,
    validate_success,
)

QA = TEST_USERS["qa_manager_headers"]
CHEMIST = TEST_USERS["qa_chemist_headers"]


class TestAssaySubmission:
    def test_assay_pct_exactly_90_is_in_range_no_hold(self, api):
        """PRD §3.5: "The acceptable window is inclusive on both ends: a
        `pct_of_claim` of at least 90.0 and at most 110.0 is in range. A submission
        whose ratio falls outside that window automatically drives the batch's
        `quality_status` from `PENDING_QC` to `ASSAY_HOLD`".

        Design: Difficulty/boundary_precision_check/assay_pct_boundary_90_inclusive
        """
        ctx, run1, _run2 = setup_two_completed_batches()
        # Label claim snapshot is 450 mg/unit; 405.0 / 450 * 100 = 90.0 exactly.
        resp = api.submit_assay_result(
            run1["batch"]["id"], {"assayed_mg_per_unit": 405.0}, CHEMIST
        )
        assay = validate_success(resp, 201)
        assert_assay_result(assay)
        assert assay["pct_of_claim"] == 90.0
        assert assay["label_claim_mg_per_unit"] == 450
        batch = get_batch(run1["batch"]["id"])
        assert batch["quality_status"] == "PENDING_QC", (
            "90.0 is inclusive in-range: no ASSAY_HOLD may be raised"
        )

    def test_assay_pct_89_8_trips_assay_hold(self, api):
        """PRD §3.5: "A submission whose ratio falls outside that window
        automatically drives the batch's `quality_status` from `PENDING_QC` to
        `ASSAY_HOLD`; the assay itself sits in `SUBMITTED` status awaiting review".

        Design: Difficulty/boundary_precision_check/assay_pct_boundary_90_inclusive
        """
        ctx, _run1, run2 = setup_two_completed_batches()
        # 404.0 / 450 * 100 = 89.777... rounds half-up to 89.8, below the window.
        resp = api.submit_assay_result(
            run2["batch"]["id"], {"assayed_mg_per_unit": 404.0}, CHEMIST
        )
        assay = validate_success(resp, 201)
        assert assay["pct_of_claim"] == 89.8
        assert assay["status"] == "SUBMITTED"
        batch = get_batch(run2["batch"]["id"])
        assert batch["quality_status"] == "ASSAY_HOLD"

    def test_assay_pct_rounding_one_decimal_half_up(self, api):
        """PRD §3.5: "At submission the system snapshots `label_claim_mg_per_unit`
        from the ordered formula's unique label-claim line onto the assay record,
        computes `pct_of_claim` as the assayed content divided by that label claim,
        multiplied by one hundred, rounded half-up to one decimal place".

        Design: Corner/calculations/assay_pct_rounding_one_decimal_half_up
        """
        ctx = setup_batch_at_stage("COMPLETED")
        resp = api.submit_assay_result(
            ctx["batch"]["id"], {"assayed_mg_per_unit": 473}, CHEMIST
        )
        assay = validate_success(resp, 201)
        assert assay["label_claim_mg_per_unit"] == 450
        # 473 / 450 * 100 = 105.111... -> 105.1 at one decimal, round half-up.
        assert assay["pct_of_claim"] == 105.1
        assert assay["submitted_by_id"] == "chem-1"


class TestDualAxisPosture:
    def test_quality_detours_to_hold_while_production_completed(self, api):
        """PRD §2.11: "A Batch carries two independent status fields that advance in
        parallel." and "The `quality_status` axis begins at `PENDING_QC`, may detour
        through `ASSAY_HOLD`, and reaches `QC_READY` once an in-range assay is
        accepted".
        PRD §2.11: "Transitions on one axis never implicitly satisfy gates on the
        other".

        Design: Difficulty/non_linear_state_machine/batch_parallel_production_and_quality_dimensions
        """
        ctx = setup_batch_at_stage("COMPLETED")
        batch = ctx["batch"]
        assert batch["production_status"] == "COMPLETED"
        assert batch["quality_status"] == "PENDING_QC"

        # 400 / 450 * 100 = 88.9 — outside the window, quality detours to hold.
        assay = submit_assay(batch["id"], 400)
        assert assay["pct_of_claim"] == 88.9
        held = get_batch(batch["id"])
        assert held["quality_status"] == "ASSAY_HOLD"
        assert held["production_status"] == "COMPLETED", (
            "the quality detour must not move the production axis"
        )

    def test_record_review_advances_production_while_quality_in_hold(self, api):
        """PRD §2.11: "The `production_status` axis walks `CREATED` → `IN_PROCESS` →
        `COMPLETED` → `RECORD_REVIEWED`" and "Transitions on one axis never
        implicitly satisfy gates on the other; release explicitly requires both
        axes to be in position (§3.5)."

        Design: Difficulty/non_linear_state_machine/batch_parallel_production_and_quality_dimensions
        """
        ctx = setup_batch_at_stage("COMPLETED")
        assay = submit_assay(ctx["batch"]["id"], 400)
        assert assay["pct_of_claim"] == 88.9
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "ASSAY_HOLD"

        reviewed = record_review_batch(ctx["batch"]["id"])
        assert reviewed["production_status"] == "RECORD_REVIEWED"
        final = get_batch(ctx["batch"]["id"])
        assert final["production_status"] == "RECORD_REVIEWED"
        assert final["quality_status"] == "ASSAY_HOLD", (
            "record review must not clear the quality hold — axes are independent"
        )


class TestAssayReview:
    def test_assay_review_twice_rejected_terminal(self, api):
        """PRD §3.5: "Assay review belongs to the `QAManager`, who supplies a
        `review_outcome` of `ACCEPT` or `REJECT` against a test still in `SUBMITTED`
        (`ERR_ASSAY_STATE` otherwise)" and "both outcomes are terminal for the
        assay."

        Design: Corner/state_machines/assay_review_twice_rejected
        """
        ctx = setup_batch_at_stage("COMPLETED")
        assay = submit_assay(ctx["batch"]["id"], 470)
        accepted = review_assay(assay["id"], "ACCEPT", qm_id="qm-1")
        assert accepted["status"] == "ACCEPTED"

        resp = api.review_assay_result(
            assay["id"], {"review_outcome": "REJECT"}, make_qa_manager_headers("qm-2")
        )
        validate_error(resp, ApiErrorId.ERR_ASSAY_STATE)
        assert resp.status_code == 409


class TestReleaseCascade:
    def test_batch_release_completes_parent_order(self, api):
        """PRD §3.5: "A successful release moves `quality_status` to `RELEASED` and,
        in the same transaction, advances the parent order from `IN_PRODUCTION` to
        `COMPLETED`".

        Design: Difficulty/transitive_cascade/release_cascade_batch_to_order_to_customer
        """
        ctx = setup_releasable_batch(clock="2026-08-01T00:00:00Z")
        assert ctx["batch"]["production_status"] == "RECORD_REVIEWED"
        assert ctx["batch"]["quality_status"] == "QC_READY"
        assert ctx["batch"]["expiry_date"] is not None

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        released = validate_success(resp, 200)
        assert released["quality_status"] == "RELEASED"
        assert get_order(ctx["mo"]["id"])["status"] == "COMPLETED"

    def test_batch_release_recomputes_customer_aggregates(self, api):
        """PRD §3.5: "the customer's `open_order_count` falls by one, its
        `committed_order_value_cents` falls by the order's `total_price_cents`, and
        its `lifetime_receipts_cents` rises by the same amount."
        PRD §2.12: "The `lifetime_receipts_cents` is the sum of `total_price_cents`
        over that customer's `COMPLETED` orders."

        Design: Difficulty/transitive_cascade/release_cascade_batch_to_order_to_customer
        """
        ctx = setup_releasable_batch(clock="2026-08-01T00:00:00Z")
        # 10000 units at the single 120-cent tier -> 1200000 committed before release.
        before = get_customer(ctx["customer"]["id"])
        assert before["committed_order_value_cents"] == 1200000
        assert before["open_order_count"] == 1
        assert before["lifetime_receipts_cents"] == 0

        release_resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_success(release_resp, 200)

        after = get_customer(ctx["customer"]["id"])
        assert after["committed_order_value_cents"] == 0
        assert after["open_order_count"] == 0
        assert after["lifetime_receipts_cents"] == 1200000


class TestReleaseGateOrdering:
    def test_release_reports_assay_gate_before_stability_gate(self, api):
        """PRD §3.5: "The assay gate runs first: an `ACCEPTED` assay with
        `pct_of_claim` within the inclusive 90.0-to-110.0 window must exist, or the
        release is rejected with `ERR_ASSAY_LABEL_CLAIM_FAIL`."
        PRD §3.5: "The stability gate runs last: a `COMPLETED` stability study must
        exist for the batch and its `expiry_date` must be set, or the release is
        rejected with `ERR_STABILITY_NOT_COMPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/release_assay_gate_beats_stability_gate
        """
        # RECORD_REVIEWED batch in ASSAY_HOLD (below-claim assay not accepted);
        # no stability study exists — both the assay and stability gates fail.
        ctx = setup_batch_at_stage("COMPLETED")
        record_review_batch(ctx["batch"]["id"])
        submit_assay(ctx["batch"]["id"], 400)
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "ASSAY_HOLD"

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_ASSAY_LABEL_CLAIM_FAIL)
        assert resp.status_code == 409, (
            "the assay gate must surface before the stability gate"
        )

    def test_failed_release_preserves_assay_hold_posture(self, api):
        """PRD §2.9: "9. Release quality gates in their pinned order — first the
        assay gate (`ERR_ASSAY_LABEL_CLAIM_FAIL`), then the component-lot gate
        (`ERR_COMPONENT_LOT_UNRESOLVED`) — and, on record review, the yield
        tolerance gate (`ERR_YIELD_VARIANCE_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/release_assay_gate_beats_stability_gate
        """
        ctx = setup_batch_at_stage("COMPLETED")
        record_review_batch(ctx["batch"]["id"])
        submit_assay(ctx["batch"]["id"], 400)

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_ASSAY_LABEL_CLAIM_FAIL)

        batch = get_batch(ctx["batch"]["id"])
        assert batch["quality_status"] == "ASSAY_HOLD", (
            "a rejected release must leave the quality posture unchanged"
        )
        assert batch["production_status"] == "RECORD_REVIEWED"
        assert get_order(ctx["mo"]["id"])["status"] == "IN_PRODUCTION"


class TestComponentLotAndStabilityGates:
    def test_component_lot_recalled_prerelease_blocks_release(self, api):
        """PRD §3.8: "every batch holding an `ACTIVE` consumption of that lot whose
        `quality_status` is `RELEASED` transitions to `RECALLED`" — a pre-release
        batch is therefore not caught by the cascade.
        PRD §3.5: "The component-lot gate runs second: every `ACTIVE` consumption
        row's lot must currently be `RELEASED` — a lot recalled after consumption
        fails this gate — or the release is rejected with
        `ERR_COMPONENT_LOT_UNRESOLVED`."

        Design: Corner/validations/component_lot_recalled_prerelease_blocks_release
        """
        ctx = setup_batch_at_stage("ASSAY_ACCEPTED")
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "QC_READY"

        recall = create_recall_event("MATERIAL_LOT", ctx["lot"]["id"])
        assert recall["affected_batch_count"] == 0, (
            "the QC_READY batch is not RELEASED, so the cascade must not touch it"
        )
        assert get_material_lot(ctx["lot"]["id"])["status"] == "RECALLED"
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "QC_READY"

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_LOT_UNRESOLVED)
        assert resp.status_code == 409

    def test_stability_gate_blocks_release_when_no_study(self, api):
        """PRD §3.5: "The stability gate runs last: a `COMPLETED` stability study
        must exist for the batch and its `expiry_date` must be set, or the release
        is rejected with `ERR_STABILITY_NOT_COMPLETED`."

        Design: Corner/validations/stability_gate_blocks_release_when_no_study
        """
        ctx = setup_batch_at_stage("ASSAY_ACCEPTED")
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "QC_READY"

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_STABILITY_NOT_COMPLETED)
        assert resp.status_code == 409
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "QC_READY"


class TestReleaseTerminal:
    def test_release_of_released_batch_rejected(self, api):
        """PRD §3.5: "A `QAManager` releases a batch whose `quality_status` is
        `PENDING_QC`, `ASSAY_HOLD`, or `QC_READY` and whose `production_status` is
        `RECORD_REVIEWED` — violations of either state requirement surface as
        `ERR_BATCH_STATE`."

        Design: Corner/state_machines/batch_release_from_released_rejected_terminal
        """
        ctx = setup_released_batch(clock="2026-08-01T00:00:00Z")
        assert ctx["batch"]["quality_status"] == "RELEASED"

        resp = api.release_batch(ctx["batch"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE)
        assert resp.status_code == 409
        assert get_batch(ctx["batch"]["id"])["quality_status"] == "RELEASED"
