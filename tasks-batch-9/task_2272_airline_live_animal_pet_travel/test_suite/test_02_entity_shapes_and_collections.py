"""Stored and derived field shapes, defaults, collections and filters.

These cases pin the contract of PRD §2.2 through §2.5 onto concrete resources:
what a created row reports, what a derived counter reports, what a list reports
in its envelope meta, and which identifier a failed lookup names.
"""

from test_helpers import (
    ApiErrorId,
    assert_append_only_event_shape,
    assert_animal_state,
    assert_envelope_meta,
    assert_flight_leg_state,
    assert_initial_version,
    assert_reservation_state,
    assert_versioned_resource_shape,
    breed_restriction_payload,
    container_model_payload,
    ids_of,
    species_profile_payload,
    station_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ANIMAL_ID = "2f4d9a10-6c5b-4e77-9f21-0d4a7b3c8e55"
UNKNOWN_SPECIES_ID = "7c1b8e42-55aa-4c19-8f03-9d2e6a41b7c0"


def test_species_profile_created_with_required_fields_returns_created(
    api, program_admin_headers
):
    """A freshly registered species profile echoes its stored fields, defaults
    ``requires_veterinary_review`` to false and starts both its derived count and
    its version at their initial values.

    PRD §3.1: "Its `breed_restriction_count` starts at 0 and is maintained by the
    service. Its `status` is `ACTIVE` or `RETIRED` and defaults to `ACTIVE`".

    Design: Corner/entities/species_profile_created_with_required_fields_returns_created
    """
    response = api.create_species_profile(
        species_profile_payload(), program_admin_headers
    )
    species = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    assert species["species_code"] == "DOG"
    assert species["common_name"] == "Dog"
    assert species["acceptance_class"] == "ACCEPTED_ALL_ROUTINGS"
    assert species["max_cabin_weight_kg"] == 12
    assert species["min_age_weeks"] == 16
    assert species["requires_veterinary_review"] is False
    assert species["breed_restriction_count"] == 0
    assert species["status"] == "ACTIVE"
    assert_versioned_resource_shape(species)
    assert_initial_version(species)


def test_flight_leg_get_returns_stored_and_derived_fields(api, workbench):
    """A leg read reports the block minutes the service computed, an OPEN posture
    with no governing rule and three zeroed booked counters.

    PRD §3.3: "On creation the service computes `block_minutes` as the number of
    whole minutes between the scheduled departure and the scheduled arrival,
    initialises `booked_cabin_count`, `booked_checked_count` and
    `booked_cargo_count` to 0, runs embargo determination and then derives
    `posture`."

    Design: Corner/entities/flight_leg_get_returns_stored_and_derived_fields
    """
    hkg = workbench.create_station(
        iata_code="HKG", country_code="HK", kennel_bay_count=4
    )
    lax = workbench.create_station(
        iata_code="LAX", country_code="US", kennel_bay_count=6
    )
    created = workbench.create_leg(hkg["id"], lax["id"])

    leg = validate_success(api.get_flight_leg(created["id"], workbench.admin()))
    assert_flight_leg_state(
        leg,
        status="SCHEDULED",
        posture="OPEN",
        governing_embargo_rule_id=None,
        booked_cabin_count=0,
        booked_checked_count=0,
        booked_cargo_count=0,
        block_minutes=780,
    )
    assert leg["flight_number"] == "AN101"
    assert leg["origin_station_id"] == hkg["id"]
    assert leg["destination_station_id"] == lax["id"]
    assert_initial_version(leg)


def test_station_list_paginates_with_total_count_and_has_more(
    api, workbench, program_admin_headers
):
    """``total_count`` counts every matching row while ``has_more`` describes only
    the page that was served.

    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true when rows remain beyond the
    current page."

    Design: Corner/entities/station_list_paginates_with_total_count_and_has_more
    """
    hkg = workbench.create_station(
        iata_code="HKG", country_code="HK", kennel_bay_count=4
    )
    lax = workbench.create_station(
        iata_code="LAX", country_code="US", kennel_bay_count=6
    )
    jfk = workbench.create_station(
        iata_code="JFK", country_code="US", kennel_bay_count=6
    )

    first_page, first_meta = validate_paginated(
        api.list_stations(program_admin_headers, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert ids_of(first_page) == [hkg["id"], lax["id"]]

    last_page, last_meta = validate_paginated(
        api.list_stations(program_admin_headers, {"limit": 2, "offset": 2})
    )
    assert len(last_page) == 1
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False
    assert ids_of(last_page) == [jfk["id"]]


def test_animal_record_get_with_unknown_id_returns_not_found(
    api, reservations_agent_headers
):
    """An unresolvable path identifier answers with the 404 belonging to that
    resource class, inside the standard error envelope.

    PRD §2.5: "the service resolves them strictly left to right and fails on the
    **first** identifier that does not resolve, returning HTTP 404 with the error
    identifier belonging to that resource class".

    Design: Corner/entities/animal_record_get_with_unknown_id_returns_not_found
    """
    response = api.get_animal_record(UNKNOWN_ANIMAL_ID, reservations_agent_headers)
    validate_error(response, ApiErrorId.ANIMAL_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert_envelope_meta(body)


def test_container_model_create_without_ventilation_area_pct_rejected(
    api, program_admin_headers
):
    """A required input field cannot be defaulted away: omitting the ventilation
    percentage is a body-shape failure and writes no row.

    PRD §3.2: "A `ProgramAdmin` registers it with a `model_code` between 2 and 24
    characters and unique across all models — a duplicate is
    `ERR_DUPLICATE_CONTAINER_MODEL` — together with its usable interior dimensions
    in centimetres (`interior_length_cm`, `interior_width_cm` and
    `interior_height_cm`, each strictly greater than 0), its `tare_weight_kg` of
    at least 0, which is the empty-container weight added to the animal's weight
    to form gross weight, its `ventilation_area_pct` between 0 and 100 inclusive
    expressing ventilated openings as a percentage of total wall area, and its
    `ventilated_side_count` between 0 and 4 giving how many sides carry openings."

    Design: Corner/entities/container_model_create_without_ventilation_area_pct_rejected
    """
    response = api.create_container_model(
        container_model_payload(ventilation_area_pct=None), program_admin_headers
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_container_models(program_admin_headers))
    assert meta["total_count"] == 0


def test_reservation_and_animal_defaults_applied_when_optional_fields_omitted(
    api, workbench, catalog
):
    """Omitting every optional flag leaves the documented defaults on both rows,
    including a null measured weight and an empty deficiency list.

    PRD §3.4: "The animal is written with `status` `DRAFT` and
    `container_compliance_state` `UNEVALUATED`, its `measured_weight_kg` null, its
    `chargeable_weight_kg` 0 and its `deficiency_codes` an empty list".

    Design: Corner/entities/reservation_and_animal_defaults_applied_when_optional_fields_omitted
    """
    reservation = workbench.create_reservation()
    assert reservation["is_service_animal_booking"] is False
    assert_reservation_state(
        reservation, booking_status="PENDING", compliance_status="UNVERIFIED"
    )

    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    assert animal["animal_kind"] == "PET"
    assert animal["behavior_attestation_on_file"] is False
    assert animal["measured_weight_kg"] is None
    assert_animal_state(
        animal,
        status="DRAFT",
        container_compliance_state="UNEVALUATED",
        deficiency_codes=[],
        chargeable_weight_kg=0,
    )

    stored = validate_success(api.get_animal_record(animal["id"], workbench.admin()))
    assert stored["measured_weight_kg"] is None
    assert stored["deficiency_codes"] == []


def test_species_breed_restriction_count_recomputes_on_withdrawal(
    api, workbench, program_admin_headers
):
    """Withdrawing one of two restrictions recomputes the parent count and
    increments the parent version for a fourth time.

    PRD §3.1: "Creating a restriction increments the parent species profile's
    `breed_restriction_count` and its `version` by one; withdrawing or reinstating
    one recomputes `breed_restriction_count` and again increments the species
    profile's `version` by one."

    Design: Corner/entities/species_breed_restriction_count_recomputes_on_withdrawal
    """
    species = workbench.create_species()
    first = workbench.create_breed_restriction(
        species["id"], breed_name="Bulldog", restriction_type="SNUB_NOSED"
    )
    second = workbench.create_breed_restriction(
        species["id"], breed_name="Wolf Hybrid", restriction_type="BANNED"
    )
    assert workbench.read_species(species["id"])["breed_restriction_count"] == 2

    withdrawn = workbench.set_breed_restriction_status(second["id"], "WITHDRAWN")
    assert withdrawn["status"] == "WITHDRAWN"

    parent = workbench.read_species(species["id"])
    assert parent["breed_restriction_count"] == 1
    assert parent["version"] == 4
    assert workbench.read_breed_restriction(first["id"])["status"] == "ACTIVE"

    active_rows, active_meta = validate_paginated(
        api.list_species_breed_restrictions(
            species["id"], program_admin_headers, {"status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 1
    assert ids_of(active_rows) == [first["id"]]


def test_welfare_check_stamps_recorded_at_from_logical_clock_and_performer(
    api, workbench, catalog, primary_leg
):
    """The service, not the client, supplies the welfare check's instant and its
    performer, and the instant is the logical clock's current value.

    PRD §3.7: "The service stamps `recorded_at_utc` from the logical clock and
    `performed_by_user_id` from the acting `X-User-ID`, increments the slot's
    `completed_welfare_check_count`, and increments the slot's `version` by one."

    Design: Corner/entities/welfare_check_stamps_recorded_at_from_logical_clock_and_performer
    """
    leg = primary_leg()
    workbench.set_clock("2026-08-05T08:30:00Z")

    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    segment = workbench.create_segment(animal["id"], leg["id"])

    response = api.create_welfare_check(
        {"segment_assignment_id": segment["id"], "check_type": "WATER"},
        workbench.acceptance("accept-07"),
    )
    check = validate_success(response, 201)
    assert check["recorded_at_utc"] == "2026-08-05T08:30:00Z"
    assert check["performed_by_user_id"] == "accept-07"
    assert check["check_type"] == "WATER"
    assert check["outcome"] == "NORMAL"
    assert check["notes"] is None

    assert (
        workbench.read_segment(segment["id"])["completed_welfare_check_count"] == 1
    )


def test_station_create_with_lowercase_iata_code_rejected(api, program_admin_headers):
    """The IATA code is case-sensitive: a lowercase code is a body-shape failure
    while the same three letters uppercased are accepted.

    PRD §3.2: "A **station** is an airport in the programme, registered with an
    `iata_code` of exactly three uppercase letters and unique across all stations".

    Design: Corner/entities/station_create_with_lowercase_iata_code_rejected
    """
    lowercase = api.create_station(
        {"iata_code": "hkg", "country_code": "HK", "kennel_bay_count": 4},
        program_admin_headers,
    )
    validate_error(lowercase, ApiErrorId.INVALID_REQUEST, 400)

    uppercase = api.create_station(
        {"iata_code": "HKG", "country_code": "HK", "kennel_bay_count": 4},
        program_admin_headers,
    )
    station = validate_success(uppercase, 201)
    assert station["iata_code"] == "HKG"


def test_welfare_check_row_is_immutable_with_no_version_field(
    api, workbench, catalog, primary_leg, acceptance_agent_headers
):
    """A welfare check is an append-only event, so the listed row exposes the two
    common fields it is allowed and nothing more.

    PRD §2.4: "Welfare checks are the single exception. A `WelfareCheck` is an
    append-only event: it carries only `id` and `created_at`. It has **no**
    `updated_at` field and **no** `version` field, and it is never updated after
    it is written."

    Design: Corner/entities/welfare_check_row_is_immutable_with_no_version_field
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    segment = workbench.create_segment(animal["id"], leg["id"])
    appended = workbench.append_welfare_check(segment["id"], check_type="WATER")
    assert_append_only_event_shape(appended)

    rows, meta = validate_paginated(
        api.list_segment_welfare_checks(
            segment["id"], acceptance_agent_headers, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert_append_only_event_shape(rows[0])
    assert rows[0]["id"] == appended["id"]


def test_breed_restriction_create_with_unknown_species_returns_not_found(
    api, program_admin_headers
):
    """A body foreign key that resolves to nothing produces that resource class's
    404 rather than a validation error.

    PRD §2.6: "Every foreign key in the request body resolves, in declared field
    order — otherwise the matching 404 from §2.5."

    Design: Corner/entities/breed_restriction_create_with_unknown_species_returns_not_found
    """
    response = api.create_breed_restriction(
        breed_restriction_payload(UNKNOWN_SPECIES_ID), program_admin_headers
    )
    validate_error(response, ApiErrorId.SPECIES_NOT_FOUND, 404)


def test_segment_assignment_is_reachable_from_both_animal_and_leg_filters(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """The same two slots are reachable by leg and by animal, and the leg's booked
    counter agrees with the collection.

    PRD §2.10: "Each `booked_<routing>_count` is the number of segment assignments
    on the leg whose `routing_type` matches and whose `status` is `RESERVED` or
    `ACCEPTED`."

    Design: Corner/entities/segment_assignment_is_reachable_from_both_animal_and_leg_filters
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    first_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    second_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=12,
        height_at_shoulder_cm=30,
        length_nose_to_tail_cm=45,
        age_weeks=40,
    )
    first_segment = workbench.create_segment(first_animal["id"], leg["id"])
    second_segment = workbench.create_segment(second_animal["id"], leg["id"])

    by_leg, by_leg_meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"flight_leg_id": leg["id"]}
        )
    )
    assert by_leg_meta["total_count"] == 2
    assert sorted(ids_of(by_leg)) == sorted([first_segment["id"], second_segment["id"]])

    by_first_animal, first_meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"animal_record_id": first_animal["id"]}
        )
    )
    assert first_meta["total_count"] == 1
    assert ids_of(by_first_animal) == [first_segment["id"]]

    by_second_animal, second_meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"animal_record_id": second_animal["id"]}
        )
    )
    assert second_meta["total_count"] == 1
    assert ids_of(by_second_animal) == [second_segment["id"]]

    assert_flight_leg_state(workbench.read_leg(leg["id"]), booked_checked_count=2)


def test_reservation_list_filters_on_the_compliance_dimension(
    api, workbench, compliance_verified_booking, program_admin_headers
):
    """The compliance filter partitions the collection independently of the
    commercial dimension: both bookings are still PENDING.

    PRD §3.4: "The two evolve independently: every commercial transition described
    in this section leaves `compliance_status` untouched, and every compliance
    transition in §3.6 leaves `booking_status` untouched."

    Design: Corner/endpoints/reservation_list_filters_on_the_compliance_dimension
    """
    verified = compliance_verified_booking()
    unverified = workbench.create_reservation(
        passenger_name="Lam", contact_email="lam@example.com", routing_type="CARGO"
    )

    verified_rows, verified_meta = validate_paginated(
        api.list_reservations(
            program_admin_headers,
            {"compliance_status": "VERIFIED", "limit": 10, "offset": 0},
        )
    )
    assert verified_meta["total_count"] == 1
    assert verified_meta["has_more"] is False
    assert ids_of(verified_rows) == [verified["reservation_id"]]
    assert_reservation_state(
        verified_rows[0], booking_status="PENDING", compliance_status="VERIFIED"
    )

    unverified_rows, unverified_meta = validate_paginated(
        api.list_reservations(
            program_admin_headers,
            {"compliance_status": "UNVERIFIED", "limit": 10, "offset": 0},
        )
    )
    assert unverified_meta["total_count"] == 1
    assert ids_of(unverified_rows) == [unverified["id"]]
    assert_reservation_state(
        unverified_rows[0], booking_status="PENDING", compliance_status="UNVERIFIED"
    )
