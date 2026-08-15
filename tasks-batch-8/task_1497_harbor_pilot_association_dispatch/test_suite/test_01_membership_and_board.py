"""Membership, endorsements, and the rotation board (PRD §2.1, §2.9, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_pilot, assert_license_endorsement, assert_rotation_entry,
    make_pilot_payload, register_pilot, issue_endorsement,
    get_pilot_fresh, rotation_entry_of,
)


class TestPilotRegistration:
    def test_pilot_create_system_fields_input_ignored(self, api, admin_headers):
        """PRD §3.1: "Registration creates the pilot in `ACTIVE` status with
        `rest_until` null (no rest obligation until the pilot's first completion)
        and `duty_minutes_rolling_7d` at zero".
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        by exactly one on every mutation of the resource".

        Client-injected system fields (status, version) are not client-settable:
        the server returns the freshly registered pilot in ACTIVE at version 1.

        Design: Corner/entities/pilot_create_system_fields_input_ignored
        """
        payload = make_pilot_payload(full_name="Pilot Sys", license_number="LIC-S",
                                     share_units=2)
        payload["status"] = "SUSPENDED"
        payload["version"] = 99
        res = api.create_pilot(payload, admin_headers)
        pilot = validate_success(res, 201)
        assert_pilot(pilot)
        assert pilot["status"] == "ACTIVE", "injected SUSPENDED must be ignored"
        assert pilot["version"] == 1, "injected version 99 must be ignored"
        assert pilot["rest_until"] is None
        assert pilot["duty_minutes_rolling_7d"] == 0

    def test_pilot_get_not_found_returns_404(self, api, dispatcher_headers):
        """PRD §2.8: "Existence of every referenced resource — path identifiers
        and body-supplied identifiers alike, covering orders, assignments, pilots,
        boats, invoices, incidents, apprentices, distribution runs, and
        endorsements — is validated next, strictly left-to-right across the
        request, with the first missing reference yielding `ERR_NOT_FOUND`."

        Design: Corner/entities/pilot_get_not_found_returns_404
        """
        res = api.get_pilot(NON_EXISTENT_UUID, dispatcher_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        body = res.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


class TestPilotRegistrationAuth:
    def test_pilot_create_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/pilot_create_missing_auth_headers_unauthenticated
        """
        res = api.create_pilot(
            make_pilot_payload(full_name="No Auth", license_number="LIC-NA"),
            headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestEndorsementSupersession:
    def test_endorsement_same_class_supersede_transition(self, api, admin_headers):
        """PRD §3.1: "Endorsements are per-class superseding: creating a new
        endorsement in the same class as an existing `CURRENT` endorsement for
        the same pilot flips the older one to `SUPERSEDED`, and this mutation
        increments the pilot's `version` by one."

        Design: Corner/entities/endorsement_same_class_supersede_transition
        """
        pilot = register_pilot()
        e1 = issue_endorsement(pilot["id"], endorsement_class="HARBOR",
                               tonnage_cap_gt=5000, expires_at="2027-01-01T00:00:00Z")
        assert e1["status"] == "CURRENT"

        e2 = issue_endorsement(pilot["id"], endorsement_class="HARBOR",
                               tonnage_cap_gt=7000, expires_at="2027-06-01T00:00:00Z")
        assert e2["status"] == "CURRENT"
        assert e2["tonnage_cap_gt"] == 7000

        data, meta = validate_paginated(
            api.list_endorsements(pilot["id"], admin_headers))
        by_id = {row["id"]: row for row in data}
        assert by_id[e1["id"]]["status"] == "SUPERSEDED", "older same-class flips"
        current_harbor = [r for r in data
                          if r["endorsement_class"] == "HARBOR" and r["status"] == "CURRENT"]
        assert len(current_harbor) == 1 and current_harbor[0]["id"] == e2["id"]

    def test_endorsement_create_occ_stale_pilot_returns_412(self, api, admin_headers):
        """PRD §2.7: "Issuing an endorsement to a pilot requires
        `expected_pilot_version`, carrying the client's last observed `version`
        of that pilot; a mismatch — for example because another writer's
        same-class endorsement legitimately superseded the one the client
        believed was current — is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/validations/endorsement_create_occ_stale_pilot_returns_412
        """
        pilot = register_pilot()
        stale_v = pilot["version"]
        e1 = issue_endorsement(pilot["id"], endorsement_class="HARBOR",
                               tonnage_cap_gt=5000)
        assert e1["status"] == "CURRENT"

        res = api.create_endorsement(pilot["id"], {
            "endorsement_class": "COASTAL",
            "tonnage_cap_gt": 20000,
            "expires_at": "2027-01-01T00:00:00Z",
            "expected_pilot_version": stale_v,
        }, admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        data, meta = validate_paginated(
            api.list_endorsements(pilot["id"], admin_headers))
        assert meta["total_count"] == 1, "rejected write must not persist"
        assert data[0]["id"] == e1["id"] and data[0]["status"] == "CURRENT"


class TestRotationBoardListing:
    def test_rotation_board_listing_pagination_defaults(self, api, dispatcher_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §3.1: "the board-wide listing is ordered by `position` ascending and
        accepts an optional `status` filter."
        PRD §2.9: "a newly registered pilot enters at the bottom of the board with
        `position` set to one greater than the current maximum".

        Design: Corner/endpoints/rotation_board_listing_pagination_defaults
        """
        pilots = [register_pilot(f"Pilot {c}", f"LIC-{c}") for c in "ABC"]

        data, meta = validate_paginated(api.list_rotation_entries(dispatcher_headers))
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["has_more"] is False
        assert [row["position"] for row in data] == [1, 2, 3]

        first_page, meta1 = validate_paginated(
            api.list_rotation_entries(dispatcher_headers, params={"limit": 2}))
        assert len(first_page) == 2 and meta1["has_more"] is True
        assert [row["position"] for row in first_page] == [1, 2]

        tail, meta2 = validate_paginated(
            api.list_rotation_entries(dispatcher_headers, params={"limit": 2, "offset": 2}))
        assert len(tail) == 1
        assert tail[0]["position"] == 3
        assert meta2["has_more"] is False
