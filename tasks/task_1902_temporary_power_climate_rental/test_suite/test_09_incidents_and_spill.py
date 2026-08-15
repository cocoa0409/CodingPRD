"""Incident lifecycle, spill cascade, and waiver segregation (PRD §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assess_incident,
    create_visit,
    get_contract,
    get_incident,
    get_unit,
    get_visit,
    make_claims_assessor_headers,
    make_depot_manager_headers,
    report_incident,
    setup_on_rent_contract,
    setup_reported_incident,
    validate_error,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_CLAIMS = TEST_USERS["claims_assessor_headers"]


class TestSpillCascade:
    def _setup_spill(self, api):
        """ON_RENT contract (window 09-01..09-15) with a SCHEDULED technician visit;
        clock at 2026-09-03; a SPILL reported against the deployed unit."""
        bundle = setup_on_rent_contract(
            contract_overrides={"expected_offhire_date": "2026-09-15T00:00:00Z"},
            clock_after_start="2026-09-03T00:00:00Z",
        )
        visit = create_visit(
            bundle["contract"]["id"], "TECHNICIAN",
            scheduled_start="2026-09-10T10:00:00Z",
            scheduled_end="2026-09-10T11:00:00Z",
            assigned_technician_id="tech-1",
        )
        incident = report_incident(
            bundle["contract"]["id"], bundle["unit"]["id"], "SPILL",
            as_customer_id=bundle["customer"]["id"], spill_volume_liters=25,
        )
        bundle["visit"] = visit
        bundle["incident"] = incident
        return bundle

    def test_spill_quarantines_unit_and_suspends_contract(self, api):
        """PRD §3.8: "When a `SPILL` incident is recorded against a unit currently
        `DEPLOYED` on the referenced contract, a three-link cascade fires: link 1
        quarantines the unit, moving it `DEPLOYED → QUARANTINED`; link 2 suspends the
        parent contract, moving it `ON_RENT → SUSPENDED` and incrementing its
        version".

        Design: Difficulty/transitive_cascade/spill_report_cascades_quarantine_suspend_cancel
        """
        bundle = self._setup_spill(api)
        assert bundle["incident"]["status"] == "REPORTED"
        assert get_unit(bundle["unit"]["id"])["status"] == "QUARANTINED"
        assert get_contract(bundle["contract"]["id"])["status"] == "SUSPENDED"

    def test_spill_cancels_scheduled_visits(self, api):
        """PRD §3.8: "link 3 cancels every visit still `SCHEDULED` for that contract,
        moving each to `CANCELLED`."

        Design: Difficulty/transitive_cascade/spill_report_cascades_quarantine_suspend_cancel
        """
        bundle = self._setup_spill(api)
        assert get_visit(bundle["visit"]["id"])["status"] == "CANCELLED"
        # The rest of the chain also lands: unit and contract states coherent.
        assert get_unit(bundle["unit"]["id"])["status"] == "QUARANTINED"
        assert get_contract(bundle["contract"]["id"])["status"] == "SUSPENDED"


class TestWaiverSegregationOfDuties:
    def test_waive_by_assessing_user_rejected(self, api):
        """PRD §3.8: "A `DepotManager` may waive it, moving the incident `ASSESSED →
        WAIVED`, but segregation of duties forbids the waver from being the assessor:
        when the acting `X-User-ID` equals the incident's `assessed_by`, the waiver is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/waive_by_same_user_as_assessor_returns_segregation
        """
        bundle = setup_reported_incident("DAMAGE")
        incident = assess_incident(bundle["incident"]["id"], 15000, assessor_id="claims-99")
        assert incident["status"] == "ASSESSED"
        assert incident["assessed_by"] == "claims-99"

        same_user = api.waive_incident(
            incident["id"], make_depot_manager_headers("claims-99")
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        still = get_incident(incident["id"])
        assert still["status"] == "ASSESSED"
        assert still["assessed_by"] == "claims-99"

        waived = validate_success(
            api.waive_incident(incident["id"], make_depot_manager_headers("depot-7")), 200
        )
        assert waived["status"] == "WAIVED"
