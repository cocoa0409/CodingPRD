"""Holder audits: the audit_hold submission block, the assessed-close penalty and
hold clearing, and the info-request cycle.

Translates queue A (cross_entity_state_dependency/report_submit_blocked_by_holder_audit)
and queue B (audit close-assess side effects, audit info-request cycle).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
)
from test_helpers.test_users import make_examiner_headers, make_holder_headers


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/report_submit_blocked_by_holder_audit
# ---------------------------------------------------------------------------
def _report_ready_with_audit_hold(api):
    ctx = fixtures.setup_draft_report_with_property(api, dormancy_basis="ISSUANCE",
                                                    interest_bearing=False, amount_cents=50000)
    ex = make_examiner_headers()
    case = validate_success(api.create_audit_case(
        f.create_audit_case_payload(ctx["holder"]["id"]), ex), 201)
    ctx["audit_case"] = case
    return ctx, ex


def test_submit_blocked_while_holder_under_audit(api):
    """PRD §3.4: "First, the filing holder's audit_hold must be false; a report submitted while
    the holder is under audit is rejected with ERR_HOLDER_UNDER_AUDIT (HTTP 409)."

    A DRAFT report with a correctly reconciled total (50000) cannot be submitted while its holder
    has an OPEN audit case; the report stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/report_submit_blocked_by_holder_audit
    """
    ctx, ex = _report_ready_with_audit_hold(api)
    hh = ctx["holder_headers"]
    validate_error(api.submit_report(ctx["report_id"],
                   {"declared_total_cents": ctx["total_remitted_cents"]}, hh),
                   ApiErrorId.ERR_HOLDER_UNDER_AUDIT.value)
    after = validate_success(api.get_report(ctx["report_id"], hh), 200)
    assert after["status"] == "DRAFT"


def test_open_audit_case_sets_holder_audit_hold(api):
    """PRD §3.9: "Opening a case also sets the holder's audit_hold to true. A holder's audit_hold
    is true whenever at least one of its audit cases is in a non-terminal state — that is, OPEN
    or INFO_REQUESTED — and, per Section 3.4, a true audit_hold blocks that holder from
    submitting reports."

    Design: Difficulty/cross_entity_state_dependency/report_submit_blocked_by_holder_audit
    """
    ctx, ex = _report_ready_with_audit_hold(api)
    holder = validate_success(api.get_holder(ctx["holder"]["id"], ctx["holder_headers"]), 200)
    assert holder["audit_hold"] is True, "an OPEN audit case must set audit_hold true"


# ---------------------------------------------------------------------------
# Corner/state_machines/audit_close_assess_sets_penalty_and_clears_hold
# ---------------------------------------------------------------------------
def test_close_assess_records_penalty_and_clears_hold(api):
    """PRD §3.9: "An assessed close records an audit finding: it carries an assessed_penalty_cents
    amount, which must be at least 1, and free-text findings, moves the case to CLOSED_ASSESSED,
    adds the case's assessed_penalty_cents to the holder's running assessed_penalty_cents total,
    sets the holder's status to SUSPENDED, and likewise recomputes the holder's audit_hold (which
    becomes false once no other case for the holder remains OPEN or INFO_REQUESTED)."

    Design: Corner/state_machines/audit_close_assess_sets_penalty_and_clears_hold
    """
    setup = fixtures.setup_open_audit_case(api)
    ex = make_examiner_headers()
    case = validate_success(api.close_assess(setup["audit_case"]["id"],
                            f.close_assess_payload(25000, "Late report"), ex), 200)
    assert case["status"] == "CLOSED_ASSESSED"
    holder = validate_success(api.get_holder(setup["holder"]["id"], setup["holder_headers"]), 200)
    assert holder["assessed_penalty_cents"] == 25000, \
        f"penalty must add 25000 to the holder total, got {holder['assessed_penalty_cents']}"
    assert holder["audit_hold"] is False, "closing the only case must clear audit_hold"


# ---------------------------------------------------------------------------
# Corner/state_machines/audit_info_request_provide_cycle
# ---------------------------------------------------------------------------
def test_audit_info_request_then_provide_cycle(api):
    """PRD §3.9: "During an audit the examiner may request information from the holder, moving the
    case from OPEN to INFO_REQUESTED; the holder responds by providing the requested information,
    returning the case from INFO_REQUESTED to OPEN. This information loop may repeat."

    Design: Corner/state_machines/audit_info_request_provide_cycle
    """
    setup = fixtures.setup_open_audit_case(api)
    ex = make_examiner_headers()
    hh = setup["holder_headers"]
    requested = validate_success(api.request_info(setup["audit_case"]["id"], ex), 200)
    assert requested["status"] == "INFO_REQUESTED"
    provided = validate_success(api.provide_info(setup["audit_case"]["id"], hh), 200)
    assert provided["status"] == "OPEN", f"provide-info must return the case to OPEN, got {provided['status']}"
