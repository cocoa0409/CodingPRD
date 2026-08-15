"""Registry claims: declared defaults, request-shape discipline, nested and
missing resources, append-only outage shape, initial entity state, computed
parcel exposure, the response envelope, list pagination and filtering, and
immediate read-after-write consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_complainant,
    assert_flight_operation,
    assert_land_use_parcel,
    assert_monitor_outage,
    assert_noise_complaint,
    create_complainant,
    create_monitor,
    create_operator,
    create_outage_payload,
    record_outage,
    create_study,
    add_parcel,
    advance_study,
    create_flight_payload,
    create_complaint,
    make_complainant_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

LIAISON = TEST_USERS["community_liaison_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
ADMIN = TEST_USERS["noise_office_admin_headers"]


def test_complainant_create_applies_defaults(api):
    """PRD 3.1: "an `outreach_opt_in` flag that defaults to `true` when omitted".
    PRD 3.1: "At registration the standing is `GOOD_STANDING` and all counters are zero."

    Design: Corner/entities/complainant_create_applies_defaults
    """
    response = api.create_complainant(
        {
            "full_name": "Def One",
            "email": "def1@x.com",
            "address_line": "1 Default Dr",
            "zone_code": "Z1",
        },
        LIAISON,
    )
    complainant = validate_success(response, 201)
    assert_complainant(complainant)

    assert complainant["outreach_opt_in"] is True
    assert complainant["standing"] == "GOOD_STANDING"
    assert complainant["complaints_90d"] == 0
    assert complainant["filed_total"] == 0
    assert complainant["open_count"] == 0
    assert complainant["version"] == 1

    reread = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert reread["outreach_opt_in"] is True
    assert reread["standing"] == "GOOD_STANDING"
    assert reread["complaints_90d"] == 0


def test_complainant_create_missing_email_returns_invalid_request(api):
    """PRD 2.11 gate 2: "required fields are present, types and enum members are valid"
    with failures "rejected with `ERR_VALIDATION`".

    Design: Corner/entities/complainant_create_missing_email_returns_invalid_request
    """
    response = api.create_complainant(
        {"full_name": "No Mail", "address_line": "2 Void St", "zone_code": "Z1"},
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_complaint_create_system_fields_input_ignored(api):
    """PRD 2.11 gate 2: "Unknown fields, and system-managed or computed fields sent
    in the request body, are ignored — never rejected."
    PRD 3.4: "A new complaint is `RECEIVED`".

    Design: Corner/entities/complaint_create_system_fields_input_ignored
    """
    complainant = create_complainant(full_name="Sys One", email="sys1@x.com")

    response = api.create_complaint(
        {
            "complainant_id": complainant["id"],
            "occurred_at": "2026-07-15T09:00:00Z",
            "channel": "WEB",
            "disturbance_type": "OTHER",
            "status": "CLOSED_SUBSTANTIATED",
            "version": 99,
        },
        make_complainant_headers(complainant["id"]),
    )
    complaint = validate_success(response, 201)
    assert_noise_complaint(complaint)
    assert complaint["status"] == "RECEIVED"
    assert complaint["version"] == 1


def test_complaint_get_nonexistent_returns_not_found(api):
    """PRD 2.10: "The request is rejected immediately with a `404 Not Found` error
    carrying `ERR_NOT_FOUND` for the *first* identifier in the path that does not
    resolve, before any later segment or business rule is examined."

    Design: Corner/entities/complaint_get_nonexistent_returns_not_found
    """
    response = api.get_complaint(NON_EXISTENT_UUID, ANALYST)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_monitor_outage_immutable_record_has_no_version(api):
    """PRD 2.5: "The single exception is the **MonitorOutage** record. An outage is
    an append-only interval and carries only `id` and `created_at`; both `updated_at`
    and `version` are absent from it, because an outage is never mutated after it
    is recorded."

    Design: Corner/entities/monitor_outage_immutable_record_has_no_version
    """
    monitor = create_monitor(station_code="IM1")
    outage = record_outage(
        monitor["id"],
        start_at="2026-07-10T10:00:00Z",
        end_at="2026-07-10T11:00:00Z",
        outage_type="CALIBRATION",
    )

    outages, meta = validate_paginated(api.list_outages(monitor["id"], ANALYST))
    assert meta["total_count"] == 1
    assert outages[0]["id"] == outage["id"]
    assert_monitor_outage(outages[0])


def test_flight_created_with_initial_state_and_zero_links(api):
    """PRD 3.2: "New flights are `SCHEDULED`."
    PRD 3.2: "The moment a flight becomes `OPERATED`, the system computes two flags
    exactly once and never recomputes them: `curfew_movement` and `curfew_violation`,
    both starting from a default of `false`."

    Design: Corner/entities/flight_created_with_initial_state_and_zero_links
    """
    operator = create_operator(name="Air Nine", iata_code="A9")
    response = api.create_flight(
        create_flight_payload(
            operator["id"],
            flight_number="A9100",
            scheduled_at="2026-08-05T10:00:00Z",
        ),
        ADMIN,
    )
    flight = validate_success(response, 201)
    assert_flight_operation(flight)
    assert flight["status"] == "SCHEDULED"
    assert flight["curfew_movement"] is False
    assert flight["curfew_violation"] is False
    assert flight["linked_complaint_count"] == 0
    assert flight["linked_event_count"] == 0
    assert flight.get("actual_at") is None


def test_parcel_computed_band_and_compatibility_on_create(api):
    """PRD 3.7: "While the owning study is not yet `ADOPTED`, the `PRELIMINARY`
    variant applies: `dnl_db_effective` is the modeled level minus a conservative
    1.5 dB adjustment, rounded half-up to one decimal."
    PRD 3.7: "for `RESIDENTIAL`, `SCHOOL`, and `HOSPITAL` parcels, an effective level
    of at least 65.0 is `INCOMPATIBLE_RESIDENTIAL`".
    PRD 3.7: "The `insulation_eligible` flag is `true` exactly when the compatibility
    status is `INCOMPATIBLE_RESIDENTIAL`".

    Design: Corner/entities/parcel_computed_band_and_compatibility_on_create
    """
    study = create_study(title="Part150 Lambda")
    advance_study(study["id"], "DATA_COLLECTION")

    response = api.create_parcel(
        study["id"],
        {
            "parcel_ref": "P-900",
            "land_use": "RESIDENTIAL",
            "dnl_db_measured": 64.0,
            "dnl_db_modeled": 67.0,
            "zone_code": "Z1",
        },
        TEST_USERS["study_coordinator_headers"],
    )
    parcel = validate_success(response, 201)
    assert_land_use_parcel(parcel)
    # PRELIMINARY: 67.0 - 1.5 = 65.5 -> band 65 -> INCOMPATIBLE_RESIDENTIAL.
    assert parcel["dnl_db_effective"] == 65.5
    assert parcel["dnl_band"] == 65
    assert parcel["compatibility_status"] == "INCOMPATIBLE_RESIDENTIAL"
    assert parcel["insulation_eligible"] is True


def test_list_pagination_defaults_and_offset_navigation(api):
    """PRD 2.3: "If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to skip
    and defaults to 0."
    PRD 2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_pagination_defaults_and_offset_navigation
    """
    for i in range(1, 13):
        create_complainant(
            full_name=f"Pg {i:02d}",
            email=f"pg{i:02d}@x.com",
            address_line=f"{i} Page St",
        )

    page_one, meta_one = validate_paginated(api.list_complainants(LIAISON))
    assert len(page_one) == 10
    assert meta_one["limit"] == 10
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 12
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_complainants(LIAISON, params={"offset": 10})
    )
    assert len(page_two) == 2
    assert meta_two["offset"] == 10
    assert meta_two["total_count"] == 12
    assert meta_two["has_more"] is False


def test_complaint_list_filter_by_status(api):
    """PRD 3.4: "The complaint list supports `complainant_id`, `status`, `quarter`,
    `correlated_flight_id`, and `correlated_event_id` filters."

    Design: Corner/endpoints/complaint_list_filter_by_status
    """
    complainant = create_complainant(full_name="Flt One", email="flt1@x.com")
    create_complaint(complainant["id"], "2026-07-01T08:00:00Z")
    create_complaint(complainant["id"], "2026-07-02T08:00:00Z")
    third = create_complaint(complainant["id"], "2026-07-03T08:00:00Z")
    withdraw = api.withdraw_complaint(
        third["id"], {}, make_complainant_headers(complainant["id"])
    )
    validate_success(withdraw, 200)

    withdrawn, meta_w = validate_paginated(
        api.list_complaints(
            ANALYST,
            params={"complainant_id": complainant["id"], "status": "WITHDRAWN"},
        )
    )
    assert meta_w["total_count"] == 1
    assert withdrawn[0]["id"] == third["id"]

    received, meta_r = validate_paginated(
        api.list_complaints(
            ANALYST,
            params={"complainant_id": complainant["id"], "status": "RECEIVED"},
        )
    )
    assert meta_r["total_count"] == 2


def test_response_envelope_shape_object_and_array(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/endpoints/response_envelope_shape_object_and_array
    """
    operator = create_operator(name="Air Env", iata_code="AE")

    single = api.get_operator(operator["id"], ANALYST)
    assert single.status_code == 200
    body = single.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"] == operator["id"]

    listing = api.list_operators(ANALYST)
    assert listing.status_code == 200
    body = listing.json()
    assert body["response_type"] == "array"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in body["meta"], f"missing pagination meta field {field}"


def test_immediate_read_after_write_consistency(api):
    """PRD 3.4: "filing also refreshes the complainant's counters and trailing-window
    count, re-evaluating standing per §3.1".
    PRD 2.9: "the system treats those cascades as part of the operation's atomic
    contract rather than as background jobs."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    complainant = create_complainant(full_name="IC One", email="ic1@x.com")

    response = api.create_complaint(
        {
            "complainant_id": complainant["id"],
            "occurred_at": "2026-07-15T09:00:00Z",
            "channel": "WEB",
            "disturbance_type": "OTHER",
        },
        make_complainant_headers(complainant["id"]),
    )
    complaint = validate_success(response, 201)
    assert complaint["status"] == "RECEIVED"

    reread = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert reread["open_count"] == 1
    assert reread["filed_total"] == 1
    assert reread["complaints_90d"] == 1
