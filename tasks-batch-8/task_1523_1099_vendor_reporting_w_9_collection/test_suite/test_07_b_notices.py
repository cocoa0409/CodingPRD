"""B-notice stage determination and stage-dependent resolution rules."""
import pytest

from test_helpers import (
    ADMIN,
    IRS,
    SPEC,
    ApiErrorId,
    assert_b_notice,
    create_b_notice,
    create_matched_vendor,
    create_mismatched_vendor,
    create_vendor,
    get_vendor,
    make_tax_admin_headers,
    make_tax_specialist_headers,
    record_match,
    setup_vendor_with_first_and_second_notice,
    submit_w9,
    validate_error,
    validate_success,
)


class TestSecondBNoticeResolution:
    def test_second_b_notice_resolution_rules(self, api):
        """PRD §3.8: "A `SECOND` notice may be resolved only by a `TaxAdmin`
        presenting `resolution_code` of `IRS_SSA_VALIDATION`; a `TaxSpecialist` may
        never resolve a `SECOND` notice, and any attempt missing the administrator
        role or the validation code is rejected with
        `ERR_B_NOTICE_NOT_RESOLVABLE`."
        PRD §3.8: "Resolution stamps `resolved_by_user_id` with the caller, moves the
        notice to `RESOLVED`, recomputes the vendor's `b_notice_stage` as the highest
        stage among its remaining `OPEN` notices (`NONE` when none remain), and
        recomputes the `backup_withholding_flag` from the rule in §3.2."
        PRD §3.8: "The notice's `stage` is computed at creation and is `SECOND` when
        either of two conditions holds: another B-notice already exists for the same
        vendor whose `notice_year` falls within the closed interval from two years
        before the new notice's year through the new notice's year and which was
        created earlier than the new notice; or the vendor's `mismatch_count_3yr` is
        at least two at creation time."

        Design: Corner/validations/c_second_b_notice_resolution_rules
        """
        vendor, first_notice, second_notice = setup_vendor_with_first_and_second_notice(
            legal_name="BN V"
        )
        assert first_notice["stage"] == "FIRST"
        # The 2024 notice sits in [2025 - 2, 2025] and was created earlier.
        assert second_notice["stage"] == "SECOND"

        # A TaxSpecialist may never resolve a SECOND notice.
        specialist_attempt = api.resolve_b_notice(
            second_notice["id"], {}, make_tax_specialist_headers("spec-1")
        )
        validate_error(specialist_attempt, ApiErrorId.ERR_B_NOTICE_NOT_RESOLVABLE, 409)

        resolved = validate_success(
            api.resolve_b_notice(
                second_notice["id"],
                {"resolution_code": "IRS_SSA_VALIDATION"},
                make_tax_admin_headers("admin-1"),
            ),
            200,
        )
        assert_b_notice(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == "admin-1"

        # The FIRST notice is still OPEN, so the vendor falls back to FIRST.
        assert get_vendor(vendor["id"], ADMIN)["b_notice_stage"] == "FIRST"

    def test_second_b_notice_rejects_wrong_resolution_code(self, api):
        """PRD §3.8: "A `SECOND` notice may be resolved only by a `TaxAdmin`
        presenting `resolution_code` of `IRS_SSA_VALIDATION`; a `TaxSpecialist` may
        never resolve a `SECOND` notice, and any attempt missing the administrator
        role or the validation code is rejected with
        `ERR_B_NOTICE_NOT_RESOLVABLE`."

        Design: Corner/validations/c_second_b_notice_resolution_rules
        """
        vendor, _first, second_notice = setup_vendor_with_first_and_second_notice(
            legal_name="BN2 V"
        )
        assert second_notice["stage"] == "SECOND"

        # Right role, wrong code.
        wrong_code = api.resolve_b_notice(
            second_notice["id"],
            {"resolution_code": "PHONE_CALL"},
            make_tax_admin_headers("admin-1"),
        )
        validate_error(wrong_code, ApiErrorId.ERR_B_NOTICE_NOT_RESOLVABLE, 409)

        # Right role, missing code.
        missing_code = api.resolve_b_notice(
            second_notice["id"], {}, make_tax_admin_headers("admin-1")
        )
        validate_error(missing_code, ApiErrorId.ERR_B_NOTICE_NOT_RESOLVABLE, 409)

        after = validate_success(api.get_b_notice(second_notice["id"], ADMIN), 200)
        assert after["status"] == "OPEN"


class TestFirstBNoticeResolution:
    def test_first_b_notice_resolved_by_fresh_match(self, api):
        """PRD §3.8: "A `FIRST` notice — which either a `TaxSpecialist` or a
        `TaxAdmin` may resolve — requires the vendor's `tin_match_status` to be
        `MATCHED` by virtue of a W-9 submission created after the notice; anything
        else is rejected with `ERR_B_NOTICE_NOT_RESOLVABLE`."

        Design: Corner/validations/c_first_b_notice_resolved_by_fresh_match
        """
        vendor, _w1 = create_matched_vendor(legal_name="FirstBN V", tin="111999111")
        notice = create_b_notice(vendor["id"], notice_year=2025)
        assert notice["stage"] == "FIRST"

        # A second W-9 exists but is still PENDING — no post-notice MATCHED W-9 yet.
        w2 = submit_w9(vendor["id"], submitted_tin="111999111", submitted_tin_type="SSN",
                       signature_name="F2")
        early = api.resolve_b_notice(notice["id"], {}, make_tax_specialist_headers("spec-1"))
        validate_error(early, ApiErrorId.ERR_B_NOTICE_NOT_RESOLVABLE, 409)

        record_match(w2["id"], "MATCHED")
        resolved = validate_success(
            api.resolve_b_notice(notice["id"], {}, make_tax_specialist_headers("spec-1")), 200
        )
        assert resolved["status"] == "RESOLVED"

        vendor_after = get_vendor(vendor["id"])
        assert vendor_after["b_notice_stage"] == "NONE"
        assert vendor_after["backup_withholding_flag"] is False

    def test_first_b_notice_rejected_when_vendor_still_mismatched(self, api):
        """PRD §3.8: "A `FIRST` notice — which either a `TaxSpecialist` or a
        `TaxAdmin` may resolve — requires the vendor's `tin_match_status` to be
        `MATCHED` by virtue of a W-9 submission created after the notice; anything
        else is rejected with `ERR_B_NOTICE_NOT_RESOLVABLE`."

        Design: Corner/validations/c_first_b_notice_resolved_by_fresh_match
        """
        # The vendor's only W-9 MISMATCHED before the notice existed; the notice
        # cannot resolve off the pre-notice (non-MATCHED) posture.
        vendor, _w1 = create_mismatched_vendor(
            legal_name="StillBad V", tin="222111222", reason_code="IRS_CODE_1"
        )
        notice = create_b_notice(vendor["id"], notice_year=2025)
        assert notice["stage"] == "FIRST"

        resp = api.resolve_b_notice(notice["id"], {}, make_tax_specialist_headers("spec-1"))
        validate_error(resp, ApiErrorId.ERR_B_NOTICE_NOT_RESOLVABLE, 409)

        after = validate_success(api.get_b_notice(notice["id"], ADMIN), 200)
        assert after["status"] == "OPEN"
