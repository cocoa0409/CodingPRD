"""A second residency chained to a finished one, and a row waived out of the sums."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_OBLIGATION_NOT_PENDING,
    ERR_PREDECESSOR_NOT_COMPLETED,
    ERR_RESIDENCY_NOT_FOUND,
    NON_EXISTENT_UUID,
    check_in,
    complete_all_trainings,
    complete_residency,
    create_applicant,
    create_residency,
    funder_outcome_report,
    get_success_data,
    log_obligation_completion,
    make_obligation_progress_payload,
    make_residency_payload,
    obligation_of_type,
    obligations_for,
    read_cycle,
    refresh_residency,
    schedule_residency,
    set_clock,
    setup_open_cycle,
    validate_error,
    validate_paginated,
    waive_obligation,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"


def _finished_artist_and_a_bystander(api):
    """Ada's first residency is over; Kell's has not begun."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    ada = create_applicant(api)
    kell = create_applicant(api)
    first = create_residency(api, cycle, ada)
    theirs = create_residency(api, cycle, kell)
    for residency in (first, theirs):
        schedule_residency(api, residency, SESSION_START, 8)
    complete_all_trainings(api, first)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, first)
    set_clock(api, f"{SESSION_END}T09:00:00Z")
    assert complete_residency(api, first)["status"] == "COMPLETED"
    assert refresh_residency(api, theirs)["status"] == "SCHEDULED"
    return cycle, ada, kell, first, theirs


def _chain(api, cycle, applicant, predecessor_id):
    """The direct-creation call carrying a predecessor link, as an admin makes it."""
    return api.create_residency(
        make_residency_payload(
            cycle.cycle_id,
            applicant.applicant_id,
            cycle.discipline_id("SCULPT"),
            predecessor_residency_id=predecessor_id,
        ),
        ADMIN_HEADERS,
    )


def test_the_follow_on_residency_needs_no_new_application(api):
    """A chained residency starts exactly where a directly created one does.

    PRD: "A directly created residency starts in `status` `SCHEDULED` and
    `compliance_status` `TRAINING_PENDING`, with `discipline_code` copied from the
    named discipline, `stipend_basis` `PROVISIONAL` and `stipend_total_cents` 0."

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, ada, _kell, first, _theirs = _finished_artist_and_a_bystander(api)

    chained = get_success_data(_chain(api, cycle, ada, first.residency_id), 201)

    assert chained["predecessor_residency_id"] == first.residency_id
    assert chained["application_id"] is None
    assert chained["status"] == "SCHEDULED"
    assert chained["compliance_status"] == "TRAINING_PENDING"
    assert chained["stipend_basis"] == "PROVISIONAL"


def test_the_chain_is_walkable_in_reverse(api):
    """The predecessor filter finds the residency that names it.

    PRD: "Residencies can be listed filtered by `cycle_id`, `application_id`,
    `applicant_id`, `predecessor_residency_id`, `status` or `compliance_status`."

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, ada, _kell, first, _theirs = _finished_artist_and_a_bystander(api)
    chained = get_success_data(_chain(api, cycle, ada, first.residency_id), 201)

    rows, meta = validate_paginated(
        api.list_residencies(
            ADMIN_HEADERS, {"predecessor_residency_id": first.residency_id}
        )
    )

    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [chained["id"]]


def test_a_predecessor_that_is_merely_scheduled_is_refused(api):
    """The right artist and the wrong status still fail.

    PRD: "When `predecessor_residency_id` is supplied it must name a residency
    whose `status` is `COMPLETED` and whose `applicant_id` equals the new
    residency's `applicant_id` — the follow-on chain is self-referential and
    strictly per artist"

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, ada, _kell, first, _theirs = _finished_artist_and_a_bystander(api)
    chained = get_success_data(_chain(api, cycle, ada, first.residency_id), 201)
    assert chained["status"] == "SCHEDULED"

    validate_error(
        _chain(api, cycle, ada, chained["id"]), ERR_PREDECESSOR_NOT_COMPLETED
    )


def test_a_finished_residency_of_another_artist_is_refused_identically(api):
    """The right status and the wrong artist share the same code.

    PRD: "either violation is `ERR_PREDECESSOR_NOT_COMPLETED` (HTTP 422)"

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, _ada, kell, first, _theirs = _finished_artist_and_a_bystander(api)

    validate_error(
        _chain(api, cycle, kell, first.residency_id), ERR_PREDECESSOR_NOT_COMPLETED
    )

    _rows, meta = validate_paginated(
        api.list_residencies(
            ADMIN_HEADERS, {"predecessor_residency_id": first.residency_id}
        )
    )
    assert meta["total_count"] == 0


def test_an_unresolvable_predecessor_outranks_the_state_and_owner_checks(api):
    """Existence is settled before anything else about the reference is examined.

    PRD: "Foreign keys supplied in a request body are resolved by the same rule,
    using the same catalogue of not-found codes, in the order in which this
    document declares the fields of that request."

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, _ada, kell, _first, _theirs = _finished_artist_and_a_bystander(api)

    validate_error(_chain(api, cycle, kell, NON_EXISTENT_UUID), ERR_RESIDENCY_NOT_FOUND)


def test_the_link_is_optional_and_only_the_linked_ones_are_counted(api):
    """One residency of the three names a predecessor, and the report says so.

    PRD: "`follow_on_count` is the number of residencies whose
    `predecessor_residency_id` is not null."

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, ada, _kell, first, theirs = _finished_artist_and_a_bystander(api)
    assert refresh_residency(api, theirs)["predecessor_residency_id"] is None
    assert refresh_residency(api, first)["predecessor_residency_id"] is None

    get_success_data(_chain(api, cycle, ada, first.residency_id), 201)

    assert funder_outcome_report(api, cycle.cycle_id)["follow_on_count"] == 1


def test_the_follow_on_counts_as_a_fresh_award_on_the_slot_ledger(api):
    """Three residencies now hold slots, the finished one included.

    PRD: "`slots_filled_count` is the number of residencies of the cycle in those
    same four statuses, and `slots_open_count` is the cohort target less the filled
    count, floored at zero so it never reports a negative."

    Design: Corner/endpoints/follow_on_residency_links_only_to_a_completed_predecessor_of_the_same_artist
    """
    cycle, ada, _kell, first, _theirs = _finished_artist_and_a_bystander(api)
    before = read_cycle(api, cycle.cycle_id)
    assert before["slots_filled_count"] == 2

    get_success_data(_chain(api, cycle, ada, first.residency_id), 201)

    after = read_cycle(api, cycle.cycle_id)
    assert after["slots_filled_count"] == 3
    assert after["slots_open_count"] == after["cohort_target_size"] - 3
    assert after["version"] == before["version"] + 1


WORKSHOP = "COMMUNITY_WORKSHOP"
WAIVED_REASON = "venue closed for repairs"
FIRST_ATTENDANCE = 25


def _partly_done_workshop_row(api):
    """An eight-week resident who has run one of their two required workshops."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    assert refresh_residency(api, residency)["obligations_required_total"] == 5
    workshop = obligation_of_type(api, residency.residency_id, WORKSHOP)
    assert workshop["required_count"] == 2
    logged = log_obligation_completion(api, workshop["id"], FIRST_ATTENDANCE)
    assert logged["status"] == "PENDING"
    assert logged["completed_count"] == 1
    return residency, logged


def test_the_waiver_records_its_reason_and_keeps_the_rows_own_tallies(api):
    """The row remembers the workshop it did run, even once it is excused.

    PRD: "`WAIVE` requires the residency's `status` to be `SCHEDULED`,
    `IN_RESIDENCE` or `WITHDRAWN`, records the `waived_reason`, and moves the row
    `PENDING → WAIVED`."

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    _residency, logged = _partly_done_workshop_row(api)

    waived = waive_obligation(api, logged["id"], WAIVED_REASON)

    assert waived["status"] == "WAIVED"
    assert waived["waived_reason"] == WAIVED_REASON
    assert waived["completed_count"] == 1
    assert waived["total_attendance"] == FIRST_ATTENDANCE


def test_the_whole_row_leaves_the_denominator(api):
    """A required count of two goes with the row, not one event at a time.

    PRD: "`obligations_required_total` is the sum of `required_count` over the
    residency's obligations whose status is anything other than `WAIVED`"

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, logged = _partly_done_workshop_row(api)

    waive_obligation(api, logged["id"], WAIVED_REASON)

    assert refresh_residency(api, residency)["obligations_required_total"] == 3


def test_the_numerator_leaves_along_with_it(api):
    """The completion already logged stops counting once its row is excused.

    PRD: "`obligations_completed_total` is the sum of `completed_count` over the
    same set; and `obligations_breached_count` counts only the rows in `BREACHED`."

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, logged = _partly_done_workshop_row(api)
    assert refresh_residency(api, residency)["obligations_completed_total"] == 1

    waive_obligation(api, logged["id"], WAIVED_REASON)

    settled = refresh_residency(api, residency)
    assert settled["obligations_completed_total"] == 0
    assert settled["obligations_breached_count"] == 0


def test_the_waiver_advances_both_versions(api):
    """One action, two rows moved, one version each.

    PRD: "Both actions recompute the residency's three obligation counters and
    advance both the obligation's and the residency's `version` by 1."

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, logged = _partly_done_workshop_row(api)
    before = refresh_residency(api, residency)

    waived = waive_obligation(api, logged["id"], WAIVED_REASON)

    assert waived["version"] == logged["version"] + 1
    assert refresh_residency(api, residency)["version"] == before["version"] + 1


def test_the_waived_row_is_out_of_the_working_set_but_not_deleted(api):
    """Excusing an obligation is not the same as removing it.

    PRD: "Either way the obligation must be in `PENDING`; a row already
    `SATISFIED`, `WAIVED` or `BREACHED` is `ERR_OBLIGATION_NOT_PENDING` (HTTP
    409)."

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, logged = _partly_done_workshop_row(api)
    waive_obligation(api, logged["id"], WAIVED_REASON)

    validate_error(
        api.update_obligation_progress(
            logged["id"],
            make_obligation_progress_payload("LOG_COMPLETION", attendance=10),
            ADMIN_HEADERS,
        ),
        ERR_OBLIGATION_NOT_PENDING,
    )

    _rows, meta = validate_paginated(
        api.list_obligations(ADMIN_HEADERS, {"residency_id": residency.residency_id})
    )
    assert meta["total_count"] == 4


def test_a_waived_row_is_never_among_the_breached_ones(api):
    """Completion breaches the three untouched rows and leaves the excused one alone.

    PRD: "Every obligation of the residency still in `PENDING` whose
    `completed_count` is below its `required_count` moves `PENDING → BREACHED`,
    each advancing its own `version` by 1, and `obligations_breached_count` is
    recomputed."

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, logged = _partly_done_workshop_row(api)
    waive_obligation(api, logged["id"], WAIVED_REASON)
    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, residency)
    set_clock(api, f"{SESSION_END}T09:00:00Z")

    finished = complete_residency(api, residency)

    assert finished["obligations_breached_count"] == 3
    statuses = {
        row["obligation_type"]: row["status"]
        for row in obligations_for(api, residency.residency_id)
    }
    assert statuses[WORKSHOP] == "WAIVED"
    assert sorted(statuses.values()) == ["BREACHED", "BREACHED", "BREACHED", "WAIVED"]


def test_a_breached_row_cannot_be_waived_after_the_fact(api):
    """Once the session closes the excuse comes too late.

    PRD: "a row already `SATISFIED`, `WAIVED` or `BREACHED` is
    `ERR_OBLIGATION_NOT_PENDING` (HTTP 409)"

    Design: Corner/endpoints/waiving_an_obligation_removes_it_from_both_residency_sums
    """
    residency, _logged = _partly_done_workshop_row(api)
    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, residency)
    set_clock(api, f"{SESSION_END}T09:00:00Z")
    complete_residency(api, residency)
    breached = obligation_of_type(api, residency.residency_id, "OPEN_STUDIO")
    assert breached["status"] == "BREACHED"

    validate_error(
        api.update_obligation_progress(
            breached["id"],
            make_obligation_progress_payload("WAIVE", waived_reason="too late"),
            ADMIN_HEADERS,
        ),
        ERR_OBLIGATION_NOT_PENDING,
    )
