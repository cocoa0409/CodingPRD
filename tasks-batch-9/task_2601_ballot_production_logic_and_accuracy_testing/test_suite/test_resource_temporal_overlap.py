"""Two shared resources booked over time: vendor press lines and a tabulator's calendar.

Press windows are counted as half-open intervals against an aggregate line count, so
back-to-back jobs coexist while a straddling job sees both of its neighbours. A
tabulator's calendar is the opposite shape: a capacity of one over intervals widened
by half an hour on each side and compared closed, so merely touching is a conflict.
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
    ERR_PRESS_CAPACITY_EXCEEDED,
    ERR_UNIT_TEST_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_same_instant, find_by
from test_helpers.constants import (
    ASSET_TAG_1,
    ASSET_TAG_2,
    DECK_CONSUMED,
    DECK_DRAFT,
    JOB_PROOF_PENDING,
    SESSION_END,
    SESSION_PASSED,
    SESSION_SCHEDULED,
    SESSION_START,
    UNIT_LA_PASSED,
)

WINDOW_A_START = "2026-08-10T08:00:00Z"
WINDOW_A_END = "2026-08-12T08:00:00Z"
WINDOW_B_START = "2026-08-12T08:00:00Z"
WINDOW_B_END = "2026-08-14T08:00:00Z"
WINDOW_STRADDLE_START = "2026-08-11T08:00:00Z"
WINDOW_STRADDLE_END = "2026-08-13T08:00:00Z"
WINDOW_D_START = "2026-08-11T08:00:00Z"
WINDOW_D_END = "2026-08-11T20:00:00Z"
WINDOW_E_START = "2026-08-11T12:00:00Z"
WINDOW_E_END = "2026-08-11T18:00:00Z"
WINDOW_F_START = "2026-08-08T08:00:00Z"
WINDOW_F_END = "2026-08-10T08:00:00Z"
WINDOW_G_START = "2026-08-11T20:00:00Z"
WINDOW_G_END = "2026-08-12T08:00:00Z"


def _locked_election_with_a_two_line_vendor(client):
    """STYLES_LOCKED election with S-100 ordered by P-001 and a two-press-line vendor."""
    sc = fx.styles_locked(client)
    fx.add_vendor(sc)
    return sc


def _order(sc, window_start, window_end):
    """Place a 12 500-ballot order over one press window, always presenting the live revision."""
    payload = f.print_job_payload(sc.vendor_id, sc.style_id, sc.style_version(),
                                 quantity_ordered=12500,
                                 press_window_start=window_start,
                                 press_window_end=window_end)
    return sc.client.create_print_job(payload, users.COORDINATOR)


def _active_job_count(sc):
    return validate_success(
        sc.client.get_print_vendor(sc.vendor_id, users.DIRECTOR))["active_job_count"]


# ---- Press lines are counted over half-open windows ----

def test_rt_adjacent_press_windows_do_not_consume_a_second_line(client):
    """Orders that begin exactly when a neighbour ends, on either side, cost no extra press line.

    PRD Section 3.6: "Both windows are half-open — they include their start instant and exclude their end instant — so a job that starts at exactly the instant another ends does not conflict with it."

    Design: Difficulty/resource_temporal_overlap/rt_press_line_capacity_half_open_adjacency
    """
    sc = _locked_election_with_a_two_line_vendor(client)

    first = validate_success(_order(sc, WINDOW_A_START, WINDOW_A_END), expected_status=201)
    later = validate_success(_order(sc, WINDOW_B_START, WINDOW_B_END), expected_status=201)
    earlier = validate_success(_order(sc, WINDOW_F_START, WINDOW_F_END),
                               expected_status=201)

    assert first["status"] == JOB_PROOF_PENDING
    assert_same_instant(later["press_window_start"], WINDOW_A_END,
                        "later job.press_window_start")
    assert_same_instant(earlier["press_window_end"], WINDOW_A_START,
                        "earlier job.press_window_end")
    assert _active_job_count(sc) == 3
    _, meta = validate_paginated(
        sc.client.list_print_jobs(users.COORDINATOR, {"vendor_id": sc.vendor_id}))
    assert meta["total_count"] == 3


def test_rt_a_window_straddling_two_neighbours_exhausts_the_capacity(client):
    """A window that overlaps both scheduled jobs on a non-empty interval reaches the line count.

    PRD Section 3.6: "The proposed job conflicts when the number of the vendor's existing jobs in `PROOF_PENDING`, `PRINTING`, `QC_HOLD`, `QC_PASSED` or `DELIVERED` whose window intersects the proposed window is already equal to or greater than the vendor's `press_line_count`; the rejection is `ERR_PRESS_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rt_press_line_capacity_half_open_adjacency
    """
    sc = _locked_election_with_a_two_line_vendor(client)
    validate_success(_order(sc, WINDOW_A_START, WINDOW_A_END), expected_status=201)
    validate_success(_order(sc, WINDOW_B_START, WINDOW_B_END), expected_status=201)

    validate_error(_order(sc, WINDOW_STRADDLE_START, WINDOW_STRADDLE_END),
                   ERR_PRESS_CAPACITY_EXCEEDED)

    assert _active_job_count(sc) == 2
    _, meta = validate_paginated(
        sc.client.list_print_jobs(users.COORDINATOR, {"vendor_id": sc.vendor_id}))
    assert meta["total_count"] == 2
    assert sc.read_election()["committed_print_cents"] == 0


def test_rt_a_single_overlap_is_legal_and_the_second_is_not(client):
    """One concurrent job is accepted on a two-line vendor and a job inside both is refused.

    PRD Section 3.6: "Because the limit counts overlaps collectively, each individual overlap can be perfectly legal while the collection is not: a two-line vendor accepts a second concurrent job and refuses the third."

    Design: Difficulty/resource_temporal_overlap/rt_press_line_capacity_half_open_adjacency
    """
    sc = _locked_election_with_a_two_line_vendor(client)
    validate_success(_order(sc, WINDOW_A_START, WINDOW_A_END), expected_status=201)

    overlapping = validate_success(_order(sc, WINDOW_D_START, WINDOW_D_END),
                                   expected_status=201)
    assert overlapping["status"] == JOB_PROOF_PENDING

    validate_error(_order(sc, WINDOW_E_START, WINDOW_E_END),
                   ERR_PRESS_CAPACITY_EXCEEDED)

    assert _active_job_count(sc) == 2


def test_rt_a_window_meeting_both_neighbours_at_their_edges_is_accepted(client):
    """A window that starts as one job ends and ends as another ends overlaps only one of them.

    PRD Section 3.6: "Both windows are half-open — they include their start instant and exclude their end instant — so a job that starts at exactly the instant another ends does not conflict with it."

    Design: Difficulty/resource_temporal_overlap/rt_press_line_capacity_half_open_adjacency
    """
    sc = _locked_election_with_a_two_line_vendor(client)
    validate_success(_order(sc, WINDOW_A_START, WINDOW_A_END), expected_status=201)
    validate_success(_order(sc, WINDOW_D_START, WINDOW_D_END), expected_status=201)

    tail = validate_success(_order(sc, WINDOW_G_START, WINDOW_G_END), expected_status=201)

    assert_same_instant(tail["press_window_start"], WINDOW_D_END,
                        "tail job.press_window_start")
    assert_same_instant(tail["press_window_end"], WINDOW_A_END,
                        "tail job.press_window_end")
    assert tail["status"] == JOB_PROOF_PENDING
    assert _active_job_count(sc) == 3


# ---- A tabulator's calendar is booked as a buffered closed interval ----

TOUCH_START = "2026-09-01T19:00:00Z"
TOUCH_END = "2026-09-01T21:00:00Z"
CLEAR_START = "2026-09-01T19:01:00Z"
CLEAR_END = "2026-09-01T21:00:00Z"
NESTED_START = "2026-09-01T16:00:00Z"
NESTED_END = "2026-09-01T17:00:00Z"
EARLY_TOUCH_START = "2026-09-01T12:00:00Z"
EARLY_TOUCH_END = "2026-09-01T13:00:00Z"
EARLY_CLEAR_START = "2026-09-01T11:00:00Z"
EARLY_CLEAR_END = "2026-09-01T12:59:00Z"
DECK_CODES = ("DECK-A", "DECK-B", "DECK-C", "DECK-D")


def _two_units_with_four_decks(client):
    """Issued-paper election with TAB-001 and TAB-002 programmed for S-100 and four draft decks."""
    sc = fx.issued_lot(client)
    fx.add_tabulator(sc, asset_tag=ASSET_TAG_1)
    fx.add_tabulator(sc, asset_tag=ASSET_TAG_2)
    fx.program_unit(sc, tabulator_id=sc.tabulator_ids[0], headers=users.TECHNICIAN)
    fx.program_unit(sc, tabulator_id=sc.tabulator_ids[1], headers=users.TECHNICIAN)
    for deck_code in DECK_CODES:
        fx.add_test_deck(sc, deck_code=deck_code)
    return sc


def _propose(sc, tabulator_index, deck_index, scheduled_start, scheduled_end):
    payload = f.la_session_payload(sc.tabulator_ids[tabulator_index],
                                  sc.deck_ids[deck_index],
                                  scheduled_start=scheduled_start,
                                  scheduled_end=scheduled_end)
    return sc.client.create_la_session(payload, users.TECHNICIAN_2)


def _sessions_of(sc, tabulator_index):
    rows, meta = validate_paginated(
        sc.client.list_la_sessions(users.TECHNICIAN,
                                   {"tabulator_id": sc.tabulator_ids[tabulator_index]}))
    return rows, meta


def _deck_status(sc, deck_index):
    decks, _ = validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))
    return find_by(decks, "id", sc.deck_ids[deck_index])["status"]


def test_rt_buffered_windows_that_merely_touch_are_refused(client):
    """A session starting an hour after another ends still collides at the shared buffer instant.

    PRD Section 3.8: "Because the buffered intervals are closed, two sessions that merely touch at a buffered endpoint **do** conflict: a session ending at noon blocks a session starting at 13:00 exactly, since both buffered intervals contain 12:30."

    Design: Difficulty/resource_temporal_overlap/rt_unit_test_window_buffered_closed_touch_conflict
    """
    sc = _two_units_with_four_decks(client)
    first = validate_success(_propose(sc, 0, 0, SESSION_START, SESSION_END),
                             expected_status=201)
    assert first["status"] == SESSION_SCHEDULED

    validate_error(_propose(sc, 0, 1, TOUCH_START, TOUCH_END),
                   ERR_UNIT_TEST_WINDOW_CONFLICT)

    _, meta = _sessions_of(sc, 0)
    assert meta["total_count"] == 1
    assert _deck_status(sc, 1) == DECK_DRAFT


def test_rt_one_minute_of_buffer_clearance_is_accepted(client):
    """Moving the proposal one minute later separates the buffered intervals and it is accepted.

    PRD Section 3.8: "Each session therefore occupies the **closed** interval running from 30 minutes before its `scheduled_start` to 30 minutes after its `scheduled_end`."

    Design: Difficulty/resource_temporal_overlap/rt_unit_test_window_buffered_closed_touch_conflict
    """
    sc = _two_units_with_four_decks(client)
    validate_success(_propose(sc, 0, 0, SESSION_START, SESSION_END), expected_status=201)

    later = validate_success(_propose(sc, 0, 1, CLEAR_START, CLEAR_END),
                             expected_status=201)

    assert later["status"] == SESSION_SCHEDULED
    assert_same_instant(later["scheduled_start"], CLEAR_START,
                        "later session.scheduled_start")
    _, meta = _sessions_of(sc, 0)
    assert meta["total_count"] == 2


def test_rt_a_window_nested_inside_another_is_refused(client):
    """Capacity is one, so a session wholly inside a booked buffered interval is refused too.

    PRD Section 3.8: "A tabulator can host exactly one session at a time, and the technician needs half an hour on each side of a session to mount and clear the deck."

    Design: Difficulty/resource_temporal_overlap/rt_unit_test_window_buffered_closed_touch_conflict
    """
    sc = _two_units_with_four_decks(client)
    validate_success(_propose(sc, 0, 0, SESSION_START, SESSION_END), expected_status=201)

    validate_error(_propose(sc, 0, 2, NESTED_START, NESTED_END),
                   ERR_UNIT_TEST_WINDOW_CONFLICT)

    _, meta = _sessions_of(sc, 0)
    assert meta["total_count"] == 1
    assert _deck_status(sc, 2) == DECK_DRAFT


def test_rt_the_same_window_on_a_second_unit_is_accepted(client):
    """Exclusivity is scoped to one machine's calendar, not to the election.

    PRD Section 3.8: "The proposed session conflicts when any other session on the same `tabulator_id` — in *any* status, including the terminal `PASSED` and `FAILED` — has a buffered interval that overlaps the proposed buffered interval; the refusal is `ERR_UNIT_TEST_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rt_unit_test_window_buffered_closed_touch_conflict
    """
    sc = _two_units_with_four_decks(client)
    validate_success(_propose(sc, 0, 0, SESSION_START, SESSION_END), expected_status=201)

    twin = validate_success(_propose(sc, 1, 2, SESSION_START, SESSION_END),
                            expected_status=201)

    assert twin["status"] == SESSION_SCHEDULED
    assert twin["tabulator_id"] == sc.tabulator_ids[1]
    assert_same_instant(twin["scheduled_start"], SESSION_START,
                        "twin session.scheduled_start")
    assert_same_instant(twin["scheduled_end"], SESSION_END,
                        "twin session.scheduled_end")
    _, first_meta = _sessions_of(sc, 0)
    _, second_meta = _sessions_of(sc, 1)
    assert first_meta["total_count"] == 1
    assert second_meta["total_count"] == 1


def test_rt_a_passed_session_keeps_holding_its_buffered_slot(client):
    """A finished session does not release the calendar: the touching proposal is still refused.

    PRD Section 3.8: "That completed sessions still occupy the calendar is intentional: a machine's test history is a matter of record and the same slot is not reused."

    Design: Difficulty/resource_temporal_overlap/rt_unit_test_window_buffered_closed_touch_conflict
    """
    sc = _two_units_with_four_decks(client)
    first = validate_success(_propose(sc, 0, 0, SESSION_START, SESSION_END),
                             expected_status=201)
    sc.session_ids.append(first["id"])
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc, headers=users.TECHNICIAN_2)
    session = fx.record_matching_results(sc, headers=users.TECHNICIAN_2)
    assert session["status"] == SESSION_PASSED
    assert session["discrepancy_count"] == 0
    assert _deck_status(sc, 0) == DECK_CONSUMED
    assert sc.read_tabulator(sc.tabulator_ids[0])["program_status"] == UNIT_LA_PASSED

    validate_error(_propose(sc, 0, 3, EARLY_TOUCH_START, EARLY_TOUCH_END),
                   ERR_UNIT_TEST_WINDOW_CONFLICT)
    accepted = validate_success(_propose(sc, 0, 3, EARLY_CLEAR_START, EARLY_CLEAR_END),
                                expected_status=201)

    assert accepted["status"] == SESSION_SCHEDULED
    assert_same_instant(accepted["scheduled_end"], EARLY_CLEAR_END,
                        "accepted session.scheduled_end")
    rows, meta = _sessions_of(sc, 0)
    assert meta["total_count"] == 2
    assert find_by(rows, "id", sc.session_ids[0])["status"] == SESSION_PASSED
