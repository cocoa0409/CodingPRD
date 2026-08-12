"""Cross-entity gate: application scheduling requires a DELIVERED box
(PRD 3.7)."""
import test_helpers as th


def test_application_create_requires_delivered_box(api):
    """PRD 3.7: "Creating an application task takes the `subscription_id`, the `shipment_id` of a box that must be `DELIVERED` — otherwise `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409) — and that must belong to the subscription, the `product_sku` being applied, and a `scheduled_date` in year-month-day form."

    Design: Difficulty/cross_entity_state_dependency/application_create_requires_delivered_box
    """
    ctx = th.setup_active_subscription(email="ad@x.com")
    box = th.create_box(ctx["subscription"]["id"],
                        lines=[th.shipment_line("FERT-01", 1)])
    th.advance_box_to(box["id"], "SHIPPED")

    # While SHIPPED (not yet DELIVERED) the scheduling request is rejected.
    th.validate_error(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-12"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED,
    )

    # After DELIVERED, the identical request succeeds.
    th.advance_box(box["id"], "DELIVERED")
    task = th.validate_success(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-12"),
            ctx["customer_headers"],
        ),
        201,
    )
    assert task["status"] == "SCHEDULED"


def test_application_create_on_scheduled_box_rejected(api):
    """PRD 3.7: "Creating an application task takes the `subscription_id`, the `shipment_id` of a box that must be `DELIVERED` — otherwise `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409) — and that must belong to the subscription, the `product_sku` being applied, and a `scheduled_date` in year-month-day form."

    Design: Difficulty/cross_entity_state_dependency/application_create_requires_delivered_box
    """
    ctx = th.setup_active_subscription(email="ad2@x.com")
    # Box never leaves SCHEDULED — the earliest fulfillment state.
    box = th.create_box(ctx["subscription"]["id"],
                        lines=[th.shipment_line("FERT-01", 1)])
    assert box["fulfillment_status"] == "SCHEDULED"

    th.validate_error(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-12"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED,
    )
