"""Subscription guards: cancel lockdown, resume precondition, skip target
existence, and ACTIVE-gated creates (PRD 3.5, 3.6, 3.9)."""
import test_helpers as th

OPS = th.TEST_USERS["fulfillment_ops_headers"]


def test_subscription_cancel_terminal_lockdown(api):
    """PRD 3.5: "Cancellation is available from `ACTIVE`, `PAUSED`, or `PAST_DUE`, and is rejected only if the subscription is already `CANCELLED` (`ERR_SUBSCRIPTION_ALREADY_CANCELLED`, HTTP 409) or the caller does not own it."
    PRD 3.5: "Moving a subscription from `ACTIVE` to `PAUSED` requires it to be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`, HTTP 409) and requires ownership; the pause cascades so that each of its shipment boxes in `SCHEDULED` flips to `HELD` and each of its application tasks in `SCHEDULED` flips to `FROZEN`."

    Design: Corner/state_machines/subscription_cancel_terminal_lockdown
    """
    ctx = th.setup_active_subscription(email="s6@x.com")
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]
    th.validate_success(api.cancel_subscription(sub_id, headers))

    th.validate_error(
        api.cancel_subscription(sub_id, headers),
        th.ApiErrorId.ERR_SUBSCRIPTION_ALREADY_CANCELLED,
    )
    th.validate_error(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
    )


def test_resume_active_subscription_rejected(api):
    """PRD 3.5: "Resuming moves a subscription from `PAUSED` back to `ACTIVE`, requires it to be `PAUSED` (`ERR_SUBSCRIPTION_NOT_PAUSED`, HTTP 409), and reverses the cascades: `HELD` boxes return to `SCHEDULED` and `FROZEN` tasks return to `SCHEDULED`."

    Design: Corner/state_machines/resume_active_subscription_rejected
    """
    ctx = th.setup_active_subscription(email="x7@x.com")
    th.validate_error(
        api.set_subscription_status(ctx["subscription"]["id"],
                                    {"to_status": "ACTIVE"},
                                    ctx["customer_headers"]),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_PAUSED,
    )


def test_skip_without_scheduled_box_rejected(api):
    """PRD 3.5: "If no `SCHEDULED` box exists at all, the skip is rejected with `ERR_NO_SKIPPABLE_SHIPMENT` (HTTP 409)."

    Design: Corner/validations/skip_without_scheduled_box_rejected
    """
    ctx = th.setup_active_subscription(email="v8@x.com")
    # Allowance is full (0 used) but there is no box to skip at all.
    th.validate_error(
        api.skip_next_shipment(ctx["subscription"]["id"], ctx["customer_headers"]),
        th.ApiErrorId.ERR_NO_SKIPPABLE_SHIPMENT,
    )


def test_addon_create_requires_active_subscription(api):
    """PRD 3.9: "The subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and the sku must resolve (`ERR_PRODUCT_NOT_FOUND`) to an active (`ERR_PRODUCT_INACTIVE`) catalog product in the `PEST` or `WEED` category that carries an `add_on_flat_price_cents` — a sku failing those shape requirements is rejected with `ERR_NOT_AN_ADD_ON_SKU` (HTTP 422)."

    Design: Corner/validations/addon_create_requires_active_subscription
    """
    ctx = th.setup_active_subscription(email="v7@x.com",
                                       seed_skus=("FERT-01", "PEST-01"))
    th.validate_success(
        api.set_subscription_status(ctx["subscription"]["id"],
                                    {"to_status": "PAUSED"},
                                    ctx["customer_headers"])
    )
    th.validate_error(
        api.create_add_on(
            th.add_on_payload(ctx["subscription"]["id"], add_on_sku="PEST-01",
                              qty_units=1),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
    )


def test_shipment_create_requires_active_subscription(api):
    """PRD 3.6: "A `FulfillmentOps` operator — or a PlatformAdmin — creates a `SEASONAL` or `ADDON` box for an `ACTIVE` subscription; creating against a non-active subscription is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Corner/endpoints/shipment_create_requires_active_subscription
    """
    ctx = th.setup_active_subscription(email="e2@x.com")
    th.validate_success(
        api.set_subscription_status(ctx["subscription"]["id"],
                                    {"to_status": "PAUSED"},
                                    ctx["customer_headers"])
    )
    th.validate_error(
        api.create_shipment(
            th.shipment_payload(ctx["subscription"]["id"],
                                lines=[th.shipment_line("FERT-01", 1)]),
            OPS,
        ),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
    )
