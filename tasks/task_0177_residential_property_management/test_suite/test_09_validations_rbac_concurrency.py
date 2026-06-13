"""Auth, RBAC, fiscal guards, OCC concurrency, and derived-field breadth tests."""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, build_user_headers,
)
from test_helpers.fixtures import (
    PM, CO, create_owner, create_property, create_unit, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, post_payment, fund_trust,
    create_assigned_work_order, create_draft_statement, create_finalized_statement,
    property_version, setup_active_lease, setup_filed_eviction,
)
from test_helpers.api_client import api_client


class TestAuthAndRbac:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits X-User-Role or supplies a value that is
        not one of the five recognized roles is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/validations/missing_role_header_returns_unauthenticated
        """
        res = api.create_owner(
            {"legal_name": "X", "email": "x@x.com", "management_fee_pct": 0.08},
            {})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_applicant_cannot_create_property(self, api):
        """PRD §2.1: "When the header is present and valid but the role is not
        permitted to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN." PRD §4: POST /properties is authorized for PropertyManager
        only.

        Design: Corner/rbac/applicant_cannot_create_property
        """
        owner = create_owner()
        applicant_headers = build_user_headers("test-applicant-x", "Applicant")
        res = api.create_property(
            {"owner_id": owner["id"], "name": "Pr23", "state_code": "TX",
             "address": "Ad23"},
            applicant_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_property_manager_cannot_enforce_eviction(self, api):
        """PRD §3.8: "A ComplianceOfficer enforces a filed case, advancing it to the
        terminal ENFORCED state". PRD §2.1: "When the header is present and valid
        but the role is not permitted to perform the requested operation, the
        request is rejected with ERR_FORBIDDEN."

        Design: Corner/rbac/property_manager_cannot_enforce_eviction
        """
        world = setup_filed_eviction(state_code="TX", reason="NONPAYMENT",
                                     notice_date="2026-06-10",
                                     file_as_of_date="2026-06-20")
        res = api.enforce_eviction(world["eviction"]["id"], PM)
        validate_error(res, "ERR_FORBIDDEN")


class TestFiscalGuards:
    def test_distribute_with_no_trust_returns_nothing_to_distribute(self, api):
        """PRD §3.10: "There must also be something to pay — the property's
        distributable_cents must be at least 1, otherwise the distribution is
        refused with ERR_NOTHING_TO_DISTRIBUTE."

        Design: Corner/validations/distribute_with_no_trust_returns_nothing_to_distribute
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX",
                               reserve_floor_cents=0)
        stmt = create_finalized_statement(prop["id"], period_label="2026-06",
                                          basis="CASH")
        v = property_version(prop["id"])
        res = api.distribute_owner_statement(
            stmt["id"], {"expected_property_version": v}, PM)
        validate_error(res, "ERR_NOTHING_TO_DISTRIBUTE")

    def test_complete_owner_charged_work_order_insufficient_trust(self, api):
        """PRD §3.7: "If the order's charge_to_owner flag is set, the actual cost is
        debited from the property's trust_balance_cents and the distributable figure
        is recomputed; if the trust cannot cover the debit, completion is refused
        with ERR_TRUST_INSUFFICIENT."

        Zero-trust property, owner-charged work order with actual cost 50000.

        Design: Corner/validations/complete_owner_charged_workorder_insufficient_trust_returns_trust_insufficient
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX",
                               reserve_floor_cents=0)
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        wo = create_assigned_work_order(unit["id"], charge_to_owner=True,
                                        category="ELECTRICAL", description="Rewire")
        res = api.complete_work_order(
            wo["id"], {"actual_cost_cents": 50000, "completed_date": "2026-06-15"}, PM)
        validate_error(res, "ERR_TRUST_INSUFFICIENT")


class TestConcurrency:
    def test_stale_lease_version_on_offer_renewal(self, api):
        """PRD §3.4: "Either direction of the toggle requires expected_lease_version
        to match the lease's current version, failing which the request is rejected
        with ERR_STALE_VERSION, and either direction increments the lease's version
        by one."

        Sign, offer-renewal (bumps version), then replay the pre-offer version.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_lease_version_on_offer_renewal
        """
        world = setup_active_lease(state_code="TX")
        lease = world["lease"]
        v_signed = lease["version"]
        get_success_data(api.offer_renewal(
            lease["id"], {"expected_lease_version": v_signed}, PM))
        res = api.offer_renewal(lease["id"], {"expected_lease_version": v_signed}, PM)
        validate_error(res, "ERR_STALE_VERSION")

    def test_stale_prior_lease_version_on_renewal_create(self, api):
        """PRD §2.9: "Creating a renewal lease — a lease whose renewed_from_lease_id
        points at a prior lease — requires the request to carry expected_lease_version
        ... On a successful renewal create, the prior lease's version is itself
        incremented by one, so that any second renewal create still carrying the
        now-superseded version is rejected."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_prior_lease_version_on_renewal_create
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX")
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app = create_approved_applicant(unit["id"])
        lease1 = create_draft_lease(unit["id"], app["id"], start_date="2026-06-01",
                                    end_date="2027-06-01", monthly_rent_cents=200000)
        collect_deposit(lease1["id"], collected_cents=200000)
        signed = get_success_data(api.sign_lease(lease1["id"], PM))
        v_signed = signed["version"]
        # First renewal create succeeds and bumps lease1.version.
        get_success_data(api.create_lease({
            "unit_id": unit["id"], "start_date": "2027-06-01",
            "end_date": "2028-06-01", "monthly_rent_cents": 210000,
            "renewed_from_lease_id": lease1["id"],
            "expected_lease_version": v_signed,
        }, PM))
        # Second renewal create still carrying the stale version is rejected.
        res = api.create_lease({
            "unit_id": unit["id"], "start_date": "2027-06-01",
            "end_date": "2028-06-01", "monthly_rent_cents": 210000,
            "renewed_from_lease_id": lease1["id"],
            "expected_lease_version": v_signed,
        }, PM)
        validate_error(res, "ERR_STALE_VERSION")

    def test_stale_property_version_on_distribute(self, api):
        """PRD §2.9: "Distributing a finalized owner statement requires the request
        to carry expected_property_version holding the property's last-observed
        version. If another distribution or trust debit has advanced the property's
        version since the client read it ... the distribution is rejected with
        ERR_STALE_VERSION. A successful distribution increments the property's
        version."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_property_version_on_distribute
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX",
                               reserve_floor_cents=0)
        fund_trust(prop["id"], 500000)
        stmt1 = create_draft_statement(prop["id"], period_label="2026-05",
                                       basis="ACCRUAL")
        stmt2 = create_draft_statement(prop["id"], period_label="2026-06",
                                       basis="ACCRUAL")
        v_pre = property_version(prop["id"])
        get_success_data(api.finalize_owner_statement(stmt1["id"], PM))
        get_success_data(api.finalize_owner_statement(stmt2["id"], PM))
        first = get_success_data(api.distribute_owner_statement(
            stmt1["id"], {"expected_property_version": v_pre}, PM))
        assert first["status"] == "DISTRIBUTED"
        res = api.distribute_owner_statement(
            stmt2["id"], {"expected_property_version": v_pre}, PM)
        validate_error(res, "ERR_STALE_VERSION")


class TestDerivedFields:
    def test_distributable_reconciles_after_maintenance_debit(self, api):
        """PRD §2.8: "distributable_cents is derived and is recomputed on every
        trust mutation as the trust balance minus the reserve floor, floored at
        zero". PRD §3.7: "the actual cost is debited from the property's
        trust_balance_cents and the distributable figure is recomputed".

        reserve_floor 100000; fund 500000; complete owner-charged work order 120000
        -> trust 380000, distributable max(0, 380000-100000)=280000.

        Design: Corner/cross_cutting_complexity_layers/derived_distributable_reconciles_after_maintenance_debit
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX",
                               reserve_floor_cents=100000)
        fund_trust(prop["id"], 500000)
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        wo = create_assigned_work_order(unit["id"], charge_to_owner=True,
                                        category="APPLIANCE", description="Fridge")
        get_success_data(api.complete_work_order(
            wo["id"], {"actual_cost_cents": 120000, "completed_date": "2026-06-15"},
            PM))
        refreshed = get_success_data(api.get_property(prop["id"], PM))
        assert refreshed["trust_balance_cents"] == 380000
        assert refreshed["distributable_cents"] == 280000

    def test_balance_due_visible_immediately_after_payment(self, api):
        """PRD §3.5: "The lease's own balance_due_cents is the sum of
        amount_outstanding_cents across its charges that are still OPEN or PARTIAL."
        PRD §3.5: "As each charge receives money it advances through its own state
        machine: a charge that receives part but not all of its outstanding amount
        moves from OPEN to PARTIAL".

        200000 RENT charge then a 120000 payment -> balance_due 80000 in the
        immediate GET.

        Design: Corner/consistency_model/immediate_balance_visible_in_same_response
        """
        world = setup_active_lease(state_code="TX", market_rent_cents=200000,
                                   deposit_cents=200000)
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, period_label="2026-06",
                         due_date="2026-06-01")
        post_payment(lease_id, 120000, received_date="2026-06-05")
        lease = get_success_data(api.get_lease(lease_id, PM))
        assert lease["balance_due_cents"] == 80000
