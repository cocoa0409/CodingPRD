"""One compliance flag walks the posting, its flight, its channel and the program's money."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import media_buyer_headers


def _active_flight_on_a_published_posting(api):
    """A delivering buy on a cleared, published posting; the channel has no credit at all."""
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=500000)
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    flight = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
    )
    fx.activate_flight(api, flight["id"])
    live_channel = fx.read_channel(api, channel["id"])
    assert live_channel["active_flight_count"] == 1, live_channel
    assert live_channel["credited_qualified_bp"] == 0, live_channel
    assert live_channel["pacing_status"] == "PACING_UNKNOWN", live_channel
    return program, family, channel, posting, flight


def test_flagging_a_published_posting_suspends_its_content_dimension(api):
    """PRD §2.7: "The first hop of the flag sets `compliance_status` to `FLAGGED` and
    `cleared_by_user_id` back to null."
    PRD §2.7: "When the flagged posting's `content_status` is `PUBLISHED`, the flag drives it
    `PUBLISHED → SUSPENDED` as hop two, recording `suspended_reason` as `COMPLIANCE_FLAG` — the
    only value that field ever takes."

    Design: Difficulty/transitive_cascade/compliance_flag_cascade_five_hops_from_review_to_idle_channel
    """
    _, _, _, posting, _ = _active_flight_on_a_published_posting(api)

    flagged = fx.flag_posting(api, posting["id"], note="salary range no longer accurate")

    assert flagged["compliance_status"] == "FLAGGED", flagged
    assert flagged["cleared_by_user_id"] is None, flagged
    assert flagged["content_status"] == "SUSPENDED", flagged
    assert flagged["suspended_reason"] == "COMPLIANCE_FLAG", flagged


def test_the_flag_suspends_the_flight_idles_the_channel_and_releases_the_money(api):
    """PRD §2.7: "Hop three follows because the posting is now suspended: every media flight
    pointing at this posting whose `state` is `ACTIVE` or `PAUSED_PACING` moves to
    `SUSPENDED_CONTENT`, with `release_reason` set to `COMPLIANCE_SUSPENSION` and `reserved_cents`
    set to 0."
    PRD §2.7: "Hop four follows because those flights left `ACTIVE`: each affected channel has its
    `active_flight_count` decremented once per departing flight that had been `ACTIVE`, and any
    channel whose count thereby reaches zero moves to `pacing_status` `IDLE` with `idle_since` set
    to the logical clock — unless the pacing calculation had already marked that channel
    `THROTTLED` earlier in this same request, in which case `THROTTLED` stands, per §2.10."
    PRD §2.7: "Hop five follows because each flight released its reservation: for every original
    `RESERVE` ledger entry of that flight, walked in ascending `sequence_no`, a mirroring `RELEASE`
    entry is written with the same `bucket` and the negated amount, which lowers
    `committed_budget_cents` on the program, lowers `reserved_cents` on the affected job families,
    and raises `available_budget_cents` correspondingly."

    Design: Difficulty/transitive_cascade/compliance_flag_cascade_five_hops_from_review_to_idle_channel
    """
    program, family, channel, posting, flight = _active_flight_on_a_published_posting(api)

    fx.flag_posting(api, posting["id"], note="salary range no longer accurate")

    suspended = fx.read_flight(api, flight["id"])
    assert suspended["state"] == "SUSPENDED_CONTENT", suspended
    assert suspended["release_reason"] == "COMPLIANCE_SUSPENSION", suspended
    a.assert_cents(suspended["reserved_cents"], 0, "reserved_cents")
    channel_row = fx.read_channel(api, channel["id"])
    assert channel_row["active_flight_count"] == 0, channel_row
    assert channel_row["pacing_status"] == "IDLE", channel_row
    assert channel_row["idle_since"] is not None, channel_row
    assert channel_row["idle_since"].startswith("2026-08-01T00:00:00"), channel_row
    entries = fx.ledger_entries_for_source(api, flight["id"])
    a.assert_ledger_buckets(
        entries,
        [
            ("FAMILY_DEDICATED", "RESERVE", 360500),
            ("FAMILY_DEDICATED", "RELEASE", -360500),
        ],
    )
    a.assert_ledger_entry(
        entries[1],
        bucket="FAMILY_DEDICATED",
        entry_type="RELEASE",
        delta_cents=-360500,
        reason="FLIGHT_COMPLIANCE_SUSPENSION",
        source_type="MEDIA_FLIGHT",
        source_id=flight["id"],
    )
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=0,
        available_budget_cents=500000,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=0,
        dedicated_available_cents=500000,
    )


def test_a_suspended_flight_is_never_resumable_while_its_posting_stays_flagged(api):
    """PRD §2.9: "25. `compliance_status` must be `CLEARED` before publishing a posting, before
    activating or resuming a flight pointing at it, and before an application on it is submitted,
    else `ERR_POSTING_COMPLIANCE_NOT_CLEARED` (409)."
    PRD §2.9: "31. A posting's `content_status` must be `PUBLISHED` before a flight on it is
    activated or resumed and before an application on it is submitted, else
    `ERR_POSTING_NOT_PUBLISHED` (409)."
    PRD §2.7: "Those flights remain in `SUSPENDED_CONTENT` and each must be resumed explicitly by a
    buyer, which re-runs the budget waterfall from scratch."

    Design: Difficulty/transitive_cascade/compliance_flag_cascade_five_hops_from_review_to_idle_channel
    """
    program, family, channel, posting, flight = _active_flight_on_a_published_posting(api)
    fx.flag_posting(api, posting["id"], note="salary range no longer accurate")

    refused = api.resume_media_flight(flight["id"], media_buyer_headers())

    validate_error(refused, ApiErrorId.POSTING_COMPLIANCE_NOT_CLEARED, 409)
    unchanged = fx.read_flight(api, flight["id"])
    assert unchanged["state"] == "SUSPENDED_CONTENT", unchanged
    assert unchanged["release_reason"] == "COMPLIANCE_SUSPENSION", unchanged
    a.assert_cents(unchanged["reserved_cents"], 0, "reserved_cents")
    channel_row = fx.read_channel(api, channel["id"])
    assert channel_row["active_flight_count"] == 0, channel_row
    assert channel_row["pacing_status"] == "IDLE", channel_row
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=0,
        available_budget_cents=500000,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=0,
        dedicated_available_cents=500000,
    )
