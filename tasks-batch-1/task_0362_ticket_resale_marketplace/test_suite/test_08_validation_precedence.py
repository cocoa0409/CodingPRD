"""Validation priority resolution when two conditions both apply.

A frozen listing's state guard pre-empts the wallet fiscal guard, and an expired
reservation's temporal guard pre-empts later constraint checks (PRD §2.8, §3.4,
§3.8).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


def test_frozen_listing_state_beats_insufficient_wallet_fiscal(api):
    """PRD §2.8: "Fifth, the target resource and any cross-entity dependency must
    be in a state that permits the transition; state failures surface as
    `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_EVENT_NOT_SELLING`,
    `ERR_LISTING_FROZEN`, `ERR_DELIVERY_BEFORE_PAYMENT`, or
    `ERR_PAYOUT_NOT_RELEASABLE` as appropriate."
    PRD §2.8: "Ninth, fiscal constraints apply (`ERR_INSUFFICIENT_WALLET_CREDIT`,
    `ERR_PRICE_CAP_EXCEEDED`, `ERR_DYNAMIC_FLOOR_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_listing_state_beats_insufficient_wallet_fiscal
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    listing, seats = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, barcode_prefix="FRZ",
    )
    # A HIGH DUPLICATE_BARCODE flag on a seat freezes the listing immediately.
    get_success_data(api.create_fraud_flag(
        F.create_fraud_flag_payload("SEAT", "DUPLICATE_BARCODE", seat_id=seats[0]["id"]), TRUST))
    frozen = validate_success(api.get_listing(listing["id"], ADMIN))
    assert frozen["status"] == "FROZEN"

    # Order on a FROZEN listing AND requesting more credit (5000) than wallet (0).
    payload = F.create_order_payload(
        listing["id"], base["buyer_id"], listing["version"],
        quantity=1, applied_credit_cents=5000,
    )
    resp = api.create_order(payload, make_buyer_headers(base["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_FROZEN.value)


# ==========================================================================
# Companion tests (second test per Difficulty instance)
# ==========================================================================
def test_frozen_listing_blocks_reservation_even_without_credit(api):
    """PRD §3.8: "The moment a `HIGH`-severity flag lands on a listing, that
    listing is frozen: a `DRAFT` or `ACTIVE` listing transitions to `FROZEN`, and
    while frozen it rejects both activation and reservation with
    `ERR_LISTING_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_listing_state_beats_insufficient_wallet_fiscal
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    listing, seats = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, barcode_prefix="FRZ2",
    )
    get_success_data(api.create_fraud_flag(
        F.create_fraud_flag_payload("SEAT", "DUPLICATE_BARCODE", seat_id=seats[0]["id"]), TRUST))
    frozen = validate_success(api.get_listing(listing["id"], ADMIN))
    assert frozen["status"] == "FROZEN"

    # A plain reservation with no credit at all still blocks on FROZEN (the
    # state guard, not the fiscal guard).
    payload = F.create_order_payload(listing["id"], base["buyer_id"], listing["version"], quantity=1)
    resp = api.create_order(payload, make_buyer_headers(base["buyer_id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_FROZEN.value)


def test_charge_within_reservation_window_succeeds(api):
    """PRD §3.4: "the current clock is before `reservation_expires_at` ... A charge
    attempted after `reservation_expires_at` is rejected with
    `ERR_RESERVATION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/reservation_expired_temporal_beats_split_rule_constraint
    """
    fx.set_clock("2027-05-01T10:00:00.000Z")
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2,
                            doors_open_at="2027-06-01T19:00:00.000Z")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, split_rule="PAIRS", barcode_prefix="EXP2",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 2, listing["version"])

    # Charge immediately (within the reservation window) → succeeds.
    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(base["buyer_id"])))
    assert charged["payment_status"] == "CHARGED"
