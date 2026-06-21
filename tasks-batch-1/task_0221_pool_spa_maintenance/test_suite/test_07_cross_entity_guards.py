"""Cross-entity state dependencies and validation-priority conflicts
(PRD §2.9, §3.3, §3.5, §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer, create_pool, create_plan, create_route, create_visit,
    create_seasonal_event_payload, create_work_order_payload,
    create_invoice_payload, complete_payload,
    ApiErrorId, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_complete_visit_blocked_when_pool_closed(api):
    """PRD §3.5: "Completion is permitted only when the visit is `SCHEDULED`, the
    owning pool's `service_status` is `OPEN` or `GREEN_RECOVERY`, and the route
    carrying the visit is `DISPATCHED`; a completion attempted against a visit not in
    a completable state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_pool_open
    """
    # Plan ACTIVE, route DISPATCHED, one SCHEDULED visit, but pool never opened (CLOSED).
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = get_success_data(api.activate_service_plan(
        create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)["id"], AM))
    route = create_route(capacity_visits=5)
    visit = create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    get_success_data(api.dispatch_route(route["id"], RM))
    resp = api.complete_visit(visit["id"], complete_payload(green_pool=False), FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_visit(visit["id"], RM))
    assert after["status"] == "SCHEDULED"


def test_complete_visit_succeeds_once_pool_open(api):
    """PRD §3.5: "Completion is permitted only when the visit is `SCHEDULED`, the
    owning pool's `service_status` is `OPEN` or `GREEN_RECOVERY`, and the route
    carrying the visit is `DISPATCHED`".

    Positive control for the cross-entity dependency: the same visit that is blocked
    while the pool is CLOSED completes successfully once the pool is OPEN.

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_pool_open
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = get_success_data(api.activate_service_plan(
        create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)["id"], AM))
    route = create_route(capacity_visits=5)
    visit = create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    # Open the pool, then dispatch.
    se = get_success_data(api.create_seasonal_event(pool["id"], create_seasonal_event_payload("OPEN"), RM))
    get_success_data(api.apply_seasonal_event(se["id"], RM))
    get_success_data(api.dispatch_route(route["id"], RM))
    resp = api.complete_visit(visit["id"], complete_payload(green_pool=False), FT)
    data = validate_success(resp)
    assert data["status"] == "COMPLETED"


def test_activate_plan_blocked_for_suspended_customer(api):
    """PRD §3.3: "Bringing a plan into service moves it from `DRAFT` to `ACTIVE`, and
    is allowed only when the owning customer's `account_status` is `ACTIVE`;
    activating a plan for a suspended customer is rejected through the state
    machinery as an invalid operation."

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_customer_active
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)
    get_success_data(api.suspend_customer(customer["id"], AM))
    resp = api.activate_service_plan(plan["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_service_plan(plan["id"], AM))
    assert after["status"] == "DRAFT"


def test_activate_plan_succeeds_for_active_customer(api):
    """PRD §3.3: "Bringing a plan into service moves it from `DRAFT` to `ACTIVE`, and
    is allowed only when the owning customer's `account_status` is `ACTIVE`".

    Positive control: a DRAFT plan on an ACTIVE customer activates to ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_customer_active
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)
    resp = api.activate_service_plan(plan["id"], AM)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"


def test_seasonal_open_blocked_by_critical_work_order(api):
    """PRD §3.8: "Opening is blocked while the pool has any work order of `CRITICAL`
    severity still in `OPEN`, `DIAGNOSED`, `AWAITING_APPROVAL`, or `ON_HOLD`; an open
    attempted against such an unresolved critical repair is rejected with
    `ERR_CRITICAL_REPAIR_BLOCKS_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/safety_before_temporal_on_seasonal_apply
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    get_success_data(api.create_work_order(
        create_work_order_payload(pool["id"], component="PUMP", severity="CRITICAL"), FT))
    se = get_success_data(api.create_seasonal_event(
        pool["id"], create_seasonal_event_payload("OPEN"), RM))
    resp = api.apply_seasonal_event(se["id"], RM)
    validate_error(resp, ApiErrorId.ERR_CRITICAL_REPAIR_BLOCKS_OPEN.value)
    after = validate_success(api.get_pool(pool["id"], AM))
    assert after["service_status"] == "CLOSED"


def test_critical_block_leaves_seasonal_event_requested(api):
    """PRD §3.8: "Applying a requested event drives the corresponding pool posture
    change as a cascade and increments both the event's `version` and the pool's
    `version`; the underlying pool transition's own preconditions must hold for the
    apply to succeed."
    PRD §3.8: "an open attempted against such an unresolved critical repair is
    rejected with `ERR_CRITICAL_REPAIR_BLOCKS_OPEN`."

    When the safety block fires, the apply does not succeed, so the seasonal event
    remains REQUESTED rather than APPLIED.

    Design: Difficulty/priority_pair_validation_conflict/safety_before_temporal_on_seasonal_apply
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    get_success_data(api.create_work_order(
        create_work_order_payload(pool["id"], component="HEATER", severity="CRITICAL"), FT))
    se = get_success_data(api.create_seasonal_event(
        pool["id"], create_seasonal_event_payload("OPEN"), RM))
    resp = api.apply_seasonal_event(se["id"], RM)
    validate_error(resp, ApiErrorId.ERR_CRITICAL_REPAIR_BLOCKS_OPEN.value)
    after = validate_success(api.get_seasonal_event(se["id"], RM))
    assert after["status"] == "REQUESTED"


def test_pay_draft_invoice_rejected_invalid_state(api):
    """PRD §2.9: "State validity is fifth: an operation invoked against a resource
    not in a state from which the transition is defined fails with
    `ERR_INVALID_STATE`. Only after these gates do the operation-specific business
    constraints (interval validity, slot overlap, capacity, repair/seasonal blocks,
    billing rules, the OCC check, and finally generic request-schema validation)
    apply."
    PRD §3.10: "Paying an issued invoice advances it from `ISSUED` to `PAID`".

    The state gate (P5 ERR_INVALID_STATE) pre-empts the fiscal pathway: a DRAFT
    invoice is not in a state from which a downstream transition is defined, so the
    state check fires before any fiscal billing rule is reached.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_invoice_issue
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = get_success_data(api.activate_service_plan(
        create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)["id"], AM))
    route = create_route(capacity_visits=5)
    visit = create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    se = get_success_data(api.create_seasonal_event(pool["id"], create_seasonal_event_payload("OPEN"), RM))
    get_success_data(api.apply_seasonal_event(se["id"], RM))
    get_success_data(api.dispatch_route(route["id"], RM))
    validate_success(api.complete_visit(visit["id"], complete_payload(green_pool=False), FT))
    inv = get_success_data(api.create_invoice(create_invoice_payload(pool["id"], visit_id=visit["id"]), AM))
    # Invoice is DRAFT; pay is undefined from DRAFT -> state gate fires.
    resp = api.pay_invoice(inv["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reissue_already_issued_invoice_rejected_invalid_state(api):
    """PRD §2.9: "State validity is fifth: an operation invoked against a resource
    not in a state from which the transition is defined fails with
    `ERR_INVALID_STATE`."
    PRD §3.10: "Issuing a draft invoice advances it from `DRAFT` to `ISSUED`."

    Issue is defined only from DRAFT; re-issuing an ISSUED invoice fails the state
    gate (P5) before any fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_invoice_issue
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = get_success_data(api.activate_service_plan(
        create_plan(pool["id"], plan_type="ONE_TIME", frequency="NONE", per_visit_rate_cents=8000)["id"], AM))
    route = create_route(capacity_visits=5)
    visit = create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    se = get_success_data(api.create_seasonal_event(pool["id"], create_seasonal_event_payload("OPEN"), RM))
    get_success_data(api.apply_seasonal_event(se["id"], RM))
    get_success_data(api.dispatch_route(route["id"], RM))
    validate_success(api.complete_visit(visit["id"], complete_payload(green_pool=False), FT))
    inv = get_success_data(api.create_invoice(create_invoice_payload(pool["id"], visit_id=visit["id"]), AM))
    validate_success(api.issue_invoice(inv["id"], AM))  # first issue (amount 8000) succeeds
    resp = api.issue_invoice(inv["id"], AM)  # re-issue from ISSUED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
