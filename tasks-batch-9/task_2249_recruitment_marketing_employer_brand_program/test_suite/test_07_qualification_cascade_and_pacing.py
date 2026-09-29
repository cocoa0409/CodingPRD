"""Qualification drives pacing: the five-hop cascade and the throttle boundary."""
from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _screened_application_on_an_active_flight(api, spend_cents=0):
    """A live buy on a dedicated-funded family, with one screened application behind it."""
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
    if spend_cents:
        fx.record_spend(api, flight["id"], spend_cents, "2026-08-01")
    fx.move_clock(api, "2026-08-02T00:00:00Z")
    application = fx.start_application(api, posting["id"])
    touchpoint = fx.add_touchpoint(
        api,
        application["id"],
        channel["id"],
        "2026-08-01T12:00:00Z",
        media_flight_id=flight["id"] if spend_cents else None,
        media_cost_cents=spend_cents,
    )
    fx.submit_application(api, application["id"])
    fx.screen_application(api, application["id"])
    return program, family, channel, posting, flight, application, touchpoint


def test_qualification_credits_the_touchpoint_its_channel_and_its_flight(api):
    """PRD §3.6: "Hop one writes the computed `credit_bp` onto every eligible touchpoint and
    records the outcome on the application: `eligible_touch_count` becomes the number of
    touchpoints in the input set, `attribution_model_applied` freezes the program's
    `attribution_model` value as it stood at this moment, and `attributed_credit_bp_total` becomes
    10,000."
    PRD §3.6: "Hop two follows because those credits changed: each channel's
    `credited_qualified_bp` rises by the `credit_bp` of each of its touchpoints, and each flight's
    `qualified_credit_bp` rises by the `credit_bp` of the touchpoints whose `media_flight_id`
    names it."

    Design: Difficulty/transitive_cascade/qualification_cascade_five_hops_from_decide_to_budget_release
    """
    _, _, channel, _, flight, application, touchpoint = _screened_application_on_an_active_flight(
        api, spend_cents=20000
    )

    decided = fx.decide_application(api, application["id"], "QUALIFIED")

    assert decided["status"] == "QUALIFIED", decided
    assert decided["eligible_touch_count"] == 1, decided
    assert decided["attributed_credit_bp_total"] == 10000, decided
    assert decided["attribution_model_applied"] == "LINEAR", decided
    assert fx.read_touchpoint(api, touchpoint["id"])["credit_bp"] == 10000
    assert fx.read_channel(api, channel["id"])["credited_qualified_bp"] == 10000
    assert fx.read_flight(api, flight["id"])["qualified_credit_bp"] == 10000


def test_qualification_throttles_the_channel_and_releases_the_reservation(api):
    """PRD §3.5: "When `credited_qualified_bp` is positive, `cpqa_cents` is the channel's
    `spent_cents` multiplied by ten thousand, divided by `credited_qualified_bp`, and rounded half
    up to a whole cent. The pacing threshold is the channel's `blended_target_cents` multiplied by
    12 and divided by 10 — a 20 percent tolerance above target — and rounded half up to a whole
    cent. `pacing_status` becomes `THROTTLED` when `cpqa_cents` is **strictly greater** than that
    threshold, and `ON_TARGET` otherwise; a channel sitting exactly on its threshold is
    `ON_TARGET`."
    PRD §3.6: "Hop four follows for any channel that just became `THROTTLED`: every flight on it
    whose `state` is `ACTIVE` moves to `PAUSED_PACING` with `release_reason` `PACING_THROTTLE` and
    `reserved_cents` 0."
    PRD §3.6: "Hop five follows because those flights released their reservations: mirroring
    `RELEASE` ledger entries are written, lowering the program's `committed_budget_cents` and the
    families' `reserved_cents` and raising `available_budget_cents`."

    Design: Difficulty/transitive_cascade/qualification_cascade_five_hops_from_decide_to_budget_release
    """
    program, family, channel, _, flight, application, _ = _screened_application_on_an_active_flight(
        api, spend_cents=20000
    )

    fx.decide_application(api, application["id"], "QUALIFIED")

    channel_row = fx.read_channel(api, channel["id"])
    a.assert_cents(channel_row["blended_target_cents"], 15000, "blended_target_cents")
    a.assert_cents(channel_row["cpqa_cents"], 20000, "cpqa_cents")
    assert channel_row["pacing_status"] == "THROTTLED", channel_row
    flight_row = fx.read_flight(api, flight["id"])
    assert flight_row["state"] == "PAUSED_PACING", flight_row
    assert flight_row["release_reason"] == "PACING_THROTTLE", flight_row
    a.assert_cents(flight_row["reserved_cents"], 0, "reserved_cents")
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
        reason="FLIGHT_PACING_THROTTLE",
        source_type="MEDIA_FLIGHT",
        source_id=flight["id"],
    )
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        0,
        "committed_budget_cents",
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=0,
        dedicated_available_cents=500000,
    )


def test_a_channel_emptied_by_its_own_throttle_stays_throttled_and_never_idles(api):
    """PRD §2.10: "When a flight departure drives a channel's `active_flight_count` to zero, the
    channel's `pacing_status` becomes `IDLE` and `idle_since` records the logical-clock instant at
    which that happened — *but only if* the pacing calculation did not already set that channel to
    `THROTTLED` earlier in the same request."
    PRD §2.10: "A channel that was throttled and whose last active flight was then paused
    *because* of that throttle stays `THROTTLED`, and its `idle_since` stays null."
    PRD §3.6: "On top of the cascade, the posting's `qualified_count` rises by 1 and the program's
    `last_attribution_recompute_at` is set to the logical clock."

    Design: Difficulty/transitive_cascade/qualification_cascade_five_hops_from_decide_to_budget_release
    """
    program, _, channel, posting, _, application, _ = _screened_application_on_an_active_flight(
        api, spend_cents=20000
    )

    fx.decide_application(api, application["id"], "QUALIFIED")

    channel_row = fx.read_channel(api, channel["id"])
    assert channel_row["active_flight_count"] == 0, channel_row
    assert channel_row["pacing_status"] == "THROTTLED", channel_row
    assert channel_row["idle_since"] is None, channel_row
    assert fx.read_posting(api, posting["id"])["qualified_count"] == 1
    program_row = fx.read_program(api, program["id"])
    assert program_row["last_attribution_recompute_at"] is not None, program_row
    assert program_row["last_attribution_recompute_at"].startswith("2026-08-02T00:00:00"), (
        program_row
    )


def _qualified_application_on_an_unspent_flight(api):
    """A live buy whose channel already carries 10,000 credited basis points and no spend at all."""
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
    fx.move_clock(api, "2026-08-02T00:00:00Z")
    application = fx.start_application(api, posting["id"], "boundary@example.com")
    fx.add_touchpoint(
        api,
        application["id"],
        channel["id"],
        "2026-08-01T12:00:00Z",
        media_flight_id=flight["id"],
    )
    fx.submit_application(api, application["id"])
    fx.screen_application(api, application["id"])
    fx.decide_application(api, application["id"], "QUALIFIED")
    before = fx.read_channel(api, channel["id"])
    assert before["credited_qualified_bp"] == 10000, before
    a.assert_cents(before["blended_target_cents"], 15000, "blended_target_cents")
    a.assert_cents(before["cpqa_cents"], 0, "cpqa_cents")
    assert before["pacing_status"] == "ON_TARGET", before
    assert before["active_flight_count"] == 1, before
    return program, family, channel, flight


def test_spend_that_lands_exactly_on_the_pacing_threshold_stays_on_target(api):
    """PRD §3.5: "The pacing threshold is the channel's `blended_target_cents` multiplied by 12 and
    divided by 10 — a 20 percent tolerance above target — and rounded half up to a whole cent."
    PRD §3.5: "`pacing_status` becomes `THROTTLED` when `cpqa_cents` is **strictly greater** than
    that threshold, and `ON_TARGET` otherwise; a channel sitting exactly on its threshold is
    `ON_TARGET`."
    PRD §3.5: "A successful record raises the flight's `spent_cents` and the channel's
    `spent_cents` by `amount_cents`, then re-runs the channel's blended target and
    cost-per-qualified-applicant calculations."

    Design: Difficulty/boundary_precision_check/cpqa_exactly_at_pacing_threshold_stays_on_target_one_cent_over_throttles
    """
    program, family, channel, flight = _qualified_application_on_an_unspent_flight(api)

    spent = fx.record_spend(api, flight["id"], 18000, "2026-08-02")

    channel_row = fx.read_channel(api, channel["id"])
    a.assert_cents(channel_row["spent_cents"], 18000, "spent_cents")
    a.assert_cents(channel_row["blended_target_cents"], 15000, "blended_target_cents")
    a.assert_cents(channel_row["cpqa_cents"], 18000, "cpqa_cents")
    assert channel_row["pacing_status"] == "ON_TARGET", channel_row
    assert channel_row["active_flight_count"] == 1, channel_row
    assert spent["state"] == "ACTIVE", spent
    a.assert_cents(spent["spent_cents"], 18000, "spent_cents")
    a.assert_cents(spent["reserved_cents"], 360500, "reserved_cents")
    assert spent["release_reason"] is None, spent
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        360500,
        "committed_budget_cents",
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=360500,
        dedicated_available_cents=139500,
    )


def test_one_cent_past_the_pacing_threshold_pauses_the_flight_and_frees_its_budget(api):
    """PRD §3.5: "When a spend record or an attribution run pushes a channel into `THROTTLED`,
    every flight on that channel whose `state` is `ACTIVE` is immediately moved to
    `PAUSED_PACING`, with `release_reason` set to `PACING_THROTTLE` and `reserved_cents` set to
    0."
    PRD §3.5: "Each paused flight then writes one mirroring `RELEASE` ledger entry per original
    `RESERVE` entry of that flight — same `bucket`, negated `delta_cents`, walked in ascending
    `sequence_no` of the originals, with `reason` `FLIGHT_PACING_THROTTLE` — which lowers the
    program's `committed_budget_cents` and the family's `reserved_cents` and correspondingly raises
    `available_budget_cents` and `dedicated_available_cents`."
    PRD §3.5: "The channel's `active_flight_count` is decremented once per departing flight, and
    the channel nonetheless stays `THROTTLED` rather than becoming `IDLE`, because the throttle
    verdict was computed earlier in the same request and outranks the idle verdict per §2.10."

    Design: Difficulty/boundary_precision_check/cpqa_exactly_at_pacing_threshold_stays_on_target_one_cent_over_throttles
    """
    program, family, channel, flight = _qualified_application_on_an_unspent_flight(api)
    fx.record_spend(api, flight["id"], 18000, "2026-08-02")

    throttled = fx.record_spend(api, flight["id"], 1, "2026-08-02")

    channel_row = fx.read_channel(api, channel["id"])
    a.assert_cents(channel_row["cpqa_cents"], 18001, "cpqa_cents")
    assert channel_row["pacing_status"] == "THROTTLED", channel_row
    assert channel_row["active_flight_count"] == 0, channel_row
    assert channel_row["idle_since"] is None, channel_row
    assert throttled["state"] == "PAUSED_PACING", throttled
    assert throttled["release_reason"] == "PACING_THROTTLE", throttled
    a.assert_cents(throttled["reserved_cents"], 0, "reserved_cents")
    a.assert_cents(throttled["spent_cents"], 18001, "spent_cents")
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
        reason="FLIGHT_PACING_THROTTLE",
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
