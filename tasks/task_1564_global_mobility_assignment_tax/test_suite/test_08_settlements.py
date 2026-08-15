"""Year-end tax equalization settlements: PROVISIONAL vs FINAL divergence,
filed-vendor gating, the zero-amount auto-settle boundary, the dispute and
recalculation loop, the settle cascade, uniqueness, and segregation of duties
(PRD §2.8, §3.3, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_engagement_to_under_review,
    api_client,
    create_and_post_record,
    create_calculated_settlement,
    create_draft_assignment,
    create_draft_record,
    create_employee,
    create_engagement,
    create_policy,
    create_program,
    create_settlement_payload,
    get_assignment,
    list_chargebacks,
    make_assignee_headers,
    mark_filed_payload,
    make_finance_headers,
    make_payroll_headers,
    setup_active_assignment,
    setup_calculated_settlement,
    setup_filed_engagement,
    setup_pending_review_settlement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_provisional_withholding_recorded_on_posted_record(api, payroll_headers):
    """PRD §3.3: "Each shadow payroll record applies the PROVISIONAL variant: the
    record's `total_gross_cents` is multiplied by twelve to project an annual gross,
    the annual schedule is applied, and the result is divided by twelve and rounded
    half up to integer cents to yield `hypothetical_tax_cents` — a forward-looking
    withholding estimate."

    Design: Difficulty/dual_variant_calc/hypothetical_tax_provisional_vs_final_divergence
    """
    ctx = setup_active_assignment(totalization=True)
    record = create_and_post_record(
        ctx["assignment"]["id"], tax_year=2026, period_month=9,
        total_gross_cents=900000, per_diem_days=20, housing_receipts_cents=310000)
    # PROVISIONAL: 900000 x 12 = 10800000, taxable 10400000 after the 400000
    # exemption, annual tax 1620000 across all three brackets, /12 = 135000.
    assert record["hypothetical_tax_cents"] == 135000


def test_final_settlement_diverges_from_provisional_withholding(api, payroll_headers):
    """PRD §3.8: "`final_hypo_tax_cents` is the FINAL variant of the hypothetical tax
    — the same tiered annual schedule of §3.3, personal exemption included, applied
    once to the engagement's `filed_total_gross_cents` rather than to any payroll
    figure — so identical payroll data paired with a filed gross that differs from
    twelve times the monthly gross yields a different number than the provisional sum."
    PRD §3.8: "`settlement_amount_cents` is the withheld total minus the final tax: a
    positive amount means the company owes the employee (`direction`
    `EMPLOYEE_CREDIT`), a negative amount means the employee owes the company
    (`EMPLOYEE_DEBIT`), and an exactly zero amount is `ZERO`."

    Design: Difficulty/dual_variant_calc/hypothetical_tax_provisional_vs_final_divergence
    """
    # One POSTED record (withheld 135000); filed gross 1500000 -> FINAL tax
    # 0.10 x (1500000 - 400000) = 110000, which provably differs from 135000.
    ctx = setup_calculated_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    settlement = ctx["settlement"]
    assert ctx["records"][0]["hypothetical_tax_cents"] == 135000
    assert settlement["total_hypo_withheld_cents"] == 135000
    assert settlement["final_hypo_tax_cents"] == 110000
    assert settlement["final_hypo_tax_cents"] != ctx["records"][0]["hypothetical_tax_cents"]
    assert settlement["settlement_amount_cents"] == 25000
    assert settlement["direction"] == "EMPLOYEE_CREDIT"


def test_zero_amount_settlement_created_with_zero_direction(api, payroll_headers):
    """PRD §3.8: "`settlement_amount_cents` is the withheld total minus the final tax:
    a positive amount means the company owes the employee (`direction`
    `EMPLOYEE_CREDIT`), a negative amount means the employee owes the company
    (`EMPLOYEE_DEBIT`), and an exactly zero amount is `ZERO`."

    Design: Difficulty/boundary_precision_check/zero_amount_settlement_auto_settles_without_chargeback
    """
    # Withheld 135000; filed gross 1750000 -> FINAL 135000; amount exactly zero.
    ctx = setup_calculated_settlement(
        filed_total_gross_cents=1750000, filed_home_tax_cents=135000)
    settlement = ctx["settlement"]
    assert settlement["settlement_amount_cents"] == 0
    assert settlement["direction"] == "ZERO"


def test_zero_amount_settlement_auto_settles_without_chargeback(api, finance_headers, admin_headers):
    """PRD §3.8: "Approval belongs to a `FinanceController` who must differ from the
    settlement's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and its effect
    splits on the amount: a zero-amount settlement skips `APPROVED` entirely and
    transitions directly to `SETTLED` with no chargeback entry created, while a nonzero
    settlement moves to `APPROVED` and records `approved_by_user_id`, waiting for the
    explicit settle step."

    Design: Difficulty/boundary_precision_check/zero_amount_settlement_auto_settles_without_chargeback
    """
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1750000, filed_home_tax_cents=135000)
    asg_id = ctx["assignment"]["id"]

    approved = validate_success(
        api.approve_settlement(ctx["settlement"]["id"], finance_headers), 200)
    assert approved["status"] == "SETTLED", (
        "a zero-amount settlement skips APPROVED and settles at approval"
    )

    entries = list_chargebacks(asg_id)
    settlement_entries = [e for e in entries if e["entry_type"] == "SETTLEMENT"]
    assert settlement_entries == [], "no chargeback entry is created for a zero amount"
    assert len(entries) == 1, "only the PERIOD_COST entry from the record post exists"


def test_dispute_records_reason_and_moves_to_disputed(api, payroll_headers):
    """PRD §3.8: "While the settlement is `PENDING_REVIEW`, the assignee — and only
    the assignee, meaning `X-User-ID` must equal the assignment's `employee_id`, else
    `ERR_FORBIDDEN_FOR_ROLE` — may dispute it with an optional `reason`, moving it to
    `DISPUTED` with that reason recorded as `dispute_reason`."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recalculate_cycle
    """
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    owner_headers = make_assignee_headers(ctx["employee"]["id"])

    disputed = validate_success(api.dispute_settlement(
        ctx["settlement"]["id"], {"reason": "Wrong hypothetical rate"}, owner_headers), 200)
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Wrong hypothetical rate"


def test_recalculate_recomputes_identically_and_clears_reason(api, payroll_headers):
    """PRD §3.8: "A `PayrollSpecialist` resolves a dispute by recalculating: the linked
    engagement must still be `FILED` or `CLOSED` (`ERR_VENDOR_NOT_FILED`), all four
    computed fields are recomputed from the current `POSTED` records and the filed
    engagement, the settlement returns `DISPUTED` → `CALCULATED`, and `dispute_reason`
    is cleared — a cyclic revision loop that may repeat."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recalculate_cycle
    """
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    owner_headers = make_assignee_headers(ctx["employee"]["id"])
    validate_success(api.dispute_settlement(
        ctx["settlement"]["id"], {"reason": "Wrong hypothetical rate"}, owner_headers), 200)

    recalculated = validate_success(
        api.recalculate_settlement(ctx["settlement"]["id"], payroll_headers), 200)
    assert recalculated["status"] == "CALCULATED"
    # Inputs unchanged: the loop re-derives the same figures.
    assert recalculated["total_hypo_withheld_cents"] == 135000
    assert recalculated["final_hypo_tax_cents"] == 110000
    assert recalculated["settlement_amount_cents"] == 25000
    assert recalculated["dispute_reason"] is None


def test_settlement_blocked_while_engagement_under_review(api, payroll_headers):
    """PRD §3.8: "An eligible filed engagement must exist for the same assignment and
    year — eligibility means status `FILED` or `CLOSED` with a recorded
    `filed_total_gross_cents`; when several qualify, the selection is deterministic: a
    `FILED` engagement ranks ahead of a `CLOSED` one, then the most recently updated,
    then the most recently created."
    PRD §3.8: "An empty eligible set fails with `ERR_VENDOR_NOT_FILED`."

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_filed_vendor_engagement
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)
    # Engagement driven only to UNDER_REVIEW — never filed.
    engagement = create_engagement(asg_id, tax_year=2026)
    advance_engagement_to_under_review(engagement["id"])

    res = api.create_settlement(
        create_settlement_payload(asg_id, tax_year=2026), payroll_headers)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_FILED)


def test_settlement_created_once_engagement_filed(api, payroll_headers):
    """PRD §3.4: "Marking the return filed moves `ACCEPTED` → `FILED` and records two
    figures from the filed return, `filed_total_gross_cents` and
    `filed_home_tax_cents`; the filing is what unlocks settlement creation for that
    assignment and tax year (§3.8)."

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_filed_vendor_engagement
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)
    engagement = create_engagement(asg_id, tax_year=2026)
    advance_engagement_to_under_review(engagement["id"])
    validate_success(api.accept_engagement(engagement["id"], TEST_USERS["vendor_coordinator_headers"]), 200)
    validate_success(api.mark_filed(
        engagement["id"], mark_filed_payload(1500000, 130000),
        TEST_USERS["vendor_coordinator_headers"]), 200)

    settlement = validate_success(api.create_settlement(
        create_settlement_payload(asg_id, tax_year=2026), payroll_headers), 201)
    assert settlement["status"] == "CALCULATED"
    assert settlement["vendor_engagement_id"] == engagement["id"]


def test_state_gate_beats_vendor_gate_on_settlement_create(api, payroll_headers):
    """PRD §2.10: "Every request is evaluated against a fixed validation pipeline, and
    the earliest failing check determines the error returned:"
    PRD §2.10: "5. **State eligibility.** The target must be in a from-state of the
    invoked transition, and terminal states accept no further transitions; state-gated
    creations require their parent state — a shadow payroll record requires an `ACTIVE`
    assignment, a settlement requires an assignment that is `ACTIVE`,
    `REPATRIATION_PENDING`, or `REPATRIATED`, and an extension request requires an
    `ACTIVE` assignment — else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_settlement_create
    """
    # DRAFT assignment and no vendor engagement at all: both the state gate and
    # the filed-vendor gate fail; the state gate is checked first.
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"],
                                         totalization_applies=True)

    res = api.create_settlement(
        create_settlement_payload(assignment["id"], tax_year=2026), payroll_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_vendor_gate_isolated_on_active_assignment(api, payroll_headers):
    """PRD §3.8: "An empty eligible set fails with `ERR_VENDOR_NOT_FILED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_settlement_create
    """
    # ACTIVE assignment with no engagement: only the filed-vendor gate can fail.
    ctx = setup_active_assignment(totalization=True)
    res = api.create_settlement(
        create_settlement_payload(ctx["assignment"]["id"], tax_year=2026), payroll_headers)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_FILED)


def test_settle_creates_settlement_chargeback_entry(api, finance_headers, admin_headers):
    """PRD §3.8: "Settling moves the settlement to `SETTLED` and fires the cascade: a
    chargeback entry of `entry_type` `SETTLEMENT` is created in `ACCRUED` with
    `amount_cents` equal to the signed `settlement_amount_cents` — an `EMPLOYEE_DEBIT`
    therefore yields a negative entry — with `source_settlement_id` pointing at the
    settlement and `business_unit` copied from the assignment; the assignment's
    `ytd_chargeback_cents` increases by the settlement amount; and the overrun posture
    check re-runs."

    Design: Difficulty/transitive_cascade/settlement_settle_cascade_to_chargeback
    """
    # Four POSTED records (withheld 4 x 135000 = 540000); filed gross 3600000 ->
    # FINAL 320000; amount +220000 EMPLOYEE_CREDIT.
    ctx = setup_calculated_settlement(
        filed_total_gross_cents=3600000, filed_home_tax_cents=320000,
        num_posted_records=4)
    asg_id = ctx["assignment"]["id"]
    settlement = ctx["settlement"]
    assert settlement["settlement_amount_cents"] == 220000
    validate_success(api.submit_settlement(settlement["id"], PAYROLL), 200)
    validate_success(api.approve_settlement(settlement["id"], finance_headers), 200)

    settled = validate_success(api.settle_settlement(settlement["id"], finance_headers), 200)
    assert settled["status"] == "SETTLED"

    entries = list_chargebacks(asg_id, entry_type="SETTLEMENT")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "ACCRUED"
    assert entry["amount_cents"] == 220000
    assert entry["source_settlement_id"] == settlement["id"]
    assert entry["business_unit"] == "BU-TOKYO"


def test_settle_updates_ytd_and_leaves_posture_normal_without_projection(api, finance_headers, admin_headers):
    """PRD §3.8: "Settling moves the settlement to `SETTLED` and fires the cascade: a
    chargeback entry of `entry_type` `SETTLEMENT` is created in `ACCRUED` with
    `amount_cents` equal to the signed `settlement_amount_cents` — an `EMPLOYEE_DEBIT`
    therefore yields a negative entry — with `source_settlement_id` pointing at the
    settlement and `business_unit` copied from the assignment; the assignment's
    `ytd_chargeback_cents` increases by the settlement amount; and the overrun posture
    check re-runs."
    PRD §3.6: "Let the reference be the assignment's `CURRENT` cost projection; if none
    exists, the posture stays `NORMAL`."

    Design: Difficulty/transitive_cascade/settlement_settle_cascade_to_chargeback
    """
    ctx = setup_calculated_settlement(
        filed_total_gross_cents=3600000, filed_home_tax_cents=320000,
        num_posted_records=4)
    asg_id = ctx["assignment"]["id"]
    # Four period chargebacks of 1072500 each.
    assert get_assignment(asg_id)["ytd_chargeback_cents"] == 4290000

    settlement = ctx["settlement"]
    validate_success(api.submit_settlement(settlement["id"], PAYROLL), 200)
    validate_success(api.approve_settlement(settlement["id"], finance_headers), 200)
    validate_success(api.settle_settlement(settlement["id"], finance_headers), 200)

    assignment = get_assignment(asg_id)
    assert assignment["ytd_chargeback_cents"] == 4510000
    assert assignment["cost_posture"] == "NORMAL", (
        "no CURRENT projection exists, so the posture check is inert"
    )


def test_duplicate_open_settlement_rejected(api):
    """PRD §3.8: "At most one settlement per assignment and tax year may be open —
    `CALCULATED`, `PENDING_REVIEW`, `APPROVED`, and `DISPUTED` all count as open, while
    `SETTLED` frees the slot — else `ERR_DUPLICATE_SETTLEMENT`."

    Design: Corner/validations/duplicate_open_settlement_rejected
    """
    ctx = setup_calculated_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    res = api.create_settlement(
        create_settlement_payload(ctx["assignment"]["id"], tax_year=2026),
        make_payroll_headers("ps-2"))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SETTLEMENT)


def test_sod_settlement_creator_cannot_approve_own_settlement(api):
    """PRD §2.8: "The controller who approves a settlement must differ from the
    settlement's `created_by_user_id`."
    PRD §2.8: "Any attempt to perform both sides of a controlled step with the same
    `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/validations/sod_settlement_creator_cannot_approve_own_settlement
    """
    # Settlement created and submitted under payroll user id ps-1.
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    settlement = ctx["settlement"]

    # The same user id holding the FinanceController role is still the creator.
    res = api.approve_settlement(settlement["id"], make_finance_headers("ps-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(
        api.approve_settlement(settlement["id"], make_finance_headers("fc-1")), 200)
    assert approved["status"] == "APPROVED", "amount 25000 is nonzero, so it rests in APPROVED"


def test_assignee_cannot_dispute_other_employees_settlement(api):
    """PRD §2.1: "When `X-User-Role` is `Assignee`, `X-User-ID` is the `id` of the
    acting Employee; ownership checks on any resource that references an Employee — in
    practice the settlement dispute path — compare the target assignment's
    `employee_id` to `X-User-ID`, and a mismatch is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/validations/assignee_cannot_dispute_other_employees_settlement
    """
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    other_employee = create_employee(
        employee_ref="E1002", full_name="Mallory Other", family_size=1,
        annual_base_salary_cents=5000000)
    settlement = ctx["settlement"]

    res = api.dispute_settlement(
        settlement["id"], {"reason": "not mine"},
        make_assignee_headers(other_employee["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    disputed = validate_success(api.dispute_settlement(
        settlement["id"], {"reason": "rate looks wrong"},
        make_assignee_headers(ctx["employee"]["id"])), 200)
    assert disputed["status"] == "DISPUTED"


def test_settlement_reconciliation_excludes_draft_and_voided_records(api, payroll_headers):
    """PRD §3.8: "`total_hypo_withheld_cents` is the sum of `hypothetical_tax_cents`
    over the assignment's `POSTED` shadow payroll records for the settlement's
    `tax_year`; `DRAFT` and `VOIDED` records never contribute."

    Design: Corner/calculations/settlement_reconciliation_excludes_draft_and_voided_records
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)
    # October stays DRAFT; November is POSTED then VOIDED before any settlement
    # exists. Neither may contribute.
    create_draft_record(asg_id, tax_year=2026, period_month=10,
                        total_gross_cents=900000, per_diem_days=20,
                        housing_receipts_cents=310000)
    november = create_and_post_record(asg_id, tax_year=2026, period_month=11,
                                      total_gross_cents=900000, per_diem_days=20,
                                      housing_receipts_cents=310000)
    validate_success(api.void_record(november["id"], payroll_headers), 200)

    setup_filed_engagement(asg_id, tax_year=2026,
                           filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    settlement = create_calculated_settlement(asg_id, tax_year=2026)
    assert settlement["total_hypo_withheld_cents"] == 135000, (
        "only the POSTED September record contributes"
    )
    assert settlement["settlement_amount_cents"] == 25000
