"""State transitions, paging/budget calculations, RBAC, and consistency
(breadth: state_machines, calculations, rbac, consistency_model sections).

Every test translates exactly one §1.9 corner instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_service,
    create_responder,
    create_schedule,
    create_shift,
    create_policy,
    create_tier,
    create_window,
    setup_pageable_service,
    setup_acknowledged_incident,
    setup_resolved_incident,
    setup_in_review_postmortem,
    setup_postmortem_with_action_item,
    trigger_incident,
    acknowledge,
    resolve,
    create_postmortem,
    create_action_item,
    TEST_USERS,
    make_responder_headers,
    WIDE_SHIFT_START,
    WIDE_SHIFT_END,
)
from test_helpers.factories import (
    create_war_room_payload,
    create_service_payload,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Corner/state_machines/acknowledge_already_resolved_incident_invalid_state
# ===========================================================================
def test_acknowledge_resolved_incident_invalid_state():
    """PRD §3.7: "It is permitted only while the incident's `lifecycle_status` is
    `TRIGGERED`; against any other lifecycle state it is rejected with
    `ERR_INCIDENT_NOT_TRIGGERED` (HTTP 409)."

    Design: Corner/state_machines/acknowledge_already_resolved_incident_invalid_state
    """
    env, incident = setup_resolved_incident(severity="SEV2")
    assert incident["lifecycle_status"] == "RESOLVED"
    res = api_client.acknowledge_incident(
        incident["id"], make_responder_headers(env["responder"]["id"])
    )
    validate_error(res, "ERR_INCIDENT_NOT_TRIGGERED")


# ===========================================================================
# Corner/state_machines/resolve_triggered_incident_skips_ack_invalid_state
# ===========================================================================
def test_resolve_triggered_incident_invalid_state():
    """PRD §3.7: "Resolution is performed by a `ResponderUser` or an
    `IncidentCommander` and is permitted only while the lifecycle is
    `ACKNOWLEDGED`; otherwise it is rejected with `ERR_INCIDENT_NOT_ACKNOWLEDGED`
    (HTTP 409)."

    Design: Corner/state_machines/resolve_triggered_incident_skips_ack_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["lifecycle_status"] == "TRIGGERED"
    res = api_client.resolve_incident(inc["id"], make_responder_headers(env["responder"]["id"]))
    validate_error(res, "ERR_INCIDENT_NOT_ACKNOWLEDGED")


# ===========================================================================
# Corner/state_machines/window_end_from_scheduled_invalid_state
# ===========================================================================
def test_end_scheduled_window_invalid_state():
    """PRD §3.8: "An `ACTIVE` window is ended only from `ACTIVE` status (else
    `ERR_WINDOW_NOT_ACTIVE`, HTTP 409), moving `status` to `ENDED`."

    Design: Corner/state_machines/window_end_from_scheduled_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    window = create_window(svc["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    assert window["status"] == "SCHEDULED"
    res = api_client.end_maintenance_window(window["id"], ADMIN)
    validate_error(res, "ERR_WINDOW_NOT_ACTIVE")


# ===========================================================================
# Corner/state_machines/war_room_close_requires_resolved_incident
# ===========================================================================
def test_war_room_close_requires_resolved_incident():
    """PRD §3.9: "A war room is closed by an `IncidentCommander`, permitted only
    while its `status` is `OPEN` (else `ERR_WAR_ROOM_NOT_OPEN`, HTTP 409) and only
    when the parent incident's `lifecycle_status` is `RESOLVED` (else
    `ERR_INCIDENT_NOT_RESOLVED`, HTTP 409)."

    Closing a war room whose parent incident is only ACKNOWLEDGED fails with
    ERR_INCIDENT_NOT_RESOLVED.

    Design: Corner/state_machines/war_room_close_requires_resolved_incident
    """
    env, incident = setup_acknowledged_incident(severity="SEV2")
    wr = validate_success(
        api_client.create_war_room(create_war_room_payload(incident["id"]), COMMANDER), 201
    )
    res = api_client.close_war_room(wr["id"], COMMANDER)
    validate_error(res, "ERR_INCIDENT_NOT_RESOLVED")


# ===========================================================================
# Corner/state_machines/action_item_complete_bubbles_up_open_count
# ===========================================================================
def test_action_item_complete_decrements_open_count():
    """PRD §3.10: "The owner completes an item, moving it from `IN_PROGRESS` to
    `DONE` ... completion decrements the parent's `open_action_item_count` by 1."

    Completing an IN_PROGRESS item moves it to DONE and decrements the parent
    postmortem's open_action_item_count from 1 to 0.

    Design: Corner/state_machines/action_item_complete_bubbles_up_open_count
    """
    env, incident, pm, ai = setup_postmortem_with_action_item(severity="SEV2")
    rid = env["responder"]["id"]
    validate_success(api_client.start_action_item(ai["id"], make_responder_headers(rid)), 200)
    done = validate_success(api_client.complete_action_item(ai["id"], make_responder_headers(rid)), 200)
    assert done["status"] == "DONE"

    pm_after = validate_success(api_client.get_postmortem(pm["id"], COMMANDER), 200)
    assert pm_after["open_action_item_count"] == 0, (
        f"complete should decrement open count to 0, got {pm_after['open_action_item_count']}"
    )


# ===========================================================================
# Corner/state_machines/postmortem_publish_happy_path_terminal
# ===========================================================================
def test_postmortem_publish_in_review_with_no_open_items():
    """PRD §3.10: "Also from `IN_REVIEW` the commander may publish it, moving it
    to the terminal `PUBLISHED` status; publication is permitted only while the
    status is `IN_REVIEW` ... and only when `open_action_item_count` is zero."

    An IN_REVIEW postmortem with zero open action items publishes to PUBLISHED.

    Design: Corner/state_machines/postmortem_publish_happy_path_terminal
    """
    env, incident, pm = setup_in_review_postmortem(severity="SEV2")
    assert pm["status"] == "IN_REVIEW"
    published = validate_success(api_client.publish_postmortem(pm["id"], COMMANDER), 200)
    assert published["status"] == "PUBLISHED", (
        f"publish should reach terminal PUBLISHED, got {published['status']}"
    )


# ===========================================================================
# Corner/calculations/paging_fanout_one_attempt_per_enabled_channel
# ===========================================================================
def test_paging_fanout_one_attempt_per_enabled_channel():
    """PRD §3.3: "the fan-out creates exactly one paging attempt per *enabled*
    channel of that responder, in a fixed channel-priority order: voice first when
    a `voice_number` is present, then SMS when an `sms_number` is present, then
    push when a `push_token` is present, and finally email, which is always
    present and always paged."

    A responder with voice+sms+email but no push_token produces exactly 3 page
    attempts (VOICE, SMS, EMAIL), all at tier_level 1 for that responder.

    Design: Corner/calculations/paging_fanout_one_attempt_per_enabled_channel
    """
    set_clock("2026-06-01T12:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = validate_success(api_client.create_responder(
        {"full_name": "R", "email": "rfanout@x.com", "sms_number": "+15551308", "voice_number": "+15551408"},
        ADMIN), 201)
    sch = create_schedule(svc["id"])
    create_shift(sch["id"], resp["id"], WIDE_SHIFT_START, WIDE_SHIFT_END)
    pol = create_policy(svc["id"])
    create_tier(pol["id"], sch["id"], tier_level=1, delay_minutes=0)
    inc = trigger_incident(svc["id"], pol["id"], severity="SEV2")

    data, meta = validate_paginated(api_client.list_incident_page_attempts(inc["id"], COMMANDER))
    assert meta["total_count"] == 3, (
        f"voice+sms+email (no push) should produce 3 page attempts, got {meta['total_count']}"
    )
    channels = {pa["channel"] for pa in data}
    assert "PUSH" not in channels, "no PUSH attempt should exist for a null push_token"
    for pa in data:
        assert pa["tier_level"] == 1
        assert pa["responder_id"] == resp["id"]


# ===========================================================================
# Corner/calculations/budget_status_warning_threshold_boundary
# ===========================================================================
def test_budget_status_warning_threshold_inclusive_boundary():
    """PRD §3.5: "Otherwise, if consumed is greater than or equal to the budget
    multiplied by 0.8 and rounded up to a whole minute, the status is `WARNING`."

    Budget 10; a SEV4 incident open exactly 8 minutes drives consumed=8 ==
    ceil(10*0.8)=8 -> WARNING (inclusive boundary).

    Design: Corner/calculations/budget_status_warning_threshold_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=10)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV4")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:08:00Z")  # exactly 8 minutes open (480s)
    resolve(inc["id"], env["responder"]["id"])

    svc = validate_success(api_client.get_service(env["service"]["id"], COMMANDER), 200)
    assert svc["error_budget_consumed_minutes"] == 8
    assert svc["budget_status"] == "WARNING", (
        f"consumed 8 == ceil(10*0.8) should be WARNING, got {svc['budget_status']}"
    )


# ===========================================================================
# Corner/calculations/escalation_target_selector_picks_covering_shift
# ===========================================================================
def test_escalation_target_selector_picks_covering_shift():
    """PRD §3.3: "The candidate set is every shift on that schedule whose
    half-open interval covers the current clock — that is, whose `starts_at` is at
    or before now and whose `ends_at` is strictly after now ... The selected
    target is the first candidate — the covering shift with the earliest start —
    and that shift's `responder_id` is the responder who will be paged."

    With a past shift (R1) and a current shift (R2 covering 12:00) on the tier's
    schedule, every page targets R2, never R1.

    Design: Corner/calculations/escalation_target_selector_picks_covering_shift
    """
    set_clock("2026-06-01T12:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    r1 = validate_success(api_client.create_responder(
        {"full_name": "R1", "email": "r1sel@x.com", "sms_number": "+15551510"}, ADMIN), 201)
    r2 = validate_success(api_client.create_responder(
        {"full_name": "R2", "email": "r2sel@x.com", "sms_number": "+15551511"}, ADMIN), 201)
    sch = create_schedule(svc["id"])
    create_shift(sch["id"], r1["id"], "2026-06-01T00:00:00Z", "2026-06-01T10:00:00Z")  # past
    create_shift(sch["id"], r2["id"], "2026-06-01T10:00:00Z", "2026-06-01T20:00:00Z")  # covers 12:00
    pol = create_policy(svc["id"])
    create_tier(pol["id"], sch["id"], tier_level=1, delay_minutes=0)
    inc = trigger_incident(svc["id"], pol["id"], severity="SEV2")

    data, _ = validate_paginated(api_client.list_incident_page_attempts(inc["id"], COMMANDER))
    assert len(data) >= 1
    for pa in data:
        assert pa["responder_id"] == r2["id"], (
            f"page target should be the covering shift's responder R2, got {pa['responder_id']}"
        )


# ===========================================================================
# Corner/rbac/responder_cannot_create_service_forbidden
# ===========================================================================
def test_responder_cannot_create_service_forbidden():
    """PRD §2.1: "A `PlatformAdmin` is an operational administrator who provisions
    the static configuration of the platform — services, responders, schedules,
    shifts, policies, tiers, and maintenance windows — and who drives the test
    clock."
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    A ResponderUser creating a service (provisioning, a PlatformAdmin role) is
    rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/responder_cannot_create_service_forbidden
    """
    resp = validate_success(api_client.create_responder(
        {"full_name": "R", "email": "rrbac@x.com", "sms_number": "+15551616"}, ADMIN), 201)
    res = api_client.create_service(
        create_service_payload(name="Sneaky", tier="TIER_2", error_budget_minutes=100),
        make_responder_headers(resp["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner/rbac/non_owner_responder_cannot_start_action_item
# ===========================================================================
def test_non_owner_responder_cannot_start_action_item():
    """PRD §3.10: "this is permitted only while the item's status is `OPEN` (else
    `ERR_ACTION_ITEM_NOT_OPEN`, HTTP 409) and only when the acting `ResponderUser`'s
    `X-User-ID` equals the item's `owner_responder_id` (else
    `ERR_NOT_ACTION_ITEM_OWNER`, HTTP 403)."

    A responder who is not the owner starting the action item is rejected with
    ERR_NOT_ACTION_ITEM_OWNER.

    Design: Corner/rbac/non_owner_responder_cannot_start_action_item
    """
    env, incident, pm, ai = setup_postmortem_with_action_item(severity="SEV2")
    # A different responder R2, not the owner.
    r2 = validate_success(api_client.create_responder(
        {"full_name": "R2", "email": "r2owner@x.com", "sms_number": "+15551717"}, ADMIN), 201)
    res = api_client.start_action_item(ai["id"], make_responder_headers(r2["id"]))
    validate_error(res, "ERR_NOT_ACTION_ITEM_OWNER")


# ===========================================================================
# Corner/rbac/acknowledge_by_unpaged_responder_forbidden
# ===========================================================================
def test_acknowledge_by_unpaged_responder_forbidden():
    """PRD §3.7: "the acting responder must actually have been paged for this
    incident: a paging attempt with `responder_id` equal to `X-User-ID` must
    exist, or the request is rejected with `ERR_RESPONDER_NOT_PAGED` (HTTP 403)."

    A TRIGGERED incident paged R1; an unpaged R2 acknowledging it is rejected with
    ERR_RESPONDER_NOT_PAGED.

    Design: Corner/rbac/acknowledge_by_unpaged_responder_forbidden
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    r2 = validate_success(api_client.create_responder(
        {"full_name": "R2", "email": "r2unpaged2@x.com", "sms_number": "+15551818"}, ADMIN), 201)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["lifecycle_status"] == "TRIGGERED"

    res = api_client.acknowledge_incident(inc["id"], make_responder_headers(r2["id"]))
    validate_error(res, "ERR_RESPONDER_NOT_PAGED")


# ===========================================================================
# Corner/rbac/missing_user_context_header_rejected
# ===========================================================================
def test_missing_user_context_header_rejected():
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. `X-User-ID` identifies the acting user, and
    `X-User-Role` declares the operational capacity under which they are acting.
    If either header is missing, or if `X-User-Role` does not name a role the
    system recognizes, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

    A POST /services with no auth headers is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    res = api_client.create_service(
        create_service_payload(name="NoAuth", tier="TIER_2", error_budget_minutes=100), {}
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT")


# ===========================================================================
# Corner/consistency_model/immediate_consistency_budget_visible_in_same_response
# ===========================================================================
def test_resolve_response_reflects_downtime_immediately():
    """PRD §3.7: "On success the lifecycle moves to `RESOLVED`, `resolved_at` is
    stamped from the clock, and `downtime_minutes` is computed as the
    open-to-resolve span rounded up to a whole minute (since
    `counts_against_budget` is true for a normally resolved incident)."

    The resolve response itself carries the freshly computed downtime_minutes
    (ceil(90/60)=2) and RESOLVED status — no read-after-write lag.

    Design: Corner/consistency_model/immediate_consistency_budget_visible_in_same_response
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV4")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:01:30Z")
    resolved = resolve(inc["id"], env["responder"]["id"])
    assert resolved["lifecycle_status"] == "RESOLVED"
    assert resolved["downtime_minutes"] == 2, (
        f"resolve response should reflect downtime_minutes immediately, got "
        f"{resolved['downtime_minutes']}"
    )
