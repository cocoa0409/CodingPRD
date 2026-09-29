"""Entity-level corners: shapes, defaults, computed fields and identity.

PRD §2.4: "Every resource the service persists is addressed by an `id`, which is a
server-minted UUID carrying no type prefix of any kind."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_FAMILY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SUPPLIER_NOT_FOUND,
    NON_EXISTENT_UUID,
    assert_envelope,
    assert_fields_equal,
    assert_identity_fields,
    assert_narrow_identity_fields,
    assert_pagination_meta,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_supplier,
    create_vintage,
    factories,
    read_family,
    success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_creating_a_family_returns_every_declared_field_at_its_default(api):
    """The six required inputs are echoed and every derived field starts at its floor.

    PRD §3.2: "A **product family** is registered with a `family_code` unique across all
    families ... Two further inputs are optional ... `engineering_estimate_rate_ppm`,
    which is either null or a non-negative engineering-estimated lifetime claim rate ...
    and `analog_family_id`, which is either null or the identifier of an existing product
    family". PRD §3.2 also fixes the derived starting values: "`observed_history_months`
    is 0 when no claim observation exists for any vintage of the family", the maturity is
    `LIMITED` "in every other case", and PRD §2.10 adds "A freshly registered family sits
    at a balance of zero and therefore at `NORMAL`".

    Design: Corner/entities/corner_create_product_family_returns_every_declared_field
    """
    response = api.create_product_family_raw(
        ANALYST_HEADERS,
        factories.family_payload(
            family_code="FAM-C1",
            name="Corner Cooktop Platform",
            launch_date="2025-03-01",
            base_warranty_months=24,
            standard_cost_per_claim_cents=18000,
            reserve_cap_cents=25000000,
        ),
    )
    family = success_data(response, expected_status=201)
    assert_envelope(response, "object")
    assert_identity_fields(family)

    assert_fields_equal(
        family,
        family_code="FAM-C1",
        name="Corner Cooktop Platform",
        launch_date="2025-03-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=25000000,
        engineering_estimate_rate_ppm=None,
        analog_family_id=None,
        observed_history_months=0,
        observed_exposure_units=0,
        units_sold_lifetime=0,
        history_maturity_status="LIMITED",
        warranty_reserve_balance_cents=0,
        reserve_posture="NORMAL",
        version=1,
    )


def test_reading_a_vintage_echoes_its_inputs_and_derives_active_exposure(api):
    """The stored row comes back untouched with exposure derived from the clock.

    PRD §3.2: "The cohort's `exposure_status` is derived, never supplied: it is `ACTIVE`
    while the logical clock is strictly earlier than `warranty_expiry_date` and `EXPIRED`
    from that date onward." PRD §2.5 puts the clock at "exactly `2026-08-01T00:00:00Z`"
    before any client moves it, which precedes the 2029-02-28 expiry.

    Design: Corner/entities/corner_get_vintage_returns_stored_row_unmodified
    """
    family = create_family(
        api,
        family_code="FAM-C2",
        name="Corner Freezer Platform",
        launch_date="2025-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=21000,
        reserve_cap_cents=30000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="C2-MY2025",
        units_shipped=1750,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-02-28",
    )

    stored = validate_success(api.get_vintage(ACTUARY_HEADERS, vintage["id"]))

    assert_fields_equal(
        stored,
        family_id=family["id"],
        vintage_code="C2-MY2025",
        units_shipped=1750,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-02-28",
        exposure_status="ACTIVE",
    )


def test_listing_vintages_reports_total_count_and_has_more_across_two_pages(api):
    """Three rows split into a full page and a remainder.

    PRD §2.3: "The `meta` object of a list response carries `limit` and `offset` as
    applied to the query, `total_count` as the number of rows matching the filters before
    pagination is applied, and `has_more` as a boolean that is true exactly when rows
    matching the filters remain beyond the returned page."

    Design: Corner/entities/corner_list_vintages_paginates_with_total_count_and_has_more
    """
    family = create_family(
        api,
        family_code="FAM-C3",
        name="Corner Dryer Platform",
        launch_date="2024-02-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=17000,
        reserve_cap_cents=30000000,
    )
    for code, units, expiry in (
        ("C3-MY2024", 1000, "2028-01-31"),
        ("C3-MY2025", 1200, "2029-01-31"),
        ("C3-MY2026", 1400, "2030-01-31"),
    ):
        create_vintage(
            api,
            family["id"],
            vintage_code=code,
            units_shipped=units,
            ship_period_code=f"{code[3:7]}-Q1",
            warranty_expiry_date=expiry,
        )

    first_page = api.list_vintages(ANALYST_HEADERS, family_id=family["id"], limit=2, offset=0)
    assert_envelope(first_page, "array")
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    second_page = api.list_vintages(ANALYST_HEADERS, family_id=family["id"], limit=2, offset=2)
    rows, meta = validate_paginated(second_page)
    assert len(rows) == 1
    assert_pagination_meta(meta, limit=2, offset=2, total_count=3, has_more=False)

    assert read_family(api, family["id"])["observed_exposure_units"] == 3600


def test_reading_a_supplier_that_does_not_exist_is_a_not_found(api):
    """A well-formed but unknown path id resolves to nothing.

    PRD §2.9 rung 4: "Every identifier embedded in the request path resolves to an
    existing row ... The error is the one belonging to the first unresolvable segment:
    ... `ERR_SUPPLIER_NOT_FOUND` ... (all HTTP 404)."

    Design: Corner/entities/corner_get_supplier_with_unknown_id_not_found
    """
    supplier = create_supplier(
        api,
        supplier_code="SUP-C1",
        name="Corner Components Oy",
        credit_rating="BBB",
        annual_purchase_volume_cents=500000000,
        contractual_recovery_cap_bps=1500,
    )

    response = api.get_supplier(ANALYST_HEADERS, NON_EXISTENT_UUID)
    validate_error(response, ERR_SUPPLIER_NOT_FOUND, expected_status=404)

    still_there = validate_success(api.get_supplier(ANALYST_HEADERS, supplier["id"]))
    assert still_there["supplier_code"] == "SUP-C1"


def test_a_family_created_without_a_reserve_cap_is_rejected_and_persists_nothing(api):
    """A required input with no default cannot be omitted.

    PRD §2.9 rung 5: "Request-shape conformance — every required field of the endpoint's
    input is present ... Guards every creation and update endpoint — otherwise
    `ERR_INVALID_REQUEST`." PRD §3.2 lists `reserve_cap_cents` among the inputs a family
    "is registered with", with no default stated.

    Design: Corner/entities/corner_create_family_missing_reserve_cap_rejected
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")

    response = api.create_product_family_raw(
        ANALYST_HEADERS,
        {
            "family_code": "FAM-C4",
            "name": "Corner Hob Platform",
            "launch_date": "2025-05-01",
            "base_warranty_months": 24,
            "standard_cost_per_claim_cents": 15000,
        },
    )
    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(api.list_product_families(ANALYST_HEADERS, limit=10, offset=0))
    assert meta["total_count"] == 0


def test_a_field_action_omitting_the_notice_flag_defaults_it_to_false(api):
    """The optional flag defaults, and a campaign is not a safety recall.

    PRD §3.5: "optionally `regulatory_notice_filed`, which defaults to false when
    omitted. The system derives `is_safety_recall` as true exactly when `action_type` is
    `SAFETY_RECALL` and false for the other two types." PRD §3.5 also fixes the rest of
    the birth state: "A new action starts with `approval_state` of `DRAFT`,
    `execution_state` of `NOT_STARTED`, a null `selected_remedy_option_id`, a
    `specific_accrual_cents` of 0, an `executed_cost_cents` of 0, a null
    `approved_period_id`".

    Design: Corner/entities/corner_field_action_optional_regulatory_notice_defaults_false
    """
    family = create_family(
        api,
        family_code="FAM-C5",
        name="Corner Hood Platform",
        launch_date="2024-09-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=16000,
        reserve_cap_cents=20000000,
    )

    response = api.create_field_action_raw(
        ENGINEER_HEADERS,
        {
            "family_id": family["id"],
            "action_code": "FA-C5-01",
            "action_type": "SERVICE_CAMPAIGN",
            "affected_build_start_date": "2025-01-01",
            "affected_build_end_date": "2025-02-28",
            "affected_unit_count": 300,
        },
    )
    action = success_data(response, expected_status=201)

    assert_fields_equal(
        action,
        regulatory_notice_filed=False,
        is_safety_recall=False,
        approval_state="DRAFT",
        execution_state="NOT_STARTED",
        selected_remedy_option_id=None,
        specific_accrual_cents=0,
        executed_cost_cents=0,
        approved_period_id=None,
    )


def test_family_exposure_metrics_recompute_on_vintage_and_observation_writes(api):
    """Registering a vintage and appending history each move the derived metrics.

    PRD §3.2: "`observed_exposure_units` is the sum of `units_shipped` over every
    production vintage of the family ... `units_sold_lifetime` is an alias metric holding
    exactly the same number as `observed_exposure_units`" and "This classification is
    re-derived on family registration, on family update, on vintage registration, on
    claim-observation append, and whenever the logical clock moves."

    Design: Corner/entities/corner_family_exposure_metrics_recompute_on_vintage_and_observation
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-C6",
        name="Corner Washer Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=30000000,
    )
    first_vintage = create_vintage(
        api,
        family["id"],
        vintage_code="C6-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-C6-01",
        description="Corner bearing wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )

    baseline = read_family(api, family["id"])
    assert_fields_equal(
        baseline,
        observed_exposure_units=3000,
        observed_history_months=0,
        history_maturity_status="LIMITED",
    )

    create_vintage(
        api,
        family["id"],
        vintage_code="C6-MY2025",
        units_shipped=2500,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-12-31",
    )
    after_vintage = read_family(api, family["id"])
    assert_fields_equal(
        after_vintage,
        observed_exposure_units=5500,
        units_sold_lifetime=5500,
        history_maturity_status="LIMITED",
    )

    create_observation(
        api,
        first_vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=18,
        claim_count=60,
        paid_cost_cents=1200000,
    )
    after_observation = read_family(api, family["id"])
    assert after_observation["observed_history_months"] == 18
    assert after_observation["history_maturity_status"] == "MATURE"


def test_accrual_lifecycle_fields_are_minted_by_the_server_not_the_caller(api):
    """The create body carries no status or attribution and the row starts clean.

    PRD §3.3: "The row is born in `status` `DRAFT` with a `revision_index` of 0 and both
    `proposed_by_user_id` and `posted_by_user_id` null". PRD §2.4: "`version` is an
    integer that starts at 1 when the row is created", and PRD §3.3's `ANALOG_BLEND`
    variant fixes the figures: the analogue develops to 75000 ppm, blends to 32400 ppm at
    the 6000-basis-point engineering weight, and prices 97 ultimate claims at the family's
    `standard_cost_per_claim_cents`.

    Design: Corner/entities/corner_accrual_system_fields_are_server_minted
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    family = create_family(
        api,
        family_code="FAM-C7",
        name="Corner Launch Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=20000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="C7-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-C7-01",
        description="Corner launch valve leak",
        severity="FUNCTIONAL",
        cost_per_claim_cents=21000,
    )

    response = api.create_accrual_raw(
        ANALYST_HEADERS,
        factories.accrual_payload(
            period["id"], vintage["id"], 1, method="ANALOG_BLEND", elapsed_exposure_bps=2000
        ),
    )
    accrual = success_data(response, expected_status=201)
    assert_identity_fields(accrual)

    assert_fields_equal(
        accrual,
        status="DRAFT",
        revision_index=0,
        proposed_by_user_id=None,
        posted_by_user_id=None,
        version=1,
        expected_claim_rate_ppm=32400,
        cost_per_claim_basis_cents=30000,
        paid_to_date_cents=0,
        accrued_amount_cents=2910000,
    )


def test_out_of_enum_and_out_of_order_values_are_shape_violations(api):
    """An unknown severity and an inverted period range are both rejected.

    PRD §2.9 rung 5: "every value satisfies its declared type, enum member set and numeric
    range. This rung also carries the shape and ordering constraints stated with the
    fields themselves: ... `period_end_date` is strictly after `period_start_date`".
    PRD §3.2 declares the closed set: "a `severity` that is one of `COSMETIC`,
    `FUNCTIONAL` or `SAFETY`".

    Design: Corner/entities/corner_invalid_enum_and_out_of_range_values_rejected
    """
    family = create_family(
        api,
        family_code="FAM-C8",
        name="Corner Enum Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )

    bad_enum = api.create_failure_mode_raw(
        ANALYST_HEADERS,
        factories.failure_mode_payload(
            family["id"],
            mode_code="FM-C8-01",
            description="Bad severity",
            severity="CRITICAL",
            cost_per_claim_cents=12000,
        ),
    )
    validate_error(bad_enum, ERR_INVALID_REQUEST, expected_status=400)

    bad_dates = api.create_period_raw(
        CONTROLLER_HEADERS,
        factories.period_payload(
            period_code="2026-Q3",
            period_start_date="2026-09-30",
            period_end_date="2026-07-01",
        ),
    )
    validate_error(bad_dates, ERR_INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(api.list_failure_modes(ANALYST_HEADERS, family_id=family["id"]))
    assert meta["total_count"] == 0


def test_a_claim_observation_carries_no_version_and_cannot_be_amended(api):
    """The append-only fact has the narrow identity set.

    PRD §2.4: "A claim observation is an append-only historical fact and is never edited
    after it is written; it carries `id` and `created_at` only — both `updated_at` and
    `version` are absent from its representation."

    Design: Corner/entities/corner_claim_observation_is_immutable_and_versionless
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-C9",
        name="Corner Immutable Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=14000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="C9-MY2024",
        units_shipped=900,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-C9-01",
        description="Corner immutable defect",
        severity="COSMETIC",
        cost_per_claim_cents=4000,
    )
    observation = create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=6,
        claim_count=3,
        paid_cost_cents=12000,
    )

    stored = validate_success(api.get_claim_observation(CONTROLLER_HEADERS, observation["id"]))

    assert_narrow_identity_fields(stored)
    assert stored["claim_count"] == 3
    assert stored["paid_cost_cents"] == 12000


def test_a_vintage_naming_an_unknown_family_in_its_body_is_a_not_found(api):
    """The parent arrives as a body foreign key and is resolved before anything is written.

    PRD §2.9 rung 6: "Every foreign-key identifier supplied in the request body resolves
    to an existing row ... guarding ... `POST /warranty/vintages` ... The error is
    `ERR_PERIOD_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`, ... according to which reference
    failed (all HTTP 404)."

    Design: Corner/entities/corner_flat_topology_vintage_with_unknown_family_not_found
    """
    family = create_family(
        api,
        family_code="FAM-CA",
        name="Corner FK Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=13000,
        reserve_cap_cents=15000000,
    )

    response = api.create_vintage_raw(
        ANALYST_HEADERS,
        factories.vintage_payload(
            NON_EXISTENT_UUID,
            vintage_code="CA-MY2025",
            units_shipped=500,
            ship_period_code="2025-Q1",
            warranty_expiry_date="2029-01-31",
        ),
    )
    validate_error(response, ERR_FAMILY_NOT_FOUND, expected_status=404)

    _, meta = validate_paginated(api.list_vintages(ANALYST_HEADERS, family_id=family["id"]))
    assert meta["total_count"] == 0
