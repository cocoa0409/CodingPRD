"""Depth tests: state machines, cross-entity cascades, and conserved invariants.

Covers queue A rules: non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)


# =====================================================================
# non_linear_state_machine / contract_suspend_reactivate_cycle
# =====================================================================

def test_contract_suspend_then_reactivate_returns_to_active(api):
    """PRD §3.2: "The same activation capability also serves the recovery path: a contract in `SUSPENDED` returns to `ACTIVE`, which is permitted only from `SUSPENDED`, and which re-activates the property's route stops as described below."

    Design: Difficulty/non_linear_state_machine/contract_suspend_reactivate_cycle
    """
    ctx = fx.setup_route_with_stop(zip="50005",
                                   contract_overrides={"contract_price_cents": 10000,
                                                       "term_months": 3})
    con = ctx["contract"]
    cust = ctx["customer"]
    validate_success(api.suspend_contract(con["id"], TEST_USERS["dispatcher_headers"]))
    reactivated = validate_success(
        api.activate_contract(con["id"], fx.make_customer_headers(cust["id"]))
    )
    assert reactivated["status"] == "ACTIVE"


def test_reactivation_reflips_route_stop_active_true(api):
    """PRD §3.2: "Reactivation reverses this exactly — every `RouteStop` for that property has its `active` flag flipped back to true."

    After ACTIVE -> SUSPENDED (stop active false) -> ACTIVE, the stop's active is true.

    Design: Difficulty/non_linear_state_machine/contract_suspend_reactivate_cycle
    """
    ctx = fx.setup_route_with_stop(zip="50005",
                                   contract_overrides={"contract_price_cents": 10000,
                                                       "term_months": 3})
    con = ctx["contract"]
    cust = ctx["customer"]
    stop = ctx["stop"]
    api.suspend_contract(con["id"], TEST_USERS["dispatcher_headers"])
    api.activate_contract(con["id"], fx.make_customer_headers(cust["id"]))
    assert fx.get_route_stop(stop["id"])["active"] is True


# =====================================================================
# non_linear_state_machine / visit_branch_scheduled_to_skipped_vs_dispatched
# =====================================================================

def test_visit_branches_skipped_vs_dispatched_divergent_effects(api):
    """PRD §3.7: "Approval is a coupled transition: it moves the visit from `SCHEDULED`
    to `SKIPPED`, computes the request's `credit_cents`, sets the request's `status` to
    `APPROVED`, adds that credit to the customer's `wallet_credit_cents`, and subtracts
    the same credit from the contract's provisional `accrued_balance_cents`."
    PRD §3.5: "On a successful dispatch the visit's `status` becomes `DISPATCHED`, the
    visit's `equipment_id` is set to the selected asset, that equipment's `status`
    becomes `IN_SERVICE`."

    Two SCHEDULED SNOW visits: one approved-skip (-> SKIPPED, flat 1500 credit), one
    dispatched (-> DISPATCHED, equipment assigned and IN_SERVICE).

    Design: Difficulty/non_linear_state_machine/visit_branch_scheduled_to_skipped_vs_dispatched
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="60006",
        contract_overrides={"contract_price_cents": 30000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 3},
    )
    con = ctx["contract"]
    cust = ctx["customer"]
    eq = ctx["equipment"]
    skip_visit = fx.make_visit(con["id"], ctx["stop"]["id"], service_type="SNOW",
                               snow_depth_in=3.0, runtime_hours=2)
    disp_visit = fx.make_visit(con["id"], ctx["stop"]["id"], service_type="SNOW",
                               snow_depth_in=3.0, runtime_hours=2)
    skip = fx.make_skip_request(cust["id"], skip_visit["id"])
    fx.approve_skip(skip["id"])
    dispatched = fx.dispatch(disp_visit["id"])

    assert fx.get_visit(skip_visit["id"])["status"] == "SKIPPED"
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["equipment_id"] == eq["id"]
    assert fx.get_equipment(eq["id"])["status"] == "IN_SERVICE"
    assert fx.get_customer(cust["id"])["wallet_credit_cents"] == 1500


def test_visit_skip_branch_grants_snow_flat_credit(api):
    """PRD §3.7: "A skipped `SNOW` visit earns a flat credit of 1500 cents."

    The SKIPPED branch grants the flat SNOW credit, distinct from the DISPATCHED
    branch's equipment-assignment side effects.

    Design: Difficulty/non_linear_state_machine/visit_branch_scheduled_to_skipped_vs_dispatched
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="60006",
        contract_overrides={"contract_price_cents": 30000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 3},
    )
    skip_visit = fx.make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                               service_type="SNOW", snow_depth_in=3.0, runtime_hours=2)
    skip = fx.make_skip_request(ctx["customer"]["id"], skip_visit["id"])
    approved = fx.approve_skip(skip["id"])
    assert approved["credit_cents"] == 1500
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 1500


# =====================================================================
# transitive_cascade / complete_visit_cascades_to_equipment_maintenance_due
# =====================================================================

def test_complete_visit_cascades_equipment_to_maintenance_due(api):
    """PRD §3.6: "The platform adds the visit's `runtime_hours` to the equipment's
    `cumulative_runtime_hours`, increments its `dispatch_count_since_service` by one, and
    recomputes its `wear_score` using the actual variant ... If the recomputed
    `wear_score` is 100 or more, the equipment's `status` flips to `MAINTENANCE_DUE`;
    otherwise it returns to `IDLE`."

    Equipment age 24, completed LAWN visit runtime 44: wear = round(2*44 + 5*1 + 0.5*24)
    = 105 >= 100, so status -> MAINTENANCE_DUE and cumulative_runtime_hours == 44.

    Design: Difficulty/transitive_cascade/complete_visit_cascades_to_equipment_maintenance_due
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="70007",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 20000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 44},
        equipment_overrides={"equipment_type": "MOWER", "age_months": 24},
    )
    completed = validate_success(
        api.complete_visit(visit["id"], fx.make_crew_headers(ctx["crew"]["id"]))
    )
    assert completed["status"] == "COMPLETED"
    eq = fx.get_equipment(ctx["equipment"]["id"])
    assert eq["cumulative_runtime_hours"] == 44
    assert eq["wear_score"] == 105, f"wear should be 105, got {eq['wear_score']}"
    assert eq["status"] == "MAINTENANCE_DUE"


def test_complete_visit_increments_cumulative_runtime(api):
    """PRD §3.6: "The platform adds the visit's `runtime_hours` to the equipment's
    `cumulative_runtime_hours`, increments its `dispatch_count_since_service` by one."

    Primary cascade hop: the 44h visit lifts cumulative_runtime_hours from 0 to 44.

    Design: Difficulty/transitive_cascade/complete_visit_cascades_to_equipment_maintenance_due
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="70007",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 20000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 44},
        equipment_overrides={"equipment_type": "MOWER", "age_months": 24},
    )
    fx.complete(visit["id"], ctx["crew"]["id"])
    assert fx.get_equipment(ctx["equipment"]["id"])["cumulative_runtime_hours"] == 44


# =====================================================================
# transitive_cascade / close_season_cascades_to_invoice_then_wallet_debit
# =====================================================================

def test_close_season_cascades_invoice_then_wallet_debit(api):
    """PRD §3.2: "Then the platform synthesizes a `SeasonInvoice` for the contract by running the finalized billing replay of Section 3.7. Then — as a second-order effect of that invoice — the customer's `wallet_credit_cents` is debited by the amount the invoice consumed, mutating the `Customer` row."
    PRD §3.9: "The wallet amount actually applied is what the close-season cascade debits from the customer's `wallet_credit_cents`."

    Contract 40000, one LAWN skip approved (credit 801, wallet 801), no completed visits.
    subtotal = 40000 - 801 = 39199; tax = round(39199*0.07) = 2744;
    wallet applied = min(801, 41943) = 801; total = 39199 + 2744 - 801 - 0 = 41142;
    wallet debited to 0.

    Design: Difficulty/transitive_cascade/close_season_cascades_to_invoice_then_wallet_debit
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="80008",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    fx.approve_skip(skip["id"])
    closed = validate_success(api.close_season(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"]))
    assert closed["status"] == "CLOSED"
    inv = get_success_data(
        api.list_contract_invoices(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    )[0]
    assert inv["subtotal_cents"] == 39199, f"subtotal should be 39199, got {inv['subtotal_cents']}"
    assert inv["total_due_cents"] == 41142, f"total_due should be 41142, got {inv['total_due_cents']}"
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 0


def test_close_season_total_reflects_wallet_consumption(api):
    """PRD §3.9: "The platform then determines how much wallet credit to apply: the lesser of the customer's `wallet_credit_cents` and the sum of subtotal plus tax."

    Asserts the synthesized invoice's total_due (41142) reflects the 801-cent wallet
    consumption and that the wallet is fully drawn down.

    Design: Difficulty/transitive_cascade/close_season_cascades_to_invoice_then_wallet_debit
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="80008",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    fx.approve_skip(skip["id"])
    fx.api_client.close_season(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    inv = get_success_data(
        api.list_contract_invoices(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    )[0]
    assert inv["total_due_cents"] == 41142
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 0


# =====================================================================
# cross_entity_state_dependency / visit_dispatch_requires_contract_active
# =====================================================================

def test_dispatch_rejected_when_contract_suspended(api):
    """PRD §3.5: "Dispatch is permitted only when the visit is `SCHEDULED` and the owning contract of the visit's stop is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."

    Route has idle equipment, so only the contract-state gate can fail.

    Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_contract_active
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10303",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
        with_crew=False,
    )
    visit = fx.make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                          service_type="SNOW", snow_depth_in=3.0, runtime_hours=2)
    api.suspend_contract(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    resp = api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"


def test_dispatch_blocked_leaves_visit_scheduled(api):
    """PRD §3.5: "A service visit reaches `DISPATCHED ... Dispatch is permitted only when the visit is `SCHEDULED` and the owning contract of the visit's stop is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."

    Confirms the blocked dispatch leaves the visit untouched at SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_contract_active
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10303",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
        with_crew=False,
    )
    visit = fx.make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                          service_type="SNOW", snow_depth_in=3.0, runtime_hours=2)
    api.suspend_contract(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"


# =====================================================================
# cross_entity_state_dependency / visit_complete_requires_equipment_in_service
# =====================================================================

def test_complete_consumes_in_service_equipment_returns_idle(api):
    """PRD §3.6: "A visit may be completed only from `DISPATCHED`, and only when its
    assigned `equipment_id` is set and that equipment's `status` is still `IN_SERVICE`."
    PRD §3.6: "If the recomputed `wear_score` is 100 or more, the equipment's `status`
    flips to `MAINTENANCE_DUE`; otherwise it returns to `IDLE`."

    DISPATCHED LAWN visit runtime 5, equipment age 24 (IN_SERVICE): post-complete wear =
    round(2*5 + 5*1 + 0.5*24) = round(10 + 5 + 12) = 27 < 100, so equipment -> IDLE.

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_equipment_in_service
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="10404",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 20000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 5},
        equipment_overrides={"equipment_type": "MOWER", "age_months": 24},
    )
    completed = validate_success(
        api.complete_visit(visit["id"], fx.make_crew_headers(ctx["crew"]["id"]))
    )
    assert completed["status"] == "COMPLETED"
    eq = fx.get_equipment(ctx["equipment"]["id"])
    assert eq["wear_score"] == 27, f"wear should be 27, got {eq['wear_score']}"
    assert eq["status"] == "IDLE"


def test_complete_dispatched_visit_with_in_service_equipment_succeeds(api):
    """PRD §3.6: "A visit may be completed only from `DISPATCHED`, and only when its
    assigned `equipment_id` is set and that equipment's `status` is still `IN_SERVICE`."

    The completion path succeeds (status COMPLETED) precisely because the selected
    equipment is IN_SERVICE at completion time.

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_equipment_in_service
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="10404",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 20000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 5},
        equipment_overrides={"equipment_type": "MOWER", "age_months": 24},
    )
    assert fx.get_equipment(ctx["equipment"]["id"])["status"] == "IN_SERVICE"
    completed = fx.complete(visit["id"], ctx["crew"]["id"])
    assert completed["status"] == "COMPLETED"


# =====================================================================
# compensating_invariant / skip_then_close_conserves_wallet_credit
# =====================================================================

def test_skip_then_close_conserves_wallet_credit(api):
    """PRD §3.9: "The platform then determines how much wallet credit to apply: the lesser of the customer's `wallet_credit_cents` and the sum of subtotal plus tax ... The wallet amount actually applied is what the close-season cascade debits from the customer's `wallet_credit_cents`."

    Skip grants 801 to wallet; close-season consumes min(801, subtotal+tax) = 801,
    leaving wallet == 0 with no drift. subtotal = 40000 - 801 = 39199.

    Design: Difficulty/compensating_invariant/skip_then_close_conserves_wallet_credit
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="10707",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    fx.approve_skip(skip["id"])
    validate_success(api.close_season(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"]))
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 0
    inv = get_success_data(
        api.list_contract_invoices(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    )[0]
    assert inv["subtotal_cents"] == 39199


def test_skip_credit_recorded_in_wallet_before_close(api):
    """PRD §3.7: "adds that credit to the customer's `wallet_credit_cents`, and subtracts
    the same credit from the contract's provisional `accrued_balance_cents`."

    Before close-season, the approved LAWN skip credit (801) is fully present in the
    wallet — the conserved quantity that close-season then consumes.

    Design: Difficulty/compensating_invariant/skip_then_close_conserves_wallet_credit
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="10707",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    fx.approve_skip(skip["id"])
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 801


# =====================================================================
# compensating_invariant / maintenance_reset_conserves_dispatch_count_baseline
# =====================================================================

def test_maintenance_complete_resets_wear_baseline(api):
    """PRD §3.8: "the platform snapshots `runtime_at_last_service_hours` to the equipment's current `cumulative_runtime_hours`, resets `dispatch_count_since_service` to zero, recomputes the `wear_score` (which now collapses toward its age-only baseline), and sets the `status` to `IDLE`."

    Equipment reached MAINTENANCE_DUE (wear 105, cumulative 44, dispatch_count 1) via a
    44h completed visit. After start+complete maintenance: runtime_at_last_service == 44,
    dispatch_count == 0, wear = round(2*0 + 5*0 + 0.5*24) = 12, status IDLE.

    Design: Difficulty/compensating_invariant/maintenance_reset_conserves_dispatch_count_baseline
    """
    ctx, completed, eq = fx.setup_equipment_maintenance_due(zip="10808", age_months=24,
                                                            runtime_hours=44)
    assert eq["status"] == "MAINTENANCE_DUE"
    fx.api_client.start_maintenance(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    done = validate_success(
        api.complete_maintenance(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    )
    assert done["status"] == "IDLE"
    final = fx.get_equipment(ctx["equipment"]["id"])
    assert final["dispatch_count_since_service"] == 0
    assert final["runtime_at_last_service_hours"] == 44
    assert final["wear_score"] == 12, f"reset wear should be 12, got {final['wear_score']}"


def test_maintenance_complete_zeroes_dispatch_count(api):
    """PRD §3.8: "resets `dispatch_count_since_service` to zero, recomputes the
    `wear_score` (which now collapses toward its age-only baseline), and sets the
    `status` to `IDLE`."

    Confirms the conserved baseline: completing maintenance zeroes the dispatch counter
    so no residual dispatch drift survives the reset.

    Design: Difficulty/compensating_invariant/maintenance_reset_conserves_dispatch_count_baseline
    """
    ctx, completed, eq = fx.setup_equipment_maintenance_due(zip="10808", age_months=24,
                                                            runtime_hours=44)
    fx.api_client.start_maintenance(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    fx.api_client.complete_maintenance(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    final = fx.get_equipment(ctx["equipment"]["id"])
    assert final["dispatch_count_since_service"] == 0
    assert final["status"] == "IDLE"
