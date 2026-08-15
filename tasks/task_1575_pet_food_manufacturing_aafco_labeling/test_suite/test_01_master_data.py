"""Master-data creation, defaults, system fields, lookup errors, listing (PRD §2, §3.1, §3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_brand_owner,
    assert_formula,
    assert_ingredient,
    brand_owner_payload,
    complaint_case_payload,
    create_brand_owner,
    create_formula,
    formula_ingredient_payload,
    formula_payload,
    ingredient_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMasterDataCreation:
    def test_brand_owner_creation_succeeds_with_declared_fields(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "A `PlatformAdmin` registers each private-label **Brand Owner**
        with its `legal_name` (non-empty, at most 200 characters), its `fein` (a
        9-digit federal employer identification string, unique across all brand
        owners), and a `contact_email` used as the primary regulatory contact."
        PRD §3.1: "A brand owner's `status` begins at `ACTIVE` and its declared
        lifecycle domain is `ACTIVE`, `SUSPENDED`, and `TERMINATED`."
        PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."
        PRD §4: "Operations that create a new resource — a brand owner, supplier,
        ingredient, pairing, formula, ingredient line, nutrient profile, trial
        protocol, production batch, lot, lab sample, guaranteed-analysis report,
        state registration, complaint case, or recall action — return `201 Created`."

        Design: Corner/entities/brand_owner_creation_succeeds_with_declared_fields
        """
        resp = api.create_brand_owner(
            brand_owner_payload(
                legal_name="Corner Brands LLC",
                fein="551000010",
                contact_email="ops@corner.example",
            ),
            platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_brand_owner(data)
        assert data["legal_name"] == "Corner Brands LLC"
        assert data["fein"] == "551000010"
        assert data["status"] == "ACTIVE"

    def test_create_brand_owner_missing_fein_fails(self, api, platform_admin_headers):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.1 names `fein` among the registration inputs of a brand owner.

        Design: Corner/entities/create_calls_missing_required_fields_fail
        """
        resp = api.create_brand_owner(
            {"legal_name": "No Fein Co", "contact_email": "x@nofein.example"},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_ingredient_missing_nutrient_matrix_fails(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.1: "The `nutrient_matrix` captures the ingredient's typical nutrient
        contribution per kilogram as-fed: an object keyed by AAFCO nutrient codes
        (for example `CRUDE_PROTEIN`, `CRUDE_FAT`, `CRUDE_FIBER`, `MOISTURE`,
        `CALCIUM`, `PHOSPHORUS`) mapping to numeric fractions between 0 and 1
        inclusive (or kcal-per-kg figures), with a moisture entry mandatory."

        Design: Corner/entities/create_calls_missing_required_fields_fail
        """
        resp = api.create_ingredient(
            {
                "aafco_name": "Corn Gluten Meal",
                "ingredient_code": "CGML0001",
                "allergen_class": "GRAIN",
            },
            formulation_scientist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_formula_missing_species_fails(
        self, api, platform_admin_headers, formulation_scientist_headers
    ):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.3: a formula is created "with a brand-scoped `formula_code` (unique
        within that brand), the marketing `product_name` printed on the label, the
        target `species` (`DOG` or `CAT`), the AAFCO `life_stage` claim (`GROWTH`,
        `ADULT_MAINTENANCE`, `ALL_LIFE_STAGES`, or `GESTATION_LACTATION`), and the
        `adequacy_basis` declaring the substantiation pathway: `FORMULATION` or
        `FEEDING_TRIAL`."

        Design: Corner/entities/create_calls_missing_required_fields_fail
        """
        brand = create_brand_owner()
        resp = api.create_formula(
            brand["id"],
            {
                "formula_code": "RF-001",
                "product_name": "No Species",
                "life_stage": "ADULT_MAINTENANCE",
                "adequacy_basis": "FORMULATION",
            },
            formulation_scientist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_ingredient_creation_applies_declared_defaults(
        self, api, formulation_scientist_headers
    ):
        """PRD §3.1: "Each ingredient declares an `allergen_class` for
        change-control flagging — one of `NONE`, `POULTRY`, `BEEF`, `FISH`,
        `DAIRY`, `GRAIN`, or `OTHER` — and a `requires_coa` flag, defaulting to
        true, that determines whether every receiving lot and pairing review must
        carry a certificate of analysis."
        PRD §3.1: "An ingredient's `status` starts at `ACTIVE` and may later
        become `RETIRED`, at which point it can no longer support formula
        submission or batch release."

        Design: Corner/entities/ingredient_creation_applies_declared_defaults
        """
        resp = api.create_ingredient(
            ingredient_payload(aafco_name="Chicken By-Product Meal"),
            formulation_scientist_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_ingredient(data)
        assert data["requires_coa"] is True, "requires_coa must default to true"
        assert data["status"] == "ACTIVE", "status must start at ACTIVE"

    def test_formula_creation_assigns_system_and_computed_fields(
        self, api, platform_admin_headers, formulation_scientist_headers
    ):
        """PRD §3.3: "A formula starts in `DRAFT` with `revision_number` 1,
        `substantiation_locked_version` null, `total_batch_count` zero, and
        `open_recall_flag` false."
        PRD §2.4: "`version` (integer): a system-managed counter that starts at 1
        and increments by exactly one on every mutation of the resource"

        Design: Corner/entities/formula_creation_assigns_system_and_computed_fields
        """
        brand = create_brand_owner()
        resp = api.create_formula(brand["id"], formula_payload(), formulation_scientist_headers)
        data = validate_success(resp, expected_status=201)
        assert_formula(data)
        assert data["version"] == 1
        assert data["revision_number"] == 1
        assert data["status"] == "DRAFT"
        assert data["total_batch_count"] == 0
        assert data["open_recall_flag"] is False

    def test_brand_owner_computed_counters_start_at_zero(self, api, platform_admin_headers):
        """PRD §3.1: "Two computed counters ride on the brand record and start at
        zero: `open_recall_count`, the number of recall actions linked to the
        brand's formulas whose status is anything other than `CLOSED`, and
        `complaint_score`, the rolling weighted complaint score described in §3.8
        that drives registration holds."

        Design: Corner/entities/brand_owner_computed_counters_start_at_zero
        """
        resp = api.create_brand_owner(brand_owner_payload(), platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_brand_owner(data)
        assert data["complaint_score"] == 0
        assert data["open_recall_count"] == 0


class TestLookupAndForeignKeyErrors:
    @pytest.mark.parametrize(
        "resource",
        ["formulas", "recall-actions", "supplier-ingredient-approvals"],
    )
    def test_get_with_unknown_id_fails_not_found(self, api, qa_approver_headers, resource):
        """PRD §2.10: "Third, existence: every path identifier and foreign-key
        body field must resolve, checked left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_with_unknown_id_fails_not_found
        """
        resp = api.get(f"/petfood/{resource}/{NON_EXISTENT_UUID}", headers=qa_approver_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_formula_create_with_unresolvable_parent_fails(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.9: "Each identifier in the URL must resolve to an existing row
        before the next is examined, and the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve"

        Design: Corner/entities/child_create_with_unresolvable_fk_fails
        """
        resp = api.create_formula(
            NON_EXISTENT_UUID, formula_payload(), formulation_scientist_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_line_add_with_unresolvable_ingredient_fails(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.9: "The same rule governs foreign-key-valued fields in request
        bodies: any `brand_owner_id`, `formula_id`, `batch_id`, `supplier_id`, or
        `ingredient_id` that does not resolve to an existing row produces
        `ERR_NOT_FOUND`."

        Design: Corner/entities/child_create_with_unresolvable_fk_fails
        """
        brand = create_brand_owner()
        formula = create_formula(brand["id"])
        resp = api.add_formula_ingredient(
            formula["id"],
            formula_ingredient_payload(NON_EXISTENT_UUID, inclusion_pct=50.0),
            formulation_scientist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_complaint_create_with_unresolvable_formula_fails(
        self, api, quality_analyst_headers
    ):
        """PRD §2.9: "The same rule governs foreign-key-valued fields in request
        bodies: any `brand_owner_id`, `formula_id`, `batch_id`, `supplier_id`, or
        `ingredient_id` that does not resolve to an existing row produces
        `ERR_NOT_FOUND`."

        Design: Corner/entities/child_create_with_unresolvable_fk_fails
        """
        brand = create_brand_owner()
        resp = api.create_complaint_case(
            complaint_case_payload(brand["id"], NON_EXISTENT_UUID),
            quality_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestEnumAndListingConstraints:
    def test_allergen_class_outside_declared_set_fails(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.1: "an `allergen_class` for change-control flagging — one of `NONE`,
        `POULTRY`, `BEEF`, `FISH`, `DAIRY`, `GRAIN`, or `OTHER`"

        Design: Corner/entities/enum_values_outside_declared_sets_fail
        """
        resp = api.create_ingredient(
            ingredient_payload(allergen_class="MEAT"), formulation_scientist_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_species_outside_declared_set_fails(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.3: "the target `species` (`DOG` or `CAT`)"

        Design: Corner/entities/enum_values_outside_declared_sets_fail
        """
        brand = create_brand_owner()
        resp = api.create_formula(
            brand["id"], formula_payload(species="FISH"), formulation_scientist_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_severity_outside_declared_set_fails(self, api, quality_analyst_headers):
        """PRD §2.10: "Independently of this ordering, structural request validity
        is always enforced: a missing required field, a wrong-typed value, or an
        enum value outside its declared set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400), and out-of-bounds pagination parameters are rejected with
        `ERR_PAGINATION`."
        PRD §3.8: "the reporter-assessed `severity` (`MINOR`, `SERIOUS`,
        `LIFE_THREATENING`, or `DEATH`)"

        Design: Corner/entities/enum_values_outside_declared_sets_fail
        """
        brand = create_brand_owner()
        formula = create_formula(brand["id"])
        resp = api.create_complaint_case(
            complaint_case_payload(brand["id"], formula["id"], severity="CATASTROPHIC"),
            quality_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_brand_owner_listing_paginates(self, api, platform_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The
        `offset` parameter states how many items to skip and defaults to 0; a
        negative offset is invalid."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/brand_owner_listing_paginates_and_filters
        """
        for i in range(3):
            create_brand_owner(legal_name=f"Page Co {i}", fein=f"55100008{i}")
        page1, meta1 = validate_paginated(
            api.list_brand_owners(platform_admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_brand_owners(platform_admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
