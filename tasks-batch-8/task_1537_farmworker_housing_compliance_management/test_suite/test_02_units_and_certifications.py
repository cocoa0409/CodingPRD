"""Unit registration defaults and the pre-occupancy certification lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_building,
    create_site,
    create_unit,
    get_unit,
    schedule_certification,
    set_clock,
    setup_pending_tenancy,
    validate_error,
    validate_success,
)


class TestUnitCreation:
    def test_unit_computed_fields_default_on_create(self, api,
                                                    operator_admin_headers):
        """PRD §3.2: "A unit is born `REGISTERED` with `current_occupancy`
        zero, both habitability scores at zero, `under_pest_exclusion` false,
        and `pest_exclusion_end_date` null."

        Design: Corner/entities/unit_computed_fields_default_on_create
        """
        site = create_site()
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        assert unit["status"] == "REGISTERED"
        assert unit["current_occupancy"] == 0
        assert unit["habitability_score_cumulative"] == 0
        assert unit["habitability_score_worst_case"] == 0
        assert unit["under_pest_exclusion"] is False
        assert unit.get("pest_exclusion_end_date") is None

    def test_invalid_enum_unit_type_rejected(self, api, operator_admin_headers):
        """PRD §2.8: "Third, request-body shape — required fields present, types
        correct, enum values inside their declared sets ... — all under
        `ERR_INVALID_REQUEST` (HTTP 400), applied on every mutation endpoint."

        Design: Corner/entities/invalid_enum_unit_type_rejected
        """
        site = create_site()
        building = create_building(site["id"])
        resp = api.create_housing_unit(
            {"building_id": building["id"], "site_id": site["id"],
             "unit_code": "U1", "unit_type": "LUXURY", "max_occupancy": 4,
             "monthly_rent_cents": 90000},
            operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCertificationTransitions:
    def test_cert_schedule_to_passed_invalid_transition(
            self, api, compliance_inspector_headers):
        """PRD §3.2: "the certification starts `SCHEDULED` and records its
        creator as `inspector_id`. Beginning the visit — `SCHEDULED →
        IN_PROGRESS` — is allowed only while the unit is not `DECOMMISSIONED`"
        PRD §2.8: "Seventh, state-machine validity: the requested target status
        must be a declared transition from the entity's current status ...
        `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/cert_schedule_to_passed_invalid_transition
        """
        site = create_site()
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        cert = schedule_certification(unit["id"])

        resp = api.update_unit_certification(
            cert["id"], {"status": "PASSED", "deficiency_count": 0},
            compliance_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = validate_success(api.get_unit_certification(
            cert["id"], compliance_inspector_headers))
        assert current["status"] == "SCHEDULED"

    def test_certification_not_found_generic(self, api,
                                             compliance_inspector_headers):
        """PRD §2.11: "every other resource type (season windows, buildings,
        certifications, household members, authorizations, ledger entries, pest
        treatments, complaints, referrals) uses the generic `ERR_NOT_FOUND`."

        Design: Corner/validations/certification_not_found_generic
        """
        resp = api.get_unit_certification(NON_EXISTENT_UUID,
                                          compliance_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_cert_failed_reinspection_cycle_with_critical_gate(
            self, api, compliance_inspector_headers, maintenance_lead_headers):
        """PRD §3.2: "Remediation loops: from `FAILED` the certification may
        return to `IN_PROGRESS` only when the unit has zero non-terminal
        `CRITICAL` work orders (`ERR_OPEN_WORK_ORDERS_REMAIN`)."
        PRD §3.2: "`IN_PROGRESS → PASSED` stamps `inspection_date` with the
        clock date, sets `expiry_date` 180 days later, lifts a `REGISTERED`
        unit to `CERTIFIED`, and recomputes the site posture."

        Design: Corner/state_machines/cert_failed_reinspection_cycle_with_critical_gate
        """
        site = create_site()
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        cert = schedule_certification(unit["id"])
        validate_success(api.update_unit_certification(
            cert["id"], {"status": "IN_PROGRESS"},
            compliance_inspector_headers))
        failed = validate_success(api.update_unit_certification(
            cert["id"], {"status": "FAILED", "deficiency_count": 3},
            compliance_inspector_headers))
        assert failed["status"] == "FAILED"

        wo = validate_success(api.create_work_order(
            {"unit_id": unit["id"], "category": "ELECTRICAL",
             "severity": "CRITICAL", "description": "exposed wiring"},
            maintenance_lead_headers), expected_status=201)

        blocked = api.update_unit_certification(
            cert["id"], {"status": "IN_PROGRESS"},
            compliance_inspector_headers)
        validate_error(blocked, ApiErrorId.ERR_OPEN_WORK_ORDERS_REMAIN)

        validate_success(api.update_work_order(
            wo["id"], {"status": "CANCELLED"}, maintenance_lead_headers))

        retry = validate_success(api.update_unit_certification(
            cert["id"], {"status": "IN_PROGRESS"},
            compliance_inspector_headers))
        assert retry["status"] == "IN_PROGRESS"
        passed = validate_success(api.update_unit_certification(
            cert["id"], {"status": "PASSED", "deficiency_count": 0},
            compliance_inspector_headers))
        assert passed["status"] == "PASSED"
        assert get_unit(unit["id"])["status"] == "CERTIFIED"


class TestActivationRequiresValidCertification:
    """Difficulty instance: expired certification blocks activation and flips
    lazily to EXPIRED."""

    def _setup_past_expiry(self, api, intake_coordinator_headers):
        """Site OPEN; unit certified with inspection_date 2026-08-01 (expiry
        2027-01-28); tenancy PENDING_MOVE_IN; clock advanced past expiry."""
        ctx = setup_pending_tenancy(site_name="Site CE")
        cert = ctx["cert"]
        assert cert["expiry_date"] == "2027-01-28", (
            f"Setup failed: expected expiry 2027-01-28, got "
            f"{cert['expiry_date']}")
        set_clock("2027-01-29T00:00:00Z")
        return ctx

    def test_expired_certification_blocks_activation(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "The unit must hold a `PASSED` certification with an
        `expiry_date` on or after the clock date (`ERR_NO_VALID_CERTIFICATION`)
        — and as a side effect of this very check, a `PASSED` certification
        whose `expiry_date` has already passed flips to `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_valid_certification
        """
        ctx = self._setup_past_expiry(api, intake_coordinator_headers)
        resp = api.update_tenancy(ctx["tenancy"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_CERTIFICATION)

        tenancy = validate_success(api.get_tenancy(ctx["tenancy"]["id"],
                                                   intake_coordinator_headers))
        assert tenancy["status"] == "PENDING_MOVE_IN"

    def test_expired_certification_flips_to_expired_on_consult(
            self, api, compliance_inspector_headers,
            intake_coordinator_headers):
        """PRD §3.2: "whenever a write consults a certification (a tenancy
        activation, a site status change, or a certification update), a
        `PASSED` certification whose `expiry_date` is before the clock date
        flips to `EXPIRED`."
        PRD §3.2: "`IN_PROGRESS → PASSED` stamps `inspection_date` with the
        clock date, sets `expiry_date` 180 days later"

        Design: Difficulty/cross_entity_state_dependency/activation_requires_valid_certification
        """
        ctx = self._setup_past_expiry(api, intake_coordinator_headers)
        cert = ctx["cert"]
        assert cert["inspection_date"] == "2026-08-01"
        assert cert["expiry_date"] == "2027-01-28"

        resp = api.update_tenancy(ctx["tenancy"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_CERTIFICATION)

        cert_after = validate_success(api.get_unit_certification(
            cert["id"], compliance_inspector_headers))
        assert cert_after["status"] == "EXPIRED", (
            "The consulted stale PASSED certification must flip to EXPIRED")
