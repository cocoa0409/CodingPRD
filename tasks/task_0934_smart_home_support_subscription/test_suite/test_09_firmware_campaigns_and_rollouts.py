"""Firmware campaigns, ring launches, the halt threshold, deferral and retry."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_campaign,
    assert_is_null,
    assert_rollout,
    claim_and_activate,
    fetch_campaign,
    fetch_device,
    fetch_rollout,
    first_response,
    list_rollouts,
    new_campaign,
    new_ticket,
    open_rma,
    report_result,
    set_clock,
    setup_account_with_catalog,
    setup_ring,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# Not-found probes
# ==========================================================================
def test_campaign_read_with_unknown_id_reports_campaign_not_found(api):
    """PRD 2.9 rung 15: "Every `FirmwareCampaign` id named in the path exists —
    otherwise `ERR_CAMPAIGN_NOT_FOUND`. Applies to the campaign endpoints."

    Design: Corner/entities/firmware_campaign_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_campaign("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, 404)


def test_rollout_read_with_unknown_id_reports_rollout_not_found(api):
    """PRD 2.9 rung 16: "Every `FirmwareRollout` id named in the path exists —
    otherwise `ERR_ROLLOUT_NOT_FOUND`. Applies to the rollout endpoints."

    Design: Corner/entities/firmware_rollout_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_rollout("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_ROLLOUT_NOT_FOUND.value, 404)


# ==========================================================================
# Halt, resume, retry and defer
# ==========================================================================
def _halted_two_device_ring():
    """A 2-device ring at halt threshold 0.5 with the first rollout already failed."""
    world = setup_ring(
        device_count=2,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.5,
        plan_kind="PRO",
        allow_overage=False,
        name="Halt House",
        email_prefix="halt",
    )
    report_result(world["rollouts"][0]["id"], "FAILURE")
    return world


def test_resuming_a_halted_campaign_returns_its_blocked_rollouts_to_pending(api):
    """PRD 3.9: "Halting sets every rollout of the current ring still in `PENDING` to
    `BLOCKED_BY_HALT` and moves each of those devices' `firmware_status` to
    `BLOCKED`, and the campaign's `status` becomes `HALTED`."
    PRD 3.9: "**Resuming** a halted campaign returns it to `RING_ACTIVE`, sets every
    `BLOCKED_BY_HALT` rollout of the current ring back to `PENDING`, and returns each
    of those devices' `firmware_status` to `UPDATE_PENDING`."
    PRD 3.9: "`ring_failure_rate` is `ring_failed_count` divided by
    `ring_device_count`, rounded half up to four decimal places, or exactly 0 when
    `ring_device_count` is 0."

    Design: Corner/state_machines/campaign_resume_returns_halt_blocked_rollouts_to_pending
    """
    world = _halted_two_device_ring()

    data = validate_success(api.resume_campaign(world["campaign_id"], {}, ADMIN), 200)

    assert_campaign(data)
    assert data["status"] == "RING_ACTIVE"
    assert fetch_rollout(world["rollouts"][1]["id"])["status"] == "PENDING"
    assert fetch_device(world["devices"][1]["id"])["firmware_status"] == "UPDATE_PENDING"

    first_rollout = fetch_rollout(world["rollouts"][0]["id"])
    assert first_rollout["status"] == "ROLLED_BACK"
    assert first_rollout["retry_count"] == 0

    campaign = fetch_campaign(world["campaign_id"])
    assert campaign["ring_failed_count"] == 1
    assert campaign["ring_failure_rate"] == 0.5


def test_retrying_while_the_campaign_is_halted_reports_campaign_halted(api):
    """PRD 3.9: "The owning campaign must not be `HALTED`, otherwise
    `ERR_CAMPAIGN_HALTED`; only retry can ever reach that rung, because a halt blocks
    every `PENDING` rollout of the ring inside the same request, so result reporting
    and deferral fail the earlier from-state check instead, while a `ROLLED_BACK`
    rollout survives the halt and remains legally retryable on its own axis."

    Design: Corner/state_machines/retry_on_a_halted_campaign_returns_campaign_halted
    """
    world = _halted_two_device_ring()

    response = api.retry_rollout(world["rollouts"][0]["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_HALTED.value, 409)

    rollout = fetch_rollout(world["rollouts"][0]["id"])
    assert rollout["status"] == "ROLLED_BACK"
    assert rollout["retry_count"] == 0
    assert fetch_campaign(world["campaign_id"])["status"] == "HALTED"


def test_the_third_retry_is_refused_by_the_retry_cap(api):
    """PRD 3.9: "The rollout's `retry_count` must then be strictly below 2, otherwise
    `ERR_RETRY_CAP_EXCEEDED` — the third retry is always refused."
    PRD 3.9: "On success `retry_count` rises by one, the rollout returns to `PENDING`,
    `deferred_until` is cleared to null, the device's firmware axis returns to
    `UPDATE_PENDING` from either `ROLLED_BACK` or `DEFERRED`, and the ring counters
    are recomputed, which lowers `ring_failed_count` and therefore `ring_failure_rate`
    when the retried row had been a failure."

    A halt threshold of 0.9 keeps the 1-in-2 rate (0.5) below the halt line, so the
    campaign stays RING_ACTIVE across all three failures.

    Design: Corner/state_machines/third_retry_is_rejected_by_the_retry_cap
    """
    world = setup_ring(
        device_count=2,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.9,
        plan_kind="PRO",
        allow_overage=False,
        name="Retry House",
        email_prefix="ret",
    )
    rollout_id = world["rollouts"][0]["id"]

    report_result(rollout_id, "FAILURE")
    validate_success(api.retry_rollout(rollout_id, {}, ADMIN), 200)
    report_result(rollout_id, "FAILURE")
    validate_success(api.retry_rollout(rollout_id, {}, ADMIN), 200)
    report_result(rollout_id, "FAILURE")

    response = api.retry_rollout(rollout_id, {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_RETRY_CAP_EXCEEDED.value, 409)

    rollout = fetch_rollout(rollout_id)
    assert rollout["retry_count"] == 2
    assert rollout["status"] == "ROLLED_BACK"
    assert fetch_campaign(world["campaign_id"])["status"] == "RING_ACTIVE"


def test_deferring_a_mandatory_security_rollout_is_not_allowed(api):
    """PRD 3.9: "It is permitted only when the owning campaign's `kind` is
    `FEATURE_OPTIONAL` and `defer_until` is at or before the logical clock plus 14
    days; a mandatory security campaign, or a deferral reaching beyond that ceiling,
    is refused with `ERR_DEFER_NOT_ALLOWED`."

    Design: Corner/state_machines/defer_on_a_mandatory_security_campaign_is_not_allowed
    """
    world = setup_ring(
        device_count=1,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.5,
        plan_kind="PRO",
        plan_overrides={"included_device_count": 2},
        allow_overage=False,
        name="Defer House",
        email_prefix="dfr",
    )
    rollout_id = world["rollouts"][0]["id"]

    response = api.defer_rollout(
        rollout_id, {"defer_until": "2026-05-08T00:00:00Z"}, world["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DEFER_NOT_ALLOWED.value, 409)

    rollout = fetch_rollout(rollout_id)
    assert rollout["status"] == "PENDING"
    assert_is_null(rollout, "deferred_until", "FirmwareRollout")
    assert fetch_device(world["devices"][0]["id"])["firmware_status"] == "UPDATE_PENDING"


def test_an_open_ticket_blocks_an_optional_feature_ring(api):
    """PRD 3.9: "for a `FEATURE_OPTIONAL` campaign only, a device with any ticket whose
    `workflow_status` is something other than `RESOLVED` or `CLOSED` gives
    `ERR_OPEN_TICKET_BLOCKS_ROLLOUT`, while a `SECURITY_MANDATORY` campaign skips
    that check entirely"
    PRD 3.9: "a listed device failing any of these is reported as `ERR_INVALID_STATE`,
    and the whole request is refused — a ring launch is all-or-nothing, and no
    rollout row is created when any listed device is unacceptable."

    Design: Corner/validations/optional_campaign_ring_is_blocked_by_an_open_ticket_on_the_device
    """
    world = setup_account_with_catalog(
        "HUB", plan_kind="PRO", allow_overage=False, name="Opt House", email_prefix="opt"
    )
    device = claim_and_activate(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P3",
        summary="Hub LED flickers",
        device_id=device["id"],
        opened_by_member_id=world["owner"]["id"],
    )
    first_response(ticket["id"], "Triaged.")
    campaign = new_campaign(
        world["catalog"]["id"], "FEATURE_OPTIONAL", "1.5.0", halt_failure_rate_pct=0.5
    )

    response = api.launch_ring(
        campaign["id"],
        {
            "ring_index": 1,
            "device_ids": [device["id"]],
            "window_start_at": "2026-05-01T00:00:00Z",
            "window_end_at": "2026-05-10T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_OPEN_TICKET_BLOCKS_ROLLOUT.value, 409)

    current = fetch_campaign(campaign["id"])
    assert current["status"] == "DRAFT"
    assert current["ring_device_count"] == 0
    assert fetch_device(device["id"])["firmware_status"] == "CURRENT"
    assert list_rollouts(campaign_id=campaign["id"]) == []


# ==========================================================================
# Difficulty: the halt threshold is inclusive
# ==========================================================================
def _five_device_ring():
    return setup_ring(
        device_count=5,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.20,
        plan_kind="PRO",
        allow_overage=False,
        name="Ring House",
        email_prefix="ring",
    )


def test_one_failure_in_five_halts_the_campaign_at_exactly_the_threshold(api):
    """PRD 3.9: "The campaign **halts** when the rounded rate is greater than or equal
    to its `halt_failure_rate_pct`. With the default threshold of 0.20, one failure
    out of five gives 0.2000 and halts, while one out of six gives 0.1667 and does
    not."
    PRD 3.9: "On `FAILURE` the rollout becomes `ROLLED_BACK` and the device's firmware
    axis moves `UPDATE_PENDING → ROLLED_BACK`, with `firmware_version` deliberately
    **left unchanged** because the rollback restores the prior image."

    Design: Difficulty/boundary_precision_check/ring_failure_rate_exactly_at_halt_threshold_halts_campaign
    """
    world = _five_device_ring()

    validate_success(
        api.report_rollout_result(world["rollouts"][0]["id"], {"result": "FAILURE"}, ADMIN),
        200,
    )

    rollout = fetch_rollout(world["rollouts"][0]["id"])
    assert_rollout(rollout)
    assert rollout["status"] == "ROLLED_BACK"
    assert rollout["last_result"] == "FAILURE"

    device = fetch_device(world["devices"][0]["id"])
    assert device["firmware_status"] == "ROLLED_BACK"
    assert device["firmware_version"] == "1.0.0"

    campaign = fetch_campaign(world["campaign_id"])
    assert campaign["ring_device_count"] == 5
    assert campaign["ring_failed_count"] == 1
    assert campaign["ring_failure_rate"] == 0.2
    assert campaign["status"] == "HALTED"


def test_the_halt_blocks_every_still_pending_rollout_of_the_ring(api):
    """PRD 3.9: "Halting sets every rollout of the current ring still in `PENDING` to
    `BLOCKED_BY_HALT` and moves each of those devices' `firmware_status` to
    `BLOCKED`, and the campaign's `status` becomes `HALTED`."

    Design: Difficulty/boundary_precision_check/ring_failure_rate_exactly_at_halt_threshold_halts_campaign
    """
    world = _five_device_ring()

    validate_success(
        api.report_rollout_result(world["rollouts"][0]["id"], {"result": "FAILURE"}, ADMIN),
        200,
    )

    for index in range(1, 5):
        assert fetch_rollout(world["rollouts"][index]["id"])["status"] == "BLOCKED_BY_HALT"
        assert fetch_device(world["devices"][index]["id"])["firmware_status"] == "BLOCKED"


# ==========================================================================
# Difficulty: a ring launch is gated by RmaCase state on the listed device
# ==========================================================================
def _rma_blocked_launch_world():
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="PRO",
        plan_overrides={"included_device_count": 1},
        allow_overage=False,
        name="Rma House",
        email_prefix="rma",
    )
    device = claim_and_activate(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    world["device"] = device
    world["rma"] = open_rma(device["id"], device["version"])
    world["campaign"] = new_campaign(
        world["catalog"]["id"], "SECURITY_MANDATORY", "1.1.0", halt_failure_rate_pct=0.5
    )
    return world


def test_a_routed_rma_case_blocks_the_ring_launch_over_that_device(api):
    """PRD 3.9: "an in-flight RMA case on the device in `OPEN`, `ROUTED`,
    `ADVANCE_SHIPPED` or `AWAITING_RETURN` gives `ERR_RMA_IN_FLIGHT` regardless of the
    campaign's kind"
    PRD 3.11: "Within the creating request the new case walks `OPEN → ROUTED`, so a
    freshly created case is returned in `ROUTED`."

    Design: Difficulty/cross_entity_state_dependency/ring_launch_depends_on_rma_case_state_of_the_listed_device
    """
    world = _rma_blocked_launch_world()

    response = api.launch_ring(
        world["campaign"]["id"],
        {
            "ring_index": 1,
            "device_ids": [world["device"]["id"]],
            "window_start_at": "2026-05-01T00:00:00Z",
            "window_end_at": "2026-05-10T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RMA_IN_FLIGHT.value, 409)

    rma = world["rma"]
    assert rma["warranty_state"] == "IN_WARRANTY"
    assert rma["routing_target"] == "ADVANCE_REPLACEMENT"
    assert rma["hold_amount_cents"] == 14940
    assert rma["hold_state"] == "HELD"


def test_the_blocked_launch_creates_no_rollout_and_leaves_the_campaign_in_draft(api):
    """PRD 3.9: "a listed device failing any of these is reported as `ERR_INVALID_STATE`,
    and the whole request is refused — a ring launch is all-or-nothing, and no
    rollout row is created when any listed device is unacceptable."
    PRD 3.9: "The campaign is created in `DRAFT` with `current_ring_index` 0,
    `ring_window_start_at` and `ring_window_end_at` null, and `ring_device_count`,
    `ring_failed_count` and `ring_failure_rate` all 0."

    Design: Difficulty/cross_entity_state_dependency/ring_launch_depends_on_rma_case_state_of_the_listed_device
    """
    world = _rma_blocked_launch_world()

    api.launch_ring(
        world["campaign"]["id"],
        {
            "ring_index": 1,
            "device_ids": [world["device"]["id"]],
            "window_start_at": "2026-05-01T00:00:00Z",
            "window_end_at": "2026-05-10T00:00:00Z",
        },
        ADMIN,
    )

    assert fetch_campaign(world["campaign"]["id"])["status"] == "DRAFT"
    assert list_rollouts(device_id=world["device"]["id"]) == []
    assert fetch_device(world["device"]["id"])["firmware_status"] == "CURRENT"


# ==========================================================================
# Difficulty: rollout windows are CLOSED intervals, so touching ends collide
# ==========================================================================
def _touching_window_world():
    world = setup_ring(
        device_count=1,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.5,
        target_firmware_version="1.1.0",
        window=("2026-05-01T00:00:00Z", "2026-05-05T12:00:00Z"),
        plan_kind="PRO",
        allow_overage=False,
        name="Window House",
        email_prefix="win",
    )
    world["second_campaign"] = new_campaign(
        world["catalog"]["id"], "SECURITY_MANDATORY", "1.2.0", halt_failure_rate_pct=0.5
    )
    return world


def test_rollout_windows_that_touch_at_one_endpoint_collide(api):
    """PRD 3.9: "Rollout windows are **closed** intervals running from
    `window_start_at` to `window_end_at` inclusive, and there is no buffer at all. A
    requested window conflicts with an existing `PENDING` rollout of the same device
    when the existing window's start is at or before the requested window's end
    **and** the requested window's start is at or before the existing window's end."
    PRD 3.9: "Touching endpoints therefore *do* conflict: an existing `PENDING`
    rollout ending at 12:00 collides with a new window starting at exactly 12:00."

    Design: Difficulty/resource_temporal_overlap/rollout_windows_touching_at_one_endpoint_conflict_on_the_device
    """
    world = _touching_window_world()

    response = api.launch_ring(
        world["second_campaign"]["id"],
        {
            "ring_index": 1,
            "device_ids": [world["devices"][0]["id"]],
            "window_start_at": "2026-05-05T12:00:00Z",
            "window_end_at": "2026-05-08T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_ROLLOUT_WINDOW_OVERLAP.value, 409)

    second = fetch_campaign(world["second_campaign"]["id"])
    assert second["status"] == "DRAFT"
    assert second["ring_device_count"] == 0


def test_the_colliding_launch_leaves_the_first_campaigns_single_rollout_alone(api):
    """PRD 3.9: "A successful launch sets `current_ring_index` to the requested
    `ring_index`, sets `ring_window_start_at` and `ring_window_end_at` to the
    requested window, creates one `FirmwareRollout` row per listed device in
    `PENDING` with `campaign_id`, `device_id`, a `ring_index` copied from the
    campaign's `current_ring_index`, `window_start_at` and `window_end_at` copied
    from the campaign's ring window, `retry_count` 0, `last_result` null,
    `deferred_until` null and `result_reported_at` null, moves each listed device's
    `firmware_status` from `CURRENT` or `ROLLED_BACK` to `UPDATE_PENDING`, and
    recomputes `ring_device_count`, `ring_failed_count` and `ring_failure_rate`."

    Design: Difficulty/resource_temporal_overlap/rollout_windows_touching_at_one_endpoint_conflict_on_the_device
    """
    world = _touching_window_world()

    api.launch_ring(
        world["second_campaign"]["id"],
        {
            "ring_index": 1,
            "device_ids": [world["devices"][0]["id"]],
            "window_start_at": "2026-05-05T12:00:00Z",
            "window_end_at": "2026-05-08T00:00:00Z",
        },
        ADMIN,
    )

    first = fetch_campaign(world["campaign_id"])
    assert first["status"] == "RING_ACTIVE"
    assert first["ring_device_count"] == 1

    rows = list_rollouts(device_id=world["devices"][0]["id"])
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == world["campaign_id"]
    assert fetch_device(world["devices"][0]["id"])["firmware_status"] == "UPDATE_PENDING"
