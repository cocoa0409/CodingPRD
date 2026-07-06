"""Money model: dual-variant deposits, invoice net-due computation, late-fee
tiers, deposit-credit conservation, and contract-value reconciliation.

Every test translates exactly one design-index instance; the trailing
`Design:` line names it.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_project_in_concept,
    create_project_in_delivery,
    propose_change_order,
    approve_change_order,
    issue_invoice,
    setup_studio_client,
    create_draft_project,
    add_milestone,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


def test_deposit_provisional_locked_while_final_recomputes_on_change_order(api):
    """PRD §2.6: "The **provisional deposit**, stored in `provisional_deposit_cents`, is computed once at activation from the base scope and is then locked permanently — it is never recomputed, even after scope changes."
    PRD §3.8: "On approval the server recomputes the project's contract_value_cents
    as base_scope_cents plus the sum of the delta_cents of every approved change
    order on the project including the one just approved, then recomputes
    final_deposit_cents as that new contract value multiplied by the project's
    deposit_pct, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/deposit_provisional_locked_vs_final_recomputed_on_change_order
    """
    # Three milestones 30000/40000/30000 -> base_scope_cents 100000.
    studio, client = setup_studio_client()
    project = create_draft_project(studio["id"], client["id"], deposit_pct=0.30, service_type="IDENTITY")
    add_milestone(studio["id"], project["id"], 30000, 1)
    add_milestone(studio["id"], project["id"], 40000, 2)
    add_milestone(studio["id"], project["id"], 30000, 3)
    get_success_data(api.activate_project(studio["id"], project["id"], SO))
    # approve a moodboard, advance to CONCEPT
    mb = get_success_data(api.create_moodboard(studio["id"], project["id"], {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(studio["id"], project["id"], mb["id"], DES))
    get_success_data(api.approve_moodboard(studio["id"], project["id"], mb["id"], make_client_headers(client["id"])))
    proj = get_success_data(api.advance_project(studio["id"], project["id"], SO))
    pv = proj["version"]

    co = propose_change_order(studio["id"], project["id"], 50000, pv, reason="SCOPE_ADD")
    approve_change_order(studio["id"], co["id"], client["id"])

    data = validate_success(api.get_project(studio["id"], project["id"], SO))
    assert data["provisional_deposit_cents"] == 30000, "provisional locked at base 100000 * 0.30"
    assert data["contract_value_cents"] == 150000, "100000 + 50000 approved delta"
    assert data["final_deposit_cents"] == 45000, "150000 * 0.30"
    assert data["final_deposit_cents"] - data["provisional_deposit_cents"] == 15000


def test_deposit_dual_variant_delta_is_fifteen_thousand(api):
    """PRD §2.6: "the final deposit diverges upward or downward from the
    provisional deposit the moment any change order is approved, because the final
    deposit follows contract_value_cents while the provisional deposit stays frozen
    on base_scope_cents."

    Design: Difficulty/dual_variant_calc/deposit_provisional_locked_vs_final_recomputed_on_change_order
    """
    studio, client = setup_studio_client()
    project = create_draft_project(studio["id"], client["id"], deposit_pct=0.30, service_type="IDENTITY")
    add_milestone(studio["id"], project["id"], 30000, 1)
    add_milestone(studio["id"], project["id"], 40000, 2)
    add_milestone(studio["id"], project["id"], 30000, 3)
    get_success_data(api.activate_project(studio["id"], project["id"], SO))
    mb = get_success_data(api.create_moodboard(studio["id"], project["id"], {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(studio["id"], project["id"], mb["id"], DES))
    get_success_data(api.approve_moodboard(studio["id"], project["id"], mb["id"], make_client_headers(client["id"])))
    proj = get_success_data(api.advance_project(studio["id"], project["id"], SO))

    before = validate_success(api.get_project(studio["id"], project["id"], SO))
    assert before["provisional_deposit_cents"] == before["final_deposit_cents"] == 30000, \
        "provisional and final equal at activation"

    co = propose_change_order(studio["id"], project["id"], 50000, proj["version"], reason="SCOPE_ADD")
    approve_change_order(studio["id"], co["id"], client["id"])

    after = validate_success(api.get_project(studio["id"], project["id"], SO))
    assert after["final_deposit_cents"] - after["provisional_deposit_cents"] == 15000


def _project_to_delivery_with_milestone(api, amount, deposit_pct, tax_rate, deposit_cents):
    """Helper local to this file mirroring the design recipe: project in DELIVERY
    with one milestone, a deposit collected. Returns (studio, client, project, mid)."""
    studio, client, project, milestones = create_project_in_delivery(
        [amount], deposit_pct=deposit_pct, tax_rate=tax_rate, deposit_cents=deposit_cents,
        service_type="LOGO",
    )
    return studio, client, project, milestones[0]


def test_invoice_late_fee_zero_at_issue_then_tier1_when_overdue(api):
    """PRD §3.6: "While the invoice is merely `ISSUED` and not overdue, its
    `late_fee_cents` is zero, and its `net_due_cents` is the taxable base plus the tax."
    PRD §3.6: "if it is at most thirty days the late fee is the net-before-fee
    multiplied by a first-tier rate of one and one-half percent (0.015), rounded
    half up to whole cents"

    Design: Difficulty/dual_variant_calc/invoice_late_fee_at_issue_vs_overdue_variant_divergence
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00Z", BO))
    studio, client, project, mid = _project_to_delivery_with_milestone(
        api, 40000, deposit_pct=0.30, tax_rate=0.0825, deposit_cents=12000
    )
    inv = issue_invoice(studio["id"], mid["id"], "2026-03-10T00:00:00Z")
    assert inv["late_fee_cents"] == 0, "at_issue: no late fee"
    assert inv["net_due_cents"] == 30310, "taxable 28000 + tax 2310"

    get_success_data(api.set_clock("2026-03-25T00:00:00Z", BO))
    overdue = validate_success(api.mark_invoice_overdue(studio["id"], inv["id"], BO))
    assert overdue["late_fee_cents"] == 455, "tier-1 0.015 on net_before_fee 30310"
    assert overdue["net_due_cents"] == 30765, "30310 + 455"


def test_invoice_net_due_at_issue_matches_credited_taxable_plus_tax(api):
    """PRD §3.6: "The tax_cents is that taxable base multiplied by the studio's
    tax_rate, rounded half up to whole cents — and this tax is computed on the
    credited taxable base, before any late fee."

    Design: Difficulty/dual_variant_calc/invoice_late_fee_at_issue_vs_overdue_variant_divergence
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00Z", BO))
    studio, client, project, mid = _project_to_delivery_with_milestone(
        api, 40000, deposit_pct=0.30, tax_rate=0.0825, deposit_cents=12000
    )
    inv = issue_invoice(studio["id"], mid["id"], "2026-03-10T00:00:00Z")
    assert inv["gross_cents"] == 40000
    assert inv["deposit_credit_cents"] == 12000, "min(round(40000*0.30)=12000, collected 12000)"
    assert inv["tax_cents"] == 2310, "round_half_up(28000 * 0.0825)"
    assert inv["net_due_cents"] == 30310


def test_late_fee_stays_tier1_at_exactly_thirty_days_overdue(api):
    """PRD §3.6: "The boundary is inclusive at thirty: exactly thirty days overdue
    stays in the first tier, and the second tier engages only past thirty days."

    Design: Difficulty/boundary_precision_check/late_fee_tier_flip_at_exactly_30_days_overdue
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00Z", BO))
    studio, client, project, mid = _project_to_delivery_with_milestone(
        api, 40000, deposit_pct=0.30, tax_rate=0.0825, deposit_cents=12000
    )
    inv = issue_invoice(studio["id"], mid["id"], "2026-03-10T00:00:00Z")

    # due 2026-03-10, clock 2026-04-09 == exactly 30 days overdue
    get_success_data(api.set_clock("2026-04-09T00:00:00Z", BO))
    overdue = validate_success(api.mark_invoice_overdue(studio["id"], inv["id"], BO))
    assert overdue["late_fee_cents"] == 455, "tier-1 at the inclusive 30-day boundary"
    assert overdue["net_due_cents"] == 30765


def test_late_fee_jumps_to_tier2_past_thirty_days_overdue(api):
    """PRD §3.6: "if it is more than thirty days the late fee is the net-before-fee
    multiplied by a second-tier rate of three percent (0.030), rounded half up to
    whole cents"

    Design: Difficulty/boundary_precision_check/late_fee_tier_flip_at_exactly_30_days_overdue
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00Z", BO))
    studio, client, project, mid = _project_to_delivery_with_milestone(
        api, 40000, deposit_pct=0.30, tax_rate=0.0825, deposit_cents=12000
    )
    inv = issue_invoice(studio["id"], mid["id"], "2026-03-10T00:00:00Z")

    # due 2026-03-10, clock 2026-04-10 == 31 days overdue -> tier-2
    get_success_data(api.set_clock("2026-04-10T00:00:00Z", BO))
    overdue = validate_success(api.mark_invoice_overdue(studio["id"], inv["id"], BO))
    assert overdue["late_fee_cents"] == 909, "round_half_up(30310 * 0.030)"


def test_deposit_credit_conserved_across_two_invoices(api):
    """PRD §3.6: "the amount of the project's deposit_collected_cents that earlier
    invoices on the project have not already consumed."
    PRD §3.6: "so each invoice only ever credits deposit cash not yet spent by an
    earlier-sequenced invoice."

    Design: Difficulty/compensating_invariant/deposit_credit_conservation_across_two_invoices
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000, 40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000, service_type="IDENTITY"
    )
    m1, m2 = milestones
    inv1 = issue_invoice(studio["id"], m1["id"], "2026-04-01T00:00:00Z")
    inv2 = issue_invoice(studio["id"], m2["id"], "2026-04-01T00:00:00Z")

    assert inv1["deposit_credit_cents"] == 12000, "first invoice draws the full deposit"
    assert inv2["deposit_credit_cents"] == 0, "deposit already consumed"


def test_deposit_credit_sum_equals_collected_deposit(api):
    """PRD §3.6: "Deposit credit is drawn down across a project's invoices in
    ascending milestone sequence_index order, breaking ties by created_at ascending,
    so each invoice only ever credits deposit cash not yet spent by an earlier-
    sequenced invoice."

    Design: Difficulty/compensating_invariant/deposit_credit_conservation_across_two_invoices
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000, 40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000, service_type="IDENTITY"
    )
    m1, m2 = milestones
    inv1 = issue_invoice(studio["id"], m1["id"], "2026-04-01T00:00:00Z")
    inv2 = issue_invoice(studio["id"], m2["id"], "2026-04-01T00:00:00Z")
    assert inv1["deposit_credit_cents"] + inv2["deposit_credit_cents"] == 12000


def test_contract_value_reconciled_after_two_change_order_approvals(api):
    """PRD §3.8: "On approval the server recomputes the project's
    contract_value_cents as base_scope_cents plus the sum of the delta_cents of
    every approved change order on the project including the one just approved"

    Design: Corner/cross_cutting_complexity_layers/contract_value_derived_field_reconciled_after_two_approvals
    """
    studio, client, project, _ = create_project_in_concept(
        [100000], deposit_pct=0.30, service_type="IDENTITY"
    )
    pv1 = validate_success(api.get_project(studio["id"], project["id"], SO))["version"]
    co1 = propose_change_order(studio["id"], project["id"], 50000, pv1, reason="SCOPE_ADD")
    approve_change_order(studio["id"], co1["id"], client["id"])

    pv2 = validate_success(api.get_project(studio["id"], project["id"], SO))["version"]
    co2 = propose_change_order(studio["id"], project["id"], -20000, pv2, reason="SCOPE_ADD")
    approve_change_order(studio["id"], co2["id"], client["id"])

    data = validate_success(api.get_project(studio["id"], project["id"], SO))
    assert data["contract_value_cents"] == 130000, "100000 + 50000 - 20000"
    assert data["final_deposit_cents"] == 39000, "130000 * 0.30"
