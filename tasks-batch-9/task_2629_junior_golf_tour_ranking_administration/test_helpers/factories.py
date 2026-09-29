"""Request-payload builders for every write endpoint.

Each builder returns a complete, valid payload for the documented required fields
and accepts keyword overrides. Passing `None` for an override removes the field,
which is how the tests exercise missing-field validation.
"""

from .constants import (
    COURSE_RATING,
    SEASON_AGE_CUTOFF_DATE,
    SEASON_ASSISTANCE_BUDGET_CENTS,
    SEASON_END_DATE,
    SEASON_NAME,
    SEASON_RANKING_WINDOW_START_DATE,
    SEASON_START_DATE,
    SLOPE_RATING,
    STANDARD_ENTRY_FEE_CENTS,
)
from .types import (
    DIVISION_U17,
    HANDICAP_SOURCE_WHS_CLUB,
    INCIDENT_COACHING_VIOLATION,
    SCOPE_RESULTS_ONLY,
    SUBJECT_PARENT,
    TIER_REGIONAL,
)

_SENTINEL = object()


def _merge(base, overrides):
    """Apply overrides; a None value deletes the key so the field goes unsent."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------- season
def season_payload(**overrides):
    return _merge(
        {
            "name": SEASON_NAME,
            "start_date": SEASON_START_DATE,
            "end_date": SEASON_END_DATE,
            "age_cutoff_date": SEASON_AGE_CUTOFF_DATE,
            "ranking_window_start_date": SEASON_RANKING_WINDOW_START_DATE,
            "assistance_budget_cents": SEASON_ASSISTANCE_BUDGET_CENTS,
        },
        overrides,
    )


# --------------------------------------------------------------------- member
def member_payload(season_id, **overrides):
    """Ava Stone: born 2010-05-04, so U17 against the 2026-08-31 cutoff."""
    return _merge(
        {
            "season_id": season_id,
            "full_name": "Ava Stone",
            "birth_date": "2010-05-04",
            "state_code": "NC",
            "guardian_email": "ava.guardian@example.com",
            "handicap_index": 3.2,
            "handicap_effective_date": "2026-07-15",
            "handicap_source": HANDICAP_SOURCE_WHS_CLUB,
            "publication_opt_in": True,
        },
        overrides,
    )


def second_member_payload(season_id, **overrides):
    """Ben Cole: born 2010-06-15, U17, and has not consented to publication."""
    return _merge(
        {
            "season_id": season_id,
            "full_name": "Ben Cole",
            "birth_date": "2010-06-15",
            "state_code": "SC",
            "guardian_email": "ben.guardian@example.com",
            "handicap_index": 5.1,
            "handicap_effective_date": "2026-07-20",
            "handicap_source": HANDICAP_SOURCE_WHS_CLUB,
            "publication_opt_in": False,
        },
        overrides,
    )


def third_member_payload(season_id, **overrides):
    """Cara Diaz: born 2010-03-02, U17."""
    return _merge(
        {
            "season_id": season_id,
            "full_name": "Cara Diaz",
            "birth_date": "2010-03-02",
            "state_code": "GA",
            "guardian_email": "cara.guardian@example.com",
            "handicap_index": 6.4,
            "handicap_effective_date": "2026-07-22",
            "handicap_source": HANDICAP_SOURCE_WHS_CLUB,
            "publication_opt_in": False,
        },
        overrides,
    )


def fourth_member_payload(season_id, **overrides):
    """Dana Reid: born 2010-04-11, U17, carrying a high handicap index."""
    return _merge(
        {
            "season_id": season_id,
            "full_name": "Dana Reid",
            "birth_date": "2010-04-11",
            "state_code": "VA",
            "guardian_email": "dana.guardian@example.com",
            "handicap_index": 12.5,
            "handicap_effective_date": "2026-07-15",
            "handicap_source": HANDICAP_SOURCE_WHS_CLUB,
            "publication_opt_in": False,
        },
        overrides,
    )


def eligibility_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def handicap_revision_payload(expected_member_version, **overrides):
    return _merge(
        {
            "expected_member_version": expected_member_version,
            "handicap_index": 3.5,
            "handicap_effective_date": "2026-08-09",
            "handicap_source": HANDICAP_SOURCE_WHS_CLUB,
        },
        overrides,
    )


# ----------------------------------------------------------------- tournament
def tournament_payload(season_id, **overrides):
    """The Carolina Regional: a two-round U17 REGIONAL event with a field cap of 2."""
    return _merge(
        {
            "season_id": season_id,
            "name": "Carolina Regional",
            "division": DIVISION_U17,
            "tier": TIER_REGIONAL,
            "start_date": "2026-09-10",
            "end_date": "2026-09-11",
            "entry_open_at": "2026-08-05T00:00:00Z",
            "entry_close_at": "2026-09-01T00:00:00Z",
            "withdrawal_deadline_at": "2026-09-05T00:00:00Z",
            "field_size_limit": 2,
            "max_handicap_index": 8.4,
            "entry_fee_cents": STANDARD_ENTRY_FEE_CENTS,
            "round_count": 2,
            "course_rating": COURSE_RATING,
            "slope_rating": SLOPE_RATING,
        },
        overrides,
    )


def october_tournament_payload(season_id, **overrides):
    """A second event a month later, so a junior can hold two entries at once."""
    return _merge(
        tournament_payload(
            season_id,
            name="Piedmont Regional",
            start_date="2026-10-15",
            end_date="2026-10-16",
            entry_close_at="2026-10-01T00:00:00Z",
            withdrawal_deadline_at="2026-10-10T00:00:00Z",
        ),
        overrides,
    )


# ------------------------------------------------------------ exemption grant
def exemption_grant_payload(member_id, tournament_id, category, expires_at, **overrides):
    return _merge(
        {
            "member_id": member_id,
            "tournament_id": tournament_id,
            "category": category,
            "expires_at": expires_at,
        },
        overrides,
    )


# ----------------------------------------------------------------------- entry
def entry_payload(member_id, tournament_id, **overrides):
    return _merge({"member_id": member_id, "tournament_id": tournament_id}, overrides)


def payment_payload(amount_cents, **overrides):
    return _merge({"amount_cents": amount_cents}, overrides)


def withdrawal_payload(reason="family travel cancelled", **overrides):
    return _merge({"reason": reason}, overrides)


# ------------------------------------------------------------ aid application
def aid_application_payload(
    member_id, season_id, expected_member_version, household_income_cents=1000000,
    dependents=1, **overrides
):
    return _merge(
        {
            "member_id": member_id,
            "season_id": season_id,
            "household_income_cents": household_income_cents,
            "dependents": dependents,
            "expected_member_version": expected_member_version,
        },
        overrides,
    )


def aid_decision_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


# ----------------------------------------------------------------------- round
def round_payload(entry_id, round_number, tee_time, marker_member_id, **overrides):
    return _merge(
        {
            "entry_id": entry_id,
            "round_number": round_number,
            "tee_time": tee_time,
            "marker_member_id": marker_member_id,
        },
        overrides,
    )


def pace_observation_payload(observation_type, minutes_behind, **overrides):
    return _merge(
        {"observation_type": observation_type, "minutes_behind": minutes_behind},
        overrides,
    )


def score_payload(gross_strokes, **overrides):
    return _merge({"gross_strokes": gross_strokes}, overrides)


def peer_verify_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


# ------------------------------------------------------------------ rules case
def rules_case_payload(round_id, proposed_disposition, penalty_strokes_proposed,
                       rule_reference="Rule 10.2 - advice from the gallery", **overrides):
    return _merge(
        {
            "round_id": round_id,
            "rule_reference": rule_reference,
            "proposed_disposition": proposed_disposition,
            "penalty_strokes_proposed": penalty_strokes_proposed,
        },
        overrides,
    )


def adjudication_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def appeal_payload(grounds="the marker misread the lie", **overrides):
    return _merge({"grounds": grounds}, overrides)


# ---------------------------------------------------------------- conduct case
def conduct_case_payload(member_id, tournament_id, incident_code=INCIDENT_COACHING_VIOLATION,
                         **overrides):
    return _merge(
        {
            "member_id": member_id,
            "tournament_id": tournament_id,
            "incident_code": incident_code,
            "subject_type": SUBJECT_PARENT,
            "subject_name": "Peter Stone",
            "narrative": "advice shouted from the gallery on the 4th tee",
        },
        overrides,
    )


def conduct_decision_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------- coach access grant
def coach_access_payload(member_id, expected_member_version,
                         scope=SCOPE_RESULTS_ONLY, coach_school="State University",
                         **overrides):
    return _merge(
        {
            "member_id": member_id,
            "coach_school": coach_school,
            "scope": scope,
            "expected_member_version": expected_member_version,
        },
        overrides,
    )


def coach_decision_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def revocation_payload(reason="no longer recruiting", **overrides):
    return _merge({"reason": reason}, overrides)


def ranking_run_payload(as_of_date=None, **overrides):
    base = {} if as_of_date is None else {"as_of_date": as_of_date}
    return _merge(base, overrides)
