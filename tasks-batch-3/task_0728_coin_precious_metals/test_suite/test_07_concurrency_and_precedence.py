"""Optimistic concurrency (layaway deposit stale-version), validation
precedence where PRD uniquely fixes the winner, and a cross-entity state
dependency (listing requires a SCHEDULED session).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_spot_rate,
    create_product,
    create_inventory_lot,
    create_customer,
    create_active_ira,
    create_placed_sell_order,
    create_intake_consignment,
    create_auction_session,
    setup_layaway,
    deposit_on_layaway,
    make_customer_headers,
    TEST_USERS,
)

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── OCC: layaway deposit stale version ───────────────────────────────────

def test_layaway_deposit_stale_version_rejected(api):
    """PRD §2.6: "If that value does not equal the layaway's current version — for
    example because a prior deposit or a status change advanced the version since the
    client last read the record — the deposit is rejected with ERR_STALE_VERSION
    (HTTP 412), preventing the client from applying a deposit against a stale
    amount_paid_cents view."

    Design: Corner/cross_cutting_complexity_layers/layaway_deposit_stale_version_returns_stale
    """
    ctx = setup_layaway(quantity=2, customer_name="OCC Payer")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]
    v0 = lay["version"]

    deposit_on_layaway(lay["id"], 50_000, v0, cust_id)  # advances version
    res = api.deposit_layaway(
        lay["id"], {"amount_cents": 50_000, "expected_layaway_version": v0},
        make_customer_headers(cust_id))
    validate_error(res, "ERR_STALE_VERSION")
    current = validate_success(api.get_layaway(lay["id"], SALES), 200)
    assert current["amount_paid_cents"] == 50_000


def test_layaway_deposit_correct_version_increments(api):
    """PRD §2.6: "Applying a deposit to a layaway requires the request body to carry
    expected_layaway_version, a non-optional field holding the version of the Layaway
    the client last observed." PRD §3.5: "A successful deposit increases
    amount_paid_cents by amount_cents and increments the layaway's version".

    Design: Corner/cross_cutting_complexity_layers/layaway_deposit_correct_version_succeeds_and_increments
    """
    ctx = setup_layaway(quantity=2, customer_name="OCC OK")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    after = deposit_on_layaway(lay["id"], 30_000, lay["version"], cust_id)
    assert after["amount_paid_cents"] == 30_000
    assert after["version"] == 2


# ─── Rule 5a: state (priority 5) beats business_safety (priority 8) ───────
# PRD-reachable: place an IRA-allocation order against an ACTIVE IRA (placement
# guard satisfied), cancel the order, then close the IRA. Settling now violates
# both the state check (order is CANCELLED) and the IRA-active check (IRA CLOSED).

def _cancelled_ira_order_with_closed_ira():
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-IRA-1", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04, ira_eligible=True)
    create_inventory_lot(product["id"], total_qty=5, acquisition_unit_cost_cents=100_000)
    customer = create_customer("IRA Owner", id_document_on_file=True, as_role=COMPLIANCE)
    ira = create_active_ira(customer["id"], custodian_name="Acme Trust", custodian_account_ref="ACME-001")
    order = create_placed_sell_order(product["id"], customer["id"], quantity=1, ira_account_id=ira["id"])
    validate_success(api_client.cancel_sell_order(order["id"], SALES), 200)
    validate_success(api_client.close_ira_account(ira["id"], COMPLIANCE), 200)
    return order


def test_cancelled_ira_order_settle_returns_invalid_state(api):
    """PRD §2.7: "Requests are validated in a fixed order, and the first failing
    check determines the error returned. The ordering is: ... (5) state — the target
    resource is in a state from which the requested transition is defined, else
    ERR_INVALID_STATE (409). Business-rule checks specific to each endpoint follow
    these in the priority documented alongside each workflow in §3."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_ira_sell_settle
    """
    order = _cancelled_ira_order_with_closed_ira()
    res = api.settle_sell_order(order["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancelled_ira_order_settle_not_ira_not_active(api):
    """PRD §3.3: "Settlement is permitted only when the order is currently PLACED;
    otherwise the state guard rejects it with ERR_INVALID_STATE (HTTP 409)." PRD §2.7:
    "a request that fails several validations surfaces only the highest-priority
    failure."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_ira_sell_settle
    """
    order = _cancelled_ira_order_with_closed_ira()
    res = api.settle_sell_order(order["id"], SALES)
    error_data = validate_error(res, "ERR_INVALID_STATE")
    assert error_data["error_id"] != "ERR_IRA_NOT_ACTIVE"


# ─── Rule 7b: listing depends on session being SCHEDULED ──────────────────

def _intake_consignment_with_closed_session():
    customer = create_customer("Consignor Four")
    session = create_auction_session(room="ROOM-D", scheduled_start="2026-04-04T10:00:00Z",
                                     scheduled_end="2026-04-04T12:00:00Z")
    validate_success(api_client.close_auction_session(session["id"], SALES), 200)
    consignment = create_intake_consignment(customer["id"], reserve_price_cents=50_000,
                                            description="Platinum bar")
    return consignment, session


def test_list_into_closed_session_rejected(api):
    """PRD §3.6: "Listing is permitted only when the consignment is currently INTAKE
    and the referenced auction session's status is SCHEDULED; a session in any other
    status yields ERR_SESSION_NOT_SCHEDULED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/consignment_list_depends_on_session_scheduled
    """
    consignment, session = _intake_consignment_with_closed_session()
    res = api.list_consignment(consignment["id"], {"auction_session_id": session["id"]}, SALES)
    validate_error(res, "ERR_SESSION_NOT_SCHEDULED")


def test_consignment_stays_intake_after_failed_list(api):
    """PRD §3.6: "On success the consignment records its auction_session_id and moves
    from INTAKE to LISTED." PRD §3.6: "a session in any other status yields
    ERR_SESSION_NOT_SCHEDULED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/consignment_list_depends_on_session_scheduled
    """
    consignment, session = _intake_consignment_with_closed_session()
    api.list_consignment(consignment["id"], {"auction_session_id": session["id"]}, SALES)
    stayed = validate_success(api.get_consignment(consignment["id"], SALES), 200)
    assert stayed["status"] == "INTAKE"
