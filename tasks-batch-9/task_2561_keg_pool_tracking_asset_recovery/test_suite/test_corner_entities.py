"""Entity creation, defaults, retrieval, listing and parentage.

These are the shape-of-the-row tests: what a freshly created resource looks
like when the caller supplies the bare minimum, which fields the server derives
rather than accepts, what a read gives back, and how a resource behaves when its
parent or its foreign keys do not resolve.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_brewer_headers,
    make_distributor_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}


def test_a_new_brewer_opens_active_with_every_ledger_at_zero():
    """A brewer registered with nothing but a name, a collar code and a credit
    limit comes back with `ACTIVE` standing, no status reason and all five
    risk-and-money counters at zero.

    PRD: "A newly registered brewer opens in `status` `ACTIVE` with
    `status_reason` unset, `chargeback_balance_cents` at 0, `lifetime_fill_count`
    at 0, `upheld_loss_count` at 0 and both loss-rate fields,
    `loss_rate_bp_trailing_90d` and `loss_rate_bp_lifetime`, at 0."

    PRD: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits recorded at creation from the logical clock."

    Design: Corner/entities/brewer_creation_returns_active_status_and_zeroed_ledgers
    """
    fixtures.pin_clock(CLOCK)

    created = validate_success(
        api_client.create_brewer(
            factories.create_brewer_payload(
                name="Ridgeline Brewing", brand_code="RDG", credit_limit_cents=400000
            ),
            OPERATOR,
        ),
        201,
    )

    assert created["name"] == "Ridgeline Brewing"
    assert created["brand_code"] == "RDG"
    assert created["credit_limit_cents"] == 400000
    assert created["status"] == "ACTIVE"
    assert created["status_reason"] is None
    assert created["chargeback_balance_cents"] == 0
    assert created["lifetime_fill_count"] == 0
    assert created["upheld_loss_count"] == 0
    assert created["loss_rate_bp_trailing_90d"] == 0
    assert created["loss_rate_bp_lifetime"] == 0
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])

    read_back = fixtures.read_brewer(created["id"])
    assert read_back["id"] == created["id"]
    assert read_back["version"] == 1


def test_a_pool_created_without_thresholds_takes_the_defaults_and_freezes():
    """Omitting all three throttle inputs yields 25, 10 and 2, and an empty pool
    reports zero availability with posture `FROZEN` rather than `OPEN`.

    PRD: "`restrict_threshold_pct`, an integer from 0 to 100 defaulting to 25, is
    the availability percentage at or above which the pool is fully open."

    PRD: "`restricted_max_kegs_per_order`, at least 1 and defaulting to 2, caps
    how many kegs a single order may ask for while the pool is throttled."

    PRD: "A newly created pool therefore opens with every counter at 0,
    `available_pct` at 0.00 and `posture` at `FROZEN`: an empty pool cannot issue
    float."

    Design: Corner/entities/pool_creation_applies_threshold_defaults_and_starts_frozen
    """
    fixtures.pin_clock(CLOCK)

    created = validate_success(
        api_client.create_pool(factories.create_pool_payload(**POOL), OPERATOR), 201
    )

    assert created["restrict_threshold_pct"] == 25
    assert created["freeze_threshold_pct"] == 10
    assert created["restricted_max_kegs_per_order"] == 2
    assert created["kegs_total"] == 0
    assert created["kegs_available"] == 0
    assert created["kegs_circulating"] == 0
    assert created["kegs_servicing"] == 0
    assert created["kegs_held"] == 0
    assert created["kegs_written_off"] == 0
    assert created["available_pct"] == 0.00
    assert created["posture"] == "FROZEN"
    assert created["version"] == 1


def test_a_keg_imported_with_only_a_tag_lands_in_float_and_certified():
    """One asset tag is enough: the keg opens `IN_FLOAT` / `SERVICE_OK` /
    `WITHIN_LIMIT`, treats its own creation as its last passing pressure test, and
    prices its shell at 3900 cents against the effective index.

    PRD: "`initial_custody_state` seeds `custody_state`; only `IN_FLOAT`,
    `IN_SERVICE` and `QUARANTINED` may be seeded, and when the field is omitted
    the keg opens in `IN_FLOAT`."

    PRD: "`last_pressure_test_at` records the instant of that last passing test;
    when the caller omits it the server records the new keg's own `created_at`,
    treating the factory acceptance test as the certification event, so this field
    is never null and every certification comparison is well defined."

    PRD: "Newly imported kegs open with `dwell_flag` `WITHIN_LIMIT`, with
    `current_brewer_id`, `current_distributor_id`, `filling_brewer_id`,
    `issuance_order_id`, `theft_investigation_id`, `filled_brand_code`,
    `dwell_started_at`, `distributor_custody_started_at`, `last_scanned_at` and
    `pre_hold_custody_state` all unset, with `cumulative_dwell_days` and
    `scan_count` at 0, and with `misdelivery_open` and `assessment_open` both
    false."

    PRD: "It is the pool's `stainless_weight_kg` multiplied by the stainless price
    in force, multiplied by a recovery factor of 65 percent, rounded half up to
    whole cents."

    Design: Corner/entities/keg_import_defaults_custody_service_state_and_certification
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)

    keg = validate_success(
        api_client.import_keg(
            pool["id"], factories.import_keg_payload("K-0001"), OPERATOR
        ),
        201,
    )

    assert keg["custody_state"] == "IN_FLOAT"
    assert keg["service_state"] == "SERVICE_OK"
    assert keg["dwell_flag"] == "WITHIN_LIMIT"
    assert keg["fill_count"] == 0
    assert keg["fills_at_last_pressure_test"] == 0
    assert keg["scan_count"] == 0
    assert keg["cumulative_dwell_days"] == 0
    assert keg["last_pressure_test_at"] == keg["created_at"]
    for field in (
        "current_brewer_id",
        "current_distributor_id",
        "filling_brewer_id",
        "issuance_order_id",
        "theft_investigation_id",
        "filled_brand_code",
        "dwell_started_at",
        "distributor_custody_started_at",
        "last_scanned_at",
        "pre_hold_custody_state",
    ):
        assert keg[field] is None, f"expected {field} unset on a fresh import"
    assert keg["misdelivery_open"] is False
    assert keg["assessment_open"] is False
    assert keg["stainless_scrap_value_cents"] == 3900

    after = fixtures.read_pool(pool["id"])
    assert after["kegs_total"] == 1
    assert after["kegs_available"] == 1
    assert after["available_pct"] == 100.00
    assert after["posture"] == "OPEN"


def test_the_import_derives_the_service_state_from_the_supplied_counters():
    """`service_state` is never accepted from the caller: 25 fills since the last
    test imports `SERVICE_DUE`, 24 imports `SERVICE_OK`, and a 2024 certification
    imports `SERVICE_OVERDUE` while its dwell classification stays clean.

    PRD: "From the imported counters the server derives `service_state` using
    exactly the rule the replenishment sweep uses."

    PRD: "If `fill_count` minus `fills_at_last_pressure_test` is at least 25 fills,
    the keg opens `SERVICE_DUE`."

    PRD: "If instead its certification is older than two years — that is, more than
    730 days have elapsed between `last_pressure_test_at` and the logical clock —
    it opens `SERVICE_OVERDUE`."

    Design: Corner/entities/keg_import_derives_service_state_from_the_supplied_counters
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)

    due = fixtures.import_keg(pool["id"], "K-DUE", fill_count=25, fills_at_last_pressure_test=0)
    ok = fixtures.import_keg(pool["id"], "K-OK", fill_count=24, fills_at_last_pressure_test=0)
    overdue = fixtures.import_keg(
        pool["id"], "K-OVERDUE", last_pressure_test_at="2024-01-01T00:00:00Z"
    )

    assert due["fill_count"] == 25
    assert due["service_state"] == "SERVICE_DUE"
    assert ok["fill_count"] == 24
    assert ok["service_state"] == "SERVICE_OK"
    assert overdue["last_pressure_test_at"] == "2024-01-01T00:00:00Z"
    assert overdue["service_state"] == "SERVICE_OVERDUE"
    assert overdue["dwell_flag"] == "WITHIN_LIMIT"

    after = fixtures.read_pool(pool["id"])
    assert after["kegs_total"] == 3
    assert after["kegs_available"] == 3
    assert after["available_pct"] == 100.00
    assert after["posture"] == "OPEN"


def test_reading_a_pool_and_a_keg_returns_the_stored_values_untouched():
    """A technician reading the pool and the keg gets the stored figures back
    verbatim, with the keg pointing at its parent pool, and neither read advances a
    `version`.

    PRD: "Reading a single keg returns both state dimensions, the dwell
    classification, the custody foreign keys, the tallies `fill_count`,
    `scan_count` and `cumulative_dwell_days`, the instants `last_scanned_at`,
    `dwell_started_at`, `distributor_custody_started_at` and
    `last_pressure_test_at`, the flags `misdelivery_open` and `assessment_open`,
    and the freshly recomputed `stainless_scrap_value_cents`."

    PRD: "The keg's `pool_id` is taken from the pool being imported into and is
    immutable thereafter."

    PRD: "Reads never advance a `version`."

    Design: Corner/entities/pool_and_keg_retrieval_round_trip_every_stored_field
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(
        restrict_threshold_pct=25,
        freeze_threshold_pct=10,
        restricted_max_kegs_per_order=2,
        **POOL,
    )
    keg = fixtures.import_keg(pool["id"], "K-0001")

    read_pool = validate_success(api_client.get_pool(pool["id"], TECHNICIAN))
    read_keg = validate_success(api_client.get_keg(keg["id"], TECHNICIAN))

    assert read_pool["pool_code"] == "HB-50L"
    assert read_pool["size_liters"] == 50
    assert read_pool["stainless_weight_kg"] == 12.5
    assert read_pool["replacement_cost_cents"] == 23500
    assert read_pool["region_code"] == "CO"
    assert read_pool["kegs_total"] == 1
    assert read_pool["kegs_available"] == 1
    assert read_pool["available_pct"] == 100.00
    assert read_pool["posture"] == "OPEN"

    assert read_keg["pool_id"] == pool["id"]
    assert read_keg["asset_tag"] == "K-0001"
    assert read_keg["custody_state"] == "IN_FLOAT"
    assert read_keg["stainless_scrap_value_cents"] == 3900

    assert validate_success(api_client.get_pool(pool["id"], TECHNICIAN))["version"] == read_pool["version"]
    assert validate_success(api_client.get_keg(keg["id"], TECHNICIAN))["version"] == read_keg["version"]
    assert read_keg["version"] == 1


def test_the_pool_keg_listing_reports_the_prefilter_total_and_has_more():
    """Two-row windows over five kegs report the full total on every page, flag
    `has_more` only while rows remain, and the default page size of ten returns the
    whole fleet in one read.

    PRD: "`limit` controls page size: it defaults to 10, may be no smaller than 1
    and no larger than 100."

    PRD: "For list responses, the `meta` object carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` is true when rows remain
    beyond the current page."

    Design: Corner/entities/pool_kegs_listing_reports_total_count_and_has_more
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)
    fixtures.import_kegs(pool["id"], [f"K-{n:04d}" for n in range(1, 6)])

    first_rows, first_meta = validate_paginated(
        api_client.list_pool_kegs(pool["id"], OPERATOR, params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 5
    assert first_meta["has_more"] is True

    last_rows, last_meta = validate_paginated(
        api_client.list_pool_kegs(pool["id"], OPERATOR, params={"limit": 2, "offset": 4})
    )
    assert len(last_rows) == 1
    assert last_meta["limit"] == 2
    assert last_meta["offset"] == 4
    assert last_meta["total_count"] == 5
    assert last_meta["has_more"] is False

    all_rows, all_meta = validate_paginated(
        api_client.list_pool_kegs(pool["id"], OPERATOR)
    )
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert len(all_rows) == 5
    assert all_meta["total_count"] == 5
    assert all_meta["has_more"] is False

    middle_rows, _meta = validate_paginated(
        api_client.list_pool_kegs(pool["id"], OPERATOR, params={"limit": 2, "offset": 2})
    )
    windows = [
        {row["asset_tag"] for row in first_rows},
        {row["asset_tag"] for row in middle_rows},
        {row["asset_tag"] for row in last_rows},
    ]
    assert windows[0].isdisjoint(windows[1])
    assert windows[1].isdisjoint(windows[2])
    assert windows[0] | windows[1] | windows[2] == {
        "K-0001",
        "K-0002",
        "K-0003",
        "K-0004",
        "K-0005",
    }


def test_an_unknown_keg_id_is_a_404_in_the_error_envelope():
    """A well-formed UUID that names no keg row is refused with the keg's own
    not-found code, carried in the error envelope rather than as an empty success.

    PRD: "A path identifier that does not resolve produces the 404 belonging to
    that resource type: `ERR_BREWER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_KEG_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_SERVICE_CYCLE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND` or
    `ERR_INVESTIGATION_NOT_FOUND`."

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/keg_detail_on_unknown_id_returns_keg_not_found
    """
    fixtures.pin_clock(CLOCK)

    response = api_client.get_keg(NON_EXISTENT_UUID, OPERATOR)
    validate_error(response, ApiErrorId.ERR_KEG_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_a_required_input_with_no_default_cannot_be_omitted():
    """A brewer without its collar code and a pool without its replacement cost are
    both refused as malformed requests, and neither mints a row.

    PRD: "Request shape: required fields present, JSON types correct, enum values
    inside their declared domain, integers inside their declared range, ISO 8601
    instants parseable, dates in `YYYY-MM-DD` form, and no conditionally forbidden
    field supplied — for example a `brewer_id` on a scan whose `party_type` is
    `DISTRIBUTOR`."

    PRD: "A `PoolOperator` registers a brewing company by supplying its legal
    `name`, between 1 and 120 characters and not blank, and its `brand_code` — the
    collar brand code stamped on the kegs that brewer fills, 2 to 8 characters drawn
    from uppercase letters and digits, and unique across every brewer on the
    platform."

    Design: Corner/entities/brewer_creation_missing_brand_code_returns_invalid_request
    """
    fixtures.pin_clock(CLOCK)

    validate_error(
        api_client.create_brewer({"name": "Ridgeline Brewing"}, OPERATOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_pool(
            {
                "pool_code": "HB-50L",
                "size_liters": 50,
                "stainless_weight_kg": 12.5,
                "region_code": "CO",
            },
            OPERATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    # Neither refusal consumed its unique key, so both creates now succeed.
    validate_success(
        api_client.create_brewer(factories.create_brewer_payload(), OPERATOR), 201
    )
    validate_success(
        api_client.create_pool(factories.create_pool_payload(**POOL), OPERATOR), 201
    )


def test_the_two_declared_pool_domain_constraints_are_enforced_at_shape_time():
    """A freeze threshold that is not strictly below the restrict threshold, and a
    size that is not one of the four declared litres, are both invalid requests, and
    the failed attempt does not consume the pool code.

    PRD: "`freeze_threshold_pct`, an integer from 0 to 100 defaulting to 10, is the
    availability percentage below which the pool freezes; it must be strictly less
    than `restrict_threshold_pct`, and a creation that violates that relationship is
    refused as an invalid request."

    PRD: "A `PoolOperator` creates it with a `pool_code` of 3 to 16 characters,
    unique across all pools and refused with `ERR_DUPLICATE_POOL_CODE` if repeated;
    a `size_liters` that must be one of 20, 30, 50 or 58; a `stainless_weight_kg`
    giving the empty stainless mass of one keg in this class, which must be greater
    than zero, no greater than 60, and carry at most two decimal places; a
    `replacement_cost_cents` greater than zero, which is the new-keg cost used as
    the gross basis of replacement-cost loss assessments; and a two-character
    uppercase `region_code` naming the region the pool serves."

    Design: Corner/entities/pool_creation_with_freeze_threshold_not_below_restrict_threshold_rejected
    """
    fixtures.pin_clock(CLOCK)

    validate_error(
        api_client.create_pool(
            factories.create_pool_payload(
                **POOL, restrict_threshold_pct=25, freeze_threshold_pct=30
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_pool(
            factories.create_pool_payload(
                pool_code="HB-40L",
                size_liters=40,
                stainless_weight_kg=12.5,
                replacement_cost_cents=23500,
                region_code="CO",
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    accepted = validate_success(
        api_client.create_pool(factories.create_pool_payload(**POOL), OPERATOR), 201
    )
    assert accepted["pool_code"] == "HB-50L"
    assert accepted["freeze_threshold_pct"] == 10
    assert accepted["restrict_threshold_pct"] == 25


def test_only_the_three_seedable_custody_states_may_be_imported():
    """`FILLED` is a perfectly legal custody state and is still refused at import,
    as is a value outside the vocabulary, while `IN_SERVICE` is accepted and counted
    as servicing — which leaves the pool frozen with nothing on the floor.

    PRD: "`initial_custody_state` seeds `custody_state`; only `IN_FLOAT`,
    `IN_SERVICE` and `QUARANTINED` may be seeded, and when the field is omitted the
    keg opens in `IN_FLOAT`."

    PRD: "`kegs_servicing` counts the kegs in `IN_SERVICE` or `QUARANTINED`."

    PRD: "Otherwise — including whenever `kegs_total` is zero — the posture is
    `FROZEN`."

    Design: Corner/entities/keg_import_with_unseedable_initial_custody_state_rejected
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)

    validate_error(
        api_client.import_keg(
            pool["id"],
            factories.import_keg_payload("K-BAD1", initial_custody_state="FILLED"),
            OPERATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.import_keg(
            pool["id"],
            factories.import_keg_payload("K-BAD2", initial_custody_state="NOT_A_STATE"),
            OPERATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    servicing = validate_success(
        api_client.import_keg(
            pool["id"],
            factories.import_keg_payload("K-SVC", initial_custody_state="IN_SERVICE"),
            OPERATOR,
        ),
        201,
    )
    assert servicing["custody_state"] == "IN_SERVICE"

    after = fixtures.read_pool(pool["id"])
    assert after["kegs_total"] == 1
    assert after["kegs_servicing"] == 1
    assert after["kegs_available"] == 0
    assert after["available_pct"] == 0.00
    assert after["posture"] == "FROZEN"


def test_an_import_under_an_unknown_pool_is_refused_before_the_body_is_read():
    """The pool in the path is resolved first, so an import under an unknown pool is
    a pool not-found; the tag it carried is never consumed and a keg imported into
    one pool never surfaces in another pool's listing.

    PRD: "When a keg is imported into a pool, the pool identified in the path is
    resolved before the request body is examined at all; when a nested resource is
    addressed, each ancestor must exist before its descendant is looked at."

    PRD: "Asset tags are unique **globally**, across every pool and not merely
    within one: a tag is etched onto the shell, so the same tag may not be reused
    when a keg is re-homed into a different pool, and a repeat is refused with
    `ERR_DUPLICATE_ASSET_TAG`."

    Design: Corner/entities/keg_import_under_unknown_pool_returns_pool_not_found
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    first_pool = fixtures.create_pool(**POOL)
    second_pool = fixtures.create_pool(
        pool_code="HB-30L",
        size_liters=30,
        stainless_weight_kg=9.5,
        replacement_cost_cents=19000,
        region_code="CO",
    )
    first_keg = fixtures.import_keg(first_pool["id"], "K-0001")

    validate_error(
        api_client.import_keg(
            NON_EXISTENT_UUID, factories.import_keg_payload("K-0002"), OPERATOR
        ),
        ApiErrorId.ERR_POOL_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(
        api_client.list_pool_kegs(second_pool["id"], OPERATOR)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    assert fixtures.read_keg(first_keg["id"])["pool_id"] == first_pool["id"]
    assert fixtures.read_pool(second_pool["id"])["kegs_total"] == 0

    rehomed = fixtures.import_keg(second_pool["id"], "K-0002")
    assert rehomed["pool_id"] == second_pool["id"]
    assert rehomed["asset_tag"] == "K-0002"


def _a_keg_delivered_under_another_brewery_s_collar():
    """One keg filled by Ridgeline and then scanned into a wholesaler's yard under
    the Oakline collar, which is what a misdelivery looks like on the record."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=2,
        keg_count=2,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": 2200},
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    other_brewer = fixtures.create_brewer(
        name="Oakline Ales", brand_code="OAK", credit_limit_cents=400000
    )
    distributor = fixtures.create_distributor(name="High Plains Distributing")

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    misdelivery = fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "OAK"
    )

    ctx["other_brewer"] = other_brewer
    ctx["distributor"] = distributor
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    ctx["misdelivery_scan"] = misdelivery
    return ctx


def test_a_claim_joins_the_keg_its_filler_the_wrong_brewery_and_the_claimant():
    """One claim row carries four distinct parents: the keg, the distributor that
    filed it, the brewer that filled the keg and the different brewer whose collar
    was scanned — and the claimant is taken from the acting identity, not the body.

    PRD: "The claim's own `claimant_distributor_id` is resolved from the acting
    `X-User-ID` rather than supplied, and `owning_brewer_id` is copied from the keg's
    `filling_brewer_id`."

    PRD: "A new claim opens in `SUBMITTED` with `round_count` at 0,
    `counter_offset_cents` and `agreed_offset_cents` unset, and
    `last_responder_role` already recorded as `Distributor`, because filing the claim
    *is* the distributor's first move."

    Design: Corner/entities/reconciliation_claim_junction_links_keg_owning_brewer_and_misdelivered_brewer
    """
    ctx = _a_keg_delivered_under_another_brewery_s_collar()

    claim = validate_success(
        api_client.create_reconciliation_claim(
            factories.create_reconciliation_claim_payload(
                ctx["keg_id"], ctx["other_brewer"]["id"], 1200, "2026-08-01T03:00:00Z"
            ),
            make_distributor_headers(ctx["distributor"]["id"]),
        ),
        201,
    )

    assert claim["keg_id"] == ctx["keg_id"]
    assert claim["claimant_distributor_id"] == ctx["distributor"]["id"]
    assert claim["owning_brewer_id"] == ctx["brewer"]["id"]
    assert claim["misdelivered_to_brewer_id"] == ctx["other_brewer"]["id"]
    assert claim["misdelivered_to_brewer_id"] != claim["owning_brewer_id"]
    assert claim["claimed_offset_cents"] == 1200
    assert claim["status"] == "SUBMITTED"
    assert claim["round_count"] == 0
    assert claim["version"] == 1
    assert claim["counter_offset_cents"] is None
    assert claim["agreed_offset_cents"] is None
    assert claim["closed_at"] is None
    assert claim["supersedes_claim_id"] is None
    assert claim["last_responder_role"] == "Distributor"

    assert ctx["misdelivery_scan"]["misdelivery_detected"] is True
    assert fixtures.read_keg(ctx["keg_id"])["misdelivery_open"] is True

    _rows, by_keg = validate_paginated(
        api_client.list_reconciliation_claims(OPERATOR, params={"keg_id": ctx["keg_id"]})
    )
    assert by_keg["total_count"] == 1
    _rows, by_brewer = validate_paginated(
        api_client.list_reconciliation_claims(
            OPERATOR, params={"misdelivered_to_brewer_id": ctx["other_brewer"]["id"]}
        )
    )
    assert by_brewer["total_count"] == 1


def test_a_superseding_claim_needs_a_closed_predecessor_on_the_same_keg():
    """Naming a still-live predecessor is a supersede mismatch rather than an
    already-open conflict; once the brewer rejects the first claim the identical
    refile is accepted, even though the misdelivery flag is still raised.

    PRD: "When `supersedes_claim_id` is supplied it must name a claim on the *same*
    keg whose `status` is `REJECTED` or `WITHDRAWN`; pointing at a claim on a
    different keg, or at one that is still live or already `AGREED`, is
    `ERR_CLAIM_SUPERSEDE_MISMATCH`."

    PRD: "Both deliberately leave `misdelivery_open` set to true, because the
    misdelivery itself has not been resolved and the distributor is entitled to file
    a superseding claim citing the same evidence scan, subject to the 30-day window
    still being open."

    Design: Corner/entities/reconciliation_claim_supersede_requires_same_keg_and_a_closed_predecessor
    """
    ctx = _a_keg_delivered_under_another_brewery_s_collar()
    first_claim = fixtures.file_claim(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        ctx["other_brewer"]["id"],
        1200,
        "2026-08-01T03:00:00Z",
    )

    def refile():
        return api_client.create_reconciliation_claim(
            factories.create_reconciliation_claim_payload(
                ctx["keg_id"],
                ctx["other_brewer"]["id"],
                900,
                "2026-08-01T03:00:00Z",
                supersedes_claim_id=first_claim["id"],
            ),
            make_distributor_headers(ctx["distributor"]["id"]),
        )

    validate_error(refile(), ApiErrorId.ERR_CLAIM_SUPERSEDE_MISMATCH.value, 422)

    rejected = fixtures.respond_to_claim(
        first_claim["id"], "REJECT", make_brewer_headers(ctx["other_brewer"]["id"])
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["closed_at"] is not None
    assert rejected["version"] == 2
    assert fixtures.read_keg(ctx["keg_id"])["misdelivery_open"] is True

    second_claim = validate_success(refile(), 201)
    assert second_claim["supersedes_claim_id"] == first_claim["id"]
    assert second_claim["keg_id"] == ctx["keg_id"]
    assert second_claim["status"] == "SUBMITTED"
    assert second_claim["round_count"] == 0

    _rows, chain = validate_paginated(
        api_client.list_reconciliation_claims(
            OPERATOR, params={"supersedes_claim_id": first_claim["id"]}
        )
    )
    assert chain["total_count"] == 1
