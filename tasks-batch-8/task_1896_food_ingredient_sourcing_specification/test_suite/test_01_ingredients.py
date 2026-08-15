"""Ingredient creation, listing, lifecycle guards, and platform-level basics."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_parameter,
    approve_spec,
    assert_ingredient,
    assert_price_observation,
    create_active_source,
    create_draft_spec,
    create_ingredient_entity,
    create_ingredient_payload,
    create_ingredient_with_effective_spec,
    create_price_index_payload,
    create_provisional_source,
    create_qualified_supplier,
    create_substitution_request,
    fresh_ingredient,
    make_spec_effective,
    submit_spec,
    validate_error,
    validate_paginated,
)


class TestIngredientCreation:
    def test_ingredient_creation_defaults_and_envelope(self, api, procurement_manager_headers):
        """PRD §3.1: "The ingredient is born with `status` set to `DRAFT`. Its
        `active_spec_id` is null until a spec becomes `EFFECTIVE`, and its
        `current_dual_source_breach` flag starts at false."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and meta carries api_request_id.

        Design: Corner/entities/ingredient_creation_defaults_and_envelope
        """
        resp = api.create_ingredient(
            create_ingredient_payload(
                ingredient_code="ENZ-D", name="Default Enzyme",
                allergen_profile=["NONE"], requires_dual_source=False,
            ),
            procurement_manager_headers,
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert body.get("response_type") == "object", "creation returns a single object"
        assert isinstance(body.get("meta", {}).get("api_request_id"), str) and body["meta"]["api_request_id"], (
            "meta.api_request_id must be present"
        )
        data = body["data"]
        assert_ingredient(data)
        assert data["status"] == "DRAFT"
        assert data["active_spec_id"] is None
        assert data["current_dual_source_breach"] is False

    def test_ingredient_missing_required_field_returns_invalid_request(self, api, procurement_manager_headers):
        """PRD §3.1: "A `ProcurementManager` introduces a new ingredient by posting
        its `ingredient_code`, display `name`, an `allergen_profile` ... and a
        `requires_dual_source` boolean." — omitting the business-unique
        `ingredient_code` leaves the request malformed; the catalogue's
        request-shape error is ERR_INVALID_REQUEST (HTTP 400, PRD §5).

        Design: Corner/entities/ingredient_missing_required_field_returns_invalid_request
        """
        payload = create_ingredient_payload(ingredient_code="ENZ-MISS")
        del payload["ingredient_code"]
        resp = api.create_ingredient(payload, procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_ingredient_duplicate_code_rejected(self, api, procurement_manager_headers):
        """PRD §2.10: "`ingredient_code` is unique across all ingredients. ... Any
        collision is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/ingredient_duplicate_code_rejected
        """
        create_ingredient_entity("ENZ-DUP", name="First")
        resp = api.create_ingredient(
            create_ingredient_payload(
                ingredient_code="ENZ-DUP", name="Second",
                allergen_profile=["SOY"], requires_dual_source=True,
            ),
            procurement_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_ingredient_invalid_allergen_enum_rejected(self, api, procurement_manager_headers):
        """PRD §3.1: "an `allergen_profile` drawn from the fixed allergen tag set
        (`MILK`, `EGG`, `FISH`, `SHELLFISH`, `TREE_NUT`, `PEANUT`, `WHEAT`, `SOY`,
        `SESAME`, `NONE`)" — GLUTEN is outside the fixed set; the request-shape
        error is ERR_INVALID_REQUEST (PRD §2.12 "valid enum values", PRD §5).

        Design: Corner/entities/ingredient_invalid_allergen_enum_rejected
        """
        resp = api.create_ingredient(
            create_ingredient_payload(
                ingredient_code="ENZ-BAD", name="Bad Allergen",
                allergen_profile=["GLUTEN"], requires_dual_source=False,
            ),
            procurement_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_ingredient_get_not_found(self, api, procurement_manager_headers):
        """PRD §2.8: "The first identifier that does not resolve is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/ingredient_get_not_found
        """
        resp = api.get_ingredient(NON_EXISTENT_UUID, procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_ingredient_list_pagination_defaults(self, api, procurement_manager_headers, quality_manager_headers):
        """PRD §2.3: "The default value of `limit` is 10; the minimum accepted value
        is 1 and the maximum is 100." and "List responses always include the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more` inside
        the `meta` envelope."

        Design: Corner/entities/ingredient_list_pagination_defaults
        """
        for i in range(1, 13):
            create_ingredient_entity(f"PAG-{i:02d}", name=f"P{i}")
        resp = api.list_ingredients(quality_manager_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 10, f"default page size is 10, got {len(data)}"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_price_index_observation_immutable_no_version(self, api, platform_admin_headers):
        """PRD §2.4: "`PriceIndexObservation` is an immutable observation log and
        carries only `id` and `created_at` — `updated_at` and `version` are absent
        on that entity and no endpoint mutates it."

        Design: Corner/entities/price_index_observation_immutable_no_version
        """
        resp = api.create_price_index_observation(
            create_price_index_payload(
                index_name="WHEY-SPOT", observed_at="2026-07-15T00:00:00Z", index_value=210.5,
            ),
            platform_admin_headers,
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text[:300]}"
        assert_price_observation(resp.json()["data"])


class TestIngredientLifecycle:
    def test_active_spec_id_computed_field_tracks_effective_spec(self, api, procurement_manager_headers):
        """PRD §3.1: "Its `active_spec_id` is null until a spec becomes `EFFECTIVE`"
        and PRD §3.2: "the ingredient's `active_spec_id` is updated to the newly
        effective spec".

        Design: Corner/entities/active_spec_id_computed_field_tracks_effective_spec
        """
        ingredient = create_ingredient_entity("ENZ-CMP")
        spec = create_draft_spec(ingredient["id"])
        add_parameter(ingredient["id"], spec["id"])
        submit_spec(ingredient["id"], spec["id"])
        approve_spec(ingredient["id"], spec["id"])

        before = fresh_ingredient(ingredient["id"])
        assert before["active_spec_id"] is None, "no EFFECTIVE spec yet: active_spec_id must be null"

        make_spec_effective(ingredient["id"], spec["id"])
        after = fresh_ingredient(ingredient["id"])
        assert after["active_spec_id"] == spec["id"], (
            f"active_spec_id must track the EFFECTIVE spec: expected {spec['id']}, got {after['active_spec_id']}"
        )

    def test_ingredient_activate_without_effective_spec_blocked(self, api, procurement_manager_headers):
        """PRD §3.1: "The activation is rejected with `ERR_INVALID_STATE` if the
        ingredient is not in `DRAFT`, and with `ERR_NO_EFFECTIVE_SPEC` if no spec
        of this ingredient is currently `EFFECTIVE`."

        Design: Corner/validations/ingredient_activate_without_effective_spec_blocked
        """
        ingredient = create_ingredient_entity("ENZ-NES")
        create_draft_spec(ingredient["id"])  # stays DRAFT — never EFFECTIVE
        resp = api.activate_ingredient(ingredient["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_SPEC)

    def test_discontinue_blocked_by_active_source(self, api, procurement_manager_headers):
        """PRD §3.1: "It is rejected with `ERR_INVALID_STATE` if the ingredient is
        not `ACTIVE`, with `ERR_ACTIVE_SOURCES_EXIST` if any approved source of the
        ingredient is in `PROVISIONAL` or `ACTIVE` status, and with
        `ERR_OPEN_SUBSTITUTIONS_EXIST` if any substitution request of the ingredient
        is in `REQUESTED`, `IMPACT_ASSESSED`, `PENDING_REGULATORY`, or `APPROVED`
        status."

        Design: Corner/errors/discontinue_blocked_by_active_source
        """
        ingredient, spec = create_ingredient_with_effective_spec("ENZ-DSC")
        api.activate_ingredient(ingredient["id"], procurement_manager_headers)
        supplier = create_qualified_supplier("SUP-DSC")
        create_active_source(ingredient["id"], supplier["id"], spec["id"])

        resp = api.discontinue_ingredient(ingredient["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_SOURCES_EXIST)

    def test_discontinue_blocked_by_open_substitution(self, api, procurement_manager_headers):
        """PRD §3.1: "It is rejected with `ERR_INVALID_STATE` if the ingredient is
        not `ACTIVE`, with `ERR_ACTIVE_SOURCES_EXIST` if any approved source of the
        ingredient is in `PROVISIONAL` or `ACTIVE` status, and with
        `ERR_OPEN_SUBSTITUTIONS_EXIST` if any substitution request of the ingredient
        is in `REQUESTED`, `IMPACT_ASSESSED`, `PENDING_REGULATORY`, or `APPROVED`
        status."

        Design: Corner/errors/discontinue_blocked_by_open_substitution
        """
        ingredient, spec = create_ingredient_with_effective_spec("ENZ-OSB")
        api.activate_ingredient(ingredient["id"], procurement_manager_headers)
        sup_a = create_qualified_supplier("SUP-OA")
        sup_b = create_qualified_supplier("SUP-OB")
        src_a = create_provisional_source(ingredient["id"], sup_a["id"], spec["id"])
        src_b = create_provisional_source(ingredient["id"], sup_b["id"], spec["id"])
        # Substitution request left in REQUESTED (never assessed).
        create_substitution_request(ingredient["id"], src_a["id"], src_b["id"])
        # Both sources REVOKED so the active-source guard passes and the
        # open-substitution guard is the one that fires.
        api.revoke_approved_source(ingredient["id"], src_a["id"], procurement_manager_headers)
        api.revoke_approved_source(ingredient["id"], src_b["id"], procurement_manager_headers)

        resp = api.discontinue_ingredient(ingredient["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_SUBSTITUTIONS_EXIST)

    def test_fk_reverse_reachability_lists_children(self, api, procurement_manager_headers):
        """PRD §3.2: "The new spec is born in `DRAFT` status with `ingredient_id`
        pointing at the parent ingredient" — GET /sourcing/ingredients/{id}/specs
        returns exactly the specs created under that ingredient.

        Design: Corner/endpoints/fk_reverse_reachability_lists_children
        """
        ingredient = create_ingredient_entity("FK-1")
        spec1 = create_draft_spec(ingredient["id"], label="v1")
        spec2 = create_draft_spec(ingredient["id"], label="v2", version_note="second spec version")
        data, meta = validate_paginated(api.list_specs(ingredient["id"], procurement_manager_headers))
        assert meta["total_count"] == 2
        ids = {row["id"] for row in data}
        assert ids == {spec1["id"], spec2["id"]}
        for row in data:
            assert row["ingredient_id"] == ingredient["id"]


class TestPlatformAccess:
    def test_error_missing_auth_header(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or empty, the request is
        rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 400)."

        Design: Corner/errors/error_missing_auth_header
        """
        resp = api.create_ingredient(
            create_ingredient_payload(ingredient_code="NOAUTH", name="NoAuth"),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)

    def test_rbac_platform_admin_cannot_create_ingredient(self, api, platform_admin_headers):
        """PRD §2.1: "Once the headers are present, the role named in `X-User-Role`
        is checked against the RBAC matrix for the target endpoint; a role that is
        not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §4 restricts POST /sourcing/ingredients to
        ProcurementManager.

        Design: Corner/roles/rbac_platform_admin_cannot_create_ingredient
        """
        resp = api.create_ingredient(
            create_ingredient_payload(ingredient_code="RBAC-4", name="Rbac Four"),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
