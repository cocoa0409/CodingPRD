"""District/segment inventory, response envelope, pagination, and defect-record shape."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_defect_observation,
    assert_district,
    assert_segment,
    create_district,
    create_district_payload,
    create_lateral,
    create_open_cycle,
    create_segment,
    create_segment_payload,
    create_technician,
    drive_inspection_to_coding,
    make_coder_headers,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def test_district_create_applies_defaults_and_computed_zero(api):
    """PRD §3.1: "Two policy knobs are optional: `notice_lead_hours`, the required
    customer-notice lead time before a bypass activation or excavation, defaults to
    48 hours when omitted, and `warranty_months`, the warranty window that runs from
    each work order's completion, defaults to 12 months."
    PRD §3.1: "The district's `budget_committed_cents` is never written by clients:
    it starts at 0 and is maintained by the system as the running sum of provisional
    totals over the district's plans that sit in `APPROVED` or `EXECUTING` status."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/district_create_applies_defaults_and_computed_zero
    """
    resp = api.create_district(
        create_district_payload(name="D-E1", ii_reduction_target_pct=20, budget_cents=1000000),
        ENGINEER,
    )
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert isinstance(resp.json()["meta"]["api_request_id"], str)
    assert_district(data)
    assert data["notice_lead_hours"] == 48, "default notice lead must be 48 hours"
    assert data["warranty_months"] == 12, "default warranty window must be 12 months"
    assert data["budget_committed_cents"] == 0, "budget commitment ledger starts at 0"


def test_segment_missing_required_field_returns_invalid_request(api):
    """PRD §3.2: "Creating one records a `segment_ref` — the upstream-to-downstream
    manhole reference, formatted like 'MH-104->MH-105' and unique within the district —
    a `diameter_mm` that later drives both the mobilization price tier and the
    pump-sizing rule, a `material` drawn from `VCP`, `RCP`, `PVC`, `HDPE`, `CI`, and
    `BRICK`, a `length_m` that must be greater than zero, and the `install_year`."
    Omitting the required `diameter_mm` makes the payload malformed, rejected with
    ERR_INVALID_REQUEST (HTTP 400 — the catalogue's malformed-payload error).

    Design: Corner/entities/segment_missing_required_field_returns_invalid_request
    """
    district = create_district(name="D-E2", ii_reduction_target_pct=20, budget_cents=1000000)
    payload = {
        "segment_ref": "MH-1->MH-2",
        "material": "VCP",
        "length_m": 100,
        "install_year": 1980,
    }  # diameter_mm deliberately omitted
    resp = api.create_segment(district["id"], payload, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_segment_computed_fields_ignore_client_input(api):
    """PRD §3.2: "Everything about a segment's condition is computed rather than
    written: `structural_grade` and `om_grade` both begin at 0, `quick_rating` and
    `structural_index` remain null until the segment's first certified inspection,
    and `last_rehab_completed_at` stays null until a work order completes."

    Design: Corner/entities/segment_computed_fields_ignore_client_input
    """
    district = create_district(name="D-E3", ii_reduction_target_pct=20, budget_cents=1000000)
    resp = api.create_segment(
        district["id"],
        create_segment_payload(segment_ref="MH-1->MH-2", diameter_mm=200, material="VCP",
                               length_m=100, install_year=1980),
        ENGINEER,
    )
    data = validate_success(resp, 201)
    assert_segment(data)
    assert data["structural_grade"] == 0
    assert data["om_grade"] == 0
    assert data["rehab_status"] == "NONE"
    assert data["quick_rating"] is None
    assert data["structural_index"] is None


def test_defect_observation_immutable_no_version_field(api):
    """PRD §2.5: "Defect observations are append-only records that are never updated
    in place, so a `DefectObservation` carries only `id` and `created_at`; both
    `updated_at` and `version` are absent from it."
    PRD §3.3: "an optional `extent_m` that defaults to 0 for point defects."

    Design: Corner/entities/defect_observation_immutable_no_version_field
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-E4", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])

    resp = api.create_defect(
        inspection["id"],
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
         "distance_m": 10, "clock_position": 6},  # extent_m deliberately omitted
        make_coder_headers(coder["id"]),
    )
    data = validate_success(resp, 201)
    assert_defect_observation(data)  # asserts absence of updated_at and version
    assert data["extent_m"] == 0, "omitted extent_m must default to 0"


def test_entity_not_found_returns_404(api):
    """PRD §2.6: "When an endpoint path contains several identifiers, the server
    confirms that each identifier exists and belongs to its declared parent scope
    before examining anything deeper, and the first identifier that fails this check
    produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_segment(NON_EXISTENT_UUID, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_pagination_defaults_on_list_endpoint(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned in one
    page: it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses carry four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_defaults_on_list_endpoint
    """
    create_district(name="D-E6", ii_reduction_target_pct=20, budget_cents=1000000)
    resp = api.list_districts(ENGINEER)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["limit"] == 10, "default page size must be 10"
    assert meta["offset"] == 0, "default offset must be 0"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_lateral_reverse_reachability_filtered_list(api):
    """PRD §3.2: "Adding one records an `address` unique within the segment, a
    `connection_type` of `DIRECT`, `WYE`, or `SADDLE`, and an optional `active` flag
    that defaults to true; a lateral's `reinstated` flag always starts false."

    Design: Corner/endpoints/lateral_reverse_reachability_filtered_list
    """
    district = create_district(name="D-P3", ii_reduction_target_pct=20, budget_cents=1000000)
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    create_lateral(segment["id"], address="1 Pine St", connection_type="DIRECT")
    resp = api.list_laterals(segment["id"], ENGINEER)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["address"] == "1 Pine St"
    assert data[0]["reinstated"] is False, "a lateral's reinstated flag always starts false"
