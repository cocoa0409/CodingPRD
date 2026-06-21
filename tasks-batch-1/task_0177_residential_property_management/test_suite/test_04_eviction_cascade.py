"""Eviction-enforce cascade and validation-priority conflicts — depth tests."""
import pytest
from test_helpers import get_success_data, validate_error
from test_helpers.fixtures import (
    PM, CO, create_unit, create_screened_applicant, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, setup_active_lease,
    setup_filed_eviction, serve_eviction,
)
from test_helpers.api_client import api_client


class TestEnforceCascade:
    def test_enforce_terminates_lease_and_vacates_unit(self, api):
        """PRD §3.8: "Enforcement drives the lease from ACTIVE to TERMINATED, and
        that lease termination cascades exactly as the eviction-driven wind-down:
        the tenant is advanced to FORMER, the unit is driven to VACANT_TURN with
        its active_lease_id cleared to null".

        Design: Difficulty/transitive_cascade/eviction_enforce_terminates_lease_vacates_unit_opens_turnover
        """
        world = setup_filed_eviction(state_code="FL", reason="NONPAYMENT",
                                     notice_date="2026-06-10",
                                     file_as_of_date="2026-06-20")
        eviction = world["eviction"]
        tenant_id = world["tenant_id"]
        lease_id = world["lease"]["id"]
        unit_id = world["unit"]["id"]
        enforced = get_success_data(api.enforce_eviction(eviction["id"], CO))
        assert enforced["status"] == "ENFORCED"
        lease = get_success_data(api.get_lease(lease_id, PM))
        assert lease["status"] == "TERMINATED"
        tenant = get_success_data(api.get_tenant(tenant_id, PM))
        assert tenant["status"] == "FORMER"
        unit = get_success_data(api.get_unit(unit_id, PM))
        assert unit["occupancy_status"] == "VACANT_TURN"

    def test_enforce_auto_opens_turnover(self, api):
        """PRD §3.8: "a turnover project is automatically opened for the unit, with
        its opened_date set to the enforcement date and its target_ready_date set
        to that date plus the default turnaround of 14 days."

        Design: Difficulty/transitive_cascade/eviction_enforce_terminates_lease_vacates_unit_opens_turnover
        """
        world = setup_filed_eviction(state_code="FL", reason="NONPAYMENT",
                                     notice_date="2026-06-10",
                                     file_as_of_date="2026-06-20")
        unit_id = world["unit"]["id"]
        get_success_data(api.enforce_eviction(world["eviction"]["id"], CO))
        res = api.list_turnovers(PM, params={"unit_id": unit_id})
        body = res.json()
        turnovers = body.get("data", [])
        assert any(t["status"] == "OPEN" for t in turnovers), (
            "an OPEN turnover must be auto-opened for the vacated unit"
        )


class TestValidationPriorityConflicts:
    def test_forbidden_beats_invalid_state_on_enforce(self, api):
        """PRD §2.6: "Authorization is checked second: a known role that lacks
        permission for the operation yields ERR_FORBIDDEN." PRD §3.8: "A
        ComplianceOfficer enforces a filed case".

        A PropertyManager (not authorized to enforce) calls enforce on a
        NOTICE_SERVED (not FILED) case; both the role check and the state check
        would fail, and the higher-priority ERR_FORBIDDEN wins.

        Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_enforce
        """
        world = setup_active_lease(state_code="TX")
        eviction = serve_eviction(world["lease"]["id"], reason="HOLDOVER",
                                  notice_date="2026-06-10")
        res = api.enforce_eviction(eviction["id"], PM)
        validate_error(res, "ERR_FORBIDDEN")

    def test_forbidden_beats_invalid_state_status_403(self, api):
        """PRD §2.6: "a known role that lacks permission for the operation yields
        ERR_FORBIDDEN."

        Second test of the priority-conflict instance: assert HTTP status 403.

        Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_enforce
        """
        world = setup_active_lease(state_code="TX")
        eviction = serve_eviction(world["lease"]["id"], reason="HOLDOVER",
                                  notice_date="2026-06-10")
        res = api.enforce_eviction(eviction["id"], PM)
        assert res.status_code == 403
        validate_error(res, "ERR_FORBIDDEN")

    def test_screening_failed_beats_unit_not_available_on_decide(self, api):
        """PRD §2.6: "Among those domain guards the ordering is: the screening gate
        (ERR_SCREENING_FAILED), then the cure-window temporal check ... then unit
        availability (ERR_UNIT_NOT_AVAILABLE)". PRD §3.2: "attempting to approve an
        application whose screening_decision is FAIL is refused with
        ERR_SCREENING_FAILED".

        A FAILed applicant on an already-OCCUPIED unit violates both guards;
        ERR_SCREENING_FAILED (the earlier guard) wins.

        Design: Difficulty/priority_pair_validation_conflict/unit_unavailable_beats_screening_failed_on_decide
        """
        # Occupy the unit with a first signed lease.
        owner_world = setup_active_lease(state_code="TX", market_rent_cents=200000)
        unit_id = owner_world["unit"]["id"]
        # Second applicant on the same unit, screened to FAIL.
        bad = create_screened_applicant(unit_id, annual_income_cents=6000000,
                                        credit_score=700, requested_rent_cents=250000,
                                        monthly_debt_cents=50000)
        assert bad["screening_decision"] == "FAIL"
        res = api.decide_applicant(bad["id"], {"decision": "APPROVE"}, PM)
        validate_error(res, "ERR_SCREENING_FAILED")

    def test_screening_failed_beats_unit_not_available_status_409(self, api):
        """PRD §3.2: "attempting to approve an application whose screening_decision
        is FAIL is refused with ERR_SCREENING_FAILED".

        Second test of the priority-conflict instance: assert HTTP status 409.

        Design: Difficulty/priority_pair_validation_conflict/unit_unavailable_beats_screening_failed_on_decide
        """
        owner_world = setup_active_lease(state_code="TX", market_rent_cents=200000)
        unit_id = owner_world["unit"]["id"]
        bad = create_screened_applicant(unit_id, annual_income_cents=6000000,
                                        credit_score=700, requested_rent_cents=250000,
                                        monthly_debt_cents=50000)
        res = api.decide_applicant(bad["id"], {"decision": "APPROVE"}, PM)
        assert res.status_code == 409
        validate_error(res, "ERR_SCREENING_FAILED")
