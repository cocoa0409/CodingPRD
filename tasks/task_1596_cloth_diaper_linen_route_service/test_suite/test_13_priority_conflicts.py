"""Validation-pipeline priority: when one request violates several rules, the
earliest failing stage answers (PRD 2.10)."""
from test_helpers import (
    ApiErrorId,
    create_swap,
    customer_event,
    intake_event,
    read_batch,
    read_pool,
    setup_active_subscription,
    setup_batch_validating,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, create_pool, make_plant_operator_headers


class TestSwapApproveStateBeatsShortfall:
    def _setup_suspended_with_empty_target_pool(self):
        """Swap MEDIUM -> LARGE in REQUESTED, created while the subscription was
        ACTIVE; the customer is then suspended; the LARGE pool has zero units."""
        ctx = setup_active_subscription()
        pool_l = create_pool("LARGE")  # no ACQUIRE: available_units 0
        swap = create_swap(ctx["subscription"]["id"], "LARGE", ctx["customer_headers"])
        customer_event(ctx["customer"]["id"], "SUSPEND")
        ctx.update({"pool_l": pool_l, "swap": swap})
        return ctx

    def test_state_error_precedes_pool_shortfall(self, api):
        """PRD 2.10: "Every request passes through a fixed validation pipeline, and
        the order matters: a request that would fail several checks is rejected with
        the error from the earliest failing stage."
        PRD 2.10: "Business rules in their declared priority — first the
        subscription-active guard (`ERR_SUBSCRIPTION_NOT_ACTIVE`) and the route-lock
        guard (`ERR_ROUTE_LOCKED`); then plant safety
        (`ERR_SANITIZATION_NOT_VALIDATED` before `ERR_SEGREGATION_OF_DUTIES` before
        `ERR_REWASH_LIMIT_EXCEEDED`); then temporal rules
        (`ERR_PAUSE_NOTICE_TOO_SHORT`, `ERR_PAUSE_WINDOW_INVALID`,
        `ERR_CUTOFF_PASSED`, `ERR_INVOICE_NOT_PAST_DUE`,
        `ERR_BILLING_CYCLE_CLOSED`); then constraint rules (`ERR_PAUSE_OVERLAP`,
        `ERR_STOP_WINDOW_CONFLICT`, `ERR_ROUTE_CAPACITY_EXCEEDED`,
        `ERR_SIZE_TRANSITION_INVALID`, `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`,
        `ERR_ZONE_NOT_SERVICEABLE`); then referential rules
        (`ERR_RETURN_COUNT_MISMATCH`, `ERR_WEIGHT_VARIANCE_EXCEEDED`,
        `ERR_KIT_NOT_RETURNED`); and finally the fiscal guards
        (`ERR_INVENTORY_SHORTFALL`, `ERR_DEPOSIT_INSUFFICIENT`,
        `ERR_INVOICE_UNPAID`)."

        Design: Difficulty/priority_pair_validation_conflict/swap_approve_state_priority_beats_pool_shortfall
        """
        ctx = self._setup_suspended_with_empty_target_pool()
        # The subscription is SUSPENDED (state guard) and the LARGE pool has
        # available_units 0 (fiscal guard): the state guard must answer.
        response = _client.approve_swap(
            ctx["swap"]["id"],
            {"expected_inventory_pool_version": ctx["pool_l"]["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)

    def test_rejected_approve_leaves_swap_and_pool_untouched(self, api):
        """PRD 3.6: "Beyond the state and subscription checks, approval requires the
        target pool's `available_units` to be at least `quantity`
        (`ERR_INVENTORY_SHORTFALL`). Approval moves `quantity` units in the target
        pool from `on_hand_units` into `reserved_units`, increments the pool's
        `version`, and moves the swap `REQUESTED` → `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/swap_approve_state_priority_beats_pool_shortfall
        """
        ctx = self._setup_suspended_with_empty_target_pool()
        response = _client.approve_swap(
            ctx["swap"]["id"],
            {"expected_inventory_pool_version": ctx["pool_l"]["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)

        swap = validate_success(_client.get_swap(ctx["swap"]["id"], ADMIN))
        assert swap["status"] == "REQUESTED", "a rejected approve leaves the swap REQUESTED"
        pool = read_pool(ctx["pool_l"]["id"])
        assert pool["available_units"] == 0
        assert pool["reserved_units"] == 0, "no reservation is taken on a rejected approve"


class TestReleaseSanitizationBeatsIntakeCleanliness:
    def _setup_failed_validation_with_disputed_intake(self):
        """Batch VALIDATING with validation_passed false (dwell one second short);
        its loaded intake is disputed after loading, so both the safety check and
        the referential check would fail. op-1 started, op-2 validated, so the
        segregation-of-duties rung is satisfied and cannot mask the outcome."""
        ctx = setup_batch_validating(
            starter_headers=make_plant_operator_headers("op-1"),
            validator_headers=make_plant_operator_headers("op-2"),
            peak_temp_celsius=71,
            dwell_seconds=179,
            chlorine_ppm=100,
            batch_soil="NORMAL",
            water_hardness="MEDIUM",
        )
        assert ctx["batch"]["validation_passed"] is False
        intake_event(ctx["intake"]["id"], "DISPUTE")
        return ctx

    def test_sanitization_error_precedes_intake_referential(self, api):
        """PRD 3.5: "Release is the most guarded transition in the plant, with three
        checks evaluated in order: `validation_passed` must be true
        (`ERR_SANITIZATION_NOT_VALIDATED`); segregation of duties requires
        `validated_by` to differ from `wash_started_by`
        (`ERR_SEGREGATION_OF_DUTIES`); and every loaded intake must still be
        `RECONCILED` or `RESOLVED` (`ERR_WEIGHT_VARIANCE_EXCEEDED`)."
        PRD 2.10: "batch release checks sanitization, then segregation of duties,
        then intake cleanliness."

        Design: Difficulty/priority_pair_validation_conflict/release_sanitization_priority_beats_intake_referential
        """
        ctx = self._setup_failed_validation_with_disputed_intake()
        response = _client.batch_event(
            ctx["batch"]["id"], {"event_type": "RELEASE"},
            make_plant_operator_headers("op-2"),
        )
        validate_error(response, ApiErrorId.ERR_SANITIZATION_NOT_VALIDATED.value)

    def test_rejected_release_leaves_batch_validating(self, api):
        """PRD 3.5: "and every loaded intake must still be `RECONCILED` or
        `RESOLVED` (`ERR_WEIGHT_VARIANCE_EXCEEDED`). Release returns `verified_count`
        units per intake from `in_wash_units` to `on_hand_units` in each intake's size
        pool and moves the batch to the terminal `RELEASED` state."

        Design: Difficulty/priority_pair_validation_conflict/release_sanitization_priority_beats_intake_referential
        """
        ctx = self._setup_failed_validation_with_disputed_intake()
        response = _client.batch_event(
            ctx["batch"]["id"], {"event_type": "RELEASE"},
            make_plant_operator_headers("op-2"),
        )
        validate_error(response, ApiErrorId.ERR_SANITIZATION_NOT_VALIDATED.value)

        batch = read_batch(ctx["batch"]["id"])
        assert batch["status"] == "VALIDATING", (
            "a rejected RELEASE leaves the batch in VALIDATING"
        )
        pool = read_pool(ctx["pool"]["id"])
        assert pool["in_wash_units"] == 80, "no units move back to the shelf on a rejected release"
