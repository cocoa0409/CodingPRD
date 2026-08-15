"""Batch-job release gates (PRD §3.6): recipe approval, credit standing, tank
cleanliness, agreement currency, schedule overlap, capacity, and the OCC
stale-version guard, plus the §2.9 evaluation order."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_batch_job,
    create_approved_recipe,
    create_batch_job,
    create_clean_validated_tank,
    create_customer,
    create_pricing_agreement,
    create_tank,
    receive_lot,
    release_batch_job,
    setup_batch_context,
    setup_released_batch,
    suspend_customer,
    validate_error,
    validate_success,
)

SCHED = TEST_USERS["batch_scheduler_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestReleasePreconditionGates:
    def test_create_with_draft_recipe_rejected(self, api):
        """PRD §3.6: "the referenced recipe must be `APPROVED` (otherwise
        `ERR_RECIPE_NOT_APPROVED`, HTTP 409)".

        Design: Corner/state_machines/batch_create_with_draft_recipe_returns_recipe_not_approved
        """
        customer = create_customer("Draft Recipe Co")
        recipe_resp = api.create_recipe(
            {"name": "DraftR", "revision": 1, "customer_id": customer["id"],
             "target_density_kg_per_l": 1.0, "theoretical_yield_pct": 100,
             "components": [{"material_code": "A", "mass_fraction_pct": 100.0,
                             "charge_order": 1}]},
            QM)
        recipe = validate_success(recipe_resp, 201)
        assert recipe["status"] == "DRAFT"
        agreement = create_pricing_agreement(customer["id"], activate=True)
        tank = create_tank()
        resp = api.create_batch_job(
            customer["id"],
            {"recipe_id": recipe["id"], "pricing_agreement_id": agreement["id"],
             "tank_id": tank["id"], "batch_size_l": 50,
             "scheduled_start": "2026-09-01T08:00:00Z",
             "scheduled_end": "2026-09-01T12:00:00Z"},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_APPROVED)

    def test_release_with_dirty_tank_rejected(self, api):
        """PRD §3.6: "the tank `CLEAN_VALIDATED` (else
        `ERR_TANK_NOT_CLEAN_VALIDATED`, HTTP 409)".

        Design: Corner/state_machines/batch_release_with_dirty_tank_returns_tank_not_clean
        """
        customer = create_customer("Dirty Tank Co")
        recipe = create_approved_recipe(customer["id"])
        agreement = create_pricing_agreement(customer["id"], activate=True)
        # Tank registered but never cleaned: cleaning_state stays DIRTY.
        tank = create_tank(capacity_l=500, working_capacity_l=500)
        assert tank["cleaning_state"] == "DIRTY"
        batch = create_batch_job(customer["id"], recipe["id"], agreement["id"],
                                 tank["id"], batch_size_l=100)
        resp = api.release_batch_job(customer["id"], batch["id"],
                                     batch["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_TANK_NOT_CLEAN_VALIDATED)

    def test_release_batch_size_exceeds_working_capacity(self, api):
        """PRD §3.6: "the ordered litres no greater than the tank's
        `working_capacity_l` (else `ERR_BATCH_SIZE_EXCEEDS_CAPACITY`,
        HTTP 422)".

        Design: Corner/state_machines/batch_capacity_exceeded_returns_err
        """
        ctx = setup_batch_context(
            tank_overrides={"capacity_l": 500, "working_capacity_l": 500},
            batch_overrides={"batch_size_l": 600})
        resp = api.release_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                     ctx["batch"]["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_BATCH_SIZE_EXCEEDS_CAPACITY)

    def test_release_with_stale_batch_version_rejected(self, api):
        """PRD §2.8: "Releasing a batch job requires the request to carry
        `expected_batch_job_version`, holding the batch's `version` as the
        client last observed it. If another writer has advanced the batch's
        `version` since that observation — a cancellation, or a charge commit
        that cascaded a version bump onto the batch — the release is rejected
        with `ERR_STALE_VERSION` (HTTP 412), so the client never acts on a
        batch state it has not seen."

        Design: Corner/errors/occ_stale_version_on_release_returns_412
        """
        ctx = setup_batch_context()
        batch = ctx["batch"]
        assert batch["version"] == 1
        # The client's observed version lags the server's current version.
        resp = api.release_batch_job(ctx["customer"]["id"], batch["id"],
                                     batch["version"] - 1, SCHED)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_batch_job(
            ctx["customer"]["id"], batch["id"], QM))
        assert after["status"] == "INTAKE"


class TestAgreementDependency:
    def test_release_with_draft_agreement_rejected(self, api):
        """PRD §3.6: "the pinned agreement `ACTIVE` with the logical clock
        inside its half-open window (else `ERR_AGREEMENT_NOT_ACTIVE`,
        HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/batch_release_depends_on_tank_and_pricing_agreement_state
        """
        # Agreement deliberately left in DRAFT (never activated).
        ctx = setup_batch_context(activate_agreement=False)
        assert ctx["agreement"]["status"] == "DRAFT"
        resp = api.release_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                     ctx["batch"]["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        after = validate_success(api.get_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], QM))
        assert after["status"] == "INTAKE", "Failed release leaves batch in INTAKE"

    def test_release_succeeds_when_tank_and_agreement_satisfied(self, api):
        """PRD §3.6: "A successful release cascades the tank from `AVAILABLE`
        to `RESERVED`, writes the batch's `id` into the tank's
        `occupied_by_batch_id`, and increments both the tank's and the batch's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/batch_release_depends_on_tank_and_pricing_agreement_state
        """
        ctx = setup_batch_context()
        batch = ctx["batch"]
        released = release_batch_job(ctx["customer"]["id"], batch)
        assert_batch_job(released)
        assert released["status"] == "RELEASED"
        assert released["version"] == batch["version"] + 1

        tank_after = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank_after["operational_state"] == "RESERVED"
        assert tank_after["occupied_by_batch_id"] == batch["id"]


class TestAgreementWindowBoundary:
    def test_release_at_exact_effective_to_rejected(self, api,
                                                    quality_manager_headers):
        """PRD §3.2: "the agreement is usable at the `effective_from` instant
        and remains usable up to, but not including, `effective_to`."
        PRD §3.6: "the pinned agreement `ACTIVE` with the logical clock inside
        its half-open window (else `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409)".

        Design: Difficulty/boundary_precision_check/pricing_agreement_window_half_open_boundary
        """
        ctx = setup_batch_context(pricing_overrides={
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-09-01T00:00:00Z"})
        # Advance the logical clock to exactly the exclusive window end.
        validate_success(api.set_clock("2026-09-01T00:00:00Z",
                                       quality_manager_headers))
        resp = api.release_batch_job(ctx["customer"]["id"], ctx["batch"]["id"],
                                     ctx["batch"]["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_release_one_second_before_effective_to_succeeds(
            self, api, quality_manager_headers):
        """PRD §3.2: "the agreement is usable at the `effective_from` instant
        and remains usable up to, but not including, `effective_to`."

        Design: Difficulty/boundary_precision_check/pricing_agreement_window_half_open_boundary
        """
        ctx = setup_batch_context(pricing_overrides={
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-09-01T00:00:00Z"})
        validate_success(api.set_clock("2026-08-31T23:59:59Z",
                                       quality_manager_headers))
        released = release_batch_job(ctx["customer"]["id"], ctx["batch"])
        assert released["status"] == "RELEASED", (
            "One second before the exclusive window end the agreement is usable")


class TestTankScheduleOverlap:
    def test_overlapping_window_release_rejected(self, api):
        """PRD §3.6: "no other non-terminal batch on the same tank with an
        overlapping scheduled window (else `ERR_TANK_SCHEDULE_OVERLAP`,
        HTTP 409)" and "with the half-open interval between them used for
        overlap testing".

        Design: Difficulty/resource_temporal_overlap/tank_schedule_overlap_half_open_interval
        """
        ctx = setup_released_batch(
            batch_overrides={"scheduled_start": "2026-11-05T08:00:00Z",
                             "scheduled_end": "2026-11-05T12:00:00Z"})
        # Second batch on the same tank, overlapping [10:00, 14:00).
        batch_b = create_batch_job(
            ctx["customer"]["id"], ctx["recipe"]["id"], ctx["agreement"]["id"],
            ctx["tank"]["id"], batch_size_l=100,
            scheduled_start="2026-11-05T10:00:00Z",
            scheduled_end="2026-11-05T14:00:00Z")
        resp = api.release_batch_job(ctx["customer"]["id"], batch_b["id"],
                                     batch_b["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_TANK_SCHEDULE_OVERLAP)
        after = validate_success(api.get_batch_job(
            ctx["customer"]["id"], batch_b["id"], QM))
        assert after["status"] == "INTAKE", "Rejected release leaves batch in INTAKE"

    def test_cancelled_batch_window_no_longer_blocks_release(self, api):
        """PRD §3.6: "no other non-terminal batch on the same tank with an
        overlapping scheduled window (else `ERR_TANK_SCHEDULE_OVERLAP`,
        HTTP 409)" — a CANCELLED batch is terminal, so its window no longer
        counts; and "Cancellation by a `BatchScheduler` is permitted only from
        `INTAKE` or `RELEASED`; from `RELEASED` the tank cascades from
        `RESERVED` back to `AVAILABLE` with `occupied_by_batch_id` cleared but
        `cleaning_state` and `last_product_ghs` untouched".

        Design: Difficulty/resource_temporal_overlap/tank_schedule_overlap_half_open_interval
        """
        ctx = setup_released_batch(
            batch_overrides={"scheduled_start": "2026-11-05T08:00:00Z",
                             "scheduled_end": "2026-11-05T12:00:00Z"})
        batch_b = create_batch_job(
            ctx["customer"]["id"], ctx["recipe"]["id"], ctx["agreement"]["id"],
            ctx["tank"]["id"], batch_size_l=100,
            scheduled_start="2026-11-05T10:00:00Z",
            scheduled_end="2026-11-05T14:00:00Z")

        cancelled = validate_success(api.cancel_batch_job(
            ctx["customer"]["id"], ctx["batch"]["id"], SCHED))
        assert cancelled["status"] == "CANCELLED"
        tank_after_cancel = validate_success(api.get_tank(ctx["tank"]["id"], QM))
        assert tank_after_cancel["operational_state"] == "AVAILABLE"
        assert tank_after_cancel["occupied_by_batch_id"] is None
        assert tank_after_cancel["cleaning_state"] == "CLEAN_VALIDATED"

        released = release_batch_job(ctx["customer"]["id"], batch_b)
        assert released["status"] == "RELEASED", (
            "The cancelled batch is terminal and no longer blocks the window")


class TestStateVersusCreditHoldOrdering:
    def _setup_suspended_customer_with_two_batches(self, api):
        """One batch already RELEASED, one still INTAKE, then suspend the
        customer (suspension does not require quiescence — only termination
            does, PRD §3.1)."""
        ctx = setup_released_batch()
        batch_b = create_batch_job(
            ctx["customer"]["id"], ctx["recipe"]["id"], ctx["agreement"]["id"],
            # Second tank so only the credit-standing rule can block batch_b.
            create_clean_validated_tank()["id"], batch_size_l=100,
            scheduled_start="2026-10-11T08:00:00Z",
            scheduled_end="2026-10-11T12:00:00Z")
        suspended = suspend_customer(ctx["customer"]["id"])
        assert suspended["status"] == "SUSPENDED"
        return ctx, batch_b

    def test_release_with_suspended_customer_rejected(self, api):
        """PRD §3.1: "a customer on credit hold or not currently `ACTIVE` can
        neither take new batch jobs into intake nor release them, and the
        rejection carries `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/release_blocked_state_vs_credit_hold_priority
        """
        ctx, batch_b = self._setup_suspended_customer_with_two_batches(api)
        # batch_b is in INTAKE (valid source state); only credit standing fails.
        resp = api.release_batch_job(ctx["customer"]["id"], batch_b["id"],
                                     batch_b["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)

    def test_state_error_reported_before_credit_hold(self, api):
        """PRD §2.9: "When several rules could reject the same request, the
        system evaluates them in a fixed order and reports the first failure."
        PRD §2.9: "then source-state validity for the requested transition
        (`ERR_INVALID_STATE`). Business rules follow, in this relative order:
        customer credit standing (`ERR_CUSTOMER_CREDIT_HOLD`)".

        Design: Difficulty/priority_pair_validation_conflict/release_blocked_state_vs_credit_hold_priority
        """
        ctx, _batch_b = self._setup_suspended_customer_with_two_batches(api)
        # ctx["batch"] is already RELEASED (source state invalid) AND the
        # customer is SUSPENDED (credit standing fails). State must win.
        batch = ctx["batch"]
        resp = api.release_batch_job(ctx["customer"]["id"], batch["id"],
                                     batch["version"], SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
