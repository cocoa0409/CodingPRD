"""Queue B - corner section ``entities``.

Declared defaults, server-minted system fields, derived-from-source constants,
single-row retrieval, listing envelopes and the four rejection shapes that guard
entity writes.
"""

import pytest

from test_helpers import (
    ApiClient,
    NON_EXISTENT_UUID,
    assert_list_meta,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS
from test_helpers.types import (
    AppointmentState,
    BatchState,
    CctOptimizationStatus,
    Classification,
    CertaintyBasis,
    ConsentState,
    CrewStatus,
    EvidenceOrigin,
    FulfillmentState,
    FundingMode,
    FundingSourceStatus,
    InventoryState,
    InventoryStatus,
    Material,
    NotificationState,
    ProgramPosture,
    PublicationBasis,
    PublicationState,
    ReplacementState,
    Side,
    SourceKind,
    SourceType,
    VerificationMethod,
)


def test_water_system_creation_applies_every_declared_default(api: ApiClient) -> None:
    """A registration carrying only the three mandatory inputs fills in every default.

    PRD 3.1: "Four further inputs are optional at registration."
    PRD 3.1: "`baseline_lead_and_grr_count` is the regulatory baseline tally of lead
    and galvanized lines that serves as the denominator of the mandated annual
    replacement rate; it defaults to 0 and may not be negative."
    PRD 3.1: "A freshly registered system starts with `inventory_status` at `DRAFT`,
    and because clause 1 of the posture rule fires on `DRAFT`, its `program_posture`
    is `FROZEN` from the very first moment."
    PRD 3.1: "Its counters all start at zero: `total_service_line_count`,
    `lead_count`, `grr_count`, `non_lead_count`, `unknown_count` and
    `outstanding_notification_count` are integers starting at 0, and
    `unknown_share_pct` starts at 0.0."

    Design: Corner/entities/water_system_creation_applies_every_declared_default
    """
    response = api.create_water_system(
        factories.water_system_payload(
            "IL2100001",
            system_name="Default Creek Water",
            compliance_deadline_date="2027-10-16",
        ),
        ADMIN_HEADERS,
    )

    system = get_success_data(response, 201)

    assert system["baseline_lead_and_grr_count"] == 0
    assert system["disadvantaged_tract_codes"] == []
    assert system["funding_mode"] == FundingMode.WATERFALL
    assert system["cct_optimization_status"] == CctOptimizationStatus.NOT_REQUIRED
    assert system["cct_orthophosphate_mg_l"] is None
    assert system["cct_target_ph"] is None
    assert system["total_service_line_count"] == 0
    assert system["lead_count"] == 0
    assert system["grr_count"] == 0
    assert system["non_lead_count"] == 0
    assert system["unknown_count"] == 0
    assert system["unknown_share_pct"] == pytest.approx(0.00)
    assert system["outstanding_notification_count"] == 0
    assert system["inventory_status"] == InventoryStatus.DRAFT
    assert system["program_posture"] == ProgramPosture.FROZEN


def test_system_fields_are_minted_by_the_server_from_the_logical_clock(
    api: ApiClient,
) -> None:
    """id is a server-minted UUID, created_at is ISO 8601 and version starts at 1.

    PRD 2.4: "`id` — a server-minted UUID."
    PRD 2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits,
    stamped when the row is first persisted and never changed afterwards."
    PRD 2.4: "`version` — an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of the row."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Note: PRD 2.5 enumerates the logical clock's consumers as "every deadline,
    overdue determination, paving-coordination tier and completion-window
    comparison"; it never states that a row's `created_at` is stamped from that
    clock rather than from wall time, so no assertion is made on its provenance.

    Design: Corner/entities/system_fields_are_minted_by_the_server_from_the_logical_clock
    """
    fixtures.set_clock(api, "2026-08-04T07:30:00Z")

    response = api.create_water_system(
        factories.water_system_payload("IL2100002", system_name="Minted Water"),
        ADMIN_HEADERS,
    )
    system = validate_success(response, 201)
    body = response.json()

    assert is_valid_uuid(system["id"])
    assert is_iso8601_timestamp(system["created_at"])
    assert system["version"] == 1
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_service_line_creation_applies_geometry_and_flag_defaults_and_counts_as_unknown(
    api: ApiClient,
) -> None:
    """Omitting every optional input yields 19.0 mm, 15.0 m and a 100.00 unknown share.

    PRD 3.2: "Four inputs are optional: `street_project_id`, which links the premise
    into a paving project's coordination window and is null when absent;
    `serves_sensitive_population`, a boolean defaulting to false that is set true
    for schools, licensed child-care premises and dialysis facilities;
    `interior_diameter_mm`, the line's interior diameter in millimetres, defaulting
    to 19.0 and required to be strictly positive; and `total_length_m`, the combined
    utility-side plus customer-side length in metres, defaulting to 15.0 and
    likewise strictly positive."
    PRD 3.2: "The classification axis, `inventory_state`, starts at `UNCLASSIFIED`
    and moves among `CLASSIFIED_PROVISIONAL` and `CLASSIFIED_VERIFIED`."
    PRD 3.1: "`unknown_share_pct` is 0.00 when the system has no service lines at
    all; otherwise it is one hundred times the unknown count divided by the total
    count, rounded half-up to two decimals."

    Design: Corner/entities/service_line_creation_applies_geometry_and_flag_defaults_and_counts_as_unknown
    """
    system = fixtures.create_water_system(api, "IL2100003", system_name="Geometry Water")

    line = get_success_data(
        api.create_service_line(
            factories.service_line_payload(
                system["id"], address_label="101 Elm St", census_tract_code="17031-9900"
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert line["serves_sensitive_population"] is False
    assert line["interior_diameter_mm"] == pytest.approx(19.0)
    assert line["total_length_m"] == pytest.approx(15.0)
    assert line["street_project_id"] is None
    assert line["inventory_state"] == InventoryState.UNCLASSIFIED
    assert line["replacement_state"] == ReplacementState.NOT_REQUIRED
    assert line["classification"] == Classification.UNKNOWN
    assert line["certainty_basis"] == CertaintyBasis.RECORDS_BASIS
    assert line["certainty_score"] == pytest.approx(0.00)
    assert line["replacement_priority_score"] == pytest.approx(0.00)
    assert line["utility_side_material"] == Material.UNKNOWN
    assert line["customer_side_material"] == Material.UNKNOWN

    parent = fixtures.read_water_system(api, system["id"])
    assert parent["total_service_line_count"] == 1
    assert parent["unknown_count"] == 1
    assert parent["unknown_share_pct"] == pytest.approx(100.00)


def test_water_system_retrieval_returns_the_stored_row_with_live_counters(
    api: ApiClient,
) -> None:
    """The read echoes the posted identity and carries the counters as they stand now.

    PRD 3.1: "Those counters are pure aggregations over the system's service lines:
    `total_service_line_count` counts every service line of the system with no
    status filter whatsoever, and `lead_count`, `grr_count`, `non_lead_count` and
    `unknown_count` count the subsets whose `classification` is `LEAD`, `GRR`,
    `NON_LEAD` and `UNKNOWN` respectively."
    PRD 3.2: "The line's `classification` is then the worst of the two sides, tested
    in a fixed order: if either side is `LEAD` the classification is `LEAD`;
    otherwise if either side is `GRR` it is `GRR`; otherwise if either side is
    `UNKNOWN` it is `UNKNOWN`; otherwise it is `NON_LEAD`."

    Design: Corner/entities/water_system_retrieval_returns_the_stored_row_with_live_counters
    """
    system = fixtures.create_water_system(api, "IL2100004", system_name="Readback Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )

    read_back = get_success_data(api.get_water_system(system["id"], ADMIN_HEADERS), 200)

    assert read_back["pwsid"] == "IL2100004"
    assert read_back["system_name"] == "Readback Water"
    assert read_back["lead_count"] == 1
    assert read_back["unknown_count"] == 0
    assert read_back["total_service_line_count"] == 1
    assert read_back["unknown_share_pct"] == pytest.approx(0.00)


def test_service_line_listing_reports_total_count_and_has_more(api: ApiClient) -> None:
    """Three rows read two at a time expose total_count 3 with has_more flipping.

    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` in the envelope's `meta` object; `total_count` counts the rows
    matching the filters before pagination is applied, and `has_more` is true when
    rows remain beyond the current page."
    PRD 2.3: "Unless a specific collection says otherwise, list results are ordered
    by `created_at` ascending."

    Design: Corner/entities/service_line_listing_reports_total_count_and_has_more
    """
    system = fixtures.create_water_system(api, "IL2100005", system_name="Paged Water")
    for label in ("101 Elm St", "103 Elm St", "105 Elm St"):
        fixtures.create_service_line(api, system["id"], address_label=label)

    first_rows, first_meta = validate_paginated(
        api.list_service_lines(ANALYST_HEADERS, water_system_id=system["id"], limit=2, offset=0)
    )
    second_rows, second_meta = validate_paginated(
        api.list_service_lines(ANALYST_HEADERS, water_system_id=system["id"], limit=2, offset=2)
    )

    assert len(first_rows) == 2
    assert_list_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert len(second_rows) == 1
    assert_list_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)


def test_unknown_water_system_id_in_the_path_returns_water_system_not_found(
    api: ApiClient,
) -> None:
    """An unallocated identifier is a 404 with its own code, never an empty 200.

    PRD 2.10: "**Path resolution.** Every identifier segment in the URL resolves to
    a live row, checked left to right, so that the leftmost unresolvable segment
    determines the error."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/unknown_water_system_id_in_the_path_returns_water_system_not_found
    """
    response = api.get_water_system(NON_EXISTENT_UUID, ADMIN_HEADERS)

    error = validate_error(response, "ERR_WATER_SYSTEM_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str)
    assert error["message"] != ""


def test_service_line_creation_missing_census_tract_code_is_rejected(
    api: ApiClient,
) -> None:
    """census_tract_code has no default, so omitting it is a schema failure at 400.

    PRD 2.10: "**Schema.** Every non-optional input field of the endpoint is present
    and of the declared JSON type, else `ERR_INVALID_REQUEST` (400)."
    PRD 3.2: "An `InventoryAnalyst` adds a premise to the inventory by creating a
    service line under a `water_system_id`, with an `address_label` naming the
    service address and a `census_tract_code` naming the tract the premise sits in."

    Design: Corner/entities/service_line_creation_missing_census_tract_code_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2100006", system_name="Required Water")

    response = api.create_service_line(
        {"water_system_id": system["id"], "address_label": "101 Elm St"}, ANALYST_HEADERS
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    assert fixtures.read_water_system(api, system["id"])["total_service_line_count"] == 0


def test_evidence_item_with_an_unresolvable_service_line_fk_is_rejected(
    api: ApiClient,
) -> None:
    """A body foreign key naming no live row is a 404, not an orphaned evidence row.

    PRD 2.10: "**Foreign-key resolution.** Every foreign-key field in the request
    body resolves to a live row, checked in the order the fields appear in that
    endpoint's input list, reporting the same per-entity 404 codes."
    PRD 3.2: "Material knowledge enters as **evidence items**."

    Design: Corner/entities/evidence_item_with_an_unresolvable_service_line_fk_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2100007", system_name="Orphan Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")

    response = api.create_evidence_item(
        factories.evidence_item_payload(
            NON_EXISTENT_UUID,
            source_type=SourceType.HISTORIC_RECORD,
            side=Side.UTILITY,
            observed_material=Material.LEAD,
            observed_at="2026-06-01T00:00:00Z",
        ),
        ANALYST_HEADERS,
    )

    validate_error(response, "ERR_SERVICE_LINE_NOT_FOUND", 404)
    assert (
        fixtures.read_service_line(api, line["id"])["inventory_state"]
        == InventoryState.UNCLASSIFIED
    )


def test_evidence_item_tier_rank_and_confidence_weight_are_computed_from_source_type(
    api: ApiClient,
) -> None:
    """A historic record is tier 1 at weight 0.40 and a pothole is tier 5 at weight 1.00.

    PRD 3.2: "Its `tier_rank` is 1 for `HISTORIC_RECORD`, 2 for `PREDICTIVE_MODEL`,
    3 for `WATER_SAMPLING`, 4 for `VISUAL_INSPECTION` and 5 for `POTHOLE` — higher
    meaning more authoritative."
    PRD 3.2: "Its `confidence_weight` is 0.40 for `HISTORIC_RECORD`, 0.55 for
    `PREDICTIVE_MODEL`, 0.70 for `WATER_SAMPLING`, 0.85 for `VISUAL_INSPECTION` and
    1.00 for `POTHOLE`."
    PRD 3.2: "Two further properties are set by the server: `origin`, which is
    `MANUAL` for an item created directly or by a classification override,
    `APPOINTMENT_CASCADE` for one synthesized by a completed verification
    appointment, and `REPLACEMENT_CASCADE` for one synthesized by a completed
    replacement; and `retracted`, a boolean starting false, paired with a
    `retraction_reason` starting null."

    Design: Corner/entities/evidence_item_tier_rank_and_confidence_weight_are_computed_from_source_type
    """
    system = fixtures.create_water_system(api, "IL2100008", system_name="Tier Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")

    record = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    pothole = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-06-02T00:00:00Z",
    )

    assert record["tier_rank"] == 1
    assert record["confidence_weight"] == pytest.approx(0.40)
    assert pothole["tier_rank"] == 5
    assert pothole["confidence_weight"] == pytest.approx(1.00)
    assert record["origin"] == EvidenceOrigin.MANUAL
    assert record["retracted"] is False
    assert record["retraction_reason"] is None


def test_evidence_item_with_an_out_of_set_source_type_is_rejected(api: ApiClient) -> None:
    """XRF_SCAN is outside the five declared source types, so the write is a 422.

    PRD 2.10: "**Enumerations.** Every enum-typed input value is a member of that
    field's declared value set, else `ERR_INVALID_ENUM_VALUE` (422)."
    PRD 3.2: "`source_type` is one of `HISTORIC_RECORD`, `PREDICTIVE_MODEL`,
    `WATER_SAMPLING`, `VISUAL_INSPECTION` or `POTHOLE`."

    Design: Corner/entities/evidence_item_with_an_out_of_set_source_type_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2100009", system_name="Enum Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")

    response = api.create_evidence_item(
        factories.evidence_item_payload(
            line["id"],
            source_type="XRF_SCAN",
            side=Side.UTILITY,
            observed_material=Material.LEAD,
            observed_at="2026-06-01T00:00:00Z",
        ),
        ANALYST_HEADERS,
    )

    validate_error(response, "ERR_INVALID_ENUM_VALUE", 422)
    unchanged = fixtures.read_service_line(api, line["id"])
    assert unchanged["inventory_state"] == InventoryState.UNCLASSIFIED
    assert unchanged["certainty_score"] == pytest.approx(0.00)


def test_every_collection_endpoint_lists_its_own_single_row_with_default_pagination(
    api: ApiClient,
) -> None:
    """Twelve unparameterised list reads each return exactly their own single row.

    PRD 2.3: "`limit` is the maximum number of rows to return; it defaults to 10,
    may not be lower than 1, and may not exceed 100."
    PRD 2.3: "`offset` is the number of rows to skip; it defaults to 0 and may not
    be negative."
    PRD 2.4: "Two collections hold their detail rows as embedded arrays rather than
    as separately addressable resources."

    Design: Corner/entities/every_collection_endpoint_lists_its_own_single_row_with_default_pagination
    """
    system = fixtures.create_water_system(api, "IL2105007", system_name="Listing Water")
    project = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm Resurfacing",
        moratorium_start_date="2026-09-01",
        moratorium_end_date="2026-09-02",
        paving_start_date="2026-12-01",
    )
    line = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", street_project_id=project["id"]
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    fixtures.create_funding_source(
        api,
        system["id"],
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        authorized_cents=200000,
        priority_rank=1,
    )
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew A",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=1,
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
    )
    fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.POTHOLE,
        window_start_utc="2026-08-05T09:00:00Z",
        window_end_utc="2026-08-05T10:00:00Z",
    )
    fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.create_progress_report(api, system["id"], "2026-07-01", "2026-07-31")

    readers = {
        "water_systems": api.list_water_systems(ADMIN_HEADERS),
        "service_lines": api.list_service_lines(ADMIN_HEADERS),
        "evidence_items": api.list_evidence_items(ADMIN_HEADERS),
        "verification_crews": api.list_verification_crews(ADMIN_HEADERS),
        "verification_appointments": api.list_verification_appointments(ADMIN_HEADERS),
        "sampling_batches": api.list_sampling_batches(ADMIN_HEADERS),
        "inventory_publications": api.list_inventory_publications(ADMIN_HEADERS),
        "customer_notifications": api.list_customer_notifications(ADMIN_HEADERS),
        "replacement_orders": api.list_replacement_orders(ADMIN_HEADERS),
        "street_projects": api.list_street_projects(ADMIN_HEADERS),
        "funding_sources": api.list_funding_sources(ADMIN_HEADERS),
        "progress_reports": api.list_progress_reports(ADMIN_HEADERS),
    }
    listed = {}
    for collection, response in readers.items():
        rows, meta = validate_paginated(response)
        assert len(rows) == 1, f"{collection} must list exactly one row"
        assert_list_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
        listed[collection] = rows[0]

    assert listed["sampling_batches"]["state"] == BatchState.VALIDATED
    assert listed["sampling_batches"]["valid_sample_count"] == 5
    assert listed["sampling_batches"]["percentile_90_ppb"] == pytest.approx(5.0)
    assert listed["inventory_publications"]["state"] == PublicationState.PUBLISHED
    assert listed["inventory_publications"]["basis"] == PublicationBasis.RECORDS
    assert listed["customer_notifications"]["state"] == NotificationState.PENDING
    assert listed["customer_notifications"]["service_line_id"] == line["id"]
    assert listed["replacement_orders"]["fulfillment_state"] == FulfillmentState.DRAFT
    assert listed["replacement_orders"]["consent_state"] == ConsentState.NOT_REQUESTED
    assert listed["verification_appointments"]["state"] == AppointmentState.SCHEDULED
    assert listed["verification_appointments"]["method"] == VerificationMethod.POTHOLE
    assert listed["verification_crews"]["status"] == CrewStatus.ACTIVE
    assert listed["street_projects"]["active_excavation_order_count"] == 0
    assert listed["funding_sources"]["status"] == FundingSourceStatus.ACTIVE
    assert listed["funding_sources"]["authorized_cents"] == 200000
    assert listed["funding_sources"]["available_cents"] == 200000
    assert listed["progress_reports"]["water_system_id"] == system["id"]
    assert "version" not in listed["progress_reports"]
    assert listed["water_systems"]["id"] == system["id"]
    assert listed["service_lines"]["id"] == line["id"]
    assert listed["evidence_items"]["service_line_id"] == line["id"]
