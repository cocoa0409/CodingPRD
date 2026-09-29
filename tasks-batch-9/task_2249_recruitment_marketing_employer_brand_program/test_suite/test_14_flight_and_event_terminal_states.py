"""Terminal states that absorb every further call, and the one release that writes no ledger row."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    community_manager_headers,
    media_buyer_headers,
    persona_researcher_headers,
)


def test_a_cancelled_flight_absorbs_cancel_spend_and_activate_without_moving_money(api):
    """PRD §2.9: "16. A flight's `state` must permit the requested transition — activation requires
    `RESERVED` (`ERR_FLIGHT_NOT_RESERVED`), resumption requires `PAUSED_PACING` or
    `SUSPENDED_CONTENT` (`ERR_FLIGHT_NOT_RESUMABLE`), completion requires `ACTIVE` or
    `PAUSED_PACING` (`ERR_FLIGHT_NOT_COMPLETABLE`), cancellation requires a non-terminal flight and
    spend recording requires `ACTIVE` or `PAUSED_PACING`, both rejecting a `COMPLETED` or
    `CANCELLED` flight with `ERR_FLIGHT_ALREADY_TERMINAL` — all 409."
    PRD §3.5: "Cancellation sets `release_reason` to `CANCELLED` and `reserved_cents` to 0, and
    writes one mirroring `RELEASE` ledger entry per outstanding `RESERVE` entry of the flight — same
    `bucket`, negated `delta_cents`, ascending `sequence_no` of the originals, `reason`
    `FLIGHT_CANCELLED` — so that the program's `committed_budget_cents` and the family's
    `reserved_cents` return to exactly their pre-reservation values while `available_budget_cents`
    and `dedicated_available_cents` rise by exactly the released amounts."
    PRD §3.5: "`CANCELLED` is terminal."

    Design: Corner/state_machines/spending_on_a_cancelled_flight_is_rejected_because_the_state_is_terminal
    """
    program = fx.create_program(api, pool_job_board_cents=1000000)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    flight = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-05",
        end_date="2026-08-10",
        daily_cap_cents=50000,
    )
    cancelled = fx.cancel_flight(api, flight["id"], reason="plan change")

    recancelled = api.cancel_media_flight(
        flight["id"], f.cancel_reason_payload("again"), media_buyer_headers()
    )
    spent = api.spend_media_flight(
        flight["id"], f.spend_payload(1000, "2026-08-06"), media_buyer_headers()
    )
    reactivated = api.activate_media_flight(flight["id"], media_buyer_headers())

    validate_error(recancelled, ApiErrorId.FLIGHT_ALREADY_TERMINAL, 409)
    validate_error(spent, ApiErrorId.FLIGHT_ALREADY_TERMINAL, 409)
    validate_error(reactivated, ApiErrorId.FLIGHT_NOT_RESERVED, 409)
    assert cancelled["state"] == "CANCELLED", cancelled
    assert cancelled["release_reason"] == "CANCELLED", cancelled
    a.assert_cents(cancelled["reserved_cents"], 0, "reserved_cents")
    settled = fx.read_flight(api, flight["id"])
    assert settled["state"] == "CANCELLED", settled
    a.assert_cents(settled["spent_cents"], 0, "spent_cents")
    entries = fx.ledger_entries_for_source(api, flight["id"])
    assert len(entries) == 2, entries
    a.assert_releases_mirror_reserves(
        [e for e in entries if e["entry_type"] == "RESERVE"],
        [e for e in entries if e["entry_type"] == "RELEASE"],
    )
    a.assert_ledger_entry(
        entries[1],
        bucket=entries[0]["bucket"],
        entry_type="RELEASE",
        delta_cents=-entries[0]["delta_cents"],
        reason="FLIGHT_CANCELLED",
        source_type="MEDIA_FLIGHT",
        source_id=flight["id"],
    )
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=0,
        available_budget_cents=1000000,
    )


def test_completing_an_event_keeps_the_reservation_and_refuses_the_boundary_instant(api):
    """PRD §3.9: "On success, one `RESERVE` ledger entry is written per drawn bucket with
    `source_type` `EVENT_PRESENCE`, `source_id` equal to the presence's `id` and `reason`
    `EVENT_RESERVATION`; `reserved_cents` becomes `booth_cost_cents`, `confirmed_at` becomes the
    logical clock, the presence moves `PLANNED → CONFIRMED`, the program's
    `committed_budget_cents` and the family's `reserved_cents` rise accordingly, and the program's
    `version` advances by 1 alongside the presence's own."
    PRD §3.9: "The presence must be in `CONFIRMED`, refused otherwise with
    `ERR_PRESENCE_NOT_CONFIRMED`, and the logical clock must be **strictly after** `end_at`,
    refused otherwise with `ERR_EVENT_WINDOW_OPEN` — note the contrast with flight completion, which
    is permitted at the boundary instant."
    PRD §3.9: "Completion moves the presence `CONFIRMED → COMPLETED` and deliberately leaves
    `reserved_cents` at `booth_cost_cents`, writing no ledger entry at all: the reservation has
    converted into actual spend and the money is genuinely gone."
    PRD §2.6: "At the family level, `reserved_cents` is the sum of `delta_cents` over that family's
    entries whose `bucket` is `FAMILY_DEDICATED`, and `dedicated_available_cents` is
    `dedicated_budget_cents` less `reserved_cents`."

    Design: Corner/state_machines/event_completion_converts_the_reservation_into_spend_without_a_ledger_row
    """
    program = fx.create_program(api, flex_reserve_cents=500000)
    family = fx.create_job_family(api, program["id"])
    presence = fx.plan_presence(
        api,
        program["id"],
        family["id"],
        venue_code="CAMPUS-A",
        start_at="2026-08-19T09:00:00Z",
        end_at="2026-08-20T18:00:00Z",
        booth_cost_cents=200000,
    )
    confirmed = fx.confirm_presence(api, presence["id"])
    fx.move_clock(api, "2026-08-20T18:00:00Z")

    at_the_boundary = api.complete_event_presence(presence["id"], media_buyer_headers())
    fx.move_clock(api, "2026-08-20T18:00:01Z")
    one_second_later = api.complete_event_presence(presence["id"], media_buyer_headers())

    a.assert_cents(confirmed["reserved_cents"], 200000, "reserved_cents")
    assert confirmed["confirmed_at"] is not None, confirmed
    reservation = fx.ledger_entries_for_source(api, presence["id"])
    a.assert_ledger_buckets(reservation, [("FLEX_RESERVE", "RESERVE", 200000)])
    a.assert_ledger_entry(
        reservation[0],
        bucket="FLEX_RESERVE",
        entry_type="RESERVE",
        delta_cents=200000,
        reason="EVENT_RESERVATION",
        source_type="EVENT_PRESENCE",
        source_id=presence["id"],
    )
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        200000,
        "committed_budget_cents",
    )
    funding_family = fx.read_job_family(api, family["id"])
    a.assert_cents(funding_family["reserved_cents"], 0, "family reserved_cents")
    a.assert_cents(
        funding_family["dedicated_available_cents"], 0, "dedicated_available_cents"
    )
    validate_error(at_the_boundary, ApiErrorId.EVENT_WINDOW_OPEN, 409)
    completed = validate_success(one_second_later, 200)
    assert completed["state"] == "COMPLETED", completed
    a.assert_cents(completed["reserved_cents"], 200000, "reserved_cents")
    assert fx.ledger_entries_for_source(api, presence["id"]) == reservation


def test_each_created_row_opens_at_the_label_its_own_machine_declares(api):
    """PRD §3.3: "A new persona is in state `DRAFT` with an empty `channel_mix` array,
    `mix_confidence_pct` 0, `signal_count` 0, `revision_count` 0, `reviewed_by_user_id` and
    `last_review_note` null, and `drafted_by_user_id` set to the acting `X-User-ID` — the value the
    later two-person rule will compare against."
    PRD §3.7: "A new campaign is in `state` `DRAFT` with `scheduled_for` and `dispatched_at` null
    and `audience_size`, `sent_count`, `suppressed_consent_count` and `suppressed_frequency_count`
    all 0."
    PRD §3.9: "A newly planned presence is in `state` `PLANNED` with `reserved_cents` 0 and
    `confirmed_at` null, and no budget is committed at this stage."

    Design: Corner/state_machines/newly_created_rows_open_in_their_declared_initial_states
    """
    program = fx.create_program(api, send_quota_total=50)
    family = fx.create_job_family(api, program["id"])

    persona = validate_success(
        api.create_candidate_persona(
            {"job_family_id": family["id"], "name": "Backend IC"}, persona_researcher_headers()
        ),
        201,
    )
    campaign = validate_success(
        api.create_nurture_campaign(
            {
                "program_id": program["id"],
                "job_family_id": family["id"],
                "name": "August Warm-up",
                "max_sends": 10,
            },
            community_manager_headers(),
        ),
        201,
    )
    review = validate_success(
        api.create_employer_review(
            {
                "program_id": program["id"],
                "platform": "INDEED",
                "external_ref": "in-1",
                "rating": 3,
                "posted_at": "2026-07-31T00:00:00Z",
            },
            community_manager_headers(),
        ),
        201,
    )
    presence = validate_success(
        api.create_event_presence(
            f.presence_payload(
                program["id"],
                family["id"],
                venue_code="CAMPUS-B",
                start_at="2026-09-10T09:00:00Z",
                end_at="2026-09-10T17:00:00Z",
                booth_cost_cents=50000,
            ),
            media_buyer_headers(),
        ),
        201,
    )

    assert persona["state"] == "DRAFT", persona
    assert persona["mix_method"] == "SURVEY_WEIGHTED", persona
    assert persona["research_window_days"] == 180, persona
    assert persona["channel_mix"] == [], persona
    assert persona["signal_count"] == 0, persona
    assert persona["mix_confidence_pct"] == 0, persona
    assert persona["revision_count"] == 0, persona
    assert campaign["state"] == "DRAFT", campaign
    assert campaign["scheduled_for"] is None, campaign
    assert campaign["dispatched_at"] is None, campaign
    assert campaign["audience_size"] == 0, campaign
    assert review["state"] == "NEW", review
    assert review["sla_status"] == "PENDING", review
    assert review["response_due_at"] == "2026-08-03T00:00:00.000Z", review
    assert presence["state"] == "PLANNED", presence
    a.assert_cents(presence["reserved_cents"], 0, "reserved_cents")
    assert presence["confirmed_at"] is None, presence
    for row in (persona, campaign, review, presence):
        a.assert_mutable_row(row, expected_version=1)
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"], 0, "committed_budget_cents"
    )
