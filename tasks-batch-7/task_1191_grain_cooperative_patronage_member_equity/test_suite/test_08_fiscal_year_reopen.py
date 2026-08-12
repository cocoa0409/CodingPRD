"""Cyclic reopen of a CLOSED_FINAL year and corrected tax forms
(PRD §3.4)."""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_closed_final_year, get_fiscal_year, list_member_tax_forms,
    pass_resolution,
    TEST_USERS,
)

SECRETARY = TEST_USERS["secretary_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _reopened_and_refinalized():
    """Year through CLOSED_FINAL, reopened by a PASSED AMEND_ALLOCATION
    resolution, then finalized again. Returns (ctx, original_form)."""
    ctx = setup_closed_final_year(
        [{"member_key": "patron", "commodity": "CORN", "gross_bushels": 2000}],
        net_margin_cents=800000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.40,
    )
    fy = ctx["fiscal_year"]
    member = ctx["members"]["patron"]
    delegate = ctx["delegate"]
    forms = list_member_tax_forms(member["id"])
    assert len(forms) >= 1, "setup failed: no tax form issued at final close"
    original_form = forms[0]
    resolution = pass_resolution(
        "AMEND_ALLOCATION", fy["id"], delegate["id"],
    )
    reopened = get_success_data(
        api_client.reopen_fiscal_year(
            fy["id"], {"resolution_id": resolution["id"]}, SECRETARY,
        ),
    )
    assert reopened["status"] == "REOPENED", (
        f"setup failed: reopen yielded {reopened['status']}"
    )
    current = get_fiscal_year(fy["id"])
    refinalized = get_success_data(
        api_client.finalize_close(
            fy["id"], {"expected_fiscal_year_version": current["version"]},
            ACCOUNTANT,
        ),
    )
    assert refinalized["status"] == "CLOSED_FINAL"
    return ctx, original_form


def test_reopen_voids_original_tax_form(api):
    """PRD §3.4: "Reopening moves the year to `REOPENED`, clears
    `final_audit_locked`, returns all `FINALIZED` allocations for the year to
    `PROVISIONAL` pending recalculation, and moves the affected tax forms to
    `VOID` with corrected versions pending."

    Design: Difficulty/non_linear_state_machine/fiscal_year_cyclic_reopen_after_final
    """
    ctx, original_form = _reopened_and_refinalized()
    fy_after = get_fiscal_year(ctx["fiscal_year"]["id"])
    assert fy_after["status"] == "CLOSED_FINAL"
    original_after = validate_success(
        api_client.get_tax_form(original_form["id"], ACCOUNTANT), 200,
    )
    assert original_after["status"] == "VOID", (
        f"Original tax form must be VOID after reopen; got "
        f"{original_after['status']}"
    )


def test_corrected_form_links_voided_original(api):
    """PRD §3.4: "When the accountant finalizes a `REOPENED` year — again
    with recalculated allocations reviewed — the reissued tax forms are
    created as `CORRECTED_1099_PATR` forms whose `corrects_form_id` points at
    the voided row, with `is_corrected` set."

    Design: Difficulty/non_linear_state_machine/fiscal_year_cyclic_reopen_after_final
    """
    ctx, original_form = _reopened_and_refinalized()
    member = ctx["members"]["patron"]
    forms = list_member_tax_forms(member["id"])
    corrected = [
        f for f in forms if f["form_type"] == "CORRECTED_1099_PATR"
    ]
    assert len(corrected) >= 1, (
        f"Expected a CORRECTED_1099_PATR after re-finalization; forms: "
        f"{[(f['form_type'], f['status']) for f in forms]}"
    )
    assert any(
        f["corrects_form_id"] == original_form["id"] for f in corrected
    ), "Corrected form must point at the voided original"
    assert all(f["is_corrected"] is True for f in corrected)
