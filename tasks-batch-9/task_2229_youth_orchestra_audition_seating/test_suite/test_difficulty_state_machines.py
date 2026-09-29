"""Non-linear state machines and transitive cascades.

Every test builds its own world from the public endpoints: the harness restarts
the server and empties the database before each test, so nothing here may lean
on a row another test created.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import validate_success

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
    REGISTRAR_USER_ID,
    REGISTRAR_USER_ID_2,
    guardian_headers,
)

# --------------------------------------------------------------------------
# Rubric sheets whose weighted totals the PRD arithmetic pins exactly.
# weighted_total = 1.2*tone + 1.0*rhythm + 1.0*intonation + 0.8*sight (PRD §3.4)
# --------------------------------------------------------------------------

# 1.2*22 + 20 + 21 + 0.8*18 = 26.4 + 20 + 21 + 14.4 = 81.80
_RUBRIC_81_80 = {
    "tone_score": 22,
    "rhythm_score": 20,
    "intonation_score": 21,
    "sight_reading_score": 18,
}
# 1.2*21 + 20 + 20 + 0.8*18 = 25.2 + 20 + 20 + 14.4 = 79.60
_RUBRIC_79_60 = {
    "tone_score": 21,
    "rhythm_score": 20,
    "intonation_score": 20,
    "sight_reading_score": 18,
}
# 1.2*18 + 17 + 16 + 0.8*15 = 21.6 + 17 + 16 + 12.0 = 66.60
_RUBRIC_66_60 = {
    "tone_score": 18,
    "rhythm_score": 17,
    "intonation_score": 16,
    "sight_reading_score": 15,
}
# 1.2*25 + 24 + 23 + 0.8*22 = 30.0 + 24 + 23 + 17.6 = 94.60
_RUBRIC_94_60 = {
    "tone_score": 25,
    "rhythm_score": 24,
    "intonation_score": 23,
    "sight_reading_score": 22,
}

_CLOCK = C.FIXTURE_CLOCK  # 2026-08-05T09:00:00Z
_OFFER_EXPIRES_AT = "2026-08-25T00:00:00Z"
_PHILHARMONIC_GROSS_CENTS = 123223  # 1.00 x tuition_base_cents 123223


# --------------------------------------------------------------------------
# Local builders (the shared fixtures only submit uniform rubric sheets, and
# these scenarios need specific weighted totals and specific section bounds).
# --------------------------------------------------------------------------

def _open_violin_season(
    api,
    slot_capacity: int = 4,
    season_overrides: Optional[Dict[str, Any]] = None,
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A season in AUDITIONS_OPEN with one PHILHARMONIC ensemble, one VIOLIN
    section, three VIOLIN adjudicators and one open slot."""
    ensemble_defaults = {
        "name": "Philharmonic",
        "tier": "PHILHARMONIC",
        "min_total_size": 1,
        "max_total_size": 4,
        "rehearsal_weekday": "SAT",
    }
    ensemble_defaults.update(ensemble_overrides or {})
    quota_defaults = {
        "instrument": "VIOLIN",
        "min_count": 1,
        "target_count": 1,
        "max_count": 2,
    }
    quota_defaults.update(quota_overrides or {})
    ctx = X.open_season_with_ensemble(
        api,
        clock=_CLOCK,
        season_overrides=season_overrides,
        ensemble_overrides=ensemble_defaults,
        quota_overrides=quota_defaults,
    )
    ctx["panelists"] = X.create_panelists(api, count=3, instrument_expertise="VIOLIN")
    ctx["slot"] = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in ctx["panelists"]],
        instrument_focus="VIOLIN",
        capacity=slot_capacity,
    )
    return ctx


def _violin_member(api, legal_name: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name,
        "primary_instrument": "VIOLIN",
        "grade_level": 10,
        "graduation_year": 2028,
        "household_income_band": "BAND_B",
        "years_in_org": 1,
    }
    payload.update(overrides)
    return X.create_member(api, **payload)


def _scored_violin_audition(
    api,
    ctx: Dict[str, Any],
    rubric: Dict[str, int],
    legal_name: str,
    slot_id: Optional[str] = None,
    **member_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Register a musician, book them, and drive a full quorum of sheets."""
    member = _violin_member(api, legal_name, **member_overrides)
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])
    X.schedule_audition(api, audition["id"], slot_id or ctx["slot"]["id"])
    for panelist in ctx["panelists"]:
        X.submit_sheet(api, audition["id"], panelist["id"], **rubric)
    return member, X.read_audition(api, audition["id"])


def _adjudicated_violin_audition(
    api, ctx: Dict[str, Any], rubric: Dict[str, int], legal_name: str, **member_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    member, audition = _scored_violin_audition(
        api, ctx, rubric, legal_name, **member_overrides
    )
    return member, X.adjudicate(api, audition["id"])


def _offered_violin_placement(
    api,
    season_overrides: Optional[Dict[str, Any]] = None,
    **member_overrides: Any,
) -> Dict[str, Any]:
    """One OFFERED placement on a season standing in PLACEMENT."""
    ctx = _open_violin_season(api, slot_capacity=1, season_overrides=season_overrides)
    member, audition = _adjudicated_violin_audition(
        api, ctx, _RUBRIC_81_80, "Cascade Case", **member_overrides
    )
    ctx["season"] = X.advance_season(api, ctx["season"]["id"], "PLACEMENT")
    ctx["member"] = member
    ctx["audition"] = audition
    ctx["placement"] = X.create_placement(
        api,
        audition["id"],
        ctx["ensemble"]["id"],
        offer_kind="OFFER",
        offer_expires_at=_OFFER_EXPIRES_AT,
    )
    return ctx


def _seated_violin_member(api, season_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Accept the single offer, which seats the player and lands the season in
    IN_SEASON."""
    ctx = _offered_violin_placement(api, season_overrides=season_overrides)
    ctx["placement"] = X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )
    return ctx


def _rehearsal(api, ensemble_id: str, day: str) -> Dict[str, Any]:
    return X.create_ensemble_event(
        api,
        ensemble_id,
        kind="REHEARSAL",
        start_at=f"{day}T18:00:00Z",
        end_at=f"{day}T20:00:00Z",
        venue_code="HALL-A",
    )


def _sheets_for(api, audition_id: str) -> List[Dict[str, Any]]:
    return X.list_sheets(api, audition_id=audition_id)


# ==========================================================================
# Instance: audition_revision_cycle_recomputes_composite_from_new_round
# ==========================================================================

def _revision_ctx(api) -> Dict[str, Any]:
    """A SCORED VIOLIN audition at 66.60 plus a second slot on the next day."""
    ctx = _open_violin_season(api, slot_capacity=1)
    ctx["slot2"] = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in ctx["panelists"]],
        instrument_focus="VIOLIN",
        capacity=1,
        start_at="2026-08-13T10:00:00Z",
        end_at="2026-08-13T10:30:00Z",
    )
    member, audition = _scored_violin_audition(
        api, ctx, _RUBRIC_66_60, "Revision Case"
    )
    ctx["member"] = member
    ctx["audition"] = audition
    return ctx


def test_revision_request_clears_the_provisional_composite_and_the_slot(api):
    """Requesting a revision advances the round, clears the provisional composite and releases the slot id.

    PRD §3.4: "The revision increments `revision_round` by one, clears `composite_provisional_score` back to null, decrements the previously held slot's `booked_count` by one and returns that slot's `status` to `OPEN` when its count falls below `capacity`, and clears the audition's `slot_id` to null."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    before = ctx["audition"]
    assert before["status"] == "SCORED"
    assert before["revision_round"] == 0
    assert before["composite_provisional_score"] == 66.60

    revised = validate_success(
        api.request_revision(before["id"], {}, DIRECTOR_HEADERS)
    )
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_round"] == 1
    assert revised["composite_provisional_score"] is None
    assert revised["slot_id"] is None


def test_revision_returns_the_released_slot_to_open(api):
    """The slot the revision released drops back to booked_count 0 and status OPEN.

    PRD §3.4: "The revision increments `revision_round` by one, clears `composite_provisional_score` back to null, decrements the previously held slot's `booked_count` by one and returns that slot's `status` to `OPEN` when its count falls below `capacity`, and clears the audition's `slot_id` to null."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    held = X.read_audition_slot(api, ctx["slot"]["id"])
    assert held["booked_count"] == 1
    assert held["status"] == "FULL"

    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))

    released = X.read_audition_slot(api, ctx["slot"]["id"])
    assert released["booked_count"] == 0
    assert released["status"] == "OPEN"


def test_revision_bumps_the_audition_and_released_slot_versions_by_one(api):
    """A revision request increments exactly two version counters, each by one.

    PRD §3.4: "Both the audition's `version` and the released slot's `version` increment by one each."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    audition_version_before = ctx["audition"]["version"]
    slot_version_before = X.read_audition_slot(api, ctx["slot"]["id"])["version"]

    revised = validate_success(
        api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS)
    )

    assert revised["version"] == audition_version_before + 1
    released = X.read_audition_slot(api, ctx["slot"]["id"])
    assert released["version"] == slot_version_before + 1


def test_rebooking_a_revision_requested_audition_returns_it_to_scheduled(api):
    """The registrar re-books a revision-requested audition onto a fresh slot.

    PRD §3.4: "Booking the audition into a slot advances it `REQUESTED → SCHEDULED`, and the same registrar action re-books a musician sent back for another round, advancing `REVISION_REQUESTED → SCHEDULED`; from any other status the attempt is `ERR_INVALID_STATE_FOR_OPERATION`."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))

    rebooked = X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])

    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["slot_id"] == ctx["slot2"]["id"]
    assert rebooked["revision_round"] == 1


def test_submitted_score_count_restarts_at_zero_for_the_new_round(api):
    """After the revision the sheet count reflects only the current round, so it reads 0.

    PRD §3.4: "The audition's `submitted_score_count` counts the sheets belonging to its *current* `revision_round`."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    assert ctx["audition"]["submitted_score_count"] == 3

    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))
    rebooked = X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])

    assert rebooked["submitted_score_count"] == 0
    assert len(_sheets_for(api, ctx["audition"]["id"])) == 3


def test_round_one_quorum_recomputes_the_provisional_composite(api):
    """The second round's quorum re-scores the audition from its own sheets alone.

    PRD §3.4: "When that count reaches the slot's `quorum_required`, the server advances the audition `SCHEDULED → SCORED` and stores `composite_provisional_score`: the plain arithmetic mean of the `weighted_total` values of every sheet in the current round, rounded half up to two decimal places, with no trimming whatever the number of sheets."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))
    X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])
    for panelist in ctx["panelists"]:
        X.submit_sheet(api, ctx["audition"]["id"], panelist["id"], **_RUBRIC_94_60)

    scored = X.read_audition(api, ctx["audition"]["id"])
    assert scored["status"] == "SCORED"
    assert scored["submitted_score_count"] == 3
    assert scored["composite_provisional_score"] == 94.60


def test_final_composite_after_a_revision_excludes_the_round_zero_sheets(api):
    """Adjudication after a revision averages only the current round's three sheets.

    PRD §3.4: "Sheets from earlier rounds are retained in the database but permanently excluded from both composite variants, which is precisely what makes a revision observable in the arithmetic."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))
    X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])
    for panelist in ctx["panelists"]:
        X.submit_sheet(api, ctx["audition"]["id"], panelist["id"], **_RUBRIC_94_60)

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["composite_final_score"] == 94.60
    assert adjudicated["composite_provisional_score"] == 94.60


def test_tier_recommendation_follows_the_post_revision_composite(api):
    """A post-revision composite of 94.60 clears the 85.00 rung, so the band is SYMPHONY.

    PRD §3.4: "Immediately after the final composite is stored, `tier_recommendation` is derived from it by three inclusive threshold comparisons on the two-decimal value: a composite of at least 85.00 recommends `SYMPHONY`; otherwise a composite of at least 75.00 recommends `PHILHARMONIC`; otherwise a composite of at least 62.50 recommends `CONCERT_ORCHESTRA`; and anything below that is `NOT_PLACED`."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))
    X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])
    for panelist in ctx["panelists"]:
        X.submit_sheet(api, ctx["audition"]["id"], panelist["id"], **_RUBRIC_94_60)

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert adjudicated["tier_recommendation"] == "SYMPHONY"


def test_every_sheet_keeps_the_round_it_was_submitted_against(api):
    """Six sheets survive the cycle, three snapshotted at round 0 and three at round 1.

    PRD §3.4: "The sheet snapshots the audition's current `revision_round` so that sheets from superseded rounds can be excluded from later arithmetic, and its `blind` flag is always true, recording that the adjudicator saw only the `blind_code` and never the musician's `legal_name`."

    Design: Difficulty/non_linear_state_machine/audition_revision_cycle_recomputes_composite_from_new_round
    """
    ctx = _revision_ctx(api)
    validate_success(api.request_revision(ctx["audition"]["id"], {}, DIRECTOR_HEADERS))
    X.schedule_audition(api, ctx["audition"]["id"], ctx["slot2"]["id"])
    for panelist in ctx["panelists"]:
        X.submit_sheet(api, ctx["audition"]["id"], panelist["id"], **_RUBRIC_94_60)

    sheets = _sheets_for(api, ctx["audition"]["id"])
    assert len(sheets) == 6
    round_zero = [s for s in sheets if s["revision_round"] == 0]
    round_one = [s for s in sheets if s["revision_round"] == 1]
    assert len(round_zero) == 3
    assert len(round_one) == 3
    assert all(s["weighted_total"] == 66.60 for s in round_zero)
    assert all(s["weighted_total"] == 94.60 for s in round_one)
    assert all(s["blind"] is True for s in sheets)


# ==========================================================================
# Instance: event_participation_three_dimensions_advance_independently
# ==========================================================================

def _tour_ctx(api) -> Dict[str, Any]:
    """A seated VIOLIN musician with one attended rehearsal and one tour row."""
    ctx = _seated_violin_member(api)
    ctx["rehearsal"] = _rehearsal(api, ctx["ensemble"]["id"], "2026-10-06")
    ctx["tour"] = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="TOUR_PERFORMANCE",
        start_at="2026-11-10T19:00:00Z",
        end_at="2026-11-10T21:00:00Z",
        venue_code="HALL-Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="NONE",
        tour_cost_share_cents=50000,
        chaperone_required=True,
    )
    ctx["rehearsal_row"] = X.create_participation(
        api, ctx["rehearsal"]["id"], ctx["member"]["id"]
    )
    ctx["tour_row"] = X.create_participation(api, ctx["tour"]["id"], ctx["member"]["id"])
    X.set_clock(api, "2026-10-07T09:00:00Z")
    X.record_attendance(api, ctx["rehearsal_row"]["id"], "PRESENT")
    return ctx


def _submit_tour_requirements(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    response = api.submit_tour_requirements(
        ctx["tour_row"]["id"],
        F.tour_requirements_payload(
            fundraising_amount_cents=50000,
            chaperone_name="Dana Chaperone",
            chaperone_background_check_ref="BGC-2026-1",
        ),
        guardian_headers(ctx["member"]["id"]),
    )
    return validate_success(response)


def test_tour_participation_starts_at_the_three_dimension_defaults(api):
    """A brand-new tour row sits at NOT_RECORDED, UNREVIEWED and PENDING at once.

    PRD §3.8: "A new row starts with `attendance_status` `NOT_RECORDED`, `performance_eligibility` `UNREVIEWED`, and `tour_status` `PENDING` for `TOUR_PERFORMANCE` and `FESTIVAL` events but `NOT_APPLICABLE` for `REHEARSAL` and `CONCERT` events, and it increments the event's `participation_count`."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _seated_violin_member(api)
    tour = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="TOUR_PERFORMANCE",
        start_at="2026-11-10T19:00:00Z",
        end_at="2026-11-10T21:00:00Z",
        venue_code="HALL-Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="NONE",
        tour_cost_share_cents=50000,
        chaperone_required=True,
    )
    row = X.create_participation(api, tour["id"], ctx["member"]["id"])

    assert row["attendance_status"] == "NOT_RECORDED"
    assert row["performance_eligibility"] == "UNREVIEWED"
    assert row["tour_status"] == "PENDING"
    assert X.read_event(api, tour["id"])["participation_count"] == 1


def test_rehearsal_participation_never_enters_the_tour_dimension(api):
    """A rehearsal row is born NOT_APPLICABLE on the tour dimension.

    PRD §3.8: "A new row starts with `attendance_status` `NOT_RECORDED`, `performance_eligibility` `UNREVIEWED`, and `tour_status` `PENDING` for `TOUR_PERFORMANCE` and `FESTIVAL` events but `NOT_APPLICABLE` for `REHEARSAL` and `CONCERT` events, and it increments the event's `participation_count`."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _seated_violin_member(api)
    rehearsal = _rehearsal(api, ctx["ensemble"]["id"], "2026-10-06")

    row = X.create_participation(api, rehearsal["id"], ctx["member"]["id"])

    assert row["tour_status"] == "NOT_APPLICABLE"
    assert row["attendance_status"] == "NOT_RECORDED"
    assert row["performance_eligibility"] == "UNREVIEWED"


def test_eligibility_review_grants_eligible_and_clears_the_reason(api):
    """An eligibility review on the tour row moves only the eligibility dimension.

    PRD §3.8: "When all three hold the row moves `UNREVIEWED → ELIGIBLE` with `ineligibility_reason` set to `NONE` and the computed index stored."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)

    reviewed = X.review_eligibility(api, ctx["tour_row"]["id"])

    assert reviewed["performance_eligibility"] == "ELIGIBLE"
    assert reviewed["ineligibility_reason"] == "NONE"
    assert reviewed["attendance_status"] == "NOT_RECORDED"
    assert reviewed["tour_status"] == "PENDING"


def test_attendance_index_is_one_hundred_over_a_single_present_rehearsal(api):
    """One PRESENT rehearsal inside the window gives an index of exactly 100.00.

    PRD §3.8: "Otherwise it is 100 multiplied by the sum of the counted rows' weights, divided by the number of counted rows, rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)

    reviewed = X.review_eligibility(api, ctx["tour_row"]["id"])

    assert reviewed["attendance_index"] == 100.00
    A.assert_two_decimal_places(reviewed["attendance_index"])


def test_tour_requirements_advance_only_the_tour_dimension_to_ready(api):
    """Meeting fundraising, chaperone and eligibility moves the tour dimension to READY.

    PRD §3.9: "The row advances `PENDING → READY` only when `fundraising_shortfall_cents` is 0, when `chaperone_confirmed` is true in the case that the event's `chaperone_required` is true, and when `performance_eligibility` is `ELIGIBLE`; if any of those three does not hold, the request is refused with `ERR_TOUR_REQUIREMENTS_UNMET`."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)
    X.review_eligibility(api, ctx["tour_row"]["id"])

    ready = _submit_tour_requirements(api, ctx)

    assert ready["tour_status"] == "READY"
    assert ready["attendance_status"] == "NOT_RECORDED"
    assert ready["performance_eligibility"] == "ELIGIBLE"


def test_tour_requirements_recompute_shortfall_and_chaperone_confirmation(api):
    """Crediting the full cost share zeroes the shortfall and confirms the chaperone.

    PRD §3.9: "`fundraising_shortfall_cents` is then recomputed as the greater of 0 and the event's `tour_cost_share_cents` minus `fundraising_credited_cents`, and `chaperone_confirmed` is derived as true only when both `chaperone_name` and `chaperone_background_check_ref` are present."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)
    X.review_eligibility(api, ctx["tour_row"]["id"])

    ready = _submit_tour_requirements(api, ctx)

    assert ready["fundraising_credited_cents"] == 50000
    assert ready["fundraising_shortfall_cents"] == 0
    assert ready["chaperone_confirmed"] is True


def test_recording_tardy_leaves_the_other_two_dimensions_where_they_stood(api):
    """The final combined state is TARDY, ELIGIBLE and READY on one row at once.

    PRD §3.8: "A participation row carries three independent state dimensions at once, and each moves on its own."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)
    X.review_eligibility(api, ctx["tour_row"]["id"])
    _submit_tour_requirements(api, ctx)
    X.set_clock(api, "2026-11-10T19:30:00Z")

    recorded = X.record_attendance(api, ctx["tour_row"]["id"], "TARDY")

    assert recorded["attendance_status"] == "TARDY"
    assert recorded["performance_eligibility"] == "ELIGIBLE"
    assert recorded["tour_status"] == "READY"


def test_a_single_tardy_contributes_no_effective_absence(api):
    """One tardy raises tardy_count to 1 but leaves the effective count at 0.

    PRD §3.8: "The combined metric `effective_unexcused_count` is `unexcused_absence_count` plus `tardy_count` divided by three with the remainder discarded — so two tardies contribute nothing and the third tardy contributes one whole effective absence."

    Design: Difficulty/non_linear_state_machine/event_participation_three_dimensions_advance_independently
    """
    ctx = _tour_ctx(api)
    X.review_eligibility(api, ctx["tour_row"]["id"])
    _submit_tour_requirements(api, ctx)
    X.set_clock(api, "2026-11-10T19:30:00Z")
    X.record_attendance(api, ctx["tour_row"]["id"], "TARDY")

    member = X.read_member(api, ctx["member"]["id"])
    assert member["tardy_count"] == 1
    assert member["unexcused_absence_count"] == 0
    assert member["effective_unexcused_count"] == 0
    assert member["standing_status"] == "CLEAR"


# ==========================================================================
# Instance: placement_creation_fork_offer_vs_waitlist_diverges
# ==========================================================================

def _fork_ctx(api) -> Dict[str, Any]:
    """Two adjudicated VIOLIN musicians and a season standing in PLACEMENT."""
    ctx = _open_violin_season(
        api,
        slot_capacity=4,
        ensemble_overrides={"min_total_size": 2},
        quota_overrides={"target_count": 2, "max_count": 2},
    )
    ctx["member_one"], ctx["audition_one"] = _adjudicated_violin_audition(
        api, ctx, _RUBRIC_81_80, "Fork One", grade_level=11, years_in_org=2
    )
    ctx["member_two"], ctx["audition_two"] = _adjudicated_violin_audition(
        api, ctx, _RUBRIC_79_60, "Fork Two", graduation_year=2029
    )
    ctx["season"] = X.advance_season(api, ctx["season"]["id"], "PLACEMENT")
    return ctx


def _create_offer(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return X.create_placement(
        api,
        ctx["audition_one"]["id"],
        ctx["ensemble"]["id"],
        offer_kind="OFFER",
        offer_expires_at=_OFFER_EXPIRES_AT,
    )


def _create_waitlist(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A WAITLIST row that also supplies offer_expires_at, which the fork ignores."""
    payload = F.placement_payload(
        ctx["audition_two"]["id"],
        ctx["ensemble"]["id"],
        X.ensemble_version(api, ctx["ensemble"]["id"]),
        offer_kind="WAITLIST",
    )
    payload["offer_expires_at"] = _OFFER_EXPIRES_AT
    return validate_success(api.create_placement(payload, DIRECTOR_HEADERS), 201)


def test_offer_fork_is_created_offered_with_no_waitlist_rank(api):
    """The OFFER fork lands in OFFERED and carries a null waitlist rank.

    PRD §3.5: "An `OFFER` is created in `OFFERED` with `waitlist_rank` null; it increments the ensemble's `offered_count` by one, thereby consuming section capacity; it increments the ensemble's `version`; and — when the musician has no tuition account for that season yet — it opens one, snapshotting the offered ensemble's tier into `ensemble_tier` and starting the account in `billing_status` `PENDING_ASSESSMENT` (a second account for the same `member_id` and `season_id` would be `ERR_DUPLICATE_TUITION_ACCOUNT`)."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)

    offer = _create_offer(api, ctx)

    assert offer["status"] == "OFFERED"
    assert offer["offer_kind"] == "OFFER"
    assert offer["waitlist_rank"] is None
    assert offer["member_id"] == ctx["member_one"]["id"]
    A.assert_instants_equal(offer["offer_expires_at"], _OFFER_EXPIRES_AT)


def test_offer_fork_consumes_capacity_through_offered_count(api):
    """The OFFER fork raises the ensemble's offered_count to 1.

    PRD §3.5: "An `OFFER` is created in `OFFERED` with `waitlist_rank` null; it increments the ensemble's `offered_count` by one, thereby consuming section capacity; it increments the ensemble's `version`; and — when the musician has no tuition account for that season yet — it opens one, snapshotting the offered ensemble's tier into `ensemble_tier` and starting the account in `billing_status` `PENDING_ASSESSMENT` (a second account for the same `member_id` and `season_id` would be `ERR_DUPLICATE_TUITION_ACCOUNT`)."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 0

    _create_offer(api, ctx)

    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 1


def test_offer_fork_opens_a_pending_assessment_tuition_account(api):
    """The OFFER fork opens the musician's billing account, tier snapshot included.

    PRD §3.5: "An `OFFER` is created in `OFFERED` with `waitlist_rank` null; it increments the ensemble's `offered_count` by one, thereby consuming section capacity; it increments the ensemble's `version`; and — when the musician has no tuition account for that season yet — it opens one, snapshotting the offered ensemble's tier into `ensemble_tier` and starting the account in `billing_status` `PENDING_ASSESSMENT` (a second account for the same `member_id` and `season_id` would be `ERR_DUPLICATE_TUITION_ACCOUNT`)."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)

    _create_offer(api, ctx)

    accounts = X.list_accounts(api, member_id=ctx["member_one"]["id"])
    assert len(accounts) == 1
    assert accounts[0]["billing_status"] == "PENDING_ASSESSMENT"
    assert accounts[0]["ensemble_tier"] == "PHILHARMONIC"
    assert accounts[0]["season_id"] == ctx["season"]["id"]


def test_offer_fork_increments_the_ensemble_version_by_one(api):
    """Creating an offer bumps the owning ensemble's version exactly once.

    PRD §3.5: "An `OFFER` is created in `OFFERED` with `waitlist_rank` null; it increments the ensemble's `offered_count` by one, thereby consuming section capacity; it increments the ensemble's `version`; and — when the musician has no tuition account for that season yet — it opens one, snapshotting the offered ensemble's tier into `ensemble_tier` and starting the account in `billing_status` `PENDING_ASSESSMENT` (a second account for the same `member_id` and `season_id` would be `ERR_DUPLICATE_TUITION_ACCOUNT`)."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    before = X.ensemble_version(api, ctx["ensemble"]["id"])

    _create_offer(api, ctx)

    assert X.ensemble_version(api, ctx["ensemble"]["id"]) == before + 1


def test_waitlist_fork_is_created_waitlisted_at_rank_one(api):
    """The WAITLIST fork lands in WAITLISTED and takes the first free rank.

    PRD §3.5: "A `WAITLIST` is created in `WAITLISTED` with `waitlist_rank` set to one more than the number of placements already `WAITLISTED` on that same ensemble-and-instrument pairing; it increments the ensemble's `version`; and it deliberately does *neither* of the offer branch's two commitments — `offered_count` is untouched and no tuition account is opened."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    _create_offer(api, ctx)

    waitlisted = _create_waitlist(api, ctx)

    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["offer_kind"] == "WAITLIST"
    assert waitlisted["waitlist_rank"] == 1
    assert waitlisted["member_id"] == ctx["member_two"]["id"]


def test_waitlist_fork_makes_neither_of_the_offer_branch_commitments(api):
    """The WAITLIST fork leaves offered_count alone and opens no billing account.

    PRD §3.5: "A `WAITLIST` is created in `WAITLISTED` with `waitlist_rank` set to one more than the number of placements already `WAITLISTED` on that same ensemble-and-instrument pairing; it increments the ensemble's `version`; and it deliberately does *neither* of the offer branch's two commitments — `offered_count` is untouched and no tuition account is opened."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    _create_offer(api, ctx)

    _create_waitlist(api, ctx)

    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 1
    assert X.list_accounts(api, member_id=ctx["member_two"]["id"]) == []


def test_waitlist_fork_increments_the_ensemble_version_by_one(api):
    """Creating a waitlist claim bumps the owning ensemble's version exactly once.

    PRD §3.5: "A `WAITLIST` is created in `WAITLISTED` with `waitlist_rank` set to one more than the number of placements already `WAITLISTED` on that same ensemble-and-instrument pairing; it increments the ensemble's `version`; and it deliberately does *neither* of the offer branch's two commitments — `offered_count` is untouched and no tuition account is opened."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    _create_offer(api, ctx)
    before = X.ensemble_version(api, ctx["ensemble"]["id"])

    _create_waitlist(api, ctx)

    assert X.ensemble_version(api, ctx["ensemble"]["id"]) == before + 1


def test_neither_placement_fork_fills_the_section(api):
    """No seat exists yet, so the section stays at fill count 0 and UNDERFILLED.

    PRD §3.1: "Thereafter `balance_state` is derived purely from `filled_count`: it is `UNDERFILLED` while `filled_count` is below `min_count`, `BALANCED` while `filled_count` is at least `min_count` but still below `target_count`, and `FULL` once `filled_count` is at least `target_count`."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    _create_offer(api, ctx)
    _create_waitlist(api, ctx)

    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["filled_count"] == 0
    assert quota["balance_state"] == "UNDERFILLED"


def test_neither_placement_fork_enrolls_the_musician(api):
    """Both musicians stay PROSPECT because only an acceptance enrolls them.

    PRD §3.2: "`PROSPECT → ENROLLED` is not a registrar action at all: the server performs it when a placement offer is accepted."

    Design: Difficulty/non_linear_state_machine/placement_creation_fork_offer_vs_waitlist_diverges
    """
    ctx = _fork_ctx(api)
    _create_offer(api, ctx)
    _create_waitlist(api, ctx)

    assert X.read_member(api, ctx["member_one"]["id"])["enrollment_status"] == "PROSPECT"
    assert X.read_member(api, ctx["member_two"]["id"])["enrollment_status"] == "PROSPECT"


# ==========================================================================
# Instance: placement_accept_seats_to_season_cascade
# ==========================================================================

def test_acceptance_stamps_accepted_at_from_the_logical_clock(api):
    """Accepting an offer moves the row to ACCEPTED and stamps the logical clock.

    PRD §3.5: "`accepted_at` is stamped from the logical clock."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)

    accepted = X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    assert accepted["status"] == "ACCEPTED"
    A.assert_instants_equal(accepted["accepted_at"], _CLOCK)


def test_acceptance_creates_the_chair_and_lifts_the_section_fill_count(api):
    """Hop one of the cascade opens a fresh ACTIVE chair and raises filled_count to 1.

    PRD §3.5: "A **SeatAssignment** is then created in `ACTIVE` status, carrying the `placement_id` that produced it, the `section_quota_id` of the matching section, the seat holder's `member_id`, a `predecessor_assignment_id` of null because it opens a fresh rotation chain, a `rotation_cycle_index` copied from the section's current `rotation_cycle_index`, and a `ranking_score` snapshotted from the audition's `composite_final_score`; the section's chair order is then recomputed per §3.6 and `filled_count` increments by one."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    assert X.read_section_quota(api, ctx["quota"]["id"])["filled_count"] == 0

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    seat = X.sole_active_seat(api, ctx["member"]["id"])
    assert seat["status"] == "ACTIVE"
    assert seat["placement_id"] == ctx["placement"]["id"]
    assert seat["section_quota_id"] == ctx["quota"]["id"]
    assert seat["member_id"] == ctx["member"]["id"]
    assert seat["predecessor_assignment_id"] is None
    assert seat["rotation_cycle_index"] == 0
    assert seat["ranking_score"] == 81.80
    assert seat["chair_number"] == 1
    assert X.read_section_quota(api, ctx["quota"]["id"])["filled_count"] == 1


def test_the_first_chair_of_the_section_carries_the_principal_flag(api):
    """Chair one of a principal-required section is the principal chair.

    PRD §3.6: "Each chair's `chair_number` is then its 1-based position in that order, and `is_principal` is true exactly when `chair_number` is 1 and the section's `principal_required` is true."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    assert X.read_section_quota(api, ctx["quota"]["id"])["principal_required"] is True

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    seat = X.sole_active_seat(api, ctx["member"]["id"])
    assert seat["chair_number"] == 1
    assert seat["is_principal"] is True
    A.assert_contiguous_chair_numbers(X.list_seats(api, section_quota_id=ctx["quota"]["id"]))


def test_section_flips_to_full_because_fill_count_reached_target(api):
    """Hop two flips the section to FULL, caused by the fill count reaching target.

    PRD §3.5: "Because `filled_count` reached `target_count`, the section's `balance_state` advances to `FULL`."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    before = X.read_section_quota(api, ctx["quota"]["id"])
    assert before["balance_state"] == "UNDERFILLED"
    assert before["target_count"] == 1

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    assert X.read_section_quota(api, ctx["quota"]["id"])["balance_state"] == "FULL"


def test_ensemble_advances_to_seated_because_every_section_is_full(api):
    """Hop three flips the ensemble to SEATED, caused by its last section filling.

    PRD §3.5: "Because every section of the ensemble is now `FULL` and `seated_count` is at least `min_total_size`, the ensemble's `roster_state` advances `FORMING → SEATED`."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "FORMING"

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["roster_state"] == "SEATED"
    assert ensemble["seated_count"] == 1


def test_season_advances_to_in_season_on_its_last_unseated_ensemble(api):
    """Hop four advances the season, caused by its final ensemble becoming SEATED.

    PRD §3.5: "And because that was the season's last unseated ensemble, the season's `status` advances `PLACEMENT → IN_SEASON`."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    before = X.read_season(api, ctx["season"]["id"])
    assert before["status"] == "PLACEMENT"
    assert before["seated_ensemble_count"] == 0
    assert before["ensemble_count"] == 1

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    season = X.read_season(api, ctx["season"]["id"])
    assert season["status"] == "IN_SEASON"
    assert season["seated_ensemble_count"] == 1


def test_acceptance_enrolls_the_musician_and_releases_the_offer_slot(api):
    """Alongside the climb, the musician enrols and the ensemble's offered_count drops.

    PRD §3.5: "Alongside that four-hop climb, the musician's `enrollment_status` moves `PROSPECT → ENROLLED` if it was `PROSPECT`; the preliminary tuition assessment of §3.7 runs on the tuition account and moves its `billing_status` `PENDING_ASSESSMENT → CURRENT` once `assessed_cents` is above zero; the ensemble's `offered_count` decrements by one and its `version` increments; and every *other* placement of the same musician in the same season sitting in `OFFERED` or `WAITLISTED` moves to `WITHDRAWN`, while any `ACCEPTED` or already-terminal sibling row is left untouched."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    assert X.read_member(api, ctx["member"]["id"])["enrollment_status"] == "PROSPECT"
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 1

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    member = X.read_member(api, ctx["member"]["id"])
    assert member["enrollment_status"] == "ENROLLED"
    assert member["standing_status"] == "CLEAR"
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["offered_count"] == 0


def test_preliminary_assessment_charges_the_gross_tier_figure_exactly(api):
    """The preliminary variant zeroes both discounts, so assessed equals the gross.

    PRD §3.7: "It forces both discount components to zero — `sibling_discount_cents` is 0 and `loyalty_credit_cents` is 0 — so `assessed_cents` equals the gross tier-adjusted figure exactly."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    account = X.sole_account(api, ctx["member"]["id"], ctx["season"]["id"])
    assert account["assessment_variant"] == "PRELIMINARY"
    assert account["assessed_cents"] == _PHILHARMONIC_GROSS_CENTS
    assert account["sibling_discount_cents"] == 0
    assert account["loyalty_credit_cents"] == 0
    assert account["billing_status"] == "CURRENT"


def test_preliminary_balance_equals_the_assessed_figure(api):
    """With no aid, no loan and no payments, the balance is the assessed figure.

    PRD §3.7: "The account's `balance_cents` is then `assessed_cents`, less `aid_effective_cents`, plus `instrument_loan_fee_cents`, less `payments_total_cents`."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)

    X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    account = X.sole_account(api, ctx["member"]["id"], ctx["season"]["id"])
    assert account["aid_effective_cents"] == 0
    assert account["instrument_loan_fee_cents"] == 0
    assert account["payments_total_cents"] == 0
    assert account["balance_cents"] == _PHILHARMONIC_GROSS_CENTS
    A.assert_balance_identity(account)


def test_the_four_hop_acceptance_cascade_bumps_four_version_counters(api):
    """Chair, section, ensemble and season are all mutated, so each version advances.

    PRD §2.6: "A cascade that touches four entities therefore bumps four version counters."

    Design: Difficulty/transitive_cascade/placement_accept_seats_to_season_cascade
    """
    ctx = _offered_violin_placement(api)
    quota_before = X.read_section_quota(api, ctx["quota"]["id"])["version"]
    ensemble_before = X.ensemble_version(api, ctx["ensemble"]["id"])
    season_before = X.season_version(api, ctx["season"]["id"])
    placement_before = ctx["placement"]["version"]

    accepted = X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )

    assert accepted["version"] > placement_before
    assert X.read_section_quota(api, ctx["quota"]["id"])["version"] > quota_before
    assert X.ensemble_version(api, ctx["ensemble"]["id"]) > ensemble_before
    assert X.season_version(api, ctx["season"]["id"]) > season_before


# ==========================================================================
# Instance: excuse_denial_probation_cascade
# ==========================================================================

def _probation_ctx(api) -> Dict[str, Any]:
    """Two effective absences banked, one excuse pending, and a programmed concert
    whose soloist is the same musician."""
    ctx = _seated_violin_member(api)
    member_id = ctx["member"]["id"]
    ensemble_id = ctx["ensemble"]["id"]

    ctx["rehearsal_a"] = _rehearsal(api, ensemble_id, "2026-09-05")
    ctx["rehearsal_b"] = _rehearsal(api, ensemble_id, "2026-09-12")
    ctx["rehearsal_c"] = _rehearsal(api, ensemble_id, "2026-09-19")
    ctx["rehearsal_d"] = _rehearsal(api, ensemble_id, "2026-10-06")
    ctx["rehearsal_e"] = _rehearsal(api, ensemble_id, "2026-10-13")
    ctx["concert"] = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at="2026-11-01T19:00:00Z",
        end_at="2026-11-01T21:00:00Z",
        venue_code="HALL-Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="AUTO_SELECT",
    )
    for key in ("a", "b", "c", "d", "e"):
        ctx[f"row_{key}"] = X.create_participation(
            api, ctx[f"rehearsal_{key}"]["id"], member_id
        )
    ctx["concert_row"] = X.create_participation(api, ctx["concert"]["id"], member_id)

    # Two unexcused absences outside the concert's eligibility window.
    X.set_clock(api, "2026-09-06T12:00:00Z")
    X.record_attendance(api, ctx["row_a"]["id"], "UNEXCUSED_ABSENT", REGISTRAR_HEADERS)
    X.set_clock(api, "2026-09-13T09:00:00Z")
    X.record_attendance(api, ctx["row_b"]["id"], "ABSENCE_UNVERIFIED", REGISTRAR_HEADERS)
    validate_success(
        api.request_excuse(
            ctx["row_b"]["id"],
            F.excuse_request_payload(
                excuse_reason_code="ILLNESS", excuse_documentation_ref="DOC-9"
            ),
            guardian_headers(member_id),
        )
    )
    X.set_clock(api, "2026-09-20T09:00:00Z")
    X.record_attendance(api, ctx["row_c"]["id"], "UNEXCUSED_ABSENT", REGISTRAR_HEADERS)

    # Two attended rehearsals inside the concert's window keep the index at 100.00.
    X.set_clock(api, "2026-10-14T09:00:00Z")
    X.record_attendance(api, ctx["row_d"]["id"], "PRESENT", REGISTRAR_HEADERS)
    X.record_attendance(api, ctx["row_e"]["id"], "PRESENT", REGISTRAR_HEADERS)
    ctx["concert_row"] = X.review_eligibility(api, ctx["concert_row"]["id"])
    ctx["concert"] = validate_success(
        api.program_event(ctx["concert"]["id"], F.programming_payload(), DIRECTOR_HEADERS)
    )
    return ctx


def _deny_excuse(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A second registrar identity decides the excuse the first one recorded."""
    return validate_success(
        api.decide_excuse(
            ctx["row_b"]["id"],
            F.excuse_decision_payload("DENIED"),
            REGISTRAR_HEADERS_2,
        )
    )


def test_denied_excuse_moves_the_row_to_unexcused_absent(api):
    """The trigger hop turns the pending excuse into an unexcused absence.

    PRD §3.8: "A decision of `DENIED` moves the row `EXCUSE_PENDING → UNEXCUSED_ABSENT`, records `excuse_decided_by_user_id`, and fires exactly the same four-hop cascade described above: the musician's `unexcused_absence_count` and `effective_unexcused_count` rise, the musician may advance `CLEAR → ATTENDANCE_PROBATION`, every future performance participation of that musician becomes `INELIGIBLE` with `ineligibility_reason` `MEMBER_ON_PROBATION` and any `READY` tour status drops to `PENDING`, and any event where that musician was the named soloist advances `PROGRAMMED → SOLOIST_VACANT` with `soloist_member_id` cleared to null."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    assert X.read_participation(api, ctx["row_b"]["id"])["attendance_status"] == "EXCUSE_PENDING"

    decided = _deny_excuse(api, ctx)

    assert decided["attendance_status"] == "UNEXCUSED_ABSENT"
    assert decided["excuse_decided_by_user_id"] == REGISTRAR_USER_ID_2
    assert decided["excuse_decided_by_user_id"] != REGISTRAR_USER_ID


def test_denial_raises_the_effective_absence_count_to_three(api):
    """Hop one increments the unexcused count and recomputes the effective count.

    PRD §3.8: "First, the musician's `unexcused_absence_count` increments by one and `effective_unexcused_count` is recomputed."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    before = X.read_member(api, ctx["member"]["id"])
    assert before["unexcused_absence_count"] == 2
    assert before["effective_unexcused_count"] == 2

    _deny_excuse(api, ctx)

    after = X.read_member(api, ctx["member"]["id"])
    assert after["unexcused_absence_count"] == 3
    assert after["effective_unexcused_count"] == 3


def test_third_effective_absence_puts_the_musician_on_probation(api):
    """Hop two flips standing to probation because the count minus the baseline hits three.

    PRD §3.8: "Second, when `effective_unexcused_count` minus `probation_baseline_count` is at least three and the musician's standing was `CLEAR`, `standing_status` advances `CLEAR → ATTENDANCE_PROBATION`."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    before = X.read_member(api, ctx["member"]["id"])
    assert before["standing_status"] == "CLEAR"
    assert before["probation_baseline_count"] == 0

    _deny_excuse(api, ctx)

    after = X.read_member(api, ctx["member"]["id"])
    assert after["standing_status"] == "ATTENDANCE_PROBATION"
    assert after["probation_baseline_count"] == 0


def test_probation_revokes_the_future_concert_eligibility(api):
    """Hop three drops the musician's future concert row to INELIGIBLE on probation.

    PRD §3.8: "Third, because the musician went on probation, every participation row of that musician on an event whose `kind` is `CONCERT`, `TOUR_PERFORMANCE` or `FESTIVAL`, whose event `start_at` is strictly later than the logical clock, and whose `performance_eligibility` is not already `INELIGIBLE`, moves to `INELIGIBLE` with `ineligibility_reason` set to `MEMBER_ON_PROBATION`, and any of those rows whose `tour_status` was `READY` drops back to `PENDING`."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    before = X.read_participation(api, ctx["concert_row"]["id"])
    assert before["performance_eligibility"] == "ELIGIBLE"
    assert before["attendance_index"] == 100.00

    _deny_excuse(api, ctx)

    after = X.read_participation(api, ctx["concert_row"]["id"])
    assert after["performance_eligibility"] == "INELIGIBLE"
    assert after["ineligibility_reason"] == "MEMBER_ON_PROBATION"


def test_revoked_soloist_empties_the_concert_programming(api):
    """Hop four vacates the soloist chair on the event the musician was announced for.

    PRD §3.8: "Fourth, wherever one of those revoked rows belongs to an event whose `soloist_member_id` is that same musician, the event's `programming_state` advances `PROGRAMMED → SOLOIST_VACANT` and its `soloist_member_id` is cleared to null."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    before = X.read_event(api, ctx["concert"]["id"])
    assert before["programming_state"] == "PROGRAMMED"
    assert before["soloist_member_id"] == ctx["member"]["id"]

    _deny_excuse(api, ctx)

    after = X.read_event(api, ctx["concert"]["id"])
    assert after["programming_state"] == "SOLOIST_VACANT"
    assert after["soloist_member_id"] is None


def test_probation_cascade_leaves_rehearsal_rows_untouched(api):
    """The revocation reaches only future performances, never a recorded rehearsal.

    PRD §3.8: "Third, because the musician went on probation, every participation row of that musician on an event whose `kind` is `CONCERT`, `TOUR_PERFORMANCE` or `FESTIVAL`, whose event `start_at` is strictly later than the logical clock, and whose `performance_eligibility` is not already `INELIGIBLE`, moves to `INELIGIBLE` with `ineligibility_reason` set to `MEMBER_ON_PROBATION`, and any of those rows whose `tour_status` was `READY` drops back to `PENDING`."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)

    _deny_excuse(api, ctx)

    rehearsal_row = X.read_participation(api, ctx["row_d"]["id"])
    assert rehearsal_row["attendance_status"] == "PRESENT"
    assert rehearsal_row["performance_eligibility"] == "UNREVIEWED"


def test_probation_cascade_bumps_the_version_of_every_row_it_touches(api):
    """The participation row, the musician, the concert row and the concert all advance.

    PRD §3.8: "Every row touched along the way has its `version` incremented."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)
    row_before = X.read_participation(api, ctx["row_b"]["id"])["version"]
    member_before = X.read_member(api, ctx["member"]["id"])["version"]
    concert_row_before = X.read_participation(api, ctx["concert_row"]["id"])["version"]
    concert_before = X.read_event(api, ctx["concert"]["id"])["version"]

    decided = _deny_excuse(api, ctx)

    assert decided["version"] > row_before
    assert X.read_member(api, ctx["member"]["id"])["version"] > member_before
    assert X.read_participation(api, ctx["concert_row"]["id"])["version"] > concert_row_before
    assert X.read_event(api, ctx["concert"]["id"])["version"] > concert_before


def test_approved_excuse_leaves_every_counter_untouched(api):
    """Approving the very same excuse fires no cascade at all.

    PRD §3.8: "A decision of `APPROVED` moves the row `EXCUSE_PENDING → EXCUSED_ABSENT`, records `excuse_decided_by_user_id`, and leaves every counter untouched."

    Design: Difficulty/transitive_cascade/excuse_denial_probation_cascade
    """
    ctx = _probation_ctx(api)

    decided = validate_success(
        api.decide_excuse(
            ctx["row_b"]["id"],
            F.excuse_decision_payload("APPROVED"),
            REGISTRAR_HEADERS_2,
        )
    )

    assert decided["attendance_status"] == "EXCUSED_ABSENT"
    assert decided["excuse_decided_by_user_id"] == REGISTRAR_USER_ID_2
    member = X.read_member(api, ctx["member"]["id"])
    assert member["unexcused_absence_count"] == 2
    assert member["effective_unexcused_count"] == 2
    assert member["standing_status"] == "CLEAR"


# ==========================================================================
# Instance: aid_rescind_delinquency_cascade
# ==========================================================================

_AID_DUE_AT = "2026-10-01T00:00:00Z"
_AID_REQUESTED_CENTS = 30000
_AID_BUDGET_CENTS = 100000


def _approved_award_ctx(api) -> Dict[str, Any]:
    """A seated BAND_A musician holding an APPROVED award of 30000 cents."""
    ctx = _offered_violin_placement(
        api,
        season_overrides={"tuition_due_at": _AID_DUE_AT},
        household_income_band="BAND_A",
    )
    ctx["placement"] = X.accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], instrument_loan_requested=False
    )
    account = X.sole_account(api, ctx["member"]["id"], ctx["season"]["id"])
    validate_success(
        api.request_aid(
            account["id"],
            F.aid_request_payload(_AID_REQUESTED_CENTS),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    # One officer reviews, a different officer funds (PRD §3.7 segregation).
    validate_success(api.review_aid(account["id"], {}, FINANCE_HEADERS))
    validate_success(
        api.aid_award_run(
            ctx["season"]["id"],
            F.aid_award_run_payload(X.season_version(api, ctx["season"]["id"])),
            FINANCE_HEADERS_2,
        )
    )
    ctx["account"] = X.read_account(api, account["id"])
    return ctx


def _rescind(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return validate_success(
        api.rescind_aid(ctx["account"]["id"], {}, FINANCE_HEADERS_2)
    )


def test_award_run_approves_the_full_request_and_commits_the_pool(api):
    """The waterfall grants the whole 30000-cent request and commits it to the season.

    PRD §3.7: "If that candidate grant is at least 5000 cents, the account is approved — `aid_awarded_cents` is set to the grant, `aid_effective_cents` is set to the same grant (uncapped, because `assessment_variant` is still `PRELIMINARY`), `aid_awarded_by_user_id` records the acting officer, `aid_status` becomes `APPROVED`, the running remainder decreases by the grant, and the season's `aid_committed_cents` increases by the grant."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)

    account = ctx["account"]
    assert account["aid_status"] == "APPROVED"
    assert account["aid_awarded_cents"] == _AID_REQUESTED_CENTS
    assert account["aid_effective_cents"] == _AID_REQUESTED_CENTS
    assert account["balance_cents"] == _PHILHARMONIC_GROSS_CENTS - _AID_REQUESTED_CENTS
    assert account["billing_status"] == "CURRENT"
    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_committed_cents"] == _AID_REQUESTED_CENTS
    assert season["aid_available_cents"] == _AID_BUDGET_CENTS - _AID_REQUESTED_CENTS
    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "CLEAR"


def test_rescission_moves_the_aid_dimension_to_rescinded(api):
    """Withdrawing an approved award moves the aid dimension to RESCINDED.

    PRD §3.7: "A `FinanceOfficer` may withdraw an award from an `APPROVED` account whose `aid_awarded_cents` is above 0, moving `aid_status` to `RESCINDED`."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    X.set_clock(api, "2026-10-15T09:00:00Z")

    rescinded = _rescind(api, ctx)

    assert rescinded["aid_status"] == "RESCINDED"


def test_rescission_zeroes_the_credit_and_returns_money_to_the_season_pool(api):
    """Hop one zeroes both aid figures, refunds the pool and pushes the balance back up.

    PRD §3.7: "First, `aid_awarded_cents` and `aid_effective_cents` are both set to 0; the season's `aid_committed_cents` decreases by the account's `aid_effective_cents` *as it stood immediately before the rescission* — that is, the amount actually committed to this account, which is the capped figure once the final assessment has run — and `aid_available_cents` increases by the same amount; and `balance_cents` is recomputed upward."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    X.set_clock(api, "2026-10-15T09:00:00Z")

    rescinded = _rescind(api, ctx)

    assert rescinded["aid_awarded_cents"] == 0
    assert rescinded["aid_effective_cents"] == 0
    assert rescinded["balance_cents"] == _PHILHARMONIC_GROSS_CENTS
    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_committed_cents"] == 0
    assert season["aid_available_cents"] == _AID_BUDGET_CENTS


def test_rescission_past_the_due_date_flips_billing_to_delinquent(api):
    """Hop two turns the account delinquent because the clock is past the due date.

    PRD §3.7: "Second, because `balance_cents` is now above 0 and the logical clock is at or past the season's `tuition_due_at`, `billing_status` advances to `DELINQUENT`."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    assert ctx["account"]["billing_status"] == "CURRENT"
    X.set_clock(api, "2026-10-15T09:00:00Z")

    rescinded = _rescind(api, ctx)

    assert rescinded["balance_cents"] > 0
    assert rescinded["billing_status"] == "DELINQUENT"


def test_delinquency_puts_the_musician_on_financial_hold(api):
    """Hop three carries the delinquency into the musician's standing dimension.

    PRD §3.7: "Third, because the account went delinquent, the musician's `standing_status` advances `CLEAR → FINANCIAL_HOLD`."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "CLEAR"
    X.set_clock(api, "2026-10-15T09:00:00Z")

    _rescind(api, ctx)

    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "FINANCIAL_HOLD"


def test_rescission_bumps_the_account_and_season_versions_by_one(api):
    """A rescission advances exactly two version counters, each by one.

    PRD §3.7: "Both the account's `version` and the season's `version` increment by one each."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    X.set_clock(api, "2026-10-15T09:00:00Z")
    account_before = ctx["account"]["version"]
    season_before = X.season_version(api, ctx["season"]["id"])

    rescinded = _rescind(api, ctx)

    assert rescinded["version"] == account_before + 1
    assert X.season_version(api, ctx["season"]["id"]) == season_before + 1


def test_the_aid_pool_stays_conserved_across_the_rescission(api):
    """Committed plus available equals the authorization before and after the refund.

    PRD §2.11: "A season authorizes `aid_budget_cents`; at every observable moment thereafter, `aid_committed_cents` plus `aid_available_cents` equals `aid_budget_cents` exactly."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)
    A.assert_aid_pool_conserved(X.read_season(api, ctx["season"]["id"]))
    X.set_clock(api, "2026-10-15T09:00:00Z")

    _rescind(api, ctx)

    season = X.read_season(api, ctx["season"]["id"])
    A.assert_aid_pool_conserved(season)
    assert season["aid_budget_cents"] == _AID_BUDGET_CENTS


def test_rescission_before_the_due_date_stops_the_chain_at_hop_one(api):
    """With the clock still before the due date the account stays CURRENT and standing CLEAR.

    PRD §3.7: "`CURRENT → DELINQUENT` whenever any balance recomputation — a final assessment, a payment, an aid award or an aid rescission — observes the logical clock at or after the season's `tuition_due_at` while `balance_cents` is above 0; that transition also sets the musician's `standing_status` to `FINANCIAL_HOLD`."

    Design: Difficulty/transitive_cascade/aid_rescind_delinquency_cascade
    """
    ctx = _approved_award_ctx(api)

    rescinded = _rescind(api, ctx)

    assert rescinded["aid_status"] == "RESCINDED"
    assert rescinded["balance_cents"] == _PHILHARMONIC_GROSS_CENTS
    assert rescinded["billing_status"] == "CURRENT"
    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "CLEAR"
