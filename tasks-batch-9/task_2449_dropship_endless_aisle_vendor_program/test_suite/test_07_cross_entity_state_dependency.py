"""Operations gated by the state of a neighbouring entity.

An offer's publication depends on its owning vendor's onboarding status, and an
order line's transmission depends on whether its vendor is closed by a blackout
window. Both gates sit on the transition, not on the create.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_blackout,
    create_certified_vendor,
    create_draft_item,
    get_success_data,
    make_merchandise_manager_headers,
    order_lines_of,
    place_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_vendor,
    reset_clock,
    setup_vendor_with_active_offer,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
OPS_HEADERS = TEST_USERS["vendor_ops_analyst_headers"]
MM_HEADERS = TEST_USERS["merchandise_manager_headers"]


def _certified_vendor_with_draft_offer(api, suffix):
    """A CERTIFIED vendor holding live coverage plus one DRAFT offer against it."""
    reset_clock(api)
    vendor = create_certified_vendor(api, suffix=suffix)
    item = create_draft_item(
        api,
        vendor["id"],
        sku=f"SKU-RUG-{suffix}",
        unit_retail_cents=12000,
    )
    return vendor, item


def _blackout_state(api, suffix, order_ref):
    """An ACTIVE vendor closed by a blackout, with one captured order on its offer."""
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    blackout = add_blackout(
        api,
        base["vendor_id"],
        start_date="2026-08-03",
        end_date="2026-08-05",
        reason="PEAK_FREEZE",
        reopen_buffer_days=1,
    )
    order = place_order(api, base["item_id"], quantity=1, order_ref=order_ref)
    line = order_lines_of(api, order["id"])[0]
    return base, blackout, order, line


# ─── Offer publication gated by the owning vendor ─────


def test_offer_activation_is_refused_while_its_vendor_is_only_certified(api):
    """PRD §2.6: "The vendor that owns the target row is in `onboarding_status` `ACTIVE` for offer activation, line acknowledgment, shipment confirmation and line retransmission; offer creation instead requires a vendor in `CERTIFIED` or `ACTIVE`."

    The offer itself is faultless — its vendor already carries a matching ACTIVE
    coverage row — so the only thing standing in the way is the parent's state.
    The rejected call leaves the offer in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/item_activation_blocked_until_the_owning_vendor_reaches_active
    """
    vendor, item = _certified_vendor_with_draft_offer(api, "XA1")
    assert vendor["onboarding_status"] == "CERTIFIED"

    response = api.activate_item(item["id"], MM_HEADERS)
    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)

    assert refresh_item(api, item["id"])["status"] == "DRAFT"


def test_offer_activation_succeeds_once_the_owning_vendor_is_activated(api):
    """PRD §3.3: "On success the platform clears `suppression_reason` to null, re-derives `unit_cost_cents`, `effective_on_hand_units`, `inventory_is_stale` and `available_units`, and increments the offer's `version`."

    The identical activation call flips from a refusal to a success the instant
    the parent vendor reaches ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/item_activation_blocked_until_the_owning_vendor_reaches_active
    """
    vendor, item = _certified_vendor_with_draft_offer(api, "XA2")
    validate_error(
        api.activate_item(item["id"], MM_HEADERS),
        ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value,
    )

    get_success_data(
        api.activate_vendor(vendor["id"], make_merchandise_manager_headers("mm-go-live-XA2"))
    )
    assert refresh_vendor(api, vendor["id"])["onboarding_status"] == "ACTIVE"

    activated = validate_success(api.activate_item(item["id"], MM_HEADERS))
    assert activated["status"] == "ACTIVE"
    assert activated["suppression_reason"] is None


def test_offer_activation_rederives_the_commission_unit_cost(api):
    """PRD §3.3: "For a `COMMISSION` vendor, the offer's `unit_cost_cents` is the offer's `unit_retail_cents` multiplied by the quantity 10000 minus the vendor's `commission_rate_bps`, divided by 10000, with the result rounded half up to a whole cent; `unit_wholesale_cost_cents` plays no part whatsoever."

    A retail price of 12000 cents at 1500 basis points of commission leaves the
    vendor 10200 cents per unit once the parent vendor is live and the offer may
    finally be published.

    Design: Difficulty/cross_entity_state_dependency/item_activation_blocked_until_the_owning_vendor_reaches_active
    """
    vendor, item = _certified_vendor_with_draft_offer(api, "XA3")
    get_success_data(
        api.activate_vendor(vendor["id"], make_merchandise_manager_headers("mm-go-live-XA3"))
    )

    activated = validate_success(api.activate_item(item["id"], MM_HEADERS))
    assert activated["unit_cost_cents"] == 10200


# ─── Line transmission gated by a blackout window ─────


def test_transmission_is_refused_while_an_active_blackout_covers_the_logical_date(api):
    """PRD §2.6: "No `ACTIVE` blackout window of the offer's vendor covers the current logical date, where coverage means the date falls on or after `start_date` and on or before `end_date`."

    The clock reads 2026-08-03, which sits inside the 2026-08-03 to 2026-08-05
    closure, so the hand-off is refused and the line does not move.

    Design: Difficulty/cross_entity_state_dependency/line_transmission_blocked_by_an_active_vendor_blackout_window
    """
    base, blackout, order, line = _blackout_state(api, "XB1", "ORD-BLACKOUT-XB1")
    assert blackout["status"] == "ACTIVE"

    response = api.transmit_order(order["id"], MM_HEADERS)
    validate_error(response, ApiErrorId.ERR_VENDOR_BLACKOUT.value)

    unmoved = refresh_line(api, line["id"])
    assert unmoved["status"] == "PENDING_TRANSMIT"
    assert unmoved["transmitted_at"] is None


def test_order_capture_is_permitted_during_a_blackout_and_quotes_the_padded_promise(api):
    """PRD §3.5: "To that the platform adds the offer's contracted `lead_time_days`, the coverage row's `transit_days`, and the vendor's `promise_padding_days`, all as whole calendar days."

    Capture never consults blackouts, so the order lands while the vendor is
    closed: anchored at 2026-08-03T10:00:00Z with no cutoff rollover, three lead
    days, four transit days and two padding days quote 2026-08-12.

    Design: Difficulty/cross_entity_state_dependency/line_transmission_blocked_by_an_active_vendor_blackout_window
    """
    base, blackout, order, line = _blackout_state(api, "XB2", "ORD-BLACKOUT-XB2")

    assert order["quoted_promise_date"] == "2026-08-12"
    assert order["promise_variant_in_effect"] == "QUOTED"
    assert line["status"] == "PENDING_TRANSMIT"


def test_cancelling_the_blackout_releases_the_transmission_gate(api):
    """PRD §3.2: "The row moves `ACTIVE → CANCELLED` and is retained so it stays visible in the audit trail, but a `CANCELLED` window no longer blocks transmission, no longer blocks retransmission, and no longer pushes delivery promise dates."

    The gating entity is released by a cancellation rather than by a forward
    advance, and the same transmit call then succeeds.

    Design: Difficulty/cross_entity_state_dependency/line_transmission_blocked_by_an_active_vendor_blackout_window
    """
    base, blackout, order, line = _blackout_state(api, "XB3", "ORD-BLACKOUT-XB3")
    validate_error(
        api.transmit_order(order["id"], MM_HEADERS),
        ApiErrorId.ERR_VENDOR_BLACKOUT.value,
    )

    cancelled = validate_success(
        api.cancel_blackout(base["vendor_id"], blackout["id"], ADMIN_HEADERS)
    )
    assert cancelled["status"] == "CANCELLED"

    validate_success(api.transmit_order(order["id"], MM_HEADERS))
    sent = refresh_line(api, line["id"])
    assert sent["status"] == "TRANSMITTED"
    assert sent["transmitted_at"] is not None


def test_transmission_pins_the_offer_unit_cost_onto_the_line(api):
    """PRD §3.6: "The line's `unit_cost_cents` is copied from the offer's `unit_cost_cents` as of that instant and is never re-read afterwards, and the line's `surcharge_cents` is copied from the `surcharge_cents` of the coverage row that matched."

    Once the closure is lifted the hand-off freezes the vendor's cost: 24999
    cents of retail at 1500 basis points of commission is 21249 cents per unit,
    and the matching coverage row carries no surcharge.

    Design: Difficulty/cross_entity_state_dependency/line_transmission_blocked_by_an_active_vendor_blackout_window
    """
    base, blackout, order, line = _blackout_state(api, "XB4", "ORD-BLACKOUT-XB4")
    get_success_data(api.cancel_blackout(base["vendor_id"], blackout["id"], OPS_HEADERS))
    validate_success(api.transmit_order(order["id"], MM_HEADERS))

    sent = refresh_line(api, line["id"])
    assert sent["unit_cost_cents"] == 21249
    assert sent["surcharge_cents"] == 0


def test_transmission_recomputes_the_promise_without_the_padding(api):
    """PRD §3.6: "Third, padding is dropped to 0 days entirely."

    No scorecard is published, so the recomputed promise reuses the contracted
    three lead days and the four transit days from the same 2026-08-03 anchor
    but drops the two padding days: 2026-08-10 against a quote of 2026-08-12.

    Design: Difficulty/cross_entity_state_dependency/line_transmission_blocked_by_an_active_vendor_blackout_window
    """
    base, blackout, order, line = _blackout_state(api, "XB5", "ORD-BLACKOUT-XB5")
    get_success_data(api.cancel_blackout(base["vendor_id"], blackout["id"], OPS_HEADERS))
    validate_success(api.transmit_order(order["id"], MM_HEADERS))

    after = refresh_order(api, order["id"])
    assert after["quoted_promise_date"] == "2026-08-12"
    assert after["recomputed_promise_date"] == "2026-08-10"
    assert after["promise_variant_in_effect"] == "RECOMPUTED"
