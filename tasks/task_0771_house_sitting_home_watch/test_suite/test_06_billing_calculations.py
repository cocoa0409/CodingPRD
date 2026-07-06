"""Per-visit charge (provisional vs final, multiplicative tiers) and the pinned-order
invoice roll-up (subtotal -> discount -> service fee -> tax -> total)."""
from test_helpers import validate_success, make_coordinator_headers
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/billing_provisional_vs_final_per_visit_charge
# ---------------------------------------------------------------------------

def _done_visit_45min(api):
    """MEDIUM+pets property, weekday visit checked out after 45 real minutes."""
    return fx.setup_done_visit(
        api,
        property_overrides={"size_tier": "MEDIUM", "has_pets": True,
                            "checklist_config": ["MAIL", "PLANTS"], "key_copies_total": 2},
        booking_overrides={"booking_type": "VACATION",
                           "start_date": "2026-06-01T00:00:00Z",
                           "end_date": "2026-06-01T00:00:00Z"},
        checkin_clock="2026-06-01T09:00:00Z", checkout_clock="2026-06-01T09:45:00Z",
        completed_tasks=["MAIL", "PLANTS"])


def test_provisional_charge_uses_unit_duration_factor(api):
    """PRD 3.6: "These two surcharges are added to the booking's base_visit_rate_cents to form the
    base sum. The base sum is then multiplied by the weekend multiplier — 1.25 when the visit's
    is_weekend is true, and 1.0 otherwise. That product is then multiplied by a duration factor,
    which for the provisional charge is fixed at 1.0 (a standard-length visit is assumed and the
    actual elapsed time is ignored)."

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_per_visit_charge
    """
    ctx = _done_visit_45min(api)
    assert ctx["visit"]["provisional_charge_cents"] == 6500, ctx["visit"]


def test_final_charge_uses_actual_duration_factor(api):
    """PRD 3.9: "each DONE visit's charge is recomputed into final_charge_cents using the final
    variant of the per-visit charge: identical to the provisional computation except that the
    duration factor is no longer fixed at 1.0. Instead the duration factor is the actual elapsed
    minutes between check_in_at and check_out_at divided by the standard thirty minutes, clamped to a
    minimum of 0.5 and a maximum of 2.0."

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_per_visit_charge
    """
    ctx = _done_visit_45min(api)
    fx.get_success_data(api.complete_booking(ctx["booking"]["id"], COORD))
    visit = fx.get_visit(api, ctx["visit"]["id"])
    assert visit["final_charge_cents"] == 9750, visit
    assert visit["final_charge_cents"] != visit["provisional_charge_cents"], visit


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/per_visit_charge_multiplicative_tiers_mode_a
# ---------------------------------------------------------------------------

def _saturday_large_pet_visit(api):
    return fx.setup_done_visit(
        api,
        property_overrides={"size_tier": "LARGE", "has_pets": True,
                            "checklist_config": ["MAIL"]},
        booking_overrides={"booking_type": "VACATION",
                           "start_date": "2026-06-06T00:00:00Z",
                           "end_date": "2026-06-06T00:00:00Z"},
        checkin_clock="2026-06-06T09:00:00Z", checkout_clock="2026-06-06T09:30:00Z",
        completed_tasks=["MAIL"])


def test_weekend_visit_flag_is_set_on_saturday(api):
    """PRD 3.4: "Its is_weekend flag is true when scheduled_start falls on a Saturday or Sunday in UTC."

    Design: Difficulty/combinatorial_formula/per_visit_charge_multiplicative_tiers_mode_a
    """
    ctx = _saturday_large_pet_visit(api)
    assert ctx["visit"]["is_weekend"] is True, ctx["visit"]


def test_charge_combines_size_pet_and_weekend_multiplier(api):
    """PRD 3.6: "The size surcharge is 0 cents for a SMALL property, 1500 cents for a MEDIUM property,
    and 3500 cents for a LARGE property. The pet surcharge is 1000 cents when the property has pets
    and 0 otherwise. These two surcharges are added to the booking's base_visit_rate_cents to form
    the base sum. The base sum is then multiplied by the weekend multiplier — 1.25 when the visit's
    is_weekend is true, and 1.0 otherwise."

    Design: Difficulty/combinatorial_formula/per_visit_charge_multiplicative_tiers_mode_a
    """
    ctx = _saturday_large_pet_visit(api)
    assert ctx["visit"]["provisional_charge_cents"] == 10625, ctx["visit"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/invoice_discount_fee_total_pinned_order_mode_c
# ---------------------------------------------------------------------------

def _completed_two_visit_invoice(api):
    """RECURRING DAILY 2-visit booking: v1 runs 45 min, v2 runs 30 min; then complete."""
    ctx = fx.setup_active_booking(
        api,
        property_overrides={"size_tier": "MEDIUM", "has_pets": True,
                            "checklist_config": ["MAIL"], "key_copies_total": 1},
        booking_overrides={"booking_type": "RECURRING", "frequency": "DAILY",
                           "start_date": "2026-06-01T00:00:00Z",
                           "end_date": "2026-06-02T00:00:00Z"})
    v1, v2 = ctx["visits"][0], ctx["visits"][1]
    sitter_id = ctx["sitter"]["id"]
    fx.perform_checkin(api, v1["id"], sitter_id, clock="2026-06-01T09:00:00Z")
    fx.add_photo_log(api, v1["id"], sitter_id, captured_at="2026-06-01T09:06:00Z")
    fx.perform_checkout(api, v1["id"], sitter_id, completed_tasks=["MAIL"],
                        clock="2026-06-01T09:45:00Z")
    fx.perform_checkin(api, v2["id"], sitter_id, clock="2026-06-02T09:00:00Z")
    fx.add_photo_log(api, v2["id"], sitter_id, captured_at="2026-06-02T09:06:00Z")
    fx.perform_checkout(api, v2["id"], sitter_id, completed_tasks=["MAIL"],
                        clock="2026-06-02T09:30:00Z")
    fx.get_success_data(api.complete_booking(ctx["booking"]["id"], COORD))
    return fx.invoice_for_booking(api, ctx["booking"]["id"])


def test_invoice_subtotal_and_zero_discount_tier(api):
    """PRD 3.9: "A loyalty discount rate is then keyed on the subtotal: the rate is 0.10 when the
    subtotal is at least 50000 cents, otherwise 0.05 when the subtotal is at least 20000 cents, and
    otherwise 0.00. The discount_cents is the subtotal multiplied by that rate, rounded half up."

    Design: Difficulty/combinatorial_formula/invoice_discount_fee_total_pinned_order_mode_c
    """
    inv = _completed_two_visit_invoice(api)
    assert inv["subtotal_cents"] == 16250, inv
    assert inv["discount_cents"] == 0, inv


def test_invoice_service_fee_tax_and_total_pinned_order(api):
    """PRD 3.9: "The service_fee_cents is the discounted base multiplied by the service fee rate of
    0.08, rounded half up. The tax_cents is the sum of the discounted base and the service fee,
    multiplied by the tax rate of 0.07, rounded half up. The total_cents is the discounted base plus
    the service fee plus the tax."

    Design: Difficulty/combinatorial_formula/invoice_discount_fee_total_pinned_order_mode_c
    """
    inv = _completed_two_visit_invoice(api)
    assert inv["service_fee_cents"] == 1300, inv
    assert inv["tax_cents"] == 1229, inv
    assert inv["total_cents"] == 18779, inv
