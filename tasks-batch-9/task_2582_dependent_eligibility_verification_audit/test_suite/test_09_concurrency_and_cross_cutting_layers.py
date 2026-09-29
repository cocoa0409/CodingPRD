"""Concurrent writers, the deferred-action checkpoint, and immediate visibility.

Two acts in this audit destroy work another writer created — re-deciding a
program's scope, which voids the previous case snapshot, and opening a claims
recovery, which supersedes the demand that came before it — so both are guarded
against the parent record's version. Everything that "happens when a deadline
passes" happens instead because an administrator runs the checkpoint against the
logical clock, and this module pins what that checkpoint does when it is early,
when it is replayed, and when it is run so late that several deadlines have
already gone by. It closes with the other side of the same coin: an ordinary
write whose whole cascade is already visible to the very next read.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    assert_race_outcome,
    run_race,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient
from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_counter_partition,
    assert_evidence_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_priority_score,
)
from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import (
    DEFAULT_ONSET_DATE,
    EFFECTIVE_DATE,
    ORIGIN_INSTANT,
    RESPONSE_WINDOW_INSTANT,
    announced_wave,
    finalized_wave,
)
from test_helpers.test_users import PROGRAM_ADMIN, RECOVERY_AGENT, employee_headers
from test_helpers.types import Ctx

# A working instant inside the amnesty window of a 2026-09-01 announcement.
AMNESTY_INSTANT = "2026-09-10T00:00:00Z"
# The last day of the month containing the removal instant above.
AMNESTY_COVERAGE_END = "2026-09-30"
# Long past both the 2026-09-22 amnesty end and the 2026-10-16 response deadline.
LATE_SWEEP_INSTANT = "2026-12-17T00:00:00Z"
# 2026-12-17 advanced by fourteen days, then taken to that month's last day.
LATE_EFFECTIVE_DATE = "2026-12-31"
# 2026-12-17 advanced by sixty whole days.
LATE_ELECTION_DEADLINE = "2027-02-15T00:00:00Z"
# A working instant after the notices went final, used to price recoveries.
RECOVERY_INSTANT = "2026-11-05T00:00:00Z"
# The two paid lines the recovery arithmetic is written against.
IN_WINDOW_CLAIM = {
    "service_date": "2026-10-05",
    "paid_cents": 90000,
    "employee_premium_offset_cents": 20000,
}
POST_WINDOW_CLAIM = {"service_date": "2026-11-15", "paid_cents": 50000}
STRICT_SUBTOTAL_CENTS = 90000
EQUITABLE_SUBTOTAL_CENTS = 70000


def _draft_program_and_one_household(b) -> Ctx:
    """One subscriber holding one enrolled dependent, and a program in DRAFT."""
    b.set_clock(ORIGIN_INSTANT)
    employee = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(employee["id"], "SPOUSE")
    program = b.program()
    b.doc_rule(program["id"], "SPOUSE")
    return Ctx(
        employee=employee,
        dependent=dependent,
        program=b.read_program(program["id"]),
    )


def _cases_page(client, program_id: str):
    """The program's cases, read through the published filter."""
    return validate_paginated(
        client.list_cases(
            PROGRAM_ADMIN, params={"program_id": program_id, "limit": 10, "offset": 0}
        )
    )


def _notices_of(b, dependent_id: str):
    """Every termination notice standing against one dependent."""
    return [row for row in b.notices() if row["dependent_id"] == dependent_id]


def _recoveries_of(b, dependent_id: str):
    """Every claims recovery standing against one dependent."""
    rows, _meta = b.recoveries(limit=100, offset=0)
    return [row for row in rows if row["dependent_id"] == dependent_id]


def _terminated_household_with_two_paid_lines(b) -> Ctx:
    """A finalised termination whose dependent carries one in-window paid line."""
    ctx = finalized_wave(b, claims=(IN_WINDOW_CLAIM, POST_WINDOW_CLAIM))
    ctx.notice = _notices_of(b, ctx.dep["id"])[0]
    b.set_clock(RECOVERY_INSTANT)
    return ctx


# ----------------------------------------------- optimistic concurrency on a re-scope
def test_replaying_a_program_version_a_scope_run_already_spent_voids_no_case(b, client):
    """If that value does not equal the program's current `version`, the request is
    rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). ... First, every existing
    case of this program still in `SELECTED` moves `SELECTED → VOIDED`, and because
    those cases are voided, each of their in-scope dependents moves back
    `PENDING_VERIFICATION → ENROLLED`.

    Design: Corner/cross-cutting complexity layers/corner_stale_program_version_blocks_a_rescope_that_would_void_unseen_cases
    """
    ctx = _draft_program_and_one_household(b)
    spent_version = ctx.program["version"]
    b.scope(ctx.program["id"], "FULL_CENSUS", expected_program_version=spent_version)

    refused = client.run_scope(
        ctx.program["id"],
        f.scope_payload(spent_version, "FULL_CENSUS"),
        PROGRAM_ADMIN,
    )
    validate_error(refused, E.ERR_STALE_PROGRAM_VERSION, expected_status=412)

    after_refusal = b.read_program(ctx.program["id"])
    assert after_refusal["version"] == spent_version + 1, after_refusal
    surviving, meta = _cases_page(client, ctx.program["id"])
    assert meta["total_count"] == 1, meta
    assert_fields(surviving[0], status="SELECTED")
    assert_fields(
        b.read_dependent(ctx.dependent["id"]), coverage_status="PENDING_VERIFICATION"
    )

    # Re-read the program, and the same re-scope is now the sanctioned supersede.
    rescoped = b.scope(ctx.program["id"], "FULL_CENSUS")
    assert_fields(
        rescoped,
        status="SCOPED",
        version=after_refusal["version"] + 1,
        in_scope_case_count=1,
        in_scope_dependent_count=1,
        pending_dependent_count=1,
    )
    assert_counter_partition(rescoped)

    rows, meta = _cases_page(client, ctx.program["id"])
    assert meta["total_count"] == 2, meta
    assert sorted(row["status"] for row in rows) == ["SELECTED", "VOIDED"], rows
    assert_fields(
        b.read_dependent(ctx.dependent["id"]), coverage_status="PENDING_VERIFICATION"
    )


def test_two_administrators_scoping_from_one_program_read_leave_a_single_case_snapshot(
    b, client
):
    """The guard matters because a re-scope legitimately supersedes the previous case
    snapshot: it voids the prior `AuditCase` rows and returns their dependents to
    `ENROLLED`. A client whose view of the program predates an earlier scope run — or
    any other program mutation — would therefore discard case state it never read.

    Design: Corner/cross-cutting complexity layers/corner_stale_program_version_blocks_a_rescope_that_would_void_unseen_cases
    """
    ctx = _draft_program_and_one_household(b)
    observed_version = ctx.program["version"]
    program_id = ctx.program["id"]

    def scope_from_the_shared_read():
        return ApiClient().run_scope(
            program_id, f.scope_payload(observed_version, "FULL_CENSUS"), PROGRAM_ADMIN
        )

    results = run_race(scope_from_the_shared_read, scope_from_the_shared_read)
    outcome = assert_race_outcome(results, 1, 1)

    validate_success(outcome["successes"][0])
    validate_error(
        outcome["failures"][0], E.ERR_STALE_PROGRAM_VERSION, expected_status=412
    )

    program = b.read_program(program_id)
    assert_fields(
        program,
        status="SCOPED",
        version=observed_version + 1,
        in_scope_case_count=1,
        in_scope_dependent_count=1,
        pending_dependent_count=1,
    )
    rows, meta = _cases_page(client, program_id)
    assert meta["total_count"] == 1, meta
    assert_fields(rows[0], status="SELECTED")


# ------------------------------------- optimistic concurrency on opening a recovery
def test_replaying_a_dependent_version_a_recovery_already_spent_supersedes_nothing(
    b, client
):
    """If it does not equal the dependent's current `version`, the request is rejected
    with `ERR_STALE_DEPENDENT_VERSION` (HTTP 412). ... Creation also supersedes: any
    prior recovery of the same dependent whose `status` is `OPEN`, or whose `status`
    is `DEMAND_ISSUED` with `recovered_cents` still exactly zero, moves to
    `SUPERSEDED`, and the program's `recovery_ledger_cents` is recomputed so the
    superseded row no longer counts.

    Design: Corner/cross-cutting complexity layers/corner_stale_dependent_version_blocks_a_recovery_that_would_supersede_an_unread_demand
    """
    ctx = _terminated_household_with_two_paid_lines(b)
    assert_fields(ctx.notice, status="FINAL", effective_date=EFFECTIVE_DATE)
    assert_fields(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="TERMINATED",
        coverage_end_date=EFFECTIVE_DATE,
    )

    observed_version = b.read_dependent(ctx.dep["id"])["version"]
    strict = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        "STRICT",
        DEFAULT_ONSET_DATE,
        expected_dependent_version=observed_version,
    )
    assert_fields(
        strict,
        status="OPEN",
        recoverable_subtotal_cents=STRICT_SUBTOTAL_CENTS,
        admin_fee_cents=0,
        net_demand_cents=0,
        recovered_cents=0,
    )

    refused = client.create_claim_recovery(
        f.claim_recovery_payload(
            ctx.dep["id"],
            ctx.notice["id"],
            observed_version,
            "EQUITABLE",
            DEFAULT_ONSET_DATE,
        ),
        RECOVERY_AGENT,
    )
    validate_error(refused, E.ERR_STALE_DEPENDENT_VERSION, expected_status=412)
    assert len(_recoveries_of(b, ctx.dep["id"])) == 1

    fresh_version = b.read_dependent(ctx.dep["id"])["version"]
    assert fresh_version != observed_version, fresh_version

    equitable = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        "EQUITABLE",
        DEFAULT_ONSET_DATE,
        expected_dependent_version=fresh_version,
    )
    assert_fields(
        equitable, status="OPEN", recoverable_subtotal_cents=EQUITABLE_SUBTOTAL_CENTS
    )
    assert_fields(b.read_recovery(strict["id"]), status="SUPERSEDED")
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == 0


def test_two_agents_opening_a_recovery_from_one_dependent_read_price_a_single_demand(b):
    """Here the destructive act is supersession: a new recovery row supersedes that
    dependent's prior `OPEN` row, or its prior `DEMAND_ISSUED` row that has collected
    nothing yet. A client operating on a stale view of the dependent would therefore
    replace a recalculated demand it never saw.

    Design: Corner/cross-cutting complexity layers/corner_stale_dependent_version_blocks_a_recovery_that_would_supersede_an_unread_demand
    """
    ctx = _terminated_household_with_two_paid_lines(b)
    observed_version = b.read_dependent(ctx.dep["id"])["version"]
    payload = f.claim_recovery_payload(
        ctx.dep["id"], ctx.notice["id"], observed_version, "STRICT", DEFAULT_ONSET_DATE
    )

    def open_from_the_shared_read():
        return ApiClient().create_claim_recovery(dict(payload), RECOVERY_AGENT)

    results = run_race(open_from_the_shared_read, open_from_the_shared_read)
    outcome = assert_race_outcome(results, 1, 1)

    opened = validate_success(outcome["successes"][0], expected_status=201)
    validate_error(
        outcome["failures"][0], E.ERR_STALE_DEPENDENT_VERSION, expected_status=412
    )

    assert_fields(
        opened, status="OPEN", recoverable_subtotal_cents=STRICT_SUBTOTAL_CENTS
    )
    standing = _recoveries_of(b, ctx.dep["id"])
    assert [row["status"] for row in standing] == ["OPEN"], standing
    assert_fields(b.read_dependent(ctx.dep["id"]), recovery_revision=1)


# --------------------------------------------- the checkpoint as an idempotent no-op
def test_running_the_checkpoint_before_the_amnesty_deadline_changes_nothing(b, client):
    """One invocation executes six steps in a fixed order, and every step whose
    preconditions are unmet is simply a no-op, which makes the checkpoint safe to
    invoke repeatedly and safe to invoke early. ... When the program's `status` is
    `AMNESTY_OPEN` and the current clock instant is at or past `amnesty_end_at`, the
    program moves `AMNESTY_OPEN → RESPONSE_WINDOW`. No case and no dependent is
    touched.

    Design: Corner/cross-cutting complexity layers/corner_sweep_is_a_no_op_checkpoint_when_no_deadline_has_passed_and_when_replayed
    """
    ctx = announced_wave(b)
    announced_version = ctx.program["version"]
    b.set_clock(AMNESTY_INSTANT)

    swept = b.sweep(ctx.program["id"])

    assert_fields(
        swept, status="AMNESTY_OPEN", sweep_epoch=0, version=announced_version
    )
    rows, meta = _cases_page(client, ctx.program["id"])
    assert meta["total_count"] == 1, meta
    assert_fields(rows[0], status="NOTIFIED")
    assert_fields(
        b.read_dependent(ctx.dep["id"]), coverage_status="PENDING_VERIFICATION"
    )
    assert _notices_of(b, ctx.dep["id"]) == []


def test_running_the_checkpoint_twice_past_the_amnesty_deadline_advances_the_epoch_once(
    b, client
):
    """The program's `sweep_epoch` and its `version` each increment by exactly 1 on a
    call in which any step mutated state, and neither moves on a call that changed
    nothing.

    Design: Corner/cross-cutting complexity layers/corner_sweep_is_a_no_op_checkpoint_when_no_deadline_has_passed_and_when_replayed
    """
    ctx = announced_wave(b)
    announced_version = ctx.program["version"]
    b.set_clock(RESPONSE_WINDOW_INSTANT)

    first = b.sweep(ctx.program["id"])
    assert_fields(
        first,
        status="RESPONSE_WINDOW",
        sweep_epoch=1,
        version=announced_version + 1,
    )

    replayed = b.sweep(ctx.program["id"])
    assert_fields(
        replayed,
        status="RESPONSE_WINDOW",
        sweep_epoch=1,
        version=announced_version + 1,
    )

    rows, meta = _cases_page(client, ctx.program["id"])
    assert meta["total_count"] == 1, meta
    assert_fields(rows[0], status="NOTIFIED")
    assert_fields(
        b.read_dependent(ctx.dep["id"]), coverage_status="PENDING_VERIFICATION"
    )
    assert _notices_of(b, ctx.dep["id"]) == []


# ------------------------------ one checkpoint call feeding its own later steps
def test_one_checkpoint_call_closes_amnesty_and_then_escalates_against_that_new_phase(
    b, client
):
    """Because the steps run in order inside one call, a single invocation made after
    the response deadline will close the amnesty window in the first step and then
    immediately escalate in the second.

    Design: Corner/cross-cutting complexity layers/corner_one_sweep_call_runs_later_steps_against_state_produced_by_earlier_steps
    """
    ctx = announced_wave(b)
    b.set_clock(LATE_SWEEP_INSTANT)

    swept = b.sweep(ctx.program["id"])

    assert_fields(
        swept,
        status="ESCALATION",
        sweep_epoch=1,
        non_responsive_case_count=1,
        termination_pending_count=1,
        pending_dependent_count=0,
        provisional_annual_savings_cents=MONTHLY_COST_CENTS["SPOUSE"] * 12,
    )
    assert_counter_partition(swept)

    rows, meta = _cases_page(client, ctx.program["id"])
    assert meta["total_count"] == 1, meta
    case = b.read_case(rows[0]["id"])
    assert_fields(case, status="ESCALATED", priority_score=55)
    assert_priority_score(
        case,
        unverified=1,
        in_scope=1,
        sensitive=False,
        reminders=0,
        max_reminders=3,
        silent=True,
    )
    assert_instant_equals(case["non_responsive_at"], LATE_SWEEP_INSTANT)
    assert_instant_equals(case["escalated_at"], LATE_SWEEP_INSTANT)


def test_the_notice_that_single_call_issues_is_dated_from_the_instant_the_call_ran(
    b, client
):
    """the computation begins from a base date: the calendar date of the notice's
    `issued_at` advanced by fourteen whole days. That base is then floored against the
    calendar date of the program's `response_deadline_at`, and the later of the two
    dates becomes the anchor. ... the notice's `effective_date` is the last calendar
    day of the month containing the anchor

    Design: Corner/cross-cutting complexity layers/corner_one_sweep_call_runs_later_steps_against_state_produced_by_earlier_steps
    """
    ctx = announced_wave(b)
    b.set_clock(LATE_SWEEP_INSTANT)
    b.sweep(ctx.program["id"])

    issued = _notices_of(b, ctx.dep["id"])
    assert len(issued) == 1, issued

    notice = b.read_notice(issued[0]["id"])
    assert_fields(
        notice,
        status="ISSUED",
        origin="AUDIT_ESCALATION",
        case_id=ctx.case["id"],
        grace_days_applied=14,
        effective_date=LATE_EFFECTIVE_DATE,
        batch_sequence_no=1,
        continuation_election_status="NOT_ELECTED",
        continuation_monthly_premium_cents=0,
        continuation_start_date=None,
        continuation_end_date=None,
    )
    assert_instant_equals(notice["issued_at"], LATE_SWEEP_INSTANT)
    assert_instant_equals(
        notice["continuation_election_deadline"], LATE_ELECTION_DEADLINE
    )

    # The effective date has not yet passed, so nothing finalised in the same call.
    assert_fields(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="TERMINATION_PENDING",
        coverage_end_date=None,
    )


# --------------------------------------- immediate visibility of a write's cascade
def test_a_voluntary_removal_is_already_visible_in_its_own_response_and_the_next_reads(
    b, client
):
    """The dependent moves `PENDING_VERIFICATION → AMNESTY_REMOVED` with its own
    `coverage_end_date` set to the removal's. ... The case moves `NOTIFIED →
    IN_PROGRESS` if this was its first response, its `unverified_dependent_count` and
    `priority_score` are recomputed

    Design: Corner/consistency model/corner_amnesty_removal_effects_are_visible_in_the_same_response_and_immediate_reads
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(AMNESTY_INSTANT)

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(
            ctx.dep2["id"], ctx.case["id"], reason_code="AGE_LIMIT_EXCEEDED"
        ),
        employee_headers(ctx.employee["id"]),
    )
    removal = validate_success(response, expected_status=201)

    assert_evidence_common_fields(removal)
    assert_fields(
        removal,
        dependent_id=ctx.dep2["id"],
        case_id=ctx.case["id"],
        coverage_end_date=AMNESTY_COVERAGE_END,
        penalty_waived=True,
        claims_recovery_waived=True,
        audited_savings_contribution_cents=(
            MONTHLY_COST_CENTS["CHILD_BIOLOGICAL"] * (12 - 9)
        ),
    )
    assert_instant_equals(removal["recorded_at"], AMNESTY_INSTANT)

    # No checkpoint runs between the write and these reads.
    assert_fields(
        b.read_case(ctx.case["id"]),
        status="IN_PROGRESS",
        unverified_dependent_count=1,
        in_scope_dependent_count=2,
    )
    assert_fields(
        b.read_dependent(ctx.dep2["id"]),
        coverage_status="AMNESTY_REMOVED",
        coverage_end_date=AMNESTY_COVERAGE_END,
    )
    assert_fields(
        b.read_dependent(ctx.dep["id"]), coverage_status="PENDING_VERIFICATION"
    )


def test_a_voluntary_removal_re_derives_the_program_ledgers_without_a_checkpoint_run(
    b, client
):
    """At the program level, `amnesty_removed_count` and `pending_dependent_count` are
    recomputed, `audited_annual_savings_cents` grows by the removal's
    `audited_savings_contribution_cents`, and `provisional_annual_savings_cents` is
    recomputed as well.

    Design: Corner/consistency model/corner_amnesty_removal_effects_are_visible_in_the_same_response_and_immediate_reads
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(AMNESTY_INSTANT)
    monthly = MONTHLY_COST_CENTS["CHILD_BIOLOGICAL"]

    validate_success(
        client.create_amnesty_removal(
            f.amnesty_removal_payload(
                ctx.dep2["id"], ctx.case["id"], reason_code="AGE_LIMIT_EXCEEDED"
            ),
            employee_headers(ctx.employee["id"]),
        ),
        expected_status=201,
    )

    program = b.read_program(ctx.program["id"])
    assert_fields(
        program,
        amnesty_removed_count=1,
        pending_dependent_count=1,
        in_scope_dependent_count=2,
        provisional_annual_savings_cents=monthly * 12,
        audited_annual_savings_cents=monthly * (12 - 9),
    )
    assert_counter_partition(program)
