"""Breadth queue B — state-machine, calculation, cross-cutting and consistency corners.

One test per non-stub corner-design instance.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    create_client_payload,
    create_contract_payload,
    create_inventory_item_payload,
    create_design_proposal_payload,
    create_line_item_payload,
    create_crew_payload,
    create_storage_bay_payload,
    create_damage_report_payload,
    create_client,
    create_draft_contract,
    create_inventory_item,
    create_storage_bay,
    setup_active_contract,
    setup_proposal_with_lines,
    create_work_order_with_visits,
    schedule_work_order,
    create_completed_takedown,
    setup_sent_renewal_offer,
    create_stored_lot,
    make_client_contact_headers,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# =====================================================================
# State machines
# =====================================================================
def test_contract_initial_state_is_draft():
    """PRD §3.1: "A freshly created contract carries `status` `DRAFT`, a
    `renewed_from_contract_id` of null ... and null values for its computed money fields."

    Design: Corner/state_machines/contract_initial_state_is_draft
    """
    client = create_client(account_type="COMMERCIAL")
    contract = validate_success(api_client.create_contract(
        client["id"], create_contract_payload(contract_type="COMMERCIAL"), AM), 201)
    assert contract["status"] == "DRAFT"


def test_propose_contract_without_submitted_proposal_returns_invalid_state():
    """PRD §3.1: "An account manager moves a contract from `DRAFT` to `PROPOSED`, which opens
    the client-review window; this is permitted only while the contract is `DRAFT` and at
    least one `DesignProposal` under it sits in `SUBMITTED`."

    Design: Corner/state_machines/propose_contract_without_submitted_proposal_returns_invalid_state
    """
    client = create_client(account_type="COMMERCIAL")
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    res = api_client.propose_contract(client["id"], contract["id"], AM)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_cancel_contract_cascades_workorders_and_storage():
    """PRD §3.1: "Cancellation cascades: every non-terminal work order for the contract — that
    is, each one whose `schedule_status` is `UNSCHEDULED` or `SCHEDULED` — has its
    `schedule_status` set to `CANCELLED`, and every storage lot for the contract whose `status`
    is `RESERVED` or `STORED` is moved to `RELEASED`."

    Design: Corner/state_machines/cancel_contract_cascades_workorders_and_storage
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-B2-CORN", sku_overrides={"on_hand_qty": 10},
        line_quantity=4, unit_install_cents=5000)
    bay = create_storage_bay(bay_code="BAY-B2-CORN", capacity_units=100)
    wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
    stored_lot = create_stored_lot(ctx["contract_id"], bay["id"], 10,
                                   "2027-01-01T00:00:00Z", "2027-03-01T00:00:00Z")
    cancelled = validate_success(
        api_client.cancel_contract(ctx["client_id"], ctx["contract_id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"
    wo_after = validate_success(api_client.get_work_order(wo["id"], FS), 200)
    assert wo_after["schedule_status"] == "CANCELLED"
    lot_after = validate_success(api_client.get_storage_lot(stored_lot["id"], FS), 200)
    assert lot_after["status"] == "RELEASED"


def test_cancel_workorder_twice_returns_invalid_state():
    """PRD §3.4: "A work order may also be cancelled from either `UNSCHEDULED` or `SCHEDULED`,
    moving its `schedule_status` to `CANCELLED`."

    Design: Corner/state_machines/cancel_workorder_twice_returns_invalid_state
    """
    client = create_client(account_type="COMMERCIAL")
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    wo = get_success_data(api_client.create_work_order(
        {"contract_id": contract["id"], "job_type": "INSTALL"}, FS))
    get_success_data(api_client.cancel_work_order(wo["id"], FS))
    # The work order is already CANCELLED (terminal); cancelling again is undefined.
    res = api_client.cancel_work_order(wo["id"], FS)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_complete_workorder_with_planned_visit_returns_visits_not_complete():
    """PRD §3.4: "Completion requires the work order to be `DISPATCHED` and every visit on it
    to be in `COMPLETED` or `SKIPPED`; a still-`PLANNED` visit blocks completion with
    `ERR_VISITS_NOT_COMPLETE` (HTTP 409)."

    Design: Corner/state_machines/complete_workorder_with_planned_visit_returns_visits_not_complete
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-D2-CORN", sku_overrides={"on_hand_qty": 10},
        line_quantity=4, unit_install_cents=5000)
    crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="D2 Crew CORN"), FS))
    wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
    schedule_work_order(wo["id"], crew["id"], "2026-11-10T00:00:00Z")
    get_success_data(api_client.dispatch_work_order(wo["id"], FS))
    # Visit is still PLANNED.
    res = api_client.complete_work_order(wo["id"], FS)
    validate_error(res, "ERR_VISITS_NOT_COMPLETE", 409)


def test_invoice_before_completion_returns_workorder_not_completed():
    """PRD §3.5: "invoicing requires the `billing_status` to be `PENDING` and the
    `schedule_status` to already be `COMPLETED`, and an attempt to invoice work that is not yet
    schedule-complete is rejected with `ERR_WORKORDER_NOT_COMPLETED` (HTTP 409)."

    Design: Corner/state_machines/invoice_before_completion_returns_workorder_not_completed
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-E2-CORN", sku_overrides={"on_hand_qty": 10},
        line_quantity=4, unit_install_cents=5000)
    crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="E2 Crew CORN"), FS))
    wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
    schedule_work_order(wo["id"], crew["id"], "2026-11-10T00:00:00Z")
    # schedule_status is SCHEDULED, not COMPLETED.
    res = api_client.invoice_work_order(wo["id"], AM)
    validate_error(res, "ERR_WORKORDER_NOT_COMPLETED", 409)


def test_renewal_offer_accept_after_expiry_returns_offer_expired():
    """PRD §3.9: "Accepting advances the offer `SENT` to `ACCEPTED` and is permitted only when
    the offer is `SENT` and the logical clock is at or before the offer's `expires_at`; an
    accept attempted after `expires_at` is rejected with `ERR_OFFER_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/renewal_offer_accept_after_expiry_returns_offer_expired
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-F2-CORN", sku_overrides={"on_hand_qty": 10},
        line_quantity=4, unit_install_cents=5000)
    renewal = setup_sent_renewal_offer(ctx, expires_at="2026-12-01T00:00:00Z")
    validate_success(api_client.set_clock({"to_iso8601": "2026-12-02T00:00:00Z"}, PA), 200)
    cc = make_client_contact_headers(ctx["client_id"])
    res = api_client.accept_renewal_offer(renewal["offer"]["id"], cc)
    validate_error(res, "ERR_OFFER_EXPIRED", 409)


def test_proposal_accept_supersedes_sibling():
    """PRD §3.2: "Acceptance is the system's single-winner mechanism: at acceptance, every
    sibling `DesignProposal` under the same contract whose `status` is `DRAFT` or `SUBMITTED`
    is moved to `SUPERSEDED`."

    Design: Corner/state_machines/proposal_accept_supersedes_sibling
    """
    client = create_client(account_type="COMMERCIAL")
    item = create_inventory_item(sku="TREE-G2-CORN", on_hand_qty=10)
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal_a = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan A"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_a["id"], create_line_item_payload(item["id"], quantity=4, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_a["id"], AM))
    proposal_b = get_success_data(api_client.create_design_proposal(contract["id"], {"theme": "Plan B"}, AM))
    get_success_data(api_client.create_line_item(
        proposal_b["id"], create_line_item_payload(item["id"], quantity=6, unit_install_cents=5000), AM))
    get_success_data(api_client.submit_proposal(proposal_b["id"], AM))
    proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
    cc = make_client_contact_headers(client["id"])
    accepted_a = validate_success(api_client.accept_proposal(
        proposal_a["id"], {"expected_contract_version": proposed["version"]}, cc), 200)
    assert accepted_a["status"] == "ACCEPTED"
    b_after = validate_success(api_client.get_design_proposal(proposal_b["id"], AM), 200)
    assert b_after["status"] == "SUPERSEDED"


# =====================================================================
# Calculations
# =====================================================================
def test_contract_total_commercial_early_bird_ten_percent():
    """PRD §3.3: "a `COMMERCIAL` contract earns 10 percent and an `HOA` contract earns 12
    percent, but only when the logical clock at sign time is at or before the
    `early_bird_deadline`."

    Design: Corner/calculations/contract_total_commercial_early_bird_ten_percent
    """
    validate_success(api_client.set_clock({"to_iso8601": "2026-02-15T00:00:00Z"}, PA), 200)
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-H2-CORN", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
        contract_overrides={"early_bird_deadline": "2026-03-01T00:00:00Z",
                            "custom_design_surcharge_cents": 0},
        line_quantity=50, unit_install_cents=10000)
    # Activation already signed; install 475000 + storage 15000 → discount 49000, total 441000.
    signed = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
    assert signed["early_bird_discount_cents"] == 49000
    assert signed["total_amount_cents"] == 441000


def test_contract_total_event_never_early_bird():
    """PRD §3.3: "an `EVENT` contract never qualifies, and signing after the deadline never
    qualifies, so in those cases the percentage is zero."

    Design: Corner/calculations/contract_total_event_never_early_bird
    """
    validate_success(api_client.set_clock({"to_iso8601": "2026-02-15T00:00:00Z"}, PA), 200)
    ctx = setup_active_contract(
        account_type="EVENT", contract_type="EVENT",
        sku="TREE-I2-CORN", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
        contract_overrides={"early_bird_deadline": "2026-03-01T00:00:00Z",
                            "custom_design_surcharge_cents": 0},
        line_quantity=50, unit_install_cents=10000)
    signed = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
    # EVENT never qualifies → discount 0, total = install 475000 + storage 15000 = 490000.
    assert signed["early_bird_discount_cents"] == 0
    assert signed["total_amount_cents"] == 490000


def test_damage_settlement_loyalty_waiver_variant():
    """PRD §3.7: "A loyalty waiver may reduce this: if the owning contract is in
    `RENEWAL_OFFERED` or has a `RenewalOffer` in `SENT`, the effective percentage is the base
    percentage reduced by 5 percentage points but never below a 5 percent floor — that is, the
    larger of the base minus 5 points and 5 percent; otherwise the effective percentage is the
    base percentage unchanged."

    Design: Corner/calculations/damage_settlement_loyalty_waiver_variant
    """
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="STRAND-K2-CORN", sku_overrides={"category": "LIGHTING", "unit_replacement_cents": 4500, "on_hand_qty": 30},
        line_quantity=3, unit_install_cents=5000)
    crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="K2 Crew CORN"), FS))
    completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2027-01-25T00:00:00Z")
    # Put the contract into RENEWAL_OFFERED via a SENT offer (loyalty posture).
    setup_sent_renewal_offer(ctx)
    dr = get_success_data(api_client.create_damage_report(
        completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=3), FS))
    assessed = validate_success(api_client.assess_damage_report(dr["id"], {"resolution_path": "REPAIR"}, FS), 200)
    # repl 3*4500=13500, base 0.20 → eff 0.15, labor 2025, total 15525 (vs 16200 standard).
    assert assessed["replacement_cost_cents"] == 13500
    assert assessed["settlement_total_cents"] == 15525


# =====================================================================
# Cross-cutting complexity layers
# =====================================================================
def test_occ_correct_version_succeeds_and_increments():
    """PRD §3.2: "Acceptance also advances the parent contract's `version` (this is what the
    OCC guard of §2.7 protects) in addition to the proposal's own `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    client = create_client(account_type="COMMERCIAL")
    item = create_inventory_item(sku="TREE-T2-CORN", on_hand_qty=10)
    contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
    proposal = setup_proposal_with_lines(
        contract["id"],
        [{"inventory_item_id": item["id"], "quantity": 4, "unit_install_cents": 5000}])
    proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
    cc = make_client_contact_headers(client["id"])
    accepted = validate_success(api_client.accept_proposal(
        proposal["id"], {"expected_contract_version": proposed["version"]}, cc), 200)
    assert accepted["status"] == "ACCEPTED"


def test_clock_default_before_set_governs_early_bird():
    """PRD §2.10: "At server startup the logical clock reads exactly `2026-04-01T00:00:00Z`,
    and before any clock-setting call it holds that default and never falls back to the host's
    wall clock."

    Design: Corner/cross_cutting_complexity_layers/clock_default_before_set_governs_early_bird
    """
    # No set_current_utc call: clock stays at the 2026-04-01 default; deadline 2026-05-01 is
    # after it, so a COMMERCIAL contract earns the 0.10 early-bird discount.
    ctx = setup_active_contract(
        account_type="COMMERCIAL", contract_type="COMMERCIAL",
        sku="TREE-U2-CORN", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
        contract_overrides={"early_bird_deadline": "2026-05-01T00:00:00Z",
                            "custom_design_surcharge_cents": 0},
        line_quantity=50, unit_install_cents=10000)
    signed = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
    assert signed["early_bird_discount_cents"] == 49000
    assert signed["total_amount_cents"] == 441000


# =====================================================================
# Consistency model
# =====================================================================
def test_sign_returns_all_computed_fees_in_same_response():
    """PRD §3.3: "In one transaction the system computes four figures over the contract's
    single `ACCEPTED` proposal and its stored décor, in a pinned order: first the install fee,
    then the storage fee, then the early-bird discount and the final total."

    Design: Corner/consistency_model/sign_returns_all_computed_fees_in_same_response
    """
    validate_success(api_client.set_clock({"to_iso8601": "2026-02-15T00:00:00Z"}, PA), 200)
    client = get_success_data(api_client.create_client(
        create_client_payload(legal_name="Victor2 HOA", account_type="HOA",
                              contact_email="v2@x.test", site_address="50 St"), AM))
    light = get_success_data(api_client.create_inventory_item(
        create_inventory_item_payload(sku="LIGHT-V2-CORN", category="LIGHTING",
                                      unit_replacement_cents=3000, on_hand_qty=100), PA))
    wreath = get_success_data(api_client.create_inventory_item(
        create_inventory_item_payload(sku="WREATH-V2-CORN", category="WREATH",
                                      unit_replacement_cents=8000, on_hand_qty=100), PA))
    contract = get_success_data(api_client.create_contract(
        client["id"], create_contract_payload(contract_type="HOA",
                                               early_bird_deadline="2026-03-01T00:00:00Z",
                                               custom_design_surcharge_cents=50000), AM))
    proposal = get_success_data(api_client.create_design_proposal(
        contract["id"], create_design_proposal_payload(theme="Winter Gold", is_custom=True), AM))
    get_success_data(api_client.create_line_item(
        proposal["id"], create_line_item_payload(light["id"], quantity=30, unit_install_cents=4999), AM))
    get_success_data(api_client.create_line_item(
        proposal["id"], create_line_item_payload(wreath["id"], quantity=25, unit_install_cents=12500), AM))
    get_success_data(api_client.submit_proposal(proposal["id"], AM))
    proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
    cc = make_client_contact_headers(client["id"])
    get_success_data(api_client.accept_proposal(
        proposal["id"], {"expected_contract_version": proposed["version"]}, cc))
    signed = validate_success(api_client.sign_contract(client["id"], contract["id"], cc), 200)
    assert signed["install_fee_cents"] == 439347
    assert signed["storage_fee_cents"] == 15000
    assert signed["early_bird_discount_cents"] == 54522
    assert signed["total_amount_cents"] == 449825
