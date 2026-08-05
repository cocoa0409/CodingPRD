"""Operator registration, venue classification, payload shape and list paging."""

from test_helpers import (
    ANON,
    ADMIN,
    INSPECTOR,
    UNKNOWN_UUIDS,
    ApiErrorId,
    api_client,
    assert_envelope_meta,
    assert_facility,
    assert_operator,
    assert_water_reading,
    create_facility_payload,
    create_operator_payload,
    create_water_reading_payload,
    register_operator,
    setup_operator_and_pool,
    setup_operator_and_spa,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_register_operator_mints_uuid_identity_and_zero_balance(api):
    """PRD 3.1: A freshly registered operator has `fee_balance_cents` of 0.
    PRD 2.5: Every stored resource carries a server-minted `id` that is a UUID
    string with no type prefix, and a `created_at` timestamp stamped from the
    logical clock at insertion.
    PRD 2.5: Most resources additionally carry an `updated_at` timestamp,
    refreshed from the logical clock on every mutation, and an integer `version`
    that starts at 1 when the row is created and increments by exactly 1 on every
    mutation of that row.
    PRD 2.4: Before any client sets it, the clock reads exactly
    `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time under any
    circumstance.

    Design: Corner/entities/create_operator_returns_server_minted_identity_and_zero_balance
    """
    response = api.create_operator(
        create_operator_payload(phone="555-0100"), ANON
    )
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert_envelope_meta(response.json())
    assert_operator(data)
    assert data["fee_balance_cents"] == 0
    assert data["version"] == 1
    assert data["created_at"] == "2026-05-01T00:00:00.000Z"


def test_read_operator_returns_the_stored_row(api):
    """PRD 3.1: the caller supplies a `legal_name` between 1 and 200 characters,
    a `contact_email` that must be non-empty and must contain an at-sign, and
    optionally a `phone`, which defaults to null when omitted.
    PRD 3.1: A freshly registered operator has `fee_balance_cents` of 0.

    Design: Corner/entities/get_operator_returns_stored_row
    """
    operator, op_headers = register_operator()

    data = validate_success(api.get_operator(operator["id"], op_headers))

    assert data["id"] == operator["id"]
    assert data["legal_name"] == "Blue Lagoon Aquatics"
    assert data["contact_email"] == "ops@bluelagoon.example"
    assert data["fee_balance_cents"] == 0


def test_pool_classification_derives_bather_load_and_signage(api):
    """PRD 3.1: `max_bather_load` is the water surface area divided by the
    per-bather allowance for that water type and rounded down to a whole number
    of bathers: the allowance is 10 square feet per bather for a spa and 20
    square feet per bather for a pool.
    PRD 3.1: `lifeguard_required` is true exactly when the class is either
    `CLASS_A_COMPETITION` or `CLASS_B_PUBLIC` **and** the computed
    `max_bather_load` is at least 50; semi-public pools and spas never require a
    lifeguard, regardless of size.
    PRD 3.1: A newly registered venue therefore reads `vgb_compliance_status` of
    `NONCOMPLIANT` — there is no certification on file yet — and
    `operating_posture` of `CLOSED` with `posture_reason` of `PERMIT_MISSING`.

    Design: Corner/entities/facility_computed_classification_fields_for_pool
    """
    operator, op_headers = register_operator()

    data = validate_success(
        api.create_facility(create_facility_payload(operator["id"]), op_headers), 201
    )

    assert_facility(data)
    assert data["water_type"] == "POOL"
    assert data["max_bather_load"] == 60
    assert data["lifeguard_required"] is True
    assert data["required_signage_types"] == [
        "DEPTH_MARKERS", "EMERGENCY_PHONE", "DIARRHEA_NOTICE",
    ]
    assert data["vgb_compliance_status"] == "NONCOMPLIANT"


def test_spa_classification_uses_spa_divisor_and_signage_set(api):
    """PRD 3.1: First, `water_type` is set to `SPA` when `facility_class` is
    `SPA` and to `POOL` for all three of the other classes.
    PRD 3.1: `required_signage_types` is assembled as an ordered list: for a spa
    it begins with `SPA_TEMP_WARNING`, `EMERGENCY_PHONE`, `DIARRHEA_NOTICE`, and
    for a pool with `DEPTH_MARKERS`, `EMERGENCY_PHONE`, `DIARRHEA_NOTICE`; then,
    when and only when `lifeguard_required` is false, `NO_LIFEGUARD_WARNING` is
    appended as the final element.

    Design: Corner/entities/spa_facility_uses_spa_divisor_and_spa_signage_set
    """
    ctx = setup_operator_and_spa()
    spa = ctx["facility"]

    assert_facility(spa)
    assert spa["water_type"] == "SPA"
    assert spa["max_bather_load"] == 40
    assert spa["lifeguard_required"] is False
    assert spa["required_signage_types"] == [
        "SPA_TEMP_WARNING", "EMERGENCY_PHONE", "DIARRHEA_NOTICE",
        "NO_LIFEGUARD_WARNING",
    ]


def test_facility_optional_inputs_take_their_declared_defaults(api):
    """PRD 3.1: Four optional inputs shape the rest of the record: `features`,
    defaulting to the empty list, whose elements must be a duplicate-free subset
    of `SLIDE`, `DIVING_BOARD`, `WAVE_GENERATOR`, `SPA_JETS` and `SPLASH_PAD`;
    `is_seasonal`, defaulting to false; the pair `season_start_date` and
    `season_end_date`, both defaulting to null; and `requires_plan_review`,
    defaulting to false.

    Design: Corner/entities/facility_defaults_applied_when_optional_fields_omitted
    """
    operator, op_headers = register_operator()

    data = validate_success(
        api.create_facility(
            create_facility_payload(
                operator["id"], facility_class="CLASS_C_SEMI_PUBLIC",
                surface_area_sqft=600, water_volume_gallons=25000, max_depth_feet=6,
            ),
            op_headers,
        ),
        201,
    )

    assert data["features"] == []
    assert data["is_seasonal"] is False
    assert data["requires_plan_review"] is False
    assert data["season_start_date"] is None
    assert data["season_end_date"] is None


def test_facility_missing_facility_class_rejected(api):
    """PRD 2.6: Required body fields present, declared types honoured, enum
    values inside their declared sets, numeric fields inside their declared
    bounds, `limit` within 1 to 100 and `offset` at least 0, and unknown
    `action`, `decision` or `outcome` values rejected.
    PRD 3.1: Registering it requires the owning `operator_id`, a `name` of 1 to
    200 characters, a `facility_class` drawn from `CLASS_A_COMPETITION`,
    `CLASS_B_PUBLIC`, `CLASS_C_SEMI_PUBLIC` and `SPA`, a `surface_area_sqft`
    strictly greater than zero, a `water_volume_gallons` of zero or more, a
    `max_depth_feet` strictly greater than zero, and a `drain_count` of at least
    1.

    Design: Corner/entities/create_facility_missing_required_field_returns_validation
    """
    operator, op_headers = register_operator()
    payload = create_facility_payload(operator["id"])
    payload.pop("facility_class")

    response = api.create_facility(payload, op_headers)

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(
        api.list_facilities(op_headers, params={"operator_id": operator["id"]})
    )
    assert meta["total_count"] == 0, "A rejected registration must create no venue"
    assert rows == []


def test_facility_unknown_class_enum_rejected(api):
    """PRD 2.6: Required body fields present, declared types honoured, enum
    values inside their declared sets, numeric fields inside their declared
    bounds, `limit` within 1 to 100 and `offset` at least 0, and unknown
    `action`, `decision` or `outcome` values rejected.
    PRD 3.1: a `facility_class` drawn from `CLASS_A_COMPETITION`,
    `CLASS_B_PUBLIC`, `CLASS_C_SEMI_PUBLIC` and `SPA`

    Design: Corner/entities/create_facility_invalid_enum_value_rejected
    """
    operator, op_headers = register_operator()

    response = api.create_facility(
        create_facility_payload(operator["id"], facility_class="CLASS_D"), op_headers
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_seasonal_facility_without_season_dates_rejected(api):
    """PRD 3.1: When `is_seasonal` is true both season dates are mandatory and
    `season_end_date` must be on or after `season_start_date`; when it is false
    both must be absent or null. Violating either shape is a payload failure.
    PRD 2.6: a facility declared seasonal requires both season dates and a
    facility declared non-seasonal forbids them

    Design: Corner/entities/facility_seasonal_without_season_dates_rejected
    """
    operator, op_headers = register_operator()

    response = api.create_facility(
        create_facility_payload(
            operator["id"], name="Seasonal Pool",
            facility_class="CLASS_C_SEMI_PUBLIC", surface_area_sqft=600,
            water_volume_gallons=30000, max_depth_feet=6, is_seasonal=True,
        ),
        op_headers,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_water_reading_is_append_only_without_version_or_updated_at(api):
    """PRD 2.5: Two record types are append-only observations rather than living
    records and therefore carry only `id` and `created_at`: a water-chemistry
    reading and a fee-ledger posting. Neither has an `updated_at` field and
    neither has a `version` field; once written they are never mutated or
    deleted.
    PRD 3.7: an optional `cyanuric_acid_ppm` that defaults to 0 and must be at
    least zero

    Design: Corner/entities/water_reading_is_immutable_and_carries_no_version
    """
    ctx = setup_operator_and_pool()

    data = validate_success(
        api.create_water_reading(
            ctx["facility_id"],
            create_water_reading_payload(free_chlorine_ppm=2.0),
            ctx["op_headers"],
        ),
        201,
    )

    assert_water_reading(data)
    assert data["created_at"] == "2026-05-01T00:00:00.000Z"
    assert "version" not in data
    assert "updated_at" not in data
    assert data["compliance_status"] == "IN_RANGE"
    assert data["cyanuric_acid_ppm"] == 0


def test_facility_list_paginates_with_total_count_and_has_more(api):
    """PRD 2.3: `total_count` is the number of rows that match the endpoint's
    filters *before* `limit` and `offset` are applied; `has_more` is true exactly
    when `offset` plus the number of rows actually returned is still less than
    `total_count`.
    PRD 2.3: Rows in every list are ordered by `created_at` ascending.

    Design: Corner/entities/facility_list_pagination_reports_total_count_and_has_more
    """
    operator, op_headers = register_operator(
        legal_name="Tri Pools", contact_email="ops@tripools.example"
    )
    ids = []
    for name in ("Pool One", "Pool Two", "Pool Three"):
        created = validate_success(
            api.create_facility(
                create_facility_payload(
                    operator["id"], name=name,
                    facility_class="CLASS_C_SEMI_PUBLIC", surface_area_sqft=600,
                    water_volume_gallons=20000, max_depth_feet=6,
                ),
                op_headers,
            ),
            201,
        )
        ids.append(created["id"])

    first_page, first_meta = validate_paginated(
        api.list_facilities(
            op_headers,
            params={"operator_id": operator["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert [row["id"] for row in first_page] == ids[:2]

    second_page, second_meta = validate_paginated(
        api.list_facilities(
            op_headers,
            params={"operator_id": operator["id"], "limit": 2, "offset": 2},
        )
    )
    assert [row["id"] for row in second_page] == [ids[2]]
    assert second_meta["has_more"] is False


def test_limit_above_one_hundred_rejected(api):
    """PRD 2.3: `limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    PRD 2.3: A `limit` below 1 or above 100, or a negative `offset`, is a payload
    error and is rejected with `ERR_VALIDATION` (HTTP 400).

    Design: Corner/entities/pagination_limit_above_maximum_returns_validation
    """
    operator, op_headers = register_operator()

    response = api.list_facilities(op_headers, params={"limit": 101})

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_unresolved_path_ids_return_entity_specific_not_found(api):
    """PRD 2.6: Each `{id}` segment of the request path resolves to a stored row,
    checked strictly left to right; the first unresolved segment decides the
    error. The candidates are `ERR_OPERATOR_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_PLAN_REVIEW_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CLOSURE_ORDER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_STAFF_ASSIGNMENT_NOT_FOUND` and `ERR_LEDGER_ENTRY_NOT_FOUND`, each HTTP
    404.

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found
    """
    register_operator()

    validate_error(
        api.get_permit(UNKNOWN_UUIDS["permit"], ADMIN),
        ApiErrorId.ERR_PERMIT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_closure_order(UNKNOWN_UUIDS["closure_order"], ADMIN),
        ApiErrorId.ERR_CLOSURE_ORDER_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_complaint(UNKNOWN_UUIDS["complaint"], ADMIN),
        ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_fee_ledger_entry(UNKNOWN_UUIDS["ledger_entry"], ADMIN),
        ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_operator(UNKNOWN_UUIDS["operator"], ADMIN),
        ApiErrorId.ERR_OPERATOR_NOT_FOUND.value, 404,
    )


def test_unresolved_body_foreign_keys_return_entity_specific_not_found(api):
    """PRD 2.6: Foreign keys supplied in the request body resolve to stored rows,
    checked in the order `facility_id`, then `plan_review_id`, then
    `prior_inspection_id`, then `linked_inspection_id`, then
    `verification_reading_id`, yielding `ERR_FACILITY_NOT_FOUND`,
    `ERR_PLAN_REVIEW_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` or
    `ERR_READING_NOT_FOUND` (all 404).

    Design: Corner/entities/unknown_body_foreign_keys_return_entity_specific_not_found
    """
    ctx = setup_operator_and_pool()

    validate_error(
        api.create_permit(
            {
                "facility_id": UNKNOWN_UUIDS["facility"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-05-01",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404,
    )
    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_id"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-05-01",
                "plan_review_id": UNKNOWN_UUIDS["plan_review"],
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_PLAN_REVIEW_NOT_FOUND.value, 404,
    )
    validate_error(
        api.create_inspection(
            {
                "facility_id": ctx["facility_id"],
                "inspection_type": "REINSPECTION",
                "scheduled_start_at": "2026-05-02T09:00:00Z",
                "scheduled_end_at": "2026-05-02T10:00:00Z",
                "prior_inspection_id": UNKNOWN_UUIDS["inspection"],
            },
            INSPECTOR,
        ),
        ApiErrorId.ERR_INSPECTION_NOT_FOUND.value, 404,
    )

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_amending_a_facility_recomputes_derived_fields_and_bumps_version(api):
    """PRD 3.1: A venue may be amended later — its `name`, `facility_class`,
    `surface_area_sqft`, `water_volume_gallons`, `max_depth_feet`, `drain_count`,
    `features`, `is_seasonal`, `season_start_date`, `season_end_date` and
    `requires_plan_review` are all individually optional on an amendment — and
    every derived field is recomputed from the new values while the facility's
    `version` climbs by 1.
    PRD 3.1: then, when and only when `lifeguard_required` is false,
    `NO_LIFEGUARD_WARNING` is appended as the final element.

    Design: Corner/endpoints/patch_facility_recomputes_derived_fields_and_bumps_version
    """
    ctx = setup_operator_and_pool()
    before_version = ctx["facility"]["version"]

    data = validate_success(
        api.patch_facility(
            ctx["facility_id"], {"surface_area_sqft": 600}, ctx["op_headers"]
        )
    )

    assert data["max_bather_load"] == 30
    assert data["lifeguard_required"] is False
    assert data["required_signage_types"] == [
        "DEPTH_MARKERS", "EMERGENCY_PHONE", "DIARRHEA_NOTICE",
        "NO_LIFEGUARD_WARNING",
    ]
    assert data["version"] == before_version + 1
    assert data["updated_at"] == "2026-05-01T00:00:00.000Z"
    assert data["water_volume_gallons"] == 60000, (
        "Fields absent from the amendment are preserved"
    )
