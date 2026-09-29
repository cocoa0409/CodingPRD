"""What a row looks like when it is created and when it is read back.

These cover the server-minted identity fields, the declared defaults, the
computed fields that stay null until a lock derives them, the pagination
envelope of a collection read, and the referential and request-shape refusals
that must leave nothing behind.
"""

from test_helpers import (
    ADMIN,
    CLOCK_STARTUP_UTC,
    ENGINEER,
    NON_EXISTENT_UUID,
    PLANNER,
    SALES,
    assert_append_only_fields,
    assert_bare_uuid,
    assert_draft_configuration_is_uncomputed,
    assert_pagination_meta,
    assert_timestamp_has_three_fractional_digits,
    assert_weight,
    authorize_builder,
    chain_authorized_builder,
    chain_locked_configuration,
    create_accessory_kit_payload,
    create_builder,
    create_builder_payload,
    create_configuration,
    create_configuration_payload,
    create_design,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_quote_payload,
    get_builder,
    get_configuration,
    get_jurisdiction,
    list_design_components,
    lock_configuration,
    member_component_payload,
    publish_loading_criteria,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant the fixtures move the logical clock to, in the three-fractional-digit
#: form the API writes it back in.
WORKING_DAY_STAMP = "2026-08-05T00:00:00.000Z"


def test_01_registering_a_jurisdiction_stores_every_supplied_field(api):
    """The commercial and engineering halves are both stored as supplied.

    PRD §3.1: "A ``PlatformAdmin`` registers one with a ``code`` — the identifier
    that appears on permit paperwork, which must be unique across all
    jurisdictions, between 3 and 32 characters long, and composed only of
    uppercase alphanumeric characters and hyphens — together with a display
    ``name`` for the authority, a ``state_code`` of exactly two uppercase letters,
    and a ``territory_code`` between 3 and 16 characters identifying the sales
    territory the jurisdiction belongs to."

    PRD §3.1: "Alongside it the server maintains ``authorized_builder_count``,
    which starts at 0 and always reflects the number of builders whose
    ``territory_code`` equals this jurisdiction's ``territory_code`` and whose
    ``status`` is ``AUTHORIZED``."

    PRD §3.1: "A newly registered jurisdiction starts with ``criteria_revision``
    equal to 1."

    Design: Corner/entities/create_jurisdiction_with_all_required_fields_returns_201
    """
    response = api.create_jurisdiction(create_jurisdiction_payload(), ADMIN)

    jurisdiction = validate_success(response, expected_status=201)
    assert response.json()["response_type"] == "object"
    assert jurisdiction["code"] == "TX-HARRIS"
    assert jurisdiction["name"] == "Harris County TX"
    assert jurisdiction["state_code"] == "TX"
    assert jurisdiction["territory_code"] == "TX-GULF"
    assert jurisdiction["freight_zone"] == 3
    assert jurisdiction["exposure_category"] == "C"
    assert jurisdiction["design_wind_speed_mph"] == 140
    assert jurisdiction["ground_snow_load_psf"] == 5
    assert jurisdiction["seismic_design_category"] == "A"
    assert jurisdiction["max_authorized_builders"] == 2
    assert jurisdiction["criteria_revision"] == 1
    assert jurisdiction["authorized_builder_count"] == 0
    assert jurisdiction["version"] == 1


def test_02_reading_a_jurisdiction_returns_the_stored_row_unmutated(api):
    """A read reports the row as stored and does not move its version.

    PRD §2.4: "Most resources additionally carry ``updated_at``, an ISO 8601 UTC
    timestamp with the same three-fractional-digit format that is refreshed on
    every mutation, and ``version``, an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row."

    PRD §2.2: "The ``response_type`` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/get_jurisdiction_by_id_returns_stored_row
    """
    created = create_jurisdiction()

    response = api.get_jurisdiction(created["id"], SALES)

    read_back = validate_success(response, expected_status=200)
    assert response.json()["response_type"] == "object"
    assert read_back["id"] == created["id"]
    assert read_back["code"] == "TX-HARRIS"
    assert read_back["design_wind_speed_mph"] == 140
    assert read_back["criteria_revision"] == 1
    assert read_back["version"] == 1


def test_03_the_builder_collection_reports_the_pagination_envelope(api):
    """Two explicit windows and one defaulted window over the same three rows.

    PRD §2.3: "Every collection read accepts two pagination parameters. ``limit``
    defaults to 10, has a minimum of 1 and a maximum of 100; ``offset`` defaults
    to 0 and has a minimum of 0."

    PRD §2.3: "The ``meta`` object of a collection response carries ``limit``,
    ``offset``, ``total_count`` (the number of rows matching the filters before
    pagination is applied) and ``has_more`` (true when rows remain beyond the
    current window)."

    PRD §2.3: "Collections are always returned sorted by ``created_at``
    ascending."

    Design: Corner/entities/list_builders_returns_pagination_envelope_fields
    """
    jurisdiction = create_jurisdiction()
    alpha = create_builder(jurisdiction["id"], name="Alpha Builders", tier="SILVER")
    bravo = create_builder(
        jurisdiction["id"], name="Bravo Builders", tier="BRONZE",
        credit_limit_cents=50000000,
    )
    charlie = create_builder(
        jurisdiction["id"], name="Charlie Builders", tier="GOLD",
        credit_limit_cents=500000000,
    )

    first_page, first_meta = validate_paginated(
        api.list_builders(SALES, params={"limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_builders(SALES, params={"limit": 2, "offset": 2})
    )
    defaulted, defaulted_meta = validate_paginated(
        api.list_builders(SALES, params={"jurisdiction_id": jurisdiction["id"]})
    )

    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert [row["id"] for row in first_page] == [alpha["id"], bravo["id"]]
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert [row["id"] for row in second_page] == [charlie["id"]]
    assert_pagination_meta(
        defaulted_meta, limit=10, offset=0, total_count=3, has_more=False
    )
    assert len(defaulted) == 3
    assert all(row["territory_code"] == "TX-GULF" for row in defaulted)


def test_04_an_unknown_order_id_reports_the_order_specific_not_found_code(api):
    """The order read has its own not-found code, not a generic one.

    PRD §2.6: "The codes are: ``ERR_JURISDICTION_NOT_FOUND`` when no jurisdiction
    matches (used by jurisdiction read, loading-criteria publication, builder
    creation, configuration drafting and drawing-package opening);
    ``ERR_BUILDER_NOT_FOUND`` when no builder matches (builder read, builder
    authorization, builder suspension, configuration drafting and quote creation);
    ``ERR_CONFIGURATION_NOT_FOUND`` when no building configuration matches
    (configuration read, configuration lock, accessory-kit creation, accessory-kit
    list, quote creation and design creation); ``ERR_QUOTE_NOT_FOUND`` (quote read,
    quote issue, quote acceptance); ``ERR_DESIGN_NOT_FOUND`` (design read,
    component append, component list, design submit, design review, design revise
    and drawing-package opening); ``ERR_DRAWING_PACKAGE_NOT_FOUND`` (package read
    and package seal); ``ERR_ORDER_NOT_FOUND`` (order read, erection-sequence read,
    release to fabrication, cancel of release, lot scheduling and load planning);
    ``ERR_LINE_NOT_FOUND`` (line read and lot scheduling); ``ERR_LOT_NOT_FOUND``
    (lot read, lot completion and lot cancellation); and ``ERR_LOAD_NOT_FOUND``
    (load read, load dispatch and load cancellation). All ten carry HTTP 404."

    PRD §2.2: "The ``message`` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_order_with_unknown_id_returns_order_not_found
    """
    create_jurisdiction()

    response = api.get_order(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_ORDER_NOT_FOUND", expected_status=404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"]


def test_05_a_builder_without_a_credit_limit_is_a_request_shape_failure(api):
    """A missing required input is band three, so it is never a domain code.

    PRD §3.2: "A builder joins the network through a ``PlatformAdmin``, who
    supplies the ``jurisdiction_id`` of the builder's home jurisdiction, the
    builder-of-record business ``name``, the network ``tier`` that will drive its
    standing discount, and a ``credit_limit_cents`` of at least 0."

    PRD §2.5: "Request-shape validation comes third: every required input
    present, every value of the right type, every enum member recognised, every
    numeric range honoured, ``component_marks`` a non-empty array of strings, and
    the component-class field consistency described in §3.6 — any failure here is
    ``ERR_INVALID_REQUEST``."

    Design: Corner/entities/create_builder_without_credit_limit_returns_invalid_request
    """
    jurisdiction = create_jurisdiction()

    response = api.create_builder(
        create_builder_payload(
            jurisdiction["id"], name="No Credit Builders", tier="SILVER",
            credit_limit_cents=None,
        ),
        ADMIN,
    )

    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)
    error_id = response.json()["data"]["error_id"]
    assert error_id != "ERR_BUILDER_NOT_FOUND"
    assert error_id != "ERR_BUILDER_CREDIT_EXCEEDED"
    _, meta = validate_paginated(api.list_builders(ADMIN))
    assert meta["total_count"] == 0


def test_06_an_omitted_authorization_cap_defaults_to_two():
    """The cap is optional at registration and defaults to two builders.

    PRD §3.1: "``max_authorized_builders`` defaults to 2 when omitted and must be
    at least 1."

    Design: Corner/entities/omitted_max_authorized_builders_defaults_to_two
    """
    create_jurisdiction()

    defaulted = create_jurisdiction(
        code="TX-BRAZORIA",
        name="Brazoria County TX",
        territory_code="TX-COAST",
        max_authorized_builders=None,
    )

    assert defaulted["max_authorized_builders"] == 2
    assert defaulted["criteria_revision"] == 1
    assert defaulted["authorized_builder_count"] == 0


def test_07_configuration_geometry_is_null_while_draft_and_derived_at_lock():
    """Nothing is computed until the lock runs the engineering arithmetic.

    PRD §3.3: "A fresh configuration is ``DRAFT``, and every geometry, load and
    weight field on it stays null until it is locked; ``locked_at`` and
    ``criteria_revision_at_lock`` are likewise null while ``DRAFT``."

    PRD §3.3: "``building_length_ft`` is ``bay_spacing_ft`` multiplied by
    ``bay_count``. ``footprint_sqft`` is ``clear_span_ft`` multiplied by
    ``building_length_ft``."

    PRD §3.3: "``panel_area_sqft`` is the sum of those two already-rounded areas,
    rounded half up to two decimal places again."

    PRD §3.3: "``estimated_frame_weight_lbs`` is ``footprint_sqft`` multiplied by
    a base of 4.6 pounds per square foot multiplied by that span factor, rounded
    half up to two decimal places."

    Design: Corner/entities/configuration_computed_geometry_is_null_until_lock_then_derived
    """
    chain = chain_authorized_builder()
    draft = create_configuration(
        chain["builder"]["id"], chain["jurisdiction"]["id"]
    )

    assert_draft_configuration_is_uncomputed(draft)

    locked = lock_configuration(draft["id"])

    assert locked["building_length_ft"] == 100.0
    assert locked["footprint_sqft"] == 10000
    assert locked["roof_slope_factor"] == 1.0035
    assert_weight(locked["panel_area_sqft"], 19635.00)
    assert locked["design_wind_pressure_psf"] == 48.79
    assert locked["dead_load_psf"] == 3.08
    assert locked["roof_snow_load_psf"] == 3.50
    assert_weight(locked["estimated_frame_weight_lbs"], 49680.00)
    assert locked["criteria_revision_at_lock"] == 1
    assert locked["locked_at"] == WORKING_DAY_STAMP


def test_08_identity_and_audit_fields_are_minted_by_the_server():
    """The id, the timestamps and the version are all the server's to write.

    PRD §2.4: "Every resource carries a server-minted ``id`` that is a UUID string
    with no type prefix — clients never supply an ``id``, and the shape of an
    ``id`` never encodes what kind of resource it points at."

    PRD §2.4: "Every resource also carries ``created_at``, an ISO 8601 UTC
    timestamp with three fractional digits recorded when the row is inserted."

    PRD §3.1: "The four values replace the stored ones, ``criteria_revision``
    increases by exactly 1, and the jurisdiction's ``version`` increments."

    Design: Corner/entities/jurisdiction_system_fields_are_server_minted
    """
    set_clock()
    created = create_jurisdiction()

    assert_bare_uuid(created["id"])
    assert_timestamp_has_three_fractional_digits(created["created_at"])
    # The clock was moved before the insert, so the startup instant is not stamped.
    assert created["created_at"] != CLOCK_STARTUP_UTC
    assert created["created_at"] == WORKING_DAY_STAMP
    assert created["created_at"] == created["updated_at"]
    assert created["version"] == 1

    publish_loading_criteria(
        created["id"],
        exposure_category="D",
        design_wind_speed_mph=160,
        ground_snow_load_psf=5,
        seismic_design_category="B",
    )

    updated = get_jurisdiction(created["id"])
    assert updated["version"] == 2
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] == WORKING_DAY_STAMP
    assert updated["criteria_revision"] == 2


def test_09_out_of_band_numbers_and_unrecognised_enums_are_all_rejected(api):
    """Four different shape failures, one code, and nothing persisted.

    PRD §3.3: "The geometry is described by six numbers: ``clear_span_ft``, the
    frame clear span in feet, between 20 and 200 inclusive; ``bay_spacing_ft``,
    the distance between primary frames, between 15 and 30 inclusive;
    ``bay_count``, the number of bays along the building length, an integer
    between 1 and 40 inclusive; ``eave_height_ft``, between 10 and 60 inclusive;
    and ``roof_pitch_rise_per_12``, the roof rise per twelve units of run,
    between 0.25 and 6 inclusive."

    PRD §3.3: "The envelope is described by ``panel_profile``, ``panel_color`` —
    the finish colour a panel fabrication run must later match — and
    ``insulation_r_value``, which must be one of 0, 13, 19 or 25."

    PRD §2.12: "Panel profile is one of ``PBR``, ``STANDING_SEAM``,
    ``R_PANEL``."

    PRD §3.1: "The commercial half of a jurisdiction record is a ``freight_zone``
    between 1 and 5, which selects the freight rate applied to every shipment
    quoted into that jurisdiction, and ``max_authorized_builders``, which caps how
    many builders may hold authorization in the jurisdiction's territory."

    Design: Corner/entities/out_of_range_span_and_unknown_enum_are_rejected
    """
    jurisdiction = create_jurisdiction()
    builder = create_builder(jurisdiction["id"])
    authorize_builder(builder["id"])

    for overrides in (
        {"clear_span_ft": 201},
        {"insulation_r_value": 20},
        {"panel_profile": "CORRUGATED_TIN"},
    ):
        response = api.create_configuration(
            create_configuration_payload(
                builder["id"], jurisdiction["id"], **overrides
            ),
            SALES,
        )
        validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    out_of_band_zone = api.create_jurisdiction(
        create_jurisdiction_payload(
            code="TX-FORTBEND", name="Fort Bend County TX", freight_zone=6
        ),
        ADMIN,
    )
    validate_error(out_of_band_zone, "ERR_INVALID_REQUEST", expected_status=400)

    _, configuration_meta = validate_paginated(api.list_configurations(SALES))
    assert configuration_meta["total_count"] == 0
    _, jurisdiction_meta = validate_paginated(api.list_jurisdictions(ADMIN))
    assert jurisdiction_meta["total_count"] == 1


def test_10_an_appended_component_carries_no_version_and_no_updated_at(api):
    """Components are immutable, so they are the one row without a version.

    PRD §2.4: "Design components are the single exception: a component row carries
    only ``id`` and ``created_at``. It has no ``updated_at`` and no ``version``,
    because components are immutable once appended — they are never edited and
    never deleted."

    PRD §3.6: "For each component of the design in ``created_at`` ascending order,
    ``unit_weight_lbs`` is ``length_ft`` multiplied by ``weight_per_ft`` rounded
    half up to two decimal places, and ``line_weight_lbs`` is that already-rounded
    ``unit_weight_lbs`` multiplied by ``quantity``, again rounded half up to two
    decimal places."

    Design: Corner/entities/design_component_is_immutable_with_no_version_field
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    design = create_design(configuration["id"], configuration["version"])

    response = api.create_design_component(
        design["id"], member_component_payload(), ENGINEER
    )

    component = validate_success(response, expected_status=201)
    assert_append_only_fields(component)
    assert component["created_at"] == WORKING_DAY_STAMP
    assert_weight(component["unit_weight_lbs"], 1527.58)
    assert_weight(component["line_weight_lbs"], 15275.80)
    rows = list_design_components(design["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == component["id"]


def test_11_a_kit_against_an_unknown_configuration_resolves_the_parent_first(api):
    """The nested write resolves its path segment before it writes anything.

    PRD §2.6: "Nested reads and nested writes validate their path segments left to
    right. A request against a design's component collection first resolves the
    design; only if the design exists does the collection read proceed. A request
    against a configuration's accessory-kit collection first resolves the
    configuration."

    PRD §2.6: "The codes are: ``ERR_JURISDICTION_NOT_FOUND`` when no jurisdiction
    matches (used by jurisdiction read, loading-criteria publication, builder
    creation, configuration drafting and drawing-package opening);
    ``ERR_BUILDER_NOT_FOUND`` when no builder matches (builder read, builder
    authorization, builder suspension, configuration drafting and quote creation);
    ``ERR_CONFIGURATION_NOT_FOUND`` when no building configuration matches
    (configuration read, configuration lock, accessory-kit creation, accessory-kit
    list, quote creation and design creation); ``ERR_QUOTE_NOT_FOUND`` (quote read,
    quote issue, quote acceptance); ``ERR_DESIGN_NOT_FOUND`` (design read,
    component append, component list, design submit, design review, design revise
    and drawing-package opening); ``ERR_DRAWING_PACKAGE_NOT_FOUND`` (package read
    and package seal); ``ERR_ORDER_NOT_FOUND`` (order read, erection-sequence read,
    release to fabrication, cancel of release, lot scheduling and load planning);
    ``ERR_LINE_NOT_FOUND`` (line read and lot scheduling); ``ERR_LOT_NOT_FOUND``
    (lot read, lot completion and lot cancellation); and ``ERR_LOAD_NOT_FOUND``
    (load read, load dispatch and load cancellation). All ten carry HTTP 404."

    Design: Corner/entities/accessory_kit_against_unknown_configuration_returns_not_found
    """
    chain = chain_authorized_builder()
    real = create_configuration(chain["builder"]["id"], chain["jurisdiction"]["id"])

    response = api.create_accessory_kit(
        NON_EXISTENT_UUID, create_accessory_kit_payload(), SALES
    )

    validate_error(response, "ERR_CONFIGURATION_NOT_FOUND", expected_status=404)
    _, meta = validate_paginated(api.list_accessory_kits(real["id"], SALES))
    assert meta["total_count"] == 0


def test_12_a_quote_resolves_its_two_body_references_in_input_order(api):
    """Each body foreign key reports its own not-found code.

    PRD §2.5: "Fourth comes existence: path identifiers are resolved left to
    right, and only then body foreign keys, in the order the fields appear in the
    endpoint's input list; each missing resource has its own code, listed in
    §2.6."

    PRD §2.6: "The codes are: ``ERR_JURISDICTION_NOT_FOUND`` when no jurisdiction
    matches (used by jurisdiction read, loading-criteria publication, builder
    creation, configuration drafting and drawing-package opening);
    ``ERR_BUILDER_NOT_FOUND`` when no builder matches (builder read, builder
    authorization, builder suspension, configuration drafting and quote creation);
    ``ERR_CONFIGURATION_NOT_FOUND`` when no building configuration matches
    (configuration read, configuration lock, accessory-kit creation, accessory-kit
    list, quote creation and design creation); ``ERR_QUOTE_NOT_FOUND`` (quote read,
    quote issue, quote acceptance); ``ERR_DESIGN_NOT_FOUND`` (design read,
    component append, component list, design submit, design review, design revise
    and drawing-package opening); ``ERR_DRAWING_PACKAGE_NOT_FOUND`` (package read
    and package seal); ``ERR_ORDER_NOT_FOUND`` (order read, erection-sequence read,
    release to fabrication, cancel of release, lot scheduling and load planning);
    ``ERR_LINE_NOT_FOUND`` (line read and lot scheduling); ``ERR_LOT_NOT_FOUND``
    (lot read, lot completion and lot cancellation); and ``ERR_LOAD_NOT_FOUND``
    (load read, load dispatch and load cancellation). All ten carry HTTP 404."

    PRD §3.4: "A quote is created by a ``SalesEngineer`` against a ``builder_id``
    and a ``configuration_id``, with ``freight_distance_miles`` greater than 0 and
    an optional signed ``adjustment_cents`` that defaults to 0 when omitted."

    Design: Corner/entities/quote_rejects_unknown_builder_and_configuration_references
    """
    chain = chain_locked_configuration()

    unknown_builder = api.create_quote(
        create_quote_payload(NON_EXISTENT_UUID, chain["configuration"]["id"]), SALES
    )
    unknown_configuration = api.create_quote(
        create_quote_payload(chain["builder"]["id"], NON_EXISTENT_UUID), SALES
    )

    validate_error(unknown_builder, "ERR_BUILDER_NOT_FOUND", expected_status=404)
    validate_error(
        unknown_configuration, "ERR_CONFIGURATION_NOT_FOUND", expected_status=404
    )
    _, meta = validate_paginated(api.list_quotes(SALES))
    assert meta["total_count"] == 0
    assert get_builder(chain["builder"]["id"])["credit_used_cents"] == 0
    assert get_configuration(chain["configuration"]["id"])["status"] == "LOCKED"
