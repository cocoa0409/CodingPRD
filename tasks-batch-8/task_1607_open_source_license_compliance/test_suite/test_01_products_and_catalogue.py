"""Products and the component catalogue: creation contract, not-found
behavior, computed-field timing, pagination, and catalogue filters."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_component,
    assert_product,
    create_component,
    create_component_payload,
    create_product,
    create_product_payload,
    get_success_data,
    manifest_component_spec,
    setup_product_with_completed_scan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductCreation:
    def test_product_creation_required_fields(self, api, analyst_headers):
        """PRD §3.1: "A new product starts with `compliance_posture` set to
        `COMPLIANT`, `posture_version` at 1, and all four aggregate counts at
        zero." PRD §2.4: every resource carries `id`, `created_at`,
        `updated_at`, and `version`.

        Design: Corner/entities/product_creation_required_fields
        """
        resp = api.create_product(
            create_product_payload(
                product_code="TEST-001", product_name="Test Product",
                distribution_model="SaaS"),
            analyst_headers)
        product = validate_success(resp, 201)
        assert_product(product)
        assert product["product_code"] == "TEST-001"
        assert product["product_name"] == "Test Product"
        assert product["distribution_model"] == "SaaS"
        assert product["compliance_posture"] == "COMPLIANT"
        assert product["posture_version"] == 1
        assert product["total_dependency_count"] == 0
        assert product["copyleft_dependency_count"] == 0
        assert product["restricted_dependency_count"] == 0
        assert product["high_severity_vulnerability_count"] == 0

    def test_product_missing_required_field_returns_error(self, api,
                                                          analyst_headers):
        """PRD §2.5: "Malformed request payloads more generally are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/product_missing_required_field_returns_error
        """
        resp = api.create_product(
            {"product_name": "No Code", "distribution_model": "SaaS"},
            analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_product_retrieval_not_found(self, api, analyst_headers):
        """PRD §2.6: "Each entity type carries its own not-found identifier —
        `ERR_PRODUCT_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, ...". PRD §5 maps
        `ERR_PRODUCT_NOT_FOUND` to 404.

        Design: Corner/entities/product_retrieval_not_found
        """
        resp = api.get_product(NON_EXISTENT_UUID, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 404)


class TestComponentCatalogue:
    def test_component_computed_fields_ignore_input(self, api,
                                                    analyst_headers):
        """PRD §3.2: "A freshly registered component has
        `discovered_license_spdx` unset — it stays null until a scan completes
        — and no policy classification computed yet."

        Design: Corner/entities/component_computed_fields_ignore_input
        """
        resp = api.create_component(
            create_component_payload(
                package_url="pkg:npm/test@1.0.0", component_name="test",
                version="1.0.0", declared_license_spdx="MIT"),
            analyst_headers)
        component = validate_success(resp, 201)
        assert_component(component)
        assert component["package_url"] == "pkg:npm/test@1.0.0"
        # PRD §2.4 naming note: on a Component, `version` is the upstream
        # package version string.
        assert component["version"] == "1.0.0"
        assert component["discovered_license_spdx"] is None
        assert component["license_policy_classification"] is None
        assert component["effective_classification"] is None

    def test_unknown_license_defaults_to_restricted(self, api):
        """PRD §3.2: "A component whose discovered license is null or
        unrecognized does not fail open — the classifier falls back to
        `RESTRICTED` and lets the approval workflow decide."

        Design: Corner/calculations/license_classification_unknown_defaults_restricted
        """
        ctx = setup_product_with_completed_scan(manifest=[
            manifest_component_spec(
                package_url="pkg:npm/unknown@1.0.0",
                declared_license_spdx="UNKNOWN-LICENSE-XYZ")])
        components = get_success_data(api.list_components(
            ctx["analyst_headers"],
            params={"package_url": "pkg:npm/unknown@1.0.0"}))
        assert len(components) == 1
        assert components[0]["license_policy_classification"] == "RESTRICTED"

    def test_components_filter_by_effective_classification(self, api):
        """PRD §3.2: "The catalogue listing supports `package_url` and
        `effective_classification` filters for lookup work." PRD §3.2: "MIT,
        BSD-2-Clause, BSD-3-Clause, ISC, Apache-2.0, Zlib, and Unlicense
        classify as `PERMISSIVE`; LGPL-2.1, LGPL-3.0, MPL-2.0, EPL-2.0, and
        CDDL-1.0 classify as `WEAK_COPYLEFT`; GPL-2.0, GPL-3.0, AGPL-3.0, and
        SSPL-1.0 classify as `STRONG_COPYLEFT`".

        Design: Corner/cross_cutting/selector_policy_component_filtering
        """
        create_component(package_url="pkg:npm/mit@1.0.0",
                         declared_license_spdx="MIT")
        create_component(package_url="pkg:npm/lgpl@1.0.0",
                         declared_license_spdx="LGPL-2.1")
        create_component(package_url="pkg:npm/gpl@1.0.0",
                         declared_license_spdx="GPL-3.0")
        # A completed scan populates discovered licenses and computes the
        # policy classification of every resolved component (PRD §3.3).
        ctx = setup_product_with_completed_scan(manifest=[
            manifest_component_spec(package_url="pkg:npm/mit@1.0.0",
                                    declared_license_spdx="MIT"),
            manifest_component_spec(package_url="pkg:npm/lgpl@1.0.0",
                                    declared_license_spdx="LGPL-2.1"),
            manifest_component_spec(package_url="pkg:npm/gpl@1.0.0",
                                    declared_license_spdx="GPL-3.0")])
        headers = ctx["analyst_headers"]
        for classification, purl in (
                ("PERMISSIVE", "pkg:npm/mit@1.0.0"),
                ("WEAK_COPYLEFT", "pkg:npm/lgpl@1.0.0"),
                ("STRONG_COPYLEFT", "pkg:npm/gpl@1.0.0")):
            items = get_success_data(api.list_components(
                headers, params={"effective_classification": classification}))
            assert len(items) == 1, (
                f"expected exactly one {classification} component, got "
                f"{[c['package_url'] for c in items]}")
            assert items[0]["package_url"] == purl
            assert items[0]["effective_classification"] == classification


class TestProductListing:
    def test_list_products_pagination(self, api, analyst_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when omitted it defaults to 10, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0." PRD §2.3: "List responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`." PRD §2.3: "every
        list endpoint returns resources sorted by `created_at` in ascending
        order."

        Design: Corner/endpoints/list_products_pagination
        """
        for i in range(1, 6):
            create_product(product_code=f"P{i}", product_name=f"Product {i}")

        page1, meta1 = validate_paginated(
            api.list_products(analyst_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 5
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_products(analyst_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 2
        assert meta2["has_more"] is True

        page3, meta3 = validate_paginated(
            api.list_products(analyst_headers, params={"limit": 2, "offset": 4}))
        assert len(page3) == 1
        assert meta3["has_more"] is False

        created = [p["created_at"] for p in page1 + page2 + page3]
        assert created == sorted(created), (
            "products must be sorted by created_at ascending")
        assert len({p["id"] for p in page1 + page2 + page3}) == 5
