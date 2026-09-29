"""Cross-entity state-dependency compliance tests.

Two dependencies are pinned here. An activation's dispatch depends on the
governance state of its parent segment, so the identical call flips from success
to refusal purely because the segment aged out of APPROVED. An erasure request's
propagation depends on the state of its subject's legal-hold suppression entry,
so the identical call flips from refusal to success once that entry is released.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_GOVERNANCE_NOT_APPROVED,
    ERR_LEGAL_HOLD_ACTIVE,
)
from test_helpers.assertions import assert_instant_equals, plus_hours
from test_helpers.test_users import ADMIN, ANALYST, PRIVACY, PRIVACY_2

# The instant the server's logical clock reads before any operator moves it.
BOOT_CLOCK = "2026-08-01T00:00:00Z"
WINDOW_START = "2026-08-05T00:00:00Z"
WINDOW_END = "2026-08-05T02:00:00Z"


def _governance_environment(api):
    """One emailable member, an approved segment valid for a single day and two
    draft activations of it on two separate destinations.

    The approval is stamped at the boot clock, so governance expires at
    2026-08-02T00:00:00Z. The two activations share a window but sit on different
    destinations, so neither the cooldown gap nor the concurrency cap is in play.
    """
    fx.reset_clock(api)
    env = fx.emailable_profiles(api, 1)
    env["segment"] = fx.approved_segment(
        api, list(f.POSTAL_10001), governance_valid_days=1
    )
    env["destination_a"] = fx.register_destination(api)
    env["destination_b"] = fx.register_destination(api, platform_kind="MESSAGING")
    env["activation_a"] = fx.draft_activation(
        api, env["segment"]["id"], env["destination_a"]["id"], WINDOW_START, WINDOW_END
    )
    env["activation_b"] = fx.draft_activation(
        api, env["segment"]["id"], env["destination_b"]["id"], WINDOW_START, WINDOW_END
    )
    return env


def _expire_the_approval(api):
    """Move the clock past the approval and let a retention run act on it."""
    fx.set_clock(api, "2026-08-03T00:00:00Z")
    return fx.retention_run(api)


# --------------------------------------------------------------------------
# an activation's dispatch depends on its parent segment's governance state
# --------------------------------------------------------------------------
def test_dispatch_succeeds_while_the_parent_segment_is_approved(api):
    """The satisfied arm of the dependency: while the parent segment is APPROVED and
    the clock is still before its expiry instant, the dispatch resolves the audience,
    consumes quota and raises the segment's active activation count.

    "It requires the activation to be `DRAFT`, the segment to be `APPROVED` with the logical clock now strictly before its `governance_expires_at` — any other governance posture being `ERR_GOVERNANCE_NOT_APPROVED` — the destination to be `ACTIVE`, and, for a sensitive audience, both the segment's `sensitive_use_approved` and the destination's `sensitive_attribute_permitted` to be true."
    "Approving moves the segment `PENDING_GOVERNANCE_REVIEW` → `APPROVED`, takes `sensitive_use_approved` from the request body, stamps `approved_at` at the logical clock now, and sets `governance_expires_at` to `approved_at` advanced by `governance_valid_days` days."
    "The audience is those candidates whose `activatable_channels` contains the destination's `channel`, and `audience_size` is its size."
    "`dispatched_hash_count` is the number of audience members whose required identifier, selected by the destination's `hashing_algorithm`, is non-null."
    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Difficulty/cross_entity_state_dependency/activation_dispatch_depends_on_segment_governance_state
    """
    env = _governance_environment(api)
    segment = fx.reread_segment(api, env["segment"]["id"])
    assert segment["status"] == "APPROVED"
    assert_instant_equals(segment["approved_at"], BOOT_CLOCK, "approved_at")
    assert_instant_equals(
        segment["governance_expires_at"], "2026-08-02T00:00:00Z", "governance_expires_at"
    )

    response = api.dispatch_activation(env["activation_a"]["id"], ANALYST)
    activation = validate_success(response, 200)

    assert activation["status"] == "DISPATCHED"
    assert_instant_equals(activation["dispatched_at"], BOOT_CLOCK, "dispatched_at")
    assert activation["candidate_count"] == 1
    assert activation["audience_size"] == 1
    assert activation["dispatched_hash_count"] == 1

    destination = fx.reread_destination(api, env["destination_a"]["id"])
    assert destination["remaining_daily_hash_quota"] == (
        destination["daily_hash_quota"] - 1
    )
    segment_after = fx.reread_segment(api, env["segment"]["id"])
    assert segment_after["active_activation_count"] == 1


def test_dispatch_refused_once_the_parent_segment_governance_expires(api):
    """The sibling activation's own status never moved — it is still DRAFT — yet the
    identical dispatch is now refused, purely because the parent segment aged out of
    APPROVED into GOVERNANCE_EXPIRED, and the refused call consumes no quota.

    "It requires the activation to be `DRAFT`, the segment to be `APPROVED` with the logical clock now strictly before its `governance_expires_at` — any other governance posture being `ERR_GOVERNANCE_NOT_APPROVED` — the destination to be `ACTIVE`, and, for a sensitive audience, both the segment's `sensitive_use_approved` and the destination's `sensitive_attribute_permitted` to be true."
    "Step four expires every segment approval whose `status` is `APPROVED` and whose `governance_expires_at` is non-null and at or before now, with the pause-and-refund cascade of §3.8."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Difficulty/cross_entity_state_dependency/activation_dispatch_depends_on_segment_governance_state
    """
    env = _governance_environment(api)
    dispatched = fx.dispatch(api, env["activation_a"]["id"])
    assert dispatched["status"] == "DISPATCHED"

    _expire_the_approval(api)
    segment = fx.reread_segment(api, env["segment"]["id"])
    assert segment["status"] == "GOVERNANCE_EXPIRED"

    response = api.dispatch_activation(env["activation_b"]["id"], ANALYST)
    validate_error(response, ERR_GOVERNANCE_NOT_APPROVED)

    activation_b = fx.reread_activation(api, env["activation_b"]["id"])
    assert activation_b["status"] == "DRAFT"
    assert activation_b["dispatched_at"] is None
    assert activation_b["dispatched_hash_count"] == 0
    assert activation_b["audience_size"] == 0

    destination_b = fx.reread_destination(api, env["destination_b"]["id"])
    assert destination_b["remaining_daily_hash_quota"] == destination_b["daily_hash_quota"]


def test_governance_expiry_drags_the_dispatched_sibling_to_paused(api):
    """The same clock move that refuses the draft's dispatch also pauses the sibling
    that had already dispatched, and reports both effects on the retention run.

    "Once the logical clock reaches `governance_expires_at`, a retention run moves the segment `APPROVED` → `GOVERNANCE_EXPIRED` and resets `sensitive_use_approved` to false; the same transition can also be reached mid-request when a cascade drops the segment's `active_activation_count` to 0 at or after that instant."
    "Expiry pauses delivery: every activation of that segment in `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING` moves to `PAUSED` with `paused_reason` of `GOVERNANCE_EXPIRED`, and each such activation's `dispatched_hash_count` is refunded to its destination's `remaining_daily_hash_quota`."
    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."
    "The run reports what it did as `run_at`, `expired_consent_record_count`, `expired_suppression_entry_count`, `timed_out_vendor_task_count`, `partially_verified_deletion_request_count`, `governance_expired_segment_count`, `paused_activation_count` and `quota_reset_destination_count`, and it increments the `version` of every entity it mutates by 1."

    Design: Difficulty/cross_entity_state_dependency/activation_dispatch_depends_on_segment_governance_state
    """
    env = _governance_environment(api)
    fx.dispatch(api, env["activation_a"]["id"])

    run = _expire_the_approval(api)
    assert run["governance_expired_segment_count"] == 1
    assert run["paused_activation_count"] == 1
    assert_instant_equals(run["run_at"], "2026-08-03T00:00:00Z", "run_at")

    segment = fx.reread_segment(api, env["segment"]["id"])
    assert segment["status"] == "GOVERNANCE_EXPIRED"
    assert segment["sensitive_use_approved"] is False
    assert segment["active_activation_count"] == 0

    activation_a = fx.reread_activation(api, env["activation_a"]["id"])
    assert activation_a["status"] == "PAUSED"
    assert activation_a["paused_reason"] == "GOVERNANCE_EXPIRED"

    activation_b = fx.reread_activation(api, env["activation_b"]["id"])
    assert activation_b["status"] == "DRAFT"
    assert activation_b["paused_reason"] is None


# --------------------------------------------------------------------------
# an erasure's propagation depends on its subject's legal-hold entry state
# --------------------------------------------------------------------------
def _held_erasure_environment(api):
    """An erasure in RECEIVED over a subject who also carries an ACTIVE legal hold.

    One destination has already taken a delivery, so exactly one destination would
    qualify for the fan-out. The hold is raised after the erasure was recorded, so
    the subject is DELETION_PENDING and the hold is stored while outranked.
    """
    fx.reset_clock(api)
    env = fx.delivering_activation_environment(api, member_count=2)
    subject = env["profiles"][0]
    env["subject"] = subject
    env["request"] = fx.record_erasure(api, subject["id"])
    env["hold"] = fx.add_suppression(
        api,
        subject["id"],
        entry_type="LEGAL_HOLD",
        reason_code="LITIGATION_HOLD",
    )
    env["profile"] = fx.reread_profile(api, subject["id"])
    return env


def _propagate(api, deletion_request_id):
    """Propagate under the request's live version guard."""
    current = fx.reread_deletion_request(api, deletion_request_id)
    return api.propagate_deletion_request(
        deletion_request_id, f.propagate_payload(current["version"]), PRIVACY
    )


def test_propagate_refused_while_the_legal_hold_entry_is_active(api):
    """The unsatisfied arm of the dependency: an ACTIVE legal-hold entry on the
    subject refuses the fan-out, and the refused call itself parks the request in
    BLOCKED_LEGAL_HOLD carrying the hold's reason code, with no task minted.

    "Where any suppression entry of the subject has `entry_type` of `LEGAL_HOLD` and `status` of `ACTIVE`, the hold wins."
    "The request moves `RECEIVED` → `BLOCKED_LEGAL_HOLD`, `blocked_reason` is set to that entry's `reason_code`, no task is minted, the subject stays `DELETION_PENDING`, the request's `version` increments — and **the call still fails with `ERR_LEGAL_HOLD_ACTIVE`**."
    "That stored-but-outranked hold still blocks erasure propagation and is the only route by which a deletion request ever becomes blocked."

    Design: Difficulty/cross_entity_state_dependency/deletion_propagate_depends_on_suppression_legal_hold_state
    """
    env = _held_erasure_environment(api)
    assert env["hold"]["status"] == "ACTIVE"
    assert env["hold"]["entry_type"] == "LEGAL_HOLD"
    assert env["profile"]["privacy_status"] == "DELETION_PENDING"

    before = fx.reread_deletion_request(api, env["request"]["id"])
    assert before["status"] == "RECEIVED"

    response = _propagate(api, env["request"]["id"])
    validate_error(response, ERR_LEGAL_HOLD_ACTIVE)

    after = fx.reread_deletion_request(api, env["request"]["id"])
    assert after["status"] == "BLOCKED_LEGAL_HOLD"
    assert after["blocked_reason"] == "LITIGATION_HOLD"
    assert after["total_vendor_task_count"] == 0
    assert after["pending_vendor_task_count"] == 0
    assert after["version"] == before["version"] + 1

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": env["request"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert tasks == []

    profile = fx.reread_profile(api, env["subject"]["id"])
    assert profile["privacy_status"] == "DELETION_PENDING"


def test_releasing_the_hold_returns_the_blocked_request_to_received(api):
    """Releasing the hold — by a second officer, as segregation of duties demands —
    is what changes the depended-on state, and it drags the blocked erasure back to
    RECEIVED with its block reason cleared while the subject stays deletion-pending.

    "A `PrivacyOfficer` releases an `ACTIVE` entry, which moves it `ACTIVE` → `RELEASED`, stamps `released_by_user_id` with the acting `X-User-ID` and `released_at` at the logical clock now, and increments the entry's `version`."
    "A legal hold released afterwards returns the request `BLOCKED_LEGAL_HOLD` → `RECEIVED` and clears `blocked_reason`, and this is the only route into and out of that state."
    "The practical consequence, spelled out again in §3.7, is that a legal hold placed on a subject who is already `DELETION_PENDING` is stored as an in-force entry but does *not* move `privacy_status` — the erasure state is the stronger claim — while still blocking the erasure's downstream fan-out."

    Design: Difficulty/cross_entity_state_dependency/deletion_propagate_depends_on_suppression_legal_hold_state
    """
    env = _held_erasure_environment(api)
    validate_error(_propagate(api, env["request"]["id"]), ERR_LEGAL_HOLD_ACTIVE)
    blocked = fx.reread_deletion_request(api, env["request"]["id"])
    assert blocked["status"] == "BLOCKED_LEGAL_HOLD"

    response = api.release_suppression_entry(env["hold"]["id"], PRIVACY_2)
    entry = validate_success(response, 200)

    assert entry["status"] == "RELEASED"
    assert entry["released_by_user_id"] == PRIVACY_2["X-User-ID"]
    assert_instant_equals(entry["released_at"], BOOT_CLOCK, "released_at")

    after = fx.reread_deletion_request(api, env["request"]["id"])
    assert after["status"] == "RECEIVED"
    assert after["blocked_reason"] is None

    profile = fx.reread_profile(api, env["subject"]["id"])
    assert profile["privacy_status"] == "DELETION_PENDING"


def test_propagate_succeeds_once_the_hold_is_released(api):
    """The satisfied arm of the dependency: the identical propagate call that was
    refused a moment ago now fans the erasure out to the one destination that has
    taken a delivery, minting a dispatched task with its acknowledgement deadline.

    "Where no hold applies, the qualifying destinations are those whose `status` is `ACTIVE` and which have at least one activation whose `status` is not `DRAFT` — a platform that never received a delivery has nothing to erase, and an inactive platform is skipped."
    "Where at least one qualifies, the request moves `RECEIVED` → `PROPAGATING`, one **vendor deletion task** is minted per qualifying destination in destination `created_at` ascending order, `propagated_at` is stamped at the logical clock now, the five counters are recomputed and the request's `version` increments."
    "Each task is created `PENDING` and immediately advanced `PENDING` → `DISPATCHED` within the same call, with `dispatched_at` at the logical clock now, `attempt_count` at 1, and `ack_deadline_at` set to `dispatched_at` advanced by that destination's `deletion_ack_sla_hours` hours."

    Design: Difficulty/cross_entity_state_dependency/deletion_propagate_depends_on_suppression_legal_hold_state
    """
    env = _held_erasure_environment(api)
    validate_error(_propagate(api, env["request"]["id"]), ERR_LEGAL_HOLD_ACTIVE)
    released = fx.release_suppression(api, env["hold"]["id"], PRIVACY_2)
    assert released["status"] == "RELEASED"

    updated = validate_success(_propagate(api, env["request"]["id"]), 200)

    assert updated["status"] == "PROPAGATING"
    assert updated["total_vendor_task_count"] == 1
    assert updated["pending_vendor_task_count"] == 1
    assert updated["acknowledged_vendor_task_count"] == 0
    assert updated["verified_at"] is None
    assert_instant_equals(updated["propagated_at"], BOOT_CLOCK, "propagated_at")

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": env["request"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    task = tasks[0]
    assert task["destination_id"] == env["destination"]["id"]
    assert task["status"] == "DISPATCHED"
    assert task["attempt_count"] == 1
    assert_instant_equals(task["dispatched_at"], BOOT_CLOCK, "dispatched_at")
    assert_instant_equals(
        task["ack_deadline_at"],
        plus_hours(BOOT_CLOCK, env["destination"]["deletion_ack_sla_hours"]),
        "ack_deadline_at",
    )

    profile = fx.reread_profile(api, env["subject"]["id"])
    assert profile["privacy_status"] == "DELETION_PENDING"
