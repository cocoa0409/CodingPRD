"""Registration of projects, owners, facilities, investigations and conflicts."""
from test_helpers import (
    SECOND_FACILITY_PAYLOAD,
    THIRD_FACILITY_PAYLOAD,
    ZERO_UUID,
    assert_common_fields,
    assert_fields,
    assert_immutable_record_fields,
    assert_meta_envelope,
    assert_ordered_by_created_at,
    conflict_payload,
    facility_payload,
    identify_conflict,
    investigation_payload,
    make_program_admin_headers,
    make_utility_coordinator_headers,
    owner_payload,
    project_payload,
    record_investigation,
    register_facility,
    register_owner,
    select_resolution,
    validate_error,
    validate_paginated,
    validate_success,
    world_plan_approved,
    world_registry,
)


def test_project_registration_returns_its_declared_fields_and_derived_defaults(api):
    """PRD 3.1: "A newly registered project opens in `status` `PLANNING` with
    `clearance_posture` `CLEARANCE_PENDING`, and its four derived figures —
    `open_conflict_count`, `estimated_state_liability_cents`,
    `total_committed_reimbursement_cents` and `aggregate_compensable_delay_days`
    — all start at 0."

    Design: Corner/entities/project_creation_returns_every_declared_field_with_derived_defaults
    """
    payload = project_payload()
    response = api.create_project(payload, make_program_admin_headers())
    project = validate_success(response, 201)

    assert_fields(project, **payload)
    assert_fields(
        project,
        status="PLANNING",
        clearance_posture="CLEARANCE_PENDING",
        open_conflict_count=0,
        estimated_state_liability_cents=0,
        total_committed_reimbursement_cents=0,
        aggregate_compensable_delay_days=0,
        version=1,
    )
    assert_common_fields(project)
    assert_meta_envelope(response)
    assert response.json()["response_type"] == "object"


def test_facility_retrieval_returns_the_stored_row_unchanged(api):
    """PRD 3.2: "`occupancy_basis` states the documented legal basis on which the
    facility occupies the corridor and is one of `FEE_SIMPLE`,
    `PRIVATE_EASEMENT`, `FRANCHISE`, `PERMIT` or `UNDOCUMENTED`; it is the
    primary driver of who pays for relocation."

    Design: Corner/entities/facility_retrieval_returns_the_stored_row_unchanged
    """
    owner = register_owner(api)
    payload = facility_payload(owner["id"])
    created = validate_success(
        api.create_facility(payload, make_utility_coordinator_headers()), 201
    )

    fetched = validate_success(
        api.get_facility(created["id"], make_utility_coordinator_headers())
    )
    assert fetched["id"] == created["id"]
    assert_fields(fetched, **payload)
    assert_common_fields(fetched)


def test_conflict_listing_paginates_and_filters_by_project_and_status(api):
    """PRD 2.3: "The conflict collection filters on `project_id`, `facility_id`,
    `depends_on_conflict_id` and `status`."

    Design: Corner/entities/conflict_listing_paginates_and_filters_by_project_and_status
    """
    world = world_registry(api)
    facility_b = register_facility(api, world["owner_id"], **SECOND_FACILITY_PAYLOAD)
    facility_c = register_facility(api, world["owner_id"], **THIRD_FACILITY_PAYLOAD)
    conflict_a = identify_conflict(api, world["project_id"], world["facility_id"])
    identify_conflict(
        api,
        world["project_id"],
        facility_b["id"],
        conflict_station=220.0,
        clearance_deficiency_in=12,
    )
    identify_conflict(
        api,
        world["project_id"],
        facility_c["id"],
        conflict_station=320.0,
        clearance_deficiency_in=6,
    )
    select_resolution(api, conflict_a["id"], "RELOCATE")

    headers = make_utility_coordinator_headers()
    first_page, first_meta = validate_paginated(
        api.list_conflicts(headers, params={"project_id": world["project_id"], "limit": 2})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert_ordered_by_created_at(first_page)

    second_page, second_meta = validate_paginated(
        api.list_conflicts(
            headers, params={"project_id": world["project_id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    selected, selected_meta = validate_paginated(
        api.list_conflicts(
            headers,
            params={"project_id": world["project_id"], "status": "RESOLUTION_SELECTED"},
        )
    )
    assert selected_meta["total_count"] == 1
    assert [row["id"] for row in selected] == [conflict_a["id"]]

    project = validate_success(
        api.get_project(world["project_id"], make_program_admin_headers())
    )
    assert project["open_conflict_count"] == 3


def test_unknown_conflict_id_is_not_found_on_reads_and_sub_resource_listings(api):
    """PRD 2.10: "For these two-segment reads the left-to-right existence rule of
    rung 4 is what matters: a request for the cost documents of a non-existent
    agreement returns `ERR_AGREEMENT_NOT_FOUND` and never an empty list."

    Design: Corner/entities/unknown_conflict_id_is_not_found_on_reads_and_on_sub_resource_listings
    """
    headers = make_utility_coordinator_headers()
    responses = [
        api.get_conflict(ZERO_UUID, headers),
        api.list_conflict_relocation_plans(ZERO_UUID, headers),
        api.list_conflict_permits(ZERO_UUID, headers),
        api.list_conflict_prior_rights(ZERO_UUID, headers),
    ]
    for response in responses:
        validate_error(response, "ERR_CONFLICT_NOT_FOUND")
        assert response.json()["response_type"] == "error"


def test_project_registration_without_a_letting_date_is_rejected(api):
    """PRD 2.9: "The request body and query parameters are schema-valid — required
    fields present, types correct, enumerated values in range, integers
    non-negative where declared"

    Design: Corner/entities/project_create_missing_required_letting_date_is_rejected
    """
    payload = project_payload()
    payload.pop("letting_date")

    validate_error(
        api.create_project(payload, make_program_admin_headers()), "ERR_INVALID_REQUEST"
    )

    _, meta = validate_paginated(api.list_projects(make_program_admin_headers()))
    assert meta["total_count"] == 0


def test_owner_registration_omitting_the_public_agency_flag_defaults_it_to_false(api):
    """PRD 3.1: "an optional `is_public_agency` flag that defaults to false and
    marks municipalities and public districts eligible for relief in prior-rights
    scoring"

    Design: Corner/entities/owner_create_omitting_is_public_agency_applies_the_declared_false_default
    """
    payload = owner_payload()
    payload.pop("is_public_agency")

    owner = validate_success(
        api.create_utility_owner(payload, make_program_admin_headers()), 201
    )
    assert_fields(
        owner,
        is_public_agency=False,
        delinquency_strikes=0,
        reimbursement_hold=False,
        open_commitment_days=0,
        assessed_delay_liability_cents=0,
    )


def test_investigation_contradicts_record_is_computed_from_the_reading(api):
    """PRD 3.2: "It is set to true when the investigation was taken at quality
    level `QL_A` and the absolute difference between its `measured_depth_in` and
    the facility's `depth_in` of record is greater than 6 inches — the depth
    tolerance."

    Design: Corner/entities/investigation_contradicts_record_is_computed_and_client_input_ignored
    """
    world = world_registry(api)
    payload = investigation_payload(
        world["project_id"],
        world["facility_id"],
        quality_level="QL_A",
        method="VACUUM_TEST_HOLE",
        measured_depth_in=60,
        station_at_investigation=120.0,
        contradicts_record=False,
    )

    investigation = validate_success(
        api.create_investigation(payload, make_utility_coordinator_headers()), 201
    )
    assert investigation["contradicts_record"] is True
    assert investigation["performed_at"] == "2026-08-01T00:00:00Z"


def test_project_identity_and_derived_figures_ignore_client_supplied_values(api):
    """PRD 2.4: "Every persisted resource carries an `id`: a server-minted UUID
    with no type prefix and no client control over its value."

    Design: Corner/entities/project_system_fields_are_generated_and_client_input_ignored
    """
    payload = project_payload(
        id="client-supplied-id",
        version=99,
        open_conflict_count=42,
        estimated_state_liability_cents=777,
    )

    project = validate_success(
        api.create_project(payload, make_program_admin_headers()), 201
    )
    assert project["id"] != "client-supplied-id"
    assert_common_fields(project)
    assert_fields(
        project,
        version=1,
        open_conflict_count=0,
        estimated_state_liability_cents=0,
        total_committed_reimbursement_cents=0,
        aggregate_compensable_delay_days=0,
    )


def test_facility_with_an_undeclared_occupancy_basis_is_rejected(api):
    """PRD 2.9: "The request body and query parameters are schema-valid — required
    fields present, types correct, enumerated values in range, integers
    non-negative where declared"

    Design: Corner/entities/facility_create_with_invalid_occupancy_basis_enum_is_rejected
    """
    owner = register_owner(api)

    validate_error(
        api.create_facility(
            facility_payload(owner["id"], occupancy_basis="HANDSHAKE"),
            make_utility_coordinator_headers(),
        ),
        "ERR_INVALID_REQUEST",
    )

    _, meta = validate_paginated(
        api.list_owner_facilities(owner["id"], make_utility_coordinator_headers())
    )
    assert meta["total_count"] == 0


def test_owner_indirect_cost_rate_above_the_ceiling_is_rejected(api):
    """PRD 3.1: "an `indirect_cost_rate_pct` — the owner's audited indirect cost
    rate as a percentage, between 0 and 35 inclusive with at most 2 decimal
    places, later applied to eligible direct cost at settlement"

    Design: Corner/entities/owner_indirect_cost_rate_above_thirtyfive_percent_is_rejected
    """
    headers = make_program_admin_headers()
    at_ceiling = validate_success(
        api.create_utility_owner(
            owner_payload(
                legal_name="Ceiling Rate Utility",
                utility_type="TELECOM",
                indirect_cost_rate_pct=35.00,
            ),
            headers,
        ),
        201,
    )
    assert at_ceiling["indirect_cost_rate_pct"] == 35.00

    validate_error(
        api.create_utility_owner(
            owner_payload(
                legal_name="Over Ceiling Utility",
                utility_type="TELECOM",
                indirect_cost_rate_pct=35.01,
            ),
            headers,
        ),
        "ERR_INVALID_REQUEST",
    )


def test_investigation_is_immutable_and_carries_no_version_counter(api):
    """PRD 2.4: "The single exception is the subsurface investigation record, which
    is immutable once written. It carries only `id` and `created_at`; both
    `updated_at` and `version` are absent from it, and no endpoint modifies it."

    Design: Corner/entities/investigation_is_immutable_with_no_update_path
    """
    world = world_registry(api)
    first = record_investigation(
        api,
        world["project_id"],
        world["facility_id"],
        quality_level="QL_D",
        method="RECORD_RESEARCH",
        measured_depth_in=48,
    )
    assert_immutable_record_fields(first)
    assert first["contradicts_record"] is False

    second = record_investigation(
        api,
        world["project_id"],
        world["facility_id"],
        quality_level="QL_A",
        measured_depth_in=61,
    )
    assert second["contradicts_record"] is True
    assert_immutable_record_fields(second)

    reread = validate_success(
        api.get_investigation(first["id"], make_utility_coordinator_headers())
    )
    assert reread["contradicts_record"] is False
    assert "version" not in reread
    assert "updated_at" not in reread

    rows, meta = validate_paginated(
        api.list_investigations(
            make_utility_coordinator_headers(),
            params={"facility_id": world["facility_id"]},
        )
    )
    assert meta["total_count"] == 2
    assert_ordered_by_created_at(rows)


def test_an_unknown_body_foreign_key_is_reported_before_anything_is_written(api):
    """PRD 2.9: "Every foreign key in the request body resolves to an existing
    row, checked in the order the endpoint declares its input fields."

    Design: Corner/entities/body_foreign_keys_are_resolved_before_type_and_state_checks
    """
    owner = register_owner(api)

    validate_error(
        api.create_facility(
            facility_payload(ZERO_UUID), make_utility_coordinator_headers()
        ),
        "ERR_OWNER_NOT_FOUND",
    )

    _, meta = validate_paginated(
        api.list_owner_facilities(owner["id"], make_utility_coordinator_headers())
    )
    assert meta["total_count"] == 0


def test_commitment_denormalises_project_facility_and_owner_from_the_plan(api):
    """PRD 3.7: "Three foreign keys on the commitment are derived rather than
    supplied, all denormalised at creation by following the plan to its conflict:
    `project_id` from the conflict's project, `facility_id` from the conflict's
    facility — this is the resource against which window collisions are tested —
    and `owner_id` from that facility's owner, which is what an owner-scope check
    compares against `X-User-ID`."

    Design: Corner/entities/commitment_denormalises_project_facility_and_owner_from_the_plan_chain
    """
    world = world_plan_approved(api)

    commitment = validate_success(
        api.create_commitment(
            {
                "plan_id": world["plan_id"],
                "window_start": "2027-04-05T00:00:00Z",
                "window_end": "2027-04-20T00:00:00Z",
                "committed_work_days": 11,
                "phase_dependency": "BEFORE_PAVING",
            },
            world["rep_headers"],
        ),
        201,
    )
    assert_fields(
        commitment,
        project_id=world["project_id"],
        facility_id=world["facility_id"],
        owner_id=world["owner_id"],
        joint_trench_slot_id=None,
        status="COMMITTED",
        actual_complete_at=None,
        late_days=0,
    )

    rows, meta = validate_paginated(
        api.list_commitments(world["rep_headers"], params={"owner_id": world["owner_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == commitment["id"]
    assert rows[0]["committed_work_days"] == 11


def test_a_conflict_may_name_a_predecessor_conflict_it_waits_on(api):
    """PRD 3.3: "An optional `depends_on_conflict_id` points at another conflict
    that must be cleared first; it defaults to null and is how clearance
    sequencing is expressed when, for example, a gas main cannot be moved until
    the fibre duct above it has been relocated."

    Design: Corner/entities/conflict_self_reference_records_a_sequenced_predecessor
    """
    world = world_registry(
        api,
        project_overrides={"name": "SR-14 Sequenced Reach"},
        facility_overrides=SECOND_FACILITY_PAYLOAD,
    )
    facility_b = register_facility(api, world["owner_id"])
    conflict_a = identify_conflict(
        api, world["project_id"], world["facility_id"], conflict_station=220.0
    )
    assert conflict_a["depends_on_conflict_id"] is None

    conflict_b = validate_success(
        api.create_conflict(
            conflict_payload(
                world["project_id"], facility_b["id"], depends_on_conflict_id=conflict_a["id"]
            ),
            make_utility_coordinator_headers(),
        ),
        201,
    )
    assert conflict_b["depends_on_conflict_id"] == conflict_a["id"]

    rows, meta = validate_paginated(
        api.list_conflicts(
            make_utility_coordinator_headers(),
            params={"depends_on_conflict_id": conflict_a["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == conflict_b["id"]

    project = validate_success(
        api.get_project(world["project_id"], make_program_admin_headers())
    )
    assert project["open_conflict_count"] == 2


def test_owner_listing_filters_by_utility_type_and_nested_facilities_paginate(api):
    """PRD 2.3: "The utility-owner collection filters on `utility_type` and
    `reimbursement_hold`."

    Design: Corner/endpoints/owner_and_facility_crud_with_the_nested_listing_and_its_filters
    """
    headers = make_program_admin_headers()
    owner_a = register_owner(api)
    facility_a1 = register_facility(api, owner_a["id"])
    facility_a2 = register_facility(api, owner_a["id"], **SECOND_FACILITY_PAYLOAD)
    owner_b = register_owner(
        api, legal_name="Northline Water District", utility_type="WATER"
    )
    facility_b1 = register_facility(
        api, owner_b["id"], occupancy_basis="FEE_SIMPLE"
    )

    first_page, first_meta = validate_paginated(
        api.list_owner_facilities(owner_a["id"], headers, params={"limit": 1})
    )
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    second_page, second_meta = validate_paginated(
        api.list_owner_facilities(
            owner_a["id"], headers, params={"limit": 1, "offset": 1}
        )
    )
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    listed = [first_page[0]["id"], second_page[0]["id"]]
    assert sorted(listed) == sorted([facility_a1["id"], facility_a2["id"]])
    assert facility_b1["id"] not in listed

    water, water_meta = validate_paginated(
        api.list_utility_owners(headers, params={"utility_type": "WATER"})
    )
    assert water_meta["total_count"] == 1
    assert water[0]["id"] == owner_b["id"]
