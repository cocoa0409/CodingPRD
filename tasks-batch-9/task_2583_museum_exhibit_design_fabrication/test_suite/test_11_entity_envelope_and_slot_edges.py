"""Referential-integrity and request-shape contracts on the entity graph.

These tests pin the eleven distinct not-found answers, the rejection of a body
that is malformed before anything is resolved, the declared numeric and enum
domains including their inclusive ceilings, the immutability of a cast vote, and
the refusal of a reference to a row filed under another commission.
"""

import pytest

from test_helpers import (
    CONSERVATOR,
    CURATOR,
    ERR_ARTIFACT_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_CROSS_PROJECT_REFERENCE,
    ERR_DRAWING_NOT_FOUND,
    ERR_DUPLICATE_VOTE,
    ERR_INTERACTIVE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MATERIAL_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_PUNCH_ITEM_NOT_FOUND,
    ERR_ROUND_NOT_FOUND,
    ERR_WINDOW_NOT_FOUND,
    ERR_ZONE_NOT_FOUND,
    FABRICATION,
    NON_EXISTENT_UUID,
    OMIT,
    OPERATIONS,
    PM,
    USER_CURATOR,
    DrawingDecision,
    OccupancyState,
    PackageStage,
    Phase,
    PlacementStatus,
    RoundStatus,
    SecurityTier,
    Severity,
    VoteDecision,
    assert_envelope,
    assert_zone_slots,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


NOT_FOUND_READS = [
    ("get_project", ERR_PROJECT_NOT_FOUND),
    ("get_design_package", ERR_PACKAGE_NOT_FOUND),
    ("get_review_round", ERR_ROUND_NOT_FOUND),
    ("get_gallery_zone", ERR_ZONE_NOT_FOUND),
    ("get_artifact_case", ERR_CASE_NOT_FOUND),
    ("get_artifact", ERR_ARTIFACT_NOT_FOUND),
    ("get_interactive", ERR_INTERACTIVE_NOT_FOUND),
    ("get_material_spec", ERR_MATERIAL_NOT_FOUND),
    ("get_shop_drawing", ERR_DRAWING_NOT_FOUND),
    ("get_install_window", ERR_WINDOW_NOT_FOUND),
    ("get_punch_item", ERR_PUNCH_ITEM_NOT_FOUND),
]


@pytest.mark.parametrize(
    "reader,expected_error",
    NOT_FOUND_READS,
    ids=[error for _, error in NOT_FOUND_READS],
)
def test_each_unknown_identifier_answers_its_own_not_found(api, reader, expected_error):
    """Each of the eleven addressable resources answers with the not-found code the
    PRD assigns to that resource alone, and each answers HTTP 404.

    "An unknown project identifier yields `ERR_PROJECT_NOT_FOUND`; an unknown design package yields `ERR_PACKAGE_NOT_FOUND`; an unknown review round yields `ERR_ROUND_NOT_FOUND`; an unknown gallery zone yields `ERR_ZONE_NOT_FOUND`; an unknown artifact case yields `ERR_CASE_NOT_FOUND`; an unknown collection object yields `ERR_ARTIFACT_NOT_FOUND`; an unknown interactive yields `ERR_INTERACTIVE_NOT_FOUND`; an unknown material specification yields `ERR_MATERIAL_NOT_FOUND`; an unknown shop drawing yields `ERR_DRAWING_NOT_FOUND`; an unknown install window yields `ERR_WINDOW_NOT_FOUND`; and an unknown punch item yields `ERR_PUNCH_ITEM_NOT_FOUND`."
    "All eleven are HTTP 404."

    Design: Corner/entities/every_path_id_and_body_foreign_key_with_an_unknown_uuid_returns_its_own_not_found
    """
    fixtures.set_clock(api)

    response = getattr(api, reader)(NON_EXISTENT_UUID, PM)

    validate_error(response, expected_error, 404)


def test_body_supplied_zone_and_object_identifiers_answer_their_own_not_found(api):
    """An identifier that names nothing is reported with its own 404 whether it
    arrives in the path or in the body, and the reported existence failure comes
    before the case-version token is even considered, so nothing is written.

    "The same rule applies to identifiers supplied in a request body rather than in the path: a body-supplied `project_id`, `zone_id`, `subject_case_id`, `subject_interactive_id`, `material_spec_id`, `artifact_id`, `interactive_id` or `case_id` that names nothing produces the corresponding 404."
    "5. Existence of every referenced row, path-supplied and body-supplied alike, in the order the eleven 404s are listed in §2.5."

    Design: Corner/entities/every_path_id_and_body_foreign_key_with_an_unknown_uuid_returns_its_own_not_found
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project["id"])
    case = fixtures.create_case(api, project["id"], zone["id"])

    validate_error(
        api.create_artifact_case(
            project["id"],
            factories.artifact_case_payload(NON_EXISTENT_UUID, case_code="C-02"),
            PM,
        ),
        ERR_ZONE_NOT_FOUND,
        404,
    )

    validate_error(
        api.create_placement(
            case["id"], factories.placement_payload(NON_EXISTENT_UUID, 1), CURATOR
        ),
        ERR_ARTIFACT_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(api.list_zone_artifact_cases(zone["id"], PM))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [case["id"]]
    assert rows[0]["placed_artifact_count"] == 0
    assert rows[0]["version"] == 1


def test_absent_and_null_required_fields_are_rejected_and_create_nothing(api):
    """A create whose body omits a required field, or sends it as null, is refused
    as malformed and leaves the collection empty.

    "4. Request-body shape: parseable JSON object, every required field present and non-null, every enum-typed field carrying a declared value, every number within its declared domain, every datetime a valid ISO 8601 UTC instant (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/each_missing_required_field_is_rejected_with_invalid_request_before_existence
    """
    fixtures.set_clock(api)

    validate_error(
        api.create_project(factories.project_payload(contract_value_cents=OMIT), PM),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_project(factories.project_payload(name=None), PM),
        ERR_INVALID_REQUEST,
        400,
    )
    _, meta = validate_paginated(api.list_projects(PM))
    assert meta["total_count"] == 0

    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)

    validate_error(
        api.create_artifact(
            project["id"], factories.artifact_payload(security_class=OMIT), CURATOR
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    _, artifact_meta = validate_paginated(api.list_artifacts(project["id"], PM))
    assert artifact_meta["total_count"] == 0


def test_a_malformed_body_is_reported_before_existence_and_before_the_version_token(api):
    """A body missing a required field is refused as malformed even when the same
    request also names a row that does not exist and even when the missing field
    is the concurrency token itself, because shape is checked above both.

    "Creating a design package under a project requires `expected_project_version` in the request body. It is not optional."
    "5. Existence of every referenced row, path-supplied and body-supplied alike, in the order the eleven 404s are listed in §2.5."
    "7. Optimistic-concurrency version match — the project version first, then the case version (`ERR_STALE_PROJECT_VERSION`, `ERR_STALE_CASE_VERSION`)."
    "Both approving branches require `actual_shop_hours` and `actual_waste_factor` in the body — the shop's real figures — and their absence is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/each_missing_required_field_is_rejected_with_invalid_request_before_existence
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)

    validate_error(
        api.create_design_package(
            project["id"],
            factories.design_package_payload(
                OMIT, stage=PackageStage.SCHEMATIC
            ),
            PM,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.drawing_decision(
            NON_EXISTENT_UUID,
            factories.drawing_decision_payload(
                DrawingDecision.APPROVE,
                actual_shop_hours=OMIT,
                actual_waste_factor=OMIT,
            ),
            PM,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.create_review_round(
            NON_EXISTENT_UUID,
            factories.review_round_payload(decision_deadline_at=OMIT),
            PM,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api.list_design_packages(project["id"], PM))
    assert meta["total_count"] == 0


def test_undeclared_enums_and_out_of_domain_numbers_are_rejected_at_the_boundary(api):
    """An enum value outside the declared domain, a humidity ceiling that is not
    strictly above its floor, and each numeric field pushed one step past its
    declared bound are all refused as malformed, while a zone sitting exactly on
    the inclusive ceilings of those same domains is accepted.

    "Each carries an `accession_number` of 1 to 40 characters unique among the project's objects, a `material_class` of `ORGANIC`, `METAL`, `PAPER`, `TEXTILE` or `COMPOSITE` naming the dominant material that drives its conservation limits, and the conservation envelope the object itself demands: `required_rh_min_pct` and `required_rh_max_pct`, both strictly between 0 and 100 with the maximum strictly greater than the minimum, and `max_lux`, the highest illuminance it tolerates, which may be 0 or more."
    "`max_noise_dba` records the loudest work the museum will tolerate in that zone and must be greater than zero."
    "`case_slot_capacity` declares how many artifact cases the floor plan can carry and must be between 1 and 20 inclusive; it is the conserved slot pool."
    "Three flags are optional: `is_public_operating`, true by default, records whether the zone stays open to visitors during the install period; `closure_allowed`, false by default, records whether the museum will permit closing the zone to visitors for work at all; and `dust_settling_buffer_minutes`, 120 by default and constrained to between 0 and 480 inclusive, is the zone's own minimum settling period after dust-generating work."

    Design: Corner/entities/undeclared_enums_out_of_domain_numbers_and_the_exclusive_or_pairs_are_rejected
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    validate_error(
        api.create_artifact(
            project_id, factories.artifact_payload(material_class="STONE"), CURATOR
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_artifact(
            project_id,
            factories.artifact_payload(
                required_rh_min_pct=45.0, required_rh_max_pct=40.0
            ),
            CURATOR,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_artifact(
            project_id,
            factories.artifact_payload(
                required_rh_min_pct=45.0, required_rh_max_pct=45.0
            ),
            CURATOR,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    for overrides in (
        {"max_noise_dba": 0.0},
        {"case_slot_capacity": 21},
        {"visitor_route_order": 0},
        {"dust_settling_buffer_minutes": 481},
    ):
        validate_error(
            api.create_gallery_zone(
                project_id, factories.gallery_zone_payload(**overrides), OPERATIONS
            ),
            ERR_INVALID_REQUEST,
            400,
        )

    _, artifact_meta = validate_paginated(api.list_artifacts(project_id, PM))
    assert artifact_meta["total_count"] == 0
    _, zone_meta = validate_paginated(api.list_gallery_zones(project_id, PM))
    assert zone_meta["total_count"] == 0

    accepted = validate_success(
        api.create_gallery_zone(
            project_id,
            factories.gallery_zone_payload(
                case_slot_capacity=20, dust_settling_buffer_minutes=480
            ),
            OPERATIONS,
        ),
        201,
    )
    assert accepted["case_slot_capacity"] == 20
    assert accepted["dust_settling_buffer_minutes"] == 480
    assert accepted["occupancy_state"] == OccupancyState.OPERATING
    assert_zone_slots(accepted, reserved=0, available=20)


def test_the_exclusive_or_subject_pairs_are_refused_before_the_phase_is_read(api):
    """A shop drawing naming neither subject or both subjects, a punch item naming
    both subjects, and a window carrying an unparseable instant are all refused as
    malformed, even though the same requests are also issued in a phase that does
    not admit them at all, because request shape is read above project phase.

    "The payload names the owning commission with `project_id`, the primary material with `material_spec_id`, and exactly one subject: either a `subject_case_id` naming the case the sheet details or a `subject_interactive_id` naming the interactive it details."
    "Supplying both, or neither, is `ERR_INVALID_REQUEST`."
    "The item may point at one subject — either an `interactive_id` or a `case_id`, both of which must belong to the same project — but naming both at once is `ERR_INVALID_REQUEST`, and naming neither is a general project-level defect."
    "4. Request-body shape: parseable JSON object, every required field present and non-null, every enum-typed field carrying a declared value, every number within its declared domain, every datetime a valid ISO 8601 UTC instant (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/undeclared_enums_out_of_domain_numbers_and_the_exclusive_or_pairs_are_rejected
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])
    interactive = fixtures.create_interactive(api, project_id)
    material = fixtures.create_material(api, project_id)

    validate_error(
        api.create_shop_drawing(
            factories.shop_drawing_payload(project_id, material["id"]), FABRICATION
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_shop_drawing(
            factories.shop_drawing_payload(
                project_id,
                material["id"],
                subject_case_id=case["id"],
                subject_interactive_id=interactive["id"],
            ),
            FABRICATION,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.create_punch_item(
            project_id,
            factories.punch_item_payload(
                severity=Severity.MAJOR,
                interactive_id=interactive["id"],
                case_id=case["id"],
            ),
            OPERATIONS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.create_install_window(
            factories.install_window_payload(
                project_id, zone["id"], starts_at="not-a-timestamp"
            ),
            FABRICATION,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    _, drawing_meta = validate_paginated(api.list_project_shop_drawings(project_id, PM))
    assert drawing_meta["total_count"] == 0
    _, punch_meta = validate_paginated(api.list_project_punch_items(project_id, PM))
    assert punch_meta["total_count"] == 0
    _, window_meta = validate_paginated(
        api.list_project_install_windows(project_id, PM)
    )
    assert window_meta["total_count"] == 0


def test_a_cast_vote_row_carries_no_version_and_no_updated_timestamp(api):
    """A cast vote is recorded as an unversioned, never-edited row: it carries an
    identifier and a creation instant but neither an update instant nor a version,
    the reply to the caller is the updated round rather than the vote, and an
    omitted comment is stored as null.

    "A vote row carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a cast vote is never edited, never withdrawn and never re-tallied."
    "Each panelist casts exactly one vote, recording their `decision` as `APPROVE`, `REVISE` or `VETO` and optionally attaching a `comment` of up to 500 characters, which is stored as null when omitted."
    "The vote row is immutable: it captures the `round_id` it belongs to, the caller's `voter_role` and the caller's `voter_user_id`, and it is never edited."
    "The response to a vote is the **updated round**, not the vote row, so the caller sees the new tally and the round's resolved status in the same reply; the individual votes are readable through the round's own vote list, oldest first."

    Design: Corner/entities/review_vote_rows_are_immutable_with_no_version_and_no_update_or_delete_endpoint
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    package = fixtures.create_package(api, project["id"], stage=PackageStage.SCHEMATIC)
    review_round = fixtures.open_round(
        api,
        package["id"],
        panel_roles=["Curator", "Conservator", "FabricationLead"],
        decision_deadline_at=fixtures.FAR_DEADLINE,
    )

    updated_round = validate_success(
        api.cast_vote(
            review_round["id"],
            factories.vote_payload(
                VoteDecision.APPROVE, comment="Interpretive plan reads well"
            ),
            CURATOR,
        ),
        201,
    )
    assert updated_round["id"] == review_round["id"]
    assert updated_round["cast_vote_count"] == 1
    assert updated_round["approve_count"] == 1
    assert updated_round["revise_count"] == 0
    assert updated_round["veto_count"] == 0
    assert updated_round["status"] == RoundStatus.OPEN

    votes, meta = validate_paginated(api.list_votes(review_round["id"], PM))
    assert meta["total_count"] == 1
    vote = votes[0]
    assert is_valid_uuid(vote["id"])
    assert is_iso8601_timestamp(vote["created_at"])
    assert "updated_at" not in vote
    assert "version" not in vote
    assert vote["round_id"] == review_round["id"]
    assert vote["voter_role"] == "Curator"
    assert vote["voter_user_id"] == USER_CURATOR
    assert vote["decision"] == VoteDecision.APPROVE
    assert vote["comment"] == "Interpretive plan reads well"

    resolved = validate_success(
        api.cast_vote(
            review_round["id"], factories.vote_payload(VoteDecision.APPROVE), CONSERVATOR
        ),
        201,
    )
    assert resolved["cast_vote_count"] == 2
    assert resolved["approve_count"] == 2
    assert resolved["status"] == RoundStatus.APPROVED

    votes, meta = validate_paginated(api.list_votes(review_round["id"], PM))
    assert meta["total_count"] == 2
    assert [row["voter_role"] for row in votes] == ["Curator", "Conservator"]
    assert votes[1]["comment"] is None
    assert "version" not in votes[1]


def test_a_second_vote_from_the_same_panelist_is_refused_and_retallies_nothing(api):
    """A panelist who has already voted cannot vote again: the second ballot is
    refused as a duplicate and the round's tallies, status and version are exactly
    what the first ballot left, so no vote is ever revised.

    "the round must not already hold a vote from this caller — neither the same `voter_role` nor the same `voter_user_id` may appear twice, since one role votes once per round and no role may revise its position — or the vote is refused with `ERR_DUPLICATE_VOTE`"
    "A vote row carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a cast vote is never edited, never withdrawn and never re-tallied."

    Design: Corner/entities/review_vote_rows_are_immutable_with_no_version_and_no_update_or_delete_endpoint
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    package = fixtures.create_package(api, project["id"], stage=PackageStage.SCHEMATIC)
    review_round = fixtures.open_round(
        api,
        package["id"],
        panel_roles=["Curator", "Conservator", "FabricationLead"],
        decision_deadline_at=fixtures.FAR_DEADLINE,
    )
    fixtures.cast_vote(api, review_round["id"], CURATOR, VoteDecision.APPROVE)
    before = validate_success(api.get_review_round(review_round["id"], PM))

    validate_error(
        api.cast_vote(
            review_round["id"], factories.vote_payload(VoteDecision.REVISE), CURATOR
        ),
        ERR_DUPLICATE_VOTE,
        409,
    )

    after = validate_success(api.get_review_round(review_round["id"], PM))
    assert after["cast_vote_count"] == 1
    assert after["approve_count"] == 1
    assert after["revise_count"] == 0
    assert after["status"] == RoundStatus.OPEN
    assert after["version"] == before["version"]

    votes, meta = validate_paginated(api.list_votes(review_round["id"], PM))
    assert meta["total_count"] == 1
    assert votes[0]["decision"] == VoteDecision.APPROVE


def test_a_reference_to_a_row_filed_under_another_commission_is_refused(api):
    """A zone, a placed object and a placement removal that each name a row which
    exists but belongs to a different commission are refused as misfiled rather
    than as missing, and the refusal outranks the membership complaint the removal
    would otherwise raise.

    "The system treats every cross-entity reference resolved inside one request as required to belong to the same project as the primary resource, and a mismatch is reported as `ERR_CROSS_PROJECT_REFERENCE` (HTTP 409) — the row is not hidden from the caller, it is misfiled."
    "This is enforced when a case names a zone, when a window names a zone, when a drawing names its material specification and its subject case or subject interactive, when a placement or a placement removal names a collection object, and when a punch item names an interactive or a case."
    "6. Cross-project ownership of every resolved reference (`ERR_CROSS_PROJECT_REFERENCE`)."

    Design: Corner/entities/every_graph_edge_refuses_a_row_that_exists_but_belongs_to_another_project
    """
    fixtures.set_clock(api)
    first = fixtures.create_project(api, name="Hall of Rivers")
    fixtures.advance(api, first["id"], Phase.SCHEMATIC)
    first_zone = fixtures.create_zone(api, first["id"], zone_code="Z-A")
    first_case = fixtures.create_case(api, first["id"], first_zone["id"])

    second = fixtures.create_project(api, name="Hall of Canopies")
    fixtures.advance(api, second["id"], Phase.SCHEMATIC)
    fixtures.create_zone(api, second["id"], zone_code="Z-B")
    foreign_artifact = fixtures.create_artifact(
        api, second["id"], accession_number="2020.77.1", security_class=SecurityTier.BASIC
    )

    validate_error(
        api.create_artifact_case(
            second["id"],
            factories.artifact_case_payload(first_zone["id"], case_code="C-B1"),
            PM,
        ),
        ERR_CROSS_PROJECT_REFERENCE,
        409,
    )

    validate_error(
        api.create_placement(
            first_case["id"],
            factories.placement_payload(foreign_artifact["id"], 1),
            CURATOR,
        ),
        ERR_CROSS_PROJECT_REFERENCE,
        409,
    )

    validate_error(
        api.delete_placement(first_case["id"], foreign_artifact["id"], CURATOR),
        ERR_CROSS_PROJECT_REFERENCE,
        409,
    )

    unchanged_case = validate_success(api.get_artifact_case(first_case["id"], PM))
    assert unchanged_case["placed_artifact_count"] == 0
    assert unchanged_case["version"] == 1
    untouched_artifact = validate_success(api.get_artifact(foreign_artifact["id"], PM))
    assert untouched_artifact["placement_status"] == PlacementStatus.UNPLACED
    assert untouched_artifact["assigned_case_id"] is None
    _, meta = validate_paginated(api.list_artifact_cases(second["id"], PM))
    assert meta["total_count"] == 0


def test_a_placement_inside_one_commission_succeeds_and_lists_stay_parent_scoped(api):
    """The same placement that is refused across commissions succeeds when the
    object and the case share one commission, and each commission's nested lists
    report only its own rows.

    "A successful placement sets the object's `assigned_case_id` to the case, moves its `placement_status` `UNPLACED → RESERVED`, increments the case's `placed_artifact_count`, and rewrites `required_rh_min_pct`, `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the new set."
    "A referenced row that *exists* but belongs to a different commission is a different failure."

    Design: Corner/entities/every_graph_edge_refuses_a_row_that_exists_but_belongs_to_another_project
    """
    fixtures.set_clock(api)
    first = fixtures.create_project(api, name="Hall of Rivers")
    fixtures.advance(api, first["id"], Phase.SCHEMATIC)
    first_zone = fixtures.create_zone(api, first["id"], zone_code="Z-A")
    first_case = fixtures.create_case(api, first["id"], first_zone["id"])
    own_artifact = fixtures.create_artifact(api, first["id"])

    second = fixtures.create_project(api, name="Hall of Canopies")
    fixtures.advance(api, second["id"], Phase.SCHEMATIC)
    second_zone = fixtures.create_zone(api, second["id"], zone_code="Z-B")
    foreign_artifact = fixtures.create_artifact(
        api, second["id"], accession_number="2020.77.1"
    )

    placed = validate_success(
        api.create_placement(
            first_case["id"], factories.placement_payload(own_artifact["id"], 1), CURATOR
        ),
        201,
    )
    assert placed["id"] == own_artifact["id"]
    assert placed["placement_status"] == PlacementStatus.RESERVED
    assert placed["assigned_case_id"] == first_case["id"]
    assert placed["version"] == 2

    loaded_case = validate_success(api.get_artifact_case(first_case["id"], PM))
    assert_envelope(
        loaded_case,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )

    second_artifacts, second_meta = validate_paginated(
        api.list_artifacts(second["id"], PM)
    )
    assert second_meta["total_count"] == 1
    assert [row["id"] for row in second_artifacts] == [foreign_artifact["id"]]
    assert second_artifacts[0]["placement_status"] == PlacementStatus.UNPLACED

    second_zones, second_zone_meta = validate_paginated(
        api.list_gallery_zones(second["id"], PM)
    )
    assert second_zone_meta["total_count"] == 1
    assert [row["id"] for row in second_zones] == [second_zone["id"]]

    first_zones, first_zone_meta = validate_paginated(
        api.list_gallery_zones(first["id"], PM)
    )
    assert first_zone_meta["total_count"] == 1
    assert [row["id"] for row in first_zones] == [first_zone["id"]]
