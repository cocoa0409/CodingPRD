"""
The declared shape of the record layer: defaults, computed fields and identity.

These are the promises a caller relies on before any workflow starts — what a freshly
registered parcel looks like, which inputs the server refuses and which it quietly
overrides, what a list envelope reports, which entity is immutable, and where a
uniqueness or a not-found rule bites.
"""

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    CLOCK_EPOCH,
    ERR_DUPLICATE_LIABILITY_PROTECTION,
    ERR_INVALID_REQUEST,
    ERR_PHASE_NOT_FOUND,
    ERR_SITE_NOT_FOUND,
    PROGRAM_ADMIN,
    REVIEWER_ALPHA,
    add_assessment_phase,
    add_finding,
    cleanup_goal_payload,
    add_site,
    assert_fields,
    assert_number,
    assert_pagination_meta,
    assessment_phase_payload,
    finding_payload,
    ids_of,
    liability_protection_payload,
    party_payload,
    set_clock,
    site_payload,
    stage_assessed,
    stage_goals,
    stage_protection,
    stage_registry,
    stage_site,
)

UNKNOWN_SITE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PHASE_ID = "22222222-2222-4222-8222-222222222222"


def test_registering_a_parcel_returns_every_declared_starting_value(api):
    """
    One create call, and the three derived values plus the two counters are all fixed.

    "A newly registered parcel starts in a known posture: `acquisition_status` is
    `UNDER_CONTRACT`, `acquisition_date` is null, `delineation_status` is `NONE`,
    `cleanup_posture` is `OPEN` and `impaired_control_count` is zero."

    Design: Corner/entities/create_site_returns_declared_system_and_computed_defaults
    """
    world = stage_registry(api)

    site = get_success_data(
        api.create_site(site_payload(world.redeveloper["id"]), world.redev_headers), 201
    )
    assert_fields(
        site,
        owner_party_id=world.redeveloper["id"],
        site_name="Kinnickinnic Rail Yard",
        county_code="OH-039",
        intended_reuse="COMMERCIAL",
        planned_acquisition_date="2026-10-15",
        institutional_control_committed=True,
        acquisition_status="UNDER_CONTRACT",
        acquisition_date=None,
        delineation_status="NONE",
        cleanup_posture="OPEN",
        impaired_control_count=0,
        version=1,
    )
    assert_number(site["acreage"], 12.4, "acreage")
    assert is_valid_uuid(site["id"]), f"the parcel id must be a UUID, got {site['id']!r}"
    assert_timestamp_format(site["created_at"])
    assert_timestamp_format(site["updated_at"])


def test_omitting_the_control_commitment_stores_false(api):
    """
    The one optional input on the parcel create has a declared default, not a null.

    "An optional `institutional_control_committed` boolean defaults to false."

    Design: Corner/entities/create_site_omitting_institutional_control_applies_false_default
    """
    world = stage_registry(api)
    payload = site_payload(
        world.redeveloper["id"],
        site_name="Cuyahoga Tannery Parcel",
        county_code="OH-035",
        acreage=3.75,
        intended_reuse="RESIDENTIAL",
        planned_acquisition_date="2026-11-01",
    )
    payload.pop("institutional_control_committed")

    created = get_success_data(api.create_site(payload, world.redev_headers), 201)
    assert_fields(
        created,
        institutional_control_committed=False,
        intended_reuse="RESIDENTIAL",
        cleanup_posture="OPEN",
    )

    echoed = get_success_data(api.get_site(created["id"], world.redev_headers))
    assert_fields(echoed, institutional_control_committed=False)


def test_supplying_the_derived_parcel_values_does_not_change_them(api):
    """
    Posture, title and the impairment count are the server's to write, not the client's.

    "It is never set by a client; it is recomputed synchronously, inside the triggering
    request, every time a side effect changes either the site's `impaired_control_count` or
    its liability protection's `bfpp_status`."

    Design: Corner/entities/create_site_system_field_input_ignored
    """
    world = stage_registry(api)
    payload = site_payload(
        world.redeveloper["id"],
        site_name="Maumee Foundry Block",
        county_code="OH-095",
        acreage=8.0,
        intended_reuse="INDUSTRIAL",
        planned_acquisition_date="2026-12-01",
        acquisition_status="ACQUIRED",
        acquisition_date="2026-01-01",
        cleanup_posture="FROZEN",
        impaired_control_count=9,
        version=42,
    )

    created = get_success_data(api.create_site(payload, world.redev_headers), 201)
    assert_fields(
        created,
        acquisition_status="UNDER_CONTRACT",
        acquisition_date=None,
        cleanup_posture="OPEN",
        impaired_control_count=0,
        version=1,
    )


def test_a_parcel_without_an_intended_reuse_is_refused_and_not_stored(api):
    """
    The most consequential input has no default, so its absence is a shape violation.

    "**Request shape** — every required field present, every type correct, every enum
    member recognised, every numeric range honoured, every date and datetime parseable,
    every conditional field pairing legal; else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_site_missing_required_intended_reuse_returns_invalid_request
    """
    world = stage_registry(api)
    payload = site_payload(
        world.redeveloper["id"],
        site_name="Scioto Gasworks",
        county_code="OH-049",
        acreage=5.0,
        planned_acquisition_date="2026-12-15",
    )
    payload.pop("intended_reuse")

    response = api.create_site(payload, world.redev_headers)
    validate_error(response, ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(
        api.list_sites(world.redev_headers, owner_party_id=world.redeveloper["id"])
    )
    assert_pagination_meta(meta, expected_total=0)


def test_the_party_registry_refuses_a_role_name_and_a_spelled_out_state(api):
    """
    Lender is a programme role, not a party type, and the state code is two letters.

    "A `ProgramAdmin` registers each organisation that will participate, supplying its
    `legal_name` (1 to 160 characters, required), its `party_type`, its `state_code`
    (exactly two uppercase letters, the US state of registration) and, where applicable,
    its `licence_number`."

    Design: Corner/entities/create_party_invalid_enum_party_type_rejected
    """
    set_clock(api, CLOCK_EPOCH)

    bad_type = api.create_party(
        party_payload(legal_name="Fifth Third Bank", party_type="LENDER"), PROGRAM_ADMIN
    )
    validate_error(bad_type, ERR_INVALID_REQUEST, 422)

    bad_state = api.create_party(
        party_payload(
            legal_name="Terraline Environmental PC",
            party_type="CONSULTANT",
            state_code="Ohio",
            licence_number="OH-PG-4417",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(bad_state, ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(api.list_parties(PROGRAM_ADMIN))
    assert_pagination_meta(meta, expected_total=0)


def test_reading_an_unminted_parcel_id_is_a_not_found(api):
    """
    A well-formed identifier that names nothing is a 404, not an empty success.

    "Each resource kind has its own not-found code so the caller can tell which segment
    failed: `ERR_SITE_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_PROTECTION_NOT_FOUND`,
    `ERR_OBLIGATION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_CONTROL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_LETTER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_GOAL_NOT_FOUND`,
    `ERR_FINDING_NOT_FOUND`, `ERR_PARTY_NOT_FOUND` and `ERR_LAB_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_site_with_unknown_id_returns_site_not_found
    """
    world = stage_registry(api)
    stage_site(world)

    response = api.get_site(UNKNOWN_SITE_ID, world.redev_headers)
    validate_error(response, ERR_SITE_NOT_FOUND, 404)

    assert_fields(
        get_success_data(api.get_site(world.site["id"], world.redev_headers)),
        id=world.site["id"],
    )


def _three_parcels_for_one_owner(api):
    """One owner holding three parcels, created in a fixed order."""
    world = stage_registry(api)
    stage_site(world)
    second = add_site(
        world,
        site_name="Cuyahoga Tannery Parcel",
        county_code="OH-035",
        acreage=3.75,
        intended_reuse="RESIDENTIAL",
        planned_acquisition_date="2026-11-01",
    )
    third = add_site(
        world,
        site_name="Maumee Foundry Block",
        county_code="OH-095",
        acreage=8.0,
        intended_reuse="INDUSTRIAL",
        planned_acquisition_date="2026-12-01",
    )
    return world, second, third


def test_the_parcel_list_pages_through_the_owners_three_rows(api):
    """
    Each page reports the size of the whole match, not the size of the window.

    "Every list response populates four pagination fields inside `meta`: `limit` (the page
    size actually applied), `offset` (the starting position actually applied),
    `total_count` (the number of rows matching the filters before the page window is
    applied), and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/list_sites_pagination_envelope_reports_total_count_and_has_more
    """
    world, second, third = _three_parcels_for_one_owner(api)

    first_page, first_meta = validate_paginated(
        api.list_sites(
            world.redev_headers, owner_party_id=world.redeveloper["id"], limit=2, offset=0
        )
    )
    assert len(first_page) == 2, "a limit of 2 returns two rows"
    assert_pagination_meta(
        first_meta, expected_total=3, expected_limit=2, expected_offset=0, expected_has_more=True
    )

    second_page, second_meta = validate_paginated(
        api.list_sites(
            world.redev_headers, owner_party_id=world.redeveloper["id"], limit=2, offset=2
        )
    )
    assert len(second_page) == 1, "one row remains beyond the first window"
    assert_pagination_meta(
        second_meta, expected_total=3, expected_limit=2, expected_offset=2, expected_has_more=False
    )

    assert sorted(ids_of(first_page) + ids_of(second_page)) == sorted(
        [world.site["id"], second["id"], third["id"]]
    ), "the two pages together carry each parcel exactly once"


def test_the_posture_filter_narrows_the_total_count_to_the_filtered_set(api):
    """
    No parcel is frozen yet, so the filtered listing is empty rather than complete.

    "The site list can be filtered by `owner_party_id` and by `cleanup_posture`, and an
    individual read exposes the three derived values alongside the inputs."

    Design: Corner/entities/list_sites_pagination_envelope_reports_total_count_and_has_more
    """
    _world, _second, _third = _three_parcels_for_one_owner(api)

    rows, meta = validate_paginated(api.list_sites(REVIEWER_ALPHA, cleanup_posture="FROZEN"))
    assert rows == [], "no parcel has a forfeited defence yet"
    assert_pagination_meta(meta, expected_total=0, expected_has_more=False)


def test_the_finding_computes_its_exceedance_factor_and_carries_no_version(api):
    """
    An analytical result is derived once and then frozen — it has no version to bump.

    "The one exception is `ContaminantFinding`: an analytical finding is immutable once
    recorded, so it carries only `id` and `created_at`."

    Design: Corner/entities/contaminant_finding_exceedance_factor_is_computed_and_immutable
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    phase = add_assessment_phase(world)

    finding = add_finding(world, phase)
    assert_number(finding["exceedance_factor"], "96.00", "exceedance_factor")
    assert_fields(finding, assessment_phase_id=phase["id"], delineated=False)
    assert "version" not in finding, "an immutable finding carries no version"
    assert "updated_at" not in finding, "an immutable finding carries no updated_at"
    assert_timestamp_format(finding["created_at"])

    read_back = get_success_data(
        api.get_contaminant_finding(finding["id"], world.consult_headers)
    )
    assert "version" not in read_back, "the read exposes no version either"

    parent = get_success_data(api.get_assessment_phase(phase["id"], world.consult_headers))
    assert_fields(parent, findings_count=1)
    assert_number(parent["max_exceedance_factor"], "96.00", "max_exceedance_factor")


def test_an_unminted_phase_reference_is_a_phase_not_found_in_both_positions(api):
    """
    The path parent and the self-reference in the body report the same missing phase.

    "URLs in this API are shallow — at most one path identifier followed by a
    sub-collection — but where a path carries an identifier, that identifier is resolved
    before anything in the body is examined, and where more than one identifier appears
    they are resolved strictly left to right."

    Design: Corner/entities/create_finding_under_unknown_phase_returns_phase_not_found
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    phase = add_assessment_phase(world)

    orphan_finding = api.record_contaminant_finding(
        UNKNOWN_PHASE_ID,
        finding_payload(
            contaminant_code="PCE",
            media="SOIL",
            sample_location_code="SB-09",
            max_concentration_ugl=12.0,
            screening_level_ugl=3.0,
        ),
        world.consult_headers,
    )
    validate_error(orphan_finding, ERR_PHASE_NOT_FOUND, 404)

    orphan_supersede = api.create_assessment_phase(
        assessment_phase_payload(
            world.site["id"],
            world.consultant["id"],
            phase_type="SUPPLEMENTAL",
            field_start_date="2026-07-15",
            field_end_date="2026-07-25",
            delineation_confidence="PARTIAL",
            supersedes_phase_id=UNKNOWN_PHASE_ID,
        ),
        world.consult_headers,
    )
    validate_error(orphan_supersede, ERR_PHASE_NOT_FOUND, 404)

    _findings, finding_meta = validate_paginated(
        api.list_contaminant_findings(phase["id"], world.consult_headers)
    )
    assert_pagination_meta(finding_meta, expected_total=0)
    _phases, phase_meta = validate_paginated(
        api.list_assessment_phases(world.consult_headers, site_id=world.site["id"])
    )
    assert_pagination_meta(phase_meta, expected_total=1)


def test_a_parcel_may_not_be_given_a_second_protection_record(api):
    """
    The defence file is one per parcel, and the second attempt is a conflict.

    "The owning `Redeveloper` opens the file by supplying only `site_id`; at most one such
    record may exist per parcel, and a second attempt is refused with
    `ERR_DUPLICATE_LIABILITY_PROTECTION` (HTTP 409)."

    Design: Corner/entities/site_cannot_be_given_a_second_liability_protection
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)

    duplicate = api.create_liability_protection(
        liability_protection_payload(world.site["id"]), world.redev_headers
    )
    validate_error(duplicate, ERR_DUPLICATE_LIABILITY_PROTECTION, 409)

    rows, meta = validate_paginated(
        api.list_site_liability_protections(world.site["id"], world.redev_headers)
    )
    assert ids_of(rows) == [world.protection["id"]], "the collection holds the one record"
    assert_pagination_meta(meta, expected_total=1)

    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_PENDING",
        obligation_state="OBLIGATIONS_NONE",
        bfpp_status="NOT_ESTABLISHED",
        obligations_total_weight=0,
    )
    assert_number(world.protection["compliance_pct"], "1.0000", "compliance_pct")


def test_rederiving_the_same_analyte_and_media_upserts_the_one_goal(api):
    """
    The triple is the identity, so a second derivation rewrites the row it finds.

    "The triple of site, `contaminant_code` and `media` is unique: a repeat derivation for
    the same triple does not create a second row, it upserts the existing goal, recomputes
    `goal_ugl`, increments that goal's `version` by 1, and recomputes its
    `compliant_streak` and `attainment_status` against the newly derived target."

    Design: Corner/entities/cleanup_goal_upsert_on_repeat_triple_bumps_version
    """
    world = stage_assessed(api)
    stage_goals(world)
    assert_number(world.goal_restricted["goal_ugl"], "250.00", "goal_ugl")
    assert_fields(world.goal_restricted, cumulative_cap_applied=True)

    upserted = get_success_data(
        api.derive_cleanup_goal(
            world.site["id"],
            cleanup_goal_payload(
                contaminant_code="TCE",
                media="SOIL_VAPOR",
                screening_level_ugl=5.0,
                basis="UNRESTRICTED",
            ),
            world.redev_headers,
        )
    )
    assert_fields(
        upserted,
        id=world.goal_restricted["id"],
        basis="UNRESTRICTED",
        control_credit_type=None,
        cumulative_cap_applied=False,
        version=world.goal_restricted["version"] + 1,
    )
    assert_number(upserted["goal_ugl"], "166.67", "goal_ugl")

    _rows, meta = validate_paginated(
        api.list_cleanup_goals(world.site["id"], world.consult_headers)
    )
    assert_pagination_meta(meta, expected_total=2)
