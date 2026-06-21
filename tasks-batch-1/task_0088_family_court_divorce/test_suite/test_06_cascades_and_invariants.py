"""Multi-hop cascades and conserved-quantity invariants (PRD §2.8, §2.9, §3.5, §3.7).

Translates queue A (Difficulty) rules transitive_cascade and compensating_invariant,
plus the queue B (Corner) derived-disclosure-flag reconciliation instance.
"""
from test_helpers import validate_success, TEST_USERS
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import (
    make_petitioner_headers, make_respondent_headers, make_mediator_headers,
    make_judge_headers,
)

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Rule: transitive_cascade — instance full_agreement_cascade_plan_support_case_depth3
# =========================================================================
def _setup_full_agreement_ready():
    """Contested CA case in MEDIATION (mediator u-med); both disclosures VERIFIED; an
    AGREED parenting plan; a SCHEDULED session started to IN_SESSION. Returns (case,
    plan, session)."""
    ctx = FX.setup_case_in_mediation(pet_gross=800000, res_gross=400000,
                                     verify_respondent=True)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    FX.agree_plan(plan["id"], "u-res", "RESPONDENT")  # AGREED
    session = FX.schedule_session(case["id"], "u-med")
    FX.start_session(session["id"], "u-med")
    return case, plan, session


def test_full_agreement_cascades_plan_to_adopted(api):
    """PRD §3.5: "Concluding in `FULL_AGREEMENT` triggers a three-hop cascade that
    completes within the same request. First, the case's parenting plan advances from
    `AGREED` to `ADOPTED`."

    Design: Difficulty/transitive_cascade/full_agreement_cascade_plan_support_case_depth3
    """
    case, plan, session = _setup_full_agreement_ready()
    concluded = validate_success(api.conclude_mediation_session(
        session["id"], {"outcome": "FULL_AGREEMENT"}, make_mediator_headers("u-med")), 200)
    assert concluded["status"] == "FULL_AGREEMENT"
    adopted = validate_success(api.get_parenting_plan(plan["id"], CLERK), 200)
    assert adopted["status"] == "ADOPTED"


def test_full_agreement_cascades_case_to_awaiting_judgment(api):
    """PRD §3.5: "Third, the case advances from `MEDIATION` to `AWAITING_JUDGMENT` and
    its `version` increments".

    Design: Difficulty/transitive_cascade/full_agreement_cascade_plan_support_case_depth3
    """
    case, plan, session = _setup_full_agreement_ready()
    validate_success(api.conclude_mediation_session(
        session["id"], {"outcome": "FULL_AGREEMENT"}, make_mediator_headers("u-med")), 200)
    fetched = validate_success(api.get_case(case["id"], CLERK), 200)
    assert fetched["status"] == "AWAITING_JUDGMENT"


# =========================================================================
# Rule: transitive_cascade — instance final_judgment_supersede_vacate_depth2
# =========================================================================
def test_final_judgment_supersedes_temporary_and_vacates_support(api):
    """PRD §3.7: "If the final judgment names a `supersedes_order_id`, that prior
    `TEMPORARY` court order advances from `ENTERED` to `SUPERSEDED` (only temporary orders
    may become superseded). When the temporary order is superseded, every support order
    it referenced that is *not* also referenced by the entering final judgment advances
    to `VACATED`".

    Design: Difficulty/transitive_cascade/final_judgment_supersede_vacate_depth2
    """
    ctx = FX.setup_default_awaiting_judgment_with_temp_order()
    case, final_order = ctx["case"], ctx["final_order"]
    version = FX.current_case_version(case["id"])
    validate_success(api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge")), 200)
    temp_order = validate_success(api.get_court_order(ctx["temp_order"]["id"], CLERK), 200)
    temp_child = validate_success(api.get_support_order(ctx["temp_child"]["id"], CLERK), 200)
    assert temp_order["status"] == "SUPERSEDED"
    assert temp_child["status"] == "VACATED"


def test_final_judgment_activates_final_support_and_syncs_ledger(api):
    """PRD §3.7: "On a successful entry, all referenced support orders advance to
    `ACTIVE` and the case's `active_support_total_cents` is recomputed to reflect the
    newly active obligations."

    FINAL CHILD order (100000) becomes ACTIVE; ledger nets to 100000.

    Design: Difficulty/transitive_cascade/final_judgment_supersede_vacate_depth2
    """
    ctx = FX.setup_default_awaiting_judgment_with_temp_order()
    case, final_order = ctx["case"], ctx["final_order"]
    version = FX.current_case_version(case["id"])
    validate_success(api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge")), 200)
    final_child = validate_success(api.get_support_order(ctx["final_child"]["id"], CLERK), 200)
    fetched_case = validate_success(api.get_case(case["id"], CLERK), 200)
    assert final_child["status"] == "ACTIVE"
    assert fetched_case["active_support_total_cents"] == 100000


# =========================================================================
# Rule: compensating_invariant — instance overnights_conserved_at_365_through_revision
# =========================================================================
def test_overnights_revision_preserves_365_sum(api):
    """PRD §3.4: "`petitioner_overnights` plus `respondent_overnights` must total exactly
    365 ... a revision supplies new `petitioner_overnights` and `respondent_overnights`
    (which must still total 365), updates those overnight values".

    Revision 110/255 -> 200/165 keeps the sum at 365.

    Design: Difficulty/compensating_invariant/overnights_conserved_at_365_through_revision
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    FX.get_success_data(api.dispute_parenting_plan(plan["id"], make_respondent_headers("u-res")))
    revised = validate_success(api.revise_parenting_plan(
        plan["id"], F.revise_plan_payload(200, 165), make_respondent_headers("u-res")), 200)
    assert revised["petitioner_overnights"] == 200
    assert revised["respondent_overnights"] == 165
    assert revised["petitioner_overnights"] + revised["respondent_overnights"] == 365


def test_overnights_revision_assigns_new_values(api):
    """PRD §3.4: "a revision supplies new `petitioner_overnights` and
    `respondent_overnights` ... updates those overnight values".

    Design: Difficulty/compensating_invariant/overnights_conserved_at_365_through_revision
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    FX.get_success_data(api.dispute_parenting_plan(plan["id"], make_respondent_headers("u-res")))
    revised = validate_success(api.revise_parenting_plan(
        plan["id"], F.revise_plan_payload(200, 165), make_respondent_headers("u-res")), 200)
    fetched = validate_success(api.get_parenting_plan(plan["id"], CLERK), 200)
    assert fetched["petitioner_overnights"] == 200
    assert fetched["respondent_overnights"] == 165


# =========================================================================
# Rule: compensating_invariant — instance active_support_total_conserved_across_supersede
# =========================================================================
def test_ledger_conserved_after_supersede_nets_to_final(api):
    """PRD §2.8: "The `active_support_total_cents` field is the sum of
    `monthly_amount_cents` across every `SupportOrder` belonging to the case whose
    `status` is `ACTIVE`; it is recomputed on every support-order status change".

    Temporary (150000 active) superseded by final (100000) -> ledger nets to 100000.

    Design: Difficulty/compensating_invariant/active_support_total_conserved_across_supersede
    """
    ctx = FX.setup_default_awaiting_judgment_with_temp_order()
    case, final_order = ctx["case"], ctx["final_order"]
    version = FX.current_case_version(case["id"])
    validate_success(api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge")), 200)
    fetched_case = validate_success(api.get_case(case["id"], CLERK), 200)
    assert fetched_case["active_support_total_cents"] == 100000


def test_ledger_conserved_temporary_vacated_final_active(api):
    """PRD §3.7: "every support order it referenced that is *not* also referenced by the
    entering final judgment advances to `VACATED`, and the case's
    `active_support_total_cents` is recomputed — this is the compensating action that
    keeps the ledger conserved as obligations are replaced."

    Design: Difficulty/compensating_invariant/active_support_total_conserved_across_supersede
    """
    ctx = FX.setup_default_awaiting_judgment_with_temp_order()
    case, final_order = ctx["case"], ctx["final_order"]
    version = FX.current_case_version(case["id"])
    validate_success(api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge")), 200)
    temp_child = validate_success(api.get_support_order(ctx["temp_child"]["id"], CLERK), 200)
    final_child = validate_success(api.get_support_order(ctx["final_child"]["id"], CLERK), 200)
    assert temp_child["status"] == "VACATED"
    assert final_child["status"] == "ACTIVE"


# =========================================================================
# Queue B (Corner) — cross_cutting_complexity_layers (derived field reconciliation)
# =========================================================================
def test_derived_disclosure_flags_reconcile_after_verify(api):
    """PRD §2.8: "A case also exposes two computed boolean flags,
    `petitioner_disclosure_verified` and `respondent_disclosure_verified`, each true
    exactly when the corresponding party's `FinancialDisclosure` has reached `VERIFIED`
    status."

    Verifying only the petitioner disclosure flips its flag true; respondent stays false.

    Design: Corner/cross_cutting_complexity_layers/derived_disclosure_flags_reconcile_after_verify
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    pet_fd = FX.submitted_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                                     gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                                     mandatory_retirement_cents=0, health_insurance_cents=0)
    FX.submitted_disclosure(res["id"], case["id"], "u-res", "RESPONDENT",
                            gross_monthly_income_cents=360000, tax_withholding_cents=60000,
                            mandatory_retirement_cents=0, health_insurance_cents=0)
    FX.verify_disclosure(pet_fd["id"])
    fetched = validate_success(api.get_case(case["id"], CLERK), 200)
    assert fetched["petitioner_disclosure_verified"] is True
    assert fetched["respondent_disclosure_verified"] is False
