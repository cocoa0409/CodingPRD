"""Multi-resource cascades: acceptance -> penalty -> delinquency -> withhold, and
sustained adjudication -> substantiate -> flag; plus the pay-to-restore compensation.

Queue A: transitive_cascade (accept withhold depth-3, adjudicate flag depth-2).
Queue B: pay_restores_withheld_statement_to_published.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_adjudicator_headers, make_filer_headers,
    setup_delinquent_filer_with_withheld_statement,
    setup_accepted_statement_under_investigation,
)


def test_accept_assesses_penalty_and_makes_delinquent(api, registrar_headers):
    """PRD 3.4: "the assessment increments the owning filer's `outstanding_penalty_cents` by
    `assessed_amount_cents` and recomputes `compliance_status`. If that recomputation flips the
    filer to `DELINQUENT`".

    Design: Difficulty/transitive_cascade/accept_late_statement_penalty_filer_withhold
    """
    ctx = setup_delinquent_filer_with_withheld_statement()
    assert ctx["penaltyB"]["status"] == "ASSESSED"
    assert ctx["penaltyB"]["assessed_amount_cents"] == 45000
    filer = validate_success(api.get_filer(ctx["filer"]["id"], registrar_headers), 200)
    assert filer["outstanding_penalty_cents"] == 45000
    assert filer["compliance_status"] == "DELINQUENT"


def test_delinquency_withholds_published_statement(api, registrar_headers):
    """PRD 3.4: "If that recomputation flips the filer to `DELINQUENT`, every one of that filer's
    statements currently `PUBLISHED` is moved to `WITHHELD`."

    Design: Difficulty/transitive_cascade/accept_late_statement_penalty_filer_withhold
    """
    ctx = setup_delinquent_filer_with_withheld_statement()
    stmt_a = validate_success(api.get_statement(ctx["stmtA"]["id"], registrar_headers), 200)
    assert stmt_a["public_status"] == "WITHHELD"


def test_sustain_substantiates_complaint(api, registrar_headers):
    """PRD 3.8: "A decision to sustain moves the investigation `OPEN → SUSTAINED`. On sustaining,
    the system sets `final_sanction_cents` to the lesser of the jurisdiction's `penalty_cap_cents`
    and the `recommended_sanction_cents`; transitions the parent complaint
    `SCREENED → SUBSTANTIATED`".

    Design: Difficulty/transitive_cascade/adjudicate_sustained_complaint_flag_statement
    """
    ctx = setup_accepted_statement_under_investigation(investigator_id="inv-1")
    res = api.adjudicate_investigation(
        ctx["investigation"]["id"],
        {"decision": "SUSTAINED", "recommended_sanction_cents": 30000, "findings": "asset omitted"},
        make_adjudicator_headers("adj-1"))
    inv = validate_success(res, 200)
    assert inv["status"] == "SUSTAINED"
    assert inv["final_sanction_cents"] == 30000
    complaint = validate_success(api.get_complaint(ctx["complaint"]["id"], registrar_headers), 200)
    assert complaint["status"] == "SUBSTANTIATED"


def test_sustain_flags_subject_statement(api, registrar_headers):
    """PRD 3.8: "When the complaint substantiates and it carries a `statement_id`, that statement
    transitions `ACCEPTED → FLAGGED`".

    Design: Difficulty/transitive_cascade/adjudicate_sustained_complaint_flag_statement
    """
    ctx = setup_accepted_statement_under_investigation(investigator_id="inv-1")
    api.adjudicate_investigation(
        ctx["investigation"]["id"],
        {"decision": "SUSTAINED", "recommended_sanction_cents": 30000, "findings": "asset omitted"},
        make_adjudicator_headers("adj-1"))
    stmt = validate_success(api.get_statement(ctx["statement"]["id"], registrar_headers), 200)
    assert stmt["status"] == "FLAGGED"


def test_pay_restores_withheld_statement(api, registrar_headers):
    """PRD 3.4: "If that recomputation flips the filer back to `COMPLIANT`, every one of that
    filer's `WITHHELD` statements is restored to `PUBLISHED`."

    Design: Corner/state_machines/pay_restores_withheld_statement_to_published
    """
    ctx = setup_delinquent_filer_with_withheld_statement()
    res = api.pay_penalty(ctx["penaltyB"]["id"], {}, make_filer_headers(ctx["filer"]["id"]))
    validate_success(res, 200)
    filer = validate_success(api.get_filer(ctx["filer"]["id"], registrar_headers), 200)
    assert filer["outstanding_penalty_cents"] == 0
    assert filer["compliance_status"] == "COMPLIANT"
    stmt_a = validate_success(api.get_statement(ctx["stmtA"]["id"], registrar_headers), 200)
    assert stmt_a["public_status"] == "PUBLISHED"
