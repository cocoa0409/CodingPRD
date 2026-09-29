"""Rejection-path compliance tests: every error identifier triggered on its own.

The harness restarts the server and empties the database before every test, so
each test builds all of its own state through the PRD's public endpoints.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import shift_instant
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    FINANCE_HEADERS,
    NO_HEADERS,
    REGISTRAR_HEADERS,
    guardian_headers,
    panelist_headers,
)


# --------------------------------------------------------------------------
# Local composition helpers (nothing here belongs in the shared package)
# --------------------------------------------------------------------------

def _panel_environment(
    api,
    panelist_count: int = 3,
    conflicted: bool = False,
    slot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A season in `AUDITIONS_OPEN` with one CELLO slot holding one `SCHEDULED` audition."""
    ctx = X.open_season_with_ensemble(api)
    season_id = ctx["season"]["id"]
    member = X.create_member(api)
    panelists: List[Dict[str, Any]] = [
        X.create_panelist(api, display_name=f"Adjudicator {index + 1}")
        for index in range(panelist_count)
    ]
    if conflicted:
        panelists.append(
            X.create_panelist(
                api,
                display_name="Conflicted Carla",
                conflict_member_ids=[member["id"]],
            )
        )
    slot = X.create_audition_slot(
        api, season_id, [p["id"] for p in panelists], **(slot_overrides or {})
    )
    audition = X.create_audition(api, member["id"], season_id)
    X.schedule_audition(api, audition["id"], slot["id"])
    ctx.update(
        {"member": member, "panelists": panelists, "slot": slot, "audition": audition}
    )
    return ctx


def _submit_sheet_response(api, audition_id: str, panelist_id: str):
    """Post one rubric sheet as the acting adjudicator, returning the raw response."""
    return api.submit_panel_score(
        audition_id,
        F.panel_score_payload(panelist_id),
        panelist_headers(panelist_id),
    )


def _request_revision_response(api, audition_id: str):
    return api.request_revision(audition_id, {}, DIRECTOR_HEADERS)


def _placement_response(api, audition_id: str, ensemble_id: str, **overrides: Any):
    """Post a placement carrying the ensemble's live concurrency token."""
    payload = F.placement_payload(
        audition_id,
        ensemble_id,
        X.ensemble_version(api, ensemble_id),
        **overrides,
    )
    return api.create_placement(payload, DIRECTOR_HEADERS)


# --------------------------------------------------------------------------
# Protocol band: headers, authorization, ownership, pagination
# --------------------------------------------------------------------------

def test_missing_role_header_is_rejected(api):
    """A request that carries neither auth header is rejected before anything else.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those five strings, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (401)."

    Design: Corner/errors/auth_envelope_and_pagination_errors_are_each_triggerable
    """
    response = api.list_seasons(NO_HEADERS)
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)


def test_panelist_may_not_list_musicians(api):
    """A real role acting outside the endpoint's authorized list is refused.

    PRD §2.1: "If the headers are well formed but the acting role is not among the roles authorized for the endpoint in §4, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/errors/auth_envelope_and_pagination_errors_are_each_triggerable
    """
    panelist = X.create_panelist(api)
    response = api.list_members(panelist_headers(panelist["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_guardian_may_not_register_another_musicians_audition(api):
    """A Guardian registering an audition for someone else's musician is refused.

    PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting musician: ownership checks compare `X-User-ID` against the `member_id` reached from the target resource — an audition's `member_id`, a placement's `member_id`, a tuition account's `member_id`, or a participation row's `member_id` — and, when registering an audition, against the `member_id` supplied in the request body."

    Design: Corner/errors/auth_envelope_and_pagination_errors_are_each_triggerable
    """
    X.set_clock(api)
    season = X.create_season(api)
    ada = X.create_member(api, legal_name="Ada Strings")
    ben = X.create_member(api, legal_name="Ben Bow")
    response = api.create_audition(
        F.audition_payload(ada["id"], season["id"]), guardian_headers(ben["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_limit_above_one_hundred_is_rejected(api):
    """A list read asking for more than one hundred rows is refused.

    PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/errors/auth_envelope_and_pagination_errors_are_each_triggerable
    """
    response = api.list_members(REGISTRAR_HEADERS, params={"limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value)


# --------------------------------------------------------------------------
# Existence band: one not-found identifier per resource family
# --------------------------------------------------------------------------

def test_unknown_section_quota_reports_its_own_not_found(api):
    """Reading an unknown section quota reports the section-quota family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_section_quota(NON_EXISTENT_UUID, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SECTION_QUOTA_NOT_FOUND.value)


def test_unknown_panelist_reports_its_own_not_found(api):
    """Reading an unknown adjudicator reports the panelist family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_panelist(NON_EXISTENT_UUID, REGISTRAR_HEADERS)
    validate_error(response, ApiErrorId.ERR_PANELIST_NOT_FOUND.value)


def test_unknown_audition_slot_reports_its_own_not_found(api):
    """Reading an unknown audition slot reports the slot family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_audition_slot(NON_EXISTENT_UUID, REGISTRAR_HEADERS)
    validate_error(response, ApiErrorId.ERR_AUDITION_SLOT_NOT_FOUND.value)


def test_unknown_audition_reports_its_own_not_found(api):
    """Adjudicating an unknown audition reports the audition family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.adjudicate_audition(NON_EXISTENT_UUID, {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_AUDITION_NOT_FOUND.value)


def test_unknown_panel_score_reports_its_own_not_found(api):
    """Reading an unknown rubric sheet reports the panel-score family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_panel_score(NON_EXISTENT_UUID, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_PANEL_SCORE_NOT_FOUND.value)


def test_unknown_seat_assignment_reports_its_own_not_found(api):
    """Vacating an unknown chair reports the seat-assignment family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.vacate_seat(NON_EXISTENT_UUID, {}, DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SEAT_ASSIGNMENT_NOT_FOUND.value)


def test_unknown_tuition_account_reports_its_own_not_found(api):
    """Reading an unknown tuition account reports the account family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_tuition_account(NON_EXISTENT_UUID, FINANCE_HEADERS)
    validate_error(response, ApiErrorId.ERR_TUITION_ACCOUNT_NOT_FOUND.value)


def test_unknown_participation_reports_its_own_not_found(api):
    """Reading an unknown participation row reports the participation family code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_remaining_resource_family_reports_its_own_not_found_error
    """
    response = api.get_event_participation(NON_EXISTENT_UUID, REGISTRAR_HEADERS)
    validate_error(response, ApiErrorId.ERR_PARTICIPATION_NOT_FOUND.value)


# --------------------------------------------------------------------------
# Season phase gates
# --------------------------------------------------------------------------

def test_skipping_a_season_rung_is_refused(api):
    """Advancing a `PLANNING` season straight to `PLACEMENT` skips a declared rung.

    PRD §3.1: "The director advances it one rung at a time by supplying a `to_status`; any `to_status` that is not the declared immediate successor of the current value — a skip ahead or any reversal — is refused with `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/errors/season_gate_errors_separate_wrong_hop_from_unmet_precondition
    """
    X.set_clock(api)
    season = X.create_season(api)
    response = api.advance_season_status(
        season["id"], F.advance_status_payload("PLACEMENT"), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value)


def test_auditions_open_needs_every_ensemble_to_own_a_section(api):
    """The right hop is refused while the season's only ensemble owns no section.

    PRD §3.1: "Each rung also has its own admission criteria, reported as `ERR_SEASON_PRECONDITION_UNMET`: reaching `AUDITIONS_OPEN` requires `ensemble_count` of at least 1 and requires every ensemble of the season to own at least one instrumentation section; reaching `PLACEMENT` requires that no audition of the season sits in `SCORED` or `REVISION_REQUESTED` (auditions still in `REQUESTED` or `SCHEDULED` may remain — they simply can no longer be scored, because slot booking closes with the audition phase); and reaching `IN_SEASON` requires `seated_ensemble_count` to equal `ensemble_count`."

    Design: Corner/errors/season_gate_errors_separate_wrong_hop_from_unmet_precondition
    """
    X.set_clock(api)
    season = X.create_season(api)
    X.create_ensemble(api, season["id"])
    response = api.advance_season_status(
        season["id"], F.advance_status_payload("AUDITIONS_OPEN"), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_SEASON_PRECONDITION_UNMET.value)


def test_slot_cannot_be_opened_before_auditions_open(api):
    """Opening an audition slot while the season is still in `PLANNING` is refused.

    PRD §3.3: "`RegistrarStaff` opens each **AuditionSlot** while the season is in `AUDITIONS_OPEN`; attempting it in any other phase is refused with `ERR_SEASON_NOT_ACCEPTING_AUDITIONS`."

    Design: Corner/errors/season_gate_errors_separate_wrong_hop_from_unmet_precondition
    """
    X.set_clock(api)
    season = X.create_season(api)
    panelists = X.create_panelists(api, count=3)
    response = api.create_audition_slot(
        F.audition_slot_payload(season["id"], [p["id"] for p in panelists]),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_ACCEPTING_AUDITIONS.value)


# --------------------------------------------------------------------------
# Blind-panel integrity and slot capacity
# --------------------------------------------------------------------------

def test_booking_a_full_slot_is_refused(api):
    """A second audition booked into a slot already at capacity is refused.

    PRD §3.4: "Finally the slot must still be `OPEN`, meaning its `booked_count` is below its `capacity`; a full slot is `ERR_AUDITION_SLOT_FULL`."

    Design: Corner/errors/panel_integrity_and_slot_capacity_errors_are_each_triggerable
    """
    ctx = _panel_environment(api, slot_overrides={"capacity": 1})
    second_member = X.create_member(api, legal_name="Ben Bow")
    second_audition = X.create_audition(
        api, second_member["id"], ctx["season"]["id"]
    )
    response = api.schedule_audition(
        second_audition["id"], F.schedule_payload(ctx["slot"]["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_AUDITION_SLOT_FULL.value)


def test_adjudicator_may_not_score_a_private_student(api):
    """An adjudicator whose conflict list names the musician may not submit a sheet.

    PRD §3.4: "The submitting adjudicator's `conflict_member_ids` must not contain the audition's `member_id` — scoring a private student is a blind-panel integrity violation reported as `ERR_PANEL_CONFLICT_OF_INTEREST`, and it outranks the duplicate check below."

    Design: Corner/errors/panel_integrity_and_slot_capacity_errors_are_each_triggerable
    """
    ctx = _panel_environment(api, conflicted=True)
    conflicted = ctx["panelists"][-1]
    response = _submit_sheet_response(api, ctx["audition"]["id"], conflicted["id"])
    validate_error(response, ApiErrorId.ERR_PANEL_CONFLICT_OF_INTEREST.value)


def test_adjudicator_absent_from_the_panel_may_not_score(api):
    """An adjudicator who is not on the slot's panel may not submit a sheet.

    PRD §3.4: "The `panelist_id` must appear in the `panelist_ids` of the slot the audition currently occupies, and that adjudicator's `instrument_expertise` must equal the slot's `instrument_focus`; otherwise `ERR_PANELIST_NOT_ON_PANEL`."

    Design: Corner/errors/panel_integrity_and_slot_capacity_errors_are_each_triggerable
    """
    ctx = _panel_environment(api)
    outsider = X.create_panelist(api, display_name="Outside Otto")
    response = _submit_sheet_response(api, ctx["audition"]["id"], outsider["id"])
    validate_error(response, ApiErrorId.ERR_PANELIST_NOT_ON_PANEL.value)


def test_second_sheet_for_the_same_round_is_refused(api):
    """A second sheet from one adjudicator in the same round is refused.

    PRD §3.4: "And only one sheet may exist per combination of `audition_id`, `panelist_id` and `revision_round`, a second being `ERR_DUPLICATE_PANEL_SCORE`."

    Design: Corner/errors/panel_integrity_and_slot_capacity_errors_are_each_triggerable
    """
    ctx = _panel_environment(api)
    panelist = ctx["panelists"][0]
    validate_success(
        _submit_sheet_response(api, ctx["audition"]["id"], panelist["id"]), 201
    )
    response = _submit_sheet_response(api, ctx["audition"]["id"], panelist["id"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PANEL_SCORE.value)


# --------------------------------------------------------------------------
# Re-audition round cap
# --------------------------------------------------------------------------

def test_third_revision_request_is_refused(api):
    """A third revision request on the same audition is refused after two rounds.

    PRD §3.4: "That requires the season to be in `AUDITIONS_OPEN` and requires `revision_round` to be strictly below two; a third revision request on the same audition is refused with `ERR_MAX_REVISION_ROUNDS_REACHED`."

    Design: Corner/errors/third_revision_request_is_refused_after_two_rounds
    """
    ctx = X.scored_audition(api, slot_overrides={"capacity": 8})
    audition_id = ctx["audition"]["id"]
    slot_id = ctx["slot"]["id"]
    for _ in range(2):
        validate_success(_request_revision_response(api, audition_id))
        X.schedule_audition(api, audition_id, slot_id)
        X.submit_uniform_sheets(api, audition_id, ctx["panelists"], 20)
    response = _request_revision_response(api, audition_id)
    validate_error(response, ApiErrorId.ERR_MAX_REVISION_ROUNDS_REACHED.value)


# --------------------------------------------------------------------------
# Uniqueness tuples
# --------------------------------------------------------------------------

def test_second_section_for_the_same_instrument_is_refused(api):
    """A second section on one ensemble for the same instrument is refused.

    PRD §3.1: "Only one section may exist per combination of `ensemble_id` and `instrument`; a second attempt is `ERR_DUPLICATE_SECTION_QUOTA`."

    Design: Corner/errors/every_uniqueness_tuple_reports_its_own_duplicate_error
    """
    X.set_clock(api)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"], instrument="CELLO")
    response = api.create_section_quota(
        F.section_quota_payload(ensemble["id"], instrument="CELLO"), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SECTION_QUOTA.value)


def test_second_audition_for_the_same_member_and_season_is_refused(api):
    """A second non-terminal audition for one musician in one season is refused.

    PRD §3.4: "Only one non-terminal audition may exist per combination of `member_id` and `season_id`, and a second is `ERR_DUPLICATE_AUDITION`."

    Design: Corner/errors/every_uniqueness_tuple_reports_its_own_duplicate_error
    """
    X.set_clock(api)
    season = X.create_season(api)
    member = X.create_member(api)
    X.create_audition(api, member["id"], season["id"])
    response = api.create_audition(
        F.audition_payload(member["id"], season["id"], declared_program="Second Try"),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_AUDITION.value)


def test_second_placement_for_the_same_audition_and_ensemble_is_refused(api):
    """A second non-terminal placement on one audition-and-ensemble pair is refused.

    PRD §3.5: "No other placement for the same musician and ensemble may already sit in `OFFERED`, `WAITLISTED` or `ACCEPTED`, and at most one non-terminal placement may exist per combination of `audition_id` and `ensemble_id`; a collision is `ERR_DUPLICATE_PLACEMENT`."

    Design: Corner/errors/every_uniqueness_tuple_reports_its_own_duplicate_error
    """
    ctx = X.placement_offer(api, quota_overrides={"max_count": 4})
    response = _placement_response(
        api, ctx["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PLACEMENT.value)


def test_second_participation_for_the_same_event_and_member_is_refused(api):
    """A second roster row for one musician on one event is refused.

    PRD §3.8: "Only one row may exist per combination of `event_id` and `member_id`, a second being `ERR_DUPLICATE_PARTICIPATION`."

    Design: Corner/errors/every_uniqueness_tuple_reports_its_own_duplicate_error
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(api, ctx["ensemble"]["id"], kind="REHEARSAL")
    X.create_participation(api, event["id"], ctx["member"]["id"])
    response = api.create_event_participation(
        F.participation_payload(event["id"], ctx["member"]["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PARTICIPATION.value)


# --------------------------------------------------------------------------
# Placement admission and chair rotation
# --------------------------------------------------------------------------

def test_offer_above_the_recommended_tier_is_refused(api):
    """A `PHILHARMONIC` recommendation may not be offered a `SYMPHONY` chair.

    PRD §3.5: "The tier bands are ordered with `SYMPHONY` highest, then `PHILHARMONIC`, then `CONCERT_ORCHESTRA`, and the target ensemble's `tier` must be equal to or below the audition's `tier_recommendation` — a musician may always be offered a lower tier than recommended, never a higher one, and a higher one is `ERR_TIER_ABOVE_RECOMMENDATION`."

    Design: Corner/errors/placement_admission_and_rotation_gate_errors_are_each_triggerable
    """
    ctx = X.adjudicated_audition(
        api, score_value=20, ensemble_overrides={"tier": "SYMPHONY"}
    )
    X.advance_season(api, ctx["season"]["id"], "PLACEMENT")
    response = _placement_response(
        api, ctx["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    validate_error(response, ApiErrorId.ERR_TIER_ABOVE_RECOMMENDATION.value)


def test_offer_into_an_ensemble_without_the_instrument_is_refused(api):
    """An ensemble owning no section for the musician's instrument refuses the offer.

    PRD §3.5: "The ensemble must own a section whose `instrument` equals the musician's `primary_instrument`, or the request is `ERR_NO_SECTION_FOR_INSTRUMENT`."

    Design: Corner/errors/placement_admission_and_rotation_gate_errors_are_each_triggerable
    """
    ctx = X.adjudicated_audition(
        api, instrument="CELLO", quota_overrides={"instrument": "VIOLIN"}
    )
    X.advance_season(api, ctx["season"]["id"], "PLACEMENT")
    response = _placement_response(
        api, ctx["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    validate_error(response, ApiErrorId.ERR_NO_SECTION_FOR_INSTRUMENT.value)


def test_offer_on_an_unadjudicated_audition_is_refused(api):
    """A placement referencing an audition still in `SCHEDULED` is refused.

    PRD §3.5: "The referenced audition must be `ADJUDICATED`, must carry a `tier_recommendation` other than `NOT_PLACED`, and must belong to the same season as the ensemble; otherwise `ERR_AUDITION_NOT_ADJUDICATED`."

    Design: Corner/errors/placement_admission_and_rotation_gate_errors_are_each_triggerable
    """
    ctx = _panel_environment(api, slot_overrides={"capacity": 8})
    X.advance_season(api, ctx["season"]["id"], "PLACEMENT")
    response = _placement_response(
        api, ctx["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    validate_error(response, ApiErrorId.ERR_AUDITION_NOT_ADJUDICATED.value)


def test_rotation_on_a_single_chair_section_is_refused(api):
    """A rotating section holding one active chair cannot run a rotation cycle.

    PRD §3.6: "Rotation is permitted only when the section's `rotation_policy` is `ROTATING` and its `filled_count` is at least 2 — a `FIXED` section, or a section holding fewer than two `ACTIVE` chairs, is refused with `ERR_ROTATION_NOT_PERMITTED` — and only when the owning ensemble's `roster_state` is `SEATED`, since a `FORMING` ensemble cannot rotate chairs even if the section itself is `FULL`, which is refused with `ERR_ENSEMBLE_NOT_SEATED`."

    Design: Corner/errors/placement_admission_and_rotation_gate_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    assert ctx["ensemble"]["roster_state"] == "SEATED"
    response = api.rotate_chairs(
        ctx["quota"]["id"],
        F.rotate_chairs_payload(X.ensemble_version(api, ctx["ensemble"]["id"])),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ROTATION_NOT_PERMITTED.value)


# --------------------------------------------------------------------------
# Attendance windows and the excuse duty split
# --------------------------------------------------------------------------

def test_attendance_cannot_be_recorded_before_the_event_starts(api):
    """Taking the register before the event begins is refused.

    PRD §3.8: "Recording requires the row still to be `NOT_RECORDED`, so a second recording on the same row is refused with `ERR_INVALID_STATE_FOR_OPERATION`, and it requires the logical clock to be at or after the event's `start_at`; recording attendance strictly before the event begins is `ERR_EVENT_NOT_STARTED`."

    Design: Corner/errors/attendance_window_and_excuse_duty_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="REHEARSAL",
        start_at="2026-10-05T18:00:00Z",
        end_at="2026-10-05T20:00:00Z",
    )
    participation = X.create_participation(api, event["id"], ctx["member"]["id"])
    response = api.record_attendance(
        participation["id"], F.attendance_payload("PRESENT"), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_STARTED.value)


def test_excuse_filed_at_the_window_boundary_is_refused(api):
    """An excuse filed exactly forty-eight hours after the event ends is refused.

    PRD §3.8: "A `Guardian` files an excuse for their own musician, advancing the row `ABSENCE_UNVERIFIED → EXCUSE_PENDING`, and must do so while the logical clock is strictly before the event's `end_at` advanced by forty-eight hours; at or after that instant the window has closed and the request is `ERR_EXCUSE_WINDOW_CLOSED`."

    Design: Corner/errors/attendance_window_and_excuse_duty_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    start_at = "2026-10-05T18:00:00Z"
    end_at = "2026-10-05T20:00:00Z"
    event = X.create_ensemble_event(
        api, ctx["ensemble"]["id"], kind="REHEARSAL", start_at=start_at, end_at=end_at
    )
    participation = X.create_participation(api, event["id"], ctx["member"]["id"])
    X.set_clock(api, shift_instant(start_at, minutes=5))
    X.record_attendance(api, participation["id"], "ABSENCE_UNVERIFIED")
    X.set_clock(api, shift_instant(end_at, hours=48))
    response = api.request_excuse(
        participation["id"],
        F.excuse_request_payload("TRANSPORT"),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EXCUSE_WINDOW_CLOSED.value)


def test_registrar_who_recorded_the_absence_may_not_decide_the_excuse(api):
    """The registrar who recorded the absence may not rule on its excuse.

    PRD §3.8: "`RegistrarStaff` then decides the pending excuse by supplying a `decision`, and the decision is segregated from the recording: the acting `X-User-ID` must not equal the `X-User-ID` that recorded the absence in the earlier attendance call on the same row, and must not equal an `excuse_decided_by_user_id` left by an earlier decision; either coincidence is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/attendance_window_and_excuse_duty_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    start_at = "2026-10-05T18:00:00Z"
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="REHEARSAL",
        start_at=start_at,
        end_at="2026-10-05T20:00:00Z",
    )
    participation = X.create_participation(api, event["id"], ctx["member"]["id"])
    X.set_clock(api, shift_instant(start_at, minutes=5))
    X.record_attendance(
        api, participation["id"], "ABSENCE_UNVERIFIED", headers=REGISTRAR_HEADERS
    )
    validate_success(
        api.request_excuse(
            participation["id"],
            F.excuse_request_payload("ILLNESS"),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    response = api.decide_excuse(
        participation["id"], F.excuse_decision_payload("APPROVED"), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# --------------------------------------------------------------------------
# Programming and tour readiness
# --------------------------------------------------------------------------

def test_programming_a_rehearsal_is_refused(api):
    """A rehearsal is never programmable.

    PRD §3.9: "The `ArtisticDirector` programs an event whose `programming_state` is `DRAFT` or `SOLOIST_VACANT` and whose `kind` is anything other than `REHEARSAL`; a rehearsal, or an event already sitting in `PROGRAMMED`, is refused with `ERR_EVENT_NOT_PROGRAMMABLE`."

    Design: Corner/errors/programming_and_tour_readiness_errors_are_each_triggerable
    """
    ctx = X.open_season_with_ensemble(api)
    event = X.create_ensemble_event(api, ctx["ensemble"]["id"], kind="REHEARSAL")
    response = api.program_event(event["id"], F.programming_payload(), DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_PROGRAMMABLE.value)


def test_auto_select_with_an_empty_candidate_pool_is_refused(api):
    """Programming a concert whose only seated player is unreviewed is refused.

    PRD §3.9: "An empty pool refuses the programming with `ERR_NO_ELIGIBLE_SOLOIST`."

    Design: Corner/errors/programming_and_tour_readiness_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="CONCERT",
        start_at="2026-11-15T19:00:00Z",
        end_at="2026-11-15T21:00:00Z",
        venue_code="HALL-B",
        eligibility_window_start="2026-10-01T00:00:00Z",
    )
    X.create_participation(api, event["id"], ctx["member"]["id"])
    response = api.program_event(event["id"], F.programming_payload(), DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_SOLOIST.value)


def test_tour_readiness_with_a_fundraising_shortfall_is_refused(api):
    """A tour row still short of its cost share cannot reach readiness.

    PRD §3.9: "The row advances `PENDING → READY` only when `fundraising_shortfall_cents` is 0, when `chaperone_confirmed` is true in the case that the event's `chaperone_required` is true, and when `performance_eligibility` is `ELIGIBLE`; if any of those three does not hold, the request is refused with `ERR_TOUR_REQUIREMENTS_UNMET`."

    Design: Corner/errors/programming_and_tour_readiness_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="TOUR_PERFORMANCE",
        start_at="2026-11-20T19:00:00Z",
        end_at="2026-11-20T21:00:00Z",
        venue_code="TOUR-HALL",
        eligibility_window_start="2026-10-01T00:00:00Z",
        tour_cost_share_cents=50000,
    )
    participation = X.create_participation(api, event["id"], ctx["member"]["id"])
    response = api.submit_tour_requirements(
        participation["id"],
        F.tour_requirements_payload(fundraising_amount_cents=20000),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TOUR_REQUIREMENTS_UNMET.value)


# --------------------------------------------------------------------------
# Tuition, the final assessment and the aid award run
# --------------------------------------------------------------------------

def test_payment_above_the_balance_is_refused(api):
    """A payment larger than the account's balance is refused, not credited.

    PRD §3.7: "A `Guardian` records a payment against their own account by supplying `amount_cents`, which must be at least 1 and no greater than the account's current `balance_cents`; an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE` rather than credited."

    Design: Corner/errors/tuition_and_aid_run_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    account = ctx["account"]
    response = api.record_payment(
        account["id"],
        F.payment_payload(account["balance_cents"] + 1),
        guardian_headers(ctx["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


def test_second_final_assessment_is_refused(api):
    """The final tuition assessment may be computed only once per account.

    PRD §3.7: "It requires the account's `assessment_variant` to still be `PRELIMINARY` — the final assessment is computed exactly once — and requires the musician's placement to be `ACCEPTED`; either failure is `ERR_ASSESSMENT_ALREADY_FINAL`."

    Design: Corner/errors/tuition_and_aid_run_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    account_id = ctx["account"]["id"]
    validate_success(api.finalize_assessment(account_id, {}, FINANCE_HEADERS))
    response = api.finalize_assessment(account_id, {}, FINANCE_HEADERS)
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_ALREADY_FINAL.value)


def test_reviewing_officer_may_not_execute_the_award_run(api):
    """The officer who reviewed an aid request may not fund it.

    PRD §3.7: "Segregation of duties bites first: the acting `X-User-ID` must not equal `aid_reviewed_by_user_id` on *any* account in the run queue, since the officer who reviewed a request may not be the officer who funds it, and a violation is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/tuition_and_aid_run_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    account_id = ctx["account"]["id"]
    validate_success(
        api.request_aid(
            account_id,
            F.aid_request_payload(40000),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))
    response = api.aid_award_run(
        ctx["season"]["id"],
        F.aid_award_run_payload(X.season_version(api, ctx["season"]["id"])),
        FINANCE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# --------------------------------------------------------------------------
# Empty aid pool, member dimensions and delinquency
# --------------------------------------------------------------------------

def test_aid_review_without_a_budget_is_refused(api):
    """A season authorizing no aid pool cannot open a request for funding.

    PRD §3.7: "The season's `aid_budget_cents` must be greater than 0 — a season with no aid pool cannot open reviews, and the attempt is `ERR_NO_AID_BUDGET`."

    Design: Corner/errors/empty_aid_pool_delinquency_and_member_dimension_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api, season_overrides={"aid_budget_cents": 0})
    account_id = ctx["account"]["id"]
    validate_success(
        api.request_aid(
            account_id,
            F.aid_request_payload(40000),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    response = api.review_aid(account_id, {}, FINANCE_HEADERS)
    validate_error(response, ApiErrorId.ERR_NO_AID_BUDGET.value)


def test_alumni_is_unreachable_from_prospect(api):
    """`ALUMNI` is reachable only from `GRADUATED`, so a prospect cannot reach it.

    PRD §3.2: "If the pair is not a declared transition out of the musician's current value on that dimension, the request is refused with `ERR_INVALID_MEMBER_TRANSITION`; that includes any attempt to reach `ALUMNI` from anything other than `GRADUATED`, and any attempt to reach `ALUMNI` for a musician whose `alumni_engagement_opt_in` is false."

    Design: Corner/errors/empty_aid_pool_delinquency_and_member_dimension_errors_are_each_triggerable
    """
    member = X.create_member(api)
    response = api.member_status_transition(
        member["id"],
        F.member_status_transition_payload("ENROLLMENT", "ALUMNI"),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_MEMBER_TRANSITION.value)


def test_delinquent_account_blocks_the_season_close(api):
    """A delinquent tuition account refuses the season's close.

    PRD §3.1: "Closing a season additionally requires that no tuition account of that season carries `billing_status` `DELINQUENT`; a delinquent account refuses the close with `ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE`."

    Design: Corner/errors/empty_aid_pool_delinquency_and_member_dimension_errors_are_each_triggerable
    """
    ctx = X.accepted_placement(api)
    assert ctx["season"]["status"] == "IN_SEASON"
    X.set_clock(api, "2026-12-02T00:00:00Z")
    validate_success(
        api.record_payment(
            ctx["account"]["id"],
            F.payment_payload(1),
            guardian_headers(ctx["member"]["id"]),
        ),
        201,
    )
    response = api.advance_season_status(
        ctx["season"]["id"], F.advance_status_payload("CLOSED"), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE.value)
