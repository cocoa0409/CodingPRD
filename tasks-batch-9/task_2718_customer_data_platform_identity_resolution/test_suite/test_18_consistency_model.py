"""Immediate consistency: a write's own response already carries every field it
derived, and the neighbours it touched are already correct on the very next read.

Nothing in this platform settles after the fact, so no test here waits, retries or
re-triggers anything to make a derived figure appear.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant_equals, assert_quota_conserved
from test_helpers.test_users import ANALYST

POSTAL_CRITERION = f.criterion("postal_code", "EQ", "10001")


def test_dispatch_response_already_carries_the_audience_counts_and_the_quota(api):
    """One dispatch over two candidates of whom one is reachable on EMAIL returns
    all four audience counts in its own body, and the destination and segment reads
    that follow are already reconciled — reading them twice changes nothing.

    PRD: "It is a deterministic, immediately-consistent service: there is no eventual convergence, no background worker, and no wall-clock dependency."
    PRD: "Resolution then proceeds in four counts. `candidate_count` is the size of the segment's member set at this instant. The audience is those candidates whose `activatable_channels` contains the destination's `channel`, and `audience_size` is its size. `suppressed_count` is `candidate_count` less `audience_size` — the members removed by consent or suppression. `dispatched_hash_count` is the number of audience members whose required identifier, selected by the destination's `hashing_algorithm`, is non-null."
    PRD: "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."
    PRD: "A channel is activatable for a subject only where its resolution is `OPT_IN`."
    PRD: "`active_activation_count` separately counts this segment's activations in `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    Design: Corner/consistency_model/dispatch_response_shows_audience_and_quota_in_the_same_response
    """
    fx.reset_clock(api)

    # Two profiles in the same postal code: one opted in to email marketing at
    # ingest, one opted out, so the segment has two candidates and one reachable
    # member.
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "IC1",
                event_timestamp="2026-07-30T10:00:00Z",
                consent_signals=[f.consent_signal("EMAIL", "MARKETING", "OPT_IN")],
            ),
            f.raw_record(
                "IC2",
                event_timestamp="2026-07-30T10:10:00Z",
                consent_signals=[f.consent_signal("EMAIL", "MARKETING", "OPT_OUT")],
            ),
        ],
        feed_overrides={
            "code": "CM_IMMED",
            "display_name": "Immediate Consistency Feed",
            "channel_type": "TRANSACTIONS",
            "trust_tier": 3,
        },
    )
    profiles = env["profiles"]
    assert len(profiles) == 2, "setup expected two distinct minted profiles"
    emailable = [p for p in profiles if "EMAIL" in p["activatable_channels"]]
    assert len(emailable) == 1, (
        "only the opted-in subject may be reachable on EMAIL, got "
        f"{[p['activatable_channels'] for p in profiles]}"
    )
    assert emailable[0]["email_norm"] is not None, (
        "the reachable member must carry the identifier the hashing contract needs"
    )

    destination = fx.register_destination(
        api,
        code="CM_IMMED_DEST",
        platform_kind="ADVERTISING",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        min_audience_size=1,
        min_match_rate=0.10,
    )
    assert destination["remaining_daily_hash_quota"] == 300

    segment = fx.approved_segment(
        api,
        [POSTAL_CRITERION],
        segment_overrides={"name": "Immediate Consistency Segment"},
    )
    assert segment["member_count"] == 2
    assert segment["active_activation_count"] == 0

    activation = fx.draft_activation(
        api,
        segment["id"],
        destination["id"],
        "2026-08-05T00:00:00Z",
        "2026-08-05T02:00:00Z",
    )

    dispatched = get_success_data(
        api.dispatch_activation(activation["id"], ANALYST), expected_status=200
    )
    # Every derived figure is present in the body of the call that produced it.
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["candidate_count"] == 2
    assert dispatched["audience_size"] == 1
    assert dispatched["suppressed_count"] == 1
    assert dispatched["dispatched_hash_count"] == 1
    assert_instant_equals(
        dispatched["dispatched_at"], "2026-08-01T00:00:00Z", "dispatched_at"
    )

    # The neighbours the dispatch touched are already correct on the first read.
    destination_read = fx.reread_destination(api, destination["id"])
    assert destination_read["remaining_daily_hash_quota"] == 299
    assert_quota_conserved(destination_read, 1)

    segment_read = fx.reread_segment(api, segment["id"])
    assert segment_read["member_count"] == 2
    assert segment_read["active_activation_count"] == 1

    # Reading again settles nothing further: there is no convergence step.
    assert fx.reread_destination(api, destination["id"]) == destination_read
    assert fx.reread_segment(api, segment["id"]) == segment_read
    assert fx.reread_activation(api, activation["id"]) == dispatched
