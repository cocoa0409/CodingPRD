"""What the collection reads return, and what the sub-resource reads return.

Each filter is exercised over a fixture deliberately built so that the filter has
something to exclude, and the audit trail is read both whole and filtered.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_paid_certification,
    create_agreement,
    create_award,
    create_certification,
    create_program,
    create_student,
    read_agreement,
    read_certification,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import (
    BURSAR_HEADERS,
    SAA_HEADERS,
    VA_HEADERS,
    make_student_headers,
)

SECOND_SCO_NAME = "Rowan Diaz"
SECOND_SCO_EMAIL = "rowan.diaz@u.edu"
SECOND_PROGRAM_CODE = "ACC-GR"
SECOND_PROGRAM_NAME = "Accounting MS"

TUITION_CHARGE_CENTS = 5000
PAID_TUITION_CENTS = 2790000
PAID_MHA_CENTS = 776444
WITHDRAWAL_REPORTED_ON = "2026-09-05"
WITHDRAWAL_EFFECTIVE_DATE = "2026-09-15"
NOTIFICATION_DUE_ON = "2026-10-05"
DAY_AFTER_NOTIFICATION_DUE = "2026-10-06"

EXPECTED_SCHOOL_SHARE_CENTS = 80000
POOL_AFTER_TWO_AWARDS_CENTS = 840000
TWO_PARTICIPANTS = 2

REDUCED_CREDIT_HOURS = 3
REDUCED_RATE_OF_PURSUIT_PCT = 25
REDUCED_ROP_TIER_PCT = 30


# ─── Filter vocabulary ────────────────────────────────────────────────
def test_officials_are_filtered_by_level_and_by_status(api, baseline):
    """Two of the three officials are front-line, and one of those is retired.

    PRD: "Certifying officials may be filtered by `official_level` and by
    `status`."

    Design: Corner/endpoints/every_collection_endpoint_lists_and_filters_its_own_rows
    """
    second = get_success_data(
        api.create_certifying_official(
            f.sco_official_payload(
                full_name=SECOND_SCO_NAME, email=SECOND_SCO_EMAIL
            ),
            VA_HEADERS,
        ),
        expected_status=201,
    )
    get_success_data(
        api.deactivate_certifying_official(second["id"], {}, VA_HEADERS)
    )

    rows, meta = validate_paginated(
        api.list_certifying_officials(VA_HEADERS, {"official_level": c.LEVEL_SCO})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {baseline.sco_id, second["id"]}

    rows, meta = validate_paginated(
        api.list_certifying_officials(
            VA_HEADERS, {"status": c.OFFICIAL_STATUS_INACTIVE}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]


def test_programs_are_filtered_by_approval_posture_and_by_degree_level(api, baseline):
    """The approved undergraduate program and the draft graduate one separate cleanly.

    PRD: "Programs may be filtered by `approval_status`, `degree_level` and
    `approved_catalog_version_id`."

    Design: Corner/endpoints/every_collection_endpoint_lists_and_filters_its_own_rows
    """
    second_program_id = create_program(
        api,
        baseline.sup_headers,
        program_code=SECOND_PROGRAM_CODE,
        name=SECOND_PROGRAM_NAME,
        degree_level=c.DEGREE_LEVEL_GRADUATE,
    )

    rows, meta = validate_paginated(
        api.list_programs(
            baseline.sup_headers, {"approval_status": c.PROGRAM_STATUS_APPROVED}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == baseline.program_id

    rows, meta = validate_paginated(
        api.list_programs(
            baseline.sup_headers, {"degree_level": c.DEGREE_LEVEL_GRADUATE}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second_program_id


def test_terms_are_filtered_by_status_and_by_term_type(api, baseline):
    """One term is still open and the other is a closed spring term.

    PRD: "Academic terms may be filtered by `academic_year`, `term_type` and
    `status`."

    Design: Corner/endpoints/every_collection_endpoint_lists_and_filters_its_own_rows
    """
    spring_id = get_success_data(
        api.create_academic_term(f.spring_term_payload(), baseline.sup_headers),
        expected_status=201,
    )["id"]
    get_success_data(api.close_academic_term(spring_id, {}, baseline.sup_headers))

    rows, meta = validate_paginated(
        api.list_academic_terms(baseline.sup_headers, {"status": c.TERM_STATUS_OPEN})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == baseline.term_id

    rows, meta = validate_paginated(
        api.list_academic_terms(
            baseline.sup_headers, {"term_type": c.TERM_TYPE_SPRING}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == spring_id


def test_agreements_are_filtered_by_status_and_by_degree_level(api, baseline):
    """The live undergraduate agreement and the closed graduate one separate cleanly.

    PRD: "Yellow Ribbon agreements may be filtered by `academic_year`,
    `degree_level` and `status`."

    Design: Corner/endpoints/every_collection_endpoint_lists_and_filters_its_own_rows
    """
    undergrad_id, _version = create_agreement(api, baseline.sup_headers)
    graduate_id, _version = create_agreement(
        api, baseline.sup_headers, degree_level=c.DEGREE_LEVEL_GRADUATE
    )
    get_success_data(
        api.close_yellow_ribbon_agreement(graduate_id, {}, baseline.sup_headers)
    )

    rows, meta = validate_paginated(
        api.list_yellow_ribbon_agreements(
            baseline.sup_headers, {"status": c.AGREEMENT_STATUS_ACTIVE}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == undergrad_id

    rows, meta = validate_paginated(
        api.list_yellow_ribbon_agreements(
            baseline.sup_headers, {"degree_level": c.DEGREE_LEVEL_GRADUATE}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == graduate_id


def test_charges_are_filtered_by_student_and_by_charge_type(api, baseline):
    """The one posted charge is reachable by student and invisible under another type.

    PRD: "Student account charges may be filtered by `student_id`, `term_id` and
    `charge_type`."

    Design: Corner/endpoints/every_collection_endpoint_lists_and_filters_its_own_rows
    """
    student_id = create_student(api, baseline.sco_headers)
    charge = get_success_data(
        api.create_student_account_charge(
            f.student_account_charge_payload(
                student_id,
                baseline.term_id,
                c.CHARGE_TYPE_TUITION,
                TUITION_CHARGE_CENTS,
            ),
            BURSAR_HEADERS,
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_student_account_charges(BURSAR_HEADERS, {"student_id": student_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == charge["id"]
    assert rows[0]["charge_type"] == c.CHARGE_TYPE_TUITION

    rows, meta = validate_paginated(
        api.list_student_account_charges(
            BURSAR_HEADERS, {"charge_type": c.CHARGE_TYPE_LATE_FEE}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ─── The certification audit trail ────────────────────────────────────
def _reconciled_withdrawal(api, baseline):
    """A paid certification carried through a withdrawal and its reconciliation."""
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    return scenario


def test_the_whole_trail_reads_back_in_ascending_sequence_order(api, baseline):
    """Six events, numbered one to six, in the order they happened.

    PRD: "The complete history of a certification is readable as its append-only
    audit trail, returned in ascending `sequence_index` order and filterable by
    `event_type`, which lets a reviewer reconstruct who submitted, who certified,
    what was auto-returned by an agency suspension, and where every debt and
    reversal came from."

    Design: Corner/endpoints/audit_entries_form_a_gapless_per_certification_sequence_readable_by_filter
    """
    scenario = _reconciled_withdrawal(api, baseline)

    entries, _meta = validate_paginated(
        api.list_audit_entries(scenario.certification_id, baseline.sup_headers)
    )
    a.assert_event_sequence(
        entries,
        [
            c.EVENT_CERTIFICATION_SUBMITTED,
            c.EVENT_CERTIFICATION_CERTIFIED,
            c.EVENT_VA_PAYMENT_RECORDED,
            c.EVENT_AMENDMENT_OPENED,
            c.EVENT_AMENDMENT_RECONCILED,
            c.EVENT_DEBT_CREATED,
        ],
    )
    for entry in entries:
        a.assert_audit_entry_shape(entry)


def test_the_trail_narrows_to_one_event_type_keeping_its_sequence_number(api, baseline):
    """Filtering to the debt event returns that entry alone, still numbered six.

    PRD: "The certification audit trail may be filtered by `event_type`."

    Design: Corner/endpoints/audit_entries_form_a_gapless_per_certification_sequence_readable_by_filter
    """
    scenario = _reconciled_withdrawal(api, baseline)

    entries, meta = validate_paginated(
        api.list_audit_entries(
            scenario.certification_id,
            SAA_HEADERS,
            {"event_type": c.EVENT_DEBT_CREATED},
        )
    )
    assert meta["total_count"] == 1
    assert entries[0]["event_type"] == c.EVENT_DEBT_CREATED
    assert entries[0]["sequence_index"] == 6


# ─── Awards from either side of the link ──────────────────────────────
def _two_awards_on_one_agreement(api, baseline):
    """One agreement carrying an award for each of two eligible students."""
    first = build_certified_certification(api, baseline)
    second = build_certified_certification(
        api,
        baseline,
        student_overrides={
            "student_number": c.SECOND_STUDENT_NUMBER,
            "full_name": c.SECOND_STUDENT_NAME,
        },
    )
    agreement_id, version = create_agreement(api, baseline.sup_headers)
    award_one = create_award(
        api, baseline.sup_headers, first.certification_id, agreement_id, version
    )
    award_two = create_award(
        api, baseline.sup_headers, second.certification_id, agreement_id, version + 1
    )
    return agreement_id, first, award_one, award_two


def test_one_award_is_reachable_from_its_certification(api, baseline):
    """The certification filter narrows the agreement's two awards down to one.

    PRD: "Yellow Ribbon awards may be filtered by `certification_id`,
    `agreement_id` and `status`."

    Design: Corner/endpoints/yellow_ribbon_awards_are_listable_from_both_the_certification_and_the_agreement_side
    """
    _agreement_id, first, award_one, _award_two = _two_awards_on_one_agreement(
        api, baseline
    )

    rows, meta = validate_paginated(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"certification_id": first.certification_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == award_one["id"]
    a.assert_fields(
        rows[0],
        {
            "school_share_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "va_match_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "student_out_of_pocket_cents": 0,
        },
    )


def test_both_awards_are_reachable_from_their_agreement(api, baseline):
    """The agreement filter returns everything drawn on that agreement.

    PRD: "Because the topology is flat, every foreign key is exposed as a list
    filter so that related rows are reachable from any parent identifier."

    Design: Corner/endpoints/yellow_ribbon_awards_are_listable_from_both_the_certification_and_the_agreement_side
    """
    agreement_id, _first, award_one, award_two = _two_awards_on_one_agreement(
        api, baseline
    )

    rows, meta = validate_paginated(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"agreement_id": agreement_id}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {award_one["id"], award_two["id"]}
    assert {row["agreement_id"] for row in rows} == {agreement_id}


def test_finalizing_one_award_moves_only_that_row_and_no_money(api, baseline):
    """The other award stays provisional and the agreement's counters do not move.

    PRD: "Finalization moves no money: the agreement's `pool_remaining_cents` and
    `participant_count` are unchanged, because both `PROVISIONAL` and `FINAL` awards
    are already counted as committed."

    Design: Corner/endpoints/yellow_ribbon_awards_are_listable_from_both_the_certification_and_the_agreement_side
    """
    agreement_id, _first, award_one, award_two = _two_awards_on_one_agreement(
        api, baseline
    )

    get_success_data(
        api.finalize_yellow_ribbon_award(
            award_one["id"], {}, baseline.sup_headers
        )
    )

    rows, meta = validate_paginated(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"status": c.AWARD_STATUS_PROVISIONAL}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == award_two["id"]
    assert (
        get_success_data(
            api.get_yellow_ribbon_award(award_one["id"], baseline.sup_headers)
        )["status"]
        == c.AWARD_STATUS_FINAL
    )
    a.assert_fields(
        read_agreement(api, baseline.sup_headers, agreement_id),
        {
            "pool_remaining_cents": POOL_AFTER_TWO_AWARDS_CENTS,
            "participant_count": TWO_PARTICIPANTS,
        },
    )


# ─── Escalating a debt notification ───────────────────────────────────
def _notified_debt(api, baseline):
    """A reconciled withdrawal's debt, notified by email on 2026-09-05."""
    scenario = _reconciled_withdrawal(api, baseline)
    rows, _meta = validate_paginated(api.list_benefit_debts(BURSAR_HEADERS))
    debt = get_success_data(
        api.notify_benefit_debt(
            rows[0]["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )
    return scenario, debt


def test_the_notification_deadline_is_thirty_days_after_the_reconciliation(
    api, baseline
):
    """A debt created on 2026-09-05 must be answered by 2026-10-05.

    PRD: "The debt's `notification_due_on` is stamped 30 days after the current
    logical clock date."

    Design: Corner/endpoints/marking_a_debt_overdue_before_its_notification_deadline_returns_4xx
    """
    _scenario, debt = _notified_debt(api, baseline)

    assert debt["notification_due_on"] == NOTIFICATION_DUE_ON


def test_escalating_on_the_due_date_itself_is_refused(api, baseline):
    """The comparison is strictly-after, so the last day is still not overdue.

    PRD: "Marking a debt overdue is permitted while its `notification_status` is
    `PENDING` or `SENT` — any other posture is refused with
    `ERR_DEBT_ALREADY_NOTIFIED` — and additionally requires that the current logical
    clock date be **strictly after** the debt's `notification_due_on`; escalating on
    or before the due date is a malformed request and is refused with
    `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/marking_a_debt_overdue_before_its_notification_deadline_returns_4xx
    """
    _scenario, debt = _notified_debt(api, baseline)
    set_clock_to(api, NOTIFICATION_DUE_ON)

    response = api.mark_benefit_debt_overdue(debt["id"], {}, VA_HEADERS)
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    unchanged = get_success_data(api.get_benefit_debt(debt["id"], BURSAR_HEADERS))
    assert unchanged["notification_status"] == c.DEBT_NOTIFICATION_SENT


def test_escalating_the_day_after_the_due_date_succeeds(api, baseline):
    """One day later the same call is accepted.

    PRD: "The two entry paths differ only in where they come from: `SENT → OVERDUE`
    escalates a notified debt the debtor has ignored, while `PENDING → OVERDUE`
    records a debt that became overdue without any notification having been sent at
    all."

    Design: Corner/endpoints/marking_a_debt_overdue_before_its_notification_deadline_returns_4xx
    """
    _scenario, debt = _notified_debt(api, baseline)
    set_clock_to(api, DAY_AFTER_NOTIFICATION_DUE)

    escalated = get_success_data(
        api.mark_benefit_debt_overdue(debt["id"], {}, VA_HEADERS)
    )
    assert escalated["notification_status"] == c.DEBT_NOTIFICATION_OVERDUE


def test_the_student_can_still_acknowledge_an_overdue_notification(api, baseline):
    """Acknowledgement is reachable from OVERDUE and leaves the money alone.

    PRD: "Acknowledgement moves the debt to `ACKNOWLEDGED` and stamps
    `acknowledged_on` with the current logical clock date."

    Design: Corner/endpoints/marking_a_debt_overdue_before_its_notification_deadline_returns_4xx
    """
    scenario, debt = _notified_debt(api, baseline)
    set_clock_to(api, DAY_AFTER_NOTIFICATION_DUE)
    get_success_data(api.mark_benefit_debt_overdue(debt["id"], {}, VA_HEADERS))

    acknowledged = get_success_data(
        api.acknowledge_benefit_debt(
            debt["id"], {}, make_student_headers(scenario.student_id)
        )
    )
    a.assert_fields(
        acknowledged,
        {
            "notification_status": c.DEBT_NOTIFICATION_ACKNOWLEDGED,
            "acknowledged_on": DAY_AFTER_NOTIFICATION_DUE,
            "collection_status": c.DEBT_COLLECTION_OPEN,
        },
    )


# ─── Revising a returned certification ────────────────────────────────
def _returned_certification(api, baseline):
    """A submitted certification sent back by supervisory review."""
    student_id = create_student(api, baseline.sco_headers)
    certification_id, _version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    submit_certification(api, baseline.sco_headers, certification_id)
    get_success_data(
        api.return_certification(
            certification_id, f.return_certification_payload(), baseline.sup_headers
        )
    )
    return certification_id


def _revise_to_three_credit_hours(api, baseline, certification_id):
    return get_success_data(
        api.update_enrollment_certification(
            certification_id,
            {"credit_hours_total": REDUCED_CREDIT_HOURS},
            baseline.sco_headers,
        )
    )


def test_revising_a_returned_certification_reopens_it_as_a_draft(api, baseline):
    """The edit puts the row back in the drafting stage and drops the reason.

    PRD: "A revision applied while it sits at `RETURNED` moves it `RETURNED → DRAFT`
    and clears the stored `return_reason`, which is how a rejected certification
    re-enters the drafting stage."

    Design: Corner/endpoints/patching_a_returned_certification_recomputes_the_pursuit_fields_and_reopens_it_as_draft
    """
    certification_id = _returned_certification(api, baseline)

    revised = _revise_to_three_credit_hours(api, baseline, certification_id)
    a.assert_fields(
        revised, {"status": c.CERT_STATUS_DRAFT, "return_reason": None}
    )


def test_the_revision_overwrites_only_what_it_supplies_and_recomputes_the_block(
    api, baseline
):
    """Three of twelve hours is a quarter of the load; the dates are untouched.

    PRD: "A revision may supply any subset of `credit_hours_total`,
    `credit_hours_online`, `term_start_certified` and `term_end_certified`,
    overwrites whichever of them it supplies, and then recomputes the whole derived
    block above from the resulting values."

    Design: Corner/endpoints/patching_a_returned_certification_recomputes_the_pursuit_fields_and_reopens_it_as_draft
    """
    certification_id = _returned_certification(api, baseline)

    revised = _revise_to_three_credit_hours(api, baseline, certification_id)
    a.assert_fields(
        revised,
        {
            "credit_hours_total": REDUCED_CREDIT_HOURS,
            "credit_hours_online": 0,
            "certified_days": c.CANONICAL_CERTIFIED_DAYS,
            "rate_of_pursuit_pct": REDUCED_RATE_OF_PURSUIT_PCT,
            "rop_tier_pct": REDUCED_ROP_TIER_PCT,
        },
    )
    assert (
        read_certification(api, baseline.sco_headers, certification_id)[
            "rate_of_pursuit_pct"
        ]
        == REDUCED_RATE_OF_PURSUIT_PCT
    )


def test_the_recomputed_band_falls_to_quarter_time(api, baseline):
    """A quarter of the full-time load reads off the quarter-time band.

    PRD: "It is `FULL_TIME` when `rate_of_pursuit_pct` is at least 100; otherwise
    `THREE_QUARTER` when it is at least 75; otherwise `HALF_TIME` when it is at
    least 50; otherwise `QUARTER_TIME` when it is at least 25; and otherwise
    `LESS_THAN_QUARTER`."

    Design: Corner/endpoints/patching_a_returned_certification_recomputes_the_pursuit_fields_and_reopens_it_as_draft
    """
    certification_id = _returned_certification(api, baseline)

    revised = _revise_to_three_credit_hours(api, baseline, certification_id)
    assert revised["training_time"] == c.TRAINING_TIME_QUARTER


def test_the_recomputed_enrollment_earns_no_housing_allowance(api, baseline):
    """At twenty-five percent pursuit the housing entitlement disappears.

    PRD: "`mha_eligible` is true only when the student's `chapter` is `CH33` **and**
    their `rate_of_pursuit_pct` is strictly greater than 50 — the comparison is
    strict, so a student pursuing at exactly 50 percent earns no housing allowance
    at all, whereas one at 51 percent does."

    Design: Corner/endpoints/patching_a_returned_certification_recomputes_the_pursuit_fields_and_reopens_it_as_draft
    """
    certification_id = _returned_certification(api, baseline)

    revised = _revise_to_three_credit_hours(api, baseline, certification_id)
    assert revised["mha_eligible"] is False
    assert revised["mha_monthly_rate_cents"] == 0
