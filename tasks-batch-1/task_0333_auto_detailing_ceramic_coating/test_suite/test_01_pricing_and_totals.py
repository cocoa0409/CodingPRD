"""Pricing: provisional vs final totals, the tier/size/discount/add-on
combinatorial formula, the membership-credit evaluation order, and add-on
recomputation / snapshotting.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_customer_headers,
    set_clock, seed_package, seed_vehicle_size_rate, seed_addon, seed_catalog,
    create_customer, create_service_bay, create_mobile_unit,
    create_active_membership, book_shop_appointment, book_mobile_appointment,
    add_addon_line,
    advance_to_in_service, attach_photo,
)
from test_helpers.api_client import api_client as _client
from test_helpers.factories import create_appointment_payload, create_addon_line_payload
from test_helpers.test_users import TEST_USERS

DETAILER = TEST_USERS["detailer_headers"]


# ──────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc /
#   appointment_provisional_vs_final_total_diverges_on_lapse_and_skip
# ──────────────────────────────────────────────────────────────────────

def _seed_full_suv_member_with_two_addons():
    """Build the FULL/SUV member appointment with ENGINE_BAY + PET_HAIR
    requested, returning (customer, appointment)."""
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="WASH")  # activation values the wash credit from the WASH row (PRD §3.5)
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SUV")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    seed_addon(addon_code="ENGINE_BAY")
    seed_addon(addon_code="PET_HAIR")
    cust = create_customer(email="derek@x.com", full_name="Derek M")
    create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    bay = create_service_bay(bay_code="B1", supports_ceramic=False)
    appt = book_shop_appointment(
        cust["id"], bay, tier="FULL", vehicle_size="SUV",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    add_addon_line(appt["id"], cust["id"], "ENGINE_BAY")
    add_addon_line(appt["id"], cust["id"], "PET_HAIR")
    return cust, appt


def test_provisional_total_member_full_suv_two_addons():
    """PRD §3.2: "First the raw package price is the tier's `base_price_cents` multiplied by the chosen size's `size_multiplier_bps`, divided by ten thousand, rounded half up to whole cents."
    PRD §3.2: "The `provisional_total_cents` reported at booking is the net package price plus the add-on total — it is reported **before** any credit is subtracted, because the credit is tracked separately in `credit_applied_cents` and flows into the outstanding balance rather than into the reported total."

    Design: Difficulty/dual_variant_calc/appointment_provisional_vs_final_total_diverges_on_lapse_and_skip
    """
    cust, appt = _seed_full_suv_member_with_two_addons()
    fetched = validate_success(api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200)
    assert fetched["provisional_total_cents"] == 21260, (
        f"expected 21260, got {fetched['provisional_total_cents']}"
    )


def test_final_total_diverges_after_lapse_and_skip():
    """PRD §3.7: "The final pricing variant differs from the provisional one in two ways: it uses the customer's **current** membership state — the customer counts as a member only if their `membership_id` is set and that membership's `status` is `ACTIVE` right now — rather than the booking-time `is_member_at_booking` snapshot, and it sums only the add-on lines whose `line_status` is `PERFORMED` rather than all requested lines."
    PRD §3.7: "If the membership has lapsed since booking, or an add-on was skipped, the final total comes out below the provisional total."

    Design: Difficulty/dual_variant_calc/appointment_provisional_vs_final_total_diverges_on_lapse_and_skip
    """
    cust, appt = _seed_full_suv_member_with_two_addons()
    appt_id, cust_id = appt["id"], cust["id"]

    # Drive to IN_SERVICE, then SKIP PET_HAIR and PERFORM ENGINE_BAY.
    advance_to_in_service(appt_id)
    get_success_data(_client.set_addon_line_status(appt_id, "PET_HAIR", {"line_status": "SKIPPED"}, DETAILER))
    get_success_data(_client.set_addon_line_status(appt_id, "ENGINE_BAY", {"line_status": "PERFORMED"}, DETAILER))

    # Lapse the membership before completion (ACTIVE -> PAST_DUE -> LAPSED).
    # mark-past-due and lapse are each gated on the clock being at or past
    # cycle_start_utc + 30 days (PRD §3.5); the membership was activated at the
    # 2026-06-15T08:00 setup clock, so advance past the cycle before lapsing.
    set_clock("2026-07-16T08:00:00Z")
    mem = get_success_data(api_client.list_customer_memberships(cust_id, make_customer_headers(cust_id)))[0]
    get_success_data(api_client.mark_membership_past_due(mem["id"], TEST_USERS["scheduler_headers"]))
    get_success_data(api_client.lapse_membership(mem["id"], TEST_USERS["scheduler_headers"]))

    attach_photo(appt_id, "AFTER")
    finished = validate_success(api_client.finish_service(appt_id, DETAILER), 200)

    assert finished["work_status"] == "READY"
    assert finished["provisional_total_cents"] == 21260
    assert finished["final_total_cents"] == 19100, (
        f"expected final 19100, got {finished['final_total_cents']}"
    )


# ──────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc /
#   customer_loyalty_chronological_vs_forward_tier_diverges
# ──────────────────────────────────────────────────────────────────────

def _seed_loyalty_divergence_customer():
    """One FULL/TRUCK paid+released appointment (18000 realized) plus a
    CERAMIC/SEDAN still-BOOKED appointment (provisional 50000). Returns the
    customer dict."""
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="TRUCK")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="tess@x.com", full_name="Tess L")
    cust_headers = make_customer_headers(cust["id"])
    unit = create_mobile_unit(unit_code="M1", travel_buffer_minutes=30)

    paid = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="TRUCK",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    from test_helpers.fixtures import advance_to_ready_non_ceramic, pay_full, release_appointment
    advance_to_ready_non_ceramic(paid["id"])
    pay_full(paid["id"], cust["id"], 18000)
    release_appointment(paid["id"])

    book_mobile_appointment(
        cust["id"], unit["id"], tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-20T09:00:00Z",
    )
    return cust


def test_chronological_spend_counts_only_paid():
    """PRD §3.6: "The `chronological_lifetime_spend_cents` is the sum of `final_total_cents` over the customer's appointments whose `payment_status` is `PAID` — that is, realized spend only."

    Design: Difficulty/dual_variant_calc/customer_loyalty_chronological_vs_forward_tier_diverges
    """
    cust = _seed_loyalty_divergence_customer()
    fetched = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["chronological_lifetime_spend_cents"] == 18000
    assert fetched["loyalty_tier"] == "BRONZE"


def test_projected_spend_adds_in_flight_provisional():
    """PRD §3.6: "The `projected_lifetime_spend_cents` is a forward-looking, what-if figure: it is the chronological realized spend plus the `provisional_total_cents` of the customer's appointments that are still in flight — those whose `work_status` is one of `BOOKED`, `CHECKED_IN`, `IN_PREP`, `IN_SERVICE`, `CURING`, or `READY` and whose `payment_status` is not `PAID` (the not-`PAID` condition avoids double-counting an appointment already realized in the chronological sum)."

    Design: Difficulty/dual_variant_calc/customer_loyalty_chronological_vs_forward_tier_diverges
    """
    cust = _seed_loyalty_divergence_customer()
    fetched = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["projected_lifetime_spend_cents"] == 68000, (
        f"expected 68000, got {fetched['projected_lifetime_spend_cents']}"
    )
    # The loyalty band is driven by realized spend only, so it stays BRONZE.
    assert fetched["loyalty_tier"] == "BRONZE"


# ──────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula /
#   appointment_total_nonlinear_tier_size_discount_addon_interaction
# ──────────────────────────────────────────────────────────────────────

def test_combinatorial_member_discount_plus_flat_addon():
    """PRD §3.2: "Then, if the customer counts as a member for this booking, a member discount is computed as that raw package price multiplied by the member discount rate of one thousand five hundred basis points, divided by ten thousand, rounded half up; if the customer is not a member the discount is zero."
    PRD §3.1: "Each add-on carries a `price_cents` (a positive flat price that is never scaled by vehicle size and never reduced by a membership discount)"

    Design: Difficulty/combinatorial_formula/appointment_total_nonlinear_tier_size_discount_addon_interaction
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SUV")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    seed_addon(addon_code="ENGINE_BAY")
    cust = create_customer(email="mae@x.com", full_name="Mae R")
    create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    bay = create_service_bay(bay_code="B2", supports_ceramic=False)
    appt = book_shop_appointment(
        cust["id"], bay, tier="FULL", vehicle_size="SUV",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    line = validate_success(
        api_client.add_appointment_addon(
            appt["id"], create_addon_line_payload(addon_code="ENGINE_BAY"),
            make_customer_headers(cust["id"]),
        ),
        201,
    )
    # pkg_raw 15600 - discount 2340 = 13260 net; + 3500 flat add-on = 16760.
    appt_after = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    assert appt_after["provisional_total_cents"] == 16760, (
        f"expected 16760, got {appt_after['provisional_total_cents']}"
    )


def test_combinatorial_full_suv_member_base_price_before_addon():
    """PRD §3.2: "The discounted package price (the net package) is the raw package price minus that discount."
    PRD §3.2: "First the raw package price is the tier's `base_price_cents` multiplied by the chosen size's `size_multiplier_bps`, divided by ten thousand, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/appointment_total_nonlinear_tier_size_discount_addon_interaction
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SUV")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="mae2@x.com", full_name="Mae R2")
    create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    bay = create_service_bay(bay_code="B2b", supports_ceramic=False)
    appt = book_shop_appointment(
        cust["id"], bay, tier="FULL", vehicle_size="SUV",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    # Net member package only, no add-ons: 15600 - 2340 = 13260.
    assert appt["provisional_total_cents"] == 13260, (
        f"expected 13260, got {appt['provisional_total_cents']}"
    )


# ──────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula /
#   membership_credit_circular_dependency_evaluation_order_pinned
# ──────────────────────────────────────────────────────────────────────

def _seed_credit_pinned_appointment():
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="ivy@x.com", full_name="Ivy K")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    bay = create_service_bay(bay_code="B3", supports_ceramic=False)
    appt = book_shop_appointment(
        cust["id"], bay, tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T10:00:00Z", use_membership_credit=True,
    )
    return cust, mem, appt


def test_wash_credit_value_frozen_at_activation():
    """PRD §3.5: "freezes `wash_credit_value_cents` to the member-discounted `WASH` price valued at the subscriber's `default_vehicle_size` (so a granted credit is worth that many cents against a package subtotal)"

    Design: Difficulty/combinatorial_formula/membership_credit_circular_dependency_evaluation_order_pinned
    """
    cust, mem, appt = _seed_credit_pinned_appointment()
    fetched = validate_success(
        api_client.get_membership(mem["id"], make_customer_headers(cust["id"])), 200
    )
    # WASH 4000 SEDAN -> raw 4000, member discount 600, net 3400.
    assert fetched["wash_credit_value_cents"] == 3400, (
        f"expected 3400, got {fetched['wash_credit_value_cents']}"
    )


def test_provisional_before_credit_outstanding_after_credit():
    """PRD §3.2: "The `provisional_total_cents` reported at booking is the net package price plus the add-on total — it is reported **before** any credit is subtracted, because the credit is tracked separately in `credit_applied_cents` and flows into the outstanding balance rather than into the reported total."
    PRD §3.2: "When a credit is legitimately applied, `credit_applied_cents` is the smaller of the membership's frozen `wash_credit_value_cents` and the net package price — the credit offsets the package only, never the add-ons — and one credit is consumed"
    PRD §3.7: "The conserved payment quantity is the `outstanding_balance_cents`, defined as `final_total_cents` minus `credit_applied_cents` minus `amount_charged_cents` plus `amount_refunded_cents`."

    Design: Difficulty/combinatorial_formula/membership_credit_circular_dependency_evaluation_order_pinned
    """
    cust, mem, appt = _seed_credit_pinned_appointment()
    fetched = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    # FULL/SEDAN member: raw 12000, discount 1800, net 10200.
    assert fetched["provisional_total_cents"] == 10200
    assert fetched["credit_applied_cents"] == 3400
    assert fetched["outstanding_balance_cents"] == 6800, (
        f"expected outstanding 6800, got {fetched['outstanding_balance_cents']}"
    )


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / addon_recomputes_provisional_total_and_occupancy
# ──────────────────────────────────────────────────────────────────────

def test_addon_recomputes_provisional_total_and_occupancy():
    """PRD §3.4: "Adding a line recomputes the appointment's occupancy window and provisional total and increments the appointment's `version`."
    PRD §3.2: "The busy minutes are the tier's `prep_minutes` plus its `service_minutes` plus those added minutes."

    Design: Corner/calculations/addon_recomputes_provisional_total_and_occupancy
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SUV")
    seed_addon(addon_code="HEADLIGHT")
    cust = create_customer(email="ar1@x.com", full_name="Ar One")
    unit = create_mobile_unit(unit_code="AR1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SUV",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    # Non-member FULL/SUV = 15600. + HEADLIGHT 6000 = 21600.
    assert appt["provisional_total_cents"] == 15600
    add_addon_line(appt["id"], cust["id"], "HEADLIGHT")
    after = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    assert after["provisional_total_cents"] == 21600
    # MOBILE occupancy_end = start + prep20 + service120 + addon25 = +165 min.
    assert after["occupancy_end_utc"] == "2026-06-15T11:45:00.000Z"


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / addon_price_snapshot_frozen_against_catalog_edit
# ──────────────────────────────────────────────────────────────────────

def test_addon_price_snapshot_frozen_at_line_creation():
    """PRD §3.4: "freezes `price_cents_snapshot` from the catalog `price_cents` and `extra_minutes_snapshot` from the catalog `extra_minutes` at the moment of line creation (so later catalog edits do not move it)"
    PRD §3.2: "The add-on portion is the sum of the per-line snapshot prices of all add-on lines requested for the appointment"

    Design: Corner/calculations/addon_price_snapshot_frozen_against_catalog_edit
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    seed_addon(addon_code="ENGINE_BAY")
    cust = create_customer(email="sn1@x.com", full_name="Sn One")
    unit = create_mobile_unit(unit_code="SN1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    line = validate_success(
        api_client.add_appointment_addon(
            appt["id"], create_addon_line_payload(addon_code="ENGINE_BAY"),
            make_customer_headers(cust["id"]),
        ),
        201,
    )
    assert line["price_cents_snapshot"] == 3500
    after = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    # Non-member FULL/SEDAN 12000 + 3500 = 15500.
    assert after["provisional_total_cents"] == 15500


# ──────────────────────────────────────────────────────────────────────
# Corner / consistency_model /
#   immediate_consistency_provisional_total_visible_in_create_response
#   (NOTE: excluded_because stub -> the combinatorial difficulty instance owns
#   the assertion; not translated.)
# ──────────────────────────────────────────────────────────────────────
