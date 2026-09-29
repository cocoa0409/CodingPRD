"""State-machine tests: initial states, terminal lock-down, declared hops and
the cascades that ride on them.

Every test builds its own state from an empty database through public
endpoints only, because the harness restarts the server and empties the
database before each test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instants_equal, shift_instant
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    REGISTRAR_HEADERS,
    panelist_headers,
)

# --------------------------------------------------------------------------
# Local builders (the shared helpers cover the single-member happy path only)
# --------------------------------------------------------------------------


def _placement_stage_one_section(
    api: ApiClient,
    member_specs: List[Dict[str, Any]],
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
    instrument: str = "VIOLIN",
) -> Dict[str, Any]:
    """A season in `PLACEMENT` with one section and one adjudicated audition per spec.

    Every audition is scored by three adjudicators submitting all four rubric
    integers at 20, so each `weighted_total` is 80.00 and, with fewer than four
    sheets in the round, both composites are 80.00 too.
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"], **(ensemble_overrides or {}))
    quota_body: Dict[str, Any] = {"instrument": instrument}
    quota_body.update(quota_overrides or {})
    quota = X.create_section_quota(api, ensemble["id"], **quota_body)
    members = []
    for spec in member_specs:
        body: Dict[str, Any] = {"primary_instrument": instrument}
        body.update(spec)
        members.append(X.create_member(api, **body))
    panelists = X.create_panelists(api, count=3, instrument_expertise=instrument)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        instrument_focus=instrument,
        capacity=8,
    )
    auditions = []
    for member in members:
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        X.submit_uniform_sheets(api, audition["id"], panelists, 20)
        auditions.append(X.adjudicate(api, audition["id"]))
    season = X.advance_season(api, season["id"], "PLACEMENT")
    return {
        "season": season,
        "ensemble": ensemble,
        "quota": quota,
        "members": members,
        "auditions": auditions,
        "slot": slot,
        "panelists": panelists,
    }


def _two_section_placement_stage(api: ApiClient) -> Dict[str, Any]:
    """A `PLACEMENT` season whose ensemble owns a VIOLIN and a CELLO section.

    Each section targets one chair, the ensemble needs two players, and both
    musicians already hold an `OFFERED` placement.
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"], min_total_size=2, max_total_size=4)
    violin_quota = X.create_section_quota(
        api, ensemble["id"], instrument="VIOLIN", min_count=1, target_count=1, max_count=2
    )
    cello_quota = X.create_section_quota(
        api, ensemble["id"], instrument="CELLO", min_count=1, target_count=1, max_count=2
    )
    violinist = X.create_member(api, legal_name="Ada Strings", primary_instrument="VIOLIN")
    cellist = X.create_member(api, legal_name="Cara Cello", primary_instrument="CELLO")
    violin_panel = X.create_panelists(api, count=3, instrument_expertise="VIOLIN")
    cello_panel = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    violin_slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in violin_panel],
        room_code="ROOM-A",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T11:00:00Z",
        instrument_focus="VIOLIN",
        capacity=8,
    )
    cello_slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in cello_panel],
        room_code="ROOM-B",
        start_at="2026-08-12T12:00:00Z",
        end_at="2026-08-12T13:00:00Z",
        instrument_focus="CELLO",
        capacity=8,
    )
    auditions = []
    for member, slot, panel in (
        (violinist, violin_slot, violin_panel),
        (cellist, cello_slot, cello_panel),
    ):
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        X.submit_uniform_sheets(api, audition["id"], panel, 20)
        auditions.append(X.adjudicate(api, audition["id"]))
    season = X.advance_season(api, season["id"], "PLACEMENT")
    placements = [
        X.create_placement(api, audition["id"], ensemble["id"], offer_kind="OFFER")
        for audition in auditions
    ]
    return {
        "season": season,
        "ensemble": ensemble,
        "violin_quota": violin_quota,
        "cello_quota": cello_quota,
        "violinist": violinist,
        "cellist": cellist,
        "placements": placements,
    }


def _quota_row(rows: List[Dict[str, Any]], instrument: str) -> Dict[str, Any]:
    matches = [row for row in rows if row["instrument"] == instrument]
    assert len(matches) == 1, f"expected one {instrument} section, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------
# EventParticipation initial state (PRD §3.8)
# --------------------------------------------------------------------------


def test_festival_participation_starts_with_tour_status_pending(api):
    """A participation row rostered onto a FESTIVAL starts NOT_RECORDED, UNREVIEWED and PENDING.

    PRD §3.8: "A new row starts with `attendance_status` `NOT_RECORDED`, `performance_eligibility` `UNREVIEWED`, and `tour_status` `PENDING` for `TOUR_PERFORMANCE` and `FESTIVAL` events but `NOT_APPLICABLE` for `REHEARSAL` and `CONCERT` events, and it increments the event's `participation_count`."

    Design: Corner/state_machines/event_participation_initial_state_forks_on_event_kind
    """
    ctx = X.accepted_placement(api)
    festival = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="FESTIVAL",
        start_at="2026-10-10T09:00:00Z",
        end_at="2026-10-10T17:00:00Z",
        venue_code="FEST-HALL",
        eligibility_window_start="2026-09-01T00:00:00Z",
        tour_cost_share_cents=50000,
        chaperone_required=True,
    )

    row = X.create_participation(api, festival["id"], ctx["member"]["id"])

    assert row["attendance_status"] == "NOT_RECORDED"
    assert row["performance_eligibility"] == "UNREVIEWED"
    assert row["tour_status"] == "PENDING"
    assert X.read_event(api, festival["id"])["participation_count"] == 1


def test_concert_participation_starts_with_tour_status_not_applicable(api):
    """A participation row rostered onto a CONCERT seeds tour_status NOT_APPLICABLE.

    PRD §3.8: "A new row starts with `attendance_status` `NOT_RECORDED`, `performance_eligibility` `UNREVIEWED`, and `tour_status` `PENDING` for `TOUR_PERFORMANCE` and `FESTIVAL` events but `NOT_APPLICABLE` for `REHEARSAL` and `CONCERT` events, and it increments the event's `participation_count`."

    Design: Corner/state_machines/event_participation_initial_state_forks_on_event_kind
    """
    ctx = X.accepted_placement(api)
    concert = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        venue_code="HALL-A",
        eligibility_window_start="2026-09-01T00:00:00Z",
    )

    row = X.create_participation(api, concert["id"], ctx["member"]["id"])

    assert row["tour_status"] == "NOT_APPLICABLE"
    assert row["attendance_status"] == "NOT_RECORDED"
    assert row["performance_eligibility"] == "UNREVIEWED"
    assert X.read_event(api, concert["id"])["participation_count"] == 1


# --------------------------------------------------------------------------
# ADJUDICATED is terminal (PRD §3.4)
# --------------------------------------------------------------------------


def test_adjudicated_audition_refuses_a_second_adjudication(api):
    """Adjudicating an already-adjudicated audition is refused and leaves the row untouched.

    PRD §3.4: "The audition then reaches `ADJUDICATED`, which is terminal, and its `version` increments."

    Design: Corner/state_machines/adjudicated_audition_rejects_every_further_lifecycle_call
    """
    ctx = X.adjudicated_audition(api)
    audition_id = ctx["audition"]["id"]
    assert ctx["audition"]["status"] == "ADJUDICATED"

    response = api.adjudicate_audition(audition_id, {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, audition_id)
    assert after["status"] == "ADJUDICATED"
    assert after["submitted_score_count"] == 3
    assert after["composite_final_score"] == 80.00
    assert after["tier_recommendation"] == "PHILHARMONIC"


def test_adjudicated_audition_refuses_a_revision_request(api):
    """A terminal ADJUDICATED audition cannot be sent back for another hearing.

    PRD §3.4: "The director may instead send a `SCORED` audition back for another hearing, advancing it `SCORED → REVISION_REQUESTED`."

    Design: Corner/state_machines/adjudicated_audition_rejects_every_further_lifecycle_call
    """
    ctx = X.adjudicated_audition(api)
    audition_id = ctx["audition"]["id"]

    response = api.request_revision(audition_id, {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, audition_id)
    assert after["status"] == "ADJUDICATED"
    assert after["revision_round"] == 0
    assert after["slot_id"] == ctx["slot"]["id"]


def test_adjudicated_audition_refuses_rebooking_into_a_slot(api):
    """Re-booking an ADJUDICATED audition is a state conflict, not a slot-capacity error.

    PRD §3.4: "Booking the audition into a slot advances it `REQUESTED → SCHEDULED`, and the same registrar action re-books a musician sent back for another round, advancing `REVISION_REQUESTED → SCHEDULED`; from any other status the attempt is `ERR_INVALID_STATE_FOR_OPERATION`."

    Design: Corner/state_machines/adjudicated_audition_rejects_every_further_lifecycle_call
    """
    ctx = X.adjudicated_audition(api)
    slot_id = ctx["slot"]["id"]

    response = api.schedule_audition(
        ctx["audition"]["id"], F.schedule_payload(slot_id), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    slot = X.read_audition_slot(api, slot_id)
    assert slot["booked_count"] == 1


def test_adjudicated_audition_state_gate_outranks_the_duplicate_sheet_check(api):
    """A sheet aimed at an ADJUDICATED audition reports the state gate, not the duplicate gate.

    PRD §3.4: "A `Panelist` submits one blind rubric sheet — a **PanelScore** — against a `SCHEDULED` audition, supplying their own `panelist_id` together with four rubric integers each between 0 and 25: `tone_score`, `rhythm_score`, `intonation_score` and `sight_reading_score`."

    Design: Corner/state_machines/adjudicated_audition_rejects_every_further_lifecycle_call
    """
    ctx = X.adjudicated_audition(api)
    panelist_id = ctx["panelists"][0]["id"]

    response = api.submit_panel_score(
        ctx["audition"]["id"],
        F.uniform_panel_score_payload(panelist_id, 25),
        panelist_headers(panelist_id),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, ctx["audition"]["id"])
    assert after["submitted_score_count"] == 3
    assert after["composite_final_score"] == 80.00


# --------------------------------------------------------------------------
# The season ladder walks one rung at a time (PRD §3.1)
# --------------------------------------------------------------------------


def test_season_refuses_hops_that_skip_ahead(api):
    """A PLANNING season refuses both a one-rung skip and a two-rung skip.

    PRD §3.1: "The director advances it one rung at a time by supplying a `to_status`; any `to_status` that is not the declared immediate successor of the current value — a skip ahead or any reversal — is refused with `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/state_machines/season_skip_ahead_and_reversal_hops_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"])
    assert X.read_season(api, season["id"])["version"] == 2

    for skipped in ("PLACEMENT", "CLOSED"):
        response = api.advance_season_status(
            season["id"], F.advance_status_payload(skipped), DIRECTOR_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value)

    after = X.read_season(api, season["id"])
    assert after["status"] == "PLANNING"
    assert after["version"] == 2


def test_season_refuses_a_reversal_after_a_valid_hop(api):
    """The declared hop to AUDITIONS_OPEN succeeds and bumps version, and the reversal is refused.

    PRD §3.1: "The director advances it one rung at a time by supplying a `to_status`; any `to_status` that is not the declared immediate successor of the current value — a skip ahead or any reversal — is refused with `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/state_machines/season_skip_ahead_and_reversal_hops_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"])

    advanced = X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    assert advanced["status"] == "AUDITIONS_OPEN"
    assert advanced["version"] == 3

    response = api.advance_season_status(
        season["id"], F.advance_status_payload("PLANNING"), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value)

    after = X.read_season(api, season["id"])
    assert after["status"] == "AUDITIONS_OPEN"
    assert after["version"] == 3


# --------------------------------------------------------------------------
# A REQUESTED audition admits neither scoring nor closing (PRD §3.4)
# --------------------------------------------------------------------------


def test_requested_audition_refuses_a_rubric_sheet(api):
    """A sheet cannot land on a REQUESTED audition, which holds no slot and no panel.

    PRD §3.4: "A `Panelist` submits one blind rubric sheet — a **PanelScore** — against a `SCHEDULED` audition, supplying their own `panelist_id` together with four rubric integers each between 0 and 25: `tone_score`, `rhythm_score`, `intonation_score` and `sight_reading_score`."

    Design: Corner/state_machines/panel_scoring_and_adjudication_require_the_prior_state
    """
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api)
    panelists = X.create_panelists(api, count=3)
    X.create_audition_slot(api, ctx["season"]["id"], [p["id"] for p in panelists])
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])
    assert audition["status"] == "REQUESTED"
    assert audition["slot_id"] is None

    panelist_id = panelists[0]["id"]
    response = api.submit_panel_score(
        audition["id"],
        F.uniform_panel_score_payload(panelist_id, 20),
        panelist_headers(panelist_id),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, audition["id"])
    assert after["status"] == "REQUESTED"
    assert after["submitted_score_count"] == 0
    assert after["composite_provisional_score"] is None
    assert after["version"] == 1


def test_requested_audition_refuses_adjudication(api):
    """Adjudication needs a SCORED audition, so a REQUESTED one is refused.

    PRD §3.4: "An `ArtisticDirector` closes a `SCORED` audition by adjudicating it, which requires the season to be in `AUDITIONS_OPEN` or `PLACEMENT` and requires `submitted_score_count` to still be at least the slot's `quorum_required`."

    Design: Corner/state_machines/panel_scoring_and_adjudication_require_the_prior_state
    """
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api)
    panelists = X.create_panelists(api, count=3)
    X.create_audition_slot(api, ctx["season"]["id"], [p["id"] for p in panelists])
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])

    response = api.adjudicate_audition(audition["id"], {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, audition["id"])
    assert after["status"] == "REQUESTED"
    assert after["composite_final_score"] is None
    assert after["version"] == 1


def test_requested_audition_refuses_a_revision_request(api):
    """A revision request needs a SCORED audition, so a REQUESTED one is refused.

    PRD §3.4: "The director may instead send a `SCORED` audition back for another hearing, advancing it `SCORED → REVISION_REQUESTED`."

    Design: Corner/state_machines/panel_scoring_and_adjudication_require_the_prior_state
    """
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api)
    panelists = X.create_panelists(api, count=3)
    slot = X.create_audition_slot(api, ctx["season"]["id"], [p["id"] for p in panelists])
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])

    response = api.request_revision(audition["id"], {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    after = X.read_audition(api, audition["id"])
    assert after["status"] == "REQUESTED"
    assert after["revision_round"] == 0
    assert after["slot_id"] is None
    assert X.read_audition_slot(api, slot["id"])["booked_count"] == 0


# --------------------------------------------------------------------------
# Attendance leaves NOT_RECORDED exactly once (PRD §3.8)
# --------------------------------------------------------------------------


def test_attendance_records_once_and_refuses_every_later_recording(api):
    """The first PRESENT recording lands and both a repeat and a different value are refused.

    PRD §3.8: "Recording requires the row still to be `NOT_RECORDED`, so a second recording on the same row is refused with `ERR_INVALID_STATE_FOR_OPERATION`, and it requires the logical clock to be at or after the event's `start_at`; recording attendance strictly before the event begins is `ERR_EVENT_NOT_STARTED`."

    Design: Corner/state_machines/attendance_recorded_once_second_record_call_rejected
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="REHEARSAL",
        start_at="2026-09-05T18:00:00Z",
        end_at="2026-09-05T20:00:00Z",
    )
    row = X.create_participation(api, event["id"], ctx["member"]["id"])
    X.set_clock(api, "2026-09-05T18:05:00Z")

    recorded = X.record_attendance(api, row["id"], "PRESENT")
    assert recorded["attendance_status"] == "PRESENT"

    for repeat in ("PRESENT", "TARDY"):
        response = api.record_attendance(
            row["id"], F.attendance_payload(repeat), REGISTRAR_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_FOR_OPERATION.value)

    assert X.read_participation(api, row["id"])["attendance_status"] == "PRESENT"
    member = X.read_member(api, ctx["member"]["id"])
    assert member["tardy_count"] == 0
    assert member["unexcused_absence_count"] == 0
    assert member["effective_unexcused_count"] == 0
    assert member["standing_status"] == "CLEAR"


# --------------------------------------------------------------------------
# Booking executes every declared side effect (PRD §3.4)
# --------------------------------------------------------------------------


def test_scheduling_books_the_slot_and_flips_it_to_full(api):
    """One schedule call moves the audition to SCHEDULED and saturates a capacity-1 slot.

    PRD §3.4: "A successful booking sets the audition's `slot_id`, increments the target slot's `booked_count` by one, flips that slot's `status` to `FULL` when the incremented count reaches or exceeds `capacity`, and increments both the audition's and the slot's `version` by one each."

    Design: Corner/state_machines/scheduling_books_the_slot_and_flips_it_to_full
    """
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api)
    panelists = X.create_panelists(api, count=3)
    slot = X.create_audition_slot(api, ctx["season"]["id"], [p["id"] for p in panelists])
    assert slot["capacity"] == 1
    assert slot["booked_count"] == 0
    assert slot["status"] == "OPEN"
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])

    booked = X.schedule_audition(api, audition["id"], slot["id"])

    assert booked["status"] == "SCHEDULED"
    assert booked["slot_id"] == slot["id"]
    assert booked["revision_round"] == 0
    assert booked["version"] == 2

    after_slot = X.read_audition_slot(api, slot["id"])
    assert after_slot["booked_count"] == 1
    assert after_slot["status"] == "FULL"
    assert after_slot["version"] == 2

    rows, meta = validate_paginated(
        api.list_auditions(DIRECTOR_HEADERS, params={"slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == audition["id"]


# --------------------------------------------------------------------------
# The offer-expiry sweep and the waitlist promotion it chains (PRD §3.5)
# --------------------------------------------------------------------------


def _sweep_stage(api: ApiClient) -> Dict[str, Any]:
    """One OFFERED placement due to expire and one WAITLISTED placement behind it."""
    ctx = _placement_stage_one_section(
        api,
        [
            {"legal_name": "Ada Strings"},
            {"legal_name": "Ben Bow"},
        ],
        ensemble_overrides={"min_total_size": 1, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 1, "max_count": 1},
    )
    expiry = "2026-08-15T00:00:00Z"
    ctx["offer"] = X.create_placement(
        api,
        ctx["auditions"][0]["id"],
        ctx["ensemble"]["id"],
        offer_kind="OFFER",
        offer_expires_at=expiry,
    )
    ctx["waitlisted"] = X.create_placement(
        api, ctx["auditions"][1]["id"], ctx["ensemble"]["id"], offer_kind="WAITLIST"
    )
    ctx["expiry"] = expiry
    X.set_clock(api, expiry)
    return ctx


def test_offer_expiry_sweep_expires_the_lapsed_offer(api):
    """An offer whose expiry instant equals the clock is swept to EXPIRED and counted.

    PRD §3.5: "Every placement of that season sitting in `OFFERED` whose `offer_expires_at` is at or before the logical clock moves to `EXPIRED`, decrementing its ensemble's `offered_count`; the ensemble's `version` increments once per affected ensemble; and the waitlist promotion runs for each freed section."

    Design: Corner/state_machines/offer_expiry_sweep_expires_then_promotes_the_waitlist_head
    """
    ctx = _sweep_stage(api)
    assert ctx["offer"]["status"] == "OFFERED"

    result = validate_success(
        api.offer_expiry_sweep(ctx["season"]["id"], {}, REGISTRAR_HEADERS)
    )
    assert result["expired_count"] == 1

    assert X.read_placement(api, ctx["offer"]["id"])["status"] == "EXPIRED"
    assert X.read_section_quota(api, ctx["quota"]["id"])["filled_count"] == 0
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "FORMING"


def test_offer_expiry_sweep_promotes_the_waitlist_head_with_a_72_hour_offer(api):
    """The freed seat promotes the waitlist head to OFFERED with a clock-plus-72-hour expiry.

    PRD §3.5: "If the queue is non-empty and the section's `filled_count` plus the ensemble's `offered_count` is strictly below the section's `max_count`, the head of the queue is promoted: its status moves `WAITLISTED → OFFERED`, its `offer_expires_at` is set to the logical clock advanced by seventy-two hours, its `waitlist_rank` is cleared to null, the ensemble's `offered_count` increments by one, a tuition account is opened for that musician and season if none exists, and the rows behind it are re-ranked densely from 1."

    Design: Corner/state_machines/offer_expiry_sweep_expires_then_promotes_the_waitlist_head
    """
    ctx = _sweep_stage(api)
    assert ctx["waitlisted"]["status"] == "WAITLISTED"
    assert ctx["waitlisted"]["waitlist_rank"] == 1

    result = validate_success(
        api.offer_expiry_sweep(ctx["season"]["id"], {}, REGISTRAR_HEADERS)
    )
    assert result["promoted_count"] == 1

    promoted = X.read_placement(api, ctx["waitlisted"]["id"])
    assert promoted["status"] == "OFFERED"
    assert_instants_equal(
        promoted["offer_expires_at"], shift_instant(ctx["expiry"], hours=72)
    )
    assert promoted["waitlist_rank"] is None
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 1
    account = X.sole_account(api, ctx["members"][1]["id"], ctx["season"]["id"])
    assert account["member_id"] == ctx["members"][1]["id"]
    assert account["season_id"] == ctx["season"]["id"]


# --------------------------------------------------------------------------
# Withdrawing a prospect sweeps her open placements (PRD §3.2)
# --------------------------------------------------------------------------


def test_prospect_withdrawal_moves_the_open_offer_to_withdrawn(api):
    """Withdrawing a PROSPECT sweeps her OFFERED placement to WITHDRAWN.

    PRD §3.2: "On the membership dimension the registrar may move `ENROLLED → GRADUATED`, which requires that no tuition account of that musician is `DELINQUENT` (otherwise `ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE`) and which vacates every `ACTIVE` chair the musician holds, running the full vacate cascade of §3.5 on each; `GRADUATED → ALUMNI`, which requires `alumni_engagement_opt_in` to be true; `PROSPECT → WITHDRAWN`, which moves every placement of that musician sitting in `OFFERED` or `WAITLISTED` to `WITHDRAWN`; and `ENROLLED → WITHDRAWN`, which does the same to open placements *and* vacates every `ACTIVE` chair with the full vacate cascade."

    Design: Corner/state_machines/member_withdrawal_cascades_open_placements_to_withdrawn
    """
    ctx = X.placement_offer(api)
    assert X.read_member(api, ctx["member"]["id"])["enrollment_status"] == "PROSPECT"

    updated = validate_success(
        api.member_status_transition(
            ctx["member"]["id"],
            F.member_status_transition_payload("ENROLLMENT", "WITHDRAWN"),
            REGISTRAR_HEADERS,
        )
    )

    assert updated["enrollment_status"] == "WITHDRAWN"
    assert updated["standing_status"] == "CLEAR"
    assert X.read_placement(api, ctx["placement"]["id"])["status"] == "WITHDRAWN"
    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["filled_count"] == 0
    assert quota["balance_state"] == "UNDERFILLED"


def test_withdrawn_offer_releases_the_ensembles_offered_count(api):
    """Once the offer is WITHDRAWN the ensemble no longer counts it as offered.

    PRD §3.1: "An ensemble's `offered_count` tracks how many of its placements currently sit in `OFFERED`."

    Design: Corner/state_machines/member_withdrawal_cascades_open_placements_to_withdrawn
    """
    ctx = X.placement_offer(api)
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 1

    validate_success(
        api.member_status_transition(
            ctx["member"]["id"],
            F.member_status_transition_payload("ENROLLMENT", "WITHDRAWN"),
            REGISTRAR_HEADERS,
        )
    )

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["offered_count"] == 0
    assert ensemble["seated_count"] == 0
    assert ensemble["roster_state"] == "FORMING"


# --------------------------------------------------------------------------
# Vacating a chair unwinds the seating cascade (PRD §3.5, §3.1)
# --------------------------------------------------------------------------


def test_seat_vacate_unwinds_the_seating_cascade_hop_by_hop(api):
    """Vacating the only chair releases the placement and empties the section.

    PRD §3.5: "The chair moves `ACTIVE → VACATED` and its `version` increments; the owning placement moves `ACCEPTED → RELEASED`; the section's `filled_count` decrements by one and the chair order is recomputed over the remaining `ACTIVE` chairs so that chair numbers stay contiguous from 1; the section's `balance_state` and the ensemble's `roster_state` are re-evaluated, which may demote the section and flip the ensemble `SEATED → FORMING` with the season's `seated_ensemble_count` decremented; waitlist promotion runs on the freed section; and the ensemble's `version` increments."

    Design: Corner/state_machines/seat_vacate_compensates_the_seating_cascade_hop_by_hop
    """
    ctx = X.accepted_placement(api)
    assert ctx["quota"]["balance_state"] == "FULL"
    assert ctx["ensemble"]["roster_state"] == "SEATED"

    vacated = validate_success(
        api.vacate_seat(ctx["seat"]["id"], {}, DIRECTOR_HEADERS)
    )

    assert vacated["status"] == "VACATED"
    assert X.read_placement(api, ctx["placement"]["id"])["status"] == "RELEASED"
    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["filled_count"] == 0
    assert quota["balance_state"] == "UNDERFILLED"
    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["seated_count"] == 0
    assert ensemble["roster_state"] == "FORMING"


def test_vacate_drops_the_ensemble_back_to_forming_without_reversing_the_season(api):
    """The SEATED to FORMING fallback decrements seated_ensemble_count but not the phase.

    PRD §3.1: "It falls back `SEATED → FORMING` when at least one section is no longer `FULL` after a chair was vacated, which decrements the season's `seated_ensemble_count` and increments the ensemble's `version`."

    Design: Corner/state_machines/seat_vacate_compensates_the_seating_cascade_hop_by_hop
    """
    ctx = X.accepted_placement(api)
    assert ctx["season"]["status"] == "IN_SEASON"
    assert ctx["season"]["seated_ensemble_count"] == 1
    version_before = ctx["ensemble"]["version"]

    validate_success(api.vacate_seat(ctx["seat"]["id"], {}, DIRECTOR_HEADERS))

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["roster_state"] == "FORMING"
    assert ensemble["version"] > version_before
    season = X.read_season(api, ctx["season"]["id"])
    assert season["seated_ensemble_count"] == 0
    assert season["status"] == "IN_SEASON"


# --------------------------------------------------------------------------
# The ensemble only bubbles up once every section is FULL (PRD §3.1)
# --------------------------------------------------------------------------


def test_ensemble_reaches_seated_only_after_the_last_section_fills(api):
    """With two sections the ensemble stays FORMING until the second acceptance lands.

    PRD §3.1: "It advances `FORMING → SEATED` when every one of its sections has `balance_state` `FULL` and its `seated_count` — the sum of `filled_count` across its sections — is at least `min_total_size`; this sets the roster state, increments the ensemble's `version`, and re-evaluates the season's `seated_ensemble_count`, which may itself advance the season from `PLACEMENT` to `IN_SEASON`."

    Design: Corner/state_machines/ensemble_bubbles_up_to_seated_only_after_the_last_section_fills
    """
    ctx = _two_section_placement_stage(api)

    first = X.accept_placement(
        api, ctx["placements"][0]["id"], ctx["violinist"]["id"]
    )
    assert first["status"] == "ACCEPTED"

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["roster_state"] == "FORMING"
    assert ensemble["seated_count"] == 1
    rows, meta = validate_paginated(
        api.list_section_quotas(
            DIRECTOR_HEADERS, params={"ensemble_id": ctx["ensemble"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    violin = _quota_row(rows, "VIOLIN")
    cello = _quota_row(rows, "CELLO")
    assert violin["filled_count"] == 1 and violin["balance_state"] == "FULL"
    assert cello["filled_count"] == 0 and cello["balance_state"] == "UNDERFILLED"
    season = X.read_season(api, ctx["season"]["id"])
    assert season["status"] == "PLACEMENT"
    assert season["seated_ensemble_count"] == 0

    second = X.accept_placement(api, ctx["placements"][1]["id"], ctx["cellist"]["id"])
    assert second["status"] == "ACCEPTED"

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["roster_state"] == "SEATED"
    assert ensemble["seated_count"] == 2
    season = X.read_season(api, ctx["season"]["id"])
    assert season["status"] == "IN_SEASON"
    assert season["seated_ensemble_count"] == 1


# --------------------------------------------------------------------------
# Rotation reads the parent ensemble's roster state (PRD §3.6)
# --------------------------------------------------------------------------


def test_chair_rotation_refused_while_the_owning_ensemble_is_forming(api):
    """A ROTATING section with two chairs cannot rotate while its ensemble is FORMING.

    PRD §3.6: "Rotation is permitted only when the section's `rotation_policy` is `ROTATING` and its `filled_count` is at least 2 — a `FIXED` section, or a section holding fewer than two `ACTIVE` chairs, is refused with `ERR_ROTATION_NOT_PERMITTED` — and only when the owning ensemble's `roster_state` is `SEATED`, since a `FORMING` ensemble cannot rotate chairs even if the section itself is `FULL`, which is refused with `ERR_ENSEMBLE_NOT_SEATED`."

    Design: Corner/state_machines/chair_rotation_guarded_by_the_owning_ensembles_roster_state
    """
    ctx = _placement_stage_one_section(
        api,
        [
            {"legal_name": "Ada Strings", "years_in_org": 2},
            {"legal_name": "Ben Bow", "years_in_org": 1},
        ],
        ensemble_overrides={"min_total_size": 3, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 3, "max_count": 3},
    )
    for audition, member in zip(ctx["auditions"], ctx["members"]):
        placement = X.create_placement(
            api, audition["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
        )
        X.accept_placement(api, placement["id"], member["id"])

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["roster_state"] == "FORMING"
    version_before = ensemble["version"]

    response = api.rotate_chairs(
        ctx["quota"]["id"],
        F.rotate_chairs_payload(version_before),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ENSEMBLE_NOT_SEATED.value)

    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["rotation_cycle_index"] == 0
    assert quota["filled_count"] == 2
    assert quota["balance_state"] == "BALANCED"

    seats = X.list_seats(api, section_quota_id=ctx["quota"]["id"])
    assert len(seats) == 2
    for seat in seats:
        assert seat["status"] == "ACTIVE"
        assert seat["rotation_cycle_index"] == 0
        assert seat["predecessor_assignment_id"] is None
    by_member = {seat["member_id"]: seat for seat in seats}
    senior = by_member[ctx["members"][0]["id"]]
    junior = by_member[ctx["members"][1]["id"]]
    assert senior["chair_number"] == 1 and senior["is_principal"] is True
    assert junior["chair_number"] == 2 and junior["is_principal"] is False
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["version"] == version_before


# --------------------------------------------------------------------------
# The season close cascade is conditional twice over (PRD §3.1)
# --------------------------------------------------------------------------


def _closable_season(api: ApiClient) -> Dict[str, Any]:
    """An IN_SEASON season whose three seated chair-holders differ on the close criteria."""
    ctx = _placement_stage_one_section(
        api,
        [
            {
                "legal_name": "Grad Gina",
                "graduation_year": 2026,
                "years_in_org": 4,
                "alumni_engagement_opt_in": True,
            },
            {
                "legal_name": "Grad Gus",
                "graduation_year": 2026,
                "years_in_org": 3,
                "alumni_engagement_opt_in": False,
            },
            {
                "legal_name": "Rising Rae",
                "graduation_year": 2028,
                "years_in_org": 1,
                "alumni_engagement_opt_in": True,
            },
        ],
        ensemble_overrides={"min_total_size": 3, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 3, "max_count": 3},
    )
    for audition, member in zip(ctx["auditions"], ctx["members"]):
        placement = X.create_placement(
            api, audition["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
        )
        X.accept_placement(api, placement["id"], member["id"])
    ctx["season"] = X.read_season(api, ctx["season"]["id"])
    assert ctx["season"]["status"] == "IN_SEASON"
    return ctx


def test_season_close_graduates_only_the_matching_graduation_year(api):
    """Only the seated chair-holders whose graduation_year is the closing year graduate.

    PRD §3.1: "Second, because those ensembles closed, every musician holding an `ACTIVE` chair in them whose `graduation_year` equals the calendar year of the season's `tuition_due_at` and whose `enrollment_status` is `ENROLLED` moves to `GRADUATED`."

    Design: Corner/state_machines/season_close_graduates_only_the_matching_graduation_year
    """
    ctx = _closable_season(api)

    closed = X.advance_season(api, ctx["season"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"

    gus = X.read_member(api, ctx["members"][1]["id"])
    rae = X.read_member(api, ctx["members"][2]["id"])
    assert gus["enrollment_status"] == "GRADUATED"
    assert rae["enrollment_status"] == "ENROLLED"
    assert gus["standing_status"] == "CLEAR"
    assert rae["standing_status"] == "CLEAR"


def test_season_close_promotes_only_opted_in_graduates_to_alumni(api):
    """Of the two graduates only the one who opted in continues to ALUMNI.

    PRD §3.1: "Third, because those musicians graduated, each of them whose `alumni_engagement_opt_in` is true moves on to `ALUMNI`."

    Design: Corner/state_machines/season_close_graduates_only_the_matching_graduation_year
    """
    ctx = _closable_season(api)

    X.advance_season(api, ctx["season"]["id"], "CLOSED")

    gina = X.read_member(api, ctx["members"][0]["id"])
    gus = X.read_member(api, ctx["members"][1]["id"])
    assert gina["enrollment_status"] == "ALUMNI"
    assert gus["enrollment_status"] == "GRADUATED"


def test_season_close_closes_every_forming_or_seated_ensemble(api):
    """Closing the season drives its SEATED ensemble to the terminal CLOSED roster state.

    PRD §3.1: "First, every ensemble of the season whose `roster_state` is `FORMING` or `SEATED` moves to `CLOSED`."

    Design: Corner/state_machines/season_close_graduates_only_the_matching_graduation_year
    """
    ctx = _closable_season(api)
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "SEATED"

    X.advance_season(api, ctx["season"]["id"], "CLOSED")

    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "CLOSED"
