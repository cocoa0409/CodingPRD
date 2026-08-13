"""Customers, properties, site assessments, response envelope, and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_assessment,
    assert_customer,
    assert_property,
    assert_weather_snapshot,
    create_assessment,
    create_customer,
    create_property,
    create_submitted_assessment,
    is_valid_uuid,
    post_weather_snapshot,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestCustomerCreation:
    def test_customer_creation_echoes_inputs_with_envelope(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." PRD §2.4: "`version`
        (integer): a system-managed counter starting at 1 that increments by
        one on every mutation of the resource". PRD §3.1: "An `OfficeAdmin`
        registers each customer with a `name`, a `customer_type` of
        `RESIDENTIAL` or `COMMERCIAL`, and contact details (`email` and
        `phone`)."

        Design: Corner/entities/customer_creation_retrieval_and_envelope
        """
        resp = api.create_customer(
            {
                "name": "Dana Homeowner",
                "customer_type": "RESIDENTIAL",
                "email": "dana@example.com",
                "phone": "555-9001",
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["version"] == 1, f"new customer version must be 1, got {data['version']}"
        assert is_valid_uuid(data["id"]), "id must be a prefix-less UUID"
        assert data["name"] == "Dana Homeowner"
        assert data["customer_type"] == "RESIDENTIAL"

        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"

        fetched = validate_success(api.get_customer(data["id"], ADMIN))
        assert fetched["name"] == "Dana Homeowner"
        assert fetched["customer_type"] == "RESIDENTIAL"


class TestPropertyComputedArea:
    def test_submit_refreshes_area_and_supersedes_prior(self, api):
        """PRD §3.2: "Submitting an assessment — permitted only while it is
        `DRAFT`, else `ERR_ASSESSMENT_NOT_SUBMITTABLE` — stamps `submitted_at`
        with the current clock and triggers two cascades: any other
        `SUBMITTED` assessment for the same property flips to `SUPERSEDED`,
        and the property's `current_area_sqft` refreshes to this assessment's
        measured area, incrementing the property's `version`."

        Design: Corner/entities/property_computed_area_and_assessment_supersede
        """
        customer = create_customer()
        prop = create_property(customer["id"])
        assert prop["version"] == 1

        a1 = create_assessment(prop["id"], measured_area_sqft=1000, crack_linear_ft=10)
        submit_assessment(a1["id"])
        mid = validate_success(api.get_property(prop["id"], ADMIN))
        assert mid["current_area_sqft"] == 1000
        assert mid["version"] == 2, f"first submit increments version to 2, got {mid['version']}"

        a2 = create_assessment(prop["id"], measured_area_sqft=1500, crack_linear_ft=5)
        submit_assessment(a2["id"])

        prop_after = validate_success(api.get_property(prop["id"], ADMIN))
        assert_property(prop_after)
        assert prop_after["current_area_sqft"] == 1500, (
            f"current_area_sqft must track the latest SUBMITTED assessment, got {prop_after['current_area_sqft']}"
        )
        assert prop_after["version"] == 3, (
            f"each submit increments the property version: expected 3, got {prop_after['version']}"
        )

        a1_after = validate_success(api.get_assessment(a1["id"], ESTIMATOR))
        a2_after = validate_success(api.get_assessment(a2["id"], ESTIMATOR))
        assert a1_after["status"] == "SUPERSEDED"
        assert a2_after["status"] == "SUBMITTED"


class TestAssessmentSubmit:
    def test_double_submit_rejected(self, api):
        """PRD §3.2: "Submitting an assessment — permitted only while it is
        `DRAFT`, else `ERR_ASSESSMENT_NOT_SUBMITTABLE`".

        Design: Corner/state_machines/assessment_double_submit_rejected
        """
        customer = create_customer()
        prop = create_property(customer["id"])
        assessment = create_assessment(prop["id"])
        first = submit_assessment(assessment["id"])
        assert first["status"] == "SUBMITTED"
        assert first["submitted_at"] is not None

        err = api.submit_assessment(assessment["id"], ESTIMATOR)
        validate_error(err, ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTABLE)

        after = validate_success(api.get_assessment(assessment["id"], ESTIMATOR))
        assert_assessment(after)
        assert after["status"] == "SUBMITTED"
        assert after["submitted_at"] == first["submitted_at"], (
            "failed resubmission must not restamp submitted_at"
        )


class TestPavementConditionIndex:
    def test_pci_weighted_scoring_moderate_and_capped(self, api):
        """PRD §3.2: "The crack deduction is the crack footage divided by the
        measured area, multiplied by 400, rounded half-up to an integer, and
        capped at 40. The pothole deduction is the pothole area divided by the
        measured area, multiplied by 700, rounded half-up to an integer, and
        capped at 35. The oil deduction is the oil-spot area divided by the
        measured area, multiplied by 300, rounded half-up to an integer, and
        capped at 15. The slope deduction is 10 points for `STEEP`, 5 for
        `MODERATE`, and 0 for `NONE`."

        Design: Corner/calculations/pci_weighted_scoring_with_caps
        """
        customer = create_customer()
        p1 = create_property(customer["id"], address="1 Elm St")
        p2 = create_property(customer["id"], address="9 Elm St")

        moderate = validate_success(
            api.create_assessment(
                {
                    "property_id": p1["id"],
                    "measured_area_sqft": 1200,
                    "crack_linear_ft": 40,
                    "pothole_count": 2,
                    "pothole_area_sqft": 10,
                    "oil_spot_area_sqft": 5,
                    "slope_severity": "NONE",
                },
                ESTIMATOR,
            ),
            201,
        )
        # deductions: min(40, r(13.33))=13, min(35, r(5.83))=6, min(15, r(1.25))=1, 0
        assert moderate["pavement_condition_index"] == 80, (
            f"PCI must be 100 - (13+6+1+0) = 80, got {moderate['pavement_condition_index']}"
        )

        catastrophic = validate_success(
            api.create_assessment(
                {
                    "property_id": p2["id"],
                    "measured_area_sqft": 1000,
                    "crack_linear_ft": 200,
                    "pothole_count": 12,
                    "pothole_area_sqft": 100,
                    "oil_spot_area_sqft": 100,
                    "slope_severity": "STEEP",
                },
                ESTIMATOR,
            ),
            201,
        )
        # raw 80/70/30 saturate caps 40/35/15; slope 10 -> max(0, 100-100) = 0
        assert catastrophic["pavement_condition_index"] == 0, (
            f"PCI must floor at 0 after caps, got {catastrophic['pavement_condition_index']}"
        )


class TestWeatherSnapshotImmutability:
    def test_snapshot_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "The sole exception is the weather snapshot: a weather
        observation or forecast is an immutable fact once posted, so weather
        snapshots carry only `id` and `created_at` — `updated_at` and
        `version` are absent from that resource."

        Design: Corner/entities/weather_snapshot_immutable_event_entity
        """
        snap = post_weather_snapshot("2026-08-10")
        assert_weather_snapshot(snap)

        data, meta = validate_paginated(
            api.list_weather_snapshots(DISPATCHER, params={"target_date": "2026-08-10"})
        )
        assert len(data) == 1
        assert_weather_snapshot(data[0])
        assert data[0]["id"] == snap["id"]


class TestNotFound:
    def test_get_unknown_work_order_returns_404(self, api):
        """PRD §2.11: "then existence of every referenced identifier, with
        path identifiers validated left-to-right". PRD §5:
        `ERR_WORK_ORDER_NOT_FOUND` | 404.

        Design: Corner/entities/not_found_on_unknown_work_order_id
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND, 404)


class TestPagination:
    def test_limit_offset_has_more_total_count(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum accepted value of 1 and a maximum of
        100. The `offset` parameter specifies how many items to skip and
        defaults to 0." and "The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_interaction
        """
        for i in (1, 2, 3):
            create_customer(
                name=f"C{i}",
                customer_type="RESIDENTIAL" if i != 2 else "COMMERCIAL",
                email=f"c{i}@example.com",
                phone=str(i),
            )

        page1, meta1 = validate_paginated(
            api.list_customers(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_customers(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        all_items, meta3 = validate_paginated(api.list_customers(ADMIN))
        assert len(all_items) == 3, "default limit 10 returns all 3"
        assert meta3["limit"] == 10
        assert meta3["has_more"] is False
