"""Unresolvable identifiers, in the path and in the body.

Both cases use one UUID that names no row of any entity, and both are about
vocabulary: the 404 names the entity that failed to resolve, and resolution
happens early enough that no state, shape or version rule ever gets a turn.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    PlanStatus,
    PostType,
    action,
    assert_error_envelope_meta,
    build_approved_assessment_world,
    build_plan_with_perimeter_post_world,
    create_verified_guard,
    post_assignment_payload,
    post_payload,
    read_event_version,
    staffing_plan_payload,
    subcontracted_guard_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_unresolvable_path_id_names_its_own_entity_in_the_404():
    """Twelve reads of the same absent UUID, twelve distinct error ids.

    The vocabulary is per entity rather than one generic not-found, and the last
    request shows that a path resource is resolved before the action in the body
    is dispatched — a decision on a review that does not exist is a 404, not the
    409 an out-of-order decision would earn. Every response still carries the
    error envelope.

    PRD: "**Path existence** — each identifier in the path is resolved left to right, and the first one that does not resolve produces its own 404: `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GUARD_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_READING_NOT_FOUND`."
    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    api = ApiClient()
    build_approved_assessment_world(api)

    attempts = [
        (api.get_venue(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ApiErrorId.VENUE_NOT_FOUND),
        (api.get_event(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ApiErrorId.EVENT_NOT_FOUND),
        (
            api.get_risk_assessment(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
            ApiErrorId.RISK_ASSESSMENT_NOT_FOUND,
        ),
        (api.get_staffing_plan(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ApiErrorId.PLAN_NOT_FOUND),
        (api.get_post(NON_EXISTENT_UUID, COORDINATOR_HEADERS), ApiErrorId.POST_NOT_FOUND),
        (
            api.get_post_assignment(NON_EXISTENT_UUID, COORDINATOR_HEADERS),
            ApiErrorId.ASSIGNMENT_NOT_FOUND,
        ),
        (api.get_guard(NON_EXISTENT_UUID, AUDITOR_HEADERS), ApiErrorId.GUARD_NOT_FOUND),
        (
            api.get_subcontractor(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ApiErrorId.SUBCONTRACTOR_NOT_FOUND,
        ),
        (api.get_screening_lane(NON_EXISTENT_UUID, COORDINATOR_HEADERS), ApiErrorId.LANE_NOT_FOUND),
        (
            api.get_density_reading(NON_EXISTENT_UUID, COORDINATOR_HEADERS),
            ApiErrorId.READING_NOT_FOUND,
        ),
        (api.get_incident(NON_EXISTENT_UUID, COMMANDER_HEADERS), ApiErrorId.INCIDENT_NOT_FOUND),
        (
            api.after_action_review_decision(
                NON_EXISTENT_UUID, action("SUBMIT"), COMMANDER_HEADERS
            ),
            ApiErrorId.REVIEW_NOT_FOUND,
        ),
    ]

    for response, expected_error_id in attempts:
        validate_error(response, expected_error_id)
        assert_error_envelope_meta(response)
        assert sorted(response.json()["data"]) == ["error_id", "message"]


def test_an_unresolvable_body_foreign_key_is_a_404_and_not_a_shape_complaint():
    """Seven well-formed bodies, each naming one row that is not there.

    Optional references are validated exactly as strictly as mandatory ones once
    supplied. The plan create is the interesting one: its `expected_event_version`
    is supplied and current, and the missing assessment answers first anyway,
    which is why the draft plan survives the request instead of being superseded
    by a replacement. Nothing was written.

    PRD: "**Body foreign keys** — `zone_id`, `guard_id`, `post_id`, `risk_assessment_id`, `subcontractor_id`, `lane_id` and `reports_to_post_id` each resolve to an existing row, else the matching 404 from `ERR_ZONE_NOT_FOUND`, `ERR_GUARD_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND` or `ERR_LANE_NOT_FOUND`."
    Design: Corner/errors/unknown_body_foreign_keys_return_not_found_not_invalid_request
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    guard_id = create_verified_guard(api, "GC-7001")

    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(NON_EXISTENT_UUID, "PX", PostType.FLOOR),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ZONE_NOT_FOUND,
    )
    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id, "PY", PostType.FLOOR, reports_to_post_id=NON_EXISTENT_UUID
            ),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.POST_NOT_FOUND,
    )
    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zi_id, "PZ", PostType.INGRESS_SCREENING, lane_id=NON_EXISTENT_UUID
            ),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.LANE_NOT_FOUND,
    )
    validate_error(
        api.create_post_assignment(
            post_assignment_payload(NON_EXISTENT_UUID, guard_id), COORDINATOR_HEADERS
        ),
        ApiErrorId.POST_NOT_FOUND,
    )
    validate_error(
        api.create_post_assignment(
            post_assignment_payload(world.p1_id, NON_EXISTENT_UUID), COORDINATOR_HEADERS
        ),
        ApiErrorId.GUARD_NOT_FOUND,
    )
    validate_error(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(NON_EXISTENT_UUID, read_event_version(api, world.event_id)),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.RISK_ASSESSMENT_NOT_FOUND,
    )
    validate_error(
        api.create_guard(
            subcontracted_guard_payload("GC-7099", NON_EXISTENT_UUID), COORDINATOR_HEADERS
        ),
        ApiErrorId.SUBCONTRACTOR_NOT_FOUND,
    )

    _, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert meta["total_count"] == 1
    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.DRAFT
    assert plan["is_current"] is True
