"""Entity shape: declared fields, defaults, computed values and foreign keys."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    NOBODY_USER_ID,
    assert_immutable_entity_shape,
    campaign_manager_headers,
    moderator_a_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import (
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SHIPMENT_NOT_FOUND,
)

# A syntactically valid UUID that no row was ever created with.
ABSENT_UUID = NOBODY_USER_ID

WINDOW_START = "2026-07-01T00:00:00Z"
WINDOW_END = "2026-09-30T00:00:00Z"


class TestCampaignCreation:
    """The campaign row a definition request produces."""

    def test_creation_returns_every_declared_field_with_its_seeded_default(self, api):
        """PRD §3.1: "A campaign is born in `DRAFT` with `compliance_posture`
        `OPEN`, with `budget_available_cents` seeded to the full
        `budget_total_cents` and `budget_committed_cents` at zero, with every
        derived counter at zero, with `kit_assembly_unit_cost_cents` at zero, and
        with `launched_by_user_id` and `closed_at` both unset."

        Design: Corner/entities/campaign_creation_returns_the_full_declared_field_set
        """
        campaign = validate_success(
            api.create_campaign(
                campaign_manager_headers(),
                name="Full Field Campaign",
                objective_type="REVIEW_ACQUISITION",
                target_segment_codes=["URBAN_MILLENNIAL", "SUBURBAN_PARENT"],
                syndication_retailer_ids=[],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_END,
                budget_total_cents=1000000,
                review_due_days=21,
                min_review_word_count=10,
                holdout_pct=0.0,
            ),
            201,
        )

        assert campaign["name"] == "Full Field Campaign"
        assert campaign["objective_type"] == "REVIEW_ACQUISITION"
        assert campaign["target_segment_codes"] == [
            "URBAN_MILLENNIAL",
            "SUBURBAN_PARENT",
        ]
        assert campaign["budget_total_cents"] == 1000000
        assert campaign["status"] == "DRAFT"
        assert campaign["compliance_posture"] == "OPEN"
        assert campaign["kit_assembly_unit_cost_cents"] == 0
        assert campaign["budget_committed_cents"] == 0
        assert campaign["budget_available_cents"] == 1000000
        assert campaign["enrollment_count"] == 0
        assert campaign["holdout_enrollment_count"] == 0
        assert campaign["allocated_sample_count"] == 0
        assert campaign["delivered_sample_count"] == 0
        assert campaign["approved_review_count"] == 0
        assert campaign["syndicated_review_count"] == 0
        assert campaign["disclosure_rejected_review_count"] == 0
        assert campaign["substantiated_diversion_count"] == 0
        assert campaign["write_off_cost_cents"] == 0
        assert campaign["cost_per_sample_provisional_cents"] == 0
        assert campaign["cost_per_sample_final_cents"] == 0
        assert campaign["launched_by_user_id"] is None
        assert campaign["closed_at"] is None

    def test_the_four_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """PRD §3.1: "`review_due_days` sets how long after delivery a panelist
        owes their review and defaults to three weeks — 21 days — with any value
        from 1 through 90 accepted. `min_review_word_count` sets the
        campaign-level floor on review length and defaults to 50 words, accepting
        10 through 500. `holdout_pct` is the fraction of screened enrollments
        deliberately withheld from sampling so that lift can be measured against
        them; it defaults to one fifth, expressed as 0.2, and may be anywhere
        from 0 through 0.5 inclusive with at most four decimal places."

        Design: Corner/entities/campaign_omitted_optional_inputs_take_their_declared_defaults
        """
        campaign = validate_success(
            api.create_campaign(
                campaign_manager_headers(),
                name="Defaults Only",
                objective_type="AWARENESS",
                target_segment_codes=["URBAN_MILLENNIAL"],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_END,
                budget_total_cents=1000000,
            ),
            201,
        )

        assert campaign["review_due_days"] == 21
        assert campaign["min_review_word_count"] == 50
        assert campaign["holdout_pct"] == 0.2
        assert campaign["syndication_retailer_ids"] == []
        assert campaign["status"] == "DRAFT"

    def test_an_objective_type_outside_the_closed_set_is_rejected(self, api):
        """PRD §3.1: "The declaration carries a `name` — non-empty and at most 160
        characters — and an `objective_type` naming the primary sampling
        objective, which is exactly one of `TRIAL_GENERATION`,
        `REVIEW_ACQUISITION` or `AWARENESS`."

        PRD §2.5: "The request body carries every required input field, every
        supplied value matches its declared type, enum membership and permitted
        range, no unknown field is present, and `limit` and `offset` are inside
        their permitted ranges — otherwise `ERR_INVALID_REQUEST` (400). Applies
        to every endpoint."

        Design: Corner/entities/campaign_rejects_an_unknown_objective_type_enum_member
        """
        validate_error(
            api.create_campaign(
                campaign_manager_headers(),
                name="Bad Enum",
                objective_type="BRAND_LOVE",
                target_segment_codes=["URBAN_MILLENNIAL"],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_END,
                budget_total_cents=1000000,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0


class TestPanelistRetrieval:
    """The panelist row a sign-up produces, read back by id."""

    def test_a_fresh_panelist_reads_back_with_its_untouched_risk_fields(self, api):
        """PRD §3.3: "A new panelist starts `CLEAR` with `diversion_strikes` at
        zero, `fraud_risk_score_screening` at 0.0, `fraud_risk_score_audit` unset
        until an audit rescore first runs, and `last_risk_scored_at` unset until
        the first scoring of any kind."

        Design: Corner/entities/panelist_retrieval_returns_the_stored_row
        """
        created = validate_success(
            api.create_panelist(
                platform_admin_headers(),
                email="read.back@example.com",
                display_name="Read Back",
                address_hash="H-RB1",
                account_opened_at="2026-01-01T00:00:00Z",
                segment_code="URBAN_MILLENNIAL",
            ),
            201,
        )

        panelist = validate_success(
            api.get_panelist(platform_admin_headers(), created["id"])
        )

        assert panelist["email"] == "read.back@example.com"
        assert panelist["display_name"] == "Read Back"
        assert panelist["address_hash"] == "H-RB1"
        assert panelist["segment_code"] == "URBAN_MILLENNIAL"
        assert panelist["referred_by_panelist_id"] is None
        assert panelist["integrity_status"] == "CLEAR"
        assert panelist["diversion_strikes"] == 0
        assert panelist["fraud_risk_score_screening"] == 0.0
        assert panelist["fraud_risk_score_audit"] is None
        assert panelist["last_risk_scored_at"] is None


class TestCampaignListing:
    """Pagination metadata and the equality filter on the campaign list."""

    @staticmethod
    def _three_campaigns_one_of_them_open(api):
        """Three campaigns, only the first of which has opened screening."""
        manager = campaign_manager_headers()
        first = validate_success(
            api.create_campaign(
                manager,
                name="List One",
                objective_type="TRIAL_GENERATION",
                target_segment_codes=["URBAN_MILLENNIAL"],
                syndication_retailer_ids=[],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_END,
                budget_total_cents=1000000,
                review_due_days=21,
                min_review_word_count=10,
                holdout_pct=0.0,
            ),
            201,
        )
        validate_success(
            api.create_kit_line(
                manager,
                campaign_id=first["id"],
                component_sku="HERO-1",
                component_role="HERO_PRODUCT",
                unit_cost_cents=1417,
                quantity_per_kit=1,
                component_discount_pct=0.8,
            ),
            201,
        )
        validate_success(api.open_screening(manager, first["id"]))
        for name in ("List Two", "List Three"):
            validate_success(
                api.create_campaign(
                    manager,
                    name=name,
                    objective_type="AWARENESS",
                    target_segment_codes=["URBAN_MILLENNIAL"],
                    syndication_retailer_ids=[],
                    sampling_window_start=WINDOW_START,
                    sampling_window_end=WINDOW_END,
                    budget_total_cents=1000000,
                    review_due_days=21,
                    min_review_word_count=10,
                    holdout_pct=0.0,
                ),
                201,
            )
        return first

    def test_the_page_meta_counts_matches_before_the_page_is_cut(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the envelope's `meta` object, where `total_count` is
        the number of rows matching the request's filters before pagination is
        applied and `has_more` indicates whether any matching row remains beyond
        the returned page."

        Design: Corner/entities/campaign_listing_paginates_with_total_count_and_has_more
        """
        first = self._three_campaigns_one_of_them_open(api)
        manager = campaign_manager_headers()

        page, meta = validate_paginated(api.list_campaigns(manager, limit=2, offset=0))
        assert len(page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        tail, tail_meta = validate_paginated(
            api.list_campaigns(manager, limit=2, offset=2)
        )
        assert len(tail) == 1
        assert tail_meta["has_more"] is False

        filtered, filtered_meta = validate_paginated(
            api.list_campaigns(manager, status="SCREENING_OPEN")
        )
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False
        assert filtered[0]["id"] == first["id"]


class TestKitLineFields:
    """Per-line costing and the required-field gate on a kit line."""

    def test_each_line_rounds_its_own_extended_cost_and_the_campaign_sums_them(
        self, api
    ):
        """PRD §3.1: "Each line's `extended_cost_cents` is its `unit_cost_cents`
        multiplied by its `quantity_per_kit`, multiplied by one minus its
        `component_discount_pct`, and that product is rounded half-up to a whole
        cent **on the line**. The campaign's `kit_assembly_unit_cost_cents` is
        then the plain sum of those already-rounded line values, taken over the
        campaign's `ACTIVE` lines only and evaluated in order of `created_at`
        ascending with `component_sku` ascending as the tie-break."

        Design: Corner/entities/kit_line_extended_cost_cents_is_computed_per_line
        """
        manager = campaign_manager_headers()
        campaign = fx.create_campaign(api, name="Computed Lines")

        hero = validate_success(
            api.create_kit_line(
                manager,
                campaign_id=campaign["id"],
                component_sku="HERO-1",
                component_role="HERO_PRODUCT",
                unit_cost_cents=1417,
                quantity_per_kit=1,
                component_discount_pct=0.8,
            ),
            201,
        )
        accessory = validate_success(
            api.create_kit_line(
                manager,
                campaign_id=campaign["id"],
                component_sku="ACC-2",
                component_role="ACCESSORY",
                unit_cost_cents=388,
                quantity_per_kit=2,
                component_discount_pct=0.85,
            ),
            201,
        )
        insert = validate_success(
            api.create_kit_line(
                manager,
                campaign_id=campaign["id"],
                component_sku="INS-3",
                component_role="INSERT_CARD",
                unit_cost_cents=554,
                quantity_per_kit=1,
                component_discount_pct=0.9,
            ),
            201,
        )
        undiscounted = validate_success(
            api.create_kit_line(
                manager,
                campaign_id=campaign["id"],
                component_sku="DISC-4",
                component_role="DISCLOSURE_INSERT",
                unit_cost_cents=40,
                quantity_per_kit=1,
            ),
            201,
        )

        assert hero["extended_cost_cents"] == 283
        assert accessory["extended_cost_cents"] == 116
        assert insert["extended_cost_cents"] == 55
        assert undiscounted["component_discount_pct"] == 0
        assert undiscounted["extended_cost_cents"] == 40

        assert hero["status"] == "ACTIVE"
        assert hero["units_received"] == 0
        assert hero["units_available"] == 0
        assert hero["units_reserved"] == 0
        assert hero["units_shipped"] == 0
        assert hero["units_written_off"] == 0

        refreshed = fx.get_campaign(api, campaign["id"])
        assert refreshed["kit_assembly_unit_cost_cents"] == 494

    def test_a_kit_line_without_its_component_sku_is_refused(self, api):
        """PRD §2.5: "The request body carries every required input field, every
        supplied value matches its declared type, enum membership and permitted
        range, no unknown field is present, and `limit` and `offset` are inside
        their permitted ranges — otherwise `ERR_INVALID_REQUEST` (400). Applies
        to every endpoint."

        Design: Corner/entities/kit_line_missing_required_component_sku_is_rejected
        """
        campaign = fx.create_campaign(api, name="Missing Field")

        validate_error(
            api.raw_post(
                "/kit-lines",
                {
                    "campaign_id": campaign["id"],
                    "component_role": "HERO_PRODUCT",
                    "unit_cost_cents": 1417,
                    "quantity_per_kit": 1,
                },
                campaign_manager_headers(),
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        refreshed = fx.get_campaign(api, campaign["id"])
        assert refreshed["kit_assembly_unit_cost_cents"] == 0

        _, meta = validate_paginated(
            api.list_kit_lines(campaign_manager_headers(), campaign_id=campaign["id"])
        )
        assert meta["total_count"] == 0


class TestPurchaseMatchImmutability:
    """The one entity family that carries neither version nor updated_at."""

    def test_an_ingested_match_exposes_no_version_and_no_updated_at(self, api):
        """PRD §2.4: "Purchase-match rows are the one exception: a purchase match
        is immutable once ingested and therefore carries only `id` and
        `created_at`. Both `updated_at` and `version` are absent from a purchase
        match."

        PRD §3.9: "The stored `qualified` flag is derived, not supplied: it is
        true when the `match_confidence` is at least 0.8 and the `purchased_at`
        instant lies inside that same conversion window."

        Design: Corner/entities/purchase_match_is_immutable_and_carries_no_version
        """
        world = fx.screening_open_campaign(
            api,
            kit_specs=(fx.KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 0),),
            name="Immutable Match",
        )
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        fx.screen_enrollment(api, enrollment["id"])

        validate_success(
            api.create_purchase_match(
                platform_admin_headers(),
                enrollment_id=enrollment["id"],
                retailer_channel_code="WEB-US",
                purchase_amount_cents=5000,
                purchased_at="2026-08-01T00:00:00Z",
                match_confidence=0.9,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_enrollment_purchase_matches(
                platform_admin_headers(), enrollment["id"]
            )
        )
        assert meta["total_count"] == 1
        match = rows[0]
        assert match["enrollment_id"] == enrollment["id"]
        assert match["retailer_channel_code"] == "WEB-US"
        assert match["purchase_amount_cents"] == 5000
        assert match["match_confidence"] == 0.9
        assert match["qualified"] is True
        assert_immutable_entity_shape(match)


class TestIdentifierResolution:
    """Path identifiers and body foreign keys that resolve to nothing."""

    def test_an_unknown_campaign_id_in_the_path_answers_not_found(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        Design: Corner/entities/campaign_not_found_on_unknown_uuid
        """
        validate_error(
            api.get_campaign(campaign_manager_headers(), ABSENT_UUID),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )

    def test_a_kit_line_whose_parent_campaign_does_not_exist_answers_not_found(
        self, api
    ):
        """PRD §2.5: "Every foreign key in the request body resolves to an
        existing row, checked in input-list order — otherwise the matching
        not-found code from §2.4 (404). Applies to every endpoint with foreign
        keys in its input."

        Design: Corner/entities/kit_line_with_unknown_parent_campaign_not_found
        """
        validate_error(
            api.create_kit_line(
                campaign_manager_headers(),
                campaign_id=ABSENT_UUID,
                component_sku="HERO-1",
                component_role="HERO_PRODUCT",
                unit_cost_cents=1417,
                quantity_per_kit=1,
                component_discount_pct=0.8,
            ),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_kit_lines(campaign_manager_headers()))
        assert meta["total_count"] == 0

    def test_body_foreign_keys_are_swept_in_input_list_order(self, api):
        """PRD §2.4: "The same codes are used when a foreign key supplied in a
        request body fails to resolve; body foreign keys are checked in the order
        the fields appear in the endpoint's input list, and the members of
        `syndication_retailer_ids` are checked left to right within that array."

        Design: Corner/entities/diversion_case_body_fks_validated_left_to_right_shipment_not_found
        """
        panelist = fx.create_panelist(api, display_name="FK One")

        validate_error(
            api.create_diversion_case(
                moderator_a_headers(),
                panelist_id=panelist["id"],
                sample_shipment_id=ABSENT_UUID,
                signal_type="RESALE_LISTING",
                evidence_note="Listing observed on a resale marketplace.",
            ),
            ERR_SHIPMENT_NOT_FOUND,
            404,
        )

        stored = fx.get_panelist(api, panelist["id"])
        assert stored["integrity_status"] == "CLEAR"

        _, meta = validate_paginated(
            api.list_diversion_cases(moderator_a_headers(), panelist_id=panelist["id"])
        )
        assert meta["total_count"] == 0
