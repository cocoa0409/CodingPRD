"""The validation ladder: which rule answers when several are broken at once."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    NOBODY_USER_ID,
    campaign_manager_headers,
    fulfillment_ops_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import (
    ERR_CAMPAIGN_BUDGET_EXHAUSTED,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_WINDOW_INVALID,
    ERR_DISCLOSURE_STATEMENT_MISSING,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_DUPLICATE_SYNDICATION_TARGET,
    ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW,
    ERR_FORBIDDEN_ROLE,
    ERR_HOLDOUT_ENROLLMENT_NOT_SAMPLEABLE,
    ERR_HONEST_OPINION_NOT_ATTESTED,
    ERR_PURCHASE_MATCH_OUT_OF_WINDOW,
    ERR_RETAILER_NOT_IN_CAMPAIGN,
    ERR_WAVE_CAPACITY_EXCEEDED,
    ERR_WAVE_WINDOW_INVALID,
    ERR_WRITE_OFF_EXCEEDS_AVAILABLE,
)
from test_helpers.fixtures import KitSpec


ABSENT_UUID = NOBODY_USER_ID
WINDOW_START = "2026-07-01T00:00:00Z"
WINDOW_END = "2026-09-30T00:00:00Z"

SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)
SHORT_ACCESSORY_KIT = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 1),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 10),
)

FIVE_WORD_BODY = "Great kit, loved everything inside."
FIFTEEN_WORD_BODY = (
    "The hero product worked well for my family and the insert card "
    "explained everything clearly."
)
PREMATURE_BODY = (
    "I have not received the kit yet but here are my expectations for it anyway."
)
NON_CONFORMING_DISCLOSURE = "The brand gave me this item."
BADGE_DISCLOSURE = "I received this product for free from the brand."


class TestWindowRules:
    """The two creation-time window rules, each with its own error code."""

    def test_a_zero_width_campaign_window_is_refused(self, api):
        """PRD §2.5: "On campaign creation, `sampling_window_end` is strictly
        later than `sampling_window_start` — otherwise
        `ERR_CAMPAIGN_WINDOW_INVALID` (400)."

        Design: Corner/validations/campaign_window_end_equal_to_start_is_rejected
        """
        validate_error(
            api.create_campaign(
                campaign_manager_headers(),
                name="Zero Width Window",
                objective_type="TRIAL_GENERATION",
                target_segment_codes=["URBAN_MILLENNIAL"],
                syndication_retailer_ids=[],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_START,
                budget_total_cents=1000000,
            ),
            ERR_CAMPAIGN_WINDOW_INVALID,
            400,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0

    def test_a_reversed_wave_window_is_refused(self, api):
        """PRD §2.5: "On fulfilment-wave creation, `window_end` is strictly later
        than `window_start` — otherwise `ERR_WAVE_WINDOW_INVALID` (400)."

        PRD §3.5: "A wave whose `window_end` is not strictly after its
        `window_start` is refused with `ERR_WAVE_WINDOW_INVALID`."

        Design: Corner/validations/wave_window_end_before_start_is_rejected
        """
        center = fx.create_center(api, name="FC Window", zone_code="EAST")

        validate_error(
            api.create_fulfillment_wave(
                fulfillment_ops_headers(),
                fulfillment_center_id=center["id"],
                window_start="2026-08-03T00:00:00Z",
                window_end="2026-08-02T00:00:00Z",
                planned_capacity_units=50,
            ),
            ERR_WAVE_WINDOW_INVALID,
            400,
        )

        _, meta = validate_paginated(
            api.list_fulfillment_waves(
                fulfillment_ops_headers(), fulfillment_center_id=center["id"]
            )
        )
        assert meta["total_count"] == 0


class TestRungOrderAtTheTopOfTheLadder:
    """Role, existence and transition legality, in that order."""

    def test_an_unknown_path_id_answers_before_the_transition_rule(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        PRD §2.5: "The target resource is in a state from which the requested
        transition is declared — otherwise the state code for that resource family
        (409)"

        Design: Corner/validations/unknown_campaign_id_beats_the_state_check_on_close
        """
        real = fx.create_campaign(api, name="Real Draft")

        validate_error(
            api.close_campaign(campaign_manager_headers(), ABSENT_UUID),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )

        stored = fx.get_campaign(api, real["id"])
        assert stored["status"] == "DRAFT"

    def test_the_role_rule_answers_before_the_id_is_ever_resolved(self, api):
        """PRD §2.5: "The named role is among the roles authorised for the called
        endpoint — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
        endpoint."

        PRD §2.5: "Every request is validated against one global, strictly ordered
        ladder of rules, and **the first rule that fails determines the
        response**: no later rule is evaluated, and no later rule's error code can
        appear once an earlier rule has rejected the request."

        Design: Corner/validations/wrong_role_beats_existence_on_an_unknown_campaign
        """
        validate_error(
            api.close_campaign(fulfillment_ops_headers(), ABSENT_UUID),
            ERR_FORBIDDEN_ROLE,
            403,
        )


class TestWriteOffCeiling:
    """The write-off ceiling is what is on hand, not what ever arrived."""

    def test_a_write_off_one_unit_over_the_available_stock_is_refused(self, api):
        """PRD §3.5: "A write-off may never exceed what is on hand: a request for
        more than `units_available` is refused with
        `ERR_WRITE_OFF_EXCEEDS_AVAILABLE`."

        PRD §2.5: "The requested write-off count does not exceed the kit line's
        `units_available` — otherwise `ERR_WRITE_OFF_EXCEEDS_AVAILABLE` (422)."

        Design: Corner/validations/write_off_of_more_units_than_available_is_rejected
        """
        campaign = fx.create_campaign(api, name="Write Off Ceiling")
        line = fx.add_kit_line(
            api,
            campaign["id"],
            component_sku="HERO-1",
            component_role="HERO_PRODUCT",
            unit_cost_cents=1417,
            quantity_per_kit=1,
            component_discount_pct=0.8,
        )
        fx.receive_units(api, line["id"], 3)

        validate_error(
            api.record_kit_line_write_off(
                fulfillment_ops_headers(), line["id"], 4, "DAMAGED_IN_TRANSIT"
            ),
            ERR_WRITE_OFF_EXCEEDS_AVAILABLE,
            422,
        )

        stored = fx.get_kit_line(api, line["id"])
        assert stored["units_written_off"] == 0
        assert stored["units_available"] == 3
        assert stored["units_received"] == 3

        assert fx.get_campaign(api, campaign["id"])["write_off_cost_cents"] == 0


class TestConversionWindowTail:
    """One second past the inclusive tail of the conversion window."""

    def test_a_purchase_one_second_late_is_refused(self, api):
        """PRD §3.9: "The purchase must fall inside the campaign's conversion
        window — from the campaign's `sampling_window_start` through its
        `sampling_window_end` plus 30 days, inclusive at both ends — and one
        outside it is refused with `ERR_PURCHASE_MATCH_OUT_OF_WINDOW`."

        PRD §2.5: "`purchased_at` falls inside the campaign's conversion window —
        otherwise `ERR_PURCHASE_MATCH_OUT_OF_WINDOW` (422). Applies to
        purchase-match ingestion."

        Design: Corner/validations/purchase_one_second_past_the_conversion_tail_is_rejected
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Tail Plus One"
        )
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])

        validate_error(
            api.create_purchase_match(
                platform_admin_headers(),
                enrollment_id=enrollment["id"],
                retailer_channel_code="CH-LATE",
                purchase_amount_cents=1999,
                purchased_at="2026-10-30T00:00:01Z",
                match_confidence=0.95,
            ),
            ERR_PURCHASE_MATCH_OUT_OF_WINDOW,
            422,
        )

        _, meta = validate_paginated(
            api.list_enrollment_purchase_matches(
                platform_admin_headers(), enrollment["id"]
            )
        )
        assert meta["total_count"] == 0


class TestReviewGateOrder:
    """The four content gates of submission, in their pinned order."""

    @staticmethod
    def _delivered_world(api, name):
        """A delivered sample whose enrollment owes a review at a ten-word floor."""
        return fx.delivered_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            objective_type="REVIEW_ACQUISITION",
            name=name,
        )

    def test_an_undelivered_sample_blocks_the_submission_but_not_the_draft(self, api):
        """PRD §3.7: "Drafting deliberately enforces almost nothing beyond field
        validity, ownership and the campaign being in `SAMPLING_ACTIVE` or
        `REVIEW_WINDOW` — **obligation eligibility is checked at submission, not
        at drafting**, so a panelist may compose a review before their sample is
        confirmed delivered."

        PRD §3.7: "the enrollment's `obligation_status` is `REVIEW_DUE`, otherwise
        `ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW`, which is what stops a panelist
        reviewing a sample that was never delivered;"

        Design: Corner/validations/submitting_before_the_sample_is_delivered_is_rejected
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            objective_type="REVIEW_ACQUISITION",
            min_review_word_count=10,
            name="Premature Review",
        )
        draft = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Too early",
            body_text=PREMATURE_BODY,
            star_rating=4,
            disclosure_statement="Sample provided by the brand at no cost.",
            honest_opinion_attested=True,
        )
        assert draft["word_count"] == 15

        validate_error(
            api.submit_review(world.panelist_headers(0), draft["id"]),
            ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW,
            422,
        )

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "NONE"
        assert enrollment["screening_status"] == "SCREEN_PASSED"

        stored = fx.get_review(api, draft["id"])
        assert stored["status"] == "DRAFT"
        assert stored["first_submitted_at"] is None

    def test_the_missing_attestation_answers_before_disclosure_and_length(self, api):
        """PRD §3.7: "Beyond the ladder's earlier rungs — the review must be
        `DRAFT` (`ERR_INVALID_REVIEW_STATE`), the caller must own it
        (`ERR_NOT_RESOURCE_OWNER`), the panelist must not be `BANNED`
        (`ERR_PANELIST_BANNED`) and the campaign must be `SAMPLING_ACTIVE` or
        `REVIEW_WINDOW` (`ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS`) — four content
        gates apply in this pinned order:"

        PRD §3.7: "`honest_opinion_attested` is true, otherwise
        `ERR_HONEST_OPINION_NOT_ATTESTED`;"

        PRD §3.7: "Two further fields are optional at draft time and mandatory in
        substance at submission time: `disclosure_statement`, the incentivized-review
        disclosure, which defaults to unset; and `honest_opinion_attested`, the
        panelist's attestation that the opinion is their own, which defaults to
        false."

        Design: Corner/validations/missing_attestation_outranks_missing_disclosure_and_a_short_body
        """
        world = self._delivered_world(api, "Gate Order")
        draft = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Loved it",
            body_text=FIVE_WORD_BODY,
            star_rating=5,
            disclosure_statement=None,
            honest_opinion_attested=None,
        )

        validate_error(
            api.submit_review(world.panelist_headers(0), draft["id"]),
            ERR_HONEST_OPINION_NOT_ATTESTED,
            422,
        )

        stored = fx.get_review(api, draft["id"])
        assert stored["status"] == "DRAFT"
        assert stored["honest_opinion_attested"] is False
        assert stored["disclosure_statement"] is None
        assert stored["word_count"] == 5
        assert stored["first_submitted_at"] is None

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"

    def test_a_plausible_but_non_conforming_disclosure_is_refused(self, api):
        """PRD §3.7: "`disclosure_statement` is present and contains one of the
        two accepted disclosure phrases — "i received this product for free" or
        "sample provided by" — matched case-insensitively as a substring,
        otherwise `ERR_DISCLOSURE_STATEMENT_MISSING`; either phrase satisfies this
        gate;"

        Design: Corner/validations/attested_review_without_a_disclosure_phrase_is_rejected
        """
        world = self._delivered_world(api, "Phrase Required")
        draft = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Nice one",
            body_text=FIVE_WORD_BODY,
            star_rating=5,
            disclosure_statement=NON_CONFORMING_DISCLOSURE,
            honest_opinion_attested=True,
        )

        validate_error(
            api.submit_review(world.panelist_headers(0), draft["id"]),
            ERR_DISCLOSURE_STATEMENT_MISSING,
            422,
        )

        stored = fx.get_review(api, draft["id"])
        assert stored["status"] == "DRAFT"
        assert stored["honest_opinion_attested"] is True
        assert stored["first_submitted_at"] is None

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["disclosure_rejected_review_count"] == 0

    def test_a_submission_that_clears_every_gate_is_stamped_and_accepted(self, api):
        """PRD §3.7: "A first submission stamps `first_submitted_at` with the
        logical clock's current instant, and only a first submission does so —
        every later submission of the same review leaves that timestamp exactly as
        it was, which is what makes it a stable anchor for the audit variant's
        review-velocity window in §3.3."

        PRD §3.7: "`APPROVE` moves the review `SUBMITTED → APPROVED`, records
        `approved_by_user_id` from the acting moderator's `X-User-ID`, increases
        the campaign's `approved_review_count` by 1, and advances the enrollment's
        obligation axis `REVIEW_DUE → REVIEW_FULFILLED`, discharging the
        panelist's obligation."

        Design: Corner/validations/a_submission_that_satisfies_every_review_rule_is_accepted
        """
        world = self._delivered_world(api, "Gate Pass")
        draft = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Worth trying",
            body_text=FIFTEEN_WORD_BODY,
            star_rating=4,
            disclosure_statement=BADGE_DISCLOSURE,
            honest_opinion_attested=True,
        )

        submitted = validate_success(
            api.submit_review(world.panelist_headers(0), draft["id"])
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["word_count"] == 15
        assert_instant(submitted["first_submitted_at"], "2026-08-01T00:00:00Z", "first_submitted_at")
        assert submitted["revision_count"] == 0
        assert submitted["approved_by_user_id"] is None

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["approved_review_count"] == 0


class TestEnrollmentUniqueness:
    """One live enrollment per campaign-and-panelist pair."""

    def test_a_second_enrollment_on_a_live_pair_is_refused(self, api):
        """PRD §2.5: "No enrollment already exists for this campaign-and-panelist
        pair whose `screening_status` is anything other than `SCREEN_REVOKED` —
        otherwise `ERR_DUPLICATE_ENROLLMENT` (409). Applies to enrollment
        creation."

        Design: Corner/validations/second_enrollment_for_the_same_campaign_and_panelist_is_rejected
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Duplicate Enrollment"
        )
        panelist = fx.create_panelist(api)
        first = fx.create_enrollment(
            api,
            world.campaign_id,
            panelist["id"],
            screening_answers={"household_size": 3, "attests_no_resale": True},
        )
        assert first["screening_status"] == "PENDING_SCREEN"

        validate_error(
            api.create_enrollment(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                panelist_id=panelist["id"],
                screening_answers={"household_size": 4, "attests_no_resale": True},
            ),
            ERR_DUPLICATE_ENROLLMENT,
            409,
        )

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["enrollment_count"] == 1

        stored = fx.get_enrollment(api, first["id"])
        assert stored["enrollment_seq"] == 1
        assert stored["screening_answers"]["household_size"] == 3

        _, meta = validate_paginated(
            api.list_enrollments(
                campaign_manager_headers(), campaign_id=world.campaign_id
            )
        )
        assert meta["total_count"] == 1


class TestAllocationBusinessRungs:
    """The allocation rungs below the state and posture gates."""

    def test_a_holdout_member_is_never_sampled(self, api):
        """PRD §2.5: "The enrollment being sampled has `holdout_flag` false —
        otherwise `ERR_HOLDOUT_ENROLLMENT_NOT_SAMPLEABLE` (422). Applies to
        shipment allocation."

        PRD §3.6: "A holdout member is refused here and always: withholding them
        is the entire basis on which lift is later measured."

        PRD §3.4: "An enrollment is placed in the holdout group when the
        whole-number part of its `enrollment_seq` multiplied by the campaign's
        `holdout_pct` is strictly greater than the whole-number part of one less
        than its `enrollment_seq` multiplied by that same `holdout_pct`."

        Design: Corner/validations/holdout_enrollment_cannot_be_allocated_a_sample
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            holdout_pct=0.5,
            name="All Holdout",
        )
        second_panelist = fx.create_panelist(api)
        second = fx.create_enrollment(api, world.campaign_id, second_panelist["id"])
        second = fx.screen_enrollment(api, second["id"])
        assert second["enrollment_seq"] == 2
        assert second["holdout_flag"] is True

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=second["id"],
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=second["version"],
                surcharge_cents=0,
            ),
            ERR_HOLDOUT_ENROLLMENT_NOT_SAMPLEABLE,
            422,
        )

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["holdout_enrollment_count"] == 1
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0

        line = fx.get_kit_line(api, world.kit_line_id(0))
        assert line["units_reserved"] == 0

    def test_the_budget_check_counts_freight_as_well_as_the_kit(self, api):
        """PRD §3.6: "The shipment's `committed_cost_cents` is the campaign's
        current `kit_assembly_unit_cost_cents` plus the `freight_cents_per_kit` of
        the center that owns the shipment's wave."

        PRD §3.6: "If `budget_available_cents` is short of it, the allocation is
        refused with `ERR_CAMPAIGN_BUDGET_EXHAUSTED`; landing exactly on the
        available balance is permitted."

        Design: Corner/validations/allocation_over_the_remaining_budget_is_rejected
        """
        world = fx.sampling_active_campaign(
            api, panelist_count=1, budget_total_cents=700, name="Thin Budget"
        )
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_CAMPAIGN_BUDGET_EXHAUSTED,
            422,
        )

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["kit_assembly_unit_cost_cents"] == 454
        assert campaign["budget_total_cents"] == 700
        assert campaign["budget_committed_cents"] == 0
        assert campaign["budget_available_cents"] == 700
        assert campaign["allocated_sample_count"] == 0

        accessory = fx.get_kit_line(api, world.kit_line_id(1))
        assert accessory["units_reserved"] == 0

    def test_the_wave_ceiling_counts_kit_units_not_shipments(self, api):
        """PRD §3.5: "The **per-wave ceiling** compares the wave's own
        `planned_unit_count` plus the kit units the new shipment would consume
        against that wave's `planned_capacity_units`. Exceeding it is refused with
        `ERR_WAVE_CAPACITY_EXCEEDED`. Landing exactly on the ceiling is allowed;
        going one unit past it is not."

        Design: Corner/validations/wave_planned_capacity_is_an_aggregate_ceiling_over_kit_units
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            wave_overrides={"planned_capacity_units": 3},
            name="Tight Wave",
        )
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_WAVE_CAPACITY_EXCEEDED,
            422,
        )

        wave = fx.get_wave(api, world.wave_id)
        assert wave["planned_unit_count"] == 0
        assert wave["status"] == "PLANNED"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0

        hero = fx.get_kit_line(api, world.kit_line_id(0))
        assert hero["units_reserved"] == 0

    def test_the_capacity_rung_answers_before_the_stock_rung(self, api):
        """PRD §2.5: "The per-wave ceiling holds — otherwise
        `ERR_WAVE_CAPACITY_EXCEEDED` (422). Applies to shipment allocation."

        PRD §2.5: "Every `ACTIVE` kit line of the campaign has at least
        `quantity_per_kit` units available — otherwise
        `ERR_KIT_STOCK_INSUFFICIENT` (422). Applies to shipment allocation."

        PRD §2.5: "The ladder is what makes error codes predictable when several
        things are wrong at once, so it is stated here once in full rather than
        restated per endpoint."

        Design: Corner/validations/capacity_is_judged_before_stock_because_kit_units_ignore_inventory
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=SHORT_ACCESSORY_KIT,
            wave_overrides={"planned_capacity_units": 3},
            name="Both Ceilings",
        )
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_WAVE_CAPACITY_EXCEEDED,
            422,
        )

        accessory = fx.get_kit_line(api, world.kit_line_id(1))
        assert accessory["units_available"] == 1
        assert accessory["units_reserved"] == 0

        wave = fx.get_wave(api, world.wave_id)
        assert wave["planned_unit_count"] == 0

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 0


class TestSyndicationTargetRules:
    """Clearance-list membership and target uniqueness."""

    def test_a_valid_retailer_off_the_clearance_list_cannot_be_queued(self, api):
        """PRD §3.1: "This array is a clearance list rather than a relationship:
        it is consulted when a review is queued for a retailer, and a retailer
        absent from it can never receive this campaign's reviews."

        PRD §2.5: "The `retailer_id` being targeted is a member of the owning
        campaign's `syndication_retailer_ids` — otherwise
        `ERR_RETAILER_NOT_IN_CAMPAIGN` (422). Applies to syndication queueing."

        Design: Corner/validations/syndicating_to_a_retailer_outside_the_campaign_list_is_rejected
        """
        bundle = fx.approved_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            objective_type="REVIEW_ACQUISITION",
            retailer_overrides={"name": "Listed Retailer"},
            name="Listed Only",
        )
        unlisted = fx.create_retailer(api, name="Unlisted Retailer")

        validate_error(
            api.create_syndication_record(
                campaign_manager_headers(),
                review_submission_id=bundle["review"]["id"],
                retailer_id=unlisted["id"],
            ),
            ERR_RETAILER_NOT_IN_CAMPAIGN,
            422,
        )

        assert fx.get_retailer(api, unlisted["id"])["feed_status"] == "ACCEPTING"

        _, meta = validate_paginated(
            api.list_syndication_records(
                campaign_manager_headers(),
                review_submission_id=bundle["review"]["id"],
            )
        )
        assert meta["total_count"] == 0

        campaign = fx.get_campaign(api, bundle["world"].campaign_id)
        assert campaign["syndicated_review_count"] == 0

    def test_a_queued_pair_cannot_be_queued_a_second_time(self, api):
        """PRD §2.5: "No syndication record already exists for this
        review-and-retailer pair whose `status` is anything other than `REJECTED`
        — otherwise `ERR_DUPLICATE_SYNDICATION_TARGET` (409). Applies to
        syndication queueing."

        PRD §3.8: "A rejected attempt may be re-queued after the underlying
        problem is fixed; a queued, syndicated or taken-down one may not be
        duplicated."

        Design: Corner/validations/second_syndication_record_for_the_same_review_and_retailer_is_rejected
        """
        bundle = fx.approved_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            objective_type="REVIEW_ACQUISITION",
            retailer_overrides={"name": "Solo Retailer"},
            name="Duplicate Target",
        )
        first = fx.create_syndication(
            api, bundle["review"]["id"], bundle["retailer"]["id"]
        )
        assert first["status"] == "QUEUED"

        validate_error(
            api.create_syndication_record(
                campaign_manager_headers(),
                review_submission_id=bundle["review"]["id"],
                retailer_id=bundle["retailer"]["id"],
            ),
            ERR_DUPLICATE_SYNDICATION_TARGET,
            409,
        )

        assert fx.get_syndication(api, first["id"])["status"] == "QUEUED"

        _, meta = validate_paginated(
            api.list_syndication_records(
                campaign_manager_headers(),
                review_submission_id=bundle["review"]["id"],
            )
        )
        assert meta["total_count"] == 1
