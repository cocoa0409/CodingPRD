"""Census tract reference data, deterministic geocode matching, manual override
and the optimistic concurrency guard on re-geocoding."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    TRACT_A,
    TRACT_B,
    TRACT_TX,
    assert_census_tract,
    assert_geocode_assignment,
    create_application,
    create_census_tract_payload,
    create_geocode_assignment_payload,
    create_institution,
    create_tract_a,
    create_tract_tx,
    geocode_application,
    make_compliance_analyst_headers,
    make_loan_officer_headers,
    make_system_admin_headers,
    manual_override_payload,
    read_application,
    setup_institution_and_tract,
    setup_institution_with_two_tracts,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_a_census_tract_is_immutable_reference_data(api):
    """PRD §2.4: "Two resources are exceptions and must be implemented
    differently. `CensusTract` rows are immutable reference data: a tract carries
    only `id` and `created_at`, and has neither `updated_at` nor `version`."
    PRD §3.4: "Each `CensusTract` carries an eleven-digit `tract_code`, the
    five-digit `county_fips` and two-letter `state_code` locating it, its
    five-digit `msa_md_code`, and four statistics used downstream:
    `minority_population_pct` (the tract's minority population share as a
    percentage), `tract_to_msa_income_pct` (tract median family income as a
    percentage of the MSA median), `owner_occupied_units` (which drives disclosure
    suppression in §3.7), and `median_family_income_cents`. Tract rows are never
    modified once loaded."

    Design: Corner/entities/census_tract_is_immutable_and_has_no_update_endpoint
    """
    data = validate_success(
        api.create_census_tract(create_census_tract_payload(), make_system_admin_headers()),
        201,
    )
    assert_census_tract(data)
    assert data["tract_code"] == TRACT_A["tract_code"]
    assert data["owner_occupied_units"] == 1200

    rows, meta = validate_paginated(
        api.list_tract_geocode_assignments(data["id"], TEST_USERS["examiner_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_geocoding_an_unknown_register_record_is_a_not_found(api):
    """PRD §2.9: "Body foreign-key resolution — the relevant not-found error, 404.
    This applies to opening a register record, recording a demographic entry,
    creating a geocode assignment, pinning a tract by manual override, starting an
    edit run, opening a submission, attaching an edit run to a submission, drawing
    an audit sample, recording an audit finding, and computing a fair lending
    analysis."
    PRD §2.9: "Optimistic concurrency on the supplied parent version —
    `ERR_STALE_INSTITUTION_VERSION` or `ERR_STALE_APPLICATION_VERSION`, 412, on
    the two endpoints named in §2.8."

    Design: Corner/entities/flat_topology_geocode_for_unknown_application_returns_not_found
    """
    institution = create_institution()
    real = create_application(institution["id"])

    validate_error(
        api.create_geocode_assignment(
            create_geocode_assignment_payload(UNKNOWN_ID, real["version"]),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_APPLICATION_NOT_FOUND.value,
    )


def test_a_property_in_an_unloaded_county_does_not_match(api):
    """PRD §3.4: "No candidates: the assignment moves `PENDING → NOT_MATCHED`,
    with `census_tract_id` and `msa_md_code` both left null."
    PRD §3.4: "The number of candidates is stored as `candidate_count`, and it
    decides the outcome:"

    Design: Corner/calculations/geocode_returns_not_matched_when_no_tract_candidate_exists
    """
    institution, _tract = setup_institution_and_tract()
    record = create_application(institution["id"])

    data = validate_success(
        api.create_geocode_assignment(
            create_geocode_assignment_payload(
                record["id"], record["version"],
                street_address="400 Main St", city="Houston", state_code="TX",
                zip_code="77002", county_fips="48201",
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert_geocode_assignment(data)
    assert data["status"] == "NOT_MATCHED"
    assert data["candidate_count"] == 0
    assert data["census_tract_id"] is None
    assert data["msa_md_code"] is None
    assert data["is_current"] is True


def test_manual_override_pins_an_ambiguous_assignment_to_a_named_tract(api):
    """PRD §3.4: "A successful override stores the tract, copies `msa_md_code`
    from it, stores `override_reason`, and increments the assignment's `version`
    by 1."
    PRD §3.4: "Override is defined only from `AMBIGUOUS → MANUAL_OVERRIDE` and
    from `NOT_MATCHED → MANUAL_OVERRIDE`; attempting it on an assignment that is
    `PENDING`, already `MATCHED`, or already overridden is refused with
    `ERR_GEOCODE_NOT_OVERRIDABLE`."

    Design: Corner/calculations/manual_override_resolves_ambiguous_assignment_to_named_tract
    """
    institution, _tract_a, tract_b = setup_institution_with_two_tracts()
    record = create_application(institution["id"])
    assignment = geocode_application(
        record["id"], record["version"], street_address="17 Folsom St"
    )
    assert assignment["status"] == "AMBIGUOUS"

    data = validate_success(
        api.manual_override_geocode(
            assignment["id"],
            manual_override_payload(
                tract_b["id"],
                override_reason="Parcel map places the property in tract 06075010200.",
            ),
            make_compliance_analyst_headers(),
        )
    )
    assert data["status"] == "MANUAL_OVERRIDE"
    assert data["census_tract_id"] == tract_b["id"]
    assert data["msa_md_code"] == TRACT_B["msa_md_code"]
    assert data["override_reason"] == "Parcel map places the property in tract 06075010200."

    rows, meta = validate_paginated(
        api.list_tract_geocode_assignments(tract_b["id"], TEST_USERS["examiner_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == assignment["id"]


def test_overriding_a_matched_assignment_is_rejected(api):
    """PRD §3.4: "Override is defined only from `AMBIGUOUS → MANUAL_OVERRIDE` and
    from `NOT_MATCHED → MANUAL_OVERRIDE`; attempting it on an assignment that is
    `PENDING`, already `MATCHED`, or already overridden is refused with
    `ERR_GEOCODE_NOT_OVERRIDABLE`."
    PRD §3.4: "Exactly one candidate: the assignment moves `PENDING → MATCHED`,
    `census_tract_id` is set to that tract, and `msa_md_code` is copied from it."

    Design: Corner/state_machines/manual_override_on_matched_geocode_rejected
    """
    institution, tract_a = setup_institution_and_tract()
    record = create_application(institution["id"])
    assignment = geocode_application(
        record["id"], record["version"], submitted_tract_code=TRACT_A["tract_code"]
    )
    assert assignment["status"] == "MATCHED"

    validate_error(
        api.manual_override_geocode(
            assignment["id"],
            manual_override_payload(
                tract_a["id"],
                override_reason="Attempting to override an already matched assignment.",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_GEOCODE_NOT_OVERRIDABLE.value,
    )

    rows, _meta = validate_paginated(
        api.list_application_geocode_assignments(record["id"], make_loan_officer_headers())
    )
    current = rows[0]
    assert current["status"] == "MATCHED"
    assert current["candidate_count"] == 1
    assert current["census_tract_id"] == tract_a["id"]
    assert current["msa_md_code"] == TRACT_A["msa_md_code"]


def test_overriding_with_a_tract_from_another_county_is_rejected(api):
    """PRD §3.4: "The pinned tract must sit in the same jurisdiction as the
    property: its `county_fips` and its `state_code` must both equal the
    assignment's own, and a mismatch on either is refused with
    `ERR_GEOCODE_TRACT_MISMATCH`."

    Design: Corner/validations/manual_override_with_mismatched_county_rejected
    """
    institution = create_institution()
    texas_tract = create_tract_tx()
    record = create_application(institution["id"])
    assignment = geocode_application(record["id"], record["version"])
    assert assignment["status"] == "NOT_MATCHED"

    validate_error(
        api.manual_override_geocode(
            assignment["id"],
            manual_override_payload(
                texas_tract["id"], override_reason="Wrong-county override attempt."
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_GEOCODE_TRACT_MISMATCH.value,
    )

    rows, _meta = validate_paginated(
        api.list_application_geocode_assignments(record["id"], make_loan_officer_headers())
    )
    assert rows[0]["status"] == "NOT_MATCHED"
    assert rows[0]["census_tract_id"] is None
    assert TRACT_TX["county_fips"] == "48201"


def test_overriding_with_an_unknown_tract_is_a_not_found(api):
    """PRD §2.9: "Body foreign-key resolution — the relevant not-found error, 404.
    This applies to opening a register record, recording a demographic entry,
    creating a geocode assignment, pinning a tract by manual override, starting an
    edit run, opening a submission, attaching an edit run to a submission, drawing
    an audit sample, recording an audit finding, and computing a fair lending
    analysis."
    PRD §2.9: "Cross-field referential accuracy, in this order —
    `ERR_DENIAL_REASON_REQUIRED`, `ERR_DENIAL_REASON_NOT_PERMITTED`,
    `ERR_PURCHASER_TYPE_REQUIRED`, `ERR_GEOCODE_TRACT_MISMATCH`,
    `ERR_EDIT_RUN_INSTITUTION_MISMATCH`, `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`,
    all 422."

    Design: Corner/errors/manual_override_with_unknown_tract_returns_not_found
    """
    institution = create_institution()
    record = create_application(institution["id"])
    assignment = geocode_application(record["id"], record["version"])

    validate_error(
        api.manual_override_geocode(
            assignment["id"],
            manual_override_payload(UNKNOWN_ID, override_reason="Unknown tract id."),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_CENSUS_TRACT_NOT_FOUND.value,
    )

    rows, _meta = validate_paginated(
        api.list_application_geocode_assignments(record["id"], make_loan_officer_headers())
    )
    assert rows[0]["status"] == "NOT_MATCHED"


def test_overriding_an_unknown_assignment_is_a_not_found(api):
    """PRD §2.6: "Path identifiers are resolved strictly left to right, and the
    first identifier that fails to resolve determines the response."
    PRD §2.9: "Path identifier resolution, left to right — the relevant not-found
    error, 404."

    Design: Corner/errors/override_unknown_geocode_assignment_returns_not_found
    """
    tract = create_tract_a()

    validate_error(
        api.manual_override_geocode(
            UNKNOWN_ID,
            manual_override_payload(tract["id"], override_reason="No such assignment."),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_GEOCODE_ASSIGNMENT_NOT_FOUND.value,
    )


def test_re_geocoding_with_a_stale_record_version_is_rejected(api):
    """PRD §2.8: "Creating a geocode assignment requires the client to supply
    `expected_application_version`, carrying the `version` of the target
    `Application` the client last observed. If that value does not equal the
    application's current `version`, the create is rejected with
    `ERR_STALE_APPLICATION_VERSION` and HTTP 412, and the previous assignment's
    `is_current` flag is left untouched."

    Design: Corner/cross_cutting_layers/stale_expected_application_version_on_geocode_create_rejected
    """
    institution, _tract = setup_institution_and_tract()
    record = create_application(institution["id"])
    first = geocode_application(
        record["id"], record["version"], submitted_tract_code=TRACT_A["tract_code"]
    )

    validate_error(
        api.create_geocode_assignment(
            create_geocode_assignment_payload(
                record["id"], record["version"],
                street_address="2 Market St",
                submitted_tract_code=TRACT_A["tract_code"],
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_STALE_APPLICATION_VERSION.value,
    )

    rows, meta = validate_paginated(
        api.list_application_geocode_assignments(record["id"], make_loan_officer_headers())
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["is_current"] is True


def test_re_geocoding_with_the_current_version_supersedes_the_previous_assignment(api):
    """PRD §3.4: "Creating a new assignment always sets the record's previous
    assignment's `is_current` flag to false, so exactly one assignment per record
    is current at any moment, and it increments the register record's `version` by
    1."
    PRD §3.4: "The full history remains readable through the record's geocode
    listing, newest last."

    Design: Corner/cross_cutting_layers/fresh_expected_application_version_supersedes_previous_assignment
    """
    institution, _tract = setup_institution_and_tract()
    record = create_application(institution["id"])
    first = geocode_application(
        record["id"], record["version"], submitted_tract_code=TRACT_A["tract_code"]
    )
    refreshed = read_application(record["id"])

    second = validate_success(
        api.create_geocode_assignment(
            create_geocode_assignment_payload(
                record["id"], refreshed["version"],
                street_address="2 Market St",
                submitted_tract_code=TRACT_A["tract_code"],
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert second["status"] == "MATCHED"
    assert second["is_current"] is True

    rows, meta = validate_paginated(
        api.list_application_geocode_assignments(record["id"], make_loan_officer_headers())
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["is_current"] is False
    assert by_id[second["id"]]["is_current"] is True
    assert read_application(record["id"])["version"] == 3
