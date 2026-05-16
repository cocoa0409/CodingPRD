"""Reference data: patients, providers, service-catalog items.

PRD §3.1 (registration & status semantics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_patient,
    assert_provider,
    assert_service_catalog_item,
    create_patient,
    create_patient_payload,
    create_provider,
    create_provider_payload,
    create_service_catalog_item,
    create_service_catalog_item_payload,
    patch_service_catalog_item,
    retire_service_catalog_item,
    validate_success,
)


# ===========================================================================
# Patient creation
# ===========================================================================
class TestPatient:
    """PRD §3.1: patients."""

    def test_create_patient_starts_active(self, api, admin_headers):
        """PRD §3.1: "Every patient starts in ACTIVE status; the only
        other allowed status value is INACTIVE."

        Claim: a newly created Patient has status=ACTIVE.
        """
        res = api.create_patient(create_patient_payload(), admin_headers)
        patient = validate_success(res, 201)
        assert patient["status"] == "ACTIVE"
        assert_patient(patient)

    def test_patient_plan_type_must_be_recognised(self, api,
                                                  admin_headers):
        """PRD §3.1: "the plan_type, which must be one of COMMERCIAL,
        MEDICARE, or MEDICAID."

        Claim: each accepted plan_type round-trips on the created
        Patient.
        """
        for plan in ("COMMERCIAL", "MEDICARE", "MEDICAID"):
            res = api.create_patient(
                create_patient_payload(plan_type=plan), admin_headers,
            )
            patient = validate_success(res, 201)
            assert patient["plan_type"] == plan


# ===========================================================================
# Provider creation
# ===========================================================================
class TestProvider:
    """PRD §3.1: providers."""

    def test_create_provider_starts_active(self, api, admin_headers):
        """PRD §3.1: "Every provider starts in ACTIVE status; the only
        other allowed status value is SUSPENDED."

        Claim: a newly created Provider has status=ACTIVE.
        """
        res = api.create_provider(create_provider_payload(), admin_headers)
        provider = validate_success(res, 201)
        assert provider["status"] == "ACTIVE"
        assert_provider(provider)

    def test_provider_npi_must_be_ten_digits(self, api, admin_headers):
        """PRD §3.1: "the npi (the National Provider Identifier —
        exactly 10 digits and unique across the system)".

        Claim: a created Provider returns a 10-digit npi.
        """
        res = api.create_provider(
            create_provider_payload(npi="1234567890"), admin_headers,
        )
        provider = validate_success(res, 201)
        assert provider["npi"] == "1234567890"
        assert len(provider["npi"]) == 10

    def test_provider_in_network_defaults_true(self, api, admin_headers):
        """PRD §3.1: "an optional in_network boolean that defaults to
        true."

        Claim: omitting in_network from the payload yields
        in_network=True on the response.
        """
        payload = create_provider_payload()
        payload.pop("in_network", None)
        res = api.create_provider(payload, admin_headers)
        provider = validate_success(res, 201)
        assert provider["in_network"] is True


# ===========================================================================
# ServiceCatalogItem creation + patch + retirement
# ===========================================================================
class TestServiceCatalogItem:
    """PRD §3.1: catalog items."""

    def test_create_catalog_item_starts_active_version_one(
        self, api, admin_headers,
    ):
        """PRD §3.1: "Every catalog item starts in ACTIVE status".
        PRD §2.4: "version (integer): a system-managed counter that
        starts at 1 on creation".

        Claim: a newly created ServiceCatalogItem has status=ACTIVE and
        version=1.
        """
        res = api.create_service_catalog_item(
            create_service_catalog_item_payload(), admin_headers,
        )
        item = validate_success(res, 201)
        assert item["status"] == "ACTIVE"
        assert item["version"] == 1
        assert_service_catalog_item(item)

    def test_default_standard_sla_hours_is_336(self, api, admin_headers):
        """PRD §3.1: "standard_sla_hours (the decision window for a
        STANDARD request, defaulting to 336 — that is, 14 days — and
        required to be at least 24)".

        Claim: omitting standard_sla_hours yields 336.
        """
        payload = create_service_catalog_item_payload()
        payload.pop("standard_sla_hours", None)
        res = api.create_service_catalog_item(payload, admin_headers)
        item = validate_success(res, 201)
        assert item["standard_sla_hours"] == 336

    def test_default_expedited_sla_hours_is_72(self, api, admin_headers):
        """PRD §3.1: "expedited_sla_hours (defaulting to 72 — three days
        — and required to be at least 4 and strictly less than
        standard_sla_hours)".

        Claim: omitting expedited_sla_hours yields 72.
        """
        payload = create_service_catalog_item_payload()
        payload.pop("expedited_sla_hours", None)
        res = api.create_service_catalog_item(payload, admin_headers)
        item = validate_success(res, 201)
        assert item["expedited_sla_hours"] == 72

    def test_default_approval_validity_days_is_90(
        self, api, admin_headers,
    ):
        """PRD §3.1: "approval_validity_days (defaulting to 90 and
        required to be at least 1)".

        Claim: omitting approval_validity_days yields 90.
        """
        payload = create_service_catalog_item_payload()
        payload.pop("approval_validity_days", None)
        res = api.create_service_catalog_item(payload, admin_headers)
        item = validate_success(res, 201)
        assert item["approval_validity_days"] == 90

    def test_patch_increments_version(self, api):
        """PRD §3.1: "Updates to a ServiceCatalogItem apply only to
        future submissions; in-flight authorizations retain the values
        captured by service_catalog_item_version".
        PRD §2.4: "version (integer): a system-managed counter that
        starts at 1 on creation and increments by one on every
        mutation."

        Claim: PATCH increments version.
        """
        item = create_service_catalog_item()
        assert item["version"] == 1
        updated = patch_service_catalog_item(
            item=item, name="Renamed Service",
        )
        assert updated["version"] == 2
        assert updated["name"] == "Renamed Service"

    def test_retire_catalog_item(self, api):
        """PRD §3.1: "an admin may retire a catalog item by moving its
        status to RETIRED."

        Claim: status=RETIRED is reachable via PATCH.
        """
        item = create_service_catalog_item()
        retired = retire_service_catalog_item(item)
        assert retired["status"] == "RETIRED"
