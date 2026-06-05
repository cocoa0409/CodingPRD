"""Resource creation, field rules, request validation, listing, and uniqueness
errors (breadth: entities, validations, endpoints, errors sections).

Every test translates exactly one §1.9 corner instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_service,
    create_schedule,
    create_policy,
    create_tier,
    setup_pageable_service,
    setup_resolved_incident,
    trigger_incident,
    TEST_USERS,
    NON_EXISTENT_UUID,
)
from test_helpers.factories import (
    create_service_payload,
    create_schedule_shift_payload,
    create_escalation_tier_payload,
    create_incident_payload,
    create_war_room_payload,
    create_postmortem_payload,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Corner/entities/create_service_returns_201_with_initialized_budget
# ===========================================================================
def test_create_service_returns_201_with_initialized_budget():
    """PRD §3.1: "On creation, a service starts with `budget_status` of `HEALTHY`,
    `error_budget_consumed_minutes` of zero, and `error_budget_remaining_minutes`
    equal to the full `error_budget_minutes`."

    Design: Corner/entities/create_service_returns_201_with_initialized_budget
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api_client.create_service(
        create_service_payload(name="Checkout", tier="TIER_2", error_budget_minutes=500), ADMIN
    )
    svc = validate_success(res, 201)
    assert svc["budget_status"] == "HEALTHY"
    assert svc["error_budget_consumed_minutes"] == 0
    assert svc["error_budget_remaining_minutes"] == 500


# ===========================================================================
# Corner/entities/get_service_not_found_returns_404
# ===========================================================================
def test_get_service_not_found_returns_404():
    """PRD §2.7: "When any resource identifier in a path ... fails to resolve to
    an existing row, the request is rejected with the corresponding not-found
    error — `ERR_SERVICE_NOT_FOUND` ... (all HTTP 404), according to which entity
    failed to resolve."

    Design: Corner/entities/get_service_not_found_returns_404
    """
    res = api_client.get_service(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_SERVICE_NOT_FOUND")


# ===========================================================================
# Corner/entities/create_service_missing_required_budget_returns_invalid_request
# ===========================================================================
def test_create_service_missing_budget_returns_invalid_request():
    """PRD §3.1: "an `error_budget_minutes` allowance, which is the total downtime
    in minutes the service may accumulate over an evaluation window and which must
    be strictly greater than zero."
    PRD §2.8: "(4) required body fields must be present, well-typed, with valid
    enum members and in-range numerics, else `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_service_missing_required_budget_returns_invalid_request
    """
    res = api_client.create_service({"name": "NoBudget", "tier": "TIER_2"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner/entities/create_service_default_tier_applied
# ===========================================================================
def test_create_service_default_tier_is_tier2():
    """PRD §3.1: "an importance `tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`,
    defaulting to `TIER_2` when omitted."

    Design: Corner/entities/create_service_default_tier_applied
    """
    res = api_client.create_service({"name": "Defaulted", "error_budget_minutes": 100}, ADMIN)
    svc = validate_success(res, 201)
    assert svc["tier"] == "TIER_2", f"omitted tier should default to TIER_2, got {svc['tier']}"


# ===========================================================================
# Corner/entities/create_service_invalid_tier_enum_rejected
# ===========================================================================
def test_create_service_invalid_tier_enum_rejected():
    """PRD §3.1: "an importance `tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`."
    PRD §2.8: "(4) required body fields must be present, well-typed, with valid
    enum members and in-range numerics, else `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_service_invalid_tier_enum_rejected
    """
    res = api_client.create_service(
        {"name": "BadTier", "tier": "TIER_9", "error_budget_minutes": 100}, ADMIN
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner/entities/incident_system_fields_generated_input_ignored
# ===========================================================================
def test_incident_system_fields_server_stamped():
    """PRD §3.2: "At creation the incident enters its initial state of `TRIGGERED`
    on the lifecycle dimension and `PENDING` on the escalation dimension ... The
    server stamps `triggered_at` from the logical clock."
    PRD §3.2: "Otherwise the system fires the first page automatically:
    `escalation_status` advances to `ESCALATING`, `current_tier_level` advances to
    tier 1."

    The server stamps lifecycle_status TRIGGERED, escalation_status ESCALATING
    (after the auto first page), and triggered_at from the clock.

    Design: Corner/entities/incident_system_fields_generated_input_ignored
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["lifecycle_status"] == "TRIGGERED"
    assert inc["escalation_status"] == "ESCALATING"
    assert inc["triggered_at"] == "2026-06-01T12:00:00.000Z"


# ===========================================================================
# Corner/entities/pageattempt_immutable_no_version_field
# ===========================================================================
def test_page_attempt_append_only_no_version_field():
    """PRD §2.4: "a paging attempt and a war-room message each carry only `id` and
    `created_at` — they have no `updated_at` and no `version`, because once
    written they are never mutated."

    Design: Corner/entities/pageattempt_immutable_no_version_field
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    pages = validate_success(api_client.list_incident_page_attempts(inc["id"], COMMANDER), 200)
    assert len(pages) >= 1, "first page should have created at least one page attempt"
    pa = pages[0]
    assert "id" in pa and "created_at" in pa
    assert "version" not in pa, "page attempt must not expose version"
    assert "updated_at" not in pa, "page attempt must not expose updated_at"


# ===========================================================================
# Corner/validations/shift_invalid_interval_end_before_start
# ===========================================================================
def test_shift_end_before_start_returns_invalid_interval():
    """PRD §3.1: "The shift's `ends_at` must be strictly after its `starts_at`;
    otherwise the create is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/shift_invalid_interval_end_before_start
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = validate_success(api_client.create_responder(
        {"full_name": "R", "email": "rshift@x.com", "sms_number": "+15551212"}, ADMIN), 201)
    sch = create_schedule(svc["id"])
    res = api_client.create_schedule_shift(
        create_schedule_shift_payload(sch["id"], resp["id"], "2026-06-01T12:00:00Z", "2026-06-01T11:00:00Z"),
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_INTERVAL")


# ===========================================================================
# Corner/validations/duplicate_tier_level_within_policy_rejected
# ===========================================================================
def test_duplicate_tier_level_within_policy_rejected():
    """PRD §3.1: "a one-based ladder position `tier_level` that must be at least 1
    and must be unique within its policy (a duplicate is rejected with
    `ERR_DUPLICATE_TIER_LEVEL`)."

    Design: Corner/validations/duplicate_tier_level_within_policy_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    sch = create_schedule(svc["id"])
    pol = create_policy(svc["id"])
    create_tier(pol["id"], sch["id"], tier_level=1, delay_minutes=0)

    res = api_client.create_escalation_tier(
        create_escalation_tier_payload(pol["id"], sch["id"], 1, 5), ADMIN
    )
    validate_error(res, "ERR_DUPLICATE_TIER_LEVEL")


# ===========================================================================
# Corner/validations/existence_left_to_right_unknown_service_fk_on_incident
# ===========================================================================
def test_incident_unknown_service_fk_returns_service_not_found():
    """PRD §2.7: "any foreign key referenced in a request body, fails to resolve
    to an existing row, the request is rejected with the corresponding not-found
    error — `ERR_SERVICE_NOT_FOUND` ... (all HTTP 404), according to which entity
    failed to resolve."

    Design: Corner/validations/existence_left_to_right_unknown_service_fk_on_incident
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    pol = create_policy(svc["id"])
    res = api_client.create_incident(
        create_incident_payload(NON_EXISTENT_UUID, pol["id"], severity="SEV2"), COMMANDER
    )
    validate_error(res, "ERR_SERVICE_NOT_FOUND")


# ===========================================================================
# Corner/endpoints/list_services_pagination_envelope
# ===========================================================================
def test_list_services_pagination_has_more():
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return."

    With two services and limit=1, total_count is 2 and has_more is true.

    Design: Corner/endpoints/list_services_pagination_envelope
    """
    create_service(name="A", error_budget_minutes=100)
    create_service(name="B", error_budget_minutes=100)
    data, meta = validate_paginated(api_client.list_services(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner/endpoints/war_room_message_append_only_author_stamped
# ===========================================================================
def test_war_room_message_author_role_stamped():
    """PRD §3.9: "A `WarRoomMessage` carries the message `body`; at post time the
    server stamps the `author_role` from `X-User-Role` and, when present, the
    `author_id` from `X-User-ID`, and references the room through `war_room_id`."

    Posting a message as IncidentCommander returns 201 with author_role stamped
    to 'IncidentCommander'.

    Design: Corner/endpoints/war_room_message_append_only_author_stamped
    """
    env, incident = setup_resolved_incident(severity="SEV2")
    # War room can be opened on a resolved incident (open requires only the incident to exist).
    wr = validate_success(
        api_client.create_war_room(create_war_room_payload(incident["id"]), COMMANDER), 201
    )
    res = api_client.create_war_room_message(wr["id"], {"body": "ack received"}, COMMANDER)
    msg = validate_success(res, 201)
    assert msg["author_role"] == "IncidentCommander", (
        f"author_role should be stamped from X-User-Role, got {msg['author_role']}"
    )


# ===========================================================================
# Corner/errors/war_room_duplicate_per_incident_rejected
# ===========================================================================
def test_war_room_duplicate_per_incident_rejected():
    """PRD §3.9: "The relationship is one-to-one — at most one war room per
    incident — and a second attempt is rejected with `ERR_WAR_ROOM_EXISTS`
    (HTTP 409)."

    Design: Corner/errors/war_room_duplicate_per_incident_rejected
    """
    env, incident = setup_resolved_incident(severity="SEV2")
    validate_success(
        api_client.create_war_room(create_war_room_payload(incident["id"]), COMMANDER), 201
    )
    res = api_client.create_war_room(create_war_room_payload(incident["id"]), COMMANDER)
    validate_error(res, "ERR_WAR_ROOM_EXISTS")


# ===========================================================================
# Corner/errors/postmortem_duplicate_per_incident_rejected
# ===========================================================================
def test_postmortem_duplicate_per_incident_rejected():
    """PRD §3.10: "The relationship is one-to-one — at most one postmortem per
    incident — and a duplicate is rejected with `ERR_POSTMORTEM_EXISTS`
    (HTTP 409)."

    Design: Corner/errors/postmortem_duplicate_per_incident_rejected
    """
    env, incident = setup_resolved_incident(severity="SEV2")
    validate_success(
        api_client.create_postmortem(create_postmortem_payload(incident["id"], "first"), COMMANDER), 201
    )
    res = api_client.create_postmortem(create_postmortem_payload(incident["id"], "second"), COMMANDER)
    validate_error(res, "ERR_POSTMORTEM_EXISTS")
