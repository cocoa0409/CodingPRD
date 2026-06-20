"""State machines and cross-entity cascades.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade.
Queue B (Corner): state_machines section, endpoints cascade visibility.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_policyholder,
    create_issued_policy,
    create_eligible_provider,
    add_premium_invoice,
    pay_invoice,
    record_trigger_certification,
    author_and_activate_care_plan,
    open_claim,
    approve_claim,
    setup_active_claimable_policy,
    setup_claim_under_review,
    read_benefit_pool,
    read_partnership_disregard,
    read_policy_ledger,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
CA = TEST_USERS["care_assessor_headers"]


# ===========================================================================
# non_linear_state_machine / policy_parallel_coverage_and_premium_axes
# ===========================================================================
def test_premium_axis_moves_to_grace_without_touching_coverage(api):
    """PRD 2.9: "The two axes evolve independently: paying a premium never changes
    coverage, and approving a claim never changes the premium posture."
    PRD 3.10: "When the clock passes an open invoice's `due_date` but not yet its
    `grace_deadline`, the policy's `premium_status` moves from `PAID_CURRENT` to
    `GRACE`."

    After paying period-0, leaving period-1 OPEN, and advancing the clock past
    period-1's due_date but within grace: premium_status GRACE, coverage IN_FORCE.

    Design: Difficulty/non_linear_state_machine/policy_parallel_coverage_and_premium_axes
    """
    ph = create_policyholder(full_name="Para Llel")
    policy = create_issued_policy(ph["id"])
    inv0 = add_premium_invoice(policy["id"], 0)
    pay_invoice(inv0["id"], ph["id"])
    add_premium_invoice(policy["id"], 1, due_date="2026-02-28", grace_deadline="2026-05-04")

    get_success_data(api.advance_clock({"to_iso8601": "2026-03-15T00:00:00Z"}, UW))

    refreshed = validate_success(api.get_policy(policy["id"], UW))
    assert refreshed["coverage_status"] == "IN_FORCE", refreshed
    assert refreshed["premium_status"] == "GRACE", refreshed


def test_issue_advances_only_coverage_axis_premium_stays_pending(api):
    """PRD 3.1: "Issuing the policy advances `coverage_status` from `APPLIED` to
    `IN_FORCE`"; "The premium axis is untouched by issue and remains `PENDING`."

    Design: Difficulty/non_linear_state_machine/policy_parallel_coverage_and_premium_axes
    """
    ph = create_policyholder()
    policy = create_issued_policy(ph["id"])
    assert policy["coverage_status"] == "IN_FORCE", policy
    assert policy["premium_status"] == "PENDING", policy


# ===========================================================================
# non_linear_state_machine / claim_cyclic_reassessment_loop
# ===========================================================================
def test_claim_reassessment_round_trip(api):
    """PRD 3.6: "they request a reassessment, moving the claim from `UNDER_REVIEW`
    to `PENDING_REASSESSMENT` and setting `requires_reassessment` to true"
    PRD 3.6: "Resuming review moves the claim from `PENDING_REASSESSMENT` back to
    `UNDER_REVIEW` and clears `requires_reassessment` to false ... additionally
    requires that the latest `BenefitTriggerCertification` recorded for the policy
    after the claim was sent for reassessment carries a `decision` of `CERTIFIED`"

    Design: Difficulty/non_linear_state_machine/claim_cyclic_reassessment_loop
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.start_review(claim["id"], CE))

    pending = get_success_data(api.request_reassessment(claim["id"], CE))
    assert pending["status"] == "PENDING_REASSESSMENT", pending
    assert pending["requires_reassessment"] is True, pending

    # A fresh CERTIFIED certification clears the claim back into review.
    record_trigger_certification(ctx["pol_id"], adl_deficiencies=["BATHING", "DRESSING", "EATING"])
    resumed = get_success_data(api.resume_review(claim["id"], CE))
    assert resumed["status"] == "UNDER_REVIEW", resumed
    assert resumed["requires_reassessment"] is False, resumed


def test_resume_review_blocked_until_new_certified(api):
    """PRD 3.6: "Resuming review moves the claim from `PENDING_REASSESSMENT` back
    to `UNDER_REVIEW` ... and additionally requires that the latest
    `BenefitTriggerCertification` recorded for the policy after the claim was sent
    for reassessment carries a `decision` of `CERTIFIED`, failing with
    `ERR_BENEFITS_NOT_TRIGGERED` otherwise."

    With no new certification recorded after request-reassessment, resume-review
    is rejected with ERR_BENEFITS_NOT_TRIGGERED.

    Design: Difficulty/non_linear_state_machine/claim_cyclic_reassessment_loop
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.start_review(claim["id"], CE))
    get_success_data(api.request_reassessment(claim["id"], CE))

    res = api.resume_review(claim["id"], CE)
    validate_error(res, "ERR_BENEFITS_NOT_TRIGGERED")


# ===========================================================================
# transitive_cascade / approve_claim_depth4_ledger_pool_partnership
# ===========================================================================
def test_approve_claim_depth4_cascade(api):
    """PRD 3.7: "A `CLAIM_PAYMENT` entry is appended to the benefit ledger with
    `amount_cents` equal to the negative of the claim's `month_paid_cents`. The
    benefit pool's `lifetime_paid_cents` is recomputed as the sum of all
    `CLAIM_PAYMENT` magnitudes, and its `remaining_pool_cents` is recomputed as
    `inflated_pool_cents` minus `lifetime_paid_cents`, floored at 0."
    PRD 3.9: "While a `PartnershipDisregard` is `ACCRUING`, its
    `protected_asset_cents` equals the policy's `BenefitPool.lifetime_paid_cents`
    exactly"

    REIMBURSEMENT partnership policy, lines 15000/25000/18000 -> 53000:
    pool lifetime_paid 53000, remaining 9947000; ledger CLAIM_PAYMENT -53000;
    partnership protected_asset_cents 53000.

    Design: Difficulty/transitive_cascade/approve_claim_depth4_ledger_pool_partnership
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policyholder_overrides={"medicaid_state_eligible": True},
        policy_overrides={"product_mode": "REIMBURSEMENT", "is_partnership_policy": True})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 53000, claim

    pool = read_benefit_pool(ctx["pol_id"])
    assert pool["lifetime_paid_cents"] == 53000, pool
    assert pool["remaining_pool_cents"] == 9947000, pool

    ledger, _ = read_policy_ledger(ctx["pol_id"])
    payments = [e for e in ledger if e["source_kind"] == "CLAIM_PAYMENT"]
    assert len(payments) == 1, ledger
    assert payments[0]["amount_cents"] == -53000, payments[0]

    disregards, _ = read_partnership_disregard(ctx["pol_id"])
    assert len(disregards) == 1, disregards
    assert disregards[0]["protected_asset_cents"] == 53000, disregards[0]


def test_approve_claim_negative_ledger_sign(api):
    """PRD 3.12: "Sign follows the direction of value: `CLAIM_PAYMENT` and
    `NONFORFEITURE_REDUCTION` carry a negative `amount_cents` because they remove
    value from the pool, while `INFLATION_GROWTH` carries a positive
    `amount_cents`."

    A claim paying 15000 appends a CLAIM_PAYMENT ledger entry of -15000.

    Design: Difficulty/transitive_cascade/approve_claim_depth4_ledger_pool_partnership
    """
    ctx = setup_claim_under_review(lines=[("2026-03-01", 15000)])
    approve_claim(ctx["pol_id"], ctx["claim_id"])
    ledger, _ = read_policy_ledger(ctx["pol_id"])
    payments = [e for e in ledger if e["source_kind"] == "CLAIM_PAYMENT"]
    assert len(payments) == 1, ledger
    assert payments[0]["amount_cents"] == -15000, payments[0]


# ===========================================================================
# transitive_cascade / suspend_provider_depth3_careplan_claim_void
# ===========================================================================
def test_suspend_provider_cascades_plan_closed_and_claim_void(api):
    """PRD 3.8: "The suspension moves the provider's `eligibility_status` to
    `SUSPENDED`, and in the same request every plan of care referencing that
    provider with `status` of `ACTIVE` is transitioned to the terminal `CLOSED`.
    The cascade then reaches one level further: every claim that draws on one of
    those just-closed plans and sits in a non-terminal status — `SUBMITTED`,
    `UNDER_REVIEW`, or `PENDING_REASSESSMENT` — is transitioned to `VOID`."

    Design: Difficulty/transitive_cascade/suspend_provider_depth3_careplan_claim_void
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])  # SUBMITTED, non-terminal

    suspended = get_success_data(api.suspend_provider(ctx["prov_id"], CA))
    assert suspended["eligibility_status"] == "SUSPENDED", suspended

    plan = validate_success(api.get_care_plan(ctx["cp_id"], CA))
    assert plan["status"] == "CLOSED", plan

    claim_after = validate_success(api.get_claim(claim["id"], CE))
    assert claim_after["status"] == "VOID", claim_after


def test_suspend_provider_voids_under_review_claim(api):
    """PRD 3.8: "every claim that draws on one of those just-closed plans and sits
    in a non-terminal status — `SUBMITTED`, `UNDER_REVIEW`, or
    `PENDING_REASSESSMENT` — is transitioned to `VOID`. This is a three-level
    chain from a single suspend: provider to plan to claim."

    A claim already moved to UNDER_REVIEW (still non-terminal) is voided by the
    provider-suspend cascade, and its care plan is CLOSED.

    Design: Difficulty/transitive_cascade/suspend_provider_depth3_careplan_claim_void
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.start_review(claim["id"], CE))
    under_review = validate_success(api.get_claim(claim["id"], CE))
    assert under_review["status"] == "UNDER_REVIEW", under_review

    get_success_data(api.suspend_provider(ctx["prov_id"], CA))

    plan = validate_success(api.get_care_plan(ctx["cp_id"], CA))
    assert plan["status"] == "CLOSED", plan
    claim_after = validate_success(api.get_claim(claim["id"], CE))
    assert claim_after["status"] == "VOID", claim_after


# ===========================================================================
# Corner/state_machines instances
# ===========================================================================
def test_issue_already_in_force_rejected(api):
    """PRD 3.1: "Issuing the policy advances `coverage_status` from `APPLIED` to
    `IN_FORCE`; it is restricted to an `Underwriter` and requires the policy to
    currently be in `APPLIED`, failing with `ERR_INVALID_STATE` otherwise."

    Design: Corner/state_machines/issue_already_in_force_policy_returns_invalid_state
    """
    ph = create_policyholder()
    policy = create_issued_policy(ph["id"])
    res = api.issue_policy(policy["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")


def test_rescind_in_force_rejected(api):
    """PRD 3.1: "an `Underwriter` may rescind a still-`APPLIED` policy, moving
    `coverage_status` from `APPLIED` to the terminal `RESCINDED`; rescission also
    requires the `APPLIED` state and otherwise fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/rescind_in_force_policy_returns_invalid_state
    """
    ph = create_policyholder()
    policy = create_issued_policy(ph["id"])
    res = api.rescind_policy(policy["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")


def test_new_provider_starts_pending(api):
    """PRD 3.4: "A new provider begins in `eligibility_status` `PENDING`."

    Design: Corner/state_machines/initial_state_provider_pending
    """
    provider = get_success_data(api.create_provider(
        {"name": "Init Prov", "provider_type": "HOME_HEALTH_AGENCY", "state_code": "CA"}, CA))
    assert provider["eligibility_status"] == "PENDING", provider


def test_certify_inactive_license_rejected(api):
    """PRD 3.4: "Certification is permitted from `PENDING` or from `SUSPENDED`, and
    in both cases requires that the provider's `license_active` be true; a
    certification attempt against a provider whose license is inactive is rejected
    with `ERR_PROVIDER_LICENSE_INACTIVE`"

    Design: Corner/state_machines/certify_provider_inactive_license_returns_license_inactive
    """
    provider = get_success_data(api.create_provider(
        {"name": "No Lic", "provider_type": "NURSING_HOME", "state_code": "CA",
         "license_active": False}, CA))
    res = api.certify_provider(provider["id"], CA)
    validate_error(res, "ERR_PROVIDER_LICENSE_INACTIVE")


def test_void_claim_cannot_resume(api):
    """PRD 3.6: "Resuming review moves the claim from `PENDING_REASSESSMENT` back
    to `UNDER_REVIEW` ...; it is valid only from `PENDING_REASSESSMENT` (else
    `ERR_INVALID_STATE`)"

    A claim VOIDed by a provider-suspend cascade is no longer in
    PENDING_REASSESSMENT, so resume-review is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_claim_void_cannot_resume
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.suspend_provider(ctx["prov_id"], CA))
    voided = validate_success(api.get_claim(claim["id"], CE))
    assert voided["status"] == "VOID", voided

    res = api.resume_review(claim["id"], CE)
    validate_error(res, "ERR_INVALID_STATE")


def test_activate_care_plan_supersedes_prior_active(api):
    """PRD 3.4: "Activating a plan supersedes the policy's prior plan: any other
    plan for the same policy currently in `ACTIVE` is moved to the terminal
    `SUPERSEDED`."

    Design: Corner/state_machines/care_plan_activate_supersedes_prior_active
    """
    ph = create_policyholder()
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"])
    plan1 = author_and_activate_care_plan(policy["id"], provider["id"])
    assert plan1["status"] == "ACTIVE", plan1

    plan2 = author_and_activate_care_plan(policy["id"], provider["id"])
    assert plan2["status"] == "ACTIVE", plan2

    plan1_after = validate_success(api.get_care_plan(plan1["id"], CA))
    assert plan1_after["status"] == "SUPERSEDED", plan1_after


def test_activate_care_plan_setting_type_mismatch_rejected(api):
    """PRD 3.4: "the plan's `care_setting` must be compatible with the provider's
    `provider_type`, failing with `ERR_CARE_SETTING_MISMATCH`. The compatibility
    pairing is one-to-one across the naming convention: `NURSING_HOME` setting with
    `NURSING_HOME` provider, `ASSISTED_LIVING` with `ASSISTED_LIVING`, `HOME_HEALTH`
    with `HOME_HEALTH_AGENCY`, `ADULT_DAY` with `ADULT_DAY_CARE`, and `INFORMAL`
    with `INFORMAL_CAREGIVER`."

    A NURSING_HOME care_setting on a HOME_HEALTH_AGENCY provider -> mismatch.

    Design: Corner/state_machines/activate_care_plan_setting_type_mismatch_returns_mismatch
    """
    ph = create_policyholder()
    provider = create_eligible_provider(provider_type="HOME_HEALTH_AGENCY")
    policy = create_issued_policy(ph["id"])
    plan = get_success_data(api.create_care_plan(
        {"policy_id": policy["id"], "provider_id": provider["id"],
         "care_setting": "NURSING_HOME"}, CA))
    res = api.activate_care_plan(plan["id"], CA)
    validate_error(res, "ERR_CARE_SETTING_MISMATCH")
