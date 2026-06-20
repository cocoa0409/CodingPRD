"""Final-bill (reservation_total) computation latched at check-out.

Translates difficulty (A) combinatorial_formula/reservation_total_pinned_order_mode_c
and corner (B) calculations/reservation_total_loyalty_tier2_at_30000.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_reservation_payload, create_addon_payload,
    setup_facility_owner_pet,
    create_run, advance_clock, create_assignment,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def _checkout_total(facility, pet, service_type, start_date, end_date,
                    run_size="LARGE", addons=None):
    """Walk a reservation create -> assignment -> confirm -> check_in -> check_out.

    Returns the checked-out reservation dict (total_cents latched). NONE policy.
    """
    run_kind = "OVERNIGHT_SUITE" if service_type == "OVERNIGHT" else "DAYCARE_PEN"
    run_kwargs = {"label": "Run-B", "kind": run_kind, "size_class": run_size}
    if run_kind == "DAYCARE_PEN":
        run_kwargs["daycare_capacity"] = 5
    run = create_run(facility["id"], **run_kwargs)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], service_type, start_date, end_date),
        MGR,
    ))
    for ad in (addons or []):
        get_success_data(api_client.create_addon(res["id"], create_addon_payload(**ad), MGR))
    create_assignment(res["id"], run["id"], res["version"])
    get_success_data(api_client.confirm_reservation(res["id"], MGR))
    advance_clock(facility["id"], start_date)
    get_success_data(api_client.check_in(res["id"], MGR))
    return get_success_data(api_client.check_out(res["id"], MGR))


def test_total_pinned_order_subtotal_tier_discount(api):
    """PRD §3.8: "A loyalty discount tier is then keyed on that subtotal: a subtotal of
    at least 30000 cents earns a 10 percent rate, a subtotal of at least 15000 cents (but
    below 30000) earns a 5 percent rate, and anything below 15000 cents earns no discount.
    The discount is the subtotal multiplied by that rate, rounded half up to whole cents
    before it is subtracted — and the tier is fixed at the subtotal stage and is never
    recomputed after the discount is applied."
    PRD §3.8: "for an `OVERNIGHT` stay it is a nightly rate keyed on the pet's `size_class`
    — 3500, 4000, 5000, or 6500 cents for `TOY`, `SMALL`, `MEDIUM`, or `LARGE` — multiplied
    by the greater of `nights` and 1".

    OVERNIGHT/MEDIUM/3n lodging 5000*3=15000 + BATH MEDIUM 2500 = subtotal 17500, tier 5%,
    discount 875, total 16625.

    Design: Difficulty/combinatorial_formula/reservation_total_pinned_order_mode_c
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", weight_kg=18)
    assert pet["size_class"] == "MEDIUM"
    out = _checkout_total(
        facility, pet, "OVERNIGHT", "2026-01-05", "2026-01-08",
        addons=[{"kind": "BATH", "scheduled_date": "2026-01-06"}])
    assert out["status"] == "CHECKED_OUT"
    assert out["total_cents"] == 16625, f"subtotal 17500 - discount 875 == 16625, got {out['total_cents']}"


def test_total_no_discount_below_tier1_threshold(api):
    """PRD §3.8: "for a `DAYCARE` stay it is a single day rate keyed on the same size
    ladder of 2500, 3000, 3500, or 4500 cents."
    PRD §3.8: "a subtotal of at least 15000 cents (but below 30000) earns a 5 percent
    rate, and anything below 15000 cents earns no discount. The discount is the subtotal
    multiplied by that rate, rounded half up to whole cents before it is subtracted".

    DAYCARE/MEDIUM lodging 3500, no add-ons -> subtotal 3500 < 15000 -> no discount,
    total 3500.

    Design: Difficulty/combinatorial_formula/reservation_total_pinned_order_mode_c
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", weight_kg=18)
    assert pet["size_class"] == "MEDIUM"
    out = _checkout_total(facility, pet, "DAYCARE", "2026-01-05", "2026-01-05", run_size="LARGE")
    assert out["total_cents"] == 3500, f"subtotal 3500, no discount -> 3500, got {out['total_cents']}"


def test_total_tier2_threshold_at_30000(api):
    """PRD §3.8: "for an `OVERNIGHT` stay it is a nightly rate keyed on the pet's
    `size_class` — 3500, 4000, 5000, or 6500 cents for `TOY`, `SMALL`, `MEDIUM`, or
    `LARGE` — multiplied by the greater of `nights` and 1".
    PRD §3.8: "A loyalty discount tier is then keyed on that subtotal: a subtotal of at
    least 30000 cents earns a 10 percent rate, a subtotal of at least 15000 cents (but
    below 30000) earns a 5 percent rate, and anything below 15000 cents earns no discount.
    The discount is the subtotal multiplied by that rate, rounded half up to whole cents
    before it is subtracted — and the tier is fixed at the subtotal stage and is never
    recomputed after the discount is applied."

    OVERNIGHT/LARGE/5n lodging 6500*5=32500 (no add-ons) -> tier 10%, discount 3250, total 29250.

    Design: Corner/calculations/reservation_total_loyalty_tier2_at_30000
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", weight_kg=35)
    assert pet["size_class"] == "LARGE"
    out = _checkout_total(facility, pet, "OVERNIGHT", "2026-01-05", "2026-01-10")
    assert out["total_cents"] == 29250, f"32500 - 3250 == 29250, got {out['total_cents']}"
