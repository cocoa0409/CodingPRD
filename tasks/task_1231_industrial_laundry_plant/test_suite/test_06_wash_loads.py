"""Wash load lifecycle: staging guards, hygienic-test discipline, the bounded
rewash escalation cycle, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_wash_load,
    setup_stop_received, create_batch, create_batch_with_items,
    create_batch_locked, create_batch_posted, stage_wash_load,
    drive_load_to_finished, get_wash_load, create_linen_category,
)

OPERATOR = TEST_USERS["plant_operator_headers"]

GOWN = {
    "code": "GOWN", "piece_weight_lb": 1.5, "wash_formula_code": "WF_STANDARD",
    "hygienic_test_required": True, "replacement_cost_cents": 3000,
    "cog_wash_rate_cents_per_lb": 200,
}


def _gown_ctx(pieces=20):
    """HEALTHCARE COG pipeline through a posted GOWN batch (test-required)."""
    ctx = setup_stop_received(
        category_overrides=dict(GOWN),
        customer_overrides={"customer_kind": "HEALTHCARE", "billing_mode": "COG"},
        stop_overrides={"declared_soiled_weight_lb": 30.0},
        carts=[{"cart_tag": "CART-1", "scale_weight_lb": 30.0}],
    )
    ctx["batch"] = create_batch_posted(
        ctx["stop"]["id"],
        [{"category_id": ctx["category"]["id"], "pieces": pieces}],
    )
    return ctx


def _drive_to_awaiting_test(load_id, api):
    validate_success(api.start_wash_load(load_id, OPERATOR), 200)
    validate_success(api.finish_cycle_wash_load(load_id, OPERATOR), 200)


class TestStagingGuards:
    def test_wash_start_requires_batch_locked(self, api):
        """PRD §3.4: "Two guards apply: the source batch must be `LOCKED` or `POSTED` — starting against an unresolved batch fails with `ERR_BATCH_NOT_LOCKED` — and the machine's half-open overlap guard of §2.8 must pass, with conflicts rejected as `ERR_MACHINE_TIME_OVERLAP`."

        Design: Difficulty/cross_entity_state_dependency/wash_start_requires_batch_locked
        """
        ctx = setup_stop_received()
        batch = create_batch_with_items(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 10},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        blocked = api.start_wash_load(load["id"], OPERATOR)
        validate_error(blocked, ApiErrorId.ERR_BATCH_NOT_LOCKED)

        lock_resp = api.lock_sort_batch(batch["id"], OPERATOR)
        validate_success(lock_resp, 200)
        started = validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        assert started["status"] == "RUNNING", (
            f"start must succeed once the batch is LOCKED, got {started['status']}"
        )

    def test_wash_start_allowed_when_batch_posted(self, api):
        """PRD §3.4: "Two guards apply: the source batch must be `LOCKED` or `POSTED` — starting against an unresolved batch fails with `ERR_BATCH_NOT_LOCKED` — and the machine's half-open overlap guard of §2.8 must pass, with conflicts rejected as `ERR_MACHINE_TIME_OVERLAP`."

        Design: Difficulty/cross_entity_state_dependency/wash_start_requires_batch_locked
        """
        ctx = setup_stop_received()
        batch = create_batch_posted(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 10},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        started = validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        assert started["status"] == "RUNNING", (
            f"a POSTED batch must also permit start, got {started['status']}"
        )

    def test_invalid_time_range_rejected_on_create(self, api):
        """PRD §2.8: "For both kinds of scheduling, `scheduled_end` must be strictly later than `scheduled_start`; a non-positive duration is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 422)."
        PRD §3.4: "The window must be strictly increasing, with violations rejected as `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/invalid_time_range_rejected_on_wash_load_create
        """
        ctx = setup_stop_received()
        batch = create_batch_locked(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 10},
        ])
        resp = api.create_wash_load(
            {
                "batch_id": batch["id"],
                "category_id": ctx["category"]["id"],
                "machine_id": "M1",
                "scheduled_start": "2026-05-02T09:00:00Z",
                "scheduled_end": "2026-05-02T08:00:00Z",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_category_not_in_batch_rejected(self, api):
        """PRD §3.4: "The category must be one actually present with disposition `ACCEPTED` in the linked batch; staging a load for a category the batch never accepted fails with `ERR_CATEGORY_NOT_IN_BATCH`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_wash_bypass
        """
        ctx = _gown_ctx(pieces=10)
        towel = create_linen_category(ctx["plant"]["id"], code="TOWEL")
        resp = api.create_wash_load(
            {
                "batch_id": ctx["batch"]["id"],
                "category_id": towel["id"],
                "machine_id": "M2",
                "scheduled_start": "2026-05-02T10:00:00Z",
                "scheduled_end": "2026-05-02T11:00:00Z",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_IN_BATCH)


class TestHygienicDiscipline:
    def test_bypass_rejected_when_test_required(self, api):
        """PRD §3.4: "When the category does not require testing, the operator instead bypasses testing, moving the load directly from `AWAITING_TEST` to `TESTED_PASS`; attempting the bypass on a category that does require testing fails with `ERR_TEST_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_wash_bypass
        """
        ctx = _gown_ctx(pieces=10)
        load = stage_wash_load(ctx["batch"]["id"], ctx["category"]["id"])
        _drive_to_awaiting_test(load["id"], api)
        resp = api.bypass_test_wash_load(load["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_TEST_REQUIRED)

    def test_record_test_rejected_when_not_required(self, api):
        """PRD §3.4: "When the category requires testing, the operator records the outcome: submitting an `outcome` of `PASS` moves the load from `AWAITING_TEST` to `TESTED_PASS`, and an `outcome` of `FAIL` moves it from `AWAITING_TEST` to `TESTED_FAIL`; attempting to record a test for a category that does not require one fails with `ERR_TEST_NOT_REQUIRED`."

        Design: Corner/errors/error_test_not_required_on_record_test
        """
        ctx = setup_stop_received()
        batch = create_batch_locked(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 10},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        _drive_to_awaiting_test(load["id"], api)
        resp = api.record_test_wash_load(load["id"], {"outcome": "PASS"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_REQUIRED)


class TestRewashCycle:
    def test_rewash_cycle_escalates_formula_to_top(self, api):
        """PRD §3.4: "Requesting a rewash moves a `TESTED_FAIL` load to `REWASH_PENDING`, but only while `rewash_count` remains below the plant-wide ceiling of 2; a load that has already been rewashed twice is rejected with `ERR_REWASH_LIMIT_REACHED`. Each granted rewash increments `rewash_count` by one and escalates the `formula_code` one step up the ladder: `WF_STANDARD` climbs to `WF_HEAVY_SOIL`, `WF_CHEM_DISINFECT` climbs to `WF_THERMAL_DISINFECT`, and `WF_THERMAL_DISINFECT` and `WF_HEAVY_SOIL` are already at the top and remain unchanged."

        Design: Difficulty/non_linear_state_machine/wash_load_rewash_cycle
        """
        ctx = _gown_ctx(pieces=20)
        load = stage_wash_load(ctx["batch"]["id"], ctx["category"]["id"])
        _drive_to_awaiting_test(load["id"], api)

        validate_success(
            api.record_test_wash_load(load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
        first = validate_success(api.request_rewash_wash_load(load["id"], OPERATOR), 200)
        assert first["rewash_count"] == 1
        assert first["formula_code"] == "WF_HEAVY_SOIL", (
            f"WF_STANDARD must escalate to WF_HEAVY_SOIL, got {first['formula_code']}"
        )
        assert first["status"] == "REWASH_PENDING"

        # Re-enter RUNNING (cycle) and fail a second time.
        validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.finish_cycle_wash_load(load["id"], OPERATOR), 200)
        validate_success(
            api.record_test_wash_load(load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
        second = validate_success(api.request_rewash_wash_load(load["id"], OPERATOR), 200)
        assert second["rewash_count"] == 2
        assert second["formula_code"] == "WF_HEAVY_SOIL", (
            "WF_HEAVY_SOIL is already at the top of the ladder and must remain"
        )

    def test_rewash_escalates_chem_disinfect_to_thermal(self, api):
        """PRD §3.4: "Each granted rewash increments `rewash_count` by one and escalates the `formula_code` one step up the ladder: `WF_STANDARD` climbs to `WF_HEAVY_SOIL`, `WF_CHEM_DISINFECT` climbs to `WF_THERMAL_DISINFECT`, and `WF_THERMAL_DISINFECT` and `WF_HEAVY_SOIL` are already at the top and remain unchanged."

        Design: Difficulty/non_linear_state_machine/wash_load_rewash_cycle
        """
        ctx = setup_stop_received(
            category_overrides={
                "code": "GOWN", "piece_weight_lb": 1.5,
                "wash_formula_code": "WF_CHEM_DISINFECT",
                "hygienic_test_required": True, "replacement_cost_cents": 3000,
                "cog_wash_rate_cents_per_lb": 200,
            },
            customer_overrides={"customer_kind": "HEALTHCARE"},
            stop_overrides={"declared_soiled_weight_lb": 30.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 30.0}],
        )
        batch = create_batch_posted(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 20},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        assert load["formula_code"] == "WF_CHEM_DISINFECT"
        _drive_to_awaiting_test(load["id"], api)
        validate_success(
            api.record_test_wash_load(load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
        rewashed = validate_success(api.request_rewash_wash_load(load["id"], OPERATOR), 200)
        assert rewashed["rewash_count"] == 1
        assert rewashed["formula_code"] == "WF_THERMAL_DISINFECT", (
            "WF_CHEM_DISINFECT must climb one step to WF_THERMAL_DISINFECT, "
            f"got {rewashed['formula_code']}"
        )

    def test_third_rewash_rejected_at_limit(self, api):
        """PRD §3.4: "Requesting a rewash moves a `TESTED_FAIL` load to `REWASH_PENDING`, but only while `rewash_count` remains below the plant-wide ceiling of 2; a load that has already been rewashed twice is rejected with `ERR_REWASH_LIMIT_REACHED`."

        Design: Corner/state_machines/wash_load_record_test_rewash_limit_reached
        """
        ctx = _gown_ctx(pieces=20)
        load = stage_wash_load(ctx["batch"]["id"], ctx["category"]["id"])
        _drive_to_awaiting_test(load["id"], api)
        for _ in range(2):
            validate_success(
                api.record_test_wash_load(load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
            validate_success(api.request_rewash_wash_load(load["id"], OPERATOR), 200)
            validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
            validate_success(api.finish_cycle_wash_load(load["id"], OPERATOR), 200)
        validate_success(
            api.record_test_wash_load(load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
        resp = api.request_rewash_wash_load(load["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_REWASH_LIMIT_REACHED)


class TestTerminalLockdown:
    def test_finished_load_rejects_further_transitions(self, api):
        """PRD §3.4: "Unloading is the exit for a passing load, moving it from `TESTED_PASS` to `FINISHED`."
        PRD §3.4: "A load may also be cancelled outright: from `STAGED` or from `REWASH_PENDING`, cancellation moves it to the terminal `CANCELLED` state with no further effect."
        PRD §2.9: "State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints."

        Design: Corner/state_machines/wash_load_terminal_finished_rejects_further_transitions
        """
        ctx = setup_stop_received()
        batch = create_batch_locked(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 10},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        finished = drive_load_to_finished(load["id"], hygienic_test_required=False)
        assert finished["status"] == "FINISHED"
        resp = api.cancel_wash_load(load["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
