"""Tax remittance (per-line rounding, late penalty), meter deltas, RBAC denials,
pagination, OCC, immediate consistency, and computed reads (PRD §2, §3)."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_deliver_drop,
    create_diesel_product,
    create_gasoline_product,
    create_posted_price,
    create_product_payload,
    create_station,
    create_active_agreement,
    create_tank,
    create_truck,
    make_dealer_operator_headers,
    open_tax_remittance,
    set_clock,
    setup_full_drop_fixture,
    submit_meter_reading,
)

ADMIN = TEST_USERS["admin_headers"]
PRICING = TEST_USERS["pricing_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CREDIT = TEST_USERS["credit_headers"]
TAX = TEST_USERS["tax_headers"]


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula / remittance_per_line_rounding_order
# ---------------------------------------------------------------------------


def _remittance_fixture():
    """TX station excise 205; gasoline invoice 3333 gal delivered 2026-05-10;
    diesel invoice 1001 gal delivered 2026-05-11. Remittance TX period
    2026-05-01..2026-05-31, open in ACCRUING."""
    gas = create_gasoline_product()
    dsl = create_diesel_product()
    station = create_station(state_code="TX", state_excise_tc_per_gal=205,
                             credit_limit_cents=100_000_000)
    create_active_agreement(station["id"])
    create_posted_price(gas["id"], price_tc_per_gal=3000, effective_date="2026-05-01")
    create_posted_price(dsl["id"], price_tc_per_gal=3059, effective_date="2026-05-01")
    t_gas = create_tank(station["id"], gas["id"],
                        capacity_gallons=20000, opening_physical_gallons=0)
    t_dsl = create_tank(station["id"], dsl["id"],
                        capacity_gallons=20000, opening_physical_gallons=0)
    truck = create_truck()
    # Gasoline drop delivered 2026-05-10.
    from test_helpers import (
        create_transport_drop_payload,
        deliver_drop,
        dispatch_drop,
        schedule_drop,
    )
    d1 = get_success_data(api_client_drop_create(
        station["id"], t_gas["id"], truck["id"], gas["id"],
        planned_gallons=3333,
        window_start="2026-05-09T08:00:00Z", window_end="2026-05-09T12:00:00Z",
    ))
    schedule_drop(d1["id"])
    dispatch_drop(d1["id"])
    set_clock("2026-05-10T00:00:00Z")
    deliver_drop(d1["id"], 3333)
    # Diesel drop delivered 2026-05-11.
    d2 = get_success_data(api_client_drop_create(
        station["id"], t_dsl["id"], truck["id"], dsl["id"],
        planned_gallons=1001,
        window_start="2026-05-11T08:00:00Z", window_end="2026-05-11T12:00:00Z",
    ))
    schedule_drop(d2["id"])
    dispatch_drop(d2["id"])
    set_clock("2026-05-11T00:00:00Z")
    deliver_drop(d2["id"], 1001)
    rem = open_tax_remittance(state_code="TX",
                              period_start="2026-05-01", period_end="2026-05-31")
    return {"station": station, "remittance": rem, "gas": gas, "dsl": dsl}


def api_client_drop_create(station_id, tank_id, truck_id, product_id,
                           planned_gallons, window_start, window_end):
    """Indirection that calls the ApiClient; resolves through the module-level
    api_client singleton."""
    from test_helpers import api_client, create_transport_drop_payload
    return api_client.create_transport_drop(
        create_transport_drop_payload(
            station_id=station_id, tank_id=tank_id, truck_id=truck_id,
            product_id=product_id, planned_gallons=planned_gallons,
            window_start=window_start, window_end=window_end,
        ),
        DISPATCH,
    )


def test_remittance_per_line_rounding_order_gallons(api):
    """PRD §3.8: "`gasoline_gallons` is the sum of `gallons_delivered` over
    included invoices whose product category is `GASOLINE`, and
    `diesel_gallons` likewise for `DIESEL`."

    Design: Difficulty/combinatorial_formula/remittance_per_line_rounding_order
    """
    fx = _remittance_fixture()
    filed = validate_success(api.file_tax_remittance(fx["remittance"]["id"], TAX))
    assert filed["gasoline_gallons"] == 3333
    assert filed["diesel_gallons"] == 1001


def test_remittance_per_line_rounding_order_amounts(api):
    """PRD §3.8: "The `tax_amount_cents` is computed per category line — the
    line's gallons multiplied by the station's `state_excise_tc_per_gal`,
    divided by ten, rounded half-up to integer cents — and the remittance
    total is the sum of the rounded lines; the rounding order is pinned, per
    line first and then summed, because summing first and rounding once
    yields a different figure."
    PRD §3.8: "When the clock date at filing is after the `due_date`, a
    `late_penalty_cents` of five percent of `tax_amount_cents`, rounded
    half-up, is added; on time it is 0. The `total_due_cents` is the tax
    plus the penalty."

    Design: Difficulty/combinatorial_formula/remittance_per_line_rounding_order
    """
    fx = _remittance_fixture()
    filed = validate_success(api.file_tax_remittance(fx["remittance"]["id"], TAX))
    # Per-line: round_half_up(3333*205/10)=68327; round_half_up(1001*205/10)=20521;
    # sum 88848 (sum-then-round would yield 88847).
    assert filed["tax_amount_cents"] == 88_848
    # Filed 2026-05-11, due 2026-06-20 (period_end + 20 days) -> no late penalty.
    assert filed["late_penalty_cents"] == 0
    assert filed["total_due_cents"] == 88_848


# ---------------------------------------------------------------------------
# Corner / calculations / late_filing_penalty_applied
# ---------------------------------------------------------------------------


def test_late_filing_penalty_applied(api):
    """PRD §3.8: "the remittance begins in `ACCRUING` with a `due_date` of
    `period_end` plus 20 days."
    PRD §3.8: "When the clock date at filing is after the `due_date`, a
    `late_penalty_cents` of five percent of `tax_amount_cents`, rounded
    half-up, is added; on time it is 0. The `total_due_cents` is the tax
    plus the penalty."
    PRD §3.8: "the included invoices are those of stations whose `state_code`
    matches the remittance, in `ISSUED`, `OVERDUE`, or `PAID` status (voided
    invoices are excluded), with `invoice_date` falling within the period,
    both ends inclusive."

    Design: Corner/calculations/late_filing_penalty_applied
    """
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=205, price_tc_per_gal=2000,
        tank_capacity=20000, opening_physical=0,
    )
    # Deliver at clock 2026-05-10 -> invoice in period.
    set_clock("2026-05-10T10:00:00Z")
    create_and_deliver_drop(
        fixture, planned_gallons=1000,
        window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z",
    )
    rem = open_tax_remittance(state_code="TX",
                              period_start="2026-05-01", period_end="2026-05-31")
    assert rem["due_date"] == "2026-06-20"
    # Advance the clock past due_date before filing.
    set_clock("2026-06-21T00:00:00Z")
    filed = validate_success(api.file_tax_remittance(rem["id"], TAX))
    assert filed["tax_amount_cents"] == 20_500  # 1000 * 205 / 10
    assert filed["late_penalty_cents"] == 1_025  # round_half_up(0.05 * 20500)
    assert filed["total_due_cents"] == 21_525


# ---------------------------------------------------------------------------
# Corner / calculations / meter_delta_out_of_order_recompute
# ---------------------------------------------------------------------------


def test_meter_delta_out_of_order_recompute(api):
    """PRD §3.7: "Each reading's `metered_gallons` is the totalizer minus the
    chronological predecessor's totalizer for the same tank — readings are
    ordered by `reading_at` ascending with `created_at` ascending breaking
    ties — and zero for the tank's first reading. An out-of-order insert
    recomputes both its own delta and its chronological successor's delta..."
    PRD §2.3: "Meter readings are the single exception: they are returned
    ordered by `reading_at` ascending, with ties broken by `created_at`
    ascending, mirroring the chronological semantics of the totalizer."

    Design: Corner/calculations/meter_delta_out_of_order_recompute
    """
    fixture = setup_full_drop_fixture()
    tank_id = fixture["tank"]["id"]
    submit_meter_reading(fixture, tank_id, "2026-05-01T08:00:00Z", 10_000)
    pre = submit_meter_reading(fixture, tank_id, "2026-05-01T12:00:00Z", 10_500)
    assert pre["metered_gallons"] == 500
    # Insert out-of-order between the two.
    inserted = submit_meter_reading(fixture, tank_id, "2026-05-01T10:00:00Z", 10_200)
    assert inserted["metered_gallons"] == 200
    readings = get_success_data(api.list_meter_readings(
        ADMIN, params={"tank_id": tank_id}
    ))
    assert [r["metered_gallons"] for r in readings] == [0, 200, 300]


def test_meter_regression_rejected(api):
    """PRD §3.7: "a reading whose totalizer falls below its chronological
    predecessor's or above its chronological successor's is rejected with
    `ERR_METER_READING_REGRESSION` (HTTP 422)."

    Design: Corner/calculations/meter_regression_rejected
    """
    fixture = setup_full_drop_fixture()
    tank_id = fixture["tank"]["id"]
    submit_meter_reading(fixture, tank_id, "2026-05-01T08:00:00Z", 10_000)
    resp = api.create_meter_reading(
        {
            "tank_id": tank_id,
            "reading_at": "2026-05-01T09:00:00Z",
            "totalizer_gallons": 9_900,
        },
        fixture["dealer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_METER_READING_REGRESSION)


# ---------------------------------------------------------------------------
# Corner / validations / duplicate_remittance_period_rejected
# ---------------------------------------------------------------------------


def test_duplicate_remittance_period_rejected(api):
    """PRD §3.8: "A state may not have two remittances whose periods overlap
    — overlap is judged on closed intervals and against existing remittances
    in any status — and a conflicting create is rejected with
    `ERR_TAX_PERIOD_ALREADY_FILED`."

    Design: Corner/validations/duplicate_remittance_period_rejected
    """
    open_tax_remittance(state_code="TX",
                        period_start="2026-05-01", period_end="2026-05-31")
    resp = api.create_tax_remittance(
        {"state_code": "TX", "period_start": "2026-05-15", "period_end": "2026-06-15"},
        TAX,
    )
    validate_error(resp, ApiErrorId.ERR_TAX_PERIOD_ALREADY_FILED)


# ---------------------------------------------------------------------------
# Corner / validations / start_renewal_outside_window_rejected
# ---------------------------------------------------------------------------


def test_start_renewal_outside_window_rejected(api):
    """PRD §3.3: "A `JobberAdmin` may open renewal on an `ACTIVE` agreement
    only when the current clock date lies within the renewal window — from
    90 days before `term_end_date` through `term_end_date` itself, both ends
    inclusive; outside that window the request is rejected with
    `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Corner/validations/start_renewal_outside_window_rejected
    """
    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01", term_end_date="2026-12-31",
        committed_gallons=1000, imaging_allowance_cents=1000,
        margin_tc_per_gal=10, shortfall_penalty_tc_per_gal=10,
    )
    # Default clock is 2026-05-01; window opens 2026-10-02.
    resp = api.start_renewal(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)


# ---------------------------------------------------------------------------
# Corner / rbac
# ---------------------------------------------------------------------------


def test_pricing_desk_cannot_create_station(api):
    """PRD §2.1: "The division of responsibility is: `JobberAdmin` owns
    stations, agreements, tanks, trucks, products, reconciliations, loss
    adjudication, and the logical clock; `PricingDesk` owns rack price
    postings; ..."
    PRD §2.1: "When the acting role is not listed among the roles permitted
    on an endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/pricing_desk_cannot_create_station
    """
    resp = api.create_dealer_station(
        {
            "station_name": "S-X",
            "state_code": "TX",
            "home_terminal_code": "TX-NORTH",
            "state_excise_tc_per_gal": 200,
            "credit_limit_cents": 500000,
        },
        PRICING,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_dealer_operator_cannot_create_drop(api):
    """PRD §2.1: "When the acting role is not listed among the roles
    permitted on an endpoint, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.1: "`Dispatcher` owns transport drops"

    Design: Corner/rbac/dealer_operator_cannot_create_drop
    """
    dealer = make_dealer_operator_headers(NON_EXISTENT_UUID)
    resp = api.create_transport_drop(
        {
            "station_id": NON_EXISTENT_UUID,
            "tank_id": NON_EXISTENT_UUID,
            "truck_id": NON_EXISTENT_UUID,
            "product_id": NON_EXISTENT_UUID,
            "planned_gallons": 100,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        dealer,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_dealer_operator_gauge_foreign_station_forbidden(api):
    """PRD §2.1: "A `DealerOperator` acting on a resource belonging to a
    different station is rejected with `ERR_STATION_OWNERSHIP_MISMATCH`
    (HTTP 403), and all of a dealer operator's read access is likewise
    scoped to their own station's resources."
    PRD §2.9 step 5: "A `DealerOperator` may act only on resources of the
    station whose `id` equals `X-User-ID` — tanks and meter readings resolve
    ownership through the tank's station, loss events through their
    `station_id` — otherwise `ERR_STATION_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/dealer_operator_gauge_foreign_station_forbidden
    """
    station_a = create_station(station_name="S-A", activate=False)
    station_b = create_station(station_name="S-B", activate=False)
    product = create_gasoline_product()
    tank_b = create_tank(station_b["id"], product["id"],
                         capacity_gallons=20000, opening_physical_gallons=0)
    # Caller is station A; tank belongs to station B.
    resp = api.gauge_storage_tank(
        tank_b["id"],
        {"reading_gallons": 100, "observed_temp_f": 60},
        make_dealer_operator_headers(station_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STATION_OWNERSHIP_MISMATCH)


def test_credit_manager_cannot_post_price(api):
    """PRD §2.1: "`PricingDesk` owns rack price postings"
    PRD §2.1: "When the acting role is not listed among the roles permitted
    on an endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/credit_manager_cannot_post_price
    """
    product = create_gasoline_product()
    posting = get_success_data(api.create_rack_price_posting(
        {
            "terminal_code": "TX-NORTH",
            "product_id": product["id"],
            "effective_date": "2026-05-01",
            "price_tc_per_gal": 2000,
        },
        PRICING,
    ))
    resp = api.post_rack_price_posting(posting["id"], CREDIT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Corner / endpoints / list_pagination_filter_interaction
# ---------------------------------------------------------------------------


def test_list_pagination_filter_interaction(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10 when omitted, and must lie between 1 and 100
    inclusive. The `offset` parameter sets the number of items skipped and
    defaults to 0. List responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."
    PRD §2.3: "transport drops by `station_id`, `tank_id`, `truck_id`,
    `product_id`, `invoice_id`, and `status`"

    Design: Corner/endpoints/list_pagination_filter_interaction
    """
    fixture = setup_full_drop_fixture()
    fixture["tank2"] = create_tank(fixture["station"]["id"], fixture["product"]["id"],
                                   capacity_gallons=20000, opening_physical_gallons=0)
    from test_helpers import create_drop
    create_drop(fixture, planned_gallons=100,
                window_start="2026-05-02T08:00:00Z",
                window_end="2026-05-02T12:00:00Z")
    create_drop(fixture, planned_gallons=100, tank_id=fixture["tank2"]["id"],
                window_start="2026-05-03T08:00:00Z",
                window_end="2026-05-03T12:00:00Z")
    data, meta = validate_paginated(api.list_transport_drops(
        DISPATCH,
        params={"station_id": fixture["station"]["id"], "status": "PLANNED",
                "limit": 1, "offset": 0},
    ))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    data2, meta2 = validate_paginated(api.list_transport_drops(
        DISPATCH,
        params={"station_id": fixture["station"]["id"], "status": "PLANNED",
                "limit": 1, "offset": 1},
    ))
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert data2[0]["id"] != data[0]["id"]


# ---------------------------------------------------------------------------
# Corner / endpoints / buyout_quote_is_side_effect_free
# ---------------------------------------------------------------------------


def test_buyout_quote_is_side_effect_free(api):
    """PRD §3.3: "Before committing to either path, a `JobberAdmin` or
    `CreditManager` may read a computed buyout projection for the
    agreement..." (a read; no mutation is described)
    PRD §2.7: "`version` (integer): starts at creation and increments by one
    on every mutation; it is the basis of optimistic concurrency control."

    Design: Corner/endpoints/buyout_quote_is_side_effect_free
    """
    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        committed_gallons=1000, imaging_allowance_cents=1000,
        margin_tc_per_gal=10, shortfall_penalty_tc_per_gal=10,
    )
    before = get_success_data(api.get_supply_agreement(agreement["id"], ADMIN))
    validate_success(api.get_buyout_quote(agreement["id"], CREDIT))
    after = get_success_data(api.get_supply_agreement(agreement["id"], ADMIN))
    assert after["version"] == before["version"]
    assert after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner / consistency_model / immediate_mutation_visibility
# ---------------------------------------------------------------------------


def test_immediate_mutation_visibility(api):
    """PRD §1: "cross-entity consequences ... are applied immediately and
    are visible in the same request's response and in every subsequent
    read."
    PRD §3.1: "A `CreditManager` may separately update a station's
    `credit_limit_cents` or `credit_terms_days`; that update increments the
    station's `version` and, when the limit changed, re-evaluates the credit
    band of §2.10."
    PRD §2.7: "`version` (integer): starts at creation and increments by one
    on every mutation"

    Design: Corner/consistency_model/immediate_mutation_visibility
    """
    station = create_station(credit_limit_cents=500000, activate=False)
    assert station["version"] == 1
    validate_success(api.patch_dealer_station(
        station["id"],
        {"credit_limit_cents": 750000, "credit_terms_days": 21},
        CREDIT,
    ))
    station_now = get_success_data(api.get_dealer_station(station["id"], ADMIN))
    assert station_now["credit_limit_cents"] == 750_000
    assert station_now["credit_terms_days"] == 21
    assert station_now["version"] == 2


# ---------------------------------------------------------------------------
# Corner / complexity_layers / OCC tests
# ---------------------------------------------------------------------------


def test_occ_agreement_amend_stale_version(api):
    """PRD §3.2: "Amendment is one of the three optimistic-concurrency
    writes of §2.8: the request must carry `expected_agreement_version`
    matching the agreement's current `version`, and a stale value is
    rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amendment
    increments the agreement's `version`."

    Design: Corner/complexity_layers/occ_agreement_amend_stale_version
    """
    station = create_station(credit_limit_cents=500000, activate=False)
    from test_helpers import create_draft_agreement
    agreement = create_draft_agreement(station["id"], committed_gallons=1000,
                                       imaging_allowance_cents=1000,
                                       margin_tc_per_gal=10,
                                       shortfall_penalty_tc_per_gal=10)
    observed_version = agreement["version"]
    amended = validate_success(api.patch_supply_agreement(
        agreement["id"],
        {"expected_agreement_version": observed_version, "margin_tc_per_gal": 30},
        ADMIN,
    ))
    assert amended["version"] == observed_version + 1
    assert amended["margin_tc_per_gal"] == 30
    # Replay with the now-stale expected version.
    resp = api.patch_supply_agreement(
        agreement["id"],
        {"expected_agreement_version": observed_version, "margin_tc_per_gal": 40},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_posting_supersede_stale_version(api):
    """PRD §2.8: "Superseding a rack price posting. The supersession request
    must carry `expected_superseded_posting_version`, a non-optional field
    holding the `version` of the `POSTED` posting the client last observed.
    A mismatch with that posting's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)..."
    PRD §3.5: "Supersession retires a `POSTED` posting to `SUPERSEDED` and
    atomically creates its replacement: a brand-new posting in `POSTED`
    status for the same terminal, product, and effective date, priced at
    the request's `new_price_tc_per_gal`."

    Design: Corner/complexity_layers/occ_posting_supersede_stale_version
    """
    product = create_gasoline_product()
    posting = create_posted_price(product["id"], price_tc_per_gal=2000)
    # Stale (one behind).
    resp = api.supersede_rack_price_posting(
        posting["id"],
        {
            "expected_superseded_posting_version": posting["version"] - 1,
            "new_price_tc_per_gal": 2050,
            "effective_date": "2026-05-01",
        },
        PRICING,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Correct version succeeds and produces a POSTED replacement at 2050.
    # PRD §3.5 fixes the side effects (replacement created POSTED at
    # new_price_tc_per_gal; original retired to SUPERSEDED) but does not
    # specify which of the two resources the response body carries, so the
    # replacement is located through the list endpoint instead.
    validate_success(api.supersede_rack_price_posting(
        posting["id"],
        {
            "expected_superseded_posting_version": posting["version"],
            "new_price_tc_per_gal": 2050,
            "effective_date": "2026-05-01",
        },
        PRICING,
    ))
    postings = get_success_data(api.list_rack_price_postings(
        PRICING, params={"product_id": product["id"], "limit": 100}
    ))
    replacements = [
        p for p in postings
        if p["id"] != posting["id"] and p["status"] == "POSTED"
    ]
    assert len(replacements) == 1
    assert replacements[0]["price_tc_per_gal"] == 2050
    assert replacements[0]["terminal_code"] == posting["terminal_code"]
    assert replacements[0]["effective_date"] == posting["effective_date"]
    original = get_success_data(api.get_rack_price_posting(posting["id"], PRICING))
    assert original["status"] == "SUPERSEDED"


def test_occ_drop_replan_stale_version(api):
    """PRD §2.8: "Replanning a failed transport drop. The replan request
    must carry `expected_drop_version`, a non-optional field holding the
    drop `version` the client last observed. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing a dispatcher from writing a
    fresh window and truck onto a drop that has already been replanned and
    re-failed by someone else."

    Design: Corner/complexity_layers/occ_drop_replan_stale_version
    """
    from test_helpers import (
        create_drop,
        deliver_drop,
        dispatch_drop,
        schedule_drop,
    )
    fixture = setup_full_drop_fixture()
    drop = create_drop(fixture, planned_gallons=1000)
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    get_success_data(api.fail_transport_drop(
        drop["id"], {"reason": "first failure"}, DISPATCH
    ))
    observed = get_success_data(api.get_transport_drop(drop["id"], DISPATCH))
    observed_version = observed["version"]
    # First replan with the fresh version succeeds.
    get_success_data(api.replan_transport_drop(
        drop["id"],
        {
            "expected_drop_version": observed_version,
            "window_start": "2026-05-03T08:00:00Z",
            "window_end": "2026-05-03T12:00:00Z",
            "truck_id": fixture["truck"]["id"],
        },
        DISPATCH,
    ))
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    get_success_data(api.fail_transport_drop(
        drop["id"], {"reason": "second failure"}, DISPATCH
    ))
    # Replan again with the stale observed version -> 412.
    resp = api.replan_transport_drop(
        drop["id"],
        {
            "expected_drop_version": observed_version,
            "window_start": "2026-05-04T08:00:00Z",
            "window_end": "2026-05-04T12:00:00Z",
            "truck_id": fixture["truck"]["id"],
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
