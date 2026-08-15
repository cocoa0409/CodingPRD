"""Product/party registration, envelope/auth rules, pagination (PRD §2.1–2.4, §2.8, §3.1–3.2, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_party,
    assert_product,
    create_party_payload,
    create_product_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
class TestProducts:
    def test_product_creation_applies_defaults(self, api, analyst_headers):
        """PRD §3.1: "A new product is born `UNCLASSIFIED` with `classification_count` zero and `active_classification_id` null."
        PRD §2.4: "`version` (integer): a system-managed counter that starts at creation and increments by exactly 1 on every mutation of the resource, including mutations driven by cascading side effects originating on another resource."

        Design: Corner/entities/product_creation_applies_defaults
        """
        res = api.create_product(
            create_product_payload(sku="P-001", name="Bolt", controlled_content_pct=0,
                                   unit_value_cents=50),
            analyst_headers,
        )
        data = validate_success(res, 201)
        assert_product(data)
        assert data["status"] == "UNCLASSIFIED", f"expected UNCLASSIFIED, got {data['status']}"
        assert data["version"] == 1, f"new product version must be 1, got {data['version']}"
        assert data["classification_count"] == 0
        assert data["active_classification_id"] is None

    def test_product_get_not_found_returns_404(self, api, analyst_headers):
        """PRD §2.8: "3. **Existence** — path-templated resource ids exist, validated strictly left to right, and body-supplied foreign-key references (`product_id`, `party_id`, `tcp_id`, `license_id`, `order_id`) exist (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/product_get_not_found_returns_404
        """
        res = api.get_product(NON_EXISTENT_UUID, analyst_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestParties:
    def test_party_defaults_and_computed_posture(self, api, ops_headers):
        """PRD §3.2: "an `is_foreign_national` flag that defaults to false and gates deemed-export access."
        PRD §3.2: "A new party's `screening_posture` is `UNSCREENED` and its `active_grant_count` is zero; `last_screened_at` stays null until the first screening runs."

        Design: Corner/entities/party_defaults_and_computed_posture
        """
        # is_foreign_national deliberately omitted to exercise the server-side default.
        payload = create_party_payload(legal_name="Acme SPA", country_code="ITA",
                                       city="Milan", party_type="CUSTOMER")
        assert "is_foreign_national" not in payload
        res = api.create_party(payload, ops_headers)
        data = validate_success(res, 201)
        assert_party(data)
        assert data["is_foreign_national"] is False
        assert data["screening_posture"] == "UNSCREENED"
        assert data["active_grant_count"] == 0
        assert data["last_screened_at"] is None

    def test_invalid_enum_value_rejected(self, api, ops_headers):
        """PRD §2.8: "4. **Request shape** — required fields present; no unknown, computed, or system-managed fields smuggled into the body; types valid; enum membership valid; dates in `YYYY-MM-DD` format; `quantity` greater than 0; `unit_value_cents` greater than 0; `approved_value_cents` greater than 0; `approved_quantity` greater than 0; `controlled_content_pct` at least 0 and at most 100; `valid_from` not after `valid_until`; `effective_from` not after `effective_to`; `start_date` strictly before `end_date`; every `conditions` entry within the declared condition set (`ERR_VALIDATION`, 400)."

        Design: Corner/entities/invalid_enum_value_rejected
        """
        res = api.create_party(
            create_party_payload(legal_name="X", country_code="FRA", city="Paris",
                                 party_type="ALIEN"),
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION)

    def test_create_product_with_computed_field_rejected(self, api, analyst_headers):
        """PRD §2.8: "4. **Request shape** — required fields present; no unknown, computed, or system-managed fields smuggled into the body; types valid; enum membership valid; dates in `YYYY-MM-DD` format; `quantity` greater than 0; `unit_value_cents` greater than 0; `approved_value_cents` greater than 0; `approved_quantity` greater than 0; `controlled_content_pct` at least 0 and at most 100; `valid_from` not after `valid_until`; `effective_from` not after `effective_to`; `start_date` strictly before `end_date`; every `conditions` entry within the declared condition set (`ERR_VALIDATION`, 400)."

        Design: Corner/entities/create_product_with_computed_field_rejected
        """
        payload = create_product_payload(sku="P-005", name="Nut", controlled_content_pct=0,
                                         unit_value_cents=10)
        payload["status"] = "CLASSIFIED"  # system-managed field smuggled into the body
        res = api.create_product(payload, analyst_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION)


class TestAuthenticationAndAuthorization:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value outside the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        res = api.get_product(NON_EXISTENT_UUID, headers=None)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_on_create_product(self, api, ops_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted to call the target endpoint per the authorization matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/forbidden_role_on_create_product
        """
        res = api.create_product(
            create_product_payload(sku="P-030", name="X", controlled_content_pct=0,
                                   unit_value_cents=10),
            ops_headers,  # POST /products is ComplianceAnalyst-only per the §4 matrix
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_authorization_beats_existence_priority(self, api, ops_headers):
        """PRD §2.8: "When multiple rules could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure."
        PRD §2.8: "2. **Authorization** — the role is permitted to call this endpoint (`ERR_FORBIDDEN`, 403). Applies to every endpoint."
        PRD §2.8: "3. **Existence** — path-templated resource ids exist, validated strictly left to right, and body-supplied foreign-key references (`product_id`, `party_id`, `tcp_id`, `license_id`, `order_id`) exist (`ERR_NOT_FOUND`, 404)."

        Design: Corner/validations/authorization_beats_existence_priority
        """
        # TradeOpsSpecialist on a Manager-only endpoint AND a non-existent id:
        # authorization (2) is evaluated before existence (3), so 403 must surface.
        res = api.review_classification(NON_EXISTENT_UUID, {"decision": "APPROVE"}, ops_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_all_roles_can_read_shared_get(self, api, analyst_headers, manager_headers,
                                           ops_headers, director_headers):
        """PRD §4: "| GET | `/compliance/products/{id}` | Get a product | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |"

        Design: Corner/rbac/all_roles_can_read_shared_get
        """
        created = validate_success(
            api.create_product(create_product_payload(sku="P-061", name="Lid",
                                                      controlled_content_pct=0,
                                                      unit_value_cents=10),
                               analyst_headers),
            201,
        )
        for headers in (analyst_headers, manager_headers, ops_headers, director_headers):
            res = api.get_product(created["id"], headers)
            data = validate_success(res, 200)
            assert data["id"] == created["id"]


class TestForeignKeyExistence:
    def test_fk_reference_to_missing_parent_returns_404(self, api, ops_headers, analyst_headers):
        """PRD §2.9: "References supplied in the request body — the `product_id` of a classification, license, TCP, or order; the `party_id` of an order or access grant; the `license_id` of an attach request; the `order_id` of a new shipment; the `tcp_id` of an access grant — are validated for existence at the same pipeline stage."

        Design: Corner/entities/fk_reference_to_missing_parent_returns_404
        """
        res1 = api.create_shipment(
            {"order_id": NON_EXISTENT_UUID, "quantity": 1, "planned_ship_date": "2026-08-10"},
            ops_headers,
        )
        validate_error(res1, ApiErrorId.ERR_NOT_FOUND)

        res2 = api.create_access_grant(
            {"tcp_id": NON_EXISTENT_UUID, "party_id": NON_EXISTENT_UUID,
             "start_date": "2026-08-01", "end_date": "2026-09-01"},
            analyst_headers,
        )
        validate_error(res2, ApiErrorId.ERR_NOT_FOUND)


class TestDateRangeValidation:
    def test_date_range_ordering_rejected(self, api, analyst_headers):
        """PRD §2.8: "4. **Request shape** — required fields present; no unknown, computed, or system-managed fields smuggled into the body; types valid; enum membership valid; dates in `YYYY-MM-DD` format; `quantity` greater than 0; `unit_value_cents` greater than 0; `approved_value_cents` greater than 0; `approved_quantity` greater than 0; `controlled_content_pct` at least 0 and at most 100; `valid_from` not after `valid_until`; `effective_from` not after `effective_to`; `start_date` strictly before `end_date`; every `conditions` entry within the declared condition set (`ERR_VALIDATION`, 400)."

        Design: Corner/entities/date_range_ordering_rejected
        """
        product = validate_success(
            api.create_product(create_product_payload(sku="P-004", name="Ring",
                                                      controlled_content_pct=0,
                                                      unit_value_cents=10),
                               analyst_headers),
            201,
        )
        res = api.create_license(
            {"product_id": product["id"], "issuing_authority": "BIS",
             "approved_value_cents": 1000, "approved_quantity": 10,
             "valid_from": "2026-12-31", "valid_until": "2026-01-01"},
            analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION)


class TestPartyListingPagination:
    def test_parties_list_pagination_envelope(self, api, ops_headers, analyst_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/parties_list_pagination_envelope
        """
        api.create_party(create_party_payload(legal_name="Alpha SRO", country_code="CZE",
                                              city="Prague", party_type="CUSTOMER"),
                         ops_headers)
        api.create_party(create_party_payload(legal_name="Beta BV", country_code="NLD",
                                              city="Eindhoven", party_type="CONSIGNEE"),
                         ops_headers)

        page1, meta1 = validate_paginated(
            api.list_parties(analyst_headers, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["legal_name"] == "Alpha SRO", (
            f"created_at ASC order expected Alpha SRO first, got {page1[0]['legal_name']}"
        )

        page2, meta2 = validate_paginated(
            api.list_parties(analyst_headers, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["legal_name"] == "Beta BV"
        assert is_valid_uuid(page2[0]["id"])
