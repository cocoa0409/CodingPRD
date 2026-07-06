"""Authentication/grading and the publish gate.

Covers the listable flag, idempotent authenticate, the grade gate, and the two
cross-entity publish/direct-buy state preconditions (PRD §3.3, §3.4, §3.5).
"""
from test_helpers import (
    validate_success, validate_error,
    create_authenticate_payload,
    make_seller_headers,
    # fixtures
    create_seller, create_category_policy, create_item, authenticate_item,
    create_listing, setup_draft_listing, get_item, get_listing,
    TEST_USERS,
)

_AUTH = TEST_USERS["authenticator_headers"]


def test_authenticate_authentic_grade_a_sets_listable_true(api):
    """PRD §3.3: "When the `verdict` is `AUTHENTIC`, the item advances to `AUTHENTICATED`;
    the server records `authenticity_verdict`, `condition_grade`, `authenticator_id`, and
    `authenticated_at`, and recomputes the derived `listable` flag."
    PRD §3.3: "The `listable` flag is `true` only when two conditions both hold: the
    `authenticity_verdict` is `AUTHENTIC`, and the item's `condition_grade` is no worse
    than its category's `listable_min_condition_grade`."

    Design: Corner/entities/authenticate_sets_computed_listable_true
    """
    create_category_policy(category="HANDBAGS", listable_min_condition_grade="C")
    seller = create_seller()
    item = create_item(seller["id"], category="HANDBAGS")
    res = api.authenticate_item(item["id"], create_authenticate_payload("AUTHENTIC", "A"), _AUTH)
    graded = validate_success(res, 200)
    assert graded["status"] == "AUTHENTICATED", graded["status"]
    assert graded["authenticity_verdict"] == "AUTHENTIC", graded["authenticity_verdict"]
    assert graded["listable"] is True, graded["listable"]


def test_authenticate_already_authenticated_returns_invalid_state(api):
    """PRD §3.3: "The authenticate action requires the item to be in `RECEIVED` status;
    attempting it on an item in any other state is rejected with `ERR_ITEM_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/authenticate_already_authenticated_returns_invalid_state
    """
    create_category_policy(category="HANDBAGS")
    seller = create_seller()
    item = create_item(seller["id"], category="HANDBAGS")
    authenticate_item(item["id"], "AUTHENTIC", "A")
    res = api.authenticate_item(item["id"], create_authenticate_payload("AUTHENTIC", "B"), _AUTH)
    validate_error(res, "ERR_ITEM_INVALID_STATE", expected_status=409)


def test_publish_grade_below_min_returns_not_listable(api):
    """PRD §3.4: "Finally, the item must be listable — its `authenticity_verdict` must be
    `AUTHENTIC` and its `condition_grade` no worse than the category's
    `listable_min_condition_grade` — or the attempt is rejected with
    `ERR_ITEM_GRADE_NOT_LISTABLE` (HTTP 422)."
    PRD §3.3: "an authentic-but-below-threshold item still becomes `AUTHENTICATED` (with
    `listable` computed as `false`), and the grade eligibility gate is enforced later, at
    publish."

    Design: Corner/validations/publish_grade_below_min_returns_not_listable
    """
    ctx = setup_draft_listing(list_price_cents=100000, category="HANDBAGS",
                              policy_overrides={"listable_min_condition_grade": "C"},
                              authenticate=True, grade="D")
    item = get_item(ctx["item_id"])
    assert item["listable"] is False, item["listable"]
    res = api.publish_listing(ctx["listing_id"], make_seller_headers(ctx["seller_id"]))
    validate_error(res, "ERR_ITEM_GRADE_NOT_LISTABLE", expected_status=422)


# --- Depth: publish requires the referenced item AUTHENTICATED ---------------
def test_publish_unauthenticated_item_rejected(api):
    """PRD §3.4: "The referenced item must be in `AUTHENTICATED` status, or the attempt is
    rejected with `ERR_ITEM_NOT_AUTHENTICATED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_item_authenticated
    """
    # DROP_OFF item stays RECEIVED (never authenticated); a DRAFT listing exists for it.
    ctx = setup_draft_listing(list_price_cents=90000, category="HANDBAGS", authenticate=False)
    res = api.publish_listing(ctx["listing_id"], make_seller_headers(ctx["seller_id"]))
    validate_error(res, "ERR_ITEM_NOT_AUTHENTICATED", expected_status=409)


def test_publish_unauthenticated_item_leaves_listing_draft(api):
    """PRD §3.4: "Publishing takes the listing from `DRAFT` to `ACTIVE` and locks in the
    economics of any future sale."
    PRD §3.4: "The referenced item must be in `AUTHENTICATED` status, or the attempt is
    rejected with `ERR_ITEM_NOT_AUTHENTICATED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_item_authenticated
    """
    ctx = setup_draft_listing(list_price_cents=90000, category="HANDBAGS", authenticate=False)
    api.publish_listing(ctx["listing_id"], make_seller_headers(ctx["seller_id"]))
    listing = get_listing(ctx["listing_id"])
    assert listing["status"] == "DRAFT", listing["status"]


# --- Depth: direct buy requires the listing ACTIVE ---------------------------
def test_direct_buy_draft_listing_rejected(api):
    """PRD §3.5: "A `Buyer` buys outright by referencing the `listing_id` and their own
    `buyer_id`. The listing must currently be `ACTIVE`, or the purchase is rejected with
    `ERR_LISTING_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/direct_buy_requires_listing_active
    """
    from test_helpers import create_buyer, create_sale_payload, make_buyer_headers
    # Item authenticated (grade A) but its listing was never published — still DRAFT.
    ctx = setup_draft_listing(list_price_cents=90000, category="HANDBAGS", authenticate=True, grade="A")
    buyer = create_buyer()
    res = api.create_sale(create_sale_payload(ctx["listing_id"], buyer["id"]),
                          make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_LISTING_NOT_ACTIVE", expected_status=409)


def test_direct_buy_draft_listing_leaves_listing_draft(api):
    """PRD §3.5: "A successful direct buy creates a `Sale` whose `sale_channel` is `DIRECT`
    and whose `sale_price_cents` is the listing's `list_price_cents`, with the sale's
    `buyer_id` taken from the acting buyer. Creating the sale drives the listing from
    `ACTIVE` to `SOLD`,"
    PRD §3.5: "The listing must currently be `ACTIVE`, or the purchase is rejected with
    `ERR_LISTING_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/direct_buy_requires_listing_active
    """
    from test_helpers import create_buyer, create_sale_payload, make_buyer_headers
    ctx = setup_draft_listing(list_price_cents=90000, category="HANDBAGS", authenticate=True, grade="A")
    buyer = create_buyer()
    api.create_sale(create_sale_payload(ctx["listing_id"], buyer["id"]), make_buyer_headers(buyer["id"]))
    listing = get_listing(ctx["listing_id"])
    assert listing["status"] == "DRAFT", listing["status"]
