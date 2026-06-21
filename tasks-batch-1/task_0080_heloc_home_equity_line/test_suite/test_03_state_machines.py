"""Non-linear state machines: covenant cyclic re-breach and the Heloc FROZEN fork to
DEFAULTED; plus temporal/credit boundary transitions (Queue A: non_linear_state_machine,
resource_temporal_overlap, boundary_precision_check, compensating_invariant)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_active_line,
    setup_frozen_line_via_cltv_breach,
    book_draw,
    set_clock,
    revalue_property,
    ApiErrorId,
    TEST_USERS,
    make_loan_servicer_headers,
)

SERVICER = TEST_USERS["loan_servicer_headers"]


def test_covenant_cycles_satisfied_breached_cured_breached(api):
    """PRD §3.8: "A covenant that has previously been cured can re-breach: evaluating a
    covenant from CURED to BREACHED requires that it currently be CURED and that the
    metric cross the threshold again, and likewise freezes a line that is in DRAW and
    increments the covenant's version by 1."

    Balance 90000000, appraised 100000000 -> cltv 9000 breaches (8500); revalue to
    200000000 -> cltv 4500 cures; revert to 100000000 -> re-breach.

    Design: Difficulty/non_linear_state_machine/covenant_cyclic_satisfied_breached_cured_breached
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        borrower_overrides={"annual_income_cents": 50000000, "monthly_debt_obligation_cents": 100000},
    )
    hl_id = ctx["heloc"]["id"]
    prop_id = ctx["property"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]

    book_draw(hl_id, 90000000)
    breached = validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))
    assert breached["status"] == "BREACHED"

    revalue_property(prop_id, appraised_value_cents=200000000)
    cured = validate_success(api.cure_covenant(hl_id, cov_id, SERVICER))
    assert cured["status"] == "CURED"

    revalue_property(prop_id, appraised_value_cents=100000000)
    rebreached = validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))
    assert rebreached["status"] == "BREACHED", (
        f"covenant must re-breach after cure (cyclic), got {rebreached['status']}"
    )


def test_covenant_cure_requires_metric_back_in_compliance(api):
    """PRD §3.8: "Curing a covenant ... requires that the covenant currently be BREACHED,
    that its metric no longer cross the threshold per the formulas above, and that the
    line not be DEFAULTED."

    A BREACHED MAX_CLTV whose metric is cured by revaluation transitions to CURED.

    Design: Difficulty/non_linear_state_machine/covenant_cyclic_satisfied_breached_cured_breached
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
    )
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]
    book_draw(hl_id, 90000000)
    validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))
    revalue_property(ctx["property"]["id"], appraised_value_cents=200000000)
    cured = validate_success(api.cure_covenant(hl_id, cov_id, SERVICER))
    assert cured["status"] == "CURED"


def test_frozen_line_forks_to_defaulted_branch(api):
    """PRD §3.10: "Default may be declared from DRAW, REPAYMENT, or FROZEN, moving the
    line to DEFAULTED."
    PRD §3.10: "Declaration sets the line's available_credit_cents to 0, blocking all
    future draws as a cascade, and increments the line's version by 1."

    A FROZEN line (via MAX_CLTV breach) declared in default by a distinct servicer forks
    to DEFAULTED with available_credit_cents 0.

    Design: Difficulty/non_linear_state_machine/heloc_branching_frozen_fork_to_draw_or_defaulted
    """
    ctx = setup_frozen_line_via_cltv_breach(activate_user_id="officer-A")
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["cltv_covenant"]["id"]
    servicer_b = make_loan_servicer_headers("servicer-B")
    result = validate_success(api.declare_default(hl_id, {"covenant_id": cov_id}, servicer_b))
    assert result["status"] == "DEFAULTED", f"FROZEN must fork to DEFAULTED, got {result['status']}"
    assert result["available_credit_cents"] == 0


def test_frozen_line_default_creates_default_event(api):
    """PRD §3.10: "A successful declaration creates an immutable DefaultEvent recording
    the line's heloc_id, the breached covenant_id, a trigger_type mirroring the
    covenant's covenant_type for the audit trail, the observed_value of the computed
    metric at declaration ..., and the declared_by_user_id capturing the acting
    servicer's X-User-ID."

    Design: Difficulty/non_linear_state_machine/heloc_branching_frozen_fork_to_draw_or_defaulted
    """
    ctx = setup_frozen_line_via_cltv_breach(activate_user_id="officer-A")
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["cltv_covenant"]["id"]
    servicer_b = make_loan_servicer_headers("servicer-B")
    validate_success(api.declare_default(hl_id, {"covenant_id": cov_id}, servicer_b))
    events, meta = _list(api.list_default_events(hl_id, servicer_b))
    assert meta["total_count"] == 1
    assert events[0]["trigger_type"] == "MAX_CLTV"


def test_convert_blocked_before_draw_period_elapsed(api):
    """PRD §3.9: "Conversion requires that the line currently be in DRAW and that the
    logical clock be at or after the origination_date plus draw_period_years; an attempt
    to convert before the draw period has elapsed is rejected with
    ERR_DRAW_PERIOD_NOT_ELAPSED (HTTP 409)."

    origination 2026-01-01, draw_period 10y; clock 2030-06-01 sits well inside the draw
    window (before draw-end under any day-count reading), so convert is rejected. (A clock
    chosen unambiguously inside the window, avoiding the leap-day-sensitive exact boundary
    which the PRD does not pin between calendar-year and 365-day addition.)

    Design: Difficulty/resource_temporal_overlap/draw_period_boundary_blocks_convert_strict
    """
    ctx = setup_active_line(heloc_overrides={"draw_period_years": 10})
    hl_id = ctx["heloc"]["id"]
    set_clock("2030-06-01T00:00:00Z")
    resp = api.convert_to_repayment(hl_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DRAW_PERIOD_NOT_ELAPSED)


def test_convert_succeeds_after_draw_period_elapsed(api):
    """PRD §3.9: "Conversion requires that the line currently be in DRAW and that the
    logical clock be at or after the origination_date plus draw_period_years ..."
    PRD §3.9: "Conversion sets available_credit_cents to 0 (no further draws are
    allowed) ..."

    origination 2026-01-01, draw_period 10y; clock 2037-01-01 is unambiguously at or after
    draw-end under any day-count reading, so convert succeeds.

    Design: Difficulty/resource_temporal_overlap/draw_period_boundary_blocks_convert_strict
    """
    ctx = setup_active_line(heloc_overrides={"draw_period_years": 10})
    hl_id = ctx["heloc"]["id"]
    set_clock("2037-01-01T00:00:00Z")
    result = validate_success(api.convert_to_repayment(hl_id, SERVICER))
    assert result["status"] == "REPAYMENT"
    assert result["available_credit_cents"] == 0


def test_index_supersede_marks_earlier_effective_date_superseded(api):
    """PRD §3.2: "Each index rate carries a computed superseded flag, false at creation,
    that becomes true once a newer index rate for the same index_name with a later
    effective_date exists. On publication of a new value, any prior index rate with the
    same index_name and an earlier effective_date is marked superseded."

    Design: Difficulty/resource_temporal_overlap/index_supersede_overlap_by_effective_date
    """
    set_clock("2026-02-01T00:00:00Z")
    old = validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 850, "effective_date": "2026-01-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    new = validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 900, "effective_date": "2026-02-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    old_after = validate_success(api.get_index_rate(old["id"], SERVICER))
    new_after = validate_success(api.get_index_rate(new["id"], SERVICER))
    assert old_after["superseded"] is True, "earlier effective_date must be superseded"
    assert new_after["superseded"] is False, "latest effective_date must be active"


def test_index_publish_keeps_later_rate_active(api):
    """PRD §3.2: "The active index is the non-superseded PRIME value."

    Publishing the later-effective PRIME leaves it non-superseded.

    Design: Difficulty/resource_temporal_overlap/index_supersede_overlap_by_effective_date
    """
    set_clock("2026-02-01T00:00:00Z")
    validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 850, "effective_date": "2026-01-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    new = validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 900, "effective_date": "2026-02-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    assert new["superseded"] is False


def test_draw_amount_exactly_equals_available_credit_permitted(api):
    """PRD §3.4: "The requested amount must not exceed the line's available_credit_cents;
    an over-limit advance is rejected with ERR_INSUFFICIENT_CREDIT (HTTP 422)."

    Fresh DRAW line, credit_limit 50000000, balance 0 -> available 50000000; a draw of
    exactly 50000000 (== available, not >) is permitted and BOOKED.

    Design: Difficulty/boundary_precision_check/draw_amount_exactly_equals_available_credit
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    draw = validate_success(api.create_draw(hl_id, {"amount_cents": 50000000}, SERVICER), 201)
    assert draw["status"] == "BOOKED"
    after = validate_success(api.get_heloc(hl_id, SERVICER))
    assert after["available_credit_cents"] == 0


def test_draw_one_cent_over_available_rejected(api):
    """PRD §3.4: "The requested amount must not exceed the line's available_credit_cents;
    an over-limit advance is rejected with ERR_INSUFFICIENT_CREDIT (HTTP 422)."

    A draw of 50000001 against available 50000000 (one cent over) is rejected.

    Design: Difficulty/boundary_precision_check/draw_amount_exactly_equals_available_credit
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    resp = api.create_draw(hl_id, {"amount_cents": 50000001}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)


def _list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)
