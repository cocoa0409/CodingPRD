"""Rejection paths on the money and rights side of the carriage contract: audit
rights expiry, billable-report discovery, payment bounds, the zero-net invoice,
the marketing ledger ceiling, termination against an open receivable, window
clearance, and the one-recovery-per-engagement rule.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
import pytest

from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    AUDITOR,
    SALES,
    RIGHTS,
    ApiErrorId,
    accept_report,
    assert_commitment_ledger_identities,
    create_audit_engagement_payload,
    create_commitment,
    create_invoice_payload,
    distributor_version,
    draft_invoice,
    earn_commitment,
    fetch_agreement,
    fetch_commitment,
    fetch_engagement,
    fetch_invoice,
    fetch_title,
    fetch_window,
    file_report,
    plan_window,
    record_payment,
    register_cleared_title,
    schedule_blackout,
    setup_accepted_report,
    setup_audit_recovery_invoice,
    setup_executed_agreement,
    setup_issued_invoice,
    suspend_agreement,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    waive_blackout,
)

_TELCO = {
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}
_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}
_JUNE = "2026-06"
_JUNE_REPORT = {
    "period_month": _JUNE,
    "reported_subscribers": 130_000,
    "reported_tier": "BASIC",
}
# 130,000 billable subscribers x 40.0000 cents at a flat escalator.
_JUNE_FEE_CENTS = 5_200_000


# ---------------------------------------------------------------------------
# Audit rights expiry
# ---------------------------------------------------------------------------
def test_sample_period_may_not_reach_past_the_month_of_term_end(api):
    """PRD §3.7: "Fieldwork on an agreement that has already reached `EXPIRED` may
    only begin within 24 months of its `term_end_date`, and `sample_period_end`
    may never reach past the month containing `term_end_date`; either violation is
    refused with `ERR_AUDIT_RIGHTS_EXPIRED`, both when the engagement is opened
    and when fieldwork is started."

    Design: Corner/errors/audit_rights_expire_with_the_sample_period_bound
    """
    _distributor, agreement, _report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides={**_TERMS, "term_end_date": "2026-12-31T00:00:00Z"},
        report_overrides=_JUNE_REPORT,
    )

    response = api.create_audit_engagement(
        create_audit_engagement_payload(
            agreement["id"],
            sample_period_start=_JUNE,
            sample_period_end="2027-01",
            rate_basis="CLOSING_RATE",
        ),
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_RIGHTS_EXPIRED.value)

    _rows, meta = validate_paginated(
        api.list_audit_engagements(AUDITOR, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, "the refused opening must not have created an engagement"

    engagement = validate_success(
        api.create_audit_engagement(
            create_audit_engagement_payload(
                agreement["id"],
                sample_period_start=_JUNE,
                sample_period_end="2026-12",
                rate_basis="CLOSING_RATE",
            ),
            AUDITOR,
        ),
        201,
    )
    assert engagement["status"] == "OPENED"
    assert engagement["sample_period_end"] == "2026-12"

    started = validate_success(
        api.audit_engagement_lifecycle(
            engagement["id"], {"action": "START_FIELDWORK"}, AUDITOR
        )
    )
    assert started["status"] == "FIELDWORK", "a sample inside the term may start fieldwork"


# ---------------------------------------------------------------------------
# Billable-report discovery
# ---------------------------------------------------------------------------
def test_license_fee_draft_for_an_unreported_period_has_nothing_to_bill(api):
    """PRD §3.8: "Second, a license-fee invoice must find at least one unbilled
    report in `ACCEPTED` or `AUDIT_ADJUSTED` status for the given `agreement_id`
    and `period_month`, and an audit-recovery invoice must name an engagement
    whose `status` is `FINDINGS_ISSUED`; failing either is
    `ERR_NO_BILLABLE_REPORTS`."
    PRD §3.8: "For a `LICENSE_FEE` invoice, `gross_license_fee_cents` is the sum
    of `license_fee_due_cents` over the subscriber reports of the named agreement
    whose `period_month` equals the invoice's `period_month`, whose `status` is
    `ACCEPTED` or `AUDIT_ADJUSTED`, and whose `invoice_id` is still null — each of
    those figures already rounded per report."

    Design: Corner/errors/license_fee_invoice_for_an_unreported_period_finds_nothing_to_bill
    """
    distributor, agreement, _report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )

    response = api.create_invoice(
        create_invoice_payload(
            distributor["id"], agreement["id"], "2026-07", distributor_version(distributor["id"])
        ),
        ACCOUNTANT,
    )
    validate_error(response, ApiErrorId.ERR_NO_BILLABLE_REPORTS.value)

    _rows, meta = validate_paginated(
        api.list_invoices(ACCOUNTANT, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, "the refused draft must not have created an invoice"

    invoice = validate_success(
        api.create_invoice(
            create_invoice_payload(
                distributor["id"], agreement["id"], _JUNE, distributor_version(distributor["id"])
            ),
            ACCOUNTANT,
        ),
        201,
    )
    assert invoice["period_month"] == _JUNE
    assert invoice["gross_license_fee_cents"] == _JUNE_FEE_CENTS
    assert invoice["net_due_cents"] == _JUNE_FEE_CENTS


# ---------------------------------------------------------------------------
# Payment bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("amount_cents", [_JUNE_FEE_CENTS + 1, 0], ids=["above_balance", "zero"])
def test_payment_outside_the_open_balance_is_refused(api, amount_cents):
    """PRD §3.8: "The amount must be strictly positive and must not exceed
    `net_due_cents` less `paid_cents`, or the payment is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/errors/payment_amount_must_be_positive_and_within_the_open_balance
    """
    _distributor, _agreement, _report, invoice = setup_issued_invoice(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    assert invoice["net_due_cents"] == _JUNE_FEE_CENTS
    assert invoice["paid_cents"] == 0

    response = api.invoice_lifecycle(
        invoice["id"], {"action": "RECORD_PAYMENT", "amount_cents": amount_cents}, ACCOUNTANT
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)

    after = fetch_invoice(invoice["id"])
    assert after["status"] == "ISSUED", "a refused payment leaves the invoice ISSUED"
    assert after["paid_cents"] == 0, "a refused payment applies no cash"


def test_payment_bound_tightens_after_a_partial_settlement(api):
    """PRD §3.8: "The amount must be strictly positive and must not exceed
    `net_due_cents` less `paid_cents`, or the payment is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD §3.8: "A payment that leaves a residue moves the invoice `ISSUED →
    PARTIALLY_PAID`; a payment that closes the balance exactly moves it `ISSUED →
    PAID` or `PARTIALLY_PAID → PAID`."

    Design: Corner/errors/payment_amount_must_be_positive_and_within_the_open_balance
    """
    _distributor, _agreement, _report, invoice = setup_issued_invoice(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )

    partial = record_payment(invoice["id"], 5_000_000)
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["paid_cents"] == 5_000_000

    response = api.invoice_lifecycle(
        invoice["id"], {"action": "RECORD_PAYMENT", "amount_cents": 200_001}, ACCOUNTANT
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)
    still = fetch_invoice(invoice["id"])
    assert still["status"] == "PARTIALLY_PAID"
    assert still["paid_cents"] == 5_000_000, "the over-large payment applied no cash"

    settled = record_payment(invoice["id"], 200_000)
    assert settled["status"] == "PAID"
    assert settled["paid_cents"] == _JUNE_FEE_CENTS


# ---------------------------------------------------------------------------
# The fully offset invoice
# ---------------------------------------------------------------------------
def test_fully_offset_invoice_cannot_be_issued_and_must_be_voided(api):
    """PRD §3.8: "And `net_due_cents` must be strictly greater than zero: a
    fully-offset invoice cannot be issued and must be voided instead, with the
    refusal `ERR_INVOICE_ZERO_NET_DUE`."
    PRD §3.8: "**Launch-fee offset.** Sum `earned_unbilled_cents` across the
    agreement's `LAUNCH_FEE` lines in `PARTIALLY_EARNED` or `EARNED` status.
    `launch_fee_offset_cents` is the lesser of that pool and what the co-op offset
    left of the gross — that is, the gross less `coop_offset_cents`, floored at
    zero."
    PRD §3.8: "**Floor and carryforward.** The raw net is the gross less
    `coop_offset_cents` less `launch_fee_offset_cents` plus
    `recovery_adjustment_cents`. `net_due_cents` is that raw net floored at zero,
    and `carryforward_cents` is however much the raw net went below zero,
    expressed as a positive amount — the offset value that could not be applied."
    PRD §3.8: "Voiding a `DRAFT` restores nothing, and that is the point: a draft
    only *projects* its offsets, so `billed_cents` and `earned_unbilled_cents` were
    never touched at drafting and are not touched at void, and the conserved
    identity of §3.8 holds unchanged across both calls."

    Design: Corner/errors/fully_offset_invoice_is_creatable_but_not_issuable
    """
    distributor, agreement = setup_executed_agreement(
        distributor_overrides={
            "distributor_type": "TELCO",
            "rate_card_class": "CLASS_C",
            "total_subscribers": 50_000,
        },
        agreement_overrides=_TERMS,
    )
    commitment = create_commitment(
        agreement["id"],
        commitment_type="LAUNCH_FEE",
        committed_cents=1_000_000,
        performance_deadline="2026-12-01T00:00:00Z",
    )
    earned = earn_commitment(commitment["id"], 1_000_000)
    assert earned["status"] == "EARNED"
    assert earned["earned_unbilled_cents"] == 1_000_000

    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month=_JUNE,
        reported_subscribers=25_000,
        reported_tier="BASIC",
    )
    accepted = accept_report(report["id"])
    assert accepted["license_fee_due_cents"] == 1_000_000

    invoice = draft_invoice(distributor["id"], agreement["id"], _JUNE)
    assert invoice["gross_license_fee_cents"] == 1_000_000
    assert invoice["coop_offset_cents"] == 0, "no co-op or marketing-support line exists"
    assert invoice["launch_fee_offset_cents"] == 1_000_000
    assert invoice["net_due_cents"] == 0
    assert invoice["carryforward_cents"] == 0

    response = api.invoice_lifecycle(invoice["id"], {"action": "ISSUE"}, ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_INVOICE_ZERO_NET_DUE.value)
    assert fetch_invoice(invoice["id"])["status"] == "DRAFT", (
        "the refused issuance leaves the invoice in DRAFT"
    )

    voided = validate_success(api.invoice_lifecycle(invoice["id"], {"action": "VOID"}, ACCOUNTANT))
    assert voided["status"] == "VOID"

    line = fetch_commitment(commitment["id"])
    assert line["billed_cents"] == 0, "a draft never consumed the offset"
    assert line["earned_unbilled_cents"] == 1_000_000
    assert_commitment_ledger_identities(line)


# ---------------------------------------------------------------------------
# Marketing ledger ceiling
# ---------------------------------------------------------------------------
def test_cumulative_earn_above_the_committed_amount_is_refused(api):
    """PRD §3.8: "Recording accepted proof of performance supplies the amount as
    `earned_cents` together with a `proof_reference` identifying the evidence."
    PRD §3.8: "The operation requires the funding agreement to be strictly
    `EXECUTED`, refusing otherwise with `ERR_AGREEMENT_NOT_EXECUTED`; requires the
    line's `performance_deadline` not to have passed at the current logical
    instant, refusing otherwise with `ERR_COMMITMENT_DEADLINE_PASSED`; and requires
    that the already-earned total plus the requested amount does not exceed
    `committed_cents`, refusing otherwise with `ERR_MARKETING_OVEREARN`."
    PRD §3.8: "The line's `status` becomes `EARNED` when `remaining_cents` reaches
    0, and `PARTIALLY_EARNED` while the earned total is above zero but still below
    `committed_cents`."

    Design: Corner/errors/marketing_earn_cannot_exceed_the_committed_amount
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides={
            "distributor_type": "DBS",
            "rate_card_class": "CLASS_B",
            "total_subscribers": 800_000,
        },
        agreement_overrides=_TERMS,
    )
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-01T00:00:00Z",
    )
    partial = earn_commitment(commitment["id"], 600_000)
    assert partial["status"] == "PARTIALLY_EARNED"

    response = api.earn_marketing_commitment(
        commitment["id"], {"earned_cents": 500_000, "proof_reference": "PROOF-OVER"}, SALES
    )
    validate_error(response, ApiErrorId.ERR_MARKETING_OVEREARN.value)

    unchanged = fetch_commitment(commitment["id"])
    assert unchanged["earned_cents"] == 600_000, "the refused earn adds nothing"
    assert unchanged["earned_unbilled_cents"] == 600_000
    assert_commitment_ledger_identities(unchanged)

    topped_up = earn_commitment(commitment["id"], 400_000)
    assert topped_up["earned_cents"] == 1_000_000
    assert topped_up["remaining_cents"] == 0
    assert topped_up["status"] == "EARNED"
    assert_commitment_ledger_identities(topped_up)


def test_a_single_cent_over_a_fully_earned_line_is_refused(api):
    """PRD §3.8: "The operation requires the funding agreement to be strictly
    `EXECUTED`, refusing otherwise with `ERR_AGREEMENT_NOT_EXECUTED`; requires the
    line's `performance_deadline` not to have passed at the current logical
    instant, refusing otherwise with `ERR_COMMITMENT_DEADLINE_PASSED`; and requires
    that the already-earned total plus the requested amount does not exceed
    `committed_cents`, refusing otherwise with `ERR_MARKETING_OVEREARN`."

    Design: Corner/errors/marketing_earn_cannot_exceed_the_committed_amount
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides={
            "distributor_type": "DBS",
            "rate_card_class": "CLASS_B",
            "total_subscribers": 800_000,
        },
        agreement_overrides=_TERMS,
    )
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-01T00:00:00Z",
    )
    fully_earned = earn_commitment(commitment["id"], 1_000_000)
    assert fully_earned["status"] == "EARNED"

    response = api.earn_marketing_commitment(
        commitment["id"], {"earned_cents": 1, "proof_reference": "PROOF-CENT"}, SALES
    )
    validate_error(response, ApiErrorId.ERR_MARKETING_OVEREARN.value)

    after = fetch_commitment(commitment["id"])
    assert after["earned_cents"] == 1_000_000, "an exhausted line takes no further earn"
    assert after["status"] == "EARNED"
    assert_commitment_ledger_identities(after)


# ---------------------------------------------------------------------------
# Termination against an open receivable
# ---------------------------------------------------------------------------
def test_agreement_termination_waits_for_the_open_receivable(api):
    """PRD §3.2: "Terminating from `SUSPENDED` additionally requires that no
    invoice of this agreement sits in `ISSUED` or `PARTIALLY_PAID` — open
    receivables must be resolved first, and the refusal is
    `ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION` — and it runs the full unwind: every
    rights window in `PLANNED`, `CLEARED`, `ACTIVE` or `BLOCKED` moves to
    `EXPIRED`, every marketing commitment with positive `remaining_cents` forfeits
    that remainder and becomes `FORFEITED`, and the operator's
    `executed_agreement_count` decrements by one."

    Design: Corner/errors/open_receivable_blocks_agreement_termination_until_paid
    """
    _distributor, agreement, _report, invoice = setup_issued_invoice(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    suspended = suspend_agreement(agreement["id"])
    assert suspended["lifecycle_status"] == "SUSPENDED"

    response = api.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
    validate_error(response, ApiErrorId.ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION.value)
    assert fetch_agreement(agreement["id"])["lifecycle_status"] == "SUSPENDED"

    paid = record_payment(invoice["id"], _JUNE_FEE_CENTS)
    assert paid["status"] == "PAID"

    terminated = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
    )
    assert terminated["lifecycle_status"] == "TERMINATED", (
        "with the receivable settled the same termination must succeed"
    )


def test_operator_termination_waits_for_the_open_receivable(api):
    """PRD §3.1: "`SUSPEND`, `TERMINATE` and `REACTIVATE` set `status` to
    `SUSPENDED`, `TERMINATED` and `ACTIVE` respectively, and a termination is
    refused with `ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION` while any invoice in the
    operator's scope sits in `ISSUED` or `PARTIALLY_PAID`."

    Design: Corner/errors/open_receivable_blocks_agreement_termination_until_paid
    """
    distributor, _agreement, _report, invoice = setup_issued_invoice(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    assert invoice["status"] == "ISSUED"

    response = api.credit_review(distributor["id"], {"action": "TERMINATE"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION.value)

    live = validate_success(api.get_distributor(distributor["id"], ADMIN))
    assert live["status"] == "ACTIVE", "the refused posture action leaves the operator ACTIVE"
    assert live["version"] == distributor["version"], "a refused posture action bumps no version"


def test_terminating_twice_reports_the_lifecycle_conflict(api):
    """PRD §3.2: "An action that is not a declared transition out of the current
    `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an action
    that is not a declared transition out of the current `renewal_status` is
    rejected with `ERR_INVALID_RENEWAL_STATE`."
    PRD §2.8: "The one structural consequence worth stating up front: because
    state admissibility (band 9) precedes every business check, an action that is
    not a declared transition out of the target's current state always surfaces as
    the relevant invalid-state conflict, never as the business rule that would
    also have failed."

    Design: Corner/errors/open_receivable_blocks_agreement_termination_until_paid
    """
    _distributor, agreement, _report, invoice = setup_issued_invoice(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    suspend_agreement(agreement["id"])
    record_payment(invoice["id"], _JUNE_FEE_CENTS)
    terminated = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
    )
    assert terminated["lifecycle_status"] == "TERMINATED"

    response = api.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
    validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value)
    assert fetch_agreement(agreement["id"])["lifecycle_status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Window clearance constraints
# ---------------------------------------------------------------------------
_RIGHTS_DISTRIBUTOR = {
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_A",
    "total_subscribers": 1_500_000,
}
_RIGHTS_TERMS = {**_TERMS, "term_end_date": "2026-12-31T00:00:00Z"}
_PREMIERE = "2026-08-15T00:00:00Z"


def test_clearance_refused_while_a_scheduled_blackout_overlaps(api):
    """PRD §3.6: "Then no `SCHEDULED` or `ENFORCED` blackout rule of the same
    agreement and the same `territory_code` may intersect the window's half-open
    interval, or the clearance is refused with `ERR_BLACKOUT_WINDOW_CONFLICT`."
    PRD §3.6: "Waiving instead moves `SCHEDULED → WAIVED`, after which the rule
    stops conflicting with anything and stops counting toward
    `monthly_blackout_hours` for its month."
    PRD §3.6: "Clearing a window moves it `PLANNED → CLEARED`, increments the
    title's `cleared_window_count` by one and re-derives
    `distribution_coverage_status`."

    Design: Corner/errors/window_clearance_refused_by_blackout_overlap_and_by_term_bounds
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides=_RIGHTS_DISTRIBUTOR, agreement_overrides=_RIGHTS_TERMS
    )
    title = register_cleared_title(linear_premiere_at=_PREMIERE)
    rule = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-05T18:00:00Z",
        blackout_end="2026-09-05T22:00:00Z",
        substitution_required=False,
    )
    assert rule["status"] == "SCHEDULED"

    window = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-09-05T20:00:00Z",
        window_end="2026-09-06T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )

    response = api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS)
    validate_error(response, ApiErrorId.ERR_BLACKOUT_WINDOW_CONFLICT.value)
    assert fetch_window(window["id"])["status"] == "PLANNED"
    assert fetch_title(title["id"])["cleared_window_count"] == 0

    waive_blackout(rule["id"])
    cleared = validate_success(
        api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS)
    )
    assert cleared["status"] == "CLEARED", "a waived rule no longer conflicts"
    assert cleared["block_reason"] == "NONE"
    assert fetch_title(title["id"])["cleared_window_count"] == 1


def test_clearance_refused_when_the_window_runs_past_the_term(api):
    """PRD §3.6: "Then the exclusivity test, then the aggregate-concurrency test,
    then the holdback test, and finally the containment test: the window's
    half-open interval must lie inside the interval from `term_start_date`
    inclusive to `term_end_date` exclusive, or the response is
    `ERR_WINDOW_OUTSIDE_TERM`."
    PRD §3.6: "Its `windowing_holdback_days` is stamped immediately, as the whole
    number of days from the title's `linear_premiere_at` to the window's
    `window_start`, discarding any fraction; a window that opens before the linear
    premiere therefore carries a negative holdback."
    PRD §3.6: "Clearing a window moves it `PLANNED → CLEARED`, increments the
    title's `cleared_window_count` by one and re-derives
    `distribution_coverage_status`."

    Design: Corner/errors/window_clearance_refused_by_blackout_overlap_and_by_term_bounds
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides=_RIGHTS_DISTRIBUTOR, agreement_overrides=_RIGHTS_TERMS
    )
    title = register_cleared_title(linear_premiere_at=_PREMIERE)

    overrunning = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-12-30T00:00:00Z",
        window_end="2027-01-05T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    response = api.rights_window_lifecycle(overrunning["id"], {"action": "CLEAR"}, RIGHTS)
    validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_TERM.value)
    assert fetch_window(overrunning["id"])["status"] == "PLANNED"
    assert fetch_title(title["id"])["cleared_window_count"] == 0

    contained = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-08T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    assert contained["windowing_holdback_days"] == 47
    cleared = validate_success(
        api.rights_window_lifecycle(contained["id"], {"action": "CLEAR"}, RIGHTS)
    )
    assert cleared["status"] == "CLEARED", "a window inside the term clears"
    assert fetch_title(title["id"])["cleared_window_count"] == 1


# ---------------------------------------------------------------------------
# One recovery invoice per engagement
# ---------------------------------------------------------------------------
def test_engagement_recovery_cannot_be_invoiced_twice(api):
    """PRD §3.8: "Third, the named engagement's `recovery_invoice_id` must still be
    null, or the draft is refused with `ERR_RECOVERY_ALREADY_INVOICED`."
    PRD §3.8: "Second, a license-fee invoice must find at least one unbilled report
    in `ACCEPTED` or `AUDIT_ADJUSTED` status for the given `agreement_id` and
    `period_month`, and an audit-recovery invoice must name an engagement whose
    `status` is `FINDINGS_ISSUED`; failing either is `ERR_NO_BILLABLE_REPORTS`."

    Design: Corner/errors/one_engagement_yields_one_recovery_invoice
    """
    distributor, agreement, report, engagement, invoice = setup_audit_recovery_invoice(
        140_000,
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    assert engagement["status"] == "RECOVERY_INVOICED"
    assert engagement["recovery_invoice_id"] == invoice["id"]

    response = api.create_invoice(
        create_invoice_payload(
            distributor["id"],
            agreement["id"],
            report["period_month"],
            distributor_version(distributor["id"]),
            invoice_kind="AUDIT_RECOVERY",
            audit_engagement_id=engagement["id"],
        ),
        ACCOUNTANT,
    )
    # The engagement's own status left FINDINGS_ISSUED when the first recovery
    # invoice was drafted, so the PRD's second and third referential checks both
    # bite on this attempt and it may surface either code.
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_RECOVERY_ALREADY_INVOICED.value,
            ApiErrorId.ERR_NO_BILLABLE_REPORTS.value,
        ],
    )

    still = fetch_engagement(engagement["id"])
    assert still["recovery_invoice_id"] == invoice["id"], "the engagement keeps its one recovery"
    _rows, meta = validate_paginated(
        api.list_invoices(
            ACCOUNTANT,
            params={
                "agreement_id": agreement["id"],
                "invoice_kind": "AUDIT_RECOVERY",
                "limit": 10,
            },
        )
    )
    assert meta["total_count"] == 1, "exactly one recovery invoice exists for the engagement"


def test_audit_manager_cannot_draft_the_recovery_invoice(api):
    """PRD §2.1: "If both headers are well-formed but the named role is not among
    the roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "2. Endpoint role membership — `ERR_FORBIDDEN_ROLE`."
    PRD §2.8: "15. Billing referential integrity (rules 80 through 85)."

    Design: Corner/errors/one_engagement_yields_one_recovery_invoice
    """
    distributor, agreement, report, engagement, invoice = setup_audit_recovery_invoice(
        140_000,
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )

    response = api.create_invoice(
        create_invoice_payload(
            distributor["id"],
            agreement["id"],
            report["period_month"],
            distributor_version(distributor["id"]),
            invoice_kind="AUDIT_RECOVERY",
            audit_engagement_id=engagement["id"],
        ),
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert fetch_engagement(engagement["id"])["recovery_invoice_id"] == invoice["id"]
