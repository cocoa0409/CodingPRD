"""Corner-queue entity creation, retrieval, listing, not-found, validation, defaults."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_basic_plan, create_executive_plan, create_product,
    create_active_membership, NON_EXISTENT_UUID, ApiErrorId,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]
MEMBER = TEST_USERS["member_headers"]
ANON = None  # anonymous: no headers


# --- Creation happy paths ---
def test_create_plan_basic_returns_201(api):
    """PRD §3.1: "It carries a tier that is either BASIC or EXECUTIVE, an annual_fee_cents
    of at least 0 ... A basic plan earns no reward: for tier BASIC both reward_rate_bps and
    reward_cap_cents must be 0, and reward_rate_bps defaults to 0."

    Design: Corner/entities/create_plan_basic_returns_201_with_fields
    """
    res = api.create_plan({"tier": "BASIC", "annual_fee_cents": 6000,
                           "max_household_cards": 1, "addon_fee_cents": 4000}, ADMIN)
    data = validate_success(res, 201)
    assert data["tier"] == "BASIC"
    assert data["annual_fee_cents"] == 6000
    assert data["reward_rate_bps"] == 0


def test_create_membership_starts_pending(api):
    """PRD §3.2: "Signup creates a Membership in PENDING_PAYMENT status."
    PRD §2.4: "an integer version that starts at its initial value and increments by one on
    each mutation."

    Design: Corner/entities/create_membership_starts_pending_payment
    """
    plan = create_basic_plan()
    res = api.create_membership({"plan_id": plan["id"], "primary_member_name": "New Mem"}, ADMIN)
    data = validate_success(res, 201)
    assert data["status"] == "PENDING_PAYMENT"
    assert data["version"] == 1


def test_create_product_defaults(api):
    """PRD §3.1: "a member_only flag (default false) ... a per_member_limit (max units a
    membership may buy of this product per term, at least 0, where 0 means unlimited,
    default 0)."

    Design: Corner/entities/create_product_returns_201
    """
    res = api.create_product({"sku": "P-CREATE", "list_price_cents": 10000,
                              "member_price_cents": 8000}, ADMIN)
    data = validate_success(res, 201)
    assert data["member_only"] is False
    assert data["per_member_limit"] == 0


def test_create_instant_saving_max_units_default(api):
    """PRD §3.1: "a max_units that caps how many units per transaction line the discount may
    apply to (at least 0, where 0 means unlimited, default 0)."

    Design: Corner/entities/create_instant_saving_returns_201
    """
    product = create_product("P-IS")
    res = api.create_instant_saving({"product_id": product["id"], "kind": "INSTANT_SAVINGS",
                                     "amount_cents": 1000,
                                     "window_start_utc": "2026-03-01T00:00:00Z",
                                     "window_end_utc": "2026-06-01T00:00:00Z"}, ADMIN)
    data = validate_success(res, 201)
    assert data["max_units"] == 0


# --- Retrieval ---
def test_get_membership_returns_entity(api):
    """PRD §3.9: "A membership read recomputes and returns the derived reward, fee, and
    household-card fields so callers always see a reconciled view."

    Design: Corner/entities/get_membership_returns_stored_entity
    """
    plan = create_basic_plan()
    m = get_success_data(api.create_membership(
        {"plan_id": plan["id"], "primary_member_name": "Get Mem"}, ADMIN))
    res = api.get_membership(m["id"], make_member_headers(m["id"]))
    data = validate_success(res, 200)
    assert data["primary_member_name"] == "Get Mem"
    assert data["reward_accrued_cents"] == 0


def test_get_product_returns_stored_prices(api):
    """PRD §3.1: "A product carries a sku ... a list_price_cents (the non-member shelf
    price, at least 0), a member_price_cents (the member-only price, at least 0 and never
    above the list price)."

    Design: Corner/entities/get_product_returns_stored_entity
    """
    product = create_product("P-GET", list_price_cents=12000, member_price_cents=9000)
    res = api.get_product(product["id"], CLERK)
    data = validate_success(res, 200)
    assert data["member_price_cents"] == 9000
    assert data["list_price_cents"] == 12000


# --- Listing / pagination ---
def test_list_plans_paginated_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and has_more in
    the envelope's meta object."

    Design: Corner/entities/list_plans_paginated_envelope
    """
    create_basic_plan()
    create_executive_plan()
    res = api.list_plans(ADMIN, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_products_filter_by_department(api):
    """PRD §3.1: "a department drawn from GENERAL, GAS, PHARMACY, and OPTICAL."

    Design: Corner/entities/list_products_filter_by_department
    """
    create_product("P-GEN", department="GENERAL")
    pharm = create_product("P-PHARM", list_price_cents=5000, member_price_cents=4000,
                           department="PHARMACY")
    res = api.list_products(CLERK, params={"department": "PHARMACY"})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert data[0]["id"] == pharm["id"]


# --- Not found ---
def test_get_membership_not_found(api):
    """PRD §2.5: "The request is rejected at the first identifier that does not resolve,
    using that identifier's not-found code: ERR_MEMBERSHIP_NOT_FOUND ... all HTTP 404."

    Design: Corner/entities/get_membership_not_found
    """
    res = api.get_membership(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND)


def test_get_product_not_found(api):
    """PRD §2.5: "using that identifier's not-found code: ... ERR_PRODUCT_NOT_FOUND ... all
    HTTP 404."

    Design: Corner/entities/get_product_not_found
    """
    res = api.get_product(NON_EXISTENT_UUID, CLERK)
    validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


def test_get_return_not_found(api):
    """PRD §2.5: "using that identifier's not-found code: ... ERR_RETURN_NOT_FOUND ... all
    HTTP 404."

    Design: Corner/entities/get_return_not_found
    """
    res = api.get_return(NON_EXISTENT_UUID, SVC)
    validate_error(res, ApiErrorId.ERR_RETURN_NOT_FOUND)


def test_get_card_not_found(api):
    """PRD §2.5: "using that identifier's not-found code: ... ERR_CARD_NOT_FOUND ... all
    HTTP 404."

    Design: Corner/entities/get_card_not_found
    """
    res = api.get_household_card(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_CARD_NOT_FOUND)


def test_signup_plan_not_found(api):
    """PRD §2.5: "using that identifier's not-found code: ... ERR_PLAN_NOT_FOUND ... all
    HTTP 404."

    Design: Corner/entities/signup_plan_not_found
    """
    res = api.create_membership({"plan_id": NON_EXISTENT_UUID, "primary_member_name": "X"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_FOUND)


def test_open_transaction_membership_not_found(api):
    """PRD §2.5: "the membership first ... The request is rejected at the first identifier
    that does not resolve, using that identifier's not-found code: ERR_MEMBERSHIP_NOT_FOUND."

    Design: Corner/entities/open_transaction_membership_not_found
    """
    res = api.create_transaction({"membership_id": NON_EXISTENT_UUID}, CLERK)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND)


def test_instant_saving_invalid_product_fk_not_found(api):
    """PRD §3.1: "A promotion is an InstantSaving row attached to a product via product_id."
    PRD §2.5: "using that identifier's not-found code: ... ERR_PRODUCT_NOT_FOUND ... HTTP 404."

    Design: Corner/entities/instant_saving_invalid_product_fk_not_found
    """
    res = api.create_instant_saving({"product_id": NON_EXISTENT_UUID, "kind": "INSTANT_SAVINGS",
                                     "amount_cents": 1000,
                                     "window_start_utc": "2026-03-01T00:00:00Z",
                                     "window_end_utc": "2026-06-01T00:00:00Z"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


# --- Required fields / type constraints ---
def test_create_membership_missing_plan_id(api):
    """PRD §2.6: "(4) request well-formedness — required body fields present and correctly
    typed ... yielding ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_membership_missing_plan_id_invalid_request
    """
    res = api.create_membership({"primary_member_name": "No Plan"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_add_line_qty_below_one(api):
    """PRD §2.6: "required body fields present and correctly typed, such as a qty that is an
    integer of at least 1 ... yielding ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/add_line_qty_below_one_invalid_request
    """
    plan = create_basic_plan()
    product = create_product("P-QTY")
    m = create_active_membership(plan["id"], primary_member_name="Qty Mem")
    txn = get_success_data(api.create_transaction({"membership_id": m["id"]}, CLERK))
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 0}, CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_basic_plan_nonzero_reward_rate(api):
    """PRD §3.1: "Attempting to create a BASIC plan with a nonzero reward_rate_bps, or any
    plan with an out-of-enum tier or a missing required field, is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_basic_plan_with_nonzero_reward_rate_invalid_request
    """
    res = api.create_plan({"tier": "BASIC", "annual_fee_cents": 6000, "reward_rate_bps": 200,
                           "max_household_cards": 1, "addon_fee_cents": 4000}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_card_kind(api):
    """PRD §3.4: "a card_kind outside that pair is rejected with ERR_CARD_KIND_INVALID
    (HTTP 400)."

    Design: Corner/entities/invalid_card_kind_rejected
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="CardKind Mem")
    res = api.create_household_card({"membership_id": m["id"], "cardholder_name": "Bad",
                                     "card_kind": "GOLD"}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_CARD_KIND_INVALID)


def test_product_member_price_above_list(api):
    """PRD §3.1: "a member_price_cents greater than list_price_cents is rejected with
    ERR_INVALID_PRICE (HTTP 400)."

    Design: Corner/entities/product_member_price_above_list_invalid_price
    """
    res = api.create_product({"sku": "P-BADPRICE", "list_price_cents": 5000,
                              "member_price_cents": 8000}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_PRICE)


def test_instant_saving_inverted_window(api):
    """PRD §3.1: "A promotion whose window_end_utc is at or before its window_start_utc is
    rejected with ERR_INVALID_PROMO_WINDOW (HTTP 400)."

    Design: Corner/entities/instant_saving_inverted_window_invalid_promo_window
    """
    product = create_product("P-WINBAD")
    res = api.create_instant_saving({"product_id": product["id"], "kind": "INSTANT_SAVINGS",
                                     "amount_cents": 1000,
                                     "window_start_utc": "2026-06-01T00:00:00Z",
                                     "window_end_utc": "2026-06-01T00:00:00Z"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_PROMO_WINDOW)


def test_duplicate_product_sku(api):
    """PRD §3.1: "Creating a product whose sku already exists is rejected with
    ERR_PRODUCT_SKU_DUPLICATE (HTTP 409)."

    Design: Corner/entities/duplicate_product_sku_rejected
    """
    create_product("P-DUPE")
    res = api.create_product({"sku": "P-DUPE", "list_price_cents": 11000,
                              "member_price_cents": 9000}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PRODUCT_SKU_DUPLICATE)


def test_invalid_pagination_bounds(api):
    """PRD §2.3: "The limit parameter caps how many items are returned; when omitted it
    defaults to 10, with a minimum of 1 and a maximum of 100. ... A limit or offset outside
    its allowed bounds is rejected with ERR_INVALID_PAGINATION (HTTP 400)."

    Design: Corner/entities/invalid_pagination_bounds_rejected
    """
    res = api.list_plans(ADMIN, params={"limit": 1000, "offset": 0})
    validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION)


# --- Defaults ---
def test_signup_auto_renew_defaults_true(api):
    """PRD §3.2: "optionally auto_renew (whether the membership renews automatically at
    period end, default true)."

    Design: Corner/entities/signup_auto_renew_defaults_true
    """
    plan = create_basic_plan()
    res = api.create_membership({"plan_id": plan["id"], "primary_member_name": "Default AR"}, ADMIN)
    data = validate_success(res, 201)
    assert data["auto_renew"] is True


def test_product_reward_eligible_defaults_true(api):
    """PRD §3.1: "a reward_eligible flag (default true) controlling whether spend on the
    product accrues executive reward."

    Design: Corner/entities/product_reward_eligible_defaults_true
    """
    res = api.create_product({"sku": "P-DEF-RE", "list_price_cents": 10000,
                              "member_price_cents": 8000}, ADMIN)
    data = validate_success(res, 201)
    assert data["reward_eligible"] is True


# --- Computed fields ---
def test_line_unit_price_snapshot_member_when_active(api):
    """PRD §3.5: "The line's unit_price_cents is snapshotted at add time: it is
    member_price_cents when the owning membership is ACTIVE, otherwise list_price_cents."

    Design: Corner/entities/line_unit_price_snapshot_member_when_active
    """
    plan = create_basic_plan()
    product = create_product("P-SNAP", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Snap Mem")
    txn = get_success_data(api.create_transaction({"membership_id": m["id"]}, CLERK))
    line = get_success_data(api.add_line(txn["id"], {"product_id": product["id"], "qty": 2}, CLERK))
    assert line["unit_price_cents"] == 8000
    txn = get_success_data(api.get_transaction(txn["id"], CLERK))
    assert txn["gross_cents"] == 16000
    assert txn["net_cents"] == 16000


def test_household_card_count_after_add(api):
    """PRD §3.4: "Adding a card recomputes the membership's household_card_count, which is
    the number of cards in ACTIVE status."
    PRD §3.4: "An INCLUDED card is free, but only while the active-card count is below the
    plan's max_household_cards."

    Design: Corner/entities/household_card_count_computed_after_add
    """
    plan = create_basic_plan(max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="Count Mem")
    card = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"},
        make_member_headers(m["id"])))
    assert card["fee_charged_cents"] == 0
    m2 = get_success_data(api.get_membership(m["id"], make_member_headers(m["id"])))
    assert m2["household_card_count"] == 1


def test_paid_addon_card_fee_charged(api):
    """PRD §3.4: "A PAID_ADDON card always carries fee_charged_cents equal to the plan's
    addon_fee_cents and records a FeeEvent of kind ADDON for that amount."

    Design: Corner/entities/paid_addon_card_fee_charged
    """
    plan = create_basic_plan(addon_fee_cents=4000, max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="Addon Mem")
    hdr = make_member_headers(m["id"])
    get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"}, hdr))
    addon = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Kid", "card_kind": "PAID_ADDON"}, hdr))
    assert addon["fee_charged_cents"] == 4000
    fees = api.list_fee_events(hdr, params={"membership_id": m["id"], "kind": "ADDON"}).json()["data"]
    addon_fees = [f for f in fees if f["kind"] == "ADDON"]
    assert len(addon_fees) == 1
    assert addon_fees[0]["amount_cents"] == 4000


# --- System fields / immutability ---
def test_membership_version_increments_on_renew(api):
    """PRD §3.3: "resets reward_accrued_cents and reward_redeemed_cents to 0 for the new
    term, and increments the membership version by one."

    Design: Corner/entities/membership_version_increments_on_renew
    """
    from test_helpers import set_clock, get_membership_version
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="Ver Mem", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.renew_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    data = validate_success(res, 200)
    # PRD §3.3: renewal "increments the membership version by one." Activation is
    # itself a mutation (§2.4), so assert the +1 delta against the observed version.
    assert data["version"] == ver + 1
    assert data["status"] == "ACTIVE"


def test_plan_has_no_version_field(api):
    """PRD §2.4: "The configuration and audit resources — MembershipPlan, Product,
    InstantSaving, RewardLedgerEntry, and FeeEvent — are not mutation-tracked: they carry
    only id and created_at, and have neither updated_at nor version."

    Design: Corner/entities/plan_is_immutable_no_version_field
    """
    plan = create_basic_plan()
    res = api.get_plan(plan["id"], ADMIN)
    data = validate_success(res, 200)
    assert "version" not in data
    assert "created_at" in data
