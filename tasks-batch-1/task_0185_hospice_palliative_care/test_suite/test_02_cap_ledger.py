"""The aggregate per-diem cap: provisional running estimate vs final frozen settlement,
the allowance evaluation order, ledger conservation, and post-settlement lockdown. PRD §3.11.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_provider,
    setup_provider_and_election,
    setup_provider_one_beneficiary_330000,
    setup_provider_with_two_beneficiaries,
    setup_settled_provider,
    post_gip_days,
    post_care_day,
    create_care_day_payload,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
CLINICAL = TEST_USERS["clinical_headers"]


# ─── Dual-variant: provisional cap-summary vs final settlement ─────────

def test_provisional_cap_summary_one_beneficiary_liability_130000(api):
    """PRD §3.11: "The cap allowance is the per_beneficiary_cap_cents multiplied by
    counted_beneficiaries, and the provisional cap_liability_cents is that total paid minus
    the allowance, but never below zero."

    Design: Difficulty/dual_variant_calc/cap_liability_provisional_vs_final_on_provider
    """
    provider, e1 = setup_provider_one_beneficiary_330000(per_beneficiary_cap_cents=200000)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert_provider(summary)
    assert summary["total_paid_cents"] == 330000
    assert summary["counted_beneficiaries"] == 1
    assert summary["cap_liability_cents"] == 130000, (
        f"330000 - (200000*1) = 130000, got {summary['cap_liability_cents']}")


def test_provisional_liability_falls_when_second_beneficiary_added(api):
    """PRD §3.11: "Because the allowance grows each time a fresh beneficiary first receives
    care, the provisional liability is a moving estimate that can actually fall when a new
    beneficiary is added."

    Design: Difficulty/dual_variant_calc/cap_liability_provisional_vs_final_on_provider
    """
    provider, e1, e2 = setup_provider_with_two_beneficiaries(per_beneficiary_cap_cents=200000)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["counted_beneficiaries"] == 2
    assert summary["total_paid_cents"] == 440000
    # allowance = 200000 * 2 = 400000 → liability = 40000, lower than the 130000 single-ben view.
    assert summary["cap_liability_cents"] == 40000, (
        f"440000 - (200000*2) = 40000, got {summary['cap_liability_cents']}")


# ─── Combinatorial: counted_beneficiaries evaluated before allowance ──

def test_cap_allowance_order_two_beneficiaries_liability_40000(api):
    """PRD §3.11: "The cap allowance is the per_beneficiary_cap_cents multiplied by
    counted_beneficiaries, and the provisional cap_liability_cents is that total paid minus
    the allowance, but never below zero."

    Design: Difficulty/combinatorial_formula/cap_allowance_evaluation_order_pinned
    """
    provider, e1, e2 = setup_provider_with_two_beneficiaries(per_beneficiary_cap_cents=200000)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["counted_beneficiaries"] == 2
    assert summary["cap_liability_cents"] == 40000


def test_cap_allowance_single_beneficiary_pins_liability(api):
    """PRD §3.11: "The counted_beneficiaries is the number of distinct elections under the
    provider that have at least one care day inside that window."

    Design: Difficulty/combinatorial_formula/cap_allowance_evaluation_order_pinned
    """
    provider, e1 = setup_provider_one_beneficiary_330000(per_beneficiary_cap_cents=200000)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["counted_beneficiaries"] == 1
    # allowance = 200000 * 1 = 200000 → liability = 330000 - 200000 = 130000.
    assert summary["cap_liability_cents"] == 130000


# ─── Compensating invariant: total_paid == sum of in-window care days ──

def test_total_paid_equals_sum_of_two_gip_caredays(api):
    """PRD §3.11: "The provider's total_paid_cents is the sum of payment_cents across every
    care day of every election under that provider whose service_date falls inside the current
    cap window of 365 days."

    Design: Difficulty/compensating_invariant/cap_ledger_conserved_total_paid_equals_sum_of_caredays
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=3490000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    days = post_gip_days(election["id"], ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"])
    assert days[0]["payment_cents"] == 110000
    assert days[1]["payment_cents"] == 110000
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["total_paid_cents"] == 220000, (
        f"total_paid must equal sum of care-day payments (110000+110000), "
        f"got {summary['total_paid_cents']}")


def test_total_paid_no_drift_after_three_gip_days(api):
    """PRD §3.11: "The provider's total_paid_cents is the sum of payment_cents across every
    care day of every election under that provider whose service_date falls inside the current
    cap window of 365 days."

    Design: Difficulty/compensating_invariant/cap_ledger_conserved_total_paid_equals_sum_of_caredays
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=3490000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    post_gip_days(election["id"],
                  ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"])
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["total_paid_cents"] == 330000


# ─── Corner: cap-summary filters in-window care days ──────────────────

def test_cap_summary_sums_single_in_window_gip_day(api):
    """PRD §3.11: "The counted_beneficiaries is the number of distinct elections under the
    provider that have at least one care day inside that window."

    Design: Corner/calculations/cap_summary_input_set_filters_in_window_caredays
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=3490000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["total_paid_cents"] == 110000
    assert summary["counted_beneficiaries"] == 1


# ─── Corner: settlement freezes the final liability ───────────────────

def test_settle_cap_freezes_liability_and_sets_settled(api):
    """PRD §3.11: "the demand recorded as the frozen cap_liability_cents is the in-window
    total less the allowance, never below zero."
    PRD §3.11: "When a BillingAdmin settles a provider's cap, the system performs the final
    variant on a frozen snapshot of all in-window care days taken at the settlement instant
    and then sets cap_settled to true."

    Design: Corner/calculations/settle_cap_freezes_final_liability
    """
    provider, election = setup_provider_one_beneficiary_330000(per_beneficiary_cap_cents=200000)
    settled = validate_success(api.settle_cap(provider["id"], BILLING), 200)
    # Single beneficiary: streamlined per-beneficiary cap clamps the beneficiary at 200000, but
    # the allowance is also 200000*1, so demand = max(0, 330000 - 200000) = 130000.
    assert settled["cap_liability_cents"] == 130000
    assert settled["cap_settled"] is True


# ─── Corner: posting a care day into a settled window is rejected ─────

def test_care_day_into_settled_window_rejected(api):
    """PRD §3.7: "No care day may be posted into a provider cap year that has already been
    settled; such a posting is rejected with ERR_CAP_YEAR_SETTLED (HTTP 409)."

    Design: Corner/calculations/careday_posting_after_settlement_rejected
    """
    provider, election = setup_settled_provider()
    payload = create_care_day_payload(election["id"], "2026-01-09T00:00:00Z", "GIP",
                                      high_intensity=False)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_CAP_YEAR_SETTLED")


# ─── Corner: cap ledger is immediately consistent ─────────────────────

def test_cap_ledger_visible_immediately_after_post(api):
    """PRD §3.11: "the system maintains a running estimate of it on the provider, recomputed
    on every care-day posting and recoverable on demand through the provider's cap-summary read."

    Design: Corner/consistency_model/cap_ledger_visible_immediately_in_same_response
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=3490000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["total_paid_cents"] == 110000, "ledger must reflect the post with no lag"
