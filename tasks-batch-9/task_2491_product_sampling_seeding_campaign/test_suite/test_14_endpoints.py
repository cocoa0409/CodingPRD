"""Endpoint surfaces: computed reads, bulk actions, round trips and links."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import ERR_INVALID_SHIPMENT_STATE
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)
DOUBLE_STOCKED_KIT = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 20),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 40),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 20),
)
CLUSTER_ADDRESS = "H-RS"
CLUSTER_OPENED_AT = "2026-07-25T00:00:00Z"
LATER_INSTANT = "2026-08-09T12:30:00Z"


class TestCostSummaryRead:
    """The dedicated cost read, checked against the stored ledger."""

    def test_the_summary_reports_both_variants_and_the_budget_triple(self, api):
        """PRD §3.6: "A dedicated cost read exposes both figures side by side
        together with the budget triple, returning `campaign_id`,
        `kit_assembly_unit_cost_cents`, `cost_per_sample_provisional_cents`,
        `cost_per_sample_final_cents`, `budget_total_cents`,
        `budget_committed_cents`, `budget_available_cents`,
        `allocated_sample_count`, `delivered_sample_count` and
        `write_off_cost_cents`, so that the budget conservation identity of §2.7
        can be checked directly against the cost figures derived from it."

        Design: Corner/endpoints/cost_summary_read_reports_both_variants_and_the_budget_pair
        """
        world = fx.delivered_sample_world(
            api, panelist_count=1, surcharges=[0], name="Cost Summary"
        )

        summary = validate_success(
            api.get_campaign_cost_summary(campaign_manager_headers(), world.campaign_id)
        )

        assert summary["campaign_id"] == world.campaign_id
        assert summary["kit_assembly_unit_cost_cents"] == 454
        assert summary["cost_per_sample_provisional_cents"] == 754
        assert summary["cost_per_sample_final_cents"] == 754
        assert summary["budget_total_cents"] == 1000000
        assert summary["budget_committed_cents"] == 754
        assert summary["budget_available_cents"] == 999246
        assert summary["allocated_sample_count"] == 1
        assert summary["delivered_sample_count"] == 1
        assert summary["write_off_cost_cents"] == 0


class TestWaveReleaseAsABulkAction:
    """One release call standing in for every shipment in the wave."""

    def test_both_allocated_shipments_ship_on_the_same_call(self, api):
        """PRD §3.6: "Every shipment of the released wave still in `ALLOCATED`
        moves to `SHIPPED` with `shipped_at` stamped from the logical clock; each
        such shipment's mapped units move from `units_reserved` to `units_shipped`
        on every kit line named in its `reserved_line_units`, with each line's
        `version` increased by 1; the wave's `shipped_unit_count` takes on the
        units that just shipped while its `planned_unit_count` returns to zero;
        and each affected enrollment's obligation axis advances `NONE →
        SAMPLE_SENT`."

        PRD §3.6: "Shipping is a batch event by design, which is why there is no
        per-shipment ship request anywhere in the API."

        Design: Corner/endpoints/wave_release_is_a_bulk_action_over_every_allocated_shipment
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=2,
            surcharges=[0, 0],
            kit_specs=DOUBLE_STOCKED_KIT,
            name="Bulk Release",
        )
        fx.lock_wave(api, world.wave_id)

        released = validate_success(
            api.release_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )

        assert released["status"] == "RELEASED"
        assert released["shipped_unit_count"] == 8
        assert released["planned_unit_count"] == 0

        for index in (0, 1):
            shipment = fx.get_shipment(api, world.shipment_id(index))
            assert shipment["status"] == "SHIPPED"
            assert_instant(shipment["shipped_at"], "2026-08-01T00:00:00Z")

        expected_shipped = {0: 2, 1: 4, 2: 2}
        for index, units in expected_shipped.items():
            line = fx.get_kit_line(api, world.kit_line_id(index))
            assert line["units_reserved"] == 0
            assert line["units_shipped"] == units

        for index in (0, 1):
            enrollment = fx.get_enrollment(api, world.enrollment_id(index))
            assert enrollment["obligation_status"] == "SAMPLE_SENT"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["cost_per_sample_provisional_cents"] == 754
        assert campaign["delivered_sample_count"] == 0


class TestOnDemandRiskRescore:
    """The variant argument selects which risk column is written."""

    def test_the_audit_call_leaves_the_screening_column_alone(self, api):
        """PRD §3.3: "The address term is multiplied by 1.5 before summation, and
        two additional terms join."

        PRD §3.3: "And a `ComplianceModerator` may rescore a panelist on demand
        without touching any enrollment, supplying a `variant` field that is
        either `SCREENING` or `AUDIT` to select which score is refreshed."

        PRD §3.3: "Every scoring, whatever its trigger, stamps
        `last_risk_scored_at` with the logical clock's current instant and
        increases the panelist's `version` by 1."

        PRD §3.3: "A new panelist starts `CLEAR` with `diversion_strikes` at zero,
        `fraud_risk_score_screening` at 0.0, `fraud_risk_score_audit` unset until
        an audit rescore first runs, and `last_risk_scored_at` unset until the
        first scoring of any kind."

        Design: Corner/endpoints/risk_rescore_writes_only_the_variant_named_in_the_payload
        """
        cluster = fx.address_cluster_panelists(
            api, 4, address_hash=CLUSTER_ADDRESS, account_opened_at=CLUSTER_OPENED_AT
        )
        screened = fx.rescore_panelist(api, cluster[0]["id"], "SCREENING")
        assert screened["fraud_risk_score_screening"] == 40.0

        audited = validate_success(
            api.rescore_panelist_risk(
                moderator_a_headers(), cluster[0]["id"], variant="AUDIT"
            )
        )

        assert audited["fraud_risk_score_screening"] == 40.0
        assert audited["fraud_risk_score_audit"] == 49.0
        assert audited["integrity_status"] == "CLEAR"
        assert_instant(audited["last_risk_scored_at"], "2026-08-01T00:00:00Z")

        untouched = fx.get_panelist(api, cluster[1]["id"])
        assert untouched["fraud_risk_score_screening"] == 0.0
        assert untouched["fraud_risk_score_audit"] is None


class TestLogicalClockEndpoint:
    """The clock drives every stamp and mutates nothing itself."""

    def test_rows_created_either_side_of_a_clock_move_carry_both_instants(self, api):
        """PRD §2.4: "The logical clock's startup value is exactly
        `2026-08-01T00:00:00Z`, and until it is explicitly moved it reads that
        value — it must never fall back to real wall-clock time."

        PRD §2.4: "A `PlatformAdmin` may reposition it through an administrative
        test-driving capability that takes a single field, `to_iso8601`, carrying
        the target ISO 8601 UTC instant, and returns the resulting clock reading
        as `current_utc`. Repositioning the clock mutates no entity."

        PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits recording when the row was first
        written."

        Design: Corner/endpoints/logical_clock_endpoint_drives_every_created_at_stamp
        """
        campaign = fx.create_campaign(api, name="Clock One")

        moved = validate_success(
            api.set_clock(platform_admin_headers(), to_iso8601=LATER_INSTANT)
        )
        assert_instant(moved["current_utc"], LATER_INSTANT, "current_utc")

        line = validate_success(
            api.create_kit_line(
                campaign_manager_headers(),
                campaign_id=campaign["id"],
                component_sku="HERO-1",
                component_role="HERO_PRODUCT",
                unit_cost_cents=1417,
                quantity_per_kit=1,
                component_discount_pct=0.8,
            ),
            201,
        )

        assert_instant(campaign["created_at"], "2026-08-01T00:00:00Z", "campaign.created_at")
        assert_instant(line["created_at"], LATER_INSTANT, "kit_line.created_at")

        stored = fx.get_campaign(api, campaign["id"])
        assert stored["status"] == "DRAFT"


class TestDeliveryPrecondition:
    """Delivery is reachable only through a wave release."""

    def test_delivering_straight_out_of_allocated_is_refused(self, api):
        """PRD §3.6: "Delivery and loss are the two outcomes of a `SHIPPED`
        shipment, and both are terminal."

        PRD §3.6: "A shipment that is not `SHIPPED` is refused with
        `ERR_INVALID_SHIPMENT_STATE` on either request."

        Design: Corner/endpoints/delivery_is_only_allowed_after_the_wave_has_been_released
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            name="Early Deliver",
        )

        validate_error(
            api.deliver_sample_shipment(
                fulfillment_ops_headers(), world.shipment_id(0)
            ),
            ERR_INVALID_SHIPMENT_STATE,
            409,
        )

        shipment = fx.get_shipment(api, world.shipment_id(0))
        assert shipment["status"] == "ALLOCATED"
        assert shipment["delivered_at"] is None
        assert shipment["shipped_at"] is None

        wave = fx.get_wave(api, world.wave_id)
        assert wave["status"] == "PLANNED"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["delivered_sample_count"] == 0
        assert campaign["cost_per_sample_final_cents"] == 0

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "NONE"


class TestRetailerRoundTrip:
    """A retailer created from its name alone, then read back."""

    def test_the_four_policy_defaults_survive_the_round_trip(self, api):
        """PRD §3.8: "A retailer is registered with a `name` and four policy
        fields, all optional with defaults: `feed_status`, either `ACCEPTING` or
        `PAUSED` and defaulting to `ACCEPTING`; `requires_disclosure_badge`,
        defaulting to true, meaning this retailer insists on the badge wording
        rather than any disclosure; `min_star_rating_accepted`, from 1 through 5
        and defaulting to 1, the lowest rating the feed will carry; and
        `max_reviews_per_panelist_per_month`, at least 1 and defaulting to 1, the
        retailer's anti-astroturfing rate limit on how often one panelist may
        appear."

        Design: Corner/endpoints/retailer_create_then_read_round_trips_the_policy_defaults
        """
        created = validate_success(
            api.create_retailer(platform_admin_headers(), name="Default Policy Retailer"),
            201,
        )

        assert created["name"] == "Default Policy Retailer"
        assert created["feed_status"] == "ACCEPTING"
        assert created["requires_disclosure_badge"] is True
        assert created["min_star_rating_accepted"] == 1
        assert created["max_reviews_per_panelist_per_month"] == 1
        assert created["version"] == 1
        assert_instant(created["created_at"], "2026-08-01T00:00:00Z", "created_at")

        read_back = validate_success(
            api.get_retailer(platform_admin_headers(), created["id"])
        )
        assert read_back == created


class TestSyndicationRecordLink:
    """The junction row and its two list filters."""

    def test_the_record_names_both_sides_and_is_findable_by_retailer(self, api):
        """PRD §3.8: "First a `CampaignManager` or `FulfillmentOps` queues a
        record by naming the `review_submission_id` and the `retailer_id`."

        PRD §3.8: "The record is created `QUEUED` with `rejection_reason`,
        `syndicated_at` and `takedown_requested_at` all unset."

        Design: Corner/endpoints/syndication_record_links_an_existing_review_to_an_existing_retailer
        """
        bundle = fx.approved_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            objective_type="REVIEW_ACQUISITION",
            retailer_overrides={"name": "Link Retailer"},
            name="Link Campaign",
        )

        record = validate_success(
            api.create_syndication_record(
                campaign_manager_headers(),
                review_submission_id=bundle["review"]["id"],
                retailer_id=bundle["retailer"]["id"],
            ),
            201,
        )

        assert record["review_submission_id"] == bundle["review"]["id"]
        assert record["retailer_id"] == bundle["retailer"]["id"]
        assert record["status"] == "QUEUED"
        assert record["syndicated_at"] is None
        assert record["rejection_reason"] is None
        assert record["takedown_requested_at"] is None

        rows, meta = validate_paginated(
            api.list_syndication_records(
                campaign_manager_headers(), retailer_id=bundle["retailer"]["id"]
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == record["id"]

        campaign = fx.get_campaign(api, bundle["world"].campaign_id)
        assert campaign["syndicated_review_count"] == 0
