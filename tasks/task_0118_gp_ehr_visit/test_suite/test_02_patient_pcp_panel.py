"""Patient CRUD, PCP binding rules, and Provider.panel_size invariants.

PRD §3.1 (patient and PCP binding), §3.2 (provider role types).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    create_patient,
    create_patient_payload,
    create_pcp_provider,
    create_provider,
    create_specialist_provider,
    bind_patient_to_pcp,
    bind_pcp_payload,
    patch_patient_payload,
    re_get_provider,
    re_get_patient,
    setup_panel_with_n_active_patients,
    setup_patient_with_pcp,
    TEST_USERS,
    unbind_patient_pcp,
    validate_error,
    validate_success,
)


# ===========================================================================
# Patient creation — PRD §3.1
# ===========================================================================
class TestPatientCreation:

    def test_patient_initial_pcp_and_status_defaults(
        self, api, receptionist_headers,
    ):
        """PRD §3.1: "The server initializes the patient's
        pcp_provider_id to null, leaves pcp_bound_at null, and sets
        status to ACTIVE."

        Claim: a freshly-created patient has pcp_provider_id=null,
        pcp_bound_at=null, status=ACTIVE.
        """
        res = api.create_patient(
            create_patient_payload(), receptionist_headers,
        )
        patient = validate_success(res, expected_status=201)
        assert patient["pcp_provider_id"] is None
        assert patient.get("pcp_bound_at") is None
        assert patient["status"] == "ACTIVE"

    def test_patient_default_smoking_status_unknown(
        self, api, receptionist_headers,
    ):
        """PRD §3.1: "smoking_status (one of NEVER, FORMER, CURRENT,
        or UNKNOWN, defaulting to UNKNOWN)".

        Claim: omitting smoking_status defaults to UNKNOWN.
        """
        payload = create_patient_payload()
        payload.pop("smoking_status", None)
        res = api.create_patient(payload, receptionist_headers)
        patient = validate_success(res, expected_status=201)
        assert patient["smoking_status"] == "UNKNOWN"

    def test_patient_default_portal_disabled(
        self, api, receptionist_headers,
    ):
        """PRD §3.1: "portal_enabled (a boolean defaulting to false)".

        Claim: omitting portal_enabled defaults to false.
        """
        payload = create_patient_payload()
        payload.pop("portal_enabled", None)
        res = api.create_patient(payload, receptionist_headers)
        patient = validate_success(res, expected_status=201)
        assert patient["portal_enabled"] is False

    def test_patient_default_chronic_conditions_empty(
        self, api, receptionist_headers,
    ):
        """PRD §3.1: "chronic_conditions (an array of ICD-10 code
        strings such as E11.9 or I10, defaulting to the empty array)".

        Claim: omitting chronic_conditions defaults to [].
        """
        payload = create_patient_payload()
        payload.pop("chronic_conditions", None)
        res = api.create_patient(payload, receptionist_headers)
        patient = validate_success(res, expected_status=201)
        assert patient["chronic_conditions"] == []


# ===========================================================================
# PCP binding — PRD §3.1
# ===========================================================================
class TestBindPcp:

    def test_bind_to_specialist_only_rejected(
        self, api, receptionist_headers,
    ):
        """PRD §3.1: "The target provider must have role_type of
        either PCP_ONLY or BOTH; a SPECIALIST_ONLY provider cannot
        serve as PCP and the request is rejected with
        ERR_PROVIDER_NOT_PCP."

        Claim: binding to a SPECIALIST_ONLY provider returns
        ERR_PROVIDER_NOT_PCP.
        """
        specialist = create_specialist_provider()
        patient = create_patient()
        res = api.bind_pcp(
            patient["id"],
            bind_pcp_payload(provider_id=specialist["id"]),
            receptionist_headers,
        )
        validate_error(res, "ERR_PROVIDER_NOT_PCP")

    def test_bind_to_both_role_succeeds(self, api, receptionist_headers):
        """PRD §3.1: "The target provider must have role_type of
        either PCP_ONLY or BOTH; a SPECIALIST_ONLY provider cannot
        serve as PCP and the request is rejected with
        ERR_PROVIDER_NOT_PCP."

        Claim: binding to a BOTH provider succeeds (negation of the
        previous test on the BOTH branch).
        """
        from test_helpers import create_both_role_provider
        both = create_both_role_provider()
        patient = create_patient()
        res = api.bind_pcp(
            patient["id"],
            bind_pcp_payload(provider_id=both["id"]),
            receptionist_headers,
        )
        patient = validate_success(res, expected_status=200)
        assert patient["pcp_provider_id"] == both["id"]

    def test_double_bind_rejected(self, api, receptionist_headers):
        """PRD §3.1: "The patient must not already have a non-null
        pcp_provider_id. If they do, the request is rejected with
        ERR_PCP_ALREADY_BOUND."

        Claim: binding the same patient a second time returns
        ERR_PCP_ALREADY_BOUND.
        """
        patient, _ = setup_patient_with_pcp()
        # Create a second eligible PCP, attempt to bind again.
        provider2 = create_pcp_provider()
        res = api.bind_pcp(
            patient["id"],
            bind_pcp_payload(provider_id=provider2["id"]),
            receptionist_headers,
        )
        validate_error(res, "ERR_PCP_ALREADY_BOUND")

    def test_bind_stamps_pcp_bound_at(self, api, receptionist_headers):
        """PRD §3.1: "Binding by a Receptionist or ClinicAdmin
        supplies a provider_id and writes it to the patient's
        pcp_provider_id, stamping pcp_bound_at with the current
        server time."

        Claim: on bind, pcp_bound_at is set to a non-null timestamp.
        """
        provider = create_pcp_provider()
        patient = create_patient()
        res = api.bind_pcp(
            patient["id"],
            bind_pcp_payload(provider_id=provider["id"]),
            receptionist_headers,
        )
        patient = validate_success(res, expected_status=200)
        assert patient["pcp_provider_id"] == provider["id"]
        assert patient["pcp_bound_at"] is not None

    def test_panel_full_rejected_at_cap(self, api, receptionist_headers):
        """PRD §3.1: "the provider's current panel_size plus one must
        be less than or equal to their panel_cap (which defaults to
        2000 when not supplied at provider creation). The panel-cap
        check is enforced only when the provider's role_type is
        PCP_ONLY or BOTH. A bind that would exceed the cap is
        rejected with ERR_PANEL_FULL."

        Claim: a provider with panel_cap=1 and one already-bound
        patient rejects a second bind with ERR_PANEL_FULL.
        """
        setup = setup_panel_with_n_active_patients(n=1, panel_cap=1)
        provider = setup["provider"]
        # Try to bind a second patient — should hit the cap.
        new_patient = create_patient()
        res = api.bind_pcp(
            new_patient["id"],
            bind_pcp_payload(provider_id=provider["id"]),
            receptionist_headers,
        )
        validate_error(res, "ERR_PANEL_FULL")


# ===========================================================================
# Provider.panel_size invariant — PRD §3.1
# ===========================================================================
class TestPanelSizeInvariant:

    # difficulty: compensating_invariant/pcp_bind_unbind_panel_size_invariant
    def test_bind_then_unbind_restores_panel_size(self, api):
        """PRD §3.1: "The panel_size on a Provider is a derived count:
        the number of Patient rows whose pcp_provider_id equals that
        provider's id and whose status equals ACTIVE. It is recomputed
        by the server on every successful bind, on every unbind, and
        whenever a patient's status transitions between ACTIVE and
        INACTIVE."

        Claim: bind + unbind on a single patient leaves
        Provider.panel_size at its pre-bind value (3 in this fixture).
        """
        setup = setup_panel_with_n_active_patients(n=3)
        provider = setup["provider"]
        size_before = re_get_provider(provider["id"])["panel_size"]
        assert size_before == 3, (
            f"Pre-bind panel_size expected 3, got {size_before}"
        )
        new_patient = create_patient()
        # Bind P_NEW.
        bind_patient_to_pcp(new_patient["id"], provider["id"])
        size_mid = re_get_provider(provider["id"])["panel_size"]
        assert size_mid == 4, (
            f"After bind panel_size expected 4, got {size_mid}"
        )
        # Unbind P_NEW.
        unbind_patient_pcp(new_patient["id"])
        size_after = re_get_provider(provider["id"])["panel_size"]
        assert size_after == 3, (
            f"After unbind panel_size expected 3, got {size_after}"
        )

    # difficulty: compensating_invariant/pcp_bind_unbind_panel_size_invariant
    def test_panel_size_starts_at_zero_for_fresh_provider(self, api):
        """PRD §3.1: "The panel_size on a Provider is a derived count:
        the number of Patient rows whose pcp_provider_id equals that
        provider's id and whose status equals ACTIVE."

        PRD §3.2: "panel_size is server-computed and starts at zero."

        Claim: a freshly-created Provider has panel_size == 0; after a
        single successful bind, panel_size == 1 (the count formula).
        """
        provider = create_pcp_provider()
        assert provider["panel_size"] == 0, (
            f"New Provider.panel_size expected 0, got {provider['panel_size']}"
        )
        patient = create_patient()
        bind_patient_to_pcp(patient["id"], provider["id"])
        assert re_get_provider(provider["id"])["panel_size"] == 1


# ===========================================================================
# Patient PATCH — PRD §3.1
# ===========================================================================
class TestPatientPatch:

    def test_patch_smoking_status_succeeds(self, api):
        """PRD §3.1: "smoking_status, chronic_conditions, and
        portal_enabled may be revised through the patient PATCH
        operation (which also accepts an optional version for OCC)."

        Claim: PATCH updating smoking_status returns the new value.
        """
        patient = create_patient(smoking_status="CURRENT")
        res = api.patch_patient(
            patient["id"],
            patch_patient_payload(smoking_status="FORMER"),
            TEST_USERS["nurse_headers"],
        )
        patient = validate_success(res, expected_status=200)
        assert patient["smoking_status"] == "FORMER"

    def test_patch_chronic_conditions_succeeds(self, api):
        """PRD §3.1: "smoking_status, chronic_conditions, and
        portal_enabled may be revised through the patient PATCH
        operation (which also accepts an optional version for OCC)."

        Claim: PATCH updating chronic_conditions returns the new
        array.
        """
        patient = create_patient(chronic_conditions=[])
        res = api.patch_patient(
            patient["id"],
            patch_patient_payload(chronic_conditions=["I10", "E11.9"]),
            TEST_USERS["nurse_headers"],
        )
        patient = validate_success(res, expected_status=200)
        assert patient["chronic_conditions"] == ["I10", "E11.9"]
