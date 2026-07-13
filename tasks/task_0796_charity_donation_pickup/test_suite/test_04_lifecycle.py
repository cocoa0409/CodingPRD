"""Lifecycle and state-machine behaviour: the completion fork, the recurring
plan's cyclic machine, cross-entity resume gate, terminal lockdowns, and
generation.

Difficulty instances: non_linear_state_machine/{pickup_request_complete_branch_donation_vs_haul,
recurring_plan_pause_resume_cycle}, cross_entity_state_dependency/resume_requires_partner_active.
Corner instances: state_machines/*, validations/void_already_voided_receipt,
cross_cutting_complexity_layers/pay_already_paid_invoice.
"""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    create_partner, create_donor, create_recurring_plan,
    setup_schedulable_request, setup_scheduled_request,
    setup_completed_donation, setup_completed_haul, setup_paused_plan,
    make_donor_headers, make_partner_admin_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: completion fork DONATION vs HAUL ─────────────────────

def test_complete_donation_issues_receipt_and_no_invoice():
    """PRD §3.5: "the system issues a **donation receipt** in status `ISSUED`, recording the completed pickup through its `request_id`"
    PRD §3.5: "No haul invoice is created."

    Design: Difficulty/non_linear_state_machine/pickup_request_complete_branch_donation_vs_haul
    """
    ctx = setup_completed_donation()
    assert ctx["receipt"]["status"] == "ISSUED"
    invoices = validate_success(
        api.list_request_haul_invoices(ctx["request"]["id"], DISPATCHER), 200)
    assert len(invoices) == 0


def test_complete_haul_creates_invoice_and_no_receipt():
    """PRD §3.5: "When the disposition is HAUL: the system creates a haul invoice
    in status INVOICED, recording the billed pickup through its request_id ...
    No donation receipt is created."

    Design: Difficulty/non_linear_state_machine/pickup_request_complete_branch_donation_vs_haul
    """
    ctx = setup_completed_haul()
    assert ctx["invoice"]["status"] == "INVOICED"
    receipts = validate_success(
        api.list_receipts(DISPATCHER, params={"request_id": ctx["request"]["id"]}), 200)
    assert len(receipts) == 0


# ─── Difficulty: recurring plan cyclic pause/resume ───────────────────

def test_resume_returns_plan_to_active():
    """PRD §3.7: "Resuming advances a PAUSED plan PAUSED -> ACTIVE, but only if
    the plan's charity partner is currently ACTIVE"

    Design: Difficulty/non_linear_state_machine/recurring_plan_pause_resume_cycle
    """
    ctx = setup_paused_plan()
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    resumed = validate_success(api.resume_plan(ctx["plan"]["id"], donor_headers), 200)
    assert resumed["status"] == "ACTIVE"


def test_plan_version_increments_across_pause_resume_cycle():
    """PRD §2.4: "version: an integer that begins at creation and increments by
    one on every mutation of the resource."

    Design: Difficulty/non_linear_state_machine/recurring_plan_pause_resume_cycle
    """
    ctx = setup_paused_plan()  # create (v1) then pause (v2)
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    resumed = validate_success(api.resume_plan(ctx["plan"]["id"], donor_headers), 200)
    assert resumed["version"] == 3


# ─── Difficulty: resume gated by partner ACTIVE ───────────────────────

def test_resume_with_suspended_partner_rejected():
    """PRD §3.7: "resuming onto a `SUSPENDED` partner is refused with `ERR_PARTNER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/resume_requires_partner_active
    """
    ctx = setup_paused_plan()
    validate_success(
        api.update_partner(ctx["partner"]["id"], {"status": "SUSPENDED"}, PLATFORM), 200)
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    res = api.resume_plan(ctx["plan"]["id"], donor_headers)
    validate_error(res, "ERR_PARTNER_SUSPENDED", expected_status=409)


def test_resume_with_active_partner_succeeds():
    """PRD §3.7: "Resuming advances a PAUSED plan PAUSED -> ACTIVE, but only if
    the plan's charity partner is currently ACTIVE"

    Design: Difficulty/cross_entity_state_dependency/resume_requires_partner_active
    """
    ctx = setup_paused_plan()
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    resumed = validate_success(api.resume_plan(ctx["plan"]["id"], donor_headers), 200)
    assert resumed["status"] == "ACTIVE"


# ─── Corner: state-machine invalid transitions and lockdowns ──────────

def test_complete_request_still_requested_rejected():
    """PRD §3.5: "the same error guards completing or no-showing a request that
    is not SCHEDULED."

    Design: Corner/state_machines/complete_from_requested_returns_invalid_state
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], disposition="HAUL",
                                    items=[{"category": "FURNITURE", "volume_cf": 10}])
    res = api.complete_pickup(ctx["request"]["id"], {"measured_volume_cf": 10}, DRIVER)
    validate_error(res, "ERR_REQUEST_INVALID_STATE", expected_status=409)


def test_cancel_completed_request_rejected():
    """PRD §3.5: "A request that is already terminal admits none of these
    transitions and is rejected with ERR_REQUEST_INVALID_STATE"

    Design: Corner/state_machines/cancel_completed_request_terminal_lockdown
    """
    ctx = setup_completed_donation()
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    res = api.cancel_pickup(ctx["request"]["id"], donor_headers)
    validate_error(res, "ERR_REQUEST_INVALID_STATE", expected_status=409)


def test_pause_already_paused_plan_rejected():
    """PRD §3.7: "Pausing an ACTIVE plan advances it ACTIVE -> PAUSED"
    PRD §3.7: "Any lifecycle action attempted from a state that does not admit
    it is rejected with ERR_PLAN_INVALID_STATE."

    Design: Corner/state_machines/pause_already_paused_plan_idempotency_rejected
    """
    ctx = setup_paused_plan()
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    res = api.pause_plan(ctx["plan"]["id"], donor_headers)
    validate_error(res, "ERR_PLAN_INVALID_STATE", expected_status=409)


def test_generate_from_active_plan_materializes_requested_pickup():
    """PRD §3.7: "Generation creates a new REQUESTED pickup request stamped from
    the plan — carrying the plan's donor_id, partner_id, pickup_mode, address,
    and the plan's default_disposition as the request's disposition — with the
    request's recurring_plan_id set to this plan"

    Design: Corner/state_machines/recurring_generate_materializes_requested_pickup
    """
    partner = create_partner(accepted_categories=["FURNITURE"])
    donor = create_donor()
    plan = create_recurring_plan(donor["id"], partner["id"],
                                 frequency="MONTHLY", default_disposition="DONATION")
    new_req = validate_success(api.generate_plan(plan["id"], DISPATCHER), 201)
    assert new_req["status"] == "REQUESTED"
    assert new_req["disposition"] == "DONATION"
    assert new_req["recurring_plan_id"] == plan["id"]


def test_close_route_with_reserved_stop_rejected():
    """PRD §3.3: "A dispatcher later closes a route, advancing it OPEN -> CLOSED,
    but only while it is OPEN and only once no stop on it remains RESERVED — that
    is, every stop has been either serviced or cancelled; closing a route that is
    not OPEN is refused with ERR_ROUTE_INVALID_STATE."
    PRD §2.10: "6. Transition legality — the target resource is in a state that
    admits the requested transition (... ERR_ROUTE_INVALID_STATE ...)."

    Design: Corner/state_machines/close_route_with_reserved_stop_returns_invalid_state
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], disposition="DONATION",
                                  items=[{"category": "FURNITURE", "volume_cf": 20}])
    res = api.close_route(ctx["route"]["id"], DISPATCHER)
    validate_error(res, "ERR_ROUTE_INVALID_STATE", expected_status=409)


# ─── Corner: receipt/invoice terminal lockdowns ───────────────────────

def test_void_already_voided_receipt_rejected():
    """PRD §3.6: "voiding a receipt that is not `ISSUED` is rejected with `ERR_RECEIPT_NOT_VOIDABLE`."

    Design: Corner/validations/void_already_voided_receipt_returns_not_voidable
    """
    ctx = setup_completed_donation()
    admin_headers = make_partner_admin_headers(ctx["partner"]["id"])
    validate_success(api.void_receipt(ctx["receipt"]["id"], admin_headers), 200)
    res = api.void_receipt(ctx["receipt"]["id"], admin_headers)
    validate_error(res, "ERR_RECEIPT_NOT_VOIDABLE", expected_status=409)


def test_pay_already_paid_invoice_rejected():
    """PRD §3.6: "paying an invoice that is not `INVOICED` is rejected with `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/cross_cutting_complexity_layers/pay_already_paid_invoice_returns_invalid_state
    """
    ctx = setup_completed_haul()
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    validate_success(api.pay_invoice(ctx["invoice"]["id"], donor_headers), 200)
    res = api.pay_invoice(ctx["invoice"]["id"], donor_headers)
    validate_error(res, "ERR_INVOICE_INVALID_STATE", expected_status=409)
