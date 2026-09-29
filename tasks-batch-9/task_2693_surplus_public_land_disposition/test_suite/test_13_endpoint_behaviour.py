"""Endpoint mechanics: partial update, a scoped sub-collection, and branching acts.

A fund PATCH rewrites one field and persists it. A parcel's title-item route is
scoped to its parent and filterable within that scope. Publishing is the sole gate
on bid eligibility. And two acts branch on a body field: authorizing a negotiated
sale without an agreed offer, and creating an exchange without its agency leg.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success


def _two_ranked_funds(api):
    """A general fund at rank 1 taking 0.6 and a park fund at rank 2 taking 0.4."""
    general = validate_success(
        api.create_fund(
            f.fund_payload(
                priority_rank=1,
                allocation_pct=0.6,
                name="General Fund",
                fund_code="F-GEN",
            ),
            fx.FINANCE_HEADERS,
        ),
        201,
    )
    park = validate_success(
        api.create_fund(
            f.fund_payload(
                priority_rank=2,
                allocation_pct=0.4,
                name="Park Acquisition Fund",
                fund_code="F-PARK",
            ),
            fx.FINANCE_HEADERS,
        ),
        201,
    )
    return general, park


def _exchange_authorized_declaration(api):
    """A declaration authorized for an exchange on an express board finding.

    The neighbouring district that was noticed declined, so the statutory window
    closes with no preference offer standing and the board is free to fix the
    exchange authority. The findings are supplied because an exchange rests on
    them.
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_adopted_declaration(api, ctx, resolution_number="RES-2026-255")
    ctx["environmental_review"] = fx.make_exempt_review(api, ctx["declaration"]["id"])
    recipient = fx.make_transit_agency(api)
    notices = fx.issue_notices(api, ctx["declaration"]["id"], [recipient["id"]], 60)
    fx.decline_notice(api, notices[0]["id"], recipient["id"])
    fx.close_preference_window(api, ctx["declaration"]["id"])
    ctx["declaration"] = fx.authorize_disposition(
        api,
        ctx["declaration"]["id"],
        "EXCHANGE",
        authority_findings=(
            "The swap secures a corporation yard of equal value adjoining the depot"
        ),
    )
    ctx["declaration_version"] = fx.declaration_version(api, ctx["declaration"]["id"])
    return ctx


def test_01_patching_one_fund_field_rewrites_it_and_leaves_the_rest_alone(api):
    """A single-field PATCH persists, bumps the version, and spares its neighbour.

    "Treasury may later adjust `allocation_pct` and `fixed_reserve_cents`, which
    increments the fund's `version` by 1; the shares must still sum to exactly 1
    at the moment proceeds are posted, and §3.10 states what happens when they do
    not." "A new fund starts with `balance_cents`, `lifetime_credits_cents` and
    `lifetime_debits_cents` all zero."

    Design: Corner/endpoints/patch_fund_allocation_pct_updates_configuration
    """
    general, park = _two_ranked_funds(api)
    assert general["version"] == 1, (
        f"the created fund carries the first version, got {general['version']}"
    )

    patched = validate_success(
        api.patch_fund(general["id"], {"allocation_pct": 0.55}, fx.FINANCE_HEADERS), 200
    )
    assert patched["allocation_pct"] == 0.55, (
        f"the supplied share is written, got {patched['allocation_pct']}"
    )
    assert patched["fund_code"] == "F-GEN", (
        f"the accounting code is left alone, got {patched['fund_code']!r}"
    )
    assert patched["priority_rank"] == 1, (
        f"as is its place in the waterfall, got {patched['priority_rank']}"
    )
    assert patched["fixed_reserve_cents"] == 0, (
        "and the reserve keeps its create-time default, got "
        f"{patched['fixed_reserve_cents']}"
    )
    assert patched["balance_cents"] == 0, (
        f"no money has moved, got {patched['balance_cents']}"
    )
    assert patched["lifetime_credits_cents"] == 0, (
        f"nothing has been credited, got {patched['lifetime_credits_cents']}"
    )
    assert patched["lifetime_debits_cents"] == 0, (
        f"nor debited, got {patched['lifetime_debits_cents']}"
    )
    assert patched["version"] == 2, (
        f"and the adjustment raises the version by one, got {patched['version']}"
    )

    reread = get_success_data(api.get_fund(general["id"], fx.FINANCE_HEADERS))
    assert reread["allocation_pct"] == 0.55, (
        "a fresh read proves the write persisted rather than being echoed, got "
        f"{reread['allocation_pct']}"
    )
    assert reread["version"] == 2, (
        f"at the same version, got {reread['version']}"
    )

    untouched = get_success_data(api.get_fund(park["id"], fx.FINANCE_HEADERS))
    assert untouched["allocation_pct"] == 0.4, (
        f"the other fund's share is not disturbed, got {untouched['allocation_pct']}"
    )
    assert untouched["version"] == 1, (
        f"and its version stands where it was, got {untouched['version']}"
    )


def test_02_the_title_item_route_is_scoped_to_its_parcel_and_filterable(api):
    """Three items on one parcel, one on another, and a status filter inside the scope.

    "Curative items are listed per parcel, filterable by `status`, and each can be
    read on its own." "The item is created `OPEN`, the parcel's
    `open_title_item_count` rises by 1, and `disposition_ready` recomputes to
    false."

    Design: Corner/endpoints/get_parcel_title_items_filtered_by_status_returns_subresource_rows
    """
    agency = fx.make_agency(api)
    parcel_a = fx.make_parcel(api, agency["id"], apn="APN-2693-151")
    parcel_b = fx.make_parcel(
        api,
        agency["id"],
        apn="APN-2693-152",
        address="44 Depot Lane",
        acreage=1.4,
        zoning_code="C-2",
        book_value_cents=30000000,
    )

    lien = fx.open_title_item(
        api,
        parcel_a["id"],
        item_type="LIEN",
        description="Recorded mechanics lien from 2019 sidewalk work",
        cure_cost_estimate_cents=400000,
    )
    encroachment = fx.open_title_item(
        api,
        parcel_a["id"],
        item_type="ENCROACHMENT",
        description="Neighboring loading dock encroaches 3 feet",
        cure_cost_estimate_cents=900000,
    )
    gap = fx.open_title_item(
        api,
        parcel_a["id"],
        item_type="BOUNDARY_GAP",
        description="Six-inch gap along the north boundary line",
        cure_cost_estimate_cents=150000,
    )
    lease = fx.open_title_item(
        api,
        parcel_b["id"],
        item_type="UNRECORDED_LEASE",
        description="Month-to-month storage lease never recorded",
        cure_cost_estimate_cents=50000,
    )
    fx.cure_title_item(api, lien["id"], 250000)
    fx.waive_title_item(api, encroachment["id"])

    rows, meta = validate_paginated(
        api.list_parcel_title_items(
            parcel_a["id"], fx.OFFICER_HEADERS, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3, (
        f"the route returns only its own parcel's items, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"and all three fit in one page, got {meta['has_more']!r}"
    )
    for row in rows:
        assert row["parcel_id"] == parcel_a["id"], (
            f"every row belongs to the addressed parcel, got {row['parcel_id']!r}"
        )
    assert lease["id"] not in [row["id"] for row in rows], (
        "and the other parcel's item never appears under this route"
    )

    open_rows, open_meta = validate_paginated(
        api.list_parcel_title_items(
            parcel_a["id"],
            fx.OFFICER_HEADERS,
            {"status": "OPEN", "limit": 10, "offset": 0},
        )
    )
    assert open_meta["total_count"] == 1, (
        "the status filter narrows the same scoped route, got "
        f"{open_meta['total_count']}"
    )
    assert open_rows[0]["id"] == gap["id"], (
        "and the survivor is the one defect never resolved"
    )

    reread_a = get_success_data(api.get_parcel(parcel_a["id"], fx.OFFICER_HEADERS))
    assert reread_a["open_title_item_count"] == 1, (
        f"one defect is still open on the first parcel, got {reread_a['open_title_item_count']}"
    )
    reread_b = get_success_data(api.get_parcel(parcel_b["id"], fx.OFFICER_HEADERS))
    assert reread_b["open_title_item_count"] == 1, (
        "and the second parcel keeps its own count, got "
        f"{reread_b['open_title_item_count']}"
    )


def test_03_publishing_is_the_only_gate_between_a_draft_offering_and_a_bid(api):
    """The identical tender fails before publication and succeeds after it.

    "Publishing the offering opens it to bids." "On success the offering moves
    `DRAFT → OPEN`. Nothing else changes; in particular publishing does not
    re-derive the frozen prices."

    Design: Corner/endpoints/publish_offering_action_endpoint_opens_the_bidding_window
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_published_offering(api, ctx, publish=False)
    draft = ctx["offering"]
    assert draft["status"] == "DRAFT", (
        f"the offering is drafted but not yet open, got {draft['status']!r}"
    )
    bidder = fx.make_funded_bidder(api, 10000000)
    tender = f.bid_payload(amount_cents=108000000, deposit_amount_cents=5000000)

    early = api.submit_bid(draft["id"], tender, fx.make_bidder_headers(bidder["id"]))
    validate_error(early, ApiErrorId.ERR_INVALID_OFFERING_STATE.value, 409)

    published = validate_success(
        api.publish_offering(draft["id"], fx.OFFICER_HEADERS), 200
    )
    assert published["status"] == "OPEN", (
        f"publication opens the window, got {published['status']!r}"
    )
    assert published["minimum_price_cents"] == draft["minimum_price_cents"] == 100000000, (
        "the minimum frozen at create is not re-derived: "
        f"{published['minimum_price_cents']} against {draft['minimum_price_cents']}"
    )
    assert (
        published["required_deposit_cents"] == draft["required_deposit_cents"] == 5000000
    ), (
        "and neither is the deposit requirement: "
        f"{published['required_deposit_cents']} against "
        f"{draft['required_deposit_cents']}"
    )

    accepted = validate_success(
        api.submit_bid(draft["id"], tender, fx.make_bidder_headers(bidder["id"])), 201
    )
    assert accepted["qualification_status"] == "SUBMITTED", (
        "the very same payload is now received, got "
        f"{accepted['qualification_status']!r}"
    )
    assert accepted["deposit_status"] == "HELD", (
        f"with its deposit held, got {accepted['deposit_status']!r}"
    )

    reread = get_success_data(api.get_bidder(bidder["id"], fx.FINANCE_HEADERS))
    assert reread["available_funds_cents"] == 5000000, (
        "10,000,000 credited less the 5,000,000 deposit, got "
        f"{reread['available_funds_cents']}"
    )
    assert reread["escrow_held_cents"] == 5000000, (
        f"which now sits in escrow, got {reread['escrow_held_cents']}"
    )

    _, meta = validate_paginated(
        api.list_bids(fx.OFFICER_HEADERS, {"offering_id": draft["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"and exactly one bid stands on the offering, got {meta['total_count']}"
    )


def test_04_authorizing_a_negotiated_sale_with_no_agreed_offer_is_refused(api):
    """The same gate on the same declaration turns on the disposition asked for.

    "Fourth, a `NEGOTIATED_SALE` requires a preference offer on the declaration
    whose `negotiation_status` is `AGREED`, and without one the request fails with
    `ERR_PREFERENCE_UNRESOLVED` (HTTP 422)."

    Design: Corner/endpoints/authorize_disposition_negotiated_sale_without_agreed_offer_is_rejected
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_adopted_declaration(api, ctx, resolution_number="RES-2026-254")
    fx.make_exempt_review(api, ctx["declaration"]["id"])
    recipient = fx.make_transit_agency(api)
    notices = fx.issue_notices(api, ctx["declaration"]["id"], [recipient["id"]], 60)
    fx.decline_notice(api, notices[0]["id"], recipient["id"])
    closed = fx.close_preference_window(api, ctx["declaration"]["id"])
    assert closed["status"] == "PREFERENCE_CLOSED", (
        f"the statutory window is shut, got {closed['status']!r}"
    )

    refused = api.authorize_disposition(
        ctx["declaration"]["id"],
        f.authorize_payload("NEGOTIATED_SALE"),
        fx.CLERK_AUTHORIZE_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_PREFERENCE_UNRESOLVED.value, 422)

    stalled = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert stalled["status"] == "PREFERENCE_CLOSED", (
        f"the declaration has not advanced, got {stalled['status']!r}"
    )
    assert stalled["authorized_disposition_type"] is None, (
        "and no authority is recorded, got "
        f"{stalled['authorized_disposition_type']!r}"
    )

    authorized = validate_success(
        api.authorize_disposition(
            ctx["declaration"]["id"],
            f.authorize_payload("COMPETITIVE_SALE"),
            fx.CLERK_AUTHORIZE_HEADERS,
        ),
        200,
    )
    assert authorized["status"] == "OFFERING_AUTHORIZED", (
        "the open-competition route is available on the very next call, got "
        f"{authorized['status']!r}"
    )
    assert authorized["authorized_disposition_type"] == "COMPETITIVE_SALE", (
        "and the authority is stamped, got "
        f"{authorized['authorized_disposition_type']!r}"
    )

    _, meta = validate_paginated(
        api.list_preference_offers(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0, (
        "no preference offer was ever opened on this declaration, got "
        f"{meta['total_count']}"
    )


def test_05_an_exchange_offering_demands_the_agency_leg_and_refuses_a_bidder(api):
    """An optional field becomes mandatory on one branch, and the wrong leg is no better.

    "And finally the counterparty legs are checked: a `NEGOTIATED_SALE` must supply
    exactly one resolvable counterparty leg, and where the declaration reached
    `OFFERING_AUTHORIZED` from `NEGOTIATION_AGREED` the supplied
    `counterparty_agency_id` must equal the `offeror_agency_id` of the `AGREED`
    preference offer — no leg, both legs, or the wrong agency is
    `ERR_NEGOTIATED_BUYER_REQUIRED` (HTTP 422); an `EXCHANGE` must supply
    `counterparty_agency_id` and leave `counterparty_bidder_id` empty, and anything
    else is `ERR_EXCHANGE_COUNTERPARTY_REQUIRED` (HTTP 422)."

    Design: Corner/endpoints/create_exchange_offering_without_counterparty_agency_is_rejected
    """
    ctx = _exchange_authorized_declaration(api)
    assert ctx["declaration"]["authorized_disposition_type"] == "EXCHANGE", (
        "the board fixed the exchange authority, got "
        f"{ctx['declaration']['authorized_disposition_type']!r}"
    )
    swap_agency = fx.make_agency(
        api,
        name="Riverbend County Public Works",
        agency_type="COUNTY",
        contact_email="realty@riverbendcounty.gov",
    )
    wrong_leg_bidder = fx.make_bidder(api)
    token = ctx["declaration_version"]

    def _create(**legs):
        return api.create_offering(
            f.offering_payload(
                ctx["declaration"]["id"],
                token,
                offering_type="EXCHANGE",
                **legs,
            ),
            fx.OFFICER_HEADERS,
        )

    no_leg = _create()
    validate_error(no_leg, ApiErrorId.ERR_EXCHANGE_COUNTERPARTY_REQUIRED.value, 422)

    bidder_leg = _create(counterparty_bidder_id=wrong_leg_bidder["id"])
    validate_error(bidder_leg, ApiErrorId.ERR_EXCHANGE_COUNTERPARTY_REQUIRED.value, 422)

    created = validate_success(_create(counterparty_agency_id=swap_agency["id"]), 201)
    assert created["offering_type"] == "EXCHANGE", (
        "the replayed token still works because the refusals spent none of it, got "
        f"{created['offering_type']!r}"
    )
    assert created["counterparty_agency_id"] == swap_agency["id"], (
        f"the agency leg is recorded, got {created['counterparty_agency_id']!r}"
    )
    assert created["counterparty_bidder_id"] is None, (
        f"and the bidder leg is left empty, got {created['counterparty_bidder_id']!r}"
    )
    assert created["minimum_price_cents"] == 100000000, (
        "with no agreed affordable-housing offer the exchange is priced at the "
        f"appraised value, got {created['minimum_price_cents']}"
    )
    assert created["minimum_price_variant"] == "MARKET_FLOOR", (
        f"on the market-floor variant, got {created['minimum_price_variant']!r}"
    )

    _, meta = validate_paginated(
        api.list_offerings(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"and only the accepted create left a row behind, got {meta['total_count']}"
    )
