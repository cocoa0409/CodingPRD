"""Validation-priority conflicts, resource/temporal overlap, and the
operation-specific business validations.

Covers difficulty instances invalid_state_beats_election_window_closed,
refund_exceeds_credit_beats_stale_version,
duplicate_invoice_same_coverage_month_point_overlap,
overlapping_subsidy_grants_range_first_match, and corner validation instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_invoice_payload, create_subsidy_payload, refund_payload,
    apply_disability_extension_payload, terminate_early_payload,
    TEST_USERS, make_beneficiary_headers,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_invalid_state_beats_election_window_closed(api):
    """PRD §2.9: "the target resource being in a state that permits the requested
    transition (ERR_INVALID_STATE). Only after all of these pass does the system
    evaluate the operation-specific business rules described in Section 3
    (eligibility, window, fiscal, and concurrency checks)."
    PRD §3.4: "Election is permitted only while the notice is OUTSTANDING — an
    already-elected or expired notice is rejected with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_election_window_closed
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])  # deadline 2026-05-31
    notice = fx.send_notice(event["id"])
    fx.set_clock("2026-04-10T00:00:00.000Z")
    api.elect(notice["id"], make_beneficiary_headers(ben["id"]))  # notice now ELECTED
    fx.set_clock("2026-06-05T00:00:00.000Z")  # also past deadline
    # Both ERR_INVALID_STATE (already elected) and window-closed could apply;
    # the state check (priority 6) masks the window check (a §3 business rule).
    resp = api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    validate_error(resp, "ERR_INVALID_STATE")


def test_already_elected_notice_reelection_rejected_within_window(api):
    """PRD §3.4: "Election is permitted only while the notice is OUTSTANDING — an
    already-elected or expired notice is rejected with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_election_window_closed
    """
    # The state check fires in isolation (clock still inside the window, so the
    # window rule cannot fire): a second elect on an ELECTED notice is
    # ERR_INVALID_STATE, confirming the state leg of the conflict is genuine.
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])  # deadline 2026-05-31
    notice = fx.send_notice(event["id"])
    fx.set_clock("2026-04-10T00:00:00.000Z")
    api.elect(notice["id"], make_beneficiary_headers(ben["id"]))  # ELECTED
    # Clock still 2026-04-10, inside the window; only the state rule can fail.
    resp = api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    validate_error(resp, "ERR_INVALID_STATE")


def test_refund_exceeds_credit_beats_stale_version(api):
    """PRD §3.11: "A refund requires a positive credit balance; against a zero
    balance it is rejected with ERR_NO_CREDIT_BALANCE. The refund_amount_cents
    must not exceed the account's current credit_balance_cents, or the request is
    rejected with ERR_REFUND_EXCEEDS_CREDIT. And the expected_account_version
    must match the account's current version, or the request is rejected with
    ERR_STALE_VERSION."

    Design: Difficulty/priority_pair_validation_conflict/refund_exceeds_credit_beats_stale_version
    """
    ctx = fx.setup_overpaid_account(payment_cents=70000)  # credit 8800
    acct_id = ctx["account"]["id"]
    stale_version = fx.account_version(acct_id)
    # First refund advances the version, leaving credit 3800.
    fx.issue_refund(acct_id, 5000, stale_version)
    # Trigger refund: 9000 > credit 3800 AND stale version. Fiscal precedes OCC.
    resp = api.refund(acct_id, refund_payload(9000, stale_version), _BILLING)
    validate_error(resp, "ERR_REFUND_EXCEEDS_CREDIT")


def test_refund_within_credit_but_stale_version_yields_stale_version(api):
    """PRD §3.11: "And the expected_account_version must match the account's
    current version, or the request is rejected with ERR_STALE_VERSION."

    Design: Difficulty/priority_pair_validation_conflict/refund_exceeds_credit_beats_stale_version
    """
    # The OCC leg fires in isolation: a refund that is within the credit balance
    # but carries a stale version returns ERR_STALE_VERSION — confirming the OCC
    # check is the loser only when the fiscal check also fails.
    ctx = fx.setup_overpaid_account(payment_cents=70000)  # credit 8800
    acct_id = ctx["account"]["id"]
    stale_version = fx.account_version(acct_id)
    fx.issue_refund(acct_id, 5000, stale_version)  # advances version, credit 3800
    # 2000 <= credit 3800 (fiscal ok) but version is stale -> OCC fires alone.
    resp = api.refund(acct_id, refund_payload(2000, stale_version), _BILLING)
    validate_error(resp, "ERR_STALE_VERSION")


def test_duplicate_invoice_same_coverage_month_rejected(api):
    """PRD §3.5: "An account may hold only one invoice per coverage month; a
    second invoice for an already-invoiced month is rejected with
    ERR_DUPLICATE_INVOICE."

    Design: Difficulty/resource_temporal_overlap/duplicate_invoice_same_coverage_month_point_overlap
    """
    ctx = fx.setup_elected_enrollment()
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-04")  # first April invoice
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04"), _BILLING)
    validate_error(resp, "ERR_DUPLICATE_INVOICE")


def test_overlapping_subsidy_grants_chronological_first_wins(api):
    """PRD §3.7: "When two ACTIVE grants overlap the same month, the earliest by
    start_month then created_at wins and the later overlapping grant is ignored
    for that month."

    Design: Difficulty/resource_temporal_overlap/overlapping_subsidy_grants_range_first_match
    """
    ctx = fx.setup_active_enrollment()  # April paid
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    fx.grant_subsidy(enr_id, 0.65, "2026-05", "2026-12")   # created first
    fx.grant_subsidy(enr_id, 1.0, "2026-05", "2026-06")    # created second, same start
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-05"), _BILLING)
    inv = validate_success(resp, 201)
    # 65% grant wins: 39780 applied, owed 21420 (not the 100% grant).
    assert inv["subsidy_applied_cents"] == 39780, f"subsidy {inv['subsidy_applied_cents']}"
    assert inv["beneficiary_owed_cents"] == 21420, f"owed {inv['beneficiary_owed_cents']}"


def test_distinct_coverage_month_invoice_accepted(api):
    """PRD §3.5: "An account may hold only one invoice per coverage month; a
    second invoice for an already-invoiced month is rejected with
    ERR_DUPLICATE_INVOICE."

    Design: Difficulty/resource_temporal_overlap/duplicate_invoice_same_coverage_month_point_overlap
    """
    # Point-overlap is exact-month equality: a different (adjacent) month does
    # NOT collide, so an April invoice followed by a May invoice both succeed.
    ctx = fx.setup_active_enrollment()  # April invoiced+paid
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-05"), _BILLING)
    inv = validate_success(resp, 201)
    assert inv["coverage_month"] == "2026-05", f"coverage_month {inv['coverage_month']}"
    assert inv["coverage_month_index"] == 2, f"index {inv['coverage_month_index']}"


def test_month_outside_later_grant_uses_chronological_first_grant(api):
    """PRD §3.7: "the system orders the enrollment's ACTIVE grants by start_month
    ascending and then by created_at ascending, and selects the first grant in
    that order whose inclusive start_month-through-end_month range contains the
    month."

    Design: Difficulty/resource_temporal_overlap/overlapping_subsidy_grants_range_first_match
    """
    # grant1 65% 2026-05..2026-12 (created first), grant2 100% 2026-05..2026-06.
    # July is inside grant1 only; the chronological-first/range-matching grant1
    # applies its 65% (39780) for July.
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    fx.grant_subsidy(enr_id, 0.65, "2026-05", "2026-12")
    fx.grant_subsidy(enr_id, 1.0, "2026-05", "2026-06")
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-07"), _BILLING)
    inv = validate_success(resp, 201)
    assert inv["subsidy_applied_cents"] == 39780, f"July subsidy {inv['subsidy_applied_cents']}"
    assert inv["beneficiary_owed_cents"] == 21420, f"July owed {inv['beneficiary_owed_cents']}"


def test_disability_extension_on_36_month_enrollment_rejected(api):
    """PRD §3.8: "the extension applies only to a base 18-month enrollment — one
    whose base_max_months is 18; a 36-month enrollment cannot extend, and an
    attempt to extend it is rejected with ERR_EXTENSION_NOT_APPLICABLE."

    Design: Corner/validations/disability_extension_on_36mo_returns_not_applicable
    """
    # DIVORCE -> 36-month enrollment. coverage_loss 2026-05-01, May paid -> ACTIVE.
    ctx = fx.setup_active_enrollment(
        event_type="DIVORCE", relationship="SPOUSE",
        coverage_loss_date="2026-05-01T00:00:00.000Z",
        notice_clock="2026-04-20T00:00:00.000Z",
        elect_clock="2026-05-10T00:00:00.000Z",
        first_month="2026-05",
    )
    enr_id = ctx["enrollment"]["id"]
    fx.set_clock("2026-05-20T00:00:00.000Z")
    resp = api.apply_disability_extension(
        enr_id, apply_disability_extension_payload("2026-05-20T00:00:00.000Z"), _ADMIN
    )
    validate_error(resp, "ERR_EXTENSION_NOT_APPLICABLE")


def test_disability_determination_outside_window_rejected(api):
    """PRD §3.8: "First, the determination must fall within the first 60 days of
    coverage — determination_date on or after the coverage_start_date and on or
    before the coverage_start_date plus 60 days."
    PRD §3.8: "A determination outside the first-60-days window, or an
    application made after the 18-month scheduled end, is rejected with
    ERR_DISABILITY_WINDOW_INVALID."

    Design: Corner/validations/disability_determination_outside_window_returns_window_invalid
    """
    ctx = fx.setup_active_enrollment()  # coverage_start 2026-04-01, +60 = 2026-05-31
    enr_id = ctx["enrollment"]["id"]
    fx.set_clock("2026-07-05T00:00:00.000Z")
    resp = api.apply_disability_extension(
        enr_id, apply_disability_extension_payload("2026-07-01T00:00:00.000Z"), _ADMIN
    )
    validate_error(resp, "ERR_DISABILITY_WINDOW_INVALID")


def test_terminate_early_with_system_only_reason_rejected(api):
    """PRD §3.9: "The reason must be one of OTHER_GROUP_COVERAGE,
    MEDICARE_ENTITLEMENT, or PLAN_TERMINATED; any other reason is rejected with
    ERR_INVALID_TERMINATION_REASON."

    Design: Corner/validations/terminate_early_invalid_reason_returns_invalid_reason
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    resp = api.terminate_early(enr_id, terminate_early_payload("RUN_TO_TERM"), _ADMIN)
    validate_error(resp, "ERR_INVALID_TERMINATION_REASON")


def test_subsidy_inverted_range_rejected(api):
    """PRD §3.7: "The range must satisfy start_month on or before end_month and
    must fall within the enrollment's coverage interval; a reversed or
    out-of-interval range is rejected with ERR_INVALID_SUBSIDY_RANGE."

    Design: Corner/validations/subsidy_range_inverted_returns_invalid_range
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    resp = api.create_subsidy(enr_id, create_subsidy_payload(0.65, "2026-08", "2026-05"), _ADMIN)
    validate_error(resp, "ERR_INVALID_SUBSIDY_RANGE")


def test_payment_with_no_open_invoice_rejected(api):
    """PRD §3.6: "The targeted month must already have an OPEN invoice on the
    account, or the payment is rejected with ERR_NO_OPEN_INVOICE."

    Design: Corner/validations/payment_no_open_invoice_returns_no_open_invoice
    """
    ctx = fx.setup_active_enrollment()  # April invoiced+paid; no May invoice
    acct_id = ctx["account"]["id"]
    from test_helpers import create_payment_payload
    resp = api.create_payment(acct_id, create_payment_payload(61200, "2026-05"), _BILLING)
    validate_error(resp, "ERR_NO_OPEN_INVOICE")
