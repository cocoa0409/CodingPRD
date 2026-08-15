"""Product catalog, shelf-life lot expiry variants, discontinuation cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot,
    assert_product,
    get_success_data,
    make_blanket_order,
    make_contract,
    make_lot,
    make_machine,
    make_product,
    make_release,
    make_standard,
    get_lot,
    get_order,
    get_release,
    get_standard,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc / lot_expiry_exact_vs_eom
# ---------------------------------------------------------------------------


def test_lot_expiry_exact_day_variant(api):
    """PRD §3.3: "Under the `EXACT_DAY` policy, `expiry_date` is the
    `manufacture_date` advanced by `shelf_life_months` calendar months; if the
    target month has no such day-of-month, the date clamps to the target month's
    last day."
    PRD §3.3: "For example, a lot manufactured on 2026-01-15 with a 12-month
    shelf life expires on 2027-01-15 under `EXACT_DAY` but on 2027-01-31 under
    `END_OF_MONTH`."

    Design: Difficulty/dual_variant_calc/lot_expiry_exact_vs_eom
    """
    product = make_product(
        sku="BW-EX",
        name="Bonded Wheel Exact",
        product_form="BONDED",
        max_operating_speed_rpm=6000,
        shelf_life_months=12,
        shelf_life_policy="EXACT_DAY",
    )
    lot = make_lot(
        product["id"], lot_code="L-EX", manufacture_date="2026-01-15", qty_received=10
    )
    assert_lot(lot)
    assert lot["expiry_date"] == "2027-01-15", (
        f"EXACT_DAY expiry must be the 12-month anniversary 2027-01-15, "
        f"got {lot['expiry_date']!r}"
    )


def test_lot_expiry_end_of_month_variant(api):
    """PRD §3.3: "Under the `END_OF_MONTH` policy, `expiry_date` is the last
    calendar day of the month reached by advancing `manufacture_date` by
    `shelf_life_months` months — later than the `EXACT_DAY` result whenever the
    manufacture day-of-month precedes the last day."
    PRD §3.3: "For example, a lot manufactured on 2026-01-15 with a 12-month
    shelf life expires on 2027-01-15 under `EXACT_DAY` but on 2027-01-31 under
    `END_OF_MONTH`."

    Design: Difficulty/dual_variant_calc/lot_expiry_exact_vs_eom
    """
    product = make_product(
        sku="BW-EOM",
        name="Bonded Wheel EOM",
        product_form="BONDED",
        max_operating_speed_rpm=6000,
        shelf_life_months=12,
        shelf_life_policy="END_OF_MONTH",
    )
    lot = make_lot(
        product["id"], lot_code="L-EOM", manufacture_date="2026-01-15", qty_received=10
    )
    assert lot["expiry_date"] == "2027-01-31", (
        f"END_OF_MONTH expiry must be the last day of the expiry month "
        f"2027-01-31, got {lot['expiry_date']!r}"
    )


# ---------------------------------------------------------------------------
# Corner / entities / product_creation_applies_defaults
# ---------------------------------------------------------------------------


def test_product_creation_applies_defaults(api):
    """PRD §3.1: "`shelf_life_policy` selects the expiry variant and is one of
    `EXACT_DAY` or `END_OF_MONTH`, defaulting to `EXACT_DAY` when omitted.
    `used_media_hazard_class` classifies the spent media as `NONE`,
    `METAL_SWARF`, or `OIL_CONTAMINATED`, defaulting to `NONE`. A new product
    starts `ACTIVE`."
    PRD §3.3: "When the product has no `shelf_life_months`, `expiry_date` is
    null — the lot never expires by shelf life."
    PRD §3.3: "The lot starts `AVAILABLE` with `qty_on_hand` initialized to
    `qty_received`"

    Design: Corner/entities/product_creation_applies_defaults
    """
    resp = api.create_product(
        {
            "sku": "DF-1",
            "name": "Default Flap Disc",
            "product_form": "COATED",
            "max_operating_speed_rpm": 6000,
        },
        ADMIN,
    )
    product = validate_success(resp, 201)
    assert_product(product)
    assert product["shelf_life_policy"] == "EXACT_DAY"
    assert product["used_media_hazard_class"] == "NONE"
    assert product["status"] == "ACTIVE"

    lot = make_lot(
        product["id"], lot_code="L-DF", manufacture_date="2026-06-01", qty_received=10
    )
    assert lot["expiry_date"] is None, (
        f"COATED product has no shelf life; expiry_date must be null, "
        f"got {lot['expiry_date']!r}"
    )
    assert lot["qty_on_hand"] == 10
    assert lot["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Corner / entities / bonded_product_missing_shelf_life_rejected
# ---------------------------------------------------------------------------


def test_bonded_product_missing_shelf_life_rejected(api):
    """PRD §3.1: "it is **required when the product form is `BONDED`** (bonded
    products degrade; omitting it is rejected with `ERR_INVALID_REQUEST`) and
    ignored for other forms."

    Design: Corner/entities/bonded_product_missing_shelf_life_rejected
    """
    resp = api.create_product(
        {
            "sku": "BD-X",
            "name": "Bonded No Shelf",
            "product_form": "BONDED",
            "max_operating_speed_rpm": 6000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner / entities / product_invalid_enum_rejected
# ---------------------------------------------------------------------------


def test_product_invalid_enum_rejected(api):
    """PRD §2.8 item 3: "Request shape — required fields present, enum values
    valid ... (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "the `product_form` — one of `COATED`, `BONDED`, or `NONWOVEN`"

    Design: Corner/entities/product_invalid_enum_rejected
    """
    resp = api.create_product(
        {
            "sku": "BD-E",
            "name": "Bad Enum",
            "product_form": "FLAPPY",
            "max_operating_speed_rpm": 6000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner / entities / lot_get_not_found_returns_404
# ---------------------------------------------------------------------------


def test_lot_get_not_found_returns_404(api):
    """PRD §2.8 item 4: "Missing ids yield `ERR_NOT_FOUND` (404)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/lot_get_not_found_returns_404
    """
    resp = api.get_lot("11111111-2222-4333-8444-555555555555", ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()
    assert isinstance(body["meta"].get("api_request_id"), str)


# ---------------------------------------------------------------------------
# Corner / entities / lot_list_filter_and_pagination
# ---------------------------------------------------------------------------


def test_lot_list_filter_and_pagination(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    items skipped and defaults to 0. Every list response sorts by `created_at`
    ascending, and every list response includes `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §2.3: "Lots may be filtered by `product_id` or `status`."

    Design: Corner/entities/lot_list_filter_and_pagination
    """
    from test_helpers import validate_paginated

    pa = make_product(sku="LP-A", name="List Prod A")
    pb = make_product(sku="LP-B", name="List Prod B")
    make_lot(pa["id"], lot_code="LA1", manufacture_date="2026-06-01")
    make_lot(pa["id"], lot_code="LA2", manufacture_date="2026-06-02")
    make_lot(pb["id"], lot_code="LB1", manufacture_date="2026-06-03")

    page1, meta1 = validate_paginated(
        api.list_lots(AM, params={"product_id": pa["id"], "limit": 1, "offset": 0})
    )
    assert meta1["total_count"] == 2, f"filtered total_count: {meta1}"
    assert meta1["has_more"] is True
    assert len(page1) == 1
    assert page1[0]["product_id"] == pa["id"]

    page2, meta2 = validate_paginated(
        api.list_lots(AM, params={"product_id": pa["id"], "limit": 1, "offset": 1})
    )
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert len(page2) == 1
    assert page2[0]["product_id"] == pa["id"]

    for item in page1 + page2:
        assert item["product_id"] != pb["id"], "filtered-out product leaked into page"


# ---------------------------------------------------------------------------
# Corner / entities / lot_create_fk_product_not_found
# ---------------------------------------------------------------------------


def test_lot_create_fk_product_not_found(api):
    """PRD §2.8 item 4: "Existence — path identifiers are resolved first; then
    body foreign keys in the order they appear in the payload (machine, product,
    lot, contract, blanket order). ... Missing ids yield `ERR_NOT_FOUND` (404)."
    PRD §3.3: "An `AccountManager` receives stock by lot, supplying the
    `product_id`"

    Design: Corner/entities/lot_create_fk_product_not_found
    """
    resp = api.create_lot(
        {
            "product_id": "11111111-2222-4333-8444-555555555555",
            "lot_code": "L-ORPHAN",
            "manufacture_date": "2026-06-01",
            "qty_received": 10,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / lot_expiry_sweep_boundary
# ---------------------------------------------------------------------------


def test_lot_expiry_sweep_stays_available_on_expiry_day(api):
    """PRD §2.4: "every inventory lot still `AVAILABLE` whose `expiry_date` is
    strictly earlier than the new clock date transitions to `EXPIRED`; a lot
    whose expiry date equals the new date stays `AVAILABLE`."

    Design: Corner/state_machines/lot_expiry_sweep_boundary
    """
    product = make_product(
        sku="LX-1",
        name="Expiry Wheel",
        product_form="BONDED",
        shelf_life_months=3,
        shelf_life_policy="EXACT_DAY",
    )
    lot = make_lot(
        product["id"], lot_code="L-LX", manufacture_date="2026-07-01", qty_received=10
    )
    assert lot["expiry_date"] == "2026-10-01"

    sweep = set_clock("2026-10-01T00:00:00Z")
    assert sweep["lots_expired"] == 0, (
        f"expiry_date == clock date must not expire the lot; sweep: {sweep}"
    )
    assert get_lot(lot["id"])["status"] == "AVAILABLE"


def test_lot_expiry_sweep_expires_after_expiry_day(api):
    """PRD §2.4: "every inventory lot still `AVAILABLE` whose `expiry_date` is
    strictly earlier than the new clock date transitions to `EXPIRED`; a lot
    whose expiry date equals the new date stays `AVAILABLE`."

    Design: Corner/state_machines/lot_expiry_sweep_boundary
    """
    product = make_product(
        sku="LX-2",
        name="Expiry Wheel 2",
        product_form="BONDED",
        shelf_life_months=3,
        shelf_life_policy="EXACT_DAY",
    )
    lot = make_lot(
        product["id"], lot_code="L-LX2", manufacture_date="2026-07-01", qty_received=10
    )
    assert lot["expiry_date"] == "2026-10-01"

    sweep = set_clock("2026-10-02T00:00:00Z")
    assert sweep["lots_expired"] == 1, f"sweep result: {sweep}"
    assert get_lot(lot["id"])["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade / product_discontinue_cascade_depth2
# ---------------------------------------------------------------------------


def _setup_discontinue_cascade(sku_prefix="AB"):
    p1 = make_product(
        sku=f"{sku_prefix}-OLD", name="Abrasive Old", max_operating_speed_rpm=6000
    )
    p2 = make_product(
        sku=f"{sku_prefix}-NEW", name="Abrasive New", max_operating_speed_rpm=6500
    )
    contract = make_contract(
        [
            {"product_id": p1["id"], "base_unit_price_cents": 9000},
            {"product_id": p2["id"], "base_unit_price_cents": 9500},
        ],
        customer_ref="PLANT-7",
        contract_number=f"C-{sku_prefix}",
    )
    order = make_blanket_order(contract["id"], p1["id"], committed_qty=50)
    release = make_release(
        order["id"], order["version"], qty=5, scheduled_ship_date="2026-09-01"
    )
    lot = make_lot(p1["id"], lot_code=f"L-{sku_prefix}", qty_received=20)
    return p1, p2, contract, order, release, lot


def test_discontinue_cascade_order_pending_and_release_on_hold(api):
    """PRD §3.1: "**Hop 1 — blanket orders.** Every blanket order in `DRAFT` or
    `OPEN` whose committed product is the discontinued product has its
    `substitution_status` set to `PENDING`.
    **Hop 2 — releases.** Every release in `SCHEDULED` belonging to a blanket
    order that just became `PENDING` moves to `ON_HOLD`."

    Design: Difficulty/transitive_cascade/product_discontinue_cascade_depth2
    """
    p1, p2, _c, order, release, _lot = _setup_discontinue_cascade()
    resp = api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN)
    product = validate_success(resp, 200)
    assert product["status"] == "DISCONTINUED"
    assert product["replacement_product_id"] == p2["id"]

    order_after = get_order(order["id"])
    assert order_after["substitution_status"] == "PENDING"
    assert order_after["status"] == "OPEN", "hop 1 leaves the order itself OPEN"

    release_after = get_release(release["id"])
    assert release_after["status"] == "ON_HOLD", (
        f"release of a just-PENDING order must move to ON_HOLD, got "
        f"{release_after['status']!r}"
    )


def test_discontinue_cascade_lot_fanout_blocked(api):
    """PRD §3.1: "**Fan-out — lots.** Every inventory lot in `AVAILABLE`
    stocking the discontinued product moves to `BLOCKED`."
    PRD §3.1: "the product moves to `DISCONTINUED`, and both
    `replacement_product_id` and `discontinued_at` (stamped from the logical
    clock) are recorded on it."

    Design: Difficulty/transitive_cascade/product_discontinue_cascade_depth2
    """
    p1, p2, _c, _order, _rel, lot = _setup_discontinue_cascade(sku_prefix="AB2")
    resp = api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN)
    product = validate_success(resp, 200)
    assert product["status"] == "DISCONTINUED"
    assert product["replacement_product_id"] == p2["id"]
    assert product.get("discontinued_at"), "discontinued_at must be stamped"

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "BLOCKED", (
        f"AVAILABLE lot of the discontinued product must move to BLOCKED, got "
        f"{lot_after['status']!r}"
    )


# ---------------------------------------------------------------------------
# Corner / state_machines / product_double_discontinue_rejected
# ---------------------------------------------------------------------------


def test_product_double_discontinue_rejected(api):
    """PRD §3.1: "The product must currently be `ACTIVE` — discontinuing
    anything else is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/product_double_discontinue_rejected
    """
    p1 = make_product(sku="DD-1", name="Double Disc 1")
    p2 = make_product(sku="DD-2", name="Double Disc 2", max_operating_speed_rpm=6500)
    resp = api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN)
    validate_success(resp, 200)

    resp2 = api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / errors / discontinue_replacement_invalid_rejected
# ---------------------------------------------------------------------------


def test_discontinue_replacement_self_rejected(api):
    """PRD §3.1: "a replacement that is the product itself, or that is not
    `ACTIVE`, is rejected with `ERR_REPLACEMENT_INVALID`."

    Design: Corner/errors/discontinue_replacement_invalid_rejected
    """
    p1 = make_product(sku="RI-1", name="Repl Invalid 1")
    resp = api.discontinue_product(p1["id"], {"replacement_product_id": p1["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPLACEMENT_INVALID.value)
    assert api.get_product(p1["id"], ADMIN).json()["data"]["status"] == "ACTIVE"


def test_discontinue_replacement_not_active_rejected(api):
    """PRD §3.1: "a replacement that is the product itself, or that is not
    `ACTIVE`, is rejected with `ERR_REPLACEMENT_INVALID`."

    Design: Corner/errors/discontinue_replacement_invalid_rejected
    """
    p1 = make_product(sku="RI-4", name="Repl Invalid 4")
    p2 = make_product(sku="RI-5", name="Repl Invalid 5")
    p3 = make_product(sku="RI-6", name="Repl Invalid 6")
    # P2 is discontinued first (with replacement P3), so P2 is not ACTIVE.
    validate_success(
        api.discontinue_product(p2["id"], {"replacement_product_id": p3["id"]}, ADMIN),
        200,
    )
    resp = api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPLACEMENT_INVALID.value)
    assert api.get_product(p1["id"], ADMIN).json()["data"]["status"] == "ACTIVE"


def test_discontinue_replacement_omitted_rejected(api):
    """PRD §3.1: "A missing replacement id is `ERR_INVALID_REQUEST`"

    Design: Corner/errors/discontinue_replacement_invalid_rejected
    """
    p1 = make_product(sku="RI-7", name="Repl Invalid 7")
    resp = api.discontinue_product(p1["id"], {}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert api.get_product(p1["id"], ADMIN).json()["data"]["status"] == "ACTIVE"
