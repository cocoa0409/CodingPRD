"""RBAC, authentication, ownership precedence, error envelope, and OCC on the order."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success, validate_error,
    create_shop, create_customer, create_product, create_order, add_line,
    upload_and_pass_preflight, add_pickup_fulfillment, read_order_version, confirm_order,
    pin_clock, setup_confirmable_copies_order,
    TEST_USERS, build_user_headers, make_customer_headers, NON_EXISTENT_UUID, ApiErrorId,
)

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Difficulty: priority_pair (owner check beats state check) ───────────────
def test_owner_check_beats_state_check_on_confirm(api):
    """PRD §3.9: "Ownership comes fourth: a customer acting on an order, proof, or line
    they do not own yields `ERR_NOT_ORDER_OWNER`. State validity comes fifth, yielding
    `ERR_INVALID_STATE` when a target is not in a state that permits the requested
    transition."

    Design: Difficulty/priority_pair_validation_conflict/owner_check_beats_state_check_on_confirm
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Prio Shop"}, quantity=10)
    owner = ctx["customer"]
    order_id = ctx["order"]["id"]
    # Owner confirms first so the order is already CONFIRMED (state check would now fail).
    confirmed = validate_success(confirm_order(order_id, owner["id"], ctx["version"]), 200)
    other = create_customer(ctx["shop"]["id"], email="other@x.com")
    other_headers = make_customer_headers(other["id"])
    # Non-owner confirms an already-CONFIRMED order: ownership (4) wins over state (5).
    res = api.confirm_order(order_id, {"expected_order_version": confirmed["version"]}, other_headers)
    validate_error(res, ApiErrorId.ERR_NOT_ORDER_OWNER, expected_status=403)


def test_non_owner_confirm_rejected_on_owner_check(api):
    """PRD §2.1: "a customer acting on an order, on a proof, or on a line must be the owner
    of the order in question — the order's `customer_id` must equal `X-User-ID` — and a
    violation is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/owner_check_beats_state_check_on_confirm
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Prio Shop 2"}, quantity=10)
    order_id = ctx["order"]["id"]
    # Order is a confirmable DRAFT; a non-owner tries to confirm it -> ownership rejection.
    other = create_customer(ctx["shop"]["id"], email="other2@x.com")
    res = api.confirm_order(order_id, {"expected_order_version": ctx["version"]},
                            make_customer_headers(other["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_ORDER_OWNER, expected_status=403)


# ─── Role-based access control ───────────────────────────────────────────────
def test_production_operator_cannot_create_shop(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.1: "A `ShopStaff` member stands up a shop before any order can flow".

    Design: Corner/rbac/production_operator_cannot_create_shop
    """
    res = api.create_shop(
        {"name": "Nope", "tax_rate_bps": 0, "rush_surcharge_bps": 0, "rush_cutoff_hour_utc": 14,
         "standard_turnaround_days": 3, "rush_turnaround_days": 1, "daily_unit_capacity": 50},
        OPERATOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_shopstaff_cannot_run_preflight(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §3.3: "A
    `ProductionOperator` then runs preflight on an uploaded file."

    Design: Corner/rbac/shopstaff_cannot_run_preflight
    """
    shop = create_shop(name="S29")
    cust = create_customer(shop["id"], email="s29@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    art = get_success_data(api.create_artwork(
        {"order_line_id": line["id"], "file_name": "s29.pdf", "page_count": 1,
         "dpi": 600, "bleed_mm": 3}, make_customer_headers(cust["id"])))
    res = api.run_preflight(art["id"], STAFF)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, declaring the capacity in which they act. A
    request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    shop = create_shop(name="S30")
    res = api.get_shop(shop["id"], {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ─── Error envelope shape ────────────────────────────────────────────────────
def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope
    format" with `response_type` "error" and `data` carrying `error_id` and `message`. PRD
    §2.5: "the first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    create_shop(name="S31")
    res = api.get_product(NON_EXISTENT_UUID, STAFF)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str) and len(body["data"]["message"]) > 0


# ─── Optimistic concurrency on the order ─────────────────────────────────────
def test_confirm_with_stale_version_rejected(api):
    """PRD §2.9: "If the order's current `version` differs from the supplied
    `expected_order_version` — because, for instance, a reorder clone, a line lock, or a
    cancel advanced the version after the client last read the order — the request is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) before any line is locked". PRD §3.8:
    "The act of reordering also increments the source order's `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_confirm_rejected
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "S32"}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    stale_v = ctx["version"]
    # A reorder of THIS order bumps its version, making stale_v one behind.
    validate_success(api.reorder(order_id, {"expected_order_version": stale_v}, cust_headers), 201)
    res = api.confirm_order(order_id, {"expected_order_version": stale_v}, cust_headers)
    validate_error(res, ApiErrorId.ERR_STALE_ORDER_VERSION, expected_status=412)


def test_confirm_increments_order_version_by_one(api):
    """PRD §3.6: "Confirmation advances `production_status` from `DRAFT` to `CONFIRMED` and
    increments the order's `version`." PRD §2.9: confirm carries `expected_order_version`
    "carrying the client's last observed `version` of the target order."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_confirm
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "S33"}, quantity=10)
    cust = ctx["customer"]
    v0 = ctx["version"]
    confirmed = validate_success(confirm_order(ctx["order"]["id"], cust["id"], v0), 200)
    assert confirmed["version"] == v0 + 1
