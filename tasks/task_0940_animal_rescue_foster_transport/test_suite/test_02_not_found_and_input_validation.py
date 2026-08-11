"""The closed not-found entity map and the input-validation rungs."""
from test_helpers import (
    MISSING_UUID,
    MISSING_UUID_2,
    MISSING_UUID_3,
    TEST_USERS,
    ApiErrorId,
    animal_payload,
    new_organization,
    set_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]
VET = TEST_USERS["veterinarian_headers"]
COORD = TEST_USERS["foster_coordinator_headers"]


def test_missing_animal_reports_the_animal_not_found_code(api):
    """PRD 2.11: "When a path segment or a body foreign key names a row that does not
    exist, the error code is fixed by the following closed map and by nothing else —
    not by which endpoint was called, and not by which role called it."
    PRD 2.11: "`Animal` yields `ERR_ANIMAL_NOT_FOUND`."
    PRD 2.11: "All of these carry HTTP 404."

    Design: Corner/entities/animal_not_found_returns_animal_not_found
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    validate_error(api.get_animal(MISSING_UUID, ADMIN),
                   ApiErrorId.ERR_ANIMAL_NOT_FOUND.value, 404)


def test_transport_resources_share_one_not_found_code(api):
    """PRD 2.11: "`TransportRun`, `TransportLeg` and `ManifestEntry` share
    `ERR_TRANSPORT_RESOURCE_NOT_FOUND`."
    PRD 2.11: "All of these carry HTTP 404."

    Design: Corner/entities/transport_resource_not_found_covers_run_leg_and_manifest
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    code = ApiErrorId.ERR_TRANSPORT_RESOURCE_NOT_FOUND.value
    validate_error(api.get_transport_run(MISSING_UUID, DISPATCH), code, 404)
    validate_error(api.get_transport_leg(MISSING_UUID_2, DISPATCH), code, 404)
    validate_error(api.get_manifest_entry(MISSING_UUID_3, DISPATCH), code, 404)


def test_adoption_funding_and_medical_resources_share_their_codes(api):
    """PRD 2.11: "`MedicalRecord` and `HealthCertificate` share
    `ERR_MEDICAL_RESOURCE_NOT_FOUND`."
    PRD 2.11: "`AdoptionApplication`, `Adoption` and `OutcomeRecord` share
    `ERR_ADOPTION_RESOURCE_NOT_FOUND`."
    PRD 2.11: "`Contribution` and `PartnerCommitment` share
    `ERR_FUNDING_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/adoption_and_funding_resource_not_found_codes
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    validate_error(
        api.get_adoption(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_ADOPTION_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_outcome(MISSING_UUID_2, ADMIN),
        ApiErrorId.ERR_ADOPTION_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_contribution(MISSING_UUID, FINANCE),
        ApiErrorId.ERR_FUNDING_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_partner_commitment(MISSING_UUID_2, DISPATCH),
        ApiErrorId.ERR_FUNDING_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_health_certificate(MISSING_UUID_3, VET),
        ApiErrorId.ERR_MEDICAL_RESOURCE_NOT_FOUND.value, 404,
    )


def test_every_remaining_entity_reports_its_own_not_found_code(api):
    """PRD 2.11: "`Organization` yields `ERR_ORGANIZATION_NOT_FOUND`."
    PRD 2.11: "`Litter` yields `ERR_LITTER_NOT_FOUND`."
    PRD 2.11: "`IntakeRecord` yields `ERR_INTAKE_RECORD_NOT_FOUND`, which is also the
    code used when an operation requires the animal's currently open custody episode
    and no such episode exists."
    PRD 2.11: "`HoldRecord` yields `ERR_HOLD_NOT_FOUND`."
    PRD 2.11: "`FosterHome` yields `ERR_FOSTER_HOME_NOT_FOUND`, covering both
    `foster_home_id` and `destination_foster_home_id`."
    PRD 2.11: "`FosterApplication` yields `ERR_FOSTER_APPLICATION_NOT_FOUND`, covering
    both `foster_application_id` and `destination_foster_application_id`."
    PRD 2.11: "`FosterPlacement` yields `ERR_FOSTER_PLACEMENT_NOT_FOUND`."

    Design: Corner/entities/remaining_not_found_codes_follow_the_closed_entity_map
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    validate_error(
        api.get_organization(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_litter(MISSING_UUID, ADMIN), ApiErrorId.ERR_LITTER_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_intake_record(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_INTAKE_RECORD_NOT_FOUND.value, 404,
    )
    validate_error(api.get_hold(MISSING_UUID, ADMIN), ApiErrorId.ERR_HOLD_NOT_FOUND.value, 404)
    validate_error(
        api.get_foster_home(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_FOSTER_HOME_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_foster_application(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_FOSTER_APPLICATION_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_foster_placement(MISSING_UUID, ADMIN),
        ApiErrorId.ERR_FOSTER_PLACEMENT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_person(MISSING_UUID, ADMIN), ApiErrorId.ERR_PERSON_NOT_FOUND.value, 404
    )


def test_animal_create_without_species_is_a_body_validation_failure(api):
    """PRD 2.5: "The body parses as JSON, every required input field for the endpoint
    is present, and every field carries the declared JSON type — otherwise
    `ERR_VALIDATION`. Applies to every write."

    Design: Corner/entities/animal_create_missing_required_species_returns_validation
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)

    payload = animal_payload(org["id"], name="NoSpecies", size_class="SMALL", weight_lb=10.0,
                             date_of_birth="2024-01-01T00:00:00Z")
    payload.pop("species")
    validate_error(
        api.create_animal(payload, INTAKE), ApiErrorId.ERR_VALIDATION.value, 400
    )

    rows, meta = validate_paginated(api.list_animals(ADMIN))
    assert meta["total_count"] == 0, "a rejected create must not leave an Animal row behind"


def test_animal_create_with_undeclared_species_routes_to_invalid_enum(api):
    """PRD 2.9: "A value that is well-formed but is not a declared member of its
    enumeration is `ERR_INVALID_ENUM` (HTTP 400), and enum routing is checked at rung
    7, above the numeric and format constraints at rung 8."
    PRD 2.9: "`ERR_INVALID_ENUM` routes **exactly** the following input fields and no
    others: `org_type` and `default_methodology` on an organization; `housing_type` on
    a person; `species`, `size_class` and `temperament` on an animal, together with
    each element of `restriction_housing_types_excluded`; `intake_type` and
    `impound_billing_basis` on an intake record; `hold_type` on a hold;
    `species_requested` on a foster application; `count_basis` on a foster placement;
    `procedure_type` and `expense_category` on a medical record; `run_type` and
    `purpose` on a transport run; `species_policy` on a transport leg;
    `credit_application_order`, `refund_basis` and `deposit_basis` on an adoption;
    `outcome_type` on an outcome record; `designated_program` and
    `restriction_category` on a contribution; `species` on a partner commitment; the
    `decision` field on the two decision-taking endpoints (foster application decision
    and adoption application screening); the `result` field on the home-check
    endpoint; the `action` field on the foster application status-change endpoint; the
    `reason` field on the placement-end endpoint; and the `methodology` query parameter
    on the live-release report."

    Design: Corner/entities/animal_create_invalid_enum_species_returns_invalid_enum
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)

    validate_error(
        api.create_animal(
            animal_payload(org["id"], name="Weasel", species="FERRET", size_class="SMALL",
                           weight_lb=4.0, date_of_birth="2024-01-01T00:00:00Z"),
            INTAKE,
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
        400,
    )


def test_non_positive_animal_weight_is_a_range_failure_not_an_enum_failure(api):
    """PRD 2.9: "The numeric and format constraints checked at rung 8 are these: every
    cents amount and every count is at least 0; a contribution's `amount_cents` is
    strictly greater than 0; an animal's `weight_lb` is strictly greater than 0; a
    leg's `crate_capacity_units` is at least 1 and its `weight_capacity_lb` is strictly
    greater than 0; a leg's `sequence_no` is at least 1; a foster home's
    `max_headcount` is at least 1; a partner commitment's `slots_total` is at least 1;
    `state_code`, `destination_state` and `destination_state_code` are exactly two
    uppercase letters; an `email` contains an at-sign; every datetime parses as an ISO
    8601 UTC instant; and a leg's `scheduled_arrive_at` is strictly after its
    `scheduled_depart_at`."

    Design: Corner/entities/animal_create_negative_weight_returns_validation_not_invalid_enum
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)

    validate_error(
        api.create_animal(
            animal_payload(org["id"], name="Weightless", size_class="SMALL", weight_lb=0.0,
                           date_of_birth="2024-01-01T00:00:00Z"),
            INTAKE,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )


def test_pagination_limit_bounds_are_inclusive_at_one_hundred(api):
    """PRD 2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger than
    100."
    PRD 2.3: "A `limit` outside the inclusive range 1 to 100, or a negative `offset`,
    is a validation failure carrying `ERR_VALIDATION` (HTTP 400); the bounds are
    inclusive at both ends, so a `limit` of exactly 1 and a `limit` of exactly 100 are
    both accepted."

    Design: Corner/entities/pagination_limit_above_maximum_returns_validation
    """
    set_clock(api, "2026-05-01T00:00:00Z")

    validate_error(
        api.list_animals(ADMIN, {"limit": 101, "offset": 0}),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )

    rows, _meta = validate_paginated(api.list_animals(ADMIN, {"limit": 100, "offset": 0}))
    assert rows == [], "an empty database must return an empty data array"


def test_body_foreign_key_naming_no_person_reports_person_not_found(api):
    """PRD 2.5: "Every foreign key in the request body resolves to an existing row,
    checked in the order the fields are listed for that endpoint — otherwise the
    not-found code from the same entity map."
    PRD 2.11: "`Person` yields `ERR_PERSON_NOT_FOUND`, which covers `person_id`,
    `source_person_id`, `donor_person_id`, `applicant_person_id`, `driver_person_id`,
    `reclaiming_person_id` and `counterparty_person_id`."

    Design: Corner/entities/body_fk_person_not_found_returns_person_not_found
    """
    set_clock(api, "2026-05-01T00:00:00Z")

    validate_error(
        api.create_foster_home(
            {"person_id": MISSING_UUID, "label": "Ghost Home", "max_headcount": 3}, COORD
        ),
        ApiErrorId.ERR_PERSON_NOT_FOUND.value,
        404,
    )
