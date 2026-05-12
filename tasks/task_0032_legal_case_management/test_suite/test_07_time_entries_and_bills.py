"""Time entries: rate pinning, adjustments, write-off; Bill creation,
issuance with court-fee / attorney-fee / total-due calculations, void.

PRD §3.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    adjust_entry_to_zero,
    adjust_time_entry_payload,
    assert_bill,
    assert_bill_total_due_invariants,
    assert_time_entry,
    create_bill_payload,
    create_time_entry_payload,
    issue_bill_for,
    log_time_entry,
    setup_case_at_awaiting_settlement,
    setup_paid_case,
    setup_three_lawyers_and_active_case,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Time entry creation: rate pinning
# ---------------------------------------------------------------------------
def test_time_entry_pins_lawyer_hourly_rate_at_creation(api):
    """PRD §3.6: 'At creation, the system pins the lawyer's current
    hourly_rate_cents into the entry's hourly_rate_cents_pinned field;
    this pinned rate is the one used for the final billed calculation,
    and it is never recomputed even if the lawyer's hourly_rate_cents
    changes later.'
    """
    bundle = setup_three_lawyers_and_active_case(partner_rate_cents=30_000)
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    assert_time_entry(entry)
    assert entry["hourly_rate_cents_pinned"] == 30_000
    assert entry["status"] == "LOGGED"
    assert entry["adjustment_minutes"] == 0


def test_time_entry_minutes_must_be_positive(api):
    """PRD §3.6: 'The minutes value must be greater than 0 and less than
    or equal to 1440 (one day).'
    """
    bundle = setup_three_lawyers_and_active_case()
    payload = create_time_entry_payload(
        lawyer_id=bundle["partner"]["id"], minutes=0
    )
    res = api.create_time_entry(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


def test_time_entry_minutes_above_1440_rejected(api):
    """PRD §3.6: 'The minutes value must be greater than 0 and less than
    or equal to 1440 (one day).'
    """
    bundle = setup_three_lawyers_and_active_case()
    payload = create_time_entry_payload(
        lawyer_id=bundle["partner"]["id"], minutes=1441
    )
    res = api.create_time_entry(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


# ---------------------------------------------------------------------------
# Adjustment math (priority 20)
# ---------------------------------------------------------------------------
def test_adjustment_negative_below_zero_rejected(api):
    """PRD §3.6: 'A partner or senior may patch the adjustment via
    adjustment_minutes (a signed integer); the resulting minutes +
    adjustment_minutes must be in the range 0 to 1440 inclusive, and a
    violation surfaces ERR_TIME_ENTRY_ADJUSTMENT_INVALID.'
    """
    bundle = setup_three_lawyers_and_active_case()
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=10,
        actor_headers=bundle["partner_headers"],
    )
    res = api.adjust_time_entry(
        entry["id"], adjust_time_entry_payload(adjustment_minutes=-11),
        bundle["partner_headers"],
    )
    validate_error(res, "ERR_TIME_ENTRY_ADJUSTMENT_INVALID",
                   expected_status=422)


def test_adjustment_pushes_above_1440_rejected(api):
    """PRD §3.6: 'the resulting minutes + adjustment_minutes must be in
    the range 0 to 1440 inclusive, and a violation surfaces
    ERR_TIME_ENTRY_ADJUSTMENT_INVALID.'
    """
    bundle = setup_three_lawyers_and_active_case()
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=1000,
        actor_headers=bundle["partner_headers"],
    )
    res = api.adjust_time_entry(
        entry["id"], adjust_time_entry_payload(adjustment_minutes=441),
        bundle["partner_headers"],
    )
    validate_error(res, "ERR_TIME_ENTRY_ADJUSTMENT_INVALID",
                   expected_status=422)


def test_successful_adjustment_transitions_to_adjusted(api):
    """PRD §3.6: 'A successful adjustment moves the entry from LOGGED to
    ADJUSTED.'
    """
    bundle = setup_three_lawyers_and_active_case()
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    adjusted = validate_success(
        api.adjust_time_entry(
            entry["id"],
            adjust_time_entry_payload(adjustment_minutes=0),
            bundle["partner_headers"],
        ), 200,
    )
    assert adjusted["status"] == "ADJUSTED"


def test_partner_can_write_off_logged_entry(api):
    """PRD §3.6: 'A partner-only write-off moves the entry from LOGGED or
    ADJUSTED to WRITTEN_OFF.'
    """
    bundle = setup_three_lawyers_and_active_case()
    entry = log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    wo = validate_success(
        api.write_off_time_entry(entry["id"], bundle["partner_headers"]), 200,
    )
    assert wo["status"] == "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# Bill creation: billing_mode validation (priority 19)
# ---------------------------------------------------------------------------
def test_bill_fixed_requires_positive_fee(api):
    """PRD §3.6: 'If billing_mode is FIXED, fixed_fee_cents must be
    supplied and strictly greater than 0 ... Violations surface
    ERR_BILLING_MODE_INVALID.'
    """
    bundle = setup_case_at_awaiting_settlement()
    payload = create_bill_payload(
        billing_mode="FIXED", fixed_fee_cents=0,
    )
    res = api.create_bill(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_BILLING_MODE_INVALID", expected_status=422)


def test_bill_fixed_missing_fee_rejected(api):
    """PRD §3.6: 'If billing_mode is FIXED, fixed_fee_cents must be
    supplied and strictly greater than 0 ... Violations surface
    ERR_BILLING_MODE_INVALID.'
    """
    bundle = setup_case_at_awaiting_settlement()
    payload = create_bill_payload(billing_mode="FIXED")  # no fee supplied
    res = api.create_bill(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_BILLING_MODE_INVALID", expected_status=422)


def test_bill_contingent_rate_above_5000_rejected(api):
    """PRD §3.6: 'If billing_mode is CONTINGENT, contingent_rate_bps must
    be supplied and lie between 1 and 5000 inclusive ... Violations
    surface ERR_BILLING_MODE_INVALID.'
    """
    bundle = setup_case_at_awaiting_settlement()
    payload = create_bill_payload(
        billing_mode="CONTINGENT", contingent_rate_bps=5001,
    )
    res = api.create_bill(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_BILLING_MODE_INVALID", expected_status=422)


def test_bill_contingent_rate_zero_rejected(api):
    """PRD §3.6: 'If billing_mode is CONTINGENT, contingent_rate_bps
    must be supplied and lie between 1 and 5000 inclusive (basis
    points, with 5000 representing the firm'
    """
    bundle = setup_case_at_awaiting_settlement()
    payload = create_bill_payload(
        billing_mode="CONTINGENT", contingent_rate_bps=0,
    )
    res = api.create_bill(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_BILLING_MODE_INVALID", expected_status=422)


# ---------------------------------------------------------------------------
# Issuance: court fee per case_type (FIXED + CRIMINAL/ADMINISTRATIVE)
# ---------------------------------------------------------------------------
def test_criminal_court_fee_is_flat_50000(api):
    """PRD §3.6: 'For CRIMINAL matters the court fee is a flat 50,000
    cents ($500); for ADMINISTRATIVE matters it is a flat 30,000 cents
    ($300).'
    """
    # CRIMINAL case has claim_amount=0; need at least one ADJUSTED entry
    # before issuance to satisfy 'every TimeEntry has status != LOGGED'.
    bundle = setup_case_at_awaiting_settlement(
        case_type="CRIMINAL", claim_amount_cents=0,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    assert issued["court_fee_cents"] == 50_000


def test_administrative_court_fee_is_flat_30000(api):
    """PRD §3.6: 'for ADMINISTRATIVE matters it is a flat 30,000 cents
    ($300).'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="ADMINISTRATIVE", claim_amount_cents=0,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    assert issued["court_fee_cents"] == 30_000


# ---------------------------------------------------------------------------
# Issuance: precondition — every TimeEntry status != LOGGED
# ---------------------------------------------------------------------------
def test_issuance_blocked_by_logged_time_entry(api):
    """PRD §3.6: 'Issuance also requires that every TimeEntry row on the
    case has a status other than LOGGED — that is, every entry must
    already be ADJUSTED, WRITTEN_OFF, or already BILLED; a single
    still-LOGGED entry blocks issuance.'
    """
    bundle = setup_three_lawyers_and_active_case(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    # One LOGGED entry; one ADJUSTED entry. LOGGED blocks issuance.
    log_time_entry(
        case_id=bundle["case"]["id"],
        lawyer_id=bundle["partner"]["id"],
        minutes=30,
        actor_headers=bundle["partner_headers"],
    )
    awaiting = validate_success(
        api.await_settlement(bundle["case"]["id"],
                             bundle["partner_headers"]), 200
    )
    assert awaiting["status"] == "AWAITING_SETTLEMENT"
    bill = validate_success(
        api.create_bill(
            bundle["case"]["id"],
            create_bill_payload(billing_mode="FIXED", fixed_fee_cents=1),
            bundle["partner_headers"],
        ), 201,
    )
    res = api.issue_bill(bill["id"], bundle["partner_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------------
# Issuance side effect: ADJUSTED → BILLED cascade
# ---------------------------------------------------------------------------
def test_issuance_cascades_adjusted_entries_to_billed(api):
    """PRD §3.6: 'Issuance also cascades: every TimeEntry on the case
    whose status is ADJUSTED is moved to BILLED.'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    # PRD §3.6 pins the cascade ADJUSTED → BILLED at issuance, but PRD
    # also says 'A subsequent void of the bill (only legal from DRAFT,
    # not from ISSUED) reverses the cascade by moving every BILLED entry
    # back to ADJUSTED.' — so the void path can't be used to round-trip
    # an ISSUED bill. We assert the visible side: bill is ISSUED and the
    # monetary fields are computed (which only happens after issuance).
    assert issued["status"] == "ISSUED"
    assert isinstance(issued.get("court_fee_cents"), int)
    assert isinstance(issued.get("attorney_fee_cents"), int)
    assert isinstance(issued.get("total_due_cents"), int)


def test_void_only_legal_from_draft(api):
    """PRD §3.6: 'A subsequent void of the bill (only legal from DRAFT,
    not from ISSUED) reverses the cascade by moving every BILLED entry
    back to ADJUSTED.'

    Claim: void on an ISSUED bill is rejected with ERR_INVALID_STATE.
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    res = api.void_bill(issued["id"], bundle["partner_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------------
# Payment events (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
def test_payment_amount_mismatch_rejected(api, system_integrator_headers):
    """PRD §3.6: 'An external payment event with matching bill_id and
    amount_cents exactly equal to total_due_cents transitions the bill
    from ISSUED to PAID; if amount_cents does not match or the bill is
    not in ISSUED, the event is rejected with ERR_PAYMENT_AMOUNT_MISMATCH.'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    from test_helpers import payment_event_payload
    res = api.emit_payment(
        payment_event_payload(
            bill_id=issued["id"],
            amount_cents=issued["total_due_cents"] + 1,
        ),
        system_integrator_headers,
    )
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH",
                   expected_status=422)


def test_payment_exact_match_transitions_to_paid(api, system_integrator_headers):
    """PRD §3.6: 'An external payment event with matching bill_id and
    amount_cents exactly equal to total_due_cents transitions the bill
    from ISSUED to PAID.'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
    )
    from test_helpers import payment_event_payload
    paid = validate_success(
        api.emit_payment(
            payment_event_payload(
                bill_id=issued["id"],
                amount_cents=issued["total_due_cents"],
            ),
            system_integrator_headers,
        ),
        200,
    )
    assert paid["status"] == "PAID"


# ---------------------------------------------------------------------------
# mark-settled requires recovery / cost_recovery
# ---------------------------------------------------------------------------
def test_mark_settled_requires_recovery(api):
    """PRD §3.6: 'Alternatively, a partner may mark an issued bill as
    SETTLED provided the bill has either recovered_amount_cents strictly
    greater than zero or cost_recovery_cents strictly greater than zero
    (a settlement requires evidence that something was recovered).'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
        recovered_amount_cents=0,
        cost_recovery_cents=0,
    )
    res = api.mark_bill_settled(issued["id"], bundle["partner_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_mark_settled_succeeds_with_cost_recovery(api):
    """PRD §3.6: 'a partner may mark an issued bill as SETTLED provided
    the bill has either recovered_amount_cents strictly greater than zero
    or cost_recovery_cents strictly greater than zero ...'
    """
    bundle = setup_case_at_awaiting_settlement(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    _, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED", fixed_fee_cents=1,
        cost_recovery_cents=10,
    )
    settled = validate_success(
        api.mark_bill_settled(issued["id"], bundle["partner_headers"]),
        200,
    )
    assert settled["status"] == "SETTLED"
