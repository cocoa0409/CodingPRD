"""Entity CRUD, FK/listing, computed-read, and RBAC tests.

Translates queue B (Corner): entities, endpoints, and rbac sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, MISSING_UUID,
    make_orthodontist_headers, make_guardian_headers,
    assert_family_account, assert_patient, assert_chair,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F


# =============================================================================
# Corner / entities
# =============================================================================

class TestEntityCreation:

    def test_create_family_account_defaults(self, api):
        """PRD 3.1: "At creation the family's computed discount_tier_pct and
        active_plan_count both start at zero"
        PRD 2.4: "an integer version that begins at 1 and increments by one with
        every mutation to the resource"

        Design: Corner/entities/create_family_account_returns_201_with_defaults
        """
        resp = api.create_family_account(
            F.create_family_account_payload(family_name="Abel",
                                            billing_email="abel@x.com",
                                            guardian_user_id="g-abel"),
            TEST_USERS["frontdesk_headers"])
        fam = validate_success(resp, expected_status=201)
        assert_family_account(fam)
        assert fam["discount_tier_pct"] == 0
        assert fam["active_plan_count"] == 0
        assert fam["version"] == 1

    def test_create_patient_records_incomplete(self, api):
        """PRD 3.1: "A patient also carries a computed records_complete flag,
        which starts false and becomes true only once the patient has the
        required growth films on file"

        Design: Corner/entities/create_patient_returns_201_records_incomplete
        """
        family = fx.create_family()
        resp = api.create_patient(
            F.create_patient_payload(family["id"], full_name="Cy Boe"),
            TEST_USERS["frontdesk_headers"])
        patient = validate_success(resp, expected_status=201)
        assert_patient(patient)
        assert patient["records_complete"] is False

    def test_get_patient_not_found(self, api):
        """PRD 2.8: "Any path identifier or foreign-key reference in the body that
        does not resolve to an existing resource causes the request to be rejected
        with ERR_NOT_FOUND (HTTP 404)"

        Design: Corner/entities/get_patient_not_found_returns_404
        """
        resp = api.get_patient(MISSING_UUID, TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_patient_missing_required_field_invalid_request(self, api):
        """PRD 2.10: "required fields present, enum values legal, an appointment's
        end strictly after its start, a contract term of at least one month, and
        all supplied amounts non-negative (ERR_INVALID_REQUEST)"

        Design: Corner/entities/create_patient_missing_required_field_returns_invalid_request
        """
        family = fx.create_family()
        # Omit full_name (required).
        resp = api.create_patient(
            {"family_account_id": family["id"],
             "date_of_birth": "2012-01-01T00:00:00Z", "is_minor": True},
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_chair_default_turnover_buffer(self, api):
        """PRD 3.1: "an integer turnover_buffer_minutes that defaults to 10 and
        reserves cleanup time after each appointment in that chair before it is
        free again, and an active flag defaulting to true"

        Design: Corner/entities/create_chair_default_turnover_buffer_applied
        """
        resp = api.create_chair({"label": "CX"}, TEST_USERS["admin_headers"])
        chair = validate_success(resp, expected_status=201)
        assert_chair(chair)
        assert chair["turnover_buffer_minutes"] == 10
        assert chair["active"] is True

    def test_records_complete_after_pano_and_ceph_finalized(self, api):
        """PRD 3.2: "the patient's records_complete flag is recomputed: it is true
        exactly when the patient now holds one FINALIZED PANO and one FINALIZED
        CEPH, and false otherwise"

        Design: Corner/entities/patient_records_complete_becomes_true_after_pano_and_ceph_finalized
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        pano = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "PANO", taken_at="2026-01-01T00:00:00Z"), ortho))
        validate_success(api.finalize_growth_record(pano["id"], ortho))
        # Only PANO finalized so far -> still incomplete.
        mid = validate_success(api.get_patient(patient["id"], TEST_USERS["frontdesk_headers"]))
        assert mid["records_complete"] is False

        ceph = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "CEPH", taken_at="2026-01-01T00:00:00Z"), ortho))
        validate_success(api.finalize_growth_record(ceph["id"], ortho))
        final = validate_success(api.get_patient(patient["id"], TEST_USERS["frontdesk_headers"]))
        assert final["records_complete"] is True

    def test_list_patients_filtered_by_family_envelope(self, api):
        """PRD 2.3: "List responses always include limit, offset, total_count, and
        has_more inside the meta object of the envelope"
        PRD 3.1: "Patients can be listed and optionally narrowed to one family"

        Design: Corner/entities/list_patients_filtered_by_family_pagination_envelope
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        data, meta = validate_paginated(api.list_patients(
            TEST_USERS["frontdesk_headers"], params={"family_account_id": family["id"]}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert data[0]["id"] == patient["id"]

    def test_growth_records_reverse_reachable_by_patient(self, api):
        """PRD 3.2: "A new record begins in DRAFT and may be listed or fetched,
        optionally filtered by patient"

        Design: Corner/entities/growth_record_fk_reverse_reachable_by_patient_filter
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        ortho = make_orthodontist_headers(puid)
        gr = get_success_data(api.create_growth_record(
            F.create_growth_record_payload(patient["id"], "PANO", taken_at="2026-01-01T00:00:00Z"), ortho))
        data, meta = validate_paginated(api.list_growth_records(
            ortho, params={"patient_id": patient["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == gr["id"]

    def test_create_patient_wrong_family_fk_not_found(self, api):
        """PRD 2.8: "Any path identifier or foreign-key reference in the body that
        does not resolve to an existing resource causes the request to be rejected
        with ERR_NOT_FOUND (HTTP 404)"

        Design: Corner/entities/create_patient_wrong_family_fk_returns_not_found
        """
        resp = api.create_patient(
            F.create_patient_payload(MISSING_UUID, full_name="Ka"),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# =============================================================================
# Corner / endpoints
# =============================================================================

class TestComputedRead:

    def test_get_treatment_plan_returns_pinned_fees(self, api):
        """PRD 3.3: "Plans can be fetched with their computed fees and listed,
        optionally filtered by patient or by policy"
        PRD 3.5: "net_fee_cents is the gross fee minus that applied discount"

        Design: Corner/endpoints/get_treatment_plan_computed_read_returns_pinned_fees
        """
        ctx = fx.setup_active_plan([100000], modality="BRACES", set_clock_to="2026-01-01T00:00:00Z")
        plan = validate_success(api.get_treatment_plan(
            ctx["plan"]["id"], TEST_USERS["billing_headers"]))
        assert plan["gross_fee_cents"] == 100000
        assert plan["net_fee_cents"] == 100000
        assert plan["estimated_patient_responsibility_cents"] == 100000


# =============================================================================
# Corner / rbac
# =============================================================================

class TestRbac:

    def test_frontdesk_cannot_create_treatment_plan(self, api):
        """PRD 2.1: "When the headers are valid but the role is not permitted to
        perform the requested operation"
        PRD 2.1: "the request is rejected with ERR_FORBIDDEN (HTTP 403)"

        Design: Corner/rbac/frontdesk_cannot_create_treatment_plan_forbidden
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        resp = api.create_treatment_plan(
            F.create_treatment_plan_payload(patient["id"], modality="BRACES"),
            TEST_USERS["frontdesk_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_guardian_cannot_approve_insurance_claim(self, api):
        """PRD 2.1: "When the headers are valid but the role is not permitted to
        perform the requested operation"
        PRD 2.1: "the request is rejected with ERR_FORBIDDEN (HTTP 403)"

        Design: Corner/rbac/guardian_cannot_approve_insurance_claim_forbidden
        """
        family = fx.create_family()
        patient = fx.create_patient(family["id"])
        _prov, puid = fx.create_provider()
        policy = fx.create_policy(patient["id"], ortho_rider=True,
                                  ortho_coverage_pct=0.50, lifetime_max_cents=200000)
        plan = fx.create_plan_with_phases(patient["id"], puid, [100000],
                                          modality="BRACES", policy_id=policy["id"])
        claim = fx.submit_claim(policy["id"], plan["id"], 50000)
        resp = api.approve_insurance_claim(
            claim["id"], make_guardian_headers(family["guardian_user_id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_guardian_cannot_activate_other_familys_plan(self, api):
        """PRD 2.1: "When X-User-Role is Guardian, X-User-ID is the
        guardian_user_id stamped on the owning FamilyAccount; ownership checks on
        any resource that traces back to a FamilyAccount compare that account's
        guardian_user_id to X-User-ID"

        Design: Corner/rbac/guardian_cannot_activate_other_familys_plan_forbidden
        """
        ctx = fx.setup_proposed_plan([100000], records_complete=True,
                                     guardian_user_id="g-own")
        # A different guardian id attempts the activation.
        resp = api.activate_treatment_plan(
            ctx["plan"]["id"], make_guardian_headers("g-other"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing, or X-User-Role is not one of the
        recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP
        401)"

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_family_account(
            F.create_family_account_payload(family_name="NoAuth",
                                            billing_email="na@x.com",
                                            guardian_user_id="g-na"),
            {})  # no X-User-ID / X-User-Role
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_orthodontist_cannot_create_chair(self, api):
        """PRD 2.1: "When the headers are valid but the role is not permitted to
        perform the requested operation"
        PRD 2.1: "the request is rejected with ERR_FORBIDDEN (HTTP 403)"

        Design: Corner/rbac/orthodontist_cannot_create_chair_forbidden
        """
        _prov, puid = fx.create_provider()
        resp = api.create_chair(
            F.create_chair_payload(label="CE1", turnover_buffer_minutes=10),
            make_orthodontist_headers(puid))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
