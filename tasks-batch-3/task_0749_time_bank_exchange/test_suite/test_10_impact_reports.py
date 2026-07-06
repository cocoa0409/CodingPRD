"""Impact reports: total_hours_exchanged rounding, gross vs net, top-skill tie break."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_member_headers,
    create_member, seed_balance, set_clock,
)


# =============================================================================
# Rule 1 — dual_variant_calc / gross_vs_net_hours_on_impact_report
# =============================================================================

def _drive_dispute_upheld_settlement(api, committed_minutes: int,
                                     claimed_delta_minutes: int) -> dict:
    """Build one dispute-upheld exchange in March 2026 and return context."""
    set_clock("2026-03-14T09:00:00Z")
    m1 = create_member(email_prefix="m1")
    m2 = create_member(email_prefix="m2")
    seed_balance(m1["id"], 1200)
    offer = get_success_data(api.create_skill_offer(
        {"member_id": m2["id"], "skill_code": "TUTORING_MATH",
         "title": "Math", "minutes_per_session": committed_minutes},
        headers=make_member_headers(m2["id"]),
    ))
    request = get_success_data(api.create_skill_request(
        {"member_id": m1["id"], "skill_code": "TUTORING_MATH",
         "needed_minutes": committed_minutes,
         "earliest_start_utc": "2026-03-15T10:00:00Z",
         "latest_start_utc": "2026-03-15T14:00:00Z"},
        headers=make_member_headers(m1["id"]),
    ))
    exch = get_success_data(api.create_exchange(
        {"offer_id": offer["id"], "request_id": request["id"],
         "scheduled_start_utc": "2026-03-15T10:00:00Z",
         "committed_minutes": committed_minutes},
        headers=make_member_headers(m1["id"]),
    ))
    set_clock("2026-03-15T11:30:00Z")
    get_success_data(api.mark_exchange_delivered(
        exch["id"], headers=make_member_headers(m2["id"]),
    ))
    dispute = get_success_data(api.create_dispute(
        {"exchange_id": exch["id"], "raised_by_member_id": m1["id"],
         "reason_code": "WRONG_DURATION",
         "claimed_delta_minutes": claimed_delta_minutes},
        headers=make_member_headers(m1["id"]),
    ))
    get_success_data(api.resolve_dispute(
        dispute["id"],
        {"outcome": "UPHELD", "admin_notes": "Confirmed shortfall."},
        headers=TEST_USERS["admin_headers"],
    ))
    set_clock("2026-04-01T01:00:00Z")
    return {"m1": m1, "m2": m2, "exch": exch}


def test_impact_report_gross_hours_uses_full_committed_minutes(api):
    """PRD §3.7: "This gross figure includes exchanges that reached SETTLED via
    a dispute-upheld reduced credit, and it uses the full committed_minutes
    value rather than the reduced credit"

    Design: Difficulty/dual_variant_calc/gross_vs_net_hours_on_impact_report
    """
    _drive_dispute_upheld_settlement(api, committed_minutes=120,
                                     claimed_delta_minutes=30)
    resp = api.create_impact_report(
        {"report_month": "2026-03"},
        headers=TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_hours_exchanged"] == pytest.approx(2.00, abs=0.001)


def test_provider_earned_ledger_reflects_reduced_credit(api):
    """PRD §3.4: "For the provider, an EARNED entry with delta_minutes equal to
    the positive of that same reduced amount."

    Design: Difficulty/dual_variant_calc/gross_vs_net_hours_on_impact_report
    """
    ctx = _drive_dispute_upheld_settlement(api, committed_minutes=120,
                                           claimed_delta_minutes=30)
    resp = api.list_ledger_entries(
        headers=make_member_headers(ctx["m2"]["id"]),
        params={"member_id": ctx["m2"]["id"], "entry_kind": "EARNED"},
    )
    from test_helpers import validate_paginated as _vp
    entries, _ = _vp(resp)
    earned_sum = sum(e["delta_minutes"] for e in entries if e["entry_kind"] == "EARNED")
    # Reduced credit = 120 - 30 = 90 minutes
    assert earned_sum == 90


# =============================================================================
# Rule 2 — combinatorial_formula / report_hours_rounding_order_pinned_mode_b
# =============================================================================

def _drive_single_settled_exchange(api, committed_minutes: int) -> None:
    """Settle exactly one exchange of the given size inside March 2026."""
    set_clock("2026-03-01T09:00:00Z")
    m1 = create_member(email_prefix="req")
    m2 = create_member(email_prefix="prov")
    seed_balance(m1["id"], 300)
    offer = get_success_data(api.create_skill_offer(
        {"member_id": m2["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": committed_minutes},
        headers=make_member_headers(m2["id"]),
    ))
    request = get_success_data(api.create_skill_request(
        {"member_id": m1["id"], "skill_code": "GARDENING",
         "needed_minutes": committed_minutes,
         "earliest_start_utc": "2026-03-02T09:00:00Z",
         "latest_start_utc": "2026-03-02T18:00:00Z"},
        headers=make_member_headers(m1["id"]),
    ))
    exch = get_success_data(api.create_exchange(
        {"offer_id": offer["id"], "request_id": request["id"],
         "scheduled_start_utc": "2026-03-02T09:00:00Z",
         "committed_minutes": committed_minutes},
        headers=make_member_headers(m1["id"]),
    ))
    # Advance well past the exchange end (scheduled_start + committed_minutes)
    set_clock("2026-03-02T18:00:00Z")
    get_success_data(api.mark_exchange_delivered(
        exch["id"], headers=make_member_headers(m2["id"]),
    ))
    get_success_data(api.settle_exchange(
        exch["id"], headers=make_member_headers(m1["id"]),
    ))
    set_clock("2026-04-01T00:00:00Z")


def test_impact_report_15min_exchange_yields_0_25_hours(api):
    """PRD §2.10: "for each settled exchange within the reporting month, the
    exchange's committed_minutes is divided by 60 and the result is rounded
    half-up to two decimal places; those per-exchange rounded values are
    then summed; and the final sum is rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/report_hours_rounding_order_pinned_mode_b
    """
    _drive_single_settled_exchange(api, committed_minutes=15)
    resp = api.create_impact_report(
        {"report_month": "2026-03"},
        headers=TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_hours_exchanged"] == pytest.approx(0.25, abs=0.001)


def test_impact_report_45min_exchange_yields_0_75_hours(api):
    """PRD §2.10: "ImpactReport.total_hours_exchanged is a decimal with two
    fractional digits and is computed with round-half-up: for each settled
    exchange within the reporting month, the exchange's committed_minutes
    is divided by 60 and the result is rounded half-up to two decimal
    places; those per-exchange rounded values are then summed; and the
    final sum is rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/report_hours_rounding_order_pinned_mode_b
    """
    _drive_single_settled_exchange(api, committed_minutes=45)
    resp = api.create_impact_report(
        {"report_month": "2026-03"},
        headers=TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_hours_exchanged"] == pytest.approx(0.75, abs=0.001)


# =============================================================================
# Corner — top_skill tie-break
# =============================================================================

def test_top_skill_tie_break_by_earliest_settled_at_utc(api):
    """PRD §3.7: "top_skill_code is the skill_code appearing on the most SETTLED
    exchanges in the month, with a pinned tie-break sequence: among tied
    skill codes, the code whose earliest settled exchange in the month has
    the earliest settled_at_utc wins"

    Design: Corner/calculations/report_top_skill_tie_break_earliest_settled
    """
    set_clock("2026-03-01T09:00:00Z")
    m1 = create_member(email_prefix="ts1")
    m2 = create_member(email_prefix="ts2")
    seed_balance(m1["id"], 240)
    o_g = get_success_data(api.create_skill_offer(
        {"member_id": m2["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": 60},
        headers=make_member_headers(m2["id"]),
    ))
    o_t = get_success_data(api.create_skill_offer(
        {"member_id": m2["id"], "skill_code": "TUTORING_MATH",
         "title": "T", "minutes_per_session": 60},
        headers=make_member_headers(m2["id"]),
    ))
    r_g = get_success_data(api.create_skill_request(
        {"member_id": m1["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(m1["id"]),
    ))
    r_t = get_success_data(api.create_skill_request(
        {"member_id": m1["id"], "skill_code": "TUTORING_MATH",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-06T10:00:00Z",
         "latest_start_utc": "2026-03-06T18:00:00Z"},
        headers=make_member_headers(m1["id"]),
    ))
    e_g = get_success_data(api.create_exchange(
        {"offer_id": o_g["id"], "request_id": r_g["id"],
         "scheduled_start_utc": "2026-03-05T10:00:00Z", "committed_minutes": 60},
        headers=make_member_headers(m1["id"]),
    ))
    e_t = get_success_data(api.create_exchange(
        {"offer_id": o_t["id"], "request_id": r_t["id"],
         "scheduled_start_utc": "2026-03-06T10:00:00Z", "committed_minutes": 60},
        headers=make_member_headers(m1["id"]),
    ))
    set_clock("2026-03-05T11:00:00Z")
    get_success_data(api.mark_exchange_delivered(e_g["id"], headers=make_member_headers(m2["id"])))
    get_success_data(api.settle_exchange(e_g["id"], headers=make_member_headers(m1["id"])))
    set_clock("2026-03-06T11:00:00Z")
    get_success_data(api.mark_exchange_delivered(e_t["id"], headers=make_member_headers(m2["id"])))
    get_success_data(api.settle_exchange(e_t["id"], headers=make_member_headers(m1["id"])))
    set_clock("2026-04-01T00:00:00Z")

    resp = api.create_impact_report(
        {"report_month": "2026-03"},
        headers=TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["top_skill_code"] == "GARDENING"
