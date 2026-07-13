"""Invoice issuance: dual-variant labor subtotal, discount-tier assembly, the
billable-work / unresolved-sessions checks and their relative order, the OCC
guard, and the dispute cycle.
"""
from test_helpers import (
    validate_success, validate_error,
    create_invoice_payload,
    new_active_project, new_session, start_session,
    setup_project_with_completed_session, setup_issued_invoice, project_version,
    make_organizer_headers, make_client_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]
BA = TEST_USERS["billing_admin_headers"]


def _issue(api, project_id):
    pv = project_version(project_id)
    return api.create_invoice(create_invoice_payload(project_id, pv), BA)


# ── Difficulty: HOURLY vs PROJECT labor subtotal (dual variant) ───────────────

def test_hourly_invoice_labor_subtotal_sums_completed_sessions(api):
    """PRD §3.7: "Under HOURLY, the labor subtotal is the sum of labor_cost_cents over
    the project's COMPLETED sessions. Under PROJECT, the labor subtotal is the
    project's flat_price_cents, and the actual logged hours are ignored entirely."
    PRD §3.7: "The tax_cents is that taxable amount multiplied by an 8% tax rate,
    rounded half up. Finally the grand_total_cents is the taxable amount plus the tax."

    Design: Difficulty/dual_variant_calc/billing_hourly_vs_project_labor_subtotal
    """
    client, organizer, project, session = setup_project_with_completed_session(
        billing_mode="HOURLY", hourly_rate_cents=6000, logged_hours=10,
        scheduled_start="2026-03-02T09:00:00Z", scheduled_end="2026-03-02T19:00:00Z")
    invoice = validate_success(_issue(api, project["id"]), 201)
    # 10h weekday at 6000: 8*6000 + 2*6000*1.5 = 48000 + 18000 = 66000.
    assert invoice["labor_subtotal_cents"] == 66000
    # subtotal 66000 (< 200000, no discount); tax = round(66000*0.08) = 5280.
    assert invoice["grand_total_cents"] == 71280


def test_project_invoice_labor_subtotal_uses_flat_price(api):
    """PRD §3.7: "Under HOURLY, the labor subtotal is the sum of labor_cost_cents over
    the project's COMPLETED sessions. Under PROJECT, the labor subtotal is the
    project's flat_price_cents, and the actual logged hours are ignored entirely."
    PRD §3.7: "The tax_cents is that taxable amount multiplied by an 8% tax rate,
    rounded half up. Finally the grand_total_cents is the taxable amount plus the tax."

    Design: Difficulty/dual_variant_calc/billing_hourly_vs_project_labor_subtotal
    """
    client, organizer, project, session = setup_project_with_completed_session(
        billing_mode="PROJECT", flat_price_cents=50000, hourly_rate_cents=6000, logged_hours=10,
        scheduled_start="2026-03-03T09:00:00Z", scheduled_end="2026-03-03T19:00:00Z")
    invoice = validate_success(_issue(api, project["id"]), 201)
    # PROJECT billing: labor subtotal = flat_price_cents = 50000, logged hours ignored.
    assert invoice["labor_subtotal_cents"] == 50000
    # subtotal 50000 (< 200000, no discount); tax = round(50000*0.08) = 4000.
    assert invoice["grand_total_cents"] == 54000


# ── Difficulty: discount tier / pinned subtotal->discount->tax order ───────────

def test_invoice_tier1_discount_then_tax(api):
    """PRD §3.7: "Next a volume discount is keyed on that subtotal: if subtotal_cents
    is at least 500,000 cents the discount rate is 10%; otherwise if it is at least
    200,000 cents the discount rate is 5%; otherwise there is no discount."
    PRD §3.7: "The discount_cents is the subtotal multiplied by the applicable
    discount rate, rounded half up. The taxable amount is subtotal_cents minus
    discount_cents. The tax_cents is that taxable amount multiplied by an 8% tax rate,
    rounded half up. Finally the grand_total_cents is the taxable amount plus the tax."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_circular_mode_c
    """
    client, organizer, project, session = setup_project_with_completed_session(
        billing_mode="HOURLY", hourly_rate_cents=6000, logged_hours=40,
        scheduled_start="2026-03-02T06:00:00Z", scheduled_end="2026-03-02T22:00:00Z")
    invoice = validate_success(_issue(api, project["id"]), 201)
    # 40h weekday: 8*6000 + 32*6000*1.5 = 48000 + 288000 = 336000.
    assert invoice["subtotal_cents"] == 336000
    # >= 200000 -> 5%: discount = round(336000*0.05) = 16800; taxable 319200;
    # tax = round(319200*0.08) = 25536; grand = 319200 + 25536 = 344736.
    assert invoice["discount_cents"] == 16800
    assert invoice["tax_cents"] == 25536
    assert invoice["grand_total_cents"] == 344736


def test_invoice_tier2_discount_then_tax(api):
    """PRD §3.7: "Next a volume discount is keyed on that subtotal: if subtotal_cents
    is at least 500,000 cents the discount rate is 10%; otherwise if it is at least
    200,000 cents the discount rate is 5%; otherwise there is no discount."
    PRD §3.7: "The discount_cents is the subtotal multiplied by the applicable
    discount rate, rounded half up. The taxable amount is subtotal_cents minus
    discount_cents. The tax_cents is that taxable amount multiplied by an 8% tax rate,
    rounded half up. Finally the grand_total_cents is the taxable amount plus the tax."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_circular_mode_c
    """
    client, organizer, project = new_active_project(
        billing_mode="PROJECT", flat_price_cents=500000, scope_rooms=["Room"])
    invoice = validate_success(_issue(api, project["id"]), 201)
    # PROJECT flat 500000 -> subtotal 500000; >= 500000 -> 10%:
    # discount = round(500000*0.10) = 50000; taxable 450000;
    # tax = round(450000*0.08) = 36000; grand = 486000.
    assert invoice["subtotal_cents"] == 500000
    assert invoice["discount_cents"] == 50000
    assert invoice["tax_cents"] == 36000
    assert invoice["grand_total_cents"] == 486000


# ── Difficulty: no billable work (empty COMPLETED set) ────────────────────────

def test_no_billable_work_after_only_session_cancelled(api):
    """PRD §3.7: "There must be billable work: under HOURLY billing at least one
    COMPLETED session must exist, and under PROJECT billing flat_price_cents must be
    strictly greater than zero. If neither condition is met the issuance is rejected
    with ERR_NO_BILLABLE_WORK."

    Design: Difficulty/boundary_precision_check/invoice_no_billable_empty_completed_set
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"],
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    validate_success(api.patch_session(
        session["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)
    validate_error(_issue(api, project["id"]), "ERR_NO_BILLABLE_WORK", expected_status=422)


def test_no_billable_work_with_zero_sessions(api):
    """PRD §3.7: "There must be billable work: under HOURLY billing at least one
    COMPLETED session must exist, and under PROJECT billing flat_price_cents must be
    strictly greater than zero. If neither condition is met the issuance is rejected
    with ERR_NO_BILLABLE_WORK."

    Design: Difficulty/boundary_precision_check/invoice_no_billable_empty_completed_set
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    validate_error(_issue(api, project["id"]), "ERR_NO_BILLABLE_WORK", expected_status=422)


# ── Difficulty: unresolved-sessions check precedes billable-work check ─────────

def test_unresolved_sessions_reported_over_no_billable_in_progress(api):
    """PRD §3.7: "issuance layers four business checks, evaluated in this relative
    order:"
    PRD §3.7: "3. There must be no session for the project still in SCHEDULED or
    IN_PROGRESS; any unresolved session blocks issuance with ERR_UNRESOLVED_SESSIONS."
    PRD §3.7: "4. There must be billable work: under HOURLY billing at least one
    COMPLETED session must exist, and under PROJECT billing flat_price_cents must be
    strictly greater than zero. If neither condition is met the issuance is rejected
    with ERR_NO_BILLABLE_WORK."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_invoice_create
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"],
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    start_session(session["id"], organizer["id"])  # IN_PROGRESS, and zero COMPLETED
    validate_error(_issue(api, project["id"]), "ERR_UNRESOLVED_SESSIONS", expected_status=409)


def test_unresolved_sessions_reported_over_no_billable_scheduled(api):
    """PRD §3.7: "issuance layers four business checks, evaluated in this relative
    order:"
    PRD §3.7: "3. There must be no session for the project still in SCHEDULED or
    IN_PROGRESS; any unresolved session blocks issuance with ERR_UNRESOLVED_SESSIONS."
    PRD §3.7: "4. There must be billable work: under HOURLY billing at least one
    COMPLETED session must exist, and under PROJECT billing flat_price_cents must be
    strictly greater than zero. If neither condition is met the issuance is rejected
    with ERR_NO_BILLABLE_WORK."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_invoice_create
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    new_session(project["id"], organizer["id"],
                "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")  # SCHEDULED, zero COMPLETED
    validate_error(_issue(api, project["id"]), "ERR_UNRESOLVED_SESSIONS", expected_status=409)


# ── Difficulty: invoice creation requires sessions terminal ───────────────────

def test_invoice_blocked_by_scheduled_session(api):
    """PRD §3.7: "3. There must be no session for the project still in SCHEDULED or
    IN_PROGRESS; any unresolved session blocks issuance with ERR_UNRESOLVED_SESSIONS."

    Design: Difficulty/cross_entity_state_dependency/invoice_create_requires_sessions_terminal
    """
    client, organizer, project = new_active_project(hourly_rate_cents=5000, scope_rooms=["Room"])
    # One COMPLETED session provides billable work; one SCHEDULED session blocks.
    from test_helpers import add_completed_session
    add_completed_session(project["id"], organizer["id"], 3,
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    new_session(project["id"], organizer["id"],
                "2026-03-10T09:00:00Z", "2026-03-10T12:00:00Z")
    validate_error(_issue(api, project["id"]), "ERR_UNRESOLVED_SESSIONS", expected_status=409)


def test_invoice_issues_after_blocking_session_resolved(api):
    """PRD §3.7: "3. There must be no session for the project still in SCHEDULED or
    IN_PROGRESS; any unresolved session blocks issuance with ERR_UNRESOLVED_SESSIONS."
    PRD §3.7: "Issuance both creates the invoice in ISSUED status and transitions the
    project from ACTIVE to WRAP_UP, freezing further session creation for that project
    and incrementing the project's version by one."

    Design: Difficulty/cross_entity_state_dependency/invoice_create_requires_sessions_terminal
    """
    client, organizer, project = new_active_project(hourly_rate_cents=5000, scope_rooms=["Room"])
    from test_helpers import add_completed_session
    add_completed_session(project["id"], organizer["id"], 3,
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    blocker = new_session(project["id"], organizer["id"],
                          "2026-03-10T09:00:00Z", "2026-03-10T12:00:00Z")
    validate_error(_issue(api, project["id"]), "ERR_UNRESOLVED_SESSIONS", expected_status=409)
    # Resolve the blocking session (CANCELLED is no longer SCHEDULED/IN_PROGRESS).
    validate_success(api.patch_session(
        blocker["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)
    invoice = validate_success(_issue(api, project["id"]), 201)
    assert invoice["status"] == "ISSUED"
    project_after = validate_success(api.get_project(project["id"], OM), 200)
    assert project_after["status"] == "WRAP_UP"


# ── Difficulty: invoice dispute cycle ─────────────────────────────────────────

def test_invoice_dispute_then_resolve_cycle(api):
    """PRD §3.8: "A Client or a BillingAdmin may move an ISSUED invoice to DISPUTED,
    and may resolve a DISPUTED invoice back to ISSUED for re-review."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
    """
    client, organizer, project, session, invoice = setup_issued_invoice(logged_hours=3)
    disputed = validate_success(api.patch_invoice(
        invoice["id"], {"status": "DISPUTED"}, make_client_headers(client["id"])), 200)
    assert disputed["status"] == "DISPUTED"
    resolved = validate_success(api.patch_invoice(
        invoice["id"], {"status": "ISSUED"}, BA), 200)
    assert resolved["status"] == "ISSUED"


def test_invoice_payable_after_dispute_resolved(api):
    """PRD §3.8: "A Client or a BillingAdmin may move an ISSUED invoice to DISPUTED,
    and may resolve a DISPUTED invoice back to ISSUED for re-review."
    PRD §3.8: "Payment is only permitted on an invoice that is currently ISSUED:
    attempting to pay a DISPUTED invoice is rejected with ERR_INVOICE_NOT_PAYABLE, so
    a disputed invoice must first be resolved back to ISSUED."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
    """
    client, organizer, project, session, invoice = setup_issued_invoice(logged_hours=3)
    validate_success(api.patch_invoice(
        invoice["id"], {"status": "DISPUTED"}, make_client_headers(client["id"])), 200)
    validate_success(api.patch_invoice(invoice["id"], {"status": "ISSUED"}, BA), 200)
    paid = validate_success(api.pay_invoice(invoice["id"], BA), 200)
    assert paid["status"] == "PAID"


# ── Corner: pay a disputed invoice ────────────────────────────────────────────

def test_pay_disputed_invoice_returns_not_payable(api):
    """PRD §3.8: "Payment is only permitted on an invoice that is currently ISSUED:
    attempting to pay a DISPUTED invoice is rejected with ERR_INVOICE_NOT_PAYABLE, so
    a disputed invoice must first be resolved back to ISSUED."

    Design: Corner/state_machines/pay_disputed_invoice_returns_not_payable
    """
    client, organizer, project, session, invoice = setup_issued_invoice(logged_hours=3)
    validate_success(api.patch_invoice(
        invoice["id"], {"status": "DISPUTED"}, make_client_headers(client["id"])), 200)
    validate_error(api.pay_invoice(invoice["id"], BA), "ERR_INVOICE_NOT_PAYABLE")


# ── Corner: OCC stale project version ─────────────────────────────────────────

def test_invoice_stale_project_version_rejected(api):
    """PRD §2.7: "The server compares this value against the project's current
    version. If they do not match — because some other writer has advanced the
    project since the client last read it — the issuance is rejected with
    ERR_STALE_PROJECT_VERSION at HTTP status 412."

    Design: Corner/cross_cutting/occ_stale_project_version_returns_412
    """
    client, organizer, project, session = setup_project_with_completed_session(
        billing_mode="HOURLY", hourly_rate_cents=5000, logged_hours=3)
    current = project_version(project["id"])
    res = api.create_invoice(create_invoice_payload(project["id"], current - 1), BA)
    validate_error(res, "ERR_STALE_PROJECT_VERSION", expected_status=412)
