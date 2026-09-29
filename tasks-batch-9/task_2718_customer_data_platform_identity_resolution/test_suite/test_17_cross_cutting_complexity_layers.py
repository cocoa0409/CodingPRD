"""Cross-cutting layers: optimistic concurrency on parent versions, the version
counter itself, and the cumulative data-quality rate threshold.

The three optimistic-concurrency guards each take a required parent version field
and answer a 412 on any mismatch, above every state and business check.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_STALE_DELETION_REQUEST_VERSION,
    ERR_STALE_PROFILE_VERSION,
    ERR_STALE_SEGMENT_VERSION,
)
from test_helpers.assertions import (
    approx2,
    approx4,
    assert_unchanged,
    assert_version_unchanged,
)
from test_helpers.test_users import ADMIN, ANALYST, GOVERNANCE, PRIVACY

POSTAL_CRITERION = f.criterion("postal_code", "EQ", "10001")


def test_consent_capture_with_stale_expected_profile_version_is_refused(api):
    """A suppression capture bumps the subject profile's version, so a consent
    capture written from the pre-suppression view is refused even though it never
    touched consent; refreshing the version makes the identical call succeed.

    PRD: "**Consent capture** — a request to create a consent record must carry `expected_profile_version`, holding the client's last observed `version` of the `Profile` named by `profile_id`. If that value does not equal the profile's current `version`, the request is rejected with `ERR_STALE_PROFILE_VERSION` (HTTP 412)."
    PRD: "The three narrow-purpose types move it `NORMAL` → `SUPPRESSED`; note that `DO_NOT_SELL` moves the axis to `SUPPRESSED` too, even though only the advertising channel is actually masked, because the subject is no longer in an unqualified normal state."
    PRD: "Creation stamps `created_by_user_id` with the acting `X-User-ID` — or with the literal string `system` for the entries minted by a retention run or by a deletion request — recomputes the subject's `activatable_channels` and `channel_engagement_score`, pauses every delivering activation whose audience lost this subject's channel with `paused_reason` of `CONSENT_WITHDRAWN` while refunding its quota, and increments both the entry's `version` and the subject's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/consent_capture_with_stale_expected_profile_version_rejected
    """
    fx.reset_clock(api)
    env = fx.single_profile(api)
    subject = env["profile"]
    stale_version = subject["version"]

    entry = fx.add_suppression(
        api,
        subject["id"],
        entry_type="DO_NOT_SELL",
        reason_code="OCC_BUMP",
        effective_at="2026-08-01T00:00:00Z",
    )
    assert entry["status"] == "ACTIVE"

    bumped = fx.reread_profile(api, subject["id"])
    assert bumped["privacy_status"] == "SUPPRESSED"
    assert bumped["version"] == stale_version + 1, (
        "the suppression capture increments the subject's version by exactly 1"
    )

    stale_capture = f.consent_record_payload(
        subject["id"],
        env["feed"]["id"],
        stale_version,
        captured_at="2026-08-01T00:00:00Z",
    )
    validate_error(
        api.create_consent_record(stale_capture, PRIVACY), ERR_STALE_PROFILE_VERSION
    )

    _, meta = validate_paginated(api.list_consent_records(ADMIN))
    assert meta["total_count"] == 0, "the refused capture persisted no election"

    fresh = fx.reread_profile(api, subject["id"])
    retry = f.consent_record_payload(
        subject["id"],
        env["feed"]["id"],
        fresh["version"],
        captured_at="2026-08-01T00:00:00Z",
    )
    created = get_success_data(
        api.create_consent_record(retry, PRIVACY), expected_status=201
    )
    assert created["status"] == "ACTIVE"


def test_activation_create_with_stale_expected_segment_version_is_refused(api):
    """Creating an activation advances the segment's version, so replaying the same
    expected_segment_version for a second activation is refused before any
    scheduling rung is reached.

    PRD: "**Activation creation** — a request to create an activation must carry `expected_segment_version`, holding the client's last observed `version` of the `Segment` named by `segment_id`. A mismatch with the segment's current `version` is rejected with `ERR_STALE_SEGMENT_VERSION` (HTTP 412)."
    PRD: "In all three cases the check is an equality comparison against the current stored `version`, evaluated after existence checks and before any state check."

    Design: Corner/cross_cutting_complexity_layers/activation_create_with_stale_expected_segment_version_rejected
    """
    fx.reset_clock(api)
    # cooldown_minutes 0 and a concurrency cap of 3 mean neither scheduling rung
    # could explain a refusal.
    destination = fx.register_destination(
        api,
        code="CC_OCC_DEST",
        daily_hash_quota=300,
        max_concurrent_activations=3,
    )
    segment = fx.approved_segment(
        api, [POSTAL_CRITERION], segment_overrides={"name": "Segment OCC Segment"}
    )
    stale_version = segment["version"]

    first = get_success_data(
        api.create_activation(
            f.activation_payload(
                segment["id"],
                destination["id"],
                stale_version,
                "2026-08-05T00:00:00Z",
                "2026-08-05T02:00:00Z",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    after_first = fx.reread_segment(api, segment["id"])
    assert after_first["version"] == stale_version + 1, (
        "the accepted create advances the segment it targets"
    )

    replay = f.activation_payload(
        segment["id"],
        destination["id"],
        stale_version,
        "2026-08-06T00:00:00Z",
        "2026-08-06T02:00:00Z",
    )
    validate_error(api.create_activation(replay, ANALYST), ERR_STALE_SEGMENT_VERSION)

    data, meta = validate_paginated(api.list_activations(ADMIN))
    assert meta["total_count"] == 1 and data[0]["id"] == first["id"]
    unchanged = fx.reread_segment(api, segment["id"])
    assert_version_unchanged(after_first, unchanged)

    retry = f.activation_payload(
        segment["id"],
        destination["id"],
        unchanged["version"],
        "2026-08-06T00:00:00Z",
        "2026-08-06T02:00:00Z",
    )
    second = get_success_data(api.create_activation(retry, ANALYST), expected_status=201)
    assert second["status"] == "DRAFT"


def test_propagate_with_stale_expected_deletion_request_version_is_refused(api):
    """A replayed propagate on an already-verified erasure answers the stale-version
    error rather than the terminal-state error, because the concurrency rung sits
    above every state check.

    PRD: "**Deletion propagation** — a request to propagate a deletion request must carry `expected_deletion_request_version`, holding the client's last observed `version` of that same `DeletionRequest`. A mismatch is rejected with `ERR_STALE_DELETION_REQUEST_VERSION` (HTTP 412)."
    PRD: "They sit *above* every state and business check, which means a stale version is reported even when the target's state would also have refused the call."
    PRD: "Where **zero** destinations qualify, there is nothing downstream to verify and the erasure completes inside the propagate call itself: `total_vendor_task_count` stays 0, the request moves `RECEIVED` → `VERIFIED`, `verified_at` is stamped, and the subject is tombstoned immediately."

    Design: Corner/cross_cutting_complexity_layers/propagate_with_stale_expected_deletion_request_version_rejected
    """
    fx.reset_clock(api)
    env = fx.pending_erasure(api)
    request = env["request"]
    stale_version = request["version"]

    verified = get_success_data(
        api.propagate_deletion_request(
            request["id"], f.propagate_payload(stale_version), PRIVACY
        ),
        expected_status=200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["total_vendor_task_count"] == 0
    assert verified["version"] == stale_version + 1

    validate_error(
        api.propagate_deletion_request(
            request["id"], f.propagate_payload(stale_version), PRIVACY
        ),
        ERR_STALE_DELETION_REQUEST_VERSION,
    )

    after = fx.reread_deletion_request(api, request["id"])
    assert after["status"] == "VERIFIED"
    assert_unchanged(verified, after, "verified_at", "total_vendor_task_count")
    assert_version_unchanged(verified, after)


def test_segment_version_advances_on_every_accepted_write_including_the_reject(api):
    """The version counter advances on each accepted write — including the rejection
    that walks the segment backwards to DRAFT — while a read and a refused write
    leave it alone.

    PRD: "`version` (integer): starts at 1 and increments by exactly 1 on every mutation of that resource."
    PRD: "Rejecting reverts the segment `PENDING_GOVERNANCE_REVIEW` → `DRAFT`, increments `rejection_count` by 1, forces `sensitive_use_approved` back to false, and **clears `submitted_by_user_id`** so that the next submission re-arms the segregation check against whoever resubmits."
    PRD: "A resource that is only *read* is never mutated: computed reads such as the per-channel consent projection, the segment performance report and the audience overlap report derive their output at read time and increment nothing."
    PRD: "Firing the same transition twice — validating an already-validated batch, dispatching an already-dispatched activation, releasing an already-released suppression, acknowledging an already-acknowledged vendor task — is rejected with `ERR_INVALID_STATE` (HTTP 409) on the second attempt, because the entity's status no longer permits the transition."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_to_segment
    """
    fx.reset_clock(api)
    segment = fx.draft_segment(api, [POSTAL_CRITERION], name="Version Ladder Segment")
    assert segment["version"] == 1, "a newly persisted resource starts at version 1"

    submitted = fx.submit_segment(api, segment["id"])
    assert submitted["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert submitted["version"] == 2

    rejected = fx.decide_segment(api, segment["id"], "REJECT", False)
    assert rejected["status"] == "DRAFT"
    assert rejected["rejection_count"] == 1
    assert rejected["version"] == 3, "the backwards rejection still consumed a version"

    resubmitted = fx.submit_segment(api, segment["id"])
    assert resubmitted["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert resubmitted["version"] == 4

    approved = fx.decide_segment(api, segment["id"], "APPROVE", False)
    assert approved["status"] == "APPROVED"
    assert approved["rejection_count"] == 1
    assert approved["version"] == 5

    read = fx.reread_segment(api, segment["id"])
    assert read["version"] == 5, "a read never advances the counter"

    validate_error(
        api.decide_segment_governance(
            segment["id"], f.governance_decision_payload("APPROVE", False), GOVERNANCE
        ),
        ERR_INVALID_STATE,
    )
    after_refusal = fx.reread_segment(api, segment["id"])
    assert after_refusal["version"] == 5, "refused writes never increment"
    assert after_refusal["status"] == "APPROVED"


def test_feed_quarantines_only_when_the_pass_rate_falls_strictly_below_the_floor(api):
    """Five in-window records at a pass rate exactly equal to the completeness floor
    do not quarantine the feed; one further invalid record drops the rate below the
    floor and fires the quarantine.

    PRD: "Under `WEIGHTED_COMPONENTS`, the score is the sum of the weights of the passing components, over a weight base that is always the full 1.00: an email that passes contributes 0.30, a phone 0.20, a loyalty number 0.20, a name pair 0.15 and a postal code 0.15 — the five weights summing to exactly 1.00, so email is worth twice postal code — and failing is again indistinguishable from being absent."
    PRD: "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."
    PRD: "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."
    PRD: "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."
    PRD: "Both boundaries are deliberate: exactly five in-window records is already enough evidence to act on, and a rate exactly equal to the floor is not a breach."

    Design: Corner/cross_cutting_complexity_layers/source_quarantines_when_dq_pass_rate_breaches_floor_at_min_sample
    """
    fx.reset_clock(api)
    feed = fx.register_feed(
        api,
        code="CC_RATE",
        display_name="Rate Threshold Feed",
        channel_type="WEB",
        trust_tier=3,
        pii_completeness_floor=0.60,
    )

    def sparse(external_id, event_timestamp):
        """Email and postal absent, so phone, loyalty and the name pair score 0.55."""
        return f.raw_record(
            external_id,
            email_raw=None,
            postal_code=None,
            event_timestamp=event_timestamp,
        )

    batch_a = fx.submit_batch(
        api,
        feed["id"],
        [
            f.raw_record("RT1", event_timestamp="2026-07-30T10:00:00Z"),
            f.raw_record("RT2", event_timestamp="2026-07-30T10:10:00Z"),
            f.raw_record("RT3", event_timestamp="2026-07-30T10:20:00Z"),
            sparse("RT4", "2026-07-30T10:30:00Z"),
            sparse("RT5", "2026-07-30T10:40:00Z"),
        ],
        batch_label="Rate Threshold Five",
    )
    batch_a = fx.validate(api, batch_a["id"])
    # (1.00 + 1.00 + 1.00 + 0.55 + 0.55) / 5 == 4.10 / 5
    assert batch_a["dq_score"] == approx2(0.82)
    assert batch_a["valid_record_count"] == 3
    assert batch_a["invalid_record_count"] == 2
    assert batch_a["status"] == "VALIDATED"

    feed_after_a = fx.reread_feed(api, feed["id"])
    assert feed_after_a["submitted_record_total"] == 5
    assert feed_after_a["valid_record_total"] == 3
    assert feed_after_a["dq_pass_rate"] == approx4(0.6000)
    assert feed_after_a["status"] == "REGISTERED", (
        "the sample is sufficient but a rate exactly equal to the floor is not a breach"
    )
    assert feed_after_a["quarantine_count"] == 0

    batch_b = fx.submit_batch(
        api,
        feed["id"],
        [sparse("RT6", "2026-07-30T10:50:00Z")],
        batch_label="Rate Threshold One More",
    )
    batch_b = fx.validate(api, batch_b["id"])
    assert batch_b["dq_score"] == approx2(0.55)
    assert batch_b["status"] == "QUARANTINED"

    feed_after_b = fx.reread_feed(api, feed["id"])
    assert feed_after_b["submitted_record_total"] == 6
    assert feed_after_b["valid_record_total"] == 3
    assert feed_after_b["dq_pass_rate"] == approx4(0.5000)
    assert feed_after_b["status"] == "QUARANTINED"
    assert feed_after_b["quarantine_count"] == 1

    assert fx.reread_batch(api, batch_a["id"])["status"] == "VALIDATED", (
        "the quarantine cascade only touches batches still in RECEIVED"
    )
