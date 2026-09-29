"""Authentication, role authorisation, ownership and request-shape rejection."""
import pytest

from test_helpers import (
    ApiErrorId, NO_AUTH_HEADERS, PROGRAM_ADMIN, UTILIZATION_ANALYST,
    create_care_manager, create_member, create_program_payload,
    create_referral_payload, create_touch_payload, enrollment_version,
    identify_social_need, make_care_manager_headers,
    make_clinical_reviewer_headers, make_community_partner_headers,
    read_referral, read_touch, register_resource, send_referral,
    setup_active_care_plan, setup_draft_care_plan, setup_referral_scenario,
    submit_plan, validate_error, validate_paginated, validate_success,
)

UNKNOWN_IDS = {
    "program": "8a3e1c0b-2f4d-4a91-9c8b-000000000001",
    "care_manager": "8a3e1c0b-2f4d-4a91-9c8b-000000000002",
    "enrollment": "8a3e1c0b-2f4d-4a91-9c8b-000000000003",
    "care_plan": "8a3e1c0b-2f4d-4a91-9c8b-000000000004",
    "goal": "8a3e1c0b-2f4d-4a91-9c8b-000000000005",
    "touch": "8a3e1c0b-2f4d-4a91-9c8b-000000000006",
    "social_need": "8a3e1c0b-2f4d-4a91-9c8b-000000000007",
    "community_resource": "8a3e1c0b-2f4d-4a91-9c8b-000000000008",
    "referral": "8a3e1c0b-2f4d-4a91-9c8b-000000000009",
    "intervention": "8a3e1c0b-2f4d-4a91-9c8b-00000000000a",
}


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's
    role. If either header is absent, empty, or if `X-User-Role` holds a value
    that is not one of the five declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). Once the caller is identified, the service
    checks whether that role appears in the list of roles authorised for the
    requested endpoint; if it does not, the answer is `ERR_FORBIDDEN_ROLE` (HTTP
    403). Authentication always precedes authorisation, and both precede any
    inspection of the request body."

    Design: Corner/validations/request_without_role_header_returns_unauthenticated
    """
    member = create_member(external_member_id="MBR-6101", full_name="Auth Amy",
                           birth_date="1970-01-01")

    response = api.get_member(member["id"], NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401


def test_limit_below_the_declared_range_is_rejected(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; a supplied `limit`
    must be an integer no smaller than 1 and no larger than 100. When `offset` is
    omitted it defaults to 0; a supplied `offset` must be an integer no smaller
    than 0. A `limit` outside the range 1 through 100, or a negative `offset`, or
    a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    Design: Corner/validations/list_with_limit_zero_returns_invalid_pagination
    """
    create_member(external_member_id="MBR-6201", full_name="Page Pat",
                  birth_date="1970-01-01")

    response = api.list_members(UTILIZATION_ANALYST, params={"limit": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value)
    assert response.status_code == 400


def test_not_found_error_names_the_failing_path_segment(api):
    """PRD §2.6: "**Path resolution** — every identifier embedded in the request
    path is resolved from left to right, and the first segment that resolves to
    nothing decides the error. The service reports the not-found code named for
    the failing segment: `ERR_MEMBER_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_CARE_MANAGER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_CARE_PLAN_NOT_FOUND`, `ERR_GOAL_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`,
    `ERR_TOUCH_NOT_FOUND`, `ERR_SOCIAL_NEED_NOT_FOUND`,
    `ERR_COMMUNITY_RESOURCE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND` or
    `ERR_TRANSITION_EVENT_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/not_found_sweep_across_path_scoped_resources
    """
    probes = [
        (api.get_program(UNKNOWN_IDS["program"], PROGRAM_ADMIN),
         ApiErrorId.ERR_PROGRAM_NOT_FOUND.value),
        (api.get_care_manager(UNKNOWN_IDS["care_manager"], PROGRAM_ADMIN),
         ApiErrorId.ERR_CARE_MANAGER_NOT_FOUND.value),
        (api.get_enrollment(UNKNOWN_IDS["enrollment"], PROGRAM_ADMIN),
         ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value),
        (api.get_care_plan(UNKNOWN_IDS["care_plan"], PROGRAM_ADMIN),
         ApiErrorId.ERR_CARE_PLAN_NOT_FOUND.value),
        (api.get_goal(UNKNOWN_IDS["goal"], PROGRAM_ADMIN),
         ApiErrorId.ERR_GOAL_NOT_FOUND.value),
        (api.get_touch(UNKNOWN_IDS["touch"], PROGRAM_ADMIN),
         ApiErrorId.ERR_TOUCH_NOT_FOUND.value),
        (api.get_social_need(UNKNOWN_IDS["social_need"], PROGRAM_ADMIN),
         ApiErrorId.ERR_SOCIAL_NEED_NOT_FOUND.value),
        (api.get_community_resource(UNKNOWN_IDS["community_resource"],
                                    PROGRAM_ADMIN),
         ApiErrorId.ERR_COMMUNITY_RESOURCE_NOT_FOUND.value),
        (api.get_referral(UNKNOWN_IDS["referral"], PROGRAM_ADMIN),
         ApiErrorId.ERR_REFERRAL_NOT_FOUND.value),
        (api.complete_intervention(
            UNKNOWN_IDS["intervention"],
            make_care_manager_headers("8a3e1c0b-2f4d-4a91-9c8b-00000000000b")),
         ApiErrorId.ERR_INTERVENTION_NOT_FOUND.value),
    ]
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id)
        assert response.status_code == 404, (
            f"Expected HTTP 404 for {expected_error_id}, got {response.status_code}"
        )


def test_care_manager_may_not_take_a_review_decision(api):
    """PRD §2.1: "Once the caller is identified, the service checks whether that
    role appears in the list of roles authorised for the requested endpoint; if it
    does not, the answer is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.5: "Review is the exclusive act of a `ClinicalReviewer`, who supplies a
    `decision` of either `APPROVE` or `REQUEST_REVISION` and, on the revision
    branch, a `revision_note`."

    Design: Corner/rbac/care_manager_cannot_review_own_or_any_care_plan
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "RBAC Program"},
        member_overrides={"external_member_id": "MBR-9101", "full_name": "Rb Ac",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "RBAC goal"}],
        plan_title="RBAC plan",
    )
    plan_id = scenario["plan"]["id"]
    submit_plan(plan_id, scenario["care_manager"]["id"])

    response = api.review_care_plan(
        plan_id, {"decision": "APPROVE"},
        make_care_manager_headers(scenario["reviewer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    from test_helpers import read_care_plan
    assert read_care_plan(plan_id)["status"] == "PENDING_REVIEW"


def test_reviewer_who_authored_the_plan_is_refused(api):
    """PRD §3.5: "The reviewer's `X-User-ID` must differ from
    `authored_by_care_manager_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.1: "That shared backing is precisely what makes the segregation-of-duties
    rule meaningful — a reviewer whose `X-User-ID` equals the plan's
    `authored_by_care_manager_id` is refusing to review their own work, and the
    service rejects the attempt with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/reviewer_who_authored_the_plan_is_rejected_for_segregation_of_duties
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "SoD Program"},
        member_overrides={"external_member_id": "MBR-9201", "full_name": "Sod Sam",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "SoD goal"}],
        plan_title="SoD plan",
    )
    plan_id = scenario["plan"]["id"]
    author_id = scenario["care_manager"]["id"]
    other_id = scenario["reviewer"]["id"]
    submit_plan(plan_id, author_id)

    self_review = api.review_care_plan(
        plan_id, {"decision": "APPROVE"}, make_clinical_reviewer_headers(author_id)
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert self_review.status_code == 403

    data = validate_success(
        api.review_care_plan(plan_id, {"decision": "APPROVE"},
                             make_clinical_reviewer_headers(other_id))
    )
    assert data["status"] == "ACTIVE"
    assert data["reviewed_by_care_manager_id"] == other_id


def test_care_manager_may_not_book_or_complete_another_managers_touch(api):
    """PRD §3.6: "Plan operations may book on anyone's calendar; a care manager may
    book only their own, so a `CareManager` whose `X-User-ID` differs from the
    `care_manager_id` in the body is refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.1: "Concretely, a care manager may complete or cancel only a touch whose
    `care_manager_id` equals their own `X-User-ID`, may schedule a touch only
    against their own `care_manager_id`, and may submit only a care plan whose
    `authored_by_care_manager_id` equals their own `X-User-ID`. A violation of any
    of these is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity; the server does not
    compare it to any entity's `id`, and no ownership check applies to a
    `ProgramAdmin`."

    Design: Corner/rbac/care_manager_cannot_book_or_complete_another_managers_touch
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Owner Program"},
        member_overrides={"external_member_id": "MBR-9301", "full_name": "Own Ola",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Owner goal"}],
        plan_title="Owner plan",
    )
    acting_id = scenario["care_manager"]["id"]
    other_id = scenario["reviewer"]["id"]
    payload = create_touch_payload(
        scenario["enrollment"]["id"], other_id,
        scheduled_start_at="2026-08-12T09:00:00Z",
        scheduled_end_at="2026-08-12T09:30:00Z",
    )

    forbidden = api.create_touch(payload, make_care_manager_headers(acting_id))
    validate_error(forbidden, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert forbidden.status_code == 403

    booked = validate_success(api.create_touch(payload, PROGRAM_ADMIN), 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["care_manager_id"] == other_id

    wrong_completer = api.complete_touch(
        booked["id"], {"outcome": "NOT_REACHED"},
        make_care_manager_headers(acting_id),
    )
    validate_error(wrong_completer, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert wrong_completer.status_code == 403
    assert read_touch(booked["id"])["status"] == "SCHEDULED"


def test_community_partner_may_not_decide_another_resources_referral(api):
    """PRD §2.1: "When `X-User-Role` is `CommunityPartner`, `X-User-ID` is the `id`
    of the acting `CommunityResource`; ownership checks compare a referral's
    `community_resource_id` to `X-User-ID`, so a partner may accept, decline, or
    close the loop only on referrals actually addressed to it, and any other
    attempt yields `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.8: "`ACCEPT` moves the referral to `ACCEPTED` and stamps `decision_at`;
    the slot occupation is retained, because both `SENT` and `ACCEPTED` occupy, and
    `open_referral_count` is unchanged."

    Design: Corner/rbac/community_partner_cannot_decide_another_resources_referral
    """
    scenario = setup_referral_scenario(
        program_overrides={"name": "Partner Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        member_overrides={"external_member_id": "MBR-9401", "full_name": "Par Pia",
                          "birth_date": "1970-01-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Partner goal"}],
        resource_overrides={"name": "Resource A", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 5},
        need_overrides={"domain": "FOOD", "severity": "MODERATE"},
    )
    addressed = scenario["resource"]
    bystander = register_resource(name="Resource B", served_domains=["FOOD"],
                                  concurrent_slot_capacity=5)
    referral = send_referral(scenario["social_need"]["id"], addressed["id"],
                             scenario["care_manager"]["id"],
                             service_start_at="2026-08-10T09:00:00Z",
                             service_end_at="2026-08-10T11:00:00Z")

    response = api.decide_referral(
        referral["id"], {"decision": "ACCEPT"},
        make_community_partner_headers(bystander["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert response.status_code == 403

    unchanged = read_referral(referral["id"])
    assert unchanged["status"] == "SENT"
    assert unchanged.get("decision_at") is None

    from test_helpers import read_community_resource
    assert read_community_resource(bystander["id"])["open_referral_count"] == 0


def test_peer_role_exclusive_operations_are_denied_to_other_roles(api):
    """PRD §2.1: "A `ProgramAdmin` runs plan operations: they register members,
    configure programs, create care managers, register community organizations,
    reassign enrollments between care managers, and drive the logical clock."
    PRD §3.9: "The analytics function is the only role permitted to record an
    outcome measurement, and it does so against a single enrollment, naming a
    `method` of `PRE_POST` or `MATCHED_COHORT` and, as §2.8 requires, the
    `expected_enrollment_version` it last observed."

    Design: Corner/rbac/peer_role_exclusive_operations_are_denied_to_other_roles
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Peer Program"},
        member_overrides={"external_member_id": "MBR-9501", "full_name": "Pee Rex",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Peer goal"}],
        plan_title="Peer plan",
    )
    enrollment_id = scenario["enrollment"]["id"]

    analyst_program = api.create_program(
        create_program_payload(name="Analyst Program", staff_minute_budget=100),
        UTILIZATION_ANALYST,
    )
    validate_error(analyst_program, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert analyst_program.status_code == 403

    care_manager_measurement = api.create_roi_measurement(
        enrollment_id,
        {"method": "PRE_POST",
         "expected_enrollment_version": enrollment_version(enrollment_id)},
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(care_manager_measurement, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert care_manager_measurement.status_code == 403

    _, meta = validate_paginated(
        api.list_roi_measurements(enrollment_id, UTILIZATION_ANALYST)
    )
    assert meta["total_count"] == 0
