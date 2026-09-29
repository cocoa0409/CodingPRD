"""Operations whose legality is owned by a neighbouring entity's state.

In each scenario the request body never changes: only the state of a parent or a
sibling record decides whether the identical call is refused or accepted.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    RECONCILE_INSTANT,
    audit_wave,
    demand_wave,
)
from test_helpers.test_users import PROGRAM_ADMIN, employee_headers


def _scoped_program_with_a_selected_case(b):
    """A scoped-but-unannounced program: the case exists but the audit is not live."""
    ctx = audit_wave(b, stage="SCOPED", relationships=("SPOUSE",))
    assert ctx.program["status"] == "SCOPED"
    assert ctx.case["status"] == "SELECTED"
    return ctx


def _submission_payload(ctx):
    return f.proof_submission_payload(
        ctx.case["id"], ctx.dep["id"], "MARRIAGE_CERTIFICATE"
    )


def test_a_submission_against_a_scoped_program_is_refused_on_the_program_phase(b, client):
    """The parent program's phase decides, ahead of the case's own status.

    PRD: "9. Program phase admits the operation — `ERR_PROGRAM_PHASE_INVALID`
    (409), across all program, case, submission, amnesty, and appeal write
    endpoints."

    Design: Difficulty/cross_entity_state_dependency/proof_submission_gated_on_audit_program_phase
    """
    ctx = _scoped_program_with_a_selected_case(b)

    response = client.create_proof_submission(
        _submission_payload(ctx), employee_headers(ctx.employee["id"])
    )

    validate_error(response, E.ERR_PROGRAM_PHASE_INVALID, 409)
    _rows, meta = b.submissions(dependent_id=ctx.dep["id"])
    assert meta["total_count"] == 0


def test_announcing_the_program_is_the_only_change_that_admits_the_same_submission(b, client):
    """Nothing about the payload moves; the program's own transition unlocks it.

    PRD: "Submissions are accepted only into a live audit. The program must be in
    `AMNESTY_OPEN` or `RESPONSE_WINDOW`; the case must be in `NOTIFIED` or
    `IN_PROGRESS`"

    Design: Difficulty/cross_entity_state_dependency/proof_submission_gated_on_audit_program_phase
    """
    ctx = _scoped_program_with_a_selected_case(b)
    payload = _submission_payload(ctx)
    refused = client.create_proof_submission(
        payload, employee_headers(ctx.employee["id"])
    )
    validate_error(refused, E.ERR_PROGRAM_PHASE_INVALID, 409)

    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(ctx.program["id"])
    assert b.read_program(ctx.program["id"])["status"] == "AMNESTY_OPEN"
    assert b.read_case(ctx.case["id"])["status"] == "NOTIFIED"

    submission = b.submit_proof(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], "MARRIAGE_CERTIFICATE"
    )

    assert submission["review_status"] == "SUBMITTED"
    case = b.read_case(ctx.case["id"])
    assert case["status"] == "IN_PROGRESS"
    assert case["proof_submission_count"] == 1


# One medical line of 150000 cents recovered STRICT: fee 7500 at the five percent
# tier, so the demand raised is 157500.
DEMAND_SUBTOTAL_CENTS = 150000
DEMAND_TOTAL_CENTS = 157500
# SPOUSE monthly cost prorated by twelve minus October, the coverage-end month.
AUDITED_SAVINGS_CENTS = 99426


def _reconciling_program_with_an_outstanding_demand(b):
    """A program whose only case has closed but whose demand is still uncollected."""
    ctx = demand_wave(b, relationships=("SPOUSE",))
    assert ctx.recovery["recoverable_subtotal_cents"] == DEMAND_SUBTOTAL_CENTS
    assert ctx.recovery["net_demand_cents"] == DEMAND_TOTAL_CENTS
    assert ctx.recovery["status"] == "DEMAND_ISSUED"

    b.set_clock(RECONCILE_INSTANT)
    b.sweep(ctx.program["id"])
    ctx.program = b.read_program(ctx.program["id"])
    assert ctx.program["status"] == "RECONCILIATION"
    assert b.read_case(ctx.case["id"])["status"] == "CLOSED"
    return ctx


def test_the_close_is_refused_while_a_demand_of_the_program_is_still_outstanding(b, client):
    """A sibling recovery row, not the program itself, blocks the terminal move.

    PRD: "no claim recovery of this program's in-scope dependents may sit in
    `DEMAND_ISSUED` or `PARTIALLY_RECOVERED`, or the close is refused with
    `ERR_OPEN_RECOVERIES_REMAIN`."

    Design: Difficulty/cross_entity_state_dependency/program_close_gated_on_outstanding_claim_recovery_state
    """
    ctx = _reconciling_program_with_an_outstanding_demand(b)

    response = client.close_program(ctx.program["id"], {}, PROGRAM_ADMIN)

    validate_error(response, E.ERR_OPEN_RECOVERIES_REMAIN, 409)
    assert b.read_program(ctx.program["id"])["status"] == "RECONCILIATION"


def test_collecting_the_demand_in_full_is_the_only_change_that_admits_the_close(b, client):
    """Only the recovery row moves; the program is then free to shut.

    PRD: "On success the program moves `RECONCILIATION → CLOSED`, which is
    terminal, and its `version` increments."

    Design: Difficulty/cross_entity_state_dependency/program_close_gated_on_outstanding_claim_recovery_state
    """
    ctx = _reconciling_program_with_an_outstanding_demand(b)
    refused = client.close_program(ctx.program["id"], {}, PROGRAM_ADMIN)
    validate_error(refused, E.ERR_OPEN_RECOVERIES_REMAIN, 409)

    paid = b.payment(
        ctx.recovery["id"], DEMAND_TOTAL_CENTS, received_date="2026-11-17"
    )
    assert paid["status"] == "RECOVERED"
    assert paid["recovered_cents"] == DEMAND_TOTAL_CENTS

    closed = b.close_program(ctx.program["id"])

    assert closed["status"] == "CLOSED"
    assert closed["recovery_ledger_cents"] == DEMAND_TOTAL_CENTS
    assert closed["recovered_total_cents"] == DEMAND_TOTAL_CENTS
    assert closed["audited_annual_savings_cents"] == AUDITED_SAVINGS_CENTS
