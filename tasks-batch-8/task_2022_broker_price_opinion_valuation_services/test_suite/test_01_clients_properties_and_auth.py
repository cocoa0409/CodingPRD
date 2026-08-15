"""Client onboarding defaults, code/format constraints, not-found, and auth headers."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client_account,
    create_broker_payload,
    create_client_account_payload,
    validate_error,
    validate_success,
)


class TestClientAccountCreation:
    def test_client_account_creation_applies_defaults(self, api, platform_admin_headers):
        """PRD §3.1: "`late_penalty_bps_per_day` is the late fee charged back to
        the vendor, expressed in basis points of the order fee per calendar day
        past SLA, ranging from 0 to 2000 and defaulting to 250 when omitted"
        PRD §3.1: "`scorecard_weight_turnaround`, `scorecard_weight_quality`,
        and `scorecard_weight_revision` are the weights (each between 0 and 1)
        applied to the turnaround, quality, and revision-rate components of the
        broker scorecard for this client's orders, defaulting to 0.5, 0.3, and
        0.2 respectively."
        PRD §3.1: "A client account's `status` begins as `ACTIVE`"

        Design: Corner/entities/client_account_creation_applies_defaults
        """
        payload = create_client_account_payload(
            client_code="CDF", display_name="Defaults Co",
            sla_hours_standard=72, sla_hours_rush=24)
        created = validate_success(
            api.create_client_account(payload, platform_admin_headers), 201)
        assert_client_account(created)
        assert created["late_penalty_bps_per_day"] == 250
        assert created["scorecard_weight_turnaround"] == 0.5
        assert created["scorecard_weight_quality"] == 0.3
        assert created["scorecard_weight_revision"] == 0.2
        assert created["status"] == "ACTIVE"

        fetched = validate_success(
            api.get_client_account(created["id"], platform_admin_headers))
        assert fetched["late_penalty_bps_per_day"] == 250
        assert fetched["scorecard_weight_turnaround"] == 0.5
        assert fetched["scorecard_weight_quality"] == 0.3
        assert fetched["scorecard_weight_revision"] == 0.2
        assert fetched["status"] == "ACTIVE"

    @pytest.mark.parametrize("standard,rush", [(48, 48), (48, 49)])
    def test_client_account_invalid_sla_relationship_rejected(
            self, api, platform_admin_headers, standard, rush):
        """PRD §3.1: "`sla_hours_rush` is the rush turnaround commitment in whole
        hours and must be at least 4 and strictly less than `sla_hours_standard`"

        Design: Corner/entities/client_account_invalid_sla_relationship_rejected
        """
        payload = create_client_account_payload(
            client_code="CBAD", display_name="Bad SLA",
            sla_hours_standard=standard, sla_hours_rush=rush)
        resp = api.create_client_account(payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_client_code_uniqueness_enforced(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` registers each lending client as a
        `ClientAccount`, supplying a `client_code` that is globally unique and
        matches the pattern of 3 to 12 uppercase alphanumeric characters"

        Design: Corner/entities/client_code_uniqueness_enforced
        """
        first = create_client_account_payload(
            client_code="DUP", display_name="First",
            sla_hours_standard=72, sla_hours_rush=24)
        validate_success(api.create_client_account(first, platform_admin_headers), 201)

        second = create_client_account_payload(
            client_code="DUP", display_name="Second",
            sla_hours_standard=96, sla_hours_rush=24)
        resp = api.create_client_account(second, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_broker_code_format_enforced(self, api, compliance_officer_headers):
        """PRD §3.3: "A `ComplianceOfficer` onboards a `Broker` with a globally
        unique `broker_code` (3 to 12 uppercase alphanumeric characters)"

        Design: Corner/entities/broker_code_format_enforced
        """
        payload = create_broker_payload(
            broker_code="lower1", full_name="Bad", email="bad@example.com",
            max_concurrent_orders=5)
        resp = api.create_broker(payload, compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_property_not_found_returns_404(self, api, operations_manager_headers):
        """PRD §2.7: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first path segment whose identifier does not resolve to
        an existing resource, before any later segment is examined."

        Design: Corner/entities/property_not_found_returns_404
        """
        resp = api.get_property(NON_EXISTENT_UUID, operations_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthentication:
    @pytest.mark.parametrize("headers", [
        {},
        {"X-User-ID": "some-user", "Content-Type": "application/json"},
        {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        {"X-User-ID": "", "X-User-Role": "PlatformAdmin",
         "Content-Type": "application/json"},
        {"X-User-ID": "some-user", "X-User-Role": "",
         "Content-Type": "application/json"},
    ])
    def test_missing_auth_header_returns_unauthenticated(self, api, headers):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_brokers(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
