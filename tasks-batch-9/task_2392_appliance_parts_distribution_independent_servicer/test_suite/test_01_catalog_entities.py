"""Catalog rows as written and read back: applied defaults, derived competence and
returnability, server-minted audit columns, append-only cross-references, and the
existence checks that guard creation."""
from test_helpers import (
    MISSING_PART_ID,
    MISSING_SERVICER_ACCOUNT_ID,
    PRICING_ADMIN,
    TEST_USERS,
    WARRANTY_ADMIN,
    ApiErrorId,
    api_client,
    assert_model_part_xref,
    assert_part,
    assert_versioned_fields,
    list_certifications,
    list_parts,
    make_account,
    make_part,
    make_pricing_tier,
    model_part_xref_payload,
    part_payload,
    read_part,
    supersession_payload,
    technician_certification_payload,
    validate_error,
    validate_success,
)

SERVICER_READER = TEST_USERS["servicer_headers"]


# ---------------------------------------------------------------------------
# Applied defaults and single-row reads
# ---------------------------------------------------------------------------

class TestPartCreation:

    def test_a_minimal_part_body_picks_up_every_documented_default(self):
        """PRD §3.1: "Three further inputs are optional: `lifecycle_status`, which
        defaults to `ACTIVE`; `core_required`, which defaults to false and marks a
        rebuildable assembly whose used core must come back; and
        `core_deposit_cents`, which defaults to 0 and is the per-unit deposit charged
        when a core is required."
        PRD §3.1: "A part's `superseded_by_part_id` always starts null."

        Design: Corner/entities/part_created_with_lifecycle_and_core_defaults_applied
        """
        response = api_client.create_part(
            part_payload(
                part_number="W10-PUMP", oem_code="WHIRLPOOL",
                description="Drain pump assembly", category="MECHANICAL",
                list_price_cents=12999, weight_grams=5200,
            ),
            PRICING_ADMIN,
        )
        part = validate_success(response, 201)
        assert_part(part)
        assert part["lifecycle_status"] == "ACTIVE"
        assert part["core_required"] is False
        assert part["core_deposit_cents"] == 0
        assert part["superseded_by_part_id"] is None
        assert part["list_price_cents"] == 12999

    def test_reading_the_part_back_by_id_returns_the_stored_row(self):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."
        PRD §3.1: "Both derived attributes are re-derived whenever the category or
        lifecycle changes, and both appear on every part read."

        Design: Corner/entities/part_get_by_id_returns_the_stored_catalog_row
        """
        created = make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )

        response = api_client.get_part(created["id"], SERVICER_READER)
        assert response.json()["response_type"] == "object"
        part = validate_success(response, 200)
        assert "error_id" not in part, "a success envelope carries no error_id"
        assert part["id"] == created["id"]
        assert part["part_number"] == "W10-PUMP"
        assert part["category"] == "MECHANICAL"
        assert part["weight_grams"] == 5200
        assert part["cert_level_required"] == "NONE"
        assert part["is_returnable"] is True

    def test_reading_an_id_that_was_never_minted_is_a_not_found(self):
        """PRD §2.7: "4. A 404 existence error — every path parameter resolves to a
        persisted row, validated left to right. Applies to every endpoint with a path
        parameter."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/get_part_with_unknown_id_returns_not_found
        """
        make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )

        response = api_client.get_part(MISSING_PART_ID, PRICING_ADMIN)
        body = validate_error(response, ApiErrorId.ERR_PART_NOT_FOUND)
        assert response.json()["response_type"] == "error"
        assert body["message"].strip(), "the error carries a human-readable message"


class TestPartInputSchema:

    def test_omitting_the_required_weight_is_rejected_and_writes_nothing(self):
        """PRD §2.7: "3. `ERR_INVALID_REQUEST` (400) — the request body conforms to
        the endpoint's input schema: every required field is present, no unknown field
        is supplied, enum values are in range, integer money and unit values are not
        negative, any `quantity` is at least 1, discount percentages fall between 0
        and 1 inclusive, and datetimes are ISO 8601 UTC. Applies to every endpoint."
        PRD §3.1: "A `PricingAdmin` creates a **Part** by supplying its `part_number`
        (unique across the catalog), the `oem_code` of the brand it belongs to, a
        human `description`, a commodity `category`, a `list_price_cents` greater
        than zero, and a `weight_grams` greater than zero."

        Design: Corner/entities/create_part_with_missing_required_weight_grams_is_rejected
        """
        payload = part_payload(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999,
        )
        payload.pop("weight_grams")

        response = api_client.create_part(payload, PRICING_ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        assert list_parts() == [], (
            "the malformed create must not persist a catalog row"
        )

    def test_a_category_outside_the_enum_is_rejected_rather_than_coerced(self):
        """PRD §3.1: "The `category` is one of `ELECTRICAL`, `MECHANICAL`,
        `COSMETIC`, or `SEALED_SYSTEM`, and it does three jobs at once: it selects
        which of the servicer's contract discounts applies, it determines what
        technician competence the part demands, and it determines whether the part can
        ever come back."
        PRD §2.7: "3. `ERR_INVALID_REQUEST` (400) — the request body conforms to the
        endpoint's input schema: every required field is present, no unknown field is
        supplied, enum values are in range, integer money and unit values are not
        negative, any `quantity` is at least 1, discount percentages fall between 0
        and 1 inclusive, and datetimes are ISO 8601 UTC. Applies to every endpoint."

        Design: Corner/entities/create_part_with_out_of_range_category_enum_is_rejected
        """
        response = api_client.create_part(
            part_payload(
                part_number="W10-PUMP", oem_code="WHIRLPOOL",
                description="Drain pump assembly", category="ELECTRONIC",
                list_price_cents=12999, weight_grams=5200,
            ),
            PRICING_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        assert list_parts() == [], (
            "an out-of-range enum is never coerced into a persisted row"
        )


# ---------------------------------------------------------------------------
# Derived attributes and audit columns
# ---------------------------------------------------------------------------

class TestDerivedPartAttributes:

    def test_competence_and_returnability_follow_category_and_lifecycle(self):
        """PRD §3.1: "`cert_level_required` is `SEALED_SYSTEM` when the category is
        `SEALED_SYSTEM`, `ADVANCED` when the category is `ELECTRICAL`, and `NONE` for
        every other category."
        PRD §3.1: "`is_returnable` is true when the category is anything other than
        `ELECTRICAL` **and** the `lifecycle_status` is anything other than `NLA`;
        electrical parts are non-returnable once they leave the counter, and that
        prohibition is absolute."

        Design: Corner/entities/part_cert_level_and_returnability_are_computed_from_category
        """
        cosmetic = make_part(
            part_number="W10-KNOB", oem_code="WHIRLPOOL", description="Control knob",
            category="COSMETIC", list_price_cents=1002, weight_grams=60,
        )
        electrical = make_part(
            part_number="GE-BOARD", oem_code="GE", description="Main control board",
            category="ELECTRICAL", list_price_cents=128000, weight_grams=400,
        )
        sealed = make_part(
            part_number="W10-COMP", oem_code="WHIRLPOOL",
            description="Sealed compressor", category="SEALED_SYSTEM",
            list_price_cents=320000, weight_grams=12000,
            core_required=True, core_deposit_cents=8500,
        )

        response = api_client.create_part(
            part_payload(
                part_number="W10-OLDBELT", oem_code="WHIRLPOOL",
                description="Discontinued drive belt", category="MECHANICAL",
                list_price_cents=4500, weight_grams=300, lifecycle_status="NLA",
            ),
            PRICING_ADMIN,
        )
        nla = validate_success(response, 201)

        assert cosmetic["cert_level_required"] == "NONE"
        assert cosmetic["is_returnable"] is True
        assert electrical["cert_level_required"] == "ADVANCED"
        assert electrical["is_returnable"] is False
        assert sealed["cert_level_required"] == "SEALED_SYSTEM"
        assert sealed["is_returnable"] is True
        assert nla["cert_level_required"] == "NONE", (
            f"MECHANICAL demands no competence, got {nla['cert_level_required']}"
        )
        assert nla["is_returnable"] is False, (
            "an NLA lifecycle removes returnability whatever the category"
        )

    def test_system_fields_are_server_generated_and_the_version_starts_at_one(self):
        """PRD §2.4: "Every resource carries an `id` that is a server-minted UUID
        with no type prefix — clients never supply it."
        PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO
        8601 UTC timestamp refreshed on every mutation, and `version`, an integer that
        starts at 1 on creation and increments by exactly 1 on every mutation of that
        row — including mutations the server performs on its own initiative as part of
        a cascade, and including mutations that only change computed money fields."
        PRD §3.1: "Recording a supersession — a `PricingAdmin` action, guarded by
        `expected_part_version` as described in §2.6 — sets the part's
        `lifecycle_status` to `SUPERSEDED` and writes the supplied
        `superseded_by_part_id`, linking it into a chain."

        Design: Corner/entities/part_system_fields_are_server_generated_and_version_starts_at_one
        """
        replacement = make_part(
            part_number="W10-PUMP-B", oem_code="WHIRLPOOL",
            description="Drain pump assembly rev B",
            category="MECHANICAL", list_price_cents=13500, weight_grams=5200,
        )
        original = make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )
        assert_versioned_fields(original)
        assert original["version"] == 1, (
            f"version starts at 1 on creation, got {original['version']}"
        )

        response = api_client.record_supersession(
            original["id"],
            supersession_payload(replacement["id"], original["version"]),
            PRICING_ADMIN,
        )
        superseded = validate_success(response, 200)

        assert superseded["version"] == 2, (
            f"one mutation increments the version by exactly 1, got "
            f"{superseded['version']}"
        )
        assert superseded["lifecycle_status"] == "SUPERSEDED"
        assert superseded["superseded_by_part_id"] == replacement["id"]
        assert superseded["created_at"] == original["created_at"], (
            "created_at records when the row was first persisted and never moves"
        )
        assert read_part(replacement["id"])["version"] == 1, (
            "the supersession target is not itself mutated"
        )


# ---------------------------------------------------------------------------
# Append-only cross-references and parent existence
# ---------------------------------------------------------------------------

class TestCrossReferenceImmutability:

    def test_a_cross_reference_row_carries_no_version_and_no_updated_at(self):
        """PRD §2.4: "There is one exception: a `ModelPartXref` is an immutable,
        append-only configuration row. It carries `id` and `created_at` only; it has
        no `updated_at` and no `version`, and there is no endpoint that modifies one."
        PRD §3.1: "These rows are append-only: once written they are never modified,
        and as noted in §2.4 they carry no `updated_at` and no `version`."

        Design: Corner/entities/model_part_xref_is_immutable_and_versionless
        """
        part = make_part(
            part_number="W10-PUMP", oem_code="WHIRLPOOL",
            description="Drain pump assembly", category="MECHANICAL",
            list_price_cents=12999, weight_grams=5200,
        )
        created = validate_success(
            api_client.create_model_part_xref(
                model_part_xref_payload(
                    part["id"], model_number="WTW5000DW1", position_code="P-14",
                    xref_source="OEM_PUBLICATION",
                ),
                PRICING_ADMIN,
            ),
            201,
        )
        assert "version" not in created
        assert "updated_at" not in created

        response = api_client.get_model_part_xref(created["id"], SERVICER_READER)
        xref = validate_success(response, 200)
        assert_model_part_xref(xref)
        assert xref["model_number"] == "WTW5000DW1"
        assert xref["part_id"] == part["id"]
        assert xref["position_code"] == "P-14"
        assert xref["xref_source"] == "OEM_PUBLICATION"
        assert xref == created, (
            "the row read back is identical to the row that was written"
        )


class TestCertificationParentExistence:

    def test_a_certification_naming_an_unknown_account_is_a_not_found(self):
        """PRD §2.7: "5. A 404 existence error — every foreign key in the request
        body resolves to a persisted row. The body foreign keys in question are
        `part_id`, `pricing_tier_id`, `pickup_branch_id`, `return_branch_id`,
        `order_line_id`, `substitute_part_id`, `branch_id`, `servicer_account_id`,
        `requested_part_id`, and `superseded_by_part_id`. Applies to every endpoint
        with foreign-key input."
        PRD §3.2: "A `WarrantyAdmin` records one by supplying the
        `servicer_account_id` of the employing account, the `technician_name` the
        certification belongs to, the `oem_code` whose training it records, a
        `cert_level` of `BASIC`, `ADVANCED`, or `SEALED_SYSTEM`, and the coverage
        interval bounded by `training_completed_at` and `expires_at`."

        Design: Corner/entities/technician_certification_rejects_an_unknown_servicer_account_parent
        """
        tier = make_pricing_tier(
            tier_code="GOLD", name="Gold Contract",
            electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
            min_annual_volume_cents=5000000,
        )
        make_account(
            tier, business_name="Ace Appliance Repair",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )

        response = api_client.create_technician_certification(
            technician_certification_payload(
                MISSING_SERVICER_ACCOUNT_ID,
                technician_name="R. Diaz", oem_code="WHIRLPOOL",
                cert_level="ADVANCED",
                training_completed_at="2026-01-01T00:00:00Z",
                expires_at="2027-01-01T00:00:00Z",
            ),
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_SERVICER_ACCOUNT_NOT_FOUND)

        assert list_certifications() == [], (
            "an unresolvable parent leaves no certification behind"
        )
