"""Stored shapes: declared defaults, single-row reads, paginated listings, the
twelve not-found codes, the append-only signature, and the supersession graph.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

UNSTORED_MODEL_ID = "11111111-1111-4111-8111-111111111111"
UNSTORED_PART_ID = "22222222-2222-4222-8222-222222222222"


def test_new_model_carries_every_computed_default_in_the_create_response():
    """PRD §3.1: "A freshly registered model starts with `support_state` at
    `ACTIVE_PRODUCTION` — or directly at `LEGACY_SUPPORT` when an
    `end_of_production_date` was supplied in the same request — with
    `support_end_date` null, `documentation_posture` at `MISSING`,
    `compliance_posture` at `OPEN`, `open_obligation_count` at zero, and both
    `published_disassembly_revision_number` and
    `published_safety_sheet_revision_number` null."
    PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO 8601
    UTC timestamp refreshed on every mutation, and `version`, an integer that starts
    at 1 on creation and increments by one on every mutation — including mutations the
    server performs on its own initiative as part of a cascade, and including
    mutations that only change a computed field."

    Design: Corner/entities/product_model_create_stamps_every_declared_system_and_computed_default
    """
    fixtures.create_region(region_code="US-CA")

    response = api_client.create_product_model(
        factories.product_model_payload(
            model_code="CRX-E100",
            product_family="CRX",
            market_release_date="2024-01-01T00:00:00Z",
            repairability_tier="TIER_A_SELF_SERVICE",
        ),
        ADMIN,
    )
    model = validate_success(response, 201)

    assert model["support_state"] == "ACTIVE_PRODUCTION", model["support_state"]
    assert model["documentation_posture"] == "MISSING", model["documentation_posture"]
    assert model["compliance_posture"] == "OPEN", model["compliance_posture"]
    assert model["open_obligation_count"] == 0, model["open_obligation_count"]
    assert model["published_disassembly_revision_number"] is None, (
        model["published_disassembly_revision_number"]
    )
    assert model["published_safety_sheet_revision_number"] is None, (
        model["published_safety_sheet_revision_number"]
    )
    assert model["support_end_date"] is None, model["support_end_date"]
    assert model["version"] == 1, f"Expected version 1 on creation, got {model['version']}"


def test_single_part_read_echoes_the_four_core_ledger_aggregates_at_zero():
    """PRD §3.3: "A new catalog item is born in `DRAFT` with `restriction_reason` null
    and all four core-ledger aggregates — `core_face_value_committed_cents`,
    `core_liability_outstanding_cents`, `core_credit_settled_cents`, and
    `core_credit_forfeited_cents` — at zero."

    Design: Corner/entities/part_catalog_item_single_row_read_returns_the_stored_row
    """
    created = fixtures.create_part(
        sku="SKU-E100-CELL",
        list_price_cents=4500,
        core_return_required=True,
        core_credit_cents=900,
    )

    part = validate_success(api_client.get_part_catalog_item(created["id"], ADMIN), 200)

    assert part["sku"] == "SKU-E100-CELL", part["sku"]
    assert part["list_price_cents"] == 4500, part["list_price_cents"]
    assert part["core_credit_cents"] == 900, part["core_credit_cents"]
    assert part["status"] == "DRAFT", part["status"]
    assert part["restriction_reason"] is None, part["restriction_reason"]
    assert part["core_face_value_committed_cents"] == 0, (
        part["core_face_value_committed_cents"]
    )
    assert part["core_liability_outstanding_cents"] == 0, (
        part["core_liability_outstanding_cents"]
    )
    assert part["core_credit_settled_cents"] == 0, part["core_credit_settled_cents"]
    assert part["core_credit_forfeited_cents"] == 0, part["core_credit_forfeited_cents"]


def test_catalog_listing_counts_the_whole_population_not_the_page():
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not
    be smaller than 1, and may not be larger than 100."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's
    `meta` object alongside `total_count` and `has_more`."
    PRD §2.3: "Catalog listings filter on `part_class`, `safety_class`, `status`, and
    `supersedes_part_id` — that last filter is the flat reverse lookup across the
    self-referential supersession edge, and a dedicated successors read returns the
    parts that name a given part as their predecessor."

    Design: Corner/entities/part_catalog_item_list_reports_total_count_and_has_more
    """
    fixtures.create_part(sku="SKU-E101-A", list_price_cents=100)
    fixtures.create_part(sku="SKU-E101-B", list_price_cents=200)
    fixtures.create_part(sku="SKU-E101-T", part_class="TOOL", list_price_cents=300)

    page, meta = validate_paginated(
        api_client.list_part_catalog_items(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert meta["total_count"] == 3, (
        f"Expected the whole population of 3, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, meta["has_more"]
    assert len(page) == 2, f"Expected the page to carry 2 rows, got {len(page)}"

    filtered, filtered_meta = validate_paginated(
        api_client.list_part_catalog_items(
            ADMIN, params={"part_class": "COMPONENT", "limit": 10}
        )
    )
    assert filtered_meta["total_count"] == 2, (
        f"Expected the filtered population of 2 components, got "
        f"{filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, filtered_meta["has_more"]
    assert {row["sku"] for row in filtered} == {"SKU-E101-A", "SKU-E101-B"}, (
        [row["sku"] for row in filtered]
    )


def test_unstored_model_identifier_reads_as_model_not_found():
    """PRD §2.8: "Each identifier has its own not-found code: `model_id` yields
    `ERR_MODEL_NOT_FOUND`, `part_id` yields `ERR_PART_NOT_FOUND`, `compatibility_id`
    yields `ERR_COMPATIBILITY_NOT_FOUND`, `revision_id` yields
    `ERR_MANUAL_REVISION_NOT_FOUND`, `assessment_id` yields
    `ERR_ASSESSMENT_NOT_FOUND`, `order_id` yields `ERR_ORDER_NOT_FOUND`, `line_id`
    yields `ERR_ORDER_LINE_NOT_FOUND`, `provider_id` yields `ERR_PROVIDER_NOT_FOUND`,
    `certification_id` yields `ERR_CERTIFICATION_NOT_FOUND`, `case_id` yields
    `ERR_RETURN_CASE_NOT_FOUND`, `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`,
    and `acknowledgment_id` yields `ERR_ACKNOWLEDGMENT_NOT_FOUND`."
    PRD §2.8: "All twelve are 404 responses."

    Design: Corner/entities/unknown_model_id_read_returns_model_not_found
    """
    response = api_client.get_product_model(UNSTORED_MODEL_ID, ADMIN)
    validate_error(response, "ERR_MODEL_NOT_FOUND", 404)


def test_catalog_create_without_a_sku_fails_the_structural_gate():
    """PRD §2.9: "**Structural validity** — malformed body, missing required field,
    wrong JSON type, out-of-set enum value, or an unknown field
    (`ERR_INVALID_REQUEST`); then numeric range (`ERR_INVALID_RANGE`); then inverted
    intervals (`ERR_INVALID_DATE_RANGE`); then natural-key uniqueness
    (`ERR_DUPLICATE_NATURAL_KEY`)."

    Design: Corner/entities/part_catalog_item_without_sku_is_rejected
    """
    response = api_client.create_part_catalog_item(
        {
            "part_class": "COMPONENT",
            "safety_class": "UNRESTRICTED",
            "list_price_cents": 100,
            "core_return_required": False,
        },
        ADMIN,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(api_client.list_part_catalog_items(ADMIN))
    assert meta["total_count"] == 0, (
        f"the refused create must store nothing, got {meta['total_count']} rows"
    )


def test_omitted_optional_catalog_inputs_take_their_declared_defaults():
    """PRD §3.3: "`core_credit_cents` is the face value of the core return credit per
    unit and defaults to zero."
    PRD §3.3: "`concurrent_rental_capacity` is the number of kits in the rental pool
    and defaults to null, which is what non-rental classes carry."
    PRD §3.3: "`requires_authentication`, defaulting to false, means a delivered line
    mints a pairing token and must be authenticated."

    Design: Corner/entities/part_catalog_item_omitted_optional_flags_take_declared_defaults
    """
    response = api_client.create_part_catalog_item(
        {
            "sku": "SKU-E102-MIN",
            "part_class": "COMPONENT",
            "safety_class": "UNRESTRICTED",
            "list_price_cents": 750,
            "core_return_required": False,
        },
        ADMIN,
    )
    part = validate_success(response, 201)

    assert part["core_credit_cents"] == 0, part["core_credit_cents"]
    assert part["rental_deposit_cents"] == 0, part["rental_deposit_cents"]
    assert part["concurrent_rental_capacity"] is None, (
        f"null and zero are not interchangeable here, got "
        f"{part['concurrent_rental_capacity']}"
    )
    assert part["requires_authentication"] is False, part["requires_authentication"]
    assert part["requires_calibration"] is False, part["requires_calibration"]
    assert part["supersedes_part_id"] is None, part["supersedes_part_id"]
    assert part["status"] == "DRAFT", part["status"]


def test_creating_an_obligation_rolls_the_parent_model_up_in_the_same_request():
    """PRD §3.2: "On creation the obligation's mandated window is computed, its initial
    `status` is derived, the parent model's posture is rolled up, `breach_count` starts
    at zero, `documentation_verified` starts false, and `last_attested_at` and
    `last_attested_by_user_id` start null."
    PRD §3.2: "If the model has no `end_of_production_date`, the obligation's
    `deadline_basis` is `PRODUCTION_ACTIVE` and both `parts_available_until` and
    `documentation_available_until` are null — the clock has not started."
    PRD §3.2: "Alongside the posture, `open_obligation_count` is set to the number of
    the model's obligations whose status is `OPEN`, `AT_RISK`, or `ATTESTED`."

    Design: Corner/entities/model_open_obligation_count_and_posture_are_derived_from_children
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={"model_code": "CRX-E103", "product_family": "CRX"},
        part_overrides={"sku": "SKU-E103-A"},
        safety_warning_count=2,
    )
    assert setup["model"]["documentation_posture"] == "CURRENT", (
        setup["model"]["documentation_posture"]
    )

    response = api_client.create_compliance_obligation(
        factories.compliance_obligation_payload(setup["model"]["id"], "US-CA"), COMPLIANCE
    )
    obligation = validate_success(response, 201)

    assert obligation["deadline_basis"] == "PRODUCTION_ACTIVE", (
        obligation["deadline_basis"]
    )
    assert obligation["parts_available_until"] is None, obligation["parts_available_until"]
    assert obligation["documentation_available_until"] is None, (
        obligation["documentation_available_until"]
    )
    assert obligation["status"] == "OPEN", obligation["status"]
    assert obligation["breach_count"] == 0, obligation["breach_count"]
    assert obligation["documentation_verified"] is False, (
        obligation["documentation_verified"]
    )
    assert obligation["last_attested_at"] is None, obligation["last_attested_at"]

    model = validate_success(
        api_client.get_product_model(setup["model"]["id"], COMPLIANCE), 200
    )
    assert model["open_obligation_count"] == 1, (
        f"the create rolled the parent up with no sweep, got "
        f"{model['open_obligation_count']}"
    )
    assert model["compliance_posture"] == "OPEN", model["compliance_posture"]


def test_server_owned_catalog_fields_cannot_be_supplied_by_the_client():
    """PRD §2.9: "**Structural validity** — malformed body, missing required field,
    wrong JSON type, out-of-set enum value, or an unknown field
    (`ERR_INVALID_REQUEST`); then numeric range (`ERR_INVALID_RANGE`); then inverted
    intervals (`ERR_INVALID_DATE_RANGE`); then natural-key uniqueness
    (`ERR_DUPLICATE_NATURAL_KEY`)."
    PRD §3.3: "A new catalog item is born in `DRAFT` with `restriction_reason` null and
    all four core-ledger aggregates — `core_face_value_committed_cents`,
    `core_liability_outstanding_cents`, `core_credit_settled_cents`, and
    `core_credit_forfeited_cents` — at zero."

    Design: Corner/entities/part_catalog_item_client_supplied_system_field_input_ignored
    """
    body = {
        "sku": "SKU-E104-SYS",
        "part_class": "COMPONENT",
        "safety_class": "UNRESTRICTED",
        "list_price_cents": 500,
        "core_return_required": False,
    }
    response = api_client.create_part_catalog_item(
        dict(body, status="PUBLISHED", core_liability_outstanding_cents=9999), ADMIN
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api_client.list_part_catalog_items(ADMIN, params={"status": "PUBLISHED"})
    )
    assert meta["total_count"] == 0, (
        f"no published row may exist after the refusal, got {meta['total_count']}"
    )

    part = validate_success(api_client.create_part_catalog_item(body, ADMIN), 201)
    assert part["status"] == "DRAFT", part["status"]
    assert part["version"] == 1, part["version"]
    assert part["core_liability_outstanding_cents"] == 0, (
        part["core_liability_outstanding_cents"]
    )


def test_out_of_set_repairability_tier_is_a_structural_failure_not_a_range_failure():
    """PRD §3.1: "A `ProgramAdmin` registers one by supplying a `model_code` — the
    manufacturer's code, globally unique and between 3 and 32 characters — a
    `product_family` naming the marketing family, a `market_release_date` giving first
    retail availability, and a `repairability_tier`, which is one of
    `TIER_A_SELF_SERVICE`, `TIER_B_GUIDED`, `TIER_C_AUTHORIZED_ONLY`, or
    `TIER_D_NON_SERVICEABLE`."
    PRD §2.9: "**Structural validity** — malformed body, missing required field, wrong
    JSON type, out-of-set enum value, or an unknown field (`ERR_INVALID_REQUEST`);
    then numeric range (`ERR_INVALID_RANGE`); then inverted intervals
    (`ERR_INVALID_DATE_RANGE`); then natural-key uniqueness
    (`ERR_DUPLICATE_NATURAL_KEY`)."

    Design: Corner/entities/unknown_repairability_tier_enum_value_is_rejected
    """
    response = api_client.create_product_model(
        {
            "model_code": "CRX-E105",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_E_MYSTERY",
        },
        ADMIN,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)


def test_disclosure_acknowledgment_is_stored_without_a_version_or_updated_at():
    """PRD §2.4: "There is one deliberate exception: a `DisclosureAcknowledgment` is an
    append-only legal record."
    PRD §2.4: "It carries only `id` and `created_at`; it has no `updated_at` and no
    `version`, and no endpoint updates it after creation."
    PRD §3.6: "The stored record captures `acknowledged_by_user_id` from the caller's
    `X-User-ID`, which must equal the order's `customer_user_id`;
    `manual_revision_number`, copied from the order's pinned revision number at
    signature time; and `acknowledged_at`, the logical-clock instant of signature."

    Design: Corner/entities/disclosure_acknowledgment_is_immutable_and_versionless
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={"model_code": "CRX-E106", "product_family": "CRX"},
        part_overrides={"sku": "SKU-E106-A"},
        safety_warning_count=2,
    )
    bundle = fixtures.build_pending_disclosure_order(setup, 1, CUSTOMER)
    order_id = bundle["order"]["id"]

    assessment = fixtures.read_assessment(bundle["assessment"]["id"], CUSTOMER)
    assert assessment["liability_warning_version"] == "LW-CRX-E106-R1", (
        assessment["liability_warning_version"]
    )

    created = validate_success(
        api_client.create_acknowledgment(
            order_id,
            factories.acknowledgment_payload(
                bundle["order"]["warranty_impact_class"],
                assessment["liability_warning_version"],
                "FULL_SELF_REPAIR",
            ),
            CUSTOMER,
        ),
        201,
    )
    acknowledgment = validate_success(
        api_client.get_disclosure_acknowledgment(created["id"], COMPLIANCE), 200
    )

    assert "version" not in acknowledgment, (
        f"an append-only record carries no version, got {acknowledgment.get('version')}"
    )
    assert "updated_at" not in acknowledgment, (
        f"an append-only record carries no updated_at, got "
        f"{acknowledgment.get('updated_at')}"
    )
    assert acknowledgment["acknowledged_by_user_id"] == "user_customer_001", (
        acknowledgment["acknowledged_by_user_id"]
    )
    assert acknowledgment["manual_revision_number"] == 1, (
        acknowledgment["manual_revision_number"]
    )
    assert acknowledgment["acknowledged_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the logical-clock instant of signature, got "
        f"{acknowledgment['acknowledged_at']}"
    )

    order = fixtures.read_order(order_id)
    assert order["disclosure_acknowledged_at"].startswith("2026-08-01T00:00:00"), (
        order["disclosure_acknowledged_at"]
    )


def test_compatibility_row_against_an_unstored_model_is_a_model_not_found():
    """PRD §2.8: "The same codes apply when the identifier arrives in a request body
    rather than in the path — an unknown `supersedes_part_id` or
    `required_tool_part_id` is an `ERR_PART_NOT_FOUND`, an unknown `order_line_id` on
    a defective-return filing is an `ERR_ORDER_LINE_NOT_FOUND`, and an unknown
    `provider_id` in a body is an `ERR_PROVIDER_NOT_FOUND`."
    PRD §2.8: "All twelve are 404 responses."

    Design: Corner/entities/compatibility_against_unknown_model_returns_not_found
    """
    part = fixtures.create_part(sku="SKU-E107-A")

    response = api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            part["id"],
            UNSTORED_PART_ID,
            effective_from="2026-01-01T00:00:00Z",
            install_minutes=20,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_MODEL_NOT_FOUND", 404)

    _, meta = validate_paginated(api_client.list_part_compatibilities(ADMIN))
    assert meta["total_count"] == 0, (
        f"no dangling junction row may be stored, got {meta['total_count']}"
    )


def test_compatibility_junction_is_reachable_from_the_model_the_part_and_the_tool():
    """PRD §2.3: "Compatibility listings filter on `part_id`, `model_id`,
    `required_tool_part_id`, `self_service_eligible`, and `as_of_date`; the
    model-scoped and part-scoped compatibility reads accept the same `as_of_date`
    filter to ask which fitment row was in force at a chosen instant."
    PRD §3.3: "`superseded_by_safety_restriction` starts false."

    Design: Corner/entities/compatibility_junction_is_readable_from_both_sides
    """
    model = fixtures.create_model(model_code="CRX-E108", product_family="CRX")
    component = fixtures.create_part(sku="SKU-E108-C", list_price_cents=1500)
    tool = fixtures.create_part(sku="SKU-E108-T", part_class="TOOL", list_price_cents=900)
    compatibility = fixtures.create_compatibility(
        component["id"],
        model["id"],
        effective_from="2025-02-01T00:00:00Z",
        install_minutes=20,
        required_tool_part_id=tool["id"],
    )

    from_model, _ = validate_paginated(
        api_client.list_model_part_compatibilities(model["id"], ADMIN)
    )
    from_part, _ = validate_paginated(
        api_client.list_compatibilities_for_part(component["id"], ADMIN)
    )
    by_tool, _ = validate_paginated(
        api_client.list_part_compatibilities(
            ADMIN, params={"required_tool_part_id": tool["id"]}
        )
    )
    for label, rows in (
        ("model-scoped", from_model),
        ("part-scoped", from_part),
        ("tool-filtered", by_tool),
    ):
        assert [row["id"] for row in rows] == [compatibility["id"]], (
            f"the {label} read must return exactly the one junction row, got {rows}"
        )

    row = validate_success(
        api_client.get_part_compatibility(compatibility["id"], ADMIN), 200
    )
    assert row["required_tool_part_id"] == tool["id"], row["required_tool_part_id"]
    assert row["superseded_by_safety_restriction"] is False, (
        row["superseded_by_safety_restriction"]
    )


def test_repointing_supersession_back_onto_a_successor_closes_a_cycle():
    """PRD §3.3: "Both at creation and at re-pointing, the supersession graph is
    policed: a chain that would close a cycle — where the referenced part transitively
    supersedes the part being created or re-pointed, or is that same part — is refused
    with `ERR_SUPERSESSION_CYCLE`, and a successor whose `part_class` differs from its
    predecessor's is refused with `ERR_SUPERSESSION_CLASS_MISMATCH`."

    Design: Corner/entities/supersession_repoint_that_closes_a_cycle_is_rejected
    """
    part_a = fixtures.create_part(sku="SKU-E109-A", list_price_cents=1000)
    fixtures.publish_part(part_a["id"])
    part_b = fixtures.create_part(
        sku="SKU-E109-B", list_price_cents=1100, supersedes_part_id=part_a["id"]
    )

    response = api_client.repoint_supersession(
        part_a["id"],
        factories.supersession_payload(
            part_b["id"], supersession_note="attempted swap-back"
        ),
        ADMIN,
    )
    validate_error(response, "ERR_SUPERSESSION_CYCLE", 422)

    assert fixtures.read_part(part_a["id"])["supersedes_part_id"] is None, (
        "the refused re-point must leave the predecessor edge unset"
    )
    assert fixtures.read_part(part_b["id"])["supersedes_part_id"] == part_a["id"], (
        "the existing edge must survive the refusal"
    )

    successors, _ = validate_paginated(
        api_client.list_part_successors(part_a["id"], ADMIN)
    )
    assert [row["id"] for row in successors] == [part_b["id"]], (
        f"Expected only the original successor, got {successors}"
    )


def test_successor_of_a_different_part_class_is_refused():
    """PRD §3.3: "Both at creation and at re-pointing, the supersession graph is
    policed: a chain that would close a cycle — where the referenced part transitively
    supersedes the part being created or re-pointed, or is that same part — is refused
    with `ERR_SUPERSESSION_CYCLE`, and a successor whose `part_class` differs from its
    predecessor's is refused with `ERR_SUPERSESSION_CLASS_MISMATCH`."
    PRD §3.3: "Where the newly published part declares a `supersedes_part_id`, that
    predecessor moves from `PUBLISHED` to `SUPERSEDED` in the same request."

    Design: Corner/entities/successor_declaring_a_different_part_class_is_rejected
    """
    predecessor = fixtures.create_part(sku="SKU-E110-COMP", list_price_cents=1000)
    fixtures.publish_part(predecessor["id"])

    response = api_client.create_part_catalog_item(
        factories.part_catalog_item_payload(
            sku="SKU-E110-TOOL",
            part_class="TOOL",
            list_price_cents=1200,
            supersedes_part_id=predecessor["id"],
        ),
        ADMIN,
    )
    validate_error(response, "ERR_SUPERSESSION_CLASS_MISMATCH", 422)

    assert fixtures.read_part(predecessor["id"])["status"] == "PUBLISHED", (
        "no supersession side effect may run behind a refused create"
    )
    rows, meta = validate_paginated(
        api_client.list_part_catalog_items(ADMIN, params={"part_class": "TOOL"})
    )
    assert meta["total_count"] == 0, (
        f"the refused tool must not be stored, got {[row['sku'] for row in rows]}"
    )
