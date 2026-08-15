"""Tenant credit gating of lease verification, rollover-risk tier
boundaries, and the remaining-term computation."""
from test_helpers import (
    ApiErrorId,
    add_lease,
    add_property,
    analyze_tenant,
    approve_tenant,
    create_approved_tenant,
    create_deal,
    create_tenant,
    set_clock,
    validate_error,
    validate_success,
)


class TestLeaseVerifyDependsOnTenantCredit:
    def test_verify_blocked_while_tenant_analyzed_not_approved(
            self, api, analyst_headers):
        """PRD §3.2: "Verification by an analyst requires the tenant's credit
        assessment to be `APPROVED` — otherwise `ERR_TENANT_CREDIT_NOT_APPROVED`
        (HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/lease_verify_depends_on_tenant_credit_state
        """
        deal = create_deal(deal_name="CrossEntDeal1",
                           purchase_price_cents=15000000)
        prop = add_property(deal["id"], address="31 Cross Rd",
                            property_type="QSR", rentable_sqft=3000,
                            year_built=2016)
        tenant = create_tenant(legal_name="CrossTenant",
                               credit_rating="NON_INVESTMENT_GRADE",
                               credit_score=650, annual_revenue_cents=30000000,
                               is_guaranteed=True)
        analyze_tenant(tenant["id"])  # ANALYZED, not yet APPROVED
        lease = add_lease(deal["id"], prop["id"], tenant["id"],
                          annual_base_rent_cents=900000,
                          lease_expiration_date="2035-01-01T00:00:00Z")

        blocked = api.verify_lease(deal["id"], prop["id"], lease["id"],
                                   analyst_headers)
        validate_error(blocked, ApiErrorId.ERR_TENANT_CREDIT_NOT_APPROVED)

        approve_tenant(tenant["id"])
        verified = validate_success(
            api.verify_lease(deal["id"], prop["id"], lease["id"],
                             analyst_headers))
        assert verified["status"] == "VERIFIED", (
            "The identical verify call succeeds once the tenant is APPROVED")

    def test_verify_blocked_while_tenant_pending(self, api, analyst_headers):
        """PRD §3.2: "Verification by an analyst requires the tenant's credit
        assessment to be `APPROVED` — otherwise `ERR_TENANT_CREDIT_NOT_APPROVED`
        (HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/lease_verify_depends_on_tenant_credit_state
        """
        deal = create_deal(deal_name="CrossEntDeal1b")
        prop = add_property(deal["id"])
        tenant = create_tenant(legal_name="PendingTenant")  # still PENDING
        lease = add_lease(deal["id"], prop["id"], tenant["id"])

        resp = api.verify_lease(deal["id"], prop["id"], lease["id"],
                                analyst_headers)
        validate_error(resp, ApiErrorId.ERR_TENANT_CREDIT_NOT_APPROVED)


class TestLeaseComputedFields:
    def test_lease_computed_fields_set_at_verify(self, api, analyst_headers):
        """PRD §3.2: "The `remaining_term_months` is the whole-month count
        between the logical clock's current instant and the
        `lease_expiration_date`"
        PRD §3.2: "120 or more is `LOW`."
        PRD §2.6: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`"

        Design: Corner/entities/lease_computed_fields_ignore_client_input
        """
        deal = create_deal(deal_name="ComputedDeal",
                           purchase_price_cents=10000000,
                           earnest_money_cents=100000)
        prop = add_property(deal["id"], address="9 Computed Ln")
        tenant = create_approved_tenant(legal_name="CT")
        lease = add_lease(deal["id"], prop["id"], tenant["id"],
                          lease_expiration_date="2036-08-01T00:00:00Z")
        assert lease["status"] == "DRAFT"

        verified = validate_success(
            api.verify_lease(deal["id"], prop["id"], lease["id"],
                             analyst_headers))
        # (2036-2026)*12 + (8-8) = 120; expiry day 1 is not earlier than
        # the clock day 1, so no partial-month decrement.
        assert verified["remaining_term_months"] == 120
        assert verified["rollover_risk_tier"] == "LOW"


class TestRolloverRiskTierBoundaries:
    def _setup_four_boundary_leases(self, api, analyst_headers):
        deal = create_deal(deal_name="TierBoundaryDeal",
                           deal_type="MULTI_TENANT",
                           purchase_price_cents=20000000,
                           earnest_money_cents=300000)
        prop = add_property(deal["id"], address="21 Tier St",
                            rentable_sqft=20000)
        tenant = create_approved_tenant(legal_name="TierTenant")
        leases = {}
        for key, expiry in (("l24", "2028-08-01T00:00:00Z"),
                            ("l23", "2028-07-31T00:00:00Z"),
                            ("l60", "2031-08-01T00:00:00Z"),
                            ("l59", "2031-07-31T00:00:00Z")):
            leases[key] = add_lease(
                deal["id"], prop["id"], tenant["id"],
                lease_commencement_date="2024-01-01T00:00:00Z",
                lease_expiration_date=expiry)
        return deal, prop, leases

    def test_tier_boundary_at_24_months(self, api, analyst_headers):
        """PRD §3.2: "fewer than 24 months remaining is `CRITICAL`"
        PRD §3.2: "The boundaries are inclusive of the upper tier — exactly
        24 months is `HIGH`, not `CRITICAL`"
        PRD §2.6: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`"

        Design: Difficulty/boundary_precision_check/rollover_risk_tier_boundary_exactly_24_months_on_lease_verify
        """
        deal, prop, leases = self._setup_four_boundary_leases(
            api, analyst_headers)

        l24 = validate_success(api.verify_lease(
            deal["id"], prop["id"], leases["l24"]["id"], analyst_headers))
        assert l24["remaining_term_months"] == 24
        assert l24["rollover_risk_tier"] == "HIGH", (
            "24 is not fewer than 24, so the tier is HIGH, not CRITICAL")

        l23 = validate_success(api.verify_lease(
            deal["id"], prop["id"], leases["l23"]["id"], analyst_headers))
        assert l23["remaining_term_months"] == 23
        assert l23["rollover_risk_tier"] == "CRITICAL"

    def test_tier_boundary_at_60_months(self, api, analyst_headers):
        """PRD §3.2: "at least 24 but fewer than 60 is `HIGH`; at least 60 but
        fewer than 120 is `MEDIUM`"
        PRD §3.2: "The boundaries are inclusive of the upper tier — exactly
        24 months is `HIGH`, not `CRITICAL`; exactly 60 is `MEDIUM`; exactly
        120 is `LOW`."
        PRD §2.6: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`"

        Design: Difficulty/boundary_precision_check/rollover_risk_tier_boundary_exactly_24_months_on_lease_verify
        """
        deal, prop, leases = self._setup_four_boundary_leases(
            api, analyst_headers)

        l60 = validate_success(api.verify_lease(
            deal["id"], prop["id"], leases["l60"]["id"], analyst_headers))
        assert l60["remaining_term_months"] == 60
        assert l60["rollover_risk_tier"] == "MEDIUM", (
            "60 is not fewer than 60, so the tier is MEDIUM, not HIGH")

        l59 = validate_success(api.verify_lease(
            deal["id"], prop["id"], leases["l59"]["id"], analyst_headers))
        assert l59["remaining_term_months"] == 59
        assert l59["rollover_risk_tier"] == "HIGH"


class TestRemainingTermMonths:
    def test_partial_month_not_counted(self, api, analyst_headers):
        """PRD §3.2: "take the expiry year minus the current year, multiply by
        twelve, add the expiry month minus the current month, subtract one if
        the expiry day-of-month is earlier than the current day-of-month (a
        partial month in progress is not counted), and floor the result at
        zero."

        Design: Corner/calculations/remaining_term_months_partial_month_not_counted
        """
        set_clock("2026-08-15T00:00:00Z")
        deal = create_deal(deal_name="PartialDeal",
                           target_close_date="2026-10-15T00:00:00Z",
                           purchase_price_cents=10000000,
                           earnest_money_cents=100000)
        prop = add_property(deal["id"], address="1 Partial St")
        tenant = create_approved_tenant(legal_name="PaT")
        lease = add_lease(deal["id"], prop["id"], tenant["id"],
                          lease_expiration_date="2036-08-01T00:00:00Z")

        verified = validate_success(
            api.verify_lease(deal["id"], prop["id"], lease["id"],
                             analyst_headers))
        # (2036-2026)*12 + (8-8) = 120, minus 1 because expiry day 1 is
        # earlier than the clock day 15.
        assert verified["remaining_term_months"] == 119
