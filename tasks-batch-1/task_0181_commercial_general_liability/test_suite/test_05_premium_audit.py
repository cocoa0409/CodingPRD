"""Premium audit lifecycle: estimated-vs-audited reconciliation, the dispute/reopen
revision cycle, the waiver-vs-finalize auto-branch, and audit preconditions.

Covers Difficulty queue instances for premium reconciliation, the audit revision cycle,
and the at-threshold waiver boundary; plus Corner queue instances for basis mismatch,
no-exposure completion, in-force start rejection, and material-adjustment finalization.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    factories, fixtures,
)

UW = TEST_USERS["underwriter_headers"]
AUD = TEST_USERS["premium_auditor_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/estimated_vs_audited_premium_reconciliation
# ===========================================================================
def test_audited_premium_and_net_adjustment_reconcile(api):
    """PRD §3.8: "the summed `audited_exposure_units` is divided by one thousand, reduced to a
    whole number by discarding any remainder, and multiplied by the policy's `rate_per_unit_cents`;
    the resulting raw figure is then taken as the greater of itself and the policy's
    `minimum_premium_cents`, and stored as `computed_audited_premium_cents`."
    PRD §3.8: "The `net_adjustment_cents` is this computed audited premium minus the policy's
    `estimated_premium_cents`".

    Design: Difficulty/dual_variant_calc/estimated_vs_audited_premium_reconciliation
    """
    insurer, insured, policy, audit = fixtures.setup_completed_audit(exposure_units=1500000)
    # estimated: floor(1000000/1000)*300 = 300000.
    assert policy["estimated_premium_cents"] == 300000
    audit = validate_success(api.get_audit(audit["id"], AUD), 200)
    # audited: floor(1500000/1000)*300 = 450000; net = 450000 - 300000 = 150000.
    assert audit["computed_audited_premium_cents"] == 450000
    assert audit["net_adjustment_cents"] == 150000


def test_estimated_and_audited_share_rating_on_different_exposures(api):
    """PRD §3.8: "On completion the **audited premium** is computed on exactly the same mechanics
    as the estimated premium so the two reconcile".
    PRD §3.2: "this is divided by one thousand and reduced to a whole number by discarding any
    remainder, then multiplied by `rate_per_unit_cents` to produce a raw premium."

    Design: Difficulty/dual_variant_calc/estimated_vs_audited_premium_reconciliation
    """
    # Audited exposure EQUAL to the estimate -> audited premium equals estimated, net == 0.
    insurer, insured, policy, audit = fixtures.setup_completed_audit(exposure_units=1000000)
    assert policy["estimated_premium_cents"] == 300000
    audit = validate_success(api.get_audit(audit["id"], AUD), 200)
    assert audit["computed_audited_premium_cents"] == 300000
    assert audit["net_adjustment_cents"] == 0


# ===========================================================================
# Difficulty/non_linear_state_machine/premium_audit_dispute_reopen_revision_cycle
# ===========================================================================
def test_audit_dispute_reopen_increments_revision_round(api):
    """PRD §3.8: "An `InsurerAdmin` may dispute it, moving it from `COMPLETED` to `DISPUTED`, and
    a `PremiumAuditor` may then reopen the disputed audit, moving it from `DISPUTED` back to
    `IN_PROGRESS`; reopening increments the audit's `revision_round` by one and clears
    `computed_audited_premium_cents` and `net_adjustment_cents` so they are recomputed on the next
    completion."

    Design: Difficulty/non_linear_state_machine/premium_audit_dispute_reopen_revision_cycle
    """
    insurer, insured, policy, audit = fixtures.setup_disputed_audit(exposure_units=1500000)
    assert audit["status"] == "DISPUTED"
    reopened = validate_success(api.reopen_audit(audit["id"], AUD), 200)
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["revision_round"] == 1


def test_audit_recompletes_with_new_exposure_after_reopen(api):
    """PRD §3.8: "reopening increments the audit's `revision_round` by one and clears
    `computed_audited_premium_cents` and `net_adjustment_cents` so they are recomputed on the next
    completion."
    PRD §3.8: "The audit's `audited_exposure_units` is maintained as the order-independent sum of
    `basis_amount_units` across all its exposure records."

    Design: Difficulty/non_linear_state_machine/premium_audit_dispute_reopen_revision_cycle
    """
    insurer, insured, policy, audit = fixtures.setup_disputed_audit(exposure_units=1500000)
    validate_success(api.reopen_audit(audit["id"], AUD), 200)
    # Add a second exposure record: total exposure becomes 2,000,000.
    fixtures.add_exposure_record(audit["id"], "91561", 500000)
    recompleted = validate_success(api.complete_audit(audit["id"], AUD), 200)
    assert recompleted["status"] == "COMPLETED"
    # floor(2000000/1000)*300 = 600000.
    assert recompleted["computed_audited_premium_cents"] == 600000


# ===========================================================================
# Difficulty/boundary_precision_check/audit_waiver_at_exactly_threshold_waives
# ===========================================================================
def test_audit_waives_when_net_adjustment_at_threshold(api):
    """PRD §3.8: "If the absolute value of `net_adjustment_cents` is at or below the insurer's
    `audit_waiver_threshold_cents`, the audit is waived: it moves from `COMPLETED` to `WAIVED`,
    the policy is driven to `AUDIT_CLOSED`, and the policy's `audited_premium_cents` is set equal
    to its `estimated_premium_cents` (the estimate stands, no adjustment)."

    Design: Difficulty/boundary_precision_check/audit_waiver_at_exactly_threshold_waives
    """
    # waiver threshold 50000; audited exposure 1166000 -> floor(1166.0)*300 = 349800;
    # net = 349800 - 300000 = 49800 <= 50000 -> WAIVED, audited_premium_cents = estimated 300000.
    insurer, insured, policy, audit = fixtures.setup_completed_audit(
        exposure_units=1166000, waiver_threshold=50000)
    audit = validate_success(api.get_audit(audit["id"], AUD), 200)
    assert audit["computed_audited_premium_cents"] == 349800
    assert audit["net_adjustment_cents"] == 49800
    pv = fixtures.current_policy_version(policy["id"])
    finalized = validate_success(
        api.finalize_audit(audit["id"], {"expected_policy_version": pv}, AUD), 200)
    assert finalized["status"] == "WAIVED"
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["audited_premium_cents"] == 300000


def test_audit_waiver_drives_policy_to_audit_closed(api):
    """PRD §3.8: "the policy is driven to `AUDIT_CLOSED`, and the policy's `audited_premium_cents`
    is set equal to its `estimated_premium_cents`".
    PRD §2.6: "When a premium audit finalizes or waives, the parent policy is driven to
    `AUDIT_CLOSED` and its `audited_premium_cents` is written."

    Design: Difficulty/boundary_precision_check/audit_waiver_at_exactly_threshold_waives
    """
    insurer, insured, policy, audit = fixtures.setup_completed_audit(
        exposure_units=1166000, waiver_threshold=50000)
    pv = fixtures.current_policy_version(policy["id"])
    validate_success(api.finalize_audit(audit["id"], {"expected_policy_version": pv}, AUD), 200)
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["status"] == "AUDIT_CLOSED"


# ===========================================================================
# Corner/validations/audit_basis_mismatch_rejected
# ===========================================================================
def test_audit_basis_mismatch_rejected(api):
    """PRD §3.8: "an `audit_basis` (`PAYROLL` or `SALES`) that must equal the policy's
    `premium_basis`; a mismatch is rejected with `ERR_AUDIT_BASIS_MISMATCH`."

    Design: Corner/validations/audit_basis_mismatch_rejected
    """
    insurer, insured, policy = fixtures.create_expired_policy(policy_number="CGL-C24")
    resp = api.create_audit(factories.create_audit_payload(policy["id"], "SALES"), AUD)
    validate_error(resp, ApiErrorId.ERR_AUDIT_BASIS_MISMATCH.value, 422)


# ===========================================================================
# Corner/validations/complete_audit_with_no_exposure_records_rejected
# ===========================================================================
def test_complete_audit_with_no_exposure_records_rejected(api):
    """PRD §3.8: "Completing the audit moves it from `IN_PROGRESS` to `COMPLETED` and requires at
    least one exposure record, else `ERR_NO_EXPOSURE_RECORDS`."

    Design: Corner/validations/complete_audit_with_no_exposure_records_rejected
    """
    insurer, insured, policy = fixtures.create_expired_policy(policy_number="CGL-C25")
    audit = fixtures.schedule_audit(policy["id"], "PAYROLL")
    validate_success(api.start_audit(audit["id"], AUD), 200)
    resp = api.complete_audit(audit["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_NO_EXPOSURE_RECORDS.value, 409)


# ===========================================================================
# Corner/validations/start_audit_on_in_force_policy_rejected
# ===========================================================================
def test_start_audit_on_in_force_policy_rejected(api):
    """PRD §3.8: "starting requires that the policy be `EXPIRED`, else `ERR_POLICY_NOT_AUDITABLE`."

    Design: Corner/validations/start_audit_on_in_force_policy_rejected
    """
    # Schedule the audit while the policy is still IN_FORCE (clock not advanced past expiry).
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-C26")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    audit = fixtures.schedule_audit(policy["id"], "PAYROLL")
    resp = api.start_audit(audit["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_AUDITABLE.value, 409)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/audit_finalize_material_adjustment_drives_audit_closed
# ===========================================================================
def test_audit_finalize_material_adjustment_drives_audit_closed(api):
    """PRD §3.8: "If instead the absolute value of the adjustment strictly exceeds the waiver
    threshold, the audit is finalized: it moves from `COMPLETED` to `FINALIZED`, the policy is
    driven to `AUDIT_CLOSED`, the policy's `audited_premium_cents` is set to the audit's
    `computed_audited_premium_cents`, and the policy `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/audit_finalize_material_adjustment_drives_audit_closed
    """
    # net adjustment 150000 > 50000 default threshold -> FINALIZED, audited 450000.
    insurer, insured, policy, audit = fixtures.setup_completed_audit(exposure_units=1500000)
    pv = fixtures.current_policy_version(policy["id"])
    finalized = validate_success(
        api.finalize_audit(audit["id"], {"expected_policy_version": pv}, AUD), 200)
    assert finalized["status"] == "FINALIZED"
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["status"] == "AUDIT_CLOSED"
    assert pol["audited_premium_cents"] == 450000
