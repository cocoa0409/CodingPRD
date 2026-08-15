"""Certificate expiry/revocation and the three-hop cascade (PRD §3.3, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    setup_allocated_order,
    setup_complete_order,
    qc_pass_order,
    place_order,
    allocate_order,
    list_order_units,
    add_approved_flammability_cert,
)

PM = TEST_USERS["plant_manager_headers"]
CO1 = TEST_USERS["compliance_creator_headers"]
CO2 = TEST_USERS["compliance_approver_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]
LOG1 = TEST_USERS["logistics_headers"]


def test_revoke_last_flammability_cert_returns_model_to_cert_review(api):
    """PRD §3.3: "When a revoked certificate was the model's last `APPROVED`
    unexpired `FLAMMABILITY_16CFR1633` certificate, hop one moves the model
    from `CERTIFIED` or `ACTIVE` back to `CERT_REVIEW`, incrementing its
    `version`."

    Design: Difficulty/transitive_cascade/certificate_revoke_depth3_cascade
    """
    ctx = setup_allocated_order(quantity=2, foam_mass_required_kg=20)
    model_id = ctx["model"]["id"]

    revoked = validate_success(
        api.revoke_certificate(model_id, ctx["cert"]["id"], CO2)
    )
    assert revoked["status"] == "REVOKED"

    model = get_success_data(api.get_model(model_id, PM))
    assert model["status"] == "CERT_REVIEW", (
        f"Model must fall back to CERT_REVIEW when its last flammability cert "
        f"is revoked, got {model['status']}"
    )


def test_revoke_cascade_supersedes_label_and_holds_open_order(api):
    """PRD §3.3: "Hop two supersedes the model's paperwork: every law label of
    the model in `GENERATED`, `APPROVED`, or `ACTIVE` moves to `SUPERSEDED`.
    Hop three reaches the floor: each superseded label pushes every production
    order with `production_status` in `MATERIAL_ALLOCATED`, `IN_PRODUCTION`,
    or `QC_PENDING` whose `destination_state_code` equals that label's
    `state_code` into `QC_HOLD`."

    Design: Difficulty/transitive_cascade/certificate_revoke_depth3_cascade
    """
    ctx = setup_allocated_order(state_code="CA", quantity=2, foam_mass_required_kg=20)
    model_id = ctx["model"]["id"]
    assert ctx["label"]["status"] == "ACTIVE"
    assert ctx["order"]["production_status"] == "MATERIAL_ALLOCATED"

    get_success_data(api.revoke_certificate(model_id, ctx["cert"]["id"], CO2))

    label = get_success_data(api.get_law_label(ctx["label"]["id"], PM))
    assert label["status"] == "SUPERSEDED", (
        f"ACTIVE label must be superseded by the revoke cascade, got {label['status']}"
    )
    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["production_status"] == "QC_HOLD", (
        f"Open order for the label's state must be held, got {order['production_status']}"
    )


def test_revoke_cascade_skips_complete_orders(api):
    """PRD §3.3: "Hop three reaches the floor: each superseded label pushes
    every production order with `production_status` in `MATERIAL_ALLOCATED`,
    `IN_PRODUCTION`, or `QC_PENDING` whose `destination_state_code` equals
    that label's `state_code` into `QC_HOLD`. An order already in `QC_HOLD` or
    beyond stays where it is."

    Design: Corner/state_machines/revoke_cascade_skips_complete_orders
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    qc_pass_order(ctx)  # order o1 -> COMPLETE
    complete_order_id = ctx["order"]["id"]

    # Second order for the same model+state, stopped at MATERIAL_ALLOCATED.
    order2 = place_order(
        ctx["model"]["id"], ctx["retailer"]["id"], state_code="CA",
        quantity=1, unit_price_cents=200000, foam_mass_required_kg=10,
    )
    allocate_order(order2["id"], ctx["batch"]["id"])

    get_success_data(api.revoke_certificate(ctx["model"]["id"], ctx["cert"]["id"], CO2))

    o1 = get_success_data(api.get_production_order(complete_order_id, PM))
    assert o1["production_status"] == "COMPLETE", (
        "COMPLETE order is beyond the cascade's hold set and must stay COMPLETE"
    )
    o2 = get_success_data(api.get_production_order(order2["id"], PM))
    assert o2["production_status"] == "QC_HOLD"


def test_shipment_rejected_when_flammability_cert_expired(api):
    """PRD §3.3: "Expiry never cascades: existing law labels keep their status
    and units already manufactured remain valid. Expiry only blocks new
    shipments (with `ERR_CERT_EXPIRED`) and new model certifications (with
    `ERR_CERT_REQUIRED`). Only an explicit revoke cascades."
    PRD §3.8: "the model's flammability certificate must be `APPROVED` and
    unexpired at shipment time — expired or absent, it is `ERR_CERT_EXPIRED`"

    Design: Corner/validations/shipment_with_expired_cert_rejected
    """
    ctx = setup_complete_order(
        state_code="CA", quantity=1, foam_mass_required_kg=10,
        cert_expires_on="2026-08-05T00:00:00Z",
    )
    qc_pass_order(ctx)
    unit_id = ctx["units"][0]["id"]

    # Advance past the certificate's expiry; the label stays ACTIVE.
    get_success_data(api.set_clock("2026-08-06T00:00:00Z", PM))

    resp = api.create_shipment(
        {"order_id": ctx["order"]["id"], "unit_ids": [unit_id]}, LOG1
    )
    validate_error(resp, ApiErrorId.ERR_CERT_EXPIRED)


def test_shipment_state_check_masks_regulatory_label_check(api):
    """PRD §2.8: "Every request is evaluated against a fixed pipeline of
    twelve validation tiers, and an earlier tier masks later ones — a failure
    surfaces the error of the earliest tier it violates, and only a request
    clean through a tier reaches the next"
    PRD §3.8: "Creation enforces a stack of gates in the pipeline order of
    §2.8: the order must be in `production_status` `COMPLETE`
    (`ERR_ORDER_NOT_COMPLETE`); an `ACTIVE` law label must exist for the
    order's model and destination state (`ERR_LABEL_NOT_ACTIVE`); the model's
    flammability certificate must be `APPROVED` and unexpired at shipment
    time — expired or absent, it is `ERR_CERT_EXPIRED`; and every listed unit
    must belong to the shipment's order (`ERR_UNIT_ORDER_MISMATCH`, 422) and
    be in `MANUFACTURED` status (`ERR_UNITS_NOT_MANUFACTURED`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/shipment_state_check_beats_label_safety_check
    """
    # Order driven to QC_PENDING, then the revoke cascade supersedes the
    # label (tier-6 failure) and pushes the order to QC_HOLD (tier-5 failure).
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    get_success_data(api.revoke_certificate(ctx["model"]["id"], ctx["cert"]["id"], CO2))
    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["production_status"] == "QC_HOLD"

    resp = api.create_shipment(
        {"order_id": ctx["order"]["id"], "unit_ids": [ctx["units"][0]["id"]]}, LOG1
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_COMPLETE)


def test_shipment_state_check_fires_with_label_active(api):
    """PRD §3.8: "Creation enforces a stack of gates in the pipeline order of
    §2.8: the order must be in `production_status` `COMPLETE`
    (`ERR_ORDER_NOT_COMPLETE`); an `ACTIVE` law label must exist for the
    order's model and destination state (`ERR_LABEL_NOT_ACTIVE`); the model's
    flammability certificate must be `APPROVED` and unexpired at shipment
    time — expired or absent, it is `ERR_CERT_EXPIRED`; and every listed unit
    must belong to the shipment's order (`ERR_UNIT_ORDER_MISMATCH`, 422) and
    be in `MANUFACTURED` status (`ERR_UNITS_NOT_MANUFACTURED`, 409)."
    PRD §3.7: "Passing moves `QC_PENDING` → `COMPLETE`; holding moves
    `QC_PENDING` → `QC_HOLD`; both are guarded by `ERR_ORDER_NOT_QC_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/shipment_state_check_beats_label_safety_check
    """
    # Label stays ACTIVE and the cert stays valid; the order alone is held.
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    held = validate_success(api.qc_hold_order(ctx["order"]["id"], QC1))
    assert held["production_status"] == "QC_HOLD"

    resp = api.create_shipment(
        {"order_id": ctx["order"]["id"], "unit_ids": [ctx["units"][0]["id"]]}, LOG1
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_COMPLETE)
