"""Entity surface: declared fields, defaults, computed reads and shape refusals.

Creation echoes, retrieval fidelity, listing pagination, missing and out-of-enum
fields, server-minted identity, and the two append-only evidence rows that carry
neither `updated_at` nor `version`.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED,
    ERR_INVALID_REQUEST,
    ERR_LOT_NOT_FOUND,
    ERR_SUPPLIER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_fields_null,
    assert_identity_fields,
    assert_mass,
    assert_money,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
)
from test_helpers.types import (
    DD_PENDING,
    DISPOSITION_PASS,
    DISPOSITION_PRETREAT,
    FEEDSTOCK_CANOLA_OIL,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    HEDGE_OPEN,
    INSTRUMENT_RIN_FORWARD,
    LOT_PRETREAT_REQUIRED,
    LOT_RECEIVED,
    RUN_PLANNED,
    TIER_HEAVY,
    TIER_NONE,
    TIER_T1,
)


def test_supplier_creation_echoes_the_declared_fields_and_starts_pending(api):
    """PRD §3.1: "The new record starts with `dd_status` of `PENDING`,
    `dd_document_type_count` of 0, and `dd_verified_at`, `dd_expires_at` and
    `suspension_reason` all null."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/supplier_creation_returns_declared_fields_and_pending_dd_status
    """
    response = api.create_supplier(
        f.supplier_payload(feedstock_types=[FEEDSTOCK_UCO, FEEDSTOCK_TALLOW]), TRADER_HEADERS
    )
    supplier = validate_success(response, 201)

    assert supplier["legal_name"] == "Gulf Coast Renderers LLC"
    assert supplier["country_code"] == "US"
    assert supplier["feedstock_types"] == [FEEDSTOCK_UCO, FEEDSTOCK_TALLOW]
    assert supplier["is_high_risk_origin"] is False
    assert supplier["dd_status"] == DD_PENDING
    assert supplier["dd_document_type_count"] == 0
    assert_fields_null(supplier, "dd_verified_at", "dd_expires_at", "suspension_reason")
    assert supplier["version"] == 1

    body = response.json()
    assert body["response_type"] == "object", f"got {body['response_type']}"
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"], "api_request_timestamp must be present"


def test_hedge_position_read_returns_the_margin_fields_stamped_at_creation(api):
    """PRD §3.9: "Step two: `base_margin_usd` is `gross_notional_usd` multiplied by the
    instrument's base margin rate — 8 percent for a `FEEDSTOCK_SWAP`, 12 percent for a
    `RIN_FORWARD`, 15 percent for an `LCFS_FORWARD` — rounded half up to 2 decimal places."
    PRD §3.9: "A new position starts at status `OPEN` with `settlement_price_usd` null and
    `realized_pnl_usd` 0.00."

    Design: Corner/entities/hedge_position_retrieval_returns_stored_margin_fields
    """
    created = fx.make_hedge(
        api,
        instrument=INSTRUMENT_RIN_FORWARD,
        notional_units=10000,
        strike_price_usd=2.50,
        maturity_at="2026-12-31T00:00:00Z",
    )

    position = validate_success(api.get_hedge_position(created["id"], OFFICER_A_HEADERS))

    assert position["instrument"] == INSTRUMENT_RIN_FORWARD
    assert_money(position["gross_notional_usd"], 25000.00, "gross_notional_usd")
    assert_money(position["base_margin_usd"], 3000.00, "base_margin_usd")
    assert position["volatility_tier"] == TIER_T1
    assert_money(position["volatility_adder_usd"], 30.00, "volatility_adder_usd")
    assert_money(position["total_margin_usd"], 3030.00, "total_margin_usd")
    assert position["status"] == HEDGE_OPEN
    assert_fields_null(position, "settlement_price_usd")
    assert_money(position["realized_pnl_usd"], 0.00, "realized_pnl_usd")


def test_lot_listing_pages_by_created_at_with_total_count_and_has_more(api):
    """PRD §2.3: "For list responses the `meta` object carries `limit` and `offset` echoing
    the effective values in force for the page, `total_count` giving the number of rows
    matching the filters before pagination, and `has_more` indicating whether any matching
    row remains beyond the current page."
    PRD §2.3: "List results are ordered by `created_at` ascending in every case."

    Design: Corner/entities/feedstock_lot_listing_paginates_with_total_count_and_has_more
    """
    supplier = fx.make_supplier(api)
    for mass in (100.000, 200.000, 300.000):
        fx.make_lot(api, supplier["id"], mass_mt=mass)

    params = {"supplier_id": supplier["id"], "limit": 2, "offset": 0}
    rows, meta = validate_paginated(api.list_feedstock_lots(TRADER_HEADERS, params))

    assert len(rows) == 2, f"expected a page of two, got {len(rows)}"
    assert meta["total_count"] == 3, f"got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0
    assert_mass(rows[0]["mass_mt"], 100.000)
    assert_mass(rows[1]["mass_mt"], 200.000)

    tail, tail_meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {**params, "offset": 2})
    )
    assert len(tail) == 1, f"expected the final row, got {len(tail)}"
    assert_mass(tail[0]["mass_mt"], 300.000)
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False


def test_unknown_lot_id_is_a_not_found_and_never_an_empty_success(api):
    """PRD §2.7: "Every resource named by a path segment exists, validated left to right —
    one of `ERR_SUPPLIER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_TURNAROUND_WINDOW_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
    `ERR_RUN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_PATHWAY_NOT_FOUND`, `ERR_CREDIT_BLOCK_NOT_FOUND` or
    `ERR_HEDGE_POSITION_NOT_FOUND`, all 404."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/unknown_feedstock_lot_id_returns_not_found
    """
    response = api.get_feedstock_lot(NON_EXISTENT_UUID, TRADER_HEADERS)
    validate_error(response, ERR_LOT_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error", f"got {body['response_type']}"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_lot_creation_without_a_mass_is_a_request_shape_failure(api):
    """PRD §2.7: "Request-body shape: required fields present, types correct, enum members
    drawn from the declared sets, numeric ranges and decimal-place limits honoured, and a
    list `limit` within 1 through 100 — `ERR_INVALID_REQUEST`, 422."
    PRD §3.2: "records `mass_mt` — the delivered mass in metric tonnes, which must be greater
    than 0, no greater than 20000, and expressed to at most 3 decimal places"

    Design: Corner/entities/feedstock_lot_missing_required_mass_returns_invalid_request
    """
    supplier = fx.make_supplier(api)
    payload = f.feedstock_lot_payload(supplier["id"])
    payload.pop("mass_mt")

    validate_error(api.create_feedstock_lot(payload, TRADER_HEADERS), ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {"supplier_id": supplier["id"]})
    )
    assert meta["total_count"] == 0, f"no lot may survive the refusal, got {meta['total_count']}"


def test_new_lot_defaults_to_received_with_its_whole_mass_still_free(api):
    """PRD §3.2: "A newly booked lot starts at status `RECEIVED` with `pretreatment_tier` of
    `NONE`, `pretreatment_fee_usd` of 0.00, `pretreatment_loss_mt` and
    `pretreatment_consumed_mt` of 0.000, `allocated_mass_mt` of 0.000, `remaining_mass_mt`
    equal to its `mass_mt`, and `source_lot_id` null."

    Design: Corner/entities/feedstock_lot_defaults_to_received_status_and_zero_allocated_mass
    """
    supplier = fx.make_supplier(api)

    lot = validate_success(
        api.create_feedstock_lot(
            f.feedstock_lot_payload(supplier["id"], mass_mt=450.500), TRADER_HEADERS
        ),
        201,
    )

    assert lot["status"] == LOT_RECEIVED, f"got {lot['status']}"
    assert_mass(lot["allocated_mass_mt"], 0.000, "allocated_mass_mt")
    assert_mass(lot["remaining_mass_mt"], 450.500, "remaining_mass_mt")
    assert lot["pretreatment_tier"] == TIER_NONE
    assert_money(lot["pretreatment_fee_usd"], 0.00, "pretreatment_fee_usd")
    assert_mass(lot["pretreatment_loss_mt"], 0.000, "pretreatment_loss_mt")
    assert_mass(lot["pretreatment_consumed_mt"], 0.000, "pretreatment_consumed_mt")
    assert_fields_null(lot, "source_lot_id")
    assert lot["version"] == 1


def test_campaign_run_days_are_derived_from_the_window_not_supplied(api):
    """PRD §3.5: "A newly created campaign is `PLANNED`. Its `run_days` is the whole number of
    days between `window_start` and `window_end`. Its `reserved_mass_mt` and
    `consumed_mass_mt` are 0.000; `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` are
    null, because a campaign with no counted allocation has no blend and is feeding nothing"
    PRD §3.5: "`provisional_yield_pct`, `planned_total_product_mt`, `planned_rd_mt`,
    `planned_saf_mt`, `final_yield_pct`, `yield_variance_pct` and `feedstock_cost_usd` are
    unstamped at creation and become populated only at the securement, completion and
    reconciliation steps described below"

    Design: Corner/entities/processing_run_run_days_computed_from_window_bounds
    """
    plant = fx.commissioned_unit(api)

    run = validate_success(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-09-01T00:00:00Z",
                window_end="2026-09-08T00:00:00Z",
                target_saf_share_pct=5.00,
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert run["run_days"] == 7, f"got {run['run_days']}"
    assert run["status"] == RUN_PLANNED
    assert_mass(run["reserved_mass_mt"], 0.000, "reserved_mass_mt")
    assert_mass(run["consumed_mass_mt"], 0.000, "consumed_mass_mt")
    assert_fields_null(
        run,
        "blend_ci_gco2e_per_mj",
        "required_h2_kg_per_day",
        "provisional_yield_pct",
        "final_yield_pct",
        "abort_reason",
    )


def test_audit_timestamps_come_from_the_logical_clock_not_wall_time(api):
    """PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits
    recording when the row was first written. `updated_at` is the same format and records the
    most recent mutation; on creation it equals `created_at`."
    PRD §2.4: "Every resource the service creates is addressed by an `id` that is a
    server-minted UUID carrying no type prefix — the identifier of a feedstock lot is
    indistinguishable in shape from the identifier of a credit block, and clients must never
    parse it."

    Design: Corner/entities/supplier_system_fields_stamped_from_logical_clock
    """
    fx.move_clock(api, "2026-08-15T00:00:00Z", headers=TRADER_HEADERS)

    payload = f.supplier_payload(
        legal_name="Midwest Tallow Partners", feedstock_types=[FEEDSTOCK_TALLOW]
    )
    assert "id" not in payload, "clients never supply an id"
    supplier = validate_success(api.create_supplier(payload, TRADER_HEADERS), 201)

    assert_identity_fields(supplier)
    assert_timestamp_equals(supplier["created_at"], "2026-08-15T00:00:00Z", "created_at")
    assert_timestamp_equals(supplier["updated_at"], "2026-08-15T00:00:00Z", "updated_at")
    assert supplier["version"] == 1


def test_feedstock_type_outside_the_declared_enum_fails_the_schema_rung(api):
    """PRD §2.7: "One domain check sits inside this same rung, after the schema and enum
    checks have passed: a delivered lot's `feedstock_type` must appear in the cited supplier's
    `feedstock_types`, and if it does not the failure is `ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED`,
    also 422."
    PRD §3.1: "a non-empty `feedstock_types` array declaring which classes the supplier is
    approved to deliver, each member drawn from `UCO`, `TALLOW`, `DCO`, `SOYBEAN_OIL` and
    `CANOLA_OIL`"

    Design: Corner/entities/feedstock_lot_rejects_unknown_feedstock_type_enum
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])

    validate_error(
        api.create_feedstock_lot(
            f.feedstock_lot_payload(
                supplier["id"],
                feedstock_type="PALM_OIL",
                mass_mt=100.000,
                attested_ci_gco2e_per_mj=40.00,
                purchase_price_usd_per_mt=800.00,
            ),
            TRADER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        422,
    )

    _, meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {"supplier_id": supplier["id"]})
    )
    assert meta["total_count"] == 0, f"got {meta['total_count']}"


def test_declared_type_the_supplier_does_not_sell_is_a_capability_failure(api):
    """PRD §3.2: "The declared `feedstock_type` must appear in the cited supplier's
    `feedstock_types`, and a mismatch is refused with `ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED`."

    Design: Corner/entities/feedstock_lot_rejects_type_absent_from_supplier_feedstock_types
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])

    validate_error(
        api.create_feedstock_lot(
            f.feedstock_lot_payload(
                supplier["id"],
                feedstock_type=FEEDSTOCK_CANOLA_OIL,
                mass_mt=100.000,
                attested_ci_gco2e_per_mj=45.00,
                purchase_price_usd_per_mt=950.00,
            ),
            TRADER_HEADERS,
        ),
        ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED,
        422,
    )

    _, meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {"supplier_id": supplier["id"]})
    )
    assert meta["total_count"] == 0, f"got {meta['total_count']}"


def test_page_size_above_one_hundred_is_refused_rather_than_clamped(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100 — including a `limit` of 0 — is
    a request-shape failure and is refused with `ERR_INVALID_REQUEST` and HTTP 422."

    Design: Corner/entities/lot_listing_rejects_limit_above_declared_maximum
    """
    validate_error(
        api.list_feedstock_lots(TRADER_HEADERS, {"limit": 101, "offset": 0}),
        ERR_INVALID_REQUEST,
        422,
    )


def test_a_retest_appends_a_row_and_leaves_the_first_sample_untouched(api):
    """PRD §2.4: "Two resources are deliberately immutable append-only evidence and therefore
    carry only `id` and `created_at`: a traceability document and a quality test. Neither of
    them has an `updated_at` and neither of them has a `version`."
    PRD §3.2: "A `PRETREAT` moves the lot to `PRETREAT_REQUIRED`, sets `pretreatment_tier` to
    the test's `LIGHT` or `HEAVY`, and sets `pretreatment_fee_usd` to the quoted fee."

    Design: Corner/entities/quality_test_rows_are_immutable_and_append_only
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.make_lot(api, supplier["id"], mass_mt=200.000)
    fx.add_quality_test(api, lot["id"], lot["version"])

    fresh = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    retest = validate_success(
        api.create_quality_test(
            lot["id"],
            f.quality_test_payload(
                fresh["version"], ffa_pct=6.00, sampled_at="2026-08-02T00:00:00Z"
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    rows = get_success_data(api.list_quality_tests(lot["id"], ANALYST_HEADERS))
    assert len(rows) == 2, f"a retest appends, it does not replace: got {len(rows)}"
    assert rows[0]["ffa_pct"] == 1.00 and rows[0]["tier"] == TIER_NONE
    assert rows[0]["disposition"] == DISPOSITION_PASS, "the first row is frozen"
    assert retest["ffa_tier_index"] == 2
    assert retest["tier"] == TIER_HEAVY
    assert retest["disposition"] == DISPOSITION_PRETREAT
    for row in rows:
        assert_append_only_shape(row)

    governed = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert governed["status"] == LOT_PRETREAT_REQUIRED, f"got {governed['status']}"
    assert governed["pretreatment_tier"] == TIER_HEAVY
    assert_money(governed["pretreatment_fee_usd"], 10260.00, "pretreatment_fee_usd")


def test_evidence_cannot_be_uploaded_under_a_supplier_that_does_not_exist(api):
    """PRD §2.7: "Left-to-right means the leftmost unresolvable segment decides: a request
    naming a supplier that does not exist and a document that does not exist reports the
    supplier."
    PRD §3.1: "each upload names the owning supplier through the path — the stored row records
    that supplier as its `supplier_id`"

    Design: Corner/entities/traceability_document_under_unknown_supplier_returns_not_found
    """
    validate_error(
        api.create_traceability_document(
            NON_EXISTENT_UUID, f.traceability_document_payload(), TRADER_HEADERS
        ),
        ERR_SUPPLIER_NOT_FOUND,
        404,
    )
