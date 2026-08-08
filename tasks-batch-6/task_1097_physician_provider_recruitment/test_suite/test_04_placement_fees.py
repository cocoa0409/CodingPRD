"""Placement fees (estimate vs final), relocation reimbursement, credentialing,
and the independent placement status axes."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_placement_pre_start, setup_placement_active, setup_placement_invoiced,
    set_clock, add_credential_item, item_transition,
    create_relocation_expense_payload,
    make_account_manager_headers, make_credentialing_coordinator_headers,
    TEST_DEFAULTS,
)


# --------------------------------------------------------------------------
# dual-variant placement fee: estimate vs final
# --------------------------------------------------------------------------
def test_placement_fee_estimate_variant_at_accept(api):
    """PRD §3.6: "That figure is multiplied by the client's contingency_pct, and
    then by a hard-to-fill multiplier of 1.20 when the opening's is_hard_to_fill
    flag is set ... The product of compensation, contingency rate, and multiplier is
    rounded half up to whole cents to give a raw fee, and the stored fee is the
    greater of that raw fee and the client's min_fee_cents floor."

    Design: Difficulty/dual_variant_calc/placement_fee_estimate_vs_final_divergence
    """
    # offered comp = 24,000,000 + 2,500,000 = 26,500,000; x0.20 x1.20 = 6,360,000.
    ctx = setup_placement_pre_start(
        is_hard_to_fill=True, offer_overrides={"sign_on_bonus_cents": 2_500_000}
    )
    assert ctx["placement"]["fee_estimate_cents"] == 6_360_000


def test_placement_fee_final_variant_diverges_from_estimate(api):
    """PRD §3.8: "The final fee uses the identical arithmetic as the estimate ...
    but the first-year compensation input is the signed final_first_year_comp_cents
    rather than the offered snapshot, so the two figures may differ."

    Design: Difficulty/dual_variant_calc/placement_fee_estimate_vs_final_divergence
    """
    # final comp 25,000,000 x0.20 x1.20 = 6,000,000 (vs estimate 6,360,000).
    ctx = setup_placement_invoiced(
        final_first_year_comp_cents=25_000_000,
        is_hard_to_fill=True, offer_overrides={"sign_on_bonus_cents": 2_500_000},
    )
    placement = ctx["placement"]
    assert placement["placement_fee_cents"] == 6_000_000
    assert placement["fee_estimate_cents"] == 6_360_000
    assert placement["fee_estimate_cents"] - placement["placement_fee_cents"] == 360_000


# --------------------------------------------------------------------------
# combinatorial fee formula: min-fee floor
# --------------------------------------------------------------------------
def test_placement_fee_floor_binds_when_product_below_min(api):
    """PRD §3.6: "the stored fee is the greater of that raw fee and the client's
    min_fee_cents floor."

    Design: Difficulty/combinatorial_formula/placement_fee_floor_binds_mode_a
    """
    # offered 8,000,000 x0.20 x1.0 = 1,600,000 < floor 2,000,000 -> 2,000,000.
    ctx = setup_placement_pre_start(
        is_hard_to_fill=False, comp_min_cents=5_000_000, comp_max_cents=10_000_000,
        offer_overrides={"base_salary_cents": 7_000_000, "sign_on_bonus_cents": 1_000_000},
    )
    assert ctx["placement"]["fee_estimate_cents"] == 2_000_000


def test_placement_fee_percentage_wins_when_product_above_floor(api):
    """PRD §3.6: "the stored fee is the greater of that raw fee and the client's
    min_fee_cents floor."

    Design: Difficulty/combinatorial_formula/placement_fee_floor_binds_mode_a
    """
    # offered 20,000,000 x0.20 x1.0 = 4,000,000 > floor 2,000,000 -> 4,000,000.
    ctx = setup_placement_pre_start(
        is_hard_to_fill=False, offer_overrides={"base_salary_cents": 20_000_000},
    )
    assert ctx["placement"]["fee_estimate_cents"] == 4_000_000


# --------------------------------------------------------------------------
# relocation reimbursement: per-line rounding before summing
# --------------------------------------------------------------------------
def _approve_expense(api, am_id, placement_id, category, amount_cents, is_taxable):
    exp = validate_success(
        api.create_relocation_expense(
            placement_id,
            create_relocation_expense_payload(category, amount_cents, is_taxable=is_taxable),
            make_account_manager_headers(am_id),
        ),
        201,
    )
    validate_success(
        api.transition_placement(
            placement_id, {"action": "RELOCATION_APPROVE", "expense_id": exp["id"]},
            make_account_manager_headers(am_id),
        )
    )
    return exp


def _reimburse_three_lines(api):
    ctx = setup_placement_pre_start(
        offer_overrides={"base_salary_cents": 25_000_000, "relocation_cap_cents": 2_000_000},
    )
    am_id, pid = ctx["am_id"], ctx["placement_id"]
    _approve_expense(api, am_id, pid, "MOVERS", 1_000_000, False)
    _approve_expense(api, am_id, pid, "TEMP_HOUSING", 333_333, True)
    _approve_expense(api, am_id, pid, "FLIGHTS", 250_001, True)
    reimbursed = validate_success(
        api.transition_placement(
            pid, {"action": "RELOCATION_REIMBURSE"}, make_account_manager_headers(am_id)
        )
    )
    return reimbursed


def test_relocation_reimbursement_rounds_per_line_before_summing(api):
    """PRD §3.8: "each taxable line's amount_cents is grossed up by a tax factor of
    1.25 and rounded half up to whole cents, while a non-taxable line contributes its
    raw amount_cents; these per-line amounts are summed after their individual
    rounding, and the reimbursed total is capped at the placement's
    relocation_cap_cents. The per-line rounding happens before summing."

    Design: Difficulty/combinatorial_formula/relocation_per_line_rounding_mode_b
    """
    # 1,000,000 + round(333,333*1.25)=416,666 + round(250,001*1.25)=312,501 = 1,729,167.
    reimbursed = _reimburse_three_lines(api)
    assert reimbursed["relocation_reimbursed_cents"] == 1_729_167


def test_relocation_reimbursement_moves_status_to_reimbursed(api):
    """PRD §3.8: "Once the placement's relocation_status is APPROVED, an
    AccountManager reimburses (APPROVED → REIMBURSED)".

    Design: Difficulty/combinatorial_formula/relocation_per_line_rounding_mode_b
    """
    reimbursed = _reimburse_three_lines(api)
    assert reimbursed["relocation_status"] == "REIMBURSED"
    assert reimbursed["relocation_reimbursed_cents"] <= reimbursed["relocation_cap_cents"]


# --------------------------------------------------------------------------
# parallel status axes independence
# --------------------------------------------------------------------------
def test_invoice_advances_fee_axis_to_invoiced(api):
    """PRD §3.8: "an AccountManager invoices a placement (fee_status
    PENDING → INVOICED)."

    Design: Difficulty/non_linear_state_machine/placement_parallel_axes_independent
    """
    ctx = setup_placement_invoiced(final_first_year_comp_cents=25_000_000)
    assert ctx["placement"]["fee_status"] == "INVOICED"


def test_invoice_leaves_lifecycle_axis_active(api):
    """PRD §2.8: "A transition on one axis never implicitly moves another except
    where a cascade explicitly says so".
    PRD §3.8: "On the billing axis, which evolves independently of the lifecycle
    axis, an AccountManager invoices a placement".

    Design: Difficulty/non_linear_state_machine/placement_parallel_axes_independent
    """
    ctx = setup_placement_invoiced(final_first_year_comp_cents=25_000_000)
    assert ctx["placement"]["placement_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# credentialing clears file; onboarding gated by cleared file
# --------------------------------------------------------------------------
def test_verify_sole_required_item_clears_file(api):
    """PRD §3.7: "it becomes CLEARED from IN_PROGRESS exactly when every item with
    is_required true is VERIFIED and no item is FLAGGED".
    PRD §3.7: "A cleared credentialing file is the precondition for onboarding."

    Design: Corner/state_machines/credential_item_verify_clears_file
    """
    ctx = setup_placement_pre_start()
    item = add_credential_item(ctx["coord_id"], ctx["cfile_id"], "STATE_LICENSE", is_required=True)
    item_transition(ctx["coord_id"], item["id"], "SUBMIT")
    validate_success(
        api.transition_credential_item(
            item["id"], "VERIFY", make_credentialing_coordinator_headers(ctx["coord_id"])
        )
    )
    cfile = validate_success(
        api.get_credentialing_file(
            ctx["cfile_id"], make_credentialing_coordinator_headers(ctx["coord_id"])
        )
    )
    assert cfile["overall_status"] == "CLEARED"


def test_onboard_before_credentialing_cleared_rejected(api):
    """PRD §3.8: "a CredentialingCoordinator onboards a placement (PRE_START →
    ACTIVE) once two conditions hold: the placement's credentialing file
    overall_status is CLEARED, otherwise the request is rejected with
    ERR_CREDENTIALING_NOT_CLEARED".

    Design: Difficulty/cross_entity_state_dependency/onboard_requires_credentialing_cleared
    """
    ctx = setup_placement_pre_start()  # credentialing file NOT_STARTED (no items)
    set_clock(TEST_DEFAULTS["START_DATE"])  # clear the start-date gate first
    resp = api.transition_placement(
        ctx["placement_id"], {"action": "ONBOARD"},
        make_credentialing_coordinator_headers(ctx["coord_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIALING_NOT_CLEARED.value)


def test_onboard_before_cleared_leaves_placement_pre_start(api):
    """PRD §3.8: "the placement's credentialing file overall_status is CLEARED,
    otherwise the request is rejected with ERR_CREDENTIALING_NOT_CLEARED".

    Design: Difficulty/cross_entity_state_dependency/onboard_requires_credentialing_cleared
    """
    ctx = setup_placement_pre_start()
    set_clock(TEST_DEFAULTS["START_DATE"])
    api.transition_placement(
        ctx["placement_id"], {"action": "ONBOARD"},
        make_credentialing_coordinator_headers(ctx["coord_id"]),
    )
    placement = validate_success(
        api.get_placement(ctx["placement_id"], make_account_manager_headers(ctx["am_id"]))
    )
    assert placement["placement_status"] == "PRE_START"


def test_invoice_without_final_comp_rejected(api):
    """PRD §3.8: "it requires final_first_year_comp_cents in the request; if that
    final compensation is absent the request is rejected with
    ERR_FINAL_COMP_REQUIRED."

    Design: Corner/validations/final_comp_required_on_invoice
    """
    ctx = setup_placement_active()
    resp = api.transition_placement(
        ctx["placement_id"], {"action": "INVOICE"},
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FINAL_COMP_REQUIRED.value)
