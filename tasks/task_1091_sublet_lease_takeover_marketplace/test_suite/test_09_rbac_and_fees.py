"""Authentication / authorization / ownership gating, and the ad-hoc fee lifecycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_landlord_payload, create_lease_payload, make_landlord_headers, make_applicant_headers,
    new_landlord, new_leaseholder, new_applicant, setup_scenario,
)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_landlord(create_landlord_payload(name="X", email="x@x.com"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_platform_admin_cannot_create_lease(api):
    """PRD §2.1: "When a request carries a role that exists but is not permitted to
    perform the requested operation, the platform responds with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_create_lease_unauthorized
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    payload = create_lease_payload(landlord["id"], leaseholder["id"])
    resp = api.create_lease(payload, TEST_USERS["admin_headers"])  # PlatformAdmin, only Landlord may
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_applicant_cannot_apply_as_other_applicant(api):
    """PRD §2.1: "When an entity-backed actor targets a resource they do not own, the
    request is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_apply_as_other_applicant_ownership
    """
    ctx = setup_scenario(api, stage="listing_open")
    applicant_b = new_applicant(api, name="B", email="b@x.com")
    # Acting applicant A submits an application whose applicant_id is B.
    resp = api.create_application(
        {"listing_id": ctx["listing"]["id"], "applicant_id": applicant_b["id"],
         "proposed_move_in_date": "2026-06-10", "proposed_move_out_date": "2026-08-31"},
        make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


def test_fee_lifecycle_charge_then_refund(api):
    """PRD §3.9: "From `PENDING`, the admin either charges the fee (moving it to terminal
    `CHARGED`) or waives it". PRD §3.9: "A `CHARGED` fee may later be refunded, moving it
    to terminal `REFUNDED`".

    Design: Corner/state_machines/fee_lifecycle_charge_then_refund
    """
    ctx = setup_scenario(api, stage="drafted")
    fee = validate_success(api.create_fee(
        {"agreement_id": ctx["agreement"]["id"], "fee_type": "SCREENING", "amount_cents": 5000},
        TEST_USERS["admin_headers"]), 201)
    charged = validate_success(api.charge_fee(fee["id"], TEST_USERS["admin_headers"]))
    assert charged["status"] == "CHARGED", f"charge must move fee to CHARGED, got {charged['status']}"
    refunded = validate_success(api.refund_fee(fee["id"], TEST_USERS["admin_headers"]))
    assert refunded["status"] == "REFUNDED", f"refund must move fee to REFUNDED, got {refunded['status']}"
