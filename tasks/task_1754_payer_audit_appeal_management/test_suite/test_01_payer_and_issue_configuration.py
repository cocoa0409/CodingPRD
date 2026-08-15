"""Payer registration, appeal-track derivation, suspension guardrails, the
denial issue taxonomy, and concurrent-audit capacity."""
from test_helpers import (
    ApiErrorId,
    create_audit_case_payload,
    create_issue_code_payload,
    create_payer,
    create_payer_payload,
    is_valid_uuid,
    reactivate_payer,
    suspend_payer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
HIM = TEST_USERS["him_headers"]
READER = TEST_USERS["reader_headers"]


class TestPayerCreation:
    def test_rac_payer_derives_medicare_track_and_active_status(self, api):
        """PRD §3.1: "From `payer_type` the system derives the payer's
        `appeal_track`: an `RAC` payer follows the `MEDICARE` track, and a
        `COMMERCIAL` payer follows the `COMMERCIAL` track."
        PRD §3.1: "A newly created payer starts with `status` `ACTIVE`."

        Design: Corner/entities/payer_created_with_derived_track_and_defaults
        """
        rac = validate_success(api.create_payer(
            create_payer_payload(name="RAC-1", payer_type="RAC"), ADMIN), 201)
        assert rac["appeal_track"] == "MEDICARE"
        assert rac["status"] == "ACTIVE"
        assert rac["version"] == 1

        com = validate_success(api.create_payer(
            create_payer_payload(name="COM-1", payer_type="COMMERCIAL"),
            ADMIN), 201)
        assert com["appeal_track"] == "COMMERCIAL"
        assert com["status"] == "ACTIVE"

    def test_payer_create_ignores_client_supplied_system_fields(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one with every modification of the resource, including
        mutations driven by cascading side effects."

        Design: Corner/entities/payer_system_fields_input_ignored
        """
        payload = create_payer_payload(name="P1", payer_type="RAC")
        payload["id"] = "11111111-1111-1111-1111-111111111111"
        payload["version"] = 99
        payer = validate_success(api.create_payer(payload, ADMIN), 201)
        assert payer["id"] != "11111111-1111-1111-1111-111111111111", (
            "The server mints its own id")
        assert is_valid_uuid(payer["id"])
        assert payer["version"] == 1, "A newly created payer starts at version 1"


class TestPayerSuspension:
    def test_suspended_payer_rejects_new_case_until_reactivated(self, api):
        """PRD §3.1: "A `RevenueCycleAdmin` may suspend a payer — moving it from
        `ACTIVE` to `SUSPENDED` — which blocks the intake of any new audit case
        for that payer (`ERR_PAYER_SUSPENDED`, §3.2) while leaving existing
        cases untouched; reactivation returns the payer from `SUSPENDED` to
        `ACTIVE`."

        Design: Corner/state_machines/suspended_payer_rejects_new_case
        """
        payer = create_payer(name="P1")
        suspended = suspend_payer(payer["id"])
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_audit_case(
            create_audit_case_payload(payer["id"]), HIM)
        validate_error(resp, ApiErrorId.ERR_PAYER_SUSPENDED)

        reactivated = reactivate_payer(payer["id"])
        assert reactivated["status"] == "ACTIVE"
        case = validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"]), HIM), 201)
        assert is_valid_uuid(case["id"])


class TestPayerReadAccess:
    def test_any_authenticated_role_can_list_payers(self, api, reader_headers):
        """PRD §2.1: "`Any`, which denotes that every read endpoint is open to
        any authenticated caller regardless of role."

        Design: Corner/rbac/any_role_read_access_positive
        """
        create_payer(name="P1")
        _data, meta = validate_paginated(api.list_payers(reader_headers))
        assert meta["total_count"] == 1


class TestIssueCodes:
    def test_issue_code_created_active(self, api):
        """PRD §3.1: "Every issue code is created with `active` set to true,
        and the platform offers no deactivation endpoint — a code, once
        created, remains active permanently."

        Design: Corner/entities/issue_code_created_with_defaults
        """
        issue = validate_success(api.create_issue_code(
            create_issue_code_payload("MED_NEC", "CLINICAL",
                                      "Medical necessity"), ADMIN), 201)
        assert issue["active"] is True

    def test_duplicate_issue_code_rejected(self, api):
        """PRD §3.1: "The `code` value must be unique across all issue codes;
        reusing an existing code is rejected with `ERR_DUPLICATE_ISSUE_CODE`
        (HTTP 409)."

        Design: Corner/validations/duplicate_issue_code_rejected
        """
        validate_success(api.create_issue_code(
            create_issue_code_payload("MED_NEC", "CLINICAL",
                                      "Medical necessity"), ADMIN), 201)
        resp = api.create_issue_code(
            create_issue_code_payload("MED_NEC", "TECHNICAL", "Duplicate"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ISSUE_CODE)


class TestConcurrentAuditCapacity:
    def test_cases_up_to_cap_minus_one_accepted(self, api):
        """PRD §3.2: "the system counts the payer's cases whose status is
        anything other than `CLOSED`, and when that count is already greater
        than or equal to the payer's `concurrent_audit_cap`, intake is rejected
        with `ERR_CONCURRENT_AUDIT_CAP` (HTTP 409). The boundary is exact: a
        payer whose open-case count equals its cap is rejected, while a count
        one below the cap is allowed."

        Design: Difficulty/resource_temporal_overlap/payer_concurrent_audit_capacity
        """
        payer = create_payer(name="P1", concurrent_audit_cap=2)
        c1 = validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"], "RAC_COMPLEX"), HIM), 201)
        c2 = validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"], "RAC_AUTOMATED"), HIM), 201)
        assert is_valid_uuid(c1["id"]) and is_valid_uuid(c2["id"]), (
            "open counts 0 and 1 both pass under cap 2")

    def test_case_at_cap_rejected(self, api):
        """PRD §3.2: "the system counts the payer's cases whose status is
        anything other than `CLOSED`, and when that count is already greater
        than or equal to the payer's `concurrent_audit_cap`, intake is rejected
        with `ERR_CONCURRENT_AUDIT_CAP` (HTTP 409). The boundary is exact: a
        payer whose open-case count equals its cap is rejected, while a count
        one below the cap is allowed."

        Design: Difficulty/resource_temporal_overlap/payer_concurrent_audit_capacity
        """
        payer = create_payer(name="P1", concurrent_audit_cap=2)
        validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"], "RAC_COMPLEX"), HIM), 201)
        validate_success(api.create_audit_case(
            create_audit_case_payload(payer["id"], "RAC_AUTOMATED"), HIM), 201)
        resp = api.create_audit_case(
            create_audit_case_payload(payer["id"], "TARGETED_PROBE"), HIM)
        validate_error(resp, ApiErrorId.ERR_CONCURRENT_AUDIT_CAP)
