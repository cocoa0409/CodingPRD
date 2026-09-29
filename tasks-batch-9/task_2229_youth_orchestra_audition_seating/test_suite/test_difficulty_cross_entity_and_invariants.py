"""Cross-entity gates, buffered and half-open interval overlap, conserved quantities.

Every test builds its own world from the public endpoints, because the harness
restarts the server and empties the database before each test.
"""

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
    guardian_headers,
)


# --------------------------------------------------------------------------
# Local helpers (no shared infrastructure is modified)
# --------------------------------------------------------------------------

def _rows_and_total(api_method, headers, **filters):
    """A full filtered page plus the envelope's `total_count`."""
    params = {"limit": C.MAX_LIMIT, "offset": 0}
    params.update(filters)
    rows, meta = validate_paginated(api_method(headers, params=params))
    return rows, meta["total_count"]


def _placement_stage(api, ensemble_specs, member_specs, season_overrides=None,
                     clock=C.FIXTURE_CLOCK):
    """A season sitting in `PLACEMENT` with adjudicated cellists ready to place.

    `ensemble_specs` is a list of {"ensemble": kwargs, "quota": kwargs}; each
    `member_specs` entry is member kwargs plus a `score` giving the uniform
    rubric integer every sheet carries, so `weighted_total` is exactly 4x it.
    """
    X.set_clock(api, clock)
    season = X.create_season(api, **(season_overrides or {}))

    ensembles = []
    quotas = []
    for index, spec in enumerate(ensemble_specs):
        ensemble_kwargs = dict(spec.get("ensemble", {}))
        ensemble_kwargs.setdefault("name", f"Orchestra {index + 1}")
        ensemble = X.create_ensemble(api, season["id"], **ensemble_kwargs)
        ensembles.append(ensemble)
        quotas.append(X.create_section_quota(api, ensemble["id"], **spec.get("quota", {})))

    members = []
    scores = []
    for index, spec in enumerate(member_specs):
        member_kwargs = {k: v for k, v in spec.items() if k != "score"}
        member_kwargs.setdefault("legal_name", f"Musician {index + 1}")
        members.append(X.create_member(api, **member_kwargs))
        scores.append(spec.get("score", 20))

    panelists = X.create_panelists(api, count=3)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        capacity=len(member_specs),
    )

    auditions = []
    for member in members:
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        auditions.append(audition)

    adjudicated = []
    for audition, score in zip(auditions, scores):
        X.submit_uniform_sheets(api, audition["id"], panelists, score)
        adjudicated.append(X.adjudicate(api, audition["id"]))

    season = X.advance_season(api, season["id"], "PLACEMENT")
    return {
        "season": season,
        "ensembles": ensembles,
        "quotas": quotas,
        "members": members,
        "auditions": adjudicated,
        "panelists": panelists,
        "slot": slot,
    }


def _offer_and_accept(api, audition_id, ensemble_id, member_id):
    placement = X.create_placement(api, audition_id, ensemble_id)
    return X.accept_placement(api, placement["id"], member_id)


def _two_ensembles_one_seated(api):
    """Two PHILHARMONIC ensembles; the first is `SEATED`, the second `FORMING`."""
    quota = {"min_count": 1, "target_count": 1, "max_count": 2}
    ctx = _placement_stage(
        api,
        ensemble_specs=[
            {"ensemble": {"name": "Philharmonic A"}, "quota": dict(quota)},
            {"ensemble": {"name": "Philharmonic B"}, "quota": dict(quota)},
        ],
        member_specs=[{"score": 20}, {"score": 20}],
    )
    _offer_and_accept(
        api,
        ctx["auditions"][0]["id"],
        ctx["ensembles"][0]["id"],
        ctx["members"][0]["id"],
    )
    return ctx


def _seated_member_with_rehearsal_and_concert(api):
    """One seated cellist, a recorded rehearsal, and an upcoming concert."""
    ctx = X.accepted_placement(api)
    member_id = ctx["member"]["id"]
    rehearsal = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="REHEARSAL",
        start_at="2026-10-02T19:00:00Z",
        end_at="2026-10-02T21:00:00Z",
    )
    concert = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="CONCERT",
        start_at="2026-11-05T19:00:00Z",
        end_at="2026-11-05T21:00:00Z",
        eligibility_window_start="2026-10-01T00:00:00Z",
        soloist_selection_mode="NONE",
    )
    rehearsal_row = X.create_participation(api, rehearsal["id"], member_id)
    concert_row = X.create_participation(api, concert["id"], member_id)
    X.set_clock(api, "2026-10-02T19:30:00Z")
    X.record_attendance(api, rehearsal_row["id"], "PRESENT")
    ctx.update(
        {
            "rehearsal": rehearsal,
            "concert": concert,
            "rehearsal_row": rehearsal_row,
            "concert_row": concert_row,
        }
    )
    return ctx


def _in_season_with_delinquent_account(api):
    """A season at `IN_SEASON` whose only tuition account went `DELINQUENT`."""
    ctx = X.accepted_placement(
        api, season_overrides={"tuition_due_at": "2026-09-01T00:00:00Z"}
    )
    X.set_clock(api, "2026-09-02T09:00:00Z")
    ctx["account"] = validate_success(
        api.finalize_assessment(ctx["account"]["id"], {}, FINANCE_HEADERS)
    )
    return ctx


def _panel_calendar_stage(api):
    """One slot in room R1 from 10:00 to 11:00 staffed by the first three of six."""
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=6)
    first_slot = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in panelists[:3]],
        room_code="R1",
        start_at="2026-08-12T10:00:00Z",
        end_at="2026-08-12T11:00:00Z",
    )
    ctx.update({"panelists": panelists, "first_slot": first_slot})
    return ctx


def _two_seated_members_with_three_concerts(api):
    """Two seated cellists and three concerts: 19:00-21:00, 21:00-23:00, 20:59-22:00."""
    ctx = _placement_stage(
        api,
        ensemble_specs=[{"quota": {"min_count": 1, "target_count": 2, "max_count": 3}}],
        member_specs=[{"score": 20}, {"score": 20}],
    )
    for audition, member in zip(ctx["auditions"], ctx["members"]):
        _offer_and_accept(api, audition["id"], ctx["ensembles"][0]["id"], member["id"])

    windows = [
        ("2026-11-01T19:00:00Z", "2026-11-01T21:00:00Z"),
        ("2026-11-01T21:00:00Z", "2026-11-01T23:00:00Z"),
        ("2026-11-01T20:59:00Z", "2026-11-01T22:00:00Z"),
    ]
    ctx["events"] = [
        X.create_ensemble_event(
            api,
            ctx["ensembles"][0]["id"],
            kind="CONCERT",
            start_at=start_at,
            end_at=end_at,
            eligibility_window_start="2026-10-01T00:00:00Z",
            soloist_selection_mode="NONE",
        )
        for start_at, end_at in windows
    ]
    return ctx


def _aid_under_review(api):
    """A `BAND_C` family with a 30000-cent request sitting in `UNDER_REVIEW`."""
    ctx = X.accepted_placement(
        api,
        member_overrides={
            "household_income_band": "BAND_C",
            "sibling_enrolled": True,
            "years_in_org": 1,
        },
    )
    account_id = ctx["account"]["id"]
    validate_success(
        api.request_aid(
            account_id,
            F.aid_request_payload(30000),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    ctx["account"] = validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))
    return ctx


def _run_aid_award(api, season_id):
    """The waterfall, run by an officer who did not review any queued request."""
    return validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )


def _rotating_section_two_chairs(api):
    """A `ROTATING` VIOLIN-sized section of two chairs inside a `SEATED` ensemble."""
    ctx = _placement_stage(
        api,
        ensemble_specs=[
            {
                "ensemble": {"min_total_size": 2},
                "quota": {
                    "min_count": 1,
                    "target_count": 2,
                    "max_count": 2,
                    "principal_required": True,
                    "rotation_policy": "ROTATING",
                },
            }
        ],
        member_specs=[
            {"score": 23, "years_in_org": 3},
            {"score": 20, "years_in_org": 1},
        ],
    )
    for audition, member in zip(ctx["auditions"], ctx["members"]):
        _offer_and_accept(api, audition["id"], ctx["ensembles"][0]["id"], member["id"])
    ctx["seats"] = [
        X.sole_active_seat(api, ctx["members"][0]["id"]),
        X.sole_active_seat(api, ctx["members"][1]["id"]),
    ]
    return ctx


def _seat_ledger_stage(api):
    """A two-chair section with one acceptance banked and one offer still open."""
    ctx = _placement_stage(
        api,
        ensemble_specs=[
            {
                "ensemble": {"min_total_size": 2, "max_total_size": 2},
                "quota": {"min_count": 1, "target_count": 2, "max_count": 2},
            }
        ],
        member_specs=[
            {"score": 20, "years_in_org": 2},
            {"score": 20, "years_in_org": 0},
        ],
    )
    ensemble_id = ctx["ensembles"][0]["id"]
    ctx["placements"] = [
        X.create_placement(api, ctx["auditions"][0]["id"], ensemble_id),
        X.create_placement(api, ctx["auditions"][1]["id"], ensemble_id),
    ]
    ctx["placements"][0] = X.accept_placement(
        api, ctx["placements"][0]["id"], ctx["members"][0]["id"]
    )
    ctx["first_seat"] = X.sole_active_seat(api, ctx["members"][0]["id"])
    return ctx


def _active_seats_of_section(api, quota_id):
    return [
        seat
        for seat in X.list_seats(api, section_quota_id=quota_id)
        if seat["status"] == "ACTIVE"
    ]


# --------------------------------------------------------------------------
# Placement is gated by the target ensemble's roster_state
# --------------------------------------------------------------------------

def test_offer_into_seated_ensemble_is_refused(api):
    """A placement offer is refused when the target ensemble is already SEATED.

    PRD §3.5: "The season must be in `PLACEMENT` and the target ensemble's `roster_state` must be `FORMING`; a `SEATED` or `CLOSED` ensemble accepts no further offers or waitlist claims, and either failure is `ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS`."

    Design: Difficulty/cross_entity_state_dependency/placement_gated_by_target_ensemble_roster_state
    """
    ctx = _two_ensembles_one_seated(api)
    seated = X.read_ensemble(api, ctx["ensembles"][0]["id"])
    quota = X.read_section_quota(api, ctx["quotas"][0]["id"])
    assert seated["roster_state"] == "SEATED"
    assert quota["filled_count"] == 1 and quota["balance_state"] == "FULL"
    assert X.read_season(api, ctx["season"]["id"])["status"] == "PLACEMENT"

    payload = F.placement_payload(
        ctx["auditions"][1]["id"],
        seated["id"],
        X.ensemble_version(api, seated["id"]),
        offer_kind="OFFER",
    )
    validate_error(
        api.create_placement(payload, DIRECTOR_HEADERS),
        ApiErrorId.ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS.value,
    )

    _, total = _rows_and_total(
        api.list_placements,
        DIRECTOR_HEADERS,
        audition_id=ctx["auditions"][1]["id"],
        ensemble_id=seated["id"],
    )
    assert total == 0
    assert X.read_ensemble(api, seated["id"])["offered_count"] == 0


def test_offer_into_forming_ensemble_is_admitted(api):
    """The same offer is admitted against a sibling ensemble still FORMING.

    PRD §3.5: "The season must be in `PLACEMENT` and the target ensemble's `roster_state` must be `FORMING`; a `SEATED` or `CLOSED` ensemble accepts no further offers or waitlist claims, and either failure is `ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS`."

    Design: Difficulty/cross_entity_state_dependency/placement_gated_by_target_ensemble_roster_state
    """
    ctx = _two_ensembles_one_seated(api)
    forming = X.read_ensemble(api, ctx["ensembles"][1]["id"])
    assert forming["roster_state"] == "FORMING"

    payload = F.placement_payload(
        ctx["auditions"][1]["id"],
        forming["id"],
        forming["version"],
        offer_kind="OFFER",
    )
    placement = validate_success(api.create_placement(payload, DIRECTOR_HEADERS), 201)
    assert placement["status"] == "OFFERED"
    assert placement["member_id"] == ctx["members"][1]["id"]

    assert X.read_ensemble(api, forming["id"])["offered_count"] == 1
    assert X.read_ensemble(api, ctx["ensembles"][0]["id"])["offered_count"] == 0


# --------------------------------------------------------------------------
# Eligibility review is gated by the parent event's kind
# --------------------------------------------------------------------------

def test_eligibility_review_refused_on_rehearsal_participation(api):
    """An eligibility review on a rehearsal participation row is refused.

    PRD §3.8: "The second dimension, `performance_eligibility`, is the `ArtisticDirector`'s judgement and applies only to performances: an eligibility review on a `REHEARSAL` is refused with `ERR_EVENT_KIND_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/eligibility_review_gated_by_event_kind
    """
    ctx = _seated_member_with_rehearsal_and_concert(api)
    validate_error(
        api.review_eligibility(
            ctx["rehearsal_row"]["id"], F.eligibility_review_payload(), DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_EVENT_KIND_NOT_ELIGIBLE.value,
    )

    row = X.read_participation(api, ctx["rehearsal_row"]["id"])
    assert row["performance_eligibility"] == "UNREVIEWED"
    assert row["attendance_status"] == "PRESENT"


def test_eligibility_review_admitted_on_concert_participation(api):
    """The same review on the concert row grants eligibility on a perfect index.

    PRD §3.8: "Eligibility is granted only when three conditions all hold: `attendance_index` is at least 80.00; when the performance's `dress_rehearsal_required` is true, the musician's participation on the latest dress-rehearsal-flagged `REHEARSAL` of that ensemble inside the window carries `attendance_status` `PRESENT`; and the musician's `standing_status` is not `ATTENDANCE_PROBATION`."

    Design: Difficulty/cross_entity_state_dependency/eligibility_review_gated_by_event_kind
    """
    ctx = _seated_member_with_rehearsal_and_concert(api)
    reviewed = validate_success(
        api.review_eligibility(
            ctx["concert_row"]["id"], F.eligibility_review_payload(), DIRECTOR_HEADERS
        )
    )
    assert reviewed["attendance_index"] == 100.00
    assert reviewed["performance_eligibility"] == "ELIGIBLE"
    assert reviewed["ineligibility_reason"] == "NONE"


def test_tour_requirements_refused_on_concert_participation(api):
    """Tour readiness work is refused on a concert row the review just accepted.

    PRD §3.9: "A `Guardian` works their own musician's row toward readiness by crediting fundraising and registering a chaperone; the attempt is refused with `ERR_EVENT_KIND_NOT_ELIGIBLE` on any event whose `kind` is not `TOUR_PERFORMANCE` or `FESTIVAL`."

    Design: Difficulty/cross_entity_state_dependency/eligibility_review_gated_by_event_kind
    """
    ctx = _seated_member_with_rehearsal_and_concert(api)
    validate_success(
        api.review_eligibility(
            ctx["concert_row"]["id"], F.eligibility_review_payload(), DIRECTOR_HEADERS
        )
    )
    validate_error(
        api.submit_tour_requirements(
            ctx["concert_row"]["id"],
            F.tour_requirements_payload(fundraising_amount_cents=1000),
            guardian_headers(ctx["member"]["id"]),
        ),
        ApiErrorId.ERR_EVENT_KIND_NOT_ELIGIBLE.value,
    )
    assert X.read_participation(api, ctx["concert_row"]["id"])["tour_status"] == "NOT_APPLICABLE"


# --------------------------------------------------------------------------
# The season close is gated by a delinquent tuition account
# --------------------------------------------------------------------------

def test_season_close_refused_while_an_account_is_delinquent(api):
    """A delinquent tuition account of the season refuses the close.

    PRD §3.1: "Closing a season additionally requires that no tuition account of that season carries `billing_status` `DELINQUENT`; a delinquent account refuses the close with `ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE`."

    Design: Difficulty/cross_entity_state_dependency/season_close_gated_by_delinquent_tuition_account
    """
    ctx = _in_season_with_delinquent_account(api)
    assert ctx["account"]["assessed_cents"] == 123223
    assert ctx["account"]["balance_cents"] == 123223
    assert ctx["account"]["billing_status"] == "DELINQUENT"
    assert X.read_member(api, ctx["member"]["id"])["standing_status"] == "FINANCIAL_HOLD"

    validate_error(
        api.advance_season_status(
            ctx["season"]["id"], F.advance_status_payload("CLOSED"), DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE.value,
    )
    assert X.read_season(api, ctx["season"]["id"])["status"] == "IN_SEASON"
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "SEATED"


def test_season_close_admitted_once_the_payment_clears_the_delinquency(api):
    """The identical close succeeds once a payment clears the delinquent account.

    PRD §3.1: "Closing a season additionally requires that no tuition account of that season carries `billing_status` `DELINQUENT`; a delinquent account refuses the close with `ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE`."

    Design: Difficulty/cross_entity_state_dependency/season_close_gated_by_delinquent_tuition_account
    """
    ctx = _in_season_with_delinquent_account(api)
    paid = validate_success(
        api.record_payment(
            ctx["account"]["id"],
            F.payment_payload(123223),
            guardian_headers(ctx["member"]["id"]),
        ),
        201,
    )
    assert paid["payments_total_cents"] == 123223
    assert paid["balance_cents"] == 0
    assert paid["billing_status"] == "PAID_IN_FULL"

    closed = validate_success(
        api.advance_season_status(
            ctx["season"]["id"], F.advance_status_payload("CLOSED"), DIRECTOR_HEADERS
        )
    )
    assert closed["status"] == "CLOSED"


def test_season_close_cascade_closes_every_open_ensemble(api):
    """The successful close walks down into the season's open ensembles.

    PRD §3.1: "First, every ensemble of the season whose `roster_state` is `FORMING` or `SEATED` moves to `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/season_close_gated_by_delinquent_tuition_account
    """
    ctx = _in_season_with_delinquent_account(api)
    validate_success(
        api.record_payment(
            ctx["account"]["id"],
            F.payment_payload(123223),
            guardian_headers(ctx["member"]["id"]),
        ),
        201,
    )
    validate_success(
        api.advance_season_status(
            ctx["season"]["id"], F.advance_status_payload("CLOSED"), DIRECTOR_HEADERS
        )
    )
    assert X.read_ensemble(api, ctx["ensemble"]["id"])["roster_state"] == "CLOSED"


# --------------------------------------------------------------------------
# An adjudicator's calendar is buffered by fifteen minutes on both sides
# --------------------------------------------------------------------------

def test_panelist_booked_ten_minutes_after_a_slot_is_refused(api):
    """Re-booking the same panel ten minutes after their slot ends is refused.

    PRD §3.3: "The same buffered comparison governs a panelist's own calendar: every identifier in `panelist_ids` must belong to an adjudicator whose `available_for_panels` is true, and no requested adjudicator may already be seated on another slot whose buffered interval overlaps this one — either failure is `ERR_PANELIST_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/panelist_calendar_buffered_strict_overlap
    """
    ctx = _panel_calendar_stage(api)
    payload = F.audition_slot_payload(
        ctx["season"]["id"],
        [p["id"] for p in ctx["panelists"][:3]],
        room_code="R2",
        start_at="2026-08-12T11:10:00Z",
        end_at="2026-08-12T11:40:00Z",
    )
    validate_error(
        api.create_audition_slot(payload, REGISTRAR_HEADERS),
        ApiErrorId.ERR_PANELIST_UNAVAILABLE.value,
    )

    _, total = _rows_and_total(
        api.list_audition_slots, REGISTRAR_HEADERS, season_id=ctx["season"]["id"]
    )
    assert total == 1


def test_panelist_booked_exactly_fifteen_minutes_after_a_slot_is_admitted(api):
    """The same panel is bookable when the gap is exactly the fifteen-minute buffer.

    PRD §3.3: "The same buffered comparison governs a panelist's own calendar: every identifier in `panelist_ids` must belong to an adjudicator whose `available_for_panels` is true, and no requested adjudicator may already be seated on another slot whose buffered interval overlaps this one — either failure is `ERR_PANELIST_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/panelist_calendar_buffered_strict_overlap
    """
    ctx = _panel_calendar_stage(api)
    payload = F.audition_slot_payload(
        ctx["season"]["id"],
        [p["id"] for p in ctx["panelists"][:3]],
        room_code="R2",
        start_at="2026-08-12T11:15:00Z",
        end_at="2026-08-12T11:45:00Z",
    )
    slot = validate_success(api.create_audition_slot(payload, REGISTRAR_HEADERS), 201)
    assert slot["status"] == "OPEN"
    A.assert_instants_equal(slot["start_at"], "2026-08-12T11:15:00Z")

    _, total = _rows_and_total(
        api.list_audition_slots, REGISTRAR_HEADERS, season_id=ctx["season"]["id"]
    )
    assert total == 2


def test_refused_interval_is_admitted_for_an_untouched_panel(api):
    """The refused interval is legal for adjudicators with an empty calendar.

    PRD §3.3: "The same buffered comparison governs a panelist's own calendar: every identifier in `panelist_ids` must belong to an adjudicator whose `available_for_panels` is true, and no requested adjudicator may already be seated on another slot whose buffered interval overlaps this one — either failure is `ERR_PANELIST_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/panelist_calendar_buffered_strict_overlap
    """
    ctx = _panel_calendar_stage(api)
    payload = F.audition_slot_payload(
        ctx["season"]["id"],
        [p["id"] for p in ctx["panelists"][3:]],
        room_code="R3",
        start_at="2026-08-12T11:10:00Z",
        end_at="2026-08-12T11:40:00Z",
    )
    slot = validate_success(api.create_audition_slot(payload, REGISTRAR_HEADERS), 201)
    assert slot["booked_count"] == 0
    assert sorted(slot["panelist_ids"]) == sorted(p["id"] for p in ctx["panelists"][3:])

    _, total = _rows_and_total(
        api.list_audition_slots,
        REGISTRAR_HEADERS,
        season_id=ctx["season"]["id"],
        room_code="R3",
    )
    assert total == 1


# --------------------------------------------------------------------------
# A musician's own calendar uses plain half-open intervals
# --------------------------------------------------------------------------

def test_back_to_back_events_do_not_conflict_for_one_musician(api):
    """Two events that touch at one instant are both bookable for one musician.

    PRD §3.8: "Because the intervals are half-open, two back-to-back events where one ends at exactly the instant the next begins do not conflict."

    Design: Difficulty/resource_temporal_overlap/member_calendar_plain_half_open_overlap
    """
    ctx = _two_seated_members_with_three_concerts(api)
    member_id = ctx["members"][0]["id"]
    first = X.create_participation(api, ctx["events"][0]["id"], member_id)
    second = X.create_participation(api, ctx["events"][1]["id"], member_id)

    assert first["attendance_status"] == "NOT_RECORDED"
    assert second["performance_eligibility"] == "UNREVIEWED"
    assert second["tour_status"] == "NOT_APPLICABLE"

    _, total = _rows_and_total(
        api.list_event_participations, DIRECTOR_HEADERS, member_id=member_id
    )
    assert total == 2


def test_one_minute_overlap_conflicts_for_the_same_musician(api):
    """A one-minute true overlap on a musician's own calendar is refused.

    PRD §3.8: "A musician's own calendar uses plain half-open intervals with no buffer at all: the new row conflicts with an existing one when this event's `start_at` is earlier than the other event's `end_at` and the other event's `start_at` is earlier than this event's `end_at`, which is reported as `ERR_MEMBER_EVENT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/member_calendar_plain_half_open_overlap
    """
    ctx = _two_seated_members_with_three_concerts(api)
    member_id = ctx["members"][0]["id"]
    X.create_participation(api, ctx["events"][0]["id"], member_id)

    validate_error(
        api.create_event_participation(
            F.participation_payload(ctx["events"][2]["id"], member_id), REGISTRAR_HEADERS
        ),
        ApiErrorId.ERR_MEMBER_EVENT_CONFLICT.value,
    )
    assert X.read_event(api, ctx["events"][2]["id"])["participation_count"] == 0
    assert X.read_event(api, ctx["events"][0]["id"])["participation_count"] == 1


def test_overlapping_interval_is_admitted_for_a_second_musician(api):
    """The refused interval is bookable for a musician whose calendar is free.

    PRD §3.8: "A musician's own calendar uses plain half-open intervals with no buffer at all: the new row conflicts with an existing one when this event's `start_at` is earlier than the other event's `end_at` and the other event's `start_at` is earlier than this event's `end_at`, which is reported as `ERR_MEMBER_EVENT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/member_calendar_plain_half_open_overlap
    """
    ctx = _two_seated_members_with_three_concerts(api)
    X.create_participation(api, ctx["events"][0]["id"], ctx["members"][0]["id"])

    row = X.create_participation(api, ctx["events"][2]["id"], ctx["members"][1]["id"])
    assert row["member_id"] == ctx["members"][1]["id"]
    assert X.read_event(api, ctx["events"][2]["id"])["participation_count"] == 1


# --------------------------------------------------------------------------
# The aid pool is conserved at every observable moment
# --------------------------------------------------------------------------

def test_aid_pool_conserved_after_the_award_run(api):
    """The award run moves the granted money out of available and into committed.

    PRD §2.11: "A season authorizes `aid_budget_cents`; at every observable moment thereafter, `aid_committed_cents` plus `aid_available_cents` equals `aid_budget_cents` exactly."

    Design: Difficulty/compensating_invariant/aid_pool_committed_plus_available_equals_budget
    """
    ctx = _aid_under_review(api)
    _run_aid_award(api, ctx["season"]["id"])

    account = X.read_account(api, ctx["account"]["id"])
    assert account["aid_status"] == "APPROVED"
    assert account["aid_awarded_cents"] == 30000
    assert account["aid_effective_cents"] == 30000
    assert account["balance_cents"] == 93223
    assert account["billing_status"] == "CURRENT"
    A.assert_balance_identity(account)

    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_budget_cents"] == 100000
    assert season["aid_committed_cents"] == 30000
    assert season["aid_available_cents"] == 70000
    A.assert_aid_pool_conserved(season)


def test_aid_pool_conserved_after_the_income_band_cap_returns_the_surplus(api):
    """The income-band cap returns the surplus, keeping the two halves in step.

    PRD §3.7: "`aid_effective_cents` becomes the lesser of `aid_awarded_cents` and that cap, and the surplus — the awarded amount minus the effective amount — is returned to the season pool: `aid_committed_cents` decreases by the surplus and `aid_available_cents` increases by the same surplus, preserving the invariant of §2.11."

    Design: Difficulty/compensating_invariant/aid_pool_committed_plus_available_equals_budget
    """
    ctx = _aid_under_review(api)
    _run_aid_award(api, ctx["season"]["id"])
    finalized = validate_success(
        api.finalize_assessment(ctx["account"]["id"], {}, FINANCE_HEADERS_2)
    )

    assert finalized["assessment_variant"] == "FINAL"
    assert finalized["sibling_discount_cents"] == 12322
    assert finalized["loyalty_credit_cents"] == 1848
    assert finalized["assessed_cents"] == 109053
    assert finalized["aid_awarded_cents"] == 30000
    assert finalized["aid_effective_cents"] == 27263
    assert finalized["balance_cents"] == 81790
    assert finalized["billing_status"] == "CURRENT"
    A.assert_balance_identity(finalized)

    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_committed_cents"] == 27263
    assert season["aid_available_cents"] == 72737
    A.assert_aid_pool_conserved(season)


def test_aid_pool_conserved_after_the_rescission_returns_the_capped_award(api):
    """A rescission returns exactly the capped amount that was committed.

    PRD §3.7: "First, `aid_awarded_cents` and `aid_effective_cents` are both set to 0; the season's `aid_committed_cents` decreases by the account's `aid_effective_cents` *as it stood immediately before the rescission* — that is, the amount actually committed to this account, which is the capped figure once the final assessment has run — and `aid_available_cents` increases by the same amount; and `balance_cents` is recomputed upward."

    Design: Difficulty/compensating_invariant/aid_pool_committed_plus_available_equals_budget
    """
    ctx = _aid_under_review(api)
    _run_aid_award(api, ctx["season"]["id"])
    validate_success(api.finalize_assessment(ctx["account"]["id"], {}, FINANCE_HEADERS_2))
    rescinded = validate_success(
        api.rescind_aid(ctx["account"]["id"], {}, FINANCE_HEADERS_2)
    )

    assert rescinded["aid_status"] == "RESCINDED"
    assert rescinded["aid_awarded_cents"] == 0
    assert rescinded["aid_effective_cents"] == 0
    assert rescinded["balance_cents"] == 109053
    A.assert_balance_identity(rescinded)

    season = X.read_season(api, ctx["season"]["id"])
    assert season["aid_budget_cents"] == 100000
    assert season["aid_committed_cents"] == 0
    assert season["aid_available_cents"] == 100000
    A.assert_aid_pool_conserved(season)


# --------------------------------------------------------------------------
# A chair rotation conserves the section's chair multiset
# --------------------------------------------------------------------------

def test_rotation_conserves_fill_count_and_chair_numbers(api):
    """A rotation permutes the chairs without moving any derived fill figure.

    PRD §3.6: "The section's `rotation_cycle_index` increments by one, and because exactly one `ACTIVE` successor replaces each `ACTIVE` predecessor, both `filled_count` and the set of chair numbers are conserved — `balance_state` cannot move as a result of a rotation."

    Design: Difficulty/compensating_invariant/chair_rotation_conserves_chair_multiset
    """
    ctx = _rotating_section_two_chairs(api)
    quota_id = ctx["quotas"][0]["id"]
    X.rotate_chairs(api, quota_id, ctx["ensembles"][0]["id"])

    quota = X.read_section_quota(api, quota_id)
    assert quota["filled_count"] == 2
    assert quota["balance_state"] == "FULL"
    assert quota["rotation_cycle_index"] == 1

    active = _active_seats_of_section(api, quota_id)
    assert len(active) == 2
    assert sorted(seat["chair_number"] for seat in active) == [1, 2]
    assert sum(seat["chair_number"] for seat in active) == 3
    A.assert_contiguous_chair_numbers(active)

    ensemble = X.read_ensemble(api, ctx["ensembles"][0]["id"])
    assert ensemble["roster_state"] == "SEATED"
    assert ensemble["seated_count"] == 2
    assert X.read_season(api, ctx["season"]["id"])["status"] == "IN_SEASON"


def test_rotation_creates_successors_that_step_the_chair_cycle(api):
    """Each successor copies its predecessor and takes the next chair in the cycle.

    PRD §3.6: "Writing the section's `filled_count` as its size, every `ACTIVE` chair moves to `ROTATED_OUT` and a successor chair is created in `ACTIVE` status that copies the predecessor's `placement_id`, `section_quota_id`, `member_id` and `ranking_score`, sets `predecessor_assignment_id` to the predecessor row's `id`, sets `rotation_cycle_index` to one more than the predecessor's, and takes a `chair_number` equal to the section size when the predecessor sat in chair 1 and equal to the predecessor's `chair_number` minus one otherwise."

    Design: Difficulty/compensating_invariant/chair_rotation_conserves_chair_multiset
    """
    ctx = _rotating_section_two_chairs(api)
    quota_id = ctx["quotas"][0]["id"]
    principal_seat, second_seat = ctx["seats"]
    assert principal_seat["chair_number"] == 1
    assert second_seat["chair_number"] == 2

    X.rotate_chairs(api, quota_id, ctx["ensembles"][0]["id"])

    assert X.read_seat(api, principal_seat["id"])["status"] == "ROTATED_OUT"
    assert X.read_seat(api, principal_seat["id"])["chair_number"] == 1
    assert X.read_seat(api, second_seat["id"])["status"] == "ROTATED_OUT"
    assert X.read_seat(api, second_seat["id"])["chair_number"] == 2

    successors = {
        seat["member_id"]: seat for seat in _active_seats_of_section(api, quota_id)
    }
    stepped_up = successors[ctx["members"][1]["id"]]
    stepped_back = successors[ctx["members"][0]["id"]]

    assert stepped_up["chair_number"] == 1
    assert stepped_up["predecessor_assignment_id"] == second_seat["id"]
    assert stepped_up["rotation_cycle_index"] == 1
    assert stepped_up["placement_id"] == second_seat["placement_id"]
    assert stepped_up["ranking_score"] == 80.00

    assert stepped_back["chair_number"] == 2
    assert stepped_back["predecessor_assignment_id"] == principal_seat["id"]
    assert stepped_back["rotation_cycle_index"] == 1
    assert stepped_back["ranking_score"] == 92.00

    _, total = _rows_and_total(
        api.list_seat_assignments, DIRECTOR_HEADERS, section_quota_id=quota_id
    )
    assert total == 4


def test_rotation_moves_the_single_principal_designation(api):
    """Exactly one active chair stays principal, and it is the new chair one.

    PRD §3.6: "`is_principal` is recomputed on each successor from its new `chair_number` and the section's `principal_required`."

    Design: Difficulty/compensating_invariant/chair_rotation_conserves_chair_multiset
    """
    ctx = _rotating_section_two_chairs(api)
    quota_id = ctx["quotas"][0]["id"]
    assert ctx["seats"][0]["is_principal"] is True
    assert ctx["seats"][1]["is_principal"] is False

    X.rotate_chairs(api, quota_id, ctx["ensembles"][0]["id"])

    active = _active_seats_of_section(api, quota_id)
    principals = [seat for seat in active if seat["is_principal"]]
    assert len(principals) == 1
    assert principals[0]["chair_number"] == 1
    assert principals[0]["member_id"] == ctx["members"][1]["id"]


# --------------------------------------------------------------------------
# The seat ledger reconciles chairs, placements and fill counts
# --------------------------------------------------------------------------

def test_acceptance_adds_one_active_chair_and_one_fill(api):
    """The second acceptance adds exactly one chair and one unit of fill.

    PRD §3.5: "A **SeatAssignment** is then created in `ACTIVE` status, carrying the `placement_id` that produced it, the `section_quota_id` of the matching section, the seat holder's `member_id`, a `predecessor_assignment_id` of null because it opens a fresh rotation chain, a `rotation_cycle_index` copied from the section's current `rotation_cycle_index`, and a `ranking_score` snapshotted from the audition's `composite_final_score`; the section's chair order is then recomputed per §3.6 and `filled_count` increments by one."

    Design: Difficulty/compensating_invariant/seat_ledger_identity_across_offer_accept_vacate
    """
    ctx = _seat_ledger_stage(api)
    quota_id = ctx["quotas"][0]["id"]
    assert X.read_section_quota(api, quota_id)["filled_count"] == 1
    assert len(_active_seats_of_section(api, quota_id)) == 1

    X.accept_placement(api, ctx["placements"][1]["id"], ctx["members"][1]["id"])

    quota = X.read_section_quota(api, quota_id)
    assert quota["filled_count"] == 2
    assert quota["balance_state"] == "FULL"

    active = _active_seats_of_section(api, quota_id)
    assert len(active) == 2
    A.assert_contiguous_chair_numbers(active)
    new_seat = X.sole_active_seat(api, ctx["members"][1]["id"])
    assert new_seat["placement_id"] == ctx["placements"][1]["id"]
    assert new_seat["predecessor_assignment_id"] is None
    assert new_seat["rotation_cycle_index"] == 0
    assert new_seat["ranking_score"] == 80.00

    _, accepted_total = _rows_and_total(
        api.list_placements,
        DIRECTOR_HEADERS,
        ensemble_id=ctx["ensembles"][0]["id"],
        status="ACCEPTED",
    )
    assert accepted_total == 2

    ensemble = X.read_ensemble(api, ctx["ensembles"][0]["id"])
    assert ensemble["seated_count"] == 2
    assert ensemble["roster_state"] == "SEATED"
    season = X.read_season(api, ctx["season"]["id"])
    assert season["seated_ensemble_count"] == 1
    assert season["status"] == "IN_SEASON"


def test_offered_count_tracks_the_offered_placements_of_the_ensemble(api):
    """`offered_count` equals the number of placements sitting in OFFERED.

    PRD §3.1: "An ensemble's `offered_count` tracks how many of its placements currently sit in `OFFERED`."

    Design: Difficulty/compensating_invariant/seat_ledger_identity_across_offer_accept_vacate
    """
    ctx = _seat_ledger_stage(api)
    ensemble_id = ctx["ensembles"][0]["id"]

    _, offered_total = _rows_and_total(
        api.list_placements, DIRECTOR_HEADERS, ensemble_id=ensemble_id, status="OFFERED"
    )
    assert offered_total == 1
    assert X.read_ensemble(api, ensemble_id)["offered_count"] == 1

    X.accept_placement(api, ctx["placements"][1]["id"], ctx["members"][1]["id"])

    _, offered_total = _rows_and_total(
        api.list_placements, DIRECTOR_HEADERS, ensemble_id=ensemble_id, status="OFFERED"
    )
    assert offered_total == 0
    assert X.read_ensemble(api, ensemble_id)["offered_count"] == 0


def test_vacating_a_chair_reverses_the_ledger_downward(api):
    """Vacating a chair releases its placement and walks every counter back down.

    PRD §3.5: "The chair moves `ACTIVE → VACATED` and its `version` increments; the owning placement moves `ACCEPTED → RELEASED`; the section's `filled_count` decrements by one and the chair order is recomputed over the remaining `ACTIVE` chairs so that chair numbers stay contiguous from 1; the section's `balance_state` and the ensemble's `roster_state` are re-evaluated, which may demote the section and flip the ensemble `SEATED → FORMING` with the season's `seated_ensemble_count` decremented; waitlist promotion runs on the freed section; and the ensemble's `version` increments."

    Design: Difficulty/compensating_invariant/seat_ledger_identity_across_offer_accept_vacate
    """
    ctx = _seat_ledger_stage(api)
    quota_id = ctx["quotas"][0]["id"]
    ensemble_id = ctx["ensembles"][0]["id"]
    X.accept_placement(api, ctx["placements"][1]["id"], ctx["members"][1]["id"])

    validate_success(api.vacate_seat(ctx["first_seat"]["id"], {}, DIRECTOR_HEADERS))

    assert X.read_seat(api, ctx["first_seat"]["id"])["status"] == "VACATED"
    assert X.read_placement(api, ctx["placements"][0]["id"])["status"] == "RELEASED"

    quota = X.read_section_quota(api, quota_id)
    assert quota["filled_count"] == 1
    assert quota["balance_state"] == "BALANCED"

    active = _active_seats_of_section(api, quota_id)
    assert len(active) == 1
    assert active[0]["member_id"] == ctx["members"][1]["id"]
    A.assert_contiguous_chair_numbers(active)

    _, accepted_total = _rows_and_total(
        api.list_placements, DIRECTOR_HEADERS, ensemble_id=ensemble_id, status="ACCEPTED"
    )
    assert accepted_total == 1

    ensemble = X.read_ensemble(api, ensemble_id)
    assert ensemble["seated_count"] == 1
    assert ensemble["roster_state"] == "FORMING"
    assert ensemble["offered_count"] == 0
    season = X.read_season(api, ctx["season"]["id"])
    assert season["seated_ensemble_count"] == 0
    assert season["status"] == "IN_SEASON"
