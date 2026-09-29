"""Boundary validations and endpoint contracts for the Youth Orchestra API.

Every test builds all of its own state through the public endpoints, because the
harness restarts the server and empties the database before each test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    FINANCE_HEADERS,
    REGISTRAR_HEADERS,
    guardian_headers,
)

# --------------------------------------------------------------------------
# Local scenario builders (no shared-helper edits allowed)
# --------------------------------------------------------------------------

ADA = {"legal_name": "Ada Strings", "years_in_org": 1}
BEN = {"legal_name": "Ben Bow", "years_in_org": 1}


def _placement_stage(
    api,
    member_specs: List[Dict[str, Any]],
    instrument: str = "CELLO",
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
    score_value: int = 20,
) -> Dict[str, Any]:
    """A season in `PLACEMENT` whose listed musicians are all `ADJUDICATED`."""
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"], **(ensemble_overrides or {}))
    quota = X.create_section_quota(
        api, ensemble["id"], instrument=instrument, **(quota_overrides or {})
    )
    panelists = X.create_panelists(api, count=3, instrument_expertise=instrument)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        instrument_focus=instrument,
        capacity=8,
    )
    members: List[Dict[str, Any]] = []
    auditions: List[Dict[str, Any]] = []
    for spec in member_specs:
        member = X.create_member(api, primary_instrument=instrument, **spec)
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        X.submit_uniform_sheets(api, audition["id"], panelists, score_value)
        members.append(member)
        auditions.append(X.adjudicate(api, audition["id"]))
    season = X.advance_season(api, season["id"], "PLACEMENT")
    return {
        "season": season,
        "ensemble": ensemble,
        "quota": quota,
        "panelists": panelists,
        "slot": slot,
        "members": members,
        "auditions": auditions,
    }


def _two_offers_on_one_section(
    api,
    quota_overrides: Dict[str, Any],
    ensemble_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ada holds an `OFFERED` placement; Ben is adjudicated with none."""
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides=ensemble_overrides,
        quota_overrides=quota_overrides,
    )
    stage["offer"] = X.create_placement(
        api, stage["auditions"][0]["id"], stage["ensemble"]["id"], offer_kind="OFFER"
    )
    return stage


def _seated_player_with_rehearsal_history(api) -> Dict[str, Any]:
    """One seated musician, four `PRESENT` rehearsals and a missed dress rehearsal."""
    ctx = X.accepted_placement(api)
    ensemble_id = ctx["ensemble"]["id"]
    member_id = ctx["member"]["id"]

    rehearsal_days = ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-22"]
    present_rows = []
    for day in rehearsal_days:
        event = X.create_ensemble_event(
            api,
            ensemble_id,
            kind="REHEARSAL",
            start_at=f"{day}T18:00:00Z",
            end_at=f"{day}T20:00:00Z",
        )
        present_rows.append(X.create_participation(api, event["id"], member_id))
    dress = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="REHEARSAL",
        start_at="2026-10-26T18:00:00Z",
        end_at="2026-10-26T20:00:00Z",
        is_dress_rehearsal=True,
    )
    dress_row = X.create_participation(api, dress["id"], member_id)

    requiring_concert = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        dress_rehearsal_required=True,
        eligibility_window_start="2026-10-01T00:00:00Z",
    )
    plain_concert = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-11-16T19:00:00Z",
        end_at="2026-11-16T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )
    requiring_row = X.create_participation(api, requiring_concert["id"], member_id)
    plain_row = X.create_participation(api, plain_concert["id"], member_id)

    X.set_clock(api, "2026-10-26T18:05:00Z")
    for row in present_rows:
        X.record_attendance(api, row["id"], "PRESENT")
    X.record_attendance(api, dress_row["id"], "UNEXCUSED_ABSENT")

    ctx.update(
        {
            "requiring_row": requiring_row,
            "plain_row": plain_row,
        }
    )
    return ctx


def _two_seated_players_with_concerts(api) -> Dict[str, Any]:
    """Two seated violinists, both `ELIGIBLE` on three differently-moded concerts."""
    stage = _placement_stage(
        api,
        [
            {"legal_name": "Prin Pia", "years_in_org": 2},
            {"legal_name": "Sec Sam", "years_in_org": 1},
        ],
        ensemble_overrides={"min_total_size": 2, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    offers = [
        X.create_placement(api, audition["id"], ensemble_id, offer_kind="OFFER")
        for audition in stage["auditions"]
    ]
    for offer, member in zip(offers, stage["members"]):
        X.accept_placement(api, offer["id"], member["id"])

    rehearsal = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="REHEARSAL",
        start_at="2026-10-05T18:00:00Z",
        end_at="2026-10-05T20:00:00Z",
    )
    concerts = {}
    for mode, day in (
        ("AUTO_SELECT", "2026-11-15"),
        ("MANUAL", "2026-11-16"),
        ("NONE", "2026-11-17"),
    ):
        concerts[mode] = X.create_ensemble_event(
            api,
            ensemble_id,
            kind="CONCERT",
            start_at=f"{day}T19:00:00Z",
            end_at=f"{day}T21:00:00Z",
            soloist_selection_mode=mode,
            eligibility_window_start="2026-10-01T00:00:00Z",
        )

    rehearsal_rows = [
        X.create_participation(api, rehearsal["id"], member["id"])
        for member in stage["members"]
    ]
    concert_rows = {
        mode: [
            X.create_participation(api, event["id"], member["id"])
            for member in stage["members"]
        ]
        for mode, event in concerts.items()
    }

    X.set_clock(api, "2026-10-05T18:05:00Z")
    for row in rehearsal_rows:
        X.record_attendance(api, row["id"], "PRESENT")
    for rows in concert_rows.values():
        for row in rows:
            X.review_eligibility(api, row["id"])

    stage["concerts"] = concerts
    return stage


# --------------------------------------------------------------------------
# Each violated check reports its own declared error id
# --------------------------------------------------------------------------

def test_instrument_mismatch_outranks_the_unmet_repertoire_check(api):
    """A booking that mismatches the slot instrument and misses a required excerpt reports the instrument mismatch.

    PRD §2.10: "Then the referential, uniqueness and per-row-constraint band, in this internal order: `ERR_SLOT_INSTRUMENT_MISMATCH`, `ERR_REPERTOIRE_REQUIREMENTS_UNMET`, the six uniqueness codes (`ERR_DUPLICATE_PANEL_SCORE`, `ERR_DUPLICATE_SECTION_QUOTA`, `ERR_DUPLICATE_TUITION_ACCOUNT`, `ERR_DUPLICATE_PARTICIPATION`, `ERR_DUPLICATE_AUDITION`, `ERR_DUPLICATE_PLACEMENT`, which share one rank because each guards a different tuple), `ERR_TIER_ABOVE_RECOMMENDATION`, `ERR_NO_SECTION_FOR_INSTRUMENT`, `ERR_ROTATION_NOT_PERMITTED`, and `ERR_AUDITION_SLOT_FULL`."

    Design: Corner/validations/each_violated_check_reports_its_own_declared_error_id
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"], instrument="VIOLIN")
    member = X.create_member(api, primary_instrument="VIOLIN")
    violin_panel = X.create_panelists(api, count=3, instrument_expertise="VIOLIN")
    cello_panel = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    cello_slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in cello_panel],
        room_code="ROOM-2",
        instrument_focus="CELLO",
        start_at="2026-08-12T12:00:00Z",
        end_at="2026-08-12T13:00:00Z",
        required_excerpt_codes=["EX9"],
        quorum_required=3,
        capacity=4,
    )
    X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in violin_panel],
        room_code="ROOM-1",
        instrument_focus="VIOLIN",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T11:00:00Z",
        required_excerpt_codes=["EX9"],
        quorum_required=3,
        capacity=4,
    )
    audition = X.create_audition(
        api, member["id"], season["id"], excerpt_ids=["EX1"], scale_attested=True
    )

    response = api.schedule_audition(
        audition["id"], F.schedule_payload(cello_slot["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_SLOT_INSTRUMENT_MISMATCH.value)

    unchanged = X.read_audition(api, audition["id"])
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["slot_id"] is None
    assert X.read_audition_slot(api, cello_slot["id"])["booked_count"] == 0


def test_uncovered_required_excerpt_reports_the_repertoire_error(api):
    """Booking into an instrument-matched slot whose required excerpt is not prepared is refused.

    PRD §3.4: "The audition's `excerpt_ids` must cover every code listed in the slot's `required_excerpt_codes`, and when that list is non-empty the audition's `scale_attested` must be true; either failure is `ERR_REPERTOIRE_REQUIREMENTS_UNMET`."

    Design: Corner/validations/each_violated_check_reports_its_own_declared_error_id
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"], instrument="VIOLIN")
    member = X.create_member(api, primary_instrument="VIOLIN")
    violin_panel = X.create_panelists(api, count=3, instrument_expertise="VIOLIN")
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    violin_slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in violin_panel],
        room_code="ROOM-1",
        instrument_focus="VIOLIN",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T11:00:00Z",
        required_excerpt_codes=["EX9"],
        quorum_required=3,
        capacity=4,
    )
    audition = X.create_audition(
        api, member["id"], season["id"], excerpt_ids=["EX1"], scale_attested=True
    )

    response = api.schedule_audition(
        audition["id"], F.schedule_payload(violin_slot["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_REPERTOIRE_REQUIREMENTS_UNMET.value)

    unchanged = X.read_audition(api, audition["id"])
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["slot_id"] is None
    assert X.read_audition_slot(api, violin_slot["id"])["booked_count"] == 0


def test_rostering_a_musician_who_holds_no_chair_is_refused(api):
    """A musician with no active chair in the ensemble cannot be rostered onto its calendar.

    PRD §3.8: "The musician must hold an `ACTIVE` chair in some section of that event's ensemble; a non-member of the ensemble cannot be added to its calendar, and the attempt is `ERR_MEMBER_NOT_IN_ENSEMBLE`."

    Design: Corner/validations/each_violated_check_reports_its_own_declared_error_id
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"], instrument="VIOLIN")
    member = X.create_member(api, primary_instrument="VIOLIN")
    event = X.create_ensemble_event(
        api,
        ensemble["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )

    response = api.create_event_participation(
        F.participation_payload(event["id"], member["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_IN_ENSEMBLE.value)

    assert X.read_event(api, event["id"])["participation_count"] == 0
    rows, meta = validate_paginated(
        api.list_event_participations(REGISTRAR_HEADERS, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


# --------------------------------------------------------------------------
# Acceptance that exactly fills the section is admitted
# --------------------------------------------------------------------------

def test_acceptance_that_takes_the_section_to_its_max_is_admitted(api):
    """The acceptance that lifts filled_count from one to the section max of two is accepted.

    PRD §3.5: "Acceptance requires the logical clock to be strictly earlier than `offer_expires_at`; requires the musician's `standing_status` to be anything other than `FINANCIAL_HOLD`; requires the musician's tuition account for that season to carry a `billing_status` other than `DELINQUENT`; requires the section's `filled_count` to still be below its `max_count`, so that an offer whose section filled up while it sat open is refused with `ERR_SECTION_FULL_AT_ACCEPTANCE`; and requires the ensemble's `seated_count` to still be below `max_total_size`."

    Design: Corner/validations/acceptance_that_exactly_fills_the_section_is_admitted
    """
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides={"min_total_size": 2, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    offers = [
        X.create_placement(api, audition["id"], ensemble_id, offer_kind="OFFER")
        for audition in stage["auditions"]
    ]

    first = X.accept_placement(api, offers[0]["id"], stage["members"][0]["id"])
    assert first["status"] == "ACCEPTED"

    response = api.accept_placement(
        offers[1]["id"],
        F.accept_payload(instrument_loan_requested=False),
        guardian_headers(stage["members"][1]["id"]),
    )
    second = validate_success(response)
    assert second["status"] == "ACCEPTED"

    quota = X.read_section_quota(api, stage["quota"]["id"])
    assert quota["filled_count"] == 2
    assert quota["balance_state"] == "FULL"

    ensemble = X.read_ensemble(api, ensemble_id)
    assert ensemble["seated_count"] == 2
    assert ensemble["offered_count"] == 0
    assert ensemble["roster_state"] == "SEATED"

    seats = X.list_seats(api, section_quota_id=stage["quota"]["id"])
    active = A.active_seats(seats)
    assert len(active) == 2
    A.assert_contiguous_chair_numbers(seats)


def test_two_acceptances_open_one_tuition_account_per_musician(api):
    """Two musicians seated in the same season each hold exactly one tuition account.

    PRD §3.7: "It comes into being as a side effect of a placement offer or a waitlist promotion, and it is unique per combination of `member_id` and `season_id`."

    Design: Corner/validations/acceptance_that_exactly_fills_the_section_is_admitted
    """
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides={"min_total_size": 2, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    offers = [
        X.create_placement(api, audition["id"], ensemble_id, offer_kind="OFFER")
        for audition in stage["auditions"]
    ]
    for offer, member in zip(offers, stage["members"]):
        X.accept_placement(api, offer["id"], member["id"])

    rows, meta = validate_paginated(
        api.list_tuition_accounts(
            FINANCE_HEADERS, params={"season_id": stage["season"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["member_id"] for row in rows) == sorted(
        member["id"] for member in stage["members"]
    )
    for member in stage["members"]:
        account = X.sole_account(api, member["id"], stage["season"]["id"])
        assert account["assessed_cents"] == 123223
        assert account["billing_status"] == "CURRENT"


# --------------------------------------------------------------------------
# Audition-window containment is inclusive on both ends
# --------------------------------------------------------------------------

def test_window_bounds_admit_slots_flush_with_either_end(api):
    """Slots starting exactly at the window open and ending exactly at the window close are created.

    PRD §3.3: "Slot times must be contained in the season's audition window: `start_at` must be at or after `audition_window_start`, and `end_at` must be at or before `audition_window_end`."

    Design: Corner/validations/audition_slot_window_bounds_are_inclusive_on_both_ends
    """
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    panelist_ids = [p["id"] for p in panelists]

    opening = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        panelist_ids,
        room_code="ROOM-A",
        start_at=C.SEASON_AUDITION_WINDOW_START,
        end_at="2026-08-10T10:00:00Z",
        quorum_required=3,
        capacity=4,
    )
    A.assert_instants_equal(opening["start_at"], C.SEASON_AUDITION_WINDOW_START)
    assert opening["status"] == "OPEN"
    assert opening["booked_count"] == 0

    closing = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        panelist_ids,
        room_code="ROOM-B",
        start_at="2026-08-20T17:00:00Z",
        end_at=C.SEASON_AUDITION_WINDOW_END,
        quorum_required=3,
        capacity=4,
    )
    A.assert_instants_equal(closing["end_at"], C.SEASON_AUDITION_WINDOW_END)
    assert closing["status"] == "OPEN"
    assert closing["booked_count"] == 0

    _, meta = validate_paginated(
        api.list_audition_slots(
            REGISTRAR_HEADERS, params={"season_id": ctx["season"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_slot_one_minute_before_the_window_open_is_refused(api):
    """A slot starting one minute before the window open is refused for escaping the window.

    PRD §3.3: "A slot that escapes either bound is refused with `ERR_SLOT_OUTSIDE_AUDITION_WINDOW`, and per §2.10 that window check is evaluated before the room-occupancy check, so a slot that is both out of window and double-booked reports the window error."

    Design: Corner/validations/audition_slot_window_bounds_are_inclusive_on_both_ends
    """
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    panelist_ids = [p["id"] for p in panelists]
    X.create_audition_slot(
        api,
        ctx["season"]["id"],
        panelist_ids,
        room_code="ROOM-A",
        start_at=C.SEASON_AUDITION_WINDOW_START,
        end_at="2026-08-10T10:00:00Z",
        quorum_required=3,
        capacity=4,
    )

    response = api.create_audition_slot(
        F.audition_slot_payload(
            ctx["season"]["id"],
            panelist_ids,
            room_code="ROOM-A",
            start_at="2026-08-10T08:59:00Z",
            end_at="2026-08-10T09:59:00Z",
        ),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_AUDITION_WINDOW.value)

    _, meta = validate_paginated(
        api.list_audition_slots(
            REGISTRAR_HEADERS, params={"season_id": ctx["season"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_slot_one_minute_after_the_window_close_is_refused(api):
    """A slot ending one minute after the window close is refused for escaping the window.

    PRD §3.3: "A slot that escapes either bound is refused with `ERR_SLOT_OUTSIDE_AUDITION_WINDOW`, and per §2.10 that window check is evaluated before the room-occupancy check, so a slot that is both out of window and double-booked reports the window error."

    Design: Corner/validations/audition_slot_window_bounds_are_inclusive_on_both_ends
    """
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    panelist_ids = [p["id"] for p in panelists]
    X.create_audition_slot(
        api,
        ctx["season"]["id"],
        panelist_ids,
        room_code="ROOM-B",
        start_at="2026-08-20T17:00:00Z",
        end_at=C.SEASON_AUDITION_WINDOW_END,
        quorum_required=3,
        capacity=4,
    )

    response = api.create_audition_slot(
        F.audition_slot_payload(
            ctx["season"]["id"],
            panelist_ids,
            room_code="ROOM-B",
            start_at="2026-08-20T17:01:00Z",
            end_at="2026-08-20T18:01:00Z",
        ),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_AUDITION_WINDOW.value)

    _, meta = validate_paginated(
        api.list_audition_slots(
            REGISTRAR_HEADERS, params={"season_id": ctx["season"]["id"]}
        )
    )
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------
# Offer capacity counts seats plus outstanding offers
# --------------------------------------------------------------------------

def test_second_offer_refused_when_seats_plus_offers_reach_section_max(api):
    """A second offer is refused although no seat is filled, because one offer already consumes the section max.

    PRD §3.5: "Capacity is checked only on the `OFFER` branch, and it is checked twice: for the section, `filled_count` plus the number of placements already sitting in `OFFERED` on that same ensemble-and-instrument pairing must be strictly below the section's `max_count`; and for the ensemble, `seated_count` plus `offered_count` must be strictly below `max_total_size`."

    Design: Corner/validations/offer_capacity_counts_seats_plus_outstanding_offers
    """
    stage = _two_offers_on_one_section(
        api, quota_overrides={"min_count": 1, "target_count": 1, "max_count": 1}
    )
    ensemble_id = stage["ensemble"]["id"]

    response = api.create_placement(
        F.placement_payload(
            stage["auditions"][1]["id"],
            ensemble_id,
            X.ensemble_version(api, ensemble_id),
            offer_kind="OFFER",
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SECTION_CAPACITY_EXCEEDED.value)

    assert X.read_section_quota(api, stage["quota"]["id"])["filled_count"] == 0
    ensemble = X.read_ensemble(api, ensemble_id)
    assert ensemble["offered_count"] == 1
    assert ensemble["seated_count"] == 0
    _, meta = validate_paginated(
        api.list_placements(DIRECTOR_HEADERS, params={"ensemble_id": ensemble_id})
    )
    assert meta["total_count"] == 1


def test_waitlist_row_is_exempt_from_the_capacity_aggregate(api):
    """The same request refused as an offer is admitted as a waitlist claim.

    PRD §3.5: "A `WAITLIST` row is exempt from both, because it reserves nothing."

    Design: Corner/validations/offer_capacity_counts_seats_plus_outstanding_offers
    """
    stage = _two_offers_on_one_section(
        api, quota_overrides={"min_count": 1, "target_count": 1, "max_count": 1}
    )
    ensemble_id = stage["ensemble"]["id"]

    response = api.create_placement(
        F.placement_payload(
            stage["auditions"][1]["id"],
            ensemble_id,
            X.ensemble_version(api, ensemble_id),
            offer_kind="WAITLIST",
        ),
        DIRECTOR_HEADERS,
    )
    waitlisted = validate_success(response, 201)
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlist_rank"] == 1
    assert waitlisted["member_id"] == stage["members"][1]["id"]


def test_waitlist_row_commits_neither_offer_count_nor_tuition_account(api):
    """A waitlist claim leaves offered_count untouched and opens no tuition account.

    PRD §3.5: "A `WAITLIST` is created in `WAITLISTED` with `waitlist_rank` set to one more than the number of placements already `WAITLISTED` on that same ensemble-and-instrument pairing; it increments the ensemble's `version`; and it deliberately does *neither* of the offer branch's two commitments — `offered_count` is untouched and no tuition account is opened."

    Design: Corner/validations/offer_capacity_counts_seats_plus_outstanding_offers
    """
    stage = _two_offers_on_one_section(
        api, quota_overrides={"min_count": 1, "target_count": 1, "max_count": 1}
    )
    ensemble_id = stage["ensemble"]["id"]
    before = X.read_ensemble(api, ensemble_id)

    X.create_placement(
        api, stage["auditions"][1]["id"], ensemble_id, offer_kind="WAITLIST"
    )

    after = X.read_ensemble(api, ensemble_id)
    assert after["offered_count"] == before["offered_count"] == 1
    assert after["version"] == before["version"] + 1
    assert X.read_section_quota(api, stage["quota"]["id"])["filled_count"] == 0
    assert X.list_accounts(api, member_id=stage["members"][1]["id"]) == []
    assert len(X.list_accounts(api, member_id=stage["members"][0]["id"])) == 1


# --------------------------------------------------------------------------
# The dress-rehearsal clause applies only when the event requires it
# --------------------------------------------------------------------------

def test_eligibility_granted_at_exactly_eighty_when_no_dress_rehearsal_required(api):
    """An index of exactly 80.00 grants eligibility on a concert that does not require the dress rehearsal.

    PRD §3.8: "Eligibility is granted only when three conditions all hold: `attendance_index` is at least 80.00; when the performance's `dress_rehearsal_required` is true, the musician's participation on the latest dress-rehearsal-flagged `REHEARSAL` of that ensemble inside the window carries `attendance_status` `PRESENT`; and the musician's `standing_status` is not `ATTENDANCE_PROBATION`."

    Design: Corner/validations/dress_rehearsal_clause_applies_only_when_the_event_requires_it
    """
    ctx = _seated_player_with_rehearsal_history(api)

    reviewed = X.review_eligibility(api, ctx["plain_row"]["id"])
    assert float(reviewed["attendance_index"]) == 80.00
    assert reviewed["performance_eligibility"] == "ELIGIBLE"
    assert reviewed["ineligibility_reason"] == "NONE"

    member = X.read_member(api, ctx["member"]["id"])
    assert member["standing_status"] == "CLEAR"
    assert member["unexcused_absence_count"] == 1
    assert member["effective_unexcused_count"] == 1


def test_dress_rehearsal_clause_makes_the_same_index_ineligible(api):
    """The same 80.00 index is ineligible for a missed dress rehearsal on a concert that requires it.

    PRD §3.8: "When at least one fails the row moves `UNREVIEWED → INELIGIBLE`, the index is still stored, and `ineligibility_reason` is set from the first failing condition in that same order — `ATTENDANCE_INDEX_BELOW_THRESHOLD`, then `DRESS_REHEARSAL_MISSED`, then `MEMBER_ON_PROBATION`."

    Design: Corner/validations/dress_rehearsal_clause_applies_only_when_the_event_requires_it
    """
    ctx = _seated_player_with_rehearsal_history(api)

    reviewed = X.review_eligibility(api, ctx["requiring_row"]["id"])
    assert float(reviewed["attendance_index"]) == 80.00
    assert reviewed["performance_eligibility"] == "INELIGIBLE"
    assert reviewed["ineligibility_reason"] == "DRESS_REHEARSAL_MISSED"


# --------------------------------------------------------------------------
# A placement write is gated by the target ensemble's own state
# --------------------------------------------------------------------------

def test_offer_refused_once_the_target_ensemble_is_seated(api):
    """An offer into a SEATED ensemble is refused even though the section could still hold a seat.

    PRD §3.5: "The season must be in `PLACEMENT` and the target ensemble's `roster_state` must be `FORMING`; a `SEATED` or `CLOSED` ensemble accepts no further offers or waitlist claims, and either failure is `ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS`."

    Design: Corner/validations/placement_write_gated_by_the_target_ensembles_own_state
    """
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides={"min_total_size": 1, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 1, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    offer = X.create_placement(
        api, stage["auditions"][0]["id"], ensemble_id, offer_kind="OFFER"
    )
    X.accept_placement(api, offer["id"], stage["members"][0]["id"])

    seated = X.read_ensemble(api, ensemble_id)
    assert seated["roster_state"] == "SEATED"

    response = api.create_placement(
        F.placement_payload(
            stage["auditions"][1]["id"],
            ensemble_id,
            seated["version"],
            offer_kind="OFFER",
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS.value)

    after = X.read_ensemble(api, ensemble_id)
    assert after["version"] == seated["version"]
    assert after["seated_count"] == 1
    assert after["offered_count"] == 0
    _, meta = validate_paginated(
        api.list_placements(DIRECTOR_HEADERS, params={"ensemble_id": ensemble_id})
    )
    assert meta["total_count"] == 1


def test_waitlist_claim_refused_once_the_target_ensemble_is_seated(api):
    """A waitlist claim on a SEATED ensemble is refused just like an offer.

    PRD §3.5: "The season must be in `PLACEMENT` and the target ensemble's `roster_state` must be `FORMING`; a `SEATED` or `CLOSED` ensemble accepts no further offers or waitlist claims, and either failure is `ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS`."

    Design: Corner/validations/placement_write_gated_by_the_target_ensembles_own_state
    """
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides={"min_total_size": 1, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 1, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    offer = X.create_placement(
        api, stage["auditions"][0]["id"], ensemble_id, offer_kind="OFFER"
    )
    X.accept_placement(api, offer["id"], stage["members"][0]["id"])
    seated = X.read_ensemble(api, ensemble_id)

    response = api.create_placement(
        F.placement_payload(
            stage["auditions"][1]["id"],
            ensemble_id,
            seated["version"],
            offer_kind="WAITLIST",
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS.value)

    after = X.read_ensemble(api, ensemble_id)
    assert after["version"] == seated["version"]
    _, meta = validate_paginated(
        api.list_placements(DIRECTOR_HEADERS, params={"ensemble_id": ensemble_id})
    )
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------
# EnsembleEvent create / read / list round trip
# --------------------------------------------------------------------------

def test_ensemble_event_create_and_read_round_trip(api):
    """A newly created calendar event reads back in DRAFT with no participations.

    PRD §3.8: "A new event starts in `programming_state` `DRAFT` with `participation_count` 0."

    Design: Corner/endpoints/ensemble_event_create_read_list_round_trip
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    created = X.create_ensemble_event(
        api,
        ensemble["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        venue_code="HALL-B",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )
    assert created["programming_state"] == "DRAFT"
    assert created["participation_count"] == 0
    A.assert_common_fields(created, expected_version=1)

    fetched = validate_success(
        api.get_ensemble_event(created["id"], REGISTRAR_HEADERS)
    )
    assert fetched["id"] == created["id"]
    assert fetched["ensemble_id"] == ensemble["id"]
    assert fetched["kind"] == "CONCERT"
    assert fetched["venue_code"] == "HALL-B"
    assert fetched["programming_state"] == "DRAFT"
    assert fetched["participation_count"] == 0
    assert fetched["version"] == 1
    A.assert_instants_equal(fetched["start_at"], "2026-11-15T19:00:00Z")
    A.assert_instants_equal(fetched["end_at"], "2026-11-15T21:00:00Z")
    A.assert_instants_equal(
        fetched["eligibility_window_start"], "2026-10-01T00:00:00Z"
    )


def test_ensemble_event_optional_inputs_take_their_declared_defaults(api):
    """A rehearsal created with only its required fields carries every declared default.

    PRD §3.8: "Six optional inputs shape the event: `is_dress_rehearsal`, defaulting to false, marks a rehearsal as its ensemble's dress rehearsal; `dress_rehearsal_required`, defaulting to false, declares on a performance event that missing the dress rehearsal disqualifies a musician; `eligibility_window_start` fixes the inclusive start of the rehearsal window the attendance index scans and is required for the three performance kinds; `soloist_selection_mode`, defaulting to `AUTO_SELECT` and otherwise `MANUAL` or `NONE`, decides who picks the soloist; `tour_cost_share_cents`, defaulting to 0, is the per-member cost share for tour and festival events; and `chaperone_required`, defaulting to false, makes a confirmed chaperone a tour-readiness precondition."

    Design: Corner/endpoints/ensemble_event_create_read_list_round_trip
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    created = X.create_ensemble_event(
        api,
        ensemble["id"],
        kind="REHEARSAL",
        start_at="2026-10-05T18:00:00Z",
        end_at="2026-10-05T20:00:00Z",
        venue_code="HALL-A",
    )
    assert created["is_dress_rehearsal"] is False
    assert created["dress_rehearsal_required"] is False
    assert created["soloist_selection_mode"] == "AUTO_SELECT"
    assert created["tour_cost_share_cents"] == 0
    assert created["chaperone_required"] is False


def test_ensemble_event_list_filters_narrow_by_ensemble_and_kind(api):
    """The calendar list endpoint honours its ensemble_id and kind filters independently.

    PRD §2.3: "Each list endpoint also accepts a small set of optional equality filters, named after the field they filter on, so that any foreign key declared in the data model can be walked in reverse."

    Design: Corner/endpoints/ensemble_event_create_read_list_round_trip
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_ensemble_event(
        api,
        ensemble["id"],
        kind="REHEARSAL",
        start_at="2026-10-05T18:00:00Z",
        end_at="2026-10-05T20:00:00Z",
        venue_code="HALL-A",
    )
    concert = X.create_ensemble_event(
        api,
        ensemble["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        venue_code="HALL-B",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )

    _, meta = validate_paginated(
        api.list_ensemble_events(
            REGISTRAR_HEADERS, params={"ensemble_id": ensemble["id"]}
        )
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_ensemble_events(
            REGISTRAR_HEADERS,
            params={"ensemble_id": ensemble["id"], "kind": "CONCERT"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == concert["id"]


# --------------------------------------------------------------------------
# The payment action returns the recomputed account
# --------------------------------------------------------------------------

def test_payment_lowers_the_balance_and_returns_the_account(api):
    """Recording a payment returns the account with payments raised and the balance lowered.

    PRD §3.7: "The payment raises `payments_total_cents` and lowers `balance_cents`."

    Design: Corner/endpoints/payment_action_returns_the_recomputed_account
    """
    ctx = X.accepted_placement(api)
    account = ctx["account"]
    assert account["assessed_cents"] == 123223
    assert account["balance_cents"] == 123223

    response = api.record_payment(
        account["id"], F.payment_payload(23223), guardian_headers(ctx["member"]["id"])
    )
    updated = validate_success(response, 201)
    assert updated["id"] == account["id"]
    assert updated["payments_total_cents"] == 23223
    assert updated["balance_cents"] == 100000
    assert updated["assessed_cents"] == 123223
    assert updated["billing_status"] == "CURRENT"
    A.assert_balance_identity(updated)


def test_payment_that_clears_the_balance_moves_the_account_to_paid_in_full(api):
    """A payment that brings the balance to exactly zero flips billing to PAID_IN_FULL.

    PRD §3.7: "A payment that brings `balance_cents` to zero or below moves the account to `PAID_IN_FULL` from either `CURRENT` or `DELINQUENT`, and clearing a delinquency re-evaluates the musician's `standing_status`, releasing `FINANCIAL_HOLD` to `CLEAR` when no other account of that musician is `DELINQUENT` and the attendance cause no longer holds, or dropping it back to `ATTENDANCE_PROBATION` when the attendance cause does still hold."

    Design: Corner/endpoints/payment_action_returns_the_recomputed_account
    """
    ctx = X.accepted_placement(api)
    account = ctx["account"]
    headers = guardian_headers(ctx["member"]["id"])

    validate_success(
        api.record_payment(account["id"], F.payment_payload(23223), headers), 201
    )
    final = validate_success(
        api.record_payment(account["id"], F.payment_payload(100000), headers), 201
    )
    assert final["payments_total_cents"] == 123223
    assert final["balance_cents"] == 0
    assert final["billing_status"] == "PAID_IN_FULL"
    assert final["assessed_cents"] == 123223
    assert final["assessment_variant"] == "PRELIMINARY"

    member = X.read_member(api, ctx["member"]["id"])
    assert member["standing_status"] == "CLEAR"


# --------------------------------------------------------------------------
# The offer-expiry sweep touches only the due rows
# --------------------------------------------------------------------------

def _two_offers_with_split_expiries(api) -> Dict[str, Any]:
    stage = _placement_stage(
        api,
        [ADA, BEN],
        ensemble_overrides={"min_total_size": 2, "max_total_size": 4},
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    ensemble_id = stage["ensemble"]["id"]
    stage["due_offer"] = X.create_placement(
        api,
        stage["auditions"][0]["id"],
        ensemble_id,
        offer_kind="OFFER",
        offer_expires_at="2026-08-15T00:00:00Z",
    )
    stage["later_offer"] = X.create_placement(
        api,
        stage["auditions"][1]["id"],
        ensemble_id,
        offer_kind="OFFER",
        offer_expires_at="2026-08-25T00:00:00Z",
    )
    X.set_clock(api, "2026-08-15T00:00:00Z")
    return stage


def test_sweep_expires_only_the_offer_due_at_the_clock(api):
    """The sweep expires the offer whose expiry equals the clock and leaves the later one open.

    PRD §3.5: "Every placement of that season sitting in `OFFERED` whose `offer_expires_at` is at or before the logical clock moves to `EXPIRED`, decrementing its ensemble's `offered_count`; the ensemble's `version` increments once per affected ensemble; and the waitlist promotion runs for each freed section."

    Design: Corner/endpoints/offer_expiry_sweep_touches_only_the_due_rows
    """
    stage = _two_offers_with_split_expiries(api)

    swept = validate_success(
        api.offer_expiry_sweep(stage["season"]["id"], {}, REGISTRAR_HEADERS)
    )
    assert swept["expired_count"] == 1
    assert swept["promoted_count"] == 0

    assert X.read_placement(api, stage["due_offer"]["id"])["status"] == "EXPIRED"
    later = X.read_placement(api, stage["later_offer"]["id"])
    assert later["status"] == "OFFERED"
    A.assert_instants_equal(later["offer_expires_at"], "2026-08-25T00:00:00Z")

    ensemble = X.read_ensemble(api, stage["ensemble"]["id"])
    assert ensemble["offered_count"] == 1
    assert ensemble["seated_count"] == 0


def test_replayed_sweep_reports_no_further_expiries(api):
    """Running the sweep a second time reports zero expiries and zero promotions.

    PRD §3.5: "The sweep reports how many offers it expired as `expired_count` and how many waitlisted rows it promoted as `promoted_count`."

    Design: Corner/endpoints/offer_expiry_sweep_touches_only_the_due_rows
    """
    stage = _two_offers_with_split_expiries(api)
    validate_success(
        api.offer_expiry_sweep(stage["season"]["id"], {}, REGISTRAR_HEADERS)
    )

    replay = validate_success(
        api.offer_expiry_sweep(stage["season"]["id"], {}, REGISTRAR_HEADERS)
    )
    assert replay["expired_count"] == 0
    assert replay["promoted_count"] == 0

    assert X.read_placement(api, stage["due_offer"]["id"])["status"] == "EXPIRED"
    assert X.read_placement(api, stage["later_offer"]["id"])["status"] == "OFFERED"
    assert X.read_ensemble(api, stage["ensemble"]["id"])["offered_count"] == 1


# --------------------------------------------------------------------------
# The account read exposes the full balance identity
# --------------------------------------------------------------------------

def _account_with_loan_and_one_payment(api) -> Dict[str, Any]:
    ctx = X.accepted_placement(api, instrument_loan_requested=True)
    validate_success(
        api.record_payment(
            ctx["account"]["id"],
            F.payment_payload(20000),
            guardian_headers(ctx["member"]["id"]),
        ),
        201,
    )
    return ctx


def test_account_read_exposes_every_term_of_the_balance_identity(api):
    """The account read shows each balance term, so 123223 less 0 aid plus 4500 loan less 20000 paid is 107723.

    PRD §3.7: "The account's `balance_cents` is then `assessed_cents`, less `aid_effective_cents`, plus `instrument_loan_fee_cents`, less `payments_total_cents`."

    Design: Corner/endpoints/tuition_account_read_exposes_the_full_balance_identity
    """
    ctx = _account_with_loan_and_one_payment(api)

    account = validate_success(
        api.get_tuition_account(ctx["account"]["id"], FINANCE_HEADERS)
    )
    assert account["assessed_cents"] == 123223
    assert account["aid_effective_cents"] == 0
    assert account["instrument_loan_fee_cents"] == 4500
    assert account["payments_total_cents"] == 20000
    assert account["balance_cents"] == 107723
    assert account["billing_status"] == "CURRENT"
    A.assert_balance_identity(account)

    rows, meta = validate_paginated(
        api.list_tuition_accounts(
            guardian_headers(ctx["member"]["id"]),
            params={"member_id": ctx["member"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["balance_cents"] == 107723


def test_string_instrument_loan_is_priced_at_forty_five_hundred_cents(api):
    """A cellist who requested a loan at acceptance is charged the STRING loan fee.

    PRD §3.7: "The instrument loan program is priced at the same moment: when the acceptance requested a loan, `instrument_loan_fee_cents` is 4500 cents for a `STRING` instrument, 6500 cents for a `WIND` instrument and 9000 cents for `PERCUSSION`, selected by `instrument_class_loaned`; when no loan was requested it is 0."

    Design: Corner/endpoints/tuition_account_read_exposes_the_full_balance_identity
    """
    ctx = X.accepted_placement(api, instrument_loan_requested=True)

    account = validate_success(
        api.get_tuition_account(ctx["account"]["id"], FINANCE_HEADERS)
    )
    assert ctx["placement"]["instrument_class_loaned"] == "STRING"
    assert account["instrument_loan_fee_cents"] == 4500
    assert account["assessed_cents"] == 123223
    assert account["balance_cents"] == 127723


def test_preliminary_variant_zeroes_both_discount_components(api):
    """The preliminary assessment leaves both discount components at zero and assessed equal to the gross.

    PRD §3.7: "It forces both discount components to zero — `sibling_discount_cents` is 0 and `loyalty_credit_cents` is 0 — so `assessed_cents` equals the gross tier-adjusted figure exactly."

    Design: Corner/endpoints/tuition_account_read_exposes_the_full_balance_identity
    """
    ctx = X.accepted_placement(
        api, member_overrides={"sibling_enrolled": True, "years_in_org": 3}
    )

    account = validate_success(
        api.get_tuition_account(ctx["account"]["id"], FINANCE_HEADERS)
    )
    assert account["assessment_variant"] == "PRELIMINARY"
    assert account["ensemble_tier"] == "PHILHARMONIC"
    assert account["sibling_discount_cents"] == 0
    assert account["loyalty_credit_cents"] == 0
    assert account["assessed_cents"] == 123223


# --------------------------------------------------------------------------
# Every foreign key is walkable backwards through a list filter
# --------------------------------------------------------------------------

def _seated_player_with_one_concert(api) -> Dict[str, Any]:
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )
    ctx["event"] = event
    ctx["participation"] = X.create_participation(
        api, event["id"], ctx["member"]["id"]
    )
    return ctx


def test_declared_list_filters_walk_every_foreign_key_backwards(api):
    """Each declared equality filter resolves exactly the linked rows, and an unpopulated link resolves to none.

    PRD §2.3: "Ensembles filter on `season_id`, `roster_state`, and `tier`; section quotas on `ensemble_id`, `instrument`, and `balance_state`; musicians on `enrollment_status`, `standing_status`, and `primary_instrument`; adjudicators on `instrument_expertise` and `available_for_panels`; audition slots on `season_id`, `room_code`, `instrument_focus`, and `status`; auditions on `member_id`, `season_id`, `slot_id`, and `status`; rubric sheets on `audition_id`, `panelist_id`, and `revision_round`; placements on `audition_id`, `member_id`, `ensemble_id`, and `status`; chairs on `section_quota_id`, `placement_id`, `member_id`, `predecessor_assignment_id`, and `status`; tuition accounts on `member_id`, `season_id`, `billing_status`, and `aid_status`; calendar events on `ensemble_id`, `soloist_member_id`, `kind`, and `programming_state`; participation rows on `event_id`, `member_id`, `attendance_status`, `performance_eligibility`, and `tour_status`; and seasons on `status`."

    Design: Corner/endpoints/every_foreign_key_is_walkable_backwards_through_a_list_filter
    """
    ctx = _seated_player_with_one_concert(api)
    member_id = ctx["member"]["id"]

    rows, meta = validate_paginated(
        api.list_placements(DIRECTOR_HEADERS, params={"member_id": member_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["placement"]["id"]
    assert rows[0]["status"] == "ACCEPTED"

    rows, meta = validate_paginated(
        api.list_auditions(DIRECTOR_HEADERS, params={"member_id": member_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["audition"]["id"]
    assert rows[0]["status"] == "ADJUDICATED"

    rows, meta = validate_paginated(
        api.list_panel_scores(
            DIRECTOR_HEADERS, params={"audition_id": ctx["audition"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    for row in rows:
        assert row["audition_id"] == ctx["audition"]["id"]
        assert float(row["weighted_total"]) == 80.00

    rows, meta = validate_paginated(
        api.list_event_participations(
            REGISTRAR_HEADERS, params={"event_id": ctx["event"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["participation"]["id"]

    rows, meta = validate_paginated(
        api.list_seat_assignments(
            DIRECTOR_HEADERS,
            params={"predecessor_assignment_id": ctx["seat"]["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_cascade_created_chairs_and_accounts_are_found_only_by_filter(api):
    """The chair and tuition account minted by the acceptance cascade are discovered through their list filters.

    PRD §2.9: "They are discoverable exclusively through their filtered list endpoints, which is why those filters (§2.3) are part of the contract rather than a convenience."

    Design: Corner/endpoints/every_foreign_key_is_walkable_backwards_through_a_list_filter
    """
    ctx = _seated_player_with_one_concert(api)

    rows, meta = validate_paginated(
        api.list_seat_assignments(
            DIRECTOR_HEADERS, params={"placement_id": ctx["placement"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["seat"]["id"]
    assert rows[0]["chair_number"] == 1
    assert rows[0]["is_principal"] is True

    rows, meta = validate_paginated(
        api.list_tuition_accounts(
            FINANCE_HEADERS, params={"season_id": ctx["season"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["account"]["id"]
    assert rows[0]["member_id"] == ctx["member"]["id"]


# --------------------------------------------------------------------------
# Programming behaves differently per soloist selection mode
# --------------------------------------------------------------------------

def test_auto_select_picks_the_principal_ahead_of_the_second_chair(api):
    """Auto-selection picks the principal, because is_principal descending is the first sort key.

    PRD §3.9: "Otherwise the pool is ordered by the candidate's chair `is_principal` descending, so principals come first, then by that chair's `ranking_score` descending, then by the musician's `years_in_org` descending, then by that participation row's `attendance_index` descending, and finally by the chair row's `created_at` ascending; the first row wins."

    Design: Corner/endpoints/programming_behaves_differently_per_soloist_selection_mode
    """
    stage = _two_seated_players_with_concerts(api)
    principal = X.sole_active_seat(api, stage["members"][0]["id"])
    assert principal["chair_number"] == 1
    assert principal["is_principal"] is True

    programmed = validate_success(
        api.program_event(
            stage["concerts"]["AUTO_SELECT"]["id"],
            F.programming_payload(),
            DIRECTOR_HEADERS,
        )
    )
    assert programmed["programming_state"] == "PROGRAMMED"
    assert programmed["soloist_member_id"] == stage["members"][0]["id"]


def test_manual_mode_honours_the_soloist_named_in_the_body(api):
    """Under MANUAL the named second-chair musician is programmed as soloist.

    PRD §3.9: "Under `MANUAL` the caller must name the `soloist_member_id` explicitly, and that musician must hold an `ACTIVE` chair in this ensemble, must have `standing_status` `CLEAR`, and must have `performance_eligibility` `ELIGIBLE` on this very event; any of those failing is `ERR_SOLOIST_NOT_ELIGIBLE`, and per §2.10 that check is evaluated before the guest-artist fee cap."

    Design: Corner/endpoints/programming_behaves_differently_per_soloist_selection_mode
    """
    stage = _two_seated_players_with_concerts(api)
    second_chair = stage["members"][1]["id"]

    programmed = validate_success(
        api.program_event(
            stage["concerts"]["MANUAL"]["id"],
            F.programming_payload(
                soloist_member_id=second_chair,
                guest_artist_name="Vera Guest",
                guest_artist_fee_cents=400000,
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert programmed["programming_state"] == "PROGRAMMED"
    assert programmed["soloist_member_id"] == second_chair
    assert programmed["guest_artist_name"] == "Vera Guest"
    assert programmed["guest_artist_fee_cents"] == 400000


def test_none_mode_programs_the_event_without_consulting_the_pool(api):
    """Under NONE the event reaches PROGRAMMED with no soloist at all.

    PRD §3.9: "Under `NONE` the event is programmed with no soloist and `soloist_member_id` stays null."

    Design: Corner/endpoints/programming_behaves_differently_per_soloist_selection_mode
    """
    stage = _two_seated_players_with_concerts(api)

    programmed = validate_success(
        api.program_event(
            stage["concerts"]["NONE"]["id"],
            F.programming_payload(),
            DIRECTOR_HEADERS,
        )
    )
    assert programmed["programming_state"] == "PROGRAMMED"
    assert programmed["soloist_member_id"] is None
