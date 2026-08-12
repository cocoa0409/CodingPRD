"""Role authorization, CustomerRep ownership linkage, and segregation of
duties (PRD §2.1, §2.11, §3.2, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    collect_sample,
    create_customer,
    create_lease_payload,
    make_customer_rep_headers,
    make_gauger_headers,
    make_manager_headers,
    record_sample_result,
    setup_certified_custody,
    setup_completed_movement,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import MANAGER


class TestRoleAuthorization:
    def test_customer_rep_cannot_create_tank(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /tanks lists TerminalOperator only.

        Design: Corner/rbac/rbac_customer_rep_cannot_create_tank
        """
        customer = create_customer(name="Role Probe Co", contact_email="rp@example.com")
        resp = api.create_tank(
            {"tank_code": "T-9901", "product_grade": "DIESEL", "capacity_bbl": 100000},
            make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403

    def test_gauger_cannot_certify_custody(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /custody-transfers/{ctId}/certify lists TerminalManager
        only.

        Design: Corner/rbac/rbac_gauger_cannot_certify_custody
        """
        bundle = setup_completed_movement(customer_name="Cert Role Co")
        # Collect and pass a sample so the transfer is otherwise certifiable.
        sample = collect_sample(bundle["movement"]["id"])
        record_sample_result(sample["id"], lab_result="PASSED", specific_gravity=0.85)
        resp = api.certify_custody_transfer(bundle["custody"]["id"], make_gauger_headers("gauger-2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403
        after = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert after["status"] == "PROVISIONAL", "rejected certify must not change status"


class TestSegregationOfDuties:
    def test_certifier_must_differ_from_gauge_recorder(self, api):
        """PRD §2.11: "First, the `X-User-ID` that certifies a custody transfer
        must differ from the `recorded_by_user_id` on the movement's gauge
        tickets." The comparison is between recorded header values, so a
        TerminalManager carrying the gauge recorder's id is rejected with
        ERR_SEGREGATION_OF_DUTIES.

        Design: Corner/rbac/segregation_gauger_cannot_certify_own_gauge
        """
        bundle = setup_completed_movement(customer_name="SoD Co", gauger_id="gauger-9")
        sample = collect_sample(bundle["movement"]["id"])
        record_sample_result(sample["id"], lab_result="PASSED", specific_gravity=0.85)
        resp = api.certify_custody_transfer(bundle["custody"]["id"], make_manager_headers("gauger-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403
        after = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert after["status"] == "PROVISIONAL"


class TestCustomerRepOwnership:
    def test_cannot_create_lease_for_other_customer(self, api):
        """PRD §3.2: "A `CustomerRep` creates a `LeaseAgreement` for their own
        customer — the payload's `customer_id` must equal the caller's
        `X-User-ID`, failing which the request is rejected with
        `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/customer_rep_cannot_create_lease_for_other
        """
        c1 = create_customer(name="Owner One", contact_email="o1@example.com")
        c2 = create_customer(name="Owner Two", contact_email="o2@example.com")
        payload = create_lease_payload(c2["id"], committed_capacity_bbl=10000,
                                       min_monthly_throughput_bbl=10)
        resp = api.create_lease_agreement(payload, make_customer_rep_headers(c1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert resp.status_code == 403

    def test_cannot_dispute_others_custody_transfer(self, api):
        """PRD §3.7: "a `CustomerRep` whose `X-User-ID` equals the lease's
        `customer_id` may move the transfer from `CERTIFIED` to `DISPUTED`; any
        other caller is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/customer_rep_cannot_dispute_others_custody
        """
        bundle = setup_certified_custody(customer_name="Rightful Owner")
        other = create_customer(name="Interloper Inc", contact_email="in@example.com")
        resp = api.dispute_custody_transfer(
            bundle["custody"]["id"], make_customer_rep_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert resp.status_code == 403
        after = validate_success(api.get_custody_transfer(bundle["custody"]["id"], MANAGER))
        assert after["status"] == "CERTIFIED", "rejected dispute must not change status"
