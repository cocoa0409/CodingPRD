"""Productions, the build pipeline, and the build-budget conservation invariant."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_build_budget_conservation,
    assert_production,
    create_build_item,
    create_build_item_payload,
    create_production,
    create_production_payload,
    get_production,
    is_iso8601_timestamp,
    is_valid_uuid,
    transition_build_item,
    transition_production,
    validate_error,
    validate_success,
)

PM = TEST_USERS["production_manager_headers"]
ANY = TEST_USERS["any_headers"]
CD = TEST_USERS["casting_director_headers"]


class TestProductionCreate:
    def test_production_create_missing_required_field_rejected(self, api):
        """PRD §2.9: "Required fields must be present, enums must be in range, integers that must be positive must be positive, and a share percentage must be greater than zero and at most one hundred — else `ERR_VALIDATION` (400)."

        Design: Corner/entities/production_create_missing_required_field_rejected
        """
        payload = {
            "title": "No Budget Ballet",
            "work_type": "BALLET",
            "default_surtitle_language": "en",
        }
        resp = api.create_production(payload, PM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_production_create_computed_and_system_fields(self, api):
        """PRD §3.2: "The new production starts in `DESIGN`, its `build_cost_balance_cents` is initialized to the full `build_budget_cents`, and its `season_revenue_cents` starts at zero."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, assigned at creation and never modified afterwards."

        Design: Corner/entities/production_create_computed_and_system_fields
        """
        resp = api.create_production(
            create_production_payload(title="Swan Lake", build_budget_cents=100_000_000), PM
        )
        data = validate_success(resp, 201)
        assert_production(data)
        assert data["build_cost_balance_cents"] == 100_000_000, (
            "build_cost_balance_cents must initialize to the full build_budget_cents"
        )
        assert data["season_revenue_cents"] == 0, "season_revenue_cents starts at zero"
        assert data["status"] == "DESIGN", "new production starts in DESIGN"
        assert is_valid_uuid(data["id"]), "id is a server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int), "version is an integer common property"

    def test_production_get_not_found_returns_404(self, api):
        """PRD §2.9: "Path identifiers are validated left to right, then body foreign-key identifiers in their declared input order — else `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/production_get_not_found_returns_404
        """
        resp = api.get_production(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProductionLifecycle:
    def test_production_design_to_rehearsal_rejected(self, api):
        """PRD §3.2: "From `DESIGN` the production advances `DESIGN` → `BUILD` with no further conditions."
        PRD §2.9: "The target entity's current state must permit the requested transition or action. Where the state machine declares a specific code, that code is used ... otherwise the generic `ERR_INVALID_STATE_TRANSITION` (409) is used."

        Design: Corner/state_machines/production_design_to_rehearsal_rejected
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        resp = api.transition_production(production["id"], "REHEARSAL", PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_production(production["id"])
        assert after["status"] == "DESIGN", "rejected transition leaves the status unchanged"

    def test_build_to_rehearsal_blocked_by_undelivered_item_rejected(self, api):
        """PRD §3.2: "Moving `BUILD` → `REHEARSAL` requires that every build item of the production that is not `CANCELLED` has reached `DELIVERED` or `IN_USE` — a requirement vacuously satisfied when the production has no build items at all — and is otherwise rejected with `ERR_BUILD_ITEMS_NOT_DELIVERED`."

        Design: Corner/state_machines/build_to_rehearsal_blocked_by_undelivered_item_rejected
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        transition_production(production["id"], "BUILD")
        create_build_item(production["id"], item_kind="SET", name="Palace flat",
                          quoted_cost_cents=1_000_000)
        resp = api.transition_production(production["id"], "REHEARSAL", PM)
        validate_error(resp, ApiErrorId.ERR_BUILD_ITEMS_NOT_DELIVERED)
        after = get_production(production["id"])
        assert after["status"] == "BUILD", "rejected transition leaves the production in BUILD"

    def test_build_item_over_budget_rejected(self, api):
        """PRD §3.2: "The quoted cost must fit within the production's current `build_cost_balance_cents`; an order that would overdraw the budget is rejected with `ERR_BUILD_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/build_item_over_budget_rejected
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        resp = api.create_build_item(
            create_build_item_payload(
                production["id"], item_kind="SET", name="Full palace",
                quoted_cost_cents=120_000_000,
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BUILD_BUDGET_EXCEEDED)


class TestAccessRules:
    def test_role_permission_rejected_for_casting_director_creating_production(self, api):
        """PRD §2.1: "If the role is declared but is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.9: "Every request passes through a fixed validation pipeline. Earlier failures mask later ones: a request that fails step 1 never reaches step 2, a request that fails shape validation never reaches the fiscal check, and so on."

        Design: Corner/validations/role_priority_auth_before_existence_rejected
        """
        resp = api.create_production(
            create_production_payload(title="Swan Lake", build_budget_cents=100_000_000), CD
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_any_role_can_read(self, api):
        """PRD §2.1: "`Any` is a read-only role shared by every authenticated caller: all GET endpoints accept any declared role."

        Design: Corner/rbac/any_role_can_read
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        resp = api.get_production(production["id"], ANY)
        data = validate_success(resp, 200)
        assert data["title"] == "Swan Lake"
        assert data["id"] == production["id"]


class TestBuildBudgetConservation:
    def test_build_budget_order_built_rework_cancel_conservation(self, api):
        """PRD §3.2: "The production's `build_cost_balance_cents` is always the budget minus the committed amount, so balance plus committed equals `build_budget_cents` at all times; all arithmetic is exact integer cents."
        PRD §3.2: "When a built item proves defective, `BUILT` → `ORDERED` is a rework loop that releases the actual-cost basis back to the quoted basis by recomputing the balance."

        Order commits 30,000,000 (balance 70,000,000); BUILT at actual 32,000,000
        commits 32,000,000 (balance 68,000,000); rework to ORDERED releases back to
        the quoted basis (70,000,000); cancel then restores exactly 100,000,000.

        Design: Difficulty/compensating_invariant/build_budget_conservation_order_cancel
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        item = create_build_item(production["id"], item_kind="SET", name="Palace flat",
                                 quoted_cost_cents=30_000_000)

        after_order = get_production(production["id"])
        assert after_order["build_cost_balance_cents"] == 70_000_000, (
            "order commits the quoted cost: 100,000,000 - 30,000,000"
        )
        assert_build_budget_conservation(after_order, 30_000_000)

        transition_build_item(item["id"], "BUILT", actual_cost_cents=32_000_000)
        after_built = get_production(production["id"])
        assert after_built["build_cost_balance_cents"] == 68_000_000, (
            "BUILT commits the actual cost: 100,000,000 - 32,000,000"
        )
        assert_build_budget_conservation(after_built, 32_000_000)

        transition_build_item(item["id"], "ORDERED")
        after_rework = get_production(production["id"])
        assert after_rework["build_cost_balance_cents"] == 70_000_000, (
            "rework releases the actual-cost basis back to the quoted basis"
        )
        assert_build_budget_conservation(after_rework, 30_000_000)

        transition_build_item(item["id"], "CANCELLED")
        after_cancel = get_production(production["id"])
        assert after_cancel["build_cost_balance_cents"] == 100_000_000, (
            "cancel restores the conserved quantity exactly — no drift"
        )
        assert_build_budget_conservation(after_cancel, 0)

    def test_build_budget_order_then_cancel_restores_exactly(self, api):
        """PRD §3.2: "Cancelling from `ORDERED` releases the committed quoted cost entirely, again via recompute, so an item that is ordered and then cancelled leaves the balance exactly where it started."

        Design: Difficulty/compensating_invariant/build_budget_conservation_order_cancel
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        before = get_production(production["id"])
        assert before["build_cost_balance_cents"] == 100_000_000

        item = create_build_item(production["id"], item_kind="PROP", name="Chandelier",
                                 quoted_cost_cents=7_500_000)
        after_order = get_production(production["id"])
        assert after_order["build_cost_balance_cents"] == 92_500_000
        assert_build_budget_conservation(after_order, 7_500_000)

        cancelled = transition_build_item(item["id"], "CANCELLED")
        assert cancelled["status"] == "CANCELLED"
        after_cancel = get_production(production["id"])
        assert after_cancel["build_cost_balance_cents"] == 100_000_000, (
            "order-then-cancel leaves the balance exactly where it started"
        )
        assert_build_budget_conservation(after_cancel, 0)
