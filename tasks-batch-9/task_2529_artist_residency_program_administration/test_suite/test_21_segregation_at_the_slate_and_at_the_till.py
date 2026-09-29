"""Who may not lock the slate they judged, and who may not pay the schedule they wrote."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_CHAIR_NOT_ELIGIBLE,
    ERR_SEGREGATION_OF_DUTIES,
    FINANCE_PAYER_HEADERS,
    FINANCE_PAYER_USER_ID,
    FINANCE_REVERSER_HEADERS,
    FINANCE_REVERSER_USER_ID,
    FINANCE_SCHEDULER_HEADERS,
    FINANCE_SCHEDULER_USER_ID,
    assert_money_equals,
    assert_score_equals,
    assign_and_score,
    assign_panelist,
    check_in,
    complete_all_trainings,
    create_chair,
    create_panelist,
    declare_conflict,
    disbursements_for,
    generate_stipend_schedule,
    get_success_data,
    make_settlement_payload,
    make_stipend_schedule_payload,
    read_application,
    read_cycle,
    refresh_application,
    refresh_residency,
    scheduled_disbursements_for,
    set_clock,
    setup_panel_review_cycle,
    setup_residency_ready_for_payment,
    setup_scheduled_residency,
    validate_error,
)

CLOCK = "2026-08-01T00:00:00Z"
ALL_EIGHTS_TOTAL = 80.00


def _cycle_judged_by_an_eligible_chair(api):
    """One scored application, judged by a chair-eligible reviewer and a plain one."""
    cycle, apps = setup_panel_review_cycle(api, clock=CLOCK, applicant_count=1)
    judging_chair = create_panelist(api, chair_eligible=True)
    plain_reviewer = create_panelist(api)
    outsider = create_chair(api)
    assign_and_score(api, apps[0], judging_chair)
    assign_and_score(api, apps[0], plain_reviewer)
    assert refresh_application(api, apps[0])["status"] == "SCORED"
    return cycle, apps[0], judging_chair, plain_reviewer, outsider


def _lock(api, cycle, panelist):
    """The lock call as the named reviewer's chair identity issues it."""
    return api.lock_slate(cycle.cycle_id, panelist.chair_headers)


def test_the_chair_who_reviewed_the_cycle_may_not_lock_it(api):
    """A reviewer wearing the chair's hat cannot adjudicate what they scored.

    PRD: "First, the acting chair locking a cycle's slate must not be the panelist
    on **any** panel assignment in that cycle whose status is `SCORED` or
    `CONFLICT_DECLARED` — a chair who merely holds unscored assignments is still
    allowed to lock."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, judging_chair, _plain, _outsider = _cycle_judged_by_an_eligible_chair(api)

    validate_error(_lock(api, cycle, judging_chair), ERR_SEGREGATION_OF_DUTIES)

    assert read_cycle(api, cycle.cycle_id)["status"] == "PANEL_REVIEW"
    assert read_application(api, app.application_id)["status"] == "SCORED"


def test_nothing_but_the_identity_stood_in_the_way(api):
    """The cycle was ready and the score was well clear of the floor.

    PRD: "Finally the cycle's `panel_review_complete` flag must be true, meaning at
    least one application has reached `SCORED` and none remains in `PANEL_REVIEW`;
    otherwise the answer is `ERR_PANEL_REVIEW_INCOMPLETE` (HTTP 409)."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, judging_chair, _plain, _outsider = _cycle_judged_by_an_eligible_chair(api)
    held = read_cycle(api, cycle.cycle_id)
    scored = read_application(api, app.application_id)
    assert held["panel_review_complete"] is True
    assert_score_equals(scored["final_panel_score"], ALL_EIGHTS_TOTAL, "final panel score")
    assert scored["final_panel_score"] > held["slate_min_score"]

    validate_error(_lock(api, cycle, judging_chair), ERR_SEGREGATION_OF_DUTIES)


def test_an_untainted_chair_locks_the_very_same_cycle(api):
    """The identical call from a chair who never reviewed here goes through.

    PRD: "Locking a cycle's slate is a single chair action that decides the fate of
    every scored application at once, drives the cycle `PANEL_REVIEW →
    SLATE_LOCKED`, and takes no request body."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, judging_chair, _plain, outsider = _cycle_judged_by_an_eligible_chair(api)
    validate_error(_lock(api, cycle, judging_chair), ERR_SEGREGATION_OF_DUTIES)

    locked = get_success_data(_lock(api, cycle, outsider))

    assert locked["status"] == "SLATE_LOCKED"
    assert read_application(api, app.application_id)["status"] == "OFFERED"


def test_the_bar_keys_on_reviewing_and_not_on_being_seated(api):
    """A chair holding an untouched assignment in the cycle may still lock it.

    PRD: "a chair who merely holds unscored assignments is still allowed to lock"

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, _judging, _plain, outsider = _cycle_judged_by_an_eligible_chair(api)
    seated = assign_panelist(api, app, outsider)
    assert seated["status"] == "ASSIGNED"
    assert seated["panelist_total_100"] is None

    locked = get_success_data(_lock(api, cycle, outsider))

    assert locked["status"] == "SLATE_LOCKED"


def test_a_declared_conflict_taints_the_chair_just_as_reviewing_does(api):
    """No score was ever recorded, and the assignment still bars the chair.

    PRD: "The acting chair's `X-User-ID` must not be the `panelist_id` of **any**
    panel assignment in the cycle whose status is `SCORED` or `CONFLICT_DECLARED` —
    a chair who reviewed or declared a conflict in the cycle cannot also adjudicate
    its outcome — and a violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, _judging, _plain, outsider = _cycle_judged_by_an_eligible_chair(api)
    seated = assign_panelist(api, app, outsider)
    declared = declare_conflict(
        api,
        seated["id"],
        outsider,
        conflict_type="SAME_AFFILIATION",
        detail="we share a studio building",
    )
    assert declared["status"] == "CONFLICT_DECLARED"
    assert declared["panelist_total_100"] is None

    validate_error(_lock(api, cycle, outsider), ERR_SEGREGATION_OF_DUTIES)

    assert read_application(api, app.application_id)["status"] == "SCORED"


def test_the_bar_is_drawn_per_cycle_and_not_per_person(api):
    """Reviewing one competition leaves a chair free to adjudicate another.

    PRD: "a chair who reviewed or declared a conflict in the cycle cannot also
    adjudicate its outcome"

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, _app, _judging, _plain, outsider = _cycle_judged_by_an_eligible_chair(api)
    elsewhere, other_apps = setup_panel_review_cycle(api, clock=CLOCK, applicant_count=1)
    reviewed_there = assign_and_score(api, other_apps[0], outsider)
    assert reviewed_there["status"] == "SCORED"

    locked = get_success_data(_lock(api, cycle, outsider))

    assert locked["status"] == "SLATE_LOCKED"
    assert read_cycle(api, elsewhere.cycle_id)["status"] == "PANEL_REVIEW"


def test_chair_eligibility_is_a_separate_and_earlier_check(api):
    """A reviewer who is barred twice over hears about the eligibility first.

    PRD: "The acting chair's backing panelist row must carry `chair_eligible` set to
    true, or `ERR_CHAIR_NOT_ELIGIBLE` (HTTP 403)."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, _app, _judging, plain_reviewer, _outsider = _cycle_judged_by_an_eligible_chair(
        api
    )
    assert plain_reviewer.panelist["chair_eligible"] is False

    validate_error(_lock(api, cycle, plain_reviewer), ERR_CHAIR_NOT_ELIGIBLE)

    assert read_cycle(api, cycle.cycle_id)["status"] == "PANEL_REVIEW"


def test_the_refusal_is_not_a_partial_lock(api):
    """No allocation ran, so neither the reserve nor any version moved.

    PRD: "`alumni_reserved_slots` is the cycle's `alumni_reserve_pct` multiplied by
    its `cohort_target_size`, rounded **up** to the next whole slot."

    Design: Corner/rbac/a_chair_who_reviewed_in_the_cycle_cannot_lock_its_slate
    """
    cycle, app, judging_chair, _plain, _outsider = _cycle_judged_by_an_eligible_chair(api)
    before_cycle = read_cycle(api, cycle.cycle_id)
    before_app = read_application(api, app.application_id)

    validate_error(_lock(api, cycle, judging_chair), ERR_SEGREGATION_OF_DUTIES)

    after_cycle = read_cycle(api, cycle.cycle_id)
    assert after_cycle["version"] == before_cycle["version"]
    assert after_cycle["alumni_reserved_slots"] == before_cycle["alumni_reserved_slots"]
    assert read_application(api, app.application_id)["version"] == before_app["version"]
    _listed = get_success_data(api.get_cycle(cycle.cycle_id, ADMIN_HEADERS))
    assert _listed["slate_ready_count"] == before_cycle["slate_ready_count"]


SESSION_START = "2026-11-02"
PERIOD_GROSS = 140000
PAY_DATE = "2026-11-16"
LATER_PAY_DATE = "2026-11-30"


def _schedule_written_by_the_first_officer(api):
    """A checked-in resident whose four payment periods were laid out by fin-01."""
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(api)
    assert [row["gross_cents"] for row in rows] == [PERIOD_GROSS] * 4
    assert refresh_residency(api, residency)["status"] == "IN_RESIDENCE"
    return residency, rows


def _settle(api, disbursement_id, headers, action="PAY", **extra):
    """The settlement call as whichever finance officer the caller names."""
    return api.settle_disbursement(
        disbursement_id, make_settlement_payload(action, **extra), headers
    )


def test_the_officer_who_wrote_the_schedule_may_not_pay_it(api):
    """The calendar's author is refused on the money it lays out.

    PRD: "The acting officer's `X-User-ID` must also differ from the row's
    `scheduled_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403): whoever
    generated the schedule may not pay it."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    residency, rows = _schedule_written_by_the_first_officer(api)
    first = rows[0]
    assert first["period_index"] == 1

    validate_error(
        _settle(api, first["id"], FINANCE_SCHEDULER_HEADERS, paid_on_date=PAY_DATE),
        ERR_SEGREGATION_OF_DUTIES,
    )

    held = get_success_data(api.get_disbursement(first["id"], FINANCE_REVERSER_HEADERS))
    assert held["status"] == "SCHEDULED"
    assert held["version"] == first["version"]
    assert refresh_residency(api, residency)["stipend_paid_gross_cents"] == 0


def test_the_bar_reads_the_operator_id_recorded_on_the_row(api):
    """Every row of the generation remembers who wrote it, and none remembers a payer.

    PRD: "`paid_on_date` and `paid_by_user_id` null, `tax_form_type` copied from the
    residency as it stands at generation time, and `scheduled_by_user_id` set to the
    acting officer's `X-User-ID` — an opaque operator identifier, not the id of any
    entity row."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    _residency, rows = _schedule_written_by_the_first_officer(api)

    assert [row["scheduled_by_user_id"] for row in rows] == [
        FINANCE_SCHEDULER_USER_ID
    ] * 4
    assert [row["paid_by_user_id"] for row in rows] == [None] * 4
    validate_error(
        _settle(api, rows[0]["id"], FINANCE_SCHEDULER_HEADERS, paid_on_date=PAY_DATE),
        ERR_SEGREGATION_OF_DUTIES,
    )


def test_a_different_officer_pays_the_identical_row(api):
    """Nothing about the request changes except the identity behind it.

    PRD: "When the residency's `tax_form_type` is `W9` the `withholding_rate` is
    0.00."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    _residency, rows = _schedule_written_by_the_first_officer(api)

    paid = get_success_data(
        _settle(api, rows[0]["id"], FINANCE_PAYER_HEADERS, paid_on_date=PAY_DATE)
    )

    assert paid["status"] == "PAID"
    assert paid["paid_by_user_id"] == FINANCE_PAYER_USER_ID
    assert paid["tax_form_type"] == "W9"
    assert_money_equals(paid["gross_cents"], PERIOD_GROSS, "gross")
    assert_money_equals(paid["withholding_cents"], 0, "withholding")
    assert_money_equals(paid["net_cents"], PERIOD_GROSS, "net")


def test_the_second_bar_reads_a_different_field(api):
    """The officer who was allowed to pay is the one now refused the reversal.

    PRD: "`REVERSE` drives `PAID → REVERSED` and is the second segregation point:
    the acting officer's `X-User-ID` must differ from the row's `paid_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    _residency, rows = _schedule_written_by_the_first_officer(api)
    paid = get_success_data(
        _settle(api, rows[0]["id"], FINANCE_PAYER_HEADERS, paid_on_date=PAY_DATE)
    )
    assert paid["paid_by_user_id"] == FINANCE_PAYER_USER_ID

    validate_error(
        _settle(
            api,
            rows[0]["id"],
            FINANCE_PAYER_HEADERS,
            action="REVERSE",
            reason="the bank returned the transfer",
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )

    undone = get_success_data(
        _settle(
            api,
            rows[0]["id"],
            FINANCE_SCHEDULER_HEADERS,
            action="REVERSE",
            reason="the bank returned the transfer",
        )
    )
    assert undone["status"] == "REVERSED"


def test_the_reversal_restores_the_ledgers_without_erasing_the_row(api):
    """The money comes back out of the totals and stays on the row for the tax year.

    PRD: "The row keeps its `gross_cents`, `withholding_cents`, `net_cents`,
    `withholding_rate`, `cumulative_taxable_cents` and `paid_on_date` for
    tax-reporting history, but it is excluded from both residency ledgers, which are
    recomputed without it and thereby restored to exactly their pre-payment values."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    residency, rows = _schedule_written_by_the_first_officer(api)
    get_success_data(
        _settle(api, rows[0]["id"], FINANCE_PAYER_HEADERS, paid_on_date=PAY_DATE)
    )
    assert refresh_residency(api, residency)["stipend_paid_gross_cents"] == PERIOD_GROSS

    undone = get_success_data(
        _settle(
            api,
            rows[0]["id"],
            FINANCE_SCHEDULER_HEADERS,
            action="REVERSE",
            reason="the bank returned the transfer",
        )
    )

    ledger = refresh_residency(api, residency)
    assert_money_equals(ledger["stipend_paid_gross_cents"], 0, "paid gross")
    assert_money_equals(ledger["withholding_to_date_cents"], 0, "withholding to date")
    assert undone["status"] == "REVERSED"
    assert_money_equals(undone["gross_cents"], PERIOD_GROSS, "gross kept for history")
    assert undone["paid_on_date"] == PAY_DATE


def test_every_row_of_the_one_generation_is_closed_to_its_writer(api):
    """The bar sits on each row, and one call wrote the same author onto all four.

    PRD: "Second, the finance officer marking a disbursement paid must not be the
    finance officer recorded in that row's `scheduled_by_user_id`."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    _residency, rows = _schedule_written_by_the_first_officer(api)
    get_success_data(
        _settle(api, rows[0]["id"], FINANCE_PAYER_HEADERS, paid_on_date=PAY_DATE)
    )

    validate_error(
        _settle(
            api, rows[1]["id"], FINANCE_SCHEDULER_HEADERS, paid_on_date=LATER_PAY_DATE
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )

    second = get_success_data(
        _settle(
            api, rows[1]["id"], FINANCE_REVERSER_HEADERS, paid_on_date=LATER_PAY_DATE
        )
    )
    assert second["period_index"] == 2
    assert second["status"] == "PAID"
    assert second["paid_by_user_id"] == FINANCE_REVERSER_USER_ID


def test_regenerating_under_another_officer_moves_the_bar_with_it(api):
    """The refreshed calendar carries a new author, and the old one may now pay.

    PRD: "On a regeneration every existing `SCHEDULED` row of the residency is first
    driven `SCHEDULED → VOIDED`, while rows in `PAID` and `REVERSED` are left
    completely untouched."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    _cycle, _applicant, residency = setup_scheduled_residency(
        api, session_start_date=SESSION_START
    )
    first_pass = generate_stipend_schedule(api, residency)
    assert [row["scheduled_by_user_id"] for row in first_pass] == [
        FINANCE_SCHEDULER_USER_ID
    ] * 4
    current = refresh_residency(api, residency)
    redone = get_success_data(
        api.generate_stipend_schedule(
            residency.residency_id,
            make_stipend_schedule_payload(current["version"]),
            FINANCE_PAYER_HEADERS,
        ),
        201,
    )
    assert [row["scheduled_by_user_id"] for row in redone] == [
        FINANCE_PAYER_USER_ID
    ] * 4
    stale = [
        row
        for row in disbursements_for(api, residency.residency_id)
        if row["status"] == "VOIDED"
    ]
    assert len(stale) == 4
    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, residency)
    live = scheduled_disbursements_for(api, residency.residency_id)
    period_one = [row for row in live if row["period_index"] == 1][0]

    validate_error(
        _settle(api, period_one["id"], FINANCE_PAYER_HEADERS, paid_on_date=PAY_DATE),
        ERR_SEGREGATION_OF_DUTIES,
    )

    paid = get_success_data(
        _settle(api, period_one["id"], FINANCE_SCHEDULER_HEADERS, paid_on_date=PAY_DATE)
    )
    assert paid["status"] == "PAID"
    assert paid["paid_by_user_id"] == FINANCE_SCHEDULER_USER_ID


def test_the_void_action_carries_no_identity_bar(api):
    """Cancelling a row is not moving money, so the author may do it.

    PRD: "`VOID` drives `SCHEDULED → VOIDED`, sets `withholding_cents` and
    `net_cents` to 0, and advances the row's `version` by 1."

    Design: Corner/rbac/the_officer_who_scheduled_cannot_pay_and_the_payer_cannot_reverse
    """
    residency, rows = _schedule_written_by_the_first_officer(api)

    voided = get_success_data(
        _settle(
            api,
            rows[0]["id"],
            FINANCE_SCHEDULER_HEADERS,
            action="VOID",
            reason="the calendar was drawn twice",
        )
    )

    assert voided["status"] == "VOIDED"
    assert_money_equals(voided["withholding_cents"], 0, "withholding")
    assert_money_equals(voided["net_cents"], 0, "net")
    assert voided["version"] == rows[0]["version"] + 1
    assert refresh_residency(api, residency)["stipend_paid_gross_cents"] == 0
