"""Crossing inventory creation, defaults, exposure computation, and pagination
(PRD §2.2, §2.3, §2.8, §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_crossing,
    create_crossing_payload,
    create_locality,
    get_success_data,
    setup_locality_and_crossing,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCrossingCreation:
    def test_crossing_create_applies_defaults(self, api, admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §3.1: "optionally a daily `school_bus_count` that defaults to 0 when
        omitted. ... A new crossing starts in `ACTIVE` status with `version` 1, and
        its derived risk profile is computed immediately."
        PRD §2.4: "`version` is a system-managed integer that starts at 1 when the
        resource is created and increments on mutation, providing the basis for
        optimistic concurrency control."

        Design: Corner/entities/crossing_create_applies_defaults
        """
        locality = create_locality(locality_name="Default City")
        payload = create_crossing_payload(
            dot_crossing_number="DOT-010001",
            road_authority_locality_id=locality["id"],
        )
        assert "school_bus_count" not in payload

        resp = api.create_crossing(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_crossing(data)
        assert resp.json()["response_type"] == "object"
        assert isinstance(resp.json()["meta"].get("api_request_id"), str)
        assert data["school_bus_count"] == 0, "omitted school_bus_count must default to 0"
        assert data["status"] == "ACTIVE"
        assert data["incident_count_5yr"] == 0
        assert data["version"] == 1
        # (365/365)*5000/1000 = 5.00; (5.00*1.10 + 0 + 0) * 1.00 * 1.00 = 5.50
        assert data["exposure_index"] == pytest.approx(5.00, abs=1e-9)
        assert data["hazard_score"] == pytest.approx(5.50, abs=1e-9)

    def test_crossing_create_rejects_client_supplied_computed_field(
        self, api, admin_headers
    ):
        """PRD §2.9: "general request-shape failures (`ERR_INVALID_REQUEST`:
        missing required fields, type mismatches, unknown fields, invalid enum
        values, negative counts, and the like)."

        Design: Corner/entities/crossing_computed_field_input_rejected
        """
        locality = create_locality(locality_name="Strict City")
        payload = create_crossing_payload(
            dot_crossing_number="DOT-010002",
            road_authority_locality_id=locality["id"],
        )
        payload["exposure_index"] = 999  # computed field smuggled into the request

        resp = api.create_crossing(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        listed, meta = validate_paginated(api.list_crossings(admin_headers))
        assert meta["total_count"] == 0, "rejected create must not persist a crossing"

    def test_crossing_get_not_found(self, api, admin_headers):
        """PRD §2.8: "The first reference that does not resolve to an existing
        resource produces the response, and each resource family has its own code:
        `ERR_CROSSING_NOT_FOUND` ... (all HTTP 404)."

        Design: Corner/entities/crossing_get_not_found
        """
        resp = api.get_crossing(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_CROSSING_NOT_FOUND, expected_status=404)
        assert resp.json()["response_type"] == "error"

    def test_crossing_list_pagination_and_status_filter(self, api, officer_headers):
        """PRD §2.3: "every list response carries `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object." and "Crossing lists accept `status`,
        `railroad_code`, `road_authority_locality_id`, and `diagnostic_review_due`."

        Design: Corner/entities/crossing_list_pagination_and_filter
        """
        locality = create_locality(locality_name="Page City")
        for n in range(11, 14):
            resp = api.create_crossing(
                create_crossing_payload(
                    dot_crossing_number=f"DOT-0100{n}",
                    road_authority_locality_id=locality["id"],
                ),
                TEST_USERS["admin_headers"],
            )
            assert resp.status_code == 201

        page1, meta1 = validate_paginated(
            api.list_crossings(officer_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        closed, meta_closed = validate_paginated(
            api.list_crossings(officer_headers, params={"status": "CLOSED"})
        )
        assert closed == []
        assert meta_closed["total_count"] == 0
        assert meta_closed["has_more"] is False


class TestExposureDualVariant:
    def test_snapshot_and_projected_exposure_diverge(self, api, admin_headers):
        """PRD §3.1: "The snapshot `exposure_index` is the crossing's average trains
        per day — its `annual_train_count` divided by 365 — multiplied by its `aadt`
        and divided by 1,000, with the result rounded half-up to 2 decimal places.
        The `projected_exposure_index` is a five-year planning variant of the same
        formula: the annual train count is first grown by compounding at two percent
        per year for five years, the AADT is grown by compounding at three percent
        per year for five years, and the snapshot formula is then applied to those
        grown figures; because both growth rates are positive, the projected figure
        is always strictly greater than the snapshot."

        Design: Difficulty/dual_variant_calc/crossing_exposure_snapshot_vs_projected
        """
        locality = create_locality(locality_name="City of Example")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-100001",
                road_authority_locality_id=locality["id"],
                highway_functional_class="ARTERIAL",
                annual_train_count=3650,
                train_speed_max_mph=40,
                aadt=2000,
                school_bus_count=4,
                sight_distance_rating=4,
                warning_device_class="GATES",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_crossing(data)
        assert data["exposure_index"] == pytest.approx(20.00, abs=1e-9)
        assert data["projected_exposure_index"] == pytest.approx(25.60, abs=1e-9)
        assert data["projected_exposure_index"] > data["exposure_index"]

    def test_snapshot_variant_drives_review_due_and_hazard(self, api, admin_headers):
        """PRD §3.1: "A crossing's `diagnostic_review_due` flag is `true` when its
        snapshot `exposure_index` reaches 10.00 or higher". PRD §3.1: "The raw score
        is the sum of exposure times its band multiplier, the incident term, and the
        bus term, all multiplied by the device factor and the sight multiplier; the
        final `hazard_score` is that raw score capped at 100 and rounded half-up to
        2 decimal places."

        Design: Difficulty/dual_variant_calc/crossing_exposure_snapshot_vs_projected
        """
        locality = create_locality(locality_name="City of Example")
        data = get_success_data(
            api.create_crossing(
                create_crossing_payload(
                    dot_crossing_number="DOT-100002",
                    road_authority_locality_id=locality["id"],
                    highway_functional_class="ARTERIAL",
                    annual_train_count=3650,
                    train_speed_max_mph=40,
                    aadt=2000,
                    school_bus_count=4,
                    sight_distance_rating=4,
                    warning_device_class="GATES",
                ),
                admin_headers,
            )
        )
        # (20.00*1.20 + 0 + 2.0) * 1.00 * 1.00 = 26.00
        assert data["hazard_score"] == pytest.approx(26.00, abs=1e-9)
        assert data["diagnostic_review_due"] is True
