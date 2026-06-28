"""Financing schedule, ledger, refund arithmetic, OCC restructure, and withdraw conservation.

Covers difficulty queue (A): dual_variant_calc (financing schedule variant),
combinatorial_formula (guarantee refund mode-b), compensating_invariant (withdraw ledger),
and corner queue (B): financing remainder, ledger void exclusion, OCC restructure,
list installments filtered, paid_in_full default plan, computed financing fields.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    setup_financed_active_enrollment, setup_eligible_failed_enrollment,
    create_published_program, create_plan, create_learner, create_enrollment,
    create_program, activate, get_enrollment, list_installments, pay_installment,
    decide_claim, file_claim,
    make_learner_headers,
)


# ==========================================================================
# dual_variant_calc / financing_schedule_paid_in_full_vs_financed_variant
# ==========================================================================
def test_paid_in_full_emits_single_installment(api):
    """A paid-in-full enrollment materializes one installment equal to the full price.

    PRD §3.2: "When `financed` is false, the schedule is instead a single installment,
    `sequence_no` 1, whose `amount_cents` equals the full `total_price_cents` with no
    remainder split."

    Design: Difficulty/dual_variant_calc/financing_schedule_paid_in_full_vs_financed_variant
    """
    prog = create_published_program("RE-SALES", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="full@x.com", full_name="Full Pay")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    data, meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"])))
    assert meta["total_count"] == 1, f"paid-in-full expects 1 installment, got {meta['total_count']}"
    assert data[0]["amount_cents"] == 120000, f"expected 120000, got {data[0]['amount_cents']}"


def test_financed_emits_down_payment_plus_monthly_installments(api):
    """A financed enrollment materializes a down payment plus financing_months equal installments.

    PRD §3.2: "The schedule then has one more installment than there are financing months:
    the first installment, `sequence_no` 1, carries the down-payment amount; installments
    `sequence_no` 2 through the number of financing months each carry the base amount; and
    the final installment, whose `sequence_no` is the number of financing months plus one,
    carries the base amount plus the leftover remainder."

    Design: Difficulty/dual_variant_calc/financing_schedule_paid_in_full_vs_financed_variant
    """
    prog = create_published_program("RE-SALES2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="fin@x.com", full_name="Financed")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    data, meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"])))
    assert meta["total_count"] == 7, f"financed expects 7 installments, got {meta['total_count']}"
    by_seq = {i["sequence_no"]: i for i in data}
    # down = round(120000*0.20)=24000; remainder=96000; base=16000; last=16000+0
    assert by_seq[1]["amount_cents"] == 24000, f"down payment expected 24000, got {by_seq[1]['amount_cents']}"
    for seq in range(2, 8):
        assert by_seq[seq]["amount_cents"] == 16000, \
            f"seq {seq} expected 16000, got {by_seq[seq]['amount_cents']}"


# ==========================================================================
# Corner / calculations / financing_remainder_to_last_installment
# ==========================================================================
def test_financing_remainder_folded_into_last_installment(api):
    """Plan 100000 / down 0.30 / 6 months -> down 30000, five of 11666, last 11670, sum 100000.

    PRD §3.2: "The down payment is the price multiplied by the down-payment fraction,
    rounded half up to whole cents. The financed remainder is the price minus that down
    payment. The base monthly amount is the financed remainder divided by the number of
    financing months, taking the integer floor in cents. The leftover remainder is the
    financed remainder minus the base amount multiplied by the number of months."
    PRD §3.2: "Folding the remainder into the last installment guarantees that the sum of
    all installment amounts equals `total_price_cents` exactly."

    Design: Corner/calculations/financing_remainder_to_last_installment
    """
    prog = create_program("REM", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PRO", total_price_cents=100000, down_payment_pct=0.30,
                       financing_months=6, included_mock_credits=5)
    learner = create_learner(email="rem@x.com", full_name="Rem")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    data, meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"])))
    assert meta["total_count"] == 7
    by_seq = {i["sequence_no"]: i for i in data}
    assert by_seq[1]["amount_cents"] == 30000
    for seq in range(2, 7):
        assert by_seq[seq]["amount_cents"] == 11666, f"seq {seq}: {by_seq[seq]['amount_cents']}"
    assert by_seq[7]["amount_cents"] == 11670
    assert sum(i["amount_cents"] for i in data) == 100000


# ==========================================================================
# combinatorial_formula / guarantee_refund_round_per_installment_then_sum_mode_b
# ==========================================================================
def test_money_back_refund_rounds_per_installment_then_sums(api):
    """MONEY_BACK refund rounds each paid installment first, then sums (26670, not 26669).

    PRD §3.5: "The **refund** is the sum of per-installment refunds taken over the
    enrollment's installments currently in `PAID` status, processed in `sequence_no`
    ascending order: for each paid installment, multiply its `amount_cents` by the plan's
    `guarantee_refund_pct` and round that product half up to whole cents, then sum those
    per-installment amounts."
    PRD §3.5: "The rounding order is pinned — each installment is rounded first and the
    rounded figures are summed, never summed-then-rounded — because when individual
    products land on a half-cent the two orders can differ and the per-installment order is
    the observable one."

    Design: Difficulty/combinatorial_formula/guarantee_refund_round_per_installment_then_sum_mode_b
    """
    # PRO plan total 100002, down 0.30, 6 months -> schedule: 30001, 11666 x5, last 11671.
    # Pay seq1(30001), seq2(11666), seq7(11671). refund = round(30001*.5)+round(11666*.5)+round(11671*.5)
    #   = 15001 + 5833 + 5836 = wait: 11671*.5=5835.5 -> 5836; 11666*.5=5833.0; 30001*.5=15000.5 -> 15001
    #   total = 15001 + 5833 + 5836 = 26670
    prog = create_published_program("NCLEX-RN", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=75)
    plan = create_plan(tier="PRO", total_price_cents=100002, down_payment_pct=0.30,
                       financing_months=6, included_mock_credits=5,
                       pass_guarantee=True, guarantee_refund_pct=0.50)
    learner = create_learner(email="mb@x.com", full_name="Money Back")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    by_seq = {i["sequence_no"]: i for i in insts}
    # pay down payment (seq1) then activate
    pay_installment(enr["id"], by_seq[1]["id"], learner["id"])
    activate(enr["id"], learner["id"])
    pay_installment(enr["id"], by_seq[2]["id"], learner["id"])
    pay_installment(enr["id"], by_seq[7]["id"], learner["id"])
    # drive to eligible FAILED
    from test_helpers import accumulate_eligibility, certify
    accumulate_eligibility(enr["id"], learner["id"])
    certify(enr["id"], "FAIL")
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")

    decided = validate_success(api.decide_pass_guarantee_claim(claim["id"], {"decision": "APPROVE"},
                                                               __import__("test_helpers").TEST_USERS["exam_proctor_headers"]))
    assert decided["status"] == "APPROVED"
    assert decided["refund_amount_cents"] == 26670, \
        f"expected refund 26670 (per-installment rounding), got {decided['refund_amount_cents']}"
    # The summed-then-rounded order would yield 26669 — confirm the per-installment order is observed.
    assert decided["refund_amount_cents"] != 26669
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "REFUNDED"


def test_money_back_refund_zero_when_no_installments_paid(api):
    """A MONEY_BACK refund over an enrollment with no PAID installments is zero.

    PRD §3.5: "The **refund** is the sum of per-installment refunds taken over the
    enrollment's installments currently in `PAID` status, processed in `sequence_no`
    ascending order: for each paid installment, multiply its `amount_cents` by the plan's
    `guarantee_refund_pct` and round that product half up to whole cents, then sum those
    per-installment amounts."

    Design: Difficulty/combinatorial_formula/guarantee_refund_round_per_installment_then_sum_mode_b
    """
    # Paid-in-full eligible FAILED enrollment but the single installment is never paid:
    # no PAID installments -> the per-installment sum is over an empty set -> refund 0.
    ctx = setup_eligible_failed_enrollment(
        license_code="MB-ZERO",
        plan_overrides={"tier": "PRO", "total_price_cents": 50000, "down_payment_pct": 0.00,
                        "financing_months": 1, "included_mock_credits": 5,
                        "pass_guarantee": True, "guarantee_refund_pct": 0.50},
        financed=False,
        learner_email="mbz@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    claim = file_claim(enr["id"], learner["id"], "MONEY_BACK")
    decided = validate_success(api.decide_pass_guarantee_claim(
        claim["id"], {"decision": "APPROVE"},
        __import__("test_helpers").TEST_USERS["exam_proctor_headers"]))
    assert decided["status"] == "APPROVED"
    assert decided["refund_amount_cents"] == 0, \
        f"no PAID installments -> refund 0, got {decided['refund_amount_cents']}"
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["status"] == "REFUNDED"


# ==========================================================================
# compensating_invariant / withdraw_voids_installments_conserves_paid_plus_balance
# ==========================================================================
def test_withdraw_voids_due_installments_conserving_paid(api):
    """Withdrawing an ACTIVE financed enrollment voids DUE installments and conserves the paid sum.

    PRD §3.6: "In both cases the side effects void all `DUE` installments (each to `VOID`)
    and increment the enrollment's `version`."
    PRD §3.2: "`financing_paid_cents` becomes the sum of `amount_cents` over installments in
    `PAID` status ... Installments in `VOID` status contribute to neither the paid sum nor
    the balance."

    Design: Difficulty/compensating_invariant/withdraw_voids_installments_conserves_paid_plus_balance
    """
    ctx = setup_financed_active_enrollment(
        license_code="WDR-P",
        plan_overrides={"tier": "PLUS", "total_price_cents": 120000, "down_payment_pct": 0.20,
                        "financing_months": 6, "included_mock_credits": 8},
        learner_email="wdr@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    withdrawn = validate_success(api.withdraw_enrollment(enr["id"], make_learner_headers(learner["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    # PRD §3.2: paid sum = sum of amount_cents over PAID installments (the down payment only).
    assert withdrawn["financing_paid_cents"] == 24000, f"paid expected 24000, got {withdrawn['financing_paid_cents']}"
    # All previously-DUE installments are now VOID; the paid figure equals the sum of PAID installments.
    paid_insts, _ = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "PAID"}))
    paid_sum = sum(i["amount_cents"] for i in paid_insts)
    assert withdrawn["financing_paid_cents"] == paid_sum == 24000
    due_insts, due_meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "DUE"}))
    assert due_meta["total_count"] == 0, "all previously-DUE installments must be VOID after withdraw"


def test_withdraw_active_paid_in_full_terminal(api):
    """An ACTIVE paid-in-full enrollment can be withdrawn to the terminal WITHDRAWN status.

    PRD §3.6: "A learner may **withdraw** an enrollment that is in `DRAFT` or in `ACTIVE`,
    moving it to the terminal `WITHDRAWN` status."

    Design: Difficulty/compensating_invariant/withdraw_voids_installments_conserves_paid_plus_balance
    """
    from test_helpers import setup_active_enrollment
    ctx = setup_active_enrollment(license_code="WDR-FULL", learner_email="wdrfull@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    withdrawn = validate_success(api.withdraw_enrollment(enr["id"], make_learner_headers(learner["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    # PRD §3.6: withdraw voids all DUE installments. Paid-in-full enrollment's single
    # unpaid installment is voided, leaving no DUE installment.
    due_insts, due_meta = validate_paginated(
        api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "DUE"}))
    assert due_meta["total_count"] == 0, "the single unpaid installment must be VOID after withdraw"


# ==========================================================================
# Corner / calculations / financing_ledger_excludes_void_installments
# ==========================================================================
def test_financing_ledger_excludes_void_after_restructure(api):
    """After restructure, only the PAID down payment counts; voided DUE installments excluded.

    PRD §3.2: "`financing_paid_cents` becomes the sum of `amount_cents` over installments in
    `PAID` status, and `financing_balance_cents` becomes `financing_total_due_cents` minus
    `financing_paid_cents`, floored at zero. Installments in `VOID` status contribute to
    neither the paid sum nor the balance."
    PRD §3.2: "A successful restructure voids the prior `DUE` installments (each moves to
    `VOID`), regenerates the schedule with the same waterfall arithmetic as above but using
    the new month count, and increments the enrollment's `version`."

    Design: Corner/calculations/financing_ledger_excludes_void_installments
    """
    prog = create_program("LDG", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="ldg@x.com", full_name="Ldg")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], insts[0]["id"], learner["id"])
    enr = get_enrollment(enr["id"], learner["id"])
    restructured = validate_success(api.restructure_financing(
        enr["id"],
        {"new_financing_months": 3, "expected_enrollment_version": enr["version"]},
        make_learner_headers(learner["id"]),
    ))
    assert restructured["financing_paid_cents"] == 24000, \
        f"paid down payment retained, expected 24000, got {restructured['financing_paid_cents']}"
    assert restructured["financing_balance_cents"] == 96000
    assert restructured["financing_total_due_cents"] == 120000


# ==========================================================================
# Corner / cross_cutting / occ_restructure_financing_stale_version_rejected
# ==========================================================================
def test_restructure_with_stale_version_rejected(api):
    """A second restructure reusing the already-consumed version is rejected with 412.

    PRD §2.9: "If that value does not match the enrollment's current `version` at the
    moment the server processes the request, the restructure is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_restructure_financing_stale_version_rejected
    """
    prog = create_program("OCC", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="occ@x.com", full_name="Occ")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    lh = make_learner_headers(learner["id"])
    observed_version = enr["version"]
    # first restructure succeeds, bumping the version
    get_success_data(api.restructure_financing(
        enr["id"], {"new_financing_months": 4, "expected_enrollment_version": observed_version}, lh))
    # second restructure reusing the stale version is rejected
    resp = api.restructure_financing(
        enr["id"], {"new_financing_months": 3, "expected_enrollment_version": observed_version}, lh)
    validate_error(resp, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value)


# ==========================================================================
# Corner / cross_cutting / occ_restructure_financing_correct_version_succeeds_and_bumps
# ==========================================================================
def test_restructure_with_current_version_succeeds_and_bumps(api):
    """Restructure with the current version rebuilds the schedule and increments version.

    PRD §3.2: "A successful restructure voids the prior `DUE` installments (each moves to
    `VOID`), regenerates the schedule with the same waterfall arithmetic as above but using
    the new month count, and increments the enrollment's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_restructure_financing_correct_version_succeeds_and_bumps
    """
    prog = create_program("OCC2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="occ2@x.com", full_name="Occ2")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    lh = make_learner_headers(learner["id"])
    assert enr["version"] == 1
    updated = validate_success(api.restructure_financing(
        enr["id"], {"new_financing_months": 3, "expected_enrollment_version": enr["version"]}, lh))
    assert updated["version"] == 2, f"version expected 2 after restructure, got {updated['version']}"
    # new schedule: down 24000 then 3 of 32000
    data, meta = validate_paginated(api.list_installments(enr["id"], lh, params={"status": "DUE"}))
    by_seq = {i["sequence_no"]: i for i in data}
    assert by_seq[1]["amount_cents"] == 24000
    assert by_seq[2]["amount_cents"] == 32000 and by_seq[3]["amount_cents"] == 32000 and by_seq[4]["amount_cents"] == 32000


# ==========================================================================
# Corner / endpoints / list_installments_filtered_by_status
# ==========================================================================
def test_list_installments_filtered_by_status_paid(api):
    """Filtering installments by status=PAID returns only the paid down payment.

    PRD §3.2: "Installments for an enrollment are always listed in `sequence_no` ascending
    order and may be filtered by `status`."

    Design: Corner/endpoints/list_installments_filtered_by_status
    """
    prog = create_program("LIF", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="PLUS", total_price_cents=120000, down_payment_pct=0.20,
                       financing_months=6, included_mock_credits=8)
    learner = create_learner(email="lif@x.com", full_name="Lif")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    insts = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], insts[0]["id"], learner["id"])
    data, meta = validate_paginated(api.list_installments(enr["id"], make_learner_headers(learner["id"]), params={"status": "PAID"}))
    assert meta["total_count"] == 1, f"expected 1 PAID installment, got {meta['total_count']}"
    assert data[0]["status"] == "PAID"
    assert data[0]["amount_cents"] == 24000


# ==========================================================================
# Corner / entities / enrollment_computed_financing_fields_ignore_client_input
# ==========================================================================
def test_enrollment_financing_total_computed_from_plan(api):
    """financing_total_due_cents is computed from the plan price; readiness starts at 0.

    PRD §3.2: "At creation the system records `financing_total_due_cents` equal to the
    plan's `total_price_cents` and materializes the installment schedule."
    PRD §3.2: "A new enrollment begins in `DRAFT` status with `exam_outcome` of `PENDING`."

    Design: Corner/entities/enrollment_computed_financing_fields_ignore_client_input
    """
    prog = create_program("CF", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    learner = create_learner(email="cf@x.com", full_name="CF")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    assert enr["financing_total_due_cents"] == 30000
    assert enr["readiness_score"] == 0
    assert enr["completed_mock_count"] == 0
