"""Vessel registration, permits, quota holdings, and openings — creation
defaults, shape constraints, uniqueness, and role gates (PRD §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_quota_holding,
    assert_vessel,
    create_holding,
    create_quota_holding_payload,
    create_vessel_payload,
    make_crew_member_headers,
    setup_vessel_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


class TestVesselRegistration:
    def test_vessel_creation_defaults(self):
        """PRD §3.1: "A freshly registered vessel is in `REGISTERED` status with
        `compliance_points` at 100."
        PRD §2.4: "Every persisted resource carries an `id`, a server-minted UUID with
        no type prefix. Resources also carry `created_at` and `updated_at` timestamps
        in ISO 8601 UTC format with three fractional digits, and a `version` integer."

        Design: Corner/entities/vessel_creation_defaults
        """
        resp = api_client.create_vessel(create_vessel_payload(), REG)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        vessel = validate_success(resp, 201)
        assert_vessel(vessel)
        assert vessel["status"] == "REGISTERED"
        assert vessel["compliance_points"] == 100
        assert isinstance(vessel["version"], int) and vessel["version"] >= 1

    def test_vessel_create_invalid_enum_rejected(self):
        """PRD §3.1 limits registration to "an `observer_coverage_class` of `FULL`,
        `PARTIAL`, or `EXEMPT`"; PRD §2.7 item 9 rejects "malformed bodies, wrong types,
        invalid enum values" with `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/vessel_create_invalid_enum_rejected
        """
        resp = api_client.create_vessel(
            create_vessel_payload(observer_coverage_class="GOLD"), REG)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)
        # The rejected vessel was not persisted.
        rows, meta = validate_paginated(api_client.list_vessels(REG))
        assert meta["total_count"] == 0

    def test_vessel_create_missing_required_field(self):
        """PRD §3.1: a regulator "registers it with a `vessel_name`, a `license_number`
        that must be unique across all vessels", so omitting license_number is a
        malformed body; PRD §2.7 item 9 maps that to `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/vessel_create_missing_required_field
        """
        payload = create_vessel_payload()
        del payload["license_number"]
        resp = api_client.create_vessel(payload, REG)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

    def test_vessel_get_not_found_returns_404(self):
        """PRD §2.9: "The resource-specific not-found errors are:
        `ERR_VESSEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
        `ERR_QUOTA_HOLDING_NOT_FOUND`, `ERR_SEASON_OPENING_NOT_FOUND`,
        `ERR_TRIP_NOT_FOUND`, `ERR_LANDING_DECLARATION_NOT_FOUND`,
        `ERR_TRANSFER_NOT_FOUND`, `ERR_OBSERVER_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_CONTRACT_NOT_FOUND`,
        `ERR_EXPENSE_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_GEAR_ASSET_NOT_FOUND`, and `ERR_VIOLATION_NOT_FOUND` — all
        HTTP 404."

        Design: Corner/entities/vessel_get_not_found_returns_404
        """
        resp = api_client.get_vessel(NON_EXISTENT_UUID, REG)
        validate_error(resp, "ERR_VESSEL_NOT_FOUND", 404)

    def test_vessel_duplicate_license_rejected(self):
        """PRD §3.1: registration takes "a `license_number` that must be unique across
        all vessels (a duplicate is rejected with `ERR_DUPLICATE_LICENSE`, HTTP 409)".

        Design: Corner/entities/vessel_duplicate_license_rejected
        """
        first = create_vessel_payload(license_number="LIC-DUP-1")
        validate_success(api_client.create_vessel(first, REG), 201)
        second = create_vessel_payload(
            vessel_name="FV Copy", license_number="LIC-DUP-1",
            home_port="KODIAK", length_ft=40, observer_coverage_class="EXEMPT")
        resp = api_client.create_vessel(second, REG)
        validate_error(resp, "ERR_DUPLICATE_LICENSE", 409)


class TestQuotaHoldings:
    def test_holding_duplicate_rejected(self):
        """PRD §3.2: "The combination of vessel, fishery, and season year is unique —
        a second allocation for the same triple is rejected with
        `ERR_DUPLICATE_HOLDING` (HTTP 409)."

        Design: Corner/entities/holding_duplicate_rejected
        """
        ctx = setup_vessel_ready(with_holding=False)
        vessel_id = ctx["vessel"]["id"]
        first = create_holding(vessel_id, initial_pounds=10000)
        assert_quota_holding(first)
        resp = api_client.create_quota_holding(
            vessel_id, create_quota_holding_payload(initial_pounds=5000), REG)
        validate_error(resp, "ERR_DUPLICATE_HOLDING", 409)
        # A different fishery in the same year is a different triple and succeeds.
        other = api_client.create_quota_holding(
            vessel_id, create_quota_holding_payload(fishery_code="SABLEFISH"), REG)
        validate_success(other, 201)


class TestSeasonOpenings:
    def test_opening_create_invalid_time_window_rejected(self):
        """PRD §3.2: creating an opening takes "a `closes_at` instant that must be
        later than `opens_at` (otherwise `ERR_INVALID_TIME_WINDOW`)".

        Design: Corner/entities/opening_create_invalid_time_window_rejected
        """
        resp = api_client.create_season_opening(
            {"fishery_code": "HALIBUT", "area_code": "3A",
             "opens_at": "2026-08-25T00:00:00Z",
             "closes_at": "2026-08-05T00:00:00Z", "tac_pounds": 100000},
            REG)
        validate_error(resp, "ERR_INVALID_TIME_WINDOW", 400)


class TestRoleGates:
    def test_rbac_crew_member_cannot_create_vessel(self):
        """PRD §4: POST /vessels lists only FisheriesRegulator; PRD §2.1: "a role that
        is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/rbac_crew_member_cannot_create_vessel
        """
        resp = api_client.create_vessel(
            create_vessel_payload(observer_coverage_class="EXEMPT", length_ft=40),
            make_crew_member_headers(NON_EXISTENT_UUID))
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
