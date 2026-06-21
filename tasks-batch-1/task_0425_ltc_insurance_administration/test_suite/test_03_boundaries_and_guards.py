"""Numeric boundaries, validation-priority conflicts, and cross-entity guards.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency.
Queue B (Corner): calculations boundary, validations, pool exhaustion.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_policyholder,
    create_policy,
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
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
CA = TEST_USERS["care_assessor_headers"]


# ===========================================================================
# boundary_precision_check / adl_count_two_of_six_inclusive_boundary
# ===========================================================================
def test_adl_two_certifies_one_does_not(api):
    """PRD 3.3: "The resulting `decision` is `CERTIFIED` when that distinct count
    is at least two, or when `cognitive_impairment` is true; otherwise it is
    `NOT_CERTIFIED`. The threshold is inclusive at two: a single activity with no
    cognitive impairment yields `NOT_CERTIFIED`, while exactly two activities
    yield `CERTIFIED`."
    PRD 3.3: "A policy's computed `benefits_triggered` flag is true precisely when
    the latest certification recorded for that policy carries a `decision` of
    `CERTIFIED`"

    Design: Difficulty/boundary_precision_check/adl_count_two_of_six_inclusive_boundary
    """
    ph = create_policyholder(full_name="Two Six")
    policy = create_issued_policy(ph["id"])

    cert2 = get_success_data(api.create_trigger_certification(
        policy["id"], {"adl_deficiencies": ["BATHING", "DRESSING"], "cognitive_impairment": False}, CA))
    assert cert2["decision"] == "CERTIFIED", cert2
    after2 = validate_success(api.get_policy(policy["id"], UW))
    assert after2["benefits_triggered"] is True, after2

    cert1 = get_success_data(api.create_trigger_certification(
        policy["id"],
        {"adl_deficiencies": ["BATHING"], "cognitive_impairment": False,
         "supersedes_id": cert2["id"]}, CA))
    assert cert1["decision"] == "NOT_CERTIFIED", cert1
    after1 = validate_success(api.get_policy(policy["id"], UW))
    assert after1["benefits_triggered"] is False, after1


def test_adl_distinct_count_ignores_duplicates_and_unknown_tokens(api):
    """PRD 3.3: "The system counts the distinct valid activities present in
    `adl_deficiencies`, ignoring duplicates and any token outside that set of
    six."
    PRD 3.3: "The threshold is inclusive at two: a single activity with no
    cognitive impairment yields `NOT_CERTIFIED`"

    ["BATHING", "BATHING", "WALKING"] has only one distinct valid ADL (the
    duplicate and the unknown "WALKING" are ignored) -> NOT_CERTIFIED.

    Design: Difficulty/boundary_precision_check/adl_count_two_of_six_inclusive_boundary
    """
    ph = create_policyholder(full_name="Dup Adl")
    policy = create_issued_policy(ph["id"])
    cert = get_success_data(api.create_trigger_certification(
        policy["id"],
        {"adl_deficiencies": ["BATHING", "BATHING", "WALKING"], "cognitive_impairment": False}, CA))
    assert cert["decision"] == "NOT_CERTIFIED", cert


def test_cognitive_alone_certifies_with_zero_adls(api):
    """PRD 3.3: "The resulting `decision` is `CERTIFIED` when that distinct count
    is at least two, or when `cognitive_impairment` is true; otherwise it is
    `NOT_CERTIFIED`."

    Empty adl_deficiencies but cognitive_impairment true -> CERTIFIED.

    Design: Corner/calculations/cognitive_impairment_alone_certifies_with_zero_adls
    """
    ph = create_policyholder(full_name="Cog Nit")
    policy = create_issued_policy(ph["id"])
    cert = get_success_data(api.create_trigger_certification(
        policy["id"], {"adl_deficiencies": [], "cognitive_impairment": True}, CA))
    assert cert["decision"] == "CERTIFIED", cert


# ===========================================================================
# boundary_precision_check / pool_exhaustion_at_exactly_zero_auto_exhaust
# ===========================================================================
def test_pool_drains_to_zero_auto_exhausts_coverage(api):
    """PRD 3.7: "If the recomputed `remaining_pool_cents` reaches exactly 0, the
    policy auto-transitions `coverage_status` from `CLAIM_OPEN` to the terminal
    `EXHAUSTED` and every other non-terminal claim on the policy is voided to
    `VOID`."

    INDEMNITY daily cap 20000, pool exactly 30000: pays 20000 + 10000 + 0 = 30000,
    pool to 0, coverage -> EXHAUSTED.

    Design: Difficulty/boundary_precision_check/pool_exhaustion_at_exactly_zero_auto_exhaust
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policy_overrides={"product_mode": "INDEMNITY", "initial_pool_cents": 30000})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 30000, claim

    pool = read_benefit_pool(ctx["pol_id"])
    assert pool["remaining_pool_cents"] == 0, pool

    policy = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert policy["coverage_status"] == "EXHAUSTED", policy


def test_pool_above_zero_returns_coverage_to_in_force(api):
    """PRD 3.7: "Otherwise, if no other non-terminal claim remains, coverage
    returns from `CLAIM_OPEN` to `IN_FORCE`."
    PRD 3.7: "and its `remaining_pool_cents` is recomputed as `inflated_pool_cents`
    minus `lifetime_paid_cents`, floored at 0."

    INDEMNITY daily cap 20000, pool 70000: pays 60000, remaining 10000 (> 0), so
    coverage returns to IN_FORCE rather than EXHAUSTED.

    Design: Difficulty/boundary_precision_check/pool_exhaustion_at_exactly_zero_auto_exhaust
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policy_overrides={"product_mode": "INDEMNITY", "initial_pool_cents": 70000})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 60000, claim

    pool = read_benefit_pool(ctx["pol_id"])
    assert pool["remaining_pool_cents"] == 10000, pool

    policy = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert policy["coverage_status"] == "IN_FORCE", policy


# ===========================================================================
# priority_pair_validation_conflict / invalid_state_beats_benefits_not_triggered
# ===========================================================================
def test_approve_submitted_claim_state_check_wins(api):
    """PRD 3.13: "State validity comes fifth: a target not in a state from which
    the requested transition is defined yields `ERR_INVALID_STATE`. Only after
    these structural checks do the domain-specific business rules described
    throughout Section 3 apply — care-setting compatibility, provider
    eligibility, benefit-trigger satisfaction, premium currency"
    PRD 3.7: "the claim must be `UNDER_REVIEW` (else `ERR_INVALID_STATE`)"

    Approving a SUBMITTED (not UNDER_REVIEW) claim on a policy whose latest
    certification is NOT_CERTIFIED fails the state check (priority 5) before the
    benefits-triggered business check -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_benefits_not_triggered_on_approve
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])  # SUBMITTED
    # Downgrade benefits so an approve would also fail the benefits-triggered check:
    # a superseding 1-ADL certification makes the latest decision NOT_CERTIFIED.
    record_trigger_certification(
        ctx["pol_id"], adl_deficiencies=["BATHING"], cognitive_impairment=False)
    downgraded = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert downgraded["benefits_triggered"] is False, downgraded

    version = downgraded["version"]
    res = api.approve_claim(claim["id"], {"expected_policy_version": version}, CE)
    validate_error(res, "ERR_INVALID_STATE")


def test_approve_under_review_claim_benefits_check_fires_when_state_ok(api):
    """PRD 3.7: "Approval is gated by four conditions evaluated against the policy:
    the claim must be `UNDER_REVIEW` (else `ERR_INVALID_STATE`),
    `expected_policy_version` must match the policy's current `version` (else
    `ERR_STALE_VERSION`), the policy's `benefits_triggered` must be true (else
    `ERR_BENEFITS_NOT_TRIGGERED`)"

    When the state precondition passes (claim UNDER_REVIEW) but benefits are not
    triggered, the lower-priority business check surfaces:
    ERR_BENEFITS_NOT_TRIGGERED — confirming the state/business ordering of the pair.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_benefits_not_triggered_on_approve
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.start_review(claim["id"], CE))  # now UNDER_REVIEW
    # Supersede with a NOT_CERTIFIED certification so benefits_triggered becomes false.
    record_trigger_certification(
        ctx["pol_id"], adl_deficiencies=["BATHING"], cognitive_impairment=False)
    downgraded = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert downgraded["benefits_triggered"] is False, downgraded

    res = api.approve_claim(claim["id"], {"expected_policy_version": downgraded["version"]}, CE)
    validate_error(res, "ERR_BENEFITS_NOT_TRIGGERED")


# ===========================================================================
# priority_pair_validation_conflict / provider_not_eligible_beats_premium_not_current
# ===========================================================================
def test_open_claim_lapsed_premium_rejected(api):
    """PRD 3.5: "The policy's `premium_status` must be one of `PAID_CURRENT`,
    `WAIVED`, or `NONFORFEITURE_PAID_UP` — a premium that is not current blocks
    the open with `ERR_PREMIUM_NOT_CURRENT`."

    A benefits-triggered, IN_FORCE policy whose premium_status has lapsed
    (clock past grace, unvested) rejects a claim open with ERR_PREMIUM_NOT_CURRENT.

    Design: Difficulty/priority_pair_validation_conflict/provider_not_eligible_beats_premium_not_current_paths
    """
    ph = create_policyholder(full_name="Both Fail")
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"])  # NONE rider, no benefits paid -> unvested
    inv0 = add_premium_invoice(policy["id"], 0)
    pay_invoice(inv0["id"], ph["id"])
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])
    # An unpaid period-1 invoice with a short grace.
    add_premium_invoice(policy["id"], 1, due_date="2026-02-28", grace_deadline="2026-03-15")
    get_success_data(api.advance_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, UW))

    lapsed = validate_success(api.get_policy(policy["id"], CE))
    assert lapsed["premium_status"] == "LAPSED", lapsed

    version = lapsed["version"]
    res = api.create_claim(
        {"policy_id": policy["id"], "care_plan_id": plan["id"],
         "service_month": "2026-05", "expected_policy_version": version}, CE)
    validate_error(res, "ERR_PREMIUM_NOT_CURRENT")


def test_open_claim_premium_still_pending_rejected(api):
    """PRD 3.5: "The policy's `premium_status` must be one of `PAID_CURRENT`,
    `WAIVED`, or `NONFORFEITURE_PAID_UP` — a premium that is not current blocks
    the open with `ERR_PREMIUM_NOT_CURRENT`."

    A benefits-triggered, IN_FORCE policy whose first premium was never paid sits
    in premium_status PENDING (not in the allowed set), so a claim open is rejected
    with ERR_PREMIUM_NOT_CURRENT — the temporal check the priority-pair instance
    isolates on the claim-open endpoint.

    Design: Difficulty/priority_pair_validation_conflict/provider_not_eligible_beats_premium_not_current_paths
    """
    ph = create_policyholder(full_name="Still Pend")
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"])  # premium_status PENDING (unpaid)
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])

    pending = validate_success(api.get_policy(policy["id"], CE))
    assert pending["premium_status"] == "PENDING", pending
    assert pending["coverage_status"] == "IN_FORCE", pending

    res = api.create_claim(
        {"policy_id": policy["id"], "care_plan_id": plan["id"],
         "service_month": "2026-03", "expected_policy_version": pending["version"]}, CE)
    validate_error(res, "ERR_PREMIUM_NOT_CURRENT")


# ===========================================================================
# cross_entity_state_dependency / start_review_requires_provider_eligible_and_plan_active
# ===========================================================================
def test_start_review_after_provider_suspend_rejected(api):
    """PRD 3.8: "every claim that draws on one of those just-closed plans and sits
    in a non-terminal status — `SUBMITTED`, `UNDER_REVIEW`, or
    `PENDING_REASSESSMENT` — is transitioned to `VOID`."
    PRD 3.6: "the claim must currently be `SUBMITTED` (else `ERR_INVALID_STATE`)"

    Suspending the provider voids the SUBMITTED claim via cascade, so a subsequent
    start-review hits the state precondition first -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/start_review_requires_provider_eligible_and_plan_active
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.suspend_provider(ctx["prov_id"], CA))

    res = api.start_review(claim["id"], CE)
    validate_error(res, "ERR_INVALID_STATE")


def test_start_review_blocked_when_care_plan_closed(api):
    """PRD 3.6: "Starting review moves the claim from `SUBMITTED` to `UNDER_REVIEW`
    and is gated by three conditions: the claim must currently be `SUBMITTED`
    (else `ERR_INVALID_STATE`), the referenced care plan's `status` must be
    `ACTIVE` (else `ERR_CARE_PLAN_NOT_ACTIVE`)"

    Closing the care plan directly (no claim cascade) leaves the claim SUBMITTED,
    so start-review fails the care-plan-active dependency:
    ERR_CARE_PLAN_NOT_ACTIVE — the claim->care-plan cross-entity dependency.

    Design: Difficulty/cross_entity_state_dependency/start_review_requires_provider_eligible_and_plan_active
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"])
    get_success_data(api.close_care_plan(ctx["cp_id"], CA))

    res = api.start_review(claim["id"], CE)
    validate_error(res, "ERR_CARE_PLAN_NOT_ACTIVE")


# ===========================================================================
# cross_entity_state_dependency / open_claim_requires_policy_in_force_and_premium_current
# ===========================================================================
def test_open_claim_in_grace_rejected(api):
    """PRD 3.5: "The policy's `premium_status` must be one of `PAID_CURRENT`,
    `WAIVED`, or `NONFORFEITURE_PAID_UP` — a premium that is not current blocks
    the open with `ERR_PREMIUM_NOT_CURRENT`."

    With premium_status GRACE (not in the allowed set) but coverage IN_FORCE, the
    open is rejected with ERR_PREMIUM_NOT_CURRENT.

    Design: Difficulty/cross_entity_state_dependency/open_claim_requires_policy_in_force_and_premium_current
    """
    ph = create_policyholder(full_name="Grace Open")
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"])
    inv0 = add_premium_invoice(policy["id"], 0)
    pay_invoice(inv0["id"], ph["id"])
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])
    add_premium_invoice(policy["id"], 1, due_date="2026-02-28", grace_deadline="2026-05-04")
    get_success_data(api.advance_clock({"to_iso8601": "2026-03-15T00:00:00Z"}, UW))

    in_grace = validate_success(api.get_policy(policy["id"], CE))
    assert in_grace["coverage_status"] == "IN_FORCE", in_grace
    assert in_grace["premium_status"] == "GRACE", in_grace

    res = api.create_claim(
        {"policy_id": policy["id"], "care_plan_id": plan["id"],
         "service_month": "2026-04", "expected_policy_version": in_grace["version"]}, CE)
    validate_error(res, "ERR_PREMIUM_NOT_CURRENT")


def test_open_claim_against_applied_policy_rejected(api):
    """PRD 3.5: "And the policy's coverage must be `IN_FORCE`, else
    `ERR_INVALID_STATE`."
    PRD 3.13: "State validity comes fifth: a target not in a state from which the
    requested transition is defined yields `ERR_INVALID_STATE`."

    Opening a claim against a never-issued APPLIED policy (coverage not IN_FORCE)
    is rejected with ERR_INVALID_STATE — the coverage half of the Claim->Policy
    dependency, ahead of the premium-current business check.

    Design: Difficulty/cross_entity_state_dependency/open_claim_requires_policy_in_force_and_premium_current
    """
    ph = create_policyholder(full_name="Applied Open")
    provider = create_eligible_provider()
    policy = create_policy(ph["id"])  # APPLIED, never issued
    record_trigger_certification(policy["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])

    applied = validate_success(api.get_policy(policy["id"], CE))
    assert applied["coverage_status"] == "APPLIED", applied

    res = api.create_claim(
        {"policy_id": policy["id"], "care_plan_id": plan["id"],
         "service_month": "2026-03", "expected_policy_version": applied["version"]}, CE)
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Corner/validations
# ===========================================================================
def test_claim_line_service_date_out_of_month_rejected(api):
    """PRD 3.5: "A line's `service_date` must fall inside the claim's
    `service_month` — that is, the date's year-month prefix must match —
    otherwise the line is rejected with `ERR_SERVICE_DATE_OUT_OF_MONTH`."

    Design: Corner/validations/service_date_out_of_month_returns_error
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    res = api.add_claim_line(claim["id"], {"service_date": "2026-04-01", "billed_charge_cents": 15000}, CE)
    validate_error(res, "ERR_SERVICE_DATE_OUT_OF_MONTH")


def test_pay_after_grace_expired_rejected(api):
    """PRD 3.10: "a payment attempted after the grace deadline has passed is
    rejected with `ERR_GRACE_EXPIRED`."
    PRD 3.10: "Paying an `OPEN` invoice is always rejected with
    `ERR_INVOICE_NOT_OPEN` if the invoice is not open."

    After the clock passes grace_deadline the invoice is DEFAULTED, so a pay
    attempt is rejected by either the grace-expiry or the not-open guard; both are
    409 rejections of a post-grace payment.

    Design: Corner/validations/pay_invoice_after_grace_returns_grace_expired
    """
    from test_helpers import validate_error_is_one_of, make_policyholder_headers
    ph = create_policyholder(full_name="Late Pay")
    policy = create_issued_policy(ph["id"])
    inv0 = add_premium_invoice(policy["id"], 0, due_date="2026-01-31", grace_deadline="2026-03-01")
    get_success_data(api.advance_clock({"to_iso8601": "2026-03-10T00:00:00Z"}, UW))

    res = api.pay_premium_invoice(inv0["id"], make_policyholder_headers(ph["id"]))
    validate_error_is_one_of(res, ["ERR_GRACE_EXPIRED", "ERR_INVOICE_NOT_OPEN"])
    assert res.status_code == 409, res.status_code


def test_file_rate_increase_while_one_pending_rejected(api):
    """PRD 3.11: "an attempt to file a new rate increase while another `FILED`
    filing already exists for the policy is rejected with
    `ERR_RATE_FILING_PENDING`."

    Design: Corner/validations/file_rate_increase_while_one_pending_returns_filing_pending
    """
    ph = create_policyholder(full_name="Two File")
    policy = create_issued_policy(ph["id"])
    get_success_data(api.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))
    res = api.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 20, "effective_period_index": 2}, UW)
    validate_error(res, "ERR_RATE_FILING_PENDING")


def test_adjudicate_granted_over_requested_rejected(api):
    """PRD 3.11: "A `granted_pct` outside the inclusive range from 0 to
    `requested_increase_pct` is rejected with `ERR_INVALID_REQUEST`"

    granted_pct 50 > requested 40 -> ERR_INVALID_REQUEST.

    Design: Corner/validations/adjudicate_granted_pct_over_requested_returns_invalid_request
    """
    ph = create_policyholder(full_name="Over Pct")
    policy = create_issued_policy(ph["id"])
    filing = get_success_data(api.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))
    version = validate_success(api.get_policy(policy["id"], TEST_USERS["regulator_headers"]))["version"]
    res = api.adjudicate_rate_filing(
        filing["id"], {"granted_pct": 50, "expected_policy_version": version},
        TEST_USERS["regulator_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")
