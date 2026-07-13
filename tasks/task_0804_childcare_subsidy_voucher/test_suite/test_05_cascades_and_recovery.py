"""Cascades, ledger conservation, and overpayment recovery (PRD §2.8, §3.2, §3.3, §3.7, §2.7).

Depth coverage for the depth-3 revocation cascade, the determination-denial cascade,
and the two conserved ledgers; breadth coverage for recovery limits, full recovery,
verify-from-licensed lockdown, and the expire/renew loop.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_authorization, submit_attendance, setup_paid_payment,
    setup_open_overpayment_claim, publish_income_standard, publish_rate_ceiling,
    create_family_with_activity, open_determination, register_provider,
    create_pending_authorization, create_licensed_provider, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / license_revoke_cascade_provider_authorization_attendance
# ---------------------------------------------------------------------------
def test_revoke_suspends_active_authorization(api):
    """PRD §3.3: "Revoking a `LICENSED` provider moves `license_status` to `REVOKED`,
    also terminal, and triggers cascade A: every `ACTIVE` authorization for that
    provider is suspended, which in turn rejects those authorizations' `SUBMITTED`
    attendance (see §2.8)."

    Design: Difficulty/transitive_cascade/license_revoke_cascade_provider_authorization_attendance
    """
    ctx = setup_active_authorization()
    submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                      present_days=18, absent_days=3)
    provider = validate_success(
        api.license_provider(ctx["provider"]["id"], {"action": "REVOKE"}, PA), 200)
    assert provider["license_status"] == "REVOKED"
    auth = validate_success(api.get_authorization(ctx["authorization"]["id"], CW), 200)
    assert auth["status"] == "SUSPENDED"


def test_revoke_cascade_rejects_submitted_attendance(api):
    """PRD §2.8: "Each such suspension in turn triggers the second hop: every
    `AttendanceRecord` for that authorization currently in `SUBMITTED` transitions to
    `REJECTED`."

    Design: Difficulty/transitive_cascade/license_revoke_cascade_provider_authorization_attendance
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    api.license_provider(ctx["provider"]["id"], {"action": "REVOKE"}, PA)
    record = validate_success(api.get_attendance_record(att["id"], CW), 200)
    assert record["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / determination_deny_cascade_terminates_authorization
# ---------------------------------------------------------------------------
def _setup_pending_auth_on_pending_determination():
    publish_income_standard(entry_monthly_limit_cents=400_000)
    publish_rate_ceiling()
    family = create_family_with_activity(gross=600_000, self_emp=0, applicant_name="Rich Fam")
    det = open_determination(family["id"], "INITIAL")  # left PENDING
    provider = register_provider()
    auth = create_pending_authorization(family["id"], provider["id"], det["id"])
    return family, det, auth


def test_finalize_denied_sets_result_and_income_ineligible(api):
    """PRD §3.2: "`income_eligible` is true when `countable_income_cents` is less than
    or equal to the applicable limit."
    PRD §3.2: "If either test fails, the determination is finalized to `DENIED`: its
    `result` becomes `DENIED`, its `monthly_copay_cents` stays 0, the household
    `status` is set to `INELIGIBLE`, and cascade B fires"

    Design: Difficulty/transitive_cascade/determination_deny_cascade_terminates_authorization
    """
    family, det, auth = _setup_pending_auth_on_pending_determination()
    finalized = validate_success(api.finalize_determination(det["id"], CW), 200)
    assert finalized["result"] == "DENIED"
    assert finalized["income_eligible"] is False


def test_denial_cascade_terminates_pending_authorization(api):
    """PRD §2.8: "When a determination is finalized to `DENIED`, every `Authorization`
    that rests on that determination and is currently in `PENDING`, `ACTIVE`, or
    `SUSPENDED` transitions to `TERMINATED`."

    Design: Difficulty/transitive_cascade/determination_deny_cascade_terminates_authorization
    """
    family, det, auth = _setup_pending_auth_on_pending_determination()
    api.finalize_determination(det["id"], CW)
    current = validate_success(api.get_authorization(auth["id"], CW), 200)
    assert current["status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / provider_payment_ledger_conserved_on_reverse
# ---------------------------------------------------------------------------
def test_provider_ledger_returns_to_zero_after_reverse(api):
    """PRD §3.7: "It unwinds both ledgers exactly: the provider's `total_net_paid_cents`
    is reduced by the payment's `net_provider_payment_cents`, and the household's
    `total_copay_charged_cents` is reduced by the payment's `copay_deducted_cents`,
    returning both ledgers to their pre-approval values."

    Design: Difficulty/compensating_invariant/provider_payment_ledger_conserved_on_reverse
    """
    ctx = setup_open_overpayment_claim(present_days=18, absent_days=3)
    assert ctx["reversed_payment"]["status"] == "REVERSED"
    provider = validate_success(api.get_provider(ctx["provider"]["id"], PA), 200)
    assert provider["total_net_paid_cents"] == 0


def test_reverse_raises_overpayment_claim_with_net_amount(api):
    """PRD §3.7: "Reversal simultaneously raises an `OverpaymentClaim` against the
    provider in `status` `OPEN`, whose `amount_cents` is the reversed payment's
    `net_provider_payment_cents` and whose `reason` is `PAYMENT_REVERSAL`."

    Design: Difficulty/compensating_invariant/provider_payment_ledger_conserved_on_reverse
    """
    ctx = setup_open_overpayment_claim(present_days=18, absent_days=3)
    assert ctx["claim"]["amount_cents"] == 93_072
    assert ctx["claim"]["status"] == "OPEN"
    assert ctx["claim"]["reason"] == "PAYMENT_REVERSAL"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / family_copay_ledger_conserved_on_reverse
# ---------------------------------------------------------------------------
def test_family_copay_ledger_charged_on_approve(api):
    """PRD §2.8: "`Family.total_copay_charged_cents` equals the sum of
    `copay_deducted_cents` over all that household's payments in status `PAID`."

    Design: Difficulty/compensating_invariant/family_copay_ledger_conserved_on_reverse
    """
    ctx = setup_paid_payment(present_days=18, absent_days=3)
    assert ctx["payment"]["copay_deducted_cents"] == 11_928
    family = validate_success(api.get_family(ctx["family"]["id"], CW), 200)
    assert family["total_copay_charged_cents"] == 11_928


def test_family_copay_ledger_returns_to_zero_after_reverse(api):
    """PRD §3.7: "the household's `total_copay_charged_cents` is reduced by the
    payment's `copay_deducted_cents`, returning both ledgers to their pre-approval
    values."

    Design: Difficulty/compensating_invariant/family_copay_ledger_conserved_on_reverse
    """
    ctx = setup_open_overpayment_claim(present_days=18, absent_days=3)
    family = validate_success(api.get_family(ctx["family"]["id"], CW), 200)
    assert family["total_copay_charged_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / recovery_exceeds_claim_returns_422
# ---------------------------------------------------------------------------
def test_recovery_installment_over_claim_amount_returns_422(api):
    """PRD §3.7: "an installment that would push the cumulative `recovered_amount_cents`
    above `amount_cents` is rejected with `ERR_RECOVERY_EXCEEDS_CLAIM`."

    Design: Corner/validations/recovery_exceeds_claim_returns_422
    """
    ctx = setup_open_overpayment_claim(present_days=18, absent_days=3)
    resp = api.record_recovery(ctx["claim"]["id"], {"recovered_amount_cents": 100_000}, PA)
    validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_CLAIM)


# ---------------------------------------------------------------------------
# Corner: endpoints / overpayment_full_recovery_marks_recovered
# ---------------------------------------------------------------------------
def test_full_recovery_marks_claim_recovered(api):
    """PRD §3.7: "When an installment brings the cumulative `recovered_amount_cents`
    exactly to the `amount_cents`, the claim is marked fully paid: the running total is
    set to the `amount_cents` and the claim transitions to `RECOVERED`."

    Design: Corner/endpoints/overpayment_full_recovery_marks_recovered
    """
    ctx = setup_open_overpayment_claim(present_days=18, absent_days=3)
    data = validate_success(
        api.record_recovery(ctx["claim"]["id"], {"recovered_amount_cents": 93_072}, PA), 200)
    assert data["status"] == "RECOVERED"
    assert data["recovered_amount_cents"] == 93_072


# ---------------------------------------------------------------------------
# Corner: state_machines / provider_verify_from_licensed_returns_409
# ---------------------------------------------------------------------------
def test_verify_already_licensed_provider_returns_409(api):
    """PRD §3.3: "Verifying a provider — permitted only while it is
    `PENDING_VERIFICATION` — moves `license_status` to `LICENSED`"
    PRD §2.9: "For any transition endpoint, the target resource must be in a state from
    which the transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/provider_verify_from_licensed_returns_409
    """
    provider = create_licensed_provider()
    resp = api.license_provider(provider["id"], {"action": "VERIFY"}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: state_machines / provider_renew_after_clock_expiry_relicenses
# ---------------------------------------------------------------------------
def test_renew_after_clock_expiry_relicenses_provider(api):
    """PRD §2.7: "Any `Provider` currently `LICENSED` whose `license_expiry_date` is
    strictly earlier than the new clock time transitions to `EXPIRED`."
    PRD §3.3: "An `EXPIRED` provider can be renewed: supplying a renewal `action`
    together with a fresh `license_expiry_date` that is strictly later than the current
    clock overwrites the stored `license_expiry_date` with the supplied value and
    returns `license_status` to `LICENSED`, closing the expire-and-renew loop."

    Design: Corner/state_machines/provider_renew_after_clock_expiry_relicenses
    """
    provider = create_licensed_provider(license_expiry="2027-01-01T00:00:00Z")
    api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, PA)
    data = validate_success(api.license_provider(
        provider["id"], {"action": "RENEW", "license_expiry_date": "2028-01-01T00:00:00Z"}, PA), 200)
    assert data["license_status"] == "LICENSED"
    assert data["license_expiry_date"].startswith("2028-01-01")
