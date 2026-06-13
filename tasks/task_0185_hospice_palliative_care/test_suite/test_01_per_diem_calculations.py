"""Per-diem rate-table calculations: the two-tier routine structure, the level-of-care
branch, and the elapsed-day boundary. PRD §3.6.
"""
import pytest

from test_helpers import (
    validate_success,
    assert_care_day,
    setup_provider_and_election,
    post_care_day,
    set_clock,
    create_care_day_payload,
    TEST_USERS,
)

CLINICAL = TEST_USERS["clinical_headers"]


# ─── Dual-variant: routine high vs base tier on CareDay ────────────────

def test_routine_high_tier_first_day_pays_21000(api):
    """PRD §3.6: "The first 60 elapsed days of the election — those whose elapsed-day index
    is less than 60 — are the high-intensity tier and pay 21000 cents ($210.00); from day 61
    onward — elapsed-day index of 60 or greater — the routine day pays the base rate of 16500
    cents ($165.00)."

    Design: Difficulty/dual_variant_calc/routine_per_diem_high_vs_base_tier_on_careday
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    day1 = post_care_day(election["id"], "2026-01-01T00:00:00Z", "ROUTINE", high_intensity=True)
    assert_care_day(day1)
    assert day1["payment_cents"] == 21000, (
        f"elapsed index 0 ROUTINE high should pay 21000, got {day1['payment_cents']}")


def test_routine_base_tier_day61_pays_16500(api):
    """PRD §3.6: "from day 61 onward — elapsed-day index of 60 or greater — the routine day
    pays the base rate of 16500 cents ($165.00)."

    Design: Difficulty/dual_variant_calc/routine_per_diem_high_vs_base_tier_on_careday
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    # Day 61 of the election is 2026-03-03 (elapsed index 61) — index >= 60, base tier.
    set_clock("2026-03-05T00:00:00Z")
    day61 = post_care_day(election["id"], "2026-03-03T00:00:00Z", "ROUTINE", high_intensity=False)
    assert day61["payment_cents"] == 16500, (
        f"elapsed index >= 60 ROUTINE base should pay 16500, got {day61['payment_cents']}")


# ─── Combinatorial: level-of-care branch dominates the day index ───────

def test_gip_day_one_pays_full_gip_rate_not_routine(api):
    """PRD §3.6: "A GIP day pays 110000 cents ($1,100.00) for general inpatient care."

    Design: Difficulty/combinatorial_formula/per_diem_three_input_nonlinear_selection
    """
    provider, election = setup_provider_and_election(election_date="2026-02-01T00:00:00Z",
                                                     clock="2026-02-01T00:00:00Z")
    gip = post_care_day(election["id"], "2026-02-01T00:00:00Z", "GIP", high_intensity=False)
    assert gip["level_of_care"] == "GIP"
    assert gip["payment_cents"] == 110000, (
        f"GIP day 1 should pay 110000 (branch dominates day index), got {gip['payment_cents']}")


def test_routine_day_one_pays_routine_high_not_gip(api):
    """PRD §3.6: "A ROUTINE day is priced on a two-tier service-intensity structure keyed on
    the day's elapsed position ... The first 60 elapsed days of the election ... pay 21000
    cents ($210.00)."

    Design: Difficulty/combinatorial_formula/per_diem_three_input_nonlinear_selection
    """
    provider, election = setup_provider_and_election(election_date="2026-02-01T00:00:00Z",
                                                     clock="2026-02-01T00:00:00Z")
    routine = post_care_day(election["id"], "2026-02-01T00:00:00Z", "ROUTINE", high_intensity=True)
    assert routine["level_of_care"] == "ROUTINE"
    assert routine["payment_cents"] == 21000, (
        f"ROUTINE day 1 should pay 21000, not the GIP rate, got {routine['payment_cents']}")


# ─── Boundary precision: tier flips at elapsed index < 60 vs >= 60 ─────

def test_routine_tier_at_elapsed_index_59_still_high(api):
    """PRD §3.6: "The first 60 elapsed days of the election — those whose elapsed-day index
    is less than 60 — are the high-intensity tier and pay 21000 cents ($210.00)."

    Design: Difficulty/boundary_precision_check/routine_tier_boundary_at_elapsed_day_60
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    set_clock("2026-03-03T00:00:00Z")
    # 2026-03-01 is elapsed index 59 (< 60) → high tier.
    day59 = post_care_day(election["id"], "2026-03-01T00:00:00Z", "ROUTINE", high_intensity=True)
    assert day59["payment_cents"] == 21000, (
        f"elapsed index 59 should still be high tier (21000), got {day59['payment_cents']}")


def test_routine_tier_at_elapsed_index_60_flips_to_base(api):
    """PRD §3.6: "from day 61 onward — elapsed-day index of 60 or greater — the routine day
    pays the base rate of 16500 cents ($165.00)."

    Design: Difficulty/boundary_precision_check/routine_tier_boundary_at_elapsed_day_60
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    set_clock("2026-03-03T00:00:00Z")
    # 2026-03-02 is elapsed index 60 (>= 60) → base tier.
    day60 = post_care_day(election["id"], "2026-03-02T00:00:00Z", "ROUTINE", high_intensity=False)
    assert day60["payment_cents"] == 16500, (
        f"elapsed index 60 should flip to base tier (16500), got {day60['payment_cents']}")


# ─── Corner: respite per-diem is a flat rate ──────────────────────────

def test_respite_day_pays_flat_47000(api):
    """PRD §3.6: "A RESPITE day pays 47000 cents ($470.00) for inpatient respite."

    Design: Corner/calculations/respite_per_diem_correct_result
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    cd = post_care_day(election["id"], "2026-01-02T00:00:00Z", "RESPITE", high_intensity=False)
    assert cd["payment_cents"] == 47000, f"RESPITE should pay 47000, got {cd['payment_cents']}"
    assert cd["respite_run_length"] == 1, "first respite day has run length 1"


# ─── Corner: payment_cents is server-computed, client input ignored ────

def test_payment_cents_is_server_computed_input_ignored(api):
    """PRD §3.6: "A GIP day pays 110000 cents ($1,100.00) for general inpatient care."
    PRD §2.4: "Every persisted resource in this system carries a server-minted id..."

    Design: Corner/entities/careday_payment_cents_is_computed_input_ignored
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    # Attempt to supply payment_cents — it is not an input field and must be ignored.
    payload = create_care_day_payload(election["id"], "2026-01-02T00:00:00Z", "GIP",
                                      high_intensity=False)
    payload["payment_cents"] = 1
    cd = validate_success(api.create_care_day(payload, CLINICAL), 201)
    assert cd["payment_cents"] == 110000, (
        f"payment_cents must be computed (110000), not the client-supplied 1, "
        f"got {cd['payment_cents']}")
