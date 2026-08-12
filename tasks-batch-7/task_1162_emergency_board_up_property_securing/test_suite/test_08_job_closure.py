"""Repair verification, removal gating, invoice-ledger-gated closure, and the
terminal lockdown of a CLOSED job."""
from test_helpers import (
    assert_invoice_invariants,
    create_invoice,
    create_service,
    get_job,
    make_customer_headers,
    make_subcontractor_headers,
    register_customer,
    setup_closed_job,
    setup_removed_job,
    setup_secured_job,
    validate_error,
    verify_repair,
)


def test_verify_repair_rejection_reverts_to_secured(api, dispatcher_headers):
    """PRD §3.9: "The owning customer verifies the repair with an `outcome` of
    `VERIFIED`, moving the job `SECURED` → `READY_FOR_REMOVAL`; if the
    verification proves premature, the same customer retracts it with `REJECTED`,
    moving the job `READY_FOR_REMOVAL` → `SECURED` with the securing left in
    place."

    Design: Corner/state_machines/verify_repair_rejection_reverts_to_secured
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")

    verified = verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    assert verified["work_status"] == "READY_FOR_REMOVAL"

    retracted = verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "REJECTED")
    assert retracted["work_status"] == "SECURED", "retracted verification restores SECURED"


def test_customer_cannot_verify_foreign_job(api, dispatcher_headers):
    """PRD §2.1: "Ownership checks on any resource that references a `Customer`
    compare the resource's `customer_id` field to `X-User-ID`; a mismatch on a
    customer-gated action (verifying a permanent repair, disputing an invoice) is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_verify_foreign_job
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    stranger = register_customer(full_name="Eve Else", email="eve@x.com")

    res = api.verify_repair(ctx["job"]["id"], {"outcome": "VERIFIED"},
                            make_customer_headers(stranger["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    assert get_job(ctx["job"]["id"])["work_status"] == "SECURED", "no transition may fire"


def test_services_still_active_rejected(api, dispatcher_headers):
    """PRD §3.9: "Removal is blocked while any temporary service of the job is
    still `ACTIVE` or `PAUSED` — everything must be deactivated first, else
    `ERR_SERVICES_STILL_ACTIVE` — and success moves the job `READY_FOR_REMOVAL` →
    `REMOVED`."

    Design: Corner/endpoints/services_still_active_rejected
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    create_service(ctx["job"]["id"], "PATROL",
                   "2026-05-02T08:00:00Z", "2026-05-05T08:00:00Z")
    verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    assert get_job(ctx["job"]["id"])["work_status"] == "READY_FOR_REMOVAL"

    res = api.record_removal(ctx["job"]["id"],
                             make_subcontractor_headers(ctx["assignee"]["id"]))
    validate_error(res, "ERR_SERVICES_STILL_ACTIVE")
    assert get_job(ctx["job"]["id"])["work_status"] == "READY_FOR_REMOVAL", (
        "no transition may fire while services remain")


def test_invoices_unpaid_close_rejected(api, dispatcher_headers):
    """PRD §3.9: "Closure is the last act and belongs to the `Dispatcher`: the job
    must carry at least one `FINAL` invoice, and every invoice of the job must be
    `PAID`, or the close is rejected with `ERR_INVOICES_UNPAID`."

    Design: Corner/endpoints/invoices_unpaid_close_rejected
    """
    ctx = setup_removed_job(market_preset="PDX")
    final = create_invoice(ctx["job"]["id"], "FINAL")  # left DRAFT
    assert final["status"] == "DRAFT"

    res = api.close_job(ctx["job"]["id"], dispatcher_headers)
    validate_error(res, "ERR_INVOICES_UNPAID")
    assert get_job(ctx["job"]["id"])["work_status"] == "REMOVED"


def test_closed_job_terminal_lockdown_rejected(api, dispatcher_headers):
    """PRD §3.2: "a dispatch attempted on a job not currently in `INTAKE` is
    rejected with `ERR_INVALID_STATE` — or `ERR_ALREADY_TERMINAL` for a `CLOSED`
    job — before any coverage pool is consulted."
    PRD §3.9: "A successful close moves the job `REMOVED` → `CLOSED`, the job's
    terminal state."

    Design: Corner/state_machines/closed_job_terminal_lockdown_rejected
    """
    ctx = setup_closed_job(priority="P3", market_preset="PDX")
    assert ctx["job"]["work_status"] == "CLOSED"
    assert_invoice_invariants(ctx["final_invoice"])
    assert ctx["final_invoice"]["total_cents"] == 29000, "work 4000 + removal 25000"

    res = api.dispatch_job(ctx["job"]["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_ALREADY_TERMINAL")
    assert get_job(ctx["job"]["id"])["work_status"] == "CLOSED"
