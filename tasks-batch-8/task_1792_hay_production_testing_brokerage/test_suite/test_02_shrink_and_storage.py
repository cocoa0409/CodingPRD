"""Shrink tonnage variants, storage capacity, spoilage, and lot lifecycle.

Covers PRD §2.9 (dual tonnage accounting), §2.10 (occupancy and capacity),
and §3.2 (lots, spoilage, condemnation, transfer).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_tonnage,
    create_bale_lot,
    create_storage_site,
    get_lot,
    post_spoilage_event,
    set_clock,
    setup_cut_cutting,
    setup_lot,
    setup_scheduled_cutting,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_bale_lot

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# dual_variant_calc / simple_vs_compound_shrink_tonnage
# ===========================================================================

class TestSimpleVsCompoundShrinkTonnage:
    def _setup_aged_lot(self):
        """100.0t lot harvested 2026-06-01 in a standard site; clock 2026-09-15
        (three full months of shrink)."""
        ctx = setup_cut_cutting(
            cutting_overrides={
                "planned_window_start": "2026-05-25",
                "planned_window_end": "2026-06-05",
            },
            dry_dates=["2026-05-30", "2026-05-31", "2026-06-01"],
            cut_date="2026-06-01",
        )
        site = create_storage_site(capacity_tons=1000.0)
        lot = create_bale_lot(
            ctx["cutting"]["id"], site["id"],
            bale_count=200, harvested_tonnage=100.0,
            harvested_date="2026-06-01",
        )
        set_clock("2026-09-15T00:00:00Z")
        return lot

    def test_allocatable_uses_simple_shrink(self, api):
        """PRD §2.9: "A 100-ton lot stored for three full months in uncontrolled
        storage therefore reports 95.50 allocatable tons before any shipments
        or reservations."

        Design: Difficulty/dual_variant_calc/simple_vs_compound_shrink_tonnage
        """
        lot = self._setup_aged_lot()
        read = get_lot(lot["id"])
        assert_tonnage(read["allocatable_tonnage"], 95.5, "allocatable_tonnage")

    def test_physical_uses_compound_shrink_and_diverges(self, api):
        """PRD §2.9: "the same 100-ton lot after three uncontrolled months
        physically occupies 95.57 tons". PRD §2.9: "Because the two variants
        diverge, a lot can fit a site's remaining capacity by physical tonnage
        while its accounting tonnage tells a different story for allocation
        purposes."

        Design: Difficulty/dual_variant_calc/simple_vs_compound_shrink_tonnage
        """
        lot = self._setup_aged_lot()
        read = get_lot(lot["id"])
        assert_tonnage(read["physical_tonnage"], 95.57, "physical_tonnage")
        assert read["allocatable_tonnage"] != read["physical_tonnage"]


# ===========================================================================
# Corner/cross_cutting_layers / shrink_cap_applies_at_12_percent
# ===========================================================================

def test_shrink_cap_binds_both_variants_at_12_percent(api):
    """PRD §2.9: the accounting variant is "capped so total shrink never
    exceeds 12 percent of the harvested tonnage" and the physical variant is
    "floored so shrink never exceeds 12 percent of harvest".

    At 10 stored months (2026-06-01 -> 2027-04-15) the simple variant's raw
    15% shrink caps at 12% (88.0t) and the compound variant's raw ~85.97t is
    raised to the same 88.0t floor.

    Design: Corner/cross_cutting_layers/shrink_cap_applies_at_12_percent
    """
    ctx = setup_cut_cutting(
        cutting_overrides={
            "planned_window_start": "2026-05-25",
            "planned_window_end": "2026-06-05",
        },
        dry_dates=["2026-05-30", "2026-05-31", "2026-06-01"],
        cut_date="2026-06-01",
    )
    site = create_storage_site(capacity_tons=1000.0)
    lot = create_bale_lot(
        ctx["cutting"]["id"], site["id"],
        bale_count=200, harvested_tonnage=100.0, harvested_date="2026-06-01",
    )
    set_clock("2027-04-15T00:00:00Z")
    read = get_lot(lot["id"])
    assert_tonnage(read["allocatable_tonnage"], 88.0, "allocatable_tonnage")
    assert_tonnage(read["physical_tonnage"], 88.0, "physical_tonnage")


# ===========================================================================
# Corner/calculations / shrink_moisture_controlled_half_rate
# ===========================================================================

def test_moisture_controlled_site_halves_shrink_rate(api):
    """PRD §2.9: "each full calendar month of storage consumes a fixed
    percentage of the *original* harvested tonnage — 1.5 percent per month in
    ordinary storage, halved to 0.75 percent per month while the lot's
    current storage site is moisture-controlled".

    100.0t over 3 months in a controlled site: 100 x (1 - 3 x 0.0075) = 97.75
    allocatable (vs 95.50 uncontrolled).

    Design: Corner/calculations/shrink_moisture_controlled_half_rate
    """
    ctx = setup_cut_cutting(
        cutting_overrides={
            "planned_window_start": "2026-05-25",
            "planned_window_end": "2026-06-05",
        },
        dry_dates=["2026-05-30", "2026-05-31", "2026-06-01"],
        cut_date="2026-06-01",
    )
    site = create_storage_site(capacity_tons=1000.0, moisture_controlled=True)
    lot = create_bale_lot(
        ctx["cutting"]["id"], site["id"],
        bale_count=200, harvested_tonnage=100.0, harvested_date="2026-06-01",
    )
    set_clock("2026-09-15T00:00:00Z")
    read = get_lot(lot["id"])
    assert_tonnage(read["allocatable_tonnage"], 97.75, "allocatable_tonnage")


# ===========================================================================
# Corner/state_machines / spoilage_event_recomputes_tonnage
# ===========================================================================

def test_spoilage_event_recomputes_tonnage(api):
    """PRD §3.2: "Each event adds its `tons_lost` to the lot's cumulative
    `spoilage_tonnage`, and both derived tonnage fields are recomputed on the
    next read. A lot's spoilage history is retrievable as a list."

    A 20.0t lot at zero stored months loses 3.0t to MOLD: spoilage_tonnage
    becomes 3.0 and allocatable_tonnage drops from 20.0 to 17.0.

    Design: Corner/state_machines/spoilage_event_recomputes_tonnage
    """
    ctx = setup_lot(lot_overrides={"bale_count": 40, "harvested_tonnage": 20.0})
    event = post_spoilage_event(ctx["lot"]["id"], 3.0, reason="MOLD")
    read = get_lot(ctx["lot"]["id"])
    assert_tonnage(read["spoilage_tonnage"], 3.0, "spoilage_tonnage")
    assert_tonnage(read["allocatable_tonnage"], 17.0, "allocatable_tonnage")
    events, meta = validate_paginated(
        api_client.list_spoilage_events(ctx["lot"]["id"], OPS)
    )
    assert meta["total_count"] == 1
    assert_tonnage(events[0]["tons_lost"], 3.0, "event tons_lost")
    assert events[0]["id"] == event["id"]


# ===========================================================================
# Corner/entities / lot_creation_computed_fields
# ===========================================================================

def test_lot_creation_computed_fields(api):
    """PRD §3.2: "New lots are born `ACTIVE` and `UNGRADED`: `quality_tier`
    starts `UNGRADED`, `certified_protein_pct` stays null, and the three
    cumulative counters `shipped_tonnage`, `spoilage_tonnage`, and
    `open_allocated_tonnage` all start at 0.0." PRD §3.1: "The first bale lot
    successfully created from a `CUT` cutting automatically advances the
    cutting to `HARVESTED`".

    At zero stored months (harvested 2026-08-01, clock 2026-08-01) both
    derived tonnages equal the 6.0t harvest figure.

    Design: Corner/entities/lot_creation_computed_fields
    """
    ctx = setup_lot(lot_overrides={"bale_count": 10, "harvested_tonnage": 6.0,
                                   "bale_type": "ROUND"})
    lot = ctx["lot"]
    assert_bale_lot(lot)
    assert lot["quality_tier"] == "UNGRADED"
    assert lot["status"] == "ACTIVE"
    assert_tonnage(lot["allocatable_tonnage"], 6.0, "allocatable_tonnage")
    assert_tonnage(lot["physical_tonnage"], 6.0, "physical_tonnage")
    assert_tonnage(lot["shipped_tonnage"], 0.0, "shipped_tonnage")
    assert_tonnage(lot["spoilage_tonnage"], 0.0, "spoilage_tonnage")
    assert_tonnage(lot["open_allocated_tonnage"], 0.0, "open_allocated_tonnage")
    cutting = validate_success(
        api_client.get_cutting(ctx["cutting"]["id"], ADMIN)
    )
    assert cutting["status"] == "HARVESTED"


# ===========================================================================
# Corner/entities / site_default_moisture_controlled_false
# ===========================================================================

def test_site_default_moisture_controlled_false(api):
    """PRD §3.2: storage sites are created with "a `capacity_tons` ceiling
    that must be greater than zero, and an optional `moisture_controlled`
    flag (default false) that, when true, halves the monthly shrink rate
    applied to lots stored there."

    Design: Corner/entities/site_default_moisture_controlled_false
    """
    site = create_storage_site(name="Pad 1", region_code="WA-YAKIMA",
                               capacity_tons=300.0)
    assert site["moisture_controlled"] is False


# ===========================================================================
# Corner/validations / capacity_boundary_equality_then_overflow
# ===========================================================================

def test_capacity_boundary_equality_then_overflow(api):
    """PRD §2.10: "the site's current occupancy plus the incoming lot's
    `physical_tonnage` must not exceed the site's `capacity_tons`; exact
    equality with capacity is allowed, and any excess is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    Two 100.0t lots exactly fill a 200.0t site (200.0 == 200.0 allowed); a
    further 0.5t lot overflows and is rejected.

    Design: Corner/validations/capacity_boundary_equality_then_overflow
    """
    ctx = setup_cut_cutting()
    site = create_storage_site(capacity_tons=200.0)
    create_bale_lot(ctx["cutting"]["id"], site["id"],
                    bale_count=200, harvested_tonnage=100.0)
    create_bale_lot(ctx["cutting"]["id"], site["id"],
                    bale_count=200, harvested_tonnage=100.0)
    occ = validate_success(api_client.get_site_occupancy(site["id"], OPS))
    assert_tonnage(occ["occupied_physical_tons"], 200.0, "occupied")
    resp = api_client.create_bale_lot(
        {
            "cutting_id": ctx["cutting"]["id"], "storage_site_id": site["id"],
            "bale_type": "ROUND", "bale_count": 1, "harvested_tonnage": 0.5,
            "harvested_date": "2026-08-01",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


# ===========================================================================
# Corner/endpoints / occupancy_computed_read
# ===========================================================================

def test_occupancy_computed_read(api):
    """PRD §2.10: "The site exposes a computed read returning
    `occupied_physical_tons`, `capacity_tons`, `available_tons`, and
    `lot_count`, all evaluated at the current logical clock."

    One 50.0t lot at zero stored months in a 500.0t site: occupied 50.0,
    available 450.0, lot_count 1.

    Design: Corner/endpoints/occupancy_computed_read
    """
    ctx = setup_lot(lot_overrides={"bale_count": 100, "harvested_tonnage": 50.0})
    occ = validate_success(
        api_client.get_site_occupancy(ctx["site"]["id"], OPS)
    )
    assert_tonnage(occ["occupied_physical_tons"], 50.0, "occupied")
    assert_tonnage(occ["capacity_tons"], 500.0, "capacity")
    assert_tonnage(occ["available_tons"], 450.0, "available")
    assert occ["lot_count"] == 1


# ===========================================================================
# Corner/endpoints / lot_transfer_moves_between_sites
# ===========================================================================

def test_lot_transfer_moves_between_sites(api):
    """PRD §3.2: "A successful transfer updates the lot's `storage_site_id`
    and increments the lot's `version` by one". PRD §2.10: "A storage site's
    physical occupancy is the sum of the `physical_tonnage` of every bale lot
    currently assigned to that site whose status is `ACTIVE` or `DEPLETED`".

    Moving a 50.0t lot from S1 to S2 shifts occupancy 50.0 -> 0.0 on S1 and
    0.0 -> 50.0 on S2; tonnage is conserved.

    Design: Corner/endpoints/lot_transfer_moves_between_sites
    """
    ctx = setup_cut_cutting()
    site1 = create_storage_site(name="Barn AB")
    site2 = create_storage_site(name="Barn AC")
    lot = create_bale_lot(ctx["cutting"]["id"], site1["id"],
                          bale_count=100, harvested_tonnage=50.0)
    moved = validate_success(api_client.transfer_lot(
        lot["id"],
        {"dest_storage_site_id": site2["id"],
         "expected_bale_lot_version": lot["version"]},
        OPS,
    ))
    assert moved["storage_site_id"] == site2["id"]
    assert moved["version"] == lot["version"] + 1
    occ1 = validate_success(api_client.get_site_occupancy(site1["id"], OPS))
    occ2 = validate_success(api_client.get_site_occupancy(site2["id"], OPS))
    assert_tonnage(occ1["occupied_physical_tons"], 0.0, "origin occupancy")
    assert_tonnage(occ2["occupied_physical_tons"], 50.0, "destination occupancy")


# ===========================================================================
# Corner/validations / lot_zero_tonnage_rejected
# ===========================================================================

def test_lot_zero_tonnage_rejected(api):
    """PRD §3.2: the creation payload carries "a `bale_count` greater than
    zero, the as-baled `harvested_tonnage` greater than zero, and the
    `harvested_date` from which shrink accrues." PRD §2.6 names "tonnage
    positivity" among the business constraints surfaced as
    `ERR_TONS_NOT_POSITIVE` (HTTP 422, PRD §5).

    Design: Corner/validations/lot_zero_tonnage_rejected
    """
    ctx = setup_cut_cutting()
    site = create_storage_site()
    resp = api_client.create_bale_lot(
        {
            "cutting_id": ctx["cutting"]["id"], "storage_site_id": site["id"],
            "bale_type": "ROUND", "bale_count": 10, "harvested_tonnage": 0.0,
            "harvested_date": "2026-08-01",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_TONS_NOT_POSITIVE)


# ===========================================================================
# Corner/validations / cutting_not_cut_blocks_lot
# ===========================================================================

def test_cutting_not_cut_blocks_lot(api):
    """PRD §3.2: "A bale lot is created by `BrokerOps` or `PlatformAdmin` from
    a cutting that has reached `CUT` or `HARVESTED` — attempting it against a
    cutting in any earlier state is rejected with `ERR_CUTTING_NOT_CUT`".

    Design: Corner/validations/cutting_not_cut_blocks_lot
    """
    _grower, _field, cutting = setup_scheduled_cutting()
    site = create_storage_site()
    resp = api_client.create_bale_lot(
        {
            "cutting_id": cutting["id"], "storage_site_id": site["id"],
            "bale_type": "ROUND", "bale_count": 10, "harvested_tonnage": 5.0,
            "harvested_date": "2026-08-01",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CUTTING_NOT_CUT)


# ===========================================================================
# Corner/validations / lot_double_condemn_rejected
# ===========================================================================

def test_lot_double_condemn_rejected(api):
    """PRD §3.2: "`BrokerOps` (or `PlatformAdmin`) may condemn an `ACTIVE`
    lot — condemning from any other state is rejected with
    `ERR_LOT_NOT_ACTIVE`."

    Design: Corner/validations/lot_double_condemn_rejected
    """
    ctx = setup_lot()
    validate_success(api_client.condemn_lot(ctx["lot"]["id"], OPS))
    resp = api_client.condemn_lot(ctx["lot"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACTIVE)
