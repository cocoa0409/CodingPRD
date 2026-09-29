"""Who may call what: exclusive writes, shared writes, ownership and the headers."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    MODERATOR_A_USER_ID,
    campaign_manager_headers,
    fulfillment_ops_headers,
    make_headers,
    make_panelist_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHENTICATED,
)
from test_helpers.factories import screening_answers


WINDOW_START = "2026-07-01T00:00:00Z"
WINDOW_END = "2026-09-30T00:00:00Z"
UNDECLARED_ROLE = "PanelManager"


def _campaign_payload(name):
    return {
        "name": name,
        "objective_type": "TRIAL_GENERATION",
        "target_segment_codes": ["URBAN_MILLENNIAL"],
        "syndication_retailer_ids": [],
        "sampling_window_start": WINDOW_START,
        "sampling_window_end": WINDOW_END,
        "budget_total_cents": 1000000,
    }


class TestExclusiveOperations:
    """Each write family answers to exactly the roles its table row names."""

    def test_fulfillment_ops_cannot_open_a_campaign_for_screening(self, api):
        """PRD §2.1: "When the named role is well-formed but is not among the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD §2.1: "`FulfillmentOps` runs inventory, wave planning and outbound
        logistics: inventory receipts, write-offs, sample allocation, wave locking
        and release, delivery outcomes and retailer feed dispatch."

        PRD §3.2: "The campaign's `kit_assembly_unit_cost_cents` is then the plain
        sum of those already-rounded line values, taken over the campaign's
        `ACTIVE` lines only and evaluated in order of `created_at` ascending with
        `component_sku` ascending as the tie-break."

        Design: Corner/rbac/fulfillment_ops_cannot_open_campaign_screening
        """
        campaign = fx.create_campaign(api, name="Role Guard")
        fx.add_kit_line(
            api,
            campaign["id"],
            component_sku="HERO-1",
            component_role="HERO_PRODUCT",
            unit_cost_cents=1417,
            quantity_per_kit=1,
            component_discount_pct=0.8,
        )
        before = fx.get_campaign(api, campaign["id"])

        validate_error(
            api.open_screening(fulfillment_ops_headers(), campaign["id"]),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        after = fx.get_campaign(api, campaign["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == before["version"]
        assert after["kit_assembly_unit_cost_cents"] == 283
        assert after["budget_committed_cents"] == 0
        assert after["budget_available_cents"] == 1000000

    def test_the_campaign_manager_cannot_book_inventory_receipts(self, api):
        """PRD §2.1: "When the named role is well-formed but is not among the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD §3.5: "A receipt names a `units` count, which increases both the line's
        `units_received` and its `units_available` by that amount and increases the
        line's `version` by 1."

        Design: Corner/rbac/campaign_manager_cannot_receive_kit_units
        """
        campaign = fx.create_campaign(api, name="Stock Guard")
        line = fx.add_kit_line(
            api,
            campaign["id"],
            component_sku="HERO-1",
            component_role="HERO_PRODUCT",
            unit_cost_cents=1417,
            quantity_per_kit=1,
            component_discount_pct=0.8,
        )

        validate_error(
            api.record_kit_line_receipt(
                campaign_manager_headers(), line["id"], units=10
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        stored = fx.get_kit_line(api, line["id"])
        assert stored["units_received"] == 0
        assert stored["units_available"] == 0
        assert stored["version"] == line["version"]

    def test_a_real_panelist_row_still_cannot_define_a_campaign(self, api):
        """PRD §2.1: "A `Panelist` is a recruited panel member who acts on their own
        enrollments and their own reviews, and on nothing else."

        PRD §2.1: "When the named role is well-formed but is not among the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/panelist_cannot_create_a_campaign
        """
        panelist = fx.create_panelist(api, display_name="RB One")

        validate_error(
            api.raw_post(
                "/campaigns",
                payload=_campaign_payload("Panelist Campaign"),
                headers=make_panelist_headers(panelist["id"]),
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0


class TestSharedOperations:
    """A write listed for two roles behaves identically under both."""

    def test_both_listed_roles_register_a_retailer_with_the_same_defaults(self, api):
        """PRD §3.8: "A retailer is registered with a `name` and four policy fields,
        all optional with defaults: `feed_status`, either `ACCEPTING` or `PAUSED`
        and defaulting to `ACCEPTING`; `requires_disclosure_badge`, defaulting to
        true, meaning this retailer insists on the badge wording rather than any
        disclosure; `min_star_rating_accepted`, from 1 through 5 and defaulting to
        1, the lowest rating the feed will carry; and
        `max_reviews_per_panelist_per_month`, at least 1 and defaulting to 1, the
        retailer's anti-astroturfing rate limit on how often one panelist may
        appear."

        Design: Corner/rbac/retailer_registration_is_shared_by_platform_admin_and_campaign_manager
        """
        by_admin = validate_success(
            api.create_retailer(platform_admin_headers(), name="AdminMart"), 201
        )
        by_manager = validate_success(
            api.create_retailer(campaign_manager_headers(), name="ManagerMart"), 201
        )

        for retailer in (by_admin, by_manager):
            assert retailer["feed_status"] == "ACCEPTING"
            assert retailer["requires_disclosure_badge"] is True
            assert retailer["min_star_rating_accepted"] == 1
            assert retailer["max_reviews_per_panelist_per_month"] == 1

        assert by_admin["id"] != by_manager["id"]


class TestOwnershipAmongPeers:
    """Two callers of one role, separated only by whose row they own."""

    def test_the_owner_reads_the_enrollment_and_a_peer_panelist_does_not(self, api):
        """PRD §2.1: "A `Panelist`-role caller who targets an enrollment or a review
        that does not resolve to their own `Panelist` row is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check guards exactly
        seven operations: enrollment creation, screener resubmission, review-draft
        creation, review submission, review revision, single-enrollment reads and
        single-review reads."

        PRD §2.5: "When `X-User-Role` is `Panelist`, `X-User-ID` equals the
        `panelist_id` of the enrollment behind the target resource — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403). Applies to the seven ownership-scoped
        operations named in §2.1."

        Design: Corner/rbac/panelist_cannot_read_another_panelists_enrollment
        """
        world = fx.screening_open_campaign(api, name="Owner Scope")
        owner = fx.create_panelist(api, display_name="Own One")
        peer = fx.create_panelist(api, display_name="Own Two")
        enrollment = fx.create_enrollment(
            api,
            world.campaign_id,
            owner["id"],
            screening_answers=screening_answers(household_size=4),
        )

        validate_error(
            api.get_enrollment(make_panelist_headers(peer["id"]), enrollment["id"]),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        own_read = validate_success(
            api.get_enrollment(make_panelist_headers(owner["id"]), enrollment["id"])
        )
        assert own_read["id"] == enrollment["id"]
        assert own_read["panelist_id"] == owner["id"]
        assert own_read["screening_status"] == "PENDING_SCREEN"


class TestHeaderLevelAuthentication:
    """The two rungs above the role check, kept apart by their status codes."""

    def test_an_empty_user_id_header_is_unauthenticated(self, api):
        """PRD §2.1: "Both headers must be present and non-empty, and `X-User-ID`
        must be a syntactically valid UUID; a request that violates any part of
        this is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §2.5: "`X-User-Role` and `X-User-ID` are both present and non-empty —
        otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/rbac/missing_user_id_header_is_unauthenticated
        """
        validate_error(
            api.raw_post(
                "/campaigns",
                payload=_campaign_payload("Headerless"),
                headers=make_headers("", "CampaignManager"),
            ),
            ERR_UNAUTHENTICATED,
            401,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0

    def test_a_role_name_outside_the_declared_six_is_unauthenticated(self, api):
        """PRD §2.1: "The platform recognises exactly six roles, spelled precisely
        as follows: `CampaignManager`, `ComplianceModerator`, `FulfillmentOps`,
        `Panelist`, `PlatformAdmin` and `Anonymous`. A value in `X-User-Role` that
        is not one of these six is also rejected with `ERR_UNAUTHENTICATED`."

        PRD §2.5: "`X-User-Role` names one of the six declared roles — otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/rbac/unknown_role_header_value_is_unauthenticated
        """
        validate_error(
            api.raw_post(
                "/campaigns",
                payload=_campaign_payload("Ghost Role"),
                headers=make_headers(MODERATOR_A_USER_ID, UNDECLARED_ROLE),
            ),
            ERR_UNAUTHENTICATED,
            401,
        )

        _, meta = validate_paginated(api.list_campaigns(campaign_manager_headers()))
        assert meta["total_count"] == 0
