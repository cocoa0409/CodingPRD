"""Client/product/ingredient/recipe registration basics, input validation,
pagination envelope, and the user-context header check."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_client,
    assert_iso8601_three_fractional,
    create_client,
    create_client_payload,
    create_ingredient,
    create_ingredient_payload,
    create_product,
    create_product_payload,
    create_recipe_payload,
    is_valid_uuid,
    make_client_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestRegistrationBasics:
    def test_client_creation_returns_system_fields(self, api):
        """PRD §2.4: "Every resource type in the system — clients, products,
        ingredients, recipes, lab analyses, nutrient panels, RACC assignments,
        label versions, claim assessments, market variants, format checks,
        artwork audits, and audit findings — carries a uniform set of
        system-managed fields: an `id`, which is a server-minted UUID with no
        type prefix; a `created_at` timestamp in ISO 8601 UTC form with three
        fractional digits; an `updated_at` timestamp of the same form,
        refreshed on every mutation; and a `version` integer that increments
        by one on every mutation."
        PRD §3.1: "A `PlatformAdmin` onboards each food manufacturer as a
        **Client**, supplying a display `name` and the client's
        `home_market_code`."

        Design: Corner/entities/entity_client_creation_returns_system_fields
        """
        resp = api.create_client(
            create_client_payload(name="Acme Foods", home_market_code="US_FDA"),
            ADMIN,
        )
        client = validate_success(resp, 201)
        assert_client(client)
        assert is_valid_uuid(client["id"]), "id is a server-minted UUID"
        assert_iso8601_three_fractional(client["created_at"], "created_at")
        assert client["name"] == "Acme Foods"
        assert client["home_market_code"] == "US_FDA"

    def test_product_get_not_found_returns_404(self, api):
        """PRD §2.8: "Path identifiers are resolved left to right, and the
        request is rejected with `ERR_NOT_FOUND` at the first identifier that
        does not resolve; the same error covers body-supplied references such
        as `racc_assignment_id`, `product_id`, or `label_version_id` that do
        not exist, and any recipe line whose `ingredient_id` does not exist
        within the client's ingredient scope."

        Design: Corner/entities/entity_product_get_not_found_returns_404
        """
        resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_recipe_create_missing_required_lines(self, api):
        """PRD §3.2: "Every line quantity must be positive, the recipe needs at
        least one line, and the ingredient references must be distinct;
        violations of these shape rules are rejected with
        `ERR_INVALID_REQUEST`, while a line referencing an ingredient that
        does not exist in the client's catalogue is rejected with
        `ERR_NOT_FOUND`."
        PRD §2.8: "Only after existence is established is the body's
        well-formedness checked — required fields present, enum members valid,
        numbers positive where required, `yield_factor` inside its allowed
        band, recipe lines non-empty with distinct ingredient references —
        failing which the request is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_recipe_create_missing_required_lines
        """
        client = create_client()
        product = create_product(client)
        payload = create_recipe_payload([{"ingredient_id": NON_EXISTENT_UUID,
                                          "quantity_g": 100}])
        del payload["lines"]
        resp = api.create_recipe(product["id"], payload,
                                 make_client_rep_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_product_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "Only after existence is established is the body's
        well-formedness checked — required fields present, enum members valid,
        numbers positive where required, `yield_factor` inside its allowed
        band, recipe lines non-empty with distinct ingredient references —
        failing which the request is rejected with `ERR_INVALID_REQUEST`."
        PRD §3.1: "Once onboarded, a `ClientRep` of that client registers each
        **Product** with a `name`, a `product_category` drawn from
        `BAKED_GOOD`, `BEVERAGE`, `CEREAL`, `SNACK`, `DAIRY`, `SAUCE`,
        `CONFECTION`, or `FROZEN_DESSERT`, and the physical facts that later
        drive compliance math: `net_weight_g` for the net contents,
        `total_surface_area_sq_in` for the total package surface, and
        `pdp_area_sq_in` for the principal display panel."

        Design: Corner/entities/entity_product_create_invalid_enum_returns_invalid_request
        """
        client = create_client()
        resp = api.create_product(
            client["id"],
            create_product_payload(name="Pastry", product_category="PASTRIES",
                                   include_household=False),
            make_client_rep_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_defaults_applied_on_create(self, api):
        """PRD §3.2: "Each ingredient carries a declaration `name`, an
        `allergen_tags` list that defaults to empty and may draw from `MILK`,
        `EGGS`, `FISH`, `SHELLFISH`, `TREE_NUTS`, `PEANUTS`, `WHEAT`,
        `SOYBEAN`, and `SESAME`, and a nine-part database nutrient profile
        expressed per 100 grams: `kcal_per_100g`, `fat_g_per_100g`,
        `satfat_g_per_100g`, `chol_mg_per_100g`, `sodium_mg_per_100g`,
        `carb_g_per_100g`, `fiber_g_per_100g`, `sugar_g_per_100g`, and
        `protein_g_per_100g`."
        PRD §3.2: "The yield factor — finished mass divided by raw mass —
        defaults to 1.0 and must be greater than 0 and at most 1.2."
        PRD §3.2: "A new recipe begins life in `DRAFT` status."

        Design: Corner/entities/entity_defaults_applied_on_create
        """
        client = create_client()
        product = create_product(client, include_household=False)
        ingredient = create_ingredient(client, name="Wheat Flour")
        assert ingredient["allergen_tags"] == [], (
            "allergen_tags defaults to empty when omitted"
        )

        payload = create_recipe_payload(
            [{"ingredient_id": ingredient["id"], "quantity_g": 100}])
        assert "yield_factor" not in payload, "factory omits yield_factor"
        recipe = validate_success(
            api.create_recipe(product["id"], payload,
                              make_client_rep_headers(client["id"])),
            201,
        )
        assert recipe["yield_factor"] == 1.0, "yield_factor defaults to 1.0"
        assert recipe["status"] == "DRAFT", "A new recipe begins life in DRAFT status"


class TestUserContextHeader:
    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request with either header missing or malformed, or
        naming a role the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/val_missing_auth_header_unauthenticated
        """
        resp = api.create_client(
            create_client_payload(name="NoHdr", home_market_code="US_FDA"),
            {},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)


class TestListingPagination:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints paginate through two query parameters.
        `limit` caps the number of items returned; it defaults to 10, with a
        minimum of 1 and a maximum of 100. `offset` specifies how many items
        to skip and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/endpoints/ep_list_pagination_envelope
        """
        client = create_client()
        p1 = create_product(client, name="Cookie", include_household=False)
        p2 = create_product(client, name="Cracker", product_category="SNACK",
                            net_weight_g=30, total_surface_area_sq_in=20.0,
                            include_household=False)

        resp1 = api.list_products(client["id"], ADMIN,
                                  params={"limit": 1, "offset": 0})
        assert resp1.json()["response_type"] == "array", (
            "a list of resources uses response_type array"
        )
        page1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 2
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert len(page1) == 1
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_products(client["id"], ADMIN,
                              params={"limit": 1, "offset": 1}))
        assert meta2["total_count"] == 2
        assert len(page2) == 1
        assert meta2["has_more"] is False

        assert {page1[0]["id"], page2[0]["id"]} == {p1["id"], p2["id"]}, (
            "the two pages partition the client's products"
        )
