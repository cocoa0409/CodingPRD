"""Role authorization, entity-backed ownership, and optimistic concurrency.

Covers PRD §2.1 (roles), §2.6 (ownership before state), §2.7 (the four
OCC-guarded writes), and §4 (per-endpoint role lists).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_tonnage,
    create_buyer,
    create_delivery_load,
    create_draft_quote,
    get_lot,
    issue_quote,
    make_buyer_headers,
    make_grower_headers,
    make_tech_headers,
    post_spoilage_event,
    setup_accepted_contract,
    setup_certified_lot,
    setup_lot,
    setup_pricing_bed,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import create_storage_site

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# Corner/rbac / role-list violations
# ===========================================================================

def test_buyer_cannot_create_bale_lot(api):
    """PRD §4: POST /api/bale-lots is authorized for BrokerOps and
    PlatformAdmin only. PRD §2.1: "A request that authenticates successfully
    but targets an operation outside that role's authorized list is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_create_bale_lot
    """
    buyer = create_buyer(name="Buyer AI")
    resp = api_client.create_bale_lot(
        {
            "cutting_id": "00000000-0000-4000-8000-0000000000dd",
            "storage_site_id": "00000000-0000-4000-8000-0000000000de",
            "bale_type": "ROUND", "bale_count": 10, "harvested_tonnage": 5.0,
            "harvested_date": "2026-08-01",
        },
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_grower_cannot_post_market_index(api):
    """PRD §4: POST /api/market-indices is PlatformAdmin-only. PRD §2.1: "A
    request that authenticates successfully but targets an operation outside
    that role's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/grower_cannot_post_market_index
    """
    grower = validate_success(api_client.create_grower(
        {"name": "Grower AH", "region_code": "OR-WILLAMETTE"}, ADMIN,
    ), expected_status=201)
    resp = api_client.create_market_index(
        {
            "region_code": "OR-WILLAMETTE", "forage_type": "ALFALFA",
            "effective_date": "2026-05-01", "price_per_ton_cents": 20000,
        },
        make_grower_headers(grower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_lab_technician_cannot_create_delivery_load(api):
    """PRD §4: POST /api/delivery-loads is authorized for BrokerOps and
    PlatformAdmin only. PRD §2.1: "A request that authenticates successfully
    but targets an operation outside that role's authorized list is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/lab_technician_cannot_create_delivery_load
    """
    resp = api_client.create_delivery_load(
        {
            "carrier_name": "CARRIER-X", "capacity_tons": 25.0,
            "planned_ship_date": "2026-08-07",
        },
        make_tech_headers("tech-9"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_platform_admin_override_brokerops_surface(api):
    """PRD §2.1: "`PlatformAdmin` is the superset administrator". PRD §4
    lists PlatformAdmin on POST /api/delivery-loads; PRD §3.7: "A new load is
    `PLANNED` on the logistics dimension and `OPEN` on the settlement
    dimension".

    Design: Corner/rbac/platform_admin_override_brokerops_surface
    """
    load = validate_success(api_client.create_delivery_load(
        {
            "carrier_name": "CARRIER-ADMIN", "capacity_tons": 20.0,
            "planned_ship_date": "2026-08-07",
        },
        ADMIN,
    ), expected_status=201)
    assert load["logistics_status"] == "PLANNED"
    assert load["settlement_status"] == "OPEN"


# ===========================================================================
# Corner/rbac / quote_accept_non_owner_forbidden
# ===========================================================================

def test_quote_accept_non_owner_forbidden(api):
    """PRD §3.5: "ownership requires the acting buyer to be the quote owner
    (`ERR_FORBIDDEN_OWNERSHIP`)". PRD §2.1: "ownership checks on any resource
    that references a `Buyer` compare the resource's `buyer_id` to
    `X-User-ID`, and a mismatch is likewise rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Buyer B carrying the quote's current version still cannot accept Buyer
    A's quote; the quote stays ISSUED.

    Design: Corner/rbac/quote_accept_non_owner_forbidden
    """
    setup_pricing_bed()
    buyer_a = create_buyer(name="Buyer AJ")
    buyer_b = create_buyer(name="Buyer AK")
    quote = create_draft_quote(buyer_a["id"])
    issued = issue_quote(quote["id"], buyer_a["id"])
    resp = api_client.accept_quote(
        quote["id"], {"expected_quote_version": issued["version"]},
        make_buyer_headers(buyer_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    read = validate_success(api_client.get_quote(quote["id"], ADMIN))
    assert read["status"] == "ISSUED"


# ===========================================================================
# Corner/cross_cutting_layers / OCC stale-version rejections
# ===========================================================================

def test_occ_quote_patch_stale_version_rejected(api):
    """PRD §2.7: "Updating a draft quote's terms: the request must carry
    `expected_quote_version` matching the quote's current `version`. A prior
    update bumps the quote's `version` without leaving `DRAFT`, so a second
    update carrying the earlier version observes identical status yet works
    from stale pricing inputs."

    The first PATCH (tons 8.0) reprices spot to 23000 x 8.0 + 163170 =
    347170 and bumps the version; the second PATCH carrying the original
    version is rejected 412 and changes nothing.

    Design: Corner/cross_cutting_layers/occ_quote_patch_stale_version_rejected
    """
    setup_pricing_bed()
    buyer = create_buyer(credit_limit_cents=5000000)
    quote = create_draft_quote(buyer["id"], quality_tier="PREMIUM", tons=12.0)
    patched = validate_success(api_client.patch_quote(
        quote["id"], {"tons": 8.0, "expected_quote_version": quote["version"]},
        make_buyer_headers(buyer["id"]),
    ))
    assert patched["total_cents"] == 347170
    resp = api_client.patch_quote(
        quote["id"], {"tons": 9.0, "expected_quote_version": quote["version"]},
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    read = validate_success(
        api_client.get_quote(quote["id"], make_buyer_headers(buyer["id"]))
    )
    assert_tonnage(read["tons"], 8.0, "quote tons")
    assert read["status"] == "DRAFT"


def test_occ_quote_accept_stale_version_rejected(api):
    """PRD §2.7: "Accepting an issued quote: the request must carry
    `expected_quote_version` matching the quote's current `version`. The
    quote may have been revised and re-issued since the client read it ... so
    a stale acceptance would contract against pricing the client never saw."

    Accepting with the pre-issue version (issue bumped it) is rejected 412;
    the quote stays ISSUED and no contract is created.

    Design: Corner/cross_cutting_layers/occ_quote_accept_stale_version_rejected
    """
    setup_pricing_bed()
    buyer = create_buyer()
    quote = create_draft_quote(buyer["id"])
    pre_issue_version = quote["version"]
    issue_quote(quote["id"], buyer["id"])
    resp = api_client.accept_quote(
        quote["id"], {"expected_quote_version": pre_issue_version},
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    read = validate_success(
        api_client.get_quote(quote["id"], make_buyer_headers(buyer["id"]))
    )
    assert read["status"] == "ISSUED"
    contracts, meta = validate_paginated(
        api_client.list_contracts(OPS, params={"quote_id": quote["id"]})
    )
    assert contracts == []
    assert get_buyer_credit(buyer["id"]) == 0


def test_occ_allocation_create_stale_version_rejected(api):
    """PRD §2.7: "Creating a load allocation: the request must carry
    `expected_delivery_load_version` matching the target delivery load's
    current `version`. Allocation creation bumps the load's `version` without
    leaving `PLANNED` or `LOADING`, so a sequential second allocation
    carrying the earlier version would succeed on capacity math computed from
    a stale `loaded_tons`."

    The first 5.0t allocation succeeds; a second carrying the load's original
    version is rejected 412, and only 5.0t is loaded.

    Design: Corner/cross_cutting_layers/occ_allocation_create_stale_version_rejected
    """
    deal = setup_accepted_contract(tons=20.0, quality_tier="GOOD",
                                   credit_limit_cents=2000000)
    inventory = setup_certified_lot(rfv=155.0, protein_pct=18.0,
                                    moisture_pct=14.0, lot_tonnage=30.0)
    load = create_delivery_load()
    payload = {
        "delivery_load_id": load["id"],
        "contract_id": deal["contract"]["id"],
        "bale_lot_id": inventory["lot"]["id"],
        "tons": 5.0,
        "expected_delivery_load_version": load["version"],
    }
    validate_success(
        api_client.create_load_allocation(payload, OPS), expected_status=201,
    )
    resp = api_client.create_load_allocation(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    read = validate_success(api_client.get_delivery_load(load["id"], OPS))
    assert_tonnage(read["loaded_tons"], 5.0, "loaded_tons")


def test_occ_lot_transfer_stale_version_rejected(api):
    """PRD §2.7: "Transferring a bale lot to another storage site: the
    request must carry `expected_bale_lot_version` matching the lot's current
    `version`. Spoilage postings and allocations bump the lot's `version`
    while leaving it `ACTIVE`, so a stale transfer would run the destination
    capacity check against tonnage the client no longer holds."

    A spoilage posting bumps the ACTIVE lot's version; a transfer carrying
    the pre-spoilage version is rejected 412 and the lot stays at its origin
    site.

    Design: Corner/cross_cutting_layers/occ_lot_transfer_stale_version_rejected
    """
    ctx = setup_lot(lot_overrides={"bale_count": 100, "harvested_tonnage": 50.0})
    site2 = create_storage_site(name="Barn AF")
    lot = ctx["lot"]
    post_spoilage_event(lot["id"], 2.0, reason="MOISTURE")
    resp = api_client.transfer_lot(
        lot["id"],
        {"dest_storage_site_id": site2["id"],
         "expected_bale_lot_version": lot["version"]},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    read = get_lot(lot["id"])
    assert read["storage_site_id"] == ctx["site"]["id"]


def get_buyer_credit(buyer_id):
    """Read a buyer's credit_used_cents (PlatformAdmin)."""
    return validate_success(api_client.get_buyer(buyer_id, ADMIN))[
        "credit_used_cents"
    ]
