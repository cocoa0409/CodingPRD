"""CSED suspension geometry & conservation, CSED sweep boundary, lien release
cross-entity guard, and payment allocation."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_csed_suspension_payload,
    setup_account_with_recomputed_period,
    setup_account_with_period_no_recompute,
    setup_lien_release_pending,
    open_suspension,
    close_suspension,
    post_payment,
    create_period,
    create_account,
    set_clock,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]


def test_csed_suspension_overlap_open_interval_rejected(api):
    """PRD §3.2: "A new interval is rejected with ERR_OVERLAPPING_SUSPENSION if its
    span overlaps any still-open interval (one whose end_at is null) on the same
    period".

    Design: Difficulty/resource_temporal_overlap/csed_suspension_open_interval_overlap_rejected
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    open_suspension(period["id"], "2024-04-15T00:00:00.000Z", reason="MANUAL")
    res = api.create_csed_suspension(
        create_csed_suspension_payload(period["id"], reason="MANUAL",
                                       start_at="2024-05-01T00:00:00.000Z"), OFFICER)
    validate_error(res, "ERR_OVERLAPPING_SUSPENSION")


def test_csed_suspension_adjacent_interval_allowed(api):
    """PRD §3.2: "adjacency is permitted — a new interval whose start_at exactly equals
    a prior interval's end_at does not overlap and is allowed."

    Design: Corner/state_machines/csed_suspension_adjacent_interval_allowed
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    susp1 = open_suspension(period["id"], "2024-01-15T00:00:00.000Z", reason="MANUAL")
    close_suspension(susp1["id"], "2024-04-15T00:00:00.000Z")
    res = api.create_csed_suspension(
        create_csed_suspension_payload(period["id"], reason="MANUAL",
                                       start_at="2024-04-15T00:00:00.000Z"), OFFICER)
    susp2 = validate_success(res, 201)
    assert susp2["end_at"] is None, susp2


def test_csed_day_conservation_on_suspension_close(api):
    """PRD §3.2: "On close, the system fixes end_at, computes days_counted as the
    whole number of days from start_at to end_at, adds those days to the linked
    period's csed_date, decrements the account's csed_protection_count by one".
    PRD §3.1: "the assessment date plus 3,653 base days plus the sum of suspension_days
    across all closed suspension intervals recorded for that period."

    Design: Difficulty/compensating_invariant/csed_day_conservation_on_suspension_close
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    susp = open_suspension(period["id"], "2024-01-15T00:00:00.000Z", reason="MANUAL")
    closed = close_suspension(susp["id"], "2024-04-15T00:00:00.000Z")
    assert closed["days_counted"] == 91, closed

    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["csed_date"][:10] == "2034-04-16", p

    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["csed_protection_count"] == 0, a


def test_csed_sweep_at_exact_expiration_writes_off(api):
    """PRD §3.11: "each IN_COLLECTION period whose csed_date is on or before the
    current UTC instant and whose balance_due_cents is greater than zero transitions
    IN_COLLECTION → WRITTEN_OFF, its balance zeroed".

    Design: Difficulty/boundary_precision_check/csed_sweep_at_exact_expiration_writes_off_boundary
    """
    set_clock("2010-01-15T00:00:00.000Z")
    acct = create_account(monthly_disposable_income_cents=300000)
    period = create_period(acct["id"], assessed_tax_cents=1000000,
                           assessment_date="2010-01-15T00:00:00.000Z", tax_year=2009)
    # a payment posts so the period is IN_COLLECTION with positive balance
    post_payment(acct["id"], 100, payment_source="MANUAL", tax_period_id=period["id"])
    set_clock("2020-01-16T00:00:00.000Z")  # csed_date == now exactly

    swept = validate_success(api.sweep_expired_csed(acct["id"], OFFICER), 200)
    assert swept["total_balance_cents"] == 0, swept

    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["period_status"] == "WRITTEN_OFF", p
    assert p["balance_due_cents"] == 0, p


def test_sweep_with_nothing_expired_returns_error(api):
    """PRD §3.11: "If the sweep finds no period meeting both conditions (a passed
    csed_date and a positive balance), it returns ERR_NOTHING_TO_SWEEP."

    Design: Corner/state_machines/sweep_with_nothing_expired_returns_error
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=0)
    res = api.sweep_expired_csed(acct["id"], OFFICER)
    validate_error(res, "ERR_NOTHING_TO_SWEEP")


def test_lien_release_succeeds_when_balance_zero(api):
    """PRD §3.10: "the account's total_balance_cents is zero, or the account has an
    InstallmentAgreement whose status is APPROVED or REINSTATED with payment_method of
    DIRECT_DEBIT. If neither condition holds, the release is blocked with
    ERR_LIEN_RELEASE_BLOCKED. On approval the system sets released_at to the current
    server time".

    Design: Difficulty/cross_entity_state_dependency/lien_release_depends_on_account_balance
    """
    acct, period, lien = setup_lien_release_pending(
        filed_amount_cents=1000000, assessed_tax_cents=1000000,
        assessment_date="2024-01-15T00:00:00.000Z", clock="2024-04-15T00:00:00.000Z")
    # full payment drives balance to 0
    post_payment(acct["id"], 1033000, payment_source="MANUAL", tax_period_id=period["id"])
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["total_balance_cents"] == 0, a

    released = validate_success(api.approve_lien_release(lien["id"], REVIEWER), 200)
    assert released["status"] == "RELEASED", released
    assert released["released_at"] is not None, released


def test_lien_release_blocked_when_balance_positive(api):
    """PRD §3.10: "If neither condition holds, the release is blocked with
    ERR_LIEN_RELEASE_BLOCKED."

    Design: Corner/validations/lien_release_blocked_when_balance_positive
    """
    acct, period, lien = setup_lien_release_pending(
        filed_amount_cents=1000000, assessed_tax_cents=1000000,
        assessment_date="2024-01-15T00:00:00.000Z", clock="2024-04-15T00:00:00.000Z",
        mdi_cents=0)
    res = api.approve_lien_release(lien["id"], REVIEWER)
    validate_error(res, "ERR_LIEN_RELEASE_BLOCKED")


def test_withdrawn_lien_cannot_request_release(api):
    """PRD §3.10: "The same officer may request its release, advancing the lien
    FILED → RELEASE_PENDING (precondition: FILED, else ERR_INVALID_STATE)".

    Design: Corner/state_machines/terminal_lien_withdrawn_cannot_request_release
    """
    acct = create_account(monthly_disposable_income_cents=0)
    from test_helpers import create_lien_payload
    lien = get_success_data(api.create_lien(create_lien_payload(acct["id"], filed_amount_cents=500000), OFFICER))
    validate_success(api.withdraw_lien(lien["id"], REVIEWER), 200)
    res = api.request_lien_release(lien["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE")


def test_payment_allocation_oldest_first_across_periods(api):
    """PRD §3.8: "it orders the target periods by assessment_date ascending, breaking
    ties by created_at ascending (never by id), considering only periods whose
    period_status is ASSESSED or IN_COLLECTION."
    PRD §3.8: "A period whose balance_due_cents reaches zero transitions
    IN_COLLECTION → SATISFIED".

    Design: Corner/calculations/payment_allocation_oldest_first_across_periods
    """
    set_clock("2022-01-01T00:00:00.000Z")
    acct = create_account(monthly_disposable_income_cents=0)
    period_a = create_period(acct["id"], assessed_tax_cents=600000,
                             assessment_date="2020-01-01T00:00:00.000Z", tax_year=2019)
    period_b = create_period(acct["id"], assessed_tax_cents=400000,
                             assessment_date="2022-01-01T00:00:00.000Z", tax_year=2021)
    post_payment(acct["id"], 700000, payment_source="MANUAL")

    pa = validate_success(api.get_tax_period(period_a["id"], OFFICER), 200)
    assert pa["balance_due_cents"] == 0, pa
    assert pa["period_status"] == "SATISFIED", pa

    pb = validate_success(api.get_tax_period(period_b["id"], OFFICER), 200)
    assert pb["balance_due_cents"] == 300000, pb


def test_csed_suspension_overlap_inside_open_window_rejected(api):
    """PRD §3.2: "A new interval is rejected with ERR_OVERLAPPING_SUSPENSION if its
    span overlaps any still-open interval (one whose end_at is null) on the same
    period".

    Design: Difficulty/resource_temporal_overlap/csed_suspension_open_interval_overlap_rejected
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    # open interval starting 2024-01-15, end null -> a second interval starting later
    # but before any close still overlaps the open span.
    open_suspension(period["id"], "2024-01-15T00:00:00.000Z", reason="MANUAL")
    res = api.create_csed_suspension(
        create_csed_suspension_payload(period["id"], reason="OIC_EVALUATION",
                                       start_at="2024-03-01T00:00:00.000Z"), OFFICER)
    validate_error(res, "ERR_OVERLAPPING_SUSPENSION")


def test_csed_close_folds_days_into_csed_date(api):
    """PRD §3.2: "On close, the system ... computes days_counted as the whole number
    of days from start_at to end_at, adds those days to the linked period's
    csed_date".

    Design: Difficulty/compensating_invariant/csed_day_conservation_on_suspension_close
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    p_before = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p_before["csed_date"][:10] == "2034-01-15", p_before
    susp = open_suspension(period["id"], "2024-01-15T00:00:00.000Z", reason="MANUAL")
    close_suspension(susp["id"], "2024-04-15T00:00:00.000Z")  # 91 days
    p_after = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p_after["csed_date"][:10] == "2034-04-16", p_after


def test_lien_release_blocked_then_succeeds_after_payoff(api):
    """PRD §3.10: "the account's total_balance_cents is zero, or the account has an
    InstallmentAgreement whose status is APPROVED or REINSTATED with payment_method of
    DIRECT_DEBIT. If neither condition holds, the release is blocked with
    ERR_LIEN_RELEASE_BLOCKED."

    Design: Difficulty/cross_entity_state_dependency/lien_release_depends_on_account_balance
    """
    acct, period, lien = setup_lien_release_pending(
        filed_amount_cents=1000000, assessed_tax_cents=1000000,
        assessment_date="2024-01-15T00:00:00.000Z", clock="2024-04-15T00:00:00.000Z")
    # before payoff the cross-entity guard blocks
    blocked = api.approve_lien_release(lien["id"], REVIEWER)
    validate_error(blocked, "ERR_LIEN_RELEASE_BLOCKED")
    # after full payoff the guard is satisfied
    post_payment(acct["id"], 1033000, payment_source="MANUAL", tax_period_id=period["id"])
    released = validate_success(api.approve_lien_release(lien["id"], REVIEWER), 200)
    assert released["status"] == "RELEASED", released


def test_csed_sweep_just_before_expiration_returns_nothing(api):
    """PRD §3.11: "each IN_COLLECTION period whose csed_date is on or before the
    current UTC instant ... If the sweep finds no period meeting both conditions (a
    passed csed_date and a positive balance), it returns ERR_NOTHING_TO_SWEEP."

    Design: Difficulty/boundary_precision_check/csed_sweep_at_exact_expiration_writes_off_boundary
    """
    set_clock("2010-01-15T00:00:00.000Z")
    acct = create_account(monthly_disposable_income_cents=300000)
    period = create_period(acct["id"], assessed_tax_cents=1000000,
                           assessment_date="2010-01-15T00:00:00.000Z", tax_year=2009)
    post_payment(acct["id"], 100, payment_source="MANUAL", tax_period_id=period["id"])
    # one day before csed_date 2020-01-16 -> not yet expired -> nothing to sweep
    set_clock("2020-01-15T00:00:00.000Z")
    res = api.sweep_expired_csed(acct["id"], OFFICER)
    validate_error(res, "ERR_NOTHING_TO_SWEEP")
