"""Entity creation shape, envelope, and listing contract tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_brand_rep_headers,
    create_claim_standard_payload, create_brand_payload, create_product_payload,
    create_ingredient_payload,
    create_standard, create_brand, create_product, add_ingredient,
    assert_claim_standard, assert_product, assert_ingredient,
)

ADMIN = TEST_USERS["verifier_admin_headers"]


class TestClaimStandardDefaults:
    def test_standard_create_applies_numeric_defaults(self, api):
        """PRD section 3.1: "Three optional knobs carry defaults when omitted:
        `audit_validity_months` defaults to 12 and controls how many calendar months a
        passed facility audit stays fresh after its decision; `renewal_window_days`
        defaults to 60 and controls how far before license expiry the renewal window
        opens; `license_term_days` defaults to 365 and is the number of days of
        validity granted at issuance and at each renewal."

        Design: Corner/entities/standard_create_applies_defaults
        """
        res = api.create_claim_standard(create_claim_standard_payload(), ADMIN)
        std = validate_success(res, 201)
        assert_claim_standard(std)
        assert std["audit_validity_months"] == 12
        assert std["renewal_window_days"] == 60
        assert std["license_term_days"] == 365


class TestProductCreation:
    def test_product_create_missing_gtin_rejected(self, api):
        """PRD section 2.9: "request-shape errors are evaluated: missing required
        fields, unknown or computed fields in the body, invalid enum members,
        numeric range violations, and missing or improperly present conditional
        fields all fail here with `ERR_VALIDATION`."
        PRD section 3.2: "A `BrandRep` enrolls a product with a payload containing
        the `brand_id` of their own brand, the `standard_id` of the claim standard
        being pursued, the product `name`, its `gtin`, and the
        `annual_volume_units` production volume."

        Design: Corner/entities/product_create_missing_required_field_rejected
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        payload = create_product_payload(brand["id"], std["id"], name="P1",
                                         annual_volume_units=100)
        del payload["gtin"]
        res = api.create_product(payload, make_brand_rep_headers(brand["id"]))
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_ingredient_invalid_crop_type_rejected(self, api):
        """PRD section 3.3: "its `crop_type` — one of `HIGH_RISK`, `LOW_RISK`, or
        `NON_CROP` — and its `declared_weight_pct`"
        PRD section 2.9: "missing required fields, unknown or computed fields in
        the body, invalid enum members, numeric range violations, and missing or
        improperly present conditional fields all fail here with `ERR_VALIDATION`."

        Design: Corner/entities/ingredient_invalid_enum_rejected
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        res = api.create_ingredient(
            create_ingredient_payload(product["id"], name="X",
                                      crop_type="MEDIUM_RISK",
                                      declared_weight_pct=10.00),
            make_brand_rep_headers(brand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_get_nonexistent_product_returns_404(self, api):
        """PRD section 2.9: "then existence: path identifiers are validated left to
        right and body-supplied foreign keys — `brand_id`, `standard_id`,
        `product_id`, `ingredient_id`, `sampling_plan_id` — must resolve to
        existing resources, else `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        res = api.get_product(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_computed_field_in_ingredient_body_rejected(self, api):
        """PRD section 2.9: "missing required fields, unknown or computed fields in
        the body, invalid enum members, numeric range violations, and missing or
        improperly present conditional fields all fail here with `ERR_VALIDATION`."

        Design: Corner/entities/computed_field_in_request_body_rejected
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        payload = create_ingredient_payload(product["id"], name="Soy",
                                            crop_type="HIGH_RISK",
                                            declared_weight_pct=10.00)
        payload["is_exempt"] = True
        res = api.create_ingredient(payload, make_brand_rep_headers(brand["id"]))
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


class TestImmediateConsistency:
    def test_ingredient_create_response_carries_derived_flags(self, api):
        """PRD section 2.10: "All of it is reconciled immediately — every side
        effect described in §3 applies atomically within the request that
        triggered it; the API never defers a recomputation to a later read or
        background job."
        PRD section 3.3: "Testing obligation follows: `requires_pcr` is true only
        for a `HIGH_RISK` crop that is not exempt."
        PRD section 3.3: "Anything else is `PENDING`."

        Design: Corner/consistency_model/response_immediately_reflects_computed_mutation
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        res = api.create_ingredient(
            create_ingredient_payload(product["id"], name="Soy",
                                      crop_type="HIGH_RISK",
                                      declared_weight_pct=30.00),
            make_brand_rep_headers(brand["id"]),
        )
        ing = validate_success(res, 201)
        assert_ingredient(ing)
        assert ing["is_exempt"] is False
        assert ing["requires_pcr"] is True
        assert ing["requires_affidavit"] is True
        assert ing["compliance_status"] == "PENDING"


class TestEnvelopes:
    def test_error_envelope_shape_on_failure(self, api):
        """PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        res = api.get_product(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_product_list_pagination_envelope_and_defaults(self, api):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."
        PRD section 2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_and_defaults
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        for i in range(3):
            create_product(brand, std, name=f"P{i+1}", gtin=f"G-{i+1}")

        res1 = api.list_products(
            ADMIN, params={"brand_id": brand["id"], "limit": 2, "offset": 0}
        )
        data1, meta1 = validate_paginated(res1)
        assert res1.json()["response_type"] == "array"
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        res2 = api.list_products(
            ADMIN, params={"brand_id": brand["id"], "limit": 2, "offset": 2}
        )
        data2, meta2 = validate_paginated(res2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        res3 = api.list_products(ADMIN, params={"brand_id": brand["id"]})
        data3, meta3 = validate_paginated(res3)
        assert meta3["limit"] == 10
        assert meta3["offset"] == 0
        assert len(data3) == 3
        assert meta3["has_more"] is False

        body = res3.json()
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
