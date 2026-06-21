"""Discharge estate settlement: the exempt/nonexempt split, the floor-at-zero
clamp on over-claimed exemptions, and the gross-estate conservation invariant.

PRD §3.10 governs every assertion in this file.
"""
import pytest

from test_helpers import (
    api_client, validate_success, assert_estate_split_conserved,
    register_debtor, register_trustee, open_case, submit_means_test,
    add_income_and_expense_schedules, add_schedule, petition,
    schedule_meeting, hold_meeting,
    make_trustee_headers,
)


def _ch7_to_meeting_held(full_name, room_code, start, end, schedules):
    """Build a Chapter 7 case at MEETING_HELD with the given (letter, kwargs)
    schedule rows added before petition. Returns (debtor, trustee, case)."""
    debtor = register_debtor(full_name=full_name, prior_discharge_within_8y=False)
    trustee = register_trustee()
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    for letter, kwargs in schedules:
        add_schedule(debtor, case, letter, **kwargs)
    case = petition(debtor, case)
    meeting = schedule_meeting(trustee, case, room_code=room_code,
                               scheduled_start=start, scheduled_end=end)
    hold_meeting(trustee, meeting)
    return debtor, trustee, case


def test_discharge_over_exempt_clamp_floors_nonexempt_at_zero(api):
    """PRD §3.10: "nonexempt_estate_cents is set to that gross minus the total
    exempt value, floored at zero so an over-claim never produces a negative
    estate."

    Design: Difficulty/dual_variant_calc/discharge_exemption_settlement_over_exempt_clamp_variant
    """
    # Schedule A asset 500000; two Schedule C exemptions 400000 + 200000 = 600000.
    # 600000 > 500000 gross, but each C row is <= the running gross at add time so
    # the over-exemption guard does not block (400000 <= 500000, then 200000 added
    # after gross is 500000 already includes the 400000 exempt vs 500000 asset).
    debtor, trustee, case = _ch7_to_meeting_held(
        "Over Exempt Debtor", "R-OE",
        "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z",
        [("A", {"description": "house", "asset_value_cents": 500000}),
         ("C", {"description": "homestead exemption", "claimed_exempt_value_cents": 400000}),
         ("C", {"description": "extra exemption", "claimed_exempt_value_cents": 200000})])

    t_headers = make_trustee_headers(trustee["id"])
    res = api.discharge_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["total_exempt_value_cents"] == 600000
    assert after["nonexempt_estate_cents"] == 0
    assert after["status"] == "DISCHARGED"


def test_discharge_under_exempt_yields_positive_nonexempt(api):
    """PRD §3.10: "nonexempt_estate_cents is set to that gross minus the total
    exempt value, floored at zero". When exemptions are below gross the floor is
    not engaged and nonexempt = gross - exempt > 0 — the non-clamped variant that
    contrasts with the over-exempt clamp.

    Design: Difficulty/dual_variant_calc/discharge_exemption_settlement_over_exempt_clamp_variant
    """
    # Schedule A asset 500000; one Schedule C exemption 200000 (under gross).
    debtor, trustee, case = _ch7_to_meeting_held(
        "Under Exempt Debtor", "R-UE",
        "2026-07-15T09:00:00Z", "2026-07-15T10:00:00Z",
        [("A", {"description": "house", "asset_value_cents": 500000}),
         ("C", {"description": "homestead exemption", "claimed_exempt_value_cents": 200000})])

    t_headers = make_trustee_headers(trustee["id"])
    after = validate_success(api.discharge_case(case["id"], t_headers), 200)
    assert after["total_exempt_value_cents"] == 200000
    assert after["nonexempt_estate_cents"] == 300000  # 500000 - 200000, not floored
    assert after["status"] == "DISCHARGED"


def test_discharge_estate_value_conservation_exempt_plus_nonexempt(api):
    """PRD §3.10: "the gross asset value is the sum of asset_value_cents over the
    case's Schedule A and B rows, and nonexempt_estate_cents is set to that gross
    minus the total exempt value, floored at zero".

    Design: Difficulty/compensating_invariant/discharge_estate_value_conservation_exempt_plus_nonexempt
    """
    # Gross 1,000,000 (A 700000 + B 300000); exempt 400000 -> nonexempt 600000.
    debtor, trustee, case = _ch7_to_meeting_held(
        "Inv9a Debtor", "R-9a",
        "2026-07-06T09:00:00Z", "2026-07-06T10:00:00Z",
        [("A", {"description": "house", "asset_value_cents": 700000}),
         ("B", {"description": "car", "asset_value_cents": 300000}),
         ("C", {"description": "homestead", "claimed_exempt_value_cents": 400000})])

    t_headers = make_trustee_headers(trustee["id"])
    res = api.discharge_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["total_exempt_value_cents"] == 400000
    assert after["nonexempt_estate_cents"] == 600000
    assert after["status"] == "DISCHARGED"
    assert_estate_split_conserved(after, gross_asset_cents=1000000)


def test_discharge_estate_conservation_with_no_exemptions(api):
    """PRD §3.10: "the gross asset value is the sum of asset_value_cents over the
    case's Schedule A and B rows, and nonexempt_estate_cents is set to that gross
    minus the total exempt value". With zero claimed exemptions the entire gross
    is nonexempt and exempt + nonexempt == gross still holds.

    Design: Difficulty/compensating_invariant/discharge_estate_value_conservation_exempt_plus_nonexempt
    """
    # Gross 450000 (A 450000); no Schedule C -> exempt 0, nonexempt 450000.
    debtor, trustee, case = _ch7_to_meeting_held(
        "NoExempt Debtor", "R-NE",
        "2026-07-16T09:00:00Z", "2026-07-16T10:00:00Z",
        [("A", {"description": "house", "asset_value_cents": 450000})])

    t_headers = make_trustee_headers(trustee["id"])
    after = validate_success(api.discharge_case(case["id"], t_headers), 200)
    assert after["total_exempt_value_cents"] == 0
    assert after["nonexempt_estate_cents"] == 450000
    assert_estate_split_conserved(after, gross_asset_cents=450000)
