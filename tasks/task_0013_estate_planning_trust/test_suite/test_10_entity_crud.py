"""Corner-design coverage for entities section: creation, retrieval, listing,
not-found, defaults, FK validation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    set_clock,
    create_decedent,
    create_estate,
    NON_EXISTENT_UUID,
    make_planner_headers,
)


class TestEntityCreation:
    def test_create_decedent_returns_201_with_system_fields(self, api):
        """PRD §2.4: "Every persisted resource carries a server-minted id
        field which is a UUID string (lowercase, hyphenated, with no
        resource-type prefix). The two timestamp fields created_at and
        updated_at are ISO 8601 UTC strings with three fractional digits;
        created_at is set once at resource creation and never changes
        thereafter, while updated_at is refreshed on every mutation. The
        version field is a non-negative integer that starts at 1 on creation
        and increments by exactly one on every successful mutation of the row."

        Design: Corner/entities/create_decedent_returns_201_with_system_fields
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_decedent(
            {
                "full_legal_name": "Alpha One",
                "date_of_birth": "1950-01-01T00:00:00Z",
                "domicile_state_code": "CA",
                "ssn_last4": "0001",
            },
            make_planner_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"]), f"id must be UUID, got {data['id']!r}"
        assert data["version"] == 1, (
            f"created resource version must be 1, got {data['version']}"
        )
        assert is_iso8601_timestamp(data["created_at"]), (
            f"created_at must be ISO 8601, got {data['created_at']!r}"
        )


class TestEntityRetrieval:
    def test_get_nonexistent_estate_returns_not_found(self, api):
        """PRD §2.5: "Endpoints that embed an identifier in their path (for
        example /estates/{id} or /beneficiary-designations/{id}/activate)
        validate path parameters left to right. If any referenced resource
        — estate, asset, designation, executor, decedent, directive,
        guardianship, claim, or order — cannot be found, the response is
        ERR_NOT_FOUND (HTTP 404), returned before any role, state, or body
        validation runs."

        Design: Corner/entities/get_nonexistent_estate_returns_not_found
        """
        resp = api.get_estate(NON_EXISTENT_UUID, make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestDefaults:
    def test_estate_initial_status_is_draft_default(self, api):
        """PRD §3.1: "The new estate begins in DRAFT with its status so set,
        its gross_estate_value_cents at 0, its net_taxable_estate_cents at
        0, its inventory_snapshot_gross_cents null, its executor_user_id
        null, and the three lifecycle timestamps (probate_filed_at,
        probate_opened_at, closed_at) all null. The estate's version starts
        at 1."

        Design: Corner/entities/estate_initial_status_is_draft_default
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Beta Two",
            domicile_state_code="CA", ssn_last4="0002",
        )
        resp = api.create_estate(
            {"decedent_id": dec["id"]}, make_planner_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["gross_estate_value_cents"] == 0
        assert data["net_taxable_estate_cents"] == 0


class TestListing:
    def test_list_estates_paginated_envelope(self, api):
        """PRD §2.3: "Every list endpoint accepts two query-string parameters:
        limit and offset. The limit parameter defaults to 10, accepts a
        minimum value of 1, and accepts a maximum value of 100. The offset
        parameter defaults to 0 and represents the number of records to skip
        before the page begins. Each list response surfaces the four
        pagination fields — limit, offset, total_count, and has_more — inside
        meta, where total_count is the unfiltered count after any
        non-pagination query filters have been applied and has_more is true
        when offset + limit < total_count."

        Design: Corner/entities/list_estates_paginated_envelope
        """
        set_clock("2026-01-01T00:00:00Z")
        for i, st in enumerate(["CA", "NY", "TX"]):
            dec = create_decedent(
                full_legal_name=f"D{i+1}",
                date_of_birth=f"195{i}-01-01T00:00:00Z",
                domicile_state_code=st,
                ssn_last4=f"000{3+i}",
            )
            create_estate(dec["id"])

        resp = api.list_estates(
            make_planner_headers(), params={"limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert len(data) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        assert meta["has_more"] is True


# `Corner/entities/fk_estate_decedent_id_invalid_returns_not_found` is skipped
# under the PRD-first filter: the §2.5 not-found rule is scoped to path
# parameters ("Endpoints that embed an identifier in their path") and the §2.9
# ordering list also names only "URL path" existence. PRD does not commit on
# whether a body FK (decedent_id in the body of POST /estates) resolves to
# ERR_NOT_FOUND or to ERR_INVALID_REQUEST; two PRD-only readers could choose
# either, so unique derivability fails.
