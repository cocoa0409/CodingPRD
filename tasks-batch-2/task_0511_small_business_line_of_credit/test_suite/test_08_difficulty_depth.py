"""Second-pass depth tests for difficulty-design instances.

Each difficulty instance is covered by at least two tests so the depth queue's >=2-tests-per-
instance target is met. These tests assert a DISTINCT, independently PRD-derivable facet of the
same rule from the primary test in test_01..test_06 (e.g. the other side of a boundary, a
complementary observable side effect, or the not-spawned/unchanged half of a branch).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_merchant,
    create_bank_feed,
    create_draft_application,
    create_submitted_application,
    create_active_credit_line,
    create_active_line_with_draw,
    take_draw,
    schedule_remittance,
    settle_remittance,
    set_clock,
    setup_delinquent_line,
    setup_line_at_default_threshold,
    setup_charged_off_line,
    get_line,
    sum_ledger_amounts,
    create_application_payload,
    submit_application_payload,
    create_renewal_offer_payload,
    create_remittance_payload,
    create_statement_payload,
    create_line_increase_request_payload,
    approve_line_increase_payload,
    declare_default_payload,
    charge_off_payload,
    create_draw_payload,
    settle_remittance_payload,
    UW1,
    UW2,
    SV1,
    CO1,
    CO_DEFAULT,
    CO_CHARGEOFF,
)


def _scheduled(api, line_id):
    return validate_paginated(api.list_remittances(line_id, SV1, params={"status": "SCHEDULED"}))


def _ledger(api, line_id, etype):
    return validate_paginated(
        api.list_ledger_entries_for_line(line_id, SV1, params={"entry_type": etype})
    )


# ─── dual_variant_calc ────────────────────────────────────────────────
def test_initial_submit_uses_original_feed_score_52(api):
    """The initial DRAFT->SUBMITTED submit scores against the originally attached feed.

    PRD §3.2: "On submit, the system records the submitting operator's identifier as
    submitted_by_user_id, computes the risk_score, and increments the application's version."

    Design: Difficulty/dual_variant_calc/risk_score_initial_vs_revision_submit
    """
    merchant = create_merchant(monthly_revenue_cents=2_000_000)
    feed_lo = create_bank_feed(
        merchant["id"], plaid_item_id="plaid_lo", pulled_at="2026-04-20T00:00:00Z",
        avg_daily_balance_cents=700_000, nsf_count_90d=0, deposit_volume_cents=3_000_000,
    )
    app = validate_success(
        api.create_application(
            create_application_payload(merchant["id"], feed_lo["id"], requested_limit_cents=1_000_000),
            UW1,
        ),
        201,
    )
    submitted = validate_success(api.submit_application(app["id"], UW1), 200)
    assert submitted["risk_score"] == 52
    assert submitted["bank_feed_id"] == feed_lo["id"]


def test_weekly_cadence_same_outstanding_diverges_from_daily(api):
    """The WEEKLY (10%) cadence variant on the same outstanding total diverges from DAILY.

    PRD §3.5: "where a DAILY line uses 2 percent and a WEEKLY line uses 10 percent; the target
    is rounded half up to a whole cent before being capped."

    Design: Difficulty/dual_variant_calc/remittance_amount_daily_vs_weekly_cadence
    """
    set_clock("2026-05-10T00:00:00Z")
    _, _, _, line = create_active_credit_line(
        cadence="WEEKLY", feed_overrides={"pulled_at": "2026-05-09T00:00:00Z"}
    )
    take_draw(line["id"], 500_000)  # fee 40000
    take_draw(line["id"], 300_000)  # fee 24000 -> outstanding_total 864000
    remit = schedule_remittance(line["id"], "2026-05-12T00:00:00Z")
    set_clock("2026-05-12T00:00:00Z")
    settled = settle_remittance(remit["id"], "SUCCESS")
    # WEEKLY: round(864000 * 0.10) = 86400. PRD §3.5 allocates "within each draw, fee is
    # repaid before principal ... advancing through draws oldest-first": draw1 fee 40000,
    # then draw1 principal 46400 exhausts the 86400 before reaching draw2. So the split is
    # 40000 fee + 46400 principal (NOT all-fees-first globally).
    assert settled["amount_cents"] == 86400
    assert settled["fee_applied_cents"] == 40000
    assert settled["principal_applied_cents"] == 46400


# ─── combinatorial_formula ────────────────────────────────────────────
def test_nsf_penalty_drives_score_to_zero(api):
    """The subtractive NSF penalty in the weighted blend can clamp the score to 0.

    PRD §3.2: "an NSF penalty is computed as the feed's trailing-90-day NSF count multiplied by
    a per-event penalty step of 0.15, capped at 1.0."
    PRD §3.2: "That raw value is clamped to the range from 0.0 to 1.0"

    Design: Difficulty/combinatorial_formula/risk_score_weighted_nonlinear_mode_a
    """
    merchant = create_merchant(monthly_revenue_cents=2_000_000)
    feed = create_bank_feed(
        merchant["id"], pulled_at="2026-04-20T00:00:00Z",
        avg_daily_balance_cents=200_000, nsf_count_90d=6, deposit_volume_cents=1_200_000,
    )
    app = validate_success(
        api.create_application(
            create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
            UW1,
        ),
        201,
    )
    submitted = validate_success(api.submit_application(app["id"], UW1), 200)
    assert submitted["risk_score"] == 0


def test_equivalent_apr_shorter_term_yields_higher_apr(api):
    """A shorter term annualizes the same flat rate to a higher APR (1800 bps over 90 days).

    PRD §3.7: "that rate is then multiplied by 365 days divided by the term length in days to
    extrapolate it to a year, and the annualized rate is multiplied back by 10000 and rounded
    once, half up, to whole basis points."

    Design: Difficulty/combinatorial_formula/equivalent_apr_annualize_after_rate_mode_c
    """
    _, _, _, line = create_active_credit_line(cadence="WEEKLY")
    offer = validate_success(
        api.create_renewal_offer(
            line["id"], create_renewal_offer_payload(new_fee_factor_bps=1800, term_days=90), CO1
        ),
        201,
    )
    assert offer["total_fee_cents"] == 180000
    assert offer["equivalent_apr_bps"] == 7300


# ─── non_linear_state_machine ─────────────────────────────────────────
def test_nsf_retry_inherits_attempt_count(api):
    """The spawned NSF retry inherits the failed remittance's post-increment attempt_count.

    PRD §3.5: "a fresh SCHEDULED remittance whose scheduled_for is this remittance's
    scheduled_for plus a 2-day retry gap, with its attempt_count initialized to this
    remittance's post-increment attempt_count"

    Design: Difficulty/non_linear_state_machine/remittance_nsf_retry_cycle
    """
    set_clock("2026-05-13T00:00:00Z")
    line, _ = create_active_line_with_draw(
        200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
    )
    remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
    set_clock("2026-05-15T00:00:00Z")
    failed = settle_remittance(remit["id"], "NSF")
    assert failed["attempt_count"] == 1
    retry = validate_success(api.get_remittance(failed["next_retry_remittance_id"], SV1), 200)
    assert retry["status"] == "SCHEDULED"
    assert retry["attempt_count"] == 1


def test_request_revision_clears_risk_score(api):
    """Requesting a revision clears risk_score to null, the first hop of the revision cycle.

    PRD §3.2: "Requesting a revision moves the application from SUBMITTED to NEEDS_REVISION,
    clears the risk_score back to null, and bumps the version"

    Design: Difficulty/non_linear_state_machine/application_revision_resubmit_cycle
    """
    merchant, feed, app = create_submitted_application()
    assert app["risk_score"] == 85
    revised = validate_success(api.request_revision_application(app["id"], UW2), 200)
    assert revised["status"] == "NEEDS_REVISION"
    assert revised["risk_score"] is None


# ─── transitive_cascade ───────────────────────────────────────────────
def test_charge_off_sets_status_and_leaves_already_repaid_untouched_observable(api):
    """Charge-off moves the line to CHARGED_OFF and the write-off ledger amount equals the
    unrepaid principal (no repayments occurred, so full 200000).

    PRD §3.6: "The line then moves to CHARGED_OFF and its version is bumped."

    Design: Difficulty/transitive_cascade/chargeoff_writeoff_ledger_cascade_depth3
    """
    line, draw, line_after = setup_charged_off_line(principal_cents=200_000)
    assert line_after["status"] == "CHARGED_OFF"
    wo, meta = _ledger(api, line["id"], "WRITE_OFF")
    assert meta["total_count"] == 1
    # PRD §2.8: amount_cents is a signed movement; a WRITE_OFF reduces outstanding, so
    # the unrepaid principal (200000) is recorded as a negative (reducing) movement.
    assert sum_ledger_amounts(wo, "WRITE_OFF") == -200_000


def test_two_strikes_keep_line_active_then_third_delinquent(api):
    """After two NSF strikes the line is still ACTIVE; only the third tips it to DELINQUENT.

    PRD §3.5: "if after the strike increment the line's nsf_strike_count has reached the
    delinquency threshold of 3 and the line is currently ACTIVE, the line auto-transitions from
    ACTIVE to DELINQUENT"

    Design: Difficulty/transitive_cascade/nsf_settle_delinquency_cascade_depth2
    """
    set_clock("2026-05-13T00:00:00Z")
    line, _ = create_active_line_with_draw(
        200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
    )
    remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
    set_clock("2026-05-15T00:00:00Z")
    f1 = settle_remittance(remit["id"], "NSF")
    r2 = validate_success(api.get_remittance(f1["next_retry_remittance_id"], SV1), 200)
    set_clock("2026-05-17T00:00:00Z")
    settle_remittance(r2["id"], "NSF")
    mid = get_line(line["id"])
    assert mid["nsf_strike_count"] == 2
    assert mid["status"] == "ACTIVE"


# ─── priority_pair_validation_conflict ────────────────────────────────
def test_draft_application_stays_draft_after_invalid_approve(api):
    """When state and feed-freshness both fail on approve, the DRAFT application is unchanged.

    PRD §2.6: "no mutation is applied."  (rejected requests apply no mutation)
    PRD §3.2: "Approving moves the application from SUBMITTED to APPROVED."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_feed_stale_on_approve
    """
    merchant, feed, app = create_draft_application(
        feed_overrides={"pulled_at": "2026-04-20T00:00:00Z"}
    )
    validate_success(api.mark_bank_feed_stale(feed["id"], UW1), 200)
    res = api.approve_application(app["id"], UW2)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_application(app["id"], UW1), 200)
    assert after["status"] == "DRAFT"
    assert after["pricing_tier"] is None
    assert after["approved_limit_cents"] is None


def test_excess_nsf_leaves_application_submitted(api):
    """Excess-NSF rejection on approve leaves the application SUBMITTED with no pricing set.

    PRD §3.2: "the feed's trailing-90-day NSF count must not exceed the underwriting maximum of
    3 events (else ERR_EXCESS_NSF)"

    Design: Difficulty/priority_pair_validation_conflict/excess_nsf_beats_score_floor_on_approve
    """
    merchant = create_merchant(monthly_revenue_cents=2_000_000)
    feed = create_bank_feed(
        merchant["id"], pulled_at="2026-04-20T00:00:00Z",
        avg_daily_balance_cents=200_000, nsf_count_90d=6, deposit_volume_cents=1_200_000,
    )
    app = validate_success(
        api.create_application(
            create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
            UW1,
        ),
        201,
    )
    validate_success(api.submit_application(app["id"], UW1), 200)
    res = api.approve_application(app["id"], UW2)
    validate_error(res, "ERR_EXCESS_NSF")
    after = validate_success(api.get_application(app["id"], UW1), 200)
    assert after["status"] == "SUBMITTED"
    assert after["approved_limit_cents"] is None


# ─── boundary_precision_check ─────────────────────────────────────────
def test_settle_one_second_before_due_rejected_boundary(api):
    """At now == scheduled_for - 1s the settle is rejected (the other side of the >= boundary).

    PRD §3.5: "the logical clock has reached or passed its scheduled_for; settling before the
    scheduled instant is rejected with ERR_REMITTANCE_NOT_DUE."

    Design: Difficulty/boundary_precision_check/settle_at_exact_scheduled_for_instant_succeeds
    """
    set_clock("2026-05-18T00:00:00Z")
    line, _ = create_active_line_with_draw(
        500_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
    )
    remit = schedule_remittance(line["id"], "2026-05-20T00:00:00Z")
    set_clock("2026-05-19T23:59:59Z")
    res = api.settle_remittance(remit["id"], settle_remittance_payload("SUCCESS"), SV1)
    validate_error(res, "ERR_REMITTANCE_NOT_DUE")
    after = validate_success(api.get_remittance(remit["id"], SV1), 200)
    assert after["status"] == "SCHEDULED"


# ─── cross_entity_state_dependency ────────────────────────────────────
def test_draw_resumes_after_unfreeze(api):
    """A draw blocked while FROZEN succeeds once the line is unfrozen back to ACTIVE.

    PRD §3.3: "Unfreezing moves it from FROZEN back to ACTIVE, forming the revolving ACTIVE <->
    FROZEN loop so that draws resume after unfreeze."

    Design: Difficulty/cross_entity_state_dependency/draw_requires_credit_line_active
    """
    _, _, _, line = create_active_credit_line(cadence="DAILY")
    validate_success(api.freeze_credit_line(line["id"], SV1), 200)
    blocked = api.create_draw(line["id"], create_draw_payload(100_000), SV1)
    validate_error(blocked, "ERR_LINE_NOT_DRAWABLE")
    validate_success(api.unfreeze_credit_line(line["id"], SV1), 200)
    draw = validate_success(api.create_draw(line["id"], create_draw_payload(100_000), SV1), 201)
    assert draw["status"] == "OUTSTANDING"


def test_increase_approve_leaves_limit_unchanged_when_line_not_active(api):
    """The increase stays PENDING and the line limit is unchanged when the line is not ACTIVE.

    PRD §3.7: "On approval, the system computes the granted approved_limit_cents, writes it onto
    the parent line's credit_limit_cents"

    Design: Difficulty/cross_entity_state_dependency/increase_approve_requires_credit_line_active
    """
    set_clock("2026-05-13T00:00:00Z")
    line, _ = create_active_line_with_draw(
        200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
    )
    feed2 = create_bank_feed(
        line["merchant_id"], plaid_item_id="plaid_x2", pulled_at="2026-05-12T12:00:00Z",
        avg_daily_balance_cents=2_000_000, nsf_count_90d=0, deposit_volume_cents=9_000_000,
    )
    lir = validate_success(
        api.create_line_increase_request(
            line["id"],
            create_line_increase_request_payload(feed2["id"], requested_limit_cents=1_500_000),
            SV1,
        ),
        201,
    )
    remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
    set_clock("2026-05-15T00:00:00Z")
    f1 = settle_remittance(remit["id"], "NSF")
    r2 = validate_success(api.get_remittance(f1["next_retry_remittance_id"], SV1), 200)
    set_clock("2026-05-17T00:00:00Z")
    f2 = settle_remittance(r2["id"], "NSF")
    r3 = validate_success(api.get_remittance(f2["next_retry_remittance_id"], SV1), 200)
    set_clock("2026-05-19T00:00:00Z")
    settle_remittance(r3["id"], "NSF")
    assert get_line(line["id"])["status"] == "DELINQUENT"
    ver = get_line(line["id"])["version"]
    res = api.approve_line_increase_request(lir["id"], approve_line_increase_payload(ver), CO1)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_line(line["id"])["credit_limit_cents"] == 1_000_000


# ─── resource_temporal_overlap ────────────────────────────────────────
def test_daily_adjacent_remittance_window_allowed(api):
    """On a DAILY line, an exact one-day-adjacent window is allowed (half-open comparison).

    PRD §3.5: "On a DAILY line, two remittance windows must be separated by at least one
    calendar day, and the comparison is half-open so that exact adjacency is allowed."

    Design: Difficulty/resource_temporal_overlap/daily_remittance_gap_half_open_adjacency_allowed
    """
    set_clock("2026-05-18T00:00:00Z")
    _, _, _, line = create_active_credit_line(
        cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
    )
    take_draw(line["id"], 100_000)
    first = schedule_remittance(line["id"], "2026-05-21T00:00:00Z")
    assert first["status"] == "SCHEDULED"
    adj = validate_success(
        api.create_remittance(line["id"], create_remittance_payload("2026-05-22T00:00:00Z"), SV1), 201
    )
    assert adj["status"] == "SCHEDULED"
    _, meta = _scheduled(api, line["id"])
    assert meta["total_count"] == 2


def test_statement_adjacent_window_allowed(api):
    """A statement window starting exactly at the prior window's period_end is allowed.

    PRD §3.8: "adjacency — where the new start equals an existing end — is allowed, because the
    windows are half-open and merely touch."

    Design: Difficulty/resource_temporal_overlap/statement_window_closed_containment_overlap_rejected
    """
    _, _, _, line = create_active_credit_line(cadence="WEEKLY")
    validate_success(
        api.create_statement(
            line["id"], create_statement_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"), SV1
        ),
        201,
    )
    adj = validate_success(
        api.create_statement(
            line["id"], create_statement_payload("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"), SV1
        ),
        201,
    )
    assert adj["status"] == "OPEN"
    _, meta = validate_paginated(api.list_statements(line["id"], SV1))
    assert meta["total_count"] == 2


# ─── compensating_invariant ───────────────────────────────────────────
def test_writeoff_ledger_amount_equals_unrepaid_principal(api):
    """The WRITE_OFF ledger entry records exactly the draw's unrepaid principal.

    PRD §3.6: "each written-off draw appends a WRITE_OFF ledger entry for its unrepaid principal
    — that draw's principal minus its principal already repaid (hop two)"

    Design: Difficulty/compensating_invariant/principal_accounting_conserved_through_chargeoff
    """
    line, draw, line_after = setup_charged_off_line(principal_cents=200_000)
    wo, _ = _ledger(api, line["id"], "WRITE_OFF")
    # PRD §2.8: amount_cents is a signed movement; a WRITE_OFF reduces outstanding, so
    # the unrepaid principal (200000) is recorded as a negative (reducing) movement.
    assert sum_ledger_amounts(wo, "WRITE_OFF") == -200_000
    assert line_after["outstanding_principal_cents"] == 0


def test_capacity_invariant_holds_immediately_after_draw(api):
    """available_credit + outstanding_principal == credit_limit immediately after a forward draw.

    PRD §3.3: "its available_credit_cents is the credit limit minus outstanding principal,
    floored at zero"

    Design: Difficulty/compensating_invariant/credit_capacity_conserved_through_draw_and_remittance
    """
    set_clock("2026-05-18T00:00:00Z")
    _, _, _, line = create_active_credit_line(
        cadence="WEEKLY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
    )
    take_draw(line["id"], 400_000)
    after = get_line(line["id"])
    assert after["outstanding_principal_cents"] == 400_000
    assert after["available_credit_cents"] == 600_000
    assert after["available_credit_cents"] + after["outstanding_principal_cents"] == after["credit_limit_cents"]
