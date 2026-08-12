"""Property portfolio, unit configuration, listing, and envelope shape."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, assert_property,
    assert_property_bucket_conservation, fixtures, get_success_data,
    validate_error, validate_paginated, validate_success,
)

DEVELOPER = fixtures.DEVELOPER


def test_property_creation_initializes_counters(api):
    """PRD §2.8: "A property exposes `units_total` (the count of its unit
    rows), `units_available_count`, `units_reserved_count`,
    `units_leased_count`, and `units_out_of_service_count`, each tallying
    units in the corresponding status; a freshly created property starts with
    all of these at zero."

    Design: Corner/entities/property_creation_initializes_counters
    """
    prop = validate_success(
        api.create_property(fixtures.create_property_payload(), DEVELOPER),
        expected_status=201)
    assert_property(prop)
    assert prop["units_total"] == 0
    fetched = validate_success(api.get_property(prop["id"], DEVELOPER))
    assert fetched["units_available_count"] == 0
    assert fetched["units_reserved_count"] == 0
    assert fetched["units_leased_count"] == 0
    assert fetched["units_out_of_service_count"] == 0
    assert_property_bucket_conservation(fetched)


def test_unit_create_invalid_bedroom_enum_returns_invalid_request(api):
    """PRD §2.10: "required fields present, enums valid, datetimes ISO 8601,
    integers integral; failures yield `ERR_INVALID_REQUEST`." PRD §3.1: "a
    `bedroom_count` of `STUDIO`, `ONE_BR`, `TWO_BR`, or `THREE_BR`".

    Design: Corner/entities/unit_create_invalid_bedroom_enum_returns_invalid_request
    """
    prop = fixtures.new_property(api)
    resp = api.create_unit(
        fixtures.create_unit_payload(prop["id"], unit_number="X9",
                                     bedroom_count="FIVE_BR"),
        DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    listed, meta = validate_paginated(
        api.list_units(DEVELOPER, params={"property_id": prop["id"]}))
    assert meta["total_count"] == 0, "no Unit row may be created"


def test_campaign_get_unknown_id_returns_not_found(api):
    """PRD §2.10: "every identifier in the path and body must resolve to an
    existing entity, validated left-to-right, so the first unresolvable
    identifier determines the failure; failures yield `ERR_NOT_FOUND`."

    Design: Corner/entities/campaign_get_unknown_id_returns_not_found
    """
    fixtures.new_property(api)
    resp = api.get_campaign(NON_EXISTENT_UUID, DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_unit_list_filtered_by_property(api):
    """PRD §3.1: "Units may be listed filtered by `property_id`, `status`, or
    `bedroom_count`." PRD §2.3: "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/unit_list_filtered_by_property
    """
    p1 = fixtures.new_property(api)
    p2 = fixtures.new_property(api, name="Oak Court", address_line="2 Oak St")
    fixtures.new_unit(api, p1["id"], unit_number="101")
    fixtures.new_unit(api, p1["id"], unit_number="102",
                      bedroom_count="TWO_BR", ami_tier="AMI_60")
    fixtures.new_unit(api, p2["id"], unit_number="201",
                      bedroom_count="STUDIO", ami_tier="AMI_30")

    page, meta = validate_paginated(
        api.list_units(DEVELOPER, params={"property_id": p1["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(u["property_id"] == p1["id"] for u in page)

    filtered, meta2 = validate_paginated(api.list_units(
        DEVELOPER, params={"property_id": p1["id"],
                           "bedroom_count": "TWO_BR"}))
    assert meta2["total_count"] == 1
    assert len(filtered) == 1
    assert filtered[0]["unit_number"] == "102"


def test_occupancy_standard_duplicate_returns_config_conflict(api):
    """PRD §3.1: "An occupancy standard states, for a `property_id` and
    `bedroom_count`, the inclusive household-size band the unit size admits:
    `min_occupants` of at least 1 and `max_occupants` of at least
    `min_occupants`. Its system-maintained `uniqueness_scope` records that
    only one row may exist per property and bedroom-count pairing; a
    duplicate is rejected with `ERR_CONFIG_CONFLICT`."

    Design: Corner/validations/occupancy_standard_duplicate_returns_config_conflict
    """
    prop = fixtures.new_property(api)
    fixtures.new_occupancy_standard(api, prop["id"], bedroom_count="ONE_BR",
                                    min_occupants=1, max_occupants=3)
    resp = api.create_occupancy_standard(
        fixtures.create_occupancy_standard_payload(
            prop["id"], bedroom_count="ONE_BR", min_occupants=1,
            max_occupants=2),
        DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_CONFIG_CONFLICT)

    other = validate_success(api.create_occupancy_standard(
        fixtures.create_occupancy_standard_payload(
            prop["id"], bedroom_count="TWO_BR", min_occupants=2,
            max_occupants=5),
        DEVELOPER), expected_status=201)
    assert other["bedroom_count"] == "TWO_BR"


def test_ami_limit_duplicate_returns_config_conflict(api):
    """PRD §3.1: "Here `uniqueness_scope` records one row per property,
    household size, and tier triple, and duplicates are likewise rejected
    with `ERR_CONFIG_CONFLICT`."

    Design: Corner/validations/ami_limit_duplicate_returns_config_conflict
    """
    prop = fixtures.new_property(api)
    fixtures.new_ami_limit(api, prop["id"], household_size=2,
                           ami_tier="AMI_50", annual_limit_cents=4_000_000)
    resp = api.create_ami_limit(
        fixtures.create_ami_limit_payload(prop["id"], household_size=2,
                                          ami_tier="AMI_50",
                                          annual_limit_cents=4_100_000),
        DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_CONFIG_CONFLICT)

    other = validate_success(api.create_ami_limit(
        fixtures.create_ami_limit_payload(prop["id"], household_size=3,
                                          ami_tier="AMI_50",
                                          annual_limit_cents=4_600_000),
        DEVELOPER), expected_status=201)
    assert other["household_size"] == 3


def test_unit_out_of_service_round_trip_and_double_place_rejected(api):
    """PRD §3.1: "a `HousingDeveloper` may take an `AVAILABLE` unit out of
    service, provided no `PENDING` offer references it (otherwise the attempt
    is rejected with `ERR_INVALID_STATE`), moving it to `OUT_OF_SERVICE`; the
    inverse action returns an `OUT_OF_SERVICE` unit to `AVAILABLE`."

    Design: Corner/state_machines/unit_out_of_service_round_trip_and_double_place_rejected
    """
    prop = fixtures.new_property(api)
    unit = fixtures.new_unit(api, prop["id"], unit_number="101")

    placed = validate_success(
        api.unit_service(unit["id"], {"action": "PLACE_OUT_OF_SERVICE"},
                         DEVELOPER))
    assert placed["status"] == "OUT_OF_SERVICE"
    prop_mid = get_success_data(api.get_property(prop["id"], DEVELOPER))
    assert prop_mid["units_out_of_service_count"] == 1
    assert prop_mid["units_available_count"] == 0

    resp = api.unit_service(unit["id"], {"action": "PLACE_OUT_OF_SERVICE"},
                            DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    returned = validate_success(
        api.unit_service(unit["id"], {"action": "RETURN_TO_SERVICE"},
                         DEVELOPER))
    assert returned["status"] == "AVAILABLE"


def test_list_pagination_defaults_and_envelope_shape(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter states how many items to skip and defaults to 0."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_pagination_defaults_and_envelope_shape
    """
    prop = fixtures.new_property(api)
    for i in range(12):
        fixtures.new_unit(api, prop["id"], unit_number=f"U{i + 1:02d}")

    page1, meta1 = validate_paginated(
        api.list_units(DEVELOPER, params={"property_id": prop["id"]}))
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_units(
        DEVELOPER, params={"property_id": prop["id"], "offset": 10}))
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    single = api.get_unit(page1[0]["id"], DEVELOPER)
    body = single.json()
    assert single.status_code == 200
    assert body["response_type"] == "object"
    assert body["data"]["unit_number"] == page1[0]["unit_number"]

    missing = api.get_unit(NON_EXISTENT_UUID, DEVELOPER)
    err = validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert err["message"].strip(), "error envelope carries a message"
