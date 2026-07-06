"""Skip lifecycle (wallet credit, cutoff window, ownership order), and win-back
offers (redeem/expire).

Covers difficulty rule `priority_pair_validation_conflict.skip_referential_beats_temporal`
and multiple corner state-machine / temporal-validation instances.
"""
from test_helpers import (
    api_client,
    make_customer_headers,
    TEST_USERS,
    validate_error,
    validate_success,
    ApiErrorId,
    setup_plan_customer_subscription,
    setup_cancelled_with_offer,
    get_subscription_shipments,
    get_customer,
    get_subscription,
    list_customer_wallet_entries,
    set_clock,
    create_plan,
    create_customer,
    create_subscription_for,
    list_customer_win_back_offers,
    cancel,
)
from test_helpers.factories import redeem_offer_payload


# =====================================================================
# Corner: per_shipment_value_skip_credit
# =====================================================================


def test_skip_credits_wallet_by_per_shipment_value():
    """PRD §3.4: "The customer is then credited: a wallet entry is created with `reason` of `SKIP_CREDIT` and a positive `amount_cents` equal to the per-shipment value of the subscription. That per-shipment value is the subscription's `renewal_price_cents` divided by the number of deliveries in the cycle (four for `WEEKLY`, two for `BIWEEKLY`, one for `MONTHLY`), rounded half up to whole cents."

    WEEKLY / ORIGINAL / no vase -> renewal 6000; per_shipment = round(6000/4) = 1500.

    Design: Corner/calculations/corner_per_shipment_value_skip_credit
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    # Server default clock is 2026-03-01; shipments[2] scheduled 2026-03-17 -> well before cutoff.
    res = api_client.skip_shipment(
        shipments[2]["id"], {}, make_customer_headers(customer["id"])
    )
    skipped = validate_success(res)
    assert skipped["status"] == "SKIPPED"
    fetched_customer = get_customer(customer["id"])
    assert fetched_customer["wallet_credit_cents"] == 1500


# =====================================================================
# Difficulty §1.8: priority_pair_validation_conflict.skip_referential_beats_temporal
# =====================================================================


def test_non_owner_past_cutoff_skip_returns_not_owner_before_window():
    """PRD §2.9: "For a shipment skip, the not-skippable state check (`ERR_SHIPMENT_NOT_SKIPPABLE`) precedes the ownership check, which precedes the cutoff-window check (`ERR_SKIP_WINDOW_CLOSED`)."

    Even when both ownership and the temporal window fail, ownership fires first.

    Design: Difficulty/priority_pair_validation_conflict/skip_referential_beats_temporal
    """
    plan = create_plan()
    owner = create_customer()
    non_owner = create_customer()
    subscription = create_subscription_for(owner, plan)
    shipments = get_subscription_shipments(subscription["id"])
    # Advance clock past shipment[0]'s cutoff. Shipment[0] scheduled 2026-03-03; cutoff 2026-03-01.
    set_clock("2026-03-02T00:00:00Z")
    res = api_client.skip_shipment(
        shipments[0]["id"], {}, make_customer_headers(non_owner["id"])
    )
    validate_error(res, ApiErrorId.ERR_NOT_OWNER.value)


def test_owner_past_cutoff_skip_returns_skip_window_closed():
    """PRD §2.9: "For a shipment skip, the not-skippable state check (`ERR_SHIPMENT_NOT_SKIPPABLE`) precedes the ownership check, which precedes the cutoff-window check (`ERR_SKIP_WINDOW_CLOSED`)."
    PRD §3.4: "the boundary itself is inclusive, so a skip exactly 48 hours ahead is still allowed, while a request past that point is rejected with `ERR_SKIP_WINDOW_CLOSED`."

    Owner (ownership OK, state SCHEDULED OK) attempts skip past the cutoff — only the
    temporal error is left; ownership does NOT mask it. Confirms the pair-selection.

    Design: Difficulty/priority_pair_validation_conflict/skip_referential_beats_temporal
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    # Shipment[0] scheduled 2026-03-03; cutoff = 2026-03-03 - 48h = 2026-03-01.
    # Advance clock strictly past cutoff.
    set_clock("2026-03-02T00:00:00Z")
    res = api_client.skip_shipment(
        shipments[0]["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_SKIP_WINDOW_CLOSED.value)


# =====================================================================
# Corner: skip_window_closed_temporal (already covered by test above,
# but the design index enumerates it explicitly — same rule, standalone case)
# =====================================================================


def test_skip_window_closed_when_clock_past_cutoff():
    """PRD §3.4: "The skip is also time-boxed: it is permitted only while the current logical clock instant is at or before the shipment's `scheduled_delivery_date` minus a 48-hour cutoff — the boundary itself is inclusive, so a skip exactly 48 hours ahead is still allowed, while a request past that point is rejected with `ERR_SKIP_WINDOW_CLOSED`."

    Design: Corner/validations/corner_skip_window_closed_temporal
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    set_clock("2026-03-02T00:00:00Z")
    res = api_client.skip_shipment(
        shipments[0]["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_SKIP_WINDOW_CLOSED.value)


# =====================================================================
# Corner: winback_redeem_reactivates_subscription
# =====================================================================


def test_win_back_redeem_reactivates_subscription_with_discount():
    """PRD §3.8: "A successful redeem moves the offer to `REDEEMED`, moves the subscription's `lifecycle_status` from `CANCELLED` back to `ACTIVE`, sets the subscription's `discount_pct` to the offer's `discount_pct`, recomputes `renewal_price_cents` so the discount lands on the next renewal, and increments the subscription's `version`."
    PRD §3.8: "Cancellation also mints a win-back offer for the customer in `OFFERED` status, carrying a `discount_pct` of 0.20".

    Design: Corner/state_machines/corner_winback_redeem_reactivates_subscription
    """
    _plan, customer, cancelled_sub, offer = setup_cancelled_with_offer()
    res = api_client.redeem_win_back_offer(
        offer["id"],
        redeem_offer_payload(subscription_id=cancelled_sub["id"]),
        make_customer_headers(customer["id"]),
    )
    redeemed = validate_success(res)
    assert redeemed["status"] == "REDEEMED"
    fetched_sub = get_subscription(cancelled_sub["id"])
    assert fetched_sub["lifecycle_status"] == "ACTIVE"
    assert fetched_sub["discount_pct"] == 0.20


# =====================================================================
# Corner: offer_expired_temporal
# =====================================================================


def test_win_back_redeem_after_expires_returns_offer_expired():
    """PRD §3.8: "the current clock instant must be at or before the offer's `expires_at`, else `ERR_OFFER_EXPIRED`".

    Cancellation at default clock 2026-03-01 -> expires_at = 2026-03-31; advance clock to
    2026-04-15 (well past).

    Design: Corner/validations/corner_offer_expired_temporal
    """
    _plan, customer, cancelled_sub, offer = setup_cancelled_with_offer()
    set_clock("2026-04-15T00:00:00Z")
    res = api_client.redeem_win_back_offer(
        offer["id"],
        redeem_offer_payload(subscription_id=cancelled_sub["id"]),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OFFER_EXPIRED.value)
