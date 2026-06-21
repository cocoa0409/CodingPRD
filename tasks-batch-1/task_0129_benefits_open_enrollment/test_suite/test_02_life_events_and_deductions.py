"""Life-event approval cascade, prospective-vs-retroactive deduction ledger,
and the conserved-total invariant on the payroll ledger.

Covers Difficulty/dual_variant_calc (retro), Difficulty/transitive_cascade (life event),
Difficulty/compensating_invariant (ledger), and Corner/validations life-event window.
"""
from test_helpers import (
    get_success_data,
    setup_silver_active_with_payrolls, submit_life_event, approve_life_event,
    list_deduction_lines, list_carrier_feed_records,
    setup_eligible_employee, create_offering, create_tier,
    validate_error, ApiErrorId,
    api_client as api,
    build_user_headers, TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]


def test_retroactive_life_event_posts_one_adjustment_line_per_processed_period():
    """PRD §3.7: "Under the retroactive variant, the system walks the already-processed
    pay periods ... and for each period whose billed coverage date falls on or after the
    life event's event_date, it posts exactly one RETRO_ADJUSTMENT deduction line whose
    amount_cents is the new per-paycheck amount minus the old per-paycheck amount."

    Design: Difficulty/dual_variant_calc/retro_deduction_prospective_vs_retroactive
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=3)
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="RETROACTIVE", event_date="2026-02-01",
                           submitter_user_id="admin_submitter")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="admin_approver")
    retro, meta = list_deduction_lines(ctx["employee"]["id"], line_type="RETRO_ADJUSTMENT")
    assert len(retro) == 3, retro
    for line in retro:
        # new_pp 13500 - old_pp 4500 = 9000
        assert line["amount_cents"] == 9000, line
    assert sum(l["amount_cents"] for l in retro) == 27000, retro


def test_prospective_life_event_posts_zero_adjustment_lines():
    """PRD §3.7: "Under the prospective variant, no RETRO_ADJUSTMENT lines are posted
    against already-processed periods; the net retroactive correction is zero and the new
    per-paycheck amount simply applies going forward, from the next unprocessed period
    whose index is at or above the employee's current pay_periods_processed."

    Design: Difficulty/dual_variant_calc/retro_deduction_prospective_vs_retroactive
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=3)
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="PROSPECTIVE", event_date="2026-02-01",
                           submitter_user_id="admin_submitter")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="admin_approver")
    retro, _ = list_deduction_lines(ctx["employee"]["id"], line_type="RETRO_ADJUSTMENT")
    assert len(retro) == 0, retro


def test_life_event_approve_supersedes_prior_and_emits_term_feed():
    """PRD §3.6: "the employee's prior ACTIVE enrollment of the same benefit type
    transitions from ACTIVE to SUPERSEDED, with its coverage_end_date set to the new
    enrollment's coverage_start_date minus one day and its superseded_by_enrollment_id set
    to the new enrollment's id."
    PRD §3.6: "the superseded enrollment emits a carrier feed record with the TERM
    maintenance type and the new enrollment emits one with the ADD maintenance type."

    Design: Difficulty/transitive_cascade/life_event_approve_supersede_term_feed_retro_chain
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=2)
    silver_enr_id = ctx["enrollment"]["id"]
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="RETROACTIVE", event_date="2026-02-01",
                           submitter_user_id="submitter_a")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="approver_b")

    silver = get_success_data(api.get_enrollment(silver_enr_id, _ADMIN))
    assert silver["status"] == "SUPERSEDED", silver
    assert silver["superseded_by_enrollment_id"] is not None, silver
    # The superseding enrollment is the new GOLD enrollment.
    new_enr = get_success_data(api.get_enrollment(silver["superseded_by_enrollment_id"], _ADMIN))
    assert new_enr["plan_tier_id"] == ctx["gold_tier"]["id"], new_enr
    assert new_enr["status"] == "ACTIVE", new_enr

    term, _ = list_carrier_feed_records(enrollment_id=silver_enr_id, transaction_set="TERM")
    assert len(term) == 1, term


def test_life_event_approve_retro_chain_posts_two_adjustment_lines():
    """PRD §3.6: "if the life event's adjustment_mode is RETROACTIVE, the system posts
    retroactive deduction corrections as described in Section 3.7."
    PRD §3.7: "it posts exactly one RETRO_ADJUSTMENT deduction line whose amount_cents is
    the new per-paycheck amount minus the old per-paycheck amount."

    Design: Difficulty/transitive_cascade/life_event_approve_supersede_term_feed_retro_chain
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=2)
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="RETROACTIVE", event_date="2026-02-01",
                           submitter_user_id="submitter_a")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="approver_b")
    retro, _ = list_deduction_lines(ctx["employee"]["id"], line_type="RETRO_ADJUSTMENT")
    assert len(retro) == 2, retro
    for line in retro:
        assert line["amount_cents"] == 9000, line


def test_retro_ledger_total_conserved_no_drift():
    """PRD §3.7: "the total retroactive correction is that per-period difference multiplied
    by the number of affected periods."
    PRD §3.7: "Each run increments the employee's pay_periods_processed by one, posts one
    REGULAR deduction line per ACTIVE enrollment at that enrollment's
    per_paycheck_deduction_cents, and increments the employee's version."

    Design: Difficulty/compensating_invariant/deduction_ledger_total_conserved_under_retro
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=2)
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="RETROACTIVE", event_date="2026-02-01",
                           submitter_user_id="sub_q")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="appr_q")
    all_lines, _ = list_deduction_lines(ctx["employee"]["id"])
    total = sum(l["amount_cents"] for l in all_lines)
    # 2 REGULAR @4500 (=9000) + 2 RETRO_ADJUSTMENT @9000 (=18000) = 27000
    assert total == 27000, all_lines
    # expected owed under the new election = new per_paycheck (13500) * 2 processed periods
    assert total == 13500 * 2, all_lines


def test_retro_lines_close_gap_to_new_election_per_period():
    """PRD §3.7: "for each period whose billed coverage date falls on or after the life
    event's event_date, it posts exactly one RETRO_ADJUSTMENT deduction line whose
    amount_cents is the new per-paycheck amount minus the old per-paycheck amount."
    PRD §3.7: "the total retroactive correction is that per-period difference multiplied by
    the number of affected periods."

    Design: Difficulty/compensating_invariant/deduction_ledger_total_conserved_under_retro
    """
    ctx = setup_silver_active_with_payrolls(num_payrolls=2)
    le = submit_life_event(ctx["employee"]["id"], ctx["gold_tier"]["id"],
                           adjustment_mode="RETROACTIVE", event_date="2026-02-01",
                           submitter_user_id="sub_gap")
    approve_life_event(le["id"], ctx["employee"]["id"], approver_user_id="appr_gap")
    regular, _ = list_deduction_lines(ctx["employee"]["id"], line_type="REGULAR")
    retro, _ = list_deduction_lines(ctx["employee"]["id"], line_type="RETRO_ADJUSTMENT")
    # Per processed period: old REGULAR (4500) + RETRO correction (9000) == new election (13500).
    assert len(regular) == 2 and len(retro) == 2, (regular, retro)
    for r in regular:
        assert r["amount_cents"] == 4500, r
    for a in retro:
        assert a["amount_cents"] == 9000, a
    assert sum(r["amount_cents"] for r in regular) + sum(a["amount_cents"] for a in retro) == 13500 * 2


def test_life_event_approve_window_expired_rejected():
    """PRD §3.6: "approval requires ... the life event's event_date to fall within thirty
    days of the current clock date (otherwise ERR_LIFE_EVENT_WINDOW_EXPIRED)."

    Design: Corner/validations/life_event_window_expired_rejected
    """
    emp = setup_eligible_employee(clock_after="2026-02-01T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_PLUS_SPOUSE",
                       monthly_premium_cents=90000, employer_contribution_pct=0.70)
    get_success_data(api.advance_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, _ADMIN))
    le = submit_life_event(emp["id"], tier["id"], adjustment_mode="PROSPECTIVE",
                           event_date="2026-01-01", submitter_user_id="sub_late")
    ev = get_success_data(api.get_employee(emp["id"], _ADMIN))["version"]
    approver = build_user_headers("appr_late", "BenefitsAdmin")
    resp = api.approve_life_event(le["id"], {"expected_employee_version": ev}, approver)
    validate_error(resp, ApiErrorId.ERR_LIFE_EVENT_WINDOW_EXPIRED.value)
    after = get_success_data(api.get_life_event(le["id"], _ADMIN))
    assert after["status"] == "SUBMITTED", after
