"""
Validation precedence when one competition entry violates several rules at once.

The requirements make the evaluation order part of the contract (§2.8): across the
whole API the precedence runs, from first to last, header authentication,
endpoint role authorization, path-identifier existence, body foreign-key
existence, resource ownership, request-body shape and weight-class membership,
version pinning, the disqualified-wrestler freeze (`ERR_WRESTLER_DISQUALIFIED`),
the season-open requirement (`ERR_SEASON_NOT_OPEN`), the from-state check for the
requested transition, and only then the domain-specific safety, referential,
temporal, capacity and uniqueness rules of section 3.  The specification is
explicit that the disqualified-wrestler freeze sits *ahead of* the season-open
check deliberately, so that a disqualified wrestler is frozen out of every
downstream write regardless of whether the season would otherwise have accepted
the operation.

The competition-entry endpoint (§3.7) is where that ordering is most visible: it
is the single most heavily guarded operation in the system.  These tests build one
world in which a single entry attempt breaks the freeze *and* the season-open
requirement at the same time, and check that the safety refusal is the one
reported — with a companion attempt by a teammate who is not disqualified proving
the season-open rule really is armed underneath it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_row_count,
)
from test_helpers.constants import (
    ASSESSMENT_DAY_INSTANT,
    CANON_USG_FAIL,
    EVENT_COMPLETED,
    FLAG_ESCALATED,
    FLAG_HYDRATION_FAIL,
    SEASON_CLOSED,
    SEX_MALE,
    WRESTLER_DISQUALIFIED,
)
from test_helpers.test_users import STATE_OFFICE, coach_headers

# A member of the season's default weight-class ladder, comfortably above the
# 150 pound minimum class the canonical measurement certifies into, so that the
# class-floor rules of §3.7 have nothing to say about these attempts.
ENTRY_CLASS_LBS = 165

# The event the entry attempts are aimed at.  Its `event_date` sits inside the
# season and its `competition_days` of 1 gives it a one-day competition window.
EVENT_NAME = "Northgate Invitational"
EVENT_DATE = "2026-11-10"

# The second measurement of the day: the same assessor, a hydration reading
# strictly above the season's 1.025 ceiling, which §3.3 forks onto the
# hydration-failure arm and which raises the `HYDRATION_FAIL` flag of §3.9.
DRY_ASSESSED_AT = "2026-11-01T14:00:00Z"
DRY_MEASURED_WEIGHT_LBS = 152.0

TEAMMATE_NAME = "Blake Ito"
TEAMMATE_GRADE = 12


def _hydration_flag_of(api, wrestler_id):
    """The one `HYDRATION_FAIL` flag the failed finalize raised on a wrestler.

    Cascade-raised flags are invisible to the caller that triggered them, so the
    filtered flag listing is their only discovery channel (§2.10).
    """
    flags = [
        flag
        for flag in fixtures.flags_of_wrestler(api, wrestler_id)
        if flag.get("source") == FLAG_HYDRATION_FAIL
    ]
    assert len(flags) == 1, (
        f"expected exactly one HYDRATION_FAIL flag on the wrestler, got {flags!r}"
    )
    return flags[0]


def _frozen_wrestler_on_a_closed_season(api):
    """Build the world both refusals are read from.

    A season is opened with one team, a trained assessor and a wrestler measured
    into the certified figures, so the wrestler sits at `PROVISIONAL`.  A
    scheduled event is added.  A second measurement fails hydration, which raises
    a health flag; a physician escalates it, and the state office cites the
    escalated flag to disqualify the wrestler (§3.9).  A teammate is rostered and
    left `UNCERTIFIED`.  Finally the season is closed, which by §3.1 sweeps the
    scheduled event forward to `COMPLETED`.

    The world therefore breaks three separate guards for one entry attempt at
    once: the wrestler is disqualified, the season is not open, and the event has
    reached a terminal status.
    """
    scenario = fixtures.assessed_wrestler(api)

    teammate = fixtures.create_wrestler(
        api, scenario.team_id, TEAMMATE_NAME, SEX_MALE, TEAMMATE_GRADE
    )
    event = fixtures.create_event(
        api,
        scenario.season_id,
        EVENT_NAME,
        EVENT_DATE,
        competition_days=1,
        weigh_in_days=1,
    )

    dehydrated = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=DRY_ASSESSED_AT,
        measured_weight_lbs=DRY_MEASURED_WEIGHT_LBS,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, dehydrated["id"], scenario.assessor_id)

    flag = _hydration_flag_of(api, scenario.wrestler_id)
    fixtures.review_flag(
        api,
        flag["id"],
        FLAG_ESCALATED,
        "Repeat hydration failure; refer to the state office.",
    )
    fixtures.disqualify_wrestler(
        api,
        scenario.wrestler_id,
        flag["id"],
        reason="Unhealthy weight management.",
    )

    fixtures.close_season(api, scenario.season_id)

    scenario.update(
        event=event,
        event_id=event["id"],
        teammate=teammate,
        teammate_id=teammate["id"],
        flag_id=flag["id"],
    )
    return scenario


def _attempt_entry(api, scenario, wrestler_id):
    """Attempt a competition entry as the owning coach, without reading success."""
    return api.create_entry(
        scenario.event_id,
        factories.entry_payload(wrestler_id, ENTRY_CLASS_LBS),
        coach_headers(scenario.team_id),
    )


def test_disqualified_freeze_outranks_the_season_open_requirement(api):
    """A frozen wrestler's entry is refused for the freeze, not the closed season.

    The entry names a disqualified wrestler on a season that has been closed, so
    the freeze of §2.8 and the season-open requirement of §3.1 are both broken by
    the one request.  §2.8 places the disqualified-wrestler freeze ahead of the
    season-open check and says so explicitly, so `ERR_WRESTLER_DISQUALIFIED` is
    the refusal that must be reported.

    Design: Difficulty/priority_pair_validation_conflict/disqualified_beats_season_not_open
    """
    scenario = _frozen_wrestler_on_a_closed_season(api)

    response = _attempt_entry(api, scenario, scenario.wrestler_id)

    validate_error(response, api_errors.ERR_WRESTLER_DISQUALIFIED, 409)


def test_closed_season_still_refuses_the_teammate_who_is_not_frozen(api):
    """The season-open rule is armed, and outranks the not-certified refusal.

    The same closed season and the same event, but the entry names a teammate who
    was never disqualified.  With the freeze inapplicable the next check in the
    §2.8 order applies, so `ERR_SEASON_NOT_OPEN` is reported — which also proves
    it outranks the `ERR_WRESTLER_NOT_CERTIFIED` refusal of §3.7 that this
    `UNCERTIFIED` teammate would otherwise trip, that being one of the
    domain-specific safety rules evaluated last.

    Design: Difficulty/priority_pair_validation_conflict/disqualified_beats_season_not_open
    """
    scenario = _frozen_wrestler_on_a_closed_season(api)

    response = _attempt_entry(api, scenario, scenario.teammate_id)

    validate_error(response, api_errors.ERR_SEASON_NOT_OPEN, 409)


def test_both_competing_guards_really_are_in_force(api):
    """The world under test genuinely breaks both rules at once.

    Per §3.9 a successful disqualification sets `certification_status` to
    `DISQUALIFIED` and stamps `disqualified_at` from the logical clock, which has
    been left where the measurement day put it.  Per §3.1 closing a season sweeps
    every event of that season whose status is `SCHEDULED` or `WEIGH_IN_CLOSED`
    forward to `COMPLETED`.

    Design: Difficulty/priority_pair_validation_conflict/disqualified_beats_season_not_open
    """
    scenario = _frozen_wrestler_on_a_closed_season(api)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_DISQUALIFIED, (
        "the cited escalated flag must have driven the wrestler to DISQUALIFIED, "
        f"got {wrestler['certification_status']!r}"
    )
    assert_instant_equals(
        wrestler["disqualified_at"], ASSESSMENT_DAY_INSTANT, "disqualified_at"
    )

    season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["status"] == SEASON_CLOSED, (
        f"the season must be CLOSED, got {season['status']!r}"
    )

    event = fixtures.read_event(api, scenario.event_id)
    assert event["status"] == EVENT_COMPLETED, (
        "closing the season sweeps a SCHEDULED event to COMPLETED, got "
        f"{event['status']!r}"
    )


def test_neither_refused_entry_creates_an_entry_row(api):
    """A refused entry attempt leaves no row and no counter movement behind.

    Only a successful entry lands in `ENTERED` and increments the event's
    `entry_count` (§3.7), so after both refusals the event still reports zero
    entries and the filtered entry listing of that event is empty.

    Design: Difficulty/priority_pair_validation_conflict/disqualified_beats_season_not_open
    """
    scenario = _frozen_wrestler_on_a_closed_season(api)

    validate_error(
        _attempt_entry(api, scenario, scenario.wrestler_id),
        api_errors.ERR_WRESTLER_DISQUALIFIED,
        409,
    )
    validate_error(
        _attempt_entry(api, scenario, scenario.teammate_id),
        api_errors.ERR_SEASON_NOT_OPEN,
        409,
    )

    event = fixtures.read_event(api, scenario.event_id)
    assert event["entry_count"] == 0, (
        f"no entry was accepted, so entry_count must be 0, got {event['entry_count']!r}"
    )

    assert_row_count(
        api.list_entries(STATE_OFFICE, {"event_id": scenario.event_id}),
        0,
        "entries of the event",
    )
