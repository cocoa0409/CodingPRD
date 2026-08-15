"""Difficulty: cross-entity state dependencies — batch release gated by
Supplier state, registration acceptance gated by the formula recall flag
(PRD §3.5, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_production_batch,
    get_batch,
    get_registration,
    initiate_recall,
    lot_payload,
    setup_locked_formula,
    setup_registration,
    validate_error,
    validate_success,
)


class TestBatchReleaseDependsOnSupplierState:
    def _setup_suspended_supplier_batch(self, api, qa_approver_headers):
        """LOCKED formula with a SCHEDULED batch; the sole ingredient pairing is
        APPROVED, then its Supplier is suspended."""
        ctx = setup_locked_formula()
        batch = create_production_batch(
            ctx["formula"]["id"], planned_kg=800.0, line_id="LINE-E",
            scheduled_start="2026-08-13T08:00:00Z",
        )
        validate_success(api.suspend_supplier(ctx["supplier"]["id"], qa_approver_headers))
        return ctx, batch

    def test_release_blocked_by_suspended_supplier(
        self, api, qa_approver_headers, production_planner_headers
    ):
        """PRD §3.5: "When no approved pairing exists for an ingredient the
        rejection is `ERR_UNAPPROVED_INGREDIENT_SOURCE`; when approved pairings
        exist but the supplier behind them has been suspended, the rejection is
        `ERR_SUPPLIER_SUSPENDED` (HTTP 422) — a suspended supplier blocks release
        even though its pairings remain on file."

        Design: Difficulty/cross_entity_state_dependency/batch_release_depends_on_supplier_state
        """
        _ctx, batch = self._setup_suspended_supplier_batch(api, qa_approver_headers)
        resp = api.release_batch(batch["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_SUSPENDED.value)

    def test_blocked_release_leaves_batch_scheduled(
        self, api, qa_approver_headers, production_planner_headers
    ):
        """PRD §3.5: "when approved pairings exist but the supplier behind them
        has been suspended, the rejection is `ERR_SUPPLIER_SUSPENDED`
        (HTTP 422) — a suspended supplier blocks release even though its pairings
        remain on file."
        PRD §3.5: "A new batch starts in `SCHEDULED` with `actual_kg` at zero."

        Design: Difficulty/cross_entity_state_dependency/batch_release_depends_on_supplier_state
        """
        _ctx, batch = self._setup_suspended_supplier_batch(api, qa_approver_headers)
        resp = api.release_batch(batch["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_SUSPENDED.value, expected_status=422)
        assert get_batch(batch["id"])["status"] == "SCHEDULED"


class TestRegistrationAcceptanceDependsOnRecallFlag:
    def _setup_open_recall_with_submitted_registration(
        self, api, production_planner_headers, line_operator_headers
    ):
        """LOCKED formula with a SUBMITTED registration, then an open recall
        flips the formula's open_recall_flag."""
        ctx = setup_registration(target_state="SUBMITTED", state_code="CA", locked=True)
        batch = create_production_batch(
            ctx["formula"]["id"], planned_kg=300.0, line_id="LINE-F",
            scheduled_start="2026-08-14T08:00:00Z",
        )
        validate_success(api.release_batch(batch["id"], production_planner_headers))
        validate_success(api.start_run(batch["id"], line_operator_headers))
        validate_success(api.complete_batch(batch["id"], {"actual_kg": 300.0}, line_operator_headers))
        validate_success(
            api.create_lot(batch["id"], lot_payload(packaged_units=100), line_operator_headers),
            expected_status=201,
        )
        initiate_recall(
            ctx["formula"]["id"], [batch["id"]], recall_class="CLASS_II",
            reason="Label misprint",
        )
        return ctx

    def test_accept_for_review_blocked_by_open_recall(self, api, production_planner_headers,
                                                      line_operator_headers,
                                                      state_regulator_headers):
        """PRD §3.7: "A `StateRegulator` accepts a submission for review, moving
        it from `SUBMITTED` to `UNDER_REVIEW`; acceptance requires the formula to
        be `SUBSTANTIATED` or `LOCKED` and the formula's `open_recall_flag` to be
        false, else `ERR_OPEN_RECALL`."
        PRD §3.8: "the formula's `open_recall_flag` is set true"

        Design: Difficulty/cross_entity_state_dependency/registration_acceptance_depends_on_recall_flag
        """
        ctx = self._setup_open_recall_with_submitted_registration(
            api, production_planner_headers, line_operator_headers
        )
        resp = api.accept_registration_for_review(
            ctx["registration"]["id"], state_regulator_headers
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_RECALL.value)

    def test_blocked_acceptance_leaves_registration_submitted(
        self, api, production_planner_headers, line_operator_headers,
        state_regulator_headers
    ):
        """PRD §3.7: "acceptance requires the formula to be `SUBSTANTIATED` or
        `LOCKED` and the formula's `open_recall_flag` to be false, else
        `ERR_OPEN_RECALL`."
        PRD §3.7: "Submission stamps `submitted_at`, computes the `fee_cents`
        from the fee schedule, and lands the registration in `SUBMITTED`."

        Design: Difficulty/cross_entity_state_dependency/registration_acceptance_depends_on_recall_flag
        """
        ctx = self._setup_open_recall_with_submitted_registration(
            api, production_planner_headers, line_operator_headers
        )
        resp = api.accept_registration_for_review(
            ctx["registration"]["id"], state_regulator_headers
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_RECALL.value, expected_status=422)
        assert get_registration(ctx["registration"]["id"])["status"] == "SUBMITTED"
