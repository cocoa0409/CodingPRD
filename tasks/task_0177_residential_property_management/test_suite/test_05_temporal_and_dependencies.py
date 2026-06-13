"""Cross-entity state dependencies and temporal-overlap depth tests."""
import pytest
from test_helpers import get_success_data, validate_error
from test_helpers.fixtures import (
    PM, create_owner, create_property, create_unit, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, setup_active_lease,
    serve_eviction,
)
from test_helpers.api_client import api_client


class TestCrossEntityStateDependency:
    def test_sign_blocked_when_unit_occupied(self, api):
        """PRD §3.3: "The unit must be VACANT_READY, unless this is a renewal whose
        renewed_from_lease_id equals the unit's active_lease_id ... otherwise the
        sign is refused with ERR_UNIT_NOT_AVAILABLE."

        A second non-renewal DRAFT lease on a now-OCCUPIED unit cannot be signed.

        Design: Difficulty/cross_entity_state_dependency/lease_sign_requires_unit_vacant_ready
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX")
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app1 = create_approved_applicant(unit["id"])
        app2 = create_approved_applicant(unit["id"])
        lease1 = create_draft_lease(unit["id"], app1["id"], start_date="2026-06-01",
                                    end_date="2027-06-01", monthly_rent_cents=200000)
        lease2 = create_draft_lease(unit["id"], app2["id"], start_date="2027-06-01",
                                    end_date="2028-06-01", monthly_rent_cents=200000)
        collect_deposit(lease1["id"], collected_cents=200000)
        collect_deposit(lease2["id"], collected_cents=200000)
        get_success_data(api.sign_lease(lease1["id"], PM))
        res = api.sign_lease(lease2["id"], PM)
        validate_error(res, "ERR_UNIT_NOT_AVAILABLE")

    def test_sign_blocked_when_unit_occupied_status_409(self, api):
        """PRD §3.3: "otherwise the sign is refused with ERR_UNIT_NOT_AVAILABLE."

        Second test of the dependency instance: assert HTTP status 409.

        Design: Difficulty/cross_entity_state_dependency/lease_sign_requires_unit_vacant_ready
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX")
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app1 = create_approved_applicant(unit["id"])
        app2 = create_approved_applicant(unit["id"])
        lease1 = create_draft_lease(unit["id"], app1["id"], start_date="2026-06-01",
                                    end_date="2027-06-01", monthly_rent_cents=200000)
        lease2 = create_draft_lease(unit["id"], app2["id"], start_date="2027-06-01",
                                    end_date="2028-06-01", monthly_rent_cents=200000)
        collect_deposit(lease1["id"], collected_cents=200000)
        collect_deposit(lease2["id"], collected_cents=200000)
        get_success_data(api.sign_lease(lease1["id"], PM))
        res = api.sign_lease(lease2["id"], PM)
        assert res.status_code == 409
        validate_error(res, "ERR_UNIT_NOT_AVAILABLE")

    def test_settle_blocked_while_lease_active(self, api):
        """PRD §3.6: "Settlement is run by a PropertyManager and may proceed only
        once the lease the deposit secures has reached EXPIRED or TERMINATED;
        attempting to settle while the lease is still active is refused with
        ERR_LEASE_STILL_ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/deposit_settle_requires_lease_ended
        """
        world = setup_active_lease(state_code="TX")
        dep = world["deposit"]
        res = api.settle_security_deposit(
            dep["id"], {"settlement_date": "2026-12-01"}, PM)
        validate_error(res, "ERR_LEASE_STILL_ACTIVE")

    def test_settle_blocked_while_lease_active_status_409(self, api):
        """PRD §3.6: "attempting to settle while the lease is still active is
        refused with ERR_LEASE_STILL_ACTIVE."

        Second test of the dependency instance: assert HTTP status 409.

        Design: Difficulty/cross_entity_state_dependency/deposit_settle_requires_lease_ended
        """
        world = setup_active_lease(state_code="TX")
        res = api.settle_security_deposit(
            world["deposit"]["id"], {"settlement_date": "2026-12-01"}, PM)
        assert res.status_code == 409
        validate_error(res, "ERR_LEASE_STILL_ACTIVE")


class TestTemporalOverlap:
    def test_lease_term_overlap_rejected(self, api):
        """PRD §3.3: "A new lease's half-open term — covering start_date up to but
        not including end_date — must not overlap the term of any existing ACTIVE
        or RENEWAL_OFFERED lease on the same unit, except the very prior lease
        being renewed ... A violation is rejected with ERR_LEASE_OVERLAP."

        Existing ACTIVE term [2026-06-01, 2027-06-01); a new term
        [2026-12-01, 2027-12-01) truly overlaps.

        Design: Difficulty/resource_temporal_overlap/lease_term_half_open_overlap_on_unit
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX")
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app1 = create_approved_applicant(unit["id"])
        app2 = create_approved_applicant(unit["id"])
        lease1 = create_draft_lease(unit["id"], app1["id"], start_date="2026-06-01",
                                    end_date="2027-06-01", monthly_rent_cents=200000)
        collect_deposit(lease1["id"], collected_cents=200000)
        get_success_data(api.sign_lease(lease1["id"], PM))
        res = api.create_lease({
            "unit_id": unit["id"], "applicant_id": app2["id"],
            "start_date": "2026-12-01", "end_date": "2027-12-01",
            "monthly_rent_cents": 200000,
        }, PM)
        validate_error(res, "ERR_LEASE_OVERLAP")

    def test_lease_term_overlap_status_409(self, api):
        """PRD §3.3: "A violation is rejected with ERR_LEASE_OVERLAP."

        Second test of the lease-overlap instance: assert HTTP status 409.

        Design: Difficulty/resource_temporal_overlap/lease_term_half_open_overlap_on_unit
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="TX")
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app1 = create_approved_applicant(unit["id"])
        app2 = create_approved_applicant(unit["id"])
        lease1 = create_draft_lease(unit["id"], app1["id"], start_date="2026-06-01",
                                    end_date="2027-06-01", monthly_rent_cents=200000)
        collect_deposit(lease1["id"], collected_cents=200000)
        get_success_data(api.sign_lease(lease1["id"], PM))
        res = api.create_lease({
            "unit_id": unit["id"], "applicant_id": app2["id"],
            "start_date": "2026-12-01", "end_date": "2027-12-01",
            "monthly_rent_cents": 200000,
        }, PM)
        assert res.status_code == 409
        validate_error(res, "ERR_LEASE_OVERLAP")

    def test_eviction_notice_window_overlap_rejected(self, api):
        """PRD §3.8: "If any existing non-terminal eviction case on the lease has a
        closed window running from its notice_date through its cure_deadline_date,
        and the new notice's notice_date falls anywhere inside that window —
        inclusive of both the opening and closing endpoints — the new notice is
        rejected with ERR_EVICTION_WINDOW_OVERLAP." PRD §3.8: "for nonpayment the
        cure window is ... 14 days in New York".

        NY first notice 2026-06-10 -> deadline 2026-06-24; a second notice
        2026-06-12 lands inside [2026-06-10, 2026-06-24].

        Design: Difficulty/resource_temporal_overlap/eviction_notice_window_closed_overlap_on_lease
        """
        world = setup_active_lease(state_code="NY", market_rent_cents=250000,
                                   deposit_cents=250000)
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=250000, period_label="2026-06",
                         due_date="2026-06-01")
        first = serve_eviction(lease_id, reason="NONPAYMENT",
                               notice_date="2026-06-10")
        assert first["cure_deadline_date"] == "2026-06-24"
        res = api.create_eviction({
            "lease_id": lease_id, "reason": "NONPAYMENT",
            "notice_date": "2026-06-12",
        }, PM)
        validate_error(res, "ERR_EVICTION_WINDOW_OVERLAP")

    def test_eviction_notice_window_overlap_status_409(self, api):
        """PRD §3.8: "the new notice is rejected with ERR_EVICTION_WINDOW_OVERLAP."

        Second test of the eviction-window-overlap instance: assert HTTP 409.

        Design: Difficulty/resource_temporal_overlap/eviction_notice_window_closed_overlap_on_lease
        """
        world = setup_active_lease(state_code="NY", market_rent_cents=250000,
                                   deposit_cents=250000)
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=250000, due_date="2026-06-01")
        serve_eviction(lease_id, reason="NONPAYMENT", notice_date="2026-06-10")
        res = api.create_eviction({
            "lease_id": lease_id, "reason": "NONPAYMENT",
            "notice_date": "2026-06-12",
        }, PM)
        assert res.status_code == 409
        validate_error(res, "ERR_EVICTION_WINDOW_OVERLAP")
