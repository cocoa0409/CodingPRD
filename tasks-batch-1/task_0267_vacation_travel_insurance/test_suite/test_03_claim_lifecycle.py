"""Claim revision cycle and policy parallel state axes (§2.8, §3.3, §3.6).

Covers difficulty rule non_linear_state_machine (claim UNDER_REVIEW<->INFO_REQUESTED
cycle; policy payment/coverage axes evolving independently) and the corner
state-machine precondition / terminal-lockdown / system-field instances.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_policy, setup_claim_under_review, set_clock,
    create_plan, create_traveler, create_quoted_policy, add_insured, record_payment,
    issue_policy, get_policy, make_traveler_headers, file_claim,
    create_policy_payload, deny_payload, TEST_USERS,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
ADMIN = TEST_USERS["carrier_admin_headers"]


# ─── non_linear_state_machine: claim revision cycle ────────────────────────

def test_claim_cycles_back_to_under_review_after_second_resubmit(api):
    """PRD §2.8: "may be bounced to `INFO_REQUESTED` and resubmitted back to `UNDER_REVIEW` any
    number of times".
    PRD §3.6: "The owning `Traveler` then resubmits, advancing the claim from `INFO_REQUESTED`
    back to `UNDER_REVIEW`; resubmission is admissible only from `INFO_REQUESTED`, requires that
    at least one document exist on the claim (else `ERR_DOCUMENTATION_MISSING`)".

    request-info -> resubmit -> request-info -> resubmit leaves the claim UNDER_REVIEW, with no
    terminal lock-in.

    Design: Difficulty/non_linear_state_machine/claim_cycle_under_review_info_requested_under_review
    """
    bundle = setup_claim_under_review(peril="MEDICAL", incident_at="2026-06-05T00:00:00Z",
                                      doc_type="MEDICAL_REPORT")
    claim_id = bundle["claim"]["id"]
    owner = bundle["owner_headers"]

    validate_success(api.request_info(claim_id, ADJUSTER), 200)
    validate_success(api.resubmit_claim(claim_id, owner), 200)
    validate_success(api.request_info(claim_id, ADJUSTER), 200)
    final = validate_success(api.resubmit_claim(claim_id, owner), 200)
    assert final["status"] == "UNDER_REVIEW", \
        f"claim must return to UNDER_REVIEW after second resubmit, got {final['status']}"


def test_claim_cycle_increments_version_each_transition(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 and increments by one on
    every mutation of the resource".
    PRD §3.6: "A claim may cycle between `UNDER_REVIEW` and `INFO_REQUESTED` any number of
    times."

    Starting from UNDER_REVIEW, two request-info / resubmit pairs are four mutations, so the
    claim version advances by exactly 4.

    Design: Difficulty/non_linear_state_machine/claim_cycle_under_review_info_requested_under_review
    """
    bundle = setup_claim_under_review(peril="MEDICAL", incident_at="2026-06-05T00:00:00Z",
                                      doc_type="MEDICAL_REPORT")
    claim_id = bundle["claim"]["id"]
    owner = bundle["owner_headers"]
    version_before = bundle["claim"]["version"]

    validate_success(api.request_info(claim_id, ADJUSTER), 200)
    validate_success(api.resubmit_claim(claim_id, owner), 200)
    validate_success(api.request_info(claim_id, ADJUSTER), 200)
    final = validate_success(api.resubmit_claim(claim_id, owner), 200)
    assert final["version"] == version_before + 4, \
        f"claim version must advance by 4 across two cycle pairs, got {final['version']} from {version_before}"


# ─── non_linear_state_machine: policy parallel axes ────────────────────────

def test_record_payment_advances_payment_axis_only(api):
    """PRD §2.8: "a single operation may advance one axis while leaving the other unchanged —
    recording payment, for instance, moves `payment_status` from `PENDING` to `PAID` while
    `coverage_status` remains `QUOTED`."

    Design: Difficulty/non_linear_state_machine/policy_parallel_payment_and_coverage_axes_evolve_independently
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    paid = record_payment(policy["id"], traveler["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["coverage_status"] == "QUOTED", \
        "coverage_status must remain QUOTED after record-payment advances only the payment axis"


def test_issue_advances_coverage_axis_leaving_payment_paid(api):
    """PRD §3.3: "Issuance moves the coverage axis from `QUOTED` to `ACTIVE`" while §2.8
    establishes "The `payment_status` axis tracks premium settlement and takes the values
    `PENDING`, `PAID`, and `REFUNDED`."

    After issue, coverage_status is ACTIVE while payment_status stays PAID — the two axes move
    on separate calls.

    Design: Difficulty/non_linear_state_machine/policy_parallel_payment_and_coverage_axes_evolve_independently
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    record_payment(policy["id"], traveler["id"])
    active = issue_policy(policy["id"])
    assert active["coverage_status"] == "ACTIVE"
    assert active["payment_status"] == "PAID", \
        "payment_status must stay PAID after issue advances only the coverage axis"


# ─── Corner: state-machine preconditions & terminal lockdown ───────────────

def test_start_review_twice_returns_invalid_state(api):
    """PRD §3.6: "Opening review advances a claim from `SUBMITTED` to `UNDER_REVIEW`; this is
    admissible only while the claim is `SUBMITTED`, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/start_review_on_already_under_review_returns_invalid_state
    """
    bundle = setup_claim_under_review(peril="MEDICAL", incident_at="2026-06-02T00:00:00Z",
                                      doc_type="MEDICAL_REPORT")
    res = api.start_review(bundle["claim"]["id"], ADJUSTER)
    validate_error(res, "ERR_INVALID_STATE")


def test_deny_terminal_claim_returns_invalid_state(api):
    """PRD §2.8: "`DENIED` and `PAID` are terminal."
    PRD §3.6: "The adjuster may also deny a claim from `UNDER_REVIEW`, which sets `denial_reason`
    from the request body and moves the claim to `DENIED`."

    A second deny on an already-DENIED claim is not a valid transition -> ERR_INVALID_STATE.

    Design: Corner/state_machines/deny_terminal_claim_lockdown_returns_invalid_state
    """
    bundle = setup_claim_under_review(peril="MEDICAL", incident_at="2026-06-02T00:00:00Z",
                                      doc_type="MEDICAL_REPORT")
    claim_id = bundle["claim"]["id"]
    validate_success(api.deny_claim(claim_id, deny_payload("INSUFFICIENT_PROOF"), ADJUSTER), 200)
    res = api.deny_claim(claim_id, deny_payload("AGAIN"), ADJUSTER)
    validate_error(res, "ERR_INVALID_STATE")


def test_issue_without_paid_premium_returns_premium_not_paid(api):
    """PRD §3.3: "The premium must already be paid — `payment_status` must be `PAID`, otherwise
    the request is rejected with `ERR_PREMIUM_NOT_PAID`."

    Design: Corner/state_machines/issue_without_paid_premium_returns_premium_not_paid
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    res = api.issue_policy(policy["id"], UNDERWRITER)
    validate_error(res, "ERR_PREMIUM_NOT_PAID")


def test_issue_with_trip_cost_mismatch_returns_mismatch(api):
    """PRD §3.3: "the sum of `covered_trip_cost_cents` across all `COVERED` insured travelers
    must equal the policy's `trip_cost_cents` exactly, otherwise `ERR_TRIP_COST_MISMATCH`."

    trip_cost 500000 but the single insured covers only 400000 -> ERR_TRIP_COST_MISMATCH.

    Design: Corner/state_machines/issue_with_trip_cost_mismatch_returns_mismatch
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=400000)
    record_payment(policy["id"], traveler["id"])
    res = api.issue_policy(policy["id"], UNDERWRITER)
    validate_error(res, "ERR_TRIP_COST_MISMATCH")


def test_free_look_cancel_blocked_when_policy_has_claims(api):
    """PRD §3.5: "it is further blocked when the policy has any claim in `SUBMITTED`,
    `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, or `PAID` status, in which case it is rejected
    with `ERR_POLICY_HAS_CLAIMS`."

    Design: Corner/state_machines/free_look_cancel_blocked_when_policy_has_claims
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z")
    policy = active["policy"]
    owner = active["owner_headers"]
    file_claim(policy["id"], active["insured"]["id"], active["traveler_id"],
               "MEDICAL", "2026-06-02T00:00:00Z")
    res = api.free_look_cancel_policy(policy["id"], owner)
    validate_error(res, "ERR_POLICY_HAS_CLAIMS")


def test_clock_advance_past_trip_end_auto_expires_active_policy(api):
    """PRD §3.1: "any policy whose `coverage_status` is `ACTIVE` and whose `trip_end_at` is at
    or before the new clock instant is transitioned to `EXPIRED`, incrementing that policy's
    `version`."

    trip_end_at 2026-07-15; advancing the clock to 2026-07-16 flips coverage_status to EXPIRED.

    Design: Corner/state_machines/clock_advance_active_policy_past_trip_end_auto_expires
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400},
        policy_overrides={"trip_end_at": "2026-07-15T00:00:00Z"},
        clock="2026-06-01T00:00:00Z")
    policy = active["policy"]
    set_clock("2026-07-16T00:00:00Z")
    refreshed = get_policy(policy["id"])
    assert refreshed["coverage_status"] == "EXPIRED", \
        f"coverage_status must be EXPIRED after the clock passes trip_end_at, got {refreshed['coverage_status']}"


# ─── Corner: system fields on policy create ────────────────────────────────

def test_policy_create_mints_system_fields(api):
    """PRD §3.2: "The new policy is born with `coverage_status` `QUOTED` and `payment_status`
    `PENDING`. At quote time the system computes `base_premium_cents` and `premium_cents`".
    PRD §2.4: "The `version` field is an integer that begins at 1".

    A BASIC plan base_rate_bps 400 on trip_cost 500000 -> base_premium_cents = ceil(500000*400/
    10000) = 20000; version 1; coverage QUOTED; payment PENDING.

    Design: Corner/entities/system_fields_generated_input_ignored_on_policy_create
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    headers = make_traveler_headers(traveler["id"])
    res = api.create_policy(create_policy_payload(plan["id"], traveler["id"],
                                                  trip_cost_cents=500000), headers)
    policy = validate_success(res, 201)
    assert policy["version"] == 1
    assert policy["coverage_status"] == "QUOTED"
    assert policy["payment_status"] == "PENDING"
    assert policy["base_premium_cents"] == 20000, \
        f"base_premium_cents must be 20000, got {policy['base_premium_cents']}"
