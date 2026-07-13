"""Role-based access control: exclusive operations and Boater resource ownership."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_boater_headers,
    create_marina,
    create_boater,
    setup_offered_permit,
    create_berth_payload,
    get_invoice,
)

HARBOR = TEST_USERS["harbormaster_headers"]


def test_boater_cannot_create_berth(api):
    """PRD §2.1: "The `Harbormaster` is the marina operations authority and is the
    only role permitted to create marinas, berths, and boater accounts"
    PRD §2.1: "A syntactically valid role that is not permitted to perform the
    requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/boater_cannot_create_berth_returns_403
    """
    marina = create_marina(api)
    boater = create_boater(api, full_name="Rb R", email="rb@example.com")
    validate_error(
        api.create_berth(create_berth_payload(marina["id"]), make_boater_headers(boater["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_harbormaster_cannot_waive_invoice(api):
    """PRD §2.1: "The `FinanceClerk` is the billing authority and is the only role
    permitted to waive an invoice."

    Design: Corner/rbac/harbormaster_cannot_waive_invoice_returns_403
    """
    b = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
    validate_error(api.waive_invoice(b["invoice_id"], HARBOR), ApiErrorId.ERR_UNAUTHORIZED)
    assert get_invoice(api, b["invoice_id"])["status"] == "UNPAID"


def test_boater_cannot_pay_another_boaters_invoice(api):
    """PRD §2.1: "When a `Boater` attempts a mutation on a resource that resolves
    to a different owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/boater_cannot_pay_unowned_invoice_returns_403
    """
    b = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
    other = create_boater(api, full_name="Owner2", email="o2@example.com")
    validate_error(
        api.pay_invoice(b["invoice_id"], {"amount_cents": 120000}, make_boater_headers(other["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )
    assert get_invoice(api, b["invoice_id"])["status"] == "UNPAID"
