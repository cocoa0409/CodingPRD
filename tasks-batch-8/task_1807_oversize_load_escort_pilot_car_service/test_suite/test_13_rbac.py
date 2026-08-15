"""RBAC: auth context, role denial matrix, and entity-backed ownership."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    read_escort,
    set_clock,
    get_job,
    get_incident,
    get_invoice,
    get_assignment,
    setup_booked_job,
    setup_delivered_rear_job,
    offer_assignment,
    report_incident,
    generate_invoice,
    finalize_invoice,
    make_carrier_rep_headers,
    make_escort_operator_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SURVEYOR = TEST_USERS["route_surveyor_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    that is not one of the declared roles, is rejected with
    `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_carriers(None)
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)
    assert resp.status_code == 400


def test_rbac_role_forbidden_matrix(api):
    """PRD §2.1: "A request whose declared role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.11: "2. Role authorization: the caller's role must appear in the
    endpoint's authorized roles, else `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_role_forbidden_matrix
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider M")
    carrier = bundle["carrier"]
    esc = bundle["escort"]
    job_id = bundle["job"]["id"]
    inc = report_incident(
        job_id,
        incident_type="EQUIPMENT_DAMAGE",
        description="flag torn",
        claimed_amount_cents=2000,
    )
    inv = generate_invoice(job_id, "bc-1")
    finalize_invoice(inv["id"], "bc-2")

    rep = make_carrier_rep_headers(carrier["id"])
    denials = [
        # quote is Dispatcher-only (and job is DELIVERED — role check fires first)
        api.quote_job(job_id, rep),
        # accept-quote is CarrierRep-only
        api.accept_quote(job_id, DISPATCHER),
        # incident assess is SafetyManager/Dispatcher-only
        api.assess_incident(inc["id"], {"escort_fault_share_pct": 10}, make_escort_operator_headers(esc["id"])),
        # escort suspend is SafetyManager-only
        api.suspend_escort(esc["id"], SURVEYOR),
        # incident settle is FinanceManager-only
        api.settle_incident(inc["id"], BILLING),
        # invoice finalize is BillingClerk-only
        api.finalize_invoice(inv["id"], FINANCE),
        # record-payment is FinanceManager-only
        api.record_payment(inv["id"], {"amount_cents": 38520}, SAFETY),
        # logical clock is Dispatcher-only
        api.set_clock({"to_iso8601": "2026-08-11T00:00:00Z"}, rep),
    ]
    for resp in denials:
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    # No state changed under the denials.
    assert get_job(job_id)["job_status"] == "DELIVERED"
    assert get_incident(inc["id"])["incident_status"] == "REPORTED"
    assert get_invoice(inv["id"])["invoice_status"] == "FINALIZED"
    assert read_escort(esc["id"])["escort_status"] == "ACTIVE"


def test_ownership_forbidden_cross_principal(api):
    """PRD §2.1: "When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id`
    of the acting Carrier; ownership checks on any resource that references a
    Carrier compare the resource's `carrier_id` field to `X-User-ID`, and a
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is
    `EscortOperator`, `X-User-ID` is the `id` of the acting Escort; ownership
    checks on an assignment compare the assignment's `escort_id` field to
    `X-User-ID`, and a mismatch is likewise rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/ownership_forbidden_cross_principal
    """
    carrier_a = register_carrier(10_000_000, "Owner A")
    carrier_b = register_carrier(10_000_000, "Owner B")
    esc1 = register_escort(("TX",), "E1")
    esc2 = register_escort(("TX",), "E2")

    bundle = setup_booked_job(carrier_a, load_description="A's job")
    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc1["id"])

    # Correct role, wrong carrier.
    resp = api.cancel_job(bundle["job"]["id"], make_carrier_rep_headers(carrier_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_job(bundle["job"]["id"])["job_status"] == "BOOKED"

    # Correct role, wrong escort.
    resp2 = api.accept_assignment(asg["id"], make_escort_operator_headers(esc2["id"]))
    validate_error(resp2, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_assignment(asg["id"])["assignment_status"] == "OFFERED"
