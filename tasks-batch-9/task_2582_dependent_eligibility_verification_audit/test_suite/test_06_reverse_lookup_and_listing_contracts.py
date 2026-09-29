"""Reading the audit back out: reverse lookups, running totals, and page meta.

Every collection in this service exists to answer a question about one parent
row — which claims the plan already paid for a dependent, which voluntary
removals a case collected, which newly enrolled dependents a program is
verifying, and which recovery answers a termination notice. This module reads
each of those collections from both sides where two paths exist, checks the
running totals and prorated figures the reads are supposed to expose, and pins
the four pagination fields that every page of them reports.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_evidence_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_ordered_by_created_at,
    assert_page_meta,
    ids_of,
)
from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    ORIGIN_INSTANT,
    announced_wave,
    recovery_wave,
)
from test_helpers.test_users import (
    ANALYST,
    PROGRAM_ADMIN,
    RECOVERY_AGENT,
    employee_headers,
)

# The instant the household below records its voluntary removal on.
AMNESTY_RECORDING_INSTANT = "2026-09-10T00:00:00Z"
# The date the audited census was frozen, before the announcement went out.
SCOPE_INSTANT = "2026-08-05T00:00:00Z"
# The instant the two post-announcement dependents joined their household.
POE_ENROLLMENT_INSTANT = "2026-09-05T00:00:00Z"
# Thirty grace days past that enrollment.
POE_DEADLINE_INSTANT = "2026-10-05T00:00:00Z"
# The single claim the recovery scenarios below price.
RECOVERY_CLAIM = {
    "service_date": "2026-10-05",
    "paid_cents": 90000,
    "employee_premium_offset_cents": 20000,
}


def _claim_lines_of(b, dependent_id: str, **params):
    """One page of a dependent's paid claim history."""
    return validate_paginated(
        b.client.list_paid_claims(dependent_id, RECOVERY_AGENT, params=params or None)
    )


def _roster_of(b, program_id: str, headers=PROGRAM_ADMIN, **params):
    """One page of the dependents a program verifies at point of enrollment."""
    return validate_paginated(
        b.client.list_program_dependents(program_id, headers, params=params or None)
    )


def test_three_paid_claim_lines_raise_the_dependents_running_total_by_their_paid_amounts(
    b, client, clock
):
    """Recording one increases the dependent's `paid_claims_total_cents` by the line's
    `paid_cents`, that field being the exact sum of the dependent's paid lines.

    Design: Corner/endpoints/corner_paid_claim_lines_are_append_only_and_maintain_the_dependent_running_total
    """
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(subscriber["id"], "SPOUSE")

    first = b.paid_claim(
        dependent["id"],
        service_date="2026-06-20",
        paid_cents=60000,
        employee_premium_offset_cents=12000,
    )
    assert_evidence_common_fields(first)
    assert first["employee_premium_offset_cents"] == 12000, first
    assert b.read_dependent(dependent["id"])["paid_claims_total_cents"] == 60000

    b.paid_claim(dependent["id"], service_date="2026-07-05", paid_cents=40000)
    assert b.read_dependent(dependent["id"])["paid_claims_total_cents"] == 100000

    b.paid_claim(dependent["id"], service_date="2026-07-19", paid_cents=30000)
    settled = b.read_dependent(dependent["id"])
    assert settled["paid_claims_total_cents"] == 130000, settled

    rows, meta = _claim_lines_of(b, dependent["id"], limit=10, offset=0)
    assert meta["total_count"] == 3, meta
    assert sum(row["paid_cents"] for row in rows) == 130000, rows


def test_a_claim_line_that_omits_the_premium_offset_records_it_as_zero(b, client, clock):
    """an optional `employee_premium_offset_cents` recording the employee's own premium
    contribution credited against the line which defaults to zero and may not be
    negative

    Design: Corner/endpoints/corner_paid_claim_lines_are_append_only_and_maintain_the_dependent_running_total
    """
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(subscriber["id"], "SPOUSE")
    payload = f.paid_claim_payload("2026-07-19", 30000, index=3)
    payload.pop("employee_premium_offset_cents")

    line = validate_success(
        client.create_paid_claim(dependent["id"], payload, RECOVERY_AGENT),
        expected_status=201,
    )

    assert_evidence_common_fields(line)
    assert_fields(
        line,
        dependent_id=dependent["id"],
        service_date="2026-07-19",
        paid_cents=30000,
        employee_premium_offset_cents=0,
        claim_reference=payload["claim_reference"],
    )
    assert b.read_dependent(dependent["id"])["paid_claims_total_cents"] == 30000


def test_the_claim_history_pages_two_lines_at_a_time_in_the_order_they_were_written(
    b, client, clock
):
    """List results are ordered by `created_at` ascending unless a workflow in §3
    explicitly pins a different processing order for an internal computation. The four
    pagination fields reported in `meta` are `limit` (the effective page size applied),
    `offset` (the effective skip applied), `total_count` (the number of records matching
    the request's filters before pagination), and `has_more` (true when records remain
    beyond the current page).

    Design: Corner/endpoints/corner_paid_claim_lines_are_append_only_and_maintain_the_dependent_running_total
    """
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(subscriber["id"], "SPOUSE")
    written = [
        b.paid_claim(dependent["id"], service_date="2026-06-20", paid_cents=60000),
        b.paid_claim(dependent["id"], service_date="2026-07-05", paid_cents=40000),
        b.paid_claim(dependent["id"], service_date="2026-07-19", paid_cents=30000),
    ]

    first_page, first_meta = _claim_lines_of(b, dependent["id"], limit=2, offset=0)

    assert len(first_page) == 2, first_page
    assert_page_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert_ordered_by_created_at(first_page)

    second_page, second_meta = _claim_lines_of(b, dependent["id"], limit=2, offset=2)
    assert len(second_page) == 1, second_page
    assert_page_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert set(ids_of(first_page) + ids_of(second_page)) == set(ids_of(written))


def _household_with_one_amnesty_removal(b):
    """An announced wave whose child dependent was voluntarily given up."""
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(AMNESTY_RECORDING_INSTANT)
    ctx.removal = b.amnesty_removal(
        ctx.dep2["id"],
        ctx.case["id"],
        ctx.employee["id"],
        reason_code="AGE_LIMIT_EXCEEDED",
    )
    return ctx


def test_the_same_removal_is_returned_by_the_dependent_path_and_the_case_path(b, client):
    """listing amnesty removals walks either `AmnestyRemoval.dependent_id` or
    `AmnestyRemoval.case_id` depending on the path used

    Design: Corner/endpoints/corner_amnesty_removal_is_readable_from_both_the_dependent_and_the_case_side
    """
    ctx = _household_with_one_amnesty_removal(b)

    from_dependent, dependent_meta = b.dependent_removals(
        ctx.dep2["id"],
        employee_headers(ctx.employee["id"]),
        limit=10,
        offset=0,
    )
    from_case, case_meta = b.case_removals(ctx.case["id"], limit=10, offset=0)

    assert_page_meta(dependent_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert_page_meta(case_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert from_dependent == from_case, (from_dependent, from_case)
    assert from_dependent[0]["id"] == ctx.removal["id"], from_dependent
    assert_evidence_common_fields(from_dependent[0])
    assert_fields(
        from_dependent[0],
        dependent_id=ctx.dep2["id"],
        case_id=ctx.case["id"],
        reason_code="AGE_LIMIT_EXCEEDED",
        coverage_end_date="2026-09-30",
        penalty_waived=True,
        claims_recovery_waived=True,
    )
    assert_instant_equals(from_dependent[0]["recorded_at"], AMNESTY_RECORDING_INSTANT)


def test_the_removals_prorated_saving_lands_in_the_programs_audited_figure(b, client):
    """Its `audited_savings_contribution_cents` is the dependent's `monthly_cost_cents`
    multiplied by twelve minus the calendar month number of the removal's
    `coverage_end_date` ... `audited_annual_savings_cents` grows by the removal's
    `audited_savings_contribution_cents`

    Design: Corner/endpoints/corner_amnesty_removal_is_readable_from_both_the_dependent_and_the_case_side
    """
    ctx = _household_with_one_amnesty_removal(b)
    expected = MONTHLY_COST_CENTS["CHILD_BIOLOGICAL"] * (12 - 9)

    rows, _meta = b.case_removals(ctx.case["id"], limit=10, offset=0)

    assert rows[0]["audited_savings_contribution_cents"] == expected, rows[0]
    assert expected == 91500, expected
    program = b.read_program(ctx.program["id"])
    assert_fields(
        program,
        amnesty_removed_count=1,
        pending_dependent_count=1,
        audited_annual_savings_cents=expected,
    )


def test_the_case_outreach_log_holds_the_announcement_then_the_amnesty_confirmation(
    b, client
):
    """one `CommunicationEvent` is appended per case with `kind` `ANNOUNCEMENT` and
    `sequence_no` 1 ... One `CommunicationEvent` with `kind` `AMNESTY_CONFIRMATION` is
    appended to the case.

    Design: Corner/endpoints/corner_amnesty_removal_is_readable_from_both_the_dependent_and_the_case_side
    """
    ctx = _household_with_one_amnesty_removal(b)

    events, meta = b.communications(ctx.case["id"], limit=10, offset=0)

    assert_page_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
    assert [row["kind"] for row in events] == [
        "ANNOUNCEMENT",
        "AMNESTY_CONFIRMATION",
    ], events
    assert [row["sequence_no"] for row in events] == [1, 2], events
    assert_ordered_by_created_at(events)
    for event in events:
        assert_evidence_common_fields(event)
        assert event["case_id"] == ctx.case["id"], event
    assert_instant_equals(events[0]["sent_at"], ANNOUNCE_INSTANT)
    assert_instant_equals(events[1]["sent_at"], AMNESTY_RECORDING_INSTANT)


def _program_verifying_two_new_dependents(b):
    """An announced program plus two dependents enrolled after the announcement."""
    b.set_clock(ORIGIN_INSTANT)
    audited = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    census_dependent = b.dependent(audited["id"], "SPOUSE")

    program = b.program(poe_verification_enabled=True)
    b.doc_rule(program["id"], "SPOUSE")
    b.doc_rule(
        program["id"],
        "SPOUSE",
        "POINT_OF_ENROLLMENT",
        grace_days=30,
        auto_terminate_on_lapse=True,
    )
    b.doc_rule(
        program["id"],
        "CHILD_BIOLOGICAL",
        "POINT_OF_ENROLLMENT",
        grace_days=30,
        auto_terminate_on_lapse=True,
    )

    b.set_clock(SCOPE_INSTANT)
    b.scope(program["id"], "FULL_CENSUS")
    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(program["id"])

    b.set_clock(POE_ENROLLMENT_INSTANT)
    newcomer = b.employee()
    joined = [
        b.dependent(newcomer["id"], "SPOUSE"),
        b.dependent(newcomer["id"], "CHILD_BIOLOGICAL"),
    ]
    return program, census_dependent, joined


def test_the_program_roster_holds_the_new_enrollments_and_not_the_audited_census(
    b, client
):
    """listing a program's point-of-enrollment dependents walks
    `Dependent.poe_program_id`

    Design: Corner/endpoints/corner_poe_roster_lists_only_program_bound_dependents_and_paginates
    """
    program, census_dependent, joined = _program_verifying_two_new_dependents(b)

    roster, meta = _roster_of(b, program["id"], limit=10, offset=0)

    assert_page_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
    assert ids_of(roster) == ids_of(joined), roster
    assert census_dependent["id"] not in ids_of(roster), roster
    assert_ordered_by_created_at(roster)

    audited_row = b.read_dependent(census_dependent["id"])
    assert_fields(
        audited_row,
        coverage_status="PENDING_VERIFICATION",
        poe_program_id=None,
        poe_deadline_at=None,
    )


def test_the_roster_filters_by_coverage_status_and_reports_the_shared_grace_deadline(
    b, client
):
    """with `poe_deadline_at` set to the current clock instant advanced by the governing
    rule's `grace_days` whole days, `accepted_proof_type_count` at zero, and
    `documentation_complete` false ... those filters are applied first and `total_count`
    reflects the filtered population.

    Design: Corner/endpoints/corner_poe_roster_lists_only_program_bound_dependents_and_paginates
    """
    program, _census_dependent, joined = _program_verifying_two_new_dependents(b)

    pending, pending_meta = _roster_of(
        b,
        program["id"],
        ANALYST,
        coverage_status="PENDING_VERIFICATION",
        limit=10,
        offset=0,
    )

    assert_page_meta(pending_meta, limit=10, offset=0, total_count=2, has_more=False)
    assert ids_of(pending) == ids_of(joined), pending
    for row in pending:
        assert row["poe_program_id"] == program["id"], row
        assert_instant_equals(row["poe_deadline_at"], POE_DEADLINE_INSTANT)
        assert row["documentation_complete"] is False, row

    verified, verified_meta = _roster_of(
        b, program["id"], coverage_status="VERIFIED", limit=10, offset=0
    )
    assert verified == [], verified
    assert_page_meta(verified_meta, limit=10, offset=0, total_count=0, has_more=False)


def test_the_roster_pages_one_dependent_at_a_time(b, client):
    """`offset` controls how many records are skipped before the page begins; it
    defaults to 0 and its minimum accepted value is 0.

    Design: Corner/endpoints/corner_poe_roster_lists_only_program_bound_dependents_and_paginates
    """
    program, _census_dependent, joined = _program_verifying_two_new_dependents(b)

    first_page, first_meta = _roster_of(b, program["id"], limit=1, offset=0)
    assert ids_of(first_page) == [joined[0]["id"]], first_page
    assert_page_meta(first_meta, limit=1, offset=0, total_count=2, has_more=True)

    second_page, second_meta = _roster_of(b, program["id"], limit=1, offset=1)
    assert ids_of(second_page) == [joined[1]["id"]], second_page
    assert_page_meta(second_meta, limit=1, offset=1, total_count=2, has_more=False)


def test_the_recovery_is_found_again_through_the_notice_it_answers(b, client):
    """and `termination_notice_id` and `recovery_variant` on claim recoveries — those
    filters are applied first and `total_count` reflects the filtered population.

    Design: Corner/endpoints/corner_recovery_list_filters_by_dependent_notice_status_and_variant
    """
    ctx = recovery_wave(b, claims=(RECOVERY_CLAIM,))

    by_notice, notice_meta = b.recoveries(
        PROGRAM_ADMIN,
        termination_notice_id=ctx.notice["id"],
        status="OPEN",
        limit=10,
        offset=0,
    )

    assert_page_meta(notice_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert ids_of(by_notice) == [ctx.recovery["id"]], by_notice
    assert_fields(
        by_notice[0],
        dependent_id=ctx.dep["id"],
        termination_notice_id=ctx.notice["id"],
        recovery_variant="STRICT",
        status="OPEN",
        recoverable_subtotal_cents=90000,
        admin_fee_cents=0,
        waiver_credit_cents=0,
        net_demand_cents=0,
        recovered_cents=0,
        refund_due_cents=0,
        demand_issued_at=None,
    )

    by_variant, variant_meta = b.recoveries(
        RECOVERY_AGENT, recovery_variant="STRICT", limit=10, offset=0
    )
    assert ids_of(by_variant) == [ctx.recovery["id"]], by_variant
    assert_page_meta(variant_meta, limit=10, offset=0, total_count=1, has_more=False)


@pytest.mark.parametrize(
    "filters",
    [{"status": "DEMAND_ISSUED"}, {"recovery_variant": "EQUITABLE"}],
    ids=["demand_issued_status", "equitable_variant"],
)
def test_a_filter_no_recovery_matches_returns_an_empty_page_rather_than_everything(
    b, client, filters
):
    """a `status` filter on programs, cases, appeals, notices, or recoveries ... those
    filters are applied first and `total_count` reflects the filtered population.

    Design: Corner/endpoints/corner_recovery_list_filters_by_dependent_notice_status_and_variant
    """
    recovery_wave(b, claims=(RECOVERY_CLAIM,))

    rows, meta = b.recoveries(PROGRAM_ADMIN, limit=10, offset=0, **filters)

    assert rows == [], rows
    assert_page_meta(meta, limit=10, offset=0, total_count=0, has_more=False)


def test_a_page_past_the_end_of_the_recovery_list_still_reports_the_unpaged_total(
    b, client
):
    """`total_count` (the number of records matching the request's filters before
    pagination), and `has_more` (true when records remain beyond the current page)

    Design: Corner/endpoints/corner_recovery_list_filters_by_dependent_notice_status_and_variant
    """
    ctx = recovery_wave(b, claims=(RECOVERY_CLAIM,))

    rows, meta = b.recoveries(
        RECOVERY_AGENT, termination_notice_id=ctx.notice["id"], limit=1, offset=1
    )

    assert rows == [], rows
    assert_page_meta(meta, limit=1, offset=1, total_count=1, has_more=False)
