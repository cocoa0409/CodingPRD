"""Add-on orders: detach compensation, sku shape rule, quote expiry sweep
(PRD 2.5, 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_addon_cancel_detaches_and_recomputes_box_charge(api):
    """PRD 3.9: "When the cancelled order was attached to a box, cancellation performs a compensating detach: the order detaches from the box and the box's `provisional_charge_cents` is recomputed without the add-on."
    PRD 3.9: "Attaching recomputes that box's `provisional_charge_cents` to include the add-on lines and increments the box's `version`."

    Design: Corner/state_machines/addon_cancel_detaches_and_recomputes_box_charge
    """
    ctx = th.setup_active_subscription(
        email="s16@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=5, target_month=6)],
        seed_skus=("FERT-01", "PEST-01"),
    )
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("FERT-01", 5)],
        ship_date="2026-06-10T00:00:00Z",
    )
    # 5 x 800 = 4000 (ship 2026-06-10 is outside the early-season window).
    assert box["provisional_charge_cents"] == 4000

    add_on = th.confirm_add_on(ctx, th.quote_add_on(ctx, "PEST-01", 1)["id"])
    assert add_on["attached_shipment_id"] == box["id"]
    attached_box = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert attached_box["provisional_charge_cents"] == 6500, (
        "attach recomputes the charge: 4000 + 2500"
    )

    cancelled = th.validate_success(
        api.cancel_add_on(add_on["id"], ctx["customer_headers"])
    )
    assert cancelled["status"] == "CANCELLED"
    restored_box = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert restored_box["provisional_charge_cents"] == 4000, (
        "the compensating detach recomputes the charge without the add-on"
    )


def test_addon_requires_pest_or_weed_sku(api):
    """PRD 3.9: "The subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and the sku must resolve (`ERR_PRODUCT_NOT_FOUND`) to an active (`ERR_PRODUCT_INACTIVE`) catalog product in the `PEST` or `WEED` category that carries an `add_on_flat_price_cents` — a sku failing those shape requirements is rejected with `ERR_NOT_AN_ADD_ON_SKU` (HTTP 422)."

    Design: Corner/validations/addon_requires_pest_or_weed_sku
    """
    ctx = th.setup_active_subscription(email="v12@x.com")
    # FERT-01 is a FERTILIZER with no add_on_flat_price_cents.
    th.validate_error(
        api.create_add_on(
            th.add_on_payload(ctx["subscription"]["id"], add_on_sku="FERT-01",
                              qty_units=1),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_NOT_AN_ADD_ON_SKU,
    )


def test_expired_addon_cancel_rejected(api):
    """PRD 3.9: "Cancelling an add-on is allowed from `QUOTED` or `CONFIRMED` — anything else is rejected with `ERR_ADD_ON_NOT_CANCELLABLE` (HTTP 409) — and requires ownership."
    PRD 2.5: "Second, the quote-expiry sweep: each `QUOTED` add-on order whose `quote_expires_at` is at or before the current logical time flips to `EXPIRED`."

    Design: Corner/validations/expired_addon_cancel_rejected
    """
    ctx = th.setup_active_subscription(email="v13@x.com",
                                       seed_skus=("FERT-01", "PEST-01"))
    add_on = th.quote_add_on(ctx, "PEST-01", 1)
    # Quote created at the default logical time 2026-05-01 expires 2026-05-08.
    th.set_clock("2026-05-08T00:00:00Z")

    th.validate_error(
        api.cancel_add_on(add_on["id"], ctx["customer_headers"]),
        th.ApiErrorId.ERR_ADD_ON_NOT_CANCELLABLE,
    )


def test_addon_quote_expiry_sweep(api):
    """PRD 2.5: "Second, the quote-expiry sweep: each `QUOTED` add-on order whose `quote_expires_at` is at or before the current logical time flips to `EXPIRED`. The capability's response reports `now_iso8601` (the new logical time), `boxes_generated` (how many boxes the auto-ship sweep created), and `add_ons_expired` (how many quotes the expiry sweep retired)."
    PRD 3.9: "Confirming a quote requires it to be `QUOTED` — a quote past its expiry has already been flipped to `EXPIRED` by the sweep, so expiry reaches confirmation only as the state error `ERR_ADD_ON_NOT_QUOTED` (HTTP 409) — requires the subscription to be `ACTIVE`, and requires ownership."

    Design: Corner/cross_cutting_layers/addon_quote_expiry_sweep
    """
    ctx = th.setup_active_subscription(email="x4@x.com",
                                       seed_skus=("FERT-01", "PEST-01"))
    add_on = th.quote_add_on(ctx, "PEST-01", 1)
    assert add_on["status"] == "QUOTED"

    # Expiry is inclusive: now == quote_expires_at (2026-05-08) retires it.
    sweep = th.set_clock("2026-05-08T00:00:00Z")
    assert sweep["add_ons_expired"] == 1

    expired = th.validate_success(api.get_add_on(add_on["id"], ADMIN))
    assert expired["status"] == "EXPIRED"

    th.validate_error(
        api.confirm_add_on(add_on["id"], ctx["customer_headers"]),
        th.ApiErrorId.ERR_ADD_ON_NOT_QUOTED,
    )
