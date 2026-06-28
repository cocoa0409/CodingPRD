"""Tuition tiering and the two derived balances (estimated vs settled).

Difficulty queue: dual_variant_calc, combinatorial_formula, and the aid-approve
depth-2 cascade. Corner queue: list_tuition tier cases and the same-response
immediate consistency claim.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_guardian_headers, make_director_headers,
    setup_enrolling_session, setup_enrolling_session_with_staffed_cabin,
    setup_submitted_application, setup_deposit_paid_application,
    request_aid, approve_aid, api_client,
)


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
def test_estimated_vs_settled_balance_diverge_by_pending_aid():
    """PRD §3.5: "Its aid set is narrower: it counts only awards in `APPROVED` status
    — a still-requested award contributes nothing until it is actually approved."
    PRD §3.5: "Because the estimated balance counts pending requests and the settled
    balance does not, the two diverge precisely when an application has a
    requested-but-unapproved award."

    Design: Difficulty/dual_variant_calc/estimated_vs_settled_balance_with_pending_aid
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="dv1@x.com")
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    # A REQUESTED (not approved) aid award of 100000.
    request_aid(g_id, app_id, 100_000, kind="NEED_GRANT")

    data = validate_success(api_client.get_application(app_id, make_guardian_headers(g_id)))
    assert data["list_tuition_cents"] == 370_000, data["list_tuition_cents"]
    # estimated counts the pending request (370000 - 100000 - 25000 deposit payment)
    assert data["estimated_balance_cents"] == 245_000, data["estimated_balance_cents"]
    # settled ignores the pending request (370000 - 25000 deposit payment)
    assert data["settled_balance_cents"] == 345_000, data["settled_balance_cents"]
    assert data["settled_balance_cents"] - data["estimated_balance_cents"] == 100_000


def test_estimated_counts_pending_aid_settled_does_not_before_deposit():
    """PRD §3.5: "It optimistically assumes every still-pending aid request will
    ultimately be approved: its aid set therefore includes awards in either
    `REQUESTED` or `APPROVED` status (excluding denied and revoked awards), pooled
    into a single sum."
    PRD §3.5: "Its aid set is narrower: it counts only awards in `APPROVED` status —
    a still-requested award contributes nothing until it is actually approved."

    Design: Difficulty/dual_variant_calc/estimated_vs_settled_balance_with_pending_aid
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="dv2@x.com")  # OFFERED, list 370000, no payments
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    request_aid(g_id, app_id, 80_000, kind="MERIT_SCHOLARSHIP")  # REQUESTED only

    data = validate_success(api_client.get_application(app_id, make_guardian_headers(g_id)))
    # estimated subtracts the pending 80000 (370000 - 80000)
    assert data["estimated_balance_cents"] == 290_000, data["estimated_balance_cents"]
    # settled ignores it entirely (370000)
    assert data["settled_balance_cents"] == 370_000, data["settled_balance_cents"]


def test_cit_weight_toggle_changes_cabin_staff_weight():
    """PRD §3.2: "Summing only over `ACTIVE` cabin assignments to this cabin whose
    staff member is background-cleared, a `COUNSELOR` contributes 10, and a `CIT`
    contributes 5 when the camp's `cit_counts_as_half` flag is true or 10 when that
    flag is false."
    PRD §3.1: "when the `cit_counts_as_half` flag changes, every cabin's effective
    staff weight and staffable flag are recomputed across the whole camp, and the
    camp's `version` increments."

    Design: Difficulty/dual_variant_calc/cit_weight_dual_interpretation_changes_staff_weight
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"cit_counts_as_half": True, "counselor_camper_ratio": 6,
                        "deposit_cents": 25_000},
        session_overrides={"capacity": 20},
        cabin_overrides={"bunk_capacity": 8},
        num_counselors=1,
    )
    camp = env["camp"]
    cabin = env["cabin"]
    director = make_director_headers()
    # add a cleared CIT to the same cabin
    cit = get_success_data(api_client.create_staff(
        camp["id"], {"full_name": "CIT B", "role_kind": "CIT", "is_background_cleared": True}, director))
    get_success_data(api_client.create_cabin_assignment(
        {"cabin_id": cabin["id"], "staff_member_id": cit["id"]}, director))

    before = validate_success(api_client.get_cabin(cabin["id"], director))
    assert before["staff_weight_x10"] == 15, before["staff_weight_x10"]  # 10 (counselor) + 5 (CIT half)

    # toggle cit_counts_as_half -> false
    get_success_data(api_client.update_camp(
        camp["id"], {"cit_counts_as_half": False, "expected_camp_version": camp["version"]}, director))

    after = validate_success(api_client.get_cabin(cabin["id"], director))
    assert after["staff_weight_x10"] == 20, after["staff_weight_x10"]  # 10 (counselor) + 10 (CIT full)


def test_cit_contributes_half_weight_when_flag_true():
    """PRD §3.2: "a `COUNSELOR` contributes 10, and a `CIT` contributes 5 when the
    camp's `cit_counts_as_half` flag is true or 10 when that flag is false. The sum
    is the cabin's `staff_weight_x10`."

    Design: Difficulty/dual_variant_calc/cit_weight_dual_interpretation_changes_staff_weight
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"cit_counts_as_half": True, "counselor_camper_ratio": 6,
                        "deposit_cents": 25_000},
        session_overrides={"capacity": 20},
        cabin_overrides={"bunk_capacity": 8},
        num_counselors=0,  # no counselors; only a single CIT below
    )
    director = make_director_headers()
    cit = get_success_data(api_client.create_staff(
        env["camp"]["id"], {"full_name": "CIT Only", "role_kind": "CIT",
                            "is_background_cleared": True}, director))
    get_success_data(api_client.create_cabin_assignment(
        {"cabin_id": env["cabin"]["id"], "staff_member_id": cit["id"]}, director))
    cabin = validate_success(api_client.get_cabin(env["cabin"]["id"], director))
    assert cabin["staff_weight_x10"] == 5, cabin["staff_weight_x10"]  # CIT counts as half (5)


# ===========================================================================
# Difficulty / combinatorial_formula
# ===========================================================================
def test_list_tuition_early_tier_plus_meds_and_epipen_surcharge():
    """PRD §3.5: "if the application is submitted at least 60 days before the start,
    the tier amount is the base tuition reduced by an early discount of 30000 cents".
    PRD §3.5: "a medical-support surcharge is added: the system reads the camper's
    latest health form (by creation time) whose status is `SUBMITTED`, `CLEARED`, or
    `FLAGGED`, and adds 1500 cents for each daily scheduled medication on that form
    plus, if that form declares a life-threatening allergy, a further 5000 cents of
    EpiPen support."

    Design: Difficulty/combinatorial_formula/list_tuition_three_input_conditional_tier_plus_med_surcharge
    """
    env = setup_enrolling_session(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        cabin_overrides={"gender_band": "GIRLS"},
    )
    gc = setup_submitted_application(
        env, email="comb1@x.com",
        camper_overrides={"gender": "GIRL"},
        health_form_overrides={"has_life_threatening_allergy": True, "epipen_on_file": True,
                               "daily_medication_count": 2},
    )
    # clock 2026-04-01 vs start 2026-07-01 -> 91 days -> early tier 370000
    # + 2 meds * 1500 + 5000 epipen = 378000
    assert gc["application"]["list_tuition_cents"] == 378_000, gc["application"]["list_tuition_cents"]


def test_list_tuition_early_tier_with_only_medication_surcharge():
    """PRD §3.5: "if the application is submitted at least 60 days before the start,
    the tier amount is the base tuition reduced by an early discount of 30000 cents".
    PRD §3.5: "adds 1500 cents for each daily scheduled medication on that form plus,
    if that form declares a life-threatening allergy, a further 5000 cents of EpiPen
    support."

    Design: Difficulty/combinatorial_formula/list_tuition_three_input_conditional_tier_plus_med_surcharge
    """
    # early tier (91 days), 3 meds, NO allergy -> 370000 + 3*1500 = 374500
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(
        env, email="comb2@x.com",
        health_form_overrides={"daily_medication_count": 3},
    )
    assert gc["application"]["list_tuition_cents"] == 374_500, gc["application"]["list_tuition_cents"]


def test_pay_balance_to_zero_sets_paid_in_full():
    """PRD §3.6: "moves the payment axis to `PAID_IN_FULL` once the settled balance
    reaches zero."
    PRD §3.6: "This creates a `Payment` of kind `BALANCE` in `APPLIED` status,
    recomputes both balances, and moves the payment axis to `PAID_IN_FULL` once the
    settled balance reaches zero."

    Design: Difficulty/combinatorial_formula/paid_in_full_keyed_on_recomputed_settled_balance_eval_order
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    gc = setup_submitted_application(env, email="pif1@x.com", clear_health=True)
    g_id = gc["guardian"]["id"]
    g_headers = make_guardian_headers(g_id)
    app_id = gc["application"]["id"]
    # pay deposit -> DEPOSIT_PAID, assign bunk, enroll -> BALANCE_DUE (345000 owed)
    get_success_data(api_client.pay_deposit(app_id, {"amount_cents": 25_000}, g_headers))
    director = make_director_headers()
    cab = get_success_data(api_client.get_cabin(env["cabin"]["id"], director))
    get_success_data(api_client.assign_bunk(
        env["cabin"]["id"], {"application_id": app_id, "expected_cabin_version": cab["version"]}, director))
    get_success_data(api_client.enroll_application(app_id, director))

    # pay the full remaining balance 345000
    data = validate_success(api_client.pay_balance(app_id, {"amount_cents": 345_000}, g_headers))
    assert data["settled_balance_cents"] == 0, data["settled_balance_cents"]
    assert data["payment_status"] == "PAID_IN_FULL", data["payment_status"]


def test_partial_balance_payment_keeps_balance_due_then_paid_in_full():
    """PRD §3.6: "This creates a `Payment` of kind `BALANCE` in `APPLIED` status,
    recomputes both balances, and moves the payment axis to `PAID_IN_FULL` once the
    settled balance reaches zero."

    Design: Difficulty/combinatorial_formula/paid_in_full_keyed_on_recomputed_settled_balance_eval_order
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    gc = setup_submitted_application(env, email="pif2@x.com", clear_health=True)
    g_id = gc["guardian"]["id"]
    g_headers = make_guardian_headers(g_id)
    director = make_director_headers()
    app_id = gc["application"]["id"]
    get_success_data(api_client.pay_deposit(app_id, {"amount_cents": 25_000}, g_headers))
    cab = get_success_data(api_client.get_cabin(env["cabin"]["id"], director))
    get_success_data(api_client.assign_bunk(
        env["cabin"]["id"], {"application_id": app_id, "expected_cabin_version": cab["version"]}, director))
    get_success_data(api_client.enroll_application(app_id, director))  # BALANCE_DUE, 345000 owed

    # first partial payment leaves a positive settled balance -> still BALANCE_DUE
    mid = validate_success(api_client.pay_balance(app_id, {"amount_cents": 145_000}, g_headers))
    assert mid["settled_balance_cents"] == 200_000, mid["settled_balance_cents"]
    assert mid["payment_status"] == "BALANCE_DUE", mid["payment_status"]
    # final payment drives settled balance to 0 -> PAID_IN_FULL
    done = validate_success(api_client.pay_balance(app_id, {"amount_cents": 200_000}, g_headers))
    assert done["settled_balance_cents"] == 0, done["settled_balance_cents"]
    assert done["payment_status"] == "PAID_IN_FULL", done["payment_status"]


# ===========================================================================
# Difficulty / transitive_cascade (aid-approve depth-2)
# ===========================================================================
def test_aid_approve_cascades_aid_cents_then_both_balances():
    """PRD §3.7: "On approval the application's `aid_cents` is recomputed and both
    balances are recomputed, and the application's `version` increments."
    PRD §3.5: "it counts only awards in `APPROVED` status — a still-requested award
    contributes nothing until it is actually approved."

    Design: Difficulty/transitive_cascade/aid_approve_cascades_aidcents_then_balances_depth2
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="casc1@x.com")
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    aid = request_aid(g_id, app_id, 100_000, kind="NEED_GRANT")

    director = make_director_headers()
    app_version = get_success_data(
        api_client.get_application(app_id, make_guardian_headers(g_id)))["version"]
    award = validate_success(api_client.approve_aid(
        aid["id"], {"expected_application_version": app_version}, director))
    assert award["status"] == "APPROVED", award["status"]

    data = validate_success(api_client.get_application(app_id, make_guardian_headers(g_id)))
    assert data["aid_cents"] == 100_000, data["aid_cents"]
    # 370000 - 100000 aid - 25000 deposit payment = 245000
    assert data["settled_balance_cents"] == 245_000, data["settled_balance_cents"]
    assert data["estimated_balance_cents"] == 245_000, data["estimated_balance_cents"]


def test_aid_approve_cascade_via_helper():
    """PRD §3.7: "On approval the application's `aid_cents` is recomputed and both
    balances are recomputed, and the application's `version` increments."
    PRD §3.5: "The estimated balance is the list tuition minus the optimistic aid
    total minus the applied-payment total, floored at zero in a single step so it can
    never go negative."

    Design: Difficulty/transitive_cascade/aid_approve_cascades_aidcents_then_balances_depth2
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="casc2@x.com")
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    aid = request_aid(g_id, app_id, 50_000, kind="MERIT_SCHOLARSHIP")
    approve_aid(aid["id"], app_id)

    data = validate_success(api_client.get_application(app_id, make_guardian_headers(g_id)))
    assert data["aid_cents"] == 50_000, data["aid_cents"]
    # 370000 - 50000 aid - 25000 deposit = 295000 (both converge, no pending aid)
    assert data["settled_balance_cents"] == 295_000, data["settled_balance_cents"]
    assert data["estimated_balance_cents"] == 295_000, data["estimated_balance_cents"]


# ===========================================================================
# Corner / calculations — list_tuition tiers
# ===========================================================================
def test_list_tuition_late_tier_adds_surcharge():
    """PRD §3.5: "otherwise — fewer than 14 days before, including any negative figure
    — the tier amount is the base tuition increased by a late surcharge of 25000
    cents."

    Design: Corner/calculations/list_tuition_late_tier_surcharge
    """
    # clock 2026-06-25 vs start 2026-07-01 = 6 days out -> late tier 425000
    env = setup_enrolling_session(camp_overrides={"clock": "2026-06-25T00:00:00Z",
                                                  "deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="lt1@x.com")
    assert gc["application"]["list_tuition_cents"] == 425_000, gc["application"]["list_tuition_cents"]


def test_list_tuition_base_tier_no_surcharge():
    """PRD §3.5: "if it is submitted at least 14 days before the start but fewer than
    60, the tier amount is exactly the base tuition".

    Design: Corner/calculations/list_tuition_mid_tier_base_no_surcharge
    """
    # clock 2026-06-01 vs start 2026-07-01 = 30 days out -> base tier 400000
    env = setup_enrolling_session(
        camp_overrides={"clock": "2026-06-01T00:00:00Z", "deposit_cents": 25_000},
        cabin_overrides={"gender_band": "GIRLS"},
    )
    gc = setup_submitted_application(env, email="mt1@x.com", camper_overrides={"gender": "GIRL"})
    assert gc["application"]["list_tuition_cents"] == 400_000, gc["application"]["list_tuition_cents"]


# ===========================================================================
# Corner / consistency_model — immediate
# ===========================================================================
def test_pay_deposit_response_reflects_settled_balance_immediately():
    """PRD §3.6: "A successful deposit creates a `Payment` of kind `DEPOSIT` in
    `APPLIED` status, sets `deposit_paid_cents` to the camp's deposit amount, moves
    the payment axis to `DEPOSIT_SETTLED`, and recomputes both balances."

    Design: Corner/consistency_model/immediate_consistency_balances_visible_in_same_response
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="im1@x.com")
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    # pay-deposit response itself carries the recomputed fields (no re-read)
    data = validate_success(api_client.pay_deposit(
        gc["application"]["id"], {"amount_cents": 25_000}, g_headers))
    assert data["deposit_paid_cents"] == 25_000, data["deposit_paid_cents"]
    # list 370000 (early tier) - 25000 deposit payment = 345000
    assert data["settled_balance_cents"] == 345_000, data["settled_balance_cents"]
