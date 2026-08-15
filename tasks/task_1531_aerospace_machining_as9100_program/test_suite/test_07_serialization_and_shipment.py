"""Serialization, serial batches, shipment, and quantity conservation (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_po_quantity_conservation,
    assert_serial,
    create_accepted_cert,
    create_ncr,
    create_released_po,
    create_serial_batch_payload,
    create_work_order,
    get_purchase_order,
    get_success_data,
    get_work_order,
    setup_wo_completed,
    setup_wo_in_production,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager"]
MP = TEST_USERS["manufacturing_planner"]
QM = TEST_USERS["quality_manager"]
QI = TEST_USERS["quality_inspector"]
CQR = TEST_USERS["customer_quality_rep"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / po_quantity_conservation
# ---------------------------------------------------------------------------

def test_wo_creation_debits_po_unreleased_quantity(api):
    """PRD §3.5: "The quantity may not exceed the order's
    `unreleased_quantity` — `ERR_QUANTITY_EXCEEDS_UNRELEASED` on overflow, with
    equality allowed — and creation debits `unreleased_quantity` by the planned
    quantity."

    Design: Difficulty/compensating_invariant/po_quantity_conservation
    """
    bundle = create_released_po(quantity=10)
    po = bundle["po"]
    assert po["unreleased_quantity"] == 10
    wo1 = create_work_order(po["id"], quantity=6)
    wo2 = create_work_order(po["id"], quantity=4)
    po_mid = get_purchase_order(po["id"])
    assert po_mid["unreleased_quantity"] == 0, (
        f"10 - 6 - 4 must leave 0 unreleased, got {po_mid['unreleased_quantity']}"
    )
    assert_po_quantity_conservation(po_mid, [wo1["quantity"], wo2["quantity"]])


def test_wo_cancel_restores_po_unreleased_quantity(api):
    """PRD §3.5: "Cancellation moves `PLANNED` or `RELEASED` to `CANCELLED` —
    from any other state, `ERR_WO_NOT_CANCELLABLE` — and returns the work
    order's `quantity` to the order's `unreleased_quantity`."

    Design: Difficulty/compensating_invariant/po_quantity_conservation
    """
    bundle = create_released_po(quantity=10)
    po = bundle["po"]
    wo1 = create_work_order(po["id"], quantity=6)
    wo2 = create_work_order(po["id"], quantity=4)
    assert get_purchase_order(po["id"])["unreleased_quantity"] == 0
    cancelled = validate_success(api_client.cancel_work_order(wo1["id"], MP))
    assert cancelled["status"] == "CANCELLED"
    po_after = get_purchase_order(po["id"])
    assert po_after["unreleased_quantity"] == 6, (
        f"cancelling the 6-unit WO restores unreleased_quantity to 6, got "
        f"{po_after['unreleased_quantity']}"
    )
    assert_po_quantity_conservation(po_after, [wo2["quantity"]])


# ---------------------------------------------------------------------------
# Corner: entities / serial_number_system_format
# ---------------------------------------------------------------------------

def test_serial_number_system_format(api):
    """PRD §3.5: "Each created serial receives a system-assigned
    `serial_number` of the form SN-NNNN — a four-digit, zero-padded sequence
    per work order in creation order, beginning SN-0001 — and records its
    `wo_id` and `material_cert_id`; the cert's `quantity_available` is debited
    by the batch size."
    PRD §3.5: "The first successful batch moves the work order `RELEASED →
    IN_PRODUCTION` automatically."

    Design: Corner/entities/serial_number_system_format
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    serials = bundle["serials"]
    assert len(serials) == 2
    assert_serial(serials[0])
    assert serials[0]["serial_number"] == "SN-0001", (
        f"first serial of the work order must be SN-0001, got "
        f"{serials[0]['serial_number']}"
    )
    assert serials[1]["serial_number"] == "SN-0002"
    assert serials[0]["status"] == "CREATED"
    assert bundle["wo"]["status"] == "IN_PRODUCTION", (
        f"the first batch moves RELEASED -> IN_PRODUCTION, got "
        f"{bundle['wo']['status']}"
    )


# ---------------------------------------------------------------------------
# Corner: validations / material_batch_boundary_equal_allowed
# ---------------------------------------------------------------------------

def test_material_batch_boundary_equal_allowed(api):
    """PRD §3.5: "The batch size may not exceed the cert's
    `quantity_available` (`ERR_INSUFFICIENT_MATERIAL_QUANTITY`, equality
    allowed), and `serials_created_count` plus the batch `count` may not exceed
    the work order's `quantity` (`ERR_SERIAL_BATCH_EXCEEDS_QUANTITY`)."

    Design: Corner/validations/material_batch_boundary_equal_allowed
    """
    bundle = create_released_po(quantity=10)
    wo = create_work_order(bundle["po"]["id"], quantity=10)
    get_success_data(api_client.release_work_order(wo["id"], MP))
    cert = create_accepted_cert(quantity_received=5)

    batch = get_success_data(
        api_client.create_serial_batch(
            wo["id"], create_serial_batch_payload(material_cert_id=cert["id"], count=5), MP
        )
    )
    assert len(batch) == 5
    cert_after = get_success_data(api_client.get_material_cert(cert["id"], TEST_USERS["supply_chain_manager"]))
    assert cert_after["quantity_available"] == 0, (
        f"a batch equal to quantity_available drives it to zero, got "
        f"{cert_after['quantity_available']}"
    )
    resp = api_client.create_serial_batch(
        wo["id"], create_serial_batch_payload(material_cert_id=cert["id"], count=1), MP
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL_QUANTITY.value)


# ---------------------------------------------------------------------------
# Corner: validations / serial_batch_exceeds_wo_quantity_rejected
# ---------------------------------------------------------------------------

def test_serial_batch_exceeds_wo_quantity_rejected(api):
    """PRD §3.5: "The batch size may not exceed the cert's
    `quantity_available` (`ERR_INSUFFICIENT_MATERIAL_QUANTITY`, equality
    allowed), and `serials_created_count` plus the batch `count` may not exceed
    the work order's `quantity` (`ERR_SERIAL_BATCH_EXCEEDS_QUANTITY`)."

    Design: Corner/validations/serial_batch_exceeds_wo_quantity_rejected
    """
    bundle = create_released_po(quantity=3)
    wo = create_work_order(bundle["po"]["id"], quantity=3)
    get_success_data(api_client.release_work_order(wo["id"], MP))
    cert = create_accepted_cert(quantity_received=10)
    # Material is sufficient (4 <= 10) but 0 + 4 exceeds the WO quantity of 3.
    resp = api_client.create_serial_batch(
        wo["id"], create_serial_batch_payload(material_cert_id=cert["id"], count=4), MP
    )
    validate_error(resp, ApiErrorId.ERR_SERIAL_BATCH_EXCEEDS_QUANTITY.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / wo_complete_requires_serials_complete
# ---------------------------------------------------------------------------

def test_wo_complete_requires_serials_complete(api):
    """PRD §3.5: "Completing moves `IN_PRODUCTION → FINAL_INSPECTION` — from
    any other state, `ERR_WO_NOT_IN_PRODUCTION` — and requires the serial count
    to be complete, `serials_created_count` equal to the work order's
    `quantity` (`ERR_SERIALS_INCOMPLETE` otherwise), with no nonconformance
    report on this work order sitting in `OPEN` or `MRB_REVIEW`
    (`ERR_WO_OPEN_NCR` otherwise)."

    Design: Corner/state_machines/wo_complete_requires_serials_complete
    """
    bundle = setup_wo_in_production(wo_quantity=3, serial_count=2, quantity=3)
    resp = api_client.complete_work_order(bundle["wo"]["id"], MP)
    validate_error(resp, ApiErrorId.ERR_SERIALS_INCOMPLETE.value)
    after = get_work_order(bundle["wo"]["id"])
    assert after["status"] == "IN_PRODUCTION"


# ---------------------------------------------------------------------------
# Corner: state_machines / serial_ship_bubbles_po_close
# ---------------------------------------------------------------------------

def test_serial_ship_bubbles_po_close(api):
    """PRD §3.5: "A successful shipment stamps `shipped_at` with the logical
    clock, increments the parent order's `delivered_quantity` by one, and —
    when the delivered count reaches the ordered `quantity` — bubbles the order
    `RELEASED → CLOSED` automatically, contributing the order's `total_cents`
    to that calendar year's rebate gross per §3.1."

    Design: Corner/state_machines/serial_ship_bubbles_po_close
    """
    bundle = setup_wo_completed(wo_quantity=1, quantity=1)
    serial = bundle["serials"][0]
    shipped = validate_success(api_client.ship_serial(serial["id"], MP))
    assert_serial(shipped)
    assert shipped["status"] == "SHIPPED"
    assert shipped.get("shipped_at"), "shipment stamps shipped_at with the logical clock"
    po_after = get_purchase_order(bundle["po"]["id"])
    assert po_after["delivered_quantity"] == 1
    assert po_after["status"] == "CLOSED", (
        f"delivering the final unit must bubble the PO RELEASED -> CLOSED, got "
        f"{po_after['status']}"
    )


# ---------------------------------------------------------------------------
# Corner: validations / serial_ship_blocked_by_open_ncr
# ---------------------------------------------------------------------------

def test_serial_ship_blocked_by_open_ncr(api):
    """PRD §3.5: "Shipping moves one serial `CREATED → SHIPPED` — from any
    other state, `ERR_SERIAL_NOT_SHIPPABLE` — and its preconditions run in
    §2.11 order: the parent work order must be `COMPLETED`
    (`ERR_WO_NOT_ACCEPTABLE` otherwise); the serial's material cert must be
    `ACCEPTED` (`ERR_MATERIAL_CERT_REVOKED` otherwise); and no nonconformance
    report in `OPEN` or `MRB_REVIEW` may list this serial in its
    `affected_serial_ids` (`ERR_SERIAL_UNDER_NCR` otherwise)."

    Design: Corner/validations/serial_ship_blocked_by_open_ncr
    """
    bundle = setup_wo_completed(wo_quantity=2, quantity=2)
    s1, s2 = bundle["serials"][0], bundle["serials"][1]
    ncr = create_ncr(
        bundle["wo"]["id"],
        defect_code="MARKING",
        description="wrong marking on first serial",
        quantity_affected=1,
        affected_serial_ids=[s1["id"]],
        detected_post_shipment=False,
    )
    assert ncr["status"] == "OPEN"
    resp = api_client.ship_serial(s1["id"], MP)
    validate_error(resp, ApiErrorId.ERR_SERIAL_UNDER_NCR.value)
    # The unlisted serial ships normally.
    shipped = validate_success(api_client.ship_serial(s2["id"], MP))
    assert shipped["status"] == "SHIPPED"
