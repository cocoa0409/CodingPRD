"""Trade-area modeling: cannibalization variants, model-lock OCC and
supersession, and listing/forecast referential gates (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_draft_model,
    create_modeled_site,
    create_qualified_market,
    create_screened_site,
    create_stores,
    get_site_version,
    get_success_data,
    lock_model,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _five_store_roster(api, market_id):
    """S1..S4 OPERATING STANDARD + S5 EXPRESS (closed by the caller)."""
    stores = create_stores(market_id, (
        ("S1", "STANDARD", 800000000),
        ("S2", "STANDARD", 600000000),
        ("S3", "STANDARD", 400000000),
        ("S4", "STANDARD", 900000000),
        ("S5", "EXPRESS", 700000000),
    ))
    get_success_data(api.close_store(stores[4]["id"], ADMIN))
    return stores


def _drive_times(stores):
    return [
        {"store_id": stores[0]["id"], "drive_minutes": 3},
        {"store_id": stores[1]["id"], "drive_minutes": 8},
        {"store_id": stores[2]["id"], "drive_minutes": 12},
        {"store_id": stores[3]["id"], "drive_minutes": 20},
        {"store_id": stores[4]["id"], "drive_minutes": 2},
    ]


class TestCannibalizationVariants:
    """Same five-store drive-time set under both variants; S4 is beyond the
    contour and S5 is CLOSED, so both are excluded from either snapshot."""

    def _setup(self, api):
        market = create_qualified_market(name="Metro C")
        stores = _five_store_roster(api, market["id"])
        ctx = create_modeled_site(
            market["id"],
            site_overrides={"address": "9 Oak Ave"},
            store_drive_times=_drive_times(stores),
        )
        return ctx

    def test_flat_band_snapshot_excludes_closed_and_out_of_contour(self, api):
        """PRD §3.3: "Under `FLAT_BAND`, the factor is 0.30 for a store at most
        5 minutes away, 0.15 for a store 6 to 10 minutes away, and 0.05 for a
        store 11 or more minutes away out to the contour."
        PRD §3.3: "a store named in `store_drive_times` is eligible exactly
        when its `store_status` is `OPERATING` at that instant and its
        `drive_minutes` does not exceed the model's `drive_time_minutes`"

        Design: Difficulty/dual_variant_calc/cannibalization_flat_band_vs_distance_decay
        """
        ctx = self._setup(api)
        model = ctx["model"]
        assert model["model_status"] == "LOCKED"
        # 0.30*800000000 + 0.15*600000000 + 0.05*400000000; S4 (20 > 15)
        # out of contour and S5 CLOSED are both excluded.
        assert model["cannibalized_sales_cents"] == 350000000

    def test_distance_decay_snapshot_differs_for_identical_inputs(self, api):
        """PRD §3.3: "Under `DISTANCE_DECAY`, the factor is 0.35 multiplied by
        the square of the difference between the model's `drive_time_minutes`
        and the store's `drive_minutes`, divided by the square of
        `drive_time_minutes`, computed in exact decimal arithmetic."
        PRD §3.3: "Either way, each eligible store contributes its
        `annual_sales_cents` multiplied by its factor, rounded half-up to whole
        cents per store, and the snapshot is the integer sum of those per-store
        amounts."

        Design: Difficulty/dual_variant_calc/cannibalization_flat_band_vs_distance_decay
        """
        market = create_qualified_market(name="Metro C2")
        stores = _five_store_roster(api, market["id"])
        ctx = create_modeled_site(
            market["id"],
            site_overrides={"address": "9 Oak Ave"},
            store_drive_times=_drive_times(stores),
        )
        flat_model = ctx["model"]
        decay_model = create_draft_model(
            ctx["site"]["id"], cannibalization_variant="DISTANCE_DECAY",
            store_drive_times=_drive_times(stores),
        )
        decay_model = lock_model(decay_model["id"], ctx["site"]["id"])
        # 0.35*(15-3)^2/15^2 * 800000000 = 179200000;
        # 0.35*7^2/225 * 600000000 -> 45733333; 0.35*3^2/225 * 400000000 = 5600000.
        assert decay_model["cannibalized_sales_cents"] == 230533333
        assert decay_model["cannibalized_sales_cents"] != (
            flat_model["cannibalized_sales_cents"]
        )
        reloaded_flat = validate_success(
            api.get_trade_area_model(flat_model["id"], ANALYST)
        )
        assert reloaded_flat["model_status"] == "SUPERSEDED"
        assert decay_model["model_status"] == "LOCKED"


class TestModelRelockInvariant:
    def test_single_locked_model_before_relock(self, api):
        """PRD §3.3: "Any other `LOCKED` model of the same site becomes
        `SUPERSEDED` (first link)."
        PRD §2.3: "trade-area models by `site_id` and `model_status`"

        Design: Difficulty/compensating_invariant/model_relock_lock_count_invariant
        """
        market = create_qualified_market(name="Metro LC")
        ctx = create_modeled_site(market["id"])
        data, meta = validate_paginated(api.list_trade_area_models(
            ANALYST, params={"site_id": ctx["site"]["id"],
                             "model_status": "LOCKED"},
        ))
        assert meta["total_count"] == 1
        assert data[0]["id"] == ctx["model"]["id"]

    def test_single_locked_model_after_relock(self, api):
        """PRD §3.3: "Any other `LOCKED` model of the same site becomes
        `SUPERSEDED` (first link)."
        PRD §3.3: "Independently of the cascade, if the locking model's site
        was `SCREENED`, the site bubbles up from `SCREENED` to `MODELED`."

        Design: Difficulty/compensating_invariant/model_relock_lock_count_invariant
        """
        market = create_qualified_market(name="Metro LC2")
        ctx = create_modeled_site(market["id"])
        m1 = ctx["model"]
        m2 = create_draft_model(
            ctx["site"]["id"], drive_time_minutes=10,
            trade_area_population=42000, per_capita_spend_cents=290000,
            cannibalization_variant="DISTANCE_DECAY",
        )
        m2 = lock_model(m2["id"], ctx["site"]["id"])
        data, meta = validate_paginated(api.list_trade_area_models(
            ANALYST, params={"site_id": ctx["site"]["id"],
                             "model_status": "LOCKED"},
        ))
        assert meta["total_count"] == 1, (
            "exactly one LOCKED model per site across a supersede pair"
        )
        assert data[0]["id"] == m2["id"]
        reloaded_m1 = validate_success(api.get_trade_area_model(m1["id"], ANALYST))
        assert reloaded_m1["model_status"] == "SUPERSEDED"
        assert m2["model_status"] == "LOCKED"


class TestModelLockOCC:
    def test_occ_stale_model_lock_rejected(self, api):
        """PRD §2.6: "A request to `POST /api/trade-area-models/{id}/lock` must
        carry `expected_site_version`, equal to the current `version` of the
        site that owns the model as the client last observed it. Because locking
        any model for a site advances the site's `version`, a second lock issued
        against a stale observation indicates the client has not seen the newest
        locked model; the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_model_lock_rejected
        """
        market = create_qualified_market(name="Metro O1")
        site = create_screened_site(market["id"])
        model = create_draft_model(site["id"])
        site_v = get_site_version(site["id"])
        resp = api.lock_trade_area_model(
            model["id"], {"expected_site_version": site_v - 1}, ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        reloaded = validate_success(api.get_trade_area_model(model["id"], ANALYST))
        assert reloaded["model_status"] == "DRAFT"
        assert get_site_version(site["id"]) == site_v, (
            "a rejected lock leaves the site version unchanged"
        )

    def test_existence_precedes_occ_and_state(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and masks
        any failure a later layer would have produced."
        PRD §2.7: "Path-template identifiers are resolved left to right, and
        every body-referenced foreign key (`market_id`, `site_id`,
        `trade_area_model_id`, `sales_forecast_id`, `sponsor_member_id`,
        `loi_id`, `crew_id`, and each store id inside `store_drive_times`) must
        resolve to an existing resource; a dangling reference yields
        `ERR_NOT_FOUND` (404)."

        Design: Corner/validations/existence_precedes_occ_and_state
        """
        market = create_qualified_market(name="Metro EO")
        site = create_screened_site(market["id"])
        site_v = get_site_version(site["id"])
        resp = api.lock_trade_area_model(
            NON_EXISTENT_UUID, {"expected_site_version": site_v}, ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_manager_cannot_lock_model(self, api):
        """PRD §4: the `POST /api/trade-area-models/{id}/lock` row authorizes
        only "RealEstateAnalyst".
        PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/manager_cannot_lock_model
        """
        market = create_qualified_market(name="Metro R2")
        site = create_screened_site(market["id"])
        model = create_draft_model(site["id"])
        site_v = get_site_version(site["id"])
        resp = api.lock_trade_area_model(
            model["id"], {"expected_site_version": site_v}, MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        reloaded = validate_success(api.get_trade_area_model(model["id"], ANALYST))
        assert reloaded["model_status"] == "DRAFT"


class TestForecastModelGate:
    def test_error_trade_area_not_locked(self, api):
        """PRD §3.5: "The analyst frames the deal's revenue case as a sales
        forecast, created against a site in `MODELED` or `SCORED` (else
        `ERR_INVALID_STATE`) and pinned to that site's currently `LOCKED`
        trade-area model via `trade_area_model_id` — a model that is not
        `LOCKED`, or that belongs to another site, is rejected with
        `ERR_TRADE_AREA_NOT_LOCKED`."

        Design: Corner/errors/error_trade_area_not_locked
        """
        market = create_qualified_market(name="Metro E9")
        ctx = create_modeled_site(market["id"])
        draft_model = create_draft_model(
            ctx["site"]["id"], drive_time_minutes=10,
            trade_area_population=42000, per_capita_spend_cents=290000,
            cannibalization_variant="DISTANCE_DECAY",
        )
        resp = api.create_sales_forecast(
            {
                "site_id": ctx["site"]["id"],
                "trade_area_model_id": draft_model["id"],
                "model_variant": "ANALOG",
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_AREA_NOT_LOCKED)
