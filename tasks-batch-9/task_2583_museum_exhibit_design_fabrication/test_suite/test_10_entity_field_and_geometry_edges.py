"""Field-level contracts on the entities the PRD declares.

These tests pin the values the PRD derives at creation time: the five money
buckets of a fresh commission, the declared defaults of a gallery zone and an
install window, the system-owned fields a client may not write, the review
round's quorum, the case geometry and strictest-wins envelope, and the
pagination envelope of the project list.
"""

from test_helpers import (
    CURATOR,
    FABRICATION,
    NON_EXISTENT_UUID,
    OPERATIONS,
    PM,
    USER_FABRICATION,
    USER_PM,
    CaseStatus,
    MountStatus,
    OccupancyState,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    RoundStatus,
    WindowStatus,
    WorkClass,
    assert_common_fields,
    assert_counters,
    assert_envelope,
    assert_geometry,
    assert_ledger,
    assert_zone_slots,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)


def test_new_commission_seeds_five_settled_buckets_and_the_default_closure_cap(api):
    """A commission created with only its required fields reports every computed
    field the PRD pins for a brand-new row: a settled ledger, six zero counters,
    an OPEN posture, empty handover fields and the omitted closure cap at 2.

    "The new project opens in phase `INTERPRETIVE` at `version` 1, with `created_by_user_id` taken from the caller's header."
    "Its ledger starts settled: `committed_fabrication_cents`, `retainage_held_cents`, `warranty_reserve_cents` and `released_cents` are each 0 and `uncommitted_cents` equals `contract_value_cents`, so the five-bucket identity of §2.7 holds from the first instant."
    "All six posture counters are 0 and `posture` is therefore `OPEN`."
    "The closeout-only fields are empty until closeout writes them: `parts_commitment_years` is 0, and `docent_kit_url`, `maintenance_manual_url` and `warranty_registered_at` are all null."
    "The optional `max_concurrent_closures` caps how many closure-requiring install windows the museum will tolerate running at once across the whole project; it must be at least 1 and at most 5, and when omitted it defaults to 2."

    Design: Corner/entities/exhibit_project_creation_seeds_every_computed_bucket_and_the_default_closure_capacity
    """
    fixtures.set_clock(api)

    project = validate_success(
        api.create_project(
            factories.project_payload(contract_value_cents=9000000), PM
        ),
        201,
    )

    assert is_valid_uuid(project["id"])
    assert_common_fields(project, expected_version=1)
    assert project["phase"] == Phase.INTERPRETIVE
    assert project["posture"] == Posture.OPEN
    assert project["created_by_user_id"] == USER_PM
    assert project["contract_value_cents"] == 9000000
    assert project["max_concurrent_closures"] == 2

    assert project["committed_fabrication_cents"] == 0
    assert project["retainage_held_cents"] == 0
    assert project["warranty_reserve_cents"] == 0
    assert project["released_cents"] == 0
    assert_ledger(project, committed=0, uncommitted=9000000)

    assert_counters(
        project,
        conservation_veto_count=0,
        conservation_block_count=0,
        open_revision_count=0,
        conditional_case_count=0,
        pending_material_count=0,
        blocking_punch_count=0,
    )

    assert project["parts_commitment_years"] == 0
    assert project["docent_kit_url"] is None
    assert project["maintenance_manual_url"] is None
    assert project["warranty_registered_at"] is None


def test_gallery_zone_optional_flags_take_their_declared_defaults(api):
    """A zone registered without its three optional flags reports the declared
    defaults and opens with an empty, self-consistent slot pool.

    "Three flags are optional: `is_public_operating`, true by default, records whether the zone stays open to visitors during the install period; `closure_allowed`, false by default, records whether the museum will permit closing the zone to visitors for work at all; and `dust_settling_buffer_minutes`, 120 by default and constrained to between 0 and 480 inclusive, is the zone's own minimum settling period after dust-generating work."
    "A new zone starts with `reserved_case_slots` at 0 and `available_case_slots` equal to its capacity, so the slot identity of §2.7 holds from creation, and with `occupancy_state` at `OPERATING`."

    Design: Corner/entities/gallery_zone_and_project_optional_fields_take_their_declared_defaults
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)

    zone = validate_success(
        api.create_gallery_zone(
            project["id"],
            factories.gallery_zone_payload(zone_code="Z-A", case_slot_capacity=4),
            OPERATIONS,
        ),
        201,
    )

    assert_common_fields(zone, expected_version=1)
    assert zone["is_public_operating"] is True
    assert zone["closure_allowed"] is False
    assert zone["dust_settling_buffer_minutes"] == 120
    assert zone["occupancy_state"] == OccupancyState.OPERATING
    assert zone["case_slot_capacity"] == 4
    assert_zone_slots(zone, reserved=0, available=4)

    stored = validate_success(api.get_gallery_zone(zone["id"], PM))
    assert stored["is_public_operating"] is True
    assert stored["closure_allowed"] is False
    assert stored["dust_settling_buffer_minutes"] == 120
    assert stored["occupancy_state"] == OccupancyState.OPERATING
    assert stored["version"] == 1
    assert_zone_slots(stored, reserved=0, available=4)


def test_quiet_install_window_is_born_with_no_closure_and_zero_buffers(api):
    """A QUIET window requested without the optional closure flag reports the
    declared default, both zero buffers, and effective instants identical to the
    nominal ones.

    "The request carries `project_id`, the `zone_id` of the gallery it occupies — which must belong to the same project, or the request answers `ERR_CROSS_PROJECT_REFERENCE` — a `work_class` of `QUIET`, `NOISY`, `DUST_GENERATING` or `CRANE_ACCESS`, the anticipated `noise_dba` between 0 and 130 inclusive, the nominal `starts_at` and `ends_at` instants, and an optional `requires_gallery_closure` flag that defaults to false."
    "The `pre_access_buffer_minutes` — the time the crew needs to protect objects and lay down floor covering before the nominal start — is 0 for `QUIET`, 15 for `NOISY`, 30 for `DUST_GENERATING` and 45 for `CRANE_ACCESS`."
    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."
    "The window is stored at status `REQUESTED` with `requested_by_user_id` from the caller and `denial_reason` null."

    Design: Corner/entities/gallery_zone_and_project_optional_fields_take_their_declared_defaults
    """
    ctx = fixtures.project_in_phase(
        api, Phase.FABRICATION, zone_overrides={"case_slot_capacity": 4}
    )

    window = validate_success(
        api.create_install_window(
            factories.install_window_payload(
                ctx["project_id"],
                ctx["zone_id"],
                work_class=WorkClass.QUIET,
                noise_dba=50.0,
            ),
            FABRICATION,
        ),
        201,
    )

    assert_common_fields(window, expected_version=1)
    assert window["status"] == WindowStatus.REQUESTED
    assert window["requested_by_user_id"] == USER_FABRICATION
    assert window["denial_reason"] is None
    assert window["requires_gallery_closure"] is False
    assert window["pre_access_buffer_minutes"] == 0
    assert window["settling_buffer_minutes"] == 0
    assert is_iso8601_timestamp(window["effective_start_at"])
    assert is_iso8601_timestamp(window["effective_end_at"])
    assert window["effective_start_at"] == window["starts_at"]
    assert window["effective_end_at"] == window["ends_at"]

    zone = validate_success(api.get_gallery_zone(ctx["zone_id"], PM))
    assert zone["occupancy_state"] == OccupancyState.OPERATING


def test_client_supplied_system_and_derived_case_fields_are_ignored(api):
    """A case created with a hand-written identifier, version, status and geometry
    is stored with the server's own values: the identifier is minted, the version
    starts at 1, the status is DRAFT and both geometry figures are recomputed
    from the interior dimensions.

    "Every resource carries an `id` that is a server-minted UUID with no type prefix; clients never supply it."
    "The case is stored with `status` `DRAFT`, `mount_status` `NOT_STARTED`, `placed_artifact_count` 0, `conditions` null and `decided_at` null."
    "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."
    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    "Because the case is empty, `required_rh_min_pct`, `required_rh_max_pct` and `allowed_lux` are all null while `env_feasible` and `security_ok` are both true."

    Design: Corner/entities/client_supplied_system_and_computed_fields_are_input_ignored
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project["id"])

    case = validate_success(
        api.create_artifact_case(
            project["id"],
            factories.artifact_case_payload(
                zone["id"],
                id=NON_EXISTENT_UUID,
                version=99,
                status=CaseStatus.APPROVED,
                mount_status=MountStatus.MOUNT_INSTALLED,
                placed_artifact_count=7,
                case_volume_m3=999.0,
                silica_gel_kg=999.0,
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:00Z",
                decided_at="2020-01-01T00:00:00Z",
                conditions="client supplied conditions",
            ),
            PM,
        ),
        201,
    )

    assert case["id"] != NON_EXISTENT_UUID
    assert_common_fields(case, expected_version=1)
    assert case["status"] == CaseStatus.DRAFT
    assert case["mount_status"] == MountStatus.NOT_STARTED
    assert case["placed_artifact_count"] == 0
    assert case["conditions"] is None
    assert case["decided_at"] is None
    assert_geometry(case, case_volume_m3=0.648, silica_gel_kg=0.91)
    assert case["required_rh_min_pct"] is None
    assert case["required_rh_max_pct"] is None
    assert case["allowed_lux"] is None
    assert case["env_feasible"] is True
    assert case["security_ok"] is True

    stored = validate_success(api.get_artifact_case(case["id"], PM))
    assert stored["id"] == case["id"]
    assert stored["version"] == 1
    assert stored["status"] == CaseStatus.DRAFT
    assert stored["mount_status"] == MountStatus.NOT_STARTED
    assert stored["created_at"] == case["created_at"]
    assert_geometry(stored, case_volume_m3=0.648, silica_gel_kg=0.91)


def test_review_round_quorum_rounds_two_thirds_of_the_seated_panel_up(api):
    """Opening a round on a three-, four- and five-seat panel fixes the quorum at
    2, 3 and 4 votes respectively, and every round is numbered from 1 inside its
    own package.

    "Its `required_vote_count` is the quorum: two thirds of the seated panel, rounded **up** to a whole vote."
    "A panel of three therefore needs 2 votes, a panel of four needs 3, and a panel of five needs 4."
    "The new round records the package it reviews through its `package_id` and takes a `round_number` equal to the package's `review_round_count` plus one, so rounds are numbered from 1 within each package."

    Design: Corner/entities/the_review_round_quorum_is_computed_from_the_panel_size_at_open_time
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    panels = [
        ["Curator", "Conservator", "FabricationLead"],
        ["Curator", "Conservator", "FabricationLead", "AccessibilitySpecialist"],
        [
            "Curator",
            "Conservator",
            "FabricationLead",
            "AccessibilitySpecialist",
            "ProjectManager",
        ],
    ]
    expected_quorums = [2, 3, 4]

    for panel_roles, expected_quorum in zip(panels, expected_quorums):
        package = fixtures.create_package(
            api, project_id, stage=PackageStage.SCHEMATIC
        )
        review_round = validate_success(
            api.create_review_round(
                package["id"],
                factories.review_round_payload(
                    panel_roles=panel_roles,
                    decision_deadline_at=fixtures.FAR_DEADLINE,
                ),
                PM,
            ),
            201,
        )
        assert review_round["package_id"] == package["id"]
        assert review_round["panel_roles"] == panel_roles
        assert review_round["required_vote_count"] == expected_quorum, (
            "a panel of %d must need %d votes"
            % (len(panel_roles), expected_quorum)
        )
        assert review_round["round_number"] == 1
        assert review_round["status"] == RoundStatus.OPEN
        assert review_round["cast_vote_count"] == 0


def test_issuing_a_package_supersedes_the_earlier_sheet_and_closes_its_open_round(api):
    """The second package of a stage supersedes the first and names itself as the
    successor, and the round still open on the superseded package is closed as
    CLOSED_SUPERSEDED and stamped with the current clock instant.

    "Every existing package of this project whose `stage` matches the new one and whose status is not already `SUPERSEDED` — that is, any package in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to `SUPERSEDED`, processed in ascending `created_at` order, and has its `superseded_by_package_id` set to the new package's identifier."
    "Every review round still `OPEN` on a superseded package is closed as `CLOSED_SUPERSEDED` with its `decided_at` set to the current logical-clock instant."

    Design: Corner/entities/the_review_round_quorum_is_computed_from_the_panel_size_at_open_time
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    first_package = fixtures.create_package(api, project_id, stage=PackageStage.SCHEMATIC)
    first_round = fixtures.open_round(
        api,
        first_package["id"],
        panel_roles=["Curator", "Conservator", "FabricationLead"],
        decision_deadline_at=fixtures.FAR_DEADLINE,
    )
    second_package = fixtures.create_package(
        api, project_id, stage=PackageStage.SCHEMATIC
    )

    superseded = validate_success(api.get_design_package(first_package["id"], PM))
    assert superseded["status"] == PackageStatus.SUPERSEDED
    assert superseded["superseded_by_package_id"] == second_package["id"]
    assert superseded["review_round_count"] == 1

    closed_round = validate_success(api.get_review_round(first_round["id"], PM))
    assert closed_round["status"] == RoundStatus.CLOSED_SUPERSEDED
    assert is_iso8601_timestamp(closed_round["decided_at"])
    assert closed_round["decided_at"].startswith("2026-08-01T00:00:00")

    assert second_package["status"] == PackageStatus.DRAFT
    assert second_package["superseded_by_package_id"] is None
    assert second_package["review_round_count"] == 0


def test_case_read_returns_the_strictest_wins_envelope_the_placement_wrote(api):
    """Reserving one object into a case rewrites the case's derived envelope, and a
    later read of the case reports exactly the same derived limits and flags as
    the placement produced, with the geometry untouched.

    "A successful placement sets the object's `assigned_case_id` to the case, moves its `placement_status` `UNPLACED → RESERVED`, increments the case's `placed_artifact_count`, and rewrites `required_rh_min_pct`, `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the new set."
    "When it is not empty, `required_rh_min_pct` becomes the **largest** of the objects' individual humidity floors, `required_rh_max_pct` becomes the **smallest** of their humidity ceilings, and `allowed_lux` becomes the **smallest** of their `max_lux` values."
    "Every one of those comparisons is inclusive, so a case whose `target_lux` exactly equals the strictest `allowed_lux` passes."

    Design: Corner/entities/artifact_case_retrieval_returns_the_same_derived_envelope_the_placement_returned
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project["id"])
    artifact = fixtures.create_artifact(
        api,
        project["id"],
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
    )
    case = fixtures.create_case(
        api,
        project["id"],
        zone["id"],
        target_rh_pct=50.0,
        rh_tolerance_pct=5.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
    )

    placed_object = validate_success(
        api.create_placement(
            case["id"], factories.placement_payload(artifact["id"], 1), CURATOR
        ),
        201,
    )
    assert placed_object["id"] == artifact["id"]
    assert placed_object["assigned_case_id"] == case["id"]
    assert placed_object["placement_status"] == PlacementStatus.RESERVED
    assert placed_object["version"] == 2

    stored_case = validate_success(api.get_artifact_case(case["id"], PM))
    assert_envelope(
        stored_case,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )
    assert stored_case["version"] == 2
    assert_geometry(stored_case, case_volume_m3=0.648, silica_gel_kg=0.91)


def test_project_list_pages_newest_first_with_total_count_and_a_phase_filter(api):
    """The project list returns every commission newest first inside the declared
    default window, reports the pre-window total in meta, walks a two-row window
    without repeating or dropping a row, and narrows to the single commission in
    the requested phase.

    "Every list endpoint accepts `limit` and `offset` as query-string parameters."
    "`limit` defaults to 10, may not be smaller than 1 and may not be larger than 100; `offset` defaults to 0 and may not be negative."
    "The four pagination fields `limit`, `offset`, `total_count` and `has_more` are returned inside `meta` on every list response, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` is true when rows remain beyond the current window."
    "The project list may be filtered by `phase` and by `posture`."

    Design: Corner/entities/exhibit_project_listing_paginates_with_total_count_and_filters_by_phase
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    first = fixtures.create_project(api, name="Hall One", contract_value_cents=1000000)
    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    second = fixtures.create_project(api, name="Hall Two", contract_value_cents=2000000)
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    third = fixtures.create_project(api, name="Hall Three", contract_value_cents=3000000)
    fixtures.advance(api, second["id"], Phase.SCHEMATIC)

    rows, meta = validate_paginated(api.list_projects(PM))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [third["id"], second["id"], first["id"]]

    page_one, meta_one = validate_paginated(
        api.list_projects(PM, params={"limit": 2, "offset": 0})
    )
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [third["id"], second["id"]]

    page_two, meta_two = validate_paginated(
        api.list_projects(PM, params={"limit": 2, "offset": 2})
    )
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert [row["id"] for row in page_two] == [first["id"]]

    filtered, filtered_meta = validate_paginated(
        api.list_projects(PM, params={"phase": Phase.SCHEMATIC})
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert [row["id"] for row in filtered] == [second["id"]]
    assert filtered[0]["phase"] == Phase.SCHEMATIC
