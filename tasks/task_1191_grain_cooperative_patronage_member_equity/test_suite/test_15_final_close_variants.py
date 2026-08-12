"""Final close under the FINAL calculation variant: agree-path finalization
and tax-form issuance (PRD §3.4)."""
from test_helpers import (
    setup_closed_final_year, close_year_provisional, finalize_year,
    setup_year_with_deliveries, list_year_allocations,
    list_member_tax_forms, get_fiscal_year,
    TEST_USERS,
)

ACCOUNTANT = TEST_USERS["accountant_headers"]


def test_agreeing_final_variant_finalizes_allocations(api):
    """PRD §3.4: "Finalization recomputes every allocation under the `FINAL`
    variant: the audited `net_margin_cents` replaces the provisional figure,
    deliveries cancelled after the provisional close are excluded, and the
    same largest-volume rounding-reconciliation rule is applied. Every
    allocation must be reviewed before finalization — either a `FINAL`
    variant row exists for it or its `PROVISIONAL` row is confirmed. Where
    the `FINAL` computation agrees with the provisional figures, the
    allocation transitions `PROVISIONAL` → `FINALIZED`."

    With no audit adjustment the two computation passes agree, so the
    allocations finalize.

    Design: Difficulty/dual_variant_calc/patronage_allocation_provisional_vs_final_on_member_equity
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "m_t2", "commodity": "CORN", "gross_bushels": 5000},
            {"member_key": "m_t3", "commodity": "SOYBEAN",
             "gross_bushels": 15000},
        ],
        net_margin_cents=1000000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.40,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    provisional = {
        a["member_id"]: a for a in list_year_allocations(fy["id"])
    }
    assert len(provisional) == 2
    assert all(a["status"] == "PROVISIONAL" for a in provisional.values())
    finalized_fy = finalize_year(fy["id"])
    assert finalized_fy["status"] == "CLOSED_FINAL"
    final = list_year_allocations(fy["id"])
    assert len(final) == 2
    for alloc in final:
        assert alloc["status"] == "FINALIZED", (
            "Agreeing FINAL computation must move the allocation to "
            f"FINALIZED; got {alloc['status']}"
        )
        before = provisional[alloc["member_id"]]
        assert (
            alloc["qualified_allocation_cents"]
            == before["qualified_allocation_cents"]
        ), (
            "With an unchanged margin the FINAL pass must agree with the "
            f"provisional figure; {alloc['qualified_allocation_cents']} != "
            f"{before['qualified_allocation_cents']}"
        )


def test_final_close_issues_tax_forms_to_patrons(api):
    """PRD §3.4: "Finalization also sets the year's `final_audit_locked`
    flag, transitions every certificate issued by the year's close from
    `ISSUED` to `ACTIVE`, and issues a patron tax form for every patron whose
    allocation is greater than zero."

    Design: Difficulty/dual_variant_calc/patronage_allocation_provisional_vs_final_on_member_equity
    """
    ctx = setup_closed_final_year(
        [
            {"member_key": "m_t2", "commodity": "CORN", "gross_bushels": 5000},
            {"member_key": "m_t3", "commodity": "SOYBEAN",
             "gross_bushels": 15000},
        ],
        net_margin_cents=1000000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.40,
    )
    fy = get_fiscal_year(ctx["fiscal_year"]["id"])
    assert fy["status"] == "CLOSED_FINAL"
    assert fy["final_audit_locked"] is True
    for key in ("m_t2", "m_t3"):
        forms = list_member_tax_forms(ctx["members"][key]["id"])
        assert len(forms) >= 1, (
            f"Expected a patron tax form issued for {key} at final close"
        )
        assert any(f["form_type"] == "FORM_1099_PATR" for f in forms)
