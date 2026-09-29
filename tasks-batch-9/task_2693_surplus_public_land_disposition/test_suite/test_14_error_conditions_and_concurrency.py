"""Uniqueness, cooling-off, buffers, concurrency tokens and derived readiness.

A parcel number is unique store-wide, and only a live declaration blocks a second
one. The cooling-off period and the recirculation buffer are both inclusive at
their boundary instants. Both concurrency tokens are spent only by the write that
succeeds. And a parcel's readiness is re-derived at every touch.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success


def _failed_competitive_sale(api):
    """A published competitive sale that closed with no bid at all.

    Nobody bid, so at the close instant the offering fails and the four-link
    cascade fires: the declaration becomes unsuccessful, the accepted appraisal is
    superseded and the parcel's valuation goes stale.
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_published_offering(api, ctx)
    fx.set_clock(api, "2026-12-31T00:00:00Z")
    ctx["offering"] = fx.close_bidding(api, ctx["offering"]["id"])
    return ctx


def _circulating_review(api):
    """A negative declaration out for comment over [2026-09-01, 2026-10-01]."""
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["parcel"] = fx.make_parcel(api, ctx["agency"]["id"], apn="APN-2693-164")
    ctx["declaration"] = fx.make_adopted_declaration(
        api, ctx["parcel"]["id"], resolution_number="RES-2026-264"
    )
    ctx["review"] = fx.make_circulating_review(
        api,
        ctx["declaration"]["id"],
        determination_class="NEGATIVE_DECLARATION",
        circulation_start_on="2026-09-01T00:00:00Z",
        circulation_end_on="2026-10-01T00:00:00Z",
    )
    return ctx


def test_01_a_parcel_number_is_unique_across_the_whole_inventory(api):
    """A different custodian does not buy the same assessor number a second time.

    "Natural keys are unique across the whole store: a parcel's `apn`, an
    appraiser's `license_number`, and a fund's `fund_code` and `priority_rank` may
    each be taken by at most one row. An attempt to reuse one is rejected with
    `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/errors/duplicate_parcel_apn_is_rejected
    """
    custodian = fx.make_agency(api)
    other = fx.make_agency(
        api,
        name="Riverbend County Public Works",
        agency_type="COUNTY",
        contact_email="realty@riverbendcounty.gov",
    )
    parcel = fx.make_parcel(api, custodian["id"], apn="APN-2693-161")

    response = api.create_parcel(
        f.parcel_payload(
            other["id"],
            apn="APN-2693-161",
            address="44 Depot Lane",
            acreage=1.4,
            zoning_code="C-2",
            book_value_cents=30000000,
        ),
        fx.OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

    rows, meta = validate_paginated(api.list_parcels(fx.OFFICER_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 1, (
        f"no second parcel row was written, got {meta['total_count']}"
    )
    assert rows[0]["id"] == parcel["id"], "and the survivor is the parcel recorded first"
    assert rows[0]["address"] == "9 Canal Street", (
        f"with its own address intact, got {rows[0]['address']!r}"
    )
    assert rows[0]["custodian_agency_id"] == custodian["id"], (
        "still held by the original custodian, got "
        f"{rows[0]['custodian_agency_id']!r}"
    )
    assert rows[0]["version"] == 1, (
        f"and never touched by the refused create, got {rows[0]['version']}"
    )


def test_02_the_one_live_declaration_rule_releases_once_the_first_is_withdrawn(api):
    """The identical payload is refused and then accepted, deleting nothing.

    "A parcel may also carry only one live declaration at a time — if another
    declaration on the same parcel has a `status` outside `CONVEYED` and
    `WITHDRAWN`, the draft is refused with `ERR_DUPLICATE_ACTIVE_DECLARATION`
    (HTTP 409)."

    Design: Corner/errors/second_active_declaration_on_same_parcel_rejected_then_allowed_after_withdrawal
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], apn="APN-2693-162")
    first = fx.make_declaration(api, parcel["id"])
    assert first["status"] == "DRAFT", (
        f"the first finding is drafted, got {first['status']!r}"
    )

    blocked = api.create_declaration(
        f.declaration_payload(parcel["id"]), fx.OFFICER_HEADERS
    )
    validate_error(blocked, ApiErrorId.ERR_DUPLICATE_ACTIVE_DECLARATION.value, 409)

    reason = "Council directed a fresh finding after the boundary survey"
    withdrawn = validate_success(
        api.withdraw_declaration(
            first["id"],
            f.withdraw_declaration_payload(withdrawn_reason=reason),
            fx.CLERK_AUTHORIZE_HEADERS,
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the first finding is abandoned, got {withdrawn['status']!r}"
    )

    second = validate_success(
        api.create_declaration(f.declaration_payload(parcel["id"]), fx.OFFICER_HEADERS),
        201,
    )
    assert second["status"] == "DRAFT", (
        "the same payload is now admissible, got " f"{second['status']!r}"
    )
    assert second["parcel_id"] == parcel["id"], (
        f"against the very same parcel, got {second['parcel_id']!r}"
    )

    rows, meta = validate_paginated(
        api.list_declarations(
            fx.OFFICER_HEADERS, {"parcel_id": parcel["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        "the withdrawal was not a deletion, so two declarations stand on the "
        f"parcel, got {meta['total_count']}"
    )
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[first["id"]] == "WITHDRAWN", (
        f"the first is withdrawn, got {by_id[first['id']]!r}"
    )
    assert by_id[second["id"]] == "DRAFT", (
        f"and the second is the live one, got {by_id[second['id']]!r}"
    )


def test_03_re_offering_before_the_cooling_off_instant_is_refused(api):
    """The failure instant is too early; the thirtieth day exactly is in time.

    "Then, in this order: every agency to be re-served must still hold
    `notice_registry_status` `REGISTERED`, and a lapsed recipient blocks the whole
    re-offer with `ERR_NOTICE_REGISTRY_LAPSED` (HTTP 422) rather than being
    silently dropped; the cooling-off period must have run, meaning the clock
    stands at or after `reoffer_eligible_at`, with the boundary instant itself
    sufficient and anything earlier refused as `ERR_REOFFER_COOLING_OFF` (HTTP
    409); and the declaration's `reoffer_count` must be strictly below 2, so that a
    parcel may be re-offered at most twice before the disposition must be
    abandoned, with a third attempt refused as `ERR_REOFFER_LIMIT_REACHED` (HTTP
    422)."

    Design: Corner/errors/re_offer_during_cooling_off_is_rejected
    """
    ctx = _failed_competitive_sale(api)
    assert ctx["offering"]["status"] == "FAILED_NO_QUALIFYING_BID", (
        f"nobody bid, so the sale failed, got {ctx['offering']['status']!r}"
    )
    assert ctx["offering"]["qualified_bid_count"] == 0, (
        f"with no qualifying bid to rank, got {ctx['offering']['qualified_bid_count']}"
    )

    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["status"] == "UNSUCCESSFUL", (
        f"the declaration falls to unsuccessful, got {declaration['status']!r}"
    )
    assert declaration["reoffer_eligible_at"] == "2027-01-30T00:00:00.000Z", (
        "and 30 days after the 2026-12-31 failure is 2027-01-30, got "
        f"{declaration['reoffer_eligible_at']!r}"
    )

    early = api.re_offer_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    validate_error(early, ApiErrorId.ERR_REOFFER_COOLING_OFF.value, 409)
    _, first_round_only = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert first_round_only["total_count"] == 1, (
        "the refused re-offer mints no notice, so only the original round stands, "
        f"got {first_round_only['total_count']}"
    )

    fx.set_clock(api, "2027-01-30T00:00:00Z")
    reoffered = validate_success(
        api.re_offer_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS), 200
    )
    assert reoffered["status"] == "NOTICED", (
        "the boundary instant itself is sufficient, got "
        f"{reoffered['status']!r}"
    )
    assert reoffered["notice_issued_at"] == "2027-01-30T00:00:00.000Z", (
        f"and the new round is served at once, got {reoffered['notice_issued_at']!r}"
    )
    assert reoffered["reoffer_count"] == 1, (
        f"the first cycle is spent, got {reoffered['reoffer_count']}"
    )

    rows, meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS,
            {
                "declaration_id": ctx["declaration"]["id"],
                "notice_round": 2,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"one notice is served in the second round, got {meta['total_count']}"
    )
    assert rows[0]["recipient_agency_id"] == ctx["recipient_agency"]["id"], (
        "to the same recipient the first round reached, got "
        f"{rows[0]['recipient_agency_id']!r}"
    )
    assert rows[0]["response_window_days"] == 60, (
        f"the window carries over unchanged, got {rows[0]['response_window_days']}"
    )
    assert rows[0]["response_deadline_at"] == "2027-03-31T00:00:00.000Z", (
        "and 60 days after 2027-01-30 is 2027-03-31, got "
        f"{rows[0]['response_deadline_at']!r}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "SUPERSEDED", (
        "the market contradicted the valuation, got " f"{appraisal['status']!r}"
    )
    assert appraisal["revaluation_required"] is True, (
        f"so a fresh one is required, got {appraisal['revaluation_required']!r}"
    )
    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["valuation_status"] == "STALE", (
        f"the parcel's valuation is stale, got {parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        "and it cannot be offered again until it is revalued, got "
        f"{parcel['disposition_ready']!r}"
    )


def test_04_recirculating_one_day_inside_the_statutory_buffer_is_refused(api):
    """Twenty-nine days is too soon; the thirtieth day itself is allowed.

    "The new window must respect the statutory buffer: its `circulation_start_on`
    must fall no earlier than 30 days after the prior round's `circulation_end_on`,
    and the boundary day itself is allowed, so a start exactly 30 days after the
    prior end is accepted while 29 days after is refused with
    `ERR_RECIRCULATION_BUFFER_VIOLATION` (HTTP 422)."

    Design: Corner/errors/recirculate_environmental_review_within_buffer_is_rejected
    """
    ctx = _circulating_review(api)
    review = ctx["review"]
    assert review["status"] == "CIRCULATING", (
        f"the document is out for comment, got {review['status']!r}"
    )

    reason = "Traffic study revised after the initial circulation closed"
    too_soon = api.recirculate_environmental_review(
        review["id"],
        f.recirculate_payload(
            "2026-10-30T00:00:00Z",
            "2026-12-01T00:00:00Z",
            recirculation_reason=reason,
        ),
        fx.OFFICER_HEADERS,
    )
    validate_error(
        too_soon, ApiErrorId.ERR_RECIRCULATION_BUFFER_VIOLATION.value, 422
    )

    held = get_success_data(
        api.get_environmental_review(review["id"], fx.OFFICER_HEADERS)
    )
    assert held["circulation_round"] == 1, (
        f"the refused restart opens no second round, got {held['circulation_round']}"
    )
    assert held["circulation_start_on"] == "2026-09-01T00:00:00Z", (
        f"the original window keeps its start, got {held['circulation_start_on']!r}"
    )
    assert held["circulation_end_on"] == "2026-10-01T00:00:00Z", (
        f"and its end, got {held['circulation_end_on']!r}"
    )
    assert held["recirculation_reason"] is None, (
        "and no reason is stored for a restart that never happened, got "
        f"{held['recirculation_reason']!r}"
    )

    accepted = validate_success(
        api.recirculate_environmental_review(
            review["id"],
            f.recirculate_payload(
                "2026-10-31T00:00:00Z",
                "2026-12-01T00:00:00Z",
                recirculation_reason=reason,
            ),
            fx.OFFICER_HEADERS,
        ),
        200,
    )
    assert accepted["circulation_round"] == 2, (
        "one day later the buffer is satisfied and the round rises, got "
        f"{accepted['circulation_round']}"
    )
    assert accepted["circulation_start_on"] == "2026-10-31T00:00:00Z", (
        "on exactly the thirtieth day after the prior end, got "
        f"{accepted['circulation_start_on']!r}"
    )
    assert accepted["status"] == "CIRCULATING", (
        "and the review a client reads afterwards is circulating again, got "
        f"{accepted['status']!r}"
    )

    _, meta = validate_paginated(
        api.list_environmental_reviews(
            ctx["declaration"]["id"], fx.OFFICER_HEADERS, {"limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        "recirculation rewrites the one review rather than filing another, got "
        f"{meta['total_count']}"
    )


def test_05_replaying_a_spent_parcel_token_on_an_appraisal_order_is_refused(api):
    """The successful order spends the token; the refusal does not.

    "If it does not equal the parcel's current `version`, the request is rejected
    with `ERR_STALE_PARCEL_VERSION` (HTTP 412)." "Note that the successful create
    itself advances `Parcel.version`, so the token a client just spent is stale for
    every other holder of the same token."

    Design: Corner/cross_cutting_complexity_layers/appraisal_order_with_stale_parcel_version_returns_412
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], apn="APN-2693-181")
    appraiser = fx.make_appraiser(api, license_number="AG-44281")
    assert parcel["version"] == 1, (
        f"a freshly recorded parcel starts at the first version, got {parcel['version']}"
    )

    first = fx.order_appraisal(
        api,
        parcel["id"],
        appraiser["id"],
        engagement_start_on="2026-08-02T00:00:00Z",
        engagement_end_on="2026-08-20T00:00:00Z",
    )
    assert fx.parcel_version(api, parcel["id"]) == 2, (
        "the accepted order advanced the parcel's token, got "
        f"{fx.parcel_version(api, parcel['id'])}"
    )

    def _order_with(token):
        return api.create_appraisal(
            f.appraisal_order_payload(
                parcel["id"],
                appraiser["id"],
                token,
                method="INCOME",
                engagement_start_on="2026-08-05T00:00:00Z",
                engagement_end_on="2026-08-25T00:00:00Z",
            ),
            fx.OFFICER_HEADERS,
        )

    replay = _order_with(parcel["version"])
    validate_error(replay, ApiErrorId.ERR_STALE_PARCEL_VERSION.value, 412)

    unchanged = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert unchanged["version"] == 2, (
        f"the refused write spends no token of its own, got {unchanged['version']}"
    )
    _, one_only = validate_paginated(
        api.list_appraisals(
            fx.OFFICER_HEADERS, {"parcel_id": parcel["id"], "limit": 100}
        )
    )
    assert one_only["total_count"] == 1, (
        f"and books no second engagement, got {one_only['total_count']}"
    )

    second = validate_success(_order_with(unchanged["version"]), 201)
    assert second["status"] == "ORDERED", (
        "the identical payload carrying the re-read token is admissible, got "
        f"{second['status']!r}"
    )
    assert second["id"] != first["id"], "and it is a genuinely new engagement"
    assert fx.parcel_version(api, parcel["id"]) == 3, (
        "which advances the parcel again, got "
        f"{fx.parcel_version(api, parcel['id'])}"
    )
    _, both = validate_paginated(
        api.list_appraisals(
            fx.OFFICER_HEADERS, {"parcel_id": parcel["id"], "limit": 100}
        )
    )
    assert both["total_count"] == 2, (
        f"two engagements now stand on the parcel, got {both['total_count']}"
    )
    reread = get_success_data(api.get_appraiser(appraiser["id"], fx.OFFICER_HEADERS))
    assert reread["active_engagement_count"] == 2, (
        "and the appraiser is carrying both of them, got "
        f"{reread['active_engagement_count']}"
    )


def test_06_replaying_a_spent_declaration_token_on_an_offering_is_refused(api):
    """A lawful second window is stopped by the token alone, not by any state rule.

    "A declaration in `OFFERING_AUTHORIZED` legitimately admits more than one
    offering over its life — re-offerings and adjacent bidding windows are both
    lawful — so a second create observes the same authorized state and would
    succeed on its own terms; the version token is what makes the stale view
    detectable." "A value that does not equal the declaration's current `version`
    is rejected with `ERR_STALE_DECLARATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/offering_create_with_stale_declaration_version_returns_412
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_authorized_declaration(api, ctx)
    token = fx.declaration_version(api, ctx["declaration"]["id"])

    def _offer_over(bid_open_at, bid_close_at, expected_version):
        return api.create_offering(
            f.offering_payload(
                ctx["declaration"]["id"],
                expected_version,
                offering_type="COMPETITIVE_SALE",
                bid_open_at=bid_open_at,
                bid_close_at=bid_close_at,
            ),
            fx.OFFICER_HEADERS,
        )

    validate_success(
        _offer_over("2026-08-01T00:00:00Z", "2026-12-31T00:00:00Z", token), 201
    )

    replay = _offer_over("2027-01-01T00:00:00Z", "2027-06-01T00:00:00Z", token)
    validate_error(replay, ApiErrorId.ERR_STALE_DECLARATION_VERSION.value, 412)

    _, one_only = validate_paginated(
        api.list_offerings(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert one_only["total_count"] == 1, (
        f"the refused create books no second window, got {one_only['total_count']}"
    )

    fresh = fx.declaration_version(api, ctx["declaration"]["id"])
    assert fresh == token + 1, (
        "the first create is what advanced the declaration, got "
        f"{fresh} against {token}"
    )

    second = validate_success(
        _offer_over("2027-01-01T00:00:00Z", "2027-06-01T00:00:00Z", fresh), 201
    )
    assert second["status"] == "DRAFT", (
        "the same payload carrying the re-read token is accepted, got "
        f"{second['status']!r}"
    )
    assert second["minimum_price_cents"] == 100000000, (
        "priced from the accepted appraisal, got "
        f"{second['minimum_price_cents']}"
    )

    _, both = validate_paginated(
        api.list_offerings(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert both["total_count"] == 2, (
        f"both disjoint windows now stand, got {both['total_count']}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["version"] == fresh + 1, (
        "and only the second successful create advanced the token again, got "
        f"{declaration['version']}"
    )
    assert declaration["status"] == "OFFERING_AUTHORIZED", (
        "the declaration never left the authorized state throughout, got "
        f"{declaration['status']!r}"
    )


def test_07_the_notice_filter_is_applied_before_the_page_is_cut(api):
    """total_count reports the filtered population, not the store-wide one.

    "List responses populate four pagination fields inside `meta`: `limit` and
    `offset` echo the effective values used for the query, `total_count` reports how
    many records match the filters before pagination is applied, and `has_more` is
    true exactly when records remain beyond the returned page." "Notices are
    readable individually and listable with filters on `declaration_id`, on
    `recipient_agency_id`, on `status` and on `notice_round`."

    Design: Corner/cross_cutting_complexity_layers/list_notices_filter_and_offset_paginate_together
    """
    custodian = fx.make_agency(api)
    housing = fx.make_preference_agency(api, "AFFORDABLE_HOUSING")
    transit = fx.make_transit_agency(api)
    school = fx.make_preference_agency(
        api,
        "SCHOOL_SITE",
        name="Riverbend Unified School District",
        agency_type="SCHOOL_DISTRICT",
        contact_email="facilities@riverbendusd.gov",
    )
    parcel_a = fx.make_parcel(api, custodian["id"], apn="APN-2693-183")
    parcel_b = fx.make_parcel(
        api,
        custodian["id"],
        apn="APN-2693-184",
        address="44 Depot Lane",
        acreage=1.4,
        zoning_code="C-2",
        book_value_cents=30000000,
    )
    declaration_a = fx.make_adopted_declaration(
        api, parcel_a["id"], resolution_number="RES-2026-283"
    )
    fx.issue_notices(
        api,
        declaration_a["id"],
        [housing["id"], transit["id"], school["id"]],
        60,
    )
    declaration_b = fx.make_adopted_declaration(
        api,
        parcel_b["id"],
        resolution_number="RES-2026-284",
        justification="Depot Lane annex is surplus after the fleet move.",
    )
    fx.issue_notices(api, declaration_b["id"], [transit["id"]], 90)

    first_rows, first_meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS,
            {"declaration_id": declaration_a["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_rows) == 2, (
        f"the page is cut to the requested size, got {len(first_rows)}"
    )
    assert first_meta["total_count"] == 3, (
        "while the count reports the three notices matching the filter, not the "
        f"four in the store, got {first_meta['total_count']}"
    )
    assert first_meta["limit"] == 2, f"the limit echoes back, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, (
        f"as does the offset, got {first_meta['offset']}"
    )
    assert first_meta["has_more"] is True, (
        f"and a third row remains beyond this page, got {first_meta['has_more']!r}"
    )

    second_rows, second_meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS,
            {"declaration_id": declaration_a["id"], "limit": 2, "offset": 1},
        )
    )
    assert len(second_rows) == 2, (
        f"the overlapping window still fills a page, got {len(second_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        f"over the same filtered population, got {second_meta['total_count']}"
    )
    assert second_meta["offset"] == 1, (
        f"from the requested offset, got {second_meta['offset']}"
    )
    assert second_meta["has_more"] is False, (
        "and rows 2 and 3 of 3 exhaust it, got " f"{second_meta['has_more']!r}"
    )

    for row in first_rows + second_rows:
        assert row["declaration_id"] == declaration_a["id"], (
            "the other declaration's notice never appears on either page, got "
            f"{row['declaration_id']!r}"
        )
        assert row["status"] == "ISSUED", (
            f"every notice is still awaiting a reply, got {row['status']!r}"
        )
        assert row["response_window_days"] == 60, (
            "each carries its own copy of the served window, got "
            f"{row['response_window_days']}"
        )
        assert row["response_deadline_at"] == "2026-09-30T00:00:00.000Z", (
            "and 60 days after 2026-08-01 is 2026-09-30, got "
            f"{row['response_deadline_at']!r}"
        )

    narrow_rows, narrow_meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS,
            {
                "declaration_id": declaration_a["id"],
                "status": "ISSUED",
                "recipient_agency_id": school["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert narrow_meta["total_count"] == 1, (
        f"three filters at once narrow it to one, got {narrow_meta['total_count']}"
    )
    assert narrow_rows[0]["recipient_agency_id"] == school["id"], (
        "the school district's own notice, got "
        f"{narrow_rows[0]['recipient_agency_id']!r}"
    )

    _, all_meta = validate_paginated(api.list_notices(fx.OFFICER_HEADERS, {"limit": 100}))
    assert all_meta["total_count"] == 4, (
        "and with no filter at all the store holds four notices, got "
        f"{all_meta['total_count']}"
    )


def test_08_readiness_is_re_derived_at_every_touch_rather_than_latched(api):
    """Three inputs are read afresh at create, at accept and at resolve.

    "A new parcel starts in `ownership_status` `AGENCY_OWNED`, `valuation_status`
    `UNVALUED`, `open_title_item_count` zero and `disposition_ready` false." "The
    parcel's `disposition_ready` is true when, and only when, all three of the
    following hold: `ownership_status` is `AGENCY_OWNED`, `valuation_status` is
    `CURRENT`, and `open_title_item_count` is zero."

    Design: Corner/cross_cutting_complexity_layers/parcel_disposition_ready_recomputes_after_title_item_resolve
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], apn="APN-2693-185")
    appraiser = fx.make_appraiser(api, license_number="AG-44285")
    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        f"a new parcel is held by its agency, got {parcel['ownership_status']!r}"
    )
    assert parcel["valuation_status"] == "UNVALUED", (
        f"with no valuation behind it, got {parcel['valuation_status']!r}"
    )
    assert parcel["open_title_item_count"] == 0, (
        f"no defect recorded yet, got {parcel['open_title_item_count']}"
    )
    assert parcel["disposition_ready"] is False, (
        "and so it is not ready, because one of the three conditions fails, got "
        f"{parcel['disposition_ready']!r}"
    )

    lien = fx.open_title_item(
        api,
        parcel["id"],
        item_type="LIEN",
        description="Recorded mechanics lien from 2019 sidewalk work",
        cure_cost_estimate_cents=400000,
    )
    with_defect = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert with_defect["open_title_item_count"] == 1, (
        f"the open defect is counted, got {with_defect['open_title_item_count']}"
    )
    assert with_defect["disposition_ready"] is False, (
        f"and readiness stays false, got {with_defect['disposition_ready']!r}"
    )

    appraisal = fx.order_appraisal(api, parcel["id"], appraiser["id"])
    fx.report_appraisal(api, appraisal["id"], appraiser["id"], 100000000)
    fx.accept_appraisal(api, appraisal["id"])
    valued = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert valued["valuation_status"] == "CURRENT", (
        f"the accepted report values the parcel, got {valued['valuation_status']!r}"
    )
    assert valued["open_title_item_count"] == 1, (
        "but the defect is still open, got " f"{valued['open_title_item_count']}"
    )
    assert valued["disposition_ready"] is False, (
        "so readiness is still refused rather than latched by the valuation, got "
        f"{valued['disposition_ready']!r}"
    )

    resolved = validate_success(
        api.resolve_title_item(
            lien["id"],
            f.cure_resolution_payload(250000),
            fx.OFFICER_HEADERS,
        ),
        200,
    )
    assert resolved["status"] == "CURED", (
        f"the lien is paid off, got {resolved['status']!r}"
    )
    assert resolved["actual_cure_cost_cents"] == 250000, (
        "at the cost supplied with the request, got "
        f"{resolved['actual_cure_cost_cents']}"
    )

    ready = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert ready["open_title_item_count"] == 0, (
        f"the last open defect is gone, got {ready['open_title_item_count']}"
    )
    assert ready["disposition_ready"] is True, (
        "and all three conditions now hold, so readiness flips without anybody "
        f"writing to the parcel, got {ready['disposition_ready']!r}"
    )

    rows, meta = validate_paginated(
        api.list_parcels(
            fx.OFFICER_HEADERS, {"disposition_ready": True, "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the derived flag is filterable on the list, got {meta['total_count']}"
    )
    assert rows[0]["id"] == parcel["id"], "and it returns the parcel just cleared"
