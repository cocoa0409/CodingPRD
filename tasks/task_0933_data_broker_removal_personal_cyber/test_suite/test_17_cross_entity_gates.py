"""Three entity pairs where one row's state blocks a transition on another:
scan/profile, seat/add-on and removal request/identity document."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    ApiErrorId, assert_same_instant, fixtures as fx,
)


# ==========================================================================
# ScanRun -> MonitoredProfile
# ==========================================================================

def _failed_scan_under_a_paused_profile():
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    fx.start_scan(scan["id"])
    validate_success(fx.api.fail_scan(scan["id"], "broker portal timeout", fx.AGENT))
    validate_success(fx.api.pause_profile(profile["id"], household["owner"]))
    return household, profile, scan


def test_scan_retry_is_refused_while_its_profile_is_paused(api):
    """PRD §2.6: "20. The monitored profile the operation depends on has status `ACTIVE`,
    otherwise `ERR_PROFILE_NOT_ACTIVE` (409). This rung applies to scan queuing and scan
    retry **only**; starting a queued scan is deliberately excluded from it."
    PRD §3.4: "Retrying moves `FAILED → QUEUED`, increments `retry_count` by 1, clears
    `started_at` back to null, consumes no additional scan unit, and requires the profile
    to be `ACTIVE` — failed scans survive a pause, which is exactly what makes that
    rejection path reachable."

    Design: Difficulty/cross_entity_state_dependency/scan_retry_blocked_by_paused_profile
    """
    household, profile, scan = _failed_scan_under_a_paused_profile()

    response = api.retry_scan(scan["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_PROFILE_NOT_ACTIVE.value, 409)
    row = validate_success(api.get_scan_run(scan["id"], fx.ADMIN))
    assert row["status"] == "FAILED", "the failed scan survives the pause untouched"
    assert row["retry_count"] == 0
    assert fx.read_profile(profile["id"])["status"] == "PAUSED"


def test_scan_retry_succeeds_once_the_profile_is_reactivated(api):
    """PRD §3.3: "The reactivation edge `PAUSED → ACTIVE` requires only that the profile is
    in `PAUSED`, the member is `ACTIVE` and the account is `ACTIVE` — and it consumes
    **no** new unit, because the unit taken at first activation was never released."
    PRD §3.4: "Retrying moves `FAILED → QUEUED`, increments `retry_count` by 1, clears
    `started_at` back to null, consumes no additional scan unit, and requires the profile
    to be `ACTIVE` — failed scans survive a pause, which is exactly what makes that
    rejection path reachable."

    Design: Difficulty/cross_entity_state_dependency/scan_retry_blocked_by_paused_profile
    """
    household, profile, scan = _failed_scan_under_a_paused_profile()

    reactivated = validate_success(api.activate_profile(profile["id"], household["owner"]))
    assert reactivated["status"] == "ACTIVE"

    data = validate_success(api.retry_scan(scan["id"], fx.AGENT))

    assert data["status"] == "QUEUED"
    assert data["retry_count"] == 1
    assert data["started_at"] is None
    account = fx.read_account(household)
    assert account["scan_units_consumed"] == 1, "a retry draws no second scan unit"
    assert account["profile_units_consumed"] == 1, \
        "re-activating from PAUSED consumes no second profile unit"


# ==========================================================================
# DeviceSeat -> AddOnSubscription
# ==========================================================================

def _released_seat_under_a_suspended_addon():
    household = fx.open_household()
    addon, seat = fx.setup_addon_with_seat(household, addon_type="DEVICE_PROTECTION",
                                           seats_total=2, per_seat_fee_cents=300,
                                           device_label="Dana Phone")
    fx.release_seat(seat["id"], household["owner"])
    validate_success(fx.api.suspend_addon(addon["id"], household["owner"]))
    # released_at 2026-05-01 + 72h = 2026-05-04; 2026-05-05 is well past it.
    fx.set_clock("2026-05-05T00:00:00Z")
    return household, addon, seat


def test_seat_rebind_is_refused_while_the_addon_is_suspended(api):
    """PRD §2.6: "23. The add-on the operation depends on has status `ACTIVE`, otherwise
    `ERR_ADDON_NOT_ACTIVE` (409). Applies to seat binding and seat rebinding."
    PRD §3.8: "Rebinding — which supplies a fresh `device_label` — moves
    `RELEASED → BOUND`, and requires the current instant to be at or after
    `rebind_eligible_at` (an **inclusive** boundary: rebinding at exactly 72 hours after
    release is allowed, and one millisecond earlier is rejected with
    `ERR_SEAT_REBIND_COOLOFF`), the add-on to be `ACTIVE`, and at least one seat's worth of
    capacity to remain available."

    Design: Difficulty/cross_entity_state_dependency/seat_rebind_blocked_by_suspended_addon
    """
    household, addon, seat = _released_seat_under_a_suspended_addon()

    response = api.rebind_seat(seat["id"], "Dana Phone 2", household["owner"])

    validate_error(response, ApiErrorId.ERR_ADDON_NOT_ACTIVE.value, 409)
    row = fx.read_seat(seat["id"])
    assert row["status"] == "RELEASED"
    assert row["bind_count"] == 1
    # The cool-off rung was satisfied: eligibility passed a day before this call.
    assert_same_instant(row["rebind_eligible_at"], "2026-05-04T00:00:00Z",
                        "rebind_eligible_at")
    addon_row = fx.read_addon(addon["id"])
    assert addon_row["status"] == "SUSPENDED"
    assert addon_row["seats_bound"] == 0


def test_seat_rebind_succeeds_once_the_addon_resumes(api):
    """PRD §3.8: "Resuming requires the add-on to be `SUSPENDED` and its account to be
    `ACTIVE`, clears `suspended_at` to null, and — caused by that transition — moves every
    seat of the add-on sitting in `VOIDED` whose member is `ACTIVE` along the edge
    `VOIDED → BOUND`, incrementing each seat's `bind_count` by 1."
    PRD §3.8: "On success it stamps `bound_at`, clears `released_at` to null, and
    increments `bind_count`."

    Design: Difficulty/cross_entity_state_dependency/seat_rebind_blocked_by_suspended_addon
    """
    household, addon, seat = _released_seat_under_a_suspended_addon()

    resumed = validate_success(api.resume_addon(addon["id"], household["owner"]))
    assert resumed["status"] == "ACTIVE"

    data = validate_success(api.rebind_seat(seat["id"], "Dana Phone 2",
                                            household["owner"]))

    assert data["status"] == "BOUND"
    assert data["bind_count"] == 2
    assert data["released_at"] is None
    assert_same_instant(data["bound_at"], "2026-05-05T00:00:00Z", "bound_at")


# ==========================================================================
# RemovalRequest -> IdentityDocument
# ==========================================================================

def test_removal_submit_without_any_identity_document_is_refused(api):
    """PRD §2.6: "25. When the broker requires identity verification, the member holds at
    least one identity document whose status is `VERIFIED`, otherwise
    `ERR_IDENTITY_VERIFICATION_REQUIRED` (403). Applies to removal submission."

    Design: Difficulty/cross_entity_state_dependency/removal_submit_gated_by_identity_document_state
    """
    world = fx.setup_verifying_broker_world()

    response = api.submit_removal_request(world["request"]["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_IDENTITY_VERIFICATION_REQUIRED.value, 403)
    assert fx.read_removal(world["request"]["id"])["status"] == "DRAFTED"


def test_removal_submit_with_a_verified_document_past_its_expiry_is_refused(api):
    """PRD §2.6: "26. When the broker requires identity verification and every `VERIFIED`
    identity document the member holds has reached or passed its `expires_at`, the
    submission is blocked with `ERR_IDENTITY_DOCUMENT_EXPIRED` (409). Applies to removal
    submission."
    PRD §3.5: "The boundary is strict — at exactly `expires_at` the document is already
    `INVALID`."

    The PRD states rung 25, rung 26 and a lazy `VERIFIED → EXPIRED` system transition
    side by side and explicitly declines to order the lazy transition against those two
    rungs, so both of the codes below are faithful readings of the same fixture; the
    assertion is written to hold under either.

    Design: Difficulty/cross_entity_state_dependency/removal_submit_gated_by_identity_document_state
    """
    world = fx.setup_verifying_broker_world()
    fx.upload_and_verify_document(world["household"], "2026-05-10T00:00:00Z")

    fx.set_clock("2026-05-10T00:00:00Z")
    response = api.submit_removal_request(world["request"]["id"], fx.AGENT)

    validate_error_is_one_of(response, [
        ApiErrorId.ERR_IDENTITY_DOCUMENT_EXPIRED.value,
        ApiErrorId.ERR_IDENTITY_VERIFICATION_REQUIRED.value,
    ])
    assert fx.read_removal(world["request"]["id"])["status"] == "DRAFTED"


def test_removal_submit_succeeds_while_the_document_is_still_valid(api):
    """PRD §3.5: "A document's `effective_status` is derived, not stored: it reads `VALID`
    when the document's status is `VERIFIED` **and** the current instant is strictly before
    `expires_at`, and `INVALID` in every other case."
    PRD §3.5: "The result is stored as `effective_window_days`, `deadline_variant` is set
    to `BASE`, and `sla_deadline_at` is `submitted_at` advanced by that many whole days
    (each day being 86400 seconds), preserving the millisecond precision of `submitted_at`."

    The clock never reaches `expires_at` in this fixture, so the lazy
    `VERIFIED → EXPIRED` transition cannot fire under either reading of §3.5.

    Design: Difficulty/cross_entity_state_dependency/removal_submit_gated_by_identity_document_state
    """
    world = fx.setup_verifying_broker_world()
    document = fx.upload_and_verify_document(world["household"], "2026-05-10T00:00:00Z")
    assert document["status"] == "VERIFIED"

    fx.set_clock("2026-05-09T00:00:00Z")
    rows, _ = validate_paginated(api.list_member_identity_documents(
        world["household"]["owner_id"], world["household"]["owner"]))
    assert rows[0]["effective_status"] == "VALID"

    data = validate_success(api.submit_removal_request(world["request"]["id"], fx.AGENT))

    assert data["status"] == "SUBMITTED"
    # EuroRecords: 20 declared window + 2 EMAIL buffer = 22; max(22, 30 EU floor) = 30.
    assert data["effective_window_days"] == 30
    # 2026-05-09 + 30 whole days: 22 days to 2026-05-31, 8 more to 2026-06-08.
    assert_same_instant(data["sla_deadline_at"], "2026-06-08T00:00:00Z", "sla_deadline_at")
