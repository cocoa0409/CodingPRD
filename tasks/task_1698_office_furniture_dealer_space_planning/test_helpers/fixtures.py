"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(the test harness restarts the server before every test, so nothing carries
over). Setup calls use the lenient get_success_data() validator so that a
failed precondition surfaces as a clear "Setup step failed" error.

Segregation-of-duties user ids (PRD section 3.3 / 3.9): contracts are
created by USER_ACCOUNT_EXECUTIVE and activated by USER_CONTRACTS_OFFICER;
lots are appraised by USER_LIQUIDATION_APPRAISER and credited by
USER_FINANCE_MANAGER. These differ by construction in every helper below.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_crew_payload,
    create_customer_payload,
    create_dealership_payload,
    create_install_event_payload,
    create_liquidation_lot_payload,
    create_order_line_payload,
    create_pricing_contract_payload,
    create_product_series_payload,
    create_project_order_payload,
    create_punch_item_payload,
    create_space_plan_payload,
    create_staging_reservation_payload,
    create_typical_payload,
)
from .test_users import (
    USER_ACCOUNT_EXECUTIVE,
    USER_CLAIMS_COORDINATOR,
    USER_CLIENT_APPROVER,
    USER_CONTRACTS_OFFICER,
    USER_DEALER_ADMIN,
    USER_DESIGNER,
    USER_FINANCE_MANAGER,
    USER_LIQUIDATION_APPRAISER,
    USER_MANUFACTURER_REP,
    USER_PROJECT_MANAGER,
    USER_WAREHOUSE_LEAD,
    make_account_executive_headers,
    make_claims_coordinator_headers,
    make_client_approver_headers,
    make_contracts_officer_headers,
    make_dealer_admin_headers,
    make_designer_headers,
    make_finance_manager_headers,
    make_liquidation_appraiser_headers,
    make_manufacturer_rep_headers,
    make_project_manager_headers,
    make_warehouse_lead_headers,
)

ADMIN = make_dealer_admin_headers(USER_DEALER_ADMIN)
AE = make_account_executive_headers(USER_ACCOUNT_EXECUTIVE)
CO = make_contracts_officer_headers(USER_CONTRACTS_OFFICER)
DESIGNER = make_designer_headers(USER_DESIGNER)
APPROVER = make_client_approver_headers(USER_CLIENT_APPROVER)
PM = make_project_manager_headers(USER_PROJECT_MANAGER)
WH = make_warehouse_lead_headers(USER_WAREHOUSE_LEAD)
CC = make_claims_coordinator_headers(USER_CLAIMS_COORDINATOR)
REP = make_manufacturer_rep_headers(USER_MANUFACTURER_REP)
APPRAISER = make_liquidation_appraiser_headers(USER_LIQUIDATION_APPRAISER)
FINANCE = make_finance_manager_headers(USER_FINANCE_MANAGER)


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_dealership(overrides=None) -> dict:
    payload = create_dealership_payload(**(overrides or {}))
    return get_success_data(api_client.create_dealership(payload, ADMIN))


def create_customer(dealership_id, overrides=None) -> dict:
    payload = create_customer_payload(dealership_id, **(overrides or {}))
    return get_success_data(api_client.create_customer(payload, AE))


def create_contract(customer_id, overrides=None, creator_headers=None) -> dict:
    """Create a DRAFT contract; creator defaults to USER_ACCOUNT_EXECUTIVE."""
    payload = create_pricing_contract_payload(customer_id, **(overrides or {}))
    return get_success_data(
        api_client.create_pricing_contract(payload, creator_headers or AE)
    )


def activate_contract(contract_id, officer_headers=None) -> dict:
    """Activate a DRAFT contract as a ContractsOfficer other than the creator."""
    return get_success_data(
        api_client.activate_contract(contract_id, officer_headers or CO)
    )


def create_active_contract(customer_id, overrides=None) -> dict:
    contract = create_contract(customer_id, overrides)
    return activate_contract(contract["id"])


def create_plan(customer_id, overrides=None) -> dict:
    payload = create_space_plan_payload(customer_id, **(overrides or {}))
    return get_success_data(api_client.create_space_plan(payload, DESIGNER))


def create_approved_plan(customer_id, plan_overrides=None, typical_overrides=None):
    """Plan with one typical, submitted and approved. Returns (plan, typical)."""
    plan = create_plan(customer_id, plan_overrides)
    typical = get_success_data(
        api_client.create_typical(
            create_typical_payload(plan["id"], **(typical_overrides or {})), DESIGNER
        )
    )
    get_success_data(api_client.submit_plan(plan["id"], DESIGNER))
    plan = get_success_data(api_client.approve_plan(plan["id"], APPROVER))
    return plan, typical


def create_series(dealership_id, overrides=None) -> dict:
    payload = create_product_series_payload(dealership_id, **(overrides or {}))
    return get_success_data(api_client.create_product_series(payload, ADMIN))


def create_crew(dealership_id, overrides=None) -> dict:
    payload = create_crew_payload(dealership_id, **(overrides or {}))
    return get_success_data(api_client.create_crew(payload, ADMIN))


def create_order(customer_id, contract_id, plan_id, overrides=None) -> dict:
    payload = create_project_order_payload(
        customer_id, contract_id, plan_id, **(overrides or {})
    )
    return get_success_data(api_client.create_project_order(payload, AE))


def add_line(order_id, series_id, overrides=None) -> dict:
    payload = create_order_line_payload(order_id, series_id, **(overrides or {}))
    return get_success_data(api_client.create_order_line(payload, AE))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: the standard order pipeline
# ---------------------------------------------------------------------------

def setup_catalog(
    dealership_overrides=None,
    customer_overrides=None,
    contract_overrides=None,
    plan_overrides=None,
    typical_overrides=None,
    series_overrides=None,
    activate=True,
    approve_plan=True,
) -> SimpleNamespace:
    """Dealership + customer + contract + plan(+typical) + series.

    By default the contract is ACTIVE and the plan is APPROVED so the
    pipeline is order-ready; pass activate=False / approve_plan=False to
    hold those back.
    """
    dealership = create_dealership(dealership_overrides)
    customer = create_customer(dealership["id"], customer_overrides)
    if activate:
        contract = create_active_contract(customer["id"], contract_overrides)
    else:
        contract = create_contract(customer["id"], contract_overrides)
    if approve_plan:
        plan, typical = create_approved_plan(
            customer["id"], plan_overrides, typical_overrides
        )
    else:
        plan = create_plan(customer["id"], plan_overrides)
        typical = get_success_data(
            api_client.create_typical(
                create_typical_payload(plan["id"], **(typical_overrides or {})),
                DESIGNER,
            )
        )
    series = create_series(dealership["id"], series_overrides)
    return SimpleNamespace(
        dealership=dealership,
        customer=customer,
        contract=contract,
        plan=plan,
        typical=typical,
        series=series,
    )


def setup_draft_order(ctx=None, order_overrides=None, line_overrides=None, **catalog_kw) -> SimpleNamespace:
    """Catalog + DRAFT order with one OPEN line."""
    ctx = ctx or setup_catalog(**catalog_kw)
    order = create_order(
        ctx.customer["id"], ctx.contract["id"], ctx.plan["id"], order_overrides
    )
    line = add_line(order["id"], ctx.series["id"], line_overrides)
    ctx.order = order
    ctx.line = line
    return ctx


def setup_submitted_order(ctx=None, **kw) -> SimpleNamespace:
    ctx = setup_draft_order(ctx, **kw) if ctx is None or not hasattr(ctx, "order") else ctx
    ctx.order = get_success_data(api_client.submit_order(ctx.order["id"], AE))
    ctx.line = get_success_data(api_client.get_order_line(ctx.line["id"], AE))
    return ctx


def setup_acknowledged_order(ctx=None, **kw) -> SimpleNamespace:
    ctx = setup_submitted_order(ctx, **kw)
    ctx.order = get_success_data(api_client.acknowledge_order(ctx.order["id"], REP))
    ctx.line = get_success_data(api_client.get_order_line(ctx.line["id"], AE))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: crews, events, staging
# ---------------------------------------------------------------------------

def add_crew(ctx, overrides=None) -> dict:
    ctx.crew = create_crew(ctx.dealership["id"], overrides)
    return ctx.crew


def add_event(ctx, overrides=None) -> dict:
    """Create a TENTATIVE install event on ctx.order with ctx.crew."""
    crew = getattr(ctx, "crew", None) or add_crew(ctx)
    payload = create_install_event_payload(
        ctx.order["id"], crew["id"], **(overrides or {})
    )
    ctx.event = get_success_data(api_client.create_install_event(payload, PM))
    return ctx.event


def add_confirmed_event(ctx, overrides=None) -> dict:
    event = add_event(ctx, overrides)
    ctx.event = get_success_data(api_client.confirm_event(event["id"], PM))
    return ctx.event


def add_staging_reservation(ctx, overrides=None) -> dict:
    payload = create_staging_reservation_payload(
        ctx.line["id"], **(overrides or {})
    )
    ctx.reservation = get_success_data(api_client.create_staging_reservation(payload, PM))
    return ctx.reservation


def receive_units(ctx, reservation_id=None, received_units=5, condition="GOOD") -> dict:
    rid = reservation_id or ctx.reservation["id"]
    return get_success_data(
        api_client.receive_staging(
            rid, {"received_units": received_units, "condition": condition}, WH
        )
    )


def setup_delivered_order(ctx=None, **kw) -> SimpleNamespace:
    """ACKNOWLEDGED order whose single line is fully received -> DELIVERED."""
    ctx = setup_acknowledged_order(ctx, **kw)
    qty = ctx.line["quantity"]
    add_staging_reservation(
        ctx, {"units": qty, "start_date": "2026-08-06", "end_date": "2026-08-08"}
    )
    receive_units(ctx, received_units=qty)
    ctx.line = get_success_data(api_client.get_order_line(ctx.line["id"], AE))
    ctx.order = get_success_data(api_client.get_project_order(ctx.order["id"], PM))
    return ctx


def setup_installed_order(ctx=None, **kw) -> SimpleNamespace:
    """DELIVERED order plus one completed event -> INSTALLED."""
    ctx = setup_delivered_order(ctx, **kw)
    add_confirmed_event(ctx)
    get_success_data(api_client.start_event(ctx.event["id"], PM))
    ctx.event = get_success_data(
        api_client.complete_event(ctx.event["id"], {"labor_hours_actual": 3}, PM)
    )
    ctx.order = get_success_data(api_client.get_project_order(ctx.order["id"], PM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: punch items and claims
# ---------------------------------------------------------------------------

def add_punch(ctx, overrides=None) -> dict:
    payload = create_punch_item_payload(ctx.order["id"], **(overrides or {}))
    ctx.punch = get_success_data(api_client.create_punch_item(payload, PM))
    return ctx.punch


def setup_verified_punch(ctx=None, severity="STANDARD", punch_overrides=None, **kw) -> SimpleNamespace:
    """Submitted-order pipeline plus a punch item walked to VERIFIED."""
    ctx = setup_submitted_order(ctx, **kw)
    overrides = {
        "order_line_id": ctx.line["id"],
        "severity": severity,
        "affected_units": 1,
    }
    overrides.update(punch_overrides or {})
    add_punch(ctx, overrides)
    get_success_data(api_client.ready_punch_for_verify(ctx.punch["id"], PM))
    ctx.punch = get_success_data(
        api_client.verify_punch(ctx.punch["id"], {"passed": True}, CC)
    )
    return ctx


def create_manual_claim(ctx, overrides=None) -> dict:
    from .factories import create_manufacturer_claim_payload

    payload = create_manufacturer_claim_payload(ctx.punch["id"], **(overrides or {}))
    ctx.claim = get_success_data(api_client.create_manufacturer_claim(payload, CC))
    return ctx.claim


def walk_claim_to_offered(ctx, settlement_amount_cents=50_000) -> dict:
    """DRAFT -> SUBMITTED -> ACKNOWLEDGED -> SETTLEMENT_OFFERED."""
    get_success_data(api_client.submit_claim(ctx.claim["id"], CC))
    get_success_data(api_client.acknowledge_claim(ctx.claim["id"], REP))
    ctx.claim = get_success_data(
        api_client.offer_settlement(
            ctx.claim["id"], {"settlement_amount_cents": settlement_amount_cents}, REP
        )
    )
    return ctx.claim


def get_auto_claim_for_punch(punch_id) -> dict:
    """Fetch the cascade-created claim for a verified CRITICAL punch item."""
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_manufacturer_claims(CC, params={"punch_item_id": punch_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one auto claim for punch {punch_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 4: liquidation credit
# ---------------------------------------------------------------------------

def create_lot(customer_id, overrides=None) -> dict:
    payload = create_liquidation_lot_payload(customer_id, **(overrides or {}))
    return get_success_data(api_client.create_liquidation_lot(payload, AE))


def appraise_lot(lot, condition_grade="A", appraised_value_cents=1_000_000,
                 appraiser_headers=None) -> dict:
    """Appraise with the lot's current version (OCC)."""
    return get_success_data(
        api_client.appraise_lot(
            lot["id"],
            {
                "condition_grade": condition_grade,
                "appraised_value_cents": appraised_value_cents,
                "expected_lot_version": lot["version"],
            },
            appraiser_headers or APPRAISER,
        )
    )


def issue_credit(lot_id, finance_headers=None) -> dict:
    return get_success_data(api_client.issue_credit(lot_id, finance_headers or FINANCE))


def setup_customer_credit(customer_id, appraised_value_cents=1_000_000,
                          condition_grade="A", item_count=10) -> dict:
    """Lot offered -> appraised -> credit issued. Returns the CREDIT_ISSUED lot."""
    lot = create_lot(customer_id, {"item_count": item_count})
    lot = appraise_lot(lot, condition_grade, appraised_value_cents)
    return issue_credit(lot["id"])
