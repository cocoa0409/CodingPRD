"""Rejection-precedence pairings and pinned numeric boundaries.

Every test builds its own world from the public endpoints, because the harness
restarts the server and empties the database before each test function.
"""

from typing import Any, Dict, List

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
    FINANCE_HEADERS_2,
    REGISTRAR_HEADERS,
    REGISTRAR_HEADERS_2,
    guardian_headers,
)

# A PHILHARMONIC ensemble charges 1.00 times tuition_base_cents, so the
# preliminary assessment is the season base exactly (PRD §3.7).
GROSS_PHILHARMONIC_CENTS = C.SEASON_TUITION_BASE_CENTS  # 123223

REHEARSAL_DAYS = [
    "2026-10-02",
    "2026-10-09",
    "2026-10-16",
    "2026-10-23",
    "2026-10-30",
    "2026-11-06",
]


# --------------------------------------------------------------------------
# Local composite builders
# --------------------------------------------------------------------------

def _auditions_open_season(api, panelist_count: int) -> Dict[str, Any]:
    """A season in `AUDITIONS_OPEN` plus `panelist_count` free CELLO adjudicators."""
    ctx = X.open_season_with_ensemble(api)
    ctx["panelists"] = X.create_panelists(
        api, count=panelist_count, instrument_expertise="CELLO"
    )
    return ctx


def _trio(ctx: Dict[str, Any], first: int) -> List[str]:
    """Three adjudicator ids starting at `first`, so each slot gets a fresh panel."""
    return [p["id"] for p in ctx["panelists"][first:first + 3]]


def _post_slot(api, season_id: str, panelist_ids: List[str], room_code: str,
               start_at: str, end_at: str):
    return api.create_audition_slot(
        F.audition_slot_payload(
            season_id,
            panelist_ids,
            room_code=room_code,
            start_at=start_at,
            end_at=end_at,
        ),
        REGISTRAR_HEADERS,
    )


def _slots_in_room(api, season_id: str, room_code: str):
    return validate_paginated(
        api.list_audition_slots(
            REGISTRAR_HEADERS,
            params={"season_id": season_id, "room_code": room_code, "limit": C.MAX_LIMIT},
        )
    )


def _two_seated_members(api, member_overrides: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A season in `IN_SEASON` with two accepted chairs in one PHILHARMONIC section."""
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(
        api, season["id"], tier="PHILHARMONIC", min_total_size=1, max_total_size=4
    )
    quota = X.create_section_quota(
        api, ensemble["id"], instrument="CELLO", min_count=1, target_count=2, max_count=3
    )
    members = [
        X.create_member(api, primary_instrument="CELLO", **overrides)
        for overrides in member_overrides
    ]
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        instrument_focus="CELLO",
        capacity=4,
    )
    auditions = []
    for member in members:
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        X.submit_uniform_sheets(api, audition["id"], panelists, 20)
        auditions.append(X.adjudicate(api, audition["id"]))
    X.advance_season(api, season["id"], "PLACEMENT")
    for member, audition in zip(members, auditions):
        placement = X.create_placement(
            api, audition["id"], ensemble["id"], offer_kind="OFFER"
        )
        X.accept_placement(api, placement["id"], member["id"])
    accounts = [X.sole_account(api, m["id"], season["id"]) for m in members]
    return {
        "season": X.read_season(api, season["id"]),
        "ensemble": X.read_ensemble(api, ensemble["id"]),
        "quota": X.read_section_quota(api, quota["id"]),
        "members": members,
        "accounts": accounts,
    }


def _approved_aid_account(api) -> Dict[str, Any]:
    """One seated musician whose tuition account has completed the aid waterfall."""
    ctx = X.accepted_placement(
        api, member_overrides={"household_income_band": "BAND_B", "years_in_org": 1}
    )
    member_id = ctx["member"]["id"]
    season_id = ctx["season"]["id"]
    account = ctx["account"]
    validate_success(
        api.request_aid(
            account["id"], F.aid_request_payload(12000), guardian_headers(member_id)
        )
    )
    validate_success(api.review_aid(account["id"], {}, FINANCE_HEADERS))
    validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )
    ctx["account"] = X.read_account(api, account["id"])
    assert ctx["account"]["aid_status"] == "APPROVED", ctx["account"]
    assert ctx["account"]["aid_awarded_cents"] == 12000, ctx["account"]
    return ctx


def _seated_member_with_two_manual_concerts(api) -> Dict[str, Any]:
    """Two MANUAL concerts; only concert A's participation has been reviewed."""
    ctx = X.accepted_placement(api)
    member_id = ctx["member"]["id"]
    ensemble_id = ctx["ensemble"]["id"]
    rehearsal = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="REHEARSAL",
        start_at="2026-09-05T19:00:00Z",
        end_at="2026-09-05T21:00:00Z",
    )
    concert_a = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-10-03T19:00:00Z",
        end_at="2026-10-03T21:00:00Z",
        eligibility_window_start="2026-09-01T00:00:00Z",
        soloist_selection_mode="MANUAL",
    )
    concert_b = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-10-10T19:00:00Z",
        end_at="2026-10-10T21:00:00Z",
        eligibility_window_start="2026-09-01T00:00:00Z",
        soloist_selection_mode="MANUAL",
    )
    row_rehearsal = X.create_participation(api, rehearsal["id"], member_id)
    row_a = X.create_participation(api, concert_a["id"], member_id)
    row_b = X.create_participation(api, concert_b["id"], member_id)
    X.set_clock(api, "2026-09-05T19:30:00Z")
    X.record_attendance(api, row_rehearsal["id"], "PRESENT")
    row_a = X.review_eligibility(api, row_a["id"])
    assert row_a["performance_eligibility"] == "ELIGIBLE", row_a
    assert float(row_a["attendance_index"]) == 100.00, row_a
    row_b = X.read_participation(api, row_b["id"])
    assert row_b["performance_eligibility"] == "UNREVIEWED", row_b
    ctx.update(
        {
            "concert_a": concert_a,
            "concert_b": concert_b,
            "row_a": row_a,
            "row_b": row_b,
        }
    )
    return ctx


def _seated_member_with_rehearsal_series(api) -> Dict[str, Any]:
    """Six weekly rehearsals and two concerts; the first five rehearsals recorded."""
    ctx = X.accepted_placement(api)
    member_id = ctx["member"]["id"]
    ensemble_id = ctx["ensemble"]["id"]
    rehearsals = [
        X.create_ensemble_event(
            api,
            ensemble_id,
            kind="REHEARSAL",
            start_at=f"{day}T19:00:00Z",
            end_at=f"{day}T21:00:00Z",
        )
        for day in REHEARSAL_DAYS
    ]
    concert_a = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-11-05T19:00:00Z",
        end_at="2026-11-05T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="NONE",
    )
    concert_b = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-11-20T19:00:00Z",
        end_at="2026-11-20T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="NONE",
    )
    rehearsal_rows = [
        X.create_participation(api, rehearsal["id"], member_id)
        for rehearsal in rehearsals
    ]
    row_a = X.create_participation(api, concert_a["id"], member_id)
    row_b = X.create_participation(api, concert_b["id"], member_id)
    # Every one of the first five rehearsals has already begun at this instant.
    X.set_clock(api, "2026-10-30T19:30:00Z")
    for row in rehearsal_rows[:4]:
        X.record_attendance(api, row["id"], "PRESENT")
    X.record_attendance(api, rehearsal_rows[4]["id"], "UNEXCUSED_ABSENT")
    return {
        "member": X.read_member(api, member_id),
        "rehearsal_rows": rehearsal_rows,
        "concert_a": concert_a,
        "concert_b": concert_b,
        "row_a": row_a,
        "row_b": row_b,
    }


# --------------------------------------------------------------------------
# State band outranks the fiscal band on an aid request
# --------------------------------------------------------------------------

def test_oversized_aid_request_on_approved_account_reports_state_error(api):
    """An aid request that is both inadmissible in state and oversized reports the state error.

    PRD §2.10: "An oversized aid request on an account that is already approved reports the aid state error, not the fiscal size error, because state outranks fiscal."

    Design: Difficulty/priority_pair_validation_conflict/aid_request_state_band_beats_fiscal_band
    """
    ctx = _approved_aid_account(api)
    account = ctx["account"]
    assert account["assessed_cents"] == GROSS_PHILHARMONIC_CENTS, account

    response = api.request_aid(
        account["id"],
        F.aid_request_payload(999999),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE.value)

    after = X.read_account(api, account["id"])
    assert after["aid_status"] == "APPROVED"
    assert after["aid_awarded_cents"] == 12000
    assert after["aid_effective_cents"] == 12000

    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_committed_cents"] == 12000
    assert season["aid_available_cents"] == 88000
    A.assert_aid_pool_conserved(season)


def test_oversized_aid_request_alone_reports_the_fiscal_error(api):
    """An oversized request on an account in an admissible aid state reports the fiscal error.

    PRD §3.7: "The requested amount must be strictly greater than 0 and no greater than the account's `assessed_cents`; otherwise `ERR_AID_REQUEST_EXCEEDS_ASSESSMENT`."

    Design: Difficulty/priority_pair_validation_conflict/aid_request_state_band_beats_fiscal_band
    """
    ctx = X.accepted_placement(
        api, member_overrides={"household_income_band": "BAND_B", "years_in_org": 1}
    )
    account = ctx["account"]
    assert account["aid_status"] == "NONE"
    assert account["assessed_cents"] == GROSS_PHILHARMONIC_CENTS

    response = api.request_aid(
        account["id"],
        F.aid_request_payload(999999),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_AID_REQUEST_EXCEEDS_ASSESSMENT.value)

    after = X.read_account(api, account["id"])
    assert after["aid_status"] == "NONE"
    assert after["aid_requested_cents"] == 0


def test_in_range_aid_request_on_approved_account_reports_state_error(api):
    """A request well inside the assessment is still refused on an APPROVED account.

    PRD §3.7: "The request is admissible only from `NONE`, `DENIED` or `RESCINDED`; from `REQUESTED`, `UNDER_REVIEW` or `APPROVED` it is refused with `ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE`, and because that state check outranks the fiscal band, an oversized request on an already-approved account reports the state error rather than the size error."

    Design: Difficulty/priority_pair_validation_conflict/aid_request_state_band_beats_fiscal_band
    """
    ctx = _approved_aid_account(api)
    account = ctx["account"]

    response = api.request_aid(
        account["id"],
        F.aid_request_payload(5000),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_AID_REQUEST_NOT_ALLOWED_IN_STATE.value)

    after = X.read_account(api, account["id"])
    assert after["aid_status"] == "APPROVED"
    assert after["aid_requested_cents"] == 12000
    assert after["aid_awarded_cents"] == 12000


# --------------------------------------------------------------------------
# Safety band outranks the fiscal band when programming a performance
# --------------------------------------------------------------------------

def test_ineligible_soloist_with_over_cap_fee_reports_soloist_error(api):
    """Naming an unreviewed soloist while also busting the guest-artist cap reports the soloist error.

    PRD §2.10: "Naming an ineligible soloist while also exceeding the guest-artist fee cap reports the soloist error, because safety outranks fiscal."

    Design: Difficulty/priority_pair_validation_conflict/soloist_safety_band_beats_guest_fee_band
    """
    ctx = _seated_member_with_two_manual_concerts(api)

    response = api.program_event(
        ctx["concert_b"]["id"],
        F.programming_payload(
            soloist_member_id=ctx["member"]["id"],
            guest_artist_name="Vera Guest",
            guest_artist_fee_cents=600000,
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SOLOIST_NOT_ELIGIBLE.value)

    after = X.read_event(api, ctx["concert_b"]["id"])
    assert after["programming_state"] == "DRAFT"
    assert after["soloist_member_id"] is None
    assert after["guest_artist_fee_cents"] == 0


def test_over_cap_fee_alone_reports_the_guest_artist_fee_error(api):
    """With an eligible soloist named, the over-cap guest-artist fee is what surfaces.

    PRD §3.9: "The guest-artist figures are constrained: `guest_artist_fee_cents` may not exceed 500000 cents, and a `guest_artist_fee_cents` above 0 must be accompanied by a `guest_artist_name`; either breach is `ERR_GUEST_ARTIST_FEE_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/soloist_safety_band_beats_guest_fee_band
    """
    ctx = _seated_member_with_two_manual_concerts(api)

    response = api.program_event(
        ctx["concert_a"]["id"],
        F.programming_payload(
            soloist_member_id=ctx["member"]["id"],
            guest_artist_name="Vera Guest",
            guest_artist_fee_cents=600000,
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_GUEST_ARTIST_FEE_CAP_EXCEEDED.value)
    assert X.read_event(api, ctx["concert_a"]["id"])["programming_state"] == "DRAFT"

    programmed = validate_success(
        api.program_event(
            ctx["concert_a"]["id"],
            F.programming_payload(
                soloist_member_id=ctx["member"]["id"],
                guest_artist_name="Vera Guest",
                guest_artist_fee_cents=100000,
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert programmed["programming_state"] == "PROGRAMMED"
    assert programmed["soloist_member_id"] == ctx["member"]["id"]
    assert programmed["guest_artist_name"] == "Vera Guest"
    assert programmed["guest_artist_fee_cents"] == 100000


def test_unreviewed_soloist_alone_reports_the_soloist_error(api):
    """A soloist whose eligibility on this very event is UNREVIEWED is refused on its own.

    PRD §3.9: "Under `MANUAL` the caller must name the `soloist_member_id` explicitly, and that musician must hold an `ACTIVE` chair in this ensemble, must have `standing_status` `CLEAR`, and must have `performance_eligibility` `ELIGIBLE` on this very event; any of those failing is `ERR_SOLOIST_NOT_ELIGIBLE`, and per §2.10 that check is evaluated before the guest-artist fee cap."

    Design: Difficulty/priority_pair_validation_conflict/soloist_safety_band_beats_guest_fee_band
    """
    ctx = _seated_member_with_two_manual_concerts(api)

    response = api.program_event(
        ctx["concert_b"]["id"],
        F.programming_payload(
            soloist_member_id=ctx["member"]["id"],
            guest_artist_name="Vera Guest",
            guest_artist_fee_cents=100000,
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SOLOIST_NOT_ELIGIBLE.value)

    after = X.read_event(api, ctx["concert_b"]["id"])
    assert after["programming_state"] == "DRAFT"
    assert after["soloist_member_id"] is None
    assert after["guest_artist_fee_cents"] == 0


# --------------------------------------------------------------------------
# Temporal band outranks the interval-overlap band on an audition slot
# --------------------------------------------------------------------------

def test_slot_past_window_and_room_collision_reports_window_error(api):
    """A slot that both escapes the audition window and buffer-collides reports the window error.

    PRD §2.10: "An audition slot that falls outside the season's audition window *and* double-books its room reports the window error, because temporal outranks interval overlap."

    Design: Difficulty/priority_pair_validation_conflict/slot_window_band_beats_room_overlap_band
    """
    ctx = _auditions_open_season(api, 6)
    season_id = ctx["season"]["id"]
    assert ctx["season"]["audition_window_end"].startswith("2026-08-20T18:00:00")
    X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-20T17:00:00Z",
        end_at="2026-08-20T17:30:00Z",
    )

    response = _post_slot(
        api, season_id, _trio(ctx, 3), "R1",
        "2026-08-20T17:40:00Z", "2026-08-20T18:10:00Z",
    )
    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_AUDITION_WINDOW.value)

    rows, meta = _slots_in_room(api, season_id, "R1")
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_room_collision_inside_the_window_reports_room_error(api):
    """A slot inside the window that sits inside the fifteen-minute buffer reports the room error.

    PRD §3.3: "Two slots in the same `room_code` conflict when the first slot's `start_at` is earlier than the second slot's `end_at` advanced by fifteen minutes, and simultaneously the second slot's `start_at` is earlier than the first slot's `end_at` advanced by fifteen minutes."

    Design: Difficulty/priority_pair_validation_conflict/slot_window_band_beats_room_overlap_band
    """
    ctx = _auditions_open_season(api, 6)
    season_id = ctx["season"]["id"]
    X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-20T17:00:00Z",
        end_at="2026-08-20T17:30:00Z",
    )

    response = _post_slot(
        api, season_id, _trio(ctx, 3), "R1",
        "2026-08-20T17:40:00Z", "2026-08-20T17:55:00Z",
    )
    validate_error(response, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)

    rows, meta = _slots_in_room(api, season_id, "R1")
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_slot_past_window_in_an_empty_room_reports_window_error(api):
    """A slot whose end_at escapes the audition window is refused even in an unused room.

    PRD §3.3: "Slot times must be contained in the season's audition window: `start_at` must be at or after `audition_window_start`, and `end_at` must be at or before `audition_window_end`."

    Design: Difficulty/priority_pair_validation_conflict/slot_window_band_beats_room_overlap_band
    """
    ctx = _auditions_open_season(api, 6)
    season_id = ctx["season"]["id"]
    X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-20T17:00:00Z",
        end_at="2026-08-20T17:30:00Z",
    )

    response = _post_slot(
        api, season_id, _trio(ctx, 3), "R9",
        "2026-08-20T17:40:00Z", "2026-08-20T18:10:00Z",
    )
    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_AUDITION_WINDOW.value)

    _, meta = _slots_in_room(api, season_id, "R9")
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# The attendance index threshold: exactly 80.00 against 79.17
# --------------------------------------------------------------------------

def test_attendance_index_of_exactly_80_is_eligible(api):
    """Four PRESENT rows and one UNEXCUSED_ABSENT row give exactly 80.00 and grant eligibility.

    PRD §3.8: "Eligibility is granted only when three conditions all hold: `attendance_index` is at least 80.00; when the performance's `dress_rehearsal_required` is true, the musician's participation on the latest dress-rehearsal-flagged `REHEARSAL` of that ensemble inside the window carries `attendance_status` `PRESENT`; and the musician's `standing_status` is not `ATTENDANCE_PROBATION`."

    Design: Difficulty/boundary_precision_check/attendance_index_exactly_80_vs_79_17
    """
    ctx = _seated_member_with_rehearsal_series(api)

    # One effective unexcused absence is short of the probation threshold of three,
    # so the standing condition cannot be the deciding factor.
    member = X.read_member(api, ctx["member"]["id"])
    assert member["unexcused_absence_count"] == 1
    assert member["effective_unexcused_count"] == 1
    assert member["standing_status"] == "CLEAR"

    reviewed = X.review_eligibility(api, ctx["row_a"]["id"])
    assert float(reviewed["attendance_index"]) == 80.00
    A.assert_two_decimal_places(reviewed["attendance_index"])
    assert reviewed["performance_eligibility"] == "ELIGIBLE"
    assert reviewed["ineligibility_reason"] == "NONE"


def test_attendance_index_of_79_17_is_ineligible(api):
    """Adding one EXCUSED_ABSENT row drops the index to 79.17 and refuses eligibility.

    PRD §3.8: "The threshold is inclusive and the boundary is observable: four `PRESENT` rows and one `UNEXCUSED_ABSENT` row over five counted rows give exactly 80.00 and are eligible, while four `PRESENT`, one `EXCUSED_ABSENT` and one `UNEXCUSED_ABSENT` over six counted rows give 79.17 (from an exact 79.1666…) and are not."

    Design: Difficulty/boundary_precision_check/attendance_index_exactly_80_vs_79_17
    """
    ctx = _seated_member_with_rehearsal_series(api)
    sixth_row_id = ctx["rehearsal_rows"][5]["id"]
    member_id = ctx["member"]["id"]

    X.set_clock(api, "2026-11-06T19:30:00Z")
    X.record_attendance(api, sixth_row_id, "ABSENCE_UNVERIFIED")
    validate_success(
        api.request_excuse(
            sixth_row_id,
            F.excuse_request_payload("ILLNESS", excuse_documentation_ref="DOC-1"),
            guardian_headers(member_id),
        )
    )
    decided = validate_success(
        api.decide_excuse(
            sixth_row_id,
            F.excuse_decision_payload("APPROVED"),
            REGISTRAR_HEADERS_2,
        )
    )
    assert decided["attendance_status"] == "EXCUSED_ABSENT"

    member = X.read_member(api, member_id)
    assert member["effective_unexcused_count"] == 1
    assert member["standing_status"] == "CLEAR"

    reviewed = X.review_eligibility(api, ctx["row_b"]["id"])
    assert float(reviewed["attendance_index"]) == 79.17
    A.assert_two_decimal_places(reviewed["attendance_index"])
    assert reviewed["performance_eligibility"] == "INELIGIBLE"
    assert reviewed["ineligibility_reason"] == "ATTENDANCE_INDEX_BELOW_THRESHOLD"


# --------------------------------------------------------------------------
# The minimum-award floor: exactly 5000 cents against 4999
# --------------------------------------------------------------------------

def test_candidate_grant_of_exactly_5000_cents_is_approved(api):
    """A clamped grant of exactly the 5000-cent floor is funded, because the test is inclusive.

    PRD §3.7: "If that candidate grant is at least 5000 cents, the account is approved — `aid_awarded_cents` is set to the grant, `aid_effective_cents` is set to the same grant (uncapped, because `assessment_variant` is still `PRELIMINARY`), `aid_awarded_by_user_id` records the acting officer, `aid_status` becomes `APPROVED`, the running remainder decreases by the grant, and the season's `aid_committed_cents` increases by the grant."

    Design: Difficulty/boundary_precision_check/aid_min_award_floor_5000_vs_4999
    """
    ctx = _two_seated_members(
        api,
        [
            {"legal_name": "Floor One", "household_income_band": "BAND_A", "years_in_org": 2},
            {"legal_name": "Floor Two", "household_income_band": "BAND_C", "years_in_org": 0},
        ],
    )
    season_id = ctx["season"]["id"]
    account_one, account_two = ctx["accounts"]
    member_one, member_two = ctx["members"]

    validate_success(
        api.request_aid(
            account_one["id"],
            F.aid_request_payload(5000),
            guardian_headers(member_one["id"]),
        )
    )
    validate_success(
        api.request_aid(
            account_two["id"],
            F.aid_request_payload(4999),
            guardian_headers(member_two["id"]),
        )
    )
    validate_success(api.review_aid(account_one["id"], {}, FINANCE_HEADERS))
    validate_success(api.review_aid(account_two["id"], {}, FINANCE_HEADERS))

    # BAND_A 40 + 3 x 2 seniority years + PHILHARMONIC 3 puts account one first.
    assert X.read_account(api, account_one["id"])["aid_need_score"] == 49
    assert X.read_account(api, account_two["id"])["aid_need_score"] == 13

    run = validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )
    assert run["approved_count"] == 1

    funded = X.read_account(api, account_one["id"])
    assert funded["aid_status"] == "APPROVED"
    assert funded["aid_awarded_cents"] == 5000
    assert funded["aid_effective_cents"] == 5000
    assert funded["aid_denial_reason"] == "NONE"
    assert funded["balance_cents"] == GROSS_PHILHARMONIC_CENTS - 5000
    A.assert_balance_identity(funded)

    season = X.read_season(api, season_id)
    assert season["aid_committed_cents"] == 5000
    A.assert_aid_pool_conserved(season)


def test_candidate_grant_of_4999_cents_is_denied_below_min_award(api):
    """A clamped grant one cent under the floor is denied and consumes nothing from the pool.

    PRD §3.7: "If the candidate grant falls below 5000 cents, the account is denied instead — `aid_awarded_cents` is set to 0, `aid_status` becomes `DENIED`, and `aid_denial_reason` records `INSUFFICIENT_BUDGET` when the running remainder was the binding constraint by being itself below 5000 cents, and `BELOW_MIN_AWARD` otherwise."

    Design: Difficulty/boundary_precision_check/aid_min_award_floor_5000_vs_4999
    """
    ctx = _two_seated_members(
        api,
        [
            {"legal_name": "Floor One", "household_income_band": "BAND_A", "years_in_org": 2},
            {"legal_name": "Floor Two", "household_income_band": "BAND_C", "years_in_org": 0},
        ],
    )
    season_id = ctx["season"]["id"]
    account_one, account_two = ctx["accounts"]
    member_one, member_two = ctx["members"]

    validate_success(
        api.request_aid(
            account_one["id"],
            F.aid_request_payload(5000),
            guardian_headers(member_one["id"]),
        )
    )
    validate_success(
        api.request_aid(
            account_two["id"],
            F.aid_request_payload(4999),
            guardian_headers(member_two["id"]),
        )
    )
    validate_success(api.review_aid(account_one["id"], {}, FINANCE_HEADERS))
    validate_success(api.review_aid(account_two["id"], {}, FINANCE_HEADERS))

    run = validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )
    assert run["denied_count"] == 1

    refused = X.read_account(api, account_two["id"])
    assert refused["aid_status"] == "DENIED"
    assert refused["aid_awarded_cents"] == 0
    assert refused["aid_effective_cents"] == 0
    assert refused["aid_denial_reason"] == "BELOW_MIN_AWARD"
    assert refused["balance_cents"] == GROSS_PHILHARMONIC_CENTS
    A.assert_balance_identity(refused)

    # Only the 5000-cent grant ahead of it moved money; the denial took nothing.
    season = X.read_season(api, season_id)
    assert season["aid_committed_cents"] == 5000
    assert season["aid_available_cents"] == C.SEASON_AID_BUDGET_CENTS - 5000
    A.assert_aid_pool_conserved(season)


# --------------------------------------------------------------------------
# The room turnover buffer: a gap of exactly fifteen minutes against fourteen
# --------------------------------------------------------------------------

def test_room_gap_of_exactly_fifteen_minutes_is_accepted(api):
    """Two slots in one room separated by exactly fifteen minutes do not conflict.

    PRD §3.3: "Both comparisons are strict, which pins the boundary precisely: two slots in the same room separated by a gap of exactly fifteen minutes do not conflict, while a gap of fourteen minutes does."

    Design: Difficulty/boundary_precision_check/room_buffer_gap_15_vs_14_minutes
    """
    ctx = _auditions_open_season(api, 6)
    season_id = ctx["season"]["id"]
    first = X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T10:30:00Z",
    )
    assert A.shift_instant(first["end_at"], minutes=15) == "2026-08-12T10:45:00Z"

    created = validate_success(
        _post_slot(
            api, season_id, _trio(ctx, 3), "R1",
            "2026-08-12T10:45:00Z", "2026-08-12T11:15:00Z",
        ),
        201,
    )
    assert created["status"] == "OPEN"
    assert created["booked_count"] == 0

    _, meta = _slots_in_room(api, season_id, "R1")
    assert meta["total_count"] == 2


def test_room_gap_of_fourteen_minutes_is_double_booked(api):
    """Two slots in one room separated by fourteen minutes collide inside the turnover buffer.

    PRD §3.3: "Both comparisons are strict, which pins the boundary precisely: two slots in the same room separated by a gap of exactly fifteen minutes do not conflict, while a gap of fourteen minutes does."

    Design: Difficulty/boundary_precision_check/room_buffer_gap_15_vs_14_minutes
    """
    ctx = _auditions_open_season(api, 9)
    season_id = ctx["season"]["id"]
    X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T10:30:00Z",
    )
    second = validate_success(
        _post_slot(
            api, season_id, _trio(ctx, 3), "R1",
            "2026-08-12T10:45:00Z", "2026-08-12T11:15:00Z",
        ),
        201,
    )
    assert second["end_at"].startswith("2026-08-12T11:15:00")

    response = _post_slot(
        api, season_id, _trio(ctx, 6), "R1",
        "2026-08-12T11:29:00Z", "2026-08-12T11:59:00Z",
    )
    validate_error(response, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)

    _, meta = _slots_in_room(api, season_id, "R1")
    assert meta["total_count"] == 2


def test_room_gap_of_exactly_fifteen_minutes_survives_a_refused_neighbour(api):
    """After the fourteen-minute attempt is refused, the same slot moved to a fifteen-minute gap lands.

    PRD §3.3: "Both comparisons are strict, which pins the boundary precisely: two slots in the same room separated by a gap of exactly fifteen minutes do not conflict, while a gap of fourteen minutes does."

    Design: Difficulty/boundary_precision_check/room_buffer_gap_15_vs_14_minutes
    """
    ctx = _auditions_open_season(api, 9)
    season_id = ctx["season"]["id"]
    X.create_audition_slot(
        api,
        season_id,
        _trio(ctx, 0),
        room_code="R1",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T10:30:00Z",
    )
    validate_success(
        _post_slot(
            api, season_id, _trio(ctx, 3), "R1",
            "2026-08-12T10:45:00Z", "2026-08-12T11:15:00Z",
        ),
        201,
    )
    validate_error(
        _post_slot(
            api, season_id, _trio(ctx, 6), "R1",
            "2026-08-12T11:29:00Z", "2026-08-12T11:59:00Z",
        ),
        ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value,
    )

    created = validate_success(
        _post_slot(
            api, season_id, _trio(ctx, 6), "R1",
            "2026-08-12T11:30:00Z", "2026-08-12T12:00:00Z",
        ),
        201,
    )
    assert created["status"] == "OPEN"
    assert created["booked_count"] == 0

    rows, meta = _slots_in_room(api, season_id, "R1")
    assert meta["total_count"] == 3
    for row in rows:
        assert row["booked_count"] == 0
        assert row["status"] == "OPEN"
