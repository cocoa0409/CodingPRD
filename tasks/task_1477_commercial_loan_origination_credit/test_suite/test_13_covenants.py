"""Covenant monitoring: pass/fail measurement rules, the breach cascade, cure and
waiver resolution, and the breach-cure-breach cycle (PRD section 3.8).
"""
from test_helpers import (
    ApiErrorId, api_client, deal_funded, get_borrower, list_exceptions,
    review_covenant, validate_error, validate_paginated, validate_success,
)


def _funded_deal_with_breach():
    """FUNDED 200,000,000 deal (first tranche 120,000,000 released); DSCR_MIN 1.25
    QUARTERLY covenant driven to BREACH_PENDING by a 1.1 measurement."""
    ctx = deal_funded(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        first_tranche_cents=120_000_000)
    return ctx


def test_first_breach_cascade():
    """PRD section 3.8: "A failing measurement moves the covenant — whether from
    `MONITORING`, `COMPLIANT`, or `CURED` — to `BREACH_PENDING` and fires a two-hop
    cascade: the system auto-creates a `COVENANT_BREACH` policy exception of `HIGH`
    severity for the application, and the borrower's `status` is set to `SUSPENDED`".
    PRD section 3.8: "a `DSCR_MIN` covenant passes when the measured value is
    greater than or equal to its `threshold_value`".

    Design: Difficulty/non_linear_state_machine/covenant_breach_cure_breach_cycle
    """
    ctx = _funded_deal_with_breach()
    o = ctx["o"]
    cov = ctx["covenant"]

    reviewed = review_covenant(o, cov["id"], 1.1, "2026-09-30")
    assert reviewed["status"] == "BREACH_PENDING", "1.1000 < 1.2500 fails DSCR_MIN"

    breach = list_exceptions(o, ctx["application"]["id"], rule_code="COVENANT_BREACH",
                             status="OPEN")
    assert len(breach) == 1
    assert breach[0]["severity"] == "HIGH"

    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["status"] == "SUSPENDED"


def test_cure_then_rebreach_cycle():
    """PRD section 3.8: "A subsequent passing measurement moves `BREACH_PENDING` →
    `CURED`, moves the linked `OPEN` `COVENANT_BREACH` exception to
    `RESOLVED_BY_CHANGE`, and restores the borrower to `ACTIVE` provided no other
    covenant of that borrower remains in `BREACH_PENDING`." and "A `CURED` covenant
    that fails again re-enters `BREACH_PENDING` with the same cascade; the
    breach-cure cycle can repeat indefinitely." and a passing review "records the
    review's `period_end_date` as its `last_reviewed_period`" (section 3.8).

    Design: Difficulty/non_linear_state_machine/covenant_breach_cure_breach_cycle
    """
    ctx = _funded_deal_with_breach()
    o = ctx["o"]
    cov = ctx["covenant"]
    app_id = ctx["application"]["id"]

    review_covenant(o, cov["id"], 1.1, "2026-09-30")
    breach1 = list_exceptions(o, app_id, rule_code="COVENANT_BREACH", status="OPEN")[0]

    cured = review_covenant(o, cov["id"], 1.3, "2026-12-31")
    assert cured["status"] == "CURED", "BREACH_PENDING -> CURED on a passing review"
    assert cured["last_reviewed_period"] == "2026-12-31"

    resolved = list_exceptions(o, app_id, rule_code="COVENANT_BREACH")
    by_id = {e["id"]: e for e in resolved}
    assert by_id[breach1["id"]]["status"] == "RESOLVED_BY_CHANGE"
    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["status"] == "ACTIVE", "no other BREACH_PENDING covenant exists"

    rebreach = review_covenant(o, cov["id"], 1.2, "2027-03-31")
    assert rebreach["status"] == "BREACH_PENDING", "CURED -> BREACH_PENDING cycle"
    assert rebreach["last_reviewed_period"] == "2027-03-31"

    open_now = list_exceptions(o, app_id, rule_code="COVENANT_BREACH", status="OPEN")
    assert len(open_now) == 1
    assert open_now[0]["id"] != breach1["id"], "a SECOND breach exception was created"
    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["status"] == "SUSPENDED"


def test_covenant_waive_breach_restores_borrower():
    """PRD section 3.8: "a `CreditPolicyOfficer` may waive the breach with a
    `waiver_rationale` of at least twenty characters, moving `BREACH_PENDING` →
    `WAIVED`, moving the linked `OPEN` exception to `WAIVED`, and restoring the
    borrower to `ACTIVE` under the same no-other-breach condition."

    Design: Corner/state_machines/covenant_waive_breach_restores_borrower
    """
    ctx = _funded_deal_with_breach()
    o = ctx["o"]
    cov = ctx["covenant"]
    review_covenant(o, cov["id"], 1.1, "2026-09-30")
    breach = list_exceptions(o, ctx["application"]["id"], rule_code="COVENANT_BREACH",
                             status="OPEN")[0]
    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["status"] == "SUSPENDED"

    waived = validate_success(api_client.waive_covenant_breach(
        cov["id"], {"waiver_rationale": "Borrower injected cure capital post-period"},
        o["po"]["headers"]), 200)
    assert waived["status"] == "WAIVED"

    excs = list_exceptions(o, ctx["application"]["id"], rule_code="COVENANT_BREACH")
    by_id = {e["id"]: e for e in excs}
    assert by_id[breach["id"]]["status"] == "WAIVED", (
        "the waiver path — not RESOLVED_BY_CHANGE")

    bor_after = get_borrower(o, ctx["borrower"]["id"])
    assert bor_after["status"] == "ACTIVE"


def test_waive_breach_requires_breach_pending():
    """PRD section 3.8: waive-breach moves "`BREACH_PENDING` → `WAIVED`" — and PRD
    section 2.8: "The target entity is in a legal from-state for the requested
    transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/waive_breach_requires_breach_pending
    """
    ctx = _funded_deal_with_breach()
    o = ctx["o"]
    cov = ctx["covenant"]
    assert cov["status"] == "MONITORING"

    resp = api_client.waive_covenant_breach(
        cov["id"], {"waiver_rationale": "Prophylactic waiver before any breach"},
        o["po"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _ = validate_paginated(api_client.list_application_covenants(
        ctx["application"]["id"], o["po"]["headers"]))
    assert rows[0]["status"] == "MONITORING"
    assert list_exceptions(o, ctx["application"]["id"], status="OPEN") == []
