"""Cold-pack shipping: coolant computation, the order-PAID dispatch gate, the transit-window
delivery/spoilage split, and the recipe curation transitions."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    set_clock,
    register_account,
    create_published_recipe,
    create_draft_recipe,
    setup_paid_order,
    setup_dispatched_shipment,
    get_shipment_for_order,
    update_shipment_payload,
    ApiErrorId,
)

VET = TEST_USERS["nutrition_vet_headers"]
OPS = TEST_USERS["fulfillment_ops_headers"]


def test_dispatch_requires_order_paid_succeeds_when_paid(api):
    """PRD §3.9: "Dispatch requires the shipment be `PENDING` (otherwise `ERR_SHIPMENT_NOT_PENDING`),
    requires the parent order be `PAID` (only paid food ships, otherwise `ERR_ORDER_NOT_PAID`)".

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_order_paid
    """
    account, pet, recipe, sub, paid = setup_paid_order(
        "ce-1@x.com", sub_overrides={"cadence_days": 28}
    )
    assert paid["status"] == "PAID", paid["status"]
    shipment = get_shipment_for_order(paid["id"])
    dispatched = validate_success(api.dispatch_shipment(shipment["id"], OPS), 200)
    assert dispatched["status"] == "DISPATCHED", dispatched["status"]


def test_deliver_after_transit_window_spoils_and_mints_make_good(api):
    """PRD §3.9: "If the elapsed days exceed `transit_days`, the food has spoiled in transit: the
    shipment transitions `DISPATCHED → SPOILED`, and a make-good compensation row is minted — a
    `MAKE_GOOD` referral-credit row created `GRANTED` to the owning account".

    Design: Difficulty/resource_temporal_overlap/shipment_transit_window_overlap_spoilage
    """
    account, sub, paid, shipment = setup_dispatched_shipment(
        "to-2@x.com", clock="2026-01-01T00:00:00Z"
    )
    # transit_days default 2; advance 4 days -> overrun -> SPOILED.
    set_clock("2026-01-05T00:00:00Z")
    delivered = validate_success(api.deliver_shipment(shipment["id"], OPS), 200)
    assert delivered["status"] == "SPOILED", delivered["status"]

    data, _ = _credits(api, referred_account_id=account["id"])
    make_goods = [c for c in data if c["reason"] == "MAKE_GOOD" and c["status"] == "GRANTED"]
    assert make_goods, "a MAKE_GOOD GRANTED referral credit must exist for the spoiled order"


def test_deliver_within_window_marks_delivered(api):
    """PRD §3.9: "If the elapsed days are within the transit window (at most `transit_days`), the
    shipment transitions `DISPATCHED → DELIVERED`."

    Design: Corner/state_machines/shipment_deliver_within_window_marks_delivered
    """
    account, sub, paid, shipment = setup_dispatched_shipment(
        "sm-6@x.com", clock="2026-01-01T00:00:00Z"
    )
    # transit_days default 2; advance only 1 day -> within window -> DELIVERED.
    set_clock("2026-01-02T00:00:00Z")
    delivered = validate_success(api.deliver_shipment(shipment["id"], OPS), 200)
    assert delivered["status"] == "DELIVERED", delivered["status"]


def test_coolant_packs_from_mass_and_transit(api):
    """PRD §3.9: "Take a mass component equal to `food_grams` divided by 4000 grams per pack,
    rounded up to the next whole number ... Take a day component equal to the transit days beyond a
    free window of 2 days ... The `coolant_packs` count is the larger of a minimum of 1 and the sum
    of the mass and day components."

    Design: Corner/calculations/coolant_packs_mass_and_transit_tier
    """
    account, pet, recipe, sub, paid = setup_paid_order(
        "ca-1@x.com", sub_overrides={"cadence_days": 28}
    )
    # food_grams 11116 -> mass_units ceil(11116/4000) == 3; transit_days 4 -> day_units 2 -> 5.
    shipment = get_shipment_for_order(paid["id"])
    patched = validate_success(api.update_shipment(shipment["id"], update_shipment_payload(4), OPS), 200)
    assert patched["coolant_packs"] == 5, patched["coolant_packs"]


def test_coolant_recomputed_on_transit_bump_then_dispatch_succeeds(api):
    """PRD §3.9: "A `FulfillmentOps` operator may update `transit_days` on a `PENDING` shipment,
    which recomputes `coolant_packs`."
    PRD §3.9: "requires that the stored `coolant_packs` be at least the amount the coolant formula
    requires for the shipment's `transit_days` ... On success the shipment transitions
    `PENDING → DISPATCHED`".

    Design: Corner/errors/coolant_packs_recomputed_on_transit_bump_then_dispatch_succeeds
    """
    account, pet, recipe, sub, paid = setup_paid_order(
        "er-3@x.com", sub_overrides={"cadence_days": 28}
    )
    shipment = get_shipment_for_order(paid["id"])
    # transit_days 5 -> mass 3 + day_units 3 == 6.
    patched = validate_success(api.update_shipment(shipment["id"], update_shipment_payload(5), OPS), 200)
    assert patched["coolant_packs"] == 6, patched["coolant_packs"]
    dispatched = validate_success(api.dispatch_shipment(shipment["id"], OPS), 200)
    assert dispatched["status"] == "DISPATCHED", dispatched["status"]


def test_publish_already_published_recipe_rejected(api):
    """PRD §3.2: "Publishing requires the recipe currently be in `DRAFT`, otherwise the request is
    rejected with `ERR_RECIPE_NOT_DRAFT`".

    Design: Corner/state_machines/publish_already_published_recipe_returns_not_draft
    """
    set_clock("2026-01-01T00:00:00Z")
    recipe = create_published_recipe(
        name="Turkey", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    res = api.publish_recipe(recipe["id"], VET)
    validate_error(res, ApiErrorId.ERR_RECIPE_NOT_DRAFT.value)


def test_retire_draft_recipe_rejected(api):
    """PRD §3.2: "Retiring requires the recipe be `PUBLISHED`, otherwise `ERR_RECIPE_NOT_PUBLISHED`".

    Design: Corner/state_machines/retire_draft_recipe_returns_not_published
    """
    set_clock("2026-01-01T00:00:00Z")
    recipe = create_draft_recipe(
        name="Draft", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    res = api.retire_recipe(recipe["id"], VET)
    validate_error(res, ApiErrorId.ERR_RECIPE_NOT_PUBLISHED.value)


def _credits(api, **params):
    from test_helpers import TEST_USERS as _TU

    resp = api.list_referral_credits(_TU["billing_admin_headers"], params=params)
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
