"""Patron registration defaults, listing envelope, and existence checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_patron,
    create_patron,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPatronComputedDefaults:
    def test_create_patron_applies_computed_defaults(self, api, admin_headers):
        """PRD §3.1: "At creation the patron's `outstanding_balance_cents` is
        `0` and `standing` is `GOOD_STANDING`."
        PRD §2.4: "`version` — an integer starting at `1` on creation and
        incremented by exactly `1` on every mutation of that entity."

        Design: Corner/entities/create_patron_applies_computed_defaults
        """
        resp = api.create_patron(
            {
                "full_name": "New Patron",
                "campus_role": "FACULTY",
                "residency": "ON_CAMPUS",
                "primary_commute_mode": "WALK",
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_patron(data)
        assert data["standing"] == "GOOD_STANDING", (
            f"new patron standing must be GOOD_STANDING, got {data['standing']}"
        )
        assert data["outstanding_balance_cents"] == 0, (
            f"new patron balance must be 0, got {data['outstanding_balance_cents']}"
        )
        assert data["version"] == 1, f"new patron version must be 1, got {data['version']}"


class TestPatronListing:
    def test_list_patrons_paginates_with_envelope(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`
        (default `10`, minimum `1`, maximum `100`) and `offset` (default `0`).
        The `meta` block of every list response includes `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_patrons_paginates_with_envelope
        """
        create_patron(full_name="P1", campus_role="STUDENT", residency="OFF_CAMPUS",
                      primary_commute_mode="DRIVE_ALONE")
        create_patron(full_name="P2", campus_role="STAFF", residency="ON_CAMPUS",
                      primary_commute_mode="TRANSIT")
        create_patron(full_name="P3", campus_role="FACULTY", residency="OFF_CAMPUS",
                      primary_commute_mode="BIKE")

        page1, meta1 = validate_paginated(
            api.list_patrons(admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2, f"page 1 must hold 2 patrons, got {len(page1)}"
        assert meta1["total_count"] == 3, f"total_count must be 3, got {meta1['total_count']}"
        assert meta1["has_more"] is True, "has_more must be true after the first page"

        page2, meta2 = validate_paginated(
            api.list_patrons(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"page 2 must hold 1 patron, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False, "has_more must be false on the last page"


class TestPatronExistence:
    def test_get_patron_not_found_returns_404(self, api, admin_headers):
        """PRD §2.8: "4. **Existence** — path ids and body foreign keys
        resolve, validated left-to-right (patron, lot, allocation, entry,
        permit, citation, closure, route, incentive account, fund)."
        PRD §5 maps `ERR_PATRON_NOT_FOUND` to HTTP 404.

        Design: Corner/entities/get_patron_not_found_returns_404
        """
        resp = api.get_patron(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_PATRON_NOT_FOUND, 404)
