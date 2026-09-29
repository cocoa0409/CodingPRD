"""What the server mints, defaults and derives when a row is first written, and what
the single-resource read gives back afterwards.
"""

from test_helpers import (
    AirHandlingClass,
    ApiErrorId,
    AssayMethod,
    DocType,
    GlutenContainingOperations,
    MarkTier,
    NON_EXISTENT_UUID,
    RiskClass,
    create_applicant,
    create_facility,
    create_ingredient,
    create_product,
    create_supplier,
    link_ingredient,
    make_admin_headers,
    make_applicant_contact_headers,
    make_auditor_headers,
    make_decision_maker_headers,
    make_reviewer_headers,
    read_ingredient,
    read_product,
    read_supplier,
    set_clock,
    setup_applicant_with_facility,
    validate_error,
    validate_paginated,
    validate_success,
    validate_sanitation,
)

CLOCK_START = "2026-08-01T00:00:00Z"
SANITATION_DAY = "2026-08-03T00:00:00Z"
UUID_PATTERN_LENGTH = 36


def test_a_freshly_registered_applicant_carries_every_counter_at_its_default(api):
    """The 201 body already holds both posture scores at 100, the band at
    GOOD_STANDING, every counter at 0 and a null cycle opening.

    PRD: "A freshly registered applicant starts in the cleanest possible position:
    `compliance_posture` is `GOOD_STANDING`, `open_nc_penalty_points` is 0,
    `active_certified_product_count`, `suspended_certificate_count` and
    `revoked_certificate_count` are all 0, `fee_balance_cents` is 0, both
    `posture_score_rolling_12m` and `posture_score_cycle` are 100, and
    `current_cycle_started_on` is null because no certificate has ever been issued to
    them."
    PRD: "Every resource the service persists carries a server-minted `id` in canonical
    UUID form with no type prefix and no client influence over its value, together with
    a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional
    digits."

    Design: Corner/entities/applicant_creation_materialises_every_computed_default
    """
    set_clock(api, CLOCK_START)
    response = api.create_applicant(
        make_admin_headers(),
        legal_name="Northgate Bakehouse Ltd",
        contact_email="qa@northgate.example",
        country_code="US",
    )
    assert response.status_code == 201, response.text
    row = validate_success(response, 201)

    assert row["legal_name"] == "Northgate Bakehouse Ltd"
    assert row["contact_email"] == "qa@northgate.example"
    assert row["country_code"] == "US"
    assert row["version"] == 1
    assert len(row["id"]) == UUID_PATTERN_LENGTH and row["id"].count("-") == 4
    assert row["created_at"].endswith("Z")
    assert row["updated_at"].endswith("Z")

    assert row["current_cycle_started_on"] is None
    assert row["open_nc_penalty_points"] == 0
    assert row["active_certified_product_count"] == 0
    assert row["suspended_certificate_count"] == 0
    assert row["revoked_certificate_count"] == 0
    assert row["substantiated_complaint_count_rolling"] == 0
    assert row["substantiated_complaint_count_cycle"] == 0
    assert row["posture_score_rolling_12m"] == 100
    assert row["posture_score_cycle"] == 100
    assert row["compliance_posture"] == "GOOD_STANDING"
    assert row["fee_balance_cents"] == 0


def test_a_site_declared_without_its_two_optional_flags_takes_the_declared_defaults(api):
    """Omitting `shared_equipment_present` and `gluten_containing_operations` yields
    false and NONE rather than nulls, and every system dimension starts empty.

    PRD: "Two further declarations describe how close the site runs to gluten:
    `shared_equipment_present`, a boolean defaulting to false that is true when at least
    one production line also runs gluten-containing product, and
    `gluten_containing_operations`, defaulting to `NONE` and otherwise `ADJACENT_LINES`
    or `SAME_LINE`, describing the degree of physical co-location."
    PRD: "A new site begins with `sanitation_validation_status` of `UNVALIDATED`, with
    `sanitation_method`, `sanitation_swab_ppm`, `sanitation_validated_on` and
    `sanitation_expires_on` all null, and with `last_closed_audit_outcome` of `NONE` and
    `last_closed_audit_closed_on` null."

    Design: Corner/entities/facility_creation_applies_declared_defaults_for_omitted_optional_inputs
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api)

    response = api.create_facility(
        make_applicant_contact_headers(applicant["id"]),
        applicant_id=applicant["id"],
        site_name="Plant 1",
        air_handling_class=AirHandlingClass.OPEN_PLENUM,
    )
    assert response.status_code == 201, response.text
    row = validate_success(response, 201)

    assert row["applicant_id"] == applicant["id"]
    assert row["site_name"] == "Plant 1"
    assert row["air_handling_class"] == "OPEN_PLENUM"
    assert row["shared_equipment_present"] is False
    assert row["gluten_containing_operations"] == "NONE"
    assert row["sanitation_validation_status"] == "UNVALIDATED"
    assert row["sanitation_method"] is None
    assert row["sanitation_swab_ppm"] is None
    assert row["sanitation_validated_on"] is None
    assert row["sanitation_expires_on"] is None
    assert row["last_closed_audit_outcome"] == "NONE"
    assert row["last_closed_audit_closed_on"] is None
    assert row["version"] == 1


def test_the_facility_read_returns_the_swab_snapshot_the_validation_stored(api):
    """The read gives back the submitted ppm and method verbatim together with the
    expiry the action derived, and it does not move the row.

    PRD: "On acceptance the facility copies the submitted values into
    `sanitation_swab_ppm`, `sanitation_method` and `sanitation_validated_on`, sets
    `sanitation_expires_on` to 365 days after `validated_on`, and moves
    `sanitation_validation_status` to `VALIDATED`."
    PRD: "Reads never mutate."

    Design: Corner/entities/facility_get_by_id_returns_the_stored_row_including_the_sanitation_snapshot
    """
    set_clock(api, SANITATION_DAY)
    applicant = create_applicant(api)
    facility = create_facility(
        api,
        applicant["id"],
        site_name="Plant 4",
        air_handling_class=AirHandlingClass.FILTERED_ZONED,
        shared_equipment_present=True,
        gluten_containing_operations=GlutenContainingOperations.ADJACENT_LINES,
    )
    validated = validate_sanitation(
        api,
        facility["id"],
        swab_ppm=4.5,
        method=AssayMethod.G12_ELISA,
        validated_on=SANITATION_DAY,
    )

    response = api.get_facility(facility["id"], make_decision_maker_headers("dm-1"))
    assert response.status_code == 200, response.text
    row = validate_success(response)

    assert row["id"] == facility["id"]
    assert row["site_name"] == "Plant 4"
    assert row["shared_equipment_present"] is True
    assert row["gluten_containing_operations"] == "ADJACENT_LINES"
    assert row["sanitation_validation_status"] == "VALIDATED"
    assert row["sanitation_swab_ppm"] == 4.5
    assert row["sanitation_method"] == "G12_ELISA"
    assert row["sanitation_validated_on"] == SANITATION_DAY
    assert row["sanitation_expires_on"] == "2027-08-03T00:00:00Z"
    assert row["version"] == validated["version"]


def test_the_ingredient_page_reports_the_filtered_total_not_the_page_length(api):
    """Three ingredients under one applicant read back two rows with total_count 3 and
    has_more true, and the other applicant's row never appears.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as they were
    resolved for the request, `total_count` as the number of rows matching the filters
    before pagination, and `has_more` as a boolean that is true when rows remain beyond
    the current page."
    PRD: "Beyond `limit` and `offset`, each collection accepts a small set of optional
    equality filters, and supplying several of them narrows the result by all of them at
    once."

    Design: Corner/entities/ingredient_list_reports_total_count_and_has_more_across_the_page_boundary
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api)
    other = create_applicant(
        api, legal_name="Southbank Snacks Inc", contact_email="qa@southbank.example"
    )
    supplier = create_supplier(api)

    for name, risk_class in (
        ("Brown Rice Flour", RiskClass.INHERENTLY_GF),
        ("Tapioca Starch", RiskClass.INHERENTLY_GF),
        ("Oat Groats", RiskClass.HIGH_RISK_GRAIN),
    ):
        create_ingredient(
            api, applicant["id"], supplier["id"], name=name, risk_class=risk_class
        )
    outsider = create_ingredient(
        api,
        other["id"],
        supplier["id"],
        name="Potato Starch",
        risk_class=RiskClass.INHERENTLY_GF,
    )

    rows, meta = validate_paginated(
        api.list_ingredients(
            make_reviewer_headers("rev-1"),
            applicant_id=applicant["id"],
            limit=2,
            offset=0,
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert all(row["applicant_id"] == applicant["id"] for row in rows)
    assert outsider["id"] not in [row["id"] for row in rows]


def test_a_product_declared_without_a_sku_is_a_body_shape_rejection(api):
    """`sku` is required where `requested_mark_tier` is optional, so omitting it is a
    400 and leaves the applicant with no product at all.

    PRD: "**Request shape.** On every write endpoint, each non-optional input field is
    present, each enum-typed field carries one of its declared values, `inclusion_pct` is
    greater than 0 and at most 100, `ppm_result` and `swab_ppm` are at least 0,
    `onsite_end_at` is strictly after `onsite_start_at`, and every datetime is a
    well-formed ISO 8601 value with a `Z` offset."
    PRD: "The applicant also states `requested_mark_tier`, which defaults to `STANDARD`
    and may instead be `PREMIUM` or `ELITE`; that request caps the certified threshold, so
    a company asking for the strictest mark is asking for the strictest number."

    Design: Corner/entities/product_creation_missing_the_required_sku_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)

    response = api.create_product(
        make_applicant_contact_headers(context.applicant_id),
        applicant_id=context.applicant_id,
        facility_id=context.facility_id,
        name="Rice Sandwich Loaf",
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_products(make_admin_headers(), applicant_id=context.applicant_id)
    )
    assert meta["total_count"] == 0


def test_a_formula_line_derives_its_risk_carrier_flag_from_the_ingredient(api):
    """The INHERENTLY_GF line reads false and the GF_PROCESSED line on the same product
    reads true, and the plan fields stay null because no plan has been posted.

    PRD: "On creation the line computes `is_risk_carrier`, which is true exactly when the
    referenced ingredient's `risk_class` is anything other than `INHERENTLY_GF`, evaluated
    at link-creation time and never revisited."
    PRD: "A new product opens with `formula_status` of `DRAFT`, `label_status` of
    `NOT_SUBMITTED`, `testing_plan_status` of `NONE`, `testing_plan_revision` of 0,
    `mark_tier_granted` of `NONE`, `linked_ingredient_count` and
    `blocked_ingredient_count` of 0, `threshold_ppm` and `sampling_lots_per_year` and
    `sampling_exclusion_days` all null, and `formula_cleared_by_user_id`,
    `label_reviewed_by_user_id`, `label_rejection_reason` and `last_scheduled_sample_on`
    all null."

    Design: Corner/entities/product_ingredient_link_computes_is_risk_carrier_and_the_parent_line_count
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api)
    safe = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    risky = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Modified Corn Starch",
        risk_class=RiskClass.GF_PROCESSED,
    )
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
        requested_mark_tier=MarkTier.STANDARD,
    )
    safe_line = link_ingredient(api, context.applicant_id, product["id"], safe["id"], 55)
    assert safe_line["is_risk_carrier"] is False

    response = api.link_product_ingredient(
        make_applicant_contact_headers(context.applicant_id),
        product_id=product["id"],
        ingredient_id=risky["id"],
        inclusion_pct=45,
    )
    assert response.status_code == 201, response.text
    risky_line = validate_success(response, 201)

    assert risky_line["product_id"] == product["id"]
    assert risky_line["ingredient_id"] == risky["id"]
    assert risky_line["inclusion_pct"] == 45
    assert risky_line["is_risk_carrier"] is True

    row = read_product(api, product["id"])
    assert row["linked_ingredient_count"] == 2
    assert row["blocked_ingredient_count"] == 0
    assert row["formula_status"] == "DRAFT"
    assert row["threshold_ppm"] is None
    assert row["sampling_lots_per_year"] is None
    assert row["testing_plan_status"] == "NONE"


def test_an_uploaded_document_is_born_pending_with_no_verification_fields(api):
    """The three verification fields are null, the supplier's verified counter is
    untouched and the ingredient's evidence list is still empty.

    PRD: "Uploaded documents begin with `status` of `PENDING` and with
    `verified_by_user_id`, `verified_on` and `rejection_reason` all null."
    PRD: "`lab_ppm_claim` is null for every non-`COA` document class."

    Design: Corner/entities/supplier_document_system_fields_are_server_minted_on_creation
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api)
    supplier = create_supplier(api)
    ingredient = create_ingredient(
        api,
        applicant["id"],
        supplier["id"],
        name="Modified Corn Starch",
        risk_class=RiskClass.GF_PROCESSED,
    )

    response = api.create_supplier_document(
        make_applicant_contact_headers(applicant["id"]),
        supplier_id=supplier["id"],
        ingredient_id=ingredient["id"],
        doc_type=DocType.PROCESS_FLOW,
        issued_on="2026-07-01T00:00:00Z",
        expires_on="2028-07-01T00:00:00Z",
    )
    assert response.status_code == 201, response.text
    row = validate_success(response, 201)

    assert row["supplier_id"] == supplier["id"]
    assert row["ingredient_id"] == ingredient["id"]
    assert row["doc_type"] == "PROCESS_FLOW"
    assert row["status"] == "PENDING"
    assert row["verified_by_user_id"] is None
    assert row["verified_on"] is None
    assert row["rejection_reason"] is None
    assert row["lab_ppm_claim"] is None
    assert row["version"] == 1
    assert len(row["id"]) == UUID_PATTERN_LENGTH

    assert read_supplier(api, supplier["id"])["verified_document_count"] == 0
    assert read_ingredient(api, ingredient["id"])["verified_doc_types"] == []


def test_an_ingredient_declared_with_an_undeclared_risk_class_is_rejected(api):
    """`risk_class` is a closed three-value enum, so MEDIUM_RISK is a 400 and no
    ingredient row survives.

    PRD: "An `ApplicantContact` declares each ingredient with the owning `applicant_id`,
    the supplying `supplier_id`, a trade `name`, and a `risk_class` of `INHERENTLY_GF`,
    `GF_PROCESSED` or `HIGH_RISK_GRAIN`."
    PRD: "Any breach is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/ingredient_creation_with_an_undeclared_risk_class_is_rejected
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api)
    supplier = create_supplier(api)

    response = api.create_ingredient(
        make_applicant_contact_headers(applicant["id"]),
        applicant_id=applicant["id"],
        supplier_id=supplier["id"],
        name="Mystery Blend",
        risk_class="MEDIUM_RISK",
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_ingredients(make_admin_headers(), applicant_id=applicant["id"])
    )
    assert meta["total_count"] == 0


def test_an_inclusion_of_one_hundred_is_accepted_but_zero_is_not(api):
    """The bound is open below and closed above: a single line at exactly 100 is stored
    and a second line at 0 is a 400 that leaves the line count at 1.

    PRD: "Each line names the `product_id` and the `ingredient_id` it consumes, together
    with `inclusion_pct`, the percentage of finished-product mass that ingredient
    contributes, which must be greater than 0 and at most 100."

    Design: Corner/entities/product_ingredient_inclusion_pct_of_zero_is_rejected_at_the_open_bound
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api)
    first = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    second = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Tapioca Starch",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    product = create_product(
        api, context.applicant_id, context.facility_id, name="Rice Sandwich Loaf", sku="RSL-001"
    )
    full_line = link_ingredient(api, context.applicant_id, product["id"], first["id"], 100)
    assert full_line["inclusion_pct"] == 100

    response = api.link_product_ingredient(
        make_applicant_contact_headers(context.applicant_id),
        product_id=product["id"],
        ingredient_id=second["id"],
        inclusion_pct=0,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    assert read_product(api, product["id"])["linked_ingredient_count"] == 1
    _rows, meta = validate_paginated(
        api.list_product_ingredients(make_admin_headers(), product_id=product["id"])
    )
    assert meta["total_count"] == 1


def test_a_formula_line_carries_no_version_and_no_updated_at(api):
    """The junction row is the one lean resource: it reads back with its four business
    fields and `created_at`, and neither `version` nor `updated_at`.

    PRD: "A product-to-ingredient formula line is immutable once written: it carries only
    `id` and `created_at`, and it has neither `updated_at` nor `version`."
    PRD: "There is no endpoint that edits or removes such a line, so a formula is
    corrected by adding lines rather than by rewriting them, and the recomputed counters
    on the owning product are the only observable consequence of a new line."

    Design: Corner/entities/product_ingredient_link_is_immutable_and_carries_no_version_field
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api)
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    product = create_product(
        api, context.applicant_id, context.facility_id, name="Rice Sandwich Loaf", sku="RSL-001"
    )
    link = link_ingredient(api, context.applicant_id, product["id"], ingredient["id"], 40)

    response = api.get_product_ingredient(link["id"], make_auditor_headers("aud-1"))
    assert response.status_code == 200, response.text
    row = validate_success(response)

    assert row["id"] == link["id"]
    assert row["product_id"] == product["id"]
    assert row["ingredient_id"] == ingredient["id"]
    assert row["inclusion_pct"] == 40
    assert row["is_risk_carrier"] is False
    assert row["created_at"].endswith("Z")
    assert "version" not in row
    assert "updated_at" not in row


def test_a_site_declared_under_an_unminted_applicant_is_a_body_reference_not_found(api):
    """The applicant is named in the body rather than the path, and the refusal is still
    the applicant's own 404 code.

    PRD: "**Body reference existence.** Every foreign key carried in the request body
    resolves to a live row, checked in the order the endpoint declares its inputs, again
    returning the matching not-found code with HTTP 404."

    Design: Corner/entities/facility_creation_under_an_unknown_applicant_returns_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.create_facility(
        make_applicant_contact_headers(NON_EXISTENT_UUID),
        applicant_id=NON_EXISTENT_UUID,
        site_name="Ghost Plant",
        air_handling_class=AirHandlingClass.OPEN_PLENUM,
    )
    validate_error(response, ApiErrorId.APPLICANT_NOT_FOUND, 404)

    _rows, meta = validate_paginated(api.list_facilities(make_admin_headers()))
    assert meta["total_count"] == 0


def test_a_document_filed_by_the_wrong_supplier_for_an_ingredient_is_refused(api):
    """Both keys resolve, but they disagree, so the upload is a 422 and neither side of
    the edge records anything.

    PRD: "Because a document sits on the edge between one supplier and one ingredient, the
    referenced ingredient's own `supplier_id` must equal the `supplier_id` supplied on the
    document, or the upload is rejected with `ERR_DOCUMENT_SUPPLIER_MISMATCH`."
    PRD: "**Document matches the ingredient's supplier.** On document upload, the
    referenced ingredient's `supplier_id` equals the `supplier_id` supplied on the document
    — otherwise `ERR_DOCUMENT_SUPPLIER_MISMATCH` (422)."

    Design: Corner/entities/supplier_document_naming_an_ingredient_of_another_supplier_is_rejected
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api)
    supplier_a = create_supplier(api, name="Prairie Mills", country_code="CA")
    supplier_b = create_supplier(api, name="Cascade Grain", country_code="US")
    ingredient = create_ingredient(
        api,
        applicant["id"],
        supplier_a["id"],
        name="Modified Corn Starch",
        risk_class=RiskClass.GF_PROCESSED,
    )

    response = api.create_supplier_document(
        make_applicant_contact_headers(applicant["id"]),
        supplier_id=supplier_b["id"],
        ingredient_id=ingredient["id"],
        doc_type=DocType.ALLERGEN_STATEMENT,
        issued_on="2026-07-01T00:00:00Z",
        expires_on="2028-07-01T00:00:00Z",
    )
    validate_error(response, ApiErrorId.DOCUMENT_SUPPLIER_MISMATCH, 422)

    _by_supplier, supplier_meta = validate_paginated(
        api.list_supplier_documents(make_admin_headers(), supplier_id=supplier_b["id"])
    )
    assert supplier_meta["total_count"] == 0
    _by_ingredient, ingredient_meta = validate_paginated(
        api.list_supplier_documents(make_admin_headers(), ingredient_id=ingredient["id"])
    )
    assert ingredient_meta["total_count"] == 0
    assert read_supplier(api, supplier_b["id"])["verified_document_count"] == 0
    assert read_ingredient(api, ingredient["id"])["verified_doc_types"] == []


def test_one_ingredient_carries_two_products_at_two_inclusion_percentages(api):
    """The duplicate guard is scoped to the pair, so the same ingredient links into a
    second product, and each product counts only its own line.

    PRD: "A line may not duplicate an existing pairing of the same `product_id` and
    `ingredient_id` (`ERR_DUPLICATE_PRODUCT_INGREDIENT`); the ingredient may not be in
    `REJECTED` state (`ERR_INVALID_INGREDIENT_STATE`); the ingredient's supplier may not be
    `SUSPENDED` (`ERR_SUPPLIER_SUSPENDED`); and the product's `formula_status` must be
    `DRAFT` or `REJECTED` (`ERR_INVALID_PRODUCT_STATE`), because a formula may not be
    edited under or after clearance."
    PRD: "Creating a line then recomputes the product's `linked_ingredient_count` and
    `blocked_ingredient_count`."

    Design: Corner/entities/one_ingredient_links_into_two_products_through_the_junction_entity
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api)
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    first = create_product(
        api, context.applicant_id, context.facility_id, name="Rice Sandwich Loaf", sku="RSL-001"
    )
    second = create_product(
        api, context.applicant_id, context.facility_id, name="Rice Dinner Roll", sku="RDR-002"
    )
    link_ingredient(api, context.applicant_id, first["id"], ingredient["id"], 55)

    response = api.link_product_ingredient(
        make_applicant_contact_headers(context.applicant_id),
        product_id=second["id"],
        ingredient_id=ingredient["id"],
        inclusion_pct=30,
    )
    assert response.status_code == 201, response.text
    row = validate_success(response, 201)

    assert row["product_id"] == second["id"]
    assert row["ingredient_id"] == ingredient["id"]
    assert row["inclusion_pct"] == 30
    assert read_product(api, first["id"])["linked_ingredient_count"] == 1
    assert read_product(api, second["id"])["linked_ingredient_count"] == 1

    _shared, shared_meta = validate_paginated(
        api.list_product_ingredients(make_admin_headers(), ingredient_id=ingredient["id"])
    )
    assert shared_meta["total_count"] == 2
    _own, own_meta = validate_paginated(
        api.list_product_ingredients(make_admin_headers(), product_id=second["id"])
    )
    assert own_meta["total_count"] == 1


def test_a_compound_parent_belonging_to_another_applicant_is_refused(api):
    """The legal two-level chain inside one applicant is accepted; hanging a second
    applicant's ingredient under it is the graph refusal.

    PRD: "That parent must belong to the same `applicant_id` and must not close a loop in
    the parent chain — an ingredient cannot be its own ancestor, and it must never equal
    the row's own identifier — or the declaration is refused with
    `ERR_INGREDIENT_GRAPH_CYCLE`."
    PRD: "A new ingredient starts with `status` of `DRAFT`, `review_cycle_count` of 0,
    `verified_doc_types` as an empty list, and `blocked_reason`, `rejection_reason`,
    `reviewed_by_user_id` and `approved_on` all null."

    Design: Corner/entities/compound_ingredient_parent_from_another_applicant_is_rejected
    """
    set_clock(api, CLOCK_START)
    northgate = create_applicant(api)
    southbank = create_applicant(
        api, legal_name="Southbank Snacks Inc", contact_email="qa@southbank.example"
    )
    supplier = create_supplier(api)

    sub_component = create_ingredient(
        api,
        northgate["id"],
        supplier["id"],
        name="Rice Bran Sub-Component",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    compound = create_ingredient(
        api,
        northgate["id"],
        supplier["id"],
        name="Rice Blend Compound",
        risk_class=RiskClass.GF_PROCESSED,
        parent_ingredient_id=sub_component["id"],
    )
    assert compound["parent_ingredient_id"] == sub_component["id"]

    response = api.create_ingredient(
        make_applicant_contact_headers(southbank["id"]),
        applicant_id=southbank["id"],
        supplier_id=supplier["id"],
        name="Borrowed Blend",
        risk_class=RiskClass.GF_PROCESSED,
        parent_ingredient_id=sub_component["id"],
    )
    validate_error(response, ApiErrorId.INGREDIENT_GRAPH_CYCLE, 422)

    assert read_ingredient(api, compound["id"])["status"] == "DRAFT"
    _rows, meta = validate_paginated(
        api.list_ingredients(make_admin_headers(), applicant_id=southbank["id"])
    )
    assert meta["total_count"] == 0
    _children, child_meta = validate_paginated(
        api.list_ingredients(make_admin_headers(), parent_ingredient_id=sub_component["id"])
    )
    assert child_meta["total_count"] == 1
