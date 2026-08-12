"""Cyclic state machines: PO dispute loop, notification resubmission loop,
shore-pass expiry/re-issue loop, and invalid/terminal transitions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    create_vendor, create_service_order, create_purchase_order,
    create_crew_change, create_notification,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers, make_vendor_rep_headers, make_crewing_agent_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / po_invoice_dispute_cycle
# ---------------------------------------------------------------------------

def _setup_delivered_po(estimated=10000):
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="sales@chandler.example")
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=estimated)
    vh = make_vendor_rep_headers(vendor["id"])
    get_success_data(api_client.send_purchase_order(po["id"], make_agency_ops_headers()))
    get_success_data(api_client.acknowledge_purchase_order(po["id"], vh))
    get_success_data(api_client.deliver_purchase_order(po["id"], vh))
    return pc, vendor, po, vh


def test_po_invoice_over_variance_forks_to_disputed(api):
    """PRD §3.4: "An absolute variance strictly greater than 10.0 percent
    routes the order to `DISPUTED` instead"; "The variance itself is the
    invoiced amount minus the estimate, divided by the estimate, expressed as
    a percentage and rounded half-up to two decimal places."

    Design: Difficulty/non_linear_state_machine/po_invoice_dispute_cycle
    """
    pc, vendor, po, vh = _setup_delivered_po(estimated=10000)
    po = validate_success(api_client.invoice_purchase_order(
        po["id"], {"invoiced_cents": 12000}, vh))
    assert po["status"] == "DISPUTED"
    assert po["variance_pct"] == 20.0, f"12000 on 10000 is 20.0; got {po['variance_pct']}"


def test_po_reinvoice_and_match_completes_dispute_loop(api):
    """PRD §3.4: "the owning `VendorRep` may reinvoice with a fresh
    `invoiced_cents`, which stores the new amount, recomputes the variance,
    returns the order to `INVOICED`"; "an `AgencyFinance` controller matches
    an `INVOICED` order ... Within tolerance, the order reaches `MATCHED`, its
    terminal state."

    Design: Difficulty/non_linear_state_machine/po_invoice_dispute_cycle
    """
    pc, vendor, po, vh = _setup_delivered_po(estimated=10000)
    po = validate_success(api_client.invoice_purchase_order(
        po["id"], {"invoiced_cents": 12000}, vh))
    assert po["status"] == "DISPUTED"
    po = validate_success(api_client.reinvoice_purchase_order(
        po["id"], {"invoiced_cents": 10500}, vh))
    assert po["status"] == "INVOICED"
    assert po["variance_pct"] == 5.0, f"10500 on 10000 is 5.0; got {po['variance_pct']}"
    po = validate_success(api_client.match_purchase_order(po["id"], make_agency_finance_headers()))
    assert po["status"] == "MATCHED", "loop DELIVERED -> DISPUTED -> INVOICED -> MATCHED traversed"


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / notification_reject_resubmit_cycle
# ---------------------------------------------------------------------------

def test_notification_reject_resubmit_counts_revisions(api):
    """PRD §3.2: "an `AgencyOps` agent may resubmit a `REJECTED` notification,
    which returns it to `SUBMITTED`, increments `revision_count`, restamps
    `submitted_at`, and retains the prior `rejection_reason` for audit."

    Design: Difficulty/non_linear_state_machine/notification_reject_resubmit_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    n = create_notification(pc["id"], "CUSTOMS", payload_summary="cus pkg")
    n = get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
    for _ in range(2):
        n = get_success_data(api_client.reject_notification(
            n["id"], {"reason": "forms incomplete"}, make_port_authority_headers()))
        assert n["status"] == "REJECTED"
        n = get_success_data(api_client.resubmit_notification(n["id"], make_agency_ops_headers()))
        assert n["status"] == "SUBMITTED"
    assert n["revision_count"] == 2, f"two reject/resubmit rounds; got {n['revision_count']}"
    assert n["rejection_reason"] == "forms incomplete", "reason retained through the loop"


def test_notification_acknowledge_after_resubmit_cycle(api):
    """PRD §3.2: "a `PortAuthority` officer acknowledges a `SUBMITTED` filing,
    recording the supplied `authority_reference` on the notification";
    "`ACKNOWLEDGED` and `WITHDRAWN` are the terminal states."

    Design: Difficulty/non_linear_state_machine/notification_reject_resubmit_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    n = create_notification(pc["id"], "CUSTOMS", payload_summary="cus pkg")
    n = get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
    n = get_success_data(api_client.reject_notification(
        n["id"], {"reason": "forms incomplete"}, make_port_authority_headers()))
    n = get_success_data(api_client.resubmit_notification(n["id"], make_agency_ops_headers()))
    n = get_success_data(api_client.acknowledge_notification(
        n["id"], {"authority_reference": "CUST-77"}, make_port_authority_headers()))
    assert n["status"] == "ACKNOWLEDGED"
    assert n["authority_reference"] == "CUST-77"
    assert n["revision_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: state_machines / ack_draft_notification_rejected
# ---------------------------------------------------------------------------

def test_acknowledge_draft_notification_rejected(api):
    """PRD §3.2: "a `PortAuthority` officer acknowledges a `SUBMITTED`
    filing"; "Every state-machine rejection on this lifecycle surfaces as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ack_draft_notification_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    n = create_notification(pc["id"], "CUSTOMS", payload_summary="x")
    resp = api_client.acknowledge_notification(
        n["id"], {"authority_reference": "X-1"}, make_port_authority_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    n_now = validate_success(api_client.get_authority_notification(n["id"], make_agency_ops_headers()))
    assert n_now["status"] == "DRAFT"
    assert n_now.get("authority_reference") is None


# ---------------------------------------------------------------------------
# Queue B: state_machines / cancel_terminal_service_order_rejected
# ---------------------------------------------------------------------------

def test_cancel_completed_service_order_rejected(api):
    """PRD §3.5: "An `AgencyOps` agent may cancel from `ORDERED` or
    `CONFIRMED` — other states fail with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_service_order_rejected
    """
    set_clock("2026-06-04T09:30:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-04T08:00:00Z", etd="2026-06-05T08:00:00Z")
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="t@x.example")
    vh = make_vendor_rep_headers(vendor["id"])
    so = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-1",
        window_start="2026-06-04T10:00:00Z", window_end="2026-06-04T11:00:00Z",
        estimated_cents=20000)
    get_success_data(api_client.confirm_service_order(so["id"], vh))
    get_success_data(api_client.start_service_order(so["id"], make_agency_ops_headers()))
    so = get_success_data(api_client.complete_service_order(
        so["id"], {"actual_cents": 21000}, make_agency_ops_headers()))
    assert so["status"] == "COMPLETED"
    resp = api_client.cancel_service_order(so["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    so_now = validate_success(api_client.get_service_order(so["id"], make_agency_ops_headers()))
    assert so_now["status"] == "COMPLETED"
    assert so_now["actual_cents"] == 21000


# ---------------------------------------------------------------------------
# Queue B: state_machines / notification_submit_twice_rejected
# ---------------------------------------------------------------------------

def test_notification_submit_twice_rejected(api):
    """PRD §3.2: "Submission by an `AgencyOps` agent moves a notification from
    `DRAFT` to `SUBMITTED`"; "Every state-machine rejection on this lifecycle
    surfaces as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/notification_submit_twice_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    n = create_notification(pc["id"], "IMMIGRATION", payload_summary="x")
    n = get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
    assert n["status"] == "SUBMITTED"
    resp = api_client.submit_notification(n["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    n_now = validate_success(api_client.get_authority_notification(n["id"], make_agency_ops_headers()))
    assert n_now["revision_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: state_machines / request_visa_when_not_required_rejected
# ---------------------------------------------------------------------------

def test_request_visa_when_not_required_rejected(api):
    """PRD §3.6: "Requesting a visa is only meaningful when the flag is set —
    a request on a movement with `requires_visa` false is rejected with
    `ERR_VISA_NOT_REQUIRED`."

    Design: Corner/state_machines/request_visa_when_not_required_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    cc = create_crew_change(pc["id"], requires_visa=False)
    cc = get_success_data(api_client.verify_docs(cc["id"], make_crewing_agent_headers()))
    assert cc["status"] == "DOCS_VERIFIED"
    resp = api_client.request_visa(cc["id"], make_crewing_agent_headers())
    validate_error(resp, ApiErrorId.ERR_VISA_NOT_REQUIRED)
    cc_now = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc_now["status"] == "DOCS_VERIFIED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / shore_pass_expiry_and_reissue_cycle
# ---------------------------------------------------------------------------

def test_shore_pass_expiry_and_reissue_cycle(api):
    """PRD §3.6: "on any read of the movement, and on any gate evaluation that
    consults it, a movement in `SHORE_PASS_ISSUED` whose `shore_pass_expires_at`
    the clock has passed flips to `PASS_EXPIRED`. Completion by a
    `CrewingAgent` requires the movement to read as `SHORE_PASS_ISSUED` after
    that lazy evaluation — an expired pass reads as `PASS_EXPIRED` and the
    completion fails with `ERR_INVALID_STATE`"; "And from `PASS_EXPIRED`, a
    fresh pass may be issued to replace the expired one."

    Design: Corner/state_machines/shore_pass_expiry_and_reissue_cycle
    """
    set_clock("2026-06-01T10:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-02T10:00:00Z", etd="2026-06-04T10:00:00Z")
    cc = create_crew_change(pc["id"], direction="OFF_SIGNER", requires_visa=False)
    cc = get_success_data(api_client.verify_docs(cc["id"], make_crewing_agent_headers()))
    cc = get_success_data(api_client.issue_shore_pass(
        cc["id"], {"shore_pass_expires_at": "2026-06-01T12:00:00Z"},
        make_crewing_agent_headers()))
    assert cc["status"] == "SHORE_PASS_ISSUED"
    set_clock("2026-06-01T12:00:01Z")
    cc = validate_success(api_client.get_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc["status"] == "PASS_EXPIRED", "lazy system transition on read"
    resp = api_client.complete_crew_change(cc["id"], make_crewing_agent_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    cc = get_success_data(api_client.issue_shore_pass(
        cc["id"], {"shore_pass_expires_at": "2026-06-03T00:00:00Z"},
        make_crewing_agent_headers()))
    assert cc["status"] == "SHORE_PASS_ISSUED", "re-issue from PASS_EXPIRED"
    cc = get_success_data(api_client.complete_crew_change(cc["id"], make_crewing_agent_headers()))
    assert cc["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / create_notification_on_cancelled_call_rejected
# ---------------------------------------------------------------------------

def test_create_notification_on_cancelled_call_rejected(api):
    """PRD §3.1: "creating or acting on any child resource of a call whose
    `ops_status` is `CANCELLED` or `CLOSED` is rejected with
    `ERR_PORT_CALL_NOT_EDITABLE`."

    Design: Corner/state_machines/create_notification_on_cancelled_call_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    get_success_data(api_client.cancel_port_call(pc["id"], make_agency_ops_headers()))
    resp = api_client.create_authority_notification(
        {"port_call_id": pc["id"], "authority_type": "CUSTOMS", "payload_summary": "x"},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_PORT_CALL_NOT_EDITABLE)
