"""Entity CRUD surface: creation echo, not-found, paginated listing, required
fields, defaults, system-minted fields, FK existence, append-only immutability,
and initial cohort states.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    setup_species_tank_cohort,
    create_species_payload,
    create_cohort_payload,
    create_stocking_event_payload,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# entities :: create_species_returns_201_with_all_fields
# ===========================================================================
def test_create_species_returns_201_with_minted_fields():
    """PRD §2.4: "Every such resource receives an id, a unique server-minted UUID
    with no type prefix; a created_at timestamp ... and a version, an integer that
    starts at 1 and increments by one on every mutation of the resource."
    PRD §4: "Operations that create a new, standalone resource return 201 Created."

    Design: Corner/entities/create_species_returns_201_with_all_fields
    """
    resp = api_client.create_species(
        create_species_payload(common_name="Rainbow Trout", code="TROUT",
                               target_market_weight_g=1200, base_daily_growth_g=3.0,
                               default_processing_yield_pct=0.60, min_water_temp_c=5,
                               max_water_temp_c=18),
        FM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["code"] == "TROUT"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert data["created_at"]


# ===========================================================================
# entities :: get_cohort_not_found_returns_404
# ===========================================================================
def test_get_cohort_unknown_id_returns_404():
    """PRD §2.5: "the request is rejected with ERR_NOT_FOUND (HTTP 404) at the
    first identifier in the path that does not correspond to an existing resource."

    Design: Corner/entities/get_cohort_not_found_returns_404
    """
    resp = api_client.get_cohort(NON_EXISTENT_UUID, FT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# entities :: list_tanks_paginated_envelope
# ===========================================================================
def test_list_tanks_paginated_envelope():
    """PRD §2.3: "Each list response carries the pagination fields limit, offset,
    total_count, and has_more in the meta object of the envelope."

    Design: Corner/entities/list_tanks_paginated_envelope
    """
    create_tank(name="TA", kind="TANK", volume_liters=1000, max_biomass_kg=100)
    create_tank(name="TB", kind="POND", volume_liters=2000, max_biomass_kg=200)
    resp = api_client.list_tanks(FM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true at limit 1 with 2 tanks"


# ===========================================================================
# entities :: create_cohort_missing_required_field_returns_400
# ===========================================================================
def test_create_cohort_missing_fish_count_returns_400():
    """PRD §2.12: "a missing required field, a bad type, an out-of-range numeric
    value, or an invalid enum value is rejected with ERR_INVALID_REQUEST (HTTP
    400)."
    PRD §3.2: "Creation supplies a label, a species_id, a current_tank_id, an
    optional origin_broodstock_id, an optional parent_cohort_id, a fish_count, a
    stocked_avg_weight_g, and a stocked_at timestamp."

    Design: Corner/entities/create_cohort_missing_required_field_returns_400
    """
    species = create_species()
    tank = create_tank()
    payload = {
        "label": "C1",
        "species_id": species["id"],
        "current_tank_id": tank["id"],
        "stocked_avg_weight_g": 50,
        "stocked_at": "2026-01-01T00:00:00Z",
    }  # fish_count omitted
    resp = api_client.create_cohort(payload, FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# entities :: sales_order_discount_tier_defaults_to_none
# ===========================================================================
def test_sales_order_discount_tier_defaults_to_none():
    """PRD §3.10: "A SalesOrder is created with a customer_name and an optional
    discount_tier - one of NONE, BRONZE, SILVER, or GOLD, defaulting to NONE - and
    begins in DRAFT with an order_total of 0."

    Design: Corner/entities/sales_order_discount_tier_defaults_to_none
    """
    resp = api_client.create_sales_order({"customer_name": "Acme"}, SA)
    data = validate_success(resp, expected_status=201)
    assert data["discount_tier"] == "NONE", \
        f"expected discount_tier NONE, got {data['discount_tier']}"
    assert data["status"] == "DRAFT"
    assert data["order_total"] == pytest.approx(0, abs=0.01)


# ===========================================================================
# entities :: cohort_id_is_system_generated_input_ignored
# ===========================================================================
def test_cohort_id_and_version_are_server_minted():
    """PRD §2.4: "Every such resource receives an id, a unique server-minted UUID
    with no type prefix; a created_at timestamp ... and a version, an integer that
    starts at 1 and increments by one on every mutation of the resource."

    Design: Corner/entities/cohort_id_is_system_generated_input_ignored
    """
    species = create_species()
    tank = create_tank()
    data = create_cohort(species["id"], tank["id"], fish_count=100,
                         stocked_avg_weight_g=50, stocked_at="2026-01-01T00:00:00Z")
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert data["created_at"], "created_at must be present"


# ===========================================================================
# entities :: create_cohort_invalid_species_fk_returns_404
# ===========================================================================
def test_create_cohort_unknown_species_fk_returns_404():
    """PRD §2.5: "Only after every path identifier resolves does the system
    validate foreign-key references carried in the request body, again rejecting
    an unknown reference with ERR_NOT_FOUND."

    Design: Corner/entities/create_cohort_invalid_species_fk_returns_404
    """
    tank = create_tank()
    payload = create_cohort_payload(NON_EXISTENT_UUID, tank["id"], fish_count=100,
                                    stocked_avg_weight_g=50,
                                    stocked_at="2026-01-01T00:00:00Z")
    resp = api_client.create_cohort(payload, FT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# entities :: stocking_event_immutable_no_version_field
# ===========================================================================
def test_stocking_event_has_no_version_field():
    """PRD §2.4: "a StockingEvent and a FeedLog carry only id and created_at. For
    these two, both updated_at and version are absent, because once written they
    are never modified."

    Design: Corner/entities/stocking_event_immutable_no_version_field
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    created = validate_success(
        api_client.create_stocking_event(
            create_stocking_event_payload(cohort["id"], tank["id"], fish_count=100,
                                          stocked_at="2026-01-01T00:00:00Z",
                                          expected_harvest_at="2026-06-01T00:00:00Z"),
            FT,
        ),
        expected_status=201,
    )
    fetched = validate_success(api_client.get_stocking_event(created["id"], FT))
    assert "id" in fetched and fetched["created_at"]
    assert "version" not in fetched, "StockingEvent must not carry a version field"
    assert "updated_at" not in fetched, "StockingEvent must not carry updated_at"


# ===========================================================================
# state_machines :: cohort_initial_states_on_create
# ===========================================================================
def test_fresh_cohort_initial_states():
    """PRD §3.2: "A newly created cohort begins with lifecycle_status STOCKED,
    health_status HEALTHY, operational_status ACTIVE, cumulative_feed_kg 0,
    estimated_biomass_kg 0, and withdrawal_until null."

    Design: Corner/state_machines/cohort_initial_states_on_create
    """
    species = create_species()
    tank = create_tank()
    data = create_cohort(species["id"], tank["id"], fish_count=100,
                         stocked_avg_weight_g=50, stocked_at="2026-01-01T00:00:00Z")
    assert data["lifecycle_status"] == "STOCKED"
    assert data["health_status"] == "HEALTHY"
    assert data["operational_status"] == "ACTIVE"
