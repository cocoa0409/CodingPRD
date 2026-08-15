"""Vendor onboarding, master data, W-9 intake, TIN matching, and vendor OCC."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    NON_EXISTENT_UUID,
    SPEC,
    ApiErrorId,
    assert_vendor,
    assert_w9_submission,
    create_matched_vendor,
    create_merge_request,
    create_mergeable_pair,
    create_vendor,
    create_vendor_payload,
    create_w9_submission_payload,
    get_vendor,
    make_ap_clerk_headers,
    make_tax_admin_headers,
    make_vendor_portal_headers,
    record_match,
    submit_w9,
    validate_error,
    validate_success,
)


class TestVendorCreation:
    def test_vendor_create_defaults_and_system_fields(self, api):
        """PRD §3.2: "A fresh vendor starts `ACTIVE`, with `tin_match_status` at
        `NOT_SUBMITTED`, `b_notice_stage` at `NONE`, `mismatch_count_3yr` at zero,
        and `withholding_balance_cents` at zero."
        PRD §3.2: "The `e_delivery_consent` flag, defaulting to false, records the
        vendor's consent to electronic Copy B delivery."
        PRD §3.2: "The `backup_withholding_flag` is computed, never set directly: it
        is true exactly when the vendor's `tin_match_status` is `MISMATCHED` or its
        `b_notice_stage` is `SECOND`, and it gates per-payment withholding at posting
        time."

        Design: Corner/entities/c_vendor_create_defaults_and_system_fields
        """
        resp = api.create_vendor(
            create_vendor_payload(
                legal_name="Fresh V",
                entity_classification="TRUST_ESTATE",
                address_line1="1 Z",
                address_city="Boerne",
                address_state="TX",
                address_postal="78006",
            ),
            CLERK,
        )
        data = validate_success(resp, 201)
        assert_vendor(data)
        assert data["status"] == "ACTIVE"
        assert data["tin_match_status"] == "NOT_SUBMITTED"
        assert data["b_notice_stage"] == "NONE"
        assert data["backup_withholding_flag"] is False
        assert data["mismatch_count_3yr"] == 0
        assert data["withholding_balance_cents"] == 0
        assert data["e_delivery_consent"] is False
        # No TIN supplied at onboarding: populated later from a matched W-9.
        assert data.get("tin") is None
        assert data["version"] == 1

    def test_vendor_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.7: "Malformed bodies, unknown fields, invalid enum members, missing
        required fields, and bad date ranges are rejected with `ERR_INVALID_REQUEST`
        wherever they arise in the ladder."
        PRD §3.2: "An `APClerk` (or a `TaxAdmin`) onboards a vendor by supplying its
        `legal_name` exactly as it should appear on filings, its
        `entity_classification`, and its mailing address..."

        Design: Corner/entities/c_vendor_create_missing_required_returns_invalid_request
        """
        payload = {
            "legal_name": "NoClass",
            "address_line1": "2 Z",
            "address_city": "Boerne",
            "address_state": "TX",
            "address_postal": "78006",
        }
        resp = api.create_vendor(payload, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        # Nothing persisted: the vendor list remains empty.
        list_resp = api.list_vendors(CLERK, params={})
        body = list_resp.json()
        assert body["meta"]["total_count"] == 0

    def test_vendor_get_not_found_returns_404(self, api):
        """PRD §2.7: "Every identifier in the path must resolve to an existing
        resource, validated left to right (`ERR_NOT_FOUND`)."

        Design: Corner/entities/c_vendor_get_not_found_returns_404
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestW9Intake:
    def test_w9_invalid_tin_format_returns_422(self, api):
        """PRD §3.3: "The submission captures `submitted_legal_name` (the name exactly
        as written on the form), `submitted_tin` (exactly nine ASCII digits, enforced
        as `ERR_INVALID_TIN_FORMAT`), `submitted_tin_type` (`SSN` or `EIN`), and
        `signature_name` as the signer's attestation."

        Design: Corner/entities/c_w9_invalid_tin_format_returns_422
        """
        vendor = create_vendor(legal_name="Tin V")
        resp = api.create_w9_submission(
            vendor["id"],
            create_w9_submission_payload(
                submitted_legal_name="Tin V",
                submitted_tin="12345",
                submitted_tin_type="SSN",
                signature_name="T",
            ),
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIN_FORMAT, 422)
        # No state change: the vendor still sits at NOT_SUBMITTED.
        assert get_vendor(vendor["id"])["tin_match_status"] == "NOT_SUBMITTED"

    def test_w9_result_on_decided_submission_returns_409(self, api):
        """PRD §3.3: "The submission must still be `PENDING` (otherwise
        `ERR_INVALID_STATE_TRANSITION`), the vendor must be `ACTIVE` (otherwise
        `ERR_VENDOR_NOT_ACTIVE`), and a `MISMATCHED` result delivered without
        `mismatch_reason_code` is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/c_w9_result_on_decided_submission_returns_409
        """
        vendor, w9 = create_matched_vendor(legal_name="Decided V", tin="963963963")
        resp = api.record_match_result(
            w9["id"],
            {"match_result": "MISMATCHED", "mismatch_reason_code": "IRS_CODE_1"},
            IRS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_vendor(vendor["id"])
        assert after["tin_match_status"] == "MATCHED"
        assert after["mismatch_count_3yr"] == 0

    def test_vendor_tin_status_resubmission_cycle_full_loop(self, api):
        """PRD §3.3: "A new submission starts with `match_result` at `PENDING`, and
        its creation moves the vendor's `tin_match_status` into `PENDING_MATCH` —
        whether the vendor was previously `NOT_SUBMITTED`, `MATCHED`, or
        `MISMATCHED`."
        PRD §3.3: "A `MISMATCHED` result moves the vendor to `MISMATCHED`, increments
        `mismatch_count_3yr` by one, sets the `backup_withholding_flag` to true, and
        copies the supplied `mismatch_reason_code` onto the submission."

        Design: Difficulty/non_linear_state_machine/vendor_tin_status_resubmission_cycle
        """
        vendor = create_vendor(legal_name="Cycle V", entity_classification="PARTNERSHIP")
        assert vendor["tin_match_status"] == "NOT_SUBMITTED"

        w1 = submit_w9(vendor["id"], submitted_tin="777777777", submitted_tin_type="EIN",
                       signature_name="C")
        assert get_vendor(vendor["id"])["tin_match_status"] == "PENDING_MATCH"

        record_match(w1["id"], "MISMATCHED", mismatch_reason_code="IRS_CODE_1")
        after_mismatch = get_vendor(vendor["id"])
        assert after_mismatch["tin_match_status"] == "MISMATCHED"
        assert after_mismatch["backup_withholding_flag"] is True
        assert after_mismatch["mismatch_count_3yr"] == 1

        w2 = submit_w9(vendor["id"], submitted_tin="777777777", submitted_tin_type="EIN",
                       signature_name="C")
        # The cycle: MISMATCHED -> PENDING_MATCH on re-submission.
        assert get_vendor(vendor["id"])["tin_match_status"] == "PENDING_MATCH"

        record_match(w2["id"], "MATCHED")
        final = get_vendor(vendor["id"])
        assert final["tin_match_status"] == "MATCHED"
        assert final["mismatch_count_3yr"] == 1
        assert final["backup_withholding_flag"] is False
        assert final["tin"] == "777777777"

    def test_vendor_tin_status_cycle_matched_result_completes_identity(self, api):
        """PRD §3.3: "A `MATCHED` result completes the vendor's identity record: the
        vendor's `tin`, `tin_type`, and `legal_name` are overwritten with
        `submitted_tin`, `submitted_tin_type`, and `submitted_legal_name`, the
        vendor's `tin_match_status` becomes `MATCHED`, and the
        `backup_withholding_flag` is recomputed — true only if the vendor's
        `b_notice_stage` is `SECOND`."

        Design: Difficulty/non_linear_state_machine/vendor_tin_status_resubmission_cycle
        """
        vendor = create_vendor(legal_name="Original Name", entity_classification="PARTNERSHIP")
        w9 = submit_w9(
            vendor["id"],
            submitted_legal_name="Corrected Legal Name",
            submitted_tin="777777777",
            submitted_tin_type="EIN",
            signature_name="C",
        )
        record_match(w9["id"], "MATCHED")
        after = get_vendor(vendor["id"])
        assert after["tin"] == "777777777"
        assert after["tin_type"] == "EIN"
        assert after["legal_name"] == "Corrected Legal Name"
        assert after["tin_match_status"] == "MATCHED"
        assert after["backup_withholding_flag"] is False


class TestVendorOcc:
    def test_occ_vendor_patch_stale(self, api):
        """PRD §2.8: "Updating a vendor master record requires the request to carry
        `expected_vendor_version`, the client-side copy of the vendor's `version`
        from its last read; if the vendor's current `version` has advanced past the
        supplied value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412),
        and the client must re-read before retrying."
        PRD §3.2: "A successful update increments the vendor's `version` by one."

        Design: Corner/cross_cutting_layers/c_occ_vendor_patch_stale
        """
        vendor = create_vendor(legal_name="Occ V")
        observed_version = vendor["version"]

        first = api.patch_vendor(
            vendor["id"],
            {"e_delivery_consent": True, "expected_vendor_version": observed_version},
            CLERK,
        )
        first_data = validate_success(first, 200)
        assert first_data["version"] == observed_version + 1
        assert first_data["e_delivery_consent"] is True

        stale = api.patch_vendor(
            vendor["id"],
            {"address_city": "Nowhere", "expected_vendor_version": observed_version},
            CLERK,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_vendor(vendor["id"])["address_city"] == vendor["address_city"]


class TestVendorPortalScope:
    def test_vendorportal_scope_enforced(self, api):
        """PRD §2.1: "When `X-User-Role` is `VendorPortal`, `X-User-ID` is the `id`
        of the acting `Vendor`; ownership checks on any resource that references a
        `Vendor` compare the resource's foreign-key field to `X-User-ID`, so a
        portal caller may submit a W-9 only for its own vendor record and may read
        only its own vendor record — any other vendor id in the path yields
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/c_vendorportal_scope_enforced
        """
        vendor_a = create_vendor(legal_name="Portal A")
        vendor_b = create_vendor(legal_name="Portal B")

        own = api.create_w9_submission(
            vendor_a["id"],
            create_w9_submission_payload(
                submitted_legal_name="Portal A",
                submitted_tin="444000444",
                submitted_tin_type="SSN",
                signature_name="PA",
            ),
            make_vendor_portal_headers(vendor_a["id"]),
        )
        own_data = validate_success(own, 201)
        assert_w9_submission(own_data)
        assert own_data["vendor_id"] == vendor_a["id"]

        cross = api.create_w9_submission(
            vendor_b["id"],
            create_w9_submission_payload(
                submitted_legal_name="Portal B",
                submitted_tin="555000555",
                submitted_tin_type="SSN",
                signature_name="PB",
            ),
            make_vendor_portal_headers(vendor_a["id"]),
        )
        validate_error(cross, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestVendorMergeBasics:
    def test_merge_self_returns_422(self, api):
        """PRD §3.9: "Naming the same vendor on both sides is rejected at request
        time with `ERR_SELF_MERGE`, and unknown vendor ids draw `ERR_NOT_FOUND`."

        Design: Corner/validations/c_merge_self_returns_422
        """
        vendor, _w9 = create_matched_vendor(legal_name="Self V", tin="123456789")
        resp = api.create_merge_request(
            {
                "source_vendor_id": vendor["id"],
                "target_vendor_id": vendor["id"],
                "reason": "self",
            },
            make_ap_clerk_headers("clerk-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_MERGE, 422)
        # No merge request persisted.
        listed = api.list_merge_requests(CLERK, params={})
        assert listed.json()["meta"]["total_count"] == 0

    def test_merge_tin_mismatch_returns_409(self, api):
        """PRD §3.9: "their TINs must be equal and both non-null
        (`ERR_TIN_MISMATCH_ON_MERGE`); and the source must have no W-9 submission
        awaiting a match (`ERR_VENDOR_HAS_OPEN_OBLIGATIONS`)."

        Design: Corner/validations/c_merge_tin_mismatch_returns_409
        """
        source, _w1 = create_matched_vendor(legal_name="Tin S", tin="123456789")
        target, _w2 = create_matched_vendor(
            legal_name="Tin G", tin="987654321", tin_type="EIN",
            entity_classification="C_CORP",
        )
        merge_request = create_merge_request(source["id"], target["id"], requester_id="clerk-1")

        resp = api.approve_merge_request(merge_request["id"], make_tax_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_TIN_MISMATCH_ON_MERGE, 409)

        after = validate_success(api.get_merge_request(merge_request["id"], CLERK), 200)
        assert after["status"] == "PENDING"
        assert get_vendor(source["id"], ADMIN)["status"] == "ACTIVE"
        assert get_vendor(target["id"], ADMIN)["status"] == "ACTIVE"

    def test_sod_merge_requester_cannot_approve(self, api):
        """PRD §2.11: "the `TaxAdmin` who approves a vendor merge, recorded as
        `reviewed_by_user_id`, must not be the `APClerk` recorded as
        `requested_by_user_id`. Any of these collisions is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/c_sod_merge_requester_cannot_approve
        """
        source, target, merge_request = create_mergeable_pair(
            tin="123456789", requester_id="clerk-9"
        )
        # Same user id on both sides of the wall, even though the role is correct.
        resp = api.approve_merge_request(merge_request["id"], make_tax_admin_headers("clerk-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        after = validate_success(api.get_merge_request(merge_request["id"], CLERK), 200)
        assert after["status"] == "PENDING"
        assert get_vendor(source["id"], ADMIN)["status"] == "ACTIVE"
        assert get_vendor(target["id"], ADMIN)["status"] == "ACTIVE"

    def test_merged_vendor_terminal_lockdown(self, api):
        """PRD §3.2: "Updating a vendor that has been `MERGED` or `DEACTIVATED` is
        rejected with `ERR_VENDOR_NOT_ACTIVE`."
        PRD §3.3: "The vendor must be `ACTIVE`; submissions against a merged or
        deactivated vendor are rejected with `ERR_VENDOR_NOT_ACTIVE`."

        Design: Corner/state_machines/c_merged_vendor_terminal_lockdown
        """
        source, target, merge_request = create_mergeable_pair(
            tin="123456789", requester_id="clerk-1"
        )
        approve = api.approve_merge_request(
            merge_request["id"], make_tax_admin_headers("admin-1")
        )
        validate_success(approve, 200)

        merged_source = get_vendor(source["id"], ADMIN)
        assert merged_source["status"] == "MERGED"
        fresh_version = merged_source["version"]

        patch = api.patch_vendor(
            source["id"],
            {"address_city": "Nowhere", "expected_vendor_version": fresh_version},
            ADMIN,
        )
        validate_error(patch, ApiErrorId.ERR_VENDOR_NOT_ACTIVE, 409)

        w9 = api.create_w9_submission(
            source["id"],
            create_w9_submission_payload(
                submitted_legal_name="Lock S",
                submitted_tin="123456789",
                submitted_tin_type="SSN",
                signature_name="S",
            ),
            CLERK,
        )
        validate_error(w9, ApiErrorId.ERR_VENDOR_NOT_ACTIVE, 409)
