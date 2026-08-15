"""Application intake: initial state, intake gates, and the outermost
request-shape / auth layers of the gatekeeping pipeline (PRD §2.1, §2.8, §3.1,
§3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_application,
    create_district,
    create_owner,
    create_property,
    get_success_data,
    make_applicant_headers,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


def test_application_initial_state_submitted(api):
    """PRD §3.2: "A freshly submitted application enters `SUBMITTED` status. From here it can only move forward into staff review, or out of the system by withdrawal (§3.5)."

    Design: Corner/state_machines/application_initial_state_submitted
    """
    owner = create_owner()
    prop = create_property(owner["id"])
    application = submit_application(
        prop["id"],
        owner["id"],
        work_items=[work_item("SITE_WORK", "wall", 60000)],
    )
    assert_application(application)
    assert application["status"] == "SUBMITTED"


def test_empty_work_items_rejected(api):
    """PRD §3.2: "The array must not be empty; an empty submission is rejected
    with `ERR_EMPTY_WORK_ITEMS`."

    Design: Corner/endpoints/empty_work_items_rejected
    """
    owner = create_owner()
    prop = create_property(owner["id"])
    response = api.create_application(
        {
            "property_id": prop["id"],
            "owner_id": owner["id"],
            "application_type": "ALTERATION",
            "is_visible_from_public_way": False,
            "after_the_fact": False,
            "work_items": [],
        },
        make_applicant_headers(owner["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EMPTY_WORK_ITEMS)


def test_iconic_contributing_demolition_prohibited(api):
    """PRD §3.2: "A `DEMOLITION` application for a `CONTRIBUTING` property in an
    `ICONIC`-tier district is prohibited outright and rejected with
    `ERR_DEMOLITION_PROHIBITED`."

    Design: Corner/validations/iconic_contributing_demolition_prohibited
    """
    district = create_district(name="Monument Quarter", significance_tier="ICONIC")
    owner = create_owner()
    prop = create_property(
        owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
    )
    response = api.create_application(
        {
            "property_id": prop["id"],
            "owner_id": owner["id"],
            "application_type": "DEMOLITION",
            "is_visible_from_public_way": True,
            "after_the_fact": False,
            "work_items": [work_item("DEMOLITION", "raze landmark", 900000)],
        },
        make_applicant_headers(owner["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DEMOLITION_PROHIBITED)

    applications, meta = validate_paginated(api.list_applications(STAFF))
    assert meta["total_count"] == 0, "no application may be persisted"


class TestDistrictReviewFreezesIntake:
    def test_district_boundary_review_blocks_submission(self, api):
        """PRD §3.1: "While a district sits in `BOUNDARY_REVIEW`, new
        application intake for properties inside it is frozen — submission
        attempts are rejected with `ERR_DISTRICT_UNDER_REVIEW` — though
        everything already in flight continues."

        Design: Difficulty/cross_entity_state_dependency/district_review_freezes_intake
        """
        district = create_district(name="Old Town")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])

        validate_success(
            api.update_district(district["id"], {"status": "BOUNDARY_REVIEW"}, STAFF)
        )
        response = api.create_application(
            {
                "property_id": prop["id"],
                "owner_id": owner["id"],
                "application_type": "ALTERATION",
                "is_visible_from_public_way": False,
                "after_the_fact": False,
                "work_items": [work_item("SITE_WORK", "fence", 50000)],
            },
            make_applicant_headers(owner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DISTRICT_UNDER_REVIEW)

    def test_district_reactivated_reenables_submission(self, api):
        """PRD §3.1: "Staff may later update the `boundary_description` or
        `significance_tier`, or move the district's `status` between `ACTIVE`
        and `BOUNDARY_REVIEW`; each such update increments the district's
        `version` by one."
        PRD §3.1: "While a district sits in `BOUNDARY_REVIEW`, new application
        intake for properties inside it is frozen — submission attempts are
        rejected with `ERR_DISTRICT_UNDER_REVIEW` — though everything already
        in flight continues."

        Design: Difficulty/cross_entity_state_dependency/district_review_freezes_intake
        """
        district = create_district(name="Old Town")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])

        get_success_data(api.update_district(district["id"], {"status": "BOUNDARY_REVIEW"}, STAFF))
        blocked = api.create_application(
            {
                "property_id": prop["id"],
                "owner_id": owner["id"],
                "application_type": "ALTERATION",
                "is_visible_from_public_way": False,
                "after_the_fact": False,
                "work_items": [work_item("SITE_WORK", "fence", 50000)],
            },
            make_applicant_headers(owner["id"]),
        )
        assert blocked.json()["data"]["error_id"] == "ERR_DISTRICT_UNDER_REVIEW"

        get_success_data(api.update_district(district["id"], {"status": "ACTIVE"}, STAFF))
        application = validate_success(
            api.create_application(
                {
                    "property_id": prop["id"],
                    "owner_id": owner["id"],
                    "application_type": "ALTERATION",
                    "is_visible_from_public_way": False,
                    "after_the_fact": False,
                    "work_items": [work_item("SITE_WORK", "fence", 50000)],
                },
                make_applicant_headers(owner["id"]),
            ),
            201,
        )
        assert application["status"] == "SUBMITTED"
        assert application["property_id"] == prop["id"]


def test_create_district_missing_auth_header(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/create_district_missing_auth_header
    """
    response = api.create_district(
        {"name": "No Auth", "boundary_description": "x", "significance_tier": "LOCAL"},
        None,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_create_district_forbidden(api):
    """PRD §2.1: "Access to specific operations is further restricted by role,
    per the endpoint authorization lists in §4; an attempt to perform an action
    outside the caller's designated role, or an `Applicant` attempt to act on
    another owner's application or appeal, is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/applicant_create_district_forbidden
    """
    response = api.create_district(
        {"name": "Applicant Attempt", "boundary_description": "x", "significance_tier": "LOCAL"},
        APPLICANT,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_create_district_missing_required_field(api):
    """PRD §2.8: "Malformed bodies, missing required fields, wrong-typed
    values, and enum values outside the declared sets are rejected at this
    same outermost layer with `ERR_VALIDATION`."

    Design: Corner/endpoints/create_district_missing_required_field
    """
    response = api.create_district(
        {"name": "No Tier", "boundary_description": "x"}, STAFF
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_list_districts_on_empty_inventory_returns_200(api):
    """PRD §4: "Retrieval endpoints, whether single-resource or list, return
    `200 OK`."
    PRD §2.3: "Paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/errors/error_catalog_covered_by_difficulty_and_corner_instances
    """
    data, meta = validate_paginated(api.list_districts(STAFF))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
