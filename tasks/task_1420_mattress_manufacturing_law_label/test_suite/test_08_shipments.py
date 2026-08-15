"""Shipments: creation gates, dispatch/deliver, and label dependency (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_shipment,
    create_shipment_payload,
    add_approved_flammability_cert,
    setup_complete_order,
    qc_pass_order,
    place_order,
    allocate_order,
    list_order_units,
    generate_label,
)

PM = TEST_USERS["plant_manager_headers"]
CO1 = TEST_USERS["compliance_creator_headers"]
CO2 = TEST_USERS["compliance_approver_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]
LOG1 = TEST_USERS["logistics_headers"]


def test_deliver_on_created_shipment_rejected(api):
    """PRD §3.8: "Delivering a shipment (`DISPATCHED` → `DELIVERED`; guarded
    by `ERR_SHIPMENT_NOT_DISPATCHED`) moves every unit from `SHIPPED` to
    `DELIVERED`, stamps each unit's `delivered_at` from the logical clock, and
    recomputes fulfillment again."

    Design: Corner/state_machines/shipment_deliver_from_created_rejected
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    qc_pass_order(ctx)
    unit_id = ctx["units"][0]["id"]
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[unit_id]), LOG1
    ))
    assert shipment["status"] == "CREATED"

    resp = api.deliver_shipment(shipment["id"], LOG1)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DISPATCHED)

    unit = get_success_data(api.get_unit(unit_id, PM))
    assert unit["status"] == "MANUFACTURED"


def test_shipment_with_unit_from_other_order_rejected(api):
    """PRD §3.8: "every listed unit must belong to the shipment's order
    (`ERR_UNIT_ORDER_MISMATCH`, 422) and be in `MANUFACTURED` status
    (`ERR_UNITS_NOT_MANUFACTURED`, 409)."

    Design: Corner/validations/shipment_unit_order_mismatch_rejected
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    qc_pass_order(ctx)
    u1 = ctx["units"][0]["id"]

    # A second complete order under the same model/retailer/state.
    order2 = place_order(ctx["model"]["id"], ctx["retailer"]["id"], state_code="CA",
                         quantity=1, unit_price_cents=200000, foam_mass_required_kg=10)
    allocate_order(order2["id"], ctx["batch"]["id"])
    get_success_data(api.start_production(order2["id"], LS1))
    get_success_data(api.complete_production(order2["id"], LS1))
    get_success_data(api.qc_pass_order(order2["id"], QC1))
    u2 = list_order_units(order2["id"])[0]["id"]

    resp = api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[u2]), LOG1
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_ORDER_MISMATCH)


def test_shipment_blocked_after_label_superseded_until_new_label(api):
    """PRD §3.8: "an `ACTIVE` law label must exist for the order's model and
    destination state (`ERR_LABEL_NOT_ACTIVE`)"
    PRD §3.3: "Expiry never cascades: existing law labels keep their status
    and units already manufactured remain valid. Expiry only blocks new
    shipments (with `ERR_CERT_EXPIRED`) and new model certifications (with
    `ERR_CERT_REQUIRED`). Only an explicit revoke cascades."

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_active_law_label
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    qc_pass_order(ctx)
    unit_id = ctx["units"][0]["id"]

    # Revoke the last flammability cert: the cascade supersedes the label.
    # The order is COMPLETE, so it is beyond the cascade's hold set.
    get_success_data(api.revoke_certificate(ctx["model"]["id"], ctx["cert"]["id"], CO2))
    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["production_status"] == "COMPLETE"

    # A fresh approved cert restores the model's certificate side (the model
    # fell back to CERT_REVIEW, where new certificates are accepted) — but no
    # ACTIVE label exists for the destination state.
    add_approved_flammability_cert(
        ctx["model"]["id"], issued_on="2026-08-02T00:00:00Z",
        expires_on="2031-01-01T00:00:00Z",
    )

    resp = api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[unit_id]), LOG1
    )
    validate_error(resp, ApiErrorId.ERR_LABEL_NOT_ACTIVE)


def test_shipment_succeeds_after_label_regenerated_and_activated(api):
    """PRD §3.8: "an `ACTIVE` law label must exist for the order's model and
    destination state (`ERR_LABEL_NOT_ACTIVE`)"
    PRD §3.4: "Activating a label supersedes any other `ACTIVE` label for the
    same model and `state_code`; this voluntary replacement holds no
    production orders, unlike the revoke cascade of §3.3, which moves labels
    in `GENERATED`, `APPROVED`, or `ACTIVE` to `SUPERSEDED` and pushes
    matching open orders into `QC_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_active_law_label
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    qc_pass_order(ctx)
    unit_id = ctx["units"][0]["id"]
    model_id = ctx["model"]["id"]

    get_success_data(api.revoke_certificate(model_id, ctx["cert"]["id"], CO2))
    add_approved_flammability_cert(
        model_id, issued_on="2026-08-02T00:00:00Z", expires_on="2031-01-01T00:00:00Z",
    )
    # Recertify the model (CERT_REVIEW -> CERTIFIED), then regenerate and
    # activate a fresh label pinned to the still-PUBLISHED spec.
    get_success_data(api.certify_model(model_id, CO1))
    label = generate_label(model_id, "CA")
    get_success_data(api.approve_law_label(model_id, label["id"], CO2))
    activated = validate_success(api.activate_law_label(model_id, label["id"], CO2))
    assert activated["status"] == "ACTIVE"

    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[unit_id]), LOG1
    ), expected_status=201)
    assert_shipment(shipment)
    assert shipment["status"] == "CREATED"
    assert shipment["order_id"] == ctx["order"]["id"]
