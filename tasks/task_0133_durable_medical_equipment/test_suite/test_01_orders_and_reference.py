"""DME order creation, reference data, and computed-field tests."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_order,
    fixtures,
    factories as f,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def test_create_dme_order_returns_201_with_default_fields(api):
    """PRD §3.2: "A newly created order is born in DRAFT status, with
    rental_months_billed initialized to 0, cap_reached initialized to false,
    and total_allowed_cents initialized to 0."
    PRD §2.4: "The version begins at 1 when the resource is created."

    Design: Corner/entities/create_dme_order_returns_201_with_fields
    """
    patient = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="PURCHASE_ONLY", monthly_rental_cents=0)
    sup_headers = make_supplier_headers(supplier["id"])

    resp = api.create_order(
        f.create_order_payload(
            patient["id"], supplier["id"], item["id"],
            acquisition_type="PURCHASE", modifier="NU",
        ),
        sup_headers,
    )
    data = validate_success(resp, 201)
    assert_order(data)
    assert data["status"] == "DRAFT"
    assert data["rental_months_billed"] == 0
    assert data["cap_reached"] is False
    assert data["total_allowed_cents"] == 0
    assert data["version"] == 1


def test_get_dme_order_not_found(api):
    """PRD §2.8: "When any referenced resource does not exist, the request is
    rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_dme_order_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, TEST_USERS["supplier_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "request well-formedness for any create-or-transition endpoint
    that carries a body (ERR_INVALID_REQUEST, raised when a required field is
    absent, an enum value is out of its allowed set, or a numeric value falls
    outside its stated bounds)."

    Design: Corner/entities/create_order_missing_required_field_returns_invalid_request
    """
    patient = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    sup_headers = make_supplier_headers(supplier["id"])

    resp = api.create_order(
        {
            "patient_id": patient["id"],
            "supplier_id": supplier["id"],
            "acquisition_type": "PURCHASE",
            "ordered_at_utc": "2026-01-01T00:00:00Z",
        },
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_bad_fk_target_returns_not_found(api):
    """PRD §2.8: "the foreign-key targets (patient, then supplier, then catalog
    item)." When any referenced resource does not exist, the request is rejected
    with ERR_NOT_FOUND (HTTP 404).

    Design: Corner/entities/create_order_bad_fk_target_returns_not_found
    """
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="PURCHASE_ONLY", monthly_rental_cents=0)
    sup_headers = make_supplier_headers(supplier["id"])

    resp = api.create_order(
        f.create_order_payload(
            NON_EXISTENT_UUID, supplier["id"], item["id"],
            acquisition_type="PURCHASE", modifier="NU",
        ),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_medicare_id_returns_conflict(api):
    """PRD §2.10: "An attempt to register a second patient, supplier, or catalog
    item reusing one of these values is rejected with ERR_DUPLICATE_VALUE (HTTP 409)."

    Design: Corner/entities/duplicate_medicare_id_returns_conflict
    """
    get_success_data(
        api.create_patient(f.create_patient_payload(medicare_id="MBI-DUP-1"), ADMIN)
    )
    resp = api.create_patient(
        f.create_patient_payload(
            full_name="Other", medicare_id="MBI-DUP-1", date_of_birth="1961-01-01",
            address_state="NY",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)


def test_supplier_accreditation_default_true(api):
    """PRD §3.1: "an accreditation_active flag indicating whether it is currently
    Medicare-accredited; when the flag is omitted at registration it defaults to true."

    Design: Corner/entities/supplier_accreditation_default_true
    """
    resp = api.create_supplier(
        {"name": "Default Sup", "ptan": "PTAN-DEFAULT-1"}, ADMIN
    )
    data = validate_success(resp, 201)
    assert data["accreditation_active"] is True


def test_purchase_order_computed_total_after_activate(api):
    """PRD §3.6: "When the modifier is NU, the full fee schedule is allowed — the
    allowed amount equals purchase_price_cents exactly."
    PRD §3.6: "one claim line of type PURCHASE is created with its allowed amount
    computed as described below, and the order's total_allowed_cents is then recomputed."

    Design: Corner/entities/purchase_order_computed_total_after_activate
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "PURCHASE_ONLY", "purchase_price_cents": 80000,
                        "monthly_rental_cents": 0},
        acquisition_type="PURCHASE", modifier="NU",
    )
    fixtures.drive_order_to_delivered(order, supplier, pod_signature_name="PU1")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.activate_billing(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["total_allowed_cents"] == 80000


def test_purchase_used_rate_when_modifier_not_nu(api):
    """PRD §3.6: "For any other modifier value, the equipment is paid at the
    used-equipment rate, which is 75 percent of purchase_price_cents, rounded half
    up to whole cents."

    Design: Corner/entities/purchase_used_rate_when_modifier_not_nu
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "PURCHASE_ONLY", "purchase_price_cents": 80000,
                        "monthly_rental_cents": 0},
        acquisition_type="PURCHASE", modifier="NONE",
    )
    fixtures.drive_order_to_delivered(order, supplier, pod_signature_name="PU2")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.activate_billing(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["total_allowed_cents"] == 60000


def test_system_fields_ignored_on_create(api):
    """PRD §3.2: "A newly created order is born in DRAFT status, with ... and
    total_allowed_cents initialized to 0."
    PRD §2.4: "The version begins at 1 when the resource is created."

    Design: Corner/entities/system_fields_ignored_on_create
    """
    patient = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="PURCHASE_ONLY", monthly_rental_cents=0)
    sup_headers = make_supplier_headers(supplier["id"])

    payload = f.create_order_payload(
        patient["id"], supplier["id"], item["id"],
        acquisition_type="PURCHASE", modifier="NU",
    )
    # Client attempts to seed system fields — must be ignored.
    payload.update({"total_allowed_cents": 999999, "version": 77})
    resp = api.create_order(payload, sup_headers)
    data = validate_success(resp, 201)
    assert data["total_allowed_cents"] == 0
    assert data["version"] == 1
