"""Valuation and pricing: dual-variant haul fee and tax-receipt value, the
combinatorial haul formula (tiered + surcharge + capped credit), the pinned
round-per-item-then-sum order, and the tier boundary.

Difficulty instances: dual_variant_calc/*, combinatorial_formula/*,
boundary_precision_check/haul_fee_tier_boundary_100_vs_101.
Corner instances: calculations/*.
"""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    schedule_payload,
    setup_schedulable_request, setup_scheduled_request,
    setup_completed_donation, setup_completed_haul,
    complete_request,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

FURN = "FURNITURE"
HH = "HOUSEHOLD"
PORCH = "https://example.com/porch.jpg"


# ─── Difficulty: dual-variant haul fee (estimate vs final) ────────────

def test_haul_invoice_estimate_and_final_diverge_by_credit():
    """PRD §3.6: "The final variant produces the invoice's final_cents (the
    subtotal before credit) and amount_due_cents: it uses V equal to the
    request's measured_volume_cf and computes the diversion credit from the
    appraised streams and weights of the request's items, recording that credit
    in diversion_credit_cents."
    PRD §3.6: "The amount due is the subtotal minus the credit, but never below
    zero."

    Design: Difficulty/dual_variant_calc/haul_fee_estimate_vs_final
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 120, "weight_lbs": 300,
                "declared_value_cents": 1000, "declared_condition": "GOOD"}],
        appraisals=[{"weight_lbs": 300, "stream": "RECYCLE"}],
        measured_volume_cf=120, pickup_mode="ATTENDED", capacity_cf=300,
    )
    invoice = ctx["invoice"]
    assert invoice["estimate_cents"] == 10700
    assert invoice["final_cents"] == 10700
    assert invoice["diversion_credit_cents"] == 1500
    assert invoice["amount_due_cents"] == 9200


def test_haul_estimate_forces_zero_diversion_credit():
    """PRD §3.6: "The estimate variant is what feeds estimated_haul_fee_cents on
    each item add and is snapshotted into the invoice's estimate_cents at
    completion: it uses V equal to the request's declared_volume_cf and forces
    the diversion credit to zero, since nothing has been appraised."

    Design: Difficulty/dual_variant_calc/haul_fee_estimate_vs_final
    """
    ctx = setup_schedulable_request(
        partner_categories=[FURN], capacity_cf=300, disposition="HAUL",
        pickup_mode="ATTENDED",
        items=[{"category": FURN, "volume_cf": 120, "weight_lbs": 300,
                "declared_value_cents": 1000, "declared_condition": "GOOD"}],
    )
    request = validate_success(api.get_pickup_request(ctx["request"]["id"], DISPATCHER), 200)
    # 3500 base + tiered(120)=5200 + attended 2000, no credit = 10700.
    assert request["estimated_haul_fee_cents"] == 10700


# ─── Difficulty: dual-variant tax receipt (provisional vs final) ──────

def test_receipt_provisional_and_final_values():
    """PRD §3.6: "Its provisional_value_cents is computed from every item's
    donor-declared inputs — declared_value_cents paired with declared_condition
    — and represents the request before appraisal."
    PRD §3.6: "Its final_value_cents, set at issuance, is computed per item from
    the appraised inputs when the item has been appraised (its
    appraised_value_cents is present), using appraised_value_cents with
    appraised_condition, and otherwise from that item's declared pair."

    Design: Difficulty/dual_variant_calc/tax_receipt_provisional_vs_final
    """
    ctx = setup_completed_donation(
        items=[{"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"},
               {"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"}],
        appraisals=[{"appraised_value_cents": 2000, "appraised_condition": "FAIR", "stream": "REUSE"},
                    {"appraised_value_cents": 2000, "appraised_condition": "FAIR", "stream": "REUSE"}],
        measured_volume_cf=50, capacity_cf=200,
    )
    receipt = ctx["receipt"]
    assert receipt["provisional_value_cents"] == 1408
    assert receipt["final_value_cents"] == 1600
    assert receipt["status"] == "ISSUED"


def test_receipt_final_mixes_appraised_and_declared_per_item():
    """PRD §3.6: "Its final_value_cents, set at issuance, is computed per item
    from the appraised inputs when the item has been appraised (its
    appraised_value_cents is present), using appraised_value_cents with
    appraised_condition, and otherwise from that item's declared pair."

    Design: Difficulty/dual_variant_calc/tax_receipt_provisional_vs_final
    """
    # Only the first item is appraised; the second falls back to its declared pair.
    ctx = setup_completed_donation(
        items=[{"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"},
               {"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"}],
        appraisals=[{"appraised_value_cents": 2000, "appraised_condition": "FAIR", "stream": "REUSE"},
                    None],
        measured_volume_cf=50, capacity_cf=200,
    )
    receipt = ctx["receipt"]
    # final = round(2000*0.40)=800 (appraised) + round(1005*0.70)=704 (declared) = 1504.
    assert receipt["final_value_cents"] == 1504
    # provisional is unaffected by appraisal: round(703.5)*2 = 1408.
    assert receipt["provisional_value_cents"] == 1408


# ─── Difficulty: combinatorial haul formula (mode a) ──────────────────

def test_haul_full_invoice_with_capped_diversion_credit():
    """PRD §3.6: "sum the weight_lbs of the request's items whose stream is
    RECYCLE or REUSE, multiply that diverted weight by 5 cents per pound, and
    cap the result at 30 percent of the subtotal, where the cap is computed as
    the subtotal times 0.30 rounded half-up to whole cents; the credit is the
    smaller of the per-pound amount and that cap."

    Design: Difficulty/combinatorial_formula/haul_fee_tiered_surcharge_credit_mode_a
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 50, "weight_lbs": 5000,
                "declared_value_cents": 100, "declared_condition": "GOOD"}],
        appraisals=[{"weight_lbs": 5000, "stream": "RECYCLE"}],
        measured_volume_cf=50, pickup_mode="UNATTENDED",
        porch_photo_url=PORCH, safety_attestation=True, capacity_cf=100,
    )
    invoice = ctx["invoice"]
    assert invoice["final_cents"] == 5500
    assert invoice["diversion_credit_cents"] == 1650
    assert invoice["amount_due_cents"] == 3850


def test_haul_diversion_credit_bound_by_thirty_percent_cap():
    """PRD §3.6: "cap the result at 30 percent of the subtotal, where the cap is
    computed as the subtotal times 0.30 rounded half-up to whole cents; the
    credit is the smaller of the per-pound amount and that cap."

    Design: Difficulty/combinatorial_formula/haul_fee_tiered_surcharge_credit_mode_a
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 50, "weight_lbs": 5000,
                "declared_value_cents": 100, "declared_condition": "GOOD"}],
        appraisals=[{"weight_lbs": 5000, "stream": "RECYCLE"}],
        measured_volume_cf=50, pickup_mode="UNATTENDED",
        porch_photo_url=PORCH, safety_attestation=True, capacity_cf=100,
    )
    invoice = ctx["invoice"]
    # Per-pound amount 5*5000=25000 is capped to round(0.30*5500)=1650.
    assert invoice["diversion_credit_cents"] == 1650
    assert invoice["diversion_credit_cents"] < 25000


# ─── Difficulty: round-per-item-then-sum (mode b) ─────────────────────

def test_receipt_provisional_rounds_each_item_before_summing():
    """PRD §3.6: "for each item, multiply its value by the factor of its
    condition and round that product to whole cents using round-half-up; then
    add the rounded per-item results together."
    PRD §3.6: "Rounding is applied to each item first and the whole-cent results
    are summed afterward — never sum first and round once."

    Design: Difficulty/combinatorial_formula/tax_receipt_round_per_item_then_sum_mode_b
    """
    ctx = setup_completed_donation(
        items=[{"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"},
               {"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"}],
        measured_volume_cf=50, capacity_cf=100,
    )
    # round(703.5)=704 per item, summed = 1408 (NOT sum-then-round 1407).
    assert ctx["receipt"]["provisional_value_cents"] == 1408


def test_receipt_final_mirrors_declared_when_unappraised():
    """PRD §3.6: "Its final_value_cents, set at issuance, is computed per item
    from the appraised inputs when the item has been appraised (its
    appraised_value_cents is present), using appraised_value_cents with
    appraised_condition, and otherwise from that item's declared pair."

    Design: Difficulty/combinatorial_formula/tax_receipt_round_per_item_then_sum_mode_b
    """
    ctx = setup_completed_donation(
        items=[{"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"},
               {"category": HH, "volume_cf": 25, "weight_lbs": 10,
                "declared_value_cents": 1005, "declared_condition": "GOOD"}],
        measured_volume_cf=50, capacity_cf=100,
    )
    # No appraisal → final mirrors declared = 704 + 704 = 1408.
    assert ctx["receipt"]["final_value_cents"] == 1408


# ─── Difficulty: haul tier boundary 100 vs 101 ────────────────────────

def test_haul_final_at_volume_100_within_tier_a():
    """PRD §3.6: "40 cents for each of the first 100 cubic feet; 60 cents for
    each cubic foot above 100 up to and including 250 (that is, the next 150
    cubic feet)"

    Design: Difficulty/boundary_precision_check/haul_fee_tier_boundary_100_vs_101
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 100, "weight_lbs": 0,
                "declared_value_cents": 100, "declared_condition": "GOOD"}],
        measured_volume_cf=100, pickup_mode="UNATTENDED",
        porch_photo_url=PORCH, safety_attestation=True, capacity_cf=300,
    )
    # 3500 base + tiered(100)=4000 = 7500.
    assert ctx["invoice"]["final_cents"] == 7500


def test_haul_final_at_volume_101_crosses_into_tier_b():
    """PRD §3.6: "40 cents for each of the first 100 cubic feet; 60 cents for
    each cubic foot above 100 up to and including 250 (that is, the next 150
    cubic feet)"

    Design: Difficulty/boundary_precision_check/haul_fee_tier_boundary_100_vs_101
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 101, "weight_lbs": 0,
                "declared_value_cents": 100, "declared_condition": "GOOD"}],
        measured_volume_cf=101, pickup_mode="UNATTENDED",
        porch_photo_url=PORCH, safety_attestation=True, capacity_cf=300,
    )
    # 3500 base + tiered(101)=100*40 + 1*60 = 4060 = 7560.
    assert ctx["invoice"]["final_cents"] == 7560


# ─── Corner: calculations ─────────────────────────────────────────────

def test_attended_surcharge_applied_to_haul_fee():
    """PRD §3.6: "plus — only when the request's `pickup_mode` is `ATTENDED` — a surcharge of 2,000 cents."

    Design: Corner/calculations/attended_surcharge_applied_to_haul_fee
    """
    ctx = setup_completed_haul(
        items=[{"category": FURN, "volume_cf": 50, "weight_lbs": 0,
                "declared_value_cents": 100, "declared_condition": "GOOD"}],
        measured_volume_cf=50, pickup_mode="ATTENDED", capacity_cf=100,
    )
    invoice = ctx["invoice"]
    # 3500 base + tiered(50)=2000 + attended 2000 = 7500; no diversion → amount_due equal.
    assert invoice["final_cents"] == 7500
    assert invoice["amount_due_cents"] == 7500


def test_reserved_volume_excludes_serviced_stop():
    """PRD §3.3: "Its reserved_volume_cf is always the sum of the
    reserved_volume_cf snapshots of its stops that are currently RESERVED —
    stops that have moved to SERVICED or CANCELLED no longer contribute."
    PRD §3.3: "Its serviced_stop_count is the number of its stops that are
    SERVICED."

    Design: Corner/calculations/reserved_volume_excludes_serviced_stop
    """
    ctx = setup_scheduled_request(partner_categories=[FURN], disposition="DONATION",
                                  items=[{"category": FURN, "volume_cf": 30}])
    complete_request(ctx["request"]["id"], 30)
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER), 200)
    assert route["reserved_volume_cf"] == 0
    assert route["serviced_stop_count"] == 1


def test_donation_over_volume_limit_boundary():
    """PRD §3.4: "If the request's disposition is DONATION, its
    declared_volume_cf must be at most 50 cubic feet; a larger donation is
    rejected with ERR_DONATION_OVER_LIMIT."

    Design: Corner/calculations/donation_over_volume_limit_boundary_50_vs_51
    """
    # 51 (over the cap) is rejected at schedule.
    over = setup_schedulable_request(partner_categories=[FURN], capacity_cf=200,
                                     disposition="DONATION",
                                     items=[{"category": FURN, "volume_cf": 51}])
    res = api.schedule_pickup(
        over["request"]["id"],
        schedule_payload(over["route"]["id"], over["route_version"],
                         "2026-03-15T10:00:00Z", "2026-03-15T10:30:00Z"),
        DISPATCHER,
    )
    validate_error(res, "ERR_DONATION_OVER_LIMIT", expected_status=422)

    # 50 (exactly the cap) is allowed.
    at = setup_schedulable_request(partner_categories=[FURN], capacity_cf=200,
                                   disposition="DONATION",
                                   items=[{"category": FURN, "volume_cf": 50}])
    ok = api.schedule_pickup(
        at["request"]["id"],
        schedule_payload(at["route"]["id"], at["route_version"],
                         "2026-03-15T10:00:00Z", "2026-03-15T10:30:00Z"),
        DISPATCHER,
    )
    validate_success(ok, 201)
