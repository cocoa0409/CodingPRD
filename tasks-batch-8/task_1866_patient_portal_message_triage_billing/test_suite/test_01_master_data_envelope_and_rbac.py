"""Master data defaults, response envelope, and role-based access control."""
from test_helpers import (
    ApiErrorId,
    LOGICAL_CLOCK_STARTUP_DEFAULT,
    MISSING_UUID,
    Scenario,
    assert_patient,
    assert_portal_message,
    assert_same_instant,
    create_patient_payload,
    create_portal_message_payload,
    make_billing_specialist_headers,
    make_patient_headers,
    make_provider_headers,
    make_triage_nurse_headers,
    triage_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPatientMasterData:
    def test_patient_copay_plan_requires_copay_cents(self, api, practice_admin_headers):
        """PRD §3.1: "The cost-sharing fields are plan-conditional: `copay_cents`,
        the patient's flat copay in cents, is required if and only if `plan_type`
        is `COPAY`, and `coinsurance_pct`, a fractional rate greater than zero and
        at most one, is required if and only if `plan_type` is `COINSURANCE`;
        violations of these conditionals are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/patient_plan_conditional_fields_and_defaults
        """
        resp = api.create_patient(
            {"full_name": "NoCopay", "plan_type": "COPAY"}, practice_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_coinsurance_patient_created_with_zeroed_computed_fields(
            self, api, practice_admin_headers):
        """PRD §3.1: "A newly registered patient starts with
        `outstanding_billed_cents` at zero and `education_gate_open` false."

        Design: Corner/entities/patient_plan_conditional_fields_and_defaults
        """
        resp = api.create_patient(
            create_patient_payload(full_name="Coins", plan_type="COINSURANCE",
                                   copay_cents=None, coinsurance_pct=0.25),
            practice_admin_headers)
        data = validate_success(resp, 201)
        assert_patient(data)
        assert data["outstanding_billed_cents"] == 0, (
            f"new patient outstanding_billed_cents must be 0, "
            f"got {data['outstanding_billed_cents']}"
        )
        assert data["education_gate_open"] is False, (
            f"new patient education_gate_open must be false, "
            f"got {data['education_gate_open']}"
        )


class TestMessageCreationDefaults:
    def test_message_created_with_system_defaults_and_default_clock(
            self, api, practice_admin_headers):
        """PRD §2.5: "At server startup, before any administrative intervention,
        the logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §3.3: "the server records `patient_id` from the caller's `X-User-ID`,
        stamps `received_at` from the logical clock, and opens the message in
        `RECEIVED` status with `urgency` and `category` unset,
        `billing_disposition` at `UNDETERMINED`, `reopen_count` at zero, and
        `sla_breached` false."
        PRD §2.4: "a unique, server-minted identifier formatted as a UUID, with
        no type prefix" (the `id` property).

        The logical clock is never set in this test, so received_at must equal
        the startup default instant.

        Design: Corner/entities/message_creation_system_fields_and_default_clock
        """
        scn = Scenario()
        patient = scn.add_patient(full_name="Pat")
        resp = api.create_portal_message(
            create_portal_message_payload(subject="Hello", body="First"),
            make_patient_headers(patient["id"]))
        data = validate_success(resp, 201)
        assert_portal_message(data)
        assert_same_instant(data["received_at"], LOGICAL_CLOCK_STARTUP_DEFAULT,
                            label="received_at (default logical clock)")
        assert data["status"] == "RECEIVED"
        assert data["billing_disposition"] == "UNDETERMINED"
        assert data["reopen_count"] == 0
        assert data["sla_breached"] is False
        assert data.get("urgency") is None, "urgency must be unset before triage"
        assert data.get("category") is None, "category must be unset before triage"
        assert data["patient_id"] == patient["id"]

    def test_get_missing_message_returns_not_found(self, api, practice_admin_headers):
        """PRD §2.8: "the server validates existence in a strict left-to-right
        order and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
        — message, patient, staff member, pool, coverage window, on-call shift,
        delegation grant, consent record, claim, escalation, or education notice —
        that does not correspond to an existing resource."

        Design: Corner/entities/message_get_not_found_returns_404
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        resp = api.get_portal_message(MISSING_UUID, make_triage_nurse_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_error_envelope_shape_for_not_found(self, api, practice_admin_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_for_not_found
        """
        resp = api.get_patient(MISSING_UUID, practice_admin_headers)
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("response_type") == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str)
        error_data = body["data"]
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.6: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order and reports the first failure."

        Header presence is tier 1, ahead of existence (tier 5), so a request for
        a nonexistent message without headers must surface the header error.

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.get_portal_message(MISSING_UUID, headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRolePermissions:
    def test_patient_cannot_triage(self, api, practice_admin_headers):
        """PRD §2.1: "Each operation is restricted to designated roles; a caller
        whose role is not authorized for the operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.3: "Classification belongs to the `TriageNurse`."

        The role check (tier 2) fires before existence (tier 5), so the bogus
        pool id in the payload is never reached.

        Design: Corner/rbac/patient_cannot_triage
        """
        scn = Scenario()
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        resp = api.triage_message(
            msg["id"],
            triage_payload("ROUTINE", "ADMINISTRATIVE", MISSING_UUID,
                           msg["version"]),
            make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_provider_cannot_adjudicate(self, api, practice_admin_headers):
        """PRD §2.1: "Each operation is restricted to designated roles; a caller
        whose role is not authorized for the operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "the table below fixes only the HTTP contract and the authorized
        roles" — record-adjudication is authorized for BillingSpecialist only.

        Design: Corner/rbac/provider_cannot_adjudicate
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        resp = api.record_adjudication(
            MISSING_UUID, {"outcome": "PAID"},
            make_provider_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_billing_cannot_cosign(self, api, practice_admin_headers):
        """PRD §2.1: "Each operation is restricted to designated roles; a caller
        whose role is not authorized for the operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.4: "The cosign decision itself belongs to a `Provider` acting on
        a `PENDING_COSIGN` message".

        Design: Corner/rbac/billing_cannot_cosign
        """
        scn = Scenario()
        biller = scn.add_staff("BILLING_SPECIALIST", "Bill S")
        resp = api.cosign_message(
            MISSING_UUID, {"action": "COSIGN"},
            make_billing_specialist_headers(biller["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_role_staff_type_mismatch_rejected(self, api, practice_admin_headers):
        """PRD §2.1: "the referenced `StaffMember` must exist and its
        `staff_type` must agree with the role — `TriageNurse` requires `NURSE`,
        `FrontDesk` requires `FRONT_DESK`, `Provider` requires `PROVIDER`, and
        `BillingSpecialist` requires `BILLING_SPECIALIST`. A disagreement is
        rejected with `ERR_ROLE_STAFF_MISMATCH`."

        A PROVIDER staff id presented under the TriageNurse role is rejected.

        Design: Corner/rbac/role_staff_type_mismatch_rejected
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat")
        msg = scn.send_message(patient, subject="S", body="B")
        resp = api.triage_message(
            msg["id"],
            triage_payload("ROUTINE", "CLINICAL", pool["id"], msg["version"]),
            make_triage_nurse_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_STAFF_MISMATCH)


class TestPatientOwnership:
    def test_patient_cannot_read_others_message(self, api, practice_admin_headers):
        """PRD §2.1: "ownership checks on any resource that references a patient
        compare the resource's `patient_id` field to `X-User-ID`, and a mismatch
        is rejected with `ERR_PATIENT_OWNERSHIP_MISMATCH`."
        PRD §2.1: "A `Patient` caller reading a single record may only read their
        own record — their own patient profile, their own messages, their own
        consent records, their own claims, their own education notices".

        Design: Corner/rbac/patient_cannot_read_others_message
        """
        scn = Scenario()
        pat_a = scn.add_patient(full_name="Pat A")
        pat_b = scn.add_patient(full_name="Pat B")
        msg = scn.send_message(pat_a, subject="S", body="B")
        resp = api.get_portal_message(msg["id"], make_patient_headers(pat_b["id"]))
        validate_error(resp, ApiErrorId.ERR_PATIENT_OWNERSHIP_MISMATCH)

    def test_patient_list_requires_own_patient_filter(
            self, api, practice_admin_headers):
        """PRD §2.1: "when calling a list endpoint must pass a `patient_id`
        filter equal to their own `X-User-ID`; omitting it or naming another
        patient is likewise rejected with `ERR_PATIENT_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/patient_list_requires_own_patient_filter
        """
        scn = Scenario()
        pat_a = scn.add_patient(full_name="Pat A")
        pat_b = scn.add_patient(full_name="Pat B")
        scn.send_message(pat_a, subject="A", body="a")
        scn.send_message(pat_b, subject="B", body="b")

        resp_no_filter = api.list_portal_messages(make_patient_headers(pat_a["id"]))
        validate_error(resp_no_filter, ApiErrorId.ERR_PATIENT_OWNERSHIP_MISMATCH)

        resp_other = api.list_portal_messages(
            make_patient_headers(pat_a["id"]), params={"patient_id": pat_b["id"]})
        validate_error(resp_other, ApiErrorId.ERR_PATIENT_OWNERSHIP_MISMATCH)

        resp_own = api.list_portal_messages(
            make_patient_headers(pat_a["id"]), params={"patient_id": pat_a["id"]})
        data, meta = validate_paginated(resp_own)
        assert meta["total_count"] == 1, (
            f"own-filtered list must contain exactly the caller's message, "
            f"got total_count {meta['total_count']}"
        )
        assert all(item["patient_id"] == pat_a["id"] for item in data)
