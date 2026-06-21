"""Validation-priority conflicts, boundary precision, and cross-entity state
dependencies (depth: priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency).

Every test translates exactly one §1.8 difficulty instance. The validation-order
tests are grounded in PRD §2.8, which states the fixed priority order verbatim.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
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
    create_schedule_shift_payload,
    create_postmortem_payload,
    escalate_payload,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/
#   acknowledge_resolved_by_unpaged_state_beats_safety
# ===========================================================================
def test_ack_resolved_by_unpaged_returns_state_error_over_safety():
    """PRD §2.8: "(6) the target resource must be in the correct state for the
    requested transition, else the relevant state error (HTTP 409) ... (8)
    safety/ownership checks must pass (HTTP 403)."
    PRD §3.7: "It is permitted only while the incident's `lifecycle_status` is
    `TRIGGERED`; against any other lifecycle state it is rejected with
    `ERR_INCIDENT_NOT_TRIGGERED` (HTTP 409)."

    An acknowledge that fails BOTH the state check (incident is RESOLVED) and the
    paged-safety check (acting responder was never paged) returns the higher-
    priority ERR_INCIDENT_NOT_TRIGGERED (priority 6), not ERR_RESPONDER_NOT_PAGED
    (priority 8).

    Design: Difficulty/priority_pair_validation_conflict/acknowledge_resolved_by_unpaged_state_beats_safety
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    # R2 exists but is never on any shift / never paged.
    r2 = api_client.create_responder({"full_name": "R2", "email": "r2unpaged@x.com", "sms_number": "+15550108"}, ADMIN)
    r2 = validate_success(r2, 201)

    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    acknowledge(inc["id"], env["responder"]["id"])
    inc = resolve(inc["id"], env["responder"]["id"])
    assert inc["lifecycle_status"] == "RESOLVED"

    res = api_client.acknowledge_incident(inc["id"], make_responder_headers(r2["id"]))
    validate_error(res, "ERR_INCIDENT_NOT_TRIGGERED")


def test_ack_triggered_by_unpaged_returns_safety_error_when_state_ok():
    """PRD §3.7: "the acting responder must actually have been paged for this
    incident: a paging attempt with `responder_id` equal to `X-User-ID` must
    exist, or the request is rejected with `ERR_RESPONDER_NOT_PAGED` (HTTP 403)."

    Isolation complement: when the priority-6 state check passes (incident is
    still TRIGGERED) but only the priority-8 paged-safety check fails (R2 was
    never paged), the lower-priority ERR_RESPONDER_NOT_PAGED is what surfaces —
    confirming the safety check is genuinely reachable and is correctly preempted
    by the state error in the conflict scenario above.

    Design: Difficulty/priority_pair_validation_conflict/acknowledge_resolved_by_unpaged_state_beats_safety
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    r2 = validate_success(api_client.create_responder(
        {"full_name": "R2", "email": "r2safe@x.com", "sms_number": "+15550109"}, ADMIN), 201)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["lifecycle_status"] == "TRIGGERED"  # state precondition satisfied

    res = api_client.acknowledge_incident(inc["id"], make_responder_headers(r2["id"]))
    validate_error(res, "ERR_RESPONDER_NOT_PAGED")


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/
#   schedule_shift_invalid_request_beats_invalid_interval
# ===========================================================================
def test_shift_missing_field_returns_invalid_request_over_invalid_interval():
    """PRD §2.8: "(4) required body fields must be present, well-typed, with valid
    enum members and in-range numerics, else `ERR_INVALID_REQUEST` (HTTP 422); (5)
    interval fields must be well-formed, else `ERR_INVALID_INTERVAL` (HTTP 422)."

    A POST /schedule-shifts that BOTH omits the required responder_id (priority 4)
    AND has ends_at <= starts_at (priority 5) returns the higher-priority
    ERR_INVALID_REQUEST, not ERR_INVALID_INTERVAL.

    Design: Difficulty/priority_pair_validation_conflict/schedule_shift_invalid_request_beats_invalid_interval
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    sch = create_schedule(svc["id"])
    # Missing responder_id AND ends_at before starts_at.
    payload = {
        "schedule_id": sch["id"],
        "starts_at": "2026-06-01T12:00:00Z",
        "ends_at": "2026-06-01T11:00:00Z",
    }
    res = api_client.create_schedule_shift(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_shift_bad_interval_alone_returns_invalid_interval():
    """PRD §3.1: "The shift's `ends_at` must be strictly after its `starts_at`;
    otherwise the create is rejected with `ERR_INVALID_INTERVAL`."

    Isolation complement: when the priority-4 request-shape check passes (all
    required fields present and well-typed) but only the priority-5 interval check
    fails (ends_at <= starts_at), the lower-priority ERR_INVALID_INTERVAL surfaces
    — confirming the interval check is genuinely reachable and is correctly
    preempted by the request-shape error in the conflict scenario above.

    Design: Difficulty/priority_pair_validation_conflict/schedule_shift_invalid_request_beats_invalid_interval
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = create_responder()
    sch = create_schedule(svc["id"])
    payload = create_schedule_shift_payload(
        sch["id"], resp["id"], "2026-06-01T12:00:00Z", "2026-06-01T11:00:00Z"
    )
    res = api_client.create_schedule_shift(payload, ADMIN)
    validate_error(res, "ERR_INVALID_INTERVAL")


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/
#   publish_postmortem_safety_beats_state_when_both_off
# ===========================================================================
def test_publish_draft_with_open_item_returns_state_error_over_safety():
    """PRD §2.8: "(6) the target resource must be in the correct state for the
    requested transition, else the relevant state error (HTTP 409) ... (8)
    safety/ownership checks must pass (HTTP 403); and (9) and beyond, the
    domain-specific business constraints described in Section 3."
    PRD §3.10: "publication is permitted only while the status is `IN_REVIEW`
    (else `ERR_POSTMORTEM_NOT_IN_REVIEW`) and only when `open_action_item_count`
    is zero ... else the publish is rejected with `ERR_OPEN_ACTION_ITEMS`."

    Publishing a DRAFT postmortem that also has an open action item fails the
    earlier state check (ERR_POSTMORTEM_NOT_IN_REVIEW) before the open-items
    business check (ERR_OPEN_ACTION_ITEMS).

    Design: Difficulty/priority_pair_validation_conflict/publish_postmortem_safety_beats_state_when_both_off
    """
    env, incident, pm, ai = setup_postmortem_with_action_item(severity="SEV2")
    pm_now = validate_success(api_client.get_postmortem(pm["id"], COMMANDER), 200)
    assert pm_now["status"] == "DRAFT"
    assert pm_now["open_action_item_count"] == 1

    res = api_client.publish_postmortem(pm["id"], COMMANDER)
    validate_error(res, "ERR_POSTMORTEM_NOT_IN_REVIEW")


def test_publish_in_review_with_open_item_returns_open_action_items():
    """PRD §3.10: "publication is permitted only while the status is `IN_REVIEW`
    (else `ERR_POSTMORTEM_NOT_IN_REVIEW`) and only when `open_action_item_count`
    is zero — that is, every child action item is `DONE` or `CANCELLED` — else the
    publish is rejected with `ERR_OPEN_ACTION_ITEMS` (HTTP 409)."

    Isolation complement: when the priority-6 state check passes (postmortem is
    IN_REVIEW) but only the open-items business check fails (one OPEN action
    item), the lower-priority ERR_OPEN_ACTION_ITEMS surfaces — confirming that
    check is genuinely reachable and is correctly preempted by the state error in
    the conflict scenario above.

    Design: Difficulty/priority_pair_validation_conflict/publish_postmortem_safety_beats_state_when_both_off
    """
    env, incident, pm = setup_in_review_postmortem(severity="SEV2")
    # Add an OPEN action item while the postmortem is IN_REVIEW.
    create_action_item(pm["id"], env["responder"]["id"])
    pm_now = validate_success(api_client.get_postmortem(pm["id"], COMMANDER), 200)
    assert pm_now["status"] == "IN_REVIEW"  # state precondition satisfied
    assert pm_now["open_action_item_count"] == 1

    res = api_client.publish_postmortem(pm["id"], COMMANDER)
    validate_error(res, "ERR_OPEN_ACTION_ITEMS")


# ===========================================================================
# Difficulty/boundary_precision_check/ack_exactly_at_deadline_not_breached
# ===========================================================================
def test_ack_exactly_at_deadline_not_breached():
    """PRD §3.7: "`ack_sla_breached` is recomputed (true exactly when
    `acknowledged_at` is later than `ack_deadline_at`)."
    PRD §3.5: "It is recomputed at acknowledgement time, when it becomes true
    exactly when `acknowledged_at` is later than `ack_deadline_at`."

    Acknowledging at exactly ack_deadline_at (00:30:00 for a SEV2 calendar
    incident triggered 00:00:00) leaves ack_sla_breached false — the rule is
    strict greater-than, so equality is not a breach.

    Design: Difficulty/boundary_precision_check/ack_exactly_at_deadline_not_breached
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["ack_deadline_at"] == "2026-06-01T00:30:00.000Z"

    set_clock("2026-06-01T00:30:00Z")  # exactly at the deadline
    after = acknowledge(inc["id"], env["responder"]["id"])
    assert after["acknowledged_at"] == "2026-06-01T00:30:00.000Z"
    assert after["ack_sla_breached"] is False, (
        "ack at exactly the deadline (==, not >) must leave ack_sla_breached false"
    )


def test_ack_one_second_past_deadline_breached():
    """PRD §3.5: "It is recomputed at acknowledgement time, when it becomes true
    exactly when `acknowledged_at` is later than `ack_deadline_at`."

    Acknowledging one second past the deadline (00:30:01 vs 00:30:00) sets
    ack_sla_breached true — the X+1 side of the strict-greater-than boundary.

    Design: Difficulty/boundary_precision_check/ack_exactly_at_deadline_not_breached
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["ack_deadline_at"] == "2026-06-01T00:30:00.000Z"

    set_clock("2026-06-01T00:30:01Z")  # one second past
    after = acknowledge(inc["id"], env["responder"]["id"])
    assert after["ack_sla_breached"] is True, (
        "ack later than the deadline must set ack_sla_breached true"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/escalate_empty_oncall_pool_zero_candidates
# ===========================================================================
def test_trigger_with_no_covering_shift_returns_no_escalation_target():
    """PRD §3.2: "If the policy has no tiers, or if tier 1's schedule has no shift
    covering the current clock, the trigger fails the reachable-target check with
    `ERR_NO_ESCALATION_TARGET` (HTTP 409)."
    PRD §3.3: "If the candidate set is empty (nobody is currently covering the
    tier's schedule), the system raises `ERR_NO_ESCALATION_TARGET`."

    Triggering an incident whose tier-1 schedule has a shift only in the past
    (clock 2026-06-10 is outside the only shift [2026-06-01, 2026-06-02)) yields
    an empty candidate pool and ERR_NO_ESCALATION_TARGET.

    Design: Difficulty/boundary_precision_check/escalate_empty_oncall_pool_zero_candidates
    """
    set_clock("2026-06-10T00:00:00Z")
    # Build a topology whose only shift does NOT cover the clock.
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = validate_success(api_client.create_responder(
        {"full_name": "R", "email": "rnocover@x.com", "sms_number": "+15550211"}, ADMIN), 201)
    sch = create_schedule(svc["id"])
    api_client.create_schedule_shift(
        create_schedule_shift_payload(sch["id"], resp["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"),
        ADMIN,
    )
    pol = create_policy(svc["id"])
    api_client.create_escalation_tier(
        {"policy_id": pol["id"], "schedule_id": sch["id"], "tier_level": 1, "delay_minutes": 0}, ADMIN
    )

    res = api_client.create_incident(
        {"service_id": svc["id"], "policy_id": pol["id"], "title": "i", "severity": "SEV2"}, COMMANDER
    )
    validate_error(res, "ERR_NO_ESCALATION_TARGET")


def test_manual_escalate_to_uncovered_next_tier_returns_no_escalation_target():
    """PRD §3.4: "The same reachable-target rule applies on every manual
    escalation step — if the next tier's schedule has no covering shift or the
    policy has no tiers, the step fails with `ERR_NO_ESCALATION_TARGET`."

    Empty-candidate-pool boundary on the manual-escalate endpoint: tier 1 has a
    covering shift (the first page fires), but tier 2's schedule has no shift
    covering the clock, so a manual escalate to tier 2 yields ERR_NO_ESCALATION_TARGET.

    Design: Difficulty/boundary_precision_check/escalate_empty_oncall_pool_zero_candidates
    """
    set_clock("2026-06-01T12:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    r1 = create_responder()
    r2 = create_responder()
    sch1 = create_schedule(svc["id"], name="Sch1")
    sch2 = create_schedule(svc["id"], name="Sch2")
    create_shift(sch1["id"], r1["id"], WIDE_SHIFT_START, WIDE_SHIFT_END)  # covers clock
    # sch2's only shift is in the past, never covering the clock.
    create_shift(sch2["id"], r2["id"], "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z")
    pol = create_policy(svc["id"], repeat_rounds=0)
    create_tier(pol["id"], sch1["id"], tier_level=1, delay_minutes=0)
    create_tier(pol["id"], sch2["id"], tier_level=2, delay_minutes=5)

    inc = trigger_incident(svc["id"], pol["id"], severity="SEV2")
    res = api_client.escalate_incident(inc["id"], escalate_payload(inc["version"]), COMMANDER)
    validate_error(res, "ERR_NO_ESCALATION_TARGET")


# ===========================================================================
# Difficulty/cross_entity_state_dependency/
#   incident_create_during_active_window_auto_suppressed
# ===========================================================================
def test_incident_created_during_active_window_born_suppressed():
    """PRD §3.2: "If an `ACTIVE` maintenance window currently covers the service —
    that is, a window on the incident's `service_id` whose closed interval
    includes the current clock — the incident is born suppressed: `lifecycle_status`
    moves directly to `SUPPRESSED`, `counts_against_budget` is set to false,
    `escalation_status` is set to `EXHAUSTED`, and no page is sent and no paging
    attempt is recorded."

    A new incident on a service with an ACTIVE covering window is born SUPPRESSED
    (lifecycle depends on MaintenanceWindow state).

    Design: Difficulty/cross_entity_state_dependency/incident_create_during_active_window_auto_suppressed
    """
    set_clock("2026-06-01T12:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    pol = create_policy(svc["id"])
    window = create_window(svc["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z")
    validate_success(api_client.activate_maintenance_window(window["id"], ADMIN), 200)

    inc = trigger_incident(svc["id"], pol["id"], severity="SEV1")
    assert inc["lifecycle_status"] == "SUPPRESSED", (
        f"incident created under an ACTIVE window must be born SUPPRESSED, "
        f"got {inc['lifecycle_status']}"
    )


def test_incident_created_during_active_window_no_page_exhausted():
    """PRD §3.2: "the incident is born suppressed: `lifecycle_status` moves
    directly to `SUPPRESSED`, `counts_against_budget` is set to false,
    `escalation_status` is set to `EXHAUSTED`, and no page is sent and no paging
    attempt is recorded."

    The auto-suppressed incident gets escalation_status EXHAUSTED,
    counts_against_budget false, and no paging attempt — the complement of the
    normal first-page branch.

    Design: Difficulty/cross_entity_state_dependency/incident_create_during_active_window_auto_suppressed
    """
    set_clock("2026-06-01T12:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    pol = create_policy(svc["id"])
    window = create_window(svc["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z")
    validate_success(api_client.activate_maintenance_window(window["id"], ADMIN), 200)

    inc = trigger_incident(svc["id"], pol["id"], severity="SEV1")
    assert inc["escalation_status"] == "EXHAUSTED"
    assert inc["counts_against_budget"] is False

    pages = validate_success(api_client.list_incident_page_attempts(inc["id"], COMMANDER), 200)
    assert pages == [], "no paging attempt must be recorded for a suppressed-at-create incident"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/postmortem_create_requires_incident_resolved
# ===========================================================================
def test_postmortem_create_against_acknowledged_incident_rejected():
    """PRD §3.10: "Creating a postmortem requires the referenced incident to be
    `RESOLVED`, else `ERR_INCIDENT_NOT_RESOLVED` (HTTP 409)."

    Creating a postmortem against an ACKNOWLEDGED (not RESOLVED) incident fails
    with ERR_INCIDENT_NOT_RESOLVED — postmortem create depends on Incident state.

    Design: Difficulty/cross_entity_state_dependency/postmortem_create_requires_incident_resolved
    """
    env, incident = setup_acknowledged_incident(severity="SEV2")
    assert incident["lifecycle_status"] == "ACKNOWLEDGED"

    res = api_client.create_postmortem(
        create_postmortem_payload(incident["id"], "rca"), COMMANDER
    )
    validate_error(res, "ERR_INCIDENT_NOT_RESOLVED")


def test_postmortem_create_against_resolved_incident_succeeds():
    """PRD §3.10: "After an incident is resolved, an `IncidentCommander` authors a
    postmortem. A `Postmortem` references the incident through `incident_id` and
    carries a `summary` root-cause narrative; it begins in `DRAFT` status with an
    `open_action_item_count` of zero. Creating a postmortem requires the
    referenced incident to be `RESOLVED`, else `ERR_INCIDENT_NOT_RESOLVED`
    (HTTP 409)."

    Cross-entity dependency complement: when the referenced incident IS RESOLVED,
    the create succeeds, producing a DRAFT postmortem with open_action_item_count
    zero — confirming the dependency gate opens exactly on the RESOLVED state.

    Design: Difficulty/cross_entity_state_dependency/postmortem_create_requires_incident_resolved
    """
    env, incident = setup_resolved_incident(severity="SEV2")
    assert incident["lifecycle_status"] == "RESOLVED"

    res = api_client.create_postmortem(
        create_postmortem_payload(incident["id"], "rca"), COMMANDER
    )
    pm = validate_success(res, 201)
    assert pm["status"] == "DRAFT"
    assert pm["open_action_item_count"] == 0
