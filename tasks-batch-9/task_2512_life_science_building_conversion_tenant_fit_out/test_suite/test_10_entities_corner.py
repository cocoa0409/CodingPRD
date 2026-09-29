"""Entity surface: what a create stores, what a read returns, what a listing pages."""

from test_helpers import (
    AHJ_HEADERS,
    CLOCK_START,
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_building,
    assert_floor,
    assert_lease,
    assert_money,
    assert_tenant,
    building_payload,
    control_areas_for_floor,
    create_building,
    create_floor,
    create_tenant,
    floor_payload,
    get_building,
    ids,
    lease_payload,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "address_city": "Cambridge",
    "occupancy_status": "PARTIALLY_OCCUPIED",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
SECOND_NAMEPLATE = {
    "name": "Binney Labs 200",
    "address_city": "Cambridge",
    "occupancy_status": "VACANT",
    "published_floor_to_floor_ft": 15.0,
    "published_live_load_psf": 100,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 40000,
    "emergency_power_capacity_kw": 600,
    "chilled_water_capacity_tons": 900,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}


def test_a_new_building_carries_server_minted_state_and_pools_from_the_nameplate(api):
    """A create answers with everything the caller did not send.

    The row comes back at version one in the initial suitability state with no
    recorded verdict, its two pools seeded from the published nameplate figures
    alone, nothing reserved or committed against them, and no scope declared.

    Design: Corner/entities/building_creation_returns_system_fields_and_zeroed_pools
    """
    response = api.create_building(building_payload(**NAMEPLATE), LANDLORD_HEADERS)

    building = validate_success(response, 201)
    assert_building(building)
    assert building["version"] == 1
    assert building["suitability_state"] == "DRAFT"
    assert building["latest_assessment_verdict"] is None
    assert_money(building["exhaust_capacity_total_cfm"], 60000.00, "exhaust total")
    assert_money(building["exhaust_reserved_cfm"], 0.00, "exhaust_reserved_cfm")
    assert_money(building["exhaust_committed_cfm"], 0.00, "exhaust_committed_cfm")
    assert_money(building["exhaust_available_cfm"], 60000.00, "exhaust_available_cfm")
    assert_money(building["power_capacity_total_kw"], 800.00, "power total")
    assert_money(building["power_available_kw"], 800.00, "power_available_kw")
    assert building["scope_disciplines_covered"] == []
    assert building["scope_disciplines_complete"] == []
    assert same_instant(building["created_at"], CLOCK_START)


def test_reading_a_plate_back_returns_the_stored_row_and_its_code_entitlement(api):
    """The entitlement is derived from the floor number, not supplied.

    A fifth-floor plate reads back with the as-built figures the create stored
    and with the two control areas its band allows, and the authority can read it
    just as the engineer who measured it can.

    Design: Corner/entities/floor_retrieval_returns_stored_row_with_derived_control_areas
    """
    building = create_building(api, **NAMEPLATE)
    created = create_floor(api, building["id"], 5, **PLATE)

    floor = validate_success(api.get_floor(created["id"], AHJ_HEADERS), 200)

    assert_floor(floor)
    assert floor["floor_number"] == 5
    assert floor["building_id"] == building["id"]
    assert floor["floor_to_floor_ft"] == 14.0
    assert floor["live_load_psf"] == 95
    assert floor["vibration_class"] == "VC_C"
    assert floor["sprinklered"] is True
    assert floor["control_areas_allowed"] == 2
    assert floor["control_areas_allowed"] == control_areas_for_floor(5)


def test_the_floor_listing_reports_the_whole_count_on_every_page(api):
    """A page states how many rows exist beyond it.

    Three plates are created and a page of two reports the full count with more
    to come, while the page after it returns the single remaining row and says
    there is nothing further.

    Design: Corner/entities/floors_listing_paginates_with_total_count_and_has_more
    """
    building = create_building(api, **NAMEPLATE)
    first = create_floor(api, building["id"], 1, floor_to_floor_ft=16.0,
                         live_load_psf=125, vibration_class="VC_C", sprinklered=True)
    second = create_floor(api, building["id"], 2, **PLATE)
    third = create_floor(api, building["id"], 3, floor_to_floor_ft=14.0,
                         live_load_psf=95, vibration_class="VC_D", sprinklered=True)

    head, head_meta = validate_paginated(
        api.list_building_floors(building["id"], LANDLORD_HEADERS,
                                 {"limit": 2, "offset": 0})
    )
    tail, tail_meta = validate_paginated(
        api.list_building_floors(building["id"], LANDLORD_HEADERS,
                                 {"limit": 2, "offset": 2})
    )

    assert len(head) == 2
    assert head_meta["total_count"] == 3
    assert head_meta["has_more"] is True
    assert head[0]["id"] == first["id"]
    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False
    assert tail[0]["id"] == third["id"]
    assert second["id"] in ids(head)


def test_each_read_path_names_the_entity_it_could_not_find(api):
    """A valid identifier that belongs to nothing is answered per entity.

    Six read paths are asked for the same unknown identifier and each reports its
    own not-found condition, so a caller can tell which of them was the one that
    failed.

    Design: Corner/entities/unknown_ids_return_entity_scoped_404_family
    """
    expected = [
        (api.get_building(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_BUILDING_NOT_FOUND.value),
        (api.get_floor(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_FLOOR_NOT_FOUND.value),
        (api.get_lease(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_LEASE_NOT_FOUND.value),
        (api.get_project(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_PROJECT_NOT_FOUND.value),
        (api.get_phase(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_PHASE_NOT_FOUND.value),
        (api.get_tenant(NON_EXISTENT_UUID, LANDLORD_HEADERS),
         ApiErrorId.ERR_TENANT_NOT_FOUND.value),
    ]

    for response, error_id in expected:
        validate_error(response, error_id, 404)


def test_a_lease_without_its_demised_area_is_refused(api):
    """The demised area has no default, so it must be supplied.

    A lease payload missing the rentable area is refused and persists nothing,
    and the identical payload carrying an area of four thousand is accepted, so
    the refusal was about the omission alone.

    Design: Corner/entities/lease_creation_missing_required_rentable_sf_rejected
    """
    building = create_building(api, **NAMEPLATE)
    floor = create_floor(api, building["id"], 2, **PLATE)
    tenant = create_tenant(api, "BSL2_BIOLOGY", legal_name="Helix Bio Labs")
    payload = lease_payload(
        tenant["id"], building["id"], floor["id"], 4000,
        term_months=120, base_rent_psf=105.00,
        delivery_deadline="2026-12-31T00:00:00Z",
    )
    without_area = {k: v for k, v in payload.items() if k != "rentable_sf"}

    validate_error(
        api.create_lease(without_area, LANDLORD_HEADERS),
        ApiErrorId.ERR_VALIDATION.value,
        422,
    )
    lease = validate_success(api.create_lease(payload, LANDLORD_HEADERS), 201)

    assert_lease(lease)
    assert lease["status"] == "LOI"
    assert lease["rentable_sf"] == 4000
    rows, meta = validate_paginated(
        api.list_leases(LANDLORD_HEADERS, {"building_id": building["id"]})
    )
    assert meta["total_count"] == 1
    assert ids(rows) == [lease["id"]]


def test_the_research_programme_fixes_the_premium_and_the_script_battery(api):
    """Two derived properties follow from the programme and nothing else.

    A vivarium tenant is stored with the highest premium and the full six-script
    battery, while an analytical QC tenant is stored with the lowest premium and
    a battery of two, neither of which the caller supplied.

    Design: Corner/entities/tenant_lab_premium_and_required_scripts_computed_from_research_type
    """
    vivarium = create_tenant(
        api, "VIVARIUM", legal_name="Vivarium Partners LLC",
        credit_tier="INVESTMENT_GRADE",
    )
    quality_control = create_tenant(
        api, "ANALYTICAL_QC", legal_name="Assay Metrics QC Inc",
        credit_tier="VENTURE_BACKED",
    )

    assert_tenant(vivarium)
    assert_tenant(quality_control)
    assert_money(vivarium["lab_premium_psf"], 88.00, "lab_premium_psf")
    assert vivarium["required_commissioning_scripts"] == [
        "CONTAINMENT_VERIFICATION",
        "EPSS_LOAD_TEST",
        "EXHAUST_AIRFLOW",
        "IQ",
        "OQ",
        "PQ",
    ]
    assert_money(quality_control["lab_premium_psf"], 30.00, "lab_premium_psf")
    assert quality_control["required_commissioning_scripts"] == ["IQ", "OQ"]
    assert quality_control["credit_tier"] == "VENTURE_BACKED"


def test_system_fields_supplied_by_the_caller_are_discarded(api):
    """The server mints identity, version and state regardless of the body.

    A create carrying its own identifier, version, state and creation stamp is
    stored with a server identifier, at version one, in the initial state, and
    stamped from the logical clock.

    Design: Corner/entities/building_client_supplied_id_and_version_input_ignored
    """
    supplied_id = "11111111-1111-4111-8111-111111111111"
    payload = building_payload(
        **NAMEPLATE,
        id=supplied_id,
        version=99,
        suitability_state="CONVERSION_APPROVED",
        created_at="2020-01-01T00:00:00Z",
    )

    building = validate_success(api.create_building(payload, LANDLORD_HEADERS), 201)

    assert_building(building)
    assert building["id"] != supplied_id
    assert building["version"] == 1
    assert building["suitability_state"] == "DRAFT"
    assert get_building(api, building["id"])["suitability_state"] == "DRAFT"
    assert same_instant(building["created_at"], CLOCK_START)
    assert same_instant(building["updated_at"], CLOCK_START)


def test_an_assessment_basis_outside_the_pair_is_refused(api):
    """Only the two declared bases exist.

    A third basis is refused, no assessment row is persisted, and the building
    stays in its initial state rather than being carried into assessment by a
    request that failed.

    Design: Corner/entities/assessment_basis_outside_enum_rejected
    """
    building = create_building(api, **NAMEPLATE)

    response = api.create_assessment(
        building["id"],
        {
            "assessment_basis": "DESKTOP",
            "required_vibration_class": "VC_C",
            "required_exhaust_cfm": 50000,
            "required_power_kw": 700,
            "measured_live_load_psf": 88,
        },
        ENGINEER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    assert get_building(api, building["id"])["suitability_state"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_building_assessments(building["id"], LANDLORD_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_plate_cannot_be_added_under_a_building_that_does_not_exist(api):
    """The nested route resolves its parent before it reads the body.

    The body is entirely valid and the request is still refused for the unknown
    building named in the path, and the building that does exist is left with no
    plates at all.

    Design: Corner/entities/floor_creation_under_unknown_building_not_found
    """
    building = create_building(api, **NAMEPLATE)

    response = api.create_floor(
        NON_EXISTENT_UUID, floor_payload(2, **PLATE), ENGINEER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_BUILDING_NOT_FOUND.value, 404)
    rows, meta = validate_paginated(
        api.list_building_floors(building["id"], LANDLORD_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_lease_may_not_demise_a_plate_from_a_different_asset(api):
    """The plate named must belong to the building named.

    A lease pointing at one building while demising a plate of another is
    refused, the same request against the building's own plate is accepted, and
    the foreign plate ends up carrying no lease.

    Design: Corner/entities/lease_premises_floor_from_another_building_rejected
    """
    home = create_building(api, **NAMEPLATE)
    other = create_building(api, **SECOND_NAMEPLATE)
    home_floor = create_floor(api, home["id"], 2, **PLATE)
    other_floor = create_floor(
        api, other["id"], 2, floor_to_floor_ft=15.0, live_load_psf=100,
        vibration_class="VC_C", sprinklered=True,
    )
    tenant = create_tenant(api, "BSL2_BIOLOGY", legal_name="Helix Bio Labs")

    mismatched = api.create_lease(
        lease_payload(tenant["id"], home["id"], other_floor["id"], 4000,
                      term_months=120, base_rent_psf=105.00,
                      delivery_deadline="2026-12-31T00:00:00Z"),
        LANDLORD_HEADERS,
    )
    validate_error(mismatched, ApiErrorId.ERR_FLOOR_NOT_IN_PREMISES.value, 422)

    lease = validate_success(
        api.create_lease(
            lease_payload(tenant["id"], home["id"], home_floor["id"], 4000,
                          term_months=120, base_rent_psf=105.00,
                          delivery_deadline="2026-12-31T00:00:00Z"),
            LANDLORD_HEADERS,
        ),
        201,
    )

    assert lease["premises_floor_id"] == home_floor["id"]
    rows, meta = validate_paginated(
        api.list_leases(LANDLORD_HEADERS, {"premises_floor_id": other_floor["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
