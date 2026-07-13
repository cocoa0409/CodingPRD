"""Accounts, subscriptions, the two billing dimensions, tier changes and their compensator."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    CLOCK_START,
    validate_success,
    validate_error,
    assert_customer,
    assert_subscription,
    assert_instant_equals,
    assert_q1_conserved,
    make_customer_headers,
    make_platform_admin_headers,
    factories as f,
    fixtures as fx,
)

ADMIN = make_platform_admin_headers()


# ═══════════════════════════════════════════════════════════════════════════
# Account registration and reads
# ═══════════════════════════════════════════════════════════════════════════

def test_register_customer_returns_system_fields_and_defaults(api):
    """PRD §3.1: "A freshly registered account has `account_status` of `ACTIVE`,
    `dna_status` of `NO_SAMPLE`, zero store credit, zero visible matches, all three
    consent booleans false, and `version` of 1."
    PRD §2.4: "`id` (string): a server-minted UUID. It never carries a type prefix, and
    clients must never construct one."

    Design: Corner/entities/customer_create_returns_system_fields_and_defaults
    """
    resp = api.create_customer(
        f.create_customer_payload(email="new@dna.test", display_name="New"), ADMIN
    )
    data = validate_success(resp, 201)
    assert_customer(data)

    assert data["version"] == 1, f"Expected version 1 on creation, got {data['version']}"
    assert data["account_status"] == "ACTIVE"
    assert data["dna_status"] == "NO_SAMPLE"
    assert data["wallet_credit_cents"] == 0
    assert data["visible_match_count"] == 0
    assert data["matching_opt_in"] is False
    assert data["research_opt_in"] is False
    assert data["health_opt_in"] is False

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_customer_with_unknown_id_returns_customer_not_found(api):
    """PRD §2.5: "The not-found codes are entity-specific: `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_TREE_NOT_FOUND`,
    `ERR_PERSON_NOT_FOUND`, `ERR_HINT_NOT_FOUND`, and `ERR_DATA_REQUEST_NOT_FOUND`, each
    returned with HTTP 404."

    Design: Corner/entities/get_customer_with_unknown_id_returns_customer_not_found
    """
    resp = api.get_customer(UNKNOWN_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_logical_clock_starts_at_the_fixed_default_instant(api):
    """PRD §2.4: "The server maintains a **logical clock** which begins at the fixed instant
    `2026-05-01T00:00:00Z` when the process starts and only ever moves when an operator
    explicitly sets it, supplying the target instant as `to_iso8601`; the operation echoes
    the new value back as `current_utc`."
    PRD §3.1: "Opening a subscription stamps `current_period_start` with the logical clock
    and sets `current_period_end` to exactly thirty days later — thirty days is the billing
    period throughout this system, and every proration in Section 3.2 divides by it."

    Design: Corner/endpoints/clock_default_is_2026_05_01_before_any_set_call
    """
    # Deliberately no set_current_utc call: the clock must already read the default.
    customer = fx.create_customer(email="clk@dna.test", display_name="Clk")
    resp = api.create_subscription(
        f.create_subscription_payload(customer["id"], tier="PLUS"),
        make_customer_headers(customer["id"]),
    )
    sub = validate_success(resp, 201)
    assert_subscription(sub)

    assert_instant_equals(sub["current_period_start"], "2026-05-01T00:00:00Z", "current_period_start")
    assert_instant_equals(sub["current_period_end"], "2026-05-31T00:00:00Z", "current_period_end")


# ═══════════════════════════════════════════════════════════════════════════
# The two independent billing dimensions
# ═══════════════════════════════════════════════════════════════════════════

def test_second_payment_failure_advances_access_only_leaving_billing_past_due(api):
    """PRD §3.1: "From the pair `CURRENT` and `ACTIVE`: the billing dimension moves
    `CURRENT → PAST_DUE`, and as a side effect the access dimension moves `ACTIVE → GRACE`
    with `grace_until` set to the logical clock plus fourteen days."
    PRD §3.1: "From the pair `PAST_DUE` and `GRACE`: this is where a second failure lands.
    The billing dimension does **not** move — it remains `PAST_DUE`. Only the access
    dimension advances, `GRACE → LOCKED`, and `grace_until` is cleared back to null."

    Design: Difficulty/non_linear_state_machine/subscription_billing_and_access_dimensions_evolve_independently
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="p@dna.test", display_name="Pia")
    sub = fx.create_subscription(customer["id"], "PLUS")

    first = validate_success(
        api.billing_event(sub["id"], f.billing_event_payload("PAYMENT_FAILED"), ADMIN)
    )
    assert first["billing_status"] == "PAST_DUE"
    assert first["access_status"] == "GRACE"

    second = validate_success(
        api.billing_event(sub["id"], f.billing_event_payload("PAYMENT_FAILED"), ADMIN)
    )
    assert second["billing_status"] == "PAST_DUE", (
        "The billing dimension must not move on a second PAYMENT_FAILED; "
        f"got {second['billing_status']}"
    )
    assert second["access_status"] == "LOCKED", (
        f"Expected access_status LOCKED after the second failure, got {second['access_status']}"
    )
    assert second["grace_until"] is None, "grace_until is cleared back to null on GRACE → LOCKED"


def test_payment_succeeded_restores_both_dimensions_from_locked(api):
    """PRD §3.1: "A `PAYMENT_SUCCEEDED` event requires `billing_status` to be `PAST_DUE`,
    and is otherwise rejected with `ERR_INVALID_STATE`. It moves the billing dimension
    `PAST_DUE → CURRENT` and, as a side effect, restores the access dimension to `ACTIVE`
    from whichever of `GRACE` or `LOCKED` it currently holds, clearing `grace_until`."

    Design: Difficulty/non_linear_state_machine/subscription_billing_and_access_dimensions_evolve_independently
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="p2@dna.test", display_name="Pia2")
    sub = fx.create_subscription(customer["id"], "PLUS")
    fx.lock_subscription(sub["id"])

    restored = validate_success(
        api.billing_event(sub["id"], f.billing_event_payload("PAYMENT_SUCCEEDED"), ADMIN)
    )
    assert restored["billing_status"] == "CURRENT"
    assert restored["access_status"] == "ACTIVE"
    assert restored["grace_until"] is None

    # A third PAYMENT_FAILED from (PAST_DUE, LOCKED) has nowhere left to go.
    fx.lock_subscription(sub["id"])
    resp = api.billing_event(sub["id"], f.billing_event_payload("PAYMENT_FAILED"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ═══════════════════════════════════════════════════════════════════════════
# The cancellation refund: CLEAN_PERIOD vs CONSUMED_PERIOD
# ═══════════════════════════════════════════════════════════════════════════

def _setup_clean_and_consumed_customers():
    """Two PLUS subscribers with identical tier/period/cancel clock (26 unused days).
    The 'consumed' side has published exactly one report inside the period."""
    fx.set_clock(CLOCK_START)
    clean = fx.create_customer(email="clean@dna.test", display_name="Clean")
    clean_sub = fx.create_subscription(clean["id"], "PLUS")

    consumed = fx.setup_dna_ready_customer(
        email="consumed@dna.test", display_name="Consumed", tier="PLUS"
    )
    fx.publish_report(consumed["customer"]["id"], "ETHNICITY", "PROVISIONAL")

    fx.set_clock("2026-05-05T00:00:00Z")
    return clean, clean_sub, consumed


def test_cancellation_refund_clean_period_returns_full_proration(api):
    """PRD §3.1: "The base refund is the tier's per-period fee multiplied by the unused
    days, divided by thirty, and rounded half up to a whole cent."
    PRD §3.1: "If that count is zero, the period was **clean** and the refund is the base
    refund exactly."

    Design: Difficulty/dual_variant_calc/subscription_close_refund_clean_vs_consumed_period
    """
    clean, clean_sub, _consumed = _setup_clean_and_consumed_customers()

    sub = validate_success(
        api.billing_event(clean_sub["id"], f.billing_event_payload("CANCEL"), ADMIN)
    )
    assert sub["billing_status"] == "CLOSED"
    assert sub["access_status"] == "CANCELLED"

    # PLUS fee 1999, 26 unused days: round_half_up(1999 * 26 / 30)
    # == round_half_up(51974 / 30) == round_half_up(1732.4666...) == 1732.
    wallet = fx.read_customer(clean["id"])["wallet_credit_cents"]
    assert wallet == 1732, f"Expected a clean-period refund of 1732 cents, got {wallet}"


def test_cancellation_refund_consumed_period_deducts_unlock_fee_per_published_report(api):
    """PRD §3.1: "If the count is one or more, the period was **consumed**: an unlock fee of
    300 cents is deducted for each such published report, and the result is floored at zero
    — the refund is never negative and, for identical tier, period and clock inputs, is
    always strictly smaller than the clean-period refund would have been."

    Design: Difficulty/dual_variant_calc/subscription_close_refund_clean_vs_consumed_period
    """
    _clean, _clean_sub, consumed = _setup_clean_and_consumed_customers()
    consumed_id = consumed["customer"]["id"]

    sub = validate_success(
        api.billing_event(
            consumed["subscription"]["id"], f.billing_event_payload("CANCEL"), ADMIN
        )
    )
    assert sub["billing_status"] == "CLOSED"
    assert sub["access_status"] == "CANCELLED"

    # Same 1732 base refund, minus one 300-cent unlock fee for the one published report.
    wallet = fx.read_customer(consumed_id)["wallet_credit_cents"]
    assert wallet == 1432, f"Expected a consumed-period refund of 1432 cents, got {wallet}"


# ═══════════════════════════════════════════════════════════════════════════
# The tier-upgrade charge: pinned evaluation order
# ═══════════════════════════════════════════════════════════════════════════

def _setup_upgrade_at_26_remaining_days(email):
    """PLUS subscriber with 10000 cents of credit, clock moved so 26 days remain."""
    fx.set_clock(CLOCK_START)
    setup = fx.setup_upgrade_ready_customer(email=email, tier="PLUS", wallet_cents=10_000)
    fx.set_clock("2026-05-05T00:00:00Z")
    return setup


def test_upgrade_charge_selects_loyalty_discount_once_from_the_prorated_subtotal(api):
    """PRD §3.2: "The **loyalty discount rate is selected once, from the prorated subtotal**,
    and is never re-selected from any later figure. A prorated subtotal of 5000 cents or
    more earns a rate of ten percent; a subtotal of at least 2000 cents but below 5000 earns
    five percent; anything below 2000 cents earns nothing."
    PRD §3.2: "The **charge total** is the discounted subtotal plus the processing fee."

    Design: Difficulty/combinatorial_formula/tier_change_charge_pinned_evaluation_order_mode_c
    """
    setup = _setup_upgrade_at_26_remaining_days("upgrade@dna.test")
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]
    headers = setup["headers"]

    version = fx.read_subscription_version(sub_id, customer_id)
    data = validate_success(
        api.change_tier(sub_id, f.change_tier_payload("PRO", version), headers)
    )
    assert_subscription(data)

    # base delta 6000; 26/30 remaining days -> prorated 5200 -> discount tier 0.10 -> 520
    # -> discounted 4680 -> fee max(30, round_half_up(135.72)) = 136 -> charge total 4816.
    # Re-selecting the discount from the post-fee total (4816) would have given 5083.
    assert data["tier"] == "PRO"
    assert data["last_change_charge_cents"] == 4816, (
        f"Expected charge_total_cents 4816, got {data['last_change_charge_cents']}"
    )
    assert data["lifetime_charged_cents"] == 4816
    assert data["last_change_from_tier"] == "PLUS"


def test_upgrade_charge_debits_the_wallet_by_exactly_the_charge_total(api):
    """PRD §3.2: "On success, `last_change_from_tier` records the tier held before the
    change, `tier` moves to the new tier immediately, the charge total is debited from
    `wallet_credit_cents`, `lifetime_charged_cents` is increased by the charge total,
    `last_change_charge_cents` is set to the charge total, and the subscription's `version`
    advances by one."

    Design: Difficulty/combinatorial_formula/tier_change_charge_pinned_evaluation_order_mode_c
    """
    setup = _setup_upgrade_at_26_remaining_days("upgrade2@dna.test")
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]

    version_before = fx.read_subscription_version(sub_id, customer_id)
    data = validate_success(
        api.change_tier(
            sub_id,
            f.change_tier_payload("PRO", version_before),
            make_customer_headers(customer_id),
        )
    )

    assert data["version"] == version_before + 1, "change-tier advances Subscription.version by one"

    customer = fx.read_customer(customer_id)
    assert customer["wallet_credit_cents"] == 10_000 - 4816, (
        f"Expected wallet 5184 after a 4816-cent charge, got {customer['wallet_credit_cents']}"
    )
    assert customer["wallet_credit_cents"] == 5184


# ═══════════════════════════════════════════════════════════════════════════
# Q1: wallet + lifetime_charged conserved across change-tier + revert-change
# ═══════════════════════════════════════════════════════════════════════════

def test_revert_change_restores_the_wallet_and_the_prior_tier(api):
    """PRD §3.2: "The revert credits `last_change_charge_cents` back to
    `wallet_credit_cents`, decrements `lifetime_charged_cents` by that same amount, restores
    `tier` to `last_change_from_tier`, clears `pending_tier`, and finally sets both
    `last_change_charge_cents` and `last_change_from_tier` back to null."

    Design: Difficulty/compensating_invariant/q1_monetary_wallet_plus_lifetime_charged_conserved_under_revert
    """
    setup = _setup_upgrade_at_26_remaining_days("w@dna.test")
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]
    headers = setup["headers"]

    version = fx.read_subscription_version(sub_id, customer_id)
    validate_success(api.change_tier(sub_id, f.change_tier_payload("PRO", version), headers))

    reverted = validate_success(api.revert_change(sub_id, headers))
    assert reverted["tier"] == "PLUS", "revert restores tier to last_change_from_tier"
    assert reverted["lifetime_charged_cents"] == 0
    assert reverted["last_change_charge_cents"] is None
    assert reverted["last_change_from_tier"] is None
    assert reverted["pending_tier"] is None

    customer = fx.read_customer(customer_id)
    assert customer["wallet_credit_cents"] == 10_000, (
        f"Expected the full 10000 cents back in the wallet, got {customer['wallet_credit_cents']}"
    )


def test_q1_wallet_plus_lifetime_charged_is_conserved_mid_flight_and_after_revert(api):
    """PRD §2.10: "The first: the sum of a customer's `wallet_credit_cents` and their
    subscription's `lifetime_charged_cents` is unchanged across the pair of a tier change
    followed by a revert of that change — whatever the charge took out of the wallet, it put
    into the lifetime total, and the revert moves exactly that amount back."

    Design: Difficulty/compensating_invariant/q1_monetary_wallet_plus_lifetime_charged_conserved_under_revert
    """
    setup = _setup_upgrade_at_26_remaining_days("w2@dna.test")
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]
    headers = setup["headers"]

    assert_q1_conserved(fx.read_customer(customer_id), fx.read_subscription(sub_id, customer_id), 10_000)

    version = fx.read_subscription_version(sub_id, customer_id)
    charged = validate_success(
        api.change_tier(sub_id, f.change_tier_payload("PRO", version), headers)
    )
    assert charged["lifetime_charged_cents"] == 4816
    # Q1 holds mid-flight: 5184 in the wallet + 4816 charged == 10000.
    assert_q1_conserved(fx.read_customer(customer_id), charged, 10_000)

    validate_success(api.revert_change(sub_id, headers))
    assert_q1_conserved(
        fx.read_customer(customer_id), fx.read_subscription(sub_id, customer_id), 10_000
    )


# ═══════════════════════════════════════════════════════════════════════════
# Downgrade, insufficient credit, subscription OCC
# ═══════════════════════════════════════════════════════════════════════════

def test_downgrade_defers_to_pending_tier_at_zero_charge(api):
    """PRD §3.2: "A **downgrade** is deferred and free. The charge total is zero, `tier`
    itself does not move, `pending_tier` is set to the requested tier — the tier a scheduled
    downgrade will move to at `current_period_end` — `last_change_charge_cents` is set to 0,
    `last_change_from_tier` records the tier held before the request, and the subscription's
    `version` advances by one. No credit is debited."

    Design: Corner/calculations/downgrade_defers_to_pending_tier_with_zero_charge
    """
    fx.set_clock(CLOCK_START)
    setup = fx.setup_upgrade_ready_customer(email="t@dna.test", tier="PRO", wallet_cents=500)
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]

    version = fx.read_subscription_version(sub_id, customer_id)
    data = validate_success(
        api.change_tier(
            sub_id, f.change_tier_payload("FREE", version), make_customer_headers(customer_id)
        )
    )

    assert data["tier"] == "PRO", "A downgrade does not move `tier`"
    assert data["pending_tier"] == "FREE"
    assert data["last_change_charge_cents"] == 0
    assert data["lifetime_charged_cents"] == 0

    customer = fx.read_customer(customer_id)
    assert customer["wallet_credit_cents"] == 500, "No credit is debited by a downgrade"


def test_upgrade_with_insufficient_wallet_credit_is_rejected(api):
    """PRD §3.2: "The customer's `wallet_credit_cents` must be at least the charge total, or
    the request is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

    Design: Corner/validations/upgrade_with_insufficient_wallet_credit_returns_402
    """
    fx.set_clock(CLOCK_START)
    setup = fx.setup_upgrade_ready_customer(email="poor@dna.test", tier="PLUS", wallet_cents=1000)
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]

    version = fx.read_subscription_version(sub_id, customer_id)
    # 30/30 remaining days: prorated 6000 -> discount 600 -> discounted 5400
    # -> fee round_half_up(156.6) = 157 -> charge total 5557, far above the 1000-cent wallet.
    resp = api.change_tier(
        sub_id, f.change_tier_payload("PRO", version), make_customer_headers(customer_id)
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value, 402)

    sub = fx.read_subscription(sub_id, customer_id)
    assert sub["tier"] == "PLUS"
    assert sub["lifetime_charged_cents"] == 0
    assert fx.read_customer(customer_id)["wallet_credit_cents"] == 1000


def test_change_tier_with_stale_subscription_version_is_rejected(api):
    """PRD §2.7: "A request to `POST /dna/subscriptions/{id}/change-tier` must carry the
    field `expected_subscription_version` in its payload, holding the `version` of the target
    Subscription as the client last observed it. A mismatch with the subscription's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/stale_expected_subscription_version_on_change_tier_returns_stale_version
    """
    fx.set_clock(CLOCK_START)
    setup = fx.setup_upgrade_ready_customer(email="occ2@dna.test", tier="PLUS", wallet_cents=20_000)
    sub_id = setup["subscription"]["id"]
    customer_id = setup["customer"]["id"]
    headers = make_customer_headers(customer_id)

    observed = fx.read_subscription_version(sub_id, customer_id)

    first = validate_success(api.change_tier(sub_id, f.change_tier_payload("PRO", observed), headers))
    assert first["last_change_charge_cents"] == 5557, (
        f"Expected a 5557-cent PLUS→PRO charge at 30/30 remaining days, "
        f"got {first['last_change_charge_cents']}"
    )

    # The client still holds the pre-change version.
    stale = api.change_tier(sub_id, f.change_tier_payload("FREE", observed), headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    sub = fx.read_subscription(sub_id, customer_id)
    assert sub["tier"] == "PRO", "The rejected change must not move the tier"
    assert sub["pending_tier"] is None

    wallet = fx.read_customer(customer_id)["wallet_credit_cents"]
    assert wallet == 14_443, f"Expected wallet 20000 - 5557 == 14443, got {wallet}"
