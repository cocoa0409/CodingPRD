"""Installment agreement state machine: propose, approve, reject, missed-debit loop,
default, and approval-time guards."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_agreement_payload,
    setup_account_with_recomputed_period,
    setup_account_with_period_no_recompute,
    setup_approved_agreement,
    setup_offer_in_evaluating,
    propose_agreement,
    approve_agreement,
    get_account_version,
    set_clock,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]


def test_proposed_agreement_initial_state(api):
    """PRD §3.3: "The agreement is created with its status field set to PROPOSED;
    its setup_fee_cents is not determined at proposal time but at approval".

    Design: Corner/state_machines/initial_state_agreement_is_proposed
    """
    acct, period = setup_account_with_period_no_recompute(clock=None)
    agr = get_success_data(api.create_agreement(
        create_agreement_payload(acct["id"], agreement_type="LONG_TERM",
                                 payment_method="MANUAL", monthly_payment_cents=200000,
                                 term_months=6), OFFICER))
    fetched = validate_success(api.get_agreement(agr["id"], OFFICER), 200)
    assert fetched["status"] == "PROPOSED", fetched
    assert fetched["setup_fee_cents"] == 0, fetched


def test_reject_proposed_agreement_no_period_change(api):
    """PRD §3.4: "Rejecting a proposed agreement, also by a RevenueOfficer, requires
    only that the agreement be in PROPOSED status (otherwise ERR_INVALID_STATE) and
    advances it PROPOSED → REJECTED. Rejection touches no period and opens or closes
    no suspension".

    Design: Corner/state_machines/reject_proposed_agreement_succeeds
    """
    acct, period = setup_account_with_period_no_recompute(clock=None)
    agr = propose_agreement(acct["id"], agreement_type="LONG_TERM",
                            payment_method="MANUAL", monthly_payment_cents=200000,
                            term_months=6)
    rejected = validate_success(api.reject_agreement(agr["id"], OFFICER), 200)
    assert rejected["status"] == "REJECTED", rejected
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["period_status"] == "ASSESSED", p


def test_approve_already_approved_agreement_invalid_state(api):
    """PRD §3.4: "First, the agreement must currently be in PROPOSED status, or the
    request fails the state check with ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_already_approved_agreement_returns_invalid_state
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="MANUAL", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(approved["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_INVALID_STATE")


def test_missed_debit_reinstates_then_defaults(api):
    """PRD §3.5: "If incrementing missed_debit_count leaves it below the threshold of
    2, the agreement stays in force, transitioning APPROVED → REINSTATED".
    PRD §3.5: "If instead the increment brings missed_debit_count to the threshold of
    2 or more, the agreement defaults — APPROVED → DEFAULTED or REINSTATED →
    DEFAULTED".

    Design: Difficulty/non_linear_state_machine/agreement_revision_loop_reinstated_then_defaulted
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    first = validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    assert first["status"] == "REINSTATED", first
    assert first["missed_debit_count"] == 1, first

    second = validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    assert second["status"] == "DEFAULTED", second
    assert second["missed_debit_count"] == 2, second


def test_agreement_default_closes_csed_and_drops_protection(api):
    """PRD §3.5: "the CSED suspension interval on every IN_COLLECTION period is closed
    (each appending a CSED_SUSPEND_END event carrying its suspension_days, those days
    added to the period's csed_date), the account's csed_protection_count is driven to
    zero".

    Design: Difficulty/transitive_cascade/agreement_default_depth3_csed_close_extend_protection_drop
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    period_before = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    csed_before = period_before["csed_date"]

    # Advance the clock so the auto-opened CSED suspension interval spans a positive
    # number of days; on default the closed interval folds those days into csed_date.
    set_clock("2024-07-15T00:00:00.000Z")

    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)  # -> REINSTATED
    defaulted = validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    assert defaulted["status"] == "DEFAULTED", defaulted

    acct_after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert acct_after["csed_protection_count"] == 0, acct_after

    period_after = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert period_after["csed_date"] > csed_before, (period_after["csed_date"], csed_before)


def test_approve_conflicting_resolution_masks_short_term_too_long(api):
    """PRD §3.4: "Next comes the conflicting-resolution check: the account must have
    no other InstallmentAgreement whose status is APPROVED or REINSTATED ... a
    violation is rejected with ERR_CONFLICTING_RESOLUTION."
    PRD §3.4: "Then the short-term length check: a SHORT_TERM agreement must have
    term_months no greater than 6, or it is rejected with ERR_SHORT_TERM_TOO_LONG."

    Design: Difficulty/priority_pair_validation_conflict/conflicting_resolution_vs_short_term_too_long_on_approve
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="MANUAL", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    # second agreement: SHORT_TERM term_months=12 (>6) on an account already holding
    # an APPROVED agreement.
    agr2 = propose_agreement(
        acct["id"], agreement_type="SHORT_TERM", payment_method="MANUAL",
        monthly_payment_cents=2000000, term_months=12,
        active_from="2025-01-15T00:00:00.000Z", active_to="2026-01-15T00:00:00.000Z")
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr2["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_CONFLICTING_RESOLUTION")


def test_approve_blocked_by_open_oic(api):
    """PRD §3.4: "the account must have ... no OfferInCompromise whose status is
    SUBMITTED, EVALUATING, or ACCEPTED; a violation is rejected with
    ERR_CONFLICTING_RESOLUTION."

    Design: Difficulty/cross_entity_state_dependency/agreement_approve_blocked_by_open_oic
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000, recompute=True)
    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_CONFLICTING_RESOLUTION")


def test_agreement_window_buffer_overlap_rejected(api):
    """PRD §3.4: "the proposed closed interval from active_from through active_to must
    be separated by at least the agreement buffer of 30 days from the recorded window
    of every other agreement on the same account whose status is APPROVED, REINSTATED,
    or DEFAULTED — a defaulted agreement's window remains a recorded statute occupation
    — and any touching, overlapping, or within-buffer window is rejected with
    ERR_AGREEMENT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/agreement_active_window_buffer_overlap_rejected
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6,
        active_from="2024-04-15T00:00:00.000Z", active_to="2024-10-15T00:00:00.000Z")
    # Default agr1 (2 missed debits) so the conflicting-resolution check passes, but
    # its [2024-04-15, 2024-10-15] window remains a recorded occupation.
    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)

    agr2 = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6,
        active_from="2024-09-01T00:00:00.000Z", active_to="2025-03-01T00:00:00.000Z")
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr2["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_AGREEMENT_WINDOW_OVERLAP")


def test_ppia_full_payoff_shape_rejected(api):
    """PRD §3.4: "for PPIA, that product must be strictly less than the account's
    total_balance_cents (partial by design); a violation yields
    ERR_PAYOFF_SHAPE_INVALID."

    Design: Corner/validations/ppia_payoff_shape_rejected_when_full_payoff
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    # monthly 200000 * 6 = 1200000 >= balance 1033000 -> wrong for PPIA
    agr = propose_agreement(
        acct["id"], agreement_type="PPIA", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_PAYOFF_SHAPE_INVALID")


def test_first_missed_debit_increments_count_without_csed_change(api):
    """PRD §3.5: "This below-threshold path is the revision loop, distinct from
    default. ... there is no CSED change and the agreement remains protective."
    PRD §3.5: "In all cases the system increments missed_debit_count by one".

    Design: Difficulty/non_linear_state_machine/agreement_revision_loop_reinstated_then_defaulted
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    protection_before = validate_success(
        api.get_tax_account(acct["id"], OFFICER), 200)["csed_protection_count"]
    first = validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    assert first["status"] == "REINSTATED", first
    assert first["missed_debit_count"] == 1, first
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["csed_protection_count"] == protection_before, a


def test_agreement_default_recomputes_collection_status_active(api):
    """PRD §3.5: "and the account's collection_status is recomputed to
    ACTIVE_COLLECTION."

    Design: Difficulty/transitive_cascade/agreement_default_depth3_csed_close_extend_protection_drop
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6)
    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    defaulted = validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    assert defaulted["status"] == "DEFAULTED", defaulted
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["collection_status"] == "ACTIVE_COLLECTION", a


def test_short_term_too_long_alone_rejected(api):
    """PRD §3.4: "Then the short-term length check: a SHORT_TERM agreement must have
    term_months no greater than 6, or it is rejected with ERR_SHORT_TERM_TOO_LONG."

    Design: Difficulty/priority_pair_validation_conflict/conflicting_resolution_vs_short_term_too_long_on_approve
    """
    # Isolated: no conflicting agreement on the account, only the SHORT_TERM length
    # violation can fire (full-payoff shape satisfied: 2000000*12 >= balance).
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    agr = propose_agreement(
        acct["id"], agreement_type="SHORT_TERM", payment_method="MANUAL",
        monthly_payment_cents=2000000, term_months=12)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_SHORT_TERM_TOO_LONG")


def test_approve_blocked_while_oic_submitted(api):
    """PRD §3.4: "the account must have ... no OfferInCompromise whose status is
    SUBMITTED, EVALUATING, or ACCEPTED; a violation is rejected with
    ERR_CONFLICTING_RESOLUTION."

    Design: Difficulty/cross_entity_state_dependency/agreement_approve_blocked_by_open_oic
    """
    from test_helpers import submit_offer
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    # OIC left in SUBMITTED (not yet EVALUATING) — still blocks approval.
    submit_offer(acct["id"], 18500000, net_realizable_equity_cents=500000)
    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_CONFLICTING_RESOLUTION")


def test_agreement_window_touching_buffer_rejected(api):
    """PRD §3.4: "any touching, overlapping, or within-buffer window is rejected with
    ERR_AGREEMENT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/agreement_active_window_buffer_overlap_rejected
    """
    acct, period, approved = setup_approved_agreement(
        payment_method="DIRECT_DEBIT", agreement_type="LONG_TERM",
        monthly_payment_cents=200000, term_months=6,
        active_from="2024-04-15T00:00:00.000Z", active_to="2024-10-15T00:00:00.000Z")
    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)
    validate_success(api.record_missed_debit(approved["id"], OFFICER), 200)  # DEFAULTED
    # second window starts within 30 days of the recorded [.., 2024-10-15] window
    agr2 = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6,
        active_from="2024-10-20T00:00:00.000Z", active_to="2025-04-20T00:00:00.000Z")
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr2["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_AGREEMENT_WINDOW_OVERLAP")
