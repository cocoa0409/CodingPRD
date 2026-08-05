"""Statement drafting, submission, the return/resubmit cycle, and state/ownership gates.

Queue A: non_linear_state_machine (statement cycle), cross_entity_state_dependency
(filer active). Queue B: accept-from-draft, duplicate, closed period, ownership isolation.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_statement_payload,
    make_filer_headers,
    register_jurisdiction, register_filer, make_training_current, open_filing_period,
    create_draft_statement, setup_returned_statement, setup_submitted_statement,
    api_client,
)


def test_returned_then_resubmit_back_to_submitted(api, ethics_officer_headers):
    """PRD 3.3: "A `RETURNED_FOR_CORRECTION` statement may be resubmitted, moving it back to
    `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/statement_returned_resubmit_cycle
    """
    ctx = setup_returned_statement()
    assert ctx["statement"]["status"] == "RETURNED_FOR_CORRECTION"
    filer = ctx["filer"]
    res = api.submit_statement(ctx["statement"]["id"], {}, make_filer_headers(filer["id"]))
    stmt = validate_success(res, 200)
    assert stmt["status"] == "SUBMITTED"


def test_correction_round_preserved_after_resubmit(api):
    """PRD 3.5: "Returning a statement requires it to be `SUBMITTED`, moves it
    `SUBMITTED → RETURNED_FOR_CORRECTION`, and increments `correction_round` by 1".

    Design: Difficulty/non_linear_state_machine/statement_returned_resubmit_cycle
    """
    ctx = setup_returned_statement()
    filer = ctx["filer"]
    res = api.submit_statement(ctx["statement"]["id"], {}, make_filer_headers(filer["id"]))
    stmt = validate_success(res, 200)
    assert stmt["correction_round"] == 1


def test_separated_filer_cannot_submit(api, registrar_headers):
    """PRD 3.3: "Four preconditions guard the initial submission: the statement is in `DRAFT`;
    the owning filer's registry `status` is `ACTIVE`".
    PRD 3.3: "a submission from any state other than `DRAFT` (or `RETURNED_FOR_CORRECTION`,
    below) is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_filer_active
    """
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="SENIOR_STAFF")
    make_training_current(filer["id"])
    period = open_filing_period(jur["id"], due_at="2026-06-01T00:00:00Z")
    stmt = create_draft_statement(filer["id"], period["id"])
    api.set_filer_status(filer["id"], {"status": "SEPARATED"}, registrar_headers)
    res = api.submit_statement(stmt["id"], {}, make_filer_headers(filer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_separated_filer_submit_leaves_statement_draft(api, registrar_headers):
    """PRD 3.1: "only an `ACTIVE` filer may submit statements or file gift reports."

    Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_filer_active
    """
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="SENIOR_STAFF")
    make_training_current(filer["id"])
    period = open_filing_period(jur["id"], due_at="2026-06-01T00:00:00Z")
    stmt = create_draft_statement(filer["id"], period["id"])
    api.set_filer_status(filer["id"], {"status": "SEPARATED"}, registrar_headers)
    api.submit_statement(stmt["id"], {}, make_filer_headers(filer["id"]))
    after = validate_success(api.get_statement(stmt["id"], registrar_headers), 200)
    assert after["status"] == "DRAFT"


def test_accept_draft_statement_invalid_state(api, ethics_officer_headers):
    """PRD 3.5: "Acceptance requires the statement to be `SUBMITTED` and moves it
    `SUBMITTED → ACCEPTED`".
    PRD 3.5: "Acting on a statement that is not `SUBMITTED` from either of these operations is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_from_draft_returns_invalid_state
    """
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="ELECTED")
    period = open_filing_period(jur["id"], due_at="2026-06-01T00:00:00Z")
    stmt = create_draft_statement(filer["id"], period["id"])
    res = api.accept_statement(stmt["id"], {}, ethics_officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_duplicate_statement_conflict(api):
    """PRD 3.3: "At most one non-superseded statement may exist for a given `filer_id` and
    `filing_period_id` pair; a second one is rejected with `ERR_DUPLICATE_STATEMENT` (HTTP 409)."

    Design: Corner/validations/duplicate_statement_returns_conflict
    """
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="ELECTED")
    period = open_filing_period(jur["id"], due_at="2026-06-01T00:00:00Z")
    create_draft_statement(filer["id"], period["id"])
    res = api.create_statement(
        create_statement_payload(filer["id"], period["id"]), make_filer_headers(filer["id"]))
    validate_error(res, "ERR_DUPLICATE_STATEMENT")


def test_statement_against_closed_period(api):
    """PRD 3.3: "The referenced period must be `OPEN`; creating a statement against a `CLOSED`
    period is rejected with `ERR_PERIOD_CLOSED` (HTTP 409)."

    Design: Corner/validations/statement_create_against_closed_period_returns_error
    """
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="ELECTED")
    period = open_filing_period(jur["id"], coverage_start="2023-01-01T00:00:00Z",
                                coverage_end="2023-12-31T00:00:00Z",
                                due_at="2024-06-01T00:00:00Z", status="CLOSED")
    res = api.create_statement(
        create_statement_payload(filer["id"], period["id"]), make_filer_headers(filer["id"]))
    validate_error(res, "ERR_PERIOD_CLOSED")


def test_filer_cannot_submit_others_statement(api, registrar_headers):
    """PRD 3.3: "Only the owning filer may submit; another filer is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/filer_cannot_submit_other_filers_statement
    """
    jur = register_jurisdiction()
    filer_a = register_filer(jur["id"], filer_category="ELECTED", full_name="Filer A")
    filer_b = register_filer(jur["id"], filer_category="APPOINTED", full_name="Filer B")
    make_training_current(filer_a["id"])
    period = open_filing_period(jur["id"], due_at="2026-06-01T00:00:00Z")
    stmt = create_draft_statement(filer_a["id"], period["id"])
    res = api.submit_statement(stmt["id"], {}, make_filer_headers(filer_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
