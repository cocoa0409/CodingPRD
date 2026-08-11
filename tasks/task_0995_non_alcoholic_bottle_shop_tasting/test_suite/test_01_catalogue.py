"""Catalogue foundations: creation rules, field constraints, uniqueness,
system-assigned identity fields (PRD §3.1, §3.2, §3.3, §2.4, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_category,
    assert_member,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_category,
    make_lot,
    make_member,
    make_sku,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestCategoryCreation:
    def test_category_creation_missing_code_rejected(self, api):
        """PRD §3.1: "The catalogue is organized into `Category` rows, each
        identified by a unique kebab-case `code` (lowercase alphanumeric plus
        dashes, between 2 and 48 characters — examples include `sparkling-tea`
        and `adaptogenic-soda`), a human-readable `display_name`, a
        `compliance_class` that determines the age-neutral posture of every SKU
        filed under it, and an `active` flag (defaulting to true) that controls
        whether new SKUs may be filed under the category."
        PRD §2.7: "4. Shape — required input fields are present and well-typed
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/category_creation_required_fields
        """
        set_clock()
        resp = api.create_category(
            {"display_name": "No Code", "compliance_class": "STANDARD"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_category_out_of_enum_compliance_class_rejected(self, api):
        """PRD §3.1: "The `compliance_class` takes one of five values:
        `STANDARD`, `SENSITIVE_INGREDIENT`, `HEMP_DERIVED`, `KAVA`, or
        `FUNCTIONAL_MUSHROOM`."
        PRD §2.7: "4. Shape — required input fields are present and well-typed
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/category_compliance_class_enum_rejected
        """
        set_clock()
        resp = api.create_category(
            {"code": "bad", "display_name": "Bad", "compliance_class": "BOOZY"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSkuCreation:
    def test_sku_abv_above_500_rejected(self, api):
        """PRD §3.1: "Any attempt to create a SKU with `abv_basis_points`
        above 500 is rejected outright — the system never carries inventory
        above the 5-percent ceiling."

        Design: Corner/entities/sku_abv_above_500_rejected
        """
        set_clock()
        category = make_category()
        resp = api.create_sku(
            {
                "category_id": category["id"],
                "sku_code": "s-501",
                "title": "S",
                "base_price_cents": 100,
                "abv_basis_points": 501,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMemberRegistration:
    def test_member_defaults_unverified_bronze_zero_balance(self, api):
        """PRD §3.4: "each member carries an `age_attestation_status` that
        progresses through a five-state lifecycle: `UNVERIFIED` (the initial
        state at registration), `PENDING_REVIEW`, `ATTESTED`, `REJECTED`, and
        the terminal `REVOKED`."
        PRD §3.3: "Below 5000 the tier is `BRONZE`."

        Design: Corner/entities/member_age_attestation_status_defaults_to_unverified
        """
        set_clock()
        data = validate_success(
            api.create_member(
                {
                    "email": "def@x.com",
                    "full_name": "Def",
                    "date_of_birth": "1990-01-01",
                    "home_state_code": "CA",
                },
                ADMIN,
            ),
            201,
        )
        assert_member(data)
        assert data["age_attestation_status"] == "UNVERIFIED"
        assert data["loyalty_tier"] == "BRONZE"
        assert data["loyalty_points_balance"] == 0

    def test_member_email_uniqueness(self, api):
        """PRD §3.3: "A `Member` registers with an `email` (unique,
        case-insensitive, RFC 5322 form), a `full_name`, a `date_of_birth`
        (ISO date), and a `home_state_code` (two-letter ISO 3166-2:US code)
        used both as the default shipping destination and as a compliance gate."
        PRD §2.7: "12. Uniqueness — `sku_code`, `code`, `email`, `state_code`,
        `(sku_id, lot_code)` (`ERR_DUPLICATE`)."

        Design: Corner/entities/member_email_uniqueness
        """
        set_clock()
        make_member(email="dup@x.com")
        resp = api.create_member(
            {
                "email": "dup@x.com",
                "full_name": "D2",
                "date_of_birth": "1991-01-01",
                "home_state_code": "WA",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestCategoryRetrieval:
    def test_category_not_found(self, api):
        """PRD §2.7: "3. Existence — every path-template and
        foreign-key-referenced entity exists (`ERR_NOT_FOUND`)."
        PRD §2.8: "If any path segment fails to resolve — the parent id does
        not exist, or the child id does not exist under that parent — the
        request is rejected with `ERR_NOT_FOUND`, and no further processing
        occurs."

        Design: Corner/entities/category_not_found
        """
        set_clock()
        resp = api.get_category(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestInventoryLotUniqueness:
    def test_duplicate_lot_code_within_sku_rejected(self, api):
        """PRD §3.2: "Each lot carries a `sku_id` linking back to its parent
        SKU, a vendor-supplied `lot_code` (unique within the pair of `sku_id`
        and `lot_code`), a `qty_received` (must be at least 1), a derived
        `qty_remaining`, a `unit_cost_cents` (per-unit acquisition cost), an
        `expires_on` ISO-8601 date, a derived `status`, and an optional
        `quarantine_reason`."
        PRD §2.7: "12. Uniqueness — `sku_code`, `code`, `email`, `state_code`,
        `(sku_id, lot_code)` (`ERR_DUPLICATE`)."

        Design: Corner/entities/inventory_lot_unique_sku_lot_code
        """
        set_clock()
        category = make_category()
        sku = make_sku(category["id"])
        make_lot(sku["id"], lot_code="X", expires_on="2027-01-01")
        resp = api.create_lot(
            sku["id"],
            {
                "lot_code": "X",
                "qty_received": 5,
                "unit_cost_cents": 10,
                "expires_on": "2027-01-02",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestSystemFields:
    def test_system_fields_assigned_on_creation(self, api):
        """PRD §2.4: "Every resource in the system shares a uniform identity
        and audit shape. Each resource carries: `id` — a server-minted UUID
        with no type prefix (the id is a bare UUID, not a string like
        `sku_...`). `created_at` — an ISO 8601 UTC timestamp with three
        fractional digits, set once at creation. `updated_at` — an ISO 8601
        UTC timestamp with three fractional digits, refreshed on every
        mutation. `version` — an integer that increments by exactly one on
        every mutation of the resource."

        Design: Corner/entities/system_fields_id_created_at_version_assigned
        """
        set_clock()
        data = validate_success(
            api.create_category(
                {
                    "code": "sysf",
                    "display_name": "SysF",
                    "compliance_class": "STANDARD",
                },
                ADMIN,
            ),
            201,
        )
        assert_category(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int)
