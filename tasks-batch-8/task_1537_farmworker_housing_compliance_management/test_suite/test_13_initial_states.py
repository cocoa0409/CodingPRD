"""Declared initial states for every entity at creation."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_member,
    create_authorization,
    create_building,
    create_complaint,
    create_household,
    create_inspection,
    create_pest_treatment,
    create_season_window,
    create_site,
    create_tenancy,
    create_unit,
    create_work_order,
    schedule_certification,
    certify_unit,
    set_eligibility,
    setup_certified_site,
    validate_paginated,
    validate_success,
    open_site,
    get_unit,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
LEAD = TEST_USERS["maintenance_lead_headers"]
INSPECTOR = TEST_USERS["compliance_inspector_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.1: "the site is born in `DRAFT` with a `compliance_posture`
        of `NORMAL`."; "A new window starts `PLANNED`."
        PRD §3.2: "A unit is born `REGISTERED`"; "the certification starts
        `SCHEDULED`"
        PRD §3.3: "The household starts `PENDING_ELIGIBILITY`"; "A referral
        starts `INITIATED`"
        PRD §3.4: "The tenancy starts `PENDING_MOVE_IN`"
        PRD §3.5: "The server stamps `charge_date` from the clock at posting,
        and each entry is born `POSTED`."; "The authorization starts `ACTIVE`"
        PRD §3.6: "The order starts `REPORTED`."; "the treatment starts
        `SCHEDULED`"
        PRD §3.7: "The complaint carries a `category` — `HABITABILITY`,
        `RENT`, `UTILITY`, `HARASSMENT`, or `OTHER` — and a `description`,
        starts `FILED`, and stamps `filed_at` from the logical clock."; "the
        inspection starts `SCHEDULED`"

        Design: Corner/state_machines/initial_states_on_create
        """
        site = create_site(name="Site IS")
        assert site["status"] == "DRAFT"

        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        assert unit["status"] == "REGISTERED"

        cert = schedule_certification(unit["id"])
        assert cert["status"] == "SCHEDULED"
        # Walk the cert to PASSED so the site can open below.
        validate_success(api.update_unit_certification(
            cert["id"], {"status": "IN_PROGRESS"}, INSPECTOR))
        validate_success(api.update_unit_certification(
            cert["id"], {"status": "PASSED", "deficiency_count": 0},
            INSPECTOR))

        window = create_season_window(site["id"])
        assert window["status"] == "PLANNED"

        opened = open_site(site["id"])
        assert opened["status"] == "OPEN", "Setup failed"

        household = create_household(name="Fam IS")
        assert household["eligibility_status"] == "PENDING_ELIGIBILITY"
        add_member(household["id"], "IS One", "1990-01-01", "HEAD")

        auth = create_authorization(household["id"], cap_percent=0.25,
                                    purpose="RENT")
        assert auth["status"] == "ACTIVE"

        set_eligibility(household["id"], "ELIGIBLE")

        tenancy = create_tenancy(household["id"], unit["id"],
                                 move_in_date="2026-08-11")
        assert tenancy["status"] == "PENDING_MOVE_IN"

        activated = validate_success(api.update_tenancy(
            tenancy["id"], {"status": "ACTIVE"}, INTAKE))
        assert activated["status"] == "ACTIVE", "Setup failed"

        # The activation-posted RENT ledger entry starts POSTED.
        entries, _ = validate_paginated(api.list_charge_ledger_entries(
            ADMIN, params={"tenancy_id": tenancy["id"]}))
        assert len(entries) >= 1
        assert entries[0]["status"] == "POSTED"

        wo = create_work_order(unit["id"], "OTHER", "MINOR", "d")
        assert wo["status"] == "REPORTED"

        treatment = create_pest_treatment(unit["id"], "ROUTINE",
                                          "2026-09-01", 2)
        assert treatment["status"] == "SCHEDULED"

        complaint = create_complaint(tenancy["id"], "OTHER", "d")
        assert complaint["status"] == "FILED"

        inspection = create_inspection(site["id"], "HUD", "2026-09-01")
        assert inspection["status"] == "SCHEDULED"

        referral = validate_success(api.create_service_referral(
            {"household_id": household["id"], "referral_type": "HEALTH",
             "agency_name": "Clinic"}, INTAKE), expected_status=201)
        assert referral["status"] == "INITIATED"
