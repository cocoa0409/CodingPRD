"""Composite setup helpers.

Every helper replays from an empty database using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors instead of confusing assertion failures.

Height-class ordering note: a lot's stand-bucket listing is returned in
declared height-class order (H_4_5 first, H_9_PLUS last), so buckets[i] is
the bucket for the i-th class of HEIGHT_CLASS_ORDER.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import AMPLE_CREDIT_LIMIT_CENTS, CLOCK
from .factories import (
    _zeroed_counts,
    create_block_payload,
    create_buyer_account_payload,
    create_consignment_payload,
    create_crew_payload,
    create_crop_lot_payload,
    create_cull_record_payload,
    create_load_payload,
    create_order_payload,
    create_replant_plan_payload,
    create_season_payload,
    create_survey_payload,
    create_ticket_payload,
    create_ucut_tag_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_crew_lead_headers,
    make_farm_manager_headers,
    make_owner_headers,
)

OWNER = TEST_USERS["owner_headers"]
FM = TEST_USERS["farm_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_season(**overrides):
    """Create a season (born PLANNING, ops_run_index 0). Returns Season."""
    resp = api_client.create_season(create_season_payload(**overrides), OWNER)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, OWNER)
    get_success_data(resp)


def advance_season_to(season_id, target_posture):
    """Walk the season forward one step per call until it reaches
    target_posture. Clock gates are the caller's responsibility."""
    order = ["PLANNING", "BOOKING", "HARVEST", "SHIPPING", "SETTLEMENT", "CLOSED"]
    season = get_success_data(api_client.get_season(season_id, OWNER))
    current = season["posture"]
    while current != target_posture:
        nxt = order[order.index(current) + 1]
        season = get_success_data(
            api_client.advance_posture(season_id, nxt, OWNER)
        )
        current = season["posture"]
    return season


def create_block(season_id, **overrides):
    resp = api_client.create_block(create_block_payload(season_id, **overrides), FM)
    return get_success_data(resp)


def create_crop_lot(block_id, **counts_by_class):
    """Plant a lot. Keyword args like H_6_7=300 fill initial_counts; other
    overrides (species, planted_year) pass through. Returns CropLot."""
    lot_overrides = {}
    for key in ("species", "planted_year"):
        if key in counts_by_class:
            lot_overrides[key] = counts_by_class.pop(key)
    counts = {k: v for k, v in counts_by_class.items() if k.startswith("H_")}
    if counts:
        lot_overrides["initial_counts"] = _zeroed_counts(**counts)
    resp = api_client.create_crop_lot(
        create_crop_lot_payload(block_id, **lot_overrides), FM
    )
    return get_success_data(resp)


def list_buckets(crop_lot_id):
    """Return the lot's six buckets in declared height-class order."""
    resp = api_client.list_stand_buckets(crop_lot_id, FM)
    data, _meta = validate_paginated(resp)
    return data


def bucket_of(crop_lot_id, height_class):
    """Return the lot's bucket for one height class."""
    idx = ["H_4_5", "H_5_6", "H_6_7", "H_7_8", "H_8_9", "H_9_PLUS"].index(
        height_class
    )
    return list_buckets(crop_lot_id)[idx]


def advance_block_to(block_id, target_state):
    """Drive the block rotation forward until rotation_state == target_state.
    Caller is responsible for guards (active lot, no open allocations/tags,
    depleted lots). Returns the final Block."""
    order = ["RESTING", "PLANTED", "GROWING", "HARVESTABLE", "HARVESTED", "RESTING"]
    block = get_success_data(api_client.get_block(block_id, FM))
    current = block["rotation_state"]
    while current != target_state:
        block = get_success_data(api_client.advance_rotation(block_id, FM))
        current = block["rotation_state"]
        if current not in order:
            raise AssertionError(f"unexpected rotation_state {current}")
    return block


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_season_with_block_and_lot(species="NOBLE_FIR", planted_year=2019,
                                    block_overrides=None, **counts):
    """Season (PLANNING) + one block + one planted lot.
    Returns dict with season, block, lot, and buckets list."""
    season = create_season()
    block = create_block(season["id"], **(block_overrides or {}))
    lot = create_crop_lot(block["id"], species=species,
                          planted_year=planted_year, **counts)
    return {
        "season": season,
        "block": block,
        "lot": lot,
        "buckets": list_buckets(lot["id"]),
    }


def setup_booking_season(**counts):
    """Season advanced to BOOKING at the booking_open instant, with one block
    and one lot already planted. Returns the hierarchy dict."""
    ctx = setup_season_with_block_and_lot(**counts)
    set_clock(CLOCK["BOOKING_OPEN"])
    advance_season_to(ctx["season"]["id"], "BOOKING")
    return ctx


def setup_harvest_season(ucut=False, advance_block=True, **counts):
    """Season advanced to HARVEST at a mid-harvest instant, with one block
    (optionally advanced to HARVESTABLE) and one planted lot."""
    ctx = setup_season_with_block_and_lot(
        block_overrides={"ucut_designated": ucut}, **counts
    )
    if advance_block:
        advance_block_to(ctx["block"]["id"], "HARVESTABLE")
    set_clock(CLOCK["HARVEST_DAY"])
    advance_season_to(ctx["season"]["id"], "HARVEST")
    ctx["buckets"] = list_buckets(ctx["lot"]["id"])
    return ctx


def create_buyer(name="Acme Wholesale", credit_limit_cents=AMPLE_CREDIT_LIMIT_CENTS):
    resp = api_client.create_buyer_account(
        create_buyer_account_payload(name=name,
                                     credit_limit_cents=credit_limit_cents),
        OWNER,
    )
    return get_success_data(resp)


def create_draft_order(season_id, buyer_id, **overrides):
    """Create a DRAFT order under the given buyer's own identity."""
    resp = api_client.create_order(
        create_order_payload(season_id, buyer_id, **overrides),
        make_buyer_headers(buyer_id),
    )
    return get_success_data(resp)


def submit_order(order_id, buyer_id):
    resp = api_client.submit_order(order_id, make_buyer_headers(buyer_id))
    return get_success_data(resp)


def allocate_order(order_id, quantity, expected_order_version):
    resp = api_client.allocate_order(order_id, quantity,
                                     expected_order_version, FM)
    return get_success_data(resp)


def list_order_allocations(order_id, **extra_params):
    params = {"order_id": order_id}
    params.update(extra_params)
    resp = api_client.list_allocations(FM, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_submitted_order(species="NOBLE_FIR", height_class="H_6_7",
                          quantity=10, unit_price_cents=400,
                          credit_limit_cents=AMPLE_CREDIT_LIMIT_CENTS,
                          **counts):
    """BOOKING season + lot + buyer + one SUBMITTED order.
    Returns dict with season, block, lot, buckets, buyer, order."""
    ctx = setup_booking_season(species=species, **counts)
    buyer = create_buyer(credit_limit_cents=credit_limit_cents)
    order = create_draft_order(
        ctx["season"]["id"], buyer["id"],
        species=species, height_class=height_class,
        quantity=quantity, unit_price_cents=unit_price_cents,
    )
    order = submit_order(order["id"], buyer["id"])
    ctx.update({"buyer": buyer, "order": order})
    return ctx


def setup_allocated_order(species="NOBLE_FIR", height_class="H_6_7",
                          quantity=10, unit_price_cents=400,
                          advance_block=False,
                          credit_limit_cents=AMPLE_CREDIT_LIMIT_CENTS,
                          **counts):
    """SUBMITTED order with the waterfall run once for its full quantity.
    Returns dict adding order (fresh), allocations list, and allocation."""
    ctx = setup_submitted_order(
        species=species, height_class=height_class, quantity=quantity,
        unit_price_cents=unit_price_cents,
        credit_limit_cents=credit_limit_cents, **counts,
    )
    if advance_block:
        advance_block_to(ctx["block"]["id"], "HARVESTABLE")
    result = allocate_order(ctx["order"]["id"], quantity, ctx["order"]["version"])
    order = get_success_data(api_client.get_order(ctx["order"]["id"], FM))
    allocations = list_order_allocations(order["id"])
    ctx.update({
        "order": order,
        "allocations": allocations,
        "allocation": allocations[0] if allocations else None,
        "allocate_result": result,
    })
    return ctx


def create_crew(season_id, **overrides):
    resp = api_client.create_crew(create_crew_payload(season_id, **overrides), FM)
    return get_success_data(resp)


def setup_harvest_with_crew(crew_size=5, crew_code="C-1", **kwargs):
    """Allocated order in a HARVEST season, block HARVESTABLE, one ACTIVE crew.
    Returns dict adding crew (with crew lead headers ready via .id)."""
    ctx = setup_allocated_order(advance_block=True, **kwargs)
    set_clock(CLOCK["HARVEST_DAY"])
    advance_season_to(ctx["season"]["id"], "HARVEST")
    crew = create_crew(ctx["season"]["id"], crew_code=crew_code, size=crew_size)
    ctx["crew"] = crew
    ctx["buckets"] = list_buckets(ctx["lot"]["id"])
    return ctx


def post_ticket(crew, block_id, lines, work_date="2026-11-05", hours_worked=8):
    """Post a harvest ticket as the crew's own lead. Returns HarvestTicket."""
    resp = api_client.create_ticket(
        create_ticket_payload(
            crew["id"], block_id, lines,
            work_date=work_date, hours_worked=hours_worked,
        ),
        make_crew_lead_headers(crew["id"]),
    )
    return get_success_data(resp)


def setup_cut_allocation(crew_size=3, **kwargs):
    """Allocated order whose allocation is fully CUT via one ticket.
    Returns dict adding crew and ticket."""
    ctx = setup_harvest_with_crew(crew_size=crew_size, **kwargs)
    qty = ctx["allocation"]["quantity"]
    ticket = post_ticket(
        ctx["crew"], ctx["block"]["id"],
        [{"allocation_id": ctx["allocation"]["id"], "cut_count": qty}],
    )
    ctx["ticket"] = ticket
    ctx["allocation"] = get_success_data(
        api_client.get_allocation(ctx["allocation"]["id"], FM)
    )
    ctx["buckets"] = list_buckets(ctx["lot"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: loads and consignments
# ---------------------------------------------------------------------------

def create_load(season_id, **overrides):
    resp = api_client.create_load(create_load_payload(season_id, **overrides), FM)
    return get_success_data(resp)


def setup_loaded_allocation(crew_size=3, capacity_units=100, **kwargs):
    """Fully allocated -> cut -> loaded chain: the allocation reaches LOADED.
    Returns dict adding crew, ticket, load."""
    ctx = setup_cut_allocation(crew_size=crew_size, **kwargs)
    load = create_load(ctx["season"]["id"], capacity_units=capacity_units)
    qty = ctx["allocation"]["cut_qty"]
    resp = api_client.add_load_line(load["id"], ctx["allocation"]["id"], qty, FM)
    load = get_success_data(resp)
    ctx["load"] = load
    ctx["allocation"] = get_success_data(
        api_client.get_allocation(ctx["allocation"]["id"], FM)
    )
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], FM))
    ctx["buckets"] = list_buckets(ctx["lot"]["id"])
    return ctx


def create_consignment(season_id, bucket_id, **overrides):
    resp = api_client.create_consignment(
        create_consignment_payload(season_id, bucket_id, **overrides), FM
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: surveys, tags, culls, replants
# ---------------------------------------------------------------------------

def create_survey(crop_lot_id, **counts):
    resp = api_client.create_survey(
        create_survey_payload(crop_lot_id, surveyed_counts=_zeroed_counts(**counts)),
        FM,
    )
    return get_success_data(resp)


def create_cull(bucket_id, count, reason="DISEASE"):
    resp = api_client.create_cull_record(
        create_cull_record_payload(bucket_id, count=count, reason=reason), FM
    )
    return get_success_data(resp)


def create_ucut_tag(block_id, bucket_id, **overrides):
    resp = api_client.create_ucut_tag(
        create_ucut_tag_payload(block_id, bucket_id, **overrides), FM
    )
    return get_success_data(resp)


def setup_harvested_block_bare(tree_count=50, height_class="H_6_7",
                               reason="DISEASE"):
    """Block advanced to HARVESTED with its only stocked bucket culled to zero
    (the lot auto-DEPLETED along the way). Returns hierarchy dict."""
    ctx = setup_season_with_block_and_lot(**{height_class: tree_count})
    bucket = bucket_of(ctx["lot"]["id"], height_class)
    advance_block_to(ctx["block"]["id"], "HARVESTABLE")
    create_cull(bucket["id"], tree_count, reason=reason)
    ctx["block"] = advance_block_to(ctx["block"]["id"], "HARVESTED")
    ctx["lot"] = get_success_data(api_client.get_crop_lot(ctx["lot"]["id"], FM))
    ctx["buckets"] = list_buckets(ctx["lot"]["id"])
    return ctx


def create_replant_plan(block_id, proposer_user_id, **overrides):
    resp = api_client.create_replant_plan(
        create_replant_plan_payload(block_id, **overrides),
        make_farm_manager_headers(proposer_user_id),
    )
    return get_success_data(resp)
