"""The conserved reserve ledger: total_incurred conservation across a payment and its
void, the void cascade restoring outstanding reserve, the open_claim_count tally
conservation, immediate consistency of reserve figures, and OCC-guarded re-projection.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    setup_lost_time_claim,
    setup_lost_time_with_posted_ttd,
    setup_medical_only_claim,
    setup_reported_claim,
    setup_acknowledged_froi,
    setup_wage_statement,
    read_claim,
    read_reserve,
    read_employer,
    set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def test_void_payment_cascade_restores_reserve_and_total(api):
    """PRD §3.6: "Voiding moves the payment to VOIDED and performs a compensating reversal:
    indemnity_paid_cents falls by the original amount and indemnity_reserve_cents rises by
    the same amount, restoring the reserve and leaving the conserved total unchanged."

    Design: Difficulty/transitive_cascade/void_payment_cascade_restores_reserve_and_total
    """
    ctx = setup_lost_time_with_posted_ttd(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    reserve_id = ctx["reserve"]["id"]
    # after the posted TTD (42858): paid 42858, reserve 1157202
    before = read_reserve(reserve_id)
    assert before["indemnity_paid_cents"] == 42858
    assert before["indemnity_reserve_cents"] == 1157202

    voided = validate_success(api.void_benefit_payment(ctx["payment"]["id"], ADJUSTER), 200)
    assert voided["status"] == "VOIDED"

    after = read_reserve(reserve_id)
    assert after["indemnity_paid_cents"] == 0, "paid restored to 0 after void"
    assert after["indemnity_reserve_cents"] == 1200060, "outstanding reserve restored"
    assert after["total_incurred_cents"] == 2700060, "conserved total unchanged across the void cascade"


def test_total_incurred_conserved_across_payment_and_void(api):
    """PRD §2.6: "The total incurred figure is a conserved quantity: whenever a benefit
    payment moves money from the outstanding indemnity reserve into indemnity paid, the same
    number of cents leaves one column and enters the other, so the total incurred is
    unchanged by any payment-plus-drawdown pair."

    Design: Difficulty/compensating_invariant/total_incurred_conserved_across_payment_and_void
    """
    ctx = setup_lost_time_with_posted_ttd(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    reserve_id = ctx["reserve"]["id"]
    after_payment = read_reserve(reserve_id)
    assert after_payment["total_incurred_cents"] == 2700060, "total unchanged by the payment drawdown"

    get_success_data(api.void_benefit_payment(ctx["payment"]["id"], ADJUSTER))
    after_void = read_reserve(reserve_id)
    assert after_void["total_incurred_cents"] == 2700060, "zero drift across the void"


def test_open_claim_count_conserved_across_close_and_reopen(api):
    """PRD §2.7: "it is incremented when a claim is accepted (moving out of the reported
    state into an active classification) and when a closed claim is reopened, and it is
    decremented when a claim is closed."
    PRD §3.11: "an adjuster may reopen it, moving it CLOSED → REOPENED and incrementing the
    employer's open_claim_count by one to conserve the count that closing decremented."

    Design: Difficulty/compensating_invariant/open_claim_count_conserved_across_close_and_reopen
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_medical_only_claim(date_of_injury="2026-02-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    claim_id = ctx["claim"]["id"]

    assert read_employer(employer_id)["open_claim_count"] == 1, "1 after accept (before close)"

    get_success_data(api.close_claim(claim_id, ADJUSTER))
    assert read_employer(employer_id)["open_claim_count"] == 0, "0 after close"

    reopened = validate_success(api.reopen_claim(claim_id, ADJUSTER), 200)
    assert reopened["status"] == "REOPENED"
    assert read_employer(employer_id)["open_claim_count"] == 1, "1 after reopen (count conserved)"


def test_reserve_total_incurred_visible_in_create_response(api):
    """PRD §2.6: "plus a derived total_incurred_cents that is the sum of those four."
    PRD §3.4: "On creation, total_incurred_cents is set to the sum of the indemnity reserve,
    the medical reserve, and the (initially zero) paid columns."

    Design: Corner/consistency_model/reserve_total_incurred_visible_same_request
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    ws, _ = setup_wage_statement(claim_id, ctx["claim_version"], average_weekly_wage_cents=150_000)

    reserve = validate_success(
        api.create_reserve(f.create_reserve_payload(claim_id, severity_tier="MODERATE", projected_weeks=12), ADJUSTER),
        201,
    )
    assert reserve["indemnity_reserve_cents"] == 1200060
    assert reserve["medical_reserve_cents"] == 1500000
    assert reserve["total_incurred_cents"] == 2700060, "all correct in the POST /reserves response itself"


def test_void_payment_marks_voided_and_reverses_paid_column(api):
    """PRD §3.6: "A posted payment may be voided. Voiding moves the payment to VOIDED and
    performs a compensating reversal: indemnity_paid_cents falls by the original amount and
    indemnity_reserve_cents rises by the same amount, restoring the reserve and leaving the
    conserved total unchanged."

    Design: Difficulty/transitive_cascade/void_payment_cascade_restores_reserve_and_total
    """
    ctx = setup_lost_time_with_posted_ttd(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    voided = validate_success(api.void_benefit_payment(ctx["payment"]["id"], ADJUSTER), 200)
    assert voided["status"] == "VOIDED", "the payment itself transitions POSTED -> VOIDED (cascade link 1)"
    # the void cascade (link 2) drives the reserve columns back
    reserve = read_reserve(ctx["reserve"]["id"])
    assert reserve["indemnity_paid_cents"] == 0
    assert reserve["indemnity_reserve_cents"] == 1200060


def test_total_incurred_unchanged_immediately_after_payment(api):
    """PRD §2.6: "whenever a benefit payment moves money from the outstanding indemnity
    reserve into indemnity paid, the same number of cents leaves one column and enters the
    other, so the total incurred is unchanged by any payment-plus-drawdown pair."

    Design: Difficulty/compensating_invariant/total_incurred_conserved_across_payment_and_void
    """
    ctx = setup_lost_time_with_posted_ttd(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    reserve = read_reserve(ctx["reserve"]["id"])
    # payment of 42858 moved between columns; total stays 2700060
    assert reserve["indemnity_paid_cents"] == 42858
    assert reserve["indemnity_reserve_cents"] == 1157202
    assert reserve["total_incurred_cents"] == 2700060


def test_open_claim_count_increments_on_accept(api):
    """PRD §2.7: "The employer's open_claim_count is a conserved tally of that employer's
    claims that are not closed: it is incremented when a claim is accepted (moving out of the
    reported state into an active classification) and when a closed claim is reopened, and it
    is decremented when a claim is closed."

    Design: Difficulty/compensating_invariant/open_claim_count_conserved_across_close_and_reopen
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_medical_only_claim(date_of_injury="2026-02-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    # accept already happened in the fixture; the accept incremented the count to 1
    assert read_employer(employer_id)["open_claim_count"] == 1
    # closing decrements it back to 0 (the count's other conserved half)
    get_success_data(api.close_claim(ctx["claim"]["id"], ADJUSTER))
    assert read_employer(employer_id)["open_claim_count"] == 0


def test_dispute_cascade_completed_ime_is_singular(api):
    """PRD §2.7: "Disputing a treating-physician rating cascades the creation of a brand-new
    IME order."
    PRD §3.9: "A reviewer completes the exam — permitted only once the current logical time
    has reached or passed scheduled_start — moving it SCHEDULED → COMPLETED."

    Design: Difficulty/transitive_cascade/dispute_creates_ime_then_complete_then_finalize_to_mmi
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    from test_helpers import setup_disputed_rating
    claim_id = ctx["claim"]["id"]
    rating, ime = setup_disputed_rating(claim_id, whole_body_pct=15)
    # exactly one IME order was synthesized by the dispute (cascade link 1)
    body = api.list_claim_ime_orders(claim_id, ADJUSTER).json()
    ime_orders = body["data"]
    assert len(ime_orders) == 1, "dispute creates exactly one IME order"
    # completing it (link 2) advances it to COMPLETED, unblocking finalize
    completed = validate_success(api.complete_ime_order(ime["id"], TEST_USERS["medical_reviewer_headers"]), 200)
    assert completed["status"] == "COMPLETED"


def test_reserve_adjustment_with_current_version_reprojects(api):
    """PRD §2.8: "A reserve adjustment must carry expected_claim_version matching the target
    claim's current version ... A successful reserve adjustment likewise increments the
    claim's version by one."
    PRD §3.4: "A reserve adjustment supplies a fresh projected_weeks and severity_tier ... and
    recomputes both outstanding reserve figures by the same rules."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_claim_version_on_reserve_adjustment_succeeds
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    ws, _ = setup_wage_statement(claim_id, ctx["claim_version"], average_weekly_wage_cents=150_000)
    reserve = get_success_data(
        api.create_reserve(f.create_reserve_payload(claim_id, severity_tier="MINOR", projected_weeks=4), ADJUSTER)
    )
    current_version = read_claim(claim_id)["version"]

    updated = validate_success(
        api.reserve_adjustment(
            claim_id,
            {"projected_weeks": 12, "severity_tier": "MODERATE", "expected_claim_version": current_version},
            ADJUSTER,
        ),
        200,
    )
    assert updated["indemnity_reserve_cents"] == 1200060, "re-projected 12 weeks * 100005"
    assert updated["medical_reserve_cents"] == 1500000, "MODERATE tier"
