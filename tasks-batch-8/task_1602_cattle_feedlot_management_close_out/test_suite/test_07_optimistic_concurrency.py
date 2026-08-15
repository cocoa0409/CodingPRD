"""Optimistic concurrency control on the lot: expected_lot_version guards on
hedge creation and close-out creation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_hedge_payload,
    create_close_out_payload,
    create_lot,
    create_owner,
    get_lot,
    market_lot,
    record_death_loss,
    set_clock,
    ship_lot,
    validate_error,
    validate_success,
)

FYM = TEST_USERS["feedyard_manager_headers"]
RM = TEST_USERS["risk_manager_headers"]


class TestOccOnCloseOutCreate:
    def test_occ_stale_version_on_closeout_create_rejected(self, api):
        """PRD §2.7: "A request that enters a new hedge position for a lot, and a
        request that opens a new close-out for a lot, must each carry
        `expected_lot_version` in the request body, holding the lot `version` the
        client last observed. If the lot's current `version` has advanced since
        that observation — because a death loss, a health event, a feed
        allocation, a hedge offset, or any other mutation bumped it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_closeout_create_rejected
        """
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-OCC1", billing_email="occ1@x.com")
        lot = create_lot(owner["id"], lot_number="L-OCC1", head_count_in=10,
                         in_weight_total_lbs=7000, purchase_cost_cents=1400000)
        marketed = market_lot(lot["id"])
        stale_version = marketed["version"]
        ship_lot(lot["id"], "2026-08-02", 8000)

        resp = api.create_close_out(
            create_close_out_payload(lot["id"], stale_version,
                                     grid_base_price_cents_per_cwt=19000),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_lot(lot["id"])["version"]
        created = validate_success(api.create_close_out(
            create_close_out_payload(lot["id"], fresh_version,
                                     grid_base_price_cents_per_cwt=19000),
            RM,
        ), 201)
        assert created["status"] == "DRAFT", (
            "The same create with the current lot version succeeds"
        )


class TestOccOnHedgeCreate:
    def test_occ_stale_version_on_hedge_create_rejected(self, api):
        """PRD §2.7: "A request that enters a new hedge position for a lot, and a
        request that opens a new close-out for a lot, must each carry
        `expected_lot_version` in the request body, holding the lot `version` the
        client last observed. If the lot's current `version` has advanced since
        that observation — because a death loss, a health event, a feed
        allocation, a hedge offset, or any other mutation bumped it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_hedge_create_rejected
        """
        owner = create_owner(owner_name="O-OCC2", billing_email="occ2@x.com")
        lot = create_lot(owner["id"], lot_number="L-OCC2", head_count_in=80,
                         in_weight_total_lbs=80000, purchase_cost_cents=9600000)
        stale_version = lot["version"]
        record_death_loss(lot["id"], loss_date="2026-08-01", head_count=1,
                          insured=False)

        resp = api.create_hedge(
            create_hedge_payload(lot["id"], stale_version, quantity_contracts=2,
                                 entry_price_cents_per_cwt=19000),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_lot(lot["id"])["version"]
        created = validate_success(api.create_hedge(
            create_hedge_payload(lot["id"], fresh_version, quantity_contracts=2,
                                 entry_price_cents_per_cwt=19000),
            RM,
        ), 201)
        assert created["status"] == "OPEN", (
            "Fresh version: 2 x 400 = 800 cwt <= 1185 marketable after the death"
        )
