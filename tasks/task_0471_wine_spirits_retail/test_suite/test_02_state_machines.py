"""State machines: Order parallel dimensions, SpecialOrder negotiation loop,
Vintage availability, IdScan review, ClubMembership lifecycle, Shipment branch.

Covers difficulty queue non_linear_state_machine and corner queue state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Difficulty: non_linear_state_machine ───────────────────────────────────
def test_order_payment_and_fulfillment_dimensions_evolve_independently(api):
    """PRD §3.7: "Payment is a parallel dimension on the order, independent of fulfillment, and moves through its own state machine."
    PRD §3.7: "A `StoreAssociate` then captures payment, advancing `AUTHORIZED → CAPTURED`; this requires the order to be `AUTHORIZED` and `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions_evolve_independently
    """
    fx.set_clock()
    cust = fx.create_verified_customer("nl1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("NL-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)

    order = fx.build_submitted_order(cust, vint["id"], 2, channel="POS")
    fx.authorize(cust, order["id"])
    captured = validate_success(api_client.capture_payment(order["id"], ASSOCIATE))

    assert captured["fulfillment_status"] == "SUBMITTED", \
        f"fulfillment should still be SUBMITTED, got {captured['fulfillment_status']}"
    assert captured["payment_status"] == "CAPTURED", \
        f"payment should be CAPTURED, got {captured['payment_status']}"


def test_special_order_cyclic_quote_counter_revision_loop(api):
    """PRD §3.9: "The `Customer` may counter a quote, advancing `QUOTED → COUNTERED`, setting `customer_counter_price_cents` from the request body and incrementing `round_count` by one. A `StoreAssociate` may re-quote a countered request, advancing `COUNTERED → QUOTED` and again setting `quoted_unit_price_cents` — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/special_order_cyclic_quote_counter_revision_loop
    """
    fx.set_clock()
    cust = fx.register_customer("nl2@x.com", ship_state_code="CA")
    so = fx.create_special_order(cust, description="1990 rare port", requested_qty=2)
    cust_h = make_customer_headers(cust["id"])

    get_success_data(api_client.quote_special_order(so["id"], {"quoted_unit_price_cents": 9000}, ASSOCIATE))
    get_success_data(api_client.counter_special_order(so["id"], {"customer_counter_price_cents": 7000}, cust_h))
    requoted = validate_success(api_client.quote_special_order(
        so["id"], {"quoted_unit_price_cents": 8000}, ASSOCIATE))

    assert requoted["status"] == "QUOTED", f"status should be QUOTED, got {requoted['status']}"
    assert requoted["round_count"] == 1, f"round_count should be 1, got {requoted['round_count']}"
    assert requoted["quoted_unit_price_cents"] == 8000


# ─── Corner: state_machines ─────────────────────────────────────────────────
def test_new_order_starts_cart_unpaid_version_one(api):
    """PRD §3.3: "A new order is created with `fulfillment_status` `CART`, `payment_status` `UNPAID`, and `version` 1."

    Design: Corner/state_machines/order_initial_states_cart_and_unpaid
    """
    cust = fx.register_customer("is1@x.com", ship_state_code="CA")
    order = validate_success(api_client.create_order(
        {"customer_id": cust["id"], "channel": "POS"}, make_customer_headers(cust["id"])),
        expected_status=201)

    assert order["fulfillment_status"] == "CART"
    assert order["payment_status"] == "UNPAID"
    assert order["version"] == 1


def test_cancel_already_cancelled_order_returns_invalid_state(api):
    """PRD §2.10: "state legality — that the target is in a state from which the requested transition is defined (and, for an order, in the correct dimension), yielding `ERR_INVALID_STATE` (HTTP 409)"
    PRD §3.10: "Cancelling a `CART` order simply advances `fulfillment_status` `CART → CANCELLED`."

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_invalid_state
    """
    cust = fx.register_customer("ic1@x.com", ship_state_code="CA")
    cust_h = make_customer_headers(cust["id"])
    order = fx.create_cart_order(cust, channel="POS")
    get_success_data(api_client.cancel_order(order["id"], cust_h))

    resp = api_client.cancel_order(order["id"], cust_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_capture_before_authorize_returns_invalid_state(api):
    """PRD §3.7: "A `StoreAssociate` then captures payment, advancing `AUTHORIZED → CAPTURED`; this requires the order to be `AUTHORIZED` and `SUBMITTED`."
    PRD §2.10: "state legality ... yielding `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/capture_before_authorize_returns_invalid_state
    """
    fx.set_clock()
    cust = fx.create_verified_customer("cb1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("CB-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)
    order = fx.build_submitted_order(cust, vint["id"], 1, channel="POS")

    resp = api_client.capture_payment(order["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_idscan_verify_sets_customer_age_verified(api):
    """PRD §3.2: "On a successful verify, the owning customer's `age_verified` flips to true and that customer's `compliance_status` is recomputed."

    Design: Corner/state_machines/idscan_verify_sets_customer_age_verified_side_effect
    """
    fx.set_clock()
    cust = fx.register_customer("av1@x.com", ship_state_code="CA")
    scan = fx.create_pending_scan(cust)

    verified = validate_success(api_client.verify_id_scan(scan["id"], ASSOCIATE))
    assert verified["status"] == "VERIFIED"

    customer = get_success_data(api_client.get_customer(cust["id"], ASSOCIATE))
    assert customer["age_verified"] is True, "age_verified should flip to true on verify"


def test_idscan_verify_underage_rejected(api):
    """PRD §3.2: "Verification advances `PENDING → VERIFIED` only when the document is not expired ... and the scanned date of birth matches the owning customer's recorded `date_of_birth`, and the age in whole years derived from `scanned_dob` at the current time is at least 21."

    Design: Corner/state_machines/idscan_verify_underage_rejected_precondition
    """
    fx.set_clock()
    cust = fx.register_customer("ua1@x.com", ship_state_code="CA", date_of_birth="2010-01-01")
    scan = fx.create_pending_scan(cust, scanned_dob="2010-01-01")

    resp = api_client.verify_id_scan(scan["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_special_order_negotiation_rounds_exceeded(api):
    """PRD §3.9: "Both the counter and the re-quote transitions are guarded by the round limit: they are permitted only while `round_count` is below 3, and an attempt to counter or quote once `round_count` has reached 3 is rejected with `ERR_NEGOTIATION_ROUNDS_EXCEEDED` (HTTP 422)."

    Design: Corner/state_machines/special_order_negotiation_rounds_exceeded
    """
    cust = fx.register_customer("nr1@x.com", ship_state_code="CA")
    cust_h = make_customer_headers(cust["id"])
    so = fx.create_special_order(cust, description="rare", requested_qty=1)

    # Drive round_count to 3 via three quote/counter cycles, ending QUOTED.
    for q, c in [(9000, 8000), (8800, 8200), (8600, 8400)]:
        get_success_data(api_client.quote_special_order(so["id"], {"quoted_unit_price_cents": q}, ASSOCIATE))
        get_success_data(api_client.counter_special_order(so["id"], {"customer_counter_price_cents": c}, cust_h))
    get_success_data(api_client.quote_special_order(so["id"], {"quoted_unit_price_cents": 8500}, ASSOCIATE))

    resp = api_client.counter_special_order(so["id"], {"customer_counter_price_cents": 8450}, cust_h)
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXCEEDED.value)


def test_special_order_convert_creates_pickup_order(api):
    """PRD §3.9: "A `StoreAssociate` converts an accepted special order, advancing `ACCEPTED → CONVERTED`; conversion ... creates a new `PICKUP` order for the customer with one order line derived from the special order, recording the new order's identifier on the special order's `converted_order_id`."

    Design: Corner/state_machines/special_order_convert_creates_pickup_order
    """
    fx.set_clock()
    cust = fx.create_verified_customer("sc1@x.com", ship_state_code="CA")
    cust_h = make_customer_headers(cust["id"])
    so = fx.create_special_order(cust, description="rare", requested_qty=1)
    get_success_data(api_client.quote_special_order(so["id"], {"quoted_unit_price_cents": 9000}, ASSOCIATE))
    get_success_data(api_client.accept_special_order(so["id"], cust_h))

    converted = validate_success(api_client.convert_special_order(so["id"], ASSOCIATE))
    assert converted["status"] == "CONVERTED"
    assert converted["converted_order_id"] is not None, "converted_order_id must be populated"


def test_vintage_auto_sold_out_then_back_to_released(api):
    """PRD §3.1: "The system itself advances a vintage `RELEASED → SOLD_OUT` ... at submit time when, after the triggering commit, the sum across the vintage's lots of available units (each lot's `qty_on_hand` minus its `qty_reserved`) reaches zero; conversely, when a cancel or refund returns availability to a non-allocated, sold-out vintage so that the summed available units rises to at least 1, the system advances it `SOLD_OUT → RELEASED`."

    Design: Corner/state_machines/vintage_auto_sold_out_then_back_to_released_compound
    """
    fx.set_clock()
    cust = fx.create_verified_customer("so2@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("SO-2", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=2, vintage_year=2020)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 2)
    fx.submit_order(cust, order["id"])
    sold = get_success_data(api_client.get_vintage(vint["id"], ASSOCIATE))
    assert sold["status"] == "SOLD_OUT", f"vintage should be SOLD_OUT after depleting, got {sold['status']}"

    get_success_data(api_client.cancel_order(order["id"], make_customer_headers(cust["id"])))
    back = get_success_data(api_client.get_vintage(vint["id"], ASSOCIATE))
    assert back["status"] == "RELEASED", f"vintage should return to RELEASED on cancel, got {back['status']}"
    assert back["units_committed"] == 0


def test_delisted_vintage_cannot_release(api):
    """PRD §3.1: "Finally an `Admin` may delist a vintage, advancing it to `DELISTED` from `RELEASED`, `SOLD_OUT`, or `DRAFT` ... A delisted vintage is terminal."
    PRD §2.10: "state legality ... yielding `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/terminal_delisted_vintage_cannot_release
    """
    product = fx.create_product("DL-1", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)
    get_success_data(api_client.delist_vintage(vint["id"], ADMIN))

    resp = api_client.release_vintage(vint["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_allocation_on_non_allocated_product_rejected(api):
    """PRD §3.1: "a `ComplianceOfficer` opens allocation on an allocation-controlled vintage, advancing `DRAFT → ALLOCATION_OPEN`; this requires the vintage to be in `DRAFT`, its parent product to be allocation-controlled, and `allocation_cap_per_customer` to be non-null — any of those failing yields `ERR_ALLOCATION_OPEN_REQUIRES_FLAG`."

    Design: Corner/state_machines/open_allocation_on_non_allocated_product_rejected
    """
    product = fx.create_product("OA-1", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)

    resp = api_client.open_allocation(vint["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_OPEN_REQUIRES_FLAG.value)


def test_confirm_delivery_without_signature_rejected(api):
    """PRD §3.10: "Confirming delivery advances `DISPATCHED → DELIVERED`; when the shipment's `adult_signature_required` is true the request must provide `signature_captured` set to true, and omitting it is rejected with `ERR_SIGNATURE_REQUIRED` (HTTP 422)."

    Design: Corner/state_machines/confirm_delivery_without_signature_required_rejected
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         requires_adult_signature=True)
    cust = fx.create_verified_customer("sg1@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("SG-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    _, shipment = fx.build_dispatched_shipment(cust, vint["id"], 2, "TX")

    resp = api_client.confirm_delivery(shipment["id"], {}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_SIGNATURE_REQUIRED.value)


def test_club_reinstate_suspended_to_active(api):
    """PRD §3.8: "A `ComplianceOfficer` may suspend an active membership (`ACTIVE → SUSPENDED`) and reinstate a suspended one (`SUSPENDED → ACTIVE`)"

    Design: Corner/state_machines/club_reinstate_cycle_suspended_to_active
    """
    cust = fx.register_customer("rs1@x.com", ship_state_code="CA")
    cm = fx.create_membership(cust)
    get_success_data(api_client.suspend_membership(cm["id"], COMPLIANCE))

    reinstated = validate_success(api_client.reinstate_membership(cm["id"], COMPLIANCE))
    assert reinstated["status"] == "ACTIVE", f"status should be ACTIVE, got {reinstated['status']}"
