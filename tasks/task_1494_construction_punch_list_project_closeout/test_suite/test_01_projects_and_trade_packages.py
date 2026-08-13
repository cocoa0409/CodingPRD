"""Project stand-up, trade-package registration, authentication, and response envelope."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_project,
    create_project_payload,
    create_trade_package_payload,
    get_project,
    new_project,
    new_trade,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]


class TestProjectCreation:

    def test_project_creation_computed_defaults(self):
        """PRD §3.1: "A new project begins in `MOBILIZED`."
        PRD §3.1: "Creation freezes `retainage_held_cents` per §2.6, initializes `retainage_paid_cents` and all three open-item counters to zero, sets `sc_eligible` and `beneficial_occupancy_registered` to false, zeroes `sc_rejection_count`, and leaves `substantial_completion_date`, `warranty_start_date`, and `closed_at` null."
        PRD §2.6: "`retainage_outstanding_cents` is always the held figure minus the paid figure, so it starts equal to `retainage_held_cents`."

        Design: Corner/entities/project_creation_computed_defaults
        """
        resp = api_client.create_project(
            create_project_payload(
                name="Proj D", contract_value_cents=250000, retainage_pct=0.10,
                reduction_policy="STANDARD", warranty_sla_mode="CALENDAR",
            ),
            PM,
        )
        data = validate_success(resp, 201)
        assert_project(data)
        assert data["status"] == "MOBILIZED"
        # round_half_up(250000 * 0.10) == 25000
        assert data["retainage_held_cents"] == 25000
        assert data["retainage_paid_cents"] == 0
        assert data["retainage_outstanding_cents"] == 25000
        assert data["open_life_safety_count"] == 0
        assert data["open_major_count"] == 0
        assert data["open_minor_count"] == 0
        assert data["sc_eligible"] is False
        assert data["beneficial_occupancy_registered"] is False
        assert data["sc_rejection_count"] == 0
        assert data["substantial_completion_date"] is None
        assert data["warranty_start_date"] is None
        assert data["closed_at"] is None

    def test_project_create_retainage_pct_out_of_range_returns_400(self):
        """PRD §3.1: "A `GCProjectManager` opens a closeout engagement by creating a project with a `name`, a `contract_value_cents` of at least 1000 cents, and a `retainage_pct` — the fraction of the contract value withheld as retainage, which must be greater than zero and no more than 0.25, a quarter of the contract at most."
        PRD §3.1: "Missing required fields, invalid enum spellings, or out-of-range numbers are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/project_create_retainage_pct_out_of_range_returns_400
        """
        resp = api_client.create_project(
            create_project_payload(name="Bad", contract_value_cents=250000, retainage_pct=0.30),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # 0.25 is the inclusive upper bound and must be accepted.
        ok_resp = api_client.create_project(
            create_project_payload(name="Edge OK", contract_value_cents=250000, retainage_pct=0.25),
            PM,
        )
        assert_project(validate_success(ok_resp, 201))


class TestTradePackageRegistration:

    def test_trade_package_missing_subcontractor_org_returns_400(self):
        """PRD §3.1: "The `subcontractor_org` name is required exactly when the responsible type is `SUBCONTRACTOR` and may be absent otherwise."

        Design: Corner/entities/trade_package_missing_subcontractor_org_returns_400
        """
        project = new_project(name="Proj")
        payload = create_trade_package_payload(
            project["id"], trade_name="ELECTRICAL", responsible_type="SUBCONTRACTOR",
            subcontractor_org=None,
        )
        resp = api_client.create_trade_package(payload, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        ok_resp = api_client.create_trade_package(
            create_trade_package_payload(
                project["id"], trade_name="PLUMBING", responsible_type="SELF_PERFORMED",
                subcontractor_org=None,
            ),
            PM,
        )
        trade = validate_success(ok_resp, 201)
        assert trade["responsible_type"] == "SELF_PERFORMED"

    def test_duplicate_trade_name_returns_error(self):
        """PRD §3.1: "Each package names its `project_id`, a `trade_name` drawn from `ELECTRICAL`, `PLUMBING`, `HVAC`, `DRYWALL`, `FLOORING`, `ROOFING`, `PAINTING`, or `CONCRETE` — unique within the project, with a repeat rejected as `ERR_DUPLICATE_TRADE` — and a `responsible_type` of `SUBCONTRACTOR` or `SELF_PERFORMED`."

        Design: Corner/validations/duplicate_trade_name_returns_error
        """
        project = new_project(name="Proj")
        new_trade(project["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        resp = api_client.create_trade_package(
            create_trade_package_payload(
                project["id"], trade_name="ELECTRICAL", responsible_type="SUBCONTRACTOR",
                subcontractor_org="VoltCo",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRADE)

        # The same trade_name on a different project is fine.
        other = new_project(name="Other Proj")
        ok_resp = api_client.create_trade_package(
            create_trade_package_payload(
                other["id"], trade_name="ELECTRICAL", responsible_type="SUBCONTRACTOR",
                subcontractor_org="VoltCo",
            ),
            PM,
        )
        validate_success(ok_resp, 201)


class TestBeginPunch:

    def test_begin_punch_with_zero_trades_returns_error(self):
        """PRD §3.1: "The move is permitted only once at least one trade package exists; with zero packages it fails with `ERR_NO_TRADE_PACKAGES`."

        Design: Corner/state_machines/begin_punch_with_zero_trades_returns_error
        """
        project = new_project(name="Proj")
        resp = api_client.begin_punch(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_NO_TRADE_PACKAGES)
        assert get_project(project["id"])["status"] == "MOBILIZED"

    def test_begin_punch_by_owner_returns_forbidden(self):
        """PRD §2.1: "A request whose role is not among the endpoint's allowed roles is rejected with `ERR_FORBIDDEN` (HTTP 403); §4 lists the authorized roles for every endpoint."

        Design: Corner/rbac/begin_punch_by_owner_returns_forbidden
        """
        project = new_project(name="Proj")
        new_trade(project["id"])
        resp = api_client.begin_punch(project["id"], TEST_USERS["owner_rep_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_project(project["id"])["status"] == "MOBILIZED"


class TestAddressingAndEnvelope:

    def test_project_get_not_found_returns_404(self):
        """PRD §2.9: "An identifier that matches no existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404), whether it arrives in the path or in the request body."

        Design: Corner/entities/project_get_not_found_returns_404
        """
        resp = api_client.get_project(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_response_envelope_shape_on_success_and_error(self):
        """PRD §2.2: "The `response_type` is either \"object\" for a single resource or \"array\" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        project = new_project(name="Proj")
        ok_resp = api_client.get_project(project["id"], PM)
        body = ok_resp.json()
        assert ok_resp.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["data"]["id"] == project["id"]

        err_resp = api_client.get_project(NON_EXISTENT_UUID, PM)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert err_body["data"]["message"].strip()


class TestAuthentication:

    def test_missing_auth_headers_returns_401(self):
        """PRD §2.1: "A request with a missing or invalid header, or an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api_client.create_project(
            create_project_payload(name="NoAuth"), headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
