"""Cyclic and two-axis lifecycles: the proofing loop and the tabulator's axes.

The first family walks a ballot style around the proofing loop, where one
endpoint forks into two target states with different side effects and the
re-entry edge out of a rejection carries an effect that the first entry does
not. The second family walks a tabulator whose programming history and whose
physical custody advance independently, so that the same pair of readings
recurs after having been reached by different triggers.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_LANGUAGE_COVERAGE_INCOMPLETE,
    ERR_STYLE_STATE_INVALID,
    ERR_UNIT_STATE_INVALID,
)
from test_helpers.constants import (
    CUSTODY_DEPLOYED,
    CUSTODY_IN_VAULT,
    DECK_CONSUMED,
    DECK_DRAFT,
    DECK_SEALED,
    DECK_VOIDED,
    EVENT_SEAL_APPLIED,
    EVENT_SEAL_BROKEN,
    FIRMWARE_VERSION,
    FIRMWARE_VERSION_NEXT,
    LANGUAGE_EN,
    FORMAT_PAPER_STANDARD,
    PHASE_CONTESTS_CERTIFIED,
    SEAL_TAB_1,
    SESSION_FAILED,
    SESSION_IN_PROGRESS,
    SESSION_PASSED,
    SESSION_START,
    STYLE_APPROVED,
    STYLE_PROOF_REJECTED,
    STYLE_PROOFING,
    SUBJECT_TABULATOR_UNIT,
    UNIT_LA_FAILED,
    UNIT_LA_PASSED,
    UNIT_PROGRAMMED,
    USER_DIRECTOR,
    USER_TECH_1,
)

_SECOND_SESSION_START = "2026-09-02T14:00:00Z"
_SECOND_SESSION_END = "2026-09-02T18:00:00Z"


# ─── Proofing-loop helpers ───────────────────────────────────────────────────

def _proofing_style(client) -> fixtures.Scenario:
    """An election whose only style has been sent out for its first proof."""
    sc = fixtures.contests_certified(client)
    fixtures.certify_languages(sc)
    validate_success(sc.client.request_proof(sc.style_id, users.COORDINATOR))
    return sc


def _decide(sc: fixtures.Scenario, decision: str, note: str):
    return sc.client.proof_decision(
        sc.style_id, f.proof_decision_payload(decision, note), users.DIRECTOR)


def _request_proof(sc: fixtures.Scenario):
    return sc.client.request_proof(sc.style_id, users.COORDINATOR)


def _second_proofing_cycle(client) -> fixtures.Scenario:
    """Style rejected once, re-certified and re-sent, so it is PROOFING at revision 2."""
    sc = _proofing_style(client)
    validate_success(_decide(sc, "REJECT", "Spanish glyphs clipped in contest 2"))
    fixtures.certify_languages(sc)
    validate_success(_request_proof(sc))
    return sc


def _third_proofing_cycle(client) -> fixtures.Scenario:
    """Style rejected twice, re-certified and re-sent, so it is PROOFING at revision 3."""
    sc = _second_proofing_cycle(client)
    validate_success(_decide(sc, "REJECT", "Header rule still 1pt too thin"))
    fixtures.certify_languages(sc)
    validate_success(_request_proof(sc))
    return sc


# ─── Tabulator helpers ───────────────────────────────────────────────────────

def _deck(sc: fixtures.Scenario, deck_id: str) -> Dict[str, Any]:
    rows, _meta = validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.DIRECTOR, {"limit": 100}))
    return asserts.find_by(rows, "id", deck_id)


def _mismatched_results(sc: fixtures.Scenario) -> Dict[str, Any]:
    """Report the deck's marks correctly but understate its blank ballot by one."""
    return f.record_results_payload(
        [f.reported_mark(sc.contest_id, sc.candidate_id, 1)],
        reported_blank_count=0,
        reported_overvote_count=0,
    )


def _matching_results(sc: fixtures.Scenario) -> Dict[str, Any]:
    return f.record_results_payload(
        [f.reported_mark(sc.contest_id, sc.candidate_id, 1)],
        reported_blank_count=1,
        reported_overvote_count=0,
    )


def _session_ready_world(client) -> fixtures.Scenario:
    """Locked election, issued paper, one programmed unit and a scheduled public test.

    The unit is programmed by one technician and the session is scheduled and
    conducted by a different one, and the clock is left at the session's start.
    """
    sc = fixtures.issued_lot(client)
    fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)
    fixtures.add_test_deck(sc, deck_code="DECK-A")
    fixtures.schedule_session(sc)
    fixtures.sign_in_observers(sc)
    fixtures.set_clock(client, SESSION_START)
    return sc


def _failed_unit(client) -> fixtures.Scenario:
    """The unit's first public test fails, demoting only its programming axis."""
    sc = _session_ready_world(client)
    validate_success(sc.client.start_session(sc.session_id, users.TECHNICIAN_2))
    validate_success(
        sc.client.record_results(sc.session_id, _mismatched_results(sc), users.TECHNICIAN_2))
    return sc


def _reprogrammed_unit(client) -> fixtures.Scenario:
    sc = _failed_unit(client)
    validate_success(
        sc.client.program_tabulator(
            sc.tabulator_id, f.program_payload(sc.style_id, FIRMWARE_VERSION_NEXT),
            users.TECHNICIAN))
    return sc


def _second_session_started(client):
    """Rebuild a deck, schedule a second test on the next day and open it."""
    sc = _reprogrammed_unit(client)
    deck_b = fixtures.add_test_deck(sc, deck_code="DECK-B")
    session_two = fixtures.schedule_session(
        sc, deck_id=deck_b, scheduled_start=_SECOND_SESSION_START,
        scheduled_end=_SECOND_SESSION_END)
    fixtures.sign_in_observers(sc, session_id=session_two)
    fixtures.set_clock(sc.client, _SECOND_SESSION_START)
    validate_success(sc.client.start_session(session_two, users.TECHNICIAN_2))
    return sc, deck_b, session_two


def _passed_unit(client):
    sc, deck_b, session_two = _second_session_started(client)
    validate_success(
        sc.client.record_results(session_two, _matching_results(sc), users.TECHNICIAN_2))
    return sc, deck_b, session_two


def _deployed_unit(client):
    sc, deck_b, session_two = _passed_unit(client)
    validate_success(
        sc.client.deploy_tabulator(
            sc.tabulator_id, f.deploy_unit_payload(sc.precinct_id, SEAL_TAB_1),
            users.CUSTODIAN))
    return sc, deck_b, session_two


# ---- The ballot style's proofing loop ----

def test_nl_rejection_clears_coverage_and_leaves_the_revision_alone(client):
    """Rejecting the first proof wipes both coverage lists while revision stays at one.

    PRD Section 3.4: "With `decision` `REJECT` the style moves `PROOFING → PROOF_REJECTED`, `proof_decided_by_user_id` is set to the deciding `X-User-ID`, and the style's `version` is bumped — and in addition `translated_languages` and `certified_formats` are both cleared to empty arrays, so re-translation and re-certification are required before the style can be sent out again, and every test deck of the style in `DRAFT` or `SEALED` transitions to `VOIDED`."

    PRD Section 3.4: "`revision` is **not** touched by a rejection; only the subsequent re-request out of `PROOF_REJECTED` increments it."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _proofing_style(client)

    style = validate_success(_decide(sc, "REJECT", "Spanish glyphs clipped in contest 2"))
    asserts.assert_fields_equal(
        style,
        {
            "status": STYLE_PROOF_REJECTED,
            "revision": 1,
            "proof_cycle_count": 1,
            "translated_languages": [],
            "certified_formats": [],
            "proof_decided_by_user_id": USER_DIRECTOR,
        },
        "ballot style",
    )


def test_nl_reentering_the_loop_needs_the_language_work_redone(client):
    """An immediate re-request after a rejection is refused because the coverage was wiped.

    PRD Section 3.4: "And coverage must be complete: every member of `language_set` must appear in `translated_languages` and every member of `required_formats` must appear in `certified_formats`, or the request fails with `ERR_LANGUAGE_COVERAGE_INCOMPLETE`."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _proofing_style(client)
    validate_success(_decide(sc, "REJECT", "Spanish glyphs clipped in contest 2"))

    validate_error(_request_proof(sc), ERR_LANGUAGE_COVERAGE_INCOMPLETE)

    style = sc.read_style()
    asserts.assert_fields_equal(
        style,
        {"status": STYLE_PROOF_REJECTED, "revision": 1, "proof_cycle_count": 1},
        "ballot style",
    )


def test_nl_loop_edge_out_of_rejection_bumps_the_revision(client):
    """Re-sending a rejected style raises revision to two and the proof cycle count to two.

    PRD Section 3.4: "A successful request moves the style to `PROOFING`, increments `proof_cycle_count` by one, records `proof_requested_by_user_id` as the calling `X-User-ID`, clears `proof_decided_by_user_id` back to null, and bumps the style's `version`."

    PRD Section 3.4: "One further effect fires **only** on the loop path: when the style was in `PROOF_REJECTED` rather than `DRAFT`, `revision` is also incremented by one."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _proofing_style(client)
    validate_success(_decide(sc, "REJECT", "Spanish glyphs clipped in contest 2"))
    fixtures.certify_languages(sc)

    style = validate_success(_request_proof(sc))
    asserts.assert_fields_equal(
        style,
        {
            "status": STYLE_PROOFING,
            "revision": 2,
            "proof_cycle_count": 2,
            "proof_decided_by_user_id": None,
        },
        "ballot style",
    )


def test_nl_request_proof_on_a_proofing_style_is_guarded(client):
    """Asking for a proof while one is already out is refused, so the loop edge is not idempotent.

    PRD Section 3.4: "The style must print at least one contest, that is its `contest_count` must be 1 or more, or the request fails with `ERR_STYLE_STATE_INVALID`; the same error answers an attempt to send a style that is not currently `DRAFT` or `PROOF_REJECTED`."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _second_proofing_cycle(client)

    validate_error(_request_proof(sc), ERR_STYLE_STATE_INVALID)

    style = sc.read_style()
    asserts.assert_fields_equal(
        style,
        {"status": STYLE_PROOFING, "revision": 2, "proof_cycle_count": 2},
        "ballot style",
    )


def test_nl_second_rejection_repeats_the_same_target_state(client):
    """The decision endpoint reaches PROOF_REJECTED a second time without moving either counter.

    PRD Section 3.4: "With `decision` `REJECT` the style moves `PROOFING → PROOF_REJECTED`, `proof_decided_by_user_id` is set to the deciding `X-User-ID`, and the style's `version` is bumped — and in addition `translated_languages` and `certified_formats` are both cleared to empty arrays, so re-translation and re-certification are required before the style can be sent out again, and every test deck of the style in `DRAFT` or `SEALED` transitions to `VOIDED`."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _second_proofing_cycle(client)

    style = validate_success(_decide(sc, "REJECT", "Header rule still 1pt too thin"))
    asserts.assert_fields_equal(
        style,
        {
            "status": STYLE_PROOF_REJECTED,
            "revision": 2,
            "proof_cycle_count": 2,
            "translated_languages": [],
            "certified_formats": [],
            "proof_decided_by_user_id": USER_DIRECTOR,
        },
        "ballot style",
    )


def test_nl_third_cycle_approval_freezes_both_counters(client):
    """The third trip through proofing carries revision three, and approval touches neither counter.

    PRD Section 3.4: "With `decision` `APPROVE` the style moves `PROOFING → APPROVED`, `proof_decided_by_user_id` is set to the deciding `X-User-ID`, and the style's `version` is bumped."

    PRD Section 3.4: "Nothing else changes: `translated_languages`, `certified_formats`, `revision` and `proof_cycle_count` are all left as they stand."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _third_proofing_cycle(client)
    asserts.assert_fields_equal(
        sc.read_style(),
        {"status": STYLE_PROOFING, "revision": 3, "proof_cycle_count": 3},
        "ballot style",
    )

    style = validate_success(_decide(sc, "APPROVE", "Third proof accepted"))
    asserts.assert_fields_equal(
        style,
        {
            "status": STYLE_APPROVED,
            "revision": 3,
            "proof_cycle_count": 3,
            "translated_languages": [LANGUAGE_EN],
            "certified_formats": [FORMAT_PAPER_STANDARD],
            "proof_decided_by_user_id": USER_DIRECTOR,
        },
        "ballot style",
    )
    assert sc.read_election()["status"] == PHASE_CONTESTS_CERTIFIED


def test_nl_approved_style_is_a_one_way_exit_from_the_loop(client):
    """A second decision on an approved style is refused, so approval cannot be taken back.

    PRD Section 3.4: "Deciding a proof is open to either an `ElectionsDirector` or a `BallotCoordinator`, requires the style to be `PROOFING` (otherwise `ERR_STYLE_STATE_INVALID`), and requires the election to be in `CONTESTS_CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/nl_style_proof_reject_reproof_cycle
    """
    sc = _third_proofing_cycle(client)
    validate_success(_decide(sc, "APPROVE", "Third proof accepted"))

    validate_error(_decide(sc, "REJECT", "Too late to change our mind"),
                   ERR_STYLE_STATE_INVALID)

    asserts.assert_fields_equal(
        sc.read_style(),
        {"status": STYLE_APPROVED, "revision": 3, "proof_cycle_count": 3},
        "ballot style",
    )


# ---- The tabulator's two independent state axes ----

def test_nl_starting_a_session_moves_the_deck_not_the_unit(client):
    """Opening the public test seals the deck and leaves both axes of the unit where they were.

    PRD Section 3.8: "On success the session moves `SCHEDULED → IN_PROGRESS`, `started_at` is stamped from the logical clock, `conducted_by_user_id` records the starting `X-User-ID`, and the referenced deck transitions `DRAFT → SEALED`, becoming immutable for the duration of the session."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc = _session_ready_world(client)
    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {"program_status": UNIT_PROGRAMMED, "custody_status": CUSTODY_IN_VAULT},
        "tabulator",
    )
    asserts.assert_fields_equal(
        _deck(sc, sc.deck_id),
        {"status": DECK_DRAFT, "expected_total_marks": 1},
        "test deck",
    )

    session = validate_success(sc.client.start_session(sc.session_id, users.TECHNICIAN_2))
    assert session["status"] == SESSION_IN_PROGRESS
    assert _deck(sc, sc.deck_id)["status"] == DECK_SEALED
    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {"program_status": UNIT_PROGRAMMED, "custody_status": CUSTODY_IN_VAULT},
        "tabulator",
    )


def test_nl_failed_result_demotes_only_the_program_axis(client):
    """A single wrong blank count fails the test, demoting the programming axis alone.

    PRD Section 3.8: "To that mark total add the absolute difference between `reported_blank_count` and the deck's `blank_count`, and the absolute difference between `reported_overvote_count` and the deck's `overvote_count`."

    PRD Section 3.8: "Hop 1: the session moves `IN_PROGRESS → FAILED` and the deck moves `SEALED → VOIDED` — the deck must be rebuilt before the unit can be tested again."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc = _session_ready_world(client)
    validate_success(sc.client.start_session(sc.session_id, users.TECHNICIAN_2))

    session = validate_success(
        sc.client.record_results(sc.session_id, _mismatched_results(sc), users.TECHNICIAN_2))
    asserts.assert_fields_equal(
        session,
        {"discrepancy_count": 1, "status": SESSION_FAILED},
        "logic-and-accuracy session",
    )
    assert _deck(sc, sc.deck_id)["status"] == DECK_VOIDED
    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {"program_status": UNIT_LA_FAILED, "custody_status": CUSTODY_IN_VAULT},
        "tabulator",
    )


def test_nl_deploy_is_refused_while_the_program_axis_reads_failed(client):
    """A unit sitting in the vault with a failed test cannot be deployed even though it is in the vault.

    PRD Section 3.9: "Its guards, in ascending rank, are: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the unit's `program_status` must be `LA_PASSED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — an untested machine never leaves the vault; at least one ballot lot with that `precinct_id` must be in `ISSUED`, or `ERR_LOT_STATE_INVALID` — the machine does not travel ahead of the paper; the unit's `programmed_style_id` must equal the precinct's `assigned_style_id`, or `ERR_UNIT_STYLE_MISMATCH` — a machine programmed for one district combination cannot read another's ballots; and the `seal_number` must not already be held by any other ballot lot or tabulator of the election, or `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc = _failed_unit(client)

    validate_error(
        sc.client.deploy_tabulator(
            sc.tabulator_id, f.deploy_unit_payload(sc.precinct_id, SEAL_TAB_1),
            users.CUSTODIAN),
        ERR_UNIT_STATE_INVALID,
    )

    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {
            "program_status": UNIT_LA_FAILED,
            "custody_status": CUSTODY_IN_VAULT,
            "precinct_id": None,
            "seal_number": None,
        },
        "tabulator",
    )
    assert sc.read_election()["open_seal_count"] == 0


def test_nl_program_axis_cycles_back_out_of_failure(client):
    """Reprogramming a failed unit that is still in the vault returns it to PROGRAMMED.

    PRD Section 3.8: "On success `programmed_style_id`, `firmware_version` and `programmed_by_user_id` are written, the last from the calling `X-User-ID`, and `program_status` becomes `PROGRAMMED`."

    PRD Section 3.8: "Programming a unit that previously failed simply overwrites all three fields, closing the loop from `LA_FAILED` back through `PROGRAMMED` to `LA_PASSED`; the recorded programmer is whoever performed the *latest* programming, which is what the segregation-of-duties check below consults."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc = _failed_unit(client)

    unit = validate_success(
        sc.client.program_tabulator(
            sc.tabulator_id, f.program_payload(sc.style_id, FIRMWARE_VERSION_NEXT),
            users.TECHNICIAN))
    asserts.assert_fields_equal(
        unit,
        {
            "program_status": UNIT_PROGRAMMED,
            "custody_status": CUSTODY_IN_VAULT,
            "firmware_version": FIRMWARE_VERSION_NEXT,
            "programmed_style_id": sc.style_id,
            "programmed_by_user_id": USER_TECH_1,
        },
        "tabulator",
    )
    assert unit["firmware_version"] != FIRMWARE_VERSION


def test_nl_second_session_passes_and_promotes_the_program_axis(client):
    """A rebuilt deck reported exactly passes the retest and lifts the unit to LA_PASSED in the vault.

    PRD Section 3.8: "The session moves `IN_PROGRESS → PASSED`, the deck moves `SEALED → CONSUMED`, the unit's `program_status` moves to `LA_PASSED`, `la_session_count` is recomputed as the number of sessions on that unit, and the readiness chain runs: the unit's precinct, if it has one, recomputes `deployment_status`, and the election recomputes `deployment_readiness`."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc, deck_b, session_two = _second_session_started(client)

    session = validate_success(
        sc.client.record_results(session_two, _matching_results(sc), users.TECHNICIAN_2))
    asserts.assert_fields_equal(
        session,
        {"discrepancy_count": 0, "status": SESSION_PASSED},
        "logic-and-accuracy session",
    )
    assert _deck(sc, deck_b)["status"] == DECK_CONSUMED
    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {
            "program_status": UNIT_LA_PASSED,
            "custody_status": CUSTODY_IN_VAULT,
            "la_session_count": 2,
        },
        "tabulator",
    )


def test_nl_deploy_moves_the_custody_axis_and_leaves_the_program_axis(client):
    """Sealing the tested unit out to its precinct advances custody while programming stays LA_PASSED.

    PRD Section 3.9: "On success the unit moves `IN_VAULT → DEPLOYED`, stores `precinct_id` and `seal_number`, appends a custody event of type `SEAL_APPLIED` with `from_state` `IN_VAULT` and `to_state` `DEPLOYED`, increments the election's `open_seal_count` by one, and re-derives the precinct's `deployment_status` and the election's `deployment_readiness`."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc, _deck_b, _session_two = _passed_unit(client)

    unit = validate_success(
        sc.client.deploy_tabulator(
            sc.tabulator_id, f.deploy_unit_payload(sc.precinct_id, SEAL_TAB_1),
            users.CUSTODIAN))
    asserts.assert_fields_equal(
        unit,
        {
            "program_status": UNIT_LA_PASSED,
            "custody_status": CUSTODY_DEPLOYED,
            "precinct_id": sc.precinct_id,
            "seal_number": SEAL_TAB_1,
        },
        "tabulator",
    )
    assert sc.read_election()["open_seal_count"] == 1


def test_nl_break_seal_returns_custody_without_touching_the_program_axis(client):
    """Breaking the seal restores the vault reading and the seal count while the unit stays LA_PASSED.

    PRD Section 3.9: "The unit moves `DEPLOYED → IN_VAULT`, `seal_number` and `precinct_id` are cleared to null, a custody event of type `SEAL_BROKEN` is appended recording the seal that was broken, and `open_seal_count` is decremented — returning to exactly its pre-deploy value."

    PRD Section 3.9: "The programming axis is untouched: the unit is still `LA_PASSED` and can be redeployed without retesting."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc, _deck_b, _session_two = _deployed_unit(client)

    unit = validate_success(
        sc.client.break_seal(
            sc.tabulator_id, f.break_seal_payload("Paper jam cleared under observation"),
            users.CUSTODIAN))
    asserts.assert_fields_equal(
        unit,
        {
            "program_status": UNIT_LA_PASSED,
            "custody_status": CUSTODY_IN_VAULT,
            "precinct_id": None,
            "seal_number": None,
        },
        "tabulator",
    )
    assert sc.read_election()["open_seal_count"] == 0

    unit_events = asserts.events_for_subject(sc.custody_events(), sc.tabulator_id)
    assert asserts.event_types(unit_events) == [EVENT_SEAL_APPLIED, EVENT_SEAL_BROKEN]
    asserts.assert_custody_event(
        unit_events[0], EVENT_SEAL_APPLIED, subject_type=SUBJECT_TABULATOR_UNIT,
        subject_id=sc.tabulator_id, from_state=CUSTODY_IN_VAULT,
        to_state=CUSTODY_DEPLOYED, seal_number=SEAL_TAB_1)
    assert unit_events[0]["sequence_index"] == 1
    asserts.assert_custody_event(
        unit_events[1], EVENT_SEAL_BROKEN, subject_type=SUBJECT_TABULATOR_UNIT,
        subject_id=sc.tabulator_id, from_state=CUSTODY_DEPLOYED,
        to_state=CUSTODY_IN_VAULT, seal_number=SEAL_TAB_1)
    assert unit_events[1]["sequence_index"] == 2


def test_nl_la_passed_unit_cannot_be_quietly_reprogrammed(client):
    """A unit back in the vault after a passed test is still refused reprogramming.

    PRD Section 3.8: "The referenced style must exist in the same election, or `ERR_BALLOT_STYLE_NOT_FOUND`; it must be `LOCKED` — an `APPROVED` but unlocked style is `ERR_STYLE_STATE_INVALID`, because a machine must never be programmed against artwork that can still change; and the unit's `program_status` must be `UNPROGRAMMED` or `LA_FAILED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — a deployed machine is not reprogrammed in the field."

    Design: Difficulty/non_linear_state_machine/nl_tabulator_parallel_program_and_custody_axes
    """
    sc, _deck_b, _session_two = _deployed_unit(client)
    validate_success(
        sc.client.break_seal(
            sc.tabulator_id, f.break_seal_payload("Paper jam cleared under observation"),
            users.CUSTODIAN))

    validate_error(
        sc.client.program_tabulator(
            sc.tabulator_id, f.program_payload(sc.style_id, FIRMWARE_VERSION_NEXT),
            users.TECHNICIAN),
        ERR_UNIT_STATE_INVALID,
    )

    asserts.assert_fields_equal(
        sc.read_tabulator(),
        {"program_status": UNIT_LA_PASSED, "custody_status": CUSTODY_IN_VAULT},
        "tabulator",
    )
