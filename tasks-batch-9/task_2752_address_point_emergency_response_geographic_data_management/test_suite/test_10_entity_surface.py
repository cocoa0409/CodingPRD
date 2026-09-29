"""Entity surface of the County Address and Emergency Response GIS API.

Queue B of the scaffold corner design: the `entities` section (creation,
retrieval, listing, not-found, required fields, declared defaults, computed
fields, server-assigned system fields, type constraints, immutability, parent
relationships and the self-referential supersession graph) plus the
`consistency_model` section (derived counters are immediate, never eventual).

Every test builds its own world through documented endpoints; the runner
restarts the server before each test, so each one starts from an empty
database with the logical clock at its startup value of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ANALYST_HEADERS,
    NON_EXISTENT_UUID,
    PERMIT_HEADERS,
    SYSADMIN_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_assignment_request,
    assert_boundary,
    assert_coverage_cell,
    assert_discrepancy_proposal,
    assert_exact_millisecond_timestamp,
    assert_jurisdiction,
    assert_log_row_fields,
    assert_ordered_by_created_at,
    assert_pagination_meta,
    assert_road_centerline,
    assert_score_equals,
    assert_slot_counters,
    expected_slot_capacity,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_create_jurisdiction_uppercases_postal_city_and_zeroes_counters(api):
    """
    Registering a **jurisdiction** captures its display `name` (one to 120 characters, non-blank), a short `code` used on provisioning exports (two to eight characters drawn from uppercase letters and digits, globally unique), a `jurisdiction_type` of `COUNTY`, `MUNICIPAL` or `UNINCORPORATED`, and the authoritative `postal_city` string for addresses inside it (one to 60 characters, stored uppercased whatever case the caller sent).
    A new jurisdiction begins with all four of its coverage counters — `cell_count`, `covered_cell_count`, `gap_pair_count` and `forward_gap_pair_count` — initialised to zero.

    Design: Corner/entities/create_jurisdiction_uppercases_postal_city_and_zeroes_counters
    """
    created = validate_success(
        api.create_jurisdiction(
            {
                "name": "Larimer County",
                "code": "LARCO",
                "jurisdiction_type": "COUNTY",
                "postal_city": "Fort Collins",
            },
            SYSADMIN_HEADERS,
        ),
        201,
    )

    assert_jurisdiction(
        created,
        name="Larimer County",
        code="LARCO",
        jurisdiction_type="COUNTY",
        postal_city="FORT COLLINS",
        cell_count=0,
        covered_cell_count=0,
        gap_pair_count=0,
        forward_gap_pair_count=0,
        version=1,
    )

    stored = validate_success(api.get_jurisdiction(created["id"], SYSADMIN_HEADERS), 200)
    assert stored["postal_city"] == "FORT COLLINS", (
        "postal_city is stored uppercased whatever case the caller sent"
    )
    assert stored["name"] == "Larimer County", "the display name is not uppercased"
    assert stored["code"] == "LARCO"
    assert stored["jurisdiction_type"] == "COUNTY"
    assert stored["cell_count"] == 0
    assert stored["covered_cell_count"] == 0
    assert stored["gap_pair_count"] == 0, (
        "no cells yet, so no (cell, service_type) pairs exist"
    )
    assert stored["forward_gap_pair_count"] == 0
    assert stored["version"] == 1


def test_get_road_centerline_returns_stored_record_with_full_capacity(api):
    """
    A `GisAnalyst` creates a **road centerline** by supplying its `primary_name` — the road name exactly as the county maintains it, spelling preserved verbatim, one to 120 characters and non-blank — the `jurisdiction_id` the segment falls in, and both address ranges in full: `from_addr_left`, `to_addr_left` and `parity_left` for the left side, and `from_addr_right`, `to_addr_right` and `parity_right` for the right.
    So "N. Maple St" uppercases to "N. MAPLE ST", loses its punctuation to become "N MAPLE ST", and expands its final token to `N MAPLE STREET`.
    The new centerline lands in `DRAFT` status with `qc_dirty` true, `open_discrepancy_case_count` at zero, and both slot counters set to the side's full capacity.

    Design: Corner/entities/get_road_centerline_returns_stored_record_with_full_capacity
    """
    jurisdiction = fx.setup_jurisdiction(api)
    road = fx.setup_road(api, jurisdiction["id"], primary_name="N. Maple St")

    fetched = validate_success(api.get_road_centerline(road["id"], ANALYST_HEADERS), 200)

    assert_road_centerline(
        fetched,
        primary_name="N. Maple St",
        normalized_name="N MAPLE STREET",
        status="DRAFT",
        qc_dirty=True,
        open_discrepancy_case_count=0,
        assignable_slot_count_left=50,
        assignable_slot_count_right=50,
    )
    assert_slot_counters(
        fetched, expected_slot_capacity(100, 198), expected_slot_capacity(101, 199)
    )
    assert fetched.get("retired_at") is None, "a DRAFT centerline has never been retired"
    assert fetched.get("retire_reason") is None


def test_list_address_points_excludes_retired_until_flag_and_paginates(api):
    """
    The listing operation excludes `RETIRED` and `VOIDED` points by default and includes them only when `include_retired` is requested as true — that flag is how a title researcher reaches historical addresses at all — and the listing may be narrowed by `road_centerline_id`, by `parent_address_point_id` to walk down a subaddress family, by `superseded_by_address_point_id` to walk a supersession chain, by `cell_id`, by `jurisdiction_id`, by `status` and by `side`.
    Collections are always sorted by `created_at` in ascending order.
    `total_count` is the number of rows matching the supplied filters *before* `limit` and `offset` are applied.
    `has_more` is true when the offset plus the number of rows actually returned in this page is still less than `total_count`.

    Design: Corner/entities/list_address_points_excludes_retired_until_flag_and_paginates
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=100, geometry_verified=True
    )
    point_102 = fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=102, geometry_verified=True
    )
    fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=104, geometry_verified=True
    )

    retired = fx.retire_point(api, point_102["id"], retire_reason="ANALYST_RETIRED")
    assert_address_point(retired, status="RETIRED", retire_reason="ANALYST_RETIRED")

    # First list: the RETIRED point is hidden by default.
    first_resp = api.list_address_points({"road_centerline_id": road_id}, ANALYST_HEADERS)
    first_rows, first_meta = validate_paginated(first_resp)
    assert first_resp.json()["response_type"] == "array", (
        "list responses carry response_type of array"
    )
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is False
    assert len(first_rows) == 2
    assert [row["house_number"] for row in first_rows] == [100, 104]
    assert_ordered_by_created_at(first_rows)

    # Second list: include_retired reaches the historical row.
    second_rows, second_meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": road_id, "include_retired": "true"}, ANALYST_HEADERS
        )
    )
    assert second_meta["total_count"] == 3
    assert [row["house_number"] for row in second_rows] == [100, 102, 104]
    assert_ordered_by_created_at(second_rows)

    # Third list: limit 1 offset 1 lands exactly on the second created_at ASC row.
    third_rows, third_meta = validate_paginated(
        api.list_address_points(
            {
                "road_centerline_id": road_id,
                "include_retired": "true",
                "limit": 1,
                "offset": 1,
            },
            ANALYST_HEADERS,
        )
    )
    assert_pagination_meta(third_meta, limit=1, offset=1, total_count=3, returned=1)
    assert len(third_rows) == 1
    assert third_rows[0]["id"] == point_102["id"]
    assert third_rows[0]["house_number"] == 102
    assert third_meta["has_more"] is True, "offset(1) + len(data)(1) < total_count(3)"

    stored = fx.read_point(api, point_102["id"])
    assert stored["status"] == "RETIRED"
    assert stored["retire_reason"] == "ANALYST_RETIRED"


def test_get_jurisdiction_with_unknown_id_not_found(api):
    """
    Each entity has its own 404 code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_COVERAGE_CELL_NOT_FOUND`, `ERR_ROAD_NOT_FOUND`, `ERR_ADDRESS_POINT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_BOUNDARY_NOT_FOUND`, `ERR_CELL_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and `ERR_PROPOSAL_NOT_FOUND`.
    The `message` provides a human-readable explanation of what went wrong.

    Design: Corner/entities/get_jurisdiction_with_unknown_id_not_found
    """
    resp = api.get_jurisdiction(NON_EXISTENT_UUID, SYSADMIN_HEADERS)

    error = validate_error(resp, ApiErrorId.JURISDICTION_NOT_FOUND, 404)
    assert resp.status_code == 404
    assert error["error_id"] == "ERR_JURISDICTION_NOT_FOUND"
    body = resp.json()
    assert body["response_type"] == "error", "not an empty 200 object"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""


def test_create_coverage_cell_missing_cell_code_rejected(api):
    """
    Creating one — the single write operation shared between `SystemAdmin` and `GisAnalyst` — captures a `cell_code` (one to 12 characters of uppercase letters and digits, unique inside its `jurisdiction_id`), the `jurisdiction_id` it belongs to, and optional informational `centroid_lat` and `centroid_lon` values that default to null and are never consulted in any business decision.
    Schema-level failures all collapse into `ERR_INVALID_REQUEST` (HTTP 400): a required field missing or null, a field of the wrong JSON type, a string outside its length bound, an enum value outside its declared set, a negative integer where a non-negative one is required, a `latitude` outside the range of −90 through 90 or a `longitude` outside −180 through 180, a malformed datetime, a bad pagination parameter, or a mutually exclusive scope pair supplied wrongly.

    Design: Corner/entities/create_coverage_cell_missing_cell_code_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)

    resp = api.create_coverage_cell(
        {"jurisdiction_id": jurisdiction["id"]}, ANALYST_HEADERS
    )

    error = validate_error(resp, ApiErrorId.INVALID_REQUEST, 400)
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    stored = fx.read_jurisdiction(api, jurisdiction["id"])
    assert stored["cell_count"] == 0, "the rejected write created no CoverageCell"
    assert stored["gap_pair_count"] == 0

    rows, meta = validate_paginated(
        api.list_coverage_cells({"jurisdiction_id": jurisdiction["id"]}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_create_address_point_applies_every_declared_default(api):
    """
    Six further fields are optional: `house_number_suffix`, an alpha suffix of up to four uppercase letters such as "A" that defaults to null and forms part of the duplicate-address key; `unit_type`, `unit_id` and `parent_address_point_id`, which together describe a subaddress unit and all default to null; `geometry_verified`, a boolean defaulting to false; and the informational `latitude` and `longitude`, both defaulting to null and never consulted in any business decision.
    And `status` begins as `PENDING`, meaning authored but not yet authoritative.
    A successful creation computes the point's `confidence_score` under the provisional variant, sets `confidence_basis` to `PROVISIONAL`, leaves `certified_confidence_score` null, increments the nominated parent's `unit_child_count` when a `unit_id` was supplied, and refreshes the centerline's assignable-slot counters.
    Its raw value is assembled by starting from the base weight for the point's `source` — 70 for `PARCEL`, 60 for `PERMIT`, 45 for `POSTAL`, and 80 for `FIELD` — then adding 12 when `geometry_verified` is true, adding 8 when the point's `postal_city` equals the postal city of its jurisdiction, adding 6 when `unit_id` is null (that is, when the point is a base address rather than a unit), and finally subtracting the road-status penalty, which is 15 while the centerline is `DRAFT`, 5 while it is `VALIDATED` and 0 once it is `PUBLISHED`.

    Design: Corner/entities/create_address_point_applies_every_declared_default
    """
    world = fx.setup_draft_road_world(api)

    created = validate_success(
        api.create_address_point(
            {
                "house_number": 100,
                "road_centerline_id": world["road_id"],
                "side": "LEFT",
                "source": "POSTAL",
                "postal_city": "FORT COLLINS",
                "cell_id": world["cell_id"],
            },
            ANALYST_HEADERS,
        ),
        201,
    )

    assert_address_point(
        created,
        geometry_verified=False,
        status="PENDING",
        confidence_basis="PROVISIONAL",
        unit_child_count=0,
        house_number=100,
        source="POSTAL",
        side="LEFT",
    )
    assert created["house_number_suffix"] is None
    assert created["unit_type"] is None
    assert created["unit_id"] is None
    assert created["parent_address_point_id"] is None
    assert created.get("superseded_by_address_point_id") is None
    assert created["latitude"] is None
    assert created["longitude"] is None
    assert created["certified_confidence_score"] is None
    assert created.get("retired_at") is None
    assert created.get("retire_reason") is None
    # 45 POSTAL + 0 geometry + 8 postal-city match + 6 base address - 15 DRAFT road
    assert_score_equals(created["confidence_score"], 44.00, "confidence_score")

    stored = fx.read_point(api, created["id"])
    assert_score_equals(stored["confidence_score"], 44.00, "confidence_score")
    assert stored["confidence_basis"] == "PROVISIONAL"
    assert stored["certified_confidence_score"] is None


def test_address_point_jurisdiction_id_copied_from_its_centerline(api):
    """
    The point's `jurisdiction_id` is copied from the referenced centerline's `jurisdiction_id` at creation and is never independently editable afterwards.
    Its raw value is assembled by starting from the base weight for the point's `source` — 70 for `PARCEL`, 60 for `PERMIT`, 45 for `POSTAL`, and 80 for `FIELD` — then adding 12 when `geometry_verified` is true, adding 8 when the point's `postal_city` equals the postal city of its jurisdiction, adding 6 when `unit_id` is null (that is, when the point is a base address rather than a unit), and finally subtracting the road-status penalty, which is 15 while the centerline is `DRAFT`, 5 while it is `VALIDATED` and 0 once it is `PUBLISHED`.

    Design: Corner/entities/address_point_jurisdiction_id_copied_from_its_centerline
    """
    larco = fx.setup_jurisdiction(api)
    weldco = fx.setup_jurisdiction(
        api, name="Weld County", code="WELDCO", postal_city="GREELEY"
    )
    weld_cell = fx.setup_coverage_cell(api, weldco["id"], "W001")
    weld_road = fx.setup_road(
        api, weldco["id"], primary_name="E 8TH STREET"
    )

    created = validate_success(
        api.create_address_point(
            {
                "house_number": 100,
                "road_centerline_id": weld_road["id"],
                "side": "LEFT",
                "source": "PARCEL",
                "postal_city": "GREELEY",
                "cell_id": weld_cell["id"],
                "geometry_verified": True,
            },
            ANALYST_HEADERS,
        ),
        201,
    )

    assert created["jurisdiction_id"] == weldco["id"], (
        "jurisdiction_id is copied from the referenced centerline"
    )
    assert created["jurisdiction_id"] != larco["id"]
    # 70 PARCEL + 12 geometry + 8 GREELEY matches WELDCO + 6 base - 15 DRAFT
    assert_score_equals(created["confidence_score"], 81.00, "confidence_score")

    stored = fx.read_point(api, created["id"])
    assert stored["jurisdiction_id"] == weldco["id"]

    _, larco_meta = validate_paginated(
        api.list_address_points({"jurisdiction_id": larco["id"]}, ANALYST_HEADERS)
    )
    assert larco_meta["total_count"] == 0, "no point was stamped with the first county"

    weld_rows, weld_meta = validate_paginated(
        api.list_address_points({"jurisdiction_id": weldco["id"]}, ANALYST_HEADERS)
    )
    assert weld_meta["total_count"] == 1
    assert weld_rows[0]["id"] == created["id"]


def test_assignment_request_system_fields_are_server_assigned(api):
    """
    The `review_status` dimension tracks GIS review and begins at `PENDING_REVIEW`, moving to either `GIS_APPROVED` or `GIS_REJECTED`.
    The `utility_status` dimension tracks utility coordination and begins at `PENDING_UTILITY`, moving to `UTILITY_CLEARED` or `UTILITY_HELD`.
    The `fulfillment_status` dimension is **derived** from the join of the first two plus the assignment and void outcomes; it begins at `OPEN` and may reach `READY_TO_ASSIGN`, `FULFILLED`, `CLOSED_REJECTED` or `VOIDED`, of which the last three are terminal.
    Two optional fields shape the outcome: `requested_unit_count`, the number of subaddress units to mint beneath the base address, an integer from 0 through 99 that defaults to 0 and where 0 means a base address only; and `proposed_house_number`, an operator-preferred number that defaults to null.

    Design: Corner/entities/assignment_request_system_fields_are_server_assigned
    """
    world = fx.setup_validated_road_world(api)

    created = validate_success(
        api.create_assignment_request(
            {
                "permit_number": "BP-2026-0100",
                "parcel_id": "8712300100",
                "road_centerline_id": world["road_id"],
                "side": "LEFT",
            },
            PERMIT_HEADERS,
        ),
        201,
    )

    assert_assignment_request(
        created,
        review_status="PENDING_REVIEW",
        utility_status="PENDING_UTILITY",
        fulfillment_status="OPEN",
        requested_unit_count=0,
        minted_point_count=0,
        version=1,
    )
    assert created["proposed_house_number"] is None
    assert created.get("assigned_address_point_id") is None
    assert created.get("assigned_house_number") is None
    assert created.get("void_reason") is None

    stored = fx.read_request(api, created["id"])
    assert stored["review_status"] == "PENDING_REVIEW"
    assert stored["utility_status"] == "PENDING_UTILITY"
    assert stored["fulfillment_status"] == "OPEN"
    assert stored["minted_point_count"] == 0
    assert stored["version"] == 1


def test_create_agency_with_unknown_agency_type_rejected(api):
    """
    Registering a **responding agency** captures its `name` (one to 120 characters, non-blank), its `agency_type` — exactly one of `LAW`, `FIRE` or `EMS` — the `jurisdiction_id` of the jurisdiction that charters it, and an optional `contact_phone` that defaults to null and is purely informational.
    Schema-level failures all collapse into `ERR_INVALID_REQUEST` (HTTP 400): a required field missing or null, a field of the wrong JSON type, a string outside its length bound, an enum value outside its declared set, a negative integer where a non-negative one is required, a `latitude` outside the range of −90 through 90 or a `longitude` outside −180 through 180, a malformed datetime, a bad pagination parameter, or a mutually exclusive scope pair supplied wrongly.

    Design: Corner/entities/create_agency_with_unknown_agency_type_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)

    resp = api.create_agency(
        {
            "name": "Larimer Search and Rescue",
            "agency_type": "SAR",
            "jurisdiction_id": jurisdiction["id"],
        },
        SYSADMIN_HEADERS,
    )

    error = validate_error(resp, ApiErrorId.INVALID_REQUEST, 400)
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    rows, meta = validate_paginated(
        api.list_agencies({"jurisdiction_id": jurisdiction["id"]}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0, "no Agency row is created"
    assert rows == []


def test_discrepancy_proposal_is_append_only_without_version_field(api):
    """
    `DiscrepancyProposal` is an append-only log row: it carries only `id` and `created_at`.
    It has no `updated_at` and no `version`, because a filed proposal is never rewritten — its `status` is a pure projection computed from its sibling rows and its parent case, as described in §3.8.
    Its `round_number` is the 1-based ordinal of the filing within the case, equal to the case's `round_count` after the filing.
    Its `proposed_by_side` is derived from the caller: `OPENER` when `X-User-ID` equals the case's `opened_by_agency_id`, and `COUNTERPARTY` when it equals the case's `counterparty_agency_id`.
    For a proposal on a case: if the case's `status` is `ADOPTED` and this proposal is the case's `current_proposal_id`, the proposal projects to `ADOPTED`; otherwise, if the case's `status` is `ESCALATED` or `ARBITRATED`, it projects to `VOIDED`; otherwise, if some proposal on the same case has a greater `round_number`, it projects to `COUNTERED`; otherwise it projects to `PENDING`.

    Design: Corner/entities/discrepancy_proposal_is_append_only_without_version_field
    """
    jurisdiction = fx.setup_jurisdiction(api)
    road = fx.setup_road(api, jurisdiction["id"])
    law = fx.setup_agency(api, jurisdiction["id"], "LAW")
    fire = fx.setup_agency(api, jurisdiction["id"], "FIRE")
    case = fx.setup_discrepancy_case(
        api,
        road["id"],
        law["id"],
        fire["id"],
        "ROAD_NAME",
        description="The sheriff records this segment as N MAPLE AVE, not N MAPLE ST",
    )

    resp = api.create_proposal(
        case["id"],
        {
            "proposed_value": "N MAPLE AVE",
            "expected_case_version": case["version"],
            "rationale": "Matches the 1998 annexation plat",
        },
        make_agency_liaison_headers(law["id"]),
    )
    proposal = validate_success(resp, 201)

    assert "id" in proposal
    assert "created_at" in proposal
    assert "version" not in proposal, "a filed proposal carries no version"
    assert "updated_at" not in proposal, "a filed proposal carries no updated_at"
    assert_log_row_fields(proposal)
    assert_discrepancy_proposal(
        proposal, round_number=1, proposed_by_side="OPENER", status="PENDING"
    )

    rows, meta = validate_paginated(api.list_proposals(case["id"], {}, ANALYST_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == proposal["id"]
    assert rows[0]["status"] == "PENDING"
    assert_log_row_fields(rows[0])


def test_create_cell_assignment_with_unknown_cell_not_found(api):
    """
    The order is: authentication (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_UNAUTHORIZED`), then agency identity ownership (`ERR_AGENCY_IDENTITY_MISMATCH`), then path-entity existence, then referenced-entity existence, then request-schema validity (`ERR_INVALID_REQUEST`), then target-state legality, then expected-version staleness, and only then the domain-specific business rules of §2.8 onwards in the order in which they are introduced there.
    A `jurisdiction_id`, `agency_id`, `road_centerline_id`, `cell_id`, `parent_address_point_id`, `superseded_by_address_point_id`, `qc_report_id`, `counterparty_agency_id` or `proposal_id` that does not resolve raises the referenced entity's own not-found code.
    The new boundary lands in `DRAFT` status with `assigned_cell_count` at zero and `retired_at` and `retire_reason` both null.

    Design: Corner/entities/create_cell_assignment_with_unknown_cell_not_found
    """
    jurisdiction = fx.setup_jurisdiction(api)
    law = fx.setup_agency(api, jurisdiction["id"], "LAW")
    boundary = fx.setup_boundary(
        api, law["id"], effective_start="2026-08-01T00:00:00Z"
    )
    assert boundary["version"] == 1

    resp = api.create_cell_assignment(
        boundary["id"],
        {
            "cell_id": NON_EXISTENT_UUID,
            "effective_start": "2026-08-01T00:00:00Z",
            "expected_boundary_version": boundary["version"],
        },
        make_agency_liaison_headers(law["id"]),
    )

    error = validate_error(resp, ApiErrorId.COVERAGE_CELL_NOT_FOUND, 404)
    assert error["error_id"] == "ERR_COVERAGE_CELL_NOT_FOUND"

    stored = fx.read_boundary(api, boundary["id"])
    assert_boundary(
        stored, assigned_cell_count=0, version=1, status="DRAFT"
    )
    assert stored["version"] == 1, "the rejected write did not bump it"

    rows, meta = validate_paginated(
        api.list_boundary_cell_assignments_of(boundary["id"], {}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_subaddress_unit_hangs_off_base_point_and_bumps_child_count(api):
    """
    Valid subaddress designators for `unit_type` are `UNIT`, `APT`, `STE` and `BLDG`; `unit_id` itself is up to eight characters of uppercase letters and digits, such as "3B".
    The `unit_child_count` on any point is the number of points whose `parent_address_point_id` equals it and whose `status` is `PENDING` or `ACTIVE`.
    Subaddress units never consume a slot, because they share their parent's `house_number`; and points in `RETIRED` or `VOIDED` status release the slot they were holding.
    Its raw value is assembled by starting from the base weight for the point's `source` — 70 for `PARCEL`, 60 for `PERMIT`, 45 for `POSTAL`, and 80 for `FIELD` — then adding 12 when `geometry_verified` is true, adding 8 when the point's `postal_city` equals the postal city of its jurisdiction, adding 6 when `unit_id` is null (that is, when the point is a base address rather than a unit), and finally subtracting the road-status penalty, which is 15 while the centerline is `DRAFT`, 5 while it is `VALIDATED` and 0 once it is `PUBLISHED`.

    Design: Corner/entities/subaddress_unit_hangs_off_base_point_and_bumps_child_count
    """
    world = fx.setup_draft_road_world(api)
    base = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=100, geometry_verified=True
    )

    unit = validate_success(
        api.create_address_point(
            {
                "house_number": 100,
                "road_centerline_id": world["road_id"],
                "side": "LEFT",
                "source": "PARCEL",
                "postal_city": "FORT COLLINS",
                "cell_id": world["cell_id"],
                "geometry_verified": True,
                "unit_type": "UNIT",
                "unit_id": "3B",
                "parent_address_point_id": base["id"],
            },
            ANALYST_HEADERS,
        ),
        201,
    )

    assert_address_point(
        unit,
        parent_address_point_id=base["id"],
        unit_type="UNIT",
        unit_id="3B",
        house_number=100,
        status="PENDING",
    )
    # 70 PARCEL + 12 geometry + 8 postal-city match + 0 base bonus - 15 DRAFT road
    assert_score_equals(unit["confidence_score"], 75.00, "confidence_score")

    stored_base = fx.read_point(api, base["id"])
    # The base address keeps its 6.00 base-address bonus: 70 + 12 + 8 + 6 - 15.
    assert_score_equals(stored_base["confidence_score"], 81.00, "confidence_score")
    assert stored_base["unit_child_count"] == 1

    road = fx.read_road(api, world["road_id"])
    assert road["assignable_slot_count_left"] == 49, "the unit consumed no slot"


def test_retired_point_supersede_chain_is_queryable_for_records_research(api):
    """
    When an address is renumbered rather than simply abandoned, the analyst records the successor at retirement time by supplying `superseded_by_address_point_id`, which must reference a point whose `status` is `PENDING` or `ACTIVE`.
    The point moves to `RETIRED` with `retired_at` stamped at the logical clock instant, and `retire_reason` is recorded as `REPLACED` when a successor was supplied and as `ANALYST_RETIRED` when it was not.
    The server maintains a **logical UTC clock** whose value at startup is exactly `2026-08-01T00:00:00Z`, and every temporal decision — coverage window containment, the forward coverage horizon, publication cadence, defect staleness horizons, and every `retired_at`, `certified_at`, `sealed_at`, `published_at`, `staled_at`, `waived_at`, `escalated_at` and `adopted_at` stamp — reads that logical instant.
    Subaddress units never consume a slot, because they share their parent's `house_number`; and points in `RETIRED` or `VOIDED` status release the slot they were holding.

    Design: Corner/entities/retired_point_supersede_chain_is_queryable_for_records_research
    """
    world = fx.setup_draft_road_world(api)
    old_point = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=100, geometry_verified=True
    )
    new_point = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=102, geometry_verified=True
    )

    retired = validate_success(
        api.retire_address_point(
            old_point["id"],
            {
                "retire_reason": "REPLACED",
                "superseded_by_address_point_id": new_point["id"],
            },
            ANALYST_HEADERS,
        ),
        200,
    )

    assert_address_point(
        retired,
        status="RETIRED",
        retire_reason="REPLACED",
        superseded_by_address_point_id=new_point["id"],
    )
    assert_exact_millisecond_timestamp(retired["retired_at"], "retired_at")
    assert retired["retired_at"] == "2026-08-01T00:00:00.000Z"

    successor = fx.read_point(api, new_point["id"])
    assert successor["status"] == "PENDING", "the successor is untouched"

    rows, meta = validate_paginated(
        api.list_address_points(
            {
                "superseded_by_address_point_id": new_point["id"],
                "include_retired": "true",
            },
            ANALYST_HEADERS,
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == old_point["id"]
    assert rows[0]["retire_reason"] == "REPLACED"

    road = fx.read_road(api, world["road_id"])
    assert road["assignable_slot_count_left"] == 49, (
        "100 released its slot, 102 still holds one"
    )


def test_derived_counters_are_visible_in_the_same_response(api):
    """
    Whenever a `BoundaryCellAssignment` row is created or changes status, or a `CoverageCell` is created, the owning `Jurisdiction` recomputes `cell_count`, `covered_cell_count`, `gap_pair_count` and `forward_gap_pair_count`, and each affected `CoverageCell` recomputes `active_assignment_count`.
    Whenever an address point on a centerline is created or changes status, or the centerline's range or parity fields change, that centerline recomputes `assignable_slot_count_left` and `assignable_slot_count_right`.
    The new cell's `active_assignment_count` starts at zero, and creating it refreshes the owning jurisdiction's counters — which means `cell_count` rises and, since a brand-new cell is claimed by nobody, the gap counters rise with it.
    A jurisdiction's `gap_pair_count` is the number of gap pairs across all of its cells taken against all three service types; its `covered_cell_count` is the number of its cells that have exactly one covering `ACTIVE` assignment for **all three** service types simultaneously; and a cell's own `active_assignment_count` is the number of `ACTIVE` assignments covering the current instant on that cell, summed across service types.
    For each cell-and-service-type pair, the `ACTIVE` assignments' half-open windows are clipped to that thirty-day horizon and merged, and the pair counts as a **forward gap** when the merged union does not cover the whole horizon.

    Design: Corner/consistency_model/derived_counters_are_visible_in_the_same_response
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    assert jurisdiction["cell_count"] == 0
    assert jurisdiction["covered_cell_count"] == 0
    assert jurisdiction["gap_pair_count"] == 0

    # The cell creation response itself already carries the child's own counter.
    cell = validate_success(
        api.create_coverage_cell(
            {"cell_code": "C001", "jurisdiction_id": j_id}, ANALYST_HEADERS
        ),
        201,
    )
    assert_coverage_cell(cell, active_assignment_count=0, jurisdiction_id=j_id)

    # The immediately following read shows the recomputed ancestor counters with
    # no intervening write of any kind.
    after_cell = validate_success(api.get_jurisdiction(j_id, ANALYST_HEADERS), 200)
    assert after_cell["cell_count"] == 1
    assert after_cell["gap_pair_count"] == 3, "1 cell x 3 service types"
    assert after_cell["forward_gap_pair_count"] == 3
    assert after_cell["covered_cell_count"] == 0

    road = validate_success(
        api.create_road_centerline(
            {
                "primary_name": "N MAPLE STREET",
                "jurisdiction_id": j_id,
                "from_addr_left": 100,
                "to_addr_left": 198,
                "parity_left": "EVEN",
                "from_addr_right": 101,
                "to_addr_right": 199,
                "parity_right": "ODD",
            },
            ANALYST_HEADERS,
        ),
        201,
    )
    assert road["assignable_slot_count_left"] == 50
    assert road["assignable_slot_count_right"] == 50

    _, road_meta = validate_paginated(
        api.list_road_centerlines({"jurisdiction_id": j_id}, ANALYST_HEADERS)
    )
    assert road_meta["total_count"] == 1

    point = validate_success(
        api.create_address_point(
            {
                "house_number": 100,
                "road_centerline_id": road["id"],
                "side": "LEFT",
                "source": "PARCEL",
                "postal_city": "FORT COLLINS",
                "cell_id": cell["id"],
                "geometry_verified": True,
            },
            ANALYST_HEADERS,
        ),
        201,
    )
    # 70 PARCEL + 12 geometry + 8 postal-city match + 6 base - 15 DRAFT road
    assert_score_equals(point["confidence_score"], 81.00, "confidence_score")
    assert point["confidence_basis"] == "PROVISIONAL"

    road_after_point = validate_success(
        api.get_road_centerline(road["id"], ANALYST_HEADERS), 200
    )
    assert road_after_point["assignable_slot_count_left"] == 49, (
        "the parent counter is already decremented"
    )
    assert road_after_point["assignable_slot_count_right"] == 50

    point_rows, point_meta = validate_paginated(
        api.list_address_points({"road_centerline_id": road["id"]}, ANALYST_HEADERS)
    )
    assert point_meta["total_count"] == 1, "immediately, with no refresh call of any kind"
    assert point_rows[0]["id"] == point["id"]
