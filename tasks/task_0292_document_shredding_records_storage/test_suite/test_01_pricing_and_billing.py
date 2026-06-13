"""Pricing and billing: destruction charge variants, the combinatorial charge
formula, retrieval charge, storage-invoice totals, free-period boundary, and
immediate consistency.

Every test creates its own entities; the server starts against an empty DB.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_field_technician_headers,
    setup_account_with_rate_card,
    setup_onsite_order_en_route,
    setup_stored_box,
    setup_pending_retrieval,
    create_container,
    create_order,
    credit_account,
    advance_period,
    create_retrieval,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# ===========================================================================
# dual_variant_calc / destruction_charge_estimated_vs_actual_on_order
# ===========================================================================
def test_onsite_charge_actualizes_at_shred(api):
    """PRD §3.7: "Under the actual variant, evaluated at on-site shred (for
    on-site orders) or at receive-at-plant (for off-site-pickup and drop-off
    orders), billed_weight_kg is the weight ticket's net_weight_kg - gross minus
    summed tare - and the resulting order_charge_cents is final, replacing the
    estimate."

    Two CONSOLE containers (cap 50/tare 8.0, cap 30/tare 5.0): estimate weight
    80 -> est charge 80*5 + 2500 trip + 2*1000 console = 4900. Weigh-in gross
    70.0 -> net 57.0 -> final 57*5 + 2500 + 2000 = 4785.

    Design: Difficulty/dual_variant_calc/destruction_charge_estimated_vs_actual_on_order
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=True, gross_weight_kg=70.0,
    )
    assert state["order"]["order_charge_cents"] == 4900, "provisional estimate"
    tech_headers = state["tech_headers"]
    resp = api.shred_on_site(state["order"]["id"], tech_headers)
    data = validate_success(resp, 200)
    assert data["order_charge_cents"] == 4785, f"final charge, got {data['order_charge_cents']}"
    assert data["billed_weight_kg"] == 57.0, f"net weight, got {data['billed_weight_kg']}"


def test_onsite_estimate_differs_from_final(api):
    """PRD §3.3: "The estimated billed weight billed_weight_kg is taken as the
    sum of capacity_kg across the order's named containers - a nominal estimate,
    since nothing has yet been weighed - and order_charge_cents computed from it
    is provisional."

    The estimate captured at create (4900) differs from the post-weigh-in final
    (4785) for the same rate inputs.

    Design: Difficulty/dual_variant_calc/destruction_charge_estimated_vs_actual_on_order
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=True, gross_weight_kg=70.0,
    )
    est_charge = state["order"]["order_charge_cents"]
    assert est_charge == 4900, f"estimate at create, got {est_charge}"
    final = validate_success(api.shred_on_site(state["order"]["id"], state["tech_headers"]), 200)
    assert final["order_charge_cents"] != est_charge
    assert final["order_charge_cents"] == 4785


# ===========================================================================
# dual_variant_calc / storage_invoice_credit_variant_on_account
# ===========================================================================
def test_storage_invoice_with_credit_applied(api):
    """PRD §3.8: "The credit applied is the smaller of the account's
    storage_credit_cents and that gross, recorded as credit_applied_cents; the
    account's storage_credit_cents is then reduced by exactly that amount, so the
    credit consumed plus the credit remaining equals the credit that was on hand
    before close."

    Two STORED boxes (free_periods 0) + one RUSH retrieval (6000) in period 0;
    gross = 2*300 + 6000 = 6600; credit 1000 -> amount_due 5600, credit_after 0.

    Design: Difficulty/dual_variant_calc/storage_invoice_credit_variant_on_account
    """
    account, location, rate_card = setup_account_with_rate_card(
        compliance_regime="HIPAA", rate_overrides={"rush_retrieval_multiplier_bps": 15000})
    box1 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1", free_periods=0), AM))
    box2 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-2", free_periods=0), AM))
    get_success_data(api.shelve_box(box1["id"], PO))
    get_success_data(api.shelve_box(box2["id"], PO))
    rr = create_retrieval(box1["id"], account["id"], priority="RUSH")
    get_success_data(api.fulfill_retrieval(rr["id"], PO))
    credit_account(account["id"], 1000)

    inv = validate_success(api.advance_period(account["id"], CO), 201)
    assert inv["storage_line_cents"] == 600, f"got {inv['storage_line_cents']}"
    assert inv["retrieval_line_cents"] == 6000, f"got {inv['retrieval_line_cents']}"
    assert inv["credit_applied_cents"] == 1000, f"got {inv['credit_applied_cents']}"
    assert inv["amount_due_cents"] == 5600, f"got {inv['amount_due_cents']}"
    acct_after = validate_success(api.get_account(account["id"], CO), 200)
    assert acct_after["storage_credit_cents"] == 0, f"got {acct_after['storage_credit_cents']}"


def test_storage_invoice_retrieval_line_priced_at_fulfillment(api):
    """PRD §3.8: "The retrieval_line_cents is the sum of retrieval_charge_cents
    across every retrieval request whose delivered_period equals the closing
    period - these were priced when each retrieval was fulfilled."

    A RUSH retrieval fulfilled in period 0 contributes 6000 to the period-0
    invoice's retrieval line.

    Design: Difficulty/dual_variant_calc/storage_invoice_credit_variant_on_account
    """
    account, location, rate_card = setup_account_with_rate_card(
        compliance_regime="HIPAA", rate_overrides={"rush_retrieval_multiplier_bps": 15000})
    box1 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1", free_periods=0), AM))
    box2 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-2", free_periods=0), AM))
    get_success_data(api.shelve_box(box1["id"], PO))
    get_success_data(api.shelve_box(box2["id"], PO))
    rr = create_retrieval(box1["id"], account["id"], priority="RUSH")
    get_success_data(api.fulfill_retrieval(rr["id"], PO))
    credit_account(account["id"], 1000)

    inv = validate_success(api.advance_period(account["id"], CO), 201)
    assert inv["retrieval_line_cents"] == 6000


# ===========================================================================
# combinatorial_formula / destruction_charge_multi_input_nonlinear
# ===========================================================================
def test_charge_combines_weight_trip_and_console_fees(api):
    """PRD §3.7: "The three components are then summed - weight charge first,
    then trip fee, then console fee - to produce order_charge_cents."

    ON_SITE SCHEDULED order, one CONSOLE (cap 50) + one BIN (cap 30): estimate
    weight 80 -> weight 80*5=400; trip 2500 (ON_SITE); console 1000 (only the
    CONSOLE) -> 3900.

    Design: Difficulty/combinatorial_formula/destruction_charge_multi_input_nonlinear
    """
    account, location, rate_card = setup_account_with_rate_card()
    console = create_container(account["id"], location["id"],
                               container_type="CONSOLE", capacity_kg=50, tare_weight_kg=8.0)
    bin_c = create_container(account["id"], location["id"],
                             container_type="BIN", capacity_kg=30, tare_weight_kg=5.0)
    resp = api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[console["id"], bin_c["id"]]), AM)
    data = validate_success(resp, 201)
    assert data["order_charge_cents"] == 3900, f"got {data['order_charge_cents']}"
    assert data["billed_weight_kg"] == 80, f"got {data['billed_weight_kg']}"


def test_console_fee_counts_only_console_containers(api):
    """PRD §3.7: "The third component is the console fee: it is
    console_swap_fee_cents multiplied by the number of CONSOLE-type containers
    among the order's named container_ids (bins do not attract this fee)."

    A mixed order's console fee reflects only the single CONSOLE; the BIN adds
    nothing, so the total is 400 + 2500 + 1000 = 3900 rather than 400+2500+2000.

    Design: Difficulty/combinatorial_formula/destruction_charge_multi_input_nonlinear
    """
    account, location, rate_card = setup_account_with_rate_card()
    console = create_container(account["id"], location["id"],
                               container_type="CONSOLE", capacity_kg=50, tare_weight_kg=8.0)
    bin_c = create_container(account["id"], location["id"],
                             container_type="BIN", capacity_kg=30, tare_weight_kg=5.0)
    data = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[console["id"], bin_c["id"]]), AM), 201)
    # console fee component is 1000 (one CONSOLE), not 2000.
    assert data["order_charge_cents"] == 3900


# ===========================================================================
# combinatorial_formula / storage_invoice_pinned_evaluation_order
# ===========================================================================
def test_storage_credit_capped_at_gross(api):
    """PRD §3.8: "The credit applied is the smaller of the account's
    storage_credit_cents and that gross, recorded as credit_applied_cents."

    One STORED box (gross 300), credit 5000 exceeds gross: credit_applied capped
    at 300, amount_due 0, credit_after 4700.

    Design: Difficulty/combinatorial_formula/storage_invoice_pinned_evaluation_order
    """
    account, location, rate_card = setup_account_with_rate_card()
    box1 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1", free_periods=0), AM))
    get_success_data(api.shelve_box(box1["id"], PO))
    credit_account(account["id"], 5000)

    inv = validate_success(api.advance_period(account["id"], CO), 201)
    assert inv["storage_line_cents"] == 300, f"got {inv['storage_line_cents']}"
    assert inv["credit_applied_cents"] == 300, f"got {inv['credit_applied_cents']}"
    assert inv["amount_due_cents"] == 0, f"got {inv['amount_due_cents']}"
    acct_after = validate_success(api.get_account(account["id"], CO), 200)
    assert acct_after["storage_credit_cents"] == 4700, f"got {acct_after['storage_credit_cents']}"


def test_storage_amount_due_never_negative_when_credit_exceeds_gross(api):
    """PRD §3.8: "The amount_due_cents is the gross minus credit_applied_cents
    and is never negative."

    With credit 5000 vs gross 300, amount_due settles to 0 rather than negative.

    Design: Difficulty/combinatorial_formula/storage_invoice_pinned_evaluation_order
    """
    account, location, rate_card = setup_account_with_rate_card()
    box1 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1", free_periods=0), AM))
    get_success_data(api.shelve_box(box1["id"], PO))
    credit_account(account["id"], 5000)
    inv = validate_success(api.advance_period(account["id"], CO), 201)
    assert inv["amount_due_cents"] == 0
    assert inv["amount_due_cents"] >= 0


# ===========================================================================
# Corner: calculations / retrieval_charge_rush_multiplier
# ===========================================================================
def test_rush_retrieval_applies_multiplier(api):
    """PRD §3.9: "while for a RUSH request the charge is the base multiplied by
    rush_retrieval_multiplier_bps and divided by ten thousand, with the result
    rounded half up to an integer cent."

    Base 4000, rush 15000 bps -> 4000*15000/10000 = 6000.

    Design: Corner/calculations/retrieval_charge_rush_multiplier
    """
    state = setup_pending_retrieval(priority="RUSH")
    data = validate_success(api.fulfill_retrieval(state["request"]["id"], PO), 200)
    assert data["retrieval_charge_cents"] == 6000, f"got {data['retrieval_charge_cents']}"


# ===========================================================================
# Corner: calculations / storage_free_period_boundary_excludes_then_includes
# ===========================================================================
def test_free_period_boundary_excludes_then_includes(api):
    """PRD §3.8: "those whose status is STORED or OUT_FOR_RETRIEVAL ... and whose
    free period has elapsed - that is, the closing period is greater than or
    equal to the box's stored_at_period plus its free_periods (the boundary is
    inclusive)."

    Box stored at period 0 with free_periods 2: excluded from period-1 invoice
    (1 < 2) but included in the period-2 invoice (2 >= 2).

    Design: Corner/calculations/storage_free_period_boundary_excludes_then_includes
    """
    account, location, rate_card = setup_account_with_rate_card()
    box1 = get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1", free_periods=2), AM))
    get_success_data(api.shelve_box(box1["id"], PO))
    inv_p0 = validate_success(api.advance_period(account["id"], CO), 201)
    inv_p1 = validate_success(api.advance_period(account["id"], CO), 201)
    inv_p2 = validate_success(api.advance_period(account["id"], CO), 201)
    assert inv_p1["storage_line_cents"] == 0, f"period 1 (1<2): got {inv_p1['storage_line_cents']}"
    assert inv_p2["storage_line_cents"] == 300, f"period 2 (2>=2): got {inv_p2['storage_line_cents']}"


# ===========================================================================
# Corner: consistency_model / immediate_charge_visible_in_create_response
# ===========================================================================
def test_provisional_charge_visible_in_create_response(api):
    """PRD §3.3: "At creation the charge is computed provisionally, using the
    estimated variant of the destruction charge."

    PRD §3.7: "The three components are then summed - weight charge first, then
    trip fee, then console fee - to produce order_charge_cents."

    One CONSOLE (cap 50) ON_SITE SCHEDULED order: the create response itself
    carries order_charge_cents == 50*5 + 2500 + 1000 = 3750 and billed_weight_kg
    == 50, with no read-after-write lag.

    Design: Corner/consistency_model/immediate_charge_visible_in_create_response
    """
    account, location, rate_card = setup_account_with_rate_card()
    console = create_container(account["id"], location["id"],
                               container_type="CONSOLE", capacity_kg=50, tare_weight_kg=8.0)
    data = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[console["id"]]), AM), 201)
    assert data["order_charge_cents"] == 3750, f"got {data['order_charge_cents']}"
    assert data["billed_weight_kg"] == 50, f"got {data['billed_weight_kg']}"
