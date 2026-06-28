"""Pricing tests: the forward-looking estimate vs. the contracted baseline, per-line
bride rounding, the tiered deposit split, and the throughput capacity boundary.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    setup_quoted_event,
    setup_scheduled_event,
    setup_deposit_paid_event,
    sign_contract,
    apply_addon,
    schedule_assignment,
    make_client_headers,
)


# ─── Rule: dual_variant_calc ──────────────────────────
def test_quote_and_contract_totals_diverge(api):
    """PRD §3.4: "The `contracted_total_cents` is the sum of the per-face subtotal and the
    travel fee. Because it excludes pending faces and uses pinned rather than cheapest-lead
    rates, the contracted total will generally differ from the `estimated_total_cents` the
    client saw at quote time."
    PRD §3.4: "It counts every face the client might bring — those in `PENDING` *or*
    `CONFIRMED` status — because before any face is confirmed the estimate should reflect
    the largest plausible party."

    Design: Difficulty/dual_variant_calc/quote_vs_contract_total_diverge
    """
    setup = setup_quoted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
            {"person_label": "BRIDESMAID_2", "service_type": "MAKEUP", "confirm": False},
        ],
    )
    # Quote includes the PENDING MAKEUP face: bride BOTH 45000*1.5=67500 + HAIR 20000
    #   + MAKEUP(pending) 25000 + travel 6000 = 118500.
    assert setup["event"]["estimated_total_cents"] == 118500, (
        f"Expected estimate 118500, got {setup['event']['estimated_total_cents']}"
    )

    resp = api.create_contract(
        {"event_id": setup["event_id"], "lead_artist_id": setup["lead_artist_id"],
         "expected_event_version": setup["quote_version"]},
        make_client_headers("client-1"),
    )
    contract = validate_success(resp, 201)
    # Contract counts CONFIRMED only at pinned rates: 67500 + 20000 + travel 6000 = 93500.
    assert contract["contracted_total_cents"] == 93500, (
        f"Expected contracted total 93500, got {contract['contracted_total_cents']}"
    )
    assert contract["contracted_total_cents"] != setup["event"]["estimated_total_cents"]


def test_balance_with_addon_diverges_from_contracted_baseline(api):
    """PRD §3.8: "Once at least one add-on has been applied, the reconciled balance includes
    those add-on amounts and therefore diverges from the bare contracted baseline."
    PRD §3.8: "the gross amount due is the contract's `contracted_total_cents` plus the
    applied add-ons; the `balance_amount_cents` is the gross due minus the paid total minus
    any cancellation relief that has been written off, floored at zero so the balance is
    never negative".

    Design: Difficulty/dual_variant_calc/balance_addon_vs_cancellation_relief_diverge
    """
    setup = setup_scheduled_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T10:00:00Z",
    )
    # contract 93500, deposit 28050 paid by the fixture. TOUCH_UP qty 2 bills 25000.
    addon = apply_addon(setup["assignment_id"], "TOUCH_UP", 2)
    assert addon["amount_cents"] == 25000, f"Expected add-on 25000, got {addon['amount_cents']}"

    invoice = validate_success(
        api.get_invoice(setup["invoice_id"], make_client_headers("client-1")), 200
    )
    # balance = 93500 + 25000 - 28050 = 90450, which diverges from contracted baseline 93500.
    assert invoice["balance_amount_cents"] == 90450, (
        f"Expected balance 90450, got {invoice['balance_amount_cents']}"
    )
    assert invoice["balance_amount_cents"] != setup["contracted_total_cents"]


# ─── Rule: combinatorial_formula ──────────────────────
def test_per_line_bride_rounding_before_sum(api):
    """PRD §3.4: "If the face is a bride, that per-face base is multiplied by the bride
    surcharge multiplier of 1.5 and rounded half-up to a whole cent before being added to
    the running per-face subtotal — this per-line rounding happens on each bride line
    individually."

    Design: Difficulty/combinatorial_formula/per_line_bride_rounding_before_sum
    """
    setup = setup_quoted_event(
        client_id="client-2",
        artist_overrides=dict(
            hair_rate_per_face_cents=10001, makeup_rate_per_face_cents=10000,
            travel_rate_per_km_cents=333, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=3),
        faces=[
            {"person_label": "BRIDE_A", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDE_B", "service_type": "BOTH", "is_bride": True, "confirm": True},
        ],
    )
    contract = sign_contract(
        setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-2"
    )
    # Each bride BOTH base = 20001, *1.5 = 30001.5 -> 30002 per line; two lines = 60004.
    # travel = 333*3 = 999. Total = 61003. (sum-then-round would give 61002.)
    assert contract["contracted_total_cents"] == 61003, (
        f"Expected 61003 (per-line rounding), got {contract['contracted_total_cents']}"
    )


def test_deposit_tier_selection_mid_band(api):
    """PRD §3.7: "If it is at least 50,000 cents but below 200,000 cents, the percentage is
    30 percent."
    PRD §3.7: "The `deposit_due_cents` is the contracted total multiplied by the chosen
    percentage, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/deposit_tier_selection_three_inputs
    """
    setup = setup_quoted_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
    )
    contract = sign_contract(
        setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-1"
    )
    # contracted_total 93500 lands in MID band -> 0.30 -> 28050.
    assert contract["contracted_total_cents"] == 93500
    assert contract["deposit_due_cents"] == 28050, (
        f"Expected deposit 28050, got {contract['deposit_due_cents']}"
    )


# ─── Rule: boundary_precision_check ───────────────────
def test_deposit_tier_boundary_at_exactly_50000(api):
    """PRD §3.7: "The tier boundaries are half-open from below: a contracted total of exactly
    50,000 cents falls in the middle (30 percent) tier, and exactly 200,000 cents falls in
    the top (40 percent) tier."

    Design: Difficulty/boundary_precision_check/deposit_tier_boundary_at_50000
    """
    setup = setup_quoted_event(
        client_id="client-3",
        artist_overrides=dict(
            hair_rate_per_face_cents=25000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=0, max_faces_per_hour=4,
        ),
        event_overrides=dict(venue_distance_km=0),
        faces=[
            {"person_label": "GUEST", "service_type": "BOTH", "is_bride": False, "confirm": True},
        ],
    )
    contract = sign_contract(
        setup["event_id"], setup["lead_artist_id"], setup["quote_version"], "client-3"
    )
    # total exactly 50000 -> MID band 0.30 -> 15000 (NOT 12500 the LOW band would give).
    assert contract["contracted_total_cents"] == 50000
    assert contract["deposit_due_cents"] == 15000, (
        f"Expected deposit 15000 at the 50000 boundary, got {contract['deposit_due_cents']}"
    )


def test_throughput_capacity_exactly_meets_faces(api):
    """PRD §3.12: "The window is sufficient when this floored capacity is greater than or
    equal to the `CONFIRMED` face count; if the capacity equals the confirmed count exactly,
    the window passes, but if it falls even one face short the schedule is rejected with
    `ERR_INSUFFICIENT_THROUGHPUT`."
    PRD §3.10: "records `faces_committed`, the count of `CONFIRMED` faces on the event at
    scheduling time."

    Design: Difficulty/boundary_precision_check/throughput_capacity_exactly_meets_faces
    """
    setup = setup_deposit_paid_event(
        client_id="client-1",
        artist_overrides=dict(
            hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
            travel_rate_per_km_cents=600, max_faces_per_hour=2,
        ),
        event_overrides=dict(venue_distance_km=10),
        faces=[
            {"person_label": "BRIDE", "service_type": "BOTH", "is_bride": True, "confirm": True},
            {"person_label": "BRIDESMAID_1", "service_type": "HAIR", "confirm": True},
        ],
    )
    # capacity floor((2+0)*1.0) = 2 == 2 CONFIRMED faces -> PASSES.
    assignment = schedule_assignment(
        setup["event_id"], setup["lead_artist_id"], setup["post_deposit_version"],
        window_start_utc="2026-07-15T08:00:00Z", window_end_utc="2026-07-15T09:00:00Z",
    )
    assert assignment["status"] == "SCHEDULED"
    assert assignment["faces_committed"] == 2, (
        f"Expected faces_committed 2, got {assignment['faces_committed']}"
    )
