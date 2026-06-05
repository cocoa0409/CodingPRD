"""Transitive cascades (close-chain, covenant-freeze-blocks-draw), validation-priority
conflicts, cross-entity activation gates, and compensating invariants (Queue A:
transitive_cascade, priority_pair_validation_conflict, cross_entity_state_dependency,
compensating_invariant)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_line,
    setup_application_line,
    book_draw,
    set_clock,
    ApiErrorId,
    TEST_USERS,
    make_loan_servicer_headers,
)

SERVICER = TEST_USERS["loan_servicer_headers"]
OFFICER = TEST_USERS["loan_officer_headers"]


# --- transitive_cascade: close cascade fee -> lien -> property --------------

def _line_for_close_cascade():
    """DRAW line, balance 0, clock 2026-06-01 (within draw period), credit_limit
    50000000 -> EARLY_CLOSURE tier1 (years_remaining >= 8) fee 1000000."""
    return setup_active_line(
        clock="2026-06-01T00:00:00Z",
        index_effective="2026-01-01T00:00:00Z",
        heloc_overrides={"credit_limit_cents": 50000000},
    )


def test_close_cascade_releases_lien_and_property(api):
    """PRD §3.11: "When closure succeeds, every covenant of the line is set to CURED,
    the line's LienRecord is set to RELEASED, the property's status is set to RELEASED
    if no other RECORDED lien record still references it, and the line's version is
    incremented by 1."

    Close in DRAW pre-draw-end assesses EARLY_CLOSURE 1000000; paying it then closing
    completes -> CLOSED, lien RELEASED, property RELEASED.

    Design: Difficulty/transitive_cascade/close_cascade_fee_lien_property_release
    """
    ctx = _line_for_close_cascade()
    hl_id = ctx["heloc"]["id"]
    prop_id = ctx["property"]["id"]

    # First close attempt assesses the EARLY_CLOSURE fee and is blocked while OUTSTANDING.
    first = api.close_heloc(hl_id, SERVICER)
    validate_error(first, ApiErrorId.ERR_FEES_OUTSTANDING)

    fees, _ = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "EARLY_CLOSURE"})
    )
    assert len(fees) == 1
    fee_amount = fees[0]["amount_cents"]
    validate_success(api.create_payment(hl_id, {"amount_cents": fee_amount}, SERVICER), 201)

    closed = validate_success(api.close_heloc(hl_id, SERVICER))
    assert closed["status"] == "CLOSED"

    liens, _ = validate_paginated(api.list_heloc_lien_records(hl_id, SERVICER))
    assert len(liens) == 1
    assert liens[0]["status"] == "RELEASED", "lien must be RELEASED on close"

    prop_after = validate_success(api.get_property(prop_id, SERVICER))
    assert prop_after["status"] == "RELEASED", "property must be RELEASED when no other lien references it"


def test_close_cascade_early_closure_fee_assessed(api):
    """PRD §3.11: "If the line is closed from DRAW while the logical clock is before the
    origination_date plus draw_period_years, an early-closure penalty is assessed as a
    fee assessment of type EARLY_CLOSURE."
    PRD §3.11: "The tier rate, expressed in basis points of the credit_limit_cents, is
    200 bps when at least 8 years remain ..."

    credit_limit 50000000, years_remaining >= 8 -> 200bps -> fee 1000000.

    Design: Difficulty/transitive_cascade/close_cascade_fee_lien_property_release
    """
    ctx = _line_for_close_cascade()
    hl_id = ctx["heloc"]["id"]
    validate_error(api.close_heloc(hl_id, SERVICER), ApiErrorId.ERR_FEES_OUTSTANDING)
    fees, _ = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "EARLY_CLOSURE"})
    )
    assert fees[0]["amount_cents"] == 1000000, (
        f"expected EARLY_CLOSURE 1000000 (200bps of 50000000), got {fees[0]['amount_cents']}"
    )


# --- transitive_cascade: covenant evaluate freezes line, blocks draw --------

def test_covenant_breach_freezes_line_and_blocks_draw(api):
    """PRD §3.8: "on breach, if the line is in DRAW it is transitioned from DRAW to
    FROZEN (a covenant breach freezes the line) ..."
    PRD §3.4: "A draw is permitted only while the line's status is exactly DRAW; an
    attempt to draw against a line that is FROZEN, REPAYMENT, DEFAULTED, or otherwise
    not in DRAW is rejected with ERR_DRAWS_NOT_PERMITTED (HTTP 409)."

    Evaluating a breachable MAX_CLTV freezes the line; a subsequent draw is rejected.

    Design: Difficulty/transitive_cascade/covenant_evaluate_freezes_line_blocks_draw
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    frozen = validate_success(api.evaluate_covenant(hl_id, ctx["covenants"]["MAX_CLTV"]["id"], SERVICER))
    assert frozen["status"] == "BREACHED"

    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["status"] == "FROZEN"
    assert heloc["available_credit_cents"] == 0

    resp = api.create_draw(hl_id, {"amount_cents": 100000}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DRAWS_NOT_PERMITTED)


def test_covenant_breach_zeroes_available_credit(api):
    """PRD §3.9: "Beyond a covenant-driven freeze ... moving it from DRAW to FROZEN,
    setting available_credit_cents to 0 so that no further draws are possible ..."

    Design: Difficulty/transitive_cascade/covenant_evaluate_freezes_line_blocks_draw
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    validate_success(api.evaluate_covenant(hl_id, ctx["covenants"]["MAX_CLTV"]["id"], SERVICER))
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["available_credit_cents"] == 0


# --- priority_pair_validation_conflict --------------------------------------

def test_frozen_draw_reports_state_error_over_fiscal(api):
    """PRD §3.12: "Authentication of the headers comes first ..., then role
    authorization ..., then existence of path-referenced resources left-to-right ...,
    then resolution of body foreign-key references ..., then the state-transition guard
    (ERR_INVALID_STATE). Only after these do the business-specific checks apply."
    PRD §3.4: "an attempt to draw against a line that is FROZEN ... is rejected with
    ERR_DRAWS_NOT_PERMITTED (HTTP 409)."

    A FROZEN line (available 0) drawn for 100000 fails both the state guard and the
    credit check; the state guard fires -> ERR_DRAWS_NOT_PERMITTED, not
    ERR_INSUFFICIENT_CREDIT.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_draw
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    validate_success(api.freeze_heloc(hl_id, SERVICER))
    resp = api.create_draw(hl_id, {"amount_cents": 100000}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DRAWS_NOT_PERMITTED)


def test_frozen_draw_state_error_holds_even_within_credit(api):
    """PRD §3.4: "A draw is permitted only while the line's status is exactly DRAW; an
    attempt to draw against a line that is FROZEN, REPAYMENT, DEFAULTED, or otherwise not
    in DRAW is rejected with ERR_DRAWS_NOT_PERMITTED (HTTP 409)."

    Even a tiny draw of 1 against a freshly frozen line (whose available_credit was the
    full limit before freeze) is rejected on the state guard, confirming the state check
    is independent of the fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_draw
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    validate_success(api.freeze_heloc(hl_id, SERVICER))
    resp = api.create_draw(hl_id, {"amount_cents": 1}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DRAWS_NOT_PERMITTED)


def test_segregation_reported_before_breached_covenant_on_default(api):
    """PRD §3.12: "For default declaration in particular, the segregation-of-duties
    check (ERR_SEGREGATION_OF_DUTIES) is evaluated before the breached-covenant check
    (ERR_NO_BREACHED_COVENANT)."
    PRD §3.10: "the acting servicer's X-User-ID must not equal the identifier of the
    officer who activated this line — enforcing segregation of duties — otherwise the
    declaration is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    The activating officer (acting as servicer, same X-User-ID) declares default citing
    a SATISFIED covenant: both checks would fail; segregation fires first.

    Design: Difficulty/priority_pair_validation_conflict/segregation_before_breached_covenant_on_default
    """
    ctx = setup_active_line(activate_user_id="officer-A")
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_DELINQUENCY_DAYS"]["id"]
    same_user_servicer = make_loan_servicer_headers("officer-A")
    resp = api.declare_default(hl_id, {"covenant_id": cov_id}, same_user_servicer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_segregation_blocks_self_declaration_on_breached_covenant(api):
    """PRD §3.10: "the acting servicer's X-User-ID must not equal the identifier of the
    officer who activated this line — enforcing segregation of duties — otherwise the
    declaration is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    The same identity that activated the line attempts to declare default citing a
    genuinely BREACHED covenant: the breached-covenant precondition is satisfied, yet the
    segregation check still rejects because it is evaluated first.

    Design: Difficulty/priority_pair_validation_conflict/segregation_before_breached_covenant_on_default
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        activate_user_id="officer-A",
    )
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]
    book_draw(hl_id, 90000000)
    validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))  # covenant now BREACHED
    same_user_servicer = make_loan_servicer_headers("officer-A")
    resp = api.declare_default(hl_id, {"covenant_id": cov_id}, same_user_servicer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


# --- cross_entity_state_dependency ------------------------------------------

def test_activate_blocked_when_borrower_kyc_pending(api):
    """PRD §3.3: "The borrower's kyc_status must be CLEARED, otherwise activation fails
    with ERR_KYC_NOT_CLEARED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_borrower_kyc_cleared
    """
    ctx = setup_application_line(borrower_overrides={"kyc_status": "PENDING"})
    hl_id = ctx["heloc"]["id"]
    resp = api.activate_heloc(hl_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_KYC_NOT_CLEARED)
    after = validate_success(api.get_heloc(hl_id, OFFICER))
    assert after["status"] == "APPLICATION", "line must stay APPLICATION on failed activation"


def test_activate_blocked_when_borrower_kyc_rejected(api):
    """PRD §3.3: "The borrower's kyc_status must be CLEARED, otherwise activation fails
    with ERR_KYC_NOT_CLEARED (HTTP 409)."

    A REJECTED borrower (the other non-CLEARED value) likewise blocks activation,
    confirming the gate is on CLEARED specifically and not merely on PENDING.

    Design: Difficulty/cross_entity_state_dependency/activate_requires_borrower_kyc_cleared
    """
    ctx = setup_application_line(borrower_overrides={"kyc_status": "REJECTED"})
    hl_id = ctx["heloc"]["id"]
    resp = api.activate_heloc(hl_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_KYC_NOT_CLEARED)


def test_first_lien_activation_blocked_by_senior_lien(api):
    """PRD §3.3: "if the line is being recorded in FIRST position, the property's
    senior_lien_balance_cents must be exactly 0, otherwise the request fails with
    ERR_LIEN_POSITION_CONFLICT (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/first_lien_activation_requires_property_no_senior_lien
    """
    ctx = setup_application_line(
        property_overrides={"senior_lien_balance_cents": 30000000},
        heloc_overrides={"lien_position": "FIRST"},
    )
    hl_id = ctx["heloc"]["id"]
    resp = api.activate_heloc(hl_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_LIEN_POSITION_CONFLICT)


def test_second_lien_activation_allowed_with_senior_lien(api):
    """PRD §3.3: "if the line is being recorded in FIRST position, the property's
    senior_lien_balance_cents must be exactly 0, otherwise the request fails with
    ERR_LIEN_POSITION_CONFLICT (HTTP 409)."

    The conflict is specific to FIRST position: a SECOND-position line against the same
    senior-encumbered property activates successfully to DRAW (the senior-lien gate does
    not apply), confirming the rule is scoped to FIRST.

    Design: Difficulty/cross_entity_state_dependency/first_lien_activation_requires_property_no_senior_lien
    """
    ctx = setup_application_line(
        property_overrides={"senior_lien_balance_cents": 30000000},
        heloc_overrides={"lien_position": "SECOND"},
    )
    hl_id = ctx["heloc"]["id"]
    activated = validate_success(api.activate_heloc(hl_id, OFFICER))
    assert activated["status"] == "DRAW"


# --- compensating_invariant -------------------------------------------------

def test_draw_reverse_conserves_committed_credit(api):
    """PRD §3.4: "A successful reversal credits the line's current_balance_cents by the
    draw's amount_cents (compensating the original debit), recomputes
    available_credit_cents as the credit limit minus the current balance floored at 0,
    flips the draw's status to REVERSED ..."

    Draw 200000 then reverse -> balance back to 0, available back to credit_limit
    50000000 (balance + available == credit_limit conserved).

    Design: Difficulty/compensating_invariant/draw_reverse_conserves_principal_plus_available
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    draw = book_draw(hl_id, 200000)
    reversed_draw = validate_success(api.reverse_draw(hl_id, draw["id"], SERVICER))
    assert reversed_draw["status"] == "REVERSED"
    after = validate_success(api.get_heloc(hl_id, SERVICER))
    assert after["current_balance_cents"] == 0
    assert after["available_credit_cents"] == 50000000, (
        "balance + available must equal credit_limit after reversal"
    )


def test_committed_credit_conserved_after_partial_draws_then_reverse(api):
    """PRD §3.4: "Available credit is always recomputed as the credit limit minus the
    current balance, floored at 0."
    PRD §3.4: "A successful reversal credits the line's current_balance_cents by the
    draw's amount_cents (compensating the original debit), recomputes
    available_credit_cents as the credit limit minus the current balance floored at 0 ..."

    Two draws (200000 + 300000) then reversing only the 200000 draw leaves
    balance 300000 and available 49700000 — balance + available still equal the
    credit_limit 50000000.

    Design: Difficulty/compensating_invariant/draw_reverse_conserves_principal_plus_available
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0}, index_rate_bps=0)
    hl_id = ctx["heloc"]["id"]
    draw_a = book_draw(hl_id, 200000)
    book_draw(hl_id, 300000)
    validate_success(api.reverse_draw(hl_id, draw_a["id"], SERVICER))
    after = validate_success(api.get_heloc(hl_id, SERVICER))
    assert after["current_balance_cents"] == 300000
    assert after["available_credit_cents"] == 49700000
    assert after["current_balance_cents"] + after["available_credit_cents"] == 50000000


def test_payment_waterfall_conserves_remittance(api):
    """PRD §3.6: "The three buckets always sum exactly to amount_cents; the allocation
    is exact integer-cents arithmetic with no rounding."

    Draw 200000, clock 2026-01-31, APR 1000 -> accrued 1644; 10000 payment splits
    0 + 1644 + 8356 == 10000.

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_remittance
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-31T00:00:00Z")
    payment = validate_success(api.create_payment(hl_id, {"amount_cents": 10000}, SERVICER), 201)
    assert payment["fee_applied_cents"] == 0
    assert payment["interest_applied_cents"] == 1644
    assert payment["principal_applied_cents"] == 8356
    total = (
        payment["fee_applied_cents"]
        + payment["interest_applied_cents"]
        + payment["principal_applied_cents"]
    )
    assert total == 10000


def test_payment_waterfall_conserves_remittance_with_fee_bucket(api):
    """PRD §3.6: "The three buckets always sum exactly to amount_cents; the allocation
    is exact integer-cents arithmetic with no rounding."
    PRD §3.6: "The remittance is then allocated across three buckets in a pinned order:
    outstanding fees first, then accrued interest, then principal."

    With an OUTSTANDING ANNUAL fee 5000 present and APR 0 (no interest), a 100000 payment
    against a 200000 principal splits 5000 fee + 0 interest + 95000 principal, summing
    exactly to 100000.

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_remittance
    """
    ctx = setup_active_line(
        heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0, "annual_fee_cents": 5000},
        index_rate_bps=0,
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    # Cross one anniversary to assess a 5000 ANNUAL fee.
    from test_helpers import advance_clock
    advance_clock(hl_id, "2027-01-01T00:00:00Z")
    payment = validate_success(api.create_payment(hl_id, {"amount_cents": 100000}, SERVICER), 201)
    assert payment["fee_applied_cents"] == 5000
    assert payment["interest_applied_cents"] == 0
    assert payment["principal_applied_cents"] == 95000
    total = (
        payment["fee_applied_cents"]
        + payment["interest_applied_cents"]
        + payment["principal_applied_cents"]
    )
    assert total == 100000
