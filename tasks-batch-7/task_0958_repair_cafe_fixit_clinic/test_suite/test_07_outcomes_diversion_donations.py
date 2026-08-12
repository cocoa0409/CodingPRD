"""Outcome money fields, dual diversion accounting, and the two donation
valuations (PRD §3.5, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
    make_fixer_headers,
    create_monetary_donation_payload, create_in_kind_donation_payload,
    in_kind_line,
    set_logical_clock, create_event, setup_intake_open_event,
    progress_item_to_verified, progress_item_to_outcome_recorded,
    progress_item_to_in_repair, make_part_stock, reserve_part,
    commit_reservation,
)

COORD = TEST_USERS["coordinator_headers"]
INTAKE = TEST_USERS["intake_volunteer_headers"]


def _diversion_scenario():
    """One event with: item1 FIXED 3.2kg VERIFIED, item2 PARTIALLY_FIXED 2.0kg
    VERIFIED, item3 FIXED 5.0kg still RECORDED (unverified)."""
    ctx = setup_intake_open_event(event_name="Cafe Alpha")
    progress_item_to_verified(ctx, outcome="FIXED", weight_kg_actual=3.2,
                              description="Toaster dead",
                              weight_kg_estimated=3.0, severity=3,
                              estimated_difficulty=2, diagnosis="fuse")
    progress_item_to_verified(ctx, outcome="PARTIALLY_FIXED",
                              weight_kg_actual=2.0, description="Radio static",
                              weight_kg_estimated=2.5, severity=2,
                              estimated_difficulty=1, diagnosis="loose wire")
    _, outcome3 = progress_item_to_outcome_recorded(
        ctx, outcome="FIXED", weight_kg_actual=5.0,
        description="Laptop no power", weight_kg_estimated=4.0,
        severity=4, estimated_difficulty=3, diagnosis="psu")
    return ctx, outcome3


def test_diversion_kg_verified_vs_projected_diverge(api):
    """PRD §3.5: "Each outcome contributes its effective weight —
    `weight_kg_actual` when set, otherwise the item's `weight_kg_estimated` —
    in full when the outcome is `FIXED`, at half weight when `PARTIALLY_FIXED`,
    and at zero when `NOT_REPAIRABLE`. The event's `diversion_kg_verified` sums
    contributions over `VERIFIED` outcomes only and is recomputed at
    verification; the event's `diversion_kg_projected` additionally includes
    outcomes still in `RECORDED`, is recomputed at outcome recording, and
    diverges from the verified figure whenever any outcome awaits
    verification."

    Design: Difficulty/dual_variant_calc/diversion_kg_verified_vs_projected
    """
    ctx, _ = _diversion_scenario()
    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    # Verified: 3.2 (FIXED) + 0.5 * 2.0 (PARTIALLY_FIXED) = 4.2; the RECORDED
    # 5.0 kg outcome is excluded from the verified variant.
    assert event["diversion_kg_verified"] == pytest.approx(4.2, abs=0.01)
    # Projected additionally includes the still-RECORDED FIXED 5.0 kg outcome.
    assert event["diversion_kg_projected"] == pytest.approx(9.2, abs=0.01)
    assert event["diversion_kg_verified"] != event["diversion_kg_projected"], (
        "the variants diverge whenever any outcome awaits verification")


def test_diversion_kg_variants_converge_after_verify(api):
    """PRD §3.5: "Each outcome contributes its effective weight —
    `weight_kg_actual` when set, otherwise the item's `weight_kg_estimated` —
    in full when the outcome is `FIXED`, at half weight when `PARTIALLY_FIXED`,
    and at zero when `NOT_REPAIRABLE`. The event's `diversion_kg_verified` sums
    contributions over `VERIFIED` outcomes only and is recomputed at
    verification; the event's `diversion_kg_projected` additionally includes
    outcomes still in `RECORDED`, is recomputed at outcome recording, and
    diverges from the verified figure whenever any outcome awaits
    verification."

    Design: Difficulty/dual_variant_calc/diversion_kg_verified_vs_projected
    """
    ctx, outcome3 = _diversion_scenario()
    # Verify the last unverified outcome; now nothing awaits verification.
    validate_success(api.verify_outcome(outcome3["id"], COORD), 200)
    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["diversion_kg_verified"] == pytest.approx(9.2, abs=0.01)
    assert event["diversion_kg_projected"] == pytest.approx(9.2, abs=0.01)


# ─── donation receipt vs campaign value ─────────────────────────────────────

def test_donation_monetary_receipt_vs_campaign(api):
    """PRD §3.8: "Receipt (`PLEDGED → RECEIVED`) stamps `received_at` from the
    logical clock and computes — then freezes — two parallel valuations. The
    tax value, `receipt_value_cents`, equals `amount_cents` for a monetary
    gift; for an in-kind gift, each line's declared value is multiplied by an
    age multiplier — 0.8 when `age_years` is at most 1, 0.5 when at most 4, and
    0.2 beyond that — each line is rounded half-up to whole cents first, and
    only then are the lines summed. The `campaign_value_cents` rewards
    timeliness and generosity differently: a monetary donation counts double
    when `received_at` falls inside the linked event's window, from `starts_at`
    through `ends_at` inclusive, and counts at face value otherwise; an in-kind
    donation counts at the full sum of declared values with no depreciation and
    no per-line rounding."

    Design: Difficulty/dual_variant_calc/donation_receipt_vs_campaign_value
    """
    set_logical_clock()
    event = create_event(name="Cafe Beta")
    d1 = validate_success(api.create_donation(
        create_monetary_donation_payload(event_id=event["id"],
                                         amount_cents=5000),
        INTAKE), 201)
    received = validate_success(api.receive_donation(d1["id"], INTAKE), 200)
    assert received["receipt_value_cents"] == 5000, (
        "monetary receipt value equals amount_cents")
    # received_at (09:00) is inside the event window 08:00-16:00 -> doubled.
    assert received["campaign_value_cents"] == 10000


def test_donation_in_kind_receipt_vs_campaign(api):
    """PRD §3.8: "Receipt (`PLEDGED → RECEIVED`) stamps `received_at` from the
    logical clock and computes — then freezes — two parallel valuations. The
    tax value, `receipt_value_cents`, equals `amount_cents` for a monetary
    gift; for an in-kind gift, each line's declared value is multiplied by an
    age multiplier — 0.8 when `age_years` is at most 1, 0.5 when at most 4, and
    0.2 beyond that — each line is rounded half-up to whole cents first, and
    only then are the lines summed. The `campaign_value_cents` rewards
    timeliness and generosity differently: a monetary donation counts double
    when `received_at` falls inside the linked event's window, from `starts_at`
    through `ends_at` inclusive, and counts at face value otherwise; an in-kind
    donation counts at the full sum of declared values with no depreciation and
    no per-line rounding."

    Design: Difficulty/dual_variant_calc/donation_receipt_vs_campaign_value
    """
    set_logical_clock()
    event = create_event(name="Cafe Beta")
    lines = [in_kind_line(description="lamp", declared_value_cents=999,
                          age_years=3),
             in_kind_line(description="cable", declared_value_cents=501,
                          age_years=3)]
    d2 = validate_success(api.create_donation(
        create_in_kind_donation_payload(lines, event_id=event["id"]),
        INTAKE), 201)
    received = validate_success(api.receive_donation(d2["id"], INTAKE), 200)
    # Age 3 -> 0.5 multiplier; per-line round-half-up: 500 + 251 = 751.
    assert received["receipt_value_cents"] == 751
    # Campaign value: full declared sum, no depreciation, no rounding.
    assert received["campaign_value_cents"] == 1500


# ─── per-line rounding order ────────────────────────────────────────────────

def test_donation_receipt_per_line_rounding_order(api):
    """PRD §3.8: "Receipt (`PLEDGED → RECEIVED`) stamps `received_at` from the
    logical clock and computes — then freezes — two parallel valuations. The
    tax value, `receipt_value_cents`, equals `amount_cents` for a monetary
    gift; for an in-kind gift, each line's declared value is multiplied by an
    age multiplier — 0.8 when `age_years` is at most 1, 0.5 when at most 4, and
    0.2 beyond that — each line is rounded half-up to whole cents first, and
    only then are the lines summed."

    Design: Difficulty/combinatorial_formula/donation_receipt_per_line_rounding_order
    """
    set_logical_clock()
    # 999*0.5 = 499.5 -> 500 and 501*0.5 = 250.5 -> 251, summed to 751.
    # Sum-then-round would give round(1500*0.5) = 750 — the pinned order matters.
    lines = [in_kind_line(description="lamp", declared_value_cents=999,
                          age_years=3),
             in_kind_line(description="cable", declared_value_cents=501,
                          age_years=3)]
    donation = validate_success(api.create_donation(
        create_in_kind_donation_payload(lines), INTAKE), 201)
    received = validate_success(api.receive_donation(donation["id"], INTAKE), 200)
    assert received["receipt_value_cents"] == 751


def test_donation_receipt_age_tier_boundaries(api):
    """PRD §3.8: "Receipt (`PLEDGED → RECEIVED`) stamps `received_at` from the
    logical clock and computes — then freezes — two parallel valuations. The
    tax value, `receipt_value_cents`, equals `amount_cents` for a monetary
    gift; for an in-kind gift, each line's declared value is multiplied by an
    age multiplier — 0.8 when `age_years` is at most 1, 0.5 when at most 4, and
    0.2 beyond that — each line is rounded half-up to whole cents first, and
    only then are the lines summed."

    Design: Difficulty/combinatorial_formula/donation_receipt_per_line_rounding_order
    """
    set_logical_clock()
    # Tier boundaries: age 1 uses 0.8 ("at most 1"), age 2 uses 0.5
    # ("at most 4"), age 5 uses 0.2 ("beyond that").
    lines = [in_kind_line(description="new", declared_value_cents=1000,
                          age_years=1),
             in_kind_line(description="mid", declared_value_cents=1000,
                          age_years=2),
             in_kind_line(description="old", declared_value_cents=1000,
                          age_years=5)]
    donation = validate_success(api.create_donation(
        create_in_kind_donation_payload(lines), INTAKE), 201)
    received = validate_success(api.receive_donation(donation["id"], INTAKE), 200)
    assert received["receipt_value_cents"] == 800 + 500 + 200


# ─── suggested donation pinned evaluation order ─────────────────────────────

def test_suggested_donation_electronics_pinned_order(api):
    """PRD §3.5: "The `suggested_donation_cents` is computed in a pinned order:
    take a category base of 1500 cents for `ELECTRONICS`, 800 cents for
    `TEXTILE`, or 1000 cents for `BIKE`; choose the parts-share rate keyed on
    that base alone — one half when the base is below 1000 cents, three fifths
    when it is below 1500 cents, three quarters otherwise; multiply
    `parts_cost_cents` by that rate and round half-up to whole cents to get the
    share; the suggestion is then the smaller of 5000 cents and the base plus
    the share."
    PRD §3.5: "The `parts_cost_cents` is the sum of `cost_cents` over the
    item's `COMMITTED` reservations."

    Design: Difficulty/combinatorial_formula/suggested_donation_circular_order_pinned
    """
    ctx = setup_intake_open_event(event_name="Cafe Delta")
    item = progress_item_to_in_repair(ctx, description="Toaster",
                                      weight_kg_estimated=3.0)
    stock = make_part_stock(sku="FUSE-10A", name="10A fuse",
                            unit_cost_cents=400, quantity_on_hand=5)
    reservation = reserve_part(stock["id"], item["id"], 2, ctx["fixer"]["id"])
    commit_reservation(reservation["id"], ctx["fixer"]["id"])

    outcome = validate_success(api.record_outcome(
        item["id"], {"outcome": "FIXED", "weight_kg_actual": 3.0},
        make_fixer_headers(ctx["fixer"]["id"])), 201)
    assert outcome["parts_cost_cents"] == 800
    # ELECTRONICS base 1500 -> "otherwise" rate 0.75; share = round(800*0.75)
    # = 600; total = min(5000, 1500 + 600) = 2100.
    assert outcome["suggested_donation_cents"] == 2100


def test_suggested_donation_textile_half_rate(api):
    """PRD §3.5: "The `suggested_donation_cents` is computed in a pinned order:
    take a category base of 1500 cents for `ELECTRONICS`, 800 cents for
    `TEXTILE`, or 1000 cents for `BIKE`; choose the parts-share rate keyed on
    that base alone — one half when the base is below 1000 cents, three fifths
    when it is below 1500 cents, three quarters otherwise; multiply
    `parts_cost_cents` by that rate and round half-up to whole cents to get the
    share; the suggestion is then the smaller of 5000 cents and the base plus
    the share."
    PRD §3.5: "The `parts_cost_cents` is the sum of `cost_cents` over the
    item's `COMMITTED` reservations."

    Design: Difficulty/combinatorial_formula/suggested_donation_circular_order_pinned
    """
    ctx = setup_intake_open_event(category="TEXTILE", skill_level=4,
                                  event_name="Cafe Delta-2")
    item = progress_item_to_in_repair(ctx, category="TEXTILE",
                                      description="Torn coat",
                                      weight_kg_estimated=1.0)
    stock = make_part_stock(name="denim patch", category="TEXTILE",
                            unit_cost_cents=500, quantity_on_hand=5)
    reservation = reserve_part(stock["id"], item["id"], 2, ctx["fixer"]["id"])
    commit_reservation(reservation["id"], ctx["fixer"]["id"])

    outcome = validate_success(api.record_outcome(
        item["id"], {"outcome": "FIXED", "weight_kg_actual": 1.0},
        make_fixer_headers(ctx["fixer"]["id"])), 201)
    assert outcome["parts_cost_cents"] == 1000
    # TEXTILE base 800 < 1000 -> rate 0.5; share = round(1000*0.5) = 500;
    # total = min(5000, 800 + 500) = 1300.
    assert outcome["suggested_donation_cents"] == 1300


# ─── outcome verification idempotency ───────────────────────────────────────

def test_outcome_verify_twice_returns_invalid_outcome_state(api):
    """PRD §3.5: "Verification requires the outcome to be `RECORDED`
    (`ERR_INVALID_OUTCOME_STATE`), requires that a fixer acting as verifier is
    not the outcome's `fixer_id` (`ERR_SELF_VERIFICATION_FORBIDDEN`), and
    requires that no `SafetyIncident` of any severity in status `REPORTED`
    exists for the item (`ERR_SAFETY_HOLD`)."

    Design: Corner/state_machines/outcome_verify_twice_returns_invalid_outcome_state
    """
    ctx = setup_intake_open_event(event_name="Cafe Omega")
    item, outcome_rec = progress_item_to_verified(
        ctx, outcome="FIXED", weight_kg_actual=1.4, description="Kettle",
        weight_kg_estimated=1.5, severity=2, estimated_difficulty=1,
        diagnosis="element")
    assert outcome_rec["verification_status"] == "VERIFIED"
    verifier = outcome_rec["verified_by_user_id"]

    # Second verify: the outcome is no longer RECORDED.
    res = api.verify_outcome(outcome_rec["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_OUTCOME_STATE)
    outcome_after = validate_success(api.get_outcome(outcome_rec["id"], COORD), 200)
    assert outcome_after["verification_status"] == "VERIFIED"
    assert outcome_after["verified_by_user_id"] == verifier
