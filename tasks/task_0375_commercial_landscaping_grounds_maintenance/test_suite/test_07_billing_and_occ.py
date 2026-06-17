"""Invoice issuance: budget ceiling boundaries, the empty-sweep guard, the
budget-vs-state validation-priority pair, and contract optimistic concurrency.

Translates queue A (Difficulty) `boundary_precision_check` (budget/empty) and the
budget-fiscal `priority_pair_validation_conflict` instance, plus queue B (Corner)
`cross_cutting_complexity_layers` OCC instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_contract_payload,
    create_plan_payload, create_crew_payload, create_route_payload,
    create_equipment_payload, create_visit_payload, create_reservation_payload,
    create_invoice_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]


def _contract_with_one_68000_visit_and_draft_invoice(api, *, annual_budget_cents, period_label):
    """Active contract whose single COMPLETED visit has final_charge_cents 68000
    (actual=120 + a 120-min reservation), with a DRAFT invoice already swept
    (subtotal 68000, tax 5610, total 73610). Returns (contract_id, invoice_id)."""
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"], turf_area_sqft=5000), AM))
    contract = get_success_data(api.create_contract(
        create_contract_payload(acct["id"], site["id"], annual_budget_cents=annual_budget_cents), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"], base_rate_cents=10000), AM))
    cver = get_success_data(api.activate_contract(contract["id"], AM))["version"]
    crew = get_success_data(api.create_crew(create_crew_payload(acct["id"], hourly_rate_cents=6000), AM))
    route = get_success_data(api.create_route(create_route_payload(crew["id"]), CL))
    visit = get_success_data(api.create_visit(create_visit_payload(plan["id"], route["id"], cver), CL))
    asset = get_success_data(api.create_equipment(create_equipment_payload(acct["id"]), AM))
    get_success_data(api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"],
                                   window_start_minute=480, window_end_minute=600), CL))
    get_success_data(api.lock_route(route["id"], CL))
    get_success_data(api.start_visit(visit["id"], CL))
    get_success_data(api.complete_visit(visit["id"], {"actual_labor_minutes": 120}, CL))  # final 68000
    invoice = get_success_data(api.create_invoice(create_invoice_payload(contract["id"], period_label), AM))
    return contract["id"], invoice["id"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair: budget fiscal beats state on issue
# ---------------------------------------------------------------------------
def test_issue_invoice_over_budget_returns_budget_exceeded(api):
    """PRD §3.10: "the resulting `billed_cents` not to *strictly* exceed the
    contract's `annual_budget_cents` (otherwise `ERR_BUDGET_EXCEEDED`, HTTP 402)".

    Design: Difficulty/priority_pair_validation_conflict/budget_fiscal_beats_referential_then_state_on_issue
    """
    contract_id, invoice_id = _contract_with_one_68000_visit_and_draft_invoice(
        api, annual_budget_cents=73609, period_label="2026-06")  # one cent below total 73610
    cver = get_success_data(api.get_contract(contract_id, AM))["version"]
    resp = api.issue_invoice(invoice_id, {"expected_service_contract_version": cver}, AM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value, expected_status=402)


def test_budget_exceeded_fires_even_though_invoice_is_draft(api):
    """PRD §3.10: "Issuing requires, in order: the invoice to be `DRAFT`
    (otherwise `ERR_INVOICE_NOT_DRAFT`); ... and the resulting `billed_cents` not
    to *strictly* exceed the contract's `annual_budget_cents` (otherwise
    `ERR_BUDGET_EXCEEDED`, HTTP 402)".

    Design: Difficulty/priority_pair_validation_conflict/budget_fiscal_beats_referential_then_state_on_issue
    """
    contract_id, invoice_id = _contract_with_one_68000_visit_and_draft_invoice(
        api, annual_budget_cents=73609, period_label="2026-06")
    # the invoice's own state precondition (DRAFT) is satisfied; the swept total is 73610
    draft = get_success_data(api.get_invoice(invoice_id, AM))
    assert draft["status"] == "DRAFT"
    assert draft["total_cents"] == 73610
    cver = get_success_data(api.get_contract(contract_id, AM))["version"]
    resp = api.issue_invoice(invoice_id, {"expected_service_contract_version": cver}, AM)
    # the fiscal ceiling check still rejects the issue
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value, expected_status=402)


# ---------------------------------------------------------------------------
# Queue A — boundary_precision: budget exactly equal is allowed
# ---------------------------------------------------------------------------
def test_issue_invoice_at_exact_budget_succeeds(api):
    """PRD §3.10: "reaching exactly the budget is allowed, only a strict excess is
    rejected. On a successful issue, the invoice moves from `DRAFT` to `ISSUED`
    ... the contract's `billed_cents` is recomputed".

    Design: Difficulty/boundary_precision_check/budget_exactly_equal_is_allowed_on_issue
    """
    contract_id, invoice_id = _contract_with_one_68000_visit_and_draft_invoice(
        api, annual_budget_cents=73610, period_label="2026-06")  # exactly the total
    cver = get_success_data(api.get_contract(contract_id, AM))["version"]
    issued = validate_success(
        api.issue_invoice(invoice_id, {"expected_service_contract_version": cver}, AM), expected_status=200)
    assert issued["status"] == "ISSUED"
    assert get_success_data(api.get_contract(contract_id, AM))["billed_cents"] == 73610


def test_issue_invoice_one_below_budget_succeeds(api):
    """PRD §3.10: "reaching exactly the budget is allowed, only a strict excess is
    rejected. On a successful issue, the invoice moves from `DRAFT` to `ISSUED`".

    Design: Difficulty/boundary_precision_check/budget_exactly_equal_is_allowed_on_issue
    """
    contract_id, invoice_id = _contract_with_one_68000_visit_and_draft_invoice(
        api, annual_budget_cents=73611, period_label="2026-06")  # one cent above total
    cver = get_success_data(api.get_contract(contract_id, AM))["version"]
    issued = validate_success(
        api.issue_invoice(invoice_id, {"expected_service_contract_version": cver}, AM), expected_status=200)
    assert issued["status"] == "ISSUED"
    assert get_success_data(api.get_contract(contract_id, AM))["billed_cents"] == 73610


# ---------------------------------------------------------------------------
# Queue A — boundary_precision: empty invoice sweep blocks issue
# ---------------------------------------------------------------------------
def test_issue_empty_invoice_rejected(api):
    """PRD §3.10: "a `line_item_count` greater than zero (otherwise
    `ERR_EMPTY_INVOICE`)".

    Design: Difficulty/boundary_precision_check/empty_invoice_sweep_blocks_issue_on_zero_line_items
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    get_success_data(api.activate_contract(contract["id"], AM))
    invoice = get_success_data(api.create_invoice(create_invoice_payload(contract["id"], "2026-07"), AM))
    assert invoice["line_item_count"] == 0
    cver = get_success_data(api.get_contract(contract["id"], AM))["version"]
    resp = api.issue_invoice(invoice["id"], {"expected_service_contract_version": cver}, AM)
    validate_error(resp, ApiErrorId.ERR_EMPTY_INVOICE.value, expected_status=409)


def test_empty_invoice_draft_still_creates_with_zero_line_items(api):
    """PRD §3.10: "A contract with no completed-and-unbilled visits yields a sweep
    of `line_item_count` equal to 0 — the draft still creates, but such an empty
    invoice cannot later be issued."

    Design: Difficulty/boundary_precision_check/empty_invoice_sweep_blocks_issue_on_zero_line_items
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    get_success_data(api.activate_contract(contract["id"], AM))
    invoice = validate_success(
        api.create_invoice(create_invoice_payload(contract["id"], "2026-07"), AM), expected_status=201)
    assert invoice["line_item_count"] == 0
    assert invoice["subtotal_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers: OCC on visit-create
# ---------------------------------------------------------------------------
def test_occ_correct_version_on_visit_create_succeeds_and_bumps_version(api):
    """PRD §2.6: "Scheduling a new visit requires `expected_service_contract_version`
    to equal the target contract's current `version`."
    PRD §3.4: "the contract's `committed_cents` and `budget_remaining_cents` are
    reconciled, and the contract's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_visit_create_succeeds
    """
    scenario = fixtures.setup_active_contract_scenario()
    cver = scenario["contract_version"]
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver), CL)
    data = validate_success(resp, expected_status=201)
    assert data["execution_status"] == "SCHEDULED"
    after = get_success_data(api.get_contract(scenario["contract"]["id"], AM))
    assert after["version"] == cver + 1


def test_occ_stale_version_on_visit_create_rejected(api):
    """PRD §2.6: "If the supplied `expected_service_contract_version` does not
    match the contract's current `version`, the visit-create is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_visit_create_rejected
    """
    scenario = fixtures.setup_active_contract_scenario()
    cver = scenario["contract_version"]
    # first create succeeds and bumps the version
    get_success_data(api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver,
                             slot_start_minute=480, slot_duration_minute=90), CL))
    # second create still carrying the stale pre-create version is rejected
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver,
                             slot_start_minute=600, slot_duration_minute=90), CL)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, expected_status=412)
