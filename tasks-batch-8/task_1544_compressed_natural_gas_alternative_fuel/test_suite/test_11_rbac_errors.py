"""RBAC permission matrix, ownership scoping rejections, header validation,
and the 404 error catalogue (PRD §2.1, §2.8, §2.10, §5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_fleet_account,
    validate_error,
)

MISSING = "00000000-0000-4000-8000-000000000001"


class TestMissingHeaders:
    def test_request_missing_auth_headers_returns_400(self, api):
        """PRD §2.8: "1. **Header presence and validity.** `X-User-ID` and
        `X-User-Role` must be present and the role must be one of the six
        declared names, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_returns_400
        """
        resp = api.list_stations(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleDenied:
    def test_station_manager_cannot_decide_claim_returns_403_forbidden(
        self, api, station_manager_headers
    ):
        """PRD §2.8: "2. **Role permission.** The caller's role must be listed
        for the endpoint, else `ERR_FORBIDDEN_ROLE` (HTTP 403). This stage also
        covers a PUBLIC session being completed by any role other than
        `Anonymous`."

        Design: Corner/rbac/station_manager_cannot_decide_claim_returns_403_forbidden
        """
        resp = api.decide_tax_credit_claim(
            "00000000-0000-4000-8000-0000000000f1", {"outcome": "APPROVED"},
            station_manager_headers,
        )
        # The role check fires before existence, so even an unknown id yields 403.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_compliance_officer_cannot_create_station_returns_403_forbidden(
        self, api, compliance_officer_headers
    ):
        """PRD §2.8: "2. **Role permission.** The caller's role must be listed
        for the endpoint, else `ERR_FORBIDDEN_ROLE` (HTTP 403). This stage also
        covers a PUBLIC session being completed by any role other than
        `Anonymous`."

        Design: Corner/rbac/compliance_officer_cannot_create_station_returns_403_forbidden
        """
        resp = api.create_station(
            {
                "station_name": "X",
                "station_code": "ST-X",
                "access_mode": "DUAL",
                "backup_capacity_gge": 1000,
            },
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_network_operator_cannot_authorize_session_returns_403_forbidden(
        self, api, network_operator_headers
    ):
        """PRD §2.8: "2. **Role permission.** The caller's role must be listed
        for the endpoint, else `ERR_FORBIDDEN_ROLE` (HTTP 403). This stage also
        covers a PUBLIC session being completed by any role other than
        `Anonymous`."

        Design: Corner/rbac/network_operator_cannot_authorize_session_returns_403_forbidden
        """
        account = create_fleet_account(account_name="RB Co", credit_limit_cents=100000)
        resp = api.authorize_session(
            {
                "fleet_card_id": "00000000-0000-4000-8000-0000000000f2",
                "dispenser_id": "00000000-0000-4000-8000-0000000000f3",
                "client_ref": "CR-RB1",
                "estimated_gge": 5.0,
                "expected_fleet_account_version": account["version"],
            },
            network_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_anonymous_cannot_list_stations_returns_403_forbidden(
        self, api, anonymous_headers
    ):
        """PRD §2.10: "`Anonymous` holds no read access to any list or detail
        endpoint."
        PRD §2.8: "2. **Role permission.** The caller's role must be listed for
        the endpoint, else `ERR_FORBIDDEN_ROLE` (HTTP 403). This stage also
        covers a PUBLIC session being completed by any role other than
        `Anonymous`."

        Design: Corner/rbac/anonymous_cannot_list_stations_returns_403_forbidden
        """
        resp = api.list_stations(anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestNotFoundCatalogue:
    """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
    left to right, then body foreign keys such as `dispenser_id`,
    `fleet_card_id`, `station_id`, `fleet_account_id`, and `compressor_id`.
    Each missing resource yields its own error: `ERR_STATION_NOT_FOUND`,
    `ERR_COMPRESSOR_NOT_FOUND`, `ERR_DISPENSER_NOT_FOUND`,
    `ERR_CALIBRATION_RECORD_NOT_FOUND`, `ERR_PRICING_POLICY_NOT_FOUND`,
    `ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_FLEET_CARD_NOT_FOUND`,
    `ERR_SUPPLY_CONTRACT_NOT_FOUND`, `ERR_MONTHLY_SETTLEMENT_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`,
    `ERR_BACKUP_ARRANGEMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or
    `ERR_TAX_CLAIM_NOT_FOUND` (all HTTP 404).\""""

    def test_station_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error:
        `ERR_STATION_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/station_not_found_returns_404
        """
        resp = api.get_station(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_FOUND, 404)

    def test_compressor_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error:
        `ERR_STATION_NOT_FOUND`, `ERR_COMPRESSOR_NOT_FOUND`,
        `ERR_DISPENSER_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/compressor_not_found_returns_404
        """
        resp = api.get_compressor(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_COMPRESSOR_NOT_FOUND, 404)

    def test_dispenser_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error:
        `ERR_STATION_NOT_FOUND`, `ERR_COMPRESSOR_NOT_FOUND`,
        `ERR_DISPENSER_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/dispenser_not_found_returns_404
        """
        resp = api.get_dispenser(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_DISPENSER_NOT_FOUND, 404)

    def test_calibration_record_not_found_returns_404(self, api, station_manager_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_CALIBRATION_RECORD_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/calibration_record_not_found_returns_404
        """
        resp = api.get_calibration_record(MISSING, station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_RECORD_NOT_FOUND, 404)

    def test_pricing_policy_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_PRICING_POLICY_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/pricing_policy_not_found_returns_404
        """
        resp = api.get_pricing_policy(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_PRICING_POLICY_NOT_FOUND, 404)

    def test_fleet_account_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_FLEET_ACCOUNT_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/fleet_account_not_found_returns_404
        """
        resp = api.get_fleet_account(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FLEET_ACCOUNT_NOT_FOUND, 404)

    def test_fleet_card_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_FLEET_CARD_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/fleet_card_not_found_returns_404
        """
        resp = api.get_fleet_card(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FLEET_CARD_NOT_FOUND, 404)

    def test_supply_contract_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_SUPPLY_CONTRACT_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/supply_contract_not_found_returns_404
        """
        resp = api.get_supply_contract(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_CONTRACT_NOT_FOUND, 404)

    def test_monthly_settlement_not_found_returns_404(self, api, network_operator_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_MONTHLY_SETTLEMENT_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/monthly_settlement_not_found_returns_404
        """
        resp = api.get_monthly_settlement(MISSING, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MONTHLY_SETTLEMENT_NOT_FOUND, 404)

    def test_session_not_found_returns_404(self, api, station_manager_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_SESSION_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/session_not_found_returns_404
        """
        resp = api.get_fueling_session(MISSING, station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND, 404)

    def test_maintenance_window_not_found_returns_404(self, api, station_manager_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/maintenance_window_not_found_returns_404
        """
        resp = api.get_maintenance_window(MISSING, station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_WINDOW_NOT_FOUND, 404)

    def test_backup_arrangement_not_found_returns_404(self, api, station_manager_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_BACKUP_ARRANGEMENT_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/backup_arrangement_not_found_returns_404
        """
        resp = api.get_backup_arrangement(MISSING, station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BACKUP_ARRANGEMENT_NOT_FOUND, 404)

    def test_inspection_not_found_returns_404(self, api, compliance_officer_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ...
        `ERR_INSPECTION_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/errors/inspection_not_found_returns_404
        """
        resp = api.get_safety_inspection(MISSING, compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_FOUND, 404)

    def test_tax_claim_not_found_returns_404(self, api, station_manager_headers):
        """PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`. Each missing resource yields its own error: ... or
        `ERR_TAX_CLAIM_NOT_FOUND` (all HTTP 404)."

        Design: Corner/errors/tax_claim_not_found_returns_404
        """
        resp = api.get_tax_credit_claim(MISSING, station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_TAX_CLAIM_NOT_FOUND, 404)
