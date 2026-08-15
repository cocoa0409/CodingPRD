"""Production-day records, FIFO feed costing, and flock ledger updates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_production_day,
    get_flock,
    record_feed_delivery,
    record_production_days,
    setup_laying_flock,
    setup_laying_flock_with_production,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import FARM_MANAGER, api_client, get_feed_delivery


class TestFeedFifo:
    def test_feed_fifo_crosses_price_layers_in_delivery_order(self, api):
        """PRD §3.3: "Issued feed is costed against the farm's FIFO queue at
        creation time, chronologically. The system walks the farm's deliveries
        with `remaining_kg` above zero from oldest to newest, taking from each
        layer the smaller of the outstanding need and that layer's
        `remaining_kg`, multiplying each take by the layer's
        `cost_per_kg_cents`, and accumulating integer cents with no rounding
        until the day's `feed_issued_kg` is fully covered; each layer's
        `remaining_kg` is reduced by what was taken."
        PRD §3.3: "A delivery's `remaining_kg` starts equal to `quantity_kg`,
        and its status is derived: `ACTIVE` while kilograms remain, flipping
        to `DEPLETED` when `remaining_kg` reaches zero."

        Design: Corner/calculations/feed_fifo_crosses_price_layers_in_delivery_order
        """
        ctx = setup_laying_flock()
        farm_id = ctx["farm"]["id"]
        flock_id = ctx["flock"]["id"]
        d1 = record_feed_delivery(
            farm_id, delivered_at="2026-07-01", quantity_kg=100, cost_per_kg_cents=50
        )
        d2 = record_feed_delivery(
            farm_id, delivered_at="2026-07-10", quantity_kg=100, cost_per_kg_cents=60
        )

        (pd,) = record_production_days(
            flock_id,
            [
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 100,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 150,
                    "mortality_count": 0,
                }
            ],
        )
        assert pd["feed_cost_cents"] == 8000, (
            f"150 kg FIFO = 100 x 50c + 50 x 60c = 8000c, got "
            f"{pd['feed_cost_cents']}"
        )

        d1_after = get_feed_delivery(d1["id"])
        assert d1_after["remaining_kg"] == 0
        assert d1_after["status"] == "DEPLETED"
        d2_after = get_feed_delivery(d2["id"])
        assert d2_after["remaining_kg"] == 50
        assert d2_after["status"] == "ACTIVE"

    def test_feed_issuance_beyond_stock_rejected(self, api):
        """PRD §3.3: "If the farm's total remaining stock across the queue is
        less than `feed_issued_kg`, the creation is rejected outright with
        `ERR_FEED_STOCK_EXHAUSTED` (HTTP 422) and nothing is consumed."

        Design: Corner/validations/feed_issuance_beyond_stock_rejected
        """
        ctx = setup_laying_flock()
        d1 = record_feed_delivery(
            ctx["farm"]["id"],
            delivered_at="2026-07-01",
            quantity_kg=5000,
            cost_per_kg_cents=50,
        )
        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-07-31",
                "eggs_collected": 100,
                "rejected_eggs": 0,
                "feed_issued_kg": 6000,
                "mortality_count": 0,
            },
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FEED_STOCK_EXHAUSTED)
        assert get_feed_delivery(d1["id"])["remaining_kg"] == 5000, (
            "a rejected issuance must not partially consume the FIFO queue"
        )


class TestProductionDayShape:
    def test_production_day_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.3: "a `FarmManager` records one **ProductionDay** per date
        with `flock_id`, `lay_date`, `eggs_collected`, `rejected_eggs`,
        `feed_issued_kg`, and `mortality_count`."
        PRD §2.8: "Tier 5 is request schema — required fields present, types
        correct, enum values valid, integers within their stated bounds, dates
        well-formed, `period_start` not after `period_end`, and spread/margin
        consistency with the pricing model, else `ERR_VALIDATION` (HTTP 400)"

        Design: Corner/entities/production_day_missing_required_field_returns_invalid_request
        """
        ctx = setup_laying_flock()
        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-07-31",
                "eggs_collected": 100,
                "rejected_eggs": 2,
                "feed_issued_kg": 0,
            },
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_production_day_immutable_event_shape(self, api):
        """PRD §2.5: "A production day is an immutable event log entry: it
        carries `id` and `created_at` only, and both `updated_at` and
        `version` are absent from it."
        PRD §3.3: "Recording the day then updates the flock ledgers:
        `cumulative_eggs` grows by `eggs_collected`, `cumulative_mortality`
        grows by `mortality_count`, `current_hen_count` falls by
        `mortality_count`, `ungraded_egg_pool` grows by `eggs_collected` minus
        `rejected_eggs`, and the flock's `version` increments by 1."

        Design: Corner/entities/production_day_immutable_event_shape
        """
        ctx = setup_laying_flock()
        before = get_flock(ctx["flock"]["id"])
        (pd,) = record_production_days(
            ctx["flock"]["id"],
            [
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 100,
                    "rejected_eggs": 2,
                    "feed_issued_kg": 0,
                    "mortality_count": 0,
                }
            ],
        )
        fetched = validate_success(api.get_production_day(pd["id"], FARM_MANAGER))
        assert_production_day(fetched)  # asserts id/created_at present, version/updated_at absent

        after = get_flock(ctx["flock"]["id"])
        assert after["version"] == before["version"] + 1, (
            "the production-day ledger update must increment the flock version "
            f"by exactly 1 ({before['version']} -> {after['version']})"
        )

    def test_immediate_consistency_of_cascaded_writes(self, api):
        """PRD §3.3: "`hens_at_start` snapshots the flock's `current_hen_count`
        immediately before that record's mortality is applied."
        PRD §3.3: "`lay_rate_pct` is `eggs_collected` multiplied by 100 and
        divided by `hens_at_start`, rounded half-up to two decimal places —
        and reads exactly 0.00 when `hens_at_start` is zero."
        PRD §3.3: "Recording the day then updates the flock ledgers:
        `cumulative_eggs` grows by `eggs_collected`, `cumulative_mortality`
        grows by `mortality_count`, `current_hen_count` falls by
        `mortality_count`, `ungraded_egg_pool` grows by `eggs_collected` minus
        `rejected_eggs`, and the flock's `version` increments by 1."

        Design: Corner/consistency_model/immediate_consistency_of_cascaded_writes
        """
        ctx = setup_laying_flock()
        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-07-31",
                "eggs_collected": 240,
                "rejected_eggs": 12,
                "feed_issued_kg": 0,
                "mortality_count": 2,
            },
            FARM_MANAGER,
        )
        pd = validate_success(resp, 201)
        assert pd["hens_at_start"] == 1000
        assert pd["feed_cost_cents"] == 0
        assert pd["lay_rate_pct"] == pytest.approx(24.00), (
            f"240 / 1000 x 100 = 24.00, got {pd['lay_rate_pct']}"
        )

        flock = get_flock(ctx["flock"]["id"])
        assert flock["cumulative_eggs"] == 240
        assert flock["cumulative_mortality"] == 2
        assert flock["current_hen_count"] == 998
        assert flock["ungraded_egg_pool"] == 228, (
            f"pool must grow by 240 - 12 rejects = 228, got "
            f"{flock['ungraded_egg_pool']}"
        )


class TestProductionDayIntegrity:
    def test_duplicate_production_day_rejected(self, api):
        """PRD §3.3: "The `lay_date` must be on or after the flock's
        `placement_date` and not later than the clock date, and only one
        production day may exist per flock per date — a duplicate is rejected
        with `ERR_DUPLICATE_PRODUCTION_DAY` (HTTP 409)."

        Design: Corner/validations/duplicate_production_day_rejected
        """
        ctx = setup_laying_flock_with_production(
            [
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 100,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 0,
                    "mortality_count": 0,
                }
            ]
        )
        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-07-31",
                "eggs_collected": 120,
                "rejected_eggs": 1,
                "feed_issued_kg": 0,
                "mortality_count": 0,
            },
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRODUCTION_DAY)
        assert get_flock(ctx["flock"]["id"])["cumulative_eggs"] == 100, (
            "the rejected duplicate must not add eggs to the ledger"
        )

    def test_mortality_beyond_hen_count_rejected(self, api):
        """PRD §3.3: "`mortality_count` is the dead hens removed that day,
        zero or more and no more than the flock's `current_hen_count`, else
        `ERR_HEN_COUNT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/mortality_beyond_hen_count_rejected
        """
        ctx = setup_laying_flock()
        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-07-31",
                "eggs_collected": 100,
                "rejected_eggs": 0,
                "feed_issued_kg": 0,
                "mortality_count": 1001,
            },
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HEN_COUNT_EXCEEDED)
        assert get_flock(ctx["flock"]["id"])["current_hen_count"] == 1000, (
            "the hen ledger must never go negative"
        )
