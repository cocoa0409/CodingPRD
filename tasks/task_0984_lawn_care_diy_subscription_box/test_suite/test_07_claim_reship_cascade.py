"""Claim RESHIP resolution: depth-3 cascade onto replacement box (PRD 3.9)."""
from datetime import datetime, timezone

import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def _setup_claim_with_unattached_addon(api):
    """Delivered box (FERT-01 x2) at clock 2026-06-05, a FILED claim on it,
    and a CONFIRMED PEST-01 add-on left unattached (no SCHEDULED box existed
    at confirm time)."""
    ctx = th.setup_active_subscription(
        email="cl@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=2, target_month=6)],
        seed_skus=("FERT-01", "PEST-01"),
    )
    box, _ = th.setup_delivered_box(
        ctx,
        lines=[th.shipment_line("FERT-01", 2)],
        ship_date="2026-06-03T00:00:00Z",
        deliver_clock="2026-06-05T00:00:00Z",
    )
    claim = th.file_claim(ctx, box, claim_reason="INEFFECTIVE",
                          evidence_url="https://img/x.jpg")
    add_on = th.quote_add_on(ctx, "PEST-01", qty_units=1)
    add_on = th.confirm_add_on(ctx, add_on["id"])
    assert add_on["attached_shipment_id"] is None, (
        "precondition: no SCHEDULED box existed at confirm time, so no attach"
    )
    return ctx, box, claim, add_on


def test_claim_reship_cascade_depth3(api):
    """PRD 3.9: "A `RESHIP` resolution creates a `REPLACEMENT` shipment box in `SCHEDULED` status whose `source_claim_id` points back to the claim, whose lines are copied from the original box, and whose `ship_date` is the current logical clock; creating that box also attaches any unattached `CONFIRMED` add-on orders of the subscription, recomputes the box's `provisional_charge_cents`, and creates one `AWAITING_DELIVERY` application task per replacement line to await the new box."
    PRD 3.9: "If no `SCHEDULED` box exists, the order stays `CONFIRMED` with `attached_shipment_id` null and attaches to the next box when one is created."

    Design: Difficulty/transitive_cascade/claim_reship_cascade_depth3
    """
    ctx, box, claim, add_on = _setup_claim_with_unattached_addon(api)

    resolved = th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "RESHIP"}, AGRONOMIST)
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_type"] == "RESHIP"

    # Link 1: exactly one REPLACEMENT box pointing back to the claim.
    replacements, meta = th.validate_paginated(
        api.list_shipments(ADMIN, params={"source_claim_id": claim["id"]})
    )
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["box_kind"] == "REPLACEMENT"

    # Link 2: the unattached CONFIRMED add-on attached to the new box.
    add_on_after = th.validate_success(api.get_add_on(add_on["id"], ADMIN))
    assert add_on_after["attached_shipment_id"] == replacement["id"]

    # Link 3: the attach recomputed the charge: FERT 2x800 + PEST 2500 = 4100
    # (ship_date 2026-06-05 is outside the early-season window, no discount).
    assert replacement["provisional_charge_cents"] == 4100, (
        f"expected 1600 + 2500 = 4100, got {replacement['provisional_charge_cents']}"
    )

    # One AWAITING_DELIVERY task per replacement line (one FERT-01 line).
    tasks = th.list_tasks(shipment_id=replacement["id"])
    assert len(tasks) == 1
    assert tasks[0]["status"] == "AWAITING_DELIVERY"


def test_claim_reship_replacement_box_fields(api):
    """PRD 3.9: "A `RESHIP` resolution creates a `REPLACEMENT` shipment box in `SCHEDULED` status whose `source_claim_id` points back to the claim, whose lines are copied from the original box, and whose `ship_date` is the current logical clock; creating that box also attaches any unattached `CONFIRMED` add-on orders of the subscription, recomputes the box's `provisional_charge_cents`, and creates one `AWAITING_DELIVERY` application task per replacement line to await the new box."

    Design: Difficulty/transitive_cascade/claim_reship_cascade_depth3
    """
    ctx, box, claim, _ = _setup_claim_with_unattached_addon(api)

    th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "RESHIP"}, AGRONOMIST)
    )
    replacements, _ = th.validate_paginated(
        api.list_shipments(ADMIN, params={"source_claim_id": claim["id"]})
    )
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["box_kind"] == "REPLACEMENT"
    assert replacement["fulfillment_status"] == "SCHEDULED"
    assert replacement["source_claim_id"] == claim["id"]
    assert replacement["lines"] == [{"product_sku": "FERT-01", "qty_units": 2}], (
        "replacement lines are copied from the original box"
    )
    # The logical clock read 2026-06-05T00:00:00Z at resolution time. PRD 3.9
    # pins ship_date to the logical-clock instant but does not specify its
    # string serialization (the "three fractional digits" sentence of PRD 2.4
    # covers created_at/updated_at only), so compare parsed instants.
    actual_ship_date = datetime.fromisoformat(
        replacement["ship_date"].replace("Z", "+00:00")
    )
    assert actual_ship_date == datetime(2026, 6, 5, tzinfo=timezone.utc)
