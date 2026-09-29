"""Entity-level surface: creation echoes, read-backs, listings, defaults,
computed columns, system-managed fields and foreign-key resolution.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    benefit_payload,
    define_tier,
    log_influence_contact,
    read_funder,
    read_sustainability,
    register_funder,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS, FC_HEADERS
from test_helpers.test_users import USER_IDS

_UNKNOWN_MEMBER_ID = "11111111-1111-4111-8111-111111111111"
_UNKNOWN_COLLABORATION_ID = "22222222-2222-4222-8222-222222222222"
_UNKNOWN_AREA_ID = "33333333-3333-4333-8333-333333333333"


class TestFiscalPeriodCreation:
    def test_a_revenue_free_period_opens_at_watch_rather_than_healthy(self):
        """Creation echoes every supplied input, seeds the concentration figures at
        zero, and derives a posture immediately: 500000 against a 200000 base is
        2.5 months against a three-month target.

        PRD: "A period opens in status `OPEN` with `board_override_active` false,
        `board_override_justification` null and `locked_at` null, and with its full
        sustainability picture derived immediately - over an empty revenue input
        set, so `recognized_revenue_cents`, `concentration_hhi` and
        `top_source_share_bps` all start at 0, `reserve_months_target` starts at the
        base policy figure of three months, and `operating_reserve_target_cents`
        starts at three times the supplied expense base."

        Design: Corner/Entities/en_fiscal_period_creation_persists_inputs_and_seeds_derived_sustainability_fields
        """
        created = validate_success(
            api_client.create_fiscal_period(
                {
                    "label": "FY2027",
                    "start_date": "2026-08-01",
                    "end_date": "2027-07-31",
                    "monthly_expense_base_cents": 200000,
                    "reserve_balance_cents": 500000,
                },
                FC_HEADERS,
            ),
            expected_status=201,
        )
        assert created["label"] == "FY2027"
        assert created["start_date"] == "2026-08-01"
        assert created["end_date"] == "2027-07-31"
        assert created["monthly_expense_base_cents"] == 200000
        assert created["reserve_balance_cents"] == 500000
        assert created["status"] == "OPEN"
        assert created["board_override_active"] is False
        assert created["board_override_justification"] is None
        assert created["locked_at"] is None
        assert created["recognized_revenue_cents"] == 0
        assert created["concentration_hhi"] == 0
        assert created["top_source_share_bps"] == 0

        picture = read_sustainability(created["id"])
        assert picture["basis"] == "RECOGNIZED"
        assert picture["recognized_revenue_cents"] == 0
        assert picture["reserve_months_target"] == 3
        assert picture["operating_reserve_target_cents"] == 600000
        assert picture["reserve_months_ratio_bps"] == 25000
        assert picture["sustainability_posture"] == "WATCH"
        assert picture["restricted_release_cap_pct_bps"] == 6000


class TestMembershipTierRetrieval:
    def test_a_draft_tier_reads_back_its_computed_columns(self):
        """The threshold is derived at creation even for a benefit-free tier, so a
        DRAFT read already carries 50 rather than waiting for publication.

        PRD: "All four of those derived values are computed once, when the tier is
        created, and are immutable from then on; every membership contribution
        simply reads them."

        Design: Corner/Entities/en_membership_tier_retrieval_returns_every_stored_and_computed_field
        """
        tier = define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )

        read_back = validate_success(
            api_client.get_membership_tier(tier["id"], DO_HEADERS)
        )
        assert read_back["tier_code"] == "SUSTAINER"
        assert read_back["renewal_cadence"] == "MONTHLY"
        assert read_back["contribution_amount_cents"] == 2500
        assert read_back["status"] == "DRAFT"
        assert read_back["published_at"] is None
        assert read_back["grace_period_days"] == 30
        assert read_back["benefit_count"] == 0
        assert read_back["insubstantial_benefit_codes"] == []
        assert read_back["quid_pro_quo_per_period_cents"] == 0
        assert read_back["insubstantial_threshold_cents"] == 50


class TestMembershipTierListing:
    def test_total_count_measures_the_filtered_set_not_the_page(self):
        """Three DRAFT tiers paginate two-then-one while `total_count` stays at 3,
        and a cadence filter narrows the count itself.

        PRD: "`total_count` counts every row matching the request's filters, not
        merely the rows on the returned page, and `has_more` is true exactly when
        unreturned matching rows remain beyond the current page."

        Design: Corner/Entities/en_membership_tier_listing_paginates_with_total_count_and_has_more
        """
        define_tier(
            benefits=[],
            tier_code="BRONZE",
            name="Bronze",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )
        define_tier(
            benefits=[],
            tier_code="SILVER",
            name="Silver",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=5000,
        )
        define_tier(
            benefits=[],
            tier_code="GOLD",
            name="Gold",
            renewal_cadence="ANNUAL",
            contribution_amount_cents=30000,
        )

        first_page, first_meta = validate_paginated(
            api_client.list_membership_tiers(
                FC_HEADERS, params={"status": "DRAFT", "limit": 2, "offset": 0}
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api_client.list_membership_tiers(
                FC_HEADERS, params={"status": "DRAFT", "limit": 2, "offset": 2}
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        annual, annual_meta = validate_paginated(
            api_client.list_membership_tiers(
                FC_HEADERS, params={"renewal_cadence": "ANNUAL"}
            )
        )
        assert len(annual) == 1
        assert annual[0]["tier_code"] == "GOLD"
        assert annual_meta["total_count"] == 1
        assert annual_meta["has_more"] is False


class TestMemberNotFound:
    def test_an_unknown_member_id_reports_the_members_own_not_found_code(self):
        """Path-parameter resolution has its own rung on the ladder and its own
        per-entity code.

        PRD: "Path-parameter existence, resolved strictly left to right. Each entity
        has its own not-found code, and the code returned is the one belonging to the
        *first* path segment that fails to resolve"

        Design: Corner/Entities/en_member_get_with_unknown_id_returns_member_not_found
        """
        response = api_client.get_member(_UNKNOWN_MEMBER_ID, DO_HEADERS)
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}


class TestFunderRequiredFields:
    def test_legal_name_is_mandatory_while_the_optional_inputs_are_not(self):
        """The same shape of request succeeds once `legal_name` is present, and the
        two optional fields settle to null and false.

        PRD: "Optionally the officer records `affiliated_coverage_area_id`, the beat
        the funder has declared an interest in, which is left null for an
        unaffiliated funder; and `self_attested_advocacy`, the funder's own
        statement that it engages in advocacy on the beat it funds, which defaults
        to false."

        Design: Corner/Entities/en_funder_create_without_legal_name_returns_invalid_request
        """
        validate_error(
            api_client.create_funder({"funder_type": "FOUNDATION"}, DO_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        _, empty_meta = validate_paginated(api_client.list_funders(DO_HEADERS))
        assert empty_meta["total_count"] == 0

        created = validate_success(
            api_client.create_funder(
                {"legal_name": "Wexler Family Foundation", "funder_type": "FOUNDATION"},
                DO_HEADERS,
            ),
            expected_status=201,
        )
        assert created["legal_name"] == "Wexler Family Foundation"
        assert created["affiliated_coverage_area_id"] is None
        assert created["self_attested_advocacy"] is False
        assert created["status"] == "PROSPECT"
        assert created["risk_basis"] == "SELF_ATTESTED"
        assert created["reporting_reliability_bps"] == 10000
        assert created["independence_risk_score"] == 10


class TestMembershipTierDefaults:
    def test_the_grace_default_applies_on_absence_only(self):
        """An omitted `grace_period_days` becomes 30 while an explicit 7 survives
        untouched, and an omitted `benefits` array is empty.

        PRD: "An optional `grace_period_days` sets how long a member lingers after
        a missed renewal before lapsing; it defaults to 30 and must fall between 0
        and 120 inclusive."

        Design: Corner/Entities/en_membership_tier_omitted_grace_period_days_defaults_to_thirty
        """
        defaulted = validate_success(
            api_client.create_membership_tier(
                {
                    "tier_code": "DEFAULTGRACE",
                    "name": "Default Grace",
                    "renewal_cadence": "MONTHLY",
                    "contribution_amount_cents": 2500,
                    "benefits": [],
                },
                DO_HEADERS,
            ),
            expected_status=201,
        )
        assert defaulted["grace_period_days"] == 30
        assert defaulted["benefits"] == []
        assert defaulted["benefit_count"] == 0

        explicit = validate_success(
            api_client.create_membership_tier(
                {
                    "tier_code": "SHORTGRACE",
                    "name": "Short Grace",
                    "renewal_cadence": "MONTHLY",
                    "contribution_amount_cents": 2500,
                    "benefits": [],
                    "grace_period_days": 7,
                },
                DO_HEADERS,
            ),
            expected_status=201,
        )
        assert explicit["grace_period_days"] == 7


class TestMembershipTierComputedBenefitColumns:
    def test_a_monthly_tier_values_each_benefit_per_period_before_comparing(self):
        """On a 30000-cent monthly tier the threshold is 600, so a 6000-a-year tote
        at 500 a period drops out while a 12000-a-year pass at 1000 stays in.

        PRD: "Walking the `benefits` array in exactly the order the request
        supplied it, an `ANNUAL` tier takes each benefit's
        `annual_fair_market_value_cents` unchanged as that benefit's per-period fair
        market value, while a `MONTHLY` tier divides that annual figure by 12 and
        rounds the result half up to whole cents **for that benefit
        individually**."

        Design: Corner/Entities/en_membership_tier_computed_benefit_columns_derive_from_the_benefits_array
        """
        tier = define_tier(
            benefits=[
                benefit_payload("TOTE", "TOTE_BAG", 6000),
                benefit_payload("EVENTS", "EVENT_ACCESS", 12000),
            ],
            tier_code="PATRON",
            name="Patron",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=30000,
        )

        assert tier["benefit_count"] == 2
        assert tier["insubstantial_threshold_cents"] == 600
        assert tier["insubstantial_benefit_codes"] == ["TOTE"]
        assert tier["quid_pro_quo_per_period_cents"] == 1000


class TestFunderSystemManagedFields:
    def test_posted_status_score_and_owner_are_all_discarded(self):
        """The client's `CLEARED` status, its zero score and its spoofed owner are
        ignored in favour of the server's own values.

        PRD: "A new funder is created in status `PROSPECT` with `risk_basis` at
        `SELF_ATTESTED`, `reporting_reliability_bps` at 10000,
        `audited_advocacy_index` null, `prior_editorial_requests_count` and
        `lifetime_committed_cents` at 0, `cleared_by_user_id` and `restricted_at`
        null, and `cultivated_by_user_id` stamped with the registering officer's
        `X-User-ID`."

        Design: Corner/Entities/en_funder_status_and_score_input_ignored_on_create
        """
        created = validate_success(
            api_client.create_funder(
                {
                    "legal_name": "Ironwood Trust",
                    "funder_type": "FOUNDATION",
                    "status": "CLEARED",
                    "independence_risk_score": 0,
                    "cultivated_by_user_id": "user-spoofed",
                },
                DO_HEADERS,
            ),
            expected_status=201,
        )

        assert created["status"] == "PROSPECT"
        assert created["independence_risk_score"] == 10
        assert created["cultivated_by_user_id"] == USER_IDS["development_officer"]
        assert created["cleared_by_user_id"] is None
        assert created["restricted_at"] is None
        assert created["lifetime_committed_cents"] == 0
        assert created["version"] == 1
        assert created["id"]
        assert created["created_at"]
        assert created["updated_at"]

        assert read_funder(created["id"])["status"] == "PROSPECT"


class TestGrantProposalEnumConstraint:
    def test_an_undeclared_restriction_type_is_rejected_before_any_gate(self):
        """`CAPITAL_CAMPAIGN` is outside the enum, so nothing is persisted even
        though the funder and period both resolve.

        PRD: "A `DevelopmentOfficer` drafts a foundation or government grant
        proposal naming `funder_id`, `fiscal_period_id`, a `title`, the
        `requested_amount_cents` - at least 100000 - and a `restriction_type` of
        `UNRESTRICTED`, `PROGRAM_RESTRICTED` or `PROJECT_RESTRICTED`."

        Design: Corner/Entities/en_grant_proposal_invalid_enum_restriction_type_returns_invalid_request
        """
        period = validate_success(
            api_client.create_fiscal_period(
                {
                    "label": "FY2027",
                    "start_date": "2026-08-01",
                    "end_date": "2027-07-31",
                    "monthly_expense_base_cents": 200000,
                    "reserve_balance_cents": 500000,
                },
                FC_HEADERS,
            ),
            expected_status=201,
        )
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")

        validate_error(
            api_client.create_grant_proposal(
                {
                    "funder_id": funder["id"],
                    "fiscal_period_id": period["id"],
                    "title": "Housing beat capital",
                    "requested_amount_cents": 350000,
                    "restriction_type": "CAPITAL_CAMPAIGN",
                },
                DO_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(api_client.list_grant_proposals(DO_HEADERS))
        assert meta["total_count"] == 0


class TestInfluenceContactImmutability:
    def test_the_append_only_record_carries_no_concurrency_token(self):
        """A routine stewardship contact reads back with its audit fields and
        without the `version` every other entity exposes.

        PRD: "An influence contact is an immutable, append-only record: it carries
        only `id` and `created_at`. Both `updated_at` and `version` are absent from an
        influence contact, and no operation ever modifies one after it is written."

        Design: Corner/Entities/en_influence_contact_is_immutable_with_no_version_field
        """
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
        contact = log_influence_contact(
            funder["id"],
            contact_type="ROUTINE_STEWARDSHIP",
            occurred_at="2026-08-01T00:00:00Z",
            summary="Annual stewardship lunch; no coverage discussed.",
        )

        read_back = validate_success(
            api_client.get_influence_contact(contact["id"], ED_HEADERS)
        )
        assert read_back["severity_weight"] == 0
        assert read_back["triggered_restriction"] is False
        assert read_back["logged_by_user_id"] == USER_IDS["development_officer"]
        assert "version" not in read_back
        assert "updated_at" not in read_back
        assert read_back["created_at"]

        unchanged = read_funder(funder["id"])
        assert unchanged["status"] == "PROSPECT"
        assert unchanged["prior_editorial_requests_count"] == 0


class TestCollaborationPartnerParentResolution:
    def test_the_unknown_parent_is_reported_before_the_body_is_read(self):
        """A well-formed partner body under a non-existent collaboration reports the
        collaboration's own not-found code.

        PRD: "Path-parameter existence, resolved strictly left to right. Each entity
        has its own not-found code, and the code returned is the one belonging to the
        *first* path segment that fails to resolve"

        Design: Corner/Entities/en_collaboration_partner_create_under_unknown_collaboration_returns_not_found
        """
        validate_error(
            api_client.create_collaboration_partner(
                _UNKNOWN_COLLABORATION_ID,
                {
                    "partner_org_name": "Riverbend Public Media",
                    "credit_share_bps": 3300,
                    "cost_share_bps": 3300,
                },
                ED_HEADERS,
            ),
            ApiErrorId.ERR_COLLABORATION_NOT_FOUND,
        )


class TestFlatTopologyForeignKeyResolution:
    def test_an_unknown_beat_in_the_body_reports_the_coverage_area_code(self):
        """The path carries no coverage-area segment, yet the body's dangling
        reference is still resolved and reported with the beat's own code.

        PRD: "Body foreign-key existence, evaluated after every path id and in the
        order the fields are declared on the endpoint's input list, again returning
        the not-found code of the missing target entity."

        Design: Corner/Entities/en_flat_topology_unknown_affiliated_coverage_area_fk_returns_not_found
        """
        validate_error(
            api_client.create_funder(
                {
                    "legal_name": "Ironwood Trust",
                    "funder_type": "FOUNDATION",
                    "affiliated_coverage_area_id": _UNKNOWN_AREA_ID,
                },
                DO_HEADERS,
            ),
            ApiErrorId.ERR_COVERAGE_AREA_NOT_FOUND,
        )

        _, meta = validate_paginated(api_client.list_funders(DO_HEADERS))
        assert meta["total_count"] == 0
