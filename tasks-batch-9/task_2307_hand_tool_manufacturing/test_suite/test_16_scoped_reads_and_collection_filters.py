"""Nested collections scoped to their addressed parent, and the declared filters
and pagination envelope of every top-level collection."""

from test_helpers import (
    TEST_USERS,
    add_pack_member,
    advance_lot,
    api_client,
    complete_campaign,
    create_chamber,
    create_claimant,
    create_furnace,
    create_lot,
    create_pack,
    create_program,
    create_report,
    create_sku,
    read_pack,
    schedule_campaign,
    schedule_test_run,
    validate_paginated,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]

HARDNESS_SLOT = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
SOCKET_SKU = {
    "sku_code": "SO-20-BR",
    "tool_family": "SOCKET",
    "nominal_size_mm": 20,
    "alloy_grade": "CR_V",
    "list_price_cents": 1500,
}
PROFESSIONAL_SOCKET = {
    "sku_code": "SO-19-PRO",
    "tool_family": "SOCKET",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 19,
    "alloy_grade": "CR_V",
    "list_price_cents": 2600,
    "warranty_tier": "LIMITED_5Y",
}


def _assert_envelope(meta):
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta must carry {key}"


# ---------------------------------------------------------------------------
# Nested collections belong to their parent
# ---------------------------------------------------------------------------


def _a_dual_alloy_furnace():
    return create_furnace(alloy_grades_supported=["CR_MO", "CR_V"])


def _two_skus_with_lots_packs_and_one_run():
    """SKU 1 owns two lots and is packed twice; SKU 2 owns one lot and is packed
    once. Only the first lot of SKU 1 carries a scheduled hardness run."""
    sku1 = create_sku()
    sku2 = create_sku(**SOCKET_SKU)
    furnace = _a_dual_alloy_furnace()
    lot1 = create_lot(sku1["id"], lot_code="LOT-1A", unit_count=100, specimen_pool_total=20)
    lot2 = create_lot(sku1["id"], lot_code="LOT-1B", unit_count=100, specimen_pool_total=20)
    lot3 = create_lot(sku2["id"], lot_code="LOT-2A", unit_count=100, specimen_pool_total=20)

    campaign = schedule_campaign(lot1["id"], furnace["id"], charge_kg=800)
    complete_campaign(campaign["id"])
    advance_lot(lot1["id"], "HEAT_TREATED")
    run = schedule_test_run(lot1["id"], "HARDNESS", 2, HARDNESS_SLOT)

    pack1 = create_pack(sku1["id"], pack_code="PK-1", pack_type="RETAIL_DISPLAY")
    pack2 = create_pack(sku1["id"], pack_code="PK-2", pack_type="MULTIPACK")
    add_pack_member(pack1["id"], sku1["id"], 1)
    add_pack_member(pack1["id"], sku2["id"], 2)
    add_pack_member(pack2["id"], sku1["id"], 3)

    return {
        "sku1": sku1,
        "sku2": sku2,
        "lot1": lot1,
        "lot2": lot2,
        "lot3": lot3,
        "run": run,
        "pack1": pack1,
        "pack2": pack2,
    }


def test_the_nested_lot_read_answers_only_for_the_addressed_sku():
    """SKU 1 has manufactured two lots and SKU 2 one, and neither read leaks the
    other's traveller.

    PRD §2.4: "Child rows record their parent's identifier: a pack member line
    carries `pack_id`, a claim replacement line carries `claim_id`, a production lot
    carries `sku_id`, a heat-treat campaign carries both `lot_id` and `furnace_id`, a
    test run carries `lot_id` and optionally `chamber_id`, a counterfeit report
    carries `sku_id`, and a warranty claim carries `claimant_id`, `sku_id` and
    `program_id` at once."

    Design: Corner/endpoints/scoped_collection_reads_return_only_their_own_children
    """
    ctx = _two_skus_with_lots_packs_and_one_run()

    first_rows, first_meta = validate_paginated(
        api_client.list_sku_production_lots(ctx["sku1"]["id"], PP, params={"limit": 50, "offset": 0})
    )
    assert first_meta["total_count"] == 2
    assert {row["lot_code"] for row in first_rows} == {"LOT-1A", "LOT-1B"}
    _assert_envelope(first_meta)

    second_rows, second_meta = validate_paginated(
        api_client.list_sku_production_lots(ctx["sku2"]["id"], PP, params={"limit": 50, "offset": 0})
    )
    assert second_meta["total_count"] == 1
    assert second_rows[0]["lot_code"] == "LOT-2A"


def test_a_skus_pack_memberships_span_every_pack_that_lists_it():
    """SKU 1 is a line in both packs while SKU 2 is a line in one, so the membership
    read is keyed on the member rather than on the hero SKU.

    PRD §4: "List every PackMember line that packs this SKU, across all pack
    configurations"

    Design: Corner/endpoints/scoped_collection_reads_return_only_their_own_children
    """
    ctx = _two_skus_with_lots_packs_and_one_run()

    _, first_meta = validate_paginated(
        api_client.list_sku_pack_memberships(
            ctx["sku1"]["id"], CM, params={"limit": 50, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 2
    _assert_envelope(first_meta)

    _, second_meta = validate_paginated(
        api_client.list_sku_pack_memberships(
            ctx["sku2"]["id"], CM, params={"limit": 50, "offset": 0}
        )
    )
    assert second_meta["total_count"] == 1


def test_the_nested_run_read_is_scoped_and_composes_with_its_own_filters():
    """The hardness run belongs to the first lot only, and the sibling lot answers
    with an empty page rather than borrowing it.

    PRD §2.3: "Test runs can be filtered by `chamber_id`, `test_type`, `status` or
    the boolean `mandatory`; heat-treat campaigns by `lot_id`, `furnace_id` or
    `status`; furnaces and chambers by `status` where they carry one."

    Design: Corner/endpoints/scoped_collection_reads_return_only_their_own_children
    """
    ctx = _two_skus_with_lots_packs_and_one_run()

    rows, meta = validate_paginated(
        api_client.list_lot_test_runs(
            ctx["lot1"]["id"], QE, params={"test_type": "HARDNESS", "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["run"]["id"]

    empty, empty_meta = validate_paginated(
        api_client.list_lot_test_runs(ctx["lot2"]["id"], QE, params={"limit": 50, "offset": 0})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


def test_the_member_collection_agrees_with_the_packs_own_member_counter():
    """The display carton lists two SKUs and the multipack one, and each pack's
    denormalised counter matches its collection.

    PRD §3.6: "Adding a line refreshes `member_subtotal_cents` and
    `distinct_member_count` on the pack and increments the pack's `version`."

    Design: Corner/endpoints/scoped_collection_reads_return_only_their_own_children
    """
    ctx = _two_skus_with_lots_packs_and_one_run()

    _, meta = validate_paginated(
        api_client.list_pack_members(ctx["pack1"]["id"], CM, params={"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert read_pack(ctx["pack1"]["id"])["distinct_member_count"] == 2
    _assert_envelope(meta)

    assert read_pack(ctx["pack2"]["id"])["distinct_member_count"] == 1


# ---------------------------------------------------------------------------
# Top-level collections: declared filters, empty pages, pagination envelope
# ---------------------------------------------------------------------------


def _a_populated_shop():
    """One row of every operational kind: two SKUs, a furnace, a cabinet, two lots
    on the first SKU with the first one heat-treated and under test, a draft display
    carton, a funded programme, a consumer claimant and one open sighting."""
    sku1 = create_sku()
    sku2 = create_sku(**PROFESSIONAL_SOCKET)
    furnace = _a_dual_alloy_furnace()
    chamber = create_chamber(coupon_capacity=24)
    lot1 = create_lot(sku1["id"], lot_code="LOT-A", unit_count=500, specimen_pool_total=20)
    lot2 = create_lot(sku1["id"], lot_code="LOT-B", unit_count=200, specimen_pool_total=20)

    campaign = schedule_campaign(lot1["id"], furnace["id"], charge_kg=800)
    complete_campaign(campaign["id"])
    advance_lot(lot1["id"], "HEAT_TREATED")
    run = schedule_test_run(lot1["id"], "HARDNESS", 2, HARDNESS_SLOT)

    pack = create_pack(sku1["id"], pack_code="PK-1", pack_type="RETAIL_DISPLAY")
    program = create_program()
    claimant = create_claimant()
    report = create_report(
        sku1["id"], seller_handle="s-1", evidence_grade="WEAK", unit_estimate=10
    )

    return {
        "sku1": sku1,
        "sku2": sku2,
        "furnace": furnace,
        "chamber": chamber,
        "lot1": lot1,
        "lot2": lot2,
        "campaign": campaign,
        "run": run,
        "pack": pack,
        "program": program,
        "claimant": claimant,
        "report": report,
    }


def test_the_three_lot_status_filters_compose_and_an_unmatched_value_empties_the_page():
    """Scheduling the run left the first lot heat-treated, under test and still in
    process, and asking for an assembled lot returns an empty page rather than the
    population.

    PRD §2.3: "Production lots can be filtered by `process_status`, `cert_status` or
    `disposition`, independently of one another."

    Design: Corner/endpoints/every_top_level_collection_read_is_paginated_and_filterable
    """
    _a_populated_shop()

    rows, meta = validate_paginated(
        api_client.list_production_lots(
            PP,
            params={
                "process_status": "HEAT_TREATED",
                "cert_status": "IN_TEST",
                "disposition": "IN_PROCESS",
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["lot_code"] == "LOT-A"

    empty, empty_meta = validate_paginated(
        api_client.list_production_lots(PP, params={"process_status": "ASSEMBLED"})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


def test_paging_past_the_end_is_an_empty_page_that_still_reports_the_population():
    """Two lots exist, so a window opening at offset two is legitimately empty while
    the envelope still counts both rows.

    PRD §2.3: "`offset` is the number of rows skipped; it defaults to 0 and may not
    be negative."

    Design: Corner/endpoints/every_top_level_collection_read_is_paginated_and_filterable
    """
    _a_populated_shop()

    rows, meta = validate_paginated(
        api_client.list_production_lots(PP, params={"limit": 1, "offset": 2})
    )

    assert rows == []
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 2
    assert meta["has_more"] is False


def test_the_pagination_defaults_are_ten_rows_from_the_very_top():
    """With the parameters omitted the envelope echoes the documented defaults.

    PRD §2.3: "`limit` is the maximum number of rows returned; it defaults to 10, may
    not be smaller than 1 and may not be larger than 100."

    Design: Corner/endpoints/every_top_level_collection_read_is_paginated_and_filterable
    """
    _a_populated_shop()

    rows, meta = validate_paginated(api_client.list_tool_skus(CM))

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2


def test_the_shop_floor_collections_answer_their_own_declared_filters():
    """A hardness run holds no cabinet, the furnace is still available, and the
    completed campaign is reachable from both of its parents.

    PRD §2.3: "Beyond pagination, list endpoints accept optional equality filters
    drawn from the attributes of the resource being listed."

    Design: Corner/endpoints/every_top_level_collection_read_is_paginated_and_filterable
    """
    ctx = _a_populated_shop()

    _, chambered = validate_paginated(
        api_client.list_test_runs(
            QE,
            params={
                "chamber_id": ctx["chamber"]["id"],
                "test_type": "HARDNESS",
                "status": "SCHEDULED",
                "mandatory": True,
            },
        )
    )
    assert chambered["total_count"] == 0

    runs, run_meta = validate_paginated(
        api_client.list_test_runs(QE, params={"test_type": "HARDNESS", "mandatory": True})
    )
    assert run_meta["total_count"] == 1
    assert runs[0]["id"] == ctx["run"]["id"]

    furnaces, _ = validate_paginated(
        api_client.list_heat_treat_furnaces(PP, params={"status": "AVAILABLE"})
    )
    assert furnaces[0]["furnace_code"] == "FCE-1"

    cabinets, _ = validate_paginated(
        api_client.list_salt_spray_chambers(QE, params={"limit": 50, "offset": 0})
    )
    assert cabinets[0]["chamber_code"] == "SSC-1"

    campaigns, campaign_meta = validate_paginated(
        api_client.list_furnace_campaigns(
            PP,
            params={
                "lot_id": ctx["lot1"]["id"],
                "furnace_id": ctx["furnace"]["id"],
                "status": "COMPLETED",
            },
        )
    )
    assert campaign_meta["total_count"] == 1
    assert campaigns[0]["soak_minutes"] == 120

    _, sibling = validate_paginated(
        api_client.list_furnace_campaigns(PP, params={"lot_id": ctx["lot2"]["id"]})
    )
    assert sibling["total_count"] == 0


def test_the_commercial_collections_answer_their_own_declared_filters():
    """Packs, programmes, claimants and sightings each narrow on their declared
    attributes, and a filter matching nothing never falls back to the full set.

    PRD §2.3: "Packaging configurations accept `primary_sku_id`, `pack_type` and
    `status`. Claimants accept `status` and `claimant_type`. Warranty claims accept
    `claimant_id`, `sku_id`, `program_id` and `status`, which is what lets a claim be
    reached from any of its three parents. Counterfeit reports accept `status` and
    `evidence_grade`."

    Design: Corner/endpoints/every_top_level_collection_read_is_paginated_and_filterable
    """
    ctx = _a_populated_shop()

    packs, pack_meta = validate_paginated(
        api_client.list_pack_configurations(
            CM,
            params={
                "primary_sku_id": ctx["sku1"]["id"],
                "pack_type": "RETAIL_DISPLAY",
                "status": "DRAFT",
            },
        )
    )
    assert pack_meta["total_count"] == 1
    assert packs[0]["pack_code"] == "PK-1"

    programs, _ = validate_paginated(
        api_client.list_warranty_programs(WA, params={"limit": 50, "offset": 0})
    )
    assert programs[0]["program_code"] == "LIFETIME-1"

    claimants, claimant_meta = validate_paginated(
        api_client.list_claimants(WA, params={"status": "ACTIVE", "claimant_type": "CONSUMER"})
    )
    assert claimant_meta["total_count"] == 1
    assert claimants[0]["email"] == "c1@example.com"

    _, pro_meta = validate_paginated(
        api_client.list_claimants(WA, params={"claimant_type": "PRO_ACCOUNT"})
    )
    assert pro_meta["total_count"] == 0

    reports, report_meta = validate_paginated(
        api_client.list_counterfeit_reports(BP, params={"status": "OPEN", "evidence_grade": "WEAK"})
    )
    assert report_meta["total_count"] == 1
    assert reports[0]["seller_handle"] == "s-1"

    _, strong_meta = validate_paginated(
        api_client.list_counterfeit_reports(BP, params={"evidence_grade": "STRONG"})
    )
    assert strong_meta["total_count"] == 0

    scoped, scoped_meta = validate_paginated(
        api_client.list_sku_counterfeit_reports(ctx["sku1"]["id"], BP, params={"status": "OPEN"})
    )
    assert scoped_meta["total_count"] == 1
    assert scoped[0]["id"] == ctx["report"]["id"]

    _, clean_meta = validate_paginated(
        api_client.list_sku_counterfeit_reports(
            ctx["sku2"]["id"], BP, params={"limit": 50, "offset": 0}
        )
    )
    assert clean_meta["total_count"] == 0
