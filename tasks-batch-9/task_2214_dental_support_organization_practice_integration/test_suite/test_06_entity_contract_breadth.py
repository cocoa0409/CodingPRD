"""Entity-contract breadth: declared defaults, server-minted system fields,
derived fields at creation, the two version-less child rows, and the 404/400
answers the request gauntlet gives before any business rule runs."""

from test_helpers import (
    COUNSEL,
    FINANCE,
    LEAD,
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    assert_affiliation,
    assert_conversion_vendor,
    assert_practice,
    assert_success_envelope_meta,
    build_closed_deal,
    build_priced_contract,
    create_affiliation,
    create_affiliation_payload,
    create_conversion_vendor,
    create_doctor_employment_payload,
    create_doctor_payload,
    create_practice,
    create_payer_enrollment_payload,
    create_service_agreement_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_opening_a_transaction_file_seeds_every_declared_default():
    """PRD §3.1: "A newly opened file begins in `DRAFT` with `repricing_round` and `practice_count` at zero, `earnout_reserved_cents` and `earnout_settled_cents` at zero, `earnout_unallocated_cents` equal to the whole `earnout_pool_cents`, `earnout_measurement_state` at `NOT_OPEN`, and `diligence_opened_at`, `signed_date` and `close_date` all still empty."
    PRD §2.4: "- `version` (integer): an integer that increments by one on every mutation of the row."

    Design: Corner/entities/affiliation_creation_returns_all_declared_fields
    """
    response = api_client.create_affiliation(create_affiliation_payload(), COUNSEL)
    affiliation = validate_success(response, expected_status=201)
    body = response.json()
    assert body["response_type"] == "object"
    assert_success_envelope_meta(body["meta"])

    assert_affiliation(affiliation)
    assert is_valid_uuid(affiliation["id"])
    assert affiliation["status"] == "DRAFT"
    assert affiliation["earnout_measurement_state"] == "NOT_OPEN"
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert affiliation["earnout_reserved_cents"] == 0
    assert affiliation["earnout_settled_cents"] == 0
    assert affiliation["repricing_round"] == 0
    assert affiliation["practice_count"] == 0
    assert affiliation["version"] == 1
    assert affiliation["diligence_opened_at"] is None
    assert affiliation["signed_date"] is None
    assert affiliation["close_date"] is None


def test_reading_the_file_echoes_the_stored_figures():
    """PRD §3.1: "The two baseline figures are recorded at origination and never change: the EBITDA baseline is the yardstick every earn-out measurement is compared against, while the net-collections baseline is retained as the deal's collections reference."
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

    Design: Corner/entities/affiliation_retrieval_returns_stored_entity
    """
    created = create_affiliation()
    read = validate_success(api_client.get_affiliation(created["id"], FINANCE))

    assert read["id"] == created["id"]
    assert read["purchase_price_cents"] == 450_000_000
    assert read["baseline_ebitda_cents"] == 90_000_000
    assert read["baseline_net_collections_cents"] == 400_000_000
    assert read["status"] == "DRAFT"
    assert read["version"] == 1


def test_practice_listing_filters_by_affiliation_and_pages():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object; `total_count` counts the rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the current page."
    PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order."

    Design: Corner/entities/practice_listing_filtered_and_paginated
    """
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    first = create_practice(affiliation["id"], vendor["id"])
    second = create_practice(
        affiliation["id"],
        vendor["id"],
        name="Oak Park Dental",
        charts_total_expected=4000,
    )

    page_one, meta_one = validate_paginated(
        api_client.list_practices(
            LEAD, {"affiliation_id": affiliation["id"], "limit": 1, "offset": 0}
        )
    )
    assert [row["id"] for row in page_one] == [first["id"]]
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api_client.list_practices(
            LEAD, {"affiliation_id": affiliation["id"], "limit": 1, "offset": 1}
        )
    )
    assert [row["id"] for row in page_two] == [second["id"]]
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False

    reread = validate_success(api_client.get_affiliation(affiliation["id"], COUNSEL))
    assert reread["practice_count"] == 2


def test_unknown_affiliation_identifier_returns_its_own_not_found():
    """PRD §2.11: "4. Path-resource existence, resolved left to right — the entity's 404 code."
    PRD §2.10: "Templated path segments are resolved strictly left to right, and the first segment that does not name an existing row terminates the request with the 404 code belonging to the entity that the collection segment names: `ERR_AFFILIATION_NOT_FOUND`, `ERR_PRACTICE_NOT_FOUND`, `ERR_DOCTOR_NOT_FOUND`, `ERR_CONVERSION_VENDOR_NOT_FOUND`, `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND`, `ERR_SERVICE_AGREEMENT_NOT_FOUND`, `ERR_MIGRATION_BATCH_NOT_FOUND`, `ERR_PAYER_CONTRACT_NOT_FOUND`, `ERR_PAYER_ENROLLMENT_NOT_FOUND`, `ERR_EARNOUT_TRANCHE_NOT_FOUND`, `ERR_SUPPLY_EXCEPTION_NOT_FOUND`, `ERR_VENDOR_CONSOLIDATION_NOT_FOUND` or `ERR_QUALITY_REVIEW_NOT_FOUND`."

    Design: Corner/entities/affiliation_not_found_for_unknown_identifier
    """
    response = api_client.get_affiliation(UNKNOWN_UUID, COUNSEL)
    validate_error(response, ApiErrorId.ERR_AFFILIATION_NOT_FOUND.value, 404)

    payload = response.json()["data"]
    assert isinstance(payload["message"], str)
    assert payload["message"] != ""


def test_missing_earnout_pool_is_a_payload_shape_failure():
    """PRD §2.11: "Every required body field must be present with its declared type; enum fields must carry a declared value; money and count fields must be integers inside their declared range; date-time fields must be ISO 8601 UTC; `monthly_collections_cents` must hold exactly twelve entries; `measurement_end` must be strictly after `measurement_start`; `cutover_end_at` must be strictly after `cutover_start_at`; `term_date`, when supplied, must be strictly after `effective_date`; and pagination must satisfy §2.3."
    PRD §2.11: "The first check whose condition is violated determines the response, no later check is evaluated, and **no state change whatsoever is written** when any check fires."

    Design: Corner/entities/affiliation_missing_required_earnout_pool_rejected
    """
    payload = create_affiliation_payload()
    payload.pop("earnout_pool_cents")

    validate_error(
        api_client.create_affiliation(payload, COUNSEL),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    rows, meta = validate_paginated(api_client.list_affiliations(COUNSEL))
    assert meta["total_count"] == 0
    assert rows == []


def test_omitted_comp_model_takes_the_declared_default():
    """PRD §3.1: "An optional `comp_model` selects the contractual compensation variant and defaults to `MONTHLY_MIN_GUARANTEE`; the alternative is `ANNUAL_TRUE_UP`."
    PRD §3.1: "A fresh offer begins with `employment_status` at `OFFERED` and `offer_accepted` false, with `credentialing_status` at `PENDING`, `records_custody_state` at `HELD_BY_PRACTICE` and `non_compete_enforcement_state` at `NOT_APPLICABLE`, with `is_harmonized` false and `harmonized_annual_comp_cents`, `harmonization_delta_cents`, `comp_effective_date`, `non_compete_end_date`, `separation_date` and `separation_reason` all still empty."

    Design: Corner/entities/doctor_employment_comp_model_default_applied
    """
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    practice = create_practice(affiliation["id"], vendor["id"])

    doctor_payload = create_doctor_payload()
    doctor_payload.pop("specialty")
    doctor_payload.pop("is_seller_owner")
    doctor = validate_success(
        api_client.create_doctor(doctor_payload, LEAD), expected_status=201
    )
    assert doctor["specialty"] == "GENERAL"
    assert doctor["is_seller_owner"] is False

    employment_payload = create_doctor_employment_payload(practice["id"], doctor["id"])
    employment_payload.pop("comp_model")
    employment = validate_success(
        api_client.create_doctor_employment(employment_payload, LEAD),
        expected_status=201,
    )

    assert employment["comp_model"] == "MONTHLY_MIN_GUARANTEE"
    assert employment["employment_status"] == "OFFERED"
    assert employment["offer_accepted"] is False
    assert employment["credentialing_status"] == "PENDING"
    assert employment["records_custody_state"] == "HELD_BY_PRACTICE"
    assert employment["non_compete_enforcement_state"] == "NOT_APPLICABLE"
    assert employment["is_harmonized"] is False
    assert employment["harmonized_annual_comp_cents"] is None


def test_new_practice_derives_its_posture_and_zeroed_counters():
    """PRD §3.1: "A new practice begins with `affiliation_status` of `PENDING`, an `integration_posture` of `PRE_CLOSE`, a `staffing_model_state` of `LEGACY`, an empty `fte_hygiene_ratio_bps`, every integration counter at zero — `active_doctor_count`, `charts_migrated_count`, `pending_credentialing_count`, `denied_enrollment_count` and `quarantined_batch_count` — and `clinical_coverage_gap` false."
    PRD §3.1: "Attaching a practice increments the affiliation's `practice_count` and its `version`."

    Design: Corner/entities/practice_computed_fields_derived_at_creation
    """
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    practice = create_practice(affiliation["id"], vendor["id"])

    assert_practice(practice)
    assert practice["affiliation_status"] == "PENDING"
    assert practice["integration_posture"] == "PRE_CLOSE"
    assert practice["active_doctor_count"] == 0
    assert practice["charts_migrated_count"] == 0
    assert practice["pending_credentialing_count"] == 0
    assert practice["denied_enrollment_count"] == 0
    assert practice["quarantined_batch_count"] == 0
    assert practice["clinical_coverage_gap"] is False
    assert practice["staffing_model_state"] == "LEGACY"
    assert practice["fte_hygiene_ratio_bps"] is None

    parent = validate_success(api_client.get_affiliation(affiliation["id"], COUNSEL))
    assert parent["practice_count"] == 1
    assert parent["version"] > affiliation["version"]


def test_vendor_system_fields_are_server_minted():
    """PRD §2.4: "- `id` (string): a server-minted UUID with no type prefix."
    PRD §3.1: "A vendor is created with a `name` and a `max_concurrent_windows` crew capacity of at least one, and its `active_window_count` starts at zero."

    Design: Corner/entities/conversion_vendor_system_fields_generated_on_create
    """
    vendor = create_conversion_vendor()

    assert_conversion_vendor(vendor)
    assert is_valid_uuid(vendor["id"])
    assert vendor["version"] == 1
    assert vendor["created_at"] == vendor["updated_at"]
    assert vendor["active_window_count"] == 0
    assert vendor["max_concurrent_windows"] == 3


def test_fee_schedule_item_carries_only_id_and_created_at():
    """PRD §2.4: "A **service line item** on a management services agreement and a **fee schedule item** on a payer contract each carry only `id` and `created_at`."
    PRD §2.4: "Both `updated_at` and `version` are absent from those two resources entirely; they are written once and never mutated."

    Design: Corner/entities/fee_schedule_item_is_immutable_and_carries_no_version
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=[{}])

    rows, meta = validate_paginated(
        api_client.list_fee_schedule_items(contract["id"], FINANCE)
    )
    assert meta["total_count"] == 1
    line = rows[0]
    assert is_valid_uuid(line["id"])
    assert isinstance(line["created_at"], str)
    assert "version" not in line
    assert "updated_at" not in line
    assert line["line_impact_cents"] == -39_195
    assert line["annual_volume"] == 100


def test_near_miss_fee_model_value_is_rejected():
    """PRD §3.2: "Creating one names the `practice_id`, selects a `fee_model` of either `PCT_OF_COLLECTIONS` or `FIXED_MONTHLY`, and sets a `mgmt_fee_bps` management fee expressed in basis points of net collections."
    PRD §2.11: "6. Payload shape — `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/service_agreement_invalid_fee_model_enum_rejected
    """
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    practice = create_practice(affiliation["id"], vendor["id"])
    validate_success(api_client.advance_diligence(affiliation["id"], COUNSEL))

    validate_error(
        api_client.create_service_agreement(
            create_service_agreement_payload(
                practice["id"], fee_model="PERCENT_OF_COLLECTIONS"
            ),
            COUNSEL,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _, meta = validate_paginated(
        api_client.list_service_agreements(COUNSEL, {"practice_id": practice["id"]})
    )
    assert meta["total_count"] == 0


def test_unknown_payer_contract_on_enrollment_create_returns_not_found():
    """PRD §2.11: "5. Body foreign-key existence — the referenced entity's 404 code."
    PRD §2.10: "Foreign keys supplied in a request body are resolved after every path segment has resolved and before the payload's shape is checked, and they raise the same family of 404 codes: a body naming a missing affiliation raises `ERR_AFFILIATION_NOT_FOUND`, a missing practice raises `ERR_PRACTICE_NOT_FOUND`, a missing doctor raises `ERR_DOCTOR_NOT_FOUND`, a missing conversion vendor raises `ERR_CONVERSION_VENDOR_NOT_FOUND`, a missing employment raises `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND`, a missing agreement raises `ERR_SERVICE_AGREEMENT_NOT_FOUND` and a missing payer contract raises `ERR_PAYER_CONTRACT_NOT_FOUND`."

    Design: Corner/entities/payer_enrollment_unknown_contract_returns_not_found
    """
    ctx = build_closed_deal()

    validate_error(
        api_client.create_payer_enrollment(
            create_payer_enrollment_payload(
                UNKNOWN_UUID, ctx["employment_id"], "2027-02-13T00:00:00Z"
            ),
            LEAD,
        ),
        ApiErrorId.ERR_PAYER_CONTRACT_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(
        api_client.list_payer_enrollments(
            LEAD, {"doctor_employment_id": ctx["employment_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_unknown_conversion_vendor_reference_creates_no_practice():
    """PRD §2.10: "Parent linkage is expressed exclusively through foreign-key fields in request bodies, and reverse navigation is provided by filtered list endpoints plus five sub-resource readers — a practice's vendor consolidations, an employment's supply preference exceptions, an employment's clinical quality reviews, an agreement's line items and a contract's fee schedule items."
    PRD §2.11: "5. Body foreign-key existence — the referenced entity's 404 code."

    Design: Corner/entities/practice_unknown_conversion_vendor_reference_rejected
    """
    affiliation = create_affiliation()

    validate_error(
        api_client.create_practice(
            {
                "affiliation_id": affiliation["id"],
                "conversion_vendor_id": UNKNOWN_UUID,
                "name": "Elm Street Dental",
                "state_code": "IL",
                "charts_total_expected": 5000,
            },
            LEAD,
        ),
        ApiErrorId.ERR_CONVERSION_VENDOR_NOT_FOUND.value,
        404,
    )

    parent = validate_success(api_client.get_affiliation(affiliation["id"], COUNSEL))
    assert parent["practice_count"] == 0
