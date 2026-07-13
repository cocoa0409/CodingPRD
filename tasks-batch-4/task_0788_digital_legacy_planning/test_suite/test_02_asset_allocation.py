"""Asset release cascade and beneficiary allocation (NET/GROSS variants, waterfall rounding)."""
from test_helpers import (
    validate_success,
    make_owner_headers, ADMIN_HEADERS,
    setup_release_approved, setup_released_asset, grant_release_request,
    set_clock, create_plan, create_vault_item,
)


# --------------------------------------------------------------------------- #
# beneficiary_allocation_net_variant_on_estate  (Difficulty/dual_variant_calc)
# --------------------------------------------------------------------------- #
def test_net_variant_deducts_liability_for_first_and_last_beneficiary(api):
    """PRD 3.4: "The basis for distribution is chosen by the asset's `distribution_basis`:
    a `NET` asset distributes its `net_value_cents` (gross minus liability, floored at
    zero), while a `GROSS` asset distributes its `gross_value_cents` outright, ignoring the
    liability."

    Design: Difficulty/dual_variant_calc/beneficiary_allocation_net_variant_on_estate
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(50, 30, 20))
    grant_release_request(api, ctx["rr_id"])
    b1, _, b3 = ctx["beneficiary_ids"]
    owner = make_owner_headers(ctx["plan_id"])
    d1 = validate_success(api.get_beneficiary(b1, owner), 200)
    d3 = validate_success(api.get_beneficiary(b3, owner), 200)
    # net 9999; floors 4999/2999/1999; 2-cent remainder to earliest two -> 5000/3000/1999.
    assert d1["allocated_value_cents"] == 5000, f"b1 expected 5000, got {d1['allocated_value_cents']}"
    assert d3["allocated_value_cents"] == 1999, f"b3 expected 1999, got {d3['allocated_value_cents']}"


def test_net_variant_vests_last_beneficiary(api):
    """PRD 3.4: "When a linked asset item transitions from `SEALED` to `RELEASED` (as a
    cascade of a granted release), the allocation runs and each linked `NOMINATED`
    beneficiary moves to `VESTED` with its `allocated_value_cents` set."

    Design: Difficulty/dual_variant_calc/beneficiary_allocation_net_variant_on_estate
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(50, 30, 20))
    grant_release_request(api, ctx["rr_id"])
    b3 = ctx["beneficiary_ids"][2]
    d3 = validate_success(api.get_beneficiary(b3, make_owner_headers(ctx["plan_id"])), 200)
    assert d3["status"] == "VESTED", f"b3 expected VESTED, got {d3['status']}"


# --------------------------------------------------------------------------- #
# beneficiary_allocation_remainder_waterfall_rounding  (Difficulty/combinatorial_formula)
# --------------------------------------------------------------------------- #
def test_waterfall_floors_then_distributes_remainder_by_created_at(api):
    """PRD 3.4: "The rounding order is fixed: floor each beneficiary first, then distribute
    the remainder."
    PRD 3.4: "Distribute that remainder one cent at a time to beneficiaries in ascending
    `created_at` order — the first beneficiary in creation order receives one extra cent,
    then the next, and so on until the remainder is exhausted — so that the earliest-created
    beneficiaries absorb the rounding leftovers."

    Design: Difficulty/combinatorial_formula/beneficiary_allocation_remainder_waterfall_rounding
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(50, 30, 20))
    grant_release_request(api, ctx["rr_id"])
    b1, b2, b3 = ctx["beneficiary_ids"]
    owner = make_owner_headers(ctx["plan_id"])
    v1 = validate_success(api.get_beneficiary(b1, owner), 200)["allocated_value_cents"]
    v2 = validate_success(api.get_beneficiary(b2, owner), 200)["allocated_value_cents"]
    v3 = validate_success(api.get_beneficiary(b3, owner), 200)["allocated_value_cents"]
    assert (v1, v2, v3) == (5000, 3000, 1999), f"expected (5000,3000,1999), got {(v1, v2, v3)}"


def test_waterfall_conserves_distributable_pool(api):
    """PRD 3.4: "Then compute the total distributable pool as the floor of the basis value
    multiplied by the sum of all the beneficiaries' `allocation_pct` divided by 100, and
    subtract the sum of the floored provisional cents to obtain the leftover remainder."

    Design: Difficulty/combinatorial_formula/beneficiary_allocation_remainder_waterfall_rounding
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(50, 30, 20))
    grant_release_request(api, ctx["rr_id"])
    owner = make_owner_headers(ctx["plan_id"])
    total = sum(
        validate_success(api.get_beneficiary(b, owner), 200)["allocated_value_cents"]
        for b in ctx["beneficiary_ids"]
    )
    # allocations sum to 100%, so the whole net 9999 is distributed.
    assert total == 9999, f"expected pool 9999 fully distributed, got {total}"


# --------------------------------------------------------------------------- #
# grant_releases_item_then_vests_beneficiary_depth3  (Difficulty/transitive_cascade)
# --------------------------------------------------------------------------- #
def test_grant_releases_item_and_marks_request_granted(api):
    """PRD 3.6: "On a successful grant, the request moves `APPROVED → GRANTED`, and as a
    two-link cascade every `SEALED` vault item on the plan whose `kind` is in `scope_kinds`
    moves to `RELEASED`, and each released `ASSET` item in turn vests its linked
    beneficiaries by running the allocation described in Section 3.4."

    Design: Difficulty/transitive_cascade/grant_releases_item_then_vests_beneficiary_depth3
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(100,))
    rr = validate_success(api.grant_release_request(ctx["rr_id"], ADMIN_HEADERS), 200)
    assert rr["status"] == "GRANTED", f"request expected GRANTED, got {rr['status']}"
    item = validate_success(api.get_vault_item(ctx["item_id"], make_owner_headers(ctx["plan_id"])), 200)
    assert item["status"] == "RELEASED", f"item expected RELEASED, got {item['status']}"


def test_grant_vests_linked_beneficiary_with_full_net_value(api):
    """PRD 3.6: "and each released `ASSET` item in turn vests its linked beneficiaries by
    running the allocation described in Section 3.4."
    PRD 3.4: "a `NET` asset distributes its `net_value_cents` (gross minus liability,
    floored at zero)"

    Design: Difficulty/transitive_cascade/grant_releases_item_then_vests_beneficiary_depth3
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="NET", allocations=(100,))
    grant_release_request(api, ctx["rr_id"])
    b1 = ctx["beneficiary_ids"][0]
    d1 = validate_success(api.get_beneficiary(b1, make_owner_headers(ctx["plan_id"])), 200)
    assert d1["status"] == "VESTED", f"beneficiary expected VESTED, got {d1['status']}"
    assert d1["allocated_value_cents"] == 9999, f"expected 9999, got {d1['allocated_value_cents']}"


# --------------------------------------------------------------------------- #
# beneficiary_allocation_gross_variant_ignores_liability  (Corner/calculations)
# --------------------------------------------------------------------------- #
def test_gross_variant_ignores_liability(api):
    """PRD 3.4: "a `GROSS` asset distributes its `gross_value_cents` outright, ignoring the
    liability."

    Design: Corner/calculations/beneficiary_allocation_gross_variant_ignores_liability
    """
    ctx = setup_release_approved(api, gross_value_cents=10000, liability_cents=1,
                                 distribution_basis="GROSS", allocations=(100,))
    grant_release_request(api, ctx["rr_id"])
    b1 = ctx["beneficiary_ids"][0]
    d1 = validate_success(api.get_beneficiary(b1, make_owner_headers(ctx["plan_id"])), 200)
    assert d1["allocated_value_cents"] == 10000, f"expected 10000, got {d1['allocated_value_cents']}"


# --------------------------------------------------------------------------- #
# vaultitem_asset_net_value_cents_computed  (Corner/entities)
# --------------------------------------------------------------------------- #
def test_asset_net_value_cents_computed_from_gross_minus_liability(api):
    """PRD 3.2: "The system derives `net_value_cents` as the gross value minus the
    liability, floored at zero so it is never negative; `net_value_cents` is null for any
    item whose kind is not `ASSET`."

    Design: Corner/entities/vaultitem_asset_net_value_cents_computed
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    item = create_vault_item(api, plan_id, kind="ASSET", category="estate", title="Car",
                             secret_ref="vault://car", gross_value_cents=5000,
                             liability_cents=200, distribution_basis="NET")
    data = validate_success(api.get_vault_item(item["id"], make_owner_headers(plan_id)), 200)
    assert data["net_value_cents"] == 4800, f"expected 4800, got {data['net_value_cents']}"
