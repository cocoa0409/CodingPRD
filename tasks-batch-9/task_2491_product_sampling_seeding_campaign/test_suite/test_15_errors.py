"""The error catalogue: unresolvable ids, repeated transitions and standing gates."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    MODERATOR_A_USER_ID,
    NOBODY_USER_ID,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    moderator_b_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import (
    ERR_DIVERSION_CASE_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_FULFILLMENT_CENTER_NOT_FOUND,
    ERR_FULFILLMENT_WAVE_NOT_FOUND,
    ERR_CAMPAIGN_POSTURE_RESTRICTED,
    ERR_INVALID_DIVERSION_CASE_STATE,
    ERR_INVALID_KIT_LINE_STATE,
    ERR_INVALID_REVIEW_STATE,
    ERR_INVALID_SYNDICATION_STATE,
    ERR_KIT_LINE_NOT_FOUND,
    ERR_LIFT_ANALYSIS_NOT_FOUND,
    ERR_PANELIST_BANNED,
    ERR_PANELIST_NOT_FOUND,
    ERR_PURCHASE_MATCH_NOT_FOUND,
    ERR_RETAILER_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SYNDICATION_RECORD_NOT_FOUND,
)
from test_helpers.factories import screening_answers
from test_helpers.fixtures import KitSpec


ABSENT_UUID = NOBODY_USER_ID
WINDOW_START = "2026-07-01T00:00:00Z"
WINDOW_END = "2026-09-30T00:00:00Z"
EPOCH = "2026-08-01T00:00:00Z"
SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)


class TestUnresolvablePathIdentifiers:
    """A path id that resolves to nothing answers 404 and nothing else."""

    def test_a_receipt_against_a_never_persisted_kit_line_is_not_found(self, api):
        """PRD §2.4: "Path identifiers are resolved strictly left to right, and the
        first identifier that fails to resolve determines the 404 returned; a later
        segment is never consulted once an earlier one has failed."

        PRD §2.5: "Every path identifier resolves to an existing row, checked left
        to right — otherwise the matching not-found code from §2.4 (404). Applies
        to every endpoint whose path contains an identifier."

        Design: Corner/errors/kit_line_receipt_on_unknown_line_not_found
        """
        validate_error(
            api.record_kit_line_receipt(
                fulfillment_ops_headers(), ABSENT_UUID, units=5
            ),
            ERR_KIT_LINE_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_kit_lines(campaign_manager_headers()))
        assert meta["total_count"] == 0

    def test_locking_a_wave_that_was_never_planned_is_not_found(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        PRD §2.5: "The target resource is in a state from which the requested
        transition is declared — otherwise the state code for that resource family
        (409): `ERR_INVALID_CAMPAIGN_TRANSITION`, `ERR_INVALID_KIT_LINE_STATE`,
        `ERR_INVALID_WAVE_STATE`, `ERR_INVALID_SHIPMENT_STATE`,
        `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_SYNDICATION_STATE`,
        `ERR_INVALID_DIVERSION_CASE_STATE` or `ERR_ENROLLMENT_NOT_SCREENABLE`.
        Applies to every transition endpoint."

        Design: Corner/errors/wave_lock_on_unknown_wave_not_found
        """
        validate_error(
            api.lock_fulfillment_wave(fulfillment_ops_headers(), ABSENT_UUID),
            ERR_FULFILLMENT_WAVE_NOT_FOUND,
            404,
        )

    def test_dispatching_a_syndication_record_that_does_not_exist_is_not_found(
        self, api
    ):
        """PRD §2.4: "The identifiers that appear in paths are `campaign_id`,
        `kit_line_id`, `fulfillment_center_id`, `fulfillment_wave_id`,
        `panelist_id`, `enrollment_id`, `sample_shipment_id`,
        `review_submission_id`, `retailer_id`, `syndication_record_id`,
        `diversion_case_id`, `purchase_match_id` and `lift_analysis_id`, and each
        has its own not-found code: `ERR_CAMPAIGN_NOT_FOUND`,
        `ERR_KIT_LINE_NOT_FOUND`, `ERR_FULFILLMENT_CENTER_NOT_FOUND`,
        `ERR_FULFILLMENT_WAVE_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
        `ERR_SYNDICATION_RECORD_NOT_FOUND`, `ERR_DIVERSION_CASE_NOT_FOUND`,
        `ERR_PURCHASE_MATCH_NOT_FOUND` and `ERR_LIFT_ANALYSIS_NOT_FOUND`."

        Design: Corner/errors/dispatch_on_unknown_syndication_record_not_found
        """
        validate_error(
            api.dispatch_syndication_record(fulfillment_ops_headers(), ABSENT_UUID),
            ERR_SYNDICATION_RECORD_NOT_FOUND,
            404,
        )

    def test_investigating_a_case_that_was_never_opened_is_not_found(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        PRD §3.3: "The audit variant runs automatically when a diversion case
        moves into investigation."

        Design: Corner/errors/investigate_on_unknown_diversion_case_not_found
        """
        validate_error(
            api.investigate_diversion_case(moderator_a_headers(), ABSENT_UUID),
            ERR_DIVERSION_CASE_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_diversion_cases(moderator_a_headers()))
        assert meta["total_count"] == 0

    def test_reading_a_lift_analysis_that_was_never_computed_is_not_found(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        Design: Corner/errors/get_unknown_lift_analysis_not_found
        """
        validate_error(
            api.get_lift_analysis(campaign_manager_headers(), ABSENT_UUID),
            ERR_LIFT_ANALYSIS_NOT_FOUND,
            404,
        )

    def test_reading_a_purchase_match_that_was_never_ingested_is_not_found(self, api):
        """PRD §2.5: "Every path identifier resolves to an existing row, checked
        left to right — otherwise the matching not-found code from §2.4 (404).
        Applies to every endpoint whose path contains an identifier."

        Design: Corner/errors/get_unknown_purchase_match_not_found
        """
        validate_error(
            api.get_purchase_match(platform_admin_headers(), ABSENT_UUID),
            ERR_PURCHASE_MATCH_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_purchase_matches(platform_admin_headers()))
        assert meta["total_count"] == 0


class TestUnresolvableBodyForeignKeys:
    """A body foreign key is checked in input-list order, before any business rule."""

    def test_a_wave_naming_a_center_that_does_not_exist_is_not_found(self, api):
        """PRD §2.5: "Every foreign key in the request body resolves to an existing
        row, checked in input-list order — otherwise the matching not-found code
        from §2.4 (404). Applies to every endpoint with foreign keys in its input."

        PRD §2.5: "On fulfilment-wave creation, `window_end` is strictly later than
        `window_start` — otherwise `ERR_WAVE_WINDOW_INVALID` (400)."

        Design: Corner/errors/wave_create_on_unknown_center_not_found
        """
        validate_error(
            api.create_fulfillment_wave(
                fulfillment_ops_headers(),
                fulfillment_center_id=ABSENT_UUID,
                window_start=EPOCH,
                window_end="2026-08-02T00:00:00Z",
                planned_capacity_units=50,
            ),
            ERR_FULFILLMENT_CENTER_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(
            api.list_fulfillment_waves(fulfillment_ops_headers())
        )
        assert meta["total_count"] == 0

    def test_an_enrollment_naming_an_unregistered_panelist_is_not_found(self, api):
        """PRD §2.5: "Every foreign key in the request body resolves to an existing
        row, checked in input-list order — otherwise the matching not-found code
        from §2.4 (404). Applies to every endpoint with foreign keys in its input."

        PRD §2.5: "The owning campaign's `status` permits the operation — otherwise
        `ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS` (409). Enrollment creation and
        screening require `SCREENING_OPEN` or `SAMPLING_ACTIVE`; shipment
        allocation requires `SAMPLING_ACTIVE`; review-draft creation and review
        submission require `SAMPLING_ACTIVE` or `REVIEW_WINDOW`; lift analysis
        requires `REVIEW_WINDOW` or `CLOSED`. Applies to exactly those six
        operations."

        Design: Corner/errors/enrollment_create_with_unknown_panelist_not_found
        """
        campaign = fx.create_campaign(api, name="Draft Only")

        validate_error(
            api.create_enrollment(
                campaign_manager_headers(),
                campaign_id=campaign["id"],
                panelist_id=ABSENT_UUID,
                screening_answers=screening_answers(household_size=2),
            ),
            ERR_PANELIST_NOT_FOUND,
            404,
        )

        stored = fx.get_campaign(api, campaign["id"])
        assert stored["status"] == "DRAFT"

        _, meta = validate_paginated(
            api.list_enrollments(campaign_manager_headers(), campaign_id=campaign["id"])
        )
        assert meta["total_count"] == 0

    def test_a_purchase_match_naming_an_unknown_enrollment_is_not_found(self, api):
        """PRD §2.5: "Every foreign key in the request body resolves to an existing
        row, checked in input-list order — otherwise the matching not-found code
        from §2.4 (404). Applies to every endpoint with foreign keys in its input."

        PRD §2.5: "`purchased_at` falls inside the campaign's conversion window —
        otherwise `ERR_PURCHASE_MATCH_OUT_OF_WINDOW` (422). Applies to
        purchase-match ingestion."

        Design: Corner/errors/purchase_match_with_unknown_enrollment_not_found
        """
        validate_error(
            api.create_purchase_match(
                platform_admin_headers(),
                enrollment_id=ABSENT_UUID,
                retailer_channel_code="RETAIL_WEB",
                purchase_amount_cents=4999,
                purchased_at="2026-08-05T00:00:00Z",
                match_confidence=0.95,
            ),
            ERR_ENROLLMENT_NOT_FOUND,
            404,
        )

    def test_the_first_of_two_body_keys_decides_the_not_found_code(self, api):
        """PRD §2.4: "The same codes are used when a foreign key supplied in a
        request body fails to resolve; body foreign keys are checked in the order
        the fields appear in the endpoint's input list, and the members of
        `syndication_retailer_ids` are checked left to right within that array."

        PRD §3.8: "First a `CampaignManager` or `FulfillmentOps` queues a record by
        naming the `review_submission_id` and the `retailer_id`."

        Design: Corner/errors/syndication_record_with_unknown_review_not_found
        """
        retailer = fx.create_retailer(
            api,
            name="BigBox Feed",
            requires_disclosure_badge=False,
            min_star_rating_accepted=1,
            max_reviews_per_panelist_per_month=5,
        )

        validate_error(
            api.create_syndication_record(
                campaign_manager_headers(),
                review_submission_id=ABSENT_UUID,
                retailer_id=retailer["id"],
            ),
            ERR_REVIEW_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(
            api.list_syndication_records(
                campaign_manager_headers(), retailer_id=retailer["id"]
            )
        )
        assert meta["total_count"] == 0

    def test_an_unresolvable_member_of_the_retailer_array_voids_the_campaign(self, api):
        """PRD §2.4: "The same codes are used when a foreign key supplied in a
        request body fails to resolve; body foreign keys are checked in the order
        the fields appear in the endpoint's input list, and the members of
        `syndication_retailer_ids` are checked left to right within that array."

        Design: Corner/errors/campaign_create_with_unknown_syndication_retailer_not_found
        """
        retailer = fx.create_retailer(
            api,
            name="ShelfMart Feed",
            requires_disclosure_badge=False,
            min_star_rating_accepted=1,
            max_reviews_per_panelist_per_month=5,
        )

        validate_error(
            api.create_campaign(
                campaign_manager_headers(),
                name="Bad Retailer List",
                objective_type="AWARENESS",
                target_segment_codes=["URBAN_MILLENNIAL"],
                syndication_retailer_ids=[retailer["id"], ABSENT_UUID],
                sampling_window_start=WINDOW_START,
                sampling_window_end=WINDOW_END,
                budget_total_cents=1000000,
            ),
            ERR_RETAILER_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0


class TestRepeatingATerminalTransition:
    """A second attempt at a completed hop is a state error, not a no-op."""

    def test_retiring_an_already_retired_kit_line_is_refused(self, api):
        """PRD §2.5: "The target resource is in a state from which the requested
        transition is declared — otherwise the state code for that resource family
        (409): `ERR_INVALID_CAMPAIGN_TRANSITION`, `ERR_INVALID_KIT_LINE_STATE`,
        `ERR_INVALID_WAVE_STATE`, `ERR_INVALID_SHIPMENT_STATE`,
        `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_SYNDICATION_STATE`,
        `ERR_INVALID_DIVERSION_CASE_STATE` or `ERR_ENROLLMENT_NOT_SCREENABLE`.
        Applies to every transition endpoint."

        PRD §2.4: "`version`, an integer that starts at 1 and increases by exactly
        1 on every mutation, including mutations the server performs on its own
        initiative as part of a cascade or a counter refresh."

        Design: Corner/errors/retire_an_already_retired_kit_line_is_rejected
        """
        campaign = fx.create_campaign(api, name="Retire Twice")
        line = fx.add_kit_line(api, campaign["id"], component_sku="HERO-1")
        retired = fx.retire_kit_line(api, line["id"])
        assert retired["status"] == "RETIRED"
        assert retired["version"] == line["version"] + 1

        validate_error(
            api.retire_kit_line(campaign_manager_headers(), line["id"]),
            ERR_INVALID_KIT_LINE_STATE,
            409,
        )

        stored = fx.get_kit_line(api, line["id"])
        assert stored["status"] == "RETIRED"
        assert stored["version"] == retired["version"]

    def test_submitting_the_same_review_a_second_time_is_refused(self, api):
        """PRD §2.5: "The target resource is in a state from which the requested
        transition is declared — otherwise the state code for that resource family
        (409): `ERR_INVALID_CAMPAIGN_TRANSITION`, `ERR_INVALID_KIT_LINE_STATE`,
        `ERR_INVALID_WAVE_STATE`, `ERR_INVALID_SHIPMENT_STATE`,
        `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_SYNDICATION_STATE`,
        `ERR_INVALID_DIVERSION_CASE_STATE` or `ERR_ENROLLMENT_NOT_SCREENABLE`.
        Applies to every transition endpoint."

        PRD §3.7: "A first submission stamps `first_submitted_at` with the logical
        clock's current instant, and only a first submission does so — every later
        submission of the same review leaves that timestamp exactly as it was,
        which is what makes it a stable anchor for the audit variant's
        review-velocity window in §3.3."

        Design: Corner/errors/submitting_the_same_review_twice_is_rejected
        """
        bundle = fx.submitted_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            holdout_pct=0.0,
            objective_type="REVIEW_ACQUISITION",
            name="Double Submit",
        )
        world = bundle["world"]
        review = bundle["review"]
        assert review["status"] == "SUBMITTED"

        validate_error(
            api.submit_review(world.panelist_headers(0), review["id"]),
            ERR_INVALID_REVIEW_STATE,
            409,
        )

        stored = fx.get_review(api, review["id"])
        assert stored["status"] == "SUBMITTED"
        assert_instant(stored["first_submitted_at"], EPOCH, "first_submitted_at")
        assert stored["revision_count"] == 0
        assert stored["version"] == review["version"]

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["approved_review_count"] == 0

    def test_dispatching_an_already_syndicated_record_is_refused(self, api):
        """PRD §3.8: "The record must be `QUEUED`
        (`ERR_INVALID_SYNDICATION_STATE`), the review must still be `APPROVED`
        (`ERR_INVALID_REVIEW_STATE`), the campaign posture must still be `OPEN` —
        `RESTRICTED` reports `ERR_CAMPAIGN_POSTURE_RESTRICTED` and `FROZEN` reports
        `ERR_CAMPAIGN_POSTURE_FROZEN` — and the retailer's `feed_status` must still
        be `ACCEPTING` (`ERR_RETAILER_FEED_PAUSED`)."

        PRD §3.8: "When all three rules pass, the record moves `QUEUED →
        SYNDICATED`, `syndicated_at` is stamped from the logical clock and the
        campaign's `syndicated_review_count` increases by 1."

        Design: Corner/errors/dispatching_an_already_syndicated_record_is_rejected
        """
        bundle = fx.syndicated_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            holdout_pct=0.0,
            objective_type="REVIEW_ACQUISITION",
            retailer_overrides={
                "name": "ShelfMart Badge",
                "requires_disclosure_badge": True,
                "min_star_rating_accepted": 3,
                "max_reviews_per_panelist_per_month": 5,
            },
            name="Double Dispatch",
        )
        record = bundle["syndication"]
        assert record["status"] == "SYNDICATED"
        assert_instant(record["syndicated_at"], EPOCH, "syndicated_at")

        validate_error(
            api.dispatch_syndication_record(fulfillment_ops_headers(), record["id"]),
            ERR_INVALID_SYNDICATION_STATE,
            409,
        )

        stored = fx.get_syndication(api, record["id"])
        assert stored["status"] == "SYNDICATED"
        assert_instant(stored["syndicated_at"], EPOCH, "syndicated_at")
        assert stored["rejection_reason"] is None
        assert stored["takedown_requested_at"] is None
        assert stored["version"] == record["version"]

        campaign = fx.get_campaign(api, bundle["world"].campaign_id)
        assert campaign["syndicated_review_count"] == 1

    def test_dismissing_a_case_that_never_reached_investigation_is_refused(self, api):
        """PRD §3.9: "Dismissal moves the case `INVESTIGATING → DISMISSED`, which
        is terminal, and restores standing conditionally: when the panelist is
        currently `FLAGGED` and holds no other case in `INVESTIGATING` or
        `SUBSTANTIATED`, their `integrity_status` returns to `CLEAR` and their
        `version` increases by 1; a panelist with another live case stays flagged."

        PRD §3.9: "Both investigation and reopening, and both dismissal and
        substantiation, require the case to be in the state their transition
        declares, and any mismatch is refused with
        `ERR_INVALID_DIVERSION_CASE_STATE`."

        PRD §3.3: "The screening variant runs automatically as part of eligibility
        screening."

        Design: Corner/errors/dismissing_an_open_diversion_case_is_rejected
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            holdout_pct=0.0,
            name="Open Case",
        )
        case = fx.open_diversion_case(
            api,
            world.panelist_id(0),
            world.shipment_id(0),
            signal_type="RESALE_LISTING",
            evidence_note="Kit listed on a marketplace hours after allocation.",
            headers=moderator_a_headers(),
        )
        assert case["status"] == "OPEN"

        validate_error(
            api.dismiss_diversion_case(moderator_b_headers(), case["id"]),
            ERR_INVALID_DIVERSION_CASE_STATE,
            409,
        )

        stored = fx.get_case(api, case["id"])
        assert stored["status"] == "OPEN"
        assert stored["opened_by_user_id"] == MODERATOR_A_USER_ID
        assert stored["reopen_count"] == 0

        panelist = fx.get_panelist(api, world.panelist_id(0))
        assert panelist["integrity_status"] == "CLEAR"
        assert panelist["fraud_risk_score_audit"] is None
        assert_instant(panelist["last_risk_scored_at"], EPOCH, "last_risk_scored_at")


class TestStandingAndDutyGates:
    """Identity and integrity refusals, each with a legal-looking target state."""

    def test_a_banned_panelist_cannot_open_a_fresh_enrollment(self, api):
        """PRD §2.5: "The panelist behind the target resource does not have
        `integrity_status` equal to `BANNED` — otherwise `ERR_PANELIST_BANNED`
        (403). Applies to enrollment creation, screening, screener resubmission,
        shipment allocation, review-draft creation, review submission, review
        revision and syndication queueing."

        PRD §2.5: "No enrollment already exists for this campaign-and-panelist pair
        whose `screening_status` is anything other than `SCREEN_REVOKED` —
        otherwise `ERR_DUPLICATE_ENROLLMENT` (409). Applies to enrollment
        creation."

        PRD §3.9: "The cascade then runs: the panelist's `diversion_strikes`
        increases by 1 and their `integrity_status` becomes `BANNED`; because they
        are banned, every enrollment of theirs whose `screening_status` is
        `PENDING_SCREEN` or `SCREEN_PASSED` moves to the terminal `SCREEN_REVOKED`
        and its `obligation_status` becomes `FORFEITED` unless it is already
        `REVIEW_FULFILLED`;"

        PRD §2.9: "the posture is `FROZEN` when the diversion rate is at least 0.2,
        or when `substantiated_diversion_count` is at least 5;"

        Design: Corner/errors/banned_panelist_cannot_enroll_again
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            holdout_pct=0.0,
            name="Ban Then Enroll",
        )
        case = fx.open_diversion_case(
            api,
            world.panelist_id(0),
            world.shipment_id(0),
            signal_type="RESALE_LISTING",
            evidence_note="Marketplace listing matches the kit contents.",
            headers=moderator_a_headers(),
        )
        fx.investigate_case(api, case["id"], headers=moderator_a_headers())
        fx.substantiate_case(api, case["id"], headers=moderator_b_headers())

        validate_error(
            api.create_enrollment(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                panelist_id=world.panelist_id(0),
                screening_answers=screening_answers(household_size=3),
            ),
            ERR_PANELIST_BANNED,
            403,
        )

        panelist = fx.get_panelist(api, world.panelist_id(0))
        assert panelist["integrity_status"] == "BANNED"
        assert panelist["diversion_strikes"] == 1

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["screening_status"] == "SCREEN_REVOKED"
        assert enrollment["obligation_status"] == "FORFEITED"

        _, meta = validate_paginated(
            api.list_enrollments(
                campaign_manager_headers(), panelist_id=world.panelist_id(0)
            )
        )
        assert meta["total_count"] == 1

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["substantiated_diversion_count"] == 1
        assert campaign["delivered_sample_count"] == 0
        assert campaign["compliance_posture"] == "OPEN"

    def test_the_moderator_who_asked_for_changes_still_cannot_approve(self, api):
        """PRD §3.7: "Approval is barred for the moderator who previously requested
        changes on this same review: when the acting `X-User-ID` equals the stored
        `changes_requested_by_user_id`, the request is refused with
        `ERR_SEGREGATION_OF_DUTIES`, and a different moderator must take the
        decision."

        PRD §3.7: "the supplied content replaces the stored content wholesale,
        `word_count` is recomputed from the new `body_text`, `revision_count`
        increases by 1, `first_submitted_at` is left untouched, and the review
        returns to `SUBMITTED` with its `version` increased by 1."

        Design: Corner/errors/same_moderator_cannot_request_changes_then_approve
        """
        bundle = fx.submitted_review_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            holdout_pct=0.0,
            objective_type="REVIEW_ACQUISITION",
            review_overrides={"headline": "First pass"},
            name="Duty Split",
        )
        world = bundle["world"]
        review = fx.moderate_review(
            api,
            bundle["review"]["id"],
            "REQUEST_CHANGES",
            headers=moderator_a_headers(),
            moderator_note="Please describe the routine you followed.",
        )
        assert review["status"] == "CHANGES_REQUESTED"
        revised = fx.revise_review(
            api,
            review["id"],
            world.panelist_id(0),
            headline="Second pass",
        )
        assert revised["status"] == "SUBMITTED"
        assert revised["revision_count"] == 1

        validate_error(
            api.moderate_review(
                moderator_a_headers(),
                review["id"],
                decision="APPROVE",
                moderator_note="Looks good to me now.",
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        stored = fx.get_review(api, review["id"])
        assert stored["status"] == "SUBMITTED"
        assert stored["changes_requested_by_user_id"] == MODERATOR_A_USER_ID
        assert stored["approved_by_user_id"] is None
        assert stored["revision_count"] == 1
        assert_instant(stored["first_submitted_at"], EPOCH, "first_submitted_at")
        assert stored["version"] == revised["version"]

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["approved_review_count"] == 0

    def test_a_posture_that_turned_restricted_after_queueing_blocks_dispatch(self, api):
        """The record is queued while the posture is still `OPEN`, because rung 17
        governs queueing as well as dispatch; the third disclosure rejection then
        moves the posture underneath the queued record.

        PRD §2.9: "otherwise the posture is `RESTRICTED` when the diversion rate is
        at least 0.05, or when `disclosure_rejected_review_count` is at least 3;"

        PRD §2.5: "When the operation publishes content to a retailer feed, the
        campaign's `compliance_posture` is exactly `OPEN` — otherwise
        `ERR_CAMPAIGN_POSTURE_RESTRICTED` (409). Applies to syndication queueing
        and syndication dispatch."

        PRD §2.9: "`RESTRICTED` withdraws only the ability to publish externally:
        queueing a review for syndication and dispatching a queued record are both
        refused with `ERR_CAMPAIGN_POSTURE_RESTRICTED`, while enrollment screening
        and sample allocation continue unaffected."

        Design: Corner/errors/restricted_posture_blocks_syndication_dispatch
        """
        retailer = fx.create_retailer(
            api,
            name="ShelfMart Open Feed",
            feed_status="ACCEPTING",
            requires_disclosure_badge=False,
            min_star_rating_accepted=1,
            max_reviews_per_panelist_per_month=5,
        )
        world = fx.delivered_sample_world(
            api,
            panelist_count=2,
            surcharges=[0, 0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            holdout_pct=0.0,
            objective_type="REVIEW_ACQUISITION",
            syndication_retailer_ids=[retailer["id"]],
            name="Restricted Posture",
        )

        clean = fx.create_review(
            api, world.enrollment_id(1), world.panelist_id(1), headline="Attempt four"
        )
        clean = fx.submit_review(api, clean["id"], world.panelist_id(1))
        clean = fx.moderate_review(
            api,
            clean["id"],
            "APPROVE",
            headers=moderator_a_headers(),
            moderator_note="This one is clean.",
        )
        assert clean["status"] == "APPROVED"

        record = fx.create_syndication(api, clean["id"], retailer["id"])
        assert record["status"] == "QUEUED"

        for attempt in ("Attempt one", "Attempt two", "Attempt three"):
            draft = fx.create_review(
                api, world.enrollment_id(0), world.panelist_id(0), headline=attempt
            )
            submitted = fx.submit_review(api, draft["id"], world.panelist_id(0))
            fx.moderate_review(
                api,
                submitted["id"],
                "REJECT_DISCLOSURE",
                headers=moderator_a_headers(),
                moderator_note="Disclosure wording is not acceptable for our feeds.",
            )

        restricted = fx.get_campaign(api, world.campaign_id)
        assert restricted["disclosure_rejected_review_count"] == 3
        assert restricted["substantiated_diversion_count"] == 0
        assert restricted["compliance_posture"] == "RESTRICTED"

        validate_error(
            api.dispatch_syndication_record(fulfillment_ops_headers(), record["id"]),
            ERR_CAMPAIGN_POSTURE_RESTRICTED,
            409,
        )

        stored = fx.get_syndication(api, record["id"])
        assert stored["status"] == "QUEUED"
        assert stored["syndicated_at"] is None
        assert stored["version"] == record["version"]

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["approved_review_count"] == 1
        assert campaign["syndicated_review_count"] == 0

        assert fx.get_review(api, clean["id"])["status"] == "APPROVED"
        assert fx.get_retailer(api, retailer["id"])["feed_status"] == "ACCEPTING"
