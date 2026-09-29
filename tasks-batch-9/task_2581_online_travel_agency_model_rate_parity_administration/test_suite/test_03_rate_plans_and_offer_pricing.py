"""Rate-plan ingestion channels, the sell-price build and offer publication."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_allotment,
    assert_offer_money,
    assert_pct,
)
from test_helpers.fixtures import (
    DEFAULT_INSTANT,
    air_merchant_offer,
    certified_hotel,
    hotel_agency_offer,
)
from test_helpers.test_users import (
    COMMERCIAL_MANAGER,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    supplier_user_headers,
)


def test_rate_plan_read_with_an_unknown_id_is_not_found(b, client):
    """Reading a rate plan that was never created is a rate-plan-shaped 404.

    PRD 2.8: "The catalogue of 404 identities is deliberately fine-grained so the
    failing segment is unambiguous" and names `ERR_RATE_PLAN_NOT_FOUND` among
    them, "all HTTP 404".

    Design: Corner/entities/rate_plan_get_unknown_id_returns_not_found
    """
    b.set_clock(DEFAULT_INSTANT)
    b.market(market_code="EU-PAR", name="Paris")

    response = client.get_rate_plan(NON_EXISTENT_UUID, COMMERCIAL_MANAGER)
    validate_error(response, E.ERR_RATE_PLAN_NOT_FOUND, 404)

    _data, meta = validate_paginated(client.list_rate_plans(PLATFORM_ADMIN))
    assert meta["total_count"] == 0


def test_offer_ingestion_without_the_net_rate_is_rejected(b, client):
    """A missing required field is refused and bumps no version.

    PRD 3.4: an offer is ingested "with a `travel_date` ..., a `net_rate_cents`
    of at least 1 ... an `allotment_total` of at least 1 giving the units released
    for that date, and the concurrency token `expected_rate_plan_version`".

    Design: Corner/entities/offer_create_missing_required_net_rate_is_rejected
    """
    ctx = certified_hotel(b)
    b.agreement(ctx.supplier["id"], model="AGENCY")
    plan = b.rate_plan(ctx.supplier["id"], ctx.market["id"])

    response = client.create_offer(
        plan["id"],
        {
            "travel_date": "2026-09-20",
            "allotment_total": 3,
            "expected_rate_plan_version": plan["version"],
        },
        supplier_user_headers(ctx.supplier["id"]),
    )
    validate_error(response, E.ERR_INVALID_REQUEST, 400)

    _data, meta = validate_paginated(
        client.list_offers(PLATFORM_ADMIN, params={"rate_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0
    assert b.read_rate_plan(plan["id"])["version"] == plan["version"]


def test_offer_money_is_computed_from_the_agreement_not_supplied(b, client):
    """The four money fields are derived from the agency base rate and the tax rate.

    PRD 3.4: "Under an `AGENCY` agreement the supplier has already published the
    sell rate, so `gross_cents` equals `net_rate_cents` exactly; ... with a
    percentage lever `marketplace_margin_cents` is the `net_rate_cents`
    multiplied by `applied_rate_pct`, rounded half up to a whole cent."

    Design: Corner/entities/offer_money_fields_are_computed_from_the_agreement_not_supplied
    """
    ctx = hotel_agency_offer(
        b,
        publish=False,
        agreement_overrides={"effective_to": "2026-12-31"},
        offer_overrides={"allotment_total": 3},
    )
    offer = ctx.offer

    assert offer["pricing_model"] == "AGENCY"
    assert_pct(offer["applied_rate_pct"], 0.15)
    assert offer["applied_override_id"] is None
    assert_offer_money(
        offer,
        gross_cents=24000,
        marketplace_margin_cents=3600,
        taxes_fees_cents=240,
        display_total_cents=24240,
        supplier_payable_cents=20400,
    )
    assert_allotment(offer, remaining=3, held=0, sold=0, total=3)
    assert offer["status"] == "PENDING"


def test_rate_plan_rejects_an_undeclared_enum_and_an_out_of_range_percentage(b, client):
    """Neither an undeclared policy code nor a tax rate above the ceiling is stored.

    PRD 3.4: a plan carries "a `cancellation_policy_code` of `FLEX`, `MODERATE`,
    `STRICT` or `NON_REF` ... a `tax_fee_pct` from 0 through 0.5".

    Design: Corner/entities/rate_plan_create_with_undeclared_enum_and_out_of_range_pct_rejected
    """
    ctx = certified_hotel(b)
    b.agreement(ctx.supplier["id"], model="AGENCY")
    headers = supplier_user_headers(ctx.supplier["id"])

    bad_enum = client.create_rate_plan(
        ctx.supplier["id"],
        f.rate_plan_payload(
            ctx.market["id"], name="Bad enum", cancellation_policy_code="SUPER_FLEX"
        ),
        headers,
    )
    validate_error(bad_enum, E.ERR_INVALID_REQUEST, 400)

    bad_pct = client.create_rate_plan(
        ctx.supplier["id"],
        f.rate_plan_payload(ctx.market["id"], name="Bad tax", tax_fee_pct=0.9),
        headers,
    )
    validate_error(bad_pct, E.ERR_INVALID_REQUEST, 400)

    _data, meta = validate_paginated(
        client.list_rate_plans(PLATFORM_ADMIN, params={"supplier_id": ctx.supplier["id"]})
    )
    assert meta["total_count"] == 0


def test_rate_plan_under_an_unknown_supplier_is_a_supplier_not_found(b, client):
    """A plan hung off a non-existent supplier is a supplier-shaped 404.

    PRD 2.8: "identifiers are resolved strictly left to right and the first one
    that fails to resolve determines the error".

    Design: Corner/entities/rate_plan_create_under_unknown_supplier_returns_not_found
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(market_code="EU-PAR", name="Paris")

    response = client.create_rate_plan(
        NON_EXISTENT_UUID,
        f.rate_plan_payload(market["id"], name="Orphan plan"),
        COMMERCIAL_MANAGER,
    )
    validate_error(response, E.ERR_SUPPLIER_NOT_FOUND, 404)

    _data, meta = validate_paginated(client.list_rate_plans(PLATFORM_ADMIN))
    assert meta["total_count"] == 0


def test_path_existence_is_checked_before_body_validation(b, client):
    """An unknown parent plus an invalid body yields the not-found, not the 400.

    PRD 2.10: the ladder runs "4. Path existence - every identifier in the path
    resolves, left to right" before "6. Request shape", and "The first check that
    fails determines the response; later checks are not evaluated".

    Design: Corner/validations/path_id_existence_is_checked_before_body_validation_returns_not_found
    """
    b.set_clock(DEFAULT_INSTANT)
    market = b.market(market_code="EU-PAR", name="Paris")

    response = client.create_rate_plan(
        NON_EXISTENT_UUID,
        f.rate_plan_payload(
            market["id"], name="Doubly invalid", cancellation_policy_code="SUPER_FLEX"
        ),
        COMMERCIAL_MANAGER,
    )
    body = validate_error(response, E.ERR_SUPPLIER_NOT_FOUND, 404)
    assert body["error_id"] != E.ERR_INVALID_REQUEST


def test_offer_listing_filters_by_plan_and_honours_limit_and_offset(b, client):
    """The offer listing pages the plan's own rows in created_at ascending order.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100" and "List
    responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`".

    Design: Corner/entities/offers_list_filters_by_rate_plan_and_honours_limit_and_offset
    """
    ctx = hotel_agency_offer(b, publish=False)
    second = b.offer(ctx.rate_plan["id"], travel_date="2026-09-21", net_rate_cents=24000)

    data, meta = validate_paginated(
        client.list_offers(
            COMMERCIAL_MANAGER,
            params={"rate_plan_id": ctx.rate_plan["id"], "limit": 1, "offset": 1},
        )
    )
    assert [row["id"] for row in data] == [second["id"]]
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["has_more"] is False

    first_page, first_meta = validate_paginated(
        client.list_offers(
            COMMERCIAL_MANAGER,
            params={"rate_plan_id": ctx.rate_plan["id"], "limit": 1, "offset": 0},
        )
    )
    assert [row["id"] for row in first_page] == [ctx.offer["id"]]
    assert first_meta["has_more"] is True


def test_offer_taxes_and_margin_round_half_up_at_the_half_cent(b, client):
    """A half-cent tax and a half-cent margin both round up, never toward even.

    PRD 2.6: "The default is round half up to a whole cent: it governs tax and
    fee computation, agency commission, refund shares, mediation fees and
    liability splits."

    Design: Corner/calculations/offer_taxes_and_margin_use_round_half_up_at_the_half_cent
    """
    ctx = hotel_agency_offer(b, publish=False)

    half_cent = b.offer(
        ctx.rate_plan["id"], travel_date="2026-09-22", net_rate_cents=24001
    )
    assert_offer_money(
        half_cent,
        gross_cents=24001,
        taxes_fees_cents=240,
        marketplace_margin_cents=3600,
        display_total_cents=24241,
        supplier_payable_cents=20401,
    )

    above_half = b.offer(
        ctx.rate_plan["id"], travel_date="2026-09-23", net_rate_cents=24050
    )
    assert_offer_money(
        above_half,
        gross_cents=24050,
        taxes_fees_cents=241,
        marketplace_margin_cents=3608,
        display_total_cents=24291,
        supplier_payable_cents=20442,
    )

    assert b.read_offer(ctx.offer["id"])["status"] == "PENDING"


def test_offer_at_the_travel_date_horizon_passes_and_one_day_beyond_is_rejected(b, client):
    """The horizon is inclusive on its last day and closed the day after.

    PRD 3.4: "The `travel_date` must fall on or after the current logical-clock
    date and no later than 500 days after it; anything outside that horizon is
    rejected with `ERR_TRAVEL_DATE_OUT_OF_RANGE`."

    Design: Corner/validations/offer_travel_date_at_the_horizon_passes_and_one_day_beyond_is_rejected
    """
    ctx = certified_hotel(b)
    b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to=f._OMIT,
    )
    plan = b.rate_plan(ctx.supplier["id"], ctx.market["id"])
    headers = supplier_user_headers(ctx.supplier["id"])

    at_horizon = client.create_offer(
        plan["id"],
        f.offer_payload("2027-12-18", 24000, plan["version"]),
        headers,
    )
    stored = validate_success(at_horizon, 201)
    assert stored["display_total_cents"] == 24240

    beyond = client.create_offer(
        plan["id"],
        f.offer_payload("2027-12-19", 24000, b.plan_version(plan["id"])),
        headers,
    )
    validate_error(beyond, E.ERR_TRAVEL_DATE_OUT_OF_RANGE, 422)

    _data, meta = validate_paginated(
        client.list_offers(PLATFORM_ADMIN, params={"rate_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1


def test_offer_publication_moves_pending_to_live(b, client):
    """Publication flips the status, clears the suppression reason and bumps version.

    PRD 3.4: "A `SupplierUser` or a `CommercialManager` publishes, optionally
    with a `note`, moving the offer `PENDING -> LIVE` or `SUPPRESSED -> LIVE`; on
    the second of those the `suppression_reason` is cleared" and "Each
    publication increments the offer's `version` by 1."

    Design: Corner/state_machines/offer_publish_moves_pending_to_live
    """
    ctx = hotel_agency_offer(b, publish=False)

    response = client.publish_offer(
        ctx.offer["id"], {"note": "Inventory verified"}, COMMERCIAL_MANAGER
    )
    published = validate_success(response)

    assert published["status"] == "LIVE"
    assert published["suppression_reason"] is None
    assert published["version"] == ctx.offer["version"] + 1
    assert published["display_total_cents"] == 24240
    assert published["allotment_remaining"] == 3


def test_supplier_user_cannot_publish_another_suppliers_offer(b, client):
    """Supplier scope binds writes to the caller's own supplier, but not reads.

    PRD 2.1: "A violation is rejected with `ERR_SUPPLIER_SCOPE_VIOLATION`
    (HTTP 403). Read endpoints are not scope-restricted: any authenticated role
    may read any resource."

    Design: Corner/rbac/supplier_user_cannot_publish_another_suppliers_offer
    """
    ctx = hotel_agency_offer(b, publish=False)
    ctx = air_merchant_offer(b, ctx, publish=False)

    intruder = supplier_user_headers(ctx.air_supplier["id"])
    denied = client.publish_offer(ctx.offer["id"], {}, intruder)
    validate_error(denied, E.ERR_SUPPLIER_SCOPE_VIOLATION, 403)

    cross_read = client.get_offer(ctx.offer["id"], intruder)
    assert validate_success(cross_read)["id"] == ctx.offer["id"]

    owner = supplier_user_headers(ctx.supplier["id"])
    published = validate_success(
        client.publish_offer(ctx.offer["id"], {}, owner)
    )
    assert published["status"] == "LIVE"
    assert published["version"] == ctx.offer["version"] + 1
    assert b.read_offer(ctx.air_offer["id"])["status"] == "PENDING"


def test_offer_publication_is_shared_by_commercial_manager_and_supplier_user(b, client):
    """Both declared writers reach the same transition on their own rows.

    PRD 3.4: "A `SupplierUser` or a `CommercialManager` publishes, optionally
    with a `note`, moving the offer `PENDING -> LIVE`".

    Design: Corner/rbac/offer_publish_is_shared_between_commercial_manager_and_supplier_user
    """
    ctx = hotel_agency_offer(b, publish=False)
    ctx = air_merchant_offer(b, ctx, publish=False)

    by_manager = validate_success(
        client.publish_offer(ctx.offer["id"], {}, COMMERCIAL_MANAGER)
    )
    by_supplier = validate_success(
        client.publish_offer(
            ctx.air_offer["id"], {}, supplier_user_headers(ctx.air_supplier["id"])
        )
    )

    assert by_manager["status"] == "LIVE"
    assert by_manager["version"] == 2
    assert by_manager["display_total_cents"] == 24240
    assert by_supplier["status"] == "LIVE"
    assert by_supplier["version"] == 2
    assert by_supplier["display_total_cents"] == 143106

    _data, meta = validate_paginated(
        client.list_offers(PLATFORM_ADMIN, params={"status": "LIVE"})
    )
    assert meta["total_count"] == 2


def test_offer_ingestion_with_a_stale_expected_rate_plan_version_is_rejected(b, client):
    """The plan version token guards ingestion and the retry with the fresh token wins.

    PRD 2.7: "If that value does not equal the plan's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/offer_create_with_a_stale_expected_rate_plan_version_is_rejected
    """
    ctx = hotel_agency_offer(b, publish=False)
    plan_version = b.plan_version(ctx.rate_plan["id"])
    headers = supplier_user_headers(ctx.supplier["id"])

    stale = client.create_offer(
        ctx.rate_plan["id"],
        f.offer_payload("2026-09-24", 24000, plan_version - 1),
        headers,
    )
    validate_error(stale, E.ERR_STALE_VERSION, 412)

    _data, meta = validate_paginated(
        client.list_offers(PLATFORM_ADMIN, params={"rate_plan_id": ctx.rate_plan["id"]})
    )
    assert meta["total_count"] == 1
    assert b.plan_version(ctx.rate_plan["id"]) == plan_version

    retry = validate_success(
        client.create_offer(
            ctx.rate_plan["id"],
            f.offer_payload("2026-09-24", 24000, plan_version),
            headers,
        ),
        201,
    )
    assert retry["display_total_cents"] == 24240

    untouched = b.read_offer(ctx.offer["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["version"] == 1


def test_provisional_certification_lapses_into_an_expired_certification_and_a_suspension(b, client):
    """Crossing the provisional expiry date expires the certificate and suspends the supplier.

    PRD 3.1: "A `PROVISIONAL` decision moves the package `IN_REVIEW ->
    PROVISIONAL` with the same stamps but a shorter runway: `expires_at` becomes
    the decision instant plus 90 days." PRD 2.5 then sweeps every package "whose
    `expires_at` is at or before the new instant" to `EXPIRED`, "which cascades
    its owning supplier from `ACTIVE` to `SUSPENDED` with `suspension_reason` set
    to `CERTIFICATION_EXPIRED`".

    Design: Difficulty/cross_entity_state_dependency/offer_publish_blocked_when_supplier_certification_has_expired
    """
    ctx = certified_hotel(b, decision="PROVISIONAL")
    assert ctx.certification["expires_at"].startswith("2026-11-03T00:00:00")

    b.set_clock("2026-11-04T00:00:00Z")

    cert = validate_success(
        client.get_certification(ctx.certification["id"], COMPLIANCE_OFFICER)
    )
    assert cert["status"] == "EXPIRED"

    supplier = b.read_supplier(ctx.supplier["id"])
    assert supplier["visibility_status"] == "SUSPENDED"
    assert supplier["suspension_reason"] == "CERTIFICATION_EXPIRED"


def test_offer_publication_is_blocked_once_the_certification_has_expired(b, client):
    """A PENDING offer cannot go live behind a lapsed certificate and stays PENDING.

    PRD 3.4: publication requires that "the supplier's `certification_level` must
    be `PROVISIONAL` or `CERTIFIED`", and "Failing the certification or visibility
    condition yields `ERR_SUPPLIER_NOT_CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/offer_publish_blocked_when_supplier_certification_has_expired
    """
    ctx = certified_hotel(b, decision="PROVISIONAL")
    b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    plan = b.rate_plan(ctx.supplier["id"], ctx.market["id"])
    offer = b.offer(plan["id"], travel_date="2026-12-20", net_rate_cents=24000)
    assert offer["status"] == "PENDING"

    b.set_clock("2026-11-04T00:00:00Z")

    denied = client.publish_offer(offer["id"], {}, COMMERCIAL_MANAGER)
    validate_error(denied, E.ERR_SUPPLIER_NOT_CERTIFIED, 422)

    after = b.read_offer(offer["id"])
    assert after["status"] == "PENDING"
    assert after["version"] == offer["version"]
