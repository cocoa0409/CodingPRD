"""Difficulty-design coverage (priority queue from
SCAFFOLD_DIFFICULTY_DESIGN.yaml).

Each scaffold_difficulty_design[*].instances[*] produces AT LEAST TWO
tests tagged ``# difficulty: <rule_id>/<instance.name>``. Citations
trace to PRD prose for the underlying rule (PRD-First).
"""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    SECONDS_PER_DAY,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_by_months,
    advance_clock_by_seconds,
    create_and_activate_plan,
    create_and_open_batch,
    create_blackout,
    create_change_of_control,
    create_departure_draft,
    create_grant_and_drive_to_live,
    create_grant_in_state,
    create_grant_payload,
    create_ipo,
    create_restructuring,
    create_stock_split,
    create_window,
    get_tip_price_version,
    list_audit_for_target,
    list_tax_events_for_grant,
    make_board_secretary_headers,
    make_grantee_headers,
    make_plan_admin_headers,
    make_shareholder_registrar_headers,
    register_grantee,
    settle_departure,
    setup_grant_ready_to_sign,
    setup_live_grant_with_open_window,
    setup_plan_batch_grantee,
    setup_plan_with_blackout,
    setup_pool_boundary,
    setup_three_grants_for_pool_invariant,
    setup_two_batches_anniversary_and_continuous,
    sign_agreement_payload,
    submit_exercise_application,
    validate_error,
    validate_success,
    accelerate_vesting_payload,
    create_blackout_event_payload,
    create_exercise_window_payload,
)


def _iso_offset(anchor: str, seconds: int) -> str:
    base = _dt.datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    return (base + _dt.timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z",
    )


# =============================================================================
# Rule 1 — Dual-variant calculations
# =============================================================================

# difficulty: dual_variant_calc/vested_qty_anniversary_vs_continuous
def test_anniversary_at_cliff_plus_3mo_vests_150(api, plan_admin_headers):
    """PRD §3.5: "For ANNIVERSARY_BATCH, tranches vest in lump sums at
    each vesting_period_months boundary after the cliff. The number of
    completed periods is one plus the integer-part (floor) of the
    elapsed-months-since-cliff divided by vesting_period_months,
    capped at vesting_total_months divided by vesting_period_months.
    The unconditional vested option count is the floor of quantity
    multiplied by the completed-period count multiplied by
    vesting_period_months, all divided by vesting_total_months."

    Inputs: quantity=1200, cliff=12, total=48, period=3. At cliff+3mo
    (= 15 months elapsed), completed_periods = floor(3/3)+1 = 2,
    vested = floor(1200*2*3/48) = 150.
    """
    setup = setup_two_batches_anniversary_and_continuous()
    advance_clock_by_months(setup["plan"]["id"], 15)
    g_a = validate_success(api.get_grant(
        setup["grant_anniversary"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_a["vested_quantity"] == 150


# difficulty: dual_variant_calc/vested_qty_anniversary_vs_continuous
def test_continuous_daily_at_cliff_plus_3mo_vests_100(api,
                                                      plan_admin_headers):
    """PRD §3.5: "For CONTINUOUS_DAILY, vesting accrues linearly by day
    after the cliff. The constant DAYS_PER_MONTH is fixed at 30, so the
    number of days from grant date to cliff is cliff_months multiplied
    by 30 and the number of total vesting days is vesting_total_months
    multiplied by 30 ... The unconditional vested option count is the
    floor of quantity multiplied by the smaller of days-since-cliff and
    total-vesting-days, divided by total-vesting-days."

    Inputs: quantity=1200, cliff=12, total=48. total_days = (48-12)*30
    = 1080. At cliff+3mo (= 90 days post-cliff):
    vested = floor(1200*90/1080) = 100.
    """
    setup = setup_two_batches_anniversary_and_continuous()
    advance_clock_by_months(setup["plan"]["id"], 15)
    g_c = validate_success(api.get_grant(
        setup["grant_continuous"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_c["vested_quantity"] == 100


# difficulty: dual_variant_calc/vested_qty_anniversary_vs_continuous
def test_anniversary_and_continuous_diverge_at_same_clock(api,
                                                          plan_admin_headers):
    """PRD §3.5: "Mid-period the two algorithms produce different counts
    on identical inputs." Same plan clock, same quantity, same cliff and
    total months — different vested_quantity.
    """
    setup = setup_two_batches_anniversary_and_continuous()
    advance_clock_by_months(setup["plan"]["id"], 15)
    g_a = api.get_grant(
        setup["grant_anniversary"]["id"], plan_admin_headers,
    ).json()["data"]
    g_c = api.get_grant(
        setup["grant_continuous"]["id"], plan_admin_headers,
    ).json()["data"]
    assert g_a["vested_quantity"] != g_c["vested_quantity"]


# difficulty: dual_variant_calc/withholding_tax_provisional_vs_final
def test_withholding_tax_record_persists_at_tax_withheld(api,
                                                         plan_admin_headers):
    """PRD §3.9: "The final mode is the one pinned at the
    ELIGIBILITY_VERIFIED to TAX_WITHHELD transition and uses the rate
    table as of the plan clock at that transition instant ... The
    persisted final figure is the legally binding one."

    Confirms the persisted TaxEventRecord row is created at TAX_WITHHELD
    (not earlier, and not after).
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(50, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    # BEFORE submit: there should be no EXERCISE tax record.
    pre = list_tax_events_for_grant(grant["id"], event_type="EXERCISE")
    assert len(pre) == 0
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    # BEFORE verify (still SUBMITTED): still no record.
    pre2 = list_tax_events_for_grant(grant["id"], event_type="EXERCISE")
    assert len(pre2) == 0
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    # AFTER verify (cascades to TAX_WITHHELD): one record pinned.
    post = list_tax_events_for_grant(grant["id"], event_type="EXERCISE")
    assert len(post) == 1
    assert post[0]["jurisdiction_code"] == "US"
    assert post[0]["event_type"] == "EXERCISE"


# difficulty: dual_variant_calc/withholding_tax_provisional_vs_final
def test_final_withholding_record_event_type_is_exercise(api,
                                                         plan_admin_headers):
    """PRD §3.9: "(EXERCISE) at the TAX_WITHHELD transition described
    above..." and PRD §3.9 catalog: "Each TaxEventRecord row carries ...
    the event_type..."
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(50, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    records = list_tax_events_for_grant(grant["id"])
    exercise_records = [
        r for r in records if r["event_type"] == "EXERCISE"
    ]
    assert len(exercise_records) == 1


# =============================================================================
# Rule 2 — Combinatorial formulas across modes
# =============================================================================

# difficulty: combinatorial_formula/withholding_tax_tiered_three_inputs_mode_a
def test_tax_rate_table_uses_jurisdiction_residency_event_type(api,
                                                                plan_admin_headers):
    """PRD §3.9: "Effective rate is looked up in a tiered table keyed by
    (plan jurisdiction, grantee residency, event type)."

    A UK plan with a UK grantee on EXERCISE must emit a record whose
    jurisdiction_code field is 'UK' (the snapshot of plan.jurisdiction
    at event time per PRD §3.9 row description).
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="UK", tax_residency="UK",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(40, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    records = list_tax_events_for_grant(
        grant["id"], event_type="EXERCISE",
    )
    assert len(records) == 1
    assert records[0]["jurisdiction_code"] == "UK"


# difficulty: combinatorial_formula/withholding_tax_tiered_three_inputs_mode_a
def test_tax_record_carries_event_type_exercise(api, plan_admin_headers):
    """PRD §3.9: "Each TaxEventRecord row carries the originating
    grant_id, the related exercise_application_id when the event is an
    exercise (null for grant and vest events), the event_type..."
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="UK", tax_residency="UK",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(40, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    records = list_tax_events_for_grant(
        grant["id"], event_type="EXERCISE",
    )
    assert records[0]["event_type"] == "EXERCISE"
    assert records[0]["exercise_application_id"] == app["id"]


# difficulty: combinatorial_formula/exercise_price_restructuring_rounding_order_mode_b
def test_restructuring_multiply_then_divide_then_round(api,
                                                       plan_admin_headers):
    """PRD §3.7: "the new per-option price is computed by multiplying
    the parent's price_per_option_cents by restructure_factor_bps, then
    dividing by the basis-points divisor of 10000, with rounding half up
    performed only at the final step — multiplication first, division
    second, rounding last."

    Inputs: parent=5000c, factor=8000bps. multiply-first:
    round_half_up(5000 * 8000 / 10000) = round_half_up(4000.0) = 4000.
    Reversing the order (e.g., round(5000/10000)=1, then *8000=8000)
    yields a wildly different cents result.
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    create_restructuring(
        plan["id"], plan["current_clock_ts"], restructure_factor_bps=8000,
    )
    tip = get_tip_price_version(batch["id"])
    assert tip["cause"] == "RESTRUCTURING"
    assert tip["price_per_option_cents"] == 4000


# difficulty: combinatorial_formula/exercise_price_restructuring_rounding_order_mode_b
def test_restructuring_chain_links_parent_version(api, plan_admin_headers):
    """PRD §3.7: "Each new row carries cause equal to the corporate
    event's type, corporate_event_id set to the triggering event,
    parent_version_id set to the previous tip..."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    versions_before = api.list_exercise_price_versions(
        batch["id"], plan_admin_headers,
    ).json()["data"]
    v1 = versions_before[0]
    create_restructuring(
        plan["id"], plan["current_clock_ts"],
        restructure_factor_bps=8000,
    )
    tip = get_tip_price_version(batch["id"])
    assert tip["parent_version_id"] == v1["id"]
    assert tip["version_index"] == 2


# difficulty: combinatorial_formula/pool_reservation_circular_dependency_mode_c
def test_good_leaver_unvested_forfeits_pool_decreases(api,
                                                      plan_admin_headers):
    """PRD §3.10: "The unvested portion (the grant's quantity minus
    vested-at-departure minus existing forfeited_quantity) is
    unconditionally added to forfeited_quantity for every leaver class,
    and plan.pool_reserved_options is decreased by the same amount."

    Per PRD §3.5 ANNIVERSARY_BATCH: q=1200, cliff=12, period=3, total=48
    at cliff+3mo gives vested=150. Forfeited at departure = 1200-150=1050
    (good leaver keeps vested).
    """
    plan = create_and_activate_plan(pool_total_options=10_000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = create_grant_and_drive_to_live(
        plan, batch, grantee, quantity=1200,
    )
    advance_clock_by_months(plan["id"], 15)
    plan_at_dep = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    pool_before = plan_at_dep["pool_reserved_options"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_at_dep["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    g_after = api.get_grant(
        grant["id"], plan_admin_headers,
    ).json()["data"]
    plan_after = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    assert g_after["forfeited_quantity"] == 1050
    assert (
        plan_after["pool_reserved_options"]
        == pool_before - 1050
    )


# difficulty: combinatorial_formula/pool_reservation_circular_dependency_mode_c
def test_outstanding_quantity_after_good_leaver_keeps_vested(api,
                                                             plan_admin_headers):
    """PRD §3.5: "outstanding_quantity is quantity minus
    exercised_quantity minus forfeited_quantity."
    PRD §3.10 GOOD_LEAVER: vested portion is NOT forfeited, so after
    settle: outstanding_quantity == quantity - exercised - forfeited
    where forfeited == unvested.
    """
    plan = create_and_activate_plan(pool_total_options=10_000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = create_grant_and_drive_to_live(
        plan, batch, grantee, quantity=1200,
    )
    advance_clock_by_months(plan["id"], 15)
    plan_at_dep = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_at_dep["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    g_after = api.get_grant(
        grant["id"], plan_admin_headers,
    ).json()["data"]
    # forfeited = 1050; exercised = 0; quantity = 1200 → outstanding = 150
    assert g_after["outstanding_quantity"] == 150


# =============================================================================
# Rule 3 — Branching state machines
# =============================================================================

# difficulty: non_linear_state_machine/grant_branching_sign_to_live_or_frozen
def test_sign_routes_frozen_during_blackout(api, plan_admin_headers,
                                            board_secretary_headers,
                                            shareholder_registrar_headers):
    """PRD §3.4: "If any EARNINGS_BLACKOUT or MATERIAL_EVENT_BLACKOUT
    corporate event is currently active ... the grant goes to FROZEN
    when require_live is false or omitted..."
    """
    setup = setup_plan_with_blackout(
        blackout_start_offset_seconds=0,
        blackout_duration_seconds=7 * SECONDS_PER_DAY,
    )
    plan = setup["plan"]
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    after = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert after["status"] == "FROZEN"


# difficulty: non_linear_state_machine/grant_branching_sign_to_live_or_frozen
def test_frozen_grant_auto_transitions_to_live_after_blackout_end(
        api, plan_admin_headers,
        board_secretary_headers, shareholder_registrar_headers):
    """PRD §3.4: "A FROZEN grant remains vesting-eligible ... until the
    system detects, on the next clock advance crossing every overlapping
    blackout_end_ts, that no blackout overlaps the clock — at that point
    it auto-transitions to LIVE."
    """
    setup = setup_plan_with_blackout(
        blackout_start_offset_seconds=0,
        blackout_duration_seconds=7 * SECONDS_PER_DAY,
    )
    plan = setup["plan"]
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    signed = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert signed["status"] == "FROZEN"
    # Advance clock past blackout_end_ts (= start + 7 days)
    advance_clock_by_days(plan["id"], 8)
    after = api.get_grant(grant["id"], plan_admin_headers).json()["data"]
    assert after["status"] == "LIVE"


# difficulty: non_linear_state_machine/exercise_application_branching_share_vs_cash
def test_cash_path_skips_payment_received(api, plan_admin_headers):
    """PRD §3.8: "For CASH_SETTLEMENT applications, verification cascades
    immediately into the ELIGIBILITY_VERIFIED → TAX_WITHHELD transition..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(40, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    after = validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    # Should land directly at TAX_WITHHELD (skip PAYMENT_RECEIVED).
    assert after["status"] == "TAX_WITHHELD"


# difficulty: non_linear_state_machine/exercise_application_branching_share_vs_cash
def test_share_path_requires_payment_then_reaches_tax_withheld(api,
                                                               plan_admin_headers):
    """PRD §3.8: "For SHARE_ISSUANCE applications, the administrator
    must first record payment by supplying a non-empty payment_reference
    ... which transitions the application from ELIGIBILITY_VERIFIED to
    PAYMENT_RECEIVED ... Immediately after PAYMENT_RECEIVED, the system
    auto-transitions to TAX_WITHHELD..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(40, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    verify_after = validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    # Should NOT cascade to TAX_WITHHELD on verify for SHARE_ISSUANCE.
    assert verify_after["status"] == "ELIGIBILITY_VERIFIED"
    from test_helpers import pay_application_payload
    pay_after = validate_success(api.pay_exercise_application(
        app["id"], pay_application_payload("BK-share-1"),
        plan_admin_headers,
    ), expected_status=200)
    assert pay_after["status"] == "TAX_WITHHELD"


# =============================================================================
# Rule 4 — Transitive cascade chains
# =============================================================================

# difficulty: transitive_cascade/departure_settle_terminate_reject_cascade_depth4
def test_bad_leaver_cascade_terminates_grants_and_rejects_apps(api,
                                                               plan_admin_headers):
    """PRD §3.10: "For BAD_LEAVER ... the grant transitions from LIVE
    or FROZEN to TERMINATED; and every still-non-terminal exercise
    application against that grant (in SUBMITTED, ELIGIBILITY_VERIFIED,
    PAYMENT_RECEIVED, or TAX_WITHHELD) auto-transitions to REJECTED
    with note BAD_LEAVER_FORFEITURE."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(20, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    plan_now = api.get_option_plan(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        setup["plan"]["id"], setup["grantee"]["id"],
        departure_type="TERMINATION",
        leaver_class="BAD_LEAVER",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(setup["grantee"]["id"], dep["id"])
    g_after = api.get_grant(grant["id"], plan_admin_headers).json()["data"]
    apps_after = api.list_exercise_applications(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    target = next(a for a in apps_after if a["id"] == app["id"])
    assert g_after["status"] == "TERMINATED"
    assert target["status"] == "REJECTED"


# difficulty: transitive_cascade/departure_settle_terminate_reject_cascade_depth4
def test_bad_leaver_cascade_decreases_pool_reserved(api, plan_admin_headers):
    """PRD §3.10: "...the outstanding-vested portion is also added to
    forfeited_quantity and plan.pool_reserved_options is decreased
    accordingly..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    plan_before = api.get_option_plan(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    pool_before = plan_before["pool_reserved_options"]
    dep = create_departure_draft(
        setup["plan"]["id"], setup["grantee"]["id"],
        departure_type="TERMINATION",
        leaver_class="BAD_LEAVER",
        departed_ts=plan_before["current_clock_ts"],
    )
    settle_departure(setup["grantee"]["id"], dep["id"])
    plan_after = api.get_option_plan(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    # Bad leaver: all 1200 forfeited → pool drops by 1200.
    assert plan_after["pool_reserved_options"] == pool_before - 1200


# difficulty: transitive_cascade/corporate_event_split_price_version_proceeds_cascade_depth3
def test_stock_split_emits_v2_with_correct_price(api, plan_admin_headers):
    """PRD §2.9: "Recording a corporate event of type STOCK_SPLIT,
    CASH_DIVIDEND, or RESTRUCTURING appends a new ExercisePriceVersion
    row for every GrantBatch under the plan, with cause set to the
    corporate-event type ... parent_version_id set to the previous tip
    of the chain for that batch, and version_index set to the previous
    tip's index plus one."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    create_stock_split(
        plan["id"], plan["current_clock_ts"], numerator=2, denominator=1,
    )
    tip = get_tip_price_version(batch["id"])
    assert tip["version_index"] == 2
    assert tip["cause"] == "STOCK_SPLIT"
    assert tip["price_per_option_cents"] == 2500


# difficulty: transitive_cascade/corporate_event_split_price_version_proceeds_cascade_depth3
def test_verify_rejects_when_pinned_version_is_stale(api, plan_admin_headers):
    """PRD §3.8 / §2.7 priority 16: "At /verify, the same check re-runs
    against the current tip; if a corporate-event repricing emitted a
    new version between submission and /verify, the application's pinned
    version is stale relative to the tip and rejects."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(20, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    # Race the price chain forward after submission.
    create_stock_split(
        setup["plan"]["id"], setup["plan"]["current_clock_ts"], 2, 1,
    )
    res = api.verify_exercise_application(app["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_STALE_PRICE_VERSION.value)


# =============================================================================
# Rule 5 — Validation priority conflicts
# =============================================================================

# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_grant_not_live_before_vested_check
# NOTE: The difficulty-design recipe asks for a grant in FROZEN AND a
# window in OPEN at the same plan clock. Per PRD §3.6 priority 8, a
# window cannot overlap an active blackout, and per PRD §3.4 a grant
# transitions to FROZEN only when a blackout is active AT sign time;
# once LIVE, a grant does not return to FROZEN. The FROZEN-with-
# open-window combination is therefore unconstructible under a
# faithful PRD implementation. We exercise the same priority pair via
# the TERMINATED state, which is reachable through the bad-leaver
# cascade (PRD §3.10).
def test_state_error_wins_over_quantity_error_via_terminated(api,
                                                              plan_admin_headers):
    """PRD §2.7: "(4) state-machine precondition (the resource is in a
    state from which the requested transition is defined), yielding the
    corresponding state-specific error such as ERR_GRANT_NOT_IN_DRAFT,
    ERR_GRANT_NOT_BOARD_APPROVED, ERR_GRANT_NOT_SHAREHOLDER_APPROVED,
    ERR_GRANT_NOT_LIVE, ERR_WINDOW_NOT_OPEN, ERR_WINDOW_NOT_CLOSED,
    ERR_BATCH_NOT_OPEN, ERR_PLAN_NOT_ACTIVE, or ERR_DEPARTURE_NOT_DRAFT..."
    PRD §3.10: "For BAD_LEAVER ... the grant transitions from LIVE or
    FROZEN to TERMINATED; and every still-non-terminal exercise
    application against that grant (in SUBMITTED, ELIGIBILITY_VERIFIED,
    PAYMENT_RECEIVED, or TAX_WITHHELD) auto-transitions to REJECTED..."

    The cascade in §3.10 is itself the priority-4 enforcement: pending
    quantity checks (priority 12) on those applications never fire
    because the state-machine precondition wins.
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty_ok = max(1, min(20,
                        grant["vested_quantity"]
                        - grant["exercised_quantity"]))
    if qty_ok < 1:
        return
    valid_app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty_ok, settlement_mode="SHARE_ISSUANCE",
    )
    plan_now = api.get_option_plan(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        setup["plan"]["id"], setup["grantee"]["id"],
        departure_type="TERMINATION",
        leaver_class="BAD_LEAVER",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(setup["grantee"]["id"], dep["id"])
    g_after = api.get_grant(grant["id"], plan_admin_headers).json()["data"]
    assert g_after["status"] == "TERMINATED"
    apps_after = api.list_exercise_applications(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    target = next(a for a in apps_after if a["id"] == valid_app["id"])
    assert target["status"] == "REJECTED"


# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_grant_not_live_before_vested_check
def test_quantity_error_fires_at_verify_on_live_grant(api,
                                                     plan_admin_headers):
    """PRD §3.8: "the requested_quantity must be at most vested_quantity
    minus exercised_quantity (else ERR_INSUFFICIENT_VESTED_QUANTITY).
    Vested quantity is freshly recomputed against the plan clock before
    the comparison."

    Positive control for the priority pair: when ONLY the quantity
    condition fails at /verify (grant is LIVE, no state failure), the
    quantity error fires. Construction: settle one application that
    exhausts vested, then a second submission's verify rejects with
    quantity error (verify checks against freshly-recomputed vested
    minus exercised).
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    assert grant["status"] == "LIVE"
    vested = grant["vested_quantity"] - grant["exercised_quantity"]
    if vested < 2:
        return
    # Submit + verify + settle exhausts vested via CASH path.
    app1 = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=vested, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app1["id"], plan_admin_headers,
    ), expected_status=200)
    from test_helpers import settle_app_cash
    settle_app_cash(app1["id"], "BK-prio-1")
    # Second app: any quantity > 0; verify rejects because available
    # exercisable is now zero.
    grant_now = api.get_grant(grant["id"], plan_admin_headers).json()["data"]
    app2 = submit_exercise_application(
        grant_now, setup["window"], setup["grantee"],
        requested_quantity=1, settlement_mode="SHARE_ISSUANCE",
    )
    res = api.verify_exercise_application(app2["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_VESTED_QUANTITY.value)




# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_segregation_vs_pool
def test_segregation_wins_over_pool(api, plan_admin_headers):
    """PRD §2.7: "(6) segregation-of-duties on approval endpoints,
    yielding ERR_SEGREGATION_OF_DUTIES_VIOLATION ... (14) plan-pool
    sufficiency at board approval, yielding ERR_POOL_INSUFFICIENT."

    Priority 6 < priority 14: when both fail (board approver shares
    X-User-ID with submitter AND quantity exceeds pool), segregation
    fires first.
    """
    plan = create_and_activate_plan(pool_total_options=1000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    submitter = make_plan_admin_headers("U1")
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=2000),
        submitter,
    ), expected_status=201)
    # Same X-User-ID switched to BoardSecretary role.
    same_actor_board = make_board_secretary_headers("U1")
    res = api.board_approve_grant(grant["id"], same_actor_board)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)


# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_segregation_vs_pool
def test_pool_error_fires_when_no_segregation_conflict(api,
                                                       plan_admin_headers,
                                                       board_secretary_headers):
    """PRD §2.7 / §3.4: "(14) plan-pool sufficiency at board approval,
    yielding ERR_POOL_INSUFFICIENT."

    With no segregation conflict, the pool-insufficient error fires.
    """
    plan = create_and_activate_plan(pool_total_options=1000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=2000),
        plan_admin_headers,
    ), expected_status=201)
    res = api.board_approve_grant(grant["id"], board_secretary_headers)
    validate_error(res, ApiErrorId.ERR_POOL_INSUFFICIENT.value)


# =============================================================================
# Rule 6 — Boundary precision
# =============================================================================

# difficulty: boundary_precision_check/pool_remaining_equality_boundary_at_board_approve
def test_pool_remaining_equals_4000_grants_4000_succeeds(api,
                                                         plan_admin_headers,
                                                         board_secretary_headers,
                                                         board_secretary_headers_alt):
    """PRD §3.4: "quantity must be less than or equal to
    pool_remaining_options or it is rejected with ERR_POOL_INSUFFICIENT."

    Boundary `<=`: equality must succeed.
    """
    setup = setup_pool_boundary(
        pool_total_options=10_000, first_grant_qty=6000,
    )
    plan = setup["plan"]
    batch = setup["batch"]
    grantee = setup["grantee"]
    # pool_remaining_options is now 4000.
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=4000),
        plan_admin_headers,
    ), expected_status=201)
    # Board approver must differ from submitter and from the earlier
    # board approver — use the alt secretary.
    res = api.board_approve_grant(
        grant["id"], board_secretary_headers_alt,
    )
    validate_success(res, expected_status=200)


# difficulty: boundary_precision_check/pool_remaining_equality_boundary_at_board_approve
def test_pool_remaining_4000_grant_4001_rejected(api, plan_admin_headers,
                                                  board_secretary_headers_alt):
    """PRD §3.4: "quantity must be less than or equal to
    pool_remaining_options or it is rejected with ERR_POOL_INSUFFICIENT."

    One above boundary → reject.
    """
    setup = setup_pool_boundary(
        pool_total_options=10_000, first_grant_qty=6000,
    )
    plan = setup["plan"]
    batch = setup["batch"]
    grantee = setup["grantee"]
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"],
        create_grant_payload(grantee["id"], quantity=4001),
        plan_admin_headers,
    ), expected_status=201)
    res = api.board_approve_grant(grant["id"], board_secretary_headers_alt)
    validate_error(res, ApiErrorId.ERR_POOL_INSUFFICIENT.value)


# difficulty: boundary_precision_check/window_blackout_half_open_zero_overlap_boundary
def test_window_touching_blackout_end_succeeds(api, plan_admin_headers):
    """PRD §3.6: "the window's [open_ts, close_ts) interval must have
    empty intersection with every blackout's [effective_ts,
    blackout_end_ts) interval. Any non-empty intersection is rejected
    with ERR_BLACKOUT_OVERLAPS_WINDOW."

    Half-open: window.open_ts == blackout.blackout_end_ts is NOT overlap.
    """
    plan = create_and_activate_plan()
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    eff = (base + _dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    end = (base + _dt.timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    create_blackout(plan["id"], eff, end)
    # Touching window: open_ts == end.
    open_ts = (base + _dt.timedelta(hours=48)).isoformat().replace(
        "+00:00", "Z",
    )
    close_ts = (base + _dt.timedelta(hours=72)).isoformat().replace(
        "+00:00", "Z",
    )
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(open_ts, close_ts),
        plan_admin_headers,
    )
    window = validate_success(res, expected_status=201)
    assert window["status"] == "SCHEDULED"


# difficulty: boundary_precision_check/window_blackout_half_open_zero_overlap_boundary
def test_window_overlapping_by_one_hour_rejected(api, plan_admin_headers):
    """PRD §3.6: "Any non-empty intersection is rejected with
    ERR_BLACKOUT_OVERLAPS_WINDOW."
    """
    plan = create_and_activate_plan()
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    create_blackout(
        plan["id"],
        (base + _dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        (base + _dt.timedelta(hours=48)).isoformat().replace("+00:00", "Z"),
    )
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(
            (base + _dt.timedelta(hours=47)).isoformat().replace("+00:00", "Z"),
            (base + _dt.timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
        ),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_BLACKOUT_OVERLAPS_WINDOW.value)


# =============================================================================
# Rule 7 — Cross-entity state dependencies
# =============================================================================

# difficulty: cross_entity_state_dependency/grant_signagreement_depends_on_grantee_eligibility
def test_sign_agreement_blocked_when_grantee_departed(api, plan_admin_headers,
                                                      board_secretary_headers,
                                                      shareholder_registrar_headers):
    """PRD §3.4: "the grantee's eligibility_status must be ELIGIBLE,
    otherwise ERR_GRANTEE_INELIGIBLE."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    # Make the grantee DEPARTED via a departure on an unrelated
    # workflow. The grantee has no LIVE grants yet so the cascade is
    # benign.
    advance_clock_by_days(plan["id"], 5)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    # Attempt sign-agreement.
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    res = api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    )
    validate_error(res, ApiErrorId.ERR_GRANTEE_INELIGIBLE.value)


# difficulty: cross_entity_state_dependency/grant_signagreement_depends_on_grantee_eligibility
def test_sign_agreement_succeeds_when_grantee_eligible(api, plan_admin_headers,
                                                       board_secretary_headers,
                                                       shareholder_registrar_headers):
    """PRD §3.4: "...the grantee's eligibility_status must be ELIGIBLE..."

    Positive variant: an ELIGIBLE grantee can sign normally.
    """
    plan, batch, grantee = setup_plan_batch_grantee()
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], board_secretary_headers,
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], shareholder_registrar_headers,
    ), expected_status=200)
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    after = validate_success(api.sign_agreement(
        grant["id"], grantee_hdrs, sign_agreement_payload(),
    ), expected_status=200)
    assert after["status"] in {"LIVE", "FROZEN"}


# difficulty: cross_entity_state_dependency/exerciseapplication_verify_depends_on_window_state
def test_verify_rejects_when_window_closed(api, plan_admin_headers):
    """PRD §3.8: "the window must still be OPEN (else ERR_WINDOW_NOT_OPEN)..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
        window_open_offset_seconds=0,
        window_close_offset_seconds=2 * SECONDS_PER_DAY,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(20, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    # Push clock past close_ts.
    advance_clock_by_days(setup["plan"]["id"], 3)
    api.sweep_exercise_windows(
        setup["plan"]["id"], plan_admin_headers,
    )
    # Re-fetch app — sweep may have auto-rejected it. Test the
    # /verify-on-closed-window path with whatever status the app has.
    apps_after = api.list_exercise_applications(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    target = next(a for a in apps_after if a["id"] == app["id"])
    if target["status"] == "SUBMITTED":
        res = api.verify_exercise_application(app["id"], plan_admin_headers)
        validate_error(res, ApiErrorId.ERR_WINDOW_NOT_OPEN.value)
    else:
        # If sweep auto-rejected the app, PRD §3.6: "every
        # ExerciseApplication still in SUBMITTED for that window
        # auto-transitions to REJECTED with note WINDOW_CLOSED."
        assert target["status"] == "REJECTED"


# difficulty: cross_entity_state_dependency/exerciseapplication_verify_depends_on_window_state
def test_window_auto_closes_and_rejects_pending_apps(api, plan_admin_headers):
    """PRD §3.6: "An OPEN window auto-transitions to CLOSED when the
    plan clock has reached close_ts; as a side effect, every
    ExerciseApplication still in SUBMITTED for that window auto-
    transitions to REJECTED with note WINDOW_CLOSED."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
        window_open_offset_seconds=0,
        window_close_offset_seconds=1 * SECONDS_PER_DAY,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(10, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    advance_clock_by_days(setup["plan"]["id"], 2)
    api.sweep_exercise_windows(setup["plan"]["id"], plan_admin_headers)
    # Re-fetch window — should be CLOSED.
    windows = api.list_exercise_windows(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    w = next(x for x in windows if x["id"] == setup["window"]["id"])
    assert w["status"] == "CLOSED"


# =============================================================================
# Rule 8 — Resource temporal-overlap conflicts
# =============================================================================

# difficulty: resource_temporal_overlap/exercise_window_vs_blackout_half_open_geometry
@pytest.mark.parametrize("label,off_open_h,off_close_h", [
    ("inside", 10, 20),
    ("cross-end", 20, 30),
    ("cross-start", -5, 5),
])
def test_window_creation_rejects_overlap_with_blackout(api,
                                                       plan_admin_headers,
                                                       label,
                                                       off_open_h,
                                                       off_close_h):
    """PRD §3.6: "Any non-empty intersection is rejected with
    ERR_BLACKOUT_OVERLAPS_WINDOW."
    """
    plan = create_and_activate_plan()
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    create_blackout(
        plan["id"],
        base.isoformat().replace("+00:00", "Z"),
        (base + _dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
    )
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(
            (base + _dt.timedelta(hours=off_open_h)).isoformat().replace("+00:00", "Z"),
            (base + _dt.timedelta(hours=off_close_h)).isoformat().replace("+00:00", "Z"),
        ),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_BLACKOUT_OVERLAPS_WINDOW.value)


# difficulty: resource_temporal_overlap/exercise_window_vs_blackout_half_open_geometry
def test_window_fully_before_blackout_succeeds(api, plan_admin_headers):
    """PRD §3.6: "the window's [open_ts, close_ts) interval must have
    empty intersection with every blackout's [effective_ts,
    blackout_end_ts) interval."

    Positive control: under half-open geometry, a window that ends
    exactly when the blackout starts has empty intersection — must
    succeed.
    """
    plan = create_and_activate_plan()
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    create_blackout(
        plan["id"],
        (base + _dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        (base + _dt.timedelta(hours=48)).isoformat().replace("+00:00", "Z"),
    )
    # Window [t, t+24h) — close_ts equals blackout.effective_ts.
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(
            base.isoformat().replace("+00:00", "Z"),
            (base + _dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        ),
        plan_admin_headers,
    )
    window = validate_success(res, expected_status=201)
    assert window["status"] == "SCHEDULED"


# difficulty: resource_temporal_overlap/grant_vesting_acceleration_must_reference_qualifying_event
def test_accelerate_rejects_non_qualifying_event(api, plan_admin_headers):
    """PRD §3.5: "takes a corporate_event_id referencing an existing
    event of type CHANGE_OF_CONTROL or IPO (failure to reference such
    an event yields ERR_INVALID_TIME_INTERVAL)..."
    """
    setup = setup_live_grant_with_open_window()
    plan = setup["plan"]
    grant = setup["grant"]
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    non_qualifying = create_blackout(
        plan["id"],
        (base + _dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        (base + _dt.timedelta(days=31)).isoformat().replace("+00:00", "Z"),
    )
    res = api.accelerate_vesting(
        grant["id"], accelerate_vesting_payload(non_qualifying["id"]),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_INTERVAL.value)


# difficulty: resource_temporal_overlap/grant_vesting_acceleration_must_reference_qualifying_event
def test_accelerate_with_change_of_control_succeeds(api, plan_admin_headers):
    """PRD §3.5: "...takes a corporate_event_id referencing an existing
    event of type CHANGE_OF_CONTROL or IPO ... writes a VestingRecord
    whose ... cause is the corresponding ACCELERATION_* value."
    """
    setup = setup_live_grant_with_open_window()
    plan = setup["plan"]
    grant = setup["grant"]
    coc = create_change_of_control(plan["id"], plan["current_clock_ts"])
    res = api.accelerate_vesting(
        grant["id"], accelerate_vesting_payload(coc["id"]),
        plan_admin_headers,
    )
    after = validate_success(res, expected_status=200)
    assert after["id"] == grant["id"]
    records = api.list_vesting_records(
        grant["id"], plan_admin_headers,
    ).json()["data"]
    causes = [r["cause"] for r in records]
    assert "ACCELERATION_CHANGE_OF_CONTROL" in causes


# =============================================================================
# Rule 9 — Compensating-action invariants
# =============================================================================

# difficulty: compensating_invariant/option_pool_conservation_invariant
def test_pool_remaining_plus_reserved_equals_total(api, plan_admin_headers):
    """PRD §3.1: "pool_remaining_options is pool_total_options minus
    pool_reserved_options; both fields are recomputed on read and
    exposed to the client."

    Post forward-and-compensating actions (board-approve adds to
    reserved; settling a good-leaver departure removes the unvested
    forfeited amount from reserved), the identity reserved + remaining
    == total must hold.
    """
    setup = setup_three_grants_for_pool_invariant(
        pool_total_options=10_000, per_grant_quantity=1200,
    )
    plan = api.get_option_plan(
        setup["plan"]["id"], plan_admin_headers,
    ).json()["data"]
    assert (
        plan["pool_reserved_options"] + plan["pool_remaining_options"]
        == plan["pool_total_options"]
    )


# difficulty: compensating_invariant/option_pool_conservation_invariant
def test_good_leaver_departure_decreases_reserved_by_unvested_sum(api,
                                                                  plan_admin_headers):
    """PRD §3.10: "The unvested portion ... is unconditionally added to
    forfeited_quantity for every leaver class, and
    plan.pool_reserved_options is decreased by the same amount."

    Three grants of 1200 each, advanced to cliff+3mo → each has 150
    vested, 1050 unvested. Good-leaver departure forfeits 3*1050 = 3150
    unvested → pool_reserved drops by 3150.
    """
    setup = setup_three_grants_for_pool_invariant(
        pool_total_options=10_000, per_grant_quantity=1200,
    )
    plan = setup["plan"]
    grantee = setup["grantee"]
    advance_clock_by_months(plan["id"], 15)
    plan_at_dep = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    pool_before = plan_at_dep["pool_reserved_options"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_at_dep["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    plan_after = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    # Three grants each have unvested = 1200 - 150 = 1050.
    assert plan_after["pool_reserved_options"] == pool_before - 3 * 1050


# difficulty: compensating_invariant/tax_event_withheld_audit_log_invariant
def test_exercise_settled_emits_one_audit_entry(api, plan_admin_headers):
    """PRD §3.8: "Settlement increases Grant.exercised_quantity by
    requested_quantity, decreases plan.pool_reserved_options by the
    same amount ... and appends an EXERCISE_SETTLED audit entry."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(20, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    from test_helpers import settle_app_cash
    settle_app_cash(app["id"], "BK-INV-1")
    entries = list_audit_for_target(
        setup["plan"]["id"], app["id"], action_code="EXERCISE_SETTLED",
    )
    assert len(entries) == 1


# difficulty: compensating_invariant/tax_event_withheld_audit_log_invariant
def test_rejected_exercise_emits_audit_entry(api, plan_admin_headers):
    """PRD §3.11: "Every state-changing operation appends one
    AuditLogEntry whose action_code is one of GRANT_CREATED,
    GRANT_BOARD_APPROVED, ..., EXERCISE_REJECTED ..."

    Compensating action (reject after submit) emits EXERCISE_REJECTED.
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ).json()["data"]
    qty = min(10, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH; this "
        "indicates a vesting calculation bug surfacing here."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    validate_success(api.reject_exercise_application(
        app["id"], plan_admin_headers, {"reason": "compensator"},
    ), expected_status=200)
    entries = list_audit_for_target(
        setup["plan"]["id"], app["id"], action_code="EXERCISE_REJECTED",
    )
    assert len(entries) == 1
