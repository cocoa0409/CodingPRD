"""Fund audits: dual assessment variants, payments, and the forfeit cascade (PRD §3.7)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def _setup_two_period_audit():
    """ULB production with ACCEPTED reports for periods 5 and 6 (finals 34,000
    and 17,000 at the ULB rate), one listed log voided after acceptance, then a
    budget revision to 40,000,000 upgrading the tier to MODIFIED_LOW_BUDGET.
    At audit time (rate 18, cap 150,000): period 5 expects 18,000 (one voided
    log dropped) -> shortfall -16,000; period 6 expects 18,000 -> shortfall
    +1,000."""
    bundle = th.create_in_production(
        "Ridge Pictures LLC", "98-7654321", title="Ridge Line",
        activate=("W-CAM-1",),
    )
    company, production = bundle["company"], bundle["production"]
    cam = bundle["assignments"]["W-CAM-1"]
    logs = []
    for date in ("2026-08-10", "2026-08-12", "2026-08-13"):
        log = th.record_log(cam, company, date)
        logs.append(th.submit_log(log, company))
    th.create_accepted_report(production, company, 5, [logs[0]["id"], logs[1]["id"]])
    th.create_accepted_report(production, company, 6, [logs[2]["id"]])
    th.void_log(logs[1], company)
    th.revise_budget(production, company, 40_000_000)
    audit = th.open_audit(production, [5, 6], "ft_1")
    return bundle, audit


def test_assessment_per_period_no_netting(api):
    """PRD §3.7: "The official per-period variant floors each period's
    shortfall at zero, multiplies by 110 and divides by 100 with round-half-up
    to whole cents, and sums those per-period amounts into `assessment_cents` —
    over-reported periods cannot offset under-reported ones."
    Period 5 is over-reported by 16,000 (floored to 0); period 6 is
    under-reported by 1,000 (x 110/100 = 1,100): assessment 1,100 cents.

    Design: Difficulty/dual_variant_calc/audit_assessment_per_period_vs_aggregate_netting
    """
    bundle, audit = _setup_two_period_audit()

    issued = th.issue_findings(audit, "ft_1")
    th.assert_audit(issued)
    assert issued["status"] == "FINDINGS_ISSUED"
    assert issued["assessment_cents"] == 1100, (
        "per-period variant: max(0,-16000)*1.1 + round(1000*110/100) = 1100"
    )


def test_alt_assessment_aggregate_nets_overreports(api):
    """PRD §3.7: "The informational aggregate variant instead nets all
    shortfalls across periods first, floors the net at zero, and applies the
    same 110-per-100 penalty with a single rounding, landing in
    `alt_assessment_cents`." Shortfalls -16,000 + 1,000 net to -15,000, floored
    at 0: alt assessment 0 cents — the two variants diverge on identical input.

    Design: Difficulty/dual_variant_calc/audit_assessment_per_period_vs_aggregate_netting
    """
    bundle, audit = _setup_two_period_audit()

    issued = th.issue_findings(audit, "ft_1")
    assert issued["alt_assessment_cents"] == 0, (
        "aggregate variant: max(0, -16000 + 1000) * 1.1 = 0"
    )
    assert issued["assessment_cents"] != issued["alt_assessment_cents"]


def _setup_underfunded_audit():
    """ULB production, period-1 report ACCEPTED at final 17,000, then tier
    upgraded to MODIFIED_LOW_BUDGET (bond UNDERFUNDED, posture RESTRICTED).
    Audit findings: expected 100,000 x 18/100 = 18,000 vs reported 17,000 ->
    shortfall 1,000 -> assessment round(1000 x 110/100) = 1,100, unpaid."""
    bundle = th.setup_accepted_report("Kestrel Media LLC", "77-6666666",
                                      period=1)
    th.revise_budget(bundle["production"], bundle["company"], 40_000_000)
    audit = th.open_audit(bundle["production"], [1], "ft_1")
    audit = th.issue_findings(audit, "ft_1")
    assert audit["assessment_cents"] == 1100, (
        f"Setup failed: expected assessment 1100, got {audit['assessment_cents']}"
    )
    return bundle, audit


def test_close_with_unpaid_assessment_forfeits_bond(api):
    """PRD §3.7: "Closing from `FINDINGS_ISSUED` with the assessment not fully
    paid triggers the forfeit cascade: the production's bond, whether `POSTED`
    or `UNDERFUNDED`, transitions to `FORFEITED`, the entire held amount moves
    into `total_forfeited_cents`, `amount_held_cents` is zeroed".

    Design: Difficulty/transitive_cascade/audit_close_bond_forfeit_company_cascade
    """
    bundle, audit = _setup_underfunded_audit()
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]

    closed = th.close_audit(audit, "ft_2")
    assert closed["status"] == "CLOSED"

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    bond_after = bonds[0]
    assert bond_after["status"] == "FORFEITED"
    assert bond_after["total_forfeited_cents"] == 2_500_000
    assert bond_after["amount_held_cents"] == 0
    th.assert_bond_ledger_conservation(bond_after)


def test_bond_forfeiture_suspends_company(api):
    """PRD §3.7: "the entire held amount moves into `total_forfeited_cents`,
    `amount_held_cents` is zeroed, the producer company transitions from
    `SIGNATORY` to `SUSPENDED`, and the production's posture is recomputed. The
    audit lands in `CLOSED`, which is terminal."

    Design: Difficulty/transitive_cascade/audit_close_bond_forfeit_company_cascade
    """
    bundle, audit = _setup_underfunded_audit()
    company = bundle["company"]

    closed = th.close_audit(audit, "ft_2")
    assert closed["status"] == "CLOSED"
    assert closed["assessment_cents"] == 1100

    company_after = th.get_company(company)
    assert company_after["status"] == "SUSPENDED"


def test_zero_variance_audit_clean_close(api):
    """PRD §3.7: "the period's shortfall is that expectation minus the report's
    `final_contributions_due_cents`" — with no voids and no tier change the
    shortfall is 0, and "The official per-period variant floors each period's
    shortfall at zero, multiplies by 110 and divides by 100 with round-half-up
    to whole cents". PRD §3.7: "Closing from `FINDINGS_ISSUED` with the
    assessment not fully paid triggers the forfeit cascade" — a zero assessment
    is fully paid, so no forfeit fires.

    Design: Corner/calculations/audit_zero_variance_assessment_zero_clean_close
    """
    bundle = th.setup_accepted_report("Bistort LLC", "20-0000027", period=1)
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]
    audit = th.open_audit(production, [1], "ft_1")

    issued = th.issue_findings(audit, "ft_1")
    assert issued["assessment_cents"] == 0
    assert issued["alt_assessment_cents"] == 0

    closed = th.close_audit(issued, "ft_2")
    assert closed["status"] == "CLOSED"

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert bonds[0]["status"] == "POSTED", "no forfeit on a zero assessment"
    assert th.get_company(company)["status"] == "SIGNATORY"


def test_opening_trustee_cannot_close(api):
    """PRD §3.7: "Closing an audit is segregated from opening it: the acting
    `FundTrustee`'s `X-User-ID` must differ from `opened_by_user_id`, or the
    request is `ERR_SEGREGATION_OF_DUTIES`." and "The closer's identity is
    recorded as `closed_by_user_id`."

    Design: Corner/validations/audit_close_by_opening_trustee_rejected
    """
    bundle = th.create_staffing_production("Gromwell LLC", "20-0000034",
                                           title="Gromwell Field",
                                           scope="TELEVISION")
    audit = th.open_audit(bundle["production"], [1], "ft_1")

    resp = api.close_audit(audit["id"], th.make_fund_trustee_headers("ft_1"))
    th.validate_error(resp, E.ERR_SEGREGATION_OF_DUTIES)

    closed = th.close_audit(audit, "ft_2")
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "ft_2"


def test_audit_overpayment_then_full_pay_and_topup(api):
    """PRD §3.7: "each `amount_cents` must be greater than zero and must not
    push `assessment_paid_cents` past `assessment_cents` (`ERR_OVERPAYMENT`)"
    and "Payments accumulate and the posture is recomputed after each, so
    paying in full may clear a `RESTRICTED` posture." Paying 1,200 against an
    1,100 assessment fails; paying exactly 1,100 settles it, and the subsequent
    bond top-up of 2,500,000 clears the remaining underfunding so the posture
    returns to CLEAR.

    Design: Corner/cross_cutting_layers/audit_overpayment_rejected_then_full_payment_and_topup_clear_posture
    """
    bundle, audit = _setup_underfunded_audit()
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]

    resp = api.pay_audit(audit["id"], {"amount_cents": 1200},
                         th.owner_headers(company))
    th.validate_error(resp, E.ERR_OVERPAYMENT)

    paid = th.pay_audit(audit, company, 1100)
    assert paid["assessment_paid_cents"] == 1100, "full payment accepted"

    topped = th.get_success_data(api.top_up_bond(
        bond["id"], {"amount_cents": 2_500_000}, th.owner_headers(company),
    ))
    assert topped["status"] == "POSTED"
    assert th.get_production(production["id"], company)["compliance_posture"] == "CLEAR"
