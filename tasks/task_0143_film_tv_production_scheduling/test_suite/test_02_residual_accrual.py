"""Residual accrual: cumulative marginal tier schedule across residual events."""
from test_helpers import validate_success, fixtures
from test_helpers.fixtures import LP, PC


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/residual_marginal_vs_naive_flat_rate
# --------------------------------------------------------------------------- #
def test_residual_second_event_straddles_tier_boundary(api):
    """PRD 3.9: "The residual for this event is the tier-rated value of the new
    cumulative total minus the tier-rated value of the prior cumulative total."
    PRD 3.9: "the first 100,000,000 cents are rated at 120 basis points, the next
    400,000,000 cents (the portion from 100,000,000 up to 500,000,000) are rated
    at 180 basis points".

    Event1 gross 80,000,000 => 960000; event2 gross 40,000,000 straddles the
    100,000,000 boundary => tier(120M)-tier(80M) = 1560000-960000 = 600000.

    Design: Difficulty/dual_variant_calc/residual_marginal_vs_naive_flat_rate
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000, title="Feature R")
    ev1 = validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "THEATRICAL",
         "gross_receipts_cents": 80_000_000, "event_date": "2026-01-31"}, PC),
        expected_status=201)
    ev2 = validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "SVOD",
         "gross_receipts_cents": 40_000_000, "event_date": "2026-02-28"}, PC),
        expected_status=201)
    assert ev1["residual_amount_cents"] == 960000, \
        f"expected ev1 residual 960000, got {ev1['residual_amount_cents']}"
    assert ev2["residual_amount_cents"] == 600000, \
        f"expected ev2 residual 600000, got {ev2['residual_amount_cents']}"


def test_residual_reserve_accumulates_on_production(api):
    """PRD 3.9: "Recording the event computes its residual_amount_cents and adds
    that amount to the production's residual_reserve_cents."

    After 960000 + 600000 the production's residual_reserve_cents == 1560000.

    Design: Difficulty/dual_variant_calc/residual_marginal_vs_naive_flat_rate
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000, title="Feature R")
    validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "THEATRICAL",
         "gross_receipts_cents": 80_000_000, "event_date": "2026-01-31"}, PC),
        expected_status=201)
    validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "SVOD",
         "gross_receipts_cents": 40_000_000, "event_date": "2026-02-28"}, PC),
        expected_status=201)
    refreshed = validate_success(api.get_production(prod["id"], LP))
    assert refreshed["residual_reserve_cents"] == 1560000, \
        f"expected reserve 1560000, got {refreshed['residual_reserve_cents']}"


# --------------------------------------------------------------------------- #
# Corner/calculations/residual_chronological_out_of_order_event_date
# --------------------------------------------------------------------------- #
def test_residual_ordered_by_event_date_not_insertion(api):
    """PRD 3.9: "the system first sums the gross_receipts_cents of all of the
    production's earlier events — ordered by event_date ascending and then
    created_at ascending — to get the prior cumulative total".

    An event posted later in wall time but with an EARLIER event_date is first in
    the tier accrual: the 80,000,000 event dated 2026-01-31 earns the tier-1
    marginal portion (960000) despite being inserted second.

    Design: Corner/calculations/residual_chronological_out_of_order_event_date
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "SVOD",
         "gross_receipts_cents": 40_000_000, "event_date": "2026-03-31"}, PC),
        expected_status=201)
    early = validate_success(api.create_residual_event(
        {"production_id": prod["id"], "market": "THEATRICAL",
         "gross_receipts_cents": 80_000_000, "event_date": "2026-01-31"}, PC),
        expected_status=201)
    assert early["residual_amount_cents"] == 960000, \
        f"expected early-dated residual 960000, got {early['residual_amount_cents']}"
    # NOTE: the production's residual_reserve_cents is NOT re-asserted here.
    # PRD 3.9 states "Recording the event computes its residual_amount_cents and
    # adds that amount to ... residual_reserve_cents", and a residual event is an
    # immutable record. So inserting an EARLIER-dated event does not retroactively
    # recompute the already-recorded later-dated event's residual. The reserve is
    # therefore the sum of each event's residual AS COMPUTED AT ITS OWN insertion
    # (the first SVOD event was rated tier(40M)=480000 when it was alone, then this
    # early THEATRICAL event added 960000 = 1,440,000) — NOT tier(120M)=1,560,000,
    # which would require retroactively recomputing the immutable SVOD event.
