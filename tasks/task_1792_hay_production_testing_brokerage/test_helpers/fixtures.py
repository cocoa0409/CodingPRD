"""Composite setup helpers.

Most testable claims in this PRD require the system to be in a state that
takes 5-15 API calls to reach (a WINDOW_OPEN cutting, a certified lot, an
accepted contract, a delivered load). These fixtures encapsulate those
preambles so tests can focus on assertions. Every fixture builds its state
from scratch via the public endpoints — the server is restarted before
every test, so each test starts against an empty database with the logical
clock at its startup default.

Identity threading: Grower and Buyer are entity-backed roles (PRD §2.1).
After creating a Grower/Buyer, ownership-gated calls use
make_grower_headers(grower["id"]) / make_buyer_headers(buyer["id"]).

Shared schedule (mirrors the canonical scenarios): cutting window
2026-07-25..2026-08-10 opened by dry reports on 2026-07-29/30/31, cut on
2026-07-31, harvested 2026-08-01 (zero full months of shrink at the
default clock 2026-08-01).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    REGION_OR,
    STD_CUT_DATE,
    STD_DRY_DATES,
    STD_HARVEST_DATE,
    TECH_CERTIFIER,
    TECH_RECORDER,
)
from .factories import (
    complete_baling_payload,
    create_bale_lot_payload,
    create_baling_service_order_payload,
    create_buyer_payload,
    create_cutting_payload,
    create_delivery_load_payload,
    create_field_payload,
    create_forage_test_payload,
    create_freight_lane_payload,
    create_grower_payload,
    create_load_allocation_payload,
    create_market_index_payload,
    create_quote_payload,
    create_spoilage_event_payload,
    create_storage_site_payload,
    create_weather_report_payload,
    record_result_payload,
    schedule_baling_payload,
    submit_forage_test_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_grower_headers,
    make_tech_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin). Returns the response data."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_grower(**overrides):
    """Create a grower (PlatformAdmin). Returns Grower."""
    return get_success_data(api_client.create_grower(create_grower_payload(**overrides), ADMIN))


def create_buyer(**overrides):
    """Create a buyer (PlatformAdmin). Returns Buyer."""
    return get_success_data(api_client.create_buyer(create_buyer_payload(**overrides), ADMIN))


def create_field(grower_id, **overrides):
    """Create a field as the owning grower. Returns Field."""
    headers = make_grower_headers(grower_id)
    return get_success_data(
        api_client.create_field(create_field_payload(grower_id, **overrides), headers)
    )


def create_cutting(field_id, grower_id, **overrides):
    """Create a cutting as the owning grower. Returns Cutting (SCHEDULED)."""
    headers = make_grower_headers(grower_id)
    return get_success_data(
        api_client.create_cutting(create_cutting_payload(field_id, **overrides), headers)
    )


def post_weather_report(report_date, region_code=REGION_OR,
                        precipitation_mm=0.0, drying_index=70):
    """Post one weather report (PlatformAdmin). Returns WeatherReport."""
    return get_success_data(api_client.create_weather_report(
        create_weather_report_payload(
            report_date, region_code=region_code,
            precipitation_mm=precipitation_mm, drying_index=drying_index,
        ),
        ADMIN,
    ))


def post_dry_reports(dates, region_code=REGION_OR, precipitation_mm=0.0,
                     drying_index=70):
    """Post a dry, drying-capable report for each date in `dates`."""
    for d in dates:
        post_weather_report(
            d, region_code=region_code,
            precipitation_mm=precipitation_mm, drying_index=drying_index,
        )


def create_storage_site(**overrides):
    """Create a storage site (PlatformAdmin). Returns StorageSite."""
    return get_success_data(
        api_client.create_storage_site(create_storage_site_payload(**overrides), ADMIN)
    )


def create_market_index(**overrides):
    """Post a market index (PlatformAdmin). Returns MarketIndex."""
    return get_success_data(
        api_client.create_market_index(create_market_index_payload(**overrides), ADMIN)
    )


def create_freight_lane(**overrides):
    """Create a freight lane (PlatformAdmin). Returns FreightLane."""
    return get_success_data(
        api_client.create_freight_lane(create_freight_lane_payload(**overrides), ADMIN)
    )


def create_delivery_load(**overrides):
    """Create a delivery load (BrokerOps). Returns DeliveryLoad (PLANNED x OPEN)."""
    return get_success_data(
        api_client.create_delivery_load(create_delivery_load_payload(**overrides), OPS)
    )


# ---------------------------------------------------------------------------
# Tier 2: grower chain and weather-driven cutting states
# ---------------------------------------------------------------------------

def setup_grower_with_field(grower_overrides=None, field_overrides=None):
    """Grower + one field. Returns (grower, field)."""
    grower = create_grower(**(grower_overrides or {}))
    field = create_field(grower["id"], **(field_overrides or {}))
    return grower, field


def setup_scheduled_cutting(grower_overrides=None, field_overrides=None,
                            cutting_overrides=None):
    """Grower + field + one SCHEDULED cutting. Returns (grower, field, cutting)."""
    grower, field = setup_grower_with_field(grower_overrides, field_overrides)
    cutting = create_cutting(field["id"], grower["id"], **(cutting_overrides or {}))
    return grower, field, cutting


def open_cutting_window(cutting_id, region_code=REGION_OR, dry_dates=None,
                        grower_id=None):
    """Drive a cutting to WINDOW_OPEN with three dry reports, return it."""
    post_dry_reports(dry_dates or list(STD_DRY_DATES), region_code=region_code)
    reader = make_grower_headers(grower_id) if grower_id else ADMIN
    return get_success_data(api_client.get_cutting(cutting_id, reader))


def mark_cutting_cut(cutting_id, grower_id, actual_cut_date=STD_CUT_DATE):
    """Mark a WINDOW_OPEN cutting cut as the owning grower. Returns Cutting."""
    return get_success_data(api_client.mark_cut(
        cutting_id, {"actual_cut_date": actual_cut_date},
        make_grower_headers(grower_id),
    ))


def setup_cut_cutting(grower_overrides=None, field_overrides=None,
                      cutting_overrides=None, region_code=REGION_OR,
                      dry_dates=None, cut_date=STD_CUT_DATE):
    """Grower + field + cutting driven to CUT via weather reports.

    Returns dict: {grower, field, cutting}.
    """
    grower, field, cutting = setup_scheduled_cutting(
        grower_overrides, field_overrides, cutting_overrides,
    )
    open_cutting_window(
        cutting["id"], region_code=region_code, dry_dates=dry_dates,
        grower_id=grower["id"],
    )
    cutting = mark_cutting_cut(cutting["id"], grower["id"], actual_cut_date=cut_date)
    return {"grower": grower, "field": field, "cutting": cutting}


def get_cutting(cutting_id, headers=None):
    return get_success_data(api_client.get_cutting(cutting_id, headers or ADMIN))


def get_lot(lot_id):
    return get_success_data(api_client.get_bale_lot(lot_id, OPS))


def get_load(load_id):
    return get_success_data(api_client.get_delivery_load(load_id, OPS))


def get_buyer(buyer_id):
    return get_success_data(api_client.get_buyer(buyer_id, ADMIN))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, OPS))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_load_allocation(allocation_id, OPS))


# ---------------------------------------------------------------------------
# Tier 3: bale lots and certified quality
# ---------------------------------------------------------------------------

def create_bale_lot(cutting_id, storage_site_id, **overrides):
    """Create a bale lot (BrokerOps). Returns BaleLot (ACTIVE, UNGRADED)."""
    return get_success_data(api_client.create_bale_lot(
        create_bale_lot_payload(cutting_id, storage_site_id, **overrides), OPS,
    ))


def setup_lot(cutting_ctx=None, site=None, lot_overrides=None,
              region_code=REGION_OR, site_overrides=None, **chain_kwargs):
    """Cutting at CUT + storage site + one bale lot.

    Returns dict: {grower, field, cutting, site, lot}.
    """
    if cutting_ctx is None:
        cutting_ctx = setup_cut_cutting(region_code=region_code, **chain_kwargs)
    if site is None:
        site = create_storage_site(
            region_code=region_code, **(site_overrides or {})
        )
    lot = create_bale_lot(
        cutting_ctx["cutting"]["id"], site["id"], **(lot_overrides or {})
    )
    return {**cutting_ctx, "site": site, "lot": lot}


def certify_lot(lot_id, rfv, protein_pct, moisture_pct,
                sample_date=STD_HARVEST_DATE,
                recorder=TECH_RECORDER, certifier=TECH_CERTIFIER):
    """Collect + submit + record + certify a forage test for a lot.

    The certifier differs from the recorder to satisfy segregation of
    duties (PRD §3.4). Returns the CERTIFIED ForageTest.
    """
    test = get_success_data(api_client.create_forage_test(
        create_forage_test_payload(lot_id, sample_date=sample_date), OPS,
    ))
    get_success_data(api_client.submit_forage_test(
        test["id"], submit_forage_test_payload(), make_tech_headers(recorder),
    ))
    get_success_data(api_client.record_forage_result(
        test["id"],
        record_result_payload(
            rfv=rfv, protein_pct=protein_pct, moisture_pct=moisture_pct,
        ),
        make_tech_headers(recorder),
    ))
    return get_success_data(
        api_client.certify_forage_test(test["id"], make_tech_headers(certifier))
    )


def setup_certified_lot(rfv=155.0, protein_pct=18.0, moisture_pct=14.0,
                        lot_tonnage=10.0, lot_overrides=None, **kwargs):
    """Lot + certified forage test writing the lot's quality tier.

    Returns the setup_lot dict extended with {test}.
    """
    merged_lot = {"harvested_tonnage": lot_tonnage}
    merged_lot.update(lot_overrides or {})
    ctx = setup_lot(lot_overrides=merged_lot, **kwargs)
    test = certify_lot(
        ctx["lot"]["id"], rfv, protein_pct, moisture_pct,
        sample_date=(lot_overrides or {}).get("harvested_date", STD_HARVEST_DATE),
    )
    ctx["test"] = test
    ctx["lot"] = get_lot(ctx["lot"]["id"])
    return ctx


def post_spoilage_event(bale_lot_id, tons_lost, reason="MOLD",
                        event_date=STD_HARVEST_DATE):
    """Record a spoilage event (BrokerOps). Returns SpoilageEvent."""
    return get_success_data(api_client.create_spoilage_event(
        create_spoilage_event_payload(
            bale_lot_id, tons_lost=tons_lost, reason=reason, event_date=event_date,
        ),
        OPS,
    ))


# ---------------------------------------------------------------------------
# Tier 3b: quotes and contracts
# ---------------------------------------------------------------------------

def create_draft_quote(buyer_id, **overrides):
    """Create a DRAFT quote as the owning buyer. Returns Quote."""
    return get_success_data(api_client.create_quote(
        create_quote_payload(buyer_id, **overrides), make_buyer_headers(buyer_id),
    ))


def issue_quote(quote_id, buyer_id):
    """Issue a DRAFT quote as the owning buyer. Returns Quote (ISSUED)."""
    return get_success_data(
        api_client.issue_quote(quote_id, make_buyer_headers(buyer_id))
    )


def accept_quote(quote_id, buyer_id, expected_quote_version):
    """Accept an ISSUED quote as the owning buyer. Returns Quote (ACCEPTED)."""
    return get_success_data(api_client.accept_quote(
        quote_id, {"expected_quote_version": expected_quote_version},
        make_buyer_headers(buyer_id),
    ))


def find_contract_by_quote(quote_id):
    """Return the single contract created from an accepted quote."""
    data, meta = validate_paginated(
        api_client.list_contracts(OPS, params={"quote_id": quote_id})
    )
    assert len(data) == 1, (
        f"Expected exactly 1 contract for quote {quote_id}, got {len(data)}"
    )
    return data[0]


def setup_pricing_bed(region_code=REGION_OR, dest_region=None,
                      forage_type="ALFALFA", index_price=20000,
                      effective_date="2026-05-01", lane_overrides=None):
    """Market index + freight lane needed for quote pricing. Returns (index, lane)."""
    index = create_market_index(
        region_code=region_code, forage_type=forage_type,
        effective_date=effective_date, price_per_ton_cents=index_price,
    )
    lane_kwargs = {"origin_region_code": region_code}
    if dest_region is not None:
        lane_kwargs["dest_region_code"] = dest_region
    lane_kwargs.update(lane_overrides or {})
    lane = create_freight_lane(**lane_kwargs)
    return index, lane


def setup_accepted_contract(tons=5.0, quality_tier="GOOD", credit_limit_cents=1000000,
                            region_code=REGION_OR, dest_region=None,
                            delivery_by="2026-08-20", buyer_overrides=None,
                            index=None, lane=None, forage_type="ALFALFA",
                            index_price=20000):
    """Full accept flow. Returns dict of all created entities:

        {index, lane, buyer, quote, contract}

    Steps: index + lane (unless supplied) -> buyer -> quote -> issue ->
    accept -> contract lookup. The contract opens ACTIVE with the credit
    reserve held.
    """
    if index is None or lane is None:
        index, lane = setup_pricing_bed(
            region_code=region_code, dest_region=dest_region,
            forage_type=forage_type, index_price=index_price,
        )
    # The quote's destination must resolve to the lane's actual
    # dest_region_code (PRD §3.5: ERR_NO_FREIGHT_LANE when no lane exists for
    # the origin-destination pair). When the caller leaves dest_region=None,
    # the pricing bed's lane falls back to the factory default
    # (REGION_CA_NORTH), so the quote must target that same destination.
    eff_dest = dest_region or lane["dest_region_code"]
    buyer_kwargs = {"region_code": eff_dest,
                    "credit_limit_cents": credit_limit_cents}
    buyer_kwargs.update(buyer_overrides or {})
    buyer = create_buyer(**buyer_kwargs)
    quote = create_draft_quote(
        buyer["id"], forage_type=forage_type, quality_tier=quality_tier,
        tons=tons, origin_region_code=region_code,
        dest_region_code=eff_dest,
        requested_delivery_by=delivery_by,
    )
    issued = issue_quote(quote["id"], buyer["id"])
    accepted = accept_quote(quote["id"], buyer["id"], issued["version"])
    contract = find_contract_by_quote(quote["id"])
    return {
        "index": index, "lane": lane, "buyer": buyer,
        "quote": accepted, "contract": contract,
    }


# ---------------------------------------------------------------------------
# Tier 4: loads, allocations, delivery, settlement
# ---------------------------------------------------------------------------

def allocate(load_id, contract_id, lot_id, tons):
    """Create an OPEN allocation against a load (BrokerOps), reading the
    load's current version for the OCC field. Returns LoadAllocation."""
    load = get_load(load_id)
    return get_success_data(api_client.create_load_allocation(
        create_load_allocation_payload(
            load_id, contract_id, lot_id, load["version"], tons=tons,
        ),
        OPS,
    ))


def setup_load_with_allocation(contract_id, lot_id, tons, capacity_tons=25.0):
    """Load + one OPEN allocation. Returns (load, allocation)."""
    load = create_delivery_load(capacity_tons=capacity_tons)
    allocation = allocate(load["id"], contract_id, lot_id, tons)
    return get_load(load["id"]), allocation


def drive_load_to_in_transit(load_id):
    """LOADING then IN_TRANSIT. Returns the updated DeliveryLoad."""
    get_success_data(api_client.start_loading(load_id, OPS))
    get_success_data(api_client.depart_load(load_id, OPS))
    return get_load(load_id)


def drive_load_to_delivered(load_id):
    """LOADING -> IN_TRANSIT -> DELIVERED. Returns the updated DeliveryLoad."""
    drive_load_to_in_transit(load_id)
    get_success_data(api_client.deliver_load(load_id, OPS))
    return get_load(load_id)


def setup_delivered_load(contract_id, lot_id, tons, capacity_tons=25.0):
    """Load + allocation + full logistics path to DELIVERED.

    Returns dict: {load, allocation}.
    """
    load, allocation = setup_load_with_allocation(
        contract_id, lot_id, tons, capacity_tons=capacity_tons,
    )
    load = drive_load_to_delivered(load["id"])
    return {"load": load, "allocation": get_allocation(allocation["id"])}


# ---------------------------------------------------------------------------
# Tier 5: baling service orders
# ---------------------------------------------------------------------------

def create_baling_order(grower_id, cutting_id):
    """Request a baling service order as the owning grower. Returns BSO."""
    return get_success_data(api_client.create_baling_service_order(
        create_baling_service_order_payload(grower_id, cutting_id),
        make_grower_headers(grower_id),
    ))


def schedule_baling_order(order_id, scheduled_date="2026-08-03",
                          equipment_unit="BALER-1"):
    """Schedule a REQUESTED order (BrokerOps). Returns BSO (SCHEDULED)."""
    return get_success_data(api_client.schedule_baling_service_order(
        order_id,
        schedule_baling_payload(
            scheduled_date=scheduled_date, equipment_unit=equipment_unit,
        ),
        OPS,
    ))


def start_baling_order(order_id):
    """SCHEDULED -> IN_PROGRESS (BrokerOps). Returns BSO."""
    return get_success_data(api_client.start_baling_service_order(order_id, OPS))


def complete_baling_order(order_id, actual_bale_count=300, baled_moisture_pct=15.0):
    """IN_PROGRESS -> COMPLETED (BrokerOps). Returns BSO."""
    return get_success_data(api_client.complete_baling_service_order(
        order_id,
        complete_baling_payload(
            actual_bale_count=actual_bale_count,
            baled_moisture_pct=baled_moisture_pct,
        ),
        OPS,
    ))


def setup_in_progress_baling_order(cutting_ctx=None, equipment_unit="BALER-1",
                                   scheduled_date="2026-08-03", **chain_kwargs):
    """Cutting WINDOW_OPEN + BSO walked REQUESTED -> SCHEDULED -> IN_PROGRESS.

    Returns the setup_cut_cutting dict extended with {bso}.
    """
    if cutting_ctx is None:
        # The schedule gate requires WINDOW_OPEN or CUT, so stop at WINDOW_OPEN.
        cutting_ctx = {}
        grower, field, cutting = setup_scheduled_cutting(**chain_kwargs)
        cutting = open_cutting_window(
            cutting["id"], grower_id=grower["id"],
        )
        cutting_ctx = {"grower": grower, "field": field, "cutting": cutting}
    bso = create_baling_order(
        cutting_ctx["grower"]["id"], cutting_ctx["cutting"]["id"],
    )
    schedule_baling_order(
        bso["id"], scheduled_date=scheduled_date, equipment_unit=equipment_unit,
    )
    bso = start_baling_order(bso["id"])
    return {**cutting_ctx, "bso": bso}
