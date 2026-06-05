"""Validation precedence and business-rule rejections: auth-over-state,
existence-over-referential, cross-entity state guards, and the single-failure
validation corners.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency.
Corner queue: validations + errors sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    create_campaign, create_open_campaign, create_closed_campaign, create_donor,
    create_employer, create_household, create_acknowledged_gift,
    setup_open_campaign_with_donor, create_pledge, set_clock,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Difficulty Rule 5 — validation priority conflicts
# ---------------------------------------------------------------------------
class TestValidationPrecedence:
    def test_auth_beats_state_on_acknowledge(self, api):
        """PRD §2.6: "Authorization is checked second: a forbidden role yields
        `ERR_UNAUTHORIZED`." PRD §2.6: "the target resource's current state is checked
        fourth: an operation requested against a resource not in a valid state for the
        requested transition yields `ERR_INVALID_STATE` (HTTP 409)."

        CampaignManager (not permitted for acknowledge) against an already-ACKNOWLEDGED
        gift violates both; authorization (priority 2) wins -> ERR_UNAUTHORIZED.

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_state_wrong_role_acknowledges_already_acknowledged_gift
        """
        camp, donor = setup_open_campaign_with_donor()
        _, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        # Already ACKNOWLEDGED; CampaignManager is not allowed to acknowledge.
        validate_error(api.acknowledge_gift(gift_id, CM), ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_existence_beats_referential_on_gift_create(self, api):
        """PRD §2.6: "Existence is checked third, yielding `ERR_NOT_FOUND`." PRD §2.6:
        "Only after these four gates does the system evaluate the domain-specific
        business rules described below". PRD §3.3: "When an `appeal_id` is supplied,
        its `campaign_id` must equal the gift's `campaign_id`, else the gift is rejected
        with `ERR_APPEAL_CAMPAIGN_MISMATCH` (HTTP 422)."

        A gift with a non-existent donor AND a mismatched appeal: existence (priority 3)
        wins -> ERR_NOT_FOUND, before the referential check.

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_referential_gift_unknown_donor_and_mismatched_appeal
        """
        camp1 = create_open_campaign(goal_cents=1000000)
        camp2 = create_open_campaign(goal_cents=1000000)
        appeal = get_success_data(
            api.create_appeal({"campaign_id": camp2["id"], "channel": "EMAIL", "code": "AP1"}, CM)
        )
        validate_error(
            api.create_gift(
                {"donor_id": NON_EXISTENT_UUID, "campaign_id": camp1["id"],
                 "amount_cents": 5000, "appeal_id": appeal["id"]},
                GA,
            ),
            ApiErrorId.ERR_NOT_FOUND.value,
        )

    def test_auth_beats_state_on_receipt(self, api):
        """PRD §2.6: "Authorization is checked second: a forbidden role yields
        `ERR_UNAUTHORIZED`." PRD §2.6: "the target resource's current state is checked
        fourth: an operation requested against a resource not in a valid state for the
        requested transition yields `ERR_INVALID_STATE` (HTTP 409)."

        GiftAdmin (not permitted for receipt) against a RECORDED (wrong-state) gift
        violates both; authorization (priority 2) wins -> ERR_UNAUTHORIZED, never the
        state error.

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_state_wrong_role_acknowledges_already_acknowledged_gift
        """
        camp, donor = setup_open_campaign_with_donor()
        from test_helpers import record_gift
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000)
        # receipt is a DonorRelations op; GiftAdmin is forbidden; gift is also RECORDED.
        validate_error(api.receipt_gift(gift["id"], GA), ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_existence_path_id_beats_referential_on_acknowledge(self, api):
        """PRD §2.6: "Existence is validated left to right: path identifiers are checked
        first ... The first identifier that does not resolve to an existing entity causes
        immediate rejection with `ERR_NOT_FOUND` (HTTP 404), before any business rule is
        evaluated."

        Acknowledging a non-existent gift id (path id) yields ERR_NOT_FOUND before any
        state evaluation.

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_referential_gift_unknown_donor_and_mismatched_appeal
        """
        validate_error(api.acknowledge_gift(NON_EXISTENT_UUID, DR), ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Difficulty Rule 7 — cross-entity state dependencies
# ---------------------------------------------------------------------------
class TestCrossEntityStateGuards:
    def test_gift_against_closed_campaign_rejected(self, api):
        """PRD §2.8: "Gifts, pledges, and planned-gift realizations may only attach to
        a campaign whose `status` is `OPEN`. Attempting to attach any of these to a
        campaign that is `DRAFT` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_OPEN`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/gift_requires_campaign_open
        """
        camp = create_closed_campaign(goal_cents=1000000)
        donor = create_donor()
        validate_error(
            api.create_gift({"donor_id": donor["id"], "campaign_id": camp["id"],
                             "amount_cents": 5000}, GA),
            ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value,
        )

    def test_pledge_against_draft_campaign_rejected(self, api):
        """PRD §2.8: "Gifts, pledges, and planned-gift realizations may only attach to a
        campaign whose `status` is `OPEN`. Attempting to attach any of these to a
        campaign that is `DRAFT` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_OPEN`
        (HTTP 409)."

        A pledge against a DRAFT (never-opened) campaign exercises the same Gift/Pledge ->
        Campaign open-gate dependency.

        Design: Difficulty/cross_entity_state_dependency/gift_requires_campaign_open
        """
        camp = create_campaign(goal_cents=1000000)  # left DRAFT
        donor = create_donor()
        validate_error(
            api.create_pledge({"donor_id": donor["id"], "campaign_id": camp["id"],
                               "total_amount_cents": 10000, "installment_count": 2,
                               "frequency": "MONTHLY", "schedule_basis": "FRONT_LOADED"}, GA),
            ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value,
        )

    def test_archive_donor_with_delinquent_pledge_rejected(self, api):
        """PRD §3.7: "provided the donor has no pledge in `ACTIVE` or `DELINQUENT`
        status; an attempt to archive a donor with such a live pledge is rejected with
        `ERR_DONOR_HAS_ACTIVE_PLEDGE` (HTTP 409)."

        A DELINQUENT pledge (a distinct live-pledge state from ACTIVE) likewise blocks
        archival, confirming the Donor -> Pledge state dependency over both live states.

        Design: Difficulty/cross_entity_state_dependency/donor_archive_requires_no_active_pledge
        """
        from test_helpers import setup_delinquent_pledge
        camp, donor, pledge = setup_delinquent_pledge(
            total_amount_cents=10000, installment_count=2,
            start_clock="2026-01-01T00:00:00Z", overdue_clock="2026-02-15T00:00:00Z",
        )
        assert pledge["status"] == "DELINQUENT"
        validate_error(api.archive_donor(donor["id"], DR), ApiErrorId.ERR_DONOR_HAS_ACTIVE_PLEDGE.value)

    def test_archive_donor_with_active_pledge_rejected(self, api):
        """PRD §3.7: "`DonorRelations` may archive a donor whose `lifecycle_status` is
        `PROSPECT` or `LAPSED`, provided the donor has no pledge in `ACTIVE` or
        `DELINQUENT` status; an attempt to archive a donor with such a live pledge is
        rejected with `ERR_DONOR_HAS_ACTIVE_PLEDGE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/donor_archive_requires_no_active_pledge
        """
        camp, donor = setup_open_campaign_with_donor()
        create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                      installment_count=2, frequency="MONTHLY")
        validate_error(api.archive_donor(donor["id"], DR), ApiErrorId.ERR_DONOR_HAS_ACTIVE_PLEDGE.value)


# ---------------------------------------------------------------------------
# Corner — validations section
# ---------------------------------------------------------------------------
class TestCornerValidations:
    def test_benefit_exceeds_amount_rejected(self, api):
        """PRD §3.3: "A `benefit_value_cents` exceeding `amount_cents` is rejected with
        `ERR_BENEFIT_EXCEEDS_GIFT` (HTTP 422)."

        Design: Corner/validations/gift_benefit_exceeds_amount_rejected
        """
        camp, donor = setup_open_campaign_with_donor()
        validate_error(
            api.create_gift({"donor_id": donor["id"], "campaign_id": camp["id"],
                             "amount_cents": 5000, "benefit_value_cents": 6000}, GA),
            ApiErrorId.ERR_BENEFIT_EXCEEDS_GIFT.value,
        )

    def test_pledge_attribution_mismatch_wrong_donor(self, api):
        """PRD §3.3: "When a `pledge_id` is supplied, the pledge's `donor_id` must
        equal the gift's `donor_id` *and* the pledge's `campaign_id` must equal the
        gift's `campaign_id`; a violation of either is rejected with
        `ERR_PLEDGE_ATTRIBUTION_MISMATCH` (HTTP 422)."

        Design: Corner/validations/pledge_attribution_mismatch_wrong_donor
        """
        camp = create_open_campaign(goal_cents=1000000)
        d1 = create_donor()
        d2 = create_donor()
        pledge = create_pledge(camp["id"], d1["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY")
        validate_error(
            api.create_gift({"donor_id": d2["id"], "campaign_id": camp["id"],
                             "amount_cents": 5000, "pledge_id": pledge["id"]}, GA),
            ApiErrorId.ERR_PLEDGE_ATTRIBUTION_MISMATCH.value,
        )

    def test_duplicate_appeal_code_within_campaign(self, api):
        """PRD §3.1: "The `code` must be unique within its campaign, compared
        case-insensitively; a collision is rejected with `ERR_DUPLICATE_APPEAL_CODE`
        (HTTP 409)."

        Design: Corner/validations/appeal_duplicate_code_within_campaign
        """
        camp = create_open_campaign(goal_cents=1000000)
        get_success_data(
            api.create_appeal({"campaign_id": camp["id"], "channel": "EMAIL", "code": "SPRING"}, CM)
        )
        validate_error(
            api.create_appeal({"campaign_id": camp["id"], "channel": "DIRECT_MAIL", "code": "spring"}, CM),
            ApiErrorId.ERR_DUPLICATE_APPEAL_CODE.value,
        )

    def test_pledge_one_time_frequency_count_mismatch(self, api):
        """PRD §3.5: "When the cadence is `ONE_TIME`, the `installment_count` must be
        exactly 1; any other count with a `ONE_TIME` frequency is rejected with
        `ERR_INSTALLMENT_FREQUENCY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/pledge_one_time_frequency_count_mismatch
        """
        camp, donor = setup_open_campaign_with_donor()
        validate_error(
            api.create_pledge({"donor_id": donor["id"], "campaign_id": camp["id"],
                               "total_amount_cents": 10000, "installment_count": 3,
                               "frequency": "ONE_TIME", "schedule_basis": "FRONT_LOADED"}, GA),
            ApiErrorId.ERR_INSTALLMENT_FREQUENCY_MISMATCH.value,
        )

    def test_household_primary_not_member_rejected(self, api):
        """PRD §3.2: "when set it must reference a donor whose `household_id` already
        equals this household's `id`, otherwise the patch is rejected with
        `ERR_PRIMARY_NOT_MEMBER` (HTTP 422)."

        Design: Corner/validations/household_primary_not_member_rejected
        """
        hh = create_household(soft_credit_policy="FULL_TO_ALL")
        outsider = create_donor()  # no household_id
        validate_error(
            api.patch_household(hh["id"], {"primary_donor_id": outsider["id"]}, CM),
            ApiErrorId.ERR_PRIMARY_NOT_MEMBER.value,
        )

    def test_reactivate_without_qualifying_gift_rejected(self, api):
        """PRD §3.7: "`DonorRelations` moves a `LAPSED` donor to `REACTIVATED` only when
        a qualifying reactivation gift exists ... without such a gift the request is
        rejected with `ERR_NO_REACTIVATION_GIFT` (HTTP 409)."

        Design: Corner/validations/reactivate_without_qualifying_gift_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor(lapse_threshold_days=30)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        set_clock("2026-03-01T00:00:00Z")
        get_success_data(api.flag_lapsed_donor(donor["id"], DR))
        # no further gift after lapse
        validate_error(api.reactivate_donor(donor["id"], DR), ApiErrorId.ERR_NO_REACTIVATION_GIFT.value)

    def test_refund_blocked_by_paid_match(self, api):
        """PRD §3.9: "is blocked when any matching claim against that gift is already
        `PAID` — a paid match must be reversed by the employer first — in which case the
        refund is rejected with `ERR_MATCH_PAID_BLOCKS_REFUND` (HTTP 409)."

        Design: Corner/validations/refund_match_paid_blocks
        """
        from test_helpers import open_match_claim, approve_match_claim, pay_match_claim
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0)
        donor = create_donor(employer_id=emp["id"])
        acked, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(gift_id)
        approve_match_claim(claim["id"])
        pay_match_claim(claim["id"])
        validate_error(
            api.refund_gift(gift_id, {"expected_gift_version": acked["version"]}, GA),
            ApiErrorId.ERR_MATCH_PAID_BLOCKS_REFUND.value,
        )

    def test_list_invalid_pagination_limit(self, api):
        """PRD §2.3: "A request whose `limit` falls outside the inclusive range of 1
        through 100, or whose `offset` is below 0, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/list_invalid_pagination_limit
        """
        validate_error(api.list_donors(GA, params={"limit": 500}), ApiErrorId.ERR_INVALID_PAGINATION.value)


# ---------------------------------------------------------------------------
# Corner — errors section (only the non-stub instance)
# ---------------------------------------------------------------------------
class TestCornerErrors:
    def test_flag_lapsed_before_window_rejected(self, api):
        """PRD §3.7: "the transition `ACTIVE → LAPSED` is permitted only when the
        elapsed time from the donor's `last_gift_at` to the current clock is at least
        the donor's `lapse_threshold_days` days; a request that does not meet that
        window is rejected with `ERR_LAPSE_WINDOW_NOT_MET` (HTTP 409)."

        Design: Corner/errors/error_lapse_window_not_met
        """
        set_clock("2026-01-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor(lapse_threshold_days=365)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        set_clock("2026-02-01T00:00:00Z")  # only 31 days < 365
        validate_error(api.flag_lapsed_donor(donor["id"], DR), ApiErrorId.ERR_LAPSE_WINDOW_NOT_MET.value)
