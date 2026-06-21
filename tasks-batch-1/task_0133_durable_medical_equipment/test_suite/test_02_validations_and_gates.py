"""Validation rules and compliance gates on the order lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures,
    factories as f,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

PHYSICIAN = TEST_USERS["physician_headers"]


# ─── Corner §validations ──────────────────────────────
def test_acquisition_type_mismatch_on_create(api):
    """PRD §3.2: "items categorized CAPPED_RENTAL, OXYGEN, or INEXPENSIVE_ROUTINE
    must be ordered as RENTAL, while PURCHASE_ONLY items must be ordered as
    PURCHASE. A mismatch is rejected with ERR_ACQUISITION_TYPE_MISMATCH."

    Design: Corner/validations/acquisition_type_mismatch_on_create
    """
    patient = fixtures.create_patient()
    supplier = fixtures.create_supplier()
    item = fixtures.create_item(billing_category="CAPPED_RENTAL")
    sup_headers = make_supplier_headers(supplier["id"])

    resp = api.create_order(
        f.create_order_payload(
            patient["id"], supplier["id"], item["id"],
            acquisition_type="PURCHASE", modifier="NU",
        ),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACQUISITION_TYPE_MISMATCH.value)


def test_prior_auth_required_on_mark_ready(api):
    """PRD §3.6: "if the ordered item requires prior authorization, an
    authorization for the order must be in APPROVED status with an expires_at_utc
    strictly after the clock's current instant, failing which the transition is
    rejected with ERR_PRIOR_AUTH_REQUIRED."

    Design: Corner/validations/prior_auth_required_on_mark_ready
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_prior_auth": True},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    # Open a prior auth but leave it PENDING.
    get_success_data(
        api.create_prior_auth(f.create_prior_auth_payload(order["id"]), sup_headers)
    )
    resp = api.mark_ready(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value)


def test_supplier_not_accredited_on_mark_ready(api):
    """PRD §3.6: "the fulfilling supplier must be currently accredited — its
    accreditation_active flag must be true — failing which the transition is
    rejected with ERR_SUPPLIER_NOT_ACCREDITED."

    Design: Corner/validations/supplier_not_accredited_on_mark_ready
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
        supplier_overrides={"accreditation_active": False},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.mark_ready(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ACCREDITED.value)


def test_cmn_signed_after_order_rejected_on_activate(api):
    """PRD §3.3: "the certificate's signed_date must be on or before the calendar
    date of the order's ordered_at_utc; a certificate signed after the order was
    placed is rejected with ERR_CMN_SIGNED_AFTER_ORDER."

    Design: Corner/validations/cmn_signed_after_order_rejected_on_activate
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-01-01T00:00:00Z",
    )
    cmn = get_success_data(
        api.create_cmn(f.create_cmn_payload(order["id"], signed_date="2026-02-01"), PHYSICIAN)
    )
    resp = api.activate_cmn(cmn["id"], order["version"], PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_CMN_SIGNED_AFTER_ORDER.value)


def test_pod_signature_required_on_confirm(api):
    """PRD §3.5: "The confirm request must carry a non-empty pod_signature_name
    (the name of the person who signed for the equipment); an empty or absent
    signature is rejected with ERR_POD_SIGNATURE_REQUIRED."

    Design: Corner/validations/pod_signature_required_on_confirm
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    fixtures.drive_order_to_ready(order, supplier)
    sup_headers = make_supplier_headers(supplier["id"])
    delivery = get_success_data(
        api.create_delivery(f.create_delivery_payload(order["id"]), sup_headers)
    )
    resp = api.confirm_delivery(delivery["id"], "", sup_headers)
    validate_error(resp, ApiErrorId.ERR_POD_SIGNATURE_REQUIRED.value)


def test_not_a_cpap_order_on_resupply_create(api):
    """PRD §3.10: "The resupply order may only be created against an order whose
    catalog item has is_cpap true; an attempt to open one against a non-CPAP order
    is rejected with ERR_NOT_A_CPAP_ORDER."

    Design: Corner/validations/not_a_cpap_order_on_resupply_create
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "is_cpap": False},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.create_resupply(f.create_resupply_payload(order["id"]), sup_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CPAP_ORDER.value)


def test_cap_reached_rejects_further_rental_cycle(api):
    """PRD §3.7: "The equipment is then beneficiary-owned, and any further attempt
    to post a rental cycle is rejected with ERR_RENTAL_CAP_REACHED."
    PRD §3.7: "The cap check is evaluated first: if the order's cap_reached flag is
    true, the post is rejected with ERR_RENTAL_CAP_REACHED."

    Design: Corner/validations/cap_reached_rejects_further_rental_cycle
    """
    starts = fixtures.distinct_month_starts(13)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        13, with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.post_rental_cycle(
        order["id"], sup_headers, {"period_start_utc": "2027-02-01T00:00:00Z"}
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_CAP_REACHED.value)


# ─── Difficulty: cross_entity_state_dependency ────────
def test_mark_ready_requires_active_cmn_rejected_while_draft(api):
    """PRD §3.6: "if the ordered item requires a certificate of medical necessity,
    an ACTIVE certificate must exist for the order, failing which the transition is
    rejected with ERR_CMN_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_active_cmn
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    # Create a CMN but leave it DRAFT (not activated).
    get_success_data(
        api.create_cmn(f.create_cmn_payload(order["id"], signed_date="2025-12-15"), PHYSICIAN)
    )
    resp = api.mark_ready(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_CMN_REQUIRED.value)


def test_mark_ready_succeeds_once_cmn_active(api):
    """PRD §3.6: "if the ordered item requires a certificate of medical necessity,
    an ACTIVE certificate must exist for the order, failing which the transition is
    rejected with ERR_CMN_REQUIRED. ... When all applicable gates pass, the order
    advances to READY_FOR_DELIVERY."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_active_cmn
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
    )
    fixtures.activate_cmn_for_order(order, supplier, signed_date="2025-12-15")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.mark_ready(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "READY_FOR_DELIVERY"


def test_activate_billing_rejected_when_order_not_delivered(api):
    """PRD §3.6: "Once at least one delivery has confirmed and bubbled the order up
    to DELIVERED, a SupplierUser activates billing, moving the order from DELIVERED
    to ACTIVE. This requires the order to be in DELIVERED status (ERR_INVALID_STATE
    otherwise)."

    Design: Difficulty/cross_entity_state_dependency/activate_billing_requires_confirmed_delivery_pod
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    fixtures.drive_order_to_ready(order, supplier)
    sup_headers = make_supplier_headers(supplier["id"])
    # A FAILED delivery never bubbles the order to DELIVERED.
    delivery = get_success_data(
        api.create_delivery(f.create_delivery_payload(order["id"]), sup_headers)
    )
    get_success_data(api.fail_delivery(delivery["id"], sup_headers))

    resp = api.activate_billing(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_billing_succeeds_after_confirmed_delivery(api):
    """PRD §3.5: "On a successful confirm, the delivery moves to the terminal
    CONFIRMED status, its pod_received flag is set to true ... The confirmation then
    bubbles up to the order: the order advances from READY_FOR_DELIVERY to DELIVERED."
    PRD §3.6: "a SupplierUser activates billing, moving the order from DELIVERED to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/activate_billing_requires_confirmed_delivery_pod
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    fixtures.drive_order_to_delivered(order, supplier, pod_signature_name="Signer")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.activate_billing(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
