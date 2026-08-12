"""Satisfaction claim filing window: 30-day inclusive boundary (PRD 3.9)."""
import test_helpers as th


def _setup_delivered_at_2026_06_01(api, email):
    """Box DELIVERED with the logical clock pinned to 2026-06-01T00:00:00Z so
    delivered_at is exactly that instant."""
    ctx = th.setup_active_subscription(email=email)
    box, _ = th.setup_delivered_box(
        ctx,
        lines=[th.shipment_line("FERT-01", 1)],
        ship_date="2026-06-01T00:00:00Z",
        deliver_clock="2026-06-01T00:00:00Z",
    )
    return ctx, box


def test_claim_window_day30_allowed_day31_expired(api):
    """PRD 3.9: "The shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`) and belong to the subscription, and the claim must be filed within 30 days of the box's `delivered_at` — filing later is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_window_day30_allowed_day31_expired
    """
    ctx, box = _setup_delivered_at_2026_06_01(api, email="cw@x.com")
    headers = ctx["customer_headers"]

    # Day 30 exactly: 2026-07-01 is 30 days after 2026-06-01 — still within.
    th.set_clock("2026-07-01T00:00:00Z")
    claim = th.validate_success(
        api.create_claim(
            th.claim_payload(ctx["subscription"]["id"], box["id"],
                             claim_reason="DAMAGED"),
            headers,
        ),
        201,
    )
    assert claim["status"] == "FILED"

    # Day 31: 2026-07-02 is 31 days after — the window has expired.
    th.set_clock("2026-07-02T00:00:00Z")
    th.validate_error(
        api.create_claim(
            th.claim_payload(ctx["subscription"]["id"], box["id"],
                             claim_reason="OTHER"),
            headers,
        ),
        th.ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED,
    )


def test_claim_window_day29_allowed(api):
    """PRD 3.9: "The shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`) and belong to the subscription, and the claim must be filed within 30 days of the box's `delivered_at` — filing later is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_window_day30_allowed_day31_expired
    """
    ctx, box = _setup_delivered_at_2026_06_01(api, email="cw29@x.com")
    # Day 29: comfortably inside the inclusive 30-day window.
    th.set_clock("2026-06-30T00:00:00Z")
    claim = th.validate_success(
        api.create_claim(
            th.claim_payload(ctx["subscription"]["id"], box["id"],
                             claim_reason="WRONG_PRODUCT"),
            ctx["customer_headers"],
        ),
        201,
    )
    assert claim["status"] == "FILED"
