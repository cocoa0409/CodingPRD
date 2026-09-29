"""Arithmetic behaviour of the Youth Orchestra Audition & Seating API.

Every test builds all of its state from scratch through PRD endpoints: the
harness restarts the server and empties the database before each test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    FINANCE_HEADERS,
    FINANCE_HEADERS_2,
    guardian_headers,
)


# --------------------------------------------------------------------------
# Local helpers (the shared infrastructure is never modified)
# --------------------------------------------------------------------------

def _score(value: Any) -> float:
    """A stored two-decimal figure, normalised for exact comparison."""
    return round(float(value), 2)


def _rubric(tone: int, rhythm: int, intonation: int, sight_reading: int) -> Dict[str, int]:
    return {
        "tone_score": tone,
        "rhythm_score": rhythm,
        "intonation_score": intonation,
        "sight_reading_score": sight_reading,
    }


def _scored_with_sheets(
    api,
    rubric_sets: List[Dict[str, int]],
    instrument: str = "VIOLIN",
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One audition carrying exactly the supplied rubric sheets."""
    quota_defaults: Dict[str, Any] = {"instrument": instrument}
    quota_defaults.update(quota_overrides or {})
    ctx = X.open_season_with_ensemble(
        api,
        ensemble_overrides=ensemble_overrides,
        quota_overrides=quota_defaults,
    )
    member_defaults: Dict[str, Any] = {"primary_instrument": instrument}
    member_defaults.update(member_overrides or {})
    member = X.create_member(api, **member_defaults)
    panelists = X.create_panelists(
        api, count=len(rubric_sets), instrument_expertise=instrument
    )
    slot = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in panelists],
        instrument_focus=instrument,
        quorum_required=len(rubric_sets),
        capacity=C.MAX_SLOT_CAPACITY,
    )
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])
    X.schedule_audition(api, audition["id"], slot["id"])
    sheets = [
        X.submit_sheet(api, audition["id"], panelists[index]["id"], **rubric_sets[index])
        for index in range(len(rubric_sets))
    ]
    ctx.update(
        {
            "member": member,
            "panelists": panelists,
            "slot": slot,
            "audition": X.read_audition(api, audition["id"]),
            "sheets": sheets,
        }
    )
    return ctx


def _placement_season(
    api,
    specs: List[Dict[str, Any]],
    ensemble_overrides: Dict[str, Any],
    quota_overrides: Dict[str, Any],
    instrument: str = "VIOLIN",
    clock: str = C.FIXTURE_CLOCK,
) -> Dict[str, Any]:
    """A season in `PLACEMENT` whose musicians are all adjudicated already.

    Each spec carries `member` overrides and the `rubric` every panelist files
    for that musician, so the resulting composites are chosen by the caller.
    """
    X.set_clock(api, clock)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"], **ensemble_overrides)
    quota_defaults: Dict[str, Any] = {"instrument": instrument}
    quota_defaults.update(quota_overrides)
    quota = X.create_section_quota(api, ensemble["id"], **quota_defaults)
    panelists = X.create_panelists(api, count=3, instrument_expertise=instrument)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        instrument_focus=instrument,
        capacity=C.MAX_SLOT_CAPACITY,
    )
    entries: List[Dict[str, Any]] = []
    for spec in specs:
        member = X.create_member(
            api, primary_instrument=instrument, **spec.get("member", {})
        )
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        for panelist in panelists:
            X.submit_sheet(api, audition["id"], panelist["id"], **spec["rubric"])
        entries.append(
            {"member": member, "audition": X.adjudicate(api, audition["id"])}
        )
    season = X.advance_season(api, season["id"], "PLACEMENT")
    return {
        "clock": clock,
        "season": season,
        "ensemble": ensemble,
        "quota": quota,
        "panelists": panelists,
        "slot": slot,
        "entries": entries,
    }


_UNIFORM_20 = _rubric(20, 20, 20, 20)


def _aid_run_season(api) -> Dict[str, Any]:
    """Three seated musicians whose aid requests all sit in `UNDER_REVIEW`.

    Need scores come out 63, 31 and 13, and the requests are 40000, 3000 and
    20000 cents against an `aid_budget_cents` of 100000.
    """
    specs = [
        {
            "member": {
                "legal_name": "Need Nora",
                "household_income_band": "BAND_A",
                "years_in_org": 4,
                "sibling_enrolled": True,
            },
            "rubric": _UNIFORM_20,
            "requested": 40000,
        },
        {
            "member": {
                "legal_name": "Mid Milo",
                "household_income_band": "BAND_B",
                "years_in_org": 1,
                "sibling_enrolled": False,
            },
            "rubric": _UNIFORM_20,
            "requested": 3000,
        },
        {
            "member": {
                "legal_name": "Low Lena",
                "household_income_band": "BAND_C",
                "years_in_org": 0,
                "sibling_enrolled": False,
            },
            "rubric": _UNIFORM_20,
            "requested": 20000,
        },
    ]
    ctx = _placement_season(
        api,
        specs,
        ensemble_overrides={
            "tier": "PHILHARMONIC",
            "min_total_size": 3,
            "max_total_size": 4,
        },
        quota_overrides={"min_count": 1, "target_count": 3, "max_count": 3},
    )
    for entry, spec in zip(ctx["entries"], specs):
        placement = X.create_placement(
            api, entry["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
        )
        X.accept_placement(
            api, placement["id"], entry["member"]["id"], instrument_loan_requested=False
        )
        account = X.sole_account(api, entry["member"]["id"], ctx["season"]["id"])
        validate_success(
            api.request_aid(
                account["id"],
                F.aid_request_payload(spec["requested"]),
                guardian_headers(entry["member"]["id"]),
            )
        )
        entry["account"] = validate_success(
            api.review_aid(account["id"], {}, FINANCE_HEADERS)
        )
    return ctx


def _run_aid_award(api, season_id: str) -> Dict[str, Any]:
    """Execute the waterfall with a funding officer distinct from the reviewer."""
    payload = F.aid_award_run_payload(X.season_version(api, season_id))
    return validate_success(api.aid_award_run(season_id, payload, FINANCE_HEADERS_2))


def _waitlist_season(api) -> Dict[str, Any]:
    """One offer plus three waitlisted claims on a section of `max_count` 1.

    Composites are 85.00 (Sara, offered), 94.60 (Tia), 81.80 (Eli) and 81.80
    (Lou); the clock moves between Eli's and Lou's rows so the tie-break on
    `created_at` is observable.
    """
    specs = [
        {"member": {"legal_name": "Seat Sara"}, "rubric": _rubric(25, 20, 19, 20)},
        {"member": {"legal_name": "Top Tia"}, "rubric": _rubric(25, 24, 23, 22)},
        {"member": {"legal_name": "Early Eli"}, "rubric": _rubric(22, 20, 21, 18)},
        {"member": {"legal_name": "Later Lou"}, "rubric": _rubric(22, 20, 21, 18)},
    ]
    ctx = _placement_season(
        api,
        specs,
        ensemble_overrides={
            "tier": "PHILHARMONIC",
            "min_total_size": 1,
            "max_total_size": 4,
        },
        quota_overrides={"min_count": 1, "target_count": 1, "max_count": 1},
    )
    entries = ctx["entries"]
    ensemble_id = ctx["ensemble"]["id"]
    entries[0]["placement"] = X.create_placement(
        api, entries[0]["audition"]["id"], ensemble_id, offer_kind="OFFER"
    )
    for index in (1, 2):
        entries[index]["placement"] = X.create_placement(
            api, entries[index]["audition"]["id"], ensemble_id, offer_kind="WAITLIST"
        )
    ctx["clock"] = X.set_clock(api, "2026-08-05T10:00:00Z")
    entries[3]["placement"] = X.create_placement(
        api, entries[3]["audition"]["id"], ensemble_id, offer_kind="WAITLIST"
    )
    return ctx


def _decline(api, placement_id: str, member_id: str) -> Dict[str, Any]:
    return validate_success(
        api.decline_placement(placement_id, {}, guardian_headers(member_id))
    )


def _rehearsal_then_concert(
    api,
    rehearsals: List[Dict[str, Any]],
    eligibility_window_start: str = "2026-10-01T00:00:00Z",
    concert_start: str = "2026-11-15T19:00:00Z",
    concert_end: str = "2026-11-15T21:00:00Z",
) -> Dict[str, Any]:
    """A seated violinist rostered on a set of rehearsals and one concert.

    Each rehearsal spec carries `start_at`, `end_at` and the `attendance_status`
    to record (or None to leave the row unrecorded). Attendance is recorded by
    walking the logical clock five minutes past each rehearsal's start.
    """
    ctx = X.accepted_placement(api, instrument="VIOLIN", instrument_loan_requested=False)
    ensemble_id = ctx["ensemble"]["id"]
    member_id = ctx["member"]["id"]
    concert = X.create_ensemble_event(
        api,
        ensemble_id,
        kind="CONCERT",
        start_at=concert_start,
        end_at=concert_end,
        venue_code="HALL-B",
        eligibility_window_start=eligibility_window_start,
    )
    rows: List[Dict[str, Any]] = []
    for rehearsal in rehearsals:
        event = X.create_ensemble_event(
            api,
            ensemble_id,
            kind="REHEARSAL",
            start_at=rehearsal["start_at"],
            end_at=rehearsal["end_at"],
        )
        rows.append(
            {
                "row": X.create_participation(api, event["id"], member_id),
                "start_at": rehearsal["start_at"],
                "attendance_status": rehearsal["attendance_status"],
            }
        )
    concert_row = X.create_participation(api, concert["id"], member_id)
    for entry in rows:
        if entry["attendance_status"] is None:
            continue
        X.set_clock(api, A.shift_instant(entry["start_at"], minutes=5))
        X.record_attendance(api, entry["row"]["id"], entry["attendance_status"])
    ctx.update({"concert": concert, "rehearsal_rows": rows, "concert_row": concert_row})
    return ctx


# --------------------------------------------------------------------------
# The financial-aid need score (PRD §3.7)
# --------------------------------------------------------------------------

def test_aid_need_score_sums_band_sibling_seniority_loan_and_tier(api):
    """An aid review scores 40 + 8 + 15 + 6 + 3 = 72 for a BAND_A applicant with six years in the organization.

    PRD §3.7: "The review records `aid_reviewed_by_user_id` from the acting `X-User-ID`, which becomes the segregation-of-duties anchor for the award run, and it computes the waterfall sort key `aid_need_score` as an integer with no rounding: the band contributes 40 points for `BAND_A`, 25 for `BAND_B` and 10 for `BAND_C`; an enrolled sibling adds 8 points; seniority adds 3 points for each year in the organization up to a ceiling of five counted years, so the seniority term is 3 multiplied by the lesser of `years_in_org` and 5; a requested instrument loan on the accepted placement adds 6 points; and the tier snapshot adds 5 points for `SYMPHONY`, 3 for `PHILHARMONIC` and 1 for `CONCERT_ORCHESTRA`."

    Design: Corner/calculations/aid_need_score_sums_every_declared_component
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        instrument_loan_requested=True,
        ensemble_overrides={"tier": "PHILHARMONIC"},
        member_overrides={
            "household_income_band": "BAND_A",
            "years_in_org": 6,
            "sibling_enrolled": True,
        },
    )
    account_id = ctx["account"]["id"]
    member_id = ctx["member"]["id"]
    validate_success(
        api.request_aid(
            account_id, F.aid_request_payload(60000), guardian_headers(member_id)
        )
    )

    reviewed = validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))

    # 40 (BAND_A) + 8 (sibling) + 3 * min(6, 5) + 6 (loan) + 3 (PHILHARMONIC).
    assert reviewed["aid_need_score"] == 72
    assert reviewed["aid_status"] == "UNDER_REVIEW"


def test_aid_need_score_uses_band_c_and_concert_orchestra_points(api):
    """An aid review scores 10 + 1 = 11 for a BAND_C applicant with no sibling, no seniority and no loan.

    PRD §3.7: "The review records `aid_reviewed_by_user_id` from the acting `X-User-ID`, which becomes the segregation-of-duties anchor for the award run, and it computes the waterfall sort key `aid_need_score` as an integer with no rounding: the band contributes 40 points for `BAND_A`, 25 for `BAND_B` and 10 for `BAND_C`; an enrolled sibling adds 8 points; seniority adds 3 points for each year in the organization up to a ceiling of five counted years, so the seniority term is 3 multiplied by the lesser of `years_in_org` and 5; a requested instrument loan on the accepted placement adds 6 points; and the tier snapshot adds 5 points for `SYMPHONY`, 3 for `PHILHARMONIC` and 1 for `CONCERT_ORCHESTRA`."

    Design: Corner/calculations/aid_need_score_sums_every_declared_component
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        instrument_loan_requested=False,
        ensemble_overrides={"tier": "CONCERT_ORCHESTRA"},
        member_overrides={
            "household_income_band": "BAND_C",
            "years_in_org": 0,
            "sibling_enrolled": False,
        },
    )
    account_id = ctx["account"]["id"]
    member_id = ctx["member"]["id"]
    validate_success(
        api.request_aid(
            account_id, F.aid_request_payload(20000), guardian_headers(member_id)
        )
    )

    reviewed = validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))

    # 10 (BAND_C) + 0 (no sibling) + 3 * 0 + 0 (no loan) + 1 (CONCERT_ORCHESTRA).
    assert reviewed["aid_need_score"] == 11
    assert reviewed["aid_status"] == "UNDER_REVIEW"


# --------------------------------------------------------------------------
# Rubric weighting (PRD §3.4)
# --------------------------------------------------------------------------

def test_weighted_total_applies_the_four_rubric_weights(api):
    """Three sheets whose raw integers all add up to 73 weight out to three different totals.

    PRD §3.4: "Each sheet's `weighted_total` is computed before the row is persisted, by weighting the four raw rubric integers and rounding the sum half up to two decimal places: tone counts 1.2 times its raw score, rhythm 1.0 times, intonation 1.0 times, and sight-reading 0.8 times."

    Design: Corner/calculations/rubric_weights_separate_sheets_with_identical_raw_sums
    """
    rubric_sets = [
        _rubric(25, 15, 14, 19),  # 30.00 + 15 + 14 + 15.20 = 74.20
        _rubric(19, 15, 14, 25),  # 22.80 + 15 + 14 + 20.00 = 71.80
        _rubric(18, 17, 20, 18),  # 21.60 + 17 + 20 + 14.40 = 73.00
    ]
    for rubric in rubric_sets:
        assert sum(rubric.values()) == 73

    ctx = _scored_with_sheets(api, rubric_sets)

    assert _score(ctx["sheets"][0]["weighted_total"]) == 74.20
    assert _score(ctx["sheets"][1]["weighted_total"]) == 71.80
    assert _score(ctx["sheets"][2]["weighted_total"]) == 73.00


# --------------------------------------------------------------------------
# Composite rounding (PRD §2.7, §3.4)
# --------------------------------------------------------------------------

def test_provisional_composite_rounds_half_up_to_two_decimals(api):
    """Sheets of 80.40, 80.40 and 80.60 give a provisional composite of 80.47, not 80.46.

    PRD §3.4: "When that count reaches the slot's `quorum_required`, the server advances the audition `SCHEDULED → SCORED` and stores `composite_provisional_score`: the plain arithmetic mean of the `weighted_total` values of every sheet in the current round, rounded half up to two decimal places, with no trimming whatever the number of sheets."

    Design: Corner/calculations/composite_rounds_half_up_at_the_third_decimal
    """
    ctx = _scored_with_sheets(
        api,
        [
            _rubric(25, 16, 16, 23),  # 30 + 16 + 16 + 18.40 = 80.40
            _rubric(25, 16, 16, 23),  # 80.40
            _rubric(25, 17, 16, 22),  # 30 + 17 + 16 + 17.60 = 80.60
        ],
    )

    audition = ctx["audition"]
    assert audition["status"] == "SCORED"
    # 241.40 / 3 = 80.4666..., which rounds half up at the third decimal.
    assert _score(audition["composite_provisional_score"]) == 80.47


def test_final_composite_rounds_half_up_to_two_decimals(api):
    """The final composite over three untrimmed sheets is also stored as 80.47.

    PRD §2.7: "A panelist's `weighted_total`, an audition's `composite_provisional_score` and `composite_final_score`, and a participation row's `attendance_index` are all rounded half up to exactly two decimal places, and every threshold comparison against them is performed on the two-decimal value."

    Design: Corner/calculations/composite_rounds_half_up_at_the_third_decimal
    """
    ctx = _scored_with_sheets(
        api,
        [
            _rubric(25, 16, 16, 23),
            _rubric(25, 16, 16, 23),
            _rubric(25, 17, 16, 22),
        ],
    )

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert adjudicated["status"] == "ADJUDICATED"
    assert _score(adjudicated["composite_final_score"]) == 80.47


# --------------------------------------------------------------------------
# Tier recommendation bands (PRD §3.4)
# --------------------------------------------------------------------------

def test_tier_recommendation_is_symphony_at_exactly_the_upper_edge(api):
    """A final composite of exactly 85.00 recommends SYMPHONY.

    PRD §3.4: "Immediately after the final composite is stored, `tier_recommendation` is derived from it by three inclusive threshold comparisons on the two-decimal value: a composite of at least 85.00 recommends `SYMPHONY`; otherwise a composite of at least 75.00 recommends `PHILHARMONIC`; otherwise a composite of at least 62.50 recommends `CONCERT_ORCHESTRA`; and anything below that is `NOT_PLACED`."

    Design: Corner/calculations/tier_bands_are_inclusive_at_their_lower_edge
    """
    # 1.2*25 + 20 + 19 + 0.8*20 = 85.00 on every sheet.
    ctx = _scored_with_sheets(api, [_rubric(25, 20, 19, 20)] * 3)

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert _score(adjudicated["composite_final_score"]) == 85.00
    assert adjudicated["tier_recommendation"] == "SYMPHONY"


def test_tier_recommendation_is_philharmonic_at_exactly_seventy_five(api):
    """A final composite of exactly 75.00 recommends PHILHARMONIC.

    PRD §3.4: "Immediately after the final composite is stored, `tier_recommendation` is derived from it by three inclusive threshold comparisons on the two-decimal value: a composite of at least 85.00 recommends `SYMPHONY`; otherwise a composite of at least 75.00 recommends `PHILHARMONIC`; otherwise a composite of at least 62.50 recommends `CONCERT_ORCHESTRA`; and anything below that is `NOT_PLACED`."

    Design: Corner/calculations/tier_bands_are_inclusive_at_their_lower_edge
    """
    # 1.2*25 + 15 + 14 + 0.8*20 = 75.00 on every sheet.
    ctx = _scored_with_sheets(api, [_rubric(25, 15, 14, 20)] * 3)

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert _score(adjudicated["composite_final_score"]) == 75.00
    assert adjudicated["tier_recommendation"] == "PHILHARMONIC"


def test_tier_recommendation_drops_to_concert_orchestra_below_seventy_five(api):
    """A final composite of 74.20 falls out of the PHILHARMONIC band into CONCERT_ORCHESTRA.

    PRD §3.4: "Immediately after the final composite is stored, `tier_recommendation` is derived from it by three inclusive threshold comparisons on the two-decimal value: a composite of at least 85.00 recommends `SYMPHONY`; otherwise a composite of at least 75.00 recommends `PHILHARMONIC`; otherwise a composite of at least 62.50 recommends `CONCERT_ORCHESTRA`; and anything below that is `NOT_PLACED`."

    Design: Corner/calculations/tier_bands_are_inclusive_at_their_lower_edge
    """
    # 1.2*25 + 15 + 14 + 0.8*19 = 74.20 on every sheet.
    ctx = _scored_with_sheets(api, [_rubric(25, 15, 14, 19)] * 3)

    adjudicated = X.adjudicate(api, ctx["audition"]["id"])

    assert _score(adjudicated["composite_final_score"]) == 74.20
    assert adjudicated["tier_recommendation"] == "CONCERT_ORCHESTRA"


# --------------------------------------------------------------------------
# The tier multiplier on tuition (PRD §3.7)
# --------------------------------------------------------------------------

def test_symphony_tuition_multiplier_rounds_half_up(api):
    """A SYMPHONY seat on a 123223-cent base is assessed 154029 cents, rounded up from 154028.75.

    PRD §3.7: "The tier multiplier is the same in both: `SYMPHONY` charges 1.25 times the season's `tuition_base_cents`, `PHILHARMONIC` charges 1.00 times, and `CONCERT_ORCHESTRA` charges 0.80 times, with that gross product rounded half up to whole cents."

    Design: Corner/calculations/tuition_multiplier_selected_by_the_accounts_tier_snapshot
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        score_value=22,  # weighted 88.00, so SYMPHONY is an admissible offer
        instrument_loan_requested=False,
        ensemble_overrides={"tier": "SYMPHONY"},
    )

    account = ctx["account"]
    assert account["ensemble_tier"] == "SYMPHONY"
    assert account["assessed_cents"] == 154029


def test_philharmonic_tuition_multiplier_charges_the_base_figure(api):
    """A PHILHARMONIC seat on a 123223-cent base is assessed exactly 123223 cents.

    PRD §3.7: "The tier multiplier is the same in both: `SYMPHONY` charges 1.25 times the season's `tuition_base_cents`, `PHILHARMONIC` charges 1.00 times, and `CONCERT_ORCHESTRA` charges 0.80 times, with that gross product rounded half up to whole cents."

    Design: Corner/calculations/tuition_multiplier_selected_by_the_accounts_tier_snapshot
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        score_value=22,
        instrument_loan_requested=False,
        ensemble_overrides={"tier": "PHILHARMONIC"},
    )

    account = ctx["account"]
    assert account["ensemble_tier"] == "PHILHARMONIC"
    assert account["assessed_cents"] == 123223


def test_concert_orchestra_tuition_multiplier_rounds_down(api):
    """A musician recommended SYMPHONY who accepts a CONCERT_ORCHESTRA chair is assessed 98578 cents, rounded down from 98578.40.

    PRD §3.7: "The tier multiplier is the same in both: `SYMPHONY` charges 1.25 times the season's `tuition_base_cents`, `PHILHARMONIC` charges 1.00 times, and `CONCERT_ORCHESTRA` charges 0.80 times, with that gross product rounded half up to whole cents."

    Design: Corner/calculations/tuition_multiplier_selected_by_the_accounts_tier_snapshot
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        score_value=22,  # weighted 88.00, so the audition recommends SYMPHONY
        instrument_loan_requested=False,
        ensemble_overrides={"tier": "CONCERT_ORCHESTRA"},
    )

    assert ctx["audition"]["tier_recommendation"] == "SYMPHONY"
    account = ctx["account"]
    assert account["ensemble_tier"] == "CONCERT_ORCHESTRA"
    assert account["assessed_cents"] == 98578


# --------------------------------------------------------------------------
# The instrument loan fee (PRD §3.7)
# --------------------------------------------------------------------------

def test_string_instrument_loan_fee_is_4500_cents(api):
    """A violinist taking an organization instrument is charged the STRING loan fee of 4500 cents.

    PRD §3.7: "The instrument loan program is priced at the same moment: when the acceptance requested a loan, `instrument_loan_fee_cents` is 4500 cents for a `STRING` instrument, 6500 cents for a `WIND` instrument and 9000 cents for `PERCUSSION`, selected by `instrument_class_loaned`; when no loan was requested it is 0."

    Design: Corner/calculations/loan_fee_constant_selected_by_instrument_class
    """
    ctx = X.accepted_placement(
        api, instrument="VIOLIN", instrument_loan_requested=True
    )

    assert ctx["placement"]["instrument_class_loaned"] == "STRING"
    assert ctx["account"]["instrument_loan_fee_cents"] == 4500


def test_wind_instrument_loan_fee_is_6500_cents(api):
    """A flautist taking an organization instrument is charged the WIND loan fee of 6500 cents.

    PRD §3.7: "The instrument loan program is priced at the same moment: when the acceptance requested a loan, `instrument_loan_fee_cents` is 4500 cents for a `STRING` instrument, 6500 cents for a `WIND` instrument and 9000 cents for `PERCUSSION`, selected by `instrument_class_loaned`; when no loan was requested it is 0."

    Design: Corner/calculations/loan_fee_constant_selected_by_instrument_class
    """
    ctx = X.accepted_placement(api, instrument="FLUTE", instrument_loan_requested=True)

    assert ctx["placement"]["instrument_class_loaned"] == "WIND"
    assert ctx["account"]["instrument_loan_fee_cents"] == 6500


def test_percussion_instrument_loan_fee_is_9000_cents(api):
    """A percussionist taking an organization instrument is charged the PERCUSSION loan fee of 9000 cents.

    PRD §3.7: "The instrument loan program is priced at the same moment: when the acceptance requested a loan, `instrument_loan_fee_cents` is 4500 cents for a `STRING` instrument, 6500 cents for a `WIND` instrument and 9000 cents for `PERCUSSION`, selected by `instrument_class_loaned`; when no loan was requested it is 0."

    Design: Corner/calculations/loan_fee_constant_selected_by_instrument_class
    """
    ctx = X.accepted_placement(
        api, instrument="PERCUSSION", instrument_loan_requested=True
    )

    assert ctx["placement"]["instrument_class_loaned"] == "PERCUSSION"
    assert ctx["account"]["instrument_loan_fee_cents"] == 9000


def test_loan_fee_is_added_on_top_of_the_assessment_in_the_balance(api):
    """A 123223-cent assessment plus a 4500-cent string loan leaves a balance of 127723 cents.

    PRD §3.7: "The account's `balance_cents` is then `assessed_cents`, less `aid_effective_cents`, plus `instrument_loan_fee_cents`, less `payments_total_cents`."

    Design: Corner/calculations/loan_fee_constant_selected_by_instrument_class
    """
    ctx = X.accepted_placement(
        api,
        instrument="VIOLIN",
        instrument_loan_requested=True,
        ensemble_overrides={"tier": "PHILHARMONIC"},
    )

    account = ctx["account"]
    assert account["assessed_cents"] == 123223
    assert account["instrument_loan_fee_cents"] == 4500
    assert account["balance_cents"] == 127723


# --------------------------------------------------------------------------
# The attendance index (PRD §3.8)
# --------------------------------------------------------------------------

def test_attendance_index_ignores_rehearsals_outside_the_window(api):
    """Rehearsals before the eligibility window and after the concert's start are left out of the index.

    PRD §3.8: "Its scope is the `REHEARSAL` events of the *same* ensemble whose `start_at` is at or after the performance's `eligibility_window_start` and strictly before the performance's own `start_at` — a half-open window."

    Design: Corner/calculations/attendance_index_counts_only_in_window_recorded_rehearsals
    """
    ctx = _rehearsal_then_concert(
        api,
        [
            # Before the window opens.
            {
                "start_at": "2026-09-20T18:00:00Z",
                "end_at": "2026-09-20T20:00:00Z",
                "attendance_status": "UNEXCUSED_ABSENT",
            },
            {
                "start_at": "2026-09-27T18:00:00Z",
                "end_at": "2026-09-27T20:00:00Z",
                "attendance_status": "UNEXCUSED_ABSENT",
            },
            # Inside the window.
            {
                "start_at": "2026-10-05T18:00:00Z",
                "end_at": "2026-10-05T20:00:00Z",
                "attendance_status": "PRESENT",
            },
            {
                "start_at": "2026-10-12T18:00:00Z",
                "end_at": "2026-10-12T20:00:00Z",
                "attendance_status": "PRESENT",
            },
            {
                "start_at": "2026-10-19T18:00:00Z",
                "end_at": "2026-10-19T20:00:00Z",
                "attendance_status": "PRESENT",
            },
            {
                "start_at": "2026-10-26T18:00:00Z",
                "end_at": "2026-10-26T20:00:00Z",
                "attendance_status": "PRESENT",
            },
            {
                "start_at": "2026-11-02T18:00:00Z",
                "end_at": "2026-11-02T20:00:00Z",
                "attendance_status": None,
            },
            # After the concert has started.
            {
                "start_at": "2026-11-16T18:00:00Z",
                "end_at": "2026-11-16T20:00:00Z",
                "attendance_status": "TARDY",
            },
        ],
    )

    reviewed = X.review_eligibility(api, ctx["concert_row"]["id"])

    # Only the four in-window PRESENT rehearsals are counted: 100 * 4.0 / 4.
    assert _score(reviewed["attendance_index"]) == 100.00


def test_attendance_index_excludes_unrecorded_rehearsals(api):
    """An unrecorded in-window rehearsal leaves the index at 100.00 rather than halving it.

    PRD §3.8: "Within that scope, the counted rows are this musician's participation rows on those rehearsals whose `attendance_status` is anything other than `NOT_RECORDED`; an unrecorded rehearsal is excluded from both the numerator and the denominator."

    Design: Corner/calculations/attendance_index_counts_only_in_window_recorded_rehearsals
    """
    ctx = _rehearsal_then_concert(
        api,
        [
            {
                "start_at": "2026-10-05T18:00:00Z",
                "end_at": "2026-10-05T20:00:00Z",
                "attendance_status": "PRESENT",
            },
            {
                "start_at": "2026-11-02T18:00:00Z",
                "end_at": "2026-11-02T20:00:00Z",
                "attendance_status": None,
            },
        ],
    )

    reviewed = X.review_eligibility(api, ctx["concert_row"]["id"])

    # One counted row of weight 1.0, not two rows of 1.0 and 0.0.
    assert _score(reviewed["attendance_index"]) == 100.00


def test_eligibility_is_granted_when_the_index_meets_the_threshold(api):
    """A clear-standing musician with a 100.00 index on a concert that needs no dress rehearsal is ELIGIBLE.

    PRD §3.8: "Eligibility is granted only when three conditions all hold: `attendance_index` is at least 80.00; when the performance's `dress_rehearsal_required` is true, the musician's participation on the latest dress-rehearsal-flagged `REHEARSAL` of that ensemble inside the window carries `attendance_status` `PRESENT`; and the musician's `standing_status` is not `ATTENDANCE_PROBATION`."

    Design: Corner/calculations/attendance_index_counts_only_in_window_recorded_rehearsals
    """
    ctx = _rehearsal_then_concert(
        api,
        [
            {
                "start_at": "2026-10-05T18:00:00Z",
                "end_at": "2026-10-05T20:00:00Z",
                "attendance_status": "PRESENT",
            },
        ],
    )
    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "CLEAR"

    reviewed = X.review_eligibility(api, ctx["concert_row"]["id"])

    assert _score(reviewed["attendance_index"]) == 100.00
    assert reviewed["performance_eligibility"] == "ELIGIBLE"
    assert reviewed["ineligibility_reason"] == "NONE"


# --------------------------------------------------------------------------
# The aid award waterfall (PRD §3.7)
# --------------------------------------------------------------------------

def test_aid_grant_is_clamped_to_the_per_member_ceiling(api):
    """The neediest applicant's 40000-cent request is cut to the 30000-cent ceiling on a 100000-cent budget.

    PRD §3.7: "A per-member ceiling equal to thirty percent of the season's `aid_budget_cents`, rounded half up to whole cents, is computed once for the whole run."

    Design: Corner/calculations/aid_waterfall_pays_in_need_order_and_a_denial_keeps_the_money
    """
    ctx = _aid_run_season(api)

    _run_aid_award(api, ctx["season"]["id"])

    nora = X.read_account(api, ctx["entries"][0]["account"]["id"])
    assert nora["aid_need_score"] == 63
    assert nora["aid_status"] == "APPROVED"
    assert nora["aid_awarded_cents"] == 30000


def test_aid_request_below_the_minimum_award_is_denied_below_min_award(api):
    """A 3000-cent request is denied with BELOW_MIN_AWARD while 70000 cents of budget still remain.

    PRD §3.7: "If the candidate grant falls below 5000 cents, the account is denied instead — `aid_awarded_cents` is set to 0, `aid_status` becomes `DENIED`, and `aid_denial_reason` records `INSUFFICIENT_BUDGET` when the running remainder was the binding constraint by being itself below 5000 cents, and `BELOW_MIN_AWARD` otherwise."

    Design: Corner/calculations/aid_waterfall_pays_in_need_order_and_a_denial_keeps_the_money
    """
    ctx = _aid_run_season(api)

    _run_aid_award(api, ctx["season"]["id"])

    milo = X.read_account(api, ctx["entries"][1]["account"]["id"])
    assert milo["aid_need_score"] == 31
    assert milo["aid_status"] == "DENIED"
    assert milo["aid_awarded_cents"] == 0
    assert milo["aid_denial_reason"] == "BELOW_MIN_AWARD"


def test_a_denial_leaves_the_remainder_for_the_applicants_behind_it(api):
    """The last applicant in the queue still receives her full 20000 cents after the middle applicant is denied.

    PRD §3.7: "Crucially, a denial does **not** decrease the running remainder: the money stays in the pool for the applicants behind it, and clamping the grant *before* the minimum-award test, rather than committing and then reversing, is what makes the later applicants' outcomes depend observably on queue order."

    Design: Corner/calculations/aid_waterfall_pays_in_need_order_and_a_denial_keeps_the_money
    """
    ctx = _aid_run_season(api)

    _run_aid_award(api, ctx["season"]["id"])

    lena = X.read_account(api, ctx["entries"][2]["account"]["id"])
    assert lena["aid_need_score"] == 13
    assert lena["aid_status"] == "APPROVED"
    assert lena["aid_awarded_cents"] == 20000


def test_aid_pool_halves_after_the_award_run(api):
    """Two grants of 30000 and 20000 cents leave 50000 committed and 50000 available on a 100000-cent budget.

    PRD §3.7: "After the walk, `aid_available_cents` is set to `aid_budget_cents` minus `aid_committed_cents`."

    Design: Corner/calculations/aid_waterfall_pays_in_need_order_and_a_denial_keeps_the_money
    """
    ctx = _aid_run_season(api)

    run = _run_aid_award(api, ctx["season"]["id"])

    assert run["aid_committed_cents"] == 50000
    assert run["aid_available_cents"] == 50000
    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_committed_cents"] == 50000
    assert season["aid_available_cents"] == 50000


def test_aid_award_run_reports_its_approved_and_denied_counts(api):
    """A run over three reviewed accounts reports two approvals and one denial.

    PRD §3.7: "The run reports `approved_count`, `denied_count`, and the season's resulting `aid_committed_cents` and `aid_available_cents`, and it increments the season's `version`."

    Design: Corner/calculations/aid_waterfall_pays_in_need_order_and_a_denial_keeps_the_money
    """
    ctx = _aid_run_season(api)
    version_before = X.season_version(api, ctx["season"]["id"])

    run = _run_aid_award(api, ctx["season"]["id"])

    assert run["approved_count"] == 2
    assert run["denied_count"] == 1
    assert X.season_version(api, ctx["season"]["id"]) == version_before + 1


# --------------------------------------------------------------------------
# Waitlist promotion order (PRD §3.5)
# --------------------------------------------------------------------------

def test_waitlist_promotion_takes_the_highest_composite(api):
    """Declining the open offer promotes the waitlisted musician with the highest final composite.

    PRD §3.5: "The queue is every placement of that ensemble sitting in `WAITLISTED` whose musician's `primary_instrument` equals the section's `instrument`, ordered by the referenced audition's `composite_final_score` descending, then by the placement's own `created_at` ascending; the row's `id` is never a tie-break."

    Design: Corner/calculations/waitlist_promotes_by_score_then_by_created_at
    """
    ctx = _waitlist_season(api)
    entries = ctx["entries"]

    _decline(api, entries[0]["placement"]["id"], entries[0]["member"]["id"])

    tia = X.read_placement(api, entries[1]["placement"]["id"])
    assert _score(entries[1]["audition"]["composite_final_score"]) == 94.60
    assert tia["status"] == "OFFERED"
    assert tia["waitlist_rank"] is None


def test_waitlist_ranks_break_a_composite_tie_by_created_at(api):
    """Two waitlisted musicians tied at 81.80 are ranked with the earlier-created row first.

    PRD §3.5: "The queue is every placement of that ensemble sitting in `WAITLISTED` whose musician's `primary_instrument` equals the section's `instrument`, ordered by the referenced audition's `composite_final_score` descending, then by the placement's own `created_at` ascending; the row's `id` is never a tie-break."

    Design: Corner/calculations/waitlist_promotes_by_score_then_by_created_at
    """
    ctx = _waitlist_season(api)
    entries = ctx["entries"]
    assert _score(entries[2]["audition"]["composite_final_score"]) == 81.80
    assert _score(entries[3]["audition"]["composite_final_score"]) == 81.80

    _decline(api, entries[0]["placement"]["id"], entries[0]["member"]["id"])

    eli = X.read_placement(api, entries[2]["placement"]["id"])
    lou = X.read_placement(api, entries[3]["placement"]["id"])
    assert eli["status"] == "WAITLISTED"
    assert eli["waitlist_rank"] == 1
    assert lou["status"] == "WAITLISTED"
    assert lou["waitlist_rank"] == 2


def test_promoted_offer_expires_seventy_two_hours_after_the_clock(api):
    """A promoted waitlist row is given an offer expiry seventy-two hours past the logical clock.

    PRD §3.5: "If the queue is non-empty and the section's `filled_count` plus the ensemble's `offered_count` is strictly below the section's `max_count`, the head of the queue is promoted: its status moves `WAITLISTED → OFFERED`, its `offer_expires_at` is set to the logical clock advanced by seventy-two hours, its `waitlist_rank` is cleared to null, the ensemble's `offered_count` increments by one, a tuition account is opened for that musician and season if none exists, and the rows behind it are re-ranked densely from 1."

    Design: Corner/calculations/waitlist_promotes_by_score_then_by_created_at
    """
    ctx = _waitlist_season(api)
    entries = ctx["entries"]
    assert ctx["clock"] == "2026-08-05T10:00:00Z"

    _decline(api, entries[0]["placement"]["id"], entries[0]["member"]["id"])

    promoted = X.read_placement(api, entries[1]["placement"]["id"])
    assert promoted["status"] == "OFFERED"
    A.assert_instants_equal(promoted["offer_expires_at"], "2026-08-08T10:00:00Z")


def test_second_decline_promotes_the_next_row_and_reranks_densely(api):
    """Declining the promoted offer promotes the next musician and renumbers the remaining queue from 1.

    PRD §3.5: "Every row in the queue receives a fresh 1-based `waitlist_rank` in that order, and `WITHDRAWN` rows are excluded permanently."

    Design: Corner/calculations/waitlist_promotes_by_score_then_by_created_at
    """
    ctx = _waitlist_season(api)
    entries = ctx["entries"]
    _decline(api, entries[0]["placement"]["id"], entries[0]["member"]["id"])

    _decline(api, entries[1]["placement"]["id"], entries[1]["member"]["id"])

    eli = X.read_placement(api, entries[2]["placement"]["id"])
    lou = X.read_placement(api, entries[3]["placement"]["id"])
    assert eli["status"] == "OFFERED"
    assert eli["waitlist_rank"] is None
    assert lou["status"] == "WAITLISTED"
    assert lou["waitlist_rank"] == 1
