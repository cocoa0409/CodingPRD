"""
Composite setup helpers for multi-step test prerequisites.
Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "setup failed" errors, not confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_landlord_payload, create_renter_payload, create_property_payload,
    create_state_compliance_rule_payload, create_renter_enrollment_payload,
    create_claim_payload, create_subrogation_case_payload, create_recovery_payment_payload,
    create_coverage_limit_adjustment_payload,
)
from .test_users import (
    TEST_USERS, make_landlord_headers, make_renter_headers,
    make_underwriting_agent_headers, make_claims_adjuster_headers,
    make_compliance_officer_headers, make_platform_admin_headers,
)

DEFAULT_CLOCK = "2026-07-01T00:00:00Z"


# ─── Tier 0: Bare entities ──────────────────────────────────────────────

def create_landlord(**overrides) -> dict:
    res = api_client.create_landlord(create_landlord_payload(**overrides), TEST_USERS["anonymous_headers"])
    return get_success_data(res)


def create_renter(**overrides) -> dict:
    res = api_client.create_renter(create_renter_payload(**overrides), TEST_USERS["anonymous_headers"])
    return get_success_data(res)


def create_property(landlord: dict, **overrides) -> dict:
    res = api_client.create_property(
        create_property_payload(landlord["id"], **overrides),
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(res)


def create_state_compliance_rule(state_code: str = "CA", **overrides) -> dict:
    res = api_client.create_state_compliance_rule(
        create_state_compliance_rule_payload(state_code, **overrides),
        make_compliance_officer_headers(),
    )
    return get_success_data(res)


def activate_property(property_id: str) -> dict:
    res = api_client.update_property_program_status(
        property_id, {"action": "ACTIVATE"}, make_compliance_officer_headers()
    )
    return get_success_data(res)


def terminate_property(property_id: str) -> dict:
    res = api_client.update_property_program_status(
        property_id, {"action": "TERMINATE"}, make_compliance_officer_headers()
    )
    return get_success_data(res)


# ─── Tier 1: Active property + state rule ──────────────────────────────

def setup_active_property(state_code: str = "CA", rule_overrides: dict = None, **property_overrides):
    """Create Landlord + Property + StateComplianceRule + ACTIVATE the property.
    Returns (landlord, property, rule)."""
    landlord = create_landlord()
    property_overrides.setdefault("state_code", state_code)
    prop = create_property(landlord, **property_overrides)
    rule = create_state_compliance_rule(state_code, **(rule_overrides or {}))
    prop = activate_property(prop["id"])
    return landlord, prop, rule


# ─── Tier 2: RenterEnrollment -> submit-underwriting -> Policy ─────────

def create_renter_enrollment(property_id: str, renter: dict, **overrides) -> dict:
    res = api_client.create_renter_enrollment(
        create_renter_enrollment_payload(property_id, renter["id"], **overrides),
        make_renter_headers(renter["id"]),
    )
    return get_success_data(res)


def submit_underwriting(enrollment_id: str, renter_id: str) -> dict:
    res = api_client.submit_underwriting(enrollment_id, make_renter_headers(renter_id))
    return get_success_data(res)


def get_policy_for_enrollment(enrollment_id: str, renter_id: str) -> dict:
    res = api_client.get_renter_enrollment_policy(enrollment_id, make_renter_headers(renter_id))
    policies = get_success_data(res)
    return policies[0]


def setup_auto_approved_policy(property_id: str, renter: dict, **enrollment_overrides):
    """Create + submit an enrollment expected to auto-approve (risk_score <= 35).
    Returns (enrollment, policy). Defaults (income 7200000, credit 750, 0 evictions) -> score 7 (LOW)."""
    enrollment = create_renter_enrollment(property_id, renter, **enrollment_overrides)
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    policy = get_policy_for_enrollment(enrollment["id"], renter["id"])
    return enrollment, policy


def setup_manual_review_and_approve(property_id: str, renter: dict, decide_action: str = "APPROVE", **enrollment_overrides):
    """Create + submit an enrollment expected to route to MANUAL_REVIEW (risk_score > 35),
    then have an UnderwritingAgent decide it. Returns (enrollment, policy_or_None)."""
    enrollment = create_renter_enrollment(property_id, renter, **enrollment_overrides)
    enrollment = submit_underwriting(enrollment["id"], renter["id"])
    res = api_client.decide_renter_enrollment(
        enrollment["id"], {"action": decide_action}, make_underwriting_agent_headers()
    )
    enrollment = get_success_data(res)
    policy = None
    if decide_action == "APPROVE":
        policy = get_policy_for_enrollment(enrollment["id"], renter["id"])
    return enrollment, policy


def pay_first_invoice(policy_id: str, renter_id: str) -> dict:
    """Pay a policy's first (ISSUED) invoice, transitioning AWAITING_FIRST_PAYMENT -> ACTIVE."""
    inv_res = api_client.list_policy_invoices(policy_id, make_renter_headers(renter_id))
    invoices = get_success_data(inv_res)
    first_invoice = invoices[0]
    pay_res = api_client.pay_invoice(first_invoice["id"], make_renter_headers(renter_id))
    return get_success_data(pay_res)


def setup_active_policy(coverage_limit_cents: int = 500000, state_code: str = "CA",
                         monthly_rent_cents: int = 200000, rule_overrides: dict = None,
                         **enrollment_overrides):
    """Full chain: Landlord+Property+Rule(active) -> Renter -> auto-approved enrollment ->
    Policy -> pay first invoice (ACTIVE). Returns dict with all created entities."""
    landlord, prop, rule = setup_active_property(
        state_code=state_code, monthly_rent_cents=monthly_rent_cents, rule_overrides=rule_overrides
    )
    renter = create_renter()
    enrollment_overrides.setdefault("requested_coverage_limit_cents", coverage_limit_cents)
    enrollment, policy = setup_auto_approved_policy(prop["id"], renter, **enrollment_overrides)
    pay_first_invoice(policy["id"], renter["id"])
    policy = get_success_data(api_client.get_policy(policy["id"], make_renter_headers(renter["id"])))
    return {
        "landlord": landlord, "property": prop, "rule": rule, "renter": renter,
        "enrollment": enrollment, "policy": policy,
    }


# ─── Tier 3: Claims lifecycle ──────────────────────────────────────────

def file_claim(policy_id: str, landlord_id: str, claim_type: str = "PROPERTY_DAMAGE", line_items=None, **overrides) -> dict:
    res = api_client.create_claim(
        policy_id,
        create_claim_payload(policy_id, claim_type=claim_type, line_items=line_items, **overrides),
        make_landlord_headers(landlord_id),
    )
    return get_success_data(res)


def approve_claim(claim_id: str, adjuster_id: str = "adjuster-001") -> dict:
    res = api_client.decide_claim(claim_id, {"action": "APPROVE"}, make_claims_adjuster_headers(adjuster_id))
    return get_success_data(res)


def deny_claim(claim_id: str, adjuster_id: str = "adjuster-001", decision_notes: str = None) -> dict:
    payload = {"action": "DENY"}
    if decision_notes is not None:
        payload["decision_notes"] = decision_notes
    res = api_client.decide_claim(claim_id, payload, make_claims_adjuster_headers(adjuster_id))
    return get_success_data(res)


def request_claim_info(claim_id: str, adjuster_id: str = "adjuster-001", decision_notes: str = "Please clarify.") -> dict:
    res = api_client.claim_info_transition(
        claim_id, {"action": "REQUEST_INFO", "decision_notes": decision_notes},
        make_claims_adjuster_headers(adjuster_id),
    )
    return get_success_data(res)


def submit_claim_info(claim_id: str, landlord_id: str, line_items=None) -> dict:
    payload = {"action": "SUBMIT_INFO"}
    if line_items is not None:
        payload["line_items"] = line_items
    res = api_client.claim_info_transition(claim_id, payload, make_landlord_headers(landlord_id))
    return get_success_data(res)


def get_payout_for_claim(claim_id: str, landlord_id: str) -> dict:
    res = api_client.list_claim_payouts(claim_id, make_landlord_headers(landlord_id))
    payouts = get_success_data(res)
    return payouts[0]


def disburse_payout(payout_id: str, adjuster_id: str) -> dict:
    res = api_client.payout_transition(payout_id, {"action": "DISBURSE"}, make_claims_adjuster_headers(adjuster_id))
    return get_success_data(res)


def reverse_payout(payout_id: str, reversal_reason: str = "Fraud investigation confirmed no damage occurred.") -> dict:
    res = api_client.payout_transition(
        payout_id, {"action": "REVERSE", "reversal_reason": reversal_reason},
        make_platform_admin_headers(),
    )
    return get_success_data(res)


def setup_approved_claim_with_pending_payout(policy_id: str, landlord_id: str, total_claimed_amount_cents: int,
                                              claim_type: str = "PROPERTY_DAMAGE", approving_adjuster_id: str = "adjuster-001"):
    """File a claim with one line item for the given total, then APPROVE it.
    Returns (claim, payout) with payout still PENDING."""
    claim = file_claim(policy_id, landlord_id, claim_type=claim_type,
                        line_items=[{"description": "Damage/unpaid rent", "amount_cents": total_claimed_amount_cents}])
    claim = approve_claim(claim["id"], approving_adjuster_id)
    payout = get_payout_for_claim(claim["id"], landlord_id)
    return claim, payout


def setup_disbursed_claim(policy_id: str, landlord_id: str, total_claimed_amount_cents: int,
                           claim_type: str = "PROPERTY_DAMAGE",
                           approving_adjuster_id: str = "adjuster-001",
                           disbursing_adjuster_id: str = "adjuster-002"):
    """File, approve, and DISBURSE a claim's payout. Returns (claim, payout) with payout DISBURSED."""
    claim, payout = setup_approved_claim_with_pending_payout(
        policy_id, landlord_id, total_claimed_amount_cents, claim_type, approving_adjuster_id
    )
    payout = disburse_payout(payout["id"], disbursing_adjuster_id)
    return claim, payout


# ─── Tier 4: Subrogation / RecoveryPayment lifecycle ───────────────────

def open_subrogation_case(claim_id: str, original_demand_amount_cents: int) -> dict:
    res = api_client.create_subrogation_case(
        claim_id,
        create_subrogation_case_payload(claim_id, original_demand_amount_cents),
        make_compliance_officer_headers(),
    )
    return get_success_data(res)


def send_demand(subrogation_case_id: str) -> dict:
    res = api_client.subrogation_case_transition(
        subrogation_case_id, {"action": "SEND_DEMAND"}, make_compliance_officer_headers()
    )
    return get_success_data(res)


def write_off_case(subrogation_case_id: str) -> dict:
    res = api_client.subrogation_case_transition(
        subrogation_case_id, {"action": "WRITE_OFF"}, make_compliance_officer_headers()
    )
    return get_success_data(res)


def record_recovery_payment(subrogation_case_id: str, renter_id: str, amount_cents: int) -> dict:
    res = api_client.create_recovery_payment(
        subrogation_case_id,
        create_recovery_payment_payload(subrogation_case_id, amount_cents),
        make_renter_headers(renter_id),
    )
    return get_success_data(res)


def reverse_recovery_payment(recovery_payment_id: str) -> dict:
    res = api_client.reverse_recovery_payment(recovery_payment_id, make_platform_admin_headers())
    return get_success_data(res)


def setup_demand_sent_subrogation_case(policy_id: str, landlord_id: str, renter_id: str,
                                        total_claimed_amount_cents: int,
                                        original_demand_amount_cents: int,
                                        approving_adjuster_id: str = "adjuster-001",
                                        disbursing_adjuster_id: str = "adjuster-002"):
    """UNPAID_RENT claim -> APPROVED -> DISBURSED -> SubrogationCase opened -> DEMAND_SENT.
    Returns (claim, payout, subrogation_case)."""
    claim, payout = setup_disbursed_claim(
        policy_id, landlord_id, total_claimed_amount_cents, claim_type="UNPAID_RENT",
        approving_adjuster_id=approving_adjuster_id, disbursing_adjuster_id=disbursing_adjuster_id,
    )
    case = open_subrogation_case(claim["id"], original_demand_amount_cents)
    case = send_demand(case["id"])
    return claim, payout, case


# ─── Tier 5: Billing cycle / logical clock ─────────────────────────────

def advance_clock(to_iso8601: str) -> None:
    api_client.set_clock(to_iso8601, make_platform_admin_headers())


def run_billing_cycle() -> None:
    api_client.run_billing_cycle(make_platform_admin_headers())


def lapse_policy_via_missed_second_invoice(policy_id: str, renter_id: str,
                                            second_period_clock: str = "2026-08-01T00:00:00Z",
                                            overdue_clock: str = "2026-08-17T00:00:00Z") -> dict:
    """Advance the clock past the first billing period (issuing invoice #2), then advance
    past invoice #2's due_date + OVERDUE_GRACE_DAYS without paying it — cascading the
    Policy ACTIVE -> LAPSED. Returns invoice #2 (now OVERDUE)."""
    advance_clock(second_period_clock)
    run_billing_cycle()
    inv_res = api_client.list_policy_invoices(policy_id, make_renter_headers(renter_id))
    invoices = get_success_data(inv_res)
    invoice2 = invoices[1]
    advance_clock(overdue_clock)
    run_billing_cycle()
    inv_res = api_client.list_policy_invoices(policy_id, make_renter_headers(renter_id))
    invoices = get_success_data(inv_res)
    return next(i for i in invoices if i["id"] == invoice2["id"])


def adjust_coverage_limit(policy_id: str, requested_coverage_limit_cents: int, expected_policy_version: int) -> dict:
    res = api_client.adjust_coverage_limit(
        policy_id,
        create_coverage_limit_adjustment_payload(requested_coverage_limit_cents, expected_policy_version),
        make_underwriting_agent_headers(),
    )
    return res
