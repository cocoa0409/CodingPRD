"""Which error wins when a single call breaks two rules of different rank.

Every test in this file arranges a request that violates two independent rules at
the same time and pins the answer to the higher-ranked one, then isolates each
rule on its own so the combined answer cannot be explained by the losing rule
simply being unreachable.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_OBSERVERS,
    ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT,
    ERR_LOT_NOT_FOR_PRECINCT,
    ERR_OUTSIDE_TEST_WINDOW,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SESSION_STATE_INVALID,
)
from test_helpers.assertions import find_by
from test_helpers.constants import (
    ASSET_TAG_1,
    ASSET_TAG_2,
    DECK_DRAFT,
    DECK_SEALED,
    DISTRICT_D07,
    DISTRICT_D12,
    LOT_CODE_1,
    LOT_ISSUED,
    LOT_RECEIVED,
    POLLING_PLACE_2,
    PRECINCT_CODE_1,
    PRECINCT_CODE_2,
    READINESS_NOT_READY,
    SEAL_1,
    SESSION_END,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SESSION_START,
    STYLE_CODE_ALT,
    STYLE_CODE_MAIN,
    USER_TECH_2,
)

SESSION_1_STARTED_AT = "2026-09-01T14:00:00.000Z"
AFTER_SESSION_1_END = "2026-09-01T19:00:00Z"
SESSION_C_START = "2026-09-04T14:00:00Z"
SESSION_C_END = "2026-09-04T18:00:00Z"
AFTER_SESSION_C_END = "2026-09-04T19:00:00Z"


def _running_session(client):
    """Issued-paper election whose TAB-001 session is IN_PROGRESS at its start instant."""
    sc = fx.issued_lot(client)
    fx.add_tabulator(sc, asset_tag=ASSET_TAG_1)
    fx.program_unit(sc, headers=users.TECHNICIAN)
    fx.add_test_deck(sc, deck_code="DECK-A")
    fx.schedule_session(sc, scheduled_start=SESSION_START, scheduled_end=SESSION_END,
                        headers=users.TECHNICIAN_2)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc, headers=users.TECHNICIAN_2)
    return sc


def _second_scheduled_session(sc):
    """Add a second programmed unit with its own deck and a still-SCHEDULED session."""
    tabulator_id = fx.add_tabulator(sc, asset_tag=ASSET_TAG_2)
    fx.program_unit(sc, tabulator_id=tabulator_id, headers=users.TECHNICIAN)
    deck_id = fx.add_test_deck(sc, deck_code="DECK-C")
    session_id = fx.schedule_session(sc, tabulator_id=tabulator_id, deck_id=deck_id,
                                     scheduled_start=SESSION_C_START,
                                     scheduled_end=SESSION_C_END,
                                     headers=users.TECHNICIAN_2)
    fx.sign_in_observers(sc, session_id=session_id, names=["Obs Three", "Obs Four"])
    return session_id, deck_id


def _deck_status(sc, deck_id):
    decks, _ = validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))
    return find_by(decks, "id", deck_id)["status"]


# ---- Restarting a running session after its window has closed ----

def test_pp_restart_after_window_answers_session_state_not_window(client):
    """A start call that breaks both the session-state guard and the admission window answers the state guard.

    PRD Section 3.9: "The session must be `SCHEDULED`, or `ERR_SESSION_STATE_INVALID` (rank 70). This outranks the window rule, so calling start again on a session already `IN_PROGRESS` after the clock has passed `scheduled_end` answers `ERR_SESSION_STATE_INVALID`, not `ERR_OUTSIDE_TEST_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/pp_session_state_beats_window_temporal
    """
    sc = _running_session(client)
    fx.set_clock(client, AFTER_SESSION_1_END)

    error = validate_error(
        client.start_session(sc.session_id, users.TECHNICIAN_2),
        ERR_SESSION_STATE_INVALID)

    assert ERR_OUTSIDE_TEST_WINDOW not in error.get("message", "")


def test_pp_rejected_restart_leaves_the_running_session_untouched(client):
    """A refused restart writes nothing: the running session keeps its original start stamp and conductor.

    PRD Section 3.9: "On success the session moves `SCHEDULED → IN_PROGRESS`, `started_at` is stamped from the logical clock, `conducted_by_user_id` records the starting `X-User-ID`, and the referenced deck transitions `DRAFT → SEALED`, becoming immutable for the duration of the session."

    Design: Difficulty/priority_pair_validation_conflict/pp_session_state_beats_window_temporal
    """
    sc = _running_session(client)
    fx.set_clock(client, AFTER_SESSION_1_END)

    validate_error(client.start_session(sc.session_id, users.TECHNICIAN_2),
                   ERR_SESSION_STATE_INVALID)

    session = sc.read_session()
    assert session["status"] == SESSION_IN_PROGRESS
    assert session["started_at"] == SESSION_1_STARTED_AT
    assert session["conducted_by_user_id"] == USER_TECH_2


def test_pp_late_start_on_a_scheduled_session_answers_the_window_rule(client):
    """With the state guard satisfied the same endpoint reports the admission window it had suppressed.

    PRD Section 3.9: "The logical clock must fall inside the admission window, the closed interval from 60 minutes before `scheduled_start` through `scheduled_end`; otherwise `ERR_OUTSIDE_TEST_WINDOW` (rank 100)."

    Design: Difficulty/priority_pair_validation_conflict/pp_session_state_beats_window_temporal
    """
    sc = _running_session(client)
    session_id, deck_id = _second_scheduled_session(sc)
    fx.set_clock(client, AFTER_SESSION_C_END)

    validate_error(client.start_session(session_id, users.TECHNICIAN_2),
                   ERR_OUTSIDE_TEST_WINDOW)

    assert sc.read_session(session_id)["status"] == SESSION_SCHEDULED
    assert _deck_status(sc, deck_id) == DECK_DRAFT


# ---- Self-testing technician versus the observer minimum ----

def _one_observer_session(client):
    """Scheduled public session on a unit programmed by user-tech-1, holding one observer."""
    sc = fx.issued_lot(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc, headers=users.TECHNICIAN)
    fx.add_test_deck(sc)
    fx.schedule_session(sc, headers=users.TECHNICIAN_2)
    fx.sign_in_observers(sc, names=["Obs One"])
    fx.set_clock(client, SESSION_START)
    return sc


def test_pp_self_start_short_of_observers_answers_segregation(client):
    """The programming technician starting an under-observed session is refused for segregation, not for the quorum.

    PRD Section 3.9: "The starting `X-User-ID` must **differ** from the unit's `programmed_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` (rank 80). The technician who programmed a machine may not conduct its public test. This rule outranks the observer minimum, so a self-test start that is *also* short of observers answers `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/pp_segregation_beats_observer_constraint
    """
    sc = _one_observer_session(client)

    error = validate_error(
        client.start_session(sc.session_id, users.TECHNICIAN),
        ERR_SEGREGATION_OF_DUTIES)

    assert ERR_INSUFFICIENT_OBSERVERS not in error.get("message", "")
    session = sc.read_session()
    assert session["status"] == SESSION_SCHEDULED
    assert session["started_at"] is None
    assert session["conducted_by_user_id"] is None


def test_pp_observer_shortfall_alone_answers_insufficient_observers(client):
    """With the segregation rule satisfied the one-observer session reports the quorum instead.

    PRD Section 3.9: "`observer_count` must meet the minimum for the session type, or `ERR_INSUFFICIENT_OBSERVERS` (rank 110): at least 2 for a `PRE_ELECTION_PUBLIC` session, at least 1 for a `POST_ELECTION_AUDIT`."

    Design: Difficulty/priority_pair_validation_conflict/pp_segregation_beats_observer_constraint
    """
    sc = _one_observer_session(client)

    validate_error(client.start_session(sc.session_id, users.TECHNICIAN_2),
                   ERR_INSUFFICIENT_OBSERVERS)

    session = sc.read_session()
    assert session["status"] == SESSION_SCHEDULED
    assert session["observer_count"] == 1
    assert session["conducted_by_user_id"] is None


def test_pp_self_start_with_a_full_quorum_still_answers_segregation(client):
    """Once the quorum is met the segregation rule still refuses the programming technician.

    PRD Section 2.6: "A technician who tries to conduct the test of a unit they programmed themselves, on a session that is also short of observers, receives `ERR_SEGREGATION_OF_DUTIES` (rank 80), not `ERR_INSUFFICIENT_OBSERVERS` (rank 110)."

    Design: Difficulty/priority_pair_validation_conflict/pp_segregation_beats_observer_constraint
    """
    sc = _one_observer_session(client)
    validate_success(client.add_observer(sc.session_id, f.observer_payload("Obs Two"),
                                        users.OBSERVER))

    validate_error(client.start_session(sc.session_id, users.TECHNICIAN),
                   ERR_SEGREGATION_OF_DUTIES)

    session = sc.read_session()
    assert session["status"] == SESSION_SCHEDULED
    assert session["observer_count"] == 2
    assert session["started_at"] is None


def test_pp_quorate_start_by_a_second_technician_succeeds(client):
    """Satisfying both rules at once lets the session open and seals the deck.

    PRD Section 3.9: "On success the session moves `SCHEDULED → IN_PROGRESS`, `started_at` is stamped from the logical clock, `conducted_by_user_id` records the starting `X-User-ID`, and the referenced deck transitions `DRAFT → SEALED`, becoming immutable for the duration of the session."

    Design: Difficulty/priority_pair_validation_conflict/pp_segregation_beats_observer_constraint
    """
    sc = _one_observer_session(client)
    validate_success(client.add_observer(sc.session_id, f.observer_payload("Obs Two"),
                                        users.OBSERVER))

    session = validate_success(client.start_session(sc.session_id, users.TECHNICIAN_2))

    assert session["status"] == SESSION_IN_PROGRESS
    assert session["conducted_by_user_id"] == USER_TECH_2
    assert session["started_at"] == SESSION_1_STARTED_AT
    assert session["observer_count"] == 2
    assert _deck_status(sc, sc.deck_id) == DECK_SEALED


# ---- Issuing a wrong-style lot in an impossible quantity ----

def _received_lot_of_two_style_election(client):
    """Two locked styles over different districts; a 500-ballot S-100 lot sits RECEIVED.

    P-001 (D-12) is assigned S-100 and P-002 (D-07) is assigned S-200, so the lot
    belongs to P-001 alone.
    """
    sc = fx.new_election(client)
    fx.add_contest(sc, title="County Sheriff", district_code=DISTRICT_D12)
    fx.add_candidate(sc)
    fx.certify_contest(sc)
    fx.add_contest(sc, title="County Assessor", district_code=DISTRICT_D07)
    fx.add_candidate(sc, contest_id=sc.contest_ids[1], full_name="Ben Brooks",
                     ballot_name="Brooks", filing_received_at="2026-06-02T09:00:00Z")
    fx.certify_contest(sc, contest_id=sc.contest_ids[1])
    fx.add_style(sc, STYLE_CODE_MAIN, [DISTRICT_D12])
    fx.add_style(sc, STYLE_CODE_ALT, [DISTRICT_D07])
    fx.add_precinct(sc, PRECINCT_CODE_1, [DISTRICT_D12], 100)
    fx.add_precinct(sc, PRECINCT_CODE_2, [DISTRICT_D07], 100,
                    polling_place=POLLING_PLACE_2)
    validate_success(client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    for style_id in sc.style_ids:
        fx.certify_languages(sc, style_id=style_id)
        fx.approve_proof_cycle(sc, style_id=style_id)
    fx.assign_style(sc, precinct_id=sc.precinct_ids[0], style_id=sc.style_ids[0])
    fx.assign_style(sc, precinct_id=sc.precinct_ids[1], style_id=sc.style_ids[1])
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    fx.add_vendor(sc)
    fx.add_print_job(sc, style_id=sc.style_ids[0], quantity_ordered=500)
    fx.printed_job(sc)
    fx.inspect_job(sc)
    fx.deliver_job(sc, lots=[f.manifest_line(LOT_CODE_1, 500, SEAL_1)])
    fx.receive_lot(sc, seal_number=SEAL_1, quantity_received=500)
    return sc


def test_pp_wrong_precinct_and_excess_quantity_answers_the_style_match(client):
    """An issue that is both to the wrong precinct and over the receipt answers the referential rule.

    PRD Section 2.6: "Issuing a wrong-style lot in an over-large quantity returns `ERR_LOT_NOT_FOR_PRECINCT` (rank 90), not `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` (rank 120)."

    Design: Difficulty/priority_pair_validation_conflict/pp_lot_referential_beats_fiscal_quantity
    """
    sc = _received_lot_of_two_style_election(client)

    error = validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[1], 600),
                         users.CUSTODIAN),
        ERR_LOT_NOT_FOR_PRECINCT)

    assert ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT not in error.get("message", "")


def test_pp_wrong_precinct_with_a_legal_quantity_answers_the_style_match(client):
    """The referential rule fires on its own when the quantity is well inside the receipt.

    PRD Section 3.7: "The lot must be `RECEIVED`, or `ERR_LOT_STATE_INVALID`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the precinct's `assigned_style_id` must be the ballot style of the lot's own print job, or the issue is refused with `ERR_LOT_NOT_FOR_PRECINCT` — a precinct may not be handed ballots printed for a different district combination; and `issue_quantity` must be at least 1 and no greater than the lot's `quantity_received`, with an excess reported as `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` and a value below 1 as a schema violation."

    Design: Difficulty/priority_pair_validation_conflict/pp_lot_referential_beats_fiscal_quantity
    """
    sc = _received_lot_of_two_style_election(client)

    validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[1], 100),
                         users.CUSTODIAN),
        ERR_LOT_NOT_FOR_PRECINCT)

    assert sc.read_precinct(sc.precinct_ids[1])["ballots_received"] == 0
    assert sc.read_precinct(sc.precinct_ids[1])["deployment_status"] == READINESS_NOT_READY


def test_pp_right_precinct_with_excess_quantity_answers_the_receipt_cap(client):
    """The fiscal rule fires on its own once the lot is offered to the precinct it was printed for.

    PRD Section 3.7: "The lot must be `RECEIVED`, or `ERR_LOT_STATE_INVALID`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the precinct's `assigned_style_id` must be the ballot style of the lot's own print job, or the issue is refused with `ERR_LOT_NOT_FOR_PRECINCT` — a precinct may not be handed ballots printed for a different district combination; and `issue_quantity` must be at least 1 and no greater than the lot's `quantity_received`, with an excess reported as `ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT` and a value below 1 as a schema violation."

    Design: Difficulty/priority_pair_validation_conflict/pp_lot_referential_beats_fiscal_quantity
    """
    sc = _received_lot_of_two_style_election(client)

    validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[0], 600),
                         users.CUSTODIAN),
        ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT)

    lot = sc.read_lot()
    assert lot["custody_state"] == LOT_RECEIVED
    assert lot["issued_quantity"] == 0
    assert lot["unused_quantity"] == 500
    assert lot["precinct_id"] is None


def test_pp_lot_survives_three_refusals_then_issues_cleanly(client):
    """None of the three refused issues moves the lot, and the legal issue then completes in full.

    PRD Section 3.7: "On success the lot moves `RECEIVED → ISSUED`, stores `precinct_id` and `issued_quantity`, sets `unused_quantity` to the received quantity minus the issued quantity, records `issued_by_user_id` as the custodian's `X-User-ID`, appends a custody event of type `ISSUE`, and triggers the readiness chain: the precinct recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` — the sum of `issued_quantity` over its lots in `ISSUED` or `RETURNED` — and `deployment_readiness`."

    Design: Difficulty/priority_pair_validation_conflict/pp_lot_referential_beats_fiscal_quantity
    """
    sc = _received_lot_of_two_style_election(client)
    validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[1], 600),
                         users.CUSTODIAN),
        ERR_LOT_NOT_FOR_PRECINCT)
    validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[1], 100),
                         users.CUSTODIAN),
        ERR_LOT_NOT_FOR_PRECINCT)
    validate_error(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[0], 600),
                         users.CUSTODIAN),
        ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT)
    assert sc.read_lot()["custody_state"] == LOT_RECEIVED

    lot = validate_success(
        client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_ids[0], 500),
                         users.CUSTODIAN))

    assert lot["custody_state"] == LOT_ISSUED
    assert lot["issued_quantity"] == 500
    assert lot["unused_quantity"] == 0
    assert lot["precinct_id"] == sc.precinct_ids[0]
    assert sc.read_precinct(sc.precinct_ids[0])["ballots_received"] == 500
    assert sc.read_election()["total_ballots_issued"] == 500
    assert sc.read_precinct(sc.precinct_ids[1])["ballots_received"] == 0
    assert sc.read_precinct(sc.precinct_ids[1])["deployment_status"] == READINESS_NOT_READY
