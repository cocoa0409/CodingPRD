"""Departure gate boundary: exactly zero active grants required (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_active_employee,
    create_registered_asset,
    create_provisioned_grant,
    create_certified_interview,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


def _setup_notice_employee_with_one_grant(api):
    """ACTIVE employee (ack signed, training completed) with one PROVISIONED
    grant; CERTIFIED exit interview; employee moved to NOTICE (voluntary)."""
    emp = create_active_employee(
        complete_training=True,
        full_name="Paula Exiting", email="paula@x.com", department="FIN",
        role_title="Controller", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    asset = create_registered_asset(
        title="Payroll model", description="comp bands",
        classification="CONFIDENTIAL", owner_department="FIN",
        exposure_estimate_cents=120000,
    )
    grant = create_provisioned_grant(
        emp["id"], asset["id"], justification="audit season",
        expires_at="2026-12-01T00:00:00Z",
    )
    create_certified_interview(emp["id"])
    emp = validate_success(api.transition_employee(
        emp["id"], {"to_status": "NOTICE", "departure_type": "VOLUNTARY"}, HR
    ))
    return emp, asset, grant


class TestDepartureRequiresExactlyZeroActiveGrants:
    def test_one_active_grant_blocks_departure(self, api):
        """PRD §3.6: "no access grant may remain in `REQUESTED`, `APPROVED`,
        `PROVISIONED`, or `SUSPENDED`, otherwise `ERR_ACTIVE_GRANTS_REMAIN`."

        Design: Difficulty/boundary_precision_check/departure_requires_exactly_zero_active_grants
        """
        emp, _asset, _grant = _setup_notice_employee_with_one_grant(api)
        resp = api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_GRANTS_REMAIN)
        data = validate_success(api.get_employee(emp["id"], HR))
        assert data["status"] == "NOTICE", "count 1 > 0 blocks departure"

    def test_zero_grants_after_revoke_allows_departure(self, api):
        """PRD §3.6: "Departure itself — `NOTICE → DEPARTED` — carries a triple
        gate: a `CERTIFIED` exit interview must exist for the employee,
        otherwise `ERR_EXIT_INTERVIEW_NOT_CERTIFIED`; no access grant may remain
        in `REQUESTED`, `APPROVED`, `PROVISIONED`, or `SUSPENDED`, otherwise
        `ERR_ACTIVE_GRANTS_REMAIN`; and every forensic review of the employee
        must have concluded in `CLOSED_NO_ACTION` or `ESCALATED`, otherwise
        `ERR_REVIEW_NOT_CONCLUDED`. Success stamps `departed_at`."
        PRD §3.4: "Revocation — from `APPROVED`, `PROVISIONED`, or `SUSPENDED` —
        is available to security or counsel and subtracts one from the asset's
        `active_grant_count`."

        Design: Difficulty/boundary_precision_check/departure_requires_exactly_zero_active_grants
        """
        emp, asset, grant = _setup_notice_employee_with_one_grant(api)
        # First attempt fails while the count is 1
        validate_error(
            api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR),
            ApiErrorId.ERR_ACTIVE_GRANTS_REMAIN,
        )
        # Revoking the single grant returns the count to exactly 0
        validate_success(api.transition_grant(grant["id"], {"to_status": "REVOKED"}, SEC))
        asset_now = validate_success(api.get_asset(asset["id"], IP))
        assert asset_now["active_grant_count"] == 0
        data = validate_success(api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR))
        assert data["status"] == "DEPARTED"
