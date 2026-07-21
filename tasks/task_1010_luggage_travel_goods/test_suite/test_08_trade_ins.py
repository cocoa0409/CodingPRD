"""Trade-ins: offer valuation, store-credit conservation, expiry, and OCC on create."""
import test_helpers as H


# ==========================================================================
# Queue A — compensating invariant: accept then void conserves store credit
# ==========================================================================
def test_void_accepted_trade_in_reports_offer_and_terminal_state(api, manager_headers):
    """PRD §3.6: "A raw value is the product's `msrp_cents` multiplied by the condition factor —
    0.40 for `LIKE_NEW`, 0.30 for `GOOD`, 0.20 for `FAIR`, and 0.10 for `POOR` — rounded half-up to
    whole cents."
    PRD §3.6: "A `Manager` may void an already-accepted offer, moving `ACCEPTED → VOIDED`, which
    subtracts the `offer_amount_cents` back out of the customer's `store_credit_cents`, restoring
    the store-credit invariant."

    Design: Difficulty/compensating_invariant/store_credit_accept_then_void_conserves_credit
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=30000)
    ti = H.new_trade_in(customer["id"], product["id"], customer["version"], api, condition="GOOD")
    assert ti["offer_amount_cents"] == 9000
    H.get_success_data(api.accept_trade_in(ti["id"], manager_headers))
    voided = H.validate_success(api.void_trade_in(ti["id"], manager_headers))
    assert voided["status"] == "VOIDED"


def test_void_accepted_trade_in_restores_store_credit(api, manager_headers):
    """PRD §3.6: "A `Manager` may void an already-accepted offer, moving `ACCEPTED → VOIDED`, which
    subtracts the `offer_amount_cents` back out of the customer's `store_credit_cents`, restoring
    the store-credit invariant."

    Design: Difficulty/compensating_invariant/store_credit_accept_then_void_conserves_credit
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=30000)
    ti = H.new_trade_in(customer["id"], product["id"], customer["version"], api, condition="GOOD")
    H.get_success_data(api.accept_trade_in(ti["id"], manager_headers))
    H.get_success_data(api.void_trade_in(ti["id"], manager_headers))
    assert H.get_customer(customer["id"], api)["store_credit_cents"] == 0


# ==========================================================================
# Queue B — calculations: fair-condition offer value
# ==========================================================================
def test_trade_in_fair_condition_offer_value(api):
    """PRD §3.6: "A raw value is the product's `msrp_cents` multiplied by the condition factor —
    0.40 for `LIKE_NEW`, 0.30 for `GOOD`, 0.20 for `FAIR`, and 0.10 for `POOR` — rounded half-up to
    whole cents."

    Design: Corner/calculations/trade_in_offer_fair_condition_value
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=30000)
    ti = H.new_trade_in(customer["id"], product["id"], customer["version"], api, condition="FAIR")
    assert ti["offer_amount_cents"] == 6000


# ==========================================================================
# Queue B — validations: accept after expiry
# ==========================================================================
def test_accept_expired_trade_in_rejected(api, manager_headers):
    """PRD §3.6: "If a `Manager` attempts to accept after expiry — when the clock is at or past
    `expires_at` — the offer is auto-expired on that touch, transitioning `OFFERED → EXPIRED`, and
    the accept is rejected with `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/accept_expired_trade_in_returns_offer_expired
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=30000)
    ti = H.new_trade_in(customer["id"], product["id"], customer["version"], api, condition="GOOD")
    H.set_clock("2026-08-01T00:00:00Z", api)
    H.validate_error(api.accept_trade_in(ti["id"], manager_headers), H.ApiErrorId.ERR_OFFER_EXPIRED)


# ==========================================================================
# Queue B — errors: OCC on trade-in creation
# ==========================================================================
def test_create_trade_in_with_stale_customer_version_rejected(api, associate_headers):
    """PRD §2.7: "Creating a trade-in offer requires `expected_customer_version`, which must equal
    the current `version` of the target `Customer`."

    Design: Corner/errors/create_trade_in_stale_customer_version_returns_stale
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=30000)
    H.new_trade_in(customer["id"], product["id"], customer["version"], api, condition="GOOD")  # bumps version 1 -> 2
    resp = api.create_trade_in(
        H.create_trade_in_payload(customer["id"], product["id"], customer["version"], condition="FAIR"),
        associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_STALE_VERSION)
