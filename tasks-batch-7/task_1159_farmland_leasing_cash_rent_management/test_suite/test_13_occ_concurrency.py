"""Optimistic concurrency control: the three versioned write operations
reject callers whose observed parent version has gone stale (PRD §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_version_incremented,
    create_settlement_payload,
    get_bid,
    get_lease,
    get_settlement,
    make_tenant_headers,
    setup_active_lease,
    setup_bid,
    setup_field,
    setup_landlord,
    setup_offering,
    setup_tenant,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


def test_lease_amend_stale_version_rejected(api):
    """PRD §2.7: "Amending a lease (`PATCH /leases/{leaseId}`) requires the request to carry `expected_lease_version`, holding the lease `version` the client last observed."
    PRD §2.7: "In all three cases, if the supplied value does not match the parent entity's current `version` — because another write has advanced that version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "Every accepted amendment increments the lease's `version` by one."

    Design: Corner/cross_cutting_layers/lease_amend_stale_version_rejected
    """
    ctx = setup_active_lease("CASH")
    observed = get_lease(ctx["lease"]["id"])["version"]

    amended = validate_success(
        api.amend_lease(
            ctx["lease"]["id"],
            {"expected_lease_version": observed, "base_rent_cents_per_acre": 25500},
            MGR,
        )
    )
    assert_version_incremented(amended["version"], observed)
    assert amended["base_rent_cents_per_acre"] == 25500

    stale = api.amend_lease(
        ctx["lease"]["id"],
        {"expected_lease_version": observed, "base_rent_cents_per_acre": 26000},
        MGR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert get_lease(ctx["lease"]["id"])["base_rent_cents_per_acre"] == 25500, (
        "the losing write is discarded"
    )


def test_settlement_create_stale_lease_version_rejected(api):
    """PRD §2.7: "Creating a harvest settlement (`POST /settlements`) likewise requires `expected_lease_version`, because a settlement is written against a specific observed state of its lease."
    PRD §2.7: "if the supplied value does not match the parent entity's current `version` — because another write has advanced that version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "Creation increments the lease's `version` by one."

    Design: Corner/cross_cutting_layers/settlement_create_stale_lease_version_rejected
    """
    ctx = setup_active_lease("FLEX")
    observed = get_lease(ctx["lease"]["id"])["version"]

    first = validate_success(
        api.create_settlement(
            create_settlement_payload(
                ctx["lease"]["id"],
                expected_lease_version=observed,
                price_source="ESTIMATED",
                yield_bu_per_acre=200,
                harvest_price_cents_per_bu=450,
            ),
            MGR,
        ),
        201,
    )
    assert first["status"] == "PROVISIONAL"
    assert_version_incremented(get_lease(ctx["lease"]["id"])["version"], observed)

    # The same observed version is now stale: the first create advanced it.
    stale = api.create_settlement(
        create_settlement_payload(
            ctx["lease"]["id"],
            expected_lease_version=observed,
            price_source="ESTIMATED",
            yield_bu_per_acre=195,
            harvest_price_cents_per_bu=455,
        ),
        MGR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert get_settlement(first["id"])["status"] == "PROVISIONAL", (
        "the rejected create supersedes nothing"
    )


def test_bid_revise_stale_version_rejected(api):
    """PRD §2.7: "Revising a bid (`PATCH /bids/{bidId}`) requires `expected_bid_version`, the bid `version` the client last observed."
    PRD §2.7: "if the supplied value does not match the parent entity's current `version` — because another write has advanced that version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Each accepted revision increments the bid's `version` and recomputes the evaluation scores of all eligible bids on the offering."

    Design: Corner/cross_cutting_layers/bid_revise_stale_version_rejected
    """
    landlord = setup_landlord(name="L OCC3", contact_email="lo3@x.com")
    tenant = setup_tenant(name="T OCC3", years_experience=5)
    field = setup_field(landlord["id"], name="FOCC3")
    offering = setup_offering(field["id"])
    bid = setup_bid(offering["id"], tenant["id"], "CASH")
    observed = bid["version"]
    tenant_headers = make_tenant_headers(tenant["id"])

    revised = validate_success(
        api.revise_bid(
            bid["id"],
            {
                "expected_bid_version": observed,
                "cash_bid_per_acre_cents": 25500,
                "cash_equivalent_bid_cents_per_acre": 25500,
            },
            tenant_headers,
        )
    )
    assert_version_incremented(revised["version"], observed)
    assert revised["cash_equivalent_bid_cents_per_acre"] == 25500

    stale = api.revise_bid(
        bid["id"],
        {
            "expected_bid_version": observed,
            "cash_bid_per_acre_cents": 26000,
            "cash_equivalent_bid_cents_per_acre": 26000,
        },
        tenant_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    current = get_bid(bid["id"])
    assert current["cash_equivalent_bid_cents_per_acre"] == 25500, (
        "the replayed stale revision changes nothing"
    )
