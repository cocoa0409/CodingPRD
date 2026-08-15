"""Commissioning events and service contracts (PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_commissioning_event,
    create_service_contract,
    get_success_data,
    make_customer_contact_headers,
    set_clock,
    setup_completed_commissioning,
    setup_commissioned_order,
    setup_customer,
    setup_delivered_order,
    setup_order,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
FSM = TEST_USERS["field_service_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/service_contract_flat_vs_tnm_divergence
# ---------------------------------------------------------------------------

def test_service_contract_flat_risk_premium_pricing(api):
    """PRD §3.9: "Under `FLAT_RISK_PREMIUM`, a locale multiplier applies — 1.25
    for `US_CA`, 1.10 for `DE`, and 1.0 otherwise — and the `annual_price_cents`
    is 1200 cents per kW-year times `nameplate_kw` times that multiplier,
    rounded half-up to whole cents; the `total_price_cents` is the annual figure
    times `term_years`."

    US_TX 500 kW 3 years: annual 1200*500*1.0 = 600000; total 1800000.

    Design: Difficulty/dual_variant_calc/service_contract_flat_vs_tnm_divergence
    """
    customer = setup_customer()
    order = setup_order(customer["id"], site_locale="US_TX")
    contract = create_service_contract(
        order["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=3, nameplate_kw=500,
    )
    assert contract["annual_price_cents"] == 600000
    assert contract["total_price_cents"] == 1800000
    assert contract["status"] == "QUOTED"


def test_service_contract_time_and_materials_pricing(api):
    """PRD §3.9: "Under `TIME_AND_MATERIALS_EV`, each preventive visit is priced
    as 6 hours of labor at 15000 cents per hour plus a 40000-cent parts
    allowance; the annual figure is that per-visit price times 4 visits per year
    times the 1.15 risk factor, rounded half-up to whole cents, and again
    `total_price_cents` is the annual figure times `term_years`."

    Per visit 6*15000 + 40000 = 130000; annual round(130000*4*1.15) = 598000;
    total over 3 years 1794000 — a different total than FLAT_RISK_PREMIUM on
    identical inputs.

    Design: Difficulty/dual_variant_calc/service_contract_flat_vs_tnm_divergence
    """
    customer = setup_customer()
    order = setup_order(customer["id"], site_locale="US_TX")
    contract_flat = create_service_contract(
        order["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=3, nameplate_kw=500,
    )
    contract_tnm = create_service_contract(
        order["id"], pricing_variant="TIME_AND_MATERIALS_EV",
        term_years=3, nameplate_kw=500,
    )
    assert contract_tnm["annual_price_cents"] == 598000
    assert contract_tnm["total_price_cents"] == 1794000
    assert contract_tnm["total_price_cents"] != contract_flat["total_price_cents"]


# ---------------------------------------------------------------------------
# Corner/state_machines/commissioning_full_path_and_order_close
# ---------------------------------------------------------------------------

def test_commissioning_full_path_and_order_close(api):
    """PRD §3.9: "The final word belongs to the customer: a `CustomerContact`
    accepts a `COMPLETED` event, and per §2.1 their `X-User-ID` must equal the
    order's `customer_id` or the call is rejected with `ERR_FORBIDDEN_ROLE`.
    Acceptance moves the event to the terminal `ACCEPTED` state and closes the
    order out — `build_status` `DELIVERED` → `COMMISSIONED`, and, if
    `commercial_status` is currently `INVOICED`, `INVOICED` → `CLOSED`."

    Design: Corner/state_machines/commissioning_full_path_and_order_close
    """
    ctx = setup_completed_commissioning()
    event = ctx["event"]
    assert event["status"] == "COMPLETED"
    contact = make_customer_contact_headers(ctx["customer"]["id"])
    accepted = validate_success(api_client.accept_commissioning_event(event["id"], contact))
    assert accepted["status"] == "ACCEPTED"
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "COMMISSIONED"
    assert order["commercial_status"] == "CLOSED"
    customer = get_success_data(api_client.get_customer(ctx["customer"]["id"], SALES))
    assert customer["credit_utilized_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/state_machines/service_contract_full_lifecycle_to_lapsed
# ---------------------------------------------------------------------------

def test_service_contract_full_lifecycle_to_lapsed(api):
    """PRD §3.9: "Activation — `BOUND` → `ACTIVE` — requires that a
    commissioning event for the order has reached `ACCEPTED` (else
    `ERR_COMMISSIONING_NOT_ACCEPTED`), and it stamps the schedule from the
    logical clock: `next_pm_due_date` becomes the current date plus
    `pm_interval_days`, and `end_date` becomes the current date plus
    `term_years` times 365 days. From `ACTIVE`, a `PlatformAdmin` runs the lapse
    check: when the logical-clock date is strictly past `next_pm_due_date` but
    not past `end_date`, the contract moves to `LAPSED`..."

    Activate at 2026-08-20 with pm_interval_days 30: PM due 2026-09-19, end
    2027-08-20. At clock 2026-09-20 (past PM due, within term) the contract
    lapses.

    Design: Corner/state_machines/service_contract_full_lifecycle_to_lapsed
    """
    ctx = setup_commissioned_order()
    contract = create_service_contract(
        ctx["order"]["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=1, nameplate_kw=500, pm_interval_days=30,
    )
    bound = get_success_data(api_client.bind_service_contract(contract["id"], SALES))
    assert bound["status"] == "BOUND"

    set_clock("2026-08-20T00:00:00Z")
    active = get_success_data(api_client.activate_service_contract(contract["id"], SALES))
    assert active["status"] == "ACTIVE"
    assert active["next_pm_due_date"] == "2026-09-19"
    assert active["end_date"] == "2027-08-20"

    set_clock("2026-09-20T00:00:00Z")
    lapsed = validate_success(api_client.lapse_check_service_contract(contract["id"], ADMIN))
    assert lapsed["status"] == "LAPSED"


# ---------------------------------------------------------------------------
# Corner/errors/lapse_check_not_lapsable_rejected
# ---------------------------------------------------------------------------

def test_lapse_check_not_lapsable_rejected(api):
    """PRD §3.9: "From `ACTIVE`, a `PlatformAdmin` runs the lapse check: when
    the logical-clock date is strictly past `next_pm_due_date` but not past
    `end_date`, the contract moves to `LAPSED`; when the date is strictly past
    `end_date`, it moves to `EXPIRED`; when neither condition holds, the check
    is rejected with `ERR_CONTRACT_NOT_LAPSABLE`."

    Activated at clock 2026-08-20 (PM due 2026-09-19); the check at the same
    clock date is neither condition, so it is rejected.

    Design: Corner/errors/lapse_check_not_lapsable_rejected
    """
    ctx = setup_commissioned_order()
    contract = create_service_contract(
        ctx["order"]["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=1, nameplate_kw=500, pm_interval_days=30,
    )
    get_success_data(api_client.bind_service_contract(contract["id"], SALES))
    set_clock("2026-08-20T00:00:00Z")
    get_success_data(api_client.activate_service_contract(contract["id"], SALES))

    resp = api_client.lapse_check_service_contract(contract["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_LAPSABLE)
    current = get_success_data(api_client.get_service_contract(contract["id"], SALES))
    assert current["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/validations/contract_activate_without_accepted_commissioning
# ---------------------------------------------------------------------------

def test_contract_activate_without_accepted_commissioning(api):
    """PRD §3.9: "Activation — `BOUND` → `ACTIVE` — requires that a
    commissioning event for the order has reached `ACCEPTED` (else
    `ERR_COMMISSIONING_NOT_ACCEPTED`)..."

    The order's commissioning event is COMPLETED but not yet ACCEPTED, so the
    activation fails.

    Design: Corner/validations/contract_activate_without_accepted_commissioning
    """
    ctx = setup_completed_commissioning()
    contract = create_service_contract(
        ctx["order"]["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=1, nameplate_kw=500,
    )
    get_success_data(api_client.bind_service_contract(contract["id"], SALES))
    resp = api_client.activate_service_contract(contract["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_COMMISSIONING_NOT_ACCEPTED)
    current = get_success_data(api_client.get_service_contract(contract["id"], SALES))
    assert current["status"] == "BOUND"


# ---------------------------------------------------------------------------
# Corner/validations/commissioning_complete_training_boundary
# ---------------------------------------------------------------------------

def test_commissioning_complete_training_boundary(api):
    """PRD §3.9: "Completion records the deliverables — `training_hours` and the
    `checklist_completed` flag — and is gated three ways, all under
    `ERR_TRAINING_INCOMPLETE` where training is concerned: the linked shipment
    must be `DELIVERED` (else `ERR_SHIPMENT_NOT_DELIVERED`),
    `checklist_completed` must be true, and `training_hours` must be at least
    2.0."

    1.9 training hours fails; exactly 2.0 passes.

    Design: Corner/validations/commissioning_complete_training_boundary
    """
    ctx = setup_delivered_order()
    event_low = create_commissioning_event(
        ctx["order"]["id"], ctx["shipment"]["id"], service_date="2026-08-20"
    )
    get_success_data(api_client.assign_commissioning_event(
        event_low["id"], {"engineer_id": "field-eng-low"}, FSM
    ))
    get_success_data(api_client.start_commissioning_event(event_low["id"], FSM))
    resp = api_client.complete_commissioning_event(
        event_low["id"], {"training_hours": 1.9, "checklist_completed": True}, FSM
    )
    validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE)

    event_ok = create_commissioning_event(
        ctx["order"]["id"], ctx["shipment"]["id"], service_date="2026-08-21"
    )
    get_success_data(api_client.assign_commissioning_event(
        event_ok["id"], {"engineer_id": "field-eng-ok"}, FSM
    ))
    get_success_data(api_client.start_commissioning_event(event_ok["id"], FSM))
    completed = validate_success(api_client.complete_commissioning_event(
        event_ok["id"], {"training_hours": 2.0, "checklist_completed": True}, FSM
    ))
    assert completed["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Corner/calculations/engineer_day_load_third_assignment_rejected
# ---------------------------------------------------------------------------

def test_engineer_day_load_third_assignment_rejected(api):
    """PRD §3.9: "The capacity rule guards an engineer's day: the count of that
    engineer's commissioning events on the same `service_date` whose status is
    `ASSIGNED`, `IN_PROGRESS`, or `COMPLETED` must be below 2 before the
    assignment — so a second same-day assignment is allowed and a third is
    rejected with `ERR_ENGINEER_DAY_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/engineer_day_load_third_assignment_rejected
    """
    ctx = setup_delivered_order()
    engineer = "field-eng-cap"
    for _ in range(2):
        event = create_commissioning_event(
            ctx["order"]["id"], ctx["shipment"]["id"], service_date="2026-08-20"
        )
        assigned = get_success_data(api_client.assign_commissioning_event(
            event["id"], {"engineer_id": engineer}, FSM
        ))
        assert assigned["status"] == "ASSIGNED"

    third = create_commissioning_event(
        ctx["order"]["id"], ctx["shipment"]["id"], service_date="2026-08-20"
    )
    resp = api_client.assign_commissioning_event(
        third["id"], {"engineer_id": engineer}, FSM
    )
    validate_error(resp, ApiErrorId.ERR_ENGINEER_DAY_CAPACITY_EXCEEDED)
    current = get_success_data(api_client.get_commissioning_event(third["id"], FSM))
    assert current["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Corner/endpoints/contract_cancel_quoted_and_bind_active_conflict
# ---------------------------------------------------------------------------

def test_contract_cancel_quoted_and_double_bind_rejected(api):
    """PRD §3.9: "A contract in `QUOTED` or `BOUND` may be cancelled outright by
    a `SalesEngineer`..."
    PRD §3.9: "Binding — `QUOTED` → `BOUND` — requires only that the order's
    `build_status` is not `CANCELLED` (else `ERR_INVALID_BUILD_STATE`)."
    Binding a contract already BOUND fails the from-state check with
    ERR_CONTRACT_STATE_INVALID (PRD §5).

    Design: Corner/endpoints/contract_cancel_quoted_and_bind_active_conflict
    """
    customer = setup_customer()
    order = setup_order(customer["id"])
    contract_a = create_service_contract(
        order["id"], pricing_variant="FLAT_RISK_PREMIUM", term_years=1, nameplate_kw=100
    )
    cancelled = validate_success(api_client.cancel_service_contract(contract_a["id"], SALES))
    assert cancelled["status"] == "CANCELLED"

    contract_b = create_service_contract(
        order["id"], pricing_variant="TIME_AND_MATERIALS_EV", term_years=2, nameplate_kw=100
    )
    bound = validate_success(api_client.bind_service_contract(contract_b["id"], SALES))
    assert bound["status"] == "BOUND"
    resp = api_client.bind_service_contract(contract_b["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_STATE_INVALID)


# ---------------------------------------------------------------------------
# Corner/rbac/customer_contact_cannot_accept_others_commissioning
# ---------------------------------------------------------------------------

def test_customer_contact_cannot_accept_others_commissioning(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerContact`, `X-User-ID` is the
    `id` of the acting `CustomerAccount`; ownership checks on any resource that
    references a `CustomerAccount` compare the resource's foreign-key field to
    `X-User-ID` — concretely, a `CustomerContact` accepting a commissioning
    event must present an `X-User-ID` equal to the order's `customer_id`, and
    any other value is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_contact_cannot_accept_others_commissioning
    """
    ctx = setup_completed_commissioning()
    other_customer = setup_customer(name="Other Account")
    contact_b = make_customer_contact_headers(other_customer["id"])
    resp = api_client.accept_commissioning_event(ctx["event"]["id"], contact_b)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    current = get_success_data(api_client.get_commissioning_event(ctx["event"]["id"], FSM))
    assert current["status"] == "COMPLETED"
