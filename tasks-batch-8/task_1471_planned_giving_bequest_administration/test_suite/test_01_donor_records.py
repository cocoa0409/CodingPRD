"""Donor records: creation defaults, envelope shape, schema conformance, listing.

Covers the Donor resource surface: system-managed defaults at creation, the
error envelope on missing resources, required-field and unknown-field schema
rejection, and list-endpoint pagination defaults.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_donor,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDonorCreationDefaults:
    def test_donor_create_applies_system_defaults(self, api, gift_officer_headers):
        """PRD §3.1: "The vital axis, `vital_status`, begins at `LIVING` and moves
        to `DECEASED`, which is terminal; the date of death is recorded on
        `deceased_on` and remains null while the donor is `LIVING`. The
        stewardship axis, `legacy_society_status`, begins at `NONE`"
        PRD §3.1: "`documented_gift_total_cents` is a live-computed field equal
        to the sum of `gift_amount_cents` over the donor's agreements in exactly
        that six-status set".
        PRD §2.5: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/donor_create_applies_defaults
        """
        resp = api.create_donor(
            {"full_name": "Defaults Donor", "date_of_birth": "1960-01-01T00:00:00Z"},
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        assert_donor(data)
        assert data["vital_status"] == "LIVING"
        assert data["legacy_society_status"] == "NONE"
        assert data["documented_gift_total_cents"] == 0
        assert data["deceased_on"] is None
        assert is_valid_uuid(data["id"])

    def test_donor_get_not_found_returns_404(self, api, gift_officer_headers):
        """PRD §2.10: "Existence: every path identifier and every foreign-key-valued
        body field resolves to an existing resource, validated left to right —
        path parameters first, then body fields — `ERR_NOT_FOUND`."
        PRD §5: `ERR_NOT_FOUND` maps to HTTP 404.

        Design: Corner/entities/donor_get_not_found_returns_404
        """
        resp = api.get_donor(NON_EXISTENT_UUID, gift_officer_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error["error_id"] == "ERR_NOT_FOUND"
        assert resp.status_code == 404


class TestDonorSchemaConformance:
    def test_donor_create_missing_required_field_rejected(self, api, gift_officer_headers):
        """PRD §3.1: "A `GiftOfficer` registers a donor by supplying the donor's
        `full_name` and `date_of_birth` (an ISO 8601 date), optionally with a
        `contact_email`."
        PRD §2.10: "Envelope and schema conformance — `ERR_INVALID_REQUEST`:
        unknown fields, malformed types, invalid enum members, missing required
        fields, a `valuation_date` outside its own coverage window, or a
        `defer_until` not in the future."

        Design: Corner/entities/donor_create_missing_required_field_rejected
        """
        resp = api.create_donor(
            {"date_of_birth": "1960-01-01T00:00:00Z"}, gift_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_donor_create_with_system_fields_rejected(self, api, gift_officer_headers):
        """PRD §2.5: every resource carries "a standard set of system-managed
        fields" (id, created_at, updated_at, version).
        PRD §2.10: "Envelope and schema conformance — `ERR_INVALID_REQUEST`:
        unknown fields, malformed types, invalid enum members, missing required
        fields, a `valuation_date` outside its own coverage window, or a
        `defer_until` not in the future."

        Design: Corner/entities/donor_create_with_system_fields_rejected
        """
        resp = api.create_donor(
            {
                "full_name": "Sneaky",
                "date_of_birth": "1960-01-01T00:00:00Z",
                "vital_status": "DECEASED",
                "version": 99,
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestDonorListing:
    def test_donor_list_pagination_defaults_and_envelope(
        self, api, gift_officer_headers, finance_steward_headers
    ):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/donor_list_pagination_defaults_and_envelope
        """
        for i in range(3):
            resp = api.create_donor(
                {"full_name": f"P{i+1}", "date_of_birth": f"196{i}-01-01T00:00:00Z"},
                gift_officer_headers,
            )
            validate_success(resp, 201)

        resp = api.list_donors(finance_steward_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
