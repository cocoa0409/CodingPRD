"""Recipe trees, the recursive allergen union, the cross-contact advisory, and the
recipe-status dependency that gates line addition."""
from test_helpers import (
    ADMIN,
    CROSS_CONTACT_ADVISORY_TEXT,
    INSPECTOR,
    ApiErrorId,
    api_client,
    assert_recipe,
    create_baker,
    create_lot,
    create_recipe,
    create_recipe_component_payload,
    make_baker_headers,
    open_order,
    read_menu_item,
    read_recipe,
    setup_storefront,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_allergen_union_walks_a_depth_three_sub_recipe_tree(api):
    """PRD §3.2: "The result stored in `allergen_union` is the accumulated set,
    deduplicated and sorted ascending as lowercase strings; traversal order affects
    nothing but the walk itself."
    PRD §3.2: "Alongside it, `tree_depth` is 1 plus the greatest depth of any
    sub-recipe subtree beneath the root, or simply 1 when the root has no
    sub-recipe children."
    PRD §3.2: "An allergen that appears *only* in some lot's
    `cross_contact_allergens` therefore never enters `allergen_union`"
    PRD §3.2: "The advisory applies when the operator's `shared_kitchen` is true,
    or when any ingredient lot anywhere in the recipe's transitive closure carries
    a non-empty `cross_contact_allergens` list."

    Design: Corner/calculations/allergen_union_is_a_recursive_union_over_a_depth_three_tree
    """
    baker = create_baker()
    headers = make_baker_headers(baker["id"])
    lot = create_lot(
        baker["id"], lot_code="SPICE-7", allergens=[],
        cross_contact_allergens=["tree_nut"],
    )
    spice = create_recipe(
        baker["id"], name="Spice Blend",
        components=[
            create_recipe_component_payload(
                component_name="sesame and cinnamon", quantity_grams=20,
                declared_allergens=["sesame"], ingredient_lot_id=lot["id"],
            )
        ],
    )
    dough = create_recipe(
        baker["id"], name="House Dough",
        components=[
            create_recipe_component_payload(
                component_name="butter", quantity_grams=200,
                declared_allergens=["milk"],
            ),
            {
                "component_name": "spice blend portion",
                "quantity_grams": 20,
                "sub_recipe_id": spice["id"],
            },
        ],
    )
    cookie_recipe = create_recipe(
        baker["id"], name="Brown Butter Cookie", publish=False,
        components=[
            create_recipe_component_payload(
                component_name="flour", quantity_grams=500,
                declared_allergens=["wheat"],
            ),
            {
                "component_name": "dough portion",
                "quantity_grams": 400,
                "sub_recipe_id": dough["id"],
            },
        ],
    )

    published = validate_success(api.publish_recipe(cookie_recipe["id"], headers))
    assert_recipe(published)
    assert published["tree_depth"] == 3
    assert published["allergen_union"] == ["milk", "sesame", "wheat"]
    assert "tree_nut" not in published["allergen_union"]
    assert published["cross_contact_advisory"] == CROSS_CONTACT_ADVISORY_TEXT

    profile = validate_success(
        api.get_allergen_profile(cookie_recipe["id"], INSPECTOR)
    )
    assert profile["allergen_union"] == ["milk", "sesame", "wheat"]
    assert profile["tree_depth"] == 3
    assert profile["published_version"] == 1


def test_component_referencing_a_recalled_lot_is_refused(api):
    """PRD §2.6: "Rung 27: no recipe component in the referenced recipe's transitive
    closure has `recalled_component` set, and no referenced ingredient lot has
    `lot_status` `RECALLED`, otherwise `ERR_LOT_RECALLED` (409); this applies to
    recipe publication, component attachment, line addition, batch advancement, and
    label issuance."
    PRD §3.10: "Recalling a **never-released** lot has no downstream product, so
    the cascade terminates early: there are no batches, no lines, no orders, and no
    labels to touch."

    Design: Corner/validations/component_referencing_a_recalled_lot_is_rejected
    """
    baker = create_baker()
    headers = make_baker_headers(baker["id"])
    lot = create_lot(baker["id"], release=False, lot_code="BAD-1", allergens=["wheat"])
    recipe = create_recipe(baker["id"], publish=False, components=[])

    recalled = validate_success(
        api.recall_ingredient_lot(
            lot["id"],
            {"recall_reason": "supplier withdrew the lot before release"},
            ADMIN,
        )
    )
    assert recalled["lot_status"] == "RECALLED"

    rejected = api.add_recipe_component(
        recipe["id"],
        {
            "component_name": "recalled flour",
            "quantity_grams": 500,
            "declared_allergens": ["wheat"],
            "ingredient_lot_id": lot["id"],
        },
        headers,
    )
    validate_error(rejected, ApiErrorId.ERR_LOT_RECALLED)

    components, comp_meta = validate_paginated(
        api.list_recipe_components(headers, {"recipe_id": recipe["id"]})
    )
    assert comp_meta["total_count"] == 0
    _, batch_meta = validate_paginated(
        api.list_batches(headers, {"recipe_id": recipe["id"]})
    )
    assert batch_meta["total_count"] == 0


def test_a_recipe_naming_itself_as_a_sub_recipe_is_a_cycle(api):
    """PRD §2.6: "Rung 28: the recipe's component and sub-recipe closure is acyclic
    and its `tree_depth` is at most 5, otherwise `ERR_RECIPE_CYCLE_DETECTED` (422);
    this applies to component attachment and recipe publication."
    PRD §3.2: "a recipe reachable from itself through any chain of sub-recipe links
    is a cycle."

    Design: Corner/validations/self_referential_sub_recipe_is_rejected_as_a_cycle
    """
    baker = create_baker()
    headers = make_baker_headers(baker["id"])
    recipe = create_recipe(
        baker["id"], name="Self Referential Dough", publish=False, components=[]
    )

    rejected = api.add_recipe_component(
        recipe["id"],
        {
            "component_name": "itself",
            "quantity_grams": 10,
            "sub_recipe_id": recipe["id"],
        },
        headers,
    )
    validate_error(rejected, ApiErrorId.ERR_RECIPE_CYCLE_DETECTED)

    _, meta = validate_paginated(
        api.list_recipe_components(headers, {"recipe_id": recipe["id"]})
    )
    assert meta["total_count"] == 0
    after = read_recipe(recipe["id"], headers)
    assert after["tree_depth"] == 1
    assert after["recipe_status"] == "DRAFT"


def test_line_add_is_blocked_while_the_backing_recipe_is_revising(api):
    """PRD §2.6: "Rung 26: the recipe backing every referenced menu item has
    `recipe_status` `PUBLISHED`, otherwise `ERR_RECIPE_NOT_PUBLISHED` (409); this
    applies to line addition, menu-item listing-status changes, and label issuance."
    PRD §3.2: "A published recipe may be moved to `REVISING` at any time (a plain
    posture change that bumps the `version`)"

    Design: Difficulty/cross_entity_state_dependency/order_line_add_blocked_by_recipe_in_revising
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    revising = validate_success(
        api.set_recipe_lifecycle(s.recipe_id, {"to_status": "REVISING"}, s.bh)
    )
    assert revising["recipe_status"] == "REVISING"
    assert read_menu_item(s.cookie_id, s.bh)["listing_status"] == "LISTED"

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 13,
            "expected_offer_window_version": s.window["version"],
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_RECIPE_NOT_PUBLISHED)

    _, meta = validate_paginated(
        api.list_order_lines(s.ch, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    window = validate_success(api.get_offer_window(s.window_id, s.ch))
    assert window["version"] == s.window["version"], (
        "the rejected line add must not have bumped the window's version"
    )


def test_line_add_succeeds_once_the_recipe_is_republished(api):
    """PRD §3.2: "the publish increments `published_version` by one, recomputes
    `allergen_union`, `tree_depth`, and `cross_contact_advisory`, recomputes
    `allergen_summary` on every menu item whose `recipe_id` is this recipe, and
    bumps the recipe's `version`."
    PRD §3.3: "with a unit price of 450 and a dozen price of 4600, twelve units
    cost 5400 while thirteen units cost 4600"

    Design: Difficulty/cross_entity_state_dependency/order_line_add_blocked_by_recipe_in_revising
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    validate_success(
        api.set_recipe_lifecycle(s.recipe_id, {"to_status": "REVISING"}, s.bh)
    )
    validate_error(
        api.add_order_line(
            order["id"],
            {
                "menu_item_id": s.cookie_id,
                "quantity": 13,
                "expected_offer_window_version": s.window["version"],
            },
            s.ch,
        ),
        ApiErrorId.ERR_RECIPE_NOT_PUBLISHED,
    )

    republished = validate_success(api.publish_recipe(s.recipe_id, s.bh))
    assert republished["published_version"] == 2
    assert republished["recipe_status"] == "PUBLISHED"

    line = validate_success(
        api.add_order_line(
            order["id"],
            {
                "menu_item_id": s.cookie_id,
                "quantity": 13,
                "expected_offer_window_version": s.window["version"],
            },
            s.ch,
        ),
        201,
    )
    assert line["line_status"] == "PENDING"
    assert line["line_total_cents"] == 4600
