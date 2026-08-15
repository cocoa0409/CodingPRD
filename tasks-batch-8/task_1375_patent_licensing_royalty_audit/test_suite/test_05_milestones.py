"""Milestones: acceptance-triggered achievement cascade, exact-threshold
boundary, DATE milestones via the clock, and void-acceptance reversals
(PRD sections 2.6, 3.4, 3.6)."""
from test_helpers import (
    accept_report,
    create_accepted_report,
    create_active_agreement,
    create_milestone,
    get_agreement,
    get_licensee,
    get_milestone,
    make_report_line,
    set_clock,
    submit_report,
    validate_report,
    validate_success,
)


def test_accept_triggers_milestone_fee_accrual(api, analyst_headers):
    """PRD section 3.6: "Hop 2 re-runs the milestone check of section 3.4
    against the updated cumulative, and hop 3 accrues the fees of any
    milestones thereby achieved." PRD section 3.4: "Achievement sets
    `achieved_at`, adds the milestone's `fee_cents` to the contracting
    licensee's `outstanding_balance_cents` — the fee-accrual hop of the
    acceptance cascade — and increments the milestone's `version`."

    Design: Difficulty/transitive_cascade/accept_triggers_milestone_fee_accrual
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-70700-F1", underreport_tolerance_bp=1000
    )
    milestone = create_milestone(
        agreement["id"], name="Sales 300k",
        trigger_type="CUMULATIVE_SALES", threshold_cents=300_000, fee_cents=25_000,
    )

    # R1: cumulative 200000 — still below the threshold.
    r1 = create_accepted_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=200_000)],
    )
    assert get_milestone(milestone["id"])["status"] == "PENDING"

    # R2: cumulative 200000 + 150000 = 350000 crosses 300000.
    r2 = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=150_000)],
    )
    validate_report(r2["id"], benchmark_net_sales_cents=0)
    accept_report(r2["id"])

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["cumulative_accepted_base_cents"] == 350_000

    milestone_after = get_milestone(milestone["id"])
    assert milestone_after["status"] == "ACHIEVED"
    assert milestone_after["achieved_at"] is not None

    # Balance = 10000 (R1 royalty) + 7500 (R2 royalty) + 25000 (fee).
    licensee_after = get_licensee(licensee["id"])
    assert licensee_after["outstanding_balance_cents"] == 42_500


def test_accept_below_threshold_leaves_milestone_pending(api, analyst_headers):
    """PRD section 3.4: "each `CUMULATIVE_SALES` milestone whose
    `threshold_cents` is less than or equal to the updated cumulative accepted
    base is achieved" — a cumulative below the threshold achieves nothing and
    accrues no fee.

    Design: Difficulty/transitive_cascade/accept_triggers_milestone_fee_accrual
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-70701-F2", underreport_tolerance_bp=1000
    )
    milestone = create_milestone(
        agreement["id"], name="Sales 300k",
        trigger_type="CUMULATIVE_SALES", threshold_cents=300_000, fee_cents=25_000,
    )
    create_accepted_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(gross_sales_cents=200_000)],
    )
    assert get_milestone(milestone["id"])["status"] == "PENDING"
    # Only the royalty accrues; no milestone fee.
    assert get_licensee(licensee["id"])["outstanding_balance_cents"] == 10_000


def test_milestone_exact_threshold_achieves(api, analyst_headers):
    """PRD section 3.4: "Achievement is automatic and inclusive at the
    boundary. ... each `CUMULATIVE_SALES` milestone whose `threshold_cents` is
    less than or equal to the updated cumulative accepted base is achieved — a
    cumulative total exactly equal to the threshold achieves."

    Design: Corner/calculations/milestone_exact_threshold_achieves
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-22223-C2", underreport_tolerance_bp=1000
    )
    milestone = create_milestone(
        agreement["id"], name="M300",
        trigger_type="CUMULATIVE_SALES", threshold_cents=300_000, fee_cents=25_000,
    )
    create_accepted_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=100_000)],
    )
    r2 = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=200_000)],
    )
    validate_report(r2["id"], benchmark_net_sales_cents=0)
    accept_report(r2["id"])

    # Cumulative exactly 300000 == threshold -> ACHIEVED (inclusive >=).
    milestone_after = get_milestone(milestone["id"])
    assert milestone_after["status"] == "ACHIEVED"

    # Balance = 5000 + 10000 royalties + 25000 fee.
    assert get_licensee(licensee["id"])["outstanding_balance_cents"] == 40_000


def test_date_milestone_achieved_on_clock_advance(api, analyst_headers, ipadmin_headers):
    """PRD section 2.6: "every `PENDING` milestone of trigger type `DATE`
    whose `trigger_date` is on or before the new logical time is achieved: its
    `achieved_at` is set, its `fee_cents` accrues to the contracting
    licensee's outstanding balance, and its version increments."

    Design: Corner/state_machines/date_milestone_achieved_on_clock_advance
    """
    licensee, agreement = create_active_agreement(patent_reference="US-78787-Z1")
    milestone = create_milestone(
        agreement["id"], name="Launch", trigger_type="DATE",
        trigger_date="2026-06-15T00:00:00Z", fee_cents=12_000,
    )
    set_clock("2026-08-02T00:00:00Z")

    milestone_after = get_milestone(milestone["id"])
    assert milestone_after["status"] == "ACHIEVED"
    assert milestone_after["achieved_at"] is not None

    assert get_licensee(licensee["id"])["outstanding_balance_cents"] == 12_000


def test_accept_void_roundtrip_balance_conservation(api, analyst_headers):
    """PRD section 3.6: "The void is a true compensating reversal: every
    acceptance posting is subtracted with the amounts originally recorded —
    the adjusted base where one was used — the licensee's outstanding balance
    is relieved of the final royalty, milestones that fall strictly below
    their thresholds revert as in section 3.4 with their fees un-accrued, and
    the report lands in `VOIDED` with another version increment."

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_balance_conservation
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-99999-S1", underreport_tolerance_bp=1000
    )
    milestone = create_milestone(
        agreement["id"], name="M300",
        trigger_type="CUMULATIVE_SALES", threshold_cents=300_000, fee_cents=25_000,
    )
    create_accepted_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=100_000)],
    )
    r2 = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=250_000)],
    )
    validate_report(r2["id"], benchmark_net_sales_cents=0)
    accept_report(r2["id"])

    # Sanity: after accept, milestone achieved and balance includes the fee.
    assert get_milestone(milestone["id"])["status"] == "ACHIEVED"

    resp = api.void_acceptance(r2["id"], {"reason": "acceptance error"}, analyst_headers)
    voided = validate_success(resp)
    assert voided["status"] == "VOIDED"

    # Balance restored to the pre-R2-accept value: R1 royalty 5000 only.
    licensee_after = get_licensee(licensee["id"])
    assert licensee_after["outstanding_balance_cents"] == 5000

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["cumulative_accepted_base_cents"] == 100_000
    assert agreement_after["undistributed_pool_cents"] == 5000

    # Milestone reverts with fee un-accrued (100000 < 300000).
    milestone_after = get_milestone(milestone["id"])
    assert milestone_after["status"] == "PENDING"
    assert milestone_after["achieved_at"] is None


def test_void_acceptance_of_adjusted_report_uses_adjusted_base(api, analyst_headers):
    """PRD section 3.6: "The void is a true compensating reversal: every
    acceptance posting is subtracted with the amounts originally recorded —
    the adjusted base where one was used". PRD section 2.10: "where an
    operation is voidable, the void is a compensating reversal that subtracts
    exactly what the original operation added, using the amounts recorded at
    the time — the adjusted base, not the original base, when the acceptance
    being voided was an adjusted one."

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_balance_conservation
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-99998-S2", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=50_000)],
    )
    validate_report(report["id"], benchmark_net_sales_cents=200_000)
    accepted = accept_report(report["id"], {"adjusted_base_cents": 120_000})
    assert accepted["status"] == "ACCEPTED_WITH_ADJUSTMENT"
    assert accepted["final_royalty_cents"] == 6000

    resp = api.void_acceptance(accepted["id"], {"reason": "adjustment error"}, analyst_headers)
    voided = validate_success(resp)
    assert voided["status"] == "VOIDED"

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["cumulative_accepted_base_cents"] == 0
    assert agreement_after["cumulative_recognized_revenue_cents"] == 0
    assert agreement_after["undistributed_pool_cents"] == 0
    assert get_licensee(licensee["id"])["outstanding_balance_cents"] == 0
