"""Lifecycle and transition compliance tests for the Customer Data Platform API.

Each test drives one declared transition — or one refusal of a transition — over a
live server, building every precondition from an empty store through the PRD's own
endpoints. Nothing is mocked and the logical clock is the only source of time.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_RETRY_LIMIT_REACHED,
)
from test_helpers.assertions import (
    approx2,
    approx4,
    assert_activatable,
    assert_draft_activation,
    assert_instant_equals,
    assert_profile_axes,
    assert_task_counters,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    GOVERNANCE,
    GOVERNANCE_2,
    PRIVACY,
    STEWARD,
    make_destination_platform_headers,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_validate_batch_moves_received_to_validated(api):
    """A received batch of one perfect record scores the full 1.00, which clears the
    feed's completeness floor, so it is validated rather than quarantined.

    "Where the computed `dq_score` is at least the feed's `pii_completeness_floor` — inclusive at equality — the batch moves `RECEIVED` → `VALIDATED` and `validated_at` is stamped at the logical clock now."
    "Alongside it, `dq_failure_breakdown` is written as a map from component name to the count of records in which that component was present but malformed; components that were merely absent never appear in those counts."
    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."
    "A `REGISTERED` feed may nonetheless submit and validate batches; registration is enough to ingest, and the `ACTIVE` marker records that the feed has proved itself."

    Design: Corner/state_machines/validate_batch_moves_received_to_validated
    """
    fx.set_clock(api, CLOCK)
    env = fx.received_batch(
        api, [f.raw_record("V1", event_timestamp="2026-07-25T10:00:00Z")]
    )
    batch_id = env["batch"]["id"]
    assert env["batch"]["status"] == "RECEIVED"

    batch = validate_success(api.validate_batch(batch_id, ENGINEER), 200)

    assert batch["status"] == "VALIDATED"
    assert batch["dq_score"] == approx2(1.00)
    assert batch["valid_record_count"] == 1
    assert batch["invalid_record_count"] == 0
    assert batch["dq_failure_breakdown"] == {}
    assert_instant_equals(batch["validated_at"], CLOCK, "validated_at")

    feed = fx.reread_feed(api, env["feed"]["id"])
    assert feed["submitted_record_total"] == 1
    assert feed["valid_record_total"] == 1
    assert feed["dq_pass_rate"] == approx4(1.0000)
    assert feed["status"] == "REGISTERED"


def test_promote_before_validate_rejected(api):
    """Promotion is declared only out of VALIDATED, so promoting a batch that has
    never been scored is refused and mints nothing in the profile graph.

    "A `DataEngineer` promotes a `VALIDATED` batch whose feed is not `QUARANTINED`; the batch moves `VALIDATED` → `PROMOTED`, `promoted_at` is stamped at the logical clock now, and the batch's `version` increments by 1."
    "Rungs 21 through 26 are state and referential integrity: (21) the target's current status permits the requested transition per its lifecycle, else `ERR_INVALID_STATE`; (22) no profile named as a link endpoint, consent subject, suppression subject or erasure subject has `resolution_status` of `MERGED_AWAY`, else `ERR_PROFILE_MERGED_AWAY`; (23) the referenced feed's `status` is not `QUARANTINED` when submitting a batch, validating one, promoting one, or capturing a consent record that names it, else `ERR_SOURCE_SYSTEM_QUARANTINED`; (24) a rule named on link creation has `status` of `ENABLED`, else `ERR_MATCH_RULE_DISABLED`; (25) the destination's `status` is `ACTIVE` when creating, dispatching or resuming an activation against it, else `ERR_DESTINATION_INACTIVE`; (26) no profile referenced by the write has `privacy_status` of `DELETED`, else `ERR_PROFILE_DELETED`."

    Design: Corner/state_machines/promote_before_validate_rejected
    """
    fx.set_clock(api, CLOCK)
    env = fx.received_batch(
        api, [f.raw_record("U1", event_timestamp="2026-07-26T10:00:00Z")]
    )
    batch_id = env["batch"]["id"]

    validate_error(api.promote_batch(batch_id, ENGINEER), ERR_INVALID_STATE)

    batch = fx.reread_batch(api, batch_id)
    assert batch["status"] == "RECEIVED"
    assert batch["promoted_at"] is None
    assert batch["version"] == env["batch"]["version"]

    profiles, meta = validate_paginated(api.list_profiles(STEWARD, {"limit": 10, "offset": 0}))
    assert profiles == []
    assert meta["total_count"] == 0

    assert fx.reread_feed(api, env["feed"]["id"])["status"] == "REGISTERED"


def test_promote_activates_source_system_and_mints_profiles(api):
    """The first successful promotion of a two-record batch mints one profile per
    record and is what finally moves the feed out of REGISTERED.

    "A `DataEngineer` promotes a `VALIDATED` batch whose feed is not `QUARANTINED`; the batch moves `VALIDATED` → `PROMOTED`, `promoted_at` is stamped at the logical clock now, and the batch's `version` increments by 1."
    "Promotion takes no rule argument at all, and it succeeds even when no rule is enabled — in that case every valid record simply mints its own profile."
    "A feed reaches `ACTIVE` only when real data has flowed all the way through, which is to say on the first successful promotion of one of its batches — that promotion moves the feed `REGISTERED` → `ACTIVE` and increments the feed's `version`."
    "Every profile the promotion touched that is not `MERGED_AWAY` and that has no outstanding `PROPOSED` link becomes `RESOLVED`, moving `UNRESOLVED` → `RESOLVED`; a profile still carrying at least one `PROPOSED` link stays `UNRESOLVED`."

    Design: Corner/state_machines/promote_activates_source_system_and_mints_profiles
    """
    fx.set_clock(api, CLOCK)
    env = fx.validated_batch(
        api,
        [
            f.raw_record(
                "SE1",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
                event_timestamp="2026-07-27T10:00:00Z",
            ),
            f.raw_record(
                "SE2",
                first_name="Ben",
                last_name="Bravo",
                postal_code="20002",
                event_timestamp="2026-07-27T11:00:00Z",
            ),
        ],
        feed_overrides={"trust_tier": 4},
    )
    batch_id = env["batch"]["id"]
    feed_id = env["feed"]["id"]
    feed_code = env["feed"]["code"]

    batch = validate_success(api.promote_batch(batch_id, ENGINEER), 200)

    assert batch["status"] == "PROMOTED"
    assert_instant_equals(batch["promoted_at"], CLOCK, "promoted_at")
    assert batch["new_profile_count"] == 2
    assert batch["matched_deterministic_count"] == 0
    assert batch["matched_probabilistic_count"] == 0

    assert fx.reread_feed(api, feed_id)["status"] == "ACTIVE"

    profiles, meta = validate_paginated(
        api.list_profiles(STEWARD, {"origin_batch_id": batch_id, "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    for profile in profiles:
        assert_profile_axes(profile, "RESOLVED", "NORMAL")
        assert profile["source_record_count"] == 1
        assert profile["lifetime_value_cents"] == 0
        assert profile["origin_batch_id"] == batch_id

    assert profiles[0]["contributing_source_system_codes"] == [feed_code]
    assert profiles[0]["primary_source_system_id"] == feed_id


def test_requeue_on_validated_batch_rejected(api):
    """Requeuing is declared only out of QUARANTINED, so aiming it at a batch that
    passed validation is refused and clears none of the quality fields.

    "A quarantined batch is not lost. Requeuing it returns it to the front of the pipeline: while its `retry_round` is strictly below the retry budget of two rounds, requeuing moves it `QUARANTINED` → `RECEIVED`, increments `retry_round` by 1, clears `dq_score`, `dq_failure_breakdown`, `valid_record_count`, `invalid_record_count` and `validated_at`, recomputes the feed's totals and rate now that this batch is no longer in a counted status, and increments the batch's `version` by 1."
    "Rungs 21 through 26 are state and referential integrity: (21) the target's current status permits the requested transition per its lifecycle, else `ERR_INVALID_STATE`; (22) no profile named as a link endpoint, consent subject, suppression subject or erasure subject has `resolution_status` of `MERGED_AWAY`, else `ERR_PROFILE_MERGED_AWAY`; (23) the referenced feed's `status` is not `QUARANTINED` when submitting a batch, validating one, promoting one, or capturing a consent record that names it, else `ERR_SOURCE_SYSTEM_QUARANTINED`; (24) a rule named on link creation has `status` of `ENABLED`, else `ERR_MATCH_RULE_DISABLED`; (25) the destination's `status` is `ACTIVE` when creating, dispatching or resuming an activation against it, else `ERR_DESTINATION_INACTIVE`; (26) no profile referenced by the write has `privacy_status` of `DELETED`, else `ERR_PROFILE_DELETED`."

    Design: Corner/state_machines/requeue_on_validated_batch_rejected
    """
    fx.set_clock(api, CLOCK)
    env = fx.validated_batch(
        api,
        [f.raw_record("IF1", event_timestamp="2026-07-28T10:00:00Z")],
        feed_overrides={"channel_type": "WEB"},
    )
    batch_id = env["batch"]["id"]
    assert env["batch"]["status"] == "VALIDATED"
    assert env["batch"]["retry_round"] == 0

    validate_error(api.requeue_batch(batch_id, ENGINEER), ERR_INVALID_STATE)

    batch = fx.reread_batch(api, batch_id)
    assert batch["status"] == "VALIDATED"
    assert batch["retry_round"] == 0
    assert batch["dq_score"] == approx2(1.00)
    assert batch["valid_record_count"] == 1
    assert_instant_equals(batch["validated_at"], CLOCK, "validated_at")
    assert batch["version"] == env["batch"]["version"]


def test_new_activation_starts_in_draft(api):
    """Creating an activation against an approved segment leaves it in DRAFT with
    every audience and rate field unset, and touches no destination quota.

    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."
    "From `DRAFT` there is neither a refund nor an active-count change, because a draft never consumed quota and was never counted as active."
    "`active_activation_count` separately counts this segment's activations in `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."
    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Corner/state_machines/new_activation_starts_in_draft
    """
    fx.set_clock(api, CLOCK)
    destination = fx.register_destination(api, daily_hash_quota=300)
    segment = fx.approved_segment(api)

    activation = validate_success(
        api.create_activation(
            f.activation_payload(
                segment["id"],
                destination["id"],
                segment["version"],
                "2026-08-05T00:00:00Z",
                "2026-08-05T02:00:00Z",
            ),
            ANALYST,
        ),
        201,
    )

    assert_draft_activation(activation)
    assert activation["segment_id"] == segment["id"]
    assert activation["destination_id"] == destination["id"]

    reread_destination = fx.reread_destination(api, destination["id"])
    assert reread_destination["remaining_daily_hash_quota"] == 300
    assert reread_destination["daily_hash_quota"] == 300

    reread_segment = fx.reread_segment(api, segment["id"])
    assert reread_segment["active_activation_count"] == 0
    assert reread_segment["version"] == segment["version"] + 1


def test_retired_segment_rejects_submit_for_review(api):
    """Retirement is terminal, so the segment refuses a resubmission, a further
    governance decision and a second retirement alike.

    "Terminal states are absolute: a `REJECTED` or `PROMOTED` ingest batch, a `RETIRED` segment, a `TERMINATED` activation, a `VERIFIED` deletion request, an `ACKNOWLEDGED` vendor deletion task, a `MERGED_AWAY` profile on the resolution axis and a `DELETED` profile on the privacy axis accept nothing further."
    "Nothing accepts a trigger afterwards."
    "A submission from any other state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retired_segment_rejects_submit_for_review
    """
    fx.set_clock(api, CLOCK)
    segment = fx.approved_segment(api)
    segment_id = segment["id"]

    retired = validate_success(api.retire_segment(segment_id, GOVERNANCE), 200)
    assert retired["status"] == "RETIRED"

    validate_error(api.submit_segment_for_review(segment_id, ANALYST), ERR_INVALID_STATE)
    validate_error(
        api.decide_segment_governance(
            segment_id, f.governance_decision_payload("APPROVE", False), GOVERNANCE_2
        ),
        ERR_INVALID_STATE,
    )
    validate_error(api.retire_segment(segment_id, GOVERNANCE_2), ERR_INVALID_STATE)

    final = fx.reread_segment(api, segment_id)
    assert final["status"] == "RETIRED"
    assert final["active_activation_count"] == 0
    assert final["version"] == retired["version"]


def test_second_pause_on_paused_activation_rejected(api):
    """A paused activation refuses a second pause outright rather than treating the
    repeat as a no-op, so the dispatched hashes are refunded exactly once.

    "The platform never treats a repeated trigger as a silent no-op."
    "Firing the same transition twice — validating an already-validated batch, dispatching an already-dispatched activation, releasing an already-released suppression, acknowledging an already-acknowledged vendor task — is rejected with `ERR_INVALID_STATE` (HTTP 409) on the second attempt, because the entity's status no longer permits the transition."
    "Every arm sets `status` to `PAUSED` and writes `paused_reason`: `OPERATOR` for the explicit call, or `CONSENT_WITHDRAWN` or `GOVERNANCE_EXPIRED` for the respective cascades."
    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."

    Design: Corner/state_machines/second_pause_on_paused_activation_rejected
    """
    fx.set_clock(api, CLOCK)
    env = fx.delivering_activation_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    activation_id = env["activation"]["id"]
    destination_id = env["destination"]["id"]
    assert env["activation"]["status"] == "DISPATCHED"
    assert env["activation"]["dispatched_hash_count"] == 1
    assert env["destination"]["remaining_daily_hash_quota"] == 299

    paused = fx.pause(api, activation_id)
    assert paused["status"] == "PAUSED"
    assert paused["paused_reason"] == "OPERATOR"
    assert fx.reread_destination(api, destination_id)["remaining_daily_hash_quota"] == 300

    validate_error(api.pause_activation(activation_id, ANALYST), ERR_INVALID_STATE)

    after = fx.reread_activation(api, activation_id)
    assert after["status"] == "PAUSED"
    assert after["paused_reason"] == "OPERATOR"
    assert after["version"] == paused["version"]
    assert fx.reread_destination(api, destination_id)["remaining_daily_hash_quota"] == 300
    assert fx.reread_segment(api, env["segment"]["id"])["active_activation_count"] == 0


def test_quarantined_batch_requeue_returns_to_received(api):
    """A batch scoring exactly 0.60 against a 0.70 floor is quarantined, and
    requeuing it walks the platform's one genuine cycle back to RECEIVED.

    "Where the score is strictly below the floor, the batch moves `RECEIVED` → `QUARANTINED`, with `validated_at` stamped just the same."
    "A quarantined batch is not lost. Requeuing it returns it to the front of the pipeline: while its `retry_round` is strictly below the retry budget of two rounds, requeuing moves it `QUARANTINED` → `RECEIVED`, increments `retry_round` by 1, clears `dq_score`, `dq_failure_breakdown`, `valid_record_count`, `invalid_record_count` and `validated_at`, recomputes the feed's totals and rate now that this batch is no longer in a counted status, and increments the batch's `version` by 1."
    "This is the platform's one genuine cycle: `RECEIVED` → `QUARANTINED` → `RECEIVED`, bounded by the budget."
    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."
    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."

    Design: Corner/state_machines/quarantined_batch_requeue_returns_to_received
    """
    fx.set_clock(api, CLOCK)
    env = fx.received_batch(
        api,
        [
            f.raw_record(
                "CY1",
                phone_raw=None,
                loyalty_number=None,
                event_timestamp="2026-07-30T10:00:00Z",
            )
        ],
        feed_overrides={"channel_type": "SUPPORT"},
    )
    batch_id = env["batch"]["id"]
    feed_id = env["feed"]["id"]

    quarantined = fx.validate(api, batch_id)
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["dq_score"] == approx2(0.60)
    assert quarantined["valid_record_count"] == 1
    assert quarantined["invalid_record_count"] == 0
    assert_instant_equals(quarantined["validated_at"], CLOCK, "validated_at")

    requeued = validate_success(api.requeue_batch(batch_id, ENGINEER), 200)

    assert requeued["status"] == "RECEIVED"
    assert requeued["retry_round"] == 1
    assert requeued["dq_score"] is None
    assert requeued["validated_at"] is None
    assert requeued["version"] == quarantined["version"] + 1

    feed = fx.reread_feed(api, feed_id)
    assert feed["submitted_record_total"] == 0
    assert feed["valid_record_total"] == 0
    assert feed["dq_pass_rate"] == approx4(1.0000)
    assert feed["status"] == "REGISTERED"


def test_third_requeue_rejected_and_batch_driven_to_rejected(api):
    """Once the retry budget is spent the requeue call both fails and rejects the
    batch in the same breath, after which a further attempt is an ordinary refusal.

    "A requeue attempt on a batch whose `retry_round` has already reached two answers `ERR_RETRY_LIMIT_REACHED` (HTTP 409) **and, in that same call, drives the batch `QUARANTINED` → `REJECTED`** with `rejection_reason` set to `RETRY_LIMIT_REACHED` and the batch's `version` incremented by 1."
    "A fourth requeue, now aimed at a terminal batch, is an ordinary `ERR_INVALID_STATE`."

    Design: Corner/state_machines/third_requeue_rejected_and_batch_driven_to_rejected
    """
    fx.set_clock(api, CLOCK)
    env = fx.batch_at_retry_budget(api)
    batch_id = env["batch"]["id"]
    assert env["batch"]["status"] == "QUARANTINED"
    assert env["batch"]["retry_round"] == 2

    validate_error(api.requeue_batch(batch_id, ENGINEER), ERR_RETRY_LIMIT_REACHED)

    rejected = fx.reread_batch(api, batch_id)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "RETRY_LIMIT_REACHED"
    assert rejected["retry_round"] == 2
    assert rejected["version"] == env["batch"]["version"] + 1

    validate_error(api.requeue_batch(batch_id, ENGINEER), ERR_INVALID_STATE)

    final = fx.reread_batch(api, batch_id)
    assert final["status"] == "REJECTED"
    assert final["rejection_reason"] == "RETRY_LIMIT_REACHED"
    assert final["version"] == rejected["version"]


def test_deletion_request_becomes_partially_verified_when_task_times_out(api):
    """A vendor task carried past its acknowledgement deadline is timed out by the
    retention run, which leaves the parent request partially verified.

    "Each task is created `PENDING` and immediately advanced `PENDING` → `DISPATCHED` within the same call, with `dispatched_at` at the logical clock now, `attempt_count` at 1, and `ack_deadline_at` set to `dispatched_at` advanced by that destination's `deletion_ack_sla_hours` hours."
    "Step three times out every vendor task that is `DISPATCHED` and whose `ack_deadline_at` is at or before now, moving each `DISPATCHED` → `TIMED_OUT`; where a parent request in `PROPAGATING` is left with no `PENDING` or `DISPATCHED` child and at least one child that is `TIMED_OUT` or `FAILED`, it moves `PROPAGATING` → `PARTIALLY_VERIFIED`."
    "A partially verified request keeps its subject at `DELETION_PENDING` — partial downstream erasure never completes the tombstone, because the platform will not claim a subject was forgotten while a vendor has not confirmed it."
    "The request's five counters are derived from its children at all times: `total_vendor_task_count` is every task minted across all propagate calls, `pending_vendor_task_count` counts those in `PENDING` or `DISPATCHED`, and `acknowledged_vendor_task_count`, `failed_vendor_task_count` and `timed_out_vendor_task_count` count the three remaining statuses one for one."

    Design: Corner/state_machines/deletion_request_becomes_partially_verified_when_task_times_out
    """
    fx.set_clock(api, CLOCK)
    env = fx.propagating_erasure(api, member_count=2)
    request_id = env["request"]["id"]
    subject_id = env["subject"]["id"]

    assert env["request"]["status"] == "PROPAGATING"
    assert_task_counters(
        env["request"],
        total_vendor_task_count=1,
        pending_vendor_task_count=1,
        acknowledged_vendor_task_count=0,
        failed_vendor_task_count=0,
        timed_out_vendor_task_count=0,
    )
    task = env["tasks"][0]
    assert task["status"] == "DISPATCHED"
    assert task["attempt_count"] == 1
    assert_instant_equals(task["dispatched_at"], CLOCK, "dispatched_at")
    assert_instant_equals(task["ack_deadline_at"], "2026-08-04T00:00:00Z", "ack_deadline_at")

    fx.set_clock(api, "2026-08-04T01:00:00Z")
    run = validate_success(api.run_retention(ADMIN), 201)
    assert run["timed_out_vendor_task_count"] == 1
    assert run["partially_verified_deletion_request_count"] == 1

    timed_out = validate_success(api.get_vendor_task(task["id"], ADMIN), 200)
    assert timed_out["status"] == "TIMED_OUT"
    assert timed_out["attempt_count"] == 1

    request = fx.reread_deletion_request(api, request_id)
    assert request["status"] == "PARTIALLY_VERIFIED"
    assert request["verified_at"] is None
    assert_task_counters(
        request,
        total_vendor_task_count=1,
        pending_vendor_task_count=0,
        acknowledged_vendor_task_count=0,
        failed_vendor_task_count=0,
        timed_out_vendor_task_count=1,
    )

    subject = fx.reread_profile(api, subject_id)
    assert subject["privacy_status"] == "DELETION_PENDING"
    assert subject["email_norm"] is not None


def test_retire_segment_terminates_every_activation_and_refunds_quota(api):
    """Retiring a segment terminates both of its activations, but only the one that
    was delivering gives its hashes back, since a draft never held any.

    "Retirement sets `status` to `RETIRED`, forces `active_activation_count` to 0, and terminates **every** activation of the segment that is not already terminated — those in `DRAFT`, `DISPATCHED`, `ACTIVE`, `UNDERPERFORMING` or `PAUSED` — each moving to `TERMINATED` with `paused_reason` of `SEGMENT_RETIRED` and `terminated_at` stamped at the logical clock now."
    "Any activation that was still delivering, meaning it was `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`, has its `dispatched_hash_count` refunded to its destination."
    "From `DRAFT` there is neither a refund nor an active-count change, because a draft never consumed quota and was never counted as active."

    Design: Corner/state_machines/retire_segment_terminates_every_activation_and_refunds_quota
    """
    fx.set_clock(api, CLOCK)
    env = fx.activation_ready_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    segment_id = env["segment"]["id"]
    destination_a = env["destination"]["id"]
    activation_a = env["activation"]["id"]

    destination_b = fx.register_destination(api, daily_hash_quota=300)["id"]
    activation_b = fx.draft_activation(api, segment_id, destination_b)["id"]

    dispatched = fx.dispatch(api, activation_a)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_hash_count"] == 1
    assert fx.reread_destination(api, destination_a)["remaining_daily_hash_quota"] == 299
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 1
    assert fx.reread_activation(api, activation_b)["status"] == "DRAFT"

    retired = validate_success(api.retire_segment(segment_id, GOVERNANCE), 200)

    assert retired["status"] == "RETIRED"
    assert retired["active_activation_count"] == 0

    delivered = fx.reread_activation(api, activation_a)
    assert delivered["status"] == "TERMINATED"
    assert delivered["paused_reason"] == "SEGMENT_RETIRED"
    assert_instant_equals(delivered["terminated_at"], CLOCK, "terminated_at")

    drafted = fx.reread_activation(api, activation_b)
    assert drafted["status"] == "TERMINATED"
    assert drafted["paused_reason"] == "SEGMENT_RETIRED"
    assert_instant_equals(drafted["terminated_at"], CLOCK, "terminated_at")

    assert fx.reread_destination(api, destination_a)["remaining_daily_hash_quota"] == 300
    assert fx.reread_destination(api, destination_b)["remaining_daily_hash_quota"] == 300


def test_consent_opt_out_capture_pauses_delivering_activation(api):
    """A later opt-out outranks the opt-in that promotion materialised, which empties
    the only member's channel list and pauses the activation that was delivering.

    "Qualifying elections are ranked by `captured_at` descending — the most recent decision wins — then, where two elections were captured at the same instant, by the `trust_tier` of the capture feed descending, and finally by the election's own `created_at` ascending."
    "Rank one is the winner and is the **only** election in its group whose `status` is `ACTIVE`; every lower-ranked sibling carries rank two, three and so on with `status` of `SUPERSEDED`, each such displacement moving that record `ACTIVE` → `SUPERSEDED` and incrementing its `version`."
    "A channel is activatable for a subject only where its resolution is `OPT_IN`."
    "When a channel drops out of a subject's `activatable_channels`, every delivering activation whose destination uses that channel recomputes its audience, and an activation whose `audience_size` reaches 0 is paused with `paused_reason` of `CONSENT_WITHDRAWN` and its dispatched hashes refunded, as §3.9 sets out."
    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."

    Design: Corner/state_machines/consent_opt_out_capture_pauses_delivering_activation
    """
    fx.set_clock(api, CLOCK)
    env = fx.delivering_activation_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    activation_id = env["activation"]["id"]
    destination_id = env["destination"]["id"]
    segment_id = env["segment"]["id"]
    profile = env["profiles"][0]

    assert env["activation"]["status"] == "DISPATCHED"
    assert env["activation"]["audience_size"] == 1
    assert env["activation"]["dispatched_hash_count"] == 1
    assert env["destination"]["remaining_daily_hash_quota"] == 299
    assert_activatable(fx.reread_profile(api, profile["id"]), ["EMAIL"])

    live = fx.reread_profile(api, profile["id"])
    opt_out = validate_success(
        api.create_consent_record(
            f.consent_record_payload(
                profile["id"],
                env["feed"]["id"],
                live["version"],
                channel="EMAIL",
                purpose="MARKETING",
                consent_state="OPT_OUT",
                captured_at=CLOCK,
            ),
            PRIVACY,
        ),
        201,
    )

    assert opt_out["precedence_rank"] == 1
    assert opt_out["status"] == "ACTIVE"
    assert opt_out["consent_state"] == "OPT_OUT"

    elections, _ = validate_paginated(
        api.list_consent_records(
            STEWARD, {"profile_id": profile["id"], "limit": 50, "offset": 0}
        )
    )
    superseded = [e for e in elections if e["id"] != opt_out["id"]]
    assert superseded, "promotion should have materialised the opt-in election"
    for election in superseded:
        assert election["status"] == "SUPERSEDED"
        assert election["precedence_rank"] >= 2

    reread = fx.reread_profile(api, profile["id"])
    assert_activatable(reread, [])

    activation = fx.reread_activation(api, activation_id)
    assert activation["status"] == "PAUSED"
    assert activation["paused_reason"] == "CONSENT_WITHDRAWN"

    assert fx.reread_destination(api, destination_id)["remaining_daily_hash_quota"] == 300
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 0


def test_match_report_rolls_revenue_into_household_combined_value(api):
    """A match report carrying two conversions credits each profile's lifetime value
    and rolls both figures up into the household the two members share.

    "`gross_match_rate` divides `vendor_matched_count` by `dispatched_hash_count`, or is exactly 0.0000 where nothing was dispatched."
    "The effective rate routes the activation, inclusively at the boundary: at or above the destination's `min_match_rate` the activation becomes `ACTIVE`, and strictly below it becomes `UNDERPERFORMING`."
    "A report also appends its conversions to `attributed_conversions` — appended, never replaced, so the array accumulates across reports — recomputes `attributed_conversion_count` as the array's length, and cascades: each referenced profile's `lifetime_value_cents` increases by the reported `revenue_cents` and each such profile's household `combined_lifetime_value_cents` is recomputed."
    "`dominant_last_name` is the most frequent non-null `last_name` among those members, ties broken alphabetically ascending, and is null when every member's last name is null."
    "`combined_lifetime_value_cents` is the sum of the members' `lifetime_value_cents`."

    Design: Corner/state_machines/match_report_rolls_revenue_into_household_combined_value
    """
    fx.set_clock(api, CLOCK)
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "HH1",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
                address_line="12 Oak Street",
                event_timestamp="2026-07-31T10:00:00Z",
                consent_signals=list(f.EMAIL_OPT_IN),
            ),
            f.raw_record(
                "HH2",
                first_name="Bea",
                last_name="Alpha",
                postal_code="10001",
                address_line="12 Oak Street",
                event_timestamp="2026-07-31T11:00:00Z",
                consent_signals=list(f.EMAIL_OPT_IN),
            ),
        ],
    )
    first, second = env["profiles"][0], env["profiles"][1]
    household_id = first["household_id"]
    assert household_id is not None
    assert second["household_id"] == household_id

    household = fx.reread_household(api, household_id)
    assert household["status"] == "ACTIVE"
    assert household["member_count"] == 2
    assert household["dominant_last_name"] == "Alpha"
    assert household["combined_lifetime_value_cents"] == 0

    destination = fx.register_destination(api, daily_hash_quota=300)
    segment = fx.approved_segment(api, list(f.POSTAL_10001))
    activation = fx.draft_activation(api, segment["id"], destination["id"])
    dispatched = fx.dispatch(api, activation["id"])
    assert dispatched["audience_size"] == 2
    assert dispatched["dispatched_hash_count"] == 2

    reported = validate_success(
        api.report_match(
            activation["id"],
            f.match_report_payload(
                2,
                0,
                [
                    f.conversion(first["id"], "2026-08-01T09:00:00Z", 1000),
                    f.conversion(second["id"], "2026-08-01T09:30:00Z", 400),
                ],
            ),
            make_destination_platform_headers(destination["id"]),
        ),
        200,
    )

    assert reported["status"] == "ACTIVE"
    assert reported["gross_match_rate"] == approx4(1.0000)
    assert reported["effective_match_rate"] == approx4(1.0000)
    assert reported["attributed_conversion_count"] == 2

    assert fx.reread_profile(api, first["id"])["lifetime_value_cents"] == 1000
    assert fx.reread_profile(api, second["id"])["lifetime_value_cents"] == 400

    rolled_up = fx.reread_household(api, household_id)
    assert rolled_up["combined_lifetime_value_cents"] == 1400
    assert rolled_up["member_count"] == 2
    assert rolled_up["status"] == "ACTIVE"
    assert rolled_up["dominant_last_name"] == "Alpha"


def test_suppression_pauses_delivering_activation_but_not_draft_one(api):
    """A global opt-out empties the only member's channels, which pauses the
    activation that was delivering while the sibling draft is left untouched.

    "The four entry types differ only in breadth: `PRIVACY_DELETE`, `GLOBAL_OPT_OUT` and `LEGAL_HOLD` each suppress every channel, while `DO_NOT_SELL` suppresses the `ADVERTISING` channel alone."
    "The three narrow-purpose types move it `NORMAL` → `SUPPRESSED`; note that `DO_NOT_SELL` moves the axis to `SUPPRESSED` too, even though only the advertising channel is actually masked, because the subject is no longer in an unqualified normal state."
    "Creation stamps `created_by_user_id` with the acting `X-User-ID` — or with the literal string `system` for the entries minted by a retention run or by a deletion request — recomputes the subject's `activatable_channels` and `channel_engagement_score`, pauses every delivering activation whose audience lost this subject's channel with `paused_reason` of `CONSENT_WITHDRAWN` while refunding its quota, and increments both the entry's `version` and the subject's `version` by 1."
    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."

    Design: Corner/state_machines/suppression_pauses_delivering_activation_but_not_draft_one
    """
    fx.set_clock(api, CLOCK)
    env = fx.activation_ready_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    segment_id = env["segment"]["id"]
    destination_a = env["destination"]["id"]
    activation_a = env["activation"]["id"]
    subject = env["profiles"][0]

    destination_b = fx.register_destination(api, daily_hash_quota=300)["id"]
    activation_b = fx.draft_activation(api, segment_id, destination_b)["id"]

    dispatched = fx.dispatch(api, activation_a)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_hash_count"] == 1
    assert fx.reread_destination(api, destination_a)["remaining_daily_hash_quota"] == 299
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 1

    entry = validate_success(
        api.create_suppression_entry(
            f.suppression_entry_payload(
                subject["id"],
                entry_type="GLOBAL_OPT_OUT",
                reason_code="GLOBAL_UNSUBSCRIBE",
                effective_at=CLOCK,
            ),
            PRIVACY,
        ),
        201,
    )

    assert entry["status"] == "ACTIVE"
    assert entry["entry_type"] == "GLOBAL_OPT_OUT"

    suppressed = fx.reread_profile(api, subject["id"])
    assert_profile_axes(suppressed, "RESOLVED", "SUPPRESSED")
    assert_activatable(suppressed, [])

    paused = fx.reread_activation(api, activation_a)
    assert paused["status"] == "PAUSED"
    assert paused["paused_reason"] == "CONSENT_WITHDRAWN"

    untouched = fx.reread_activation(api, activation_b)
    assert untouched["status"] == "DRAFT"
    assert untouched["paused_reason"] is None
    assert untouched["dispatched_hash_count"] == 0

    assert fx.reread_destination(api, destination_a)["remaining_daily_hash_quota"] == 300
    assert fx.reread_destination(api, destination_b)["remaining_daily_hash_quota"] == 300
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 0
