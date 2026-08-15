"""Grower settlement math and the auto-allocation waterfall.

Covers PRD §3.8 (commission tiers, protein bonus, pinned evaluation order)
and §3.7 (waterfall allocation and its empty-pool rejections).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_tonnage,
    certify_lot,
    create_bale_lot,
    create_buyer,
    create_delivery_load,
    create_draft_quote,
    create_storage_site,
    drive_load_to_delivered,
    get_allocation,
    get_contract,
    issue_quote,
    setup_accepted_contract,
    setup_certified_lot,
    setup_cut_cutting,
    setup_pricing_bed,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_settlement_net_identity
from test_helpers.fixtures import accept_quote, allocate, find_contract_by_quote

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# combinatorial_formula / grower_settlement_evaluation_order
# ===========================================================================

class TestGrowerSettlementEvaluationOrder:
    def _setup_tier_crossing_settle(self):
        """Grower YTD driven to 490.0 by a fully settled 490t contract, then a
        second delivered load carrying two 10.0t allocations (created in
        order) against a 20t contract. Settles the second load and returns
        (grower, a1, a2)."""
        setup_pricing_bed(region_code="WA-YAKIMA", dest_region="NV-NORTH",
                          index_price=10000, lane_overrides={"distance_miles": 80})
        buyer = create_buyer(region_code="NV-NORTH", credit_limit_cents=20000000)
        ctx = setup_cut_cutting(
            grower_overrides={"region_code": "WA-YAKIMA"},
            region_code="WA-YAKIMA",
        )
        grower = ctx["grower"]

        # Contract C0: GOOD 490t; lot1 500.0t GOOD (rfv 160, protein 19).
        q0 = create_draft_quote(
            buyer["id"], tons=490.0, origin_region_code="WA-YAKIMA",
            dest_region_code="NV-NORTH",
        )
        q0 = issue_quote(q0["id"], buyer["id"])
        accept_quote(q0["id"], buyer["id"], q0["version"])
        c0 = find_contract_by_quote(q0["id"])
        site = create_storage_site(region_code="WA-YAKIMA", capacity_tons=2000.0)
        lot1 = create_bale_lot(ctx["cutting"]["id"], site["id"],
                               bale_count=500, harvested_tonnage=500.0)
        certify_lot(lot1["id"], 160.0, 19.0, 14.0)
        load1 = create_delivery_load(capacity_tons=600.0)
        allocate(load1["id"], c0["id"], lot1["id"], 490.0)
        drive_load_to_delivered(load1["id"])
        validate_success(api_client.settle_load(load1["id"], OPS))

        # Contract C1: GOOD 20t; lot2 30.0t GOOD off the same (HARVESTED)
        # cutting; load carries A1 (lot1) then A2 (lot2), delivered.
        lot2 = create_bale_lot(ctx["cutting"]["id"], site["id"],
                               bale_count=30, harvested_tonnage=30.0)
        certify_lot(lot2["id"], 155.0, 18.0, 15.0)
        q1 = create_draft_quote(
            buyer["id"], tons=20.0, origin_region_code="WA-YAKIMA",
            dest_region_code="NV-NORTH", requested_delivery_by="2026-08-25",
        )
        q1 = issue_quote(q1["id"], buyer["id"])
        accept_quote(q1["id"], buyer["id"], q1["version"])
        c1 = find_contract_by_quote(q1["id"])
        load2 = create_delivery_load(capacity_tons=100.0)
        a1 = allocate(load2["id"], c1["id"], lot1["id"], 10.0)
        a2 = allocate(load2["id"], c1["id"], lot2["id"], 10.0)
        drive_load_to_delivered(load2["id"])
        validate_success(api_client.settle_load(load2["id"], OPS))
        return grower, a1, a2

    def test_first_allocation_settles_at_eight_percent(self, api):
        """PRD §3.8: "The commission rate is then read off the grower's
        `settled_tons_ytd` *before* the allocation's tons are added: while
        the year-to-date figure is below 500 tons the rate is 8 percent".
        PRD §3.8: "The commission is then computed on the gross — never on
        the net — at the rate just determined, itself rounded half-up to
        whole cents."

        A1 (10.0t at the contract's 10000-cent unit price, no protein bonus)
        settles with the YTD at 490.0: gross 100000, commission 8000, net
        92000.

        Design: Difficulty/combinatorial_formula/grower_settlement_evaluation_order
        """
        _grower, a1, _a2 = self._setup_tier_crossing_settle()
        a1 = get_allocation(a1["id"])
        assert a1["settled_gross_cents"] == 100000
        assert a1["settled_commission_cents"] == 8000
        assert a1["settled_net_cents"] == 92000
        assert_settlement_net_identity(a1)

    def test_second_allocation_settles_at_six_percent_after_crossing(self, api):
        """PRD §3.8: "once it has reached at least 500 but remains below 1500
        tons the rate is 6 percent — a year-to-date of exactly 500 tons pays
        6 percent". PRD §3.8: "only then adds the allocation's tons to the
        grower's `settled_tons_ytd`, so the next allocation in the sequence
        is tiered against the updated cumulative figure."

        A2 (identical 10.0t, created after A1) is read against YTD exactly
        500.0: commission 6000, net 94000; the grower ends at 510.0.

        Design: Difficulty/combinatorial_formula/grower_settlement_evaluation_order
        """
        grower, _a1, a2 = self._setup_tier_crossing_settle()
        a2 = get_allocation(a2["id"])
        assert a2["settled_commission_cents"] == 6000
        assert a2["settled_net_cents"] == 94000
        assert_settlement_net_identity(a2)
        assert_tonnage(
            get_buyer_ytd(grower["id"]), 510.0, "settled_tons_ytd",
        )


def get_buyer_ytd(grower_id):
    """Read a grower's settled_tons_ytd (PlatformAdmin)."""
    return validate_success(api_client.get_grower(grower_id, ADMIN))[
        "settled_tons_ytd"
    ]


# ===========================================================================
# Corner/calculations / protein_bonus_boundary_at_settlement
# ===========================================================================

def test_protein_bonus_boundary_at_settlement(api):
    """PRD §3.8: "The gross proceeds for an allocation are the allocation's
    tons multiplied by the contract's `unit_price_cents`, with a 2 percent
    protein bonus added when the lot's `certified_protein_pct` is at least
    20.0, and the result rounded half-up to whole cents."

    Two identical 10.0t GOOD allocations on one delivered load: the lot
    certified at protein 20.0 earns the bonus (gross 102000, commission
    8160), the lot at 19.9 does not (gross 100000, commission 8000).

    Design: Corner/calculations/protein_bonus_boundary_at_settlement
    """
    setup_pricing_bed(region_code="WA-YAKIMA", dest_region="NV-NORTH",
                      index_price=10000, lane_overrides={"distance_miles": 80})
    buyer = create_buyer(region_code="NV-NORTH", credit_limit_cents=1000000)
    c_pa = _accept_simple_contract(buyer, delivery_by="2026-08-20")
    c_pb = _accept_simple_contract(buyer, delivery_by="2026-08-22")
    ctx = setup_cut_cutting(
        grower_overrides={"region_code": "WA-YAKIMA"}, region_code="WA-YAKIMA",
    )
    site = create_storage_site(region_code="WA-YAKIMA")
    lot_a = create_bale_lot(ctx["cutting"]["id"], site["id"],
                            bale_count=20, harvested_tonnage=10.0)
    lot_b = create_bale_lot(ctx["cutting"]["id"], site["id"],
                            bale_count=20, harvested_tonnage=10.0)
    certify_lot(lot_a["id"], 155.0, 20.0, 14.0)
    certify_lot(lot_b["id"], 155.0, 19.9, 14.0)
    load = create_delivery_load(capacity_tons=30.0)
    a_a = allocate(load["id"], c_pa["id"], lot_a["id"], 10.0)
    a_b = allocate(load["id"], c_pb["id"], lot_b["id"], 10.0)
    drive_load_to_delivered(load["id"])
    validate_success(api_client.settle_load(load["id"], OPS))
    a_a = get_allocation(a_a["id"])
    a_b = get_allocation(a_b["id"])
    assert a_a["settled_gross_cents"] == 102000
    assert a_a["settled_commission_cents"] == 8160
    assert a_b["settled_gross_cents"] == 100000
    assert a_b["settled_commission_cents"] == 8000


def _accept_simple_contract(buyer, delivery_by):
    """Accept a GOOD 10.0t WA-YAKIMA -> NV-NORTH quote. Returns Contract."""
    quote = create_draft_quote(
        buyer["id"], tons=10.0, origin_region_code="WA-YAKIMA",
        dest_region_code="NV-NORTH", requested_delivery_by=delivery_by,
    )
    quote = issue_quote(quote["id"], buyer["id"])
    accept_quote(quote["id"], buyer["id"], quote["version"])
    return find_contract_by_quote(quote["id"])


# ===========================================================================
# Corner/calculations / auto_allocate_waterfall_partial_fill
# ===========================================================================

def test_auto_allocate_waterfall_partial_fill(api):
    """PRD §3.7: "Eligible contracts are those `ACTIVE` with `remaining_tons`
    greater than zero, ranked by earliest `delivery_deadline` first, ties
    broken by earliest `created_at`". PRD §3.7: "Eligible lots for a given
    contract are those `ACTIVE`, carrying a `quality_tier` equal to the
    contract's tier, and having `allocatable_tonnage` greater than zero,
    ranked by earliest `harvested_date` first". PRD §3.7: "Partial fills are
    the norm".

    A 25.0t load across C_A (10t, earliest deadline, created first), C_B
    (20t, same deadline, created second) and C_C (10t, later deadline), fed
    by PREMIUM lots L1 (12.0t, harvested earlier) and L2 (30.0t): the
    waterfall emits allocations of 10.0 (C_A x L1), 2.0 (C_B x L1 remainder)
    and 13.0 (C_B x L2), fills the truck exactly, and leaves C_C untouched.

    Design: Corner/calculations/auto_allocate_waterfall_partial_fill
    """
    setup_pricing_bed()
    buyer = create_buyer(credit_limit_cents=5000000)
    c_a = _accept_premium_contract(buyer, 10.0, "2026-08-20")
    c_b = _accept_premium_contract(buyer, 20.0, "2026-08-20")
    c_c = _accept_premium_contract(buyer, 10.0, "2026-08-25")

    ctx = setup_cut_cutting(
        cutting_overrides={
            "planned_window_start": "2026-07-10",
            "planned_window_end": "2026-07-31",
        },
        dry_dates=["2026-07-12", "2026-07-13", "2026-07-14"],
        cut_date="2026-07-14",
    )
    site = create_storage_site()
    l1 = create_bale_lot(ctx["cutting"]["id"], site["id"], bale_count=24,
                         harvested_tonnage=12.0, harvested_date="2026-07-15")
    l2 = create_bale_lot(ctx["cutting"]["id"], site["id"], bale_count=60,
                         harvested_tonnage=30.0, harvested_date="2026-07-20")
    certify_lot(l1["id"], 175.0, 18.0, 14.0, sample_date="2026-07-16")
    certify_lot(l2["id"], 178.0, 19.0, 13.5, sample_date="2026-07-21")

    load = create_delivery_load(carrier_name="CARRIER-Q")
    validate_success(api_client.auto_allocate(load["id"], OPS))
    allocations, meta = validate_paginated(
        api_client.list_load_allocations(OPS, params={"delivery_load_id": load["id"]})
    )
    assert meta["total_count"] == 3
    a0, a1, a2 = allocations
    assert a0["contract_id"] == c_a["id"]
    assert a0["bale_lot_id"] == l1["id"]
    assert_tonnage(a0["tons"], 10.0, "allocation[0] tons")
    assert a1["contract_id"] == c_b["id"]
    assert a1["bale_lot_id"] == l1["id"]
    assert_tonnage(a1["tons"], 2.0, "allocation[1] tons")
    assert a2["contract_id"] == c_b["id"]
    assert a2["bale_lot_id"] == l2["id"]
    assert_tonnage(a2["tons"], 13.0, "allocation[2] tons")
    assert_tonnage(
        api_client.get_delivery_load(load["id"], OPS).json()["data"]["loaded_tons"],
        25.0, "loaded_tons",
    )
    assert_tonnage(
        get_contract(c_c["id"])["remaining_tons"], 10.0, "C_C remaining_tons",
    )


def _accept_premium_contract(buyer, tons, delivery_by):
    """Accept a PREMIUM quote on the standard lane. Returns Contract."""
    quote = create_draft_quote(buyer["id"], quality_tier="PREMIUM", tons=tons,
                               requested_delivery_by=delivery_by)
    quote = issue_quote(quote["id"], buyer["id"])
    accept_quote(quote["id"], buyer["id"], quote["version"])
    return find_contract_by_quote(quote["id"])


# ===========================================================================
# Corner/endpoints / auto_allocate_no_eligible_contract
# ===========================================================================

def test_auto_allocate_no_eligible_contract(api):
    """PRD §3.7: "when no eligible contract exists the attempt is rejected
    with `ERR_NO_ELIGIBLE_CONTRACT`."

    Design: Corner/endpoints/auto_allocate_no_eligible_contract
    """
    load = create_delivery_load(carrier_name="CARRIER-K")
    resp = api_client.auto_allocate(load["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACT)


# ===========================================================================
# Corner/endpoints / auto_allocate_no_eligible_lot
# ===========================================================================

def test_auto_allocate_no_eligible_lot(api):
    """PRD §3.7: "If the waterfall runs to completion having created no
    allocation at all because no active graded lot matched any eligible
    contract's tier, the attempt is rejected with `ERR_NO_ELIGIBLE_LOT`."

    A PREMIUM contract is eligible, but the only ACTIVE lot is GOOD, so zero
    allocations are created.

    Design: Corner/endpoints/auto_allocate_no_eligible_lot
    """
    setup_accepted_contract(tons=10.0, quality_tier="PREMIUM")
    setup_certified_lot(rfv=155.0, protein_pct=18.0, moisture_pct=14.0,
                        lot_tonnage=10.0)
    load = create_delivery_load(carrier_name="CARRIER-J")
    resp = api_client.auto_allocate(load["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_LOT)
