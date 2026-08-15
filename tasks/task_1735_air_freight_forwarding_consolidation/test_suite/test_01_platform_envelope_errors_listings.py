"""Platform-level contracts: response envelope, error catalog, auth, listings."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_shipper,
    create_flight_booking_payload,
    create_hwb,
    create_master_waybill_payload,
    create_shipper,
    file_rate_agreement,
    get_hwb,
    setup_consolidated,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_HWB = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_BOOKING = "00000000-0000-4000-8000-0000000000bb"
UNKNOWN_SHIPPER = "00000000-0000-4000-8000-0000000000ff"


class TestResponseEnvelope:
    def test_success_and_error_envelope_shape(
        self, api, forwarder_ops_headers, claims_adjuster_headers
    ):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        shipper = create_shipper()

        ok = api.get_shipper(shipper["id"], claims_adjuster_headers)
        data = validate_success(ok)
        assert_shipper(data)
        assert ok.json()["response_type"] == "object"
        assert data["account_code"] == "ACME"
        meta = ok.json()["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert isinstance(meta["api_request_timestamp"], str)

        err = api.get_shipper(UNKNOWN_SHIPPER, claims_adjuster_headers)
        validate_error(err, ApiErrorId.ERR_SHIPPER_NOT_FOUND)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }
        assert err_body["data"]["message"]


class TestNotFoundFamily:
    def test_not_found_family_covers_all_resources(
        self,
        api,
        forwarder_ops_headers,
        compliance_officer_headers,
        customs_broker_headers,
    ):
        """PRD §2.6: "Existence — resource identifiers in the path, then identifiers
        referenced in the body, validated left to right; the first missing resource
        produces its specific 404 (`ERR_SHIPPER_NOT_FOUND`, `ERR_FLIGHT_BOOKING_NOT_FOUND`,
        `ERR_MASTER_WAYBILL_NOT_FOUND`, `ERR_HOUSE_WAYBILL_NOT_FOUND`,
        `ERR_SCREENING_RECORD_NOT_FOUND`, `ERR_CUSTOMS_ENTRY_NOT_FOUND`, or
        `ERR_CLAIM_NOT_FOUND`)."

        Design: Corner/errors/not_found_family_covers_all_resources
        """
        validate_error(
            api.get_shipper("00000000-0000-4000-8000-000000000001", forwarder_ops_headers),
            ApiErrorId.ERR_SHIPPER_NOT_FOUND,
        )
        validate_error(
            api.get_flight_booking(
                "00000000-0000-4000-8000-000000000002", forwarder_ops_headers
            ),
            ApiErrorId.ERR_FLIGHT_BOOKING_NOT_FOUND,
        )
        validate_error(
            api.resolve_screening_record(
                "00000000-0000-4000-8000-000000000003",
                {"outcome": "CLEARED"},
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_SCREENING_RECORD_NOT_FOUND,
        )
        validate_error(
            api.transition_customs_entry(
                "00000000-0000-4000-8000-000000000004",
                {"target_status": "FILED"},
                customs_broker_headers,
            ),
            ApiErrorId.ERR_CUSTOMS_ENTRY_NOT_FOUND,
        )
        validate_error(
            api.get_claim("00000000-0000-4000-8000-000000000005", forwarder_ops_headers),
            ApiErrorId.ERR_CLAIM_NOT_FOUND,
        )


class TestAuthAndExistenceOrdering:
    def test_missing_auth_header_returns_400(self, api, forwarder_ops_headers):
        """PRD §2.1: "A request missing either header, or carrying a role the system
        does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/errors/missing_auth_header_returns_400
        """
        shipper = create_shipper()
        resp = api.get_shipper(shipper["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_forbidden_role_beats_not_found(self, api, pricing_manager_headers):
        """PRD §2.6: "When several validation rules could reject the same request, the
        system evaluates them in a fixed priority order so that the surfaced error is
        deterministic:"
        PRD §2.6: "2. Role authorization — the caller's role is permitted for this
        operation, honoring the per-target role map on customs transitions
        (`ERR_FORBIDDEN_ROLE`)."

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        resp = api.submit_house_waybill(UNKNOWN_HWB, pricing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_path_existence_validated_left_to_right(
        self, api, forwarder_ops_headers, capacity_planner_headers
    ):
        """PRD §2.6: "Existence — resource identifiers in the path, then identifiers
        referenced in the body, validated left to right; the first missing resource
        produces its specific 404"

        Design: Corner/validations/path_existence_validated_left_to_right
        """
        resp = api.consolidate_house_waybill(
            "00000000-0000-4000-8000-0000000000dd",
            {
                "hwb_id": "00000000-0000-4000-8000-0000000000ee",
                "expected_master_waybill_version": 1,
            },
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MASTER_WAYBILL_NOT_FOUND)


class TestResourceLookups:
    def test_get_nonexistent_house_waybill_returns_not_found(
        self, api, forwarder_ops_headers
    ):
        """PRD §2.6: "Existence — resource identifiers in the path, then identifiers
        referenced in the body, validated left to right; the first missing resource
        produces its specific 404 (`ERR_SHIPPER_NOT_FOUND`, `ERR_FLIGHT_BOOKING_NOT_FOUND`,
        `ERR_MASTER_WAYBILL_NOT_FOUND`, `ERR_HOUSE_WAYBILL_NOT_FOUND`,
        `ERR_SCREENING_RECORD_NOT_FOUND`, `ERR_CUSTOMS_ENTRY_NOT_FOUND`, or
        `ERR_CLAIM_NOT_FOUND`)."

        Design: Corner/entities/get_nonexistent_house_waybill_returns_not_found
        """
        resp = api.get_house_waybill(UNKNOWN_HWB, forwarder_ops_headers)
        validate_error(resp, ApiErrorId.ERR_HOUSE_WAYBILL_NOT_FOUND)

    def test_master_waybill_with_unknown_booking_returns_not_found(
        self, api, capacity_planner_headers
    ):
        """PRD §2.6: "Existence — resource identifiers in the path, then identifiers
        referenced in the body, validated left to right; the first missing resource
        produces its specific 404"

        Design: Corner/entities/master_waybill_with_unknown_booking_returns_not_found
        """
        resp = api.create_master_waybill(
            create_master_waybill_payload(UNKNOWN_BOOKING, mawb_number="180-00000001"),
            capacity_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_BOOKING_NOT_FOUND)


class TestListings:
    def test_house_waybill_list_pagination_and_filters(
        self, api, forwarder_ops_headers
    ):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100.
        The `offset` parameter sets how many items to skip and defaults to 0."
        PRD §2.3: "List responses carry four pagination fields in the `meta` object of
        the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/house_waybill_list_pagination_and_filters
        """
        shipper = create_shipper()
        other_shipper = create_shipper(name="Beta Freight", account_code="BETA")
        for number in ("HWB-P1", "HWB-P2", "HWB-P3"):
            create_hwb(
                shipper["id"],
                number,
                pieces=1,
                gross_weight_kg=10.0,
                declared_volume_m3=0.05,
            )

        page1, meta1 = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers,
                params={"shipper_id": shipper["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers,
                params={"shipper_id": shipper["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1, f"page 2 must hold the last row, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        _rows, meta3 = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers, params={"shipper_id": other_shipper["id"]}
            )
        )
        assert meta3["total_count"] == 0, "filter for a shipper with no waybills must be empty"

    def test_fk_reverse_listings_return_children(self, api, forwarder_ops_headers):
        """PRD §4: "`/air-freight/flight-bookings/{id}/master-waybills` | List master
        waybills of a booking"
        PRD §4: "`/air-freight/house-waybills` | List house waybills with optional
        filters `shipper_id`, `mawb_id`, `status`, `rate_agreement_id`"
        PRD §4: "`/air-freight/house-waybills/{id}/screening-records` | List screening
        records of a waybill, SECURITY before DANGEROUS_GOODS within one submit"
        PRD §4: "`/air-freight/master-waybills/{id}/milestone-events` | List milestone
        events of a master waybill"

        Design: Corner/endpoints/fk_reverse_listings_return_children
        """
        ctx = setup_consolidated()
        booking = ctx["booking"]
        mawb = ctx["mawb"]
        hwb = ctx["hwb"]
        shipper = ctx["shipper"]

        mawbs, mawb_meta = validate_paginated(
            api.list_booking_master_waybills(booking["id"], forwarder_ops_headers)
        )
        assert mawb_meta["total_count"] == 1
        assert mawbs[0]["id"] == mawb["id"]

        by_mawb, mawb_filter_meta = validate_paginated(
            api.list_house_waybills(forwarder_ops_headers, params={"mawb_id": mawb["id"]})
        )
        assert mawb_filter_meta["total_count"] == 1
        assert by_mawb[0]["id"] == hwb["id"]

        _by_shipper, shipper_filter_meta = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers, params={"shipper_id": shipper["id"]}
            )
        )
        assert shipper_filter_meta["total_count"] == 1

        records, rec_meta = validate_paginated(
            api.list_screening_records(hwb["id"], forwarder_ops_headers)
        )
        assert rec_meta["total_count"] == 1
        assert records[0]["result"] == "CLEARED"

        events, ev_meta = validate_paginated(
            api.list_milestone_events(mawb["id"], forwarder_ops_headers)
        )
        assert ev_meta["total_count"] == 0
        assert events == []
