"""One scheduling call, and every derived figure already answered in the same breath."""

from test_helpers import (
    assert_cycle_slot_ledger,
    assert_cycle_stipend_ledger,
    create_international_applicant,
    create_residency,
    obligations_for,
    read_cycle,
    read_residency,
    schedule_residency,
    setup_open_cycle,
    visa_case_for,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_WEEKS = 8
SESSION_END = "2026-12-27"
AWARD_CENTS = 560000
UNCOMMITTED_CENTS = 19440000
SLOTS_FILLED = 1
SLOTS_OPEN = 9
REQUIRED_EVENTS = 5
OBLIGATION_ROWS = 4
BACKLOG_DAYS = 21
FILING_DEADLINE = "2026-07-14"
EARLIEST_ENTRY = "2026-10-03"
SHORT_WEEKS = 4
SHORT_END = "2026-11-29"
SHORT_AWARD_CENTS = 280000
SHORT_UNCOMMITTED_CENTS = 19720000
SHORT_REQUIRED_EVENTS = 4


def _invited_international_residency(api):
    """An invited French resident with a visa case open and no calendar yet."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    artist = create_international_applicant(api)
    residency = create_residency(api, cycle, artist)
    assert residency.residency["status"] == "SCHEDULED"
    assert residency.residency["stipend_total_cents"] == 0
    assert residency.residency["visa_required"] is True
    return cycle, artist, residency


def test_the_calendar_is_already_derived_in_the_answer(api):
    """The end date arrives with the response, not on some later pass.

    PRD: "It derives `session_end_date` as the start date plus the session length in
    weeks multiplied by seven days, minus one day, so that the session is a closed
    inclusive interval — an eight-week session beginning on a Monday ends on a Sunday
    fifty-five days later."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)

    scheduled = schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    assert scheduled["session_start_date"] == SESSION_START
    assert scheduled["session_length_weeks"] == SESSION_WEEKS
    assert scheduled["session_end_date"] == SESSION_END
    assert scheduled["required_training_types"] == [
        "EQUIPMENT_WELDING",
        "SAFETY_ORIENTATION",
    ]


def test_the_money_is_derived_in_the_same_body(api):
    """Eight weeks at seventy thousand a week, priced before the caller asks again.

    PRD: "It is the residency's `stipend_weekly_rate_cents` multiplied by the planned
    week count, so the cycle commits the whole award up front."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)

    scheduled = schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    assert scheduled["stipend_total_cents"] == AWARD_CENTS
    assert scheduled["stipend_basis"] == "PROVISIONAL"


def test_the_obligation_counters_come_back_with_the_calendar(api):
    """Three flat commitments plus two workshops, counted in the same response.

    PRD: "An eight-week residency therefore owes two workshops and carries four
    obligation rows totalling five required events"

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)

    scheduled = schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    assert scheduled["obligations_required_total"] == REQUIRED_EVENTS
    assert scheduled["obligations_completed_total"] == 0
    assert scheduled["obligations_breached_count"] == 0


def test_the_obligation_rows_are_readable_immediately(api):
    """The rows exist the instant the call returns, not eventually.

    PRD: "Every provisioned row starts with `status` `PENDING`, `completed_count` 0,
    `total_attendance` 0 and a `due_date` equal to the residency's `session_end_date`
    at the moment of provisioning."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)
    schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    rows = obligations_for(api, residency.residency_id)

    assert len(rows) == OBLIGATION_ROWS
    assert {row["status"] for row in rows} == {"PENDING"}
    assert {row["completed_count"] for row in rows} == {0}
    assert {row["total_attendance"] for row in rows} == {0}
    assert {row["due_date"] for row in rows} == {SESSION_END}


def test_the_cycle_ledgers_moved_in_lock_step(api):
    """Money and slots on the parent are consistent on the very next read.

    PRD: "All of these figures are recomputed from their inputs rather than patched
    incrementally, so a cascade that changes several rows at once leaves them
    consistent."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    cycle, _artist, residency = _invited_international_residency(api)

    schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    settled = read_cycle(api, cycle.cycle_id)
    assert_cycle_stipend_ledger(settled, AWARD_CENTS, UNCOMMITTED_CENTS)
    assert_cycle_slot_ledger(settled, SLOTS_FILLED, SLOTS_OPEN)


def test_the_visa_timeline_is_derived_on_the_other_entity_too(api):
    """The sponsorship dates are waiting on the case as soon as the residency has dates.

    PRD: "`filing_deadline_date` is the residency's `session_start_date` minus a lead
    time of 90 days plus `backlog_days`: 135 days for a high-volume citizenship, 111
    days otherwise. A session starting on 2 November 2026 therefore has a filing
    deadline of 20 June 2026 for an Indian citizen and 14 July 2026 for a French one."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)
    before = visa_case_for(api, residency.residency_id)
    assert before["status"] == "INITIATED"
    assert before["backlog_days"] == BACKLOG_DAYS
    assert before["filing_deadline_date"] is None

    schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    case = visa_case_for(api, residency.residency_id)
    assert case["case_type"] == "B1_SHORT_TERM"
    assert case["backlog_days"] == BACKLOG_DAYS
    assert case["filing_deadline_date"] == FILING_DEADLINE
    assert case["earliest_entry_date"] == EARLIEST_ENTRY


def test_a_re_read_is_redundant_rather_than_corrective(api):
    """Fetching the residency again changes nothing and moves no counter.

    PRD: "The residency's `version` advances by 1, the cycle's `version` advances by
    1, and the visa case's `version` advances by 1 when one exists."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    _cycle, _artist, residency = _invited_international_residency(api)
    born = residency.residency["version"]

    scheduled = schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    again = read_residency(api, residency.residency_id)
    assert scheduled["version"] == born + 1
    assert again["version"] == scheduled["version"]
    for field in (
        "session_end_date",
        "session_length_weeks",
        "stipend_total_cents",
        "stipend_basis",
        "obligations_required_total",
        "obligations_completed_total",
        "required_training_types",
    ):
        assert again[field] == scheduled[field]


def test_a_correction_replaces_and_releases_in_the_one_call(api):
    """The shorter calendar hands the difference back to the pool as it lands.

    PRD: "It re-bases `stipend_total_cents` to the provisional award for the confirmed
    length and recomputes the cycle's stipend ledger."

    Design: Corner/consistency_model/scheduling_returns_every_derived_field_in_the_same_response
    """
    cycle, _artist, residency = _invited_international_residency(api)
    schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    corrected = schedule_residency(api, residency, SESSION_START, SHORT_WEEKS)

    assert corrected["session_end_date"] == SHORT_END
    assert corrected["stipend_total_cents"] == SHORT_AWARD_CENTS
    assert corrected["obligations_required_total"] == SHORT_REQUIRED_EVENTS
    settled = read_cycle(api, cycle.cycle_id)
    assert_cycle_stipend_ledger(settled, SHORT_AWARD_CENTS, SHORT_UNCOMMITTED_CENTS)
    rows = obligations_for(api, residency.residency_id)
    assert len(rows) == OBLIGATION_ROWS
    assert {row["due_date"] for row in rows} == {SHORT_END}
