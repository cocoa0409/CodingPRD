"""Prospect/fundraiser/naming creation defaults, schema rejections, listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_prospect_payload, create_fundraiser_payload, create_naming_opportunity_payload,
    assert_prospect, assert_fundraiser, assert_naming_opportunity,
)

RES = TEST_USERS["researcher_headers"]
VP = TEST_USERS["vp_headers"]


class TestProspectCreation:
    def test_prospect_creation_applies_defaults_and_initial_states(self, api):
        """PRD §3.2: "A new prospect enters with `research_status` `IDENTIFIED` and
        `moves_stage` `QUALIFICATION` — the two parallel dimensions of §2.9 — with
        `capacity_band`, `affinity_score`, `rated_assessment_id`, and
        `rated_adjusted_capacity_cents` all null until the first approved rating,
        and with `lifetime_given_cents`, `outstanding_pledge_cents`, and
        `recognition_society_id` initialized to zero, zero, and null respectively."

        Design: Corner/entities/prospect_creation_applies_defaults_and_initial_states
        """
        resp = api.create_prospect(create_prospect_payload(full_name="New Prospect", contact_email="n@x.com"), RES)
        created = validate_success(resp, expected_status=201)
        assert_prospect(created)

        data = validate_success(api.get_prospect(created["id"], RES))
        assert data["research_status"] == "IDENTIFIED"
        assert data["moves_stage"] == "QUALIFICATION"
        assert data["lifetime_given_cents"] == 0
        assert data["outstanding_pledge_cents"] == 0
        assert data["capacity_band"] is None
        assert data["rated_assessment_id"] is None
        assert data["recognition_society_id"] is None
        assert data["version"] == 1

    def test_prospect_missing_required_field_rejected(self, api):
        """PRD §2.10: "The body is well-formed: required fields present, types
        correct, enum values within their declared sets, integer money fields
        positive, unknown fields rejected, and split structures well-formed;
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/prospect_missing_required_field_rejected
        """
        resp = api.create_prospect(
            {"full_name": "No Type", "contact_email": "n@x.com"}, RES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_prospect_invalid_enum_rejected(self, api):
        """PRD §3.2: "A `ProspectResearcher` creates a **prospect** with a
        `full_name`, a `prospect_type` of `INDIVIDUAL` or `ORGANIZATION`, and a
        `contact_email`."
        PRD §2.10: "The body is well-formed: required fields present, types
        correct, enum values within their declared sets, integer money fields
        positive, unknown fields rejected, and split structures well-formed;
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/prospect_invalid_enum_rejected
        """
        resp = api.create_prospect(
            {"full_name": "Bad Enum", "prospect_type": "COMPANY", "contact_email": "b@x.com"}, RES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_prospect_get_not_found_returns_404(self, api):
        """PRD §2.8: "`ERR_PROSPECT_NOT_FOUND` for an unresolvable prospect segment
        or a `prospect_id` body reference."

        Design: Corner/entities/prospect_get_not_found_returns_404
        """
        resp = api.get_prospect("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", RES)
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_FOUND)

    def test_prospect_computed_field_input_rejected(self, api):
        """PRD §2.10: "The body is well-formed: required fields present, types
        correct, enum values within their declared sets, integer money fields
        positive, unknown fields rejected, and split structures well-formed;
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/prospect_computed_field_input_rejected
        """
        resp = api.create_prospect(
            {"full_name": "Sneaky", "prospect_type": "INDIVIDUAL",
             "contact_email": "s@x.com", "lifetime_given_cents": 5}, RES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFundraiserCreation:
    def test_fundraiser_creation_initializes_counters(self, api):
        """PRD §3.1: "A new fundraiser starts with `status` `ACTIVE`,
        `current_prospect_count` at zero, and `current_open_ask_cents` at zero;
        the two counters are computed by the system thereafter and are never set
        directly."

        Design: Corner/entities/fundraiser_creation_initializes_counters
        """
        resp = api.create_fundraiser(
            create_fundraiser_payload(max_prospect_count=3, max_open_ask_cents=1000000), VP,
        )
        created = validate_success(resp, expected_status=201)
        assert_fundraiser(created)

        data = validate_success(api.get_fundraiser(created["id"], VP))
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["current_prospect_count"] == 0
        assert data["current_open_ask_cents"] == 0


class TestNamingOpportunityCreation:
    def test_naming_opportunity_creation_initializes_available(self, api):
        """PRD §3.5: "A `VPAdvancement` creates each **naming opportunity** with a
        `name`, a `category` of `BUILDING`, `ENDOWED_CHAIR`, `SCHOLARSHIP`, or
        `PROGRAM`, and a positive integer `price_floor_cents`; it starts
        `AVAILABLE`."

        Design: Corner/entities/naming_opportunity_creation_initializes_available
        """
        resp = api.create_naming_opportunity(create_naming_opportunity_payload(), VP)
        created = validate_success(resp, expected_status=201)
        assert_naming_opportunity(created)

        data = validate_success(api.get_naming_opportunity(created["id"], VP))
        assert data["status"] == "AVAILABLE"
        assert data["reserved_by_agreement_id"] is None
        assert data["reserved_until"] is None


class TestAssessmentCreation:
    def test_assessment_create_leaves_computed_fields_null(self, api):
        """PRD §3.2: "The assessment is born `SUBMITTED`, records the filer's
        `X-User-ID` as `created_by`, and its `prospect_id` ties it to the
        subject. Filing the first assessment moves the prospect from `IDENTIFIED`
        to `IN_SCREENING`."

        Design: Corner/entities/assessment_create_leaves_computed_fields_null
        """
        from test_helpers import create_prospect, create_assessment_payload
        p = create_prospect()
        resp = api.create_assessment(p["id"], create_assessment_payload(), RES)
        assessment = validate_success(resp, expected_status=201)
        assert assessment["status"] == "SUBMITTED"
        assert assessment["capacity_band_result"] is None
        assert assessment["adjusted_capacity_cents"] is None
        assert assessment["affinity_score_result"] is None

        p_after = validate_success(api.get_prospect(p["id"], RES))
        assert p_after["research_status"] == "IN_SCREENING"


class TestProspectListing:
    def test_prospects_list_paginates_with_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/prospects_list_paginates_with_limit_offset
        """
        from test_helpers import create_prospect
        create_prospect(full_name="P1", contact_email="p1@x.com")
        create_prospect(full_name="P2", contact_email="p2@x.com")
        create_prospect(full_name="P3", contact_email="p3@x.com")

        page1, meta1 = validate_paginated(api.list_prospects(RES, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(api.list_prospects(RES, params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1
