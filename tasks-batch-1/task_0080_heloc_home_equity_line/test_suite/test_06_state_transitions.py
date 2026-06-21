"""Corner coverage: invalid/valid transitions, initial state, terminal lockdown,
guarded unfreeze, draw-reverse idempotency, fee settlement and waiver side effects
(Queue B: state_machines)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_line,
    setup_application_line,
    setup_frozen_line_via_cltv_breach,
    book_draw,
    advance_clock,
    revalue_property,
    set_clock,
    ApiErrorId,
    TEST_USERS,
)

OFFICER = TEST_USERS["loan_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


def test_activate_already_active_heloc_rejected(api):
    """PRD §3.12: "An attempt to drive a transition from a state that does not define
    it ... is rejected with ERR_INVALID_STATE (HTTP 409)."

    Activating a line already in DRAW is rejected.

    Design: Corner/state_machines/activate_already_active_heloc_returns_invalid_state
    """
    ctx = setup_active_line()
    resp = api.activate_heloc(ctx["heloc"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_heloc_initial_state_application(api):
    """PRD §3.3: "A line's status begins at APPLICATION ..."

    Design: Corner/state_machines/new_heloc_initial_state_application
    """
    ctx = setup_application_line(attach_covenants=False, publish_index_rate=False)
    heloc = validate_success(api.get_heloc(ctx["heloc"]["id"], OFFICER))
    assert heloc["status"] == "APPLICATION"


def test_convert_to_repayment_after_draw_period_succeeds(api):
    """PRD §3.9: "Conversion requires that the line currently be in DRAW and that the
    logical clock be at or after the origination_date plus draw_period_years ..."
    PRD §3.9: "Conversion sets available_credit_cents to 0 (no further draws are
    allowed) ..."

    Design: Corner/state_machines/convert_to_repayment_after_draw_period_elapsed_succeeds
    """
    ctx = setup_active_line(heloc_overrides={"draw_period_years": 10})
    hl_id = ctx["heloc"]["id"]
    # Clock unambiguously at/after draw-end under any day-count reading.
    set_clock("2037-01-01T00:00:00Z")
    result = validate_success(api.convert_to_repayment(hl_id, SERVICER))
    assert result["status"] == "REPAYMENT"
    assert result["available_credit_cents"] == 0


def test_closed_heloc_rejects_freeze(api):
    """PRD §3.12: "An attempt to drive a transition from a state that does not define
    it — ... freezing a line that is not in DRAW ... — is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    A CLOSED line (closed from DRAW after draw-end, no early fee, balance 0) rejects freeze.

    Design: Corner/state_machines/terminal_closed_heloc_rejects_further_transitions
    """
    ctx = setup_active_line(
        clock="2036-06-01T00:00:00Z",
        index_effective="2026-01-01T00:00:00Z",
        heloc_overrides={"draw_period_years": 10},
    )
    hl_id = ctx["heloc"]["id"]
    closed = validate_success(api.close_heloc(hl_id, SERVICER))
    assert closed["status"] == "CLOSED"
    resp = api.freeze_heloc(hl_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_unfreeze_blocked_while_covenant_breached(api):
    """PRD §3.9: "A frozen line may be unfrozen back from FROZEN to DRAW, but only when
    no covenant of that line is currently BREACHED ..."
    PRD §3.12: "An attempt to drive a transition from a state that does not define it —
    ... unfreezing a line that is not FROZEN ... — is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    A FROZEN line whose MAX_CLTV covenant is still BREACHED rejects unfreeze.

    Design: Corner/state_machines/unfreeze_blocked_while_covenant_breached
    """
    ctx = setup_frozen_line_via_cltv_breach()
    hl_id = ctx["heloc"]["id"]
    resp = api.unfreeze_heloc(hl_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["status"] == "FROZEN"


def test_reverse_already_reversed_draw_rejected(api):
    """PRD §3.12: "An attempt to drive a transition from a state that does not define
    it — ... reversing a draw that is not BOOKED ... — is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    Design: Corner/state_machines/draw_reverse_already_reversed_returns_invalid_state
    """
    ctx = setup_active_line()
    hl_id = ctx["heloc"]["id"]
    draw = book_draw(hl_id, 200000)
    validate_success(api.reverse_draw(hl_id, draw["id"], SERVICER))
    resp = api.reverse_draw(hl_id, draw["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_annual_fee_settled_via_payment_waterfall(api):
    """PRD §3.7: "A fee assessment transitions from OUTSTANDING to SETTLED automatically
    once the cumulative fee_applied_cents across payments reaches or exceeds its
    amount_cents ..."
    PRD §3.6: "The fee bucket is filled first ..."

    An ANNUAL fee 5000 assessed at the 1-year anniversary is SETTLED once a 5000 payment's
    fee bucket covers it.

    Design: Corner/state_machines/fee_settled_via_payment_waterfall_side_effect
    """
    ctx = setup_active_line(heloc_overrides={"annual_fee_cents": 5000})
    hl_id = ctx["heloc"]["id"]
    advance_clock(hl_id, "2027-01-01T00:00:00Z")
    fees, _ = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "ANNUAL"})
    )
    assert len(fees) == 1
    fee_id = fees[0]["id"]
    payment = validate_success(api.create_payment(hl_id, {"amount_cents": 5000}, SERVICER), 201)
    assert payment["fee_applied_cents"] == 5000
    fee_after = _find_fee(api, hl_id, fee_id)
    assert fee_after["settlement_status"] == "SETTLED"


def test_covenant_cure_waives_in_window_annual_fee(api):
    """PRD §3.8: "Curing waives any OUTSTANDING ANNUAL fee assessment created during the
    breach window, transitioning each such fee to WAIVED ..."

    MAX_CLTV breached, ANNUAL fee assessed during breach, metric cured by revalue ->
    fee WAIVED (not SETTLED).

    Design: Corner/state_machines/covenant_cure_waives_annual_fee_in_breach_window
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000, "annual_fee_cents": 5000},
    )
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]
    book_draw(hl_id, 90000000)
    validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))  # breach -> FROZEN
    advance_clock(hl_id, "2027-01-01T00:00:00Z")  # ANNUAL fee during breach window
    fees, _ = validate_paginated(
        api.list_fee_assessments(hl_id, SERVICER, params={"fee_type": "ANNUAL"})
    )
    fee_id = fees[0]["id"]
    revalue_property(ctx["property"]["id"], appraised_value_cents=200000000)
    cured = validate_success(api.cure_covenant(hl_id, cov_id, SERVICER))
    assert cured["status"] == "CURED"
    fee_after = _find_fee(api, hl_id, fee_id)
    assert fee_after["settlement_status"] == "WAIVED"


def _find_fee(api, hl_id, fee_id):
    fees, _ = validate_paginated(api.list_fee_assessments(hl_id, SERVICER))
    for f in fees:
        if f["id"] == fee_id:
            return f
    raise AssertionError(f"fee {fee_id} not found in line {hl_id}")
