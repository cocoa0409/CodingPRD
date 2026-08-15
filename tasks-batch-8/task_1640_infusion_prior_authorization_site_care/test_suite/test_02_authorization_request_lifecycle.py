"""Authorization request lifecycle: drafting, submission gates, determinations
with OCC, the pend/resubmit cycle, validity-window computation, and expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_criteria_submission,
    advance_clock,
    assert_authorization_request,
    assert_timestamp_equals,
    create_auth_request_payload,
    create_draft_request,
    create_patient,
    create_policy,
    determination_payload,
    get_request,
    record_determination,
    review_criteria_submission,
    setup_approved_request,
    setup_submittable_request,
    setup_submitted_request,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
    AUTH_COORDINATOR_HEADERS,
    MEDICAL_DIRECTOR_2_HEADERS,
    make_medical_director_headers,
)


class TestDraftCreation:
    def test_new_request_is_born_draft(self, api):
        """PRD §3.2: "The new request is born in `DRAFT` status with the
        creating operator recorded in `created_by_user_id`."

        Design: Corner/state_machines/auth_request_initial_state_draft
        """
        policy = create_policy(drug_code="J9110", regimen_name="Init")
        patient = create_patient(member_id="M1110", full_name="Init P")
        auth = validate_success(api.create_authorization_request(
            create_auth_request_payload(
                patient["id"], policy["id"],
                requested_site_type="HOME", requested_dose_mg=250,
                patient_weight_kg=80),
            AUTH_COORDINATOR_HEADERS), 201)
        assert_authorization_request(auth)
        assert auth["status"] == "DRAFT", "A new request is born DRAFT"
        assert auth.get("auth_valid_from") is None, (
            "No validity window exists before approval")
        assert auth.get("auth_valid_to") is None

    def test_injected_system_fields_are_ignored(self, api):
        """PRD §3.2: "The new request is born in `DRAFT` status with the
        creating operator recorded in `created_by_user_id`."

        Design: Corner/entities/auth_request_create_system_fields_input_ignored
        """
        policy = create_policy(drug_code="J9101", regimen_name="SysF")
        patient = create_patient(member_id="M1101", full_name="Sys P")
        payload = create_auth_request_payload(patient["id"], policy["id"])
        payload["status"] = "APPROVED"
        payload["version"] = 99
        payload["created_by_user_id"] = "spoofed-user"
        auth = validate_success(
            api.create_authorization_request(payload, AUTH_COORDINATOR_HEADERS),
            201)
        assert auth["status"] == "DRAFT", "Injected APPROVED status is ignored"
        assert auth["created_by_user_id"] == "coord-1", (
            "created_by_user_id is stamped from X-User-ID, not from the body")

    def test_get_unknown_request_returns_not_found(self, api):
        """PRD §2.9: "the first missing reference yields that resource's
        dedicated 404: `ERR_PATIENT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
        `ERR_AUTH_REQUEST_NOT_FOUND`, `ERR_CRITERIA_SUBMISSION_NOT_FOUND`,
        `ERR_APPEAL_NOT_FOUND`, `ERR_P2P_NOT_FOUND`,
        `ERR_BENEFIT_INVESTIGATION_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`,
        `ERR_LINE_ITEM_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_DOSE_CHANGE_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_auth_request_returns_not_found
        """
        resp = api.get_authorization_request(
            NON_EXISTENT_UUID, AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUEST_NOT_FOUND)

    def test_dose_above_ceiling_rejected_at_create(self, api):
        """PRD §3.2: "A dose above the policy's `max_dose_mg` ceiling is
        rejected on the spot with `ERR_DOSE_EXCEEDS_MAX` (422)."

        Design: Corner/validations/dose_exceeds_max_at_create_rejected
        """
        policy = create_policy(drug_code="J9142", regimen_name="Safety")
        patient = create_patient(member_id="M1142", full_name="DS P")

        over = api.create_authorization_request(
            create_auth_request_payload(patient["id"], policy["id"],
                                        requested_dose_mg=1500),
            AUTH_COORDINATOR_HEADERS)
        validate_error(over, ApiErrorId.ERR_DOSE_EXCEEDS_MAX)

        at_max = validate_success(api.create_authorization_request(
            create_auth_request_payload(patient["id"], policy["id"],
                                        requested_dose_mg=1000),
            AUTH_COORDINATOR_HEADERS), 201)
        assert at_max["requested_dose_mg"] == 1000, (
            "A dose exactly equal to max_dose_mg passes (the ceiling rejects "
            "only doses above it)")


class TestDeterminations:
    def test_determination_on_draft_rejected(self, api):
        """PRD §3.4: "Once `SUBMITTED`, a `MedicalDirector` records a
        determination whose `outcome` is `APPROVED`, `DENIED`, or `PENDED`"
        PRD §2.9: "**State preconditions and cross-entity state gates** — the
        parent-approval gate surfaces as `ERR_AUTH_NOT_APPROVED` (409) on
        appointment booking, dose-change creation, clearance creation, and
        clearance recompute; every other from-state violation, including any
        write aimed at a resource in a terminal state, surfaces as
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/determinations_on_draft_rejected
        """
        policy = create_policy(drug_code="J9111", regimen_name="InvTr")
        patient = create_patient(member_id="M1111", full_name="IT P")
        auth = create_draft_request(patient["id"], policy["id"])

        resp = api.record_determination(
            auth["id"], determination_payload("APPROVED", auth["version"]),
            MEDICAL_DIRECTOR_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_request(auth["id"])
        assert after["status"] == "DRAFT", "The request remains DRAFT"

    def test_determination_on_unknown_request_returns_404(self, api):
        """PRD §2.9: "**Resource existence** — path- and body-referenced
        resources are resolved left to right (patient, policy, authorization
        request, appeal, criteria submission, clearance, line item, chair,
        appointment, dose-change request, benefit investigation, peer-to-peer
        review), and the first missing reference yields that resource's
        dedicated 404: `ERR_PATIENT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
        `ERR_AUTH_REQUEST_NOT_FOUND`, `ERR_CRITERIA_SUBMISSION_NOT_FOUND`,
        `ERR_APPEAL_NOT_FOUND`, `ERR_P2P_NOT_FOUND`,
        `ERR_BENEFIT_INVESTIGATION_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`,
        `ERR_LINE_ITEM_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_DOSE_CHANGE_NOT_FOUND`."

        Design: Corner/validations/determinations_on_missing_auth_returns_404
        """
        policy = create_policy(drug_code="J9131", regimen_name="NF")
        patient = create_patient(member_id="M1131", full_name="NF P")
        auth = create_draft_request(patient["id"], policy["id"])

        resp = api.record_determination(
            NON_EXISTENT_UUID,
            determination_payload("APPROVED", auth["version"]),
            MEDICAL_DIRECTOR_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUEST_NOT_FOUND)

    def test_coordinator_cannot_record_determination(self, api):
        """PRD §2.1: "A well-formed request whose role is not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: POST /infusion/authorization-requests/{id}/determinations is
        authorized for MedicalDirector only.

        Design: Corner/rbac/coordinator_cannot_record_determination
        """
        ws = setup_submitted_request(drug_code="J9170", member_id="M1170")
        resp = api.record_determination(
            ws["auth"]["id"],
            determination_payload("APPROVED", ws["auth"]["version"]),
            {"X-User-ID": "coord-9", "X-User-Role": "AuthCoordinator",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        after = get_request(ws["auth"]["id"])
        assert after["status"] == "SUBMITTED"

    def test_decider_who_created_request_violates_segregation(self, api):
        """PRD §2.8: "First, the `MedicalDirector` recording a determination on
        an authorization request must not be the operator recorded as that
        request's `created_by_user_id`."
        PRD §2.8: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403), and the check applies to exactly three capabilities:
        recording a determination, reviewing a criteria submission, and clearing
        a financial clearance."

        Design: Corner/validations/sod_determination_same_user_rejected
        """
        ws = setup_submitted_request(drug_code="J9153", member_id="M1153")
        assert ws["auth"]["created_by_user_id"] == "coord-1"

        resp = api.record_determination(
            ws["auth"]["id"],
            determination_payload("APPROVED", ws["auth"]["version"]),
            make_medical_director_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = get_request(ws["auth"]["id"])
        assert after["status"] == "SUBMITTED"


class TestOptimisticConcurrency:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.7: "The request body must carry
        `expected_authorization_version`, a non-optional field holding the
        client's last observed `version` of the authorization request. If the
        request's current `version` has advanced beyond that value — because
        another writer has already recorded a determination, or the coordinator
        has resubmitted the request — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from deciding a
        request it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_determination
        """
        ws = setup_submitted_request(drug_code="J9180", member_id="M1180")
        current_version = ws["auth"]["version"]

        resp = api.record_determination(
            ws["auth"]["id"],
            determination_payload("APPROVED", current_version - 1),
            MEDICAL_DIRECTOR_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = get_request(ws["auth"]["id"])
        assert after["status"] == "SUBMITTED"
        assert after["version"] == current_version, (
            "A rejected determination leaves the version untouched")

    def test_current_version_determination_increments_by_one(self, api):
        """PRD §3.4: "All three outcomes record the decider in
        `decided_by_user_id` and increment `version` by one."

        Design: Corner/cross_cutting_layers/occ_success_increments_version
        """
        ws = setup_submitted_request(drug_code="J9181", member_id="M1181")
        observed = ws["auth"]["version"]

        decided = validate_success(api.record_determination(
            ws["auth"]["id"], determination_payload("APPROVED", observed),
            MEDICAL_DIRECTOR_2_HEADERS))
        assert decided["status"] == "APPROVED"
        assert decided["version"] == observed + 1, (
            f"version must increment by exactly one: {observed} -> "
            f"{decided['version']}")
        assert decided["decided_by_user_id"] == "md-2"


class TestValidityWindow:
    def test_course_cap_and_validity_days_alternately_bind(self, api):
        """PRD §3.4: "The `auth_valid_from` bound is the decision date
        truncated to midnight — 00:00:00Z of that day."
        PRD §3.4: "The `auth_valid_to` bound is the earliest of three instants:
        `auth_valid_from` plus the base length in days, the patient's
        `plan_year_end`, and `auth_valid_from` plus the policy's
        `max_course_days` in days."

        Design: Difficulty/combinatorial_formula/validity_window_nested_min_three_dates
        """
        # W1: validity 90 / course 60 — the course cap binds.
        ws1 = setup_approved_request(
            drug_code="J9011", member_id="M301",
            policy_overrides={"regimen_name": "W1", "validity_days": 90,
                              "max_course_days": 60})
        assert_timestamp_equals(
            ws1["auth"]["auth_valid_from"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(
            ws1["auth"]["auth_valid_to"], "2026-09-30T00:00:00Z")
        # W2: validity 30 / course 60 — the validity-days input binds.
        ws2 = setup_approved_request(
            drug_code="J9012", member_id="M302",
            policy_overrides={"regimen_name": "W2", "validity_days": 30,
                              "max_course_days": 60})
        assert_timestamp_equals(
            ws2["auth"]["auth_valid_from"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(
            ws2["auth"]["auth_valid_to"], "2026-08-31T00:00:00Z")

    def test_plan_year_end_binds_and_decision_date_truncates(self, api):
        """PRD §3.4: "The `auth_valid_from` bound is the decision date
        truncated to midnight — 00:00:00Z of that day."
        PRD §3.4: "The `auth_valid_to` bound is the earliest of three instants:
        `auth_valid_from` plus the base length in days, the patient's
        `plan_year_end`, and `auth_valid_from` plus the policy's
        `max_course_days` in days."

        Design: Difficulty/combinatorial_formula/validity_window_nested_min_three_dates
        """
        ws = setup_submitted_request(
            drug_code="J9013", member_id="M303",
            policy_overrides={"validity_days": 90, "max_course_days": 60},
            patient_overrides={"plan_year_end": "2026-09-10T00:00:00Z"})
        advance_clock("2026-08-05T15:30:00Z")
        approved = record_determination(
            ws["auth"]["id"], "APPROVED", ws["auth"]["version"])
        assert_timestamp_equals(
            approved["auth_valid_from"], "2026-08-05T00:00:00Z")
        # min(+90d 2026-11-03, plan_year_end 2026-09-10, +60d 2026-10-04)
        assert_timestamp_equals(
            approved["auth_valid_to"], "2026-09-10T00:00:00Z")

    def test_pharmacy_channel_uses_pharmacy_validity_days(self, api):
        """PRD §3.4: "The window's base length is the policy's `validity_days`,
        or its `pharmacy_validity_days` when the policy's `benefit_channel` is
        `PHARMACY`."
        PRD §3.3: "Successful verification stamps `VERIFIED` (a terminal state),
        derives the `routing` as `BUY_AND_BILL` for a medical channel or
        `SPECIALTY_PHARMACY` for a pharmacy channel, and records the specialist
        in `verified_by_user_id`."

        Design: Corner/calculations/validity_window_pharmacy_channel_branch
        """
        ws = setup_approved_request(
            drug_code="J9122", member_id="M1122",
            policy_overrides={"benefit_channel": "PHARMACY",
                              "validity_days": 90,
                              "pharmacy_validity_days": 30,
                              "max_course_days": 60},
            request_overrides={"requested_site_type": "HOME"},
            verify_channel="PHARMACY")
        assert ws["benefit"]["routing"] == "SPECIALTY_PHARMACY"
        assert ws["benefit"]["status"] == "VERIFIED"
        # min(+30d 2026-08-31, plan_year_end 2026-12-31, +60d 2026-09-30)
        assert_timestamp_equals(
            ws["auth"]["auth_valid_to"], "2026-08-31T00:00:00Z")


class TestPendResubmitCycle:
    def test_pend_then_fresh_criteria_then_approval(self, api):
        """PRD §3.4: "A pend stamps `pended_at` and returns the request to the
        coordinator for more evidence."
        PRD §3.4: "Resubmitting a `PENDED` request carries one decisive gate:
        at least one `ACCEPTED` criteria submission created after `pended_at` —
        stale acceptances from before the pend do not count, and without a fresh
        one the resubmission is rejected with `ERR_MISSING_REQUIRED_CRITERIA`.
        A successful resubmission re-stamps `submitted_at` and increments
        `version`."

        Design: Difficulty/non_linear_state_machine/auth_pend_resubmit_cycle
        """
        ws = setup_submitted_request(drug_code="J9021", member_id="M401")
        v_submitted = ws["auth"]["version"]

        pended = record_determination(
            ws["auth"]["id"], "PENDED", v_submitted)
        assert pended["status"] == "PENDED"
        assert pended["version"] > v_submitted

        # A fresh criterion created strictly after pended_at.
        advance_clock("2026-08-01T00:00:01Z")
        fresh = add_criteria_submission(
            ws["auth"]["id"], "PRIOR_THERAPY_FAIL", "methotrexate-12wk")
        review_criteria_submission(fresh["id"], "ACCEPTED")

        resubmitted = submit_request(ws["auth"]["id"])
        assert resubmitted["status"] == "SUBMITTED", (
            "The PENDED request cycles back to SUBMITTED")
        assert resubmitted["version"] > pended["version"], (
            "Versions advance strictly across the cycle")

        approved = record_determination(
            ws["auth"]["id"], "APPROVED", resubmitted["version"])
        assert approved["status"] == "APPROVED"
        assert_timestamp_equals(
            approved["auth_valid_from"], "2026-08-01T00:00:00Z")

    def test_resubmit_without_fresh_criteria_rejected(self, api):
        """PRD §3.4: "Resubmitting a `PENDED` request carries one decisive
        gate: at least one `ACCEPTED` criteria submission created after
        `pended_at` — stale acceptances from before the pend do not count, and
        without a fresh one the resubmission is rejected with
        `ERR_MISSING_REQUIRED_CRITERIA`."

        Design: Difficulty/non_linear_state_machine/auth_pend_resubmit_cycle
        """
        ws = setup_submitted_request(drug_code="J9021", member_id="M402")
        pended = record_determination(
            ws["auth"]["id"], "PENDED", ws["auth"]["version"])
        assert pended["status"] == "PENDED"

        resp = api.submit_authorization_request(
            ws["auth"]["id"], AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_CRITERIA)

        after = get_request(ws["auth"]["id"])
        assert after["status"] == "PENDED", (
            "The stale pre-pend acceptance does not satisfy resubmission")


class TestExpiryLockdown:
    def test_expired_request_rejects_further_writes(self, api):
        """PRD §3.4: "When the logical clock advances past `auth_valid_to`, an
        `APPROVED` request becomes `EXPIRED`, incrementing `version`."
        PRD §3.4: "The `SUPERSEDED` and `DENIED_CLOSED` terminals arrive by
        cascade — through dose-change approval (§3.8) and appeal resolution
        (§3.5) respectively — and `SUPERSEDED`, `EXPIRED`, and `DENIED_CLOSED`
        are terminal: any further write against a request in one of those
        states is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/expired_auth_terminal_lockdown
        """
        ws = setup_approved_request(
            drug_code="J9112", member_id="M1112",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        assert_timestamp_equals(
            ws["auth"]["auth_valid_to"], "2026-08-31T00:00:00Z")

        advance_clock("2026-09-01T00:00:00Z")
        expired = get_request(ws["auth"]["id"])
        assert expired["status"] == "EXPIRED", (
            "Clock past auth_valid_to drives APPROVED -> EXPIRED")

        resp = api.record_determination(
            ws["auth"]["id"],
            determination_payload("APPROVED", expired["version"]),
            MEDICAL_DIRECTOR_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRequestListing:
    def test_list_pagination_defaults_and_patient_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of
        100. The `offset` parameter states how many items to skip and defaults
        to 0."
        PRD §3.2: "The request collection supports filtering by `patient_id`,
        `policy_id`, `status`, and `supersedes_request_id`, alongside the
        standard `limit` and `offset` pagination parameters."

        Design: Corner/endpoints/list_authorization_requests_pagination_defaults
        """
        policy = create_policy(drug_code="J9160", regimen_name="List")
        pat_a = create_patient(member_id="M1160", full_name="List A")
        pat_b = create_patient(member_id="M1161", full_name="List B")
        create_draft_request(pat_a["id"], policy["id"],
                             requested_site_type="OFFICE", requested_dose_mg=400,
                             patient_weight_kg=60)
        create_draft_request(pat_b["id"], policy["id"],
                             requested_site_type="HOME", requested_dose_mg=600,
                             patient_weight_kg=80)

        data, meta = validate_paginated(
            api.list_authorization_requests(AUTH_COORDINATOR_HEADERS))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "The default limit is 10"
        assert meta["offset"] == 0
        assert len(data) == 2

        filtered, meta_f = validate_paginated(api.list_authorization_requests(
            AUTH_COORDINATOR_HEADERS, params={"patient_id": pat_a["id"]}))
        assert meta_f["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["patient_id"] == pat_a["id"]
