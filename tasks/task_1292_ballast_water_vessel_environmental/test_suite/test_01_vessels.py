"""Vessel registration, retrieval, listing, and response-envelope tests."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_timestamp_equals,
    assert_vessel,
    create_vessel,
    create_vessel_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestVesselCreation:
    def test_vessel_create_returns_201_with_computed_defaults(self, api, shore_officer_headers):
        """PRD section 3.1: "A newly registered vessel starts with `version` 1 and
        `compliance_posture` `OPEN`."
        PRD section 3.1: "The `flag_state` is fixed to `US` for every vessel in this
        system."
        PRD section 4: "Creating a new resource returns HTTP 201; modifying an
        existing resource returns HTTP 200."

        Design: Corner/entities/vessel_create_returns_201_with_computed_defaults
        """
        set_clock()
        resp = api.create_vessel(
            create_vessel_payload(imo_number="9100001", vessel_name="MV Avery",
                                  gross_tonnage=52000, keel_laid_date="2009-01-01T00:00:00Z"),
            shore_officer_headers,
        )
        data = validate_success(resp, 201)
        assert_vessel(data)
        assert data["version"] == 1, f"new vessel version must start at 1, got {data['version']}"
        assert data["compliance_posture"] == "OPEN"
        assert data["flag_state"] == "US"

    def test_vessel_create_missing_imo_number_returns_400(self, api, shore_officer_headers,
                                                          flag_surveyor_headers):
        """PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409), and a generic request-body validation failure — a missing required
        field, a bad type, or a bad enum value — is rejected with `ERR_VALIDATION`
        (HTTP 400)."
        PRD section 3.1: "A `ShoreComplianceOfficer` registers a new US-flag vessel by
        supplying its `imo_number` (a unique 7-digit numeric string), `vessel_name`,
        `bwms_type` (one of `NONE`, `EXCHANGE_ONLY`, `TREATMENT_USCG_TYPE_APPROVED`,
        or `TREATMENT_ALTERNATIVE`), `gross_tonnage` (at least 1), `keel_laid_date`,
        and `ballast_capacity_m3` (greater than 0)."

        Design: Corner/entities/vessel_create_missing_imo_number_returns_400
        """
        payload = create_vessel_payload(vessel_name="MV Broken", bwms_type="EXCHANGE_ONLY")
        payload.pop("imo_number")
        resp = api.create_vessel(payload, shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        data, meta = validate_paginated(api.list_vessels(flag_surveyor_headers))
        assert meta["total_count"] == 0, "rejected vessel must not be persisted"

    def test_vessel_create_invalid_bwms_type_returns_400(self, api, shore_officer_headers):
        """PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409), and a generic request-body validation failure — a missing required
        field, a bad type, or a bad enum value — is rejected with `ERR_VALIDATION`
        (HTTP 400)."
        PRD section 3.1: "`bwms_type` (one of `NONE`, `EXCHANGE_ONLY`,
        `TREATMENT_USCG_TYPE_APPROVED`, or `TREATMENT_ALTERNATIVE`)"

        Design: Corner/entities/vessel_create_invalid_bwms_type_returns_400
        """
        payload = create_vessel_payload(
            imo_number="9100002", vessel_name="MV Badenum", bwms_type="MAGIC_BWMS",
            gross_tonnage=10000, keel_laid_date="2015-01-01T00:00:00Z",
            ballast_capacity_m3=5000,
        )
        resp = api.create_vessel(payload, shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_vessel_create_zero_gross_tonnage_returns_400(self, api, shore_officer_headers):
        """PRD section 3.1: "A `ShoreComplianceOfficer` registers a new US-flag vessel
        by supplying its `imo_number` (a unique 7-digit numeric string), `vessel_name`,
        `bwms_type` (one of `NONE`, `EXCHANGE_ONLY`, `TREATMENT_USCG_TYPE_APPROVED`,
        or `TREATMENT_ALTERNATIVE`), `gross_tonnage` (at least 1), `keel_laid_date`,
        and `ballast_capacity_m3` (greater than 0)."
        PRD section 2.5: "a generic request-body validation failure — a missing
        required field, a bad type, or a bad enum value — is rejected with
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/vessel_create_zero_gross_tonnage_returns_400
        """
        payload = create_vessel_payload(
            imo_number="9100003", vessel_name="MV ZeroGT", bwms_type="NONE",
            bwms_installation_date=None, gross_tonnage=0,
            keel_laid_date="2015-01-01T00:00:00Z", ballast_capacity_m3=5000,
        )
        resp = api.create_vessel(payload, shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_vessel_create_id_input_ignored(self, api, shore_officer_headers):
        """PRD section 2.4: "Every persisted entity carries a server-minted `id` that
        is a UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with
        three fractional digits, an `updated_at` timestamp in the same format, and a
        `version` integer that starts at 1 and increments by 1 on every mutation."

        Design: Corner/entities/vessel_create_id_input_ignored
        """
        supplied_id = "11111111-2222-4333-8444-555555555555"
        payload = create_vessel_payload(
            imo_number="9100012", vessel_name="MV IdSeed", bwms_type="NONE",
            bwms_installation_date=None, gross_tonnage=8000,
            keel_laid_date="2016-01-01T00:00:00Z", ballast_capacity_m3=4000,
        )
        payload["id"] = supplied_id
        resp = api.create_vessel(payload, shore_officer_headers)
        data = validate_success(resp, 201)
        assert_vessel(data)
        assert data["id"] != supplied_id, (
            "server-minted id must not echo the client-supplied id"
        )


class TestVesselRetrieval:
    def test_vessel_get_unknown_id_returns_404(self, api, shore_officer_headers):
        """PRD section 2.5: "Path parameters are validated left to right: each
        segment's identifier must resolve to an existing entity, and each child must
        belong to the ancestor named to its left. A failure at any segment is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/vessel_get_unknown_id_returns_404
        """
        resp = api.get_vessel(NON_EXISTENT_UUID, shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_vessel_get_response_envelope_shape(self, api, shore_officer_headers,
                                                platform_admin_headers):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD section 2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD section 2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/endpoints/vessel_get_response_envelope_shape
        """
        vessel = create_vessel(imo_number="9100054", vessel_name="MV Chiffchaff",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        resp = api.get_vessel(vessel["id"], platform_admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"].get("api_request_id", "").startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object", (
            f"single-resource GET must use response_type object, got {body['response_type']!r}"
        )
        assert body["data"]["imo_number"] == "9100054", "stored imo_number must round-trip"


class TestVesselListing:
    def test_vessel_list_pagination_limit_and_offset(self, api, shore_officer_headers,
                                                     flag_surveyor_headers):
        """PRD section 2.3: "List endpoints accept two query parameters: `limit`
        (default 10, minimum 1, maximum 100) and `offset` (default 0). Results are
        sorted by `created_at` ascending. The `meta` block of a list response includes
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/vessel_list_pagination_limit_and_offset
        """
        first = create_vessel(imo_number="9100010", vessel_name="MV PageOne",
                              bwms_type="NONE", gross_tonnage=9000,
                              keel_laid_date="2014-01-01T00:00:00Z", ballast_capacity_m3=4000)
        second = create_vessel(imo_number="9100011", vessel_name="MV PageTwo",
                               bwms_type="NONE", gross_tonnage=9500,
                               keel_laid_date="2014-06-01T00:00:00Z", ballast_capacity_m3=4500)

        page0, meta0 = validate_paginated(
            api.list_vessels(flag_surveyor_headers, params={"limit": 1, "offset": 0})
        )
        assert meta0["total_count"] == 2
        assert meta0["has_more"] is True
        assert len(page0) == 1

        page1, meta1 = validate_paginated(
            api.list_vessels(flag_surveyor_headers, params={"limit": 1, "offset": 1})
        )
        assert meta1["has_more"] is False
        assert len(page1) == 1

        seen = {page0[0]["id"], page1[0]["id"]}
        assert seen == {first["id"], second["id"]}, (
            "the two pages must partition the two registered vessels without overlap"
        )
