"""Role-based access control and list/filter endpoints."""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    fixtures,
    factories as f,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
PAYER = TEST_USERS["payer_headers"]


# ─── Corner: §rbac ────────────────────────────────────
def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected
    with ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    no_auth_headers = {"Content-Type": "application/json"}
    resp = api.create_order(
        f.create_order_payload(
            "00000000-0000-4000-8000-0000000000bb",
            "00000000-0000-4000-8000-0000000000cc",
            "00000000-0000-4000-8000-0000000000dd",
            acquisition_type="PURCHASE", modifier="NU",
        ),
        no_auth_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_physician_cannot_create_order(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/physician_cannot_create_order
    """
    patient = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="CAPPED_RENTAL")
    resp = api.create_order(
        f.create_order_payload(patient["id"], supplier["id"], item["id"]),
        PHYSICIAN,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_supplier_cannot_uphold_audit(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/supplier_cannot_uphold_audit
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    audit = fixtures.open_audit(order, "NO_VALID_CMN")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.uphold_audit(audit["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ─── Corner: §endpoints ───────────────────────────────
def test_list_dme_orders_filtered_by_patient(api):
    """PRD §3.2: "the same three roles may list orders, optionally filtering by
    patient_id, supplier_id, hcpcs_item_id, or status."
    PRD §2.3: "the meta object additionally carries limit, offset, total_count
    (the count of records matching the filter before pagination), and has_more."

    Design: Corner/endpoints/list_dme_orders_paginated_filtered_by_patient
    """
    px = fixtures.create_patient()
    py = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="CAPPED_RENTAL")
    sup_headers = make_supplier_headers(supplier["id"])

    for ordered_at in ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"):
        get_success_data(
            api.create_order(
                f.create_order_payload(px["id"], supplier["id"], item["id"],
                                       ordered_at_utc=ordered_at),
                sup_headers,
            )
        )
    get_success_data(
        api.create_order(
            f.create_order_payload(py["id"], supplier["id"], item["id"],
                                   ordered_at_utc="2026-03-01T00:00:00Z"),
            sup_headers,
        )
    )

    data, meta = validate_paginated(
        api.list_orders(ADMIN, params={"patient_id": px["id"], "limit": 10, "offset": 0})
    )
    assert len(data) == 2
    assert all(o["patient_id"] == px["id"] for o in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_deliveries_filtered_by_order(api):
    """PRD §3.5: "Deliveries may be retrieved individually or listed by a
    SupplierUser or PayerReviewer, filterable by order_id or status."

    Design: Corner/endpoints/list_deliveries_filtered_by_order
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    delivery = get_success_data(
        api.create_delivery(f.create_delivery_payload(order["id"]), sup_headers)
    )
    data, meta = validate_paginated(
        api.list_deliveries(sup_headers, params={"order_id": order["id"], "limit": 100})
    )
    assert len(data) == 1
    assert data[0]["id"] == delivery["id"]
    assert data[0]["order_id"] == order["id"]
